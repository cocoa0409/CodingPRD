"""Enrollment routes (PRD §3.2, §3.4, §3.7, §3.9)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import get_user_context, require_role
from response import success
from services import dates, validate, calc, domain
from services.listing import paginate_and_render
from services.serialize import enrollment_view

bp = Blueprint("enrollments", __name__)

ALL_ROLES = ("Registrar", "Bursar", "Student")


def _new_enrollment_ledger_fields():
    return {
        "installment_count": None,
        "down_payment_pct": None,
        "plan_fee_cents": None,
        "gross_charges_cents": 0,
        "total_aid_cents": 0,
        "net_after_aid_cents": 0,
        "down_payment_cents": 0,
        "financed_principal_cents": 0,
        "scheduled_balance_cents": 0,
        "paid_principal_cents": 0,
        "late_fee_balance_cents": 0,
        "delinquent_installment_count": 0,
        "down_payment_collected": False,
    }


@bp.route("/institutions/enrollments", methods=["POST"])
def create_enrollment():
    _, role = get_user_context()
    require_role(role, ("Registrar",))
    body = validate.get_body()

    student_id = validate.require_string(body, "student_id")
    student = db.students.get(student_id)
    if student is None:
        raise err("ERR_NOT_FOUND", "Student not found")

    term_id = validate.require_string(body, "term_id")
    term = db.terms.get(term_id)
    if term is None:
        raise err("ERR_NOT_FOUND", "Term not found")

    plan_template_id = validate.require_string(body, "plan_template_id")
    template = db.plan_templates.get(plan_template_id)
    if template is None:
        raise err("ERR_NOT_FOUND", "Plan template not found")

    autopay_enabled = validate.optional_bool(body, "autopay_enabled", False)

    record = db.stamp_new({
        "institution_id": student["institution_id"],
        "student_id": student_id,
        "term_id": term_id,
        "plan_template_id": plan_template_id,
        "autopay_enabled": autopay_enabled,
        "status": "PENDING",
    })
    record.update(_new_enrollment_ledger_fields())
    db.enrollments[record["id"]] = record
    return success(enrollment_view(record), status=201)


@bp.route("/institutions/enrollments/<enrollment_id>", methods=["GET"])
def get_enrollment(enrollment_id):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    record = db.enrollments.get(enrollment_id)
    if record is None:
        raise err("ERR_NOT_FOUND", "Enrollment not found")
    return success(enrollment_view(record), status=200)


@bp.route("/institutions/enrollments", methods=["GET"])
def list_enrollments():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    student_id = request.args.get("student_id")
    term_id = request.args.get("term_id")
    plan_template_id = request.args.get("plan_template_id")
    status = request.args.get("status")
    records = list(db.enrollments.values())
    if student_id is not None:
        records = [r for r in records if r["student_id"] == student_id]
    if term_id is not None:
        records = [r for r in records if r["term_id"] == term_id]
    if plan_template_id is not None:
        records = [r for r in records if r["plan_template_id"] == plan_template_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return paginate_and_render(records, enrollment_view)


@bp.route("/institutions/enrollments/<enrollment_id>/activate", methods=["POST"])
def activate_enrollment(enrollment_id):
    _, role = get_user_context()
    require_role(role, ("Registrar",))
    enrollment = db.enrollments.get(enrollment_id)
    if enrollment is None:
        raise err("ERR_NOT_FOUND", "Enrollment not found")

    body = validate.get_body()

    # State check first (PRD §3.10).
    if enrollment["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Enrollment must be PENDING to activate")

    student = db.students[enrollment["student_id"]]
    term = db.terms[enrollment["term_id"]]
    template = db.plan_templates[enrollment["plan_template_id"]]
    institution = db.institutions[enrollment["institution_id"]]

    # Ledger up to date before precondition reads.
    domain.recompute_gross_and_aid(enrollment)

    # PRD §3.10 activation ordering: student-hold -> term-not-open ->
    # outside-window -> template-retired -> autopay-required ->
    # no-charges-to-finance -> stale-version.
    # (Template-retired sits among the cross-entity guards; PRD §3.4 lists it
    #  with the other preconditions. We evaluate it after the temporal checks
    #  and before autopay, matching the §3.4 prose order.)
    if student["has_active_hold"]:
        raise err("ERR_STUDENT_ON_HOLD", "Student is on hold")

    if term["status"] != "OPEN":
        raise err("ERR_TERM_NOT_OPEN", "Financing term is not OPEN")

    clock = dates.parse_iso(institution["clock_utc"])
    enroll_open = dates.parse_iso(term["enroll_open"])
    enroll_close = dates.parse_iso(term["enroll_close"])
    if not (enroll_open <= clock <= enroll_close):
        raise err("ERR_OUTSIDE_ENROLL_WINDOW", "Clock outside enrollment window")

    if template["status"] != "ACTIVE":
        raise err("ERR_TEMPLATE_RETIRED", "Plan template is retired")

    # PRD §3.10 enumerates autopay-required ahead of charges-to-finance.
    if template["autopay_required"] and not enrollment["autopay_enabled"]:
        raise err("ERR_AUTOPAY_REQUIRED", "Plan template requires autopay")

    if enrollment["gross_charges_cents"] <= 0:
        raise err("ERR_NO_CHARGES_TO_FINANCE", "No charges to finance")

    # OCC version guard on the transition (PRD §2.7, §3.10).
    _check_version(enrollment, body)

    # --- Apply activation (atomic) ---
    enrollment["installment_count"] = template["installment_count"]
    enrollment["down_payment_pct"] = template["down_payment_pct"]
    enrollment["plan_fee_cents"] = template["plan_fee_cents"]
    enrollment["status"] = "ACTIVE"

    total_days = domain.term_total_days(term)
    term_start = dates.parse_iso(term["term_start"])
    net = enrollment["net_after_aid_cents"]

    down_payment_cents, financed_principal, rows = calc.installment_schedule(
        net, template["down_payment_pct"], template["installment_count"],
        total_days, term_start, dates.add_days)

    enrollment["down_payment_cents"] = down_payment_cents
    enrollment["financed_principal_cents"] = financed_principal

    for (seq, amount, due_date) in rows:
        inst = db.stamp_new({
            "institution_id": enrollment["institution_id"],
            "enrollment_id": enrollment["id"],
            "sequence_index": seq,
            "due_date": dates.to_iso(due_date),
            "amount_cents": amount,
            "paid_amount_cents": 0,
            "status": "SCHEDULED",
        })
        db.installments[inst["id"]] = inst

    domain.recompute_scheduled_balance(enrollment)
    domain.recompute_paid_principal(enrollment)
    db.touch(enrollment)  # increments version by 1
    return success(enrollment_view(enrollment), status=200)


@bp.route("/institutions/enrollments/<enrollment_id>/withdraw", methods=["POST"])
def withdraw_enrollment(enrollment_id):
    _, role = get_user_context()
    require_role(role, ("Registrar",))
    enrollment = db.enrollments.get(enrollment_id)
    if enrollment is None:
        raise err("ERR_NOT_FOUND", "Enrollment not found")

    body = validate.get_body()

    if enrollment["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Enrollment must be ACTIVE to withdraw")

    effective_raw = body.get("effective_date")
    effective_date = dates.parse_iso(effective_raw)
    if effective_date is None:
        raise err("ERR_INVALID_REQUEST", "effective_date must be a valid date")

    _check_version(enrollment, body)

    term = db.terms[enrollment["term_id"]]
    institution = db.institutions[enrollment["institution_id"]]
    term_start = dates.parse_iso(term["term_start"])
    term_end = dates.parse_iso(term["term_end"])
    total_days = domain.term_total_days(term)

    # Clamp effective_date to [term_start, term_end]; days_elapsed = floor + 1.
    clamped = effective_date
    if clamped < term_start:
        clamped = term_start
    elif clamped > term_end:
        clamped = term_end
    days_elapsed = (dates.day_number(clamped) - dates.day_number(term_start)) + 1

    variant = institution["refund_policy"]
    retained, net_owed, refund = calc.refund_proration(
        variant,
        enrollment["gross_charges_cents"],
        enrollment["total_aid_cents"],
        enrollment["paid_principal_cents"],
        days_elapsed,
        total_days,
    )

    withdrawal = db.stamp_new({
        "institution_id": enrollment["institution_id"],
        "enrollment_id": enrollment["id"],
        "effective_date": dates.to_iso(effective_date),
        "variant_used": variant,
        "retained_charges_cents": retained,
        "net_owed_after_withdrawal_cents": net_owed,
        "refund_to_student_cents": refund,
    })
    db.withdrawals[withdrawal["id"]] = withdrawal

    # Transition to WITHDRAWN; cancelled installments are excluded from
    # scheduled_balance via the WITHDRAWN parent. Late fees survive.
    enrollment["status"] = "WITHDRAWN"
    # Hop 3: delinquent count -> 0; release ACTIVE hold for this enrollment.
    enrollment["delinquent_installment_count"] = 0
    domain.release_hold_for_enrollment(enrollment)
    # Scheduled balance no longer counts the cancelled installments.
    enrollment["scheduled_balance_cents"] = 0
    db.touch(enrollment)  # increments version by 1
    return success(enrollment_view(enrollment), status=200)


@bp.route("/institutions/enrollments/<enrollment_id>/run-delinquency", methods=["POST"])
def run_delinquency(enrollment_id):
    _, role = get_user_context()
    require_role(role, ("Registrar",))
    enrollment = db.enrollments.get(enrollment_id)
    if enrollment is None:
        raise err("ERR_NOT_FOUND", "Enrollment not found")

    institution = db.institutions[enrollment["institution_id"]]
    template = db.plan_templates[enrollment["plan_template_id"]]
    grace = template["late_fee_grace_days"]
    clock = dates.parse_iso(institution["clock_utc"])
    clock_day = dates.day_number(clock)

    changed = False
    insts = sorted(domain.installments_of(enrollment_id),
                   key=lambda i: i["sequence_index"])
    for inst in insts:
        if inst["status"] != "SCHEDULED":
            continue
        due_day = dates.day_number(dates.parse_iso(inst["due_date"]))
        # SCHEDULED -> OVERDUE when clock_day > due_day + grace and unpaid.
        if clock_day > due_day + grace and inst["paid_amount_cents"] < inst["amount_cents"]:
            inst["status"] = "OVERDUE"
            db.touch(inst)
            changed = True
            # late_fee_assessment for this newly-OVERDUE installment.
            overdue = inst["amount_cents"] - inst["paid_amount_cents"]
            days_late = clock_day - due_day
            fee_amount = calc.late_fee_amount(
                overdue, days_late, enrollment["late_fee_balance_cents"])
            late_fee = db.stamp_new({
                "institution_id": enrollment["institution_id"],
                "enrollment_id": enrollment["id"],
                "installment_id": inst["id"],
                "days_late": days_late,
                "amount_cents": fee_amount,
                "status": "ASSESSED",
            })
            db.late_fees[late_fee["id"]] = late_fee
            domain.recompute_late_fee_balance(enrollment)
            # Increment delinquent count.
            enrollment["delinquent_installment_count"] += 1
            # Evaluate delinquency thresholds (may raise a hold).
            domain.delinquency_evaluation(enrollment)

    if changed:
        domain.recompute_scheduled_balance(enrollment)
        db.touch(enrollment)
    return success(enrollment_view(enrollment), status=200)


def _check_version(enrollment, body):
    """OCC check: expected_enrollment_version must equal current version."""
    expected = body.get("expected_enrollment_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err("ERR_INVALID_REQUEST",
                  "expected_enrollment_version is required and must be an integer")
    if expected != enrollment["version"]:
        raise err("ERR_STALE_VERSION", "Enrollment version is stale")
