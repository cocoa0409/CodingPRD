"""Payload factories — input fields only, one per entity (PRD §3)."""
import itertools

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


# --- desk setup ---

def create_security_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "ticker": f"TK{n:04d}",
        # CUSIP is 9 chars: 3-letter prefix + 6-digit counter (zero-padded).
        "cusip": f"CUS{n:06d}",
        "name": f"Test Security {n}",
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "account_number": f"ACC-{n:05d}",
        "holder_name": f"Holder {n}",
    }
    defaults.update(overrides)
    return defaults


def create_position_lot_payload(**overrides) -> dict:
    defaults = {
        "account_id": None,
        "security_id": None,
        "quantity": 100,
        "acquisition_date": "2026-04-01",
        "cost_basis_total_cents": 500000,
    }
    defaults.update(overrides)
    return defaults


def create_event_source_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "name": f"Source {n}",
        "source_type": "VENDOR",
        "reliability_weight": 10,
    }
    defaults.update(overrides)
    return defaults


# --- notifications / events ---

def split_terms(**overrides) -> dict:
    defaults = {
        "ratio_num": 2,
        "ratio_den": 1,
        "price_per_share_cents": 3333,
        "fractional_policy": "ROUND_HALF_UP",
    }
    defaults.update(overrides)
    return defaults


def merger_terms(new_security_id, **overrides) -> dict:
    defaults = {
        "cash_per_share_cents": 5000,
        "cash_pool_cents": 900000,
        "new_security_id": new_security_id,
        "ratio_num": 1,
        "ratio_den": 1,
        "default_option": "STOCK",
    }
    defaults.update(overrides)
    return defaults


def rights_terms(**overrides) -> dict:
    defaults = {
        "rights_ratio_num": 1,
        "rights_ratio_den": 1,
        "subscription_price_cents": 400,
        "shares_offered": 1000,
        "oversubscription_allowed": True,
    }
    defaults.update(overrides)
    return defaults


def cash_dividend_terms(**overrides) -> dict:
    defaults = {"cash_per_share_cents": 250}
    defaults.update(overrides)
    return defaults


def spinoff_terms(spinoff_security_id, **overrides) -> dict:
    defaults = {
        "spinoff_security_id": spinoff_security_id,
        "ratio_num": 1,
        "ratio_den": 5,
        "fmv_parent_cents": 9777,
        "fmv_spin_cents": 1234,
        "price_per_share_cents": 2000,
        "fractional_policy": "ROUND_HALF_UP",
    }
    defaults.update(overrides)
    return defaults


def create_source_notification_payload(**overrides) -> dict:
    defaults = {
        "source_id": None,
        "security_id": None,
        "event_type": "SPLIT",
        "record_date": "2026-05-15",
        "announced_terms": split_terms(),
    }
    defaults.update(overrides)
    return defaults


def create_event_payload(**overrides) -> dict:
    defaults = {
        "security_id": None,
        "event_type": "SPLIT",
        "terms": split_terms(),
        "record_date": "2026-05-15",
        "payable_date": "2026-05-29",
        "source_notification_ids": [],
    }
    defaults.update(overrides)
    return defaults


def create_amendment_payload(**overrides) -> dict:
    defaults = {
        "amended_terms": split_terms(ratio_num=3),
        "reason": "terms revised",
        "expected_event_version": 1,
    }
    defaults.update(overrides)
    return defaults


# --- elections / claims / statements ---

def submit_election_payload(**overrides) -> dict:
    defaults = {
        "account_id": None,
        "option_code": "CASH",
        "expected_event_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(**overrides) -> dict:
    defaults = {
        "event_id": None,
        "entitlement_id": None,
        "account_id": None,
        "reason": "MISSED_ENTITLEMENT",
        "claimed_amount_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_custodian_statement_payload(**overrides) -> dict:
    defaults = {
        "source_id": None,
        "coverage_start_date": "2026-05-01",
        "coverage_end_date": "2026-05-14",
        "lines": [],
    }
    defaults.update(overrides)
    return defaults
