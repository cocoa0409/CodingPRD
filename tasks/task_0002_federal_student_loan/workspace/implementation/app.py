"""Federal Student Loan Servicing API — Flask application.

Boots empty (no seeding). All state in process memory. start.sh re-launches
on every test under per-test-server isolation.
"""
import os
import uuid
from datetime import datetime, timezone

from flask import Flask, request

from db import store, utc_now_iso
from errors import (
    ApiError, raise_err,
    ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED,
    ERR_LOAN_NOT_FOUND, ERR_BORROWER_NOT_FOUND, ERR_RESOURCE_NOT_FOUND,
    ERR_INVALID_STATE, ERR_PLAN_ALREADY_ACTIVE,
    ERR_NOT_VETERAN, ERR_PSLF_INSUFFICIENT_PAYMENTS,
    ERR_DEFAULT_THRESHOLD_NOT_MET, ERR_REHABILITATION_NOT_QUALIFIED,
    ERR_STALE_LOAN_VERSION, ERR_STALE_APPLICATION_VERSION,
    ERR_INVALID_PERIOD, ERR_FUTURE_PAYMENT,
    ERR_PAYMENT_AMOUNT_OUT_OF_RANGE, ERR_INVALID_REQUEST,
)
from middleware import get_auth, require_role
from response import success_object, success_array, error_response
import services
from services import (
    active_plan_at, active_plan_for_loan, accrue_loan_to_now, accrue_all_loans,
    borrower_view, delinquency_days, latest_certified_certification,
    loan_status_history, loan_status_at, loan_view, payment_is_pslf_qualifying,
    pslf_qualifying_payment_count, recompute_monthly_payment_for_plan,
    recompute_pslf_for_borrower, get_current_utc_dt,
)
from calculations import (
    parse_iso_to_dt, parse_iso_to_date, compute_monthly_payment_cents,
)


app = Flask(__name__)
app.url_map.strict_slashes = False

API_PREFIX = "/loan-servicing"


# ============================================================
# Global error handler
# ============================================================

@app.errorhandler(ApiError)
def handle_api_error(err: ApiError):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_RESOURCE_NOT_FOUND", "Path not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_INVALID_REQUEST", "Method not allowed", 400)


@app.errorhandler(Exception)
def handle_exception(e):
    # Unknown server error -> return as ERR_INVALID_REQUEST 400 to keep envelope stable.
    # In production this would be 500; per benchmark spirit, surface as a controlled envelope.
    return error_response("ERR_INVALID_REQUEST", f"Internal error: {e}", 500)


# ============================================================
# Helpers
# ============================================================

def gen_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    # All server timestamps trace to the server logical clock (PRD §2.9),
    # since the clock drives every time-sensitive computation. created_at /
    # updated_at / effective_at all derive from it so that the test-driving
    # clock advance produces deterministic chronological ordering.
    return store.current_utc


def get_json_body() -> dict:
    """Get JSON body; return {} if absent/empty. Raises ERR_INVALID_REQUEST on bad JSON."""
    if not request.data:
        return {}
    try:
        body = request.get_json(silent=False, force=True)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def require_fields(body: dict, fields: list):
    for f in fields:
        if f not in body:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field: {f}")


