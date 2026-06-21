"""TurnoverProject routes (PRD §3.9) — open, get, list, start, complete."""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import require_role, get_json_body
from response import object_response, array_response
from services.common import (
    serialize, require_string, require_int, optional_int, require_iso_date,
    parse_pagination, paginate, filter_param, parse_date,
)
from services import domain

bp = Blueprint("turnovers", __name__)


@bp.route("/turnovers", methods=["POST"])
def create_turnover():
    require_role({"PropertyManager"})
    body = get_json_body()
    unit_id = require_string(body, "unit_id")
    opened_date = require_iso_date(body, "opened_date")
    target_ready_date = require_iso_date(body, "target_ready_date")
    make_ready = optional_int(body, "make_ready_cost_cents", 0, minimum=0)
    # target_ready_date >= opened_date (request-shape constraint).
    if parse_date(target_ready_date) < parse_date(opened_date):
        raise err(errors.ERR_INVALID_REQUEST, "target_ready_date must be >= opened_date")
    with db.LOCK:
        if unit_id not in db.units:
            raise err(errors.ERR_FK_NOT_FOUND, "unit_id does not resolve")
        common = db.new_common()
        record = {
            **{k: common[k] for k in ("id", "created_at", "updated_at", "version", "_seq")},
            "unit_id": unit_id,
            "opened_date": opened_date,
            "target_ready_date": target_ready_date,
            "make_ready_cost_cents": make_ready,
            "status": "OPEN",
        }
        db.turnovers[record["id"]] = record
        return object_response(serialize(record), 201)


@bp.route("/turnovers/<id>", methods=["GET"])
def get_turnover(id):
    require_role({"PropertyManager", "Owner"})
    with db.LOCK:
        record = db.turnovers.get(id)
        if record is None:
            raise err(errors.ERR_NOT_FOUND, "Turnover not found")
        return object_response(serialize(record), 200)


@bp.route("/turnovers", methods=["GET"])
def list_turnovers():
    require_role({"PropertyManager", "Owner"})
    unit_id = filter_param(request.args, "unit_id")
    status = filter_param(request.args, "status")
    limit, offset = parse_pagination(request.args)
    with db.LOCK:
        records = list(db.turnovers.values())
        if unit_id is not None:
            records = [r for r in records if r["unit_id"] == unit_id]
        if status is not None:
            records = [r for r in records if r["status"] == status]
        items, total = paginate(records, limit, offset)
        return array_response(items, limit, offset, total, 200)


@bp.route("/turnovers/<id>/start", methods=["POST"])
def start_turnover(id):
    require_role({"PropertyManager"})
    with db.LOCK:
        tp = db.turnovers.get(id)
        if tp is None:
            raise err(errors.ERR_NOT_FOUND, "Turnover not found")
        if tp["status"] != "OPEN":
            raise err(errors.ERR_INVALID_STATE, "Turnover is not OPEN")
        tp["status"] = "IN_PROGRESS"
        db.touch(tp)
        return object_response(serialize(tp), 200)


@bp.route("/turnovers/<id>/complete", methods=["POST"])
def complete_turnover(id):
    require_role({"PropertyManager"})
    with db.LOCK:
        tp = db.turnovers.get(id)
        if tp is None:
            raise err(errors.ERR_NOT_FOUND, "Turnover not found")
        # State-admissibility (priority 7) precedes open-work-order (13) and
        # trust solvency (14).
        if tp["status"] != "IN_PROGRESS":
            raise err(errors.ERR_INVALID_STATE, "Turnover is not IN_PROGRESS")
        unit = db.units.get(tp["unit_id"])
        # Open work orders on the unit block completion.
        for wo in db.work_orders.values():
            if wo["unit_id"] == tp["unit_id"] and wo["status"] in ("OPEN", "ASSIGNED"):
                raise err(errors.ERR_OPEN_WORK_ORDERS,
                          "Unit has open/assigned work orders")
        # Trust solvency (last guard): debit make-ready before mutating turnover.
        if tp["make_ready_cost_cents"] > 0:
            prop = domain.property_of_unit(unit)
            if prop is not None:
                domain.debit_trust(prop, tp["make_ready_cost_cents"])
        tp["status"] = "READY"
        db.touch(tp)
        # Unit returns to VACANT_READY.
        if unit is not None:
            unit["occupancy_status"] = "VACANT_READY"
            db.touch(unit)
        return object_response(serialize(tp), 200)
