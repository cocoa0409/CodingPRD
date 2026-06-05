import os

from flask import Flask, request

from db import db, now_iso, new_id
from errors import (
    ApiError, err,
    ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE, ERR_NOT_RESOURCE_OWNER,
    ERR_SEGREGATION_OF_DUTIES, ERR_RESOURCE_NOT_FOUND, ERR_INVALID_STATE,
    ERR_ACCOUNT_ON_HOLD, ERR_DUPLICATE_CLAIM, ERR_DUPLICATE_EMAIL,
    ERR_COVERAGE_WINDOW_OVERLAP, ERR_STALE_ACCOUNT_VERSION,
    ERR_EXPENSE_NOT_QUALIFIED, ERR_SERVICE_DATE_OUTSIDE_WINDOW,
    ERR_FILING_WINDOW_CLOSED, ERR_CONTRIBUTION_CAP_EXCEEDED,
    ERR_ELECTION_CAP_EXCEEDED, ERR_INSUFFICIENT_FUNDS,
    ERR_RELIEF_MODE_CONFLICT, ERR_INVALID_REQUEST,
)
from middleware import get_auth, require_role
from response import success, success_list, error_response
import services as svc

app = Flask(__name__)

# ===========================================================================
# Enumerations
# ===========================================================================
MARITAL_STATUSES = {"SINGLE", "MARRIED_JOINT", "MARRIED_SEPARATE"}
ACCOUNT_TYPES = {"HSA", "HEALTH_FSA", "DCFSA"}
COVERAGE_TIERS = {"SELF_ONLY", "FAMILY"}
CONTRIB_SOURCES = {"PAYROLL", "EMPLOYER", "INDIVIDUAL"}
EXPENSE_CATEGORIES = {"MEDICAL", "DENTAL", "VISION", "PRESCRIPTION", "DEPENDENT_CARE", "OTC"}
FSA_RELIEF_MODES = {"NONE", "GRACE_PERIOD", "CARRYOVER"}
ADJUDICATE_DECISIONS = {"APPROVE", "DENY", "REQUEST_DOCS"}
DENIAL_REASONS = {"NOT_QUALIFIED", "OUTSIDE_WINDOW", "INSUFFICIENT_FUNDS", "UNSUBSTANTIATED", "DUPLICATE"}


# ===========================================================================
# Error handlers
# ===========================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_RESOURCE_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_RESOURCE_NOT_FOUND", "Method not allowed.", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.message, e.http_status)
    return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % e, 400)


# ===========================================================================
# Body / field helpers
# ===========================================================================
def get_body():
    if request.data and len(request.data) > 0:
        try:
            body = request.get_json(force=True, silent=True)
        except Exception:
            body = None
        if body is None:
            raise err(ERR_INVALID_REQUEST, "Malformed JSON body.")
        if not isinstance(body, dict):
            raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object.")
        return body
    return {}


def require_str(body, field):
    if field not in body or body[field] is None:
        raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % field)
    v = body[field]
    if not isinstance(v, str) or v == "":
        raise err(ERR_INVALID_REQUEST, "Field %s must be a non-empty string." % field)
    return v


def require_enum(body, field, allowed):
    v = require_str(body, field)
    if v not in allowed:
        raise err(ERR_INVALID_REQUEST, "Field %s has an invalid value." % field)
    return v


def optional_enum(body, field, allowed, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str) or v not in allowed:
        raise err(ERR_INVALID_REQUEST, "Field %s has an invalid value." % field)
    return v


def require_int(body, field, *, positive=False, non_negative=False):
    if field not in body or body[field] is None:
        raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % field)
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, "Field %s must be an integer." % field)
    if positive and v <= 0:
        raise err(ERR_INVALID_REQUEST, "Field %s must be a positive integer." % field)
    if non_negative and v < 0:
        raise err(ERR_INVALID_REQUEST, "Field %s must be >= 0." % field)
    return v


def optional_int(body, field, default, *, non_negative=False):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, "Field %s must be an integer." % field)
    if non_negative and v < 0:
        raise err(ERR_INVALID_REQUEST, "Field %s must be >= 0." % field)
    return v


def require_version(body, field):
    if field not in body or body[field] is None:
        raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % field)
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, "Field %s must be an integer." % field)
    return v


def optional_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a boolean." % field)
    return v


def require_bool(body, field):
    if field not in body or body[field] is None:
        raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % field)
    v = body[field]
    if not isinstance(v, bool):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a boolean." % field)
    return v


# ===========================================================================
# Pagination (PRD §2.3)
# ===========================================================================
def get_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err(ERR_INVALID_REQUEST, "limit must be an integer.")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err(ERR_INVALID_REQUEST, "offset must be an integer.")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items, limit, offset):
    # items already sorted by created_at ASC (PRD §2.3)
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


def sort_by_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ===========================================================================
# Lookup helpers (existence, PRD §2.8)
# ===========================================================================
def find_participant(pid):
    p = db.participants.get(pid)
    if p is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "Participant not found.")
    return p


def find_plan_year(pyid):
    py = db.plan_years.get(pyid)
    if py is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "Plan year not found.")
    return py


def find_account(aid):
    a = db.accounts.get(aid)
    if a is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "Account not found.")
    return a


def find_claim(cid):
    c = db.claims.get(cid)
    if c is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "Claim not found.")
    return c


def find_batch(bid):
    b = db.batches.get(bid)
    if b is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "Reimbursement batch not found.")
    return b


