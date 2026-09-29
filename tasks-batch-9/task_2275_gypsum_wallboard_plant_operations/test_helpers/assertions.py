"""Entity-shape assertions and domain invariant checkers.

The ``assert_{entity}`` helpers check the fields every representation of that
entity must carry (PRD 2.4) plus its declared precision (PRD 2.5).  The
invariant checkers restate the conservation and derivation rules of PRD 2.8 and
2.9 so a test can assert the whole identity in one line.
"""

from __future__ import annotations

from typing import Any, Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    BASE_RATE_BY_ZONE,
    HEMIHYDRATE_FACTOR,
    POSTURE_FROZEN_HELD_RUN_COUNT,
    POSTURE_RESTRICTED_HELD_RUN_COUNT,
    POSTURE_RESTRICTED_STUCCO_TONS,
    RATE_ZONE_BOUNDARIES_MILES,
    SEASONALITY_INDEX_BY_MONTH,
)
from .types import (
    BatchStatus,
    BoardLineStatus,
    LoadOrderStatus,
    LotStatus,
    ProductionPosture,
    QualityState,
    RunStatus,
)

JsonDict = dict[str, Any]


# --------------------------------------------------------------------------- #
# Low-level helpers
# --------------------------------------------------------------------------- #


def assert_decimals(value: Any, places: int, field: str) -> None:
    """A JSON number must be representable at exactly ``places`` decimals."""
    assert isinstance(value, (int, float)), f"{field} must be a JSON number, got {value!r}"
    scaled = round(float(value), places)
    assert abs(float(value) - scaled) < 1e-9, (
        f"{field} carries more than {places} decimal places: {value!r}"
    )


def assert_identity(entity: JsonDict, name: str) -> None:
    assert is_valid_uuid(entity.get("id")), f"{name}.id must be a UUID, got {entity.get('id')!r}"
    assert is_iso8601_timestamp(entity.get("created_at")), (
        f"{name}.created_at must be an ISO-8601 timestamp, got {entity.get('created_at')!r}"
    )


def assert_versioned(entity: JsonDict, name: str) -> None:
    """PRD 2.4: mutable entities carry ``updated_at`` and an integer ``version``."""
    assert_identity(entity, name)
    assert is_iso8601_timestamp(entity.get("updated_at")), (
        f"{name}.updated_at must be an ISO-8601 timestamp, got {entity.get('updated_at')!r}"
    )
    assert isinstance(entity.get("version"), int), f"{name}.version must be an integer"
    assert entity["version"] >= 1, f"{name}.version starts at 1, got {entity['version']}"


def assert_append_only(entity: JsonDict, name: str) -> None:
    """PRD 2.4: append-only rows carry no ``updated_at`` and no ``version``."""
    assert_identity(entity, name)
    assert "updated_at" not in entity, f"{name} is append-only and must not expose updated_at"
    assert "version" not in entity, f"{name} is append-only and must not expose version"


def assert_in_enum(value: Any, enum_cls: Any, field: str) -> None:
    allowed = [member.value for member in enum_cls]
    assert value in allowed, f"{field} must be one of {allowed}, got {value!r}"


# --------------------------------------------------------------------------- #
# Per-entity assertions
# --------------------------------------------------------------------------- #


def assert_plant(plant: JsonDict) -> None:
    assert_versioned(plant, "Plant")
    assert isinstance(plant.get("code"), str) and 1 <= len(plant["code"]) <= 16
    assert isinstance(plant.get("name"), str) and plant["name"]
    assert plant["calciner_capacity_tph"] > 0
    assert plant["stucco_silo_capacity_tons"] > 0
    assert 50.0 <= plant["natural_gypsum_purity_floor_pct"] <= 100.0
    assert 0.0 <= plant["synthetic_free_moisture_ceiling_pct"] <= 30.0
    assert plant["energy_price_per_mmbtu"] > 0
    assert plant["contribution_margin_per_msf"] >= 0
    for field in ("stucco_on_hand_tons", "stucco_committed_tons", "stucco_available_tons"):
        assert_decimals(plant[field], 3, f"Plant.{field}")
    assert isinstance(plant.get("held_run_count"), int) and plant["held_run_count"] >= 0
    assert_in_enum(plant.get("production_posture"), ProductionPosture, "Plant.production_posture")
    assert_silo_identity(plant)
    assert_posture_derivation(plant)


def assert_board_line(line: JsonDict) -> None:
    assert_versioned(line, "BoardLine")
    assert is_valid_uuid(line.get("plant_id")), "BoardLine.plant_id must be a UUID"
    assert isinstance(line.get("designation"), str) and line["designation"]
    assert 100 <= line["max_speed_fpm"] <= 1200
    assert line["web_width_in"] > 0
    assert_in_enum(line.get("status"), BoardLineStatus, "BoardLine.status")


