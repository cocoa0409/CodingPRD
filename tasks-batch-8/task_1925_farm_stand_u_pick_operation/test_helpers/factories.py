"""Payload factories — one per resource, input fields only (PRD §3)."""
from .constants import (
    DEFAULT_CLOSE_TIME,
    DEFAULT_OPEN_TIME,
    POLICY_A,
    SEASON_END,
    SEASON_NAME,
    SEASON_START,
    WAIVER_TEXT_V1,
    WEEKDAY_DATE,
)


def create_season_payload(**overrides):
    defaults = {
        "name": SEASON_NAME,
        "start_date": SEASON_START,
        "end_date": SEASON_END,
        "waiver_text": WAIVER_TEXT_V1,
    }
    defaults.update(overrides)
    return defaults


def create_crop_payload(season_id, **overrides):
    defaults = {
        "season_id": season_id,
        "name": "Strawberry",
        "price_per_lb_cents": 480,
    }
    defaults.update(overrides)
    return defaults


def create_field_payload(season_id, **overrides):
    defaults = {
        "season_id": season_id,
        "name": "North",
        "rotation_group": "RG1",
        "rotation_order": 1,
        "estimated_harvest_oz": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_pricing_policy_payload(season_id, expected_season_version, **overrides):
    defaults = dict(POLICY_A)
    defaults.update(overrides)
    defaults["season_id"] = season_id
    defaults["expected_season_version"] = expected_season_version
    return defaults


def create_sales_day_payload(season_id, **overrides):
    defaults = {
        "season_id": season_id,
        "date": WEEKDAY_DATE,
        "day_type": "WEEKDAY",
        "parking_capacity": 50,
        "staff_on_duty": 3,
    }
    defaults.update(overrides)
    return defaults


def create_window_payload(field_id, **overrides):
    defaults = {
        "field_id": field_id,
        "date": WEEKDAY_DATE,
        "open_time": DEFAULT_OPEN_TIME,
        "close_time": DEFAULT_CLOSE_TIME,
        "picking_capacity_slots": 30,
    }
    defaults.update(overrides)
    return defaults


def create_waiver_payload(season_id, **overrides):
    defaults = {
        "season_id": season_id,
        "signer_name": "Ann",
        "signer_email": "ann@x.com",
        "party_member_names": ["Ann"],
    }
    defaults.update(overrides)
    return defaults


def create_visit_session_payload(window_id, waiver_id, **overrides):
    defaults = {
        "window_id": window_id,
        "waiver_id": waiver_id,
        "party_size": 1,
        "container_count": 0,
        "parking_spaces": 0,
        "origin": "ONLINE",
    }
    defaults.update(overrides)
    return defaults


def create_harvest_line_payload(session_id, crop_id, **overrides):
    defaults = {
        "session_id": session_id,
        "crop_id": crop_id,
        "gross_weight_oz": 36,
        "container_count": 4,
    }
    defaults.update(overrides)
    return defaults


def create_addon_product_payload(season_id, **overrides):
    defaults = {
        "season_id": season_id,
        "kind": "WAGON_RIDE",
        "name": "Orchard Wagon",
        "price_cents": 900,
        "slot_capacity": 20,
    }
    defaults.update(overrides)
    return defaults


def create_addon_booking_payload(session_id, addon_product_id, **overrides):
    defaults = {
        "session_id": session_id,
        "addon_product_id": addon_product_id,
        "booking_date": WEEKDAY_DATE,
        "slot_time": "11:00",
        "qty": 1,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(session_id, **overrides):
    defaults = {
        "session_id": session_id,
        "kind": "CHARGE",
        "method": "CASH",
        "amount_cents": 650,
        "idempotency_key": "k1",
    }
    defaults.update(overrides)
    return defaults


def create_offline_batch_payload(device_id, batch_id, records, **overrides):
    defaults = {
        "device_id": device_id,
        "batch_id": batch_id,
        "records": records,
    }
    defaults.update(overrides)
    return defaults


def offline_session_record(sequence_index, offline_ref, *, window_id, waiver_id,
                           pricing_policy_id, party_size=1, container_count=0,
                           parking_spaces=0):
    """A VISIT_SESSION batch record (PRD §3.9 payload shape)."""
    return {
        "record_type": "VISIT_SESSION",
        "sequence_index": sequence_index,
        "offline_ref": offline_ref,
        "payload": {
            "window_id": window_id,
            "waiver_id": waiver_id,
            "pricing_policy_id": pricing_policy_id,
            "party_size": party_size,
            "container_count": container_count,
            "parking_spaces": parking_spaces,
        },
    }


def offline_payment_record(sequence_index, offline_ref, *, session_ref, amount_cents,
                           method="OFFLINE_CARD"):
    """A PAYMENT batch record (PRD §3.9 payload shape)."""
    return {
        "record_type": "PAYMENT",
        "sequence_index": sequence_index,
        "offline_ref": offline_ref,
        "payload": {
            "session_ref": session_ref,
            "method": method,
            "amount_cents": amount_cents,
        },
    }


def offline_harvest_line_record(sequence_index, offline_ref, *, session_ref, crop_id,
                                gross_weight_oz, container_count):
    """A HARVEST_LINE batch record (PRD §3.9 payload shape)."""
    return {
        "record_type": "HARVEST_LINE",
        "sequence_index": sequence_index,
        "offline_ref": offline_ref,
        "payload": {
            "session_ref": session_ref,
            "crop_id": crop_id,
            "gross_weight_oz": gross_weight_oz,
            "container_count": container_count,
        },
    }
