"""Course and CourseVersion endpoints."""
from __future__ import annotations

from typing import Any

from flask import Flask, request

from ..auth import require_auth
from ..clock import now_iso_ms
from ..errors import ApiError
from ..occ import check_version
from ..pagination import parse_limit_offset
from ..store import bump_version, common_fields_append_only, common_fields_create, get_store, new_id, now_iso
from ..services.lookups import (
    get_certificate_template_by_course,
    get_course,
    ref_category,
    ref_course,
)
from ..services.serializers import serialize_course, serialize_course_version
from ..services.validation import COURSE_CODE_PATTERN, normalize_tag_list
from ._helpers import created, get_json_body, ok, ok_list, sort_by_created, with_lock


PREREQ_MAX_DEPTH = 5


def _has_prereq_cycle(course_id_or_none: str | None, prereq_ids: list[str]) -> bool:
    """Detect cycle reachable within 5 hops starting from prereq_ids,
    forbidding any path leading back to course_id_or_none."""
    if not prereq_ids:
        return False
    store = get_store()
    # BFS up to depth 5
    frontier = list(prereq_ids)
    depth = 0
    visited = set()
    while frontier and depth < PREREQ_MAX_DEPTH:
        next_frontier = []
        for pid in frontier:
            if pid == course_id_or_none:
                return True
            if pid in visited:
                continue
            visited.add(pid)
            row = store.courses.get(pid)
            if not row:
                continue
            for p in row.get("prerequisite_course_ids", []) or []:
                next_frontier.append(p)
        frontier = next_frontier
        depth += 1
    # also check final frontier hop
    for pid in frontier:
        if pid == course_id_or_none:
            return True
    return False


def _validate_course_payload(body: dict, *, is_create: bool, existing: dict | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if is_create:
        code = body.get("code")
        if not isinstance(code, str) or not COURSE_CODE_PATTERN.match(code):
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "Invalid course code format.", http_status=422)
        # uniqueness
        store = get_store()
        if code in store.course_code_uniq:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "Course code already exists.", http_status=422)
        out["code"] = code

    if "title" in body or is_create:
        title = body.get("title") if not is_create else body.get("title")
        if title is None and is_create:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "title is required.", http_status=422)
        if title is not None:
            if not isinstance(title, str) or not (1 <= len(title) <= 200):
                raise ApiError("ERR_REFERENCE_NOT_FOUND", "title 1..200.", http_status=422)
            out["title"] = title

    if is_create:
        cat_id = body.get("category_id")
        if not cat_id:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "category_id is required.", http_status=422)
        ref_category(cat_id)
        out["category_id"] = cat_id

    if is_create or "objective" in body:
        objective = body.get("objective")
        if is_create and not isinstance(objective, str):
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "objective is required.", http_status=422)
        if objective is not None:
            if not isinstance(objective, str):
                raise ApiError("ERR_REFERENCE_NOT_FOUND", "objective must be string.", http_status=422)
            out["objective"] = objective

    if is_create or "outline" in body:
        outline = body.get("outline")
        if is_create and not isinstance(outline, str):
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "outline is required.", http_status=422)
        if outline is not None:
            if not isinstance(outline, str):
                raise ApiError("ERR_REFERENCE_NOT_FOUND", "outline must be string.", http_status=422)
            out["outline"] = outline

    if is_create or "duration_hours" in body:
        dh = body.get("duration_hours")
        if dh is not None:
            try:
                dh_f = float(dh)
            except Exception:
                raise ApiError("ERR_REFERENCE_NOT_FOUND", "duration_hours must be number.", http_status=422)
            if not (0.5 <= dh_f <= 40.0):
                raise ApiError("ERR_REFERENCE_NOT_FOUND", "duration_hours out of range.", http_status=422)
            out["duration_hours"] = round(dh_f, 1)
        elif is_create:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "duration_hours required.", http_status=422)

    if is_create or "credit_value" in body:
        cv = body.get("credit_value")
        if cv is not None:
            try:
                cv_f = float(cv)
            except Exception:
                raise ApiError("ERR_REFERENCE_NOT_FOUND", "credit_value must be number.", http_status=422)
            if not (0 <= cv_f <= 20.0):
                raise ApiError("ERR_REFERENCE_NOT_FOUND", "credit_value out of range.", http_status=422)
            out["credit_value"] = round(cv_f, 1)
        elif is_create:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "credit_value required.", http_status=422)

    if "tags" in body:
        out["tags"] = normalize_tag_list(body.get("tags") or [])

    if "prerequisite_course_ids" in body or is_create:
        prereq = body.get("prerequisite_course_ids") or []
        if not isinstance(prereq, list):
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "prerequisite_course_ids must be list.", http_status=422)
        if len(prereq) > 5:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "Too many prerequisites (>5).", http_status=422)
        store = get_store()
        for pid in prereq:
            if pid not in store.courses:
                raise ApiError("ERR_REFERENCE_NOT_FOUND", f"Prerequisite {pid} not found.")
        out["prerequisite_course_ids"] = list(prereq)

    if "is_charged" in body:
        out["is_charged"] = bool(body["is_charged"])
    elif is_create:
        out["is_charged"] = bool(body.get("is_charged", False))

    return out


