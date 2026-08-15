"""SearchOrder routes: create/get/patch, lifecycle actions, summary."""
from flask import Blueprint

import db
import services
from db import touch
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_STALE_VERSION,
    ERR_NOT_ORDER_OWNER,
    ERR_SOD_VIOLATION,
    ERR_ASSOCIATION_JURISDICTION_MISMATCH,
    ERR_NO_STATUTE_IN_FORCE,
    ERR_SERVICE_DATE_PAST,
    ERR_CLOSING_DATE_PASSED,
    ERR_RUSH_NOT_SUPPORTED,
    ERR_RUSH_CAPACITY_FULL,
    ERR_DUPLICATE_ACTIVE_SEARCH,
    ERR_TASKS_OUTSTANDING,
    ERR_ESTOPPEL_NOT_CURRENT,
    ERR_ESTOPPEL_STALE_FOR_CLOSING,
    ERR_PAYOFF_MISMATCH,
)
from helpers import (
    body, req_str, opt_bool, req_date, is_int, paginate, _MISSING,
)
from middleware import require_roles, require_any_role
from response import success

bp = Blueprint("search_orders", __name__)

EDITABLE_STATES = ("INTAKE", "RESEARCH_IN_PROGRESS", "VERIFICATION", "READY_FOR_DELIVERY")


def get_order_or_404(oid):
    o = db.search_orders.get(oid)
    if o is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Search order not found")
    return o


# --------------------------------------------------------------------- create

@bp.post("/search-orders")
def create_search_order():
    uid = require_roles("TitleAgent")
    b = body()
    # --- body shape (ERR_INVALID_REQUEST) ---
    address = req_str(b, "property_address")
    parcel = req_str(b, "parcel_number")
    closing_date = req_date(b, "closing_date")
    order_class = req_str(b, "order_class")
    if order_class not in ("STANDARD", "RUSH"):
        raise ApiError(ERR_INVALID_REQUEST, 400, "order_class must be STANDARD or RUSH")
    extended_coverage = opt_bool(b, "extended_coverage", False)
    association_id = b.get("association_id")
    if association_id is not None and not isinstance(association_id, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "association_id must be a string or null")
    service_date = None
    rush_candidate = None
    if order_class == "RUSH":
        if b.get("service_date") is None or b.get("jurisdiction_id") is None:
            raise ApiError(
                ERR_INVALID_REQUEST, 400,
                "RUSH orders require service_date and jurisdiction_id",
            )
        service_date = req_date(b, "service_date")
        rush_candidate = b["jurisdiction_id"]
        if not isinstance(rush_candidate, str) or not rush_candidate:
            raise ApiError(ERR_INVALID_REQUEST, 400, "jurisdiction_id must be a string")
    # --- existence (ERR_NOT_FOUND) ---
    jurisdiction = None
    if order_class == "RUSH":
        jurisdiction = db.jurisdictions.get(rush_candidate)
        if jurisdiction is None:
            raise ApiError(ERR_NOT_FOUND, 404, "Jurisdiction not found")
    if association_id is not None and association_id not in db.associations:
        raise ApiError(ERR_NOT_FOUND, 404, "Association not found")
    # --- temporal validity (422) ---
    clock_date = db.today()
    if order_class == "RUSH" and service_date < clock_date:
        raise ApiError(ERR_SERVICE_DATE_PAST, 422, "service_date is before the current clock date")
    if closing_date < clock_date:
        raise ApiError(ERR_CLOSING_DATE_PASSED, 422, "closing_date is before the current clock date")
    # --- business constraints (409) ---
    if order_class == "RUSH":
        for d in db.departments.values():
            if (d["jurisdiction_id"] == rush_candidate and d["status"] == "ACTIVE"
                    and not d["supports_rush"]):
                raise ApiError(
                    ERR_RUSH_NOT_SUPPORTED, 409,
                    "An ACTIVE department of the jurisdiction does not support rush",
                )
        occupants = sum(
            1 for o in db.search_orders.values()
            if o["order_class"] == "RUSH"
            and o["rush_candidate_jurisdiction_id"] == rush_candidate
            and o["service_date"] == service_date
            and o["status"] != "CANCELLED"
        )
        if occupants >= jurisdiction["rush_daily_capacity"]:
            raise ApiError(
                ERR_RUSH_CAPACITY_FULL, 409,
                "Rush daily capacity reached for this jurisdiction and service_date",
            )
    # Parcel service-window overlap: CLOSED interval [created date, closing_date].
    for o in db.search_orders.values():
        if o["parcel_number"] != parcel or o["status"] == "CANCELLED":
            continue
        if o["_created_date"] <= closing_date and clock_date <= o["closing_date"]:
            raise ApiError(
                ERR_DUPLICATE_ACTIVE_SEARCH, 409,
                "Another non-cancelled order for this parcel has an overlapping service window",
            )
    o = {
        "id": db.new_id(), "title_agent_id": uid, "property_address": address,
        "parcel_number": parcel, "association_id": association_id,
        "jurisdiction_id": None,
        "rush_candidate_jurisdiction_id": rush_candidate,
        "statute_id": None, "order_class": order_class,
        "service_date": service_date, "closing_date": closing_date,
        "extended_coverage": extended_coverage, "status": "INTAKE",
        "research_completed_by_user_id": None,
        "payoff_verified_by_user_id": None, "payoff_verified_at": None,
    }
    db.stamp(o)
    db.search_orders[o["id"]] = o
    return success(services.ser_order(o), 201)


