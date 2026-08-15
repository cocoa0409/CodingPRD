"""The screening grid: venues, slots, holds, premiere discipline, licensed
counts, and the CONFIRMED<->PROGRAMMED cycle (PRD §2.7, §3.8; withdrawal
unwind of §3.2)."""
import pytest

from test_helpers import (
    ApiErrorId,
    fx_invited, fx_responded, fx_scheduling, fx_programmed,
    issue_agreement_payload,
    make_filmmaker_headers,
    set_clock,
    st_advance, st_agreement_for, st_edition, st_issue_and_sign, st_slot,
    st_venue,
    validate_error, validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
DIRECTOR = TEST_USERS["director_headers"]
OPS = TEST_USERS["ops_headers"]


class TestSlotCreation:
    def test_screening_slot_window_and_shape_validation(self, api):
        """PRD §3.8: "Every slot must sit inside the festival window —
        `start_at` at or after `festival_start_at` and `end_at` at or before
        `festival_end_at` — with violations rejected as
        `ERR_SLOT_OUTSIDE_FESTIVAL_WINDOW`, and `end_at` must be later than
        `start_at`, with violations rejected as `ERR_VALIDATION`."

        Design: Corner/entities/screening_slot_window_and_shape_validation
        """
        ctx = st_edition(with_config=False)
        venue = st_venue(ctx)

        before_window = api.create_screening_slot(
            {"venue_id": venue["id"], "slot_type": "PUBLIC",
             "start_at": "2027-01-20T17:00:00Z", "end_at": "2027-01-20T19:00:00Z",
             "expected_venue_version": venue["version"]},
            OPS,
        )
        validate_error(before_window, ApiErrorId.ERR_SLOT_OUTSIDE_FESTIVAL_WINDOW.value)

        empty_span = api.create_screening_slot(
            {"venue_id": venue["id"], "slot_type": "PUBLIC",
             "start_at": "2027-01-22T19:00:00Z", "end_at": "2027-01-22T19:00:00Z",
             "expected_venue_version": venue["version"]},
            OPS,
        )
        validate_error(empty_span, ApiErrorId.ERR_VALIDATION.value)

    def test_occ_stale_slot_create(self, api):
        """PRD §2.7: "Creating a screening slot — `POST
        /festival/screening-slots` — requires `expected_venue_version`
        carrying the venue's last observed `version`" and the endpoint
        "rejects the request with `ERR_STALE_VERSION` (HTTP 412) when the
        supplied value does not match the parent entity's current `version`."

        Design: Corner/cross_cutting_layers/occ_stale_slot_create
        """
        ctx = st_edition(with_config=False)
        venue = st_venue(ctx)
        stale_version = venue["version"]

        first = st_slot(venue["id"], {"start_at": "2027-01-22T17:00:00Z",
                                      "end_at": "2027-01-22T18:00:00Z"})
        assert first["status"] == "OPEN"

        replay = api.create_screening_slot(
            {"venue_id": venue["id"], "slot_type": "PUBLIC",
             "start_at": "2027-01-22T19:00:00Z", "end_at": "2027-01-22T20:00:00Z",
             "expected_venue_version": stale_version},
            OPS,
        )
        validate_error(replay, ApiErrorId.ERR_STALE_VERSION.value)

        fresh = validate_success(api.get_venue(venue["id"], OPS))
        second = validate_success(api.create_screening_slot(
            {"venue_id": venue["id"], "slot_type": "PUBLIC",
             "start_at": "2027-01-22T19:00:00Z", "end_at": "2027-01-22T20:00:00Z",
             "expected_venue_version": fresh["version"]},
            OPS,
        ), 201)
        assert second["status"] == "OPEN"


class TestTurnoverBuffer:
    def _venue_with_slot(self, api):
        ctx = st_edition(with_config=False)
        venue = st_venue(ctx, {"turnover_minutes": 30})
        slot = st_slot(venue["id"], {"slot_type": "PUBLIC",
                                     "start_at": "2027-01-22T17:00:00Z",
                                     "end_at": "2027-01-22T19:00:00Z"})
        return venue, slot

    def test_exact_buffer_adjacency_accepted_one_minute_inside_rejected(self, api):
        """PRD §3.8: an existing slot "conflicts with a candidate unless the
        candidate's end plus the venue's `turnover_minutes` is at or before
        the existing slot's start, or the existing slot's end plus the
        turnover buffer is at or before the candidate's start. Two slots
        separated by exactly the turnover buffer therefore do not conflict,
        and a genuine collision is rejected with `ERR_VENUE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/venue_slot_turnover_buffer_overlap
        """
        venue, _slot = self._venue_with_slot(api)
        # Existing 17:00-19:00; candidate starts exactly at 19:00 + 30min.
        adjacent = st_slot(venue["id"], {"slot_type": "PUBLIC",
                                         "start_at": "2027-01-22T19:30:00Z",
                                         "end_at": "2027-01-22T21:00:00Z"})
        assert adjacent["status"] == "OPEN"

        fresh = validate_success(api.get_venue(venue["id"], OPS))
        inside = api.create_screening_slot(
            {"venue_id": venue["id"], "slot_type": "PUBLIC",
             "start_at": "2027-01-22T19:29:00Z", "end_at": "2027-01-22T20:30:00Z",
             "expected_venue_version": fresh["version"]},
            OPS,
        )
        validate_error(inside, ApiErrorId.ERR_VENUE_OVERLAP.value)

    def test_symmetric_leading_adjacency_and_version_stability(self, api):
        """PRD §3.8: "Two slots separated by exactly the turnover buffer
        therefore do not conflict" — the buffer guards the leading edge
        symmetrically; and §3.8: "each created slot increments the venue's
        `version`", so a rejected create must not move it.

        Design: Difficulty/resource_temporal_overlap/venue_slot_turnover_buffer_overlap
        """
        venue, _slot = self._venue_with_slot(api)
        fresh = validate_success(api.get_venue(venue["id"], OPS))
        inside = api.create_screening_slot(
            {"venue_id": venue["id"], "slot_type": "PUBLIC",
             "start_at": "2027-01-22T19:29:00Z", "end_at": "2027-01-22T20:30:00Z",
             "expected_venue_version": fresh["version"]},
            OPS,
        )
        validate_error(inside, ApiErrorId.ERR_VENUE_OVERLAP.value)

        after_reject = validate_success(api.get_venue(venue["id"], OPS))
        assert after_reject["version"] == fresh["version"], (
            "a rejected create must leave the venue version unchanged"
        )

        leading = st_slot(venue["id"], {"slot_type": "PUBLIC",
                                        "start_at": "2027-01-22T16:00:00Z",
                                        "end_at": "2027-01-22T16:30:00Z"})
        assert leading["status"] == "OPEN"


class TestHoldGates:
    def test_hold_blocked_until_agreement_signed(self, api):
        """PRD §3.8: "the exhibition agreement for the entry's submission
        must be `SIGNED` or `ACTIVE`, failing with
        `ERR_AGREEMENT_NOT_SIGNED`."

        Design: Difficulty/cross_entity_state_dependency/slot_hold_requires_signed_agreement
        """
        ctx = fx_responded(films=1, capacity_slots=1, sign_agreements=False)
        agreement = ctx["agreements"][0]
        assert agreement["status"] == "DRAFT"  # auto-created, never issued
        st_advance(ctx, "SCHEDULING")
        venue = st_venue(ctx)
        slot = st_slot(venue["id"])

        blocked = api.hold_slot(slot["id"], ctx["entries"][0]["id"], OPS)
        validate_error(blocked, ApiErrorId.ERR_AGREEMENT_NOT_SIGNED.value)

    def test_hold_succeeds_after_issue_and_sign(self, api):
        """PRD §3.8: once the agreement "must be `SIGNED` or `ACTIVE`"
        condition is met, "A successful hold sets `slate_entry_id` on the
        slot and moves it `OPEN` → `HELD`."

        Design: Difficulty/cross_entity_state_dependency/slot_hold_requires_signed_agreement
        """
        ctx = fx_responded(films=1, capacity_slots=1, sign_agreements=False)
        spec = ctx["films"][0]
        agreement = ctx["agreements"][0]
        st_advance(ctx, "SCHEDULING")
        venue = st_venue(ctx)
        slot = st_slot(venue["id"])

        validate_success(api.issue_agreement(
            agreement["id"], issue_agreement_payload(), DIRECTOR,
        ))
        validate_success(api.sign_agreement(
            agreement["id"], make_filmmaker_headers(spec["submitter"]["id"]),
        ))

        held = validate_success(
            api.hold_slot(slot["id"], ctx["entries"][0]["id"], OPS)
        )
        assert held["status"] == "HELD"
        assert held["slate_entry_id"] == ctx["entries"][0]["id"]

    def test_hold_entry_state_then_edition_phase(self, api):
        """PRD §3.8: a hold requires that the named entry "must be
        `CONFIRMED`, failing with `ERR_ENTRY_NOT_CONFIRMED`" and is "available
        only while the edition is in `SCHEDULING`, otherwise
        `ERR_EDITION_PHASE_FORBIDDEN`"; §2.9 runs the target's state gate
        ("Sixth") before the posture gate ("Seventh").

        Design: Corner/validations/hold_gates_entry_state_then_edition_phase
        """
        ctx = fx_invited(films=1, capacity_slots=1)
        entry = ctx["entries"][0]  # INVITED, edition NOTIFICATION
        venue = st_venue(ctx)
        slot = st_slot(venue["id"])

        not_confirmed = api.hold_slot(slot["id"], entry["id"], OPS)
        validate_error(not_confirmed, ApiErrorId.ERR_ENTRY_NOT_CONFIRMED.value)

        spec = ctx["films"][0]
        validate_success(api.respond_to_entry(
            entry["id"], True, make_filmmaker_headers(spec["submitter"]["id"]),
        ))
        # Acceptance auto-creates a DRAFT agreement (PRD §3.6); §2.9 runs
        # domain state gates (ERR_AGREEMENT_NOT_SIGNED) at step six, before
        # the step-seven posture gate, so the agreement must be SIGNED here
        # for the phase gate to be the sole surviving violation.
        agreement = st_agreement_for(spec["film"]["id"])
        st_issue_and_sign(agreement["id"], spec["submitter"]["id"])
        wrong_phase = api.hold_slot(slot["id"], entry["id"], OPS)
        validate_error(wrong_phase, ApiErrorId.ERR_EDITION_PHASE_FORBIDDEN.value)


class TestPremiereDiscipline:
    def test_temporal_gate_beats_format_constraint(self, api):
        """PRD §2.9: "Eighth, clock-based window rules run: intake timing, the
        slot's festival window, premiere-before-public ordering, ..." while
        "Eleventh, uniqueness, eligibility, and structural constraints run —
        ... format support"; §3.8: "a `PUBLIC` or `PRESS_INDUSTRY` hold is
        rejected with `ERR_PREMIERE_WINDOW_VIOLATION` unless a `PREMIERE`
        slot for the same entry exists ... starting earlier".

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_slot_hold
        """
        ctx = fx_scheduling(films=1, capacity_slots=1)
        entry = ctx["entries"][0]
        # Venue supports only DCP_4K while the film is DCP_2K; no PREMIERE
        # slot exists for the entry — both rules are violated.
        venue = st_venue(ctx, {"name": "Egyptian",
                               "formats_supported": ["DCP_4K"]})
        slot = st_slot(venue["id"], {"slot_type": "PUBLIC",
                                     "start_at": "2027-01-23T20:00:00Z",
                                     "end_at": "2027-01-23T21:00:00Z"})
        resp = api.hold_slot(slot["id"], entry["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_PREMIERE_WINDOW_VIOLATION.value)
        fresh = validate_success(api.get_screening_slot(slot["id"], OPS))
        assert fresh["status"] == "OPEN"
        assert fresh["slate_entry_id"] is None

    def test_format_gate_fires_once_premiere_precedence_satisfied(self, api):
        """PRD §3.8: "The film's `format` must appear in the venue's
        `formats_supported`, failing with `ERR_FORMAT_UNSUPPORTED`."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_slot_hold
        """
        ctx = fx_scheduling(films=1, capacity_slots=1)
        entry = ctx["entries"][0]
        venue_a = st_venue(ctx, {"name": "Eccles",
                                 "formats_supported": ["DCP_2K"]})
        premiere = st_slot(venue_a["id"], {"slot_type": "PREMIERE",
                                           "start_at": "2027-01-22T17:00:00Z",
                                           "end_at": "2027-01-22T18:00:00Z"})
        held = validate_success(api.hold_slot(premiere["id"], entry["id"], OPS))
        assert held["status"] == "HELD"

        venue_b = st_venue(ctx, {"name": "Retro",
                                 "formats_supported": ["FILM_35MM"]})
        public = st_slot(venue_b["id"], {"slot_type": "PUBLIC",
                                         "start_at": "2027-01-22T19:00:00Z",
                                         "end_at": "2027-01-22T20:00:00Z"})
        resp = api.hold_slot(public["id"], entry["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_FORMAT_UNSUPPORTED.value)

    def test_premiere_uniqueness_and_format_support(self, api):
        """PRD §3.8: "a `PREMIERE` hold is rejected with
        `ERR_PREMIERE_SLOT_EXISTS` when the entry already has a `PREMIERE`
        slot in `HELD`, `CONFIRMED`, or `PLAYED`" and "The film's `format`
        must appear in the venue's `formats_supported`, failing with
        `ERR_FORMAT_UNSUPPORTED`."

        Design: Corner/validations/premiere_uniqueness_and_format_support
        """
        ctx = fx_scheduling(films=1, capacity_slots=1,
                            agreement_over={"licensed_screening_count": 5})
        entry = ctx["entries"][0]
        venue_a = st_venue(ctx, {"name": "Eccles",
                                 "formats_supported": ["DCP_2K"]})
        slot1 = st_slot(venue_a["id"], {"slot_type": "PREMIERE",
                                        "start_at": "2027-01-22T17:00:00Z",
                                        "end_at": "2027-01-22T18:00:00Z"})
        slot2 = st_slot(venue_a["id"], {"slot_type": "PREMIERE",
                                        "start_at": "2027-01-22T21:00:00Z",
                                        "end_at": "2027-01-22T22:00:00Z"})
        venue_b = st_venue(ctx, {"name": "Retro",
                                 "formats_supported": ["FILM_35MM"]})
        slot3 = st_slot(venue_b["id"], {"slot_type": "PUBLIC",
                                        "start_at": "2027-01-22T19:00:00Z",
                                        "end_at": "2027-01-22T20:00:00Z"})

        first = validate_success(api.hold_slot(slot1["id"], entry["id"], OPS))
        assert first["status"] == "HELD"

        second_premiere = api.hold_slot(slot2["id"], entry["id"], OPS)
        validate_error(second_premiere, ApiErrorId.ERR_PREMIERE_SLOT_EXISTS.value)

        wrong_format = api.hold_slot(slot3["id"], entry["id"], OPS)
        validate_error(wrong_format, ApiErrorId.ERR_FORMAT_UNSUPPORTED.value)


class TestFilmFitAndLicense:
    def test_slot_fit_qa_minutes_boundary(self, api):
        """PRD §3.8: "the slot's duration must cover the film's
        `runtime_minutes` plus 15 minutes of audience Q&A, failing with
        `ERR_SLOT_TOO_SHORT`."

        Design: Corner/calculations/slot_fit_qa_minutes_boundary
        """
        ctx = fx_scheduling(films=1, capacity_slots=1)  # runtime 20
        entry = ctx["entries"][0]
        venue = st_venue(ctx)
        exact = st_slot(venue["id"], {"slot_type": "PREMIERE",
                                      "start_at": "2027-01-22T17:00:00Z",
                                      "end_at": "2027-01-22T17:35:00Z"})
        short = st_slot(venue["id"], {"slot_type": "PUBLIC",
                                      "start_at": "2027-01-22T19:00:00Z",
                                      "end_at": "2027-01-22T19:34:00Z"})

        held = validate_success(api.hold_slot(exact["id"], entry["id"], OPS))
        assert held["status"] == "HELD", "35 minutes exactly covers 20 + 15"

        # Premiere precedence is satisfied by the HELD premiere above; the
        # 34-minute PUBLIC slot fails the fit check.
        too_short = api.hold_slot(short["id"], entry["id"], OPS)
        validate_error(too_short, ApiErrorId.ERR_SLOT_TOO_SHORT.value)

    def test_licensed_count_exceeded_at_confirm(self, api):
        """PRD §3.8: "confirmation is rejected with
        `ERR_LICENSED_COUNT_EXCEEDED` when the agreement's
        `used_screening_count` plus one would exceed
        `licensed_screening_count`."

        Design: Corner/validations/licensed_count_exceeded_at_confirm
        """
        ctx = fx_scheduling(films=1, capacity_slots=1,
                            agreement_over={"licensed_screening_count": 1})
        entry = ctx["entries"][0]
        agreement = ctx["agreements"][0]
        venue = st_venue(ctx)
        slot1 = st_slot(venue["id"], {"slot_type": "PREMIERE",
                                      "start_at": "2027-01-22T17:00:00Z",
                                      "end_at": "2027-01-22T18:00:00Z"})
        slot2 = st_slot(venue["id"], {"slot_type": "PUBLIC",
                                      "start_at": "2027-01-22T19:00:00Z",
                                      "end_at": "2027-01-22T20:00:00Z"})

        validate_success(api.hold_slot(slot1["id"], entry["id"], OPS))
        confirmed = validate_success(api.confirm_slot(slot1["id"], OPS))
        assert confirmed["status"] == "CONFIRMED"

        validate_success(api.hold_slot(slot2["id"], entry["id"], OPS))
        over = api.confirm_slot(slot2["id"], OPS)
        validate_error(over, ApiErrorId.ERR_LICENSED_COUNT_EXCEEDED.value)

        agreement_after = validate_success(
            api.get_exhibition_agreement(agreement["id"], DIRECTOR)
        )
        assert agreement_after["used_screening_count"] == 1
        slot2_after = validate_success(api.get_screening_slot(slot2["id"], OPS))
        assert slot2_after["status"] == "HELD"


class TestHoldReleaseConfirmCycle:
    def _confirmed_setup(self, api):
        ctx = fx_scheduling(films=1, capacity_slots=1)
        venue = st_venue(ctx, {"name": "Eccles",
                               "formats_supported": ["DCP_2K", "DCP_4K"]})
        slot = st_slot(venue["id"], {"slot_type": "PREMIERE",
                                     "start_at": "2027-01-22T17:00:00Z",
                                     "end_at": "2027-01-22T18:00:00Z"})
        return ctx, venue, slot

    def test_hold_release_hold_confirm_cycle(self, api):
        """PRD §3.8: "A hold can be released, returning the slot `HELD` →
        `OPEN` and clearing its `slate_entry_id`; the hold–release cycle may
        repeat. Confirming a hold moves the slot `HELD` → `CONFIRMED` ...
        Each confirmation increments `used_screening_count`, flips a `SIGNED`
        agreement to `ACTIVE` on the first confirmation, and — on the first
        confirmed slot for the entry — moves the slate entry `CONFIRMED` →
        `PROGRAMMED`."

        Design: Difficulty/non_linear_state_machine/slot_hold_release_and_reverse_programmed_cycle
        """
        ctx, _venue, slot = self._confirmed_setup(api)
        entry = ctx["entries"][0]
        agreement = ctx["agreements"][0]

        held = validate_success(api.hold_slot(slot["id"], entry["id"], OPS))
        assert held["status"] == "HELD"

        released = validate_success(api.release_slot(slot["id"], OPS))
        assert released["status"] == "OPEN"
        assert released["slate_entry_id"] is None

        held_again = validate_success(api.hold_slot(slot["id"], entry["id"], OPS))
        assert held_again["status"] == "HELD"

        confirmed = validate_success(api.confirm_slot(slot["id"], OPS))
        assert confirmed["status"] == "CONFIRMED"

        agreement_after = validate_success(
            api.get_exhibition_agreement(agreement["id"], OPS)
        )
        assert agreement_after["used_screening_count"] == 1
        assert agreement_after["status"] == "ACTIVE"

        entry_after = validate_success(api.get_slate_entry(entry["id"], OPS))
        assert entry_after["status"] == "PROGRAMMED"

    def test_cancel_reverses_programmed_cycle(self, api):
        """PRD §3.8: "Cancelling a confirmed slot moves it `CONFIRMED` →
        `CANCELLED`, decrements `used_screening_count`, and, when the
        cancellation leaves the entry with zero `CONFIRMED` or `PLAYED`
        slots, reverses both the entry and the submission from `PROGRAMMED`
        back to `CONFIRMED`."

        Design: Difficulty/non_linear_state_machine/slot_hold_release_and_reverse_programmed_cycle
        """
        ctx, _venue, slot = self._confirmed_setup(api)
        entry = ctx["entries"][0]
        agreement = ctx["agreements"][0]
        validate_success(api.hold_slot(slot["id"], entry["id"], OPS))
        validate_success(api.confirm_slot(slot["id"], OPS))

        cancelled = validate_success(api.cancel_slot(slot["id"], OPS))
        assert cancelled["status"] == "CANCELLED"

        agreement_after = validate_success(
            api.get_exhibition_agreement(agreement["id"], OPS)
        )
        assert agreement_after["used_screening_count"] == 0

        entry_after = validate_success(api.get_slate_entry(entry["id"], OPS))
        assert entry_after["status"] == "CONFIRMED"
        film = validate_success(
            api.get_submission(ctx["films"][0]["film"]["id"], OPS)
        )
        assert film["status"] == "CONFIRMED"


class TestMarkPlayed:
    def test_mark_played_requires_festival_live(self, api):
        """PRD §3.8: "during `FESTIVAL_LIVE` a confirmed slot is marked
        played, moving `CONFIRMED` → `PLAYED`; marking at any other phase is
        rejected with `ERR_EDITION_PHASE_FORBIDDEN`."

        Design: Corner/validations/mark_played_requires_festival_live
        """
        ctx = fx_programmed(films=1, capacity_slots=1)
        slot = ctx["slots"][0]

        too_early = api.mark_slot_played(slot["id"], OPS)
        validate_error(too_early, ApiErrorId.ERR_EDITION_PHASE_FORBIDDEN.value)

        set_clock("2027-01-21T00:00:00Z")
        st_advance(ctx, "FESTIVAL_LIVE")
        played = validate_success(api.mark_slot_played(slot["id"], OPS))
        assert played["status"] == "PLAYED"


class TestWithdrawalUnwind:
    def _programmed_with_waitlist(self, api):
        """Film 0 PROGRAMMED with a CONFIRMED premiere slot; film 1
        WAITLISTED as the rank-2 entry of the same capacity-1 slate."""
        ctx = fx_scheduling(films=[
            {"title": "Main Film", "scores": [("STAFF", 8), ("STAFF", 9)]},
            {"title": "Wait Film", "scores": [("STAFF", 8), ("STAFF", 8)]},
        ], capacity_slots=1)
        venue = st_venue(ctx, {"formats_supported": ["DCP_2K"]})
        slot = st_slot(venue["id"], {"slot_type": "PREMIERE",
                                     "start_at": "2027-01-22T17:00:00Z",
                                     "end_at": "2027-01-22T18:00:00Z"})
        validate_success(api.hold_slot(slot["id"], ctx["entries"][0]["id"], OPS))
        ctx["slot_m"] = validate_success(api.confirm_slot(slot["id"], OPS))
        return ctx

    def test_withdraw_unwinds_slot_agreement_and_entry(self, api):
        """PRD §3.2: on withdrawal, "Every slot held for the entry returns to
        `OPEN` with its `slate_entry_id` cleared, and every confirmed slot is
        cancelled with the agreement's `used_screening_count` decremented
        once per cancelled slot" and "that entry is dropped to `DROPPED` and
        the waitlist-promotion cascade of §3.6 fires".

        Design: Difficulty/transitive_cascade/withdrawal_unwinds_slots_and_promotes
        """
        ctx = self._programmed_with_waitlist(api)
        main = ctx["films"][0]
        entry_m = ctx["entries"][0]
        agreement = ctx["agreements"][0]

        withdrawn = validate_success(api.withdraw_submission(
            main["film"]["id"], make_filmmaker_headers(main["submitter"]["id"]),
        ))
        assert withdrawn["status"] == "WITHDRAWN"

        slot_after = validate_success(
            api.get_screening_slot(ctx["slot_m"]["id"], OPS)
        )
        assert slot_after["status"] == "CANCELLED"

        agreement_after = validate_success(
            api.get_exhibition_agreement(agreement["id"], DIRECTOR)
        )
        assert agreement_after["used_screening_count"] == 0

        entry_after = validate_success(api.get_slate_entry(entry_m["id"], DIRECTOR))
        assert entry_after["status"] == "DROPPED"

    def test_withdraw_promotes_waitlist_without_refund(self, api):
        """PRD §3.2: the auto-refund applies only when "no screening slot
        ever reached `HELD`, `CONFIRMED`, or `PLAYED` for the film's slate
        entry"; here a CONFIRMED slot existed, so the payment stays `PAID`,
        while §3.6's promotion cascade "promotes it to lane `MAIN` and status
        `INVITED` ... and moves its film `WAITLISTED` → `INVITED`."

        Design: Difficulty/transitive_cascade/withdrawal_unwinds_slots_and_promotes
        """
        ctx = self._programmed_with_waitlist(api)
        main, wait = ctx["films"][0], ctx["films"][1]
        payment_m = ctx["payments"][main["film"]["id"]]
        entry_w = ctx["entries"][1]

        withdrawn = validate_success(api.withdraw_submission(
            main["film"]["id"], make_filmmaker_headers(main["submitter"]["id"]),
        ))
        assert withdrawn["payment_status"] == "PAID"

        payment_after = validate_success(
            api.get_fee_payment(payment_m["id"], ADMIN)
        )
        assert payment_after["status"] == "SUCCEEDED"
        assert payment_after["refunded_amount_cents"] == 0

        promoted = validate_success(api.get_slate_entry(entry_w["id"], DIRECTOR))
        assert promoted["lane"] == "MAIN"
        assert promoted["status"] == "INVITED"
        film_w = validate_success(api.get_submission(wait["film"]["id"], ADMIN))
        assert film_w["status"] == "INVITED"
