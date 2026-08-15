"""Privileged committee notes and the deliberation sub-resource: ledger
immutability, the note-writing window, and the auto-open cascade on the
third distinct submission."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_case_note,
    assert_instant_equals,
    assign_reviewer,
    create_case,
    create_note_payload,
    create_provider,
    get_case_deliberation,
    make_committee_member_headers,
    screen_case_in,
    seat_member,
    submit_scores,
    validate_error,
    validate_success,
)

QD = TEST_USERS["quality_director_headers"]


def _case_with_assignment():
    subject = create_provider("Subj Notes", "PEDIATRICS")
    member = seat_member(create_provider("Rev B", "PEDIATRICS")["id"], "MEMBER")
    case = create_case(subject["id"], description="notes case")
    screen_case_in(case["id"])
    assignment = assign_reviewer(case["id"], member["id"])
    return subject, member, case, assignment


class TestCaseNotes:
    def test_case_note_is_immutable_ledger_record(self):
        """PRD §2.4: "Six record types are immutable ledger-style entries and
        carry only `id` and `created_at`; both `updated_at` and `version` are
        absent from them: ConflictDeclaration, CaseNote, ProviderNotification,
        ProviderResponse, ExternalReferral, and FocusGroupMember."
        PRD §3.5: "A note carries a non-empty `body` and an optional
        `note_type` of `GENERAL` (the default when omitted) or `DELIBERATION`;
        its `author_member_id` is stamped from the acting member's `X-User-ID`,
        never from the request body."

        Design: Corner/entities/case_note_immutable_no_version_field
        """
        _, member, case, _ = _case_with_assignment()
        resp = api_client.create_case_note(
            case["id"], create_note_payload(body="reviewer context note"),
            make_committee_member_headers(member["id"]))
        data = validate_success(resp, expected_status=201)
        assert_case_note(data)
        assert data["author_member_id"] == member["id"]
        assert data["note_type"] == "GENERAL"

        notes = validate_success(api_client.list_case_notes(case["id"], QD))
        assert len(notes) == 1 and notes[0]["id"] == data["id"]

    def test_note_on_referred_case_returns_invalid_state(self):
        """PRD §3.5: "Throughout the working life of a case — while it is in
        `ASSIGNED`, `IN_REVIEW`, `DELIBERATION`, `NOTIFIED`, `RESPONDED`, or
        `COMMITTEE_REVIEW` — any committee member may attach privileged
        notes."
        PRD §3.5: "Attempts to note a case outside the listed window are
        rejected under the standard state checks, with the terminal variant
        once the case is closed."

        Design: Corner/state_machines/note_on_referred_case_returns_invalid_state
        """
        subject = create_provider("Subj Note2", "SURGERY")
        member = seat_member(create_provider("Rev B", "SURGERY")["id"], "MEMBER")
        case = create_case(subject["id"], description="early note case")
        resp = api_client.create_case_note(
            case["id"], create_note_payload(body="too early"),
            make_committee_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


class TestDeliberationAutoOpen:
    def test_deliberation_read_is_zero_or_one_list(self, quality_director_headers):
        """PRD §3.4: "And if this submission makes three distinct `SUBMITTED`
        assignments on the case, the case moves from `IN_REVIEW` to
        `DELIBERATION` and the Deliberation auto-opens: exactly one
        Deliberation exists per case, created with status `OPEN`, `opened_at`
        stamped with the current logical time, and `rating` still null."

        Design: Corner/endpoints/deliberation_read_zero_or_one_shape
        """
        _, _, members, case, assignments = self._case_with_two_submissions()
        submit_scores(assignments[1]["id"], members[1]["id"], case["id"], 4)

        before = validate_success(
            api_client.get_case_deliberation(case["id"], quality_director_headers))
        assert before == [], "before the third submit the deliberation list is empty"

        submit_scores(assignments[2]["id"], members[2]["id"], case["id"], 4)
        after = validate_success(
            api_client.get_case_deliberation(case["id"], quality_director_headers))
        assert len(after) == 1
        assert after[0]["status"] == "OPEN"
        assert after[0]["rating"] is None

    def _case_with_two_submissions(self):
        subject = create_provider("Subj Nine", "SURGERY")
        chair = seat_member(create_provider("Chair A", "INTERNAL_MEDICINE")["id"], "CHAIR")
        members = [seat_member(create_provider(n, s)["id"], "MEMBER")
                   for n, s in [("Rev B", "SURGERY"), ("Rev C", "CARDIOLOGY"),
                                ("Rev D", "PEDIATRICS")]]
        case = create_case(subject["id"], referral_source="STAFF_REFERRAL",
                           description="depth2 case")
        screen_case_in(case["id"])
        assignments = [assign_reviewer(case["id"], m["id"]) for m in members]
        submit_scores(assignments[0]["id"], members[0]["id"], case["id"], 5)
        return subject, chair, members, case, assignments

    def test_first_submission_moves_case_to_in_review(self, quality_director_headers):
        """PRD §3.4: "If this is the first submission on the case, the case
        moves from `ASSIGNED` to `IN_REVIEW`."

        Design: Difficulty/transitive_cascade/third_submit_depth2_deliberation_cascade
        """
        _, _, _, case, _ = self._case_with_two_submissions()
        mid = validate_success(api_client.get_case(case["id"], quality_director_headers))
        assert mid["status"] == "IN_REVIEW"

    def test_third_submission_opens_deliberation(self, quality_director_headers):
        """PRD §3.4: "And if this submission makes three distinct `SUBMITTED`
        assignments on the case, the case moves from `IN_REVIEW` to
        `DELIBERATION` and the Deliberation auto-opens: exactly one
        Deliberation exists per case, created with status `OPEN`, `opened_at`
        stamped with the current logical time, and `rating` still null."

        Design: Difficulty/transitive_cascade/third_submit_depth2_deliberation_cascade
        """
        _, _, members, case, assignments = self._case_with_two_submissions()

        # With two submissions the case is still IN_REVIEW and no Deliberation
        # exists yet.
        submit_scores(assignments[1]["id"], members[1]["id"], case["id"], 5)
        before = get_case_deliberation(case["id"])
        assert before == [], "no Deliberation row exists before the third submission"

        submitted = submit_scores(assignments[2]["id"], members[2]["id"], case["id"], 4)
        assert submitted["status"] == "SUBMITTED"
        assert_instant_equals(submitted["submitted_at"], "2026-08-01T00:00:00Z")

        case_after = validate_success(api_client.get_case(case["id"], quality_director_headers))
        assert case_after["status"] == "DELIBERATION"

        rows = get_case_deliberation(case["id"])
        assert len(rows) == 1, "exactly one Deliberation exists per case"
        assert rows[0]["status"] == "OPEN"
        assert rows[0]["rating"] is None
        assert_instant_equals(rows[0]["opened_at"], "2026-08-01T00:00:00Z")
