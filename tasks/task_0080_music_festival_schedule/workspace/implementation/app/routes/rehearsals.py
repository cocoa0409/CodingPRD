"""Rehearsal endpoints per PRD §3.5."""
from __future__ import annotations

from typing import Any, Dict

from flask import Flask, request

from ._common import (
    ANY_ROLE,
    ApiError,
    DB,
    GLOBAL_LOCK,
    append_audit,
    assert_within_festival_window,
    check_if_match,
    check_rehearsal_room_overlap,
    check_stage_changeover_overlap,
    get_json_body,
    if_match_header,
    list_by_predicate,
    make_blueprint,
    optional_str,
    paginate_list,
    require_enum,
    require_int,
    require_role,
    require_str,
    require_window,
    resolve_festival,
    stamp_create,
    stamp_update,
    success_envelope,
)


bp = make_blueprint("rehearsals")


def _payload(r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": r["id"],
        "festival_id": r.get("festival_id"),
        "artist_id": r.get("artist_id"),
        "rehearsal_type": r.get("rehearsal_type"),
        "stage_id": r.get("stage_id"),
        "rehearsal_room_name": r.get("rehearsal_room_name"),
        "start_time": r.get("start_time"),
        "end_time": r.get("end_time"),
        "archive_uri": r.get("archive_uri"),
        "status": r.get("status"),
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
        "version": r.get("version"),
    }


def _resolve(festival_id: str, reh_id: str) -> Dict[str, Any]:
    resolve_festival(festival_id)
    r = DB.rehearsals.get(reh_id)
    if r is None:
        raise ApiError("ERR_REHEARSAL_NOT_FOUND", f"rehearsal {reh_id} not found")
    if r.get("festival_id") != festival_id:
        raise ApiError(
            "ERR_RESOURCE_MISMATCHED_PARENT",
            "rehearsal belongs to a different festival",
        )
    return r


@bp.route("/festivals/<festival_id>/rehearsals", methods=["POST"])
def create_rehearsal(festival_id: str):
    require_role(["StageManager"])
    body = get_json_body()
    with GLOBAL_LOCK:
        festival = resolve_festival(festival_id)
        artist_id = require_str(body, "artist_id")
        if artist_id not in DB.artists:
            raise ApiError("ERR_ARTIST_NOT_FOUND", f"artist {artist_id} not found")
        rtype = require_enum(body, "rehearsal_type", ("STAGE", "ROOM"))
        start, end = require_window(body, "start_time", "end_time")
        assert_within_festival_window(festival, start, end)

        stage_id = None
        room_name = None
        if rtype == "STAGE":
            stage_id = require_str(body, "stage_id")
            stage = DB.stages.get(stage_id)
            if stage is None:
                raise ApiError("ERR_STAGE_NOT_FOUND", f"stage {stage_id} not found")
            if stage.get("festival_id") != festival_id:
                raise ApiError(
                    "ERR_RESOURCE_MISMATCHED_PARENT",
                    "stage belongs to a different festival",
                )
            # The STAGE-rehearsal goes through the stage-changeover overlap
            # rule per PRD §3.5 priority-10.
            buf = stage.get("changeover_buffer_seconds")
            check_stage_changeover_overlap(festival_id, stage_id, start, end, buf)
        else:
            room_name = require_str(body, "rehearsal_room_name")
            check_rehearsal_room_overlap(festival_id, room_name, start, end)

        row = {
            "festival_id": festival_id,
            "artist_id": artist_id,
            "rehearsal_type": rtype,
            "stage_id": stage_id,
            "rehearsal_room_name": room_name,
            "start_time": start,
            "end_time": end,
            "archive_uri": None,
            "status": "BOOKED",
        }
        stamp_create(row)
        DB.rehearsals[row["id"]] = row
        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="Rehearsal",
            subject_entity_id=row["id"],
            to_state="BOOKED",
            payload_summary=f"rehearsal booked ({rtype}) on artist {artist_id}",
        )
        out = _payload(row)
    return success_envelope(out, http_status=201)


@bp.route("/festivals/<festival_id>/rehearsals", methods=["GET"])
def list_rehearsals(festival_id: str):
    require_role(ANY_ROLE)
    status_f = request.args.get("status")
    artist_f = request.args.get("artist_id")
    type_f = request.args.get("rehearsal_type")
    with GLOBAL_LOCK:
        resolve_festival(festival_id)

        def _pred(r: dict) -> bool:
            if r.get("festival_id") != festival_id:
                return False
            if status_f is not None and r.get("status") != status_f:
                return False
            if artist_f is not None and r.get("artist_id") != artist_f:
                return False
            if type_f is not None and r.get("rehearsal_type") != type_f:
                return False
            return True

        rows = list_by_predicate(DB.rehearsals, _pred)
        page, meta = paginate_list(rows, request.args)
        out = [_payload(r) for r in page]
    return success_envelope(out, pagination=meta)


@bp.route("/festivals/<festival_id>/rehearsals/<reh_id>", methods=["GET"])
def read_rehearsal(festival_id: str, reh_id: str):
    require_role(ANY_ROLE)
    with GLOBAL_LOCK:
        r = _resolve(festival_id, reh_id)
        out = _payload(r)
    return success_envelope(out)


@bp.route("/festivals/<festival_id>/rehearsals/<reh_id>/cancel", methods=["POST"])
def cancel_rehearsal(festival_id: str, reh_id: str):
    require_role(["StageManager"])
    body = get_json_body()
    reason = optional_str(body, "reason", default="") or ""
    with GLOBAL_LOCK:
        r = _resolve(festival_id, reh_id)
        check_if_match(r, if_match_header())
        if r.get("status") != "BOOKED":
            raise ApiError(
                "ERR_REHEARSAL_NOT_BOOKED",
                f"rehearsal is in {r.get('status')!r}, only BOOKED rehearsals may be cancelled",
            )
        prior = r["status"]
        r["status"] = "CANCELLED"
        stamp_update(r)
        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="Rehearsal",
            subject_entity_id=reh_id,
            from_state=prior,
            to_state="CANCELLED",
            payload_summary=f"rehearsal cancelled, reason: {reason!r}",
        )
        out = _payload(r)
    return success_envelope(out)


def register(app: Flask) -> None:
    app.register_blueprint(bp)