# --------------------------------------------------------------------- read

@bp.get("/search-orders/<oid>")
def get_search_order(oid):
    require_any_role()
    return success(services.ser_order(get_order_or_404(oid)))


@bp.get("/search-orders/<oid>/summary")
def get_search_order_summary(oid):
    require_any_role()
    o = get_order_or_404(oid)
    payoff, fees, claims, liability = services.order_totals(o)
    coverage_fee, cap = services.liability_cap_projection(fees, o["extended_coverage"])
    tasks, estoppels, discs, dels = services.order_children(oid)
    task_counts = {s: 0 for s in ("PENDING", "IN_PROGRESS", "COMPLETED", "UNABLE_TO_REACH", "CANCELLED")}
    for t in tasks:
        task_counts[t["status"]] = task_counts.get(t["status"], 0) + 1
    open_discs = sum(1 for d in discs if d["status"] in ("OPEN", "UNDER_REVIEW"))
    latest_delivery = max(dels, key=lambda d: d["_seq"])["status"] if dels else None
    return success({
        "total_payoff_cents": payoff,
        "total_fees_cents": fees,
        "pending_claims_cents": claims,
        "total_liability_cents": liability,
        "projected_coverage_fee_cents": coverage_fee,
        "projected_liability_cap_cents": cap,
        "task_counts": task_counts,
        "estoppel_count": len(estoppels),
        "open_discrepancy_count": open_discs,
        "latest_delivery_status": latest_delivery,
    })


# --------------------------------------------------------------------- patch

@bp.patch("/search-orders/<oid>")
def patch_search_order(oid):
    uid = require_roles("TitleAgent")
    o = get_order_or_404(oid)
    if o["status"] not in EDITABLE_STATES:
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION, 409,
            f"Order in {o['status']} cannot be updated",
        )
    b = body()
    # --- body shape ---
    expected = b.get("expected_search_order_version", _MISSING)
    if expected is _MISSING or not is_int(expected):
        raise ApiError(
            ERR_INVALID_REQUEST, 400,
            "expected_search_order_version is required and must be an integer",
        )
    has_closing = "closing_date" in b
    has_assoc = "association_id" in b
    if not has_closing and not has_assoc:
        raise ApiError(
            ERR_INVALID_REQUEST, 400,
            "At least one of closing_date or association_id must be provided",
        )
    new_closing = None
    if has_closing:
        if b["closing_date"] is None:
            raise ApiError(ERR_INVALID_REQUEST, 400, "closing_date must not be null")
        new_closing = req_date(b, "closing_date")
    new_assoc = None
    if has_assoc and b["association_id"] is not None:
        if not isinstance(b["association_id"], str) or not b["association_id"]:
            raise ApiError(ERR_INVALID_REQUEST, 400, "association_id must be a string or null")
        new_assoc = b["association_id"]
    # --- existence ---
    assoc_obj = None
    if new_assoc is not None:
        assoc_obj = db.associations.get(new_assoc)
        if assoc_obj is None:
            raise ApiError(ERR_NOT_FOUND, 404, "Association not found")
    # --- state guard on association change ---
    assoc_changing = has_assoc and new_assoc != o["association_id"]
    if assoc_changing:
        for e in db.estoppel_orders.values():
            if e["search_order_id"] == oid and e["status"] == "RECEIVED":
                raise ApiError(
                    ERR_INVALID_STATE_TRANSITION, 409,
                    "association_id cannot change while an estoppel is RECEIVED",
                )
    # --- ownership ---
    if uid != o["title_agent_id"]:
        raise ApiError(ERR_NOT_ORDER_OWNER, 403, "Only the owning TitleAgent may update this order")
    # --- OCC ---
    if expected != o["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_search_order_version does not match current version")
    # --- referential ---
    if (assoc_changing and assoc_obj is not None and o["jurisdiction_id"] is not None
            and assoc_obj["jurisdiction_id"] != o["jurisdiction_id"]):
        raise ApiError(
            ERR_ASSOCIATION_JURISDICTION_MISMATCH, 422,
            "Association belongs to a different jurisdiction than the order",
        )
    # --- temporal ---
    if has_closing and new_closing < db.today():
        raise ApiError(ERR_CLOSING_DATE_PASSED, 422, "closing_date is before the current clock date")
    # --- apply (order version advances by exactly 1) ---
    if has_closing:
        o["closing_date"] = new_closing
    if assoc_changing:
        for e in db.estoppel_orders.values():
            if e["search_order_id"] == oid and e["status"] in ("DRAFT", "ORDERED", "OVERDUE"):
                e["status"] = "CANCELLED"
                touch(e)
        o["association_id"] = new_assoc
        if new_assoc is not None and o["jurisdiction_id"] is not None:
            services.spawn_estoppel_draft(o, new_assoc)
    if has_closing and o["status"] in ("VERIFICATION", "READY_FOR_DELIVERY"):
        stale = any(
            e["status"] == "RECEIVED" and e["valid_through"] is not None
            and e["valid_through"] < o["closing_date"]
            for e in db.estoppel_orders.values()
            if e["search_order_id"] == oid
        )
        if stale:
            services.revert_order_to_research(o, void_ready=True, bump=False)
    touch(o)
    return success(services.ser_order(o))


