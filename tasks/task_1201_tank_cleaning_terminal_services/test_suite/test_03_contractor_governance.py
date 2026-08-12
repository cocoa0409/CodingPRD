"""Contractor safety score variants, qualification threshold, lifecycle (PRD §3.2)."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_terminal_payload, create_contractor_payload,
    new_ctx, record_safety_event, qualify_contractor,
)

ADMIN = TEST_USERS["admin_headers"]


def _qualify(api, contractor_id, terminal_id):
    return api.qualify_contractor(contractor_id, {"terminal_id": terminal_id}, ADMIN)


class TestScoreVariants:
    def test_rolling_variant_excludes_events_older_than_365_days(self, api):
        """PRD §3.2: "under `ROLLING_12MO` only events whose `occurred_at` falls at or after the instant exactly 365 days before now count — the boundary is inclusive — while under `LIFETIME` every event counts regardless of age."
        PRD §3.2: "the contractor's score is computed under that terminal's variant and must meet the terminal's `safety_score_threshold` — a score exactly equal to the threshold passes"

        Design: Difficulty/dual_variant_calc/contractor_score_rolling_vs_lifetime
        """
        terminal = validate_success(api.create_terminal(
            create_terminal_payload(
                name="ROLLING", safety_score_threshold=90.0,
                score_variant="ROLLING_12MO"), ADMIN), 201)
        contractor = validate_success(api.create_contractor(
            create_contractor_payload(company_name="ScoreCo"), ADMIN), 201)
        record_safety_event(contractor["id"], "VIOLATION", 3,
                            "2026-04-25T00:00:00Z")
        record_safety_event(contractor["id"], "INCIDENT", 5,
                            "2025-03-15T00:00:00Z")

        result = validate_success(_qualify(api, contractor["id"], terminal["id"]), 200)
        assert result["status"] == "QUALIFIED"
        # 100.00 - 1.00*3 = 97.00; the 2025-03-15 INCIDENT is outside the window.
        assert result["safety_score"] == pytest.approx(97.00, abs=0.001)

    def test_lifetime_variant_counts_all_events(self, api):
        """PRD §3.2: "under `ROLLING_12MO` only events whose `occurred_at` falls at or after the instant exactly 365 days before now count — the boundary is inclusive — while under `LIFETIME` every event counts regardless of age. The same event history can therefore yield two different scores at two terminals, and each terminal's pinned variant governs evaluations made against that terminal."

        Design: Difficulty/dual_variant_calc/contractor_score_rolling_vs_lifetime
        """
        terminal = validate_success(api.create_terminal(
            create_terminal_payload(
                name="LIFE", safety_score_threshold=85.0,
                score_variant="LIFETIME"), ADMIN), 201)
        contractor = validate_success(api.create_contractor(
            create_contractor_payload(company_name="ScoreCo"), ADMIN), 201)
        record_safety_event(contractor["id"], "VIOLATION", 3,
                            "2026-04-25T00:00:00Z")
        record_safety_event(contractor["id"], "INCIDENT", 5,
                            "2025-03-15T00:00:00Z")

        result = validate_success(_qualify(api, contractor["id"], terminal["id"]), 200)
        assert result["status"] == "QUALIFIED"
        # 100.00 - 1.00*3 - 2.00*5 = 87.00: the old INCIDENT counts under LIFETIME.
        assert result["safety_score"] == pytest.approx(87.00, abs=0.001)

    def test_lifetime_variant_below_threshold_rejected(self, api):
        """PRD §3.2: "the contractor's score is computed under that terminal's variant and must meet the terminal's `safety_score_threshold` — a score exactly equal to the threshold passes — failing which the request is rejected with `ERR_CONTRACTOR_NOT_QUALIFIED` (HTTP 409) and the contractor's status is unchanged."

        Design: Difficulty/dual_variant_calc/contractor_score_rolling_vs_lifetime
        """
        terminal = validate_success(api.create_terminal(
            create_terminal_payload(
                name="LIFE", safety_score_threshold=90.0,
                score_variant="LIFETIME"), ADMIN), 201)
        contractor = validate_success(api.create_contractor(
            create_contractor_payload(company_name="ScoreCo"), ADMIN), 201)
        record_safety_event(contractor["id"], "VIOLATION", 3,
                            "2026-04-25T00:00:00Z")
        record_safety_event(contractor["id"], "INCIDENT", 5,
                            "2025-03-15T00:00:00Z")

        # LIFETIME score 87.00 < 90.0: same history the rolling terminal passed.
        validate_error(_qualify(api, contractor["id"], terminal["id"]),
                       ApiErrorId.ERR_CONTRACTOR_NOT_QUALIFIED)
        after = validate_success(api.get_contractor(contractor["id"], ADMIN), 200)
        assert after["status"] == "APPLICANT"


class TestThresholdBoundary:
    def test_score_exactly_at_threshold_qualifies(self, api):
        """PRD §3.2: "the contractor's score is computed under that terminal's variant and must meet the terminal's `safety_score_threshold` — a score exactly equal to the threshold passes"

        Design: Difficulty/boundary_precision_check/score_threshold_inclusive_85
        """
        ctx = new_ctx(terminal_overrides={"safety_score_threshold": 85.0,
                                          "score_variant": "ROLLING_12MO"},
                      qualify=False)
        contractor = ctx["contractor"]
        # severity_weight is bounded to 1..10 inclusive by PRD §3.2, so the
        # 15.00 deduction is built from two in-range VIOLATION events.
        record_safety_event(contractor["id"], "VIOLATION", 10,
                            "2026-04-20T00:00:00Z")
        record_safety_event(contractor["id"], "VIOLATION", 5,
                            "2026-04-21T00:00:00Z")
        # 100.00 - 1.00*10 - 1.00*5 = 85.00 == threshold: boundary passes.
        result = validate_success(
            _qualify(api, contractor["id"], ctx["terminal"]["id"]), 200)
        assert result["safety_score"] == pytest.approx(85.00, abs=0.001)
        assert result["status"] == "QUALIFIED"

    def test_score_one_step_below_threshold_rejected(self, api):
        """PRD §3.2: "the contractor's score is computed under that terminal's variant and must meet the terminal's `safety_score_threshold` — a score exactly equal to the threshold passes — failing which the request is rejected with `ERR_CONTRACTOR_NOT_QUALIFIED` (HTTP 409)"

        Design: Difficulty/boundary_precision_check/score_threshold_inclusive_85
        """
        ctx = new_ctx(terminal_overrides={"safety_score_threshold": 85.0,
                                          "score_variant": "ROLLING_12MO"},
                      qualify=False)
        contractor = ctx["contractor"]
        # severity_weight is bounded to 1..10 inclusive by PRD §3.2, so the
        # 15.00 deduction is built from two in-range VIOLATION events.
        record_safety_event(contractor["id"], "VIOLATION", 10,
                            "2026-04-20T00:00:00Z")
        record_safety_event(contractor["id"], "VIOLATION", 5,
                            "2026-04-21T00:00:00Z")
        record_safety_event(contractor["id"], "NEAR_MISS", 1,
                            "2026-04-21T00:00:00Z")
        # 100.00 - 15.00 - 0.25 = 84.75 < 85.0: one quarter-point below.
        validate_error(_qualify(api, contractor["id"], ctx["terminal"]["id"]),
                       ApiErrorId.ERR_CONTRACTOR_NOT_QUALIFIED)
        after = validate_success(api.get_contractor(contractor["id"], ADMIN), 200)
        assert after["status"] == "APPLICANT"


class TestWeightedScoreConstants:
    def test_violation_and_training_credit_weighted_sum(self, api):
        """PRD §3.2: "The computation starts from a base of 100.00, subtracts 2.00 times the total severity weight of the contractor's `INCIDENT` events, subtracts 1.00 times the total severity weight of `VIOLATION` events, subtracts 0.25 times the total severity weight of `NEAR_MISS` events, adds 0.50 times the total severity weight of `TRAINING_CREDIT` events, and clamps the result into the band from 0.00 to 100.00 at two decimal places."

        Design: Corner/calculations/contractor_score_weighted_constants
        """
        ctx = new_ctx(qualify=False)
        contractor = ctx["contractor"]
        record_safety_event(contractor["id"], "VIOLATION", 3,
                            "2026-04-10T00:00:00Z")
        record_safety_event(contractor["id"], "TRAINING_CREDIT", 4,
                            "2026-04-12T00:00:00Z")
        # 100.00 - 3.00 + 2.00 = 99.00 (default terminal is ROLLING_12MO / 85.0).
        result = validate_success(
            _qualify(api, contractor["id"], ctx["terminal"]["id"]), 200)
        assert result["safety_score"] == pytest.approx(99.00, abs=0.001)
        assert result["status"] == "QUALIFIED"


class TestGovernanceLifecycle:
    def test_suspend_reinstate_cycle_and_barred_terminal_state(self, api):
        """PRD §3.2: "Success moves `APPLICANT` to `QUALIFIED`, or `SUSPENDED` back to `QUALIFIED` on reinstatement. Governance actions complete the lifecycle: suspension moves `QUALIFIED` to `SUSPENDED`, and barring moves a contractor from `APPLICANT`, `QUALIFIED`, or `SUSPENDED` to the terminal state `BARRED`, from which no return exists."

        Design: Corner/state_machines/contractor_suspend_reinstate_cycle
        """
        ctx = new_ctx()
        cid = ctx["contractor"]["id"]

        suspended = validate_success(api.suspend_contractor(cid, ADMIN), 200)
        assert suspended["status"] == "SUSPENDED"

        reinstated = validate_success(
            _qualify_reinstate(api, cid, ctx["terminal"]["id"]), 200)
        assert reinstated["status"] == "QUALIFIED"

        barred = validate_success(api.bar_contractor(cid, ADMIN), 200)
        assert barred["status"] == "BARRED"

        # BARRED is terminal: reinstate is not defined from it.
        res = api.reinstate_contractor(cid, {"terminal_id": ctx["terminal"]["id"]},
                                       ADMIN)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


def _qualify_reinstate(api, contractor_id, terminal_id):
    return api.reinstate_contractor(contractor_id, {"terminal_id": terminal_id},
                                    ADMIN)
