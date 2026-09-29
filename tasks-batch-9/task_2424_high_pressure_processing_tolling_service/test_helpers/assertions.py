"""Entity assertions and conserved-ledger invariant checkers.

Each ``assert_<entity>`` helper checks only what the PRD pins for that resource:
the shape of the system-managed properties and the enumerations the resource's
own fields are drawn from.  The two append-only event records are additionally
checked for the *absence* of ``updated_at`` and ``version``.

The three ``assert_*_conserved`` helpers encode the three quantities the PRD
declares conserved: a pallet's unit ledger, a contract's slot ledger and a
customer's chargeback balance.
"""

from typing import List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    CHARGEBACK_BASES,
    CROSS_CONTAMINATION_GROUPS,
    DEVIATION_FLAG_ORDER,
    PACKAGE_FORMATS,
)


# --------------------------------------------------------------------------- #
# shared shape checks
# --------------------------------------------------------------------------- #
def assert_common_fields(data: dict) -> None:
    """id is a server-minted UUID with no type prefix; created_at and updated_at
    are ISO 8601 UTC timestamps; version starts at 1 and only ever rises."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer of at least 1, got {data.get('version')!r}"
    )


def assert_append_only_fields(data: dict) -> None:
    """An append-only event record carries only id and created_at of the system
    properties — it has neither an updated_at nor a version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert "updated_at" not in data or data["updated_at"] is None, (
        "updated_at must be absent from an append-only record"
    )
    assert "version" not in data or data["version"] is None, (
        "version must be absent from an append-only record"
    )


def assert_timestamp_has_three_fractional_digits(value: str) -> None:
    assert isinstance(value, str) and "." in value, (
        f"expected a timestamp with fractional digits, got {value!r}"
    )
    fraction = value.split(".")[1]
    digits = "".join(ch for ch in fraction if ch.isdigit())
    assert len(digits) == 3, f"expected three fractional digits in {value!r}"


def assert_two_decimal_places(value: float) -> None:
    """Percentages and scores are carried to two decimal places."""
    assert isinstance(value, (int, float)), f"expected a number, got {value!r}"
    assert round(float(value), 2) == float(value), (
        f"expected a value carried to two decimal places, got {value!r}"
    )


def assert_whole_cents(value: Optional[int]) -> None:
    """All monetary amounts are integers denominated in whole cents."""
    assert value is None or (
        isinstance(value, int) and not isinstance(value, bool)
    ), f"monetary amounts must be whole-cent integers, got {value!r}"


def assert_instant_equals(actual: Optional[str], expected_prefix: str) -> None:
    """Compare an API timestamp against an expected instant written without
    fractional digits, tolerating the three fractional digits the API adds."""
    assert actual is not None, f"expected the instant {expected_prefix}, got None"
    normalised = actual.replace("Z", "").split(".")[0]
    assert normalised == expected_prefix.replace("Z", "").split(".")[0], (
        f"expected the instant {expected_prefix}, got {actual}"
    )


