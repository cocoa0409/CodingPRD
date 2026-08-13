"""Score submission: range validation, state legality, OCC guard, immediate
read-after-write visibility, and the submit-vs-waive fork's side effects."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_instant_equals,
    assign_reviewer,
    create_case,
    create_provider,
    get_assignment,
    get_case,
    list_case_assignments,
    make_committee_member_headers,
    screen_case_in,
    seat_member,
    submit_assignment_payload,
    submit_scores,
    validate_error,
    validate_paginated,
    validate_success,
)

QD = TEST_USERS["quality_director_headers"]
PRC = TEST_USERS["peer_review_coordinator_headers"]


def _case_with_one_assignment():
    subject = create_provider("Subj Sub", "SURGERY")
    member = seat_member(create_provider("Rev B", "SURGERY")["id"], "MEMBER")
    case = create_case(subject["id"], description="submit case")
    screen_case_in(case["id"])
    assignment = assign_reviewer(case["id"], member["id"])
    return subject, member, case, assignment


class TestSubmitValidation:
    def test_score_out_of_range_rejected(self):
        """PRD §3.4: "A score present but outside the 1-to-5 range is rejected
        with `ERR_SCORE_OUT_OF_RANGE` (422)."

        Design: Corner/validations/submit_score_out_of_range_rejected
        """
        _, member, case, assignment = _case_with_one_assignment()
        version = get_case(case["id"])["version"]
        resp = api_client.submit_assignment(
            assignment["id"],
            submit_assignment_payload(0, version),
            make_committee_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_SCORE_OUT_OF_RANGE.value, expected_status=422)
        after = get_assignment(assignment["id"])
        assert after["status"] == "PENDING"
        assert after["care_appropriateness_score"] is None

    def test_double_submit_returns_invalid_state(self):
        """PRD §3.4: "The assignment itself must still be `PENDING`, and the
        case must be in `ASSIGNED` or `IN_REVIEW`; otherwise the submission is
        rejected with `ERR_INVALID_STATE`, or with `ERR_ALREADY_TERMINAL` when
        the case has already reached a terminal state."

        Design: Corner/state_machines/double_submit_returns_invalid_state
        """
        _, member, case, assignment = _case_with_one_assignment()
        submit_scores(assignment["id"], member["id"], case["id"], 4)
        version = get_case(case["id"])["version"]
        resp = api_client.submit_assignment(
            assignment["id"],
            submit_assignment_payload(5, version),
            make_committee_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
        after = get_assignment(assignment["id"])
        assert after["care_appropriateness_score"] == 4, (
            "the rejected resubmission must not overwrite the stored score")

    def test_stale_case_version_on_submit_returns_412(self):
        """PRD §2.7: "If the case's current `version` has advanced past that
        value — for instance because another writer has already added a
        reviewer (legitimately consuming one of the three assignment slots) or
        another reviewer's submission has already advanced the case's status —
        the write is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing
        the client from acting on a case state it has not observed."

        Design: Corner/complexity_layers/occ_stale_submit_returns_412
        """
        subject = create_provider("Subj OCC1", "SURGERY")
        member_b = seat_member(create_provider("Rev B", "SURGERY")["id"], "MEMBER")
        member_c = seat_member(create_provider("Rev C", "CARDIOLOGY")["id"], "MEMBER")
        case = create_case(subject["id"], description="occ case 1")
        screen_case_in(case["id"])
        asg_b = assign_reviewer(case["id"], member_b["id"])
        asg_c = assign_reviewer(case["id"], member_c["id"])

        stale_version = get_case(case["id"])["version"]
        api_client.submit_assignment(
            asg_b["id"], submit_assignment_payload(4, stale_version),
            make_committee_member_headers(member_b["id"]))

        resp = api_client.submit_assignment(
            asg_c["id"], submit_assignment_payload(4, stale_version),
            make_committee_member_headers(member_c["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)
        assert get_assignment(asg_c["id"])["status"] == "PENDING"

        fresh_version = get_case(case["id"])["version"]
        retry = api_client.submit_assignment(
            asg_c["id"], submit_assignment_payload(4, fresh_version),
            make_committee_member_headers(member_c["id"]))
        retry_data = validate_success(retry, expected_status=200)
        assert retry_data["status"] == "SUBMITTED"

    def test_immediate_read_after_write_visibility(self, quality_director_headers):
        """PRD §2.4: "All such cascade effects commit atomically with the
        triggering write; the consistency model is immediate, with no deferred
        reconciliation."
        PRD §3.4: "The assignment moves to `SUBMITTED`, its `submitted_at` is
        stamped with the current logical time (first submission only —
        revision never touches it), and its `version` increments. The
        reviewing member's `reliability_completed_count` increments by one and
        the member's `version` increments."

        Design: Corner/consistency_model/immediate_read_after_write_visibility
        """
        _, member, case, assignment = _case_with_one_assignment()
        submitted = submit_scores(assignment["id"], member["id"], case["id"], 4)
        assert submitted["status"] == "SUBMITTED"
        assert_instant_equals(submitted["submitted_at"], "2026-08-01T00:00:00Z")

        case_after = validate_success(api_client.get_case(case["id"], quality_director_headers))
        assert case_after["status"] == "IN_REVIEW"
        member_after = validate_success(
            api_client.get_committee_member(member["id"], quality_director_headers))
        assert member_after["reliability_completed_count"] == 1


class TestSubmitVersusWaiveFork:
    def _setup_fork(self):
        """Case with B/C/D assigned; B submits 4; C and D remain PENDING."""
        subject = create_provider("Subj Seven", "OBSTETRICS")
        members = {c: seat_member(create_provider(f"Rev {c}", s)["id"], "MEMBER")
                   for c, s in [("B", "OBSTETRICS"), ("C", "SURGERY"),
                                ("D", "CARDIOLOGY"), ("E", "PEDIATRICS")]}
        case = create_case(subject["id"], referral_source="INCIDENT_REPORT",
                           description="fork case")
        screen_case_in(case["id"])
        assignments = {c: assign_reviewer(case["id"], m["id"])
                       for c, m in members.items() if c != "E"}
        submit_scores(assignments["B"]["id"], members["B"]["id"], case["id"], 4)
        return subject, members, case, assignments

    def test_submit_branch_increments_reliability_and_advances_case(
            self, quality_director_headers):
        """PRD §3.4: "The reviewing member's `reliability_completed_count`
        increments by one and the member's `version` increments."
        PRD §3.4: "If this is the first submission on the case, the case moves
        from `ASSIGNED` to `IN_REVIEW`."

        Design: Difficulty/non_linear_state_machine/assignment_fork_submit_vs_waive_side_effects
        """
        _, members, case, _ = self._setup_fork()
        member_b = validate_success(
            api_client.get_committee_member(members["B"]["id"], quality_director_headers))
        assert member_b["reliability_completed_count"] == 1
        case_after = validate_success(api_client.get_case(case["id"], quality_director_headers))
        assert case_after["status"] == "IN_REVIEW"

    def test_waive_branch_frees_slot_without_touching_reliability(
            self, quality_director_headers, peer_review_coordinator_headers):
        """PRD §3.1: "Deactivation moves a member from `ACTIVE` to `INACTIVE`
        and ripples through their workload: every `PENDING` assignment held by
        that member flips to `WAIVED`, and each housing case has its `version`
        incremented and `updated_at` refreshed without any change to the
        case's own status."
        PRD §3.3: "sequence numbers are never reused, so a waived slot still
        consumes its ordinal."

        Design: Difficulty/non_linear_state_machine/assignment_fork_submit_vs_waive_side_effects
        """
        _, members, case, assignments = self._setup_fork()
        validate_success(api_client.deactivate_committee_member(members["D"]["id"], QD))

        waived = get_assignment(assignments["D"]["id"])
        assert waived["status"] == "WAIVED"
        member_d = validate_success(
            api_client.get_committee_member(members["D"]["id"], quality_director_headers))
        assert member_d["reliability_completed_count"] == 0, (
            "waiver is not a submission and must not touch reliability")

        replacement = assign_reviewer(case["id"], members["E"]["id"])
        assert replacement["sequence"] == 4
        case_after = validate_success(api_client.get_case(case["id"], quality_director_headers))
        assert case_after["status"] == "IN_REVIEW", (
            "waiver and refill cause no case status regression")


class TestWaiverReplacementConservesPanel:
    def _setup_panel(self):
        """Case with B/C/D assigned; B submitted 4; C and D PENDING."""
        subject = create_provider("Subj Twenty", "SURGERY")
        members = {c: seat_member(create_provider(f"Rev {c}", s)["id"], "MEMBER")
                   for c, s in [("B", "SURGERY"), ("C", "CARDIOLOGY"),
                                ("D", "PEDIATRICS"), ("E", "EMERGENCY_MEDICINE")]}
        case = create_case(subject["id"], description="invariant case")
        screen_case_in(case["id"])
        assignments = {c: assign_reviewer(case["id"], m["id"])
                       for c, m in members.items() if c != "E"}
        submit_scores(assignments["B"]["id"], members["B"]["id"], case["id"], 4)
        return subject, members, case, assignments

    def test_score_ledger_unchanged_by_waiver_and_replacement(self, quality_director_headers):
        """PRD §3.1: "The member's `SUBMITTED` assignments and
        `reliability_completed_count` are untouched by deactivation."
        PRD §3.3: "The assignment list of a case is ordered by `sequence`
        ascending and may be filtered by `status`."

        Design: Difficulty/compensating_invariant/deactivate_replace_conserves_case_panel
        """
        _, members, case, _ = self._setup_panel()
        validate_success(api_client.deactivate_committee_member(members["D"]["id"], QD))
        assign_reviewer(case["id"], members["E"]["id"])

        submitted_rows, meta = validate_paginated(
            api_client.list_case_assignments(case["id"], QD, params={"status": "SUBMITTED"}))
        assert len(submitted_rows) == 1
        assert submitted_rows[0]["care_appropriateness_score"] == 4, (
            "the waiver-plus-replacement pair must leave the SUBMITTED score "
            "ledger bit-identical")

    def test_panel_refilled_to_three_non_waived_with_fresh_sequence(
            self, quality_director_headers):
        """PRD §3.1: "A `WAIVED` assignment frees its slot toward the per-case
        cap of three non-`WAIVED` assignments, so the coordinator may seat a
        replacement reviewer."
        PRD §3.3: "Its `sequence` is the count of all existing assignments on
        that case — of any status, `WAIVED` included — plus one, and sequence
        numbers are never reused, so a waived slot still consumes its
        ordinal."

        Design: Difficulty/compensating_invariant/deactivate_replace_conserves_case_panel
        """
        _, members, case, _ = self._setup_panel()
        validate_success(api_client.deactivate_committee_member(members["D"]["id"], QD))
        assign_reviewer(case["id"], members["E"]["id"])

        rows = list_case_assignments(case["id"])
        assert [r["sequence"] for r in rows] == [1, 2, 3, 4]
        assert [r["status"] for r in rows] == ["SUBMITTED", "PENDING", "WAIVED", "PENDING"], (
            "non-WAIVED count must return to exactly 3 with the WAIVED row "
            "retaining its consumed ordinal")
