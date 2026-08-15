"""Protocol committee review: revision cycles, FCR quorum, tally validity,
terminal WITHDRAWN lockdown, segregation of duties, and version increments
(PRD §2.5, §2.8, §2.10, §3.3).
"""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    assert_protocol,
    assert_protocol_reviewer,
    create_draft_protocol,
    create_fcr_protocol_in_review,
    get_success_data,
    make_admin_headers,
    parse_instant,
    record_dmr_decision,
    submit_protocol,
    validate_error,
)
from test_helpers.fixtures import record_fcr_decisions


class TestReviewRevisionCycle:
    def test_require_modifications_returns_to_draft_and_resets_reviewers(self, api):
        """PRD §3.3: "a designated member voting `REQUIRE_MODIFICATIONS` sends a
        `DMR` protocol back to `DRAFT`, and under full committee a majority
        voting `REQUIRE_MODIFICATIONS` with no `WITHHOLD` does the same. In
        both paths, every reviewer row's `decision` is reset to `PENDING` for
        the next round."

        Design: Difficulty/non_linear_state_machine/protocol_review_revision_cycle
        """
        scenario = create_draft_protocol(review_path="DMR")
        protocol = scenario["protocol"]
        inv_headers = scenario["investigator_headers"]

        submit_protocol(protocol["id"], scenario["investigator"]["id"])
        returned = record_dmr_decision(protocol["id"], "REQUIRE_MODIFICATIONS")
        assert returned["status"] == "DRAFT", (
            f"REQUIRE_MODIFICATIONS must return the protocol to DRAFT, got "
            f"{returned['status']}"
        )

        reviewers = get_success_data(
            api_client.list_protocol_reviewers(protocol["id"], ADMIN)
        )
        assert len(reviewers) >= 1, "expected reviewer rows to be listed"
        for row in reviewers:
            assert_protocol_reviewer(row)
            assert row["decision"] == "PENDING", (
                "every reviewer row's decision is reset to PENDING for the "
                "next round"
            )

        resubmitted = get_success_data(api_client.submit_protocol(
            protocol["id"], inv_headers,
        ))
        assert resubmitted["status"] == "DMR_REVIEW", (
            "resubmission from DRAFT re-enters DMR_REVIEW"
        )

    def test_revision_cycle_completes_with_approval_and_version_steps(self, api):
        """PRD §3.3: "Approval from `DMR_REVIEW` requires the designated member
        to vote `APPROVE` ... Either approval sets `approved_at` to the
        current clock time, computes `expires_at` as exactly three years after
        `approved_at`, and moves the protocol to `APPROVED`." PRD §2.5:
        "`version` (integer): a system-managed integer that increments on
        every mutation of the resource, including mutations produced by
        cascading side effects and recomputed fields."

        Design: Difficulty/non_linear_state_machine/protocol_review_revision_cycle
        """
        scenario = create_draft_protocol(review_path="DMR")
        protocol = scenario["protocol"]
        v_create = protocol["version"]

        submitted = submit_protocol(protocol["id"], scenario["investigator"]["id"])
        assert submitted["version"] == v_create + 1, "submit increments version"

        returned = record_dmr_decision(protocol["id"], "REQUIRE_MODIFICATIONS")
        assert returned["version"] == submitted["version"] + 1

        resubmitted = submit_protocol(protocol["id"], scenario["investigator"]["id"])
        assert resubmitted["version"] == returned["version"] + 1

        approved = record_dmr_decision(protocol["id"], "APPROVE")
        assert_protocol(approved)
        assert approved["status"] == "APPROVED"
        assert approved["version"] == resubmitted["version"] + 1, (
            "version increments on every loop transition"
        )
        approved_at = parse_instant(approved["approved_at"])
        expires_at = parse_instant(approved["expires_at"])
        assert expires_at.year == approved_at.year + 3
        assert (expires_at.month, expires_at.day) == (
            approved_at.month, approved_at.day,
        ), "expires_at is exactly three years after approved_at"


class TestFcrReview:
    def test_fcr_quorum_two_approves_one_modifications_approves(self, api):
        """PRD §3.3: "An `FCR` protocol lands in `FCR_REVIEW`, and the system
        creates three reviewer assignments of `reviewer_kind`
        `COMMITTEE_MEMBER`, each with `decision` `PENDING`." and "approval
        from `FCR_REVIEW` requires at least two of the three committee members
        to vote `APPROVE` with no member voting `WITHHOLD`. Either approval
        sets `approved_at` to the current clock time, computes `expires_at` as
        exactly three years after `approved_at`, and moves the protocol to
        `APPROVED`."

        Design: Corner/state_machines/fcr_quorum_two_approves_with_one_modifications
        """
        scenario = create_fcr_protocol_in_review(species="RAT", max_animals=10)
        protocol = scenario["protocol"]
        assert protocol["status"] == "FCR_REVIEW"

        reviewers = get_success_data(
            api_client.list_protocol_reviewers(protocol["id"], ADMIN)
        )
        assert len(reviewers) == 3, (
            f"FCR submit must create 3 COMMITTEE_MEMBER reviewers, got "
            f"{len(reviewers)}"
        )
        for row in reviewers:
            assert row["reviewer_kind"] == "COMMITTEE_MEMBER"
            assert row["decision"] == "PENDING"

        decided = record_fcr_decisions(
            protocol["id"], "APPROVE", "APPROVE", "REQUIRE_MODIFICATIONS",
        )
        assert decided["status"] == "APPROVED", (
            "2 APPROVE + 1 REQUIRE_MODIFICATIONS with no WITHHOLD approves"
        )
        approved_at = parse_instant(decided["approved_at"])
        expires_at = parse_instant(decided["expires_at"])
        assert expires_at.year == approved_at.year + 3
        assert (expires_at.month, expires_at.day) == (
            approved_at.month, approved_at.day,
        )

    def test_fcr_any_withhold_withdraws_despite_approves(self, api):
        """PRD §3.3: "Withholding: a designated member voting `WITHHOLD`, or
        any single committee member voting `WITHHOLD`, moves the protocol to
        `WITHDRAWN`, a terminal state."

        Design: Corner/state_machines/fcr_any_withhold_withdraws
        """
        scenario = create_fcr_protocol_in_review(species="RAT", max_animals=10)
        protocol = scenario["protocol"]

        decided = record_fcr_decisions(
            protocol["id"], "APPROVE", "APPROVE", "WITHHOLD",
        )
        assert decided["status"] == "WITHDRAWN", (
            "a single WITHHOLD vetoes even with 2 APPROVE votes"
        )


