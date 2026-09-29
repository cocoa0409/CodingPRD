"""
Appeals as a stop-work order on the procedural gate: standing decided before
timeliness, an upholding that vacates a ballot and reopens development, and a
denial that releases publication.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx


class TestUpheldAppealReopensDevelopment:
    """Vacating a ballot walks back the whole consensus cycle."""

    def test_upholding_vacates_the_cited_ballot_but_preserves_its_tallies(self, api):
        """
        Hop two, under the `VACATE_BALLOT` remedy, moves the cited ballot from
        `EVALUATED` to `VACATED` — the tallies and percentages are preserved
        untouched as the historical record, and `consensus_result` is left exactly
        as it was.

        Design: Difficulty/transitive_cascade/upheld_appeal_cascade_vacates_ballot_and_reopens_work_item_development
        """
        scenario = fx.consensus_approved_after_non_persuasive(api)
        scenario.file_appeal(
            "p3",
            cited_ballot_id=scenario.ballot_id,
            grounds="NEGATIVE_NOT_CONSIDERED",
            statement="The negative was dismissed without addressing clause 12",
            headers=scenario.member("p3"),
        )
        scenario.decide_appeal("ACCEPT_FOR_REVIEW")
        scenario.decide_appeal(
            "UPHOLD",
            remedy="VACATE_BALLOT",
            decision_rationale="The objection was not substantively answered",
        )

        appeal = scenario.get_appeal()
        assert appeal["status"] == "UPHELD", (
            f"appeal status expected UPHELD, got {appeal['status']}"
        )
        assert appeal["remedy"] == "VACATE_BALLOT", (
            f"remedy expected VACATE_BALLOT, got {appeal['remedy']}"
        )
        a.assert_same_instant(appeal["decided_at"], "2026-09-15T00:00:00Z")
        a.assert_same_instant(appeal["filing_deadline_at"], "2026-10-15T00:00:00Z")

        ballot = scenario.get_ballot()
        assert ballot["status"] == "VACATED", (
            f"the cited ballot expected VACATED, got {ballot['status']}"
        )
        assert ballot["negative_count"] == 1, (
            "the vacated ballot keeps its historical tallies, got "
            f"{ballot['negative_count']}"
        )
        assert ballot["consensus_result"] == "APPROVED", (
            "consensus_result is left exactly as it was, got "
            f"{ballot['consensus_result']}"
        )
        a.assert_pct(ballot["provisional_approval_pct"], 66.7)

    def test_upholding_carries_the_negative_forward_and_reopens_the_work_item(self, api):
        """
        Hop four, because the draft returned to development, moves the work item from
        `CONSENSUS_APPROVED` back to `IN_DEVELOPMENT` and re-derives its gate, so the
        consensus cycle can run again — this time with the approval bar raised by 5.0
        percentage points on account of the carryover.

        Design: Difficulty/transitive_cascade/upheld_appeal_cascade_vacates_ballot_and_reopens_work_item_development
        """
        scenario = fx.consensus_approved_after_non_persuasive(api)
        assert scenario.get_work_item()["progress_status"] == "CONSENSUS_APPROVED", (
            "the cycle had completed before the appeal"
        )
        scenario.file_appeal(
            "p3",
            cited_ballot_id=scenario.ballot_id,
            grounds="NEGATIVE_NOT_CONSIDERED",
            statement="The negative was dismissed without addressing clause 12",
            headers=scenario.member("p3"),
        )
        scenario.decide_appeal("ACCEPT_FOR_REVIEW")
        scenario.decide_appeal(
            "UPHOLD",
            remedy="VACATE_BALLOT",
            decision_rationale="The objection was not substantively answered",
        )

        draft = scenario.get_draft()
        assert draft["status"] == "DRAFTING", (
            f"the approved draft returns to DRAFTING, got {draft['status']}"
        )
        assert draft["carryover_unresolved_negative_count"] == 1, (
            "the draft inherits the vacated ballot's negative_count, got "
            f"{draft['carryover_unresolved_negative_count']}"
        )

        work_item = scenario.get_work_item()
        assert work_item["progress_status"] == "IN_DEVELOPMENT", (
            f"progress_status expected IN_DEVELOPMENT, got {work_item['progress_status']}"
        )
        assert work_item["published_at"] is None, (
            "nothing was ever published on this path"
        )
        assert work_item["consensus_gate"] == "OPEN", (
            "the decided appeal is no longer live, so the gate reopens; got "
            f"{work_item['consensus_gate']}"
        )
        assert work_item["ip_status"] == "IP_PENDING", (
            "reopening development reopens the call for patents, got "
            f"{work_item['ip_status']}"
        )


class TestFiledAppealHoldsPublication:
    """A live appeal is a stop-work order; a denial lifts it."""

    def test_filing_an_appeal_shuts_the_gate_and_publication_is_refused(self, api):
        """
        Merely filing it shuts the work item's procedural gate to `BLOCKED`, and the
        work item's `version` advances — an appeal is a stop-work order until it is
        decided.

        Design: Difficulty/cross_entity_state_dependency/publication_blocked_while_a_filed_appeal_holds_the_consensus_gate
        """
        scenario = fx.consensus_approved_work_item(api)
        before = scenario.get_work_item()
        assert before["progress_status"] == "CONSENSUS_APPROVED", (
            f"progress_status expected CONSENSUS_APPROVED, got {before['progress_status']}"
        )
        assert before["ip_status"] == "IP_CLEARED", (
            f"ip_status expected IP_CLEARED, got {before['ip_status']}"
        )
        assert before["consensus_gate"] == "OPEN", (
            f"consensus_gate expected OPEN, got {before['consensus_gate']}"
        )
        assert before["unresolved_negative_count"] == 0, (
            "a unanimous cycle leaves nothing unresolved"
        )

        appeal = scenario.file_appeal(
            "p3",
            cited_ballot_id=scenario.ballot_id,
            grounds="VOTING_PROCEDURE_DEFECT",
            statement="The consensus ballot closed before its announced closing instant",
            headers=scenario.member("p3"),
        )
        assert appeal["status"] == "FILED", (
            f"a new appeal opens in FILED, got {appeal['status']}"
        )
        assert appeal["remedy"] == "NONE", (
            f"remedy starts at NONE, got {appeal['remedy']}"
        )
        a.assert_same_instant(appeal["filing_deadline_at"], "2026-10-15T00:00:00Z")

        blocked = scenario.get_work_item()
        assert blocked["consensus_gate"] == "BLOCKED", (
            f"consensus_gate expected BLOCKED, got {blocked['consensus_gate']}"
        )
        assert blocked["version"] > before["version"], (
            "filing advances the work item's version"
        )

        validate_error(
            api.publish_work_item(scenario.work_item_id, scenario.staff),
            "ERR_CONSENSUS_GATE_BLOCKED",
            409,
        )
        after = scenario.get_work_item()
        assert after["progress_status"] == "CONSENSUS_APPROVED", (
            "the refused publication changed nothing"
        )
        assert after["published_at"] is None, (
            f"published_at must stay null, got {after['published_at']}"
        )

    def test_denying_the_appeal_reopens_the_gate_and_publication_proceeds(self, api):
        """
        And the work item's gate is re-derived, returning to `OPEN` when no other
        appeal is live and no draft of the work item sits in `COMMENT_RESOLUTION`.

        Design: Difficulty/cross_entity_state_dependency/publication_blocked_while_a_filed_appeal_holds_the_consensus_gate
        """
        scenario = fx.consensus_approved_work_item(api)
        scenario.file_appeal(
            "p3",
            cited_ballot_id=scenario.ballot_id,
            grounds="VOTING_PROCEDURE_DEFECT",
            statement="The consensus ballot closed before its announced closing instant",
            headers=scenario.member("p3"),
        )
        validate_error(
            api.publish_work_item(scenario.work_item_id, scenario.staff),
            "ERR_CONSENSUS_GATE_BLOCKED",
            409,
        )

        scenario.decide_appeal(
            "DENY",
            decision_rationale="An early close is permitted once every seat has returned",
        )
        appeal = scenario.get_appeal()
        assert appeal["status"] == "DENIED", (
            f"appeal status expected DENIED, got {appeal['status']}"
        )
        assert appeal["remedy"] == "NONE", (
            f"a denial leaves remedy at NONE, got {appeal['remedy']}"
        )
        a.assert_same_instant(appeal["decided_at"], "2026-09-15T00:00:00Z")
        assert scenario.get_ballot()["status"] == "EVALUATED", (
            "a denial leaves the cited ballot untouched"
        )
        assert scenario.get_draft()["status"] == "APPROVED", (
            "a denial leaves the draft untouched"
        )
        assert scenario.get_work_item()["consensus_gate"] == "OPEN", (
            "the gate reopens once no appeal is live"
        )

        published = scenario.publish()
        assert published["progress_status"] == "PUBLISHED", (
            f"progress_status expected PUBLISHED, got {published['progress_status']}"
        )
        a.assert_same_instant(published["published_at"], "2026-09-15T00:00:00Z")
        a.assert_date_equals(published["periodic_review_due_date"], "2031-09-15")


class TestStandingIsDecidedBeforeTimeliness:
    """Two rules broken at once; the ladder reports the earlier one."""

    def test_outsider_filing_late_is_refused_for_standing_not_for_timeliness(self, api):
        """
        an appeal filed by a participant who holds no membership, authored no comment
        and did not propose the work item, submitted after the filing window has
        already elapsed, likewise violates two rules; the response is
        `ERR_APPELLANT_NOT_INTERESTED_PARTY` (403), because standing at precedence 97
        is decided before timeliness at precedence 117, and no appeal row is created.

        Design: Difficulty/priority_pair_validation_conflict/appeal_standing_error_precedes_untimeliness_error
        """
        scenario = fx.draft_ready_for_public_review(api)
        scenario.register("p6")
        scenario.set_clock("2026-09-15T00:00:00Z")

        response = api.create_appeal(
            f.appeal_payload(
                scenario.work_item_id,
                scenario.pid("p6"),
                grounds="VOTING_PROCEDURE_DEFECT",
                statement="The subcommittee ballot closed before its announced instant",
                cited_ballot_id=scenario.ballot_id,
            ),
            scenario.proposer("p6"),
        )
        validate_error(response, "ERR_APPELLANT_NOT_INTERESTED_PARTY", 403)

        _, meta = validate_paginated(api.list_appeals(scenario.staff))
        a.assert_total_count(meta, 0)

    def test_seated_member_filing_at_the_same_instant_is_refused_as_untimely(self, api):
        """
        Given an anchor, `filing_deadline_at` is that anchor instant advanced by 30
        days, and a filing is timely when the logical clock is at or before that
        deadline — the deadline instant itself is timely.

        Design: Difficulty/priority_pair_validation_conflict/appeal_standing_error_precedes_untimeliness_error
        """
        scenario = fx.draft_ready_for_public_review(api)
        scenario.register("p6")
        scenario.set_clock("2026-09-15T00:00:00Z")
        anchor = scenario.get_ballot()
        a.assert_same_instant(anchor["closed_at"], "2026-08-01T00:00:00Z")

        response = api.create_appeal(
            f.appeal_payload(
                scenario.work_item_id,
                scenario.pid("p3"),
                grounds="VOTING_PROCEDURE_DEFECT",
                statement="The subcommittee ballot closed before its announced instant",
                cited_ballot_id=scenario.ballot_id,
            ),
            scenario.member("p3"),
        )
        validate_error(response, "ERR_APPEAL_UNTIMELY", 409)

        _, meta = validate_paginated(api.list_appeals(scenario.staff))
        a.assert_total_count(meta, 0)
        assert scenario.get_work_item()["consensus_gate"] == "OPEN", (
            "a refused filing never shuts the gate"
        )
