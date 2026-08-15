"""Board disciplinary-event endpoints (PRD 3.7)."""
from flask import Blueprint, request

from db import DB, current_date, new_id, now_iso
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from serializers import disciplinary_event_view
from services import (
    invalidate_sealed_packages,
    refresh_employee_derived,
    refresh_license_derived,
    touch,
)
from util import as_bool, as_date, as_enum, as_str, body, pagination_args, required

bp = Blueprint("disciplinary_events", __name__, url_prefix="/licensing")

EVENT_TYPES = ("WARNING", "REPRIMAND", "FINE", "SUSPENSION", "REVOCATION")
RECEIVED_VIA = ("BOARD_FEED", "MANUAL")


def _open_suspension_covers(license_id, excluding_id=None):
    """True when another SUSPENSION event still covers the license: standing at
    CONFIRMED, or at RECEIVED with the effect applied at creation (PRD 3.7)."""
    for ev in DB["disciplinary_events"].values():
        if ev["license_id"] != license_id or ev["id"] == excluding_id:
            continue
        if ev["event_type"] != "SUSPENSION":
            continue
        if ev["status"] == "CONFIRMED":
            return True
        if ev["status"] == "RECEIVED" and ev["applied_at_creation"]:
            return True
    return False


def _cascade_license(lic):
    """Refresh derived fields and holder authorization after a sanction."""
    refresh_license_derived(lic)
    emp = DB["employees"][lic["employee_id"]]
    refresh_employee_derived(emp, bump=True)


