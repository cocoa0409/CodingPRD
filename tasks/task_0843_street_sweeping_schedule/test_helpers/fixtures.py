"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface
as clear "Setup failed" errors, not confusing assertion failures.

The test harness restarts the server (empty DB, logical clock reset to
2026-03-01T00:00:00Z) before every test, so each helper builds its preconditions
from scratch using only PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_route_payload,
    create_block_payload,
    create_equipment_payload,
    create_shift_payload,
    create_sweep_event_payload,
    create_suspension_payload,
    create_citation_payload,
    create_resident_payload,
    create_complaint_payload,
    post_sign_payload,
)
from .test_users import TEST_USERS, make_officer_headers, make_resident_headers

_DISPATCHER = TEST_USERS["route_dispatcher_headers"]
_INSPECTOR = TEST_USERS["signage_inspector_headers"]
_ADMIN = TEST_USERS["public_works_admin_headers"]


# ─── Logical clock ────────────────────────────────────────────────────────────

def set_clock(iso, headers=None):
    """Advance the logical clock. Allowed for every role except Resident (§2.5)."""
    headers = headers or _DISPATCHER
    return api_client.set_clock({"to_iso8601": iso}, headers)


# ─── Tier 1: primitive create helpers ─────────────────────────────────────────

def create_route(**overrides):
    return get_success_data(
        api_client.create_route(create_route_payload(**overrides), _DISPATCHER))


def create_block(route_id, **overrides):
    return get_success_data(
        api_client.create_block(create_block_payload(route_id, **overrides), _DISPATCHER))


def post_sign(block_id, expected_block_version, sign_expires_at=None):
    return get_success_data(api_client.post_sign(
        block_id, post_sign_payload(expected_block_version, sign_expires_at), _INSPECTOR))


def verify_sign(block_id):
    return get_success_data(api_client.verify_sign(block_id, _INSPECTOR))


def create_equipment(hopper_capacity_lbs=20000, **overrides):
    return get_success_data(api_client.create_equipment(
        create_equipment_payload(hopper_capacity_lbs=hopper_capacity_lbs, **overrides),
        _DISPATCHER))


def create_shift(equipment_id, **overrides):
    return get_success_data(
        api_client.create_shift(create_shift_payload(equipment_id, **overrides), _DISPATCHER))


def start_shift(shift_id):
    return get_success_data(api_client.start_shift(shift_id, _DISPATCHER))


def create_sweep_event(block_id, **overrides):
    return get_success_data(
        api_client.create_sweep_event(create_sweep_event_payload(block_id, **overrides), _DISPATCHER))


def complete_sweep(event_id, shift_id, debris_lbs):
    return get_success_data(api_client.complete_sweep_event(
        event_id, {"shift_id": shift_id, "debris_lbs": debris_lbs}, _DISPATCHER))


def create_resident(home_block_id, **overrides):
    return get_success_data(
        api_client.create_resident(create_resident_payload(home_block_id, **overrides), _DISPATCHER))


# ─── Tier 2: signage progression ──────────────────────────────────────────────

def setup_verified_block(route_overrides=None, **block_overrides):
    """Route + block whose sign is POSTED then VERIFIED (enforceable while the
    clock is before sign_expires_at). Returns (route, block_after_verify).

    Sign is posted/verified at the startup clock default; callers set the clock
    forward before issuing citations."""
    route = create_route(**(route_overrides or {}))
    block = create_block(route["id"], **block_overrides)
    post_sign(block["id"], block["version"])
    verified = verify_sign(block["id"])
    return route, verified


def setup_posted_block(route_overrides=None, sign_expires_at=None, **block_overrides):
    """Route + block whose sign is POSTED but NOT verified (not enforceable).
    Returns (route, block_after_post)."""
    route = create_route(**(route_overrides or {}))
    block = create_block(route["id"], **block_overrides)
    posted = post_sign(block["id"], block["version"], sign_expires_at)
    return route, posted


# ─── Tier 3: shift progression ────────────────────────────────────────────────

def setup_started_shift(hopper_capacity_lbs=20000, unit_number="SW-1",
                        equipment_type="MECHANICAL", **shift_overrides):
    """Equipment + a shift started to IN_PROGRESS (equipment -> IN_SERVICE).
    Returns (equipment, started_shift)."""
    equipment = create_equipment(
        hopper_capacity_lbs=hopper_capacity_lbs, unit_number=unit_number, type=equipment_type)
    shift = create_shift(equipment["id"], **shift_overrides)
    started = start_shift(shift["id"])
    return equipment, started


def setup_route_block_started_shift(hopper_capacity_lbs=20000, block_overrides=None,
                                    **shift_overrides):
    """Route + block + started shift, ready for sweep completion.
    Returns (route, block, equipment, started_shift)."""
    equipment, shift = setup_started_shift(hopper_capacity_lbs=hopper_capacity_lbs,
                                           **shift_overrides)
    route = create_route()
    block = create_block(route["id"], **(block_overrides or {}))
    return route, block, equipment, shift


# ─── Tier 4: citation lifecycle ───────────────────────────────────────────────

