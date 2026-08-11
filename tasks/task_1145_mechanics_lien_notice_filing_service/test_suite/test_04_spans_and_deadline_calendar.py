"""Furnishing spans, furnishing-date variants, and the deadline calendar
computed read (PRD §2.6, §3.3)."""
from test_helpers import (
    ApiErrorId,
    create_company,
    create_project,
    create_verified_project,
    get_deadline_calendar,
    make_customer_admin_headers,
    publish_rule,
    record_span,
    setup_locked_claim,
    supersede_rule,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client as api
from test_helpers.factories import create_furnishing_span_payload
from test_helpers.test_users import TEST_USERS

_PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
_OPS_AGENT = TEST_USERS["ops_agent_headers"]


def test_span_end_before_start_rejected():
    """PRD §3.3: "an `end_date` earlier than the `start_date` is rejected with
    `ERR_SPAN_DATES_INVALID` (HTTP 422)."

    Design: Corner/validations/span_end_before_start_rejected
    """
    company = create_company(name="SD Co")
    project = create_project(company["id"], name="SD Job", contract_value_cents=100000)

    res = api.create_furnishing_span(
        create_furnishing_span_payload(
            project["id"],
            project["version"],
            start_date="2026-06-10",
            end_date="2026-06-01",
        ),
        make_customer_admin_headers(company["id"]),
    )
    validate_error(res, ApiErrorId.ERR_SPAN_DATES_INVALID)

    spans, meta = validate_paginated(
        api.list_project_furnishing_spans(project["id"], _OPS_AGENT)
    )
    assert meta["total_count"] == 0


def test_furnishing_span_same_kind_supersedes_prior():
    """PRD §3.3: "Creating a span supersedes any prior `ACTIVE` span of the same
    kind on the same project: the prior span moves to `SUPERSEDED` with its
    `updated_at` refreshed, the project's furnishing dates are recomputed over
    the remaining `ACTIVE` spans, and the project's `version` increments by one."

    Design: Corner/state_machines/furnishing_span_same_kind_supersedes_prior
    """
    company = create_company(name="FS Co")
    publish_rule()
    project = create_project(company["id"], name="FS Job", contract_value_cents=100000)
    first = record_span(project["id"], company["id"],
                        start_date="2026-05-02", end_date="2026-06-10")
    second = record_span(project["id"], company["id"],
                         start_date="2026-05-05", end_date="2026-06-15")
    assert second["status"] == "ACTIVE"

    spans, _meta = validate_paginated(
        api.list_project_furnishing_spans(project["id"], _OPS_AGENT)
    )
    by_id = {s["id"]: s for s in spans}
    assert by_id[first["id"]]["status"] == "SUPERSEDED"
    assert by_id[second["id"]]["status"] == "ACTIVE"

    calendar = get_deadline_calendar(project["id"])
    assert calendar["last_furnishing_date"] == "2026-06-15"
    assert calendar["filing_window_end"] == "2026-09-13"


def test_deadline_calendar_null_without_active_span():
    """PRD §3.3: "when a rule matches but the project has no `ACTIVE` span,
    `prelim_notice_deadline` is null; and when there is no last furnishing date,
    `filing_window_end` and `stop_notice_deadline` are null."

    Design: Corner/calculations/deadline_calendar_null_without_active_span
    """
    company = create_company(name="DC Co")
    rule = publish_rule()
    project = create_project(company["id"], name="DC Job", contract_value_cents=100000)

    calendar = get_deadline_calendar(project["id"])
    assert calendar["applied_rule_id"] == rule["id"]
    assert calendar["prelim_notice_deadline"] is None
    assert calendar["filing_window_end"] is None
    assert calendar["stop_notice_deadline"] is None
    assert calendar["last_furnishing_date"] is None


def test_deadline_calendar_computed_read_fields():
    """PRD §3.3: "It reports `applied_rule_id` — the effective rule chosen per
    §2.7 — together with three projected deadlines: `prelim_notice_deadline`,
    the `first_furnishing_date` plus the rule's `prelim_days` counted on its
    `prelim_day_basis`; `filing_window_end`, the `last_furnishing_date` plus the
    rule's `filing_window_days`; and `stop_notice_deadline`, the
    `last_furnishing_date` plus the rule's `stop_notice_days`."

    Design: Corner/endpoints/deadline_calendar_computed_read_fields
    """
    company = create_company(name="CR Co")
    rule = publish_rule()
    project = create_project(company["id"], name="CR Job", contract_value_cents=100000)
    record_span(project["id"], company["id"])

    calendar = get_deadline_calendar(project["id"])
    assert calendar["applied_rule_id"] == rule["id"]
    assert calendar["prelim_notice_deadline"] == "2026-05-22"
    assert calendar["filing_window_end"] == "2026-09-08"
    assert calendar["stop_notice_deadline"] == "2026-07-10"
    assert calendar["last_furnishing_date"] == "2026-06-10"
    assert calendar["last_furnishing_variant"] == "strict"


def test_locked_claim_pins_rule_version():
    """PRD §2.7: "The moment a lien claim is locked, however, it pins the
    effective rule's identity as `locked_rule_id`, and everything the claim
    derives from that rule — the filing window end, the foreclosure deadline,
    the bonding percentage, the interest rate — is governed by the pinned
    version forever, immune to later supersessions."
    PRD §3.3: "Locked or filed claims on the project ignore this projection
    entirely — they keep the rule pinned at lock."

    Design: Corner/calculations/locked_claim_pins_rule_version
    """
    ctx = setup_locked_claim(contract_value_cents=100000)
    claim = ctx["claim"]
    rule = ctx["rule"]
    assert claim["locked_rule_id"] == rule["id"]
    assert claim["filing_window_end"] == "2026-09-08"

    supersede_rule(rule["id"], rule["version"],
                   filing_window_days=30, effective_from="2026-02-01")

    claim_after = validate_success(api.get_lien_claim(claim["id"], _OPS_AGENT), 200)
    assert claim_after["locked_rule_id"] == rule["id"]
    assert claim_after["filing_window_end"] == "2026-09-08"

    calendar = get_deadline_calendar(ctx["project"]["id"])
    assert calendar["filing_window_end"] == "2026-07-10"


# ─── Furnishing-date variants (queue A: dual_variant_calc) ───────────

def _setup_strict_and_inclusive_projects():
    """One company; CA rule (counts_punch_list false) and NV rule (true);
    identical spans on a CA and an NV project."""
    company = create_company(name="Beta Sub", seed_balance_cents=10000000)
    publish_rule(state_code="CA")  # strict (counts_punch_list false by default)
    publish_rule(state_code="NV", counts_punch_list=True)  # inclusive

    projects = {}
    for state, name in (("CA", "CA Job"), ("NV", "NV Job")):
        project, _parties = create_verified_project(
            company["id"], name=name, state_code=state,
            county="Orange" if state == "CA" else "Clark",
            contract_value_cents=500000,
        )
        record_span(project["id"], company["id"],
                    start_date="2026-05-02", end_date="2026-06-10")
        record_span(project["id"], company["id"], span_kind="PUNCH_LIST",
                    start_date="2026-05-15", end_date="2026-06-20")
        projects[state] = project
    return company, projects


def test_strict_variant_ignores_punch_list_span():
    """PRD §3.3: "Under the strict variant — `counts_punch_list` false — only
    `BASE_CONTRACT` and `CHANGE_ORDER` spans are considered, and `PUNCH_LIST`
    and `WARRANTY` spans never extend last furnishing."

    Design: Difficulty/dual_variant_calc/punch_list_strict_vs_inclusive_last_furnishing
    """
    _company, projects = _setup_strict_and_inclusive_projects()

    calendar = get_deadline_calendar(projects["CA"]["id"])
    assert calendar["last_furnishing_date"] == "2026-06-10"
    assert calendar["filing_window_end"] == "2026-09-08"
    assert calendar["last_furnishing_variant"] == "strict"


def test_inclusive_variant_counts_punch_list_span():
    """PRD §3.3: "Under the inclusive variant — `counts_punch_list` true — the
    latest `end_date` across all `ACTIVE` spans wins, so identical inputs can
    yield a later date than strict."

    Design: Difficulty/dual_variant_calc/punch_list_strict_vs_inclusive_last_furnishing
    """
    _company, projects = _setup_strict_and_inclusive_projects()

    calendar = get_deadline_calendar(projects["NV"]["id"])
    assert calendar["last_furnishing_date"] == "2026-06-20"
    assert calendar["filing_window_end"] == "2026-09-18"
    assert calendar["last_furnishing_variant"] == "inclusive"