def assert_product_spec(spec: JsonDict) -> None:
    assert_versioned(spec, "ProductSpec")
    assert is_valid_uuid(spec.get("plant_id")), "ProductSpec.plant_id must be a UUID"
    assert spec["thickness_in"] in (0.375, 0.5, 0.625), (
        f"ProductSpec.thickness_in must be one of 0.375, 0.5, 0.625, got {spec['thickness_in']}"
    )
    fire_rated_types = ("TYPE_X", "TYPE_C")
    assert spec["fire_rated"] is (spec["board_type"] in fire_rated_types), (
        "ProductSpec.fire_rated must be true exactly for TYPE_X and TYPE_C"
    )
    assert 0.30 <= spec["slurry_water_stucco_ratio"] <= 1.20
    assert 100 <= spec["line_speed_max_fpm"] <= 1200
    assert spec["paper_tension_max_lb"] > spec["paper_tension_min_lb"]
    assert spec["max_boards_per_bundle"] % 2 == 0, (
        "ProductSpec.max_boards_per_bundle must be even"
    )
    assert 2 <= spec["max_boards_per_bundle"] <= 80


def assert_market(market: JsonDict) -> None:
    assert_versioned(market, "Market")
    assert market["distance_miles"] > 0
    assert 0.0 <= market["fuel_surcharge_pct"] <= 60.0
    assert market["min_charge_usd"] >= 0
    assert market["backhaul_credit_usd"] >= 0
    assert_decimals(market["min_charge_usd"], 2, "Market.min_charge_usd")
    assert_decimals(market["backhaul_credit_usd"], 2, "Market.backhaul_credit_usd")
    assert_rate_zone(market)


def assert_gypsum_lot(lot: JsonDict) -> None:
    assert_versioned(lot, "GypsumLot")
    assert is_valid_uuid(lot.get("plant_id")), "GypsumLot.plant_id must be a UUID"
    assert_in_enum(lot.get("status"), LotStatus, "GypsumLot.status")
    for field in ("received_tons", "consumed_tons", "remaining_tons"):
        assert_decimals(lot[field], 3, f"GypsumLot.{field}")
    assert isinstance(lot.get("assay_count"), int) and 0 <= lot["assay_count"] <= 3
    assert_lot_mass_conservation(lot)


def assert_calciner_batch(batch: JsonDict) -> None:
    assert_versioned(batch, "CalcinerBatch")
    assert is_valid_uuid(batch.get("plant_id")), "CalcinerBatch.plant_id must be a UUID"
    assert_in_enum(batch.get("status"), BatchStatus, "CalcinerBatch.status")
    assert batch["target_stucco_tons"] > 0
    assert 250.0 <= batch["calcination_temp_f"] <= 400.0
    assert batch["feed_rate_tph"] > 0
    for field in ("feed_tons_total", "stucco_yield_plan_tons", "stucco_yield_actual_tons"):
        assert_decimals(batch[field], 3, f"CalcinerBatch.{field}")
    for field in ("feed_moisture_plan_pct", "feed_moisture_as_fed_pct", "feed_purity_plan_pct"):
        if batch.get(field) is not None:
            assert_decimals(batch[field], 2, f"CalcinerBatch.{field}")


def assert_batch_feed(feed: JsonDict) -> None:
    assert_append_only(feed, "BatchFeed")
    assert is_valid_uuid(feed.get("batch_id")), "BatchFeed.batch_id must be a UUID"
    assert is_valid_uuid(feed.get("lot_id")), "BatchFeed.lot_id must be a UUID"
    assert isinstance(feed.get("feed_seq"), int) and feed["feed_seq"] >= 1
    assert_decimals(feed["tons_fed"], 3, "BatchFeed.tons_fed")
    assert_decimals(feed["dry_tons_plan"], 6, "BatchFeed.dry_tons_plan")
    assert_decimals(feed["dry_tons_as_fed"], 6, "BatchFeed.dry_tons_as_fed")
    assert_decimals(feed["assay_free_moisture_pct"], 2, "BatchFeed.assay_free_moisture_pct")
    assert_decimals(feed["measured_free_moisture_pct"], 2, "BatchFeed.measured_free_moisture_pct")


