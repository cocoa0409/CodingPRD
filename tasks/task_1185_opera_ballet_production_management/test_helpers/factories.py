"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "PRODUCTION_TITLE": "Swan Lake",
    "WORK_TYPE": "BALLET",
    "BUILD_BUDGET_CENTS": 100_000_000,
    "SURTITLE_LANGUAGE": "en",
    "COMPANY_NAME": "PartnerCo",
    "ITEM_NAME": "Palace flat",
    "QUOTED_COST_CENTS": 1_000_000,
    "ARTIST_NAME": "Anna Principal",
    "HOURLY_RATE_CENTS": 8_000,
    "WEEKLY_HOURS_CAP": 30,
    "ROLE_NAME": "Odette/Odile",
    "ROOM_NAME": "Studio 1",
    "ROOM_CAPACITY": 40,
    "ROOM_RATE_CENTS": 5_000,
    "CUE_COUNT": 400,
    "PERFORMANCES_COUNT": 4,
    "PER_PERFORMANCE_FEE_CENTS": 500_000,
    "WINDOW_START": "2026-09-01T00:00:00Z",
    "WINDOW_END": "2026-09-30T00:00:00Z",
}


def create_partner_company_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["COMPANY_NAME"],
        "partner_kind": "CO_PRODUCER",
    }
    defaults.update(overrides)
    return defaults


def create_production_payload(**overrides) -> dict:
    defaults = {
        "title": DEFAULTS["PRODUCTION_TITLE"],
        "work_type": DEFAULTS["WORK_TYPE"],
        "build_budget_cents": DEFAULTS["BUILD_BUDGET_CENTS"],
        "default_surtitle_language": DEFAULTS["SURTITLE_LANGUAGE"],
    }
    defaults.update(overrides)
    return defaults


def create_build_item_payload(production_id, **overrides) -> dict:
    defaults = {
        "production_id": production_id,
        "item_kind": "SET",
        "name": DEFAULTS["ITEM_NAME"],
        "quoted_cost_cents": DEFAULTS["QUOTED_COST_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_co_production_share_payload(production_id, company_id, **overrides) -> dict:
    defaults = {
        "production_id": production_id,
        "company_id": company_id,
        "share_percentage": 40,
        "cost_split_method": "GROSS_COST",
    }
    defaults.update(overrides)
    return defaults


def create_artist_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["ARTIST_NAME"],
        "discipline": "PRINCIPAL_DANCER",
        "union_code": "AGMA",
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(production_id, artist_id, **overrides) -> dict:
    defaults = {
        "production_id": production_id,
        "artist_id": artist_id,
        "engagement_type": "PRINCIPAL",
        "hourly_rate_cents": DEFAULTS["HOURLY_RATE_CENTS"],
        "weekly_hours_cap": DEFAULTS["WEEKLY_HOURS_CAP"],
    }
    defaults.update(overrides)
    return defaults


def create_role_payload(production_id, **overrides) -> dict:
    defaults = {
        "production_id": production_id,
        "role_name": DEFAULTS["ROLE_NAME"],
        "voice_type": "DANCER_F",
    }
    defaults.update(overrides)
    return defaults


def create_cast_assignment_payload(role_id, contract_id, **overrides) -> dict:
    defaults = {
        "role_id": role_id,
        "contract_id": contract_id,
        "slot": "PRINCIPAL",
    }
    defaults.update(overrides)
    return defaults


def create_rehearsal_room_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["ROOM_NAME"],
        "kind": "STUDIO",
        "capacity": DEFAULTS["ROOM_CAPACITY"],
        "hourly_rate_cents": DEFAULTS["ROOM_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_rehearsal_call_payload(production_id, room_id, starts_at, ends_at, **overrides) -> dict:
    defaults = {
        "production_id": production_id,
        "room_id": room_id,
        "call_type": "DANCE_CALL",
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    defaults.update(overrides)
    return defaults


def create_call_participant_payload(call_id, contract_id, **overrides) -> dict:
    defaults = {
        "call_id": call_id,
        "contract_id": contract_id,
    }
    defaults.update(overrides)
    return defaults


def create_stage_slot_payload(production_id, starts_at, ends_at, **overrides) -> dict:
    defaults = {
        "production_id": production_id,
        "slot_type": "TECH",
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    defaults.update(overrides)
    return defaults


def create_performance_payload(production_id, starts_at, ends_at, sections=None, **overrides) -> dict:
    defaults = {
        "production_id": production_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "sections": sections
        or [{"section": "STALLS", "total_seats": 50, "base_price_cents": 15_000}],
    }
    defaults.update(overrides)
    return defaults


def create_surtitle_track_payload(production_id, **overrides) -> dict:
    defaults = {
        "production_id": production_id,
        "language": DEFAULTS["SURTITLE_LANGUAGE"],
        "cue_count": DEFAULTS["CUE_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_rental_offer_payload(production_id, renter_company_id, expected_production_version, **overrides) -> dict:
    defaults = {
        "production_id": production_id,
        "renter_company_id": renter_company_id,
        "window_start": DEFAULTS["WINDOW_START"],
        "window_end": DEFAULTS["WINDOW_END"],
        "performances_count": DEFAULTS["PERFORMANCES_COUNT"],
        "per_performance_fee_cents": DEFAULTS["PER_PERFORMANCE_FEE_CENTS"],
        "expected_production_version": expected_production_version,
    }
    defaults.update(overrides)
    return defaults
