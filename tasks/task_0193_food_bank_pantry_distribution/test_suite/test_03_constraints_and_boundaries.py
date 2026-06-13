"""Cold-chain / capacity / cycle / fair-share / certification constraints,
validation-precedence pairs, numeric boundary precision, cross-entity state
gates, and FEFO consumption ordering.

Covers Difficulty queue rules priority_pair_validation_conflict,
boundary_precision_check, cross_entity_state_dependency, and
resource_temporal_overlap.
"""
from prd_bench_local_runner.testing import (
    validate_success, validate_error, validate_paginated,
)
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS, fixtures, factories,
    make_agency_coordinator_headers,
)

MGR = TEST_USERS["allocation_manager_headers"]
OP = TEST_USERS["food_bank_operator_headers"]


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict
# ---------------------------------------------------------------------------

def test_cold_chain_mismatch_beats_capacity_on_intake(api):
    """PRD §2.5: "At intake, the derived required_temp_zone must equal the holding
    unit's temp_zone; a mismatch is rejected with ERR_COLD_CHAIN_MISMATCH."
    PRD §4: "and finally the domain-specific business rules (cold-chain, household
    certification, agency standing, cycle openness, capacity, over-distribution,
    fair-share cap, and lot-version OCC, in that order)."

    Design: Difficulty/priority_pair_validation_conflict/cold_chain_mismatch_beats_capacity_on_intake
    """
    # DRY unit full at capacity 100; intake a PRODUCE (REFRIGERATED) lot -> both
    # cold-chain mismatch and capacity overage; cold-chain (earlier rule) wins.
    unit = fixtures.create_cold_storage_unit(name="DryFull", temp_zone="DRY", capacity_lbs=100)
    fixtures.create_inventory_lot(unit["id"], food_category="DRY_GOODS",
                                  source_type="DONATION", intake_lbs=100,
                                  expiration_date="2026-12-01T00:00:00.000Z")
    resp = api.create_inventory_lot(
        factories.create_inventory_lot_payload(
            unit["id"], food_category="PRODUCE", source_type="DONATION",
            intake_lbs=50, expiration_date="2026-12-01T00:00:00.000Z"),
        OP)
    validate_error(resp, ApiErrorId.ERR_COLD_CHAIN_MISMATCH.value)


def test_cold_chain_mismatch_wins_even_when_unit_empty(api):
    """PRD §2.5: "At intake, the derived required_temp_zone must equal the holding
    unit's temp_zone; a mismatch is rejected with ERR_COLD_CHAIN_MISMATCH."
    PRD §2.5: "produce and dairy require REFRIGERATED, frozen meat requires FROZEN,
    and dry goods and bakery require DRY."

    Design: Difficulty/priority_pair_validation_conflict/cold_chain_mismatch_beats_capacity_on_intake
    """
    # Mismatch on a small DRY unit: intake of a FROZEN_MEAT (requires FROZEN) lot
    # well within capacity still fails on cold-chain — confirming the safety check
    # is what fires (capacity would otherwise pass).
    unit = fixtures.create_cold_storage_unit(name="DrySmall", temp_zone="DRY", capacity_lbs=1000)
    resp = api.create_inventory_lot(
        factories.create_inventory_lot_payload(
            unit["id"], food_category="FROZEN_MEAT", source_type="PURCHASED",
            intake_lbs=10, expiration_date="2026-12-01T00:00:00.000Z", unit_cost_cents=300),
        OP)
    validate_error(resp, ApiErrorId.ERR_COLD_CHAIN_MISMATCH.value)


# ---------------------------------------------------------------------------
# boundary_precision_check
# ---------------------------------------------------------------------------

