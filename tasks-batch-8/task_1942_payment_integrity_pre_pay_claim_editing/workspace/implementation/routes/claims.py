"""Claim, ClaimLine, and run-edits endpoints."""

from flask import Blueprint, request

import db
from errors import raise_err
from middleware import (
    check_provider_owner,
    get_body,
    pagination_params,
    require_auth,
    require_role,
    validate_body,
)
from response import success_list, success_object
from serializers import serialize
from services.calc import DRG_WEIGHTS
from services.screening import run_edits

bp = Blueprint("claims", __name__)
PREFIX = "/payment-integrity"

CLAIM_TYPES = {"PROFESSIONAL", "INSTITUTIONAL_INPATIENT", "INSTITUTIONAL_OUTPATIENT"}
CLAIM_STATUSES = {"RECEIVED", "PENDED", "DETERMINED", "READY_TO_PAY", "DENIED", "PAID"}


@bp.route(PREFIX + "/claims", methods=["POST"])
def create_claim():
    user_id, role = require_auth()
    require_role(role, ["Provider"])
    body = get_body()
    # Band 3 ownership surfaces before band 4 shape when the payload names
    # a provider other than the caller.
    if isinstance(body.get("provider_id"), str) and body["provider_id"] != user_id:
        raise_err("ERR_NOT_RESOURCE_OWNER", "provider_id must equal X-User-ID")
    vals = validate_body(
        body,
        {
            "claim_number": (True, "string", None),
            "provider_id": (True, "string", None),
            "member_id": (True, "string", None),
            "claim_type": (True, "string", CLAIM_TYPES),
            "total_billed_cents": (True, "integer", None),
            "service_from": (True, "datetime", None),
            "service_to": (True, "datetime", None),
            "admission_date": (False, "datetime", None),
            "discharge_date": (False, "datetime", None),
            "drg_code": (False, "string", None),
            "discharge_disposition": (False, "string", {"HOME", "TRANSFER"}),
        },
    )
    # Band 3 ownership: provider_id must equal X-User-ID
    check_provider_owner(user_id, vals["provider_id"])
    # Value-domain checks (band 4 request shape)
    if vals["total_billed_cents"] < 1:
        raise_err("ERR_INVALID_REQUEST", "total_billed_cents must be >= 1")
    if vals["service_to"] < vals["service_from"]:
        raise_err("ERR_INVALID_REQUEST", "service_to may not precede service_from")
    inpatient = vals["claim_type"] == "INSTITUTIONAL_INPATIENT"
    if inpatient:
        if vals.get("admission_date") is None or vals.get("discharge_date") is None or vals.get("drg_code") is None:
            raise_err(
                "ERR_INVALID_REQUEST",
                "INSTITUTIONAL_INPATIENT requires admission_date, discharge_date, drg_code",
            )
        if vals["discharge_date"] < vals["admission_date"]:
            raise_err("ERR_INVALID_REQUEST", "discharge_date may not precede admission_date")
    # Band 5 existence: provider must resolve
    provider = db.get("providers", vals["provider_id"])
    if provider is None:
        raise_err("ERR_PROVIDER_NOT_FOUND", "Provider not found")
    claim = db.create_resource(
        "claims",
        {
            "claim_number": vals["claim_number"],
            "provider_id": vals["provider_id"],
            "member_id": vals["member_id"],
            "claim_type": vals["claim_type"],
            "total_billed_cents": vals["total_billed_cents"],
            "service_from": vals["service_from"],
            "service_to": vals["service_to"],
            "admission_date": vals.get("admission_date"),
            "discharge_date": vals.get("discharge_date"),
            "drg_code": vals.get("drg_code"),
            "discharge_disposition": vals.get("discharge_disposition", "HOME"),
            "status": "RECEIVED",
            "initial_allowed_cents": 0,
            "allowed_amount_cents": 0,
            "denied_amount_cents": 0,
            "high_dollar_flag": False,
            "readmission_flag": False,
            "determined_at": None,
        },
    )
    return success_object(serialize(claim), status=201)


@bp.route(PREFIX + "/claims", methods=["GET"])
def list_claims():
    require_auth()
    limit, offset = pagination_params()
    provider_id = request.args.get("provider_id")
    status = request.args.get("status")
    member_id = request.args.get("member_id")
    rows = db.all_records("claims")
    if provider_id is not None:
        rows = [r for r in rows if r["provider_id"] == provider_id]
    if status is not None:
        if status not in CLAIM_STATUSES:
            raise_err("ERR_INVALID_ENUM", "status filter carries undeclared member")
        rows = [r for r in rows if r["status"] == status]
    if member_id is not None:
        rows = [r for r in rows if r["member_id"] == member_id]
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    return success_list([serialize(r) for r in rows[offset : offset + limit]], limit, offset, total)


def _get_claim_or_404(cid):
    claim = db.get("claims", cid)
    if claim is None:
        raise_err("ERR_CLAIM_NOT_FOUND", "Claim not found")
    return claim


