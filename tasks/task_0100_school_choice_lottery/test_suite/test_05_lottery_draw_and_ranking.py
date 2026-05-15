"""Lottery draw, ranking, LotteryRun audit, and the related
state-machine and validation rules.

Covers PRD §3.5 (draw preconditions, ordering, side effects, audit
record).
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
    assert_lottery_ordering,
    assert_lottery_run,
    close_program_window,
    create_application,
    create_program,
    create_school,
    create_district,
    draw_lottery,
    get_application,
    get_program,
    iso_utc,
    make_district_admin_headers,
    open_program_window,
    setup_district_with_school_and_program,
    setup_family_with_student,
    setup_open_program_with_one_application,
    setup_drawn_program_with_single_offer,
    setup_drawn_program_with_offer_and_one_waitlisted,
    submit_application,
    validate_error,
    validate_success,
)


class TestDrawPreconditions:

    def test_draw_on_open_program_rejected_with_not_ready(self, api):
        """PRD §3.5: "a SCHEDULED or OPEN program is rejected with
        ERR_LOTTERY_NOT_READY".

        Claim: invoking lottery/draw while window_status == OPEN
        yields ERR_LOTTERY_NOT_READY.
        """
        district, school, program = setup_district_with_school_and_program()
        open_program_window(program)
        res = api.draw_lottery(
            program["id"], make_district_admin_headers(district["id"]),
        )
        validate_error(res, ApiErrorId.ERR_LOTTERY_NOT_READY.value)

    def test_draw_on_scheduled_program_rejected_with_not_ready(self, api):
        """PRD §3.5: "a SCHEDULED or OPEN program is rejected with
        ERR_LOTTERY_NOT_READY"."""
        district, school, program = setup_district_with_school_and_program()
        res = api.draw_lottery(
            program["id"], make_district_admin_headers(district["id"]),
        )
        validate_error(res, ApiErrorId.ERR_LOTTERY_NOT_READY.value)

    def test_draw_without_seed_rejected_with_seed_missing(self, api):
        """PRD §3.5: "The program's lottery_seed must be set and
        non-empty, or the draw is rejected with ERR_LOTTERY_SEED_MISSING."
        """
        # Build a program without a seed. PRD §3.1 says the seed is
        # optional at creation.
        advance_clock_to(DEFAULT_BASE_CLOCK)
        district = create_district()
        school = create_school(district, grade_levels_offered=[5])
        program = create_program(
            district, school,
            grade_level=5, seats_total=1,
            registration_open_at=iso_utc(DEFAULT_BASE_CLOCK + timedelta(days=1)),
            registration_close_at=iso_utc(DEFAULT_BASE_CLOCK + timedelta(days=30)),
            lottery_seed=None,  # omitted at creation
        )
        # Need at least one SUBMITTED applicant — open & submit one app.
        family, student = setup_family_with_student(district)
        from test_helpers import create_application as create_app
        app = create_app(family, student, program, choice_rank=1)
        open_program_window(program)
        submit_application(family, app)
        close_program_window(program)
        res = api.draw_lottery(
            program["id"], make_district_admin_headers(district["id"]),
        )
        validate_error(res, ApiErrorId.ERR_LOTTERY_SEED_MISSING.value)

    def test_second_draw_rejected_with_already_drawn(self, api):
        """PRD §3.5: "a LOTTERY_DRAWN or BACKFILL program is rejected
        with ERR_LOTTERY_ALREADY_DRAWN."

        Claim: calling /lottery/draw again after a successful draw
        yields ERR_LOTTERY_ALREADY_DRAWN.
        """
        district, school, program, family, student, app, run = (
            setup_drawn_program_with_single_offer()
        )
        res = api.draw_lottery(
            program["id"], make_district_admin_headers(district["id"]),
        )
        validate_error(res, ApiErrorId.ERR_LOTTERY_ALREADY_DRAWN.value)


