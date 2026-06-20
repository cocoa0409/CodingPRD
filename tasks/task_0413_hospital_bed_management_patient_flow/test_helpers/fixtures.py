"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface
as clear "setup failed" errors rather than confusing assertion failures.

Every helper builds its preconditions from scratch via PRD-declared endpoints,
because the harness restarts the server (empty DB) before every test.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_unit_payload, create_bed_payload, create_block_payload,
    create_encounter_payload, create_bed_request_payload, create_assign_payload,
    create_confirm_payload, create_evs_task_payload, create_discharge_barrier_payload,
    create_surge_event_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["flow_admin_headers"]
BCC = TEST_USERS["bed_control_headers"]
NURSE = TEST_USERS["charge_nurse_headers"]
TCA = TEST_USERS["transfer_agent_headers"]
CM = TEST_USERS["case_manager_headers"]
EVS = TEST_USERS["evs_tech_headers"]


# ─── Clock control ──────────────────────────────────────────────────────────

def set_clock(iso8601: str):
    """Set the simulated UTC clock. Returns the result object."""
    return get_success_data(api_client.set_clock(iso8601, ADMIN))


# ─── Tier 1: Units and beds ─────────────────────────────────────────────────

def create_unit(name="Test Unit", unit_type="MEDSURG", gmlos_days=None):
    """Create a unit. Returns the Unit dict."""
    payload = create_unit_payload(name=name, unit_type=unit_type)
    if gmlos_days is not None:
        payload["gmlos_days"] = gmlos_days
    return get_success_data(api_client.create_unit(payload, ADMIN))


def add_bed(unit_id, label="Bed", **bed_overrides):
    """Add a DIRTY bed to a unit. Returns the Bed dict."""
    payload = create_bed_payload(unit_id, label=label, **bed_overrides)
    return get_success_data(api_client.create_bed(unit_id, payload, NURSE))


def add_clean_bed(unit_id, label="Bed", **bed_overrides):
    """Add a bed and mark it CLEAN directly. Returns the CLEAN Bed dict
    (carrying its current version, useful as expected_bed_version)."""
    bed = add_bed(unit_id, label=label, **bed_overrides)
    cleaned = get_success_data(api_client.mark_clean_bed(unit_id, bed["id"], NURSE))
    return cleaned


def create_unit_with_clean_bed(unit_name="U", unit_type="MEDSURG",
                               gmlos_days=None, bed_label="B1", **bed_overrides):
    """Active unit + one CLEAN bed. Returns (unit, clean_bed)."""
    unit = create_unit(name=unit_name, unit_type=unit_type, gmlos_days=gmlos_days)
    bed = add_clean_bed(unit["id"], label=bed_label, **bed_overrides)
    return unit, bed


# ─── Tier 2: Encounters ─────────────────────────────────────────────────────

def register_encounter(mrn="M-X", sex="MALE", origin="ED", **enc_overrides):
    """Register an encounter. Returns the Encounter dict."""
    payload = create_encounter_payload(mrn=mrn, sex=sex, origin=origin, **enc_overrides)
    return get_success_data(api_client.create_encounter(payload, BCC))


def register_and_admit(mrn="M-X", sex="MALE", origin="ED", **enc_overrides):
    """Register encounter + place admit order. ED origin auto-advances to BOARDING.
    Returns the Encounter dict after the admit order."""
    enc = register_encounter(mrn=mrn, sex=sex, origin=origin, **enc_overrides)
    return get_success_data(api_client.admit_order(enc["id"], BCC))


# ─── Tier 3: BedRequest placement lifecycle ─────────────────────────────────

def create_queued_request(encounter_id, **req_overrides):
    """Create a QUEUED bed request. Returns the BedRequest dict."""
    payload = create_bed_request_payload(encounter_id, **req_overrides)
    return get_success_data(api_client.create_bed_request(payload, TCA))


def assign_request(request_id, bed_id):
    """Manually assign a specific bed to a queued request. Returns BedRequest dict."""
    return get_success_data(
        api_client.assign_bed_request(request_id, create_assign_payload(bed_id), BCC))


def confirm_request(request_id, expected_bed_version):
    """Confirm an assigned request. Returns BedRequest dict (CONFIRMED)."""
    return get_success_data(
        api_client.confirm_bed_request(
            request_id, create_confirm_payload(expected_bed_version), BCC))


