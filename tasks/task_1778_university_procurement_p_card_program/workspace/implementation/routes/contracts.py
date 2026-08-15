"""Contract lifecycle: draft, review/negotiation loop, execute (exclusivity +
supersede), amend (OCC-guarded), terminate (cascade) — PRD 3.2."""

import db
import services as svc
from middleware import authenticate, ROLES
from response import success_obj, success_list
from routes import make_blueprint
from util import (
    body_json,
    check_shape,
    pagination_params,
    paginate,
    apply_filters,
    require_fk,
    exist_body_fks,
    parse_dt,
)
from errors import (
    ApiError,
    ERR_CONTRACT_STATE_INVALID,
    ERR_CONTRACT_OVERLAP,
    ERR_VENDOR_SUSPENDED,
    ERR_INVALID_REQUEST,
    ERR_STALE_VERSION,
)

bp = make_blueprint("contracts")


def _check_period(start, end):
    if not parse_dt(start) < parse_dt(end):
        raise ApiError(ERR_INVALID_REQUEST, 400, "effective_start must be strictly before effective_end")


@bp.post("/contracts")
def create_contract():
    authenticate(["ContractOfficer"])
    body = body_json()
    # p3: body-referenced vendor existence precedes shape validation.
    exist_body_fks(body, {"vendor_id": "vendors"})
    check_shape(body, {
        "vendor_id": {"type": "string", "required": True},
        "commodity_code": {"type": "string", "required": True},
        "value_cents": {"type": "integer", "required": True},
        "effective_start": {"type": "datetime", "required": True},
        "effective_end": {"type": "datetime", "required": True},
        "terms_text": {"type": "string"},
    })
    _check_period(body["effective_start"], body["effective_end"])
    contract = db.new_entity("contracts", {
        "vendor_id": body["vendor_id"],
        "commodity_code": body["commodity_code"],
        "value_cents": body["value_cents"],
        "effective_start": body["effective_start"],
        "effective_end": body["effective_end"],
        "terms_text": body.get("terms_text"),
        "status": "DRAFT",
        "negotiation_round": 0,
        "supersedes_contract_id": None,
        "executed_at": None,
        "terminated_reason": None,
    })
    return success_obj(db.public(contract), 201)


