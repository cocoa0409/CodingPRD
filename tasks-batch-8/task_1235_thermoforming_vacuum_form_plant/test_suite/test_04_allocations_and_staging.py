"""Material reservations, order staging, and the mass conservation invariant
(PRD §3.5, §2.7, §3.1)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_lot_mass_invariant,
    create_certified_lot,
    create_lot,
    create_material_allocation_payload,
    create_order,
    create_stage_payload,
    create_stock_spec,
    create_tool_production,
    create_tool_prototype,
    get_allocation,
    get_lot,
    get_order,
    get_success_data,
    order_version,
    reserve_virgin,
    stage_order,
    validate_error,
    validate_paginated,
    validate_success,
)

_PLANNER = TEST_USERS["materials_planner_headers"]
_ENGINEER = TEST_USERS["tooling_engineer_headers"]
_SCHEDULER = TEST_USERS["production_scheduler_headers"]
_ANY = TEST_USERS["any_headers"]


def test_allocation_zero_quantity_returns_invalid_request(api):
    """PRD §3.5: "A `ProductionScheduler` reserves mass against an order by
    creating a material allocation naming the `production_order_id`, a
    `source_type` of `VIRGIN_LOT` or `REGRIND`, the source identifier
    (`lot_id` or `regrind_batch_id` per the conditional-field rule), and a
    positive `qty_kg`."
    PRD §2.9: "When several rules could reject the same request, checks are
    evaluated in a fixed priority order, and the earliest failing check
    determines the error returned."

    A zero quantity violates the schema tier, which runs before existence
    checks (the referenced ids deliberately do not exist).

    Design: Corner/validations/allocation_zero_quantity_returns_invalid_request
    """
    res = api.create_material_allocation(
        create_material_allocation_payload(
            NON_EXISTENT_UUID, source_type="VIRGIN_LOT",
            lot_id=NON_EXISTENT_UUID, qty_kg=0,
        ),
        _SCHEDULER,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_allocation_beyond_available_returns_insufficient_material(api):
    """PRD §3.5: "and the lot's `available_kg` must be at least the requested
    `qty_kg` (otherwise `ERR_INSUFFICIENT_MATERIAL`)."

    Requesting 4.000kg from a lot holding 3.000kg fails the material
    sufficiency check.

    Design: Corner/validations/allocation_beyond_available_returns_insufficient_material
    """
    lot = create_certified_lot(lot_code="L-V3", quantity_kg=3.000, unit_cost_per_kg=10.00)
    tool = create_tool_prototype(tool_code="T-V3", part_number="P-V3")
    spec = create_stock_spec(spec_code="S-V3")
    order = create_order(tool, spec, order_code="O-V3", ordered_qty=50)
    res = api.create_material_allocation(
        create_material_allocation_payload(
            order["id"], source_type="VIRGIN_LOT", lot_id=lot["id"], qty_kg=4.000
        ),
        _SCHEDULER,
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_MATERIAL)


def test_allocation_resin_mismatch_rejected(api):
    """PRD §3.5: "the lot's `resin_type` must equal the order's `resin_type`
    (otherwise `ERR_RESIN_MISMATCH`)"

    Design: Corner/validations/allocation_resin_mismatch_rejected
    """
    lot = create_certified_lot(lot_code="L-V4", resin_type="ABS")
    tool = create_tool_prototype(tool_code="T-V4", part_number="P-V4")
    spec = create_stock_spec(spec_code="S-V4")
    order = create_order(tool, spec, order_code="O-V4", ordered_qty=50, resin_type="PETG")
    res = api.create_material_allocation(
        create_material_allocation_payload(
            order["id"], source_type="VIRGIN_LOT", lot_id=lot["id"], qty_kg=1.000
        ),
        _SCHEDULER,
    )
    validate_error(res, ApiErrorId.ERR_RESIN_MISMATCH)


def test_allocation_gauge_mismatch_rejected(api):
    """PRD §3.5: "the lot's `gauge_mm` must equal the order's
    `required_gauge_mm` exactly (otherwise `ERR_GAUGE_MISMATCH`)"

    Design: Corner/validations/allocation_gauge_mismatch_rejected
    """
    lot = create_certified_lot(lot_code="L-V5", gauge_mm=2.000)
    tool = create_tool_prototype(tool_code="T-V5", part_number="P-V5")
    spec = create_stock_spec(spec_code="S-V5")
    order = create_order(tool, spec, order_code="O-V5", ordered_qty=50, required_gauge_mm=1.500)
    res = api.create_material_allocation(
        create_material_allocation_payload(
            order["id"], source_type="VIRGIN_LOT", lot_id=lot["id"], qty_kg=1.000
        ),
        _SCHEDULER,
    )
    validate_error(res, ApiErrorId.ERR_GAUGE_MISMATCH)


def test_allocation_from_quarantine_lot_rejected(api):
    """PRD §3.5: "the lot must be `CERTIFIED` (otherwise
    `ERR_INVALID_LOT_STATE`)"

    A lot never released from QUARANTINE (no certificate was ever issued)
    cannot be allocated.

    Design: Corner/validations/allocation_from_quarantine_lot_rejected
    """
    lot = create_lot(lot_code="L-V6")
    tool = create_tool_prototype(tool_code="T-V6", part_number="P-V6")
    spec = create_stock_spec(spec_code="S-V6")
    order = create_order(tool, spec, order_code="O-V6", ordered_qty=50)
    res = api.create_material_allocation(
        create_material_allocation_payload(
            order["id"], source_type="VIRGIN_LOT", lot_id=lot["id"], qty_kg=1.000
        ),
        _SCHEDULER,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_LOT_STATE)


def test_allocation_lot_cert_grade_below_order_rejected(api):
    """PRD §3.5: "a cleanliness certificate must exist for the lot at a grade
    at least the order's grade regardless of its expiry (a rank failure is
    `ERR_GRADE_INCOMPATIBLE`) and that certificate must be currently valid at
    the logical time (otherwise `ERR_CERTIFICATE_INVALID`)"

    The lot's only certificate is INDUSTRIAL while the order is FOOD, so the
    rank check fails.

    Design: Corner/validations/allocation_lot_cert_grade_below_order_rejected
    """
    lot = create_certified_lot(lot_code="L-V7")  # INDUSTRIAL-required, INDUSTRIAL cert
    tool = create_tool_prototype(tool_code="T-V7", part_number="P-V7", cleanliness_grade="FOOD")
    spec = create_stock_spec(spec_code="S-V7", cleanliness_grade="FOOD", per_pack_cost=0.60)
    order = create_order(tool, spec, order_code="O-V7", ordered_qty=50, cleanliness_grade="FOOD")
    res = api.create_material_allocation(
        create_material_allocation_payload(
            order["id"], source_type="VIRGIN_LOT", lot_id=lot["id"], qty_kg=1.000
        ),
        _SCHEDULER,
    )
    validate_error(res, ApiErrorId.ERR_GRADE_INCOMPATIBLE)


def test_allocation_double_release_rejected(api):
    """PRD §3.5: "An allocation in `RESERVED` or `REVIEW` may be released by a
    `ProductionScheduler`; releasing from any other status is
    `ERR_ALLOCATION_NOT_RELEASABLE`."
    PRD §3.1: "reserving a quantity against a lot and later releasing that
    same allocation must leave `available_kg` bit-identical to its value
    before the pair, with equality evaluated at three decimal places."

    Design: Corner/errors/allocation_double_release_rejected
    """
    lot = create_certified_lot(lot_code="L-ERR5")
    tool = create_tool_prototype(tool_code="T-ERR5", part_number="P-ERR5")
    spec = create_stock_spec(spec_code="S-ERR5")
    order = create_order(tool, spec, order_code="O-ERR5", ordered_qty=50)
    alloc = reserve_virgin(order["id"], lot["id"], 2.000)

    released = validate_success(api.release_allocation(alloc["id"], _SCHEDULER), 200)
    assert released["status"] == "RELEASED"

    res = api.release_allocation(alloc["id"], _SCHEDULER)
    validate_error(res, ApiErrorId.ERR_ALLOCATION_NOT_RELEASABLE)

    lot_after = get_lot(lot["id"])
    assert lot_after["available_kg"] == 10.000, (
        f"rejected second release must not restore balance twice, "
        f"got available_kg {lot_after['available_kg']}"
    )
    assert_lot_mass_invariant(lot_after)


def test_allocations_filterable_by_production_order(api):
    """PRD §4: "the foreign-key reverse-reachability filters
    `production_order_id`, `lot_id`, `regrind_batch_id`, `station_id`,
    `forming_run_id`, and `booth_id` on their respective collections"

    The filtered allocation list returns exactly the queried order's two
    allocations.

    Design: Corner/endpoints/allocations_filterable_by_production_order
    """
    lot = create_certified_lot(lot_code="L-E2")
    tool = create_tool_prototype(tool_code="T-E2", part_number="P-E2")
    spec = create_stock_spec(spec_code="S-E2")
    order = create_order(tool, spec, order_code="O-E2", ordered_qty=50)
    a1 = reserve_virgin(order["id"], lot["id"], 2.000)
    a2 = reserve_virgin(order["id"], lot["id"], 3.950)

    data, meta = validate_paginated(
        api.list_material_allocations(_ANY, params={"production_order_id": order["id"]})
    )
    ids = {a["id"] for a in data}
    assert ids == {a1["id"], a2["id"]}, (
        f"filter must return exactly the order's two allocations, got {ids}"
    )
    assert meta["total_count"] == 2


def test_occ_stale_version_stage_rejected(api):
    """PRD §2.7: "A staging request must carry
    `expected_production_order_version`, a non-optional input holding the
    `version` of the order as the client last observed it."
    PRD §2.7: "If that value no longer matches the order's current `version` —
    for example because a material allocation was created or released against
    the order after the client's read, each of which advances the order's
    `version` — the request is rejected with `ERR_STALE_VERSION` (HTTP 412),
    and the client must re-read the order before staging."

    Design: Corner/cross_cutting_layers/occ_stale_version_stage_rejected
    """
    lot = create_certified_lot(lot_code="L-CC1")
    tool = create_tool_prototype(tool_code="T-CC1", part_number="P-CC1")
    spec = create_stock_spec(spec_code="S-CC1")
    order = create_order(tool, spec, order_code="O-CC1", ordered_qty=100)
    reserve_virgin(order["id"], lot["id"], 3.000)
    stale_version = order_version(order["id"])
    reserve_virgin(order["id"], lot["id"], 2.900)  # advances the order version

    res = api.stage_order(order["id"], create_stage_payload(stale_version), _SCHEDULER)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)

    fresh_version = order_version(order["id"])
    assert fresh_version == stale_version + 1, (
        f"the second allocation must advance the order version by exactly one, "
        f"got {stale_version} -> {fresh_version}"
    )
    staged = validate_success(
        api.stage_order(order["id"], create_stage_payload(fresh_version), _SCHEDULER), 200
    )
    assert staged["schedule_status"] == "STAGED", (
        f"re-reading and staging with the fresh version must succeed, got {staged['schedule_status']}"
    )


def test_stage_on_cancelled_order_rejected(api):
    """PRD §3.5: "the order must be `QUEUED` (otherwise
    `ERR_INVALID_ORDER_STATE`)"
    PRD §3.6: "A `ProductionScheduler` may cancel from `QUEUED`, `STAGED`,
    `RUNNING`, or `ON_HOLD` — from anywhere else it is
    `ERR_INVALID_ORDER_STATE`."

    CANCELLED is terminal: staging with a fresh OCC version still fails the
    state check.

    Design: Corner/state_machines/stage_on_cancelled_order_rejected
    """
    tool = create_tool_prototype(tool_code="T-S4", part_number="P-S4")
    spec = create_stock_spec(spec_code="S-S4")
    order = create_order(tool, spec, order_code="O-S4", ordered_qty=50)
    cancelled = validate_success(api.cancel_order(order["id"], _SCHEDULER), 200)
    assert cancelled["schedule_status"] == "CANCELLED"

    res = api.stage_order(order["id"], create_stage_payload(order_version(order["id"])), _SCHEDULER)
    validate_error(res, ApiErrorId.ERR_INVALID_ORDER_STATE)


def test_allocation_state_error_beats_fiscal_error(api):
    """PRD §2.9: "When several rules could reject the same request, checks are
    evaluated in a fixed priority order, and the earliest failing check
    determines the error returned."
    PRD §2.9: "6. **State legality** — the target entity is in a legal
    from-state for the requested transition (the 409 state errors, such as
    `ERR_INVALID_ORDER_STATE`)."
    PRD §2.9: "10. **Material sufficiency** — source pools actually hold the
    requested mass (`ERR_INSUFFICIENT_MATERIAL`)."
    PRD §3.5: "The order's schedule must be `QUEUED`, `STAGED`, or `ON_HOLD`;
    allocating against an order in any other schedule state is
    `ERR_ORDER_NOT_ALLOCATABLE`."

    The order is CANCELLED and the request also exceeds the lot's available
    mass: the state error must win over the fiscal error.

    Design: Difficulty/priority_pair_validation_conflict/allocation_state_beats_fiscal_priority
    """
    lot = create_certified_lot(lot_code="LX", quantity_kg=2.000, unit_cost_per_kg=10.00)
    tool = create_tool_prototype(tool_code="TX", part_number="P-X", prototype_cost=1200.00)
    spec = create_stock_spec(spec_code="S-X")
    order = create_order(tool, spec, order_code="OX", ordered_qty=100)
    validate_success(api.cancel_order(order["id"], _SCHEDULER), 200)

    res = api.create_material_allocation(
        create_material_allocation_payload(
            order["id"], source_type="VIRGIN_LOT", lot_id=lot["id"], qty_kg=5.000
        ),
        _SCHEDULER,
    )
    validate_error(res, ApiErrorId.ERR_ORDER_NOT_ALLOCATABLE)


def test_allocation_on_cancelled_order_rejected_within_availability(api):
    """PRD §3.5: "The order's schedule must be `QUEUED`, `STAGED`, or
    `ON_HOLD`; allocating against an order in any other schedule state is
    `ERR_ORDER_NOT_ALLOCATABLE`."
    PRD §2.9: "When several rules could reject the same request, checks are
    evaluated in a fixed priority order, and the earliest failing check
    determines the error returned."

    Even a request the lot could easily satisfy is rejected on the CANCELLED
    order, and the lot's pool is untouched.

    Design: Difficulty/priority_pair_validation_conflict/allocation_state_beats_fiscal_priority
    """
    lot = create_certified_lot(lot_code="LX2", quantity_kg=2.000, unit_cost_per_kg=10.00)
    tool = create_tool_prototype(tool_code="TX2", part_number="P-X2", prototype_cost=1200.00)
    spec = create_stock_spec(spec_code="S-X2")
    order = create_order(tool, spec, order_code="OX2", ordered_qty=100)
    validate_success(api.cancel_order(order["id"], _SCHEDULER), 200)

    res = api.create_material_allocation(
        create_material_allocation_payload(
            order["id"], source_type="VIRGIN_LOT", lot_id=lot["id"], qty_kg=1.000
        ),
        _SCHEDULER,
    )
    validate_error(res, ApiErrorId.ERR_ORDER_NOT_ALLOCATABLE)
    lot_after = get_lot(lot["id"])
    assert lot_after["available_kg"] == 2.000, (
        f"the rejected allocation must not touch the pool, got {lot_after['available_kg']}"
    )


def test_stage_blocked_when_tool_under_revision(api):
    """PRD §3.5: "the tool must be `PROTOTYPE` or `PRODUCTION` (otherwise
    `ERR_TOOL_NOT_QUALIFIED`)"
    PRD §3.3: "Revising moves `PRODUCTION` → `UNDER_REVISION` (legal only from
    `PRODUCTION`, else `ERR_INVALID_TOOL_TRANSITION`)"

    Staging an order whose tool moved to UNDER_REVISION after the material
    plan was built is rejected even with a fresh OCC version and full
    coverage; the order remains QUEUED.

    Design: Difficulty/cross_entity_state_dependency/stage_blocked_when_tool_under_revision
    """
    lot = create_certified_lot(lot_code="LRV")
    tool = create_tool_production(tool_code="TRV", part_number="P-RV", prototype_cost=1200.00)
    spec = create_stock_spec(spec_code="S-RV")
    order = create_order(tool, spec, order_code="ORV", ordered_qty=100)
    reserve_virgin(order["id"], lot["id"], 5.900)
    fresh_version = order_version(order["id"])

    get_success_data(api.revise_tool(tool["id"], _ENGINEER))
    res = api.stage_order(order["id"], create_stage_payload(fresh_version), _SCHEDULER)
    validate_error(res, ApiErrorId.ERR_TOOL_NOT_QUALIFIED)

    order_after = get_order(order["id"])
    assert order_after["schedule_status"] == "QUEUED", (
        f"the rejected stage must not transition the order, got {order_after['schedule_status']}"
    )


def test_stage_succeeds_when_tool_remains_qualified(api):
    """PRD §3.5: "On success the system computes `provisional_cost` and
    `tooling_charge`, moves the order `QUEUED` → `STAGED`, and advances its
    `version`."
    PRD §3.5: "the tool must be `PROTOTYPE` or `PRODUCTION` (otherwise
    `ERR_TOOL_NOT_QUALIFIED`)"

    The control case for the tool-state dependency: with the tool still
    PRODUCTION, the same order stages and its costs are computed.

    Design: Difficulty/cross_entity_state_dependency/stage_blocked_when_tool_under_revision
    """
    lot = create_certified_lot(lot_code="LRV2")
    tool = create_tool_production(tool_code="TRV2", part_number="P-RV2", prototype_cost=1200.00)
    spec = create_stock_spec(spec_code="S-RV2")
    order = create_order(tool, spec, order_code="ORV2", ordered_qty=100)
    reserve_virgin(order["id"], lot["id"], 5.900)

    staged = stage_order(order["id"])
    assert staged["schedule_status"] == "STAGED"
    assert staged["provisional_cost"] is not None, "provisional_cost must be computed at stage"
    assert staged["tooling_charge"] is not None, "tooling_charge must be computed at stage"


def test_lot_mass_allocate_tracks_available_kg(api):
    """PRD §3.1: "`available_kg` is always exactly `quantity_kg` minus
    `allocated_kg` minus `consumed_kg`."
    PRD §3.5: "Creating one adds `qty_kg` to the lot's `allocated_kg` or the
    batch's `reserved_kg` and advances the order's `version` by one."

    Design: Difficulty/compensating_invariant/lot_mass_allocate_release_conservation
    """
    lot = create_certified_lot(
        lot_code="LM", resin_type="HIPS", gauge_mm=2.000,
        quantity_kg=10.000, unit_cost_per_kg=8.00,
    )
    tool = create_tool_prototype(tool_code="TM", part_number="P-M", prototype_cost=900.00)
    spec = create_stock_spec(spec_code="S-M9")
    order = create_order(
        tool, spec, order_code="OM", resin_type="HIPS", ordered_qty=50,
        required_gauge_mm=2.000, spec_nominal_wall_mm=1.500, spec_min_wall_mm=1.400,
        std_machine_rate_per_hour=50.00,
    )
    baseline = get_lot(lot["id"])
    assert baseline["available_kg"] == 10.000

    alloc = reserve_virgin(order["id"], lot["id"], 4.000)
    assert alloc["status"] == "RESERVED"

    mid = get_lot(lot["id"])
    assert mid["allocated_kg"] == 4.000, f"allocated_kg must be 4.000, got {mid['allocated_kg']}"
    assert mid["available_kg"] == 6.000, f"available_kg must be 6.000, got {mid['available_kg']}"
    assert_lot_mass_invariant(mid)


def test_lot_mass_release_restores_available_kg_bit_identical(api):
    """PRD §3.1: "reserving a quantity against a lot and later releasing that
    same allocation must leave `available_kg` bit-identical to its value
    before the pair, with equality evaluated at three decimal places."
    PRD §3.5: "Release moves the allocation to `RELEASED`, subtracts its
    `qty_kg` from the lot's `allocated_kg` or the batch's `reserved_kg`, and
    advances the order's `version`."
    PRD §2.4: "`version` is an integer that increments by exactly one on every
    successful mutation of the resource, including mutations driven by system
    cascades rather than direct client action."

    Design: Difficulty/compensating_invariant/lot_mass_allocate_release_conservation
    """
    lot = create_certified_lot(
        lot_code="LM2", resin_type="HIPS", gauge_mm=2.000,
        quantity_kg=10.000, unit_cost_per_kg=8.00,
    )
    tool = create_tool_prototype(tool_code="TM2", part_number="P-M2", prototype_cost=900.00)
    spec = create_stock_spec(spec_code="S-M9B")
    order = create_order(
        tool, spec, order_code="OM2", resin_type="HIPS", ordered_qty=50,
        required_gauge_mm=2.000, spec_nominal_wall_mm=1.500, spec_min_wall_mm=1.400,
        std_machine_rate_per_hour=50.00,
    )
    v0 = order_version(order["id"])

    alloc = reserve_virgin(order["id"], lot["id"], 4.000)
    v1 = order_version(order["id"])

    released = validate_success(api.release_allocation(alloc["id"], _SCHEDULER), 200)
    assert released["status"] == "RELEASED"
    v2 = order_version(order["id"])

    end = get_lot(lot["id"])
    assert end["available_kg"] == 10.000, (
        f"the allocate/release pair must restore available_kg bit-identically, "
        f"got {end['available_kg']}"
    )
    assert end["allocated_kg"] == 0 and end["consumed_kg"] == 0
    assert_lot_mass_invariant(end)
    assert v1 == v0 + 1 and v2 == v1 + 1, (
        f"allocate and release must each advance the order version by exactly one, "
        f"got {v0} -> {v1} -> {v2}"
    )
