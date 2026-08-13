"""Entity assertions and domain invariant checkers (PRD §2.4, §2.6, §2.9)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    CalStatus,
    ClaimStatus,
    CoreGrade,
    CoreSettlementStatus,
    CoreUnitStatus,
    DynoBookingStatus,
    DynoVerdict,
    InterchangeTier,
    InvoiceStatus,
    RemanOrderStatus,
    ReturnStatus,
    RoutingType,
)


def _assert_mutable_common(data: dict, entity: str):
    """Common fields of primary mutable resources (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity}.version must be a positive integer"


def _assert_immutable_common(data: dict, entity: str):
    """Immutable records carry only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    assert "updated_at" not in data, f"{entity} must not carry updated_at (PRD §2.4)"
    assert "version" not in data, f"{entity} must not carry version (PRD §2.4)"


def assert_transmission_model(data: dict):
    _assert_mutable_common(data, "TransmissionModel")
    assert isinstance(data["model_code"], str) and data["model_code"]
    assert isinstance(data["year_start"], int)
    assert isinstance(data["year_end"], int) and data["year_end"] >= data["year_start"]
    assert isinstance(data["core_deposit_cents"], int) and data["core_deposit_cents"] > 0
    assert data["flat_rate_hours"] > 0
    assert isinstance(data["labor_cap_cents"], int) and data["labor_cap_cents"] > 0
    assert isinstance(data["warranty_days"], int) and data["warranty_days"] > 0
    assert isinstance(data["dyno_targets"], list)
    assert isinstance(data["required_parts"], list)
    assert isinstance(data["spec_version"], int) and data["spec_version"] >= 1


def assert_hard_part(data: dict):
    _assert_mutable_common(data, "HardPart")
    assert isinstance(data["part_number"], str) and data["part_number"]
    assert isinstance(data["part_family"], str) and data["part_family"]
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] > 0
    assert isinstance(data["qty_on_hand"], int) and data["qty_on_hand"] >= 0
    assert isinstance(data["qty_reserved"], int) and data["qty_reserved"] >= 0


def assert_hard_part_availability(data: dict):
    """PRD §2.9: availability is the read-only difference qty_on_hand - qty_reserved."""
    assert data["availability"] == data["qty_on_hand"] - data["qty_reserved"], (
        f"availability {data.get('availability')} != "
        f"{data.get('qty_on_hand')} - {data.get('qty_reserved')}"
    )


def assert_interchange_mapping(data: dict):
    _assert_immutable_common(data, "InterchangeMapping")
    assert is_valid_uuid(data.get("hard_part_id", ""))
    assert is_valid_uuid(data.get("transmission_model_id", ""))
    assert data["tier"] in {t.value for t in InterchangeTier}


def assert_reman_order(data: dict):
    _assert_mutable_common(data, "RemanOrder")
    assert is_valid_uuid(data.get("transmission_model_id", ""))
    assert data["status"] in {s.value for s in RemanOrderStatus}
    assert data["cal_status"] in {s.value for s in CalStatus}
    assert data["core_settlement_status"] in {s.value for s in CoreSettlementStatus}
    assert isinstance(data["model_spec_version_pin"], int)
    assert isinstance(data["pinned_spec"], dict)
    assert isinstance(data["shortage_parts"], list)
    assert isinstance(data["reserved_parts"], list)
    assert isinstance(data["surcharge_labor_minutes"], int)
    assert isinstance(data["cal_generation"], int)
    assert isinstance(data["dyno_attempts_used"], int)


def assert_dyno_booking(data: dict):
    _assert_immutable_common(data, "DynoBooking")
    assert is_valid_uuid(data.get("reman_order_id", ""))
    assert isinstance(data["dyno_cell_code"], str) and data["dyno_cell_code"]
    assert is_iso8601_timestamp(data.get("start_utc", ""))
    assert is_iso8601_timestamp(data.get("end_utc", ""))
    assert data["status"] == DynoBookingStatus.BOOKED.value


def assert_dyno_test_run(data: dict):
    _assert_immutable_common(data, "DynoTestRun")
    assert is_valid_uuid(data.get("reman_order_id", ""))
    assert is_valid_uuid(data.get("dyno_booking_id", ""))
    assert isinstance(data["attempt_number"], int) and data["attempt_number"] >= 1
    assert isinstance(data["gear_pressures_kpa"], list)
    assert data["verdict"] in {v.value for v in DynoVerdict}
    assert 0.0 <= data["shift_quality_score"] <= 100.0


def assert_core_unit(data: dict):
    _assert_mutable_common(data, "CoreUnit")
    assert is_valid_uuid(data.get("core_deposit_invoice_id", ""))
    assert isinstance(data["dock_code"], str) and data["dock_code"]
    assert data["status"] in {s.value for s in CoreUnitStatus}
    assert isinstance(data["days_late"], int) and data["days_late"] >= 0
    if data.get("grade") is not None:
        assert data["grade"] in {g.value for g in CoreGrade}


def assert_core_deposit_invoice(data: dict):
    _assert_mutable_common(data, "CoreDepositInvoice")
    assert is_valid_uuid(data.get("reman_order_id", ""))
    assert isinstance(data["deposit_cents"], int) and data["deposit_cents"] > 0
    assert data["status"] in {s.value for s in InvoiceStatus}
    assert isinstance(data["provisional_credit_cents"], int)


def assert_deposit_invariant(data: dict):
    """PRD §2.6: final_credit_cents + forfeited_cents always equals deposit_cents
    on every settled invoice."""
    if data.get("final_credit_cents") is not None:
        assert data["final_credit_cents"] + data["forfeited_cents"] == data["deposit_cents"], (
            f"deposit invariant broken: {data.get('final_credit_cents')} + "
            f"{data.get('forfeited_cents')} != {data.get('deposit_cents')}"
        )


def assert_warranty_claim(data: dict):
    _assert_mutable_common(data, "WarrantyClaim")
    assert is_valid_uuid(data.get("reman_order_id", ""))
    assert isinstance(data["installer_id"], str) and data["installer_id"]
    assert data["claimed_labor_hours"] > 0
    assert isinstance(data["installer_labor_rate_cents"], int) \
        and data["installer_labor_rate_cents"] > 0
    assert data["claim_status"] in {s.value for s in ClaimStatus}
    assert data["return_status"] in {s.value for s in ReturnStatus}
    if data.get("routing_type") is not None:
        assert data["routing_type"] in {r.value for r in RoutingType}
