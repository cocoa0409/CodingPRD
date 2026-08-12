"""RunSlots: scheduling with all gates, start/complete/cancel (PRD SS3.4-SS3.5)."""
from flask import request

from db import STORE, clock_now
from errors import ApiError
from middleware import require_roles, ROLES
from response import success_object, success_list, paginate
from serializers import ser_run_slot
from services import (
    D, new_common, touch, stages_of_line, lot_outstanding, spec_of,
    predicted_film_build_um, theoretical_voc_kg, metered_voc_kg,
    covering_permit, post_emission, adjust_reserved, cap_would_exceed,
)
from validators import get_body, req, as_str, as_int, as_num, as_dt

from . import bp


def _get_or_404(table, rid):
    rec = STORE[table].get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found: %s" % rid)
    return rec


@bp.post("/ecoat/run-slots")
@require_roles("LineScheduler")
def create_run_slot():
    body = get_body()
    paint_line_id = as_str(req(body, "paint_line_id"), "paint_line_id")
    lot_id = as_str(req(body, "lot_id"), "lot_id")
    start_raw = req(body, "start_utc")
    end_raw = req(body, "end_utc")
    start = as_dt(start_raw, "start_utc")
    end = as_dt(end_raw, "end_utc")
    if end <= start:
        raise ApiError("ERR_INVALID_REQUEST", 400, "end_utc must be after start_utc")
    parts_per_hanger = as_int(req(body, "parts_per_hanger"), "parts_per_hanger")
    if parts_per_hanger < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "parts_per_hanger must be at least 1")
    expected_version = as_int(req(body, "expected_paint_line_version"),
                              "expected_paint_line_version")

    line = STORE["paint_lines"].get(paint_line_id)
    if line is None:
        raise ApiError("ERR_NOT_FOUND", 404, "paint_line_id does not exist")
    lot = STORE["lots"].get(lot_id)
    if lot is None:
        raise ApiError("ERR_NOT_FOUND", 404, "lot_id does not exist")

    # OCC (guard rung 5).
    if expected_version != line["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_paint_line_version does not match the PaintLine version")

    # State (rung 6).
    if lot["status"] != "QUEUED":
        raise ApiError("ERR_LOT_NOT_QUEUED", 409,
                       "Run-slot creation requires the lot in QUEUED status")

    # Chemical safety gate (rung 7): every stage of the line must be IN_RANGE.
    if any(s["status"] != "IN_RANGE" for s in stages_of_line(paint_line_id)):
        raise ApiError("ERR_STAGE_OUT_OF_RANGE", 409,
                       "A pretreatment stage of the line is OUT_OF_RANGE or ADJUSTING")

    # Interval conflicts (rung 8): half-open overlap on the same line.
    for s in STORE["run_slots"].values():
        if (s["paint_line_id"] == paint_line_id
                and s["status"] in ("SCHEDULED", "RUNNING")
                and s["_start"] < end and start < s["_end"]):
            raise ApiError("ERR_RUN_SLOT_OVERLAP", 409,
                           "Window collides with another SCHEDULED/RUNNING slot on the line")

    # Process constraints (rung 9): color, hanger density, film window.
    spec = spec_of(lot)
    if spec["color_code"] != line["current_color_code"]:
        raise ApiError("ERR_COLOR_MISMATCH", 409,
                       "Lot's spec color differs from the line's current_color_code")
    if parts_per_hanger > line["hanger_capacity_parts"]:
        raise ApiError("ERR_HANGER_DENSITY_EXCEEDED", 422,
                       "parts_per_hanger exceeds the line's hanger_capacity_parts")
    predicted = predicted_film_build_um(line["line_speed_fpm"], parts_per_hanger)
    if not (D(spec["film_build_min_um"]) <= predicted <= D(spec["film_build_max_um"])):
        raise ApiError("ERR_FILM_BUILD_OUT_OF_WINDOW", 422,
                       "predicted_film_build_um is outside the spec film window")

    # VOC fiscal checks (rung 10).
    permit = covering_permit()
    if permit is None:
        raise ApiError("ERR_NO_ACTIVE_PERMIT", 409,
                       "No non-CLOSED VOC permit covers the current logical clock")
    projected = theoretical_voc_kg(spec, lot_outstanding(lot))
    if cap_would_exceed(permit, projected):
        raise ApiError("ERR_VOC_CAP_EXCEEDED", 409,
                       "used_kg + reserved_kg + new emission would exceed cap_kg")

    slot = new_common()
    slot.update({
        "paint_line_id": paint_line_id, "lot_id": lot_id,
        "start_utc": start_raw, "end_utc": end_raw,
        "_start": start, "_end": end,
        "parts_per_hanger": parts_per_hanger,
        "planned_line_speed_fpm": line["line_speed_fpm"],
        "predicted_film_build_um": predicted,
        "voc_projected_kg": projected,
        "status": "SCHEDULED",
        "_permit_id": permit["id"],
        "_completed_at": None,
    })
    STORE["run_slots"][slot["id"]] = slot

    adjust_reserved(permit, projected)
    touch(line)  # scheduling commits the line: version += 1
    lot["status"] = "SCHEDULED"
    touch(lot)
    return success_object(ser_run_slot(slot), 201)


