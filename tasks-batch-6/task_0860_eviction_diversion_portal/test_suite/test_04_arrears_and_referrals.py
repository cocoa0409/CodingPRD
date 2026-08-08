"""Dual-variant arrears, rental-assistance award, money conservation, and referral
error paths (PRD §3.3, §3.5, §2.7, §2.9)."""
from test_helpers import (
    validate_error, get_success_data,
    ApiErrorId,
    make_tenant_headers, TEST_USERS,
    assert_arrears_conservation,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

CLERK = TEST_USERS["clerk_headers"]
PROGRAM_ADMIN = TEST_USERS["program_admin_headers"]


# --------------------------------------------------------------------------- #
# Queue A: dual_variant_calc / case_net_arrears_provisional_vs_final           #
# --------------------------------------------------------------------------- #
def test_net_arrears_provisional_equals_claimed_at_filing(api):
    """PRD §3.2: "At filing the case's outstanding balance, net_arrears_cents, is
    seeded to the claimed amount — the provisional variant of the arrears calculation,
    which simply equals claimed_arrears_cents before any money has moved."

    Design: Difficulty/dual_variant_calc/case_net_arrears_provisional_vs_final
    """
    ctx = fx.setup_answered_case(api, claimed_arrears_cents=600000)
    case = get_success_data(api.get_case(ctx["case"]["id"], CLERK))
    assert case["net_arrears_cents"] == 600000


def test_net_arrears_final_drops_by_paid_installment(api):
    """PRD §3.5: "Paying stamps paid_at with the current instant and reduces the case's
    net_arrears_cents by that installment's amount_cents." PRD §3.5: final arrears "is
    always the claimed amount at filing minus the sum of amount_cents across the case's
    paid installments".

    Design: Difficulty/dual_variant_calc/case_net_arrears_provisional_vs_final
    """
    ctx = fx.setup_answered_case(api, claimed_arrears_cents=600000)
    plan = fx.open_plan(api, ctx, 600000, 6)
    fx.accept_plan_as_tenant(api, ctx, plan["id"])
    inst1 = fx.installments_of(api, plan["id"])[0]
    paid = get_success_data(api.transition_installment(
        inst1["id"], {"to_status": "PAID"}, make_tenant_headers(ctx["tenant"]["id"])))
    case = get_success_data(api.get_case(ctx["case"]["id"], CLERK))
    assert paid["status"] == "PAID"
    assert paid["amount_cents"] == 100000
    assert case["net_arrears_cents"] == 500000


# --------------------------------------------------------------------------- #
# Queue A: dual_variant_calc / rental_assistance_requested_vs_disbursed        #
# --------------------------------------------------------------------------- #
def _setup_ra_requested_vs_disbursed(api):
    """Case 600000, RA referral APPROVED (requested=500000 income cap), then a 200000
    installment PAID (arrears -> 400000), so disbursal recomputes to 400000."""
    ctx = fx.setup_answered_case(api, claimed_arrears_cents=600000, income_cents=200000,
                                 household_size=3)
    ref = fx.submit_referral(api, ctx, "RENTAL_ASSISTANCE")
    ctx["referral"] = fx.approve_referral(api, ref["id"])
    plan = fx.open_plan(api, ctx, 600000, 3)  # three 200000 installments
    fx.accept_plan_as_tenant(api, ctx, plan["id"])
    inst1 = fx.installments_of(api, plan["id"])[0]
    get_success_data(api.transition_installment(
        inst1["id"], {"to_status": "PAID"}, make_tenant_headers(ctx["tenant"]["id"])))
    return ctx


def test_ra_requested_amount_is_income_cap_at_approval(api):
    """PRD §3.3: "approval computes and stores requested_amount_cents as the provisional
    award: the smallest of three independent figures — the case's current outstanding
    arrears, the household income cap, and the program's remaining budget." (income cap
    = 300000 + (3-1)*100000 = 500000, the binding term.)

    Design: Difficulty/dual_variant_calc/rental_assistance_requested_vs_disbursed
    """
    ctx = _setup_ra_requested_vs_disbursed(api)
    assert ctx["referral"]["requested_amount_cents"] == 500000


def test_ra_disbursed_recomputed_below_requested(api):
    """PRD §3.3: "the final award, disbursed_amount_cents, is recomputed as the smallest
    of three figures — the case's current outstanding arrears at this instant, the
    requested_amount_cents fixed at approval, and the program's currently remaining
    budget — because the arrears may have fallen through interim payments between
    approval and disbursement, so the disbursed amount can be strictly less than the
    requested amount."

    Design: Difficulty/dual_variant_calc/rental_assistance_requested_vs_disbursed
    """
    ctx = _setup_ra_requested_vs_disbursed(api)
    disbursed = get_success_data(api.transition_referral(
        ctx["referral"]["id"], {"to_status": "DISBURSED"}, PROGRAM_ADMIN))
    case = get_success_data(api.get_case(ctx["case"]["id"], CLERK))
    assert disbursed["disbursed_amount_cents"] == 400000
    assert case["net_arrears_cents"] == 0


# --------------------------------------------------------------------------- #
# Queue A: combinatorial_formula / rental_assistance_award_nested_min          #
# --------------------------------------------------------------------------- #
def test_ra_award_income_cap_binds_over_arrears_and_budget(api):
    """PRD §3.3: "the smallest of three independent figures — the case's current
    outstanding arrears, the household income cap, and the program's remaining budget.
    The income cap is a base of three thousand dollars plus one thousand dollars for
    each household member beyond the first; that is, INCOME_CAP_BASE_CENTS of 300000
    plus household_size minus one, multiplied by INCOME_CAP_PER_MEMBER_CENTS of 100000."

    Design: Difficulty/combinatorial_formula/rental_assistance_award_nested_min_income_cap_binds
    """
    ctx = fx.setup_answered_case(api, claimed_arrears_cents=600000, income_cents=200000,
                                 household_size=3)
    ref = fx.submit_referral(api, ctx, "RENTAL_ASSISTANCE")
    approved = fx.approve_referral(api, ref["id"])
    # min(arrears 600000, income_cap 500000, budget 5000000) == 500000 (cap binds)
    assert approved["status"] == "APPROVED"
    assert approved["requested_amount_cents"] == 500000


def test_ra_award_binds_below_arrears_and_budget(api):
    """PRD §3.3: "the smallest of three independent figures — the case's current
    outstanding arrears, the household income cap, and the program's remaining budget."
    The 500000 cap is strictly below both the 600000 arrears and 5000000 budget inputs.

    Design: Difficulty/combinatorial_formula/rental_assistance_award_nested_min_income_cap_binds
    """
    ctx = fx.setup_answered_case(api, claimed_arrears_cents=600000, income_cents=200000,
                                 household_size=3)
    ref = fx.submit_referral(api, ctx, "RENTAL_ASSISTANCE")
    approved = fx.approve_referral(api, ref["id"])
    assert approved["requested_amount_cents"] < 600000
    assert approved["requested_amount_cents"] < 5000000
    assert approved["requested_amount_cents"] == 300000 + (3 - 1) * 100000


# --------------------------------------------------------------------------- #
# Queue A: compensating_invariant / arrears_money_conservation                 #
# --------------------------------------------------------------------------- #
def test_arrears_conservation_after_installment_payment(api):
    """PRD §2.9: "a case's outstanding arrears (net_arrears_cents) always equals the
    claimed amount at filing reduced by paid installments and disbursed rental
    assistance, floored at 0".

    Design: Difficulty/compensating_invariant/arrears_money_conservation_on_installment_payment
    """
    ctx = fx.setup_answered_case(api, claimed_arrears_cents=600000)
    plan = fx.open_plan(api, ctx, 600000, 6)
    fx.accept_plan_as_tenant(api, ctx, plan["id"])
    inst1 = fx.installments_of(api, plan["id"])[0]
    get_success_data(api.transition_installment(
        inst1["id"], {"to_status": "PAID"}, make_tenant_headers(ctx["tenant"]["id"])))
    case = get_success_data(api.get_case(ctx["case"]["id"], CLERK))
    assert case["net_arrears_cents"] == 500000
    # net + paid(100000) + disbursed(0) == claimed(600000)
    assert_arrears_conservation(case, paid_sum=100000, disbursed_sum=0)


def test_arrears_conservation_holds_before_any_payment(api):
    """PRD §2.9: "a case's outstanding arrears (net_arrears_cents) always equals the
    claimed amount at filing reduced by paid installments and disbursed rental
    assistance, floored at 0". With no money moved, net equals claimed exactly.

    Design: Difficulty/compensating_invariant/arrears_money_conservation_on_installment_payment
    """
    ctx = fx.setup_answered_case(api, claimed_arrears_cents=600000)
    plan = fx.open_plan(api, ctx, 600000, 6)
    fx.accept_plan_as_tenant(api, ctx, plan["id"])
    case = get_success_data(api.get_case(ctx["case"]["id"], CLERK))
    assert case["net_arrears_cents"] == 600000
    assert_arrears_conservation(case, paid_sum=0, disbursed_sum=0)


# --------------------------------------------------------------------------- #
# Queue B: referral error paths                                                #
# --------------------------------------------------------------------------- #
def test_legal_aid_disburse_returns_not_disbursable(api):
    """PRD §3.3: "the referral must be of type RENTAL_ASSISTANCE (attempting to disburse
    a LEGAL_AID referral is refused with ERR_NOT_DISBURSABLE)".

    Design: Corner/validations/legal_aid_disburse_returns_not_disbursable
    """
    ctx = fx.setup_answered_case(api, claimed_arrears_cents=600000)
    ref = fx.submit_referral(api, ctx, "LEGAL_AID", provider_name="Legal Aid Society")
    fx.approve_referral(api, ref["id"])
    resp = api.transition_referral(ref["id"], {"to_status": "DISBURSED"}, PROGRAM_ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_DISBURSABLE.value, expected_status=409)


def test_referral_denied_then_disburse_returns_invalid_state(api):
    """PRD §3.3: "A referral may instead be denied, moving it from SUBMITTED to DENIED."
    PRD §2.8: "(6) state legality — the target resource is in a state from which the
    requested transition is legal, else ERR_INVALID_STATE".

    Design: Corner/state_machines/referral_denied_then_disburse_returns_invalid_state
    """
    ctx = fx.setup_answered_case(api, claimed_arrears_cents=600000)
    ref = fx.submit_referral(api, ctx, "RENTAL_ASSISTANCE")
    get_success_data(api.transition_referral(ref["id"], {"to_status": "DENIED"}, PROGRAM_ADMIN))
    resp = api.transition_referral(ref["id"], {"to_status": "DISBURSED"}, PROGRAM_ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_assistance_budget_exhausted_returns_budget_exceeded(api):
    """PRD §3.3: "the program's remaining budget must be at least one cent (a fully
    exhausted budget yields ERR_ASSISTANCE_BUDGET_EXCEEDED)."

    Design: Corner/validations/assistance_budget_exhausted_returns_budget_exceeded
    """
    # Tenant household_size 50 lifts income cap above 5000000 so it never binds.
    ctx = fx.setup_answered_case(api, claimed_arrears_cents=5000000, income_cents=500000,
                                 household_size=50)
    ref1 = fx.submit_referral(api, ctx, "RENTAL_ASSISTANCE")
    fx.approve_referral(api, ref1["id"])
    fx.disburse_referral(api, ref1["id"])  # drains 5000000 budget to 0
    # Second case, same tenant/landlord/court context.
    case2 = fx.file_case(api, ctx, claimed_arrears_cents=100000)
    fx.serve_case(api, case2["id"])
    fx.answer_case(api, ctx, case2["id"])
    ref2 = get_success_data(api.create_referral(
        f.create_referral_payload(case2["id"], "RENTAL_ASSISTANCE", provider_name="RA2"),
        make_tenant_headers(ctx["tenant"]["id"])))
    fx.approve_referral(api, ref2["id"])
    resp = api.transition_referral(ref2["id"], {"to_status": "DISBURSED"}, PROGRAM_ADMIN)
    validate_error(resp, ApiErrorId.ERR_ASSISTANCE_BUDGET_EXCEEDED.value, expected_status=409)
