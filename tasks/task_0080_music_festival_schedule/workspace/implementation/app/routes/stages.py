"""Stage CRUD per PRD §3.2."""
from __future__ import annotations

from typing import Any, Dict, List

from flask import Flask, request

from ._common import (
    ANY_ROLE,
    ApiError,
    DB,
    GLOBAL_LOCK,
    append_audit,
    check_if_match,
    get_json_body,
    if_match_header,
    list_by_predicate,
    make_blueprint,
    optional_int,
    optional_list,
    optional_str,
    paginate_list,
    require_int,
    require_role,
    require_str,
    resolve_festival,
    stamp_create,
    stamp_update,
    success_envelope,
)
from ..validators import optional_bool


bp = make_blueprint("stages")


def _payload(s: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": s["id"],
        "festival_id": s.get("festival_id"),
        "stage_name": s.get("stage_name"),
        "zone_capacity": s.get("zone_capacity"),
        "changeover_buffer_seconds": s.get("changeover_buffer_seconds"),
        "equipment_kits": list(s.get("equipment_kits", []) or []),
        "is_emergency_substitute": bool(s.get("is_emergency_substitute", False)),
        "status": s.get("status", "ACTIVE"),
        "created_at": s.get("created_at"),
        "updated_at": s.get("updated_at"),
        "version": s.get("version"),
    }


def _resolve(festival_id: str, stage_id: str) -> Dict[str, Any]:
    resolve_festival(festival_id)
    s = DB.stages.get(stage_id)
    if s is None:
        raise ApiError("ERR_STAGE_NOT_FOUND", f"stage {stage_id} not found")
    if s.get("festival_id") != festival_id:
        raise ApiError(
            "ERR_RESOURCE_MISMATCHED_PARENT", "stage belongs to a different festival"
        )
    return s


@bp.route("/festivals/<festival_id>/stages", methods=["POST"])
def create_stage(festival_id: str):
    require_role(["FestivalProducer", "StageManager"])
    body = get_json_body()
    with GLOBAL_LOCK:
        resolve_festival(festival_id)
        name = require_str(body, "stage_name")
        capacity = require_int(body, "zone_capacity", non_negative=True)
        from ..constants import STAGE_CHANGEOVER_BUFFER_SECONDS

        changeover = optional_int(
            body, "changeover_buffer_seconds", default=STAGE_CHANGEOVER_BUFFER_SECONDS,
            non_negative=True,
        )
        kits = optional_list(body, "equipment_kits", default=[], element_type=str)
        is_sub = optional_bool(body, "is_emergency_substitute", default=False)

        row = {
            "festival_id": festival_id,
            "stage_name": name,
            "zone_capacity": capacity,
            "changeover_buffer_seconds": changeover,
            "equipment_kits": list(kits),
            "is_emergency_substitute": is_sub,
            "status": "ACTIVE",
        }
        stamp_create(row)
        DB.stages[row["id"]] = row
        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="Stage",
            subject_entity_id=row["id"],
            from_state=None,
            to_state="ACTIVE",
            payload_summary=f"stage {name!r} created with capacity {capacity}",
        )
        out = _payload(row)
    return success_envelope(out, http_status=201)


@bp.route("/festivals/<festival_id>/stages", methods=["GET"])
def list_stages(festival_id: str):
    require_role(ANY_ROLE)
    with GLOBAL_LOCK:
        resolve_festival(festival_id)
        rows = list_by_predicate(
            DB.stages, lambda r: r.get("festival_id") == festival_id
        )
        page, meta = paginate_list(rows, request.args)
        out = [_payload(r) for r in page]
    return success_envelope(out, pagination=meta)


@bp.route("/festivals/<festival_id>/stages/<stage_id>", methods=["GET"])
def read_stage(festival_id: str, stage_id: str):
    require_role(ANY_ROLE)
    with GLOBAL_LOCK:
        s = _resolve(festival_id, stage_id)
        out = _payload(s)
    return success_envelope(out)


@bp.route("/festivals/<festival_id>/stages/<stage_id>", methods=["PATCH"])
def patch_stage(festival_id: str, stage_id: str):
    require_role(["StageManager"])
    body = get_json_body()
    with GLOBAL_LOCK:
        s = _resolve(festival_id, stage_id)
        check_if_match(s, if_match_header())

        # The DECOMMISSIONED-precondition rule from §3.2: cannot move to
        # DECOMMISSIONED while any non-terminal program item is on the stage.
        new_status = body.get("status")
        if new_status is not None and new_status not in ("ACTIVE", "DECOMMISSIONED"):
            raise ApiError(
                "ERR_INVALID_FIELD_VALUE", "stage.status must be ACTIVE or DECOMMISSIONED"
            )
        if new_status == "DECOMMISSIONED":
            for pi in DB.program_items.values():
                if (
                    pi.get("festival_id") == festival_id
                    and pi.get("stage_id") == stage_id
                    and pi.get("status") in ("PROPOSED", "CONFIRMED", "ANNOUNCED", "ON_STAGE")
                ):
                    raise ApiError(
                        "ERR_FESTIVAL_NOT_SCHEDULING_OR_PUBLISHED",
                        "cannot decommission a stage with active program items",
                    )

        for field in (
            "zone_capacity",
            "changeover_buffer_seconds",
            "equipment_kits",
            "is_emergency_substitute",
            "stage_name",
        ):
            if field in body:
                value = body[field]
                if field == "equipment_kits":
                    if not isinstance(value, list) or not all(
                        isinstance(x, str) for x in value
                    ):
                        raise ApiError(
                            "ERR_INVALID_FIELD_VALUE",
                            "equipment_kits must be a list of strings",
                        )
                    s["equipment_kits"] = list(value)
                elif field == "is_emergency_substitute":
                    if not isinstance(value, bool):
                        raise ApiError(
                            "ERR_INVALID_FIELD_VALUE",
                            "is_emergency_substitute must be a boolean",
                        )
                    s["is_emergency_substitute"] = bool(value)
                elif field == "stage_name":
                    if not isinstance(value, str) or value == "":
                        raise ApiError(
                            "ERR_INVALID_FIELD_VALUE", "stage_name must be a non-empty string"
                        )
                    s["stage_name"] = value
                else:
                    # zone_capacity, changeover_buffer_seconds — non-negative ints.
                    if (
                        isinstance(value, bool)
                        or not isinstance(value, int)
                        or value < 0
                    ):
                        raise ApiError(
                            "ERR_INVALID_FIELD_VALUE",
                            f"{field} must be a non-negative integer",
                        )
                    s[field] = int(value)

        if new_status is not None and new_status != s.get("status"):
            prior = s.get("status")
            s["status"] = new_status
            append_audit(
                festival_id=festival_id,
                event_category="STATE_TRANSITION",
                subject_entity_type="Stage",
                subject_entity_id=stage_id,
                from_state=prior,
                to_state=new_status,
                payload_summary=f"stage status flipped {prior} → {new_status}",
            )

        stamp_update(s)
        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="Stage",
            subject_entity_id=stage_id,
            payload_summary="stage fields patched",
        )
        out = _payload(s)
    return success_envelope(out)


def register(app: Flask) -> None:
    app.register_blueprint(bp)
