"""Unauthorized-item liability claims (PRD §3.8)."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import store
from auth import ALL_ROLES, authenticate, authorize, check_list_enrollment_param, check_ownership, scope_list
from errors import (
    ERR_CASE_NOT_OPEN,
    ERR_CLAIM_WINDOW_CLOSED,
    ERR_ITEM_NOT_CLAIMABLE,
    ERR_SOD_CASE_RESOLUTION_CONFLICT,
    raise_err,
)
from services import (
    CLAIM_REASONS,
    CLAIM_WINDOW_DAYS,
    PROVISIONAL_CREDIT_CAP_CENTS,
    RESOLUTIONS,
    SOD_CASE_THRESHOLD_CENTS,
    case_out,
    guard_enrollment_active,
    guard_enrollment_mutable,
    item_enrollment_id,
    ytd_bank_loss,
)
from util import body_json, bump, get_or_404, list_response, new_record, req_enum, req_str, success_object

bp = Blueprint("liability_cases", __name__)

FILER_ROLES = ["CustomerAdmin", "CustomerManager", "CustomerDecisionMaker"]


@bp.route("/treasury/liability-cases", methods=["POST"])
def file_case():
    uid, role, user = authenticate()
    authorize(role, user, FILER_ROLES)
    body = body_json()
    item_id = req_str(body, "presented_item_id")
    claim_reason = req_enum(body, "claim_reason", CLAIM_REASONS)
    item = get_or_404(store.items, item_id, "PresentedItem")
    enr = store.enrollments[item_enrollment_id(item)]
    check_ownership(user, enr["id"])
    guard_enrollment_active(enr)
    if item["status"] != "PAID":
        raise_err(ERR_ITEM_NOT_CLAIMABLE, "Only a PAID item can be claimed")
    if clock.now() > item["paid_at"] + timedelta(days=CLAIM_WINDOW_DAYS):
        raise_err(ERR_CLAIM_WINDOW_CLOSED, "Claim window (paid_at + 30 days) has closed")
    rec = new_record()
    rec.update({
        "enrollment_id": enr["id"],
        "presented_item_id": item["id"],
        "filed_by_user_id": uid,
        "claim_reason": claim_reason,
        "claim_amount_cents": item["amount_cents"],
        "status": "FILED",
        "assigned_bank_user_id": None,
        "provisional_credit_cents": 0,
        "bank_liability_cents": None,
        "customer_liability_cents": None,
        "resolved_by_bank_user_id": None,
        "resolved_at": None,
    })
    store.cases[rec["id"]] = rec
    return success_object(case_out(rec), 201)


@bp.route("/treasury/liability-cases/<cid>", methods=["GET"])
def get_case(cid):
    _, role, user = authenticate()
    authorize(role, user, ALL_ROLES)
    rec = get_or_404(store.cases, cid, "LiabilityCase")
    check_ownership(user, rec["enrollment_id"])
    return success_object(case_out(rec), 200)


@bp.route("/treasury/liability-cases", methods=["GET"])
def list_cases():
    _, role, user = authenticate()
    authorize(role, user, ALL_ROLES)
    enr_filter = check_list_enrollment_param(user)
    records = scope_list(store.cases.values(), user, lambda c: c["enrollment_id"])
    if enr_filter is not None:
        records = [c for c in records if c["enrollment_id"] == enr_filter]
    for param in ("presented_item_id", "filed_by_user_id", "status"):
        v = request.args.get(param)
        if v is not None:
            records = [c for c in records if str(c.get(param)) == v]
    return list_response(records, case_out)


@bp.route("/treasury/liability-cases/<cid>/start-review", methods=["POST"])
def start_review(cid):
    uid, role, _user = authenticate()
    authorize(role, _user, ["BankOps"])
    body_json()
    rec = get_or_404(store.cases, cid, "LiabilityCase")
    enr = store.enrollments[rec["enrollment_id"]]
    guard_enrollment_mutable(enr)
    if rec["status"] != "FILED":
        raise_err(ERR_CASE_NOT_OPEN, "Only a FILED case can enter review")
    rec["status"] = "UNDER_REVIEW"
    rec["assigned_bank_user_id"] = uid
    if rec["claim_amount_cents"] <= PROVISIONAL_CREDIT_CAP_CENTS:
        rec["provisional_credit_cents"] = rec["claim_amount_cents"]
    else:
        rec["provisional_credit_cents"] = 0
    bump(rec)
    return success_object(case_out(rec), 200)


@bp.route("/treasury/liability-cases/<cid>/resolve", methods=["POST"])
def resolve_case(cid):
    uid, role, _user = authenticate()
    authorize(role, _user, ["BankTreasuryManager"])
    body = body_json()
    resolution = req_enum(body, "resolution", RESOLUTIONS)
    rec = get_or_404(store.cases, cid, "LiabilityCase")
    enr = store.enrollments[rec["enrollment_id"]]
    guard_enrollment_mutable(enr)
    if rec["status"] != "UNDER_REVIEW":
        raise_err(ERR_CASE_NOT_OPEN, "Only an UNDER_REVIEW case can be resolved")
    if (
        rec["claim_amount_cents"] > SOD_CASE_THRESHOLD_CENTS
        and rec["assigned_bank_user_id"] == uid
    ):
        raise_err(
            ERR_SOD_CASE_RESOLUTION_CONFLICT,
            "Claims over 25000 cents require a resolver different from the assignee",
        )
    rec["resolved_by_bank_user_id"] = uid
    rec["resolved_at"] = clock.now()
    claim = rec["claim_amount_cents"]
    if resolution == "BANK_LIABLE":
        rec["status"] = "RESOLVED_BANK_LIABLE"
        rec["bank_liability_cents"] = claim
        rec["customer_liability_cents"] = 0
    elif resolution == "CUSTOMER_LIABLE":
        rec["status"] = "RESOLVED_CUSTOMER_LIABLE"
        rec["bank_liability_cents"] = 0
        rec["customer_liability_cents"] = claim
    else:
        rec["status"] = "RESOLVED_SHARED"
        rec["bank_liability_cents"] = claim // 2  # floor; odd cent lands on customer
        rec["customer_liability_cents"] = claim - rec["bank_liability_cents"]
    bump(rec)
    # auto-suspension: ytd loss reaching the threshold suspends an ACTIVE enrollment
    if rec["bank_liability_cents"] > 0:
        threshold = enr.get("loss_suspension_threshold_cents")
        if (
            threshold is not None
            and enr["status"] == "ACTIVE"
            and ytd_bank_loss(enr["id"]) >= threshold
        ):
            enr["status"] = "SUSPENDED"
            bump(enr)  # automatic suspension is a version-bumping write (§2.4)
    return success_object(case_out(rec), 200)


@bp.route("/treasury/liability-cases/<cid>/withdraw", methods=["POST"])
def withdraw_case(cid):
    _, role, user = authenticate()
    authorize(role, user, FILER_ROLES)
    body_json()
    rec = store.cases.get(cid)
    if rec is not None:
        check_ownership(user, rec["enrollment_id"])
    if rec is None:
        get_or_404(store.cases, cid, "LiabilityCase")
    enr = store.enrollments[rec["enrollment_id"]]
    guard_enrollment_active(enr)
    if rec["status"] not in ("FILED", "UNDER_REVIEW"):
        raise_err(ERR_CASE_NOT_OPEN, "Only a FILED or UNDER_REVIEW case can be withdrawn")
    rec["status"] = "WITHDRAWN"  # leaving UNDER_REVIEW reverses the provisional credit
    bump(rec)
    return success_object(case_out(rec), 200)
