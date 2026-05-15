"""Offer-response lifecycle (accept / decline / expire / withdraw)
and the cascades they trigger.

Covers PRD §3.6 (responding to an offer, sibling-anchor cascade,
withdraw-grace).
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_BASE_CLOCK,
    accept_application,
    advance_clock_iso,
    advance_clock_to,
    api_client,
    create_application,
    create_program,
    decline_application,
    draw_lottery,
    get_application,
    get_family,
    get_program,
    iso_utc,
    make_family_user_headers,
    open_program_window,
    close_program_window,
    setup_accepted_application_with_anchor,
    setup_drawn_program_with_offer_and_one_waitlisted,
    setup_drawn_program_with_single_offer,
    setup_family_with_student,
    setup_post_grace_accepted_application,
    submit_application,
    validate_error,
    validate_success,
    withdraw_application,
)


class TestAccept:

    def test_accept_transitions_offered_to_accepted(self, api):
        """PRD §3.6: "Acceptance transitions the application from
        OFFERED to ACCEPTED and requires both that the application's
        current status be OFFERED and that Clock.now be strictly
        earlier than the application's offer_expires_at."
        """
        district, school, program, family, student, app, run = (
            setup_drawn_program_with_single_offer()
        )
        assert app["status"] == "OFFERED"
        res = api.accept_application(app["id"], make_family_user_headers(family["id"]))
        accepted = validate_success(res, 200)
        assert accepted["status"] == "ACCEPTED"

    def test_accept_increments_seats_accepted(self, api):
        """PRD §3.6: "On acceptance the program's seats_accepted
        increases by one."
        """
        district, school, program, family, student, app, run = (
            setup_drawn_program_with_single_offer()
        )
        before = get_program(program["id"])
        accept_application(family, app)
        after = get_program(program["id"])
        assert after["seats_accepted"] == before["seats_accepted"] + 1

    def test_accept_sets_family_anchor_when_null(self, api):
        """PRD §3.6: "If the family's head_household_application_id is
        currently null, this application's id is recorded as the new
        anchor."
        """
        district, school, program, family, student, app, run = (
            setup_drawn_program_with_single_offer()
        )
        family_before = get_family(family["id"])
        assert family_before.get("head_household_application_id") is None
        accept_application(family, app)
        family_after = get_family(family["id"])
        assert family_after["head_household_application_id"] == app["id"]

    def test_accept_on_non_offered_rejected(self, api):
        """PRD §3.6: state check evaluated before temporal check.

        PRD §2.8 priority conflict B: "once the sweep has run, the same
        request fails earlier with ERR_INVALID_STATE_FOR_TRANSITION
        because the row is no longer OFFERED."

        Claim: accept on a DRAFT app yields
        ERR_INVALID_STATE_FOR_TRANSITION.
        """
        from test_helpers import setup_district_with_school_and_program
        district, school, program = setup_district_with_school_and_program()
        family, student = setup_family_with_student(district)
        from test_helpers import create_application as create_app
        app = create_app(family, student, program, choice_rank=1)
        assert app["status"] == "DRAFT"
        res = api.accept_application(app["id"], make_family_user_headers(family["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_FOR_TRANSITION.value)


class TestDecline:

    def test_decline_transitions_offered_to_declined(self, api):
        """PRD §3.6: "Decline transitions the application from OFFERED
        to DECLINED, decrements the program's seats_offered by one,
        and runs the waitlist-backfill rule on the same program."
        """
        district, school, program, family, student, app, run = (
            setup_drawn_program_with_single_offer()
        )
        res = api.decline_application(app["id"], make_family_user_headers(family["id"]))
        declined = validate_success(res, 200)
        assert declined["status"] == "DECLINED"

    def test_decline_decrements_seats_offered_when_waitlist_empty(self, api):
        """PRD §3.6: "Decline transitions the application from OFFERED
        to DECLINED, decrements the program's seats_offered by one".

        Claim: when the waitlist is empty, decline reduces seats_offered
        by one and no promotion happens.
        """
        district, school, program, family, student, app, run = (
            setup_drawn_program_with_single_offer()
        )
        before = get_program(program["id"])
        assert before["seats_offered"] == 1
        decline_application(family, app)
        after = get_program(program["id"])
        assert after["seats_offered"] == 0


class TestExpire:

    def test_offer_auto_expires_at_offer_expires_at_via_clock_sweep(self, api):
        """PRD §3.6 / §2.10: "When the operator-driven clock advance
        sweep observes that an application's offer_expires_at has been
        reached, the application transitions from OFFERED to EXPIRED".

        Claim: advancing the clock past offer_expires_at flips the
        application to EXPIRED.
        """
        district, school, program, family, student, app, run = (
            setup_drawn_program_with_single_offer()
        )
        oea = app["offer_expires_at"]
        # Advance the clock to (and slightly past) offer_expires_at.
        # PRD says "has been reached" → Clock.now >= offer_expires_at.
        advance_clock_iso(oea)
        app_after = get_application(app["id"])
        assert app_after["status"] == "EXPIRED", (
            "PRD §3.6: clock-advance sweep transitions OFFERED → EXPIRED "
            "when offer_expires_at has been reached"
        )


class TestWithdraw:

    def test_withdraw_within_grace_succeeds(self, api):
        """PRD §3.6: "A family may also withdraw an application that
        has already reached ACCEPTED, but only while Clock.now is
        strictly earlier than the lottery's drawn_at plus the
        withdraw-grace window of 14 days".

        Claim: within the grace window, withdraw succeeds and
        transitions ACCEPTED → WITHDRAWN.
        """
        district, school, program, family, student, accepted = (
            setup_accepted_application_with_anchor()
        )
        res = api.withdraw_application(
            accepted["id"], make_family_user_headers(family["id"]),
        )
        withdrawn = validate_success(res, 200)
        assert withdrawn["status"] == "WITHDRAWN"

    def test_withdraw_after_grace_rejected(self, api):
        """PRD §3.6: "an attempt past that grace deadline is rejected
        with ERR_WITHDRAW_GRACE_PASSED."
        """
        bundle = setup_post_grace_accepted_application()
        res = api.withdraw_application(
            bundle["application"]["id"],
            make_family_user_headers(bundle["family"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_WITHDRAW_GRACE_PASSED.value)


class TestSiblingCascade:

    def test_accept_cascades_other_offers_for_same_student_to_withdrawn(self, api):
        """PRD §3.6: "every other application by the same student that
        is currently in OFFERED (in any other program) transitions to
        WITHDRAWN".

        Claim: a student holding TWO OFFERED applications (different
        programs) sees one transitioned to ACCEPTED and the other
        cascaded to WITHDRAWN.
        """
        from test_helpers import (
            setup_district_with_school_and_program,
            create_program,
            create_student,
            create_application,
            open_program_window,
            close_program_window,
            draw_lottery,
            submit_application,
            setup_family_with_student,
            advance_clock_to,
        )
        district, school, program1 = setup_district_with_school_and_program(
            seats_total=1, seed="p1-cascade",
        )
        program2 = create_program(
            district, school,
            grade_level=5,
            seats_total=1,
            registration_open_at=iso_utc(DEFAULT_BASE_CLOCK + timedelta(days=1)),
            registration_close_at=iso_utc(DEFAULT_BASE_CLOCK + timedelta(days=30)),
            lottery_seed="p2-cascade",
        )
        family, student = setup_family_with_student(district)
        app1 = create_application(family, student, program1, choice_rank=1)
        app2 = create_application(family, student, program2, choice_rank=2)
        open_program_window(program1)
        app1 = submit_application(family, app1)
        app2 = submit_application(family, app2)
        close_program_window(program1)
        # Both programs share the same close instant, so program2 is
        # also CLOSED by this point.
        prog2 = get_program(program2["id"])
        assert prog2["window_status"] == "CLOSED"
        draw_lottery(district, program1)
        draw_lottery(district, program2)
        app1_after = get_application(app1["id"])
        app2_after = get_application(app2["id"])
        assert app1_after["status"] == "OFFERED"
        assert app2_after["status"] == "OFFERED"
        # Accept app1.
        accept_application(family, app1_after)
        app1_final = get_application(app1["id"])
        app2_final = get_application(app2["id"])
        assert app1_final["status"] == "ACCEPTED"
        assert app2_final["status"] == "WITHDRAWN", (
            "PRD §3.6: accept cascades other OFFERED apps by same student "
            "to WITHDRAWN"
        )
