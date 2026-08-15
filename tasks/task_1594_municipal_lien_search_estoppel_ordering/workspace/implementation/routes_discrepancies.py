"""Discrepancy routes: file, get, start-review, resolve (with cascades)."""
from flask import Blueprint

import db
import services
from db import touch
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_NOT_ORDER_OWNER,
    ERR_SOD_VIOLATION,
    ERR_SUBJECT_NOT_IN_ORDER,
    ERR_DISCREPANCY_NOT_APPLICABLE,
    ERR_CLAIM_AMOUNT_INVALID,
    MAX_CLAIM_CENTS,
)
from helpers import body, req_str, is_int, _MISSING
from middleware import require_roles, require_any_role
from response import success

bp = Blueprint("discrepancies", __name__)


def get_discrepancy_or_404(did):
    d = db.discrepancies.get(did)
    if d is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Discrepancy not found")
    return d


@bp.post("/discrepancies")
def create_discrepancy():
    uid = require_roles("TitleAgent")
    b = body()
    # --- body shape ---
    search_order_id = req_str(b, "search_order_id")
    subject_type = req_str(b, "subject_type")
    if subject_type not in services.SUBJECT_TYPES:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid subject_type")
    subject_id = req_str(b, "subject_id")
    discrepancy_type = req_str(b, "discrepancy_type")
    if discrepancy_type not in services.DISCREPANCY_TYPES:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid discrepancy_type")
    claimed = b.get("claimed_amount_cents", _MISSING)
    if claimed is _MISSING or not is_int(claimed):
        raise ApiError(ERR_INVALID_REQUEST, 400, "claimed_amount_cents is required and must be an integer")
    description = req_str(b, "description")
    # --- existence ---
    order = db.search_orders.get(search_order_id)
    if order is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Search order not found")
    subject = None
    if subject_type == "SEARCH_ORDER":
        subject = db.search_orders.get(subject_id)
    elif subject_type == "RESEARCH_TASK":
        subject = db.research_tasks.get(subject_id)
    else:
        subject = db.estoppel_orders.get(subject_id)
    if subject is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Discrepancy subject not found")
    # --- ownership ---
    if uid != order["title_agent_id"]:
        raise ApiError(ERR_NOT_ORDER_OWNER, 403, "Only the owning TitleAgent may file a discrepancy")
    # --- structural business rules ---
    if subject_type == "SEARCH_ORDER":
        belongs = subject_id == search_order_id
    else:
        belongs = subject.get("search_order_id") == search_order_id
    if not belongs:
        raise ApiError(ERR_SUBJECT_NOT_IN_ORDER, 409, "Subject does not belong to the given search order")
    if discrepancy_type == "MISSED_ITEM" and order["status"] != "DELIVERED":
        raise ApiError(
            ERR_DISCREPANCY_NOT_APPLICABLE, 409,
            "MISSED_ITEM may only be filed on a delivered order",
        )
    # --- fiscal ---
    if claimed <= 0 or claimed > MAX_CLAIM_CENTS:
        raise ApiError(
            ERR_CLAIM_AMOUNT_INVALID, 422,
            f"claimed_amount_cents must be between 1 and {MAX_CLAIM_CENTS}",
        )
    d = {
        "id": db.new_id(), "search_order_id": search_order_id,
        "subject_type": subject_type, "subject_id": subject_id,
        "discrepancy_type": discrepancy_type, "claimed_amount_cents": claimed,
        "description": description, "filed_by_user_id": uid,
        "post_delivery": order["status"] == "DELIVERED",
        "status": "OPEN", "resolution_outcome": None,
        "confirmed_amount_cents": None, "confirmed_liability_cents": 0,
        "resolved_by_user_id": None,
    }
    db.stamp(d)
    db.discrepancies[d["id"]] = d
    touch(order)  # pending_claims_cents advanced
    return success(services.ser_discrepancy(d), 201)


