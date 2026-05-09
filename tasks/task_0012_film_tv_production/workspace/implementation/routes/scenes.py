"""Scene routes."""
import copy
from flask import Blueprint, g, request

import errors as E
from db import store, init_common, touch
from middleware import require_roles, parse_pagination
from response import ok_object, ok_array
from body import (
    get_json_body, require_string, require_enum, require_int, require_array,
    optional_bool,
)
from services.occ import check_version
from services.audit import log as audit_log
from services.serializers import serialize_scene, paginate
from services.conflicts import (
    check_actor_callsheet_conflict_within_production,
    check_actor_cross_project_conflict,
    actor_signed_role_ids_for_production,
)


bp = Blueprint("scenes", __name__)


SCENE_STATUSES = {"BREAKDOWN", "SCHEDULED", "RESCHEDULING", "SHOT", "OMITTED"}
INT_EXT = {"INT", "EXT", "INT_EXT"}
EQUIP_CATS = {"CAMERA", "LIGHTING", "SOUND", "GRIP", "WARDROBE", "PROPS", "MISC"}


def _get_production(pid):
    p = store.productions.get(pid)
    if not p:
        E.not_found(f"Production {pid} not found")
    return p


def _get_scene(pid, sid):
    s = store.scenes.get(sid)
    if not s or s["production_id"] != pid:
        E.not_found(f"Scene {sid} not found in production {pid}")
    return s


def _ensure_posture_ok(p):
    if p.get("posture") == "FROZEN":
        E.posture_blocked("Production posture is FROZEN")


@bp.route("/productions/<pid>/scenes", methods=["POST"])
@require_roles("LineProducer")
def create_scene(pid):
    body = get_json_body()
    p = _get_production(pid)
    _ensure_posture_ok(p)

    scene_number = require_string(body, "scene_number")
    int_ext = require_enum(body, "int_ext", INT_EXT)
    duration = require_int(body, "planned_duration_minutes", minv=1, maxv=720)
    role_ids = require_array(body, "required_actor_role_ids", item_check=lambda v: isinstance(v, str))
    eq_cats = require_array(body, "required_equipment_categories", item_check=lambda v: isinstance(v, str))
    for ec in eq_cats:
        if ec not in EQUIP_CATS:
            E.validation_err(f"Invalid equipment category: {ec}")
    weather_dep = optional_bool(body, "weather_dependent", default=False)

    # validate role_ids exist & belong to this production
    for rid in role_ids:
        r = store.roles.get(rid)
        if not r:
            E.reference_mismatch(f"Role {rid} not found")
        if r["production_id"] != pid:
            E.reference_mismatch(f"Role {rid} not in this production")

    with store.lock:
        # scene_number unique within production
        for s in store.scenes.values():
            if s["production_id"] == pid and s["scene_number"] == scene_number:
                E.validation_err("scene_number already used in this production")
        rec = {
            "production_id": pid,
            "scene_number": scene_number,
            "int_ext": int_ext,
            "planned_duration_minutes": duration,
            "required_actor_role_ids": list(role_ids),
            "required_equipment_categories": list(eq_cats),
            "weather_dependent": weather_dep,
            "status": "BREAKDOWN",
        }
        init_common(rec)
        store.scenes[rec["id"]] = rec
        return ok_object(serialize_scene(rec), http_status=201)


@bp.route("/productions/<pid>/scenes", methods=["GET"])
@require_roles(
    "ExecutiveProducer", "LineProducer", "FinanceController",
    "CastingDirector", "ProductionCoordinator",
)
def list_scenes(pid):
    _get_production(pid)
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    items = [s for s in store.scenes.values() if s["production_id"] == pid]
    if status_filter:
        if status_filter not in SCENE_STATUSES:
            E.validation_err("Invalid status filter")
        items = [s for s in items if s["status"] == status_filter]
    page, total, has_more = paginate(items, limit, offset)
    return ok_array([serialize_scene(s) for s in page], limit, offset, total, has_more)


