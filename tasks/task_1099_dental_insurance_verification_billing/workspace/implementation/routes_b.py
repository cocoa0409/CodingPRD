"""Routes: preauthorizations, attachments, claims, payments, memberships."""
from flask import Blueprint, request

import core
import core as C
from core import db, err, base_record, touch, render_dt, parse_date, get_clock, timedelta
import web
from web import auth, get_body, ok, created, paginate
from routes_a import get_or_404, patient_list_filter

bp_b = Blueprint("bp_b", __name__)


# ----------------------------------------------------------------------------
# Shared procedure-line validation
# ----------------------------------------------------------------------------
def validate_procedures(procedures):
    if not isinstance(procedures, list) or len(procedures) == 0:
        err("ERR_INVALID_REQUEST", "procedures must be a non-empty list")
    for line in procedures:
        if not isinstance(line, dict):
            err("ERR_INVALID_REQUEST", "each procedure line must be an object")
        code = line.get("cdt_code")
        if not isinstance(code, str) or code == "":
            err("ERR_INVALID_REQUEST", "each procedure line requires a cdt_code")
        fee = line.get("billed_fee_cents")
        if isinstance(fee, bool) or not isinstance(fee, int) or fee < 0:
            err("ERR_INVALID_REQUEST", "billed_fee_cents must be a non-negative integer")


def check_procedure_codes_exist(procedures):
    for line in procedures:
        if C.proc_by_code(line["cdt_code"]) is None:
            err("ERR_NOT_FOUND", f"Procedure {line['cdt_code']} does not exist")


def any_line_requires(procedures, flag):
    for line in procedures:
        proc = C.proc_by_code(line["cdt_code"])
        if proc and proc.get(flag):
            return True
    return False


# ----------------------------------------------------------------------------
# PreAuthorization
# ----------------------------------------------------------------------------
@bp_b.route("/preauthorizations", methods=["POST"])
def create_preauth():
    auth({"Biller", "BillingManager"})
    body = get_body()
    C.require_fields(body, ["patient_id", "coverage_id", "procedures"])
    get_or_404(db.patients, body["patient_id"])
    get_or_404(db.coverages, body["coverage_id"])
    validate_procedures(body["procedures"])
    check_procedure_codes_exist(body["procedures"])
    rec = base_record()
    rec["patient_id"] = body["patient_id"]
    rec["coverage_id"] = body["coverage_id"]
    rec["procedures"] = body["procedures"]
    rec["narrative"] = body.get("narrative")
    rec["status"] = "DRAFT"
    rec["estimated_benefit_cents"] = 0
    rec["approved_amount_cents"] = None
    rec["submitted_at"] = None
    db.preauthorizations[rec["id"]] = rec
    return created(C.serialize_preauth(rec))


@bp_b.route("/preauthorizations/<preauth_id>", methods=["GET"])
def get_preauth(preauth_id):
    auth({"FrontOffice", "Biller", "BillingManager"})
    rec = get_or_404(db.preauthorizations, preauth_id)
    return ok(C.serialize_preauth(rec))


@bp_b.route("/preauthorizations", methods=["GET"])
def list_preauth():
    auth({"FrontOffice", "Biller", "BillingManager"})
    records = list(db.preauthorizations.values())
    for field in ("patient_id", "coverage_id", "status"):
        v = request.args.get(field)
        if v is not None:
            records = [r for r in records if r.get(field) == v]
    return paginate(records, C.serialize_preauth)


def compute_preauth_estimate(rec):
    coverage = db.coverages[rec["coverage_id"]]
    plan = db.insurance_plans[coverage["insurance_plan_id"]]
    snapshot = C.snapshot_for_coverage(coverage)
    return C.benefit_estimate(rec["procedures"], snapshot, coverage, plan)


