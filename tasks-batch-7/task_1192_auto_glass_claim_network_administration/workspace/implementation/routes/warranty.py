"""Warranty claims: file against a completed work order, auditor decision."""

from datetime import timedelta

from flask import Blueprint, request

from db import store, base_fields, touch, sorted_created, now_dt, now_iso
from errors import (
    ApiError,
    ERR_WORK_ORDER_NOT_FOUND,
    ERR_WARRANTY_CLAIM_NOT_FOUND,
    ERR_RESOURCE_OWNERSHIP_MISMATCH,
    ERR_WORK_ORDER_NOT_COMPLETED,
    ERR_WARRANTY_ALREADY_OPEN,
    ERR_WARRANTY_WINDOW_EXPIRED,
    ERR_WARRANTY_NOT_FILED,
    ERR_INVALID_REQUEST,
)
from middleware import (
    get_context,
    body_json,
    req_str,
    req_enum,
    opt_str,
    pagination_params,
    paginate,
    ALL_ROLES,
    ROLE_POLICYHOLDER,
    ROLE_NETWORK_AUDITOR,
)
from response import success_object, success_list
from serialize import warranty_claim_view, work_order_view

bp = Blueprint("warranty", __name__)

MOBILE_WINDOW_DAYS = 365
IN_SHOP_WINDOW_DAYS = 730
DECISIONS = {"APPROVE_REWORK", "DENY"}


def _get_wo(wid):
    wo = store.work_orders.get(wid)
    if wo is None:
        raise ApiError(ERR_WORK_ORDER_NOT_FOUND, 404, "Work order does not exist")
    return wo


def _get_wc(wcid):
    wc = store.warranty_claims.get(wcid)
    if wc is None:
        raise ApiError(ERR_WARRANTY_CLAIM_NOT_FOUND, 404, "Warranty claim does not exist")
    return wc


@bp.route("/work-orders/<wid>/warranty-claims", methods=["POST"])
def file_warranty_claim(wid):
    uid, _role = get_context([ROLE_POLICYHOLDER])
    wo = _get_wo(wid)
    claim = store.claims.get(wo["claim_id"])
    if claim is None or claim["policyholder_id"] != uid:
        raise ApiError(
            ERR_RESOURCE_OWNERSHIP_MISMATCH,
            403,
            "Policyholder may file warranty claims only on work orders of their own claims",
        )
    if wo["status"] != "COMPLETED":
        raise ApiError(ERR_WORK_ORDER_NOT_COMPLETED, 409, "Warranty claim requires WorkOrder COMPLETED")
    data = body_json(required=True)
    issue_description = req_str(data, "issue_description")
    for other in store.warranty_claims.values():
        if other["original_work_order_id"] == wid and other["status"] in ("FILED", "APPROVED_REWORK"):
            raise ApiError(
                ERR_WARRANTY_ALREADY_OPEN,
                409,
                "Another WarrantyClaim of the same work order is FILED or APPROVED_REWORK",
            )
    window_days = MOBILE_WINDOW_DAYS if wo.get("service_mode") == "MOBILE" else IN_SHOP_WINDOW_DAYS
    completed_dt = wo.get("_completed_dt")
    if completed_dt is not None and now_dt() > completed_dt + timedelta(days=window_days):
        raise ApiError(ERR_WARRANTY_WINDOW_EXPIRED, 422, "Warranty filing window has expired")
    wc = base_fields()
    wc.update(
        {
            "original_work_order_id": wid,
            "issue_description": issue_description,
            "filed_at": now_iso(),
            "decision_notes": None,
            "status": "FILED",
        }
    )
    store.warranty_claims[wc["id"]] = wc
    return success_object(warranty_claim_view(wc), status=201)


@bp.route("/work-orders/<wid>/warranty-claims", methods=["GET"])
def list_wo_warranty_claims(wid):
    get_context(ALL_ROLES)
    _get_wo(wid)
    limit, offset = pagination_params()
    items = sorted_created(
        [w for w in store.warranty_claims.values() if w["original_work_order_id"] == wid]
    )
    page, total = paginate(items, limit, offset)
    return success_list([warranty_claim_view(w) for w in page], limit, offset, total)


@bp.route("/warranty-claims/<wcid>", methods=["GET"])
def get_warranty_claim(wcid):
    get_context(ALL_ROLES)
    return success_object(warranty_claim_view(_get_wc(wcid)))


@bp.route("/warranty-claims/<wcid>/work-orders", methods=["GET"])
def list_warranty_work_orders(wcid):
    get_context(ALL_ROLES)
    _get_wc(wcid)
    limit, offset = pagination_params()
    items = sorted_created([w for w in store.work_orders.values() if w.get("warranty_claim_id") == wcid])
    page, total = paginate(items, limit, offset)
    return success_list([work_order_view(w) for w in page], limit, offset, total)


@bp.route("/warranty-claims/<wcid>/decide", methods=["POST"])
def decide_warranty_claim(wcid):
    get_context([ROLE_NETWORK_AUDITOR])
    wc = _get_wc(wcid)
    if wc["status"] != "FILED":
        raise ApiError(ERR_WARRANTY_NOT_FILED, 409, "decide requires WarrantyClaim FILED")
    data = body_json(required=True)
    decision = req_enum(data, "decision", DECISIONS)
    notes = opt_str(data, "decision_notes", None)
    if notes is not None:
        wc["decision_notes"] = notes
    if decision == "DENY":
        wc["status"] = "DENIED"
        touch(wc)
        return success_object(warranty_claim_view(wc))

    # APPROVE_REWORK
    original = store.work_orders.get(wc["original_work_order_id"])
    wc["status"] = "APPROVED_REWORK"
    touch(wc)
    if original is not None:
        rework = base_fields()
        rework.update(
            {
                "claim_id": original["claim_id"],
                "shop_id": original["shop_id"],
                "warranty_claim_id": wc["id"],
                "service_mode": None,
                "scheduled_start": None,
                "scheduled_end": None,
                "completed_at": None,
                "status": "OFFERED",
            }
        )
        store.work_orders[rework["id"]] = rework
        shop = store.shops.get(original["shop_id"])
        if shop is not None:
            shop["warranty_strike_count"] += 1
            if shop["warranty_strike_count"] >= 3:
                shop["network_status"] = "SUSPENDED"
            touch(shop)
    return success_object(warranty_claim_view(wc))
