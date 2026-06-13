"""HaulJob routes: CRUD, child collections, and all job state-machine transitions."""
from flask import Blueprint, request
import errors
from errors import err
from db import db
from middleware import authenticate, require_role
from response import success, success_list
import helpers as H
import models
from services import calc
from services.recompute import recompute_crew_reserved_minutes, recompute_customer_balance
from services import lookups as L

bp = Blueprint("haul_jobs", __name__)

ITEM_CATEGORIES = {"STANDARD", "MATTRESS", "APPLIANCE", "FREON_APPLIANCE"}
JOB_STATUSES = {"DRAFT", "ESTIMATED", "SCHEDULED", "DISPATCHED", "ON_SITE",
                "LOADED", "COMPLETED", "CANCELLED"}


# --------------------------------------------------------------------------
# HaulJob create / list / get
# --------------------------------------------------------------------------

@bp.route("/haul-jobs", methods=["POST"])
def create_haul_job():
    auth = authenticate()
    require_role(auth, {"Customer", "Dispatcher"})
    body = H.get_json_body()
    H.require_fields(body, ["customer_id", "service_type", "address"])
    customer_id = H.as_str(body["customer_id"], "customer_id")
    # existence (priority 3): customer must exist
    customer = L.get_customer_or_404(customer_id)
    # ownership: a Customer may only create jobs for itself
    if auth.role == "Customer" and customer_id != auth.user_id:
        err(errors.ERR_FORBIDDEN_ROLE, "Customer may only create jobs for itself")
    # well-formedness (priority 4)
    service_type = H.as_enum(body["service_type"], "service_type", {"SAME_DAY", "SCHEDULED"})
    address = H.as_str(body["address"], "address")
    # state (priority 4): an ACTIVE policy must exist
    policy = L.active_policy()
    if policy is None:
        err(errors.ERR_NO_ACTIVE_POLICY, "No ACTIVE PricingPolicy exists")
    job = models.make_haul_job(customer_id, policy["id"], service_type, address)
    db.haul_jobs[job["id"]] = job
    return success(models.ser_haul_job(job), 201)


@bp.route("/haul-jobs", methods=["GET"])
def list_haul_jobs():
    auth = authenticate()
    require_role(auth, {"PlatformAdmin", "Dispatcher", "Billing", "Customer"})
    limit, offset = H.pagination_params()
    customer_filter = request.args.get("customer_id")
    policy_filter = request.args.get("pricing_policy_id")
    status_filter = request.args.get("status")
    items = list(db.haul_jobs.values())
    if auth.role == "Customer":
        items = [j for j in items if j["customer_id"] == auth.user_id]
    if customer_filter is not None:
        items = [j for j in items if j["customer_id"] == customer_filter]
    if policy_filter is not None:
        items = [j for j in items if j["pricing_policy_id"] == policy_filter]
    if status_filter is not None:
        items = [j for j in items if j["status"] == status_filter]
    items = H.sort_by_creation(items)
    page, total = H.paginate(items, limit, offset)
    return success_list([models.ser_haul_job(j) for j in page], limit, offset, total)


@bp.route("/haul-jobs/<job_id>", methods=["GET"])
def get_haul_job(job_id):
    auth = authenticate()
    require_role(auth, {"PlatformAdmin", "Dispatcher", "Billing", "Customer", "CrewLead"})
    job = L.get_job_or_404(job_id)
    if auth.role == "Customer":
        L.require_customer_owns_job(auth, job)
    if auth.role == "CrewLead":
        L.require_crewlead_owns_job(auth, job)
    return success(models.ser_haul_job(job), 200)


# --------------------------------------------------------------------------
# JobItem
# --------------------------------------------------------------------------

@bp.route("/haul-jobs/<job_id>/items", methods=["POST"])
def add_item(job_id):
    auth = authenticate()
    require_role(auth, {"Customer", "Dispatcher"})
    job = L.get_job_or_404(job_id)
    L.require_customer_owns_job(auth, job)
    body = H.get_json_body()
    H.require_fields(body, ["category"])
    category = H.as_enum(body["category"], "category", ITEM_CATEGORIES)
    quantity = 1
    if "quantity" in body and body["quantity"] is not None:
        quantity = H.as_int(body["quantity"], "quantity")
        if quantity < 1:
            err(errors.ERR_INVALID_REQUEST, "quantity must be >= 1")
    description = None
    if "description" in body and body["description"] is not None:
        description = H.as_str(body["description"], "description")
    # state: items attach to DRAFT or ESTIMATED jobs
    if job["status"] not in ("DRAFT", "ESTIMATED"):
        err(errors.ERR_JOB_NOT_ESTIMATED, "Items may only be added to a DRAFT or ESTIMATED job")
    item = models.make_job_item(job["id"], category, quantity, description)
    db.job_items[item["id"]] = item
    return success(models.ser_job_item(item), 201)