@bp_b.route("/preauthorizations/<preauth_id>/submit", methods=["POST"])
def submit_preauth(preauth_id):
    auth({"Biller", "BillingManager"})
    rec = get_or_404(db.preauthorizations, preauth_id)
    if rec["status"] not in ("DRAFT", "PENDED"):
        err("ERR_INVALID_STATE", "PreAuthorization can only be submitted from DRAFT or PENDED")
    if not rec["procedures"]:
        err("ERR_INVALID_REQUEST", "procedures must be non-empty")
    if any_line_requires(rec["procedures"], "requires_attachment"):
        if C.preauth_attachment_count(rec["id"]) < 1:
            err("ERR_MISSING_ATTACHMENT", "An attachment is required for one of the procedures")
    rec["estimated_benefit_cents"] = compute_preauth_estimate(rec)
    if rec["submitted_at"] is None:
        rec["submitted_at"] = render_dt(get_clock())
    rec["status"] = "SUBMITTED"
    touch(rec)
    return ok(C.serialize_preauth(rec))


@bp_b.route("/preauthorizations/<preauth_id>/decision", methods=["POST"])
def decide_preauth(preauth_id):
    auth({"Biller", "BillingManager"})
    rec = get_or_404(db.preauthorizations, preauth_id)
    body = get_body()
    outcome = C.require_enum(body, "outcome", {"APPROVED", "DENIED", "PENDED"})
    if rec["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", "PreAuthorization can only be decided from SUBMITTED")
    if outcome == "APPROVED":
        rec["approved_amount_cents"] = rec["estimated_benefit_cents"]
        rec["status"] = "APPROVED"
    elif outcome == "DENIED":
        rec["status"] = "DENIED"
    else:
        rec["status"] = "PENDED"
    touch(rec)
    return ok(C.serialize_preauth(rec))


# ----------------------------------------------------------------------------
# Attachment (polymorphic)
# ----------------------------------------------------------------------------
@bp_b.route("/attachments", methods=["POST"])
def create_attachment():
    auth({"FrontOffice", "Biller", "BillingManager"})
    body = get_body()
    claim_id = body.get("claim_id")
    preauth_id = body.get("preauth_id")
    # existence (priority 3) for any provided target
    if claim_id is not None:
        get_or_404(db.claims, claim_id)
    if preauth_id is not None:
        get_or_404(db.preauthorizations, preauth_id)
    # well-formed (priority 5)
    C.require_fields(body, ["kind", "filename"])
    kind = C.require_enum(body, "kind", {"XRAY", "PERIO_CHART", "NARRATIVE", "PHOTO", "OTHER"})
    filename = C.require_str(body, "filename")
    # exactly one target (priority 6)
    if (claim_id is None) == (preauth_id is None):
        err("ERR_ATTACHMENT_TARGET_REQUIRED", "Exactly one of claim_id or preauth_id is required")
    rec = base_record(common_fields=False)
    rec["claim_id"] = claim_id
    rec["preauth_id"] = preauth_id
    rec["kind"] = kind
    rec["filename"] = filename
    rec["note"] = body.get("note")
    db.attachments[rec["id"]] = rec
    return created(C.serialize_attachment(rec))


@bp_b.route("/attachments/<attachment_id>", methods=["GET"])
def get_attachment(attachment_id):
    auth({"FrontOffice", "Biller", "BillingManager"})
    rec = get_or_404(db.attachments, attachment_id)
    return ok(C.serialize_attachment(rec))


@bp_b.route("/attachments", methods=["GET"])
def list_attachments():
    auth({"FrontOffice", "Biller", "BillingManager"})
    records = list(db.attachments.values())
    for field in ("claim_id", "preauth_id", "kind"):
        v = request.args.get(field)
        if v is not None:
            records = [r for r in records if r.get(field) == v]
    return paginate(records, C.serialize_attachment)


