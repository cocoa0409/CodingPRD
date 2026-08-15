"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "COMMUNITY_NAME": "Cedar Ridge",
    "COMMUNITY_BUDGET": 1_000_000,
    "PHASE_NAME": "P1",
    "UPLIFT_PCT": 0.03,
    "EFFECTIVE_FROM": "2026-08-01T00:00:00Z",
    "EFFECTIVE_TO": "2026-09-01T00:00:00Z",
    "PLAN_NAME": "Maple",
    "PLAN_BASE_PRICE": 35_000_000,
    "LOT_NUMBER": "L-101",
    "LOT_BASE_PRICE": 8_000_000,
    "LOT_TYPE": "CORNER",
    "VIEW_ADJUSTMENT": 200_000,
    "BUYER_NAME": "Bea Buyer",
    "BUYER_EMAIL": "bea@example.com",
    "ELEVATION_NAME": "B",
    "EARNEST_MONEY": 500_000,
    "CONTINGENCY_DEADLINE": "2026-08-21T00:00:00Z",
    "OUTSIDE_CLOSE_DATE": "2027-03-01T00:00:00Z",
    "QUANTITY": 1,
    "INCENTIVE_TYPE": "RATE_BUYDOWN",
    "INCENTIVE_AMOUNT": 200_000,
}

DEFAULT_ELEVATIONS = [
    {"name": "A", "price_cents": 0},
    {"name": "B", "price_cents": 250_000},
]


def create_community_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["COMMUNITY_NAME"],
        "incentive_budget_total_cents": DEFAULTS["COMMUNITY_BUDGET"],
    }
    defaults.update(overrides)
    return defaults


def create_price_phase_payload(community_id, **overrides) -> dict:
    defaults = {
        "community_id": community_id,
        "phase_name": DEFAULTS["PHASE_NAME"],
        "uplift_pct": DEFAULTS["UPLIFT_PCT"],
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
        "effective_to": DEFAULTS["EFFECTIVE_TO"],
    }
    defaults.update(overrides)
    return defaults


def create_plan_payload(community_id, **overrides) -> dict:
    defaults = {
        "community_id": community_id,
        "plan_name": DEFAULTS["PLAN_NAME"],
        "base_price_cents": DEFAULTS["PLAN_BASE_PRICE"],
        "elevations": [dict(e) for e in DEFAULT_ELEVATIONS],
    }
    defaults.update(overrides)
    return defaults


def create_option_catalog_item_payload(community_id, **overrides) -> dict:
    defaults = {
        "community_id": community_id,
        "option_name": "Quartz Counters",
        "category": "KITCHEN",
        "price_cents": 800_000,
        "cutoff_stage": "FOUNDATION",
        "install_stage": "DRYWALL",
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(community_id, **overrides) -> dict:
    defaults = {
        "community_id": community_id,
        "lot_number": DEFAULTS["LOT_NUMBER"],
        "base_price_cents": DEFAULTS["LOT_BASE_PRICE"],
        "lot_type": DEFAULTS["LOT_TYPE"],
        "view_adjustment_cents": DEFAULTS["VIEW_ADJUSTMENT"],
    }
    defaults.update(overrides)
    return defaults


def create_buyer_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["BUYER_NAME"],
        "email": DEFAULTS["BUYER_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(buyer_id, lot_id, plan_id, expected_lot_version,
                             **overrides) -> dict:
    defaults = {
        "buyer_id": buyer_id,
        "lot_id": lot_id,
        "plan_id": plan_id,
        "elevation_name": DEFAULTS["ELEVATION_NAME"],
        "earnest_money_deposited_cents": DEFAULTS["EARNEST_MONEY"],
        "contingency_deadline": DEFAULTS["CONTINGENCY_DEADLINE"],
        "outside_close_date": DEFAULTS["OUTSIDE_CLOSE_DATE"],
        "has_sale_of_home_contingency": False,
        "expected_lot_version": expected_lot_version,
    }
    defaults.update(overrides)
    return defaults


def create_contingency_clearance_payload(contingency_type, action,
                                         expected_agreement_version) -> dict:
    return {
        "contingency_type": contingency_type,
        "action": action,
        "expected_agreement_version": expected_agreement_version,
    }


def create_cancel_payload(reason="BUYER_DEFAULT") -> dict:
    return {"reason": reason}


def create_option_selection_payload(agreement_id, option_item_id,
                                    **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "option_item_id": option_item_id,
        "quantity": DEFAULTS["QUANTITY"],
    }
    defaults.update(overrides)
    return defaults


def create_incentive_request_payload(agreement_id, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "incentive_type": DEFAULTS["INCENTIVE_TYPE"],
        "amount_cents": DEFAULTS["INCENTIVE_AMOUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_decide_payload(action="APPROVE") -> dict:
    return {"action": action}


def create_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
