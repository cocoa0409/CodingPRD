"""Entity assertions and the PRD's conserved-quantity invariant checkers."""

from typing import Dict, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AccrualStatus,
    AccrualType,
    AgreementStatus,
    AssessmentBasis,
    AssessmentStatus,
    BrewerStatus,
    ChargebackStatus,
    ClaimStatus,
    CooperationTier,
    CustodyState,
    DistributorStatus,
    DwellFlag,
    FloatPosture,
    InspectionResult,
    InvestigationStatus,
    LossCause,
    OrderStatus,
    PartyType,
    PoolPosture,
    PressureTestResult,
    ScanPoint,
    ServiceStage,
    ServiceState,
)


def _values(enum_cls) -> List[str]:
    return [member.value for member in enum_cls]


def _assert_mutable_record(data: dict, label: str) -> None:
    """Common shape of a record that can be re-written: identifier, creation
    and update timestamps, and a version counter."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{label}.updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version must start at 1"


def _assert_append_only_record(data: dict, label: str) -> None:
    """Common shape of an immutable record: identifier and creation timestamp
    only."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be an ISO 8601 timestamp"


def assert_brewer(data: dict) -> None:
    _assert_mutable_record(data, "brewer")
    assert isinstance(data["name"], str) and data["name"].strip()
    assert isinstance(data["brand_code"], str) and data["brand_code"].strip()
    assert data["status"] in _values(BrewerStatus)
    for field in (
        "credit_limit_cents",
        "chargeback_balance_cents",
        "lifetime_fill_count",
        "upheld_loss_count",
        "loss_rate_bp_trailing_90d",
        "loss_rate_bp_lifetime",
    ):
        assert isinstance(data[field], int), f"brewer.{field} must be an integer"
        assert data[field] >= 0, f"brewer.{field} must not be negative"
    assert data.get("status_reason") is None or isinstance(data["status_reason"], str)


def assert_distributor(data: dict) -> None:
    _assert_mutable_record(data, "distributor")
    assert isinstance(data["name"], str) and data["name"].strip()
    assert isinstance(data["region_code"], str) and len(data["region_code"]) == 2
    assert data["cooperation_tier"] in _values(CooperationTier)
    assert data["status"] in _values(DistributorStatus)
    for field in (
        "return_incentive_rate_cents_per_keg",
        "total_returns_count",
        "on_time_returns_count",
        "incentive_accrual_cents",
    ):
        assert isinstance(data[field], int), f"distributor.{field} must be an integer"
        assert data[field] >= 0
    for field in ("on_time_return_pct", "avg_dwell_days"):
        assert isinstance(
            data[field], (int, float)
        ), f"distributor.{field} must be numeric"
        assert data[field] >= 0
    assert data["on_time_returns_count"] <= data["total_returns_count"]


def assert_keg_pool(data: dict) -> None:
    _assert_mutable_record(data, "pool")
    assert isinstance(data["pool_code"], str) and data["pool_code"].strip()
    assert data["size_liters"] in (20, 30, 50, 58)
    assert isinstance(data["stainless_weight_kg"], (int, float))
    assert 0 < data["stainless_weight_kg"] <= 60
    assert isinstance(data["replacement_cost_cents"], int) and data[
        "replacement_cost_cents"
    ] > 0
    assert isinstance(data["region_code"], str) and len(data["region_code"]) == 2
    assert data["freeze_threshold_pct"] < data["restrict_threshold_pct"], (
        "the freeze threshold must be below the restrict threshold"
    )
    assert data["restricted_max_kegs_per_order"] >= 1
    for field in (
        "kegs_total",
        "kegs_available",
        "kegs_circulating",
        "kegs_servicing",
        "kegs_held",
        "kegs_written_off",
    ):
        assert isinstance(data[field], int), f"pool.{field} must be an integer"
        assert data[field] >= 0, f"pool.{field} must not be negative"
    assert isinstance(data["available_pct"], (int, float))
    assert data["posture"] in _values(PoolPosture)
    assert_pool_census_conserved(data)