# ------------------------------------------------------- lifecycle: identify

@bp.post("/search-orders/<oid>/identify-jurisdiction")
def identify_jurisdiction(oid):
    require_roles("ResearchAnalyst")
    o = get_order_or_404(oid)
    b = body()
    jurisdiction_id = b.get("jurisdiction_id")
    if not isinstance(jurisdiction_id, str) or not jurisdiction_id:
        raise ApiError(ERR_INVALID_REQUEST, 400, "jurisdiction_id is required")
    jurisdiction = db.jurisdictions.get(jurisdiction_id)
    if jurisdiction is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Jurisdiction not found")
    if o["status"] != "INTAKE":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION, 409,
            f"Order in {o['status']} cannot identify a jurisdiction",
        )
    if o["order_class"] == "RUSH" and jurisdiction_id != o["rush_candidate_jurisdiction_id"]:
        raise ApiError(
            ERR_INVALID_REQUEST, 400,
            "RUSH orders must identify the jurisdiction declared as capacity candidate",
        )
    if jurisdiction["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "Jurisdiction is not ACTIVE")
    statute = services.covering_statute(jurisdiction_id, db.today())
    if statute is None:
        raise ApiError(
            ERR_NO_STATUTE_IN_FORCE, 422,
            "No statute window covers the current clock date for this jurisdiction",
        )
    if o["association_id"] is not None:
        assoc = db.associations.get(o["association_id"])
        if assoc is not None and assoc["jurisdiction_id"] != jurisdiction_id:
            raise ApiError(
                ERR_ASSOCIATION_JURISDICTION_MISMATCH, 422,
                "Association belongs to a different jurisdiction",
            )
    o["jurisdiction_id"] = jurisdiction_id
    o["statute_id"] = statute["id"]
    o["status"] = "RESEARCH_IN_PROGRESS"
    active_depts = [
        d for d in db.departments.values()
        if d["jurisdiction_id"] == jurisdiction_id and d["status"] == "ACTIVE"
    ]
    for d in sorted(active_depts, key=lambda x: (x["created_at"], x["_seq"])):
        services.spawn_research_task(o, d)
    if o["association_id"] is not None:
        services.spawn_estoppel_draft(o, o["association_id"])
    touch(o)
    return success(services.ser_order(o))


# -------------------------------------------------------- lifecycle: cancel

@bp.post("/search-orders/<oid>/cancel")
def cancel_search_order(oid):
    uid = require_roles("TitleAgent")
    o = get_order_or_404(oid)
    if o["status"] not in EDITABLE_STATES:
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION, 409,
            f"Order in {o['status']} cannot be cancelled",
        )
    if uid != o["title_agent_id"]:
        raise ApiError(ERR_NOT_ORDER_OWNER, 403, "Only the owning TitleAgent may cancel this order")
    services.cancel_order_cascade(o)
    return success(services.ser_order(o))


# -------------------------------------------- lifecycle: submit for verify

