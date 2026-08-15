"""Notification phase: bulk issuance, RSVP answers, and the waitlist
promotion cascade (PRD §2.4, §3.6)."""
from datetime import datetime, timezone

from test_helpers import (
    fx_invited,
    make_filmmaker_headers,
    parse_instant,
    set_clock,
    st_agreement_for, st_package_for,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
DIRECTOR = TEST_USERS["director_headers"]


def _two_film_invite(api):
    """Edition NOTIFICATION; capacity-1 SHORTS slate with film 0 rank 1
    (MAIN/INVITED) and film 1 rank 2 (WAITLIST/NOMINATED)."""
    return fx_invited(
        films=[
            {"title": "Main Film", "scores": [("STAFF", 9), ("STAFF", 9)]},
            {"title": "Wait Film", "scores": [("STAFF", 8), ("STAFF", 8)]},
        ],
        capacity_slots=1,
    )


class TestBulkIssuance:
    def test_issue_invitations_bulk_declines_unslated(self, api, director_headers,
                                                      admin_headers):
        """PRD §3.6: "Films still `IN_SCREENING` that sit on no locked slate
        are declined in the same sweep, moving to `DECLINED`. The issuance
        response enumerates what happened through `invited_entry_ids`,
        `declined_submission_ids`, and `waitlisted_submission_ids`."

        Design: Corner/endpoints/issue_invitations_bulk_declines_unslated
        """
        ctx = fx_invited(
            films=[{"title": "Slated"}, {"title": "Unslated"}],
            capacity_slots=1,
            entry_order=[0],  # film 1 never reaches a slate
        )
        invitations = ctx["invitations"]
        entry_s = ctx["entries"][0]
        film_u = ctx["films"][1]["film"]["id"]
        assert invitations["invited_entry_ids"] == [entry_s["id"]]
        assert invitations["waitlisted_submission_ids"] == []
        assert invitations["declined_submission_ids"] == [film_u]
        film = validate_success(api.get_submission(film_u, admin_headers))
        assert film["status"] == "DECLINED"


class TestAutoCreatedArtifacts:
    def test_travel_package_and_agreement_auto_created_draft_on_accept(self, api):
        """PRD §3.6: acceptance "moves the entry `INVITED` → `CONFIRMED` and
        the film `INVITED` → `CONFIRMED`, and the system immediately creates
        two `DRAFT` artifacts linked to the film: a travel package — one per
        confirmed submission — and an exhibition agreement keyed to the
        accepting entry"; §3.7: "until approval both fields read zero".

        Design: Corner/entities/travel_package_auto_created_draft_on_accept
        """
        ctx = fx_invited(films=1, capacity_slots=1)
        spec = ctx["films"][0]
        entry = ctx["entries"][0]

        answered = validate_success(api.respond_to_entry(
            entry["id"], True, make_filmmaker_headers(spec["submitter"]["id"]),
        ))
        assert answered["status"] == "CONFIRMED"

        package = st_package_for(spec["film"]["id"])
        assert package["status"] == "DRAFT"
        assert package["hotel_nights_allocated"] == 0
        assert package["stipend_cents"] == 0
        assert package["submission_id"] == spec["film"]["id"]

        agreement = st_agreement_for(spec["film"]["id"])
        assert agreement["status"] == "DRAFT"
        assert agreement["slate_entry_id"] == entry["id"]


class TestDeclinePromotionCascade:
    def test_decline_moves_pair_and_promotes_waitlist(self, api):
        """PRD §3.6: "Declining moves the entry `INVITED` → `DECLINED` and
        the film `INVITED` → `DECLINED_BY_FILMMAKER`, and fires the
        waitlist-promotion cascade": "the selector takes the entries still in
        `NOMINATED` status with lane `WAITLIST`, picks the one with the
        smallest `rank_position`, promotes it to lane `MAIN` and status
        `INVITED` ... and moves its film `WAITLISTED` → `INVITED`."

        Design: Difficulty/transitive_cascade/decline_promotes_waitlist_chain
        """
        ctx = _two_film_invite(api)
        main, wait = ctx["films"][0], ctx["films"][1]
        entry_m, entry_w = ctx["entries"][0], ctx["entries"][1]

        answered = validate_success(api.respond_to_entry(
            entry_m["id"], False, make_filmmaker_headers(main["submitter"]["id"]),
        ))
        assert answered["status"] == "DECLINED"

        film_m = validate_success(api.get_submission(main["film"]["id"], ADMIN))
        assert film_m["status"] == "DECLINED_BY_FILMMAKER"

        promoted = validate_success(api.get_slate_entry(entry_w["id"], DIRECTOR))
        assert promoted["lane"] == "MAIN"
        assert promoted["status"] == "INVITED"

        film_w = validate_success(api.get_submission(wait["film"]["id"], ADMIN))
        assert film_w["status"] == "INVITED"

    def test_promotion_sets_fresh_rsvp_deadline(self, api):
        """PRD §3.6: the promoted entry "sets its `rsvp_deadline_at` to the
        current instant plus `rsvp_window_days`" — with the logical clock at
        the 2026-08-01 startup default (§2.4) and the default 7-day window
        (§3.1), the deadline lands at 2026-08-08T00:00:00Z.

        Design: Difficulty/transitive_cascade/decline_promotes_waitlist_chain
        """
        ctx = _two_film_invite(api)
        main = ctx["films"][0]
        entry_m, entry_w = ctx["entries"][0], ctx["entries"][1]

        validate_success(api.respond_to_entry(
            entry_m["id"], False, make_filmmaker_headers(main["submitter"]["id"]),
        ))
        promoted = validate_success(api.get_slate_entry(entry_w["id"], DIRECTOR))
        assert parse_instant(promoted["rsvp_deadline_at"]) == datetime(
            2026, 8, 8, tzinfo=timezone.utc,
        )


class TestRsvpExpirySweep:
    def test_clock_sweep_expires_invitation_and_promotes(self, api):
        """PRD §2.4: "When the clock moves past a slate entry's
        `rsvp_deadline_at`, the unanswered invitation expires and the
        waitlist-promotion cascade runs"; §3.6: "the clock sweep moves the
        entry `INVITED` → `EXPIRED` and the film `INVITED` → `EXPIRED` once
        it passes `rsvp_deadline_at`, firing the same promotion cascade."

        Design: Corner/state_machines/clock_sweep_expires_invitation_and_promotes
        """
        ctx = _two_film_invite(api)
        entry_m, entry_w = ctx["entries"][0], ctx["entries"][1]
        film_m = ctx["films"][0]["film"]["id"]

        # Entry M's invitation was issued at the 2026-08-01 default clock
        # with rsvp_window_days 7, so its deadline is 2026-08-08.
        set_clock("2026-08-09T00:00:00Z")

        expired_entry = validate_success(api.get_slate_entry(entry_m["id"], DIRECTOR))
        assert expired_entry["status"] == "EXPIRED"
        expired_film = validate_success(api.get_submission(film_m, ADMIN))
        assert expired_film["status"] == "EXPIRED"

        promoted = validate_success(api.get_slate_entry(entry_w["id"], DIRECTOR))
        assert promoted["lane"] == "MAIN"
        assert promoted["status"] == "INVITED"
        assert parse_instant(promoted["rsvp_deadline_at"]) == datetime(
            2026, 8, 16, tzinfo=timezone.utc,
        ), "promotion stamps now (2026-08-09) + rsvp_window_days (7)"
