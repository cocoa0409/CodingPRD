"""Payload factories — one per entity, input fields only (per PRD §3/§4)."""
from itertools import count

_email_seq = count(1)
_sku_seq = count(1)
_name_seq = count(1)

DEFAULTS = {
    "LEVEL_CODE": "BASIC",
    "MIN_ANNUAL_CENTS": 6000,
    "MIN_MONTHLY_SUSTAINER_CENTS": 500,
    "PREMIUM_TITLE": "Station Mug",
    "PREMIUM_FMV_CENTS": 2500,
    "LOT_RECEIVED_AT": "2026-07-15T00:00:00Z",
    "LOT_UNIT_COST_CENTS": 800,
    "LOT_TOTAL_QTY": 10,
    "POSTAL_CODE": "97201",
    "DRIVE_STARTS_AT": "2026-08-01T00:00:00Z",
    "DRIVE_ENDS_AT": "2026-08-15T00:00:00Z",
    "DRIVE_GOAL_CENTS": 100000,
    "BREAK_STARTS_AT": "2026-08-02T18:00:00Z",
    "BREAK_ENDS_AT": "2026-08-02T18:20:00Z",
    "BREAK_PROGRAM_TITLE": "Evening Pledge",
    "PLEDGE_AMOUNT_CENTS": 6000,
    "PLEDGE_CHANNEL": "PHONE",
    "PLEDGE_KIND": "ONE_TIME",
    "FISCAL_YEAR": 2026,
}


def create_level_payload(**overrides) -> dict:
    defaults = {
        "code": DEFAULTS["LEVEL_CODE"],
        "min_annual_cents": DEFAULTS["MIN_ANNUAL_CENTS"],
        "min_monthly_sustainer_cents": DEFAULTS["MIN_MONTHLY_SUSTAINER_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_premium_payload(**overrides) -> dict:
    defaults = {
        "sku": f"MUG-{next(_sku_seq):04d}",
        "title": DEFAULTS["PREMIUM_TITLE"],
        "fair_market_value_cents": DEFAULTS["PREMIUM_FMV_CENTS"],
        "membership_level_code": DEFAULTS["LEVEL_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(**overrides) -> dict:
    defaults = {
        "received_at": DEFAULTS["LOT_RECEIVED_AT"],
        "unit_cost_cents": DEFAULTS["LOT_UNIT_COST_CENTS"],
        "total_qty": DEFAULTS["LOT_TOTAL_QTY"],
    }
    defaults.update(overrides)
    return defaults


def create_donor_payload(**overrides) -> dict:
    defaults = {
        "email": f"donor-{next(_email_seq):04d}@example.org",
        "full_name": "Test Donor",
        "postal_code": DEFAULTS["POSTAL_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_membership_payload(donor_id, level_code=DEFAULTS["LEVEL_CODE"],
                              **overrides) -> dict:
    defaults = {"donor_id": donor_id, "level_code": level_code}
    defaults.update(overrides)
    return defaults


def create_drive_payload(**overrides) -> dict:
    defaults = {
        "name": f"Fall 2026 Drive {next(_name_seq):04d}",
        "starts_at": DEFAULTS["DRIVE_STARTS_AT"],
        "ends_at": DEFAULTS["DRIVE_ENDS_AT"],
        "goal_cents": DEFAULTS["DRIVE_GOAL_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_break_payload(expected_drive_version, **overrides) -> dict:
    defaults = {
        "starts_at": DEFAULTS["BREAK_STARTS_AT"],
        "ends_at": DEFAULTS["BREAK_ENDS_AT"],
        "program_title": DEFAULTS["BREAK_PROGRAM_TITLE"],
        "pitch_level_code": DEFAULTS["LEVEL_CODE"],
        "expected_drive_version": expected_drive_version,
    }
    defaults.update(overrides)
    return defaults


def create_pledge_payload(donor_id, membership_id, drive_id, **overrides) -> dict:
    defaults = {
        "donor_id": donor_id,
        "membership_id": membership_id,
        "drive_id": drive_id,
        "channel": DEFAULTS["PLEDGE_CHANNEL"],
        "kind": DEFAULTS["PLEDGE_KIND"],
        "amount_cents": DEFAULTS["PLEDGE_AMOUNT_CENTS"],
    }
    defaults.update(overrides)
    # Optional nullable references are omitted entirely when not supplied.
    for optional in ("on_air_break_id", "matching_challenge_id", "premium_id",
                     "premium_waived"):
        if optional in defaults and defaults[optional] is None:
            del defaults[optional]
    return defaults


def create_payment_payload(amount_cents, expected_pledge_version) -> dict:
    return {
        "amount_cents": amount_cents,
        "expected_pledge_version": expected_pledge_version,
    }


def create_reason_payload(reason="no response after follow-up") -> dict:
    return {"reason": reason}


def create_reservation_payload(quantity=1, **overrides) -> dict:
    defaults = {"quantity": quantity}
    defaults.update(overrides)
    if defaults.get("lot_id") is None:
        defaults.pop("lot_id", None)
    return defaults


def create_challenge_payload(**overrides) -> dict:
    defaults = {
        "sponsor_name": "Acme Corp",
        "goal_cents": 10000,
        "match_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_underwriting_payload(**overrides) -> dict:
    defaults = {
        "underwriter_name": "BigCo Underwriting",
        "amount_cents": 25000,
    }
    defaults.update(overrides)
    return defaults


def create_nffs_report_payload(fiscal_year=DEFAULTS["FISCAL_YEAR"]) -> dict:
    return {"fiscal_year": fiscal_year}
