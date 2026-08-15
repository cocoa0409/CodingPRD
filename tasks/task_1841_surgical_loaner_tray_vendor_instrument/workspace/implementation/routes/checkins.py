"""CheckInEvent routes: creation by VendorRep, verification by
VendorCoordinator, plus the late-delivery penalty cascade."""

import math

from flask import Blueprint, request as flask_request

import db
from errors import raise_err
from middleware import get_auth, require_role, get_body
from response import success_object, success_list, parse_pagination
from services import core

bp = Blueprint("checkins", __name__)


def _get_checkin_or_404(checkin_id):
    c = db.check_ins.get(checkin_id)
    if c is None:
        raise_err("ERR_CHECKIN_NOT_FOUND", "Check-in not found")
    return c


def _rep_guard(request, rep_id):
    """The acting rep must exist, be credential-ACTIVE, and belong to the
    request's vendor."""
    rep = db.reps.get(rep_id)
    if rep is None:
        raise_err("ERR_REP_NOT_FOUND", "Representative not found")
    if rep["credential_status"] != "ACTIVE":
        raise_err("ERR_REP_CREDENTIAL_NOT_ACTIVE", "Rep credential is not ACTIVE")
    if rep["vendor_id"] != request["vendor_id"]:
        raise_err("ERR_REP_VENDOR_MISMATCH", "Rep does not belong to the request's vendor")
    return rep


@bp.post("/requests/<id>/check-ins")
def create_checkin(id):
    user_id, role = get_auth()
    body = get_body(required=True)

    # Body well-formedness (tier 2) precedes role authorization and
    # existence checks.
    lines = body.get("lines")
    if not isinstance(lines, list) or not lines:
        raise_err("ERR_VALIDATION", "lines must be a non-empty array")
    for line in lines:
        if not isinstance(line, dict):
            raise_err("ERR_VALIDATION", "each line must be an object")
        if not isinstance(line.get("tray_id"), str):
            raise_err("ERR_VALIDATION", "each line requires a tray_id string")
        count = line.get("instrument_count_delivered")
        if count is None or isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise_err("ERR_VALIDATION", "instrument_count_delivered must be a non-negative integer")
        if "condition_notes" in line and line["condition_notes"] is not None and not isinstance(line["condition_notes"], str):
            raise_err("ERR_VALIDATION", "condition_notes must be a string")
    ifu_provided = body.get("ifu_provided")
    if not isinstance(ifu_provided, bool):
        raise_err("ERR_VALIDATION", "ifu_provided must be a boolean")
    implant_log_provided = body.get("implant_log_provided", False)
    if not isinstance(implant_log_provided, bool):
        raise_err("ERR_VALIDATION", "implant_log_provided must be a boolean")
    loaner_agreement_ref = body.get("loaner_agreement_ref")
    if not isinstance(loaner_agreement_ref, str) or not loaner_agreement_ref.strip():
        raise_err("ERR_VALIDATION", "loaner_agreement_ref is required")

    require_role(role, ["VendorRep"])

    request = db.requests.get(id)
    if request is None:
        raise_err("ERR_REQUEST_NOT_FOUND", "Loaner request not found")

    # State guard: request must be APPROVED to accept deliveries.
    if request["status"] != "APPROVED":
        raise_err("ERR_REQUEST_INVALID_STATE", "Check-in requires an APPROVED request")

    # Rep credential + vendor ownership guards.
    _rep_guard(request, user_id)

    # Line-level referential + state + duplicate checks.
    seen = set()
    line_trays = []
    for line in lines:
        tray_id = line["tray_id"]
        if tray_id in seen:
            raise_err("ERR_DUPLICATE_TRAY_LINE", "same tray_id appears twice in check-in lines")
        seen.add(tray_id)
        tray = db.trays.get(tray_id)
        if tray is None:
            raise_err("ERR_TRAY_NOT_FOUND", "Tray not found")
        if tray["request_id"] != id:
            raise_err("ERR_TRAY_NOT_IN_REQUEST", "Tray belongs to a different request")
        if tray["status"] not in {"EXPECTED", "MISSING"}:
            raise_err("ERR_TRAY_INVALID_STATE", "Tray must be EXPECTED or MISSING for check-in")
        line_trays.append(tray)

    # Implant log required when any line's tray is an implant tray.
    if any(t["implant_flag"] for t in line_trays) and not implant_log_provided:
        raise_err("ERR_IMPLANT_LOG_REQUIRED", "Implant log is required for implant trays")

    checkin = {
        "request_id": id,
        "rep_id": user_id,
        "delivered_at": db.fmt_ts(db.now_dt()),
        "lines": [
            {
                "tray_id": line["tray_id"],
                "instrument_count_delivered": line["instrument_count_delivered"],
                **({"condition_notes": line["condition_notes"]} if line.get("condition_notes") is not None else {}),
            }
            for line in lines
        ],
        "ifu_provided": ifu_provided,
        "implant_log_provided": implant_log_provided,
        "loaner_agreement_ref": loaner_agreement_ref,
        "status": "SUBMITTED",
        "verified_by_user_id": None,
        "late_minutes": 0,
    }
    core.stamp_new(checkin, with_version=False)
    db.check_ins[checkin["id"]] = checkin

    # Covered trays -> DELIVERY_PENDING.
    for tray in line_trays:
        tray["status"] = "DELIVERY_PENDING"
        core.recompute_tray_projection(tray)
        core.touch(tray)
    core.recompute_readiness(request)
    core.touch(request)

    return success_object(core.serialize(checkin), status=201)


