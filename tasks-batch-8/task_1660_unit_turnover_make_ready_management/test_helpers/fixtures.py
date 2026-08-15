"""Composite setup helpers for the make-ready domain.

Every helper builds its preconditions from scratch through the public API —
each test runs against a freshly restarted server with an empty database.
Lenient get_success_data is used internally so setup failures surface as
clear "Setup failed" errors.

Vendor actions (accept / decline / complete) are ownership-gated
(PRD §2.1): they always thread the acting vendor's entity id through
make_vendor_headers — never the shared vendor constant.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import DEFAULT_PROPERTY
from .factories import (
    create_lease_commitment_payload,
    create_property_payload,
    create_replacement_decision_payload,
    create_scope_item_payload,
    create_turn_payload,
    create_unit_payload,
    create_vendor_assignment_payload,
    create_vendor_payload,
)
from .test_users import TEST_USERS, make_vendor_headers

RM = TEST_USERS["regional_manager_headers"]
PM = TEST_USERS["property_manager_headers"]
TC = TEST_USERS["turn_coordinator_headers"]
INSP = TEST_USERS["inspector_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Single-entity creators
# ---------------------------------------------------------------------------

def create_property(**overrides) -> dict:
    """RegionalManager onboards a property (PRD §3.1)."""
    return get_success_data(api_client.create_property(
        create_property_payload(**overrides), RM))


def create_unit(property_id, **overrides) -> dict:
    """PropertyManager creates a unit, born OCCUPIED (PRD §3.1)."""
    return get_success_data(api_client.create_unit(
        create_unit_payload(property_id, **overrides), PM))


def create_vendor(name="FixCo", trade="REPAIR") -> dict:
    """PropertyManager registers a vendor (PRD §3.1)."""
    return get_success_data(api_client.create_vendor(
        create_vendor_payload(name, trade), PM))


def open_turn(unit_id, **overrides) -> dict:
    """TurnCoordinator records a vacancy notice; turn opens OPEN (PRD §3.2)."""
    return get_success_data(api_client.create_turn(
        create_turn_payload(unit_id, **overrides), TC))


def add_scope_item(turn_id, category="REPAIR", estimated_cost_cents=5000,
                   description=None) -> dict:
    """TurnCoordinator adds a scope item (PRD §3.2/§3.5)."""
    overrides = {}
    if description is not None:
        overrides["description"] = description
    return get_success_data(api_client.create_scope_item(
        create_scope_item_payload(
            turn_id, category, estimated_cost_cents=estimated_cost_cents,
            **overrides),
        TC))


def create_commitment(unit_id, committed_delivery_date="2026-08-10",
                      applicant_name="A Lee") -> dict:
    """TurnCoordinator pre-leases a unit during its turn (PRD §3.8)."""
    return get_success_data(api_client.create_lease_commitment(
        create_lease_commitment_payload(
            unit_id, applicant_name=applicant_name,
            committed_delivery_date=committed_delivery_date),
        TC))


# ---------------------------------------------------------------------------
# Workflow actions
# ---------------------------------------------------------------------------

def finalize_turn(turn_id) -> dict:
    """Finalize scope: OPEN -> SCOPED, budget locked (PRD §3.3)."""
    return get_success_data(api_client.finalize_scope(turn_id, TC))


def close_turn(turn_id) -> dict:
    """PropertyManager closes a READY turn (PRD §3.9)."""
    return get_success_data(api_client.close_turn(turn_id, PM))


def schedule(item_id, vendor_id, start_date="2026-08-01",
             end_date="2026-08-03") -> dict:
    """TurnCoordinator schedules a vendor over [start_date, end_date)."""
    return get_success_data(api_client.create_vendor_assignment(
        create_vendor_assignment_payload(item_id, vendor_id, start_date,
                                         end_date),
        TC))


def accept(assignment_id, vendor_id) -> dict:
    """Assigned vendor accepts; ownership-gated on vendor_id (PRD §3.4)."""
    return get_success_data(api_client.accept_assignment(
        assignment_id, make_vendor_headers(vendor_id)))


def decline(assignment_id, vendor_id) -> dict:
    """Assigned vendor declines (PRD §3.4)."""
    return get_success_data(api_client.decline_assignment(
        assignment_id, make_vendor_headers(vendor_id)))


def complete(assignment_id, vendor_id, actual_cost_cents) -> dict:
    """Assigned vendor completes with the invoiced actual cost (PRD §3.4)."""
    return get_success_data(api_client.complete_assignment(
        assignment_id, {"actual_cost_cents": actual_cost_cents},
        make_vendor_headers(vendor_id)))


def pass_inspection(turn_id, notes=None) -> dict:
    """Inspector submits PASS (PRD §3.7)."""
    payload = {"result": "PASS"}
    if notes is not None:
        payload["notes"] = notes
    return get_success_data(api_client.submit_inspection(turn_id, payload, INSP))


def fail_inspection(turn_id, failed_scope_item_ids, notes=None) -> dict:
    """Inspector submits FAIL, opening the rework loop (PRD §3.7)."""
    payload = {"result": "FAIL", "failed_scope_item_ids": failed_scope_item_ids}
    if notes is not None:
        payload["notes"] = notes
    return get_success_data(api_client.submit_inspection(turn_id, payload, INSP))


def record_decision(turn_id, scope_item_id, **overrides) -> dict:
    """TurnCoordinator records a repair-vs-replace decision (PRD §3.6)."""
    return get_success_data(api_client.create_replacement_decision(
        turn_id, create_replacement_decision_payload(scope_item_id, **overrides),
        TC))


def set_clock(to_iso8601) -> dict:
    """PlatformAdmin sets the logical clock (PRD §2.5)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def get_turn(turn_id) -> dict:
    return get_success_data(api_client.get_turn(turn_id, TC))


