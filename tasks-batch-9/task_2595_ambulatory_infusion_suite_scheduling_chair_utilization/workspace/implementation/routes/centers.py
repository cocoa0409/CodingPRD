"""Infusion centers, chairs and nurses (PRD 3.1)."""

from flask import Blueprint

import db
from db import must, new_row, rows, touch
from errors import ApiError
from middleware import authenticate
from response import created, ok
from routes.common import paged
from services import derive, present
from validators import (
    bad,
    body,
    opt_bool,
    opt_enum,
    opt_int,
    present as has,
    q_bool,
    q_enum,
    q_str,
    req_int,
    req_str,
)

bp = Blueprint("centers", __name__)

ALL_STAFF = ("Scheduler", "InfusionNurse", "Pharmacist", "AuthorizationSpecialist", "MedicalDirector")
CHAIR_TYPES = ("STANDARD", "BARIATRIC", "ISOLATION")
CHAIR_STATUSES = ("AVAILABLE", "OUT_OF_SERVICE")
NURSE_STATUSES = ("ACTIVE", "INACTIVE")


# ------------------------------------------------------------------ centers
@bp.post("/infusion-centers")
def create_center():
    authenticate("Scheduler")
    data = body()
    name = req_str(data, "name", 1, 120)
    open_minute = req_int(data, "open_minute", 0, 1440)
    close_minute = req_int(data, "close_minute", 0, 1440)
    if not (0 <= open_minute < close_minute <= 1440):
        bad("open_minute must be below close_minute and both inside the day.")
    turnover = opt_int(data, "turnover_buffer_minutes", 0, 60, 15)
    urgent_reserve = opt_int(data, "urgent_reserve_chair_count", 0, 10, 1)
    cutoff_supplied = has(data, "addon_cutoff_minute")
    cutoff = opt_int(data, "addon_cutoff_minute", 0, 1440, 900)
    if cutoff_supplied and not (open_minute <= cutoff <= close_minute):
        bad("addon_cutoff_minute must lie inside the operating window.")
    lab_validity = opt_int(data, "lab_validity_hours", 1, 168, 72)
    grid = opt_int(data, "stagger_grid_minutes", None, None, 15)
    if grid not in (5, 10, 15, 20, 30):
        bad("stagger_grid_minutes must be one of 5, 10, 15, 20 or 30.")
    slot = opt_int(data, "acuity_slot_minutes", None, None, 30)
    if slot not in (15, 30, 60):
        bad("acuity_slot_minutes must be one of 15, 30 or 60.")
    row = new_row(
        "centers",
        {
            "name": name,
            "open_minute": open_minute,
            "close_minute": close_minute,
            "turnover_buffer_minutes": turnover,
            "urgent_reserve_chair_count": urgent_reserve,
            "addon_cutoff_minute": cutoff,
            "lab_validity_hours": lab_validity,
            "stagger_grid_minutes": grid,
            "acuity_slot_minutes": slot,
            "available_chair_count": 0,
            "reserved_chair_count": 0,
        },
    )
    return created(present.plain(row))


@bp.get("/infusion-centers/<center_id>")
def read_center(center_id):
    authenticate(*ALL_STAFF)
    return ok(present.plain(must("centers", center_id)))


@bp.get("/infusion-centers")
def list_centers():
    authenticate(*ALL_STAFF)
    name = q_str("name")
    items = [c for c in rows("centers") if name is None or c["name"] == name]
    return paged("centers", items)


# ------------------------------------------------------------------ chairs
@bp.post("/chairs")
def create_chair():
    authenticate("Scheduler")
    data = body()
    center_id = req_str(data, "center_id", 1, None)
    label = req_str(data, "label", 1, 16)
    chair_type = opt_enum(data, "chair_type", CHAIR_TYPES, "STANDARD")
    status = opt_enum(data, "status", CHAIR_STATUSES, "AVAILABLE")
    reserved = opt_bool(data, "reserved_for_urgent", False)
    center = must("centers", center_id)
    for chair in rows("chairs"):
        if chair["center_id"] == center_id and chair["label"] == label:
            bad("A chair with this label already exists at the center.")
    if status == "OUT_OF_SERVICE" and reserved:
        raise ApiError("ERR_CHAIR_OUT_OF_SERVICE")
    row = new_row(
        "chairs",
        {
            "center_id": center_id,
            "label": label,
            "chair_type": chair_type,
            "status": status,
            "reserved_for_urgent": reserved,
            "committed_minutes": 0,
        },
    )
    derive.recompute_center(center["id"])
    return created(present.plain(row))


@bp.get("/chairs/<chair_id>")
def read_chair(chair_id):
    authenticate("Scheduler", "InfusionNurse", "Pharmacist", "MedicalDirector")
    return ok(present.plain(must("chairs", chair_id)))


