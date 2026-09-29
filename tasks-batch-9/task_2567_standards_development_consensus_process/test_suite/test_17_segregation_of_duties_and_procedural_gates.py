"""
The two segregation-of-duties errors that exist only to police the chair, and the
gates that will not let the next step run until what came before has been
answered: an unconsidered negative, an undisposed public review, and a
procedural gate that is a fixed point rather than a toggle.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx


def _ballot_carrying_the_chairs_own_negative(api):
    """
    The subcommittee ballot closed with all three seats returned, the chair alone
    voting NEGATIVE with an explanation, so the chair's own objection is the one
    pending negative on the ballot.
    """
    scenario = fx.open_subcommittee_ballot(api)
    scenario.cast_negative(
        "m1",
        comment_text="Clause 12 torque ceiling is unsafe for cast fittings",
        clause_reference="12",
        vote_key="v1",
    )
    scenario.cast("m2", "AFFIRMATIVE", vote_key="v2")
    scenario.cast("m3", "AFFIRMATIVE", vote_key="v3")
    scenario.close_ballot()
    return scenario


class TestTheChairWearsTwoHatsOnOneVote:
    """The chair may not rule on their own objection, but may retract it."""

    def test_a_chair_may_not_rule_on_their_own_negative_but_may_withdraw_it(self, api):
        """
        `PERSUASIVE` and `NON_PERSUASIVE` require that the caller's identifier equal the
        `chair_participant_id` of the committee sponsoring the draft's work item, else
        `ERR_NOT_COMMITTEE_CHAIR`, and further require that the caller not be the participant
        behind the vote's own seat: a chair who cast a negative may not rule on it, and the
        attempt is refused with `ERR_SELF_ADJUDICATION`. `WITHDRAWN_BY_VOTER` is the opposite
        — only the participant who cast the negative may choose it

        `WITHDRAWN_BY_VOTER` moves `adjudication_status` to `WITHDRAWN_BY_VOTER` and rewrites
        `position` from `NEGATIVE` to `ABSTAIN`, so the objection leaves the approval base
        entirely.

        Design: Corner/rbac/a_chair_may_not_rule_on_their_own_negative_but_may_withdraw_it
        """
        scenario = _ballot_carrying_the_chairs_own_negative(api)
        evaluated = scenario.get_ballot()
        assert evaluated["consensus_result"] == "APPROVED_PENDING_NEGATIVES", (
            "the ballot passed as cast but carries an unanswered objection, got "
            f"{evaluated['consensus_result']}"
        )
        a.assert_pct(evaluated["provisional_approval_pct"], 66.7)
        assert evaluated["pending_negative_count"] == 1, (
            f"pending_negative_count expected 1, got {evaluated['pending_negative_count']}"
        )
        assert scenario.get_draft()["status"] == "COMMENT_RESOLUTION", (
            f"the draft waits on the objection, got {scenario.get_draft()['status']}"
        )

        own_ruling = api.adjudicate_vote(
            scenario.votes["v1"]["id"],
            f.adjudication_payload(
                resolution="NON_PERSUASIVE",
                adjudication_rationale="On reflection the chair is unpersuaded by the chair",
            ),
            scenario.chair,
        )
        validate_error(own_ruling, "ERR_SELF_ADJUDICATION", 403)

        untouched = scenario.get_vote("v1")
        assert untouched["adjudication_status"] == "PENDING", (
            f"the objection is still unanswered, got {untouched['adjudication_status']}"
        )
        assert untouched["position"] == "NEGATIVE", (
            f"position expected NEGATIVE, got {untouched['position']}"
        )
        assert scenario.get_ballot()["final_approval_pct"] is None, (
            "no final reading was taken, got "
            f"{scenario.get_ballot()['final_approval_pct']}"
        )

        scenario.adjudicate(
            "v1",
            "WITHDRAWN_BY_VOTER",
            headers=scenario.member("p1"),
            adjudication_rationale="The chair withdraws the negative after the test report",
        )

        withdrawn = scenario.get_vote("v1")
        assert withdrawn["adjudication_status"] == "WITHDRAWN_BY_VOTER", (
            "the resolution reserved for the voter is open to the chair as voter, got "
            f"{withdrawn['adjudication_status']}"
        )
        assert withdrawn["position"] == "ABSTAIN", (
            f"the retraction rewrites the position, got {withdrawn['position']}"
        )
        ballot = scenario.get_ballot()
        a.assert_seat_ledger(
            ballot,
            affirmative=2,
            negative=0,
            abstain=1,
            returned=3,
            not_returned=0,
            eligible=3,
        )
        a.assert_pct(ballot["final_approval_pct"], 100.0)
        a.assert_pct(ballot["provisional_approval_pct"], 66.7)
        assert ballot["pending_negative_count"] == 0, (
            f"pending_negative_count expected 0, got {ballot['pending_negative_count']}"
        )
        draft = scenario.get_draft()
        assert draft["status"] == "PUBLIC_REVIEW_READY", (
            f"the answered draft advances, got {draft['status']}"
        )
        assert draft["recirculation_required"] is False, (
            f"recirculation_required expected false, got {draft['recirculation_required']}"
        )
        work_item = scenario.get_work_item()
        assert work_item["unresolved_negative_count"] == 0, (
            f"unresolved_negative_count expected 0, got {work_item['unresolved_negative_count']}"
        )
        assert work_item["consensus_gate"] == "OPEN", (
            f"the gate reopens, got {work_item['consensus_gate']}"
        )


def _review_whose_dispositions_the_chair_wrote(api):
    """
    A public review over 2026-08-01 .. 2026-09-14 that drew two comments, closed at
    2026-09-15 and dispositioned entirely by the sponsoring chair, so it sits in
    DISPOSITION_DRAFTED at 100.0 completeness.
    """
    scenario = fx.draft_ready_for_public_review(api)
    scenario.announce_public_review(start_date="2026-08-01", end_date="2026-09-14")
    technical = scenario.submit_public_comment(
        "p2",
        comment_type="TECHNICAL",
        comment_text="The torque band in clause 9 is too wide for cast fittings",
        clause_reference="9",
    )
    general = scenario.submit_public_comment(
        "p3",
        comment_type="GENERAL",
        comment_text="The scope statement should say which fittings are excluded",
        clause_reference="1",
    )
    scenario.set_clock("2026-09-15T00:00:00Z")
    scenario.close_public_review()
    scenario.dispose_comment(
        technical["id"],
        disposition="ACCEPTED_WITH_MODIFICATION",
        disposition_rationale="A tolerance band is added with a narrower range",
    )
    scenario.dispose_comment(
        general["id"],
        disposition="REJECTED",
        disposition_rationale="The scope statement already excludes cast fittings",
    )
    return scenario


class TestTheAuthorMayNotSignOff:
    """The chair role is admitted to the endpoint and then refused by identity."""

    def test_the_chair_who_wrote_the_dispositions_may_not_approve_them(self, api):
        """
        Either the secretariat or a committee chair may approve, the review must be in
        `DISPOSITION_DRAFTED` (else `ERR_INVALID_PUBLIC_REVIEW_STATE`), its
        `disposition_completeness_pct` must be exactly 100.0 (else
        `ERR_DISPOSITION_INCOMPLETE`), and the caller's identifier must

        differ from the `chair_participant_id` of the committee sponsoring the reviewed
        draft's work item — whoever wrote the dispositions may not sign them off, and a chair
        who tries is refused with `ERR_DISPOSITION_APPROVER_CONFLICT`.

        Design: Corner/rbac/the_chair_who_wrote_the_dispositions_may_not_approve_them
        """
        scenario = _review_whose_dispositions_the_chair_wrote(api)
        drafted = scenario.get_public_review()
        assert drafted["status"] == "DISPOSITION_DRAFTED", (
            f"the record is complete and awaiting sign-off, got {drafted['status']}"
        )
        a.assert_pct(drafted["disposition_completeness_pct"], 100.0)

        self_approval = api.approve_disposition(
            scenario.public_review_id, scenario.chair
        )
        validate_error(self_approval, "ERR_DISPOSITION_APPROVER_CONFLICT", 403)

        refused = scenario.get_public_review()
        assert refused["status"] == "DISPOSITION_DRAFTED", (
            "the refusal left the review awaiting sign-off, got "
            f"{refused['status']}"
        )
        assert refused["disposition_approved_by_participant_id"] is None, (
            "no approver was recorded, got "
            f"{refused['disposition_approved_by_participant_id']}"
        )
        assert refused["disposition_approved_at"] is None, (
            f"no timestamp was written, got {refused['disposition_approved_at']}"
        )

        approved = scenario.approve_disposition()

        assert approved["status"] == "DISPOSITION_APPROVED", (
            "the identical call from another quarter lands, got "
            f"{approved['status']}"
        )
        a.assert_same_instant(approved["disposition_approved_at"], "2026-09-15T00:00:00Z")
        a.assert_pct(approved["disposition_completeness_pct"], 100.0)
        assert scenario.get_draft()["status"] == "PUBLIC_REVIEW_CLOSED", (
            f"the approval moves no draft, got {scenario.get_draft()['status']}"
        )


class TestARevisionMayNotBuryAnObjection:
    """The draft state allows the supersession; the aggregate over votes forbids it."""

    def test_superseding_a_draft_holding_a_pending_negative_is_blocked(self, api):
        """
        From `COMMENT_RESOLUTION` or from `PUBLIC_REVIEW_CLOSED`, the predecessor may be
        superseded only when no vote on any of its ballots still has `adjudication_status`
        `PENDING`; a draft holding unconsidered negatives cannot be quietly replaced, and the
        attempt is refused with `ERR_NEGATIVES_NOT_CONSIDERED`.

        Design: Corner/validations/superseding_a_draft_that_still_holds_a_pending_negative_is_blocked
        """
        scenario = fx.evaluated_ballot_with_pending_negative(api)
        predecessor = scenario.get_draft()
        assert predecessor["status"] == "COMMENT_RESOLUTION", (
            "the draft sits in a status the supersession guard does allow, got "
            f"{predecessor['status']}"
        )

        response = api.create_draft(
            scenario.work_item_id,
            f.draft_payload(
                total_clause_count=40,
                changed_clause_count=6,
                prior_draft_id=scenario.draft_id,
                summary="Revision 2 — quietly reworked clause 12",
            ),
            scenario.chair,
        )
        validate_error(response, "ERR_NEGATIVES_NOT_CONSIDERED", 409)

        drafts, meta = validate_paginated(
            api.list_drafts(scenario.staff, {"work_item_id": scenario.work_item_id})
        )
        a.assert_total_count(meta, 1)
        after = scenario.get_draft()
        assert after["status"] == "COMMENT_RESOLUTION", (
            f"the predecessor was not abandoned, got {after['status']}"
        )
        assert after["revision_number"] == 1, (
            f"revision_number expected 1, got {after['revision_number']}"
        )
        a.assert_version_unchanged(predecessor, after)
        assert scenario.get_vote("v3")["adjudication_status"] == "PENDING", (
            "the objection is still unanswered, got "
            f"{scenario.get_vote('v3')['adjudication_status']}"
        )
        work_item = scenario.get_work_item()
        assert work_item["unresolved_negative_count"] == 1, (
            f"unresolved_negative_count expected 1, got {work_item['unresolved_negative_count']}"
        )
        assert work_item["consensus_gate"] == "BLOCKED", (
            f"consensus_gate expected BLOCKED, got {work_item['consensus_gate']}"
        )
        assert work_item["progress_status"] == "IN_DEVELOPMENT", (
            f"progress_status expected IN_DEVELOPMENT, got {work_item['progress_status']}"
        )


class TestTheConsensusBodyWaitsForTheDisposition:
    """A review that merely exists is not a review that has been answered."""

    def test_a_consensus_ballot_before_the_disposition_is_approved_is_blocked(self, api):
        """
        A consensus-body ballot carries one further gate: the most recently created public
        review on that draft must have reached `DISPOSITION_APPROVED`, or the request is
        refused with `ERR_PUBLIC_REVIEW_NOT_APPROVED` — the consensus body may not vote on a
        text whose public comments have not been formally disposed of.

        Design: Corner/validations/a_consensus_body_ballot_before_the_disposition_is_approved_is_blocked
        """
        scenario = fx.draft_ready_for_public_review(api)
        subcommittee_ballot_id = scenario.ballot_id
        scenario.announce_public_review(start_date="2026-08-01", end_date="2026-09-14")
        scenario.submit_public_comment(
            "p2",
            comment_type="TECHNICAL",
            comment_text="The torque band in clause 9 is too wide for cast fittings",
            clause_reference="9",
        )
        scenario.set_clock("2026-09-15T00:00:00Z")
        scenario.close_public_review()
        assert scenario.get_draft()["status"] == "PUBLIC_REVIEW_CLOSED", (
            "the draft is in a status that does accept a consensus ballot, got "
            f"{scenario.get_draft()['status']}"
        )

        response = api.create_ballot(
            f.ballot_payload(
                scenario.draft_id,
                scenario.committee_id,
                ballot_kind="CONSENSUS_BODY",
                opens_at="2026-09-15T00:00:00Z",
                closes_at="2026-10-15T00:00:00Z",
            ),
            scenario.chair,
        )
        validate_error(response, "ERR_PUBLIC_REVIEW_NOT_APPROVED", 409)

        review = scenario.get_public_review()
        assert review["status"] == "CLOSED", (
            "the review is closed but its comment is unanswered, got "
            f"{review['status']}"
        )
        a.assert_comment_ledger(
            review,
            comment_count=1,
            disposed_count=0,
            unresolved_count=1,
            completeness_pct=0.0,
        )
        assert scenario.get_draft()["status"] == "PUBLIC_REVIEW_CLOSED", (
            f"the refusal moved no draft, got {scenario.get_draft()['status']}"
        )
        ballots, meta = validate_paginated(
            api.list_ballots(scenario.staff, {"draft_id": scenario.draft_id})
        )
        a.assert_total_count(meta, 1)
        assert ballots[0]["id"] == subcommittee_ballot_id, (
            "only the subcommittee ballot exists on this revision"
        )


class TestTheGateIsAFixedPointNotAToggle:
    """Two blockers held it down; clearing one of them changes nothing."""

    def test_restoring_the_committee_leaves_the_gate_blocked_by_the_draft(self, api):
        """
        It is a fixed point over three independent blockers living on other resources, and it
        is recomputed from scratch on every request that touches one of them rather than being
        incrementally toggled — so clearing one blocker while another still holds leaves the
        gate `BLOCKED`. The gate is `BLOCKED` when any of the following holds: some appeal on
        the work item has `status` `FILED` or `ACCEPTED_FOR_REVIEW`; some draft of the work
        item has `status` `COMMENT_RESOLUTION`; or the sponsoring committee's `status` is
        anything other than `ACTIVE`, or its `balance_status` is anything other than
        `BALANCED`.

        Design: Corner/calculations/clearing_one_gate_blocker_while_another_holds_leaves_the_gate_blocked
        """
        scenario = fx.evaluated_ballot_with_pending_negative(api)
        assert scenario.get_draft()["status"] == "COMMENT_RESOLUTION", (
            "the unanswered negative is the first blocker"
        )
        assert scenario.get_work_item()["consensus_gate"] == "BLOCKED", (
            "the gate is already shut on the draft alone"
        )

        scenario.patch_membership("m2", status="SUSPENDED")

        suspended = scenario.get_committee()
        assert suspended["status"] == "SUSPENDED", (
            f"the second blocker is now in place, got {suspended['status']}"
        )
        assert suspended["balance_status"] == "UNBALANCED", (
            f"balance_status expected UNBALANCED, got {suspended['balance_status']}"
        )
        assert scenario.get_work_item()["consensus_gate"] == "BLOCKED", (
            "two blockers hold the gate shut"
        )

        scenario.patch_membership("m2", status="ACTIVE")

        restored = scenario.get_committee()
        assert restored["balance_status"] == "BALANCED", (
            f"the roster balances again, got {restored['balance_status']}"
        )
        assert restored["status"] == "SUSPENDED", (
            "but a seat edit never re-activates a committee on its own, got "
            f"{restored['status']}"
        )
        assert scenario.get_work_item()["consensus_gate"] == "BLOCKED", (
            "the gate is unmoved, got "
            f"{scenario.get_work_item()['consensus_gate']}"
        )

        scenario.activate_committee()

        reactivated = scenario.get_committee()
        assert reactivated["status"] == "ACTIVE", (
            f"the committee blocker is now cleared, got {reactivated['status']}"
        )
        work_item = scenario.get_work_item()
        assert work_item["consensus_gate"] == "BLOCKED", (
            "the COMMENT_RESOLUTION draft still holds the gate, got "
            f"{work_item['consensus_gate']}"
        )
        assert work_item["unresolved_negative_count"] == 1, (
            f"unresolved_negative_count expected 1, got {work_item['unresolved_negative_count']}"
        )

        scenario.adjudicate("v3", "NON_PERSUASIVE")

        assert scenario.get_draft()["status"] == "PUBLIC_REVIEW_READY", (
            "the last blocker is answered, got "
            f"{scenario.get_draft()['status']}"
        )
        cleared = scenario.get_work_item()
        assert cleared["unresolved_negative_count"] == 0, (
            f"unresolved_negative_count expected 0, got {cleared['unresolved_negative_count']}"
        )
        assert cleared["consensus_gate"] == "OPEN", (
            f"only now does the gate open, got {cleared['consensus_gate']}"
        )
