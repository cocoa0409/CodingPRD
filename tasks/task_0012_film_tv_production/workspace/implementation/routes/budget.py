"""Budget categories and change orders."""
import copy
from flask import Blueprint, g, request

import errors as E
from db import store, init_common, touch
from middleware import require_roles
from response import ok_object, ok_array
from body import get_json_body, require_string, require_enum, require_int
from services.occ import check_version
from services.audit import log as audit_log
from services.budget import (
    categories_for_production,
    find_category,
    recompute_posture,
    category_alert_state,
)
from services.serializers import serialize_budget_category, serialize_change_order, paginate


bp = Blueprint("budget", __name__)


CATEGORY_CODES = {"CAST", "CREW", "EQUIPMENT", "LOCATION", "POST", "MISC"}
CHANGE_SOURCES = {"REALLOCATION", "RESERVE_DRAW"}


def _get_production(pid):
    p = store.productions.get(pid)
    if not p:
        E.not_found(f"Production {pid} not found")
    return p


@bp.route("/productions/<pid>/budget-categories", methods=["POST"])
@require_roles("FinanceController")
def create_budget_category(pid):
    body = get_json_body()
    with store.lock:
        p = _get_production(pid)
        if p.get("posture") == "FROZEN":
            E.posture_blocked("Production posture is FROZEN")
        code = require_enum(body, "code", CATEGORY_CODES)
        planned = require_int(body, "planned_cents", minv=0)
        # Sum check: existing planned + new + reserve <= total_budget
        existing = sum(c.get("planned_cents", 0) for c in categories_for_production(pid))
        if existing + planned + p["reserve_fund_cents"] > p["total_budget_cents"]:
            E.budget_overallocated("Sum of planned_cents + reserve > total_budget")
        # Don't allow duplicate code
        for c in categories_for_production(pid):
            if c["code"] == code:
                E.validation_err("BudgetCategory with this code already exists for production")
        rec = {
            "production_id": pid,
            "code": code,
            "planned_cents": planned,
            "committed_cents": 0,
            "actual_cents": 0,
            "alert_state": "OK",
        }
        init_common(rec)
        store.budget_categories[rec["id"]] = rec
        return ok_object(serialize_budget_category(rec), http_status=201)


@bp.route("/productions/<pid>/budget-categories", methods=["GET"])
@require_roles("LineProducer", "FinanceController")
def list_budget_categories(pid):
    _get_production(pid)
    from middleware import parse_pagination
    limit, offset = parse_pagination()
    items = categories_for_production(pid)
    page, total, has_more = paginate(items, limit, offset)
    return ok_array(
        [serialize_budget_category(c) for c in page],
        limit, offset, total, has_more,
    )


@bp.route("/change-orders", methods=["POST"])
@require_roles("LineProducer")
def create_change_order():
    body = get_json_body()
    with store.lock:
        production_id = require_string(body, "production_id")
        category_id = require_string(body, "category_id")
        delta = body.get("delta_cents")
        if not isinstance(delta, int) or isinstance(delta, bool):
            E.validation_err("delta_cents must be an integer")
        justification = require_string(body, "justification", allow_empty=True)
        source = require_enum(body, "source", CHANGE_SOURCES)
        prod = store.productions.get(production_id)
        if not prod:
            E.reference_mismatch(f"Production {production_id} not found")
        cat = store.budget_categories.get(category_id)
        if not cat:
            E.reference_mismatch(f"Category {category_id} not found")
        if cat["production_id"] != production_id:
            E.reference_mismatch("Category does not belong to specified production")
        if prod.get("posture") == "FROZEN":
            E.posture_blocked("Production posture is FROZEN")
        rec = {
            "production_id": production_id,
            "category_id": category_id,
            "delta_cents": delta,
            "justification": justification,
            "requested_by": g.user_id,
            "approved_by": None,
            "source": source,
            "status": "PENDING",
        }
        init_common(rec)
        store.change_orders[rec["id"]] = rec
        return ok_object(serialize_change_order(rec), http_status=201)


def _get_change_order(cid):
    co = store.change_orders.get(cid)
    if not co:
        E.not_found(f"ChangeOrder {cid} not found")
    return co


