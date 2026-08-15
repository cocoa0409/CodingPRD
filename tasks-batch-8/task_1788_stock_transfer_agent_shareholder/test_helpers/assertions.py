"""Entity assertions and domain invariant checkers.

Structural checks only (identity, timestamps, enum membership, money types);
value pinning lives in the tests themselves.
"""
import re

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def _assert_money(data: dict, *fields):
    for f in fields:
        if data.get(f) is not None:
            assert isinstance(data[f], int), f"{f} must be integer cents"


def assert_issuer(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["cusip"], str) and data["cusip"]
    _assert_money(data, "par_value_cents", "current_market_price_cents")
    assert isinstance(data["shares_outstanding"], int)
    assert isinstance(data["total_book_entry_shares"], int)
    assert isinstance(data["total_certificated_shares"], int)


def assert_account(data: dict):
    _assert_common(data)
    assert data["account_status"] in ("ACTIVE", "RESTRICTED", "DORMANT", "ESCHEATED")
    assert data["residency"] in ("US", "FOREIGN")
    assert data["tin_status"] in ("MISSING", "CERTIFIED", "UNCERTIFIED")
    assert data["treaty_tier"] in ("STANDARD", "TREATY")
    assert isinstance(data["holder_name"], str) and data["holder_name"]
    assert isinstance(data["address_verified"], bool)
    assert isinstance(data["pending_transfer_count"], int)
    assert isinstance(data["stale_dividend_cents"], int)
    assert is_iso8601_timestamp(data["last_qualifying_contact_date"])


def assert_position(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "CLOSED")
    for f in ("book_entry_shares", "restricted_shares", "certificated_shares",
              "total_shares", "pending_legend_removal_count"):
        assert isinstance(data[f], int), f"{f} must be an integer"
    assert data["total_shares"] == data["book_entry_shares"] + data["certificated_shares"], \
        "total_shares is the sum of the two holding forms"
    assert 0 <= data["restricted_shares"] <= data["book_entry_shares"], \
        "restricted_shares stays within the book-entry leg"


def assert_certificate(data: dict):
    _assert_common(data)
    assert data["status"] in ("ISSUED", "LOST_REPORTED", "REPLACED", "CANCELLED")
    assert isinstance(data["share_quantity"], int) and data["share_quantity"] >= 1
    assert isinstance(data["certificate_number"], str) and data["certificate_number"]
    assert isinstance(data["legend_restricted"], bool)
    assert is_iso8601_timestamp(data["issued_at"])


def assert_transfer_request(data: dict):
    _assert_common(data)
    assert data["status"] in ("UNDER_REVIEW", "MEDALLION_VERIFIED", "DEFICIENT",
                              "APPROVED", "SETTLED", "REJECTED", "CANCELLED")
    assert isinstance(data["share_quantity"], int) and data["share_quantity"] >= 1
    _assert_money(data, "transfer_value_cents", "medallion_coverage_cents")


def assert_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ("FILED", "BOND_POSTED", "APPROVED", "REPLACED",
                              "REJECTED", "WITHDRAWN")
    assert isinstance(data["loss_report_price_cents"], int)
    _assert_money(data, "bond_amount_cents", "required_premium_cents",
                  "premium_paid_cents")


def assert_declaration(data: dict):
    _assert_common(data)
    assert data["status"] in ("DECLARED", "ACCRUED", "PAYABLE", "CLOSED", "VOIDED")
    assert isinstance(data["amount_per_share_millicents"], int)
    assert isinstance(data["total_eligible_shares"], int)
    assert isinstance(data["total_accrued_cents"], int)


def assert_payment(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACCRUED", "DISBURSED", "RECONCILED", "RETURNED",
                              "STALE_DATED", "ESCHEATED")
    assert isinstance(data["eligible_shares"], int)
    _assert_money(data, "gross_cents", "provisional_withholding_cents",
                  "withholding_cents", "net_cents")


def assert_legend_request(data: dict):
    _assert_common(data)
    assert data["status"] in ("SUBMITTED", "OPINION_UNDER_REVIEW", "DEFICIENT",
                              "LEGEND_REMOVED", "REJECTED")
    assert data["rule_basis"] == "RULE_144"
    assert isinstance(data["share_quantity"], int) and data["share_quantity"] >= 1


def assert_case(data: dict):
    _assert_common(data)
    assert data["status"] in ("IDENTIFIED", "NOTICE_SENT", "REPORTED", "REMITTED",
                              "REACTIVATED")
    assert is_iso8601_timestamp(data["dormancy_start_date"])
    _assert_money(data, "report_price_cents", "share_value_cents",
                  "cash_value_cents", "total_remit_cents")


def assert_inquiry(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "IN_REVIEW", "ANSWERED", "CLOSED")
    assert data["channel"] in ("PHONE", "MAIL", "EMAIL")


def assert_freeze_window(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "ACTIVE", "EXPIRED")
    assert is_iso8601_timestamp(data["start_date"])
    assert is_iso8601_timestamp(data["end_date"])


def assert_audit_event(data: dict):
    """Append-only: carries only id + created_at from the standard set."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert "updated_at" not in data, "AuditEvent must not carry updated_at"
    assert "version" not in data, "AuditEvent must not carry version"
    assert isinstance(data["entity_type"], str) and data["entity_type"]
    assert isinstance(data["entity_id"], str) and data["entity_id"]
    assert isinstance(data["actor_role"], str) and data["actor_role"]
    assert isinstance(data["action"], str) and data["action"]
    assert isinstance(data["prev_entry_hash"], str) and data["prev_entry_hash"]
    assert _HEX64.match(data.get("entry_hash", "")), \
        "entry_hash must be a SHA-256 hex digest"


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------

def assert_payment_money_conserved(payment: dict):
    """Per-row cash identity: gross == net + withholding."""
    assert payment["gross_cents"] == payment["net_cents"] + payment["withholding_cents"], (
        f"gross {payment['gross_cents']} != net {payment['net_cents']} "
        f"+ withholding {payment['withholding_cents']}"
    )


def assert_issuer_conservation(issuer: dict):
    """Register conservation: issuer aggregates sum back to shares_outstanding
    when the seeded positions cover the full issuance."""
    total = issuer["total_book_entry_shares"] + issuer["total_certificated_shares"]
    assert total == issuer["shares_outstanding"], (
        f"issuer totals {total} drifted from shares_outstanding "
        f"{issuer['shares_outstanding']}"
    )
