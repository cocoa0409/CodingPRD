"""PointRule lifecycle: create -> activate -> retire.

Covers PRD §3.2 (rule creation, activation, retirement, effectiveness)
and the activation-time constraints (no dual-active, no backdating).
"""
from __future__ import annotations

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import (
    ApiErrorId,
    activate_point_rule,
    activate_point_rule_payload,
    advance_clock,
    create_community,
    create_point_rule,
    create_point_rule_payload,
    list_audit_logs,
    make_community_admin_headers,
    retire_point_rule,
    setup_active_point_rule,
)


class TestPointRuleCreation:
    def test_create_rule_born_draft_with_version_1(self, api):
        """PRD §3.2: 'A rule is created in DRAFT status with several scoring
        parameters and is then explicitly activated.' PRD §3.2: 'the version
        integer starts at 1 and increments by one for every published
        successor.'"""
        community = create_community()
        rule = create_point_rule(community["id"])
        assert rule["status"] == "DRAFT"
        assert rule["version"] == 1
        assert rule["activated_at"] is None
        assert rule["retired_at"] is None


class TestPointRuleActivation:
    def test_activate_draft_rule_succeeds(self, api):
        """PRD §3.2: 'On success, the rule transitions DRAFT -> ACTIVE, its
        activated_at is set to the supplied value.'"""
        advance_clock("2030-01-01T00:00:00.000Z")
        community = create_community()
        rule = setup_active_point_rule(
            community["id"], "2030-01-01T00:00:00.000Z",
        )
        assert rule["status"] == "ACTIVE"
        assert rule["activated_at"] == "2030-01-01T00:00:00.000Z"

    def test_activate_emits_audit_log_rule_published(self, api):
        """PRD §3.2: 'an AuditLog entry of action RULE_PUBLISHED and subject
        kind POINT_RULE is appended.'"""
        advance_clock("2030-01-01T00:00:00.000Z")
        community = create_community()
        rule = setup_active_point_rule(
            community["id"], "2030-01-01T00:00:00.000Z",
        )
        logs = list_audit_logs(
            community["id"], params={"action": "RULE_PUBLISHED"},
        )
        matching = [
            log for log in logs
            if log.get("subject_kind") == "POINT_RULE"
            and log.get("subject_id") == rule["id"]
        ]
        assert matching, (
            f"Expected RULE_PUBLISHED audit entry for rule {rule['id']}"
        )

    def test_activate_with_backdated_activated_at_rejected(self, api):
        """PRD §3.2: 'an activated_at instant that must be at or after the
        current logical clock - backdating is rejected with
        ERR_RULE_BACKDATING.'"""
        advance_clock("2030-06-01T00:00:00.000Z")
        community = create_community()
        rule = create_point_rule(community["id"])
        resp = api.activate_point_rule(
            community["id"], rule["id"],
            activate_point_rule_payload("2030-05-01T00:00:00.000Z"),
            make_community_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_RULE_BACKDATING.value)

    def test_activate_when_predecessor_active_yields_rule_already_active(
        self, api,
    ):
        """PRD §3.2: 'Activation by a CommunityAdmin requires that the rule
        is currently in DRAFT and that no other PointRule with the same
        (community_id, category) is currently ACTIVE; a competing predecessor
        must be retired first or the activation is rejected with
        ERR_RULE_ALREADY_ACTIVE.'"""
        advance_clock("2030-01-01T00:00:00.000Z")
        community = create_community()
        setup_active_point_rule(
            community["id"], "2030-01-01T00:00:00.000Z",
            category="RECYCLABLE",
        )
        # Create a second RECYCLABLE rule in DRAFT and attempt activation.
        rule_b = create_point_rule(community["id"], category="RECYCLABLE")
        resp = api.activate_point_rule(
            community["id"], rule_b["id"],
            activate_point_rule_payload("2030-01-02T00:00:00.000Z"),
            make_community_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_RULE_ALREADY_ACTIVE.value)

    def test_activate_different_category_succeeds_alongside_predecessor(
        self, api,
    ):
        """PRD §3.2: 'no other PointRule with the same (community_id,
        category) is currently ACTIVE'. Different category is allowed."""
        advance_clock("2030-01-01T00:00:00.000Z")
        community = create_community()
        setup_active_point_rule(
            community["id"], "2030-01-01T00:00:00.000Z",
            category="RECYCLABLE",
        )
        rule_haz = setup_active_point_rule(
            community["id"], "2030-01-01T00:00:00.000Z",
            category="HAZARDOUS",
        )
        assert rule_haz["status"] == "ACTIVE"


class TestPointRuleRetirement:
    def test_retire_active_rule_sets_retired_at(self, api):
        """PRD §3.2: 'Retirement ... only succeeds when the rule is currently
        ACTIVE: it transitions to RETIRED, sets retired_at to the current
        logical clock.'"""
        advance_clock("2030-01-01T00:00:00.000Z")
        community = create_community()
        rule = setup_active_point_rule(
            community["id"], "2030-01-01T00:00:00.000Z",
        )
        advance_clock("2030-02-01T00:00:00.000Z")
        retired = retire_point_rule(community["id"], rule["id"])
        assert retired["status"] == "RETIRED"
        assert retired["retired_at"] is not None

    def test_after_retire_new_rule_can_activate(self, api):
        """PRD §3.2: 'a competing predecessor must be retired first.'"""
        advance_clock("2030-01-01T00:00:00.000Z")
        community = create_community()
        rule_a = setup_active_point_rule(
            community["id"], "2030-01-01T00:00:00.000Z",
            category="RECYCLABLE",
        )
        advance_clock("2030-02-01T00:00:00.000Z")
        retire_point_rule(community["id"], rule_a["id"])
        rule_b = create_point_rule(community["id"], category="RECYCLABLE")
        activated = activate_point_rule(
            community["id"], rule_b["id"], "2030-02-01T00:00:00.000Z",
        )
        assert activated["status"] == "ACTIVE"
