"""Validation precedence, cross-entity dependency, temporal overlap, and
compensating-invariant depth tests (queue A). PRD §2.7, §3.2, §3.3, §3.6, §3.8.
"""
from test_helpers import (
    TEST_USERS,
    create_allocation_payload,
    get_success_data,
    read_lease,
    read_vehicle,
    setup_active_lease,
    setup_assessed_repair,
    setup_card_with_txn,
    setup_scheduled_maintenance,
    setup_settlement_open,
    validate_error,
    validate_success,
)

FM = TEST_USERS["fleet_manager_headers"]
TG = TEST_USERS["telematics_gateway_headers"]


# ===========================================================================
# priority_pair_validation_conflict / allocation_license_invalid_beats_overlap
# ===========================================================================

def test_license_invalid_beats_overlap(api):
    """PRD §2.7: "Only after all of those pass are the operation-specific
    business rules — vehicle availability, driver license standing, lease
    activeness, window overlaps, odometer monotonicity, fuel-card standing,
    open-blocker gates, qualified-fuel presence, total-loss thresholds, and
    the optimistic-concurrency version match — evaluated."

    Driver license standing precedes window overlaps, so a SUSPENDED driver
    on an overlapping window yields ERR_DRIVER_LICENSE_INVALID.

    Design: Difficulty/priority_pair_validation_conflict/allocation_license_invalid_beats_overlap
    """
    lessee, vehicle, lease = setup_active_lease(vehicle_class="LIGHT_DUTY")
    good = get_success_data(api.create_driver(
        {"lessee_id": lessee["id"], "full_name": "Good", "license_number": "LIC-GOOD"}, FM))
    bad = get_success_data(api.create_driver(
        {"lessee_id": lessee["id"], "full_name": "Bad", "license_number": "LIC-BAD"}, FM))
    get_success_data(api.suspend_license(bad["id"], FM))
    alloc = get_success_data(api.create_allocation(
        create_allocation_payload(lease["id"], good["id"], lease["version"]), FM))
    resp = api.create_allocation(
        create_allocation_payload(
            lease["id"], bad["id"], alloc["version"],
            window_start="2026-06-05T00:00:00Z", window_end="2026-06-15T00:00:00Z",
        ), FM)
    validate_error(resp, "ERR_DRIVER_LICENSE_INVALID")


def test_suspended_driver_allocation_rejected(api):
    """PRD §3.3: "The referenced driver's `license_status` must be `VALID`;
    assigning a vehicle to a driver whose license is `SUSPENDED` is rejected
    with `ERR_DRIVER_LICENSE_INVALID` (HTTP 409)."

    Isolated: a SUSPENDED driver on a non-overlapping window still fails on
    the license rule.

    Design: Difficulty/priority_pair_validation_conflict/allocation_license_invalid_beats_overlap
    """
    lessee, vehicle, lease = setup_active_lease(vehicle_class="LIGHT_DUTY")
    bad = get_success_data(api.create_driver(
        {"lessee_id": lessee["id"], "full_name": "Bad", "license_number": "LIC-BAD2"}, FM))
    get_success_data(api.suspend_license(bad["id"], FM))
    resp = api.create_allocation(
        create_allocation_payload(lease["id"], bad["id"], lease["version"]), FM)
    validate_error(resp, "ERR_DRIVER_LICENSE_INVALID")


# ===========================================================================
# priority_pair_validation_conflict / settlement_open_blockers_beats_nothing_state_vs_constraint
# ===========================================================================

