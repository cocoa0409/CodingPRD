"""Payment-schedule generations and instalment collection (§3.6 - §3.7)."""

from flask import Blueprint

import calc
import serialize
import services as svc
from clockutil import add_days, now
from db import db
from errors import fail
from listing import paged, str_filters
from response import created, obj
from validate import ANY_ROLE, authorize, body, field_enum, field_int, field_str

bp = Blueprint("collection", __name__)

# ISSUANCE is reserved for the generation the server mints at issuance.
MINTABLE_SOURCES = ("REVIEW_DECISION", "ARBITRATION_AWARD", "ACTUARIAL_CORRECTION")


# --------------------------------------------------------------------------
# explicit regeneration
# --------------------------------------------------------------------------

def _conceded_amount(assessment, source, override):
    """Tier 10: every source must have a real concession behind it."""
    conceded = None
    if source == "REVIEW_DECISION":
        for review in reversed(svc.reviews_of(assessment["id"])):
            if (review["status"] == "DECIDED" and review["decision"] == "REDUCED"
                    and review["recomputed_net_assessed_cents"] is not None):
                conceded = review["recomputed_net_assessed_cents"]
                break
    elif source == "ARBITRATION_AWARD":
        for arb in reversed(svc.arbitrations_of(assessment["id"])):
            if (arb["award_outcome"] == "REDUCE"
                    and arb["awarded_net_assessed_cents"] is not None):
                conceded = arb["awarded_net_assessed_cents"]
                break
    else:
        conceded = override

    if conceded is None or conceded > assessment["net_assessed_cents"]:
        fail("ERR_NO_REDUCTION_TO_APPLY")
    return conceded


@bp.post("/payment-schedules")
def mint_schedule():
    authorize(("PlanActuary",))
    data = body()
    assessment_id = field_str(data, "liability_assessment_id", required=True)
    expected_version = field_int(data, "expected_assessment_version", required=True)
    source = field_enum(data, "source", MINTABLE_SOURCES, required=True)
    override = field_int(data, "override_net_assessed_cents", minimum=0)

    assessment = svc.get_assessment(assessment_id)

    # tier 7
    if expected_version != assessment["version"]:
        fail("ERR_STALE_ASSESSMENT_VERSION")

    # tier 8
    svc.require_issued(assessment)

    # tier 10
    conceded = _conceded_amount(assessment, source, override)

    # tier 13: reject before a single row moves
    plan = svc.plan_of_assessment(assessment)
    rate_bps = (svc.sustained_interest_rate(assessment)
                or assessment["interest_rate_bps_applied"])
    svc.check_amortizable(plan, conceded, assessment["annual_payment_cents"],
                          rate_bps, svc.applied_credit_for(assessment))

    schedule = svc.regenerate(assessment, source, conceded)
    return created(serialize.payment_schedule(schedule))


@bp.get("/payment-schedules")
def list_schedules():
    authorize(ANY_ROLE)
    rows = str_filters(list(db.schedules.values()), {
        "liability_assessment_id": "liability_assessment_id",
        "status": "status",
    })
    return paged(rows, serialize.payment_schedule)


@bp.get("/payment-schedules/<payment_schedule_id>")
def read_schedule(payment_schedule_id):
    authorize(ANY_ROLE)
    return obj(serialize.payment_schedule(svc.get_schedule(payment_schedule_id)))


# --------------------------------------------------------------------------
# default notice / cure / acceleration
# --------------------------------------------------------------------------

@bp.post("/payment-schedules/<payment_schedule_id>/default-notice")
def default_notice(payment_schedule_id):
    authorize(("PlanTrustee",))
    schedule = svc.get_schedule(payment_schedule_id)
    if schedule["status"] != "DEFAULT_ELIGIBLE":
        fail("ERR_SCHEDULE_NOT_DEFAULT_ELIGIBLE")

    issued_at = now()
    svc.apply_changes(schedule, {
        "status": "NOTICED",
        "default_notice_issued_at": issued_at,
        "cure_deadline_at": add_days(issued_at, calc.CURE_WINDOW_DAYS),
    })

    assessment = db.assessments.get(schedule["liability_assessment_id"])
    if assessment is not None:
        svc.recompute_assessment(assessment)
    return obj(serialize.payment_schedule(schedule))