def test_cold_storage_exact_fill_allowed_flips_status_full(api):
    """PRD §2.5: "An intake that lands the unit exactly at capacity is permitted;
    only a strict overage is refused."
    PRD §2.5: "it reads FULL when stored_lbs equals capacity_lbs"

    Design: Difficulty/boundary_precision_check/cold_storage_capacity_exact_fill_allowed
    """
    unit = fixtures.create_cold_storage_unit(temp_zone="REFRIGERATED", capacity_lbs=500)
    fixtures.create_inventory_lot(unit["id"], food_category="PRODUCE",
                                  intake_lbs=300,
                                  expiration_date="2026-09-01T00:00:00.000Z")
    resp = api.create_inventory_lot(
        factories.create_inventory_lot_payload(
            unit["id"], food_category="DAIRY", source_type="DONATION",
            intake_lbs=200, expiration_date="2026-09-01T00:00:00.000Z"),
        OP)
    validate_success(resp, expected_status=201)  # 300+200 == 500, allowed
    refetched = validate_success(api.get_cold_storage_unit(unit["id"], OP))
    assert refetched["stored_lbs"] == 500.00, \
        f"stored_lbs should reach exactly 500, got {refetched['stored_lbs']}"
    assert refetched["status"] == "FULL", \
        f"unit at capacity should be FULL, got {refetched['status']}"


def test_cold_storage_one_pound_over_capacity_rejected(api):
    """PRD §2.5: "a lot whose intake_lbs would push the holding unit's stored_lbs
    strictly above its capacity_lbs is rejected with
    ERR_COLD_STORAGE_CAPACITY_EXCEEDED."
    PRD §2.5: "only a strict overage is refused."

    Design: Difficulty/boundary_precision_check/cold_storage_capacity_exact_fill_allowed
    """
    # X+1 side of the boundary: 300 + 201 = 501 > 500 capacity is refused.
    unit = fixtures.create_cold_storage_unit(temp_zone="REFRIGERATED", capacity_lbs=500)
    fixtures.create_inventory_lot(unit["id"], food_category="PRODUCE",
                                  intake_lbs=300,
                                  expiration_date="2026-09-01T00:00:00.000Z")
    resp = api.create_inventory_lot(
        factories.create_inventory_lot_payload(
            unit["id"], food_category="DAIRY", source_type="DONATION",
            intake_lbs=201, expiration_date="2026-09-01T00:00:00.000Z"),
        OP)
    validate_error(resp, ApiErrorId.ERR_COLD_STORAGE_CAPACITY_EXCEEDED.value)
    refetched = validate_success(api.get_cold_storage_unit(unit["id"], OP))
    assert refetched["stored_lbs"] == 300.00, \
        f"occupancy unchanged at 300 after rejected over-capacity intake, got {refetched['stored_lbs']}"


def test_tefap_income_exactly_at_threshold_is_eligible(api):
    """PRD §3.3: "the threshold in cents equals 199800 cents for the first person
    plus 70500 cents for each member beyond the first."
    PRD §3.3: "The household is tefap_eligible when its monthly_income_cents is at
    or below this threshold; a household whose income lands exactly on the
    threshold is eligible."

    Design: Difficulty/boundary_precision_check/tefap_income_exactly_at_threshold_is_eligible
    """
    # size 3 -> threshold = 199800 + 2*70500 = 340800; income exactly at threshold.
    agency = fixtures.create_agency()
    resp = api.create_client_household(
        factories.create_client_household_payload(
            agency["id"], household_size=3, monthly_income_cents=340800),
        make_agency_coordinator_headers(agency["id"]))
    hh = validate_success(resp, expected_status=201)
    assert hh["tefap_eligible"] is True, \
        f"income == threshold (340800) should be eligible, got {hh['tefap_eligible']}"
    assert hh["certification_status"] == "PENDING", \
        f"new household starts PENDING, got {hh['certification_status']}"


