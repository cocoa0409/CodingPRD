"""ACH debit block/filter rules (PRD §3.6)."""
from flask import Blueprint, request

import clock
import store
from auth import ALL_ROLES, authenticate, authorize, check_ownership, scope_list
from errors import (
    ERR_ACH_RULE_NOT_ACTIVE,
    ERR_ACH_RULE_WINDOW_OVERLAP,
    ERR_INVALID_REQUEST,
    ERR_STALE_VERSION,
    raise_err,
)
from services import (
    RULE_TYPES,
    SEC_CODES,
    ach_has_overlap,
    guard_enrollment_active,
    guard_enrollment_mutable,
    rule_enrollment_id,
    rule_out,
)
from util import (
    body_json,
    bump,
    get_or_404,
    list_response,
    new_record,
    opt_nullable_date,
    req_date,
    req_enum,
    req_str,
    success_object,
)

bp = Blueprint("ach_rules", __name__)

WRITE_ROLES = ["BankOps", "CustomerAdmin", "CustomerManager"]


def _validate_max(rule_type, body, existing_rule=None):
    """FILTER rules carry max_amount_cents; BLOCK rules omit it (shape)."""
    has_key = "max_amount_cents" in body
    value = body.get("max_amount_cents")
    if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value <= 0):
        raise_err(ERR_INVALID_REQUEST, "max_amount_cents must be a positive integer")
    if rule_type == "BLOCK" and has_key and value is not None:
        raise_err(ERR_INVALID_REQUEST, "BLOCK rules must not carry max_amount_cents")
    if rule_type == "FILTER":
        if has_key:
            if value is None:
                raise_err(ERR_INVALID_REQUEST, "FILTER rules require max_amount_cents")
        elif existing_rule is None or existing_rule.get("max_amount_cents") is None:
            raise_err(ERR_INVALID_REQUEST, "FILTER rules require max_amount_cents")


def _rule_enrollment(rule):
    return store.enrollments[store.accounts[rule["account_id"]]["enrollment_id"]]


@bp.route("/treasury/ach-rules", methods=["POST"])
def create_rule():
    _, role, user = authenticate()
    authorize(role, user, WRITE_ROLES)
    body = body_json()
    account_id = req_str(body, "account_id")
    rule_type = req_enum(body, "rule_type", RULE_TYPES)
    originator = req_str(body, "originator_company_id")
    if not (1 <= len(originator) <= 10):
        raise_err(ERR_INVALID_REQUEST, "originator_company_id must be 1-10 characters")
    sec_code = req_enum(body, "sec_code", SEC_CODES)
    _validate_max(rule_type, body)
    start = req_date(body, "effective_start_date")
    end_present, end = opt_nullable_date(body, "effective_end_date")

    acct = get_or_404(store.accounts, account_id, "Account")
    check_ownership(user, acct["enrollment_id"])
    enr = store.enrollments[acct["enrollment_id"]]
    guard_enrollment_active(enr)
    if ach_has_overlap(acct["id"], originator, sec_code, start, end):
        raise_err(ERR_ACH_RULE_WINDOW_OVERLAP, "Window overlaps an existing ACTIVE/SUSPENDED rule")
    rec = new_record()
    rec.update({
        "account_id": acct["id"],
        "rule_type": rule_type,
        "originator_company_id": originator,
        "sec_code": sec_code,
        "max_amount_cents": body.get("max_amount_cents"),
        "effective_start_date": start,
        "effective_end_date": end if end_present else None,
        "status": "ACTIVE",
    })
    store.ach_rules[rec["id"]] = rec
    return success_object(rule_out(rec), 201)


@bp.route("/treasury/ach-rules/<rid>", methods=["GET"])
def get_rule(rid):
    _, role, user = authenticate()
    authorize(role, user, ALL_ROLES)
    rec = get_or_404(store.ach_rules, rid, "AchDebitRule")
    check_ownership(user, rule_enrollment_id(rec))
    return success_object(rule_out(rec), 200)


@bp.route("/treasury/ach-rules", methods=["GET"])
def list_rules():
    _, role, user = authenticate()
    authorize(role, user, ALL_ROLES)
    records = scope_list(store.ach_rules.values(), user, rule_enrollment_id)
    for param in ("account_id", "status"):
        v = request.args.get(param)
        if v is not None:
            records = [r for r in records if str(r.get(param)) == v]
    return list_response(records, rule_out)


