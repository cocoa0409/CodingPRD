"""Enrollment / installment / charge state machines and the conserved-principal
invariant.

Difficulty queue: non_linear_state_machine, compensating_invariant (charge half).
Corner: state_machines (invalid transitions, completion bubble-up).
"""
from test_helpers import (
    validate_error,
    fixtures,
    ApiErrorId,
    TEST_USERS,
)

REGISTRAR = TEST_USERS["registrar_headers"]


# ===========================================================================
# Difficulty: non_linear_state_machine (installment parallel axis)
# ===========================================================================
def test_installment_paid_while_siblings_overdue_and_enrollment_active(api):
    """PRD 3.6: "An installment reaches `PAID` from either `SCHEDULED` or
    `OVERDUE` when its cumulative `paid_amount_cents` is at least its
    `amount_cents`." ... "When an `OVERDUE` installment reaches `PAID`, the
    enrollment's `delinquent_installment_count` is decremented"

    With 3 installments OVERDUE, paying one drives it to PAID while the other
    two remain OVERDUE and the enrollment stays ACTIVE — the installment axis
    evolves independently of the enrollment axis.

    Design: Difficulty/non_linear_state_machine/installment_parallel_dimension_independent_of_enrollment
    """
    base = fixtures.setup_active_enrollment(
        charges_cents=200000, aid_cents=0, installment_count=5, down_payment_pct=0,
        plan_fee_cents=0,
    )
    enr_id = base["enrollment"]["id"]
    fixtures.set_clock(base["institution"]["id"], "2026-11-05T00:00:00.000Z")
    fixtures.run_delinquency(enr_id)

    installments = fixtures.list_installments(enr_id)
    overdue = [i for i in installments if i["status"] == "OVERDUE"]
    assert len(overdue) == 3, installments
    first = overdue[0]
    fixtures.settle_installment(enr_id, first["id"], first["amount_cents"])

    refetched = fixtures.list_installments(enr_id)
    paid_one = [i for i in refetched if i["id"] == first["id"]][0]
    assert paid_one["status"] == "PAID", paid_one
    enr = fixtures.get_enrollment(enr_id)
    assert enr["status"] == "ACTIVE", enr
    assert enr["delinquent_installment_count"] == 2, enr


def test_installment_paid_while_others_scheduled_keeps_enrollment_active(api):
    """PRD 3.6: "An installment reaches `PAID` from either `SCHEDULED` or
    `OVERDUE` when its cumulative `paid_amount_cents` is at least its
    `amount_cents`." ... "Whenever the last open installment is paid so that
    every installment is `PAID` and the down payment has been collected, the
    system automatically bubbles the enrollment `ACTIVE -> COMPLETED`"

    Paying only the first installment of a non-delinquent 4PAY plan drives that
    one installment to PAID while the other three stay SCHEDULED and the
    enrollment stays ACTIVE — the installment axis advances without forcing the
    enrollment axis off ACTIVE.

    Design: Difficulty/non_linear_state_machine/installment_parallel_dimension_independent_of_enrollment
    """
    base = fixtures.setup_active_enrollment(charges_cents=500000, aid_cents=100000)
    enr_id = base["enrollment"]["id"]
    fixtures.settle_down_payment(enr_id, 80000)
    installments = fixtures.list_installments(enr_id)
    fixtures.settle_installment(enr_id, installments[0]["id"], 80000)

    refetched = fixtures.list_installments(enr_id)
    assert refetched[0]["status"] == "PAID", refetched
    assert [i["status"] for i in refetched[1:]] == ["SCHEDULED", "SCHEDULED", "SCHEDULED"]
    enr = fixtures.get_enrollment(enr_id)
    assert enr["status"] == "ACTIVE", enr