def pagination_params() -> tuple:
    limit_str = request.args.get("limit")
    offset_str = request.args.get("offset")
    try:
        limit = int(limit_str) if limit_str is not None else 10
        offset = int(offset_str) if offset_str is not None else 0
    except (TypeError, ValueError):
        raise_err(ERR_INVALID_REQUEST, "limit/offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        raise_err(ERR_INVALID_REQUEST, "limit must be 1..100; offset >= 0")
    return limit, offset


def paginate(items: list, limit: int, offset: int) -> tuple:
    total = len(items)
    return items[offset:offset + limit], total


def common_create(obj: dict, common_version: bool = True) -> dict:
    """Stamp id, created_at, updated_at, version onto a new resource dict."""
    if "id" not in obj:
        obj["id"] = gen_id()
    now = now_iso()
    obj["created_at"] = now
    obj["updated_at"] = now
    if common_version:
        obj["version"] = 1
    return obj


def bump_version(obj: dict):
    obj["version"] = int(obj.get("version", 1)) + 1
    obj["updated_at"] = now_iso()


def ownership_check_borrower(role: str, user_id: str, borrower_id: str):
    """For Borrower role, verify the resource's borrower_id matches X-User-ID."""
    if role == "Borrower" and user_id != borrower_id:
        raise_err(ERR_UNAUTHORIZED, "Borrower can only access own resources")


def get_loan_or_404(loan_id: str) -> dict:
    loan = store.loans.get(loan_id)
    if not loan:
        raise_err(ERR_LOAN_NOT_FOUND, f"Loan {loan_id} not found")
    return loan


def get_borrower_or_404(borrower_id: str) -> dict:
    b = store.borrowers.get(borrower_id)
    if not b:
        raise_err(ERR_BORROWER_NOT_FOUND, f"Borrower {borrower_id} not found")
    return b


def get_resource_or_404(coll: dict, rid: str) -> dict:
    v = coll.get(rid)
    if not v:
        raise_err(ERR_RESOURCE_NOT_FOUND, f"Resource {rid} not found")
    return v


def write_status_change(loan_id: str, from_status: str, to_status: str,
                        reason_code: str, actor_role: str) -> dict:
    sc_id = gen_id()
    now = now_iso()
    row = {
        "id": sc_id,
        "loan_id": loan_id,
        "from_status": from_status,
        "to_status": to_status,
        "reason_code": reason_code,
        "actor_role": actor_role,
        "effective_at": now,
        "created_at": now,
    }
    store.status_changes[sc_id] = row
    # Also stamp the loan's status_change_at
    loan = store.loans.get(loan_id)
    if loan:
        loan["status_change_at"] = now
    return row


# ============================================================
# Borrowers
# ============================================================

@app.route(f"{API_PREFIX}/borrowers", methods=["POST"])
def create_borrower():
    _, role = get_auth()
    require_role(role, ["LoanServicer"])
    body = get_json_body()
    require_fields(body, ["full_name", "ssn_last4"])
    full_name = body.get("full_name")
    ssn_last4 = body.get("ssn_last4")
    is_veteran = body.get("is_veteran", False)
    if not isinstance(full_name, str) or not (1 <= len(full_name) <= 200):
        raise_err(ERR_INVALID_REQUEST, "full_name must be a string 1..200 chars")
    if not isinstance(ssn_last4, str) or not (len(ssn_last4) == 4 and ssn_last4.isdigit()):
        raise_err(ERR_INVALID_REQUEST, "ssn_last4 must be exactly 4 digits")
    if not isinstance(is_veteran, bool):
        raise_err(ERR_INVALID_REQUEST, "is_veteran must be boolean")
    obj = {
        "full_name": full_name,
        "ssn_last4": ssn_last4,
        "is_veteran": is_veteran,
    }
    common_create(obj)
    store.borrowers[obj["id"]] = obj
    return success_object(borrower_view(obj), 201)


@app.route(f"{API_PREFIX}/borrowers/<bid>", methods=["GET"])
def get_borrower(bid):
    uid, role = get_auth()
    require_role(role, ["LoanServicer", "Borrower", "CollectionsAgent"])
    b = get_borrower_or_404(bid)
    ownership_check_borrower(role, uid, b["id"])
    return success_object(borrower_view(b), 200)


@app.route(f"{API_PREFIX}/borrowers", methods=["GET"])
def list_borrowers():
    _, role = get_auth()
    require_role(role, ["LoanServicer"])
    limit, offset = pagination_params()
    items = list(store.borrowers.values())
    items.sort(key=lambda b: b["created_at"])
    items, total = paginate(items, limit, offset)
    return success_array([borrower_view(b) for b in items], limit, offset, total)


# ============================================================
# Loans
# ============================================================

LOAN_TYPES = {"DIRECT_SUB", "DIRECT_UNSUB", "DIRECT_PLUS"}


@app.route(f"{API_PREFIX}/loans", methods=["POST"])
def create_loan():
    _, role = get_auth()
    require_role(role, ["LoanServicer"])
    body = get_json_body()
    require_fields(body, ["borrower_id", "loan_type", "principal_cents",
                          "interest_rate_bps", "disbursement_date"])
    borrower_id = body["borrower_id"]
    loan_type = body["loan_type"]
    principal_cents = body["principal_cents"]
    rate_bps = body["interest_rate_bps"]
    disbursement_date = body["disbursement_date"]

    # Borrower existence — per validation priority §1.4 #4 (above general body checks).
    get_borrower_or_404(borrower_id)

    if loan_type not in LOAN_TYPES:
        raise_err(ERR_INVALID_REQUEST, "loan_type must be DIRECT_SUB/UNSUB/PLUS")
    if not isinstance(principal_cents, int) or principal_cents < 100:
        raise_err(ERR_INVALID_REQUEST, "principal_cents must be integer >= 100")
    if not isinstance(rate_bps, int) or not (1 <= rate_bps <= 2000):
        raise_err(ERR_INVALID_REQUEST, "interest_rate_bps must be integer in [1,2000]")
    try:
        parse_iso_to_dt(disbursement_date)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "disbursement_date must be ISO 8601")

    loan = {
        "borrower_id": borrower_id,
        "loan_type": loan_type,
        "principal_cents": principal_cents,
        "interest_rate_bps": rate_bps,
        "disbursement_date": disbursement_date,
        "status": "ORIGINATED",
        "principal_balance_cents": principal_cents,
        "accrued_interest_cents": 0,
        "capitalized_interest_cents": 0,
        "last_accrual_date": disbursement_date,
        "status_change_at": None,
        "pslf_qualifying_payment_count": 0,
        "delinquency_days": 0,
    }
    common_create(loan)
    store.loans[loan["id"]] = loan
    return success_object(loan_view(loan), 201)


@app.route(f"{API_PREFIX}/loans/<lid>", methods=["GET"])
def get_loan(lid):
    uid, role = get_auth()
    require_role(role, ["LoanServicer", "Borrower", "CollectionsAgent"])
    loan = get_loan_or_404(lid)
    ownership_check_borrower(role, uid, loan["borrower_id"])
    # Accrue before return so the read reflects the latest clock state.
    accrue_loan_to_now(loan)
    return success_object(loan_view(loan), 200)


@app.route(f"{API_PREFIX}/loans", methods=["GET"])
def list_loans():
    uid, role = get_auth()
    require_role(role, ["LoanServicer", "CollectionsAgent", "Borrower"])
    # Note: scaffold §1.5 lists [LoanServicer, CollectionsAgent] but PRD §4 same.
    # Borrowers viewing their own loans must filter to their own borrower_id;
    # we'll permit Borrower role and restrict to own.
    limit, offset = pagination_params()
    borrower_id = request.args.get("borrower_id")

    items = list(store.loans.values())
    if borrower_id:
        items = [l for l in items if l["borrower_id"] == borrower_id]
    if role == "Borrower":
        items = [l for l in items if l["borrower_id"] == uid]
    items.sort(key=lambda l: l["created_at"])
    items, total = paginate(items, limit, offset)
    for l in items:
        accrue_loan_to_now(l)
    return success_array([loan_view(l) for l in items], limit, offset, total)


def _loan_transition(lid: str, allowed_role: list, from_status_set: set,
                     to_status: str, reason_code: str, actor_role: str):
    """Generic loan state transition helper. Returns the transitioned loan."""
    loan = get_loan_or_404(lid)
    if loan["status"] not in from_status_set:
        raise_err(ERR_INVALID_STATE,
                  f"Loan status is {loan['status']}, required one of {sorted(from_status_set)}")
    # Accrue interest up to current clock BEFORE the transition (so the day count is correct).
    accrue_loan_to_now(loan)
    prev = loan["status"]
    loan["status"] = to_status
    write_status_change(lid, prev, to_status, reason_code, actor_role)
    bump_version(loan)
    return loan


