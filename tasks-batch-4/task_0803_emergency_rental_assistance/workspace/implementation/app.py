import os
import random
import string
import re
from datetime import datetime, date
from calendar import monthrange
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

from flask import Flask, request, jsonify

app = Flask(__name__)

# =====================================================================
# In-memory stores (wiped on every process boot; NEVER seeded)
# =====================================================================
programs = {}
tenants = {}
landlords = {}
units = {}
applications = {}
income_sources = {}
ledgers = {}
ledger_lines = {}
disbursements = {}
recertifications = {}
recapture_cases = {}

_seq_counter = 0

# logical clock (default fixed; never falls back to wall clock)
CLOCK = datetime(2026, 3, 1, 0, 0, 0)

ROLES = {"Anonymous", "Tenant", "Landlord", "CaseWorker", "ProgramAdmin", "FraudInvestigator"}

HARDSHIP_TYPES = {"JOB_LOSS", "REDUCED_INCOME", "MEDICAL", "OTHER"}
SOURCE_TYPES = {"WAGES", "SELF_EMPLOYMENT", "UNEMPLOYMENT", "SSI", "TANF", "CHILD_SUPPORT"}
COUNTABLE_TYPES = {"WAGES", "SELF_EMPLOYMENT", "UNEMPLOYMENT"}
LINE_TYPES = {"CHARGE", "PAYMENT", "ADJUSTMENT"}
COVERAGE_KINDS = {"ARREARS", "PROSPECTIVE", "COMBINED"}
RECAP_REASONS = {"DUPLICATE_BENEFIT", "INCOME_MISREPRESENTATION", "VACATED_UNIT", "OTHER"}
VERIFY_DECISIONS = {"VERIFIED", "REJECTED"}
RECERT_DECISIONS = {"APPROVE", "DENY"}

RESERVING = {"PENDING", "SENT", "CLEARED"}


# =====================================================================
# Errors
# =====================================================================
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# =====================================================================
# Helpers: clock / ids / seq
# =====================================================================
def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def now_iso():
    dt = CLOCK
    return "{:%Y-%m-%dT%H:%M:%S}.{:03d}Z".format(dt, dt.microsecond // 1000)


def new_id():
    return str(uuid4())


def request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def base_entity():
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(entity):
    entity["updated_at"] = now_iso()
    entity["version"] += 1


# =====================================================================
# Response envelope
# =====================================================================
def meta_base():
    return {"api_request_id": request_id(), "api_request_timestamp": now_iso()}


def ok(data, status=200):
    body = {"meta": meta_base(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total):
    m = meta_base()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total
    m["has_more"] = (offset + limit) < total
    body = {"meta": m, "response_type": "array", "data": items}
    return jsonify(body), 200


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# =====================================================================
# Auth / RBAC
# =====================================================================
def authenticate(allowed_roles, anonymous_ok=False):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if anonymous_ok:
        return uid, role
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unknown authentication headers")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role is not permitted for this operation")
    return uid, role


# =====================================================================
# Existence
# =====================================================================
def get_or_404(store, oid, err_id):
    if oid is None or oid not in store:
        raise ApiError(err_id, 404, "Referenced resource not found")
    return store[oid]


# =====================================================================
# Body helpers
# =====================================================================
def get_body():
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return body


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg)


def req_int(body, key, minimum=None, maximum=None):
    if key not in body or body[key] is None:
        bad("Missing required field: " + key)
    v = body[key]
    if not is_int(v):
        bad("Field must be an integer: " + key)
    if minimum is not None and v < minimum:
        bad("Field below minimum: " + key)
    if maximum is not None and v > maximum:
        bad("Field above maximum: " + key)
    return v


def req_str(body, key):
    if key not in body or body[key] is None:
        bad("Missing required field: " + key)
    v = body[key]
    if not isinstance(v, str) or v == "":
        bad("Field must be a non-empty string: " + key)
    return v


MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def valid_month(s):
    if not isinstance(s, str) or not MONTH_RE.match(s):
        return False
    m = int(s[5:7])
    return 1 <= m <= 12


def valid_date(s):
    if not isinstance(s, str) or not DATE_RE.match(s):
        return False
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


