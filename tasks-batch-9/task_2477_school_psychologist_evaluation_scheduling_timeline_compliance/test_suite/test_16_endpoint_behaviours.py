"""What the action endpoints report, what they leave alone, and when they are available."""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    BreachSeverity,
    ComplianceStatus,
    OrderStatus,
    SeatStatus,
    SessionStatus,
    api_client,
    assert_compliance_run_summary,
    assert_evaluation,
    assert_interpreter_session,
    assert_protocol_order,
    assert_scoring_license_seat,
    decision_payload,
    fixtures,
    receive_order_payload,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["district_admin_headers"]
SUPERVISOR = TEST_USERS["psych_services_supervisor_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_one_sweep_sorts_three_evaluations_into_three_postures():
    """The summary arrays, the breach it opens and the two pressure views all agree.

    "It reports `run_at`, the clock instant the sweep executed at; `evaluated_count`, how many evaluations it re-resolved; `at_risk_evaluation_ids` and `breached_evaluation_ids`, the identifiers it moved into each of those postures on this run; `breach_ids`, the identifiers of the breach records it opened; and `sessions_completed_count`, how many interpreter sessions it completed."

    Design: Corner/endpoints/compliance_run_report_matches_recomputed_postures
    """
    fixtures.set_clock("2026-07-01T00:00:00Z")
    school = fixtures.create_school(
        name="Alderway Middle",
        building_code="AW56",
        grade_band="MIDDLE",
        concurrent_meeting_capacity=2,
        enrollment_count=560,
    )
    psychologist = fixtures.create_psychologist(
        [school["id"]],
        full_name="Tomas Riel",
        employee_number="E-2030",
        credential_type="SSP",
        languages_certified=["en", "es"],
        weekly_capacity_points=20,
    )
    _, doomed = fixtures.consented_referral(
        school["id"],
        effective_at="2026-07-01T00:00:00Z",
        student_local_id="STU-47",
        requested_domains=["COGNITIVE"],
    )
    fixtures.assign_evaluator(doomed["id"], psychologist["id"])

    fixtures.set_clock("2026-08-01T00:00:00Z")
    _, at_risk = fixtures.consented_referral(
        school["id"],
        effective_at="2026-08-01T00:00:00Z",
        student_local_id="STU-48",
        requested_domains=["COGNITIVE", "ACADEMIC"],
        primary_language="es",
        interpreter_required=True,
    )
    fixtures.assign_evaluator(at_risk["id"], psychologist["id"])
    session = fixtures.book_session(
        at_risk["id"], "2026-09-19T09:00:00Z", "2026-09-19T10:00:00Z"
    )

    fixtures.set_clock("2026-09-20T12:00:00Z")
    _, fresh = fixtures.consented_referral(
        school["id"],
        effective_at="2026-09-20T09:00:00Z",
        student_local_id="STU-49",
        requested_domains=["COGNITIVE"],
    )

    summary = fixtures.run_sweep()

    assert_compliance_run_summary(summary)
    assert summary["run_at"].startswith("2026-09-20T12:00")
    assert summary["evaluated_count"] == 3
    assert summary["breached_evaluation_ids"] == [doomed["id"]]
    assert summary["at_risk_evaluation_ids"] == [at_risk["id"]]
    assert fresh["id"] not in summary["breached_evaluation_ids"]
    assert fresh["id"] not in summary["at_risk_evaluation_ids"]

    overdue = fixtures.get_evaluation(doomed["id"])
    assert_evaluation(overdue)
    assert overdue["elapsed_statutory_days"] == 81
    assert overdue["days_remaining"] == -21
    assert overdue["compliance_status"] == ComplianceStatus.BREACHED.value

    pressed = fixtures.get_evaluation(at_risk["id"])
    assert pressed["elapsed_statutory_days"] == 50
    assert pressed["days_remaining"] == 10
    assert pressed["compliance_status"] == ComplianceStatus.AT_RISK.value

    untouched = fixtures.get_evaluation(fresh["id"])
    assert untouched["elapsed_statutory_days"] == 0
    assert untouched["days_remaining"] == 60
    assert untouched["compliance_status"] == ComplianceStatus.ON_TRACK.value

    assert len(summary["breach_ids"]) == 1
    breach = fixtures.first_breach(doomed["id"])
    assert breach["breach_days"] == 21
    assert breach["severity"] == BreachSeverity.SEVERE.value
    # 21 * 30 * 1.5 is 945; three whole missed weeks * 150 * 1.5 is 675.
    assert breach["minutes_breach_day_basis"] == 945
    assert breach["minutes_missed_service_basis"] == 675

    assert summary["sessions_completed_count"] == 1
    completed = fixtures.evaluation_sessions(at_risk["id"])[0]
    assert_interpreter_session(completed)
    assert completed["id"] == session["id"]
    assert completed["status"] == SessionStatus.COMPLETED.value
    assert completed["duration_minutes"] == 60

    loaded = fixtures.get_psychologist(psychologist["id"])
    assert loaded["open_case_points"] == 13
    assert loaded["pressure_index_assigned_basis"] == 0.65
    # (5 points at the breached weight of 2.0 plus 8 at the at-risk 1.5) over 20.
    assert loaded["pressure_index_clock_weighted"] == 1.10

    second_run = fixtures.run_sweep()
    assert second_run["evaluated_count"] == 3
    assert second_run["breach_ids"] == []
    assert len(fixtures.evaluation_breaches(doomed["id"])) == 1


def test_the_psychologist_seat_index_spans_instruments_and_keeps_released_rows():
    """One release leaves two rows on the person and one free seat on the instrument.

    "The seats of one psychologist and the seats of one instrument are each listable and accept a `status` filter; an instrument's protocol orders are listable with a `status` filter; an evaluation's exclusion claims, interpreter sessions and breach records are each listable with a `status` filter."

    "Seats are never deleted — the population of `ASSIGNED` plus `RELEASED` seats only grows — and only `ASSIGNED` seats occupy capacity."

    Design: Corner/endpoints/psychologist_license_seat_index_includes_released_seats
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Bellhaven Elementary",
        building_code="BV57",
        grade_band="ELEMENTARY",
        concurrent_meeting_capacity=2,
        enrollment_count=290,
    )
    psychologist = fixtures.create_psychologist(
        [school["id"]],
        full_name="Uma Sorel",
        employee_number="E-2031",
        credential_type="SSP",
    )
    kept = fixtures.create_instrument(
        name="Vineland-3",
        instrument_code="VIN3",
        license_seat_total=1,
        license_expires_on="2027-06-30",
    )
    given_up = fixtures.create_instrument(
        name="Bayley-4",
        instrument_code="BAY4",
        license_seat_total=1,
        license_expires_on="2027-06-30",
    )
    kept_seat = fixtures.assign_license_seat(kept["id"], psychologist["id"])
    released_seat = fixtures.assign_license_seat(given_up["id"], psychologist["id"])

    released = fixtures.release_license_seat(given_up["id"], released_seat["id"])

    assert_scoring_license_seat(released)
    assert released["status"] == SeatStatus.RELEASED.value
    assert released["released_at"].startswith("2026-08-01T00:00:00")
    assert released["psychologist_id"] == psychologist["id"]

    by_person = {row["id"]: row for row in fixtures.psychologist_seats(psychologist["id"])}
    assert len(by_person) == 2
    assert by_person[kept_seat["id"]]["status"] == SeatStatus.ASSIGNED.value
    assert by_person[released_seat["id"]]["status"] == SeatStatus.RELEASED.value

    assert fixtures.get_instrument(kept["id"])["license_seats_free"] == 0
    assert fixtures.get_instrument(given_up["id"])["license_seats_free"] == 1

    # Rows are never deleted, so the released seat still lists on its instrument.
    on_instrument = fixtures.instrument_seats(given_up["id"])
    assert len(on_instrument) == 1
    assert on_instrument[0]["id"] == released_seat["id"]


def test_moving_the_clock_changes_the_day_counts_but_writes_no_row():
    """Fifty-five days pass on a read while the posture and the version stand still.

    "A test-driving capability lets any of the five roles set the clock to a supplied `current_utc` instant, and the response echoes the accepted `current_utc`."

    "Setting the clock mutates no entity: no `updated_at` is refreshed and no `version` is incremented anywhere."

    Design: Corner/endpoints/clock_endpoint_moves_derived_reads_without_mutating_rows
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Cliffmont High",
        building_code="CM58",
        grade_band="HIGH",
        concurrent_meeting_capacity=2,
        enrollment_count=830,
    )
    _, evaluation = fixtures.consented_referral(
        school["id"], student_local_id="STU-50", requested_domains=["COGNITIVE"]
    )

    before = fixtures.get_evaluation(evaluation["id"])
    assert before["elapsed_statutory_days"] == 0
    assert before["days_remaining"] == 60
    guard_version = before["version"]

    echo = validate_success(api_client.set_clock("2026-09-25T00:00:00Z", COMPLIANCE))

    assert echo["current_utc"].startswith("2026-09-25T00:00:00")

    after = fixtures.get_evaluation(evaluation["id"])
    assert_evaluation(after)
    assert after["elapsed_statutory_days"] == 55
    assert after["days_remaining"] == 5
    # Only a sweep, a hold, a remedy or an exclusion may write the posture.
    assert after["compliance_status"] == ComplianceStatus.ON_TRACK.value
    assert after["version"] == guard_version
    assert after["statutory_due_date"] == "2026-09-30"
    assert after["clock_start_date"] == "2026-08-01"


