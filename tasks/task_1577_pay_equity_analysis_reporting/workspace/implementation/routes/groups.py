"""ComparatorGroup endpoints (PRD §3.2)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_STUDY_INVALID_STATE,
    ERR_DUPLICATE_GROUP_NAME,
    ERR_GROUP_INVALID_STATE,
    ERR_STUDY_NOT_MODELING,
    ERR_GROUP_BELOW_MIN_SIZE,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public
from services.core import new_record, touch
from validate import get_body, req_str, req_int, require_path_resource, require_fk

bp = Blueprint("groups", __name__)


@bp.post("/comparator-groups")
def create_group():
    authorized(["CompAnalyst"])
    body = get_body()
    study_id = body.get("study_id")
    if study_id is None or not isinstance(study_id, str) or study_id.strip() == "":
        raise_error(ERR_INVALID_REQUEST, "missing or invalid field: study_id")
    # Priority 3: body FK existence
    study = require_fk("pay_equity_studies", study_id, "study_id")
    # Priority 3.7: shape
    name = req_str(body, "name")
    job_family = req_str(body, "job_family")
    min_job_level = req_int(body, "min_job_level")
    max_job_level = req_int(body, "max_job_level")
    location_code = req_str(body, "location_code")
    if max_job_level < min_job_level:
        raise_error(ERR_INVALID_REQUEST,
                    "max_job_level must be >= min_job_level")
    # Priority 4: state — groups are created in a DRAFT or MODELING study
    if study["status"] not in ("DRAFT", "MODELING"):
        raise_error(ERR_STUDY_INVALID_STATE,
                    "group creation requires the study to be DRAFT or MODELING")
    # Priority 7: name unique within the study
    for g in db["comparator_groups"].values():
        if g["study_id"] == study_id and g["name"] == name:
            raise_error(ERR_DUPLICATE_GROUP_NAME,
                        f"group name already exists within the study: {name}")

    rec = new_record("comparator_groups", {
        "study_id": study_id,
        "name": name,
        "job_family": job_family,
        "min_job_level": min_job_level,
        "max_job_level": max_job_level,
        "location_code": location_code,
        "member_count": 0,
        "status": "DRAFT",
    })
    return success_object(public(rec), status=201)


@bp.get("/comparator-groups")
def list_groups():
    return list_response("comparator_groups", {
        "study_id": request.args.get("study_id"),
        "status": request.args.get("status"),
    })


@bp.get("/comparator-groups/<rid>")
def get_group(rid):
    return get_one("comparator_groups", rid)


@bp.post("/comparator-groups/<rid>/lock")
def lock_group(rid):
    authorized(["CompAnalyst"])
    group = require_path_resource("comparator_groups", rid)
    study = db["pay_equity_studies"].get(group["study_id"])
    # State preconditions in the pinned order (SCAFFOLD §1.2)
    if group["status"] != "DRAFT":
        raise_error(ERR_GROUP_INVALID_STATE, "lock requires group in DRAFT")
    if study is None or study["status"] != "MODELING":
        raise_error(ERR_STUDY_NOT_MODELING, "lock requires the parent study to be MODELING")
    # Priority 7: minimum size at lock (inclusive boundary)
    if group["member_count"] < study["min_group_size"]:
        raise_error(ERR_GROUP_BELOW_MIN_SIZE,
                    "group member_count is below the study's min_group_size")
    group["status"] = "LOCKED"
    touch(group)
    return success_object(public(group))
