"""
Request-body factories for every write endpoint of the Berry Harvest Ops API.

Each factory returns a complete, valid body for the happy path and accepts
``**overrides`` so a test can bend exactly one field. Numeric fields are
emitted as JSON numbers, never as strings: PRD section 2.6 declares money as
"integer cents" and pounds, hours, temperatures, rates and ratios as decimal
quantities, so the wire types must match.

Each test runs against a freshly started service with an empty database, so
the default names below are unique within a test by construction; a test that
asserts a derived ``traceability_code`` passes its own block name explicitly
because PRD section 3.6 composes that code from the block's ``block_name``.
"""

import itertools
from typing import Any, Dict, Optional

from .constants import CLOCK_DEFAULT

_counter = itertools.count(1)


def _next(prefix: str) -> str:
    return f"{prefix}-{next(_counter):04d}"


# ─── Production blocks (PRD 3.1) ──────────────────────────────────────────


def block_payload(**overrides: Any) -> Dict[str, Any]:
    """
    A registrable production block.

    PRD 3.1: a "`name` of between 1 and 80 characters", the planted
    ``variety``, "the planted `acres`, a positive figure carried to two
    decimals", a ``planting_year`` "between 2000 and 2026 inclusive", and an
    ``irrigation_source_code`` of 1 to 32 characters.
    """
    payload: Dict[str, Any] = {
        "name": _next("BLK"),
        "variety": "STRAWBERRY",
        "acres": 10.00,
        "planting_year": 2021,
        "irrigation_source_code": "CANAL-1",
    }
    payload.update(overrides)
    return payload


def quarantine_payload(**overrides: Any) -> Dict[str, Any]:
    """A manual food-safety hold (PRD 3.1 "The quarantine cascade")."""
    payload: Dict[str, Any] = {"quarantine_reason_code": "ADJACENT_LIVESTOCK"}
    payload.update(overrides)
    return payload


# ─── Agricultural water register (PRD 3.1) ────────────────────────────────


def water_test_payload(block_id: str, **overrides: Any) -> Dict[str, Any]:
    """
    One agricultural-water sample.

    PRD 3.1: the officer supplies "the `block_id` of the block whose
    irrigation source was drawn, the `sample_date` on which it was drawn as a
    calendar date, and `generic_ecoli_mpn` ... which must be at least 1 and no
    more than 100000".
    """
    payload: Dict[str, Any] = {
        "block_id": block_id,
        "sample_date": "2026-07-20",
        "generic_ecoli_mpn": 40,
    }
    payload.update(overrides)
    return payload


# ─── Crews and pickers (PRD 3.2) ──────────────────────────────────────────


def crew_payload(**overrides: Any) -> Dict[str, Any]:
    """
    A recruitable harvest crew.

    PRD 3.2: "a crew `name` of 1 to 80 characters, a `labor_program` of either
    `DOMESTIC` or `H2A`, a `supervisor_user_id` of 1 to 64 characters ..., a
    contracted `planned_head_count` between 1 and 60, and the engagement dates
    `contract_start_date` and `contract_end_date`".
    """
    payload: Dict[str, Any] = {
        "name": _next("CREW"),
        "labor_program": "DOMESTIC",
        "supervisor_user_id": "sup-1",
        "planned_head_count": 1,
        "contract_start_date": "2026-07-01",
        "contract_end_date": "2026-10-31",
    }
    payload.update(overrides)
    return payload


def picker_payload(crew_id: str, **overrides: Any) -> Dict[str, Any]:
    """
    A registrable picker.

    PRD 3.2: the caller supplies "the target `crew_id`, the worker's
    `full_name` of 1 to 80 characters, and optionally `hygiene_training_on`".
    """
    payload: Dict[str, Any] = {
        "crew_id": crew_id,
        "full_name": _next("Picker"),
        "hygiene_training_on": "2026-06-01",
    }
    payload.update(overrides)
    return payload


def hygiene_training_payload(**overrides: Any) -> Dict[str, Any]:
    """A fresh hygiene-training date (PRD 3.2 "Training lapses")."""
    payload: Dict[str, Any] = {"hygiene_training_on": "2026-07-15"}
    payload.update(overrides)
    return payload


def support_plan_payload(head_count: int = 1, **overrides: Any) -> Dict[str, Any]:
    """
    A crew support plan that is complete for either labor program.

    PRD 3.2: "For every crew, `transport_route_code` must be present and
    `vehicle_seats` must be at least `planned_head_count`. For an `H2A` crew
    there is an additional employer-provided-housing obligation:
    `housing_unit_code` must also be present and `beds_confirmed` must also be
    at least `planned_head_count`."
    """
    payload: Dict[str, Any] = {
        "housing_unit_code": _next("HOUSE"),
        "beds_confirmed": head_count,
        "transport_route_code": _next("ROUTE"),
        "vehicle_seats": head_count,
    }
    payload.update(overrides)
    return payload


# ─── Harvest windows (PRD 3.3) ────────────────────────────────────────────


