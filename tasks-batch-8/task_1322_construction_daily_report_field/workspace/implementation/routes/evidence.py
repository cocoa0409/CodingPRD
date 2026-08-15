"""MediaAttachment and MaterialDelivery routes."""
import json
from datetime import timedelta
from decimal import Decimal
from flask import Blueprint, request

from auth import ctx, need
from calc import bump_report, touch
from db import store
from envelope import success
from errors import ApiError, bad
from route_helpers import stamp, list_response, day_window
from serializers import ser_media, ser_delivery
from routes.daily_reports import get_report, require_editable
from routes.setup_resources import get_work_area, get_zone
from validate import (
    body,
    req_str,
    opt_str,
    opt_num,
    req_num,
    req_enum,
    req_dt,
)

bp = Blueprint("evidence", __name__)

MEDIA_TYPES = ("PHOTO", "VIDEO")
MEDIA_STATUSES = ("ACTIVE", "PURGED")
DELIVERY_STATUSES = ("DELIVERED", "PARTIAL", "INSPECTED")
UNITS = ("LF", "SF", "CY", "EA", "TON", "GAL")


def get_media(mid):
    m = store.media_attachments.get(mid)
    if m is None:
        raise ApiError("ERR_MEDIA_NOT_FOUND", 404, "MediaAttachment not found")
    return m


def get_delivery(did):
    d = store.material_deliveries.get(did)
    if d is None:
        raise ApiError("ERR_DELIVERY_NOT_FOUND", 404, "MaterialDelivery not found")
    return d


