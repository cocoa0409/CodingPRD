"""Entity assertions and domain invariant checkers.

Every primary resource carries id / created_at / updated_at / version
(PRD §2.5); the append-only credit ledger entry carries only id + created_at.
Datetime-valued fields are compared by parsed instant, not string equality.
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating optional fractional digits."""
    assert isinstance(value, str), f"Expected ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def assert_instant_equal(actual: str, expected_iso: str, label: str = "instant"):
    """Two ISO 8601 strings denote the same instant regardless of whether
    fractional seconds are rendered."""
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"{label}: expected {expected_iso}, got {actual}"
    )


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), \
        "version must be an integer (the PRD pins that it increments per modification, not its absolute starting value)"


def assert_program(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["program_status"] in (
        "OPEN", "CAP_REACHED", "SUSPENDED", "CLOSED")
    assert isinstance(data["aggregate_cap_watts"], int) \
        and data["aggregate_cap_watts"] > 0
    assert data["metering_variant"] in ("ENERGY_BANKING", "MONETARY_CREDIT")
    assert data["true_up_mode"] in ("AVOIDED_COST_PAYOUT", "BANK_ROLLOVER")
    assert isinstance(data["true_up_month"], int) \
        and 1 <= data["true_up_month"] <= 12
    assert data["screening_basis"] in ("COMMITTED", "INCLUDE_QUEUED")
    assert data["bank_cap_wh"] is None or (
        isinstance(data["bank_cap_wh"], int) and data["bank_cap_wh"] >= 0)
    for field in ("interconnected_watts", "reserved_watts",
                  "available_capacity_watts", "queued_count"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_capacity_ledger_invariant(program: dict):
    """PRD §2.7: available == aggregate cap - interconnected - reserved."""
    assert program["available_capacity_watts"] == (
        program["aggregate_cap_watts"]
        - program["interconnected_watts"]
        - program["reserved_watts"]
    ), f"Capacity ledger drift: {program}"


def assert_tariff_schedule(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert isinstance(data["schedule_code"], str) and data["schedule_code"]
    assert is_iso8601_timestamp(data["effective_from"])
    assert data["effective_to"] is None or \
        is_iso8601_timestamp(data["effective_to"])
    for field in ("import_rate_millicents_per_kwh",
                  "export_rate_millicents_per_kwh",
                  "net_surplus_rate_millicents_per_kwh"):
        assert isinstance(data[field], int) and data[field] > 0


def assert_feeder(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["feeder_code"], str) and data["feeder_code"]
    assert isinstance(data["peak_load_watts"], int) \
        and data["peak_load_watts"] > 0
    assert isinstance(data["pre_existing_der_watts"], int) \
        and data["pre_existing_der_watts"] >= 0
    assert isinstance(data["aggregate_der_watts"], int)


def assert_service_transformer(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["feeder_id"])
    assert isinstance(data["transformer_code"], str) \
        and data["transformer_code"]
    assert isinstance(data["nameplate_watts"], int) \
        and data["nameplate_watts"] > 0
    assert isinstance(data["pre_existing_der_watts"], int) \
        and data["pre_existing_der_watts"] >= 0
    assert isinstance(data["aggregate_der_watts"], int)


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]


def assert_service_account(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["transformer_id"])
    assert isinstance(data["account_number"], str) and data["account_number"]
    assert data["service_class"] in ("RESIDENTIAL", "COMMERCIAL", "INDUSTRIAL")
    assert isinstance(data["prior_annual_usage_wh"], int) \
        and data["prior_annual_usage_wh"] >= 0
    assert data["account_status"] in ("ACTIVE", "SUSPENDED", "CLOSED")
    assert data["metering_status"] in ("STANDARD", "NET_METERING")
    assert data["meter_serial"] is None or isinstance(data["meter_serial"], str)
    assert isinstance(data["credit_balance_cents"], int)
    assert isinstance(data["banked_wh"], int)


def assert_application(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert is_valid_uuid(data["service_account_id"])
    assert data["technology"] in ("SOLAR_PV", "WIND", "FUEL_CELL")
    assert isinstance(data["system_size_watts_ac"], int) \
        and data["system_size_watts_ac"] > 0
    assert isinstance(data["estimated_annual_production_wh"], int) \
        and data["estimated_annual_production_wh"] > 0
    assert data["application_status"] in (
        "DRAFT", "PENDING_COMPLETENESS", "INCOMPLETE", "WAITING_FOR_CAPACITY",
        "CAPACITY_RESERVED", "SUPPLEMENTAL_REVIEW", "SCREEN_PASSED",
        "AWAITING_COST_ESTIMATE", "CUSTOMER_DECISION_PENDING",
        "UPGRADE_IN_PROGRESS", "PTO_GRANTED", "OPERATING", "WITHDRAWN",
        "DENIED")
    assert data["denial_reason"] is None or data["denial_reason"] in (
        "PRODUCTION_EXCEEDS_LOAD", "SIZE_EXCEEDS_CLASS_CAP",
        "TECHNICALLY_INFEASIBLE")
    assert data["withdrawal_reason"] is None or data["withdrawal_reason"] in (
        "APPLICANT_WITHDRAWN", "CUSTOMER_DECLINED", "ESTIMATE_EXPIRED",
        "RESERVATION_EXPIRED")
    assert data["queue_position"] is None or (
        isinstance(data["queue_position"], int) and data["queue_position"] >= 1)
    assert isinstance(data["capacity_reserved_watts"], int) \
        and data["capacity_reserved_watts"] >= 0
    assert data["reservation_expires_at"] is None or \
        is_iso8601_timestamp(data["reservation_expires_at"])
    assert isinstance(data["submission_round"], int) \
        and data["submission_round"] >= 0
    assert data["submitted_at"] is None or \
        is_iso8601_timestamp(data["submitted_at"])
    assert data["pto_granted_at"] is None or \
        is_iso8601_timestamp(data["pto_granted_at"])


def assert_document(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["application_id"])
    assert data["doc_type"] in (
        "SITE_PLAN", "SINGLE_LINE_DIAGRAM", "INSURANCE_CERTIFICATE")
    assert isinstance(data["title"], str)
    assert data["review_status"] in ("UPLOADED", "ACCEPTED", "REJECTED")
    assert data["review_note"] is None or isinstance(data["review_note"], str)


def assert_screening_report(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["screening_round"], int) \
        and data["screening_round"] >= 1
    assert data["report_status"] in ("CURRENT", "SUPERSEDED")
    assert data["aggregate_basis"] in ("COMMITTED", "INCLUDE_QUEUED")
    for field in ("transformer_aggregate_after_watts", "transformer_limit_watts",
                  "feeder_aggregate_after_watts", "feeder_limit_watts"):
        assert isinstance(data[field], int)
    for field in ("transformer_screen_passed", "feeder_screen_passed",
                  "size_within_fast_track"):
        assert isinstance(data[field], bool)
    assert data["outcome"] in ("PASSED", "FAILED")
    assert isinstance(data["failing_screens"], list)
    for screen in data["failing_screens"]:
        assert screen in ("TRANSFORMER_CAPACITY", "FEEDER_PENETRATION",
                          "FAST_TRACK_SIZE")


def assert_supplemental_review(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["application_id"])
    assert data["review_type"] in ("FACILITIES_STUDY", "SYSTEM_IMPACT_STUDY")
    assert data["review_status"] in ("OPEN", "COMPLETED", "CLOSED")
    assert data["outcome"] is None or data["outcome"] in (
        "CLEARED", "UPGRADES_REQUIRED", "DENIED")
    assert data["findings"] is None or isinstance(data["findings"], str)


def assert_cost_estimate(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["application_id"])
    assert is_valid_uuid(data["supplemental_review_id"])
    assert isinstance(data["items"], list)
    for item in data["items"]:
        assert isinstance(item["description"], str)
        assert isinstance(item["amount_cents"], int) \
            and item["amount_cents"] >= 0
    assert isinstance(data["contingency_pct"], int) \
        and 0 <= data["contingency_pct"] <= 100
    assert isinstance(data["total_cents"], int) and data["total_cents"] >= 0
    assert is_iso8601_timestamp(data["valid_until"])
    assert data["estimate_status"] in (
        "ISSUED", "ACCEPTED", "WORK_COMPLETE", "DECLINED", "EXPIRED",
        "SUPERSEDED", "CANCELLED")
    assert data["decided_at"] is None or \
        is_iso8601_timestamp(data["decided_at"])


def assert_inspection(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["application_id"])
    assert is_iso8601_timestamp(data["scheduled_date"])
    assert data["inspection_status"] in (
        "SCHEDULED", "RESULT_RECORDED", "CANCELLED")
    assert data["outcome"] is None or data["outcome"] in ("PASSED", "FAILED")
    assert data["occurred_at"] is None or \
        is_iso8601_timestamp(data["occurred_at"])
    assert data["defects"] is None or isinstance(data["defects"], str)
    assert data["inspector_user_id"] is None or \
        isinstance(data["inspector_user_id"], str)


def assert_meter_exchange(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["crew_id"], str) and data["crew_id"]
    assert data["exchange_status"] in (
        "SCHEDULED", "COMPLETED", "FAILED", "CANCELLED")
    assert data["installed_meter_serial"] is None or \
        isinstance(data["installed_meter_serial"], str)
    assert data["technician_user_id"] is None or \
        isinstance(data["technician_user_id"], str)
    assert data["fail_reason"] is None or isinstance(data["fail_reason"], str)


def assert_meter_reading(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["service_account_id"])
    assert isinstance(data["import_wh"], int) and data["import_wh"] >= 0
    assert isinstance(data["export_wh"], int) and data["export_wh"] >= 0
    assert data["reading_status"] in ("POSTED", "SUPERSEDED", "VOIDED")
    assert is_valid_uuid(data["tariff_id"])
    for field in ("bill_cents", "credit_applied_cents", "bank_drawn_wh",
                  "bank_deposited_wh"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_ledger_entry(data: dict):
    """PRD §2.5: the append-only entry carries only id + created_at of the
    common fields — updated_at and version are absent."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert "updated_at" not in data, "ledger entries must not carry updated_at"
    assert "version" not in data, "ledger entries must not carry version"
    assert is_valid_uuid(data["service_account_id"])
    assert data["meter_reading_id"] is None or \
        is_valid_uuid(data["meter_reading_id"])
    assert data["annual_reconciliation_id"] is None or \
        is_valid_uuid(data["annual_reconciliation_id"])
    assert data["entry_type"] in (
        "EXPORT_SURPLUS_CREDIT", "CREDIT_APPLIED", "BANK_DEPOSIT", "BANK_DRAW",
        "BANK_FORFEIT", "TRUE_UP_PAYOUT", "TRUE_UP_FORFEIT", "REVERSAL")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["quantity_wh"], int)


def assert_annual_reconciliation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["service_account_id"])
    assert isinstance(data["reconciliation_year"], int)
    assert data["reconciliation_status"] in ("COMPUTED", "SETTLED", "VOIDED")
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert isinstance(data["surplus_wh"], int) and data["surplus_wh"] >= 0
    assert isinstance(data["credit_balance_at_compute_cents"], int)
    assert isinstance(data["nsc_cents"], int) and data["nsc_cents"] >= 0
    assert isinstance(data["payout_cents"], int) and data["payout_cents"] >= 0
    assert isinstance(data["forfeited_cents"], int) \
        and data["forfeited_cents"] >= 0
    assert isinstance(data["forfeited_wh"], int) and data["forfeited_wh"] >= 0
    assert is_valid_uuid(data["tariff_id"])


def assert_ledger_balances_consistent(entries: list, account: dict):
    """PRD §2.8: account balances are sums over the append-only ledger."""
    expected_credit = sum(e["amount_cents"] for e in entries)
    expected_banked = sum(
        e["quantity_wh"] for e in entries
        if e["entry_type"] in ("BANK_DEPOSIT", "BANK_DRAW", "BANK_FORFEIT"))
    assert account["credit_balance_cents"] == expected_credit, (
        f"credit_balance_cents {account['credit_balance_cents']} != "
        f"ledger sum {expected_credit}")
    assert account["banked_wh"] == expected_banked, (
        f"banked_wh {account['banked_wh']} != ledger sum {expected_banked}")