# ----------------------------------------------------------------------------
# Claim
# ----------------------------------------------------------------------------
def _new_claim_defaults(rec):
    rec["status"] = "DRAFT"
    rec["estimated_insurance_cents"] = 0
    rec["estimated_patient_portion_cents"] = 0
    rec["paid_insurance_cents"] = 0
    rec["final_patient_portion_cents"] = 0
    rec["submitted_by_user_id"] = None
    rec["submitted_at"] = None
    rec["adjudicated_at"] = None
    rec["appeal_count"] = 0
    rec["_cov_benefit"] = 0
    rec["_cov_deductible"] = 0


@bp_b.route("/claims", methods=["POST"])
def create_claim():
    auth({"Biller", "BillingManager"})
    body = get_body()
    C.require_fields(body, ["patient_id", "coverage_id", "procedures", "service_date"])
    get_or_404(db.patients, body["patient_id"])
    get_or_404(db.coverages, body["coverage_id"])
    if body.get("preauth_id") is not None:
        get_or_404(db.preauthorizations, body["preauth_id"])
    if body.get("primary_claim_id") is not None:
        get_or_404(db.claims, body["primary_claim_id"])
    validate_procedures(body["procedures"])
    check_procedure_codes_exist(body["procedures"])
    try:
        parse_date(body["service_date"])
    except (ValueError, TypeError):
        err("ERR_INVALID_REQUEST", "service_date must be YYYY-MM-DD")
    rec = base_record()
    rec["patient_id"] = body["patient_id"]
    rec["coverage_id"] = body["coverage_id"]
    rec["preauth_id"] = body.get("preauth_id")
    rec["primary_claim_id"] = body.get("primary_claim_id")
    rec["procedures"] = body["procedures"]
    rec["narrative"] = body.get("narrative")
    rec["service_date"] = body["service_date"]
    _new_claim_defaults(rec)
    db.claims[rec["id"]] = rec
    return created(C.serialize_claim(rec))


@bp_b.route("/claims/<claim_id>", methods=["GET"])
def get_claim(claim_id):
    user_id, role = auth({"Biller", "BillingManager", "Patient"})
    rec = get_or_404(db.claims, claim_id)
    if role == "Patient" and rec["patient_id"] != user_id:
        err("ERR_NOT_RESOURCE_OWNER", "Patient may only read their own claim")
    return ok(C.serialize_claim(rec))


@bp_b.route("/claims", methods=["GET"])
def list_claims():
    user_id, role = auth({"Biller", "BillingManager", "Patient"})
    records = list(db.claims.values())
    records = patient_list_filter(role, user_id, records)
    for field in ("patient_id", "coverage_id", "preauth_id", "primary_claim_id", "status"):
        v = request.args.get(field)
        if v is not None:
            records = [r for r in records if r.get(field) == v]
    bucket = request.args.get("aging_bucket")
    if bucket is not None:
        records = [r for r in records if C.aging_bucket(C.claim_aging_days(r)) == bucket]
    return paginate(records, C.serialize_claim)


def _frequency_check(claim):
    this_date = parse_date(claim["service_date"])
    window_start = this_date - timedelta(days=core.FREQUENCY_WINDOW_DAYS)
    for line in claim["procedures"]:
        proc = C.proc_by_code(line["cdt_code"])
        if proc["frequency_limit_per_year"] is None:
            continue
        limit = proc["frequency_limit_per_year"]
        count = 0
        for other in db.claims.values():
            if other["id"] == claim["id"]:
                continue
            if other["patient_id"] != claim["patient_id"]:
                continue
            if other["status"] not in ("SUBMITTED", "ADJUDICATED", "APPEALED", "CLOSED"):
                continue
            od = parse_date(other["service_date"])
            if not (window_start <= od <= this_date):
                continue
            for oline in other["procedures"]:
                if oline["cdt_code"] == line["cdt_code"]:
                    count += 1
        if count >= limit:
            err("ERR_FREQUENCY_LIMIT_EXCEEDED",
                f"Frequency limit exceeded for procedure {line['cdt_code']}")


