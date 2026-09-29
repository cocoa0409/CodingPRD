"""
How wide one cascade hop reaches, and which of two edges it picks. A close fans
out across every sibling vote in the same request; the draft it then moves is
routed by whether a negative is still pending; and a comment disposition only
bubbles its review up once the last one is answered.
"""

from prd_bench_local_runner.testing import validate_paginated

from test_helpers import assertions as a
from test_helpers import fixtures as fx


def _five_seat_committee(api):
    """Five voting seats in five distinct categories on five distinct employers."""
    scenario = fx.Scenario(api)
    scenario.register_core()
    scenario.register("p4", interest_category="REGULATORY")
    scenario.register("p5", interest_category="ACADEMIC")
    scenario.create_committee("p1")
    for participant_key, seat_key in (
        ("p1", "m1"),
        ("p2", "m2"),
        ("p3", "m3"),
        ("p4", "m4"),
        ("p5", "m5"),
    ):
        scenario.appoint(participant_key, seat_key)
    scenario.activate_committee()
    return scenario


class TestCloseFansOutAcrossSiblingVotes:
    """Hop two touches every negative sibling and no affirmative one."""

    def test_close_flips_both_negatives_and_leaves_the_affirmatives_alone(self, api):
        """
        Hop two moves every cast negative vote on the ballot from `adjudication_status`
        `NOT_APPLICABLE` to `PENDING`.

        Design: Corner/state_machines/ballot_close_cascades_down_to_every_negative_vote_on_the_ballot
        """
        scenario = _five_seat_committee(api)
        a.assert_voting_balance(
            scenario.get_committee(),
            balance_status="BALANCED",
            active_member_count=5,
            distinct_category_count=5,
            dominance_pct=20.0,
        )
        scenario.propose_work_item("p1")
        scenario.approve_scope(designation="STD-1400")
        scenario.add_draft(total_clause_count=40, changed_clause_count=0)
        scenario.open_ballot()
        scenario.cast("m1", "AFFIRMATIVE", vote_key="v1")
        scenario.cast("m2", "AFFIRMATIVE", vote_key="v2")
        scenario.cast("m3", "AFFIRMATIVE", vote_key="v3")
        scenario.cast_negative("m4", vote_key="v4")
        scenario.cast_negative("m5", vote_key="v5")

        scenario.close_ballot()

        ballot = scenario.get_ballot()
        assert ballot["status"] == "EVALUATED", (
            f"status expected EVALUATED, got {ballot['status']}"
        )
        a.assert_seat_ledger(
            ballot,
            affirmative=3,
            negative=2,
            abstain=0,
            returned=5,
            not_returned=0,
            eligible=5,
        )
        a.assert_pct(ballot["return_rate_pct"], 100.0)
        a.assert_pct(ballot["required_return_rate_pct"], 50.0)
        a.assert_pct(ballot["required_approval_pct"], 50.1)
        a.assert_pct(ballot["provisional_approval_pct"], 60.0)
        assert ballot["final_approval_pct"] is None, (
            f"the close leaves the final reading null, got {ballot['final_approval_pct']}"
        )
        assert ballot["consensus_result"] == "APPROVED_PENDING_NEGATIVES", (
            f"consensus_result expected APPROVED_PENDING_NEGATIVES, got {ballot['consensus_result']}"
        )
        assert ballot["pending_negative_count"] == 2, (
            f"pending_negative_count expected 2, got {ballot['pending_negative_count']}"
        )

        for vote_key in ("v4", "v5"):
            assert scenario.get_vote(vote_key)["adjudication_status"] == "PENDING", (
                f"the negative {vote_key} was moved to PENDING by the same close"
            )
        for vote_key in ("v1", "v2", "v3"):
            assert (
                scenario.get_vote(vote_key)["adjudication_status"] == "NOT_APPLICABLE"
            ), f"the affirmative {vote_key} was not dragged into the adjudication dimension"

        objections, meta = validate_paginated(
            api.list_comments(scenario.staff, {"source_type": "BALLOT_NEGATIVE"})
        )
        a.assert_total_count(meta, 2)
        assert {row["source_vote_id"] for row in objections} == {
            scenario.get_vote("v4")["id"],
            scenario.get_vote("v5")["id"],
        }, "one objection stands behind each negative"

        draft = scenario.get_draft()
        assert draft["status"] == "COMMENT_RESOLUTION", (
            f"draft status expected COMMENT_RESOLUTION, got {draft['status']}"
        )
        assert draft["unresolved_negative_count"] == 2, (
            f"draft unresolved_negative_count expected 2, got {draft['unresolved_negative_count']}"
        )
        work_item = scenario.get_work_item()
        assert work_item["unresolved_negative_count"] == 2, (
            "the count is re-derived onto the work item, got "
            f"{work_item['unresolved_negative_count']}"
        )
        assert work_item["consensus_gate"] == "BLOCKED", (
            f"consensus_gate expected BLOCKED, got {work_item['consensus_gate']}"
        )
        for seat_key in ("m1", "m2", "m3", "m4", "m5"):
            assert scenario.get_membership(seat_key)["missed_ballot_streak"] == 0, (
                f"seat {seat_key} returned, so its streak stays at 0"
            )


