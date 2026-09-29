"""Request-body builders.

Each builder returns the minimal valid body for its endpoint and merges any
keyword overrides on top, so a test that wants one field wrong writes only that
field. `without()` strips a key so the required-field branch of PRD §2.6 band 30
can be exercised without hand-writing a whole body.
"""

import itertools
from typing import Any, Dict, List, Optional

from .constants import (
    AIRLINE_AN,
    FLIGHT_NUMBER,
    SERVICE_DATE,
    SPEC_AN_C,
    SPEC_AN_F,
    SPEC_AN_V,
    SPEC_AN_Y,
    STAND_CODE,
    STATION_CODE,
    STD_UTC,
    TAIL_NUMBER,
    TRUCK_REGISTRATION,
)

_counter = itertools.count(1)


def next_seq() -> int:
    """A process-unique integer for building unique codes."""
    return next(_counter)


def unique_iata_code() -> str:
    """A two-uppercase-letter code, unique within one test process."""
    n = next_seq()
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return alphabet[(n // 26) % 26] + alphabet[n % 26]


def unique_spec_code(prefix: str = "SPEC") -> str:
    return "%s-%04d" % (prefix, next_seq())


def unique_seal_number(prefix: str = "SEAL") -> str:
    return "%s-%04d" % (prefix, next_seq())


def unique_registration(prefix: str = "HL") -> str:
    return "%s-%04d" % (prefix, next_seq())


def unique_stand_code(prefix: str = "B") -> str:
    return "%s%02d" % (prefix, next_seq() % 100)


def unique_seat_number() -> str:
    n = next_seq()
    return "%d%s" % (10 + (n % 40), "ABCDEF"[n % 6])


def without(payload: Dict[str, Any], *keys: str) -> Dict[str, Any]:
    """A copy of `payload` with `keys` removed."""
    stripped = dict(payload)
    for key in keys:
        stripped.pop(key, None)
    return stripped


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------


def airline_payload(**overrides: Any) -> Dict[str, Any]:
    """`name`, `iata_code`, `waste_regime` and `cost_cap_per_pax_cents` (PRD §3.1)."""
    base = dict(AIRLINE_AN)
    base["iata_code"] = overrides.pop("iata_code", unique_iata_code())
    return _merge(base, overrides)


def spec_payload(airline_id: str, template: Dict[str, Any], **overrides: Any):
    """One meal specification under `airline_id` (PRD §3.1)."""
    base = dict(template)
    base["airline_id"] = airline_id
    return _merge(base, overrides)


def spec_first_payload(airline_id: str, **overrides: Any) -> Dict[str, Any]:
    return spec_payload(airline_id, SPEC_AN_F, **overrides)


def spec_business_payload(airline_id: str, **overrides: Any) -> Dict[str, Any]:
    return spec_payload(airline_id, SPEC_AN_C, **overrides)


def spec_economy_payload(airline_id: str, **overrides: Any) -> Dict[str, Any]:
    return spec_payload(airline_id, SPEC_AN_Y, **overrides)


def spec_vgml_payload(airline_id: str, **overrides: Any) -> Dict[str, Any]:
    return spec_payload(airline_id, SPEC_AN_V, **overrides)


def truck_payload(**overrides: Any) -> Dict[str, Any]:
    """`station_code` and `registration` are required (PRD §3.7)."""
    base = {
        "station_code": STATION_CODE,
        "registration": TRUCK_REGISTRATION,
    }
    return _merge(base, overrides)


def stand_payload(**overrides: Any) -> Dict[str, Any]:
    """`station_code` and `stand_code` are required (PRD §3.7)."""
    base = {
        "station_code": STATION_CODE,
        "stand_code": STAND_CODE,
    }
    return _merge(base, overrides)


# ---------------------------------------------------------------------------
# Flights
# ---------------------------------------------------------------------------


def flight_payload(airline_id: str, **overrides: Any) -> Dict[str, Any]:
    """The full required intake body of PRD §3.2."""
    base = {
        "airline_id": airline_id,
        "flight_number": FLIGHT_NUMBER,
        "service_date": SERVICE_DATE,
        "std_utc": STD_UTC,
        "tail_number": TAIL_NUMBER,
        "station_code": STATION_CODE,
    }
    return _merge(base, overrides)


def pax_counts_payload(**overrides: Any) -> Dict[str, Any]:
    """"A passenger-count refresh may carry any subset" (PRD §3.2)."""
    return dict(overrides)


def retime_payload(std_utc: str) -> Dict[str, Any]:
    return {"std_utc": std_utc}


def delay_payload(delay_minutes: int, **overrides: Any) -> Dict[str, Any]:
    return _merge({"delay_minutes": delay_minutes}, overrides)


# ---------------------------------------------------------------------------
# Special meal orders
# ---------------------------------------------------------------------------


def order_payload(
    flight_id: str, meal_specification_id: str, seat_number: str, **overrides: Any
) -> Dict[str, Any]:
    base = {
        "flight_id": flight_id,
        "meal_specification_id": meal_specification_id,
        "passenger_ref": "PNR%05d" % next_seq(),
        "seat_number": seat_number,
    }
    return _merge(base, overrides)


def cancel_order_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"action": "CANCEL"}, overrides)


