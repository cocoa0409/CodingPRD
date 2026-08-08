"""The case balance, payment plans and collections (PRD 3.9)."""
from flask import Blueprint

import calc
import domain
import envelope
import guards
import nav
import pconst
import projections
from errors import ApiError
from store import db, now, sorted_rows, touch
from util import ZERO, add_days, new_id, q2

bp = Blueprint("billing", __name__)


def _installment_owner(installment_id):
    row = db.installments.get(installment_id)
    if row is None:
        return None
    plan = db.plans.get(row["payment_plan_id"])
    return plan["patient_id"] if plan else None


# ===========================================================================
# PaymentPlan
# ===========================================================================
@bp.post("/prosthetics/payment-plans")
@guards.endpoint(["FrontOffice"])
def create_plan(ctx):
    # Outside the global write gate: establishing (or replacing) a plan is the
    # remedy for the gate; gating it would make the gate permanent.
    guards.body_fks(ctx, ["patient_id", "case_id"])  # rung 6

    # rung 7
    guards.require_string(ctx, "patient_id", "case_id")
    case = db.cases[ctx.body["case_id"]]
    installment_count = guards.require_int(
        ctx,
        "installment_count",
        pconst.PAYMENT_PLAN_MIN_INSTALLMENTS,
        pconst.PAYMENT_PLAN_MAX_INSTALLMENTS,
    )
    down_payment = guards.require_number(ctx, "down_payment_amount")
    first_due_date = guards.require_instant(ctx, "first_due_date")
    frequency = guards.require_enum_value(ctx, "frequency")
    guards.require_int(ctx, "expected_prosthesis_case_version")
    pay_in_full = guards.optional_bool(ctx, "pay_in_full", False)

    # The down-payment floor is checked FIRST, and against the PRE-discount
    # responsibility -- the value observed before any prompt-pay discount.
    pre_discount = domain.case_pre_discount_responsibility(case)
    floor = q2(pre_discount * pconst.PAYMENT_PLAN_MIN_DOWN_RATE)
    if q2(down_payment) < floor:
        guards.bad_request(
            "down_payment_amount is below the declared minimum down-payment rate."
        )

    guards.check_enum("frequency", frequency)  # rung 8
    guards.occ(ctx, "expected_prosthesis_case_version", case)  # rung 9

    new_plan_id = new_id()

    # --- supersede the case's current live plan ----------------------------
    for old in nav.plans_of_case(case):
        if old["plan_status"] not in ("ACTIVE", "DELINQUENT"):
            continue
        old["plan_status"] = "SUPERSEDED"
        old["superseded_by_plan_id"] = new_plan_id
        for row in nav.installments_of_plan(old):
            if row["installment_status"] in ("SCHEDULED", "MISSED"):
                row["installment_status"] = "WAIVED"
                touch(row)
        touch(old)

    plan = db.create(
        "plans",
        {
            "patient_id": ctx.body["patient_id"],
            "case_id": case["id"],
            "superseded_by_plan_id": None,
            "principal_amount": ZERO,
            "installment_count": installment_count,
            "down_payment_amount": q2(down_payment),
            "pay_in_full": pay_in_full,
            "first_due_date": first_due_date,
            "frequency": frequency,
            "plan_status": "ACTIVE",
            "applied_lab_credit_amount": ZERO,
        },
        row_id=new_plan_id,
    )

    # Only once the floor has passed is the prompt-pay discount applied to the
    # case -- steps 7 and 8 now see a live plan with pay_in_full true.
    domain.recompute_case_totals(case)
    plan["principal_amount"] = q2(
        case["patient_responsibility_amount"] - q2(down_payment)
    )

    amounts = calc.installment_amounts(plan["principal_amount"], installment_count)
    for index, amount in enumerate(amounts, start=1):
        db.create(
            "installments",
            {
                "payment_plan_id": plan["id"],
                "sequence_number": index,
                "amount": amount,
                "due_date": calc.installment_due_date(
                    first_due_date, index, frequency
                ),
                "installment_status": "SCHEDULED",
                "is_residual_installment": index == installment_count,
                "paid_at": None,
            },
        )

    touch(case)
    return envelope.created(projections.plan(plan))


@bp.get("/prosthetics/payment-plans/<payment_plan_id>")
@guards.endpoint(["FrontOffice", "PlatformAdmin", "Patient"])
def get_plan(ctx, payment_plan_id):
    existing = db.plans.get(payment_plan_id)
    guards.owner_patient_guard(ctx, existing["patient_id"] if existing else None)
    row = guards.path_row("payment_plan_id", payment_plan_id)  # rung 4
    return envelope.ok(projections.plan(row))


