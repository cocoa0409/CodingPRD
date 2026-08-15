"""Build job endpoints: booking, advance/hold/resume, payments, summary."""
from flask import Blueprint, request

from store import STORE, now
from helpers import (ApiError, endpoint, get_body, validate_payload, ok, created,
                     ok_list, paginate, filter_eq, sort_created, not_found,
                     stamp_new, stamp_new_noversion, bump)
from domain import (ser_job, ser_payment, milestones_of_job, tool_by_job,
                    milestone_plan_amounts, eval_ownership, sweep_customer,
                    job_open_eco_count, job_billed_cents, job_paid_cents,
                    job_credit_balance_cents, job_net_paid_cents,
                    job_outstanding_cents, ship_threshold_cents,
                    BILLING_PCT, MILESTONE_CODES, WARRANTY_SHOT_LIMIT,
                    JOB_STATES)

bp = Blueprint("jobs", __name__)


@bp.route("/build-jobs", methods=["POST"])
@endpoint(roles=["ProjectManager"])
def create_job(uid, role):
    data = validate_payload(get_body(), [
        ("quote_id", "str", True),
    ])
    quote = STORE.quotes.get(data["quote_id"])
    if quote is None:
        not_found("QUOTE")
    # Tier 10: one build job per quote.
    for existing in STORE.jobs.values():
        if existing["quote_id"] == quote["id"]:
            raise ApiError("ERR_JOB_ALREADY_EXISTS", 409,
                           "A build job already exists for this quote")
    # Tier 11: the quote must be ACCEPTED.
    if quote["status"] != "ACCEPTED":
        raise ApiError("ERR_QUOTE_NOT_ACCEPTED", 409,
                       "A build job requires an ACCEPTED quote")
    design = STORE.designs.get(quote["tool_design_id"])
    die_class = design["die_class"] if design else None
    STORE.job_n += 1
    job = stamp_new({
        "quote_id": quote["id"],
        "customer_id": quote["customer_id"],
        "tool_design_id": quote["tool_design_id"],
        "die_class": die_class,
        "contract_value_cents": quote["total_price_cents"],
        "status": "BOOKED",
        "hold_return_state": None,
        "_job_no": STORE.job_n,
    })
    STORE.jobs[job["id"]] = job
    STORE.invoice_n[job["id"]] = 0
    # Mint the six canonical milestones per the pinned billing schedule.
    planned = milestone_plan_amounts(job["contract_value_cents"])
    for idx in range(6):
        ms = stamp_new({
            "build_job_id": job["id"],
            "seq": idx + 1,
            "code": MILESTONE_CODES[idx],
            "billing_pct": BILLING_PCT[idx],
            "planned_amount_cents": planned[idx],
            "paid_cents": 0,
            "completed_at": None,
            "status": "PENDING",
        })
        STORE.milestones[ms["id"]] = ms
    # Mint the tool asset (one per job).
    STORE.serial_n += 1
    tool = stamp_new({
        "build_job_id": job["id"],
        "customer_id": job["customer_id"],
        "serial_number": "TLT-%d" % STORE.serial_n,
        "die_class": die_class,
        "warranty_terms": quote["warranty_terms"],
        "warranty_shot_limit": WARRANTY_SHOT_LIMIT[die_class],
        "warranty_expires_at": None,
        "tryout_shots": 0,
        "reported_shots": 0,
        "contract_snapshot_cents": job["contract_value_cents"],
        "carrier": None,
        "tracking_number": None,
        "shipped_at": None,
        "delivered_at": None,
        "physical_status": "IN_BUILD",
        "ownership_status": "SHOP_RETAINED",
    })
    STORE.tools[tool["id"]] = tool
    return created(ser_job(job))


@bp.route("/build-jobs", methods=["GET"])
@endpoint(roles=None)
def list_jobs(uid, role):
    items = sort_created(list(STORE.jobs.values()))
    items = filter_eq(items, "customer_id", request.args.get("customer_id"))
    items = filter_eq(items, "status", request.args.get("status"))
    page, meta = paginate(items)
    return ok_list([ser_job(j) for j in page], meta)


@bp.route("/build-jobs/<jobId>", methods=["GET"])
@endpoint(roles=None)
def get_job(uid, role, jobId):
    job = STORE.jobs.get(jobId)
    if job is None:
        not_found("BUILD_JOB")
    return ok(ser_job(job))


@bp.route("/build-jobs/<jobId>/advance", methods=["POST"])
@endpoint(roles=["ProjectManager"])
def advance_job(uid, role, jobId):
    data = validate_payload(get_body(), [
        ("target_state", "enum", True, {"values": JOB_STATES}),
    ])
    job = STORE.jobs.get(jobId)
    if job is None:
        not_found("BUILD_JOB")
    target = data["target_state"]
    legal = ((job["status"] == "BOOKED" and target == "IN_BUILD")
             or (job["status"] == "BUYOFF_PASSED" and target == "READY_TO_SHIP"))
    if not legal:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Illegal advance target for the job's current state")
    if target == "IN_BUILD":
        reserved = any(r["build_job_id"] == job["id"] and r["status"] == "RESERVED"
                       for r in STORE.machine_res.values())
        if not reserved:
            raise ApiError("ERR_NO_CAPACITY_RESERVED", 409,
                           "BOOKED -> IN_BUILD requires a RESERVED machine reservation")
    else:  # READY_TO_SHIP
        ms = {m["seq"]: m for m in milestones_of_job(job["id"])}
        for seq in range(1, 6):
            if seq not in ms or ms[seq]["status"] not in ("EARNED", "INVOICED", "PAID"):
                raise ApiError("ERR_MILESTONE_SEQUENCE_BLOCKED", 409,
                               "Milestones 1-5 must all be EARNED or beyond")
    job["status"] = target
    bump(job)
    return ok(ser_job(job))


