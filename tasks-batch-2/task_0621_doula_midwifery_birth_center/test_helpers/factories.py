"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Only source: input fields appear here; computed and
system fields (status, version, counters, snapshots) are never in a create body.
"""

DEFAULTS = {
    "KIT_SKU": "BK1",
    "KIT_NAME": "Birth Kit",
    "KIT_ON_HAND": 5,
    "PACKAGE_CODE": "PKG_BIRTH",
    "GLOBAL_FEE_CENTS": 800000,
    "PRENATAL_INCLUDED": 3,
    "POSTPARTUM_INCLUDED": 2,
    "CLIENT_NAME": "Ada A",
    "CLIENT_DOB": "1994-03-02",
    "EDD": "2026-08-01",
    "PROVIDER_NAME": "Pri Midwife",
    "LICENSE": "L-PRI",
    "MAX_ACTIVE": 2,
    "ROOM_NAME": "Garden Suite",
    "VISIT_SCHEDULED_AT": "2026-04-01T10:00:00Z",
    "COVERAGE_START": "2026-07-25T00:00:00Z",
    "COVERAGE_END": "2026-08-10T00:00:00Z",
    "BOOK_START": "2026-01-02T00:00:00Z",
    "BOOK_END": "2026-01-03T00:00:00Z",
}


def create_client_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["CLIENT_NAME"],
        "date_of_birth": DEFAULTS["CLIENT_DOB"],
        "parity": 0,
    }
    defaults.update(overrides)
    return defaults


def create_care_package_payload(**overrides) -> dict:
    defaults = {
        "code": DEFAULTS["PACKAGE_CODE"],
        "package_type": "BIRTH",
        "global_fee_cents": DEFAULTS["GLOBAL_FEE_CENTS"],
        "prenatal_visits_included": DEFAULTS["PRENATAL_INCLUDED"],
        "postpartum_visits_included": DEFAULTS["POSTPARTUM_INCLUDED"],
        "kit_sku": DEFAULTS["KIT_SKU"],
    }
    defaults.update(overrides)
    return defaults


def create_supply_kit_payload(**overrides) -> dict:
    defaults = {
        "sku": DEFAULTS["KIT_SKU"],
        "name": DEFAULTS["KIT_NAME"],
        "on_hand_count": DEFAULTS["KIT_ON_HAND"],
    }
    defaults.update(overrides)
    return defaults


def create_provider_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["PROVIDER_NAME"],
        "role_type": "MIDWIFE",
        "license_number": DEFAULTS["LICENSE"],
        "max_active_episodes": DEFAULTS["MAX_ACTIVE"],
    }
    defaults.update(overrides)
    return defaults


def create_room_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["ROOM_NAME"],
        "turnover_minutes": 0,
    }
    defaults.update(overrides)
    return defaults


def create_episode_payload(client_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "package_code": DEFAULTS["PACKAGE_CODE"],
        "edd": DEFAULTS["EDD"],
    }
    defaults.update(overrides)
    return defaults


def create_prenatal_visit_payload(episode_id, **overrides) -> dict:
    defaults = {
        "episode_id": episode_id,
        "visit_kind": "PRENATAL",
        "scheduled_at": DEFAULTS["VISIT_SCHEDULED_AT"],
    }
    defaults.update(overrides)
    return defaults


def complete_visit_payload(risk_flag="NONE", **overrides) -> dict:
    defaults = {"risk_flag": risk_flag}
    defaults.update(overrides)
    return defaults


def create_on_call_assignment_payload(episode_id, provider_id, **overrides) -> dict:
    defaults = {
        "episode_id": episode_id,
        "provider_id": provider_id,
        "coverage_start": DEFAULTS["COVERAGE_START"],
        "coverage_end": DEFAULTS["COVERAGE_END"],
    }
    defaults.update(overrides)
    return defaults


def name_backup_payload(provider_id, **overrides) -> dict:
    defaults = {
        "provider_id": provider_id,
        "coverage_start": DEFAULTS["COVERAGE_START"],
        "coverage_end": DEFAULTS["COVERAGE_END"],
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(episode_id, room_id, expected_room_version, **overrides) -> dict:
    defaults = {
        "episode_id": episode_id,
        "room_id": room_id,
        "starts_at": DEFAULTS["BOOK_START"],
        "ends_at": DEFAULTS["BOOK_END"],
        "expected_room_version": expected_room_version,
    }
    defaults.update(overrides)
    return defaults


def create_charge_payload(episode_id, charge_kind, amount_cents, **overrides) -> dict:
    defaults = {
        "episode_id": episode_id,
        "charge_kind": charge_kind,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_insurance_claim_payload(episode_id, **overrides) -> dict:
    defaults = {"episode_id": episode_id}
    defaults.update(overrides)
    return defaults


def adjudicate_payload(allowed_amount_cents, paid_amount_cents, **overrides) -> dict:
    defaults = {
        "allowed_amount_cents": allowed_amount_cents,
        "paid_amount_cents": paid_amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_payment_plan_payload(episode_id, installment_count, expected_episode_version, **overrides) -> dict:
    defaults = {
        "episode_id": episode_id,
        "installment_count": installment_count,
        "expected_episode_version": expected_episode_version,
    }
    defaults.update(overrides)
    return defaults


def payment_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults
