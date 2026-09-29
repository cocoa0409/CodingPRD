"""Sanction case endpoints (PRD §3.9)."""

from flask import Blueprint

import calc
import clock
import config as C
import envelope
import services
import validators
from auth import authenticate, check_vendor_scope
from errors import ApiError
from routes.common import body_fk, listing, need
from store import db, ordered, touch

bp = Blueprint("sanctions", __name__)

READ_ROLES = (
    C.ROLE_ANALYST,
    C.ROLE_SUPERVISOR,
    C.ROLE_INVESTIGATOR,
    C.ROLE_VENDOR_OPERATOR,
)


@bp.post("/sanction-cases")
def create_case():
    caller = authenticate(C.ROLE_INVESTIGATOR)
    payload = validators.body()
    vendor = body_fk(payload, "vendor_id", db.vendors, "ERR_VENDOR_NOT_FOUND")
    body_fk(payload, "source_visit_id", db.monitoring_visits, "ERR_VISIT_NOT_FOUND")

    validators.req_string(payload, "vendor_id")
    violation_code = validators.req_enum(payload, "violation_code", C.VIOLATION_CODES)
    source_visit_id = validators.opt_string(payload, "source_visit_id")
    narrative = validators.req_string(payload, "narrative")
    expected = validators.req_int(payload, "expected_vendor_version", minimum=0)

    if expected != vendor["version"]:
        raise ApiError("ERR_STALE_VENDOR_VERSION")
    if services.has_open_case(vendor["id"]):
        raise ApiError("ERR_OPEN_SANCTION_CASE_EXISTS")

    case = services.open_sanction_case(
        vendor, violation_code, source_visit_id, narrative, caller.user_id
    )
    touch(vendor)
    return envelope.success(case, 201)


@bp.get("/sanction-cases/<entity_id>")
def read_case(entity_id):
    caller = authenticate(*READ_ROLES)
    case = need(db.sanction_cases, entity_id, "ERR_SANCTION_CASE_NOT_FOUND")
    check_vendor_scope(caller, case["vendor_id"])
    return envelope.success(case)


@bp.get("/sanction-cases")
def list_cases():
    authenticate(*READ_ROLES)
    return listing(
        ordered(db.sanction_cases),
        {
            "vendor_id": "vendor_id",
            "source_visit_id": "source_visit_id",
            "status": "status",
        },
    )


@bp.post("/sanction-cases/<entity_id>/serve-notice")
def serve_notice(entity_id):
    authenticate(C.ROLE_INVESTIGATOR, C.ROLE_SUPERVISOR)
    case = need(db.sanction_cases, entity_id, "ERR_SANCTION_CASE_NOT_FOUND")
    if case["status"] != "OPENED":
        raise ApiError("ERR_INVALID_SANCTION_STATE")
    served_at = clock.now()
    services.update(
        case,
        status="NOTICE_SERVED",
        notice_served_at=served_at,
        response_due_at=clock.add_days(served_at, C.CMP_ELECTION_DAYS),
    )
    vendor = db.vendors.get(case["vendor_id"])
    if (
        case["base_tier"] == 4
        and vendor is not None
        and vendor["authorization_status"] == "AUTHORIZED"
    ):
        services.update(vendor, authorization_status="SUSPENDED")
    return envelope.success(case)


@bp.post("/sanction-cases/<entity_id>/elect-cmp")
def elect_cmp(entity_id):
    caller = authenticate(C.ROLE_VENDOR_OPERATOR)
    case = need(db.sanction_cases, entity_id, "ERR_SANCTION_CASE_NOT_FOUND")
    check_vendor_scope(caller, case["vendor_id"])
    if case["status"] != "NOTICE_SERVED":
        raise ApiError("ERR_INVALID_SANCTION_STATE")
    if not case["cmp_permitted"]:
        raise ApiError("ERR_CMP_NOT_PERMITTED")
    if case["response_due_at"] is None or clock.now() > case["response_due_at"]:
        raise ApiError("ERR_CMP_ELECTION_WINDOW_EXPIRED")
    services.update(case, status="CMP_ELECTED", resolution="CMP")
    return envelope.success(case)


@bp.post("/sanction-cases/<entity_id>/impose-disqualification")
def impose_disqualification(entity_id):
    caller = authenticate(C.ROLE_SUPERVISOR, C.ROLE_INVESTIGATOR)
    case = need(db.sanction_cases, entity_id, "ERR_SANCTION_CASE_NOT_FOUND")
    if case["status"] != "NOTICE_SERVED":
        raise ApiError("ERR_INVALID_SANCTION_STATE")
    if caller.user_id == case["opened_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if case["violation_code"] != "CLASS_A":
        if case["response_due_at"] is None or clock.now() <= case["response_due_at"]:
            raise ApiError("ERR_ELECTION_WINDOW_OPEN")
    if case["disqualification_months"] <= 0:
        raise ApiError("ERR_DISQUALIFICATION_NOT_AVAILABLE")

    services.update(
        case, status="DISQUALIFICATION_IMPOSED", resolution="DISQUALIFICATION"
    )
    vendor = db.vendors.get(case["vendor_id"])
    if vendor is not None:
        services.disqualify_vendor(vendor, case)
    return envelope.success(case)


@bp.post("/sanction-cases/<entity_id>/dismiss")
def dismiss_case(entity_id):
    authenticate(C.ROLE_INVESTIGATOR, C.ROLE_SUPERVISOR)
    case = need(db.sanction_cases, entity_id, "ERR_SANCTION_CASE_NOT_FOUND")
    payload = validators.body()
    reason = validators.req_string(payload, "dismissal_reason")
    if case["status"] != "NOTICE_SERVED":
        raise ApiError("ERR_INVALID_SANCTION_STATE")
    services.update(
        case, status="DISMISSED", resolution="DISMISSED", dismissal_reason=reason
    )
    vendor = db.vendors.get(case["vendor_id"])
    if (
        vendor is not None
        and vendor["authorization_status"] == "SUSPENDED"
        and not services.has_open_case(vendor["id"])
    ):
        services.update(vendor, authorization_status="AUTHORIZED", risk_flag="NONE")
    return envelope.success(case)


@bp.post("/sanction-cases/<entity_id>/close")
def close_case(entity_id):
    authenticate(C.ROLE_SUPERVISOR)
    case = need(db.sanction_cases, entity_id, "ERR_SANCTION_CASE_NOT_FOUND")
    payload = validators.body()
    payment = validators.opt_int(payload, "cmp_payment_cents", default=0, minimum=0)
    if case["status"] not in ("CMP_ELECTED", "DISQUALIFICATION_IMPOSED"):
        raise ApiError("ERR_INVALID_SANCTION_STATE")

    if case["status"] == "CMP_ELECTED":
        if case["cmp_paid_cents"] + payment < case["cmp_amount_cents"]:
            raise ApiError("ERR_CMP_UNDERPAID")
        services.update(
            case, status="CLOSED", cmp_paid_cents=case["cmp_paid_cents"] + payment
        )
        vendor = db.vendors.get(case["vendor_id"])
        if vendor is not None:
            services.update(
                vendor, sanction_points=vendor["sanction_points"] + case["case_points"]
            )
    else:
        services.update(case, status="CLOSED")
    return envelope.success(case)
