"""Notice fee rounding, the delivery-failure reprepare cycle, the inclusive
service-deadline boundary, open-notice counter conservation, and the
safety-over-fiscal validation priority (PRD §2.6, §2.10, §3.4)."""
from test_helpers import (
    ApiErrorId,
    create_company,
    create_party,
    create_project,
    get_company,
    get_notice,
    get_project,
    make_customer_admin_headers,
    order_notice,
    publish_rule,
    record_proof,
    record_span,
    serve_notice,
    set_clock,
    setup_verified_ca_project,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client as api
from test_helpers.factories import create_notice_payload
from test_helpers.test_users import TEST_USERS

_PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
_OPS_AGENT = TEST_USERS["ops_agent_headers"]


# ─── Fee rounding (queue A: combinatorial_formula) ───────────────────

def _setup_fee_scenario():
    """Verified CA project; company prepaid balance exactly 10000000."""
    return setup_verified_ca_project(name="Fee Job", county="Alameda",
                                     seed_balance_cents=10000000)


def test_notice_fee_rounds_each_line_then_sums():
    """PRD §3.4: "The recipient line starts from a base of 1499 cents; when the
    recipient party's `party_role` is `LENDER`, a 15 percent surcharge is
    applied to that base and the result rounded half-up to whole cents" and
    "Rounding each line first and then summing is the pinned evaluation order;
    summing the unrounded lines and rounding once is forbidden, because it can
    produce a different cent value."
    (LENDER line 1724 + PERSONAL_SERVICE line 2248 = 3972; the forbidden order
    would give 3971.)

    Design: Difficulty/combinatorial_formula/notice_fee_per_line_rounding
    """
    ctx = _setup_fee_scenario()

    notice = order_notice(ctx["project"]["id"], ctx["company"]["id"],
                          ctx["parties"]["LENDER"]["id"],
                          delivery_method="PERSONAL_SERVICE")
    assert notice["fee_cents"] == 3972


def test_notice_fee_debits_company_balance_at_creation():
    """PRD §3.4: "The fee is debited from the company's `prepaid_balance_cents`
    at creation, incrementing the company's `version` by one, and both the
    project's and the company's `open_notice_count` increment by one."

    Design: Difficulty/combinatorial_formula/notice_fee_per_line_rounding
    """
    ctx = _setup_fee_scenario()

    order_notice(ctx["project"]["id"], ctx["company"]["id"],
                 ctx["parties"]["LENDER"]["id"],
                 delivery_method="PERSONAL_SERVICE")
    company = get_company(ctx["company"]["id"])
    assert company["prepaid_balance_cents"] == 10000000 - 3972
    assert company["open_notice_count"] == 1


# ─── Delivery-failure reprepare cycle (queue A: non_linear_state_machine) ──

def test_notice_returned_proof_then_reprepare_returns_draft():
    """PRD §3.4: "A `result` of `RETURNED` — or `REFUSED` when
    `refused_counts_as_served` is false — moves it to `DELIVERY_FAILED`." and
    "a `CustomerAdmin` can reprepare it, returning it to `DRAFT` with
    `served_at` and `proof_result` cleared and the `service_deadline` recomputed
    live against the currently effective rule."

    Design: Difficulty/non_linear_state_machine/notice_delivery_failure_reprepare_cycle
    """
    ctx = setup_verified_ca_project(name="Cycle Job", county="Fresno")
    notice = order_notice(ctx["project"]["id"], ctx["company"]["id"],
                          ctx["parties"]["OWNER"]["id"])

    served = serve_notice(notice["id"], "2026-05-20")
    assert served["status"] == "SERVED"

    failed = record_proof(notice["id"], result="RETURNED")
    assert failed["status"] == "DELIVERY_FAILED"

    reprepared = validate_success(
        api.reprepare_notice(
            notice["id"], make_customer_admin_headers(ctx["company"]["id"])
        ),
        200,
    )
    assert reprepared["status"] == "DRAFT"
    assert reprepared["served_at"] is None
    assert reprepared["proof_result"] is None
    # rule unchanged: recomputed deadline equals the original 2026-05-22
    assert reprepared["service_deadline"] == "2026-05-22"


def test_notice_reprepare_second_pass_reaches_proof_confirmed():
    """PRD §3.4: "A `result` of `DELIVERED` moves the notice to
    `PROOF_CONFIRMED`" and "Confirming proof decrements the project's and the
    company's `open_notice_count` by one and recomputes `lien_posture`; a failed
    delivery changes neither count, so the notice remains open."

    Design: Difficulty/non_linear_state_machine/notice_delivery_failure_reprepare_cycle
    """
    ctx = setup_verified_ca_project(name="Cycle Job", county="Fresno")
    notice = order_notice(ctx["project"]["id"], ctx["company"]["id"],
                          ctx["parties"]["OWNER"]["id"])

    serve_notice(notice["id"], "2026-05-20")
    record_proof(notice["id"], result="RETURNED")
    # still open after the failed delivery
    assert get_project(ctx["project"]["id"])["open_notice_count"] == 1

    validate_success(
        api.reprepare_notice(
            notice["id"], make_customer_admin_headers(ctx["company"]["id"])
        ),
        200,
    )
    re_served = serve_notice(notice["id"], "2026-05-21")
    assert re_served["status"] == "SERVED"

    confirmed = record_proof(notice["id"], result="DELIVERED")
    assert confirmed["status"] == "PROOF_CONFIRMED"
    # decremented exactly once, at PROOF_CONFIRMED
    assert get_project(ctx["project"]["id"])["open_notice_count"] == 0
    assert get_company(ctx["company"]["id"])["open_notice_count"] == 0


# ─── Service-deadline boundary (queue A: boundary_precision_check) ───

def _setup_two_draft_notices():
    """Verified CA project (prelim deadline 2026-05-22) with DRAFT notices to
    the OWNER and the GC."""
    ctx = setup_verified_ca_project(name="Edge Job", county="Solano")
    n1 = order_notice(ctx["project"]["id"], ctx["company"]["id"],
                      ctx["parties"]["OWNER"]["id"])
    n2 = order_notice(ctx["project"]["id"], ctx["company"]["id"],
                      ctx["parties"]["GC"]["id"])
    return ctx, n1, n2


def test_serve_on_deadline_day_is_timely():
    """PRD §2.6: "Every statutory deadline treats its final day as usable: an
    action performed on the deadline day itself is timely, and only a date
    strictly after the deadline fails."

    Design: Difficulty/boundary_precision_check/prelim_deadline_last_day_inclusive
    """
    _ctx, n1, _n2 = _setup_two_draft_notices()
    assert n1["service_deadline"] == "2026-05-22"

    served = serve_notice(n1["id"], "2026-05-22")
    assert served["status"] == "SERVED"
    assert served["served_at"] == "2026-05-22"


def test_serve_one_day_past_deadline_rejected():
    """PRD §3.4: "The date must fall on or before the `service_deadline` — the
    deadline day itself is timely — or the service is rejected with
    `ERR_NOTICE_DEADLINE_PASSED` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/prelim_deadline_last_day_inclusive
    """
    _ctx, _n1, n2 = _setup_two_draft_notices()

    res = api.serve_notice(n2["id"], {"served_at": "2026-05-23"}, _OPS_AGENT)
    validate_error(res, ApiErrorId.ERR_NOTICE_DEADLINE_PASSED)
    assert get_notice(n2["id"])["status"] == "DRAFT"


# ─── Open-notice counter conservation (queue A: compensating_invariant) ──

def test_notice_create_increments_open_counts():
    """PRD §3.4: "both the project's and the company's `open_notice_count`
    increment by one."

    Design: Difficulty/compensating_invariant/notice_create_expire_conserves_open_count
    """
    ctx = setup_verified_ca_project(name="Cnt Job", county="Colusa")

    order_notice(ctx["project"]["id"], ctx["company"]["id"],
                 ctx["parties"]["OWNER"]["id"])
    assert get_project(ctx["project"]["id"])["open_notice_count"] == 1
    assert get_company(ctx["company"]["id"])["open_notice_count"] == 1


def test_notice_expiry_decrements_open_counts_to_baseline():
    """PRD §3.4: "a `DRAFT` notice whose `service_deadline` falls behind the
    logical clock auto-expires — lazily, on its next read or mutation — moving
    to `EXPIRED`, decrementing both open-notice counters, and recomputing the
    project's posture."

    Design: Difficulty/compensating_invariant/notice_create_expire_conserves_open_count
    """
    ctx = setup_verified_ca_project(name="Cnt Job", county="Colusa")
    notice = order_notice(ctx["project"]["id"], ctx["company"]["id"],
                          ctx["parties"]["OWNER"]["id"])

    set_clock("2026-05-23T00:00:00Z")  # past the 2026-05-22 deadline
    assert get_notice(notice["id"])["status"] == "EXPIRED"
    assert get_project(ctx["project"]["id"])["open_notice_count"] == 0
    assert get_company(ctx["company"]["id"])["open_notice_count"] == 0


# ─── Validation priority: compliance over fiscal (queue A) ───────────

def _setup_unverified_project_empty_balance():
    """Company with balance 0, CA rule published, project UNRESEARCHED,
    recipient party PENDING."""
    company = create_company(name="Broke Co")  # no balance seed
    publish_rule()
    project = create_project(company["id"], name="Broke Job")
    party = create_party(project["id"], company["id"], "OWNER", verify=False)
    return company, project, party


def test_notice_create_unverified_project_reports_compliance_error():
    """PRD §2.10: "All remaining checks run as a fixed ladder. The first failing
    rung determines the response, and later rungs are never evaluated for that
    request" — rung 7 lists `ERR_PROJECT_NOT_VERIFIED` (409) among the
    compliance gates and rung 11 holds `ERR_INSUFFICIENT_BALANCE` (402) as a
    fiscal check, so the compliance error must be the one reported.

    Design: Difficulty/priority_pair_validation_conflict/notice_create_unverified_project_empty_balance_safety_wins
    """
    company, project, party = _setup_unverified_project_empty_balance()

    res = api.create_notice(
        create_notice_payload(project["id"], party["id"]),
        make_customer_admin_headers(company["id"]),
    )
    err = validate_error(res, ApiErrorId.ERR_PROJECT_NOT_VERIFIED)
    assert err["error_id"] != ApiErrorId.ERR_INSUFFICIENT_BALANCE


def test_failed_notice_create_debits_no_fee():
    """PRD §3.4: "the company's `prepaid_balance_cents` must cover the quoted
    fee (`ERR_INSUFFICIENT_BALANCE`, HTTP 402)" and "The fee is debited from the
    company's `prepaid_balance_cents` at creation" — a rejected order is never
    created, so no debit may occur.

    Design: Difficulty/priority_pair_validation_conflict/notice_create_unverified_project_empty_balance_safety_wins
    """
    company, project, party = _setup_unverified_project_empty_balance()

    api.create_notice(
        create_notice_payload(project["id"], party["id"]),
        make_customer_admin_headers(company["id"]),
    )
    assert get_company(company["id"])["prepaid_balance_cents"] == 0

    notices, meta = validate_paginated(
        api.list_project_notices(project["id"], _OPS_AGENT)
    )
    assert notices == []
    assert meta["total_count"] == 0
