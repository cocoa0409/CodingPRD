"""Service tickets, dispatch jobs, and coverage agreements (PRD section 3.7)."""

from datetime import timedelta

from flask import Blueprint, request

import envelope
from auth import auth_and_roles, pm_owns_or_403
from calc import (
    DIAGNOSTIC_ESTIMATE_CENTS,
    compute_repair_cost,
    determine_coverage,
    lazy_expire_agreement,
    select_dispatch_technician,
)
from db import STORES, now
from errors import ApiError
from util import (
    base_record,
    body,
    fk_exists,
    fmt_ts,
    get_or_404,
    paginate,
    pub,
    sorted_default,
    touch,
    v_dt,
    v_int,
    v_list,
    v_str,
)

bp = Blueprint("service", __name__)

TICKET_READ_ROLES = [
    "DistributionAdmin",
    "ServiceDispatcher",
    "PracticeManager",
    "FieldTechnician",
]
JOB_ROLES = ["DistributionAdmin", "ServiceDispatcher", "FieldTechnician"]
AGREEMENT_READ_ROLES = [
    "DistributionAdmin",
    "SalesRep",
    "ServiceDispatcher",
    "PracticeManager",
]
REOPEN_WINDOW_DAYS = 30


# ---------------------------------------------------------------------------
# Service tickets
# ---------------------------------------------------------------------------


@bp.post("/service-tickets")
def create_service_ticket():
    uid, role = auth_and_roles(["PracticeManager", "ServiceDispatcher"])
    data = body()
    if role == "PracticeManager":
        pid = data.get("practice_id")
        if pid is not None:
            pm_owns_or_403(role, uid, pid)

    fk_exists(data, "practice_id", "practices")
    fk_exists(data, "equipment_sale_id", "equipment_sales")

    practice_id = v_str(data, "practice_id")
    equipment_sale_id = v_str(data, "equipment_sale_id")
    issue_description = v_str(data, "issue_description")

    sale = STORES["equipment_sales"][equipment_sale_id]
    # The referenced sale must have reached ACCEPTED (equipment in service).
    if sale["status"] != "ACCEPTED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Service tickets require an ACCEPTED equipment sale",
        )
    if sale["practice_id"] != practice_id:
        raise ApiError(
            "ERR_PRACTICE_MISMATCH",
            422,
            "Ticket practice must equal the equipment sale's practice",
        )

    record = base_record()
    record.update(
        {
            "practice_id": practice_id,
            "equipment_sale_id": equipment_sale_id,
            "issue_description": issue_description,
            "status": "OPEN",
            "coverage_determination": None,
            "coverage_agreement_id": None,
            "estimate_cents": None,
            "parts_used": None,
            "labor_minutes": None,
            "customer_due_cents": None,
            "resolved_at": None,
            "_resolved_dt": None,
            "_plan_share_cents": 0,
            "_resolved_technician_id": None,
        }
    )
    STORES["service_tickets"][record["id"]] = record
    return envelope.success(pub(record), "object", 201)


@bp.get("/service-tickets/<rid>")
def get_service_ticket(rid):
    uid, role = auth_and_roles(TICKET_READ_ROLES)
    ticket = get_or_404("service_tickets", rid)
    pm_owns_or_403(role, uid, ticket["practice_id"])
    return envelope.success(pub(ticket))


@bp.get("/service-tickets")
def list_service_tickets():
    uid, role = auth_and_roles(TICKET_READ_ROLES)
    records = list(STORES["service_tickets"].values())
    if role == "PracticeManager":
        records = [r for r in records if r["practice_id"] == uid]
    for field in ("practice_id", "equipment_sale_id", "coverage_agreement_id"):
        value = request.args.get(field)
        if value is not None:
            records = [r for r in records if r.get(field) == value]
    records = sorted_default(records)
    page, pagination = paginate(records)
    return envelope.success([pub(r) for r in page], "array", 200, pagination)


@bp.post("/service-tickets/<rid>/assess-coverage")
def assess_coverage(rid):
    auth_and_roles(["ServiceDispatcher"])
    ticket = get_or_404("service_tickets", rid)
    if ticket["status"] != "OPEN":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Coverage can be assessed only from OPEN"
        )
    determination, agreement_id = determine_coverage(ticket["equipment_sale_id"])
    ticket["coverage_determination"] = determination
    ticket["coverage_agreement_id"] = agreement_id
    if determination == "BILLABLE":
        ticket["estimate_cents"] = DIAGNOSTIC_ESTIMATE_CENTS
        ticket["status"] = "AWAITING_APPROVAL"
    else:
        ticket["status"] = "COVERAGE_ASSESSED"
    touch(ticket)
    return envelope.success(pub(ticket))


