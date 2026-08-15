"""AuditPackage endpoints: engagement, drafts, exceptions, attest, decision."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_AUDIT_PACKAGE_EXISTS,
    ERR_AUDIT_PACKAGE_INCOMPLETE,
    ERR_INVALID_STATE_TRANSITION,
    ERR_NOT_OWNER,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SPEND_ENTRIES_PENDING,
)
from helpers import get_one, list_query, public
from middleware import authorized
from response import success_object
from services.core import (
    credit_pipeline,
    new_record,
    recompute_application,
    touch,
)
from util import CLOCK
from validate import (
    get_body,
    opt_str,
    reject_unknown_fields,
    req_bool,
    req_enum,
    req_int,
    req_str,
    require_body_ref,
    require_path_resource,
)

bp = Blueprint("audit_packages", __name__)

DECISION_OUTCOMES = {"ACCEPT", "REJECT"}


@bp.post("/audit-packages")
def create_audit_package():
    caller = authorized(["CPAAuditor"])
    body = get_body()
    reject_unknown_fields(body, {"application_id"})
    application_id = req_str(body, "application_id")
    app = require_body_ref("applications", application_id, "application_id")
    # State (5): engagement requires an APPROVED application.
    if app["status"] != "APPROVED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"cannot engage an audit package while the application is {app['status']}")
    # Lifecycle uniqueness (6): at most one non-REJECTED package per application.
    for p in db["audit_packages"].values():
        if p["application_id"] == application_id and p["status"] != "REJECTED":
            raise_error(ERR_AUDIT_PACKAGE_EXISTS,
                        "an audit package with status other than REJECTED already exists")
    rec = new_record("audit_packages", {
        "application_id": application_id,
        "cpa_user_id": caller.user_id,
        "status": "ENGAGED",
        "documentation_complete": None,
        "attested_atl_cents": None,
        "attested_btl_cents": None,
        "exception_count": 0,
        "attested_at": None,
        "decided_by_user_id": None,
    })
    return success_object(public(rec), status=201)


@bp.get("/audit-packages")
def list_audit_packages():
    return list_query("audit_packages", {
        "application_id": request.args.get("application_id"),
        "status": request.args.get("status"),
    })


@bp.get("/audit-packages/<packageId>")
def get_audit_package(packageId):
    return get_one("audit_packages", packageId)


def _check_package_owner(caller, package):
    # Priority 4: only the engaging CPA may submit drafts and attest.
    if caller.user_id != package["cpa_user_id"]:
        raise_error(ERR_NOT_OWNER, "caller is not the audit package's engaging CPA")


@bp.post("/audit-packages/<packageId>/submit-draft")
def submit_draft(packageId):
    caller = authorized(["CPAAuditor"])
    package = require_path_resource("audit_packages", packageId)
    body = get_body()
    reject_unknown_fields(body, {"documentation_complete"})
    documentation_complete = req_bool(body, "documentation_complete")
    _check_package_owner(caller, package)
    if package["status"] not in ("ENGAGED", "FIELDWORK"):
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"submit-draft is not declared from status {package['status']}")
    package["documentation_complete"] = documentation_complete
    package["status"] = "DRAFT_SUBMITTED"
    touch(package)
    return success_object(public(package))


@bp.post("/audit-packages/<packageId>/raise-exceptions")
def raise_exceptions(packageId):
    authorized(["FilmOfficeReviewer"])
    package = require_path_resource("audit_packages", packageId)
    body = get_body()
    reject_unknown_fields(body, {"exception_notes"})
    req_str(body, "exception_notes")
    if package["status"] != "DRAFT_SUBMITTED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"raise-exceptions is not declared from status {package['status']}")
    package["status"] = "FIELDWORK"
    package["exception_count"] = int(package["exception_count"]) + 1
    touch(package)
    return success_object(public(package))


@bp.post("/audit-packages/<packageId>/attest")
def attest(packageId):
    caller = authorized(["CPAAuditor"])
    package = require_path_resource("audit_packages", packageId)
    body = get_body()
    reject_unknown_fields(body, {"attested_atl_cents", "attested_btl_cents", "documentation_complete"})
    attested_atl = req_int(body, "attested_atl_cents", non_negative=True)
    attested_btl = req_int(body, "attested_btl_cents", non_negative=True)
    documentation_complete = req_bool(body, "documentation_complete")
    _check_package_owner(caller, package)
    if package["status"] != "DRAFT_SUBMITTED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"attest is not declared from status {package['status']}")
    # Compliance (8): documentation must be complete in THIS request.
    if documentation_complete is not True:
        raise_error(ERR_AUDIT_PACKAGE_INCOMPLETE,
                    "documentation_complete must be true at attestation")
    # Compliance (8): no spend entry of the application may be PENDING_REVIEW.
    for e in db["spend_entries"].values():
        if e["application_id"] == package["application_id"] and e["status"] == "PENDING_REVIEW":
            raise_error(ERR_SPEND_ENTRIES_PENDING,
                        "spend entries of the application are still PENDING_REVIEW")
    package["attested_atl_cents"] = attested_atl
    package["attested_btl_cents"] = attested_btl
    package["documentation_complete"] = documentation_complete
    package["attested_at"] = CLOCK.now_iso()
    package["status"] = "ATTESTED"
    touch(package)
    return success_object(public(package))


@bp.post("/audit-packages/<packageId>/decision")
def decide(packageId):
    caller = authorized(["FilmOfficeReviewer"])
    package = require_path_resource("audit_packages", packageId)
    body = get_body()
    reject_unknown_fields(body, {"outcome", "decision_reason"})
    outcome = req_enum(body, "outcome", DECISION_OUTCOMES)
    if package["status"] != "ATTESTED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"decision is not declared from status {package['status']}")
    # Compliance (8): segregation of duties — decider differs from the CPA.
    if caller.user_id == package["cpa_user_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    "the audit decider must differ from the engaging CPA")
    package["decided_by_user_id"] = caller.user_id
    if outcome == "ACCEPT":
        package["status"] = "ACCEPTED"
        touch(package)
        # Lock the application's final credit to the FINAL variant over the
        # attested sums; refresh recomputed figures on the same pass.
        app = db["applications"].get(package["application_id"])
        program = db["jurisdiction_programs"].get(app["jurisdiction_program_id"])
        _, _, final_credit, _ = credit_pipeline(
            int(package["attested_atl_cents"]), int(package["attested_btl_cents"]), program
        )
        app["final_credit_cents"] = final_credit
        touch(app)
        recompute_application(app)
    else:
        # REJECT: terminal; application remains APPROVED and a fresh package
        # may be engaged (the REJECTED package no longer blocks creation).
        package["status"] = "REJECTED"
        touch(package)
    return success_object(public(package))
