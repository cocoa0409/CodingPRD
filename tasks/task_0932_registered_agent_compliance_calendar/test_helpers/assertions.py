"""Entity assertions, instant comparison, and domain invariant checkers."""
from datetime import datetime, timezone
from typing import Optional

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into an aware datetime.

    Accepts a trailing 'Z', an explicit numeric offset, and any number of
    fractional-second digits, so that two renderings of the same instant
    compare equal.
    """
    assert isinstance(value, str) and value, f"expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual, expected, label: str = "timestamp") -> None:
    """Compare two timestamps as instants, never as strings.

    Both sides are parsed into aware datetimes and compared by absolute
    instant, so '2026-06-08T10:00:00Z', '2026-06-08T10:00:00.000Z' and
    '2026-06-08T12:00:00+02:00' are all treated as equal.
    """
    assert actual is not None, f"{label} must not be null (expected {expected})"
    left = parse_instant(actual)
    right = parse_instant(expected)
    assert left == right, f"{label}: expected instant {expected}, got {actual}"


def assert_iso_date(value, label: str = "date") -> None:
    assert isinstance(value, str), f"{label} must be an ISO date string, got {value!r}"
    datetime.strptime(value, "%Y-%m-%d")


def assert_audit_fields(data: dict, label: str = "resource") -> None:
    """Every resource carries a bare-UUID id and an ISO 8601 created_at."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a bare UUID"
    assert "_" not in str(data.get("id", "")), f"{label}.id must carry no type prefix"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be an ISO 8601 timestamp"


def assert_versioned_fields(data: dict, label: str = "resource") -> None:
    """Resources that are not one of the three lean types carry updated_at + version."""
    assert_audit_fields(data, label)
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{label}.updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version starts at 1"


def assert_lean_resource(data: dict, label: str = "resource") -> None:
    """GoodStandingCertificate, PaymentAllocation and SopEscalationEvent carry
    only id and created_at — no updated_at and no version field at all."""
    assert_audit_fields(data, label)
    assert "updated_at" not in data, f"{label} must not carry updated_at"
    assert "version" not in data, f"{label} must not carry version"


# --- Per-entity assertions ---------------------------------------------------

def assert_client(data: dict) -> None:
    assert_versioned_fields(data, "Client")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["billing_email"], str) and data["billing_email"]
    assert isinstance(data["credit_balance_cents"], int)
    assert data["credit_balance_cents"] >= 0, "credit_balance_cents can never go negative"
    assert isinstance(data["portfolio_entity_count"], int)
    assert isinstance(data["portfolio_open_obligation_count"], int)
    assert isinstance(data["portfolio_outstanding_cents"], int)
    assert data["portfolio_delinquency_status"] in (
        "CURRENT", "DUE_SOON", "IN_GRACE", "DELINQUENT", "ADMIN_DISSOLVED",
    )
    assert isinstance(data["sop_open_escalation_count"], int)
    assert isinstance(data["portfolio_risk_flag"], bool)


def assert_legal_entity(data: dict) -> None:
    assert_versioned_fields(data, "LegalEntity")
    assert data["entity_type"] in ("LLC", "CORP", "LP", "LLP", "NONPROFIT")
    assert data["lifecycle_status"] in ("DRAFT", "ACTIVE", "WINDING_DOWN", "DISSOLVED")
    assert data["boi_status"] in (
        "NOT_REQUIRED", "PENDING_INITIAL", "FILED", "UPDATE_DUE", "DELINQUENT",
    )
    assert data["boi_exempt_class"] in (
        "NONE", "LARGE_OPERATING", "PUBLICLY_TRADED", "BANK", "TAX_EXEMPT",
    )
    assert isinstance(data["company_applicant_required"], bool)
    assert isinstance(data["final_report_required"], bool)
    assert data["compliance_posture"] in (
        "CURRENT", "DUE_SOON", "IN_GRACE", "DELINQUENT", "ADMIN_DISSOLVED",
    )


def assert_registration(data: dict) -> None:
    assert_versioned_fields(data, "Registration")
    assert data["registration_kind"] in ("HOME", "FOREIGN")
    assert data["status"] in (
        "PENDING", "ACTIVE", "DELINQUENT", "ADMIN_DISSOLVED",
        "WITHDRAWN", "TERMINATED", "CLOSED_PERMANENT",
    )
    assert isinstance(data["delinquency_rank"], int)
    assert 0 <= data["delinquency_rank"] <= 4
    assert isinstance(data["sop_priority_hold"], bool)
    assert len(data["state_code"]) == 2 and data["state_code"].isupper()


def assert_compliance_obligation(data: dict) -> None:
    assert_versioned_fields(data, "ComplianceObligation")
    assert data["obligation_type"] in (
        "ANNUAL_REPORT", "FRANCHISE_TAX", "BOI_INITIAL", "BOI_UPDATE", "FINAL_REPORT",
    )
    assert data["status"] in (
        "SCHEDULED", "DUE_SOON", "IN_GRACE", "DELINQUENT",
        "SATISFIED", "WAIVED", "VOIDED",
    )
    assert_iso_date(data["due_date"], "ComplianceObligation.due_date")
    assert_iso_date(data["grace_end_date"], "ComplianceObligation.grace_end_date")
    assert_iso_date(data["delinquency_date"], "ComplianceObligation.delinquency_date")
    assert_obligation_total(data)