def issue_citation(block_id, plate="ABC123", scanned_at_utc="2026-03-10T08:30:00Z",
                   officer_id="officer-1", sweep_event_id=None):
    """Issue a citation as a specific EnforcementOfficer. Assumes the block's sign
    is enforceable and the clock already sits inside the restriction window."""
    payload = create_citation_payload(block_id, sweep_event_id=sweep_event_id,
                                       plate=plate, scanned_at_utc=scanned_at_utc)
    return get_success_data(api_client.create_citation(payload, make_officer_headers(officer_id)))


def setup_issued_citation(plate="ABC123", scan_iso="2026-03-10T08:30:00Z",
                          officer_id="officer-1", block_overrides=None,
                          sweep_event_id=None):
    """Verified block + clock inside the window + one ISSUED citation (provisional
    6000 for a plate with no priors). Returns (route, block, citation)."""
    route, block = setup_verified_block(**(block_overrides or {}))
    set_clock(scan_iso, TEST_USERS["enforcement_officer_headers"])
    cit = issue_citation(block["id"], plate=plate, scanned_at_utc=scan_iso,
                         officer_id=officer_id, sweep_event_id=sweep_event_id)
    return route, block, cit


def contest_citation(citation_id, officer_id="officer-1"):
    return get_success_data(api_client.contest_citation(
        citation_id, {}, make_officer_headers(officer_id)))


def adjudicate_citation(citation_id, decision, officer_id="officer-2"):
    return get_success_data(api_client.adjudicate_citation(
        citation_id, {"decision": decision}, make_officer_headers(officer_id)))


def pay_citation(citation_id, officer_id="officer-1"):
    return get_success_data(api_client.pay_citation(citation_id, make_officer_headers(officer_id)))


def setup_upheld_citation(plate="UPH001", scan_iso="2026-03-10T08:30:00Z",
                          issuing_officer="officer-1", adjudicator="officer-2"):
    """A citation issued, contested, and upheld by a different officer.
    Returns (route, block, citation_after_uphold)."""
    route, block, cit = setup_issued_citation(plate=plate, scan_iso=scan_iso,
                                              officer_id=issuing_officer)
    contest_citation(cit["id"], officer_id=issuing_officer)
    upheld = adjudicate_citation(cit["id"], "UPHOLD", officer_id=adjudicator)
    return route, block, upheld


def setup_prior_upheld_then_issue(plate="REP999", first_scan="2026-03-10T08:30:00Z",
                                  second_scan="2026-03-12T08:30:00Z"):
    """Drive one citation for `plate` to UPHELD (giving prior_upheld_count 1), then
    issue a second citation for the same plate. Returns (route, block, second_citation)."""
    route, block = setup_verified_block()
    set_clock(first_scan, TEST_USERS["enforcement_officer_headers"])
    cit1 = issue_citation(block["id"], plate=plate, scanned_at_utc=first_scan,
                          officer_id="officer-1")
    contest_citation(cit1["id"], officer_id="officer-1")
    adjudicate_citation(cit1["id"], "UPHOLD", officer_id="officer-2")
    set_clock(second_scan, TEST_USERS["enforcement_officer_headers"])
    cit2 = issue_citation(block["id"], plate=plate, scanned_at_utc=second_scan,
                          officer_id="officer-1")
    return route, block, cit2


# ─── Tier 5: suspension cascade ───────────────────────────────────────────────

def create_suspension(reason="HOLIDAY", scope="ROUTE", route_id=None,
                      start_date="2026-03-09", end_date="2026-03-11"):
    payload = create_suspension_payload(reason=reason, scope=scope,
                                        start_date=start_date, end_date=end_date)
    if scope == "ROUTE" and route_id is not None:
        payload["route_id"] = route_id
    elif "route_id" in payload:
        del payload["route_id"]
    return get_success_data(api_client.create_suspension(payload, _ADMIN))


def activate_suspension(suspension_id):
    return get_success_data(api_client.activate_suspension(suspension_id, _ADMIN))


# ─── Tier 6: resident / complaint lifecycle ───────────────────────────────────

def file_complaint(resident_id, block_id, category="MISSED_BLOCK", **overrides):
    payload = create_complaint_payload(resident_id, block_id, category=category, **overrides)
    return get_success_data(
        api_client.create_complaint(payload, make_resident_headers(resident_id)))


def resolve_complaint(complaint_id, resolution_note="resolved"):
    return get_success_data(api_client.resolve_complaint(
        complaint_id, {"resolution_note": resolution_note}, _DISPATCHER))


def reopen_complaint(complaint_id, resident_id, reason="still an issue"):
    return get_success_data(api_client.reopen_complaint(
        complaint_id, {"reason": reason}, make_resident_headers(resident_id)))


def setup_resolved_complaint(category="MISSED_BLOCK"):
    """Route + block + resident + a complaint filed then resolved.
    Returns (block, resident, complaint_after_resolve)."""
    route = create_route()
    block = create_block(route["id"])
    resident = create_resident(block["id"], email="r@x.com", full_name="Rae")
    complaint = file_complaint(resident["id"], block["id"], category=category)
    resolved = resolve_complaint(complaint["id"], resolution_note="swept next day")
    return block, resident, resolved
