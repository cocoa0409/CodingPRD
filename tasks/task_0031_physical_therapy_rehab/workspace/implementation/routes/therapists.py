"""Therapist routes (scaffold §1.5 — Therapists block; PRD §3.1)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_INVALID_REQUEST
from middleware import get_json_body, require_auth
from response import ok_array, ok_object, paginate_params, slice_page
from services.validation import (
    require_bool,
    require_fields,
    require_npi,
    require_state,
    require_string,
    lookup_or_404,
)


bp = Blueprint("therapists", __name__)


@bp.post("/rehab/therapists")
def create_therapist():
    require_auth(["PlatformAdmin"])()
    body = get_json_body()
    require_fields(body, ["full_name", "npi_number", "license_state"])
    full_name = require_string(body["full_name"], "full_name", max_len=120)
    npi_number = require_npi(body["npi_number"], "npi_number")
    license_state = require_state(body["license_state"], "license_state")
    enrolled = body.get("medicare_provider_enrolled", False)
    if enrolled is None:
        enrolled = False
    enrolled = require_bool(enrolled, "medicare_provider_enrolled")

    # npi_number must be unique across the Therapist table.
    for existing in db.therapists.values():
        if existing["npi_number"] == npi_number:
            raise APIError(
                ERR_INVALID_REQUEST, 400, "npi_number must be unique across therapists"
            )

    with db.mutation_lock:
        therapist = {
            "full_name": full_name,
            "npi_number": npi_number,
            "license_state": license_state,
            "medicare_provider_enrolled": enrolled,
        }
        db.stamp_common(therapist)
        db.therapists[therapist["id"]] = therapist
        return ok_object(therapist, 201)


@bp.get("/rehab/therapists/<tid>")
def get_therapist(tid: str):
    require_auth(["PlatformAdmin", "CaseManager", "Therapist", "BillingClerk"])()
    therapist = lookup_or_404(db.therapists, tid, "Therapist")
    return ok_object(therapist, 200)


@bp.get("/rehab/therapists")
def list_therapists():
    require_auth(["PlatformAdmin", "CaseManager"])()
    limit, offset = paginate_params(request.args)
    items = list(db.therapists.values())
    if "medicare_provider_enrolled" in request.args:
        flag = request.args.get("medicare_provider_enrolled") == "true"
        items = [t for t in items if t["medicare_provider_enrolled"] == flag]
    if "license_state" in request.args:
        items = [t for t in items if t["license_state"] == request.args.get("license_state")]
    items.sort(key=db.created_then_id)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)