def place_encounter_in_bed(unit, clean_bed, encounter,
                           preferred=True, req_overrides=None):
    """Drive a registered+admitted encounter through assign+confirm into a CLEAN bed.

    Returns (request, placed_encounter, occupied_bed). The encounter must already
    be ADMIT_PENDING (DIRECT/TRANSFER_IN) or BOARDING (ED).
    """
    overrides = dict(req_overrides or {})
    if preferred:
        overrides.setdefault("preferred_unit_id", unit["id"])
    req = create_queued_request(encounter["id"], **overrides)
    assign_request(req["id"], clean_bed["id"])
    confirmed = confirm_request(req["id"], clean_bed["version"])
    placed_enc = get_success_data(api_client.get_encounter(encounter["id"], BCC))
    occ_bed = get_success_data(api_client.get_bed(unit["id"], clean_bed["id"], NURSE))
    return confirmed, placed_enc, occ_bed


def setup_placed_encounter(unit_type="MEDSURG", gmlos_days=None, origin="ED",
                           sex="MALE", mrn="M-P", bed_label="B1",
                           bed_overrides=None, enc_overrides=None,
                           preferred=True):
    """Full setup: unit + CLEAN bed + registered/admitted encounter placed into the bed.

    Returns (unit, occupied_bed, placed_encounter, request).
    """
    unit, bed = create_unit_with_clean_bed(
        unit_name="PU", unit_type=unit_type, gmlos_days=gmlos_days,
        bed_label=bed_label, **(bed_overrides or {}))
    enc = register_and_admit(mrn=mrn, sex=sex, origin=origin, **(enc_overrides or {}))
    req, placed_enc, occ_bed = place_encounter_in_bed(
        unit, bed, enc, preferred=preferred)
    return unit, occ_bed, placed_enc, req


# ─── Tier 4: Discharge lifecycle ────────────────────────────────────────────

def order_discharge(encounter_id):
    """PLACED -> DISCHARGE_ORDERED. Returns Encounter dict."""
    return get_success_data(api_client.discharge_order(encounter_id, CM))


def setup_discharge_ordered_encounter(**kwargs):
    """Place an encounter then order its discharge.

    Returns (unit, occupied_bed, encounter, request).
    """
    unit, occ_bed, enc, req = setup_placed_encounter(**kwargs)
    order_discharge(enc["id"])
    enc_after = get_success_data(api_client.get_encounter(enc["id"], CM))
    return unit, occ_bed, enc_after, req


# ─── Tier 5: EVS tasks ──────────────────────────────────────────────────────

def create_evs_task(bed_id, task_type=None, headers=None):
    """Create an EVS task on a DIRTY bed. Returns EvsTask dict."""
    payload = create_evs_task_payload(bed_id)
    if task_type is not None:
        payload["task_type"] = task_type
    return get_success_data(api_client.create_evs_task(payload, headers or NURSE))


def setup_evs_task_in_progress(unit_name="EU", task_type="ROUTINE", tech_headers=None):
    """DIRTY bed with an EvsTask walked to IN_PROGRESS.

    Returns (unit, dirty_bed, evs_task).
    """
    tech = tech_headers or EVS
    unit = create_unit(name=unit_name)
    bed = add_bed(unit["id"], label="EVB")  # starts DIRTY
    task = create_evs_task(bed["id"], task_type=task_type)
    get_success_data(api_client.assign_evs_task(task["id"], {}, tech))
    started = get_success_data(api_client.start_evs_task(task["id"], tech))
    return unit, bed, started


# ─── Tier 6: Surge ──────────────────────────────────────────────────────────

def declare_surge(unit_id, level, reason=None):
    """Declare a surge on a unit. Returns SurgeEvent dict."""
    payload = create_surge_event_payload(unit_id, level)
    if reason is not None:
        payload["reason"] = reason
    return get_success_data(api_client.create_surge_event(payload, BCC))


# ─── Tier 7: Discharge barriers ─────────────────────────────────────────────

def open_barrier(encounter_id, barrier_type="TRANSPORT", note=None):
    """Open a discharge barrier on an encounter. Returns DischargeBarrier dict."""
    payload = create_discharge_barrier_payload(encounter_id, barrier_type)
    if note is not None:
        payload["note"] = note
    return get_success_data(api_client.create_discharge_barrier(payload, CM))
