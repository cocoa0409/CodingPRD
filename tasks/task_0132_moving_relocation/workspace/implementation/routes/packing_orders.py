"""PackingOrder routes (PRD §3.3).

packing_total_cents recomputed at creation and on every amendment:
round_half_up(sum(line.qty*line.unit_price_cents) + crate_count*9500).
"""
from flask import Blueprint, request

import db
from errors import err
from middleware import authenticate, require_roles
from response import object_response, array_response
from serialize import public, public_list
from services import common
from services import calculations

bp = Blueprint("packing_orders", __name__)


def _validate_packing_lines(lines):
    if not isinstance(lines, list):
        raise err("ERR_INVALID_FIELD", "packing_lines must be an array.")
    for line in lines:
        if not isinstance(line, dict):
            raise err("ERR_INVALID_FIELD", "each packing line must be an object.")
        for f in ("material_code", "quantity", "unit_price_cents"):
            if f not in line or line[f] is None:
                raise err("ERR_VALIDATION", "packing line missing field: %s" % f)
        if not common.is_int(line["quantity"]) or line["quantity"] < 0:
            raise err("ERR_INVALID_FIELD", "packing line quantity must be a non-negative integer.")
        if not common.is_int(line["unit_price_cents"]) or line["unit_price_cents"] < 0:
            raise err("ERR_INVALID_FIELD", "packing line unit_price_cents must be a non-negative integer.")
    return lines


@bp.route("/packing-orders", methods=["POST"])
def create_packing_order():
    user_id, role = authenticate()
    require_roles(role, {"Estimator", "PlatformAdmin"})
    body = common.get_json_body()
    common.require_fields(body, ["move_job_id", "packing_lines"])

    common.lookup_fk(db.move_jobs, body["move_job_id"])

    crate_count = body.get("crate_count", 0)
    if crate_count is None:
        crate_count = 0
    if not common.is_int(crate_count) or crate_count < 0:
        raise err("ERR_INVALID_FIELD", "crate_count must be a non-negative integer.")
    lines = _validate_packing_lines(body["packing_lines"])

    total = calculations.packing_total(crate_count, lines)
    record = db.new_common({
        "move_job_id": body["move_job_id"],
        "crate_count": crate_count,
        "packing_lines": lines,
        "packing_total_cents": total,
    })
    db.packing_orders[record["id"]] = record
    return object_response(public(record), 201)


@bp.route("/packing-orders/<pid>", methods=["GET"])
def get_packing_order(pid):
    user_id, role = authenticate()
    require_roles(role, {"Estimator", "PlatformAdmin", "Customer"})
    record = common.lookup(db.packing_orders, pid)
    return object_response(public(record), 200)


@bp.route("/packing-orders", methods=["GET"])
def list_packing_orders():
    user_id, role = authenticate()
    require_roles(role, {"Estimator", "PlatformAdmin", "Customer"})
    limit, offset = common.parse_pagination()
    move_job_id = request.args.get("move_job_id")
    records = list(db.packing_orders.values())
    if move_job_id is not None:
        records = [r for r in records if r["move_job_id"] == move_job_id]
    page, total = common.paginate(records, limit, offset)
    return array_response(public_list(page), limit, offset, total, 200)


@bp.route("/packing-orders/<pid>", methods=["PATCH"])
def update_packing_order(pid):
    user_id, role = authenticate()
    require_roles(role, {"Estimator", "PlatformAdmin"})
    record = common.lookup(db.packing_orders, pid)
    body = common.get_json_body()

    if "crate_count" in body and body["crate_count"] is not None:
        if not common.is_int(body["crate_count"]) or body["crate_count"] < 0:
            raise err("ERR_INVALID_FIELD", "crate_count must be a non-negative integer.")
        record["crate_count"] = body["crate_count"]
    if "packing_lines" in body and body["packing_lines"] is not None:
        record["packing_lines"] = _validate_packing_lines(body["packing_lines"])

    record["packing_total_cents"] = calculations.packing_total(
        record["crate_count"], record["packing_lines"]
    )
    db.touch(record)
    return object_response(public(record), 200)
