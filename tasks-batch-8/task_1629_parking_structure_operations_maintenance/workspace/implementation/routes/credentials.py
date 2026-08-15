"""Credential endpoints (PRD 3.4)."""
from flask import Blueprint, request

import db
from errors import (
    err_invalid_state, err_not_owner,
    err_agreement_not_issuable, err_credential_limit,
)
from middleware import get_actor, require_roles, ALL_ROLES
from response import success_object, success_list
from services.common import (
    body, require_enum, require_int, parse_pagination, paginate,
    require_ref, get_credential, public_view,
)

bp = Blueprint("credentials", __name__)

CREDENTIAL_TYPES = {"BADGE", "TRANSPONDER"}


def _check_parker_ownership(actor, credential):
    if actor.role == "MonthlyParker":
        agreement = db.monthly_agreements.get(credential["agreement_id"])
        if agreement is None or agreement["parker_account_id"] != actor.user_id:
            raise err_not_owner("a parker may act only on their own credentials")


@bp.post("/ops/credentials")
def create_credential():
    actor = get_actor()
    require_roles(actor, ["ParkingAttendant"])
    payload = body()
    agreement = require_ref(payload, db.monthly_agreements, "agreement_id")
    ctype = require_enum(payload, "credential_type", CREDENTIAL_TYPES)
    deposit = require_int(payload, "deposit_cents", minimum=0)
    if agreement["agreement_status"] not in ("APPROVED", "ACTIVE"):
        raise err_agreement_not_issuable()
    live_count = sum(
        1 for c in db.credentials.values()
        if c["agreement_id"] == agreement["id"]
        and c["credential_status"] in ("ACTIVE", "LOST_REPORTED")
    )
    if live_count >= 2:
        raise err_credential_limit()
    ent = {
        "id": db.new_id(),
        "agreement_id": agreement["id"],
        "credential_type": ctype,
        "credential_status": "ACTIVE",
        "deposit_cents": deposit,
        "replaced_by_credential_id": None,
    }
    db.stamp_new(ent)
    db.credentials[ent["id"]] = ent
    facility = db.facilities[agreement["facility_id"]]
    facility["deposit_liability_cents"] += deposit
    db.touch_ledger(facility)
    return success_object(public_view(ent), status=201)


@bp.get("/ops/credentials/<credential_id>")
def get_credential_route(credential_id):
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    return success_object(public_view(get_credential(credential_id)))


@bp.get("/ops/credentials")
def list_credentials():
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.credentials.values())
    agreement_id = request.args.get("agreement_id")
    credential_status = request.args.get("credential_status")
    replaced_by = request.args.get("replaced_by_credential_id")
    if agreement_id is not None:
        items = [c for c in items if c["agreement_id"] == agreement_id]
    if credential_status is not None:
        items = [c for c in items if c["credential_status"] == credential_status]
    if replaced_by is not None:
        items = [c for c in items if c.get("replaced_by_credential_id") == replaced_by]
    page, total = paginate(items, limit, offset)
    return success_list([public_view(c) for c in page], limit, offset, total)


@bp.post("/ops/credentials/<credential_id>/report-lost")
def report_lost(credential_id):
    actor = get_actor()
    require_roles(actor, ["MonthlyParker", "ParkingAttendant"])
    cred = get_credential(credential_id)
    _check_parker_ownership(actor, cred)
    if cred["credential_status"] != "ACTIVE":
        raise err_invalid_state("only an ACTIVE credential may be reported lost")
    cred["credential_status"] = "LOST_REPORTED"
    db.touch(cred)
    return success_object(public_view(cred))


@bp.post("/ops/credentials/<credential_id>/report-found")
def report_found(credential_id):
    actor = get_actor()
    require_roles(actor, ["MonthlyParker", "ParkingAttendant"])
    cred = get_credential(credential_id)
    _check_parker_ownership(actor, cred)
    if cred["credential_status"] != "LOST_REPORTED":
        raise err_invalid_state("only a LOST_REPORTED credential may be reported found")
    cred["credential_status"] = "ACTIVE"
    db.touch(cred)
    return success_object(public_view(cred))


@bp.post("/ops/credentials/<credential_id>/replace")
def replace_credential(credential_id):
    actor = get_actor()
    require_roles(actor, ["ParkingAttendant"])
    cred = get_credential(credential_id)
    payload = body()
    ctype = require_enum(payload, "credential_type", CREDENTIAL_TYPES)
    if cred["credential_status"] not in ("ACTIVE", "LOST_REPORTED"):
        raise err_invalid_state("only an ACTIVE or LOST_REPORTED credential may be replaced")
    successor = {
        "id": db.new_id(),
        "agreement_id": cred["agreement_id"],
        "credential_type": ctype,
        "credential_status": "ACTIVE",
        "deposit_cents": cred["deposit_cents"],
        "replaced_by_credential_id": None,
    }
    db.stamp_new(successor)
    db.credentials[successor["id"]] = successor
    cred["credential_status"] = "REPLACED"
    cred["replaced_by_credential_id"] = successor["id"]
    db.touch(cred)
    # deposit carries over: Facility.deposit_liability_cents unchanged
    return success_object(public_view(successor))


@bp.post("/ops/credentials/<credential_id>/return")
def return_credential(credential_id):
    actor = get_actor()
    require_roles(actor, ["ParkingAttendant"])
    cred = get_credential(credential_id)
    if cred["credential_status"] not in ("ACTIVE", "LOST_REPORTED"):
        raise err_invalid_state("only an ACTIVE or LOST_REPORTED credential may be returned")
    cred["credential_status"] = "RETURNED"
    db.touch(cred)
    agreement = db.monthly_agreements[cred["agreement_id"]]
    facility = db.facilities[agreement["facility_id"]]
    facility["deposit_liability_cents"] -= cred["deposit_cents"]
    db.touch_ledger(facility)
    return success_object(public_view(cred))


@bp.post("/ops/credentials/<credential_id>/revoke")
def revoke_credential(credential_id):
    actor = get_actor()
    require_roles(actor, ["ParkingAttendant", "FacilityManager"])
    cred = get_credential(credential_id)
    if cred["credential_status"] not in ("ACTIVE", "LOST_REPORTED"):
        raise err_invalid_state("only an ACTIVE or LOST_REPORTED credential may be revoked")
    cred["credential_status"] = "REVOKED"
    db.touch(cred)
    agreement = db.monthly_agreements[cred["agreement_id"]]
    facility = db.facilities[agreement["facility_id"]]
    facility["deposit_liability_cents"] -= cred["deposit_cents"]
    db.touch_ledger(facility)
    return success_object(public_view(cred))
