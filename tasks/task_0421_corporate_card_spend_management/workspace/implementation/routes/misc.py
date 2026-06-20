"""RewardAccount, SpendAuthorization, ErpSyncBatch (PRD §3.8-§3.10)."""
from flask import Blueprint

import errors
from db import db, stamp_create, touch, LOCK
from middleware import get_user_context, require_role, get_json_body
from response import success, success_list
from services.common import (
    get_or_404, require_fields, require_positive_int, validate_enum,
    paginate, serialize, to_dt, AUTH_BUFFER_DAYS,
    q as _q, filter_items as _filter,
)

bp = Blueprint("misc", __name__)


# ----------------------------------------------------- RewardAccount
@bp.route("/reward-accounts/<ra_id>", methods=["GET"])
def get_reward_account(ra_id):
    get_user_context()
    with LOCK:
        return success(serialize(get_or_404(db.reward_accounts, ra_id)), 200)


@bp.route("/reward-accounts", methods=["GET"])
def list_reward_accounts():
    get_user_context()
    with LOCK:
        items = list(db.reward_accounts.values())
        items = _filter(items, {"company_id": _q("company_id")})
        page, limit, offset, total = paginate(items)
        return success_list(page, limit, offset, total)


@bp.route("/reward-accounts/<ra_id>/redeem", methods=["POST"])
def redeem_reward(ra_id):
    _, role = get_user_context()
    require_role(role, {"FinanceAdmin"})
    body = get_json_body()
    with LOCK:
        ra = get_or_404(db.reward_accounts, ra_id)
        amount = require_positive_int(body, "amount_cents")
        if amount > ra["balance_points_cents"]:
            raise errors.err(errors.ERR_INSUFFICIENT_REWARD_BALANCE,
                             "Redemption exceeds available reward balance.")
        ra["redeemed_points_cents"] += amount
        ra["balance_points_cents"] = ra["accrued_points_cents"] - ra["redeemed_points_cents"]
        touch(ra)
        return success(serialize(ra), 200)


# ----------------------------------------------------- SpendAuthorization
@bp.route("/spend-authorizations", methods=["POST"])
def create_spend_authorization():
    _, role = get_user_context()
    require_role(role, {"FinanceAdmin", "Approver"})
    body = get_json_body()
    require_fields(body, ["company_id", "scope", "employee_id",
                          "budget_cents", "window_start", "window_end"])
    validate_enum(body, "scope", {"EMPLOYEE", "CARD"})
    with LOCK:
        get_or_404(db.companies, body["company_id"])
        get_or_404(db.employees, body["employee_id"])
        scope = body["scope"]
        card_id = body.get("card_id")
        if scope == "CARD":
            if card_id is None:
                raise errors.err(errors.ERR_VALIDATION, "card_id is required for CARD scope.")
            get_or_404(db.cards, card_id)
        else:
            card_id = None

        budget = require_positive_int(body, "budget_cents")
        ws = to_dt(body["window_start"])
        we = to_dt(body["window_end"])
        if not (we > ws):
            raise errors.err(errors.ERR_INVALID_AMOUNT,
                             "window_end must be strictly after window_start.")

        # Interval-conflict checks against ACTIVE authorizations.
        if scope == "EMPLOYEE":
            for ex in db.spend_authorizations.values():
                if (ex["scope"] == "EMPLOYEE" and ex["status"] == "ACTIVE"
                        and ex["employee_id"] == body["employee_id"]):
                    ex_ws = to_dt(ex["window_start"])
                    ex_we = to_dt(ex["window_end"])
                    # half-open overlap: new.start < ex.end AND ex.start < new.end
                    if ws < ex_we and ex_ws < we:
                        raise errors.err(errors.ERR_AUTH_WINDOW_OVERLAP,
                                         "Window overlaps an active employee-scope authorization.")
        else:  # CARD scope, buffered adjacency
            from datetime import timedelta
            buf = timedelta(days=AUTH_BUFFER_DAYS)
            for ex in db.spend_authorizations.values():
                if (ex["scope"] == "CARD" and ex["status"] == "ACTIVE"
                        and ex["card_id"] == card_id):
                    ex_ws = to_dt(ex["window_start"])
                    ex_we = to_dt(ex["window_end"])
                    # acceptable only if new.start >= ex.end + buf OR new.end + buf <= ex.start
                    ok = (ws >= ex_we + buf) or (we + buf <= ex_ws)
                    if not ok:
                        raise errors.err(errors.ERR_AUTH_WINDOW_TOO_CLOSE,
                                         "Window is within the buffer of an active card-scope authorization.")

        auth = {
            "company_id": body["company_id"],
            "scope": scope,
            "employee_id": body["employee_id"],
            "card_id": card_id,
            "budget_cents": budget,
            "window_start": body["window_start"],
            "window_end": body["window_end"],
            "status": "ACTIVE",
        }
        stamp_create(auth)
        db.spend_authorizations[auth["id"]] = auth
        return success(serialize(auth), 201)


