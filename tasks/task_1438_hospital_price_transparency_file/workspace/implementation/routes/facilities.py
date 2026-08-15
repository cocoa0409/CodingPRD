"""Facility registration, read, and the CMS attestation/enforcement machine."""

from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_ATTESTATION_INVALID_STATE,
    ERR_ATTESTATION_YEAR_MISMATCH,
    ERR_DUPLICATE_CCN,
    ERR_FACILITY_NOT_FOUND,
    ERR_INVALID_WINDOW,
    ERR_NO_CONTAINING_ANNUAL_CYCLE,
)
from middleware import ALL_ROLES, require_roles
from response import success_object
from services.core import compute_penalty, facility_view
from util import (
    get_json_body,
    optional_bool,
    optional_int,
    optional_enum,
    require_enum,
    require_int,
    require_string,
    require_ts,
    require_field,
    parse_iso8601,
)

bp = Blueprint("facilities", __name__)

PENALTY_POLICIES = {"SIMPLE", "TIERED"}
DECISIONS = {"ACCEPT_ATTESTATION", "REJECT_ATTESTATION", "ACCEPT_PLAN", "REJECT_PLAN"}


def get_facility_or_404(fid: str) -> dict:
    fac = db.facilities.get(fid)
    if fac is None:
        raise_err(ERR_FACILITY_NOT_FOUND, "Facility not found")
    return fac


@bp.post("/transparency/facilities")
@require_roles("PlatformAdmin")
def create_facility(_user_id: str, _role: str):
    body = get_json_body()
    name = require_string(body, "name")
    ccn = require_string(body, "cms_certification_number")
    bed_count = require_int(body, "bed_count", minimum=0)
    penalty_policy = optional_enum(body, "penalty_policy", PENALTY_POLICIES, default="SIMPLE")
    min_records = optional_int(body, "min_records_per_cycle", minimum=0)
    if min_records is None:
        min_records = 1
    shoppable_min = optional_int(body, "shoppable_min_entries", minimum=0)
    if shoppable_min is None:
        shoppable_min = 300
    mandated_min = optional_int(body, "mandated_min_entries", minimum=0)
    if mandated_min is None:
        mandated_min = 70
    display_enabled = optional_bool(body, "shoppable_display_enabled", default=True)

    # Structural: CCN unique across the platform.
    for f in db.facilities.values():
        if f["cms_certification_number"] == ccn:
            raise_err(ERR_DUPLICATE_CCN, "cms_certification_number already registered")

    fac = db.stamp_new({
        "name": name,
        "cms_certification_number": ccn,
        "bed_count": bed_count,
        "penalty_policy": penalty_policy,
        "min_records_per_cycle": min_records,
        "shoppable_min_entries": shoppable_min,
        "mandated_min_entries": mandated_min,
        "shoppable_display_enabled": display_enabled,
        "attestation_status": "NONE",
        "attestation_year": None,
        "attestation_cycle_id": None,
        "rejected_at": None,
        "plan_due_date": None,
        "penalty_accrued_cents": 0,
    })
    db.facilities[fac["id"]] = fac
    return success_object(facility_view(fac), 201)


@bp.get("/transparency/facilities/<fid>")
@require_roles(*ALL_ROLES)
def get_facility(fid: str, _user_id: str, _role: str):
    return success_object(facility_view(get_facility_or_404(fid)), 200)


def _containing_annual_cycle(facility_id: str, year: int):
    """ANNUAL PUBLISHED cycles whose half-open window fully contains the
    calendar year [year-01-01, (year+1)-01-01)."""
    year_start = datetime(year, 1, 1, tzinfo=timezone.utc)
    year_end_excl = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    matches = []
    for c in db.publication_cycles.values():
        if c["facility_id"] != facility_id or c["cycle_type"] != "ANNUAL" or c["status"] != "PUBLISHED":
            continue
        if db.parse_dt(c["period_start"]) <= year_start and db.parse_dt(c["period_end"]) >= year_end_excl:
            matches.append(c)
    # Selector: latest period_start, tie-break created_at ASC (insertion order).
    matches.sort(key=lambda c: (-db.parse_dt(c["period_start"]).timestamp(), c["created_at"], c["_seq"]))
    return matches[0] if matches else None


