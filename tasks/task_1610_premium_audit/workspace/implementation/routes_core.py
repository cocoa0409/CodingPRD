"""Core routes: clock, policies, auditors, classification codes, selection."""
from flask import Blueprint, request

import db
import services
from db import policies, auditors, class_codes
from errors import raise_err, validation
from middleware import (
    Ctx, authenticate, require_role, get_body, check_allowed,
    req_str, req_int, req_enum, req_dt, req_array, opt_number, opt_bool,
    parse_pagination,
)
from response import ok, created, ok_list

bp = Blueprint("core", __name__)

COVERAGE_LINES = {"WC", "GL"}
POLICY_STATUSES = {"ACTIVE", "AUDIT_PENDING", "AUDIT_FINALIZED", "CANCELLED"}
AUDITOR_LEVELS = {"STAFF", "SENIOR"}


# --- clock ---------------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate()
    body = get_body()
    check_allowed(body, {"to_iso8601"})
    to_iso = req_dt(body, "to_iso8601")
    require_role("AuditManager")
    db.set_clock(db.parse_dt(to_iso))
    services.run_sweeps()
    return ok({"current_utc": db.fmt_dt(db.clock_now())})


# --- policies --------------------------------------------------------------------

def _validate_policy_shape(body):
    check_allowed(body, {
        "policy_number", "insured_name", "coverage_line", "state_code",
        "effective_date", "expiration_date", "estimated_annual_premium_cents",
        "minimum_premium_cents", "payroll_estimate_dollars",
        "experience_mod_factor", "class_code_ids",
    })
    vals = {
        "policy_number": req_str(body, "policy_number"),
        "insured_name": req_str(body, "insured_name"),
        "coverage_line": req_enum(body, "coverage_line", COVERAGE_LINES),
        "state_code": req_str(body, "state_code"),
        "effective_date": req_dt(body, "effective_date"),
        "expiration_date": req_dt(body, "expiration_date"),
        "estimated_annual_premium_cents": req_int(
            body, "estimated_annual_premium_cents", gt=0),
        "minimum_premium_cents": req_int(body, "minimum_premium_cents", gt=0),
        "payroll_estimate_dollars": req_int(body, "payroll_estimate_dollars", gt=0),
        "class_code_ids": req_array(body, "class_code_ids", item_type=str),
    }
    if db.parse_dt(vals["effective_date"]) >= db.parse_dt(vals["expiration_date"]):
        validation("effective_date must be strictly before expiration_date")
    if vals["minimum_premium_cents"] > vals["estimated_annual_premium_cents"]:
        validation("minimum_premium_cents must be <= estimated_annual_premium_cents")
    mod = opt_number(body, "experience_mod_factor", 1.00)
    if vals["coverage_line"] == "WC":
        if not (0.75 <= float(mod) <= 1.50):
            validation("WC experience_mod_factor must be within [0.75, 1.50]")
    else:
        if float(mod) != 1.00:
            validation("GL experience_mod_factor must equal 1.00")
    vals["experience_mod_factor"] = mod
    return vals


@bp.route("/policies", methods=["POST"])
def create_policy():
    authenticate()
    body = get_body()
    vals = _validate_policy_shape(body)
    require_role("Underwriter")
    # existence of class code FKs, left to right
    ccs = []
    for cid in vals["class_code_ids"]:
        cc = class_codes.get(cid)
        if cc is None:
            raise_err("ERR_CLASS_CODE_NOT_FOUND",
                      "ClassificationCode id does not exist: %s" % cid)
        ccs.append(cc)
    # each code must match coverage line and state, and overlap the term
    p_start = db.parse_dt(vals["effective_date"])
    p_end = db.parse_dt(vals["expiration_date"])
    for cc in ccs:
        if cc["coverage_line"] != vals["coverage_line"]:
            validation("class code coverage_line does not match policy")
        if cc["state_code"] != vals["state_code"]:
            validation("class code state_code does not match policy")
        if not (db.parse_dt(cc["effective_from"]) <= p_end
                and p_start <= db.parse_dt(cc["effective_to"])):
            validation("class code effective window does not overlap policy term")
    for p in policies.values():
        if p["policy_number"] == vals["policy_number"]:
            raise_err("ERR_DUPLICATE_POLICY_NUMBER", "policy_number already in use")
    vals["status"] = "ACTIVE"
    ent = db.new_entity(vals)
    policies[ent["id"]] = ent
    return created(db.serialize(ent))