# ===========================================================================
# PARTICIPANTS
# ===========================================================================
@app.route("/participants", methods=["POST"])
def create_participant():
    role, uid = get_auth()
    require_role(role, {"PlanAdmin"})
    body = get_body()

    email = require_str(body, "email")
    full_name = require_str(body, "full_name")
    birth_date = require_str(body, "birth_date")
    bd = svc.parse_date(birth_date)
    if bd is None:
        raise err(ERR_INVALID_REQUEST, "birth_date must be a valid ISO 8601 date.")
    if bd >= svc.clock_date():
        raise err(ERR_INVALID_REQUEST, "birth_date must be in the past.")
    marital_status = optional_enum(body, "marital_status", MARITAL_STATUSES, "SINGLE")
    hdhp_covered = optional_bool(body, "hdhp_covered", False)

    with db.lock:
        # email uniqueness (PRD §3.1)
        for p in db.participants.values():
            if p["email"] == email:
                raise err(ERR_DUPLICATE_EMAIL, "Email already in use.")
        ts = now_iso()
        p = {
            "id": new_id(),
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "_seq": db.next_seq(),
            "email": email,
            "full_name": full_name,
            "birth_date": birth_date,
            "marital_status": marital_status,
            "hdhp_covered": hdhp_covered,
        }
        db.participants[p["id"]] = p
        return success(svc.ser_participant(p), 201)


@app.route("/participants/<pid>", methods=["GET"])
def get_participant(pid):
    role, uid = get_auth()
    require_role(role, {"PlanAdmin", "Participant", "Adjudicator", "FundDisburser"})
    with db.lock:
        p = find_participant(pid)
        return success(svc.ser_participant(p), 200)


@app.route("/participants", methods=["GET"])
def list_participants():
    role, uid = get_auth()
    require_role(role, {"PlanAdmin"})
    limit, offset = get_pagination()
    with db.lock:
        rows = sort_by_created(db.participants.values())
        page, total = paginate(rows, limit, offset)
        return success_list([svc.ser_participant(p) for p in page], limit, offset, total)


@app.route("/participants/<pid>", methods=["PATCH"])
def update_participant(pid):
    role, uid = get_auth()
    require_role(role, {"PlanAdmin"})
    body = get_body()
    expected = require_version(body, "expected_participant_version")
    marital_status = None
    hdhp_covered = None
    if "marital_status" in body and body["marital_status"] is not None:
        marital_status = optional_enum(body, "marital_status", MARITAL_STATUSES, None)
    if "hdhp_covered" in body and body["hdhp_covered"] is not None:
        hdhp_covered = optional_bool(body, "hdhp_covered", None)

    with db.lock:
        p = find_participant(pid)
        if expected != p["version"]:
            raise err(ERR_STALE_ACCOUNT_VERSION, "Stale participant version.")
        if marital_status is not None:
            p["marital_status"] = marital_status
        if hdhp_covered is not None:
            p["hdhp_covered"] = hdhp_covered
        svc.touch(p)
        return success(svc.ser_participant(p), 200)


# ===========================================================================
# PLAN YEARS
# ===========================================================================
@app.route("/plan-years", methods=["POST"])
def create_plan_year():
    role, uid = get_auth()
    require_role(role, {"PlanAdmin"})
    body = get_body()

    label = require_str(body, "label")
    coverage_start = require_str(body, "coverage_start")
    coverage_end = require_str(body, "coverage_end")
    run_out_end = require_str(body, "run_out_end")
    cs = svc.parse_date(coverage_start)
    ce = svc.parse_date(coverage_end)
    ro = svc.parse_date(run_out_end)
    if cs is None or ce is None or ro is None:
        raise err(ERR_INVALID_REQUEST, "coverage_start/coverage_end/run_out_end must be ISO 8601 dates.")
    if ro < ce:
        raise err(ERR_INVALID_REQUEST, "run_out_end must be >= coverage_end.")

    fsa_relief_mode = optional_enum(body, "fsa_relief_mode", FSA_RELIEF_MODES, "NONE")
    grace_period_end = body.get("grace_period_end")
    if grace_period_end is not None and not isinstance(grace_period_end, str):
        raise err(ERR_INVALID_REQUEST, "grace_period_end must be an ISO 8601 date string.")
    carryover_cap_cents = optional_int(body, "carryover_cap_cents", 0, non_negative=True)

    hsa_individual_cap_cents = require_int(body, "hsa_individual_cap_cents", positive=True)
    hsa_family_cap_cents = require_int(body, "hsa_family_cap_cents", positive=True)
    if hsa_family_cap_cents <= hsa_individual_cap_cents:
        raise err(ERR_INVALID_REQUEST, "hsa_family_cap_cents must be > hsa_individual_cap_cents.")
    hsa_catchup_cents = require_int(body, "hsa_catchup_cents", non_negative=True)
    health_fsa_cap_cents = require_int(body, "health_fsa_cap_cents", positive=True)
    dcfsa_cap_joint_cents = require_int(body, "dcfsa_cap_joint_cents", positive=True)
    dcfsa_cap_separate_cents = require_int(body, "dcfsa_cap_separate_cents", positive=True)
    if dcfsa_cap_separate_cents >= dcfsa_cap_joint_cents:
        raise err(ERR_INVALID_REQUEST, "dcfsa_cap_separate_cents must be < dcfsa_cap_joint_cents.")

    # Relief-mode coherence (ERR_RELIEF_MODE_CONFLICT, PRD §3.1)
    if fsa_relief_mode == "GRACE_PERIOD":
        gpe = svc.parse_date(grace_period_end) if grace_period_end else None
        if gpe is None or not (gpe > ce and gpe <= ro):
            raise err(ERR_RELIEF_MODE_CONFLICT,
                      "GRACE_PERIOD requires grace_period_end strictly after coverage_end and on or before run_out_end.")
    elif fsa_relief_mode == "CARRYOVER":
        if carryover_cap_cents <= 0:
            raise err(ERR_RELIEF_MODE_CONFLICT, "CARRYOVER requires carryover_cap_cents > 0.")
        grace_period_end = None
    else:  # NONE
        grace_period_end = None

    with db.lock:
        ts = now_iso()
        py = {
            "id": new_id(),
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "_seq": db.next_seq(),
            "label": label,
            "coverage_start": coverage_start,
            "coverage_end": coverage_end,
            "run_out_end": run_out_end,
            "fsa_relief_mode": fsa_relief_mode,
            "grace_period_end": grace_period_end,
            "carryover_cap_cents": carryover_cap_cents,
            "hsa_individual_cap_cents": hsa_individual_cap_cents,
            "hsa_family_cap_cents": hsa_family_cap_cents,
            "hsa_catchup_cents": hsa_catchup_cents,
            "health_fsa_cap_cents": health_fsa_cap_cents,
            "dcfsa_cap_joint_cents": dcfsa_cap_joint_cents,
            "dcfsa_cap_separate_cents": dcfsa_cap_separate_cents,
            "lifecycle": "OPEN",
        }
        db.plan_years[py["id"]] = py
        return success(svc.ser_plan_year(py), 201)


