"""
Economic-Development Incentive & Abatement API.

Single-file Flask implementation. In-memory storage only (no persistence).
All state lives in module-level dicts and is wiped on every process (re)start.
Timestamps use a logical clock (default 2026-05-01T00:00:00Z), never wall-clock.
"""

import os
import random
import string
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
STATE = {"clock": DEFAULT_CLOCK, "seq": 0}


def next_seq():
    STATE["seq"] += 1
    return STATE["seq"]


def render_ts(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


def parse_dt(s):
    if s is None:
        return None
    t = str(s).strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now_ts():
    return render_ts(STATE["clock"])


# ---------------------------------------------------------------------------
# Decimal / rounding helpers
# ---------------------------------------------------------------------------
def dec(x):
    return Decimal(str(x))


def rhu_cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu_2dp(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# In-memory stores
# ---------------------------------------------------------------------------
programs = {}
parcels = {}
applications = {}
reviews = {}
agreements = {}
covenants = {}
reports = {}
disbursements = {}
assessments = {}
disclosures = {}


# ---------------------------------------------------------------------------
# Errors + response envelope
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def rand_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def meta_base():
    return {"api_request_id": rand_req_id(), "api_request_timestamp": now_ts()}


def ok(data, status=200, page_meta=None):
    m = meta_base()
    if page_meta:
        m.update(page_meta)
    rtype = "array" if isinstance(data, list) else "object"
    return jsonify({"meta": m, "response_type": rtype, "data": data}), status


def err_response(error_id, http_status, message):
    m = meta_base()
    return (
        jsonify(
            {
                "meta": m,
                "response_type": "error",
                "data": {"error_id": error_id, "message": message},
            }
        ),
        http_status,
    )


@app.errorhandler(ApiError)
def handle_api_error(e):
    return err_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return err_response("ERR_NOT_FOUND", 404, "resource not found")


@app.errorhandler(405)
def handle_405(e):
    return err_response("ERR_METHOD_NOT_ALLOWED", 405, "method not allowed")


@app.errorhandler(Exception)
def handle_uncaught(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return err_response("ERR_INTERNAL", 500, str(e))


@app.after_request
def add_conn_close(resp):
    # Avoid keep-alive flakiness under per-test-server isolation.
    resp.headers["Connection"] = "close"
    return resp


# ---------------------------------------------------------------------------
# Auth / body helpers
# ---------------------------------------------------------------------------
def auth(allowed_roles):
    uid = request.headers.get("X-User-ID", "")
    role = request.headers.get("X-User-Role", "")
    if not uid or not role:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "missing X-User-ID/X-User-Role")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted")
    return uid, role


def get_body():
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


def req_str(b, name, optional=False, default=None, allow_empty=False):
    if name not in b or b[name] is None:
        if optional:
            return default
        raise ApiError("ERR_VALIDATION", 422, f"{name} is required")
    v = b[name]
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 422, f"{name} must be a string")
    if not allow_empty and v == "":
        raise ApiError("ERR_VALIDATION", 422, f"{name} must be non-empty")
    return v


def req_int(b, name, optional=False, default=None, allow_negative=False):
    if name not in b or b[name] is None:
        if optional:
            return default
        raise ApiError("ERR_VALIDATION", 422, f"{name} is required")
    v = b[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 422, f"{name} must be an integer")
    if not allow_negative and v < 0:
        raise ApiError("ERR_VALIDATION", 422, f"{name} must be non-negative")
    return v


def req_num(b, name, optional=False, default=None, allow_negative=False):
    if name not in b or b[name] is None:
        if optional:
            return default
        raise ApiError("ERR_VALIDATION", 422, f"{name} is required")
    v = b[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", 422, f"{name} must be a number")
    if not allow_negative and v < 0:
        raise ApiError("ERR_VALIDATION", 422, f"{name} must be non-negative")
    return v


def req_bool(b, name, optional=True, default=False):
    if name not in b or b[name] is None:
        if optional:
            return default
        raise ApiError("ERR_VALIDATION", 422, f"{name} is required")
    v = b[name]
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 422, f"{name} must be a boolean")
    return v


def req_enum(b, name, choices, optional=False, default=None):
    if name not in b or b[name] is None:
        if optional:
            return default
        raise ApiError("ERR_VALIDATION", 422, f"{name} is required")
    v = b[name]
    if v not in choices:
        raise ApiError("ERR_VALIDATION", 422, f"{name} must be one of {sorted(choices)}")
    return v


# ---------------------------------------------------------------------------
# Common record helpers
# ---------------------------------------------------------------------------
def new_common(with_version=True):
    ts = now_ts()
    rec = {"id": str(uuid.uuid4()), "created_at": ts, "_seq": next_seq()}
    if with_version:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    rec["updated_at"] = now_ts()
    if "version" in rec:
        rec["version"] += 1


def strip(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Lookups (raise the correct 404)
# ---------------------------------------------------------------------------
def get_or_404(store, rid, error_id):
    rec = store.get(rid)
    if rec is None:
        raise ApiError(error_id, 404, f"{rid} not found")
    return rec


# ---------------------------------------------------------------------------
# Pagination + filtering
# ---------------------------------------------------------------------------
def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if args.get("limit") is not None:
        try:
            limit = int(args.get("limit"))
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", 422, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", 422, "limit must be between 1 and 100")
    if args.get("offset") is not None:
        try:
            offset = int(args.get("offset"))
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", 422, "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", 422, "offset must be >= 0")
    return limit, offset


def list_response(records, serializer, filters):
    items = list(records)
    for field, value in filters.items():
        if value is not None:
            items = [x for x in items if str(x.get(field)) == str(value)]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    data = [serializer(x) for x in page]
    page_meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return ok(data, 200, page_meta)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def compute_committed(program_id):
    total = 0
    for a in agreements.values():
        if a["program_id"] == program_id and a["status"] in ("EXECUTED", "ACTIVE", "DEFAULTED"):
            total += a["max_incentive_cents"] - a["gross_disbursed_cents"]
    return total


def compute_disbursed(program_id):
    total = 0
    for d in disbursements.values():
        if d["status"] != "PAID":
            continue
        a = agreements.get(d["agreement_id"])
        if a and a["program_id"] == program_id:
            total += d["disbursed_amount_cents"]
    return total


def serialize_program(p):
    out = strip(p)
    committed = compute_committed(p["id"])
    disbursed = compute_disbursed(p["id"])
    out["committed_cents"] = committed
    out["disbursed_cents"] = disbursed
    out["available_budget_cents"] = p["total_budget_cents"] - committed - disbursed
    return out


def serialize(rec):
    return strip(rec)


# ---------------------------------------------------------------------------
# Ownership helpers
# ---------------------------------------------------------------------------
def application_owner(app_rec):
    return app_rec.get("applicant_user_id")


def agreement_owner(agr):
    ap = applications.get(agr.get("application_id"))
    return ap.get("applicant_user_id") if ap else None


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def calc_eligibility_score(app_rec, program):
    jobs = app_rec["proposed_jobs"]
    inv = app_rec["proposed_investment_cents"]
    min_jobs = program["min_jobs_required"]
    min_inv = program["min_investment_cents"]

    if min_jobs > 0:
        jobs_comp = min(Decimal(30), Decimal(30) * dec(jobs) / dec(min_jobs))
    else:
        jobs_comp = Decimal(30) if jobs > 0 else Decimal(0)

    if min_inv > 0:
        inv_comp = min(Decimal(30), Decimal(30) * dec(inv) / dec(min_inv))
    else:
        inv_comp = Decimal(30) if inv > 0 else Decimal(0)

    but_for_bonus = Decimal(25) if app_rec.get("but_for_attested") else Decimal(0)
    distress_bonus = Decimal(15) if app_rec.get("distress_zone") else Decimal(0)

    score = rhu_2dp(jobs_comp + inv_comp + but_for_bonus + distress_bonus)
    return float(score)


def calc_award_cap(program, parcel, term_years, awarded_jobs):
    itype = program["incentive_type"]
    if itype == "GRANT":
        return awarded_jobs * program["grant_per_job_cents"]
    if itype == "ABATEMENT":
        per_year = rhu_cents(dec(parcel["current_assessed_value_cents"]) * dec(program["abatement_rate_pct"]) / Decimal(100))
        return per_year * term_years
    # TIF
    increment = max(0, parcel["current_assessed_value_cents"] - parcel["base_assessed_value_cents"])
    per_year = rhu_cents(dec(increment) * dec(program["tif_capture_pct"]) / Decimal(100))
    return per_year * term_years


def calc_period_disbursement(agr, report):
    term = agr["term_years"]
    base = rhu_cents(dec(agr["max_incentive_cents"]) / dec(term)) if term > 0 else 0
    if agr["incentive_type"] == "GRANT":
        awarded_jobs = agr["awarded_jobs"]
        if awarded_jobs > 0:
            ratio = min(Decimal(1), dec(report["actual_jobs"]) / dec(awarded_jobs))
        else:
            ratio = Decimal(1)
        gross = base
        disbursed = rhu_cents(dec(base) * ratio)
    else:
        gross = base
        disbursed = base
    return gross, disbursed


def calc_attainment_pct(cov, report):
    if cov["covenant_type"] == "JOBS":
        actual = report["actual_jobs"]
    else:
        actual = report["actual_investment_cents"]
    target = cov["target_value"]
    if target > 0:
        return rhu_2dp(dec(actual) / dec(target) * Decimal(100))
    return Decimal(0)


def calc_recapture(agr, severity, breached_count, total_count):
    net = agr["net_disbursed_cents"]
    if severity == "MATERIAL":
        return net
    if total_count > 0:
        return rhu_cents(dec(net) * dec(breached_count) / dec(total_count))
    return 0


# ---------------------------------------------------------------------------
# Cascade helpers
# ---------------------------------------------------------------------------
def agreement_covenants(agreement_id):
    return [c for c in covenants.values() if c["agreement_id"] == agreement_id]


def maybe_complete_agreement(agr):
    covs = agreement_covenants(agr["id"])
    if agr["status"] == "ACTIVE" and len(covs) >= 1 and all(c["status"] in ("MET", "WAIVED") for c in covs):
        agr["status"] = "COMPLETED"
        touch(agr)


# ===========================================================================
# ROUTES
# ===========================================================================

# ---- Logical clock --------------------------------------------------------
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth({"ProgramDirector", "ComplianceOfficer"})
    b = get_body()
    iso = req_str(b, "to_iso8601")
    try:
        dt = parse_dt(iso)
    except Exception:
        raise ApiError("ERR_VALIDATION", 422, "to_iso8601 is not a valid ISO-8601 timestamp")
    if dt is None:
        raise ApiError("ERR_VALIDATION", 422, "to_iso8601 is required")
    STATE["clock"] = dt
    return ok({"current_utc": render_ts(dt)}, 200)


# ---- IncentiveProgram -----------------------------------------------------
@app.route("/incentive-programs", methods=["POST"])
def create_program():
    auth({"ProgramDirector"})
    b = get_body()
    rec = new_common()
    rec["program_name"] = req_str(b, "program_name")
    rec["incentive_type"] = req_enum(b, "incentive_type", {"TIF", "ABATEMENT", "GRANT"})
    rec["total_budget_cents"] = req_int(b, "total_budget_cents")
    rec["min_jobs_required"] = req_int(b, "min_jobs_required")
    rec["min_investment_cents"] = req_int(b, "min_investment_cents")
    rec["max_term_years"] = req_int(b, "max_term_years")
    rec["abatement_rate_pct"] = req_num(b, "abatement_rate_pct")
    rec["grant_per_job_cents"] = req_int(b, "grant_per_job_cents")
    rec["tif_capture_pct"] = req_num(b, "tif_capture_pct")
    rec["but_for_pass_threshold"] = req_num(b, "but_for_pass_threshold", optional=True, default=60)
    rec["disclosure_threshold_cents"] = req_int(b, "disclosure_threshold_cents", optional=True, default=0)
    programs[rec["id"]] = rec
    return ok(serialize_program(rec), 201)


@app.route("/incentive-programs", methods=["GET"])
def list_programs():
    auth({"Applicant", "ProgramAnalyst", "ProgramDirector", "ComplianceOfficer", "PublicViewer"})
    filters = {"incentive_type": request.args.get("incentive_type")}
    return list_response(programs.values(), serialize_program, filters)


@app.route("/incentive-programs/<program_id>", methods=["GET"])
def get_program(program_id):
    auth({"Applicant", "ProgramAnalyst", "ProgramDirector", "ComplianceOfficer", "PublicViewer"})
    p = get_or_404(programs, program_id, "ERR_PROGRAM_NOT_FOUND")
    return ok(serialize_program(p), 200)


# ---- Parcel ---------------------------------------------------------------
@app.route("/parcels", methods=["POST"])
def create_parcel():
    auth({"ProgramDirector"})
    b = get_body()
    rec = new_common()
    rec["parcel_identifier"] = req_str(b, "parcel_identifier")
    rec["jurisdiction"] = req_str(b, "jurisdiction")
    rec["base_assessed_value_cents"] = req_int(b, "base_assessed_value_cents")
    rec["current_assessed_value_cents"] = req_int(b, "current_assessed_value_cents")
    parcels[rec["id"]] = rec
    return ok(serialize(rec), 201)


@app.route("/parcels", methods=["GET"])
def list_parcels():
    auth({"ProgramAnalyst", "ProgramDirector", "ComplianceOfficer"})
    return list_response(parcels.values(), serialize, {})


@app.route("/parcels/<parcel_id>", methods=["GET"])
def get_parcel(parcel_id):
    auth({"ProgramAnalyst", "ProgramDirector", "ComplianceOfficer"})
    p = get_or_404(parcels, parcel_id, "ERR_PARCEL_NOT_FOUND")
    return ok(serialize(p), 200)


# ---- Application ----------------------------------------------------------
@app.route("/applications", methods=["POST"])
def create_application():
    auth({"Applicant"})
    b = get_body()
    program_id = req_str(b, "program_id")
    applicant_user_id = req_str(b, "applicant_user_id")
    applicant_name = req_str(b, "applicant_name")
    proposed_jobs = req_int(b, "proposed_jobs")
    proposed_investment_cents = req_int(b, "proposed_investment_cents")
    but_for_attested = req_bool(b, "but_for_attested", default=False)
    distress_zone = req_bool(b, "distress_zone", default=False)
    get_or_404(programs, program_id, "ERR_PROGRAM_NOT_FOUND")

    rec = new_common()
    rec["program_id"] = program_id
    rec["applicant_user_id"] = applicant_user_id
    rec["applicant_name"] = applicant_name
    rec["proposed_jobs"] = proposed_jobs
    rec["proposed_investment_cents"] = proposed_investment_cents
    rec["but_for_attested"] = but_for_attested
    rec["distress_zone"] = distress_zone
    rec["but_for_eligibility_score"] = None
    rec["status"] = "DRAFT"
    applications[rec["id"]] = rec
    return ok(serialize(rec), 201)


@app.route("/applications", methods=["GET"])
def list_applications():
    auth({"Applicant", "ProgramAnalyst", "ProgramDirector", "ComplianceOfficer"})
    filters = {
        "program_id": request.args.get("program_id"),
        "applicant_user_id": request.args.get("applicant_user_id"),
        "status": request.args.get("status"),
    }
    return list_response(applications.values(), serialize, filters)


@app.route("/applications/<application_id>", methods=["GET"])
def get_application(application_id):
    auth({"Applicant", "ProgramAnalyst", "ProgramDirector", "ComplianceOfficer"})
    a = get_or_404(applications, application_id, "ERR_APPLICATION_NOT_FOUND")
    return ok(serialize(a), 200)


@app.route("/applications/<application_id>/submit", methods=["POST"])
def submit_application(application_id):
    uid, _ = auth({"Applicant"})
    a = get_or_404(applications, application_id, "ERR_APPLICATION_NOT_FOUND")
    if uid != a["applicant_user_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "only the owning applicant may submit")
    if a["status"] != "DRAFT":
        raise ApiError("ERR_APPLICATION_INVALID_STATE", 409, "application not in DRAFT")
    program = programs[a["program_id"]]
    a["but_for_eligibility_score"] = calc_eligibility_score(a, program)
    a["status"] = "SUBMITTED"
    touch(a)
    return ok(serialize(a), 200)


@app.route("/applications/<application_id>/start-review", methods=["POST"])
def start_review(application_id):
    uid, _ = auth({"ProgramAnalyst"})
    a = get_or_404(applications, application_id, "ERR_APPLICATION_NOT_FOUND")
    b = get_body()
    notes = req_str(b, "notes", optional=True, default="", allow_empty=True)
    if a["status"] != "SUBMITTED":
        raise ApiError("ERR_APPLICATION_INVALID_STATE", 409, "application not in SUBMITTED")
    program = programs[a["program_id"]]
    score = a["but_for_eligibility_score"]
    threshold = program["but_for_pass_threshold"]
    finding = "PASS" if Decimal(str(score)) >= Decimal(str(threshold)) else "FAIL"

    rec = new_common(with_version=False)
    rec["application_id"] = application_id
    rec["reviewer_user_id"] = uid
    rec["eligibility_score"] = score
    rec["finding"] = finding
    rec["notes"] = notes
    reviews[rec["id"]] = rec

    a["status"] = "UNDER_REVIEW"
    touch(a)
    return ok(serialize(rec), 201)


def latest_review_for(application_id):
    revs = [r for r in reviews.values() if r["application_id"] == application_id]
    if not revs:
        return None
    revs.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return revs[-1]


@app.route("/applications/<application_id>/approve", methods=["POST"])
def approve_application(application_id):
    uid, _ = auth({"ProgramDirector"})
    a = get_or_404(applications, application_id, "ERR_APPLICATION_NOT_FOUND")
    if a["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_APPLICATION_INVALID_STATE", 409, "application not in UNDER_REVIEW")
    review = latest_review_for(application_id)
    # Four-eyes SoD (priority 7) is evaluated before the referential PASS check (priority 8).
    if review is not None and uid == review["reviewer_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403, "approver must differ from reviewer")
    if review is None or review["finding"] != "PASS":
        raise ApiError("ERR_ELIGIBILITY_NOT_PASSED", 409, "latest eligibility review is not PASS")
    a["status"] = "APPROVED"
    touch(a)
    return ok(serialize(a), 200)


@app.route("/applications/<application_id>/deny", methods=["POST"])
def deny_application(application_id):
    auth({"ProgramDirector"})
    a = get_or_404(applications, application_id, "ERR_APPLICATION_NOT_FOUND")
    b = get_body()
    req_str(b, "reason", optional=True, default="", allow_empty=True)
    if a["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_APPLICATION_INVALID_STATE", 409, "application not in UNDER_REVIEW")
    a["status"] = "DENIED"
    touch(a)
    return ok(serialize(a), 200)


# ---- EligibilityReview ----------------------------------------------------
@app.route("/eligibility-reviews", methods=["GET"])
def list_reviews():
    auth({"ProgramAnalyst", "ProgramDirector", "ComplianceOfficer"})
    filters = {"application_id": request.args.get("application_id")}
    return list_response(reviews.values(), serialize, filters)


@app.route("/eligibility-reviews/<review_id>", methods=["GET"])
def get_review(review_id):
    auth({"ProgramAnalyst", "ProgramDirector", "ComplianceOfficer"})
    r = get_or_404(reviews, review_id, "ERR_ELIGIBILITY_REVIEW_NOT_FOUND")
    return ok(serialize(r), 200)


# ---- Agreement ------------------------------------------------------------
@app.route("/agreements", methods=["POST"])
def create_agreement():
    auth({"ProgramDirector"})
    b = get_body()
    application_id = req_str(b, "application_id")
    parcel_id = req_str(b, "parcel_id")
    term_years = req_int(b, "term_years")
    awarded_jobs = req_int(b, "awarded_jobs")
    awarded_investment_cents = req_int(b, "awarded_investment_cents")
    if term_years < 1:
        raise ApiError("ERR_VALIDATION", 422, "term_years must be >= 1")

    a = get_or_404(applications, application_id, "ERR_APPLICATION_NOT_FOUND")
    parcel = get_or_404(parcels, parcel_id, "ERR_PARCEL_NOT_FOUND")
    program = programs[a["program_id"]]

    if term_years > program["max_term_years"]:
        raise ApiError("ERR_VALIDATION", 422, "term_years exceeds program.max_term_years")
    if a["status"] != "APPROVED":
        raise ApiError("ERR_APPLICATION_NOT_APPROVED", 409, "source application is not APPROVED")

    cap = calc_award_cap(program, parcel, term_years, awarded_jobs)

    committed = compute_committed(program["id"])
    disbursed = compute_disbursed(program["id"])
    available = program["total_budget_cents"] - committed - disbursed
    if available < cap:
        raise ApiError("ERR_PROGRAM_BUDGET_EXCEEDED", 402, "award cap exceeds available budget")

    rec = new_common()
    rec["application_id"] = application_id
    rec["program_id"] = program["id"]
    rec["parcel_id"] = parcel_id
    rec["incentive_type"] = program["incentive_type"]
    rec["term_years"] = term_years
    rec["awarded_jobs"] = awarded_jobs
    rec["awarded_investment_cents"] = awarded_investment_cents
    rec["max_incentive_cents"] = cap
    rec["gross_disbursed_cents"] = 0
    rec["net_disbursed_cents"] = 0
    rec["clawed_back_cents"] = 0
    rec["effective_date"] = now_ts()
    rec["status"] = "EXECUTED"
    agreements[rec["id"]] = rec
    return ok(serialize(rec), 201)


@app.route("/agreements", methods=["GET"])
def list_agreements():
    auth({"Applicant", "ProgramAnalyst", "ProgramDirector", "ComplianceOfficer"})
    filters = {
        "program_id": request.args.get("program_id"),
        "application_id": request.args.get("application_id"),
        "parcel_id": request.args.get("parcel_id"),
        "status": request.args.get("status"),
    }
    return list_response(agreements.values(), serialize, filters)


@app.route("/agreements/<agreement_id>", methods=["GET"])
def get_agreement(agreement_id):
    auth({"Applicant", "ProgramAnalyst", "ProgramDirector", "ComplianceOfficer"})
    a = get_or_404(agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")
    return ok(serialize(a), 200)


@app.route("/agreements/<agreement_id>/activate", methods=["POST"])
def activate_agreement(agreement_id):
    auth({"ProgramDirector"})
    a = get_or_404(agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")
    if a["status"] != "EXECUTED":
        raise ApiError("ERR_AGREEMENT_INVALID_STATE", 409, "agreement not in EXECUTED")
    a["status"] = "ACTIVE"
    touch(a)
    return ok(serialize(a), 200)


@app.route("/agreements/<agreement_id>/declare-default", methods=["POST"])
def declare_default(agreement_id):
    auth({"ProgramDirector"})
    a = get_or_404(agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")
    b = get_body()
    severity = req_enum(b, "severity", {"PARTIAL", "MATERIAL"}, optional=True, default="PARTIAL")
    reason = req_str(b, "reason", optional=True, default="", allow_empty=True)
    if a["status"] != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_INVALID_STATE", 409, "agreement not in ACTIVE")

    covs = agreement_covenants(agreement_id)
    if not any(c["status"] not in ("MET", "WAIVED") for c in covs):
        raise ApiError("ERR_NO_BREACH_TO_DEFAULT", 409, "no covenant is breachable")

    # CASCADE-1 hop 1->2: every ACTIVE covenant -> BREACHED
    for c in covs:
        if c["status"] == "ACTIVE":
            c["status"] = "BREACHED"
            touch(c)

    breached_count = sum(1 for c in covs if c["status"] not in ("MET", "WAIVED"))
    total_count = len(covs)

    assessed = calc_recapture(a, severity, breached_count, total_count)
    rec = new_common()
    rec["agreement_id"] = agreement_id
    rec["trigger_reason"] = reason
    rec["severity"] = severity
    rec["breached_covenants_count"] = breached_count
    rec["total_covenants_count"] = total_count
    rec["assessed_amount_cents"] = assessed
    rec["status"] = "ASSESSED"
    assessments[rec["id"]] = rec

    a["status"] = "DEFAULTED"
    touch(a)
    return ok(serialize(a), 200)


# ---- Covenant -------------------------------------------------------------
@app.route("/agreements/<agreement_id>/covenants", methods=["POST"])
def create_covenant(agreement_id):
    auth({"ProgramDirector"})
    a = get_or_404(agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")
    b = get_body()
    covenant_type = req_enum(b, "covenant_type", {"JOBS", "INVESTMENT"})
    target_value = req_int(b, "target_value")
    start_raw = req_str(b, "measurement_start_date")
    end_raw = req_str(b, "measurement_end_date")
    cure_period_days = req_int(b, "cure_period_days", optional=True, default=0)
    try:
        start_dt = parse_dt(start_raw)
        end_dt = parse_dt(end_raw)
    except Exception:
        raise ApiError("ERR_VALIDATION", 422, "invalid measurement date")
    if end_dt < start_dt:
        raise ApiError("ERR_VALIDATION", 422, "measurement_end_date must be >= measurement_start_date")

    program = programs[a["program_id"]]
    if covenant_type == "JOBS":
        if target_value < program["min_jobs_required"]:
            raise ApiError("ERR_COVENANT_TARGET_BELOW_MINIMUM", 422, "target below program min jobs")
    else:
        if target_value < program["min_investment_cents"]:
            raise ApiError("ERR_COVENANT_TARGET_BELOW_MINIMUM", 422, "target below program min investment")

    # Interval-overlap (closed) vs same covenant_type on this agreement.
    for c in agreement_covenants(agreement_id):
        if c["covenant_type"] != covenant_type:
            continue
        c_start = parse_dt(c["measurement_start_date"])
        c_end = parse_dt(c["measurement_end_date"])
        if start_dt <= c_end and c_start <= end_dt:
            raise ApiError("ERR_COVENANT_WINDOW_OVERLAP", 409, "measurement window overlaps existing covenant")

    rec = new_common()
    rec["agreement_id"] = agreement_id
    rec["covenant_type"] = covenant_type
    rec["target_value"] = target_value
    rec["measurement_start_date"] = start_raw
    rec["measurement_end_date"] = end_raw
    rec["cure_period_days"] = cure_period_days
    rec["attainment_pct"] = 0
    rec["status"] = "ACTIVE"
    covenants[rec["id"]] = rec

    touch(a)  # covenant attachment advances agreement.version
    return ok(serialize(rec), 201)


@app.route("/covenants", methods=["GET"])
def list_covenants():
    auth({"Applicant", "ProgramAnalyst", "ProgramDirector", "ComplianceOfficer"})
    filters = {
        "agreement_id": request.args.get("agreement_id"),
        "covenant_type": request.args.get("covenant_type"),
        "status": request.args.get("status"),
    }
    return list_response(covenants.values(), serialize, filters)


@app.route("/covenants/<covenant_id>", methods=["GET"])
def get_covenant(covenant_id):
    auth({"Applicant", "ProgramAnalyst", "ProgramDirector", "ComplianceOfficer"})
    c = get_or_404(covenants, covenant_id, "ERR_COVENANT_NOT_FOUND")
    return ok(serialize(c), 200)


@app.route("/covenants/<covenant_id>/waive", methods=["POST"])
def waive_covenant(covenant_id):
    auth({"ProgramDirector"})
    c = get_or_404(covenants, covenant_id, "ERR_COVENANT_NOT_FOUND")
    b = get_body()
    req_str(b, "reason", optional=True, default="", allow_empty=True)
    if c["status"] not in ("ACTIVE", "BREACHED"):
        raise ApiError("ERR_COVENANT_INVALID_STATE", 409, "covenant not in ACTIVE/BREACHED")
    c["status"] = "WAIVED"
    touch(c)
    agr = agreements.get(c["agreement_id"])
    if agr:
        maybe_complete_agreement(agr)
    return ok(serialize(c), 200)


# ---- ComplianceReport -----------------------------------------------------
@app.route("/agreements/<agreement_id>/compliance-reports", methods=["POST"])
def create_report(agreement_id):
    uid, _ = auth({"Applicant"})
    a = get_or_404(agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")
    b = get_body()
    reporting_year = req_int(b, "reporting_year")
    start_raw = req_str(b, "period_start_date")
    end_raw = req_str(b, "period_end_date")
    actual_jobs = req_int(b, "actual_jobs")
    actual_investment_cents = req_int(b, "actual_investment_cents")
    attestation = req_bool(b, "attestation", default=False)
    try:
        start_dt = parse_dt(start_raw)
        end_dt = parse_dt(end_raw)
    except Exception:
        raise ApiError("ERR_VALIDATION", 422, "invalid period date")
    if end_dt <= start_dt:
        raise ApiError("ERR_VALIDATION", 422, "period_end_date must be strictly after period_start_date")

    rec = new_common()
    rec["agreement_id"] = agreement_id
    rec["reporting_year"] = reporting_year
    rec["period_start_date"] = start_raw
    rec["period_end_date"] = end_raw
    rec["actual_jobs"] = actual_jobs
    rec["actual_investment_cents"] = actual_investment_cents
    rec["attestation"] = attestation
    rec["certified_by"] = uid if attestation else None
    rec["status"] = "SUBMITTED"
    reports[rec["id"]] = rec
    return ok(serialize(rec), 201)


@app.route("/compliance-reports", methods=["GET"])
def list_reports():
    auth({"Applicant", "ProgramAnalyst", "ProgramDirector", "ComplianceOfficer"})
    filters = {
        "agreement_id": request.args.get("agreement_id"),
        "status": request.args.get("status"),
    }
    return list_response(reports.values(), serialize, filters)


@app.route("/compliance-reports/<report_id>", methods=["GET"])
def get_report(report_id):
    auth({"Applicant", "ProgramAnalyst", "ProgramDirector", "ComplianceOfficer"})
    r = get_or_404(reports, report_id, "ERR_COMPLIANCE_REPORT_NOT_FOUND")
    return ok(serialize(r), 200)


@app.route("/compliance-reports/<report_id>/accept", methods=["POST"])
def accept_report(report_id):
    auth({"ProgramAnalyst"})
    r = get_or_404(reports, report_id, "ERR_COMPLIANCE_REPORT_NOT_FOUND")
    if r["status"] != "SUBMITTED":
        raise ApiError("ERR_COMPLIANCE_REPORT_INVALID_STATE", 409, "report not in SUBMITTED")
    if not r["attestation"]:
        raise ApiError("ERR_REPORT_NOT_CERTIFIED", 422, "report attestation is not true")

    # half-open period overlap vs already-ACCEPTED reports on same agreement
    r_start = parse_dt(r["period_start_date"])
    r_end = parse_dt(r["period_end_date"])
    for other in reports.values():
        if other["id"] == r["id"] or other["agreement_id"] != r["agreement_id"]:
            continue
        if other["status"] != "ACCEPTED":
            continue
        o_start = parse_dt(other["period_start_date"])
        o_end = parse_dt(other["period_end_date"])
        if r_start < o_end and o_start < r_end:
            raise ApiError("ERR_REPORTING_PERIOD_OVERLAP", 409, "period overlaps an accepted report")

    r["status"] = "ACCEPTED"
    touch(r)

    # CASCADE-2: recompute covenants, transition, maybe complete agreement.
    agr = agreements.get(r["agreement_id"])
    if agr:
        clock = STATE["clock"]
        for c in agreement_covenants(agr["id"]):
            if c["status"] not in ("ACTIVE", "BREACHED"):
                continue
            attn = calc_attainment_pct(c, r)
            c["attainment_pct"] = float(attn)
            if c["status"] == "ACTIVE":
                c["status"] = "MET" if attn >= Decimal("100.00") else "BREACHED"
            elif c["status"] == "BREACHED":
                cure_deadline = parse_dt(c["measurement_end_date"]) + timedelta(days=c["cure_period_days"])
                if attn >= Decimal("100.00") and clock <= cure_deadline:
                    c["status"] = "MET"
            touch(c)
        maybe_complete_agreement(agr)

    return ok(serialize(r), 200)


@app.route("/compliance-reports/<report_id>/return", methods=["POST"])
def return_report(report_id):
    auth({"ProgramAnalyst"})
    r = get_or_404(reports, report_id, "ERR_COMPLIANCE_REPORT_NOT_FOUND")
    b = get_body()
    req_str(b, "reason", optional=True, default="", allow_empty=True)
    if r["status"] != "SUBMITTED":
        raise ApiError("ERR_COMPLIANCE_REPORT_INVALID_STATE", 409, "report not in SUBMITTED")
    r["status"] = "RETURNED"
    touch(r)
    return ok(serialize(r), 200)


@app.route("/compliance-reports/<report_id>/resubmit", methods=["POST"])
def resubmit_report(report_id):
    uid, _ = auth({"Applicant"})
    r = get_or_404(reports, report_id, "ERR_COMPLIANCE_REPORT_NOT_FOUND")
    b = get_body()
    actual_jobs = req_int(b, "actual_jobs", optional=True, default=None)
    actual_investment_cents = req_int(b, "actual_investment_cents", optional=True, default=None)
    attestation = b.get("attestation", None)
    if attestation is not None and not isinstance(attestation, bool):
        raise ApiError("ERR_VALIDATION", 422, "attestation must be a boolean")

    agr = agreements.get(r["agreement_id"])
    if agr and uid != agreement_owner(agr):
        raise ApiError("ERR_UNAUTHORIZED", 403, "only the owning applicant may resubmit")
    if r["status"] != "RETURNED":
        raise ApiError("ERR_COMPLIANCE_REPORT_INVALID_STATE", 409, "report not in RETURNED")

    if actual_jobs is not None:
        r["actual_jobs"] = actual_jobs
    if actual_investment_cents is not None:
        r["actual_investment_cents"] = actual_investment_cents
    if attestation is not None:
        r["attestation"] = attestation
        if attestation:
            r["certified_by"] = uid
    r["status"] = "SUBMITTED"
    touch(r)
    return ok(serialize(r), 200)


# ---- Disbursement ---------------------------------------------------------
@app.route("/disbursements", methods=["POST"])
def create_disbursement():
    auth({"ComplianceOfficer"})
    b = get_body()
    agreement_id = req_str(b, "agreement_id")
    compliance_report_id = req_str(b, "compliance_report_id")
    expected_version = req_int(b, "expected_agreement_version")

    a = get_or_404(agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")
    r = get_or_404(reports, compliance_report_id, "ERR_COMPLIANCE_REPORT_NOT_FOUND")

    # OCC (priority 6) before referential accepted-report (priority 8).
    if expected_version != a["version"]:
        raise ApiError("ERR_STALE_AGREEMENT_VERSION", 412, "expected_agreement_version is stale")
    if r["status"] != "ACCEPTED":
        raise ApiError("ERR_NO_ACCEPTED_REPORT", 409, "linked report is not ACCEPTED")

    gross, disbursed = calc_period_disbursement(a, r)
    rec = new_common()
    rec["agreement_id"] = agreement_id
    rec["compliance_report_id"] = compliance_report_id
    rec["period_year"] = r["reporting_year"]
    rec["gross_entitlement_cents"] = gross
    rec["disbursed_amount_cents"] = disbursed
    rec["status"] = "CALCULATED"
    disbursements[rec["id"]] = rec

    touch(a)  # creating a disbursement advances agreement.version
    return ok(serialize(rec), 201)


@app.route("/disbursements", methods=["GET"])
def list_disbursements():
    auth({"Applicant", "ProgramAnalyst", "ProgramDirector", "ComplianceOfficer"})
    filters = {
        "agreement_id": request.args.get("agreement_id"),
        "compliance_report_id": request.args.get("compliance_report_id"),
        "status": request.args.get("status"),
    }
    return list_response(disbursements.values(), serialize, filters)


@app.route("/disbursements/<disbursement_id>", methods=["GET"])
def get_disbursement(disbursement_id):
    auth({"Applicant", "ProgramAnalyst", "ProgramDirector", "ComplianceOfficer"})
    d = get_or_404(disbursements, disbursement_id, "ERR_DISBURSEMENT_NOT_FOUND")
    return ok(serialize(d), 200)


@app.route("/disbursements/<disbursement_id>/approve", methods=["POST"])
def approve_disbursement(disbursement_id):
    auth({"ComplianceOfficer"})
    d = get_or_404(disbursements, disbursement_id, "ERR_DISBURSEMENT_NOT_FOUND")
    if d["status"] != "CALCULATED":
        raise ApiError("ERR_DISBURSEMENT_INVALID_STATE", 409, "disbursement not in CALCULATED")
    d["status"] = "APPROVED"
    touch(d)
    return ok(serialize(d), 200)


@app.route("/disbursements/<disbursement_id>/pay", methods=["POST"])
def pay_disbursement(disbursement_id):
    auth({"ComplianceOfficer"})
    d = get_or_404(disbursements, disbursement_id, "ERR_DISBURSEMENT_NOT_FOUND")
    if d["status"] != "APPROVED":
        raise ApiError("ERR_DISBURSEMENT_INVALID_STATE", 409, "disbursement not in APPROVED")
    a = agreements[d["agreement_id"]]
    amt = d["disbursed_amount_cents"]
    if a["gross_disbursed_cents"] + amt > a["max_incentive_cents"]:
        raise ApiError("ERR_DISBURSEMENT_EXCEEDS_CAP", 402, "payment exceeds agreement cap")
    a["gross_disbursed_cents"] += amt
    a["net_disbursed_cents"] += amt
    d["status"] = "PAID"
    touch(d)
    touch(a)  # paying a disbursement advances agreement.version
    return ok(serialize(d), 200)


# ---- RecaptureAssessment --------------------------------------------------
@app.route("/recapture-assessments", methods=["GET"])
def list_assessments():
    auth({"Applicant", "ProgramAnalyst", "ProgramDirector", "ComplianceOfficer"})
    filters = {
        "agreement_id": request.args.get("agreement_id"),
        "status": request.args.get("status"),
    }
    return list_response(assessments.values(), serialize, filters)


@app.route("/recapture-assessments/<assessment_id>", methods=["GET"])
def get_assessment(assessment_id):
    auth({"Applicant", "ProgramAnalyst", "ProgramDirector", "ComplianceOfficer"})
    r = get_or_404(assessments, assessment_id, "ERR_RECAPTURE_ASSESSMENT_NOT_FOUND")
    return ok(serialize(r), 200)


@app.route("/recapture-assessments/<assessment_id>/dispute", methods=["POST"])
def dispute_assessment(assessment_id):
    uid, _ = auth({"Applicant"})
    r = get_or_404(assessments, assessment_id, "ERR_RECAPTURE_ASSESSMENT_NOT_FOUND")
    b = get_body()
    req_str(b, "grounds", optional=True, default="", allow_empty=True)
    agr = agreements.get(r["agreement_id"])
    if agr and uid != agreement_owner(agr):
        raise ApiError("ERR_UNAUTHORIZED", 403, "only the owning applicant may dispute")
    if r["status"] != "ASSESSED":
        raise ApiError("ERR_RECAPTURE_INVALID_STATE", 409, "assessment not in ASSESSED")
    r["status"] = "DISPUTED"
    touch(r)
    return ok(serialize(r), 200)


def close_agreement_via_recapture(agr, clawback):
    if clawback:
        for d in disbursements.values():
            if d["agreement_id"] != agr["id"] or d["status"] != "PAID":
                continue
            amt = d["disbursed_amount_cents"]
            d["status"] = "CLAWED_BACK"
            touch(d)
            agr["net_disbursed_cents"] -= amt
            agr["clawed_back_cents"] += amt
    if agr["status"] == "DEFAULTED":
        agr["status"] = "CLOSED"
        touch(agr)


@app.route("/recapture-assessments/<assessment_id>/finalize", methods=["POST"])
def finalize_assessment(assessment_id):
    auth({"ComplianceOfficer"})
    r = get_or_404(assessments, assessment_id, "ERR_RECAPTURE_ASSESSMENT_NOT_FOUND")
    b = get_body()
    reopen = b.get("reopen", False)
    if reopen is not None and not isinstance(reopen, bool):
        raise ApiError("ERR_VALIDATION", 422, "reopen must be a boolean")

    if reopen:
        if r["status"] != "DISPUTED":
            raise ApiError("ERR_RECAPTURE_INVALID_STATE", 409, "reopen requires DISPUTED")
        r["status"] = "ASSESSED"
        touch(r)
        return ok(serialize(r), 200)

    if r["status"] not in ("ASSESSED", "DISPUTED"):
        raise ApiError("ERR_RECAPTURE_INVALID_STATE", 409, "assessment not in ASSESSED/DISPUTED")
    r["status"] = "FINALIZED"
    touch(r)
    agr = agreements.get(r["agreement_id"])
    if agr:
        close_agreement_via_recapture(agr, clawback=True)
    return ok(serialize(r), 200)


@app.route("/recapture-assessments/<assessment_id>/waive", methods=["POST"])
def waive_assessment(assessment_id):
    auth({"ProgramDirector"})
    r = get_or_404(assessments, assessment_id, "ERR_RECAPTURE_ASSESSMENT_NOT_FOUND")
    b = get_body()
    req_str(b, "reason", optional=True, default="", allow_empty=True)
    if r["status"] not in ("ASSESSED", "DISPUTED"):
        raise ApiError("ERR_RECAPTURE_INVALID_STATE", 409, "assessment not in ASSESSED/DISPUTED")
    r["status"] = "WAIVED"
    touch(r)
    agr = agreements.get(r["agreement_id"])
    if agr:
        close_agreement_via_recapture(agr, clawback=False)
    return ok(serialize(r), 200)


# ---- TransparencyDisclosure -----------------------------------------------
@app.route("/agreements/<agreement_id>/disclosures", methods=["POST"])
def create_disclosure(agreement_id):
    auth({"ComplianceOfficer"})
    a = get_or_404(agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")
    b = get_body()
    disclosure_year = req_int(b, "disclosure_year")
    app_rec = applications.get(a["application_id"])

    rec = new_common()
    rec["agreement_id"] = agreement_id
    rec["disclosure_year"] = disclosure_year
    rec["disclosed_recipient_name"] = app_rec["applicant_name"] if app_rec else None
    rec["disclosed_incentive_type"] = a["incentive_type"]
    rec["disclosed_max_incentive_cents"] = a["max_incentive_cents"]
    rec["disclosed_net_disbursed_cents"] = a["net_disbursed_cents"]
    rec["disclosed_jobs_committed"] = a["awarded_jobs"]
    rec["status"] = "PUBLISHED"
    disclosures[rec["id"]] = rec
    return ok(serialize(rec), 201)


@app.route("/disclosures", methods=["GET"])
def list_disclosures():
    auth({"Applicant", "ProgramAnalyst", "ProgramDirector", "ComplianceOfficer", "PublicViewer"})
    filters = {
        "agreement_id": request.args.get("agreement_id"),
        "status": request.args.get("status"),
    }
    return list_response(disclosures.values(), serialize, filters)


@app.route("/disclosures/<disclosure_id>", methods=["GET"])
def get_disclosure(disclosure_id):
    auth({"Applicant", "ProgramAnalyst", "ProgramDirector", "ComplianceOfficer", "PublicViewer"})
    d = get_or_404(disclosures, disclosure_id, "ERR_DISCLOSURE_NOT_FOUND")
    return ok(serialize(d), 200)


# ---- Portfolio dashboard --------------------------------------------------
@app.route("/portfolio/summary", methods=["GET"])
def portfolio_summary():
    auth({"ProgramAnalyst", "ProgramDirector", "ComplianceOfficer", "PublicViewer"})
    scope = request.args.get("program_id")

    def agr_in_scope(a):
        return scope is None or a["program_id"] == scope

    active = sum(1 for a in agreements.values() if a["status"] == "ACTIVE" and agr_in_scope(a))
    defaulted = sum(1 for a in agreements.values() if a["status"] == "DEFAULTED" and agr_in_scope(a))

    total_committed = 0
    total_disbursed = 0
    for p in programs.values():
        if scope is not None and p["id"] != scope:
            continue
        total_committed += compute_committed(p["id"])
        total_disbursed += compute_disbursed(p["id"])

    total_recaptured = 0
    for asr in assessments.values():
        if asr["status"] != "FINALIZED":
            continue
        agr = agreements.get(asr["agreement_id"])
        if agr and agr_in_scope(agr):
            total_recaptured += asr["assessed_amount_cents"]

    data = {
        "active_agreement_count": active,
        "defaulted_agreement_count": defaulted,
        "total_committed_cents": total_committed,
        "total_disbursed_cents": total_disbursed,
        "total_recaptured_cents": total_recaptured,
    }
    return ok(data, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
