"""Channel mapping sync, per-channel rounding, and the parity band.

Covers channel_sync: the per-channel rounded channel_rate, the net-rate parity
comparison against DIRECT, and the publish -> channel re-sync cascade hop.
"""
from test_helpers import (
    validate_success,
    TEST_USERS,
    set_clock,
    create_property,
    create_room_type,
    create_rate_plan,
    create_inventory_day,
    create_rate_decision,
    create_channel_mapping,
)

RM = TEST_USERS["revenue_manager_headers"]
CM = TEST_USERS["channel_manager_headers"]


class TestChannelRoundingAndParity:
    def test_channel_rate_rounded_per_channel_then_parity_compared(self, api):
        """PRD §3.6: "otherwise it is the plan's `published_rate` multiplied by the
        quantity one plus the channel's `markup_pct`, rounded half-up to 2 decimal
        places."
        PRD §3.6: "a purely synced channel carrying no override always nets back to
        the published rate and is likewise `IN_PARITY`."

        Design: Difficulty/combinatorial_formula/channel_rate_round_per_channel_then_parity_compare
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="Vista", total_rooms=50)
        rt = create_room_type(prop["id"], code="DLX", name="Deluxe", physical_rooms=50)
        plan = create_rate_plan(
            rt["id"], rate_class="BAR", is_master_bar=True,
            base_rate=233.33, floor_rate=100, ceiling_rate=500,
        )
        create_inventory_day(rt["id"], "2026-06-05T00:00:00Z", physical_capacity=50, transient_sold_rooms=10)
        create_channel_mapping(plan["id"], "DIRECT", markup_pct=0.0)
        ota_a = create_channel_mapping(plan["id"], "OTA_A", markup_pct=0.18)
        dec = create_rate_decision(plan["id"], "2026-06-05T00:00:00Z", requested_rate=233.33)
        validate_success(api.publish_rate_decision(dec["id"], {"expected_rate_plan_version": plan["version"]}, RM))

        data = validate_success(api.get_channel_mapping(ota_a["id"], CM))
        # round(233.33 * 1.18, 2) = 275.33; net 275.33/1.18 = 233.33 == direct net -> IN_PARITY
        assert data["channel_rate"] == 275.33, f"expected 275.33 got {data['channel_rate']}"
        assert data["parity_status"] == "IN_PARITY"

    def test_direct_mapping_is_always_in_parity(self, api):
        """PRD §3.6: "The `DIRECT` mapping is always its own parity reference and is
        therefore always `IN_PARITY`, and a purely synced channel carrying no
        override always nets back to the published rate and is likewise
        `IN_PARITY`."

        Design: Difficulty/combinatorial_formula/channel_rate_round_per_channel_then_parity_compare
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="VistaDirect", total_rooms=50)
        rt = create_room_type(prop["id"], code="DLX", name="Deluxe", physical_rooms=50)
        plan = create_rate_plan(
            rt["id"], rate_class="BAR", is_master_bar=True,
            base_rate=233.33, floor_rate=100, ceiling_rate=500,
        )
        create_inventory_day(rt["id"], "2026-06-05T00:00:00Z", physical_capacity=50, transient_sold_rooms=10)
        direct = create_channel_mapping(plan["id"], "DIRECT", markup_pct=0.0)
        create_channel_mapping(plan["id"], "OTA_A", markup_pct=0.18)
        dec = create_rate_decision(plan["id"], "2026-06-05T00:00:00Z", requested_rate=233.33)
        validate_success(api.publish_rate_decision(dec["id"], {"expected_rate_plan_version": plan["version"]}, RM))
        data = validate_success(api.get_channel_mapping(direct["id"], CM))
        # DIRECT markup 0 -> channel_rate round(233.33*1.0,2)=233.33; always IN_PARITY
        assert data["channel_rate"] == 233.33, f"expected 233.33 got {data['channel_rate']}"
        assert data["parity_status"] == "IN_PARITY"

    def test_manual_override_undercutting_direct_is_out_of_parity(self, api):
        """PRD §3.6: "A channel's `channel_rate` is its `manual_rate_override` when
        that override is set."
        PRD §3.6: "A channel is judged `OUT_OF_PARITY` when its net rate is strictly
        less than the direct net rate reduced by a parity tolerance of 2% of the
        direct net rate (that is, less than the direct net rate multiplied by the
        quantity one minus 0.02); otherwise it is `IN_PARITY`."

        Design: Corner/calculations/parity_out_of_parity_on_manual_override
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="Parity", total_rooms=50)
        rt = create_room_type(prop["id"], code="STD", name="Standard", physical_rooms=50)
        plan = create_rate_plan(
            rt["id"], rate_class="BAR", is_master_bar=True,
            base_rate=230, floor_rate=100, ceiling_rate=400,
        )
        create_inventory_day(rt["id"], "2026-06-06T00:00:00Z", physical_capacity=50, transient_sold_rooms=10)
        create_channel_mapping(plan["id"], "DIRECT", markup_pct=0.0)
        ota_b = create_channel_mapping(plan["id"], "OTA_B", markup_pct=0.15)
        dec = create_rate_decision(plan["id"], "2026-06-06T00:00:00Z", requested_rate=230)
        validate_success(api.publish_rate_decision(dec["id"], {"expected_rate_plan_version": plan["version"]}, RM))

        # override 200: channel_rate 200; net 200/1.15=173.91 < direct net 230*0.98=225.4 -> OUT_OF_PARITY
        data = validate_success(api.update_channel_mapping(ota_b["id"], {"manual_rate_override": 200.0}, CM))
        assert data["channel_rate"] == 200.00, f"expected 200.00 got {data['channel_rate']}"
        assert data["parity_status"] == "OUT_OF_PARITY"


class TestPublishChannelCascade:
    def test_publish_master_bar_resyncs_channel_rate(self, api):
        """PRD §3.4: "**Hop 2:** only when the published decision's plan is the room
        type's master BAR plan, every channel mapping under that plan re-syncs its
        `channel_rate` and recomputes its `parity_status` (the channel sync of
        §3.6)."
        PRD §3.6: "otherwise it is the plan's `published_rate` multiplied by the
        quantity one plus the channel's `markup_pct`, rounded half-up to 2 decimal
        places."

        Design: Difficulty/transitive_cascade/publish_sets_rate_then_resyncs_channel_depth2
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="Cascade2", total_rooms=50)
        rt = create_room_type(prop["id"], code="STD", name="Standard", physical_rooms=50)
        plan = create_rate_plan(
            rt["id"], rate_class="BAR", is_master_bar=True,
            base_rate=200, floor_rate=100, ceiling_rate=400,
        )
        create_inventory_day(rt["id"], "2026-06-08T00:00:00Z", physical_capacity=50, transient_sold_rooms=10)
        create_channel_mapping(plan["id"], "DIRECT", markup_pct=0.0)
        ota = create_channel_mapping(plan["id"], "OTA_A", markup_pct=0.18)
        dec = create_rate_decision(plan["id"], "2026-06-08T00:00:00Z", requested_rate=200)
        published = validate_success(api.publish_rate_decision(dec["id"], {"expected_rate_plan_version": plan["version"]}, RM))
        assert published["yielded_rate"] == 200.00

        # plan published_rate now 200; OTA_A re-syncs to round(200*1.18,2)=236.00
        plan_after = validate_success(api.get_rate_plan(plan["id"], RM))
        assert plan_after["published_rate"] == 200.00, f"expected 200.00 got {plan_after['published_rate']}"
        ota_after = validate_success(api.get_channel_mapping(ota["id"], CM))
        assert ota_after["channel_rate"] == 236.00, f"expected 236.00 got {ota_after['channel_rate']}"

    def test_publish_sets_published_rate_hop1(self, api):
        """PRD §3.4: "The decision's `yielded_rate` becomes the plan's
        `published_rate`, and the plan's `version` increments by 1."

        Design: Difficulty/transitive_cascade/publish_sets_rate_then_resyncs_channel_depth2
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="Cascade2b", total_rooms=50)
        rt = create_room_type(prop["id"], code="STD", name="Standard", physical_rooms=50)
        plan = create_rate_plan(
            rt["id"], rate_class="BAR", is_master_bar=True,
            base_rate=200, floor_rate=100, ceiling_rate=400,
        )
        create_inventory_day(rt["id"], "2026-06-08T00:00:00Z", physical_capacity=50, transient_sold_rooms=10)
        create_channel_mapping(plan["id"], "DIRECT", markup_pct=0.0)
        create_channel_mapping(plan["id"], "OTA_A", markup_pct=0.18)
        dec = create_rate_decision(plan["id"], "2026-06-08T00:00:00Z", requested_rate=200)
        before_v = plan["version"]
        validate_success(api.publish_rate_decision(dec["id"], {"expected_rate_plan_version": before_v}, RM))
        plan_after = validate_success(api.get_rate_plan(plan["id"], RM))
        # hop 1: published_rate set from yielded_rate, plan version bumped
        assert plan_after["published_rate"] == 200.00, f"expected 200.00 got {plan_after['published_rate']}"
        assert plan_after["version"] == before_v + 1, (
            f"plan version must increment on publish, got {plan_after['version']} from {before_v}"
        )
