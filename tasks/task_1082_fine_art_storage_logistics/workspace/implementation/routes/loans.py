"""Routes: loan agreements (cyclic, SoD-guarded) and customs carnets."""
import uuid

from flask import Blueprint, request

import store
from store import db, new_record, touch, serialize
from common import (auth, require_auth, require_role, get_body, require_fields,
                    check_enum, require_int, require_bool, get_or_404, fk_or_404, paginate)
from envelope import object_response, list_response
from errors import err
from timeutil import parse_dt
import domain

bp = Blueprint("loans", __name__)

LOAN_STATES = {"DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "ACTIVE", "RETURNED", "CANCELLED"}
CARNET_STATES = {"ISSUED", "ACTIVATED", "DISCHARGED", "EXPIRED"}

# role required to drive each loan target state
ROLE_FOR_TARGET = {
    "SUBMITTED": "Registrar",
    "DRAFT": "Registrar",
    "APPROVED": "Approver",
    "REJECTED": "Approver",
    "CANCELLED": "Approver",
    "ACTIVE": "Coordinator",
    "RETURNED": "Coordinator",
}

LOAN_TRANSITIONS = {
    ("DRAFT", "SUBMITTED"),
    ("SUBMITTED", "DRAFT"),
    ("SUBMITTED", "APPROVED"),
    ("SUBMITTED", "REJECTED"),
    ("APPROVED", "ACTIVE"),
    ("APPROVED", "CANCELLED"),
    ("ACTIVE", "RETURNED"),
}


# ---------------------------------------------------------------------------
# Loan agreements
# ---------------------------------------------------------------------------
@bp.route("/loans", methods=["POST"])
def create_loan():
    auth(["Registrar"])
    body = get_body()
    fk_or_404("artworks", body.get("artwork_id"))
    fk_or_404("clients", body.get("client_id"))
    require_fields(body, ["artwork_id", "client_id", "borrower_name", "exhibition_name",
                          "loan_start", "loan_end", "is_international", "required_value_cents"])
    require_bool(body, "is_international")
    require_int(body, "required_value_cents")
    start = parse_dt(body["loan_start"])
    end = parse_dt(body["loan_end"])
    if not end > start:
        raise err("ERR_TIME_WINDOW_INVALID", "loan_end must be after loan_start")
    rec = new_record({
        "artwork_id": body["artwork_id"],
        "client_id": body["client_id"],
        "borrower_name": body["borrower_name"],
        "exhibition_name": body["exhibition_name"],
        "loan_start": body["loan_start"],
        "loan_end": body["loan_end"],
        "is_international": body["is_international"],
        "required_value_cents": body["required_value_cents"],
        "submitted_by_user_id": None,
        "coa_issued": False,
        "coa_number": None,
        "status": "DRAFT",
    })
    db["loans"][rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/loans/<rid>/state", methods=["POST"])
def loan_state(rid):
    uid, role = require_auth()
    require_role(role, ["Registrar", "Approver", "Coordinator"])
    loan = get_or_404("loans", rid)
    body = get_body()
    require_fields(body, ["to_status"])
    to_status = body["to_status"]
    check_enum(to_status, LOAN_STATES, "to_status")
    # per-transition role (authorization) before state-legality
    if role != ROLE_FOR_TARGET[to_status]:
        raise err("ERR_UNAUTHORIZED", "role %s may not drive loan to %s" % (role, to_status))
    cur = loan["status"]
    if (cur, to_status) not in LOAN_TRANSITIONS:
        raise err("ERR_INVALID_STATE", "cannot move loan from %s to %s" % (cur, to_status))

    artwork = db["artworks"].get(loan["artwork_id"])

    if to_status == "SUBMITTED":
        loan["submitted_by_user_id"] = uid
        loan["status"] = "SUBMITTED"
        touch(loan)
    elif to_status == "DRAFT":
        loan["status"] = "DRAFT"
        touch(loan)
    elif to_status == "APPROVED":
        _approve_loan(loan, artwork, uid)
    elif to_status == "REJECTED":
        loan["status"] = "REJECTED"
        touch(loan)
    elif to_status == "ACTIVE":
        _activate_loan(loan, artwork)
    elif to_status == "RETURNED":
        _return_loan(loan, artwork)
    elif to_status == "CANCELLED":
        _cancel_loan(loan)
    return object_response(serialize(loan))


def _approve_loan(loan, artwork, uid):
    # 1. segregation of duties
    if uid == loan.get("submitted_by_user_id"):
        raise err("ERR_SEGREGATION_OF_DUTIES", "approver may not be the submitter")
    # 2. condition safety
    if artwork["condition_status"] == "MAJOR_DAMAGE":
        raise err("ERR_ARTWORK_CONDITION_UNSAFE", "artwork condition unsafe")
    # 3. custody availability
    if artwork["custody_status"] != "IN_STORAGE":
        raise err("ERR_ARTWORK_NOT_AVAILABLE", "artwork not available for loan")
    # 4. finalized appraisal exists
    if len(domain.finalized_appraisals_for(artwork["id"])) < 1:
        raise err("ERR_NO_FINALIZED_APPRAISAL", "no finalized appraisal for artwork")
    # 5. sufficient coverage
    policy = domain.active_policy_for(artwork["id"])
    if policy is None or policy["insured_value_cents"] < loan["required_value_cents"]:
        raise err("ERR_INSUFFICIENT_COVERAGE", "insufficient insurance coverage")
    loan["coa_issued"] = True
    loan["coa_number"] = "COA-" + uuid.uuid4().hex[:12].upper()
    loan["status"] = "APPROVED"
    touch(loan)


def _activate_loan(loan, artwork):
    clock = store.get_clock()
    # 1. custody availability
    if artwork["custody_status"] != "IN_STORAGE":
        raise err("ERR_ARTWORK_NOT_AVAILABLE", "artwork not available for loan")
    # 2. active, non-expired policy
    policy = domain.active_policy_for(artwork["id"])
    if policy is None:
        raise err("ERR_POLICY_NOT_ACTIVE", "no active policy for artwork")
    if clock > parse_dt(policy["effective_end"]):
        policy["status"] = "LAPSED"
        touch(policy)
        if artwork.get("active_policy_id") == policy["id"]:
            artwork["active_policy_id"] = None
            touch(artwork)
        raise err("ERR_POLICY_EXPIRED", "policy has expired")
    # 3. international -> valid carnet
    if loan["is_international"]:
        carnet = domain.carnet_for_loan(loan["id"], statuses=("ISSUED",))
        if carnet is None:
            raise err("ERR_CARNET_REQUIRED", "issued carnet required for international loan")
        if parse_dt(carnet["validity_end"]) < clock:
            raise err("ERR_CARNET_EXPIRED", "carnet validity has passed")
    # side effects
    loan["status"] = "ACTIVE"
    touch(loan)
    domain.artwork_go_on_loan(artwork)
    if loan["is_international"]:
        carnet["status"] = "ACTIVATED"
        touch(carnet)


def _return_loan(loan, artwork):
    domain.artwork_return_from_loan(artwork)
    carnet = domain.carnet_for_loan(loan["id"], statuses=("ISSUED", "ACTIVATED"))
    if carnet is not None:
        carnet["status"] = "DISCHARGED"
        touch(carnet)
    loan["status"] = "RETURNED"
    touch(loan)


def _cancel_loan(loan):
    carnet = domain.carnet_for_loan(loan["id"], statuses=("ISSUED", "ACTIVATED"))
    if carnet is not None:
        carnet["status"] = "DISCHARGED"
        touch(carnet)
    loan["status"] = "CANCELLED"
    touch(loan)


@bp.route("/loans/<rid>", methods=["GET"])
def get_loan(rid):
    uid, role = auth(["Registrar", "Approver", "Coordinator", "Client"])
    loan = get_or_404("loans", rid)
    if role == "Client" and loan["client_id"] != uid:
        raise err("ERR_OWNERSHIP_REQUIRED", "not your loan")
    return object_response(serialize(loan))


@bp.route("/loans", methods=["GET"])
def list_loans():
    uid, role = auth(["Registrar", "Approver", "Coordinator", "Client"])
    aid = request.args.get("artwork_id")
    cid = request.args.get("client_id")
    st = request.args.get("status")
    if role == "Client":
        if cid is not None and cid != uid:
            raise err("ERR_OWNERSHIP_REQUIRED", "not your client scope")
        cid = uid
    recs = [r for r in db["loans"].values()
            if (aid is None or r["artwork_id"] == aid)
            and (cid is None or r["client_id"] == cid)
            and (st is None or r["status"] == st)]
    items, limit, offset, total = paginate(recs)
    return list_response(items, limit, offset, total)


# ---------------------------------------------------------------------------
# Carnets
# ---------------------------------------------------------------------------
@bp.route("/carnets", methods=["POST"])
def create_carnet():
    auth(["Coordinator"])
    body = get_body()
    fk_or_404("loans", body.get("loan_id"))
    require_fields(body, ["loan_id", "carnet_number", "countries",
                          "validity_start", "validity_end"])
    if not isinstance(body["countries"], list):
        raise err("ERR_VALIDATION", "countries must be an array")
    start = parse_dt(body["validity_start"])
    end = parse_dt(body["validity_end"])
    if not end > start:
        raise err("ERR_TIME_WINDOW_INVALID", "validity_end must be after validity_start")
    rec = new_record({
        "loan_id": body["loan_id"],
        "carnet_number": body["carnet_number"],
        "countries": body["countries"],
        "validity_start": body["validity_start"],
        "validity_end": body["validity_end"],
        "status": "ISSUED",
    })
    db["carnets"][rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/carnets/<rid>/state", methods=["POST"])
def carnet_state(rid):
    auth(["Coordinator"])
    rec = get_or_404("carnets", rid)
    body = get_body()
    require_fields(body, ["to_status"])
    to_status = body["to_status"]
    check_enum(to_status, CARNET_STATES, "to_status")
    cur = rec["status"]
    allowed = {("ACTIVATED", "DISCHARGED"), ("ISSUED", "EXPIRED")}
    if (cur, to_status) not in allowed:
        raise err("ERR_INVALID_STATE", "cannot move carnet from %s to %s" % (cur, to_status))
    if to_status == "EXPIRED":
        if not parse_dt(rec["validity_end"]) < store.get_clock():
            raise err("ERR_INVALID_STATE", "carnet still within validity")
    rec["status"] = to_status
    touch(rec)
    return object_response(serialize(rec))


@bp.route("/carnets/<rid>", methods=["GET"])
def get_carnet(rid):
    auth(["Coordinator"])
    rec = get_or_404("carnets", rid)
    return object_response(serialize(rec))


@bp.route("/carnets", methods=["GET"])
def list_carnets():
    auth(["Coordinator"])
    lid = request.args.get("loan_id")
    st = request.args.get("status")
    recs = [r for r in db["carnets"].values()
            if (lid is None or r["loan_id"] == lid) and (st is None or r["status"] == st)]
    items, limit, offset, total = paginate(recs)
    return list_response(items, limit, offset, total)