@bp_b.route("/claims/<claim_id>/submit", methods=["POST"])
def submit_claim(claim_id):
    user_id, _ = auth({"Biller", "BillingManager"})
    claim = get_or_404(db.claims, claim_id)
    if claim["status"] != "DRAFT":
        err("ERR_INVALID_STATE", "Only a DRAFT claim can be submitted")
    coverage = db.coverages[claim["coverage_id"]]
    plan = db.insurance_plans[coverage["insurance_plan_id"]]
    # 1. coverage active
    if C.coverage_status(coverage) != "ACTIVE":
        err("ERR_COVERAGE_INACTIVE", "Billing coverage is not ACTIVE")
    # 2. verification exists
    ver = C.latest_verification(coverage["id"])
    if ver is None:
        err("ERR_VERIFICATION_REQUIRED", "Coverage has no verification record")
    # 3. verification not expired
    if C.verification_status(ver) == "EXPIRED":
        err("ERR_VERIFICATION_EXPIRED", "The coverage's latest verification has expired")
    # 4. frequency
    _frequency_check(claim)
    # 5. narrative
    if any_line_requires(claim["procedures"], "requires_narrative"):
        if not claim.get("narrative"):
            err("ERR_MISSING_NARRATIVE", "A narrative is required for one of the procedures")
    # 6. attachment
    if any_line_requires(claim["procedures"], "requires_attachment"):
        has = any(a.get("claim_id") == claim["id"] for a in db.attachments.values())
        if not has:
            err("ERR_MISSING_ATTACHMENT", "An attachment is required for one of the procedures")
    # 7. secondary primary adjudicated
    if claim["primary_claim_id"] is not None:
        primary = db.claims[claim["primary_claim_id"]]
        if primary["status"] not in ("ADJUDICATED", "DENIED", "CLOSED"):
            err("ERR_PRIMARY_CLAIM_NOT_ADJUDICATED",
                "Primary claim must be adjudicated before submitting the secondary claim")
    # 8. annual maximum
    snapshot = C.snapshot_for_coverage(coverage)
    if snapshot["max"] - coverage["benefits_used_cents"] <= 0:
        err("ERR_ANNUAL_MAXIMUM_EXCEEDED", "No remaining annual maximum on the coverage")
    # compute estimate
    normal = C.benefit_estimate(claim["procedures"], snapshot, coverage, plan)
    if claim["primary_claim_id"] is not None:
        estimated = C.cob_secondary_benefit(claim, coverage, plan, normal)
    else:
        estimated = normal
    claim["estimated_insurance_cents"] = estimated
    claim["estimated_patient_portion_cents"] = C.claim_total_billed(claim) - estimated
    claim["submitted_by_user_id"] = user_id
    claim["submitted_at"] = render_dt(get_clock())
    claim["status"] = "SUBMITTED"
    touch(claim)
    return ok(C.serialize_claim(claim))


@bp_b.route("/claims/<claim_id>/appeal", methods=["POST"])
def appeal_claim(claim_id):
    auth({"Biller", "BillingManager"})
    claim = get_or_404(db.claims, claim_id)
    if claim["status"] not in ("DENIED", "ADJUDICATED") or claim["appeal_count"] >= core.APPEAL_LIMIT:
        err("ERR_APPEAL_NOT_ALLOWED", "Claim is not appealable or the appeal limit has been reached")
    claim["appeal_count"] += 1
    claim["status"] = "APPEALED"
    touch(claim)
    return ok(C.serialize_claim(claim))


# ----------------------------------------------------------------------------
# Payment
# ----------------------------------------------------------------------------
def _validate_eob_lines(lines):
    if not isinstance(lines, list):
        err("ERR_INVALID_REQUEST", "eob_lines must be a list")
    for l in lines:
        if not isinstance(l, dict):
            err("ERR_INVALID_REQUEST", "each eob line must be an object")
        for f in ("paid_cents", "allowed_cents", "deductible_applied_cents"):
            v = l.get(f, 0)
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                err("ERR_INVALID_REQUEST", f"eob line {f} must be a non-negative integer")


