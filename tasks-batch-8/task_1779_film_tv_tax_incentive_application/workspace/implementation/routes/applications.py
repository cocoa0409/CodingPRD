"""IncentiveApplication endpoints: lifecycle, computed reads, credit issuance."""
from datetime import timedelta
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_APPLICATION_ALREADY_OPEN,
    ERR_AUDIT_NOT_ACCEPTED,
    ERR_CERTIFICATE_ALREADY_ISSUED,
    ERR_APPLICATION_DEADLINE_PASSED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_MINIMUM_SPEND_NOT_MET,
    ERR_PROGRAM_CAP_EXHAUSTED,
    ERR_PROGRAM_NOT_OPEN,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_WINDOW_NOT_YET_OPEN,
)
from helpers import (
    audit_package_for_application,
    certificate_for_application,
    check_producer_owns,
    company_id_of_application,
    get_one,
    list_query,
    program_of_application,
    public,
)
from middleware import authorized
from response import success_object
from services.core import (
    credit_pipeline,
    issue_certificate,
    new_record,
    recompute_shares,
    touch,
)
from util import CLOCK, dec, parse_dt, round_half_up_cents
from validate import (
    get_body,
    reject_unknown_fields,
    req_int,
    req_str,
    require_body_ref,
    require_path_resource,
)

bp = Blueprint("applications", __name__)

APP_STATUSES = {
    "DRAFT", "SUBMITTED", "UNDER_REVIEW", "CORRECTION_REQUESTED",
    "APPROVED", "DENIED", "WITHDRAWN", "CREDIT_ISSUED", "REVOKED",
}
TERMINAL_FREEING = {"DENIED", "WITHDRAWN", "REVOKED"}


# --- CRUD -------------------------------------------------------------------

@bp.post("/applications")
def create_application():
    caller = authorized(["Producer"])
    body = get_body()
    reject_unknown_fields(body, {"production_id", "jurisdiction_program_id", "estimated_qualified_spend_cents"})
    production_id = req_str(body, "production_id")
    jurisdiction_program_id = req_str(body, "jurisdiction_program_id")
    estimated = req_int(body, "estimated_qualified_spend_cents", non_negative=True)
    # Existence (3): body FKs left to right.
    require_body_ref("productions", production_id, "production_id")
    require_body_ref("jurisdiction_programs", jurisdiction_program_id, "jurisdiction_program_id")
    # Ownership (4).
    production = db["productions"][production_id]
    check_producer_owns(caller, production["production_company_id"])
    # Lifecycle uniqueness (6): one open application per (production, program).
    for other in db["applications"].values():
        if (
            other["production_id"] == production_id
            and other["jurisdiction_program_id"] == jurisdiction_program_id
            and other["status"] not in TERMINAL_FREEING
        ):
            raise_error(ERR_APPLICATION_ALREADY_OPEN,
                        "another application for this production and program is still open")
    rec = new_record("applications", {
        "production_id": production_id,
        "jurisdiction_program_id": jurisdiction_program_id,
        "estimated_qualified_spend_cents": estimated,
        "status": "DRAFT",
        "submitted_at": None,
        "reviewer_user_id": None,
        "decided_by_user_id": None,
        "atl_qualified_cents": 0,
        "btl_qualified_cents": 0,
        "capped_total_qualified_cents": 0,
        "provisional_credit_cents": 0,
        "recomputed_credit_cents": 0,
        "final_credit_cents": None,
        "allocation_share_pct": 0,
    })
    return success_object(public(rec), status=201)


@bp.get("/applications")
def list_applications():
    return list_query("applications", {
        "production_id": request.args.get("production_id"),
        "jurisdiction_program_id": request.args.get("jurisdiction_program_id"),
        "status": request.args.get("status"),
    })


@bp.get("/applications/<applicationId>")
def get_application(applicationId):
    return get_one("applications", applicationId)


# --- Lifecycle ---------------------------------------------------------------

def _owned_application(caller, applicationId):
    """Path resolution (3) precedes body validation (PRD 2.10); ownership (4)
    follows request-shape checks."""
    app = require_path_resource("applications", applicationId)
    return app


def _check_owner(caller, app):
    check_producer_owns(caller, company_id_of_application(app))


@bp.post("/applications/<applicationId>/submit")
def submit_application(applicationId):
    caller = authorized(["Producer"])
    app = _owned_application(caller, applicationId)
    body = get_body()
    reject_unknown_fields(body, set())
    _check_owner(caller, app)
    # State (5).
    if app["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"submit is not declared from status {app['status']}")
    program = program_of_application(app)
    # Lifecycle (6): program must be OPEN.
    if program["status"] != "OPEN":
        raise_error(ERR_PROGRAM_NOT_OPEN,
                    f"program status is {program['status']}, not OPEN")
    # Temporal (9): window checks against the logical clock; close inclusive.
    now = CLOCK.now()
    if now < parse_dt(program["window_opens_at"]):
        raise_error(ERR_WINDOW_NOT_YET_OPEN, "the application window has not opened yet")
    if now > parse_dt(program["window_closes_at"]):
        raise_error(ERR_APPLICATION_DEADLINE_PASSED, "the application deadline has passed")
    app["status"] = "SUBMITTED"
    app["submitted_at"] = CLOCK.now_iso()
    touch(app)
    return success_object(public(app))


@bp.post("/applications/<applicationId>/withdraw")
def withdraw_application(applicationId):
    caller = authorized(["Producer"])
    app = _owned_application(caller, applicationId)
    body = get_body()
    reject_unknown_fields(body, set())
    _check_owner(caller, app)
    if app["status"] not in ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "CORRECTION_REQUESTED"):
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"withdraw is not declared from status {app['status']}")
    app["status"] = "WITHDRAWN"
    touch(app)
    recompute_shares(app["production_id"])
    return success_object(public(app))


@bp.post("/applications/<applicationId>/claim-review")
def claim_review(applicationId):
    caller = authorized(["FilmOfficeReviewer"])
    app = require_path_resource("applications", applicationId)
    body = get_body()
    reject_unknown_fields(body, set())
    if app["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"claim-review is not declared from status {app['status']}")
    app["status"] = "UNDER_REVIEW"
    app["reviewer_user_id"] = caller.user_id
    touch(app)
    return success_object(public(app))


@bp.post("/applications/<applicationId>/request-corrections")
def request_corrections(applicationId):
    authorized(["FilmOfficeReviewer"])
    app = require_path_resource("applications", applicationId)
    body = get_body()
    reject_unknown_fields(body, {"notes"})
    if app["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"request-corrections is not declared from status {app['status']}")
    app["status"] = "CORRECTION_REQUESTED"
    touch(app)
    return success_object(public(app))


@bp.post("/applications/<applicationId>/resubmit")
def resubmit_application(applicationId):
    caller = authorized(["Producer"])
    app = _owned_application(caller, applicationId)
    body = get_body()
    reject_unknown_fields(body, set())
    _check_owner(caller, app)
    if app["status"] != "CORRECTION_REQUESTED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"resubmit is not declared from status {app['status']}")
    app["status"] = "UNDER_REVIEW"
    touch(app)
    return success_object(public(app))


@bp.post("/applications/<applicationId>/approve")
def approve_application(applicationId):
    caller = authorized(["FilmOfficeReviewer"])
    app = require_path_resource("applications", applicationId)
    body = get_body()
    reject_unknown_fields(body, set())
    if app["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"approve is not declared from status {app['status']}")
    # Compliance (8): segregation of duties.
    if caller.user_id == app["reviewer_user_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    "the approver must differ from the claiming reviewer")
    # Fiscal (12): eligibility pre-check against the program minimum.
    program = program_of_application(app)
    if int(app["estimated_qualified_spend_cents"]) < int(program["minimum_qualified_spend_cents"]):
        raise_error(ERR_MINIMUM_SPEND_NOT_MET,
                    "estimated_qualified_spend_cents is below the program minimum")
    app["status"] = "APPROVED"
    app["decided_by_user_id"] = caller.user_id
    touch(app)
    recompute_shares(app["production_id"])
    return success_object(public(app))


@bp.post("/applications/<applicationId>/deny")
def deny_application(applicationId):
    caller = authorized(["FilmOfficeReviewer"])
    app = require_path_resource("applications", applicationId)
    body = get_body()
    reject_unknown_fields(body, {"reason"})
    if app["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"deny is not declared from status {app['status']}")
    if caller.user_id == app["reviewer_user_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    "the denier must differ from the claiming reviewer")
    app["status"] = "DENIED"
    app["decided_by_user_id"] = caller.user_id
    touch(app)
    return success_object(public(app))


# --- Computed reads ----------------------------------------------------------

@bp.get("/applications/<applicationId>/credit-estimate")
def credit_estimate(applicationId):
    authorized(["FilmOfficeAdmin", "FilmOfficeReviewer", "Producer", "CPAAuditor", "CreditBuyer"])
    app = require_path_resource("applications", applicationId)
    variant = request.args.get("variant", "PROVISIONAL")
    if variant not in ("PROVISIONAL", "FINAL"):
        raise_error(ERR_INVALID_REQUEST, f"invalid variant: {variant}")
    program = program_of_application(app)
    if variant == "PROVISIONAL":
        atl = int(app["atl_qualified_cents"])
        btl = int(app["btl_qualified_cents"])
    else:
        package = audit_package_for_application(app["id"], statuses={"ATTESTED", "ACCEPTED"})
        if package is None:
            raise_error(ERR_AUDIT_NOT_ACCEPTED,
                        "variant=FINAL requires an audit package in ATTESTED or ACCEPTED status")
        atl = int(package["attested_atl_cents"])
        btl = int(package["attested_btl_cents"])
    capped, rate, credit, meets_minimum = credit_pipeline(atl, btl, program)
    return success_object({
        "variant": variant,
        "atl_qualified_cents": atl,
        "btl_qualified_cents": btl,
        "capped_total_qualified_cents": capped,
        "applied_rate": rate,
        "credit_cents": credit,
        "meets_minimum": meets_minimum,
    })


@bp.get("/applications/<applicationId>/cashflow-projection")
def cashflow_projection(applicationId):
    authorized(["FilmOfficeAdmin", "FilmOfficeReviewer", "Producer", "CPAAuditor", "CreditBuyer"])
    app = require_path_resource("applications", applicationId)
    variant = request.args.get("variant", "OPTIMISTIC")
    if variant not in ("OPTIMISTIC", "CONSERVATIVE"):
        raise_error(ERR_INVALID_REQUEST, f"invalid variant: {variant}")
    program = program_of_application(app)
    production = db["productions"].get(app["production_id"])

    accepted = audit_package_for_application(app["id"], statuses={"ACCEPTED"})
    cert = certificate_for_application(app["id"])
    if accepted is not None or cert is not None:
        basis = int(app["final_credit_cents"] or 0)
    else:
        basis = int(app["provisional_credit_cents"])

    if variant == "OPTIMISTIC":
        net = basis
        lag_extra = 0
    else:
        net = round_half_up_cents(dec(program["transfer_price_floor_pct"]) * basis)
        lag_extra = 30

    m1 = round_half_up_cents(dec("0.40") * net)
    m2 = round_half_up_cents(dec("0.30") * net)
    m3 = net - m1 - m2  # pinned remainder, never rounded

    wrap = parse_dt(production["scheduled_wrap_date"]).date()
    specs = [
        ("PRODUCTION_WRAP", 0, m1),
        ("AUDIT_COMPLETE", 90, m2),
        ("CREDIT_ISSUANCE", 180, m3),
    ]
    milestones = []
    for name, lag, amount in specs:
        day = wrap + timedelta(days=lag + lag_extra)
        milestones.append({
            "milestone": name,
            "name": name,
            "type": name,
            "date": day.isoformat(),
            "amount_cents": amount,
        })
    return success_object({
        "variant": variant,
        "basis_credit_cents": basis,
        "expected_net_proceeds_cents": net,
        "milestones": milestones,
    })


# --- Issuance -----------------------------------------------------------------

@bp.post("/applications/<applicationId>/issue-credit")
def issue_credit(applicationId):
    authorized(["FilmOfficeAdmin"])
    app = require_path_resource("applications", applicationId)
    body = get_body()
    reject_unknown_fields(body, set())
    # State (5): the already-issued state maps explicitly to the domain error.
    if app["status"] == "CREDIT_ISSUED" or certificate_for_application(app["id"]) is not None:
        raise_error(ERR_CERTIFICATE_ALREADY_ISSUED,
                    "a certificate already exists for this application")
    if app["status"] != "APPROVED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"issue-credit is not declared from status {app['status']}")
    # Compliance (8): an ACCEPTED audit package must exist.
    package = audit_package_for_application(app["id"], statuses={"ACCEPTED"})
    if package is None:
        raise_error(ERR_AUDIT_NOT_ACCEPTED,
                    "no audit package in ACCEPTED status exists for this application")
    program = program_of_application(app)
    final_credit = int(app["final_credit_cents"] or 0)
    # Fiscal (12): final credit must be positive and fit the remaining cap.
    if final_credit <= 0:
        raise_error(ERR_MINIMUM_SPEND_NOT_MET,
                    "final credit is zero (attested capped total below the program minimum)")
    if final_credit > int(program["remaining_cap_cents"]):
        raise_error(ERR_PROGRAM_CAP_EXHAUSTED,
                    "final credit exceeds the program's remaining cap")
    cert = issue_certificate(app, program)
    return success_object(public(cert), status=201)
