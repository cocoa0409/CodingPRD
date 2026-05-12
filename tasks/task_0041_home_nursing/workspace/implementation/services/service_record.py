"""ServiceRecord on-site check-in and progression."""
import db
from clock import now, parse_iso, iso
from errors import err
from services.audit import audit
from services.constants import MAX_CHECKIN_RADIUS_KM
from services.util import (
    require_str, require_num, require_bool, check_occ, haversine_km,
)


VITAL_TYPES = {"BP", "HR", "TEMP", "SPO2", "GLU"}
SEVERITIES = {"LOW", "MEDIUM", "HIGH"}


def _record_for_order(order_id: str):
    for sr in db.service_records.values():
        if sr.get("order_id") == order_id:
            return sr
    return None


def _validate_checklist(items):
    if items is None:
        return []
    if not isinstance(items, list):
        raise err("ERR_INVALID_REQUEST", "checklist_items must be an array")
    out = []
    for it in items:
        if not isinstance(it, dict):
            raise err("ERR_INVALID_REQUEST", "checklist item must be an object")
        if "step" not in it or not isinstance(it["step"], str):
            raise err("ERR_INVALID_REQUEST", "checklist item must have step (string)")
        if "done" not in it or not isinstance(it["done"], bool):
            raise err("ERR_INVALID_REQUEST", "checklist item must have done (bool)")
        note = it.get("note", "")
        if note is not None and not isinstance(note, str):
            raise err("ERR_INVALID_REQUEST", "checklist item note must be a string")
        out.append({"step": it["step"], "done": it["done"], "note": note or ""})
    return out


def _validate_vitals(vitals):
    if vitals is None:
        return []
    if not isinstance(vitals, list):
        raise err("ERR_INVALID_REQUEST", "vitals must be an array")
    out = []
    for v in vitals:
        if not isinstance(v, dict):
            raise err("ERR_INVALID_REQUEST", "vital must be an object")
        if v.get("type") not in VITAL_TYPES:
            raise err("ERR_INVALID_REQUEST", f"vital.type must be one of {VITAL_TYPES}")
        if not isinstance(v.get("ts"), str):
            raise err("ERR_INVALID_REQUEST", "vital.ts must be a string")
        out.append(v)
    return out


def _validate_meds(meds):
    if meds is None:
        return []
    if not isinstance(meds, list):
        raise err("ERR_INVALID_REQUEST", "medications_administered must be an array")
    return list(meds)


def _validate_evidence(urls):
    if urls is None:
        return []
    if not isinstance(urls, list):
        raise err("ERR_INVALID_REQUEST", "evidence_urls must be an array")
    for u in urls:
        if not isinstance(u, str):
            raise err("ERR_INVALID_REQUEST", "evidence_urls entries must be strings")
    return list(urls)


def _validate_abnormals(events):
    if events is None:
        return []
    if not isinstance(events, list):
        raise err("ERR_INVALID_REQUEST", "abnormal_events must be an array")
    out = []
    for e in events:
        if not isinstance(e, dict):
            raise err("ERR_INVALID_REQUEST", "abnormal event must be an object")
        if e.get("severity") not in SEVERITIES:
            raise err("ERR_INVALID_REQUEST", f"abnormal severity must be one of {SEVERITIES}")
        out.append(e)
    return out