@app.route(f"{API_PREFIX}/loans/<lid>/enter-school", methods=["POST"])
def loan_enter_school(lid):
    _, role = get_auth()
    require_role(role, ["LoanServicer"])
    loan = _loan_transition(lid, ["LoanServicer"], {"ORIGINATED"},
                            "IN_SCHOOL", "GRACE_AUTO_START", role)
    return success_object(loan_view(loan), 200)


@app.route(f"{API_PREFIX}/loans/<lid>/graduate", methods=["POST"])
def loan_graduate(lid):
    _, role = get_auth()
    require_role(role, ["LoanServicer"])
    loan = _loan_transition(lid, ["LoanServicer"], {"IN_SCHOOL"},
                            "GRACE", "GRACE_AUTO_START", role)
    return success_object(loan_view(loan), 200)


@app.route(f"{API_PREFIX}/loans/<lid>/start-repayment", methods=["POST"])
def loan_start_repayment(lid):
    _, role = get_auth()
    require_role(role, ["LoanServicer"])
    loan = _loan_transition(lid, ["LoanServicer"], {"GRACE"},
                            "REPAYMENT", "GRACE_AUTO_END", role)
    return success_object(loan_view(loan), 200)


@app.route(f"{API_PREFIX}/loans/<lid>/request-deferment", methods=["POST"])
def loan_request_deferment(lid):
    uid, role = get_auth()
    require_role(role, ["Borrower"])
    loan = get_loan_or_404(lid)
    ownership_check_borrower(role, uid, loan["borrower_id"])
    if loan["status"] != "REPAYMENT":
        raise_err(ERR_INVALID_STATE, f"Loan status is {loan['status']}, required REPAYMENT")
    accrue_loan_to_now(loan)
    prev = loan["status"]
    loan["status"] = "DEFERMENT"
    write_status_change(lid, prev, "DEFERMENT", "DEFERMENT_REQUEST", role)
    bump_version(loan)
    return success_object(loan_view(loan), 200)


@app.route(f"{API_PREFIX}/loans/<lid>/request-forbearance", methods=["POST"])
def loan_request_forbearance(lid):
    uid, role = get_auth()
    require_role(role, ["Borrower"])
    loan = get_loan_or_404(lid)
    ownership_check_borrower(role, uid, loan["borrower_id"])
    if loan["status"] != "REPAYMENT":
        raise_err(ERR_INVALID_STATE, f"Loan status is {loan['status']}, required REPAYMENT")
    accrue_loan_to_now(loan)
    prev = loan["status"]
    loan["status"] = "FORBEARANCE"
    write_status_change(lid, prev, "FORBEARANCE", "FORBEARANCE_REQUEST", role)
    bump_version(loan)
    return success_object(loan_view(loan), 200)


@app.route(f"{API_PREFIX}/loans/<lid>/resume-repayment", methods=["POST"])
def loan_resume_repayment(lid):
    _, role = get_auth()
    require_role(role, ["LoanServicer"])
    loan = get_loan_or_404(lid)
    if loan["status"] not in ("DEFERMENT", "FORBEARANCE"):
        raise_err(ERR_INVALID_STATE,
                  f"Loan status is {loan['status']}, required DEFERMENT or FORBEARANCE")
    # Accrue up to now (final accrual under the paused-status window).
    accrue_loan_to_now(loan)
    # Capitalize: accrued -> principal
    accrued = int(loan["accrued_interest_cents"])
    loan["principal_balance_cents"] = int(loan["principal_balance_cents"]) + accrued
    loan["capitalized_interest_cents"] = int(loan["capitalized_interest_cents"]) + accrued
    loan["accrued_interest_cents"] = 0
    prev = loan["status"]
    loan["status"] = "REPAYMENT"
    write_status_change(lid, prev, "REPAYMENT", "RESUME_REPAYMENT", role)
    bump_version(loan)
    return success_object(loan_view(loan), 200)


@app.route(f"{API_PREFIX}/loans/<lid>/declare-default", methods=["POST"])
def loan_declare_default(lid):
    _, role = get_auth()
    require_role(role, ["CollectionsAgent"])
    loan = get_loan_or_404(lid)
    if loan["status"] != "REPAYMENT":
        raise_err(ERR_INVALID_STATE, f"Loan status is {loan['status']}, required REPAYMENT")
    if delinquency_days(loan) < 270:
        raise_err(ERR_DEFAULT_THRESHOLD_NOT_MET,
                  "delinquency_days must be >= 270 to declare default")
    accrue_loan_to_now(loan)
    prev = loan["status"]
    loan["status"] = "DEFAULT"
    write_status_change(lid, prev, "DEFAULT", "DEFAULT_DECLARATION", role)
    # Cascade: every ACTIVE RepaymentPlan for this loan -> SUPERSEDED, superseded_by_plan_id := null
    for plan in store.repayment_plans.values():
        if plan["loan_id"] == lid and plan["status"] == "ACTIVE":
            plan["status"] = "SUPERSEDED"
            plan["superseded_by_plan_id"] = None
            bump_version(plan)
    bump_version(loan)
    return success_object(loan_view(loan), 200)


