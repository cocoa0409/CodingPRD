"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database). Setup calls use get_success_data so failures surface as clear
"Setup failed" errors. All version-guarded writes re-read the parent first,
because any mutation touching a resource increments its version (PRD §2.9).
"""
from types import SimpleNamespace

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_damage_claim_payload,
    create_equipment_assignment_payload,
    create_equipment_unit_payload,
    create_gang_order_payload,
    create_invoice_payload,
    create_move_record_payload,
    create_safety_incident_payload,
    create_shift_window_payload,
    create_timesheet_entry_payload,
    create_vessel_call_payload,
    create_worker_payload,
)
from .test_users import TEST_USERS, make_adjuster_headers, make_foreman_headers, make_payroll_headers

ADMIN = TEST_USERS["admin_headers"]
SUPT = TEST_USERS["superintendent_headers"]
DISP = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_headers"]

DEFAULT_SHIFT_DATE = "2026-08-10"
DEFAULT_SHIFT_START = "2026-08-10T08:00:00Z"
DEFAULT_SHIFT_END = "2026-08-10T16:00:00Z"


# ---------------------------------------------------------------------------
# Atomic helpers (single API calls, lenient validation)
# ---------------------------------------------------------------------------

def create_vessel(**overrides) -> dict:
    resp = api_client.create_vessel_call(create_vessel_call_payload(**overrides), ADMIN)
    return get_success_data(resp)


def berth_vessel(vessel_id) -> dict:
    return get_success_data(api_client.berth_vessel_call(vessel_id, SUPT))


def get_vessel(vessel_id) -> dict:
    return get_success_data(api_client.get_vessel_call(vessel_id, SUPT))


def create_shift(vessel_id, **overrides) -> dict:
    resp = api_client.create_shift_window(
        create_shift_window_payload(vessel_id, **overrides), SUPT)
    return get_success_data(resp)


def open_shift(shift_id) -> dict:
    return get_success_data(api_client.open_shift_window_for_orders(shift_id, SUPT))


def start_shift(shift_id) -> dict:
    return get_success_data(api_client.start_shift_window(shift_id, SUPT))


def get_shift(shift_id) -> dict:
    return get_success_data(api_client.get_shift_window(shift_id, SUPT))


def place_gang(shift_id, **overrides) -> dict:
    resp = api_client.create_gang_order(
        create_gang_order_payload(shift_id, **overrides), SUPT)
    return get_success_data(resp)


def get_gang(gang_id) -> dict:
    return get_success_data(api_client.get_gang_order(gang_id, SUPT))


def amend_gang(gang_id, expected_version, **fields):
    """PATCH a gang order's required_headcount / required_equipment_count.

    Returns the raw response so callers can test both success and rejection.
    """
    payload = dict(fields)
    payload["expected_gang_order_version"] = expected_version
    return api_client.amend_gang_order(gang_id, payload, SUPT)


def register_worker(**overrides) -> dict:
    resp = api_client.create_worker(create_worker_payload(**overrides), ADMIN)
    return get_success_data(resp)


def register_workers(specs) -> list:
    """Register workers from a list of override dicts, preserving order."""
    return [register_worker(**spec) for spec in specs]


def get_worker(worker_id) -> dict:
    return get_success_data(api_client.get_worker(worker_id, ADMIN))


def set_worker_status(worker_id, status, expected_version):
    """PATCH worker status (OCC-guarded). Returns the raw response."""
    return api_client.update_worker_status(
        worker_id, {"status": status, "expected_worker_version": expected_version}, ADMIN)


def register_unit(**overrides) -> dict:
    resp = api_client.create_equipment_unit(
        create_equipment_unit_payload(**overrides), ADMIN)
    return get_success_data(resp)


def get_unit(unit_id) -> dict:
    return get_success_data(api_client.get_equipment_unit(unit_id, SUPT))


def book_equipment(gang_id, unit_id, **overrides) -> dict:
    resp = api_client.create_equipment_assignment(
        create_equipment_assignment_payload(gang_id, unit_id, **overrides), SUPT)
    return get_success_data(resp)


def get_equipment_assignment(assignment_id) -> dict:
    return get_success_data(api_client.get_equipment_assignment(assignment_id, SUPT))


def dispatch_batch(gang_id, worker_ids=None):
    """Run a dispatch batch with the gang order's CURRENT version (OCC-safe).

    Returns the raw response so callers can assert on rejections too.
    """
    current = get_gang(gang_id)
    payload = {"expected_gang_order_version": current["version"]}
    if worker_ids is not None:
        payload["worker_ids"] = worker_ids
    return api_client.dispatch_batch(gang_id, payload, DISP)


def run_dispatch(gang_id, worker_ids=None) -> dict:
    """Dispatch batch expected to succeed; returns the updated gang order."""
    return get_success_data(dispatch_batch(gang_id, worker_ids=worker_ids))


def list_assignments(headers=None, **filters) -> list:
    params = {k: v for k, v in filters.items() if v is not None}
    resp = api_client.list_dispatch_assignments(headers or DISP, params=params or None)
    data, _meta = validate_paginated(resp)
    return data


def get_assignment(assignment_id) -> dict:
    return get_success_data(api_client.get_dispatch_assignment(assignment_id, DISP))


def check_in(assignment_id) -> dict:
    return get_success_data(api_client.check_in_assignment(assignment_id, DISP))


def start_gang_work(gang_id, foreman_worker_id):
    """start-work as GangForeman. Returns the raw response."""
    return api_client.start_gang_work(gang_id, make_foreman_headers(foreman_worker_id))


def complete_gang(gang_id, foreman_worker_id) -> dict:
    return get_success_data(
        api_client.complete_gang_order(gang_id, make_foreman_headers(foreman_worker_id)))


def record_moves(gang_id, foreman_worker_id, **overrides) -> dict:
    resp = api_client.create_move_record(
        create_move_record_payload(gang_id, **overrides),
        make_foreman_headers(foreman_worker_id))
    return get_success_data(resp)


def void_move_record(record_id, foreman_worker_id) -> dict:
    return get_success_data(
        api_client.void_move_record(record_id, make_foreman_headers(foreman_worker_id)))


def enter_timesheet(gang_id, worker_id, foreman_worker_id, **overrides) -> dict:
    resp = api_client.create_timesheet_entry(
        create_timesheet_entry_payload(gang_id, worker_id, **overrides),
        make_foreman_headers(foreman_worker_id))
    return get_success_data(resp)


def submit_timesheet(entry_id, foreman_worker_id) -> dict:
    return get_success_data(api_client.submit_timesheet_entry(
        entry_id, make_foreman_headers(foreman_worker_id)))


def approve_timesheet(entry_id, approver_user_id="pay-1") -> dict:
    return get_success_data(api_client.approve_timesheet_entry(
        entry_id, make_payroll_headers(approver_user_id)))


def enter_submit_approve_timesheet(gang_id, worker_id, foreman_worker_id,
                                   approver_user_id="pay-1", **overrides) -> dict:
    entry = enter_timesheet(gang_id, worker_id, foreman_worker_id, **overrides)
    submit_timesheet(entry["id"], foreman_worker_id)
    return approve_timesheet(entry["id"], approver_user_id)


def get_timesheet_entry(entry_id, headers=None) -> dict:
    return get_success_data(api_client.get_timesheet_entry(
        entry_id, headers or TEST_USERS["payroll_headers"]))


def report_claim(gang_id, foreman_worker_id, **overrides) -> dict:
    resp = api_client.create_damage_claim(
        create_damage_claim_payload(gang_id, **overrides),
        make_foreman_headers(foreman_worker_id))
    return get_success_data(resp)


def decide_claim(claim_id, decision, adjuster_user_id="adj-1", fault_pct=None):
    payload = {"decision": decision}
    if fault_pct is not None:
        payload["fault_pct"] = fault_pct
    return api_client.decide_damage_claim(
        claim_id, payload, make_adjuster_headers(adjuster_user_id))


def settle_claim(claim_id, adjuster_user_id="adj-1") -> dict:
    return get_success_data(
        api_client.settle_damage_claim(claim_id, make_adjuster_headers(adjuster_user_id)))


def report_incident(vessel_id, foreman_worker_id=None, **overrides) -> dict:
    headers = make_foreman_headers(foreman_worker_id) if foreman_worker_id else SUPT
    resp = api_client.create_safety_incident(
        create_safety_incident_payload(vessel_id, **overrides), headers)
    return get_success_data(resp)


def clear_incident(incident_id) -> dict:
    return get_success_data(api_client.clear_safety_incident(incident_id, SUPT))


def create_invoice(vessel_id) -> dict:
    resp = api_client.create_invoice(create_invoice_payload(vessel_id), BILLING)
    return get_success_data(resp)


def get_invoice(invoice_id) -> dict:
    return get_success_data(api_client.get_invoice(invoice_id, BILLING))


def finalize_invoice(invoice_id) -> dict:
    return get_success_data(api_client.finalize_invoice(invoice_id, BILLING))


def issue_invoice(invoice_id) -> dict:
    return get_success_data(api_client.issue_invoice(invoice_id, BILLING))


def record_payment(invoice_id, amount_cents):
    return api_client.record_invoice_payment(invoice_id, {"amount_cents": amount_cents}, BILLING)


def dispute_invoice(invoice_id, reason) -> dict:
    return get_success_data(
        api_client.dispute_invoice(invoice_id, {"dispute_reason": reason}, BILLING))


def adjust_invoice(invoice_id, adjustment_cents, reason, expected_version=None):
    """PATCH an invoice adjustment; reads the current version when not given.

    Returns the raw response so both success and stale-version rejection are
    testable.
    """
    if expected_version is None:
        expected_version = get_invoice(invoice_id)["version"]
    payload = {
        "adjustment_cents": adjustment_cents,
        "reason": reason,
        "expected_invoice_version": expected_version,
    }
    return api_client.adjust_invoice(invoice_id, payload, BILLING)


# ---------------------------------------------------------------------------
# Tier 1/2 — vessel + shift + gang stand-up
# ---------------------------------------------------------------------------

def setup_vessel_with_open_shift(vessel_overrides=None, shift_overrides=None):
    """BERTHED vessel + OPEN_FOR_ORDERS shift. Returns (vessel, shift)."""
    vessel = create_vessel(**(vessel_overrides or {}))
    berth_vessel(vessel["id"])
    shift = create_shift(vessel["id"], **(shift_overrides or {}))
    open_shift(shift["id"])
    return get_vessel(vessel["id"]), get_shift(shift["id"])


def setup_placed_gang(vessel_overrides=None, shift_overrides=None,
                      gang_overrides=None) -> SimpleNamespace:
    """BERTHED vessel, OPEN_FOR_ORDERS shift, PLACED gang order."""
    vessel, shift = setup_vessel_with_open_shift(vessel_overrides, shift_overrides)
    gang = place_gang(shift["id"], **(gang_overrides or {}))
    return SimpleNamespace(vessel=vessel, shift=shift, gang=gang)


# ---------------------------------------------------------------------------
# Tier 3 — dispatch pipeline
# ---------------------------------------------------------------------------

DEFAULT_WORKER_SPECS = [
    {"classification": "HOLDMAN", "registered_on": "2010-01-01",
     "base_hourly_rate_cents": 4000},
    {"classification": "HOLDMAN", "registered_on": "2015-06-01",
     "base_hourly_rate_cents": 4000},
]


def setup_dispatched_gang(vessel_overrides=None, shift_overrides=None,
                          gang_overrides=None, worker_specs=None,
                          equipment_specs=None,
                          force_worker_ids=None) -> SimpleNamespace:
    """PLACED gang + registered workers (+ booked equipment) + one successful
    dispatch batch. Assignments are OFFERED, listed in creation order.

    equipment_specs: list of unit override dicts; each unit is registered and
    booked to the gang over the default shift window.
    """
    ns = setup_placed_gang(vessel_overrides, shift_overrides, gang_overrides)
    ns.workers = register_workers(
        worker_specs if worker_specs is not None else DEFAULT_WORKER_SPECS)
    ns.equipment = []
    ns.equipment_assignments = []
    for spec in (equipment_specs or []):
        unit = register_unit(**spec)
        ea = book_equipment(ns.gang["id"], unit["id"])
        ns.equipment.append(unit)
        ns.equipment_assignments.append(ea)
    ns.gang = run_dispatch(ns.gang["id"], worker_ids=force_worker_ids)
    ns.assignments = list_assignments(gang_order_id=ns.gang["id"])
    return ns


def setup_working_gang(vessel_overrides=None, shift_overrides=None,
                       gang_overrides=None, worker_specs=None,
                       equipment_specs=None, check_in_count=None,
                       move_records=None) -> SimpleNamespace:
    """Dispatch pipeline + shift IN_PROGRESS + check-ins + start-work.

    The gang is WORKING; the vessel advanced BERTHED -> WORKING on shift start.
    check_in_count defaults to every offered assignment.
    move_records: optional list of move-record override dicts logged while WORKING.
    """
    ns = setup_dispatched_gang(vessel_overrides, shift_overrides, gang_overrides,
                               worker_specs, equipment_specs)
    ns.shift = start_shift(ns.shift["id"])
    ns.vessel = get_vessel(ns.vessel["id"])
    foreman_id = ns.workers[0]["id"]
    offered = [a for a in ns.assignments if a["status"] == "OFFERED"]
    to_check_in = offered if check_in_count is None else offered[:check_in_count]
    for a in to_check_in:
        check_in(a["id"])
    resp = start_gang_work(ns.gang["id"], foreman_id)
    ns.gang = get_success_data(resp)
    ns.assignments = list_assignments(gang_order_id=ns.gang["id"])
    ns.foreman_id = foreman_id
    ns.move_records = []
    for mr in (move_records or []):
        ns.move_records.append(record_moves(ns.gang["id"], foreman_id, **mr))
    return ns


def setup_completed_gang(vessel_overrides=None, shift_overrides=None,
                         gang_overrides=None, worker_specs=None,
                         equipment_specs=None, move_records=None) -> SimpleNamespace:
    """WORKING gang completed. The shift auto-closes when this gang is its
    only order. Timesheets may still be entered afterwards (assignments are
    COMPLETED, which satisfies the timesheet linkage rule)."""
    ns = setup_working_gang(vessel_overrides, shift_overrides, gang_overrides,
                            worker_specs, equipment_specs, move_records=move_records)
    ns.gang = complete_gang(ns.gang["id"], ns.foreman_id)
    ns.shift = get_shift(ns.shift["id"])
    ns.assignments = list_assignments(gang_order_id=ns.gang["id"])
    return ns


# ---------------------------------------------------------------------------
# Tier 5 — vessel completion and invoices
# ---------------------------------------------------------------------------

def setup_completed_vessel(vessel_overrides=None, shift_overrides=None,
                           gang_overrides=None, worker_specs=None,
                           equipment_specs=None, move_records=None,
                           timesheets=None) -> SimpleNamespace:
    """Full lifecycle: gang completed, optional approved timesheets, vessel
    COMPLETED. timesheets: list of (worker_index, override-dict) tuples."""
    ns = setup_completed_gang(vessel_overrides, shift_overrides, gang_overrides,
                              worker_specs, equipment_specs, move_records)
    ns.timesheets = []
    for worker_index, overrides in (timesheets or []):
        worker = ns.workers[worker_index]
        entry = enter_submit_approve_timesheet(
            ns.gang["id"], worker["id"], ns.foreman_id, **overrides)
        ns.timesheets.append(entry)
    resp = api_client.complete_vessel_call(ns.vessel["id"], SUPT)
    ns.vessel = get_success_data(resp)
    return ns


def setup_finalized_invoice(**kwargs) -> SimpleNamespace:
    """Vessel COMPLETED + invoice created and recomputed from actuals
    (FINALIZED, rate_variant FINAL)."""
    ns = setup_completed_vessel(**kwargs)
    ns.invoice = create_invoice(ns.vessel["id"])
    ns.invoice = finalize_invoice(ns.invoice["id"])
    return ns


def setup_issued_invoice(**kwargs) -> SimpleNamespace:
    """FINALIZED invoice issued (credit-limit gate passed)."""
    ns = setup_finalized_invoice(**kwargs)
    ns.invoice = issue_invoice(ns.invoice["id"])
    return ns
