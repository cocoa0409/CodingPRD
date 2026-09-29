"""Tour operators, safety audits and the vetting state machine."""

from datetime import timedelta

from flask import Blueprint

from db import db
from errors import fail
from middleware import FINANCE, MANAGER, RISK, VETTING, endpoint
from response import list_response, object_response
from routes import API_PREFIX
from serializers import audit_json, operator_json
from services.cascades import recompute_operator_score, suspend_operator, excursions_of_operator
from services.safety import latest_auditor_user_id
from validation import (audit_or_404, f, operator_or_404, paginate, pagination,
                        port_or_404, query_values, raw_body, validate_body)

bp = Blueprint("operators", __name__)

VETTING_STATUSES = ("DRAFT", "SUBMITTED", "INFO_REQUESTED", "APPROVED", "SUSPENDED", "TERMINATED")
AUDIT_TYPES = ("INITIAL", "ANNUAL", "INCIDENT_TRIGGERED")
VETTING_ACTIONS = ("SUBMIT", "REQUEST_INFO", "RESUBMIT", "APPROVE", "SUSPEND", "REINSTATE", "TERMINATE")

MIN_LIABILITY_LIMIT_CENTS = 100000000
SAFETY_SCORE_FLOOR = 60
MAX_VETTING_CYCLES = 3
OPEN_CLAIM_STATUSES = ("SUBMITTED", "UNDER_OPERATOR_REVIEW", "DISPUTED")

OPERATOR_CREATE = [
    f("port_id", "string", required=True),
    f("legal_name", "string", required=True),
    f("contact_email", "string", required=True),
    f("insurance_expiry_date", "instant", required=True),
    f("insurance_liability_limit_cents", "int", required=True, lo=0),
    f("commission_rate_bps", "int", required=True, lo=0, hi=5000),
]

AUDIT_CREATE = [
    f("audit_type", "enum", required=True, enum=AUDIT_TYPES),
    f("conducted_on", "instant", required=True),
    f("raw_score", "int", required=True, lo=0, hi=100),
    f("critical_finding_count", "int", required=True, lo=0, hi=20),
]

VETTING_ACTION = [
    f("action", "enum", required=True, enum=VETTING_ACTIONS),
    f("note", "string"),
]

READ_ROLES = (VETTING, MANAGER, RISK, FINANCE)


def _has_open_claim(operator_id):
    return any(c["operator_id"] == operator_id and c["status"] in OPEN_CLAIM_STATUSES
               for c in db.claims.values())


@bp.post(API_PREFIX + "/operators")
@endpoint(VETTING)
def create_operator(caller):
    body = validate_body(OPERATOR_CREATE)
    port = port_or_404(body["port_id"])
    row = db.insert("operators", {
        "port_id": port["id"],
        "legal_name": body["legal_name"],
        "contact_email": body["contact_email"],
        "insurance_expiry_date": body["insurance_expiry_date"],
        "insurance_liability_limit_cents": body["insurance_liability_limit_cents"],
        "commission_rate_bps": body["commission_rate_bps"],
        "vetting_status": "DRAFT",
        "vetting_cycle_count": 0,
        "safety_score": 0,
        "reliability_strikes": 0,
        "liability_reserve_cents": 0,
        "latest_audit_auditor_user_id": None,
    })
    return object_response(operator_json(row), 201)


@bp.get(API_PREFIX + "/operators/<operator_id>")
@endpoint(*READ_ROLES)
def read_operator(caller, operator_id):
    return object_response(operator_json(operator_or_404(operator_id)))


@bp.get(API_PREFIX + "/operators")
@endpoint(*READ_ROLES)
def list_operators(caller):
    limit, offset = pagination()
    filters = query_values([
        f("port_id", "string"),
        f("vetting_status", "enum", enum=VETTING_STATUSES),
    ])
    rows = db.ordered("operators")
    if "port_id" in filters:
        rows = [r for r in rows if r["port_id"] == filters["port_id"]]
    if "vetting_status" in filters:
        rows = [r for r in rows if r["vetting_status"] == filters["vetting_status"]]
    page, total = paginate(rows, limit, offset)
    return list_response([operator_json(r) for r in page], limit, offset, total)


@bp.post(API_PREFIX + "/operators/<operator_id>/safety-audits")
@endpoint(VETTING)
def create_audit(caller, operator_id):
    body = validate_body(AUDIT_CREATE)
    operator = operator_or_404(operator_id)
    if body["conducted_on"] > db.now():
        fail("ERR_INVALID_TIME_WINDOW", "conducted_on may not be later than the logical clock")

    row = db.insert("audits", {
        "operator_id": operator["id"],
        "audit_type": body["audit_type"],
        "conducted_on": body["conducted_on"],
        "raw_score": body["raw_score"],
        "critical_finding_count": body["critical_finding_count"],
        "auditor_user_id": caller.user_id,
    }, versioned=False)

    operator["latest_audit_auditor_user_id"] = latest_auditor_user_id(operator["id"])
    recompute_operator_score(operator, allow_auto_suspend=True)
    db.touch(operator)
    return object_response(audit_json(row), 201)