@app.route("/plan-years/<pyid>", methods=["GET"])
def get_plan_year(pyid):
    role, uid = get_auth()
    require_role(role, {"PlanAdmin", "Participant", "Adjudicator", "FundDisburser"})
    with db.lock:
        py = find_plan_year(pyid)
        return success(svc.ser_plan_year(py), 200)


@app.route("/plan-years", methods=["GET"])
def list_plan_years():
    role, uid = get_auth()
    require_role(role, {"PlanAdmin"})
    limit, offset = get_pagination()
    with db.lock:
        rows = sort_by_created(db.plan_years.values())
        page, total = paginate(rows, limit, offset)
        return success_list([svc.ser_plan_year(p) for p in page], limit, offset, total)


@app.route("/plan-years/<pyid>/settle", methods=["POST"])
def settle_plan_year(pyid):
    role, uid = get_auth()
    require_role(role, {"PlanAdmin"})
    with db.lock:
        py = find_plan_year(pyid)
        # state gate (PRD §3.8)
        if py["lifecycle"] != "OPEN":
            raise err(ERR_INVALID_STATE, "Plan year is already settled.")
        # filing window must have closed (strictly past)
        today = svc.clock_date()
        ro = svc.parse_date(py["run_out_end"])
        if not (today > ro):
            raise err(ERR_INVALID_STATE, "Settlement may run only after the run-out window closes.")
        if py["fsa_relief_mode"] == "GRACE_PERIOD" and py["grace_period_end"]:
            gpe = svc.parse_date(py["grace_period_end"])
            if gpe is not None and not (today > gpe):
                raise err(ERR_INVALID_STATE, "Settlement may run only after the grace period closes.")

        # Eligible accounts under this plan year, created_at ASC (PRD §3.8)
        eligible = [
            a for a in db.accounts.values()
            if a["plan_year_id"] == pyid and a["funding_status"] in ("ACTIVE", "DEPLETED")
        ]
        eligible = sort_by_created(eligible)
        for acct in eligible:
            settle_account(acct, py)

        py["lifecycle"] = "SETTLED"
        svc.touch(py)
        return success(svc.ser_plan_year(py), 200)


def settle_account(acct, py):
    """Year-End-Settlement calc per account (scaffold §1.3 / PRD §3.8)."""
    svc.recompute_balance(acct)
    unused = acct["available_balance_cents"]
    at = acct["account_type"]
    carryover_out = 0
    forfeited = 0

    if at == "HSA":
        carryover_out = 0
        forfeited = 0
    elif at == "HEALTH_FSA":
        if py["fsa_relief_mode"] == "CARRYOVER":
            carryover_out = min(unused, py["carryover_cap_cents"])
            forfeited = unused - carryover_out
        else:  # NONE or GRACE_PERIOD
            carryover_out = 0
            forfeited = unused
    elif at == "DCFSA":
        carryover_out = 0
        forfeited = unused

    if forfeited < 0:
        forfeited = 0
    acct["forfeited_cents"] = forfeited

    if forfeited > 0:
        svc.append_ledger(acct["id"], "FORFEITURE", forfeited,
                          "Forfeited unused balance at year-end settlement.")

    if carryover_out > 0:
        svc.append_ledger(acct["id"], "CARRYOVER_OUT", carryover_out,
                          "Carried unused Health-FSA balance forward at settlement.")
        # destination carryover-holding account (transitive cascade)
        ts = now_iso()
        dest = {
            "id": new_id(),
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "_seq": db.next_seq(),
            "participant_id": acct["participant_id"],
            "plan_year_id": acct["plan_year_id"],
            "account_type": "HEALTH_FSA",
            "coverage_tier": "SELF_ONLY",
            "elected_amount_cents": 0,
            "auto_adjudication_threshold_cents": 0,
            "funding_status": "PENDING",
            "compliance_hold": "CLEAR",
            "contributed_cents": 0,
            "reimbursed_cents": 0,
            "available_balance_cents": 0,
            "forfeited_cents": 0,
            "carried_in_cents": carryover_out,
            "carryover_source_account_id": acct["id"],
        }
        svc.recompute_balance(dest)
        db.accounts[dest["id"]] = dest
        svc.append_ledger(dest["id"], "CARRYOVER_IN", carryover_out,
                          "Received carryover from prior Health-FSA account.")

    acct["funding_status"] = "CLOSED"
    svc.touch(acct)