# --------------------------------------------------------------------------- #
# per-entity assertions
# --------------------------------------------------------------------------- #
def assert_customer(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    code = data["code"]
    assert isinstance(code, str) and 3 <= len(code) <= 12
    assert all(ch.isupper() or ch.isdigit() or ch == "_" for ch in code), (
        f"code must be uppercase letters, digits and underscores, got {code!r}"
    )
    assert "@" in data["billing_email"]
    assert isinstance(data["trailing_leaker_ppm"], int)
    assert_whole_cents(data["chargeback_balance_cents"])


def assert_product_family(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["family_code"], str)
    assert data["cross_contamination_group"] in CROSS_CONTAMINATION_GROUPS
    assert isinstance(data["cleanout_minutes"], int) and data["cleanout_minutes"] >= 0
    assert isinstance(data["max_receipt_temp_c"], (int, float))
    assert isinstance(data["max_outbound_temp_c"], (int, float))
    assert isinstance(data["requires_dedicated_cycle"], bool)


def assert_vessel(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["vessel_code"], str)
    assert data["chamber_volume_liters"] > 0
    assert data["pump_ramp_rate_mpa_per_sec"] > 0
    assert isinstance(data["decompression_seconds"], int)
    assert data["decompression_seconds"] >= 0
    assert isinstance(data["basket_count"], int) and data["basket_count"] > 0
    assert_whole_cents(data["hourly_operating_cost_cents"])
    assert data["status"] in ["AVAILABLE", "IN_USE", "MAINTENANCE", "DOWN"]
    assert isinstance(data["cycles_run_count"], int) and data["cycles_run_count"] >= 0


def assert_cold_room(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["room_code"], str)
    assert isinstance(data["capacity_pallets"], int) and data["capacity_pallets"] > 0
    groups = data["allowed_family_groups"]
    assert isinstance(groups, list) and len(groups) >= 1
    assert all(group in CROSS_CONTAMINATION_GROUPS for group in groups)
    assert isinstance(data["occupied_pallets"], int) and data["occupied_pallets"] >= 0
    assert data["capacity_state"] in ["NORMAL", "AT_CAPACITY"]
    assert_cold_room_posture_derived(data)


def assert_cold_room_posture_derived(data: dict) -> None:
    """capacity_state is AT_CAPACITY whenever occupied_pallets is greater than or
    equal to capacity_pallets, and NORMAL otherwise."""
    expected = (
        "AT_CAPACITY"
        if data["occupied_pallets"] >= data["capacity_pallets"]
        else "NORMAL"
    )
    assert data["capacity_state"] == expected, (
        f"occupancy {data['occupied_pallets']} against capacity "
        f"{data['capacity_pallets']} implies {expected}, "
        f"got {data['capacity_state']}"
    )


def assert_qualification(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["product_family_id"])
    assert data["package_format"] in PACKAGE_FORMATS
    assert 0 < data["pressure_mpa"] <= 600
    assert data["hold_time_seconds"] > 0
    assert data["film_thickness_micron"] > 0
    assert data["status"] in [
        "DRAFT",
        "SUBMITTED",
        "UNDER_VALIDATION",
        "QUALIFIED",
        "CHANGES_REQUESTED",
        "EXPIRED",
        "SUPERSEDED",
    ]
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0
    assert isinstance(data["validation_run_acceptable_count"], int)
    assert_two_decimal_places(data["package_suitability_score"])
    assert 0.0 <= data["package_suitability_score"] <= 100.0


def assert_validation_run(data: dict) -> None:
    assert_append_only_fields(data)
    assert data["package_integrity_result"] in ["PASS", "MARGINAL", "FAIL"]
    assert data["run_verdict"] in ["ACCEPTABLE", "UNACCEPTABLE"]
    assert data["units_tested"] > 0
    assert 0 <= data["leaker_count"] <= data["units_tested"]
    assert isinstance(data["recorded_by_user_id"], str) and data["recorded_by_user_id"]


def assert_contract(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert data["window_end"] > data["window_start"]
    assert data["committed_slots"] > 0
    assert_whole_cents(data["slot_take_or_pay_cents"])
    assert data["slot_take_or_pay_cents"] >= 0
    assert data["peak_multiplier"] >= 1.0
    assert data["status"] in ["DRAFT", "ACTIVE", "EXHAUSTED", "CLOSED"]
    assert_whole_cents(data["take_or_pay_cents"])
    assert isinstance(data["shortfall_slots"], int) and data["shortfall_slots"] >= 0
    assert_slot_ledger_conserved(data)


def assert_lot(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["qualification_id"])
    assert is_valid_uuid(data["cold_room_id"])
    assert data["unit_count"] > 0
    assert data["segregation_group"] in CROSS_CONTAMINATION_GROUPS
    assert data["custody_state"] in [
        "AT_DOCK",
        "IN_COLD_STORAGE",
        "IN_VESSEL",
        "TREATED",
        "SHIPPED",
        "REJECTED_AT_DOCK",
        "DISPOSED",
    ]
    assert data["release_state"] in [
        "NOT_RELEASED",
        "ON_HOLD_FOR_TEST",
        "RELEASED",
        "REJECTED",
    ]
    assert_unit_ledger_conserved(data)


def assert_vessel_cycle(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["vessel_id"])
    assert is_valid_uuid(data["product_family_id"])
    assert data["target_pressure_mpa"] > 0
    assert data["target_hold_seconds"] > 0
    assert data["state"] in [
        "SCHEDULED",
        "LOADED",
        "RUNNING",
        "COMPLETED_CLEAN",
        "COMPLETED_DEVIATED",
        "DISPOSITIONED",
        "ABORTED",
        "CANCELLED",
    ]
    assert isinstance(data["baskets_used_total"], int)
    assert_two_decimal_places(data["utilization_pct"])
    assert isinstance(data["estimated_cycle_seconds"], int)
    assert_whole_cents(data["estimated_tolling_fee_cents"])
    assert_whole_cents(data["actual_tolling_fee_cents"])


def assert_cycle_load(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["cycle_id"])
    assert is_valid_uuid(data["lot_id"])
    assert is_valid_uuid(data["contract_id"])
    assert data["baskets_used"] > 0
    assert data["units_loaded"] > 0
    assert data["disposition_state"] in [
        "PENDING",
        "ALLOCATED",
        "REPROCESSED",
        "VOIDED",
        "REJECTED",
    ]
    assert data["inspection_state"] in ["PENDING_INSPECTION", "INSPECTED"]
    assert_whole_cents(data["allocated_fee_cents"])
    assert_whole_cents(data["chargeback_cents"])
    if data.get("chargeback_party") is not None:
        assert data["chargeback_party"] in ["CUSTOMER", "FACILITY"]


def assert_cycle_log(data: dict) -> None:
    assert_append_only_fields(data)
    assert data["actual_hold_seconds"] > 0
    assert data["come_up_seconds"] > 0
    assert isinstance(data["actual_cycle_seconds"], int)
    assert data["ccp_verdict"] in ["WITHIN_LIMITS", "DEVIATION"]
    assert isinstance(data["deviation_flags"], list)
    assert all(flag in DEVIATION_FLAG_ORDER for flag in data["deviation_flags"])
    assert_deviation_flag_order(data["deviation_flags"])
    expected_verdict = "WITHIN_LIMITS" if not data["deviation_flags"] else "DEVIATION"
    assert data["ccp_verdict"] == expected_verdict, (
        f"flags {data['deviation_flags']} imply {expected_verdict}, "
        f"got {data['ccp_verdict']}"
    )
    assert isinstance(data["logged_by_user_id"], str) and data["logged_by_user_id"]
    assert is_iso8601_timestamp(data["logged_at"])


def assert_deviation_flag_order(flags: List[str]) -> None:
    """The three flags are collected in the fixed order UNDER_PRESSURE,
    SHORT_HOLD, TEMP_EXCURSION and never re-sorted."""
    positions = [DEVIATION_FLAG_ORDER.index(flag) for flag in flags]
    assert positions == sorted(positions), (
        f"flags must follow the fixed order {DEVIATION_FLAG_ORDER}, got {flags}"
    )


def assert_deviation(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["cycle_id"])
    assert data["deviation_type"] in [
        "UNDER_PRESSURE",
        "SHORT_HOLD",
        "TEMP_EXCURSION",
        "PACKAGE_FAILURE_RATE",
    ]
    assert data["severity"] in ["MAJOR", "CRITICAL"]
    assert_two_decimal_places(data["worst_shortfall_pct"])
    assert data["status"] in [
        "OPEN",
        "ADJUDICATED_ACCEPT",
        "ADJUDICATED_REPROCESS",
        "ADJUDICATED_REJECT",
    ]
    if data.get("chargeback_party") is not None:
        assert data["chargeback_party"] in ["CUSTOMER", "FACILITY"]


def assert_chargeback_line(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert data["basis"] in CHARGEBACK_BASES
    assert_whole_cents(data["amount_cents"])
    assert data["amount_cents"] >= 0
    assert data["status"] in ["PENDING", "WAIVED"]


def assert_day_close_report(data: dict) -> None:
    assert isinstance(data["expired_qualification_count"], int)
    assert isinstance(data["customers_rescored"], int)
    assert is_iso8601_timestamp(data["closed_at"])


# --------------------------------------------------------------------------- #
# conserved ledgers
# --------------------------------------------------------------------------- #
def assert_unit_ledger_conserved(lot: dict) -> None:
    """unit_count always equals units_untreated plus units_in_vessel plus
    units_treated plus units_disposed, after every single request that touches
    the pallet."""
    total = (
        lot["units_untreated"]
        + lot["units_in_vessel"]
        + lot["units_treated"]
        + lot["units_disposed"]
    )
    assert total == lot["unit_count"], (
        f"unit ledger drift: {lot['units_untreated']} untreated + "
        f"{lot['units_in_vessel']} in vessel + {lot['units_treated']} treated + "
        f"{lot['units_disposed']} disposed = {total}, "
        f"but unit_count is {lot['unit_count']}"
    )


def assert_slot_ledger_conserved(contract: dict) -> None:
    """committed_slots always equals reserved_slots plus consumed_slots plus
    available_slots, and available_slots is the remainder of the other two."""
    total = (
        contract["reserved_slots"]
        + contract["consumed_slots"]
        + contract["available_slots"]
    )
    assert total == contract["committed_slots"], (
        f"slot ledger drift: {contract['reserved_slots']} reserved + "
        f"{contract['consumed_slots']} consumed + "
        f"{contract['available_slots']} available = {total}, "
        f"but committed_slots is {contract['committed_slots']}"
    )
    assert contract["available_slots"] == (
        contract["committed_slots"]
        - contract["reserved_slots"]
        - contract["consumed_slots"]
    )


def assert_chargeback_balance_conserved(customer: dict, lines: List[dict]) -> None:
    """chargeback_balance_cents always equals the sum of amount_cents over that
    customer's chargeback lines whose status is PENDING, whatever the basis."""
    pending = sum(
        line["amount_cents"]
        for line in lines
        if line["status"] == "PENDING" and line["customer_id"] == customer["id"]
    )
    assert customer["chargeback_balance_cents"] == pending, (
        f"chargeback balance drift: balance is "
        f"{customer['chargeback_balance_cents']} but the PENDING lines sum to "
        f"{pending}"
    )


def assert_allocation_sums_to(loads: List[dict], total_cents: int) -> None:
    """After the truncate-then-hand-out-leftover-cents pass the allocated amounts
    sum to the fee being divided exactly."""
    allocated = sum(load["allocated_fee_cents"] for load in loads)
    assert allocated == total_cents, (
        f"allocated fees sum to {allocated}, expected exactly {total_cents}"
    )
