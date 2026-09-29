"""Entity assertions and domain invariant checkers for the catastrophe response API."""
import pytest

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .types import (
    AccessStatus,
    AdvanceBasis,
    AdvanceStatus,
    AssignmentStatus,
    BatchStatus,
    BulletinStatus,
    BulletinType,
    CredentialStatus,
    DeploymentAxisStatus,
    DeploymentStatus,
    EmploymentType,
    EstimateMethod,
    EventPosture,
    EventStatus,
    HandlingStatus,
    HousingBlockStatus,
    InspectionMode,
    PaymentStatus,
    PerilType,
    ReserveEntryType,
    RoleType,
    SurgePremiumTier,
    TriageTier,
    VendorAssignmentStatus,
    VendorFirmStatus,
    VendorType,
)

MONEY_TOL = 0.005


def _values(enum_cls):
    return [m.value for m in enum_cls]


# --------------------------------------------------------------------------
# Shared field shapes
# --------------------------------------------------------------------------
def assert_identity_fields(data: dict, mutable: bool = True):
    """`id` is a server-minted UUID with no type prefix; `created_at` is ISO 8601 UTC.

    Mutable resources additionally carry `updated_at` and an integer `version`
    starting at 1. Immutable rows (the reserve ledger and loss-estimate
    snapshots) must NOT carry `updated_at` or `version`.
    """
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    if mutable:
        assert is_iso8601_timestamp(
            data.get("updated_at", "")
        ), f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
        assert isinstance(data.get("version"), int), "version must be an integer"
        assert data["version"] >= 1, "version starts at 1"
    else:
        assert "updated_at" not in data, "immutable rows must not carry updated_at"
        assert "version" not in data, "immutable rows must not carry version"


def assert_money(value, label="amount"):
    assert isinstance(value, (int, float)), f"{label} must be numeric, got {value!r}"
    assert_cost_precision(float(value))


def assert_money_equals(actual, expected, label="amount"):
    assert actual == pytest.approx(expected, abs=0.005), (
        f"Expected {label} == {expected}, got {actual}"
    )


def assert_enum(value, enum_cls, label):
    assert value in _values(enum_cls), f"{label} must be one of {_values(enum_cls)}, got {value!r}"


# --------------------------------------------------------------------------
# CatastropheEvent
# --------------------------------------------------------------------------
def assert_catastrophe_event(data: dict):
    assert_identity_fields(data)
    assert isinstance(data["cat_code"], str) and 3 <= len(data["cat_code"]) <= 24
    assert_enum(data["peril_type"], PerilType, "peril_type")
    assert isinstance(data["jurisdiction_state"], str) and len(data["jurisdiction_state"]) == 2
    assert_enum(data["status"], EventStatus, "status")
    assert_enum(data["posture"], EventPosture, "posture")
    assert isinstance(data["exposure_count"], int) and data["exposure_count"] >= 0
    assert data["avg_insured_value"] >= 0
    assert 0.0 <= data["expected_severity_index"] <= 1.0
    assert isinstance(data["open_claim_count"], int) and data["open_claim_count"] >= 0
    for money_field in (
        "case_reserve_total",
        "paid_total",
        "incurred_total",
        "housing_committed_cost",
        "deployment_settled_cost",
        "gross_loss_estimate",
    ):
        assert_money(data[money_field], money_field)
    assert isinstance(data["moratorium_active"], bool)
    assert isinstance(data["surge_adjuster_count"], int) and data["surge_adjuster_count"] >= 0
    if data["declared_at_utc"] is not None:
        assert is_iso8601_timestamp(data["declared_at_utc"])


def assert_event_incurred_conservation(event: dict):
    """`incurred_total` equals `case_reserve_total` plus `paid_total`, to 2dp."""
    assert_money_equals(
        event["incurred_total"],
        round(event["case_reserve_total"] + event["paid_total"], 2),
        "incurred_total",
    )