@app.route(f"{API_PREFIX}/loans/<lid>/rehabilitate", methods=["POST"])
def loan_rehabilitate(lid):
    _, role = get_auth()
    require_role(role, ["CollectionsAgent"])
    loan = get_loan_or_404(lid)
    if loan["status"] != "DEFAULT":
        raise_err(ERR_INVALID_STATE, f"Loan status is {loan['status']}, required DEFAULT")
    # Find the most recent DEFAULT_DECLARATION StatusChange
    decls = [sc for sc in store.status_changes.values()
             if sc["loan_id"] == lid and sc["reason_code"] == "DEFAULT_DECLARATION"]
    if not decls:
        raise_err(ERR_REHABILITATION_NOT_QUALIFIED, "No prior default declaration")
    decls.sort(key=lambda sc: parse_iso_to_dt(sc["effective_at"]), reverse=True)
    cutoff = parse_iso_to_dt(decls[0]["effective_at"])
    qual_count = 0
    for p in store.payments.values():
        if p["loan_id"] != lid:
            continue
        if p["status"] != "APPLIED":
            continue
        if parse_iso_to_dt(p["payment_date"]) > cutoff:
            qual_count += 1
    if qual_count < 9:
        raise_err(ERR_REHABILITATION_NOT_QUALIFIED,
                  f"Need >=9 post-default APPLIED payments; have {qual_count}")
    accrue_loan_to_now(loan)
    prev = loan["status"]
    loan["status"] = "REPAYMENT"
    write_status_change(lid, prev, "REPAYMENT", "REHABILITATION_COMPLETE", role)
    bump_version(loan)
    return success_object(loan_view(loan), 200)


@app.route(f"{API_PREFIX}/loans/<lid>/status-changes", methods=["GET"])
def list_status_changes(lid):
    uid, role = get_auth()
    require_role(role, ["LoanServicer", "Borrower", "CollectionsAgent"])
    loan = get_loan_or_404(lid)
    ownership_check_borrower(role, uid, loan["borrower_id"])
    limit, offset = pagination_params()
    rows = [sc for sc in store.status_changes.values() if sc["loan_id"] == lid]
    rows.sort(key=lambda r: (parse_iso_to_dt(r["effective_at"]),
                             parse_iso_to_dt(r["created_at"])))
    rows, total = paginate(rows, limit, offset)
    return success_array(rows, limit, offset, total)


# ============================================================
# Repayment Plans
# ============================================================

PLAN_TYPES = {"STANDARD", "IBR", "PAYE", "SAVE"}


@app.route(f"{API_PREFIX}/repayment-plans", methods=["POST"])
def create_repayment_plan():
    _, role = get_auth()
    require_role(role, ["LoanServicer"])
    body = get_json_body()
    require_fields(body, ["loan_id", "plan_type", "effective_date", "expected_loan_version"])
    loan_id = body["loan_id"]
    plan_type = body["plan_type"]
    effective_date = body["effective_date"]
    expected_loan_version = body["expected_loan_version"]

    loan = get_loan_or_404(loan_id)

    # OCC check (priority §1.4 #12, after existence)
    if not isinstance(expected_loan_version, int):
        raise_err(ERR_INVALID_REQUEST, "expected_loan_version must be integer")
    if expected_loan_version != int(loan["version"]):
        raise_err(ERR_STALE_LOAN_VERSION,
                  f"Expected loan version {expected_loan_version}, current {loan['version']}")
    if plan_type not in PLAN_TYPES:
        raise_err(ERR_INVALID_REQUEST, "plan_type must be STANDARD|IBR|PAYE|SAVE")
    try:
        parse_iso_to_dt(effective_date)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "effective_date must be ISO 8601")

    plan = {
        "loan_id": loan_id,
        "plan_type": plan_type,
        "status": "PENDING",
        "effective_date": effective_date,
        "superseded_by_plan_id": None,
        "monthly_payment_cents": 0,
    }
    common_create(plan)
    store.repayment_plans[plan["id"]] = plan
    recompute_monthly_payment_for_plan(plan)
    # Side effect: increments Loan.version by 1
    bump_version(loan)
    return success_object(plan, 201)


@app.route(f"{API_PREFIX}/repayment-plans/<pid>/activate", methods=["POST"])
def activate_repayment_plan(pid):
    _, role = get_auth()
    require_role(role, ["LoanServicer"])
    plan = store.repayment_plans.get(pid)
    if not plan:
        raise_err(ERR_RESOURCE_NOT_FOUND, f"RepaymentPlan {pid} not found")
    loan = get_loan_or_404(plan["loan_id"])
    if plan["status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, f"Plan status is {plan['status']}, required PENDING")
    if loan["status"] != "REPAYMENT":
        raise_err(ERR_INVALID_STATE, f"Loan status is {loan['status']}, required REPAYMENT")
    # No other plan for this loan may be ACTIVE
    current_active = active_plan_for_loan(loan["id"])
    if current_active is not None and current_active["id"] != pid:
        # Per PRD §3.5 + scaffold: activating supersedes prior ACTIVE plan.
        # The PRD says: "When activating a new plan implicitly displaces the prior ACTIVE plan
        # for the same loan ... the previously ACTIVE plan is transitioned to SUPERSEDED
        # and its superseded_by_plan_id is set to the new plan's id."
        # But scaffold §1.4 priority 7 says ERR_PLAN_ALREADY_ACTIVE on activate.
        # SCAFFOLD wins on validation but PRD describes supersession semantics — PRD §3.5
        # actually attributes the supersede to the create-then-activate sequence flow.
        # Reconciling: activation's third precondition is "no other plan ACTIVE";
        # so we raise ERR_PLAN_ALREADY_ACTIVE.
        raise_err(ERR_PLAN_ALREADY_ACTIVE,
                  f"Another plan {current_active['id']} is already ACTIVE for this loan")
    plan["status"] = "ACTIVE"
    recompute_monthly_payment_for_plan(plan)
    bump_version(plan)
    return success_object(plan, 200)


@app.route(f"{API_PREFIX}/repayment-plans/<pid>", methods=["GET"])
def get_repayment_plan(pid):
    uid, role = get_auth()
    require_role(role, ["LoanServicer", "Borrower"])
    plan = store.repayment_plans.get(pid)
    if not plan:
        raise_err(ERR_RESOURCE_NOT_FOUND, f"RepaymentPlan {pid} not found")
    loan = store.loans.get(plan["loan_id"])
    if loan:
        ownership_check_borrower(role, uid, loan["borrower_id"])
    return success_object(plan, 200)


@app.route(f"{API_PREFIX}/repayment-plans", methods=["GET"])
def list_repayment_plans():
    uid, role = get_auth()
    require_role(role, ["LoanServicer", "Borrower"])
    limit, offset = pagination_params()
    loan_id = request.args.get("loan_id")
    superseded_by_plan_id = request.args.get("superseded_by_plan_id")

    items = list(store.repayment_plans.values())
    if loan_id:
        items = [p for p in items if p["loan_id"] == loan_id]
    if superseded_by_plan_id:
        items = [p for p in items if p.get("superseded_by_plan_id") == superseded_by_plan_id]
    if role == "Borrower":
        # Restrict to plans where parent loan's borrower_id == uid
        items = [p for p in items
                 if (store.loans.get(p["loan_id"]) or {}).get("borrower_id") == uid]
    items.sort(key=lambda p: p["created_at"])
    items, total = paginate(items, limit, offset)
    return success_array(items, limit, offset, total)


# ============================================================
# Income Certifications
# ============================================================

@app.route(f"{API_PREFIX}/income-certifications", methods=["POST"])
def create_income_certification():
    uid, role = get_auth()
    require_role(role, ["Borrower"])
    body = get_json_body()
    require_fields(body, ["borrower_id", "agi_cents", "family_size", "state_code", "effective_date"])
    borrower_id = body["borrower_id"]
    get_borrower_or_404(borrower_id)
    ownership_check_borrower(role, uid, borrower_id)
    agi = body["agi_cents"]
    fam = body["family_size"]
    state_code = body["state_code"]
    effective_date = body["effective_date"]
    if not isinstance(agi, int) or agi < 0:
        raise_err(ERR_INVALID_REQUEST, "agi_cents must be integer >= 0")
    if not isinstance(fam, int) or fam < 1:
        raise_err(ERR_INVALID_REQUEST, "family_size must be integer >= 1")
    if not isinstance(state_code, str) or len(state_code) != 2:
        raise_err(ERR_INVALID_REQUEST, "state_code must be a 2-letter code")
    try:
        parse_iso_to_dt(effective_date)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "effective_date must be ISO 8601")

    obj = {
        "borrower_id": borrower_id,
        "agi_cents": agi,
        "family_size": fam,
        "state_code": state_code,
        "effective_date": effective_date,
        "status": "SUBMITTED",
    }
    common_create(obj)
    store.income_certifications[obj["id"]] = obj
    return success_object(obj, 201)