def assert_stucco_test(test: JsonDict) -> None:
    assert_append_only(test, "StuccoTest")
    assert is_valid_uuid(test.get("batch_id")), "StuccoTest.batch_id must be a UUID"
    assert isinstance(test.get("sample_seq"), int) and test["sample_seq"] >= 1
    assert test["result"] in ("PASS", "MARGINAL", "FAIL")
    assert isinstance(test.get("recorded_by_user_id"), str) and test["recorded_by_user_id"]
    assert is_iso8601_timestamp(test.get("tested_at")), "StuccoTest.tested_at must be ISO-8601"


def assert_production_run(run: JsonDict) -> None:
    assert_versioned(run, "ProductionRun")
    for ref in ("plant_id", "line_id", "product_spec_id", "calciner_batch_id"):
        assert is_valid_uuid(run.get(ref)), f"ProductionRun.{ref} must be a UUID"
    assert_in_enum(run.get("status"), RunStatus, "ProductionRun.status")
    assert_in_enum(run.get("quality_state"), QualityState, "ProductionRun.quality_state")
    for field in (
        "requested_planned_msf",
        "effective_planned_msf",
        "actual_msf",
        "scrap_msf",
        "net_good_msf",
        "scrapped_msf",
        "available_msf",
        "stucco_reserved_tons",
        "stucco_consumed_tons",
    ):
        assert_decimals(run[field], 3, f"ProductionRun.{field}")
    if run.get("kiln_energy_mmbtu") is not None:
        assert_decimals(run["kiln_energy_mmbtu"], 3, "ProductionRun.kiln_energy_mmbtu")
    if run.get("kiln_energy_cost_usd") is not None:
        assert_decimals(run["kiln_energy_cost_usd"], 2, "ProductionRun.kiln_energy_cost_usd")
    if run.get("capacity_msf") is not None:
        assert_decimals(run["capacity_msf"], 3, "ProductionRun.capacity_msf")
    assert_decimals(run["fail_rate"], 4, "ProductionRun.fail_rate")
    assert isinstance(run.get("specimen_count"), int)
    assert isinstance(run.get("failing_specimen_count"), int)
    assert isinstance(run.get("retest_count"), int)


def assert_board_test(test: JsonDict) -> None:
    assert_append_only(test, "BoardTest")
    assert is_valid_uuid(test.get("run_id")), "BoardTest.run_id must be a UUID"
    assert isinstance(test.get("specimen_seq"), int) and test["specimen_seq"] >= 1
    assert test["result"] in ("PASS", "FAIL")
    assert isinstance(test.get("failing_attributes"), list)
    if test["result"] == "PASS":
        assert test["failing_attributes"] == [], (
            "a passing specimen must have an empty failing_attributes list"
        )
    else:
        assert test["failing_attributes"], "a failing specimen must list its failing attributes"
    assert isinstance(test.get("recorded_by_user_id"), str) and test["recorded_by_user_id"]
    assert is_iso8601_timestamp(test.get("tested_at")), "BoardTest.tested_at must be ISO-8601"


def assert_maintenance_outage(outage: JsonDict) -> None:
    assert_versioned(outage, "MaintenanceOutage")
    assert is_valid_uuid(outage.get("line_id")), "MaintenanceOutage.line_id must be a UUID"
    assert outage["outage_type"] in ("PLANNED", "EMERGENCY")
    assert outage["status"] in ("PROPOSED", "APPROVED", "DEFERRED", "IN_PROGRESS", "CLOSED")
    assert isinstance(outage.get("proposed_by_user_id"), str) and outage["proposed_by_user_id"]
    assert isinstance(outage.get("deferral_count"), int) and 0 <= outage["deferral_count"] <= 2
    assert_decimals(outage["seasonality_index"], 2, "MaintenanceOutage.seasonality_index")
    assert_decimals(outage["planned_downtime_hours"], 2, "MaintenanceOutage.planned_downtime_hours")
    assert_decimals(outage["at_risk_msf"], 3, "MaintenanceOutage.at_risk_msf")
    assert_decimals(outage["opportunity_cost_usd"], 2, "MaintenanceOutage.opportunity_cost_usd")
    assert_seasonality_index(outage)


def assert_load_order(load: JsonDict) -> None:
    assert_versioned(load, "LoadOrder")
    assert is_valid_uuid(load.get("run_id")), "LoadOrder.run_id must be a UUID"
    assert is_valid_uuid(load.get("market_id")), "LoadOrder.market_id must be a UUID"
    assert_in_enum(load.get("status"), LoadOrderStatus, "LoadOrder.status")
    assert load["bundles_count"] >= 1
    assert load["boards_per_bundle"] % 2 == 0, "LoadOrder.boards_per_bundle must be even"
    assert_decimals(load["board_msf_each"], 6, "LoadOrder.board_msf_each")
    assert_decimals(load["bundle_msf"], 4, "LoadOrder.bundle_msf")
    assert_decimals(load["bundle_weight_lb"], 2, "LoadOrder.bundle_weight_lb")
    assert_decimals(load["total_msf"], 3, "LoadOrder.total_msf")
    assert_decimals(load["trailer_weight_lb"], 2, "LoadOrder.trailer_weight_lb")
    assert_decimals(load["quoted_freight_usd"], 2, "LoadOrder.quoted_freight_usd")
    if load.get("settled_freight_usd") is not None:
        assert_decimals(load["settled_freight_usd"], 2, "LoadOrder.settled_freight_usd")
    if load.get("freight_variance_usd") is not None:
        assert_decimals(load["freight_variance_usd"], 2, "LoadOrder.freight_variance_usd")
    assert isinstance(load.get("backhaul"), bool), "LoadOrder.backhaul must be a boolean"
    assert_bundle_geometry(load)


# --------------------------------------------------------------------------- #
# Domain invariants
# --------------------------------------------------------------------------- #


def assert_silo_identity(plant: JsonDict) -> None:
    """PRD 2.8: available tonnage is on-hand less committed."""
    expected = round(plant["stucco_on_hand_tons"] - plant["stucco_committed_tons"], 3)
    assert plant["stucco_available_tons"] == pytest.approx(expected, abs=0.0005), (
        "stucco_available_tons must equal stucco_on_hand_tons minus stucco_committed_tons: "
        f"{plant['stucco_available_tons']} != {plant['stucco_on_hand_tons']} - "
        f"{plant['stucco_committed_tons']}"
    )


def assert_posture_derivation(plant: JsonDict) -> None:
    """PRD 2.9: posture follows held runs and available tonnage, inclusive then strict.

    An emergency outage in progress also forces ``FROZEN``, which this checker
    cannot see from the plant alone, so a plant reporting ``FROZEN`` with no held
    runs is accepted.
    """
    held = plant["held_run_count"]
    available = plant["stucco_available_tons"]
    posture = plant["production_posture"]
    if held >= POSTURE_FROZEN_HELD_RUN_COUNT:
        assert posture == ProductionPosture.FROZEN.value, (
            f"held_run_count {held} must freeze the plant, got {posture}"
        )
        return
    if posture == ProductionPosture.FROZEN.value:
        return  # an emergency outage in progress; not derivable from the plant alone
    if held >= POSTURE_RESTRICTED_HELD_RUN_COUNT or available < POSTURE_RESTRICTED_STUCCO_TONS:
        assert posture == ProductionPosture.RESTRICTED.value, (
            f"held_run_count {held} with {available} available tons must be RESTRICTED, "
            f"got {posture}"
        )
    else:
        assert posture == ProductionPosture.OPEN.value, (
            f"no held runs and {available} available tons must be OPEN, got {posture}"
        )


def assert_lot_mass_conservation(lot: JsonDict) -> None:
    """PRD 2.8: received tonnage equals consumed plus remaining, except once rejected."""
    if lot["status"] == LotStatus.REJECTED.value:
        return  # rejection zeroes remaining_tons without unwinding received_tons
    expected = round(lot["received_tons"] - lot["consumed_tons"], 3)
    assert lot["remaining_tons"] == pytest.approx(expected, abs=0.0005), (
        "remaining_tons must equal received_tons minus consumed_tons: "
        f"{lot['remaining_tons']} != {lot['received_tons']} - {lot['consumed_tons']}"
    )


def assert_run_msf_conservation(run: JsonDict, committed_load_msf: float) -> None:
    """PRD 2.8: available MSF is net good less the volume held by live loads."""
    expected = round(run["net_good_msf"] - committed_load_msf, 3)
    assert run["available_msf"] == pytest.approx(expected, abs=0.0005), (
        "available_msf must equal net_good_msf less the total_msf of every STAGED, HELD, "
        f"LOADED or SHIPPED load: {run['available_msf']} != {run['net_good_msf']} - "
        f"{committed_load_msf}"
    )


def assert_rate_zone(market: JsonDict) -> None:
    """PRD 3.1: zone and base rate are derived from ``distance_miles``."""
    miles = market["distance_miles"]
    low, mid, high = RATE_ZONE_BOUNDARIES_MILES
    if miles < low:
        expected_zone = "ZONE_1"
    elif miles < mid:
        expected_zone = "ZONE_2"
    elif miles < high:
        expected_zone = "ZONE_3"
    else:
        expected_zone = "ZONE_4"
    assert market["rate_zone"] == expected_zone, (
        f"{miles} miles must derive {expected_zone}, got {market['rate_zone']}"
    )
    assert market["base_rate_per_msf"] == pytest.approx(
        BASE_RATE_BY_ZONE[expected_zone], abs=0.005
    ), (
        f"{expected_zone} bills {BASE_RATE_BY_ZONE[expected_zone]} per MSF, "
        f"got {market['base_rate_per_msf']}"
    )


