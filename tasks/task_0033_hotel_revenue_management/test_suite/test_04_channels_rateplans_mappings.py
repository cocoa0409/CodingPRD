"""Channels, rate plans, and channel-rate-plan mappings (PRD §3.2)."""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_channel,
    assert_channel_rate_plan_mapping,
    assert_rate_plan,
    create_channel,
    create_channel_payload,
    create_channel_rate_plan_mapping_payload,
    create_mapping,
    create_rate_plan,
    create_rate_plan_payload,
    create_room_type,
    unique_priority_rank,
    validate_error,
    validate_success,
)


# ===========================================================================
# Channel create
# ===========================================================================
class TestChannelCreate:
    def test_create_channel_success(self, api, admin_headers):
        """PRD §3.2: 'A PlatformAdmin registers a channel by supplying its
        uppercase short code (unique across active channels), its
        channel_type ... a commission_basis_points value between 0 and 5000
        inclusive ... and a priority_rank of at least 1.'"""
        rank = unique_priority_rank()
        res = api.create_channel(
            create_channel_payload(
                channel_type="OTA", commission_basis_points=1500,
                priority_rank=rank,
            ),
            admin_headers,
        )
        ch = validate_success(res, expected_status=201)
        assert_channel(ch)
        assert ch["channel_type"] == "OTA"
        assert ch["commission_basis_points"] == 1500
        assert ch["priority_rank"] == rank
        assert ch["status"] == "ACTIVE"

    def test_duplicate_priority_rank_rejected(self, api, admin_headers):
        """PRD §3.2: 'ranks are unique across active channels, and any
        attempted duplicate is rejected with ERR_DUPLICATE_PRIORITY_RANK.'"""
        rank = unique_priority_rank()
        first = create_channel(priority_rank=rank)
        # Second create with the same priority_rank
        res2 = api.create_channel(
            create_channel_payload(priority_rank=rank), admin_headers,
        )
        validate_error(res2, "ERR_DUPLICATE_PRIORITY_RANK")

    def test_commission_above_max_rejected(self, api, admin_headers):
        """PRD §3.2: 'a commission_basis_points value between 0 and 5000
        inclusive (so commissions range from zero up to 50%).'"""
        res = api.create_channel(
            create_channel_payload(commission_basis_points=5001),
            admin_headers,
        )
        validate_error(res, "ERR_INVALID_INPUT")

    def test_priority_rank_zero_rejected(self, api, admin_headers):
        """PRD §3.2: 'a priority_rank of at least 1.'"""
        res = api.create_channel(
            create_channel_payload(priority_rank=0), admin_headers,
        )
        validate_error(res, "ERR_INVALID_INPUT")


# ===========================================================================
# RatePlan create
# ===========================================================================
class TestRatePlanCreate:
    def test_create_rate_plan_success(self, api, manager_headers):
        """PRD §3.2: 'A PlatformAdmin or RevenueManager creates a rate
        plan with its uppercase short code (unique across active plans),
        the room_type_id it applies to, a refund_tier_code ... and a
        boolean modification_allowed flag (which defaults to true).'"""
        rt = create_room_type()
        res = api.create_rate_plan(
            create_rate_plan_payload(
                room_type_id=rt["id"], refund_tier_code="MODERATE",
                modification_allowed=True,
            ),
            manager_headers,
        )
        plan = validate_success(res, expected_status=201)
        assert_rate_plan(plan)
        assert plan["room_type_id"] == rt["id"]
        assert plan["refund_tier_code"] == "MODERATE"
        assert plan["modification_allowed"] is True
        assert plan["status"] == "ACTIVE"


# ===========================================================================
# ChannelRatePlanMapping
# ===========================================================================
class TestChannelRatePlanMapping:
    def test_create_mapping_success(self, api, manager_headers):
        """PRD §3.2: 'A PlatformAdmin or RevenueManager creates the
        mapping by supplying the channel_id, the rate_plan_id, and an
        inventory_share_basis_points in the inclusive range from 0 to
        10000.'"""
        rt = create_room_type()
        plan = create_rate_plan(room_type_id=rt["id"])
        ch = create_channel()
        res = api.create_channel_rate_plan_mapping(
            create_channel_rate_plan_mapping_payload(
                channel_id=ch["id"], rate_plan_id=plan["id"],
                inventory_share_basis_points=5000,
            ),
            manager_headers,
        )
        mp = validate_success(res, expected_status=201)
        assert_channel_rate_plan_mapping(mp)
        assert mp["inventory_share_basis_points"] == 5000
        assert mp["enabled"] is True

    def test_mapping_carries_only_id_and_created_at(self, api, manager_headers):
        """PRD §2.4: 'the ChannelRatePlanMapping is an immutable join row
        that carries only id and created_at — both updated_at and version
        are absent.'"""
        rt = create_room_type()
        plan = create_rate_plan(room_type_id=rt["id"])
        ch = create_channel()
        mp = create_mapping(
            channel_id=ch["id"], rate_plan_id=plan["id"],
            inventory_share_basis_points=10000,
        )
        # The shared assertion already covers the absence of updated_at /
        # version. Explicit check here for the literal PRD claim.
        assert "updated_at" not in mp
        assert "version" not in mp

    def test_inventory_share_sum_above_10000_rejected(
        self, api, manager_headers,
    ):
        """PRD §3.2: 'On creation, the system validates that the sum of
        inventory_share_basis_points across all mappings sharing the same
        rate_plan_id does not exceed 10000 after the new row is taken
        into account; if it would, the request is rejected with
        ERR_INVENTORY_SHARE_EXCEEDED.'"""
        rt = create_room_type()
        plan = create_rate_plan(room_type_id=rt["id"])
        ch1 = create_channel()
        ch2 = create_channel()
        # First mapping at 7000bp
        first = api.create_channel_rate_plan_mapping(
            create_channel_rate_plan_mapping_payload(
                channel_id=ch1["id"], rate_plan_id=plan["id"],
                inventory_share_basis_points=7000,
            ),
            manager_headers,
        )
        validate_success(first, expected_status=201)
        # Second mapping at 4000bp would push sum to 11000bp.
        second = api.create_channel_rate_plan_mapping(
            create_channel_rate_plan_mapping_payload(
                channel_id=ch2["id"], rate_plan_id=plan["id"],
                inventory_share_basis_points=4000,
            ),
            manager_headers,
        )
        validate_error(second, "ERR_INVENTORY_SHARE_EXCEEDED")

    def test_inventory_share_sum_at_exactly_10000_allowed(
        self, api, manager_headers,
    ):
        """PRD §3.2: 'sum of inventory_share_basis_points across all
        mappings sharing the same rate_plan_id does not exceed 10000.'
        Sum == 10000 is allowed; only > 10000 is forbidden."""
        rt = create_room_type()
        plan = create_rate_plan(room_type_id=rt["id"])
        ch1 = create_channel()
        ch2 = create_channel()
        first = api.create_channel_rate_plan_mapping(
            create_channel_rate_plan_mapping_payload(
                channel_id=ch1["id"], rate_plan_id=plan["id"],
                inventory_share_basis_points=4000,
            ),
            manager_headers,
        )
        validate_success(first, expected_status=201)
        second = api.create_channel_rate_plan_mapping(
            create_channel_rate_plan_mapping_payload(
                channel_id=ch2["id"], rate_plan_id=plan["id"],
                inventory_share_basis_points=6000,
            ),
            manager_headers,
        )
        validate_success(second, expected_status=201)