@bp.get("/discrepancies/<did>")
def get_discrepancy(did):
    require_any_role()
    return success(services.ser_discrepancy(get_discrepancy_or_404(did)))


@bp.post("/discrepancies/<did>/start-review")
def start_review(did):
    require_roles("QAReviewer")
    d = get_discrepancy_or_404(did)
    if d["status"] != "OPEN":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION, 409,
            f"Discrepancy in {d['status']} cannot start review",
        )
    d["status"] = "UNDER_REVIEW"
    touch(d)
    return success(services.ser_discrepancy(d))


@bp.post("/discrepancies/<did>/resolve")
def resolve_discrepancy(did):
    uid = require_roles("QAReviewer")
    d = get_discrepancy_or_404(did)
    if d["status"] != "UNDER_REVIEW":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION, 409,
            f"Discrepancy in {d['status']} cannot be resolved",
        )
    b = body()
    outcome = b.get("resolution_outcome")
    if outcome not in services.RESOLUTION_OUTCOMES:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid resolution_outcome")
    confirmed_amount = b.get("confirmed_amount_cents")
    if confirmed_amount is not None and not is_int(confirmed_amount):
        raise ApiError(ERR_INVALID_REQUEST, 400, "confirmed_amount_cents must be an integer")
    # Segregation of duties: resolver differs from filer.
    if uid == d["filed_by_user_id"]:
        raise ApiError(ERR_SOD_VIOLATION, 403, "Resolver must differ from the filer")
    if outcome == "CONFIRMED_CORRECTION" and d["discrepancy_type"] == "MISSED_ITEM":
        if confirmed_amount is None or confirmed_amount <= 0:
            raise ApiError(
                ERR_INVALID_REQUEST, 400,
                "confirmed_amount_cents > 0 is required to confirm a MISSED_ITEM",
            )
    order = db.search_orders.get(d["search_order_id"])
    d["status"] = "RESOLVED"
    d["resolution_outcome"] = outcome
    d["resolved_by_user_id"] = uid
    if confirmed_amount is not None:
        d["confirmed_amount_cents"] = confirmed_amount
    d["confirmed_liability_cents"] = 0
    touch(d)
    if order is not None:
        if outcome == "CONFIRMED_CORRECTION":
            _apply_confirmed_cascades(d, order)
        touch(order)  # pending claims released (+ possible cascades)
    return success(services.ser_discrepancy(d))


def _apply_confirmed_cascades(d, order):
    """The three confirmed-correction cascades of PRD 3.8, applied together."""
    oid = order["id"]
    # (a) Post-delivery confirmed MISSED_ITEM: cap-limited liability + DELIVERED revert.
    if d["post_delivery"] and d["discrepancy_type"] == "MISSED_ITEM":
        delivered = [
            x for x in db.deliveries.values()
            if x["search_order_id"] == oid and x["status"] in ("DELIVERED", "ACKNOWLEDGED")
        ]
        cap = max(delivered, key=lambda x: x["_seq"])["liability_cap_cents"] if delivered else 0
        d["confirmed_liability_cents"] = min(d["confirmed_amount_cents"] or 0, cap or 0)
        if order["status"] == "DELIVERED":
            services.revert_order_to_research(
                order, void_ready=False, supersede_delivered=True, bump=False,
            )
    # (b) Confirmed correction on a research task: reopen COMPLETED -> IN_PROGRESS.
    if d["subject_type"] == "RESEARCH_TASK":
        task = db.research_tasks.get(d["subject_id"])
        if task is not None and task["status"] == "COMPLETED":
            task["status"] = "IN_PROGRESS"
            task["completed_by_user_id"] = None
            touch(task)
    # (c) Pre-delivery confirmed correction during verification: revert the pipeline.
    if not d["post_delivery"] and order["status"] in ("VERIFICATION", "READY_FOR_DELIVERY"):
        services.revert_order_to_research(order, void_ready=True, bump=False)