class TestVoteTallyValidity:
    def test_dmr_wrong_reviewer_kind_rejected(self, api):
        """PRD §3.3: "The tally must fit the review path: for a `DMR` protocol
        the payload must carry exactly one decision for the single
        `DESIGNATED_MEMBER` row; for an `FCR` protocol it must carry decisions
        for all three `COMMITTEE_MEMBER` rows. A payload that does not form a
        valid tally for the protocol's path is rejected with
        `ERR_INVALID_VOTE_TALLY` (HTTP 422)."

        Design: Corner/state_machines/dmr_wrong_reviewer_kind_rejected
        """
        scenario = create_draft_protocol(review_path="DMR")
        protocol = scenario["protocol"]
        submit_protocol(protocol["id"], scenario["investigator"]["id"])

        # A second, FCR protocol supplies COMMITTEE_MEMBER reviewer rows. A
        # decision referencing one of those rows is not "exactly one decision
        # for the single DESIGNATED_MEMBER row" of the DMR protocol: the
        # referenced row exists (passes the existence check) but does not fit
        # the protocol's review path.
        other = create_fcr_protocol_in_review()
        committee = get_success_data(
            api_client.list_protocol_reviewers(other["protocol"]["id"], ADMIN)
        )
        foreign_member_id = committee[0]["id"]

        resp = api_client.record_review_decisions(
            protocol["id"],
            {"decisions": [
                {"reviewer_id": foreign_member_id, "decision": "APPROVE"},
            ]},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_VOTE_TALLY)

        current = get_success_data(api_client.get_protocol(protocol["id"], ADMIN))
        assert current["status"] == "DMR_REVIEW", (
            "a rejected tally leaves the protocol in DMR_REVIEW"
        )


class TestWithdrawnTerminalLockdown:
    def test_withhold_withdraws_and_blocks_further_transitions(self, api):
        """PRD §3.3: "a designated member voting `WITHHOLD` ... moves the
        protocol to `WITHDRAWN`, a terminal state." PRD §2.8: "State legality
        — the target resource is in a state from which the requested
        transition exists (`ERR_INVALID_STATE`, 409)."

        Design: Corner/state_machines/protocol_terminal_withdrawn_lockdown
        """
        scenario = create_draft_protocol(review_path="DMR")
        protocol = scenario["protocol"]
        submit_protocol(protocol["id"], scenario["investigator"]["id"])

        withdrawn = record_dmr_decision(protocol["id"], "WITHHOLD")
        assert withdrawn["status"] == "WITHDRAWN"

        resp = api_client.submit_protocol(
            protocol["id"], scenario["investigator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestSegregationOfDuties:
    def test_investigator_cannot_record_review_on_own_protocol(self, api):
        """PRD §2.10: "an investigator may not record committee review
        decisions on their own protocol: when review decisions are recorded,
        the acting `X-User-ID` must not equal the protocol's owning
        `investigator_id`." and "Either violation is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/validations/segregation_of_duties_pi_cannot_review_own
        """
        scenario = create_draft_protocol(review_path="DMR")
        protocol = scenario["protocol"]
        submit_protocol(protocol["id"], scenario["investigator"]["id"])

        # A well-formed, valid tally for the protocol's own DESIGNATED_MEMBER
        # row, so segregation of duties (priority 8, before vote-tally
        # validity at 15) is the surfaced failure.
        reviewers = get_success_data(
            api_client.list_protocol_reviewers(protocol["id"], ADMIN)
        )
        designated_id = reviewers[0]["id"]

        resp = api_client.record_review_decisions(
            protocol["id"],
            {"decisions": [
                {"reviewer_id": designated_id, "decision": "APPROVE"},
            ]},
            make_admin_headers(scenario["investigator"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        current = get_success_data(api_client.get_protocol(protocol["id"], ADMIN))
        assert current["status"] == "DMR_REVIEW"


class TestProtocolVersioning:
    def test_version_increments_on_every_mutation(self, api):
        """PRD §2.5: "`version` (integer): a system-managed integer that
        increments on every mutation of the resource, including mutations
        produced by cascading side effects and recomputed fields." PRD §3.3:
        "A successful submission increments the protocol's `version`" and each
        review outcome "increments the protocol's `version`".

        Design: Corner/complexity_layers/version_increments_on_every_mutation
        """
        # Capture the version at the moment of each mutation.
        scenario = create_draft_protocol(review_path="DMR")
        protocol = scenario["protocol"]
        v1 = protocol["version"]
        assert isinstance(v1, int)

        submitted = submit_protocol(protocol["id"], scenario["investigator"]["id"])
        assert submitted["version"] == v1 + 1, (
            f"submit must increment version by 1: {v1} -> {submitted['version']}"
        )

        approved = record_dmr_decision(protocol["id"], "APPROVE")
        assert approved["version"] == submitted["version"] + 1, (
            f"review decision must increment version by 1: "
            f"{submitted['version']} -> {approved['version']}"
        )