# ===========================================================================
# Difficulty: non_linear_state_machine (charge POSTED->REVERSED negative recalc)
# ===========================================================================
def test_charge_reversal_runs_negative_recalc(api):
    """PRD 3.3: "A `Registrar` may reverse a posted charge, moving it
    `POSTED -> REVERSED`" ... "once `REVERSED` it is excluded, and the reversal
    recomputes `gross_charges_cents` and `net_after_aid_cents`."
    PRD 3.5: "reversing a posted charge lowers it, a negative delta" ... "the
    system takes the magnitude of the credit and walks the scheduled
    installments from the *latest* sequence index backward, reducing each
    installment's `amount_cents`"

    Posting an extra 60000 charge onto ACTIVE [80000 x4] then reversing it
    returns scheduled_balance to 320000 and gross to 500000.

    Design: Difficulty/non_linear_state_machine/charge_cycle_posted_reversed_recalc
    """
    base = fixtures.setup_active_enrollment(charges_cents=500000, aid_cents=100000)
    enr_id = base["enrollment"]["id"]
    extra = fixtures.post_charge(enr_id, 60000, kind="FEE")
    fixtures.get_success_data(api.reverse_charge(extra["id"], REGISTRAR))

    charge = fixtures.get_success_data(api.get_charge(extra["id"], REGISTRAR))
    assert charge["status"] == "REVERSED", charge
    enr = fixtures.get_enrollment(enr_id)
    assert enr["scheduled_balance_cents"] == 320000, enr
    assert enr["gross_charges_cents"] == 500000, enr


def test_charge_reversal_respread_reduces_latest_installments(api):
    """PRD 3.5: "For a negative delta, the system takes the magnitude of the
    credit and walks the scheduled installments from the *latest* sequence index
    backward, reducing each installment's `amount_cents` by as much of the
    remaining credit as that installment holds (never below zero), and stopping
    once the credit is exhausted — reductions come off the *latest* installments
    first."

    The POSTED->REVERSED branch's negative recalc runs the latest-first
    reduction: posting 60000 (spread +15000 onto each of [80000 x4] -> [95000 x4])
    then reversing it walks back from the latest installment, reducing each by as
    much of the 60000 credit as that installment holds and stopping once the credit
    is exhausted — the entire 60000 comes off installment 4 (95000 -> 35000),
    leaving [95000, 95000, 95000, 35000], the divergent side-effect set of the
    reversal branch.

    Design: Difficulty/non_linear_state_machine/charge_cycle_posted_reversed_recalc
    """
    base = fixtures.setup_active_enrollment(charges_cents=500000, aid_cents=100000)
    enr_id = base["enrollment"]["id"]
    extra = fixtures.post_charge(enr_id, 60000, kind="FEE")
    after_post = fixtures.list_installments(enr_id)
    assert [i["amount_cents"] for i in after_post] == [95000, 95000, 95000, 95000]

    fixtures.get_success_data(api.reverse_charge(extra["id"], REGISTRAR))
    after_reverse = fixtures.list_installments(enr_id)
    assert [i["amount_cents"] for i in after_reverse] == [95000, 95000, 95000, 35000]
    enr = fixtures.get_enrollment(enr_id)
    assert enr["net_after_aid_cents"] == 400000, enr


# ===========================================================================
# Difficulty: compensating_invariant (charge post+reverse conserves principal)
# ===========================================================================
def test_charge_post_then_reverse_conserves_principal_identity(api):
    """PRD 3.5: "reversing a posted charge lowers it, a negative delta" ...
    "After the re-spread, `scheduled_balance_cents` is recomputed as the sum of
    `amount_cents` over the scheduled installments plus the sum over any overdue
    installments."
    PRD 2.9: "the still-owed financed amount, the paid principal, and the
    scheduled installments always reconcile."

    Posting 60000 then reversing returns scheduled_balance to 320000 and
    net_after_aid to 400000; the identity scheduled_balance + paid_principal ==
    net_after_aid holds (320000 + 80000 == 400000).

    Design: Difficulty/compensating_invariant/charge_post_then_reverse_conserves_financed_principal
    """
    base = fixtures.setup_active_enrollment(charges_cents=500000, aid_cents=100000)
    enr_id = base["enrollment"]["id"]
    fixtures.settle_down_payment(enr_id, 80000)  # paid_principal 80000
    extra = fixtures.post_charge(enr_id, 60000, kind="FEE")
    fixtures.get_success_data(api.reverse_charge(extra["id"], REGISTRAR))

    enr = fixtures.get_enrollment(enr_id)
    assert enr["scheduled_balance_cents"] == 320000, enr
    assert enr["net_after_aid_cents"] == 400000, enr
    assert enr["paid_principal_cents"] == 80000, enr
    assert (
        enr["scheduled_balance_cents"] + enr["paid_principal_cents"]
        == enr["net_after_aid_cents"]
    ), enr


