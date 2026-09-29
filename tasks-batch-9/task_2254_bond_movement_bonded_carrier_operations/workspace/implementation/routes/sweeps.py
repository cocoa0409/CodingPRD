"""The deterministic compliance sweep (PRD 3.6)."""
from flask import Blueprint, request

from db import db, new_record, touch
from middleware import ALL_ROLES, require
from response import ok, ok_list, read_pagination, window
from services import calc, domain
import validate as v

bp = Blueprint("sweeps", __name__)


@bp.route("/in-bond/compliance-sweeps", methods=["POST"])
def run_sweep():
    user_id, _role = require("CBPOfficer")
    body = v.get_body()
    note = v.opt_str(body, "note")

    now = db.now
    overdue_ids = []
    bonds_expired = 0
    general_order = 0

    # Pass 1 - movements past their deadline go overdue.
    for movement in domain.rows(db.movements):
        if movement["transit_status"] != "IN_TRANSIT":
            continue
        if movement["transit_deadline_utc"] >= now:
            continue
        movement["transit_status"] = "OVERDUE"
        movement["overdue_days"] = calc.overdue_days_measure(
            movement["transit_deadline_utc"], now)
        touch(movement)
        overdue_ids.append(movement["id"])

    # Pass 2 - lapsed bonds expire.
    for bond in domain.rows(db.bonds):
        if bond["status"] == "EXPIRED" or bond["expiry_date"] >= now:
            continue
        bond["status"] = "EXPIRED"
        touch(bond)
        bonds_expired += 1

    # Pass 3 - arrived but unentered cargo goes to general order.
    for movement in domain.rows(db.movements):
        if movement["transit_status"] != "ARRIVED":
            continue
        if movement["custody_status"] not in ("BONDED", "EXAM_HOLD"):
            continue
        deadline = movement["go_deadline_utc"]
        if deadline is None or now < deadline:
            continue
        port = db.ports.get(movement["destination_port_id"])
        if port is None or not port["go_warehouse_available"]:
            continue
        movement["custody_status"] = "GENERAL_ORDER"
        touch(movement)
        general_order += 1

    # Pass 4 - every carrier's decayed sanction score is re-valued.
    for carrier in domain.rows(db.carriers):
        domain.recompute_sanctions(carrier)

    rec = new_record(full=False)
    rec.update({
        "run_at": now,
        "executed_by_officer_id": user_id,
        "overdue_marked_count": len(overdue_ids),
        "bonds_expired_count": bonds_expired,
        "general_order_count": general_order,
        "overdue_movement_ids": overdue_ids,
        "note": note,
    })
    db.sweeps[rec["id"]] = rec
    return ok(domain.sweep_json(rec), 201)


@bp.route("/in-bond/compliance-sweeps", methods=["GET"])
def list_sweeps():
    require(*ALL_ROLES)
    limit, offset = read_pagination(request.args)
    items = sorted(db.sweeps.values(), key=lambda s: (s["run_at"], s["_seq"]),
                   reverse=True)
    total = len(items)
    page = window(items, limit, offset)
    return ok_list([domain.sweep_json(s) for s in page], limit, offset, total)
