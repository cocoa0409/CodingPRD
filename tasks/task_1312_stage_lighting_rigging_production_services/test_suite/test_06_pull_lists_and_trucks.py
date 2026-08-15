"""Pull lists, truck packs, and dock scheduling: the waitlist promotion
cascade, asset engagement conservation, dock window and door rules, check-out
validation priority, pack-weight computation, and tiered rental billing."""
import pytest

from test_helpers import (
    validate_error,
    ApiErrorId, TEST_USERS,
    setup_planning_production, setup_full_planning_surface, setup_load_in_production,
    create_production, transition_production,
    create_asset, get_asset, transition_asset,
    create_pull_list_entry, get_pull_list_entry,
    reserve_entry, prep_entry, checkout_entry, return_entry, cancel_entry,
    create_truck, create_load_schedule, get_load_schedule, transition_schedule,
    set_clock, certify_show,
    CLOCK_AFTER_SHOW,
)

PM = TEST_USERS["production_manager_headers"]
WH = TEST_USERS["warehouse_chief_headers"]


class TestWaitlistPromotionChain:
    def test_entry_cancel_waitlist_promotion_chain(self, api):
        """PRD §3.6: "The waitlist makes reservation automatic where possible: whenever an asset returns to `AVAILABLE` from `RESERVED`, `PREPPED`, or `DEPLOYED` — that is, on an entry cancellation or a check-in — the system scans the waitlist, considering exactly the `REQUESTED` entries for that asset whose productions are in `PLANNING`. If the candidate set is empty, nothing happens; otherwise exactly one entry is promoted, the one with the earliest `created_at` (ascending, at three-fractional-digit precision, which is the final ordering key — the tie-break never reaches the `id`), moving the promoted entry to `RESERVED` and the asset back to `RESERVED`."

        Design: Difficulty/transitive_cascade/entry_cancel_waitlist_promotion_chain
        """
        ctx = setup_planning_production()
        prod2 = create_production(ctx["venue"]["id"], name="P2",
                                  load_in_at="2026-09-10T08:00:00Z",
                                  show_at="2026-09-11T19:00:00Z",
                                  load_out_at="2026-09-12T23:00:00Z")
        transition_production(prod2["id"], "PLANNING")
        asset = create_asset()
        e1 = create_pull_list_entry(ctx["production"]["id"], asset["id"])
        reserve_entry(e1["id"])
        e2 = create_pull_list_entry(prod2["id"], asset["id"])
        assert e2["status"] == "REQUESTED"
        cancel_entry(e1["id"])
        assert get_pull_list_entry(e1["id"])["status"] == "CANCELLED"
        assert get_pull_list_entry(e2["id"])["status"] == "RESERVED", \
            "the waitlisted entry is promoted by the cascade"
        assert get_asset(asset["id"])["status"] == "RESERVED", \
            "AVAILABLE was only an intermediate hop"

    def test_cancel_requested_entry_is_asset_noop(self, api):
        """PRD §3.6: "Individual entries may be cancelled from `REQUESTED` (a no-op for the asset) or from `RESERVED` (the asset returns to `AVAILABLE` and the waitlist scan runs)."

        Design: Difficulty/transitive_cascade/entry_cancel_waitlist_promotion_chain
        """
        ctx = setup_planning_production()
        asset = create_asset()
        e1 = create_pull_list_entry(ctx["production"]["id"], asset["id"])
        reserve_entry(e1["id"])
        e2 = create_pull_list_entry(ctx["production"]["id"], asset["id"])
        cancel_entry(e2["id"])
        assert get_pull_list_entry(e2["id"])["status"] == "CANCELLED"
        assert get_asset(asset["id"])["status"] == "RESERVED", \
            "cancelling a REQUESTED entry never touched the asset"
        assert get_pull_list_entry(e1["id"])["status"] == "RESERVED"