@bp.post("/service-tickets/<rid>/approve-estimate")
def approve_estimate(rid):
    uid, role = auth_and_roles(["PracticeManager"])
    ticket = get_or_404("service_tickets", rid)
    pm_owns_or_403(role, uid, ticket["practice_id"])
    if ticket["status"] != "AWAITING_APPROVAL":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Only an AWAITING_APPROVAL ticket can be estimate-approved",
        )
    ticket["status"] = "COVERAGE_ASSESSED"
    touch(ticket)
    return envelope.success(pub(ticket))


def _ticket_job(ticket_id, status=None):
    for job in STORES["dispatch_jobs"].values():
        if job["service_ticket_id"] != ticket_id:
            continue
        if status is None or job["status"] == status:
            return job
    return None


@bp.post("/service-tickets/<rid>/dispatch")
def dispatch_ticket(rid):
    auth_and_roles(["ServiceDispatcher"])
    ticket = get_or_404("service_tickets", rid)
    data = body()

    _, req_start = v_dt(data, "scheduled_start")
    _, req_end = v_dt(data, "scheduled_end")
    if not req_end > req_start:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "scheduled_end must be strictly after scheduled_start",
        )

    if ticket["status"] != "COVERAGE_ASSESSED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only a COVERAGE_ASSESSED ticket can be dispatched"
        )
    if _ticket_job(ticket["id"], status="SCHEDULED") is not None:
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Ticket already has a SCHEDULED dispatch job"
        )

    practice = STORES["practices"][ticket["practice_id"]]
    technician = select_dispatch_technician(practice, req_start, req_end)

    job = base_record()
    job.update(
        {
            "service_ticket_id": ticket["id"],
            "technician_id": technician["id"],
            "scheduled_start": data["scheduled_start"],
            "scheduled_end": data["scheduled_end"],
            "status": "SCHEDULED",
            "_start_dt": req_start,
            "_end_dt": req_end,
        }
    )
    STORES["dispatch_jobs"][job["id"]] = job

    ticket["status"] = "DISPATCHED"
    touch(ticket)
    return envelope.success(pub(job))


def _validate_parts_shape(data):
    parts = v_list(data, "parts_used")
    cleaned = []
    for entry in parts:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400, "Each parts_used entry must be an object")
        product_id = entry.get("product_id")
        if not isinstance(product_id, str) or product_id == "":
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "Each parts_used entry requires a product_id"
            )
        quantity = entry.get("quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "parts_used quantity must be an integer > 0"
            )
        cleaned.append({"product_id": product_id, "quantity": quantity})
    return cleaned


