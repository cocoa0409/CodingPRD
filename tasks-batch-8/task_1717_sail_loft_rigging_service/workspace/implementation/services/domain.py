"""Shared domain lookups, serialization, and cross-entity cascade logic."""

from datetime import date, datetime, timedelta, timezone

import db
import errors
import util
from services import calculations as calc


# ---------------------------------------------------------------------------
# Serialization (plain dict passthrough — entities are already JSON-shaped)
# ---------------------------------------------------------------------------

def serialize(entity):
    return dict(entity)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_customer_or_404(customer_id):
    c = db.customers.get(customer_id)
    if c is None:
        raise errors.not_found(f"Customer {customer_id} not found")
    return c


def get_boat_or_404(boat_id):
    b = db.boats.get(boat_id)
    if b is None:
        raise errors.not_found(f"Boat {boat_id} not found")
    return b


def get_sheet_or_404(sheet_id):
    s = db.measurement_sheets.get(sheet_id)
    if s is None:
        raise errors.not_found(f"MeasurementSheet {sheet_id} not found")
    return s


def get_design_or_404(design_id):
    d = db.sail_designs.get(design_id)
    if d is None:
        raise errors.not_found(f"SailDesign {design_id} not found")
    return d


def get_work_order_or_404(wo_id):
    w = db.work_orders.get(wo_id)
    if w is None:
        raise errors.not_found(f"LoftWorkOrder {wo_id} not found")
    return w


def get_job_or_404(job_id):
    j = db.production_jobs.get(job_id)
    if j is None:
        raise errors.not_found(f"ProductionJob {job_id} not found")
    return j


def get_bolt_or_404(bolt_id):
    b = db.cloth_ledger.get(bolt_id)
    if b is None:
        raise errors.not_found(f"ClothLedgerEntry {bolt_id} not found")
    return b


def get_inspection_or_404(insp_id):
    i = db.rigging_inspections.get(insp_id)
    if i is None:
        raise errors.not_found(f"RiggingInspection {insp_id} not found")
    return i


def get_mast_event_or_404(event_id):
    e = db.mast_service_events.get(event_id)
    if e is None:
        raise errors.not_found(f"MastServiceEvent {event_id} not found")
    return e


def get_contract_or_404(contract_id):
    c = db.storage_contracts.get(contract_id)
    if c is None:
        raise errors.not_found(f"StorageContract {contract_id} not found")
    return c


def get_cert_or_404(cert_id):
    c = db.class_certificates.get(cert_id)
    if c is None:
        raise errors.not_found(f"ClassCertificate {cert_id} not found")
    return c


def check_child_of(child, parent_field, parent_id):
    """Verify a nested resource belongs to the path parent (404 if not)."""
    if child.get(parent_field) != parent_id:
        raise errors.not_found(
            f"Resource does not belong to parent {parent_id}"
        )


# ---------------------------------------------------------------------------
# Cloth ledger
# ---------------------------------------------------------------------------

def cloth_available_sqm(bolt):
    """available_sqm = total_sqm - sum(reserved on non-terminal jobs against this bolt)."""
    reserved = 0.0
    for job in db.production_jobs.values():
        if job.get("bolt_id") == bolt["id"] and job["job_status"] not in (
            "QC_PASSED", "CANCELLED",
        ):
            reserved += job.get("reserved_cloth_sqm", 0) or 0
    return bolt["total_sqm"] - reserved


def refresh_bolt_availability(bolt):
    new_avail = cloth_available_sqm(bolt)
    if new_avail != bolt.get("available_sqm"):
        bolt["available_sqm"] = new_avail
        util.touch(bolt)


def total_available_for_tier(cloth_tier):
    return sum(
        b["available_sqm"] for b in db.cloth_ledger.values()
        if b["cloth_tier"] == cloth_tier
    )


def reserve_cloth(bolt, sqm):
    bolt["available_sqm"] = bolt["available_sqm"] - sqm
    util.touch(bolt)


def release_cloth(bolt, sqm):
    bolt["available_sqm"] = bolt["available_sqm"] + sqm
    util.touch(bolt)


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def supersede_frozen_sheet(boat, newly_frozen_sheet):
    """On freezing a new sheet: supersede any previously FROZEN sheet for the boat,
    cascade REVOKED to certificates and ARCHIVED to dependent designs."""
    for sheet in db.measurement_sheets.values():
        if (
            sheet["boat_id"] == boat["id"]
            and sheet["id"] != newly_frozen_sheet["id"]
            and sheet["sheet_status"] == "FROZEN"
        ):
            sheet["sheet_status"] = "SUPERSEDED"
            util.touch(sheet)
            # Cascade: certificates referencing the superseded sheet -> REVOKED
            for cert in db.class_certificates.values():
                if cert["measurement_sheet_id"] == sheet["id"] and cert["cert_status"] == "ACTIVE":
                    cert["cert_status"] = "REVOKED"
                    util.touch(cert)
            # Cascade: designs in DRAFT/SUBMITTED/REVISION_REQUESTED pinning it -> ARCHIVED
            for design in db.sail_designs.values():
                if (
                    design["measurement_sheet_id"] == sheet["id"]
                    and design["design_status"] in ("DRAFT", "SUBMITTED", "REVISION_REQUESTED")
                ):
                    design["design_status"] = "ARCHIVED"
                    util.touch(design)


