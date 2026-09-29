"""Entity assertions and domain invariant checkers for the OMS API."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    ANESTHESIA_LEVEL_RANK,
    RECOVERY_MINUTES_REQUIRED,
    RESTOCKING_TIERS,
)


def assert_common_fields(data: dict):
    """Mutable resources carry id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC with three fractional digits, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer starting at 1, got {data.get('version')!r}"
    )


def assert_write_once_fields(data: dict):
    """Write-once records carry only id and created_at — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "an immutable record must not expose updated_at"
    assert "version" not in data, "an immutable record must not expose version"


def assert_two_decimal_places(value, label="value"):
    assert isinstance(value, (int, float)), f"{label} must be numeric, got {value!r}"
    assert round(float(value), 2) == float(value), (
        f"{label} must carry at most two decimal places, got {value!r}"
    )


def assert_practice(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert 1 <= data["recovery_bay_count"] <= 12
    assert 0 <= data["turnover_buffer_minutes"] <= 120
    assert data["consignment_credit_limit_cents"] >= 0
    assert data["sedation_privilege_state"] in (
        "UNPERMITTED", "PERMITTED", "RESTRICTED", "SUSPENDED"
    ), f"unexpected sedation_privilege_state {data['sedation_privilege_state']!r}"
    assert isinstance(data["open_adverse_event_count"], int)
    assert data["open_adverse_event_count"] >= 0
    assert isinstance(data["consignment_committed_cents"], int)
    assert data["consignment_committed_cents"] >= 0


def assert_permit(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["practice_id"])
    assert data["permit_level"] in (
        "MINIMAL_SEDATION", "MODERATE_SEDATION", "DEEP_SEDATION_GENERAL"
    )
    assert data["status"] in (
        "APPLIED", "INSPECTION_PENDING", "ACTIVE", "PROBATION",
        "SUSPENDED", "EXPIRED", "REVOKED",
    ), f"unexpected permit status {data['status']!r}"
    assert isinstance(data["required_drill_types"], list)
    assert_two_decimal_places(data["drill_compliance_ratio"], "drill_compliance_ratio")
    assert 0.0 <= float(data["drill_compliance_ratio"]) <= 1.0
    assert isinstance(data["probation_count"], int) and data["probation_count"] >= 0
    if data.get("last_enforcement_reason") is not None:
        assert data["last_enforcement_reason"] in (
            "CRITICAL_DEFICIENCY", "DEFICIENCY_SCORE", "SENTINEL_EVENT",
            "DRILL_LAPSE", "PERMIT_EXPIRY",
        )


def assert_inspection(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["permit_id"])
    assert data["status"] in ("SCHEDULED", "PASSED", "FAILED_CORRECTABLE", "FAILED_CRITICAL")
    for field in ("minor_deficiency_count", "major_deficiency_count", "critical_deficiency_count"):
        assert isinstance(data[field], int) and data[field] >= 0
    if data.get("inspection_score") is not None:
        assert data["inspection_score"] >= 0, "inspection_score is floored at 0"


def assert_drill(data: dict):
    assert_write_once_fields(data)
    assert is_valid_uuid(data["practice_id"])
    assert data["drill_type"] in (
        "AIRWAY_OBSTRUCTION", "LARYNGOSPASM", "MALIGNANT_HYPERTHERMIA",
        "CARDIAC_ARREST", "LOCAL_ANESTHETIC_TOXICITY",
    )
    assert isinstance(data["participant_staff_ids"], list)
    assert len(data["participant_staff_ids"]) >= 2
    assert isinstance(data["deficiency_noted"], bool)


def assert_staff_member(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["practice_id"])
    assert isinstance(data["full_name"], str) and 1 <= len(data["full_name"]) <= 120
    assert data["role_type"] in (
        "SURGEON", "ANESTHESIA_MONITOR", "RECOVERY_NURSE", "INVENTORY_TECH"
    )
    assert isinstance(data["monitoring_certified"], bool)


def assert_patient(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["practice_id"])
    assert 1 <= data["asa_class"] <= 4
    assert 1 <= data["airway_class"] <= 4
    assert float(data["weight_kg"]) > 0
    assert isinstance(data["medical_plan_active"], bool)
    assert isinstance(data["dental_plan_active"], bool)
    assert data["dental_annual_remaining_cents"] >= 0
    assert isinstance(data["age_years"], int) and data["age_years"] >= 0


def assert_block_time(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["practice_id"])
    assert is_valid_uuid(data["surgeon_id"])
    assert data["status"] in ("RESERVED", "PARTIALLY_RELEASED", "RELEASED")
    assert 0 <= data["release_deadline_hours"] <= 336
    assert_block_ledger_conserved(data)


def assert_block_ledger_conserved(block: dict):
    """committed_minutes + released_minutes + open_minutes == block_duration_minutes."""
    total = (
        block["committed_minutes"] + block["released_minutes"] + block["open_minutes"]
    )
    assert total == block["block_duration_minutes"], (
        "block minute ledger must conserve: "
        f"{block['committed_minutes']} + {block['released_minutes']} + "
        f"{block['open_minutes']} != {block['block_duration_minutes']}"
    )
    assert block["open_minutes"] >= 0, "open_minutes is never negative"
    assert_two_decimal_places(block["utilization_pct"], "utilization_pct")


def assert_surgical_case(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["practice_id"])
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["primary_surgeon_id"])
    assert data["planned_anesthesia_level"] in ANESTHESIA_LEVEL_RANK
    assert data["procedure_category"] in (
        "THIRD_MOLAR", "ORTHOGNATHIC", "PATHOLOGY", "TRAUMA", "IMPLANT", "TMJ"
    )
    assert data["scheduling_status"] in (
        "DRAFT", "BLOCK_HELD", "CONFIRMED", "IN_RECOVERY", "COMPLETED", "CANCELLED"
    )
    assert data["clearance_status"] in (
        "NOT_EVALUATED", "EVALUATED", "CLEARED", "DEFERRED"
    )
    assert data["referral_coordination_status"] in (
        "NOT_REQUIRED", "PENDING", "ACKNOWLEDGED"
    )
    assert data["total_charge_cents"] >= 0
    assert data["duration_minutes"] > 0
    assert data["recovery_minutes_required"] == RECOVERY_MINUTES_REQUIRED[
        data["planned_anesthesia_level"]
    ], (
        "recovery_minutes_required must follow the anesthesia level: expected "
        f"{RECOVERY_MINUTES_REQUIRED[data['planned_anesthesia_level']]}, got "
        f"{data['recovery_minutes_required']}"
    )


def assert_evaluation(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["case_id"])
    assert is_valid_uuid(data["evaluator_staff_id"])
    assert 1 <= data["asa_class_recorded"] <= 4
    assert 1 <= data["airway_class_recorded"] <= 4
    assert data["comorbidity_count"] >= 0
    assert data["status"] in ("DRAFT", "SIGNED", "VERIFIED", "SUPERSEDED", "VOIDED")
    if data.get("provisional_risk_score") is not None:
        assert_two_decimal_places(data["provisional_risk_score"], "provisional_risk_score")
    if data.get("final_risk_score") is not None:
        assert_two_decimal_places(data["final_risk_score"], "final_risk_score")
    if data.get("risk_band") is not None:
        assert data["risk_band"] in ("LOW", "ELEVATED", "HIGH", "PROHIBITIVE")


def assert_risk_band_matches(score, band):
    """risk_band floors: <25 LOW, 25..<40 ELEVATED, 40..<55 HIGH, >=55 PROHIBITIVE."""
    expected = (
        "LOW" if score < 25 else
        "ELEVATED" if score < 40 else
        "HIGH" if score < 55 else
        "PROHIBITIVE"
    )
    assert band == expected, f"score {score} must derive band {expected}, got {band}"


def assert_determination(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["case_id"])
    assert data["route"] in ("MEDICAL_PRIMARY", "DENTAL_PRIMARY", "SPLIT", "SELF_PAY")
    assert data["status"] in ("DRAFT", "SUBMITTED", "PENDED", "APPROVED", "DENIED")
    assert isinstance(data["submission_count"], int) and data["submission_count"] >= 0
    for field in ("medical_allowed_cents", "dental_allowed_cents",
                  "patient_responsibility_cents",
                  "dental_annual_remaining_snapshot_cents"):
        assert isinstance(data[field], int), f"{field} must be whole cents, got {data[field]!r}"


def assert_money_identity(determination: dict, total_charge_cents: int):
    """medical + dental + patient responsibility == the case's total_charge_cents."""
    total = (
        determination["medical_allowed_cents"]
        + determination["dental_allowed_cents"]
        + determination["patient_responsibility_cents"]
    )
    assert total == total_charge_cents, (
        "conserved money identity broken: "
        f"{determination['medical_allowed_cents']} + {determination['dental_allowed_cents']}"
        f" + {determination['patient_responsibility_cents']} != {total_charge_cents}"
    )