def test_open_blockers_blocks_finalize(api):
    """PRD §3.7: "Finalizing the settlement — the `DRAFT` to `FINALIZED`
    transition — is permitted only when the settlement is `DRAFT` and its
    lease is `PENDING_SETTLEMENT`, and it is additionally gated on the vehicle
    having no open blockers: if the vehicle's `open_block_count` is greater
    than zero, finalization is rejected with `ERR_OPEN_BLOCKERS` (HTTP 409)."

    State is valid (settlement DRAFT, lease PENDING_SETTLEMENT) but the
    vehicle has an open ASSESSED repair, so the open-blocker gate fires.

    Design: Difficulty/priority_pair_validation_conflict/settlement_open_blockers_beats_nothing_state_vs_constraint
    """
    lessee, vehicle, lease = setup_active_lease(vehicle_class="HEAVY_DUTY")
    veh = read_vehicle(vehicle["id"])
    repair = get_success_data(api.create_repair_order(
        {"vehicle_id": vehicle["id"], "lease_id": lease["id"],
         "expected_vehicle_version": veh["version"]}, FM))
    get_success_data(api.assess_repair(
        repair["id"], {"estimate_cents": 100000, "insurance_cap_cents": 800000}, FM))
    get_success_data(api.create_telematics_reading(
        {"vehicle_id": vehicle["id"], "jurisdiction": "CA", "odometer_miles": 70000,
         "segment_miles": 70000, "recorded_at": "2026-06-01T00:00:00Z"}, TG))
    get_success_data(api.initiate_return(lease["id"], FM))
    settlement = get_success_data(api.create_settlement({"lease_id": lease["id"]}, FM))
    resp = api.finalize_settlement(settlement["id"], FM)
    validate_error(resp, "ERR_OPEN_BLOCKERS")


def test_open_blockers_clears_after_repair_rejected(api):
    """PRD §3.7: "...if the vehicle's `open_block_count` is greater than zero,
    finalization is rejected with `ERR_OPEN_BLOCKERS` (HTTP 409)."

    Once the open blocker is removed (repair rejected → open_block_count 0),
    finalize is no longer blocked by the open-blocker gate.

    Design: Difficulty/priority_pair_validation_conflict/settlement_open_blockers_beats_nothing_state_vs_constraint
    """
    lessee, vehicle, lease = setup_active_lease(vehicle_class="HEAVY_DUTY")
    veh = read_vehicle(vehicle["id"])
    repair = get_success_data(api.create_repair_order(
        {"vehicle_id": vehicle["id"], "lease_id": lease["id"],
         "expected_vehicle_version": veh["version"]}, FM))
    get_success_data(api.assess_repair(
        repair["id"], {"estimate_cents": 100000, "insurance_cap_cents": 800000}, FM))
    get_success_data(api.create_telematics_reading(
        {"vehicle_id": vehicle["id"], "jurisdiction": "CA", "odometer_miles": 70000,
         "segment_miles": 70000, "recorded_at": "2026-06-01T00:00:00Z"}, TG))
    get_success_data(api.initiate_return(lease["id"], FM))
    settlement = get_success_data(api.create_settlement({"lease_id": lease["id"]}, FM))
    # remove the blocker
    get_success_data(api.reject_repair(repair["id"], FM))
    data = validate_success(api.finalize_settlement(settlement["id"], FM), 200)
    assert data["status"] == "FINALIZED", data


# ===========================================================================
# cross_entity_state_dependency / lease_activate_requires_vehicle_available
# ===========================================================================

def test_activate_requires_available_vehicle(api):
    """PRD §3.2: "If the vehicle is in any state other than `AVAILABLE`,
    activation is refused with `ERR_VEHICLE_NOT_AVAILABLE` (HTTP 409)."

    A second lease on a vehicle already ALLOCATED by lease A cannot activate.

    Design: Difficulty/cross_entity_state_dependency/lease_activate_requires_vehicle_available
    """
    lessee, vehicle, lease_a = setup_active_lease(vehicle_class="LIGHT_DUTY")
    lease_b = get_success_data(api.create_lease(
        {"lessee_id": lessee["id"], "vehicle_id": vehicle["id"],
         "term_start": "2026-01-01T00:00:00Z", "term_end": "2026-12-31T00:00:00Z",
         "contracted_miles": 60000, "per_mile_overage_cents": 25,
         "overage_model": "CONTRACT_FLAT", "collision_deductible_cents": 100000,
         "waterfall_model": "DEDUCTIBLE_FIRST"}, FM))
    resp = api.activate_lease(lease_b["id"], FM)
    validate_error(resp, "ERR_VEHICLE_NOT_AVAILABLE")


