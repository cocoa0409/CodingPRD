"""Payload factories — one per write endpoint, input fields only."""

from .constants import BASE_RATE_CARD, TEST_DEFAULTS


def barn_payload(**overrides) -> dict:
    payload = {
        "name": "Ridgeview",
        "zone": "A",
        "served_weekdays": list(TEST_DEFAULTS["WEEKDAYS_MON_FRI"]),
        "access_open_minute": TEST_DEFAULTS["BARN_OPEN_MINUTE"],
        "access_close_minute": TEST_DEFAULTS["BARN_CLOSE_MINUTE"],
        "blackout_dates": [],
    }
    payload.update(overrides)
    return payload


def client_payload(home_barn_id, **overrides) -> dict:
    payload = {"display_name": "Aoi Tanaka", "home_barn_id": home_barn_id}
    payload.update(overrides)
    return payload


def horse_payload(client_id, barn_id, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "barn_id": barn_id,
        "name": "Comet",
        "routine_cycle_weeks": 6,
        "shoe_size_code": "1",
    }
    payload.update(overrides)
    return payload


def farrier_payload(**overrides) -> dict:
    payload = {
        "display_name": "Kenji Mori",
        "certification_level": "JOURNEYMAN",
        "cert_expires_on": TEST_DEFAULTS["CERT_EXPIRES_ON"],
    }
    payload.update(overrides)
    return payload


def shoe_sku_payload(**overrides) -> dict:
    payload = {
        "sku_code": "ST-1",
        "size_code": "1",
        "material": "STEEL",
        "price_cents_per_pair": TEST_DEFAULTS["SKU_PRICE_CENTS_PER_PAIR"],
    }
    payload.update(overrides)
    return payload


def rate_card_payload(**overrides) -> dict:
    payload = dict(BASE_RATE_CARD)
    payload.update(overrides)
    return payload


def stock_transfer_payload(sku_id, from_bucket_id, to_bucket_id, quantity_pairs=5):
    return {
        "sku_id": sku_id,
        "from_bucket_id": from_bucket_id,
        "to_bucket_id": to_bucket_id,
        "quantity_pairs": quantity_pairs,
    }


def route_payload(farrier_id, route_date=None) -> dict:
    return {
        "farrier_id": farrier_id,
        "route_date": route_date or TEST_DEFAULTS["ROUTE_DATE"],
    }


def route_stop_payload(barn_id, sequence_index=1, planned_start_minute=None) -> dict:
    return {
        "barn_id": barn_id,
        "sequence_index": sequence_index,
        "planned_start_minute": (
            TEST_DEFAULTS["STOP_START_MINUTE"]
            if planned_start_minute is None
            else planned_start_minute
        ),
    }


def appointment_payload(horse_id, scheduled_date, **overrides) -> dict:
    payload = {"horse_id": horse_id, "scheduled_date": scheduled_date}
    payload.update(overrides)
    return payload


def service_line(limb_state_id, service_type, **overrides) -> dict:
    line = {"limb_state_id": limb_state_id, "service_type": service_type}
    line.update(overrides)
    return line


def service_lines_payload(lines, expected_appointment_version) -> dict:
    return {
        "lines": lines,
        "expected_appointment_version": expected_appointment_version,
    }


def lameness_case_payload(horse_id, reported_on, severity) -> dict:
    return {"horse_id": horse_id, "reported_on": reported_on, "severity": severity}


def prescription_payload(
    lameness_case_id,
    issued_on,
    expires_on,
    limb_scope=None,
    prescribed_cycle_weeks=3,
) -> dict:
    return {
        "lameness_case_id": lameness_case_id,
        "issued_on": issued_on,
        "expires_on": expires_on,
        "limb_scope": list(limb_scope or ["LF", "RF", "LH", "RH"]),
        "prescribed_cycle_weeks": prescribed_cycle_weeks,
    }
