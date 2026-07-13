"""Composite setup helpers.

Each helper drives the PRD-declared endpoints to place the system in a specific
precondition state, so tests can focus on their trigger + assertion. The test
harness restarts the server (empty DB) before every test, so every helper builds
its preconditions from scratch. Setup calls use get_success_data() (lenient) so a
broken precondition surfaces as a clear "Setup step failed" error.

Identity threading: Steward and DonorAgent are entity-backed; ownership-gated calls
use make_steward_headers(steward_id) / make_donor_headers(donor_id) with the real id.
"""
from prd_bench_local_runner.testing import get_success_data

from .test_users import (
    make_admin_headers,
    make_sponsor_headers,
    make_member_headers,
    make_steward_headers,
    make_donor_headers,
)
from . import factories as F
from .constants import CLOCK_BASE


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def set_clock(api, iso: str):
    """Advance the logical clock to `iso` (PRD §2.6)."""
    return get_success_data(api.set_clock(iso, make_admin_headers()))


def reset_clock(api, iso: str = CLOCK_BASE):
    """Set the logical clock to the boot base (or a supplied base)."""
    return set_clock(api, iso)


# --------------------------------------------------------------------------
# Primitive resource creators
# --------------------------------------------------------------------------
def new_fridge(api, **overrides) -> dict:
    return get_success_data(
        api.create_fridge(F.create_fridge_payload(**overrides), make_admin_headers())
    )


def new_steward(api, **overrides) -> dict:
    return get_success_data(
        api.create_steward(F.create_steward_payload(**overrides), make_admin_headers())
    )


def new_donor(api, **overrides) -> dict:
    return get_success_data(
        api.create_donor(F.create_donor_payload(**overrides), make_admin_headers())
    )


def new_grant(api, fridge_id, **overrides) -> dict:
    return get_success_data(
        api.create_grant(
            fridge_id, F.create_grant_payload(**overrides), make_sponsor_headers()
        )
    )


def new_need(api, fridge_id, **overrides) -> dict:
    return get_success_data(
        api.create_need(
            fridge_id, F.create_need_payload(**overrides), make_member_headers()
        )
    )


def new_offer(api, donor_id, fridge_id, **overrides) -> dict:
    return get_success_data(
        api.create_offer(
            donor_id,
            F.create_offer_payload(fridge_id, **overrides),
            make_donor_headers(donor_id),
        )
    )


def new_shift(api, fridge_id, steward_id, actor="admin", **overrides) -> dict:
    headers = (
        make_steward_headers(steward_id) if actor == "steward" else make_admin_headers()
    )
    return get_success_data(
        api.create_shift(
            fridge_id, F.create_shift_payload(steward_id, **overrides), headers
        )
    )


def get_fridge_version(api, fridge_id) -> int:
    fridge = get_success_data(api.get_fridge(fridge_id, make_admin_headers()))
    return fridge["version"]


def record_temperature(api, fridge_id, reading_c, steward_id=None):
    """Record a temperature reading (NetworkAdmin or Steward)."""
    headers = (
        make_steward_headers(steward_id) if steward_id else make_admin_headers()
    )
    return get_success_data(
        api.record_temperature(fridge_id, {"reading_c": reading_c}, headers)
    )


# --------------------------------------------------------------------------
# Intake / batch helpers
# --------------------------------------------------------------------------
def intake_batch(api, fridge_id, steward_id, expected_version=None, **overrides) -> dict:
    """Log a STOCKED donation batch. If expected_version is not supplied, reads the
    fridge's current version first so the OCC check passes (PRD §2.10)."""
    if expected_version is None:
        expected_version = get_fridge_version(api, fridge_id)
    payload = F.create_batch_payload(steward_id, expected_version, **overrides)
    return get_success_data(
        api.create_batch(fridge_id, payload, make_steward_headers(steward_id))
    )


def claim_portion(api, batch_id, quantity_kg, **overrides) -> dict:
    return get_success_data(
        api.create_claim(
            batch_id,
            F.create_claim_payload(quantity_kg, **overrides),
            make_member_headers(),
        )
    )


def recall_batch(api, batch_id, steward_id) -> dict:
    return get_success_data(
        api.recall_batch(batch_id, make_steward_headers(steward_id))
    )


def discard_batch(api, batch_id, steward_id) -> dict:
    return get_success_data(
        api.discard_batch(batch_id, make_steward_headers(steward_id))
    )


