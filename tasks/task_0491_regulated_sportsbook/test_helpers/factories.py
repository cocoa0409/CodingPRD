"""Payload factories — one per create endpoint, input fields only.

Field names are PRD-exact. Required fields per the PRD are always present;
optional fields (stake_bucket, bonus_grant_id, is_vpn_suspected, line, period,
limit_cents, duration_days, min_odds_american) are only included when provided.
"""

DEFAULTS = {
    "DOB_ADULT": "1980-01-01",     # age 46 at the 2026-01-01 default clock
    "RESIDENCE_STATE": "NJ",
    "DEPOSIT_CENTS": 100_000,
    "STAKE_CENTS": 5_000,
    "STARTS_AT": "2026-02-01T18:00:00Z",
    "LIABILITY_CAP_CENTS": 90_000_000,
}

_email_counter = [0]


def _unique_email(prefix: str = "acct") -> str:
    _email_counter[0] += 1
    return f"{prefix}{_email_counter[0]}@example.com"


def create_account_payload(**overrides) -> dict:
    defaults = {
        "email": _unique_email(),
        "full_name": "Test Bettor",
        "date_of_birth": DEFAULTS["DOB_ADULT"],
        "residence_state": DEFAULTS["RESIDENCE_STATE"],
    }
    defaults.update(overrides)
    return defaults


def kyc_decision_payload(decision: str, expected_account_version: int, **overrides) -> dict:
    defaults = {"decision": decision, "expected_account_version": expected_account_version}
    defaults.update(overrides)
    return defaults


def rg_control_payload(control_type: str, expected_account_version: int, **overrides) -> dict:
    defaults = {"control_type": control_type, "expected_account_version": expected_account_version}
    defaults.update(overrides)
    return defaults


def deposit_payload(amount_cents: int, expected_account_version: int, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents, "expected_account_version": expected_account_version}
    defaults.update(overrides)
    return defaults


def withdrawal_payload(amount_cents: int, expected_account_version: int, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents, "expected_account_version": expected_account_version}
    defaults.update(overrides)
    return defaults


def geo_check_payload(detected_state: str = "NJ", accuracy_meters: int = 20, **overrides) -> dict:
    defaults = {"detected_state": detected_state, "accuracy_meters": accuracy_meters}
    defaults.update(overrides)
    return defaults


def event_payload(**overrides) -> dict:
    defaults = {
        "sport": "NBA",
        "home_team": "Home",
        "away_team": "Away",
        "starts_at": DEFAULTS["STARTS_AT"],
    }
    defaults.update(overrides)
    return defaults


def market_payload(market_type: str = "MONEYLINE", **overrides) -> dict:
    defaults = {
        "market_type": market_type,
        "liability_cap_cents": DEFAULTS["LIABILITY_CAP_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def selection_payload(name: str = "AWAY", american_odds: int = 200, **overrides) -> dict:
    defaults = {"name": name, "american_odds": american_odds}
    defaults.update(overrides)
    return defaults


def reprice_payload(american_odds: int, **overrides) -> dict:
    defaults = {"american_odds": american_odds}
    defaults.update(overrides)
    return defaults


def bet_payload(account_id: str, bet_type: str, stake_cents: int, leg_selection_ids,
                expected_account_version: int, **overrides) -> dict:
    """leg_selection_ids: list of selection_id strings → built into legs array."""
    defaults = {
        "account_id": account_id,
        "bet_type": bet_type,
        "stake_cents": stake_cents,
        "legs": [{"selection_id": sid} for sid in leg_selection_ids],
        "expected_account_version": expected_account_version,
    }
    defaults.update(overrides)
    return defaults


def promotion_payload(code: str, bonus_cents: int = 2000, wagering_multiplier: int = 5,
                      max_claims: int = 10, **overrides) -> dict:
    defaults = {
        "code": code,
        "bonus_cents": bonus_cents,
        "wagering_multiplier": wagering_multiplier,
        "max_claims": max_claims,
    }
    defaults.update(overrides)
    return defaults


def bonus_claim_payload(promotion_id: str, expected_account_version: int, **overrides) -> dict:
    defaults = {"promotion_id": promotion_id, "expected_account_version": expected_account_version}
    defaults.update(overrides)
    return defaults
