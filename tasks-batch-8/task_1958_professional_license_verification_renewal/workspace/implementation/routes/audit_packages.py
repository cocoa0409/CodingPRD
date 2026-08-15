"""Audit evidence package endpoints (PRD 3.9)."""
from flask import Blueprint, request

from db import DB, current_date, current_timestamp_iso, new_id, now_iso
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from serializers import audit_package_view
from services import touch
from util import as_date, body, pagination_args, parse_ymd, required

bp = Blueprint("audit_packages", __name__, url_prefix="/licensing")


@bp.post("/employees/<eid>/audit-packages")
def create_audit_package(eid):
    auth(["ExternalAuditor"])
    if eid not in DB["employees"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Employee not found")
    data = body()
    period_start = as_date(required(data, "period_start"), "period_start")
    period_end = as_date(required(data, "period_end"), "period_end")
    if period_end <= period_start:
        raise ApiError(
            "ERR_INVALID_AUDIT_PERIOD", 422, "period_end must be after period_start"
        )
    # Half-open [start, end) overlap with BUILDING/SEALED packages of the same
    # employee; strictly adjacent is allowed; INVALIDATED packages are ignored.
    for pkg in DB["audit_packages"].values():
        if pkg["employee_id"] != eid or pkg["status"] in ("INVALIDATED",):
            continue
        if pkg["status"] not in ("BUILDING", "SEALED"):
            continue
        other_start = parse_ymd(pkg["period_start"])
        other_end = parse_ymd(pkg["period_end"])
        if period_start < other_end and other_start < period_end:
            raise ApiError(
                "ERR_AUDIT_PERIOD_OVERLAP", 409,
                "The period intersects an existing BUILDING/SEALED package for this employee",
            )

    ts = now_iso()
    pkg = {
        "id": new_id(),
        "employee_id": eid,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "status": "BUILDING",
        "sealed_at": None,
        "evidence_snapshot": [],
        "evidence_item_count": 0,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB["audit_packages"][pkg["id"]] = pkg
    return ok(audit_package_view(pkg), status=201)


@bp.get("/employees/<eid>/audit-packages")
def list_audit_packages(eid):
    auth(ALL_ROLES)
    if eid not in DB["employees"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Employee not found")
    limit, offset = pagination_args()
    items = sorted(
        (p for p in DB["audit_packages"].values() if p["employee_id"] == eid),
        key=lambda x: x["created_at"],
    )
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([audit_package_view(x) for x in page], total, limit, offset)


@bp.get("/audit-packages/<pid>")
def get_audit_package(pid):
    auth(ALL_ROLES)
    pkg = DB["audit_packages"].get(pid)
    if pkg is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Audit package not found")
    return ok(audit_package_view(pkg))


def _in_period(day_str, start, end):
    day = parse_ymd(day_str)
    return start <= day < end


def _build_snapshot(pkg):
    """audit_snapshot calculation: evidence items over the subject employee's
    records within [period_start, period_end), ordered occurred_on ASC, then
    kind ASC (alphabetical), then the record's created_at ASC."""
    employee_id = pkg["employee_id"]
    start = parse_ymd(pkg["period_start"])
    end = parse_ymd(pkg["period_end"])
    license_ids = {
        l["id"] for l in DB["licenses"].values() if l["employee_id"] == employee_id
    }
    items = []
    for ev in DB["verification_events"].values():
        if ev["license_id"] in license_ids and _in_period(ev["verified_on"], start, end):
            items.append(
                {
                    "kind": "VerificationEvent",
                    "ref_id": ev["id"],
                    "occurred_on": ev["verified_on"],
                    "_created_at": ev["created_at"],
                }
            )
    for ev in DB["disciplinary_events"].values():
        if ev["license_id"] in license_ids and _in_period(ev["effective_on"], start, end):
            items.append(
                {
                    "kind": "DisciplinaryEvent",
                    "ref_id": ev["id"],
                    "occurred_on": ev["effective_on"],
                    "_created_at": ev["created_at"],
                }
            )
    for scr in DB["exclusion_screenings"].values():
        if scr["employee_id"] == employee_id and _in_period(scr["screened_on"], start, end):
            items.append(
                {
                    "kind": "ExclusionScreening",
                    "ref_id": scr["id"],
                    "occurred_on": scr["screened_on"],
                    "_created_at": scr["created_at"],
                }
            )
    for req in DB["renewal_requests"].values():
        if (
            req["license_id"] in license_ids
            and req["status"] == "PAID"
            and req["paid_on"] is not None
            and _in_period(req["paid_on"], start, end)
        ):
            items.append(
                {
                    "kind": "RenewalRequest",
                    "ref_id": req["id"],
                    "occurred_on": req["paid_on"],
                    "_created_at": req["created_at"],
                }
            )
    items.sort(key=lambda x: (x["occurred_on"], x["kind"], x["_created_at"]))
    for item in items:
        del item["_created_at"]
    return items


@bp.post("/audit-packages/<pid>/seal")
def seal_audit_package(pid):
    auth(["ExternalAuditor"])
    pkg = DB["audit_packages"].get(pid)
    if pkg is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Audit package not found")
    if pkg["status"] != "BUILDING":
        raise ApiError(
            "ERR_INVALID_STATE", 409,
            f"Audit package in {pkg['status']} cannot be sealed",
        )
    if parse_ymd(pkg["period_end"]) > current_date():
        raise ApiError(
            "ERR_AUDIT_PERIOD_NOT_CLOSED", 422,
            "The audit period has not yet closed against the logical clock",
        )
    pkg["evidence_snapshot"] = _build_snapshot(pkg)
    pkg["evidence_item_count"] = len(pkg["evidence_snapshot"])
    pkg["status"] = "SEALED"
    pkg["sealed_at"] = current_timestamp_iso()
    touch(pkg)
    return ok(audit_package_view(pkg))
