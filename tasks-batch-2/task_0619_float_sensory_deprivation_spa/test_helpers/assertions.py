"""Entity assertions and domain invariant checkers for the Float-Spa API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# ─── Common helpers ───────────────────────────────────────────────────────
def _assert_primary_record(data: dict):
    """Primary records carry id (bare UUID), created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def _assert_append_only_record(data: dict):
    """Append-only ledger records carry only id (UUID) and created_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


# ─── MembershipPlan ───────────────────────────────────────────────────────
def assert_plan(data: dict):
    _assert_primary_record(data)
    assert isinstance(data["tier"], str) and len(data["tier"]) > 0
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] >= 0
    assert isinstance(data["included_floats_per_cycle"], int) and data["included_floats_per_cycle"] >= 0
    assert isinstance(data["rollover_cap"], int) and data["rollover_cap"] >= 0
    assert 0.0 <= data["member_discount_pct"] <= 1.0
    assert isinstance(data["retail_float_cents"], int) and data["retail_float_cents"] > 0
    assert isinstance(data["active"], bool)


# ─── Member ───────────────────────────────────────────────────────────────
def assert_member(data: dict):
    _assert_primary_record(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["orientation_completed"], bool)
    assert isinstance(data["waiver_signed_version"], int)
    assert isinstance(data["no_show_strikes"], int) and data["no_show_strikes"] >= 0


# ─── Membership ───────────────────────────────────────────────────────────
def assert_membership(data: dict):
    _assert_primary_record(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["plan_id"])
    assert data["status"] in ("PENDING", "ACTIVE", "PAST_DUE", "CANCELLED")
    assert isinstance(data["credit_balance"], int)
    assert isinstance(data["cycle_index"], int) and data["cycle_index"] >= 0


def assert_membership_credit_nonnegative(data: dict):
    """§2.5 / §2.9: a membership's credit balance is never negative under valid play."""
    assert data["credit_balance"] >= 0, "credit_balance must never go negative"


# ─── Tank ─────────────────────────────────────────────────────────────────
def assert_tank(data: dict):
    _assert_primary_record(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["capacity_kind"] in ("SINGLE", "DUAL")
    assert isinstance(data["turnover_buffer_minutes"], int) and data["turnover_buffer_minutes"] >= 0
    assert data["operational_status"] in ("IN_SERVICE", "MAINTENANCE", "RETIRED")
    assert data["sanitation_status"] in ("CLEAN", "IN_CYCLE")


# ─── SanitationCycle ──────────────────────────────────────────────────────
def assert_sanitation_cycle(data: dict):
    _assert_primary_record(data)
    assert is_valid_uuid(data["tank_id"])
    assert data["kind"] in ("TURNOVER", "DEEP_CLEAN")
    assert data["status"] in ("IN_PROGRESS", "COMPLETED")
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] >= 0


# ─── Attendant ────────────────────────────────────────────────────────────
def assert_attendant(data: dict):
    _assert_primary_record(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["active"], bool)


# ─── Orientation ──────────────────────────────────────────────────────────
def assert_orientation(data: dict):
    _assert_primary_record(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["attendant_id"])
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")
    assert isinstance(data["waiver_version"], int) and data["waiver_version"] >= 1


# ─── Booking ──────────────────────────────────────────────────────────────
def assert_booking(data: dict):
    _assert_primary_record(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["tank_id"])
    assert data["session_minutes"] in (60, 90)
    assert isinstance(data["is_couples"], bool)
    assert data["status"] in (
        "RESERVED", "CONFIRMED", "RESCHEDULED", "CHECKED_IN",
        "COMPLETED", "CANCELLED", "NO_SHOW",
    )
    assert data["pay_source"] in ("CREDIT", "GIFT_CARD", "CASH")
    assert isinstance(data["deposit_cents"], int)
    assert isinstance(data["provisional_charge_cents"], int)
    assert isinstance(data["final_charge_cents"], int)
    assert isinstance(data["credits_consumed"], int)


# ─── GiftCard ─────────────────────────────────────────────────────────────
def assert_gift_card(data: dict):
    _assert_primary_record(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["initial_balance_cents"], int) and data["initial_balance_cents"] > 0
    assert isinstance(data["remaining_balance_cents"], int)
    assert data["status"] in ("ACTIVE", "DEPLETED", "VOID")


def assert_gift_card_balance_nonnegative(data: dict):
    """§2.5 / §2.9: a gift card's remaining balance is never negative under valid play."""
    assert data["remaining_balance_cents"] >= 0, "remaining_balance_cents must never go negative"


# ─── CreditLedgerEntry (append-only) ──────────────────────────────────────
def assert_credit_ledger_entry(data: dict):
    _assert_append_only_record(data)
    assert is_valid_uuid(data["membership_id"])
    assert data["reason"] in ("GRANT", "CONSUME", "FORFEIT", "EXPIRE")
    assert isinstance(data["delta"], int)
    # Append-only records must NOT carry updated_at / version.
    assert "updated_at" not in data, "CreditLedgerEntry must not carry updated_at"
    assert "version" not in data, "CreditLedgerEntry must not carry version"


# ─── Payment (append-only) ────────────────────────────────────────────────
def assert_payment(data: dict):
    _assert_append_only_record(data)
    assert data["kind"] in (
        "DEPOSIT_HOLD", "DEPOSIT_REFUND", "LATE_FEE",
        "NO_SHOW_FEE", "SESSION_CHARGE", "SESSION_REFUND",
    )
    assert data["source"] in ("GIFT_CARD", "CASH")
    assert isinstance(data["amount_cents"], int)
    assert "updated_at" not in data, "Payment must not carry updated_at"
    assert "version" not in data, "Payment must not carry version"


# ─── Ledger reconciliation invariant ──────────────────────────────────────
def assert_credit_balance_matches_ledger(membership: dict, ledger_entries: list):
    """§2.9: credit_balance == sum of all CreditLedgerEntry.delta for the membership."""
    ledger_sum = sum(e["delta"] for e in ledger_entries)
    assert membership["credit_balance"] == ledger_sum, (
        f"credit_balance {membership['credit_balance']} != ledger sum {ledger_sum}"
    )