# ===========================================================================
# ACCOUNTS
# ===========================================================================
@app.route("/accounts", methods=["POST"])
def create_account():
    role, uid = get_auth()
    require_role(role, {"PlanAdmin"})
    body = get_body()

    participant_id = require_str(body, "participant_id")
    plan_year_id = require_str(body, "plan_year_id")
    account_type = require_enum(body, "account_type", ACCOUNT_TYPES)
    coverage_tier = optional_enum(body, "coverage_tier", COVERAGE_TIERS, "SELF_ONLY")
    elected_amount_cents = require_int(body, "elected_amount_cents", non_negative=True)
    auto_threshold = optional_int(body, "auto_adjudication_threshold_cents", 0, non_negative=True)

    with db.lock:
        participant = find_participant(participant_id)
        plan_year = find_plan_year(plan_year_id)

        # FSA-Election-Cap (PRD §3.2) — HEALTH_FSA/DCFSA only.
        if account_type == "HEALTH_FSA":
            allowed = plan_year["health_fsa_cap_cents"]
            if elected_amount_cents > allowed:
                raise err(ERR_ELECTION_CAP_EXCEEDED, "Health-FSA election exceeds plan-year cap.")
        elif account_type == "DCFSA":
            if participant["marital_status"] == "MARRIED_SEPARATE":
                allowed = plan_year["dcfsa_cap_separate_cents"]
            else:
                allowed = plan_year["dcfsa_cap_joint_cents"]
            if elected_amount_cents > allowed:
                raise err(ERR_ELECTION_CAP_EXCEEDED, "DCFSA election exceeds plan-year cap.")

        # Coverage-window-overlap (PRD §3.2) — HEALTH_FSA/DCFSA only.
        if account_type in ("HEALTH_FSA", "DCFSA"):
            check_coverage_overlap(participant_id, account_type, plan_year)

        ts = now_iso()
        acct = {
            "id": new_id(),
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "_seq": db.next_seq(),
            "participant_id": participant_id,
            "plan_year_id": plan_year_id,
            "account_type": account_type,
            "coverage_tier": coverage_tier,
            "elected_amount_cents": elected_amount_cents,
            "auto_adjudication_threshold_cents": auto_threshold,
            "funding_status": "PENDING",
            "compliance_hold": "CLEAR",
            "contributed_cents": 0,
            "reimbursed_cents": 0,
            "available_balance_cents": 0,
            "forfeited_cents": 0,
            "carried_in_cents": 0,
            "carryover_source_account_id": None,
        }
        svc.recompute_balance(acct)
        db.accounts[acct["id"]] = acct
        return success(svc.ser_account(acct), 201)


def check_coverage_overlap(participant_id, account_type, new_py):
    new_start = svc.parse_date(new_py["coverage_start"])
    for other in db.accounts.values():
        if other["participant_id"] != participant_id:
            continue
        if other["account_type"] != account_type:
            continue
        if other["funding_status"] == "CLOSED":
            continue
        other_py = db.plan_years.get(other["plan_year_id"])
        if other_py is None:
            continue
        other_start = svc.parse_date(other_py["coverage_start"])
        if account_type == "HEALTH_FSA":
            new_end = svc.effective_service_end(new_py)
            other_end = svc.effective_service_end(other_py)
            # closed-interval collision: a.start <= b.end AND b.start <= a.end
            if new_start <= other_end and other_start <= new_end:
                raise err(ERR_COVERAGE_WINDOW_OVERLAP,
                          "Coverage window overlaps an existing Health-FSA account.")
        else:  # DCFSA half-open
            new_end = svc.parse_date(new_py["coverage_end"])
            other_end = svc.parse_date(other_py["coverage_end"])
            # half-open collision: a.start < b.end AND b.start < a.end
            if new_start < other_end and other_start < new_end:
                raise err(ERR_COVERAGE_WINDOW_OVERLAP,
                          "Coverage window overlaps an existing DCFSA account.")


@app.route("/accounts/<aid>", methods=["GET"])
def get_account(aid):
    role, uid = get_auth()
    require_role(role, {"PlanAdmin", "Participant", "Adjudicator", "FundDisburser"})
    with db.lock:
        a = find_account(aid)
        return success(svc.ser_account(a), 200)


@app.route("/accounts", methods=["GET"])
def list_accounts():
    role, uid = get_auth()
    require_role(role, {"PlanAdmin", "Participant", "Adjudicator", "FundDisburser"})
    limit, offset = get_pagination()
    f_participant = request.args.get("participant_id")
    f_plan_year = request.args.get("plan_year_id")
    f_carryover = request.args.get("carryover_source_account_id")
    f_type = request.args.get("account_type")
    with db.lock:
        rows = list(db.accounts.values())
        if f_participant is not None:
            rows = [a for a in rows if a["participant_id"] == f_participant]
        if f_plan_year is not None:
            rows = [a for a in rows if a["plan_year_id"] == f_plan_year]
        if f_carryover is not None:
            rows = [a for a in rows if a["carryover_source_account_id"] == f_carryover]
        if f_type is not None:
            rows = [a for a in rows if a["account_type"] == f_type]
        rows = sort_by_created(rows)
        page, total = paginate(rows, limit, offset)
        return success_list([svc.ser_account(a) for a in page], limit, offset, total)


@app.route("/accounts/<aid>/activate", methods=["POST"])
def activate_account(aid):
    role, uid = get_auth()
    require_role(role, {"PlanAdmin"})
    with db.lock:
        a = find_account(aid)
        if a["funding_status"] != "PENDING":
            raise err(ERR_INVALID_STATE, "Only a PENDING account can be activated.")
        if a["account_type"] in ("HEALTH_FSA", "DCFSA"):
            if a["elected_amount_cents"] <= 0:
                raise err(ERR_INVALID_STATE, "FSA/DCFSA activation requires elected_amount_cents > 0.")
        else:  # HSA
            participant = db.participants.get(a["participant_id"])
            if not participant or not participant["hdhp_covered"]:
                raise err(ERR_INVALID_STATE, "HSA activation requires the participant to be HDHP-covered.")
        a["funding_status"] = "ACTIVE"
        svc.recompute_balance(a)
        svc.touch(a)
        return success(svc.ser_account(a), 200)


