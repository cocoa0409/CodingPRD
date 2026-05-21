"""CrewMember registration + Pairing draft construction.

PRD §3.1 covers crew-member registration and the multi-step pairing
draft (duty periods + flight legs). PRD §3.5 names the FAA single-period
cap that is enforced on publish.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    CrewMemberStatus,
    PairingStatus,
    add_duty_period,
    add_flight_leg,
    add_minutes_iso,
    assert_crew_member,
    assert_duty_period,
    assert_flight_leg,
    assert_pairing,
    build_pairing_with_one_duty_period,
    build_pairing_with_revenue_legs,
    create_crew_member,
    create_crew_member_payload,
    create_pairing_draft,
    create_pairing_payload,
    iso_from_dt,
    iso_now_utc,
    publish_pairing,
    scheduler_headers,
    validate_error,
    validate_success,
)


class TestCrewMemberRegistration:

    def test_create_crew_member_shape(self, api, scheduler_headers):
        """PRD §3.1: "A CrewMember is registered by a CrewScheduler with
        an employee_no matching the pattern ^E\\d{6}$ ... a rank drawn
        from CAPTAIN, FIRST_OFFICER, PURSER, or FLIGHT_ATTENDANT, a
        three-letter IATA base_airport code, a strictly positive
        union_seniority_number ... and a union_local_id."
        """
        payload = create_crew_member_payload(
            rank="CAPTAIN", base_airport="DFW",
            union_seniority_number=1, union_local_id="L-100",
        )
        resp = api.create_crew_member(payload, scheduler_headers)
        data = validate_success(resp, expected_status=201)
        assert_crew_member(data)
        assert data["rank"] == "CAPTAIN"
        assert data["base_airport"] == "DFW"
        assert data["status"] == CrewMemberStatus.ACTIVE.value

    def test_employee_no_pattern_violation_rejected(self, api,
                                                      scheduler_headers):
        """PRD §3.1: "an employee_no matching the pattern ^E\\d{6}$ (the
        letter E followed by exactly six digits, unique across the
        workforce)."
        """
        payload = create_crew_member_payload(employee_no="X123456")
        resp = api.create_crew_member(payload, scheduler_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED.value)

    def test_iata_base_airport_violation_rejected(self, api,
                                                    scheduler_headers):
        """PRD §3.1: "a three-letter IATA base_airport code."""
        payload = create_crew_member_payload(base_airport="LONGER")
        resp = api.create_crew_member(payload, scheduler_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED.value)

    def test_seniority_number_must_be_positive(self, api,
                                                  scheduler_headers):
        """PRD §3.1: "a strictly positive union_seniority_number (lower
        numbers indicate greater seniority and the number must be unique
        within rank)".
        """
        payload = create_crew_member_payload(union_seniority_number=0)
        resp = api.create_crew_member(payload, scheduler_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED.value)


