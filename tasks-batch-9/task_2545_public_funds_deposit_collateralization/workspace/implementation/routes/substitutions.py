"""Collateral substitution as a fork-join (PRD 3.6)."""

from flask import Blueprint

import db
import middleware as mw
from constants import (
    ROLE_BANK_COLLATERAL_OFFICER,
    ROLE_BANK_COMPLIANCE_OFFICER,
    ROLE_CUSTODIAN,
    ROLE_STATE_REGULATOR,
    ROLE_SYSTEM_OPERATOR,
    SUBSTITUTION_STATUSES,
)
from errors import fail
from response import list_response, record_response
from routes.collateral import pledgeable, price_is_stale
from services import calc, state

bp = Blueprint("substitutions", __name__)

READ_ROLES = (
    ROLE_STATE_REGULATOR,
    ROLE_BANK_COLLATERAL_OFFICER,
    ROLE_BANK_COMPLIANCE_OFFICER,
    ROLE_CUSTODIAN,
    ROLE_SYSTEM_OPERATOR,
)


@bp.post("/substitution-requests")
def open_request():
    user_id, _ = mw.authorize(ROLE_BANK_COLLATERAL_OFFICER)
    body = mw.body_json()
    agreement = mw.resolve_fk("pledge_agreements", body.get("pledge_agreement_id"))
    outgoing = mw.resolve_fk("pledge_allocations", body.get("outgoing_allocation_id"))
    incoming = mw.resolve_fk("collateral_assets", body.get("incoming_asset_id"))
    mw.req_id(body, "pledge_agreement_id")
    mw.req_id(body, "outgoing_allocation_id")
    mw.req_id(body, "incoming_asset_id")
    incoming_par = mw.req_int(body, "incoming_par_cents")
    depository = db.get("depositories", agreement["depository_id"])
    if depository is not None and depository["collateral_posture"] == "FROZEN":
        fail("ERR_DEPOSITORY_POSTURE_FROZEN")
    if agreement["status"] != "EXECUTED":
        fail("ERR_AGREEMENT_NOT_EXECUTED")
    if not pledgeable(incoming):
        fail("ERR_COLLATERAL_TYPE_INELIGIBLE")
    if incoming["custodian_id"] != agreement["custodian_id"]:
        fail("ERR_CUSTODIAN_MISMATCH")
    if incoming["depository_id"] != agreement["depository_id"]:
        fail("ERR_DEPOSITORY_MISMATCH")
    if outgoing["pledge_agreement_id"] != agreement["id"] or outgoing["status"] != "ACTIVE":
        fail("ERR_ALLOCATION_NOT_UNDER_AGREEMENT")
    if price_is_stale(incoming):
        fail("ERR_STALE_COLLATERAL_PRICE")
    record = db.new_record(
        {
            "pledge_agreement_id": agreement["id"],
            "outgoing_allocation_id": outgoing["id"],
            "incoming_asset_id": incoming["id"],
            "incoming_par_cents": incoming_par,
            "submitted_by_user_id": user_id,
            "compliance_approved_by_user_id": None,
            "compliance_approved_at": None,
            "custodian_acked_at": None,
            "value_adequacy_delta_cents": None,
            "status": "SUBMITTED",
            "rejection_reason": None,
            "settled_at": None,
        }
    )
    db.insert("substitution_requests", record)
    state.recompute_all()
    return record_response(record, 201)


@bp.get("/substitution-requests/<request_id>")
def read_request(request_id):
    mw.authorize(*READ_ROLES)
    return record_response(mw.resolve("substitution_requests", request_id))


@bp.get("/substitution-requests")
def list_requests():
    mw.authorize(*READ_ROLES)
    limit, offset = mw.page_params()
    agreement_id = mw.query_filter("pledge_agreement_id")
    outgoing_id = mw.query_filter("outgoing_allocation_id")
    incoming_id = mw.query_filter("incoming_asset_id")
    status_filter = mw.query_filter("status", SUBSTITUTION_STATUSES)
    records = db.rows("substitution_requests")
    if agreement_id is not None:
        records = [r for r in records if r["pledge_agreement_id"] == agreement_id]
    if outgoing_id is not None:
        records = [r for r in records if r["outgoing_allocation_id"] == outgoing_id]
    if incoming_id is not None:
        records = [r for r in records if r["incoming_asset_id"] == incoming_id]
    if status_filter is not None:
        records = [r for r in records if r["status"] == status_filter]
    return list_response(mw.paginate(records, limit, offset), limit, offset, len(records))


@bp.post("/substitution-requests/<request_id>/compliance-approve")
def compliance_approve(request_id):
    user_id, _ = mw.authorize(ROLE_BANK_COMPLIANCE_OFFICER)
    request_record = mw.resolve("substitution_requests", request_id)
    if request_record["status"] not in ("SUBMITTED", "CUSTODIAN_ACKED"):
        fail("ERR_INVALID_STATE")
    if user_id == request_record["submitted_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")
    incoming = db.get("collateral_assets", request_record["incoming_asset_id"])
    outgoing = db.get("pledge_allocations", request_record["outgoing_allocation_id"])
    incoming_value = 0
    if incoming is not None:
        incoming_value = calc.asset_value_of_par(incoming, request_record["incoming_par_cents"])
    outgoing_value = 0 if outgoing is None else outgoing["allocated_collateral_value_cents"]
    delta = incoming_value - outgoing_value
    if delta < 0:
        fail("ERR_SUBSTITUTION_VALUE_SHORTFALL")
    request_record["value_adequacy_delta_cents"] = delta
    request_record["compliance_approved_at"] = db.now_ts()
    request_record["compliance_approved_by_user_id"] = user_id
    if request_record["status"] == "CUSTODIAN_ACKED":
        request_record["status"] = "READY_TO_SETTLE"
    else:
        request_record["status"] = "COMPLIANCE_APPROVED"
    db.touch(request_record)
    state.recompute_all()
    return record_response(request_record)