@bp.route("/haul-jobs/<job_id>/items", methods=["GET"])
def list_items(job_id):
    auth = authenticate()
    require_role(auth, {"PlatformAdmin", "Dispatcher", "Billing", "Customer", "CrewLead"})
    job = L.get_job_or_404(job_id)
    if auth.role == "Customer":
        L.require_customer_owns_job(auth, job)
    if auth.role == "CrewLead":
        L.require_crewlead_owns_job(auth, job)
    limit, offset = H.pagination_params()
    items = [i for i in db.job_items.values() if i["haul_job_id"] == job["id"]]
    items = H.sort_by_creation(items)
    page, total = H.paginate(items, limit, offset)
    return success_list([models.ser_job_item(i) for i in page], limit, offset, total)


# --------------------------------------------------------------------------
# PhotoEstimate
# --------------------------------------------------------------------------

@bp.route("/haul-jobs/<job_id>/photo-estimates", methods=["POST"])
def submit_estimate(job_id):
    auth = authenticate()
    require_role(auth, {"Customer", "Dispatcher"})
    job = L.get_job_or_404(job_id)
    L.require_customer_owns_job(auth, job)
    body = H.get_json_body()
    H.require_fields(body, ["photo_url", "raw_fraction"])
    photo_url = H.as_str(body["photo_url"], "photo_url")
    raw_fraction = H.as_number(body["raw_fraction"], "raw_fraction")
    if not (raw_fraction > 0 and raw_fraction <= 1.0):
        err(errors.ERR_INVALID_REQUEST, "raw_fraction must be in (0, 1.0]")
    declared_items = []
    if "declared_items" in body and body["declared_items"] is not None:
        di = body["declared_items"]
        if not isinstance(di, list):
            err(errors.ERR_INVALID_REQUEST, "declared_items must be an array")
        for entry in di:
            if not isinstance(entry, dict):
                err(errors.ERR_INVALID_REQUEST, "declared_items entries must be objects")
            if "category" not in entry:
                err(errors.ERR_INVALID_REQUEST, "declared_items entries need a category")
            cat = H.as_enum(entry["category"], "category", ITEM_CATEGORIES)
            qty = 1
            if "quantity" in entry and entry["quantity"] is not None:
                qty = H.as_int(entry["quantity"], "quantity")
                if qty < 1:
                    err(errors.ERR_INVALID_REQUEST, "declared_items quantity must be >= 1")
            declared_items.append({"category": cat, "quantity": qty})
    est = models.make_photo_estimate(job["id"], photo_url, raw_fraction, declared_items)
    db.photo_estimates[est["id"]] = est
    return success(models.ser_photo_estimate(est), 201)


@bp.route("/haul-jobs/<job_id>/photo-estimates", methods=["GET"])
def list_estimates(job_id):
    auth = authenticate()
    require_role(auth, {"PlatformAdmin", "Dispatcher", "Customer"})
    job = L.get_job_or_404(job_id)
    if auth.role == "Customer":
        L.require_customer_owns_job(auth, job)
    limit, offset = H.pagination_params()
    status_filter = request.args.get("status")
    items = [e for e in db.photo_estimates.values() if e["haul_job_id"] == job["id"]]
    if status_filter is not None:
        items = [e for e in items if e["status"] == status_filter]
    items = H.sort_by_creation(items)
    page, total = H.paginate(items, limit, offset)
    return success_list([models.ser_photo_estimate(e) for e in page], limit, offset, total)