def harvest_window_payload(
    block_id: str, crew_id: str, **overrides: Any
) -> Dict[str, Any]:
    """
    A plannable harvest window.

    PRD 3.3: "`end_at` must be strictly after `start_at` **and** must fall on
    the same calendar date — a window is a shift, not a multi-day campaign."
    The default is an eight-hour shift on 2026-08-03.
    """
    payload: Dict[str, Any] = {
        "block_id": block_id,
        "crew_id": crew_id,
        "start_at": "2026-08-03T06:00:00Z",
        "end_at": "2026-08-03T14:00:00Z",
        "forecast_brix": 8.5,
        "planned_volume_lbs": 150.00,
        "piece_rate_cents_per_clamshell": 45,
        "clamshell_net_weight_lbs": 1.00,
    }
    payload.update(overrides)
    return payload


def cancel_window_payload(**overrides: Any) -> Dict[str, Any]:
    """A window cancellation reason code (PRD 3.3 "Cancellation")."""
    payload: Dict[str, Any] = {"cancel_reason_code": "WEATHER"}
    payload.update(overrides)
    return payload


# ─── Pick sessions (PRD 3.4) ──────────────────────────────────────────────


def pick_session_payload(
    harvest_window_id: str, picker_id: str, **overrides: Any
) -> Dict[str, Any]:
    """
    A pick session for one worker's day on one window.

    PRD 3.4: the supervisor supplies "the `harvest_window_id` of the window
    being worked, the `picker_id` of the worker, and the `work_date` on which
    they worked".
    """
    payload: Dict[str, Any] = {
        "harvest_window_id": harvest_window_id,
        "picker_id": picker_id,
        "work_date": "2026-08-03",
    }
    payload.update(overrides)
    return payload


def tally_payload(**overrides: Any) -> Dict[str, Any]:
    """
    A row-pack tally.

    PRD 3.4: "`hours_worked`, the clock hours on the row, greater than zero
    and no more than 16.00, carried to two decimals; `clamshells_filled` ...
    zero or greater; and `culled_clamshells` ... never more than
    `clamshells_filled`".
    """
    payload: Dict[str, Any] = {
        "hours_worked": 3.00,
        "clamshells_filled": 20,
        "culled_clamshells": 0,
    }
    payload.update(overrides)
    return payload


def dispute_payload(**overrides: Any) -> Dict[str, Any]:
    """A dispute reason code (PRD 3.4 "Disputes")."""
    payload: Dict[str, Any] = {"dispute_reason_code": "PICKER_CONTESTS_COUNT"}
    payload.update(overrides)
    return payload


# ─── Payroll runs (PRD 3.5) ───────────────────────────────────────────────


def payroll_run_payload(crew_id: str, **overrides: Any) -> Dict[str, Any]:
    """
    A draft pay period.

    PRD 3.5: the clerk supplies "the `crew_id` being settled and the inclusive
    date range `period_start_date` to `period_end_date`, where
    `period_end_date` is on or after `period_start_date`".
    """
    payload: Dict[str, Any] = {
        "crew_id": crew_id,
        "period_start_date": "2026-08-03",
        "period_end_date": "2026-08-03",
    }
    payload.update(overrides)
    return payload


# ─── Cooling tunnels and fruit lots (PRD 3.6) ─────────────────────────────


def cooling_tunnel_payload(**overrides: Any) -> Dict[str, Any]:
    """
    A registrable forced-air tunnel.

    PRD 3.6: "a `name` of 1 to 40 characters, unique across all tunnels ..., a
    `slot_capacity` of 1 to 96 pallet positions, and a `target_pulp_temp_f`
    between 30.0 and 40.0 inclusive at one decimal".
    """
    payload: Dict[str, Any] = {
        "name": _next("TUN"),
        "slot_capacity": 4,
        "target_pulp_temp_f": 34.0,
    }
    payload.update(overrides)
    return payload


def fruit_lot_payload(
    harvest_window_id: str, block_id: str, **overrides: Any
) -> Dict[str, Any]:
    """
    A field-packed lot of clamshells.

    PRD 3.6: the operator records "the `harvest_window_id` it was picked
    under, the `block_id` it came from, the `variety` and `grade` packed, the
    `clamshell_count` and `clamshell_net_weight_lbs` of the pack, the
    `pick_date`, the `pack_completed_at` instant at which the pack closed, and
    the `field_pulp_temp_f` measured at that moment".
    """
    payload: Dict[str, Any] = {
        "harvest_window_id": harvest_window_id,
        "block_id": block_id,
        "variety": "STRAWBERRY",
        "grade": "A",
        "clamshell_count": 50,
        "clamshell_net_weight_lbs": 1.00,
        "pick_date": "2026-08-03",
        "pack_completed_at": "2026-08-03T12:00:00Z",
        "field_pulp_temp_f": 70.0,
    }
    payload.update(overrides)
    return payload


