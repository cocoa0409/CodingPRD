"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import uuid

ALL_CATEGORY_CAPS = {
    "FOOD_BEVERAGE": 5,
    "CRAFT": 5,
    "APPAREL": 5,
    "HOME_GOODS": 5,
    "EXPERIENCE": 5,
}


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def create_market_payload(**overrides) -> dict:
    """Market creation payload. jury_quorum / shared_pos_enabled /
    shared_pos_fee_bps / weather_alert_threshold_wind_mph are omitted so the
    PRD-declared server defaults apply unless a test overrides them."""
    defaults = {
        "name": "Holiday Market",
        "season_code": _uniq("WINTER"),
        "opens_at": "2026-12-01T00:00:00Z",
        "closes_at": "2026-12-31T23:59:59Z",
        "application_opens_at": "2026-09-01T00:00:00Z",
        "application_closes_at": "2026-11-01T00:00:00Z",
        "category_caps": dict(ALL_CATEGORY_CAPS),
        "chalet_count": 2,
        "standard_booth_count": 10,
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Vendor Co",
        "contact_email": f"{_uniq('vendor')}@example.com",
        "category": "CRAFT",
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(vendor_id: str, requested_booth_type: str = "STANDARD",
                               **overrides) -> dict:
    defaults = {
        "vendor_id": vendor_id,
        "requested_booth_type": requested_booth_type,
    }
    defaults.update(overrides)
    return defaults


def create_booth_payload(**overrides) -> dict:
    defaults = {
        "booth_code": _uniq("STD"),
        "booth_type": "STANDARD",
        "zone": "NORTH",
        "square_feet": 80,
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(booth_id: str, application_id: str, **overrides) -> dict:
    defaults = {
        "booth_id": booth_id,
        "application_id": application_id,
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(assignment_id: str, permit_type: str = "TEMP_STRUCTURE",
                          **overrides) -> dict:
    defaults = {
        "assignment_id": assignment_id,
        "permit_type": permit_type,
        "issued_by": "CITY-FIRE-DEPT",
        "issued_at": "2026-11-01T00:00:00Z",
        "expires_at": "2026-12-31T23:59:59Z",
    }
    defaults.update(overrides)
    return defaults


def create_hookup_payload(booth_id: str, hookup_type: str = "ELECTRIC_15A",
                          **overrides) -> dict:
    defaults = {
        "booth_id": booth_id,
        "hookup_type": hookup_type,
    }
    defaults.update(overrides)
    return defaults


def create_pos_device_payload(assignment_id: str, **overrides) -> dict:
    defaults = {
        "assignment_id": assignment_id,
        "device_code": _uniq("DEV"),
    }
    defaults.update(overrides)
    return defaults


def create_settlement_payload(assignment_id: str, business_date: str,
                              gross_card_cents: int, gross_cash_cents: int,
                              **overrides) -> dict:
    defaults = {
        "assignment_id": assignment_id,
        "business_date": business_date,
        "gross_card_cents": gross_card_cents,
        "gross_cash_cents": gross_cash_cents,
    }
    defaults.update(overrides)
    return defaults


def create_programming_slot_payload(**overrides) -> dict:
    defaults = {
        "title": "Main Stage Act",
        "slot_kind": "MUSIC",
        "starts_at": "2026-12-10T10:00:00Z",
        "ends_at": "2026-12-10T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_load_slot_payload(assignment_id: str, **overrides) -> dict:
    defaults = {
        "assignment_id": assignment_id,
        "direction": "LOAD_IN",
        "starts_at": "2026-12-05T08:00:00Z",
        "ends_at": "2026-12-05T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_weather_event_payload(**overrides) -> dict:
    defaults = {
        "observed_at": "2026-12-05T12:00:00Z",
        "wind_mph": 10,
        "temp_f": 30,
        "precipitation": "NONE",
        "source": "ON_SITE_SENSOR",
    }
    defaults.update(overrides)
    return defaults


def create_renewal_offer_payload(vendor_id: str, prior_assignment_id: str,
                                 offered_booth_id: str, **overrides) -> dict:
    defaults = {
        "vendor_id": vendor_id,
        "prior_assignment_id": prior_assignment_id,
        "offered_booth_id": offered_booth_id,
        "offer_expires_at": "2027-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
