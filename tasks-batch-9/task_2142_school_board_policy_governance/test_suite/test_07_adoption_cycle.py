"""The two-reading adoption cycle, the revision loop and the adoption cascade."""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_agenda_item,
    adjourn_meeting,
    api_client,
    assert_instant_equals,
    assert_vote_ledger_balances,
    approve_minutes,
    draft_version,
    file_mandate,
    make_board_president_headers,
    publish_edition,
    read_agenda_item,
    read_edition,
    read_mandate,
    read_meeting,
    read_policy,
    read_policy_version,
    record_vote,
    seat_board,
    setup_emergency_adoption,
    setup_open_meeting_with_first_reading,
    setup_policy_with_draft,
    setup_second_reading_stage,
    start_edition,
    validate_error,
    validate_success,
    vote_payload,
)

PUBLIC = TEST_USERS["public_headers"]


def test_second_reading_at_the_first_reading_meeting_is_void():
    """PRD 3.7: "First, the second reading may not be held at the meeting that held the
    first reading: if the item's meeting is the same meeting recorded in the version's
    `first_reading_meeting_id`, the vote is refused with `ERR_SECOND_READING_SAME_MEETING`.
    Only then is the minutes rule consulted: the meeting named by `first_reading_meeting_id`
    must have `minutes_status` `APPROVED`, and otherwise the vote is refused with
    `ERR_MINUTES_NOT_APPROVED`."
    PRD 2.7: "One consequence deserves emphasis because it is easy to get backwards: a
    second reading held at the same meeting as the first reading is refused with
    `ERR_SECOND_READING_SAME_MEETING` **before** the minutes-approval rule is consulted,
    because a same-meeting second reading is void no matter what the minutes say."

    Design: Corner/validations/second_reading_held_at_the_first_reading_meeting_is_rejected
    """
    members = seat_board(3)
    ids = [m["id"] for m in members]
    policy, version = setup_policy_with_draft()

    from test_helpers import post_notice, schedule_meeting, set_clock, open_meeting

    meeting = schedule_meeting()
    first_item = add_agenda_item(
        meeting["id"],
        meeting["version"],
        item_type="POLICY_FIRST_READING",
        title="First reading BP-4119",
        policy_version_id=version["id"],
    )
    second_item = add_agenda_item(
        meeting["id"],
        first_item["meeting_version_after"],
        item_type="POLICY_SECOND_READING",
        title="Second reading BP-4119 same night",
        policy_version_id=version["id"],
    )
    post_notice(meeting["id"])
    set_clock("2026-09-10T18:00:00Z")
    open_meeting(meeting["id"], ids, ids[0])
    record_vote(first_item["id"], ids[0], yes_member_ids=ids[:2], no_member_ids=ids[2:3])

    response = api_client.record_vote(
        second_item["id"],
        vote_payload(yes_member_ids=ids[:2], no_member_ids=ids[2:3]),
        make_board_president_headers(ids[0]),
    )
    error = validate_error(response, ApiErrorId.ERR_SECOND_READING_SAME_MEETING.value)
    assert response.status_code == 422
    assert error["error_id"] != ApiErrorId.ERR_MINUTES_NOT_APPROVED.value

    version_row = read_policy_version(version["id"])
    assert version_row["status"] == "FIRST_READING_PASSED"
    assert version_row["first_reading_meeting_id"] == meeting["id"]
    assert read_agenda_item(second_item["id"])["status"] == "POSTED"


