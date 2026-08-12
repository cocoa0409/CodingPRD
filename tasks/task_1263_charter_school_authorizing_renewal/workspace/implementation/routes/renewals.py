"""Renewal decisions (PRD §3.6)."""
from datetime import timedelta

from flask import Blueprint, request

import db
import errors
from clock import now_dt, now_iso, parse as parse_iso, to_iso
from errors import raise_error
from middleware import ALL_ROLES, body, require_non_empty_string, require_roles
from response import success_object
from routes.common import filter_eq, get_or_404, paginate
from services import cascade

bp = Blueprint("renewals", __name__)


@bp.post("/authorizer/schools/<id>/renewal-decisions")
def create_renewal(id):
    require_roles(["AuthorizerStaff"])
    school = get_or_404("schools", id)
    data = body()
    contract_id = require_non_empty_string(data, "contract_id")
    contract = get_or_404("contracts", contract_id)
    if contract["status"] != "ACTIVE":
        raise_error(errors.ERR_CONTRACT_INVALID_STATE, "contract_id must name an ACTIVE contract")
    if contract["school_id"] != id:
        raise_error(errors.ERR_NOT_FOUND, "Contract does not belong to this school")
    if school["status"] != "OPEN":
        raise_error(errors.ERR_SCHOOL_NOT_OPEN, "School must be OPEN for a renewal decision")
    # Renewal window: [term_end - 365d, term_end - 30d] inclusive (layer 6).
    term_end = parse_iso(contract["term_end"])
    now = now_dt()
    window_open = term_end - timedelta(days=365)
    window_close = term_end - timedelta(days=30)
    if now < window_open or now > window_close:
        raise_error(errors.ERR_RENEWAL_WINDOW_NOT_OPEN, "Clock outside the renewal window")
    # One open (PENDING|DECIDED) renewal decision per school.
    for rd in db.all_records("renewal_decisions"):
        if rd["school_id"] == id and rd["status"] in ("PENDING", "DECIDED"):
            raise_error(errors.ERR_RENEWAL_ALREADY_OPEN, "An open renewal decision already exists")
    eligible = cascade.compute_eligible_term_years(school, contract)
    record = db.stamp_new({
        "school_id": id,
        "contract_id": contract_id,
        "eligible_term_years": eligible,
        "decision": None,
        "granted_term_years": None,
        "decided_by_user_id": None,
        "decided_at": None,
        "status": "PENDING",
    })
    db.insert("renewal_decisions", record)
    return success_object(record, 201)


@bp.get("/authorizer/renewal-decisions")
def list_renewals():
    require_roles(ALL_ROLES)
    records = db.all_records("renewal_decisions")
    records = filter_eq(records, "school_id", request.args.get("school_id"))
    records = filter_eq(records, "contract_id", request.args.get("contract_id"))
    records = filter_eq(records, "status", request.args.get("status"))
    return paginate(records)


@bp.get("/authorizer/renewal-decisions/<id>")
def get_renewal(id):
    require_roles(ALL_ROLES)
    return success_object(get_or_404("renewal_decisions", id))


@bp.post("/authorizer/renewal-decisions/<id>/decide")
def decide_renewal(id):
    user_id, _role = require_roles(["BoardMember"])
    decision = get_or_404("renewal_decisions", id)
    if decision["status"] not in ("PENDING", "REVERTED"):
        raise_error(errors.ERR_DECISION_INVALID_STATE, "Decision is not PENDING or REVERTED")
    data = body()
    outcome = require_non_empty_string(data, "outcome")
    if outcome not in ("RENEWED", "RENEWED_WITH_CONDITIONS", "DENIED"):
        raise_error(errors.ERR_INVALID_REQUEST, "outcome must be RENEWED|RENEWED_WITH_CONDITIONS|DENIED")
    if outcome == "RENEWED" and not (decision["eligible_term_years"] > 0):
        raise_error(errors.ERR_RENEWAL_NOT_ELIGIBLE, "RENEWED requires eligible_term_years > 0")
    if outcome == "RENEWED_WITH_CONDITIONS" and not (decision["eligible_term_years"] >= 3):
        raise_error(errors.ERR_TERM_LENGTH_MISMATCH, "RENEWED_WITH_CONDITIONS requires eligible_term_years >= 3")
    decision["decision"] = outcome
    decision["decided_by_user_id"] = user_id
    decision["decided_at"] = now_iso()
    if outcome == "RENEWED":
        decision["granted_term_years"] = decision["eligible_term_years"]
    elif outcome == "RENEWED_WITH_CONDITIONS":
        decision["granted_term_years"] = 3
    else:
        decision["granted_term_years"] = None
    decision["status"] = "DECIDED"
    db.touch(decision)
    return success_object(decision)


@bp.post("/authorizer/renewal-decisions/<id>/finalize")
def finalize_renewal(id):
    require_roles(["AuthorizerStaff"])
    decision = get_or_404("renewal_decisions", id)
    if decision["status"] != "DECIDED":
        raise_error(errors.ERR_DECISION_INVALID_STATE, "Decision is not DECIDED")
    decided_at = parse_iso(decision["decided_at"])
    # Strictly greater than decided_at + 30 days.
    if now_dt() <= decided_at + timedelta(days=30):
        raise_error(errors.ERR_APPEAL_WINDOW_OPEN, "Appeal window is still open")
    for appeal in db.all_records("appeals"):
        if (
            appeal["target_type"] == "RENEWAL_DENIAL"
            and appeal["target_id"] == id
            and appeal["status"] in ("FILED", "HEARING_SCHEDULED")
        ):
            raise_error(errors.ERR_APPEAL_WINDOW_OPEN, "An appeal is still open on this decision")
    decision["status"] = "FINAL"
    db.touch(decision)
    contract = db.get("contracts", decision["contract_id"])
    school = db.get("schools", decision["school_id"])
    if decision["decision"] in ("RENEWED", "RENEWED_WITH_CONDITIONS"):
        if contract is not None:
            prior_end = parse_iso(contract["term_end"])
            new_start = prior_end + timedelta(days=1)
            # term_end = granted_term_years years after start.
            years = decision["granted_term_years"]
            try:
                new_end = new_start.replace(year=new_start.year + years)
            except ValueError:
                # Feb 29 -> Feb 28 on non-leap year
                new_end = new_start.replace(year=new_start.year + years, day=28)
            successor = db.stamp_new({
                "school_id": contract["school_id"],
                "prior_contract_id": contract["id"],
                "framework_version": contract["framework_version"],
                "term_start": to_iso(new_start),
                "term_end": to_iso(new_end),
                "status": "DRAFT",
                "targets_weight_total": 0,
            })
            db.insert("contracts", successor)
            if contract["status"] == "ACTIVE":
                contract["status"] = "RENEWED"
                db.touch(contract)
    else:  # DENIED
        if school is not None and school["status"] == "OPEN":
            cascade.school_to_closing(school)
        if school is not None:
            plan = db.stamp_new({
                "school_id": school["id"],
                "reason": "NON_RENEWAL",
                "closure_date": None,
                "decided_by_user_id": "system",
                "status": "INITIATED",
            })
            db.insert("closure_plans", plan)
    return success_object(decision)
