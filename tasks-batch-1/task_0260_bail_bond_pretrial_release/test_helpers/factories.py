"""Payload factories — one per entity, input fields only.

Each factory returns a dict carrying only client-supplied (source: input) fields,
with sensible defaults; pass overrides to control any value.
"""
import itertools

# Monotonic counters so generated unique values never collide within a test.
_phone_counter = itertools.count(1)
_case_counter = itertools.count(1)
_serial_counter = itertools.count(1)


def _next_phone() -> str:
    return f"+1555{next(_phone_counter):07d}"


def _next_case_number() -> str:
    return f"CR-AUTO-{next(_case_counter):05d}"


def _next_serial() -> str:
    return f"GPS-AUTO-{next(_serial_counter):05d}"


def create_defendant_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Defendant",
        "date_of_birth": "1990-01-01",
        "phone_e164": _next_phone(),
        # risk_tier omitted -> server default MEDIUM, unless overridden.
    }
    defaults.update(overrides)
    return defaults


def create_bail_order_payload(**overrides) -> dict:
    defaults = {
        "case_number": _next_case_number(),
        "bail_amount_cents": 1_000_000,
        "bond_type_allowed": "SURETY",
        # condition_codes / gps_required omitted -> server defaults [] / false.
    }
    defaults.update(overrides)
    return defaults


def create_bond_payload(**overrides) -> dict:
    defaults = {
        "bond_type": "SURETY",
        "premium_rate_bps": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_indemnitor_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Indemnitor",
        "phone_e164": _next_phone(),
        "credit_limit_cents": 5_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_indemnity_agreement_payload(indemnitor_id, **overrides) -> dict:
    defaults = {
        "indemnitor_id": indemnitor_id,
        "liability_share_cents": 1_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_collateral_payload(**overrides) -> dict:
    defaults = {
        "kind": "CASH",
        "pledged_value_cents": 250_000,
    }
    defaults.update(overrides)
    return defaults


def create_court_date_payload(scheduled_utc, **overrides) -> dict:
    defaults = {
        "scheduled_utc": scheduled_utc,
        "duration_minutes": 60,
        # hearing_type omitted -> server default ARRAIGNMENT.
    }
    defaults.update(overrides)
    return defaults


def create_notify_payload(**overrides) -> dict:
    defaults = {
        "channel": "SMS",
    }
    defaults.update(overrides)
    return defaults


def create_check_in_payload(bond_id, condition_code, result, **overrides) -> dict:
    defaults = {
        "bond_id": bond_id,
        "condition_code": condition_code,
        "result": result,
    }
    defaults.update(overrides)
    return defaults


def create_gps_device_payload(**overrides) -> dict:
    defaults = {
        "serial_number": _next_serial(),
    }
    defaults.update(overrides)
    return defaults


def assign_gps_payload(device_id, **overrides) -> dict:
    defaults = {
        "device_id": device_id,
    }
    defaults.update(overrides)
    return defaults


def enter_judgment_payload(expected_bond_version, **overrides) -> dict:
    defaults = {
        "expected_bond_version": expected_bond_version,
    }
    defaults.update(overrides)
    return defaults


def remit_payload(remission_pct, **overrides) -> dict:
    defaults = {
        "remission_pct": remission_pct,
    }
    defaults.update(overrides)
    return defaults
