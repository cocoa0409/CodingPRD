"""The escalation fan-out, and the nine-step certification timeline projection."""

import pytest

from test_helpers import api_client, assertions, fixtures, validate_success
from test_helpers.test_users import TEST_USERS

AUDIT_MANAGER = TEST_USERS["audit_manager_headers"]

CANVASS_DAY = "2026-11-05T09:00:00Z"


def _review(audit_id):
    return validate_success(api_client.review_audit_timeline(audit_id, AUDIT_MANAGER))


class TestEscalationCreatesTheFullHandCountRound:
    """One board decision fans out to a new round, three drawn rows and three authorizations."""

    def test_escalation_moves_the_finding_and_the_audit_and_supersedes_round_one(self):
        """PRD §3.6: "On success the finding becomes `ESCALATED`, the audit moves to
        `ESCALATED_FULL_HAND_COUNT` with its `escalation_level` increased by one, that audit
        transition creates the full-hand-count round covering every unsampled batch."

        Design: Difficulty/transitive_cascade/cascade_escalation_creates_full_hand_count_round_and_authorizes_three_batches
        """
        scenario = fixtures.setup_escalated_audit()

        assert scenario["discrepancy"]["status"] == "ESCALATED"
        audit = fixtures.read_audit(scenario["audit"]["id"])
        assert audit["status"] == "ESCALATED_FULL_HAND_COUNT"
        assert audit["escalation_level"] == 1
        # PRD §3.4: cumulative_sampled_batches is "the number of drawn-batch rows
        # across all of its non-superseded rounds".  The escalation supersedes
        # round one, so only the full-hand-count round's three rows remain.
        assert audit["cumulative_sampled_batches"] == 3
        assert audit["timeline_status"] == "ON_TRACK"
        assert fixtures.read_audit_round(scenario["round"]["id"])["status"] == (
            "SUPERSEDED"
        )

    def test_the_full_hand_count_round_takes_the_whole_unsampled_pool_in_label_order(self):
        """PRD §3.4: "A full-hand-count round is the one exception: its whole eligible pool
        is drawn, in `batch_label` ascending order, its `selection_sequence` is that sorted
        pool, and the pseudo-random generator is not consulted at all."

        Design: Difficulty/transitive_cascade/cascade_escalation_creates_full_hand_count_round_and_authorizes_three_batches
        """
        scenario = fixtures.setup_escalated_audit()

        escalation_round = scenario["escalation_round"]
        assertions.assert_audit_round(escalation_round)
        assert escalation_round["round_number"] == 2
        assert escalation_round["is_full_hand_count"] is True
        assert escalation_round["status"] == "SELECTED"
        assert escalation_round["previous_round_id"] == scenario["round"]["id"]
        assert escalation_round["sample_size_batches"] == 3
        assert escalation_round["selection_sequence"] == ["B-001", "B-002", "B-006"]

        drawn = scenario["escalation_batches"]
        assert [row["selection_index"] for row in drawn] == [0, 1, 2]
        assert [row["retrieval_status"] for row in drawn] == ["PENDING_RETRIEVAL"] * 3
        expected_batch_ids = [
            fixtures.batch_by_label(scenario["batches"], label)["id"]
            for label in ("B-001", "B-002", "B-006")
        ]
        assert [row["ballot_batch_id"] for row in drawn] == expected_batch_ids

    def test_each_unsampled_batch_is_authorized_with_a_custody_entry(self):
        """PRD §3.6: "that round creates one drawn-batch row per unsampled batch, each
        stamping the physical batch's `retrieval_authorized_at` and appending an
        `AUTHORIZED` custody entry."

        Design: Difficulty/transitive_cascade/cascade_escalation_creates_full_hand_count_round_and_authorizes_three_batches
        """
        scenario = fixtures.setup_escalated_audit()

        for label in ("B-001", "B-002", "B-006"):
            physical = fixtures.read_batch(
                fixtures.batch_by_label(scenario["batches"], label)["id"]
            )
            assertions.assert_same_instant(
                physical["retrieval_authorized_at"], CANVASS_DAY,
                f"{label} retrieval_authorized_at",
            )
            events = fixtures.list_custody_events(physical["id"])
            assert [event["event_type"] for event in events] == ["INTAKE", "AUTHORIZED"]
            assert events[1]["sequence_no"] == 2


class TestTimelineExtensionFromPreExtensionSlack:
    """The statutory extension is sized on the slack before it is granted."""

    def _escalate_two_days_before_the_deadline(self):
        scenario = fixtures.setup_documented_discrepancy()
        fixtures.set_clock("2026-11-23T21:00:00Z")
        scenario["discrepancy"] = fixtures.escalate_discrepancy(
            scenario["discrepancy"]["id"]
        )
        return scenario

    def test_the_extension_is_derived_from_the_slack_before_it_is_granted(self):
        """PRD §3.9: "`extension_days_granted` is zero when `slack_hours` is zero or
        greater; otherwise it is the smaller of 5 and the absolute value of `slack_hours`
        divided by 24 and rounded up to the next whole day — the statute grants at most five
        days. The audit's `effective_certification_deadline_at` is the election's
        `certification_deadline_at` plus `extension_days_granted` days."

        Design: Difficulty/combinatorial_formula/combinatorial_timeline_extension_derived_from_pre_extension_slack
        """
        scenario = self._escalate_two_days_before_the_deadline()

        audit = fixtures.read_audit(scenario["audit"]["id"])
        assert audit["status"] == "ESCALATED_FULL_HAND_COUNT"
        assert audit["escalation_level"] == 1
        assertions.assert_same_instant(
            audit["projected_completion_at"],
            "2026-11-26T15:00:00Z",
            "projected_completion_at",
        )
        assert audit["slack_hours"] == pytest.approx(-46.00, abs=0.005)
        assert audit["extension_days_granted"] == 2
        assertions.assert_same_instant(
            audit["effective_certification_deadline_at"],
            "2026-11-26T17:00:00Z",
            "effective_certification_deadline_at",
        )
        assert audit["effective_slack_hours"] == pytest.approx(2.00, abs=0.005)
        assert audit["timeline_status"] == "AT_RISK"

    def test_the_extension_rolls_up_to_the_election_deadline_and_contest_window(self):
        """PRD §3.9: "The election's `effective_certification_deadline_at` is its
        `certification_deadline_at` plus the largest `extension_days_granted` across all
        audits of its contests — one audit's extension moves the whole election's deadline,
        and the largest, not the sum, governs. Its `contest_window_ends_at` is ten days
        after that effective deadline."

        Design: Difficulty/combinatorial_formula/combinatorial_timeline_extension_derived_from_pre_extension_slack
        """
        scenario = self._escalate_two_days_before_the_deadline()

        election = fixtures.read_election(scenario["election"]["id"])
        assertions.assert_election(election)
        assertions.assert_same_instant(
            election["effective_certification_deadline_at"],
            "2026-11-26T17:00:00Z",
            "effective_certification_deadline_at",
        )
        assertions.assert_same_instant(
            election["contest_window_ends_at"],
            "2026-12-06T17:00:00Z",
            "contest_window_ends_at",
        )
        assert election["timeline_status"] == "AT_RISK"
        assert election["certification_risk_flag"] is True


class TestEffectiveSlackAtTheAtRiskCeiling:
    """Seventy-three hours of slack is routine; seventy-two exactly is not."""

    def _audit_with_one_pending_round(self):
        scenario = fixtures.setup_canvassed_contest()
        scenario.update(fixtures.setup_audit_round_one(scenario["contest"]["id"]))
        return scenario

    def test_seventy_three_hours_of_slack_is_on_track(self):
        """PRD §3.9: "The round hours are 48 multiplied by the number of pending rounds —
        two days of fixed overhead per open round."

        Design: Difficulty/boundary_precision_check/boundary_effective_slack_hours_exactly_at_at_risk_ceiling
        """
        scenario = self._audit_with_one_pending_round()
        fixtures.set_clock("2026-11-19T16:00:00Z")

        reviewed = _review(scenario["audit"]["id"])

        assertions.assert_audit(reviewed)
        assertions.assert_same_instant(
            reviewed["projected_completion_at"],
            "2026-11-21T16:00:00Z",
            "projected_completion_at",
        )
        assert reviewed["effective_slack_hours"] == pytest.approx(73.00, abs=0.005)
        assert reviewed["timeline_status"] == "ON_TRACK"
        assert reviewed["extension_days_granted"] == 0

    def test_exactly_seventy_two_hours_of_slack_is_at_risk(self):
        """PRD §3.9: "`timeline_status` is `BREACHED` when `effective_slack_hours` is
        negative, `AT_RISK` when it is zero or greater but no greater than 72, and
        `ON_TRACK` otherwise."

        Design: Difficulty/boundary_precision_check/boundary_effective_slack_hours_exactly_at_at_risk_ceiling
        """
        scenario = self._audit_with_one_pending_round()
        fixtures.set_clock("2026-11-19T16:00:00Z")
        _review(scenario["audit"]["id"])
        fixtures.set_clock("2026-11-19T17:00:00Z")

        reviewed = _review(scenario["audit"]["id"])

        assertions.assert_same_instant(
            reviewed["projected_completion_at"],
            "2026-11-21T17:00:00Z",
            "projected_completion_at",
        )
        assert reviewed["slack_hours"] == pytest.approx(72.00, abs=0.005)
        assert reviewed["extension_days_granted"] == 0
        assertions.assert_same_instant(
            reviewed["effective_certification_deadline_at"],
            "2026-11-24T17:00:00Z",
            "effective_certification_deadline_at",
        )
        assert reviewed["effective_slack_hours"] == pytest.approx(72.00, abs=0.005)
        assert reviewed["timeline_status"] == "AT_RISK"
        election = fixtures.read_election(scenario["election"]["id"])
        assert election["timeline_status"] == "AT_RISK"
        assertions.assert_same_instant(
            election["contest_window_ends_at"],
            "2026-12-04T17:00:00Z",
            "contest_window_ends_at",
        )