@bp.route("/productions/<pid>/scenes/<sid>/schedule", methods=["POST"])
@require_roles("LineProducer")
def schedule_scene(pid, sid):
    body = get_json_body()
    with store.lock:
        p = _get_production(pid)
        s = _get_scene(pid, sid)
        check_version(s, body)
        if s["status"] != "BREAKDOWN":
            E.invalid_state("schedule requires BREAKDOWN")
        _ensure_posture_ok(p)

        reservation_id = body.get("reservation_id")
        if not isinstance(reservation_id, str) or not reservation_id:
            E.validation_err("reservation_id is required")
        res = store.location_reservations.get(reservation_id)
        if not res:
            E.reference_mismatch(f"Reservation {reservation_id} not found")
        if res["production_id"] != pid:
            E.reference_mismatch("Reservation does not belong to this production")
        if res["scene_id"] != sid:
            E.reference_mismatch("Reservation is not bound to this scene")
        if res["status"] not in {"HELD", "CONFIRMED"}:
            E.invalid_state("Reservation must be HELD or CONFIRMED")

        # Weather dependent precondition
        if s.get("weather_dependent") and res.get("weather_status") != "ACCEPTABLE":
            E.weather_blocked("Weather not acceptable for this reservation")

        # Same-production callsheet conflict (priority 14)
        if check_actor_callsheet_conflict_within_production(pid, s, res):
            E.actor_callsheet_conflict("Actor call sheet conflict detected")

        # Cross-production conflict (priority 15) — for each signed actor in this scene
        for rid in s.get("required_actor_role_ids") or []:
            role = store.roles.get(rid)
            if not role or role.get("casting_status") != "SIGNED":
                continue
            actor_id = role.get("signed_actor_id")
            if not actor_id:
                continue
            if check_actor_cross_project_conflict(
                actor_id, res, exclude_production_id=pid
            ):
                E.cross_project_conflict("Cross-production schedule conflict")

        before = copy.deepcopy(s)
        s["status"] = "SCHEDULED"
        touch(s)
        # Reservation HELD → CONFIRMED
        if res["status"] == "HELD":
            res["status"] = "CONFIRMED"
            touch(res)
        audit_log(
            production_id=pid, actor_user_id=g.user_id,
            action="SCHEDULE_CHANGE", subject_entity="Scene", subject_id=sid,
            before=before, after=copy.deepcopy(s),
        )
        return ok_object(serialize_scene(s))


@bp.route("/productions/<pid>/scenes/<sid>/mark-weather-blocked", methods=["POST"])
@require_roles("ProductionCoordinator")
def mark_weather_blocked(pid, sid):
    body = get_json_body()
    with store.lock:
        p = _get_production(pid)
        s = _get_scene(pid, sid)
        check_version(s, body)
        if s["status"] != "SCHEDULED":
            E.invalid_state("mark-weather-blocked requires SCHEDULED")
        _ensure_posture_ok(p)
        if not s.get("weather_dependent"):
            E.invalid_state("Scene is not weather_dependent")
        # Find linked reservation
        res = next(
            (r for r in store.location_reservations.values()
             if r["scene_id"] == sid and r["status"] == "CONFIRMED"),
            None,
        )
        if not res or res.get("weather_status") != "BLOCKED":
            E.invalid_state("Linked reservation weather_status must be BLOCKED")
        before = copy.deepcopy(s)
        s["status"] = "RESCHEDULING"
        touch(s)
        res["status"] = "RESCHEDULING"
        touch(res)
        audit_log(
            production_id=pid, actor_user_id=g.user_id,
            action="SCHEDULE_CHANGE", subject_entity="Scene", subject_id=sid,
            before=before, after=copy.deepcopy(s),
        )
        return ok_object(serialize_scene(s))


