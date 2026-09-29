"""
The three gates above every business rule: are the headers there at all, is the
role admitted to this endpoint, and is the caller who the body says they are.
Each of them answers before anything is loaded, parsed or checked.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import API_PREFIX
from test_helpers.test_users import make_chair_headers, no_headers

UNKNOWN_WORK_ITEM_ID = "22222222-2222-2222-2222-222222222222"


class TestAuthenticationPrecedesExistence:
    """An unauthenticated caller learns nothing about what exists."""

    def test_missing_headers_report_unauthenticated_not_not_found(self, api, staff_headers):
        """
        Both headers present and non-empty, else `ERR_UNAUTHENTICATED` (401). Precedes path
        resolution.

        Every identifier templated into the path resolves to a stored row, checked left to
        right in the order the segments appear.

        Design: Corner/validations/a_request_with_a_missing_x_user_id_header_returns_unauthenticated_not_not_found
        """
        path = f"{API_PREFIX}/work-items/{UNKNOWN_WORK_ITEM_ID}"

        anonymous = api.call("GET", path, headers=no_headers())
        validate_error(anonymous, "ERR_UNAUTHENTICATED", 401)

        identified = api.call("GET", path, headers=staff_headers)
        validate_error(identified, "ERR_WORK_ITEM_NOT_FOUND", 404)


class TestRoleAdmissionPrecedesTheBody:
    """A role that is not listed for the endpoint never gets its body read."""

    def test_a_forbidden_role_hides_the_malformed_body(self, api, staff_headers):
        """
        `X-User-Role` is one of the six declared roles and is listed for the target endpoint,
        else `ERR_UNAUTHORIZED` (403). Decided from the header alone.

        Design: Corner/validations/a_forbidden_role_is_rejected_before_the_missing_required_field_is_noticed
        """
        scenario = fx.Scenario(api)
        scenario.register("p1")
        malformed = {
            "full_name": "Hal Interloper",
            "interest_category": "USER",
            "employer_affiliation_code": "HALCO",
        }

        forbidden = api.create_participant(malformed, scenario.proposer("p1"))
        validate_error(forbidden, "ERR_UNAUTHORIZED", 403)

        admitted = api.create_participant(malformed, staff_headers)
        validate_error(admitted, "ERR_INVALID_REQUEST", 400)

        rows, meta = validate_paginated(api.list_participants(staff_headers))
        a.assert_total_count(meta, 1)
        assert len(rows) == 1, (
            f"neither attempt created a participant, got {len(rows)}"
        )


class TestChairIdentityIsSeparateFromTheChairRole:
    """Wearing the role admits the request; being the chair decides it."""

    def test_a_member_wearing_the_chair_role_may_not_open_a_ballot(self, api):
        """
        Only a committee chair opens a ballot, and only on their own committee: the caller's
        identifier must equal the `chair_participant_id` of the committee named in the
        request, or the request is refused with `ERR_NOT_COMMITTEE_CHAIR`.

        Design: Corner/validations/a_seated_member_wearing_the_chair_role_may_not_open_a_ballot
        """
        scenario = fx.work_item_with_draft(api)
        assert scenario.get_committee()["chair_participant_id"] == scenario.pid("p1"), (
            "the PRODUCER seat holds the chair"
        )

        impostor = api.create_ballot(
            f.ballot_payload(scenario.draft_id, scenario.committee_id),
            make_chair_headers(scenario.pid("p2")),
        )
        validate_error(impostor, "ERR_NOT_COMMITTEE_CHAIR", 403)

        ballots, meta = validate_paginated(
            api.list_ballots(scenario.staff, {"draft_id": scenario.draft_id})
        )
        a.assert_total_count(meta, 0)
        assert scenario.get_draft()["status"] == "DRAFTING", (
            f"the refused ballot moved nothing, got {scenario.get_draft()['status']}"
        )

        ballot = scenario.open_ballot()

        assert ballot["status"] == "OPEN", (
            f"the real chair's identical request lands, got {ballot['status']}"
        )
        assert ballot["eligible_voter_count"] == 3, (
            f"eligible_voter_count expected 3, got {ballot['eligible_voter_count']}"
        )
        assert scenario.get_draft()["status"] == "SUBCOMMITTEE_BALLOT", (
            f"the draft goes out to ballot, got {scenario.get_draft()['status']}"
        )


class TestSubmitterIdentityIsTiedToTheHeader:
    """A body field naming a participant must name the caller."""

    def test_a_comment_may_not_be_filed_in_another_name(self, api):
        """
        any submitter-identity field carried in a request body — `proposer_participant_id`,
        `submitter_participant_id`, `disclosing_participant_id`, `appellant_participant_id`
        or `requester_participant_id` — must equal `X-User-ID`; a mismatch, or a `X-User-ID`
        that resolves to no participant at all, is `ERR_ACTOR_IDENTITY_MISMATCH` (HTTP 403).

        Design: Corner/validations/filing_a_comment_in_another_participants_name_is_rejected
        """
        scenario = fx.work_item_with_draft(api)
        text = "Clause 19 conflicts with the referenced test method"

        impersonation = api.create_comment(
            f.committee_comment_payload(
                scenario.pid("p3"),
                scenario.draft_id,
                comment_type="TECHNICAL",
                comment_text=text,
                clause_reference="19",
            ),
            scenario.member("p2"),
        )
        validate_error(impersonation, "ERR_ACTOR_IDENTITY_MISMATCH", 403)

        rows, meta = validate_paginated(
            api.list_comments(scenario.staff, {"draft_id": scenario.draft_id})
        )
        a.assert_total_count(meta, 0)
        assert rows == [], f"the refused comment stored nothing, got {rows}"

        comment = validate_success(
            api.create_comment(
                f.committee_comment_payload(
                    scenario.pid("p2"),
                    scenario.draft_id,
                    comment_type="TECHNICAL",
                    comment_text=text,
                    clause_reference="19",
                ),
                scenario.member("p2"),
            ),
            201,
        )

        assert comment["submitter_participant_id"] == scenario.pid("p2"), (
            "the comment is filed in the caller's own name, got "
            f"{comment['submitter_participant_id']}"
        )
        assert comment["status"] == "OPEN", (
            f"a new comment opens OPEN, got {comment['status']}"
        )
        assert comment["is_substantive"] is True, (
            f"a technical comment is substantive, got {comment['is_substantive']}"
        )
        assert comment["public_review_id"] is None, (
            "a committee comment never enters a public review ledger, got "
            f"{comment['public_review_id']}"
        )


class TestTheOpaqueRolesAreNarrow:
    """The board decides appeals and nothing else; the secretariat is exclusive too."""

    def test_the_appeals_board_may_only_decide_the_appeal(self, api):
        """
        The appeals board is the independent panel that decides appeals, and it is
        deliberately barred from every other mutation in the system so that a body able to
        vacate a ballot can never have participated in it. Both opaque roles retain read
        access to every collection.

        Design: Corner/rbac/the_appeals_board_may_decide_appeals_and_is_forbidden_everything_else
        """
        scenario = fx.published_work_item(api)
        consensus_ballot_id = scenario.ballot_id
        scenario.file_appeal(
            "p2",
            cited_ballot_id=consensus_ballot_id,
            grounds="VOTING_PROCEDURE_DEFECT",
            statement="The tally was announced before the window had ended",
        )
        assert scenario.get_work_item()["consensus_gate"] == "BLOCKED", (
            "the filed appeal holds the gate"
        )

        withdrawal = api.periodic_review(
            scenario.work_item_id,
            f.periodic_review_payload(
                action="WITHDRAW",
                rationale="The board withdraws the standard directly",
            ),
            scenario.appeals_board,
        )
        validate_error(withdrawal, "ERR_UNAUTHORIZED", 403)
        assert scenario.get_work_item()["progress_status"] == "PUBLISHED", (
            "the role check ran before any state check, got "
            f"{scenario.get_work_item()['progress_status']}"
        )

        registration = api.create_participant(
            f.participant_payload(
                full_name="Board Clerk",
                organization="Appeals Secretariat",
                interest_category="GENERAL_INTEREST",
                employer_affiliation_code="APPSC",
            ),
            scenario.appeals_board,
        )
        validate_error(registration, "ERR_UNAUTHORIZED", 403)
        _, participants_meta = validate_paginated(
            api.list_participants(scenario.staff)
        )
        a.assert_total_count(participants_meta, 3)

        appeals, appeals_meta = validate_paginated(
            api.list_appeals(
                scenario.appeals_board, {"work_item_id": scenario.work_item_id}
            )
        )
        a.assert_total_count(appeals_meta, 1)
        assert appeals[0]["id"] == scenario.appeal_id, (
            "every GET under the API is open to the board"
        )

        decided = scenario.decide_appeal(
            decision="DENY",
            decision_rationale="The tally followed the announced schedule",
        )

        assert decided["status"] == "DENIED", (
            f"the board's own mutation lands, got {decided['status']}"
        )
        assert decided["remedy"] == "NONE", (
            f"a denial grants no remedy, got {decided['remedy']}"
        )
        a.assert_same_instant(decided["decided_at"], "2026-09-15T00:00:00Z")
        assert scenario.get_work_item()["consensus_gate"] == "OPEN", (
            "the denial releases the hold, got "
            f"{scenario.get_work_item()['consensus_gate']}"
        )
        ballot = scenario.get_ballot(consensus_ballot_id)
        assert ballot["status"] == "EVALUATED", (
            f"the cited ballot stands, got {ballot['status']}"
        )
        assert ballot["hold_reason"] == "NONE", (
            f"hold_reason expected NONE, got {ballot['hold_reason']}"
        )
        assert scenario.get_draft()["status"] == "APPROVED", (
            f"the draft stands too, got {scenario.get_draft()['status']}"
        )

    def test_only_the_secretariat_appoints_seats_moves_the_clock_or_announces(self, api):
        """
        `StandardsStaff` is the secretariat: it registers participants, forms and activates
        committees, appoints and suspends seats, approves scopes, announces and closes public
        reviews, publishes standards, runs periodic review, issues errata and drives the
        logical clock.

        At the moment of appointment the server snapshots the participant's
        `interest_category` and `employer_affiliation_code` onto the membership, records
        `appointed_at` from the logical clock

        Design: Corner/rbac/only_standards_staff_may_move_the_clock_appoint_seats_or_announce_a_review
        """
        scenario = fx.draft_ready_for_public_review(api)
        newcomer = scenario.register("p6")
        pinned_version = scenario.get_draft()["version"]

        clock_push = api.set_clock("2026-09-15T00:00:00Z", scenario.chair)
        validate_error(clock_push, "ERR_UNAUTHORIZED", 403)

        appointment = api.create_membership(
            scenario.committee_id,
            f.membership_payload(newcomer["id"]),
            scenario.chair,
        )
        validate_error(appointment, "ERR_UNAUTHORIZED", 403)
        _, seat_meta = validate_paginated(
            api.list_memberships(
                scenario.staff, {"committee_id": scenario.committee_id}
            )
        )
        a.assert_total_count(seat_meta, 3)

        announcement = api.create_public_review(
            f.public_review_payload(
                scenario.draft_id,
                pinned_version,
                start_date="2026-08-01",
                end_date="2026-09-14",
            ),
            scenario.chair,
        )
        validate_error(announcement, "ERR_UNAUTHORIZED", 403)
        _, review_meta = validate_paginated(api.list_public_reviews(scenario.staff))
        a.assert_total_count(review_meta, 0)
        untouched = scenario.get_draft()
        assert untouched["version"] == pinned_version, (
            "none of the three refusals touched the draft, got "
            f"{untouched['version']} against {pinned_version}"
        )
        assert untouched["status"] == "PUBLIC_REVIEW_READY", (
            f"the draft still awaits its review, got {untouched['status']}"
        )

        seat = scenario.appoint("p6", "m6")

        a.assert_same_instant(seat["appointed_at"], "2026-08-01T00:00:00Z")
        assert seat["status"] == "ACTIVE", (
            f"the secretariat's appointment lands, got {seat['status']}"
        )

        review = scenario.announce_public_review(
            start_date="2026-08-01",
            end_date="2026-09-14",
            expected_draft_version=pinned_version,
        )

        assert review["status"] == "OPEN", (
            f"the identical announcement lands for staff, got {review['status']}"
        )
        assert review["duration_days"] == 45, (
            f"duration_days expected 45, got {review['duration_days']}"
        )
        assert scenario.get_draft()["status"] == "PUBLIC_REVIEW", (
            f"the draft goes out for comment, got {scenario.get_draft()['status']}"
        )


class TestTheUnseatedParticipant:
    """A participant with no seat has a voice but no vote."""

    def test_a_public_commenter_may_comment_but_may_not_cast(self, api):
        """
        `CommitteeMember` is the capacity of a participant who holds a seat: it is the only
        role, alongside `CommitteeChair`, that may cast, change or withdraw a vote

        `PublicCommenter` is the capacity of a participant with no committee seat, taking part
        through the public review period, patent disclosure, appeals and maintenance requests.

        Design: Corner/rbac/an_unseated_participant_may_comment_but_may_not_vote
        """
        scenario = fx.open_subcommittee_ballot(api)
        outsider = scenario.register("p6")

        cast = api.cast_vote(
            scenario.ballot_id,
            f.vote_payload(scenario.mid("m3")),
            scenario.commenter("p6"),
        )
        validate_error(cast, "ERR_UNAUTHORIZED", 403)

        votes, vote_meta = validate_paginated(
            api.list_votes(scenario.staff, {"ballot_id": scenario.ballot_id})
        )
        a.assert_total_count(vote_meta, 0)
        assert votes == [], f"the refused cast stored nothing, got {votes}"
        ballot = scenario.get_ballot()
        assert ballot["returned_count"] == 0, (
            f"returned_count expected 0, got {ballot['returned_count']}"
        )
        assert ballot["eligible_voter_count"] == 3, (
            "the outsider was never in the eligible set, got "
            f"{ballot['eligible_voter_count']}"
        )

        comment = validate_success(
            api.create_comment(
                f.committee_comment_payload(
                    outsider["id"],
                    scenario.draft_id,
                    comment_type="TECHNICAL",
                    comment_text="Clause 30 should reference the coating standard",
                    clause_reference="30",
                ),
                scenario.commenter("p6"),
            ),
            201,
        )

        assert comment["submitter_participant_id"] == outsider["id"], (
            "the unseated participant comments in their own name, got "
            f"{comment['submitter_participant_id']}"
        )
        assert comment["status"] == "OPEN", (
            f"the comment opens OPEN, got {comment['status']}"
        )
        assert comment["is_substantive"] is True, (
            f"a technical comment is substantive, got {comment['is_substantive']}"
        )
        assert comment["public_review_id"] is None, (
            "a committee comment belongs to no review, got "
            f"{comment['public_review_id']}"
        )
        assert comment["draft_id"] == scenario.draft_id, (
            "the comment attaches to the revision under ballot"
        )
