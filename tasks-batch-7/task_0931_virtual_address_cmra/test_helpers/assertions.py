"""Entity assertions, instant comparison and domain invariant checkers."""

import re
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

BARE_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
CALENDAR_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --------------------------------------------------------------------------
# Instants
# --------------------------------------------------------------------------
def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant into a timezone-aware datetime.

    Accepts a trailing `Z`, an explicit `+00:00` offset and any number of
    fractional digits, so that comparison is semantic rather than textual.
    """
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected: str, label: str = "instant") -> None:
    """Compare two instants by the moment they denote, never as strings."""
    assert actual is not None, f"{label}: expected {expected}, got null"
    got = parse_instant(actual)
    want = parse_instant(expected)
    assert got == want, f"{label}: expected instant {expected}, got {actual}"


def assert_is_instant(value: str, label: str = "instant") -> None:
    assert isinstance(value, str), f"{label} must be an ISO 8601 string, got {value!r}"
    parse_instant(value)
    assert is_iso8601_timestamp(value), f"{label} must be ISO 8601, got {value!r}"


def assert_is_calendar_date(value: str, label: str = "date") -> None:
    assert isinstance(value, str) and CALENDAR_DATE_RE.match(value), (
        f"{label} must be a plain YYYY-MM-DD string, got {value!r}"
    )


def assert_bare_uuid(value: str, label: str = "id") -> None:
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert BARE_UUID_RE.match(value), f"{label} must be a bare UUID with no prefix, got {value!r}"
    assert is_valid_uuid(value), f"{label} must be a valid UUID, got {value!r}"


# --------------------------------------------------------------------------
# Common shapes
# --------------------------------------------------------------------------
def assert_common_fields(data: dict, entity: str) -> None:
    """Resources that carry id, created_at, updated_at and version (PRD §2.4)."""
    assert_bare_uuid(data.get("id"), f"{entity}.id")
    assert_is_instant(data.get("created_at"), f"{entity}.created_at")
    assert_is_instant(data.get("updated_at"), f"{entity}.updated_at")
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"
    assert data["version"] >= 1, f"{entity}.version starts at 1"


def assert_append_only_fields(data: dict, entity: str) -> None:
    """Resources that carry only id and created_at (PRD §2.4)."""
    assert_bare_uuid(data.get("id"), f"{entity}.id")
    assert_is_instant(data.get("created_at"), f"{entity}.created_at")
    assert "updated_at" not in data, f"{entity} must not carry updated_at"
    assert "version" not in data, f"{entity} must not carry version"


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------
def assert_plan_tier(data: dict) -> None:
    assert_append_only_fields(data, "plan tier")
    assert data["tier_code"] in ("BASIC", "PLUS", "BUSINESS", "ENTERPRISE")
    assert isinstance(data["name"], str) and data["name"]
    assert 1 <= data["rank"] <= 4
    assert data["monthly_fee_cents"] >= 0
    assert data["included_recipients"] >= 1
    for field in (
        "included_scan_pages",
        "included_forwards",
        "included_storage_days",
        "overage_scan_page_cents",
        "overage_forward_cents",
        "overage_storage_day_cents",
        "overage_recipient_cents",
    ):
        assert data[field] >= 0, f"plan tier {field} must be zero or more"
    assert isinstance(data["allows_overage"], bool)


def assert_carrier_rule(data: dict) -> None:
    assert_append_only_fields(data, "carrier rule")
    assert data["carrier_code"] in ("USPS", "UPS", "FEDEX", "DHL", "AMAZON")
    assert data["dim_divisor"] >= 1
    assert data["max_length_plus_girth_in"] > 0
    assert data["max_actual_weight_lb"] > 0
    assert isinstance(data["accepts_signature_required"], bool)
    assert data["acceptance_fee_cents"] >= 0
    assert data["base_rate_cents_per_lb"] >= 0


def assert_box(data: dict) -> None:
    assert_common_fields(data, "mailbox")
    assert isinstance(data["box_number"], str) and data["box_number"]
    assert data["service_status"] in (
        "PENDING_SETUP",
        "ACTIVE",
        "SUSPENDED",
        "CLOSING",
        "CLOSED",
    )
    assert data["compliance_status"] in ("COMPLIANT", "UNDER_REVIEW", "NON_COMPLIANT")
    assert data["suspended_reason"] in ("NONE", "COMPLIANCE_REVIEW", "USPS_ORDER")
    assert data["release_gate_state"] in ("OPEN", "GATED_SUSPENDED", "GATED_LIFECYCLE")
    assert data["security_deposit_cents"] >= 0
    assert data["extra_recipient_slots"] >= 0
    assert data["prepaid_balance_cents"] >= 0


def assert_recipient(data: dict) -> None:
    assert_common_fields(data, "roster member")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["recipient_kind"] in ("INDIVIDUAL", "BUSINESS", "MINOR")
    assert isinstance(data.get("dba_aliases", []), list)
    assert data["roster_status"] in ("PENDING", "AUTHORIZED", "SUSPENDED", "REMOVED")
    assert data["release_eligibility"] in ("BLOCKED", "RELEASABLE")
    assert data["blocked_reason"] in (
        "NONE",
        "NO_ACCEPTED_1583",
        "ID_SET_INCOMPLETE",
        "ID_EXPIRED",
        "GUARANTOR_BLOCKED",
        "ROSTER_NOT_AUTHORIZED",
    )
    assert isinstance(data.get("signature_authorization_on_file", False), bool)


def assert_form_1583(data: dict) -> None:
    assert_common_fields(data, "Form 1583")
    assert data["status"] in ("DRAFT", "NOTARIZED", "ACCEPTED", "REJECTED", "EXPIRED")
    assert isinstance(data["home_address_line"], str) and data["home_address_line"]


def assert_id_document(data: dict) -> None:
    assert_common_fields(data, "identification document")
    assert data["doc_class"] in ("PHOTO", "ADDRESS")
    assert data["doc_type"] in (
        "DRIVERS_LICENSE",
        "PASSPORT",
        "STATE_ID",
        "UTILITY_BILL",
        "LEASE",
        "VOTER_CARD",
        "VEHICLE_REGISTRATION",
    )
    assert data["status"] in ("PENDING_REVIEW", "VERIFIED", "EXPIRED", "SUPERSEDED")
    assert_is_calendar_date(data["expires_on"], "identification document expires_on")


def assert_mail_item(data: dict) -> None:
    assert_common_fields(data, "mail item")
    assert data["item_class"] in ("LETTER", "FLAT", "PACKAGE", "SOP")
    assert data["handling_status"] in (
        "RECEIVED",
        "AWAITING_CLEARANCE",
        "HELD",
        "PENDING_DISPOSITION",
        "FORWARDED",
        "SHREDDED",
        "DEPOSITED",
        "RETURNED",
        "REFUSED",
    )
    assert data["storage_status"] in ("FREE_WINDOW", "ACCRUING", "RELEASED", "DESTROYED")
    assert data["billing_status"] in ("UNBILLED", "METERED", "BILLED", "WRITTEN_OFF")
    assert data["notification_status"] in ("NOT_REQUIRED", "PENDING", "SENT", "BREACHED")
    assert_is_instant(data["received_at"], "mail item received_at")
    assert isinstance(data["addressee_name"], str) and data["addressee_name"]


def assert_scan_job(data: dict) -> None:
    assert_common_fields(data, "scan job")
    assert data["scan_tier"] in ("COVER", "INTERIOR", "OCR")
    assert data["status"] in (
        "QUEUED",
        "IN_PROGRESS",
        "COMPLETED",
        "FAILED",
        "ABANDONED",
    )
    assert data["split_index"] >= 1
    assert data["split_group_size"] >= 1
    assert 1 <= data["page_count"] <= 25
    assert 0 <= data["retry_count"] <= 2


def assert_disposition_request(data: dict) -> None:
    assert_common_fields(data, "disposition request")
    assert data["disposition_type"] in ("FORWARD", "SHRED", "DEPOSIT", "RETURN")
    assert data["status"] in ("PENDING", "EXECUTED", "CANCELLED", "SUPERSEDED")
    assert data["resolution_reason"] in (
        "NONE",
        "EXECUTED",
        "LOST_PRECEDENCE",
        "GATE_SUSPENSION",
        "HOLDER_CANCELLED",
    )
    assert data["precedence_rank"] in (1, 2, 3, 4)


def assert_forward_shipment(data: dict) -> None:
    assert_common_fields(data, "forward shipment")
    assert data["service_level"] in ("ECONOMY", "PRIORITY", "EXPRESS")
    assert data["status"] in ("PRICED", "SHIPPED", "CANCELLED")
    assert data["item_count"] >= 0
    assert data["excluded_item_count"] >= 0
    assert data["base_price_cents"] >= 0
    assert data["consolidation_discount_cents"] >= 0
    assert data["total_price_cents"] >= 0


def assert_check_deposit(data: dict) -> None:
    assert_common_fields(data, "check deposit")
    assert data["status"] in ("RECEIVED", "MATCHED", "DEPOSITED", "HELD", "RETURNED")
    assert data["match_mode"] in ("NONE", "EXACT_LEGAL", "ALIAS")
    assert data["hold_reason"] in ("NONE", "PAYEE_MISMATCH", "NOT_ENDORSED")
    assert data["amount_cents"] >= 1


def assert_deposit_batch(data: dict) -> None:
    assert_common_fields(data, "deposit batch")
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["closed"], bool)
    assert_is_calendar_date(data["business_date"], "deposit batch business_date")
    assert_deposit_money_partition(data)


def assert_registered_agent_service(data: dict) -> None:
    assert_common_fields(data, "registered-agent add-on")
    assert isinstance(data["active"], bool)
    assert data["retention_days"] >= 1
    assert re.match(r"^[A-Z]{2}$", data["jurisdiction_code"])


def assert_compliance_review(data: dict) -> None:
    assert_common_fields(data, "compliance review")
    assert data["reason"] in ("ID_EXPIRY", "USPS_AUDIT", "ROSTER_ANOMALY", "PAYMENT")
    assert data["status"] in ("OPEN", "SUSPENDED", "RESOLVED")
    assert data["resolution"] in ("NONE", "CLEARED", "ESCALATED_CLOSURE")


def assert_billing_cycle(data: dict) -> None:
    assert_common_fields(data, "billing cycle")
    assert data["status"] in ("OPEN", "CLOSING", "CLOSED")
    assert data["cycle_index"] >= 1
    assert_is_calendar_date(data["period_start"], "billing cycle period_start")
    assert_is_calendar_date(data["period_end"], "billing cycle period_end")
    for counter in (
        "scan_pages_consumed",
        "forwards_consumed",
        "storage_days_consumed",
        "recipients_consumed",
    ):
        assert data[counter] >= 0, f"billing cycle {counter} must be zero or more"


def assert_usage_ledger_entry(data: dict) -> None:
    assert_append_only_fields(data, "usage-ledger entry")
    assert data["unit_type"] in ("SCAN_PAGE", "FORWARD", "STORAGE_DAY", "RECIPIENT")
    assert data["tranche"] in ("IN_TIER", "OVERAGE")
    assert data["quantity"] >= 1
    assert data["source_event"] in (
        "SCAN_COMPLETED",
        "FORWARD_SHIPPED",
        "STORAGE_ACCRUAL",
        "RECIPIENT_AUTHORIZED",
        "PLAN_CHANGE",
    )
    assert data["amount_cents"] == data["quantity"] * data["unit_rate_cents"], (
        "a usage-ledger entry's amount_cents is its quantity times its unit_rate_cents"
    )
    if data["tranche"] == "IN_TIER":
        assert data["unit_rate_cents"] == 0, "an IN_TIER entry carries unit_rate_cents 0"


def assert_cancellation_request(data: dict) -> None:
    assert_common_fields(data, "cancellation request")
    assert data["status"] in ("REQUESTED", "FINAL_FORWARD", "FINALIZED", "WITHDRAWN")
    for field in (
        "requested_on",
        "notice_end_date",
        "final_forward_deadline",
        "abandonment_date",
        "destruction_eligible_on",
    ):
        assert_is_calendar_date(data[field], f"cancellation request {field}")


# --------------------------------------------------------------------------
# Conservation invariants (PRD §2.11)
# --------------------------------------------------------------------------
def assert_deposit_money_partition(batch: dict) -> None:
    assert batch["received_amount_cents"] == (
        batch["deposited_amount_cents"]
        + batch["returned_amount_cents"]
        + batch["held_amount_cents"]
    ), (
        "received_amount_cents must equal deposited + returned + held: "
        f"{batch['received_amount_cents']} != {batch['deposited_amount_cents']} + "
        f"{batch['returned_amount_cents']} + {batch['held_amount_cents']}"
    )


def assert_refund_waterfall_conservation(cancellation: dict) -> None:
    total = (
        cancellation["refund_total_cents"]
        + cancellation["applied_to_overage_cents"]
        + cancellation["forfeited_cents"]
    )
    pool = (
        cancellation["prepaid_at_request_cents"] + cancellation["deposit_held_cents"]
    )
    assert total == pool, (
        "refund_total_cents + applied_to_overage_cents + forfeited_cents must equal "
        f"prepaid_at_request_cents + deposit_held_cents: {total} != {pool}"
    )


def assert_custody_cardinality(summary: dict, total_pieces: int) -> None:
    got = (
        summary["items_in_custody"]
        + summary["items_released"]
        + summary["items_destroyed"]
    )
    assert got == total_pieces, (
        "items_in_custody + items_released + items_destroyed must equal the mailbox's "
        f"piece count: {got} != {total_pieces}"
    )


def assert_storage_day_partition(item: dict, total_custody_days: int) -> None:
    got = item["free_storage_days_used"] + item["billable_storage_days"]
    assert got == total_custody_days, (
        "free_storage_days_used + billable_storage_days must equal total custody days: "
        f"{got} != {total_custody_days}"
    )
