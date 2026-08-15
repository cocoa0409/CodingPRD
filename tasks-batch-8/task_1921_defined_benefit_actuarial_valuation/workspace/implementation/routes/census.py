"""CensusBatch and Participant endpoints."""

from flask import Blueprint, request

from db import store
from middleware import require_roles
from response import success_object, success_list, parse_pagination, list_page
from errors import (
    invalid_state, plan_terminated, validation, ApiError,
    ERR_PLAN_YEAR_MISMATCH, ERR_CENSUS_YEAR_CONFLICT, ERR_UNIQUENESS_VIOLATION,
    ERR_INVALID_PARTICIPANT_DATA,
)
from validate import body_of, req_str, req_int, NUM
from services.core import (
    base_record, touch, public, get_plan, get_batch, get_participant,
    screen_participant_row, recompute_batch_counts, batch_participants,
    r2, attained_age, parse_iso,
)

bp = Blueprint("census", __name__)

READ_ROLES = ["PlanAdmin", "Actuary", "SeniorActuary", "Auditor"]
PARTICIPANT_STATUSES = ("ACTIVE", "TERMINATED_VESTED", "RETIREE")
NUMERIC_FIELDS = ("years_of_service", "annual_compensation", "deferred_benefit_annual", "current_annual_benefit")


def _plan_active_gate(plan):
    if plan["status"] != "ACTIVE":
        raise plan_terminated()


def _parse_date(s):
    from datetime import datetime as _dt
    return parse_iso(s) if "T" in s else _dt.fromisoformat(s)


# ---------------------------------------------------------------------------
# CensusBatch
# ---------------------------------------------------------------------------

