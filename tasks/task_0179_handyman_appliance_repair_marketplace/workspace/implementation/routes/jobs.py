"""Job lifecycle endpoints (PRD §3.3, §3.5, §3.6, §3.8, §3.9).

Validation order per PRD §2.9: body shape (400) -> auth (decorator: 401/403) ->
existence (404) -> semantic body (422) -> ownership (403) -> state (409) ->
business rules (422). The decorator runs auth before the view body, so existence
and the rest are checked here in the order the PRD pins.
"""
import re

from flask import Blueprint, request, g

from db import store
from errors import ApiError
from middleware import require_role
from models import (
    common, touch, serialize, JOB_FIELDS, QUOTE_FIELDS, WORK_VISIT_FIELDS,
    LABOR_LINE_FIELDS, PART_LINE_FIELDS,
)
from response import object_response, array_response
from timeutil import add_days
from services import pricing, vetting
from services.lookup import (
    require_body, require_string, require_number, require_int, require_bool,
    require_datetime, get_or_404, paginate, sorted_by_creation,
)

bp = Blueprint("jobs", __name__)

_ZIP_RE = re.compile(r"^[0-9]{5}$")


def _own_job_or_403(job):
    """Customer ownership guard on a Job (PRD §2.1)."""
    if g.role == "Customer" and job["customer_id"] != g.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Customer does not own this job")


def _acting_pro_or_403(pro_id):
    if g.role == "Pro" and g.user_id != pro_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Acting Pro mismatch")


# ---------------------------------------------------------------------------
# Job create / fetch / list
# ---------------------------------------------------------------------------
def _v_create_job(body):
    customer_id = require_string(body, "customer_id")
    category_id = require_string(body, "category_id")
    address_zip = require_string(body, "address_zip_code")
    if not _ZIP_RE.match(address_zip):
        raise ApiError("ERR_INVALID_REQUEST", "address_zip_code must be exactly 5 digits")
    return {"customer_id": customer_id, "category_id": category_id,
            "address_zip": address_zip}


@bp.post("/jobs")
@require_role({"Customer"}, validate=_v_create_job)
def create_job():
    customer_id = g.validated["customer_id"]
    category_id = g.validated["category_id"]
    address_zip = g.validated["address_zip"]

    # existence: body FKs in declaration order (PRD §2.7).
    get_or_404(store.customers, customer_id)
    get_or_404(store.service_categories, category_id)

    # ownership: a Customer files jobs only under their own id.
    if g.user_id != customer_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Customer may only file jobs for themselves")

    job = {
        "customer_id": customer_id,
        "category_id": category_id,
        "pro_id": None,
        "parent_job_id": None,
        "status": "REQUESTED",
        "quote_path": None,
        "agreed_price_cents": None,
        "is_warranty_callback": False,
        "address_zip_code": address_zip,
    }
    common(job)
    store.jobs[job["id"]] = job
    return object_response(serialize(job, JOB_FIELDS), status=201)


@bp.get("/jobs/<jid>")
@require_role({"PlatformAdmin", "Customer", "Pro", "Dispatcher"})
def get_job(jid):
    job = get_or_404(store.jobs, jid)
    return object_response(serialize(job, JOB_FIELDS))


@bp.get("/jobs")
@require_role({"PlatformAdmin", "Customer", "Pro", "Dispatcher"})
def list_jobs():
    items = list(store.jobs.values())
    cust = request.args.get("customer_id")
    cat = request.args.get("category_id")
    parent = request.args.get("parent_job_id")
    if cust is not None:
        items = [j for j in items if j["customer_id"] == cust]
    if cat is not None:
        items = [j for j in items if j["category_id"] == cat]
    if parent is not None:
        items = [j for j in items if j.get("parent_job_id") == parent]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(request.args, items)
    return array_response([serialize(j, JOB_FIELDS) for j in page],
                          limit, offset, total)