@bp.post("/payment-schedules/<payment_schedule_id>/cure")
def cure_schedule(payment_schedule_id):
    ctx = authorize(("EmployerRepresentative",))
    schedule = svc.get_schedule(payment_schedule_id)
    data = body()
    payment_amount = field_int(data, "payment_amount_cents", required=True, minimum=0)

    svc.require_owner(ctx, svc.employer_of_schedule(schedule))

    # tier 8: only a delinquent or noticed generation can be cured, and a
    # notice whose cure window has run out is no longer curable.
    if schedule["status"] not in ("DEFAULT_ELIGIBLE", "NOTICED"):
        fail("ERR_SCHEDULE_NOT_ACTIVE")
    if (schedule["status"] == "NOTICED"
            and schedule["cure_deadline_at"] is not None
            and now() > schedule["cure_deadline_at"]):
        fail("ERR_SCHEDULE_NOT_ACTIVE")

    delinquent = [i for i in svc.installments_of(schedule["id"])
                  if i["status"] == "DELINQUENT"]

    # tier 13: all or nothing, to the cent
    if payment_amount != sum(i["amount_due_cents"] for i in delinquent):
        fail("ERR_CURE_AMOUNT_MISMATCH")

    paid_at = now()
    for inst in delinquent:
        svc.apply_changes(inst, {
            "status": "PAID",
            "amount_paid_cents": inst["amount_due_cents"],
            "paid_at": paid_at,
        })

    svc.apply_changes(schedule, {
        "status": "ACTIVE",
        "consecutive_delinquent_count": 0,
        "default_notice_issued_at": None,
        "cure_deadline_at": None,
    })

    assessment = db.assessments.get(schedule["liability_assessment_id"])
    if assessment is not None:
        svc.recompute_assessment(assessment)
    return obj(serialize.payment_schedule(schedule))


@bp.post("/payment-schedules/<payment_schedule_id>/accelerate")
def accelerate_schedule(payment_schedule_id):
    authorize(("PlanTrustee",))
    schedule = svc.get_schedule(payment_schedule_id)

    # tier 8
    if schedule["status"] != "NOTICED":
        fail("ERR_SCHEDULE_NOT_NOTICED")
    # tier 9: the cure period may not be cut short
    deadline = schedule["cure_deadline_at"]
    if deadline is None or now() <= deadline:
        fail("ERR_CURE_DEADLINE_NOT_EXPIRED")

    balance = 0
    for inst in svc.installments_of(schedule["id"]):
        if inst["status"] in svc.OPEN_INSTALLMENT_STATUSES:
            balance += inst["principal_cents"]
            svc.apply_changes(inst, {"status": "ACCELERATED"})

    svc.apply_changes(schedule, {
        "status": "ACCELERATED",
        "accelerated_balance_cents": balance,
    })

    assessment = db.assessments.get(schedule["liability_assessment_id"])
    employer = svc.employer_of_schedule(schedule)
    if assessment is not None:
        svc.recompute_assessment(assessment, cascade=False)
    if employer is not None:
        svc.apply_changes(employer, {"status": "DEFAULTED"})
        svc.recompute_employer(employer, outstanding_override=balance)
    return obj(serialize.payment_schedule(schedule))


# --------------------------------------------------------------------------
# Installment
# --------------------------------------------------------------------------

@bp.get("/installments")
def list_installments():
    authorize(ANY_ROLE)
    rows = str_filters(list(db.installments.values()), {
        "payment_schedule_id": "payment_schedule_id",
        "status": "status",
    })
    return paged(rows, serialize.installment,
                 key=lambda r: (r["sequence_number"], r["_seq"]))


@bp.get("/installments/<installment_id>")
def read_installment(installment_id):
    authorize(ANY_ROLE)
    return obj(serialize.installment(svc.get_installment(installment_id)))


@bp.post("/installments/<installment_id>/pay")
def pay_installment(installment_id):
    ctx = authorize(("EmployerRepresentative",))
    inst = svc.get_installment(installment_id)
    data = body()
    payment_amount = field_int(data, "payment_amount_cents", required=True, minimum=0)

    employer = svc.employer_of_installment(inst)
    svc.require_owner(ctx, employer)

    # tier 8
    if inst["status"] not in ("DUE", "DELINQUENT"):
        fail("ERR_INSTALLMENT_NOT_PAYABLE")
    # tier 13: payment must be exact - short payments and overpayments alike
    if payment_amount != inst["amount_due_cents"]:
        fail("ERR_PAYMENT_AMOUNT_MISMATCH")

    was_delinquent = inst["status"] == "DELINQUENT"
    svc.apply_changes(inst, {
        "status": "PAID",
        "amount_paid_cents": inst["amount_due_cents"],
        "paid_at": now(),
    })

    schedule = svc.get_schedule(inst["payment_schedule_id"])
    if was_delinquent:
        svc.apply_changes(schedule, {
            "consecutive_delinquent_count":
                max(0, schedule["consecutive_delinquent_count"] - 1),
        })

    siblings = svc.installments_of(schedule["id"])
    settled = all(i["status"] in ("PAID", "VOID") for i in siblings)
    if settled:
        svc.apply_changes(schedule, {"status": "SATISFIED"})

    assessment = db.assessments.get(schedule["liability_assessment_id"])
    if (settled and employer is not None
            and employer["status"] in ("PARTIAL_WITHDRAWN", "COMPLETE_WITHDRAWN")):
        svc.apply_changes(employer, {"status": "LIABILITY_SATISFIED"})
    if assessment is not None:
        # lifecycle_status is untouched: satisfaction is a collection fact and
        # finalisation remains the sweep's job.
        svc.recompute_assessment(assessment)
    elif employer is not None:
        svc.recompute_employer(employer)

    return obj(serialize.installment(inst))
