"""Payload factories — one per creatable resource, input fields only.

Field names follow the PRD endpoint definitions exactly.
"""


def create_client_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Client",
        "household_size": 2,
    }
    defaults.update(overrides)
    return defaults


def patch_client_payload(expected_client_version, **overrides) -> dict:
    defaults = {"expected_client_version": expected_client_version}
    defaults.update(overrides)
    return defaults


def checkin_visit_payload(voucher_id=None) -> dict:
    payload: dict = {}
    if voucher_id is not None:
        payload["voucher_id"] = voucher_id
    return payload


def add_line_payload(item_id) -> dict:
    return {"item_id": item_id}


def create_donation_batch_payload(**overrides) -> dict:
    defaults = {
        "donor_name": "Test Donor",
        "item_count_declared": 1,
    }
    defaults.update(overrides)
    return defaults


def create_item_payload(category="ADULT_TOPS", season="ALL_SEASON",
                        quality_grade="GOOD", drive_id=None, **overrides) -> dict:
    payload = {
        "category": category,
        "season": season,
        "quality_grade": quality_grade,
    }
    if drive_id is not None:
        payload["drive_id"] = drive_id
    payload.update(overrides)
    return payload


def stock_item_payload(storage_zone_id) -> dict:
    return {"storage_zone_id": storage_zone_id}


def release_quarantine_payload(outcome) -> dict:
    return {"outcome": outcome}


def create_storage_zone_payload(**overrides) -> dict:
    defaults = {
        "zone_code": "Z1",
        "season_policy": "ALL_SEASON",
        "capacity_items": 10,
    }
    defaults.update(overrides)
    return defaults


def patch_storage_zone_payload(expected_zone_version, **overrides) -> dict:
    defaults = {"expected_zone_version": expected_zone_version}
    defaults.update(overrides)
    return defaults


def create_seasonal_rotation_payload(**overrides) -> dict:
    defaults = {
        "target_season": "WINTER",
        "window_start": "2026-09-01T00:00:00Z",
        "window_end": "2026-09-02T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_volunteer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Vol One",
        "is_lead": False,
    }
    defaults.update(overrides)
    return defaults


def create_shift_payload(**overrides) -> dict:
    defaults = {
        "start_at": "2026-08-05T08:00:00Z",
        "end_at": "2026-08-05T12:00:00Z",
        "role_type": "FLOOR",
        "capacity_volunteers": 1,
    }
    defaults.update(overrides)
    return defaults


def create_signup_payload(volunteer_id) -> dict:
    return {"volunteer_id": volunteer_id}


def create_referral_partner_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Agency",
        "base_voucher_quota": 5,
    }
    defaults.update(overrides)
    return defaults


def issue_voucher_payload(client_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "bonus_items": 1,
        "expires_at": "2026-12-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_drive_payload(**overrides) -> dict:
    defaults = {
        "drive_type": "WINTER_COATS",
        "target_category": "COATS",
        "start_at": "2026-08-05T00:00:00Z",
        "end_at": "2026-08-10T00:00:00Z",
        "bonus_items_per_client": 1,
    }
    defaults.update(overrides)
    return defaults


def create_recycling_batch_payload(**overrides) -> dict:
    defaults = {
        "recycler_name": "TexCycle",
        "capacity_kg": 50,
    }
    defaults.update(overrides)
    return defaults


def pickup_payload(actual_weight_kg) -> dict:
    return {"actual_weight_kg": actual_weight_kg}
