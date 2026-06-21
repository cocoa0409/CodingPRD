"""Corner — validations section.

Single-violation-to-error claims (one violation, the expected error_id).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    set_clock,
    create_chapter,
    create_round,
    register_pnm,
    register_and_activate_pnm,
    create_party,
    create_and_open_party,
    create_invitation,
    accept_invitation,
    complete_party,
    advance_round,
    file_pnm_preference,
    create_invitation_payload,
    create_party_payload,
    create_preference_payload,
    register_pnm_payload,
    make_chapter_officer_headers,
    make_pnm_headers,
    ApiErrorId,
    TEST_USERS,
)


class TestPnmActivateBelowMinGpa:
    """PNM.gpa=2.49 at activation fires ERR_GPA_BELOW_MINIMUM (422), distinct
    from ERR_INVALID_REQUEST (400) which catches out-of-range input."""

    def test_activate_pnm_with_gpa_2_49_returns_gpa_below_minimum(self, api):
        """PRD §3.1: "Activation by the `RecruitmentChair` advances `status` from `REGISTERED` to `ACTIVE`, but only if the PNM's `gpa` is at least 2.50 — a `gpa` strictly below 2.50 is rejected with `ERR_GPA_BELOW_MINIMUM` (HTTP 422), not the generic not-found code, because the row does exist."

        Design: Corner/validations/corner_pnm_activate_below_min_gpa
        """
        pnm = register_pnm(full_name="LowGpa", gpa=2.49)
        res = api.activate_pnm(pnm["id"], TEST_USERS["recruitment_chair_headers"])
        validate_error(res, ApiErrorId.ERR_GPA_BELOW_MINIMUM)
        # PNM should still be REGISTERED.
        pnm_after = validate_success(
            api.get_pnm(pnm["id"], TEST_USERS["panhellenic_admin_headers"]),
            200,
        )
        assert pnm_after["status"] == "REGISTERED"


class TestDuplicateInvitationRejected:
    """A second invitation for the same (party_id, pnm_id) returns
    ERR_DUPLICATE_INVITATION."""

    def test_duplicate_invitation_returns_duplicate_invitation(self, api):
        """PRD §3.3: "Two preconditions guard creation: the targeted PNM's `status` must be `ACTIVE` at the time the invitation is created, and the pair `(party_id, pnm_id)` must not already exist — a duplicate is rejected with `ERR_DUPLICATE_INVITATION`."

        Design: Corner/validations/corner_duplicate_invitation_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        ch = create_chapter(
            name="DupInv",
            greek_type="SORORITY",
            quota_total=3,
            dues_per_member_cents=10000,
            legacy_priority_slots=0,
        )
        rnd = create_round(cycle_label="Fall 2026 dup")
        pnm = register_and_activate_pnm(full_name="DupP", gpa=3.50)
        party = create_party(
            rnd["id"], ch["id"], scheduled_start_utc="2026-09-05T18:00:00Z"
        )
        # First invitation succeeds.
        first = validate_success(
            api.create_invitation(
                create_invitation_payload(party["id"], pnm["id"]),
                make_chapter_officer_headers(ch["id"]),
            ),
            201,
        )
        # Trigger: second invitation with same (party_id, pnm_id).
        res = api.create_invitation(
            create_invitation_payload(party["id"], pnm["id"]),
            make_chapter_officer_headers(ch["id"]),
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_INVITATION)