@app.route("/accounts/<aid>/clear-hold", methods=["POST"])
def clear_hold(aid):
    role, uid = get_auth()
    require_role(role, {"PlanAdmin"})
    with db.lock:
        a = find_account(aid)
        if a["compliance_hold"] != "HELD":
            raise err(ERR_INVALID_STATE, "Account is not on hold.")
        # every REIMBURSED claim must now be substantiated (PRD §3.7)
        for c in db.claims.values():
            if c["account_id"] == aid and c["status"] == "REIMBURSED" and not c["substantiated"]:
                raise err(ERR_INVALID_STATE,
                          "An unsubstantiated reimbursed claim remains on this account.")
        a["compliance_hold"] = "CLEAR"
        svc.touch(a)
        return success(svc.ser_account(a), 200)


# ===========================================================================
# CONTRIBUTIONS
# ===========================================================================
@app.route("/accounts/<aid>/contributions", methods=["POST"])
def post_contribution(aid):
    role, uid = get_auth()
    require_role(role, {"PlanAdmin"})
    body = get_body()

    amount_cents = require_int(body, "amount_cents", positive=True)
    source = require_enum(body, "source", CONTRIB_SOURCES)
    posted_at = require_str(body, "posted_at")
    expected_version = require_version(body, "expected_account_version")

    with db.lock:
        a = find_account(aid)
        # OCC check (PRD §2.9)
        if expected_version != a["version"]:
            raise err(ERR_STALE_ACCOUNT_VERSION, "Stale account version.")
        # HSA contribution cap (PRD §3.3)
        if a["account_type"] == "HSA":
            participant = db.participants.get(a["participant_id"])
            plan_year = db.plan_years.get(a["plan_year_id"])
            allowed = svc.hsa_allowed_cap(a, participant, plan_year)
            prospective = a["contributed_cents"] + amount_cents
            if prospective > allowed:
                raise err(ERR_CONTRIBUTION_CAP_EXCEEDED,
                          "Contribution would exceed the HSA cap.")

        ts = now_iso()
        contrib = {
            "id": new_id(),
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "_seq": db.next_seq(),
            "account_id": aid,
            "amount_cents": amount_cents,
            "source": source,
            "posted_at": posted_at,
            "status": "POSTED",
        }
        db.contributions[contrib["id"]] = contrib
        svc.append_ledger(aid, "CONTRIBUTION", amount_cents,
                          "Posted %s contribution." % source)
        svc.recompute_balance(a)
        svc.apply_funding_transition(a)
        svc.touch(a)
        return success(svc.ser_contribution(contrib), 201)


@app.route("/accounts/<aid>/contributions", methods=["GET"])
def list_contributions(aid):
    role, uid = get_auth()
    require_role(role, {"PlanAdmin", "Participant", "Adjudicator", "FundDisburser"})
    limit, offset = get_pagination()
    with db.lock:
        find_account(aid)
        rows = [c for c in db.contributions.values() if c["account_id"] == aid]
        rows = sort_by_created(rows)
        page, total = paginate(rows, limit, offset)
        return success_list([svc.ser_contribution(c) for c in page], limit, offset, total)


@app.route("/accounts/<aid>/contributions/<cid>/reverse", methods=["POST"])
def reverse_contribution(aid, cid):
    role, uid = get_auth()
    require_role(role, {"PlanAdmin"})
    body = get_body()
    expected_version = require_version(body, "expected_account_version")

    with db.lock:
        a = find_account(aid)  # left-to-right path validation (PRD §2.8)
        contrib = db.contributions.get(cid)
        if contrib is None or contrib["account_id"] != aid:
            raise err(ERR_RESOURCE_NOT_FOUND, "Contribution not found.")
        # state gate before OCC per validation ordering (priority 6 before 16)
        if contrib["status"] != "POSTED":
            raise err(ERR_INVALID_STATE, "Only a POSTED contribution can be reversed.")
        if expected_version != a["version"]:
            raise err(ERR_STALE_ACCOUNT_VERSION, "Stale account version.")

        contrib["status"] = "REVERSED"
        svc.touch(contrib)
        svc.append_ledger(aid, "CONTRIBUTION_REVERSAL", contrib["amount_cents"],
                          "Reversed contribution %s." % cid)
        svc.recompute_balance(a)
        svc.apply_funding_transition(a)
        svc.touch(a)
        return success(svc.ser_contribution(contrib), 200)