def test_activate_succeeds_on_available_vehicle(api):
    """PRD §3.2: "Activating a draft lease — the `DRAFT` to `ACTIVE`
    transition — requires that the lease currently be `DRAFT`, that the
    referenced vehicle be `AVAILABLE`, and that the lessee's account be
    `ACTIVE`."

    A lease on a fresh AVAILABLE vehicle activates successfully (the positive
    arm of the dependency).

    Design: Difficulty/cross_entity_state_dependency/lease_activate_requires_vehicle_available
    """
    _, vehicle, lease = setup_active_lease(vehicle_class="LIGHT_DUTY")
    assert lease["status"] == "ACTIVE", lease
    assert read_vehicle(vehicle["id"])["status"] == "ALLOCATED"


# ===========================================================================
# cross_entity_state_dependency / allocation_create_requires_lease_active
# ===========================================================================

def test_allocation_requires_active_lease(api):
    """PRD §3.3: "The referenced lease's `status` must be `ACTIVE`; an
    allocation against a lease in any other state is rejected with
    `ERR_LEASE_NOT_ACTIVE` (HTTP 409)."

    A lease still in DRAFT rejects allocation create.

    Design: Difficulty/cross_entity_state_dependency/allocation_create_requires_lease_active
    """
    lessee = get_success_data(api.create_lessee(
        {"company_name": "CE2 Co", "billing_email": "ce2@x.com"}, FM))
    vehicle = get_success_data(api.create_vehicle(
        {"vin": "VINCE20001", "class": "LIGHT_DUTY"}, FM))
    driver = get_success_data(api.create_driver(
        {"lessee_id": lessee["id"], "full_name": "D2", "license_number": "LIC-CE2"}, FM))
    lease = get_success_data(api.create_lease(
        {"lessee_id": lessee["id"], "vehicle_id": vehicle["id"],
         "term_start": "2026-01-01T00:00:00Z", "term_end": "2026-12-31T00:00:00Z",
         "contracted_miles": 60000, "per_mile_overage_cents": 25,
         "overage_model": "CONTRACT_FLAT", "collision_deductible_cents": 100000,
         "waterfall_model": "DEDUCTIBLE_FIRST"}, FM))
    resp = api.create_allocation(
        create_allocation_payload(lease["id"], driver["id"], lease["version"]), FM)
    validate_error(resp, "ERR_LEASE_NOT_ACTIVE")


def test_allocation_succeeds_on_active_lease(api):
    """PRD §3.3: "An allocation is born `ASSIGNED` and can later be released."

    The positive arm: against an ACTIVE lease with a VALID driver, allocation
    create succeeds and the allocation is ASSIGNED.

    Design: Difficulty/cross_entity_state_dependency/allocation_create_requires_lease_active
    """
    lessee, vehicle, lease = setup_active_lease(vehicle_class="LIGHT_DUTY")
    driver = get_success_data(api.create_driver(
        {"lessee_id": lessee["id"], "full_name": "OK D", "license_number": "LIC-OKD"}, FM))
    data = validate_success(api.create_allocation(
        create_allocation_payload(lease["id"], driver["id"], lease["version"]), FM), 201)
    assert data["status"] == "ASSIGNED", data


# ===========================================================================
# resource_temporal_overlap / allocation_half_open_overlap_on_vehicle
# ===========================================================================