def test_tefap_income_one_cent_over_threshold_is_ineligible(api):
    """PRD §3.3: "The household is tefap_eligible when its monthly_income_cents is
    at or below this threshold; a household whose income lands exactly on the
    threshold is eligible."
    PRD §3.3: "the threshold in cents equals 199800 cents for the first person plus
    70500 cents for each member beyond the first."

    Design: Difficulty/boundary_precision_check/tefap_income_exactly_at_threshold_is_eligible
    """
    # X+1 side: size 3 threshold 340800; income 340801 is one cent over -> ineligible.
    agency = fixtures.create_agency()
    resp = api.create_client_household(
        factories.create_client_household_payload(
            agency["id"], household_size=3, monthly_income_cents=340801),
        make_agency_coordinator_headers(agency["id"]))
    hh = validate_success(resp, expected_status=201)
    assert hh["tefap_eligible"] is False, \
        f"income 340801 > threshold 340800 should be ineligible, got {hh['tefap_eligible']}"


# ---------------------------------------------------------------------------
# cross_entity_state_dependency
# ---------------------------------------------------------------------------

def test_pack_blocked_when_household_not_certified(api):
    """PRD §3.7: "Packing a PLANNED event requires that its linked AgencyOrder be
    APPROVED and its linked ClientHousehold be CERTIFIED"
    PRD §3.7: "A pack attempted when the household is not CERTIFIED, or when a TEFAP
    line is being packed for a household that is not tefap_eligible, is rejected
    with ERR_HOUSEHOLD_NOT_CERTIFIED."

    Design: Difficulty/cross_entity_state_dependency/event_pack_requires_household_certified
    """
    # household left PENDING (not certified).
    ctx = fixtures.setup_planned_event(requested_lbs=200, intake_lbs=500, certify=False)
    agency_id = ctx["agency"]["id"]
    resp = api.pack_distribution_event(ctx["event"]["id"],
                                       make_agency_coordinator_headers(agency_id))
    validate_error(resp, ApiErrorId.ERR_HOUSEHOLD_NOT_CERTIFIED.value)
    event = validate_success(api.get_distribution_event(ctx["event"]["id"],
                             make_agency_coordinator_headers(agency_id)))
    assert event["status"] == "PLANNED", \
        f"event unchanged on blocked pack, got {event['status']}"


def test_pack_succeeds_once_household_certified(api):
    """PRD §3.7: "Packing a PLANNED event requires that its linked AgencyOrder be
    APPROVED and its linked ClientHousehold be CERTIFIED"
    PRD §3.7: "On a valid pack the event moves from PLANNED to PACKED"

    Design: Difficulty/cross_entity_state_dependency/event_pack_requires_household_certified
    """
    # Same scenario, but the household IS certified -> the cross-entity gate passes.
    ctx = fixtures.setup_planned_event(requested_lbs=200, intake_lbs=500, certify=True)
    agency_id = ctx["agency"]["id"]
    packed = validate_success(api.pack_distribution_event(
        ctx["event"]["id"], make_agency_coordinator_headers(agency_id)))
    assert packed["status"] == "PACKED", \
        f"pack should succeed once household is CERTIFIED, got {packed['status']}"


def test_approve_succeeds_while_cycle_open(api):
    """PRD §3.4: "Only orders drawing from an OPEN cycle may be submitted or
    approved."
    PRD §3.5: "the order moves from SUBMITTED to APPROVED, and the order's version
    is bumped."

    Design: Difficulty/cross_entity_state_dependency/order_approve_requires_cycle_open
    """
    # Same scenario, cycle left OPEN -> the cross-entity cycle gate passes.
    unit = fixtures.create_cold_storage_unit(temp_zone="REFRIGERATED", capacity_lbs=5000)
    lot = fixtures.create_inventory_lot(unit["id"], food_category="PRODUCE",
                                        intake_lbs=500,
                                        expiration_date="2026-07-01T00:00:00.000Z")
    agency = fixtures.create_agency()
    cycle = fixtures.create_open_cycle()
    order = fixtures.submit_order(
        agency["id"], cycle["id"],
        lines=[{"food_category": "PRODUCE", "requested_lbs": 200}])
    approved = validate_success(api.approve_agency_order(
        order["id"], {"expected_lot_version": lot["version"]}, MGR))
    assert approved["status"] == "APPROVED", \
        f"approve should succeed against an OPEN cycle, got {approved['status']}"


