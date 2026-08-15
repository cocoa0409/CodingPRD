"""DiscrepancyReport: intake, triage, and the segregation-of-duties
correction pipeline (propose / approve / apply), PRD 3.7."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_CASH_EXCEEDS_GROSS,
    ERR_CHARGE_RECORD_NOT_FOUND,
    ERR_CYCLE_NOT_FOUND,
    ERR_CYCLE_NOT_PUBLISHED,
    ERR_DISCREPANCY_NOT_ACTIONABLE,
    ERR_DISCREPANCY_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_RECORD_CYCLE_MISMATCH,
    ERR_RECORD_NOT_DISPUTABLE,
    ERR_SOD_SAME_USER,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services.core import recompute_record
from util import (
    apply_filters,
    get_json_body,
    optional_int,
    paginate,
    parse_pagination,
    require_enum,
    require_string,
    sort_created,
)

bp = Blueprint("discrepancies", __name__)

REPORTER_TYPES = {"CONSUMER", "PAYER", "INTERNAL"}
TRIAGE_OUTCOMES = {"CONFIRMED", "DISMISSED"}


def get_discrepancy_or_404(did: str) -> dict:
    d = db.discrepancy_reports.get(did)
    if d is None:
        raise_err(ERR_DISCREPANCY_NOT_FOUND, "Discrepancy report not found")
    return d


@bp.post("/transparency/discrepancy-reports")
@require_roles(*ALL_ROLES)
def create_discrepancy(_user_id: str, _role: str):
    body = get_json_body()
    cycle_id = require_string(body, "publication_cycle_id")
    record_id = require_string(body, "standard_charge_record_id")
    reporter_type_raw = require_string(body, "reporter_type")
    description = require_string(body, "description")

    # Existence (P3), body field order: cycle, then record.
    cycle = db.publication_cycles.get(cycle_id)
    if cycle is None:
        raise_err(ERR_CYCLE_NOT_FOUND, "Publication cycle not found")
    rec = db.standard_charge_records.get(record_id)
    if rec is None:
        raise_err(ERR_CHARGE_RECORD_NOT_FOUND, "Standard charge record not found")

    # Enum membership after FK existence.
    if reporter_type_raw not in REPORTER_TYPES:
        raise_err(ERR_INVALID_REQUEST, "reporter_type must be CONSUMER, PAYER, or INTERNAL")

    # State (P4): the cycle must be PUBLISHED.
    if cycle["status"] != "PUBLISHED":
        raise_err(ERR_CYCLE_NOT_PUBLISHED, "Discrepancies may only target a PUBLISHED cycle")

    # Referential (P7), fixed order: record-cycle match first, then the
    # record's disputable status.
    if rec["publication_cycle_id"] != cycle_id:
        raise_err(ERR_RECORD_CYCLE_MISMATCH, "Record does not belong to the referenced cycle")
    if rec["status"] not in ("PUBLISHED", "FLAGGED"):
        raise_err(ERR_RECORD_NOT_DISPUTABLE, "Only PUBLISHED or FLAGGED records are disputable")

    d = db.stamp_new({
        "publication_cycle_id": cycle_id,
        "standard_charge_record_id": record_id,
        "reporter_type": reporter_type_raw,
        "description": description,
        "status": "SUBMITTED",
        "proposed_gross_charge_cents": None,
        "proposed_discounted_cash_cents": None,
        "proposed_by_user_id": None,
        "approved_by_user_id": None,
        "applied_by_user_id": None,
    })
    db.discrepancy_reports[d["id"]] = d
    return success_object(db.public(d), 201)


@bp.get("/transparency/discrepancy-reports/<did>")
@require_roles(*ALL_ROLES)
def get_discrepancy(did: str, _user_id: str, _role: str):
    return success_object(db.public(get_discrepancy_or_404(did)), 200)


@bp.get("/transparency/discrepancy-reports")
@require_roles(*ALL_ROLES)
def list_discrepancies(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = list(db.discrepancy_reports.values())
    items = apply_filters(items, ["publication_cycle_id", "standard_charge_record_id", "status"])
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([db.public(d) for d in page], limit, offset, total)


@bp.post("/transparency/discrepancy-reports/<did>/triage")
@require_roles("ComplianceAuditor")
def triage_discrepancy(did: str, _user_id: str, _role: str):
    d = get_discrepancy_or_404(did)
    # State (P4) first: triage is defined only from SUBMITTED.
    if d["status"] != "SUBMITTED":
        raise_err(ERR_DISCREPANCY_NOT_ACTIONABLE, "Triage is defined only from SUBMITTED")
    body = get_json_body()
    outcome = require_enum(body, "outcome", TRIAGE_OUTCOMES)

    if outcome == "CONFIRMED":
        d["status"] = "CONFIRMED"
        # Same-request cascade: the disputed record PUBLISHED -> FLAGGED.
        rec = db.standard_charge_records.get(d["standard_charge_record_id"])
        if rec is not None and rec["status"] == "PUBLISHED":
            rec["status"] = "FLAGGED"
            db.bump(rec)
    else:
        d["status"] = "DISMISSED"
    db.bump(d)
    return success_object(db.public(d), 200)


@bp.post("/transparency/discrepancy-reports/<did>/propose-correction")
@require_roles("TransparencyOfficer")
def propose_correction(did: str, _user_id: str, _role: str):
    d = get_discrepancy_or_404(did)
    # State (P4).
    if d["status"] != "CONFIRMED":
        raise_err(ERR_DISCREPANCY_NOT_ACTIONABLE, "Corrections may only be proposed from CONFIRMED")
    body = get_json_body()
    gross = optional_int(body, "proposed_gross_charge_cents", minimum=0)
    cash = optional_int(body, "proposed_discounted_cash_cents", minimum=0)
    if gross is None and cash is None:
        raise_err(ERR_INVALID_REQUEST, "At least one of proposed_gross_charge_cents / proposed_discounted_cash_cents is required")

    # Fiscal (P9): effective proposed cash must not exceed effective proposed
    # gross — a supplied side overrides, a missing side falls back to current.
    rec = db.standard_charge_records.get(d["standard_charge_record_id"])
    eff_gross = gross if gross is not None else (rec["gross_charge_cents"] if rec else 0)
    eff_cash = cash if cash is not None else (rec["discounted_cash_cents"] if rec else 0)
    if eff_cash > eff_gross:
        raise_err(ERR_CASH_EXCEEDS_GROSS, "Effective proposed discounted cash exceeds effective proposed gross")

    d["proposed_gross_charge_cents"] = gross
    d["proposed_discounted_cash_cents"] = cash
    d["proposed_by_user_id"] = _user_id
    d["status"] = "CORRECTION_PROPOSED"
    db.bump(d)
    return success_object(db.public(d), 200)


@bp.post("/transparency/discrepancy-reports/<did>/approve-correction")
@require_roles("TransparencyOfficer")
def approve_correction(did: str, _user_id: str, _role: str):
    d = get_discrepancy_or_404(did)
    # State (P4).
    if d["status"] != "CORRECTION_PROPOSED":
        raise_err(ERR_DISCREPANCY_NOT_ACTIONABLE, "Approval is defined only from CORRECTION_PROPOSED")
    # Regulatory safety (P5): segregation of duties — approver != proposer.
    if _user_id == d.get("proposed_by_user_id"):
        raise_err(ERR_SOD_SAME_USER, "The approver must differ from the proposer")
    d["approved_by_user_id"] = _user_id
    d["status"] = "CORRECTION_APPROVED"
    db.bump(d)
    return success_object(db.public(d), 200)


@bp.post("/transparency/discrepancy-reports/<did>/apply-correction")
@require_roles("TransparencyOfficer")
def apply_correction(did: str, _user_id: str, _role: str):
    d = get_discrepancy_or_404(did)
    # State (P4).
    if d["status"] != "CORRECTION_APPROVED":
        raise_err(ERR_DISCREPANCY_NOT_ACTIONABLE, "Application is defined only from CORRECTION_APPROVED")
    # Regulatory safety (P5): applier != approver.
    if _user_id == d.get("approved_by_user_id"):
        raise_err(ERR_SOD_SAME_USER, "The applier must differ from the approver")

    old = db.standard_charge_records.get(d["standard_charge_record_id"])
    if old is None:
        raise_err(ERR_CHARGE_RECORD_NOT_FOUND, "Disputed record not found")

    # Cascade link 1: disputed record FLAGGED -> SUPERSEDED; the replacement
    # is born directly in PUBLISHED with the proposed overrides applied.
    old["status"] = "SUPERSEDED"
    db.bump(old)

    new_rec = db.stamp_new({
        "facility_id": old["facility_id"],
        "publication_cycle_id": old["publication_cycle_id"],
        "service_item_id": old["service_item_id"],
        "supersedes_id": old["id"],
        "gross_charge_cents": d["proposed_gross_charge_cents"] if d["proposed_gross_charge_cents"] is not None else old["gross_charge_cents"],
        "discounted_cash_cents": d["proposed_discounted_cash_cents"] if d["proposed_discounted_cash_cents"] is not None else old["discounted_cash_cents"],
        "min_negotiated_cents": None,
        "max_negotiated_cents": None,
        "derived_disclosure_cents": None,
        "derivation_method": "NONE",
        "status": "PUBLISHED",
    })
    recompute_record(new_rec)
    db.standard_charge_records[new_rec["id"]] = new_rec

    # Cascade link 2: the owning cycle's aggregates recompute from child state
    # (count conserved — the old record leaves the counted set as the new one
    # enters); the cycle's version increments.
    cycle = db.publication_cycles.get(old["publication_cycle_id"])
    if cycle is not None:
        db.bump(cycle)

    d["applied_by_user_id"] = _user_id
    d["status"] = "CORRECTED"
    db.bump(d)
    return success_object(db.public(d), 200)