class TestRoutingByPendingNegative:
    """The same passing arithmetic routes the draft two different ways."""

    def test_pending_negative_diverts_the_draft_then_releases_it(self, api):
        """
        if the evaluated ballot leaves any pending negative, the draft goes to
        `COMMENT_RESOLUTION` regardless of `consensus_result` — from `SUBCOMMITTEE_BALLOT`
        or from `CONSENSUS_BALLOT` alike. Only when zero negatives are pending do the
        other edges apply.

        Design: Corner/state_machines/close_cascade_routes_the_draft_to_comment_resolution_only_while_a_negative_is_pending
        """
        scenario = fx.evaluated_ballot_with_pending_negative(api)
        at_close = scenario.get_ballot()
        a.assert_pct(at_close["provisional_approval_pct"], 66.7)
        assert at_close["consensus_result"] == "APPROVED_PENDING_NEGATIVES", (
            f"consensus_result expected APPROVED_PENDING_NEGATIVES, got {at_close['consensus_result']}"
        )
        assert at_close["pending_negative_count"] == 1, (
            f"pending_negative_count expected 1, got {at_close['pending_negative_count']}"
        )
        assert scenario.get_draft()["status"] == "COMMENT_RESOLUTION", (
            "a passing ballot still diverts the draft while a negative is pending"
        )
        assert scenario.get_work_item()["consensus_gate"] == "BLOCKED", (
            "the diverted draft shuts the gate"
        )

        scenario.adjudicate("v3", "NON_PERSUASIVE")

        vote = scenario.get_vote("v3")
        assert vote["adjudication_status"] == "NON_PERSUASIVE", (
            f"adjudication_status expected NON_PERSUASIVE, got {vote['adjudication_status']}"
        )
        assert vote["adjudicated_by_participant_id"] == scenario.pid("p1"), (
            "the acting chair is recorded as the adjudicator"
        )
        after = scenario.get_ballot()
        a.assert_pct(after["final_approval_pct"], 66.7)
        assert after["consensus_result"] == "APPROVED", (
            f"consensus_result expected APPROVED, got {after['consensus_result']}"
        )
        draft = scenario.get_draft()
        assert draft["status"] == "PUBLIC_REVIEW_READY", (
            "with no persuasive ruling the released draft goes forward, got "
            f"{draft['status']}"
        )
        assert draft["recirculation_required"] is False, (
            "a non-persuasive ruling never demands recirculation, got "
            f"{draft['recirculation_required']}"
        )
        assert draft["unresolved_negative_count"] == 0, (
            f"unresolved_negative_count expected 0, got {draft['unresolved_negative_count']}"
        )
        work_item = scenario.get_work_item()
        assert work_item["unresolved_negative_count"] == 0, (
            f"the work item count expected 0, got {work_item['unresolved_negative_count']}"
        )
        assert work_item["consensus_gate"] == "OPEN", (
            f"consensus_gate expected OPEN, got {work_item['consensus_gate']}"
        )

    def test_position_change_moves_the_seat_between_buckets_only(self, api):
        """
        Supplying a different `position` takes the vote around a self-loop — it stays
        `CAST` — increments `position_change_count`, and moves the seat between position
        buckets without ever changing `returned_count`; a member may do this any number
        of times while the ballot is open.

        Design: Corner/state_machines/vote_position_change_keeps_the_ballot_tally_ledger_in_sync
        """
        scenario = fx.open_subcommittee_ballot(api)
        scenario.cast("m2", "AFFIRMATIVE", vote_key="v2")
        a.assert_seat_ledger(
            scenario.get_ballot(),
            affirmative=1,
            negative=0,
            abstain=0,
            returned=1,
            not_returned=2,
            eligible=3,
        )

        scenario.change_vote(
            "v2",
            position="NEGATIVE",
            comment_text="Clause 12 torque ceiling is unsafe",
        )

        vote = scenario.get_vote("v2")
        assert vote["status"] == "CAST", (
            f"the self-loop keeps the vote CAST, got {vote['status']}"
        )
        assert vote["position"] == "NEGATIVE", (
            f"position expected NEGATIVE, got {vote['position']}"
        )
        assert vote["position_change_count"] == 1, (
            f"position_change_count expected 1, got {vote['position_change_count']}"
        )
        assert vote["adjudication_status"] == "NOT_APPLICABLE", (
            "the ballot is still open, so nothing is pending yet; got "
            f"{vote['adjudication_status']}"
        )

        ballot = scenario.get_ballot()
        a.assert_seat_ledger(
            ballot,
            affirmative=0,
            negative=1,
            abstain=0,
            returned=1,
            not_returned=2,
            eligible=3,
        )
        a.assert_seat_conservation(ballot)

        objections, meta = validate_paginated(
            api.list_comments(scenario.staff, {"source_vote_id": vote["id"]})
        )
        a.assert_total_count(meta, 1)
        assert objections[0]["source_type"] == "BALLOT_NEGATIVE", (
            f"source_type expected BALLOT_NEGATIVE, got {objections[0]['source_type']}"
        )


