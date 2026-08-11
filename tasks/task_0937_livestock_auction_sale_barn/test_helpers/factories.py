"""Payload factories — input fields only, named exactly as the PRD names them."""

from .constants import TEST_DEFAULTS


def create_party_payload(**overrides) -> dict:
    payload = {
        "legal_name": "Rocking R Ranch",
        "party_type": "FARM",
        "origin_state_code": "NE",
        "origin_county": "Lincoln",
        "tax_id": "47-1111111",
    }
    payload.update(overrides)
    return payload


def create_sale_day_payload(**overrides) -> dict:
    payload = {
        "sale_date": TEST_DEFAULTS["SALE_DATE"],
        "barn_code": TEST_DEFAULTS["BARN_CODE"],
        "barn_state_code": TEST_DEFAULTS["BARN_STATE_CODE"],
    }
    payload.update(overrides)
    return payload


def create_pen_payload(**overrides) -> dict:
    payload = {
        "pen_code": TEST_DEFAULTS["PEN_CODE"],
        "species_class": "CATTLE",
        "head_capacity": TEST_DEFAULTS["PEN_CAPACITY"],
        "pen_type": "HOLDING",
    }
    payload.update(overrides)
    return payload


def create_scale_payload(**overrides) -> dict:
    payload = {
        "scale_code": TEST_DEFAULTS["SCALE_CODE"],
        "certified_from": TEST_DEFAULTS["SCALE_CERTIFIED_FROM"],
        "certification_expires_on": TEST_DEFAULTS["SCALE_EXPIRES_ON"],
        "max_draft_lb": TEST_DEFAULTS["MAX_DRAFT_LB"],
    }
    payload.update(overrides)
    return payload


def create_drover_crew_payload(**overrides) -> dict:
    payload = {"crew_code": "CREW-A", "member_count": 3}
    payload.update(overrides)
    return payload


def create_consignment_payload(sale_day_id, consignor_party_id, **overrides) -> dict:
    payload = {
        "sale_day_id": sale_day_id,
        "consignor_party_id": consignor_party_id,
        "species_class": "CATTLE",
        "head_received": 10,
        "weigh_basis": "PENCIL_SHRINK",
    }
    payload.update(overrides)
    return payload


def create_lot_payload(consignment_id, **overrides) -> dict:
    payload = {
        "consignment_id": consignment_id,
        "head_count": 10,
        "livestock_class": "FEEDER_STEER",
        "bid_basis": "PER_CWT",
        "opening_bid": TEST_DEFAULTS["OPENING_BID"],
        "reserve_price": TEST_DEFAULTS["RESERVE_PRICE"],
    }
    payload.update(overrides)
    return payload


def create_weigh_ticket_payload(lot_id, scale_id, **overrides) -> dict:
    payload = {
        "lot_id": lot_id,
        "scale_id": scale_id,
        "head_on_draft": 10,
        "gross_weight_lb": TEST_DEFAULTS["GROSS_WEIGHT_LB"],
        "tare_weight_lb": TEST_DEFAULTS["TARE_WEIGHT_LB"],
    }
    payload.update(overrides)
    return payload


def create_pen_move_payload(lot_id, to_pen_id, crew_id, scheduled_start_at, **overrides) -> dict:
    payload = {
        "lot_id": lot_id,
        "to_pen_id": to_pen_id,
        "crew_id": crew_id,
        "scheduled_start_at": scheduled_start_at,
    }
    payload.update(overrides)
    return payload


def create_buyer_registration_payload(party_id, sale_day_id, **overrides) -> dict:
    payload = {
        "party_id": party_id,
        "sale_day_id": sale_day_id,
        "buyer_number": 101,
        "bond_type": "BONDED",
        "credit_limit": TEST_DEFAULTS["CREDIT_LIMIT"],
    }
    payload.update(overrides)
    return payload


def create_bid_payload(lot_id, buyer_registration_id, unit_price, **overrides) -> dict:
    payload = {
        "lot_id": lot_id,
        "buyer_registration_id": buyer_registration_id,
        "unit_price": unit_price,
    }
    payload.update(overrides)
    return payload


def create_inspection_record_payload(lot_id, inspection_type, **overrides) -> dict:
    payload = {
        "lot_id": lot_id,
        "inspection_type": inspection_type,
        "document_number": "DOC-1",
        "issue_date": TEST_DEFAULTS["SALE_DATE"],
        "inspected_head": 10,
    }
    payload.update(overrides)
    return payload


def create_load_manifest_payload(sale_day_id, carrier_party_id, **overrides) -> dict:
    payload = {
        "sale_day_id": sale_day_id,
        "carrier_party_id": carrier_party_id,
        "trailer_code": "TR-77",
        "trailer_head_capacity": 60,
        "trailer_weight_capacity_lb": 60000,
        "haul_basis": "PER_MILE",
        "loaded_miles": 40,
    }
    payload.update(overrides)
    return payload