@bp.post("/transparency/facilities/<fid>/submit-attestation")
@require_roles("ComplianceAuditor")
def submit_attestation(fid: str, _user_id: str, _role: str):
    fac = get_facility_or_404(fid)
    body = get_json_body()
    year = require_int(body, "attestation_year")

    # State (P4)
    prior_status = fac["attestation_status"]
    if prior_status not in ("NONE", "CLOSED"):
        raise_err(ERR_ATTESTATION_INVALID_STATE, "Attestation may only be submitted from NONE or CLOSED")

    # Regulatory safety (P5): year must equal the logical clock's calendar year;
    # resubmission from CLOSED must name a different year than the previous one.
    if year != db.clock().year:
        raise_err(ERR_ATTESTATION_YEAR_MISMATCH, "attestation_year does not match the current logical clock year")
    if prior_status == "CLOSED" and fac.get("attestation_year") == year:
        raise_err(ERR_ATTESTATION_YEAR_MISMATCH, "Resubmission must name a different attestation_year")

    # Fiscal (P9): a containing ANNUAL PUBLISHED cycle must exist.
    cycle = _containing_annual_cycle(fid, year)
    if cycle is None:
        raise_err(ERR_NO_CONTAINING_ANNUAL_CYCLE, "No ANNUAL PUBLISHED cycle contains the attestation year")

    fac["attestation_status"] = "SUBMITTED"
    fac["attestation_year"] = year
    fac["attestation_cycle_id"] = cycle["id"]
    if prior_status == "CLOSED":
        fac["rejected_at"] = None
        fac["plan_due_date"] = None
        fac["penalty_accrued_cents"] = 0
    db.bump(fac)
    return success_object(facility_view(fac), 200)


@bp.post("/transparency/facilities/<fid>/cms-decision")
@require_roles("PlatformAdmin")
def cms_decision(fid: str, _user_id: str, _role: str):
    fac = get_facility_or_404(fid)
    body = get_json_body()
    decision = require_enum(body, "decision", DECISIONS)

    # State (P4): each decision pairs with exactly one source status.
    expected = {
        "ACCEPT_ATTESTATION": "SUBMITTED",
        "REJECT_ATTESTATION": "SUBMITTED",
        "ACCEPT_PLAN": "PLAN_SUBMITTED",
        "REJECT_PLAN": "PLAN_SUBMITTED",
    }[decision]
    if fac["attestation_status"] != expected:
        raise_err(ERR_ATTESTATION_INVALID_STATE, f"{decision} is not defined from {fac['attestation_status']}")

    # Temporal (P8): rejections carry a plan_due_date strictly after the clock.
    plan_due_raw = None
    if decision in ("REJECT_ATTESTATION", "REJECT_PLAN"):
        plan_due_raw = require_ts(body, "plan_due_date")
        if parse_iso8601(plan_due_raw, "plan_due_date") <= db.clock():
            raise_err(ERR_INVALID_WINDOW, "plan_due_date must be strictly after the current clock")

    if decision == "ACCEPT_ATTESTATION":
        fac["attestation_status"] = "ACCEPTED"  # rejected_at stays null; no accrual
    elif decision == "REJECT_ATTESTATION":
        fac["attestation_status"] = "REJECTED"
        fac["rejected_at"] = db.now_iso()
        fac["plan_due_date"] = plan_due_raw
        fac["penalty_accrued_cents"] = 0  # accrual restarts from the new rejection
        # Enforcement cascade: retract PUBLISHED files of the attestation cycle.
        for f in db.machine_readable_files.values():
            if (
                f["publication_cycle_id"] == fac.get("attestation_cycle_id")
                and f["generation_status"] == "PUBLISHED"
            ):
                f["generation_status"] = "RETRACTED"
                db.bump(f)
    elif decision == "ACCEPT_PLAN":
        # Penalty accrual freezes at its current value.
        fac["penalty_accrued_cents"] = compute_penalty(fac)
        fac["attestation_status"] = "CLOSED"
    else:  # REJECT_PLAN — rejected_at UNCHANGED; accrual continues from origin
        fac["attestation_status"] = "REJECTED"
        fac["plan_due_date"] = plan_due_raw
    db.bump(fac)
    return success_object(facility_view(fac), 200)


@bp.post("/transparency/facilities/<fid>/submit-plan")
@require_roles("ComplianceAuditor")
def submit_plan(fid: str, _user_id: str, _role: str):
    fac = get_facility_or_404(fid)
    # State (P4) before body shape: transition defined only from REJECTED/ESCALATED.
    if fac["attestation_status"] not in ("REJECTED", "ESCALATED"):
        raise_err(ERR_ATTESTATION_INVALID_STATE, "Plan may only be submitted from REJECTED or ESCALATED")
    body = get_json_body()
    require_string(body, "plan_text")
    # Freeze the accrual at its current value while the plan is reviewed.
    fac["penalty_accrued_cents"] = compute_penalty(fac)
    fac["attestation_status"] = "PLAN_SUBMITTED"
    db.bump(fac)
    return success_object(facility_view(fac), 200)
