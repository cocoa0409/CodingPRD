"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (each test starts against an empty database). Setup calls use the
lenient ``get_success_data`` validator so a broken precondition surfaces as a
clear "Setup failed" rather than a confusing assertion error.

Identity threading: the Carrier role is entity_backed, so every ownership-gated
Carrier call uses ``make_carrier_headers(carrier_id)`` with the real Carrier id.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_carrier_headers
from . import factories

# Monotonic counters so default unique keys never collide inside one test.
_usdot_counter = itertools.count(1)
_cert_counter = itertools.count(1)


def _admin():
    return TEST_USERS["dot_admin_headers"]


def _officer():
    return TEST_USERS["permit_officer_headers"]


def _engineer():
    return TEST_USERS["bridge_engineer_headers"]


def _enforcer():
    return TEST_USERS["enforcement_officer_headers"]


# ---------------------------------------------------------------------------
# Primitive builders
# ---------------------------------------------------------------------------
def new_carrier(api=api_client, **overrides):
    if "usdot_number" not in overrides:
        overrides["usdot_number"] = f"USDOT-{next(_usdot_counter):04d}"
    return get_success_data(api.create_carrier(factories.create_carrier_payload(**overrides), _admin()))


def deposit_escrow(api, carrier_id, amount_cents):
    return get_success_data(
        api.deposit_escrow(carrier_id, factories.escrow_deposit_payload(amount_cents), _admin())
    )


def new_structure(api=api_client, **overrides):
    return get_success_data(api.create_structure(factories.create_structure_payload(**overrides), _admin()))


def new_pilot_car(api=api_client, **overrides):
    if "cert_number" not in overrides:
        overrides["cert_number"] = f"PC-{next(_cert_counter):04d}"
    return get_success_data(api.create_pilot_car(factories.create_pilot_car_payload(**overrides), _admin()))


def new_travel_restriction(api=api_client, **overrides):
    return get_success_data(
        api.create_travel_restriction(factories.create_travel_restriction_payload(**overrides), _admin())
    )


def new_permit(api, carrier_id, **overrides):
    return get_success_data(
        api.create_permit(factories.create_permit_payload(carrier_id, **overrides), make_carrier_headers(carrier_id))
    )


def add_segment(api, permit_id, carrier_id, **overrides):
    return get_success_data(
        api.add_route_segment(permit_id, factories.create_route_segment_payload(**overrides),
                              make_carrier_headers(carrier_id))
    )


def add_escort(api, permit_id, carrier_id, pilot_car_id, **overrides):
    return get_success_data(
        api.add_escort_assignment(permit_id, factories.create_escort_assignment_payload(pilot_car_id, **overrides),
                                  make_carrier_headers(carrier_id))
    )


def confirm_escort(api, escort_id, carrier_id):
    return get_success_data(api.confirm_escort(escort_id, make_carrier_headers(carrier_id)))


def submit(api, permit_id, carrier_id):
    return get_success_data(api.submit_permit(permit_id, make_carrier_headers(carrier_id)))


def begin_review(api, permit_id, actor="officer"):
    headers = _engineer() if actor == "engineer" else _officer()
    return get_success_data(api.begin_review(permit_id, headers))


def approve(api, permit_id, actor="officer"):
    headers = _engineer() if actor == "engineer" else _officer()
    return get_success_data(api.approve_permit(permit_id, headers))


def issue(api, permit_id):
    return get_success_data(api.issue_permit(permit_id, _officer()))


def complete(api, permit_id, carrier_id):
    return get_success_data(api.complete_permit(permit_id, make_carrier_headers(carrier_id)))


def bridge_analyses_for(api, permit_id):
    """Return the list of BridgeAnalysis rows for a permit."""
    return get_success_data(api.list_bridge_analyses(_engineer(), params={"permit_id": permit_id}))


def first_bridge_analysis_id(api, permit_id):
    rows = bridge_analyses_for(api, permit_id)
    assert rows, f"expected at least one bridge analysis for permit {permit_id}"
    return rows[0]["id"]


def review_bridge(api, ba_id, method="LFR"):
    return get_success_data(api.review_bridge_analysis(ba_id, {"method": method}, _engineer()))


def bonds_for(api, permit_id):
    return get_success_data(api.list_bonds(_engineer(), params={"permit_id": permit_id}))


def cite_violation(api, permit_id, violation_type="OVER_DIMENSION", severity="MINOR"):
    return get_success_data(
        api.create_violation(
            factories.create_violation_payload(permit_id, violation_type=violation_type, severity=severity),
            _enforcer(),
        )
    )


def uphold(api, violation_id):
    return get_success_data(api.uphold_violation(violation_id, _enforcer()))


def cite_and_uphold(api, permit_id, violation_type="OVER_DIMENSION", severity="MINOR"):
    v = cite_violation(api, permit_id, violation_type, severity)
    uphold(api, v["id"])
    return v


