"""Transfer Portal entry, window evaluation, withdrawal, commitment.

PRD §3.4 (portal entry, holding period, contact window, withdrawal,
commitment, immediate eligibility), §2.10 (clock).
"""
from __future__ import annotations

import pytest
from datetime import timedelta

from test_helpers import (
    PORTAL_HOLDING_PERIOD_HOURS,
    TEST_USERS,
    WINDOW_DAYS_AMATEUR,
    advance_clock_to,
    assert_transfer_portal_entry,
    create_athlete,
    create_eligibility_record,
    create_portal_entry,
    create_program,
    create_transfer_portal_entry_payload,
    iso_utc,
    make_athlete_headers,
    offer_slot,
    parse_iso,
    setup_enrolled_athlete,
    setup_portal_entry_in_contact_window,
    sign_slot,
    submit_nil_deal,
    review_nil_deal,
    transition_transfer_portal_entry_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.4 Portal entry side effects
# ===========================================================================
class TestPortalEntryCreation:
    """PRD §3.4: "On successful creation, the entry stores
    origin_program_id (the athlete's current_program_id at this
    instant), pins entered_at to the request timestamp, computes
    window_closes_at per the transfer_window_close rule, and starts in
    ENTERED status." """

    def test_entry_initializes_status_and_origin_program(self, api):
        """PRD §3.4: "On successful creation, the entry stores
        origin_program_id (the athlete's current_program_id at this
        instant), pins entered_at to the request timestamp ... and
        starts in ENTERED status."

        Claim: a freshly created entry has status=ENTERED,
        origin_program_id == the athlete's current_program_id at
        entry time, entered_at set, window_closes_at set.
        """
        athlete, program, _slot = setup_enrolled_athlete()
        entry = create_portal_entry(athlete["id"])
        assert_transfer_portal_entry(entry)
        assert entry["status"] == "ENTERED"
        assert entry["origin_program_id"] == program["id"]
        assert entry.get("entered_at")
        assert entry.get("window_closes_at")

    def test_entry_sets_athlete_to_transfer_portal_and_clears_program(
        self, api, officer_headers,
    ):
        """PRD §3.4: "The act of entering the portal cascades through
        several entities. The athlete moves ENROLLED -> TRANSFER_PORTAL,
        and current_program_id is set to null."

        Claim: after POST /transfer-portal-entries, the athlete has
        status=TRANSFER_PORTAL and current_program_id is null.
        """
        athlete, _program, _slot = setup_enrolled_athlete()
        create_portal_entry(athlete["id"])
        a_resp = api.get_athlete(athlete["id"], officer_headers)
        a_data = validate_success(a_resp)
        assert a_data["status"] == "TRANSFER_PORTAL"
        assert a_data.get("current_program_id") in (None, "")


# ===========================================================================
# §3.4 ERR_PORTAL_INELIGIBLE (FORFEITED amateur_status)
# ===========================================================================
class TestPortalForfeited:
    """PRD §3.4: "a FORFEITED athlete receives zero days — meaning a
    forfeited athlete cannot enter the portal at all, and the
    creation attempt is rejected with ERR_PORTAL_INELIGIBLE." """

    def test_forfeited_athlete_cannot_enter_portal(
        self, api, officer_headers,
    ):
        """PRD §3.4: "a FORFEITED athlete receives zero days — meaning
        a forfeited athlete cannot enter the portal at all, and the
        creation attempt is rejected with ERR_PORTAL_INELIGIBLE."

        Claim: posting a TransferPortalEntry for an athlete whose
        amateur_status is FORFEITED -> ERR_PORTAL_INELIGIBLE.

        Coverage note: PRD §3.7 pins that the only way to reach
        amateur_status=FORFEITED is via a LEVEL_I SUSTAINED cascade,
        which also flips the athlete ENROLLED -> INELIGIBLE. Per
        PRD §3.4, portal creation also requires the athlete be in
        ENROLLED — so the test setup necessarily violates BOTH the
        forfeited rule (FORFEITED amateur_status) and the from-state
        rule (athlete not ENROLLED). PRD §2.8 enumerates ERR_INVALID_STATE
        at priority 6 but does NOT enumerate ERR_PORTAL_INELIGIBLE in
        the priority list — so a PRD-faithful reader could land on
        either error first. We accept either.
        """
        from test_helpers import (
            setup_ineligible_athlete_via_violation,
            validate_error_is_one_of,
        )
        _program, athlete, _v = setup_ineligible_athlete_via_violation()
        assert athlete["amateur_status"] == "FORFEITED"
        # PRD §3.4 portal entry creation can be invoked by Athlete or
        # ComplianceOfficer. Use officer to avoid the athlete's
        # INELIGIBLE status from blocking via ERR_FORBIDDEN/other.
        res = api.create_transfer_portal_entry(
            create_transfer_portal_entry_payload(
                athlete_id=athlete["id"], reason="PLAYING_TIME",
            ),
            officer_headers,
        )
        validate_error_is_one_of(
            res, ["ERR_PORTAL_INELIGIBLE", "ERR_INVALID_STATE"],
        )


# ===========================================================================
# §3.4 Duplicate active entry blocked
# ===========================================================================
class TestPortalDuplicate:
    """PRD §3.4: "The athlete also may not already have a
    TransferPortalEntry in ENTERED or CONTACT_WINDOW status; a
    duplicate active entry is rejected with
    ERR_DUPLICATE_PORTAL_ENTRY." """

    def test_second_active_entry_rejected(self, api, officer_headers):
        """PRD §3.4: "The athlete also may not already have a
        TransferPortalEntry in ENTERED or CONTACT_WINDOW status; a
        duplicate active entry is rejected with
        ERR_DUPLICATE_PORTAL_ENTRY."

        Claim: a second POST /transfer-portal-entries for the same
        athlete while their first entry is in ENTERED ->
        ERR_DUPLICATE_PORTAL_ENTRY.

        Coverage note: the first portal entry cascades the athlete
        ENROLLED -> TRANSFER_PORTAL (PRD §3.4), so by the time the
        second entry is posted the athlete is no longer in ENROLLED.
        PRD §2.8 priority 6 (from-state validity) and priority 20
        (active portal-entry uniqueness) both apply, and PRD does
        not explicitly state which fires first for portal creation.
        We accept either error.
        """
        from test_helpers import validate_error_is_one_of
        athlete, _p, _s = setup_enrolled_athlete()
        create_portal_entry(athlete["id"])
        # Now try again with a different reason.
        res = api.create_transfer_portal_entry(
            create_transfer_portal_entry_payload(
                athlete_id=athlete["id"], reason="COACHING_CHANGE",
            ),
            officer_headers,
        )
        validate_error_is_one_of(
            res, ["ERR_DUPLICATE_PORTAL_ENTRY", "ERR_INVALID_STATE"],
        )


# ===========================================================================
# §3.4 ERR_PENDING_NIL_REVIEW
# ===========================================================================
class TestPortalPendingReview:
    """PRD §3.4: "The athlete must currently be in ENROLLED and must
    have no NILDeal in UNDER_REVIEW status (a pending NIL review
    blocks portal entry with ERR_PENDING_NIL_REVIEW)." """

    def test_portal_entry_blocked_by_pending_nil_review(
        self, api, officer_headers, officer_headers_secondary,
    ):
        """PRD §3.4: "must have no NILDeal in UNDER_REVIEW status (a
        pending NIL review blocks portal entry with
        ERR_PENDING_NIL_REVIEW)."

        Claim: with an NIL deal in UNDER_REVIEW on the athlete, posting
        a portal entry -> ERR_PENDING_NIL_REVIEW.
        """
        athlete, _p, _s = setup_enrolled_athlete()
        # Submit as Athlete (entity-backed), review as PRIMARY officer.
        d = submit_nil_deal(athlete["id"])
        review_nil_deal(d["id"], headers=officer_headers_secondary)
        # Deal is now UNDER_REVIEW.
        res = api.create_transfer_portal_entry(
            create_transfer_portal_entry_payload(
                athlete_id=athlete["id"], reason="PLAYING_TIME",
            ),
            officer_headers,
        )
        validate_error(res, "ERR_PENDING_NIL_REVIEW")


# ===========================================================================
# §3.4 ENTERED -> WITHDRAWN
# ===========================================================================
class TestPortalEarlyWithdraw:
    """PRD §3.4: "An Athlete or a ComplianceOfficer may withdraw the
    entry directly out of ENTERED (before the holding period elapses).
    This ENTERED -> WITHDRAWN transition has no precondition and rolls
    the athlete back to ENROLLED at the origin_program_id." """

    def test_withdraw_from_entered_rolls_back_to_enrolled(
        self, api, officer_headers,
    ):
        """PRD §3.4: "This ENTERED -> WITHDRAWN transition has no
        precondition and rolls the athlete back to ENROLLED at the
        origin_program_id."

        Claim: ENTERED -> WITHDRAWN succeeds and the athlete returns
        to ENROLLED with current_program_id = origin_program_id.
        """
        athlete, program, _slot = setup_enrolled_athlete()
        entry = create_portal_entry(athlete["id"])
        res = api.transition_transfer_portal_entry(
            entry["id"],
            transition_transfer_portal_entry_payload(
                to_status="WITHDRAWN",
            ),
            officer_headers,
        )
        data = validate_success(res)
        assert data["status"] == "WITHDRAWN"
        # Verify athlete rollback.
        a_resp = api.get_athlete(athlete["id"], officer_headers)
        a_data = validate_success(a_resp)
        assert a_data["status"] == "ENROLLED"
        assert a_data["current_program_id"] == program["id"]


# ===========================================================================
# §2.10 Clock-driven ENTERED -> CONTACT_WINDOW
# ===========================================================================
class TestClockDrivenContactWindow:
    """PRD §3.4 / §2.10: "The entry sits in ENTERED for 24 hours and
    then automatically transitions to CONTACT_WINDOW when the logical
    clock reaches entered_at + 24 hours. This transition is fired by
    a clock advance and never by a direct API call." """

    def test_clock_advance_past_24h_transitions_to_contact_window(
        self, api,
    ):
        """PRD §3.4: "The entry sits in ENTERED for 24 hours and then
        automatically transitions to CONTACT_WINDOW when the logical
        clock reaches entered_at + 24 hours."

        Claim: advance clock to entered_at + 25 hours -> entry status
        becomes CONTACT_WINDOW.
        """
        athlete, program, entry = setup_portal_entry_in_contact_window()
        assert entry["status"] == "CONTACT_WINDOW", (
            f"expected CONTACT_WINDOW after clock advance, got "
            f"{entry['status']}"
        )


# ===========================================================================
# §3.4 CONTACT_WINDOW -> COMMITTED requires SIGNED slot at destination
# ===========================================================================
class TestPortalCommit:
    """PRD §3.4: "the destination program already has a SIGNED
    ScholarshipSlot for this athlete". """

    def test_commit_without_signed_slot_at_destination_rejected(
        self, api, officer_headers,
    ):
        """PRD §3.4: "the destination program already has a SIGNED
        ScholarshipSlot for this athlete".
        PRD §5: ERR_NO_SIGNED_SLOT is the error for "Athlete
        PROSPECTIVE->COMMITTED requires a SIGNED ScholarshipSlot for
        the same program", and PRD §3.4 reuses this precondition by
        triggering the Athlete TRANSFER_PORTAL->COMMITTED transition.

        Claim: portal CONTACT_WINDOW -> COMMITTED with a
        destination_program_id that has no SIGNED slot for the
        athlete -> rejection (either ERR_NO_SIGNED_SLOT or a
        precondition error). We assert it does not succeed; PRD prose
        is explicit the precondition fails, so the call must 4xx.
        """
        athlete, _origin_program, entry = (
            setup_portal_entry_in_contact_window()
        )
        # Build a destination program with no slot for this athlete.
        dest_program = create_program()
        res = api.transition_transfer_portal_entry(
            entry["id"],
            transition_transfer_portal_entry_payload(
                to_status="COMMITTED",
                destination_program_id=dest_program["id"],
            ),
            officer_headers,
        )
        # PRD §3.4: the COMMITTED move triggers Athlete
        # TRANSFER_PORTAL->COMMITTED whose preconditions include
        # ERR_NO_SIGNED_SLOT.
        validate_error(res, "ERR_NO_SIGNED_SLOT")


# ===========================================================================
# §3.4 CONTACT_WINDOW -> WITHDRAWN window check
# ===========================================================================
class TestPortalWindowWithdraw:
    """PRD §3.4: "This too requires the current clock to be strictly
    less than window_closes_at." """

    def test_withdraw_after_window_closes_rejected(self, api, officer_headers):
        """PRD §3.4: "This too requires the current clock to be
        strictly less than window_closes_at."

        Claim: advancing clock past window_closes_at then attempting
        CONTACT_WINDOW -> WITHDRAWN -> ERR_PORTAL_WINDOW_CLOSED. Note:
        per PRD §2.10 clock advance fires CONTACT_WINDOW -> EXPIRED
        automatically when clock crosses window_closes_at; in that
        case the entry is no longer in CONTACT_WINDOW and the explicit
        withdraw attempt would 409 with ERR_INVALID_STATE (the loser
        of the implicit race per PRD §3.4). We accept either outcome
        per the §3.4 race semantics: "exactly one terminal transition
        wins; loser sees ERR_INVALID_STATE".
        """
        from test_helpers import validate_error_is_one_of
        athlete, _program, entry = setup_portal_entry_in_contact_window()
        # Advance past window_closes_at.
        close_at = parse_iso(entry["window_closes_at"])
        target = close_at + timedelta(seconds=1)
        advance_clock_to(iso_utc(target))
        res = api.transition_transfer_portal_entry(
            entry["id"],
            transition_transfer_portal_entry_payload(
                to_status="WITHDRAWN",
            ),
            officer_headers,
        )
        # PRD §3.4 documents both outcomes are well-defined: either
        # ERR_PORTAL_WINDOW_CLOSED (if the §2.8 priority-15 check
        # fires first) or ERR_INVALID_STATE (if the auto-expire
        # already fired). PRD does not commit to a tie-breaker
        # between the two: cite the §3.4 "first-writer-wins on
        # TransferPortalEntry.status" prose.
        validate_error_is_one_of(
            res,
            ["ERR_PORTAL_WINDOW_CLOSED", "ERR_INVALID_STATE"],
        )


# ===========================================================================
# §2.10 Clock auto-expire CONTACT_WINDOW -> EXPIRED
# ===========================================================================
class TestPortalAutoExpire:
    """PRD §2.10: "TransferPortalEntry CONTACT_WINDOW -> EXPIRED for
    every entry whose window_closes_at has been crossed." """

    def test_clock_advance_past_window_close_expires_entry(self, api):
        """PRD §2.10: "TransferPortalEntry CONTACT_WINDOW -> EXPIRED
        for every entry whose window_closes_at has been crossed."

        Claim: advance clock past window_closes_at -> entry.status
        becomes EXPIRED on the next clock read.
        """
        athlete, _program, entry = setup_portal_entry_in_contact_window()
        close_at = parse_iso(entry["window_closes_at"])
        target = close_at + timedelta(seconds=2)
        advance_clock_to(iso_utc(target))
        e_resp = api.get_transfer_portal_entry(
            entry["id"], TEST_USERS["officer_headers"],
        )
        e_data = validate_success(e_resp)
        assert e_data["status"] == "EXPIRED"


# ===========================================================================
# §2.1 Athlete ownership on portal entry creation
# ===========================================================================
class TestAthleteOwnershipOnPortalEntry:
    """PRD §2.1: "an Athlete who supplies someone else's athlete_id
    when submitting an NIL deal or entering the portal is rejected
    with ERR_FORBIDDEN." """

    def test_athlete_cannot_enter_portal_for_other_athlete(self, api):
        """PRD §2.1: "an Athlete who supplies someone else's
        athlete_id when submitting an NIL deal or entering the portal
        is rejected with ERR_FORBIDDEN."

        Claim: Athlete A1 calling POST /transfer-portal-entries with
        athlete_id=A2 -> ERR_FORBIDDEN.
        """
        a1, _p1, _s1 = setup_enrolled_athlete()
        a2, _p2, _s2 = setup_enrolled_athlete()
        res = api.create_transfer_portal_entry(
            create_transfer_portal_entry_payload(
                athlete_id=a2["id"], reason="PLAYING_TIME",
            ),
            make_athlete_headers(a1["id"]),
        )
        validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# §3.4 transfer_window_close: 45-day vs 30-day window
# ===========================================================================
class TestPortalWindowLength:
    """PRD §3.4: "an AMATEUR athlete receives a 45-day window, an
    AT_RISK athlete receives a 30-day window ... window_closes_at
    equals entered_at plus the window length expressed in hours
    (so 45 days resolves to 1080 hours, and 30 days resolves to 720
    hours)". """

    def test_amateur_athlete_45_day_window(self, api):
        """PRD §3.4: "an AMATEUR athlete receives a 45-day window ...
        45 days resolves to 1080 hours".

        Claim: for an AMATEUR athlete, window_closes_at - entered_at
        equals 45 days = 1080 hours.
        """
        athlete, _program, _slot = setup_enrolled_athlete()
        entry = create_portal_entry(athlete["id"])
        entered_at = parse_iso(entry["entered_at"])
        closes_at = parse_iso(entry["window_closes_at"])
        delta = closes_at - entered_at
        # Carry to second precision per PRD §3.4 scaffold note.
        assert delta == timedelta(days=WINDOW_DAYS_AMATEUR), (
            f"expected 45-day window = 1080h, got {delta}"
        )
