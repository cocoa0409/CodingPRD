"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common(data: dict):
    """Common fields carried by every persisted resource (PRD 2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1"


def assert_drug(data: dict):
    _assert_common(data)
    assert isinstance(data["ndc_code"], str) and len(data["ndc_code"]) > 0
    assert data["therapy_category"] in [
        "ANTI_INFECTIVE",
        "AMINOGLYCOSIDE_OR_VANCO",
        "TPN",
        "IMMUNE_GLOBULIN",
        "CHEMO",
    ]
    assert isinstance(data["vial_size_mg"], int) and data["vial_size_mg"] > 0
    assert isinstance(data["awp_per_vial_cents"], int) and data["awp_per_vial_cents"] >= 0
    assert isinstance(data["is_specialty"], bool)
    assert isinstance(data["requires_trough_lab"], bool)
    assert isinstance(data["on_hand_vials"], int) and data["on_hand_vials"] >= 0


def assert_payer_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["plan_code"], str) and len(data["plan_code"]) > 0
    assert isinstance(data["per_diem_rate_cents"], dict)
    assert 0 <= data["awp_discount_pct"] < 1
    assert 0 <= data["coinsurance_pct"] <= 1
    assert isinstance(data["deductible_remaining_cents"], int) and data["deductible_remaining_cents"] >= 0
    assert isinstance(data["oop_max_remaining_cents"], int) and data["oop_max_remaining_cents"] >= 0


def assert_nurse(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["license_state"], str) and len(data["license_state"]) == 2
    assert data["status"] in ["ACTIVE", "INACTIVE"]


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["service_state"], str) and len(data["service_state"]) == 2
    assert is_valid_uuid(data["payer_plan_id"])
    assert data["status"] in ["ACTIVE", "DISCHARGED"]


def assert_referral(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["patient_id"])
    assert data["status"] in ["RECEIVED", "ACCEPTED", "REJECTED"]


def assert_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["referral_id"])
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["drug_id"])
    assert data["route"] in ["IV", "SUBQ", "INTRATHECAL"]
    assert isinstance(data["daily_dose_mg"], int) and data["daily_dose_mg"] > 0
    assert isinstance(data["frequency_per_day"], int) and data["frequency_per_day"] >= 1
    assert isinstance(data["scheduled_days"], int) and data["scheduled_days"] >= 1
    assert isinstance(data["administered_days"], int) and data["administered_days"] >= 0
    assert data["status"] in [
        "DRAFT",
        "PENDING_AUTH",
        "RELEASED",
        "ON_HOLD",
        "ACTIVE",
        "DISCONTINUED",
        "COMPLETED",
    ]
    assert data["hold_reason"] in [None, "ADVERSE_EVENT", "LAB_OVERDUE"]


def assert_prior_auth(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["payer_plan_id"])
    assert isinstance(data["requested_units"], int) and data["requested_units"] > 0
    assert isinstance(data["approved_units"], int) and data["approved_units"] >= 0
    assert data["status"] in ["SUBMITTED", "APPROVED", "DENIED"]


def assert_compound(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["pump_id"])
    assert isinstance(data["vials_reserved"], int) and data["vials_reserved"] >= 0
    assert data["status"] in ["ORDERED", "COMPOUNDED", "DELIVERED", "WASTED"]


def assert_pump(data: dict):
    _assert_common(data)
    assert isinstance(data["asset_tag"], str) and len(data["asset_tag"]) > 0
    assert data["model"] in ["AMBULATORY", "STATIONARY"]
    assert data["status"] in ["AVAILABLE", "RETIRED"]


def assert_supply_kit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert data["kit_type"] in ["START_OF_CARE", "WEEKLY_RESUPPLY", "FLUSH_ONLY"]
    assert isinstance(data["line_count"], int) and data["line_count"] >= 1
    assert data["status"] in ["PICKING", "SHIPPED", "CANCELLED"]


def assert_visit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["nurse_id"])
    assert data["visit_type"] in ["TEACH", "ADMINISTER"]
    assert isinstance(data["duration_min"], int) and data["duration_min"] > 0
    assert isinstance(data["sequence_index"], int)
    assert data["status"] in ["SCHEDULED", "COMPLETED", "MISSED", "CANCELLED"]


def assert_lab_result(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert data["lab_type"] in ["TROUGH", "PEAK", "CMP", "CBC"]
    assert isinstance(data["is_critical"], bool)


def assert_adverse_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert data["severity_grade"] in [1, 2, 3, 4]
    assert isinstance(data["reaction_count"], int) and data["reaction_count"] >= 0
    assert data["vital_instability"] in [0, 1]
    assert isinstance(data["severity_score"], int)
    assert data["status"] in ["REPORTED", "ADJUDICATED"]


def assert_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["payer_plan_id"])
    assert data["variant"] in ["ESTIMATE", "FINAL"]
    assert data["status"] in ["DRAFT", "POSTED", "VOID"]
    for field in (
        "billed_days",
        "per_diem_cents",
        "drug_allowed_cents",
        "allowed_total_cents",
        "patient_responsibility_cents",
        "plan_paid_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer (cents)"


def assert_claim_ledger(data: dict):
    """Invariant: plan_paid_cents == allowed_total_cents - patient_responsibility_cents
    and allowed_total_cents == per_diem_cents + drug_allowed_cents (PRD 3.12)."""
    assert (
        data["allowed_total_cents"]
        == data["per_diem_cents"] + data["drug_allowed_cents"]
    ), "allowed_total_cents must equal per_diem_cents + drug_allowed_cents"
    assert (
        data["plan_paid_cents"]
        == data["allowed_total_cents"] - data["patient_responsibility_cents"]
    ), "plan_paid_cents must equal allowed_total_cents - patient_responsibility_cents"


def assert_inventory_conserved(drug_data: dict, committed_vials: int):
    """Invariant inv_drug_inventory: on_hand_vials + committed == lot_total_vials
    (PRD 2.9)."""
    assert (
        drug_data["on_hand_vials"] + committed_vials == drug_data["lot_total_vials"]
    ), (
        f"on_hand_vials ({drug_data['on_hand_vials']}) + committed ({committed_vials}) "
        f"must equal lot_total_vials ({drug_data['lot_total_vials']})"
    )