def assert_pool_census_conserved(pool: dict) -> None:
    """The five occupancy buckets must always account for every keg in the
    pool."""
    buckets = (
        pool["kegs_available"]
        + pool["kegs_circulating"]
        + pool["kegs_servicing"]
        + pool["kegs_held"]
        + pool["kegs_written_off"]
    )
    assert pool["kegs_total"] == buckets, (
        "pool census is not conserved: kegs_total "
        f"{pool['kegs_total']} != available {pool['kegs_available']} + "
        f"circulating {pool['kegs_circulating']} + servicing "
        f"{pool['kegs_servicing']} + held {pool['kegs_held']} + written off "
        f"{pool['kegs_written_off']}"
    )


def assert_available_pct(pool: dict, expected: float) -> None:
    assert pool["available_pct"] == expected, (
        f"expected available_pct {expected}, got {pool['available_pct']}"
    )


def assert_keg(data: dict) -> None:
    _assert_mutable_record(data, "keg")
    assert is_valid_uuid(data["pool_id"])
    assert isinstance(data["asset_tag"], str) and data["asset_tag"].strip()
    assert data["custody_state"] in _values(CustodyState)
    assert data["service_state"] in _values(ServiceState)
    assert data["dwell_flag"] in _values(DwellFlag)
    for field in (
        "fill_count",
        "fills_at_last_pressure_test",
        "cumulative_dwell_days",
        "scan_count",
        "stainless_scrap_value_cents",
    ):
        assert isinstance(data[field], int), f"keg.{field} must be an integer"
        assert data[field] >= 0, f"keg.{field} must not be negative"
    assert is_iso8601_timestamp(
        data.get("last_pressure_test_at", "")
    ), "keg.last_pressure_test_at is never null"
    assert isinstance(data["misdelivery_open"], bool)
    assert isinstance(data["assessment_open"], bool)
    for field in ("dwell_started_at", "distributor_custody_started_at", "last_scanned_at"):
        value = data.get(field)
        assert value is None or is_iso8601_timestamp(value)
    if data.get("pre_hold_custody_state") is not None:
        assert data["pre_hold_custody_state"] in _values(CustodyState)


def assert_scan_event(data: dict) -> None:
    _assert_append_only_record(data, "scan event")
    assert "version" not in data, "a scan event is immutable and carries no version"
    assert "updated_at" not in data, (
        "a scan event is immutable and carries no updated_at"
    )
    assert is_valid_uuid(data["keg_id"])
    assert data["scan_point"] in _values(ScanPoint)
    assert data["party_type"] in _values(PartyType)
    assert is_iso8601_timestamp(data["scanned_at"])
    assert is_iso8601_timestamp(data["recorded_at"])
    assert isinstance(data["brand_code_scanned"], str)
    assert isinstance(data["misdelivery_detected"], bool)
    assert isinstance(data["is_late_arrival"], bool)
    assert data["custody_state_after"] in _values(CustodyState)
    assert isinstance(data["dwell_days_closed"], int) and data["dwell_days_closed"] >= 0
    if data["scan_point"] == ScanPoint.FILL.value:
        assert isinstance(data["fill_charge_net_cents"], int)
    else:
        assert data.get("fill_charge_net_cents") is None, (
            "only a fill scan carries a per-fill charge"
        )


def assert_float_agreement(data: dict) -> None:
    _assert_mutable_record(data, "agreement")
    assert is_valid_uuid(data["brewer_id"])
    assert is_valid_uuid(data["pool_id"])
    assert isinstance(data["float_size_kegs"], int) and 1 <= data["float_size_kegs"] <= 500
    assert isinstance(data["per_fill_rate_cents"], int) and data["per_fill_rate_cents"] > 0
    assert 0 <= data["replenishment_threshold_pct"] <= 100
    assert data["min_fills_per_month"] >= 0
    assert data["status"] in _values(AgreementStatus)
    assert data["float_posture"] in _values(FloatPosture)
    for field in (
        "kegs_issued_count",
        "kegs_at_brewer_count",
        "pending_replenishment_kegs",
        "billed_fills_count",
        "billed_amount_cents",
    ):
        assert isinstance(data[field], int), f"agreement.{field} must be an integer"
        assert data[field] >= 0, f"agreement.{field} must not be negative"
    if data["float_posture"] != FloatPosture.TIGHT.value:
        assert data["pending_replenishment_kegs"] == 0, (
            "only a tight float reports pending replenishment kegs"
        )


