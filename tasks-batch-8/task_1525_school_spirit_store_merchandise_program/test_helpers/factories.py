"""Payload factories — one per resource, input fields only (PRD section 3)."""

DEFAULTS = {
    "PROGRAM_NAME": "Spirit 2026",
    "SCHOOL_YEAR": "2026-2027",
    "VALUATION_METHOD": "FIFO",
    "DESIGN_NAME": "Eagle",
    "ARTWORK_REF": "eagle.png",
    "VENDOR_NAME": "PrintCo",
    "VENDOR_EMAIL": "p@co.com",
    "UNIT_PRICE_CENTS": 2500,
    "UNIT_COST_CENTS": 500,
    "MIN_ORDER_QTY": 25,
    "PRODUCTION_DAYS": 10,
    "DEPOSIT_PCT": 0.4,
    "GOAL_UNITS": 5,
    "EVENT_NAME": "Game",
    "REGISTER": "GYM-A",
    "EVENT_STARTS": "2026-09-05T14:00:00Z",
    "EVENT_ENDS": "2026-09-05T16:00:00Z",
    "CAMPAIGN_OPENS": "2026-08-01T00:00:00Z",
    "CAMPAIGN_CLOSES": "2026-09-01T00:00:00Z",
    "OPENING_FLOAT_CENTS": 10000,
}


def create_program_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PROGRAM_NAME"],
        "school_year": DEFAULTS["SCHOOL_YEAR"],
        "valuation_method": DEFAULTS["VALUATION_METHOD"],
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(design_id, **overrides) -> dict:
    defaults = {
        "design_id": design_id,
        "unit_cost_cents": DEFAULTS["UNIT_COST_CENTS"],
        "min_order_qty": DEFAULTS["MIN_ORDER_QTY"],
        "production_days": DEFAULTS["PRODUCTION_DAYS"],
        "status": "ACTIVE",
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(program_id, quotes=None, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "name": DEFAULTS["VENDOR_NAME"],
        "contact_email": DEFAULTS["VENDOR_EMAIL"],
    }
    if quotes is not None:
        defaults["quotes"] = quotes
    defaults.update(overrides)
    return defaults


def create_design_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "name": DEFAULTS["DESIGN_NAME"],
        "artwork_ref": DEFAULTS["ARTWORK_REF"],
        "royalty_pct": 0,
        "licensing_fee_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_product_variant_payload(program_id, design_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "design_id": design_id,
        "size": "M",
        "unit_price_cents": DEFAULTS["UNIT_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_seasonal_drop_payload(
    program_id, expected_program_version, **overrides
) -> dict:
    defaults = {
        "program_id": program_id,
        "name": "Fall Drop",
        "opens_at": "2026-09-01T00:00:00Z",
        "closes_at": "2026-10-01T00:00:00Z",
        "expected_program_version": expected_program_version,
    }
    defaults.update(overrides)
    return defaults


def create_purchase_order_payload(
    program_id, variant_id, vendor_id, qty_ordered=25, **overrides
) -> dict:
    defaults = {
        "program_id": program_id,
        "variant_id": variant_id,
        "vendor_id": vendor_id,
        "qty_ordered": qty_ordered,
    }
    defaults.update(overrides)
    return defaults


def create_preorder_campaign_payload(program_id, design_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "design_id": design_id,
        "unit_price_cents": DEFAULTS["UNIT_PRICE_CENTS"],
        "deposit_pct": DEFAULTS["DEPOSIT_PCT"],
        "goal_units": DEFAULTS["GOAL_UNITS"],
        "opens_at": DEFAULTS["CAMPAIGN_OPENS"],
        "closes_at": DEFAULTS["CAMPAIGN_CLOSES"],
    }
    defaults.update(overrides)
    return defaults


def create_preorder_payload(
    program_id, campaign_id, variant_id, customer_user_id, qty=1, **overrides
) -> dict:
    defaults = {
        "program_id": program_id,
        "campaign_id": campaign_id,
        "variant_id": variant_id,
        "customer_user_id": customer_user_id,
        "qty": qty,
    }
    defaults.update(overrides)
    return defaults


def create_event_sale_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "name": DEFAULTS["EVENT_NAME"],
        "register_location": DEFAULTS["REGISTER"],
        "starts_at": DEFAULTS["EVENT_STARTS"],
        "ends_at": DEFAULTS["EVENT_ENDS"],
    }
    defaults.update(overrides)
    return defaults


def create_order_line(variant_id, qty, **overrides) -> dict:
    line = {"variant_id": variant_id, "qty": qty}
    line.update(overrides)
    return line


def create_order_payload(
    program_id, channel, customer_user_id, payment_method, lines, **overrides
) -> dict:
    defaults = {
        "program_id": program_id,
        "channel": channel,
        "customer_user_id": customer_user_id,
        "payment_method": payment_method,
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_exchange_payload(
    program_id, order_id, original_variant_id, new_variant_id, **overrides
) -> dict:
    defaults = {
        "program_id": program_id,
        "order_id": order_id,
        "original_variant_id": original_variant_id,
        "new_variant_id": new_variant_id,
    }
    defaults.update(overrides)
    return defaults


def create_activity_account_payload(program_id, name="Band", **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "name": name,
        "allocation_weight": 1,
    }
    defaults.update(overrides)
    return defaults


def create_allocation_run_payload(program_id, distributable_cents, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "distributable_cents": distributable_cents,
    }
    defaults.update(overrides)
    return defaults
