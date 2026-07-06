"""Financing: deposit/financed derivation, DTI tiers and boundary, amortized
payment, amount coherence and bounds precedence, and the independent
presentation/financing state axes.

Queue A (difficulty): non_linear_state_machine (parallel axes),
boundary_precision_check (DTI at exact max), priority_pair_validation_conflict
(mismatch beats exceeds-max).
Queue B (corner): calculations + validations + state_machines.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    make_customer_headers,
    setup_presented_quote, setup_presented_financed_quote,
    setup_design_complete_project, create_quote_payload,
    make_designer_headers, get_project_version, refresh_quote,
)

IC = TEST_USERS["install_coordinator_headers"]
FO = TEST_USERS["finance_officer_headers"]


def _attempt_financed_quote(api, area, bathroom_type, wall_system, plan, requested, income):
    """Try to create a financed quote on a fresh DESIGN_COMPLETE project; returns
    the raw response so error paths can be asserted."""
    ctx = setup_design_complete_project(api, area=area, bathroom_type=bathroom_type)
    version = get_project_version(api, ctx["project"]["id"])
    payload = create_quote_payload(
        ctx["project"]["id"], version, wall_system=wall_system, color="WHITE",
        financing_plan_code=plan, requested_amount_cents=requested,
        stated_annual_income_cents=income)
    return api.create_quote(payload, make_designer_headers(ctx["designer"]["id"]))


# --- Queue A: parallel status/financing dimensions -------------------------

def test_finance_approve_leaves_presentation_status_unchanged(api):
    """PRD §3.4: "The application sits until a FinanceOfficer decides it, which is
    permitted only while financing_status is REQUESTED (ERR_FINANCING_NOT_REQUESTED)."
    PRD §3.4: "The approved APR (approved_apr_bps) is the plan's base APR plus the
    selected tier's surcharge, in basis points, and financing_status moves
    REQUESTED → APPROVED."

    Design: Difficulty/non_linear_state_machine/quote_parallel_status_and_financing_dimensions
    """
    ctx = setup_presented_financed_quote(
        api, area=60.0, financing_plan_code="PLAN_60_999",
        requested_amount_cents=555610, stated_annual_income_cents=6000000,
        wall_system="SMOOTH_ACRYLIC", accessibility_addon="WALK_IN_TUB", promo_code="SPRING750")
    validate_success(api.finance_decide(ctx["quote"]["id"], {"decision": "APPROVE"}, FO), 200)
    quote = refresh_quote(api, ctx["quote"]["id"])
    assert quote["financing_status"] == "APPROVED"
    assert quote["status"] == "PRESENTED", (
        "the presentation status axis is independent and stays PRESENTED after finance approval"
    )


def test_finance_approve_computes_terms(api):
    """PRD §3.4: "First, the deposit (deposit_cents) is 10% of the net price,
    rounded half-up to a whole cent. Second, the financed amount
    (financed_amount_cents) is the net price minus the deposit."
    PRD §3.4: "When that monthly rate is greater than zero, the monthly payment
    equals the financed amount multiplied by the monthly rate, multiplied by (one
    plus the monthly rate) raised to the power of the number of term months,
    divided by the quantity (one plus the monthly rate) raised to the power of the
    number of term months minus one, with the result rounded half-up to a whole
    cent."

    Design: Difficulty/non_linear_state_machine/quote_parallel_status_and_financing_dimensions
    """
    ctx = setup_presented_financed_quote(
        api, area=60.0, financing_plan_code="PLAN_60_999",
        requested_amount_cents=555610, stated_annual_income_cents=6000000,
        wall_system="SMOOTH_ACRYLIC", accessibility_addon="WALK_IN_TUB", promo_code="SPRING750")
    validate_success(api.finance_decide(ctx["quote"]["id"], {"decision": "APPROVE"}, FO), 200)
    quote = refresh_quote(api, ctx["quote"]["id"])
    assert quote["deposit_cents"] == 61734          # round(617344 * 0.10)
    assert quote["financed_amount_cents"] == 555610  # 617344 - 61734
    assert quote["approved_apr_bps"] == 999          # base 999 + 0 (DTI 0.0926 <= 0.20)
    assert quote["monthly_payment_cents"] == 11802


# --- Queue A: DTI boundary at exact maximum --------------------------------

def test_dti_at_exact_max_ratio_approved(api):
    """PRD §3.4: "a ratio of at most 0.20 adds 0 basis points; a ratio above 0.20
    but at most 0.35 adds 250 basis points; a ratio above 0.35 but at most 0.50
    adds 600 basis points; and a ratio above 0.50 is not financeable and the
    approval is refused with ERR_DTI_EXCEEDED."

    Design: Difficulty/boundary_precision_check/dti_ratio_at_exact_max_finance_decide
    """
    ctx = setup_presented_financed_quote(
        api, area=60.0, financing_plan_code="PLAN_60_999",
        requested_amount_cents=555610, stated_annual_income_cents=1111220,  # ratio == 0.50
        wall_system="SMOOTH_ACRYLIC", accessibility_addon="WALK_IN_TUB", promo_code="SPRING750")
    validate_success(api.finance_decide(ctx["quote"]["id"], {"decision": "APPROVE"}, FO), 200)
    quote = refresh_quote(api, ctx["quote"]["id"])
    assert quote["financing_status"] == "APPROVED"
    assert quote["approved_apr_bps"] == 1599  # 999 + 600 (0.50 falls in the <=0.50 tier)
    assert quote["monthly_payment_cents"] == 13508


def test_dti_just_over_max_ratio_rejected(api):
    """PRD §3.4: "a ratio above 0.35 but at most 0.50 adds 600 basis points; and a
    ratio above 0.50 is not financeable and the approval is refused with
    ERR_DTI_EXCEEDED."

    Design: Difficulty/boundary_precision_check/dti_ratio_at_exact_max_finance_decide
    """
    ctx = setup_presented_financed_quote(
        api, area=60.0, financing_plan_code="PLAN_60_999",
        requested_amount_cents=555610, stated_annual_income_cents=1111219,  # ratio > 0.50
        wall_system="SMOOTH_ACRYLIC", accessibility_addon="WALK_IN_TUB", promo_code="SPRING750")
    resp = api.finance_decide(ctx["quote"]["id"], {"decision": "APPROVE"}, FO)
    validate_error(resp, ApiErrorId.ERR_DTI_EXCEEDED.value)


# --- Queue A: mismatch beats exceeds-max (validation precedence) -----------

def test_financing_mismatch_reported_before_exceeds_max(api):
    """PRD §2.5: "When a request could fail more than one check, the checks are
    evaluated in a fixed precedence so that the reported error is deterministic."
    PRD §2.5: "When a financing plan is requested at quote creation, the requested
    amount must reconcile with the computed financed amount; a mismatch is
    ERR_FINANCING_AMOUNT_MISMATCH (422)."
    PRD §2.5: "The requested amount must fall within the chosen plan's bounds and,
    at approval, the debt-to-income ratio must be within tolerance:
    ERR_FINANCING_AMOUNT_BELOW_MIN, ERR_FINANCING_AMOUNT_EXCEEDS_MAX, and
    ERR_DTI_EXCEEDED (all 422)."

    Design: Difficulty/priority_pair_validation_conflict/financing_mismatch_beats_exceeds_max
    """
    # TILE/100 financed == 488520; requested 9999999 both mismatches AND exceeds the
    # PLAN_12_0 max of 1500000. Coherence (prio 10) precedes bounds (prio 11).
    resp = _attempt_financed_quote(
        api, area=100.0, bathroom_type="FULL_BATH", wall_system="TILE_LOOK_ACRYLIC",
        plan="PLAN_12_0", requested=9999999, income=6000000)
    validate_error(resp, ApiErrorId.ERR_FINANCING_AMOUNT_MISMATCH.value)


def test_financing_mismatch_in_isolation(api):
    """PRD §3.4: "The applicant's requested_amount_cents must equal this financed
    amount exactly; if it does not, the request is rejected with
    ERR_FINANCING_AMOUNT_MISMATCH."

    Design: Difficulty/priority_pair_validation_conflict/financing_mismatch_beats_exceeds_max
    """
    # requested 500000 is within PLAN_12_0 bounds but != financed 488520 -> only mismatch.
    resp = _attempt_financed_quote(
        api, area=100.0, bathroom_type="FULL_BATH", wall_system="TILE_LOOK_ACRYLIC",
        plan="PLAN_12_0", requested=500000, income=6000000)
    validate_error(resp, ApiErrorId.ERR_FINANCING_AMOUNT_MISMATCH.value)


# --- Queue B (corner) ------------------------------------------------------

def test_near_prime_dti_tier_surcharge(api):
    """PRD §3.4: "a ratio above 0.20 but at most 0.35 adds 250 basis points".
    PRD §3.4: "The approved APR (approved_apr_bps) is the plan's base APR plus the
    selected tier's surcharge, in basis points, and financing_status moves
    REQUESTED → APPROVED."

    Design: Corner/calculations/financing_near_prime_dti_tier
    """
    ctx = setup_presented_financed_quote(
        api, area=60.0, financing_plan_code="PLAN_60_999",
        requested_amount_cents=555610, stated_annual_income_cents=2000000,  # ratio 0.2778
        wall_system="SMOOTH_ACRYLIC", accessibility_addon="WALK_IN_TUB", promo_code="SPRING750")
    validate_success(api.finance_decide(ctx["quote"]["id"], {"decision": "APPROVE"}, FO), 200)
    quote = refresh_quote(api, ctx["quote"]["id"])
    assert quote["approved_apr_bps"] == 1249  # 999 + 250
    assert quote["monthly_payment_cents"] == 12497


def test_financing_below_plan_min_rejected(api):
    """PRD §3.4: "The requested amount must lie within the chosen plan's band:
    below the minimum it is rejected with ERR_FINANCING_AMOUNT_BELOW_MIN, and
    above the maximum with ERR_FINANCING_AMOUNT_EXCEEDS_MAX."
    PRD §3.4: "PLAN_12_0: base APR 0 basis points, term 12 months, financing at
    least 100000 cents and at most 1500000 cents."

    Design: Corner/validations/financing_requested_below_plan_min_rejected
    """
    # SMOOTH/20 -> net 75000, financed 67500 (== requested, passes coherence) but < 100000.
    resp = _attempt_financed_quote(
        api, area=20.0, bathroom_type="TUB_ONLY", wall_system="SMOOTH_ACRYLIC",
        plan="PLAN_12_0", requested=67500, income=6000000)
    validate_error(resp, ApiErrorId.ERR_FINANCING_AMOUNT_BELOW_MIN.value)


def test_financing_exceeds_plan_max_rejected(api):
    """PRD §3.4: "The requested amount must lie within the chosen plan's band:
    below the minimum it is rejected with ERR_FINANCING_AMOUNT_BELOW_MIN, and
    above the maximum with ERR_FINANCING_AMOUNT_EXCEEDS_MAX."
    PRD §3.4: "PLAN_12_0: base APR 0 basis points, term 12 months, financing at
    least 100000 cents and at most 1500000 cents."

    Design: Corner/validations/financing_requested_exceeds_plan_max_rejected
    """
    # STONE/250 -> net 1749000, financed 1574100 (== requested, passes coherence) but > 1500000.
    resp = _attempt_financed_quote(
        api, area=250.0, bathroom_type="FULL_BATH", wall_system="STONE_LOOK_ACRYLIC",
        plan="PLAN_12_0", requested=1574100, income=9000000)
    validate_error(resp, ApiErrorId.ERR_FINANCING_AMOUNT_EXCEEDS_MAX.value)


def test_dti_exceeded_at_approval(api):
    """PRD §3.4: "a ratio above 0.50 is not financeable and the approval is
    refused with ERR_DTI_EXCEEDED."

    Design: Corner/validations/dti_exceeded_at_finance_decide
    """
    ctx = setup_presented_financed_quote(
        api, area=60.0, financing_plan_code="PLAN_60_999",
        requested_amount_cents=555610, stated_annual_income_cents=900000,  # ratio 0.617
        wall_system="SMOOTH_ACRYLIC", accessibility_addon="WALK_IN_TUB", promo_code="SPRING750")
    resp = api.finance_decide(ctx["quote"]["id"], {"decision": "APPROVE"}, FO)
    validate_error(resp, ApiErrorId.ERR_DTI_EXCEEDED.value)


def test_finance_decide_without_financing_requested_rejected(api):
    """PRD §3.4: "The application sits until a FinanceOfficer decides it, which is
    permitted only while financing_status is REQUESTED (ERR_FINANCING_NOT_REQUESTED)."

    Design: Corner/state_machines/finance_decide_when_no_financing_requested_returns_not_requested
    """
    ctx = setup_presented_quote(api, area=100.0, wall_system="TILE_LOOK_ACRYLIC")  # no plan -> NONE
    resp = api.finance_decide(ctx["quote"]["id"], {"decision": "APPROVE"}, FO)
    validate_error(resp, ApiErrorId.ERR_FINANCING_NOT_REQUESTED.value)


def test_declined_financing_blocks_acceptance(api):
    """PRD §3.4: "On a decline decision, the officer moves financing_status
    REQUESTED → DECLINED and nothing further is computed."
    PRD §3.5: "a quote whose financing is still REQUESTED or was DECLINED cannot
    be accepted and is refused with ERR_FINANCING_NOT_APPROVED."

    Design: Corner/state_machines/finance_decide_decline_then_accept_blocked
    """
    ctx = setup_presented_financed_quote(
        api, area=100.0, financing_plan_code="PLAN_60_999",
        requested_amount_cents=488520, stated_annual_income_cents=6000000,
        wall_system="TILE_LOOK_ACRYLIC")
    validate_success(api.finance_decide(ctx["quote"]["id"], {"decision": "DECLINE"}, FO), 200)
    quote = refresh_quote(api, ctx["quote"]["id"])
    assert quote["financing_status"] == "DECLINED"
    resp = api.accept_quote(ctx["quote"]["id"], make_customer_headers(ctx["customer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_FINANCING_NOT_APPROVED.value)