@bp.route("/productions/<pid>/scenes/<sid>/reschedule", methods=["POST"])
@require_roles("ProductionCoordinator")
def reschedule_scene(pid, sid):
    body = get_json_body()
    with store.lock:
        p = _get_production(pid)
        s = _get_scene(pid, sid)
        check_version(s, body)
        if s["status"] != "RESCHEDULING":
            E.invalid_state("reschedule requires RESCHEDULING")
        _ensure_posture_ok(p)

        new_res_id = body.get("new_reservation_id")
        if not isinstance(new_res_id, str) or not new_res_id:
            E.validation_err("new_reservation_id is required")
        new_res = store.location_reservations.get(new_res_id)
        if not new_res:
            E.reference_mismatch("New reservation not found")
        if new_res["production_id"] != pid:
            E.reference_mismatch("New reservation does not belong to this production")
        if new_res["scene_id"] != sid:
            E.reference_mismatch("New reservation is not bound to this scene")
        if new_res["status"] not in {"HELD", "CONFIRMED"}:
            E.invalid_state("New reservation must be HELD or CONFIRMED")
        if new_res.get("weather_status") != "ACCEPTABLE":
            E.weather_blocked("New reservation weather_status must be ACCEPTABLE")

        # Conflict checks against the new reservation
        if check_actor_callsheet_conflict_within_production(pid, s, new_res):
            E.actor_callsheet_conflict("Actor call sheet conflict detected on reschedule")
        for rid in s.get("required_actor_role_ids") or []:
            role = store.roles.get(rid)
            if not role or role.get("casting_status") != "SIGNED":
                continue
            actor_id = role.get("signed_actor_id")
            if not actor_id:
                continue
            if check_actor_cross_project_conflict(
                actor_id, new_res, exclude_production_id=pid
            ):
                E.cross_project_conflict("Cross-production schedule conflict on reschedule")

        before = copy.deepcopy(s)
        # Cascade: old reservation RESCHEDULING → RELEASED
        old_res = next(
            (r for r in store.location_reservations.values()
             if r["scene_id"] == sid and r["status"] == "RESCHEDULING" and r["id"] != new_res_id),
            None,
        )
        if old_res is not None:
            old_res["status"] = "RELEASED"
            touch(old_res)
        # New reservation: HELD → CONFIRMED
        if new_res["status"] == "HELD":
            new_res["status"] = "CONFIRMED"
            touch(new_res)
        s["status"] = "SCHEDULED"
        touch(s)
        audit_log(
            production_id=pid, actor_user_id=g.user_id,
            action="SCHEDULE_CHANGE", subject_entity="Scene", subject_id=sid,
            before=before, after=copy.deepcopy(s),
        )
        return ok_object(serialize_scene(s))


@bp.route("/productions/<pid>/scenes/<sid>/mark-shot", methods=["POST"])
@require_roles("ProductionCoordinator")
def mark_shot(pid, sid):
    body = get_json_body()
    with store.lock:
        p = _get_production(pid)
        s = _get_scene(pid, sid)
        check_version(s, body)
        if s["status"] != "SCHEDULED":
            E.invalid_state("mark-shot requires SCHEDULED")
        _ensure_posture_ok(p)
        if p["status"] != "IN_PRODUCTION":
            E.invalid_state("Production must be IN_PRODUCTION")
        # Linked reservation must be CONFIRMED
        res = next(
            (r for r in store.location_reservations.values()
             if r["scene_id"] == sid and r["status"] == "CONFIRMED"),
            None,
        )
        if not res:
            E.invalid_state("Linked reservation must be CONFIRMED")
        before = copy.deepcopy(s)
        s["status"] = "SHOT"
        touch(s)
        res["status"] = "FULFILLED"
        touch(res)
        audit_log(
            production_id=pid, actor_user_id=g.user_id,
            action="SCHEDULE_CHANGE", subject_entity="Scene", subject_id=sid,
            before=before, after=copy.deepcopy(s),
        )
        return ok_object(serialize_scene(s))


@bp.route("/productions/<pid>/scenes/<sid>/omit", methods=["POST"])
@require_roles("LineProducer")
def omit_scene(pid, sid):
    body = get_json_body()
    with store.lock:
        p = _get_production(pid)
        s = _get_scene(pid, sid)
        check_version(s, body)
        _ensure_posture_ok(p)
        if s["status"] not in {"BREAKDOWN", "SCHEDULED"}:
            E.invalid_state("omit requires BREAKDOWN or SCHEDULED")
        if s["status"] == "SCHEDULED" and p["status"] != "PLANNING":
            E.invalid_state("omit from SCHEDULED requires Production PLANNING")
        before = copy.deepcopy(s)
        # Cascade: linked reservation CONFIRMED → RELEASED
        if s["status"] == "SCHEDULED":
            res = next(
                (r for r in store.location_reservations.values()
                 if r["scene_id"] == sid and r["status"] == "CONFIRMED"),
                None,
            )
            if res is not None:
                res["status"] = "RELEASED"
                touch(res)
            audit_log(
                production_id=pid, actor_user_id=g.user_id,
                action="SCHEDULE_CHANGE", subject_entity="Scene", subject_id=sid,
                before=before, after=None,
            )
        s["status"] = "OMITTED"
        touch(s)
        return ok_object(serialize_scene(s))
