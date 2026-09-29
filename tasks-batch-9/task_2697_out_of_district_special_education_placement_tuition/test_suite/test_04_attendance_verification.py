"""
Attendance-record filing, verification and amendment.

The twenty-eight-day billing cycle is the unit of account for every downstream
invoice, so these tests pin the order in which a filing is refused, the roll-up
of service hours onto the addenda a record names, and the amendment cycle.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_ADDENDUM_PLACEMENT_MISMATCH,
    ERR_BILLING_PERIOD_SHAPE,
    ERR_DUPLICATE_BILLING_PERIOD,
    ERR_PERIOD_OUTSIDE_PLACEMENT,
)
from test_helpers.fixtures import (
    ATTENDANCE_FILING_INSTANT,
    FULL_MONTH_PERIOD,
    add_authorized_addendum,
    build_active_day_placement,
    build_two_addenda_world,
    file_attendance,
    list_rows,
    make_active_placement,
    make_student,
    read_addendum,
    read_attendance,
    set_clock,
)
from test_helpers.test_users import COORDINATOR_HEADERS

# The 2026-10-05..2026-10-20 closed interval is sixteen days, twelve short of the
# twenty-eight-day cycle, so it breaks the period-shape rule on its own.
SHORT_PERIOD = {"period_start": "2026-10-05", "period_end": "2026-10-20"}
MISMATCH_FILING_INSTANT = "2026-10-21T09:00:00Z"


def _two_placements_and_an_addendum_on_the_second(api):
    """
    Two students, each with an ACTIVE DAY placement at the same school, and one
    ACTIVE speech addendum belonging to the second placement only.
    """
    world = build_active_day_placement(api)
    student_b = make_student(
        api,
        full_name="Omar Vasquez",
        disability_category="SPECIFIC_LEARNING_DISABILITY",
    )
    placement_b = make_active_placement(api, world, student=student_b)
    addendum_b = add_authorized_addendum(
        api,
        placement_b["id"],
        service_type="SPEECH",
        authorized_hours_per_week=2.0,
        contract_weeks=36,
        medicaid_billable=False,
    )
    set_clock(api, MISMATCH_FILING_INSTANT)
    return world, placement_b, addendum_b


class TestAttendanceRefusalOrder:
    """A filing that breaks both the referential rung and the temporal rung."""

    def test_foreign_addendum_line_outranks_the_malformed_period(self, api):
        """
        A record naming another placement's addendum over a sixteen-day period
        reports the referential mismatch, never the period shape.

        PRD: "The refusal ladder is **total**: the system evaluates rules in the order below and always returns the error belonging to the earliest rung that is violated, never a later one."

        Design: Difficulty/priority_pair_validation_conflict/referential_priority_9_beats_temporal_priority_10_on_attendance_create
        """
        world, placement_b, addendum_b = _two_placements_and_an_addendum_on_the_second(api)
        placement_a_id = world["placement"]["id"]

        response = api.create_attendance_record(
            f.attendance_record_payload(
                placement_a_id,
                days_enrolled=12,
                days_attended=12,
                days_absent_unexcused=0,
                residential_nights=0,
                service_delivery_lines=[f.service_line(addendum_b["id"], 4.0)],
                **SHORT_PERIOD,
            ),
            world["school_headers"],
        )
        validate_error(response, ERR_ADDENDUM_PLACEMENT_MISMATCH, 409)

        rows, meta = list_rows(
            api.list_attendance_records(
                COORDINATOR_HEADERS, {"placement_id": placement_a_id}
            )
        )
        assert meta["total_count"] == 0
        assert rows == []
        assert read_addendum(api, addendum_b["id"])["delivered_hours_ytd"] == 0

    def test_the_period_shape_rung_is_reachable_on_its_own(self, api):
        """
        The same sixteen-day period with no service lines at all is refused for
        its shape, which proves the mismatch above really did outrank it.

        PRD: "A cycle whose closed interval is not exactly twenty-eight days, or where `days_enrolled` plus `days_absent_unexcused` exceeds twenty-eight, or where `residential_nights` exceeds twenty-eight, or where `days_attended` exceeds `days_enrolled`, is refused with `ERR_BILLING_PERIOD_SHAPE`."

        Design: Difficulty/priority_pair_validation_conflict/referential_priority_9_beats_temporal_priority_10_on_attendance_create
        """
        world, placement_b, addendum_b = _two_placements_and_an_addendum_on_the_second(api)
        placement_a_id = world["placement"]["id"]

        response = api.create_attendance_record(
            f.attendance_record_payload(
                placement_a_id,
                days_enrolled=12,
                days_attended=12,
                days_absent_unexcused=0,
                residential_nights=0,
                service_delivery_lines=[],
                **SHORT_PERIOD,
            ),
            world["school_headers"],
        )
        validate_error(response, ERR_BILLING_PERIOD_SHAPE, 409)

        _, meta = list_rows(
            api.list_attendance_records(
                COORDINATOR_HEADERS, {"placement_id": placement_a_id}
            )
        )
        assert meta["total_count"] == 0
        assert read_addendum(api, addendum_b["id"])["delivered_hours_ytd"] == 0


class TestAttendanceVerification:
    """ACCEPT closes the record and banks the hours it reported."""

    def test_accept_rolls_each_line_onto_the_addendum_it_names(self, api):
        """
        Seven and a half hours land on the speech addendum and five and a half on
        the occupational-therapy addendum, each on its own row.

        PRD: "Its side effects are: `status` set to `VERIFIED`, `verified_by_user_id` set to the acting user's identifier, and, for every entry in `service_delivery_lines`, that entry's `hours_delivered` added to the named addendum's `delivered_hours_ytd` with that addendum's `version` incremented."

        Design: Corner/state_machines/attendance_verify_accept_rolls_delivered_hours_onto_named_addenda
        """
        world = build_two_addenda_world(api)
        speech, ot = world["speech"], world["ot"]
        assert speech["delivered_hours_ytd"] == 0
        assert ot["delivered_hours_ytd"] == 0

        set_clock(api, ATTENDANCE_FILING_INSTANT)
        record = file_attendance(
            api,
            world,
            world["placement"]["id"],
            days_enrolled=20,
            days_attended=16,
            days_absent_unexcused=4,
            residential_nights=0,
            service_delivery_lines=[
                f.service_line(speech["id"], 7.5),
                f.service_line(ot["id"], 5.5),
            ],
            **FULL_MONTH_PERIOD,
        )

        verified = validate_success(
            api.verify_attendance_record(
                record["id"], f.verify_attendance_payload("ACCEPT"), COORDINATOR_HEADERS
            )
        )
        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_user_id"] == "u-coord-1"
        assert verified["days_enrolled"] == 20
        assert verified["days_attended"] == 16
        assert verified["days_absent_unexcused"] == 4

        fresh_speech = read_addendum(api, speech["id"])
        fresh_ot = read_addendum(api, ot["id"])
        assert fresh_speech["delivered_hours_ytd"] == pytest.approx(7.5)
        assert fresh_speech["version"] == 3
        assert fresh_ot["delivered_hours_ytd"] == pytest.approx(5.5)
        assert fresh_ot["version"] == 3


class TestBillingPeriodUniqueness:
    """One cycle, one record: the first filing blocks the second while still open."""

    def test_a_second_record_for_the_same_open_period_is_refused(self, api):
        """
        The first record is still `SUBMITTED`, and that alone is enough to bar a
        second filing for the same twenty-eight days.

        PRD: "And a cycle that shares a `period_start` with, or whose closed interval overlaps, another attendance record for the same placement in `SUBMITTED`, `VERIFIED` or `DISPUTED` status is refused with `ERR_DUPLICATE_BILLING_PERIOD`."

        Design: Corner/validations/second_attendance_record_for_the_same_period_rejected
        """
        world = build_active_day_placement(api)
        placement_id = world["placement"]["id"]
        set_clock(api, ATTENDANCE_FILING_INSTANT)
        first = file_attendance(
            api,
            world,
            placement_id,
            days_enrolled=20,
            days_attended=20,
            days_absent_unexcused=0,
            **FULL_MONTH_PERIOD,
        )
        assert first["status"] == "SUBMITTED"

        response = api.create_attendance_record(
            f.attendance_record_payload(
                placement_id,
                days_enrolled=20,
                days_attended=18,
                days_absent_unexcused=2,
                residential_nights=0,
                service_delivery_lines=[],
                **FULL_MONTH_PERIOD,
            ),
            world["school_headers"],
        )
        validate_error(response, ERR_DUPLICATE_BILLING_PERIOD, 409)

        rows, meta = list_rows(
            api.list_attendance_records(
                COORDINATOR_HEADERS, {"placement_id": placement_id}
            )
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1
        surviving = read_attendance(api, first["id"])
        assert surviving["days_attended"] == 20
        assert surviving["days_absent_unexcused"] == 0
        assert surviving["status"] == "SUBMITTED"


class TestAttendanceAmendment:
    """The amendment cycle returns a disputed record to the district's inbox."""

    def test_amend_replaces_the_day_counts_and_bumps_the_round(self, api):
        """
        A disputed record amended with fresh day counts comes back `SUBMITTED`
        with one amendment round spent and no verifier recorded.

        PRD: "Side effects: `status` back to `SUBMITTED`, `amendment_round` incremented by one, `verified_by_user_id` reset to null, and `version` incremented."

        Design: Corner/endpoints/attendance_amend_resets_to_submitted_and_bumps_amendment_round
        """
        world = build_active_day_placement(api)
        set_clock(api, ATTENDANCE_FILING_INSTANT)
        record = file_attendance(
            api,
            world,
            world["placement"]["id"],
            days_enrolled=20,
            days_attended=14,
            days_absent_unexcused=6,
            **FULL_MONTH_PERIOD,
        )
        disputed = validate_success(
            api.verify_attendance_record(
                record["id"],
                f.verify_attendance_payload(
                    "DISPUTE", dispute_reason="Absence coding disagrees with the roster."
                ),
                COORDINATOR_HEADERS,
            )
        )
        assert disputed["status"] == "DISPUTED"
        assert disputed["amendment_round"] == 0

        amended = validate_success(
            api.amend_attendance_record(
                record["id"],
                f.amend_attendance_payload(
                    days_enrolled=20, days_attended=18, days_absent_unexcused=2
                ),
                world["school_headers"],
            )
        )
        assert amended["status"] == "SUBMITTED"
        assert amended["amendment_round"] == 1
        assert amended["days_enrolled"] == 20
        assert amended["days_attended"] == 18
        assert amended["days_absent_unexcused"] == 2
        assert amended["verified_by_user_id"] is None
        assert amended["version"] > disputed["version"]