def _apply_insurance(claim, coverage, paid, ded, is_denial, snapshot_holder):
    total = C.claim_total_billed(claim)
    snapshot_holder["prev_paid"] = claim["paid_insurance_cents"]
    snapshot_holder["prev_final"] = claim["final_patient_portion_cents"]
    snapshot_holder["prev_cov_benefit"] = claim["_cov_benefit"]
    snapshot_holder["prev_cov_deductible"] = claim["_cov_deductible"]
    snapshot_holder["prev_adjudicated_at"] = claim["adjudicated_at"]
    # reverse this claim's prior contribution, apply new (compensating on the pool)
    new_benefit = 0 if is_denial else paid
    new_ded = 0 if is_denial else ded
    coverage["benefits_used_cents"] += (new_benefit - claim["_cov_benefit"])
    coverage["deductible_met_cents"] += (new_ded - claim["_cov_deductible"])
    claim["_cov_benefit"] = new_benefit
    claim["_cov_deductible"] = new_ded
    if is_denial:
        claim["paid_insurance_cents"] = 0
        claim["final_patient_portion_cents"] = total
        claim["status"] = "DENIED"
    else:
        claim["paid_insurance_cents"] = paid
        claim["final_patient_portion_cents"] = total - paid
        claim["status"] = "ADJUDICATED"
    claim["adjudicated_at"] = render_dt(get_clock())
    touch(claim)
    touch(coverage)


@bp_b.route("/payments", methods=["POST"])
def create_payment():
    user_id, role = auth({"Biller", "BillingManager", "Patient"})
    body = get_body()
    # existence (priority 3): patient_id then claim_id (left-to-right)
    if body.get("patient_id") is not None:
        get_or_404(db.patients, body["patient_id"])
    if body.get("claim_id") is not None:
        get_or_404(db.claims, body["claim_id"])
    # ownership (priority 4)
    if role == "Patient":
        if body.get("patient_id") != user_id:
            err("ERR_NOT_RESOURCE_OWNER", "Patient may only pay on their own behalf")
        if body.get("claim_id") is not None and db.claims[body["claim_id"]]["patient_id"] != user_id:
            err("ERR_NOT_RESOURCE_OWNER", "Patient may only pay their own claim")
    # well-formed (priority 5)
    C.require_fields(body, ["patient_id", "payer_type", "amount_cents", "claim_id"])
    payer_type = C.require_enum(body, "payer_type", {"INSURANCE", "PATIENT"})
    amount = C.require_nonneg_int(body, "amount_cents")
    claim = db.claims[body["claim_id"]]
    is_denial = bool(body.get("is_denial", False))

    if payer_type == "INSURANCE":
        eob_lines = body.get("eob_lines")
        if not is_denial:
            if eob_lines is None:
                err("ERR_INVALID_REQUEST", "eob_lines is required for an insurance payment")
            _validate_eob_lines(eob_lines)
        elif eob_lines is not None:
            _validate_eob_lines(eob_lines)
        # SoD (priority 9)
        if user_id == claim.get("submitted_by_user_id"):
            err("ERR_SEGREGATION_OF_DUTIES", "The claim submitter may not post its insurance payment")
        # postable state + patient match (priority 10)
        if claim["status"] not in ("SUBMITTED", "APPEALED") or claim["patient_id"] != body["patient_id"]:
            err("ERR_PAYMENT_CLAIM_MISMATCH", "Claim is not in a postable state or patient mismatch")
        paid = sum(int(l.get("paid_cents", 0)) for l in (eob_lines or []))
        ded = sum(int(l.get("deductible_applied_cents", 0)) for l in (eob_lines or []))
        coverage = db.coverages[claim["coverage_id"]]
        rec = base_record()
        snap = {}
        _apply_insurance(claim, coverage, paid, ded, is_denial, snap)
        rec["_snapshot"] = snap
    else:  # PATIENT
        # postable state + patient match (priority 10)
        if claim["status"] not in ("ADJUDICATED", "DENIED") or claim["patient_id"] != body["patient_id"]:
            err("ERR_PAYMENT_CLAIM_MISMATCH", "Claim is not in a payable state or patient mismatch")
        # overpayment (priority 21)
        current_paid = C.claim_patient_paid(claim["id"])
        if amount + current_paid > claim["final_patient_portion_cents"]:
            err("ERR_OVERPAYMENT", "Patient payment exceeds the outstanding patient portion")
        rec = base_record()

    rec["claim_id"] = body["claim_id"]
    rec["patient_id"] = body["patient_id"]
    rec["payer_type"] = payer_type
    rec["amount_cents"] = amount
    rec["eob_lines"] = body.get("eob_lines")
    rec["is_denial"] = is_denial
    rec["status"] = "POSTED"
    rec["posted_at"] = render_dt(get_clock())
    db.payments[rec["id"]] = rec

    if payer_type == "PATIENT":
        if C.claim_patient_paid(claim["id"]) == claim["final_patient_portion_cents"]:
            rec["_closed_from"] = claim["status"]
            claim["status"] = "CLOSED"
            touch(claim)

    return created(C.serialize_payment(rec))


