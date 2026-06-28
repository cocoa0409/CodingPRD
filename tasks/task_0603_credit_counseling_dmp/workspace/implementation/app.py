"""Credit Counseling & Debt Management Plan API -- Python + Flask, in-memory.

Single-file application. Store starts EMPTY on every boot (no seeding).
"""
import math
import os
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps

from flask import Flask, g, request

import errors as E
from db import db, new_id, now_iso, next_seq
from errors import ApiError
from response import ok, created, listed, error as err_response

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants (scaffold §1.3)
# ---------------------------------------------------------------------------
MIN_ENROLL_DTI = Decimal("15.0")
SETUP_FEE_CAP_CENTS = 5000
MONTHLY_FEE_CAP_CENTS = 7500
MISSED_DEPOSIT_LIMIT = 3
LATE_FEE_THRESHOLD_APR = Decimal("0.10")

VALID_ROLES = {"AgencyAdmin", "Counselor", "CreditorRep"}
SESSION_TYPES = {"BUDGET_INTAKE", "BANKRUPTCY_PREFILING",
                 "BANKRUPTCY_PREDISCHARGE", "HUD_HOUSING"}
CERTIFIABLE_TYPES = {"BANKRUPTCY_PREFILING", "BANKRUPTCY_PREDISCHARGE", "HUD_HOUSING"}


# ---------------------------------------------------------------------------
# Rounding helpers
# ---------------------------------------------------------------------------
def round_half_up_2(value):
    """Round a value to 2 decimal places, ROUND_HALF_UP. Returns float."""
    d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)


def floor_interest(balance_cents, apr):
    """floor(balance_cents * apr / 12) using exact Decimal arithmetic."""
    if apr is None:
        return None
    val = (Decimal(balance_cents) * Decimal(str(apr))) / Decimal(12)
    return int(val.to_integral_value(rounding="ROUND_FLOOR"))


