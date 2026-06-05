"""Trustee appointments — Trust<->Trustee junction (PRD §3.2)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import authenticate, require_role, parse_pagination, paginate
from response import success
from services import serialize
from services.helpers import (
    get_json_body, require_str, require_datetime, parse_datetime, must_exist,
)

bp = Blueprint("appointments", __name__)

TRUSTEE_GAP_DAYS = 30
GAP_SECONDS = TRUSTEE_GAP_DAYS * 86400


@bp.route("/trusts/<tid>/trustee-appointments", methods=["POST"])
def create_appointment(tid):
    _, role = authenticate()
    require_role(role, {"TrustAdmin"})
    t = must_exist(db.trusts, tid)
    body = get_json_body()
    trustee_id = require_str(body, "trustee_id")
    term_start = require_datetime(body, "term_start")
    term_end = require_datetime(body, "term_end")
    must_exist(db.trustees, trustee_id)

    ts = parse_datetime(term_start, "term_start")
    te = parse_datetime(term_end, "term_end")
    if not (te > ts):
        raise err("ERR_VALIDATION", "term_end must be strictly after term_start")

    with db.LOCK:
        # Conflict check: same (trust, trustee) seat; closed intervals with a
        # mandatory 30-day buffer gap. Overlap OR within-gap => conflict.
        for a in db.trustee_appointments.values():
            if a["trust_id"] != tid or a["trustee_id"] != trustee_id:
                continue
            if a["status"] != "ACTIVE":
                continue
            ex_s = parse_datetime(a["term_start"])
            ex_e = parse_datetime(a["term_end"])
            # Two closed intervals conflict if the gap between them is < buffer.
            # No conflict only if new starts >= existing_end + gap, OR
            # existing starts >= new_end + gap.
            if not (ts >= ex_e + GAP_SECONDS or ex_s >= te + GAP_SECONDS):
                raise err("ERR_TRUSTEE_TERM_CONFLICT")
        a = db.base_fields()
        a.update({
            "trust_id": tid,
            "trustee_id": trustee_id,
            "term_start": term_start,
            "term_end": term_end,
            "status": "ACTIVE",
        })
        db.trustee_appointments[a["id"]] = a
    return success(serialize.trustee_appointment(a), status=201)


@bp.route("/trusts/<tid>/trustee-appointments", methods=["GET"])
def list_trust_appointments(tid):
    user_id, role = authenticate()
    require_role(role, {"TrustAdmin", "Trustee"})
    must_exist(db.trusts, tid)
    limit, offset = parse_pagination()
    items = [a for a in db.trustee_appointments.values() if a["trust_id"] == tid]
    page, meta = paginate(items, limit, offset)
    return success([serialize.trustee_appointment(a) for a in page], pagination=meta)


@bp.route("/trustee-appointments/<aid>", methods=["GET"])
def get_appointment(aid):
    _, role = authenticate()
    require_role(role, {"TrustAdmin", "Trustee"})
    a = must_exist(db.trustee_appointments, aid)
    return success(serialize.trustee_appointment(a))


@bp.route("/trustee-appointments", methods=["GET"])
def list_appointments():
    _, role = authenticate()
    require_role(role, {"TrustAdmin"})
    limit, offset = parse_pagination()
    trustee_id = request.args.get("trustee_id")
    items = list(db.trustee_appointments.values())
    if trustee_id is not None:
        items = [a for a in items if a["trustee_id"] == trustee_id]
    page, meta = paginate(items, limit, offset)
    return success([serialize.trustee_appointment(a) for a in page], pagination=meta)
