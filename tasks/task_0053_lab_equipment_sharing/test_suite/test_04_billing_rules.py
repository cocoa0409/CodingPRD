"""Billing rules — draft, publish, supersede, fee-split validation.

PRD §3.5 (Billing rules and fee calculation).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    assert_billing_rule,
    create_billing_rule_payload,
    draft_billing_rule,
    draft_and_publish_billing_rule,
    make_lab_owner_headers,
    publish_billing_rule,
    setup_basic_scenario,
    validate_error,
    validate_success,
)


# ===========================================================================
# Draft and publish (PRD §3.5)
# ===========================================================================
class TestBillingRuleDraftPublish:
    """PRD §3.5: 'The draft is created with status DRAFT and no assigned
    rule_version ... Publishing transitions the rule to PUBLISHED ... On
    successful publish, the previously PUBLISHED rule for the same
    equipment (if any) is moved to SUPERSEDED, the new rule's
    rule_version is assigned as one greater than the maximum existing
    rule_version for the equipment (starting at 1 if none exist), the
    equipment's active_billing_rule_id is updated to the new rule's id,
    and published_at is set to the server clock.'
    """

    def test_draft_has_status_draft(self, api):
        """PRD §3.5: 'The draft is created with status DRAFT'."""
        s = setup_basic_scenario()
        rule = draft_billing_rule(
            equipment=s["equipment"], owner_user=s["owner_user"],
        )
        assert_billing_rule(rule)
        assert rule["status"] == "DRAFT"

    def test_publish_transitions_to_published(self, api):
        """PRD §3.5: 'Publishing transitions the rule to PUBLISHED'."""
        s = setup_basic_scenario()
        rule = draft_billing_rule(
            equipment=s["equipment"], owner_user=s["owner_user"],
        )
        published = publish_billing_rule(
            equipment=s["equipment"], rule=rule,
            owner_user=s["owner_user"],
        )
        assert published["status"] == "PUBLISHED"

    def test_publish_supersedes_previous_published_rule(self, api):
        """PRD §3.5: 'On successful publish, the previously PUBLISHED rule
        for the same equipment (if any) is moved to SUPERSEDED'."""
        s = setup_basic_scenario()
        # The basic setup already published a rule; publish another.
        old_rule = s["rule"]
        new_rule = draft_and_publish_billing_rule(
            equipment=s["equipment"], owner_user=s["owner_user"],
        )
        owner_h = make_lab_owner_headers(s["owner_user"]["id"])
        from test_helpers import validate_paginated
        data, _ = validate_paginated(api.list_billing_rules(
            s["equipment"]["id"], owner_h,
        ))
        statuses = {r["id"]: r["status"] for r in data}
        assert statuses[old_rule["id"]] == "SUPERSEDED"
        assert statuses[new_rule["id"]] == "PUBLISHED"

    def test_publish_updates_active_billing_rule_id(self, api):
        """PRD §3.5: 'the equipment's active_billing_rule_id is updated to
        the new rule's id'."""
        s = setup_basic_scenario()
        new_rule = draft_and_publish_billing_rule(
            equipment=s["equipment"], owner_user=s["owner_user"],
        )
        from test_helpers import get_equipment
        eq = get_equipment(s["equipment"]["id"])
        assert eq["active_billing_rule_id"] == new_rule["id"]


# ===========================================================================
# Fee split validation (PRD §3.5)
# ===========================================================================
class TestFeeSplitValidation:
    """PRD §3.5: 'At publish, the system checks ... that the sum of
    platform_fee_bps and the owning lab's revenue_share_bps does not
    exceed 10000 — if it does, the publish is rejected with
    ERR_FEE_SPLIT_INVALID.'
    """

    def test_fee_split_over_10000_rejected(self, api):
        """PRD §3.5: 'the sum of platform_fee_bps and the owning lab's
        revenue_share_bps does not exceed 10000 — if it does, the publish
        is rejected with ERR_FEE_SPLIT_INVALID'."""
        # Lab.revenue_share_bps default is 8000; pick platform_fee_bps
        # so 8000 + 2500 = 10500 > 10000.
        s = setup_basic_scenario(revenue_share_bps=8000)
        draft = draft_billing_rule(
            equipment=s["equipment"], owner_user=s["owner_user"],
            platform_fee_bps=2500,
        )
        res = api.publish_billing_rule(
            s["equipment"]["id"], draft["id"],
            make_lab_owner_headers(s["owner_user"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FEE_SPLIT_INVALID.value)

    def test_fee_split_exactly_10000_accepted(self, api):
        """PRD §3.5: 'does not exceed 10000' — exactly 10000 is permitted.
        """
        s = setup_basic_scenario(revenue_share_bps=8000)
        draft = draft_billing_rule(
            equipment=s["equipment"], owner_user=s["owner_user"],
            platform_fee_bps=2000,
        )
        res = api.publish_billing_rule(
            s["equipment"]["id"], draft["id"],
            make_lab_owner_headers(s["owner_user"]["id"]),
        )
        published = validate_success(res, 200)
        assert published["status"] == "PUBLISHED"