@bp.post("/licenses/<lid>/disciplinary-events")
def create_disciplinary_event(lid):
    user_id, role = auth(["ComplianceOfficer"])
    lic = DB["licenses"].get(lid)
    if lic is None:
        raise ApiError("ERR_NOT_FOUND", 404, "License not found")
    data = body()
    case_number = as_str(required(data, "board_case_number"), "board_case_number")
    event_type = as_enum(required(data, "event_type"), "event_type", EVENT_TYPES)
    effective = as_date(required(data, "effective_on"), "effective_on")
    via = as_enum(required(data, "received_via"), "received_via", RECEIVED_VIA)
    confirm_at_creation = False
    if "confirm_at_creation" in data and data["confirm_at_creation"] is not None:
        confirm_at_creation = as_bool(
            data["confirm_at_creation"], "confirm_at_creation"
        )
    if effective > current_date():
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "effective_on must not be in the future"
        )

    # Case numbers are unique per license.
    for ev in DB["disciplinary_events"].values():
        if ev["license_id"] == lid and ev["board_case_number"] == case_number:
            raise ApiError(
                "ERR_DUPLICATE_CASE_NUMBER", 409,
                "A disciplinary event with this board_case_number already exists for the license",
            )

    ts = now_iso()
    ev = {
        "id": new_id(),
        "license_id": lid,
        "board_case_number": case_number,
        "event_type": event_type,
        "effective_on": effective.isoformat(),
        "received_via": via,
        "confirm_at_creation": confirm_at_creation,
        "applied_at_creation": False,
        "created_by_user_id": user_id,
        "adjudicated_by_user_id": None,
        "resolution_note": None,
        "status": "RECEIVED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB["disciplinary_events"][ev["id"]] = ev

    # confirm_at_creation on a SUSPENSION applies the sanction immediately;
    # the event itself still sits at RECEIVED awaiting adjudication.
    if confirm_at_creation and event_type == "SUSPENSION" and lic["status"] == "ACTIVE":
        lic["status"] = "SUSPENDED"
        lic["alert_tier"] = "AT_EXPIRY"
        ev["applied_at_creation"] = True
        touch(lic)
        _cascade_license(lic)

    # Board actions are evidence: invalidate sealed packages covering the date.
    invalidate_sealed_packages(lic["employee_id"], effective)
    return ok(disciplinary_event_view(ev), status=201)


@bp.get("/licenses/<lid>/disciplinary-events")
def list_disciplinary_events(lid):
    auth(ALL_ROLES)
    if lid not in DB["licenses"]:
        raise ApiError("ERR_NOT_FOUND", 404, "License not found")
    limit, offset = pagination_args()
    items = sorted(
        (e for e in DB["disciplinary_events"].values() if e["license_id"] == lid),
        key=lambda x: x["created_at"],
    )
    status = request.args.get("status")
    event_type = request.args.get("event_type")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    if event_type is not None:
        items = [e for e in items if e["event_type"] == event_type]
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([disciplinary_event_view(x) for x in page], total, limit, offset)


def _get_event_or_404(eid):
    ev = DB["disciplinary_events"].get(eid)
    if ev is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Disciplinary event not found")
    return ev


def _sod_check(ev, user_id):
    if user_id == ev["created_by_user_id"]:
        raise ApiError(
            "ERR_SOD_SAME_USER", 403,
            "Adjudicator must differ from the event's recorder",
        )


@bp.post("/disciplinary-events/<eid>/confirm")
def confirm_disciplinary_event(eid):
    user_id, role = auth(["ComplianceOfficer"])
    ev = _get_event_or_404(eid)
    if ev["status"] != "RECEIVED":
        raise ApiError(
            "ERR_INVALID_STATE", 409,
            f"Disciplinary event in {ev['status']} cannot be confirmed",
        )
    _sod_check(ev, user_id)
    ev["status"] = "CONFIRMED"
    ev["adjudicated_by_user_id"] = user_id
    touch(ev)
    lic = DB["licenses"][ev["license_id"]]
    if ev["event_type"] == "SUSPENSION":
        if not ev["applied_at_creation"] and lic["status"] == "ACTIVE":
            lic["status"] = "SUSPENDED"
            lic["alert_tier"] = "AT_EXPIRY"
            touch(lic)
            _cascade_license(lic)
    elif ev["event_type"] == "REVOCATION":
        if lic["status"] in ("ACTIVE", "SUSPENDED"):
            lic["status"] = "REVOKED"
            lic["alert_tier"] = "AT_EXPIRY"
            touch(lic)
            _cascade_license(lic)
    # WARNING / REPRIMAND / FINE leave the license untouched.
    return ok(disciplinary_event_view(ev))


@bp.post("/disciplinary-events/<eid>/dismiss")
def dismiss_disciplinary_event(eid):
    user_id, role = auth(["ComplianceOfficer"])
    ev = _get_event_or_404(eid)
    data = body()
    resolution_note = None
    if "resolution_note" in data and data["resolution_note"] is not None:
        resolution_note = as_str(data["resolution_note"], "resolution_note")
    if ev["status"] != "RECEIVED":
        raise ApiError(
            "ERR_INVALID_STATE", 409,
            f"Disciplinary event in {ev['status']} cannot be dismissed",
        )
    _sod_check(ev, user_id)
    ev["status"] = "DISMISSED"
    ev["adjudicated_by_user_id"] = user_id
    ev["resolution_note"] = resolution_note
    touch(ev)
    lic = DB["licenses"][ev["license_id"]]
    # Compensation: unwind a suspension applied at creation.
    if ev["applied_at_creation"] and lic["status"] == "SUSPENDED":
        lic["status"] = "ACTIVE"
        touch(lic)
        _cascade_license(lic)
    return ok(disciplinary_event_view(ev))


@bp.post("/disciplinary-events/<eid>/resolve")
def resolve_disciplinary_event(eid):
    user_id, role = auth(["ComplianceOfficer"])
    ev = _get_event_or_404(eid)
    data = body()
    resolution_note = None
    if "resolution_note" in data and data["resolution_note"] is not None:
        resolution_note = as_str(data["resolution_note"], "resolution_note")
    if ev["status"] != "CONFIRMED":
        raise ApiError(
            "ERR_INVALID_STATE", 409,
            f"Disciplinary event in {ev['status']} cannot be resolved",
        )
    _sod_check(ev, user_id)
    ev["status"] = "RESOLVED"
    ev["adjudicated_by_user_id"] = user_id
    ev["resolution_note"] = resolution_note
    touch(ev)
    lic = DB["licenses"][ev["license_id"]]
    if ev["event_type"] == "SUSPENSION" and lic["status"] == "SUSPENDED":
        # The suspension lifts only when no other open suspension covers it.
        if not _open_suspension_covers(ev["license_id"], excluding_id=ev["id"]):
            lic["status"] = "ACTIVE"
            touch(lic)
            _cascade_license(lic)
    # A REVOCATION never lifts: the license stays REVOKED (terminal).
    return ok(disciplinary_event_view(ev))