def test_emergency_adoption_is_already_settled_in_the_same_response():
    """PRD 3.7: "Such an item takes its version straight from `DRAFT` to `ADOPTED`,
    skipping `FIRST_READING_PASSED` altogether: `reading_count` becomes 2,
    `adopting_meeting_id` and `adopted_at` are written, and `effective_date` equals
    `adopted_at` exactly, with no delay, because an emergency adoption takes force
    immediately."
    PRD 1: "when a policy is adopted, the cascade that supersedes the prior version,
    satisfies the outstanding mandates, recomputes the policy's compliance posture and
    re-certifies every published manual edition that pins that policy all runs inside the
    same request."

    Design: Corner/consistency_model/emergency_adoption_cascade_is_visible_in_the_same_response
    """
    members = seat_board(3)
    ids = [m["id"] for m in members]
    policy, version = setup_policy_with_draft()
    meeting, item = setup_open_meeting_with_first_reading(
        members,
        version["id"],
        meeting_type="EMERGENCY",
        scheduled_start_utc="2026-08-02T18:00:00Z",
        meeting_title="Emergency Board Meeting",
        item_title="Emergency first reading BP-4119",
    )

    voted = validate_success(
        api_client.record_vote(
            item["id"],
            vote_payload(yes_member_ids=ids),
            make_board_president_headers(ids[0]),
        ),
        200,
    )
    assert voted["status"] == "ACTED"
    assert voted["vote_outcome"] == "PASSED"

    policy_row = validate_success(api_client.get_policy(policy["id"], PUBLIC), 200)
    assert policy_row["adopted_version_no"] == 1
    assert policy_row["compliance_state"] == "COMPLIANT"
    assert policy_row["status"] == "ADOPTED"
    assert_instant_equals(
        policy_row["last_review_date"], "2026-08-02T18:00:00Z", "Policy.last_review_date"
    )

    version_row = read_policy_version(version["id"])
    assert version_row["status"] == "ADOPTED"
    assert version_row["reading_count"] == 2
    assert_instant_equals(
        version_row["effective_date"], "2026-08-02T18:00:00Z", "PolicyVersion.effective_date"
    )


def _failed_second_reading():
    members = seat_board(5)
    ids = [m["id"] for m in members]
    policy, version = setup_policy_with_draft()
    stage = setup_second_reading_stage(
        members,
        policy,
        version,
        first_yes=ids[:3],
        first_no=ids[3:4],
        first_abstain=ids[4:5],
    )
    voted = record_vote(
        stage["ai2"]["id"], ids[0], yes_member_ids=ids[:3], no_member_ids=ids[3:5]
    )
    return policy, version, stage, voted


def test_a_failed_second_reading_freezes_the_ledger_on_the_acted_item():
    """PRD 3.6: "For a `POLICY_SECOND_READING` item on a policy whose
    `legal_requirement_level` is `REQUIRED_BY_LAW`, the threshold is a two-thirds
    supermajority of the whole seated body: two times the frozen
    `seated_member_count_snapshot`, divided by three, rounded **up** to the next whole
    trustee."
    PRD 3.7: "The item is marked `ACTED` with `vote_outcome` `FAILED` and `acted_at`
    stamped, and the version goes `FIRST_READING_PASSED → DRAFT` with `reading_count` reset
    to 0 and `first_reading_meeting_id` cleared back to null."

    Design: Difficulty/non_linear_state_machine/policy_version_failed_second_reading_returns_to_draft
    """
    policy, version, stage, voted = _failed_second_reading()
    assert voted["required_yes_votes"] == 4
    assert voted["vote_yes"] == 3
    assert voted["vote_outcome"] == "FAILED"
    assert voted["status"] == "ACTED"
    assert voted["absent_member_count"] == 0
    assert_vote_ledger_balances(voted, stage["m2"]["seated_member_count_snapshot"])


def test_a_failed_second_reading_throws_the_version_back_to_draft():
    """PRD 3.7: "**The revision loop.** A `POLICY_SECOND_READING` item that fails does not
    kill the version. The item is marked `ACTED` with `vote_outcome` `FAILED` and `acted_at`
    stamped, and the version goes `FIRST_READING_PASSED → DRAFT` with `reading_count` reset
    to 0 and `first_reading_meeting_id` cleared back to null. No policy field changes and no
    mandate is satisfied."

    Design: Difficulty/non_linear_state_machine/policy_version_failed_second_reading_returns_to_draft
    """
    policy, version, stage, voted = _failed_second_reading()

    version_row = read_policy_version(version["id"])
    assert version_row["status"] == "DRAFT"
    assert version_row["reading_count"] == 0
    assert version_row["first_reading_meeting_id"] is None
    assert version_row["adopted_at"] is None

    policy_row = read_policy(policy["id"])
    assert policy_row["status"] == "UNADOPTED"
    assert policy_row["adopted_version_no"] is None


