"""Cancellation, tuition settlement, and cross-axis side effects (PRD §3.7)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, TEST_USERS,
    make_student_headers,
)
from test_helpers.fixtures import (
    setup_basic_world, setup_open_offering, advance_clock,
    submit_enrollment_success, get_enrollment_request, cancel_enrollment,
    settle_tuition, get_offering, list_student_sync_events,
    create_student,
)


def test_cancel_approved_decrements_enrolled_count_and_reverts_billing(api, registrar_headers):
    """PRD §3.7: "The cancellation of an APPROVED enrollment carries a
    substantial cascade: the offering's enrolled_count is decremented, the
    student's provisional credit usage is decremented by the course's
    credits, financial_status reverts from BILLED to UNBILLED..."

    Claim: cancel APPROVED enrollment → enrolled_count decrements,
    financial_status becomes UNBILLED.
    """
    world = setup_basic_world(student_year=2)
    co = setup_open_offering(world, credits=3.0, base_capacity=5,
                              scheduled_meetings=[{"day_of_week": 0, "start_minute_of_day": 540, "end_minute_of_day": 600}])
    er = submit_enrollment_success(world["student"], co["offering"]["id"])
    assert er["academic_status"] == "APPROVED"
    assert er["financial_status"] == "BILLED"

    offering_before = get_offering(co["offering"]["id"])
    enrolled_before = offering_before["enrolled_count"]

    cancel_enrollment(world["student"], er["id"])
    er_after = get_enrollment_request(er["id"])
    assert er_after["academic_status"] == "CANCELED"
    assert er_after["financial_status"] == "UNBILLED"

    offering_after = get_offering(co["offering"]["id"])
    assert offering_after["enrolled_count"] == enrolled_before - 1


def test_cancel_after_classes_start_rejected(api, registrar_headers):
    """PRD §3.7: "For a cancellation of an APPROVED enrollment, the parent
    Term must additionally be in REGISTRATION_OPEN or REGISTRATION_CLOSED
    and the logical clock must still be strictly before classes_start_at;
    once classes have begun, the cancellation fails with
    ERR_TERM_LOCKED_FOR_CANCEL (409)."

    Claim: cancel after the clock has advanced past classes_start_at →
    ERR_TERM_LOCKED_FOR_CANCEL.
    """
    world = setup_basic_world(student_year=2)
    co = setup_open_offering(world, credits=3.0,
                              scheduled_meetings=[{"day_of_week": 1, "start_minute_of_day": 540, "end_minute_of_day": 600}])
    er = submit_enrollment_success(world["student"], co["offering"]["id"])
    assert er["academic_status"] == "APPROVED"

    advance_clock(world["term"]["classes_start_at"])
    res = api.cancel_enrollment_request(er["id"], make_student_headers(world["student"]["id"]))
    validate_error(res, "ERR_TERM_LOCKED_FOR_CANCEL")


def test_cancel_by_non_owner_rejected(api, registrar_headers):
    """PRD §3.7: "The cancellation requires X-User-ID to match the request's
    student_id; otherwise it fails with ERR_NOT_OWNER."

    Claim: a different student attempting cancel → ERR_NOT_OWNER.
    """
    world = setup_basic_world(student_year=2)
    co = setup_open_offering(world, credits=3.0,
                              scheduled_meetings=[{"day_of_week": 2, "start_minute_of_day": 540, "end_minute_of_day": 600}])
    er = submit_enrollment_success(world["student"], co["offering"]["id"])
    intruder = create_student(world["department"]["id"], world["campus"]["id"], year_in_program=2,
                               full_name="Intruder")
    res = api.cancel_enrollment_request(er["id"], make_student_headers(intruder["id"]))
    validate_error(res, "ERR_NOT_OWNER")


def test_settle_tuition_from_billed_to_paid(api, registrar_headers, finance_headers):
    """PRD §3.7: "Tuition settlement is the Finance role's only operation. Once
    the system has set an enrollment's financial_status to BILLED (which
    happens automatically on approval), Finance may move it to PAID."

    Claim: BILLED → PAID via /settle-tuition.

    # difficulty: non_linear_state_machine/non_linear_enrollment_request_parallel_dimensions
    """
    world = setup_basic_world(student_year=1)
    co = setup_open_offering(world, credits=3.0,
                              scheduled_meetings=[{"day_of_week": 3, "start_minute_of_day": 540, "end_minute_of_day": 600}])
    er = submit_enrollment_success(world["student"], co["offering"]["id"])
    assert er["academic_status"] == "APPROVED"
    assert er["financial_status"] == "BILLED"

    res = api.settle_tuition(er["id"], finance_headers)
    paid = validate_success(res, 200)
    assert paid["financial_status"] == "PAID"
    # Academic dimension unchanged by financial transition.
    assert paid["academic_status"] == "APPROVED"


def test_settle_tuition_on_canceled_rejected(api, registrar_headers, finance_headers):
    """PRD §3.7: "The transition is rejected with ERR_INVALID_STATE_FOR_SETTLE
    (409) unless the request's academic_status is APPROVED — that is,
    settlement is forbidden once the enrollment has reached any of CANCELED,
    REJECTED, or SETTLED."

    Claim: settle on CANCELED → ERR_INVALID_STATE_FOR_SETTLE.
    """
    world = setup_basic_world(student_year=2)
    co = setup_open_offering(world, credits=3.0,
                              scheduled_meetings=[{"day_of_week": 4, "start_minute_of_day": 540, "end_minute_of_day": 600}])
    er = submit_enrollment_success(world["student"], co["offering"]["id"])
    cancel_enrollment(world["student"], er["id"])

    res = api.settle_tuition(er["id"], finance_headers)
    validate_error(res, "ERR_INVALID_STATE_FOR_SETTLE")


def test_create_then_cancel_preserves_seat_invariant(api, registrar_headers):
    """PRD §3.4 + §3.7: enrolled_count increments on APPROVED, decrements on
    cancel of APPROVED. The conserved quantity is capacity − enrolled_count.

    Claim: a single create-then-cancel cycle leaves capacity − enrolled_count
    unchanged at 5.

    # difficulty: compensating_invariant/invariant_offering_seat_ledger_create_then_cancel
    """
    world = setup_basic_world(student_year=2)
    co = setup_open_offering(world, credits=3.0, base_capacity=5,
                              scheduled_meetings=[{"day_of_week": 5, "start_minute_of_day": 540, "end_minute_of_day": 600}])
    o0 = get_offering(co["offering"]["id"])
    available_before = o0["capacity"] - o0["enrolled_count"]
    assert available_before == 5

    er = submit_enrollment_success(world["student"], co["offering"]["id"])
    o1 = get_offering(co["offering"]["id"])
    assert o1["enrolled_count"] == 1
    assert o1["capacity"] == 5

    cancel_enrollment(world["student"], er["id"])
    o2 = get_offering(co["offering"]["id"])
    assert o2["enrolled_count"] == 0
    assert o2["capacity"] == 5
    available_after = o2["capacity"] - o2["enrolled_count"]
    assert available_after == available_before, (
        f"Seat ledger drift: before={available_before}, after={available_after}"
    )


def test_create_then_cancel_preserves_credit_load_invariant(api, registrar_headers):
    """PRD §3.6: provisional credit load is the sum of Course.credits across
    APPROVED+WAITLISTED enrollments; APPROVED→CANCELED releases the
    provisional credit charge. The conserved quantity is provisional credit
    load.

    Claim: a single create-then-cancel cycle leaves the student's APPROVED
    credit total unchanged.

    # difficulty: compensating_invariant/invariant_student_credit_budget_create_then_cancel
    """
    world = setup_basic_world(student_year=2)
    plan_before = validate_success(
        api.get_student_degree_plan(world["student"]["id"], registrar_headers), 200
    )
    in_progress_before = float(plan_before["in_progress_credits"])

    co = setup_open_offering(world, credits=3.0,
                              scheduled_meetings=[{"day_of_week": 6, "start_minute_of_day": 540, "end_minute_of_day": 600}])
    er = submit_enrollment_success(world["student"], co["offering"]["id"])
    assert float(er["provisional_credit_charge"]) == pytest.approx(3.0, abs=0.01)

    plan_after_create = validate_success(
        api.get_student_degree_plan(world["student"]["id"], registrar_headers), 200
    )
    assert float(plan_after_create["in_progress_credits"]) == pytest.approx(
        in_progress_before + 3.0, abs=0.01
    )

    cancel_enrollment(world["student"], er["id"])
    plan_after_cancel = validate_success(
        api.get_student_degree_plan(world["student"]["id"], registrar_headers), 200
    )
    assert float(plan_after_cancel["in_progress_credits"]) == pytest.approx(
        in_progress_before, abs=0.01
    ), (
        f"Credit load drift: before={in_progress_before}, "
        f"after={plan_after_cancel['in_progress_credits']}"
    )