# --------------------------------------------------------------------------
# RegulatoryBulletin
# --------------------------------------------------------------------------
def assert_regulatory_bulletin(data: dict):
    assert_identity_fields(data)
    assert isinstance(data["event_id"], str)
    assert isinstance(data["bulletin_number"], str) and data["bulletin_number"]
    assert len(data["jurisdiction_state"]) == 2
    assert_enum(data["bulletin_type"], BulletinType, "bulletin_type")
    assert_enum(data["status"], BulletinStatus, "status")
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])
    assert 0.0 <= data["mandated_advance_pct"] <= 1.0
    assert isinstance(data["deadline_extension_days"], int)
    assert 0 <= data["deadline_extension_days"] <= 365


# --------------------------------------------------------------------------
# Adjuster
# --------------------------------------------------------------------------
def assert_adjuster(data: dict):
    assert_identity_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert_enum(data["employment_type"], EmploymentType, "employment_type")
    assert len(data["home_state"]) == 2
    assert isinstance(data["licensed_states"], list)
    assert is_iso8601_timestamp(data["license_expiry_utc"])
    assert_enum(data["credential_status"], CredentialStatus, "credential_status")
    assert_enum(data["deployment_status"], DeploymentAxisStatus, "deployment_status")
    assert isinstance(data["desk_certified"], bool)
    assert isinstance(data["aerial_certified"], bool)
    assert isinstance(data["max_open_claims"], int) and 1 <= data["max_open_claims"] <= 60
    assert isinstance(data["open_assignment_count"], int) and data["open_assignment_count"] >= 0
    assert data["daily_rate"] > 0
    assert data["per_diem_rate"] >= 0
    assert_adjuster_score_invariants(data)


def assert_adjuster_score_invariants(data: dict):
    """The surge-capacity score is clamped into [0, 100] before its single rounding."""
    score = data["surge_capacity_score"]
    assert 0 <= score <= 100, f"surge_capacity_score must be clamped into [0, 100], got {score}"
    assert_money(score, "surge_capacity_score")
    assert data["cumulative_deployed_hours"] >= 0


# --------------------------------------------------------------------------
# HousingBlock
# --------------------------------------------------------------------------
def assert_housing_block(data: dict):
    assert_identity_fields(data)
    assert isinstance(data["event_id"], str)
    assert isinstance(data["hotel_name"], str) and data["hotel_name"]
    assert isinstance(data["city"], str)
    assert isinstance(data["rooms_total"], int) and 0 <= data["rooms_total"] <= 400
    assert data["nightly_rate"] > 0
    assert_enum(data["status"], HousingBlockStatus, "status")
    assert isinstance(data["block_night_count"], int) and data["block_night_count"] >= 1
    assert_housing_room_conservation(data)


def assert_housing_room_conservation(block: dict):
    """`rooms_total` equals `rooms_available` plus `rooms_occupied`; counts are integers."""
    assert isinstance(block["rooms_occupied"], int), "rooms_occupied must be an integer"
    assert isinstance(block["rooms_available"], int), "rooms_available must be an integer"
    assert block["rooms_occupied"] >= 0
    assert block["rooms_available"] >= 0
    assert block["rooms_total"] == block["rooms_available"] + block["rooms_occupied"], (
        f"rooms_total {block['rooms_total']} must equal rooms_available "
        f"{block['rooms_available']} + rooms_occupied {block['rooms_occupied']}"
    )


# --------------------------------------------------------------------------
# Deployment
# --------------------------------------------------------------------------
def assert_deployment(data: dict):
    assert_identity_fields(data)
    assert isinstance(data["event_id"], str)
    assert_enum(data["role_type"], RoleType, "role_type")
    assert is_iso8601_timestamp(data["window_start_utc"])
    assert is_iso8601_timestamp(data["window_end_utc"])
    assert data["window_end_utc"] > data["window_start_utc"]
    assert isinstance(data["rooms_reserved"], int) and 0 <= data["rooms_reserved"] <= 4
    assert_enum(data["status"], DeploymentStatus, "status")
    assert data["selection_reason"] in ("EXPLICIT_ADJUSTER", "SELECTOR_RANKED")
    assert_money(data["provisional_cost"], "provisional_cost")
    assert_money(data["final_settled_cost"], "final_settled_cost")
    if data.get("surge_premium_tier") is not None:
        assert_enum(data["surge_premium_tier"], SurgePremiumTier, "surge_premium_tier")
    if data["role_type"] == "DESK":
        assert data["rooms_reserved"] == 0, "a DESK deployment reserves no rooms"


