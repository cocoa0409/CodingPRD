"""Ledger calculations, disbursement posting/return, and the projected balance.

Covers the posted-vs-projected ledger divergence, the disbursement net/return
compensation invariant, the clock-hour and time gates on posting, and the
duplicate-payment-period rule.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error,
    get_success_data,
    ApiErrorId,
    assert_ledger_consistent,
    create_program, create_student, create_enrollment,
    schedule_disbursement, post_disbursement,
    setup_posted_disbursement, setup_scheduled_disbursement_ready_to_post,
    setup_enrollment_with_hours,
    create_disbursement_payload, create_enrollment_payload,
    make_financial_aid_officer_headers, make_registrar_headers,
)

FAO = make_financial_aid_officer_headers()
REGISTRAR = make_registrar_headers()


# ==========================================================================
# dual_variant_calc / ledger_posted_vs_projected_on_enrollment  (queue A)
# ==========================================================================
def test_ledger_balance_counts_posted_only_with_scheduled_award(api):
    """PRD §3.5: "Its `total_credits_cents` is the sum of `net_amount_cents` over
    only those disbursements on the enrollment whose status is `POSTED` —
    `SCHEDULED` and `RETURNED` disbursements are excluded."

    With one still-SCHEDULED award, the POSTED-only ledger_balance_cents stays at
    the full charges (1400000) because nothing has posted yet.

    Design: Difficulty/dual_variant_calc/ledger_posted_vs_projected_on_enrollment
    """
    program = create_program(
        total_clock_hours=1500, tuition_cents=1200000,
        kit_fee_cents=150000, lab_fee_cents=50000, clinic_phase_start_hour=300,
    )
    student = create_student()
    enrollment = create_enrollment(
        program=program, student=student, scheduled_hours_to_date=450,
    )
    schedule_disbursement(
        enrollment["id"], payment_period=1, period_hours=400, period_weeks=4,
        gross_amount_cents=600000, origination_fee_cents=0,
    )
    data = validate_success(api.get_enrollment(enrollment["id"], FAO))
    assert data["ledger_balance_cents"] == 1400000, (
        f"posted-only ledger should be 1400000, got {data['ledger_balance_cents']}"
    )


def test_projected_balance_counts_scheduled_award(api):
    """PRD §3.5: "The projected credits are the sum of `net_amount_cents` over
    disbursements whose status is either `POSTED` or `SCHEDULED` (only `RETURNED`
    is excluded); for a still-`SCHEDULED` disbursement its net is projected as its
    `gross_amount_cents` minus its `origination_fee_cents` as though it will post."

    The SCHEDULED 600000 award drops projected_balance_cents to 800000 while the
    posted ledger stays at 1400000.

    Design: Difficulty/dual_variant_calc/ledger_posted_vs_projected_on_enrollment
    """
    program = create_program(
        total_clock_hours=1500, tuition_cents=1200000,
        kit_fee_cents=150000, lab_fee_cents=50000, clinic_phase_start_hour=300,
    )
    student = create_student()
    enrollment = create_enrollment(
        program=program, student=student, scheduled_hours_to_date=450,
    )
    schedule_disbursement(
        enrollment["id"], payment_period=1, period_hours=400, period_weeks=4,
        gross_amount_cents=600000, origination_fee_cents=0,
    )
    data = validate_success(api.get_enrollment(enrollment["id"], FAO))
    assert data["projected_balance_cents"] == 800000, (
        f"projected balance should be 800000, got {data['projected_balance_cents']}"
    )
    assert data["ledger_balance_cents"] != data["projected_balance_cents"], (
        "posted ledger and projected balance must diverge with a scheduled award"
    )


# ==========================================================================
# compensating_invariant / disbursement_return_conserves_ledger_credits (queue A)
# ==========================================================================
def test_disbursement_return_restores_ledger_to_pre_post(api):
    """PRD §3.4: "Because the ledger is always recomputed over the set of `POSTED`
    disbursements rather than adjusted incrementally, a post followed by a return
    leaves the ledger exactly where it began."

    Design: Difficulty/compensating_invariant/disbursement_return_conserves_ledger_credits
    """
    program, student, instructor, enrollment, dis = setup_posted_disbursement(
        program_overrides={
            "total_clock_hours": 1500, "tuition_cents": 1200000,
            "kit_fee_cents": 150000, "lab_fee_cents": 50000,
            "clinic_phase_start_hour": 300,
        },
        actual_hours=405, scheduled_hours_to_date=450,
        gross_amount_cents=600000, origination_fee_cents=0,
    )
    returned = validate_success(api.return_disbursement(dis["id"], FAO))
    assert returned["status"] == "RETURNED"
    enr = validate_success(api.get_enrollment(enrollment["id"], FAO))
    assert enr["ledger_balance_cents"] == 1400000, (
        f"ledger should return to 1400000, got {enr['ledger_balance_cents']}"
    )


def test_disbursement_return_zeroes_total_credits(api):
    """PRD §3.4: "A return reverses exactly the previously credited
    `net_amount_cents`: that amount is subtracted from the enrollment's
    `total_credits_cents`, the `ledger_balance_cents` is recomputed from scratch,
    and the enrollment's `version` is bumped."

    Design: Difficulty/compensating_invariant/disbursement_return_conserves_ledger_credits
    """
    program, student, instructor, enrollment, dis = setup_posted_disbursement(
        program_overrides={
            "total_clock_hours": 1500, "tuition_cents": 1200000,
            "kit_fee_cents": 150000, "lab_fee_cents": 50000,
            "clinic_phase_start_hour": 300,
        },
        actual_hours=405, scheduled_hours_to_date=450,
        gross_amount_cents=600000, origination_fee_cents=0,
    )
    validate_success(api.return_disbursement(dis["id"], FAO))
    enr = validate_success(api.get_enrollment(enrollment["id"], FAO))
    assert enr["total_credits_cents"] == 0, (
        f"total_credits_cents should be 0 after return, got {enr['total_credits_cents']}"
    )
    assert_ledger_consistent(enr)


# ==========================================================================
# cross_entity_state_dependency / disbursement_post_requires_enrollment_hours (queue A)
# ==========================================================================
def test_post_disbursement_blocked_when_hours_below_period_hours(api):
    """PRD §3.4: "The clock-hour gate requires the owning enrollment's
    `actual_hours` to be at least the disbursement's `period_hours`; if not, the
    post is rejected with `ERR_PERIOD_HOURS_NOT_EARNED`."

    Design: Difficulty/cross_entity_state_dependency/disbursement_post_requires_enrollment_hours
    """
    program, student, instructor, enrollment, dis = setup_scheduled_disbursement_ready_to_post(
        actual_hours=405, period_hours=500, period_weeks=4,
        scheduled_hours_to_date=450,
    )
    resp = api.post_disbursement(dis["id"], enrollment["version"], FAO)
    validate_error(resp, ApiErrorId.ERR_PERIOD_HOURS_NOT_EARNED.value)


def test_post_disbursement_blocked_hours_short_keeps_scheduled(api):
    """PRD §3.4: "Posting a `SCHEDULED` disbursement moves it to `POSTED` and is
    the moment aid actually credits the ledger, so it is gated on the period
    genuinely having been earned along two dimensions. The clock-hour gate
    requires the owning enrollment's `actual_hours` to be at least the
    disbursement's `period_hours`; if not, the post is rejected with
    `ERR_PERIOD_HOURS_NOT_EARNED`."

    Design: Difficulty/cross_entity_state_dependency/disbursement_post_requires_enrollment_hours
    """
    program, student, instructor, enrollment, dis = setup_scheduled_disbursement_ready_to_post(
        actual_hours=405, period_hours=500, period_weeks=4,
        scheduled_hours_to_date=450,
    )
    validate_error(
        api.post_disbursement(dis["id"], enrollment["version"], FAO),
        ApiErrorId.ERR_PERIOD_HOURS_NOT_EARNED.value,
    )
    still = validate_success(api.get_disbursement(dis["id"], FAO))
    assert still["status"] == "SCHEDULED", "a blocked post must leave it SCHEDULED"


# ==========================================================================
# enrollment_create_computes_ledger  (queue B / entities)
# ==========================================================================
def test_enrollment_create_snapshots_charges_and_zero_credits(api):
    """PRD §3.2: "`total_charges_cents` is the sum of the program's
    `tuition_cents`, `kit_fee_cents`, and `lab_fee_cents`, fixed at this moment
    and not re-read if the program is later edited. A fresh enrollment has
    `total_credits_cents` of 0, so its `ledger_balance_cents` (charges minus
    credits) initially equals the full charges."

    Design: Corner/entities/enrollment_create_computes_ledger
    """
    program = create_program(
        total_clock_hours=1500, tuition_cents=1200000,
        kit_fee_cents=150000, lab_fee_cents=50000, clinic_phase_start_hour=300,
    )
    student = create_student()
    data = validate_success(
        api.create_enrollment(
            create_enrollment_payload(
                student["id"], program["id"], scheduled_hours_to_date=0,
            ),
            REGISTRAR,
        ),
        201,
    )
    assert data["total_charges_cents"] == 1400000
    assert data["total_credits_cents"] == 0
    assert data["ledger_balance_cents"] == 1400000
    assert data["status"] == "ACTIVE"


# ==========================================================================
# calculations / disbursement_net_subtracts_origination_fee  (queue B)
# ==========================================================================
def test_disbursement_net_subtracts_origination_fee(api):
    """PRD §3.4: "On a successful post the disbursement's `net_amount_cents` is
    computed as its `gross_amount_cents` minus its `origination_fee_cents` (an
    exact integer-cent subtraction), that net amount is added to the enrollment's
    `total_credits_cents`."

    Design: Corner/calculations/disbursement_net_subtracts_origination_fee
    """
    program, student, instructor, enrollment, dis = setup_scheduled_disbursement_ready_to_post(
        actual_hours=405, period_hours=400, period_weeks=4,
        gross_amount_cents=600000, origination_fee_cents=5000,
        scheduled_hours_to_date=450,
    )
    posted = validate_success(api.post_disbursement(dis["id"], enrollment["version"], FAO))
    assert posted["net_amount_cents"] == 595000, (
        f"net should be 595000, got {posted['net_amount_cents']}"
    )
    enr = validate_success(api.get_enrollment(enrollment["id"], FAO))
    assert enr["total_credits_cents"] == 595000


# ==========================================================================
# calculations / disbursement_post_weeks_not_elapsed  (queue B)
# ==========================================================================
def test_post_disbursement_blocked_when_weeks_not_elapsed(api):
    """PRD §3.4: "The time gate requires that the whole number of weeks elapsed
    since the enrollment's `enrolled_on_iso`, measured against the current logical
    clock, be at least the disbursement's `period_weeks`; if not, the post is
    rejected with `ERR_PERIOD_WEEKS_NOT_ELAPSED`."

    Design: Corner/calculations/disbursement_post_weeks_not_elapsed
    """
    # Clock left at default 2026-04-01 == enrolled_on_iso, so 0 weeks elapsed < 4.
    program, student, instructor, enrollment = setup_enrollment_with_hours(
        actual_hours=405, scheduled_hours_to_date=450,
    )
    dis = schedule_disbursement(
        enrollment["id"], period_hours=400, period_weeks=4,
        gross_amount_cents=600000, origination_fee_cents=0,
    )
    enr = validate_success(api.get_enrollment(enrollment["id"], FAO))
    validate_error(
        api.post_disbursement(dis["id"], enr["version"], FAO),
        ApiErrorId.ERR_PERIOD_WEEKS_NOT_ELAPSED.value,
    )


# ==========================================================================
# validations / duplicate_payment_period_rejected  (queue B)
# ==========================================================================
def test_duplicate_payment_period_rejected(api):
    """PRD §3.4: "scheduling a disbursement whose `payment_period` is not 1 or 2,
    or that duplicates a payment period already held by another non-`RETURNED`
    disbursement on the same enrollment, is rejected with `ERR_INVALID_PERIOD`."

    Design: Corner/validations/duplicate_payment_period_rejected
    """
    program = create_program()
    student = create_student()
    enrollment = create_enrollment(
        program=program, student=student, scheduled_hours_to_date=450,
    )
    schedule_disbursement(
        enrollment["id"], payment_period=1, period_hours=400, period_weeks=4,
        gross_amount_cents=600000, origination_fee_cents=0,
    )
    resp = api.create_disbursement(
        create_disbursement_payload(
            enrollment["id"], payment_period=1, period_hours=700, period_weeks=8,
            gross_amount_cents=500000, origination_fee_cents=0,
        ),
        FAO,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_PERIOD.value)


# ==========================================================================
# state_machines / terminal_returned_disbursement_cannot_return_again  (queue B)
# ==========================================================================
def test_returned_disbursement_cannot_return_again(api):
    """PRD §3.4: "A return requested against a disbursement not in a valid
    originating state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/terminal_returned_disbursement_cannot_return_again
    """
    program, student, instructor, enrollment, dis = setup_posted_disbursement(
        actual_hours=405, scheduled_hours_to_date=450,
    )
    validate_success(api.return_disbursement(dis["id"], FAO))
    validate_error(
        api.return_disbursement(dis["id"], FAO),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