@bp_b.route("/payments/<payment_id>", methods=["GET"])
def get_payment(payment_id):
    user_id, role = auth({"Biller", "BillingManager", "Patient"})
    rec = get_or_404(db.payments, payment_id)
    if role == "Patient" and rec["patient_id"] != user_id:
        err("ERR_NOT_RESOURCE_OWNER", "Patient may only read their own payment")
    return ok(C.serialize_payment(rec))


@bp_b.route("/payments", methods=["GET"])
def list_payments():
    user_id, role = auth({"Biller", "BillingManager", "Patient"})
    records = list(db.payments.values())
    records = patient_list_filter(role, user_id, records)
    for field in ("claim_id", "patient_id", "payer_type", "status"):
        v = request.args.get(field)
        if v is not None:
            records = [r for r in records if r.get(field) == v]
    return paginate(records, C.serialize_payment)


@bp_b.route("/payments/<payment_id>/reverse", methods=["POST"])
def reverse_payment(payment_id):
    auth({"BillingManager"})
    rec = get_or_404(db.payments, payment_id)
    if rec["status"] != "POSTED":
        err("ERR_INVALID_STATE", "Only a POSTED payment can be reversed")
    claim = db.claims.get(rec["claim_id"]) if rec.get("claim_id") else None
    if rec["payer_type"] == "INSURANCE" and claim is not None:
        snap = rec["_snapshot"]
        coverage = db.coverages[claim["coverage_id"]]
        coverage["benefits_used_cents"] += (snap["prev_cov_benefit"] - claim["_cov_benefit"])
        coverage["deductible_met_cents"] += (snap["prev_cov_deductible"] - claim["_cov_deductible"])
        claim["_cov_benefit"] = snap["prev_cov_benefit"]
        claim["_cov_deductible"] = snap["prev_cov_deductible"]
        claim["paid_insurance_cents"] = snap["prev_paid"]
        claim["final_patient_portion_cents"] = snap["prev_final"]
        claim["adjudicated_at"] = snap["prev_adjudicated_at"]
        claim["status"] = "SUBMITTED"
        touch(claim)
        touch(coverage)
    elif rec["payer_type"] == "PATIENT" and claim is not None:
        if claim["status"] == "CLOSED":
            claim["status"] = rec.get("_closed_from", "ADJUDICATED")
            touch(claim)
    rec["status"] = "REVERSED"
    touch(rec)
    return ok(C.serialize_payment(rec))


