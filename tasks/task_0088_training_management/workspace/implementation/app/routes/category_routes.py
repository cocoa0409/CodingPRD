"""CourseCategory endpoints."""
from __future__ import annotations

from typing import Any

from flask import Flask, request

from ..auth import require_auth
from ..errors import ApiError
from ..occ import check_version
from ..pagination import parse_limit_offset
from ..store import bump_version, common_fields_create, get_store
from ..services.lookups import get_course_category, ref_category
from ..services.serializers import serialize_course_category
from ._helpers import created, get_json_body, ok, ok_list, sort_by_created, with_lock


MAX_DEPTH = 4


def _compute_depth(parent_id: str | None) -> int:
    if parent_id is None:
        return 0
    store = get_store()
    depth = 0
    cur = parent_id
    seen = set()
    while cur is not None:
        if cur in seen:
            raise ApiError("ERR_CATEGORY_CYCLE", "Category parent chain has a cycle.")
        seen.add(cur)
        row = store.course_categories.get(cur)
        if not row:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", f"Parent category {cur} not found.")
        depth += 1
        cur = row.get("parent_id")
    return depth


def _validate_no_cycle(category_id: str, new_parent_id: str | None) -> None:
    if new_parent_id is None:
        return
    if new_parent_id == category_id:
        raise ApiError("ERR_CATEGORY_CYCLE", "Cannot set parent to self.")
    store = get_store()
    cur = new_parent_id
    seen = set()
    while cur is not None:
        if cur == category_id:
            raise ApiError("ERR_CATEGORY_CYCLE", "Parent chain would form a cycle.")
        if cur in seen:
            raise ApiError("ERR_CATEGORY_CYCLE", "Parent chain has a cycle.")
        seen.add(cur)
        row = store.course_categories.get(cur)
        if not row:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", f"Parent category {cur} not found.")
        cur = row.get("parent_id")


def _check_sibling_unique_name(name: str, parent_id: str | None, exclude_id: str | None = None) -> None:
    store = get_store()
    for c in store.course_categories.values():
        if exclude_id and c["id"] == exclude_id:
            continue
        if c.get("parent_id") == parent_id and c.get("name") == name:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", f"Sibling category with name {name!r} already exists.", http_status=422)


def register(app: Flask) -> None:
    @app.post("/training/course-categories")
    @require_auth("TrainingAdmin")
    @with_lock
    def create_category():
        body = get_json_body()
        name = body.get("name")
        parent_id = body.get("parent_id")
        if not isinstance(name, str) or not (1 <= len(name) <= 80):
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "name must be 1..80 chars.", http_status=422)
        if parent_id is not None:
            ref_category(parent_id)
        depth = _compute_depth(parent_id)
        if depth > MAX_DEPTH:
            raise ApiError("ERR_CATEGORY_CYCLE", f"Depth {depth} exceeds max {MAX_DEPTH}.")
        _check_sibling_unique_name(name, parent_id)

        base = common_fields_create()
        row: dict[str, Any] = {
            **base,
            "name": name,
            "parent_id": parent_id,
            "depth": depth,
            "course_count": 0,
        }
        get_store().course_categories[base["id"]] = row
        return created(serialize_course_category(row))

    @app.get("/training/course-categories")
    @require_auth("TrainingAdmin", "CourseDesigner", "DepartmentManager", "Trainee")
    @with_lock
    def list_categories():
        limit, offset = parse_limit_offset()
        parent_id = request.args.get("parent_id")
        items = list(get_store().course_categories.values())
        if parent_id is not None:
            # parent_id="null" treated as filter for roots
            if parent_id == "null":
                items = [c for c in items if c.get("parent_id") is None]
            else:
                items = [c for c in items if c.get("parent_id") == parent_id]
        items = sort_by_created(items)
        return ok_list([serialize_course_category(c) for c in items], limit, offset)

    @app.patch("/training/course-categories/<cid>")
    @require_auth("TrainingAdmin")
    @with_lock
    def patch_category(cid):
        row = get_course_category(cid)
        body = get_json_body()
        check_version(row, body)

        new_name = body.get("name", row["name"]) if "name" in body else row["name"]
        if "name" in body:
            if not isinstance(new_name, str) or not (1 <= len(new_name) <= 80):
                raise ApiError("ERR_REFERENCE_NOT_FOUND", "name must be 1..80 chars.", http_status=422)

        if "parent_id" in body:
            new_parent_id = body["parent_id"]
            if new_parent_id is not None:
                ref_category(new_parent_id)
            _validate_no_cycle(cid, new_parent_id)
            new_depth = _compute_depth(new_parent_id)
            if new_depth > MAX_DEPTH:
                raise ApiError("ERR_CATEGORY_CYCLE", f"Depth {new_depth} exceeds max {MAX_DEPTH}.")
            row["parent_id"] = new_parent_id
            row["depth"] = new_depth
            # Also re-evaluate descendant depths
            _recompute_descendant_depths(cid)

        if "name" in body:
            _check_sibling_unique_name(new_name, row.get("parent_id"), exclude_id=cid)
            row["name"] = new_name

        bump_version(row)
        return ok(serialize_course_category(row))


def _recompute_descendant_depths(root_id: str) -> None:
    store = get_store()
    # Walk children of root_id BFS
    # First compute depth map
    children_by_parent: dict[str | None, list[str]] = {}
    for c in store.course_categories.values():
        children_by_parent.setdefault(c.get("parent_id"), []).append(c["id"])

    stack = list(children_by_parent.get(root_id, []))
    while stack:
        cur = stack.pop()
        row = store.course_categories.get(cur)
        if not row:
            continue
        parent = store.course_categories.get(row.get("parent_id"))
        if parent is None:
            row["depth"] = 0
        else:
            row["depth"] = int(parent.get("depth", 0)) + 1
        if row["depth"] > MAX_DEPTH:
            raise ApiError("ERR_CATEGORY_CYCLE", f"Descendant depth {row['depth']} exceeds max {MAX_DEPTH}.")
        bump_version(row)
        stack.extend(children_by_parent.get(cur, []))