class TestAssetReservationConservation:
    def test_asset_reservation_conservation(self, api):
        """PRD §3.6: "Reserving an entry (`REQUESTED` → `RESERVED`) requires the asset to be `AVAILABLE` at that moment (else `ERR_ASSET_NOT_AVAILABLE`) and flips the asset to `RESERVED`."
        PRD §3.6: "Individual entries may be cancelled from `REQUESTED` (a no-op for the asset) or from `RESERVED` (the asset returns to `AVAILABLE` and the waitlist scan runs)."

        Design: Difficulty/compensating_invariant/asset_reservation_conservation
        """
        ctx = setup_planning_production()
        asset = create_asset()
        assert asset["status"] == "AVAILABLE"
        entry = create_pull_list_entry(ctx["production"]["id"], asset["id"])
        entry = reserve_entry(entry["id"])
        assert entry["status"] == "RESERVED"
        assert get_asset(asset["id"])["status"] == "RESERVED"
        entry = cancel_entry(entry["id"])
        assert entry["status"] == "CANCELLED"
        assert get_asset(asset["id"])["status"] == "AVAILABLE", \
            "the reserve/cancel pair leaves zero active engagements on the asset"

    def test_production_cancel_frees_reserved_asset(self, api):
        """PRD §3.2: "Cancellation is available from `DRAFT`, `PLANNING`, and `READY_FOR_LOADIN`, and it triggers a full teardown cascade: every crew call in `DRAFT`, `PUBLISHED`, or `CONFIRMED` moves to `CANCELLED`, and each cancelled call's assignments in `ASSIGNED`, `CONFIRMED`, or `WORKED` move to `CANCELLED`; every rigging point in `RESERVED`, `UNDER_REVIEW`, `REJECTED`, or `APPROVED` moves to `RELEASED`, recomputing its plot's `total_factored_load_kg`; every pull list entry in `REQUESTED`, `RESERVED`, or `PREPPED` moves to `CANCELLED`, and each asset thereby freed (an asset in `RESERVED` or `PREPPED`) returns to `AVAILABLE`, immediately running the waitlist promotion scan of §3.6; every load schedule in `PLANNED`, `CONFIRMED`, or `AUTHORIZED` moves to `CANCELLED`; and every safety inspection in `SCHEDULED`, `IN_PROGRESS`, or `FAILED` moves to `CANCELLED`."

        Design: Difficulty/compensating_invariant/asset_reservation_conservation
        """
        ctx = setup_planning_production()
        asset = create_asset()
        entry = create_pull_list_entry(ctx["production"]["id"], asset["id"])
        reserve_entry(entry["id"])
        transition_production(ctx["production"]["id"], "CANCELLED")
        assert get_pull_list_entry(entry["id"])["status"] == "CANCELLED"
        assert get_asset(asset["id"])["status"] == "AVAILABLE"


