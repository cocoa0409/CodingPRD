"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

SAFETY_STATES = ["NORMAL", "ELEVATED", "ALARM", "LOCKOUT"]
MARKET_STATES = ["OFFLINE", "AVAILABLE", "SUSPENDED"]
RESERVATION_STATUSES = ["HELD", "CONSUMED", "RELEASED", "EXPIRED"]
BID_STATUSES = ["DRAFT", "SUBMITTED", "CLEARED", "UNCLEARED", "WITHDRAWN"]
EXECUTION_STATUSES = ["PENDING", "ACCEPTED", "EXECUTING", "COMPLETED", "FAILED"]
SCORING_STATUSES = ["NOT_SCORED", "PROVISIONAL", "SETTLED"]
THERMAL_BANDS = ["NONE", "WARNING", "RUNAWAY"]
EVENT_STATUSES = ["OPEN", "SUPPRESSION_ACTIVE", "CLOSED"]
OBLIGATION_STATUSES = ["ACTIVE", "SHORTFALL", "PENALIZED", "FULFILLED"]
TEST_STATUSES = ["SCHEDULED", "IN_PROGRESS", "COMPLETED"]
CLAIM_STATUSES = ["DRAFT", "SUBMITTED", "APPROVED", "DENIED", "REMEDIED"]


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"
    assert data["version"] >= 1, f"{entity}.version starts at 1"


def assert_energy_precision(value: float, label: str = "energy"):
    """Energy quantities in megawatt-hours are carried at 3 decimal places."""
    assert value is None or round(float(value), 3) == float(
        value
    ), f"{label} must carry at most 3 decimal places, got {value}"


def assert_efc_precision(value: float, label: str = "equivalent full cycles"):
    """Equivalent full cycles are carried at 4 decimal places."""
    assert value is None or round(float(value), 4) == float(
        value
    ), f"{label} must carry at most 4 decimal places, got {value}"


def assert_pct_precision(value: float, label: str = "percentage"):
    """Performance scores and percentages are carried at 2 decimal places."""
    assert value is None or round(float(value), 2) == float(
        value
    ), f"{label} must carry at most 2 decimal places, got {value}"


def assert_storage_asset(data: dict):
    _assert_common(data, "storage asset")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    for field in (
        "nameplate_energy_mwh",
        "power_rating_mw",
        "poi_mw_limit",
        "poi_mva_limit",
        "warranty_throughput_limit_mwh",
    ):
        assert data[field] > 0, f"storage asset {field} must be greater than 0"
    assert data["poi_mva_limit"] >= data["poi_mw_limit"]
    assert data["reactive_capability_mvar"] >= 0
    assert 50.0 <= data["round_trip_efficiency_pct"] <= 100.0
    assert 0.0 <= data["soc_floor_pct"] < data["soc_ceiling_pct"] <= 100.0
    assert data["safety_state"] in SAFETY_STATES
    assert data["market_state"] in MARKET_STATES
    assert data["cycle_limit_per_year"] > 0
    for field in (
        "soc_mwh",
        "cumulative_throughput_mwh",
        "reserved_mwh_total",
        "free_dispatchable_mwh",
        "rated_energy_mwh",
        "available_energy_mwh",
    ):
        assert_energy_precision(data[field], f"storage asset {field}")
    assert_efc_precision(data["equivalent_full_cycles_ytd"], "equivalent_full_cycles_ytd")
    assert_pct_precision(data["soh_pct"], "soh_pct")
    assert data["free_dispatchable_mwh"] >= 0, "free_dispatchable_mwh is floored at 0"
    assert data["reserved_mwh_total"] >= 0


def assert_soc_reservation(data: dict):
    _assert_common(data, "reservation")
    assert data["purpose"] in ["ENERGY_ARBITRAGE", "ANCILLARY", "CAPACITY"]
    assert data["status"] in RESERVATION_STATUSES
    assert data["reserved_mwh"] > 0
    assert_energy_precision(data["reserved_mwh"], "reserved_mwh")
    assert_energy_precision(data["consumed_mwh"], "consumed_mwh")
    assert data["priority_rank"] in [1, 2, 3]
    assert data["window_end"] > data["window_start"]


def assert_market_bid(data: dict):
    _assert_common(data, "market offer")
    assert data["market_type"] in ["DAY_AHEAD", "REAL_TIME"]
    assert data["product"] in ["ENERGY", "REG_UP", "REG_DOWN", "SPIN"]
    assert data["direction"] in ["DISCHARGE", "CHARGE"]
    assert data["status"] in BID_STATUSES
    assert data["offer_mw"] > 0
    assert data["price_adder_usd_per_mwh"] >= 0
    assert data["offer_price_usd_per_mwh"] >= 0.00, "the minimum offer price is 0.00"
    assert_cost_precision(data["offer_price_usd_per_mwh"])
    assert_energy_precision(data["expected_energy_mwh"], "expected_energy_mwh")
    assert_efc_precision(data["cycle_debit_efc"], "cycle_debit_efc")
    assert isinstance(data["revision_count"], int) and 0 <= data["revision_count"] <= 3
    assert data["delivery_end"] > data["delivery_start"]