@bp.post("/service-tickets/<rid>/resolve")
def resolve_ticket(rid):
    uid, role = auth_and_roles(["FieldTechnician"])
    ticket = get_or_404("service_tickets", rid)
    data = body()

    # Ownership: the caller must be the technician on the SCHEDULED job.
    job = None
    if ticket["status"] == "DISPATCHED":
        job = _ticket_job(ticket["id"], status="SCHEDULED")
        if job is not None and job["technician_id"] != uid:
            raise ApiError(
                "ERR_FORBIDDEN",
                403,
                "Only the assigned technician may resolve this ticket",
            )

    # Body FK existence (rung 3).
    raw_parts = data.get("parts_used")
    if isinstance(raw_parts, list):
        for entry in raw_parts:
            if isinstance(entry, dict):
                pid = entry.get("product_id")
                if isinstance(pid, str) and pid != "" and pid not in STORES["products"]:
                    raise ApiError(
                        "ERR_RESOURCE_NOT_FOUND",
                        404,
                        "parts_used product_id does not reference an existing product",
                    )

    # Shape (rung 4).
    parts_used = _validate_parts_shape(data)
    labor_minutes = v_int(data, "labor_minutes", min_val=0)

    # State (rung 5).
    if ticket["status"] != "DISPATCHED" or job is None:
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only a DISPATCHED ticket can be resolved"
        )

    # Domain: every part line must be sufficiently stocked on the van.
    technician = STORES["technicians"][job["technician_id"]]
    for entry in parts_used:
        van_entry = next(
            (
                e
                for e in technician["van_stock"]
                if e["product_id"] == entry["product_id"]
            ),
            None,
        )
        if van_entry is None or entry["quantity"] > van_entry["quantity_on_van"]:
            raise ApiError(
                "ERR_PARTS_NOT_ON_VAN",
                422,
                "parts_used exceeds the assigned technician's van stock",
            )

    # Hop 1: debit van stock.
    for entry in parts_used:
        van_entry = next(
            e for e in technician["van_stock"] if e["product_id"] == entry["product_id"]
        )
        van_entry["quantity_on_van"] -= entry["quantity"]
    if parts_used:
        touch(technician)

    # Hop 2: money.
    gross, customer_due, plan_share = compute_repair_cost(
        ticket, parts_used, labor_minutes
    )
    if ticket["coverage_determination"] == "SERVICE_PLAN" and plan_share:
        agreement = STORES["coverage_agreements"][ticket["coverage_agreement_id"]]
        agreement["used_cents"] += plan_share
        # Hop 3: a capped plan at or above its cap flips to EXHAUSTED.
        cap = agreement["coverage_cap_cents"]
        if cap is not None and agreement["used_cents"] >= cap:
            agreement["status"] = "EXHAUSTED"
        touch(agreement)

    # Hop 4: complete the dispatch job and stamp the ticket.
    job["status"] = "COMPLETED"
    touch(job)

    t = now()
    ticket["status"] = "RESOLVED"
    ticket["parts_used"] = parts_used
    ticket["labor_minutes"] = labor_minutes
    ticket["customer_due_cents"] = customer_due
    ticket["resolved_at"] = fmt_ts(t)
    ticket["_resolved_dt"] = t
    ticket["_plan_share_cents"] = plan_share
    ticket["_resolved_technician_id"] = technician["id"]
    touch(ticket)
    return envelope.success(pub(ticket))


@bp.post("/service-tickets/<rid>/reopen")
def reopen_ticket(rid):
    uid, role = auth_and_roles(["PracticeManager", "ServiceDispatcher"])
    ticket = get_or_404("service_tickets", rid)
    pm_owns_or_403(role, uid, ticket["practice_id"])
    if ticket["status"] != "RESOLVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a RESOLVED ticket can be reopened")
    if now() - ticket["_resolved_dt"] > timedelta(days=REOPEN_WINDOW_DAYS):
        raise ApiError(
            "ERR_REOPEN_WINDOW_EXPIRED",
            422,
            "Reopen is allowed only within 30 days of resolution",
        )

    # Compensation: credit parts back onto the resolving technician's van.
    technician_id = ticket["_resolved_technician_id"]
    if technician_id is not None and ticket["parts_used"]:
        technician = STORES["technicians"].get(technician_id)
        if technician is not None:
            for entry in ticket["parts_used"]:
                van_entry = next(
                    (
                        e
                        for e in technician["van_stock"]
                        if e["product_id"] == entry["product_id"]
                    ),
                    None,
                )
                if van_entry is not None:
                    van_entry["quantity_on_van"] += entry["quantity"]
                else:
                    technician["van_stock"].append(
                        {
                            "product_id": entry["product_id"],
                            "quantity_on_van": entry["quantity"],
                            "min_quantity": 0,
                        }
                    )
            touch(technician)

    # Compensation: credit a SERVICE_PLAN's utilization back (floor 0) and
    # revive an EXHAUSTED plan whose utilization drops below its cap.
    if (
        ticket["coverage_determination"] == "SERVICE_PLAN"
        and ticket["coverage_agreement_id"] is not None
    ):
        agreement = STORES["coverage_agreements"].get(ticket["coverage_agreement_id"])
        if agreement is not None:
            agreement["used_cents"] = max(
                0, agreement["used_cents"] - ticket["_plan_share_cents"]
            )
            cap = agreement["coverage_cap_cents"]
            if (
                agreement["status"] == "EXHAUSTED"
                and cap is not None
                and agreement["used_cents"] < cap
            ):
                agreement["status"] = "ACTIVE"
            touch(agreement)

    # Clear the coverage/resolution fields.
    ticket["status"] = "OPEN"
    ticket["coverage_determination"] = None
    ticket["coverage_agreement_id"] = None
    ticket["customer_due_cents"] = None
    ticket["parts_used"] = None
    ticket["labor_minutes"] = None
    ticket["resolved_at"] = None
    ticket["_resolved_dt"] = None
    ticket["_plan_share_cents"] = 0
    ticket["_resolved_technician_id"] = None
    touch(ticket)
    return envelope.success(pub(ticket))


