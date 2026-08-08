"""Transitive cascades, diversion-satisfaction boundary, and installment miss gating
(PRD §3.3, §3.5, §3.7)."""
from test_helpers import (
    validate_error, get_success_data,
    ApiErrorId,
    make_tenant_headers, make_judge_headers, TEST_USERS,
)
from test_helpers import fixtures as fx

CLERK = TEST_USERS["clerk_headers"]
PROGRAM_ADMIN = TEST_USERS["program_admin_headers"]


# --------------------------------------------------------------------------- #
# Queue A: transitive_cascade / referral_disburse_clears_arrears_depth3        #
# --------------------------------------------------------------------------- #
def _setup_diversion_with_hearing(api):
    ctx = fx.setup_approved_rental_assistance(api, claimed_arrears_cents=200000,
                                              income_cents=200000, household_size=3)
    ctx["hearing"] = fx.schedule_hearing(api, ctx, "2026-06-01T10:00:00Z", "2026-06-01T11:00:00Z")
    return ctx


def test_disburse_clears_arrears_and_satisfies_diversion(api):
    """PRD §3.3: "Disbursement then reduces the case's net_arrears_cents by
    disbursed_amount_cents (the first cascade hop). If that reduction brings the case's
    outstanding arrears to exactly 0 while the case is IN_DIVERSION, the case is
    automatically satisfied — it advances to DIVERSION_SATISFIED".

    Design: Difficulty/transitive_cascade/referral_disburse_clears_arrears_depth3_cascade
    """
    ctx = _setup_diversion_with_hearing(api)
    fx.disburse_referral(api, ctx["referral"]["id"])
    case = get_success_data(api.get_case(ctx["case"]["id"], CLERK))
    assert case["net_arrears_cents"] == 0
    assert case["status"] == "DIVERSION_SATISFIED"


def test_disburse_cascade_cancels_hearing_and_frees_slot(api):
    """PRD §3.7: DIVERSION_SATISFIED "triggers the closing cascade". PRD §2.9: a court's
    hearings_scheduled_count "decreases by 1 whenever a scheduled hearing leaves
    SCHEDULED by being held, cancelled, or continued." PRD §3.7 outcome becomes DIVERTED
    "when a diversion is satisfied".

    Design: Difficulty/transitive_cascade/referral_disburse_clears_arrears_depth3_cascade
    """
    ctx = _setup_diversion_with_hearing(api)
    fx.disburse_referral(api, ctx["referral"]["id"])
    hearing = get_success_data(api.get_hearing(ctx["hearing"]["id"], CLERK))
    court = get_success_data(api.get_court(ctx["court"]["id"], CLERK))
    case = get_success_data(api.get_case(ctx["case"]["id"], CLERK))
    assert hearing["status"] == "CANCELLED"
    assert court["hearings_scheduled_count"] == 0
    assert case["outcome"] == "DIVERTED"


# --------------------------------------------------------------------------- #
# Queue A: transitive_cascade / plan_default_relitigates_case_depth2           #
# --------------------------------------------------------------------------- #
def _setup_missed_installment(api):
    ctx = fx.setup_answered_case(api, claimed_arrears_cents=600000)
    plan = fx.open_plan(api, ctx, 600000, 3, first_due_date="2026-05-20T00:00:00Z")
    fx.accept_plan_as_tenant(api, ctx, plan["id"])
    ctx["plan"] = plan
    ctx["inst1"] = fx.installments_of(api, plan["id"])[0]
    fx.set_clock(api, "2026-05-21T00:00:00Z")  # past first due_date 2026-05-20
    return ctx


def test_installment_miss_defaults_plan(api):
    """PRD §3.5: "A clerk marks an installment MISSED, moving it from DUE to MISSED,
    only after its due_date has strictly passed ... a single missed installment bubbles
    the plan up to DEFAULTED."

    Design: Difficulty/transitive_cascade/plan_default_relitigates_case_depth2_cascade
    """
    ctx = _setup_missed_installment(api)
    missed = get_success_data(api.transition_installment(
        ctx["inst1"]["id"], {"to_status": "MISSED"}, CLERK))
    plan = get_success_data(api.get_payment_plan(ctx["plan"]["id"], CLERK))
    assert missed["status"] == "MISSED"
    assert plan["status"] == "DEFAULTED"


def test_plan_default_relitigates_case(api):
    """PRD §3.5: "When a plan defaults and its case was IN_DIVERSION, the case is
    relitigated — pushed from IN_DIVERSION to IN_LITIGATION."

    Design: Difficulty/transitive_cascade/plan_default_relitigates_case_depth2_cascade
    """
    ctx = _setup_missed_installment(api)
    get_success_data(api.transition_installment(
        ctx["inst1"]["id"], {"to_status": "MISSED"}, CLERK))
    case = get_success_data(api.get_case(ctx["case"]["id"], CLERK))
    assert case["status"] == "IN_LITIGATION"


