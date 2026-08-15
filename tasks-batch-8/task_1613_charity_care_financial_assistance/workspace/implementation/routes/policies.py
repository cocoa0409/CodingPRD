"""Policy authoring and activation (PRD 3.1, 2.7)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_POLICY_NOT_FOUND, ERR_POLICY_NOT_DRAFT,
    ERR_INVALID_PERIOD, ERR_POLICY_WINDOW_OVERLAP, ERR_DUPLICATE_POLICY_CODE,
)
from middleware import authorized
from response import success_object
from routes.helpers import require
from services.core import new_record, public, touch
from util import parse_dt
from validate import get_body, req_datetime, req_int, req_number, req_str

bp = Blueprint("policies", __name__)

READ_ROLES = ["FinancialCounselor", "AssistanceReviewer", "BillingAdministrator",
              "CollectionsAgent", "ComplianceOfficer"]


@bp.post("/charity-care/policies")
def create_policy():
    authorized(["ComplianceOfficer"])
    body = get_body()
    # Priority 9: window sanity (fields must parse first)
    effective_from = req_datetime(body, "effective_from")
    effective_to = req_datetime(body, "effective_to")
    if parse_dt(effective_from) >= parse_dt(effective_to):
        raise_error(ERR_INVALID_PERIOD, "effective_from must be strictly earlier than effective_to")
    # Priority 12: policy_code uniqueness
    policy_code = req_str(body, "policy_code")
    if any(p["policy_code"] == policy_code for p in db["policies"].values()):
        raise_error(ERR_DUPLICATE_POLICY_CODE, "policy_code already exists")
    # Priority 13: remaining required fields
    rec = new_record("policies", {
        "policy_code": policy_code,
        "fpl_base_cents": req_int(body, "fpl_base_cents"),
        "fpl_increment_cents": req_int(body, "fpl_increment_cents"),
        "full_discount_max_fpl_pct": req_int(body, "full_discount_max_fpl_pct"),
        "partial_discount_max_fpl_pct": req_int(body, "partial_discount_max_fpl_pct"),
        "partial_discount_floor_pct": req_number(body, "partial_discount_floor_pct"),
        "asset_limit_cents": req_int(body, "asset_limit_cents"),
        "retroactive_window_days": req_int(body, "retroactive_window_days"),
        "notification_period_days": req_int(body, "notification_period_days"),
        "eca_notice_days": req_int(body, "eca_notice_days"),
        "doc_response_days": req_int(body, "doc_response_days"),
        "presumptive_partial_score_threshold": req_number(body, "presumptive_partial_score_threshold"),
        "presumptive_full_score_threshold": req_number(body, "presumptive_full_score_threshold"),
        "effective_from": effective_from,
        "effective_to": effective_to,
        "status": "DRAFT",
    })
    return success_object(public(rec), status=201)


@bp.get("/charity-care/policies/<pid>")
def get_policy(pid):
    authorized(READ_ROLES)
    policy = require("policies", pid, ERR_POLICY_NOT_FOUND)
    return success_object(public(policy))


@bp.post("/charity-care/policies/<pid>/activate")
def activate_policy(pid):
    authorized(["ComplianceOfficer"])
    policy = require("policies", pid, ERR_POLICY_NOT_FOUND)
    if policy["status"] != "DRAFT":
        raise_error(ERR_POLICY_NOT_DRAFT, "activate requires a DRAFT policy")
    new_from = parse_dt(policy["effective_from"])
    new_to = parse_dt(policy["effective_to"])
    if new_from >= new_to:
        raise_error(ERR_INVALID_PERIOD, "effective_from must be strictly earlier than effective_to")
    # Half-open window overlap vs ACTIVE / SUPERSEDED policies; adjacency allowed
    for other in db["policies"].values():
        if other["id"] == pid or other["status"] not in ("ACTIVE", "SUPERSEDED"):
            continue
        ex_from = parse_dt(other["effective_from"])
        ex_to = parse_dt(other["effective_to"])
        if new_from < ex_to and ex_from < new_to:
            raise_error(
                ERR_POLICY_WINDOW_OVERLAP,
                "effective window intersects an ACTIVE or SUPERSEDED policy window",
            )
    # Activation supersedes the currently ACTIVE policy
    for other in db["policies"].values():
        if other["id"] != pid and other["status"] == "ACTIVE":
            other["status"] = "SUPERSEDED"
            touch(other)
    policy["status"] = "ACTIVE"
    touch(policy)
    return success_object(public(policy))