# ---------------------------------------------------------------------------
# resource_temporal_overlap
# ---------------------------------------------------------------------------

def test_cold_storage_capacity_aggregate_occupancy_overlap_rejected(api):
    """PRD §2.5: "a lot whose intake_lbs would push the holding unit's stored_lbs
    strictly above its capacity_lbs is rejected with
    ERR_COLD_STORAGE_CAPACITY_EXCEEDED."
    PRD §2.5: "the sum of remaining_lbs over every InventoryLot whose
    cold_storage_unit_id points at this unit and whose disposition is either
    AVAILABLE or RESERVED."

    Design: Difficulty/resource_temporal_overlap/cold_storage_capacity_aggregate_occupancy_overlap
    """
    unit = fixtures.create_cold_storage_unit(temp_zone="REFRIGERATED", capacity_lbs=500)
    fixtures.create_inventory_lot(unit["id"], food_category="PRODUCE",
                                  intake_lbs=250, expiration_date="2026-09-01T00:00:00.000Z")
    fixtures.create_inventory_lot(unit["id"], food_category="DAIRY",
                                  intake_lbs=200, expiration_date="2026-09-01T00:00:00.000Z")
    resp = api.create_inventory_lot(
        factories.create_inventory_lot_payload(
            unit["id"], food_category="PRODUCE", source_type="DONATION",
            intake_lbs=100, expiration_date="2026-09-01T00:00:00.000Z"),
        OP)
    validate_error(resp, ApiErrorId.ERR_COLD_STORAGE_CAPACITY_EXCEEDED.value)
    refetched = validate_success(api.get_cold_storage_unit(unit["id"], OP))
    assert refetched["stored_lbs"] == 450.00, \
        f"occupancy unchanged at 450 after rejected intake, got {refetched['stored_lbs']}"


def test_fefo_earliest_expiration_lot_consumed_first(api):
    """PRD §3.5: "it consumes AVAILABLE lots of the line's food_category in
    ascending order of expiration_date, breaking ties by created_at"
    PRD §3.5: "its reserved_lot_id is set to the single FEFO-earliest lot it
    reserved against (the one consumed first)"

    Design: Difficulty/resource_temporal_overlap/fefo_expiration_window_consumption_ordering
    """
    unit = fixtures.create_cold_storage_unit(temp_zone="REFRIGERATED", capacity_lbs=5000)
    # lot-late created first (exp 2026-08-01), lot-early second (exp 2026-07-01).
    lot_late = fixtures.create_inventory_lot(unit["id"], food_category="PRODUCE",
                                             intake_lbs=100,
                                             expiration_date="2026-08-01T00:00:00.000Z")
    lot_early = fixtures.create_inventory_lot(unit["id"], food_category="PRODUCE",
                                              intake_lbs=100,
                                              expiration_date="2026-07-01T00:00:00.000Z")
    agency = fixtures.create_agency()
    cycle = fixtures.create_open_cycle()
    order = fixtures.submit_order(
        agency["id"], cycle["id"],
        lines=[{"food_category": "PRODUCE", "requested_lbs": 60}])
    api.approve_agency_order(order["id"], {"expected_lot_version": lot_early["version"]}, MGR)

    lines, _ = validate_paginated(api.list_order_lines(order["id"], MGR))
    assert lines[0]["reserved_lot_id"] == lot_early["id"], \
        f"FEFO should reserve against the earliest-expiring lot, got {lines[0]['reserved_lot_id']}"

    early = validate_success(api.get_inventory_lot(lot_early["id"], OP))
    late = validate_success(api.get_inventory_lot(lot_late["id"], OP))
    assert early["remaining_lbs"] == 40.00, \
        f"early lot 100-60=40 remaining, got {early['remaining_lbs']}"
    assert late["remaining_lbs"] == 100.00, \
        f"late lot untouched at 100, got {late['remaining_lbs']}"