# ===========================================================================
# CLAIMS
# ===========================================================================
@app.route("/claims", methods=["POST"])
def create_claim():
    role, uid = get_auth()
    require_role(role, {"Participant", "PlanAdmin"})
    body = get_body()

    account_id = require_str(body, "account_id")
    service_date = require_str(body, "service_date")
    if svc.parse_date(service_date) is None:
        raise err(ERR_INVALID_REQUEST, "service_date must be an ISO 8601 date.")
    expense_category = require_enum(body, "expense_category", EXPENSE_CATEGORIES)
    claimed_amount_cents = require_int(body, "claimed_amount_cents", positive=True)
    substantiated = optional_bool(body, "substantiated", False)

    with db.lock:
        a = find_account(account_id)  # body FK existence (priority 4)
        # ownership for Participant (priority 5)
        if role == "Participant" and a["participant_id"] != uid:
            raise err(ERR_NOT_RESOURCE_OWNER, "Participant does not own this account.")

        plan_year = db.plan_years.get(a["plan_year_id"])

        # expense qualification (priority 9)
        if not svc.expense_qualified(a["account_type"], expense_category):
            raise err(ERR_EXPENSE_NOT_QUALIFIED, "Expense category not qualified for this account type.")
        # service-window (priority 10)
        if not svc.service_date_in_window(plan_year, service_date):
            raise err(ERR_SERVICE_DATE_OUTSIDE_WINDOW, "Service date outside the coverage window.")
        # duplicate-claim guard (priority 11)
        for other in db.claims.values():
            if (other["account_id"] == account_id
                    and other["status"] not in ("DENIED", "VOIDED")
                    and other["service_date"] == service_date
                    and other["expense_category"] == expense_category
                    and other["claimed_amount_cents"] == claimed_amount_cents):
                raise err(ERR_DUPLICATE_CLAIM, "A matching non-terminal claim already exists.")
        # filing-window timeliness (priority 19)
        deadline = svc.effective_filing_deadline(plan_year)
        today = svc.clock_date()
        if today > deadline:
            raise err(ERR_FILING_WINDOW_CLOSED, "Filing window has closed.")

        ts = now_iso()
        claim = {
            "id": new_id(),
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "_seq": db.next_seq(),
            "account_id": account_id,
            "service_date": service_date,
            "expense_category": expense_category,
            "claimed_amount_cents": claimed_amount_cents,
            "substantiated": substantiated,
            "reimbursable_amount_cents": 0,
            "status": "SUBMITTED",
            "denial_reason": None,
            "adjudicated_by": None,
            "reimbursed_by": None,
        }
        db.claims[claim["id"]] = claim
        return success(svc.ser_claim(claim), 201)


@app.route("/claims/<cid>", methods=["GET"])
def get_claim(cid):
    role, uid = get_auth()
    require_role(role, {"PlanAdmin", "Participant", "Adjudicator", "FundDisburser"})
    with db.lock:
        c = find_claim(cid)
        return success(svc.ser_claim(c), 200)


@app.route("/claims", methods=["GET"])
def list_claims():
    role, uid = get_auth()
    require_role(role, {"PlanAdmin", "Participant", "Adjudicator", "FundDisburser"})
    limit, offset = get_pagination()
    f_account = request.args.get("account_id")
    f_participant = request.args.get("participant_id")
    f_status = request.args.get("status")
    with db.lock:
        rows = list(db.claims.values())
        if f_account is not None:
            rows = [c for c in rows if c["account_id"] == f_account]
        if f_participant is not None:
            rows = [c for c in rows
                    if db.accounts.get(c["account_id"], {}).get("participant_id") == f_participant]
        if f_status is not None:
            rows = [c for c in rows if c["status"] == f_status]
        rows = sort_by_created(rows)
        page, total = paginate(rows, limit, offset)
        return success_list([svc.ser_claim(c) for c in page], limit, offset, total)


@app.route("/claims/<cid>/adjudicate", methods=["POST"])
def adjudicate_claim(cid):
    role, uid = get_auth()
    require_role(role, {"Adjudicator"})
    body = get_body()
    decision = require_enum(body, "decision", ADJUDICATE_DECISIONS)
    denial_reason_in = body.get("denial_reason")
    if denial_reason_in is not None:
        if not isinstance(denial_reason_in, str) or denial_reason_in not in DENIAL_REASONS:
            raise err(ERR_INVALID_REQUEST, "denial_reason has an invalid value.")

    with db.lock:
        claim = find_claim(cid)
        account = db.accounts.get(claim["account_id"])
        plan_year = db.plan_years.get(account["plan_year_id"]) if account else None

        if decision == "APPROVE":
            if claim["status"] != "SUBMITTED":
                raise err(ERR_INVALID_STATE, "Only a SUBMITTED claim can be approved.")
            # re-check qualification & window (PRD §3.4)
            if not svc.expense_qualified(account["account_type"], claim["expense_category"]):
                raise err(ERR_EXPENSE_NOT_QUALIFIED, "Expense category not qualified.")
            if not svc.service_date_in_window(plan_year, claim["service_date"]):
                raise err(ERR_SERVICE_DATE_OUTSIDE_WINDOW, "Service date outside the coverage window.")
            # substantiation gate
            if not (claim["substantiated"]
                    or claim["claimed_amount_cents"] <= account["auto_adjudication_threshold_cents"]):
                raise err(ERR_INVALID_STATE,
                          "Claim must be substantiated or at/below the auto-adjudication threshold.")
            # forward-looking reimbursable
            svc.recompute_balance(account)
            reimbursable = svc.forward_looking_reimbursable(account, claim["claimed_amount_cents"])
            if reimbursable <= 0:
                raise err(ERR_INSUFFICIENT_FUNDS, "No projected funds available for this claim.")
            claim["reimbursable_amount_cents"] = reimbursable
            claim["adjudicated_by"] = uid
            claim["denial_reason"] = None
            claim["status"] = "APPROVED"
            svc.touch(claim)
            return success(svc.ser_claim(claim), 200)

        elif decision == "REQUEST_DOCS":
            if claim["status"] != "SUBMITTED":
                raise err(ERR_INVALID_STATE, "Only a SUBMITTED claim can be sent to substantiation.")
            if claim["substantiated"]:
                raise err(ERR_INVALID_STATE, "An already-substantiated claim cannot request docs.")
            if claim["claimed_amount_cents"] <= account["auto_adjudication_threshold_cents"]:
                raise err(ERR_INVALID_STATE,
                          "Claim is at/below the auto-adjudication threshold; docs not required.")
            claim["adjudicated_by"] = uid
            claim["status"] = "PENDING_SUBSTANTIATION"
            svc.touch(claim)
            return success(svc.ser_claim(claim), 200)

        else:  # DENY
            if claim["status"] not in ("SUBMITTED", "PENDING_SUBSTANTIATION"):
                raise err(ERR_INVALID_STATE, "Claim cannot be denied from its current state.")
            if claim["status"] == "PENDING_SUBSTANTIATION":
                claim["denial_reason"] = "UNSUBSTANTIATED"
            else:
                claim["denial_reason"] = denial_reason_in if denial_reason_in else "NOT_QUALIFIED"
            claim["adjudicated_by"] = uid
            claim["status"] = "DENIED"
            svc.touch(claim)
            return success(svc.ser_claim(claim), 200)