def substitute_order_payload(
    substitute_meal_specification_id: str, **overrides: Any
) -> Dict[str, Any]:
    base = {
        "action": "SUBSTITUTE",
        "substitute_meal_specification_id": substitute_meal_specification_id,
    }
    return _merge(base, overrides)


# ---------------------------------------------------------------------------
# Production
# ---------------------------------------------------------------------------


def haccp_payload(step_code: str, measured_temp_c: float, **overrides: Any):
    base = {"step_code": step_code, "measured_temp_c": measured_temp_c}
    return _merge(base, overrides)


def complete_payload(produced_qty: int, **overrides: Any) -> Dict[str, Any]:
    return _merge({"produced_qty": produced_qty}, overrides)


# ---------------------------------------------------------------------------
# Carts, items and manifests
# ---------------------------------------------------------------------------


def cart_payload(
    flight_id: str,
    cart_code: str,
    cart_type: str,
    storage_class: str,
    capacity_units: int,
    **overrides: Any
) -> Dict[str, Any]:
    base = {
        "flight_id": flight_id,
        "cart_code": cart_code,
        "cart_type": cart_type,
        "storage_class": storage_class,
        "capacity_units": capacity_units,
    }
    return _merge(base, overrides)


def cart_item_payload(
    production_batch_id: str, qty_units: int, **overrides: Any
) -> Dict[str, Any]:
    base = {"production_batch_id": production_batch_id, "qty_units": qty_units}
    return _merge(base, overrides)


def seal_payload(
    expected_cart_version: int, seal_number: str, **overrides: Any
) -> Dict[str, Any]:
    """`expected_cart_version` is "a non-optional field of its request body" (PRD §2.7)."""
    base = {
        "expected_cart_version": expected_cart_version,
        "seal_number": seal_number,
    }
    return _merge(base, overrides)


def manifest_payload(expected_flight_version: int, **overrides: Any) -> Dict[str, Any]:
    return _merge({"expected_flight_version": expected_flight_version}, overrides)


# ---------------------------------------------------------------------------
# Delivery runs
# ---------------------------------------------------------------------------


def run_payload(
    loading_manifest_id: str,
    truck_id: str,
    stand_id: str,
    window_start_utc: str,
    window_end_utc: str,
    **overrides: Any
) -> Dict[str, Any]:
    base = {
        "loading_manifest_id": loading_manifest_id,
        "truck_id": truck_id,
        "stand_id": stand_id,
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
    }
    return _merge(base, overrides)


def recovery_run_payload(
    truck_id: str,
    stand_id: str,
    window_start_utc: str,
    window_end_utc: str,
    **overrides: Any
) -> Dict[str, Any]:
    base = {
        "truck_id": truck_id,
        "stand_id": stand_id,
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
    }
    return _merge(base, overrides)


def event_payload(event_type: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"event_type": event_type}, overrides)


# ---------------------------------------------------------------------------
# Uplift, disposition and waste
# ---------------------------------------------------------------------------


def uplift_line(
    meal_specification_id: str, consumed_units: int, returned_units: int
) -> Dict[str, Any]:
    return {
        "meal_specification_id": meal_specification_id,
        "consumed_units": consumed_units,
        "returned_units": returned_units,
    }


def uplift_payload(
    expected_flight_version: int,
    lines: List[Dict[str, Any]],
    observed_seals: Optional[List[str]] = None,
    **overrides: Any
) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "expected_flight_version": expected_flight_version,
        "lines": lines,
    }
    if observed_seals is not None:
        base["observed_seals"] = observed_seals
    return _merge(base, overrides)


def disposition_line(
    meal_specification_id: str,
    reuse_units: int = 0,
    donate_units: int = 0,
    destroy_units: int = 0,
) -> Dict[str, Any]:
    return {
        "meal_specification_id": meal_specification_id,
        "reuse_units": reuse_units,
        "donate_units": donate_units,
        "destroy_units": destroy_units,
    }


def dispositions_payload(
    dispositions: List[Dict[str, Any]], **overrides: Any
) -> Dict[str, Any]:
    return _merge({"dispositions": dispositions}, overrides)


def waste_manifest_payload(
    uplift_record_id: str, disposal_method: str, seal_number: str, **overrides: Any
) -> Dict[str, Any]:
    base = {
        "uplift_record_id": uplift_record_id,
        "disposal_method": disposal_method,
        "seal_number": seal_number,
    }
    return _merge(base, overrides)


def waste_transition_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


# ---------------------------------------------------------------------------
# The audit docket
# ---------------------------------------------------------------------------


def finding_payload(
    airline_id: str,
    flight_id: Optional[str],
    finding_type: str,
    severity: str,
    **overrides: Any
) -> Dict[str, Any]:
    base = {
        "airline_id": airline_id,
        "flight_id": flight_id,
        "finding_type": finding_type,
        "severity": severity,
    }
    return _merge(base, overrides)


def resolution_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)