@bp.route("/haul-jobs/<job_id>/photo-estimates/<estimate_id>/accept", methods=["POST"])
def accept_estimate(job_id, estimate_id):
    auth = authenticate()
    require_role(auth, {"Customer"})
    job = L.get_job_or_404(job_id)
    est = L.get_estimate_on_job_or_404(job, estimate_id)
    L.require_customer_owns_job(auth, job)
    # state: job must have at least one SUBMITTED estimate, and target must be SUBMITTED
    has_submitted = any(
        e["haul_job_id"] == job["id"] and e["status"] == "SUBMITTED"
        for e in db.photo_estimates.values()
    )
    if not has_submitted:
        err(errors.ERR_NO_ESTIMATE, "Job has no SUBMITTED PhotoEstimate")
    if est["status"] != "SUBMITTED":
        err(errors.ERR_ESTIMATE_NOT_SUBMITTED, "Target estimate is not SUBMITTED")

    # Side effects: supersede any prior ACCEPTED estimate, accept this one.
    for e in db.photo_estimates.values():
        if e["haul_job_id"] == job["id"] and e["status"] == "ACCEPTED":
            e["status"] = "SUPERSEDED"
            e["accepted"] = False
            models.touch(e)
    est["status"] = "ACCEPTED"
    est["accepted"] = True
    models.touch(est)

    policy = db.pricing_policies[job["pricing_policy_id"]]
    job["estimated_truck_fraction"] = calc.estimated_truck_fraction(est, policy)
    job["estimated_total_cents"] = calc.estimated_total_cents(job, est, policy)
    job["status"] = "ESTIMATED"
    models.touch(job)
    return success(models.ser_haul_job(job), 200)


# --------------------------------------------------------------------------
# Revision loop
# --------------------------------------------------------------------------

@bp.route("/haul-jobs/<job_id>/revise", methods=["POST"])
def revise_job(job_id):
    auth = authenticate()
    require_role(auth, {"Customer"})
    job = L.get_job_or_404(job_id)
    L.require_customer_owns_job(auth, job)
    body = H.get_json_body()
    H.require_fields(body, ["expected_job_version"])
    expected = H.as_int(body["expected_job_version"], "expected_job_version")
    # state (priority 5) before OCC (priority 10)
    if job["status"] != "SCHEDULED":
        err(errors.ERR_JOB_NOT_REVISABLE, "Revise requires the job to be in SCHEDULED status")
    if expected != job["version"]:
        err(errors.ERR_STALE_JOB_VERSION, "expected_job_version does not match current version")

    # Void the job's RESERVED dispatch and recompute the crew's reserved minutes.
    for d in db.dispatches.values():
        if d["haul_job_id"] == job["id"] and d["dispatch_status"] == "RESERVED":
            d["dispatch_status"] = "VOIDED"
            models.touch(d)
            crew = db.crews.get(d["crew_id"])
            if crew is not None:
                recompute_crew_reserved_minutes(crew)
    job["status"] = "ESTIMATED"
    models.touch(job)  # increments HaulJob.version by 1
    return success(models.ser_haul_job(job), 200)


# --------------------------------------------------------------------------
# On-site: arrive / diversions / dump-tickets / load
# --------------------------------------------------------------------------

@bp.route("/haul-jobs/<job_id>/arrive", methods=["POST"])
def arrive(job_id):
    auth = authenticate()
    require_role(auth, {"CrewLead"})
    job = L.get_job_or_404(job_id)
    L.require_crewlead_owns_job(auth, job)
    if job["status"] != "DISPATCHED":
        err(errors.ERR_JOB_NOT_DISPATCHED, "Arrive requires the job to be in DISPATCHED status")
    job["status"] = "ON_SITE"
    models.touch(job)
    return success(models.ser_haul_job(job), 200)


@bp.route("/haul-jobs/<job_id>/diversions", methods=["POST"])
def add_diversion(job_id):
    auth = authenticate()
    require_role(auth, {"CrewLead"})
    job = L.get_job_or_404(job_id)
    L.require_crewlead_owns_job(auth, job)
    body = H.get_json_body()
    H.require_fields(body, ["destination", "tons"])
    destination = H.as_enum(body["destination"], "destination", {"DONATION", "RECYCLING"})
    tons = H.as_number(body["tons"], "tons")
    if tons < 0:
        err(errors.ERR_INVALID_REQUEST, "tons must be >= 0")
    if job["status"] != "ON_SITE":
        err(errors.ERR_JOB_NOT_ON_SITE, "Diversions require the job to be ON_SITE")
    rec = models.make_diversion_record(job["id"], destination, tons)
    db.diversion_records[rec["id"]] = rec
    return success(models.ser_diversion_record(rec), 201)


