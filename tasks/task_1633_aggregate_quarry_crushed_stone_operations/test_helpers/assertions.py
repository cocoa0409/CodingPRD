"""Entity assertions and domain invariant checkers.

Each assert_<entity>() verifies the system-managed fields plus the declared
field types and enum membership of one resource kind. Domain invariant
checkers verify cross-field rules the PRD pins (e.g. the stockpile
available == on_hand - reserved identity).
"""
import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_quarry_site(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["permitted_acres"] > 0
    assert data["bond_rate_per_acre_usd"] > 0
    assert data["posture"] in ["OPERATING", "RESTRICTED", "SUSPENDED"]
    assert data["bond_adequacy"] in ["ADEQUATE", "DEFICIENT"]
    for f in ("disturbed_acres", "bond_required_usd", "bond_posted_usd"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric"


def assert_bench(data: dict):
    _assert_common(data)
    assert data["status"] in ["PLANNED", "RELEASED", "ON_HOLD", "MINED_OUT",
                              "RECLAMATION_IN_PROGRESS", "RECLAIMED"]
    assert data["acreage"] > 0


def assert_shot_plan(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPROVED", "DRILLING",
                              "DRILLED", "LOADED", "FIRED", "ON_HOLD",
                              "CANCELLED"]
    assert data["hole_count"] >= 1
    assert isinstance(data["estimated_tons"], (int, float))


def assert_muckpile(data: dict):
    _assert_common(data)
    assert data["status"] in ["OPEN", "DEPLETED"]
    for f in ("estimated_tons", "actual_fed_tons", "remaining_tons"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric"


def assert_product_spec(data: dict):
    _assert_common(data)
    assert data["category"] in ["COARSE", "FINE", "RIPRAP"]
    assert data["status"] in ["ACTIVE", "RETIRED"]
    assert data["base_price_per_ton"] > 0
    assert isinstance(data["gradation_bands"], list) and data["gradation_bands"]


def assert_stockpile(data: dict):
    _assert_common(data)
    assert data["status"] in ["OPEN", "QUARANTINED", "CLOSED"]
    for f in ("capacity_tons", "on_hand_tons", "reserved_tons",
              "available_tons"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric"


def assert_gradation_test(data: dict):
    _assert_common(data)
    assert data["result"] in ["PASS", "FAIL"]
    assert data["status"] in ["REPORTED", "CONFIRMED", "VOIDED"]
    assert isinstance(data["sieve_results"], list)


def assert_scale(data: dict):
    _assert_common(data)
    assert data["scale_type"] in ["TRUCK", "BELT"]
    assert data["status"] in ["CERTIFIED", "OUT_OF_SERVICE"]


def assert_scale_calibration(data: dict):
    _assert_common(data)
    assert data["result"] in ["PASS", "FAIL"]
    assert data["status"] in ["RECORDED", "VOIDED"]


def assert_plant_run(data: dict):
    _assert_common(data)
    assert data["circuit_line"] in ["PRIMARY", "SECONDARY"]
    assert data["production_status"] in ["SCHEDULED", "RUNNING", "COMPLETED",
                                         "VOIDED", "CANCELLED"]
    assert data["reconciliation_status"] in ["UNRECONCILED", "RECONCILED",
                                             "DISPUTED"]


def assert_freight_zone(data: dict):
    _assert_common(data)
    assert data["status"] in ["ACTIVE", "INACTIVE"]
    assert data["distance_miles"] > 0


def assert_sales_order(data: dict):
    _assert_common(data)
    assert data["status"] in ["QUOTED", "CONFIRMED", "BACKORDERED",
                              "IN_FULFILLMENT", "COMPLETED", "CANCELLED"]
    assert data["quantity_tons"] > 0
    assert isinstance(data["prices_pinned"], bool)
    for f in ("quoted_material_per_ton", "quoted_freight_per_ton",
              "quoted_surcharge_per_ton", "quoted_unit_delivered_per_ton",
              "quoted_total_usd", "fulfilled_tons"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric"


def assert_scale_ticket(data: dict):
    _assert_common(data)
    assert data["status"] in ["OPEN", "COMPLETED", "VOIDED"]
    assert data["gross_lbs"] > 0


def assert_royalty_agreement(data: dict):
    _assert_common(data)
    assert data["status"] in ["ACTIVE", "SUPERSEDED", "TERMINATED"]
    assert data["base_rate_per_ton"] > 0
    assert data["tier_threshold_tons"] > 0
    assert data["tier_rate_per_ton"] > 0


def assert_royalty_statement(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "ISSUED", "PAID", "VOID"]
    for f in ("tons_sold", "ytd_tons_before", "ytd_tons_after",
              "royalty_due_usd"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric"


def assert_msha_inspection(data: dict):
    _assert_common(data)
    assert data["inspection_type"] in ["REGULAR", "SPOT", "COMPLAINT"]
    assert data["status"] in ["OPEN", "CLOSED"]


def assert_msha_citation(data: dict):
    _assert_common(data)
    assert data["status"] in ["ISSUED", "ABATED", "VACATED"]
    assert isinstance(data["s_and_s"], bool)


def assert_training_record(data: dict):
    _assert_common(data)
    assert data["course_type"] in ["NEW_MINER", "ANNUAL_REFRESHER",
                                   "TASK_TRAINING"]
    assert isinstance(data["is_current"], bool)


def assert_reclamation_bond(data: dict):
    _assert_common(data)
    assert data["status"] in ["POSTED", "PARTIALLY_RELEASED", "FULLY_RELEASED"]
    assert data["amount_usd"] > 0


def assert_truck_queue_entry(data: dict):
    _assert_common(data)
    assert data["priority_class"] in ["CONTRACT", "SPOT", "INTERNAL"]
    assert data["status"] in ["QUEUED", "AT_SCALE_IN", "LOADING",
                              "AT_SCALE_OUT", "EXITED", "NO_SHOW"]
    assert data["certified_tare_lbs"] > 0
    assert data["max_payload_lbs"] > 0


def assert_stockpile_invariants(pile: dict):
    """The PRD's standing identity: available == on_hand - reserved."""
    assert pile["available_tons"] == pytest.approx(
        pile["on_hand_tons"] - pile["reserved_tons"], abs=1e-6), (
        f"available_tons {pile['available_tons']} != on_hand "
        f"{pile['on_hand_tons']} - reserved {pile['reserved_tons']}")
