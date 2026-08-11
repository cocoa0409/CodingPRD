"""SupplementalDataBatch + SupplementalRecord routes."""
from flask import Blueprint, request

import errors
from db import db, new_id, parse_dt
from middleware import require_roles, get_json_body, require_fields, require_enum, require_str
from response import success_object, success_list, parse_pagination
from serializers import batch_view, record_view
from services.core import (touch, find_run, find_batch, recompute_run_counters,
                           auto_close_gap_for_entry)
from services.supplemental import screen_batch

bp = Blueprint("supplemental", __name__)

ANALYST = ["QualityAnalyst"]
ALL = ["QualityAdmin", "QualityAnalyst", "Abstractor", "OverReader",
       "ProviderRelations", "Auditor", "QualityDirector"]

SOURCE_TYPES = ["LAB_FEED", "IMMUNIZATION_REGISTRY", "PHARMACY", "EHR"]


@bp.post("/hedis/supplemental-batches")
def create_batch():
    require_roles(ANALYST)
    body = get_json_body()
    require_fields(body, ["run_id", "source_type"])
    source_type = require_enum(body, "source_type", SOURCE_TYPES)
    run = find_run(body.get("run_id") if isinstance(body.get("run_id"), str) else "")
    rec = {
        "id": new_id(),
        "run_id": run["id"],
        "source_type": source_type,
        "status": "RECEIVED",
        "record_count": 0,
        "accepted_record_count": 0,
        "matching_policy_used": None,
        "created_at": db.clock,
        "updated_at": db.clock,
        "version": 1,
    }
    db.batches[rec["id"]] = rec
    return success_object(batch_view(rec), 201)


@bp.get("/hedis/supplemental-batches/<batchId>")
def get_batch(batchId):
    require_roles(ALL)
    b = find_batch(batchId)
    return success_object(batch_view(b))


@bp.post("/hedis/supplemental-batches/<batchId>/screen")
def screen(batchId):
    require_roles(ANALYST)
    get_json_body()
    b = find_batch(batchId)
    if b["status"] != "RECEIVED":
        raise errors.invalid_state("Batch must be RECEIVED to screen")
    run = db.runs.get(b["run_id"])
    if run is None:
        raise errors.not_found()
    season = db.seasons.get(run["season_id"])
    spec = db.specs.get(run["spec_id"])
    if season is None or spec is None:
        raise errors.not_found()
    screen_batch(b, run, season, spec)
    b["status"] = "SCREENED"
    touch(b)
    return success_object(batch_view(b))


