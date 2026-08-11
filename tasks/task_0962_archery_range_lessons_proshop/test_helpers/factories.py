"""Payload factories — one per entity, input fields only (PRD §4)."""

DEFAULTS = {
    "MEMBER_EMAIL": "archer@example.com",
    "MEMBER_FULL_NAME": "Test Archer",
    "MEMBER_DOB": "1990-01-01",
    "LANE_NAME": "Lane 1",
    "LANE_TYPE": "INDOOR",
    "LANE_MAX_ARCHERS": 4,
    "PUNCHES_TOTAL": 5,
    "RENTAL_ITEM_NAME": "Recurve Bow",
    "RENTAL_ITEM_TYPE": "BOW",
    "RENTAL_DAILY_RATE": 2500,
    "DRAW_LENGTH_IN": 28.0,
    "DRAW_WEIGHT_LB": 40,
    "COACH_NAME": "Coach Taylor",
    "DISCIPLINES": ["RECURVE"],
    "LESSON_DURATION": 60,
    "LEAGUE_NAME": "Spring League",
    "ENTRY_FEE_CENTS": 5000,
    "LEAGUE_MAX_ENTRIES": 10,
    "PRODUCT_NAME": "Target Face",
    "PRODUCT_SKU": "TF-1",
    "PRODUCT_PRICE": 1000,
    "PRODUCT_STOCK": 10,
    "REPAIR_DESCRIPTION": "cracked limb",
}


def create_member_payload(**overrides) -> dict:
    defaults = {
        "email": DEFAULTS["MEMBER_EMAIL"],
        "full_name": DEFAULTS["MEMBER_FULL_NAME"],
        "date_of_birth": DEFAULTS["MEMBER_DOB"],
    }
    defaults.update(overrides)
    return defaults


def create_lane_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["LANE_NAME"],
        "lane_type": DEFAULTS["LANE_TYPE"],
        "max_archers": DEFAULTS["LANE_MAX_ARCHERS"],
    }
    defaults.update(overrides)
    return defaults


def create_range_session_payload(lane_id, booking_type, start_at, end_at, **overrides):
    payload = {
        "lane_id": lane_id,
        "booking_type": booking_type,
        "start_at": start_at,
        "end_at": end_at,
    }
    payload.update(overrides)
    return payload


def add_participant_payload(member_id, payment_method, **overrides) -> dict:
    payload = {"member_id": member_id, "payment_method": payment_method}
    payload.update(overrides)
    return payload


def purchase_punch_card_payload(punches_total=DEFAULTS["PUNCHES_TOTAL"], **overrides):
    payload = {"punches_total": punches_total}
    payload.update(overrides)
    return payload


def create_rental_item_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["RENTAL_ITEM_NAME"],
        "item_type": DEFAULTS["RENTAL_ITEM_TYPE"],
        "daily_rate_cents": DEFAULTS["RENTAL_DAILY_RATE"],
    }
    defaults.update(overrides)
    return defaults


def create_rental_agreement_payload(rental_item_id, member_id, due_date, **overrides):
    payload = {
        "rental_item_id": rental_item_id,
        "member_id": member_id,
        "draw_length_in": DEFAULTS["DRAW_LENGTH_IN"],
        "draw_weight_lb": DEFAULTS["DRAW_WEIGHT_LB"],
        "due_date": due_date,
    }
    payload.update(overrides)
    return payload


def return_rental_agreement_payload(returned_condition="GOOD", **overrides) -> dict:
    payload = {"returned_condition": returned_condition}
    payload.update(overrides)
    return payload


def create_coach_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["COACH_NAME"],
        "disciplines": list(DEFAULTS["DISCIPLINES"]),
    }
    defaults.update(overrides)
    return defaults


def create_lesson_payload(coach_id, discipline, proposed_start_at, **overrides):
    payload = {
        "coach_id": coach_id,
        "discipline": discipline,
        "proposed_start_at": proposed_start_at,
        "duration_minutes": DEFAULTS["LESSON_DURATION"],
    }
    payload.update(overrides)
    return payload


def create_league_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["LEAGUE_NAME"],
        "entry_fee_cents": DEFAULTS["ENTRY_FEE_CENTS"],
        "max_entries": DEFAULTS["LEAGUE_MAX_ENTRIES"],
    }
    defaults.update(overrides)
    return defaults


def scorecard_payload(ends=None, x_hits=0, **overrides) -> dict:
    if ends is None:
        ends = [[10, 10, 10]] * 10
    payload = {"ends": ends, "x_hits": x_hits}
    payload.update(overrides)
    return payload


def create_shop_product_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PRODUCT_NAME"],
        "sku": DEFAULTS["PRODUCT_SKU"],
        "unit_price_cents": DEFAULTS["PRODUCT_PRICE"],
        "initial_stock": DEFAULTS["PRODUCT_STOCK"],
    }
    defaults.update(overrides)
    return defaults


def create_sale_payload(items, **overrides) -> dict:
    payload = {"items": items}
    payload.update(overrides)
    return payload


def create_repair_order_payload(member_id, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "item_description": DEFAULTS["REPAIR_DESCRIPTION"],
    }
    payload.update(overrides)
    return payload


def quote_repair_order_payload(parts, labor_minutes, promised_hours,
                               expected_repair_order_version, **overrides) -> dict:
    payload = {
        "parts": parts,
        "labor_minutes": labor_minutes,
        "promised_hours": promised_hours,
        "expected_repair_order_version": expected_repair_order_version,
    }
    payload.update(overrides)
    return payload
