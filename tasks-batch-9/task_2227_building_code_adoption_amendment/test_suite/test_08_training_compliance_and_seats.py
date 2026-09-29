"""The two training compliance bases, and the session seat ledger."""
from test_helpers import (
    fixtures,
    get_success_data,
    make_council_admin_headers,
    validate_success,
)

FULL_ATTENDANCE = {
    "riverbend_1": "ATTENDED",
    "riverbend_2": "ATTENDED",
    "riverbend_3": "ATTENDED",
    "riverbend_4": "ATTENDED",
    "riverbend_5": "NO_SHOW",
}


def _closed_session_two_jurisdictions(api):
    """Riverbend's five officials hold every seat on a closed session; Harborview
    is registered but has trained nobody."""
    world = fixtures.setup_published_adoption_rule(api)
    fixtures.add_riverbend(api, world)
    fixtures.add_harborview(api, world)
    fixtures.setup_closed_enrollment_session(api, world=world)
    return world


def test_01_the_enrollment_basis_credits_the_no_show_and_the_attendance_basis_does_not(
    api,
):
    """"The enrollment-basis numerator is the count of *distinct* `attendee_name`
    values whose enrollment `status` is `ENROLLED`, `ATTENDED` or `NO_SHOW`; the
    attendance-basis numerator is the count of distinct `attendee_name` values
    whose enrollment `status` is `ATTENDED`." Over one identical set of five
    officials of which four attended, the enrollment basis reads 100.00 and the
    attendance basis 80.00, and "the attendance basis ... is the only one that
    drives `enforcement_readiness`, which reads `READY` when
    `compliance_pct_attendance_basis` is at or above 80.00".

    Design: Difficulty/dual_variant_calc/jurisdiction_training_compliance_enrollment_vs_attendance_diverge
    """
    world = _closed_session_two_jurisdictions(api)

    validate_success(
        fixtures.record_attendance(
            api, world, fixtures.attendance_for(world, FULL_ATTENDANCE)
        )
    )

    riverbend = fixtures.read_jurisdiction(api, world["riverbend_id"])
    assert riverbend["compliance_pct_enrollment_basis"] == 100.00
    assert riverbend["compliance_pct_attendance_basis"] == 80.00
    assert riverbend["enforcement_readiness"] == "READY"


def test_02_attendance_moves_seats_between_buckets_without_releasing_them(api):
    """"On success the session moves `ENROLLMENT_CLOSED` → `DELIVERED`" and
    "either move shifts a seat between buckets without releasing it:
    `enrolled_count` falls by one and `attended_count` or `no_show_count` rises by
    one, while `seats_available` is unchanged." A jurisdiction that trained nobody
    still reads 0.00, because the bases are computed only over enrollment rows
    whose `jurisdiction_id` is that jurisdiction.

    Design: Difficulty/dual_variant_calc/jurisdiction_training_compliance_enrollment_vs_attendance_diverge
    """
    world = _closed_session_two_jurisdictions(api)

    fixtures.record_attendance(
        api, world, fixtures.attendance_for(world, FULL_ATTENDANCE)
    )

    session = get_success_data(
        api.get_training_session(world["session_id"], make_council_admin_headers())
    )
    assert session["status"] == "DELIVERED"
    assert session["attended_count"] == 4
    assert session["no_show_count"] == 1
    assert session["enrolled_count"] == 0
    assert session["seats_available"] == 55

    no_show = get_success_data(
        api.get_training_enrollment(
            world["enrollments"]["riverbend_5"]["id"], make_council_admin_headers()
        )
    )
    assert no_show["status"] == "NO_SHOW"

    harborview = fixtures.read_jurisdiction(api, world["harborview_id"])
    assert harborview["compliance_pct_attendance_basis"] == 0.00


def test_03_cancelling_one_seat_restores_the_ledger_exactly(api):
    """"Cancellation is a full compensation of the seat ledger:
    `enrolled_count` falls by one and `seats_available` rises by one, restoring the
    invariant exactly." Five of sixty seats were taken, so returning one leaves 56
    available against 4 enrolled with nothing yet in the attended or no-show
    buckets.

    Design: Difficulty/compensating_invariant/enrollment_cancel_restores_session_seat_ledger_exactly
    """
    world = fixtures.setup_session_with_riverbend_enrollments(api)
    assert world["session"]["seats_available"] == 55
    assert world["session"]["enrolled_count"] == 5

    validate_success(fixtures.cancel_enrollment(api, world, "riverbend_5"))

    session = get_success_data(
        api.get_training_session(world["session_id"], make_council_admin_headers())
    )
    assert session["seat_capacity"] == 60
    assert session["seats_available"] == 56
    assert session["enrolled_count"] == 4
    assert session["attended_count"] == 0
    assert session["no_show_count"] == 0

    cancelled = get_success_data(
        api.get_training_enrollment(
            world["enrollments"]["riverbend_5"]["id"], make_council_admin_headers()
        )
    )
    assert cancelled["status"] == "CANCELLED"


def test_04_a_cancelled_seat_drops_out_of_both_compliance_numerators(api):
    """"Enrollments in `CANCELLED` are excluded from both numerators", and
    cancellation means "both compliance percentages for the attendee's
    jurisdiction are recomputed", so four live seats out of a headcount of five
    read 80.00 on the enrollment basis while the attendance basis stays 0.00 and
    readiness stays `NOT_READY`.

    Design: Difficulty/compensating_invariant/enrollment_cancel_restores_session_seat_ledger_exactly
    """
    world = fixtures.setup_session_with_riverbend_enrollments(api)

    fixtures.cancel_enrollment(api, world, "riverbend_5")

    riverbend = fixtures.read_jurisdiction(api, world["riverbend_id"])
    assert riverbend["compliance_pct_enrollment_basis"] == 80.00
    assert riverbend["compliance_pct_attendance_basis"] == 0.00
    assert riverbend["enforcement_readiness"] == "NOT_READY"
