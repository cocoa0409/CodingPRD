"""Load dispatch and delivery: the biosecurity battery (verified/type/
staleness/reuse), delivery date gate, weight-window branches, and the
close-out cascade a draining delivery fires.
"""
from test_helpers import (
    ApiErrorId,
    assert_settlement_pay_invariants,
    get_success_data,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import create_truck_wash_payload
from test_helpers.fixtures import (
    ADMIN,
    FIELDTECH,
    TRANSPORT,
    book_load,
    confirm_group,
    create_and_deliver_feed,
    create_slot,
    create_verified_truck_wash,
    create_scheduled_group,
    deliver_load,
    dispatch_load,
    get_barn,
    get_group,
    get_settlement_for_group,
    record_truck_wash,
    set_clock,
    setup_contract_with_barn,
    setup_dispatched_load,
    setup_placed_group,
)

JULY_SLOT = {"slot_date": "2026-07-13", "shift": "AM", "capacity_head": 500,
             "min_weight_lbs": 240, "max_weight_lbs": 320}


class TestDispatchRequiresVerifiedWash:
    def test_dispatch_requires_verified_truck_wash(self, api):
        """PRD §3.5: "The referenced wash must be `VERIFIED`
        (`ERR_WASH_NOT_VERIFIED`) and of type `FULL_DISINFECT`
        (`ERR_WASH_TYPE_INSUFFICIENT`)".
        PRD §3.5: "Dispatching a load, done by a `TransportCoordinator`
        supplying the `truck_wash_id`, moves it `SCHEDULED` → `DISPATCHED` ...
        A successful dispatch records the wash on the load."

        The same wash flips the outcome: RECORDED rejects, VERIFIED dispatches.

        Design: Difficulty/cross_entity_state_dependency/dispatch_requires_verified_truck_wash
        """
        ctx = setup_placed_group(head_placed=500)
        slot = create_slot(**JULY_SLOT)
        load = book_load(ctx["group"]["id"], slot["id"], 100)

        set_clock("2026-07-12T08:00:00Z")
        wash = record_truck_wash("2026-07-12T08:00:00Z")
        assert wash["wash_status"] == "RECORDED"

        res = api.dispatch_market_load(
            load["id"], {"truck_wash_id": wash["id"]}, TRANSPORT
        )
        validate_error(res, ApiErrorId.ERR_WASH_NOT_VERIFIED, expected_status=409)
        assert get_success_data(
            api.get_market_load(load["id"], TRANSPORT)
        )["load_status"] == "SCHEDULED"

        verified = validate_success(api.verify_truck_wash(wash["id"], ADMIN), 200)
        assert verified["wash_status"] == "VERIFIED"
        assert verified["verified_by"] == "adm_1"

        dispatched = dispatch_load(load["id"], wash["id"])
        assert dispatched["load_status"] == "DISPATCHED"
        assert dispatched["truck_wash_id"] == wash["id"]

    def test_rejected_wash_also_fails_dispatch(self, api):
        """PRD §3.5: "The referenced wash must be `VERIFIED`
        (`ERR_WASH_NOT_VERIFIED`)" — a REJECTED wash is not VERIFIED.
        PRD §3.5: "An `IntegratorAdmin` then verifies it — `RECORDED` →
        `VERIFIED`, stamping `verified_by` — or rejects it — `RECORDED` →
        `REJECTED`".

        Design: Difficulty/cross_entity_state_dependency/dispatch_requires_verified_truck_wash
        """
        ctx = setup_placed_group(head_placed=500)
        slot = create_slot(**JULY_SLOT)
        load = book_load(ctx["group"]["id"], slot["id"], 100)

        set_clock("2026-07-12T08:00:00Z")
        rejected_wash = record_truck_wash("2026-07-12T08:00:00Z", truck_code="T-R")
        get_success_data(api.reject_truck_wash(rejected_wash["id"], ADMIN))
        res = api.dispatch_market_load(
            load["id"], {"truck_wash_id": rejected_wash["id"]}, TRANSPORT
        )
        validate_error(res, ApiErrorId.ERR_WASH_NOT_VERIFIED, expected_status=409)

        good_wash = create_verified_truck_wash("2026-07-12T08:00:00Z",
                                               truck_code="T-G")
        dispatched = dispatch_load(load["id"], good_wash["id"])
        assert dispatched["load_status"] == "DISPATCHED"


class TestSafetyBeatsTemporal:
    def test_unverified_and_stale_wash_reports_unverified(self, api):
        """PRD §2.6: "A dispatch request whose truck wash is both unverified
        and older than forty-eight hours is rejected with
        `ERR_WASH_NOT_VERIFIED`, never `ERR_WASH_STALE`, because biosecurity
        outranks temporal checks."

        The wash is 100h old AND never verified: safety wins the report.

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_temporal_dispatch_wash_unverified_and_stale
        """
        ctx = setup_placed_group(head_placed=500)
        slot = create_slot(**JULY_SLOT)
        set_clock("2026-07-08T00:00:00Z")
        load = book_load(ctx["group"]["id"], slot["id"], 100)
        wash = record_truck_wash("2026-07-03T20:00:00Z")  # 100h stale, RECORDED

        res = api.dispatch_market_load(
            load["id"], {"truck_wash_id": wash["id"]}, TRANSPORT
        )
        err = validate_error(res, ApiErrorId.ERR_WASH_NOT_VERIFIED,
                             expected_status=409)
        assert err["error_id"] != "ERR_WASH_STALE"
        assert get_success_data(
            api.get_market_load(load["id"], TRANSPORT)
        )["load_status"] == "SCHEDULED"

    def test_verified_but_stale_wash_reports_stale(self, api):
        """PRD §3.5: "the dispatch instant must fall within forty-eight hours
        of `washed_at`, with a dispatch exactly forty-eight hours after the
        wash still valid and anything later rejected as `ERR_WASH_STALE`".

        With safety satisfied (VERIFIED, FULL_DISINFECT, unused), the temporal
        staleness check is the one that fires.

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_temporal_dispatch_wash_unverified_and_stale
        """
        ctx = setup_placed_group(head_placed=500)
        slot = create_slot(**JULY_SLOT)
        set_clock("2026-07-08T00:00:00Z")
        load = book_load(ctx["group"]["id"], slot["id"], 100)
        wash = create_verified_truck_wash("2026-07-03T20:00:00Z")
        assert wash["wash_status"] == "VERIFIED"

        res = api.dispatch_market_load(
            load["id"], {"truck_wash_id": wash["id"]}, TRANSPORT
        )
        validate_error(res, ApiErrorId.ERR_WASH_STALE, expected_status=409)


class TestWashGates:
    def test_wash_reuse_rejected(self, api):
        """PRD §3.5: "the wash must not already back another load in
        `DISPATCHED`, `DELIVERED`, or `REJECTED_AT_PLANT`
        (`ERR_WASH_ALREADY_USED`)".

        Design: Corner/errors/wash_reuse_rejected
        """
        ctx = setup_placed_group(head_placed=1000)
        slot = create_slot(**JULY_SLOT)
        load1 = book_load(ctx["group"]["id"], slot["id"], 100)
        load2 = book_load(ctx["group"]["id"], slot["id"], 100)

        set_clock("2026-07-12T08:00:00Z")
        wash = create_verified_truck_wash("2026-07-12T08:00:00Z")
        dispatch_load(load1["id"], wash["id"])

        res = api.dispatch_market_load(
            load2["id"], {"truck_wash_id": wash["id"]}, TRANSPORT
        )
        validate_error(res, ApiErrorId.ERR_WASH_ALREADY_USED, expected_status=409)
        assert get_success_data(
            api.get_market_load(load2["id"], TRANSPORT)
        )["load_status"] == "SCHEDULED"

    def test_wash_only_type_insufficient(self, api):
        """PRD §2.10: "Only a verified wash of type `FULL_DISINFECT` is
        biosecure enough to back a pig movement — a `WASH_ONLY` wash never
        suffices, and attempts to rely on one are rejected with
        `ERR_WASH_TYPE_INSUFFICIENT`."

        Design: Corner/errors/wash_only_type_insufficient
        """
        ctx = setup_placed_group(head_placed=500)
        slot = create_slot(**JULY_SLOT)
        load = book_load(ctx["group"]["id"], slot["id"], 100)

        set_clock("2026-07-12T08:00:00Z")
        wash = create_verified_truck_wash("2026-07-12T08:00:00Z",
                                          wash_type="WASH_ONLY")
        assert wash["wash_status"] == "VERIFIED"

        res = api.dispatch_market_load(
            load["id"], {"truck_wash_id": wash["id"]}, TRANSPORT
        )
        validate_error(res, ApiErrorId.ERR_WASH_TYPE_INSUFFICIENT,
                       expected_status=409)
        assert get_success_data(
            api.get_market_load(load["id"], TRANSPORT)
        )["load_status"] == "SCHEDULED"

    def test_wash_staleness_boundary_48h(self, api):
        """PRD §2.10: "A truck wash additionally expires: dispatch is permitted
        within forty-eight hours of the wash, with the exact forty-eight-hour
        mark still valid."
        PRD §3.5: "anything later rejected as `ERR_WASH_STALE`".

        Dispatch at exactly washed_at + 48h succeeds; at +49h it fails.

        Design: Corner/errors/wash_staleness_boundary_48h
        """
        ctx = setup_placed_group(head_placed=500)
        slot = create_slot(**JULY_SLOT)
        load1 = book_load(ctx["group"]["id"], slot["id"], 100)
        load2 = book_load(ctx["group"]["id"], slot["id"], 100)

        set_clock("2026-07-12T08:00:00Z")
        wash1 = create_verified_truck_wash("2026-07-10T08:00:00Z", truck_code="T-1")
        wash2 = create_verified_truck_wash("2026-07-10T07:00:00Z", truck_code="T-2")

        dispatched = dispatch_load(load1["id"], wash1["id"])
        assert dispatched["load_status"] == "DISPATCHED"

        res = api.dispatch_market_load(
            load2["id"], {"truck_wash_id": wash2["id"]}, TRANSPORT
        )
        validate_error(res, ApiErrorId.ERR_WASH_STALE, expected_status=409)

    def test_truck_wash_invalid_enum_returns_400(self, api):
        """PRD §2.6: "Required fields must be present, enum values must be
        members of their declared sets, integers must honor their minimums ...
        violations fail with `ERR_MALFORMED_FIELD` (HTTP 400)."
        PRD §3.5: "A `TransportCoordinator` records a **truck wash** with the
        `truck_code`, the `washed_at` instant the wash completed, and the
        `wash_type` — `FULL_DISINFECT` or `WASH_ONLY`."

        Design: Corner/entities/truck_wash_invalid_enum_returns_400
        """
        res = api.create_truck_wash(
            create_truck_wash_payload(wash_type="HOSE_DOWN"), TRANSPORT
        )
        validate_error(res, ApiErrorId.ERR_MALFORMED_FIELD, expected_status=400)


class TestDelivery:
    def test_delivery_before_slot_date_rejected(self, api):
        """PRD §3.5: "Delivery is not accepted before the slot's date — the
        clock date must be on or after `slot_date`
        (`ERR_DELIVERY_BEFORE_SLOT_DATE`)."

        Design: Corner/errors/delivery_before_slot_date_rejected
        """
        ctx = setup_placed_group(head_placed=500)
        _slot, load, _wash = setup_dispatched_load(
            ctx["group"]["id"], slot_date="2026-07-13", head_count=100,
            slot_overrides={"capacity_head": 500, "min_weight_lbs": 240,
                            "max_weight_lbs": 320},
            washed_at="2026-07-12T08:00:00Z",
            dispatch_clock="2026-07-12T08:00:00Z",
        )
        # Clock is 2026-07-12, one day before the slot date.
        res = api.deliver_market_load(
            load["id"], {"live_weight_lbs_total": 28000}, TRANSPORT
        )
        validate_error(res, ApiErrorId.ERR_DELIVERY_BEFORE_SLOT_DATE,
                       expected_status=409)
        assert get_success_data(
            api.get_market_load(load["id"], TRANSPORT)
        )["load_status"] == "DISPATCHED"
        assert get_group(ctx["group"]["id"])["head_marketed"] == 0


class TestDeliveryCascade:
    def test_cascade_delivery_to_settlement_creation(self, api):
        """PRD §3.5: "A group's first delivered load also moves its lifecycle
        from `PLACED` to `MARKETING`, and a delivery that drains `head_current`
        to zero closes the group outright (§3.8)."
        PRD §3.8: "Either close stamps `closed_at` with the clock instant,
        flips the occupying barn to `WASH_REQUIRED` as described in §3.6, and
        mints the group's **settlement**."
        PRD §3.8: "The settlement is created one-to-one with the group, already
        in `FINALIZED` status".

        One deliver call fires the depth-3 chain: load DELIVERED -> group
        CLOSED -> barn WASH_REQUIRED -> settlement FINALIZED.

        Design: Difficulty/transitive_cascade/cascade_delivery_to_settlement_creation
        """
        ctx = setup_placed_group(head_placed=300)
        group_id = ctx["group"]["id"]
        create_and_deliver_feed(ctx["group"]["id"], 100000)
        slot, load, _wash = setup_dispatched_load(
            group_id, slot_date="2026-07-13", head_count=300,
            slot_overrides={"capacity_head": 400, "min_weight_lbs": 240,
                            "max_weight_lbs": 300},
            washed_at="2026-07-12T08:00:00Z",
            dispatch_clock="2026-07-12T08:00:00Z",
        )

        set_clock("2026-07-13T00:00:00Z")
        delivered = deliver_load(load["id"], 84000)
        assert delivered["load_status"] == "DELIVERED"

        group = get_group(group_id)
        assert group["group_status"] == "CLOSED"
        assert group["head_marketed"] == 300
        assert group["head_current"] == 0
        assert group["head_unaccounted"] == 0
        assert group["closed_at"] is not None

        barn = get_barn(ctx["barn"]["id"])
        assert barn["barn_status"] == "WASH_REQUIRED"
        assert barn["wash_required"] is True
        assert barn["current_group_id"] is None

        settlement = get_settlement_for_group(group_id)
        assert settlement["settlement_status"] == "FINALIZED"
        assert settlement["base_pay_cents"] == 300 * 4000
        assert settlement["bonus_cents"] == 180000
        assert settlement["deductions_cents"] == 0
        assert settlement["total_pay_cents"] == 1380000
        assert_settlement_pay_invariants(settlement)

    def test_cascade_settlement_carries_computed_metrics(self, api):
        """PRD §3.8: "The settlement is created one-to-one with the group,
        already in `FINALIZED` status, carrying the group's `contract_id` and
        snapshotting the close-out aggregates: `head_marketed`,
        `total_live_weight_lbs`, the group's `mortality_pct`, and `days_on_feed`
        measured as the number of days from `placement_date` to the closing
        date."
        PRD §3.8: "The `adg_lbs` divides that weight gain across pig-days — by
        the product of `head_marketed` and `days_on_feed` — rounded half-up to
        two decimals. The `fcr` divides `cumulative_feed_lbs` by the weight
        gain, also rounded half-up to two decimals."

        69000 lbs gain over 133 days: fcr 100000/69000 = 1.45, adg
        69000/(300*133) = 1.73.

        Design: Difficulty/transitive_cascade/cascade_delivery_to_settlement_creation
        """
        ctx = setup_placed_group(head_placed=300)
        group_id = ctx["group"]["id"]
        create_and_deliver_feed(group_id, 100000)
        _slot, load, _wash = setup_dispatched_load(
            group_id, slot_date="2026-07-13", head_count=300,
            slot_overrides={"capacity_head": 400, "min_weight_lbs": 240,
                            "max_weight_lbs": 300},
            washed_at="2026-07-12T08:00:00Z",
            dispatch_clock="2026-07-12T08:00:00Z",
        )
        set_clock("2026-07-13T00:00:00Z")
        deliver_load(load["id"], 84000)

        settlement = get_settlement_for_group(group_id)
        assert settlement["contract_id"] == ctx["contract"]["id"]
        assert settlement["group_id"] == group_id
        assert settlement["head_marketed"] == 300
        assert settlement["total_live_weight_lbs"] == 84000
        assert settlement["days_on_feed"] == 133
        assert settlement["mortality_pct"] == 0.0
        assert settlement["fcr"] == 1.45
        assert settlement["adg_lbs"] == 1.73

        _data, meta = validate_paginated(
            api.list_settlements(ADMIN, params={"group_id": group_id})
        )
        assert meta["total_count"] == 1


class TestSettlementPreviewGating:
    def test_settlement_preview_variant_selection(self, api):
        """PRD §3.8: "While a group is still `PLACED` or `MARKETING`, a
        provisional settlement preview projects where the close-out is
        heading."
        PRD §3.8: "its response carries `variant` identifying the projection
        variant, together with `base_pay_cents`, `bonus_cents`,
        `deductions_cents`, `adjustment_cents`, `total_pay_cents`, `fcr`,
        `adg_lbs`, `mortality_pct`, and `head_projected_marketed`".
        PRD §3.8: "The `base_pay_cents` is `head_placed` times the contract's
        `base_pay_cents_per_head`."

        Preview is refused before the group is on the ground and computes the
        PROVISIONAL variant once PLACED.

        Design: Corner/calculations/settlement_preview_variant_selection
        """
        ctx = setup_contract_with_barn()
        group = create_scheduled_group(
            ctx["barn"]["id"], ctx["contract"]["id"], head_placed=1000
        )

        res = api.get_settlement_preview(group["id"], FIELDTECH)
        assert res.status_code == 409
        validate_error_is_one_of(
            res, [ApiErrorId.ERR_GROUP_NOT_ACTIVE,
                  ApiErrorId.ERR_INVALID_STATE_TRANSITION]
        )

        confirm_group(group["id"])
        preview = validate_success(
            api.get_settlement_preview(group["id"], FIELDTECH), 200
        )
        assert preview["variant"] == "PROVISIONAL"
        assert preview["base_pay_cents"] == 1000 * 4000