def assert_dispatch_instruction(data: dict):
    _assert_common(data, "dispatch instruction")
    assert data["execution_status"] in EXECUTION_STATUSES
    assert data["scoring_status"] in SCORING_STATUSES
    assert data["direction"] in ["DISCHARGE", "CHARGE"]
    assert data["instructed_mw"] > 0
    assert_energy_precision(data["expected_energy_mwh"], "expected_energy_mwh")
    assert_energy_precision(data["delivered_mwh"], "delivered_mwh")
    assert_energy_precision(data["soc_delta_mwh"], "soc_delta_mwh")
    assert isinstance(data["telemetry_sample_count"], int)
    assert data["telemetry_sample_count"] >= 0
    assert_cost_precision(data["non_performance_charge_usd"])
    assert data["setpoint_end"] > data["setpoint_start"]
    for field in ("accuracy_score", "deadband_pct", "composite_score"):
        assert_pct_precision(data[field], field)


def assert_telemetry_sample(data: dict):
    """A sample is an immutable measurement: only `id` and `created_at`."""
    assert is_valid_uuid(data.get("id", "")), "telemetry sample id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), "telemetry sample created_at must be ISO 8601"
    assert "updated_at" not in data, "a telemetry sample has no updated_at"
    assert "version" not in data, "a telemetry sample has no version"
    assert isinstance(data["sample_index"], int) and data["sample_index"] >= 1
    assert data["measured_mw"] >= 0
    assert data["thermal_escalation"] in THERMAL_BANDS
    assert isinstance(data["within_deadband"], bool)
    assert_energy_precision(data["apparent_mva"], "apparent_mva")
    assert_energy_precision(data["deviation_mw"], "deviation_mw")
    assert_efc_precision(data["error_ratio"], "error_ratio")


def assert_safety_event(data: dict):
    _assert_common(data, "safety event")
    assert data["event_type"] in [
        "THERMAL_ANOMALY",
        "THERMAL_RUNAWAY",
        "OFFGAS_DETECTED",
        "SMOKE_DETECTED",
    ]
    assert data["severity"] in ["ADVISORY", "WARNING", "CRITICAL"]
    assert data["source"] in ["MANUAL", "TELEMETRY_AUTO"]
    assert data["imposed_safety_state"] in ["NONE", "ELEVATED", "ALARM", "LOCKOUT"]
    assert data["status"] in EVENT_STATUSES
    assert isinstance(data["suppression_discharged"], bool)
    assert isinstance(data["responder_cleared"], bool)
    assert isinstance(data["emergency_ack_agencies"], list)
    assert isinstance(data["opened_by_user_id"], str) and data["opened_by_user_id"]


def assert_capacity_obligation(data: dict):
    _assert_common(data, "capacity obligation")
    assert data["status"] in OBLIGATION_STATUSES
    assert 2000 <= data["program_year"] <= 2100
    assert data["committed_mw"] > 0
    assert 0 < data["availability_hours_required"] <= 8760
    assert data["penalty_rate_usd_per_mw_hour"] >= 0
    assert data["obligation_duration_hours"] > 0
    assert data["assessment_mode"] in [None, "PRELIMINARY", "FINAL"]
    assert_pct_precision(data["unavailable_hours"], "unavailable_hours")
    assert_pct_precision(data["measured_available_hours"], "measured_available_hours")
    assert_pct_precision(data["shortfall_hours"], "shortfall_hours")
    assert_pct_precision(data["availability_pct"], "availability_pct")
    assert_cost_precision(data["penalty_exposure_usd"])
    assert_energy_precision(data["derated_committed_mw"], "derated_committed_mw")


def assert_capacity_test(data: dict):
    _assert_common(data, "capacity test")
    assert data["status"] in TEST_STATUSES
    assert isinstance(data["warranty_claim_triggered"], bool)
    assert_energy_precision(
        data["test_energy_throughput_mwh"], "test_energy_throughput_mwh"
    )
    assert_energy_precision(data["measured_capacity_mwh"], "measured_capacity_mwh")
    for field in ("measured_soh_pct", "expected_soh_pct", "soh_deficit_pct"):
        assert_pct_precision(data[field], field)


def assert_warranty_claim(data: dict):
    _assert_common(data, "warranty claim")
    assert data["claim_type"] in ["CAPACITY_SHORTFALL", "THROUGHPUT_BREACH"]
    assert data["status"] in CLAIM_STATUSES
    assert data["denial_reason"] in [
        None,
        "NO_SHORTFALL",
        "THROUGHPUT_EXCEEDED_WARRANTY",
        "LATE_FILING",
    ]
    assert_pct_precision(data["claimed_shortfall_pct"], "claimed_shortfall_pct")
    assert_energy_precision(data["remedy_energy_add_mwh"], "remedy_energy_add_mwh")
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]


def assert_throughput_conservation(asset: dict, completed_delivered, completed_tests):
    """`cumulative_throughput_mwh` equals the initial carry-over plus every
    completed instruction's delivered energy plus every completed test's credit."""
    expected = round(
        asset["initial_cumulative_throughput_mwh"]
        + sum(completed_delivered)
        + sum(completed_tests),
        3,
    )
    assert (
        abs(asset["cumulative_throughput_mwh"] - expected) < 0.0005
    ), f"cumulative_throughput_mwh {asset['cumulative_throughput_mwh']} != {expected}"


def assert_soc_conservation(asset: dict, completed_soc_deltas):
    """`soc_mwh` equals `initial_soc_mwh` plus every completed instruction's
    signed state-of-charge movement."""
    expected = round(asset["initial_soc_mwh"] + sum(completed_soc_deltas), 3)
    assert (
        abs(asset["soc_mwh"] - expected) < 0.0005
    ), f"soc_mwh {asset['soc_mwh']} != {expected}"