class TestDockWindowsAndDoors:
    def test_dock_window_half_open_adjacency(self, api):
        """PRD §3.6: "Confirming the run (`PLANNED` → `CONFIRMED`) checks the dock calendar: no other run in `CONFIRMED` or `AUTHORIZED` status at the same venue and the same `dock_door_index` may have a half-open window intersecting this one — windows that merely touch endpoints are allowed — and a collision is rejected with `ERR_DOCK_WINDOW_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/dock_window_half_open_adjacency
        """
        ctx = setup_planning_production()
        t1 = create_truck(plate_no="T-1")
        t2 = create_truck(plate_no="T-2")
        ls1 = create_load_schedule(ctx["production"]["id"], t1["id"])
        transition_schedule(ls1["id"], "CONFIRMED")
        # Adjacent half-open window [12:00, 16:00) touches [08:00, 12:00) — allowed.
        ls2 = create_load_schedule(ctx["production"]["id"], t2["id"],
                                   window_start="2026-09-01T12:00:00Z",
                                   window_end="2026-09-01T16:00:00Z")
        data = transition_schedule(ls2["id"], "CONFIRMED")
        assert data["status"] == "CONFIRMED"
        # Overlapping window [11:00, 13:00) collides.
        ls3 = create_load_schedule(ctx["production"]["id"], t1["id"],
                                   window_start="2026-09-01T11:00:00Z",
                                   window_end="2026-09-01T13:00:00Z")
        resp = api.transition_load_schedule(ls3["id"], {"to": "CONFIRMED"}, PM)
        validate_error(resp, ApiErrorId.ERR_DOCK_WINDOW_CONFLICT)
        assert get_load_schedule(ls3["id"])["status"] == "PLANNED"

    def test_dock_window_conflict_scoped_to_same_door(self, api):
        """PRD §3.6: "no other run in `CONFIRMED` or `AUTHORIZED` status at the same venue and the same `dock_door_index` may have a half-open window intersecting this one — windows that merely touch endpoints are allowed — and a collision is rejected with `ERR_DOCK_WINDOW_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/dock_window_half_open_adjacency
        """
        ctx = setup_planning_production()  # dock_doors 2
        t1 = create_truck(plate_no="T-1")
        t2 = create_truck(plate_no="T-2")
        ls1 = create_load_schedule(ctx["production"]["id"], t1["id"])
        transition_schedule(ls1["id"], "CONFIRMED")
        # Same time span, different dock door: no conflict.
        ls2 = create_load_schedule(ctx["production"]["id"], t2["id"], dock_door_index=1,
                                   window_start="2026-09-01T09:00:00Z",
                                   window_end="2026-09-01T13:00:00Z")
        data = transition_schedule(ls2["id"], "CONFIRMED")
        assert data["status"] == "CONFIRMED"

    def test_dock_door_index_out_of_range(self, api):
        """PRD §3.6: "The dock door must exist: a `dock_door_index` at or beyond the venue's `dock_doors` count is rejected with `ERR_DOCK_DOOR_INVALID` (HTTP 422) at planning time."

        Design: Corner/errors/dock_door_index_out_of_range
        """
        ctx = setup_planning_production()  # dock_doors 2 -> valid indices 0, 1
        truck = create_truck()
        resp = api.create_load_schedule(
            ctx["production"]["id"],
            {"truck_id": truck["id"], "direction": "LOAD_IN", "dock_door_index": 2,
             "window_start": "2026-09-01T08:00:00Z", "window_end": "2026-09-01T12:00:00Z"}, PM)
        validate_error(resp, ApiErrorId.ERR_DOCK_DOOR_INVALID)
        data = create_load_schedule(ctx["production"]["id"], truck["id"], dock_door_index=1)
        assert data["status"] == "PLANNED"


class TestCheckoutValidationPriority:
    def test_safety_over_referential_on_checkout(self, api):
        """PRD §3.6: "A pack weight equal to the truck's `capacity_kg` passes; strictly greater rejects the check-out with `ERR_TRUCK_OVERLOAD` (HTTP 422). Following the validation pipeline, the capacity verdict surfaces ahead of the schedule-authorization verdict when both would fail."

        Design: Difficulty/priority_pair_validation_conflict/safety_over_referential_on_checkout
        """
        ctx = setup_planning_production()
        asset = create_asset(asset_tag="TRUSS-001", asset_class="TRUSS_12IN", weight_kg=600)
        entry = create_pull_list_entry(ctx["production"]["id"], asset["id"])
        reserve_entry(entry["id"])
        prep_entry(entry["id"])
        truck = create_truck(capacity_kg=500)
        schedule = create_load_schedule(ctx["production"]["id"], truck["id"])  # stays PLANNED
        resp = api.transition_pull_list_entry(
            entry["id"], {"to": "OUT", "load_schedule_id": schedule["id"]}, WH)
        validate_error(resp, ApiErrorId.ERR_TRUCK_OVERLOAD)  # 600 x 1.02 = 612.00 > 500
        assert get_pull_list_entry(entry["id"])["status"] == "PREPPED"

    def test_checkout_requires_authorized_schedule_when_pack_fits(self, api):
        """PRD §3.6: "The payload must name the `load_schedule_id` of the run carrying the item (its absence is `ERR_INVALID_REQUEST`); the referenced run must be `AUTHORIZED` with direction `LOAD_IN` (else `ERR_SCHEDULE_NOT_AUTHORIZED`); and the truck must physically take the weight."

        Design: Difficulty/priority_pair_validation_conflict/safety_over_referential_on_checkout
        """
        ctx = setup_planning_production()
        asset = create_asset()
        entry = create_pull_list_entry(ctx["production"]["id"], asset["id"])
        reserve_entry(entry["id"])
        prep_entry(entry["id"])
        truck = create_truck()
        schedule = create_load_schedule(ctx["production"]["id"], truck["id"])  # PLANNED
        resp = api.transition_pull_list_entry(
            entry["id"], {"to": "OUT", "load_schedule_id": schedule["id"]}, WH)
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_NOT_AUTHORIZED)
        assert get_pull_list_entry(entry["id"])["status"] == "PREPPED"