# --------------------------------------------------------------------------
# Claim
# --------------------------------------------------------------------------
def assert_claim(data: dict):
    assert_identity_fields(data)
    assert isinstance(data["policy_number"], str) and data["policy_number"]
    assert len(data["loss_state"]) == 2
    assert is_iso8601_timestamp(data["loss_date_utc"])
    assert is_iso8601_timestamp(data["reported_at_utc"])
    assert data["reported_loss_amount"] >= 0
    assert isinstance(data["coverage_lines"], list) and 1 <= len(data["coverage_lines"]) <= 6
    codes = [line["coverage_code"] for line in data["coverage_lines"]]
    assert len(codes) == len(set(codes)), "no coverage code may repeat within the array"
    assert_enum(data["access_status"], AccessStatus, "access_status")
    assert_enum(data["handling_status"], HandlingStatus, "handling_status")
    assert_enum(data["payment_status"], PaymentStatus, "payment_status")
    assert_claim_score_invariants(data)
    if data.get("triage_tier") is not None:
        assert_enum(data["triage_tier"], TriageTier, "triage_tier")
    if data.get("inspection_mode") is not None:
        assert_enum(data["inspection_mode"], InspectionMode, "inspection_mode")
    assert isinstance(data["reopen_count"], int) and 0 <= data["reopen_count"] <= 2
    for money_field in ("advance_cap", "advance_paid_total", "case_reserve", "paid_amount"):
        assert_money(data[money_field], money_field)


def assert_claim_score_invariants(data: dict):
    """The severity score is clamped into [0, 100] before its single rounding."""
    score = data["severity_score"]
    assert 0 <= score <= 100, f"severity_score must be clamped into [0, 100], got {score}"
    assert_money(score, "severity_score")


def assert_claim_tier_band(score: float, tier: str):
    """A score of 75.00 or more is CAT_SEVERE, 50.00 or more COMPLEX,
    25.00 or more STANDARD, and anything below 25.00 FAST_TRACK."""
    if score >= 75.0:
        expected = "CAT_SEVERE"
    elif score >= 50.0:
        expected = "COMPLEX"
    elif score >= 25.0:
        expected = "STANDARD"
    else:
        expected = "FAST_TRACK"
    assert tier == expected, f"score {score} bands as {expected}, got {tier}"


# --------------------------------------------------------------------------
# InspectionAssignment
# --------------------------------------------------------------------------
def assert_inspection_assignment(data: dict):
    assert_identity_fields(data)
    assert isinstance(data["claim_id"], str)
    assert_enum(data["mode"], InspectionMode, "mode")
    assert is_iso8601_timestamp(data["window_start_utc"])
    assert is_iso8601_timestamp(data["window_end_utc"])
    assert data["window_end_utc"] > data["window_start_utc"]
    assert_enum(data["status"], AssignmentStatus, "status")
    assert data["selection_reason"] in ("EXPLICIT_ADJUSTER", "SELECTOR_RANKED")
    if data.get("verified_damage_amount") is not None:
        assert data["verified_damage_amount"] >= 0
    if data.get("report_submitted_at_utc") is not None:
        assert is_iso8601_timestamp(data["report_submitted_at_utc"])


# --------------------------------------------------------------------------
# AdvancePayment
# --------------------------------------------------------------------------
def assert_advance_payment(data: dict):
    assert_identity_fields(data)
    assert isinstance(data["claim_id"], str)
    assert data["requested_amount"] > 0
    assert_money(data["amount"], "amount")
    assert data["amount"] > 0, "an issued advance moves a positive amount"
    assert_enum(data["basis"], AdvanceBasis, "basis")
    assert_enum(data["status"], AdvanceStatus, "status")
    if data["status"] == "VOIDED":
        assert is_iso8601_timestamp(data["voided_at_utc"])