def test_cold_storage_capacity_overlap_admits_intake_within_remaining(api):
    """PRD §2.5: "An intake that lands the unit exactly at capacity is permitted;
    only a strict overage is refused."
    PRD §2.5: "the sum of remaining_lbs over every InventoryLot whose
    cold_storage_unit_id points at this unit and whose disposition is either
    AVAILABLE or RESERVED."

    Design: Difficulty/resource_temporal_overlap/cold_storage_capacity_aggregate_occupancy_overlap
    """
    # Two lots total 450 in a 500-unit; a third 50-lb lot fits exactly (450+50==500).
    unit = fixtures.create_cold_storage_unit(temp_zone="REFRIGERATED", capacity_lbs=500)
    fixtures.create_inventory_lot(unit["id"], food_category="PRODUCE",
                                  intake_lbs=250, expiration_date="2026-09-01T00:00:00.000Z")
    fixtures.create_inventory_lot(unit["id"], food_category="DAIRY",
                                  intake_lbs=200, expiration_date="2026-09-01T00:00:00.000Z")
    resp = api.create_inventory_lot(
        factories.create_inventory_lot_payload(
            unit["id"], food_category="PRODUCE", source_type="DONATION",
            intake_lbs=50, expiration_date="2026-09-01T00:00:00.000Z"),
        OP)
    validate_success(resp, expected_status=201)
    refetched = validate_success(api.get_cold_storage_unit(unit["id"], OP))
    assert refetched["stored_lbs"] == 500.00, \
        f"aggregate occupancy reaches exactly 500, got {refetched['stored_lbs']}"
    assert refetched["status"] == "FULL", \
        f"unit at capacity should be FULL, got {refetched['status']}"


def test_fefo_consumes_earlier_lot_then_spills_to_later_lot(api):
    """PRD §3.5: "it consumes AVAILABLE lots of the line's food_category in
    ascending order of expiration_date, breaking ties by created_at, reserving
    poundage until either the line's requested_lbs is met or no matching lot
    remains."
    PRD §3.5: "its reserved_lot_id is set to the single FEFO-earliest lot it
    reserved against (the one consumed first)"

    Design: Difficulty/resource_temporal_overlap/fefo_expiration_window_consumption_ordering
    """
    # Early lot 100 (exp 2026-07-01) drained first, then 50 spills into the late
    # lot 100 (exp 2026-08-01); reserved_lot_id points to the FEFO-earliest lot.
    unit = fixtures.create_cold_storage_unit(temp_zone="REFRIGERATED", capacity_lbs=5000)
    lot_late = fixtures.create_inventory_lot(unit["id"], food_category="PRODUCE",
                                             intake_lbs=100,
                                             expiration_date="2026-08-01T00:00:00.000Z")
    lot_early = fixtures.create_inventory_lot(unit["id"], food_category="PRODUCE",
                                              intake_lbs=100,
                                              expiration_date="2026-07-01T00:00:00.000Z")
    agency = fixtures.create_agency()
    cycle = fixtures.create_open_cycle()
    order = fixtures.submit_order(
        agency["id"], cycle["id"],
        lines=[{"food_category": "PRODUCE", "requested_lbs": 150}])
    api.approve_agency_order(order["id"], {"expected_lot_version": lot_early["version"]}, MGR)

    lines, _ = validate_paginated(api.list_order_lines(order["id"], MGR))
    assert lines[0]["reserved_lot_id"] == lot_early["id"], \
        f"reserved_lot_id points to the FEFO-earliest lot consumed first, got {lines[0]['reserved_lot_id']}"
    early = validate_success(api.get_inventory_lot(lot_early["id"], OP))
    late = validate_success(api.get_inventory_lot(lot_late["id"], OP))
    assert early["remaining_lbs"] == 0.00, \
        f"early lot fully drained (100 used), got {early['remaining_lbs']}"
    assert late["remaining_lbs"] == 50.00, \
        f"later lot supplies the remaining 50 (100-50), got {late['remaining_lbs']}"