@bp.route("/build-jobs/<jobId>/hold", methods=["POST"])
@endpoint(roles=["ProjectManager"])
def hold_job(uid, role, jobId):
    validate_payload(get_body(), [])
    job = STORE.jobs.get(jobId)
    if job is None:
        not_found("BUILD_JOB")
    if job["status"] not in ("BOOKED", "IN_BUILD", "TRYOUT_PHASE",
                             "BUYOFF_PASSED", "READY_TO_SHIP"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an active job may be put ON_HOLD")
    job["hold_return_state"] = job["status"]
    job["status"] = "ON_HOLD"
    bump(job)
    return ok(ser_job(job))


@bp.route("/build-jobs/<jobId>/resume", methods=["POST"])
@endpoint(roles=["ProjectManager"])
def resume_job(uid, role, jobId):
    validate_payload(get_body(), [])
    job = STORE.jobs.get(jobId)
    if job is None:
        not_found("BUILD_JOB")
    if job["status"] != "ON_HOLD":
        raise ApiError("ERR_INVALID_STATE", 409, "Only an ON_HOLD job may resume")
    job["status"] = job["hold_return_state"]
    job["hold_return_state"] = None
    bump(job)
    return ok(ser_job(job))


@bp.route("/build-jobs/<jobId>/payments", methods=["POST"])
@endpoint(roles=["FinanceAdmin"])
def record_payment(uid, role, jobId):
    data = validate_payload(get_body(), [
        ("amount_cents", "int", True, {"min": 1}),
        ("expected_build_job_version", "int", True),
    ])
    job = STORE.jobs.get(jobId)
    if job is None:
        not_found("BUILD_JOB")
    # Tier 6: OCC against the job version.
    if data["expected_build_job_version"] != job["version"]:
        raise ApiError("ERR_STALE_BUILD_JOB_VERSION", 412,
                       "The build job version has advanced since it was observed")
    eligible = sorted(
        (i for i in STORE.invoices.values()
         if i["build_job_id"] == jobId and i["status"] in ("ISSUED", "PARTIALLY_PAID")),
        key=lambda i: (i["due_date"], i["created_at"], i["_seq"]))
    # Tier 8: segregation of duties, simulated before any money moves.
    remaining = data["amount_cents"]
    for inv in eligible:
        if remaining <= 0:
            break
        applied = min(inv["amount_cents"] - inv["paid_cents"], remaining)
        if applied > 0 and inv["issued_by_user_id"] == uid:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                           "The payment recorder issued an invoice that would receive an allocation")
        remaining -= applied
    # Tier 12: overpayment (atomic rejection).
    total_due = sum(i["amount_cents"] - i["paid_cents"] for i in eligible)
    if data["amount_cents"] > total_due:
        raise ApiError("ERR_OVERPAYMENT", 422,
                       "Payment exceeds the sum of eligible invoice balances")
    # Waterfall allocation: due_date ASC, created_at ASC.
    allocations = []
    remaining = data["amount_cents"]
    for inv in eligible:
        if remaining <= 0:
            break
        applied = min(inv["amount_cents"] - inv["paid_cents"], remaining)
        if applied == 0:
            continue
        inv["paid_cents"] += applied
        remaining -= applied
        allocations.append({"invoice_id": inv["id"], "applied_cents": applied})
        inv["status"] = "PAID" if inv["paid_cents"] == inv["amount_cents"] else "PARTIALLY_PAID"
        bump(inv)
        ms = STORE.milestones.get(inv["build_milestone_id"])
        if ms is not None:
            ms["paid_cents"] += applied
            if inv["status"] == "PAID" and ms["status"] == "INVOICED":
                live = [x for x in STORE.invoices.values()
                        if x["build_milestone_id"] == ms["id"] and x["status"] != "VOID"]
                if live and all(x["status"] == "PAID" for x in live):
                    ms["status"] = "PAID"
            bump(ms)
    payment = stamp_new_noversion({
        "build_job_id": jobId,
        "amount_cents": data["amount_cents"],
        "allocations": allocations,
        "recorded_by_user_id": uid,
    })
    STORE.payments[payment["id"]] = payment
    bump(job)  # recording a payment increments the job's version (PRD §2.5)
    eval_ownership(job)
    cust = STORE.customers.get(job["customer_id"])
    if cust is not None:
        sweep_customer(cust)
    return created(ser_payment(payment))


@bp.route("/build-jobs/<jobId>/summary", methods=["GET"])
@endpoint(roles=None)
def job_summary(uid, role, jobId):
    job = STORE.jobs.get(jobId)
    if job is None:
        not_found("BUILD_JOB")
    tool = tool_by_job(jobId)
    threshold = ship_threshold_cents(job)
    outstanding = job_outstanding_cents(job)
    return ok({
        "build_job_id": jobId,
        "contract_value_cents": job["contract_value_cents"],
        "billed_cents": job_billed_cents(jobId),
        "paid_cents": job_paid_cents(jobId),
        "credit_balance_cents": job_credit_balance_cents(jobId),
        "net_paid_cents": job_net_paid_cents(jobId),
        "outstanding_cents": outstanding,
        "ship_release_threshold_cents": threshold,
        "ship_release_allowed": outstanding <= threshold,
        "open_eco_count": job_open_eco_count(jobId),
        "ownership_status": tool["ownership_status"] if tool else None,
    })