@app.route(f"{API_PREFIX}/income-certifications/<cid>/certify", methods=["POST"])
def certify_income_certification(cid):
    _, role = get_auth()
    require_role(role, ["LoanServicer"])
    cert = store.income_certifications.get(cid)
    if not cert:
        raise_err(ERR_RESOURCE_NOT_FOUND, f"IncomeCertification {cid} not found")
    if cert["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, f"Status is {cert['status']}, required SUBMITTED")
    cert["status"] = "CERTIFIED"
    bump_version(cert)
    # Cascade: recompute monthly_payment_cents for borrower's loans' RepaymentPlans
    # whose status IN {PENDING, ACTIVE} and effective_date <= this.effective_date.
    cert_eff = parse_iso_to_dt(cert["effective_date"])
    for plan in store.repayment_plans.values():
        loan = store.loans.get(plan["loan_id"])
        if not loan or loan["borrower_id"] != cert["borrower_id"]:
            continue
        if plan["status"] not in ("PENDING", "ACTIVE"):
            continue
        if parse_iso_to_dt(plan["effective_date"]) <= cert_eff:
            recompute_monthly_payment_for_plan(plan)
            bump_version(plan)
    # Also recompute PSLF count for borrower's loans
    recompute_pslf_for_borrower(cert["borrower_id"])
    return success_object(cert, 200)


@app.route(f"{API_PREFIX}/income-certifications/<cid>", methods=["GET"])
def get_income_certification(cid):
    uid, role = get_auth()
    require_role(role, ["LoanServicer", "Borrower"])
    cert = store.income_certifications.get(cid)
    if not cert:
        raise_err(ERR_RESOURCE_NOT_FOUND, f"IncomeCertification {cid} not found")
    ownership_check_borrower(role, uid, cert["borrower_id"])
    return success_object(cert, 200)


@app.route(f"{API_PREFIX}/income-certifications", methods=["GET"])
def list_income_certifications():
    uid, role = get_auth()
    require_role(role, ["LoanServicer", "Borrower"])
    limit, offset = pagination_params()
    borrower_id = request.args.get("borrower_id")
    items = list(store.income_certifications.values())
    if borrower_id:
        items = [c for c in items if c["borrower_id"] == borrower_id]
    if role == "Borrower":
        items = [c for c in items if c["borrower_id"] == uid]
    items.sort(key=lambda c: c["created_at"])
    items, total = paginate(items, limit, offset)
    return success_array(items, limit, offset, total)


# ============================================================
# Qualifying Employments
# ============================================================

EMPLOYER_TYPES = {"GOVERNMENT", "NONPROFIT_501C3", "OTHER_NONPROFIT", "PRIVATE_NONQUALIFYING"}


@app.route(f"{API_PREFIX}/qualifying-employments", methods=["POST"])
def create_qualifying_employment():
    uid, role = get_auth()
    require_role(role, ["Borrower"])
    body = get_json_body()
    require_fields(body, ["borrower_id", "employer_name", "employer_type", "period_start", "period_end"])
    borrower_id = body["borrower_id"]
    get_borrower_or_404(borrower_id)
    ownership_check_borrower(role, uid, borrower_id)
    employer_name = body["employer_name"]
    employer_type = body["employer_type"]
    period_start = body["period_start"]
    period_end = body["period_end"]
    if not isinstance(employer_name, str) or not employer_name:
        raise_err(ERR_INVALID_REQUEST, "employer_name is required")
    if employer_type not in EMPLOYER_TYPES:
        raise_err(ERR_INVALID_REQUEST, "employer_type invalid")
    try:
        ps = parse_iso_to_dt(period_start)
        pe = parse_iso_to_dt(period_end)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "period_start/period_end must be ISO 8601")
    # Priority §1.4 #14: period_end must be > period_start
    if pe <= ps:
        raise_err(ERR_INVALID_PERIOD, "period_end must be > period_start")

    obj = {
        "borrower_id": borrower_id,
        "employer_name": employer_name,
        "employer_type": employer_type,
        "period_start": period_start,
        "period_end": period_end,
        "status": "SUBMITTED",
    }
    common_create(obj)
    store.qualifying_employments[obj["id"]] = obj
    return success_object(obj, 201)


