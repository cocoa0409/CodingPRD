"""Complaints, investigation, resolution, and the contagion cascade (PRD §3.8)."""

from flask import request

import services as svc
from db import STORE, bump, logical_now, new_record
from errors import ApiError
from middleware import ALL_ROLES, endpoint
from response import list_response, ok_object
from routes import bp
from serializers import complaint_out
from util import (
    COMPLAINT_TYPES,
    VERDICTS,
    as_enum,
    as_positive_int,
    as_string,
    body_dict,
    opt_present,
    req_present,
)

COMPLAINT_READ_ROLES = {"PlantManager", "ProductionPlanner", "QATechnician", "QAManager", "CoPackCustomer"}


@bp.route("/plant/complaints", methods=["POST"])
@endpoint({"QATechnician", "CoPackCustomer"})
def create_complaint(user_id, role):
    body = body_dict(request.get_json(silent=True))
    # minimal shape needed for the customer-scope check (stage 4) first
    lot_id = as_string(req_present(body, "lot_id"), "lot_id")

    lot = svc.require_record("lots", lot_id, "FinishedGoodsLot")
    if role == "CoPackCustomer":
        order = svc.order_of_lot(lot)
        svc.assert_customer_scope(user_id, order)

    # remaining shape (stage 5)
    complaint_type = as_enum(
        req_present(body, "complaint_type"), "complaint_type", COMPLAINT_TYPES
    )
    units_affected = as_positive_int(req_present(body, "units_affected"), "units_affected")

    # state (stage 8): lot must be complainable
    if lot["release_status"] not in ("RELEASED", "QUARANTINED", "DEPLETED"):
        raise ApiError(
            "ERR_LOT_STATE",
            "Complaints are accepted only on RELEASED, QUARANTINED or DEPLETED lots",
        )
    # aggregate fiscal check (stage 12)
    if units_affected > lot["cases_produced"]:
        raise ApiError(
            "ERR_COMPLAINT_UNITS_INVALID", "units_affected exceeds the lot's cases_produced"
        )

    rec = new_record()
    rec.update(
        lot_id=lot["id"],
        complaint_type=complaint_type,
        units_affected=units_affected,
        reported_by_user_id=user_id,
        reported_at=logical_now(),
        status="OPEN",
    )
    STORE["complaints"][rec["id"]] = rec
    return ok_object(complaint_out(rec), 201)


@bp.route("/plant/complaints", methods=["GET"])
@endpoint(COMPLAINT_READ_ROLES)
def list_complaints(user_id, role):
    lot_id = request.args.get("lot_id")
    status = request.args.get("status")
    recs = list(STORE["complaints"].values())
    if role == "CoPackCustomer":
        if lot_id is not None:
            lot = STORE["lots"].get(lot_id)
            if lot is not None:
                svc.assert_customer_scope(user_id, svc.order_of_lot(lot))
        recs = [
            c
            for c in recs
            if (
                STORE["lots"].get(c["lot_id"]) is not None
                and svc.order_of_lot(STORE["lots"][c["lot_id"]]) is not None
                and svc.order_of_lot(STORE["lots"][c["lot_id"]])["copack_customer_id"] == user_id
            )
        ]
    if lot_id is not None:
        recs = [c for c in recs if c["lot_id"] == lot_id]
    if status is not None:
        recs = [c for c in recs if c["status"] == status]
    return list_response(recs, complaint_out)


@bp.route("/plant/complaints/<complaintId>", methods=["GET"])
@endpoint(COMPLAINT_READ_ROLES)
def get_complaint(user_id, role, complaintId):
    complaint = svc.require_record("complaints", complaintId, "Complaint")
    if role == "CoPackCustomer":
        lot = STORE["lots"].get(complaint["lot_id"])
        svc.assert_customer_scope(user_id, svc.order_of_lot(lot) if lot else None)
    return ok_object(complaint_out(complaint))


@bp.route("/plant/lots/<lotId>/complaints", methods=["GET"])
@endpoint(ALL_ROLES)
def list_lot_complaints(user_id, role, lotId):
    lot = svc.require_record("lots", lotId, "FinishedGoodsLot")
    if role == "CoPackCustomer":
        svc.assert_customer_scope(user_id, svc.order_of_lot(lot))
    return list_response(svc.complaints_of_lot(lotId), complaint_out)


@bp.route("/plant/complaints/<complaintId>/investigate", methods=["POST"])
@endpoint({"QATechnician"})
def investigate_complaint(user_id, role, complaintId):
    complaint = svc.require_record("complaints", complaintId, "Complaint")
    if complaint["status"] != "OPEN":
        raise ApiError("ERR_COMPLAINT_STATE", "Only an OPEN complaint can be investigated")
    complaint["status"] = "UNDER_INVESTIGATION"
    bump(complaint)
    return ok_object(complaint_out(complaint))


@bp.route("/plant/complaints/<complaintId>/resolve", methods=["POST"])
@endpoint({"QAManager"})
def resolve_complaint(user_id, role, complaintId):
    complaint = svc.require_record("complaints", complaintId, "Complaint")
    # segregation of duties (stage 3): resolver differs from the reporter
    if complaint["reported_by_user_id"] == user_id:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES", "The resolver must differ from the complaint reporter"
        )
    body = body_dict(request.get_json(silent=True))
    verdict = as_enum(req_present(body, "verdict"), "verdict", VERDICTS)
    notes = opt_present(body, "notes")
    if notes is not None:
        as_string(notes, "notes")

    if complaint["status"] != "UNDER_INVESTIGATION":
        raise ApiError(
            "ERR_COMPLAINT_STATE", "Only an UNDER_INVESTIGATION complaint can be resolved"
        )

    if verdict == "VALID":
        complaint["status"] = "RESOLVED_VALID"
        bump(complaint)
        # hop 1 (valid_complaint_count) is derived from RESOLVED_VALID complaints;
        # hops 2-3 run against the post-resolution state.
        svc.complaint_contagion(complaint)
    else:
        complaint["status"] = "RESOLVED_INVALID"
        bump(complaint)
    return ok_object(complaint_out(complaint))
