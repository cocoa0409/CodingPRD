"""Entity assertions and domain invariant checkers (PRD §2.4, §2.10, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_study(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["protocol_number"], str) and data["protocol_number"]
    assert data["phase"] in ("PHASE_I", "PHASE_II", "PHASE_III", "PHASE_IV")
    assert data["blinding_model"] in ("DOUBLE_BLIND", "SINGLE_BLIND", "OPEN_LABEL")
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "CLOSED")
    assert isinstance(data["max_dose_per_visit_mg"], int)
    assert isinstance(data["unblinding_suspension_threshold_pct"], int)
    assert isinstance(data["randomized_subject_count"], int)
    assert isinstance(data["unblinded_subject_count"], int)


def assert_site(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["study_id"], str) and data["study_id"]
    assert isinstance(data["site_number"], str) and data["site_number"]
    assert data["status"] in ("INITIATED", "ACTIVE", "ON_HOLD", "CLOSED")
    assert "activated_at" in data


def assert_staff(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["site_id"], str) and data["site_id"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["is_unblinded"], bool)


def assert_lot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["study_id"], str) and data["study_id"]
    assert isinstance(data["lot_number"], str) and data["lot_number"]
    assert isinstance(data["strength_mg"], int)
    assert data["status"] in ("ACTIVE", "DEPLETED", "EXPIRED", "CLOSED")
    assert isinstance(data["stability_budget_minutes"], int)
    assert isinstance(data["stability_minutes_consumed"], int)


def assert_kit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["lot_id"], str) and data["lot_id"]
    assert isinstance(data["site_id"], str) and data["site_id"]
    assert isinstance(data["kit_number"], str) and data["kit_number"]
    assert data["status"] in (
        "IN_TRANSIT", "QUARANTINED_RECEIPT", "AVAILABLE", "QUARANTINED_EXCURSION",
        "ALLOCATED", "DISPENSED", "RETURNED", "DESTRUCTION_PENDING", "EXPIRED", "DESTROYED",
    )
    for counter in ("units_received", "units_dispensed", "units_returned",
                    "units_destroyed", "units_lost", "on_hand_units"):
        assert isinstance(data[counter], int), f"{counter} must be int"


def assert_kit_book_balance(data: dict):
    """PRD §2.10 ledger: on_hand = received - dispensed + returned - destroyed - lost."""
    expected = (
        data["units_received"] - data["units_dispensed"] + data["units_returned"]
        - data["units_destroyed"] - data["units_lost"]
    )
    assert data["on_hand_units"] == expected, (
        f"on_hand_units {data['on_hand_units']} != ledger projection {expected}"
    )


def assert_temperature_log(data: dict):
    # Append-only observation: id + created_at only; no updated_at / version (PRD §2.4).
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "temperature log must not carry version"
    assert "updated_at" not in data, "temperature log must not carry updated_at"
    assert isinstance(data["site_id"], str) and data["site_id"]
    assert isinstance(data["celsius"], (int, float))
    assert data["source"] in ("MANUAL", "DATALOGGER")
    assert "excursion_id" in data
    assert is_iso8601_timestamp(data.get("recorded_at", "")), "recorded_at must be ISO 8601"


def assert_excursion(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["site_id"], str) and data["site_id"]
    assert data["status"] in ("OPEN", "RESOLVED_ACCEPTABLE", "RESOLVED_UNACCEPTABLE", "VOIDED")
    assert isinstance(data["severity_minutes_charged"], int)


def assert_subject(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["site_id"], str) and data["site_id"]
    assert isinstance(data["subject_number"], str) and data["subject_number"]
    assert data["stratum"] in ("STANDARD", "HIGH_RISK")
    assert data["enrollment_status"] in (
        "SCREENING", "SCREEN_FAILED", "RANDOMIZED", "COMPLETED", "WITHDRAWN",
    )
    assert data["blinded_status"] in ("BLINDED", "UNBLINDED")
    assert isinstance(data["rescreen_count"], int)


def assert_slot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["study_id"], str) and data["study_id"]
    assert isinstance(data["sequence_number"], int)
    assert data["stratum"] in ("STANDARD", "HIGH_RISK")
    assert isinstance(data["kit_number"], str) and data["kit_number"]
    assert data["status"] in ("UNASSIGNED", "ASSIGNED", "RELEASED")
    assert "arm_code" in data


def assert_dispensing_record(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["subject_id"], str) and data["subject_id"]
    assert isinstance(data["kit_id"], str) and data["kit_id"]
    assert isinstance(data["visit_number"], int) and data["visit_number"] >= 1
    assert isinstance(data["quantity_dispensed"], int) and data["quantity_dispensed"] >= 1
    assert isinstance(data["dose_mg"], int)
    assert data["status"] in ("ACTIVE", "RETURNED", "RECONCILED")


def assert_drug_return(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["dispensing_record_id"], str) and data["dispensing_record_id"]
    assert isinstance(data["quantity_returned"], int) and data["quantity_returned"] >= 1
    assert data["status"] in ("RECORDED", "VERIFIED")
    assert isinstance(data["recorded_by_staff_id"], str) and data["recorded_by_staff_id"]


def assert_destruction_record(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["kit_id"], str) and data["kit_id"]
    assert isinstance(data["site_id"], str) and data["site_id"]
    assert data["method"] in ("INCINERATION", "CHEMICAL_NEUTRALIZATION", "RETURN_TO_SPONSOR")
    assert isinstance(data["quantity_destroyed"], int)
    assert isinstance(data["witness_staff_id"], str) and data["witness_staff_id"]
    assert data["status"] in ("DRAFT", "WITNESSED", "FINALIZED", "VOIDED")
    assert data["kit_prior_status"] in ("RETURNED", "EXPIRED")


def assert_unblinding_request(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["subject_id"], str) and data["subject_id"]
    assert isinstance(data["reason"], str) and data["reason"]
    assert data["status"] in ("REQUESTED", "APPROVED", "REJECTED", "EXECUTED")
    assert isinstance(data["requested_by_user_id"], str) and data["requested_by_user_id"]


def assert_monitor_visit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["site_id"], str) and data["site_id"]
    assert isinstance(data["monitor_name"], str) and data["monitor_name"]
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "CLOSED_RECONCILED", "CLOSED_DISCREPANCY")
    assert isinstance(data["discrepancy_count"], int)


def assert_fee_schedule(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["study_id"], str) and data["study_id"]
    assert data["status"] in ("DRAFT", "APPROVED", "SUPERSEDED")
    for field in ("setup_fee_cents", "dispensing_fee_cents", "dispensing_tier_threshold",
                  "dispensing_tier_fee_cents", "monitoring_fee_cents_per_hour",
                  "storage_fee_cents_per_kit_month", "unblinding_fee_cents"):
        assert isinstance(data[field], int), f"{field} must be int cents"
    assert isinstance(data["overhead_pct"], (int, float))
