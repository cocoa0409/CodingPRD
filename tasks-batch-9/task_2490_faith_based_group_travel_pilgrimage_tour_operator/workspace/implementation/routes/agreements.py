"""Group leader agreements (PRD section 3.4)."""

from flask import Blueprint

import core
import response
from db import db, lock
from errors import err
from middleware import (ROLE_FINANCE_CONTROLLER, ROLE_GROUP_LEADER, ROLE_PROGRAM_MANAGER,
                        authorize)
from validate import (apply_filters, body_of, opt_enum, pagination, req_enum, req_id, req_int,
                      req_str)

bp = Blueprint("agreements", __name__)

READ_ROLES = (ROLE_PROGRAM_MANAGER, ROLE_FINANCE_CONTROLLER, ROLE_GROUP_LEADER)


def _load(agreement_id):
    row = db.agreements.get(agreement_id)
    if row is None:
        err("ERR_AGREEMENT_NOT_FOUND", "Group leader agreement %s does not exist." % agreement_id)
    return row


@bp.route("/group-leader-agreements", methods=["POST"])
def create_agreement():
    authorize((ROLE_PROGRAM_MANAGER,))
    body = body_of()
    with lock:
        departure_id = req_id(body, "departure_id")
        leader_name = req_str(body, "leader_name", 1, 120)
        leader_user_id = req_str(body, "leader_user_id", 1, 64)
        free_travel_threshold = req_int(body, "free_travel_threshold", 1, 60)
        commission_mode = req_enum(body, "commission_mode", core.COMMISSION_MODES)
        commission_rate = req_int(body, "commission_rate_cents_per_pax", 0, 100000)
        accrual_basis = opt_enum(body, "accrual_basis", core.ACCRUAL_BASES, "RECRUITED")
        expected_departure_version = req_int(body, "expected_departure_version")

        departure = db.departures.get(departure_id)
        if departure is None:
            err("ERR_DEPARTURE_NOT_FOUND", "Departure %s does not exist." % departure_id)
        if departure["status"] not in ("PLANNING", "OPEN_FOR_SALE"):
            err("ERR_DEPARTURE_INVALID_STATE",
                "A leader agreement can only be offered on a PLANNING or OPEN_FOR_SALE departure.")
        if expected_departure_version != departure["version"]:
            err("ERR_STALE_DEPARTURE_VERSION",
                "expected_departure_version %d does not match the stored version %d."
                % (expected_departure_version, departure["version"]))

        row = core.base_row()
        row.update({
            "departure_id": departure_id,
            "leader_name": leader_name,
            "leader_user_id": leader_user_id,
            "free_travel_threshold": free_travel_threshold,
            "commission_mode": commission_mode,
            "commission_rate_cents_per_pax": commission_rate,
            "accrual_basis": accrual_basis,
            "status": "PENDING_COUNTERSIGN",
            "recruited_paying_count": 0,
            "earned_free_seats": 0,
            "free_seats_granted_count": 0,
            "commission_payable_cents": 0,
            "settled_recruited_count": 0,
            "settled_earned_free_seats": 0,
            "settled_commission_cents": 0,
            "superseded_by_agreement_id": None,
        })

        # (departure_id, leader_user_id) is the supersede key.
        for prior in core.agreements_of_departure(departure_id):
            if prior["leader_user_id"] != leader_user_id:
                continue
            if prior["status"] not in ("PENDING_COUNTERSIGN", "ACTIVE"):
                continue
            prior["status"] = "TERMINATED"
            prior["superseded_by_agreement_id"] = row["id"]
            core.touch(prior)

        db.agreements[row["id"]] = row
        core.touch(departure)
        return response.ok(core.serialize(row), 201)


@bp.route("/group-leader-agreements/<agreement_id>", methods=["GET"])
def get_agreement(agreement_id):
    caller = authorize(READ_ROLES)
    with lock:
        row = _load(agreement_id)
        if caller.is_group_leader and caller.user_id != row["id"]:
            err("ERR_UNAUTHORIZED", "A group leader may only read their own agreement.")
        return response.ok(core.serialize(row))


@bp.route("/group-leader-agreements", methods=["GET"])
def list_agreements():
    caller = authorize(READ_ROLES)
    with lock:
        limit, offset = pagination()
        rows = core.order_rows(list(db.agreements.values()))
        if caller.is_group_leader:
            rows = [r for r in rows if r["id"] == caller.user_id]
        rows = apply_filters(rows, {
            "departure_id": "departure_id",
            "superseded_by_agreement_id": "superseded_by_agreement_id",
            "status": "status",
        })
        page, total = core.paginate(rows, limit, offset)
        return response.ok_list([core.serialize(r) for r in page], limit, offset, total)


@bp.route("/group-leader-agreements/<agreement_id>/countersign", methods=["POST"])
def countersign(agreement_id):
    caller = authorize((ROLE_GROUP_LEADER,))
    with lock:
        if caller.user_id != agreement_id:
            err("ERR_UNAUTHORIZED", "A group leader may only countersign their own agreement.")
        row = _load(agreement_id)
        if row["status"] != "PENDING_COUNTERSIGN":
            err("ERR_AGREEMENT_INVALID_STATE",
                "Only a PENDING_COUNTERSIGN agreement can be countersigned.")
        row["status"] = "ACTIVE"
        core.recompute_accrual_snapshot(row)
        core.touch(row)
        return response.ok(core.serialize(row))


@bp.route("/group-leader-agreements/<agreement_id>/settle", methods=["POST"])
def settle(agreement_id):
    authorize((ROLE_FINANCE_CONTROLLER,))
    with lock:
        row = _load(agreement_id)
        departure = db.departures.get(row["departure_id"])
        if departure is not None and departure["status"] not in ("SALES_CLOSED", "OPERATED"):
            err("ERR_DEPARTURE_INVALID_STATE",
                "Settlement requires the departure to be SALES_CLOSED or OPERATED.")
        if row["status"] != "ACTIVE":
            err("ERR_AGREEMENT_INVALID_STATE", "Only an ACTIVE agreement can be settled.")
        core.recompute_accrual_settlement(row)
        row["status"] = "SETTLED"
        core.touch(row)
        return response.ok(core.serialize(row))
