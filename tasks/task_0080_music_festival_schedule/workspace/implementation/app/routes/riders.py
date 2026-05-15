"""Rider-requirement append-only collection per PRD §3.3."""
from __future__ import annotations

from typing import Any, Dict

from flask import Flask, request

from ._common import (
    ANY_ROLE,
    ApiError,
    DB,
    GLOBAL_LOCK,
    append_audit,
    fresh_uuid,
    get_json_body,
    list_by_predicate,
    logical_now_iso,
    make_blueprint,
    optional_bool,
    paginate_list,
    require_enum,
    require_role,
    require_str,
    resolve_festival,
    server_now_iso8601,
    success_envelope,
)


bp = make_blueprint("riders")


_CATEGORIES = ("TECHNICAL", "HOSPITALITY", "SECURITY", "CATERING", "ACCESSIBILITY")


def _payload(r: Dict[str, Any]) -> Dict[str, Any]:
    # Per §2.4 the rider entity carries only `id` and `created_at` from
    # the common-field set.  We omit `updated_at` and `version`.
    return {
        "id": r["id"],
        "program_item_id": r.get("program_item_id"),
        "category": r.get("category"),
        "description": r.get("description"),
        "is_blocking": bool(r.get("is_blocking", False)),
        "fulfilled_at": r.get("fulfilled_at"),
        "created_at": r.get("created_at"),
    }


def _resolve_program_item(festival_id: str, item_id: str) -> Dict[str, Any]:
    resolve_festival(festival_id)
    pi = DB.program_items.get(item_id)
    if pi is None:
        raise ApiError("ERR_PROGRAM_ITEM_NOT_FOUND", f"program item {item_id} not found")
    if pi.get("festival_id") != festival_id:
        raise ApiError(
            "ERR_RESOURCE_MISMATCHED_PARENT",
            "program item belongs to a different festival",
        )
    return pi


def _resolve_rider(festival_id: str, item_id: str, rider_id: str) -> Dict[str, Any]:
    pi = _resolve_program_item(festival_id, item_id)
    r = DB.riders.get(rider_id)
    if r is None:
        raise ApiError("ERR_RIDER_NOT_FOUND", f"rider {rider_id} not found")
    if r.get("program_item_id") != item_id:
        raise ApiError(
            "ERR_RESOURCE_MISMATCHED_PARENT",
            "rider belongs to a different program item",
        )
    return r


@bp.route(
    "/festivals/<festival_id>/program-items/<item_id>/riders", methods=["POST"]
)
def append_rider(festival_id: str, item_id: str):
    require_role(["ArtistLiaison"])
    body = get_json_body()
    pi = _resolve_program_item(festival_id, item_id)
    category = require_enum(body, "category", _CATEGORIES)
    description = require_str(body, "description")
    is_blocking = optional_bool(body, "is_blocking", default=False)
    row = {
        "id": fresh_uuid(),
        "program_item_id": item_id,
        "category": category,
        "description": description,
        "is_blocking": is_blocking,
        "fulfilled_at": None,
        "created_at": server_now_iso8601(),
    }
    with GLOBAL_LOCK:
        DB.riders[row["id"]] = row
        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="RiderRequirement",
            subject_entity_id=row["id"],
            payload_summary=(
                f"rider appended on item {item_id}, category={category}, "
                f"is_blocking={is_blocking}"
            ),
        )
        # The slot-priority score depends on the rider count.
        from ..services import recompute_slot_priority

        recompute_slot_priority(pi)
        out = _payload(row)
    return success_envelope(out, http_status=201)


@bp.route(
    "/festivals/<festival_id>/program-items/<item_id>/riders", methods=["GET"]
)
def list_riders(festival_id: str, item_id: str):
    require_role(ANY_ROLE)
    pi = _resolve_program_item(festival_id, item_id)
    cat_f = request.args.get("category")
    is_blocking_f = request.args.get("is_blocking")
    if is_blocking_f is not None:
        if is_blocking_f.lower() not in ("true", "false"):
            raise ApiError(
                "ERR_INVALID_PAGINATION",
                "is_blocking query parameter must be 'true' or 'false'",
            )
    with GLOBAL_LOCK:

        def _pred(r: dict) -> bool:
            if r.get("program_item_id") != item_id:
                return False
            if cat_f is not None and r.get("category") != cat_f:
                return False
            if is_blocking_f is not None:
                want = is_blocking_f.lower() == "true"
                if bool(r.get("is_blocking", False)) != want:
                    return False
            return True

        rows = list_by_predicate(DB.riders, _pred)
        page, meta = paginate_list(rows, request.args)
        out = [_payload(r) for r in page]
    return success_envelope(out, pagination=meta)


@bp.route(
    "/festivals/<festival_id>/program-items/<item_id>/riders/<rider_id>",
    methods=["PATCH"],
)
def fulfil_rider(festival_id: str, item_id: str, rider_id: str):
    require_role(["ArtistLiaison"])
    body = get_json_body()
    # The marker is `fulfilled: true`.  Other shapes are no-ops or the
    # response is the unchanged row (PRD §3.3 wording).
    if "fulfilled" not in body:
        raise ApiError(
            "ERR_INVALID_FIELD_VALUE",
            "request body must carry `fulfilled` (true) to mark the rider fulfilled",
        )
    fulfilled = body["fulfilled"]
    if not isinstance(fulfilled, bool):
        raise ApiError(
            "ERR_INVALID_FIELD_VALUE", "`fulfilled` must be a boolean"
        )
    with GLOBAL_LOCK:
        festival = DB.festivals[festival_id]
        rider = _resolve_rider(festival_id, item_id, rider_id)
        if fulfilled and rider.get("fulfilled_at") is None:
            # First-time flip from null to the server clock.
            rider["fulfilled_at"] = logical_now_iso(festival)
            append_audit(
                festival_id=festival_id,
                event_category="STATE_TRANSITION",
                subject_entity_type="RiderRequirement",
                subject_entity_id=rider_id,
                payload_summary=f"rider {rider_id} marked fulfilled",
            )
        elif fulfilled and rider.get("fulfilled_at") is not None:
            # Idempotent — the second call returns the row unchanged with no
            # fresh audit entry, per the PRD §3.3 prose.
            pass
        # `fulfilled: false` on an already-fulfilled rider is the
        # un-fulfil case the PRD does not pin; we treat it as a no-op
        # since the rider entity does not surface an unflip in the
        # state-machine table.
        out = _payload(rider)
    return success_envelope(out)


def register(app: Flask) -> None:
    app.register_blueprint(bp)
