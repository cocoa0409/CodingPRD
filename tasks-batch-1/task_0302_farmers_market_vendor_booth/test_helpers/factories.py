"""Payload factories — one per entity, input fields only.

The standard market policy (season_fee=50000, daily_fee=4000, commission_bps=700,
voucher_face_value=200, season 2026-06-01..2026-09-30) is pinned here so every
test that does not care about policy uses identical, predictable inputs.
"""

DEFAULTS = {
    "MARKET_NAME": "Green Sq",
    "SEASON_START": "2026-06-01",
    "SEASON_END": "2026-09-30",
    "SEASON_FEE_CENTS": 50000,
    "DAILY_FEE_CENTS": 4000,
    "COMMISSION_BPS": 700,
    "VOUCHER_FACE_VALUE_CENTS": 200,
}


def create_market_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["MARKET_NAME"],
        "season_start_date": DEFAULTS["SEASON_START"],
        "season_end_date": DEFAULTS["SEASON_END"],
        "season_fee_cents": DEFAULTS["SEASON_FEE_CENTS"],
        "daily_fee_cents": DEFAULTS["DAILY_FEE_CENTS"],
        "commission_bps": DEFAULTS["COMMISSION_BPS"],
        "voucher_face_value_cents": DEFAULTS["VOUCHER_FACE_VALUE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(market_id: str, **overrides) -> dict:
    defaults = {
        "market_id": market_id,
        "legal_name": "Acme Farm",
        "contact_email": "acme@x.com",
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(vendor_id: str, **overrides) -> dict:
    defaults = {
        "vendor_id": vendor_id,
        "permit_type": "HEALTH",
        "permit_number": "H-1",
        "issue_date": "2026-05-01",
        "expiry_date": "2026-12-31",
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(vendor_id: str, **overrides) -> dict:
    defaults = {
        "vendor_id": vendor_id,
        "product_category": "CRAFTS",
    }
    defaults.update(overrides)
    return defaults


def create_booth_payload(market_id: str, **overrides) -> dict:
    defaults = {
        "market_id": market_id,
        "label": "A-12",
        "grid_row": 1,
        "grid_col": 12,
        "size_class": "SINGLE",
        "allowed_categories": [],
    }
    defaults.update(overrides)
    return defaults


def create_market_day_payload(market_id: str, **overrides) -> dict:
    defaults = {
        "market_id": market_id,
        "market_date": "2026-06-06",
    }
    defaults.update(overrides)
    return defaults


def create_booth_assignment_payload(market_id: str, booth_id: str, vendor_id: str,
                                    assignment_type: str = "SEASON", **overrides) -> dict:
    defaults = {
        "market_id": market_id,
        "booth_id": booth_id,
        "vendor_id": vendor_id,
        "assignment_type": assignment_type,
    }
    defaults.update(overrides)
    return defaults


def create_check_in_payload(market_id: str, booth_assignment_id: str,
                            market_day_id: str, **overrides) -> dict:
    defaults = {
        "market_id": market_id,
        "booth_assignment_id": booth_assignment_id,
        "market_day_id": market_day_id,
    }
    defaults.update(overrides)
    return defaults


def create_sales_report_payload(market_id: str, check_in_id: str,
                                gross_sales_cents: int = 30000,
                                tokens_accepted: int = 0, **overrides) -> dict:
    defaults = {
        "market_id": market_id,
        "check_in_id": check_in_id,
        "gross_sales_cents": gross_sales_cents,
        "tokens_accepted": tokens_accepted,
    }
    defaults.update(overrides)
    return defaults


def create_voucher_batch_payload(market_id: str, market_day_id: str,
                                tokens_issued: int = 100, **overrides) -> dict:
    defaults = {
        "market_id": market_id,
        "market_day_id": market_day_id,
        "tokens_issued": tokens_issued,
    }
    defaults.update(overrides)
    return defaults


def create_voucher_redemption_payload(market_id: str, voucher_batch_id: str,
                                    vendor_id: str, market_day_id: str,
                                    token_count: int = 40, **overrides) -> dict:
    defaults = {
        "market_id": market_id,
        "voucher_batch_id": voucher_batch_id,
        "vendor_id": vendor_id,
        "market_day_id": market_day_id,
        "token_count": token_count,
    }
    defaults.update(overrides)
    return defaults