def register(app: Flask) -> None:
    @app.post("/training/courses")
    @require_auth("CourseDesigner", "TrainingAdmin")
    @with_lock
    def create_course():
        body = get_json_body()
        data = _validate_course_payload(body, is_create=True)

        store = get_store()
        # Cycle check
        if _has_prereq_cycle(None, data.get("prerequisite_course_ids", [])):
            raise ApiError("ERR_PREREQUISITE_CYCLE", "Prerequisite cycle detected.")

        base = common_fields_create()
        row: dict[str, Any] = {
            **base,
            "code": data["code"],
            "title": data.get("title", ""),
            "category_id": data["category_id"],
            "objective": data.get("objective", ""),
            "outline": data.get("outline", ""),
            "duration_hours": data.get("duration_hours", 0.5),
            "prerequisite_course_ids": data.get("prerequisite_course_ids", []),
            "tags": data.get("tags", []),
            "credit_value": data.get("credit_value", 0),
            "is_charged": data.get("is_charged", False),
            "status": "DRAFT",
            "current_version_no": 0,
        }
        store.courses[base["id"]] = row
        store.course_code_uniq[row["code"]] = row["id"]

        # increment category.course_count
        cat = store.course_categories.get(row["category_id"])
        if cat is not None:
            cat["course_count"] = int(cat.get("course_count", 0)) + 1
            bump_version(cat)

        return created(serialize_course(row))

    @app.get("/training/courses")
    @require_auth("TrainingAdmin", "CourseDesigner", "DepartmentManager", "Trainee")
    @with_lock
    def list_courses():
        limit, offset = parse_limit_offset()
        status = request.args.get("status")
        category_id = request.args.get("category_id")
        tag = request.args.get("tag")
        q = request.args.get("q")
        items = list(get_store().courses.values())
        if status:
            items = [c for c in items if c["status"] == status]
        if category_id:
            items = [c for c in items if c["category_id"] == category_id]
        if tag:
            items = [c for c in items if tag in (c.get("tags") or [])]
        if q:
            ql = q.lower()
            items = [c for c in items if ql in (c.get("title", "").lower() + " " + c.get("objective", "").lower() + " " + c.get("outline", "").lower())]
        items = sort_by_created(items)
        return ok_list([serialize_course(c) for c in items], limit, offset)

    @app.get("/training/courses/<cid>")
    @require_auth("TrainingAdmin", "CourseDesigner", "DepartmentManager", "Trainee")
    @with_lock
    def get_course_route(cid):
        row = get_course(cid)
        return ok(serialize_course(row))

    @app.patch("/training/courses/<cid>")
    @require_auth("CourseDesigner", "TrainingAdmin")
    @with_lock
    def patch_course(cid):
        row = get_course(cid)
        body = get_json_body()
        check_version(row, body)
        if row["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", "Course must be DRAFT to edit.")
        data = _validate_course_payload(body, is_create=False, existing=row)

        new_prereq = data.get("prerequisite_course_ids", row.get("prerequisite_course_ids", []))
        if _has_prereq_cycle(cid, new_prereq):
            raise ApiError("ERR_PREREQUISITE_CYCLE", "Prerequisite cycle detected.")

        # Apply changes
        for k, v in data.items():
            if k == "code":
                continue  # immutable
            row[k] = v

        bump_version(row)
        return ok(serialize_course(row))

    @app.post("/training/courses/<cid>/submit-for-review")
    @require_auth("CourseDesigner")
    @with_lock
    def submit_for_review(cid):
        row = get_course(cid)
        if row["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", "Course not in DRAFT.")
        if not (row.get("objective") and row.get("outline")):
            raise ApiError("ERR_INVALID_STATE", "objective and outline must be non-empty.")
        if not (float(row.get("credit_value") or 0) > 0):
            raise ApiError("ERR_INVALID_STATE", "credit_value must be > 0.")
        row["status"] = "PENDING_REVIEW"
        bump_version(row)
        return ok(serialize_course(row))

    @app.post("/training/courses/<cid>/reject")
    @require_auth("TrainingAdmin")
    @with_lock
    def reject_course(cid):
        row = get_course(cid)
        if row["status"] != "PENDING_REVIEW":
            raise ApiError("ERR_INVALID_STATE", "Course not in PENDING_REVIEW.")
        row["status"] = "DRAFT"
        bump_version(row)
        return ok(serialize_course(row))

    @app.post("/training/courses/<cid>/publish")
    @require_auth("TrainingAdmin")
    @with_lock
    def publish_course(cid):
        row = get_course(cid)
        store = get_store()
        if row["status"] not in ("PENDING_REVIEW", "OFF_SHELF"):
            raise ApiError("ERR_INVALID_STATE", "Course not in PENDING_REVIEW or OFF_SHELF.")

        # Charged courses require certificate template
        if row.get("is_charged"):
            tpl = get_certificate_template_by_course(cid)
            if tpl is None:
                raise ApiError("ERR_CERT_TEMPLATE_MISSING", "Charged course requires CertificateTemplate.")

        if row["status"] == "PENDING_REVIEW":
            # Create new CourseVersion
            existing_versions = [v for v in store.course_versions.values() if v["course_id"] == cid]
            max_v = max((v["version_no"] for v in existing_versions), default=0)
            new_version_no = max_v + 1

            # Supersede any prior PUBLISHED version
            for v in existing_versions:
                if v["status"] == "PUBLISHED":
                    v["status"] = "SUPERSEDED"

            snapshot = {
                "objective": row["objective"],
                "outline": row["outline"],
                "duration_hours": row["duration_hours"],
                "prerequisite_course_ids": list(row.get("prerequisite_course_ids", [])),
                "tags": list(row.get("tags", [])),
                "credit_value": row["credit_value"],
            }
            base = common_fields_append_only()
            ver_row: dict[str, Any] = {
                **base,
                "course_id": cid,
                "version_no": new_version_no,
                "snapshot": snapshot,
                "status": "PUBLISHED",
                "published_at": now_iso(),
            }
            store.course_versions[base["id"]] = ver_row
            row["current_version_no"] = new_version_no

        else:
            # OFF_SHELF -> ON_SHELF; requires a PUBLISHED version exists
            existing_versions = [v for v in store.course_versions.values() if v["course_id"] == cid]
            if not any(v["status"] == "PUBLISHED" for v in existing_versions):
                raise ApiError("ERR_INVALID_STATE", "No PUBLISHED version exists.")

        row["status"] = "ON_SHELF"
        bump_version(row)
        return ok(serialize_course(row))

    @app.post("/training/courses/<cid>/unpublish")
    @require_auth("TrainingAdmin")
    @with_lock
    def unpublish_course(cid):
        row = get_course(cid)
        if row["status"] != "ON_SHELF":
            raise ApiError("ERR_INVALID_STATE", "Course not ON_SHELF.")
        row["status"] = "OFF_SHELF"
        bump_version(row)
        return ok(serialize_course(row))

    @app.post("/training/courses/<cid>/archive")
    @require_auth("TrainingAdmin")
    @with_lock
    def archive_course(cid):
        row = get_course(cid)
        if row["status"] != "OFF_SHELF":
            raise ApiError("ERR_INVALID_STATE", "Course not OFF_SHELF.")
        store = get_store()
        # No session referencing this course in non-terminal state
        for s in store.sessions.values():
            if s["course_id"] == cid and s["status"] not in ("COMPLETED", "CANCELLED"):
                raise ApiError("ERR_INVALID_STATE", "Active sessions reference this course.")
        row["status"] = "ARCHIVED"
        bump_version(row)
        return ok(serialize_course(row))

    @app.get("/training/courses/<cid>/versions")
    @require_auth("TrainingAdmin", "CourseDesigner")
    @with_lock
    def list_course_versions(cid):
        get_course(cid)
        limit, offset = parse_limit_offset()
        items = [v for v in get_store().course_versions.values() if v["course_id"] == cid]
        items = sort_by_created(items)
        return ok_list([serialize_course_version(v) for v in items], limit, offset)