@bp.post("/service-tickets/<rid>/close")
def close_ticket(rid):
    uid, role = auth_and_roles(["PracticeManager", "ServiceDispatcher"])
    ticket = get_or_404("service_tickets", rid)
    pm_owns_or_403(role, uid, ticket["practice_id"])
    if ticket["status"] != "RESOLVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a RESOLVED ticket can be closed")
    ticket["status"] = "CLOSED"
    touch(ticket)
    return envelope.success(pub(ticket))


# ---------------------------------------------------------------------------
# Dispatch jobs
# ---------------------------------------------------------------------------


@bp.get("/dispatch-jobs/<rid>")
def get_dispatch_job(rid):
    auth_and_roles(JOB_ROLES)
    return envelope.success(pub(get_or_404("dispatch_jobs", rid)))


@bp.get("/dispatch-jobs")
def list_dispatch_jobs():
    auth_and_roles(JOB_ROLES)
    records = list(STORES["dispatch_jobs"].values())
    for field in ("service_ticket_id", "technician_id"):
        value = request.args.get(field)
        if value is not None:
            records = [r for r in records if r.get(field) == value]
    records = sorted_default(records)
    page, pagination = paginate(records)
    return envelope.success([pub(r) for r in page], "array", 200, pagination)


# ---------------------------------------------------------------------------
# Coverage agreements
# ---------------------------------------------------------------------------


@bp.post("/coverage-agreements")
def create_coverage_agreement():
    auth_and_roles(["SalesRep"])
    data = body()
    fk_exists(data, "practice_id", "practices")
    fk_exists(data, "equipment_sale_id", "equipment_sales")

    practice_id = v_str(data, "practice_id")
    equipment_sale_id = v_str(data, "equipment_sale_id")
    coverage_type = v_str(data, "coverage_type")
    if coverage_type != "SERVICE_PLAN":
        # WARRANTY rows are system-created by equipment accept.
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "coverage_type must be SERVICE_PLAN for client-registered agreements",
        )
    start_raw, start_dt = v_dt(data, "start_date")
    end_raw, end_dt = v_dt(data, "end_date")
    deductible = v_int(data, "deductible_cents", required=False, default=0, min_val=0)
    cap = v_int(data, "coverage_cap_cents", required=False, default=None, min_val=0)

    record = base_record()
    record.update(
        {
            "practice_id": practice_id,
            "equipment_sale_id": equipment_sale_id,
            "coverage_type": "SERVICE_PLAN",
            "start_date": start_raw,
            "end_date": end_raw,
            "deductible_cents": deductible,
            "coverage_cap_cents": cap,
            "used_cents": 0,
            "status": "ACTIVE",
            "_start_dt": start_dt,
            "_end_dt": end_dt,
        }
    )
    STORES["coverage_agreements"][record["id"]] = record
    return envelope.success(pub(record), "object", 201)


@bp.get("/coverage-agreements/<rid>")
def get_coverage_agreement(rid):
    uid, role = auth_and_roles(AGREEMENT_READ_ROLES)
    agreement = get_or_404("coverage_agreements", rid)
    pm_owns_or_403(role, uid, agreement["practice_id"])
    lazy_expire_agreement(agreement)
    return envelope.success(pub(agreement))


@bp.get("/coverage-agreements")
def list_coverage_agreements():
    uid, role = auth_and_roles(AGREEMENT_READ_ROLES)
    records = list(STORES["coverage_agreements"].values())
    if role == "PracticeManager":
        records = [r for r in records if r["practice_id"] == uid]
    for field in ("practice_id", "equipment_sale_id"):
        value = request.args.get(field)
        if value is not None:
            records = [r for r in records if r.get(field) == value]
    for record in records:
        lazy_expire_agreement(record)
    records = sorted_default(records)
    page, pagination = paginate(records)
    return envelope.success([pub(r) for r in page], "array", 200, pagination)
