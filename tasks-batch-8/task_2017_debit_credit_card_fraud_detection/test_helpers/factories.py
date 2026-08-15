"""Payload factories — one per creatable entity, input fields only."""

from .constants import STD_RULESET

_counter = {"n": 0}


def _seq() -> int:
    _counter["n"] += 1
    return _counter["n"]


def create_account_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "account_number": f"ACCT-{n:05d}",
        "cardholder_name": "Test Cardholder",
        "home_country": "US",
    }
    defaults.update(overrides)
    return defaults


def create_card_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "pan_token": f"PT-{n:05d}",
        "product_type": "CREDIT",
        "network": "VISA",
    }
    defaults.update(overrides)
    return defaults


def create_rule_set_payload(**overrides) -> dict:
    defaults = dict(STD_RULESET)
    defaults["amount_tiers"] = [dict(t) for t in STD_RULESET["amount_tiers"]]
    defaults["channel_weights"] = dict(STD_RULESET["channel_weights"])
    defaults["high_risk_countries"] = list(STD_RULESET["high_risk_countries"])
    defaults.update(overrides)
    return defaults


def create_auth_transaction_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "amount_cents": 1000,
        "merchant_id": f"M-{n:05d}",
        "merchant_category_code": "5411",
        "channel": "CNP",
        "origin_country": "US",
    }
    defaults.update(overrides)
    return defaults


def create_fraud_alert_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_verification_contact_payload(**overrides) -> dict:
    defaults = {"channel": "VOICE"}
    defaults.update(overrides)
    return defaults


def create_compromised_event_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "network_source": "CAMS",
        "event_reference": f"CAMS-{n:05d}",
        "merchant_id": f"M-{n:05d}",
        "window_start": "2026-08-01T00:00:00Z",
        "window_end": "2026-08-03T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_travel_notice_payload(**overrides) -> dict:
    defaults = {
        "region_country": "MX",
        "start_date": "2026-08-10",
        "end_date": "2026-08-20",
    }
    defaults.update(overrides)
    return defaults


def create_chargeback_case_payload(**overrides) -> dict:
    defaults = {
        "reason_code": "4855",
        "provisional_credit_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_loss_entry_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_recovery_filing_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "network_reference": f"NR-{n:05d}",
        "claimed_cents": 1,
    }
    defaults.update(overrides)
    return defaults


def create_ring_detect_payload(**overrides) -> dict:
    defaults = {
        "signal_type": "COMMON_MERCHANT",
        "merchant_id": "M-RING",
        "window_start": "2026-08-01T00:00:00Z",
        "window_end": "2026-08-04T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