# ---------------------------------------------------------------------------
# Composite fixtures
# ---------------------------------------------------------------------------
def setup_carrier_and_draft_permit(api, permit_overrides=None):
    """Carrier + one DRAFT permit. Returns (carrier, permit)."""
    carrier = new_carrier(api)
    permit = new_permit(api, carrier["id"], **(permit_overrides or {}))
    return carrier, permit


def setup_submitted_permit(api, permit_overrides=None, segment_overrides=None,
                           review_actor="officer", begin=False):
    """Carrier + permit + one route segment + submit.

    If ``begin`` is true, also transitions the permit into review via
    begin-review with the given ``review_actor`` ("officer" or "engineer").
    Returns dict: carrier, permit (post-submit or post-begin), segment.
    """
    carrier = new_carrier(api)
    permit = new_permit(api, carrier["id"], **(permit_overrides or {}))
    segment = add_segment(api, permit["id"], carrier["id"], **(segment_overrides or {}))
    submitted = submit(api, permit["id"], carrier["id"])
    ctx = {"carrier": carrier, "permit": submitted, "segment": segment}
    if begin:
        ctx["permit"] = begin_review(api, permit["id"], actor=review_actor)
    return ctx


def drive_overweight_permit_to_issued(api, structure=None, gross_weight_lbs=120000,
                                      cross_start="2026-06-05T10:00:00Z",
                                      cross_end="2026-06-05T10:30:00Z",
                                      method="LFR"):
    """Full standard-path lifecycle to ISSUED for a non-superload permit.

    If ``structure`` (a structure dict) is given, the single segment crosses it
    at [cross_start, cross_end] and the spawned analysis is reviewed with
    ``method`` (defaults to LFR, which clears a rated-200/dead-40 span at 120000
    lbs). Otherwise the permit has one no-structure segment.
    Returns dict: carrier, permit (ISSUED), segment.
    """
    carrier = new_carrier(api)
    permit = new_permit(api, carrier["id"], gross_weight_lbs=gross_weight_lbs)
    seg_over = {}
    if structure is not None:
        seg_over = {
            "structure_id": structure["id"],
            "planned_cross_start_utc": cross_start,
            "planned_cross_end_utc": cross_end,
        }
    segment = add_segment(api, permit["id"], carrier["id"], **seg_over)
    submit(api, permit["id"], carrier["id"])
    begin_review(api, permit["id"], actor="officer")
    if structure is not None:
        ba_id = first_bridge_analysis_id(api, permit["id"])
        review_bridge(api, ba_id, method=method)
    approve(api, permit["id"], actor="officer")
    issued = issue(api, permit["id"])
    return {"carrier": carrier, "permit": issued, "segment": segment}


def drive_superload_permit_to_approved(api, escrow_cents=10_000_000,
                                       gross_weight_lbs=210000):
    """Carrier (funded) + SUPERLOAD permit + one no-structure segment + one
    CONFIRMED POLICE escort, driven through superload review to APPROVED.

    A superload with gross>=200000 has required_escort_count 1 (police), so one
    CONFIRMED escort satisfies approval. Returns dict: carrier, permit
    (APPROVED), pilot_car, escort.
    """
    carrier = new_carrier(api)
    if escrow_cents:
        deposit_escrow(api, carrier["id"], escrow_cents)
    pilot = new_pilot_car(api)
    permit = new_permit(api, carrier["id"], gross_weight_lbs=gross_weight_lbs)
    add_segment(api, permit["id"], carrier["id"])
    escort = add_escort(api, permit["id"], carrier["id"], pilot["id"], role="POLICE",
                        window_start_utc="2026-06-05T09:00:00Z", window_end_utc="2026-06-05T12:00:00Z")
    submit(api, permit["id"], carrier["id"])
    confirm_escort(api, escort["id"], carrier["id"])
    begin_review(api, permit["id"], actor="engineer")
    approved = approve(api, permit["id"], actor="engineer")
    return {"carrier": carrier, "permit": approved, "pilot_car": pilot, "escort": escort}


def drive_permit_to_issued_then_suspend(api, structure, severity="MAJOR",
                                        violation_type="OFF_SCHEDULE"):
    """Overweight permit crossing ``structure`` driven to ISSUED, then a
    MAJOR/CRITICAL violation cited so the permit becomes SUSPENDED.
    Returns dict: carrier, permit (SUSPENDED), segment, violation, structure.
    """
    ctx = drive_overweight_permit_to_issued(api, structure=structure)
    violation = cite_violation(api, ctx["permit"]["id"], violation_type=violation_type, severity=severity)
    return {
        "carrier": ctx["carrier"],
        "permit_id": ctx["permit"]["id"],
        "segment": ctx["segment"],
        "violation": violation,
        "structure": structure,
    }