@bp.route("/policies", methods=["GET"])
def list_policies():
    authenticate()
    require_role("Insured", "Auditor", "AuditManager", "Underwriter", "BillingClerk")
    limit, offset = parse_pagination()
    status_f = request.args.get("status")
    if status_f is not None and status_f not in POLICY_STATUSES:
        validation("invalid status filter")
    line_f = request.args.get("coverage_line")
    if line_f is not None and line_f not in COVERAGE_LINES:
        validation("invalid coverage_line filter")
    items = list(policies.values())
    if Ctx.role == "Insured":
        items = [p for p in items if p["id"] == Ctx.user_id]
    if status_f:
        items = [p for p in items if p["status"] == status_f]
    if line_f:
        items = [p for p in items if p["coverage_line"] == line_f]
    items = [db.serialize(p) for p in db.by_created(items)]
    return ok_list(items, limit, offset)


def _load_policy(policy_id):
    p = policies.get(policy_id)
    if p is None:
        raise_err("ERR_POLICY_NOT_FOUND", "Policy id does not exist")
    return p


@bp.route("/policies/<policy_id>", methods=["GET"])
def get_policy(policy_id):
    authenticate()
    require_role("Insured", "Auditor", "AuditManager", "Underwriter", "BillingClerk")
    p = _load_policy(policy_id)
    if Ctx.role == "Insured" and p["id"] != Ctx.user_id:
        raise_err("ERR_FORBIDDEN_SCOPE", "Insured may only access own policy graph")
    return ok(db.serialize(p))


@bp.route("/policies/<policy_id>/cancel", methods=["POST"])
def cancel_policy(policy_id):
    authenticate()
    body = get_body()
    check_allowed(body, set())
    require_role("Underwriter")
    p = _load_policy(policy_id)
    if p["status"] == "CANCELLED":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Policy already CANCELLED")
    services.cancel_policy(p)
    return ok(db.serialize(p))


@bp.route("/policies/<policy_id>/mod-revisions", methods=["GET"])
def list_policy_mod_revisions(policy_id):
    authenticate()
    require_role("Insured", "AuditManager", "Underwriter")
    p = _load_policy(policy_id)
    if Ctx.role == "Insured" and p["id"] != Ctx.user_id:
        raise_err("ERR_FORBIDDEN_SCOPE", "Insured may only access own policy graph")
    limit, offset = parse_pagination()
    items = [m for m in db.mod_revisions.values() if m["policy_id"] == p["id"]]
    items = [db.serialize(m) for m in db.by_created(items)]
    return ok_list(items, limit, offset)


# --- auditors ---------------------------------------------------------------------

@bp.route("/auditors", methods=["POST"])
def create_auditor():
    authenticate()
    body = get_body()
    check_allowed(body, {"full_name", "territory_states", "level"})
    vals = {
        "full_name": req_str(body, "full_name"),
        "territory_states": req_array(body, "territory_states",
                                      non_empty=True, item_type=str),
        "level": req_enum(body, "level", AUDITOR_LEVELS),
    }
    require_role("AuditManager")
    ent = db.new_entity(vals)
    auditors[ent["id"]] = ent
    return created(db.serialize(ent))


@bp.route("/auditors", methods=["GET"])
def list_auditors():
    authenticate()
    require_role("Auditor", "AuditManager", "Underwriter")
    limit, offset = parse_pagination()
    items = [db.serialize(a) for a in db.by_created(auditors.values())]
    return ok_list(items, limit, offset)


@bp.route("/auditors/<auditor_id>", methods=["GET"])
def get_auditor(auditor_id):
    authenticate()
    require_role("Auditor", "AuditManager", "Underwriter")
    a = auditors.get(auditor_id)
    if a is None:
        raise_err("ERR_AUDITOR_NOT_FOUND", "Auditor id does not exist")
    return ok(db.serialize(a))


