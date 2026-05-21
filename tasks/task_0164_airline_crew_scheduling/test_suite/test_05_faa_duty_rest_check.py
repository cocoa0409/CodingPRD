"""FAA duty-rest check boundaries and error attribution.

PRD §3.5 enumerates the four inequalities and pins ordering ("the first
to fail is the one reported"). All four bounds are inclusive: 600
minutes, 3600, 6000, and 840 minutes are each permitted.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    CREW_REST_MIN_MINUTES,
    MAX_BLOCK_MINUTES_30D,
    MAX_DUTY_MINUTES_SINGLE,
    add_minutes_iso,
    admin_assign,
    advance_clock_to,
    assert_assignment,
    build_pairing_with_one_duty_period,
    create_assignment_payload,
    create_crew_member,
    get_crew_member,
    iso_from_dt,
    publish_pairing,
    raise_cumulative_block_30d,
    scheduler_headers,
    validate_error,
    validate_success,
)


class TestCrewRestBoundary:

    def test_crew_rest_exactly_600_minutes_accepted(self, api,
                                                     scheduler_headers):
        """PRD §3.5: "the gap from the candidate's last_duty_end_at to
        the candidate pairing's earliest report_at must be at least 600
        minutes (the ten-hour crew-rest minimum); a shorter gap yields
        ERR_FAA_CREW_REST_VIOLATION ... All four boundary inequalities
        are inclusive — a gap of exactly 600 minutes ... are all
        permitted."

        # difficulty: boundary_precision_check/crew_rest_exactly_600_minutes
        """
        # Seed last_duty_end_at by completing a prior pairing for the
        # crew member.
        from test_helpers import (
            run_pairing_to_completion,
            setup_pairing_admin_assigned,
        )
        pilot = create_crew_member(rank="CAPTAIN")
        # Build a first pairing well in the past via clock-driving, then
        # complete it so last_duty_end_at is populated.
        from test_helpers import advance_clock_to
        first_start = iso_from_dt(
            datetime.now(timezone.utc) + timedelta(days=1),
        )
        p1, a1 = setup_pairing_admin_assigned(
            pilot, assigned_rank_slot="CAPTAIN",
            start_at=first_start,
            revenue_block_minutes=300, duty_minutes=480,
        )
        run_pairing_to_completion(p1)
        # Re-read pilot for new last_duty_end_at.
        pilot = get_crew_member(pilot["id"])
        # Build second pairing where report_at = last_duty_end_at + 600min.
        last_end = pilot["last_duty_end_at"]
        assert last_end is not None
        report_at = add_minutes_iso(last_end, 600)
        p2, _, _ = build_pairing_with_one_duty_period(
            start_at=report_at,
            revenue_block_minutes=300, duty_minutes=480,
            required_rank_composition={"CAPTAIN": 1},
        )
        publish_pairing(p2["id"])
        # Admin-assign — exactly 600min crew rest.
        resp = api.create_assignment(
            create_assignment_payload(
                p2["id"], pilot["id"], "CAPTAIN",
            ),
            scheduler_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_assignment(data)

    def test_crew_rest_below_600_minutes_rejected(self, api,
                                                     scheduler_headers):
        """PRD §3.5: "the gap ... must be at least 600 minutes ... a
        shorter gap yields ERR_FAA_CREW_REST_VIOLATION."

        # difficulty: boundary_precision_check/crew_rest_exactly_600_minutes
        Second test for this difficulty instance — 599-minute gap.
        """
        from test_helpers import (
            run_pairing_to_completion,
            setup_pairing_admin_assigned,
        )
        pilot = create_crew_member(rank="CAPTAIN")
        first_start = iso_from_dt(
            datetime.now(timezone.utc) + timedelta(days=1),
        )
        p1, _ = setup_pairing_admin_assigned(
            pilot, assigned_rank_slot="CAPTAIN",
            start_at=first_start,
            revenue_block_minutes=300, duty_minutes=480,
        )
        run_pairing_to_completion(p1)
        pilot = get_crew_member(pilot["id"])
        last_end = pilot["last_duty_end_at"]
        assert last_end is not None
        # 599-minute gap → below boundary.
        report_at = add_minutes_iso(last_end, 599)
        p2, _, _ = build_pairing_with_one_duty_period(
            start_at=report_at,
            revenue_block_minutes=300, duty_minutes=480,
            required_rank_composition={"CAPTAIN": 1},
        )
        publish_pairing(p2["id"])
        resp = api.create_assignment(
            create_assignment_payload(
                p2["id"], pilot["id"], "CAPTAIN",
            ),
            scheduler_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FAA_CREW_REST_VIOLATION.value)


class TestBlockCap30d:

    def test_block_cap_exactly_6000_minutes_accepted(self, api,
                                                      scheduler_headers):
        """PRD §3.5: "the candidate's cumulative_block_minutes_30d plus
        the pairing's total_block_minutes must be at most 6000 minutes
        ... All four boundary inequalities are inclusive — ... a
        cumulative block total reaching exactly 6000 minutes ... are
        all permitted."
        """
        pilot = create_crew_member(rank="CAPTAIN")
        pilot = raise_cumulative_block_30d(pilot, target_minutes=5400)
        # Now build a pairing whose total_block_minutes = 600 →
        # cumulative becomes 6000 exactly.
        future_start = iso_from_dt(
            datetime.now(timezone.utc) + timedelta(days=10),
        )
        pairing, _, _ = build_pairing_with_one_duty_period(
            start_at=future_start,
            revenue_block_minutes=600, duty_minutes=720,
            required_rank_composition={"CAPTAIN": 1},
        )
        publish_pairing(pairing["id"])
        resp = api.create_assignment(
            create_assignment_payload(
                pairing["id"], pilot["id"], "CAPTAIN",
            ),
            scheduler_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_assignment(data)

    def test_block_cap_at_6001_minutes_rejected(self, api,
                                                  scheduler_headers):
        """PRD §3.5: "the candidate's cumulative_block_minutes_30d plus
        the pairing's total_block_minutes must be at most 6000 minutes
        (the rolling 100-hour, thirty-day block cap)."
        """
        pilot = create_crew_member(rank="CAPTAIN")
        pilot = raise_cumulative_block_30d(pilot, target_minutes=5400)
        # +601 → 6001 > 6000.
        future_start = iso_from_dt(
            datetime.now(timezone.utc) + timedelta(days=10),
        )
        pairing, _, _ = build_pairing_with_one_duty_period(
            start_at=future_start,
            revenue_block_minutes=601, duty_minutes=720,
            required_rank_composition={"CAPTAIN": 1},
        )
        publish_pairing(pairing["id"])
        resp = api.create_assignment(
            create_assignment_payload(
                pairing["id"], pilot["id"], "CAPTAIN",
            ),
            scheduler_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FAA_DUTY_VIOLATION.value)


class TestSingleDutyPeriodCap:

    def test_duty_period_at_840_minutes_accepted(self, api,
                                                   scheduler_headers):
        """PRD §3.5: "every DutyPeriod belonging to the candidate
        pairing must have a duty_minutes of at most 840 minutes (the
        14-hour single-duty-period cap) ... a duty period of exactly
        840 minutes ... are all permitted."
        """
        pilot = create_crew_member(rank="CAPTAIN")
        future_start = iso_from_dt(
            datetime.now(timezone.utc) + timedelta(days=2),
        )
        pairing, _, _ = build_pairing_with_one_duty_period(
            start_at=future_start,
            duty_minutes=840,  # exactly 840
            revenue_block_minutes=600,
            required_rank_composition={"CAPTAIN": 1},
        )
        publish_pairing(pairing["id"])
        resp = api.create_assignment(
            create_assignment_payload(
                pairing["id"], pilot["id"], "CAPTAIN",
            ),
            scheduler_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_assignment(data)


class TestErrorAttributionOrdering:

    def test_rest_check_evaluated_before_block_cap(self, api,
                                                     scheduler_headers):
        """PRD §3.5: "Four inequalities must all hold; the first to fail
        is the one reported."

        # difficulty: combinatorial_formula/faa_duty_rest_check_three_input_threshold
        Setup: rest=599min AND cumulative_block would also breach. The
        rest check is evaluated first per PRD §3.5 ordering, so the
        response is ERR_FAA_CREW_REST_VIOLATION (not
        ERR_FAA_DUTY_VIOLATION).
        """
        # Seed last_duty_end_at and cumulative_block in one shot via
        # the raise helper.
        from test_helpers import (
            run_pairing_to_completion,
            setup_pairing_admin_assigned,
        )
        pilot = create_crew_member(rank="CAPTAIN")
        # First, raise cumulative_block to 5800 to make the cap-breach
        # condition latent.
        pilot = raise_cumulative_block_30d(pilot, target_minutes=5800)
        # Now run a recent pairing to completion so last_duty_end_at is
        # set.
        recent_start = iso_from_dt(
            datetime.now(timezone.utc) + timedelta(days=30),
        )
        p1, _ = setup_pairing_admin_assigned(
            pilot,
            assigned_rank_slot="CAPTAIN",
            start_at=recent_start,
            revenue_block_minutes=100, duty_minutes=180,
        )
        run_pairing_to_completion(p1)
        pilot = get_crew_member(pilot["id"])
        last_end = pilot["last_duty_end_at"]
        # New pairing: report_at = last_end + 599min (rest fails),
        # total_block = 300 (would also breach since 5800+100+300 > 6000).
        report_at = add_minutes_iso(last_end, 599)
        p2, _, _ = build_pairing_with_one_duty_period(
            start_at=report_at,
            revenue_block_minutes=300, duty_minutes=420,
            required_rank_composition={"CAPTAIN": 1},
        )
        publish_pairing(p2["id"])
        resp = api.create_assignment(
            create_assignment_payload(
                p2["id"], pilot["id"], "CAPTAIN",
            ),
            scheduler_headers,
        )
        # Crew rest check fires first.
        validate_error(resp, ApiErrorId.ERR_FAA_CREW_REST_VIOLATION.value)