@bp.get("/ecoat/run-slots/<sid>")
@require_roles(*ROLES)
def get_run_slot(sid):
    return success_object(ser_run_slot(_get_or_404("run_slots", sid)))


@bp.get("/ecoat/run-slots")
@require_roles(*ROLES)
def list_run_slots():
    items = list(STORE["run_slots"].values())
    paint_line_id = request.args.get("paint_line_id")
    lot_id = request.args.get("lot_id")
    if paint_line_id is not None:
        items = [s for s in items if s["paint_line_id"] == paint_line_id]
    if lot_id is not None:
        items = [s for s in items if s["lot_id"] == lot_id]
    page, meta = paginate(items, ser_run_slot)
    return success_list(page, meta)


@bp.post("/ecoat/run-slots/<sid>/start")
@require_roles("LineScheduler")
def start_run_slot(sid):
    slot = _get_or_404("run_slots", sid)
    if slot["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Run-slot start requires status SCHEDULED")
    line = STORE["paint_lines"][slot["paint_line_id"]]
    if line["posture"] != "RUNNING":
        raise ApiError("ERR_LINE_ON_CHEM_HOLD", 409,
                       "Run-slot start rejected: line posture is CHEM_HOLD")
    slot["status"] = "RUNNING"
    touch(slot)
    lot = STORE["lots"][slot["lot_id"]]
    lot["status"] = "ON_LINE"
    touch(lot)
    return success_object(ser_run_slot(slot))


@bp.post("/ecoat/run-slots/<sid>/complete")
@require_roles("LineScheduler")
def complete_run_slot(sid):
    body = get_body()
    paint_used = as_num(req(body, "paint_used_liters"), "paint_used_liters")
    if paint_used < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "paint_used_liters must be >= 0")
    slot = _get_or_404("run_slots", sid)
    if slot["status"] != "RUNNING":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Run-slot completion requires status RUNNING")
    lot = STORE["lots"][slot["lot_id"]]
    spec = spec_of(lot)

    slot["status"] = "COMPLETED"
    slot["_completed_at"] = clock_now()
    touch(slot)
    lot["status"] = "CURING"
    touch(lot)

    # Metered VOC posting; reservation settled against the same permit.
    permit = STORE["voc_permits"].get(slot["_permit_id"])
    if permit is not None:
        adjust_reserved(permit, -slot["voc_projected_kg"])
        voc = metered_voc_kg(paint_used, spec["voc_g_per_l"])
        post_emission(permit, "PAINT_USAGE_METERED", voc, "METERED", lot_id=lot["id"])
    return success_object(ser_run_slot(slot))


@bp.post("/ecoat/run-slots/<sid>/cancel")
@require_roles("LineScheduler")
def cancel_run_slot(sid):
    slot = _get_or_404("run_slots", sid)
    if slot["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Run-slot cancel requires status SCHEDULED")
    slot["status"] = "CANCELLED"
    touch(slot)
    lot = STORE["lots"][slot["lot_id"]]
    lot["status"] = "QUEUED"
    touch(lot)
    # Compensating action: release the VOC reservation.
    permit = STORE["voc_permits"].get(slot["_permit_id"])
    if permit is not None:
        adjust_reserved(permit, -slot["voc_projected_kg"])
    return success_object(ser_run_slot(slot))