# --------------------------------------------------------------------------
# ReserveEntry — immutable ledger row
# --------------------------------------------------------------------------
def assert_reserve_entry(data: dict):
    assert_identity_fields(data, mutable=False)
    assert isinstance(data["event_id"], str)
    assert isinstance(data["claim_id"], str)
    assert_enum(data["entry_type"], ReserveEntryType, "entry_type")
    assert_money(data["delta_case_reserve"], "delta_case_reserve")
    assert_money(data["delta_paid"], "delta_paid")
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert is_iso8601_timestamp(data["effective_utc"])
    if data["entry_type"] != "REVERSAL":
        assert data.get("reverses_entry_id") is None, (
            "reverses_entry_id is populated only on a REVERSAL row"
        )


def assert_ledger_sequence_ascending(entries: list):
    """The ledger is returned in `sequence_no` ascending order."""
    seqs = [e["sequence_no"] for e in entries]
    assert seqs == sorted(seqs), f"ledger must be sequence_no ascending, got {seqs}"


# --------------------------------------------------------------------------
# VendorFirm / VendorAssignment
# --------------------------------------------------------------------------
def assert_vendor_firm(data: dict):
    assert_identity_fields(data)
    assert isinstance(data["firm_name"], str) and data["firm_name"]
    assert_enum(data["vendor_type"], VendorType, "vendor_type")
    assert isinstance(data["service_states"], list)
    assert_enum(data["status"], VendorFirmStatus, "status")
    assert isinstance(data["max_concurrent_jobs"], int) and 1 <= data["max_concurrent_jobs"] <= 200
    assert isinstance(data["open_job_count"], int) and data["open_job_count"] >= 0
    assert 0 <= data["performance_score"] <= 100


def assert_vendor_assignment(data: dict):
    assert_identity_fields(data)
    assert isinstance(data["claim_id"], str)
    assert data["scope_amount"] > 0
    assert_enum(data["status"], VendorAssignmentStatus, "status")
    assert is_iso8601_timestamp(data["dispatched_at_utc"])
    assert data["selection_reason"] in ("EXPLICIT_VENDOR", "SELECTOR_RANKED")


# --------------------------------------------------------------------------
# LossEstimateSnapshot — immutable row
# --------------------------------------------------------------------------
def assert_loss_estimate_snapshot(data: dict):
    assert_identity_fields(data, mutable=False)
    assert isinstance(data["event_id"], str)
    assert_enum(data["method"], EstimateMethod, "method")
    for money_field in ("gross_estimate", "ibnr_component", "reported_component"):
        assert_money(data[money_field], money_field)
    assert isinstance(data["input_reserve_sequence_high_water"], int)
    assert data["input_reserve_sequence_high_water"] >= 0
    assert isinstance(data["stale"], bool)
    assert is_iso8601_timestamp(data["computed_at_utc"])
    assert_money_equals(
        data["gross_estimate"],
        round(data["reported_component"] + data["ibnr_component"], 2),
        "gross_estimate",
    )


# --------------------------------------------------------------------------
# FileTransferBatch
# --------------------------------------------------------------------------
def assert_file_transfer_batch(data: dict):
    assert_identity_fields(data)
    assert isinstance(data["event_id"], str)
    assert isinstance(data["target_unit"], str) and data["target_unit"]
    assert_enum(data["status"], BatchStatus, "status")
    assert isinstance(data["claim_count"], int) and data["claim_count"] >= 0
    assert isinstance(data["blocking_claim_count"], int) and data["blocking_claim_count"] >= 0
    assert data["blocking_claim_count"] <= data["claim_count"]


# --------------------------------------------------------------------------
# Ordering / list helpers
# --------------------------------------------------------------------------
def assert_created_at_ascending(rows: list):
    stamps = [r["created_at"] for r in rows]
    assert stamps == sorted(stamps), f"rows must be created_at ascending, got {stamps}"


def assert_computed_at_ascending(rows: list):
    stamps = [r["computed_at_utc"] for r in rows]
    assert stamps == sorted(stamps), f"snapshots must be computed_at_utc ascending, got {stamps}"


def find_by_id(rows: list, row_id: str) -> dict:
    matches = [r for r in rows if r.get("id") == row_id]
    assert matches, f"expected a row with id {row_id} in {[r.get('id') for r in rows]}"
    return matches[0]