@bp.post("/search-orders/<oid>/submit-for-verification")
def submit_for_verification(oid):
    uid = require_roles("ResearchAnalyst")
    o = get_order_or_404(oid)
    if o["status"] != "RESEARCH_IN_PROGRESS":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION, 409,
            f"Order in {o['status']} cannot be submitted for verification",
        )
    tasks, estoppels, _discs, _dels = services.order_children(oid)
    # Temporal check (priority 8) precedes structural checks (priority 9) per PRD 2.8.
    for e in estoppels:
        if (e["status"] == "RECEIVED" and e["valid_through"] is not None
                and e["valid_through"] < o["closing_date"]):
            raise ApiError(
                ERR_ESTOPPEL_STALE_FOR_CLOSING, 422,
                "An estoppel's valid_through is before the closing_date",
            )
    for t in tasks:
        if t["status"] not in ("COMPLETED", "UNABLE_TO_REACH"):
            raise ApiError(ERR_TASKS_OUTSTANDING, 409, "A research task is still outstanding")
    for e in estoppels:
        if e["status"] != "RECEIVED":
            raise ApiError(ERR_ESTOPPEL_NOT_CURRENT, 409, "An estoppel order is not RECEIVED")
    o["status"] = "VERIFICATION"
    o["research_completed_by_user_id"] = uid
    touch(o)
    return success(services.ser_order(o))


# --------------------------------------------------------- lifecycle: verify

@bp.post("/search-orders/<oid>/verify-payoff")
def verify_payoff(oid):
    uid = require_roles("QAReviewer")
    o = get_order_or_404(oid)
    if o["status"] != "VERIFICATION":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION, 409,
            f"Order in {o['status']} cannot be verified",
        )
    b = body()
    verified = b.get("verified_payoff_total_cents", _MISSING)
    if verified is _MISSING or not is_int(verified):
        raise ApiError(
            ERR_INVALID_REQUEST, 400,
            "verified_payoff_total_cents is required and must be an integer",
        )
    # Segregation of duties (priority 6) precedes the fiscal check (priority 10).
    if uid == o["research_completed_by_user_id"]:
        raise ApiError(ERR_SOD_VIOLATION, 403, "Verifier must differ from the research submitter")
    for t in db.research_tasks.values():
        if (t["search_order_id"] == oid and t["status"] == "COMPLETED"
                and t["completed_by_user_id"] == uid):
            raise ApiError(ERR_SOD_VIOLATION, 403, "Verifier must differ from every task completer")
    payoff, _fees, _claims, _liab = services.order_totals(o)
    if verified != payoff:
        raise ApiError(ERR_PAYOFF_MISMATCH, 409, "Verified payoff total does not match the computed total")
    o["status"] = "READY_FOR_DELIVERY"
    o["payoff_verified_by_user_id"] = uid
    o["payoff_verified_at"] = db.now()
    touch(o)
    return success(services.ser_order(o))


# --------------------------------------------------------- lifecycle: reject

@bp.post("/search-orders/<oid>/reject-verification")
def reject_verification(oid):
    require_roles("QAReviewer")
    o = get_order_or_404(oid)
    if o["status"] != "VERIFICATION":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION, 409,
            f"Order in {o['status']} cannot be rejected for verification",
        )
    b = body()
    reason = b.get("reason")
    if not isinstance(reason, str) or not reason:
        raise ApiError(ERR_INVALID_REQUEST, 400, "reason is required")
    o["status"] = "RESEARCH_IN_PROGRESS"
    o["payoff_verified_by_user_id"] = None
    o["payoff_verified_at"] = None
    touch(o)
    return success(services.ser_order(o))


# ------------------------------------------------------- child list endpoints

@bp.get("/search-orders/<oid>/research-tasks")
def list_order_research_tasks(oid):
    require_any_role()
    get_order_or_404(oid)
    items = [t for t in db.research_tasks.values() if t["search_order_id"] == oid]
    page, meta = paginate(items)
    return success([services.ser_task(t) for t in page], pagination=meta)


@bp.get("/search-orders/<oid>/estoppel-orders")
def list_order_estoppel_orders(oid):
    require_any_role()
    get_order_or_404(oid)
    items = [e for e in db.estoppel_orders.values() if e["search_order_id"] == oid]
    page, meta = paginate(items)
    return success([services.ser_estoppel(e) for e in page], pagination=meta)


@bp.get("/search-orders/<oid>/discrepancies")
def list_order_discrepancies(oid):
    require_any_role()
    get_order_or_404(oid)
    items = [d for d in db.discrepancies.values() if d["search_order_id"] == oid]
    page, meta = paginate(items)
    return success([services.ser_discrepancy(d) for d in page], pagination=meta)


@bp.get("/search-orders/<oid>/deliveries")
def list_order_deliveries(oid):
    require_any_role()
    get_order_or_404(oid)
    items = [d for d in db.deliveries.values() if d["search_order_id"] == oid]
    page, meta = paginate(items)
    return success([services.ser_delivery(d) for d in page], pagination=meta)
