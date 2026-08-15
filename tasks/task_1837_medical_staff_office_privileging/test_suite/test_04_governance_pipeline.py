"""Committee governance: agenda items, vote quorum, deferral, MEC/board SoD."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_delineation,
    add_verification_item,
    advance_to_committee,
    agenda_item_for_case,
    assert_agenda_item,
    board_decline_item,
    board_ratify_item,
    committee_approve_item,
    create_approved_member,
    create_committee_review_application,
    create_draft_application,
    create_member_record,
    create_proposed_case,
    evaluate_delineation_ok,
    get_agenda_item_for_application,
    get_success_data,
    make_board_member_headers,
    mec_endorse_item,
    parse_ts,
    receive_and_verify_item,
    refresh_agenda_item,
    refresh_application,
    refresh_case,
    refresh_member,
    set_clock,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
CHAIR = TEST_USERS["committee_chair_headers"]
MEC = TEST_USERS["mec_chair_headers"]
BOARD = TEST_USERS["board_member_headers"]


class TestAgendaItemCreation:
    def test_agenda_item_created_manually_requires_matching_ref(self, api):
        """PRD §3.4: "Each item carries an `item_kind` — `APPLICATION_APPROVAL`,
        `PRIVILEGE_GRANT`, `ADVERSE_ACTION`, or `POLICY_CHANGE` — and exactly the
        reference field its kind implies: `ref_application_id` for an application
        approval, `ref_delineation_id` for a privilege grant, `ref_case_id` for
        an adverse action. A kind inconsistent with the populated reference is
        rejected with `ERR_AGENDA_REF_MISMATCH` (422)."

        Design: Corner/endpoints/agenda_item_created_manually_requires_matching_ref
        """
        member = create_member_record("Dr. RefMis", "NPDB-RM", "CARD")
        application = create_draft_application(member)

        resp = api.create_agenda_item(
            {"item_kind": "ADVERSE_ACTION",
             "ref_application_id": application["id"]},
            CHAIR)
        validate_error(resp, ApiErrorId.ERR_AGENDA_REF_MISMATCH, 422)


class TestCommitteeVoting:
    def test_committee_vote_quorum_boundary(self, api):
        """PRD §3.4: "the batch must push a tally to quorum: if, after applying
        the batch, `committee_votes_for` has reached `quorum_required`, the item
        moves to `COMMITTEE_APPROVED`; if instead `committee_votes_against` has
        reached `quorum_required`, it moves to `COMMITTEE_REJECTED`; a batch that
        reaches neither threshold is rejected with `ERR_COMMITTEE_QUORUM_UNMET`."
        PRD §3.4: "for every other kind it is the fixed committee quorum of 3."

        Design: Corner/endpoints/committee_vote_quorum_boundary
        """
        ws = create_committee_review_application("Dr. Quorum", "NPDB-QR")
        item_id = ws["agenda_item"]["id"]

        resp = api.committee_vote_agenda_item(item_id, 2, 0, CHAIR)
        validate_error(resp, ApiErrorId.ERR_COMMITTEE_QUORUM_UNMET, 409)
        mid = refresh_agenda_item(item_id)
        assert mid["committee_votes_for"] == 0, (
            "A rejected vote batch is atomic — no partial tally")
        assert mid["committee_votes_against"] == 0
        assert mid["committee_status"] == "AGENDA"

        resp2 = api.committee_vote_agenda_item(item_id, 1, 0, CHAIR)
        validate_error(resp2, ApiErrorId.ERR_COMMITTEE_QUORUM_UNMET, 409)
        assert refresh_agenda_item(item_id)["committee_votes_for"] == 0

        approved = validate_success(
            api.committee_vote_agenda_item(item_id, 3, 0, CHAIR))
        assert approved["committee_status"] == "COMMITTEE_APPROVED"
        assert approved["committee_votes_for"] == 3

    def test_cascade_partial_failure_atomicity_on_committee_vote(self, api):
        """PRD §3.4: "a batch that reaches neither threshold is rejected with
        `ERR_COMMITTEE_QUORUM_UNMET`."
        PRD §2.9: "Every request is validated against a fixed priority ladder,
        and a request that fails an earlier rung is never evaluated against a
        later one — the first failing rung determines the error returned."

        A rejected batch leaves no trace: vote counters and status are unchanged.

        Design: Corner/cross_cutting_layers/cascade_partial_failure_atomicity_on_committee_vote
        """
        ws = create_committee_review_application("Dr. Atom", "NPDB-ATM")
        item_id = ws["agenda_item"]["id"]

        resp = api.committee_vote_agenda_item(item_id, 2, 0, CHAIR)
        validate_error(resp, ApiErrorId.ERR_COMMITTEE_QUORUM_UNMET, 409)

        item = refresh_agenda_item(item_id)
        assert item["committee_votes_for"] == 0
        assert item["committee_votes_against"] == 0
        assert item["committee_status"] == "AGENDA"

    def test_defer_reagenda_cycle_and_terminal_lockout(self, api):
        """PRD §3.4: "the chair may defer an item — `AGENDA` → `DEFERRED`,
        rejected from any other state with `ERR_ITEM_NOT_DEFERRABLE` — and may
        later return it to the agenda, `DEFERRED` → `AGENDA`, rejected from any
        other state with `ERR_ITEM_NOT_REAGENDABLE`; the `AGENDA` ↔ `DEFERRED`
        cycle is unrestricted."

        Design: Corner/endpoints/defer_reagenda_cycle_and_terminal_lockout
        """
        ws = create_committee_review_application("Dr. Defer", "NPDB-DF")
        item_id = ws["agenda_item"]["id"]

        deferred = get_success_data(api.defer_agenda_item(item_id, CHAIR))
        assert deferred["committee_status"] == "DEFERRED"
        back = get_success_data(api.reagenda_agenda_item(item_id, CHAIR))
        assert back["committee_status"] == "AGENDA"

        committee_approve_item(item_id)
        mec_endorse_item(item_id, "mec-voter-df")
        ratified = board_ratify_item(item_id)
        assert ratified["committee_status"] == "BOARD_RATIFIED"

        resp = api.defer_agenda_item(item_id, CHAIR)
        validate_error(resp, ApiErrorId.ERR_ITEM_NOT_DEFERRABLE, 409)
        assert refresh_agenda_item(item_id)["committee_status"] == "BOARD_RATIFIED"


class TestMecEndorsement:
    def test_error_duplicate_mec_vote_rejected(self, api):
        """PRD §3.4: "MEC endorsement by a `MedicalExecutiveCommitteeChair`
        requires the item in `COMMITTEE_APPROVED`
        (`ERR_ITEM_NOT_COMMITTEE_APPROVED`). The call carries a `voter_id`, which
        is appended to the item's `mec_voter_ids`; a `voter_id` already present
        in that list may not vote twice and is rejected with
        `ERR_DUPLICATE_MEC_VOTE`."
        PRD §2.9: "the first failing rung determines the error returned" — the
        state-machine rung (5) is evaluated before structural constraints (9),
        so the second endorsement surfaces the state error.

        Design: Corner/errors/error_duplicate_mec_vote_rejected
        """
        ws = create_committee_review_application("Dr. Dup", "NPDB-DUP")
        item_id = ws["agenda_item"]["id"]
        committee_approve_item(item_id)

        endorsed = mec_endorse_item(item_id, "mec-user-dup")
        assert endorsed["committee_status"] == "MEC_ENDORSED"

        resp = api.mec_endorse_agenda_item(item_id, "mec-user-dup", MEC)
        validate_error(resp, ApiErrorId.ERR_ITEM_NOT_COMMITTEE_APPROVED, 409)

        item = refresh_agenda_item(item_id)
        assert item["mec_voter_ids"] == ["mec-user-dup"], (
            "The single successful endorsement records the voter exactly once")


class TestBoardSegregation:
    def test_rbac_board_sod_conflict_on_ratify(self, api):
        """PRD §2.10: "Every MEC endorsement records the voter's identifier in
        the agenda item's `mec_voter_ids`, and a board member whose `X-User-ID`
        appears in that list may not cast the board ratification or decline vote
        on the same item — the attempt is rejected with `ERR_SOD_BOARD_CONFLICT`
        (403)."

        Design: Corner/roles/rbac_board_sod_conflict_on_ratify
        """
        ws = create_committee_review_application("Dr. SOD", "NPDB-SOD")
        item_id = ws["agenda_item"]["id"]
        committee_approve_item(item_id)
        mec_endorse_item(item_id, "dual-hat-1")

        conflicted = api.board_ratify_agenda_item(
            item_id, make_board_member_headers("dual-hat-1"))
        validate_error(conflicted, ApiErrorId.ERR_SOD_BOARD_CONFLICT, 403)

        ratified = validate_success(api.board_ratify_agenda_item(
            item_id, make_board_member_headers("board-clean-2")))
        assert ratified["committee_status"] == "BOARD_RATIFIED"
        assert ratified["board_voter_id"] == "board-clean-2"
        assert refresh_application(
            ws["application"]["id"])["application_status"] == "APPROVED"


class TestRatificationCascade:
    def test_immediate_visibility_of_cascade_results(self, api):
        """PRD §3.4: "Ratification moves the item to `BOARD_RATIFIED` and
        cascades by kind: an `APPLICATION_APPROVAL` ratification approves the
        application (the cascade below)".
        PRD §3.4: "In both cases, every `CRITERIA_MET` delineation on the
        application flips to `GRANTED` and spawns a **PrivilegeGrant** in
        `PROVISIONAL` whose `effective_until` equals the member's
        `current_term_end`".

        Design: Corner/consistency_model/immediate_visibility_of_cascade_results
        """
        ws = create_committee_review_application("Dr. ImmC", "NPDB-IC")
        committee_approve_item(ws["agenda_item"]["id"])
        mec_endorse_item(ws["agenda_item"]["id"], "mec-voter-ic")
        board_ratify_item(ws["agenda_item"]["id"])

        application = refresh_application(ws["application"]["id"])
        assert application["application_status"] == "APPROVED"

        delineation = get_success_data(
            api.get_delineation(ws["delineation"]["id"], COORD))
        assert delineation["delineation_status"] == "GRANTED"

        grants, meta = validate_paginated(
            api.list_privilege_grants(
                COORD, params={"member_id": ws["member"]["id"]}))
        assert len(grants) == 1
        assert grants[0]["grant_status"] == "PROVISIONAL"
        assert grants[0]["member_id"] == ws["member"]["id"]
        assert grants[0]["privilege_line"] == "EMED-GEN"

        member = refresh_member(ws["member"]["id"])
        assert member["membership_status"] == "ACTIVE"
        assert parse_ts(member["current_term_end"]) == parse_ts(
            "2028-08-01T00:00:00Z"), (
            "Initial ratification at the 2026-08-01 clock stamps a two-year term")

    def test_application_denied_reappointment_spawns_adverse_case(self, api):
        """PRD §3.4: "Denial — `BOARD_REVIEW` → `DENIED`, automatic on
        declination — copies the deciding agenda item's recorded rationale into
        the application's `decision_reason`."
        PRD §3.4: "For a `REAPPOINTMENT` application the system additionally
        auto-creates an **AdverseActionCase** of `case_kind`
        `DENIAL_OF_REAPPOINTMENT` referencing the member — which itself schedules
        a `hearing_request_deadline` per §3.8."

        Design: Corner/state_machines/application_denied_reappointment_spawns_adverse_case
        """
        ws = create_approved_member("Dr. Deny", "NPDB-DR1")
        member_id = ws["member"]["id"]

        # Inside the reappointment window (180 days before the 2028-08-01 term
        # end), build a second, REAPPOINTMENT application to BOARD_REVIEW.
        set_clock("2028-03-01T00:00:00Z")
        member = refresh_member(member_id)
        application2 = create_draft_application(
            member, application_kind="REAPPOINTMENT")
        item2 = add_verification_item(application2["id"])
        delineation2 = add_delineation(application2["id"])
        submit_application(application2["id"])
        receive_and_verify_item(item2["id"])
        evaluate_delineation_ok(delineation2["id"])
        advance_to_committee(application2["id"])
        agenda2 = get_agenda_item_for_application(application2["id"])
        committee_approve_item(agenda2["id"])
        mec_endorse_item(agenda2["id"], "mec-voter-dr1")

        board_decline_item(agenda2["id"])

        assert refresh_application(
            application2["id"])["application_status"] == "DENIED"
        cases, meta = validate_paginated(
            api.list_adverse_action_cases(
                COORD, params={"subject_member_id": member_id}))
        denial_cases = [c for c in cases
                        if c["case_kind"] == "DENIAL_OF_REAPPOINTMENT"]
        assert len(denial_cases) == 1, (
            "Exactly one DENIAL_OF_REAPPOINTMENT case is auto-created")
        assert denial_cases[0]["subject_member_id"] == member_id


class TestAdverseItemReadinessGate:
    def _proposed_case_with_agenda_item(self):
        ws = create_approved_member("Dr. AC", "NPDB-AC1")
        chief = create_member_record("Dr. ChiefAC", "NPDB-PAC", "EMED")
        case = create_proposed_case(ws["member"]["id"], chief["id"],
                                    "SUSPENSION")
        item = agenda_item_for_case(case["id"])
        return ws, case, item

    def test_committee_vote_blocked_while_case_proposed(self, api):
        """PRD §3.4: "For an `ADVERSE_ACTION` item there is one more readiness
        gate: the referenced case must be in `HEARING_HELD` or `MEC_ENDORSED`
        (`ERR_CASE_NOT_READY_FOR_COMMITTEE`)."

        Design: Difficulty/cross_entity_state_dependency/committee_vote_gated_by_adverse_case_state
        """
        _ws, case, item = self._proposed_case_with_agenda_item()
        assert refresh_case(case["id"])["case_status"] == "PROPOSED"

        resp = api.committee_vote_agenda_item(item["id"], 3, 0, CHAIR)
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_READY_FOR_COMMITTEE, 409)
        assert refresh_agenda_item(item["id"])["committee_status"] == "AGENDA"

    def test_committee_vote_succeeds_once_case_endorsed(self, api):
        """PRD §3.4: "For an `ADVERSE_ACTION` item there is one more readiness
        gate: the referenced case must be in `HEARING_HELD` or `MEC_ENDORSED`
        (`ERR_CASE_NOT_READY_FOR_COMMITTEE`)."

        The identical vote succeeds once the case reaches MEC_ENDORSED.

        Design: Difficulty/cross_entity_state_dependency/committee_vote_gated_by_adverse_case_state
        """
        _ws, case, item = self._proposed_case_with_agenda_item()
        get_success_data(api.endorse_adverse_action_case(case["id"], MEC))

        approved = validate_success(
            api.committee_vote_agenda_item(item["id"], 3, 0, CHAIR))
        assert_agenda_item(approved)
        assert approved["committee_status"] == "COMMITTEE_APPROVED"
        assert approved["committee_votes_for"] == 3
