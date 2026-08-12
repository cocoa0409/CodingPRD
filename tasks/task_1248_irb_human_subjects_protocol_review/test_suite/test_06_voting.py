"""Convened-board voting: cross-entity gates, tally integrity, chair
segregation of duties, modification routing, and the DISAPPROVED terminal
state (PRD §3.6, §3.7).
"""
from test_helpers import (
    ApiErrorId,
    add_agenda_item_ok,
    approve_consent_document,
    convene_meeting_ok,
    create_draft_protocol,
    create_modification_ok,
    declare_conflict,
    adjudicate_declaration,
    drive_to_awaiting_full_board,
    get_agenda_item,
    get_meeting,
    get_protocol,
    get_success_data,
    make_chair_headers,
    make_pi_headers,
    register_chair,
    register_investigator,
    register_member,
    register_quorum_members,
    schedule_meeting,
    setup_approved_protocol,
    setup_awaiting_full_board_scenario,
    unique_email,
    upload_consent,
    submit_protocol_ok,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

COORDINATOR = TEST_USERS["coordinator_headers"]


def _convened_initial_review_item(api):
    """Five ACTIVE members; protocol AWAITING_FULL_BOARD with APPROVED consent,
    LISTED on a meeting CONVENED with attendees {chair, nonsci, unaff}
    (eligible_voter_count 3)."""
    members = register_quorum_members()
    scenario = setup_awaiting_full_board_scenario(chair=members["chair"])
    proto = scenario["protocol"]
    meeting = schedule_meeting(room_id="R-VOTE")
    item = add_agenda_item_ok(meeting["id"], proto["id"], meeting["version"])
    convene_meeting_ok(
        meeting["id"], members["chair"]["id"],
        [members["chair"]["id"], members["nonsci"]["id"], members["unaff"]["id"]],
    )
    return members, scenario, meeting, item


class TestVoteCrossEntityGate:
    def test_vote_rejected_while_meeting_scheduled(self, api):
        """PRD §3.6: "The item must be `LISTED` and its meeting `CONVENED` — a
        cross-entity gate, each breach answered by `ERR_INVALID_STATE`".

        Design: Difficulty/cross_entity_state_dependency/agenda_vote_requires_convened_meeting
        """
        members = register_quorum_members()
        scenario = setup_awaiting_full_board_scenario()
        proto = scenario["protocol"]
        meeting = schedule_meeting(room_id="R-VOTE")
        item = add_agenda_item_ok(meeting["id"], proto["id"], meeting["version"])

        # The meeting is still SCHEDULED: the vote is rejected even though the
        # item itself is LISTED and unchanged.
        resp = api.vote_agenda_item(
            item["id"],
            {"motion": "APPROVE", "votes_for": 3, "votes_against": 0,
             "votes_abstain": 0},
            make_chair_headers(members["chair"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_agenda_item(item["id"])["status"] == "LISTED"

    def test_vote_succeeds_after_convene(self, api):
        """PRD §3.6: "An `APPROVE` motion that passes records `outcome`
        `APPROVE`: on an initial-review item the protocol becomes `APPROVED`
        with the same interval, expiry, and first-cycle creation side effects
        as an expedited approval". PRD §3.6: "A motion passes only when twice
        `votes_for` strictly exceeds `eligible_voter_count`; an exact tie
        fails."

        Design: Difficulty/cross_entity_state_dependency/agenda_vote_requires_convened_meeting
        """
        members, scenario, _meeting, item = _convened_initial_review_item(api)
        proto = scenario["protocol"]

        data = validate_success(
            api.vote_agenda_item(
                item["id"],
                {"motion": "APPROVE", "votes_for": 3, "votes_against": 0,
                 "votes_abstain": 0},
                make_chair_headers(members["chair"]["id"]),
            )
        )
        assert data["status"] == "VOTED"
        assert data["outcome"] == "APPROVE"
        assert get_protocol(proto["id"])["status"] == "APPROVED"


class TestVoteTallyIntegrity:
    def test_vote_tally_must_match_recusal_adjusted_denominator(self, api):
        """PRD §3.6: "Integrity demands the three tallies sum exactly to that
        count, any mismatch rejected with `ERR_VOTE_TALLY_MISMATCH`. A motion
        passes only when twice `votes_for` strictly exceeds
        `eligible_voter_count`; an exact tie fails."

        Design: Corner/validations/vote_tally_must_match_recusal_adjusted_denominator
        """
        members, scenario, _meeting, item = _convened_initial_review_item(api)
        proto = scenario["protocol"]

        # eligible_voter_count is 3; 2+0+0 = 2 does not match.
        resp = api.vote_agenda_item(
            item["id"],
            {"motion": "APPROVE", "votes_for": 2, "votes_against": 0,
             "votes_abstain": 0},
            make_chair_headers(members["chair"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VOTE_TALLY_MISMATCH)

        # Corrected tally: 2+1+0 = 3 and 2*2 = 4 > 3 passes strict majority.
        data = validate_success(
            api.vote_agenda_item(
                item["id"],
                {"motion": "APPROVE", "votes_for": 2, "votes_against": 1,
                 "votes_abstain": 0},
                make_chair_headers(members["chair"]["id"]),
            )
        )
        assert data["outcome"] == "APPROVE"
        assert get_protocol(proto["id"])["status"] == "APPROVED"


class TestChairConflictSegregation:
    def test_chair_conflicted_cannot_run_vote(self, api):
        """PRD §3.6: "the chair must hold no `CONFLICTED` declaration on the
        item's protocol, else `ERR_CHAIR_CONFLICTED`. At the moment of voting
        the server freezes `eligible_voter_count`: the size of the meeting's
        attendee roster minus those attendees holding a `CONFLICTED`
        declaration on the item's protocol."

        Design: Corner/validations/chair_conflicted_cannot_run_vote
        """
        inv = register_investigator()
        chair1 = register_chair(email=unique_email("chairone"))
        chair2 = register_chair(email=unique_email("chairtwo"))
        nonsci = register_member("NON_SCIENTIST", email=unique_email("nssod"))
        unaff = register_member("UNAFFILIATED", email=unique_email("unsod"))
        register_member("PRISONER_REPRESENTATIVE", email=unique_email("prsod"))

        proto = create_draft_protocol(
            inv["id"], title="SoD Study", claimed_review_level="FULL_BOARD",
            risk_level="GREATER_THAN_MINIMAL",
        )
        cd = upload_consent(proto["id"], inv["id"], file_ref="s3://consent/sod.pdf")
        approve_consent_document(cd["id"], chair2["id"])
        drive_to_awaiting_full_board(proto["id"], inv["id"])

        # chair1 self-declares a financial conflict, adjudicated by chair2.
        decl = declare_conflict(
            proto["id"], chair1["id"], declaration_type="FINANCIAL",
            detail="consulting income from sponsor",
        )
        adjudicate_declaration(decl["id"], chair2["id"], "CONFLICTED")

        meeting = schedule_meeting(room_id="R-SOD")
        item = add_agenda_item_ok(meeting["id"], proto["id"], meeting["version"])
        convene_meeting_ok(
            meeting["id"], chair2["id"],
            [chair1["id"], chair2["id"], nonsci["id"], unaff["id"]],
        )

        resp = api.vote_agenda_item(
            item["id"],
            {"motion": "APPROVE", "votes_for": 2, "votes_against": 1,
             "votes_abstain": 0},
            make_chair_headers(chair1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CHAIR_CONFLICTED)

        # Unconflicted chair2 records the same vote; the denominator excludes
        # conflicted chair1: 4 attendees - 1 = 3.
        data = validate_success(
            api.vote_agenda_item(
                item["id"],
                {"motion": "APPROVE", "votes_for": 2, "votes_against": 1,
                 "votes_abstain": 0},
                make_chair_headers(chair2["id"]),
            )
        )
        assert data["eligible_voter_count"] == 3, (
            f"4 attendees minus conflicted chair1 = 3, got {data['eligible_voter_count']}"
        )
        assert data["outcome"] == "APPROVE"  # 2*2 = 4 > 3
        assert get_protocol(proto["id"])["status"] == "APPROVED"


class TestMajorModificationRouting:
    def test_major_modification_requires_board_vote(self, api):
        """PRD §3.7: "chair approval of a `MAJOR` modification is rejected with
        `ERR_MAJOR_REQUIRES_BOARD`, because major amendments are decided only
        by a convened board voting on an agenda item that carries the
        modification's `modification_id` — a passing `APPROVE` approves it,
        while a failed `APPROVE` or a passing `REQUIRE_CHANGES` denies it."

        Design: Corner/validations/major_modification_requires_board_vote
        """
        scenario = setup_approved_protocol()
        inv = scenario["investigator"]
        chair = scenario["chair"]
        proto = scenario["protocol"]
        rev2 = scenario["reviewers"][1]
        unaff = register_member("UNAFFILIATED", email=unique_email("unmj"))
        register_member("PRISONER_REPRESENTATIVE", email=unique_email("prmj"))

        pv = get_protocol(proto["id"])["version"]
        mod = create_modification_ok(
            proto["id"], inv["id"], pv, scope="MAJOR",
            description="add adolescent cohort",
        )

        meeting = schedule_meeting(room_id="R-MAJ")
        item = add_agenda_item_ok(
            meeting["id"], proto["id"], meeting["version"],
            modification_id=mod["id"],
        )
        # Five ACTIVE members -> threshold 3; roster {chair, rev2, unaff}.
        convene_meeting_ok(
            meeting["id"], chair["id"], [chair["id"], rev2["id"], unaff["id"]]
        )

        resp = api.adjudicate_modification(
            mod["id"], {"outcome": "APPROVE"}, make_chair_headers(chair["id"])
        )
        validate_error(resp, ApiErrorId.ERR_MAJOR_REQUIRES_BOARD)
        assert get_success_data(api.get_modification(mod["id"], COORDINATOR))["status"] == "SUBMITTED"

        data = validate_success(
            api.vote_agenda_item(
                item["id"],
                {"motion": "APPROVE", "votes_for": 3, "votes_against": 0,
                 "votes_abstain": 0},
                make_chair_headers(chair["id"]),
            )
        )
        assert data["outcome"] == "APPROVE"
        mod_after = get_success_data(api.get_modification(mod["id"], COORDINATOR))
        assert mod_after["status"] == "APPROVED"
        assert get_protocol(proto["id"])["status"] == "APPROVED"


class TestDisapprovedTerminalLockdown:
    def test_disapproved_terminal_lockdown(self, api):
        """PRD §3.6: "An `APPROVE` motion that fails records `outcome`
        `DISAPPROVE`: the protocol becomes `DISAPPROVED` — only a convened
        board may disapprove a protocol". PRD §3.2: "From `DRAFT` or `RETURNED`
        it enters `SUBMITTED`; from `CHANGES_REQUESTED` it re-enters
        `UNDER_EXPEDITED_REVIEW`; from `BOARD_CHANGES_REQUESTED` it re-enters
        `AWAITING_FULL_BOARD`." PRD §3.2: "A protocol not currently in
        `SUBMITTED` rejects either lever with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/disapproved_terminal_lockdown
        """
        members, scenario, _meeting, item = _convened_initial_review_item(api)
        proto = scenario["protocol"]
        inv = scenario["investigator"]

        # eligible_voter_count 3; votes_for 1 -> 1*2 = 2 <= 3, motion fails.
        data = validate_success(
            api.vote_agenda_item(
                item["id"],
                {"motion": "APPROVE", "votes_for": 1, "votes_against": 2,
                 "votes_abstain": 0},
                make_chair_headers(members["chair"]["id"]),
            )
        )
        assert data["outcome"] == "DISAPPROVE"
        assert get_protocol(proto["id"])["status"] == "DISAPPROVED"

        # DISAPPROVED is terminal: both a resubmission and a determination fail.
        resp1 = api.submit_protocol(proto["id"], make_pi_headers(inv["id"]))
        validate_error(resp1, ApiErrorId.ERR_INVALID_STATE)

        resp2 = api.record_determination(
            proto["id"], {"determined_review_level": "EXPEDITED"}, COORDINATOR
        )
        validate_error(resp2, ApiErrorId.ERR_INVALID_STATE)