def get_unit(unit_id) -> dict:
    return get_success_data(api_client.get_unit(unit_id, PM))


def get_item(item_id) -> dict:
    return get_success_data(api_client.get_scope_item(item_id, TC))


def get_assignment(assignment_id) -> dict:
    return get_success_data(api_client.get_vendor_assignment(assignment_id, TC))


def get_benchmark(property_id) -> dict:
    return get_success_data(api_client.get_turn_benchmark(property_id, PM))


def list_commitments(unit_id) -> list:
    data, _meta = validate_paginated(
        api_client.list_unit_lease_commitments(unit_id, TC))
    return data


def list_assignments(params) -> tuple:
    """Returns (data, meta) for the vendor-assignment collection."""
    return validate_paginated(api_client.list_vendor_assignments(PM, params=params))


def find_rework_item(original_item_id) -> dict:
    """The single rework item auto-created from a failed original (PRD §3.7)."""
    data, meta = validate_paginated(api_client.list_scope_items(
        TC, params={"rework_of_item_id": original_item_id}))
    assert meta["total_count"] == 1, (
        f"Setup failed: expected exactly one rework item of {original_item_id}, "
        f"got {meta['total_count']}"
    )
    return data[0]


# ---------------------------------------------------------------------------
# Composite scenarios
# ---------------------------------------------------------------------------

def setup_property_with_unit(**property_overrides) -> dict:
    """Property + one unit. Returns {"property", "unit"}."""
    prop = create_property(**property_overrides)
    unit = create_unit(prop["id"])
    return {"property": prop, "unit": unit}


def setup_open_turn(item_category="REPAIR", item_estimate=5000,
                    **property_overrides) -> dict:
    """Property + unit + OPEN turn + one PLANNED scope item."""
    ctx = setup_property_with_unit(**property_overrides)
    ctx["turn"] = open_turn(ctx["unit"]["id"])
    ctx["item"] = add_scope_item(ctx["turn"]["id"], item_category, item_estimate)
    return ctx


def setup_scoped_turn(item_category="REPAIR", item_estimate=5000,
                      **property_overrides) -> dict:
    """OPEN turn + one PLANNED item, finalized: turn SCOPED, unit IN_TURN,
    approved_budget_cents locked to the item estimate (PRD §3.3)."""
    ctx = setup_open_turn(item_category, item_estimate, **property_overrides)
    ctx["turn"] = finalize_turn(ctx["turn"]["id"])
    return ctx


def setup_in_progress_turn(item_estimate=5000, start_date="2026-08-01",
                           end_date="2026-08-03", **property_overrides) -> dict:
    """SCOPED turn + REPAIR-trade vendor + assignment accepted: the first
    acceptance advances the turn to IN_PROGRESS (PRD §3.4)."""
    ctx = setup_scoped_turn("REPAIR", item_estimate, **property_overrides)
    ctx["vendor"] = create_vendor("FixCo", "REPAIR")
    ctx["assignment"] = schedule(ctx["item"]["id"], ctx["vendor"]["id"],
                                 start_date, end_date)
    ctx["assignment"] = accept(ctx["assignment"]["id"], ctx["vendor"]["id"])
    ctx["turn"] = get_turn(ctx["turn"]["id"])
    return ctx


def setup_completed_turn_item(item_estimate=5000, actual_cost_cents=4000,
                              start_date="2026-08-01", end_date="2026-08-03",
                              **property_overrides) -> dict:
    """IN_PROGRESS turn whose single item has been completed by the vendor:
    item COMPLETED with actual_cost_cents set (PRD §3.4)."""
    ctx = setup_in_progress_turn(item_estimate, start_date, end_date,
                                 **property_overrides)
    ctx["assignment"] = complete(ctx["assignment"]["id"], ctx["vendor"]["id"],
                                 actual_cost_cents)
    ctx["item"] = get_item(ctx["item"]["id"])
    ctx["turn"] = get_turn(ctx["turn"]["id"])
    return ctx


def setup_ready_turn(item_estimate=5000, actual_cost_cents=4000,
                     **kwargs) -> dict:
    """Completed work + PASS inspection: turn READY, unit READY (PRD §3.7)."""
    ctx = setup_completed_turn_item(item_estimate, actual_cost_cents, **kwargs)
    ctx["inspection"] = pass_inspection(ctx["turn"]["id"])
    ctx["turn"] = get_turn(ctx["turn"]["id"])
    return ctx


def setup_closed_turn(item_estimate=5000, actual_cost_cents=4000,
                      **kwargs) -> dict:
    """Full lifecycle through CLOSED; the turn enters the benchmark (§3.9)."""
    ctx = setup_ready_turn(item_estimate, actual_cost_cents, **kwargs)
    ctx["turn"] = close_turn(ctx["turn"]["id"])
    return ctx
