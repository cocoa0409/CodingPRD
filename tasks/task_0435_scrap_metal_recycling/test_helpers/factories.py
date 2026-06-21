"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "SELLER_LEGAL_NAME": "Test Seller",
    "ID_TYPE": "STATE_ID",
    "ID_NUMBER": "SID-TEST",
    "GRADE_CODE": "SHRED_STEEL",
    "CATEGORY": "FERROUS",
    "SPOT_PRICE": 11,
    "MILL_PRICE": 14,
    "GROSS_WEIGHT": 1500,
    "WEIGHT_LB": 100,
    "CAPACITY_LB": 5000,
    "HEDGED_WEIGHT": 1300,
    "LOCKED_PRICE": 90,
    "TARE_WEIGHT": 200,
    "REASON": "suspected stolen material",
}


def create_seller_payload(**overrides) -> dict:
    """Seller registration input: legal_name, id_type, id_number, tin? (optional)."""
    payload = {
        "legal_name": DEFAULTS["SELLER_LEGAL_NAME"],
        "id_type": DEFAULTS["ID_TYPE"],
        "id_number": DEFAULTS["ID_NUMBER"],
    }
    payload.update(overrides)
    return payload


def create_commodity_price_payload(**overrides) -> dict:
    """CommodityPrice input: grade_code, category, spot_price_cents_per_lb, mill_price_cents_per_lb."""
    payload = {
        "grade_code": DEFAULTS["GRADE_CODE"],
        "category": DEFAULTS["CATEGORY"],
        "spot_price_cents_per_lb": DEFAULTS["SPOT_PRICE"],
        "mill_price_cents_per_lb": DEFAULTS["MILL_PRICE"],
    }
    payload.update(overrides)
    return payload


def create_ticket_payload(seller_id, **overrides) -> dict:
    """ScaleTicket input: seller_id, gross_weight_lb."""
    payload = {
        "seller_id": seller_id,
        "gross_weight_lb": DEFAULTS["GROSS_WEIGHT"],
    }
    payload.update(overrides)
    return payload


def create_line_item_payload(**overrides) -> dict:
    """TicketLineItem input: grade_code, weight_lb."""
    payload = {
        "grade_code": DEFAULTS["GRADE_CODE"],
        "weight_lb": DEFAULTS["WEIGHT_LB"],
    }
    payload.update(overrides)
    return payload


def weigh_out_payload(**overrides) -> dict:
    """weigh-out input: tare_weight_lb."""
    payload = {"tare_weight_lb": DEFAULTS["TARE_WEIGHT"]}
    payload.update(overrides)
    return payload


def release_payload(container_id, **overrides) -> dict:
    """release input: container_id."""
    payload = {"container_id": container_id}
    payload.update(overrides)
    return payload


def report_payload(**overrides) -> dict:
    """report input: reason."""
    payload = {"reason": DEFAULTS["REASON"]}
    payload.update(overrides)
    return payload


def create_payout_payload(ticket_id, method="CASH", **overrides) -> dict:
    """Payout input: ticket_id, method."""
    payload = {"ticket_id": ticket_id, "method": method}
    payload.update(overrides)
    return payload


def create_container_payload(**overrides) -> dict:
    """Container input: category, capacity_lb."""
    payload = {
        "category": DEFAULTS["CATEGORY"],
        "capacity_lb": DEFAULTS["CAPACITY_LB"],
    }
    payload.update(overrides)
    return payload


def dispatch_payload(expected_container_version, **overrides) -> dict:
    """dispatch input: expected_container_version."""
    payload = {"expected_container_version": expected_container_version}
    payload.update(overrides)
    return payload


def create_mill_shipment_payload(container_id, **overrides) -> dict:
    """MillShipment input: container_id, hedge_position_id? (optional)."""
    payload = {"container_id": container_id}
    payload.update(overrides)
    return payload


def settle_shipment_payload(final_settlement_cents, **overrides) -> dict:
    """settle input: final_settlement_cents, expected_hedge_version? (optional)."""
    payload = {"final_settlement_cents": final_settlement_cents}
    payload.update(overrides)
    return payload


def create_hedge_payload(**overrides) -> dict:
    """HedgePosition input: category, hedged_weight_lb, locked_price_cents_per_lb."""
    payload = {
        "category": DEFAULTS["CATEGORY"],
        "hedged_weight_lb": DEFAULTS["HEDGED_WEIGHT"],
        "locked_price_cents_per_lb": DEFAULTS["LOCKED_PRICE"],
    }
    payload.update(overrides)
    return payload


def create_theft_report_payload(seller_id, **overrides) -> dict:
    """TheftReport input: seller_id, reason, ticket_id? (optional)."""
    payload = {"seller_id": seller_id, "reason": DEFAULTS["REASON"]}
    payload.update(overrides)
    return payload
