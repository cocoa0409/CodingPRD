"""SoundEngineerTeam roster per PRD §3.2."""
from __future__ import annotations

from typing import Any, Dict

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
    paginate_list,
    require_role,
    require_str,
    resolve_festival,
    stamp_create,
    stamp_update,
    success_envelope,
)
from ..constants import TEAM_WARMUP_MINUTES


bp = make_blueprint("sound_engineer_teams")


def _payload(t: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": t["id"],
        "festival_id": t.get("festival_id"),
        "team_name": t.get("team_name"),
        "head_engineer_name": t.get("head_engineer_name"),
        "warmup_minutes": t.get("warmup_minutes", TEAM_WARMUP_MINUTES),
        "status": t.get("status", "AVAILABLE"),
        "current_booking_id": t.get("current_booking_id"),
        "created_at": t.get("created_at"),
        "updated_at": t.get("updated_at"),
        "version": t.get("version"),
    }


def _resolve(festival_id: str, team_id: str) -> Dict[str, Any]:
    resolve_festival(festival_id)
    t = DB.sound_engineer_teams.get(team_id)
    if t is None:
        raise ApiError(
            "ERR_SOUND_ENGINEER_TEAM_NOT_FOUND",
            f"sound engineer team {team_id} not found",
        )
    if t.get("festival_id") != festival_id:
        raise ApiError(
            "ERR_RESOURCE_MISMATCHED_PARENT",
            "team belongs to a different festival",
        )
    return t


@bp.route("/festivals/<festival_id>/sound-engineer-teams", methods=["POST"])
def create_team(festival_id: str):
    require_role(["StageManager"])
    body = get_json_body()
    with GLOBAL_LOCK:
        resolve_festival(festival_id)
        team_name = require_str(body, "team_name")
        head = require_str(body, "head_engineer_name")
        warmup = optional_int(
            body, "warmup_minutes", default=TEAM_WARMUP_MINUTES, non_negative=True
        )
        row = {
            "festival_id": festival_id,
            "team_name": team_name,
            "head_engineer_name": head,
            "warmup_minutes": warmup,
            "status": "AVAILABLE",
            "current_booking_id": None,
        }
        stamp_create(row)
        DB.sound_engineer_teams[row["id"]] = row
        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="SoundEngineerTeam",
            subject_entity_id=row["id"],
            to_state="AVAILABLE",
            payload_summary=f"sound-engineer team {team_name!r} registered",
        )
        out = _payload(row)
    return success_envelope(out, http_status=201)


@bp.route("/festivals/<festival_id>/sound-engineer-teams", methods=["GET"])
def list_teams(festival_id: str):
    require_role(ANY_ROLE)
    status_f = request.args.get("status")
    with GLOBAL_LOCK:
        resolve_festival(festival_id)

        def _pred(r: dict) -> bool:
            if r.get("festival_id") != festival_id:
                return False
            if status_f is not None and r.get("status") != status_f:
                return False
            return True

        rows = list_by_predicate(DB.sound_engineer_teams, _pred)
        page, meta = paginate_list(rows, request.args)
        out = [_payload(r) for r in page]
    return success_envelope(out, pagination=meta)


@bp.route(
    "/festivals/<festival_id>/sound-engineer-teams/<team_id>", methods=["GET"]
)
def read_team(festival_id: str, team_id: str):
    require_role(ANY_ROLE)
    with GLOBAL_LOCK:
        t = _resolve(festival_id, team_id)
        out = _payload(t)
    return success_envelope(out)


@bp.route(
    "/festivals/<festival_id>/sound-engineer-teams/<team_id>/withdraw",
    methods=["POST"],
)
def withdraw_team(festival_id: str, team_id: str):
    require_role(["StageManager"])
    with GLOBAL_LOCK:
        t = _resolve(festival_id, team_id)
        check_if_match(t, if_match_header())
        if t.get("status") == "WITHDRAWN":
            # already terminal — surface via the team-active-slot family,
            # which is the closest catalog match for a "team is in a
            # non-AVAILABLE-or-WITHDRAWN-eligible state" error.  But
            # withdrawing an already-WITHDRAWN team is a no-op return per
            # idempotent-state semantics; we return the row unchanged.
            return success_envelope(_payload(t))

        # Reject if the team currently anchors a SCHEDULED slot.
        if t.get("status") == "BUSY" and t.get("current_booking_id"):
            slot = DB.sound_check_slots.get(t["current_booking_id"])
            if slot is not None and slot.get("status") == "SCHEDULED":
                raise ApiError(
                    "ERR_TEAM_HAS_ACTIVE_SLOT",
                    f"team {team_id} is currently booked to slot "
                    f"{slot['id']}; cancel the slot before withdrawing",
                )

        prior = t.get("status")
        t["status"] = "WITHDRAWN"
        t["current_booking_id"] = None
        stamp_update(t)
        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="SoundEngineerTeam",
            subject_entity_id=team_id,
            from_state=prior,
            to_state="WITHDRAWN",
            payload_summary="team withdrawn",
        )
        out = _payload(t)
    return success_envelope(out)


def register(app: Flask) -> None:
    app.register_blueprint(bp)
