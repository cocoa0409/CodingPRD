"""Instructor and InstructorAvailability endpoints."""
from __future__ import annotations

from typing import Any

from flask import Flask, request

from ..auth import require_auth
from ..clock import parse_iso
from ..errors import ApiError
from ..occ import check_version
from ..pagination import parse_limit_offset
from ..store import bump_version, common_fields_append_only, common_fields_create, get_store
from ..services.lookups import get_instructor
from ..services.serializers import serialize_instructor, serialize_instructor_availability
from ._helpers import created, get_json_body, ok, ok_list, sort_by_created, with_lock


def _validate_instructor_payload(body: dict, *, is_create: bool, existing: dict | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if is_create:
        full_name = body.get("full_name")
        if not isinstance(full_name, str) or not full_name:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "full_name required.", http_status=422)
        out["full_name"] = full_name
        inst_type = body.get("instructor_type")
        if inst_type not in ("INTERNAL", "EXTERNAL"):
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "instructor_type must be INTERNAL or EXTERNAL.", http_status=422)
        out["instructor_type"] = inst_type
    else:
        if "full_name" in body:
            if not isinstance(body["full_name"], str) or not body["full_name"]:
                raise ApiError("ERR_REFERENCE_NOT_FOUND", "full_name invalid.", http_status=422)
            out["full_name"] = body["full_name"]

    if "expertise_tags" in body:
        et = body.get("expertise_tags") or []
        if not isinstance(et, list):
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "expertise_tags must be list.", http_status=422)
        out["expertise_tags"] = list(et)
    elif is_create:
        out["expertise_tags"] = list(body.get("expertise_tags") or [])

    if is_create:
        out["qualifications"] = list(body.get("qualifications") or [])

    eff_type = out.get("instructor_type") or (existing.get("instructor_type") if existing else None)

    if "hourly_rate" in body:
        try:
            hr = float(body["hourly_rate"] or 0)
        except Exception:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "hourly_rate must be number.", http_status=422)
        if hr < 0:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "hourly_rate must be >=0.", http_status=422)
        out["hourly_rate"] = round(hr, 2)
    elif is_create:
        out["hourly_rate"] = 0.0

    if "travel_cost" in body:
        try:
            tc = float(body["travel_cost"] or 0)
        except Exception:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "travel_cost must be number.", http_status=422)
        if tc < 0:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "travel_cost must be >=0.", http_status=422)
        out["travel_cost"] = round(tc, 2)
    elif is_create:
        out["travel_cost"] = 0.0

    # INTERNAL instructors must have hourly_rate=0 and travel_cost=0
    if eff_type == "INTERNAL":
        if out.get("hourly_rate", 0) != 0:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "INTERNAL instructor hourly_rate must be 0.", http_status=422)
        if out.get("travel_cost", 0) != 0:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "INTERNAL instructor travel_cost must be 0.", http_status=422)

    return out


def register(app: Flask) -> None:
    @app.post("/training/instructors")
    @require_auth("TrainingAdmin")
    @with_lock
    def create_instructor():
        body = get_json_body()
        data = _validate_instructor_payload(body, is_create=True)
        base = common_fields_create()
        row: dict[str, Any] = {
            **base,
            "full_name": data["full_name"],
            "instructor_type": data["instructor_type"],
            "expertise_tags": data["expertise_tags"],
            "qualifications": data["qualifications"],
            "hourly_rate": data["hourly_rate"],
            "travel_cost": data["travel_cost"],
            "avg_evaluation_score": None,
            "status": "ACTIVE",
            "blacklist_reason": None,
        }
        get_store().instructors[base["id"]] = row
        return created(serialize_instructor(row))

    @app.get("/training/instructors")
    @require_auth("TrainingAdmin", "CourseDesigner")
    @with_lock
    def list_instructors():
        limit, offset = parse_limit_offset()
        et = request.args.get("expertise_tag")
        status = request.args.get("status")
        items = list(get_store().instructors.values())
        if et:
            items = [i for i in items if et in (i.get("expertise_tags") or [])]
        if status:
            items = [i for i in items if i["status"] == status]
        items = sort_by_created(items)
        return ok_list([serialize_instructor(i) for i in items], limit, offset)

    @app.patch("/training/instructors/<iid>")
    @require_auth("TrainingAdmin")
    @with_lock
    def patch_instructor(iid):
        row = get_instructor(iid)
        body = get_json_body()
        check_version(row, body)
        data = _validate_instructor_payload(body, is_create=False, existing=row)
        for k, v in data.items():
            row[k] = v
        bump_version(row)
        return ok(serialize_instructor(row))

    @app.post("/training/instructors/<iid>/blacklist")
    @require_auth("TrainingAdmin")
    @with_lock
    def blacklist_instructor(iid):
        row = get_instructor(iid)
        if row["status"] == "RETIRED":
            raise ApiError("ERR_INVALID_STATE", "Cannot blacklist a retired instructor.")
        body = get_json_body()
        reason = body.get("blacklist_reason")
        if not isinstance(reason, str) or not reason:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "blacklist_reason required.", http_status=422)
        if row["status"] == "BLACKLISTED":
            raise ApiError("ERR_INVALID_STATE", "Already BLACKLISTED.")
        row["status"] = "BLACKLISTED"
        row["blacklist_reason"] = reason
        bump_version(row)
        return ok(serialize_instructor(row))

    @app.post("/training/instructors/<iid>/reinstate")
    @require_auth("TrainingAdmin")
    @with_lock
    def reinstate_instructor(iid):
        row = get_instructor(iid)
        if row["status"] != "BLACKLISTED":
            raise ApiError("ERR_INVALID_STATE", "Not BLACKLISTED.")
        row["status"] = "ACTIVE"
        row["blacklist_reason"] = None
        bump_version(row)
        return ok(serialize_instructor(row))

    @app.post("/training/instructors/<iid>/availabilities")
    @require_auth("TrainingAdmin")
    @with_lock
    def create_availability(iid):
        get_instructor(iid)
        body = get_json_body()
        try:
            sa = parse_iso(body.get("start_at"))
            ea = parse_iso(body.get("end_at"))
        except ValueError as exc:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", f"Invalid timestamp: {exc}", http_status=422)
        if ea <= sa:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "end_at must be after start_at.", http_status=422)
        kind = body.get("kind")
        if kind not in ("AVAILABLE", "BLOCKED"):
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "kind must be AVAILABLE or BLOCKED.", http_status=422)

        from ..clock import format_iso
        base = common_fields_append_only()
        row = {
            **base,
            "instructor_id": iid,
            "start_at": format_iso(sa),
            "end_at": format_iso(ea),
            "kind": kind,
        }
        get_store().instructor_availabilities[base["id"]] = row
        return created(serialize_instructor_availability(row))