# --------------------------------------------------------------------------
# Composite scenarios
# --------------------------------------------------------------------------
def setup_fridge_and_steward(api, capacity_slots=10, **fridge_overrides):
    """Empty DB -> one OPERATIONAL fridge + one ACTIVE steward.
    Returns (fridge, steward)."""
    reset_clock(api)
    fridge = new_fridge(api, capacity_slots=capacity_slots, **fridge_overrides)
    steward = new_steward(api)
    return fridge, steward


def setup_stocked_batch(api, capacity_slots=10, declared_quantity_kg=5.0,
                        slot_footprint=1, **batch_overrides):
    """OPERATIONAL fridge + steward + one STOCKED batch.
    Returns (fridge, steward, batch)."""
    fridge, steward = setup_fridge_and_steward(api, capacity_slots=capacity_slots)
    batch = intake_batch(
        api,
        fridge["id"],
        steward["id"],
        expected_version=fridge["version"],
        declared_quantity_kg=declared_quantity_kg,
        slot_footprint=slot_footprint,
        **batch_overrides,
    )
    return fridge, steward, batch


def setup_restricted_fridge(api, capacity_slots=10):
    """Fridge forced to RESTRICTED via a 10.0C temperature reading + steward.
    Returns (fridge, steward)."""
    fridge, steward = setup_fridge_and_steward(api, capacity_slots=capacity_slots)
    record_temperature(api, fridge["id"], 10.0, steward_id=steward["id"])
    return fridge, steward


def setup_completed_cleaning_shift(api, capacity_slots=5, miles_traveled=0,
                                   handled_cold_chain=False,
                                   start_at="2026-03-01T09:00:00Z",
                                   end_at="2026-03-01T11:00:00Z",
                                   complete_at="2026-03-01T09:30:00Z"):
    """Schedule a CLEANING shift, advance the clock past start, and complete it.
    Returns (fridge, steward, shift). The shift is COMPLETED with a computed
    reimbursement committed to the fridge budget (PRD §3.3)."""
    fridge, steward = setup_fridge_and_steward(api, capacity_slots=capacity_slots)
    shift = new_shift(
        api, fridge["id"], steward["id"], kind="CLEANING",
        start_at=start_at, end_at=end_at,
    )
    set_clock(api, complete_at)
    completed = get_success_data(
        api.complete_shift(
            shift["id"],
            F.complete_shift_payload(
                miles_traveled=miles_traveled, handled_cold_chain=handled_cold_chain
            ),
            make_steward_headers(steward["id"]),
        )
    )
    return fridge, steward, completed


def setup_accepted_offer(api, capacity_slots=10):
    """OPERATIONAL fridge + donor + steward + an OFFERED offer accepted to ACCEPTED.
    Returns (fridge, donor, steward, offer)."""
    reset_clock(api)
    fridge = new_fridge(api, capacity_slots=capacity_slots)
    donor = new_donor(api)
    steward = new_steward(api)
    offer = new_offer(api, donor["id"], fridge["id"])
    accepted = get_success_data(
        api.accept_offer(offer["id"], make_steward_headers(steward["id"]))
    )
    return fridge, donor, steward, accepted


def setup_two_stocked_batches(api, capacity_slots=10, declared_quantity_kg=4.0,
                              slot_footprint=1):
    """OPERATIONAL fridge + steward + two STOCKED batches A and B.
    Returns (fridge, steward, batch_a, batch_b)."""
    fridge, steward = setup_fridge_and_steward(api, capacity_slots=capacity_slots)
    batch_a = intake_batch(
        api, fridge["id"], steward["id"],
        declared_quantity_kg=declared_quantity_kg, slot_footprint=slot_footprint,
    )
    batch_b = intake_batch(
        api, fridge["id"], steward["id"],
        declared_quantity_kg=declared_quantity_kg, slot_footprint=slot_footprint,
    )
    return fridge, steward, batch_a, batch_b


def setup_quarantined_fridge(api, capacity_slots=10):
    """Fridge with two STOCKED batches + one OPEN need; recall batch A so the fridge
    becomes QUARANTINED (batch B -> HELD, need -> SUSPENDED).
    Returns (fridge, steward, recalled_batch_a, sibling_batch_b, need)."""
    fridge, steward = setup_fridge_and_steward(api, capacity_slots=capacity_slots)
    need = new_need(api, fridge["id"])
    batch_a = intake_batch(api, fridge["id"], steward["id"], slot_footprint=1)
    batch_b = intake_batch(api, fridge["id"], steward["id"], slot_footprint=1)
    recalled = recall_batch(api, batch_a["id"], steward["id"])
    return fridge, steward, recalled, batch_b, need