def assert_issuance_order(data: dict) -> None:
    _assert_mutable_record(data, "order")
    assert is_valid_uuid(data["agreement_id"])
    assert is_valid_uuid(data["brewer_id"])
    assert isinstance(data["requested_keg_count"], int) and data["requested_keg_count"] >= 1
    assert isinstance(data["allow_partial"], bool)
    assert data["status"] in _values(OrderStatus)
    assert isinstance(data["allocated_keg_count"], int) and data["allocated_keg_count"] >= 0
    assert isinstance(data["allocation_shortfall"], int) and data["allocation_shortfall"] >= 0
    assert isinstance(data["allocated_keg_ids"], list)
    assert len(data["allocated_keg_ids"]) == data["allocated_keg_count"], (
        "allocated_keg_ids must list exactly the allocated kegs"
    )


def assert_service_center(data: dict) -> None:
    _assert_mutable_record(data, "service centre")
    assert isinstance(data["name"], str) and data["name"].strip()
    assert isinstance(data["region_code"], str) and len(data["region_code"]) == 2
    assert 1 <= data["concurrent_cycle_capacity"] <= 50
    assert 0 <= data["intake_buffer_hours"] <= 48
    assert isinstance(data["open_cycle_count"], int) and data["open_cycle_count"] >= 0


def assert_service_cycle(data: dict) -> None:
    _assert_mutable_record(data, "service cycle")
    assert is_valid_uuid(data["keg_id"])
    assert is_valid_uuid(data["service_center_id"])
    assert data["stage"] in _values(ServiceStage)
    assert is_iso8601_timestamp(data["received_at"])
    if data.get("inspection_result") is not None:
        assert data["inspection_result"] in _values(InspectionResult)
    if data.get("pressure_test_result") is not None:
        assert data["pressure_test_result"] in _values(PressureTestResult)
    for field in ("cleaned_at", "inspected_at", "pressure_tested_at", "released_at"):
        value = data.get(field)
        assert value is None or is_iso8601_timestamp(value)


def assert_loss_assessment(data: dict) -> None:
    _assert_mutable_record(data, "assessment")
    assert is_valid_uuid(data["keg_id"])
    assert data["cause"] in _values(LossCause)
    assert data["assessment_basis"] in _values(AssessmentBasis)
    assert data["assessment_status"] in _values(AssessmentStatus)
    assert data["chargeback_status"] in _values(ChargebackStatus)
    for field in (
        "gross_value_cents",
        "scrap_credit_cents",
        "assessed_value_cents",
        "brewer_liability_pct_bp",
        "net_chargeback_cents",
        "dwell_days_at_assessment",
    ):
        assert isinstance(data[field], int), f"assessment.{field} must be an integer"
        assert data[field] >= 0, f"assessment.{field} must not be negative"
    assert data["assessed_value_cents"] == max(
        0, data["gross_value_cents"] - data["scrap_credit_cents"]
    ), "assessed value is the gross value less the scrap credit, floored at zero"
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]


def assert_reconciliation_claim(data: dict) -> None:
    _assert_mutable_record(data, "claim")
    assert is_valid_uuid(data["keg_id"])
    assert is_valid_uuid(data["claimant_distributor_id"])
    assert is_valid_uuid(data["owning_brewer_id"])
    assert is_valid_uuid(data["misdelivered_to_brewer_id"])
    assert data["status"] in _values(ClaimStatus)
    assert isinstance(data["claimed_offset_cents"], int)
    assert 1 <= data["claimed_offset_cents"] <= 50000
    assert isinstance(data["round_count"], int) and data["round_count"] >= 0
    assert is_iso8601_timestamp(data["evidence_scanned_at"])
    if data.get("last_responder_role") is not None:
        assert data["last_responder_role"] in ("Brewer", "Distributor")