@bp.get("/check-ins")
def list_checkins():
    get_auth()
    request_id = flask_request.args.get("request_id")
    rep_id = flask_request.args.get("rep_id")
    status = flask_request.args.get("status")
    items = sorted(db.check_ins.values(), key=lambda c: c["_seq"])
    if request_id:
        items = [c for c in items if c["request_id"] == request_id]
    if rep_id:
        items = [c for c in items if c["rep_id"] == rep_id]
    if status:
        items = [c for c in items if c["status"] == status]
    total = len(items)
    limit, offset = parse_pagination(flask_request.args)
    page = items[offset : offset + limit]
    return success_list([core.serialize(c) for c in page], limit, offset, total)


@bp.get("/check-ins/<id>")
def get_checkin(id):
    get_auth()
    checkin = _get_checkin_or_404(id)
    return success_object(core.serialize(checkin))


@bp.post("/check-ins/<id>/verify")
def verify_checkin(id):
    user_id, role = get_auth()
    body = get_body(required=True)

    line_dispositions = body.get("line_dispositions")
    if not isinstance(line_dispositions, list) or not line_dispositions:
        raise_err("ERR_VALIDATION", "line_dispositions must be a non-empty array")
    parsed_dispositions = {}
    for entry in line_dispositions:
        if not isinstance(entry, dict):
            raise_err("ERR_VALIDATION", "each line disposition must be an object")
        tray_id = entry.get("tray_id")
        disposition = entry.get("disposition")
        if not isinstance(tray_id, str) or disposition not in {"ACCEPT", "QUARANTINE"}:
            raise_err("ERR_VALIDATION", "each line disposition requires tray_id and disposition ACCEPT|QUARANTINE")
        parsed_dispositions[tray_id] = disposition

    require_role(role, ["VendorCoordinator"])
    checkin = _get_checkin_or_404(id)

    if checkin["status"] != "SUBMITTED":
        raise_err("ERR_CHECKIN_INVALID_STATE", "Check-in must be SUBMITTED to verify")

    request = db.requests.get(checkin["request_id"])
    vendor = db.vendors.get(request["vendor_id"]) if request else None

    # Every check-in line needs a disposition; default missing ones to ACCEPT?
    # No — dispositions are one per line. Missing disposition for a line is a
    # validation error to avoid silent acceptance.
    for line in checkin["lines"]:
        if line["tray_id"] not in parsed_dispositions:
            raise_err("ERR_VALIDATION", f"missing disposition for tray {line['tray_id']}")

    # Late minutes: whole minutes from required_delivery_by to delivered_at,
    # floored at zero.
    delivered_at = db.parse_dt(checkin["delivered_at"])
    required_by = db.parse_dt(request["required_delivery_by"]) if request else None
    late_minutes = 0
    if required_by is not None and delivered_at is not None:
        late_minutes = db.whole_minutes(delivered_at - required_by)
    checkin["late_minutes"] = late_minutes
    checkin["verified_by_user_id"] = user_id

    # Apply per-line dispositions.
    any_quarantine = False
    for line in checkin["lines"]:
        tray = db.trays.get(line["tray_id"])
        disposition = parsed_dispositions[line["tray_id"]]
        if disposition == "ACCEPT":
            if line["instrument_count_delivered"] < 1:
                raise_err("ERR_VALIDATION", "ACCEPT requires instrument_count_delivered >= 1")
            tray["status"] = "CHECKED_IN"
            tray["delivered_instrument_count"] = line["instrument_count_delivered"]
            core.recompute_tray_projection(tray)
            core.touch(tray)
            if line["instrument_count_delivered"] < tray["declared_instrument_count"]:
                core.create_escalation(request["id"], "INCOMPLETE_COUNT", linked_tray_id=tray["id"])
        else:  # QUARANTINE
            any_quarantine = True
            tray["status"] = "QUARANTINED"
            core.recompute_tray_projection(tray)
            core.touch(tray)
            core.create_escalation(request["id"], "DOCUMENTATION", linked_tray_id=tray["id"])
        core.recompute_readiness(request)

    checkin["status"] = "PARTIALLY_VERIFIED" if any_quarantine else "VERIFIED"

    # Late-delivery cascade link 1: create ACCRUING penalty when late_minutes
    # exceeds grace (equivalently time charge > 0) and none exists yet.
    if vendor is not None:
        billable_minutes = max(0, late_minutes - vendor["late_grace_minutes"])
        billable_hours = math.ceil(billable_minutes / 60) if billable_minutes > 0 else 0
        time_charge = min(
            vendor["late_penalty_cap_cents"],
            vendor["late_rate_per_hour_cents"] * billable_hours,
        )
        existing = [p for p in db.penalties.values() if p["request_id"] == request["id"]]
        if time_charge > 0 and not existing:
            penalty = {
                "request_id": request["id"],
                "check_in_id": checkin["id"],
                "late_minutes": late_minutes,
                "billable_minutes": billable_minutes,
                "time_charge_cents": time_charge,
                "delay_surcharge_cents": 0,
                "assessed_cents": time_charge,
                "waived_cents": 0,
                "settled_cents": 0,
                "outstanding_cents": time_charge,
                "status": "ACCRUING",
            }
            core.stamp_new(penalty)
            db.penalties[penalty["id"]] = penalty
            # Link 2: penalty creation recomputes request penalty exposure.
            core.recompute_request_penalty_exposure(request["id"])

    return success_object(core.serialize(checkin))
