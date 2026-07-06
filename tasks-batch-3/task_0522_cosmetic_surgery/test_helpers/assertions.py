"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_procedure(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["surgical_fee_cents"], int)
    assert isinstance(data["facility_fee_cents"], int)
    assert isinstance(data["anesthesia_fee_cents"], int)
    assert data["status"] in ("ACTIVE", "RETIRED")
    assert isinstance(data["active"], bool)


def assert_patient(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["surgical_risk_score"], int)
    assert 0 <= data["surgical_risk_score"] <= 100, "risk score clamped to [0,100]"
    assert data["clearance_tier"] in ("NONE", "STANDARD", "MEDICAL")


def assert_consultation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CONVERTED", "CLOSED")


def assert_quote_package(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("DRAFT", "PRESENTED", "ACCEPTED", "REJECTED", "EXPIRED")
    assert_quote_balance_identity(data)


def assert_quote_balance_identity(data: dict):
    """balance_due_cents == total_cents - deposit_paid_cents - financed_cents (PRD §2.6)."""
    expected = data["total_cents"] - data["deposit_paid_cents"] - data["financed_cents"]
    assert data["balance_due_cents"] == expected, (
        f"balance_due_cents {data['balance_due_cents']} != "
        f"total {data['total_cents']} - deposit {data['deposit_paid_cents']} "
        f"- financed {data['financed_cents']} = {expected}"
    )


def assert_line_item(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["bundle_total_cents"] == (
        data["surgical_fee_cents"] + data["facility_fee_cents"] + data["anesthesia_fee_cents"]
    ), "bundle_total_cents is the sum of the three snapshotted fees"
    # append-only: no version, no updated_at
    assert "version" not in data, "QuoteLineItem must not carry version"
    assert "updated_at" not in data, "QuoteLineItem must not carry updated_at"


def assert_consent(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ("PENDING", "SIGNED", "REVOKED")


def assert_clearance(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["tier_required"] in ("NONE", "STANDARD", "MEDICAL")
    assert data["status"] in ("ISSUED", "REVOKED")
    assert isinstance(data["cleared"], bool)


def assert_surgery_booking(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")


def assert_financing(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["lender"] in ("CARECREDIT", "CHERRY")
    assert data["status"] in ("SUBMITTED", "APPROVED", "DECLINED", "VOIDED")


def assert_complication_case(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["attribution"] in ("SURGICAL_ORIGIN", "PATIENT_FACTOR", "UNRELATED")
    assert data["status"] in ("OPEN", "UNDER_REVIEW", "REVISION_APPROVED", "RESOLVED")


def assert_deposit_conservation(booking: dict, deposit_paid_before: int):
    """forfeited + refunded == deposit paid before cancel (PRD §3.7, exact complement)."""
    assert (booking["deposit_forfeited_cents"] + booking["deposit_refunded_cents"]
            == deposit_paid_before), (
        f"forfeited {booking['deposit_forfeited_cents']} + refunded "
        f"{booking['deposit_refunded_cents']} != paid {deposit_paid_before}"
    )