def _minutes_blocked_stage():
    members = seat_board(3)
    ids = [m["id"] for m in members]
    policy, version = setup_policy_with_draft()
    stage = setup_second_reading_stage(
        members, policy, version, approve_first_minutes=False
    )
    return members, ids, policy, version, stage


def test_second_reading_is_blocked_while_the_first_meeting_minutes_are_unapproved():
    """PRD 3.7: "Only then is the minutes rule consulted: the meeting named by
    `first_reading_meeting_id` must have `minutes_status` `APPROVED`, and otherwise the
    vote is refused with `ERR_MINUTES_NOT_APPROVED`."
    PRD 3.7: "A policy version must survive two readings at two different meetings before
    it becomes board policy, and the minutes of the first meeting must have been approved
    before the second reading can be held."

    Design: Difficulty/cross_entity_state_dependency/second_reading_blocked_until_first_reading_meeting_minutes_approved
    """
    members, ids, policy, version, stage = _minutes_blocked_stage()
    assert read_meeting(stage["m1"]["id"])["minutes_status"] == "DRAFTED"

    response = api_client.record_vote(
        stage["ai2"]["id"],
        vote_payload(yes_member_ids=ids[:2], no_member_ids=ids[2:3]),
        make_board_president_headers(ids[0]),
    )
    validate_error(response, ApiErrorId.ERR_MINUTES_NOT_APPROVED.value)
    assert response.status_code == 422
    assert read_policy_version(version["id"])["status"] == "FIRST_READING_PASSED"


def test_approving_the_first_meeting_minutes_unblocks_the_identical_second_reading():
    """PRD 3.7: "On approval the meeting records `minutes_approved_at_meeting_id` — a
    self-reference from one meeting to another — and, in doing so, unblocks any second
    reading whose version records that meeting in `first_reading_meeting_id`. This is the
    cross-meeting dependency at the heart of the open-meeting rules: the vote at meeting
    N+1 depends on the minutes state of meeting N."
    PRD 3.7: "When the second reading passes, the full adoption cascade fires, and every
    hop of it must land inside the same request. The version's `reading_count` becomes 2,
    `adopting_meeting_id` records the hosting meeting, `adopted_at` is stamped from the
    logical clock, and `effective_date` is set to 30 days after `adopted_at` — the standard
    delay before a regularly adopted policy takes force."

    Design: Difficulty/cross_entity_state_dependency/second_reading_blocked_until_first_reading_meeting_minutes_approved
    """
    members, ids, policy, version, stage = _minutes_blocked_stage()
    api_client.record_vote(
        stage["ai2"]["id"],
        vote_payload(yes_member_ids=ids[:2], no_member_ids=ids[2:3]),
        make_board_president_headers(ids[0]),
    )

    approve_minutes(stage["m1"]["id"], stage["m2"]["id"])
    assert read_meeting(stage["m1"]["id"])["minutes_status"] == "APPROVED"

    accepted = api_client.record_vote(
        stage["ai2"]["id"],
        vote_payload(yes_member_ids=ids[:2], no_member_ids=ids[2:3]),
        make_board_president_headers(ids[0]),
    )
    data = validate_success(accepted, 200)
    assert data["vote_outcome"] == "PASSED"
    assert data["required_yes_votes"] == 2

    version_row = read_policy_version(version["id"])
    assert version_row["status"] == "ADOPTED"
    assert version_row["adopting_meeting_id"] == stage["m2"]["id"]


def _five_hop_cascade():
    members = seat_board(3)
    ids = [m["id"] for m in members]
    policy, first_version = setup_policy_with_draft()
    emergency_meeting, _item = setup_emergency_adoption(members, first_version["id"])
    adjourn_meeting(emergency_meeting["id"])

    mandate = file_mandate(
        policy["id"],
        notice_code="LUS-2026-021",
        citation="EC 35291.5",
        issued_on="2026-08-02T18:00:00Z",
        compliance_deadline="2026-11-30T00:00:00Z",
        required_action="REVISE_EXISTING",
    )
    edition = start_edition("2026-FALL", "2026-08-02T18:00:00Z")
    publish_edition(edition["id"])

    refreshed = read_policy(policy["id"])
    second_version = draft_version(
        policy["id"],
        refreshed["version"],
        body_text="Version two text.",
        summary_of_change="Revision compelled by LUS-2026-021",
    )
    stage = setup_second_reading_stage(members, policy, second_version)
    voted = record_vote(
        stage["ai2"]["id"], ids[0], yes_member_ids=ids[:2], no_member_ids=ids[2:3]
    )
    return {
        "policy": policy,
        "first_version": first_version,
        "second_version": second_version,
        "mandate": mandate,
        "edition": edition,
        "stage": stage,
        "voted": voted,
    }


