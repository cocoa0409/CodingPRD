"""Commencement cascades, death cascades, QDRO conservation, COLA gating, and the
payment suspend/resume cycle.

Translates transitive_cascade and compensating_invariant (QDRO half)
difficulty instances (queue A), plus the payment-related state_machine and
validation corner instances (queue B).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_plan_payload,
    create_participant,
    add_standard_comp_330k,
    setup_terminated_vested_participant_330k,
    create_approved_single_life_election,
    create_qualified_percentage_qdro,
    create_submitted_percentage_qdro,
    setup_in_pay_payment,
    assert_qdro_conservation,
)

SPONSOR = TEST_USERS["plan_sponsor_headers"]
ADMIN = TEST_USERS["benefits_admin_headers"]
ADM_A = TEST_USERS["benefits_admin_a_headers"]
ADM_B = TEST_USERS["benefits_admin_b_headers"]


def _commence_330k(api, plan_overrides=None):
    plan, participant = setup_terminated_vested_participant_330k(**(plan_overrides or {}))
    election = create_approved_single_life_election(participant["id"])
    commenced = validate_success(api.commence_election(election["id"], ADM_B))
    return plan, participant, election, commenced


# ---------------------------------------------------------------------------
# transitive_cascade / commence_cascades_payment_then_retire_depth3
# ---------------------------------------------------------------------------
def test_commence_creates_pending_payment_with_base(api):
    """PRD §3.4: "Commencement creates a `BenefitPayment` in `PENDING_SETUP` with its
    `base_monthly_cents` computed by the payment-setup rule (which nets out qualified
    QDRO carve-outs, §3.5), and it cascades the participant from `TERMINATED` to
    `RETIRED`."

    Design: Difficulty/transitive_cascade/commence_cascades_payment_then_retire_depth3
    """
    plan, participant, election, commenced = _commence_330k(api)
    assert commenced["status"] == "COMMENCED"
    payments = get_success_data(api.list_payments(ADMIN, params={"participant_id": participant["id"]}))
    assert len(payments) == 1
    assert payments[0]["status"] == "PENDING_SETUP"
    assert payments[0]["base_monthly_cents"] == 330000


def test_commence_retires_participant(api):
    """PRD §3.4: "...and it cascades the participant from `TERMINATED` to `RETIRED`."

    Design: Difficulty/transitive_cascade/commence_cascades_payment_then_retire_depth3
    """
    plan, participant, election, commenced = _commence_330k(api)
    refetched = validate_success(api.get_participant(participant["id"], ADMIN))
    assert refetched["employment_status"] == "RETIRED"


# ---------------------------------------------------------------------------
# transitive_cascade / record_death_cascades_inpay_payment_terminated_depth2
# ---------------------------------------------------------------------------
def test_record_death_marks_participant_deceased(api):
    """PRD §3.2: "Recording death is a `BenefitsAdministrator` action that moves the
    participant to `DECEASED` from `ACTIVE`, `TERMINATED`, or `RETIRED`, and as a cascade
    drives every `IN_PAY` benefit payment for that participant to `TERMINATED`."

    Design: Difficulty/transitive_cascade/record_death_cascades_inpay_payment_terminated_depth2
    """
    plan, participant, election, payment = setup_in_pay_payment()
    deceased = validate_success(api.record_death(participant["id"], ADMIN))
    assert deceased["employment_status"] == "DECEASED"


def test_record_death_cascades_inpay_payment_to_terminated(api):
    """PRD §3.8: "when the participant is recorded `DECEASED`, or when the plan begins
    `TERMINATING`, every `IN_PAY` or `SUSPENDED` payment for that participant or plan is
    driven to the terminal `TERMINATED` state."

    Design: Difficulty/transitive_cascade/record_death_cascades_inpay_payment_terminated_depth2
    """
    plan, participant, election, payment = setup_in_pay_payment()
    assert payment["status"] == "IN_PAY"
    validate_success(api.record_death(participant["id"], ADMIN))
    refetched = validate_success(api.get_payment(payment["id"], ADMIN))
    assert refetched["status"] == "TERMINATED"


# ---------------------------------------------------------------------------
# compensating_invariant / qdro_split_conserves_total_monthly_benefit
# ---------------------------------------------------------------------------
def test_qdro_carve_out_computed_at_qualify(api):
    """PRD §3.5: "a `PERCENTAGE` award carves `award_pct` of the *original* base (not of
    the remaining amount), rounded half-up to whole cents... The carve is written to that
    award's `alternate_payee_monthly_cents` and subtracted from the running remaining
    amount."

    Design: Difficulty/compensating_invariant/qdro_split_conserves_total_monthly_benefit
    """
    plan, participant = setup_terminated_vested_participant_330k(fap_accrual_rate=0.015)
    qdro = create_submitted_percentage_qdro(participant["id"], 0.40)
    # Submit the election first so js_reduced (330000) exists as the carve base.
    election = get_success_data(api.create_election(
        {"participant_id": participant["id"], "payment_form": "SINGLE_LIFE",
         "annuity_start_date": "2024-06-01"}, ADMIN))
    validate_success(api.submit_election(election["id"], ADM_A))
    qualified = validate_success(api.qualify_qdro(qdro["id"], ADMIN))
    assert qualified["alternate_payee_monthly_cents"] == 132000  # round(330000 * 0.40)


def test_qdro_split_conserves_total_monthly_benefit(api):
    """PRD §3.5: "The `base_monthly_cents` on the new payment is the election's
    `js_reduced_monthly_cents` minus the sum of `alternate_payee_monthly_cents` across
    the participant's `QUALIFIED` awards, with the result floored at zero so it never
    goes negative."

    Design: Difficulty/compensating_invariant/qdro_split_conserves_total_monthly_benefit
    """
    plan, participant = setup_terminated_vested_participant_330k(fap_accrual_rate=0.015)
    qdro = create_submitted_percentage_qdro(participant["id"], 0.40)
    election = get_success_data(api.create_election(
        {"participant_id": participant["id"], "payment_form": "SINGLE_LIFE",
         "annuity_start_date": "2024-06-01"}, ADMIN))
    validate_success(api.submit_election(election["id"], ADM_A))
    qualified = validate_success(api.qualify_qdro(qdro["id"], ADMIN))
    validate_success(api.approve_election(election["id"], ADM_B))
    validate_success(api.commence_election(election["id"], ADM_B))
    payments = get_success_data(api.list_payments(ADMIN, params={"participant_id": participant["id"]}))
    base = payments[0]["base_monthly_cents"]
    assert base == 198000  # 330000 - 132000
    assert_qdro_conservation(base, qualified["alternate_payee_monthly_cents"], 330000)


# ---------------------------------------------------------------------------
# Corner: state_machines / payment_suspend_then_resume_cycle
# ---------------------------------------------------------------------------
def test_payment_suspend_then_resume_preserves_current(api):
    """PRD §3.8: "An `IN_PAY` payment can be suspended by a `BenefitsAdministrator`,
    moving it to `SUSPENDED`, and a `SUSPENDED` payment can be resumed, moving it back to
    `IN_PAY`; this suspend/resume cycle has no further side effects."

    Design: Corner/state_machines/payment_suspend_then_resume_cycle
    """
    plan, participant, election, payment = setup_in_pay_payment(plan_overrides={"cola_pct": 0.0})
    assert payment["current_monthly_cents"] == 330000
    suspended = validate_success(api.suspend_payment(payment["id"], ADMIN))
    assert suspended["status"] == "SUSPENDED"
    resumed = validate_success(api.resume_payment(payment["id"], ADMIN))
    assert resumed["status"] == "IN_PAY"
    assert resumed["current_monthly_cents"] == 330000


# ---------------------------------------------------------------------------
# Corner: validations / apply_cola_no_cola_configured
# ---------------------------------------------------------------------------
def test_apply_cola_no_cola_configured_rejected(api):
    """PRD §3.8: "It requires that the payment currently be `IN_PAY` (otherwise
    `ERR_INVALID_STATE`) and that the plan's `cola_pct` be greater than zero (otherwise
    `ERR_NO_COLA_CONFIGURED`)."

    Design: Corner/validations/apply_cola_no_cola_configured
    """
    plan, participant, election, payment = setup_in_pay_payment(plan_overrides={"cola_pct": 0.0})
    resp = api.apply_cola(payment["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_NO_COLA_CONFIGURED.value)