@app.route("/claims/<cid>/resubmit", methods=["POST"])
def resubmit_claim(cid):
    role, uid = get_auth()
    require_role(role, {"Participant", "PlanAdmin"})
    body = get_body()
    substantiated = require_bool(body, "substantiated")
    if substantiated is not True:
        raise err(ERR_INVALID_REQUEST, "resubmit requires substantiated == true.")

    with db.lock:
        claim = find_claim(cid)
        account = db.accounts.get(claim["account_id"])
        # ownership for Participant (priority 5)
        if role == "Participant" and account and account["participant_id"] != uid:
            raise err(ERR_NOT_RESOURCE_OWNER, "Participant does not own this account.")
        if claim["status"] != "PENDING_SUBSTANTIATION":
            raise err(ERR_INVALID_STATE, "Only a PENDING_SUBSTANTIATION claim can be resubmitted.")
        claim["substantiated"] = True
        claim["status"] = "SUBMITTED"
        svc.touch(claim)
        return success(svc.ser_claim(claim), 200)


@app.route("/claims/<cid>/void", methods=["POST"])
def void_claim(cid):
    role, uid = get_auth()
    require_role(role, {"Adjudicator", "PlanAdmin"})
    with db.lock:
        claim = find_claim(cid)
        account = db.accounts.get(claim["account_id"])

        if claim["status"] == "APPROVED":
            # Adjudicator path (PlanAdmin also allowed by role gate)
            claim["reimbursable_amount_cents"] = 0
            claim["status"] = "VOIDED"
            svc.touch(claim)
            return success(svc.ser_claim(claim), 200)
        elif claim["status"] == "REIMBURSED":
            # PlanAdmin clawback path
            if role != "PlanAdmin":
                raise err(ERR_INVALID_STATE, "Only a PlanAdmin may claw back a reimbursed claim.")
            svc.append_ledger(account["id"], "REIMBURSEMENT_REVERSAL",
                              claim["reimbursable_amount_cents"],
                              "Clawback of reimbursed claim %s." % cid, claim_id=cid)
            claim["status"] = "VOIDED"
            svc.touch(claim)
            svc.recompute_balance(account)
            svc.apply_funding_transition(account)
            # lift hold if this was the only unsubstantiated reimbursed claim (PRD §3.7)
            if account["compliance_hold"] == "HELD":
                remaining = any(
                    c["account_id"] == account["id"]
                    and c["status"] == "REIMBURSED"
                    and not c["substantiated"]
                    for c in db.claims.values()
                )
                if not remaining:
                    account["compliance_hold"] = "CLEAR"
            svc.touch(account)
            return success(svc.ser_claim(claim), 200)
        else:
            raise err(ERR_INVALID_STATE, "Claim cannot be voided from its current state.")


@app.route("/claims/<cid>/ledger-entries", methods=["GET"])
def list_claim_ledger(cid):
    role, uid = get_auth()
    require_role(role, {"PlanAdmin", "Participant", "Adjudicator", "FundDisburser"})
    limit, offset = get_pagination()
    with db.lock:
        find_claim(cid)
        rows = [e for e in db.ledger_entries.values() if e["claim_id"] == cid]
        rows = sort_by_created(rows)
        page, total = paginate(rows, limit, offset)
        return success_list([svc.ser_ledger(e) for e in page], limit, offset, total)


# ===========================================================================
# REIMBURSEMENT BATCHES
# ===========================================================================
@app.route("/reimbursement-batches", methods=["POST"])
def create_batch():
    role, uid = get_auth()
    require_role(role, {"FundDisburser", "PlanAdmin"})
    body = get_body()

    participant_id = require_str(body, "participant_id")
    claim_ids = body.get("claim_ids")
    if not isinstance(claim_ids, list) or len(claim_ids) == 0:
        raise err(ERR_INVALID_REQUEST, "claim_ids must be a non-empty array.")
    for cid in claim_ids:
        if not isinstance(cid, str):
            raise err(ERR_INVALID_REQUEST, "claim_ids must contain string ids.")

    with db.lock:
        find_participant(participant_id)  # body FK existence (priority 4)
        for cid in claim_ids:
            claim = db.claims.get(cid)
            if claim is None:
                raise err(ERR_RESOURCE_NOT_FOUND, "Claim %s not found." % cid)
            account = db.accounts.get(claim["account_id"])
            if account is None or account["participant_id"] != participant_id:
                raise err(ERR_RESOURCE_NOT_FOUND,
                          "Claim %s is not owned by participant." % cid)
            if claim["status"] != "APPROVED":
                raise err(ERR_INVALID_STATE, "Claim %s is not APPROVED." % cid)

        ts = now_iso()
        batch = {
            "id": new_id(),
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "_seq": db.next_seq(),
            "participant_id": participant_id,
            "claim_ids": list(claim_ids),
            "total_reimbursed_cents": 0,
            "status": "DRAFT",
        }
        db.batches[batch["id"]] = batch
        return success(svc.ser_batch(batch), 201)


@app.route("/reimbursement-batches/<bid>", methods=["GET"])
def get_batch(bid):
    role, uid = get_auth()
    require_role(role, {"PlanAdmin", "FundDisburser"})
    with db.lock:
        b = find_batch(bid)
        return success(svc.ser_batch(b), 200)


@app.route("/reimbursement-batches", methods=["GET"])
def list_batches():
    role, uid = get_auth()
    require_role(role, {"PlanAdmin", "FundDisburser"})
    limit, offset = get_pagination()
    f_participant = request.args.get("participant_id")
    with db.lock:
        rows = list(db.batches.values())
        if f_participant is not None:
            rows = [b for b in rows if b["participant_id"] == f_participant]
        rows = sort_by_created(rows)
        page, total = paginate(rows, limit, offset)
        return success_list([svc.ser_batch(b) for b in page], limit, offset, total)


@app.route("/reimbursement-batches/<bid>/disburse", methods=["POST"])
def disburse_batch(bid):
    role, uid = get_auth()
    require_role(role, {"FundDisburser"})
    body = get_body()
    expected_version = require_version(body, "expected_account_version")

    with db.lock:
        batch = find_batch(bid)
        if batch["status"] != "DRAFT":
            raise err(ERR_INVALID_STATE, "Only a DRAFT batch can be disbursed.")

        member_claims = []
        for cid in batch["claim_ids"]:
            claim = db.claims.get(cid)
            if claim is None:
                raise err(ERR_RESOURCE_NOT_FOUND, "Claim %s not found." % cid)
            member_claims.append(claim)

        reimbursed_subset = []
        skipped_any = False
        first = True
        # expected_account_version is the disburser's last-observed version of the
        # account being drawn down (PRD §2.9). It is compared the FIRST time each
        # account is touched in this disburse; once a reimbursement bumps that
        # account's version, later claims on the same account must not re-fail OCC.
        occ_checked = set()

        def reject_or_skip(spec, msg):
            # While no claim has yet succeeded (`first` True), a failing claim is a
            # hard reject that leaves the batch DRAFT (PRD §3.6). Once at least one
            # claim has succeeded, a later failing claim is simply skipped (PARTIAL).
            nonlocal skipped_any
            if first:
                raise err(spec, msg)
            skipped_any = True

        for claim in member_claims:
            account = db.accounts.get(claim["account_id"])

            # state: claim must still be APPROVED (priority 6)
            if claim["status"] != "APPROVED":
                reject_or_skip(ERR_INVALID_STATE, "Claim %s is not APPROVED." % claim["id"])
                continue

            # segregation of duties (priority 7) — first among per-claim domain checks
            if uid == claim["adjudicated_by"]:
                reject_or_skip(ERR_SEGREGATION_OF_DUTIES,
                               "Disburser may not pay a claim they adjudicated.")
                continue

            # compliance hold (priority 8)
            if account["compliance_hold"] != "CLEAR":
                reject_or_skip(ERR_ACCOUNT_ON_HOLD, "Account is on a compliance hold.")
                continue

            # OCC (priority 16) — checked on first touch of each account
            if account["id"] not in occ_checked:
                if expected_version != account["version"]:
                    reject_or_skip(ERR_STALE_ACCOUNT_VERSION, "Stale account version.")
                    continue
                occ_checked.add(account["id"])

            # funds: chronological cash-on-hand >= stored reimbursable (priority 15)
            svc.recompute_balance(account)
            if account["funding_status"] != "ACTIVE":
                reject_or_skip(ERR_INVALID_STATE, "Account is not ACTIVE.")
                continue
            if account["available_balance_cents"] < claim["reimbursable_amount_cents"]:
                reject_or_skip(ERR_INSUFFICIENT_FUNDS, "Insufficient cash on hand.")
                continue

            # ---- reimburse this claim ----
            svc.append_ledger(account["id"], "REIMBURSEMENT",
                              claim["reimbursable_amount_cents"],
                              "Reimbursed claim %s under chronological algorithm." % claim["id"],
                              claim_id=claim["id"])
            claim["reimbursed_by"] = uid
            claim["status"] = "REIMBURSED"
            svc.touch(claim)
            svc.recompute_balance(account)
            svc.apply_funding_transition(account)
            if not claim["substantiated"] and account["compliance_hold"] == "CLEAR":
                account["compliance_hold"] = "HELD"
            svc.touch(account)
            reimbursed_subset.append(claim)
            first = False

        # finalize batch status
        total = sum(c["reimbursable_amount_cents"] for c in reimbursed_subset)
        batch["total_reimbursed_cents"] = total
        if skipped_any and reimbursed_subset:
            batch["status"] = "PARTIAL"
        else:
            batch["status"] = "SETTLED"
        svc.touch(batch)
        return success(svc.ser_batch(batch), 200)


# ===========================================================================
# ACCOUNT LEDGER
# ===========================================================================
@app.route("/accounts/<aid>/ledger-entries", methods=["GET"])
def list_account_ledger(aid):
    role, uid = get_auth()
    require_role(role, {"PlanAdmin", "Participant", "Adjudicator", "FundDisburser"})
    limit, offset = get_pagination()
    f_type = request.args.get("entry_type")
    with db.lock:
        find_account(aid)
        rows = [e for e in db.ledger_entries.values() if e["account_id"] == aid]
        if f_type is not None:
            rows = [e for e in rows if e["entry_type"] == f_type]
        rows = sort_by_created(rows)
        page, total = paginate(rows, limit, offset)
        return success_list([svc.ser_ledger(e) for e in page], limit, offset, total)


# ===========================================================================
# CLOCK (test-driving)
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    role, uid = get_auth()
    require_role(role, {"PlanAdmin"})
    body = get_body()
    to_iso = require_str(body, "to_iso8601")
    if svc.parse_date(to_iso) is None:
        raise err(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 instant.")
    with db.lock:
        db.clock["current_utc"] = to_iso
        return success(svc.ser_clock(db.clock), 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