@bp.route("/spend-authorizations/<auth_id>", methods=["GET"])
def get_spend_authorization(auth_id):
    get_user_context()
    with LOCK:
        return success(serialize(get_or_404(db.spend_authorizations, auth_id)), 200)


@bp.route("/spend-authorizations", methods=["GET"])
def list_spend_authorizations():
    get_user_context()
    with LOCK:
        items = list(db.spend_authorizations.values())
        items = _filter(items, {
            "company_id": _q("company_id"),
            "employee_id": _q("employee_id"),
            "card_id": _q("card_id"),
            "scope": _q("scope"),
            "status": _q("status"),
        })
        page, limit, offset, total = paginate(items)
        return success_list(page, limit, offset, total)


@bp.route("/spend-authorizations/<auth_id>/consume", methods=["POST"])
def consume_spend_authorization(auth_id):
    _, role = get_user_context()
    require_role(role, {"FinanceAdmin"})
    get_json_body()
    with LOCK:
        auth = get_or_404(db.spend_authorizations, auth_id)
        if auth["status"] != "ACTIVE":
            raise errors.err(errors.ERR_INVALID_STATE, "Authorization is not ACTIVE.")
        auth["status"] = "CONSUMED"
        touch(auth)
        return success(serialize(auth), 200)


@bp.route("/spend-authorizations/<auth_id>/cancel", methods=["POST"])
def cancel_spend_authorization(auth_id):
    _, role = get_user_context()
    require_role(role, {"FinanceAdmin"})
    get_json_body()
    with LOCK:
        auth = get_or_404(db.spend_authorizations, auth_id)
        if auth["status"] != "ACTIVE":
            raise errors.err(errors.ERR_INVALID_STATE, "Authorization is not ACTIVE.")
        auth["status"] = "CANCELLED"
        touch(auth)
        return success(serialize(auth), 200)


# ----------------------------------------------------- ErpSyncBatch
@bp.route("/erp-sync-batches", methods=["POST"])
def build_erp_batch():
    _, role = get_user_context()
    require_role(role, {"FinanceAdmin"})
    body = get_json_body()
    require_fields(body, ["company_id", "statement_id"])
    with LOCK:
        get_or_404(db.companies, body["company_id"])
        stmt = get_or_404(db.statements, body["statement_id"])
        if stmt["status"] not in ("CLOSED", "DUE", "PAST_DUE", "PAID"):
            raise errors.err(errors.ERR_INVALID_STATE,
                             "Statement must be CLOSED/DUE/PAST_DUE/PAID.")
        entry_count = 0
        total_debits = 0
        for tx in db.transactions.values():
            if (tx["company_id"] == body["company_id"]
                    and tx.get("statement_id") == stmt["id"]
                    and tx["auth_status"] == "SETTLED"
                    and tx.get("gl_account_id") is not None):
                entry_count += 1
                total_debits += tx["settled_amount_cents"]
        batch = {
            "company_id": body["company_id"],
            "statement_id": stmt["id"],
            "entry_count": entry_count,
            "total_debits_cents": total_debits,
            "status": "BUILT",
        }
        stamp_create(batch)
        db.erp_sync_batches[batch["id"]] = batch
        return success(serialize(batch), 201)


@bp.route("/erp-sync-batches/<batch_id>", methods=["GET"])
def get_erp_batch(batch_id):
    _, role = get_user_context()
    require_role(role, {"FinanceAdmin", "Auditor"})
    with LOCK:
        return success(serialize(get_or_404(db.erp_sync_batches, batch_id)), 200)


@bp.route("/erp-sync-batches", methods=["GET"])
def list_erp_batches():
    _, role = get_user_context()
    require_role(role, {"FinanceAdmin", "Auditor"})
    with LOCK:
        items = list(db.erp_sync_batches.values())
        items = _filter(items, {
            "company_id": _q("company_id"),
            "statement_id": _q("statement_id"),
            "status": _q("status"),
        })
        page, limit, offset, total = paginate(items)
        return success_list(page, limit, offset, total)


@bp.route("/erp-sync-batches/<batch_id>/post", methods=["POST"])
def post_erp_batch(batch_id):
    _, role = get_user_context()
    require_role(role, {"FinanceAdmin"})
    get_json_body()
    with LOCK:
        batch = get_or_404(db.erp_sync_batches, batch_id)
        if batch["status"] != "BUILT":
            raise errors.err(errors.ERR_INVALID_STATE, "Batch is not BUILT.")
        batch["status"] = "POSTED"
        touch(batch)
        return success(serialize(batch), 200)


@bp.route("/erp-sync-batches/<batch_id>/discard", methods=["POST"])
def discard_erp_batch(batch_id):
    _, role = get_user_context()
    require_role(role, {"FinanceAdmin"})
    get_json_body()
    with LOCK:
        batch = get_or_404(db.erp_sync_batches, batch_id)
        if batch["status"] != "BUILT":
            raise errors.err(errors.ERR_INVALID_STATE, "Batch is not BUILT.")
        batch["status"] = "DISCARDED"
        touch(batch)
        return success(serialize(batch), 200)
