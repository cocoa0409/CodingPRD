"""Recalls: draft, activation sweep, close (PRD §3.6)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_RECALL_NOT_FOUND,
    ERR_SUPPLIER_NOT_FOUND,
    ERR_INVALID_WINDOW,
    ERR_RECALL_INVALID_STATE,
    ERR_RECALL_UNRESOLVED_UNITS,
)
from middleware import require_roles, ALL_ROLES
from response import success_object
from services import domain
from util import fmt_dt
from validate import get_body, req_str, req_dt, req_str_list

bp = Blueprint("recalls", __name__)

ANY = ALL_ROLES


def get_recall_or_404(recall_id: str) -> dict:
    recall = db["recalls"].get(recall_id)
    if recall is None:
        raise_error(ERR_RECALL_NOT_FOUND, f"recall {recall_id} does not exist")
    return recall


@bp.route("/tissue-bank/recalls", methods=["POST"])
def create_recall():
    require_roles({"QualityManager"})
    body = get_body()
    supplier_id = req_str(body, "supplier_id")
    lot_numbers = req_str_list(body, "lot_numbers", min_items=1)
    window_start = req_dt(body, "received_window_start")
    window_end = req_dt(body, "received_window_end")
    reason = req_str(body, "reason")
    if window_end < window_start:
        raise_error(ERR_INVALID_WINDOW, "received_window_end must not fall before received_window_start")
    supplier = db["suppliers"].get(supplier_id)
    if supplier is None:
        raise_error(ERR_SUPPLIER_NOT_FOUND, f"supplier {supplier_id} does not exist")
    recall = {
        "supplier_id": supplier["id"],
        "lot_numbers": lot_numbers,
        "received_window_start": fmt_dt(window_start),
        "received_window_end": fmt_dt(window_end),
        "reason": reason,
        "status": "DRAFT",
        "closure_reason": "NONE",
        "affected_unit_count": 0,
        "activated_at": None,
        "_window_start": window_start,
        "_window_end": window_end,
    }
    domain.stamp_new(recall)
    db["recalls"][recall["id"]] = recall
    return success_object(domain.recall_json(recall), status=201)


@bp.route("/tissue-bank/recalls/<recall_id>", methods=["GET"])
def get_recall(recall_id):
    require_roles(ANY)
    return success_object(domain.recall_json(get_recall_or_404(recall_id)))


@bp.route("/tissue-bank/recalls/<recall_id>/activate", methods=["POST"])
def activate_recall(recall_id):
    require_roles({"QualityManager"})
    recall = get_recall_or_404(recall_id)
    if recall["status"] != "DRAFT":
        raise_error(ERR_RECALL_INVALID_STATE, f"recall status is {recall['status']}, not DRAFT")
    now = domain.CLOCK.now()
    recall["status"] = "ACTIVE"
    recall["activated_at"] = fmt_dt(now)
    domain.touch(recall)
    # deterministic sweep: received_at ASC, tie created_at ASC
    matched = sorted(
        (u for u in db["units"].values() if domain.recall_matches_unit(recall, u)),
        key=lambda u: (u["_received_dt"], u["_created_dt"], u["_seq"]),
    )
    for u in matched:
        if u["status"] == "AVAILABLE":
            u["status"] = "QUARANTINED"
            u["hold_reason"] = "RECALL"
            domain.touch(u)
        elif u["status"] == "RESERVED":
            u["status"] = "QUARANTINED"
            u["hold_reason"] = "RECALL"
            domain.touch(u)
            res = domain.active_reservation_for_unit(u["id"])
            if res is not None:
                res["status"] = "RELEASED"
                res["release_reason"] = "RECALL"
                domain.touch(res)
        elif u["status"] == "QUARANTINED":
            if u["hold_reason"] == "NONE":
                u["hold_reason"] = "RECALL"
                domain.touch(u)
        elif u["status"] == "ISSUED":
            u["recall_flag"] = True
            domain.touch(u)
        # terminal states (IMPLANTED / DISCARDED / RETURNED_TO_SUPPLIER / EXPIRED)
        # are counted but not modified
    recall["affected_unit_count"] = len(matched)
    if len(matched) == 0:
        # zero-match auto-transition: DRAFT -> CLOSED (NO_MATCH)
        recall["status"] = "CLOSED"
        recall["closure_reason"] = "NO_MATCH"
    # supplier score model: the recall joins the provisional active-recall term
    supplier = db["suppliers"].get(recall["supplier_id"])
    if supplier is not None:
        domain.maybe_auto_suspend(supplier)
    return success_object(domain.recall_json(recall))


@bp.route("/tissue-bank/recalls/<recall_id>/close", methods=["POST"])
def close_recall(recall_id):
    require_roles({"QualityManager"})
    recall = get_recall_or_404(recall_id)
    if recall["status"] != "ACTIVE":
        raise_error(ERR_RECALL_INVALID_STATE, f"recall status is {recall['status']}, not ACTIVE")
    unresolved = any(
        domain.recall_matches_unit(recall, u)
        and u["status"] == "QUARANTINED"
        and u["hold_reason"] == "RECALL"
        for u in db["units"].values()
    )
    if unresolved:
        raise_error(ERR_RECALL_UNRESOLVED_UNITS, "units matching the recall scope remain QUARANTINED with hold_reason RECALL")
    recall["status"] = "CLOSED"
    recall["closure_reason"] = "RESOLVED"
    domain.touch(recall)
    supplier = db["suppliers"].get(recall["supplier_id"])
    if supplier is not None:
        domain.maybe_auto_suspend(supplier)
    return success_object(domain.recall_json(recall))
