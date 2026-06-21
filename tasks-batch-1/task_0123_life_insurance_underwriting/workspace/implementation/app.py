"""Life Insurance Underwriting API — Flask entry point.

Boots a fresh in-memory store on every process start (per-test-server
isolation). No seeding, no disk persistence.
"""
import os
import time

from flask import Flask, request

import auth
import calculations
import validate
from clock import clock
from db import store
from errors import ApiError, err
from models import make_record, serialize, touch
from response import error_response, success
import policy_service as ps

app = Flask(__name__)
app.url_map.strict_slashes = False


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    body = error_response(e.error_id, e.message)
    from flask import jsonify
    resp = jsonify(body)
    resp.status_code = e.http_status
    return resp


@app.errorhandler(404)
def handle_404(e):
    from flask import jsonify
    body = error_response("ERR_NOT_FOUND", "Resource not found.")
    resp = jsonify(body)
    resp.status_code = 404
    return resp


@app.errorhandler(405)
def handle_405(e):
    from flask import jsonify
    body = error_response("ERR_NOT_FOUND", "Method not allowed.")
    resp = jsonify(body)
    resp.status_code = 404
    return resp


@app.errorhandler(Exception)
def handle_uncaught(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    from flask import jsonify
    body = error_response("ERR_INVALID_REQUEST", f"Unexpected error: {e}")
    resp = jsonify(body)
    resp.status_code = 422
    return resp


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------
def get_body():
    if request.data is None or len(request.data) == 0:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    return validate.require_dict(data)


def begin(allowed_roles):
    """Auth (priority 1) + authz (priority 2). Returns the principal."""
    principal = auth.authenticate()
    auth.authorize(principal, allowed_roles)
    return principal


def paginate(items):
    """Apply limit/offset; return (page, pagination_meta).

    items must already be sorted. limit default 10 (min 1, max 100), offset
    default 0 (PRD §2.3). Out-of-range values are rejected as ERR_INVALID_REQUEST.
    """
    total = len(items)
    limit = _int_query("limit", default=10, minimum=1, maximum=100)
    offset = _int_query("offset", default=0, minimum=0)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


def _int_query(name, default, minimum=None, maximum=None):
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", f"Query param {name} must be an integer.")
    if minimum is not None and value < minimum:
        raise err("ERR_INVALID_REQUEST", f"Query param {name} must be >= {minimum}.")
    if maximum is not None and value > maximum:
        raise err("ERR_INVALID_REQUEST", f"Query param {name} must be <= {maximum}.")
    return value


def sorted_by_created(records):
    return sorted(records, key=lambda r: r["_seq"])


# Lookup-or-404 (path existence -> ERR_NOT_FOUND).
def get_or_404(collection, _id):
    rec = collection.get(_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Resource not found.")
    return rec


# FK-or-ref-not-found (body FK -> ERR_REFERENCE_NOT_FOUND).
def get_or_ref(collection, _id):
    rec = collection.get(_id)
    if rec is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "Referenced resource not found.")
    return rec


# ===========================================================================
# Products  (Admin create; Admin/Underwriter read)
# ===========================================================================
@app.route("/products", methods=["POST"])
def create_product():
    begin({"Admin"})
    body = get_body()
    code = validate.as_str(validate.get_required(body, "code"), "code", non_empty=True)
    base_rate = validate.as_int(validate.get_required(body, "base_annual_rate_per_thousand_cents"),
                                "base_annual_rate_per_thousand_cents", minimum=1)
    max_face = validate.as_int(validate.get_required(body, "max_face_amount_cents"),
                               "max_face_amount_cents", minimum=100000)
    accrual = validate.as_int(validate.get_required(body, "cash_value_accrual_rate_bps"),
                              "cash_value_accrual_rate_bps", minimum=0, maximum=10000)
    contestability_months = _opt_int(body, "contestability_months", 24, minimum=1)
    grace_period_days = _opt_int(body, "grace_period_days", 31, minimum=1)
    max_loan_pct = _opt_int(body, "max_loan_to_cash_value_pct", 90, minimum=1, maximum=100)
    exam_validity_days = _opt_int(body, "exam_validity_days", 180, minimum=1)

    with store.lock:
        # Uniqueness (priority 6).
        for p in store.products.values():
            if p["code"] == code:
                raise err("ERR_DUPLICATE_VALUE", "Product code already exists.")
        rec = make_record("Product", {
            "code": code,
            "base_annual_rate_per_thousand_cents": base_rate,
            "max_face_amount_cents": max_face,
            "cash_value_accrual_rate_bps": accrual,
            "contestability_months": contestability_months,
            "grace_period_days": grace_period_days,
            "max_loan_to_cash_value_pct": max_loan_pct,
            "exam_validity_days": exam_validity_days,
        })
        store.products[rec["id"]] = rec
    return success(serialize(rec), status=201)


def _opt_int(body, field, default, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        return default
    return validate.as_int(body[field], field, minimum=minimum, maximum=maximum)


@app.route("/products/<pid>", methods=["GET"])
def get_product(pid):
    begin({"Admin", "Underwriter"})
    rec = get_or_404(store.products, pid)
    return success(serialize(rec))


# ===========================================================================
# Underwriters  (Admin create; Admin/Underwriter read)
# ===========================================================================
@app.route("/underwriters", methods=["POST"])
def create_underwriter():
    begin({"Admin"})
    body = get_body()
    name = validate.as_str(validate.get_required(body, "name"), "name", non_empty=True)
    license_id = validate.as_str(validate.get_required(body, "license_id"), "license_id", non_empty=True)
    with store.lock:
        for u in store.underwriters.values():
            if u["license_id"] == license_id:
                raise err("ERR_DUPLICATE_VALUE", "Underwriter license_id already exists.")
        rec = make_record("Underwriter", {"name": name, "license_id": license_id})
        store.underwriters[rec["id"]] = rec
    return success(serialize(rec), status=201)


@app.route("/underwriters/<uid>", methods=["GET"])
def get_underwriter(uid):
    begin({"Admin", "Underwriter"})
    rec = get_or_404(store.underwriters, uid)
    return success(serialize(rec))


# ===========================================================================
# Applicants  (Admin/Underwriter create + read)
# ===========================================================================
@app.route("/applicants", methods=["POST"])
def create_applicant():
    begin({"Admin", "Underwriter"})
    body = get_body()
    full_name = validate.as_str(validate.get_required(body, "full_name"), "full_name", non_empty=True)
    dob = validate.get_required(body, "date_of_birth")
    validate.parse_date(dob, "date_of_birth", must_be_past=True)
    sex = validate.as_enum(validate.get_required(body, "sex"), "sex", {"MALE", "FEMALE"})
    tobacco = validate.as_bool(validate.get_required(body, "tobacco_use"), "tobacco_use")
    email = validate.as_str(validate.get_required(body, "email"), "email", non_empty=True)
    with store.lock:
        for a in store.applicants.values():
            if a["email"] == email:
                raise err("ERR_DUPLICATE_VALUE", "Applicant email already exists.")
        rec = make_record("Applicant", {
            "full_name": full_name,
            "date_of_birth": dob,
            "sex": sex,
            "tobacco_use": tobacco,
            "email": email,
        })
        store.applicants[rec["id"]] = rec
    return success(serialize(rec), status=201)


@app.route("/applicants/<aid>", methods=["GET"])
def get_applicant(aid):
    begin({"Admin", "Underwriter"})
    rec = get_or_404(store.applicants, aid)
    return success(serialize(rec))


# ===========================================================================
# Applications
# ===========================================================================
@app.route("/applications", methods=["POST"])
def create_application():
    begin({"Underwriter"})
    body = get_body()
    # FK fields must be present + well-typed (these are part of the body) before
    # we can resolve their existence.
    applicant_id = validate.as_str(validate.get_required(body, "applicant_id"), "applicant_id")
    product_id = validate.as_str(validate.get_required(body, "product_id"), "product_id")
    with store.lock:
        # Body FK existence (priority 4) precedes body well-formedness (priority 5)
        # and the face ceiling (priority 16).
        applicant = get_or_ref(store.applicants, applicant_id)
        product = get_or_ref(store.products, product_id)
        face = validate.as_int(validate.get_required(body, "requested_face_amount_cents"),
                               "requested_face_amount_cents", minimum=100000)
        # Face ceiling (priority 16).
        if face > product["max_face_amount_cents"]:
            raise err("ERR_FACE_EXCEEDS_PRODUCT_MAX", "Requested face exceeds product maximum.")
        rec = make_record("Application", {
            "applicant_id": applicant_id,
            "product_id": product_id,
            "ordering_underwriter_id": None,
            "deciding_underwriter_id": None,
            "requested_face_amount_cents": face,
            "status": "DRAFT",
            "offer_expires_at": None,
            "provisional_annual_premium_cents": None,
            "final_annual_premium_cents": None,
        })
        store.applications[rec["id"]] = rec
    return success(serialize(rec), status=201)


def _reflect_application_expiry(appn):
    """Lazy APPROVED_OFFER -> EXPIRED once the clock passes offer_expires_at."""
    if appn["status"] == "APPROVED_OFFER" and appn.get("offer_expires_at"):
        expires = validate.parse_datetime(appn["offer_expires_at"], "offer_expires_at")
        if clock.now() > expires:
            appn["status"] = "EXPIRED"
            touch(appn)


@app.route("/applications/<aid>", methods=["GET"])
def get_application(aid):
    begin({"Admin", "Underwriter"})
    with store.lock:
        rec = get_or_404(store.applications, aid)
        _reflect_application_expiry(rec)
    return success(serialize(rec))


@app.route("/applications", methods=["GET"])
def list_applications():
    begin({"Admin", "Underwriter"})
    with store.lock:
        items = list(store.applications.values())
        for f in ("applicant_id", "product_id", "ordering_underwriter_id", "deciding_underwriter_id"):
            val = request.args.get(f)
            if val is not None:
                items = [a for a in items if a.get(f) == val]
        for a in items:
            _reflect_application_expiry(a)
        items = sorted_by_created(items)
        page, meta = paginate(items)
        data = [serialize(a) for a in page]
    return success(data, pagination=meta)


def _acting_underwriter_id(principal):
    return principal.user_id


@app.route("/applications/<aid>/submit", methods=["POST"])
def submit_application(aid):
    begin({"Underwriter"})
    with store.lock:
        appn = get_or_404(store.applications, aid)
        if appn["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "Application is not in DRAFT.")
        applicant = store.applicants.get(appn["applicant_id"])
        product = store.products.get(appn["product_id"])
        # Referenced applicant and product must exist (precondition).
        if applicant is None or product is None:
            raise err("ERR_REFERENCE_NOT_FOUND", "Referenced applicant or product missing.")
        if appn["requested_face_amount_cents"] > product["max_face_amount_cents"]:
            raise err("ERR_FACE_EXCEEDS_PRODUCT_MAX", "Requested face exceeds product maximum.")
        # compute_premium variant=provisional (class mult = 1000, STANDARD).
        premium = calculations.compute_premium(
            appn["requested_face_amount_cents"],
            product["base_annual_rate_per_thousand_cents"],
            applicant["tobacco_use"],
            calculations.PROVISIONAL_CLASS_MULT_MILLI,
        )
        appn["provisional_annual_premium_cents"] = premium
        appn["status"] = "SUBMITTED"
        touch(appn)
    return success(serialize(appn))


@app.route("/applications/<aid>/order-exam", methods=["POST"])
def order_exam(aid):
    principal = begin({"Underwriter"})
    with store.lock:
        appn = get_or_404(store.applications, aid)
        if appn["status"] not in ("SUBMITTED", "UNDER_REVIEW"):
            raise err("ERR_INVALID_STATE", "Application is not in SUBMITTED or UNDER_REVIEW.")
        # Create an ORDERED ParamedExam shell (measurements attached later via
        # POST /applications/{id}/paramed-exams while in EXAM_PENDING).
        # PRD §3.3: ordering moves the application to EXAM_PENDING and pins the
        # ordering underwriter. It does NOT itself create a ParamedExam — the exam is
        # attached separately via POST /applications/{id}/paramed-exams while the
        # application sits in EXAM_PENDING. Creating a shell exam here would invent a
        # phantom row with no PRD basis and inflate the paramed-exam list.
        appn["ordering_underwriter_id"] = _acting_underwriter_id(principal)
        appn["status"] = "EXAM_PENDING"
        touch(appn)
    return success(serialize(appn))


@app.route("/applications/<aid>/begin-review", methods=["POST"])
def begin_review(aid):
    begin({"Underwriter"})
    with store.lock:
        appn = get_or_404(store.applications, aid)
        status = appn["status"]
        if status not in ("EXAM_PENDING", "POSTPONED"):
            raise err("ERR_INVALID_STATE", "Application is not in EXAM_PENDING or POSTPONED.")
        completed_exams = [
            e for e in store.paramed_exams.values()
            if e["application_id"] == appn["id"] and e["status"] == "COMPLETED"
        ]
        mib_checks = [m for m in store.mib_checks.values() if m["application_id"] == appn["id"]]
        # Evidence completeness (priority 8).
        if status == "EXAM_PENDING":
            if not completed_exams or not mib_checks:
                raise err("ERR_EVIDENCE_INCOMPLETE",
                          "begin-review requires a COMPLETED exam and at least one MIB check.")
        else:  # POSTPONED -> only a COMPLETED exam required.
            if not completed_exams:
                raise err("ERR_EVIDENCE_INCOMPLETE", "begin-review requires a COMPLETED exam.")
        # classify_risk: most-recently-COMPLETED exam (MAX created_at == MAX _seq).
        exam = max(completed_exams, key=lambda e: e["_seq"])
        applicant = store.applicants[appn["applicant_id"]]
        any_flagged = any(m["result"] == "FLAGGED" for m in mib_checks)
        build, total, risk_class, table_rating = calculations.classify_risk(
            exam["weight_pounds"], exam["height_inches"], exam["systolic_bp"],
            applicant["tobacco_use"], any_flagged,
        )
        # Create or refresh the (single) RiskAssessment for this application.
        existing = [r for r in store.risk_assessments.values() if r["application_id"] == appn["id"]]
        if existing:
            ra = existing[0]
            ra["build_debits"] = build
            ra["total_debits"] = total
            ra["risk_class"] = risk_class
            ra["table_rating"] = table_rating
            ra["finalized"] = False
            touch(ra)
        else:
            ra = make_record("RiskAssessment", {
                "application_id": appn["id"],
                "build_debits": build,
                "total_debits": total,
                "risk_class": risk_class,
                "table_rating": table_rating,
                "finalized": False,
            })
            store.risk_assessments[ra["id"]] = ra
        appn["status"] = "UNDER_REVIEW"
        touch(appn)
    return success(serialize(appn))


@app.route("/applications/<aid>/approve", methods=["POST"])
def approve_application(aid):
    principal = begin({"Underwriter"})
    body = get_body()
    expected_version = validate.as_int(
        validate.get_required(body, "expected_application_version"),
        "expected_application_version", minimum=0,
    )
    with store.lock:
        appn = get_or_404(store.applications, aid)
        _reflect_application_expiry(appn)
        if appn["status"] != "UNDER_REVIEW":
            raise err("ERR_INVALID_STATE", "Application is not UNDER_REVIEW.")
        # Segregation of duties (priority 9).
        if _acting_underwriter_id(principal) == appn["ordering_underwriter_id"]:
            raise err("ERR_SEGREGATION_OF_DUTIES", "Decider must differ from ordering underwriter.")
        # Uninsurable risk gate (priority 10).
        ra_list = [r for r in store.risk_assessments.values() if r["application_id"] == appn["id"]]
        ra = ra_list[0] if ra_list else None
        mib_checks = [m for m in store.mib_checks.values() if m["application_id"] == appn["id"]]
        if ra is None or ra["risk_class"] in ("TABLE_7", "TABLE_8") or any(m["result"] == "FLAGGED" for m in mib_checks):
            raise err("ERR_UNINSURABLE_RISK", "Risk is uninsurable or evidence flagged.")
        # OCC (priority 17) — last gate before commit.
        if expected_version != appn["version"]:
            raise err("ERR_STALE_APPLICATION_VERSION", "Application version is stale.")
        # compute_premium variant=final from finalized RiskAssessment.
        applicant = store.applicants[appn["applicant_id"]]
        product = store.products[appn["product_id"]]
        class_mult = calculations.class_mult_milli_for(ra["risk_class"], ra["table_rating"])
        premium = calculations.compute_premium(
            appn["requested_face_amount_cents"],
            product["base_annual_rate_per_thousand_cents"],
            applicant["tobacco_use"],
            class_mult,
        )
        appn["final_annual_premium_cents"] = premium
        ra["finalized"] = True
        touch(ra)
        appn["deciding_underwriter_id"] = _acting_underwriter_id(principal)
        appn["offer_expires_at"] = _iso_instant(validate_add_days_dt(clock.now(), 30))
        appn["status"] = "APPROVED_OFFER"
        touch(appn)
    return success(serialize(appn))


def validate_add_days_dt(dt, days):
    from datetime import timedelta
    return dt + timedelta(days=days)


def _iso_instant(dt):
    from datetime import timezone
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


@app.route("/applications/<aid>/postpone", methods=["POST"])
def postpone_application(aid):
    principal = begin({"Underwriter"})
    with store.lock:
        appn = get_or_404(store.applications, aid)
        if appn["status"] != "UNDER_REVIEW":
            raise err("ERR_INVALID_STATE", "Application is not UNDER_REVIEW.")
        if _acting_underwriter_id(principal) == appn["ordering_underwriter_id"]:
            raise err("ERR_SEGREGATION_OF_DUTIES", "Decider must differ from ordering underwriter.")
        appn["deciding_underwriter_id"] = _acting_underwriter_id(principal)
        appn["status"] = "POSTPONED"
        touch(appn)
    return success(serialize(appn))


@app.route("/applications/<aid>/decline", methods=["POST"])
def decline_application(aid):
    principal = begin({"Underwriter"})
    with store.lock:
        appn = get_or_404(store.applications, aid)
        status = appn["status"]
        if status not in ("SUBMITTED", "UNDER_REVIEW"):
            raise err("ERR_INVALID_STATE", "Application cannot be declined from this state.")
        # Segregation of duties only applies from UNDER_REVIEW.
        if status == "UNDER_REVIEW":
            if _acting_underwriter_id(principal) == appn["ordering_underwriter_id"]:
                raise err("ERR_SEGREGATION_OF_DUTIES", "Decider must differ from ordering underwriter.")
        appn["deciding_underwriter_id"] = _acting_underwriter_id(principal)
        appn["status"] = "DECLINED"
        touch(appn)
    return success(serialize(appn))


@app.route("/applications/<aid>/issue", methods=["POST"])
def issue_application(aid):
    begin({"Underwriter"})
    body = get_body()
    expected_version = validate.as_int(
        validate.get_required(body, "expected_application_version"),
        "expected_application_version", minimum=0,
    )
    with store.lock:
        appn = get_or_404(store.applications, aid)
        # NOTE: do NOT eagerly flip APPROVED_OFFER -> EXPIRED here. The state
        # check (priority 7) precedes offer expiry (priority 11): if the offer is
        # still APPROVED_OFFER in storage but the clock has passed, issue must
        # report ERR_OFFER_EXPIRED — not ERR_INVALID_STATE. If a prior read
        # already flipped it to EXPIRED, the state check below reports
        # ERR_INVALID_STATE (no issue transition from EXPIRED).
        if appn["status"] != "APPROVED_OFFER":
            raise err("ERR_INVALID_STATE", "Application is not APPROVED_OFFER.")
        # Offer expiry (priority 11).
        expires = validate.parse_datetime(appn["offer_expires_at"], "offer_expires_at")
        if clock.now() > expires:
            appn["status"] = "EXPIRED"
            touch(appn)
            raise err("ERR_OFFER_EXPIRED", "Offer has expired.")
        # OCC (priority 17).
        if expected_version != appn["version"]:
            raise err("ERR_STALE_APPLICATION_VERSION", "Application version is stale.")
        # Create the Policy (cascade origin).
        issue_date = clock.now().date()
        product = store.products[appn["product_id"]]
        policy = make_record("Policy", {
            "application_id": appn["id"],
            "face_amount_cents": appn["requested_face_amount_cents"],
            "annual_premium_cents": appn["final_annual_premium_cents"],
            "issue_date": validate.iso_date(issue_date),
            "lifecycle_status": "IN_FORCE",
            "contestability_status": "CONTESTABLE",
            "next_premium_due_date": validate.iso_date(validate.add_years(issue_date, 1)),
            "cumulative_premium_paid_cents": appn["final_annual_premium_cents"],
            "gross_cash_value_cents": 0,
            "outstanding_loan_principal_cents": 0,
            "net_cash_value_cents": 0,
            # Internal: contestability window anchor (resets on reinstatement).
            "_contestability_start": validate.iso_date(issue_date),
        })
        store.policies[policy["id"]] = policy
        # First-year cash-value accrual (PRD §3.6): issuing "lays down the first
        # cash-value accrual ... for the first year". The first year's premium is
        # funded at issue, so cumulative_premium_paid_cents starts at one annual
        # premium and the §3.7 accrual formula yields the first PREMIUM_ACCRUAL
        # increment (cumulative * rate / 10000, half-up).
        ps.accrue_cash_value(policy)
        appn["status"] = "ISSUED"
        touch(appn)
    return success(serialize(policy), status=201)


# ===========================================================================
# ParamedExams
# ===========================================================================
@app.route("/applications/<aid>/paramed-exams", methods=["POST"])
def create_paramed_exam(aid):
    begin({"Underwriter"})
    body = get_body()
    with store.lock:
        appn = get_or_404(store.applications, aid)
        height = validate.as_int(validate.get_required(body, "height_inches"), "height_inches",
                                 minimum=48, maximum=84)
        weight = validate.as_int(validate.get_required(body, "weight_pounds"), "weight_pounds",
                                 minimum=60, maximum=500)
        bp = validate.as_int(validate.get_required(body, "systolic_bp"), "systolic_bp",
                             minimum=70, maximum=260)
        exam_date = validate.get_required(body, "exam_date")
        validate.parse_date(exam_date, "exam_date")
        rec = make_record("ParamedExam", {
            "application_id": appn["id"],
            "height_inches": height,
            "weight_pounds": weight,
            "systolic_bp": bp,
            "exam_date": exam_date,
            "status": "ORDERED",
        })
        store.paramed_exams[rec["id"]] = rec
    return success(serialize(rec), status=201)


@app.route("/applications/<aid>/paramed-exams", methods=["GET"])
def list_paramed_exams(aid):
    begin({"Admin", "Underwriter"})
    with store.lock:
        get_or_404(store.applications, aid)
        items = [e for e in store.paramed_exams.values() if e["application_id"] == aid]
        items = sorted_by_created(items)
        page, meta = paginate(items)
        data = [serialize(e) for e in page]
    return success(data, pagination=meta)


@app.route("/paramed-exams/<eid>", methods=["GET"])
def get_paramed_exam(eid):
    begin({"Admin", "Underwriter"})
    rec = get_or_404(store.paramed_exams, eid)
    return success(serialize(rec))


@app.route("/paramed-exams/<eid>/complete", methods=["POST"])
def complete_paramed_exam(eid):
    begin({"Underwriter"})
    with store.lock:
        exam = get_or_404(store.paramed_exams, eid)
        if exam["status"] != "ORDERED":
            raise err("ERR_INVALID_STATE", "Exam is not ORDERED.")
        # Measurements must all be present.
        for f in ("height_inches", "weight_pounds", "systolic_bp", "exam_date"):
            if exam.get(f) is None:
                raise err("ERR_INVALID_STATE", "Exam is missing measurements; cannot complete.")
        # check_exam_overlap (priority 8.5).
        product = _product_for_application(exam["application_id"])
        validity = product["exam_validity_days"]
        cand_start = validate.parse_date(exam["exam_date"], "exam_date")
        cand_end = validate.add_days(cand_start, validity)
        for other in store.paramed_exams.values():
            if other["id"] == exam["id"]:
                continue
            if other["application_id"] != exam["application_id"]:
                continue
            if other["status"] != "COMPLETED":
                continue
            o_start = validate.parse_date(other["exam_date"], "exam_date")
            o_end = validate.add_days(o_start, validity)
            if calculations.intervals_overlap(cand_start, cand_end, o_start, o_end):
                raise err("ERR_EXAM_WINDOW_OVERLAP", "Exam validity window overlaps a completed exam.")
        exam["status"] = "COMPLETED"
        touch(exam)
    return success(serialize(exam))


def _product_for_application(application_id):
    appn = store.applications[application_id]
    return store.products[appn["product_id"]]


@app.route("/paramed-exams/<eid>/cancel", methods=["POST"])
def cancel_paramed_exam(eid):
    begin({"Underwriter"})
    with store.lock:
        exam = get_or_404(store.paramed_exams, eid)
        if exam["status"] != "ORDERED":
            raise err("ERR_INVALID_STATE", "Exam is not ORDERED.")
        exam["status"] = "CANCELLED"
        touch(exam)
    return success(serialize(exam))


# ===========================================================================
# MIBChecks
# ===========================================================================
@app.route("/applications/<aid>/mib-checks", methods=["POST"])
def create_mib_check(aid):
    begin({"Underwriter"})
    body = get_body()
    with store.lock:
        appn = get_or_404(store.applications, aid)
        mib_hit = validate.as_bool(validate.get_required(body, "mib_hit"), "mib_hit")
        rx_flag_count = validate.as_int(validate.get_required(body, "rx_flag_count"),
                                        "rx_flag_count", minimum=0)
        result = "CLEAR" if (not mib_hit and rx_flag_count == 0) else "FLAGGED"
        rec = make_record("MIBCheck", {
            "application_id": appn["id"],
            "mib_hit": mib_hit,
            "rx_flag_count": rx_flag_count,
            "result": result,
        })
        store.mib_checks[rec["id"]] = rec
    return success(serialize(rec), status=201)


@app.route("/applications/<aid>/mib-checks", methods=["GET"])
def list_mib_checks(aid):
    begin({"Admin", "Underwriter"})
    with store.lock:
        get_or_404(store.applications, aid)
        items = [m for m in store.mib_checks.values() if m["application_id"] == aid]
        items = sorted_by_created(items)
        page, meta = paginate(items)
        data = [serialize(m) for m in page]
    return success(data, pagination=meta)


# ===========================================================================
# RiskAssessment
# ===========================================================================
@app.route("/applications/<aid>/risk-assessment", methods=["GET"])
def list_risk_assessment(aid):
    begin({"Admin", "Underwriter"})
    with store.lock:
        get_or_404(store.applications, aid)
        items = [r for r in store.risk_assessments.values() if r["application_id"] == aid]
        items = sorted_by_created(items)
        page, meta = paginate(items)
        data = [serialize(r) for r in page]
    return success(data, pagination=meta)


# ===========================================================================
# Policies
# ===========================================================================
def _policy_owner_applicant_id(policy):
    appn = store.applications[policy["application_id"]]
    return appn["applicant_id"]


def _check_policy_owner(principal, policy):
    """PolicyOwner ownership: trace policy -> application -> applicant."""
    if principal.role == "PolicyOwner":
        if _policy_owner_applicant_id(policy) != principal.user_id:
            raise err("ERR_UNAUTHORIZED", "PolicyOwner does not own this policy.")


@app.route("/policies/<pid>", methods=["GET"])
def get_policy(pid):
    principal = begin({"Admin", "Underwriter", "PolicyOwner"})
    with store.lock:
        policy = get_or_404(store.policies, pid)
        _check_policy_owner(principal, policy)
        ps.reconcile_policy_time(policy)
    return success(serialize(policy))


@app.route("/applications/<aid>/policies", methods=["GET"])
def list_application_policies(aid):
    begin({"Admin", "Underwriter"})
    with store.lock:
        get_or_404(store.applications, aid)
        items = [p for p in store.policies.values() if p["application_id"] == aid]
        for p in items:
            ps.reconcile_policy_time(p)
        items = sorted_by_created(items)
        page, meta = paginate(items)
        data = [serialize(p) for p in page]
    return success(data, pagination=meta)


@app.route("/policies/<pid>/premium-payments", methods=["POST"])
def create_premium_payment(pid):
    principal = begin({"PolicyOwner"})
    body = get_body()
    with store.lock:
        policy = get_or_404(store.policies, pid)
        _check_policy_owner(principal, policy)
        ps.reconcile_policy_time(policy)
        amount = validate.as_int(validate.get_required(body, "amount_cents"), "amount_cents", minimum=1)
        coverage_start_raw = body.get("coverage_period_start")
        if coverage_start_raw is not None:
            cov_start = validate.parse_date(coverage_start_raw, "coverage_period_start")
        else:
            cov_start = validate.parse_date(policy["next_premium_due_date"], "next_premium_due_date")
        # State: defined from IN_FORCE or GRACE (priority 7).
        if policy["lifecycle_status"] not in ("IN_FORCE", "GRACE"):
            raise err("ERR_INVALID_STATE", "Policy cannot accept payment in its current state.")
        # GRACE acceptance window.
        if policy["lifecycle_status"] == "GRACE":
            product = ps.product_for_policy(policy)
            due = validate.parse_date(policy["next_premium_due_date"], "next_premium_due_date")
            limit = validate.add_days(due, product["grace_period_days"])
            if clock.now().date() > limit:
                raise err("ERR_INVALID_STATE", "Grace period has elapsed.")
        # Exact amount (priority 13).
        if amount != policy["annual_premium_cents"]:
            raise err("ERR_PREMIUM_AMOUNT_MISMATCH", "Payment must equal the annual premium.")
        # Coverage overlap (priority 13.5).
        cov_end = validate.add_years(cov_start, 1)
        _assert_no_coverage_overlap(policy["id"], cov_start, cov_end)
        # Record payment.
        next_due = validate.parse_date(policy["next_premium_due_date"], "next_premium_due_date")
        on_cycle = (cov_start == next_due)
        rec = make_record("PremiumPayment", {
            "policy_id": policy["id"],
            "amount_cents": amount,
            "paid_at": _iso_instant(clock.now()),
            "applied_to_due_date": policy["next_premium_due_date"],
            "coverage_period_start": validate.iso_date(cov_start),
            "coverage_period_end": validate.iso_date(cov_end),
        })
        store.premium_payments[rec["id"]] = rec
        if on_cycle:
            policy["next_premium_due_date"] = validate.iso_date(validate.add_years(next_due, 1))
        policy["cumulative_premium_paid_cents"] += amount
        ps.accrue_cash_value(policy)
        if policy["lifecycle_status"] == "GRACE":
            policy["lifecycle_status"] = "IN_FORCE"
        touch(policy)
    return success(serialize(rec), status=201)


def _assert_no_coverage_overlap(policy_id, new_start, new_end):
    for p in store.premium_payments.values():
        if p["policy_id"] != policy_id:
            continue
        e_start = validate.parse_date(p["coverage_period_start"], "coverage_period_start")
        e_end = validate.parse_date(p["coverage_period_end"], "coverage_period_end")
        if calculations.intervals_overlap(new_start, new_end, e_start, e_end):
            raise err("ERR_COVERAGE_PERIOD_OVERLAP", "Coverage interval overlaps an existing payment.")


@app.route("/policies/<pid>/premium-payments", methods=["GET"])
def list_premium_payments(pid):
    principal = begin({"Admin", "Underwriter", "PolicyOwner"})
    with store.lock:
        policy = get_or_404(store.policies, pid)
        _check_policy_owner(principal, policy)
        items = [p for p in store.premium_payments.values() if p["policy_id"] == pid]
        items = sorted_by_created(items)
        page, meta = paginate(items)
        data = [serialize(p) for p in page]
    return success(data, pagination=meta)


@app.route("/policies/<pid>/reinstate", methods=["POST"])
def reinstate_policy(pid):
    principal = begin({"PolicyOwner"})
    body = get_body()
    with store.lock:
        policy = get_or_404(store.policies, pid)
        _check_policy_owner(principal, policy)
        ps.reconcile_policy_time(policy)
        back_premium_count = validate.as_int(
            validate.get_required(body, "back_premium_count"), "back_premium_count", minimum=0)
        if policy["lifecycle_status"] != "LAPSED":
            raise err("ERR_INVALID_STATE", "Policy is not LAPSED.")
        issue_date = validate.parse_date(policy["issue_date"], "issue_date")
        window_close = validate.add_years(issue_date, 3)
        now_date = clock.now().date()
        # Reinstatement window (priority 12).
        if now_date > window_close:
            raise err("ERR_REINSTATEMENT_WINDOW_CLOSED", "Reinstatement window has closed.")
        # Required back premiums: whole years from applied due date through clock.
        applied_due = validate.parse_date(policy["next_premium_due_date"], "next_premium_due_date")
        required = _whole_years_overdue(applied_due, now_date)
        if back_premium_count < required:
            raise err("ERR_BACK_PREMIUM_INSUFFICIENT", "Back premium count does not cover all overdue premiums.")
        # Record back premiums as on-cycle payments, advancing the due date.
        cur_due = applied_due
        product = ps.product_for_policy(policy)
        for _ in range(back_premium_count):
            cov_start = cur_due
            cov_end = validate.add_years(cov_start, 1)
            _assert_no_coverage_overlap(policy["id"], cov_start, cov_end)
            rec = make_record("PremiumPayment", {
                "policy_id": policy["id"],
                "amount_cents": policy["annual_premium_cents"],
                "paid_at": _iso_instant(clock.now()),
                "applied_to_due_date": validate.iso_date(cur_due),
                "coverage_period_start": validate.iso_date(cov_start),
                "coverage_period_end": validate.iso_date(cov_end),
            })
            store.premium_payments[rec["id"]] = rec
            policy["cumulative_premium_paid_cents"] += policy["annual_premium_cents"]
            ps.accrue_cash_value(policy)
            cur_due = validate.add_years(cur_due, 1)
        policy["next_premium_due_date"] = validate.iso_date(cur_due)
        # Reset contestability: fresh window from the reinstatement date.
        policy["contestability_status"] = "CONTESTABLE"
        policy["_contestability_start"] = validate.iso_date(now_date)
        policy["lifecycle_status"] = "REINSTATED"
        touch(policy)
    return success(serialize(policy))


def _whole_years_overdue(applied_due, now_date):
    """Number of whole annual premiums overdue from applied_due through now."""
    count = 0
    cur = applied_due
    while cur <= now_date:
        count += 1
        cur = validate.add_years(cur, 1)
    return count


# ===========================================================================
# Beneficiaries
# ===========================================================================
@app.route("/policies/<pid>/beneficiaries", methods=["POST"])
def add_beneficiary(pid):
    principal = begin({"PolicyOwner"})
    body = get_body()
    with store.lock:
        policy = get_or_404(store.policies, pid)
        _check_policy_owner(principal, policy)
        full_name = validate.as_str(validate.get_required(body, "full_name"), "full_name", non_empty=True)
        designation = validate.as_enum(validate.get_required(body, "designation"), "designation",
                                       {"PRIMARY", "CONTINGENT"})
        share_pct = validate.as_int(validate.get_required(body, "share_pct"), "share_pct",
                                    minimum=1, maximum=100)
        rec = make_record("Beneficiary", {
            "policy_id": policy["id"],
            "full_name": full_name,
            "designation": designation,
            "share_pct": share_pct,
        })
        store.beneficiaries[rec["id"]] = rec
        # Validate tier sums AFTER adding (priority 14). Roll back on failure so
        # a rejected beneficiary does not pollute the tier for later operations.
        try:
            _validate_beneficiary_tiers(policy["id"])
        except Exception:
            del store.beneficiaries[rec["id"]]
            raise
    return success(serialize(rec), status=201)


def _validate_beneficiary_tiers(policy_id):
    bens = [b for b in store.beneficiaries.values() if b["policy_id"] == policy_id]
    primary = [b for b in bens if b["designation"] == "PRIMARY"]
    contingent = [b for b in bens if b["designation"] == "CONTINGENT"]
    if primary and sum(b["share_pct"] for b in primary) != 100:
        raise err("ERR_BENEFICIARY_SHARE_INVALID", "PRIMARY tier shares must sum to 100.")
    if contingent and sum(b["share_pct"] for b in contingent) != 100:
        raise err("ERR_BENEFICIARY_SHARE_INVALID", "CONTINGENT tier shares must sum to 100.")


@app.route("/policies/<pid>/beneficiaries", methods=["GET"])
def list_beneficiaries(pid):
    principal = begin({"Admin", "Underwriter", "PolicyOwner"})
    with store.lock:
        policy = get_or_404(store.policies, pid)
        _check_policy_owner(principal, policy)
        items = [b for b in store.beneficiaries.values() if b["policy_id"] == pid]
        items = sorted_by_created(items)
        page, meta = paginate(items)
        data = [serialize(b) for b in page]
    return success(data, pagination=meta)


@app.route("/beneficiaries/<bid>", methods=["DELETE"])
def delete_beneficiary(bid):
    principal = begin({"PolicyOwner"})
    with store.lock:
        ben = get_or_404(store.beneficiaries, bid)
        policy = store.policies.get(ben["policy_id"])
        if policy is not None:
            _check_policy_owner(principal, policy)
        affected_tier = ben["designation"]
        del store.beneficiaries[bid]
        # Re-validate the affected tier (priority 14): remaining must sum to 100
        # unless the tier became empty.
        remaining = [b for b in store.beneficiaries.values()
                     if b["policy_id"] == ben["policy_id"] and b["designation"] == affected_tier]
        if remaining and sum(b["share_pct"] for b in remaining) != 100:
            # Roll back the deletion.
            store.beneficiaries[bid] = ben
            raise err("ERR_BENEFICIARY_SHARE_INVALID", "Remaining tier shares must still sum to 100.")
    return success(serialize(ben))


# ===========================================================================
# PolicyLoans
# ===========================================================================
@app.route("/policies/<pid>/policy-loans", methods=["POST"])
def draw_policy_loan(pid):
    principal = begin({"PolicyOwner"})
    body = get_body()
    with store.lock:
        policy = get_or_404(store.policies, pid)
        _check_policy_owner(principal, policy)
        ps.reconcile_policy_time(policy)
        principal_cents = validate.as_int(validate.get_required(body, "principal_cents"),
                                          "principal_cents", minimum=1)
        expected_version = validate.as_int(
            validate.get_required(body, "expected_policy_version"), "expected_policy_version", minimum=0)
        # Loan value cap (priority 15).
        product = ps.product_for_policy(policy)
        available = calculations.available_loan_value(
            policy["gross_cash_value_cents"], policy["outstanding_loan_principal_cents"],
            product["max_loan_to_cash_value_pct"],
        )
        if principal_cents > available:
            raise err("ERR_LOAN_EXCEEDS_VALUE", "Requested principal exceeds available loan value.")
        # OCC (priority 17) — last gate before commit.
        if expected_version != policy["version"]:
            raise err("ERR_STALE_POLICY_VERSION", "Policy version is stale.")
        rec = make_record("PolicyLoan", {
            "policy_id": policy["id"],
            "principal_cents": principal_cents,
            "status": "ACTIVE",
        })
        store.policy_loans[rec["id"]] = rec
        ps.reconcile(policy)
        touch(policy)
    return success(serialize(rec), status=201)


@app.route("/policies/<pid>/policy-loans", methods=["GET"])
def list_policy_loans(pid):
    principal = begin({"Admin", "Underwriter", "PolicyOwner"})
    with store.lock:
        policy = get_or_404(store.policies, pid)
        _check_policy_owner(principal, policy)
        items = [l for l in store.policy_loans.values() if l["policy_id"] == pid]
        items = sorted_by_created(items)
        page, meta = paginate(items)
        data = [serialize(l) for l in page]
    return success(data, pagination=meta)


@app.route("/policy-loans/<lid>/repay", methods=["POST"])
def repay_policy_loan(lid):
    principal = begin({"PolicyOwner"})
    with store.lock:
        loan = get_or_404(store.policy_loans, lid)
        policy = store.policies.get(loan["policy_id"])
        if policy is not None:
            _check_policy_owner(principal, policy)
        if loan["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "Loan is not ACTIVE.")
        loan["status"] = "REPAID"
        touch(loan)
        ps.reconcile(policy)
        touch(policy)
    return success(serialize(loan))


# ===========================================================================
# CashValueEntries
# ===========================================================================
@app.route("/policies/<pid>/cash-value-entries", methods=["GET"])
def list_cash_value_entries(pid):
    principal = begin({"Admin", "Underwriter", "PolicyOwner"})
    with store.lock:
        policy = get_or_404(store.policies, pid)
        _check_policy_owner(principal, policy)
        items = [c for c in store.cash_value_entries.values() if c["policy_id"] == pid]
        items = sorted_by_created(items)
        page, meta = paginate(items)
        data = [serialize(c) for c in page]
    return success(data, pagination=meta)


# ===========================================================================
# Test-driving clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    begin({"Admin"})
    body = get_body()
    target = validate.get_required(body, "to_iso8601")
    dt = validate.parse_datetime(target, "to_iso8601")
    clock.set(dt)
    return success({})


# ---------------------------------------------------------------------------
# Boot
# ---------------------------------------------------------------------------
def _make_server(host, port):
    """Build a WSGI server bound to host:port, retrying on a transient
    same-port bind race that can occur on rapid per-test-server restarts."""
    from werkzeug.serving import make_server
    last_err = None
    for _ in range(40):
        try:
            return make_server(host, port, app, threaded=True)
        except OSError as e:
            last_err = e
            time.sleep(0.25)
    raise last_err


def _bind_and_run():
    port = int(os.environ.get("PORT", "10000"))
    host = "0.0.0.0"
    server = _make_server(host, port)
    server.serve_forever()


if __name__ == "__main__":
    _bind_and_run()
