"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .constants import DENSITY_BAND_HIGH, DENSITY_BAND_MID, COEFF_HIGH_DENSITY, \
    COEFF_MID_DENSITY, COEFF_LOW_DENSITY, REFERENCE_TEMPERATURE_C


def _common(data: dict, versioned: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID string, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601 with three fractional digits, got {data.get('created_at')!r}"
    if versioned:
        assert is_iso8601_timestamp(data.get("updated_at", "")), \
            f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
        assert isinstance(data.get("version"), int) and data["version"] >= 1, \
            f"version must be an integer starting at 1, got {data.get('version')!r}"


def assert_fuel_farm(data: dict):
    _common(data)
    assert isinstance(data["iata_code"], str) and len(data["iata_code"]) == 3
    assert isinstance(data["name"], str)
    assert isinstance(data["hydrant_system_available"], bool)
    assert data["posture"] in ("OPEN", "RESTRICTED", "FROZEN")
    assert isinstance(data["active_permit_throughput_used_liters"], (int, float))
    assert isinstance(data["in_service_asset_count"], int)
    assert isinstance(data["open_spill_count"], int)


def assert_environmental_permit(data: dict):
    _common(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "EXPIRED")
    assert data["max_daily_throughput_liters"] > 0


def assert_storage_tank(data: dict):
    _common(data)
    assert data["service_status"] in ("IN_SERVICE", "ISOLATED", "OUT_OF_SERVICE")
    assert data["quality_status"] in ("ON_TEST", "RELEASED", "QUARANTINED")
    assert data["capacity_liters"] > 0
    assert 0 < data["safe_fill_liters"] <= data["capacity_liters"]
    assert 750 <= data["density_kg_per_m3"] <= 850
    assert_tank_ledger_invariants(data)


def assert_tank_ledger_invariants(data: dict):
    """available_volume_liters is floored at 0.0 and never negative."""
    assert data["available_volume_liters"] >= 0.0, \
        f"available_volume_liters is floored at 0.0, got {data['available_volume_liters']}"
    assert data["reserved_volume_liters"] >= 0.0
    assert_two_decimals(data["book_volume_liters"], "book_volume_liters")
    assert_two_decimals(data["reserved_volume_liters"], "reserved_volume_liters")
    assert_two_decimals(data["available_volume_liters"], "available_volume_liters")


def assert_fuel_receipt(data: dict):
    _common(data)
    assert data["status"] in ("RECORDED", "SAMPLED", "UNDER_TEST", "RELEASED",
                             "QUARANTINED", "REJECTED")
    assert data["delivery_mode"] in ("PIPELINE", "TRUCK")
    assert isinstance(data["retest_round"], int)
    assert data["meter_ticket_gross_liters"] > 0
    assert data["tank_closing_gauge_liters"] > data["tank_opening_gauge_liters"]


def assert_quality_sample(data: dict):
    _common(data)
    assert data["status"] in ("DRAWN", "TESTED")
    assert data["sample_purpose"] in ("RECEIPT_QC", "PERIODIC_TANK_QA", "POST_FILTER_CHANGE")
    parents = [data.get("fuel_receipt_id"), data.get("storage_tank_id"),
               data.get("fueling_asset_id")]
    assert sum(1 for p in parents if p) == 1, \
        f"exactly one of fuel_receipt_id, storage_tank_id, fueling_asset_id must be set, got {parents}"
    if data["status"] == "TESTED":
        assert data["verdict"] in ("PASS", "FAIL")


def assert_fueling_asset(data: dict):
    _common(data)
    assert data["asset_type"] in ("TRUCK", "HYDRANT_CART")
    assert data["status"] in ("IN_SERVICE", "FILTER_DUE", "DOWN_FOR_FILTER", "DOWN_MAINTENANCE")
    assert isinstance(data["reliability_score"], int)
    assert data["reliability_score"] >= 0, "reliability_score is floored at zero"
    assert data["element_life_pct"] >= 0
    if data["asset_type"] == "HYDRANT_CART":
        assert data["onboard_volume_liters"] == 0.0, \
            "a HYDRANT_CART holds nothing, so onboard_volume_liters is always 0.0"


def assert_filter_change(data: dict):
    """A FilterChange is an immutable audit document: only id and created_at."""
    _common(data, versioned=False)
    assert "updated_at" not in data or data.get("updated_at") is None, \
        "a FilterChange carries no updated_at"
    assert "version" not in data or data.get("version") is None, \
        "a FilterChange carries no version"
    assert isinstance(data["element_count"], int) and data["element_count"] >= 1


def assert_hydrant_pit(data: dict):
    _common(data)
    assert data["status"] in ("AVAILABLE", "LOCKED_OUT")


def assert_airline_account(data: dict):
    _common(data)
    assert data["status"] in ("ACTIVE", "CREDIT_HOLD")
    assert data["contract_type"] in ("CONTRACT_FUEL", "INTO_PLANE_ONLY")
    assert isinstance(data["invoiced_exposure_cents"], int)
    assert isinstance(data["accrual_exposure_cents"], int)
    assert len(data["airline_iata_code"]) == 2


def assert_flight(data: dict):
    _common(data)
    assert data["status"] in ("SCHEDULED", "DEPARTED", "CANCELLED")


def assert_fuel_authorization(data: dict):
    _common(data)
    assert data["status"] in ("ISSUED", "REDEEMED", "VOIDED", "EXPIRED")
    assert isinstance(data["authorization_code"], str)
    assert len(data["authorization_code"]) == 14, \
        f"authorization_code is fourteen characters, got {data['authorization_code']!r}"
    assert isinstance(data["day_sequence"], int) and data["day_sequence"] >= 1
    assert data["max_authorized_liters"] > 0


def assert_fueling_order(data: dict):
    _common(data)
    assert data["status"] in ("REQUESTED", "AUTHORIZED", "ASSIGNED", "FUELING",
                             "COMPLETED", "CANCELLED", "ABORTED")
    assert data["delivery_mode"] in ("HYDRANT", "TRUCK")
    assert isinstance(data["unassign_count"], int)
    assert isinstance(data["reserved_amount_cents"], int)
    assert data["requested_uplift_liters"] > 0


def assert_uplift_record(data: dict):
    _common(data)
    assert data["status"] in ("POSTED", "VOIDED", "BILLED")
    assert data["meter_end_liters"] > data["meter_start_liters"]
    assert isinstance(data["billed_line_cents"], int), \
        "money is carried exclusively in integer cents"
    assert isinstance(data["fuel_component_cents"], int)
    assert_two_decimals(data["net_liters"], "net_liters")


def assert_spill_incident(data: dict):
    _common(data)
    assert data["status"] in ("REPORTED", "ESCALATED", "CONTAINED", "REMEDIATED", "CLOSED")
    assert data["surface"] in ("APRON", "TANK_BUND", "UNSEALED_GROUND", "STORM_DRAIN")
    assert data["spilled_volume_liters"] > 0


def assert_reconciliation_run(data: dict):
    _common(data)
    assert data["status"] in ("OPEN", "MEASURED", "VARIANCE_HOLD", "POSTED")
    assert isinstance(data["tank_measurements"], list)


def assert_invoice(data: dict):
    _common(data)
    assert data["status"] in ("DRAFT", "ISSUED", "DISPUTED", "PAID", "VOIDED")
    for money_field in ("fuel_component_cents", "subtotal_cents", "volume_rebate_cents",
                        "admin_fee_cents", "total_cents", "amount_paid_cents"):
        assert isinstance(data[money_field], int), \
            f"{money_field} must be an integer number of cents, got {data[money_field]!r}"
    assert isinstance(data["dispute_round"], int)


# --- numeric precision helpers ---------------------------------------------


def assert_two_decimals(value, field_name: str = "value"):
    """All volumes in liters are carried and compared at 2 decimal places."""
    assert value is not None, f"{field_name} must be present"
    assert round(float(value), 2) == float(value), \
        f"{field_name} must be carried at 2 decimal places, got {value}"


def assert_four_decimals(value, field_name: str = "value"):
    assert value is not None, f"{field_name} must be present"
    assert round(float(value), 4) == float(value), \
        f"{field_name} must be carried at 4 decimal places, got {value}"


# --- reference implementations of PRD arithmetic ---------------------------


def _round_half_up(value: float, digits: int) -> float:
    from decimal import Decimal, ROUND_HALF_UP
    quant = Decimal(1).scaleb(-digits)
    return float(Decimal(repr(float(value))).quantize(quant, rounding=ROUND_HALF_UP))


def expansion_coefficient(density: float) -> float:
    if density >= DENSITY_BAND_HIGH:
        return COEFF_HIGH_DENSITY
    if density >= DENSITY_BAND_MID:
        return COEFF_MID_DENSITY
    return COEFF_LOW_DENSITY


def correction_factor(density: float, temperature_c: float) -> float:
    """One minus the coefficient times (temperature - 15), rounded to five decimals first."""
    coeff = expansion_coefficient(density)
    raw = 1.0 - coeff * (temperature_c - REFERENCE_TEMPERATURE_C)
    return _round_half_up(raw, 5)


def corrected_volume(gross: float, density: float, temperature_c: float) -> float:
    return _round_half_up(gross * correction_factor(density, temperature_c), 2)


def receipt_net_volume(gross: float, density: float, temperature_c: float,
                       measured_water_liters: float = 0.0) -> float:
    corrected = corrected_volume(gross, density, temperature_c)
    cap = _round_half_up(gross * 0.005, 2)
    deduction = min(measured_water_liters, cap)
    return _round_half_up(corrected - deduction, 2)


def assert_same_instant(actual, expected: str, field_name: str = "timestamp"):
    """Assert a server-written timestamp names the same instant as ``expected``.

    PRD §2.4 renders every server-written timestamp as "an ISO 8601 UTC timestamp with
    three fractional digits", so a bare-second literal such as ``2026-08-10T06:00:00Z``
    has to be normalised before it can be compared to the server's value. The comparison
    stays exact — the instant must match to the millisecond — and the three-fractional-digit
    shape of the server value is asserted too.
    """
    assert is_iso8601_timestamp(actual or ""), \
        f"{field_name} must be ISO 8601 with three fractional digits, got {actual!r}"
    body = expected[:-1] if expected.endswith("Z") else expected
    if "." not in body:
        body += ".000"
    assert actual == f"{body}Z", \
        f"{field_name} should be {body}Z, got {actual!r}"
