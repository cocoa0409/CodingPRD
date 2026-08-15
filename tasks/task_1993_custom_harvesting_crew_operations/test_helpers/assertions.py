"""Entity assertions and domain invariant checkers."""
from typing import Any, Dict

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: Dict[str, Any], label: str = "resource"):
    """id / created_at / updated_at / version — the common set every resource carries."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer >= 1, got {data.get('version')!r}"
    )


def _assert_number(value: Any, label: str):
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be numeric, got {value!r}"
    )


def _assert_int(value: Any, label: str):
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer, got {value!r}"
    )


def assert_harvest_season(data: Dict[str, Any]):
    assert_common_fields(data, "HarvestSeason")
    _assert_int(data.get("season_year"), "HarvestSeason.season_year")
    _assert_int(data.get("diesel_baseline_per_gallon_cents"), "HarvestSeason.diesel_baseline_per_gallon_cents")
    _assert_int(data.get("current_diesel_per_gallon_cents"), "HarvestSeason.current_diesel_per_gallon_cents")
    _assert_number(data.get("committed_acres_total"), "HarvestSeason.committed_acres_total")
    _assert_number(data.get("harvested_acres_total"), "HarvestSeason.harvested_acres_total")
    assert data.get("status") in ("DRAFT", "ACTIVE", "SETTLING", "CLOSED"), (
        f"HarvestSeason.status unexpected: {data.get('status')!r}"
    )


def assert_customer_contract(data: Dict[str, Any]):
    assert_common_fields(data, "CustomerContract")
    assert isinstance(data.get("season_id"), str)
    assert isinstance(data.get("grower_name"), str) and data["grower_name"]
    assert data.get("crop") in ("WHEAT", "CORN", "SOYBEAN", "SORGHUM")
    assert data.get("rate_basis") in ("PER_ACRE", "PER_BUSHEL")
    _assert_int(data.get("rate_cents_per_acre"), "CustomerContract.rate_cents_per_acre")
    _assert_int(data.get("rate_cents_per_bushel"), "CustomerContract.rate_cents_per_bushel")
    _assert_number(data.get("committed_acres"), "CustomerContract.committed_acres")
    _assert_number(data.get("harvested_acres"), "CustomerContract.harvested_acres")
    _assert_int(data.get("moisture_discount_total_cents"), "CustomerContract.moisture_discount_total_cents")
    assert data.get("status") in (
        "DRAFT", "COMMITTED", "IN_PROGRESS", "HARVESTED", "SETTLED", "CANCELLED"
    ), f"CustomerContract.status unexpected: {data.get('status')!r}"


def assert_route_stop(data: Dict[str, Any]):
    assert_common_fields(data, "RouteStop")
    assert isinstance(data.get("contract_id"), str)
    assert isinstance(data.get("season_id"), str)
    assert isinstance(data.get("planned_start_date"), str)
    assert isinstance(data.get("planned_end_date"), str)
    _assert_number(data.get("planned_acres"), "RouteStop.planned_acres")
    _assert_number(data.get("actual_acres"), "RouteStop.actual_acres")
    _assert_int(data.get("sequence_index"), "RouteStop.sequence_index")
    assert data.get("status") in (
        "SCHEDULED", "EN_ROUTE", "CUTTING", "PAUSED_WEATHER", "COMPLETED", "SKIPPED"
    ), f"RouteStop.status unexpected: {data.get('status')!r}"


def assert_machine(data: Dict[str, Any]):
    assert_common_fields(data, "Machine")
    assert isinstance(data.get("season_id"), str)
    assert data.get("machine_kind") in ("COMBINE", "GRAIN_CART", "TRUCK")
    assert isinstance(data.get("label"), str) and data["label"]
    _assert_number(data.get("daily_capacity_acres"), "Machine.daily_capacity_acres")
    assert data.get("status") in (
        "AVAILABLE", "ASSIGNED", "IN_FIELD", "DOWN", "REPAIRING", "RETIRED"
    ), f"Machine.status unexpected: {data.get('status')!r}"


def assert_crew_member(data: Dict[str, Any]):
    assert_common_fields(data, "CrewMember")
    assert isinstance(data.get("season_id"), str)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert data.get("visa_type") in ("US_CITIZEN", "H2A", "TN", "PERMANENT_RESIDENT")
    _assert_int(data.get("hourly_rate_cents"), "CrewMember.hourly_rate_cents")
    assert isinstance(data.get("requires_housing"), bool)
    assert data.get("status") in ("ONBOARDED", "ACTIVE", "RELEASED"), (
        f"CrewMember.status unexpected: {data.get('status')!r}"
    )


def assert_machine_assignment(data: Dict[str, Any]):
    assert_common_fields(data, "MachineAssignment")
    assert isinstance(data.get("route_stop_id"), str)
    assert isinstance(data.get("machine_id"), str)
    assert isinstance(data.get("assigned_start_date"), str)
    assert isinstance(data.get("assigned_end_date"), str)
    assert data.get("status") in ("RESERVED", "DEPLOYED", "RELEASED", "CANCELLED"), (
        f"MachineAssignment.status unexpected: {data.get('status')!r}"
    )


def assert_delivery_ticket(data: Dict[str, Any]):
    assert_common_fields(data, "DeliveryTicket")
    assert isinstance(data.get("route_stop_id"), str)
    assert isinstance(data.get("contract_id"), str)
    assert isinstance(data.get("delivered_at"), str)
    _assert_number(data.get("gross_bushels"), "DeliveryTicket.gross_bushels")
    _assert_number(data.get("moisture_pct"), "DeliveryTicket.moisture_pct")
    _assert_number(data.get("net_bushels"), "DeliveryTicket.net_bushels")
    _assert_int(data.get("hauling_add_on_cents"), "DeliveryTicket.hauling_add_on_cents")
    assert isinstance(data.get("used_our_trucks"), bool)


def assert_settlement(data: Dict[str, Any]):
    assert_common_fields(data, "Settlement")
    assert isinstance(data.get("contract_id"), str)
    assert isinstance(data.get("season_id"), str)
    for field in (
        "base_amount_cents",
        "fuel_surcharge_cents",
        "hauling_add_on_total_cents",
        "moisture_discount_cents",
        "total_amount_cents",
    ):
        _assert_number(data.get(field), f"Settlement.{field}")
    assert data.get("status") in ("DRAFT", "ISSUED", "PAID", "DISPUTED", "RESOLVED"), (
        f"Settlement.status unexpected: {data.get('status')!r}"
    )
    if data.get("status") != "DRAFT" and data.get("issued_at") is not None:
        assert is_iso8601_timestamp(data["issued_at"]), (
            f"Settlement.issued_at must be ISO 8601, got {data.get('issued_at')!r}"
        )


def assert_lodging_reservation(data: Dict[str, Any]):
    assert_common_fields(data, "LodgingReservation")
    assert isinstance(data.get("route_stop_id"), str)
    assert isinstance(data.get("crew_member_id"), str)
    assert isinstance(data.get("lodging_site_id"), str)
    assert isinstance(data.get("stay_start_date"), str)
    assert isinstance(data.get("stay_end_date"), str)
    _assert_int(data.get("bed_count"), "LodgingReservation.bed_count")
    assert data.get("status") in ("BOOKED", "CHECKED_IN", "CHECKED_OUT", "CANCELLED"), (
        f"LodgingReservation.status unexpected: {data.get('status')!r}"
    )


def assert_lodging_site(data: Dict[str, Any]):
    assert_common_fields(data, "LodgingSite")
    assert isinstance(data.get("season_id"), str)
    assert isinstance(data.get("site_name"), str) and data["site_name"]
    assert isinstance(data.get("state_code"), str)
    _assert_int(data.get("total_beds"), "LodgingSite.total_beds")


def assert_money_equal(actual: Any, expected_cents: int, label: str = "amount"):
    """Monetary amounts are integer cents (PRD precision rules)."""
    assert int(actual) == expected_cents, (
        f"{label}: expected {expected_cents} cents, got {actual!r}"
    )
