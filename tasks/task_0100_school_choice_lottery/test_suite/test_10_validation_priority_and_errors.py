"""Validation priority orderings explicitly named in PRD §2.8.

PRD §2.8 names three non-obvious priority orderings:
A. Lottery /draw: priority 8 (state==CLOSED required → ERR_LOTTERY_NOT_READY)
   before priority 10 (already-drawn → ERR_LOTTERY_ALREADY_DRAWN).
B. Accept/decline temporal: priority 7 (state) vs priority 14
   (offer-expired). After the sweep moves the row to EXPIRED, the
   accept fails with ERR_INVALID_STATE_FOR_TRANSITION.
C. Transfer approve: priority 15 (ERR_DISTRICT_NO_TRANSFERS) before
   priority 16 (ERR_DISTRICT_CAPACITY_EXCEEDED).

This file targets ONLY orderings PRD prose explicitly commits to. Other
scaffold priority rows are tested in isolation elsewhere; we do NOT
generate "rule A fires before rule B" tests unless PRD names the
ordering.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_BASE_CLOCK,
    advance_clock_iso,
    advance_clock_to,
    api_client,
    create_application,
    create_district,
    create_family,
    create_program,
    create_school,
    create_student,
    create_transfer_request,
    get_application,
    iso_utc,
    make_district_admin_headers,
    make_family_user_headers,
    open_program_window,
    close_program_window,
    setup_district_with_school_and_program,
    setup_family_with_student,
    setup_drawn_program_with_single_offer,
    submit_application,
    validate_error,
)


class TestLotteryDrawPriorityAB:

    def test_open_program_yields_not_ready_not_already_drawn(self, api):
        """PRD §2.8 priority conflict A: "any non-CLOSED status that is
        not yet LOTTERY_DRAWN or BACKFILL (i.e., SCHEDULED or OPEN)
        yields ERR_LOTTERY_NOT_READY, while LOTTERY_DRAWN or BACKFILL
        yields ERR_LOTTERY_ALREADY_DRAWN."

        Claim: draw on an OPEN program is ERR_LOTTERY_NOT_READY (not
        ERR_LOTTERY_ALREADY_DRAWN).
        """
        district, school, program = setup_district_with_school_and_program()
        open_program_window(program)
        res = api.draw_lottery(
            program["id"], make_district_admin_headers(district["id"]),
        )
        validate_error(res, ApiErrorId.ERR_LOTTERY_NOT_READY.value)

    def test_drawn_program_yields_already_drawn(self, api):
        """PRD §2.8: "LOTTERY_DRAWN or BACKFILL yields
        ERR_LOTTERY_ALREADY_DRAWN."
        """
        district, school, program, family, student, app, run = (
            setup_drawn_program_with_single_offer()
        )
        res = api.draw_lottery(
            program["id"], make_district_admin_headers(district["id"]),
        )
        validate_error(res, ApiErrorId.ERR_LOTTERY_ALREADY_DRAWN.value)


class TestAcceptTemporalPriorityB:

    def test_accept_after_sweep_yields_invalid_state(self, api):
        """PRD §2.8 priority conflict B: "once the sweep has run, the
        same request fails earlier with
        ERR_INVALID_STATE_FOR_TRANSITION because the row is no longer
        OFFERED."

        Claim: advancing the clock past offer_expires_at runs the sweep
        (turning the app into EXPIRED); a subsequent /accept then
        yields ERR_INVALID_STATE_FOR_TRANSITION.
        """
        district, school, program, family, student, app, run = (
            setup_drawn_program_with_single_offer()
        )
        # Sweep happens during /_clock/advance per PRD §2.10.
        advance_clock_iso(app["offer_expires_at"])
        # State transition to EXPIRED is now applied. Verify.
        expired = get_application(app["id"])
        assert expired["status"] == "EXPIRED"
        res = api.accept_application(app["id"], make_family_user_headers(family["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_FOR_TRANSITION.value)


class TestTransferApprovePriorityC:

    def test_district_no_transfers_wins_over_capacity_exceeded(self, api):
        """PRD §2.8 priority conflict C: "on transfer-request approval,
        the district-permission check (the district must permit
        inter-district transfers) is evaluated before the capacity
        check, so a district that has both refused transfers and
        exhausted capacity yields ERR_DISTRICT_NO_TRANSFERS, not
        ERR_DISTRICT_CAPACITY_EXCEEDED."

        Claim: target district has accepts_inter_district_transfers ==
        false AND no MAGNET/CHARTER programs (capacity == 0). Approval
        is rejected with ERR_DISTRICT_NO_TRANSFERS.
        """
        advance_clock_to(DEFAULT_BASE_CLOCK)
        # Target has zero MAGNET/CHARTER programs → capacity = 0.
        target = create_district(accepts_inter_district_transfers=False)
        # Provide a NEIGHBORHOOD program in target so the cross-district
        # application has a destination — NEIGHBORHOOD is excluded from
        # capacity (PRD §3.3: "NEIGHBORHOOD schools do not contribute to
        # inter-district capacity").
        target_school = create_school(
            target, school_type="NEIGHBORHOOD", grade_levels_offered=[5],
        )
        target_program = create_program(
            target, target_school, grade_level=5, seats_total=2,
            registration_open_at=iso_utc(DEFAULT_BASE_CLOCK + timedelta(days=1)),
            registration_close_at=iso_utc(DEFAULT_BASE_CLOCK + timedelta(days=30)),
            lottery_seed="no-transfers-seed",
        )
        home = create_district()
        family = create_family(home, poverty_index_score=0.10)
        student = create_student(family, grade_level_next_year=5)
        app = create_application(family, student, target_program, choice_rank=1)
        tr = create_transfer_request(family, app, target)
        res = api.approve_transfer_request(
            tr["id"], make_district_admin_headers(target["id"]),
        )
        # PRD §2.8: priority 15 (no_transfers) fires before priority 16
        # (capacity_exceeded).
        validate_error(res, ApiErrorId.ERR_DISTRICT_NO_TRANSFERS.value)