class TestDrawSideEffects:

    def test_draw_transitions_program_to_lottery_drawn(self, api):
        """PRD §3.5 state machine: CLOSED → LOTTERY_DRAWN.

        Claim: a successful draw flips window_status from CLOSED to
        LOTTERY_DRAWN.
        """
        district, school, program, family, student, app, run = (
            setup_drawn_program_with_single_offer()
        )
        prog = get_program(program["id"])
        assert prog["window_status"] == "LOTTERY_DRAWN"

    def test_draw_offers_top_seats_total_apps(self, api):
        """PRD §3.5: "The top seats_total applications in this ordering
        transition from SUBMITTED to OFFERED."

        Claim: with seats_total=1 and 2 submitted applicants, exactly
        one is OFFERED and the other WAITLISTED.
        """
        bundle = setup_drawn_program_with_offer_and_one_waitlisted()
        assert bundle["winner"]["status"] == "OFFERED"
        assert bundle["loser"]["status"] == "WAITLISTED"
        prog = get_program(bundle["program"]["id"])
        assert prog["seats_offered"] == 1
        assert prog["seats_accepted"] == 0

    def test_waitlist_position_assigned_1_based(self, api):
        """PRD §3.5: "The remaining applications transition from
        SUBMITTED to WAITLISTED with their waitlist_position assigned
        1, 2, 3, and so on in the same ordering — that is,
        waitlist_position 1 goes to the highest-ranked non-offered
        application."
        """
        bundle = setup_drawn_program_with_offer_and_one_waitlisted()
        loser = bundle["loser"]
        assert loser["waitlist_position"] == 1

    def test_offered_application_has_offer_expires_at_set(self, api):
        """PRD §3.5: "Each such offer sets offer_expires_at to Clock.now
        plus 168 hours (the offer-response window of 7 days)".

        Claim: offer_expires_at is non-null after the draw.
        """
        district, school, program, family, student, app, run = (
            setup_drawn_program_with_single_offer()
        )
        assert app["status"] == "OFFERED"
        assert app["offer_expires_at"] is not None

    def test_lottery_run_audit_record_shape(self, api):
        """PRD §3.5: "The system writes a LotteryRun audit record
        containing this program's program_id, a snapshot of the seed in
        seed_used, the drawn_at instant equal to Clock.now, the
        applications_ranked array (an ordered list of {application_id,
        lottery_score, rank} entries with rank 1 corresponding to the
        highest score), and offers_issued_count set to the number of
        offers issued (which excludes the waitlisted entries)."
        """
        district, school, program, family, student, app, run = (
            setup_drawn_program_with_single_offer()
        )
        assert_lottery_run(run)
        assert run["program_id"] == program["id"]
        assert run["offers_issued_count"] == 1
        assert run["seed_used"] == "seed-test"
        assert len(run["applications_ranked"]) >= 1


class TestRankingOrdering:

    def test_priority_dominates_lottery_score(self, api):
        """PRD §3.5: "Priority dominates: a SIBLING_IN_DISTRICT
        application with a low lottery_score still beats an
        IN_DISTRICT_STANDARD application with a high lottery_score."

        Claim: when one applicant is SIBLING_IN_DISTRICT and the other
        is IN_DISTRICT_STANDARD on the same program with seats_total=1,
        the sibling-priority applicant always wins regardless of
        lottery_score draw.
        """
        # Build family with anchor first (via a prior accepted app).
        from test_helpers import (
            setup_accepted_application_with_anchor,
            create_program,
            create_school,
            create_district,
            create_student,
            create_application,
            open_program_window,
            close_program_window,
            draw_lottery,
            submit_application,
            setup_family_with_student,
            create_family,
            advance_clock_to,
            DEFAULT_BASE_CLOCK,
        )
        # Family F has an ACCEPTED anchor (S1 accepted on prior
        # program). Now build a NEW program P2 in the same district
        # with a NEW student S2 and a competing OUTSIDER family F2.
        district, school_anchor, program_anchor, family, student_anchor, anchor_app = (
            setup_accepted_application_with_anchor(seed="anchor-priority")
        )
        # Refresh family — it should now have the anchor set.
        from test_helpers import get_family
        family = get_family(family["id"])
        assert family["head_household_application_id"] == anchor_app["id"]
        # Build a second program under the same school + district with
        # a fresh seed and a new student in F.
        program2 = create_program(
            district, school_anchor,
            grade_level=5,
            seats_total=1,
            registration_open_at=iso_utc(DEFAULT_BASE_CLOCK + timedelta(days=40)),
            registration_close_at=iso_utc(DEFAULT_BASE_CLOCK + timedelta(days=70)),
            lottery_seed="seed-p2",
        )
        # Sibling student S2 in family F (anchor present → priority is
        # SIBLING_IN_DISTRICT for in-district program2).
        from test_helpers import create_student
        student2 = create_student(family, grade_level_next_year=5)
        sibling_app = create_application(family, student2, program2, choice_rank=1)
        # Outsider family F2 — same district residency, no anchor.
        family_out = create_family(district, poverty_index_score=0.10)
        student_out = create_student(family_out, grade_level_next_year=5)
        outsider_app = create_application(
            family_out, student_out, program2, choice_rank=1,
        )
        # Open program2 window — advance clock to its open instant.
        open_program_window(program2)
        sibling_app = submit_application(family, sibling_app)
        outsider_app = submit_application(family_out, outsider_app)
        # Close + draw.
        close_program_window(program2)
        run = draw_lottery(district, program2)
        sibling_after = get_application(sibling_app["id"])
        outsider_after = get_application(outsider_app["id"])
        assert sibling_after["priority_category"] == "SIBLING_IN_DISTRICT"
        assert outsider_after["priority_category"] == "IN_DISTRICT_STANDARD"
        assert sibling_after["status"] == "OFFERED", \
            "PRD §3.5: SIBLING_IN_DISTRICT priority dominates lottery_score"
        assert outsider_after["status"] == "WAITLISTED"