def start_cooling_payload(
    cooling_tunnel_id: str, expected_cooling_tunnel_version: int, **overrides: Any
) -> Dict[str, Any]:
    """
    A cooling run admission request.

    PRD 3.6: the operator supplies "the `cooling_tunnel_id`, the
    `cool_start_at` instant, the `planned_cool_end_at` instant, the measured
    `entry_pulp_temp_f`, the `pallet_slots` the lot will occupy — 1 to 96 —
    and the `expected_cooling_tunnel_version` guard".
    """
    payload: Dict[str, Any] = {
        "cooling_tunnel_id": cooling_tunnel_id,
        "cool_start_at": "2026-08-03T13:00:00Z",
        "planned_cool_end_at": "2026-08-03T17:00:00Z",
        "entry_pulp_temp_f": 62.0,
        "pallet_slots": 1,
        "expected_cooling_tunnel_version": expected_cooling_tunnel_version,
    }
    payload.update(overrides)
    return payload


def complete_cooling_payload(**overrides: Any) -> Dict[str, Any]:
    """
    A cooling completion.

    PRD 3.6: "Completion supplies the `cool_complete_at` instant, which must
    be strictly after `cool_start_at`, and the measured `exit_pulp_temp_f`."
    """
    payload: Dict[str, Any] = {
        "cool_complete_at": "2026-08-03T17:00:00Z",
        "exit_pulp_temp_f": 34.0,
    }
    payload.update(overrides)
    return payload


def repack_payload(
    output_clamshell_count: int,
    cull_clamshell_count: int,
    optical_reject_clamshell_count: int,
    output_grade: str = "B",
    **overrides: Any,
) -> Dict[str, Any]:
    """
    A repack across the optical sorter.

    PRD 3.6: the operator supplies "the `output_grade` the child will carry,
    the `output_clamshell_count` that came out good, the
    `cull_clamshell_count` diverted to culls and the
    `optical_reject_clamshell_count` thrown out by the sorter".
    """
    payload: Dict[str, Any] = {
        "output_grade": output_grade,
        "output_clamshell_count": output_clamshell_count,
        "cull_clamshell_count": cull_clamshell_count,
        "optical_reject_clamshell_count": optical_reject_clamshell_count,
    }
    payload.update(overrides)
    return payload


def reject_lot_payload(**overrides: Any) -> Dict[str, Any]:
    """A lot rejection reason code (PRD 3.6 "Rejecting a lot")."""
    payload: Dict[str, Any] = {"reject_reason_code": "MOLD"}
    payload.update(overrides)
    return payload


# ─── Buyer programs (PRD 3.7) ─────────────────────────────────────────────


def buyer_commitment_payload(**overrides: Any) -> Dict[str, Any]:
    """
    A buyer program commitment.

    PRD 3.7: the manager supplies "the `buyer_name` of the program (1 to 80
    characters), the `buyer_user_id` of the buyer contact (1 to 64
    characters), the `variety` the program accepts, the
    `volume_commitment_lbs` contracted at two decimals and greater than zero,
    the `price_cents_per_lb` between 1 and 10000, the
    `shelf_life_guarantee_days` promised at delivery between 1 and 30, and the
    delivery window `window_start_date` to `window_end_date`".
    """
    payload: Dict[str, Any] = {
        "buyer_name": _next("Buyer Program"),
        "buyer_user_id": "buyer-1",
        "variety": "STRAWBERRY",
        "volume_commitment_lbs": 200.00,
        "price_cents_per_lb": 400,
        "shelf_life_guarantee_days": 5,
        "window_start_date": "2026-08-01",
        "window_end_date": "2026-08-10",
    }
    payload.update(overrides)
    return payload


def lot_allocation_payload(
    fruit_lot_id: str,
    buyer_commitment_id: str,
    allocated_lbs: float,
    expected_buyer_commitment_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """
    A pledge of pounds from a lot to a buyer program.

    PRD 3.7: the manager names "the `fruit_lot_id` pledged, the
    `buyer_commitment_id` being filled, the `allocated_lbs` pledged at two
    decimals and greater than zero, and the
    `expected_buyer_commitment_version` guard".
    """
    payload: Dict[str, Any] = {
        "fruit_lot_id": fruit_lot_id,
        "buyer_commitment_id": buyer_commitment_id,
        "allocated_lbs": allocated_lbs,
        "expected_buyer_commitment_version": expected_buyer_commitment_version,
    }
    payload.update(overrides)
    return payload


def ship_payload(shipped_at: str = "2026-08-05T09:00:00Z", **overrides: Any) -> Dict[str, Any]:
    """A shipment pickup instant (PRD 3.7 "Shipping a line")."""
    payload: Dict[str, Any] = {"shipped_at": shipped_at}
    payload.update(overrides)
    return payload


def release_payload(**overrides: Any) -> Dict[str, Any]:
    """A release reason code (PRD 3.7 "Releasing a line")."""
    payload: Dict[str, Any] = {"release_reason_code": "BUYER_CANCELLED"}
    payload.update(overrides)
    return payload


# ─── The logical clock (PRD 2.5) ──────────────────────────────────────────


def clock_payload(current_utc: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    """A logical-clock instant; the start-up default is 2026-08-01T00:00:00Z."""
    payload: Dict[str, Any] = {"current_utc": current_utc or CLOCK_DEFAULT}
    payload.update(overrides)
    return payload
