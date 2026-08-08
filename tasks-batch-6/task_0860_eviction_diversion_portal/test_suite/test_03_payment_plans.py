"""Payment-plan negotiation cycle, installment schedule, and acceptance gating
(PRD §3.5, §2.8)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    make_landlord_headers, make_tenant_headers, TEST_USERS,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

CLERK = TEST_USERS["clerk_headers"]


# --------------------------------------------------------------------------- #
# Queue A: non_linear_state_machine / payment_plan_counter_negotiation_cycle   #
# --------------------------------------------------------------------------- #
def test_plan_counter_cycle_returns_to_proposed_tenant_turn(api):
    """PRD §3.5: "Countering moves a PROPOSED plan to COUNTERED, and a subsequent
    counter moves it from COUNTERED back to PROPOSED, so the offer can bounce between
    the parties indefinitely."

    Design: Difficulty/non_linear_state_machine/payment_plan_counter_negotiation_cycle
    """
    ctx = fx.setup_answered_case(api, claimed_arrears_cents=600000)
    plan = fx.open_plan(api, ctx, 600000, 6, proposed_by="LANDLORD")
    # current_proposer is TENANT; tenant counters -> COUNTERED (proposer flips to LANDLORD)
    get_success_data(api.respond_payment_plan(
        plan["id"], {"decision": "COUNTER", "new_total_cents": 660000, "new_installment_count": 6},
        make_tenant_headers(ctx["tenant"]["id"])))
    # landlord counters back -> PROPOSED (proposer flips to TENANT)
    data = get_success_data(api.respond_payment_plan(
        plan["id"], {"decision": "COUNTER", "new_total_cents": 600000, "new_installment_count": 6},
        make_landlord_headers(ctx["landlord"]["id"])))
    assert data["status"] == "PROPOSED"
    assert data["current_proposer"] == "TENANT"
    assert data["total_cents"] == 600000


def test_plan_counter_flips_proposer_on_first_counter(api):
    """PRD §3.5: "A counter-offer supplies new_total_cents and new_installment_count;
    it overwrites the plan's total_cents and installment_count with the countered
    terms and flips current_proposer to the other party."

    Design: Difficulty/non_linear_state_machine/payment_plan_counter_negotiation_cycle
    """
    ctx = fx.setup_answered_case(api, claimed_arrears_cents=600000)
    plan = fx.open_plan(api, ctx, 600000, 6, proposed_by="LANDLORD")
    data = get_success_data(api.respond_payment_plan(
        plan["id"], {"decision": "COUNTER", "new_total_cents": 660000, "new_installment_count": 6},
        make_tenant_headers(ctx["tenant"]["id"])))
    assert data["status"] == "COUNTERED"
    assert data["current_proposer"] == "LANDLORD"
    assert data["total_cents"] == 660000
    assert data["installment_count"] == 6


# --------------------------------------------------------------------------- #
# Queue A: combinatorial_formula / installment_schedule_remainder_to_last      #
# --------------------------------------------------------------------------- #
def test_installment_schedule_remainder_to_last_installment(api):
    """PRD §3.5: "first compute the per-installment floor as the total divided by the
    count, dropping any fraction; the leftover remainder is the total minus that floor
    multiplied by the count. Every installment is assigned the floor amount, except the
    final installment, which additionally absorbs the entire remainder".

    Design: Difficulty/combinatorial_formula/installment_schedule_remainder_to_last
    """
    ctx = fx.setup_answered_case(api, claimed_arrears_cents=100000)
    plan = fx.open_plan(api, ctx, 100000, 3)
    fx.accept_plan_as_tenant(api, ctx, plan["id"])
    insts = fx.installments_of(api, plan["id"])
    amounts = [i["amount_cents"] for i in insts]
    assert amounts == [33333, 33333, 33334]


def test_installment_schedule_sum_conserves_total(api):
    """PRD §3.5: "so the sum of all installment amounts equals the plan total exactly."
    PRD §3.5: "a due_date computed as the plan's first_due_date plus thirty days for
    each position past the first".

    Design: Difficulty/combinatorial_formula/installment_schedule_remainder_to_last
    """
    ctx = fx.setup_answered_case(api, claimed_arrears_cents=100000)
    plan = fx.open_plan(api, ctx, 100000, 3, first_due_date="2026-05-20T00:00:00Z")
    fx.accept_plan_as_tenant(api, ctx, plan["id"])
    insts = fx.installments_of(api, plan["id"])
    assert sum(i["amount_cents"] for i in insts) == 100000
    assert [i["sequence"] for i in insts] == [1, 2, 3]
    assert insts[0]["due_date"] == "2026-05-20T00:00:00.000Z"
    assert insts[1]["due_date"] == "2026-06-19T00:00:00.000Z"
    assert insts[2]["due_date"] == "2026-07-19T00:00:00.000Z"


# --------------------------------------------------------------------------- #
# Queue A: priority_pair_validation_conflict / state_beats_fiscal              #
# --------------------------------------------------------------------------- #
def test_accept_rejected_plan_state_beats_fiscal_returns_invalid_state(api):
    """PRD §2.8: "checks are applied in a fixed order and the first failing check
    determines the error returned. The order is: ... (6) state legality ... (11) fiscal
    sufficiency ... Lower-numbered categories always take precedence over higher-numbered
    ones." PRD §3.5: acceptance "moves the plan from PROPOSED or COUNTERED to ACCEPTED".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_plan_accept_returns_invalid_state
    """
    ctx = fx.setup_answered_case(api, claimed_arrears_cents=600000)
    plan = fx.open_plan(api, ctx, 100000, 2)  # total 100000 < arrears 600000 (fiscal fault)
    # Tenant rejects -> plan terminal REJECTED (state fault)
    get_success_data(api.respond_payment_plan(
        plan["id"], {"decision": "REJECT"}, make_tenant_headers(ctx["tenant"]["id"])))
    resp = api.respond_payment_plan(
        plan["id"], {"decision": "ACCEPT"}, make_tenant_headers(ctx["tenant"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_accept_valid_plan_below_arrears_isolated_fiscal_returns_plan_insufficient(api):
    """PRD §3.5: "acceptance ... but only if the plan's total_cents is at least the
    case's current final outstanding arrears; a plan that would leave arrears uncovered
    is refused with ERR_PLAN_INSUFFICIENT." (Isolated fiscal-only path: plan state is
    still PROPOSED, so only priority-11 fiscal can fail.)

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_plan_accept_returns_invalid_state
    """
    ctx = fx.setup_answered_case(api, claimed_arrears_cents=600000)
    plan = fx.open_plan(api, ctx, 100000, 2)  # PROPOSED, total below arrears
    resp = api.respond_payment_plan(
        plan["id"], {"decision": "ACCEPT"}, make_tenant_headers(ctx["tenant"]["id"]))
    validate_error(resp, ApiErrorId.ERR_PLAN_INSUFFICIENT.value, expected_status=409)


# --------------------------------------------------------------------------- #
# Queue B: plan error paths + bubble-up                                        #
# --------------------------------------------------------------------------- #
def test_plan_respond_wrong_party_returns_wrong_turn(api):
    """PRD §3.5: "the acting party must be the one whose turn it is — the counterparty
    named by current_proposer. A response from the wrong party is refused with
    ERR_WRONG_PARTY_TURN."

    Design: Corner/validations/plan_respond_wrong_party_returns_wrong_turn
    """
    ctx = fx.setup_answered_case(api, claimed_arrears_cents=600000)
    plan = fx.open_plan(api, ctx, 600000, 6, proposed_by="LANDLORD")  # current_proposer TENANT
    resp = api.respond_payment_plan(
        plan["id"], {"decision": "COUNTER", "new_total_cents": 620000, "new_installment_count": 6},
        make_landlord_headers(ctx["landlord"]["id"]))
    validate_error(resp, ApiErrorId.ERR_WRONG_PARTY_TURN.value, expected_status=409)


def test_plan_accept_insufficient_total_returns_plan_insufficient(api):
    """PRD §3.5: "a plan that would leave arrears uncovered is refused with
    ERR_PLAN_INSUFFICIENT."

    Design: Corner/validations/plan_accept_insufficient_total_returns_plan_insufficient
    """
    ctx = fx.setup_answered_case(api, claimed_arrears_cents=600000)
    plan = fx.open_plan(api, ctx, 100000, 2)
    resp = api.respond_payment_plan(
        plan["id"], {"decision": "ACCEPT"}, make_tenant_headers(ctx["tenant"]["id"]))
    validate_error(resp, ApiErrorId.ERR_PLAN_INSUFFICIENT.value, expected_status=409)


def test_installment_pay_completes_plan_bubbles_case_diversion(api):
    """PRD §3.5: "Paying the last outstanding installment — the moment every installment
    of the plan is PAID — bubbles the plan up from ACCEPTED to COMPLETED, which in turn
    satisfies the case (DIVERSION_SATISFIED)."

    Design: Corner/state_machines/installment_pay_completes_plan_bubbles_case_diversion
    """
    ctx = fx.setup_answered_case(api, claimed_arrears_cents=100000)
    plan = fx.open_plan(api, ctx, 100000, 1)
    fx.accept_plan_as_tenant(api, ctx, plan["id"])
    inst = fx.installments_of(api, plan["id"])[0]
    get_success_data(api.transition_installment(
        inst["id"], {"to_status": "PAID"}, make_tenant_headers(ctx["tenant"]["id"])))
    plan_data = get_success_data(api.get_payment_plan(plan["id"], CLERK))
    case_data = get_success_data(api.get_case(ctx["case"]["id"], CLERK))
    assert plan_data["status"] == "COMPLETED"
    assert case_data["status"] == "DIVERSION_SATISFIED"
    assert case_data["net_arrears_cents"] == 0