# =====================================================================
# Pagination
# =====================================================================
def get_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args["limit"])
        except (ValueError, TypeError):
            bad("limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if "offset" in args:
        try:
            offset = int(args["offset"])
        except (ValueError, TypeError):
            bad("offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate_and_respond(items):
    items = sorted(items, key=lambda e: e["_seq"])
    limit, offset = get_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


# =====================================================================
# Computed reservation values
# =====================================================================
def program_reserved(program_id):
    total = 0
    for d in disbursements.values():
        appn = applications.get(d["application_id"])
        if appn and appn["program_id"] == program_id and d["status"] in RESERVING:
            total += d["amount_cents"]
    return total


def program_remaining(program):
    return program["funding_pool_total_cents"] - program_reserved(program["id"])


def program_status(program):
    return "EXHAUSTED" if program_remaining(program) <= 0 else "OPEN"


def tenant_months_used(tenant_id):
    total = 0
    for d in disbursements.values():
        appn = applications.get(d["application_id"])
        if appn and appn["tenant_id"] == tenant_id and d["status"] in RESERVING:
            total += d["months_covered"]
    return total


def app_total_disbursed(app_id):
    total = 0
    for d in disbursements.values():
        if d["application_id"] == app_id and d["status"] == "CLEARED":
            total += d["amount_cents"]
    return total


def app_reserved_amount(app_id):
    total = 0
    for d in disbursements.values():
        if d["application_id"] == app_id and d["status"] in RESERVING:
            total += d["amount_cents"]
    return total


def app_reserved_months(app_id):
    total = 0
    for d in disbursements.values():
        if d["application_id"] == app_id and d["status"] in RESERVING:
            total += d["months_covered"]
    return total


def ledger_for_app(app_id):
    for l in ledgers.values():
        if l["application_id"] == app_id:
            return l
    return None


def active_fraud_hold(app_id):
    for c in recapture_cases.values():
        if c["application_id"] == app_id and c["status"] in ("OPEN", "SUBSTANTIATED"):
            return True
    return False


# =====================================================================
# Serializers
# =====================================================================
COMMON = ["id", "created_at", "updated_at", "version"]


def _pick(entity, fields):
    out = {}
    for f in COMMON:
        out[f] = entity[f]
    for f in fields:
        out[f] = entity.get(f)
    return out


def serialize_program(p):
    d = _pick(p, ["name", "funding_pool_total_cents", "months_cap",
                  "per_month_max_cents", "monthly_income_limit_by_size",
                  "eligibility_ami_pct"])
    d["funding_pool_remaining_cents"] = program_remaining(p)
    d["status"] = program_status(p)
    return d


def serialize_tenant(t):
    d = _pick(t, ["full_name", "email", "household_size"])
    d["months_used"] = tenant_months_used(t["id"])
    return d


def serialize_landlord(l):
    return _pick(l, ["legal_name", "email", "w9_status", "tin",
                     "banking_last4", "mailing_address"])


def serialize_unit(u):
    return _pick(u, ["landlord_id", "address", "monthly_rent_cents"])


def serialize_application(a):
    d = _pick(a, [
        "program_id", "tenant_id", "landlord_id", "unit_id", "status",
        "tenant_section_status", "landlord_section_status", "hardship_type",
        "hardship_attested", "monthly_rent_cents", "arrears_start_month",
        "arrears_end_month", "arrears_covered_months", "requested_prospective_months",
        "prospective_start_date", "prospective_end_date",
        "countable_monthly_income_cents", "ami_pct", "income_eligible",
        "arrears_owed_cents", "arrears_award_cents", "prospective_award_cents",
        "total_award_cents", "months_awarded", "approved_by_cw_id", "decision_reason",
    ])
    d["total_disbursed_cents"] = app_total_disbursed(a["id"])
    return d


def serialize_income_source(i):
    return _pick(i, ["application_id", "source_type", "monthly_amount_cents", "countable"])


def serialize_ledger(l):
    return _pick(l, ["application_id", "status", "verified_by_id"])


def serialize_ledger_line(ll):
    return _pick(ll, ["ledger_id", "month", "line_type", "charge_cents", "payment_cents"])


def serialize_disbursement(d):
    return _pick(d, ["application_id", "amount_cents", "months_covered",
                     "coverage_kind", "status", "issued_by_cw_id", "payment_reference"])


def serialize_recert(r):
    return _pick(r, ["application_id", "requested_additional_months",
                     "new_prospective_start_date", "new_prospective_end_date",
                     "status", "decision_reason"])


def serialize_recapture(c):
    return _pick(c, ["application_id", "disbursement_id", "reason", "status",
                     "recovered_amount_cents"])


# =====================================================================
# Ownership
# =====================================================================
def check_owner_tenant(uid, tenant_id):
    if uid != tenant_id:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP", 403, "Acting tenant does not own the target")


def check_owner_landlord(uid, landlord_id):
    if uid != landlord_id:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP", 403, "Acting landlord does not own the target")


# =====================================================================
# Calculations
# =====================================================================
def month_index(ym):
    y = int(ym[0:4])
    m = int(ym[5:7])
    return y * 12 + (m - 1)


def count_month_span(start_ym, end_ym):
    return month_index(end_ym) - month_index(start_ym) + 1


def add_one_month(d):
    y, m = d.year, d.month
    m += 1
    if m > 12:
        m = 1
        y += 1
    dim = monthrange(y, m)[1]
    return date(y, m, min(d.day, dim))


def compute_arrears_owed(app):
    lg = ledger_for_app(app["id"])
    if lg is None:
        return 0
    lines = [ll for ll in ledger_lines.values() if ll["ledger_id"] == lg["id"]]
    lines.sort(key=lambda ll: (ll["month"], ll["_seq"]))
    outstanding = {}
    charges_order = []
    for ln in lines:
        if ln["line_type"] == "CHARGE":
            outstanding[ln["id"]] = ln.get("charge_cents") or 0
            charges_order.append(ln)
        else:
            credit = ln.get("payment_cents") or 0
            for c in charges_order:
                if credit <= 0:
                    break
                rem = outstanding[c["id"]]
                if rem <= 0:
                    continue
                take = min(rem, credit)
                outstanding[c["id"]] -= take
                credit -= take
    start = app.get("arrears_start_month")
    end = app.get("arrears_end_month")
    if not start or not end:
        return 0
    total = 0
    for c in charges_order:
        if start <= c["month"] <= end:
            total += outstanding[c["id"]]
    return total


def prospective_month_amounts(psd, ped, monthly_award):
    start = parse_date(psd)
    end = parse_date(ped)
    res = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        dim = monthrange(y, m)[1]
        mfirst = date(y, m, 1)
        mlast = date(y, m, dim)
        os_ = max(start, mfirst)
        oe = min(end, mlast)
        covered = (oe - os_).days + 1
        if covered >= dim:
            amt = monthly_award
        else:
            amt = int((Decimal(monthly_award * covered) / Decimal(dim)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP))
        res.append(amt)
        m += 1
        if m > 12:
            m = 1
            y += 1
    return res


def compute_income(app):
    incs = [i for i in income_sources.values() if i["application_id"] == app["id"]]
    countable = sum(i["monthly_amount_cents"] for i in incs if i["countable"])
    program = programs[app["program_id"]]
    tenant = tenants[app["tenant_id"]]
    limit = program["monthly_income_limit_by_size"].get(str(tenant["household_size"]))
    if limit is None:
        income_eligible = False
        ami_pct = 0.0
    else:
        income_eligible = countable <= limit
        denom = limit / program["eligibility_ami_pct"] if program["eligibility_ami_pct"] else 0
        ami_pct = (countable / denom) if denom else 0.0
    return countable, income_eligible, ami_pct


# =====================================================================
# Program endpoints
# =====================================================================
@app.route("/programs", methods=["POST"])
def create_program():
    authenticate({"ProgramAdmin"})
    body = get_body()
    name = req_str(body, "name")
    total = req_int(body, "funding_pool_total_cents", minimum=0)
    per_month_max = req_int(body, "per_month_max_cents", minimum=0)
    table = body.get("monthly_income_limit_by_size")
    if table is None or not isinstance(table, dict):
        bad("monthly_income_limit_by_size must be an object")
    months_cap = 18
    if "months_cap" in body and body["months_cap"] is not None:
        months_cap = req_int(body, "months_cap", minimum=0)
    ami_pct = 0.80
    if "eligibility_ami_pct" in body and body["eligibility_ami_pct"] is not None:
        v = body["eligibility_ami_pct"]
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            bad("eligibility_ami_pct must be a number")
        ami_pct = float(v)
    p = base_entity()
    p.update({
        "name": name,
        "funding_pool_total_cents": total,
        "per_month_max_cents": per_month_max,
        "monthly_income_limit_by_size": table,
        "months_cap": months_cap,
        "eligibility_ami_pct": ami_pct,
    })
    programs[p["id"]] = p
    return ok(serialize_program(p), 201)


@app.route("/programs/<pid>", methods=["GET"])
def get_program(pid):
    authenticate({"ProgramAdmin", "CaseWorker", "Tenant", "Landlord", "FraudInvestigator"})
    p = get_or_404(programs, pid, "ERR_PROGRAM_NOT_FOUND")
    return ok(serialize_program(p))


@app.route("/programs/<pid>/funding", methods=["PATCH"])
def patch_funding(pid):
    authenticate({"ProgramAdmin"})
    p = get_or_404(programs, pid, "ERR_PROGRAM_NOT_FOUND")
    body = get_body()
    total = req_int(body, "funding_pool_total_cents", minimum=0)
    p["funding_pool_total_cents"] = total
    touch(p)
    return ok(serialize_program(p))


# =====================================================================
# Tenant endpoints
# =====================================================================
@app.route("/tenants", methods=["POST"])
def create_tenant():
    body = get_body()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    household_size = req_int(body, "household_size", minimum=1)
    t = base_entity()
    t.update({"full_name": full_name, "email": email, "household_size": household_size})
    tenants[t["id"]] = t
    return ok(serialize_tenant(t), 201)


@app.route("/tenants/<tid>", methods=["GET"])
def get_tenant(tid):
    authenticate({"ProgramAdmin", "CaseWorker", "Tenant", "FraudInvestigator"})
    t = get_or_404(tenants, tid, "ERR_TENANT_NOT_FOUND")
    return ok(serialize_tenant(t))


# =====================================================================
# Landlord endpoints
# =====================================================================
@app.route("/landlords", methods=["POST"])
def create_landlord():
    body = get_body()
    legal_name = req_str(body, "legal_name")
    email = req_str(body, "email")
    l = base_entity()
    l.update({
        "legal_name": legal_name, "email": email, "w9_status": "MISSING",
        "tin": None, "banking_last4": None, "mailing_address": None,
    })
    landlords[l["id"]] = l
    return ok(serialize_landlord(l), 201)


@app.route("/landlords/<lid>", methods=["GET"])
def get_landlord(lid):
    authenticate({"ProgramAdmin", "CaseWorker", "Landlord", "FraudInvestigator"})
    l = get_or_404(landlords, lid, "ERR_LANDLORD_NOT_FOUND")
    return ok(serialize_landlord(l))


@app.route("/landlords/<lid>/w9", methods=["POST"])
def submit_w9(lid):
    uid, role = authenticate({"Landlord"})
    l = get_or_404(landlords, lid, "ERR_LANDLORD_NOT_FOUND")
    check_owner_landlord(uid, l["id"])
    if l["w9_status"] not in ("MISSING", "REJECTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "W-9 cannot be submitted from current state")
    body = get_body()
    tin = req_str(body, "tin")
    banking_last4 = req_str(body, "banking_last4")
    mailing_address = req_str(body, "mailing_address")
    l["tin"] = tin
    l["banking_last4"] = banking_last4
    l["mailing_address"] = mailing_address
    l["w9_status"] = "SUBMITTED"
    touch(l)
    return ok(serialize_landlord(l))


@app.route("/landlords/<lid>/w9/verify", methods=["POST"])
def verify_w9(lid):
    authenticate({"ProgramAdmin"})
    l = get_or_404(landlords, lid, "ERR_LANDLORD_NOT_FOUND")
    if l["w9_status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "W-9 is not in a verifiable state")
    body = get_body()
    decision = body.get("decision")
    if decision not in VERIFY_DECISIONS:
        bad("decision must be one of VERIFIED, REJECTED")
    l["w9_status"] = decision
    touch(l)
    return ok(serialize_landlord(l))


# =====================================================================
# Unit endpoints
# =====================================================================
@app.route("/units", methods=["POST"])
def create_unit():
    uid, role = authenticate({"Landlord"})
    body = get_body()
    landlord_id = body.get("landlord_id")
    if landlord_id is not None:
        get_or_404(landlords, landlord_id, "ERR_LANDLORD_NOT_FOUND")
        check_owner_landlord(uid, landlord_id)
    landlord_id = req_str(body, "landlord_id")
    address = req_str(body, "address")
    monthly_rent_cents = req_int(body, "monthly_rent_cents", minimum=1)
    u = base_entity()
    u.update({"landlord_id": landlord_id, "address": address,
              "monthly_rent_cents": monthly_rent_cents})
    units[u["id"]] = u
    return ok(serialize_unit(u), 201)


@app.route("/units/<uid_>", methods=["GET"])
def get_unit(uid_):
    authenticate({"ProgramAdmin", "CaseWorker", "Landlord"})
    u = get_or_404(units, uid_, "ERR_UNIT_NOT_FOUND")
    return ok(serialize_unit(u))


@app.route("/units", methods=["GET"])
def list_units():
    authenticate({"ProgramAdmin", "CaseWorker", "Landlord"})
    landlord_id = request.args.get("landlord_id")
    items = [u for u in units.values() if landlord_id is None or u["landlord_id"] == landlord_id]
    page, limit, offset, total = paginate_and_respond(items)
    return ok_list([serialize_unit(u) for u in page], limit, offset, total)


# =====================================================================
# Application endpoints
# =====================================================================
@app.route("/applications", methods=["POST"])
def create_application():
    uid, role = authenticate({"Tenant"})
    body = get_body()
    program_id = body.get("program_id")
    tenant_id = body.get("tenant_id")
    landlord_id = body.get("landlord_id")
    unit_id = body.get("unit_id")
    # existence, left-to-right (only for provided ids)
    if program_id is not None:
        get_or_404(programs, program_id, "ERR_PROGRAM_NOT_FOUND")
    if tenant_id is not None:
        get_or_404(tenants, tenant_id, "ERR_TENANT_NOT_FOUND")
    if landlord_id is not None:
        get_or_404(landlords, landlord_id, "ERR_LANDLORD_NOT_FOUND")
    if unit_id is not None:
        get_or_404(units, unit_id, "ERR_UNIT_NOT_FOUND")
    # ownership: tenant creates for self
    if tenant_id is not None:
        check_owner_tenant(uid, tenant_id)
    # unit/landlord referential
    if unit_id is not None and landlord_id is not None:
        if units[unit_id]["landlord_id"] != landlord_id:
            raise ApiError("ERR_UNIT_LANDLORD_MISMATCH", 422,
                           "Unit landlord does not match application landlord")
    # structural validation (lowest priority)
    program_id = req_str(body, "program_id")
    tenant_id = req_str(body, "tenant_id")
    landlord_id = req_str(body, "landlord_id")
    unit_id = req_str(body, "unit_id")
    monthly_rent_cents = req_int(body, "monthly_rent_cents", minimum=1)
    requested_prospective_months = 0
    if "requested_prospective_months" in body and body["requested_prospective_months"] is not None:
        requested_prospective_months = req_int(body, "requested_prospective_months", minimum=0)

    asm = body.get("arrears_start_month")
    aem = body.get("arrears_end_month")
    if asm is not None and not valid_month(asm):
        bad("arrears_start_month must be YYYY-MM")
    if aem is not None and not valid_month(aem):
        bad("arrears_end_month must be YYYY-MM")
    psd = body.get("prospective_start_date")
    ped = body.get("prospective_end_date")
    if psd is not None and not valid_date(psd):
        bad("prospective_start_date must be YYYY-MM-DD")
    if ped is not None and not valid_date(ped):
        bad("prospective_end_date must be YYYY-MM-DD")

    arrears_covered_months = 0
    if asm and aem:
        arrears_covered_months = count_month_span(asm, aem)

    a = base_entity()
    a.update({
        "program_id": program_id, "tenant_id": tenant_id, "landlord_id": landlord_id,
        "unit_id": unit_id, "status": "DRAFT",
        "tenant_section_status": "INCOMPLETE", "landlord_section_status": "INCOMPLETE",
        "hardship_type": None, "hardship_attested": False,
        "monthly_rent_cents": monthly_rent_cents,
        "arrears_start_month": asm, "arrears_end_month": aem,
        "arrears_covered_months": arrears_covered_months,
        "requested_prospective_months": requested_prospective_months,
        "prospective_start_date": psd, "prospective_end_date": ped,
        "countable_monthly_income_cents": 0, "ami_pct": 0.0, "income_eligible": False,
        "arrears_owed_cents": 0, "arrears_award_cents": 0, "prospective_award_cents": 0,
        "total_award_cents": 0, "months_awarded": 0,
        "approved_by_cw_id": None, "decision_reason": None,
    })
    applications[a["id"]] = a
    return ok(serialize_application(a), 201)


@app.route("/applications/<aid>", methods=["GET"])
def get_application(aid):
    authenticate({"ProgramAdmin", "CaseWorker", "Tenant", "Landlord", "FraudInvestigator"})
    a = get_or_404(applications, aid, "ERR_APPLICATION_NOT_FOUND")
    return ok(serialize_application(a))


@app.route("/applications", methods=["GET"])
def list_applications():
    authenticate({"ProgramAdmin", "CaseWorker", "Tenant", "Landlord", "FraudInvestigator"})
    args = request.args
    items = list(applications.values())
    for key in ("tenant_id", "landlord_id", "unit_id", "program_id", "status"):
        val = args.get(key)
        if val is not None:
            items = [a for a in items if a[key] == val]
    page, limit, offset, total = paginate_and_respond(items)
    return ok_list([serialize_application(a) for a in page], limit, offset, total)


@app.route("/applications/<aid>/tenant-section", methods=["PATCH"])
def tenant_section(aid):
    uid, role = authenticate({"Tenant"})
    a = get_or_404(applications, aid, "ERR_APPLICATION_NOT_FOUND")
    check_owner_tenant(uid, a["tenant_id"])
    body = get_body()
    hardship_type = body.get("hardship_type")
    if hardship_type not in HARDSHIP_TYPES:
        bad("hardship_type must be one of JOB_LOSS, REDUCED_INCOME, MEDICAL, OTHER")
    hardship_attested = body.get("hardship_attested")
    if not isinstance(hardship_attested, bool):
        bad("hardship_attested must be a boolean")
    has_income = any(i["application_id"] == a["id"] for i in income_sources.values())
    if not has_income:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "At least one income source is required to complete the tenant section")
    a["hardship_type"] = hardship_type
    a["hardship_attested"] = hardship_attested
    a["tenant_section_status"] = "COMPLETE"
    touch(a)
    return ok(serialize_application(a))


@app.route("/applications/<aid>/landlord-section", methods=["PATCH"])
def landlord_section(aid):
    uid, role = authenticate({"Landlord"})
    a = get_or_404(applications, aid, "ERR_APPLICATION_NOT_FOUND")
    check_owner_landlord(uid, a["landlord_id"])
    lg = ledger_for_app(a["id"])
    if not a.get("unit_id") or lg is None:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Unit and a submitted rent ledger are required to complete the landlord section")
    a["landlord_section_status"] = "COMPLETE"
    touch(a)
    return ok(serialize_application(a))


@app.route("/applications/<aid>/submit", methods=["POST"])
def submit_application(aid):
    uid, role = authenticate({"Tenant"})
    a = get_or_404(applications, aid, "ERR_APPLICATION_NOT_FOUND")
    check_owner_tenant(uid, a["tenant_id"])
    if a["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Application cannot be submitted from current state")
    if a["tenant_section_status"] != "COMPLETE" or a["landlord_section_status"] != "COMPLETE":
        raise ApiError("ERR_SECTION_INCOMPLETE", 409, "Both sections must be complete to submit")
    a["status"] = "SUBMITTED"
    touch(a)
    return ok(serialize_application(a))


@app.route("/applications/<aid>/review", methods=["POST"])
def review_application(aid):
    authenticate({"CaseWorker"})
    a = get_or_404(applications, aid, "ERR_APPLICATION_NOT_FOUND")
    if a["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Application is not submitted")
    a["status"] = "UNDER_REVIEW"
    touch(a)
    return ok(serialize_application(a))


@app.route("/applications/<aid>/request-info", methods=["POST"])
def request_info(aid):
    authenticate({"CaseWorker"})
    a = get_or_404(applications, aid, "ERR_APPLICATION_NOT_FOUND")
    if a["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Application is not under review")
    a["status"] = "INFO_REQUESTED"
    touch(a)
    return ok(serialize_application(a))


@app.route("/applications/<aid>/resubmit", methods=["POST"])
def resubmit_application(aid):
    uid, role = authenticate({"Tenant", "Landlord"})
    a = get_or_404(applications, aid, "ERR_APPLICATION_NOT_FOUND")
    if role == "Tenant":
        check_owner_tenant(uid, a["tenant_id"])
    else:
        check_owner_landlord(uid, a["landlord_id"])
    if a["status"] != "INFO_REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Application is not awaiting resubmission")
    a["status"] = "UNDER_REVIEW"
    touch(a)
    return ok(serialize_application(a))


@app.route("/applications/<aid>/approve", methods=["POST"])
def approve_application(aid):
    uid, role = authenticate({"CaseWorker"})
    a = get_or_404(applications, aid, "ERR_APPLICATION_NOT_FOUND")
    if a["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Application is not under review")
    body = get_body()
    program = programs[a["program_id"]]
    tenant = tenants[a["tenant_id"]]
    landlord = landlords[a["landlord_id"]]
    lg = ledger_for_app(a["id"])

    # gate 1: W-9 verified
    if landlord["w9_status"] != "VERIFIED":
        raise ApiError("ERR_W9_NOT_VERIFIED", 422, "Landlord W-9 is not verified")
    # gate 2: ledger verified
    if lg is None or lg["status"] != "VERIFIED":
        raise ApiError("ERR_LEDGER_NOT_VERIFIED", 422, "Rent ledger is not verified")
    # gate 3: hardship attested
    if not a["hardship_attested"]:
        raise ApiError("ERR_HARDSHIP_NOT_ATTESTED", 422, "Hardship is not attested")
    # gate 4: income eligible
    countable, income_eligible, ami_pct = compute_income(a)
    if not income_eligible:
        raise ApiError("ERR_INCOME_INELIGIBLE", 422, "Household is not income-eligible")
    # gate 5: duplicate benefit on arrears (same unit)
    if a.get("arrears_start_month") and a.get("arrears_end_month"):
        s1 = month_index(a["arrears_start_month"])
        e1 = month_index(a["arrears_end_month"])
        for other in applications.values():
            if other["id"] == a["id"]:
                continue
            if other["unit_id"] != a["unit_id"]:
                continue
            if other["status"] not in ("APPROVED", "DISBURSED"):
                continue
            if not (other.get("arrears_start_month") and other.get("arrears_end_month")):
                continue
            s2 = month_index(other["arrears_start_month"])
            e2 = month_index(other["arrears_end_month"])
            if max(s1, s2) <= min(e1, e2):
                raise ApiError("ERR_DUPLICATE_BENEFIT", 409, "Arrears window overlaps another award")
    # gate 6: prospective overlap (same tenant, 1-month buffer)
    if a.get("prospective_start_date") and a.get("prospective_end_date"):
        a_start = parse_date(a["prospective_start_date"])
        a_end = parse_date(a["prospective_end_date"])
        for other in applications.values():
            if other["id"] == a["id"]:
                continue
            if other["tenant_id"] != a["tenant_id"]:
                continue
            if other["status"] not in ("APPROVED", "DISBURSED"):
                continue
            if not (other.get("prospective_start_date") and other.get("prospective_end_date")):
                continue
            b_start = parse_date(other["prospective_start_date"])
            b_end = parse_date(other["prospective_end_date"])
            if a_start <= add_one_month(b_end) and b_start <= add_one_month(a_end):
                raise ApiError("ERR_PROSPECTIVE_OVERLAP", 409,
                               "Prospective window overlaps or abuts another award")

    # compute award
    arrears_owed = compute_arrears_owed(a)
    arrears_covered_months = a["arrears_covered_months"]
    monthly_award = min(a["monthly_rent_cents"], program["per_month_max_cents"])
    arrears_award = min(arrears_owed, arrears_covered_months * monthly_award)

    months_remaining = program["months_cap"] - tenant_months_used(tenant["id"])
    psd = a.get("prospective_start_date")
    ped = a.get("prospective_end_date")
    if psd and ped:
        month_amounts = prospective_month_amounts(psd, ped, monthly_award)
        calmonths = len(month_amounts)
    else:
        month_amounts = []
        calmonths = 0
    grantable = min(a["requested_prospective_months"],
                    max(0, months_remaining - arrears_covered_months),
                    calmonths)
    prospective_award = sum(month_amounts[:grantable])

    total_award = arrears_award + prospective_award
    months_awarded = arrears_covered_months + grantable

    # gate 7: months cap
    if tenant_months_used(tenant["id"]) + months_awarded > program["months_cap"]:
        raise ApiError("ERR_MONTHS_CAP_EXCEEDED", 422, "Award would exceed the months cap")
    # gate 8: funding
    if program_remaining(program) < total_award:
        raise ApiError("ERR_FUNDING_EXHAUSTED", 402, "Insufficient program funds for the award")

    # pin
    a["countable_monthly_income_cents"] = countable
    a["ami_pct"] = ami_pct
    a["income_eligible"] = income_eligible
    a["arrears_owed_cents"] = arrears_owed
    a["arrears_award_cents"] = arrears_award
    a["prospective_award_cents"] = prospective_award
    a["total_award_cents"] = total_award
    a["months_awarded"] = months_awarded
    a["approved_by_cw_id"] = uid
    if body.get("decision_reason") is not None:
        a["decision_reason"] = body.get("decision_reason")
    a["status"] = "APPROVED"
    touch(a)
    return ok(serialize_application(a))


@app.route("/applications/<aid>/deny", methods=["POST"])
def deny_application(aid):
    authenticate({"CaseWorker"})
    a = get_or_404(applications, aid, "ERR_APPLICATION_NOT_FOUND")
    if a["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Application is not under review")
    body = get_body()
    if body.get("decision_reason") is not None:
        a["decision_reason"] = body.get("decision_reason")
    a["status"] = "DENIED"
    touch(a)
    return ok(serialize_application(a))


# =====================================================================
# IncomeSource endpoints
# =====================================================================
@app.route("/applications/<aid>/income-sources", methods=["POST"])
def add_income_source(aid):
    uid, role = authenticate({"Tenant"})
    a = get_or_404(applications, aid, "ERR_APPLICATION_NOT_FOUND")
    check_owner_tenant(uid, a["tenant_id"])
    body = get_body()
    source_type = body.get("source_type")
    if source_type not in SOURCE_TYPES:
        bad("source_type is invalid")
    monthly_amount_cents = req_int(body, "monthly_amount_cents", minimum=0)
    i = base_entity()
    i.update({
        "application_id": a["id"], "source_type": source_type,
        "monthly_amount_cents": monthly_amount_cents,
        "countable": source_type in COUNTABLE_TYPES,
    })
    income_sources[i["id"]] = i
    return ok(serialize_income_source(i), 201)


@app.route("/applications/<aid>/income-sources", methods=["GET"])
def list_income_sources(aid):
    authenticate({"ProgramAdmin", "CaseWorker", "Tenant"})
    a = get_or_404(applications, aid, "ERR_APPLICATION_NOT_FOUND")
    items = [i for i in income_sources.values() if i["application_id"] == a["id"]]
    page, limit, offset, total = paginate_and_respond(items)
    return ok_list([serialize_income_source(i) for i in page], limit, offset, total)


@app.route("/income-sources/<iid>", methods=["GET"])
def get_income_source(iid):
    authenticate({"ProgramAdmin", "CaseWorker", "Tenant"})
    i = get_or_404(income_sources, iid, "ERR_APPLICATION_NOT_FOUND")
    return ok(serialize_income_source(i))


# =====================================================================
# RentLedger / LedgerLine endpoints
# =====================================================================
@app.route("/applications/<aid>/ledger", methods=["POST"])
def create_ledger(aid):
    uid, role = authenticate({"Landlord"})
    a = get_or_404(applications, aid, "ERR_APPLICATION_NOT_FOUND")
    check_owner_landlord(uid, a["landlord_id"])
    if ledger_for_app(a["id"]) is not None:
        raise ApiError("ERR_LEDGER_ALREADY_EXISTS", 409, "A ledger already exists for this application")
    body = get_body()
    lines = body.get("lines")
    if lines is None or not isinstance(lines, list):
        bad("lines must be an array")
    # validate lines
    parsed = []
    for ln in lines:
        if not isinstance(ln, dict):
            bad("each ledger line must be an object")
        month = ln.get("month")
        if not valid_month(month):
            bad("ledger line month must be YYYY-MM")
        line_type = ln.get("line_type")
        if line_type not in LINE_TYPES:
            bad("ledger line line_type is invalid")
        charge_cents = ln.get("charge_cents", 0)
        if charge_cents is None:
            charge_cents = 0
        if not is_int(charge_cents) or charge_cents < 0:
            bad("charge_cents must be a non-negative integer")
        payment_cents = ln.get("payment_cents", 0)
        if payment_cents is None:
            payment_cents = 0
        if not is_int(payment_cents) or payment_cents < 0:
            bad("payment_cents must be a non-negative integer")
        parsed.append((month, line_type, charge_cents, payment_cents))

    lg = base_entity()
    lg.update({"application_id": a["id"], "status": "SUBMITTED", "verified_by_id": None})
    ledgers[lg["id"]] = lg
    for (month, line_type, charge_cents, payment_cents) in parsed:
        ll = base_entity()
        ll.update({"ledger_id": lg["id"], "month": month, "line_type": line_type,
                   "charge_cents": charge_cents, "payment_cents": payment_cents})
        ledger_lines[ll["id"]] = ll
    return ok(serialize_ledger(lg), 201)


@app.route("/applications/<aid>/ledger", methods=["GET"])
def get_ledger(aid):
    authenticate({"ProgramAdmin", "CaseWorker", "Landlord", "Tenant"})
    a = get_or_404(applications, aid, "ERR_APPLICATION_NOT_FOUND")
    lg = ledger_for_app(a["id"])
    items = [lg] if lg is not None else []
    page, limit, offset, total = paginate_and_respond(items)
    return ok_list([serialize_ledger(l) for l in page], limit, offset, total)


@app.route("/applications/<aid>/ledger/verify", methods=["POST"])
def verify_ledger(aid):
    uid, role = authenticate({"ProgramAdmin"})
    a = get_or_404(applications, aid, "ERR_APPLICATION_NOT_FOUND")
    lg = ledger_for_app(a["id"])
    if lg is None:
        raise ApiError("ERR_LEDGER_NOT_FOUND", 404, "Application has no rent ledger")
    if lg["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Ledger is not in a verifiable state")
    body = get_body()
    decision = body.get("decision")
    if decision not in VERIFY_DECISIONS:
        bad("decision must be one of VERIFIED, REJECTED")
    lg["status"] = decision
    lg["verified_by_id"] = uid
    touch(lg)
    return ok(serialize_ledger(lg))


@app.route("/ledger-lines/<llid>", methods=["GET"])
def get_ledger_line(llid):
    authenticate({"ProgramAdmin", "CaseWorker", "Landlord"})
    ll = get_or_404(ledger_lines, llid, "ERR_LEDGER_NOT_FOUND")
    return ok(serialize_ledger_line(ll))


@app.route("/ledger-lines", methods=["GET"])
def list_ledger_lines():
    authenticate({"ProgramAdmin", "CaseWorker", "Landlord"})
    ledger_id = request.args.get("ledger_id")
    items = [ll for ll in ledger_lines.values() if ledger_id is None or ll["ledger_id"] == ledger_id]
    page, limit, offset, total = paginate_and_respond(items)
    return ok_list([serialize_ledger_line(ll) for ll in page], limit, offset, total)


# =====================================================================
# Disbursement endpoints
# =====================================================================
@app.route("/applications/<aid>/disbursements", methods=["POST"])
def create_disbursement(aid):
    uid, role = authenticate({"CaseWorker"})
    a = get_or_404(applications, aid, "ERR_APPLICATION_NOT_FOUND")
    body = get_body()
    # state: application must be APPROVED
    if a["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Application is not approved")
    # fraud hold
    if active_fraud_hold(a["id"]):
        raise ApiError("ERR_FRAUD_HOLD", 409, "Application is under a fraud hold")
    program = programs[a["program_id"]]
    # amount/months for checks (defensive; final validation raises 400)
    amount = body.get("amount_cents")
    amount_ok = is_int(amount) and amount > 0
    months = body.get("months_covered")
    months_ok = is_int(months) and months >= 0
    amt_for_check = amount if amount_ok else 0
    mon_for_check = months if months_ok else 0
    # funding fit
    if program_remaining(program) < amt_for_check:
        raise ApiError("ERR_FUNDING_EXHAUSTED", 402, "Insufficient program funds")
    # segregation of duties
    if uid == a.get("approved_by_cw_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "Approver may not issue the disbursement")
    # award ceiling
    if app_reserved_amount(a["id"]) + amt_for_check > a["total_award_cents"]:
        raise ApiError("ERR_AWARD_EXCEEDED", 422, "Disbursement exceeds the pinned award")
    if app_reserved_months(a["id"]) + mon_for_check > a["months_awarded"]:
        raise ApiError("ERR_AWARD_EXCEEDED", 422, "Disbursement exceeds the awarded months")
    # optimistic concurrency
    expected = body.get("expected_application_version")
    if expected is not None:
        if not is_int(expected):
            bad("expected_application_version must be an integer")
        if expected != a["version"]:
            raise ApiError("ERR_STALE_APPLICATION_VERSION", 412, "Application version is stale")
    # structural validation (lowest priority)
    if not amount_ok:
        bad("amount_cents must be a positive integer")
    if not months_ok:
        bad("months_covered must be a non-negative integer")
    coverage_kind = body.get("coverage_kind")
    if coverage_kind not in COVERAGE_KINDS:
        bad("coverage_kind is invalid")
    if expected is None:
        bad("expected_application_version is required")

    d = base_entity()
    d.update({
        "application_id": a["id"], "amount_cents": amount, "months_covered": months,
        "coverage_kind": coverage_kind, "status": "PENDING",
        "issued_by_cw_id": uid, "payment_reference": None,
    })
    disbursements[d["id"]] = d
    touch(a)  # increments application version by one
    return ok(serialize_disbursement(d), 201)


@app.route("/applications/<aid>/disbursements", methods=["GET"])
def list_disbursements(aid):
    authenticate({"ProgramAdmin", "CaseWorker", "Landlord", "Tenant"})
    a = get_or_404(applications, aid, "ERR_APPLICATION_NOT_FOUND")
    items = [d for d in disbursements.values() if d["application_id"] == a["id"]]
    page, limit, offset, total = paginate_and_respond(items)
    return ok_list([serialize_disbursement(d) for d in page], limit, offset, total)


@app.route("/disbursements/<did>", methods=["GET"])
def get_disbursement(did):
    authenticate({"ProgramAdmin", "CaseWorker", "Landlord"})
    d = get_or_404(disbursements, did, "ERR_DISBURSEMENT_NOT_FOUND")
    return ok(serialize_disbursement(d))


@app.route("/disbursements/<did>/send", methods=["POST"])
def send_disbursement(did):
    authenticate({"CaseWorker"})
    d = get_or_404(disbursements, did, "ERR_DISBURSEMENT_NOT_FOUND")
    a = applications[d["application_id"]]
    if d["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Disbursement is not pending")
    if a["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Application is not approved")
    landlord = landlords[a["landlord_id"]]
    if landlord["w9_status"] != "VERIFIED":
        raise ApiError("ERR_W9_NOT_VERIFIED", 422, "Landlord W-9 is not verified")
    if active_fraud_hold(a["id"]):
        raise ApiError("ERR_FRAUD_HOLD", 409, "Application is under a fraud hold")
    body = get_body()
    if body.get("payment_reference") is not None:
        d["payment_reference"] = body.get("payment_reference")
    d["status"] = "SENT"
    touch(d)
    return ok(serialize_disbursement(d))


@app.route("/disbursements/<did>/clear", methods=["POST"])
def clear_disbursement(did):
    authenticate({"ProgramAdmin"})
    d = get_or_404(disbursements, did, "ERR_DISBURSEMENT_NOT_FOUND")
    a = applications[d["application_id"]]
    if d["status"] != "SENT":
        raise ApiError("ERR_INVALID_STATE", 409, "Disbursement is not sent")
    d["status"] = "CLEARED"
    touch(d)
    # bubble up
    if app_total_disbursed(a["id"]) >= a["total_award_cents"] and a["status"] == "APPROVED":
        a["status"] = "DISBURSED"
    touch(a)
    return ok(serialize_disbursement(d))


@app.route("/disbursements/<did>/fail", methods=["POST"])
def fail_disbursement(did):
    authenticate({"ProgramAdmin"})
    d = get_or_404(disbursements, did, "ERR_DISBURSEMENT_NOT_FOUND")
    if d["status"] != "SENT":
        raise ApiError("ERR_INVALID_STATE", 409, "Disbursement is not sent")
    d["status"] = "FAILED"  # releases funds & months reservation (computed)
    touch(d)
    return ok(serialize_disbursement(d))


@app.route("/disbursements/<did>/retry", methods=["POST"])
def retry_disbursement(did):
    authenticate({"CaseWorker"})
    d = get_or_404(disbursements, did, "ERR_DISBURSEMENT_NOT_FOUND")
    a = applications[d["application_id"]]
    program = programs[a["program_id"]]
    tenant = tenants[a["tenant_id"]]
    if d["status"] != "FAILED":
        raise ApiError("ERR_INVALID_STATE", 409, "Disbursement is not failed")
    if active_fraud_hold(a["id"]):
        raise ApiError("ERR_FRAUD_HOLD", 409, "Application is under a fraud hold")
    if tenant_months_used(tenant["id"]) + d["months_covered"] > program["months_cap"]:
        raise ApiError("ERR_MONTHS_CAP_EXCEEDED", 422, "Retry would exceed the months cap")
    if program_remaining(program) < d["amount_cents"]:
        raise ApiError("ERR_FUNDING_EXHAUSTED", 402, "Insufficient program funds to re-reserve")
    d["status"] = "PENDING"  # re-reserves funds & months (computed)
    touch(d)
    return ok(serialize_disbursement(d))


# =====================================================================
# Recertification endpoints
# =====================================================================
@app.route("/applications/<aid>/recertifications", methods=["POST"])
def create_recert(aid):
    authenticate({"CaseWorker"})
    a = get_or_404(applications, aid, "ERR_APPLICATION_NOT_FOUND")
    body = get_body()
    requested = req_int(body, "requested_additional_months", minimum=1)
    nps = body.get("new_prospective_start_date")
    npe = body.get("new_prospective_end_date")
    if nps is not None and not valid_date(nps):
        bad("new_prospective_start_date must be YYYY-MM-DD")
    if npe is not None and not valid_date(npe):
        bad("new_prospective_end_date must be YYYY-MM-DD")
    r = base_entity()
    r.update({
        "application_id": a["id"], "requested_additional_months": requested,
        "new_prospective_start_date": nps, "new_prospective_end_date": npe,
        "status": "PENDING", "decision_reason": None,
    })
    recertifications[r["id"]] = r
    return ok(serialize_recert(r), 201)


@app.route("/applications/<aid>/recertifications", methods=["GET"])
def list_recerts(aid):
    authenticate({"ProgramAdmin", "CaseWorker", "Tenant"})
    a = get_or_404(applications, aid, "ERR_APPLICATION_NOT_FOUND")
    items = [r for r in recertifications.values() if r["application_id"] == a["id"]]
    page, limit, offset, total = paginate_and_respond(items)
    return ok_list([serialize_recert(r) for r in page], limit, offset, total)


@app.route("/recertifications/<rid>/decide", methods=["POST"])
def decide_recert(rid):
    uid, role = authenticate({"CaseWorker"})
    r = get_or_404(recertifications, rid, "ERR_RECERT_NOT_FOUND")
    if r["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Recertification is not pending")
    body = get_body()
    decision = body.get("decision")
    if decision not in RECERT_DECISIONS:
        bad("decision must be one of APPROVE, DENY")
    a = applications[r["application_id"]]
    program = programs[a["program_id"]]
    tenant = tenants[a["tenant_id"]]
    if decision == "DENY":
        if body.get("decision_reason") is not None:
            r["decision_reason"] = body.get("decision_reason")
        r["status"] = "DENIED"
        touch(r)
        return ok(serialize_recert(r))
    # APPROVE
    if a["status"] != "DISBURSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Application is not disbursed")
    _, income_eligible, _ = compute_income(a)
    if not income_eligible:
        raise ApiError("ERR_INCOME_INELIGIBLE", 422, "Household is no longer income-eligible")
    additional = r["requested_additional_months"]
    if tenant_months_used(tenant["id"]) + additional > program["months_cap"]:
        raise ApiError("ERR_MONTHS_CAP_EXCEEDED", 422, "Extension would exceed the months cap")
    monthly_award = min(a["monthly_rent_cents"], program["per_month_max_cents"])
    extension_cost = additional * monthly_award
    if program_remaining(program) < extension_cost:
        raise ApiError("ERR_FUNDING_EXHAUSTED", 402, "Insufficient program funds for the extension")
    # create child disbursement (reserves funds & months)
    d = base_entity()
    d.update({
        "application_id": a["id"], "amount_cents": extension_cost,
        "months_covered": additional, "coverage_kind": "PROSPECTIVE",
        "status": "PENDING", "issued_by_cw_id": uid, "payment_reference": None,
    })
    disbursements[d["id"]] = d
    if body.get("decision_reason") is not None:
        r["decision_reason"] = body.get("decision_reason")
    r["status"] = "APPROVED"
    touch(r)
    return ok(serialize_recert(r))


# =====================================================================
# RecaptureCase endpoints
# =====================================================================
@app.route("/recapture-cases", methods=["POST"])
def create_recapture():
    authenticate({"FraudInvestigator"})
    body = get_body()
    application_id = body.get("application_id")
    disbursement_id = body.get("disbursement_id")
    if application_id is not None:
        get_or_404(applications, application_id, "ERR_APPLICATION_NOT_FOUND")
    if disbursement_id is not None:
        get_or_404(disbursements, disbursement_id, "ERR_DISBURSEMENT_NOT_FOUND")
    application_id = req_str(body, "application_id")
    disbursement_id = req_str(body, "disbursement_id")
    reason = body.get("reason")
    if reason not in RECAP_REASONS:
        bad("reason is invalid")
    c = base_entity()
    c.update({
        "application_id": application_id, "disbursement_id": disbursement_id,
        "reason": reason, "status": "OPEN", "recovered_amount_cents": 0,
    })
    recapture_cases[c["id"]] = c
    return ok(serialize_recapture(c), 201)


@app.route("/recapture-cases/<cid>", methods=["GET"])
def get_recapture(cid):
    authenticate({"ProgramAdmin", "CaseWorker", "FraudInvestigator"})
    c = get_or_404(recapture_cases, cid, "ERR_RECAPTURE_NOT_FOUND")
    return ok(serialize_recapture(c))


@app.route("/recapture-cases", methods=["GET"])
def list_recaptures():
    authenticate({"ProgramAdmin", "CaseWorker", "FraudInvestigator"})
    args = request.args
    items = list(recapture_cases.values())
    for key in ("application_id", "disbursement_id"):
        val = args.get(key)
        if val is not None:
            items = [c for c in items if c[key] == val]
    page, limit, offset, total = paginate_and_respond(items)
    return ok_list([serialize_recapture(c) for c in page], limit, offset, total)


@app.route("/recapture-cases/<cid>/substantiate", methods=["POST"])
def substantiate_recapture(cid):
    authenticate({"FraudInvestigator"})
    c = get_or_404(recapture_cases, cid, "ERR_RECAPTURE_NOT_FOUND")
    if c["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Case is not open")
    c["status"] = "SUBSTANTIATED"
    touch(c)
    return ok(serialize_recapture(c))


@app.route("/recapture-cases/<cid>/dismiss", methods=["POST"])
def dismiss_recapture(cid):
    authenticate({"FraudInvestigator"})
    c = get_or_404(recapture_cases, cid, "ERR_RECAPTURE_NOT_FOUND")
    if c["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Case is not open")
    c["status"] = "DISMISSED"
    touch(c)
    return ok(serialize_recapture(c))


@app.route("/recapture-cases/<cid>/recover", methods=["POST"])
def recover_recapture(cid):
    authenticate({"FraudInvestigator"})
    c = get_or_404(recapture_cases, cid, "ERR_RECAPTURE_NOT_FOUND")
    if c["status"] != "SUBSTANTIATED":
        raise ApiError("ERR_INVALID_STATE", 409, "Case is not substantiated")
    d = disbursements[c["disbursement_id"]]
    if d["status"] != "CLEARED":
        raise ApiError("ERR_INVALID_STATE", 409, "Targeted disbursement is not cleared")
    a = applications[d["application_id"]]
    program = programs[a["program_id"]]
    tenant = tenants[a["tenant_id"]]
    # cascade
    c["recovered_amount_cents"] = d["amount_cents"]
    d["status"] = "RECAPTURED"  # releases funds & months (computed), total_disbursed drops
    a["status"] = "CLOSED"
    c["status"] = "RECOVERED"
    # each touched entity independently refreshes updated_at and bumps version
    touch(d)
    touch(a)
    touch(program)
    touch(tenant)
    touch(c)
    return ok(serialize_recapture(c))


# =====================================================================
# Clock
# =====================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate({"ProgramAdmin"})
    global CLOCK
    body = get_body()
    to_iso = body.get("to_iso8601")
    if not isinstance(to_iso, str) or not to_iso:
        bad("to_iso8601 is required")
    s = to_iso.strip()
    if s.endswith("Z"):
        s = s[:-1]
    try:
        CLOCK = datetime.fromisoformat(s)
        if CLOCK.tzinfo is not None:
            CLOCK = CLOCK.replace(tzinfo=None)
    except ValueError:
        bad("to_iso8601 is not a valid ISO 8601 timestamp")
    return ok({})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