# ---------------------------------------------------------------------------
# Quoting: instant path / estimate path
# ---------------------------------------------------------------------------
@bp.post("/jobs/<jid>/instant-quote")
@require_role({"Customer"})
def instant_quote(jid):
    job = get_or_404(store.jobs, jid)
    _own_job_or_403(job)
    if job["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "Instant quote only from REQUESTED")
    category = store.service_categories[job["category_id"]]

    # business rule: instant only on eligible categories and non-callback jobs.
    if not category["instant_quote_eligible"] or job["is_warranty_callback"]:
        raise ApiError("ERR_INSTANT_QUOTE_INELIGIBLE",
                       "Instant quote not available for this category or callback job")

    quote = {
        "job_id": jid,
        "quote_type": "INSTANT",
        "estimated_labor_hours": None,
        "priced_amount_cents": pricing.instant_quote_amount(category),
        "accepted": False,
        "superseded": False,
    }
    common(quote)
    store.quotes[quote["id"]] = quote

    job["quote_path"] = "INSTANT"
    job["status"] = "INSTANT_QUOTED"
    touch(job)
    return object_response(serialize(quote, QUOTE_FIELDS), status=201)


@bp.post("/jobs/<jid>/request-estimate")
@require_role({"Customer"})
def request_estimate(jid):
    job = get_or_404(store.jobs, jid)
    _own_job_or_403(job)
    if job["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "Estimate only from REQUESTED")

    job["quote_path"] = "IN_HOME"
    job["status"] = "ESTIMATE_REQUESTED"
    touch(job)
    return object_response(serialize(job, JOB_FIELDS))


def _v_submit_estimate(body):
    estimated_hours = require_number(body, "estimated_labor_hours", required=False,
                                     default=None, minimum=0)
    return {"estimated_hours": estimated_hours}


@bp.post("/jobs/<jid>/quotes")
@require_role({"Pro"}, validate=_v_submit_estimate)
def submit_estimate(jid):
    estimated_hours = g.validated["estimated_hours"]
    job = get_or_404(store.jobs, jid)
    if job["status"] != "ESTIMATE_REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "In-home estimate only from ESTIMATE_REQUESTED")
    category = store.service_categories[job["category_id"]]
    pro = get_or_404(store.pros, g.user_id)

    # assignability gates (background -> license -> skill), PRD §3.5.
    vetting.assert_assignable(pro, category)

    priced = pricing.in_home_quote_amount(category, job, pro, estimated_hours)

    # supersede prior non-accepted quotes on this job.
    for q in store.quotes.values():
        if q["job_id"] == jid and not q["accepted"] and not q["superseded"]:
            q["superseded"] = True
            touch(q)

    quote = {
        "job_id": jid,
        "quote_type": "IN_HOME",
        "estimated_labor_hours": estimated_hours,
        "priced_amount_cents": priced,
        "accepted": False,
        "superseded": False,
    }
    common(quote)
    store.quotes[quote["id"]] = quote

    job["status"] = "ESTIMATED"
    touch(job)
    return object_response(serialize(quote, QUOTE_FIELDS), status=201)


@bp.get("/jobs/<jid>/quotes")
@require_role({"PlatformAdmin", "Customer", "Pro", "Dispatcher"})
def list_quotes(jid):
    get_or_404(store.jobs, jid)
    items = [q for q in store.quotes.values() if q["job_id"] == jid]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(request.args, items)
    return array_response([serialize(q, QUOTE_FIELDS) for q in page],
                          limit, offset, total)


def _v_accept_quote(body):
    return {"quote_id": require_string(body, "quote_id")}


@bp.post("/jobs/<jid>/accept-quote")
@require_role({"Customer"}, validate=_v_accept_quote)
def accept_quote(jid):
    quote_id = g.validated["quote_id"]
    job = get_or_404(store.jobs, jid)
    _own_job_or_403(job)
    if job["status"] not in ("INSTANT_QUOTED", "ESTIMATED"):
        raise ApiError("ERR_INVALID_STATE", "No active quote to accept")
    quote = get_or_404(store.quotes, quote_id)
    if quote["job_id"] != jid:
        raise ApiError("ERR_NOT_FOUND", "Quote does not belong to this job")

    quote["accepted"] = True
    touch(quote)
    job["agreed_price_cents"] = quote["priced_amount_cents"]
    touch(job)
    return object_response(serialize(job, JOB_FIELDS))


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------
@bp.post("/jobs/<jid>/cancel")
@require_role({"Customer"})
def cancel_job(jid):
    job = get_or_404(store.jobs, jid)
    _own_job_or_403(job)
    status = job["status"]
    if status not in ("REQUESTED", "INSTANT_QUOTED", "ESTIMATE_REQUESTED",
                      "ESTIMATED", "SCHEDULED", "IN_PROGRESS"):
        raise ApiError("ERR_INVALID_STATE", "Job cannot be cancelled from %s" % status)

    if status == "IN_PROGRESS":
        # only when no PAID invoice exists for this job.
        for inv in store.invoices.values():
            if inv["job_id"] == jid and inv["status"] == "PAID":
                raise ApiError("ERR_INVALID_STATE", "Cannot cancel a job with a paid invoice")

    if status in ("SCHEDULED", "IN_PROGRESS"):
        _release_window_for_job(jid, clear_booked=True)

    if status == "IN_PROGRESS":
        # void any DRAFT/ISSUED unpaid invoice.
        for inv in store.invoices.values():
            if inv["job_id"] == jid and inv["status"] in ("DRAFT", "ISSUED"):
                if inv["status"] == "DRAFT" or inv["amount_paid_cents"] == 0:
                    inv["status"] = "VOID"
                    touch(inv)

    job["status"] = "CANCELLED"
    job["pro_id"] = None
    touch(job)
    return object_response(serialize(job, JOB_FIELDS))


def _release_window_for_job(jid, clear_booked):
    for win in store.dispatch_windows.values():
        if win.get("booked_job_id") == jid and win["hold_state"] == "BOOKED":
            win["hold_state"] = "RELEASED"
            if clear_booked:
                win["booked_job_id"] = None
            touch(win)


# ---------------------------------------------------------------------------
# Visits (SCHEDULED -> IN_PROGRESS)
# ---------------------------------------------------------------------------
def _v_create_visit(body):
    return {
        "dispatch_window_id": require_string(body, "dispatch_window_id"),
        "arrived_at": require_datetime(body, "arrived_at"),
    }


@bp.post("/jobs/<jid>/visits")
@require_role({"Pro"}, validate=_v_create_visit)
def create_visit(jid):
    dispatch_window_id = g.validated["dispatch_window_id"]
    arrived_at = g.validated["arrived_at"]
    job = get_or_404(store.jobs, jid)
    window = get_or_404(store.dispatch_windows, dispatch_window_id)

    if g.user_id != job.get("pro_id"):
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Acting Pro is not the job's Pro")
    if job["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Visit only from SCHEDULED")

    # the referenced window must be the one booked for this job.
    if window["hold_state"] != "BOOKED" or window.get("booked_job_id") != jid:
        raise ApiError("ERR_INVALID_STATE", "Window is not the one booked for this job")

    # arrived_at within [window_start, window_end).
    if not (window["window_start"] <= arrived_at < window["window_end"]):
        raise ApiError("ERR_VISIT_OUTSIDE_WINDOW", "Arrival outside the booked window")

    visit = {
        "job_id": jid,
        "dispatch_window_id": dispatch_window_id,
        "arrived_at": arrived_at,
        "outcome": "OPEN",
    }
    common(visit)
    store.work_visits[visit["id"]] = visit

    job["status"] = "IN_PROGRESS"
    touch(job)
    return object_response(serialize(visit, WORK_VISIT_FIELDS), status=201)


@bp.get("/jobs/<jid>/visits")
@require_role({"PlatformAdmin", "Customer", "Pro", "Dispatcher"})
def list_job_visits(jid):
    get_or_404(store.jobs, jid)
    items = [v for v in store.work_visits.values() if v["job_id"] == jid]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(request.args, items)
    return array_response([serialize(v, WORK_VISIT_FIELDS) for v in page],
                          limit, offset, total)


# ---------------------------------------------------------------------------
# Labor lines / part lines (IN_PROGRESS)
# ---------------------------------------------------------------------------
def _v_labor_line(body):
    return {"hours_worked": require_number(body, "hours_worked", minimum=0)}


@bp.post("/jobs/<jid>/labor-lines")
@require_role({"Pro"}, validate=_v_labor_line)
def create_labor_line(jid):
    hours_worked = g.validated["hours_worked"]
    job = get_or_404(store.jobs, jid)
    if g.user_id != job.get("pro_id"):
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Acting Pro is not the job's Pro")
    if job["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "Labor lines only on IN_PROGRESS jobs")
    category = store.service_categories[job["category_id"]]
    # labor lines apply only to HOURLY categories.
    if category["pricing_model"] != "HOURLY":
        raise ApiError("ERR_PRICING_MODEL_MISMATCH", "Labor hours not allowed on a FLAT category")

    rate = category["hourly_rate_cents"]
    line = {
        "job_id": jid,
        "hours_worked": hours_worked,
        "rate_cents_per_hour": rate,
        "line_total_cents": pricing.labor_line_total(hours_worked, rate),
    }
    common(line)
    store.labor_lines[line["id"]] = line
    return object_response(serialize(line, LABOR_LINE_FIELDS), status=201)


@bp.get("/jobs/<jid>/labor-lines")
@require_role({"PlatformAdmin", "Customer", "Pro", "Dispatcher"})
def list_labor_lines(jid):
    get_or_404(store.jobs, jid)
    items = [l for l in store.labor_lines.values() if l["job_id"] == jid]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(request.args, items)
    return array_response([serialize(l, LABOR_LINE_FIELDS) for l in page],
                          limit, offset, total)


def _v_part_line(body):
    return {
        "description": require_string(body, "description"),
        "unit_cost": require_int(body, "unit_cost_cents", minimum=0),
        "quantity": require_int(body, "quantity", minimum=1),
        "from_truck": require_bool(body, "from_truck_stock", required=False, default=False),
    }


@bp.post("/jobs/<jid>/part-lines")
@require_role({"Pro"}, validate=_v_part_line)
def create_part_line(jid):
    description = g.validated["description"]
    unit_cost = g.validated["unit_cost"]
    quantity = g.validated["quantity"]
    from_truck = g.validated["from_truck"]
    job = get_or_404(store.jobs, jid)
    if g.user_id != job.get("pro_id"):
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Acting Pro is not the job's Pro")
    if job["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "Part lines only on IN_PROGRESS jobs")
    pro = store.pros[job["pro_id"]]

    line = {
        "job_id": jid,
        "description": description,
        "unit_cost_cents": unit_cost,
        "quantity": quantity,
        "from_truck_stock": from_truck,
        "line_total_cents": pricing.part_line_total(
            unit_cost, quantity, from_truck, pro["truck_stock_markup_pct"]),
    }
    common(line)
    store.part_lines[line["id"]] = line
    return object_response(serialize(line, PART_LINE_FIELDS), status=201)


@bp.get("/jobs/<jid>/part-lines")
@require_role({"PlatformAdmin", "Customer", "Pro", "Dispatcher"})
def list_part_lines(jid):
    get_or_404(store.jobs, jid)
    items = [p for p in store.part_lines.values() if p["job_id"] == jid]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(request.args, items)
    return array_response([serialize(p, PART_LINE_FIELDS) for p in page],
                          limit, offset, total)


# ---------------------------------------------------------------------------
# Complete (IN_PROGRESS -> COMPLETED)
# ---------------------------------------------------------------------------
@bp.post("/jobs/<jid>/complete")
@require_role({"Pro"})
def complete_job(jid):
    job = get_or_404(store.jobs, jid)
    if g.user_id != job.get("pro_id"):
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Acting Pro is not the job's Pro")
    if job["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "Complete only from IN_PROGRESS")

    # an Invoice for the job must exist in ISSUED status.
    issued = [inv for inv in store.invoices.values()
              if inv["job_id"] == jid and inv["status"] == "ISSUED"]
    if not issued:
        raise ApiError("ERR_INVALID_STATE", "No ISSUED invoice for this job")

    # resolve the open work visit(s).
    for v in store.work_visits.values():
        if v["job_id"] == jid and v["outcome"] == "OPEN":
            v["outcome"] = "RESOLVED"
            touch(v)

    # release the booked window.
    _release_window_for_job(jid, clear_booked=False)

    pro = store.pros[job["pro_id"]]
    if not job["is_warranty_callback"]:
        pro["completed_job_count"] += 1
    pro["callback_rate"] = pricing.callback_rate(pro)
    touch(pro)

    # mark completion instant for warranty math.
    job["status"] = "COMPLETED"
    job["completed_at"] = store.now()
    touch(job)
    return object_response(serialize(job, JOB_FIELDS))


# ---------------------------------------------------------------------------
# Callbacks (COMPLETED -> CALLBACK_OPEN, spawns callback job)
# ---------------------------------------------------------------------------
@bp.post("/jobs/<jid>/callbacks")
@require_role({"Customer"})
def open_callback(jid):
    job = get_or_404(store.jobs, jid)
    _own_job_or_403(job)
    if job["status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE", "Callback only from COMPLETED")
    if job["is_warranty_callback"]:
        raise ApiError("ERR_INVALID_STATE", "Cannot open a callback against a callback job")

    category = store.service_categories[job["category_id"]]
    deadline = add_days(job["completed_at"], category["callback_warranty_days"])
    if not (store.now() < deadline):
        raise ApiError("ERR_WARRANTY_EXPIRED", "Warranty window has expired")

    # spawn the callback job: pre-scheduled, reuses original Pro, skips quoting.
    callback = {
        "customer_id": job["customer_id"],
        "category_id": job["category_id"],
        "pro_id": job["pro_id"],
        "parent_job_id": job["id"],
        "status": "SCHEDULED",
        "quote_path": None,
        "agreed_price_cents": None,
        "is_warranty_callback": True,
        "address_zip_code": job["address_zip_code"],
    }
    common(callback)
    store.jobs[callback["id"]] = callback

    pro = store.pros[job["pro_id"]]
    pro["callback_job_count"] += 1
    pro["callback_rate"] = pricing.callback_rate(pro)
    touch(pro)

    job["status"] = "CALLBACK_OPEN"
    touch(job)
    return object_response(serialize(callback, JOB_FIELDS), status=201)