def cancel_work_order_cascade(wo):
    """Three-hop cascade on work order cancel."""
    for job in db.production_jobs.values():
        if job["work_order_id"] == wo["id"] and job["job_status"] in (
            "SCHEDULED", "CUTTING", "SEAMING", "FINISHING",
        ):
            job["job_status"] = "CANCELLED"
            util.touch(job)
            # Hop 2: release reserved cloth
            bolt_id = job.get("bolt_id")
            if bolt_id and bolt_id in db.cloth_ledger:
                release_cloth(db.cloth_ledger[bolt_id], job.get("reserved_cloth_sqm", 0) or 0)
    # Hop 3: orphaned design -> ARCHIVED
    design_id = wo.get("sail_design_id")
    if design_id and design_id in db.sail_designs:
        design = db.sail_designs[design_id]
        other_refs = [
            o for o in db.work_orders.values()
            if o.get("sail_design_id") == design_id
            and o["id"] != wo["id"]
            and o["order_status"] != "CANCELLED"
        ]
        if not other_refs and design["design_status"] != "ARCHIVED":
            design["design_status"] = "ARCHIVED"
            util.touch(design)


def fail_inspection_cascade(boat):
    """FAIL verdict: boat ACTIVE->OUT_OF_SERVICE; BOOKED mast events -> RIGGING_HOLD."""
    if boat["status"] == "ACTIVE":
        boat["status"] = "OUT_OF_SERVICE"
        util.touch(boat)
    for ev in db.mast_service_events.values():
        if ev["boat_id"] == boat["id"] and ev["event_status"] == "BOOKED":
            ev["event_status"] = "RIGGING_HOLD"
            util.touch(ev)


def close_fail_inspection_release(boat):
    """On closing a FAIL inspection with a passing replacement: boat -> ACTIVE,
    held mast events -> BOOKED."""
    if boat["status"] == "OUT_OF_SERVICE":
        boat["status"] = "ACTIVE"
        util.touch(boat)
    for ev in db.mast_service_events.values():
        if ev["boat_id"] == boat["id"] and ev["event_status"] == "RIGGING_HOLD":
            ev["event_status"] = "BOOKED"
            util.touch(ev)


def supersede_approved_design_cascade(prior_design):
    """On creating a new revision: prior APPROVED design -> SUPERSEDED; any OPEN work
    order pinning it -> CANCELLED."""
    prior_design["design_status"] = "SUPERSEDED"
    util.touch(prior_design)
    for wo in db.work_orders.values():
        if wo.get("sail_design_id") == prior_design["id"] and wo["order_status"] == "OPEN":
            wo["order_status"] = "CANCELLED"
            util.touch(wo)
            cancel_work_order_cascade(wo)


# ---------------------------------------------------------------------------
# Overlap checks
# ---------------------------------------------------------------------------

def bay_conflict_exists(bay_code, start_d, end_d, exclude_job_id=None):
    for job in db.production_jobs.values():
        if job["bay_code"] != bay_code:
            continue
        if job["job_status"] == "CANCELLED":
            continue
        if exclude_job_id and job["id"] == exclude_job_id:
            continue
        j_start = date.fromisoformat(job["scheduled_start_date"])
        j_end = date.fromisoformat(job["scheduled_end_date"])
        if calc.bay_windows_conflict(start_d, end_d, j_start, j_end):
            return True
    return False


def mast_slot_conflict_exists(boat_id, slot_start, slot_end, exclude_event_id=None):
    for ev in db.mast_service_events.values():
        if ev["boat_id"] != boat_id:
            continue
        if ev["event_status"] not in ("BOOKED", "IN_PROGRESS", "RIGGING_HOLD"):
            continue
        if exclude_event_id and ev["id"] == exclude_event_id:
            continue
        e_start = util.parse_iso_datetime(ev["slot_start_utc"], "slot_start_utc")
        e_end = util.parse_iso_datetime(ev["slot_end_utc"], "slot_end_utc")
        if calc.mast_slots_conflict(slot_start, slot_end, e_start, e_end):
            return True
    return False
