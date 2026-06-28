"""Expenditure routing, fiscal gates, disbursement, and the account invariant.

Difficulty: routing strict-greater boundary, OCC stale-version beats budget cap,
account available_balance conserved by approve->deny.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    assert_account_balance_invariant,
)
from test_helpers import factories as F
from test_helpers import fixtures as fx


# ===========================================================================
# Difficulty: routing threshold strict-greater boundary on create
# ===========================================================================
def test_routing_exactly_at_threshold_auto_approved(api):
    """PRD 3.6: "an amount of 1,000,000 cents routes on the auto-approval path,
    while 1,000,001 cents routes to court."

    Design: Difficulty/boundary_precision_check/bpc_routing_threshold_strict_greater
    """
    ctx = fx.funded_conservatorship(funding_cents=5_000_000, care_cap_cents=5_000_000)
    exp = fx.create_expenditure(
        ctx["case_id"], ctx["budget_id"], ctx["fiduciary_id"],
        category="CARE", amount_cents=1_000_000, payee_name="At threshold",
    )
    assert exp["requires_court_approval"] is False
    assert exp["status"] == "APPROVED"


def test_routing_one_over_threshold_pending_court(api):
    """PRD 3.6: "An expenditure requires court approval when its amount_cents is
    strictly greater than the court-approval threshold of 1,000,000 cents, or when
    its category is ADMIN."

    Design: Difficulty/boundary_precision_check/bpc_routing_threshold_strict_greater
    """
    ctx = fx.funded_conservatorship(funding_cents=5_000_000, care_cap_cents=5_000_000)
    exp = fx.create_expenditure(
        ctx["case_id"], ctx["budget_id"], ctx["fiduciary_id"],
        category="CARE", amount_cents=1_000_001, payee_name="Over threshold",
    )
    assert exp["requires_court_approval"] is True
    assert exp["status"] == "PENDING_COURT"


def test_admin_category_always_routes_to_court(api):
    """PRD 3.6: "An expenditure requires court approval when its amount_cents is
    strictly greater than the court-approval threshold of 1,000,000 cents, or when
    its category is ADMIN."

    Design: Corner/cross_cutting_complexity_layers/threshold_routing_admin_always_court
    """
    ctx = fx.funded_conservatorship(funding_cents=5_000_000, care_cap_cents=0, admin_cap_cents=2_000_000)
    exp = fx.create_expenditure(
        ctx["case_id"], ctx["budget_id"], ctx["fiduciary_id"],
        category="ADMIN", amount_cents=100_000, payee_name="SmallFee",
    )
    assert exp["requires_court_approval"] is True
    assert exp["status"] == "PENDING_COURT"


# ===========================================================================
# Budget cap + funds boundaries
# ===========================================================================
def test_budget_cap_boundary_exactly_at_cap_allowed(api):
    """PRD 3.6: "The boundary is strict the other way: a total exactly equal to
    the cap is allowed, and only a total strictly greater than the cap is rejected,
    with ERR_BUDGET_CAP_EXCEEDED."

    Design: Corner/calculations/budget_cap_boundary_exactly_at_cap_allowed
    """
    # Amount equals the cap (already 0 + held 0 + 1,000,000 == cap 1,000,000), so
    # the strict-greater cap rule allows equality. The amount is also exactly at the
    # court-approval threshold (1,000,000, not strictly greater), so it stays on the
    # auto-approval path and reaches APPROVED rather than PENDING_COURT.
    ctx = fx.funded_conservatorship(funding_cents=5_000_000, care_cap_cents=1_000_000)
    exp = fx.create_expenditure(
        ctx["case_id"], ctx["budget_id"], ctx["fiduciary_id"],
        category="CARE", amount_cents=1_000_000, payee_name="AtCap",
    )
    assert exp["status"] == "APPROVED"


def test_funds_insufficient_one_cent_over_available(api):
    """PRD 3.6: "the restricted account's available_balance_cents must be at least
    this expenditure's amount_cents, or the approval is rejected with
    ERR_INSUFFICIENT_RESTRICTED_FUNDS."

    Design: Corner/calculations/funds_insufficient_one_cent_over_available
    """
    ctx = fx.funded_conservatorship(funding_cents=500_000, care_cap_cents=5_000_000)
    cv = fx.current_case_version(ctx["case_id"])
    resp = api.create_expenditure(
        F.create_expenditure_payload(
            ctx["case_id"], ctx["budget_id"], cv,
            category="CARE", amount_cents=500_001, payee_name="Over",
        ),
        fx.make_fiduciary_headers(ctx["fiduciary_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_RESTRICTED_FUNDS)


# ===========================================================================
# Difficulty: OCC stale-version beats budget-cap (priority pair)
# ===========================================================================
def test_stale_version_beats_budget_cap(api):
    """PRD 2.8: "if that value does not equal the case's current version, the
    operation is rejected with ERR_STALE_CASE_VERSION (HTTP 412)."
    PRD 3.9: "a stale case version surfaces before a segregation-of-duties or
    state conflict."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_stale_version_beats_budget_cap
    """
    ctx = fx.funded_conservatorship(funding_cents=5_000_000, care_cap_cents=1_000_000)
    fid = ctx["fiduciary_id"]
    # Observe a case version, then advance the version by creating+disbursing a
    # CARE expenditure (care_spent -> 900,000), making the captured version stale.
    cv_stale = fx.current_case_version(ctx["case_id"])
    first = get_success_data(
        api.create_expenditure(
            F.create_expenditure_payload(
                ctx["case_id"], ctx["budget_id"], cv_stale,
                category="CARE", amount_cents=900_000, payee_name="Caregiver A",
            ),
            fx.make_fiduciary_headers(fid),
        )
    )
    api.disburse_expenditure(first["id"], fx.make_fiduciary_headers(fid))

    # Now reuse cv_stale: it is stale AND 900,000+200,000 > cap 1,000,000.
    resp = api.create_expenditure(
        F.create_expenditure_payload(
            ctx["case_id"], ctx["budget_id"], cv_stale,
            category="CARE", amount_cents=200_000, payee_name="Caregiver B",
        ),
        fx.make_fiduciary_headers(fid),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_CASE_VERSION)


def test_stale_version_beats_budget_cap_status_412(api):
    """PRD 2.8: "if that value does not equal the case's current version, the
    operation is rejected with ERR_STALE_CASE_VERSION (HTTP 412)."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_stale_version_beats_budget_cap
    """
    # Same conflict (stale version AND over-cap) but assert the HTTP status is the
    # OCC's 412, not the budget-cap's 409 — proving OCC wins the precedence.
    ctx = fx.funded_conservatorship(funding_cents=5_000_000, care_cap_cents=1_000_000)
    fid = ctx["fiduciary_id"]
    cv_stale = fx.current_case_version(ctx["case_id"])
    first = get_success_data(
        api.create_expenditure(
            F.create_expenditure_payload(
                ctx["case_id"], ctx["budget_id"], cv_stale,
                category="CARE", amount_cents=900_000, payee_name="Caregiver A",
            ),
            fx.make_fiduciary_headers(fid),
        )
    )
    api.disburse_expenditure(first["id"], fx.make_fiduciary_headers(fid))
    resp = api.create_expenditure(
        F.create_expenditure_payload(
            ctx["case_id"], ctx["budget_id"], cv_stale,
            category="CARE", amount_cents=200_000, payee_name="Caregiver B",
        ),
        fx.make_fiduciary_headers(fid),
    )
    assert resp.status_code == 412, f"expected 412 (OCC wins), got {resp.status_code}"


# ===========================================================================
# Difficulty: account available_balance conserved by approve->deny
# ===========================================================================
def test_account_available_after_court_approve(api):
    """PRD 2.9: "The encumbered figure is the sum of expenditure amounts that are
    APPROVED but not yet DISBURSED — funds held against the account but not yet
    paid out."

    Design: Difficulty/compensating_invariant/ci_account_available_conserved_by_deny
    """
    ctx = fx.funded_conservatorship(funding_cents=5_000_000, care_cap_cents=0, admin_cap_cents=2_000_000)
    fid = ctx["fiduciary_id"]
    exp = fx.create_expenditure(
        ctx["case_id"], ctx["budget_id"], fid,
        category="ADMIN", amount_cents=600_000, payee_name="Fee",
    )
    assert exp["status"] == "PENDING_COURT"
    api.approve_expenditure(exp["id"], fx.JUDGE)
    acct = get_success_data(api.get_restricted_account(ctx["account_id"], fx.JUDGE))
    assert acct["encumbered_cents"] == 600_000
    assert acct["available_balance_cents"] == 4_400_000
    assert_account_balance_invariant(acct)


def test_account_available_conserved_by_deny(api):
    """PRD 3.6: "A judge may also deny an already-APPROVED expenditure; doing so
    moves it to DENIED and releases the hold, lowering encumbered_cents by the
    amount and recomputing the available balance."

    Design: Difficulty/compensating_invariant/ci_account_available_conserved_by_deny
    """
    ctx = fx.funded_conservatorship(funding_cents=5_000_000, care_cap_cents=0, admin_cap_cents=2_000_000)
    fid = ctx["fiduciary_id"]
    exp = fx.create_expenditure(
        ctx["case_id"], ctx["budget_id"], fid,
        category="ADMIN", amount_cents=600_000, payee_name="Fee",
    )
    api.approve_expenditure(exp["id"], fx.JUDGE)
    api.deny_expenditure(exp["id"], fx.JUDGE)
    acct = get_success_data(api.get_restricted_account(ctx["account_id"], fx.JUDGE))
    assert acct["encumbered_cents"] == 0
    assert acct["available_balance_cents"] == 5_000_000
    assert_account_balance_invariant(acct)


# ===========================================================================
# Disbursement, freeze, filtered listing
# ===========================================================================
def test_suspend_freezes_account_then_disburse_blocked(api):
    """PRD 3.6: "A fiduciary disburses an APPROVED expenditure (else
    ERR_INVALID_STATE), which requires the restricted account to be OPEN (else
    ERR_ACCOUNT_FROZEN)."

    Design: Corner/state_machines/suspend_freezes_account_then_disburse_blocked
    """
    ctx = fx.funded_conservatorship(funding_cents=5_000_000, care_cap_cents=5_000_000)
    fid = ctx["fiduciary_id"]
    exp = fx.create_expenditure(
        ctx["case_id"], ctx["budget_id"], fid,
        category="CARE", amount_cents=500_000, payee_name="Pay",
    )
    assert exp["status"] == "APPROVED"
    api.suspend_appointment(ctx["appointment_id"], fx.JUDGE)
    acct = get_success_data(api.get_restricted_account(ctx["account_id"], fx.JUDGE))
    assert acct["status"] == "FROZEN"
    validate_error(
        api.disburse_expenditure(exp["id"], fx.make_fiduciary_headers(fid)),
        ApiErrorId.ERR_ACCOUNT_FROZEN,
    )


# NOTE: Corner instance endpoints/filtered_list_expenditures_by_status is SKIPPED.
# Its assertion — that GET /gc/expenditures honors a `status` query filter — is not
# uniquely derivable from PRD prose: Section 2.4 states only that the foreign-key
# field is accepted as an optional query parameter for reverse reachability, and the
# `status` filter appears solely in the Section 4 endpoint table (endpoint-titular,
# fails C2). Two faithful PRD-only implementers could diverge on whether `?status=`
# is supported, so the instance is skipped rather than weakened.
