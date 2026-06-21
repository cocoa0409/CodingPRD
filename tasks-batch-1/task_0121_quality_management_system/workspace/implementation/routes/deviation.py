"""Deviation routes and the test-driving clock (PRD 3.9, 3.10)."""
from flask import Blueprint, request

from common import (parse_iso, require_enum, require_fields,
                    require_non_negative_int, require_string, stamp_create, touch)
from db import db
from errors import (ERR_DEVIATION_IN_USE, ERR_DEVIATION_OVERLAP,
                    ERR_FK_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE, err)
from middleware import (ROLE_QUALITY_ENGINEER, ROLE_QUALITY_MANAGER,
                        authenticate, require_role)
from response import list_success, success
from services.helpers import get_or_404, paginate, paginate_args
from services.serializers import deviation_out

bp = Blueprint("deviation", __name__)

DEVIATION_ACTIONS = {"APPROVE", "REJECT", "REVOKE"}


@bp.route("/deviations", methods=["POST"])
def create_deviation():
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_ENGINEER})
    body = request.get_json(silent=True) or {}

    # FK resolution (priority 4).
    ncr_id = body.get("ncr_id")
    supplier_id = body.get("supplier_id")
    if ncr_id is not None and ncr_id not in db.nonconformance_reports:
        raise err(ERR_FK_NOT_FOUND, "ncr_id does not resolve")
    if supplier_id is not None and supplier_id not in db.suppliers:
        raise err(ERR_FK_NOT_FOUND, "supplier_id does not resolve")

    # Well-formedness (priority 5).
    require_fields(body, ["ncr_id", "supplier_id", "part_number",
                          "valid_from", "valid_to", "max_qty"])
    require_string(body["part_number"], "part_number")
    require_non_negative_int(body["max_qty"], "max_qty", minimum=1)
    valid_from = parse_iso(body["valid_from"])
    valid_to = parse_iso(body["valid_to"])

    rec = {
        "ncr_id": ncr_id,
        "supplier_id": supplier_id,
        "part_number": body["part_number"],
        "valid_from": body["valid_from"],
        "valid_to": body["valid_to"],
        "valid_from_dt": valid_from,
        "valid_to_dt": valid_to,
        "max_qty": body["max_qty"],
        "status": "REQUESTED",
        "approved_by_personnel_id": None,
    }
    stamp_create(rec)
    db.deviations[rec["id"]] = rec
    return success(deviation_out(rec), status=201)


@bp.route("/deviations/<rid>", methods=["GET"])
def get_deviation(rid):
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_MANAGER, ROLE_QUALITY_ENGINEER})
    rec = get_or_404(db.deviations, rid)
    return success(deviation_out(rec))


@bp.route("/nonconformance-reports/<rid>/deviations", methods=["GET"])
def list_ncr_deviations(rid):
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_MANAGER, ROLE_QUALITY_ENGINEER})
    get_or_404(db.nonconformance_reports, rid)
    limit, offset = paginate_args()
    matches = [d for d in db.deviations.values() if d["ncr_id"] == rid]
    page, total = paginate(matches, limit, offset)
    return list_success([deviation_out(d) for d in page], limit, offset, total)


@bp.route("/deviations/<rid>/transition", methods=["POST"])
def transition_deviation(rid):
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_MANAGER})
    rec = get_or_404(db.deviations, rid)
    body = request.get_json(silent=True) or {}

    require_fields(body, ["action"])
    action = body["action"]
    require_enum(action, DEVIATION_ACTIONS, "action")

    if action == "APPROVE":
        if rec["status"] != "REQUESTED":
            raise err(ERR_INVALID_STATE, "APPROVE requires REQUESTED")
        # Overlap check against APPROVED deviations for same (supplier, part).
        for other in db.deviations.values():
            if other["id"] == rec["id"]:
                continue
            if other["status"] != "APPROVED":
                continue
            if other["supplier_id"] != rec["supplier_id"]:
                continue
            if other["part_number"] != rec["part_number"]:
                continue
            # Half-open overlap: a.from < b.to AND b.from < a.to.
            if (rec["valid_from_dt"] < other["valid_to_dt"]
                    and other["valid_from_dt"] < rec["valid_to_dt"]):
                raise err(ERR_DEVIATION_OVERLAP, "Deviation window overlaps an approved one")
        rec["status"] = "APPROVED"
        rec["approved_by_personnel_id"] = auth.user_id
        touch(rec)
        return success(deviation_out(rec))

    if action == "REJECT":
        if rec["status"] != "REQUESTED":
            raise err(ERR_INVALID_STATE, "REJECT requires REQUESTED")
        rec["status"] = "REJECTED"
        touch(rec)
        return success(deviation_out(rec))

    # REVOKE
    if rec["status"] != "APPROVED":
        raise err(ERR_INVALID_STATE, "REVOKE requires APPROVED")
    # Blocked if bound to a live USE_AS_IS NCR (PRD 3.9).
    for ncr in db.nonconformance_reports.values():
        if (ncr["deviation_id"] == rec["id"] and ncr["disposition"] == "USE_AS_IS"
                and ncr["status"] not in {"CLOSED", "VOID"}):
            raise err(ERR_DEVIATION_IN_USE, "Deviation is in live use")
    rec["status"] = "REVOKED"
    touch(rec)
    return success(deviation_out(rec))


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_MANAGER})
    body = request.get_json(silent=True) or {}
    require_fields(body, ["to_iso8601"])
    new_clock = parse_iso(body["to_iso8601"])
    db.set_clock(new_clock)

    # Sweep: every APPROVED deviation whose valid_to <= clock -> EXPIRED.
    for dev in db.deviations.values():
        if dev["status"] == "APPROVED" and new_clock >= dev["valid_to_dt"]:
            dev["status"] = "EXPIRED"
            touch(dev)

    return success({})
