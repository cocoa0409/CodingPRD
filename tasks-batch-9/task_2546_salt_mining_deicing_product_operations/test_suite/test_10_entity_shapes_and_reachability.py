"""
Entity shapes and reverse reachability across the salt mining and deicing domain.

These tests read the shape of a resource the moment it is created or retrieved: the
system fields the server mints, the derived figures it computes at creation, the
defaults it applies when an optional input is omitted, the 404 an unresolved
identifier produces, and the list filters that are the only way to reach a row the
server minted on the caller's behalf (PRD §2.4, §2.10, §3.1-§3.9).
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f, fixtures as fx
from test_helpers.api_errors import (
    ERR_INVALID_REQUEST,
    ERR_MINE_NOT_FOUND,
    ERR_PANEL_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_amount,
    assert_common_fields,
    assert_immutable_inspection_fields,
    assert_lot_tonnage,
    assert_page_meta,
    assert_purity,
    assert_three_decimals,
    assert_tons,
    only,
)
from test_helpers.constants import (
    ALLOCATION_RESERVED,
    CHEMICAL_FEEDSTOCK,
    COARSE,
    COMPLIANT,
    COVERED,
    DEPOT_OPEN,
    FINDING_PASS,
    HIGHWAY_DEICING,
    HOIST_AVAILABLE,
    LOT_AVAILABLE,
    MEDIUM,
    MODE_RAIL,
    ORIGIN_MANUAL,
    PANEL_PLANNED,
    QC_PENDING,
    REQUIRED_GAP_MINUTES,
    SHIPMENT_PLANNED,
)
from test_helpers.test_users import (
    CONTRACT_ADMIN,
    GROUND_CONTROL,
    LAB_TECH,
    LOGISTICS,
    MINE_PLANNER,
)

# One panel assay reused across the file: 100000 gross tons at a 50 percent
# extraction ratio, a 96.00 grade that sits in the top grade tier, insolubles of
# 2.00 inside the forgiven band and no pillar recovery, which recovers 50000.00 tons.
PANEL_KWARGS = {
    "panel_code": "P-1",
    "gross_tons_in_place": 100000,
    "extraction_ratio_pct": 50,
    "grade_pct_nacl": 96.00,
    "insolubles_pct": 2.00,
}

# A 1000-ton run over a full 24-hour hoist window.
RUN_KWARGS = {
    "planned_tons": 1000,
    "hoist_window_start": "2026-08-02T00:00:00Z",
    "hoist_window_end": "2026-08-03T00:00:00Z",
}

# A coarse-screened highway deicing batch of 1000 dry input tons: 940.00 tons of
# yield at a purity of 96.500.
BATCH_KWARGS = {
    "product_line": HIGHWAY_DEICING,
    "screen_spec": COARSE,
    "anticaking_ppm": 20.00,
    "corrosion_inhibitor_pct": 0.50,
    "input_tons": 1000,
    "moisture_pct": 0.00,
    "storage_kind": COVERED,
}

SYRACUSE_DEPOT = {
    "name": "Syracuse Market Depot",
    "state_code": "NY",
    "covered_capacity_tons": 5000,
    "open_pad_capacity_tons": 5000,
    "loadout_rate_tons_per_hour": 500,
    "outbound_freight_rate_per_ton": 12.500,
}

ROCHESTER_DEPOT = {
    "name": "Rochester Market Depot",
    "state_code": "NY",
    "covered_capacity_tons": 5000,
    "open_pad_capacity_tons": 5000,
    "loadout_rate_tons_per_hour": 400,
    "outbound_freight_rate_per_ton": 8.000,
}

CONTRACT_KWARGS = {
    "committed_tons": 1000,
    "guaranteed_price_per_ton": 80.00,
    "failure_to_supply_penalty_per_ton": 30.00,
}

ORDER_KWARGS = {
    "requested_tons": 500,
    "required_by": "2026-12-01T00:00:00Z",
    "market_index_price_per_ton": 82.00,
}


def test_mine_registration_returns_derated_capacity_and_zeroed_counters(api):
    """
    Registering a mine returns the nameplate shaft capacity already carried through
    both derating dimensions, together with the counters the fresh row opens at zero.

    PRD §3.1: "A newly registered mine opens with `hoist_state` at `HOIST_AVAILABLE`, `compliance_state` at `COMPLIANT`, `scheduled_hoist_tons_open` at 0, `producing_panel_count` at 0, `last_compliance_action_at` null, and `version` at 1."
    PRD §3.1: "The mine's `effective_hoist_tons_per_day` is `rated_hoist_tons_per_day` multiplied by the shaft factor and then by the compliance factor, rounded half up to two decimal places."

    Design: Corner/entities/mine_create_returns_derated_capacity_and_zeroed_counters
    """
    resp = api.create_mine(
        f.mine_payload(
            name="Retsof Salt Mine",
            state_code="NY",
            rated_hoist_tons_per_day=24000,
            ground_control_plan_version=2,
        ),
        MINE_PLANNER,
    )
    mine = validate_success(resp, 201)

    assert mine["name"] == "Retsof Salt Mine"
    assert mine["state_code"] == "NY"
    assert mine["ground_control_plan_version"] == 2
    assert mine["hoist_state"] == HOIST_AVAILABLE
    assert mine["compliance_state"] == COMPLIANT
    assert_tons(mine["rated_hoist_tons_per_day"], 24000.00, "rated_hoist_tons_per_day")
    assert_tons(
        mine["effective_hoist_tons_per_day"], 24000.00, "effective_hoist_tons_per_day"
    )
    assert_tons(mine["scheduled_hoist_tons_open"], 0.00, "scheduled_hoist_tons_open")
    assert mine["producing_panel_count"] == 0
    assert mine["last_compliance_action_at"] is None
    assert_common_fields(mine, expected_version=1)


def test_depot_retrieval_returns_stored_capacities_and_open_posture(api):
    """
    Retrieving a freshly opened depot echoes the shed and pad capacities, the loadout
    rate and the three-decimal outbound freight rate, and shows an empty yard.

    PRD §3.6: "A new depot opens `OPEN`, with `covered_stored_tons`, `open_pad_stored_tons` and `covered_utilization_pct` all at 0, `storm_state_set_by_user_id` null, and `version` at 1."

    Design: Corner/entities/depot_retrieval_returns_stored_capacities_and_open_posture
    """
    depot = fx.create_depot(api, **SYRACUSE_DEPOT)

    resp = api.get_depot(depot["id"], LOGISTICS)
    read = validate_success(resp, 200)

    assert read["id"] == depot["id"]
    assert read["name"] == "Syracuse Market Depot"
    assert read["state_code"] == "NY"
    assert read["depot_state"] == DEPOT_OPEN
    assert_tons(read["covered_capacity_tons"], 5000.00, "covered_capacity_tons")
    assert_tons(read["open_pad_capacity_tons"], 5000.00, "open_pad_capacity_tons")
    assert_amount(
        read["loadout_rate_tons_per_hour"], 500.00, 2, "loadout_rate_tons_per_hour"
    )
    assert_three_decimals(
        read["outbound_freight_rate_per_ton"], 12.500, "outbound_freight_rate_per_ton"
    )
    assert_tons(read["covered_stored_tons"], 0.00, "covered_stored_tons")
    assert_tons(read["open_pad_stored_tons"], 0.00, "open_pad_stored_tons")
    assert_amount(read["covered_utilization_pct"], 0.00, 2, "covered_utilization_pct")
    assert read["storm_state_set_by_user_id"] is None
    assert_common_fields(read, expected_version=1)


def test_stockpile_lot_listing_by_treatment_batch_filter_returns_minted_lot(api):
    """
    A quality-control pass mints a stockpile lot that has no creation response of its
    own, so the only way to reach it is the lot list filtered by the batch that minted
    it, which comes back as a single-row page under the default page window.

    PRD §3.5: "The new lot's `treatment_batch_id` records which batch minted it, and — since the mint has no response of its own — the lot is discoverable only through the lot list filtered by that batch (§2.10)."
    PRD §2.10: "Because parents are never in the path, every relationship is instead traversed by filtering the child collection."

    Design: Corner/entities/stockpile_lot_listing_by_treatment_batch_filter_returns_minted_lot
    """
    world = fx.lot_at_depot(
        api,
        panel_kwargs=PANEL_KWARGS,
        depot_kwargs=SYRACUSE_DEPOT,
        run_kwargs=RUN_KWARGS,
        hoisted_tons=1000,
        **BATCH_KWARGS,
    )

    resp = api.list_lots(LOGISTICS, {"treatment_batch_id": world["batch"]["id"]})
    rows, meta = validate_paginated(resp)

    assert_page_meta(meta, total_count=1, has_more=False, limit=10, offset=0)
    lot = only(rows)
    assert lot["treatment_batch_id"] == world["batch"]["id"]
    assert lot["depot_id"] == world["depot"]["id"]
    assert lot["product_line"] == HIGHWAY_DEICING
    assert lot["storage_kind"] == COVERED
    assert lot["lot_state"] == LOT_AVAILABLE
    assert_purity(lot["purity_pct_nacl"], 96.500)
    assert_lot_tonnage(lot, on_hand=940.00, reserved=0.00, available=940.00)
    assert_common_fields(lot)


def test_panel_get_with_unknown_uuid_returns_panel_not_found(api):
    """
    A well-formed identifier that names no panel is a lookup failure, not a validation
    failure: the read comes back as the panel family's own 404 even though other panels
    exist in the system.

    PRD §2.6: "8. **Path resource existence** — each identifier in the URL path is resolved left to right, and the first one that does not resolve yields that entity's own 404: `ERR_MINE_NOT_FOUND`, `ERR_PANEL_NOT_FOUND`, `ERR_RUN_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_DEPOT_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_FORECAST_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND` or `ERR_INSPECTION_NOT_FOUND` (all 404)."

    Design: Corner/entities/panel_get_with_unknown_uuid_returns_panel_not_found
    """
    mine = fx.create_mine(api)
    existing = fx.create_panel(api, mine["id"], **PANEL_KWARGS)

    resp = api.get_panel(NON_EXISTENT_UUID, MINE_PLANNER)
    validate_error(resp, ERR_PANEL_NOT_FOUND, 404)

    # The panel that does exist is untouched by the missed lookup.
    still_there = validate_success(api.get_panel(existing["id"], MINE_PLANNER), 200)
    assert still_there["id"] == existing["id"]


def test_bid_contract_create_missing_committed_tons_rejected(api):
    """
    A bid contract drafted without the tonnage it commits to is refused as an invalid
    request, and no draft is written.

    PRD §2.6: "5. **Required inputs present** — every field the endpoint marks required must be present and non-null, else `ERR_INVALID_REQUEST` (422)."

    Design: Corner/entities/bid_contract_create_missing_committed_tons_rejected
    """
    forecast = fx.create_forecast(api)
    payload = f.contract_payload(forecast["id"], **CONTRACT_KWARGS)
    payload.pop("committed_tons")

    resp = api.create_contract(payload, CONTRACT_ADMIN)
    validate_error(resp, ERR_INVALID_REQUEST, 422)

    rows, meta = validate_paginated(
        api.list_contracts(CONTRACT_ADMIN, {"season_forecast_id": forecast["id"]})
    )
    assert_page_meta(meta, total_count=0)
    assert rows == []


def test_optional_inputs_omitted_apply_declared_defaults(api):
    """
    A mine registered without a ground-control plan version and a panel laid out
    without the pillar-recovery flag both take the documented defaults, and the panel's
    recoverable reserve is computed with no pillar bonus at all.

    PRD §3.1: "A `MinePlanner` registers a mine by supplying its `name`, the two-letter uppercase `state_code` of the jurisdiction it sits in, its nameplate shaft capacity as `rated_hoist_tons_per_day` (which must be strictly greater than zero), and optionally the `ground_control_plan_version` of the ground-control plan on file — an integer of at least 1, defaulting to 1 when omitted."
    PRD §3.2: "A new panel opens with `status` at `PLANNED`, `mined_tons` at 0, `ground_control_defect_count` at 0, `open_defect` false, `suspended_by_user_id` null, and `version` at 1."
    PRD §3.2: "In every other case — the flag is false, or the mine is `CITED`, or the mine is under a `WITHDRAWAL_ORDER` — the bonus is zero."

    Design: Corner/entities/optional_inputs_omitted_apply_declared_defaults
    """
    mine = validate_success(api.create_mine(f.mine_payload(), MINE_PLANNER), 201)
    assert mine["ground_control_plan_version"] == 1

    resp = api.create_panel(f.panel_payload(mine["id"], **PANEL_KWARGS), MINE_PLANNER)
    panel = validate_success(resp, 201)

    assert panel["pillar_recovery_allowed"] is False
    assert panel["status"] == PANEL_PLANNED
    assert_tons(panel["recoverable_tons"], 50000.00, "recoverable_tons")
    assert_tons(panel["mined_tons"], 0.00, "mined_tons")
    assert panel["ground_control_defect_count"] == 0
    assert panel["open_defect"] is False
    assert panel["suspended_by_user_id"] is None
    assert_common_fields(panel, expected_version=1)


def test_treatment_batch_computed_yield_and_purity_are_server_derived(api):
    """
    Opening a treatment batch on a hoisted run derives its yield from the screen cut
    and the moisture it carries, and its purity from the assayed grade of the panel
    behind the feeding run plus the screen's upgrade; neither figure is posted.

    PRD §3.5: "The batch's `yield_tons` is `input_tons` multiplied by the screen's yield factor, multiplied by one minus `moisture_pct` divided by 100, multiplied by the rework loss factor, rounded half up to two decimal places."
    PRD §3.5: "The batch's `purity_pct_nacl` is the `grade_pct_nacl` of the panel behind the feeding run plus that upgrade, capped at a ceiling of 99.9, rounded half up to three decimal places."

    Design: Corner/entities/treatment_batch_computed_yield_and_purity_are_server_derived
    """
    world = fx.hoisted_run(
        api, panel_kwargs=PANEL_KWARGS, hoisted_tons=1000, **RUN_KWARGS
    )
    depot = fx.create_depot(api, **SYRACUSE_DEPOT)

    resp = api.create_batch(
        f.batch_payload(
            world["run"]["id"],
            depot["id"],
            product_line=CHEMICAL_FEEDSTOCK,
            screen_spec=MEDIUM,
            anticaking_ppm=10.00,
            corrosion_inhibitor_pct=0.00,
            input_tons=1000,
            moisture_pct=2.50,
            storage_kind=COVERED,
        ),
        LAB_TECH,
    )
    batch = validate_success(resp, 201)

    assert batch["production_run_id"] == world["run"]["id"]
    assert batch["depot_id"] == depot["id"]
    assert_tons(batch["input_tons"], 1000.00, "input_tons")
    assert_tons(batch["yield_tons"], 877.50, "yield_tons")
    assert_purity(batch["purity_pct_nacl"], 97.200)
    assert batch["qc_state"] == QC_PENDING
    assert batch["rework_count"] == 0
    assert batch["qc_decided_by_user_id"] is None
    assert_common_fields(batch, expected_version=1)

    # The pending batch is the run's only open one.
    assert fx.refresh_run(api, world["run"]["id"])["open_batch_count"] == 1


def test_shipment_create_stamps_system_fields_and_planned_status(api):
    """
    Booking a shipment opens it as planned with no receipt lot yet, and the server sets
    the separation the chosen mode demands around its own loadout window rather than
    taking it from the caller.

    PRD §3.7: "A new shipment opens with `status` at `PLANNED`, `received_lot_id` null, and `version` at 1."
    PRD §3.7: "The `required_gap_minutes` field is server-set from the `mode` — 45 minutes for `RAIL`, 20 for `BARGE`, 0 for `TRUCK` — and records the switching or mooring separation that mode demands around its own window."

    Design: Corner/entities/shipment_create_stamps_system_fields_and_planned_status
    """
    world = fx.lot_at_depot(
        api,
        panel_kwargs=PANEL_KWARGS,
        depot_kwargs=SYRACUSE_DEPOT,
        run_kwargs=RUN_KWARGS,
        hoisted_tons=1000,
        **BATCH_KWARGS,
    )
    destination = fx.create_depot(api, **ROCHESTER_DEPOT)

    resp = api.create_shipment(
        f.shipment_payload(
            world["lot"]["id"],
            world["depot"]["id"],
            destination["id"],
            tons=400,
            mode=MODE_RAIL,
            destination_storage_kind=COVERED,
            load_window_start="2026-08-05T08:00:00Z",
            load_window_end="2026-08-05T10:00:00Z",
        ),
        LOGISTICS,
    )
    shipment = validate_success(resp, 201)

    assert shipment["stockpile_lot_id"] == world["lot"]["id"]
    assert shipment["origin_depot_id"] == world["depot"]["id"]
    assert shipment["destination_depot_id"] == destination["id"]
    assert shipment["mode"] == MODE_RAIL
    assert shipment["status"] == SHIPMENT_PLANNED
    assert shipment["received_lot_id"] is None
    assert shipment["required_gap_minutes"] == REQUIRED_GAP_MINUTES[MODE_RAIL]
    assert_tons(shipment["tons"], 400.00, "tons")
    assert_common_fields(shipment, expected_version=1)

    # Booking moves no salt: the tonnage is still in the origin pile.
    assert_lot_tonnage(
        fx.refresh_lot(api, world["lot"]["id"]),
        on_hand=940.00,
        reserved=0.00,
        available=940.00,
    )


def test_treatment_batch_invalid_product_line_enum_rejected(api):
    """
    A treatment batch naming a product line outside the register is refused as an
    invalid request, and the parent run's pending-batch counter never moves.

    PRD §2.6: "6. **Enum membership** — every enum-typed input value must be a member of the set declared for that field, else `ERR_INVALID_REQUEST` (422)."

    Design: Corner/entities/treatment_batch_invalid_product_line_enum_rejected
    """
    world = fx.hoisted_run(
        api, panel_kwargs=PANEL_KWARGS, hoisted_tons=1000, **RUN_KWARGS
    )
    depot = fx.create_depot(api, **SYRACUSE_DEPOT)
    unregistered = dict(BATCH_KWARGS)
    unregistered["product_line"] = "ICE_MELT"

    resp = api.create_batch(
        f.batch_payload(world["run"]["id"], depot["id"], **unregistered), LAB_TECH
    )
    validate_error(resp, ERR_INVALID_REQUEST, 422)

    rows, meta = validate_paginated(
        api.list_batches(LAB_TECH, {"production_run_id": world["run"]["id"]})
    )
    assert_page_meta(meta, total_count=0)
    assert rows == []
    assert fx.refresh_run(api, world["run"]["id"])["open_batch_count"] == 0


def test_ground_control_inspection_is_immutable_and_carries_no_version(api):
    """
    A filed inspection is an append-only observation: it carries an identifier and a
    creation stamp, the engineer who filed it, and the computed flag saying whether
    filing it was what took its panel out of production — but no revision fields.

    PRD §2.4: "`GroundControlInspection` is the exception. An inspection record is an immutable append-only observation: it carries only `id` and `created_at`. It has no `updated_at` field, no `version` field, and no update endpoint of any kind."
    PRD §3.3: "Each record also carries `caused_suspension`, a computed boolean that is true only when filing this particular record was what moved its panel out of production."

    Design: Corner/entities/ground_control_inspection_is_immutable_and_carries_no_version
    """
    mine = fx.create_mine(api)
    panel = fx.create_panel(api, mine["id"], **PANEL_KWARGS)
    fx.develop(api, panel["id"])

    created = validate_success(
        api.create_inspection(
            f.inspection_payload(
                panel["id"],
                FINDING_PASS,
                roof_span_ft=42.0,
                convergence_rate_in_per_day=0.004,
            ),
            GROUND_CONTROL,
        ),
        201,
    )

    read = validate_success(api.get_inspection(created["id"], GROUND_CONTROL), 200)

    assert read["id"] == created["id"]
    assert read["panel_id"] == panel["id"]
    assert read["finding"] == FINDING_PASS
    assert read["inspector_user_id"] == GROUND_CONTROL["X-User-ID"]
    assert read["caused_suspension"] is False
    assert_immutable_inspection_fields(read)

    # A passing observation opens no defect on the panel it names.
    reread = fx.refresh_panel(api, panel["id"])
    assert reread["open_defect"] is False
    assert reread["ground_control_defect_count"] == 0


def test_panel_create_with_unknown_mine_id_returns_mine_not_found(api):
    """
    A panel laid out against a mine identifier that resolves to nothing is refused with
    the mine family's own 404, because the failure is in the body reference rather than
    in the panel's own fields.

    PRD §2.6: "9. **Body reference existence** — every foreign key supplied in a request body must resolve, and an unresolved one yields the referenced entity's own 404 code."

    Design: Corner/entities/panel_create_with_unknown_mine_id_returns_mine_not_found
    """
    mine = fx.create_mine(api)

    resp = api.create_panel(
        f.panel_payload(NON_EXISTENT_UUID, **PANEL_KWARGS), MINE_PLANNER
    )
    validate_error(resp, ERR_MINE_NOT_FOUND, 404)

    rows, meta = validate_paginated(
        api.list_panels(MINE_PLANNER, {"mine_id": mine["id"]})
    )
    assert_page_meta(meta, total_count=0)
    assert rows == []


def test_allocation_junction_is_reachable_from_both_parents(api):
    """
    A hand-written reservation is the junction between a delivery order and a stockpile
    lot: it is reachable by filtering the allocation collection on either parent, and it
    reserves tonnage against the lot exactly as the waterfall does.

    PRD §3.9: "A manual row is written with `origin` set to `MANUAL`, `rank_position` at its default of 1, and `state` at `RESERVED`, and it reserves against the lot exactly as a waterfall row does."
    PRD §3.9: "A manual row updates the order's `allocated_tons` to the new sum of its reserved and consumed rows, and increments the order's, the lot's and the contract's `version` by 1."

    Design: Corner/entities/allocation_junction_is_reachable_from_both_parents
    """
    world = fx.requested_order(
        api,
        order_kwargs=ORDER_KWARGS,
        panel_kwargs=PANEL_KWARGS,
        depot_kwargs=SYRACUSE_DEPOT,
        run_kwargs=RUN_KWARGS,
        batch_kwargs=BATCH_KWARGS,
        contract_kwargs=CONTRACT_KWARGS,
        hoisted_tons=1000,
    )
    order_id = world["order"]["id"]
    lot_id = world["lot"]["id"]

    resp = api.create_allocation(
        f.allocation_payload(order_id, lot_id, 500, fx.lot_version(api, lot_id)),
        LOGISTICS,
    )
    allocation = validate_success(resp, 201)

    assert allocation["delivery_order_id"] == order_id
    assert allocation["stockpile_lot_id"] == lot_id
    assert allocation["origin"] == ORIGIN_MANUAL
    assert allocation["rank_position"] == 1
    assert allocation["state"] == ALLOCATION_RESERVED
    assert_tons(allocation["tons"], 500.00, "tons")
    assert_common_fields(allocation, expected_version=1)

    from_order = only(
        fx.list_rows(api.list_allocations(LOGISTICS, {"delivery_order_id": order_id}))
    )
    from_lot = only(
        fx.list_rows(api.list_allocations(LOGISTICS, {"stockpile_lot_id": lot_id}))
    )
    assert from_order["id"] == allocation["id"]
    assert from_lot["id"] == allocation["id"]

    assert_lot_tonnage(
        fx.refresh_lot(api, lot_id), on_hand=940.00, reserved=500.00, available=440.00
    )
    assert_tons(
        fx.refresh_order(api, order_id)["allocated_tons"], 500.00, "allocated_tons"
    )
