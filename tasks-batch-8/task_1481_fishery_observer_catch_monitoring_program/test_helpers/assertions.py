"""Entity assertions and domain invariant checkers (PRD §2.4, §2.9, §3.9)."""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with or without fractional digits)."""
    assert isinstance(value, str), f"Expected ISO timestamp string, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_same_instant(actual: str, expected: str, label: str = "timestamp"):
    a = _parse_instant(actual)
    b = _parse_instant(expected)
    assert a == b, f"{label}: expected instant {expected}, got {actual}"


def assert_common_fields(data: dict):
    """PRD §2.4: every primary resource carries id/created_at/updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_fishery(data: dict):
    assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["coverage_target_pct"], (int, float))
    assert data["priority_gear"] in ("TRAWL", "LONGLINE", "POT", "GILLNET")


def assert_vessel_operator(data: dict):
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert data["payment_standing"] in ("GOOD", "DELINQUENT")
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_vessel(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("REGISTERED", "ACTIVE", "SUSPENDED")
    assert data["monitoring_mode"] in ("HUMAN_OBSERVER", "ELECTRONIC_MONITORING")
    assert data["gear_type"] in ("TRAWL", "LONGLINE", "POT", "GILLNET")
    assert isinstance(data["selection_penalty_points"], int)
    assert isinstance(data["substantiated_harassment_count"], int)
    assert isinstance(data["sea_days_observed_ytd"], int)


def assert_observer(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "DECERTIFIED")
    assert data["certification_level"] in ("TRAINEE", "CERTIFIED", "LEAD")
    assert isinstance(data["max_consecutive_sea_days"], int)
    assert isinstance(data["sea_days_used_ytd"], int)


def assert_debriefer(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["person_ref"], str) and data["person_ref"]


def assert_em_reviewer(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["person_ref"], str) and data["person_ref"]


def assert_coverage_plan(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("DRAFT", "PUBLISHED", "SELECTION_COMPLETED", "CLOSED")
    assert isinstance(data["projected_fleet_effort_days"], int)
    assert isinstance(data["projected_em_effort_days"], int)
    assert isinstance(data["actual_observer_sea_days"], int)
    assert isinstance(data["actual_em_sea_days"], int)


def assert_selection_run(data: dict):
    assert_common_fields(data)
    assert isinstance(data["run_index"], int) and data["run_index"] >= 1
    assert isinstance(data["vessels_evaluated"], int)
    assert isinstance(data["vessels_selected"], int)
    assert isinstance(data["selection_deficit_sea_days"], int)


def assert_selection_notice(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "ISSUED", "ACCEPTED", "DECLINED", "EXPIRED", "FULFILLED", "DEFAULTED", "VOIDED",
    )
    assert isinstance(data["allocated_sea_days"], int)
    assert isinstance(data["reserved_sea_days"], int)
    assert isinstance(data["consumed_sea_days"], int)
    assert isinstance(data["remaining_sea_days"], int)
    assert isinstance(data["rank"], int) and data["rank"] >= 1


def assert_deployment(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "SCHEDULED", "SAFETY_HOLD", "READY_TO_DEPLOY", "AT_SEA", "RETURNED",
        "EARLY_TERMINATED", "DEBRIEFING", "DATA_REJECTED", "DATA_VALIDATED",
        "CLOSED", "CANCELLED",
    )
    assert isinstance(data["planned_sea_days"], int)


def assert_safety_inspection(data: dict):
    """PRD §2.4: safety-inspection records are immutable — only id + created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "safety inspection must not carry updated_at"
    assert "version" not in data, "safety inspection must not carry version"
    assert data["result"] in ("PASS", "FAIL")
    for flag in (
        "life_raft_certified", "epirb_registered", "immersion_suits_adequate",
        "fire_suppression_ok", "comms_equipment_ok",
    ):
        assert isinstance(data[flag], bool), f"{flag} must be boolean"


def assert_haul_sample(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("RECORDED", "FLAGGED", "VERIFIED", "DISCARDED")
    assert isinstance(data["haul_number"], int) and data["haul_number"] >= 1


def assert_harassment_report(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "FILED", "UNDER_REVIEW", "SUBSTANTIATED", "APPEALED", "DISMISSED", "RESOLVED",
    )
    assert data["report_type"] in ("HARASSMENT", "INTERFERENCE", "SAFETY_COERCION")
    assert isinstance(data["penalty_applied"], bool)


def assert_em_enrollment(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "PENDING_REVIEW", "APPROVED", "REJECTED", "ACTIVE", "SUSPENDED", "TERMINATED",
    )


def assert_em_trip(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "DECLARED", "FOOTAGE_SUBMITTED", "IN_REVIEW", "REVIEWED", "ACCEPTED", "REJECTED",
    )
    assert isinstance(data["trip_sea_days"], int) and data["trip_sea_days"] >= 1


def assert_invoice(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "DRAFT", "ISSUED", "PARTIALLY_PAID", "PAID", "DISPUTED", "OVERDUE", "WAIVED",
    )
    assert data["fee_variant"] in ("STANDARD", "SMALL_VESSEL")
    assert isinstance(data["amount_due_cents"], int)
    assert isinstance(data["amount_paid_cents"], int)
    assert isinstance(data["amount_adjusted_cents"], int)
    assert isinstance(data["amount_outstanding_cents"], int)
    assert isinstance(data["sea_days_billed"], int)
    assert isinstance(data["line_items"], list)


def assert_notice_day_invariant(notice: dict):
    """PRD §2.9: allocated == remaining + reserved + consumed after every mutation."""
    total = (
        notice["remaining_sea_days"]
        + notice["reserved_sea_days"]
        + notice["consumed_sea_days"]
    )
    assert notice["allocated_sea_days"] == total, (
        f"Sea-day partition broken: allocated {notice['allocated_sea_days']} != "
        f"remaining {notice['remaining_sea_days']} + reserved "
        f"{notice['reserved_sea_days']} + consumed {notice['consumed_sea_days']}"
    )


def assert_invoice_balance_invariant(invoice: dict):
    """PRD §3.9: outstanding == due + adjusted - paid, never negative."""
    expected = (
        invoice["amount_due_cents"]
        + invoice["amount_adjusted_cents"]
        - invoice["amount_paid_cents"]
    )
    assert invoice["amount_outstanding_cents"] == expected, (
        f"Invoice balance broken: outstanding {invoice['amount_outstanding_cents']} "
        f"!= due {invoice['amount_due_cents']} + adjusted "
        f"{invoice['amount_adjusted_cents']} - paid {invoice['amount_paid_cents']}"
    )
    assert invoice["amount_outstanding_cents"] >= 0, "outstanding must never go negative"