# ---------------------------------------------------------------- Check-in --
def checkin(order_id: str, user_id: str, body: dict) -> dict:
    from services.order import get_order
    order = get_order(order_id)
    # PRD §2.5 priority funnel: (4) state-machine precondition fires
    # before (5) cross-entity referential integrity, so check the order
    # state first; the nurse-on-dispatch link is treated as cross-ref.
    if order["status"] != "DISPATCHED":
        raise err("ERR_INVALID_STATE", f"order is {order['status']}")
    if _record_for_order(order_id) is not None:
        raise err("ERR_INVALID_STATE", "service record already exists")
    # Determine assigned nurse: must have an ACCEPTED dispatch tied to caller
    assigned_nid = None
    for d in db.dispatches.values():
        if d.get("order_id") == order_id and d.get("status") == "ACCEPTED":
            assigned_nid = d.get("nurse_id")
            break
    if assigned_nid is None or assigned_nid != user_id:
        raise err("ERR_RESOURCE_LINK_INVALID",
                  "only the dispatched nurse may check in")

    checkin_at_raw = require_str(body, "checkin_at")
    try:
        checkin_at_dt = parse_iso(checkin_at_raw)
    except ValueError as e:
        raise err("ERR_INVALID_REQUEST", str(e))
    lat = require_num(body, "checkin_lat")
    lng = require_num(body, "checkin_lng")
    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        raise err("ERR_INVALID_REQUEST", "checkin_lat/lng out of range")
    face_pass = require_bool(body, "face_verification_passed")

    # Geofence first
    dist = haversine_km(order["service_lat"], order["service_lng"], lat, lng)
    if dist > MAX_CHECKIN_RADIUS_KM:
        raise err("ERR_CHECKIN_OUT_OF_RANGE",
                  f"check-in too far ({dist:.3f}km) from service address")
    # Then face verification
    if not face_pass:
        raise err("ERR_FACE_VERIFICATION_FAILED", "face_verification_passed must be true")

    checklist = _validate_checklist(body.get("checklist_items"))
    vitals = _validate_vitals(body.get("vitals"))
    meds = _validate_meds(body.get("medications_administered"))
    evidence = _validate_evidence(body.get("evidence_urls"))
    abnormals = _validate_abnormals(body.get("abnormal_events"))

    sr = {
        "order_id": order_id,
        "nurse_id": user_id,
        "checkin_at": iso(checkin_at_dt),
        "checkin_lat": float(lat),
        "checkin_lng": float(lng),
        "face_verification_passed": True,
        "checklist_items": checklist,
        "vitals": vitals,
        "medications_administered": meds,
        "evidence_urls": evidence,
        "abnormal_events": abnormals,
        "completed_at": None,
        "status": "STARTED",
    }
    db.stamp_create(sr, common_fields=True)
    db.service_records[sr["id"]] = sr

    # Order DISPATCHED → IN_PROGRESS
    order["status"] = "IN_PROGRESS"
    db.stamp_update(order)

    audit("SERVICE_RECORD", sr["id"], "CHECKIN", payload={"order_id": order_id})
    return sr


# ----------------------------------------------------------------- Append --
def append_record(order_id: str, user_id: str, body: dict) -> dict:
    sr = _record_for_order(order_id)
    if sr is None:
        raise err("ERR_INVALID_STATE", "service record does not exist")
    if sr.get("nurse_id") != user_id:
        raise err("ERR_INSUFFICIENT_PERMISSIONS", "not your service record")
    if sr["status"] not in ("STARTED", "IN_PROGRESS"):
        raise err("ERR_INVALID_STATE", f"service record is {sr['status']}")

    check_occ(sr, body or {})

    if "checklist_items" in body:
        sr["checklist_items"] = _validate_checklist(body["checklist_items"])
    if "vitals" in body:
        sr["vitals"] = _validate_vitals(body["vitals"])
    if "medications_administered" in body:
        sr["medications_administered"] = _validate_meds(body["medications_administered"])
    if "evidence_urls" in body:
        sr["evidence_urls"] = _validate_evidence(body["evidence_urls"])
    if "abnormal_events" in body:
        sr["abnormal_events"] = _validate_abnormals(body["abnormal_events"])

    if sr["status"] == "STARTED":
        sr["status"] = "IN_PROGRESS"
    db.stamp_update(sr)
    return sr


# -------------------------------------------------------------- Finish --
def finish(order_id: str, user_id: str, body: dict) -> dict:
    sr = _record_for_order(order_id)
    if sr is None:
        raise err("ERR_INVALID_STATE", "service record does not exist")
    if sr.get("nurse_id") != user_id:
        raise err("ERR_INSUFFICIENT_PERMISSIONS", "not your service record")
    if sr["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", f"service record is {sr['status']}")
    check_occ(sr, body or {})
    # Gates
    cl = sr.get("checklist_items") or []
    if not cl or not all(item.get("done") is True for item in cl):
        raise err("ERR_CHECKLIST_INCOMPLETE",
                  "all checklist items must be done and the list must be non-empty")
    if not (sr.get("evidence_urls") or []):
        raise err("ERR_CHECKLIST_INCOMPLETE", "at least one evidence URL is required")
    for ev in sr.get("abnormal_events") or []:
        if ev.get("severity") == "HIGH":
            desc = ev.get("description")
            if not desc or not str(desc).strip():
                raise err("ERR_CHECKLIST_INCOMPLETE",
                          "HIGH severity abnormal events require a description")
    sr["completed_at"] = iso(now())
    sr["status"] = "AWAITING_PATIENT_CONFIRM"
    db.stamp_update(sr)
    return sr