@app.route(f"{API_PREFIX}/qualifying-employments/<qid>/certify", methods=["POST"])
def certify_qualifying_employment(qid):
    _, role = get_auth()
    require_role(role, ["LoanServicer"])
    qe = store.qualifying_employments.get(qid)
    if not qe:
        raise_err(ERR_RESOURCE_NOT_FOUND, f"QualifyingEmployment {qid} not found")
    if qe["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, f"Status is {qe['status']}, required SUBMITTED")
    qe["status"] = "CERTIFIED"
    bump_version(qe)
    # Cascade: recompute PSLF count for all loans of this borrower
    recompute_pslf_for_borrower(qe["borrower_id"])
    return success_object(qe, 200)


@app.route(f"{API_PREFIX}/qualifying-employments/<qid>", methods=["GET"])
def get_qualifying_employment(qid):
    uid, role = get_auth()
    require_role(role, ["LoanServicer", "Borrower"])
    qe = store.qualifying_employments.get(qid)
    if not qe:
        raise_err(ERR_RESOURCE_NOT_FOUND, f"QualifyingEmployment {qid} not found")
    ownership_check_borrower(role, uid, qe["borrower_id"])
    return success_object(qe, 200)


@app.route(f"{API_PREFIX}/qualifying-employments", methods=["GET"])
def list_qualifying_employments():
    uid, role = get_auth()
    require_role(role, ["LoanServicer", "Borrower"])
    limit, offset = pagination_params()
    borrower_id = request.args.get("borrower_id")
    items = list(store.qualifying_employments.values())
    if borrower_id:
        items = [q for q in items if q["borrower_id"] == borrower_id]
    if role == "Borrower":
        items = [q for q in items if q["borrower_id"] == uid]
    items.sort(key=lambda q: q["created_at"])
    items, total = paginate(items, limit, offset)
    return success_array(items, limit, offset, total)


# ============================================================
# Payments
# ============================================================

@app.route(f"{API_PREFIX}/payments", methods=["POST"])
def create_payment():
    uid, role = get_auth()
    require_role(role, ["Borrower", "LoanServicer"])
    body = get_json_body()
    require_fields(body, ["loan_id", "amount_cents", "payment_date"])
    loan_id = body["loan_id"]
    amount = body["amount_cents"]
    payment_date = body["payment_date"]

    loan = get_loan_or_404(loan_id)
    ownership_check_borrower(role, uid, loan["borrower_id"])
    # Temporal: payment_date <= current server clock (priority §1.4 #15)
    try:
        pdt = parse_iso_to_dt(payment_date)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "payment_date must be ISO 8601")
    if pdt > get_current_utc_dt():
        raise_err(ERR_FUTURE_PAYMENT, "payment_date must not be in the future")
    # Fiscal range (priority §1.4 #16)
    accrue_loan_to_now(loan)
    if not isinstance(amount, int) or amount < 1:
        raise_err(ERR_PAYMENT_AMOUNT_OUT_OF_RANGE, "amount_cents must be >= 1")
    ceiling = int(loan["principal_balance_cents"]) + int(loan["accrued_interest_cents"])
    if amount > ceiling:
        raise_err(ERR_PAYMENT_AMOUNT_OUT_OF_RANGE,
                  f"amount_cents {amount} exceeds outstanding {ceiling}")

    # repayment_plan_id resolved server-side to ACTIVE plan at posting time
    active_plan = active_plan_for_loan(loan_id)
    plan_id = active_plan["id"] if active_plan else None

    obj = {
        "loan_id": loan_id,
        "repayment_plan_id": plan_id,
        "amount_cents": amount,
        "payment_date": payment_date,
        "status": "PENDING",
        "principal_applied_cents": 0,
        "interest_applied_cents": 0,
        "is_pslf_qualifying": False,
        "reversed_by_payment_id": None,
    }
    common_create(obj)
    store.payments[obj["id"]] = obj
    return success_object(obj, 201)


