"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert data["verification_status"] in ("UNVERIFIED", "VERIFIED")
    assert data["active_membership_tier"] in ("BASIC", "PLUS", "PREMIER", None)
    assert isinstance(data["settled_points_balance"], int)
    assert isinstance(data["available_points_balance"], int)
    assert isinstance(data["trust_score"], int)
    assert 0 <= data["trust_score"] <= 100, "trust_score must be within [0, 100]"
    assert isinstance(data["completed_exchange_count"], int)
    assert isinstance(data["upheld_damage_count"], int)
    assert isinstance(data["disputes_lost_count"], int)


def assert_membership(data: dict):
    _assert_common(data)
    assert data["tier"] in ("BASIC", "PLUS", "PREMIER")
    assert data["status"] in ("PENDING_ACTIVATION", "ACTIVE", "EXPIRED", "CANCELLED")


def assert_home_listing(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ACTIVE")
    assert isinstance(data["points_per_night"], int) and data["points_per_night"] >= 1
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert 0 <= data["min_trust_score"] <= 100


def assert_availability_window(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "BOOKED")
    assert isinstance(data["nights"], int) and data["nights"] >= 1


def assert_verification(data: dict):
    _assert_common(data)
    assert data["verification_type"] in ("IDENTITY", "HOME")
    assert data["status"] in ("PENDING_REVIEW", "VERIFIED", "REJECTED")


def assert_exchange_request(data: dict):
    _assert_common(data)
    assert data["exchange_type"] in ("POINTS", "RECIPROCAL")
    assert data["status"] in ("PROPOSED", "COUNTERED", "ACCEPTED", "DECLINED", "WITHDRAWN", "EXPIRED")
    assert isinstance(data["points_cost"], int)


def assert_exchange_agreement(data: dict):
    _assert_common(data)
    assert data["exchange_type"] in ("POINTS", "RECIPROCAL")
    assert data["status"] in ("PENDING_CONFIRMATION", "CONFIRMED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    assert data["insurance_status"] in ("NONE", "ACTIVE", "CLAIMED")
    assert isinstance(data["points_cost"], int)


def assert_ledger_entry(data: dict):
    """PointsLedgerEntry is append-only: only id and created_at as lifecycle fields."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only ledger entry must not carry updated_at"
    assert "version" not in data, "append-only ledger entry must not carry version"
    assert data["entry_type"] in (
        "WELCOME_BONUS", "ADMIN_ADJUSTMENT", "EXCHANGE_HOLD", "EXCHANGE_DEBIT",
        "EXCHANGE_CREDIT", "EXCHANGE_REFUND", "CREDIT_REVERSAL",
        "DAMAGE_SETTLEMENT", "DISPUTE_PENALTY",
    )
    assert data["status"] in ("HELD", "POSTED", "VOIDED")
    assert isinstance(data["amount"], int)


def assert_damage_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ("FILED", "SETTLED", "REJECTED")


def assert_dispute(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "UNDER_REVIEW", "RESOLVED_FOR_CLAIMANT",
                              "RESOLVED_FOR_RESPONDENT", "WITHDRAWN")


def find_ledger_entry(entries: list, entry_type: str, amount=None, status=None):
    """Return the first ledger entry matching type (and optionally amount/status)."""
    for e in entries:
        if e.get("entry_type") != entry_type:
            continue
        if amount is not None and e.get("amount") != amount:
            continue
        if status is not None and e.get("status") != status:
            continue
        return e
    return None