def test_allocation_overlap_rejected(api):
    """PRD §3.3: "the requested half-open window must not overlap any other
    `ASSIGNED` allocation on the same lease's vehicle: two intervals that
    merely touch at the boundary (one ending exactly when the next begins)
    do not overlap and are allowed, but any genuine overlap is rejected with
    `ERR_ALLOCATION_OVERLAP` (HTTP 409)."

    [06-05,06-15) genuinely overlaps existing [06-01,06-10).

    Design: Difficulty/resource_temporal_overlap/allocation_half_open_overlap_on_vehicle
    """
    lessee, vehicle, lease = setup_active_lease(vehicle_class="LIGHT_DUTY")
    d1 = get_success_data(api.create_driver(
        {"lessee_id": lessee["id"], "full_name": "D1", "license_number": "LIC-TO1-1"}, FM))
    d2 = get_success_data(api.create_driver(
        {"lessee_id": lessee["id"], "full_name": "D2", "license_number": "LIC-TO1-2"}, FM))
    alloc = get_success_data(api.create_allocation(
        create_allocation_payload(lease["id"], d1["id"], lease["version"]), FM))
    resp = api.create_allocation(
        create_allocation_payload(
            lease["id"], d2["id"], alloc["version"],
            window_start="2026-06-05T00:00:00Z", window_end="2026-06-15T00:00:00Z",
        ), FM)
    validate_error(resp, "ERR_ALLOCATION_OVERLAP")


def test_allocation_boundary_adjacency_allowed(api):
    """PRD §3.3: "two intervals that merely touch at the boundary (one ending
    exactly when the next begins) do not overlap and are allowed."

    [06-10,06-20) is adjacent to existing [06-01,06-10) → allowed.

    Design: Difficulty/resource_temporal_overlap/allocation_half_open_overlap_on_vehicle
    """
    lessee, vehicle, lease = setup_active_lease(vehicle_class="LIGHT_DUTY")
    d1 = get_success_data(api.create_driver(
        {"lessee_id": lessee["id"], "full_name": "D1", "license_number": "LIC-ADJ-1"}, FM))
    d2 = get_success_data(api.create_driver(
        {"lessee_id": lessee["id"], "full_name": "D2", "license_number": "LIC-ADJ-2"}, FM))
    get_success_data(api.create_allocation(
        create_allocation_payload(lease["id"], d1["id"], lease["version"]), FM))
    # The first create incremented the lease's version (PRD §3.3); re-read it.
    current_lease_version = read_lease(lease["id"])["version"]
    data = validate_success(api.create_allocation(
        create_allocation_payload(
            lease["id"], d2["id"], current_lease_version,
            window_start="2026-06-10T00:00:00Z", window_end="2026-06-20T00:00:00Z",
        ), FM), 201)
    assert data["status"] == "ASSIGNED", data


# ===========================================================================
# resource_temporal_overlap / maintenance_buffer_window_overlap_on_vehicle
# ===========================================================================

def test_maintenance_buffer_overlap_rejected(api):
    """PRD §3.6: "Equivalently, two maintenance windows on a vehicle conflict
    whenever the clear gap between them is sixty minutes or less; a gap
    strictly greater than sixty minutes is required for the new order to be
    accepted. A violation is rejected with `ERR_MAINTENANCE_OVERLAP`
    (HTTP 409)."

    A [12:30,13:00] window sits 30 min after [10:00,12:00] (gap <= 60) →
    rejected.

    Design: Difficulty/resource_temporal_overlap/maintenance_buffer_window_overlap_on_vehicle
    """
    _, vehicle, _, mo1 = setup_scheduled_maintenance(
        vehicle_class="MEDIUM_DUTY",
        mo_overrides={"window_start": "2026-06-01T10:00:00Z",
                      "window_end": "2026-06-01T12:00:00Z"},
    )
    resp = api.create_maintenance_order(
        {"vehicle_id": vehicle["id"], "kind": "CORRECTIVE",
         "labor_cents": 1000, "parts_cents": 1000,
         "window_start": "2026-06-01T12:30:00Z", "window_end": "2026-06-01T13:00:00Z"}, FM)
    validate_error(resp, "ERR_MAINTENANCE_OVERLAP")


def test_maintenance_gap_above_buffer_allowed(api):
    """PRD §3.6: "a gap strictly greater than sixty minutes is required for
    the new order to be accepted."

    A [13:01,14:00] window sits 61 min after [10:00,12:00] (gap > 60) →
    accepted.

    Design: Difficulty/resource_temporal_overlap/maintenance_buffer_window_overlap_on_vehicle
    """
    _, vehicle, _, mo1 = setup_scheduled_maintenance(
        vehicle_class="MEDIUM_DUTY",
        mo_overrides={"window_start": "2026-06-01T10:00:00Z",
                      "window_end": "2026-06-01T12:00:00Z"},
    )
    data = validate_success(api.create_maintenance_order(
        {"vehicle_id": vehicle["id"], "kind": "CORRECTIVE",
         "labor_cents": 1000, "parts_cents": 1000,
         "window_start": "2026-06-01T13:01:00Z", "window_end": "2026-06-01T14:00:00Z"}, FM), 201)
    assert data["status"] == "SCHEDULED", data