def assert_implant_lot(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["practice_id"])
    assert float(data["diameter_mm"]) > 0 and float(data["length_mm"]) > 0
    assert data["unit_cost_cents"] >= 0 and data["quantity_on_hand"] >= 0
    assert data["status"] in ("AVAILABLE", "QUARANTINED")
    assert isinstance(data["is_consignment"], bool)
    assert data["available_quantity"] >= 0, "available_quantity is never negative"


def assert_lot_quantities_consistent(lot: dict):
    """available_quantity is quantity_on_hand less quantity_reserved, never negative."""
    if lot["status"] == "QUARANTINED":
        assert lot["available_quantity"] == 0, (
            "a quarantined lot has available_quantity forced to 0"
        )
        return
    expected = max(lot["quantity_on_hand"] - lot["quantity_reserved"], 0)
    assert lot["available_quantity"] == expected, (
        f"available_quantity must be {expected} "
        f"({lot['quantity_on_hand']} on hand less {lot['quantity_reserved']} reserved), "
        f"got {lot['available_quantity']}"
    )


def assert_reservation(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["case_id"])
    assert is_valid_uuid(data["lot_id"])
    assert data["quantity"] >= 1
    assert data["selection_mode"] in ("EXPLICIT", "AUTO_SIZED")
    assert data["status"] in ("HELD", "CONSUMED", "RELEASED", "SHORTED")
    for field in ("line_subtotal_cents", "restocking_fee_cents",
                  "consignment_credit_cents", "consignment_liability_cents"):
        assert isinstance(data[field], int), f"{field} must be whole cents, got {data[field]!r}"