@bp.route("/haul-jobs/<job_id>/diversions", methods=["GET"])
def list_diversions(job_id):
    auth = authenticate()
    require_role(auth, {"PlatformAdmin", "Dispatcher", "Billing", "CrewLead"})
    job = L.get_job_or_404(job_id)
    if auth.role == "CrewLead":
        L.require_crewlead_owns_job(auth, job)
    limit, offset = H.pagination_params()
    dest_filter = request.args.get("destination")
    items = [d for d in db.diversion_records.values() if d["haul_job_id"] == job["id"]]
    if dest_filter is not None:
        items = [d for d in items if d["destination"] == dest_filter]
    items = H.sort_by_creation(items)
    page, total = H.paginate(items, limit, offset)
    return success_list([models.ser_diversion_record(d) for d in page], limit, offset, total)


@bp.route("/haul-jobs/<job_id>/dump-tickets", methods=["POST"])
def add_dump_ticket(job_id):
    auth = authenticate()
    require_role(auth, {"CrewLead"})
    job = L.get_job_or_404(job_id)
    L.require_crewlead_owns_job(auth, job)
    body = H.get_json_body()
    H.require_fields(body, ["landfill_tons", "landfill_fraction", "fee_basis"])
    landfill_tons = H.as_number(body["landfill_tons"], "landfill_tons")
    if landfill_tons < 0:
        err(errors.ERR_INVALID_REQUEST, "landfill_tons must be >= 0")
    landfill_fraction = H.as_number(body["landfill_fraction"], "landfill_fraction")
    if not (landfill_fraction >= 0 and landfill_fraction <= 1.0):
        err(errors.ERR_INVALID_REQUEST, "landfill_fraction must be in [0, 1.0]")
    fee_basis = H.as_enum(body["fee_basis"], "fee_basis", {"WEIGHT_BASED", "VOLUME_BASED"})
    if job["status"] != "ON_SITE":
        err(errors.ERR_JOB_NOT_ON_SITE, "Dump tickets require the job to be ON_SITE")
    ticket = models.make_dump_ticket(job["id"], landfill_tons, landfill_fraction, fee_basis)
    db.dump_tickets[ticket["id"]] = ticket
    return success(models.ser_dump_ticket(ticket), 201)


@bp.route("/haul-jobs/<job_id>/dump-tickets", methods=["GET"])
def list_dump_tickets(job_id):
    auth = authenticate()
    require_role(auth, {"PlatformAdmin", "Dispatcher", "Billing", "CrewLead"})
    job = L.get_job_or_404(job_id)
    if auth.role == "CrewLead":
        L.require_crewlead_owns_job(auth, job)
    limit, offset = H.pagination_params()
    items = [d for d in db.dump_tickets.values() if d["haul_job_id"] == job["id"]]
    items = H.sort_by_creation(items)
    page, total = H.paginate(items, limit, offset)
    return success_list([models.ser_dump_ticket(d) for d in page], limit, offset, total)


@bp.route("/haul-jobs/<job_id>/load", methods=["POST"])
def load_job(job_id):
    auth = authenticate()
    require_role(auth, {"CrewLead"})
    job = L.get_job_or_404(job_id)
    L.require_crewlead_owns_job(auth, job)
    body = H.get_json_body()
    H.require_fields(body, ["measured_truck_fraction"])
    measured = H.as_number(body["measured_truck_fraction"], "measured_truck_fraction")
    # state (priority 5) before the fraction structural rule
    if job["status"] != "ON_SITE":
        err(errors.ERR_JOB_NOT_ON_SITE, "Load requires the job to be ON_SITE")
    if not (measured > 0 and measured <= 1.0):
        err(errors.ERR_INVALID_FRACTION, "measured_truck_fraction must be in (0, 1.0]")

    policy = db.pricing_policies[job["pricing_policy_id"]]
    job["measured_truck_fraction"] = measured
    # Compute each dump ticket's pass-through fee.
    tickets = [d for d in db.dump_tickets.values() if d["haul_job_id"] == job["id"]]
    for dt in tickets:
        dt["dump_fee_cents"] = calc.dump_fee_for_ticket(dt, policy)
    items = [i for i in db.job_items.values() if i["haul_job_id"] == job["id"]]
    diversions = [d for d in db.diversion_records.values() if d["haul_job_id"] == job["id"]]
    job["final_total_cents"] = calc.final_total_cents(job, items, tickets, diversions, policy)
    job["status"] = "LOADED"
    models.touch(job)
    return success(models.ser_haul_job(job), 200)