# ===========================================================================
# compensating_invariant / repair_assess_then_reject_conserves_open_block_count
# ===========================================================================

def test_assess_then_reject_conserves_block_count(api):
    """PRD §3.8: "Assessment — the `REPORTED` to `ASSESSED` transition,
    permitted only from `REPORTED` — records the adjuster's `estimate_cents`
    ... and increments the vehicle's `open_block_count` by 1."
    PRD §3.8: "A claim in `ASSESSED` may also be rejected outright — the
    `ASSESSED` to `REJECTED` transition ... which decrements the vehicle's
    `open_block_count` by 1 and moves the order to its terminal `REJECTED`
    state."

    assess (+1) then reject (-1) leaves open_block_count back at 0.

    Design: Difficulty/compensating_invariant/repair_assess_then_reject_conserves_open_block_count
    """
    _, vehicle, _, repair = setup_assessed_repair(
        estimate_cents=100000, insurance_cap_cents=800000,
    )
    assert read_vehicle(vehicle["id"])["open_block_count"] == 1
    data = validate_success(api.reject_repair(repair["id"], FM), 200)
    assert data["status"] == "REJECTED", data
    assert read_vehicle(vehicle["id"])["open_block_count"] == 0


def test_reject_returns_vehicle_to_allocated(api):
    """PRD §3.8: "A claim in `ASSESSED` may also be rejected outright — the
    `ASSESSED` to `REJECTED` transition ... which decrements the vehicle's
    `open_block_count` by 1 and moves the order to its terminal `REJECTED`
    state."

    Since assess did not move the vehicle off ALLOCATED, the conserved state
    is ALLOCATED after the compensating reject.

    Design: Difficulty/compensating_invariant/repair_assess_then_reject_conserves_open_block_count
    """
    _, vehicle, _, repair = setup_assessed_repair(
        estimate_cents=100000, insurance_cap_cents=800000,
    )
    validate_success(api.reject_repair(repair["id"], FM), 200)
    assert read_vehicle(vehicle["id"])["status"] == "ALLOCATED"


# ===========================================================================
# compensating_invariant / fuel_post_then_void_conserves_card_gallons
# ===========================================================================

def test_post_then_void_conserves_card_gallons(api):
    """PRD §3.4: "A posted transaction can be voided — the `POSTED` to
    `VOIDED` transition, permitted only from `POSTED` — which moves it to its
    terminal `VOIDED` state and compensating-reverses its effect by
    subtracting its `gallons` back out of the card's `total_gallons_purchased`."

    Post 120 (+120) then void (-120) leaves total_gallons_purchased at 0.

    Design: Difficulty/compensating_invariant/fuel_post_then_void_conserves_card_gallons
    """
    _, _, _, card, txn = setup_card_with_txn(gallons=120)
    data = validate_success(api.void_fuel_transaction(txn["id"], FM), 200)
    assert data["status"] == "VOIDED", data
    card_after = validate_success(api.get_fuel_card(card["id"], FM), 200)
    assert card_after["total_gallons_purchased"] == 0, card_after


def test_post_adds_gallons_before_void(api):
    """PRD §3.4: "Each successful post adds the transaction's gallons to the
    card's `total_gallons_purchased`."

    The pre-void leg of the conservation pair: total reads 120.

    Design: Difficulty/compensating_invariant/fuel_post_then_void_conserves_card_gallons
    """
    _, _, _, card, txn = setup_card_with_txn(gallons=120)
    card_before = validate_success(api.get_fuel_card(card["id"], FM), 200)
    assert card_before["total_gallons_purchased"] == 120, card_before
