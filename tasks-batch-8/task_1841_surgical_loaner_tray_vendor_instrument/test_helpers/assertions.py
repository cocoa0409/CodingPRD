"""Entity assertions and domain invariant checkers.

assert_same_instant compares two datetimes as instants (the PRD pins the
instant, e.g. "case's scheduled_start_at minus two hours", while datetime
rendering — fractional digits — is a serializer detail).
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _parse_instant(value: str) -> datetime:
    assert isinstance(value, str), f"expected ISO 8601 string, got {value!r}"
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def assert_same_instant(actual: str, expected_iso: str, label: str = "datetime"):
    """Assert two ISO 8601 strings denote the same instant (exact to the second)."""
    assert is_iso8601_timestamp(actual), (
        f"{label} must be an ISO 8601 UTC timestamp, got {actual!r}")
    a = _parse_instant(actual)
    e = _parse_instant(expected_iso)
    assert a == e, f"{label}: expected instant {expected_iso}, got {actual!r}"


def _assert_system_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def _assert_event_fields(data: dict):
    # Event records carry id + created_at only; updated_at/version absent.
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert "updated_at" not in data, "event records must not carry updated_at"
    assert "version" not in data, "event records must not carry version"


def assert_vendor(data: dict):
    _assert_system_fields(data)
    assert isinstance(data["vendor_name"], str) and data["vendor_name"]
    assert isinstance(data["vendor_code"], str) and data["vendor_code"]
    assert data["status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")
    assert isinstance(data["late_grace_minutes"], int) \
        and data["late_grace_minutes"] >= 0
    assert isinstance(data["late_rate_per_hour_cents"], int) \
        and data["late_rate_per_hour_cents"] > 0
    assert isinstance(data["late_penalty_cap_cents"], int) \
        and data["late_penalty_cap_cents"] > 0
    assert isinstance(data["delay_surcharge_per_minute_cents"], int) \
        and data["delay_surcharge_per_minute_cents"] >= 0
    assert isinstance(data["outstanding_penalty_cents"], int)
    assert isinstance(data["outstanding_liability_cents"], int)


def assert_vendor_rep(data: dict):
    _assert_system_fields(data)
    assert is_valid_uuid(data["vendor_id"])
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["rep_email"], str) and data["rep_email"]
    assert isinstance(data["credential_doc_ref"], str)
    assert data["credential_status"] in (
        "PENDING_VERIFICATION", "ACTIVE", "EXPIRED", "REVOKED")
    assert data["or_access_level"] in ("NONE", "OBSERVER", "SCRUB_ASSIST")


def assert_or_room(data: dict):
    _assert_system_fields(data)
    assert isinstance(data["room_name"], str) and data["room_name"]
    assert isinstance(data["turnover_buffer_minutes"], int) \
        and data["turnover_buffer_minutes"] >= 0


def assert_sterilizer_unit(data: dict):
    _assert_system_fields(data)
    assert isinstance(data["unit_name"], str) and data["unit_name"]
    assert isinstance(data["slot_capacity"], int) and data["slot_capacity"] >= 1
    assert isinstance(data["cycle_minutes"], int) and data["cycle_minutes"] > 0
    assert isinstance(data["cooldown_minutes"], int) \
        and data["cooldown_minutes"] >= 0


def assert_surgical_case(data: dict):
    _assert_system_fields(data)
    assert isinstance(data["case_number"], str) and data["case_number"]
    assert is_valid_uuid(data["or_room_id"])
    assert isinstance(data["procedure_type"], str)
    assert isinstance(data["surgeon_name"], str)
    assert is_iso8601_timestamp(data["scheduled_start_at"])
    assert is_iso8601_timestamp(data["scheduled_end_at"])
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED",
                              "CANCELLED")
    assert data["actual_start_at"] is None or \
        is_iso8601_timestamp(data["actual_start_at"])
    assert data["actual_end_at"] is None or \
        is_iso8601_timestamp(data["actual_end_at"])
    assert isinstance(data["delay_minutes_provisional"], int) \
        and data["delay_minutes_provisional"] >= 0
    assert isinstance(data["vendor_delay_minutes_provisional"], int) \
        and data["vendor_delay_minutes_provisional"] >= 0
    assert data["vendor_delay_minutes_final"] is None or \
        isinstance(data["vendor_delay_minutes_final"], int)


def assert_case_delay_event(data: dict):
    _assert_event_fields(data)
    assert is_valid_uuid(data["case_id"])
    assert data["cause"] in (
        "VENDOR_LATE_DELIVERY", "STERILIZATION_TURNAROUND", "REP_ACCESS_ISSUE",
        "PATIENT", "STAFFING", "OTHER")
    assert isinstance(data["minutes"], int) and data["minutes"] > 0
    assert isinstance(data["recorded_by_role"], str) and data["recorded_by_role"]


def assert_loaner_request(data: dict):
    _assert_system_fields(data)
    assert is_valid_uuid(data["case_id"])
    assert is_valid_uuid(data["vendor_id"])
    assert data["priority_class"] in ("STANDARD", "URGENT", "EMERGENT")
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED",
                              "CANCELLED", "CLOSED")
    assert data["readiness"] in ("NOT_READY", "AT_RISK", "READY")
    assert data["required_delivery_by"] is None or \
        is_iso8601_timestamp(data["required_delivery_by"])
    assert isinstance(data["penalty_exposure_cents"], int)
    assert data["submitted_at"] is None or \
        is_iso8601_timestamp(data["submitted_at"])


def assert_loaner_tray(data: dict):
    _assert_system_fields(data)
    assert is_valid_uuid(data["request_id"])
    assert isinstance(data["tray_code"], str) and data["tray_code"]
    assert isinstance(data["declared_instrument_count"], int) \
        and data["declared_instrument_count"] > 0
    assert isinstance(data["implant_flag"], bool)
    assert isinstance(data["replacement_value_cents"], int) \
        and data["replacement_value_cents"] > 0
    assert data["status"] in (
        "EXPECTED", "DELIVERY_PENDING", "CHECKED_IN", "PROCESSING",
        "QUARANTINED", "STERILE_READY", "STAGED", "IN_USE", "USED",
        "AWAITING_PICKUP", "PICKED_UP", "RECONCILED", "MISSING", "CANCELLED")
    assert data["delivered_instrument_count"] is None or \
        isinstance(data["delivered_instrument_count"], int)
    assert data["returned_instrument_count"] is None or \
        isinstance(data["returned_instrument_count"], int)
    assert isinstance(data["shortage_count"], int) \
        and data["shortage_count"] >= 0
    assert isinstance(data["rework_count"], int) and data["rework_count"] >= 0


def assert_check_in_event(data: dict):
    _assert_event_fields(data)
    assert is_valid_uuid(data["request_id"])
    assert is_valid_uuid(data["rep_id"])
    assert is_iso8601_timestamp(data["delivered_at"])
    assert isinstance(data["lines"], list)
    assert isinstance(data["ifu_provided"], bool)
    assert isinstance(data["loaner_agreement_ref"], str)
    assert data["status"] in ("SUBMITTED", "VERIFIED", "PARTIALLY_VERIFIED")
    assert isinstance(data["late_minutes"], int) and data["late_minutes"] >= 0


def assert_sterilization_turn(data: dict):
    _assert_system_fields(data)
    assert is_valid_uuid(data["tray_id"])
    assert data["sterilizer_unit_id"] is None or \
        is_valid_uuid(data["sterilizer_unit_id"])
    assert isinstance(data["attempt_number"], int) and data["attempt_number"] >= 1
    assert data["status"] in ("DECONTAMINATING", "STERILIZING", "COOLDOWN",
                              "RELEASED", "FAILED_QA")
    assert is_iso8601_timestamp(data["decon_started_at"])


def assert_escalation(data: dict):
    _assert_system_fields(data)
    assert is_valid_uuid(data["request_id"])
    assert data["type"] in ("MISSING_TRAY", "INCOMPLETE_COUNT", "DOCUMENTATION",
                            "STERILIZATION_DELAY", "LATE_DELIVERY")
    assert data["status"] in ("OPEN", "ACKNOWLEDGED", "RESOLVED")
    assert data["resolution_type"] is None or data["resolution_type"] in (
        "BACKFILL_DELIVERY", "SUBSTITUTE_APPROVED", "CASE_RESCHEDULED",
        "CASE_CANCELLED", "WAIVED")


def assert_or_access_pass(data: dict):
    _assert_system_fields(data)
    assert is_valid_uuid(data["rep_id"])
    assert is_valid_uuid(data["case_id"])
    assert data["status"] in ("REQUESTED", "APPROVED", "DENIED", "ADMITTED",
                              "EXITED", "EXPIRED", "REVOKED")
    assert data["window_start_at"] is None or \
        is_iso8601_timestamp(data["window_start_at"])
    assert data["window_end_at"] is None or \
        is_iso8601_timestamp(data["window_end_at"])


def assert_pickup_record(data: dict):
    _assert_system_fields(data)
    assert is_valid_uuid(data["request_id"])
    assert is_valid_uuid(data["rep_id"])
    assert is_iso8601_timestamp(data["picked_up_at"])
    assert isinstance(data["lines"], list)
    assert data["status"] in ("SUBMITTED", "RECONCILED", "DISPUTED")
    assert isinstance(data["discrepancy_count"], int) \
        and data["discrepancy_count"] >= 0


def assert_damage_loss_claim(data: dict):
    _assert_system_fields(data)
    assert is_valid_uuid(data["tray_id"])
    assert is_valid_uuid(data["request_id"])
    assert isinstance(data["claim_seq"], int) and data["claim_seq"] >= 1
    assert data["damage_type"] in ("LOSS", "DAMAGE", "CONTAMINATION")
    assert isinstance(data["shortage_count"], int) \
        and data["shortage_count"] >= 0
    assert isinstance(data["claimed_amount_cents"], int) \
        and data["claimed_amount_cents"] > 0
    assert isinstance(data["provisional_vendor_share_cents"], int) \
        and data["provisional_vendor_share_cents"] >= 0
    assert data["final_vendor_share_cents"] is None or \
        isinstance(data["final_vendor_share_cents"], int)
    assert data["final_hospital_share_cents"] is None or \
        isinstance(data["final_hospital_share_cents"], int)
    assert data["status"] in ("FILED", "APPORTIONED", "DISPUTED", "SETTLED")


def assert_penalty_assessment(data: dict):
    _assert_system_fields(data)
    assert is_valid_uuid(data["request_id"])
    assert is_valid_uuid(data["check_in_id"])
    assert isinstance(data["late_minutes"], int) and data["late_minutes"] >= 0
    assert isinstance(data["billable_minutes"], int) \
        and data["billable_minutes"] >= 0
    assert isinstance(data["time_charge_cents"], int) \
        and data["time_charge_cents"] >= 0
    assert isinstance(data["delay_surcharge_cents"], int) \
        and data["delay_surcharge_cents"] >= 0
    assert isinstance(data["assessed_cents"], int)
    assert isinstance(data["waived_cents"], int) and data["waived_cents"] >= 0
    assert isinstance(data["settled_cents"], int) and data["settled_cents"] >= 0
    assert isinstance(data["outstanding_cents"], int) \
        and data["outstanding_cents"] >= 0
    assert data["status"] in ("ACCRUING", "ASSESSED", "SETTLED",
                              "WAIVED_CLOSED", "VOID")


def assert_penalty_money_conservation(penalty: dict):
    """Domain invariant (PRD): outstanding is always assessed minus waived
    minus settled — the money allocation of a penalty is conserved."""
    assert penalty["outstanding_cents"] == (
        penalty["assessed_cents"] - penalty["waived_cents"]
        - penalty["settled_cents"]
    ), (
        f"penalty money not conserved: {penalty['assessed_cents']} != "
        f"{penalty['waived_cents']} + {penalty['settled_cents']} + "
        f"{penalty['outstanding_cents']}"
    )


def assert_tray_count_conservation(tray: dict):
    """Domain invariant (PRD): a reconciled tray's shortage is exactly its
    delivered count minus its returned count."""
    if tray["delivered_instrument_count"] is not None \
            and tray["returned_instrument_count"] is not None:
        assert tray["delivered_instrument_count"] == (
            tray["returned_instrument_count"] + tray["shortage_count"]
        ), (
            f"instrument counts not conserved on tray {tray['id']}: "
            f"{tray['delivered_instrument_count']} != "
            f"{tray['returned_instrument_count']} + {tray['shortage_count']}"
        )
