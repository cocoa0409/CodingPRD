"""Inspection scheduling and reporting (with the rework loop)."""

from db import store, now
from errors import ApiError
from helpers import (
    get_body, check_allowed_fields, req_string, req_enum, opt_string, req_datetime,
    get_inspection_or_404, get_holdback_or_404, work_order_of,
    new_entity, touch, refresh_holdback_derived, ser_inspection,
)
from middleware import authenticate, authorize
from response import success

from . import bp

PURPOSES = {"DRAW_VERIFICATION", "FINAL_VERIFICATION", "REINSPECTION"}
RESULTS = {"PASSED", "FAILED"}
FINAL_PURPOSES = {"FINAL_VERIFICATION", "REINSPECTION"}


@bp.post("/escrow/inspections")
def create_inspection():
    _uid, role = authenticate()
    authorize(role, ["EscrowOfficer"])
    data = get_body()
    raw_hid = data.get("holdback_id")
    if isinstance(raw_hid, str) and raw_hid not in store.holdbacks:
        raise ApiError("ERR_NOT_FOUND", "Holdback not found: %s" % raw_hid)
    check_allowed_fields(
        data, {"holdback_id", "inspector_user_id", "purpose", "scheduled_start", "scheduled_end"}
    )
    hid = req_string(data, "holdback_id")
    hb = get_holdback_or_404(hid)
    inspector = req_string(data, "inspector_user_id")
    purpose = req_enum(data, "purpose", PURPOSES)
    start = req_datetime(data, "scheduled_start")
    end = req_datetime(data, "scheduled_end")
    if not (start < end):
        raise ApiError("ERR_VALIDATION", "scheduled_start must be strictly before scheduled_end")

    # Rung 7: a REINSPECTION presupposes a prior failed final.
    if purpose == "REINSPECTION":
        wo = work_order_of(hid)
        if wo is None or wo["failed_final_count"] < 1:
            raise ApiError("ERR_INVALID_STATE", "Reinspection requires a prior failed final")
    # Rung 8: scheduling requires an ACTIVE holdback.
    if hb["status"] != "ACTIVE":
        raise ApiError("ERR_HOLDBACK_NOT_ACTIVE", "Inspections require an ACTIVE holdback")

    # Rung 12, interval occupation, fixed order:
    # (a) inspector calendar, half-open [start, end), across all holdbacks.
    for i in store.inspections.values():
        if i["status"] == "PLANNED" and i["inspector_user_id"] == inspector:
            if start < i["scheduled_end"] and i["scheduled_start"] < end:
                raise ApiError(
                    "ERR_INSPECTOR_SCHEDULE_CONFLICT",
                    "Window overlaps a PLANNED inspection of this inspector",
                )
    # (b) property slot, closed [start, end], within this holdback; adjacency conflicts.
    for i in store.inspections.values():
        if i["status"] == "PLANNED" and i["holdback_id"] == hid:
            if start <= i["scheduled_end"] and i["scheduled_start"] <= end:
                raise ApiError(
                    "ERR_INSPECTION_SLOT_OCCUPIED",
                    "Window overlaps a PLANNED inspection on this holdback",
                )

    i = new_entity()
    i.update({
        "holdback_id": hid,
        "inspector_user_id": inspector,
        "purpose": purpose,
        "scheduled_start": start,
        "scheduled_end": end,
        "status": "PLANNED",
        "reported_at": None,
        "result_notes": None,
    })
    store.inspections[i["id"]] = i
    return success(ser_inspection(i), response_type="object", status=201)


@bp.post("/escrow/inspections/<iid>/report")
def report_inspection(iid):
    uid, role = authenticate()
    authorize(role, ["Inspector"])
    ins = get_inspection_or_404(iid)
    data = get_body()
    check_allowed_fields(data, {"result", "result_notes"})
    result = req_enum(data, "result", RESULTS)
    notes = opt_string(data, "result_notes")

    # Rung 5: reporting belongs to the assigned inspector.
    if uid != ins["inspector_user_id"]:
        raise ApiError("ERR_NOT_FILE_PARTY", "Only the assigned inspector may report")
    # Rung 8 (fixed internal order): inspection PLANNED, then work submitted.
    if ins["status"] != "PLANNED":
        raise ApiError("ERR_INSPECTION_NOT_PLANNED", "Inspection is not in PLANNED state")
    hb = get_holdback_or_404(ins["holdback_id"])
    wo = work_order_of(hb["id"])
    if ins["purpose"] in FINAL_PURPOSES:
        if wo is None or wo["status"] != "COMPLETION_SUBMITTED":
            raise ApiError(
                "ERR_WORK_NOT_SUBMITTED",
                "Final verification / reinspection requires COMPLETION_SUBMITTED work",
            )

    ins["status"] = "PASSED" if result == "PASSED" else "FAILED"
    ins["reported_at"] = now()
    ins["result_notes"] = notes
    touch(ins)

    if ins["purpose"] in FINAL_PURPOSES:
        if result == "PASSED":
            wo["status"] = "VERIFIED"
        else:
            wo["status"] = "IN_PROGRESS"
            wo["failed_final_count"] += 1
        touch(wo)
        if refresh_holdback_derived(hb):
            touch(hb)

    return success(ser_inspection(ins), response_type="object", status=200)
