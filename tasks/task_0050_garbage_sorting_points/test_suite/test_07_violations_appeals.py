"""Violation recording, escalation, appeals, and the overturn cascade.

Covers PRD §3.6.
"""
from __future__ import annotations

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import (
    ApiErrorId,
    accept_review_violation,
    advance_clock,
    appeal_violation,
    appeal_violation_payload,
    decide_violation,
    fetch_household,
    fetch_violation,
    list_points_txns,
    make_appeal_reviewer_headers,
    make_community_admin_headers,
    make_resident_headers,
    record_violation,
    setup_verified_resident,
    walk_violation_to_upheld,
)


class TestViolationRecord:
    def test_record_violation_applies_base_20_for_mis_sorting(self, api):
        """PRD §3.6: 'The base_deduction_points is fixed by violation type:
        20 points for MIS_SORTING, 50 points for LITTERING, and 30 points
        for NO_CLASSIFICATION.'

        First MIS_SORTING in window: repeat=1, multiplier=1.00, final=20.
        """
        advance_clock("2030-01-01T00:00:00.000Z")
        community, household, resident = setup_verified_resident()
        advance_clock("2030-01-02T00:00:00.000Z")
        v = record_violation(
            community["id"], resident["id"], "2030-01-02T00:00:00.000Z",
            violation_type="MIS_SORTING",
        )
        assert v["base_deduction_points"] == 20
        assert v["repeat_count_in_window"] == 1
        assert float(v["escalation_multiplier"]) == pytest.approx(1.00)
        assert v["final_deduction_points"] == 20

    def test_record_violation_applies_base_50_for_littering(self, api):
        """PRD §3.6: '50 points for LITTERING.'"""
        advance_clock("2030-01-01T00:00:00.000Z")
        community, household, resident = setup_verified_resident()
        advance_clock("2030-01-02T00:00:00.000Z")
        v = record_violation(
            community["id"], resident["id"], "2030-01-02T00:00:00.000Z",
            violation_type="LITTERING",
        )
        assert v["base_deduction_points"] == 50
        assert v["final_deduction_points"] == 50

    def test_record_violation_debits_balance_can_go_negative(self, api):
        """PRD §3.6: 'reduces Household.points_balance by
        final_deduction_points even when the balance would become negative.'"""
        advance_clock("2030-01-01T00:00:00.000Z")
        community, household, resident = setup_verified_resident()
        advance_clock("2030-01-02T00:00:00.000Z")
        record_violation(
            community["id"], resident["id"], "2030-01-02T00:00:00.000Z",
            violation_type="MIS_SORTING",
        )
        hh = fetch_household(community["id"], household["id"])
        assert hh["points_balance"] == -20

    def test_record_violation_sets_appeal_deadline_at_plus_14_days(self, api):
        """PRD §3.6: 'It computes appeal_deadline_at as occurred_at plus
        14 days.'"""
        advance_clock("2030-01-01T00:00:00.000Z")
        community, household, resident = setup_verified_resident()
        advance_clock("2030-01-02T00:00:00.000Z")
        v = record_violation(
            community["id"], resident["id"], "2030-01-02T00:00:00.000Z",
            violation_type="MIS_SORTING",
        )
        # 14 days later
        assert v["appeal_deadline_at"].startswith("2030-01-16T00:00:00")

    def test_record_violation_emits_violation_recorded_audit(self, api):
        """PRD §3.6: 'It appends an AuditLog entry of action VIOLATION_RECORDED
        and subject kind VIOLATION.'"""
        from test_helpers import list_audit_logs
        advance_clock("2030-01-01T00:00:00.000Z")
        community, household, resident = setup_verified_resident()
        advance_clock("2030-01-02T00:00:00.000Z")
        v = record_violation(
            community["id"], resident["id"], "2030-01-02T00:00:00.000Z",
            violation_type="MIS_SORTING",
        )
        logs = list_audit_logs(
            community["id"], params={"action": "VIOLATION_RECORDED"},
        )
        matching = [
            log for log in logs
            if log.get("subject_kind") == "VIOLATION"
            and log.get("subject_id") == v["id"]
        ]
        assert matching, "Expected VIOLATION_RECORDED audit log"


class TestViolationEscalation:
    def test_second_violation_in_window_uses_1_50_multiplier(self, api):
        """PRD §3.6: 'two violations to 1.50.' base=20, mult=1.50, final=30."""
        advance_clock("2030-01-01T00:00:00.000Z")
        community, household, resident = setup_verified_resident()
        advance_clock("2030-01-02T00:00:00.000Z")
        record_violation(
            community["id"], resident["id"], "2030-01-02T00:00:00.000Z",
            violation_type="MIS_SORTING",
        )
        advance_clock("2030-01-03T00:00:00.000Z")
        v2 = record_violation(
            community["id"], resident["id"], "2030-01-03T00:00:00.000Z",
            violation_type="MIS_SORTING",
        )
        assert v2["repeat_count_in_window"] == 2
        assert float(v2["escalation_multiplier"]) == pytest.approx(1.50)
        assert v2["final_deduction_points"] == 30

    def test_third_violation_in_window_uses_2_00_multiplier(self, api):
        """PRD §3.6: 'three violations to 2.00.' base=20, final=40."""
        advance_clock("2030-01-01T00:00:00.000Z")
        community, household, resident = setup_verified_resident()
        for i, day in enumerate(("02", "03", "04")):
            t = f"2030-01-{day}T00:00:00.000Z"
            advance_clock(t)
            v = record_violation(
                community["id"], resident["id"], t,
                violation_type="MIS_SORTING",
            )
        assert v["repeat_count_in_window"] == 3
        assert v["final_deduction_points"] == 40


