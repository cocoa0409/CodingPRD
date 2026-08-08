"""Bill adjustments: leak-relief dual-variant credit math, segregation of duties,
and error-precedence when state and business-safety/fiscal checks collide."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    TEST_USERS,
    open_account, finalize_payload,
    setup_bill_with_leak_adjustment, approve_adjustment,
    setup_account_with_water_bill, request_adjustment,
    setup_bill_with_approved_goodwill,
    make_supervisor_headers,
)

BS = TEST_USERS["billing_specialist_headers"]


# ---------------------------------------------------------------------------
# dual_variant_calc / leak_credit_sewer_relief_vs_tier_reprice
# ---------------------------------------------------------------------------
def test_leak_sewer_relief_credit(api):
    """PRD §3.8: "Under `SEWER_RELIEF`, the credit is the sewer volumetric rate applied to
    the excess only — the excess gallons divided by 1,000, multiplied by 250 cents per 1,000
    gallons, rounded half up."
    PRD §3.8: "Approving an adjustment moves it `REQUESTED → APPROVED`, computes its
    `credit_cents`, adds that credit to the target bill's `amount_paid_cents`".

    Design: Difficulty/dual_variant_calc/leak_credit_sewer_relief_vs_tier_reprice
    """
    ctx = setup_bill_with_leak_adjustment(api, "SEWER_RELIEF", reading_value=9500,
                                          baseline_units=3000, requester_id="cw_1")
    approved = approve_adjustment(api, ctx["adjustment"]["id"], "sup_1")
    assert approved["status"] == "APPROVED"
    assert approved["credit_cents"] == 1625


def test_leak_tier_reprice_credit_differs_from_sewer_relief(api):
    """PRD §3.8: "Under `TIER_REPRICE`, the excess gallons are first charged at the actual
    marginal water tiers they occupied — the charge over the gallons above `baseline_units`
    up to the current water consumption, computed with the water tier schedule and rounded
    half up — and then repriced by charging all of those excess gallons at the lowest water
    tier rate of 315 cents per 1,000 gallons, rounded half up; the credit is the first
    (actual tiered) amount minus the second (repriced) amount."

    Design: Difficulty/dual_variant_calc/leak_credit_sewer_relief_vs_tier_reprice
    """
    ctx = setup_bill_with_leak_adjustment(api, "TIER_REPRICE", reading_value=9500,
                                          baseline_units=3000, requester_id="cw_1")
    approved = approve_adjustment(api, ctx["adjustment"]["id"], "sup_1")
    assert approved["credit_cents"] == 647
    assert approved["credit_cents"] != 1625


# ---------------------------------------------------------------------------
# validations / sod_violation_on_approve_by_requester_returns_403 (corner)
# ---------------------------------------------------------------------------
def test_approve_by_requester_violates_sod(api):
    """PRD §2.10: "the approving supervisor's `X-User-ID` must differ from the recorded
    `requested_by`; the deciding supervisor is recorded as `approved_by`."
    PRD §2.10: "If the acting `X-User-ID` on an approve or reject equals `requested_by`, the
    request is rejected with `ERR_SOD_VIOLATION` (HTTP 403)."

    Design: Corner/validations/sod_violation_on_approve_by_requester_returns_403
    """
    ctx = setup_account_with_water_bill(api, reading_value=9500)
    adj = request_adjustment(api, ctx["bill"]["id"], "shared_id",
                             adjustment_type="GOODWILL", goodwill_amount_cents=500)
    resp = api.approve_adjustment(adj["id"], make_supervisor_headers("shared_id"))
    validate_error(resp, "ERR_SOD_VIOLATION")


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / state_beats_sod_on_already_approved_adjustment
# ---------------------------------------------------------------------------
def test_reapprove_approved_adjustment_returns_invalid_state_over_sod(api):
    """PRD §2.11: "Only after a resource is known to exist are state preconditions
    evaluated: a transition attempted from an invalid current state yields
    `ERR_INVALID_STATE` (409)".
    PRD §2.11: "Business-safety checks come next — segregation of duties
    (`ERR_SOD_VIOLATION`) and moratorium enforcement (`ERR_MORATORIUM_ACTIVE`)".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_sod_on_already_approved_adjustment
    """
    ctx = setup_bill_with_approved_goodwill(api, requester_id="cw_shared", approver_id="sup_a",
                                            goodwill_amount_cents=500)
    # Re-approve by the original requester: both ERR_INVALID_STATE (already APPROVED) and
    # ERR_SOD_VIOLATION (approver == requester) would apply; the state check wins.
    resp = api.approve_adjustment(ctx["adjustment"]["id"], make_supervisor_headers("cw_shared"))
    validate_error(resp, "ERR_INVALID_STATE")


def test_reapprove_rejected_leaves_adjustment_approved(api):
    """PRD §2.11: "a transition attempted from an invalid current state yields
    `ERR_INVALID_STATE` (409)".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_sod_on_already_approved_adjustment
    """
    ctx = setup_bill_with_approved_goodwill(api, requester_id="cw_shared", approver_id="sup_a",
                                            goodwill_amount_cents=500)
    api.approve_adjustment(ctx["adjustment"]["id"], make_supervisor_headers("cw_shared"))
    adjustments, _ = validate_paginated(api.list_adjustments(ctx["bill"]["id"], BS))
    adj = [a for a in adjustments if a["id"] == ctx["adjustment"]["id"]][0]
    assert adj["status"] == "APPROVED", "the rejected re-approval must not change the adjustment"


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / state_beats_fiscal_on_finalized_account_payment
# ---------------------------------------------------------------------------
def test_payment_on_finalized_account_returns_not_active_over_fiscal(api):
    """PRD §2.11: "an attempt to mutate an account that is `FINALED` or `LIEN_TRANSFERRED`
    yields `ERR_ACCOUNT_NOT_ACTIVE` (409)".
    PRD §2.11: "and finally the fiscal checks (`ERR_PAYMENT_EXCEEDS_BALANCE`)".
    PRD §3.1: "Any mutating operation attempted against an account that has reached
    `FINALED` or `LIEN_TRANSFERRED` is refused with `ERR_ACCOUNT_NOT_ACTIVE`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_finalized_account_payment
    """
    account = open_account(api, account_holder_name="Done Dan")
    validate_success(api.finalize_account(account["id"], finalize_payload(), BS), 201)
    resp = api.create_payment(account["id"], {"amount_cents": 5000, "method": "CASH"}, BS)
    validate_error(resp, "ERR_ACCOUNT_NOT_ACTIVE")


def test_payment_rejected_on_finalized_account_records_no_payment(api):
    """PRD §3.1: "Any mutating operation attempted against an account that has reached
    `FINALED` or `LIEN_TRANSFERRED` is refused with `ERR_ACCOUNT_NOT_ACTIVE`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_finalized_account_payment
    """
    account = open_account(api, account_holder_name="Done Dan")
    validate_success(api.finalize_account(account["id"], finalize_payload(), BS), 201)
    api.create_payment(account["id"], {"amount_cents": 5000, "method": "CASH"}, BS)
    payments, _ = validate_paginated(api.list_payments(account["id"], BS))
    assert payments == [], "a rejected payment on a finalized account must not be recorded"
