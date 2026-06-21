"""Calculation corners: allergen inheritance / controlling allergen, FEFO rotation
gate, zone touching-endpoint acceptance, and invalid-interval rejection.

Queue B — Corner/calculations.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_facility, create_supplier, create_ingredient, create_allergen_profile,
    receive_lot, release_lot, open_run, add_consumed_lot, finalize_run,
    current_run_version, create_zone, create_booking,
    create_booking_payload, finalize_payload, ApiErrorId,
    TEST_USERS,
)

QM = TEST_USERS["quality_manager_headers"]
OP = TEST_USERS["production_operator_headers"]


def test_allergen_inheritance_union_and_controlling():
    """PRD 3.4: "The finished lot's `effective_allergen_codes` is the distinct union of
    the output ingredient's `declared_allergen_codes` and the `effective_allergen_codes`
    of every source lot; its `controlling_allergen_code` is then the code in that union
    of highest `severity_rank`, breaking ties by the lexicographically smallest code,
    and is null when the union is empty."

    Design: Corner/calculations/allergen_inheritance_union_and_controlling
    """
    facility = create_facility(initial_utc="2026-01-01T00:00:00Z")
    create_allergen_profile(facility["id"], "PEANUT", 5)
    create_allergen_profile(facility["id"], "WHEAT", 2)
    supplier = create_supplier(facility["id"], coa_required=False)
    ing_peanut = create_ingredient(facility["id"], name="PeanutPaste", storage_target_c=20,
                                   storage_tolerance_c=5, shelf_life_days=365,
                                   declared_allergen_codes=["PEANUT"])
    ing_cookie = create_ingredient(facility["id"], name="Cookie", storage_target_c=20,
                                   storage_tolerance_c=5, shelf_life_days=200,
                                   declared_allergen_codes=["WHEAT"])
    lotP = receive_lot(facility["id"], ing_peanut["id"], "P1", supplier_id=supplier["id"],
                       received_qty=50)
    release_lot(lotP["id"])
    run = open_run(facility["id"], ing_cookie["id"], planned_output_qty=20)
    add_consumed_lot(run["id"], lotP["id"], 10)
    finalized = finalize_run(run["id"], current_run_version(run["id"]))

    fin_lot = validate_success(api_client.get_lot(finalized["output_lot_id"], QM), 200)
    # union {PEANUT, WHEAT}; PEANUT severity 5 beats WHEAT severity 2.
    assert fin_lot["controlling_allergen_code"] == "PEANUT"


def test_fefo_blocks_consuming_later_expiring_lot():
    """PRD 3.4: "a source lot may be consumed only if no other released, free,
    same-ingredient, same-facility lot has an earlier `effective_expiration_date`;
    bypassing an earlier-expiring lot is rejected with `ERR_FEFO_VIOLATION`."

    Design: Corner/calculations/fefo_blocks_consuming_later_expiring_lot
    """
    facility = create_facility(initial_utc="2026-01-01T00:00:00Z")
    supplier = create_supplier(facility["id"], coa_required=False)
    ingredient = create_ingredient(facility["id"], storage_target_c=4,
                                   storage_tolerance_c=2, shelf_life_days=10,
                                   declared_allergen_codes=[])
    lotA = receive_lot(facility["id"], ingredient["id"], "A", supplier_id=supplier["id"],
                       received_qty=50)   # effective_expiration 2026-01-11
    lotB = receive_lot(facility["id"], ingredient["id"], "B", supplier_id=supplier["id"],
                       received_qty=50, expiration_date="2026-01-06T00:00:00Z")  # earlier
    release_lot(lotA["id"])
    release_lot(lotB["id"])
    run = open_run(facility["id"], ingredient["id"], planned_output_qty=10)
    add_consumed_lot(run["id"], lotA["id"], 10)   # consuming A bypasses earlier-expiring B
    run_v = current_run_version(run["id"])
    res = api_client.finalize_production_run(run["id"], finalize_payload(run_v), OP)
    validate_error(res, ApiErrorId.ERR_FEFO_VIOLATION.value)


def test_zone_booking_touching_endpoints_no_overlap():
    """PRD 3.8: "two bookings that merely touch at an endpoint — where one ends exactly
    when the other begins — do not overlap."

    Design: Corner/calculations/zone_booking_touching_endpoints_no_overlap
    """
    facility = create_facility(initial_utc="2026-01-01T00:00:00Z")
    supplier = create_supplier(facility["id"], coa_required=False)
    ingredient = create_ingredient(facility["id"], storage_target_c=2, shelf_life_days=30)
    zone = create_zone(facility["id"], "Z1", 100, target_temp_c=2)
    l1 = receive_lot(facility["id"], ingredient["id"], "L1", supplier_id=supplier["id"],
                     received_qty=5)
    l2 = receive_lot(facility["id"], ingredient["id"], "L2", supplier_id=supplier["id"],
                     received_qty=5)
    create_booking(zone["id"], l1["id"], "2026-01-01T00:00:00Z", "2026-01-01T06:00:00Z", 70)
    # B=70 over [06:00,12:00) touches A's end; 70+70 never coexist -> 201.
    booking = validate_success(
        api_client.create_booking(
            zone["id"], create_booking_payload(l2["id"], "2026-01-01T06:00:00Z",
                                               "2026-01-01T12:00:00Z", 70), QM), 201)
    assert booking["capacity_units"] == 70


def test_zone_booking_invalid_interval_rejected():
    """PRD 3.8: "The interval must be valid — `end_utc` strictly greater than
    `start_utc` — otherwise `ERR_INVALID_INTERVAL`."

    Design: Corner/calculations/zone_booking_invalid_interval_rejected
    """
    facility = create_facility(initial_utc="2026-01-01T00:00:00Z")
    supplier = create_supplier(facility["id"], coa_required=False)
    ingredient = create_ingredient(facility["id"], storage_target_c=2, shelf_life_days=30)
    zone = create_zone(facility["id"], "Z1", 100, target_temp_c=2)
    l1 = receive_lot(facility["id"], ingredient["id"], "L1", supplier_id=supplier["id"],
                     received_qty=5)
    # end_utc == start_utc -> not strictly greater.
    res = api_client.create_booking(
        zone["id"], create_booking_payload(l1["id"], "2026-01-01T06:00:00Z",
                                           "2026-01-01T06:00:00Z", 10), QM)
    validate_error(res, ApiErrorId.ERR_INVALID_INTERVAL.value)