@bp.route("/change-orders/<cid>/approve", methods=["POST"])
@require_roles("FinanceController")
def approve_change_order(cid):
    body = get_json_body()
    override_reason = (request.headers.get("X-Override-Reason", "") or "").strip()
    with store.lock:
        co = _get_change_order(cid)
        check_version(co, body)
        prod = store.productions.get(co["production_id"])
        if not prod:
            E.not_found("Production not found")
        if co["status"] != "PENDING":
            E.invalid_state("approve requires PENDING")
        # Posture FROZEN blocks
        if prod.get("posture") == "FROZEN":
            E.posture_blocked("Production posture is FROZEN")
        # Posture RED gates RESERVE_DRAW unless override
        if co["source"] == "RESERVE_DRAW" and prod.get("posture") == "RED" and not override_reason:
            E.posture_blocked("Production posture is RED; X-Override-Reason required for RESERVE_DRAW")
        # Segregation
        if g.user_id == co["requested_by"]:
            E.segregation_of_duties("Approver must differ from requester")
        # Production must be in PLANNING or IN_PRODUCTION
        if prod["status"] not in {"PLANNING", "IN_PRODUCTION"}:
            E.invalid_state("Production must be PLANNING or IN_PRODUCTION")

        # Reserve sufficiency for RESERVE_DRAW with positive delta
        if co["source"] == "RESERVE_DRAW" and co["delta_cents"] > 0:
            if prod.get("reserve_fund_cents", 0) < co["delta_cents"]:
                E.reserve_insufficient("Reserve fund insufficient for delta_cents")

        # Budget overallocation: sum across categories + reserve <= total
        cat = store.budget_categories.get(co["category_id"])
        if not cat:
            E.not_found("Category vanished")
        all_cats = categories_for_production(prod["id"])
        new_planned_sum = sum(c.get("planned_cents", 0) for c in all_cats) + co["delta_cents"]
        # Reserve will decrement if RESERVE_DRAW
        new_reserve = prod["reserve_fund_cents"]
        if co["source"] == "RESERVE_DRAW":
            new_reserve -= co["delta_cents"]
        if new_planned_sum + new_reserve > prod["total_budget_cents"]:
            E.budget_overallocated("Approval would overallocate budget")

        # Apply
        before_co = copy.deepcopy(co)
        co["status"] = "APPROVED"
        co["approved_by"] = g.user_id
        touch(co)
        cat["planned_cents"] = cat.get("planned_cents", 0) + co["delta_cents"]
        touch(cat)
        if co["source"] == "RESERVE_DRAW":
            prod["reserve_fund_cents"] = prod["reserve_fund_cents"] - co["delta_cents"]
            touch(prod)
        # alert_state recomputed on serialization (derived) — explicit assign
        cat["alert_state"] = category_alert_state(cat)
        recompute_posture(prod, actor_user_id=g.user_id)

        # Audit logs
        audit_log(
            production_id=prod["id"],
            actor_user_id=g.user_id,
            action="BUDGET_ADJUSTMENT",
            subject_entity="ChangeOrder",
            subject_id=cid,
            before=before_co,
            after=copy.deepcopy(co),
        )
        if co["source"] == "RESERVE_DRAW":
            audit_log(
                production_id=prod["id"],
                actor_user_id=g.user_id,
                action="RESERVE_DRAW",
                subject_entity="ChangeOrder",
                subject_id=cid,
                before=before_co,
                after=copy.deepcopy(co),
            )
        return ok_object(serialize_change_order(co))


@bp.route("/change-orders/<cid>/reject", methods=["POST"])
@require_roles("FinanceController")
def reject_change_order(cid):
    body = get_json_body()
    with store.lock:
        co = _get_change_order(cid)
        check_version(co, body)
        prod = store.productions.get(co["production_id"])
        if prod and prod.get("posture") == "FROZEN":
            E.posture_blocked("Production posture is FROZEN")
        if co["status"] != "PENDING":
            E.invalid_state("reject requires PENDING")
        if g.user_id == co["requested_by"]:
            E.segregation_of_duties("Approver must differ from requester")
        co["status"] = "REJECTED"
        co["approved_by"] = g.user_id
        touch(co)
        return ok_object(serialize_change_order(co))


@bp.route("/change-orders/<cid>/cancel", methods=["POST"])
@require_roles("LineProducer")
def cancel_change_order(cid):
    body = get_json_body()
    with store.lock:
        co = _get_change_order(cid)
        check_version(co, body)
        prod = store.productions.get(co["production_id"])
        if prod and prod.get("posture") == "FROZEN":
            E.posture_blocked("Production posture is FROZEN")
        if co["status"] != "PENDING":
            E.invalid_state("cancel requires PENDING")
        if g.user_id != co["requested_by"]:
            E.forbidden("Only the requester may cancel this change order")
        co["status"] = "CANCELLED"
        touch(co)
        return ok_object(serialize_change_order(co))
