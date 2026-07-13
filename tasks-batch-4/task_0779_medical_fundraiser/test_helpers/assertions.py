"""Entity assertions and domain invariant checkers (PRD §2.4, §2.6)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version for full resources (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def _assert_journal(data: dict):
    """id + created_at only for immutable journal entries (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "journal entry must NOT carry updated_at"
    assert "version" not in data, "journal entry must NOT carry version"


def assert_organizer(data: dict):
    _assert_common(data)
    assert isinstance(data["display_name"], str)
    assert isinstance(data["email"], str)
    for f in ("total_dispute_count", "upheld_dispute_count", "refunded_amount_cents",
              "raised_cents", "strict_risk_score", "lenient_risk_score"):
        assert isinstance(data[f], int), f"{f} must be int"
    assert isinstance(data["has_unverified_beneficiary"], bool)
    assert 0 <= data["strict_risk_score"] <= 100, "strict_risk_score clamped to [0,100]"
    assert 0 <= data["lenient_risk_score"] <= 100, "lenient_risk_score clamped to [0,100]"


def assert_beneficiary(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str)
    assert data["verification_status"] in ("UNVERIFIED", "PENDING", "VERIFIED", "REJECTED")
    assert isinstance(data["withdrawal_ready"], bool)
    assert isinstance(data["total_paid_out_cents"], int)


def assert_donor(data: dict):
    _assert_common(data)
    assert isinstance(data["display_name"], str)
    assert isinstance(data["is_anonymous_default"], bool)


def assert_campaign(data: dict):
    _assert_common(data)
    assert data["lifecycle_status"] in ("DRAFT", "ACTIVE", "PAUSED", "COMPLETED", "CANCELLED")
    assert data["payout_posture"] in ("OPEN", "HOLD", "FROZEN")
    assert data["category"] in ("MEDICAL", "MEMORIAL", "EMERGENCY", "OTHER")
    assert data["tax_disclosure"] in ("TAX_DEDUCTIBLE", "NOT_TAX_DEDUCTIBLE")
    for f in ("goal_cents", "raised_cents", "reserve_total_cents", "committed_cents",
              "paid_out_cents", "disputed_locked_cents", "hold_locked_cents",
              "provisional_available_cents", "settled_available_cents"):
        assert isinstance(data[f], int), f"{f} must be int cents"


def assert_team_member(data: dict):
    _assert_common(data)
    assert data["team_role"] in ("OWNER", "CO_ORGANIZER", "WITHDRAWAL_MANAGER")
    assert data["status"] in ("ACTIVE", "REMOVED")


def assert_donation(data: dict):
    _assert_common(data)
    for f in ("amount_cents", "tip_cents", "processing_fee_cents", "total_charged_cents",
              "net_to_campaign_cents", "reserve_cents"):
        assert isinstance(data[f], int), f"{f} must be int cents"
    assert data["status"] in ("CAPTURED", "REFUNDED")
    assert data["tax_receipt_status"] in ("DEDUCTIBLE", "NON_DEDUCTIBLE")
    assert isinstance(data["thanked"], bool)


def assert_payout(data: dict):
    _assert_common(data)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in (
        "REQUESTED", "PROCESSING", "PAID", "ON_HOLD", "FAILED", "REVERSED", "CANCELLED"
    )


def assert_dispute(data: dict):
    _assert_common(data)
    assert data["reason"] in ("FRAUD", "UNAUTHORIZED", "NOT_AS_DESCRIBED", "OTHER")
    assert data["status"] in ("OPEN", "UNDER_REVIEW", "NEEDS_INFO", "UPHELD", "REJECTED")


def assert_hold(data: dict):
    _assert_common(data)
    assert data["severity"] in ("STANDARD", "CRITICAL")
    assert data["status"] in ("ACTIVE", "RELEASED")
    assert isinstance(data["locked_amount_cents"], int)


def assert_feature_placement(data: dict):
    _assert_common(data)
    assert data["category"] in ("HOMEPAGE", "MEDICAL", "EMERGENCY")
    assert data["status"] in ("BOOKED", "CANCELLED", "EXPIRED")
    assert isinstance(data["slot_index"], int)


def assert_update(data: dict):
    """Update/thank-you note is a journal entry (PRD §2.4)."""
    _assert_journal(data)
    assert data["update_type"] in ("UPDATE", "THANK_YOU")


def assert_refund(data: dict):
    """Refund is a journal entry (PRD §2.4)."""
    _assert_journal(data)
    assert data["reason"] in ("REQUESTED_BY_DONOR", "DISPUTE_UPHELD")
    assert isinstance(data["amount_cents"], int)


def assert_campaign_ledger_invariants(data: dict):
    """Money-field relationships that must hold on any campaign read (PRD §2.6)."""
    assert data["provisional_available_cents"] == (
        data["raised_cents"] - data["reserve_total_cents"] - data["committed_cents"]
    ), "provisional = raised - reserve_total - committed (PRD §2.6)"
    assert data["settled_available_cents"] == (
        data["provisional_available_cents"]
        - data["disputed_locked_cents"]
        - data["hold_locked_cents"]
    ), "settled = provisional - disputed_locked - hold_locked (PRD §2.6)"
