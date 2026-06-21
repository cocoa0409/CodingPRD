"""Role-based access control, authentication, and optimistic concurrency control.

Covers ERR_FORBIDDEN for cross-role calls, ERR_UNAUTHENTICATED for an unknown
role, and ERR_STALE_VERSION for stale-parent publish/commit (OCC). Also covers
the paginated list envelope.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    TEST_USERS,
    UNKNOWN_ROLE_HEADERS,
    set_clock,
    create_property,
    create_room_type,
    create_rate_plan,
    create_inventory_day,
    create_rate_decision,
    publish_decision,
    create_group_block,
    evaluate_group_block,
    commit_group_block,
    ApiErrorId,
    PLACEHOLDER_GENERIC_ID,
)

RM = TEST_USERS["revenue_manager_headers"]
GSM = TEST_USERS["group_sales_manager_headers"]
CM = TEST_USERS["channel_manager_headers"]
ANALYST = TEST_USERS["analyst_headers"]


class TestRbacDenials:
    def test_group_sales_manager_cannot_publish(self, api):
        """PRD §2.1: "The `RevenueManager` owns rate strategy — properties, room
        types, rate plans, inventory days, yield rules, rate decisions,
        group-displacement evaluation, and competitor-rate entry."
        PRD §2.1: "When the headers are well-formed but the named role is not
        permitted to perform the requested operation, the request is rejected with
        `ERR_FORBIDDEN`."

        Design: Corner/rbac/group_sales_manager_cannot_publish_rate_decision
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="RbacPub", total_rooms=40)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=40)
        plan = create_rate_plan(rt["id"], rate_class="BAR", is_master_bar=True, base_rate=200, floor_rate=100, ceiling_rate=400)
        create_inventory_day(rt["id"], "2026-06-05T00:00:00Z", physical_capacity=40, transient_sold_rooms=5)
        dec = create_rate_decision(plan["id"], "2026-06-05T00:00:00Z", requested_rate=200)
        resp = api.publish_rate_decision(dec["id"], {"expected_rate_plan_version": plan["version"]}, GSM)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_analyst_cannot_create_property(self, api):
        """PRD §2.1: "The `Analyst` is a read-only consumer of KPIs, forecasts,
        yield rules, decisions, and blocks."
        PRD §2.1: "When the headers are well-formed but the named role is not
        permitted to perform the requested operation, the request is rejected with
        `ERR_FORBIDDEN`."

        Design: Corner/rbac/analyst_cannot_create_property
        """
        resp = api.create_property({"name": "AnalystTry", "total_rooms": 10}, ANALYST)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_channel_manager_cannot_commit_group_block(self, api):
        """PRD §2.1: "The `GroupSalesManager` owns the group-block lifecycle —
        creating, revising, committing, and cancelling blocks."
        PRD §2.1: "When the headers are well-formed but the named role is not
        permitted to perform the requested operation, the request is rejected with
        `ERR_FORBIDDEN`."

        Design: Corner/rbac/channel_manager_cannot_commit_group_block
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="RbacCommit", total_rooms=30)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=30)
        create_inventory_day(rt["id"], "2026-06-05T00:00:00Z", physical_capacity=30, transient_sold_rooms=2)
        gb = create_group_block(
            rt["id"], "2026-06-05T00:00:00Z", group_name="Quebec",
            nights=1, rooms_per_night=2, offered_rate=400,
        )
        evaluate_group_block(gb["id"], "LRV")
        resp = api.commit_group_block(gb["id"], {"expected_room_type_version": rt["version"]}, CM)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_unknown_role_returns_unauthenticated(self, api):
        """PRD §2.1: "If either header is missing, or if `X-User-Role` does not name
        a role the system recognizes, the request is rejected with
        `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/missing_role_header_returns_401
        """
        resp = api.get_property(PLACEHOLDER_GENERIC_ID, UNKNOWN_ROLE_HEADERS)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


class TestOptimisticConcurrency:
    def test_publish_stale_rate_plan_version_rejected(self, api):
        """PRD §2.10: "The publish request must carry `expected_rate_plan_version`,
        the `version` of the rate plan the client last read. If that value does not
        equal the rate plan's current `version` — which happens, for instance, when
        another writer has already published a decision for this plan, superseding
        the prior effective rate and bumping the plan's `version` — the publish is
        rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from
        overwriting pricing it has not actually observed."

        Design: Corner/cross_cutting_complexity_layers/occ_publish_stale_rate_plan_version_412
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="OccPub", total_rooms=50)
        rt = create_room_type(prop["id"], code="STD", name="Standard", physical_rooms=50)
        plan = create_rate_plan(rt["id"], rate_class="BAR", is_master_bar=True, base_rate=200, floor_rate=100, ceiling_rate=400)
        create_inventory_day(rt["id"], "2026-06-21T00:00:00Z", physical_capacity=50, transient_sold_rooms=10)
        plan_v0 = plan["version"]
        dec1 = create_rate_decision(plan["id"], "2026-06-21T00:00:00Z", requested_rate=200)
        dec2 = create_rate_decision(plan["id"], "2026-06-21T00:00:00Z", requested_rate=250)
        publish_decision(dec1["id"], plan_v0)  # bumps plan version to v0+1
        # second publish with the now-stale v0 -> ERR_STALE_VERSION
        resp = api.publish_rate_decision(dec2["id"], {"expected_rate_plan_version": plan_v0}, RM)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
        dec2_after = validate_success(api.get_rate_decision(dec2["id"], RM))
        assert dec2_after["status"] == "DRAFT", f"stale publish must not transition, got {dec2_after['status']}"

    def test_commit_stale_room_type_version_rejected(self, api):
        """PRD §2.10: "The commit request must carry `expected_room_type_version`,
        the `version` of the room type the client last read. If that value does not
        equal the room type's current `version` — which happens, for instance, when
        another group block was just committed on the same room type, consuming
        shared inventory and bumping the room type's `version` — the commit is
        rejected with `ERR_STALE_VERSION` (HTTP 412), so the committing client
        cannot act on an availability picture that no longer holds."

        Design: Corner/cross_cutting_complexity_layers/occ_commit_stale_room_type_version_412
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="OccCommit", total_rooms=30)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=30)
        create_inventory_day(rt["id"], "2026-06-22T00:00:00Z", physical_capacity=30, transient_sold_rooms=2)
        rt_v0 = rt["version"]
        gb1 = create_group_block(rt["id"], "2026-06-22T00:00:00Z", group_name="Romeo", nights=1, rooms_per_night=3, offered_rate=400)
        evaluate_group_block(gb1["id"], "LRV")
        gb2 = create_group_block(rt["id"], "2026-06-22T00:00:00Z", group_name="Sierra", nights=1, rooms_per_night=3, offered_rate=400)
        evaluate_group_block(gb2["id"], "LRV")
        commit_group_block(gb1["id"], rt_v0)  # bumps room type version to v0+1
        # second commit with the now-stale v0 -> ERR_STALE_VERSION
        resp = api.commit_group_block(gb2["id"], {"expected_room_type_version": rt_v0}, GSM)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
        gb2_after = validate_success(api.get_group_block(gb2["id"], GSM))
        assert gb2_after["status"] == "NEGOTIATING", f"stale commit must not transition, got {gb2_after['status']}"


class TestListPagination:
    def test_list_inventory_days_paginated_envelope(self, api):
        """PRD §2.3: "Every list response carries the pagination fields `limit`,
        `offset`, `total_count`, and `has_more` inside the envelope's `meta`
        object."

        Design: Corner/endpoints/list_inventory_days_paginated_envelope
        """
        prop = create_property(name="ListInv", total_rooms=30)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=30)
        create_inventory_day(rt["id"], "2026-06-06T00:00:00Z", physical_capacity=30, transient_sold_rooms=2)
        create_inventory_day(rt["id"], "2026-06-07T00:00:00Z", physical_capacity=30, transient_sold_rooms=3)
        resp = api.list_inventory_days(ANALYST, params={"room_type_id": rt["id"], "limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2, f"expected total_count 2 got {meta['total_count']}"
        assert meta["has_more"] is True
        assert len(data) == 1, f"expected 1 item got {len(data)}"
