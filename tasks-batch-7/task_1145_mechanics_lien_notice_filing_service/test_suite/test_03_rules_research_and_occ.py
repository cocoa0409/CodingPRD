"""Jurisdiction rule administration, project research gating, optimistic
concurrency, and the supersede cascade (PRD §2.7, §2.9, §3.1, §3.2)."""
from test_helpers import (
    ApiErrorId,
    advance_research,
    create_company,
    create_party,
    create_project,
    create_verified_project,
    get_company,
    get_notice,
    get_project,
    make_customer_admin_headers,
    order_notice,
    publish_rule,
    record_span,
    set_clock,
    supersede_rule,
    validate_error,
    validate_success,
)
from test_helpers import api_client as api
from test_helpers.factories import (
    create_furnishing_span_payload,
    create_jurisdiction_rule_payload,
)
from test_helpers.test_users import TEST_USERS

_PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
_OPS_AGENT = TEST_USERS["ops_agent_headers"]


# ─── Rule publication and supersession ───────────────────────────────

def test_duplicate_published_rule_rejected():
    """PRD §3.1: "If a `PUBLISHED` rule already exists for the pair, creation is
    rejected with `ERR_RULE_ALREADY_PUBLISHED` (HTTP 409) — the operator must
    supersede instead."

    Design: Corner/validations/duplicate_published_rule_rejected
    """
    publish_rule()
    res = api.create_jurisdiction_rule(
        create_jurisdiction_rule_payload(
            prelim_notice_required=False,
            prelim_days=10,
            filing_window_days=60,
            effective_from="2026-02-01",
        ),
        _PLATFORM_ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_RULE_ALREADY_PUBLISHED)


def test_rule_supersede_of_superseded_rejected():
    """PRD §3.1: "The addressed rule must currently be `PUBLISHED`, or the
    request fails with `ERR_RULE_NOT_PUBLISHED` (HTTP 409)" and "the addressed
    rule moves to `SUPERSEDED` and its `version` increments by one."

    Design: Corner/state_machines/rule_supersede_of_superseded_rejected
    """
    rule = publish_rule()
    supersede_rule(rule["id"], rule["version"], prelim_days=25,
                   effective_from="2026-02-01")
    old = validate_success(api.get_jurisdiction_rule(rule["id"], _PLATFORM_ADMIN), 200)
    assert old["status"] == "SUPERSEDED"
    assert old["version"] == rule["version"] + 1

    payload = create_jurisdiction_rule_payload(prelim_days=30,
                                               effective_from="2026-03-01")
    # state_code/project_type are not part of the supersede request body
    payload.pop("state_code")
    payload.pop("project_type")
    payload["expected_jurisdiction_rule_version"] = old["version"]
    res = api.supersede_jurisdiction_rule(rule["id"], payload, _PLATFORM_ADMIN)
    validate_error(res, ApiErrorId.ERR_RULE_NOT_PUBLISHED)


# ─── Research gating ─────────────────────────────────────────────────

def test_research_verify_blocked_by_unverified_parties():
    """PRD §3.2: "from `RESEARCHED` it moves to `VERIFIED` only when every
    required party is itself `VERIFIED` — the `OWNER` and the `GC` always, and
    the `LENDER` as well whenever the effective rule's `prelim_notice_required`
    is true — failing which the advance is rejected with
    `ERR_PARTIES_UNVERIFIED` (HTTP 409)."

    Design: Corner/state_machines/research_verify_blocked_by_unverified_parties
    """
    company = create_company(name="R Co")
    publish_rule()
    project = create_project(company["id"], name="R Job", contract_value_cents=1000)
    owner = create_party(project["id"], company["id"], "OWNER", verify=False)
    gc = create_party(project["id"], company["id"], "GC", verify=False,
                      legal_name="GC Inc", address="2 Main St")
    create_party(project["id"], company["id"], "LENDER", verify=True,
                 legal_name="Bank NA", address="3 Main St")

    project = advance_research(project["id"])
    assert project["research_status"] == "RESEARCHED"

    res = api.research_advance(project["id"], _OPS_AGENT)
    validate_error(res, ApiErrorId.ERR_PARTIES_UNVERIFIED)

    api.decide_party(owner["id"], {"outcome": "VERIFIED"}, _OPS_AGENT)
    api.decide_party(gc["id"], {"outcome": "VERIFIED"}, _OPS_AGENT)
    project = advance_research(project["id"])
    assert project["research_status"] == "VERIFIED"


def test_research_advance_on_verified_returns_409():
    """PRD §3.2: "Advancing a project that is already `VERIFIED` always fails
    with `ERR_RESEARCH_ALREADY_VERIFIED` (HTTP 409)."

    Design: Corner/state_machines/research_advance_on_verified_returns_409
    """
    company = create_company(name="RV Co")
    publish_rule(prelim_notice_required=False)
    project, _parties = create_verified_project(
        company["id"], name="RV Job", contract_value_cents=1000
    )
    assert project["research_status"] == "VERIFIED"

    res = api.research_advance(project["id"], _OPS_AGENT)
    validate_error(res, ApiErrorId.ERR_RESEARCH_ALREADY_VERIFIED)