def _fingerprint(b):
    return json.dumps(b, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# media attachments
# ---------------------------------------------------------------------------

@bp.post("/media-attachments")
def create_media():
    uid, role = ctx()
    need(role, ["Superintendent", "SafetyOfficer"])
    b = body()
    report_id = req_str(b, "report_id")
    work_area_id = req_str(b, "work_area_id")
    media_type = req_enum(b, "media_type", MEDIA_TYPES)
    file_url = req_str(b, "file_url")
    captured_at = req_dt(b, "captured_at")
    gps_lat = opt_num(b, "gps_lat")
    gps_lng = opt_num(b, "gps_lng")
    linked_incident_id = opt_str(b, "linked_incident_id")
    linked_delivery_id = opt_str(b, "linked_delivery_id")
    idempotency_key = opt_str(b, "idempotency_key")
    # priority 5: body FK existence
    report = get_report(report_id)
    area = get_work_area(work_area_id)
    incident = None
    if linked_incident_id is not None:
        incident = store.incidents.get(linked_incident_id)
        if incident is None:
            raise ApiError("ERR_INCIDENT_NOT_FOUND", 404, "Incident not found")
    delivery = None
    if linked_delivery_id is not None:
        delivery = store.material_deliveries.get(linked_delivery_id)
        if delivery is None:
            raise ApiError("ERR_DELIVERY_NOT_FOUND", 404, "MaterialDelivery not found")
    # priority 6.1: posture gate
    require_editable(report)
    # priority 8.4: link constraint + GPS pairing
    if linked_incident_id is not None and linked_delivery_id is not None:
        raise ApiError(
            "ERR_MEDIA_LINK_CONSTRAINT",
            422,
            "At most one of linked_incident_id / linked_delivery_id may be set",
        )
    lat_given = "gps_lat" in b and b["gps_lat"] is not None
    lng_given = "gps_lng" in b and b["gps_lng"] is not None
    if lat_given != lng_given:
        raise ApiError(
            "ERR_GPS_INCOMPLETE_PAIR",
            422,
            "gps_lat and gps_lng must be supplied together",
        )
    # priority 8.5: idempotency
    if idempotency_key is not None:
        prior = store.idempotency.get(("/media-attachments", uid, idempotency_key))
        if prior is not None:
            if prior["fingerprint"] != _fingerprint(b):
                raise ApiError(
                    "ERR_IDEMPOTENCY_CONFLICT",
                    409,
                    "idempotency_key reused with a different request body",
                )
            return success(
                ser_media(store.media_attachments[prior["entity_id"]]), 201
            )
    # priority 9.2: captured_at within report_date calendar day
    day_start, day_end = day_window(report["report_date"])
    if not (day_start <= captured_at < day_end):
        raise ApiError(
            "ERR_MEDIA_CAPTURED_OUTSIDE_REPORT_DATE",
            422,
            "captured_at outside report_date calendar day",
        )
    # priority 10: work area open
    if area["status"] != "OPEN":
        raise ApiError("ERR_WORK_AREA_CLOSED", 409, "WorkArea is CLOSED")
    # priority 10.2: linked targets belong to the same report
    if incident is not None and incident["report_id"] != report_id:
        raise ApiError(
            "ERR_MEDIA_REPORT_MISMATCH",
            422,
            "Linked incident belongs to a different report",
        )
    if delivery is not None and delivery["report_id"] != report_id:
        raise ApiError(
            "ERR_MEDIA_REPORT_MISMATCH",
            422,
            "Linked delivery belongs to a different report",
        )
    rec = stamp(
        {
            "report_id": report_id,
            "work_area_id": work_area_id,
            "media_type": media_type,
            "file_url": file_url,
            "captured_at": captured_at,
            "gps_lat": gps_lat,
            "gps_lng": gps_lng,
            "linked_incident_id": linked_incident_id,
            "linked_delivery_id": linked_delivery_id,
            "status": "ACTIVE",
        }
    )
    store.media_attachments[rec["id"]] = rec
    bump_report(report)
    if idempotency_key is not None:
        store.idempotency[("/media-attachments", uid, idempotency_key)] = {
            "fingerprint": _fingerprint(b),
            "entity_id": rec["id"],
        }
    return success(ser_media(rec), 201)


@bp.get("/media-attachments/<mid>")
def get_one_media(mid):
    ctx()
    return success(ser_media(get_media(mid)), 200)


@bp.get("/media-attachments")
def list_media():
    ctx()
    report_id = request.args.get("report_id")
    work_area_id = request.args.get("work_area_id")
    linked_incident_id = request.args.get("linked_incident_id")
    linked_delivery_id = request.args.get("linked_delivery_id")
    status = request.args.get("status")
    if status is not None and status not in MEDIA_STATUSES:
        bad("Invalid status filter")
    rows = list(store.media_attachments.values())
    if report_id is not None:
        rows = [r for r in rows if r["report_id"] == report_id]
    if work_area_id is not None:
        rows = [r for r in rows if r["work_area_id"] == work_area_id]
    if linked_incident_id is not None:
        rows = [r for r in rows if r["linked_incident_id"] == linked_incident_id]
    if linked_delivery_id is not None:
        rows = [r for r in rows if r["linked_delivery_id"] == linked_delivery_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(rows, ser_media)


@bp.post("/media-attachments/<mid>/purge")
def purge_media(mid):
    _, role = ctx()
    need(role, ["Superintendent", "SafetyOfficer"])
    m = get_media(mid)
    if m["status"] != "ACTIVE":
        raise ApiError(
            "ERR_MEDIA_INVALID_TRANSITION", 409, "MediaAttachment is not ACTIVE"
        )
    report = get_report(m["report_id"])
    require_editable(report)
    # priority 8.8: purge forbidden when linked to an incident
    if m["linked_incident_id"] is not None:
        raise ApiError(
            "ERR_MEDIA_LINKED_TO_INCIDENT",
            409,
            "Media linked to an incident may not be purged",
        )
    # clear references from OPEN/MITIGATED safety observations
    for o in store.safety_observations.values():
        if (
            o["media_attachment_id"] == m["id"]
            and o["status"] in ("OPEN", "MITIGATED")
        ):
            o["media_attachment_id"] = None
            touch(o)
    m["status"] = "PURGED"
    touch(m)
    bump_report(report)
    return success(ser_media(m), 200)


# ---------------------------------------------------------------------------
# material deliveries
# ---------------------------------------------------------------------------

@bp.post("/deliveries")
def create_delivery():
    _, role = ctx()
    need(role, ["Superintendent"])
    b = body()
    report_id = req_str(b, "report_id")
    delivery_zone_id = req_str(b, "delivery_zone_id")
    po_number = req_str(b, "po_number")
    material_description = req_str(b, "material_description")
    delivered_qty = req_num(b, "delivered_qty", gt=Decimal(0))
    unit = req_enum(b, "unit", UNITS)
    win_start = req_dt(b, "scheduled_window_start")
    win_end = req_dt(b, "scheduled_window_end")
    inspection_notes = opt_str(b, "inspection_notes")
    # priority 5: body FK existence
    report = get_report(report_id)
    zone = get_zone(delivery_zone_id)
    # priority 6.1: posture gate
    require_editable(report)
    # priority 9.4: window end strictly after start
    if win_end <= win_start:
        raise ApiError(
            "ERR_INVALID_WINDOW",
            422,
            "scheduled_window_end must be strictly after scheduled_window_start",
        )
    # priority 9.6: zone window collision (closed intervals + buffer on both sides)
    buffer = timedelta(minutes=zone["buffer_minutes"])
    for d in store.material_deliveries.values():
        if d["delivery_zone_id"] != delivery_zone_id:
            continue
        s2, e2 = d["scheduled_window_start"], d["scheduled_window_end"]
        # no collision iff the new window starts strictly after the other's end
        # plus buffer, or ends strictly before the other's start minus buffer.
        # A zero-length gap (touching) is a collision under closed-interval semantics.
        after = (win_start - e2) >= buffer and (win_start - e2).total_seconds() > 0
        before = (s2 - win_end) >= buffer and (s2 - win_end).total_seconds() > 0
        if not (after or before):
            raise ApiError(
                "ERR_DELIVERY_WINDOW_OVERLAP",
                409,
                "Scheduled window collides within zone buffer_minutes",
            )
    # priority 10.1: zone must be OPEN
    if zone["status"] != "OPEN":
        raise ApiError("ERR_DELIVERY_ZONE_CLOSED", 409, "DeliveryZone is CLOSED")
    rec = stamp(
        {
            "report_id": report_id,
            "delivery_zone_id": delivery_zone_id,
            "po_number": po_number,
            "material_description": material_description,
            "delivered_qty": delivered_qty,
            "unit": unit,
            "scheduled_window_start": win_start,
            "scheduled_window_end": win_end,
            "accepted_qty": Decimal(0),
            "rejected_qty": Decimal(0),
            "pending_recount_qty": delivered_qty,
            "inspection_notes": inspection_notes,
            "status": "DELIVERED",
        }
    )
    store.material_deliveries[rec["id"]] = rec
    bump_report(report)
    return success(ser_delivery(rec), 201)


@bp.get("/deliveries/<did>")
def get_one_delivery(did):
    ctx()
    return success(ser_delivery(get_delivery(did)), 200)


@bp.get("/deliveries")
def list_deliveries():
    ctx()
    report_id = request.args.get("report_id")
    delivery_zone_id = request.args.get("delivery_zone_id")
    status = request.args.get("status")
    if status is not None and status not in DELIVERY_STATUSES:
        bad("Invalid status filter")
    rows = list(store.material_deliveries.values())
    if report_id is not None:
        rows = [r for r in rows if r["report_id"] == report_id]
    if delivery_zone_id is not None:
        rows = [r for r in rows if r["delivery_zone_id"] == delivery_zone_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(rows, ser_delivery)


@bp.post("/deliveries/<did>/inspect")
def inspect_delivery(did):
    _, role = ctx()
    need(role, ["Superintendent"])
    d = get_delivery(did)
    b = body()
    accepted = req_num(b, "accepted_qty", mn=Decimal(0))
    rejected = req_num(b, "rejected_qty", mn=Decimal(0))
    inspection_notes = opt_str(b, "inspection_notes")
    # priority 6: state
    if d["status"] not in ("DELIVERED", "PARTIAL"):
        raise ApiError(
            "ERR_DELIVERY_INVALID_TRANSITION",
            409,
            "Delivery must be DELIVERED or PARTIAL to inspect",
        )
    report = get_report(d["report_id"])
    require_editable(report)
    # priority 8.7: quantity bounds
    if accepted + rejected > d["pending_recount_qty"]:
        raise ApiError(
            "ERR_INSPECTION_QTY_OVERFLOW",
            422,
            "inspection quantities exceed pending_recount_qty",
        )
    d["accepted_qty"] += accepted
    d["rejected_qty"] += rejected
    d["pending_recount_qty"] -= accepted + rejected
    if inspection_notes is not None:
        d["inspection_notes"] = inspection_notes
    d["status"] = (
        "INSPECTED" if d["pending_recount_qty"] == 0 else "PARTIAL"
    )
    touch(d)
    bump_report(report)
    return success(ser_delivery(d), 200)


@bp.post("/deliveries/<did>/resolve-recount")
def resolve_recount(did):
    _, role = ctx()
    need(role, ["Superintendent"])
    d = get_delivery(did)
    b = body()
    recount_accepted = req_num(b, "recount_accepted_qty", mn=Decimal(0))
    if d["status"] != "PARTIAL":
        raise ApiError(
            "ERR_DELIVERY_INVALID_TRANSITION",
            409,
            "Delivery must be PARTIAL to resolve a recount",
        )
    report = get_report(d["report_id"])
    require_editable(report)
    if recount_accepted > d["pending_recount_qty"]:
        raise ApiError(
            "ERR_INSPECTION_QTY_OVERFLOW",
            422,
            "recount_accepted_qty exceeds pending_recount_qty",
        )
    remainder = d["pending_recount_qty"]
    d["accepted_qty"] += recount_accepted
    d["rejected_qty"] += remainder - recount_accepted
    d["pending_recount_qty"] = Decimal(0)
    d["status"] = "INSPECTED"
    touch(d)
    bump_report(report)
    return success(ser_delivery(d), 200)
