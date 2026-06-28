"""Entity assertions and domain invariant checkers.

Append-only entities (GeoCheck, BetLeg, LedgerEntry) are asserted WITHOUT
updated_at / version, matching their PRD shape.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _versioned(data: dict):
    _common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_account(data: dict):
    _versioned(data)
    assert data["kyc_status"] in ("PENDING", "VERIFIED", "REJECTED")
    assert data["rg_status"] in ("ACTIVE", "COOLING_OFF", "SELF_EXCLUDED")
    assert isinstance(data["cash_balance_cents"], int)
    assert isinstance(data["bonus_balance_cents"], int)
    assert isinstance(data["lifetime_deposits_cents"], int)
    assert isinstance(data["email"], str) and data["email"]


def assert_rg_control(data: dict):
    _versioned(data)
    assert data["control_type"] in (
        "DEPOSIT_LIMIT", "WAGER_LIMIT", "NET_LOSS_LIMIT", "COOLING_OFF", "SELF_EXCLUSION"
    )
    assert data["status"] in ("ACTIVE", "SUPERSEDED")


def assert_event(data: dict):
    _versioned(data)
    assert data["status"] in ("SCHEDULED", "LIVE", "SETTLED", "VOIDED")
    assert data["sport"] in ("NFL", "NBA", "MLB", "SOCCER")


def assert_market(data: dict):
    _versioned(data)
    assert data["status"] in ("OPEN", "SUSPENDED", "SETTLED", "VOIDED")
    assert data["market_type"] in ("MONEYLINE", "SPREAD", "TOTAL")
    assert isinstance(data["liability_cap_cents"], int)
    assert isinstance(data["current_liability_cents"], int)


def assert_selection(data: dict):
    _versioned(data)
    assert data["result"] in ("PENDING", "WON", "LOST", "PUSH", "VOID")
    assert isinstance(data["american_odds"], int)
    assert abs(data["american_odds"]) >= 100, "american_odds magnitude must be >= 100"


def assert_bet(data: dict):
    _versioned(data)
    assert data["status"] in ("PLACED", "WON", "LOST", "PUSHED", "VOIDED", "CASHED_OUT")
    assert data["bet_type"] in ("SINGLE", "PARLAY", "SAME_GAME_PARLAY")
    assert data["stake_bucket"] in ("CASH", "BONUS")
    assert isinstance(data["stake_cents"], int)
    assert isinstance(data["potential_payout_cents"], int)
    assert isinstance(data["actual_payout_cents"], int)


def assert_promotion(data: dict):
    _versioned(data)
    assert data["status"] in ("ACTIVE", "EXHAUSTED", "ENDED")
    assert isinstance(data["bonus_cents"], int)
    assert isinstance(data["wagering_multiplier"], int) and data["wagering_multiplier"] >= 1
    assert isinstance(data["max_claims"], int) and data["max_claims"] >= 1


def assert_bonus_grant(data: dict):
    _versioned(data)
    assert data["status"] in ("ACTIVE", "COMPLETED", "FORFEITED")
    assert isinstance(data["wagering_target_cents"], int)
    assert isinstance(data["wagering_progress_cents"], int)


# --- Append-only entities: NO updated_at / version ---
def assert_geo_check(data: dict):
    _common(data)
    assert "version" not in data, "GeoCheck is append-only and must not carry version"
    assert "updated_at" not in data, "GeoCheck is append-only and must not carry updated_at"
    assert isinstance(data["eligible"], bool)
    assert is_iso8601_timestamp(data.get("expires_at", "")), "expires_at must be ISO 8601"


def assert_bet_leg(data: dict):
    _common(data)
    assert "version" not in data, "BetLeg is append-only and must not carry version"
    assert "updated_at" not in data, "BetLeg is append-only and must not carry updated_at"
    assert isinstance(data["odds_at_placement"], int)
    assert data["leg_result"] in ("PENDING", "WON", "LOST", "PUSH", "VOID")


def assert_ledger_entry(data: dict):
    _common(data)
    assert "version" not in data, "LedgerEntry is append-only and must not carry version"
    assert "updated_at" not in data, "LedgerEntry is append-only and must not carry updated_at"
    assert data["entry_type"] in (
        "DEPOSIT", "WITHDRAWAL", "STAKE", "PAYOUT", "BONUS_GRANT", "CASHOUT", "VOID_REFUND"
    )
    assert data["bucket"] in ("CASH", "BONUS")
    assert isinstance(data["amount_cents"], int)


def find_ledger_entry(entries, entry_type=None, bucket=None, amount_cents=None):
    """Return the first ledger entry in `entries` matching all supplied filters,
    or None. Used to verify a specific PAYOUT/STAKE/VOID_REFUND was posted."""
    for e in entries:
        if entry_type is not None and e.get("entry_type") != entry_type:
            continue
        if bucket is not None and e.get("bucket") != bucket:
            continue
        if amount_cents is not None and e.get("amount_cents") != amount_cents:
            continue
        return e
    return None