def assert_seasonality_index(outage: JsonDict) -> None:
    """PRD 3.9: the index is looked up from the month of ``window_start``."""
    month = int(outage["window_start"][5:7])
    expected = SEASONALITY_INDEX_BY_MONTH[month]
    assert outage["seasonality_index"] == pytest.approx(expected, abs=0.005), (
        f"window_start month {month} maps to seasonality_index {expected}, "
        f"got {outage['seasonality_index']}"
    )


def assert_bundle_geometry(load: JsonDict) -> None:
    """PRD 3.8: bundle MSF is the per-board area times the boards in a bundle."""
    expected_bundle = round(load["boards_per_bundle"] * load["board_msf_each"], 4)
    assert load["bundle_msf"] == pytest.approx(expected_bundle, abs=0.00005), (
        "bundle_msf must be boards_per_bundle times board_msf_each: "
        f"{load['bundle_msf']} != {expected_bundle}"
    )
    billable = (
        load["loaded_bundles_count"]
        if load.get("loaded_bundles_count") is not None
        else load["bundles_count"]
    )
    expected_total = round(billable * load["bundle_msf"], 3)
    assert load["total_msf"] == pytest.approx(expected_total, abs=0.0005), (
        f"total_msf must be the billable bundle count ({billable}) times bundle_msf: "
        f"{load['total_msf']} != {expected_total}"
    )
    expected_weight = round(billable * load["bundle_weight_lb"], 2)
    assert load["trailer_weight_lb"] == pytest.approx(expected_weight, abs=0.005), (
        f"trailer_weight_lb must be the billable bundle count ({billable}) times "
        f"bundle_weight_lb: {load['trailer_weight_lb']} != {expected_weight}"
    )


def assert_board_msf_each(load: JsonDict, length_ft: float, width_in: float) -> None:
    """PRD 3.8: per-board area at six decimals."""
    expected = round(length_ft * width_in / 12 / 1000, 6)
    assert load["board_msf_each"] == pytest.approx(expected, abs=0.0000005), (
        f"board_msf_each must be {length_ft} ft times {width_in} in over 12000: "
        f"{load['board_msf_each']} != {expected}"
    )


def expected_stucco_yield(
    feeds: list[tuple[float, float, float]],
) -> float:
    """PRD 3.3: sum of per-feed contributions, rounded once at the end.

    ``feeds`` is a list of ``(tons_fed, moisture_pct, purity_pct)`` triples; the
    caller chooses which moisture basis to pass, which is what makes the planned
    and actual variants diverge.
    """
    total = 0.0
    for tons_fed, moisture_pct, purity_pct in feeds:
        dry = tons_fed * (1 - moisture_pct / 100)
        gypsum = dry * purity_pct / 100
        inert = dry - gypsum
        total += gypsum * HEMIHYDRATE_FACTOR + inert
    return round(total, 3)


def expected_required_paper_tension(
    paper_tension_min_lb: float, line_speed_fpm: int
) -> float:
    """PRD 3.5: the minimum plus 0.06 lb for every fpm above the 250 pivot."""
    return round(paper_tension_min_lb + (line_speed_fpm - 250) * 0.06, 2)


def assert_error_body(body: JsonDict) -> None:
    """PRD 2.2: an error carries ``error_id`` and ``message`` and no entity payload."""
    assert "error_id" in body and "message" in body, (
        f"an error body must carry error_id and message, got {sorted(body)}"
    )
    assert "id" not in body, "an error body must not carry an entity id"


def assert_no_run_side_effects(run: JsonDict, expected_status: str) -> None:
    """A rejected schedule must leave the run in place with nothing reserved."""
    assert run["status"] == expected_status, (
        f"run status must stay {expected_status}, got {run['status']}"
    )
    assert run["stucco_reserved_tons"] in (0, 0.0), (
        f"a run that never scheduled must reserve nothing, got {run['stucco_reserved_tons']}"
    )


def find_by(items: list[JsonDict], **criteria: Any) -> Optional[JsonDict]:
    """First item in a listing matching every keyword criterion."""
    for item in items:
        if all(item.get(key) == value for key, value in criteria.items()):
            return item
    return None
