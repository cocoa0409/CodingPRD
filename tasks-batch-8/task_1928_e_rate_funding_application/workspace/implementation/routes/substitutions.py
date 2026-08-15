"""ServiceSubstitution endpoints: OCC-guarded requests and supersede chains (PRD 3.7)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE_TRANSITION, ERR_STALE_VERSION,
    ERR_SERVICE_NOT_ELIGIBLE, ERR_SUBSTITUTION_CATEGORY_MISMATCH,
    ERR_CROSS_ENTITY_MISMATCH,
)
from middleware import get_caller, check_role, check_applicant_scope
from response import success_object
from routes.helpers import public, list_collection, get_one
from services.core import new_record, touch, retain_document, request_of_line
from validate import (
    get_body, check_allowed, req_str, opt_str, req_int, require_ref,
    require_path_resource,
)

bp = Blueprint("service_substitutions", __name__, url_prefix="/erate")

CREATE_FIELDS = {"frn_line_id", "to_eligible_service_id", "expected_line_version",
                 "supersedes_substitution_id", "reason"}


@bp.post("/service-substitutions")
def create_substitution():
    caller = get_caller()
    check_role(caller, ["ApplicantCoordinator"])
    body = get_body()
    # Tier 3 ownership via the line's applicant chain.
    raw_line_id = body.get("frn_line_id")
    if isinstance(raw_line_id, str):
        line_peek = db["funding_request_lines"].get(raw_line_id)
        if line_peek is not None:
            req = request_of_line(line_peek)
            check_applicant_scope(caller, req["applicant_id"] if req else None)
    check_allowed(body, CREATE_FIELDS)
    frn_line_id = req_str(body, "frn_line_id")
    to_eligible_service_id = req_str(body, "to_eligible_service_id")
    expected_line_version = req_int(body, "expected_line_version")
    supersedes_substitution_id = opt_str(body, "supersedes_substitution_id")
    reason = opt_str(body, "reason")
    # Existence in declared body order.
    line = require_ref("funding_request_lines", frn_line_id, "frn_line_id")
    to_service = require_ref("eligible_services", to_eligible_service_id,
                             "to_eligible_service_id")
    prev = None
    if supersedes_substitution_id is not None:
        prev = require_ref("service_substitutions", supersedes_substitution_id,
                           "supersedes_substitution_id")
    # State gate: the line must be COMMITTED.
    if line["status"] != "COMMITTED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    "substitutions are only allowed on COMMITTED lines")
    # OCC rule substitution-supersede-stale-line.
    if expected_line_version != line["version"]:
        raise_error(ERR_STALE_VERSION,
                    "expected_line_version does not match the line's current version")
    freq = request_of_line(line)
    from_service = db["eligible_services"][line["eligible_service_id"]]
    # Structural: target in the same funding cycle inventory; same category.
    if to_service["funding_cycle_id"] != freq["funding_cycle_id"]:
        raise_error(ERR_SERVICE_NOT_ELIGIBLE,
                    "target service is not in the funding cycle's eligible services inventory")
    if to_service["category"] != from_service["category"]:
        raise_error(ERR_SUBSTITUTION_CATEGORY_MISMATCH,
                    "target service category differs from the replaced service's category")
    # Referential: the supersede target must be APPROVED on the same line.
    if prev is not None and (prev["frn_line_id"] != frn_line_id
                             or prev["status"] != "APPROVED"):
        raise_error(ERR_CROSS_ENTITY_MISMATCH,
                    "supersede target is not an APPROVED substitution on the same line")
    rec = new_record("service_substitutions", {
        "frn_line_id": frn_line_id,
        "from_eligible_service_id": line["eligible_service_id"],
        "to_eligible_service_id": to_eligible_service_id,
        "supersedes_substitution_id": supersedes_substitution_id,
        "reason": reason,
        "status": "REQUESTED",
    })
    # The very act of creating the substitution increments the line's version.
    touch(line)
    return success_object(public(rec), 201)


@bp.get("/service-substitutions")
def list_substitutions():
    return list_collection("service_substitutions", {
        "frn_line_id": request.args.get("frn_line_id"),
        "supersedes_substitution_id": request.args.get("supersedes_substitution_id"),
        "from_eligible_service_id": request.args.get("from_eligible_service_id"),
        "to_eligible_service_id": request.args.get("to_eligible_service_id"),
        "status": request.args.get("status"),
    })


@bp.get("/service-substitutions/<rid>")
def get_substitution(rid):
    return get_one("service_substitutions", rid)


@bp.post("/service-substitutions/<rid>/approve")
def approve(rid):
    caller = get_caller()
    check_role(caller, ["ProgramAdmin"])
    body = get_body()
    check_allowed(body, set())
    sub = require_path_resource("service_substitutions", rid)
    if sub["status"] != "REQUESTED":
        raise_error(ERR_INVALID_STATE_TRANSITION, "substitution is not REQUESTED")
    line = db["funding_request_lines"][sub["frn_line_id"]]
    # Rewrite the line's eligible service; committed amounts stay unchanged.
    line["eligible_service_id"] = sub["to_eligible_service_id"]
    touch(line)
    if sub["supersedes_substitution_id"] is not None:
        prev = db["service_substitutions"].get(sub["supersedes_substitution_id"])
        if prev is not None and prev["status"] == "APPROVED":
            prev["status"] = "SUPERSEDED"
            touch(prev)
    sub["status"] = "APPROVED"
    freq = request_of_line(line)
    retain_document("SERVICE_SUBSTITUTION", rid, freq["funding_cycle_id"],
                    "SUBSTITUTION_APPROVAL")
    touch(sub)
    return success_object(public(sub))


@bp.post("/service-substitutions/<rid>/deny")
def deny(rid):
    caller = get_caller()
    check_role(caller, ["ProgramAdmin"])
    body = get_body()
    check_allowed(body, {"denial_reason"})
    opt_str(body, "denial_reason")
    sub = require_path_resource("service_substitutions", rid)
    if sub["status"] != "REQUESTED":
        raise_error(ERR_INVALID_STATE_TRANSITION, "substitution is not REQUESTED")
    sub["status"] = "DENIED"
    touch(sub)
    return success_object(public(sub))