@bp.post("/hedis/supplemental-batches/<batchId>/accept")
def accept(batchId):
    require_roles(ANALYST)
    get_json_body()
    b = find_batch(batchId)
    if b["status"] != "SCREENED":
        raise errors.invalid_state("Batch must be SCREENED to accept")
    run = db.runs.get(b["run_id"])
    if run is None:
        raise errors.not_found()
    season = db.seasons.get(run["season_id"])
    if season is None:
        raise errors.not_found()
    # priority 8.2: source approval — strictly before the denominator check
    if b["source_type"] not in season["approved_supplemental_sources"]:
        raise errors.ApiError(errors.ERR_UNAPPROVED_SUPPLEMENTAL_SOURCE, 422,
                              "source_type not in the season's approved registry")
    # priority 11: every record's member_ref must be in the non-excluded denominator
    non_excluded_refs = {e["member_ref"] for e in db.population_entries.values()
                         if e["run_id"] == run["id"] and not e["is_excluded"]}
    batch_records = [r for r in db.records.values() if r["batch_id"] == b["id"]]
    policy = b["matching_policy_used"] or "EXACT"
    from services.supplemental import normalize_ref
    for r in batch_records:
        if policy == "EXACT":
            present = r["member_ref"] in non_excluded_refs
        else:
            target = normalize_ref(r["member_ref"])
            present = any(normalize_ref(x) == target for x in non_excluded_refs)
        if not present:
            raise errors.ApiError(errors.ERR_RECORD_MEMBER_NOT_IN_DENOMINATOR, 422,
                                  "Record member_ref absent from the run's denominator")
    # run-state gate (checked after business gates per scaffold ordering)
    if run["reporting_status"] in ("SUBMITTED", "CERTIFIED", "CERTIFICATION_FAILED"):
        raise errors.invalid_state("Run no longer accepts supplemental evidence")

    # cascade link 1: flip admin_compliant for matching entries (ACCEPTED records only)
    entries_by_ref = {}
    for e in db.population_entries.values():
        if e["run_id"] == run["id"] and not e["is_excluded"]:
            entries_by_ref.setdefault(e["member_ref"], e)
    for r in batch_records:
        if r["disposition"] != "ACCEPTED":
            continue
        entry = None
        if policy == "EXACT":
            entry = entries_by_ref.get(r["member_ref"])
        else:
            target = normalize_ref(r["member_ref"])
            for ref, e in entries_by_ref.items():
                if normalize_ref(ref) == target:
                    entry = e
                    break
        if entry is None:
            continue
        if not entry["admin_compliant"]:
            entry["admin_compliant"] = True
            touch(entry)
            # cascade link 2+3: auto-close gap, reconcile provider count
            auto_close_gap_for_entry(run, entry)
    b["status"] = "ACCEPTED"
    touch(b)
    recompute_run_counters(run)
    return success_object(batch_view(b))


@bp.post("/hedis/supplemental-batches/<batchId>/reject")
def reject(batchId):
    require_roles(ANALYST)
    get_json_body()
    b = find_batch(batchId)
    if b["status"] != "SCREENED":
        raise errors.invalid_state("Batch must be SCREENED to reject")
    b["status"] = "REJECTED"
    touch(b)
    return success_object(batch_view(b))


@bp.get("/hedis/supplemental-batches/<id>/records")
def list_records(id):
    require_roles(ALL)
    find_batch(id)
    items = [r for r in db.records.values() if r["batch_id"] == id]
    disposition = request.args.get("disposition")
    if disposition is not None:
        items = [r for r in items if r["disposition"] == disposition]
    items.sort(key=lambda r: r["created_at"])
    limit, offset = parse_pagination(request.args)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([record_view(r) for r in page], limit, offset, total)


@bp.post("/hedis/supplemental-records")
def create_record():
    require_roles(ANALYST)
    body = get_json_body()
    require_fields(body, ["batch_id", "member_ref", "service_date", "evidence_code"])
    member_ref = require_str(body, "member_ref")
    evidence_code = require_str(body, "evidence_code")
    service_date = parse_dt(body.get("service_date"))
    if service_date is None:
        raise errors.invalid_request("service_date must be an ISO8601 datetime")
    batch = find_batch(body.get("batch_id") if isinstance(body.get("batch_id"), str) else "")
    # cross-entity guard: batch must be RECEIVED
    if batch["status"] != "RECEIVED":
        raise errors.invalid_state("Records may only be added while the batch is RECEIVED")
    # request-level duplicate (same batch, identical triple) — priority 12.7
    for r in db.records.values():
        if (r["batch_id"] == batch["id"]
                and r["member_ref"] == member_ref
                and r["service_date"] == service_date
                and r["evidence_code"] == evidence_code):
            raise errors.ApiError(errors.ERR_DUPLICATE_SERVICE_DATE, 409,
                                  "Identical record already exists in this batch")
    rec = {
        "id": new_id(),
        "batch_id": batch["id"],
        "member_ref": member_ref,
        "service_date": service_date,
        "evidence_code": evidence_code,
        "disposition": "PENDING",
        "created_at": db.clock,
    }
    db.records[rec["id"]] = rec
    batch["record_count"] += 1
    batch["updated_at"] = db.clock  # counter mutation; no version bump per scaffold
    return success_object(record_view(rec), 201)
