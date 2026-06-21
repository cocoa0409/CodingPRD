"""CashDrawerSession endpoints (PRD §3.2, §2.8)."""
from flask import Blueprint, request

from db import DB
from middleware import auth_context, require_role
from common import (
    stamp_create, touch, public_view, get_json_body, as_int, as_str,
    parse_pagination, paginate,
)
from response import success, success_list
from errors import (
    err, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND, ERR_INVALID_STATE,
    ERR_INVALID_REQUEST,
)
from services import sale_ops

bp = Blueprint("cash_sessions", __name__)


def _open_or_close_requested_exists(store_id, exclude_id=None):
    for s in DB.cash_sessions.values():
        if s["id"] == exclude_id:
            continue
        if s["store_id"] == store_id and s["status"] in ("OPEN", "CLOSE_REQUESTED"):
            return True
    return False


@bp.route("/cash-sessions", methods=["POST"])
def open_session():
    _, role = auth_context()
    require_role(role, {"StoreManager"})
    body = get_json_body()
    store_id = as_str(body, "store_id")
    opening_float_cents = as_int(body, "opening_float_cents", minimum=0)
    with DB.lock:
        if store_id not in DB.stores:
            raise err(ERR_REFERENCE_NOT_FOUND, "store_id not found")
        # at most one OPEN or CLOSE_REQUESTED per store (PRD §2.8)
        if _open_or_close_requested_exists(store_id):
            raise err(ERR_INVALID_STATE, "Store already has an open or close-requested session")
        session = {
            "store_id": store_id,
            "opening_float_cents": opening_float_cents,
            "expected_cash_cents": opening_float_cents,
            "counted_cash_cents": None,
            "variance_cents": None,
            "status": "OPEN",
        }
        stamp_create(session)
        DB.cash_sessions[session["id"]] = session
        return success(public_view(session), status=201)


@bp.route("/cash-sessions/<session_id>", methods=["GET"])
def get_session(session_id):
    _, role = auth_context()
    require_role(role, {"StoreManager", "Cashier"})
    with DB.lock:
        session = DB.cash_sessions.get(session_id)
        if session is None:
            raise err(ERR_NOT_FOUND, "Cash session not found")
        return success(public_view(session))


@bp.route("/cash-sessions", methods=["GET"])
def list_sessions():
    _, role = auth_context()
    require_role(role, {"StoreManager", "Cashier"})
    limit, offset = parse_pagination()
    store_id = request.args.get("store_id")
    status = request.args.get("status")
    with DB.lock:
        recs = list(DB.cash_sessions.values())
        if store_id is not None:
            recs = [r for r in recs if r["store_id"] == store_id]
        if status is not None:
            recs = [r for r in recs if r["status"] == status]
        items, total = paginate(recs, limit, offset)
        return success_list(items, limit, offset, total)


@bp.route("/cash-sessions/<session_id>/request-close", methods=["POST"])
def request_close(session_id):
    _, role = auth_context()
    require_role(role, {"StoreManager"})
    with DB.lock:
        session = DB.cash_sessions.get(session_id)
        if session is None:
            raise err(ERR_NOT_FOUND, "Cash session not found")
        if session["status"] != "OPEN":
            raise err(ERR_INVALID_STATE, "Session is not OPEN")
        # no bound sale may be TENDERING (PRD §3.2)
        for sale in DB.sales.values():
            if sale.get("cash_session_id") == session_id and sale["settlement_status"] == "TENDERING":
                raise err(ERR_INVALID_STATE, "A bound sale is still TENDERING")
        # freeze expected_cash for the count
        sale_ops._recompute_expected_cash(DB, session)
        session["status"] = "CLOSE_REQUESTED"
        touch(session)
        return success(public_view(session))


@bp.route("/cash-sessions/<session_id>/reconcile", methods=["POST"])
def reconcile(session_id):
    _, role = auth_context()
    require_role(role, {"StoreManager"})
    body = get_json_body()
    with DB.lock:
        session = DB.cash_sessions.get(session_id)
        if session is None:
            raise err(ERR_NOT_FOUND, "Cash session not found")
        if session["status"] != "CLOSE_REQUESTED":
            raise err(ERR_INVALID_STATE, "Session is not CLOSE_REQUESTED")
        # counted_cash_cents required (PRD §3.2)
        counted = as_int(body, "counted_cash_cents")
        session["counted_cash_cents"] = counted
        session["variance_cents"] = counted - session["expected_cash_cents"]
        session["status"] = "RECONCILED"
        touch(session)
        return success(public_view(session))


@bp.route("/cash-sessions/<session_id>/reopen", methods=["POST"])
def reopen(session_id):
    _, role = auth_context()
    require_role(role, {"StoreManager"})
    with DB.lock:
        session = DB.cash_sessions.get(session_id)
        if session is None:
            raise err(ERR_NOT_FOUND, "Cash session not found")
        if session["status"] != "CLOSE_REQUESTED":
            raise err(ERR_INVALID_STATE, "Session is not CLOSE_REQUESTED")
        session["counted_cash_cents"] = None
        session["variance_cents"] = None
        session["status"] = "OPEN"
        sale_ops._recompute_expected_cash(DB, session)
        touch(session)
        return success(public_view(session))


@bp.route("/cash-sessions/<session_id>/force-close", methods=["POST"])
def force_close(session_id):
    _, role = auth_context()
    require_role(role, {"StoreManager"})
    with DB.lock:
        session = DB.cash_sessions.get(session_id)
        if session is None:
            raise err(ERR_NOT_FOUND, "Cash session not found")
        if session["status"] != "OPEN":
            raise err(ERR_INVALID_STATE, "Session is not OPEN")
        # cascade: void every bound DRAFT/TENDERING sale, reversing tenders,
        # restocking inventory, restoring loyalty (PRD §3.2, §2.10).
        for sale in DB.sales.values():
            if sale.get("cash_session_id") != session_id:
                continue
            if sale["settlement_status"] in ("DRAFT", "TENDERING"):
                sale_ops.void_sale(DB, sale)
                sale["tendered_cents"] = sum(
                    DB.tender_lines[t]["amount_cents"]
                    for t in sale.get("_tenders", []) if t in DB.tender_lines
                )
                touch(sale)
        session["status"] = "FORCE_CLOSED"
        touch(session)
        return success(public_view(session))