@bp.route("/treasury/ach-rules/<rid>", methods=["PATCH"])
def patch_rule(rid):
    _, role, user = authenticate()
    authorize(role, user, WRITE_ROLES)
    rec = store.ach_rules.get(rid)
    if rec is not None:
        check_ownership(user, rule_enrollment_id(rec))
    body = body_json()
    expected = body.get("expected_ach_rule_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise_err(ERR_INVALID_REQUEST, "expected_ach_rule_version is required and must be an integer")
    # shape: window fields + FILTER/BLOCK max consistency against the stored rule
    if "effective_start_date" in body:
        from util import req_date
        start = req_date(body, "effective_start_date")  # non-nullable
        start_present = True
    else:
        start, start_present = None, False
    end_present, end = opt_nullable_date(body, "effective_end_date")
    if rec is not None:
        _validate_max(rec["rule_type"], body, existing_rule=rec)
    elif "max_amount_cents" in body:
        v = body.get("max_amount_cents")
        if v is not None and (not isinstance(v, int) or isinstance(v, bool) or v <= 0):
            raise_err(ERR_INVALID_REQUEST, "max_amount_cents must be a positive integer")
    if rec is None:
        get_or_404(store.ach_rules, rid, "AchDebitRule")
    if expected != rec["version"]:
        raise_err(ERR_STALE_VERSION, "expected_ach_rule_version is stale")
    enr = _rule_enrollment(rec)
    guard_enrollment_active(enr)
    if rec["status"] not in ("ACTIVE", "SUSPENDED"):
        raise_err(ERR_ACH_RULE_NOT_ACTIVE, "Only ACTIVE or SUSPENDED rules are editable")
    new_start = start if start_present else rec["effective_start_date"]
    new_end = end if end_present else rec["effective_end_date"]
    if ach_has_overlap(rec["account_id"], rec["originator_company_id"], rec["sec_code"],
                       new_start, new_end, exclude_id=rec["id"]):
        raise_err(ERR_ACH_RULE_WINDOW_OVERLAP, "Window overlaps an existing ACTIVE/SUSPENDED rule")
    if "max_amount_cents" in body:
        rec["max_amount_cents"] = body.get("max_amount_cents")
    if start_present:
        rec["effective_start_date"] = start
    if end_present:
        rec["effective_end_date"] = end
    bump(rec)
    return success_object(rule_out(rec), 200)


@bp.route("/treasury/ach-rules/<rid>/suspend", methods=["POST"])
def suspend_rule(rid):
    _, role, user = authenticate()
    authorize(role, user, WRITE_ROLES)
    body_json()
    rec = store.ach_rules.get(rid)
    if rec is not None:
        check_ownership(user, rule_enrollment_id(rec))
    if rec is None:
        get_or_404(store.ach_rules, rid, "AchDebitRule")
    guard_enrollment_active(_rule_enrollment(rec))
    if rec["status"] != "ACTIVE":
        raise_err(ERR_ACH_RULE_NOT_ACTIVE, "Only an ACTIVE rule can be suspended")
    rec["status"] = "SUSPENDED"
    bump(rec)
    return success_object(rule_out(rec), 200)


@bp.route("/treasury/ach-rules/<rid>/resume", methods=["POST"])
def resume_rule(rid):
    _, role, user = authenticate()
    authorize(role, user, WRITE_ROLES)
    body_json()
    rec = store.ach_rules.get(rid)
    if rec is not None:
        check_ownership(user, rule_enrollment_id(rec))
    if rec is None:
        get_or_404(store.ach_rules, rid, "AchDebitRule")
    guard_enrollment_active(_rule_enrollment(rec))
    if rec["status"] != "SUSPENDED":
        raise_err(ERR_ACH_RULE_NOT_ACTIVE, "Only a SUSPENDED rule can be resumed")
    if rec["effective_end_date"] is not None and rec["effective_end_date"] < clock.today():
        raise_err(ERR_ACH_RULE_NOT_ACTIVE, "Rule window has elapsed")
    if ach_has_overlap(rec["account_id"], rec["originator_company_id"], rec["sec_code"],
                       rec["effective_start_date"], rec["effective_end_date"],
                       exclude_id=rec["id"]):
        raise_err(ERR_ACH_RULE_WINDOW_OVERLAP, "Window overlaps an existing ACTIVE/SUSPENDED rule")
    rec["status"] = "ACTIVE"
    bump(rec)
    return success_object(rule_out(rec), 200)


@bp.route("/treasury/ach-rules/<rid>/retire", methods=["POST"])
def retire_rule(rid):
    _, role, user = authenticate()
    authorize(role, user, WRITE_ROLES)
    body_json()
    rec = store.ach_rules.get(rid)
    if rec is not None:
        check_ownership(user, rule_enrollment_id(rec))
    if rec is None:
        get_or_404(store.ach_rules, rid, "AchDebitRule")
    guard_enrollment_mutable(_rule_enrollment(rec))
    if rec["status"] not in ("ACTIVE", "SUSPENDED"):
        raise_err(ERR_ACH_RULE_NOT_ACTIVE, "Only ACTIVE or SUSPENDED rules can be retired")
    rec["status"] = "RETIRED"
    bump(rec)
    return success_object(rule_out(rec), 200)