# ─── Optimistic concurrency (PRD §2.9) ───────────────────────────────

def test_occ_span_create_stale_version():
    """PRD §2.9: "`POST /lien/furnishing-spans` requires
    `expected_project_version`, carrying the client's last observed `version` of
    the parent project." and "If the supplied value no longer matches the parent
    entity's current `version` — because another write has advanced that entity
    since the client last read it — the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412)"

    Design: Corner/cross_cutting_layers/occ_span_create_stale_version
    """
    company = create_company(name="OC1 Co")
    project = create_project(company["id"], name="OC1 Job", contract_value_cents=100)
    observed_version = project["version"]

    record_span(project["id"], company["id"])

    res = api.create_furnishing_span(
        create_furnishing_span_payload(
            project["id"],
            observed_version,
            span_kind="CHANGE_ORDER",
            start_date="2026-06-11",
            end_date="2026-06-20",
        ),
        make_customer_admin_headers(company["id"]),
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)

    current = get_project(project["id"])
    assert current["version"] == observed_version + 1


def test_occ_balance_adjust_stale_version():
    """PRD §2.9: "`POST /lien/companies/{id}/balance-adjustments` requires
    `expected_company_version`, carrying the client's last observed `version` of
    the company." and PRD §3.1: "A successful adjustment moves
    `prepaid_balance_cents` by exactly `amount_cents` and increments the
    company's `version` by one."

    Design: Corner/cross_cutting_layers/occ_balance_adjust_stale_version
    """
    company = create_company(name="OC2 Co")
    observed_version = company["version"]

    adjusted = validate_success(
        api.create_balance_adjustment(
            company["id"],
            {"amount_cents": 5000, "reason": "load",
             "expected_company_version": observed_version},
            _PLATFORM_ADMIN,
        ),
        201,
    )
    assert adjusted["prepaid_balance_cents"] == 5000
    assert adjusted["version"] == observed_version + 1

    res = api.create_balance_adjustment(
        company["id"],
        {"amount_cents": 5000, "reason": "load2",
         "expected_company_version": observed_version},
        _PLATFORM_ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)
    assert get_company(company["id"])["prepaid_balance_cents"] == 5000


# ─── Supersede cascade (queue A: transitive_cascade) ─────────────────

def _setup_draft_notice_before_supersede():
    """Verified CA project, DRAFT notice outstanding (deadline 2026-05-22 under
    the 20-day rule), clock advanced to 2026-05-16."""
    company = create_company(name="Cascade Co",
                             seed_balance_cents=10000000)
    rule = publish_rule()
    project, parties = create_verified_project(company["id"], name="Cascade Job")
    record_span(project["id"], company["id"])
    notice = order_notice(project["id"], company["id"], parties["OWNER"]["id"])
    set_clock("2026-05-16T00:00:00Z")
    return company, rule, project, notice


def test_rule_supersede_auto_expires_draft_notice():
    """PRD §3.1: "Any of those projects' `DRAFT` notice orders whose recomputed
    `service_deadline` now falls before the current clock date auto-transition
    from `DRAFT` to `EXPIRED`"
    PRD §2.7: "a `PlatformAdmin` supersedes the published rule, which creates a
    successor rule carrying the addressed rule's `state_code` and
    `project_type`, links the successor to its predecessor through
    `supersedes_rule_id`, and moves the predecessor to `SUPERSEDED`."

    Design: Difficulty/transitive_cascade/rule_supersede_expires_draft_notice_chain
    """
    company, rule, project, notice = _setup_draft_notice_before_supersede()

    successor = supersede_rule(rule["id"], rule["version"],
                               prelim_days=10, effective_from="2026-05-10")
    assert successor["supersedes_rule_id"] == rule["id"]
    assert successor["status"] == "PUBLISHED"

    # recomputed deadline 2026-05-12 < clock 2026-05-16: next read expires it
    notice_after = get_notice(notice["id"])
    assert notice_after["status"] == "EXPIRED"

    old_rule = validate_success(
        api.get_jurisdiction_rule(rule["id"], _PLATFORM_ADMIN), 200
    )
    assert old_rule["status"] == "SUPERSEDED"


def test_rule_supersede_expiry_decrements_open_counts():
    """PRD §3.1: "each such expiry decrements the owning project's
    `open_notice_count` and the owning company's `open_notice_count` by one."

    Design: Difficulty/transitive_cascade/rule_supersede_expires_draft_notice_chain
    """
    company, rule, project, notice = _setup_draft_notice_before_supersede()
    assert get_project(project["id"])["open_notice_count"] == 1
    assert get_company(company["id"])["open_notice_count"] == 1

    supersede_rule(rule["id"], rule["version"],
                   prelim_days=10, effective_from="2026-05-10")
    get_notice(notice["id"])  # read applies the due expiry

    assert get_project(project["id"])["open_notice_count"] == 0
    assert get_company(company["id"])["open_notice_count"] == 0