@bp.get(API_PREFIX + "/safety-audits/<audit_id>")
@endpoint(*READ_ROLES)
def read_audit(caller, audit_id):
    return object_response(audit_json(audit_or_404(audit_id)))


@bp.get(API_PREFIX + "/safety-audits")
@endpoint(*READ_ROLES)
def list_audits(caller):
    limit, offset = pagination()
    filters = query_values([
        f("operator_id", "string"),
        f("audit_type", "enum", enum=AUDIT_TYPES),
    ])
    rows = list(db.audits.values())
    if "operator_id" in filters:
        rows = [r for r in rows if r["operator_id"] == filters["operator_id"]]
    if "audit_type" in filters:
        rows = [r for r in rows if r["audit_type"] == filters["audit_type"]]
    rows.sort(key=lambda r: (r["conducted_on"], r["created_at"], r["_seq"]), reverse=True)
    page, total = paginate(rows, limit, offset)
    return list_response([audit_json(r) for r in page], limit, offset, total)


@bp.post(API_PREFIX + "/operators/<operator_id>/vetting-actions")
@endpoint(VETTING)
def vetting_action(caller, operator_id):
    # priority 5 is evaluated before request shape, so read the action leniently first
    raw = raw_body()
    candidate = db.operators.get(operator_id)
    if (candidate is not None and raw.get("action") == "APPROVE"
            and candidate.get("latest_audit_auditor_user_id") is not None
            and caller.user_id == candidate["latest_audit_auditor_user_id"]):
        fail("ERR_AUDITOR_CANNOT_APPROVE",
             "the officer who recorded the newest audit may not approve this operator")

    body = validate_body(VETTING_ACTION, raw)
    operator = operator_or_404(operator_id)
    action = body["action"]

    # every vetting action recomputes standing before it decides anything
    recompute_operator_score(operator)

    status = operator["vetting_status"]
    allowed = {
        "SUBMIT": ("DRAFT",),
        "REQUEST_INFO": ("SUBMITTED",),
        "RESUBMIT": ("INFO_REQUESTED",),
        "APPROVE": ("SUBMITTED",),
        "SUSPEND": ("APPROVED",),
        "REINSTATE": ("SUSPENDED",),
        "TERMINATE": ("SUSPENDED",),
    }[action]
    if status not in allowed:
        fail("ERR_INVALID_VETTING_ACTION",
             "%s is not declared for an operator in %s" % (action, status))

    now = db.now()
    if action in ("SUBMIT", "RESUBMIT", "APPROVE", "REINSTATE"):
        if not operator["insurance_expiry_date"] > now:
            fail("ERR_INSURANCE_EXPIRED", "the operator's insurance cover has lapsed")
    if action == "APPROVE":
        if operator["insurance_liability_limit_cents"] < MIN_LIABILITY_LIMIT_CENTS:
            fail("ERR_INSURANCE_LIMIT_INSUFFICIENT", "per-occurrence cover is below the minimum")
    if action == "SUBMIT":
        if not any(a["operator_id"] == operator["id"] for a in db.audits.values()):
            fail("ERR_AUDIT_REQUIRED", "at least one safety audit is required before submission")
    if action in ("APPROVE", "REINSTATE"):
        if operator["safety_score"] < SAFETY_SCORE_FLOOR:
            fail("ERR_SAFETY_SCORE_BELOW_FLOOR", "safety_score is below the floor of 60")
    if action == "RESUBMIT":
        if operator["vetting_cycle_count"] > MAX_VETTING_CYCLES:
            fail("ERR_VETTING_CYCLE_EXHAUSTED", "the vetting cycle cap has been reached")
    if action in ("REINSTATE", "TERMINATE"):
        if _has_open_claim(operator["id"]):
            fail("ERR_OPEN_CLAIM_BLOCKS_ISSUE", "an open liability claim blocks this action")

    if action == "SUBMIT":
        operator["vetting_status"] = "SUBMITTED"
        recompute_operator_score(operator)
        db.touch(operator)
    elif action == "REQUEST_INFO":
        operator["vetting_status"] = "INFO_REQUESTED"
        operator["vetting_cycle_count"] = operator["vetting_cycle_count"] + 1
        db.touch(operator)
    elif action == "RESUBMIT":
        operator["vetting_status"] = "SUBMITTED"
        recompute_operator_score(operator)
        db.touch(operator)
    elif action == "APPROVE":
        operator["vetting_status"] = "APPROVED"
        db.touch(operator)
    elif action == "SUSPEND":
        suspend_operator(operator)
    elif action == "REINSTATE":
        operator["vetting_status"] = "APPROVED"
        operator["reliability_strikes"] = 0
        db.touch(operator)
    else:  # TERMINATE
        operator["vetting_status"] = "TERMINATED"
        db.touch(operator)
        for excursion in excursions_of_operator(operator["id"]):
            if excursion["catalog_status"] in ("DRAFT", "PENDING_REVIEW", "WITHDRAWN"):
                excursion["catalog_status"] = "ARCHIVED"
                db.touch(excursion)

    return object_response(operator_json(operator))
