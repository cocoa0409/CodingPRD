"""Routes: clock, billing run, patients, plans/procedures, coverages, verifications."""
from flask import Blueprint, request

import core
from core import db, err, base_record, touch, render_dt, parse_iso, parse_date, get_clock
import core as C
import web
from web import auth, get_body, ok, created, empty_ok, paginate

bp_a = Blueprint("bp_a", __name__)


def get_or_404(store, rid):
    rec = store.get(rid)
    if rec is None:
        err("ERR_NOT_FOUND", "Referenced resource does not exist")
    return rec


def patient_list_filter(role, user_id, records):
    """Restrict patient-owned collections for the Patient role."""
    if role != "Patient":
        return records
    req_pid = request.args.get("patient_id")
    if req_pid is not None and req_pid != user_id:
        err("ERR_NOT_RESOURCE_OWNER", "Patient may only list their own resources")
    return [r for r in records if r.get("patient_id") == user_id]


# ----------------------------------------------------------------------------
# Ops / clock
# ----------------------------------------------------------------------------
@bp_a.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth({"BillingManager"})
    body = get_body()
    to_iso = body.get("to_iso8601")
    if not isinstance(to_iso, str):
        err("ERR_INVALID_REQUEST", "to_iso8601 is required")
    try:
        db.clock = parse_iso(to_iso)
    except (ValueError, TypeError):
        err("ERR_INVALID_REQUEST", "to_iso8601 must be a valid ISO8601 timestamp")
    return empty_ok()


@bp_a.route("/billing/run", methods=["POST"])
def billing_run():
    auth({"BillingManager"})
    clock = get_clock()
    for m in db.memberships.values():
        if m["status"] == "CANCELLED":
            continue
        plan = db.membership_plans[m["membership_plan_id"]]
        if plan["billing_period"] == "MONTHLY":
            period_fee = C.round_half_up(plan["annual_fee_cents"], 12)
        else:
            period_fee = plan["annual_fee_cents"]
        overdue_boundary = parse_iso(
            parse_date(m["paid_through_date"]).isoformat() + "T00:00:00Z"
        ) + C.timedelta(days=core.MEMBERSHIP_GRACE_DAYS)
        if clock > overdue_boundary:
            m["balance_cents"] += period_fee
            m["past_due_periods"] += 1
            m["status"] = "PAST_DUE"
            if m["past_due_periods"] >= core.MAX_PAST_DUE_PERIODS:
                m["status"] = "CANCELLED"
            touch(m)
    # Claim aging + patient balances are computed on read; nothing to persist.
    return empty_ok()


# ----------------------------------------------------------------------------
# Patients
# ----------------------------------------------------------------------------
@bp_a.route("/patients", methods=["POST"])
def create_patient():
    auth({"FrontOffice", "BillingManager"})
    body = get_body()
    C.require_fields(body, ["full_name", "date_of_birth", "email"])
    rec = base_record()
    rec["full_name"] = C.require_str(body, "full_name")
    rec["date_of_birth"] = C.require_str(body, "date_of_birth")
    rec["email"] = C.require_str(body, "email")
    db.patients[rec["id"]] = rec
    return created(C.serialize_patient(rec))


@bp_a.route("/patients/<patient_id>", methods=["GET"])
def get_patient(patient_id):
    _, role = auth({"FrontOffice", "Biller", "BillingManager", "Patient"})
    rec = get_or_404(db.patients, patient_id)
    if role == "Patient" and request.headers.get("X-User-ID") != patient_id:
        err("ERR_NOT_RESOURCE_OWNER", "Patient may only read their own record")
    return ok(C.serialize_patient(rec))