class TestDispositionBubblesOnTheLastComment:
    """The child-to-parent hop fires once, on the last open comment."""

    def test_only_the_second_disposition_bubbles_the_review_up(self, api):
        """
        Every one of the three disposing outcomes has identical downstream effects: the
        parent review's `disposed_count`, `unresolved_comment_count` and
        `disposition_completeness_pct` are recomputed, and when the recomputed
        `unresolved_comment_count` reaches 0 on a review that has at least one comment,
        the review bubbles up from `CLOSED` to `DISPOSITION_DRAFTED` with
        `disposition_completeness_pct` at 100.0.

        Design: Corner/state_machines/disposing_the_last_open_comment_bubbles_the_review_to_disposition_drafted
        """
        scenario = fx.draft_ready_for_public_review(api)
        scenario.register("p6")
        scenario.announce_public_review(start_date="2026-08-01", end_date="2026-09-14")
        first = scenario.submit_public_comment(
            "p6",
            comment_type="TECHNICAL",
            comment_text="The torque band in clause 9 is too wide for cast fittings",
            clause_reference="9",
        )
        second = scenario.submit_public_comment(
            "p2",
            comment_type="EDITORIAL",
            comment_text="Clause numbering skips from 11 to 13",
            clause_reference="11",
        )
        scenario.set_clock("2026-09-15T00:00:00Z")
        scenario.close_public_review()
        a.assert_comment_ledger(
            scenario.get_public_review(),
            comment_count=2,
            disposed_count=0,
            unresolved_count=2,
            completeness_pct=0.0,
        )

        scenario.dispose_comment(
            first["id"],
            disposition="REJECTED",
            disposition_rationale="The existing band is already normative in clause 9",
        )

        halfway = scenario.get_public_review()
        assert scenario.get_comment(first["id"])["status"] == "REJECTED", (
            "the first comment carries its disposition"
        )
        assert halfway["status"] == "CLOSED", (
            f"one comment is still open, so no bubble-up yet; got {halfway['status']}"
        )
        a.assert_comment_ledger(
            halfway,
            comment_count=2,
            disposed_count=1,
            unresolved_count=1,
            completeness_pct=50.0,
        )

        scenario.dispose_comment(
            second["id"],
            disposition="ACCEPTED",
            disposition_rationale="Renumbering applied in the next revision",
        )

        review = scenario.get_public_review()
        assert scenario.get_comment(second["id"])["status"] == "ACCEPTED", (
            "the second comment carries its disposition"
        )
        assert review["status"] == "DISPOSITION_DRAFTED", (
            f"the last disposition bubbles the review up, got {review['status']}"
        )
        a.assert_comment_ledger(
            review,
            comment_count=2,
            disposed_count=2,
            unresolved_count=0,
            completeness_pct=100.0,
        )
        assert review["disposition_approved_by_participant_id"] is None, (
            "bubbling up is not approval, got "
            f"{review['disposition_approved_by_participant_id']}"
        )
        assert scenario.get_draft()["status"] == "PUBLIC_REVIEW_CLOSED", (
            "no disposition ever moves the draft"
        )