def test_the_decision_endpoint_is_reachable_only_from_submitted():
    """A manual-review order cancels; an auto-approved one has no decision to make.

    "A decision submitted against an order that is not `SUBMITTED` is rejected with `ERR_ORDER_STATE_INVALID`, as is a receipt recorded against an order that is not `APPROVED`."

    Design: Corner/endpoints/order_decision_is_only_available_from_submitted
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    instrument = fixtures.create_instrument(
        name="TOWL-4",
        instrument_code="TOWL4",
        protocol_stock_count=0,
        protocol_units_per_administration=1,
        protocol_unit_cost_cents=1799,
        license_seat_total=1,
        license_expires_on="2027-06-30",
    )
    manual_review = fixtures.order_protocols(instrument["id"], 30)
    auto_approved = fixtures.order_protocols(instrument["id"], 10)
    assert manual_review["total_cost_cents"] == 47681
    assert manual_review["status"] == OrderStatus.SUBMITTED.value
    assert auto_approved["total_cost_cents"] == 17981
    assert auto_approved["status"] == OrderStatus.APPROVED.value

    cancelled = fixtures.decide_order(manual_review["id"], "CANCEL")

    assert_protocol_order(cancelled)
    assert cancelled["status"] == OrderStatus.CANCELLED.value
    assert cancelled["decided_by_user_id"] == ADMIN["X-User-ID"]
    assert fixtures.get_instrument(instrument["id"])["protocol_stock_count"] == 0

    receipt = api_client.receive_protocol_order(
        manual_review["id"], receive_order_payload(30), SUPERVISOR
    )
    validate_error(receipt, ApiErrorId.ERR_ORDER_STATE_INVALID.value, 409)

    second_decision = api_client.decide_protocol_order(
        auto_approved["id"], decision_payload("APPROVE"), ADMIN
    )
    validate_error(second_decision, ApiErrorId.ERR_ORDER_STATE_INVALID.value, 409)

    orders = fixtures.list_rows(
        api_client.list_instrument_protocol_orders(instrument["id"], SUPERVISOR)
    )
    assert [row["status"] for row in orders] == [
        OrderStatus.CANCELLED.value,
        OrderStatus.APPROVED.value,
    ]