# ----------------------------------------------------------------------------
# InsurancePlan
# ----------------------------------------------------------------------------
@bp_a.route("/insurance-plans", methods=["POST"])
def create_insurance_plan():
    auth({"BillingManager"})
    body = get_body()
    C.require_fields(body, ["payer_name", "plan_name"])
    rec = base_record()
    rec["payer_name"] = C.require_str(body, "payer_name")
    rec["plan_name"] = C.require_str(body, "plan_name")
    rec["annual_maximum_cents"] = C.optional_nonneg_int(body, "annual_maximum_cents", 150000)
    rec["deductible_cents"] = C.optional_nonneg_int(body, "deductible_cents", 5000)
    applies = body.get("deductible_applies_to", ["BASIC", "MAJOR"])
    if not isinstance(applies, list) or any(a not in ("PREVENTIVE", "BASIC", "MAJOR") for a in applies):
        err("ERR_INVALID_REQUEST", "deductible_applies_to must be a subset of PREVENTIVE/BASIC/MAJOR")
    rec["deductible_applies_to"] = applies
    rec["preventive_coinsurance_pct"] = C.optional_nonneg_int(body, "preventive_coinsurance_pct", 100)
    rec["basic_coinsurance_pct"] = C.optional_nonneg_int(body, "basic_coinsurance_pct", 80)
    rec["major_coinsurance_pct"] = C.optional_nonneg_int(body, "major_coinsurance_pct", 50)
    rec["cob_method"] = C.optional_enum(body, "cob_method", {"STANDARD", "NON_DUPLICATION"}, "STANDARD")
    db.insurance_plans[rec["id"]] = rec
    return created(C.serialize_insurance_plan(rec))


# ----------------------------------------------------------------------------
# Procedure
# ----------------------------------------------------------------------------
@bp_a.route("/procedures", methods=["POST"])
def create_procedure():
    auth({"BillingManager"})
    body = get_body()
    C.require_fields(body, ["cdt_code", "description", "category", "ucr_fee_cents"])
    rec = base_record()
    rec["cdt_code"] = C.require_str(body, "cdt_code")
    rec["description"] = C.require_str(body, "description")
    rec["category"] = C.require_enum(body, "category", {"PREVENTIVE", "BASIC", "MAJOR"})
    rec["ucr_fee_cents"] = C.require_nonneg_int(body, "ucr_fee_cents")
    freq = body.get("frequency_limit_per_year")
    if freq is not None:
        rec["frequency_limit_per_year"] = C.require_nonneg_int(body, "frequency_limit_per_year")
    else:
        rec["frequency_limit_per_year"] = None
    rec["requires_narrative"] = bool(body.get("requires_narrative", False))
    rec["requires_attachment"] = bool(body.get("requires_attachment", False))
    db.procedures[rec["id"]] = rec
    return created(C.serialize_procedure(rec))


# ----------------------------------------------------------------------------
# MembershipPlan
# ----------------------------------------------------------------------------
@bp_a.route("/membership-plans", methods=["POST"])
def create_membership_plan():
    auth({"BillingManager"})
    body = get_body()
    C.require_fields(body, ["name", "annual_fee_cents"])
    rec = base_record()
    rec["name"] = C.require_str(body, "name")
    rec["annual_fee_cents"] = C.require_nonneg_int(body, "annual_fee_cents")
    rec["billing_period"] = C.optional_enum(body, "billing_period", {"MONTHLY", "ANNUAL"}, "MONTHLY")
    rec["discount_pct"] = C.optional_nonneg_int(body, "discount_pct", 0)
    included = body.get("included_cdt_codes", [])
    if not isinstance(included, list):
        err("ERR_INVALID_REQUEST", "included_cdt_codes must be a list")
    rec["included_cdt_codes"] = included
    db.membership_plans[rec["id"]] = rec
    return created(C.serialize_membership_plan(rec))