def assert_obligation_total(data: dict) -> None:
    """total_due_cents is state_fee_cents plus franchise_tax_cents plus
    late_fee_cents plus service_fee_cents."""
    expected = (
        data["state_fee_cents"]
        + data["franchise_tax_cents"]
        + data["late_fee_cents"]
        + data["service_fee_cents"]
    )
    assert data["total_due_cents"] == expected, (
        f"total_due_cents {data['total_due_cents']} must equal the sum of its four "
        f"components ({expected})"
    )


def assert_filing(data: dict) -> None:
    assert_versioned_fields(data, "Filing")
    assert data["filing_kind"] in (
        "ANNUAL_REPORT", "FRANCHISE_TAX", "FOREIGN_QUALIFICATION", "WITHDRAWAL",
        "DISSOLUTION", "REINSTATEMENT", "FINAL_REPORT",
    )
    assert data["expedite_tier"] in ("NONE", "STANDARD", "RUSH", "SAME_DAY")
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED", "ABANDONED")
    assert isinstance(data["attempt_number"], int) and data["attempt_number"] >= 1
    assert_filing_total(data)


def assert_filing_total(data: dict) -> None:
    """total_fee_cents is the sum of the two portions."""
    assert data["total_fee_cents"] == (
        data["state_portion_cents"] + data["service_portion_cents"]
    ), "total_fee_cents must equal state_portion_cents + service_portion_cents"


def assert_payment(data: dict) -> None:
    assert_versioned_fields(data, "Payment")
    assert data["status"] in (
        "AUTHORIZED", "CAPTURED", "PARTIALLY_REFUNDED", "REFUNDED", "VOIDED",
    )
    assert_payment_identity(data)


def assert_payment_identity(data: dict) -> None:
    """captured_amount_cents equals the sum of allocated_amount_cents,
    unallocated_amount_cents and refunded_amount_cents, as exact integers."""
    total = (
        data["allocated_amount_cents"]
        + data["unallocated_amount_cents"]
        + data["refunded_amount_cents"]
    )
    assert data["captured_amount_cents"] == total, (
        f"payment identity broken: captured {data['captured_amount_cents']} != "
        f"allocated {data['allocated_amount_cents']} + unallocated "
        f"{data['unallocated_amount_cents']} + refunded {data['refunded_amount_cents']}"
    )


def assert_allocation_split(row: dict) -> None:
    """state_portion_cents and service_portion_cents sum to exactly amount_cents."""
    assert row["state_portion_cents"] + row["service_portion_cents"] == row[
        "amount_cents"
    ], "allocation split identity broken"


def assert_sop_document(data: dict) -> None:
    assert_versioned_fields(data, "SopDocument")
    assert data["sop_class"] in ("ORDINARY", "LITIGATION")
    assert data["status"] in (
        "RECEIVED", "SCANNED", "FORWARDED", "ESCALATED",
        "ACKNOWLEDGED", "REJECTED_NOT_OUR_ENTITY",
    )
    assert isinstance(data["escalation_level"], int)
    assert 0 <= data["escalation_level"] <= 3
    assert isinstance(data["deferred"], bool)
    assert isinstance(data["deferral_count"], int)
    assert isinstance(data["forwarded_late"], bool)


def assert_boi_report(data: dict) -> None:
    assert_versioned_fields(data, "BoiReport")
    assert data["report_kind"] in ("INITIAL", "UPDATED")
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED")
    assert isinstance(data["includes_company_applicant"], bool)
    assert isinstance(data["owner_snapshot_count"], int)


def assert_reinstatement_case(data: dict) -> None:
    assert_versioned_fields(data, "ReinstatementCase")
    assert data["status"] in (
        "OPEN", "FEES_ASSESSED", "PAID", "FILED", "GRANTED", "DENIED", "EXPIRED",
    )
    assert isinstance(data["missed_period_count"], int)
    assert isinstance(data["back_fee_total_cents"], int)
    assert isinstance(data["obligations_cured_count"], int)


def assert_agent_appointment(data: dict) -> None:
    assert_versioned_fields(data, "AgentAppointment")
    assert data["status"] in (
        "PROPOSED", "APPOINTED", "RESIGNATION_NOTICED",
        "RESIGNED", "TRANSFERRED_OUT", "REJECTED",
    )
    assert isinstance(data["of_record"], bool)


def find_by_id(rows, row_id: str) -> Optional[dict]:
    """Locate one row of a list response by its id, without relying on order."""
    for row in rows:
        if row.get("id") == row_id:
            return row
    return None


def count_of_record(appointments) -> int:
    return sum(1 for a in appointments if a.get("of_record") is True)
