"""TechRiderCheck endpoints: POST/GET under /stops/{id}/tech-checks,
PUT /tech-checks/{check_id} (record measurement or waive a FAIL)."""

from flask import Blueprint

import db
from db import touch
from errors import (err, ERR_NOT_FOUND, ERR_INVALID_REQUEST,
                    ERR_WAIVER_NOTE_REQUIRED, ERR_STOP_INVALID_STATE,
                    ERR_CHECK_INVALID_STATE)
from middleware import authenticate, require_roles
from response import success, success_list
from services import domain
from util import (get_body, reject_unknown, require_present, as_int,
                  as_enum, paginate)

bp = Blueprint("tech_checks", __name__)

ITEMS = ("STAGE_WIDTH_FT", "FLY_LINES", "POWER_AMPS", "CREW_MINIMUM")


def _get_stop_or_404(stop_id):
    stop = db.stops.get(stop_id)
    if stop is None:
        raise err(ERR_NOT_FOUND, 404, "Stop not found")
    return stop


@bp.route("/stops/<stop_id>/tech-checks", methods=["POST"])
def create_check(stop_id):
    _, role = authenticate()
    require_roles(role, ("TourManager",))
    stop = _get_stop_or_404(stop_id)
    body = get_body()
    reject_unknown(body, {"item", "required_value"})
    item = as_enum(require_present(body, "item"), "item", ITEMS)
    required = as_int(require_present(body, "required_value"), "required_value", minv=1)
    if stop["booking_status"] not in ("CONTRACTED", "ADVANCED"):
        raise err(ERR_STOP_INVALID_STATE, 409,
                  "Tech checks may be created only while CONTRACTED or ADVANCED")
    rec = db.new_record()
    rec.update({
        "stop_id": stop_id,
        "item": item,
        "required_value": required,
        "actual_value": None,
        "status": "PENDING",
        "waiver_note": None,
    })
    db.tech_checks[rec["id"]] = rec
    domain.recompute_compliance(stop)  # first check: PENDING -> IN_PROGRESS
    return success(db.serialize("tech_check", rec), 201)


@bp.route("/stops/<stop_id>/tech-checks", methods=["GET"])
def list_checks(stop_id):
    authenticate()
    _get_stop_or_404(stop_id)
    items = sorted(domain.checks_of_stop(stop_id), key=lambda c: c["_seq"])
    data, total, limit, offset = paginate(items, lambda r: db.serialize("tech_check", r))
    return success_list(data, total, limit, offset, 200)


@bp.route("/tech-checks/<check_id>", methods=["PUT"])
def put_check(check_id):
    _, role = authenticate()
    body = get_body()
    # Role-for-transition (priority 2): WAIVED is Producer-only; recording
    # actual_value is TourManager-only.
    if body.get("status") == "WAIVED":
        require_roles(role, ("Producer",))
    elif "actual_value" in body and body.get("status") is None:
        require_roles(role, ("TourManager",))
    else:
        require_roles(role, ("Producer", "TourManager"))
    check = db.tech_checks.get(check_id)
    if check is None:
        raise err(ERR_NOT_FOUND, 404, "Tech check not found")
    reject_unknown(body, {"actual_value", "status", "waiver_note"})
    stop = db.stops[check["stop_id"]]

    if body.get("status") is not None:
        # Waive path: the only client-settable status is WAIVED.
        target = as_enum(body["status"], "status", ("PENDING", "PASS", "FAIL", "WAIVED"))
        if target != "WAIVED":
            raise err(ERR_INVALID_REQUEST, 400,
                      "check status is system-computed; only WAIVED may be requested")
        note = body.get("waiver_note")
        if not isinstance(note, str) or note == "":
            raise err(ERR_WAIVER_NOTE_REQUIRED, 400,
                      "Waiving a FAIL check requires a waiver_note")
        if check["status"] != "FAIL":
            raise err(ERR_CHECK_INVALID_STATE, 409,
                      "Only a FAIL check may be waived")
        check["status"] = "WAIVED"
        check["waiver_note"] = note
        touch(check)
        domain.recompute_compliance(stop)
        return success(db.serialize("tech_check", check), 200)

    # Measurement path.
    actual = as_int(require_present(body, "actual_value"), "actual_value", minv=0)
    if check["status"] == "WAIVED":
        raise err(ERR_CHECK_INVALID_STATE, 409,
                  "WAIVED is terminal; actual_value cannot be recorded")
    check["actual_value"] = actual
    # PASS iff actual >= required (>= boundary passes); FAIL otherwise.
    check["status"] = "PASS" if actual >= check["required_value"] else "FAIL"
    touch(check)
    domain.recompute_compliance(stop)  # FAIL on a READY stop revokes certification
    return success(db.serialize("tech_check", check), 200)