@bp.get("/prosthetics/payment-plans")
@guards.endpoint(["FrontOffice", "PlatformAdmin", "Prosthodontist"])
def list_plans(ctx):
    limit, offset = guards.pagination(ctx)
    rows = sorted_rows(db.plans.values())
    rows = guards.apply_filters(
        rows,
        ctx,
        [
            ("patient_id", "patient_id", None),
            ("case_id", "case_id", None),
            ("superseded_by_plan_id", "superseded_by_plan_id", None),
            ("plan_status", "plan_status", guards.status_members("plan_status")),
        ],
    )
    return envelope.listing(
        [projections.plan(r) for r in guards.paginate(rows, limit, offset)],
        limit,
        offset,
        len(rows),
    )


@bp.post("/prosthetics/payment-plans/<payment_plan_id>/assess-delinquency")
@guards.endpoint(["PlatformAdmin", "FrontOffice"])
def assess_delinquency(ctx, payment_plan_id):
    plan = guards.path_row("payment_plan_id", payment_plan_id)  # rung 4
    # Outside the global write gate: the sweep is what raises and lowers it.
    guards.terminal_guard(plan, "plan_status")  # rung 10
    guards.from_state_guard(  # rung 12
        plan, "plan_status", ("ACTIVE", "DELINQUENT", "DEFAULTED")
    )

    clock = now()
    for row in nav.installments_of_plan(plan):
        if row["installment_status"] != "SCHEDULED":
            continue
        boundary = add_days(row["due_date"], pconst.PAYMENT_PLAN_DELINQUENCY_GRACE_DAYS)
        if boundary < clock:
            row["installment_status"] = "MISSED"
            touch(row)

    missed = domain.plan_missed_count(plan)
    if missed >= pconst.PAYMENT_PLAN_DEFAULT_MISSED_COUNT:
        plan["plan_status"] = "DEFAULTED"
    elif missed >= 1:
        plan["plan_status"] = "DELINQUENT"
    touch(plan)
    return envelope.ok(projections.plan(plan))


# ===========================================================================
# Installment
# ===========================================================================
@bp.get("/prosthetics/installments/<installment_id>")
@guards.endpoint(["FrontOffice", "PlatformAdmin", "Patient"])
def get_installment(ctx, installment_id):
    guards.owner_patient_guard(ctx, _installment_owner(installment_id))  # rung 3
    row = guards.path_row("installment_id", installment_id)  # rung 4
    return envelope.ok(projections.installment(row))


@bp.get("/prosthetics/installments")
@guards.endpoint(["FrontOffice", "PlatformAdmin", "Patient"])
def list_installments(ctx):
    limit, offset = guards.pagination(ctx)
    rows = sorted_rows(db.installments.values())
    rows = guards.apply_filters(
        rows,
        ctx,
        [
            ("payment_plan_id", "payment_plan_id", None),
            (
                "installment_status",
                "installment_status",
                guards.status_members("installment_status"),
            ),
        ],
    )
    return envelope.listing(
        [projections.installment(r) for r in guards.paginate(rows, limit, offset)],
        limit,
        offset,
        len(rows),
    )


@bp.post("/prosthetics/installments/<installment_id>/pay")
@guards.endpoint(["Patient", "FrontOffice"])
def pay_installment(ctx, installment_id):
    guards.owner_patient_guard(ctx, _installment_owner(installment_id))  # rung 3
    installment = guards.path_row("installment_id", installment_id)  # rung 4
    # Outside the global write gate: paying is the cure.
    amount_paid = guards.require_number(ctx, "amount_paid")  # rung 7
    if amount_paid <= ZERO:
        guards.bad_request("amount_paid must be strictly greater than zero.")
    if q2(amount_paid) != installment["amount"]:
        guards.bad_request("amount_paid must equal the installment amount to the cent.")
    guards.terminal_guard(installment, "installment_status")  # rung 10
    guards.from_state_guard(  # rung 12
        installment, "installment_status", ("SCHEDULED", "MISSED")
    )

    installment["installment_status"] = "PAID"
    installment["paid_at"] = now()
    touch(installment)

    plan = nav.plan_of_installment(installment)
    if plan is not None:
        domain.cure_or_settle_plan(plan)
        case = db.cases.get(plan["case_id"])
        if case is not None:
            domain.maybe_close_case(case)
    return envelope.ok(projections.installment(installment))


@bp.post("/prosthetics/installments/<installment_id>/reverse-payment")
@guards.endpoint(["FrontOffice"])
def reverse_payment(ctx, installment_id):
    installment = guards.path_row("installment_id", installment_id)  # rung 4
    # Outside the global write gate.
    guards.terminal_guard(installment, "installment_status")  # rung 10
    guards.from_state_guard(installment, "installment_status", ("PAID",))  # rung 12

    boundary = add_days(
        installment["due_date"], pconst.PAYMENT_PLAN_DELINQUENCY_GRACE_DAYS
    )
    if now() <= boundary:
        installment["installment_status"] = "SCHEDULED"
    else:
        installment["installment_status"] = "MISSED"
    installment["paid_at"] = None
    touch(installment)
    return envelope.ok(projections.installment(installment))