# --------------------------------------------------------------------------
# Complete
# --------------------------------------------------------------------------

@bp.route("/haul-jobs/<job_id>/complete", methods=["POST"])
def complete_job(job_id):
    auth = authenticate()
    require_role(auth, {"Dispatcher"})
    job = L.get_job_or_404(job_id)
    if job["status"] != "LOADED":
        err(errors.ERR_JOB_NOT_LOADED, "Complete requires the job to be in LOADED status")
    customer = db.customers[job["customer_id"]]
    # fiscal guard (priority 9): outstanding + new exposure must not exceed credit limit
    exposure = job["final_total_cents"]
    if customer["outstanding_balance_cents"] + exposure > customer["credit_limit_cents"]:
        err(errors.ERR_CREDIT_LIMIT_EXCEEDED, "Completion would exceed customer credit limit")

    # Issue SERVICE invoice.
    invoice = models.make_invoice(job["id"], customer["id"], job["final_total_cents"], "SERVICE")
    db.invoices[invoice["id"]] = invoice
    recompute_customer_balance(customer)
    # Release the job's ACTIVE dispatch and recompute crew reserved minutes.
    for d in db.dispatches.values():
        if d["haul_job_id"] == job["id"] and d["dispatch_status"] == "ACTIVE":
            d["dispatch_status"] = "RELEASED"
            models.touch(d)
            crew = db.crews.get(d["crew_id"])
            if crew is not None:
                recompute_crew_reserved_minutes(crew)
    job["status"] = "COMPLETED"
    models.touch(job)
    return success(models.ser_haul_job(job), 200)


# --------------------------------------------------------------------------
# Cancel
# --------------------------------------------------------------------------

@bp.route("/haul-jobs/<job_id>/cancel", methods=["POST"])
def cancel_job(job_id):
    auth = authenticate()
    require_role(auth, {"Customer"})
    job = L.get_job_or_404(job_id)
    L.require_customer_owns_job(auth, job)
    if job["status"] not in ("ESTIMATED", "SCHEDULED", "DISPATCHED"):
        err(errors.ERR_JOB_NOT_CANCELLABLE,
            "Cancel requires job in ESTIMATED/SCHEDULED/DISPATCHED status")
    policy = db.pricing_policies[job["pricing_policy_id"]]
    fee = calc.cancellation_fee(job, policy)
    job["cancellation_fee_cents"] = fee

    # Void any RESERVED or ACTIVE dispatch; recompute crew reserved minutes.
    for d in db.dispatches.values():
        if d["haul_job_id"] == job["id"] and d["dispatch_status"] in ("RESERVED", "ACTIVE"):
            d["dispatch_status"] = "VOIDED"
            models.touch(d)
            crew = db.crews.get(d["crew_id"])
            if crew is not None:
                recompute_crew_reserved_minutes(crew)

    if fee > 0:
        customer = db.customers[job["customer_id"]]
        invoice = models.make_invoice(job["id"], customer["id"], fee, "CANCELLATION")
        db.invoices[invoice["id"]] = invoice
        recompute_customer_balance(customer)
    job["status"] = "CANCELLED"
    models.touch(job)
    return success(models.ser_haul_job(job), 200)


# --------------------------------------------------------------------------
# Invoices for a job
# --------------------------------------------------------------------------

@bp.route("/haul-jobs/<job_id>/invoices", methods=["GET"])
def list_job_invoices(job_id):
    auth = authenticate()
    require_role(auth, {"PlatformAdmin", "Dispatcher", "Billing", "Customer"})
    job = L.get_job_or_404(job_id)
    if auth.role == "Customer":
        L.require_customer_owns_job(auth, job)
    limit, offset = H.pagination_params()
    kind_filter = request.args.get("kind")
    items = [i for i in db.invoices.values() if i["haul_job_id"] == job["id"]]
    if kind_filter is not None:
        items = [i for i in items if i["kind"] == kind_filter]
    items = H.sort_by_creation(items)
    page, total = H.paginate(items, limit, offset)
    return success_list([models.ser_invoice(i) for i in page], limit, offset, total)
