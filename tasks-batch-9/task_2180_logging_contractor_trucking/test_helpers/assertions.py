"""Entity assertions and domain invariant checkers."""
from decimal import Decimal, ROUND_HALF_UP

import pytest
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def round_half_up(value, places=0):
    """Half-up rounding: a value exactly halfway rounds away from zero."""
    quant = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


def _assert_common_fields(data: dict, label: str) -> None:
    """id, created_at, updated_at and version, as PRD §2.4 requires."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID string"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be an ISO 8601 UTC timestamp"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{label}.updated_at must be an ISO 8601 UTC timestamp"
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version starts at 1"


def assert_mill(data: dict) -> None:
    _assert_common_fields(data, "Mill")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["receiving_status"] in ("OPEN", "CLOSED")


def assert_mill_contract(data: dict) -> None:
    _assert_common_fields(data, "MillContract")
    assert is_valid_uuid(data["mill_id"])
    assert data["species"] in (
        "DOUGLAS_FIR",
        "WESTERN_HEMLOCK",
        "RED_ALDER",
        "PONDEROSA_PINE",
    )
    assert data["grade"] in ("PEELER", "SAWLOG_1", "SAWLOG_2", "PULP")
    assert data["quota_tons"] > 0
    assert 0 <= data["overrun_tolerance_pct"] <= 0.25
    assert data["base_rate_cents_per_ton"] > 0
    assert data["status"] in ("OPEN", "FILLED", "SUSPENDED", "CLOSED")
    assert_quota_position(data)


def assert_quota_position(contract: dict) -> None:
    """quota_tons = reserved_tons + delivered_tons + available_tons (PRD §3.1)."""
    total = (
        contract["reserved_tons"]
        + contract["delivered_tons"]
        + contract["available_tons"]
    )
    assert total == pytest.approx(contract["quota_tons"], abs=0.005), (
        "available_tons must be the committed quota less reserved less delivered: "
        f"{contract['reserved_tons']} + {contract['delivered_tons']} + "
        f"{contract['available_tons']} != {contract['quota_tons']}"
    )
    assert contract["reserved_tons"] >= 0
    assert contract["delivered_tons"] >= 0


def assert_haul_contractor(data: dict) -> None:
    _assert_common_fields(data, "HaulContractor")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["dot_number"], str) and 1 <= len(data["dot_number"]) <= 32
    assert len(data["base_state_code"]) == 2
    assert data["compliance_status"] in ("COMPLIANT", "WARNED", "SUSPENDED")
    assert 0 <= data["compliance_score"] <= 100, "compliance_score is clamped to 0..100"
    assert isinstance(data["lifetime_settled_cents"], int)


def assert_insurance_certificate(data: dict) -> None:
    _assert_common_fields(data, "InsuranceCertificate")
    assert data["coverage_type"] in (
        "GENERAL_LIABILITY",
        "AUTO_LIABILITY",
        "WORKERS_COMP",
    )
    assert data["limit_cents"] > 0
    assert data["status"] in ("PENDING", "ACTIVE", "EXPIRED", "REVOKED")


def assert_truck(data: dict) -> None:
    _assert_common_fields(data, "Truck")
    assert is_valid_uuid(data["haul_contractor_id"])
    assert data["axle_config"] in ("FIVE_AXLE", "SIX_AXLE", "SEVEN_AXLE")
    assert 10_000 <= data["tare_weight_lbs"] <= 60_000
    assert data["permit_class"] in (
        "STANDARD",
        "DIVISIBLE_LOAD_PERMIT",
        "LONGER_COMBINATION",
    )
    assert data["status"] in ("AVAILABLE", "DISPATCHED", "OUT_OF_SERVICE")


def assert_safety_finding(data: dict) -> None:
    """A SafetyFinding is an immutable audit record: id and created_at only."""
    assert is_valid_uuid(data.get("id", "")), "SafetyFinding.id must be a UUID string"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), "SafetyFinding.created_at must be an ISO 8601 UTC timestamp"
    assert "version" not in data, "SafetyFinding must not carry a version field"
    assert "updated_at" not in data, "SafetyFinding must not carry an updated_at field"
    assert data["severity"] in ("MINOR", "MAJOR", "CRITICAL")
    assert 0 <= data["points"] <= 100


def assert_tract(data: dict) -> None:
    _assert_common_fields(data, "Tract")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert 1 <= len(data["legal_description"]) <= 200
    assert data["gross_acres"] > 0
    assert data["planned_volume_tons"] > 0
    assert data["access_class"] in ("ALL_SEASON", "SUMMER_ONLY", "FROZEN_ONLY")
    assert data["status"] in (
        "PLANNED",
        "MOBILIZING",
        "ACTIVE",
        "SUSPENDED",
        "COMPLETED",
    )
    assert data["suspension_count"] >= 0
    assert data["move_in_cost_cents"] >= 0
    assert data["produced_tons"] >= 0


def assert_production_plan(data: dict) -> None:
    _assert_common_fields(data, "ProductionPlan")
    assert is_valid_uuid(data["tract_id"])
    assert data["target_tons_per_week"] > 0
    assert 1 <= data["plan_horizon_weeks"] <= 52
    assert data["status"] in ("DRAFT", "APPROVED", "SUPERSEDED")


def assert_crew(data: dict) -> None:
    _assert_common_fields(data, "Crew")
    assert data["crew_type"] in ("HAND_FALLING", "MECHANIZED_GROUND", "CABLE_YARDING")
    assert 1 <= data["equipment_pieces"] <= 24
    assert data["daily_rate_cents"] > 0
    assert data["status"] in ("IDLE", "MOBILIZING", "ON_TRACT", "STOOD_DOWN")


def assert_crew_assignment(data: dict) -> None:
    _assert_common_fields(data, "CrewAssignment")
    assert is_valid_uuid(data["tract_id"])
    assert is_valid_uuid(data["crew_id"])
    assert 0 <= data["move_in_miles"] <= 600
    assert data["window_end"] > data["window_start"]
    assert data["lowboy_trips"] >= 1
    assert 185_000 <= data["move_in_cost_cents"] <= 1_250_000, (
        "move_in_cost_cents is floored at 185000 cents and capped at 1250000 cents"
    )
    assert data["status"] in (
        "SCHEDULED",
        "MOVED_IN",
        "WORKING",
        "STOOD_DOWN",
        "RELEASED",
    )


def assert_haul_route(data: dict) -> None:
    _assert_common_fields(data, "HaulRoute")
    assert is_valid_uuid(data["tract_id"])
    assert is_valid_uuid(data["mill_id"])
    assert 1 <= data["distance_miles"] <= 400
    assert 40_000 <= data["legal_gross_weight_lbs"] <= 120_000
    assert data["permit_class_required"] in (
        "STANDARD",
        "DIVISIBLE_LOAD_PERMIT",
        "LONGER_COMBINATION",
    )
    assert data["status"] in ("OPEN", "POSTED_RESTRICTED", "CLOSED")


def assert_shutdown_order(data: dict) -> None:
    _assert_common_fields(data, "ShutdownOrder")
    assert is_valid_uuid(data["tract_id"])
    assert data["reason"] in (
        "WET_WEATHER",
        "FROST_LAW",
        "FIRE_DANGER",
        "SAFETY_STAND_DOWN",
    )
    assert 0 <= data["soil_moisture_index"] <= 100
    assert is_iso8601_timestamp(data["declared_at"])
    assert data["status"] in ("ACTIVE", "LIFTED")


def assert_load(data: dict) -> None:
    _assert_common_fields(data, "Load")
    assert is_valid_uuid(data["tract_id"])
    assert is_valid_uuid(data["mill_contract_id"])
    assert is_valid_uuid(data["haul_route_id"])
    assert is_valid_uuid(data["truck_id"])
    assert is_valid_uuid(data["haul_contractor_id"])
    assert data["estimated_net_tons"] > 0
    assert data["dispatch_status"] in (
        "DISPATCHED",
        "IN_TRANSIT",
        "AT_MILL",
        "DELIVERED",
        "REJECTED",
        "CANCELLED",
    )
    assert data["settlement_status"] in (
        "UNSETTLED",
        "ACCRUED",
        "STATEMENTED",
        "PAID",
    )
    assert data["rehaul_status"] in ("NONE", "REHAULED", "NO_ALTERNATE")
    assert isinstance(data["provisional_haul_pay_cents"], int)
    assert data["scheduled_arrive_at"] > data["scheduled_depart_at"]


def assert_delivery_ticket(data: dict) -> None:
    _assert_common_fields(data, "DeliveryTicket")
    assert is_valid_uuid(data["load_id"])
    assert is_valid_uuid(data["mill_id"])
    assert 0 <= data["gross_weight_lbs"] <= 200_000
    assert 0 <= data["defect_deduction_pct"] <= 0.50
    assert data["ticket_status"] in ("DRAFT", "CERTIFIED", "REJECTED")
    assert_ticket_weight_chain(data)


def assert_ticket_weight_chain(ticket: dict) -> None:
    """The pinned pound-then-ton order of PRD §3.7."""
    assert ticket["net_weight_lbs"] == ticket["gross_weight_lbs"] - ticket[
        "tare_weight_lbs"
    ], "net_weight_lbs is the gross weight less the truck's tare weight"
    assert ticket["payable_lbs"] == ticket["net_weight_lbs"] - ticket[
        "defect_deducted_lbs"
    ], "payable_lbs is the net weight less the rounded deduction"
    expected_tons = round_half_up(Decimal(ticket["payable_lbs"]) / Decimal(2000), 2)
    assert ticket["net_tons"] == pytest.approx(expected_tons, abs=0.005), (
        "net_tons divides only the integer payable pound figure by 2000 and rounds "
        f"half-up to two decimal places: expected {expected_tons}, "
        f"got {ticket['net_tons']}"
    )
    assert (
        ticket["gross_weight_lbs"] <= ticket["max_allowed_gross_lbs"]
    ), "a certified-able ticket never exceeds max_allowed_gross_lbs"


def assert_settlement_statement(data: dict) -> None:
    _assert_common_fields(data, "SettlementStatement")
    assert is_valid_uuid(data["haul_contractor_id"])
    assert data["period_end"] >= data["period_start"]
    assert data["status"] in (
        "DRAFT",
        "SUBMITTED",
        "APPROVED",
        "DISPUTED",
        "REVISED",
        "PAID",
        "VOID",
    )
    assert isinstance(data["lines"], list)
    assert_statement_money_rollup(data)


def assert_statement_money_rollup(statement: dict) -> None:
    """deduction_cents and net_pay_cents follow the pinned rollup of PRD §3.9."""
    assert (
        statement["deduction_cents"]
        == statement["reject_deduction_cents"] + statement["holdback_cents"]
    ), "deduction_cents is the reject deduction plus the holdback"
    assert (
        statement["net_pay_cents"]
        == statement["gross_pay_cents"] - statement["deduction_cents"]
    ), "net_pay_cents is gross pay less that total deduction"


def line_amounts_by_type(statement: dict, line_type: str) -> list:
    return [
        line["amount_cents"]
        for line in statement["lines"]
        if line["line_type"] == line_type
    ]


def lines_for_load(statement: dict, load_id: str) -> list:
    return [line for line in statement["lines"] if line.get("load_id") == load_id]


def normalize_instant(value):
    """Normalise an ISO 8601 UTC instant so trailing fractional zeros compare equal."""
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = frac.rstrip("0")
        text = head if not frac else f"{head}.{frac}"
    return f"{text}Z"


def assert_instant_equals(actual, expected, label="instant"):
    assert normalize_instant(actual) == normalize_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )
