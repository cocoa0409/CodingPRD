"""Firm element plans: create (OCC on Representative) / list / get /
needs-analysis / publish / close."""

from decimal import Decimal

from flask import Blueprint, request

from db import store, base_record, touch, audit, clock_now
from errors import (ApiError, ERR_STALE_VERSION, ERR_DUPLICATE_PLAN_YEAR,
                    ERR_PLAN_NOT_NEEDS_ANALYSIS, ERR_NEEDS_ANALYSIS_MISSING,
                    ERR_PLAN_NOT_PUBLISHED, ERR_PLAN_HOURS_UNMET)
from middleware import require_roles, actor, json_body, require_fields
from response import success, paginate
from services import (get_or_404, by_seq, compute_required_hours,
                      recompute_plan)
from util import require_int, require_str, view
from routes.enrollments import _check_rep_active

bp = Blueprint("plans", __name__)

ANY = ("TrainingAdmin", "ComplianceOfficer", "RegisteredRep", "Auditor")


@bp.post("/firm-element-plans")
@require_roles("TrainingAdmin")
def create_plan():
    body = json_body()
    rep = None
    if body.get("rep_id") is not None:
        rep = get_or_404(store.representatives, body["rep_id"], "Representative")
    # Shape: plan_year and the mandatory OCC field.
    require_fields(body, "rep_id", "plan_year", "expected_representative_version")
    plan_year = require_int(body["plan_year"], "plan_year")
    expected = require_int(body["expected_representative_version"],
                           "expected_representative_version")
    # OCC on the Representative (before business checks).
    if expected != rep["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_representative_version does not match the "
                       "representative's current version")
    # Registration standing.
    _check_rep_active(rep)
    # Uniqueness: a PLAN_PUBLISHED or CLOSED plan for rep+year blocks creation.
    superseded = None
    for p in store.plans.values():
        if p["rep_id"] == rep["id"] and p["plan_year"] == plan_year:
            if p["plan_status"] in ("PLAN_PUBLISHED", "CLOSED"):
                raise ApiError(ERR_DUPLICATE_PLAN_YEAR, 409,
                               "A published or closed plan already exists for "
                               "this rep and plan_year")
            if p["plan_status"] == "NEEDS_ANALYSIS":
                superseded = p
    if superseded is not None:
        superseded["plan_status"] = "SUPERSEDED"
        touch(superseded)
    rec = base_record()
    rec.update({
        "rep_id": rep["id"],
        "plan_year": plan_year,
        "plan_status": "NEEDS_ANALYSIS",
        "needs_analysis_document_ref": None,
        "needs_analysis_notes": None,
        "needs_analysis_completed_at": None,
        "required_hours": None,
        "certified_hours": Decimal("0"),
        "projected_hours": Decimal("0"),
        "published_at": None,
        "closed_at": None,
    })
    store.plans[rec["id"]] = rec
    # Plan creation bumps the representative's version (the OCC anchor).
    touch(rep)
    return success(view(rec), status=201)


@bp.get("/firm-element-plans")
@require_roles(*ANY)
def list_plans():
    items = by_seq(store.plans.values())
    rep_id = request.args.get("rep_id")
    if rep_id is not None:
        items = [p for p in items if p["rep_id"] == rep_id]
    plan_year = request.args.get("plan_year")
    if plan_year is not None:
        try:
            year_val = int(plan_year)
            items = [p for p in items if p["plan_year"] == year_val]
        except ValueError:
            items = []
    plan_status = request.args.get("plan_status")
    if plan_status is not None:
        items = [p for p in items if p["plan_status"] == plan_status]
    items = sorted(items, key=lambda p: (p["created_at"], p["_seq"]))
    page, pagination = paginate(items)
    return success([view(p) for p in page], is_list=True, pagination=pagination)


@bp.get("/firm-element-plans/<planId>")
@require_roles(*ANY)
def get_plan(planId):
    rec = get_or_404(store.plans, planId, "FirmElementPlan")
    return success(view(rec))


@bp.post("/firm-element-plans/<planId>/needs-analysis")
@require_roles("TrainingAdmin")
def record_needs_analysis(planId):
    rec = get_or_404(store.plans, planId, "FirmElementPlan")
    body = json_body()
    require_fields(body, "analysis_document_ref", "analysis_notes")
    doc_ref = require_str(body["analysis_document_ref"], "analysis_document_ref")
    notes = body["analysis_notes"]
    if not isinstance(notes, str):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field 'analysis_notes' must be a string")
    if rec["plan_status"] != "NEEDS_ANALYSIS":
        raise ApiError(ERR_PLAN_NOT_NEEDS_ANALYSIS, 409,
                       "needs-analysis requires plan_status == NEEDS_ANALYSIS")
    rec["needs_analysis_document_ref"] = doc_ref
    rec["needs_analysis_notes"] = notes
    rec["needs_analysis_completed_at"] = clock_now()
    touch(rec)
    return success(view(rec))


@bp.post("/firm-element-plans/<planId>/publish")
@require_roles("TrainingAdmin")
def publish_plan(planId):
    rec = get_or_404(store.plans, planId, "FirmElementPlan")
    if rec["plan_status"] != "NEEDS_ANALYSIS":
        raise ApiError(ERR_PLAN_NOT_NEEDS_ANALYSIS, 409,
                       "publish requires plan_status == NEEDS_ANALYSIS")
    if rec["needs_analysis_completed_at"] is None:
        raise ApiError(ERR_NEEDS_ANALYSIS_MISSING, 409,
                       "Needs analysis must be recorded before publish")
    rep = store.representatives[rec["rep_id"]]
    # Requirement is fixed at publish and never recomputed afterwards.
    rec["required_hours"] = compute_required_hours(rep, rec["plan_year"])
    rec["plan_status"] = "PLAN_PUBLISHED"
    rec["published_at"] = clock_now()
    touch(rec)
    recompute_plan(rec)
    # Publish spawns the plan's annual attestation in PENDING.
    att = base_record()
    att.update({
        "rep_id": rec["rep_id"],
        "plan_id": rec["id"],
        "attestation_status": "PENDING",
        "attestation_statement": None,
        "attested_at": None,
    })
    store.attestations[att["id"]] = att
    a = actor()
    audit("PLAN_PUBLISHED", "FirmElementPlan", rec["id"], a[0], a[1],
          "plan_status: NEEDS_ANALYSIS -> PLAN_PUBLISHED; required_hours=%s"
          % rec["required_hours"])
    return success(view(rec))


@bp.post("/firm-element-plans/<planId>/close")
@require_roles("TrainingAdmin")
def close_plan(planId):
    rec = get_or_404(store.plans, planId, "FirmElementPlan")
    if rec["plan_status"] != "PLAN_PUBLISHED":
        raise ApiError(ERR_PLAN_NOT_PUBLISHED, 409,
                       "close requires plan_status == PLAN_PUBLISHED")
    recompute_plan(rec)
    if rec["certified_hours"] < rec["required_hours"]:
        raise ApiError(ERR_PLAN_HOURS_UNMET, 409,
                       "certified_hours %s is below required_hours %s"
                       % (rec["certified_hours"], rec["required_hours"]))
    rec["plan_status"] = "CLOSED"
    rec["closed_at"] = clock_now()
    touch(rec)
    a = actor()
    audit("PLAN_CLOSED", "FirmElementPlan", rec["id"], a[0], a[1],
          "plan_status: PLAN_PUBLISHED -> CLOSED")
    return success(view(rec))