@bp.post("/substitution-requests/<request_id>/custodian-ack")
def custodian_ack(request_id):
    user_id, _ = mw.authorize(ROLE_CUSTODIAN)
    request_record = mw.resolve("substitution_requests", request_id)
    agreement = db.get("pledge_agreements", request_record["pledge_agreement_id"])
    if agreement is not None and agreement["custodian_id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER")
    if request_record["status"] not in ("SUBMITTED", "COMPLIANCE_APPROVED"):
        fail("ERR_INVALID_STATE")
    incoming = db.get("collateral_assets", request_record["incoming_asset_id"])
    if incoming is not None and agreement is not None:
        if incoming["custodian_id"] != agreement["custodian_id"]:
            fail("ERR_CUSTODIAN_MISMATCH")
    request_record["custodian_acked_at"] = db.now_ts()
    if request_record["status"] == "COMPLIANCE_APPROVED":
        request_record["status"] = "READY_TO_SETTLE"
    else:
        request_record["status"] = "CUSTODIAN_ACKED"
    db.touch(request_record)
    state.recompute_all()
    return record_response(request_record)


@bp.post("/substitution-requests/<request_id>/settle")
def settle(request_id):
    user_id, _ = mw.authorize(ROLE_CUSTODIAN)
    request_record = mw.resolve("substitution_requests", request_id)
    agreement = db.get("pledge_agreements", request_record["pledge_agreement_id"])
    if agreement is not None and agreement["custodian_id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER")
    if request_record["status"] != "READY_TO_SETTLE":
        fail("ERR_INVALID_STATE")
    custodian = db.get("custodians", agreement["custodian_id"]) if agreement else None
    if custodian is None or custodian["approval_status"] != "APPROVED":
        fail("ERR_CUSTODIAN_NOT_ELIGIBLE")
    if custodian["tri_party_capable"] is not True:
        fail("ERR_CUSTODIAN_NOT_ELIGIBLE")
    incoming = db.get("collateral_assets", request_record["incoming_asset_id"])
    if incoming is None or not pledgeable(incoming):
        fail("ERR_COLLATERAL_TYPE_INELIGIBLE")
    outgoing = db.get("pledge_allocations", request_record["outgoing_allocation_id"])
    incoming_par = request_record["incoming_par_cents"]
    effective_from = db.now_ts()
    effective_to = db.SENTINEL_TS
    exclude = () if outgoing is None else (outgoing["id"],)
    if not state.par_capacity_available(
        incoming, effective_from.dt, effective_to.dt, incoming_par, exclude_ids=exclude
    ):
        fail("ERR_ALLOCATION_OVERSUBSCRIBED")
    # Hop one: the two equal and opposite legs.
    if outgoing is not None:
        outgoing["status"] = "SUBSTITUTED"
        outgoing["released_at"] = db.now_ts()
        outgoing["release_reason"] = "SUBSTITUTION_SETTLED"
        db.touch(outgoing)
    minted = db.new_record(
        {
            "pledge_agreement_id": request_record["pledge_agreement_id"],
            "collateral_asset_id": incoming["id"],
            "allocated_par_cents": incoming_par,
            "allocated_collateral_value_cents": calc.asset_value_of_par(incoming, incoming_par),
            "effective_from": effective_from,
            "effective_to": effective_to,
            "status": "ACTIVE",
            "released_at": None,
            "release_reason": None,
            "created_by_substitution_id": request_record["id"],
        }
    )
    db.insert("pledge_allocations", minted)
    request_record["status"] = "SETTLED"
    request_record["settled_at"] = db.now_ts()
    db.touch(request_record)
    # Hops two, three and four.
    state.recompute_all(apply_status=True)
    return record_response(request_record)


@bp.post("/substitution-requests/<request_id>/reject")
def reject(request_id):
    user_id, _ = mw.authorize(ROLE_BANK_COMPLIANCE_OFFICER)
    request_record = mw.resolve("substitution_requests", request_id)
    body = mw.body_json()
    reason = mw.req_text(body, "rejection_reason")
    if request_record["status"] not in ("SUBMITTED", "CUSTODIAN_ACKED"):
        fail("ERR_INVALID_STATE")
    if user_id == request_record["submitted_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")
    request_record["status"] = "REJECTED"
    request_record["rejection_reason"] = reason
    db.touch(request_record)
    state.recompute_all()
    return record_response(request_record)


@bp.post("/substitution-requests/<request_id>/withdraw")
def withdraw(request_id):
    user_id, _ = mw.authorize(ROLE_BANK_COLLATERAL_OFFICER)
    request_record = mw.resolve("substitution_requests", request_id)
    if request_record["status"] not in (
        "SUBMITTED",
        "COMPLIANCE_APPROVED",
        "CUSTODIAN_ACKED",
        "READY_TO_SETTLE",
    ):
        fail("ERR_INVALID_STATE")
    if user_id != request_record["submitted_by_user_id"]:
        fail("ERR_NOT_RESOURCE_OWNER")
    request_record["status"] = "WITHDRAWN"
    db.touch(request_record)
    state.recompute_all()
    return record_response(request_record)
