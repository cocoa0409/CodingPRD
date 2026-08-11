"""Oral argument scheduling: half-open overlap arithmetic and notice window."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    assert_oral_argument,
    attorney_headers,
    create_court, create_attorney,
    setup_argument_pending_case,
    set_clock,
    CLERK,
)


def _two_argument_pending_cases(api, court_code):
    """One court, two cases both driven to ARGUMENT_PENDING (argument REQUESTED)."""
    court = create_court(code=court_code)
    attorney = create_attorney(admitted_court_ids=[court["id"]])
    reviewer = create_attorney(admitted_court_ids=[court["id"]])
    ctx_a = setup_argument_pending_case(court=court, attorneys=(attorney, reviewer),
                                        docket_number=f"{court_code}-A")
    ctx_b = setup_argument_pending_case(court=court, attorneys=(attorney, reviewer),
                                        docket_number=f"{court_code}-B")
    return court, attorney, ctx_a, ctx_b


class TestAdjacentIntervals:
    def test_first_argument_schedules_successfully(self, api):
        """PRD §3.7: "Scheduling is the clerk's job and is guarded by two
        temporal rules, evaluated with the overlap check first. The proposed
        interval — from `scheduled_start` to `scheduled_start` plus
        `duration_minutes`, treated as half-open — is compared against every
        other argument on the same court that stands `SCHEDULED` or `HELD`: the
        proposed and existing intervals conflict only when the proposed start
        falls strictly before the existing interval's end and the existing start
        falls strictly before the proposed interval's end."
        PRD §3.7: "A clean scheduling moves the argument from `REQUESTED` to
        `SCHEDULED`."

        Design: Difficulty/boundary_precision_check/oral_argument_adjacent_intervals_no_overlap
        """
        _, _, ctx_a, _ = _two_argument_pending_cases(api, "BP2")
        set_clock("2026-08-01T00:00:00Z")
        res = api.schedule_argument(
            ctx_a["oral_argument"]["id"],
            {"scheduled_start": "2026-09-01T14:00:00Z", "duration_minutes": 30},
            CLERK,
        )
        scheduled = validate_success(res, 200)
        assert_oral_argument(scheduled)
        assert scheduled["status"] == "SCHEDULED"

    def test_back_to_back_argument_is_adjacent_not_overlapping(self, api):
        """PRD §3.7: "Back-to-back arguments, where one's end coincides exactly
        with the other's start, are adjacent rather than overlapping and are
        permitted; a genuine conflict is rejected with `ERR_ARGUMENT_OVERLAP`."
        PRD §2.7: "Scheduling conflicts use half-open interval arithmetic with
        strictly-less-than comparisons, so an argument that ends exactly when
        another begins does not overlap it."

        Design: Difficulty/boundary_precision_check/oral_argument_adjacent_intervals_no_overlap
        """
        _, _, ctx_a, ctx_b = _two_argument_pending_cases(api, "BP2A")
        set_clock("2026-08-01T00:00:00Z")
        validate_success(api.schedule_argument(
            ctx_a["oral_argument"]["id"],
            {"scheduled_start": "2026-09-01T14:00:00Z", "duration_minutes": 30},
            CLERK,
        ), 200)

        res = api.schedule_argument(
            ctx_b["oral_argument"]["id"],
            {"scheduled_start": "2026-09-01T14:30:00Z", "duration_minutes": 30},
            CLERK,
        )
        scheduled = validate_success(res, 200)
        assert scheduled["status"] == "SCHEDULED", (
            "an argument starting exactly when another ends is adjacent, not overlapping"
        )


class TestOverlapRejection:
    def test_one_minute_overlap_is_rejected(self, api):
        """PRD §3.7: "the proposed and existing intervals conflict only when the
        proposed start falls strictly before the existing interval's end and the
        existing start falls strictly before the proposed interval's end.
        Back-to-back arguments, where one's end coincides exactly with the
        other's start, are adjacent rather than overlapping and are permitted;
        a genuine conflict is rejected with `ERR_ARGUMENT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/oral_argument_half_open_overlap_rejected
        """
        _, _, ctx_a, ctx_b = _two_argument_pending_cases(api, "OV1")
        set_clock("2026-08-01T00:00:00Z")
        validate_success(api.schedule_argument(
            ctx_a["oral_argument"]["id"],
            {"scheduled_start": "2026-09-01T14:00:00Z", "duration_minutes": 30},
            CLERK,
        ), 200)

        res = api.schedule_argument(
            ctx_b["oral_argument"]["id"],
            {"scheduled_start": "2026-09-01T14:29:00Z", "duration_minutes": 30},
            CLERK,
        )
        validate_error(res, ApiErrorId.ERR_ARGUMENT_OVERLAP.value, expected_status=409)
        arg_b = validate_success(
            api.get_oral_argument(ctx_b["oral_argument"]["id"],
                                  attorney_headers(ctx_b["attorney"])),
            200,
        )
        assert arg_b["status"] == "REQUESTED", (
            "a rejected scheduling must leave the argument REQUESTED"
        )

    def test_overlap_check_fires_before_notice_check(self, api):
        """PRD §2.9: "13. **Argument notice** — on argument scheduling, the
        proposed start must respect the court's minimum notice window; otherwise
        `ERR_ARGUMENT_NOTICE_TOO_SHORT` (HTTP 422). The overlap check runs
        before the notice check, so a conflicting slot surfaces
        `ERR_ARGUMENT_OVERLAP` even when the slot is also too soon."

        Design: Difficulty/resource_temporal_overlap/oral_argument_half_open_overlap_rejected
        """
        _, _, ctx_a, ctx_b = _two_argument_pending_cases(api, "OV1N")
        set_clock("2026-08-01T00:00:00Z")
        validate_success(api.schedule_argument(
            ctx_a["oral_argument"]["id"],
            {"scheduled_start": "2026-09-01T14:00:00Z", "duration_minutes": 30},
            CLERK,
        ), 200)

        # Advance so that 2026-09-01 is inside the 14-day notice window,
        # then propose a slot that both overlaps and is too soon.
        set_clock("2026-08-25T00:00:00Z")
        res = api.schedule_argument(
            ctx_b["oral_argument"]["id"],
            {"scheduled_start": "2026-09-01T14:15:00Z", "duration_minutes": 30},
            CLERK,
        )
        validate_error(res, ApiErrorId.ERR_ARGUMENT_OVERLAP.value, expected_status=409)
        err = res.json()["data"]["error_id"]
        assert err != ApiErrorId.ERR_ARGUMENT_NOTICE_TOO_SHORT.value, (
            "overlap must surface before the notice-window check"
        )
