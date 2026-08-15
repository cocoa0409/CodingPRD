"""BuildMilestone, ProgressInvoice, and Payment read endpoints (PRD §3.5)."""
from datetime import timedelta

from flask import Blueprint, request

from store import STORE, now
from helpers import (ApiError, endpoint, get_body, validate_payload, ok, created,
                     ok_list, paginate, filter_eq, sort_created, not_found,
                     stamp_new, bump)
from domain import (ser_milestone, ser_invoice, ser_payment, milestones_of_job,
                    tool_by_job)

bp = Blueprint("milestones", __name__)


@bp.route("/build-milestones", methods=["GET"])
@endpoint(roles=None)
def list_milestones(uid, role):
    items = sorted(STORE.milestones.values(),
                   key=lambda m: (m["build_job_id"], m["seq"]))
    items = filter_eq(items, "build_job_id", request.args.get("build_job_id"))
    items = filter_eq(items, "status", request.args.get("status"))
    page, meta = paginate(items)
    return ok_list([ser_milestone(m) for m in page], meta)


@bp.route("/build-milestones/<milestoneId>", methods=["GET"])
@endpoint(roles=None)
def get_milestone(uid, role, milestoneId):
    ms = STORE.milestones.get(milestoneId)
    if ms is None:
        not_found("BUILD_MILESTONE")
    return ok(ser_milestone(ms))


@bp.route("/build-milestones/<milestoneId>/complete", methods=["POST"])
@endpoint(roles=["ProjectManager", "Customer"])
def complete_milestone(uid, role, milestoneId):
    validate_payload(get_body(), [
        ("completion_note", "str", False),
    ])
    ms = STORE.milestones.get(milestoneId)
    if ms is None:
        not_found("BUILD_MILESTONE")
    job = STORE.jobs.get(ms["build_job_id"])
    # Tier 5: a Customer caller may only act on its own jobs.
    if role == "Customer" and (job is None or job["customer_id"] != uid):
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                       "Customer caller does not own this job")
    # Tier 7: state gates.
    if job is not None and job["status"] == "ON_HOLD":
        raise ApiError("ERR_JOB_ON_HOLD", 409,
                       "Milestones may not be completed while the job is ON_HOLD")
    if ms["status"] not in ("PENDING", "REOPENED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Milestone must be PENDING or REOPENED to complete")
    samples = [s for s in STORE.samples.values() if s["build_job_id"] == ms["build_job_id"]]
    if ms["seq"] == 4:
        if not any(s["status"] in ("SUBMITTED", "BOUGHT_OFF") for s in samples):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Seq 4 requires a tryout sample in SUBMITTED or BOUGHT_OFF")
    if ms["seq"] == 5:
        if not any(s["status"] == "BOUGHT_OFF" for s in samples):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Seq 5 requires a BOUGHT_OFF tryout sample")
    if ms["seq"] == 6:
        tool = tool_by_job(ms["build_job_id"])
        if tool is None or tool["physical_status"] != "IN_PRODUCTION":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Seq 6 requires the tool to be IN_PRODUCTION")
    # Tier 10: actor rule, then sequence ordering.
    if role == "Customer" and ms["seq"] != 5:
        raise ApiError("ERR_MILESTONE_ACTOR_MISMATCH", 403,
                       "Customers may only complete milestone seq 5")
    if role == "ProjectManager" and ms["seq"] == 5:
        raise ApiError("ERR_MILESTONE_ACTOR_MISMATCH", 403,
                       "Milestone seq 5 is the owning customer's signature")
    for lower in milestones_of_job(ms["build_job_id"]):
        if lower["seq"] < ms["seq"] and lower["status"] not in ("EARNED", "INVOICED", "PAID"):
            raise ApiError("ERR_MILESTONE_SEQUENCE_BLOCKED", 409,
                           "A lower-seq milestone is not yet EARNED")
    ms["status"] = "EARNED"
    ms["completed_at"] = now()
    bump(ms)
    return ok(ser_milestone(ms))


@bp.route("/build-milestones/<milestoneId>/invoice", methods=["POST"])
@endpoint(roles=["FinanceAdmin"])
def invoice_milestone(uid, role, milestoneId):
    validate_payload(get_body(), [])
    ms = STORE.milestones.get(milestoneId)
    if ms is None:
        not_found("BUILD_MILESTONE")
    if ms["status"] != "EARNED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an EARNED milestone may be invoiced")
    job = STORE.jobs.get(ms["build_job_id"])
    job_no = job["_job_no"] if job is not None else 0
    STORE.invoice_n[ms["build_job_id"]] = STORE.invoice_n.get(ms["build_job_id"], 0) + 1
    n = STORE.invoice_n[ms["build_job_id"]]
    amount = ms["planned_amount_cents"] - ms["paid_cents"]
    inv = stamp_new({
        "build_job_id": ms["build_job_id"],
        "build_milestone_id": ms["id"],
        "invoice_number": "INV-%d-%d" % (job_no, n),
        "amount_cents": amount,
        "paid_cents": 0,
        "issued_by_user_id": uid,
        "due_date": now() + timedelta(days=30),
        "void_reason": None,
        "status": "ISSUED",
    })
    STORE.invoices[inv["id"]] = inv
    ms["status"] = "INVOICED"
    bump(ms)
    return created(ser_invoice(inv))


@bp.route("/progress-invoices", methods=["GET"])
@endpoint(roles=None)
def list_invoices(uid, role):
    items = sort_created(list(STORE.invoices.values()))
    items = filter_eq(items, "build_job_id", request.args.get("build_job_id"))
    items = filter_eq(items, "status", request.args.get("status"))
    page, meta = paginate(items)
    return ok_list([ser_invoice(i) for i in page], meta)


@bp.route("/progress-invoices/<invoiceId>", methods=["GET"])
@endpoint(roles=None)
def get_invoice(uid, role, invoiceId):
    inv = STORE.invoices.get(invoiceId)
    if inv is None:
        not_found("PROGRESS_INVOICE")
    return ok(ser_invoice(inv))


@bp.route("/payments", methods=["GET"])
@endpoint(roles=None)
def list_payments(uid, role):
    items = sort_created(list(STORE.payments.values()))
    items = filter_eq(items, "build_job_id", request.args.get("build_job_id"))
    page, meta = paginate(items)
    return ok_list([ser_payment(p) for p in page], meta)


@bp.route("/payments/<paymentId>", methods=["GET"])
@endpoint(roles=None)
def get_payment(uid, role, paymentId):
    payment = STORE.payments.get(paymentId)
    if payment is None:
        not_found("PAYMENT")
    return ok(ser_payment(payment))