# ---------------------------------------------------------------------------
# Auth / RBAC middleware
# ---------------------------------------------------------------------------
def require_auth(allowed_roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in VALID_ROLES:
                raise ApiError(E.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400,
                               "Missing or invalid user context header")
            if role not in allowed_roles:
                raise ApiError(E.ERR_FORBIDDEN_FOR_ROLE, 403,
                               "Role not permitted for this operation")
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Common system fields
# ---------------------------------------------------------------------------
def make_common(versioned=True):
    ts = now_iso()
    base = {"id": new_id(), "created_at": ts, "_seq": next_seq()}
    if versioned:
        base["updated_at"] = ts
        base["version"] = 1
    return base


def touch(rec):
    """Mutation: refresh updated_at and bump version (if versioned)."""
    if "version" in rec:
        rec["updated_at"] = now_iso()
        rec["version"] += 1


def public(rec):
    """Strip internal-only fields for serialization."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Input parsing helpers
# ---------------------------------------------------------------------------
def get_body():
    if request.data and request.data.strip():
        try:
            data = request.get_json(force=True, silent=True)
        except Exception:
            data = None
        if data is None:
            raise ApiError(E.ERR_INVALID_REQUEST, 400, "Malformed JSON body")
        if not isinstance(data, dict):
            raise ApiError(E.ERR_INVALID_REQUEST, 400, "Body must be an object")
        return data
    return {}


def require_field(body, name):
    if name not in body or body[name] is None:
        raise ApiError(E.ERR_INVALID_REQUEST, 400, f"Missing required field: {name}")
    return body[name]


def as_int(value, name, positive=False, non_negative=False):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, f"{name} must be an integer")
    if positive and value <= 0:
        raise ApiError(E.ERR_INVALID_REQUEST, 400, f"{name} must be > 0")
    if non_negative and value < 0:
        raise ApiError(E.ERR_INVALID_REQUEST, 400, f"{name} must be >= 0")
    return value


def as_number(value, name, lo=None, hi=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, f"{name} must be a number")
    if lo is not None and value < lo:
        raise ApiError(E.ERR_VALIDATION, 422, f"{name} out of range")
    if hi is not None and value > hi:
        raise ApiError(E.ERR_VALIDATION, 422, f"{name} out of range")
    return value


def as_bool(value, name):
    if not isinstance(value, bool):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, f"{name} must be a boolean")
    return value


# ---------------------------------------------------------------------------
# Lookups (path existence -> ERR_NOT_FOUND 404)
# ---------------------------------------------------------------------------
def get_or_404(coll, _id):
    rec = coll.get(_id)
    if rec is None:
        raise ApiError(E.ERR_NOT_FOUND, 404, "Resource not found")
    return rec


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def pagination_params():
    limit = request.args.get("limit", "10")
    offset = request.args.get("offset", "0")
    try:
        limit = int(limit)
    except (ValueError, TypeError):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "limit must be an integer")
    try:
        offset = int(offset)
    except (ValueError, TypeError):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "offset must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(records, serialize=public):
    limit, offset = pagination_params()
    records = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(records)
    page = records[offset:offset + limit]
    return listed([serialize(r) for r in page], limit, offset, total)


# ===========================================================================
# Computation helpers for Client derived fields
# ===========================================================================
def client_debt_accounts(client_id):
    return [d for d in db.debt_accounts.values() if d["client_id"] == client_id]


def compute_front_end_dti(client):
    gross = client["gross_monthly_income_cents"]
    return round_half_up_2(Decimal(client["housing_payment_cents"]) /
                           Decimal(gross) * Decimal(100))


def compute_back_end_dti(client):
    gross = client["gross_monthly_income_cents"]
    back_debts = sum(d["min_payment_cents"] for d in client_debt_accounts(client["id"])
                     if d["status"] in ("PROPOSED", "COUNTERED", "ACCEPTED", "ENROLLED"))
    total = Decimal(client["housing_payment_cents"] + back_debts)
    return round_half_up_2(total / Decimal(gross) * Decimal(100))


def compute_total_enrolled_balance(client):
    return sum(d["current_balance_cents"] or 0 for d in client_debt_accounts(client["id"])
               if d["status"] in ("ENROLLED", "SETTLED"))


def compute_monthly_deposit(client):
    agency = db.agencies.get(client["agency_id"])
    monthly_fee = agency["monthly_fee_cents"] if agency else 0
    enrolled_sum = sum(d["proposed_monthly_payment_cents"]
                       for d in client_debt_accounts(client["id"])
                       if d["status"] == "ENROLLED")
    return monthly_fee + enrolled_sum


def latest_proposal_id(debt_account_id):
    proposals = [p for p in db.proposals.values()
                 if p["debt_account_id"] == debt_account_id]
    if not proposals:
        return None
    proposals.sort(key=lambda p: (p["round_index"], p["_seq"]))
    return proposals[-1]["id"]


def serialize_client(client):
    out = public(client)
    out["front_end_dti"] = compute_front_end_dti(client)
    out["back_end_dti"] = compute_back_end_dti(client)
    out["total_enrolled_balance_cents"] = compute_total_enrolled_balance(client)
    # monthly_deposit_cents is a stored/locked value once ACTIVE; otherwise computed.
    if client["status"] in ("ACTIVE", "DEFAULTED", "GRADUATED", "WITHDRAWN"):
        out["monthly_deposit_cents"] = client.get("monthly_deposit_cents")
    else:
        out["monthly_deposit_cents"] = compute_monthly_deposit(client)
    return out


def serialize_debt_account(d):
    out = public(d)
    out["proposal_id"] = latest_proposal_id(d["id"])
    return out


# ===========================================================================
# AGENCY
# ===========================================================================
@app.post("/agencies/agencies")
@require_auth({"AgencyAdmin"})
def create_agency():
    body = get_body()
    name = require_field(body, "name")
    if not isinstance(name, str):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "name must be a string")
    setup_fee = body.get("setup_fee_cents", 5000)
    monthly_fee = body.get("monthly_fee_cents", 3500)
    setup_fee = as_int(setup_fee, "setup_fee_cents", non_negative=True)
    monthly_fee = as_int(monthly_fee, "monthly_fee_cents", non_negative=True)
    if setup_fee > SETUP_FEE_CAP_CENTS or monthly_fee > MONTHLY_FEE_CAP_CENTS:
        raise ApiError(E.ERR_FEE_CAP_EXCEEDED, 422, "Fee exceeds regulatory cap")
    rec = make_common()
    rec.update({
        "name": name,
        "setup_fee_cents": setup_fee,
        "monthly_fee_cents": monthly_fee,
        "current_cycle_index": 0,
    })
    db.agencies[rec["id"]] = rec
    return created(public(rec))


@app.get("/agencies/agencies/<agency_id>")
@require_auth({"AgencyAdmin", "Counselor", "CreditorRep"})
def get_agency(agency_id):
    rec = get_or_404(db.agencies, agency_id)
    return ok(public(rec))


# ===========================================================================
# COUNSELOR
# ===========================================================================
@app.post("/agencies/counselors")
@require_auth({"AgencyAdmin"})
def create_counselor():
    body = get_body()
    agency_id = require_field(body, "agency_id")
    full_name = require_field(body, "full_name")
    if not isinstance(full_name, str):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "full_name must be a string")
    hud = body.get("hud_certified", False)
    hud = as_bool(hud, "hud_certified")
    if agency_id not in db.agencies:
        raise ApiError(E.ERR_REFERENCE_NOT_FOUND, 422, "agency_id does not resolve")
    rec = make_common()
    rec.update({
        "agency_id": agency_id,
        "full_name": full_name,
        "hud_certified": hud,
        "status": "ACTIVE",
    })
    db.counselors[rec["id"]] = rec
    return created(public(rec))


@app.get("/agencies/counselors/<counselor_id>")
@require_auth({"AgencyAdmin", "Counselor"})
def get_counselor(counselor_id):
    rec = get_or_404(db.counselors, counselor_id)
    return ok(public(rec))


@app.get("/agencies/counselors")
@require_auth({"AgencyAdmin", "Counselor"})
def list_counselors():
    recs = list(db.counselors.values())
    agency_id = request.args.get("agency_id")
    if agency_id is not None:
        recs = [r for r in recs if r["agency_id"] == agency_id]
    hud = request.args.get("hud_certified")
    if hud is not None:
        want = hud.lower() == "true"
        recs = [r for r in recs if r["hud_certified"] == want]
    return paginate(recs)


# ===========================================================================
# CREDITOR
# ===========================================================================
@app.post("/agencies/creditors")
@require_auth({"AgencyAdmin"})
def create_creditor():
    body = get_body()
    agency_id = require_field(body, "agency_id")
    name = require_field(body, "name")
    if not isinstance(name, str):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "name must be a string")
    dca = require_field(body, "default_concession_apr")
    dca = as_number(dca, "default_concession_apr", lo=0.0, hi=1.0)
    waives = body.get("waives_late_fees", True)
    waives = as_bool(waives, "waives_late_fees")
    min_pct = body.get("min_proposed_payment_pct", 0.02)
    min_pct = as_number(min_pct, "min_proposed_payment_pct", lo=0.0, hi=1.0)
    if agency_id not in db.agencies:
        raise ApiError(E.ERR_REFERENCE_NOT_FOUND, 422, "agency_id does not resolve")
    rec = make_common()
    rec.update({
        "agency_id": agency_id,
        "name": name,
        "default_concession_apr": dca,
        "waives_late_fees": waives,
        "min_proposed_payment_pct": min_pct,
    })
    db.creditors[rec["id"]] = rec
    return created(public(rec))


@app.get("/agencies/creditors/<creditor_id>")
@require_auth({"AgencyAdmin", "Counselor", "CreditorRep"})
def get_creditor(creditor_id):
    rec = get_or_404(db.creditors, creditor_id)
    return ok(public(rec))


@app.get("/agencies/creditors")
@require_auth({"AgencyAdmin", "Counselor", "CreditorRep"})
def list_creditors():
    recs = list(db.creditors.values())
    agency_id = request.args.get("agency_id")
    if agency_id is not None:
        recs = [r for r in recs if r["agency_id"] == agency_id]
    return paginate(recs)


# ===========================================================================
# CLIENT
# ===========================================================================
@app.post("/agencies/clients")
@require_auth({"Counselor"})
def create_client():
    body = get_body()
    agency_id = require_field(body, "agency_id")
    counselor_id = require_field(body, "counselor_id")
    full_name = require_field(body, "full_name")
    if not isinstance(full_name, str):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "full_name must be a string")
    gross = require_field(body, "gross_monthly_income_cents")
    gross = as_int(gross, "gross_monthly_income_cents", positive=True)
    housing = body.get("housing_payment_cents", 0)
    housing = as_int(housing, "housing_payment_cents", non_negative=True)
    # Body FK resolution within agency
    if agency_id not in db.agencies:
        raise ApiError(E.ERR_REFERENCE_NOT_FOUND, 422, "agency_id does not resolve")
    counselor = db.counselors.get(counselor_id)
    if counselor is None or counselor["agency_id"] != agency_id:
        raise ApiError(E.ERR_REFERENCE_NOT_FOUND, 422, "counselor_id does not resolve")
    rec = make_common()
    rec.update({
        "agency_id": agency_id,
        "counselor_id": counselor_id,
        "full_name": full_name,
        "gross_monthly_income_cents": gross,
        "housing_payment_cents": housing,
        "monthly_deposit_cents": None,
        "projected_payoff_months": None,
        "missed_deposit_streak": 0,
        "status": "INTAKE",
    })
    db.clients[rec["id"]] = rec
    return created(serialize_client(rec))


@app.get("/agencies/clients/<client_id>")
@require_auth({"AgencyAdmin", "Counselor"})
def get_client(client_id):
    rec = get_or_404(db.clients, client_id)
    return ok(serialize_client(rec))


@app.get("/agencies/clients")
@require_auth({"AgencyAdmin", "Counselor"})
def list_clients():
    recs = list(db.clients.values())
    agency_id = request.args.get("agency_id")
    if agency_id is not None:
        recs = [r for r in recs if r["agency_id"] == agency_id]
    counselor_id = request.args.get("counselor_id")
    if counselor_id is not None:
        recs = [r for r in recs if r["counselor_id"] == counselor_id]
    status = request.args.get("status")
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    return paginate(recs, serialize=serialize_client)


@app.post("/agencies/clients/<client_id>/activate")
@require_auth({"Counselor"})
def activate_client(client_id):
    client = get_or_404(db.clients, client_id)
    body = get_body()
    expected = require_field(body, "expected_client_version")
    expected = as_int(expected, "expected_client_version", non_negative=True)
    # State tier: client must be INTAKE
    if client["status"] != "INTAKE":
        raise ApiError(E.ERR_INVALID_STATE, 409, "Client not in INTAKE")
    # OCC first per PRD §3.5 ordering
    if expected != client["version"]:
        raise ApiError(E.ERR_STALE_VERSION, 412, "expected_client_version mismatch")
    # Completed BUDGET_INTAKE session
    has_intake = any(
        s["client_id"] == client_id and s["session_type"] == "BUDGET_INTAKE"
        and s["status"] in ("COMPLETED", "CERTIFIED")
        for s in db.sessions.values()
    )
    if not has_intake:
        raise ApiError(E.ERR_INTAKE_NOT_COMPLETE, 409, "No completed BUDGET_INTAKE session")
    accepted = [d for d in client_debt_accounts(client_id) if d["status"] == "ACCEPTED"]
    if not accepted:
        raise ApiError(E.ERR_NO_ACCEPTED_ACCOUNTS, 409, "No ACCEPTED debt accounts")
    if Decimal(str(compute_back_end_dti(client))) < MIN_ENROLL_DTI:
        raise ApiError(E.ERR_DTI_BELOW_THRESHOLD, 409, "back_end_dti below threshold")
    agency = db.agencies[client["agency_id"]]
    if agency["setup_fee_cents"] > SETUP_FEE_CAP_CENTS or \
            agency["monthly_fee_cents"] > MONTHLY_FEE_CAP_CENTS:
        raise ApiError(E.ERR_FEE_CAP_EXCEEDED, 422, "Fee exceeds regulatory cap")
    # Side effects: enroll accepted accounts
    for d in accepted:
        d["status"] = "ENROLLED"
        d["current_balance_cents"] = d["original_balance_cents"]
        touch(d)
    client["monthly_deposit_cents"] = compute_monthly_deposit(client)
    client["status"] = "ACTIVE"
    touch(client)
    return ok(serialize_client(client))


@app.post("/agencies/clients/<client_id>/re_age")
@require_auth({"Counselor"})
def re_age_client(client_id):
    client = get_or_404(db.clients, client_id)
    if client["status"] != "DEFAULTED":
        raise ApiError(E.ERR_INVALID_STATE, 409, "Client not DEFAULTED")
    agency = db.agencies[client["agency_id"]]
    has_deposit = any(
        dep["client_id"] == client_id and dep["cycle_index"] == agency["current_cycle_index"]
        for dep in db.deposits.values()
    )
    if not has_deposit:
        raise ApiError(E.ERR_NO_CURRENT_DEPOSIT, 409, "No deposit at current cycle")
    client["missed_deposit_streak"] = 0
    client["status"] = "ACTIVE"
    touch(client)
    return ok(serialize_client(client))


@app.post("/agencies/clients/<client_id>/withdraw")
@require_auth({"Counselor"})
def withdraw_client(client_id):
    client = get_or_404(db.clients, client_id)
    if client["status"] not in ("INTAKE", "ACTIVE"):
        raise ApiError(E.ERR_INVALID_STATE, 409, "Client not INTAKE or ACTIVE")
    for d in client_debt_accounts(client_id):
        if d["status"] not in ("DROPPED", "SETTLED"):
            d["status"] = "DROPPED"
            touch(d)
    client["status"] = "WITHDRAWN"
    touch(client)
    return ok(serialize_client(client))


@app.post("/agencies/clients/<client_id>/deposits")
@require_auth({"Counselor", "AgencyAdmin"})
def record_deposit(client_id):
    client = get_or_404(db.clients, client_id)
    body = get_body()
    amount = require_field(body, "amount_cents")
    amount = as_int(amount, "amount_cents", positive=True)
    # State tier: client ACTIVE, checked before amount match
    if client["status"] != "ACTIVE":
        raise ApiError(E.ERR_CLIENT_NOT_ACTIVE, 409, "Client not ACTIVE")
    if amount != client["monthly_deposit_cents"]:
        raise ApiError(E.ERR_DEPOSIT_AMOUNT_MISMATCH, 422, "Deposit amount mismatch")
    agency = db.agencies[client["agency_id"]]
    cycle = agency["current_cycle_index"]
    dup = any(dep["client_id"] == client_id and dep["cycle_index"] == cycle
              for dep in db.deposits.values())
    if dup:
        raise ApiError(E.ERR_DUPLICATE_CYCLE_DEPOSIT, 409, "Duplicate deposit for cycle")
    rec = make_common(versioned=False)
    rec.update({
        "client_id": client_id,
        "cycle_index": cycle,
        "amount_cents": amount,
        "posted": True,
    })
    db.deposits[rec["id"]] = rec
    client["missed_deposit_streak"] = 0
    touch(client)
    return created(public(rec))


@app.post("/agencies/clients/<client_id>/sessions")
@require_auth({"Counselor"})
def open_session(client_id):
    client = get_or_404(db.clients, client_id)
    body = get_body()
    counselor_id = require_field(body, "counselor_id")
    session_type = require_field(body, "session_type")
    if session_type not in SESSION_TYPES:
        raise ApiError(E.ERR_VALIDATION, 422, "Invalid session_type")
    counselor = db.counselors.get(counselor_id)
    if counselor is None or counselor["agency_id"] != client["agency_id"]:
        raise ApiError(E.ERR_REFERENCE_NOT_FOUND, 422, "counselor_id does not resolve")
    in_flight = any(
        s["client_id"] == client_id and s["session_type"] == session_type
        and s["status"] in ("OPEN", "NEEDS_REVISION")
        for s in db.sessions.values()
    )
    if in_flight:
        raise ApiError(E.ERR_SESSION_TYPE_IN_FLIGHT, 409, "Same-type session in flight")
    rec = make_common()
    rec.update({
        "client_id": client_id,
        "counselor_id": counselor_id,
        "session_type": session_type,
        "status": "OPEN",
        "certificate_number": None,
    })
    db.sessions[rec["id"]] = rec
    return created(public(rec))


@app.post("/agencies/clients/<client_id>/debt-accounts")
@require_auth({"Counselor"})
def create_debt_account(client_id):
    client = get_or_404(db.clients, client_id)
    body = get_body()
    creditor_id = require_field(body, "creditor_id")
    account_ref = require_field(body, "account_ref")
    if not isinstance(account_ref, str):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "account_ref must be a string")
    orig_balance = as_int(require_field(body, "original_balance_cents"),
                          "original_balance_cents", positive=True)
    orig_apr = as_number(require_field(body, "original_apr"), "original_apr",
                         lo=0.0, hi=1.0)
    min_payment = as_int(require_field(body, "min_payment_cents"),
                         "min_payment_cents", positive=True)
    proposed = as_int(require_field(body, "proposed_monthly_payment_cents"),
                      "proposed_monthly_payment_cents", positive=True)
    requested_concession = body.get("requested_concession_apr")
    # FK resolution within agency
    creditor = db.creditors.get(creditor_id)
    if creditor is None or creditor["agency_id"] != client["agency_id"]:
        raise ApiError(E.ERR_REFERENCE_NOT_FOUND, 422, "creditor_id does not resolve")
    # account_ref uniqueness among non-DROPPED for this client (priority 6, before concession)
    for d in client_debt_accounts(client_id):
        if d["status"] != "DROPPED" and d["account_ref"] == account_ref:
            raise ApiError(E.ERR_DUPLICATE_ACCOUNT_REF, 409, "Duplicate account_ref")
    # proposed >= min_proposed_payment_pct * original_balance
    min_required = Decimal(str(creditor["min_proposed_payment_pct"])) * Decimal(orig_balance)
    if Decimal(proposed) < min_required:
        raise ApiError(E.ERR_INVALID_CONCESSION, 422, "proposed below creditor minimum")
    if requested_concession is None:
        requested_concession = creditor["default_concession_apr"]
    else:
        requested_concession = as_number(requested_concession,
                                         "requested_concession_apr", lo=0.0, hi=1.0)
    rec = make_common()
    rec.update({
        "client_id": client_id,
        "creditor_id": creditor_id,
        "account_ref": account_ref,
        "original_balance_cents": orig_balance,
        "current_balance_cents": None,
        "original_apr": orig_apr,
        "concession_apr": None,
        "min_payment_cents": min_payment,
        "proposed_monthly_payment_cents": proposed,
        "status": "PROPOSED",
    })
    db.debt_accounts[rec["id"]] = rec
    # Auto-create first CreditorProposal SUBMITTED round 1
    prop = make_common()
    prop.update({
        "debt_account_id": rec["id"],
        "creditor_id": creditor_id,
        "round_index": 1,
        "requested_concession_apr": requested_concession,
        "requested_waive_late_fees": body.get("requested_waive_late_fees", True),
        "countered_concession_apr": None,
        "status": "SUBMITTED",
    })
    db.proposals[prop["id"]] = prop
    # Recompute client derived (back_end_dti, monthly_deposit are computed on read)
    touch(client)
    return created(serialize_debt_account(rec))


@app.get("/agencies/clients/<client_id>/payoff_projection")
@require_auth({"AgencyAdmin", "Counselor"})
def payoff_projection(client_id):
    client = get_or_404(db.clients, client_id)
    enrolled = [d for d in client_debt_accounts(client_id)
                if d["status"] == "ENROLLED" and (d["current_balance_cents"] or 0) > 0]
    months_list = []
    for a in enrolled:
        monthly_interest = floor_interest(a["current_balance_cents"], a["concession_apr"])
        if monthly_interest is None:
            monthly_interest = 0
        net_principal = a["proposed_monthly_payment_cents"] - monthly_interest
        if net_principal <= 0:
            raise ApiError(E.ERR_NON_AMORTIZING_PLAN, 409, "Account does not amortize")
        months_list.append(math.ceil(a["current_balance_cents"] / net_principal))
    projected = max(months_list) if months_list else None
    out = serialize_client(client)
    out["projected_payoff_months"] = projected
    return ok(out)


# ===========================================================================
# DEPOSIT (read)
# ===========================================================================
@app.get("/agencies/deposits/<deposit_id>")
@require_auth({"AgencyAdmin", "Counselor"})
def get_deposit(deposit_id):
    rec = get_or_404(db.deposits, deposit_id)
    return ok(public(rec))


@app.get("/agencies/deposits")
@require_auth({"AgencyAdmin", "Counselor"})
def list_deposits():
    recs = list(db.deposits.values())
    client_id = request.args.get("client_id")
    if client_id is not None:
        recs = [r for r in recs if r["client_id"] == client_id]
    cycle = request.args.get("cycle_index")
    if cycle is not None:
        try:
            ci = int(cycle)
        except ValueError:
            raise ApiError(E.ERR_INVALID_REQUEST, 400, "cycle_index must be integer")
        recs = [r for r in recs if r["cycle_index"] == ci]
    return paginate(recs)


# ===========================================================================
# COUNSELING SESSION
# ===========================================================================
@app.get("/agencies/sessions/<session_id>")
@require_auth({"AgencyAdmin", "Counselor"})
def get_session(session_id):
    rec = get_or_404(db.sessions, session_id)
    return ok(public(rec))


@app.get("/agencies/sessions")
@require_auth({"AgencyAdmin", "Counselor"})
def list_sessions():
    recs = list(db.sessions.values())
    for key in ("client_id", "counselor_id", "session_type", "status"):
        val = request.args.get(key)
        if val is not None:
            recs = [r for r in recs if r[key] == val]
    return paginate(recs)


@app.post("/agencies/sessions/<session_id>/request_revision")
@require_auth({"Counselor"})
def session_request_revision(session_id):
    s = get_or_404(db.sessions, session_id)
    if s["status"] != "OPEN":
        raise ApiError(E.ERR_INVALID_STATE, 409, "Session not OPEN")
    s["status"] = "NEEDS_REVISION"
    touch(s)
    return ok(public(s))


@app.post("/agencies/sessions/<session_id>/resume")
@require_auth({"Counselor"})
def session_resume(session_id):
    s = get_or_404(db.sessions, session_id)
    if s["status"] != "NEEDS_REVISION":
        raise ApiError(E.ERR_INVALID_STATE, 409, "Session not NEEDS_REVISION")
    s["status"] = "OPEN"
    touch(s)
    return ok(public(s))


@app.post("/agencies/sessions/<session_id>/complete")
@require_auth({"Counselor"})
def session_complete(session_id):
    s = get_or_404(db.sessions, session_id)
    if s["status"] != "OPEN":
        raise ApiError(E.ERR_INVALID_STATE, 409, "Session not OPEN")
    if s["session_type"] == "BUDGET_INTAKE":
        client = db.clients.get(s["client_id"])
        if Decimal(str(compute_back_end_dti(client))) < MIN_ENROLL_DTI:
            raise ApiError(E.ERR_DTI_BELOW_THRESHOLD, 409, "back_end_dti below threshold")
    s["status"] = "COMPLETED"
    touch(s)
    return ok(public(s))


@app.post("/agencies/sessions/<session_id>/certify")
@require_auth({"Counselor"})
def session_certify(session_id):
    s = get_or_404(db.sessions, session_id)
    if s["status"] != "COMPLETED":
        raise ApiError(E.ERR_INVALID_STATE, 409, "Session not COMPLETED")
    if s["session_type"] not in CERTIFIABLE_TYPES:
        raise ApiError(E.ERR_SESSION_NOT_CERTIFIABLE, 409, "Session type not certifiable")
    if s["session_type"] == "HUD_HOUSING":
        counselor = db.counselors.get(s["counselor_id"])
        if not (counselor and counselor["hud_certified"]):
            raise ApiError(E.ERR_COUNSELOR_NOT_HUD_CERTIFIED, 409,
                           "Counselor not HUD certified")
    s["status"] = "CERTIFIED"
    s["certificate_number"] = "CERT-" + new_id().replace("-", "")[:16].upper()
    touch(s)
    return ok(public(s))


# ===========================================================================
# DEBT ACCOUNT (read / drop / savings)
# ===========================================================================
@app.get("/agencies/debt-accounts/<debt_account_id>")
@require_auth({"AgencyAdmin", "Counselor", "CreditorRep"})
def get_debt_account(debt_account_id):
    rec = get_or_404(db.debt_accounts, debt_account_id)
    return ok(serialize_debt_account(rec))


@app.get("/agencies/debt-accounts")
@require_auth({"AgencyAdmin", "Counselor", "CreditorRep"})
def list_debt_accounts():
    recs = list(db.debt_accounts.values())
    for key in ("client_id", "creditor_id", "status"):
        val = request.args.get(key)
        if val is not None:
            recs = [r for r in recs if r[key] == val]
    return paginate(recs, serialize=serialize_debt_account)


@app.post("/agencies/debt-accounts/<debt_account_id>/drop")
@require_auth({"Counselor"})
def drop_debt_account(debt_account_id):
    d = get_or_404(db.debt_accounts, debt_account_id)
    client = db.clients.get(d["client_id"])
    # State tier: account ENROLLED, then client ACTIVE
    if d["status"] != "ENROLLED":
        raise ApiError(E.ERR_INVALID_STATE, 409, "Account not ENROLLED")
    if client["status"] != "ACTIVE":
        raise ApiError(E.ERR_CLIENT_NOT_ACTIVE, 409, "Client not ACTIVE")
    d["status"] = "DROPPED"
    touch(d)
    client["monthly_deposit_cents"] = compute_monthly_deposit(client)
    touch(client)
    return ok(serialize_debt_account(d))


@app.get("/agencies/debt-accounts/<debt_account_id>/savings")
@require_auth({"AgencyAdmin", "Counselor"})
def debt_account_savings(debt_account_id):
    d = get_or_404(db.debt_accounts, debt_account_id)
    if d["status"] not in ("ACCEPTED", "ENROLLED") or d["concession_apr"] is None:
        raise ApiError(E.ERR_INVALID_STATE, 409, "Account has no concession")
    if d["status"] == "ENROLLED":
        basis = d["current_balance_cents"]
    else:
        basis = d["original_balance_cents"]
    orig_interest = floor_interest(basis, d["original_apr"])
    conc_interest = floor_interest(basis, d["concession_apr"])
    savings = orig_interest - conc_interest
    creditor = db.creditors.get(d["creditor_id"])
    late_fee_waiver = bool(creditor and creditor["waives_late_fees"]) and \
        d["status"] in ("ACCEPTED", "ENROLLED")
    high_interest = Decimal(str(d["original_apr"])) > LATE_FEE_THRESHOLD_APR
    out = serialize_debt_account(d)
    out["original_monthly_interest_cents"] = orig_interest
    out["concession_monthly_interest_cents"] = conc_interest
    out["monthly_interest_savings_cents"] = savings
    out["late_fee_waiver_applied"] = late_fee_waiver
    out["high_interest"] = high_interest
    return ok(out)


# ===========================================================================
# CREDITOR PROPOSAL
# ===========================================================================
@app.get("/agencies/proposals/<proposal_id>")
@require_auth({"AgencyAdmin", "Counselor", "CreditorRep"})
def get_proposal(proposal_id):
    rec = get_or_404(db.proposals, proposal_id)
    return ok(public(rec))


@app.get("/agencies/proposals")
@require_auth({"AgencyAdmin", "Counselor", "CreditorRep"})
def list_proposals():
    recs = list(db.proposals.values())
    for key in ("debt_account_id", "creditor_id", "status"):
        val = request.args.get(key)
        if val is not None:
            recs = [r for r in recs if r[key] == val]
    return paginate(recs)


@app.post("/agencies/proposals/<proposal_id>/counter")
@require_auth({"CreditorRep"})
def proposal_counter(proposal_id):
    p = get_or_404(db.proposals, proposal_id)
    body = get_body()
    if p["status"] != "SUBMITTED":
        raise ApiError(E.ERR_INVALID_STATE, 409, "Proposal not SUBMITTED")
    countered = body.get("countered_concession_apr")
    d = db.debt_accounts[p["debt_account_id"]]
    if countered is None:
        raise ApiError(E.ERR_INVALID_CONCESSION, 422, "countered_concession_apr required")
    countered = as_number(countered, "countered_concession_apr", lo=0.0, hi=1.0)
    if not (Decimal(str(countered)) < Decimal(str(d["original_apr"]))):
        raise ApiError(E.ERR_INVALID_CONCESSION, 422, "counter must be below original_apr")
    p["countered_concession_apr"] = countered
    p["status"] = "COUNTERED"
    touch(p)
    d["status"] = "COUNTERED"
    touch(d)
    return ok(public(p))


@app.post("/agencies/proposals/<proposal_id>/resubmit")
@require_auth({"Counselor"})
def proposal_resubmit(proposal_id):
    p = get_or_404(db.proposals, proposal_id)
    body = get_body()
    if p["status"] != "COUNTERED":
        raise ApiError(E.ERR_INVALID_STATE, 409, "Proposal not COUNTERED")
    requested = body.get("requested_concession_apr")
    if requested is None:
        raise ApiError(E.ERR_INVALID_CONCESSION, 422, "requested_concession_apr required")
    requested = as_number(requested, "requested_concession_apr", lo=0.0, hi=1.0)
    d = db.debt_accounts[p["debt_account_id"]]
    p["requested_concession_apr"] = requested
    p["round_index"] += 1
    p["status"] = "SUBMITTED"
    touch(p)
    d["status"] = "PROPOSED"
    touch(d)
    return ok(public(p))


@app.post("/agencies/proposals/<proposal_id>/accept")
@require_auth({"CreditorRep"})
def proposal_accept(proposal_id):
    p = get_or_404(db.proposals, proposal_id)
    if p["status"] != "SUBMITTED":
        raise ApiError(E.ERR_INVALID_STATE, 409, "Proposal not SUBMITTED")
    d = db.debt_accounts[p["debt_account_id"]]
    p["status"] = "ACCEPTED"
    touch(p)
    d["concession_apr"] = p["requested_concession_apr"]
    d["status"] = "ACCEPTED"
    touch(d)
    return ok(public(p))


@app.post("/agencies/proposals/<proposal_id>/accept_counter")
@require_auth({"Counselor"})
def proposal_accept_counter(proposal_id):
    p = get_or_404(db.proposals, proposal_id)
    if p["status"] != "COUNTERED":
        raise ApiError(E.ERR_INVALID_STATE, 409, "Proposal not COUNTERED")
    d = db.debt_accounts[p["debt_account_id"]]
    p["status"] = "ACCEPTED"
    touch(p)
    d["concession_apr"] = p["countered_concession_apr"]
    d["status"] = "ACCEPTED"
    touch(d)
    return ok(public(p))


@app.post("/agencies/proposals/<proposal_id>/reject")
@require_auth({"CreditorRep"})
def proposal_reject(proposal_id):
    p = get_or_404(db.proposals, proposal_id)
    if p["status"] not in ("SUBMITTED", "COUNTERED"):
        raise ApiError(E.ERR_INVALID_STATE, 409, "Proposal not SUBMITTED/COUNTERED")
    d = db.debt_accounts[p["debt_account_id"]]
    p["status"] = "REJECTED"
    touch(p)
    d["status"] = "DROPPED"
    touch(d)
    return ok(public(p))


# ===========================================================================
# DISBURSEMENT RUN
# ===========================================================================
def prorate_disbursement(disbursable, eligible):
    """Largest-remainder (Hamilton) apportionment with balance caps.

    eligible: list of debt-account dicts sorted by (created_at, _seq) ASC.
    Returns dict {account_id: cents}.
    """
    if disbursable <= 0 or not eligible:
        return {a["id"]: 0 for a in eligible}
    weights = {a["id"]: a["proposed_monthly_payment_cents"] for a in eligible}
    W = sum(weights.values())
    if W <= 0:
        return {a["id"]: 0 for a in eligible}
    exact = {}
    target = {}
    for a in eligible:
        ex = Decimal(disbursable) * Decimal(weights[a["id"]]) / Decimal(W)
        exact[a["id"]] = ex
        target[a["id"]] = int(ex.to_integral_value(rounding="ROUND_FLOOR"))
    remainder = disbursable - sum(target.values())
    # order by descending fractional part, tie-break by created_at ASC (eligible order)
    def frac(a):
        ex = exact[a["id"]]
        return ex - ex.to_integral_value(rounding="ROUND_FLOOR")
    order = sorted(eligible, key=lambda a: (-frac(a),))
    # stable sort keeps eligible (created_at ASC) order for equal fractional parts
    for i in range(remainder):
        target[order[i % len(order)]["id"]] += 1
    # Cap by balance; redistribute overflow to under-cap accounts by created_at ASC
    line = {}
    overflow = 0
    for a in eligible:
        cap = a["current_balance_cents"]
        amt = target[a["id"]]
        if amt > cap:
            overflow += amt - cap
            line[a["id"]] = cap
        else:
            line[a["id"]] = amt
    # Redistribute overflow to accounts still under their cap, ascending
    # created_at: fill each under-cap account up to its remaining headroom
    # before moving to the next (sequential, not round-robin).
    for a in eligible:
        if overflow <= 0:
            break
        cap = a["current_balance_cents"]
        headroom = cap - line[a["id"]]
        if headroom <= 0:
            continue
        take = min(headroom, overflow)
        line[a["id"]] += take
        overflow -= take
    return line


@app.post("/agencies/agencies/<agency_id>/run_disbursement")
@require_auth({"AgencyAdmin"})
def run_disbursement(agency_id):
    agency = get_or_404(db.agencies, agency_id)
    # Deposits are stamped with the cycle index that is current at record time;
    # the run advances the index by one, then matches each client against the
    # deposit recorded for the cycle that was current before this advance
    # (i.e. cycle - 1). This is what makes the record-deposit-then-run sequence
    # disburse on the very first run (PRD §3.6).
    deposit_cycle = agency["current_cycle_index"]
    agency["current_cycle_index"] += 1
    touch(agency)
    cycle = agency["current_cycle_index"]

    active_clients = [c for c in db.clients.values()
                      if c["agency_id"] == agency_id and c["status"] == "ACTIVE"]
    # deterministic order
    active_clients.sort(key=lambda c: (c["created_at"], c["_seq"]))

    clients_processed = 0
    clients_defaulted = 0
    total_disbursed = 0

    run = make_common()
    run.update({
        "agency_id": agency_id,
        "cycle_index": cycle,
        "clients_processed": 0,
        "clients_defaulted": 0,
        "total_disbursed_cents": 0,
        "status": "COMPLETED",
    })

    for client in active_clients:
        clients_processed += 1
        deposit = next((dep for dep in db.deposits.values()
                        if dep["client_id"] == client["id"]
                        and dep["cycle_index"] == deposit_cycle), None)
        if deposit is None:
            # missed deposit
            client["missed_deposit_streak"] += 1
            if client["missed_deposit_streak"] >= MISSED_DEPOSIT_LIMIT:
                client["status"] = "DEFAULTED"
                clients_defaulted += 1
            touch(client)
            continue
        # has deposit -> prorate & disburse
        disbursable = deposit["amount_cents"] - agency["monthly_fee_cents"]
        eligible = [a for a in client_debt_accounts(client["id"])
                    if a["status"] == "ENROLLED" and (a["current_balance_cents"] or 0) > 0]
        eligible.sort(key=lambda a: (a["created_at"], a["_seq"]))
        line_amounts = prorate_disbursement(disbursable, eligible)
        for a in eligible:
            amt = line_amounts.get(a["id"], 0)
            if amt <= 0:
                continue
            a["current_balance_cents"] -= amt
            total_disbursed += amt
            settled = a["current_balance_cents"] == 0
            if settled:
                a["status"] = "SETTLED"
            touch(a)
            dl = make_common(versioned=False)
            dl.update({
                "disbursement_run_id": run["id"],
                "client_id": client["id"],
                "debt_account_id": a["id"],
                "amount_cents": amt,
                "balance_after_cents": a["current_balance_cents"],
            })
            db.disbursement_lines[dl["id"]] = dl
        # graduation: every account SETTLED or DROPPED with >= 1 SETTLED
        accounts = client_debt_accounts(client["id"])
        if accounts and all(a["status"] in ("SETTLED", "DROPPED") for a in accounts) \
                and any(a["status"] == "SETTLED" for a in accounts):
            client["status"] = "GRADUATED"
        touch(client)

    run["clients_processed"] = clients_processed
    run["clients_defaulted"] = clients_defaulted
    run["total_disbursed_cents"] = total_disbursed
    db.disbursement_runs[run["id"]] = run
    return created(public(run))


@app.get("/agencies/disbursement-runs/<run_id>")
@require_auth({"AgencyAdmin", "Counselor"})
def get_disbursement_run(run_id):
    rec = get_or_404(db.disbursement_runs, run_id)
    return ok(public(rec))


@app.get("/agencies/disbursement-runs")
@require_auth({"AgencyAdmin", "Counselor"})
def list_disbursement_runs():
    recs = list(db.disbursement_runs.values())
    agency_id = request.args.get("agency_id")
    if agency_id is not None:
        recs = [r for r in recs if r["agency_id"] == agency_id]
    cycle = request.args.get("cycle_index")
    if cycle is not None:
        try:
            ci = int(cycle)
        except ValueError:
            raise ApiError(E.ERR_INVALID_REQUEST, 400, "cycle_index must be integer")
        recs = [r for r in recs if r["cycle_index"] == ci]
    return paginate(recs)


@app.get("/agencies/disbursement-lines/<line_id>")
@require_auth({"AgencyAdmin", "Counselor"})
def get_disbursement_line(line_id):
    rec = get_or_404(db.disbursement_lines, line_id)
    return ok(public(rec))


@app.get("/agencies/disbursement-lines")
@require_auth({"AgencyAdmin", "Counselor"})
def list_disbursement_lines():
    recs = list(db.disbursement_lines.values())
    for key in ("disbursement_run_id", "client_id", "debt_account_id"):
        val = request.args.get(key)
        if val is not None:
            recs = [r for r in recs if r[key] == val]
    return paginate(recs)


# ===========================================================================
# Error handlers
# ===========================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return err_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return err_response(E.ERR_NOT_FOUND, 404, "Resource not found")


@app.errorhandler(405)
def handle_405(e):
    return err_response(E.ERR_NOT_FOUND, 404, "Method not allowed")


@app.errorhandler(400)
def handle_400(e):
    return err_response(E.ERR_INVALID_REQUEST, 400, "Bad request")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return err_response(e.error_id, e.http_status, e.message)
    return err_response(E.ERR_INVALID_REQUEST, 400, str(e))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
