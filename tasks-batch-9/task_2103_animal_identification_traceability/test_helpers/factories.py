"""Payload factories — one per write endpoint, input fields only."""
import itertools

from .constants import DEFAULT_AID_PREFIX, DEFAULT_SERIAL_START

# ---------------------------------------------------------------------------
# Unique-value generators.
#
# `pin` is globally unique across the programme and `supplier_code` is globally
# unique too, so every fixture that does not care about the exact value draws a
# fresh one from these counters.
# ---------------------------------------------------------------------------
_pin_counter = itertools.count(1)
_supplier_code_counter = itertools.count(1)


def next_pin() -> str:
    """Fresh seven-character Premises Identification Number over [0-9A-Z]."""
    return "P{:06d}".format(next(_pin_counter))


def next_supplier_code() -> str:
    """Fresh four-character supplier code over [A-Z0-9]."""
    return "S{:03d}".format(next(_supplier_code_counter) % 1000)


def ain_for_serial(serial: int, aid_prefix: str = DEFAULT_AID_PREFIX) -> str:
    """Build a 15-digit AIN: three-digit prefix plus a twelve-digit serial."""
    return "{}{:012d}".format(aid_prefix, serial)


DEFAULTS = {
    "PRODUCER_NAME": "Test Cattle Company",
    "CONTACT_EMAIL": "ops@test-cattle.example",
    "STATE_CODE": "CO",
    "OPERATION_TYPE": "COW_CALF",
    "CAPACITY": 10,
    "SUPPLIER_NAME": "Test Device Works",
    "SPECIES": "BOVINE",
    "BIRTH_DATE": "2026-03-01",
    "PERIOD_START": "2026-08-01",
    "PERIOD_END": "2026-08-31",
    "LOT_QUANTITY": 10,
}


# --------------------------------------------------------------------------
# Producer / Premises
# --------------------------------------------------------------------------
def create_producer_payload(**overrides) -> dict:
    payload = {
        "legal_name": DEFAULTS["PRODUCER_NAME"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
        "state_code": DEFAULTS["STATE_CODE"],
    }
    payload.update(overrides)
    return payload


def create_premises_payload(producer_id: str, **overrides) -> dict:
    payload = {
        "producer_id": producer_id,
        "pin": next_pin(),
        "operation_type": DEFAULTS["OPERATION_TYPE"],
        "state_code": DEFAULTS["STATE_CODE"],
        "capacity": DEFAULTS["CAPACITY"],
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Device supplier
# --------------------------------------------------------------------------
def create_device_supplier_payload(**overrides) -> dict:
    payload = {
        "company_name": DEFAULTS["SUPPLIER_NAME"],
        "supplier_code": next_supplier_code(),
    }
    payload.update(overrides)
    return payload


def defect_report_payload(defect_count: int, **overrides) -> dict:
    payload = {"defect_count": defect_count}
    payload.update(overrides)
    return payload


def reinstate_payload(forgiven_defects: int) -> dict:
    return {"forgiven_defects": forgiven_defects}


# --------------------------------------------------------------------------
# Tag lot / tag
# --------------------------------------------------------------------------
def create_tag_lot_payload(
    supplier_id: str,
    premises_id: str,
    expected_supplier_version: int,
    serial_start: int = DEFAULT_SERIAL_START,
    quantity: int = None,
    **overrides,
) -> dict:
    if quantity is None:
        quantity = DEFAULTS["LOT_QUANTITY"]
    payload = {
        "supplier_id": supplier_id,
        "premises_id": premises_id,
        "serial_start": serial_start,
        "serial_end": serial_start + quantity - 1,
        "expected_supplier_version": expected_supplier_version,
    }
    payload.update(overrides)
    return payload


def apply_tag_payload(ain: str, birth_premises_id: str, **overrides) -> dict:
    payload = {
        "ain": ain,
        "species": DEFAULTS["SPECIES"],
        "birth_date": DEFAULTS["BIRTH_DATE"],
        "birth_premises_id": birth_premises_id,
    }
    payload.update(overrides)
    return payload


def replace_tag_payload(replacement_ain: str, tag_lot_id: str) -> dict:
    return {"replacement_ain": replacement_ain, "tag_lot_id": tag_lot_id}


def retire_tag_payload(
    harvest_premises_id: str,
    harvested_at: str,
    carcass_ref: str = "CARC-0001",
    tag_returned: bool = True,
) -> dict:
    return {
        "harvest_premises_id": harvest_premises_id,
        "harvested_at": harvested_at,
        "carcass_ref": carcass_ref,
        "tag_returned": tag_returned,
    }


# --------------------------------------------------------------------------
# Movement events
# --------------------------------------------------------------------------
def create_movement_payload(
    animal_id: str,
    origin_premises_id: str,
    destination_premises_id: str,
    departed_at: str,
    **overrides,
) -> dict:
    payload = {
        "animal_id": animal_id,
        "origin_premises_id": origin_premises_id,
        "destination_premises_id": destination_premises_id,
        "departed_at": departed_at,
    }
    payload.update(overrides)
    return payload


def receive_movement_payload(arrived_at: str) -> dict:
    return {"arrived_at": arrived_at}


def dispute_movement_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


def correct_movement_payload(departed_at: str, **overrides) -> dict:
    payload = {"departed_at": departed_at}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Trace requests
# --------------------------------------------------------------------------
def create_trace_request_payload(index_animal_id: str, **overrides) -> dict:
    payload = {
        "index_animal_id": index_animal_id,
        "pathogen_class": "DIRECT_CONTACT",
        "direction": "BOTH",
        "lookback_days": 30,
        "max_hops": 3,
    }
    payload.update(overrides)
    return payload


def respond_hit_payload(resolved: bool) -> dict:
    return {"resolved": resolved}


# --------------------------------------------------------------------------
# Hold orders
# --------------------------------------------------------------------------
def create_hold_order_payload(
    premises_id: str,
    expected_premises_version: int,
    effective_from: str = "2026-08-01T00:00:00Z",
    effective_until: str = "2026-08-30T00:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "premises_id": premises_id,
        "effective_from": effective_from,
        "effective_until": effective_until,
        "expected_premises_version": expected_premises_version,
    }
    payload.update(overrides)
    return payload


def appeal_hold_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Reconciliation runs
# --------------------------------------------------------------------------
def create_reconciliation_run_payload(
    premises_id: str,
    expected_premises_version: int,
    period_start: str = DEFAULTS["PERIOD_START"],
    period_end: str = DEFAULTS["PERIOD_END"],
    **overrides,
) -> dict:
    payload = {
        "premises_id": premises_id,
        "period_start": period_start,
        "period_end": period_end,
        "expected_premises_version": expected_premises_version,
    }
    payload.update(overrides)
    return payload


def submit_reconciliation_payload(physical_unapplied_count: int) -> dict:
    return {"physical_unapplied_count": physical_unapplied_count}


# --------------------------------------------------------------------------
# Incentive awards
# --------------------------------------------------------------------------
def create_incentive_award_payload(
    producer_id: str,
    period_start: str = "2026-07-01",
    period_end: str = "2026-09-30",
    **overrides,
) -> dict:
    payload = {
        "producer_id": producer_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Programme clock
# --------------------------------------------------------------------------
def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