def assert_return_incentive_accrual(data: dict) -> None:
    _assert_mutable_record(data, "accrual")
    assert is_valid_uuid(data["distributor_id"])
    assert is_valid_uuid(data["keg_id"])
    assert data["accrual_type"] in _values(AccrualType)
    assert data["status"] in _values(AccrualStatus)
    assert isinstance(data["dwell_days"], int) and data["dwell_days"] >= 0
    assert isinstance(data["incentive_cents"], int) and data["incentive_cents"] >= 0
    if data["accrual_type"] == AccrualType.RECONCILIATION_OFFSET.value:
        assert is_valid_uuid(data["claim_id"])


def assert_theft_investigation(data: dict) -> None:
    _assert_mutable_record(data, "investigation")
    assert is_valid_uuid(data["pool_id"])
    assert data["status"] in _values(InvestigationStatus)
    for field in (
        "held_keg_count",
        "attached_keg_count",
        "stainless_value_at_risk_cents",
    ):
        assert isinstance(data[field], int), f"investigation.{field} must be an integer"
        assert data[field] >= 0
    assert data["held_keg_count"] <= data["attached_keg_count"]
    assert isinstance(data["opened_by_user_id"], str) and data["opened_by_user_id"]


def assert_commodity_index(data: dict) -> None:
    _assert_append_only_record(data, "commodity index reading")
    assert "version" not in data, (
        "a commodity index reading is immutable and carries no version"
    )
    assert "updated_at" not in data, (
        "a commodity index reading is immutable and carries no updated_at"
    )
    assert isinstance(data["effective_date"], str) and len(data["effective_date"]) == 10
    assert isinstance(data["usd_cents_per_kg"], int) and data["usd_cents_per_kg"] > 0
    assert isinstance(data["source"], str)


# --- Domain invariants ----------------------------------------------------


def assert_chargeback_ledger_matches(brewer: dict, assessments: List[dict]) -> None:
    """The brewer's chargeback balance is the sum of the net chargebacks of
    its issued and settled assessments."""
    expected = sum(
        row["net_chargeback_cents"]
        for row in assessments
        if row["brewer_id"] == brewer["id"]
        and row["chargeback_status"]
        in (ChargebackStatus.ISSUED.value, ChargebackStatus.SETTLED.value)
    )
    assert brewer["chargeback_balance_cents"] == expected, (
        f"chargeback balance {brewer['chargeback_balance_cents']} does not equal "
        f"the sum {expected} of the issued and settled net chargebacks"
    )


def assert_incentive_ledger_matches(distributor: dict, accruals: List[dict]) -> None:
    """The distributor's incentive ledger is the sum of the accrued and paid
    incentives."""
    expected = sum(
        row["incentive_cents"]
        for row in accruals
        if row["distributor_id"] == distributor["id"]
        and row["status"] in (AccrualStatus.ACCRUED.value, AccrualStatus.PAID.value)
    )
    assert distributor["incentive_accrual_cents"] == expected, (
        f"incentive ledger {distributor['incentive_accrual_cents']} does not equal "
        f"the sum {expected} of the accrued and paid incentives"
    )


def assert_census(pool: dict, expected: Dict[str, int]) -> None:
    """Assert an exact five-bucket census plus the pool total."""
    for field, value in expected.items():
        assert pool[field] == value, (
            f"expected pool {field} {value}, got {pool[field]}"
        )
    assert_pool_census_conserved(pool)


def assert_same_record(first: dict, second: dict, label: str = "record") -> None:
    """Two reads of the same row must be identical, version field included."""
    assert first == second, (
        f"repeated reads of the same {label} differ: {first} vs {second}"
    )


def assert_version(data: dict, expected: int, label: str = "record") -> None:
    assert data["version"] == expected, (
        f"expected {label} version {expected}, got {data['version']}"
    )


def assert_no_version_field(data: dict, label: str = "record") -> None:
    assert "version" not in data, f"{label} is immutable and carries no version"