# --------------------------------------------------------------------------- #
# Queue A: boundary_precision_check / net_arrears_exactly_zero                  #
# --------------------------------------------------------------------------- #
def test_net_arrears_exactly_zero_flips_to_diversion_satisfied(api):
    """PRD §3.3: "If that reduction brings the case's outstanding arrears to exactly 0
    while the case is IN_DIVERSION, the case is automatically satisfied — it advances to
    DIVERSION_SATISFIED".

    Design: Difficulty/boundary_precision_check/net_arrears_exactly_zero_triggers_diversion_satisfied
    """
    ctx = fx.setup_approved_rental_assistance(api, claimed_arrears_cents=200000,
                                              income_cents=200000, household_size=3)
    disbursed = get_success_data(api.transition_referral(
        ctx["referral"]["id"], {"to_status": "DISBURSED"}, PROGRAM_ADMIN))
    case = get_success_data(api.get_case(ctx["case"]["id"], CLERK))
    assert disbursed["disbursed_amount_cents"] == 200000
    assert case["net_arrears_cents"] == 0
    assert case["status"] == "DIVERSION_SATISFIED"


def test_net_arrears_positive_remainder_stays_in_diversion(api):
    """PRD §3.3: satisfaction happens only when the reduction "brings the case's
    outstanding arrears to exactly 0 while the case is IN_DIVERSION". A disbursement that
    leaves a positive balance therefore leaves the case IN_DIVERSION. (household_size 1
    income cap 300000 binds below the 500000 arrears, so 300000 is disbursed.)

    Design: Difficulty/boundary_precision_check/net_arrears_exactly_zero_triggers_diversion_satisfied
    """
    ctx = fx.setup_approved_rental_assistance(api, claimed_arrears_cents=500000,
                                              income_cents=200000, household_size=1)
    disbursed = get_success_data(api.transition_referral(
        ctx["referral"]["id"], {"to_status": "DISBURSED"}, PROGRAM_ADMIN))
    case = get_success_data(api.get_case(ctx["case"]["id"], CLERK))
    assert disbursed["disbursed_amount_cents"] == 300000
    assert case["net_arrears_cents"] == 200000
    assert case["status"] == "IN_DIVERSION"


# --------------------------------------------------------------------------- #
# Queue B: judgment vacate cascade + installment miss gating                   #
# --------------------------------------------------------------------------- #
def test_judgment_vacate_cancels_lockout_and_dismisses_case(api):
    """PRD §3.7: "Vacating a judgment — from either ENTERED or STAYED — dismisses the
    underlying case: the case moves from JUDGMENT_ENTERED to DISMISSED, its closed_at is
    stamped and its outcome set to DISMISSED (the first cascade hop), and any REQUESTED
    or SCHEDULED lockout order on the case is cancelled and its officer freed (the second
    hop)."

    Design: Corner/state_machines/judgment_vacate_cancels_lockout_and_dismisses_case
    """
    ctx = fx.setup_scheduled_lockout(api, claimed_arrears_cents=600000,
                                     scheduled_at="2026-06-01T10:00:00Z")
    get_success_data(api.transition_judgment(
        ctx["judgment"]["id"], {"to_status": "VACATED"}, make_judge_headers("judge-1")))
    judgment = get_success_data(api.get_judgment(ctx["judgment"]["id"], CLERK))
    lockout = get_success_data(api.get_lockout_order(ctx["lockout"]["id"], CLERK))
    case = get_success_data(api.get_case(ctx["case"]["id"], CLERK))
    assert judgment["status"] == "VACATED"
    assert lockout["status"] == "CANCELLED"
    assert case["status"] == "DISMISSED"
    assert case["outcome"] == "DISMISSED"


def test_installment_miss_before_due_returns_not_due(api):
    """PRD §3.5: "A clerk marks an installment MISSED ... only after its due_date has
    strictly passed (attempting it at or before the due date yields
    ERR_INSTALLMENT_NOT_DUE)".

    Design: Corner/validations/installment_miss_before_due_returns_not_due
    """
    ctx = fx.setup_answered_case(api, claimed_arrears_cents=600000)
    plan = fx.open_plan(api, ctx, 600000, 3, first_due_date="2026-05-20T00:00:00Z")
    fx.accept_plan_as_tenant(api, ctx, plan["id"])
    inst1 = fx.installments_of(api, plan["id"])[0]
    # Clock still at default 2026-05-01, before due 2026-05-20.
    resp = api.transition_installment(inst1["id"], {"to_status": "MISSED"}, CLERK)
    validate_error(resp, ApiErrorId.ERR_INSTALLMENT_NOT_DUE.value, expected_status=409)