class TestPairingDraft:

    def test_create_pairing_starts_in_draft(self, api, scheduler_headers):
        """PRD §3.1: "The pairing is born in DRAFT."""
        p = create_pairing_draft()
        assert_pairing(p)
        assert p["status"] == PairingStatus.DRAFT.value

    def test_add_duty_period_recomputes_pairing_totals(self, api,
                                                        scheduler_headers):
        """PRD §2.9: "Adding a duty period to a draft pairing recomputes
        Pairing.total_duty_minutes, Pairing.start_at, and Pairing.end_at."
        """
        from test_helpers import get_pairing
        p = create_pairing_draft()
        report_at = "2030-06-01T08:00:00.000Z"
        release_at = "2030-06-01T18:00:00.000Z"  # 600 minutes
        dp = add_duty_period(p["id"], 1, report_at, release_at)
        assert_duty_period(dp)
        assert dp["duty_minutes"] == 600, (
            "PRD §3.1: from which the system computes the duty period's "
            "duty_minutes."
        )
        refreshed = get_pairing(p["id"])
        assert refreshed["total_duty_minutes"] == 600
        assert refreshed["start_at"] == report_at
        assert refreshed["end_at"] == release_at

    def test_flight_leg_dep_after_arr_rejected(self, api):
        """PRD §3.1: "A flight leg with dep_at greater than or equal to
        arr_at is rejected with ERR_FLIGHT_LEG_INVALID."
        """
        p = create_pairing_draft()
        dp = add_duty_period(
            p["id"], 1,
            "2030-06-01T08:00:00.000Z", "2030-06-01T18:00:00.000Z",
        )
        from test_helpers import (
            create_flight_leg_payload,
            scheduler_headers as _sch,
        )
        bad = create_flight_leg_payload(
            leg_sequence_no=1,
            flight_number="AA1",
            dep_airport="DFW", arr_airport="JFK",
            dep_at="2030-06-01T12:00:00.000Z",
            arr_at="2030-06-01T12:00:00.000Z",  # equal → rejected
        )
        resp = api.add_flight_leg(dp["id"], bad, _sch())
        validate_error(resp, ApiErrorId.ERR_FLIGHT_LEG_INVALID.value)

    def test_flight_legs_overlap_in_duty_period_rejected(self, api):
        """PRD §3.1: "so is one whose dep_at is earlier than the prior
        leg's arr_at in the same duty period (sequential legs may touch
        but must not overlap; no buffer is required inside a duty
        period)."
        """
        p = create_pairing_draft()
        dp = add_duty_period(
            p["id"], 1,
            "2030-06-01T08:00:00.000Z", "2030-06-01T18:00:00.000Z",
        )
        add_flight_leg(
            dp["id"], leg_sequence_no=1,
            dep_airport="DFW", arr_airport="JFK",
            dep_at="2030-06-01T09:00:00.000Z",
            arr_at="2030-06-01T12:00:00.000Z",
        )
        # Second leg starts before first ended.
        from test_helpers import (
            create_flight_leg_payload,
            scheduler_headers as _sch,
        )
        bad = create_flight_leg_payload(
            leg_sequence_no=2,
            flight_number="AA2",
            dep_airport="JFK", arr_airport="DFW",
            dep_at="2030-06-01T11:30:00.000Z",
            arr_at="2030-06-01T14:00:00.000Z",
        )
        resp = api.add_flight_leg(dp["id"], bad, _sch())
        validate_error(resp, ApiErrorId.ERR_FLIGHT_LEG_INVALID.value)

    def test_flight_legs_touch_at_arr_time_allowed(self, api):
        """PRD §3.1: "sequential legs may touch but must not overlap; no
        buffer is required inside a duty period."
        """
        p = create_pairing_draft()
        dp = add_duty_period(
            p["id"], 1,
            "2030-06-01T08:00:00.000Z", "2030-06-01T18:00:00.000Z",
        )
        add_flight_leg(
            dp["id"], leg_sequence_no=1,
            dep_airport="DFW", arr_airport="JFK",
            dep_at="2030-06-01T09:00:00.000Z",
            arr_at="2030-06-01T12:00:00.000Z",
        )
        # Touching exactly.
        from test_helpers import (
            create_flight_leg_payload,
            scheduler_headers as _sch,
        )
        ok = create_flight_leg_payload(
            leg_sequence_no=2,
            flight_number="AA2",
            dep_airport="JFK", arr_airport="DFW",
            dep_at="2030-06-01T12:00:00.000Z",
            arr_at="2030-06-01T15:00:00.000Z",
        )
        resp = api.add_flight_leg(dp["id"], ok, _sch())
        data = validate_success(resp, expected_status=201)
        assert_flight_leg(data)

    def test_leg_type_defaults_to_revenue(self, api):
        """PRD §3.1: "an optional leg_type defaulting to REVENUE."""
        p = create_pairing_draft()
        dp = add_duty_period(
            p["id"], 1,
            "2030-06-01T08:00:00.000Z", "2030-06-01T18:00:00.000Z",
        )
        leg = add_flight_leg(
            dp["id"], leg_sequence_no=1,
            dep_airport="DFW", arr_airport="JFK",
            dep_at="2030-06-01T09:00:00.000Z",
            arr_at="2030-06-01T12:00:00.000Z",
            leg_type=None,  # do not include leg_type
        )
        assert leg["leg_type"] == "REVENUE"