# ----------------------------------------------------------------------------
# Coverage
# ----------------------------------------------------------------------------
def _dates_overlap_closed(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end


@bp_a.route("/coverages", methods=["POST"])
def create_coverage():
    auth({"FrontOffice", "BillingManager"})
    body = get_body()
    # existence (priority 3)
    C.require_fields(body, ["patient_id", "insurance_plan_id"])
    get_or_404(db.patients, body["patient_id"])
    get_or_404(db.insurance_plans, body["insurance_plan_id"])
    # well-formed (priority 5)
    C.require_fields(body, ["priority", "subscriber_id", "effective_date", "term_date"])
    priority = C.require_enum(body, "priority", {"PRIMARY", "SECONDARY"})
    subscriber_id = C.require_str(body, "subscriber_id")
    relationship = C.optional_enum(body, "relationship", {"SELF", "SPOUSE", "CHILD", "OTHER"}, "SELF")
    try:
        eff = parse_date(body["effective_date"])
        term = parse_date(body["term_date"])
    except (ValueError, TypeError):
        err("ERR_INVALID_REQUEST", "effective_date and term_date must be YYYY-MM-DD")
    # overlap (priority 18) — same patient + plan, closed intervals
    for c in db.coverages.values():
        if c["patient_id"] == body["patient_id"] and c["insurance_plan_id"] == body["insurance_plan_id"]:
            if _dates_overlap_closed(eff, term, parse_date(c["effective_date"]), parse_date(c["term_date"])):
                err("ERR_COVERAGE_OVERLAP", "Coverage overlaps an existing coverage for this patient and plan")
    rec = base_record()
    rec["patient_id"] = body["patient_id"]
    rec["insurance_plan_id"] = body["insurance_plan_id"]
    rec["priority"] = priority
    rec["subscriber_id"] = subscriber_id
    rec["relationship"] = relationship
    rec["effective_date"] = body["effective_date"]
    rec["term_date"] = body["term_date"]
    rec["benefits_used_cents"] = 0
    rec["deductible_met_cents"] = 0
    db.coverages[rec["id"]] = rec
    return created(C.serialize_coverage(rec))


@bp_a.route("/coverages/<coverage_id>", methods=["GET"])
def get_coverage(coverage_id):
    user_id, role = auth({"FrontOffice", "Biller", "BillingManager", "Patient"})
    rec = get_or_404(db.coverages, coverage_id)
    if role == "Patient" and rec["patient_id"] != user_id:
        err("ERR_NOT_RESOURCE_OWNER", "Patient may only read their own coverage")
    return ok(C.serialize_coverage(rec))


@bp_a.route("/coverages", methods=["GET"])
def list_coverages():
    user_id, role = auth({"FrontOffice", "Biller", "BillingManager", "Patient"})
    records = list(db.coverages.values())
    records = patient_list_filter(role, user_id, records)
    for field in ("patient_id", "insurance_plan_id", "priority"):
        v = request.args.get(field)
        if v is not None:
            records = [r for r in records if r.get(field) == v]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if C.coverage_status(r) == status]
    return paginate(records, C.serialize_coverage)


# ----------------------------------------------------------------------------
# Verification (OCC on Coverage.version)
# ----------------------------------------------------------------------------
@bp_a.route("/coverages/<coverage_id>/verifications", methods=["POST"])
def create_verification(coverage_id):
    auth({"FrontOffice", "BillingManager"})
    # existence: path coverage first
    coverage = get_or_404(db.coverages, coverage_id)
    body = get_body()
    # well-formed
    fields = ["expected_coverage_version", "verified_annual_maximum_cents", "verified_deductible_cents",
              "verified_preventive_pct", "verified_basic_pct", "verified_major_pct"]
    C.require_fields(body, fields)
    expected = C.require_nonneg_int(body, "expected_coverage_version")
    vam = C.require_nonneg_int(body, "verified_annual_maximum_cents")
    vded = C.require_nonneg_int(body, "verified_deductible_cents")
    vprev = C.require_nonneg_int(body, "verified_preventive_pct")
    vbasic = C.require_nonneg_int(body, "verified_basic_pct")
    vmajor = C.require_nonneg_int(body, "verified_major_pct")
    # OCC (priority 7)
    if expected != coverage["version"]:
        err("ERR_STALE_VERSION", "expected_coverage_version does not match current coverage version")
    rec = base_record()
    rec["coverage_id"] = coverage_id
    rec["verified_annual_maximum_cents"] = vam
    rec["verified_deductible_cents"] = vded
    rec["verified_preventive_pct"] = vprev
    rec["verified_basic_pct"] = vbasic
    rec["verified_major_pct"] = vmajor
    rec["verified_at"] = render_dt(get_clock())
    db.verifications[rec["id"]] = rec
    # supersede prior snapshot -> advance coverage version
    touch(coverage)
    return created(C.serialize_verification(rec))


@bp_a.route("/verifications/<verification_id>", methods=["GET"])
def get_verification(verification_id):
    auth({"FrontOffice", "Biller", "BillingManager"})
    rec = get_or_404(db.verifications, verification_id)
    return ok(C.serialize_verification(rec))


@bp_a.route("/verifications", methods=["GET"])
def list_verifications():
    auth({"FrontOffice", "Biller", "BillingManager"})
    records = list(db.verifications.values())
    cov = request.args.get("coverage_id")
    if cov is not None:
        records = [r for r in records if r["coverage_id"] == cov]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if C.verification_status(r) == status]
    return paginate(records, C.serialize_verification)