class TestPeriodWindowCodes:
    """Shape and window are separate rungs with separate codes."""

    def test_a_short_period_and_an_out_of_window_period_report_different_codes(self, api):
        """
        A twenty-seven-day cycle fails on shape, a well-shaped cycle running past
        the placement's end date fails on the window, and a cycle accounting for
        twenty-nine days fails on shape again.

        PRD: "A cycle that is not entirely inside the placement's contracted window — `period_start` on or after the placement's `start_date` and `period_end` on or before its `end_date` — is refused with `ERR_PERIOD_OUTSIDE_PLACEMENT`."

        Design: Corner/errors/malformed_and_out_of_window_billing_periods_are_rejected_with_distinct_codes
        """
        world = build_active_day_placement(api)
        placement_id = world["placement"]["id"]
        set_clock(api, ATTENDANCE_FILING_INSTANT)

        short_cycle = api.create_attendance_record(
            f.attendance_record_payload(
                placement_id,
                period_start="2026-10-05",
                period_end="2026-10-31",
                days_enrolled=19,
                days_attended=19,
                days_absent_unexcused=0,
            ),
            world["school_headers"],
        )
        validate_error(short_cycle, ERR_BILLING_PERIOD_SHAPE, 409)

        past_the_end = api.create_attendance_record(
            f.attendance_record_payload(
                placement_id,
                period_start="2027-06-08",
                period_end="2027-07-05",
                days_enrolled=20,
                days_attended=20,
                days_absent_unexcused=0,
            ),
            world["school_headers"],
        )
        validate_error(past_the_end, ERR_PERIOD_OUTSIDE_PLACEMENT, 409)

        overcounted = api.create_attendance_record(
            f.attendance_record_payload(
                placement_id,
                days_enrolled=27,
                days_attended=25,
                days_absent_unexcused=2,
                **FULL_MONTH_PERIOD,
            ),
            world["school_headers"],
        )
        validate_error(overcounted, ERR_BILLING_PERIOD_SHAPE, 409)

        _, meta = list_rows(
            api.list_attendance_records(
                COORDINATOR_HEADERS, {"placement_id": placement_id}
            )
        )
        assert meta["total_count"] == 0
