"""GrowthRecord endpoints (PRD §3.2)."""

from flask import Blueprint, request

import errors
from db import db, lock
from helpers import (
    get_json_body, require_str, require_enum, require_fields, stamp_new,
    parse_pagination, sort_and_paginate, touch,
)
from lookups import get_or_404, fk_or_404
from middleware import require_roles
from response import success, list_success
from serializers import public, public_list
from services.domain import recompute_records_complete

bp = Blueprint("growth_records", __name__)


@bp.post("/growth-records")
@require_roles("Orthodontist", "ClinicAdmin")
def create_growth_record():
    body = get_json_body()
    patient_id = require_str(body, "patient_id")
    record_type = require_enum(body, "record_type", {"PANO", "CEPH"})
    require_fields(body, ["taken_at"])
    taken_at = body["taken_at"]
    if not isinstance(taken_at, str) or taken_at == "":
        raise errors.invalid_request("taken_at must be a non-empty string")
    with lock:
        fk_or_404(db.patients, patient_id)
        rec = {
            "patient_id": patient_id,
            "record_type": record_type,
            "taken_at": taken_at,
            "status": "DRAFT",
        }
        stamp_new(rec)
        db.growth_records[rec["id"]] = rec
        return success(public(rec), 201)


@bp.get("/growth-records/<record_id>")
@require_roles("Orthodontist", "ClinicAdmin", "FrontDesk")
def get_growth_record(record_id):
    with lock:
        rec = get_or_404(db.growth_records, record_id)
        return success(public(rec), 200)


@bp.get("/growth-records")
@require_roles("Orthodontist", "ClinicAdmin", "FrontDesk")
def list_growth_records():
    with lock:
        limit, offset = parse_pagination()
        patient_id = request.args.get("patient_id")
        records = list(db.growth_records.values())
        if patient_id is not None:
            records = [r for r in records if r["patient_id"] == patient_id]
        page, total = sort_and_paginate(records, limit, offset)
        return list_success(public_list(page), limit, offset, total, 200)


@bp.post("/growth-records/<record_id>/finalize")
@require_roles("Orthodontist")
def finalize_growth_record(record_id):
    with lock:
        rec = get_or_404(db.growth_records, record_id)
        if rec["status"] != "DRAFT":
            raise errors.invalid_state()
        # Supersede any prior FINALIZED record of the same type for this patient.
        for other in db.growth_records.values():
            if (other["id"] != rec["id"]
                    and other["patient_id"] == rec["patient_id"]
                    and other["record_type"] == rec["record_type"]
                    and other["status"] == "FINALIZED"):
                other["status"] = "SUPERSEDED"
                touch(other)
        rec["status"] = "FINALIZED"
        touch(rec)
        recompute_records_complete(rec["patient_id"])
        return success(public(rec), 200)
