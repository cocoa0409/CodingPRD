"""Optimistic-concurrency on lot dispose, derived-field reconciliation on the
agency ledger, immediate consistency of the approve response, and occupancy
input-set filtering after depletion.

Covers Corner queue sections cross_cutting_complexity_layers, consistency_model,
and the occupancy-filtering entry of section calculations.
"""
from prd_bench_local_runner.testing import validate_success, validate_error
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS, fixtures, make_agency_coordinator_headers,
)

MGR = TEST_USERS["allocation_manager_headers"]
OP = TEST_USERS["food_bank_operator_headers"]


def test_dispose_stale_lot_version_rejected(api):
    """PRD §2.7: "when a FoodBankOperator disposes of a lot, the dispose request
    must carry expected_lot_version matching the lot's current version; if a
    shelf-life sweep has meanwhile transitioned the lot from AVAILABLE to EXPIRED
    and bumped its version, the stale dispose is rejected with ERR_STALE_LOT_VERSION
    (HTTP 412)"

    Design: Corner/cross_cutting_complexity_layers/occ_stale_lot_version_on_dispose
    """
    api.set_clock("2026-06-01T00:00:00.000Z", OP)
    unit = fixtures.create_cold_storage_unit(temp_zone="REFRIGERATED", capacity_lbs=5000)
    lot = fixtures.create_inventory_lot(unit["id"], food_category="PRODUCE",
                                        intake_lbs=100,
                                        expiration_date="2026-06-15T00:00:00.000Z")
    stale_version = lot["version"]
    # clock advance expires the lot and bumps its version.
    api.set_clock("2026-06-20T00:00:00.000Z", OP)
    resp = api.dispose_inventory_lot(lot["id"], {"expected_lot_version": stale_version}, OP)
    validate_error(resp, ApiErrorId.ERR_STALE_LOT_VERSION.value)
    refetched = validate_success(api.get_inventory_lot(lot["id"], OP))
    assert refetched["disposition"] == "EXPIRED", \
        f"lot is EXPIRED (still disposable with current version), got {refetched['disposition']}"


def test_dispose_correct_lot_version_succeeds(api):
    """PRD §3.1: "Either way the lot moves to DISPOSED, its remaining_lbs is set to
    0, the holding unit's stored_lbs is recomputed, and its version is bumped."
    PRD §2.7: "the dispose request must carry expected_lot_version matching the
    lot's current version"

    Design: Corner/cross_cutting_complexity_layers/occ_correct_lot_version_on_dispose_succeeds
    """
    unit = fixtures.create_cold_storage_unit(temp_zone="REFRIGERATED", capacity_lbs=5000)
    lot = fixtures.create_inventory_lot(unit["id"], food_category="PRODUCE",
                                        intake_lbs=100,
                                        expiration_date="2026-09-01T00:00:00.000Z")
    disposed = validate_success(api.dispose_inventory_lot(
        lot["id"], {"expected_lot_version": lot["version"]}, OP))
    assert disposed["disposition"] == "DISPOSED", \
        f"AVAILABLE lot disposes to DISPOSED, got {disposed['disposition']}"
    assert disposed["version"] == 2, f"version bumps to 2, got {disposed['version']}"
    assert disposed["remaining_lbs"] == 0.00, \
        f"remaining_lbs set to 0 on dispose, got {disposed['remaining_lbs']}"


def test_lifetime_distributed_reconciles_after_finalize(api):
    """PRD §3.2: "Each agency also carries a computed lifetime_distributed_lbs, the
    running sum of poundage actually handed out across all of its finalized
    distribution events, initialized to 0."
    PRD §3.7: "increases the receiving agency's lifetime_distributed_lbs by the
    actual_distributed_lbs"

    Design: Corner/cross_cutting_complexity_layers/derived_lifetime_distributed_reconciles_after_finalize
    """
    ctx = fixtures.setup_packed_event(requested_lbs=200, intake_lbs=300)
    agency_id = ctx["agency"]["id"]
    before = validate_success(api.get_agency(agency_id, MGR))
    assert before["lifetime_distributed_lbs"] == 0.00, \
        f"ledger starts at 0 before finalize, got {before['lifetime_distributed_lbs']}"
    validate_success(api.finalize_distribution_event(
        ctx["event"]["id"], {"actual_distributed_lbs": 150},
        make_agency_coordinator_headers(agency_id)))
    after = validate_success(api.get_agency(agency_id, MGR))
    assert after["lifetime_distributed_lbs"] == 150.00, \
        f"ledger equals finalized 150 after, got {after['lifetime_distributed_lbs']}"


def test_approve_response_reflects_reservation_immediately(api):
    """PRD §3.5: "The order's approved_lbs is set to the sum of its lines'
    reserved_lbs, the order moves from SUBMITTED to APPROVED, and the order's
    version is bumped."

    Design: Corner/consistency_model/approve_response_reflects_reservation_immediately
    """
    unit = fixtures.create_cold_storage_unit(temp_zone="REFRIGERATED", capacity_lbs=5000)
    lot = fixtures.create_inventory_lot(unit["id"], food_category="PRODUCE",
                                        intake_lbs=500,
                                        expiration_date="2026-07-01T00:00:00.000Z")
    agency = fixtures.create_agency()
    cycle = fixtures.create_open_cycle()
    order = fixtures.submit_order(
        agency["id"], cycle["id"],
        lines=[{"food_category": "PRODUCE", "requested_lbs": 250}])
    approved = validate_success(api.approve_agency_order(
        order["id"], {"expected_lot_version": lot["version"]}, MGR))
    assert approved["status"] == "APPROVED", \
        f"status APPROVED in the approve response, got {approved['status']}"
    assert approved["approved_lbs"] == 250.00, \
        f"approved_lbs 250 in same response, got {approved['approved_lbs']}"


def test_cold_storage_occupancy_excludes_depleted_lots(api):
    """PRD §2.5: "Lots that have become DEPLETED, EXPIRED, or DISPOSED leave the
    occupancy count entirely."
    PRD §2.5: "Its stored_lbs is a computed running total: the sum of remaining_lbs
    over every InventoryLot whose cold_storage_unit_id points at this unit and
    whose disposition is either AVAILABLE or RESERVED."

    Design: Corner/calculations/cold_storage_occupancy_excludes_depleted_lots
    """
    # 100-lb lot fully reserved then finalized -> DEPLETED -> leaves occupancy.
    ctx = fixtures.setup_finalized_event(requested_lbs=100, intake_lbs=100,
                                         actual_distributed_lbs=100)
    unit = validate_success(api.get_cold_storage_unit(ctx["unit"]["id"], OP))
    assert unit["stored_lbs"] == 0.00, \
        f"DEPLETED lot excluded from occupancy, stored_lbs should be 0, got {unit['stored_lbs']}"
    lot = validate_success(api.get_inventory_lot(ctx["lot"]["id"], OP))
    assert lot["disposition"] == "DEPLETED", \
        f"fully-distributed lot should be DEPLETED, got {lot['disposition']}"