class TestChapterDoubleBookOverlapRejected:
    """Same-chapter overlapping party returns ERR_CHAPTER_DOUBLE_BOOK at
    priority 9 (distinct from priority 8's PNM ACCEPT conflict)."""

    def test_overlapping_same_chapter_party_returns_double_book(self, api):
        """PRD §3.2: "In addition, the system runs a same-chapter double-booking check: the half-open interval from `scheduled_start_utc` (inclusive) to `scheduled_start_utc` plus `duration_minutes` (exclusive) must not overlap any other party hosted by the same chapter. Adjacent parties — those whose intervals abut at exactly zero gap — are allowed; any positive overlap is rejected with `ERR_CHAPTER_DOUBLE_BOOK`."

        Design: Corner/validations/corner_chapter_double_book_overlap_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        ch = create_chapter(
            name="DblBook",
            greek_type="SORORITY",
            quota_total=3,
            dues_per_member_cents=10000,
            legacy_priority_slots=0,
        )
        rnd = create_round(cycle_label="Fall 2026 db")
        create_party(
            rnd["id"],
            ch["id"],
            scheduled_start_utc="2026-09-05T18:00:00Z",
            duration_minutes=60,
        )
        # Trigger: overlapping party at 18:30 (overlaps [18:00,19:00))
        res = api.create_party(
            create_party_payload(
                round_id=rnd["id"],
                chapter_id=ch["id"],
                scheduled_start_utc="2026-09-05T18:30:00Z",
                duration_minutes=60,
                capacity=10,
            ),
            make_chapter_officer_headers(ch["id"]),
        )
        validate_error(res, ApiErrorId.ERR_CHAPTER_DOUBLE_BOOK)


class TestPreferenceRankTakenReturnsConflict:
    """A PNM filing two PNM_TO_CHAPTER preferences both at rank=1 in the same
    round is rejected — (round_id, side, ranker, rank) uniqueness."""

    def test_duplicate_pnm_rank_in_same_round_returns_rank_taken(self, api):
        """PRD §3.4: "Each row is unique on the tuple `(round_id, side, ranker, rank)`. The ranker is the `pnm_id` when `side` is `PNM_TO_CHAPTER` and the `chapter_id` when `side` is `CHAPTER_TO_PNM`, so a single PNM cannot file two `rank` 1 picks against two different chapters in the same round, and a single chapter cannot rank two different PNMs as its `rank` 1. A duplicate-rank attempt is rejected with `ERR_PREFERENCE_RANK_TAKEN`."

        Design: Corner/validations/corner_preference_rank_taken_returns_conflict
        """
        set_clock("2026-09-01T00:00:00Z")
        ca = create_chapter(
            name="PA",
            greek_type="SORORITY",
            quota_total=3,
            dues_per_member_cents=10000,
            legacy_priority_slots=0,
        )
        cb = create_chapter(
            name="PB",
            greek_type="SORORITY",
            quota_total=3,
            dues_per_member_cents=10000,
            legacy_priority_slots=0,
        )
        rnd = create_round(cycle_label="Fall 2026 prt")
        pnm = register_and_activate_pnm(full_name="RP", gpa=3.50)
        # Both chapters host a party with the PNM ATTENDED so PNM eligibility holds.
        pa = create_and_open_party(
            rnd["id"], ca["id"], scheduled_start_utc="2026-09-05T18:00:00Z"
        )
        pb = create_and_open_party(
            rnd["id"], cb["id"], scheduled_start_utc="2026-09-06T18:00:00Z"
        )
        ia = create_invitation(pa["id"], pnm["id"], ca["id"])
        ib = create_invitation(pb["id"], pnm["id"], cb["id"])
        accept_invitation(ia["id"], pnm["id"])
        accept_invitation(ib["id"], pnm["id"])
        complete_party(pa["id"], ca["id"])
        complete_party(pb["id"], cb["id"])
        advance_round(rnd["id"])  # PARTY -> MUTUAL_SELECTION
        # First PNM_TO_CHAPTER rank=1 toward CA — succeeds.
        file_pnm_preference(rnd["id"], pnm["id"], ca["id"], rank=1)
        # Trigger: same PNM, same rank=1, different chapter (CB).
        res = api.create_preference(
            create_preference_payload(
                round_id=rnd["id"],
                side="PNM_TO_CHAPTER",
                pnm_id=pnm["id"],
                chapter_id=cb["id"],
                rank=1,
            ),
            make_pnm_headers(pnm["id"]),
        )
        validate_error(res, ApiErrorId.ERR_PREFERENCE_RANK_TAKEN)