class TestScheduleAuthorizationGate:
    def test_load_in_authorization_requires_ready_production(self, api):
        """PRD §3.6: "Authorizing the run (`CONFIRMED` → `AUTHORIZED`) matches the production's state to the direction: a `LOAD_IN` run requires the production to be `READY_FOR_LOADIN` or `LOAD_IN`, while a `LOAD_OUT` run requires `SHOW_COMPLETE` or `LOAD_OUT`; a mismatch is rejected with `ERR_SCHEDULE_NOT_AUTHORIZED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/schedule_authorization_requires_production_state
        """
        ctx = setup_full_planning_surface()  # everything ready, still PLANNING
        resp = api.transition_load_schedule(ctx["schedule"]["id"], {"to": "AUTHORIZED"}, PM)
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_NOT_AUTHORIZED)
        transition_production(ctx["production"]["id"], "READY_FOR_LOADIN")
        data = transition_schedule(ctx["schedule"]["id"], "AUTHORIZED")
        assert data["status"] == "AUTHORIZED"

    def test_load_out_authorization_requires_show_complete(self, api):
        """PRD §3.6: "a `LOAD_IN` run requires the production to be `READY_FOR_LOADIN` or `LOAD_IN`, while a `LOAD_OUT` run requires `SHOW_COMPLETE` or `LOAD_OUT`; a mismatch is rejected with `ERR_SCHEDULE_NOT_AUTHORIZED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/schedule_authorization_requires_production_state
        """
        ctx = setup_full_planning_surface(with_load_out_schedule=True)
        transition_production(ctx["production"]["id"], "READY_FOR_LOADIN")
        set_clock(ctx["production"]["load_in_at"])
        transition_production(ctx["production"]["id"], "LOAD_IN")
        resp = api.transition_load_schedule(ctx["schedule_out"]["id"], {"to": "AUTHORIZED"}, PM)
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_NOT_AUTHORIZED)
        certify_show(ctx)
        set_clock(CLOCK_AFTER_SHOW)
        transition_production(ctx["production"]["id"], "SHOW_COMPLETE")
        data = transition_schedule(ctx["schedule_out"]["id"], "AUTHORIZED")
        assert data["status"] == "AUTHORIZED"


class TestPullEntryInitialState:
    def test_pull_list_entry_initial_state(self, api):
        """PRD §3.6: "The `WarehouseChief` requests a serialized asset for a `PLANNING` production by supplying the `asset_id`; the entry begins in `REQUESTED`."
        PRD §3.6: "Reserving an entry (`REQUESTED` → `RESERVED`) requires the asset to be `AVAILABLE` at that moment (else `ERR_ASSET_NOT_AVAILABLE`) and flips the asset to `RESERVED`."

        Design: Corner/state_machines/pull_list_entry_initial_state
        """
        ctx = setup_planning_production()
        asset = create_asset()
        data = create_pull_list_entry(ctx["production"]["id"], asset["id"])
        assert data["status"] == "REQUESTED"
        assert data.get("prep_window_start") is None
        assert data.get("prep_window_end") is None
        assert data.get("load_schedule_id") is None
        assert data.get("out_at") is None
        assert data.get("returned_at") is None
        assert data.get("rental_charge_cents") is None
        assert get_asset(asset["id"])["status"] == "AVAILABLE", \
            "creation does not reserve the asset"