class TestAppealLifecycle:
    def test_appeal_new_violation_transitions_to_appealed(self, api):
        """PRD §3.6: 'On a first appeal - current status NEW - the violation
        transitions NEW -> APPEALED, appeal_filed_at is set to the current
        logical clock, and appeal_round increments to 1.'"""
        advance_clock("2030-01-01T00:00:00.000Z")
        community, household, resident = setup_verified_resident()
        advance_clock("2030-01-02T00:00:00.000Z")
        v = record_violation(
            community["id"], resident["id"], "2030-01-02T00:00:00.000Z",
            violation_type="MIS_SORTING",
        )
        appealed = appeal_violation(community["id"], resident, v["id"])
        assert appealed["status"] == "APPEALED"
        assert appealed["appeal_round"] == 1
        assert appealed["appeal_filed_at"] is not None

    def test_accept_review_transitions_to_under_review(self, api):
        """PRD §3.6 / state machine: An AppealReviewer takes an appealed
        violation under review (transitioning APPEALED -> UNDER_REVIEW with
        no points movement)."""
        advance_clock("2030-01-01T00:00:00.000Z")
        community, household, resident = setup_verified_resident()
        advance_clock("2030-01-02T00:00:00.000Z")
        v = record_violation(
            community["id"], resident["id"], "2030-01-02T00:00:00.000Z",
            violation_type="MIS_SORTING",
        )
        appeal_violation(community["id"], resident, v["id"])
        reviewed = accept_review_violation(community["id"], v["id"])
        assert reviewed["status"] == "UNDER_REVIEW"

    def test_decide_uphold_keeps_deduction_no_points_movement(self, api):
        """PRD §3.6: 'An UPHOLD decision transitions UNDER_REVIEW -> UPHELD,
        performs no points movement (the deduction was already applied at
        creation).'"""
        advance_clock("2030-01-01T00:00:00.000Z")
        community, household, resident = setup_verified_resident()
        advance_clock("2030-01-02T00:00:00.000Z")
        v = record_violation(
            community["id"], resident["id"], "2030-01-02T00:00:00.000Z",
            violation_type="MIS_SORTING",
        )
        hh_after_create = fetch_household(community["id"], household["id"])
        assert hh_after_create["points_balance"] == -20
        walk_violation_to_upheld(community, resident, v["id"])
        hh_after_uphold = fetch_household(community["id"], household["id"])
        # No points movement during APPEAL/REVIEW/UPHOLD.
        assert hh_after_uphold["points_balance"] == -20

    def test_decide_overturn_appends_violation_reversal_and_restores_balance(
        self, api,
    ):
        """PRD §3.6: 'An OVERTURN decision transitions UNDER_REVIEW ->
        OVERTURNED ... the system appends a PointsTransaction whose kind is
        VIOLATION_REVERSAL and whose amount is the positive
        final_deduction_points of this violation, restores
        Household.points_balance by the same amount.'"""
        advance_clock("2030-01-01T00:00:00.000Z")
        community, household, resident = setup_verified_resident()
        advance_clock("2030-01-02T00:00:00.000Z")
        v = record_violation(
            community["id"], resident["id"], "2030-01-02T00:00:00.000Z",
            violation_type="MIS_SORTING",
        )
        appeal_violation(community["id"], resident, v["id"])
        accept_review_violation(community["id"], v["id"])
        decided = decide_violation(community["id"], v["id"], "OVERTURN")
        assert decided["status"] == "OVERTURNED"
        hh = fetch_household(community["id"], household["id"])
        assert hh["points_balance"] == 0  # -20 + 20
        # Confirm reversal txn exists.
        txns = list_points_txns(community["id"], household["id"])
        rev = [
            t for t in txns
            if t["kind"] == "VIOLATION_REVERSAL"
            and t["related_entity_id"] == v["id"]
        ]
        assert len(rev) == 1
        assert rev[0]["amount"] == 20


class TestAppealGuards:
    def test_appeal_after_window_expired_yields_appeal_window_expired(
        self, api,
    ):
        """PRD §3.6: 'The appeal is allowed only when now() is strictly
        before appeal_deadline_at (else ERR_APPEAL_WINDOW_EXPIRED).'"""
        advance_clock("2030-01-01T00:00:00.000Z")
        community, household, resident = setup_verified_resident()
        advance_clock("2030-01-02T00:00:00.000Z")
        v = record_violation(
            community["id"], resident["id"], "2030-01-02T00:00:00.000Z",
            violation_type="MIS_SORTING",
        )
        # 14 day appeal window from occurred_at; advance well past it.
        advance_clock("2030-02-01T00:00:00.000Z")
        resp = api.appeal_violation(
            community["id"], v["id"], appeal_violation_payload(),
            make_resident_headers(resident["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED.value)

    def test_appeal_by_non_owner_yields_forbidden(self, api):
        """PRD §3.6: 'X-User-ID equals the violation's resident_id and
        X-User-Role is Resident (else ERR_FORBIDDEN).'"""
        advance_clock("2030-01-01T00:00:00.000Z")
        community, household, resident = setup_verified_resident()
        c2, hh2, other = setup_verified_resident()
        advance_clock("2030-01-02T00:00:00.000Z")
        v = record_violation(
            community["id"], resident["id"], "2030-01-02T00:00:00.000Z",
            violation_type="MIS_SORTING",
        )
        # Other resident appeals — not violation's resident.
        resp = api.appeal_violation(
            community["id"], v["id"], appeal_violation_payload(),
            make_resident_headers(other["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
