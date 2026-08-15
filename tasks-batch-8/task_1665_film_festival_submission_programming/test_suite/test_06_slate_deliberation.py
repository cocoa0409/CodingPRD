"""Slate construction: sections, entries, lock gates, reopen cycle, and the
entry-add OCC guard (PRD §2.7, §3.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    build_user_headers,
    fx_screening,
    make_filmmaker_headers,
    st_add_entry, st_advance, st_deliberate, st_edition, st_film,
    st_issue_invitations, st_lock, st_rule, st_slate, st_submitter,
    validate_error, validate_success,
    TEST_USERS,
)

CHAIR = TEST_USERS["chair_headers"]
DIRECTOR = TEST_USERS["director_headers"]


class TestSlateCreation:
    def test_duplicate_slate_section_rejected(self, api):
        """PRD §3.5: "One slate per section per edition: a duplicate section
        for the same edition is rejected with `ERR_DUPLICATE_SLATE`."

        Design: Corner/validations/duplicate_slate_section_rejected
        """
        ctx = st_edition(with_config=False)
        first = st_slate(ctx, section="SHORTS", capacity_slots=2)
        assert first["status"] == "OPEN"

        dup = api.create_slate(
            {"edition_id": ctx["edition"]["id"], "section": "SHORTS",
             "capacity_slots": 3},
            CHAIR,
        )
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_SLATE.value)

        other = validate_success(api.create_slate(
            {"edition_id": ctx["edition"]["id"], "section": "NEXT",
             "capacity_slots": 3},
            CHAIR,
        ), 201)
        assert other["section"] == "NEXT"


class TestEntryAdd:
    def test_section_category_mismatch_and_duplicate_entry(self, api):
        """PRD §3.5: "Section–category mapping confines `SHORT_FILM`
        submissions to `SHORTS` slates ... with mismatches rejected as
        `ERR_SECTION_CATEGORY_MISMATCH`; and a submission that already holds a
        non-`DROPPED` entry on the same slate is rejected with
        `ERR_DUPLICATE_ENTRY`."

        Design: Corner/validations/section_category_mismatch_and_duplicate_entry
        """
        ctx = fx_screening(films=[{"title": "Mismatch"}])
        st_advance(ctx, "DELIBERATION")
        film_id = ctx["films"][0]["film"]["id"]

        slate_d = st_slate(ctx, section="US_DRAMATIC", capacity_slots=1)
        st_deliberate(slate_d["id"])
        slate_s = st_slate(ctx, section="SHORTS", capacity_slots=1)
        st_deliberate(slate_s["id"])

        slate_now = validate_success(api.get_slate(slate_d["id"], CHAIR))
        mismatch = api.add_slate_entry(
            slate_d["id"],
            {"submission_id": film_id,
             "expected_slate_version": slate_now["version"]},
            CHAIR,
        )
        validate_error(mismatch, ApiErrorId.ERR_SECTION_CATEGORY_MISMATCH.value)

        entry = st_add_entry(slate_s["id"], film_id)
        assert entry["status"] == "NOMINATED"

        slate_now = validate_success(api.get_slate(slate_s["id"], CHAIR))
        duplicate = api.add_slate_entry(
            slate_s["id"],
            {"submission_id": film_id,
             "expected_slate_version": slate_now["version"]},
            CHAIR,
        )
        validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_ENTRY.value)

    def test_entry_add_in_screening_submission_accepted(self, api):
        """PRD §3.5: "A film must be `IN_SCREENING` to be nominated; the add
        moves it `IN_SCREENING` → `ADVANCED`. The new entry is born
        `NOMINATED` in lane `UNASSIGNED`."

        Design: Difficulty/cross_entity_state_dependency/entry_add_requires_in_screening_submission
        """
        ctx = fx_screening(films=[{"title": "Film Y"}])
        st_advance(ctx, "DELIBERATION")
        film_id = ctx["films"][0]["film"]["id"]
        slate = st_slate(ctx, section="SHORTS", capacity_slots=2)
        st_deliberate(slate["id"])

        entry = st_add_entry(slate["id"], film_id)
        assert entry["status"] == "NOMINATED"
        film = validate_success(api.get_submission(film_id, TEST_USERS["admin_headers"]))
        assert film["status"] == "ADVANCED"

    def test_entry_add_assigns_rank_and_stamps_slate(self, api):
        """PRD §3.5: "The new entry is born `NOMINATED` in lane `UNASSIGNED`,
        takes a `rank_position` one above the slate's current maximum, and
        stamps the slate's `last_entry_added_by` with the caller's
        `X-User-ID`; the slate's `version` increments on every add."

        Design: Difficulty/cross_entity_state_dependency/entry_add_requires_in_screening_submission
        """
        ctx = fx_screening(films=[{"title": "Film Y"}])
        st_advance(ctx, "DELIBERATION")
        film_id = ctx["films"][0]["film"]["id"]
        slate = st_slate(ctx, section="SHORTS", capacity_slots=2)
        st_deliberate(slate["id"])
        before = validate_success(api.get_slate(slate["id"], CHAIR))

        entry = st_add_entry(slate["id"], film_id)
        assert entry["lane"] == "UNASSIGNED"
        assert entry["rank_position"] == 1
        assert entry["slate_id"] == slate["id"]

        after = validate_success(api.get_slate(slate["id"], CHAIR))
        assert after["version"] == before["version"] + 1
        assert after["last_entry_added_by"] == "chair-1"
        assert after["entry_count"] == 1


class TestSlateLockGates:
    def test_slate_lock_underfilled_and_below_threshold(self, api):
        """PRD §3.5: "The underfill gate requires `entry_count` to be at least
        `capacity_slots`, failing with `ERR_SLATE_UNDERFILLED`. The threshold
        gate requires every entry whose `rank_position` is at or below
        `capacity_slots` — the future main lane — to have a non-null
        `composite_score` of at least 7.500 ... any shortfall is rejected with
        `ERR_BELOW_SLATE_THRESHOLD`."

        Design: Corner/validations/slate_lock_underfilled_and_below_threshold
        """
        ctx = fx_screening(films=[
            {"title": "Strong"},  # composite (8+9)/2 = 8.5
            {"title": "Weak", "scores": [("STAFF", 7), ("STAFF", 7)]},  # 7.0
        ])
        st_advance(ctx, "DELIBERATION")

        # One SHORTS slate (PRD §3.5 confines SHORT_FILM to SHORTS) with
        # capacity 2: the first lock is underfilled; after the weak film is
        # added the count clears and the threshold gate fires instead.
        slate = st_slate(ctx, section="SHORTS", capacity_slots=2)
        st_deliberate(slate["id"])
        st_add_entry(slate["id"], ctx["films"][0]["film"]["id"])
        underfilled = api.lock_slate(slate["id"], DIRECTOR)  # dir != chair
        validate_error(underfilled, ApiErrorId.ERR_SLATE_UNDERFILLED.value)

        st_add_entry(slate["id"], ctx["films"][1]["film"]["id"])
        below = api.lock_slate(slate["id"], DIRECTOR)
        validate_error(below, ApiErrorId.ERR_BELOW_SLATE_THRESHOLD.value)

    def test_lock_at_exactly_7500_succeeds(self, api):
        """PRD §3.5: the threshold gate requires "a non-null `composite_score`
        of at least 7.500, compared at its stored three-decimal precision so
        that exactly 7.500 passes"; a successful lock "assigns lanes —
        entries at or below `capacity_slots` become `MAIN`".

        Design: Difficulty/boundary_precision_check/slate_threshold_exactly_7500
        """
        ctx = fx_screening(films=[
            {"title": "Threshold", "scores": [("STAFF", 7), ("STAFF", 8)]},
        ])
        film_id = ctx["films"][0]["film"]["id"]
        film = validate_success(api.get_submission(film_id, TEST_USERS["admin_headers"]))
        assert film["composite_score"] == pytest.approx(7.5, abs=1e-9)

        st_advance(ctx, "DELIBERATION")
        slate = st_slate(ctx, section="SHORTS", capacity_slots=1)
        st_deliberate(slate["id"])
        entry = st_add_entry(slate["id"], film_id)

        locked = validate_success(api.lock_slate(slate["id"], DIRECTOR))
        assert locked["status"] == "LOCKED"
        entry_after = validate_success(api.get_slate_entry(entry["id"], DIRECTOR))
        assert entry_after["lane"] == "MAIN"

    def test_lock_at_7500_snapshots_score_and_timestamp(self, api):
        """PRD §3.5: "A successful lock ... snapshots each entry's
        `composite_score` into `locked_composite_score`, and stamps
        `locked_at` with the logical clock."

        Design: Difficulty/boundary_precision_check/slate_threshold_exactly_7500
        """
        ctx = fx_screening(films=[
            {"title": "Threshold", "scores": [("STAFF", 7), ("STAFF", 8)]},
        ])
        film_id = ctx["films"][0]["film"]["id"]
        st_advance(ctx, "DELIBERATION")
        slate = st_slate(ctx, section="SHORTS", capacity_slots=1)
        st_deliberate(slate["id"])
        entry = st_add_entry(slate["id"], film_id)

        locked = validate_success(api.lock_slate(slate["id"], DIRECTOR))
        assert locked["locked_at"], "locked_at must be stamped"

        entry_after = validate_success(api.get_slate_entry(entry["id"], DIRECTOR))
        assert entry_after["locked_composite_score"] == pytest.approx(7.5, abs=1e-9)


class TestSegregationPriority:
    def _underfilled_conflict_slate(self, api):
        """Edition DELIBERATION; cap-2 slate with exactly one entry added by
        chair-1 (composite 7.5, sufficient)."""
        ctx = fx_screening(films=[
            {"title": "Slate Lock", "scores": [("STAFF", 7), ("STAFF", 8)]},
        ])
        st_advance(ctx, "DELIBERATION")
        slate = st_slate(ctx, section="SHORTS", capacity_slots=2)
        st_deliberate(slate["id"])
        st_add_entry(slate["id"], ctx["films"][0]["film"]["id"])
        return ctx, slate

    def test_segregation_fires_before_underfill(self, api):
        """PRD §3.5: "three gates stand in front of the lock, evaluated in the
        precedence order of §2.9 — segregation first, then underfill, then the
        score threshold. The segregation-of-duties gate fires when the slate
        holds at least one entry and the director's `X-User-ID` equals the
        slate's `last_entry_added_by`, rejected with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_slate_lock
        """
        _ctx, slate = self._underfilled_conflict_slate(api)
        # Locker's X-User-ID equals the adder's (chair-1); underfill also true.
        resp = api.lock_slate(
            slate["id"], build_user_headers("chair-1", "FESTIVAL_DIRECTOR"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
        slate_after = validate_success(api.get_slate(slate["id"], DIRECTOR))
        assert slate_after["status"] == "DELIBERATING"

    def test_underfill_fires_once_segregation_satisfied(self, api):
        """PRD §3.5: with a different director the segregation gate passes and
        the underfill gate runs — "The underfill gate requires `entry_count`
        to be at least `capacity_slots`, failing with
        `ERR_SLATE_UNDERFILLED`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_slate_lock
        """
        _ctx, slate = self._underfilled_conflict_slate(api)
        resp = api.lock_slate(slate["id"], DIRECTOR)  # dir-1 != chair-1
        validate_error(resp, ApiErrorId.ERR_SLATE_UNDERFILLED.value)
        slate_after = validate_success(api.get_slate(slate["id"], DIRECTOR))
        assert slate_after["status"] == "DELIBERATING"


class TestSlateReopenCycle:
    def test_reopen_cycle_then_locked_down_after_invitations(self, api):
        """PRD §3.5: "before any invitation has been issued, the director may
        reopen a slate, but only while every entry is still `NOMINATED` — any
        entry that has progressed further fails the reopen with
        `ERR_INVALID_STATE`. Reopening returns the slate to `DELIBERATING`,
        resets every entry's lane to `UNASSIGNED`, and clears every
        `locked_composite_score`."

        Design: Corner/state_machines/slate_reopen_cycle_then_locked_down_after_invitations
        """
        ctx = fx_screening(films=[{"title": "Reopen"}])
        st_advance(ctx, "DELIBERATION")
        slate = st_slate(ctx, section="SHORTS", capacity_slots=1)
        st_deliberate(slate["id"])
        entry = st_add_entry(slate["id"], ctx["films"][0]["film"]["id"])
        st_lock(slate["id"])

        reopened = validate_success(api.reopen_slate(slate["id"], DIRECTOR))
        assert reopened["status"] == "DELIBERATING"
        entry_after = validate_success(api.get_slate_entry(entry["id"], DIRECTOR))
        assert entry_after["lane"] == "UNASSIGNED"
        assert entry_after["locked_composite_score"] is None

        # Re-lock (director dir-1 != adder chair-1), advance, and issue.
        st_lock(slate["id"])
        st_advance(ctx, "SLATE_LOCKED")
        st_advance(ctx, "NOTIFICATION")
        st_issue_invitations(ctx)

        blocked = api.reopen_slate(slate["id"], DIRECTOR)
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE.value)


class TestEntryAddOcc:
    def test_occ_stale_slate_entry_add(self, api):
        """PRD §2.7: "Adding an entry to a slate — `POST
        /festival/slates/{id}/entries` — requires `expected_slate_version`
        carrying the slate's last observed `version`" and the endpoint
        "rejects the request with `ERR_STALE_VERSION` (HTTP 412) when the
        supplied value does not match the parent entity's current `version`."

        Design: Corner/cross_cutting_layers/occ_stale_slate_entry_add
        """
        ctx = fx_screening(films=[{"title": "Film Y"}, {"title": "Film Z"}])
        st_advance(ctx, "DELIBERATION")
        slate = st_slate(ctx, section="SHORTS", capacity_slots=2)
        st_deliberate(slate["id"])
        observed = validate_success(api.get_slate(slate["id"], CHAIR))
        stale_version = observed["version"]

        first = validate_success(api.add_slate_entry(
            slate["id"],
            {"submission_id": ctx["films"][0]["film"]["id"],
             "expected_slate_version": stale_version},
            CHAIR,
        ), 201)
        assert first["rank_position"] == 1

        replay = api.add_slate_entry(
            slate["id"],
            {"submission_id": ctx["films"][1]["film"]["id"],
             "expected_slate_version": stale_version},
            CHAIR,
        )
        validate_error(replay, ApiErrorId.ERR_STALE_VERSION.value)

        entries = validate_success(
            api.list_entries_of_slate(slate["id"], CHAIR)
        )
        assert [e["submission_id"] for e in entries] == [
            ctx["films"][0]["film"]["id"]
        ], "the stale add must not have landed"