@bp.route("/auditors/<auditor_id>/appointments", methods=["GET"])
def list_auditor_appointments(auditor_id):
    authenticate()
    require_role("Auditor", "AuditManager")
    a = auditors.get(auditor_id)
    if a is None:
        raise_err("ERR_AUDITOR_NOT_FOUND", "Auditor id does not exist")
    limit, offset = parse_pagination()
    items = [ap for ap in db.appointments.values() if ap["auditor_id"] == a["id"]]
    items = [db.serialize(ap) for ap in db.by_created(items)]
    return ok_list(items, limit, offset)


# --- classification codes -----------------------------------------------------------

@bp.route("/classification-codes", methods=["POST"])
def create_class_code():
    authenticate()
    body = get_body()
    check_allowed(body, {
        "code", "description", "state_code", "coverage_line",
        "rate_per_100_cents", "high_hazard", "effective_from", "effective_to",
    })
    vals = {
        "code": req_str(body, "code"),
        "description": req_str(body, "description"),
        "state_code": req_str(body, "state_code"),
        "coverage_line": req_enum(body, "coverage_line", COVERAGE_LINES),
        "rate_per_100_cents": req_int(body, "rate_per_100_cents", gt=0),
        "high_hazard": opt_bool(body, "high_hazard", False),
        "effective_from": req_dt(body, "effective_from"),
        "effective_to": req_dt(body, "effective_to"),
    }
    if db.parse_dt(vals["effective_from"]) >= db.parse_dt(vals["effective_to"]):
        validation("effective_from must be strictly before effective_to")
    require_role("Underwriter")
    for cc in class_codes.values():
        if (cc["code"] == vals["code"]
                and cc["state_code"] == vals["state_code"]
                and cc["coverage_line"] == vals["coverage_line"]):
            raise_err("ERR_DUPLICATE_CLASS_CODE",
                      "(code, state_code, coverage_line) already exists")
    ent = db.new_entity(vals)
    class_codes[ent["id"]] = ent
    return created(db.serialize(ent))


@bp.route("/classification-codes", methods=["GET"])
def list_class_codes():
    authenticate()
    require_role("Insured", "Auditor", "AuditManager", "Underwriter", "BillingClerk")
    limit, offset = parse_pagination()
    state_f = request.args.get("state_code")
    line_f = request.args.get("coverage_line")
    if line_f is not None and line_f not in COVERAGE_LINES:
        validation("invalid coverage_line filter")
    items = list(class_codes.values())
    if state_f:
        items = [c for c in items if c["state_code"] == state_f]
    if line_f:
        items = [c for c in items if c["coverage_line"] == line_f]
    items = [db.serialize(c) for c in db.by_created(items)]
    return ok_list(items, limit, offset)


def _load_class_code(code_id):
    cc = class_codes.get(code_id)
    if cc is None:
        raise_err("ERR_CLASS_CODE_NOT_FOUND", "ClassificationCode id does not exist")
    return cc


@bp.route("/classification-codes/<code_id>", methods=["GET"])
def get_class_code(code_id):
    authenticate()
    require_role("Insured", "Auditor", "AuditManager", "Underwriter", "BillingClerk")
    cc = _load_class_code(code_id)
    return ok(db.serialize(cc))


@bp.route("/classification-codes/<code_id>/payroll-allocations", methods=["GET"])
def list_class_code_allocations(code_id):
    authenticate()
    require_role("Auditor", "AuditManager", "Underwriter")
    cc = _load_class_code(code_id)
    limit, offset = parse_pagination()
    items = [a for a in db.allocations.values() if a["class_code_id"] == cc["id"]]
    items = [db.serialize(a) for a in db.by_created(items)]
    return ok_list(items, limit, offset)


@bp.route("/classification-codes/<code_id>/subcontractor-exposures", methods=["GET"])
def list_class_code_exposures(code_id):
    authenticate()
    require_role("Auditor", "AuditManager", "Underwriter")
    cc = _load_class_code(code_id)
    limit, offset = parse_pagination()
    items = [e for e in db.exposures.values()
             if e["governing_class_code_id"] == cc["id"]]
    items = [db.serialize(e) for e in db.by_created(items)]
    return ok_list(items, limit, offset)


# --- audit selection --------------------------------------------------------------

@bp.route("/audit-selection-runs", methods=["POST"])
def create_selection_run():
    authenticate()
    body = get_body()
    check_allowed(body, set())
    require_role("AuditManager")
    run = services.run_selection()
    return created(db.serialize(run))