@bp.get("/contracts")
def list_contracts():
    authenticate(ROLES)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("contracts"), ["vendor_id", "status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(c) for c in page], limit, offset, total, has_more)


@bp.get("/contracts/<cid>")
def get_contract(cid):
    authenticate(ROLES)
    contract = require_fk("contracts", cid)
    return success_obj(db.public(contract), 200)


@bp.post("/contracts/<cid>/submit-review")
def submit_review(cid):
    authenticate(["ContractOfficer"])
    contract = require_fk("contracts", cid)
    if contract["status"] not in ("DRAFT", "IN_NEGOTIATION"):
        raise ApiError(ERR_CONTRACT_STATE_INVALID, 409, "submit-review requires DRAFT or IN_NEGOTIATION")
    contract["status"] = "UNDER_REVIEW"
    db.touch(contract)
    return success_obj(db.public(contract), 200)


@bp.post("/contracts/<cid>/negotiate")
def negotiate(cid):
    authenticate(["ContractOfficer"])
    body_json()  # optional note is accepted and not persisted
    contract = require_fk("contracts", cid)
    if contract["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_CONTRACT_STATE_INVALID, 409, "negotiate requires UNDER_REVIEW")
    contract["status"] = "IN_NEGOTIATION"
    contract["negotiation_round"] += 1
    db.touch(contract)
    return success_obj(db.public(contract), 200)


@bp.post("/contracts/<cid>/approve-review")
def approve_review(cid):
    authenticate(["ContractOfficer"])
    contract = require_fk("contracts", cid)
    if contract["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_CONTRACT_STATE_INVALID, 409, "approve-review requires UNDER_REVIEW")
    contract["status"] = "REVIEW_APPROVED"
    db.touch(contract)
    return success_obj(db.public(contract), 200)


@bp.post("/contracts/<cid>/execute")
def execute_contract(cid):
    authenticate(["ProcurementDirector"])
    contract = require_fk("contracts", cid)
    if contract["status"] != "REVIEW_APPROVED":
        raise ApiError(ERR_CONTRACT_STATE_INVALID, 409, "execute requires REVIEW_APPROVED")
    predecessor = None
    if contract.get("supersedes_contract_id"):
        predecessor = db.get("contracts", contract["supersedes_contract_id"])
        if predecessor is None or predecessor["status"] != "EXECUTED":
            raise ApiError(ERR_CONTRACT_STATE_INVALID, 409, "supersede target must be EXECUTED")
    # p9 structural: half-open [start, end) exclusivity over the same
    # (vendor_id, commodity_code), excluding the supersede target.
    start = parse_dt(contract["effective_start"])
    end = parse_dt(contract["effective_end"])
    for other in db.all_of("contracts"):
        if other["id"] == contract["id"] or other["status"] != "EXECUTED":
            continue
        if predecessor is not None and other["id"] == predecessor["id"]:
            continue
        if other["vendor_id"] != contract["vendor_id"] or other["commodity_code"] != contract["commodity_code"]:
            continue
        o_start = parse_dt(other["effective_start"])
        o_end = parse_dt(other["effective_end"])
        if start < o_end and o_start < end:
            raise ApiError(ERR_CONTRACT_OVERLAP, 409, "an EXECUTED contract already covers this vendor/commodity period")
    # p10 referential: counterparty vendor must be ACTIVE.
    vendor = db.get("vendors", contract["vendor_id"])
    if vendor is None or vendor["status"] != "ACTIVE":
        raise ApiError(ERR_VENDOR_SUSPENDED, 409, "contract vendor must be ACTIVE")
    # Period internal consistency (unreachable when create/amend enforced it).
    _check_period(contract["effective_start"], contract["effective_end"])
    contract["status"] = "EXECUTED"
    contract["executed_at"] = db.logical_ts()
    db.touch(contract)
    if predecessor is not None:
        predecessor["status"] = "SUPERSEDED"
        db.touch(predecessor)
    return success_obj(db.public(contract), 200)


@bp.post("/contracts/<cid>/amend")
def amend_contract(cid):
    """Create an amendment DRAFT superseding this EXECUTED contract; bumps the
    amended contract's version, hence the OCC guard (PRD 2.7/3.2)."""
    authenticate(["ContractOfficer"])
    contract = require_fk("contracts", cid)
    body = body_json()
    expected = body.get("expected_contract_version")
    if expected is None or not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "expected_contract_version is required and must be an integer")
    if expected != contract["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_contract_version does not match the current version")
    if contract["status"] != "EXECUTED":
        raise ApiError(ERR_CONTRACT_STATE_INVALID, 409, "amend requires an EXECUTED contract")
    check_shape(body, {
        "expected_contract_version": {"type": "integer", "required": True},
        "effective_start": {"type": "datetime", "required": True},
        "effective_end": {"type": "datetime", "required": True},
        "value_cents": {"type": "integer"},
        "terms_text": {"type": "string"},
    })
    _check_period(body["effective_start"], body["effective_end"])
    amendment = db.new_entity("contracts", {
        "vendor_id": contract["vendor_id"],
        "commodity_code": contract["commodity_code"],
        "value_cents": body.get("value_cents", contract["value_cents"]),
        "effective_start": body["effective_start"],
        "effective_end": body["effective_end"],
        "terms_text": body.get("terms_text", contract["terms_text"]),
        "status": "DRAFT",
        "negotiation_round": 0,
        "supersedes_contract_id": contract["id"],
        "executed_at": None,
        "terminated_reason": None,
    })
    db.touch(contract)  # creating the amendment mutates the amended contract
    return success_obj(db.public(amendment), 201)


@bp.post("/contracts/<cid>/terminate")
def terminate_contract(cid):
    authenticate(["ProcurementDirector"])
    contract = require_fk("contracts", cid)
    if contract["status"] != "EXECUTED":
        raise ApiError(ERR_CONTRACT_STATE_INVALID, 409, "terminate requires EXECUTED")
    body = body_json()
    check_shape(body, {"reason": {"type": "string", "required": True, "non_empty": True}})
    contract["status"] = "TERMINATED"
    contract["terminated_reason"] = body["reason"]
    db.touch(contract)
    svc.contract_termination_cascade(contract)
    return success_obj(db.public(contract), 200)