@bp.route("/v1/plans/<plan_id>/census-batches", methods=["POST"])
def create_census_batch(plan_id):
    require_roles(["PlanAdmin"])
    plan = get_plan(plan_id)
    _plan_active_gate(plan)
    body = body_of(request)
    # priority 11: plan-year match (before body well-formedness)
    py = body.get("plan_year")
    if isinstance(py, int) and not isinstance(py, bool) and py != plan["plan_year"]:
        raise ApiError(ERR_PLAN_YEAR_MISMATCH, 422, "plan_year differs from the plan's plan_year")
    plan_year = req_int(body, "plan_year")
    source_label = req_str(body, "source_label")

    rec = base_record()
    rec.update({
        "plan_id": plan["id"],
        "plan_year": plan_year,
        "source_label": source_label,
        "status": "UPLOADED",
        "participant_count": 0,
        "error_count": 0,
        "screening_errors": [],
    })
    store.census_batches[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/v1/plans/<plan_id>/census-batches", methods=["GET"])
def list_census_batches(plan_id):
    require_roles(READ_ROLES)
    plan = get_plan(plan_id)
    limit, offset = parse_pagination(request.args)
    items = [b for b in store.census_batches.values() if b["plan_id"] == plan["id"]]
    page, total = list_page(items, limit, offset)
    return success_list([public(b) for b in page], limit, offset, total)


@bp.route("/v1/census-batches/<batch_id>", methods=["GET"])
def fetch_census_batch(batch_id):
    require_roles(READ_ROLES)
    batch = get_batch(batch_id)
    return success_object(public(batch))


# ---------------------------------------------------------------------------
# Participant bulk append (tolerant: rows stored; validity adjudicated at screening)
# ---------------------------------------------------------------------------

def _validate_row_schema(row, idx):
    """Structural (schema) checks on an incoming row. Raises ERR_VALIDATION."""
    if not isinstance(row, dict):
        raise validation(f"participants[{idx}] must be an object")
    ext = row.get("external_ref")
    if not isinstance(ext, str) or not ext:
        raise validation(f"participants[{idx}].external_ref is required and must be a string")
    dob = row.get("date_of_birth")
    if not isinstance(dob, str):
        raise validation(f"participants[{idx}].date_of_birth is required and must be an ISO date string")
    try:
        _parse_date(dob)
    except Exception:
        raise validation(f"participants[{idx}].date_of_birth must be a valid ISO date")
    status = row.get("status")
    if status not in PARTICIPANT_STATUSES:
        raise validation(f"participants[{idx}].status must be one of {list(PARTICIPANT_STATUSES)}")
    for f in NUMERIC_FIELDS:
        if f in row and row[f] is not None:
            v = row[f]
            if isinstance(v, bool) or not isinstance(v, NUM):
                raise validation(f"participants[{idx}].{f} must be a number")


@bp.route("/v1/census-batches/<batch_id>/participants", methods=["POST"])
def append_participants(batch_id):
    require_roles(["PlanAdmin"])
    batch = get_batch(batch_id)
    plan = store.plans.get(batch["plan_id"])
    # priority 4: generic from-state — only UPLOADED or NEEDS_CORRECTION accept rows
    if batch["status"] not in ("UPLOADED", "NEEDS_CORRECTION"):
        raise invalid_state("CensusBatch does not accept participant rows in its current status")
    # priority 5: plan-active gate
    if plan is not None and plan["status"] != "ACTIVE":
        raise plan_terminated()
    body = body_of(request)
    rows = body.get("participants")
    if not isinstance(rows, list):
        raise validation("participants must be an array")

    # structural validation of every row (request-level, ERR_VALIDATION)
    for i, row in enumerate(rows):
        _validate_row_schema(row, i)

    # priority 17: external_ref unique within the batch (existing + incoming)
    seen = {p["external_ref"] for p in batch_participants(batch["id"])}
    incoming = set()
    for row in rows:
        ref = row["external_ref"]
        if ref in seen or ref in incoming:
            raise ApiError(ERR_UNIQUENESS_VIOLATION, 409, f"external_ref {ref} already exists in this batch")
        incoming.add(ref)

    for row in rows:
        rec = base_record()
        rec.update({
            "census_batch_id": batch["id"],
            "external_ref": row["external_ref"],
            "date_of_birth": row["date_of_birth"],
            "status": row["status"],
            "years_of_service": row.get("years_of_service"),
            "annual_compensation": r2(row["annual_compensation"]) if row.get("annual_compensation") is not None else None,
            "deferred_benefit_annual": r2(row["deferred_benefit_annual"]) if row.get("deferred_benefit_annual") is not None else None,
            "current_annual_benefit": r2(row["current_annual_benefit"]) if row.get("current_annual_benefit") is not None else None,
        })
        store.participants[rec["id"]] = rec

    # side effects: counts recomputed; NEEDS_CORRECTION returns to UPLOADED
    recompute_batch_counts(batch)
    batch["screening_errors"] = []
    batch["error_count"] = 0
    if batch["status"] == "NEEDS_CORRECTION":
        batch["status"] = "UPLOADED"
    touch(batch)
    return success_object(public(batch))


@bp.route("/v1/census-batches/<batch_id>/participants", methods=["GET"])
def list_participants(batch_id):
    require_roles(READ_ROLES)
    batch = get_batch(batch_id)
    limit, offset = parse_pagination(request.args)
    page, total = list_page(batch_participants(batch["id"]), limit, offset)
    return success_list([public(p) for p in page], limit, offset, total)


@bp.route("/v1/participants/<participant_id>", methods=["GET"])
def fetch_participant(participant_id):
    require_roles(READ_ROLES)
    rec = get_participant(participant_id)
    return success_object(public(rec))


# ---------------------------------------------------------------------------
# Screening and lock
# ---------------------------------------------------------------------------

@bp.route("/v1/census-batches/<batch_id>/submit-screening", methods=["POST"])
def submit_screening(batch_id):
    require_roles(["PlanAdmin"])
    batch = get_batch(batch_id)
    plan = store.plans.get(batch["plan_id"])
    if batch["status"] != "UPLOADED":
        raise invalid_state("CensusBatch is not UPLOADED")
    if plan is not None and plan["status"] != "ACTIVE":
        raise plan_terminated()
    # priority 18: batch must be non-empty
    rows = batch_participants(batch["id"])
    if len(rows) == 0:
        raise ApiError(ERR_INVALID_PARTICIPANT_DATA, 422, "Census batch has no participant rows")

    # row-level screening
    errors = []
    for p in rows:
        row_errors = screen_participant_row(p, batch["plan_year"])
        for msg in row_errors:
            errors.append({
                "participant_id": p["id"],
                "external_ref": p["external_ref"],
                "message": msg,
            })

    if errors:
        batch["status"] = "NEEDS_CORRECTION"
        batch["error_count"] = len(errors)
        batch["screening_errors"] = errors
        touch(batch)
        return success_object(public(batch))

    # priority 15: census plan-year uniqueness against VALIDATED/LOCKED siblings
    for other in store.census_batches.values():
        if (
            other["id"] != batch["id"]
            and other["plan_id"] == batch["plan_id"]
            and other["plan_year"] == batch["plan_year"]
            and other["status"] in ("VALIDATED", "LOCKED")
        ):
            raise ApiError(ERR_CENSUS_YEAR_CONFLICT, 409, "Another census batch is already VALIDATED or LOCKED for this plan_year")

    batch["status"] = "VALIDATED"
    batch["error_count"] = 0
    batch["screening_errors"] = []
    touch(batch)
    return success_object(public(batch))


@bp.route("/v1/census-batches/<batch_id>/lock", methods=["POST"])
def lock_census_batch(batch_id):
    require_roles(["PlanAdmin"])
    batch = get_batch(batch_id)
    plan = store.plans.get(batch["plan_id"])
    if batch["status"] != "VALIDATED":
        raise invalid_state("CensusBatch is not VALIDATED")
    if plan is not None and plan["status"] != "ACTIVE":
        raise plan_terminated()
    # priority 15: no other LOCKED batch for the same plan_year
    for other in store.census_batches.values():
        if (
            other["id"] != batch["id"]
            and other["plan_id"] == batch["plan_id"]
            and other["plan_year"] == batch["plan_year"]
            and other["status"] == "LOCKED"
        ):
            raise ApiError(ERR_CENSUS_YEAR_CONFLICT, 409, "Another census batch is already LOCKED for this plan_year")
    batch["status"] = "LOCKED"
    touch(batch)
    return success_object(public(batch))
