"""Payload factories — one per creatable resource, input fields only (PRD §4)."""
from .constants import DEFAULTS, TERMINAL_DEFAULTS, T_TRAIN_DEPARTURE


def create_terminal_payload(**overrides) -> dict:
    defaults = dict(TERMINAL_DEFAULTS)
    defaults.update(overrides)
    return defaults


def create_slot_payload(**overrides) -> dict:
    defaults = {
        "slot_code": DEFAULTS["SLOT_CODE"],
        "row": DEFAULTS["SLOT_ROW"],
        "tier_max": DEFAULTS["TIER_MAX"],
    }
    defaults.update(overrides)
    return defaults


def create_pool_payload(**overrides) -> dict:
    defaults = {"pool_code": DEFAULTS["POOL_CODE"]}
    defaults.update(overrides)
    return defaults


def create_chassis_payload(**overrides) -> dict:
    defaults = {"chassis_number": DEFAULTS["CHASSIS_NUMBER"]}
    defaults.update(overrides)
    return defaults


def create_carrier_payload(**overrides) -> dict:
    defaults = {
        "scac_code": DEFAULTS["SCAC_CODE"],
        "carrier_name": DEFAULTS["CARRIER_NAME"],
        "billing_credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_membership_payload(carrier_id, **overrides) -> dict:
    defaults = {"carrier_id": carrier_id}
    defaults.update(overrides)
    return defaults


def load_flip_credit_payload(credit_cents, **overrides) -> dict:
    defaults = {"credit_cents": credit_cents}
    defaults.update(overrides)
    return defaults


def create_train_payload(**overrides) -> dict:
    defaults = {
        "train_symbol": DEFAULTS["TRAIN_SYMBOL"],
        "scheduled_departure_utc": T_TRAIN_DEPARTURE,
    }
    defaults.update(overrides)
    return defaults


def create_container_payload(planned_train_id, **overrides) -> dict:
    defaults = {
        "container_number": DEFAULTS["CONTAINER_NUMBER"],
        "iso_type": DEFAULTS["ISO_TYPE"],
        "planned_train_id": planned_train_id,
    }
    defaults.update(overrides)
    return defaults


def ground_container_payload(expected_terminal_version, **overrides) -> dict:
    defaults = {"expected_terminal_version": expected_terminal_version}
    defaults.update(overrides)
    return defaults


def create_appointment_payload(carrier_id, container_id, direction,
                               window_start_utc, window_end_utc,
                               **overrides) -> dict:
    defaults = {
        "carrier_id": carrier_id,
        "container_id": container_id,
        "direction": direction,
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
    }
    defaults.update(overrides)
    return defaults


def check_in_payload(driver_id=DEFAULTS["DRIVER_ID"], **overrides) -> dict:
    defaults = {"driver_id": driver_id}
    defaults.update(overrides)
    return defaults


def reserve_chassis_payload(appointment_id, expected_pool_version,
                            **overrides) -> dict:
    defaults = {
        "appointment_id": appointment_id,
        "expected_pool_version": expected_pool_version,
    }
    defaults.update(overrides)
    return defaults


def create_transaction_payload(appointment_id, driver_id=DEFAULTS["DRIVER_ID"],
                               gate_lane=DEFAULTS["GATE_LANE"], chassis_id=None,
                               **overrides) -> dict:
    defaults = {
        "appointment_id": appointment_id,
        "driver_id": driver_id,
        "gate_lane": gate_lane,
    }
    if chassis_id is not None:
        defaults["chassis_id"] = chassis_id
    defaults.update(overrides)
    return defaults


def create_damage_payload(gate_transaction_id, damage_kind, severity,
                          repair_cost_cents, chassis_id=None, container_id=None,
                          **overrides) -> dict:
    defaults = {
        "gate_transaction_id": gate_transaction_id,
        "damage_kind": damage_kind,
        "severity": severity,
        "repair_cost_cents": repair_cost_cents,
    }
    if chassis_id is not None:
        defaults["chassis_id"] = chassis_id
    if container_id is not None:
        defaults["container_id"] = container_id
    defaults.update(overrides)
    return defaults


def apply_ledger_payload(apply_cents, expected_carrier_version, **overrides) -> dict:
    defaults = {
        "apply_cents": apply_cents,
        "expected_carrier_version": expected_carrier_version,
    }
    defaults.update(overrides)
    return defaults