@app.route(f"{API_PREFIX}/payments/<pid>/apply", methods=["POST"])
def apply_payment(pid):
    _, role = get_auth()
    require_role(role, ["LoanServicer"])
    p = store.payments.get(pid)
    if not p:
        raise_err(ERR_RESOURCE_NOT_FOUND, f"Payment {pid} not found")
    if p["status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, f"Payment status is {p['status']}, required PENDING")
    loan = get_loan_or_404(p["loan_id"])
    if loan["status"] not in ("REPAYMENT", "DEFAULT"):
        raise_err(ERR_INVALID_STATE,
                  f"Loan status is {loan['status']}, required REPAYMENT or DEFAULT")
    # Accrue before allocation so interest bucket is current
    accrue_loan_to_now(loan)
    # Re-validate range at apply-time
    ceiling = int(loan["principal_balance_cents"]) + int(loan["accrued_interest_cents"])
    if p["amount_cents"] > ceiling:
        raise_err(ERR_PAYMENT_AMOUNT_OUT_OF_RANGE,
                  f"amount_cents {p['amount_cents']} exceeds outstanding {ceiling}")
    # Waterfall: first to accrued_interest_cents, then principal_balance_cents
    remaining = int(p["amount_cents"])
    interest_applied = min(remaining, int(loan["accrued_interest_cents"]))
    loan["accrued_interest_cents"] = int(loan["accrued_interest_cents"]) - interest_applied
    remaining -= interest_applied
    principal_applied = min(remaining, int(loan["principal_balance_cents"]))
    loan["principal_balance_cents"] = int(loan["principal_balance_cents"]) - principal_applied
    remaining -= principal_applied
    # remaining should be 0 here due to ceiling check
    p["interest_applied_cents"] = interest_applied
    p["principal_applied_cents"] = principal_applied
    p["status"] = "APPLIED"
    # Compute is_pslf_qualifying using full predicate set
    p["is_pslf_qualifying"] = payment_is_pslf_qualifying(p)
    bump_version(p)
    bump_version(loan)
    # Auto-PAID_OFF if balances zeroed and loan was in REPAYMENT
    if (loan["principal_balance_cents"] == 0 and loan["accrued_interest_cents"] == 0
            and loan["status"] == "REPAYMENT"):
        prev = loan["status"]
        loan["status"] = "PAID_OFF"
        write_status_change(loan["id"], prev, "PAID_OFF", "PAY_OFF", "system")
        bump_version(loan)
        # Cascade: ACTIVE plan -> COMPLETED
        for plan in store.repayment_plans.values():
            if plan["loan_id"] == loan["id"] and plan["status"] == "ACTIVE":
                plan["status"] = "COMPLETED"
                bump_version(plan)
    # Recompute PSLF count for loan
    loan["pslf_qualifying_payment_count"] = pslf_qualifying_payment_count(loan["id"])
    return success_object(p, 200)


@app.route(f"{API_PREFIX}/payments/<pid>/reverse", methods=["POST"])
def reverse_payment(pid):
    _, role = get_auth()
    require_role(role, ["LoanServicer"])
    p = store.payments.get(pid)
    if not p:
        raise_err(ERR_RESOURCE_NOT_FOUND, f"Payment {pid} not found")
    if p["status"] != "APPLIED":
        raise_err(ERR_INVALID_STATE, f"Payment status is {p['status']}, required APPLIED")
    loan = get_loan_or_404(p["loan_id"])
    # Compensating: add the splits back
    loan["principal_balance_cents"] = int(loan["principal_balance_cents"]) + int(p["principal_applied_cents"])
    loan["accrued_interest_cents"] = int(loan["accrued_interest_cents"]) + int(p["interest_applied_cents"])
    p["status"] = "REVERSED"
    bump_version(p)
    bump_version(loan)
    # Recompute PSLF for borrower
    recompute_pslf_for_borrower(loan["borrower_id"])
    return success_object(p, 200)


@app.route(f"{API_PREFIX}/payments/<pid>", methods=["GET"])
def get_payment(pid):
    uid, role = get_auth()
    require_role(role, ["LoanServicer", "Borrower"])
    p = store.payments.get(pid)
    if not p:
        raise_err(ERR_RESOURCE_NOT_FOUND, f"Payment {pid} not found")
    loan = store.loans.get(p["loan_id"])
    if loan:
        ownership_check_borrower(role, uid, loan["borrower_id"])
    return success_object(p, 200)


@app.route(f"{API_PREFIX}/payments", methods=["GET"])
def list_payments():
    uid, role = get_auth()
    require_role(role, ["LoanServicer", "Borrower"])
    limit, offset = pagination_params()
    loan_id = request.args.get("loan_id")
    plan_id = request.args.get("repayment_plan_id")
    reversed_by_id = request.args.get("reversed_by_payment_id")
    items = list(store.payments.values())
    if loan_id:
        items = [p for p in items if p["loan_id"] == loan_id]
    if plan_id:
        items = [p for p in items if p.get("repayment_plan_id") == plan_id]
    if reversed_by_id:
        items = [p for p in items if p.get("reversed_by_payment_id") == reversed_by_id]
    if role == "Borrower":
        items = [p for p in items
                 if (store.loans.get(p["loan_id"]) or {}).get("borrower_id") == uid]
    items.sort(key=lambda p: p["created_at"])
    items, total = paginate(items, limit, offset)
    return success_array(items, limit, offset, total)


# ============================================================
# Discharge Applications
# ============================================================

DISCHARGE_TYPES = {"VETERAN_TOTAL_DISABILITY", "PSLF"}


@app.route(f"{API_PREFIX}/discharge-applications", methods=["POST"])
def create_discharge_application():
    uid, role = get_auth()
    require_role(role, ["Borrower"])
    body = get_json_body()
    require_fields(body, ["loan_id", "discharge_type"])
    loan_id = body["loan_id"]
    dt_type = body["discharge_type"]
    review_notes = body.get("review_notes", "")
    loan = get_loan_or_404(loan_id)
    ownership_check_borrower(role, uid, loan["borrower_id"])
    if dt_type not in DISCHARGE_TYPES:
        raise_err(ERR_INVALID_REQUEST, "discharge_type invalid")
    if not isinstance(review_notes, str):
        raise_err(ERR_INVALID_REQUEST, "review_notes must be string")
    obj = {
        "loan_id": loan_id,
        "discharge_type": dt_type,
        "status": "SUBMITTED",
        "review_notes": review_notes,
    }
    common_create(obj)
    store.discharge_applications[obj["id"]] = obj
    return success_object(obj, 201)


@app.route(f"{API_PREFIX}/discharge-applications/<aid>/begin-review", methods=["POST"])
def begin_review_discharge(aid):
    _, role = get_auth()
    require_role(role, ["LoanServicer"])
    app_obj = store.discharge_applications.get(aid)
    if not app_obj:
        raise_err(ERR_RESOURCE_NOT_FOUND, f"DischargeApplication {aid} not found")
    if app_obj["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, f"Status is {app_obj['status']}, required SUBMITTED")
    app_obj["status"] = "UNDER_REVIEW"
    bump_version(app_obj)
    return success_object(app_obj, 200)


@app.route(f"{API_PREFIX}/discharge-applications/<aid>/approve", methods=["POST"])
def approve_discharge(aid):
    _, role = get_auth()
    require_role(role, ["LoanServicer"])
    app_obj = store.discharge_applications.get(aid)
    if not app_obj:
        raise_err(ERR_RESOURCE_NOT_FOUND, f"DischargeApplication {aid} not found")
    body = get_json_body()
    # Validation priorities §1.4:
    # 6 state, 8 NOT_VETERAN, 9 PSLF_INSUFFICIENT, 13 OCC
    if app_obj["status"] != "UNDER_REVIEW":
        raise_err(ERR_INVALID_STATE, f"Status is {app_obj['status']}, required UNDER_REVIEW")
    loan = get_loan_or_404(app_obj["loan_id"])
    if app_obj["discharge_type"] == "VETERAN_TOTAL_DISABILITY":
        borrower = store.borrowers.get(loan["borrower_id"])
        if not borrower or not borrower.get("is_veteran"):
            raise_err(ERR_NOT_VETERAN, "Borrower is not flagged as veteran")
    elif app_obj["discharge_type"] == "PSLF":
        count = pslf_qualifying_payment_count(loan["id"])
        loan["pslf_qualifying_payment_count"] = count
        if count < 120:
            raise_err(ERR_PSLF_INSUFFICIENT_PAYMENTS,
                      f"PSLF count is {count}, requires >= 120")
    # OCC check
    if "expected_application_version" not in body:
        raise_err(ERR_INVALID_REQUEST, "expected_application_version required")
    expected = body["expected_application_version"]
    if not isinstance(expected, int):
        raise_err(ERR_INVALID_REQUEST, "expected_application_version must be integer")
    if expected != int(app_obj["version"]):
        raise_err(ERR_STALE_APPLICATION_VERSION,
                  f"Expected version {expected}, current {app_obj['version']}")

    # Persist review_notes if supplied
    if "review_notes" in body:
        if not isinstance(body["review_notes"], str):
            raise_err(ERR_INVALID_REQUEST, "review_notes must be string")
        app_obj["review_notes"] = body["review_notes"]

    # Transition application
    app_obj["status"] = "APPROVED"
    bump_version(app_obj)

    # Cascade: Loan REPAYMENT->DISCHARGED
    prev = loan["status"]
    loan["status"] = "DISCHARGED"
    loan["principal_balance_cents"] = 0
    loan["accrued_interest_cents"] = 0
    write_status_change(loan["id"], prev, "DISCHARGED", "DISCHARGE_APPROVED", "system")
    bump_version(loan)

    # Secondary cascade: all PENDING Payments for the loan -> REVERSED
    for pay in store.payments.values():
        if pay["loan_id"] == loan["id"] and pay["status"] == "PENDING":
            pay["status"] = "REVERSED"
            pay["reversed_by_payment_id"] = None
            bump_version(pay)

    return success_object(app_obj, 200)


@app.route(f"{API_PREFIX}/discharge-applications/<aid>/deny", methods=["POST"])
def deny_discharge(aid):
    _, role = get_auth()
    require_role(role, ["LoanServicer"])
    app_obj = store.discharge_applications.get(aid)
    if not app_obj:
        raise_err(ERR_RESOURCE_NOT_FOUND, f"DischargeApplication {aid} not found")
    body = get_json_body()
    if app_obj["status"] != "UNDER_REVIEW":
        raise_err(ERR_INVALID_STATE, f"Status is {app_obj['status']}, required UNDER_REVIEW")
    if "review_notes" in body:
        if not isinstance(body["review_notes"], str):
            raise_err(ERR_INVALID_REQUEST, "review_notes must be string")
        app_obj["review_notes"] = body["review_notes"]
    app_obj["status"] = "DENIED"
    bump_version(app_obj)
    return success_object(app_obj, 200)


@app.route(f"{API_PREFIX}/discharge-applications/<aid>", methods=["GET"])
def get_discharge_application(aid):
    uid, role = get_auth()
    require_role(role, ["LoanServicer", "Borrower"])
    app_obj = store.discharge_applications.get(aid)
    if not app_obj:
        raise_err(ERR_RESOURCE_NOT_FOUND, f"DischargeApplication {aid} not found")
    loan = store.loans.get(app_obj["loan_id"])
    if loan:
        ownership_check_borrower(role, uid, loan["borrower_id"])
    return success_object(app_obj, 200)


@app.route(f"{API_PREFIX}/discharge-applications", methods=["GET"])
def list_discharge_applications():
    uid, role = get_auth()
    require_role(role, ["LoanServicer", "Borrower"])
    limit, offset = pagination_params()
    loan_id = request.args.get("loan_id")
    items = list(store.discharge_applications.values())
    if loan_id:
        items = [a for a in items if a["loan_id"] == loan_id]
    if role == "Borrower":
        items = [a for a in items
                 if (store.loans.get(a["loan_id"]) or {}).get("borrower_id") == uid]
    items.sort(key=lambda a: a["created_at"])
    items, total = paginate(items, limit, offset)
    return success_array(items, limit, offset, total)


# ============================================================
# Test-driving clock
# ============================================================

@app.route(f"{API_PREFIX}/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _, role = get_auth()
    require_role(role, ["LoanServicer"])
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    to_iso = body["to_iso8601"]
    try:
        parse_iso_to_dt(to_iso)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be ISO 8601")
    store.current_utc = to_iso
    # Trigger flat interest_accrual recomputation across all loans
    accrue_all_loans()
    # Recompute delinquency_days across population (best-effort; left at 0 unless
    # explicit driver logic populates it).
    return success_object({"current_utc": store.current_utc}, 200)


# ============================================================
# Health
# ============================================================

@app.route("/", methods=["GET"])
def root():
    return success_object({"service": "federal-student-loan-servicing"}, 200)


@app.route("/healthz", methods=["GET"])
def healthz():
    return success_object({"ok": True}, 200)


# ============================================================
# Entry
# ============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # No reloader; foreground; bind 0.0.0.0
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