class TestIndependentWorkItemDimensions:
    """A blocked patent dimension never slows the development dimension."""

    def test_an_essential_disclosure_blocks_ip_while_the_draft_advances(self, api):
        """
        The two evolve independently — a work item can sit in `IP_BLOCKED` while its
        development dimension advances all the way to `CONSENSUS_APPROVED` — and
        publication is the single point at which both dimensions are read together.

        Design: Corner/state_machines/work_item_ip_dimension_blocks_while_the_progress_dimension_keeps_advancing
        """
        scenario = fx.work_item_with_draft(api)

        disclosure = scenario.disclose_patent(
            "p2", patent_number="US-9876543", essentiality="ESSENTIAL"
        )

        assert disclosure["status"] == "DISCLOSED_NO_COMMITMENT", (
            f"status expected DISCLOSED_NO_COMMITMENT, got {disclosure['status']}"
        )
        assert disclosure["blocks_publication"] is True, (
            "an essential patent with no commitment blocks publication, got "
            f"{disclosure['blocks_publication']}"
        )
        blocked = scenario.get_work_item()
        assert blocked["ip_status"] == "IP_BLOCKED", (
            f"ip_status expected IP_BLOCKED, got {blocked['ip_status']}"
        )
        assert blocked["progress_status"] == "IN_DEVELOPMENT", (
            f"progress_status expected IN_DEVELOPMENT, got {blocked['progress_status']}"
        )
        assert blocked["consensus_gate"] == "OPEN", (
            "the gate reads appeals, drafts and committee balance only, got "
            f"{blocked['consensus_gate']}"
        )

        scenario.open_ballot()
        scenario.cast("m1", "AFFIRMATIVE", vote_key="v1")
        scenario.cast("m2", "AFFIRMATIVE", vote_key="v2")
        scenario.cast("m3", "AFFIRMATIVE", vote_key="v3")
        scenario.close_ballot()

        assert scenario.get_ballot()["consensus_result"] == "APPROVED", (
            "the unanimous subcommittee ballot passes on its own terms"
        )
        assert scenario.get_draft()["status"] == "PUBLIC_REVIEW_READY", (
            "the development dimension keeps advancing"
        )
        after = scenario.get_work_item()
        assert after["ip_status"] == "IP_BLOCKED", (
            "a subcommittee ballot never closes the call for patents, got "
            f"{after['ip_status']}"
        )
        assert after["progress_status"] == "IN_DEVELOPMENT", (
            f"progress_status expected IN_DEVELOPMENT, got {after['progress_status']}"
        )
        assert after["consensus_gate"] == "OPEN", (
            f"consensus_gate expected OPEN, got {after['consensus_gate']}"
        )