class TestReserveUnavailableAsset:
    def test_reserve_unavailable_asset_rejected(self, api):
        """PRD §3.6: "An asset that is `RETIRED`, `LOST`, or `DAMAGED` cannot be pulled — the request fails with `ERR_ASSET_NOT_AVAILABLE` (HTTP 409) — while an asset that is merely busy is a different story: multiple `REQUESTED` entries may stack against the same asset, forming its waitlist."
        PRD §3.6: "Reserving an entry (`REQUESTED` → `RESERVED`) requires the asset to be `AVAILABLE` at that moment (else `ERR_ASSET_NOT_AVAILABLE`) and flips the asset to `RESERVED`."

        Design: Corner/errors/reserve_unavailable_asset_rejected
        """
        ctx = setup_planning_production()
        a1 = create_asset(asset_tag="ML-001")
        a2 = create_asset(asset_tag="ML-002")
        transition_asset(a2["id"], "RETIRED")
        e1 = create_pull_list_entry(ctx["production"]["id"], a1["id"])
        reserve_entry(e1["id"])
        e2 = create_pull_list_entry(ctx["production"]["id"], a1["id"])
        resp = api.transition_pull_list_entry(e2["id"], {"to": "RESERVED"}, WH)
        validate_error(resp, ApiErrorId.ERR_ASSET_NOT_AVAILABLE)
        assert get_pull_list_entry(e2["id"])["status"] == "REQUESTED"
        resp = api.create_pull_list_entry(
            ctx["production"]["id"], {"asset_id": a2["id"]}, WH)
        validate_error(resp, ApiErrorId.ERR_ASSET_NOT_AVAILABLE)


class TestTruckPackDunnage:
    def test_truck_pack_dunnage_weight(self, api):
        """PRD §3.6: "The truck check recomputes the run's `pack_weight_kg` *including the new entry*: the sum of `weight_kg` over all entries checked out onto that schedule, uplifted by a 2 percent dunnage allowance, rounded half-up to 2 decimal places. A pack weight equal to the truck's `capacity_kg` passes; strictly greater rejects the check-out with `ERR_TRUCK_OVERLOAD` (HTTP 422)."

        Design: Corner/calculations/truck_pack_dunnage_weight
        """
        ctx = setup_load_in_production(
            asset_specs=[{"asset_tag": "TRUSS-001", "asset_class": "TRUSS_12IN",
                          "weight_kg": 1000},
                         {"asset_tag": "TRUSS-002", "asset_class": "TRUSS_12IN",
                          "weight_kg": 1000}],
            truck_overrides={"capacity_kg": 2040},
            checkout=False)
        e1, e2 = ctx["entries"]
        checkout_entry(e1["id"], ctx["schedule"]["id"])
        assert get_load_schedule(ctx["schedule"]["id"])["pack_weight_kg"] == pytest.approx(1020.00, abs=0.005)
        checkout_entry(e2["id"], ctx["schedule"]["id"])
        assert get_load_schedule(ctx["schedule"]["id"])["pack_weight_kg"] == pytest.approx(2040.00, abs=0.005)
        assert get_pull_list_entry(e1["id"])["status"] == "OUT"
        assert get_pull_list_entry(e2["id"])["status"] == "OUT", \
            "2040.00 == capacity 2040 passes the strictly-greater rule"


class TestRentalTierBoundary:
    def test_rental_tier_boundary_day3_day4(self, api):
        """PRD §3.6: "Billable days count every calendar date touched from the date of `out_at` through the date of `returned_at`, both endpoints inclusive, so a same-day return bills exactly one day. The pricing is tiered: each of the first three days bills at the asset's full `daily_rate_cents`; days four through seven bill at half the daily rate each; days eight and beyond bill at a quarter of the daily rate each."

        Design: Corner/calculations/rental_tier_boundary_day3_day4
        """
        ctx = setup_load_in_production(
            asset_specs=[{"asset_tag": "ML-001"}, {"asset_tag": "ML-002"}])
        e1, e2 = ctx["entries"]  # both OUT at 2026-09-01T08:00:00Z, rate 5000
        set_clock("2026-09-03T09:00:00Z")  # dates 09-01..09-03 = 3 days at 100%
        data = return_entry(e1["id"])
        assert data["rental_charge_cents"] == 15000
        set_clock("2026-09-04T09:00:00Z")  # 4 days: 3 x 5000 + 1 x 2500
        data = return_entry(e2["id"])
        assert data["rental_charge_cents"] == 17500, \
            "the day-4 marginal rate is exactly half the daily rate"
        assert get_asset(ctx["assets"][0]["id"])["status"] == "AVAILABLE"
        assert get_asset(ctx["assets"][1]["id"])["status"] == "AVAILABLE"
