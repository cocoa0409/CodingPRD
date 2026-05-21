"""/foia/responsive-records — record collection & disposition updates."""

from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..envelope import ok_object
from ..errors import (
    ApiError,
    ERR_FK_NOT_FOUND,
    ERR_INVALID_INPUT,
    ERR_INVALID_STATE,
    ERR_MISSING_THIRD_PARTY_NOTICE,
    ERR_NOT_FOUND,
    ERR_RECORDS_FORBIDDEN_ON_GLOMAR,
    ERR_VERSION_CONFLICT,
)
from ..serializers import serialize_responsive_record
from ..store import store
from ..util import (
    optional_str,
    require_bool,
    require_int,
    require_json_body,
    require_str,
)


responsive_records_bp = Blueprint("responsive_records", __name__)

DISPOSITIONS = ("PENDING_REVIEW", "RELEASED_FULL", "RELEASED_REDACTED", "WITHHELD_FULL")


@responsive_records_bp.post("/foia/responsive-records")
@require_auth({"Officer"})
def create_record():
    payload = require_json_body()
    request_id = require_str(payload, "request_id", max_len=200)
    title = require_str(payload, "title", max_len=200)
    page_count = require_int(payload, "page_count", minimum=1)
    contains_tp = require_bool(payload, "contains_third_party_info", default=False) or False
    third_party_id = optional_str(
        payload, "third_party_id", max_len=200, allow_empty=False, nullable=True
    )

    req = store.requests.get(request_id)
    if req is None:
        raise ApiError(ERR_FK_NOT_FOUND, 404, "Referenced request does not exist.")

    # Priority 14 (ERR_RECORDS_FORBIDDEN_ON_GLOMAR) fires when request is on a
    # Glomar path OR not in SEARCH.
    if req.get("glomar_invoked") or req["status"] != "SEARCH":
        raise ApiError(
            ERR_RECORDS_FORBIDDEN_ON_GLOMAR,
            422,
            "Responsive records require a request in SEARCH and non-Glomar.",
        )

    if contains_tp and not third_party_id:
        raise ApiError(
            ERR_MISSING_THIRD_PARTY_NOTICE,
            422,
            "third_party_id is required when contains_third_party_info is true.",
        )

    entity = {
        "request_id": request_id,
        "title": title,
        "page_count": page_count,
        "contains_third_party_info": contains_tp,
        "third_party_id": third_party_id,
        "disposition": "PENDING_REVIEW",
    }
    with store.lock:
        store.stamp_create(entity)
        store.responsive_records[entity["id"]] = entity
    return ok_object(serialize_responsive_record(entity), status=201)


@responsive_records_bp.get("/foia/responsive-records/<rid>")
@require_auth({"Officer", "AppealAuthority"})
def get_record(rid: str):
    rec = store.responsive_records.get(rid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Responsive record not found.")
    return ok_object(serialize_responsive_record(rec))


@responsive_records_bp.patch("/foia/responsive-records/<rid>/disposition")
@require_auth({"Officer"})
def update_disposition(rid: str):
    rec = store.responsive_records.get(rid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Responsive record not found.")
    payload = require_json_body()
    if "disposition" not in payload:
        raise ApiError(ERR_INVALID_INPUT, 400, "disposition is required.")
    new_disp = payload["disposition"]
    if new_disp not in DISPOSITIONS:
        raise ApiError(ERR_INVALID_INPUT, 400, "Invalid disposition value.")

    with store.lock:
        if "version" in payload:
            ver = payload.get("version")
            if not isinstance(ver, int) or isinstance(ver, bool):
                raise ApiError(ERR_INVALID_INPUT, 400, "version must be an integer.")
            if ver != rec["version"]:
                raise ApiError(ERR_VERSION_CONFLICT, 409, "Version conflict.")
        rec["disposition"] = new_disp
        store.bump(rec)
    return ok_object(serialize_responsive_record(rec))
