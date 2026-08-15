"""Nomination guards: athletics-conflict overlap semantics (half-open
intervals, overlapping sets, cancelled blocks) and the chapter freeze guard's
position ahead of every business rule."""
from test_helpers import (
    ApiErrorId,
    add_athletics_block,
    add_member,
    api_client,
    create_active_chapter,
    create_cycle,
    create_service_entry_payload,
    list_applications,
    open_cycle_nominations,
    set_clock,
    suspend_chapter,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADVISOR = TEST_USERS["advisor_headers"]


def _nomination_env(with_block=None):
    """Active chapter + one GPA-passing prospective member + cycle in
    NOMINATION; optionally pre-register athletics blocks for the member."""
    set_clock()
    chapter = create_active_chapter()
    member = add_member(chapter["id"])
    blocks = []
    for spec in (with_block or []):
        blocks.append(add_athletics_block(chapter["id"], member["id"], **spec))
    cycle = create_cycle(chapter["id"])
    open_cycle_nominations(chapter["id"], cycle["id"])
    return chapter, member, cycle, blocks


class TestNominationBlockedByAthleticsBlock:
    def test_nominate_with_overlapping_block_rejected(self):
        """PRD section 3.2: "then the scheduling check — the student must have
        no `ACTIVE` athletics calendar block overlapping the cycle's
        `induction_date`, or the nomination is rejected with
        `ERR_ATHLETICS_CONFLICT` (HTTP 409)".
        PRD section 3.2: "A successful nomination advances the member from
        `PROSPECTIVE` to `CANDIDATE` and, in the same act, creates a
        `CycleApplication` under the current cycle in `SUBMITTED` status,
        recording the applying student as `member_id` and the nominating
        advisor's identity as `nominated_by_user_id`."

        Design: Difficulty/cross_entity_state_dependency/nomination_blocked_by_athletics_block
        """
        chapter, member, cycle, _blocks = _nomination_env(with_block=[{
            "block_start": "2026-08-30T00:00:00Z",
            "block_end": "2026-09-05T00:00:00Z",
            "priority": "GAME",
        }])
        resp = api_client.nominate_member(chapter["id"], member["id"], ADVISOR)
        validate_error(resp, ApiErrorId.ERR_ATHLETICS_CONFLICT)
        member_after = validate_success(
            api_client.get_member(chapter["id"], member["id"], ADVISOR))
        assert member_after["status"] == "PROSPECTIVE"
        applications = list_applications(chapter["id"], cycle["id"])
        assert applications == [], "no CycleApplication may be created"

    def test_nominate_with_cancelled_block_succeeds(self):
        """PRD section 3.8: "In every case the check consults only `ACTIVE`
        blocks — a `CANCELLED` block commits nobody."
        PRD section 3.2: "A successful nomination advances the member from
        `PROSPECTIVE` to `CANDIDATE` and, in the same act, creates a
        `CycleApplication` under the current cycle in `SUBMITTED` status,
        recording the applying student as `member_id` and the nominating
        advisor's identity as `nominated_by_user_id`."

        Design: Difficulty/cross_entity_state_dependency/nomination_blocked_by_athletics_block
        """
        chapter, member, cycle, blocks = _nomination_env(with_block=[{
            "block_start": "2026-08-30T00:00:00Z",
            "block_end": "2026-09-05T00:00:00Z",
            "priority": "GAME",
        }])
        resp = api_client.cancel_athletics_block(chapter["id"], blocks[0]["id"],
                                                 ADVISOR)
        validate_success(resp)
        resp = api_client.nominate_member(chapter["id"], member["id"], ADVISOR)
        data = validate_success(resp)
        assert data["status"] == "CANDIDATE"
        applications = list_applications(chapter["id"], cycle["id"])
        assert len(applications) == 1
        assert applications[0]["member_id"] == member["id"]
        assert applications[0]["status"] == "SUBMITTED"


class TestAthleticsBlockIntervalSemantics:
    def test_adjacent_blocks_induction_inside_second_conflicts(self):
        """PRD section 3.8: "A member has an athletics conflict with a given
        date when an `ACTIVE` block of theirs covers that date: the block's
        start falls on or before the date and its end falls strictly after
        it."
        PRD section 3.2: "the student must have no `ACTIVE` athletics calendar
        block overlapping the cycle's `induction_date`, or the nomination is
        rejected with `ERR_ATHLETICS_CONFLICT` (HTTP 409)".

        Design: Difficulty/resource_temporal_overlap/athletics_block_adjacent_intervals_no_conflict
        """
        # Block1 [08-30, 09-01) ends exactly at the induction date and so does
        # not cover it; Block2 [09-01, 09-05) covers 2026-09-01T00:00.
        chapter, member, _cycle, _blocks = _nomination_env(with_block=[
            {"block_start": "2026-08-30T00:00:00Z",
             "block_end": "2026-09-01T00:00:00Z", "priority": "PRACTICE"},
            {"block_start": "2026-09-01T00:00:00Z",
             "block_end": "2026-09-05T00:00:00Z", "priority": "GAME"},
        ])
        resp = api_client.nominate_member(chapter["id"], member["id"], ADVISOR)
        validate_error(resp, ApiErrorId.ERR_ATHLETICS_CONFLICT)

    def test_block_ending_exactly_at_induction_date_does_not_conflict(self):
        """PRD section 3.8: "Blocks are half-open intervals. A block covers the
        instant of its `block_start` and every instant up to but not including
        its `block_end`; consequently two intervals conflict exactly when each
        begins before the other ends, and two blocks that merely touch — one
        ending at the precise instant the other begins — do not conflict."

        Design: Difficulty/resource_temporal_overlap/athletics_block_adjacent_intervals_no_conflict
        """
        # Sole block [08-30, 09-01): the induction date 2026-09-01T00:00 equals
        # block_end, and the end must fall strictly after the date to cover it.
        chapter, member, _cycle, _blocks = _nomination_env(with_block=[{
            "block_start": "2026-08-30T00:00:00Z",
            "block_end": "2026-09-01T00:00:00Z",
            "priority": "PRACTICE",
        }])
        resp = api_client.nominate_member(chapter["id"], member["id"], ADVISOR)
        data = validate_success(resp)
        assert data["status"] == "CANDIDATE"


class TestAthleticsOverlappingSet:
    def test_multiple_overlapping_blocks_reject_nomination(self):
        """PRD section 3.8: "When several `ACTIVE` blocks cover the same date,
        the highest-priority block governs: `TOURNAMENT` outranks `GAME`,
        which outranks `PRACTICE`."
        PRD section 3.2: "the student must have no `ACTIVE` athletics calendar
        block overlapping the cycle's `induction_date`, or the nomination is
        rejected with `ERR_ATHLETICS_CONFLICT` (HTTP 409)".

        Design: Difficulty/resource_temporal_overlap/athletics_block_priority_overrides_on_conflict
        """
        chapter, member, _cycle, _blocks = _nomination_env(with_block=[
            {"block_start": "2026-08-28T00:00:00Z",
             "block_end": "2026-09-05T00:00:00Z", "priority": "PRACTICE"},
            {"block_start": "2026-08-30T00:00:00Z",
             "block_end": "2026-09-03T00:00:00Z", "priority": "GAME"},
            {"block_start": "2026-09-01T00:00:00Z",
             "block_end": "2026-09-02T00:00:00Z", "priority": "TOURNAMENT"},
        ])
        resp = api_client.nominate_member(chapter["id"], member["id"], ADVISOR)
        validate_error(resp, ApiErrorId.ERR_ATHLETICS_CONFLICT)
        member_after = validate_success(
            api_client.get_member(chapter["id"], member["id"], ADVISOR))
        assert member_after["status"] == "PROSPECTIVE"

    def test_cancelling_all_overlapping_blocks_clears_the_conflict(self):
        """PRD section 3.8: "In every case the check consults only `ACTIVE`
        blocks — a `CANCELLED` block commits nobody."

        Design: Difficulty/resource_temporal_overlap/athletics_block_priority_overrides_on_conflict
        """
        chapter, member, _cycle, blocks = _nomination_env(with_block=[
            {"block_start": "2026-08-28T00:00:00Z",
             "block_end": "2026-09-05T00:00:00Z", "priority": "PRACTICE"},
            {"block_start": "2026-08-30T00:00:00Z",
             "block_end": "2026-09-03T00:00:00Z", "priority": "GAME"},
            {"block_start": "2026-09-01T00:00:00Z",
             "block_end": "2026-09-02T00:00:00Z", "priority": "TOURNAMENT"},
        ])
        for b in blocks:
            validate_success(
                api_client.cancel_athletics_block(chapter["id"], b["id"],
                                                  ADVISOR))
        resp = api_client.nominate_member(chapter["id"], member["id"], ADVISOR)
        data = validate_success(resp)
        assert data["status"] == "CANDIDATE"


class TestFreezeGuardPrecedence:
    def test_frozen_chapter_reports_freeze_not_athletics_conflict(self):
        """PRD section 2.7: "While a chapter is `SUSPENDED` or `DISSOLVED`,
        every mutating request nested under that chapter — any create or action
        endpoint below the chapter's path — is rejected with
        `ERR_CHAPTER_FROZEN` (HTTP 409)."
        PRD section 2.7: "The freeze guard is evaluated before any
        state-machine or business rule, per the validation order in §2.6."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_nominate
        """
        chapter, member, _cycle, _blocks = _nomination_env(with_block=[{
            "block_start": "2026-08-30T00:00:00Z",
            "block_end": "2026-09-05T00:00:00Z",
            "priority": "TOURNAMENT",
        }])
        suspend_chapter(chapter["id"])
        resp = api_client.nominate_member(chapter["id"], member["id"], ADVISOR)
        validate_error(resp, ApiErrorId.ERR_CHAPTER_FROZEN)

    def test_frozen_chapter_blocks_service_entry_creation(self):
        """PRD section 2.7: "Suspension freezes the member-facing surface in a
        specific, enumerated way: no new `ServiceHourEntry`,
        `FundraiserRequest`, `OfficerElection`, or `CycleApplication` may be
        created while the freeze holds."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_nominate
        """
        set_clock()
        chapter = create_active_chapter()
        member = add_member(chapter["id"])
        suspend_chapter(chapter["id"])
        resp = api_client.create_service_entry(
            chapter["id"], member["id"], create_service_entry_payload(),
            ADVISOR)
        validate_error(resp, ApiErrorId.ERR_CHAPTER_FROZEN)