# ----------------------------------------------------------------------------
# Membership
# ----------------------------------------------------------------------------
def _intervals_overlap_halfopen(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


@bp_b.route("/memberships", methods=["POST"])
def create_membership():
    user_id, role = auth({"FrontOffice", "BillingManager", "Patient"})
    body = get_body()
    C.require_fields(body, ["patient_id", "membership_plan_id"])
    get_or_404(db.patients, body["patient_id"])
    get_or_404(db.membership_plans, body["membership_plan_id"])
    if role == "Patient" and body.get("patient_id") != user_id:
        err("ERR_NOT_RESOURCE_OWNER", "Patient may only enroll themselves")
    C.require_fields(body, ["period_start", "period_end"])
    try:
        start = parse_date(body["period_start"])
        end = parse_date(body["period_end"])
    except (ValueError, TypeError):
        err("ERR_INVALID_REQUEST", "period_start and period_end must be YYYY-MM-DD")
    for m in db.memberships.values():
        if m["patient_id"] == body["patient_id"] and m["status"] != "CANCELLED":
            if _intervals_overlap_halfopen(start, end, parse_date(m["period_start"]), parse_date(m["period_end"])):
                err("ERR_MEMBERSHIP_OVERLAP", "Membership overlaps an existing membership for this patient")
    rec = base_record()
    rec["patient_id"] = body["patient_id"]
    rec["membership_plan_id"] = body["membership_plan_id"]
    rec["status"] = "ACTIVE"
    rec["enrolled_at"] = render_dt(get_clock())
    rec["period_start"] = body["period_start"]
    rec["period_end"] = body["period_end"]
    rec["paid_through_date"] = body["period_start"]
    rec["balance_cents"] = 0
    rec["past_due_periods"] = 0
    db.memberships[rec["id"]] = rec
    return created(C.serialize_membership(rec))


@bp_b.route("/memberships/<membership_id>", methods=["GET"])
def get_membership(membership_id):
    user_id, role = auth({"FrontOffice", "BillingManager", "Patient"})
    rec = get_or_404(db.memberships, membership_id)
    if role == "Patient" and rec["patient_id"] != user_id:
        err("ERR_NOT_RESOURCE_OWNER", "Patient may only read their own membership")
    return ok(C.serialize_membership(rec))


@bp_b.route("/memberships", methods=["GET"])
def list_memberships():
    user_id, role = auth({"FrontOffice", "BillingManager", "Patient"})
    records = list(db.memberships.values())
    records = patient_list_filter(role, user_id, records)
    for field in ("patient_id", "membership_plan_id", "status"):
        v = request.args.get(field)
        if v is not None:
            records = [r for r in records if r.get(field) == v]
    return paginate(records, C.serialize_membership)


@bp_b.route("/memberships/<membership_id>/pay", methods=["POST"])
def pay_membership(membership_id):
    user_id, role = auth({"Patient", "FrontOffice", "BillingManager"})
    rec = get_or_404(db.memberships, membership_id)
    if role == "Patient" and rec["patient_id"] != user_id:
        err("ERR_NOT_RESOURCE_OWNER", "Patient may only pay their own membership")
    body = get_body()
    amount = C.require_nonneg_int(body, "amount_cents")
    if rec["status"] == "CANCELLED" or rec["balance_cents"] <= 0:
        err("ERR_MEMBERSHIP_NOT_PAYABLE", "Membership has no balance or is cancelled")
    plan = db.membership_plans[rec["membership_plan_id"]]
    rec["balance_cents"] -= amount
    rec["paid_through_date"] = C.advance_period(parse_date(rec["paid_through_date"]), plan["billing_period"]).isoformat()
    rec["past_due_periods"] = 0
    rec["status"] = "ACTIVE"
    touch(rec)
    return ok(C.serialize_membership(rec))