def expected_restocking_fee_cents(line_subtotal_cents: int) -> int:
    """Tier picked once from the whole subtotal, rounded half-up to whole cents."""
    for ceiling, rate in RESTOCKING_TIERS:
        if ceiling is None or line_subtotal_cents <= ceiling:
            return int((line_subtotal_cents * rate) + 0.5)
    raise AssertionError("unreachable restocking tier")


def assert_adverse_event(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["case_id"])
    assert data["event_type"] in (
        "AIRWAY_OBSTRUCTION", "HYPOXEMIA", "PROLONGED_RECOVERY",
        "UNPLANNED_INTUBATION", "NERVE_INJURY", "DEATH",
    )
    assert data["severity"] in ("MINOR", "MODERATE", "SEVERE", "SENTINEL")
    assert data["status"] in (
        "REPORTED", "UNDER_MORBIDITY_REVIEW", "REVIEW_SIGNED_OFF", "CLOSED"
    )
    assert isinstance(data["regulator_notified"], bool)
    assert isinstance(data["late_report"], bool)


def assert_imaging_study(data: dict):
    assert_write_once_fields(data)
    assert is_valid_uuid(data["patient_id"])
    assert data["modality"] in (
        "PANORAMIC", "CEPHALOMETRIC", "CBCT_SMALL_FOV", "CBCT_LARGE_FOV"
    )
    assert data["justification_code"] in (
        "IMPLANT_PLANNING", "THIRD_MOLAR_ASSESSMENT", "PATHOLOGY_STAGING",
        "TRAUMA_SURVEY", "ORTHOGNATHIC_PLANNING",
    )
    assert float(data["dose_mgy_cm2"]) > 0
    assert data["dose_flag"] in ("WITHIN_PROTOCOL", "ABOVE_REFERENCE_LEVEL")
    assert is_iso8601_timestamp(data["retention_until"])


def assert_pagination_meta(meta: dict, expected_limit=None, expected_offset=None,
                           expected_total=None, expected_has_more=None):
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key in meta, f"list responses must carry meta.{key}"
    if expected_limit is not None:
        assert meta["limit"] == expected_limit
    if expected_offset is not None:
        assert meta["offset"] == expected_offset
    if expected_total is not None:
        assert meta["total_count"] == expected_total, (
            f"total_count must count the filtered set: expected {expected_total}, got {meta['total_count']}"
        )
    if expected_has_more is not None:
        assert meta["has_more"] is expected_has_more