def test_charge_post_then_reverse_restores_per_installment_amounts(api):
    """PRD 3.5: "it then adds the base to every scheduled installment and one
    extra cent to each of the earliest installments up to the remainder" ...
    "For a negative delta, the system ... walks the scheduled installments from
    the *latest* sequence index backward, reducing each installment's
    `amount_cents` by as much of the remaining credit as that installment holds
    (never below zero), and stopping once the credit is exhausted"

    The conserved quantity is the financed principal sum, not the per-line
    schedule: posting 60000 spreads +15000 onto each of [80000 x4] -> [95000 x4]
    (base onto every line), while reversing applies the asymmetric latest-first
    rule that pulls the entire 60000 credit off installment 4 (95000 -> 35000),
    yielding [95000, 95000, 95000, 35000]. The per-line totals diverge from the
    pre-charge schedule even though the schedule sum is restored (320000).

    Design: Difficulty/compensating_invariant/charge_post_then_reverse_conserves_financed_principal
    """
    base = fixtures.setup_active_enrollment(charges_cents=500000, aid_cents=100000)
    enr_id = base["enrollment"]["id"]
    before = fixtures.list_installments(enr_id)
    assert [i["amount_cents"] for i in before] == [80000, 80000, 80000, 80000]

    extra = fixtures.post_charge(enr_id, 60000, kind="FEE")
    fixtures.get_success_data(api.reverse_charge(extra["id"], REGISTRAR))

    after = fixtures.list_installments(enr_id)
    assert [i["amount_cents"] for i in after] == [95000, 95000, 95000, 35000]
    assert sum(i["amount_cents"] for i in after) == 320000


# ===========================================================================
# Corner: state_machines / invalid transitions
# ===========================================================================
def test_activate_already_active_enrollment_rejected(api):
    """PRD 3.4: "The enrollment must currently be `PENDING`, or the attempt is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/activate_already_active_returns_invalid_state
    """
    base = fixtures.setup_active_enrollment(charges_cents=500000, aid_cents=100000)
    enr_id = base["enrollment"]["id"]
    version = fixtures.current_version(enr_id)
    resp = api.activate_enrollment(
        enr_id, fixtures.factories.activate_payload(version), REGISTRAR
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_close_open_term_rejected(api):
    """PRD 3.1: "A locked term may then be closed, moving it `LOCKED -> CLOSED`;
    closing requires the term to currently be `LOCKED` (otherwise
    `ERR_INVALID_STATE`)"

    Design: Corner/state_machines/term_close_from_open_returns_invalid_state
    """
    inst = fixtures.create_institution()
    term = fixtures.create_term(inst["id"])
    resp = api.close_term(term["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_reverse_already_reversed_charge_rejected(api):
    """PRD 3.3: "reversal requires the charge to currently be `POSTED`
    (otherwise `ERR_INVALID_STATE`)"

    Design: Corner/state_machines/charge_reverse_twice_returns_invalid_state
    """
    base = fixtures.setup_active_enrollment(charges_cents=500000, aid_cents=0)
    enr_id = base["enrollment"]["id"]
    extra = fixtures.post_charge(enr_id, 60000, kind="FEE")
    fixtures.get_success_data(api.reverse_charge(extra["id"], REGISTRAR))
    resp = api.reverse_charge(extra["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Corner: state_machines / completion bubble-up
# ===========================================================================
def test_enrollment_completes_when_all_installments_paid(api):
    """PRD 3.6: "Whenever the last open installment is paid so that every
    installment is `PAID` and the down payment has been collected, the system
    automatically bubbles the enrollment `ACTIVE -> COMPLETED`; on completion
    `scheduled_balance_cents` is zero"

    A 1PAY (down 0) plan with charges 120000: paying the single installment
    drives the enrollment to COMPLETED with scheduled_balance 0.

    Design: Corner/state_machines/enrollment_completes_when_all_installments_paid
    """
    base = fixtures.setup_base(installment_count=1, down_payment_pct=0, plan_fee_cents=0)
    enr = fixtures.create_enrollment(
        base["student"]["id"], base["term"]["id"], base["template"]["id"]
    )
    fixtures.post_charge(enr["id"], 120000)
    fixtures.activate(enr["id"])
    installments = fixtures.list_installments(enr["id"])
    fixtures.settle_installment(enr["id"], installments[0]["id"], 120000)

    enr = fixtures.get_enrollment(enr["id"])
    assert enr["status"] == "COMPLETED", enr
    assert enr["scheduled_balance_cents"] == 0, enr