class TestPairingPublish:

    def test_publish_requires_duty_periods(self, api, scheduler_headers):
        """PRD §3.1: "Publishing a draft pairing moves it to PUBLISHED
        and is rejected if the pairing has no duty periods or contains a
        duty period with no flight legs."
        """
        p = create_pairing_draft()
        resp = api.publish_pairing(p["id"], scheduler_headers)
        # PRD §3.1 says rejected — body validation category. The error
        # families PRD names for pairing-structure failures are
        # ERR_PAIRING_INTERNAL_OVERLAP (overlap-only) and
        # ERR_VALIDATION_FAILED (general). PRD does NOT pin one. Use
        # is_one_of.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_VALIDATION_FAILED.value,
            ApiErrorId.ERR_PAIRING_INTERNAL_OVERLAP.value,
            ApiErrorId.ERR_PAIRING_INVALID_STATE.value,
        ])

    def test_publish_recomputes_pairing_totals(self, api):
        """PRD §3.1: "Publication recomputes Pairing.total_block_minutes
        (the sum of block_minutes over REVENUE legs only — deadheads are
        excluded from the block total even though they will earn
        fractional credit later), Pairing.total_duty_minutes (the sum of
        duty_minutes across all duty periods)."
        """
        # One DutyPeriod of 600min total: 300min REVENUE + 60min DEADHEAD.
        from test_helpers import build_pairing_with_deadhead_legs
        pairing, dp, legs = build_pairing_with_deadhead_legs(
            deadhead_durations_minutes=[60],
            revenue_durations_minutes=[300],
            duty_pad_minutes=120,  # 60+300+60 + 2*120 = 600
        )
        published = publish_pairing(pairing["id"])
        # total_block_minutes = REVENUE legs only.
        assert published["total_block_minutes"] == 300, (
            "PRD §3.1: total_block_minutes is sum of REVENUE legs only."
        )
        # total_duty_minutes = sum of duty_minutes across periods.
        assert published["total_duty_minutes"] == 600
        assert published["status"] == PairingStatus.PUBLISHED.value

    def test_duty_period_rest_gap_below_minimum_rejected(self, api):
        """PRD §3.1: "the publish step additionally verifies that no two
        duty periods overlap and that the rest gap between consecutive
        duty periods (the difference between the earlier period's
        release_at and the later period's report_at) is at least the
        crew-rest minimum interval of ten hours; any violation yields
        ERR_PAIRING_INTERNAL_OVERLAP, and the same check applies
        whenever a duty period is appended to a draft."
        """
        p = create_pairing_draft()
        # D1 ends at 18:00.
        add_duty_period(
            p["id"], 1,
            "2030-06-01T08:00:00.000Z", "2030-06-01T18:00:00.000Z",
        )
        # D2 starts 599min later → gap 599 < 600.
        bad_start = add_minutes_iso("2030-06-01T18:00:00.000Z", 599)
        bad_end = add_minutes_iso(bad_start, 540)
        from test_helpers import (
            create_duty_period_payload,
            scheduler_headers as _sch,
        )
        resp = api.add_duty_period(
            p["id"],
            create_duty_period_payload(2, bad_start, bad_end),
            _sch(),
        )
        validate_error(resp, ApiErrorId.ERR_PAIRING_INTERNAL_OVERLAP.value)

    def test_duty_period_rest_gap_at_minimum_accepted(self, api):
        """PRD §3.5: "All four boundary inequalities are inclusive — a
        gap of exactly 600 minutes ... are all permitted."
        PRD §3.1: rest gap >= the crew-rest minimum interval of ten
        hours.

        # difficulty: resource_temporal_overlap/pairing_internal_dutyperiod_rest_overlap
        """
        p = create_pairing_draft()
        add_duty_period(
            p["id"], 1,
            "2030-06-01T08:00:00.000Z", "2030-06-01T18:00:00.000Z",
        )
        # Gap of exactly 600 minutes.
        good_start = add_minutes_iso("2030-06-01T18:00:00.000Z", 600)
        good_end = add_minutes_iso(good_start, 540)
        from test_helpers import (
            create_duty_period_payload,
            scheduler_headers as _sch,
        )
        resp = api.add_duty_period(
            p["id"],
            create_duty_period_payload(2, good_start, good_end),
            _sch(),
        )
        data = validate_success(resp, expected_status=201)
        assert_duty_period(data)