@bp.route(PREFIX + "/claims/<cid>", methods=["GET"])
def get_claim(cid):
    require_auth()
    return success_object(serialize(_get_claim_or_404(cid)))


@bp.route(PREFIX + "/claims/<cid>/lines", methods=["POST"])
def add_claim_line(cid):
    user_id, role = require_auth()
    require_role(role, ["Provider"])
    body = get_body()
    vals = validate_body(
        body,
        {
            "line_number": (True, "integer", None),
            "procedure_code": (True, "string", None),
            "billed_cents": (True, "integer", None),
            "units": (False, "integer", None),
        },
    )
    if vals["line_number"] < 1:
        raise_err("ERR_INVALID_REQUEST", "line_number must be >= 1")
    if vals["billed_cents"] < 1:
        raise_err("ERR_INVALID_REQUEST", "billed_cents must be >= 1")
    units = vals.get("units", 1)
    if units < 1:
        raise_err("ERR_INVALID_REQUEST", "units must be >= 1")
    # Band 5 existence
    claim = _get_claim_or_404(cid)
    # Band 3 ownership (checked after existence so 404s surface for unknown ids
    # while known foreign claims surface 403)
    check_provider_owner(user_id, claim["provider_id"])
    # Band 7 state
    if claim["status"] != "RECEIVED":
        raise_err("ERR_CLAIM_LINES_LOCKED", "Claim lines locked once claim leaves RECEIVED")
    # line_number unique within claim
    for line in db.all_records("claim_lines"):
        if line["claim_id"] == cid and line["line_number"] == vals["line_number"]:
            raise_err("ERR_INVALID_REQUEST", "line_number must be unique within the claim")
    line = db.create_resource(
        "claim_lines",
        {
            "claim_id": cid,
            "line_number": vals["line_number"],
            "procedure_code": vals["procedure_code"],
            "units": units,
            "billed_cents": vals["billed_cents"],
            "allowed_cents": 0,
            "denied_cents": 0,
        },
    )
    return success_object(serialize(line), status=201)


@bp.route(PREFIX + "/claims/<cid>/lines", methods=["GET"])
def list_claim_lines(cid):
    require_auth()
    _get_claim_or_404(cid)
    limit, offset = pagination_params()
    rows = [l for l in db.all_records("claim_lines") if l["claim_id"] == cid]
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    return success_list([serialize(r) for r in rows[offset : offset + limit]], limit, offset, total)


@bp.route(PREFIX + "/claims/<cid>/edit-hits", methods=["GET"])
def list_claim_edit_hits(cid):
    require_auth()
    _get_claim_or_404(cid)
    limit, offset = pagination_params()
    rows = [h for h in db.all_records("edit_hits") if h["claim_id"] == cid]
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    return success_list([serialize(r) for r in rows[offset : offset + limit]], limit, offset, total)


@bp.route(PREFIX + "/claims/<cid>/run-edits", methods=["POST"])
def run_edits_endpoint(cid):
    user_id, role = require_auth()
    require_role(role, ["PlanAdmin"])
    body = get_body()
    validate_body(body, {})
    claim = _get_claim_or_404(cid)
    # Band 7 state
    if claim["status"] != "RECEIVED":
        raise_err("ERR_CLAIM_NOT_SCREENABLE", "run-edits requires RECEIVED")
    # Band 8 safety: provider must be ACTIVE
    provider = db.get("providers", claim["provider_id"])
    if provider is not None and provider["status"] == "TERMINATED":
        raise_err("ERR_PROVIDER_TERMINATED", "Provider is TERMINATED")
    # Band 11 referential: inpatient drg_code must be a known DRG weight key
    if claim["claim_type"] == "INSTITUTIONAL_INPATIENT":
        if claim.get("drg_code") not in DRG_WEIGHTS:
            raise_err("ERR_DRG_CODE_UNKNOWN", "drg_code not a known DRG weight key")
    # Band 12 fiscal: at least one line; line sum equals header
    lines = [l for l in db.all_records("claim_lines") if l["claim_id"] == cid]
    if len(lines) == 0:
        raise_err("ERR_NO_CLAIM_LINES", "run-edits requires at least one claim line")
    if sum(l["billed_cents"] for l in lines) != claim["total_billed_cents"]:
        raise_err("ERR_LINE_AMOUNT_MISMATCH", "Line billed sum != total_billed_cents")
    run_edits(claim)
    return success_object(serialize(claim))


@bp.route(PREFIX + "/claims/<cid>/pay", methods=["POST"])
def pay_claim(cid):
    user_id, role = require_auth()
    require_role(role, ["PlanAdmin"])
    body = get_body()
    validate_body(body, {})
    claim = _get_claim_or_404(cid)
    if claim["status"] != "READY_TO_PAY":
        raise_err("ERR_CLAIM_NOT_PAYABLE", "pay requires READY_TO_PAY")
    claim["status"] = "PAID"
    db.touch(claim)
    return success_object(serialize(claim))