@bp.get("/chairs")
def list_chairs():
    authenticate("Scheduler", "InfusionNurse", "Pharmacist", "MedicalDirector")
    center_id = q_str("center_id")
    status = q_enum("status", CHAIR_STATUSES)
    reserved = q_bool("reserved_for_urgent")
    items = []
    for chair in rows("chairs"):
        if center_id is not None and chair["center_id"] != center_id:
            continue
        if status is not None and chair["status"] != status:
            continue
        if reserved is not None and bool(chair["reserved_for_urgent"]) != reserved:
            continue
        items.append(chair)
    items.sort(key=lambda c: (c["label"], c["_seq"]))
    return paged("chairs", items)


@bp.patch("/chairs/<chair_id>")
def patch_chair(chair_id):
    authenticate("Scheduler")
    data = body()
    status = opt_enum(data, "status", CHAIR_STATUSES)
    reserved = opt_bool(data, "reserved_for_urgent")
    chair = must("chairs", chair_id)
    new_status = status if status is not None else chair["status"]
    new_reserved = reserved if reserved is not None else chair["reserved_for_urgent"]
    if new_status == "OUT_OF_SERVICE" and new_reserved:
        raise ApiError("ERR_CHAIR_OUT_OF_SERVICE")
    chair["status"] = new_status
    chair["reserved_for_urgent"] = new_reserved
    touch(chair)
    derive.recompute_center(chair["center_id"])
    if new_status == "OUT_OF_SERVICE":
        derive.bump_visits_of_chair(chair["id"])
    derive.recompute_chair(chair["id"])
    return ok(present.plain(chair))


# ------------------------------------------------------------------ nurses
@bp.post("/nurses")
def create_nurse():
    authenticate("Scheduler")
    data = body()
    center_id = req_str(data, "center_id", 1, None)
    full_name = req_str(data, "full_name", 1, 120)
    capacity = req_int(data, "acuity_capacity_points", 1, 20)
    shift_start = req_int(data, "shift_start_minute", 0, 1440)
    shift_end = req_int(data, "shift_end_minute", 0, 1440)
    status = opt_enum(data, "status", NURSE_STATUSES, "ACTIVE")
    if not (0 <= shift_start < shift_end <= 1440):
        bad("shift_start_minute must be below shift_end_minute and both inside the day.")
    must("centers", center_id)
    row = new_row(
        "nurses",
        {
            "center_id": center_id,
            "full_name": full_name,
            "acuity_capacity_points": capacity,
            "shift_start_minute": shift_start,
            "shift_end_minute": shift_end,
            "status": status,
            "assigned_acuity_points": 0,
        },
    )
    return created(present.plain(row))


@bp.get("/nurses/<nurse_id>")
def read_nurse(nurse_id):
    authenticate("Scheduler", "InfusionNurse", "MedicalDirector")
    return ok(present.plain(must("nurses", nurse_id)))


@bp.get("/nurses")
def list_nurses():
    authenticate("Scheduler", "InfusionNurse", "MedicalDirector")
    center_id = q_str("center_id")
    status = q_enum("status", NURSE_STATUSES)
    items = []
    for nurse in rows("nurses"):
        if center_id is not None and nurse["center_id"] != center_id:
            continue
        if status is not None and nurse["status"] != status:
            continue
        items.append(nurse)
    return paged("nurses", items)


@bp.patch("/nurses/<nurse_id>")
def patch_nurse(nurse_id):
    authenticate("Scheduler")
    data = body()
    capacity = opt_int(data, "acuity_capacity_points", 1, 20)
    shift_start = opt_int(data, "shift_start_minute", 0, 1440)
    shift_end = opt_int(data, "shift_end_minute", 0, 1440)
    status = opt_enum(data, "status", NURSE_STATUSES)
    nurse = must("nurses", nurse_id)
    new_start = shift_start if shift_start is not None else nurse["shift_start_minute"]
    new_end = shift_end if shift_end is not None else nurse["shift_end_minute"]
    if not (0 <= new_start < new_end <= 1440):
        bad("shift_start_minute must be below shift_end_minute.")
    nurse["acuity_capacity_points"] = capacity if capacity is not None else nurse["acuity_capacity_points"]
    nurse["shift_start_minute"] = new_start
    nurse["shift_end_minute"] = new_end
    nurse["status"] = status if status is not None else nurse["status"]
    touch(nurse)
    if nurse["status"] == "INACTIVE":
        derive.bump_visits_of_nurse(nurse["id"])
    derive.recompute_nurse(nurse["id"])
    return ok(present.plain(nurse))