def test_the_second_reading_adoption_supersedes_the_prior_version_and_satisfies_the_mandate():
    """PRD 3.7: "Because a newer version is now board policy, the policy's prior `ADOPTED`
    version, if there is one, moves `ADOPTED → SUPERSEDED` with `superseded_at` stamped
    from the logical clock; the policy's `status` becomes `ADOPTED`, its
    `adopted_version_no` becomes this version's `version_no`, its `last_review_date` is set
    to `adopted_at`, and its `version` rises by 1."
    PRD 3.3: "When a version of the mandate's policy reaches `ADOPTED` with its `adopted_at`
    at or after the mandate's `issued_on`, every mandate on that policy whose `status` is
    `OPEN`, `IN_PROGRESS` or `OVERDUE` and whose `required_action` is `ADOPT_NEW` or
    `REVISE_EXISTING` transitions to `SATISFIED`, recording the adopting version's
    `version_no` in `satisfied_by_version_no` and resetting `days_past_deadline` to 0."

    Design: Difficulty/transitive_cascade/second_reading_adoption_five_hop_recertification_cascade
    """
    scenario = _five_hop_cascade()
    voted = scenario["voted"]
    assert voted["required_yes_votes"] == 2
    assert voted["vote_outcome"] == "PASSED"

    second = read_policy_version(scenario["second_version"]["id"])
    assert second["status"] == "ADOPTED"
    assert second["version_no"] == 2
    assert_instant_equals(second["adopted_at"], "2026-09-24T18:00:00Z", "PolicyVersion.adopted_at")
    assert_instant_equals(
        second["effective_date"], "2026-10-24T18:00:00Z", "PolicyVersion.effective_date"
    )
    assert second["adopting_meeting_id"] == scenario["stage"]["m2"]["id"]

    assert read_policy_version(scenario["first_version"]["id"])["status"] == "SUPERSEDED"

    policy_row = read_policy(scenario["policy"]["id"])
    assert policy_row["adopted_version_no"] == 2
    assert_instant_equals(
        policy_row["last_review_date"], "2026-09-24T18:00:00Z", "Policy.last_review_date"
    )

    mandate_row = read_mandate(scenario["mandate"]["id"])
    assert mandate_row["status"] == "SATISFIED"
    assert mandate_row["satisfied_by_version_no"] == 2


def test_the_adoption_cascade_recertifies_the_published_manual_edition():
    """PRD 3.7: "Because mandate statuses changed, the policy's `open_mandate_count` and
    `overdue_mandate_count` are recomputed and phase 2 of the compliance recompute rewrites
    `compliance_state`. And because `compliance_state` changed, every manual edition in
    `PUBLISHED` status whose pinned entries include this policy recomputes its
    `compliance_gap_count` and flips `certification_state` — `CERTIFIED` when the gap count
    has reached zero, `LAPSED` otherwise."
    PRD 3.9: "The version numbers inside `pinned_entries` are frozen forever: a later
    adoption on the same policy changes that policy's `adopted_version_no` but never
    rewrites an already-published edition's entry."

    Design: Difficulty/transitive_cascade/second_reading_adoption_five_hop_recertification_cascade
    """
    scenario = _five_hop_cascade()

    policy_row = read_policy(scenario["policy"]["id"])
    assert policy_row["open_mandate_count"] == 0
    assert policy_row["compliance_state"] == "COMPLIANT"

    edition_row = read_edition(scenario["edition"]["id"])
    assert edition_row["compliance_gap_count"] == 0
    assert edition_row["certification_state"] == "CERTIFIED"
    assert edition_row["pinned_entries"][0]["version_no"] == 1
