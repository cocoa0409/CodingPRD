"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates the shape of a returned resource against the PRD
field contract. Append-only entities (AuthorizedRecipient, LedgerEntry) are
checked WITHOUT updated_at/version, since the PRD declares those absent.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    LOCKER_SIZE_TIERS, MAILBOX_SIZE_TIERS, PACKAGE_SIZE_TIERS, CARRIERS,
    PRIMARY_ID_TYPES, ADDRESS_PROOF_TYPES, RECIPIENT_RELATIONSHIPS, MAIL_CLASSES,
    FORWARDING_KINDS, LEDGER_KINDS, LEDGER_REASONS, PAYMENT_METHODS,
)


def _assert_common(data: dict):
    """id + created_at + updated_at + version for common_fields entities."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive int, got {data.get('version')!r}"


def _assert_append_only(data: dict):
    """id + created_at only (no updated_at, no version)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_facility(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["time_zone"], str) and len(data["time_zone"]) > 0
    assert is_iso8601_timestamp(data["current_utc"]), "current_utc must be ISO 8601"
    assert isinstance(data["total_locker_count"], int) and data["total_locker_count"] >= 0
    assert isinstance(data["available_locker_count"], int) and data["available_locker_count"] >= 0


def assert_locker_unit(data: dict):
    _assert_common(data)
    assert isinstance(data["facility_id"], str)
    assert isinstance(data["label"], str) and len(data["label"]) > 0
    assert data["size_tier"] in LOCKER_SIZE_TIERS
    assert data["status"] in ["AVAILABLE", "OCCUPIED", "OUT_OF_SERVICE"]


def assert_mailbox_unit(data: dict):
    _assert_common(data)
    assert isinstance(data["facility_id"], str)
    assert isinstance(data["box_number"], str) and len(data["box_number"]) > 0
    assert data["size_tier"] in MAILBOX_SIZE_TIERS
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] >= 0
    assert data["status"] in ["VACANT", "RENTED", "OUT_OF_SERVICE"]


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["facility_id"], str)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_form_1583(data: dict):
    _assert_common(data)
    assert isinstance(data["facility_id"], str)
    assert isinstance(data["customer_id"], str)
    assert data["primary_id_type"] in PRIMARY_ID_TYPES
    assert data["address_proof_type"] in ADDRESS_PROOF_TYPES
    assert data["status"] in ["DRAFT", "SUBMITTED", "VERIFIED", "REJECTED"]
    assert isinstance(data["submission_count"], int) and data["submission_count"] >= 0


def assert_authorized_recipient(data: dict):
    _assert_append_only(data)
    assert isinstance(data["form_1583_id"], str)
    assert isinstance(data["recipient_name"], str) and len(data["recipient_name"]) > 0
    assert data["relationship"] in RECIPIENT_RELATIONSHIPS


def assert_rental_agreement(data: dict):
    _assert_common(data)
    assert isinstance(data["facility_id"], str)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["mailbox_unit_id"], str)
    assert isinstance(data["form_1583_id"], str)
    assert isinstance(data["term_months"], int) and data["term_months"] >= 1
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] >= 0
    assert isinstance(data["autopay_enabled"], bool)
    assert data["status"] in ["PENDING_AUTH", "ACTIVE", "SUSPENDED", "CLOSED", "ABANDONED"]
    assert isinstance(data["renewal_count"], int) and data["renewal_count"] >= 0


def assert_package(data: dict):
    _assert_common(data)
    assert isinstance(data["facility_id"], str)
    assert isinstance(data["rental_agreement_id"], str)
    assert data["carrier"] in CARRIERS
    assert data["size_tier"] in PACKAGE_SIZE_TIERS
    assert isinstance(data["longest_dim_cm"], int) and data["longest_dim_cm"] >= 1
    assert isinstance(data["weight_g"], int) and data["weight_g"] >= 1
    assert isinstance(data["oversize_fee_cents"], int) and data["oversize_fee_cents"] >= 0
    assert isinstance(data["overstay_fee_cents"], int) and data["overstay_fee_cents"] >= 0
    assert data["status"] in ["RECEIVED", "NOTIFIED", "PICKED_UP", "FORWARDED", "RETURNED", "ABANDONED"]


def assert_mail_item(data: dict):
    _assert_common(data)
    assert isinstance(data["rental_agreement_id"], str)
    assert data["mail_class"] in MAIL_CLASSES
    assert data["status"] in ["STORED", "SCANNED", "FORWARDED", "SHREDDED"]


def assert_forwarding_request(data: dict):
    _assert_common(data)
    assert isinstance(data["mail_item_id"], str)
    assert data["kind"] in FORWARDING_KINDS
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0
    assert data["status"] in ["REQUESTED", "ON_HOLD", "COMPLETED", "CANCELLED"]


def assert_invoice(data: dict):
    _assert_common(data)
    assert isinstance(data["rental_agreement_id"], str)
    assert isinstance(data["charges_total_cents"], int)
    assert isinstance(data["credits_total_cents"], int)
    assert isinstance(data["payments_total_cents"], int)
    assert isinstance(data["balance_cents"], int)
    assert data["status"] in ["OPEN", "SETTLED", "WRITTEN_OFF"]


def assert_ledger_entry(data: dict):
    _assert_append_only(data)
    assert isinstance(data["invoice_id"], str)
    assert data["kind"] in LEDGER_KINDS
    assert data["reason"] in LEDGER_REASONS
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0


def assert_payment(data: dict):
    _assert_common(data)
    assert isinstance(data["invoice_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["method"] in PAYMENT_METHODS
    assert data["status"] == "CAPTURED"


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_invoice_balance_identity(data: dict):
    """balance == charges - credits - payments (round-per-line-then-sum, PRD §3.6)."""
    expected = data["charges_total_cents"] - data["credits_total_cents"] - data["payments_total_cents"]
    assert data["balance_cents"] == expected, (
        f"balance_cents {data['balance_cents']} != charges {data['charges_total_cents']} "
        f"- credits {data['credits_total_cents']} - payments {data['payments_total_cents']}"
    )


def find_ledger_entries(entries: list, reason: str = None, kind: str = None) -> list:
    """Filter a ledger-entry list by reason and/or kind."""
    out = []
    for e in entries:
        if reason is not None and e.get("reason") != reason:
            continue
        if kind is not None and e.get("kind") != kind:
            continue
        out.append(e)
    return out
