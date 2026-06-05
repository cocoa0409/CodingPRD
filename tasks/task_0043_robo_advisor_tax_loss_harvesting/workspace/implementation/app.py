import os
import re
from datetime import datetime, timezone

from flask import Flask, request as flask_request

from clock import clock
from db import db, new_common, touch
from response import success, error_response, iso_ms
from errors import (
    ApiError, err,
    ERR_UNAUTHENTICATED, ERR_FORBIDDEN, ERR_NOT_FOUND, ERR_INVALID_REQUEST,
    ERR_DUPLICATE_RESOURCE, ERR_INVALID_STATE, ERR_ACCOUNT_NOT_OPERABLE,
    ERR_NOT_REBALANCE_DUE, ERR_STALE_ACCOUNT_VERSION, ERR_NOT_A_LOSS_LOT,
    ERR_SUBSTANTIALLY_IDENTICAL, ERR_REPLACEMENT_TOO_CORRELATED,
    ERR_SECURITY_DELISTED, ERR_NO_MODEL_FOR_SCORE, ERR_MODEL_RETIRED,
    ERR_QUARTER_ALREADY_REBALANCED, ERR_OPEN_LOTS_REMAIN, ERR_TAX_YEAR_NOT_CLOSED,
)
from calculations import (
    risk_score as compute_risk_score, market_value_cents, round_half_up,
    MAX_REPLACEMENT_CORRELATION,
)
import services

app = Flask(__name__)

# ----------------------------------------------------------------------------
# Domain enumerations (PRD §3)
# ----------------------------------------------------------------------------
ROLES = {"Advisor", "Compliance"}
ASSET_CLASSES = {"US_EQUITY", "INTL_EQUITY", "BOND", "REIT", "COMMODITY"}
LOT_SELECTIONS = {"FIFO", "HIFO"}
QUARTER_RE = re.compile(r"^\d{4}-Q[1-4]$")


# ----------------------------------------------------------------------------
# Error handling
# ----------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response("ERR_INVALID_REQUEST", str(e), 422)


# ----------------------------------------------------------------------------
# Body / parsing helpers
# ----------------------------------------------------------------------------
def get_body():
    try:
        body = flask_request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return body


def require(body, field):
    if field not in body or body[field] is None:
        raise err(ERR_INVALID_REQUEST, f"Missing required field: {field}")
    return body[field]


def require_int(body, field, minimum=None, maximum=None):
    v = require(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, f"{field} must be an integer.")
    if minimum is not None and v < minimum:
        raise err(ERR_INVALID_REQUEST, f"{field} must be >= {minimum}.")
    if maximum is not None and v > maximum:
        raise err(ERR_INVALID_REQUEST, f"{field} must be <= {maximum}.")
    return v


def parse_iso(value):
    if not isinstance(value, str):
        raise err(ERR_INVALID_REQUEST, "Invalid datetime.")
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, "Invalid ISO 8601 datetime.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ----------------------------------------------------------------------------
# Auth / RBAC (PRD §2.1)
# ----------------------------------------------------------------------------
def auth():
    """Returns (role, user_id). ERR_UNAUTHENTICATED if either header missing or
    role unrecognized."""
    role = flask_request.headers.get("X-User-Role")
    user_id = flask_request.headers.get("X-User-ID")
    if not user_id or not role or role not in ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or unrecognized authentication headers.")
    return role, user_id


def require_role(role, allowed):
    if role not in allowed:
        raise err(ERR_FORBIDDEN, f"Role {role} not permitted for this operation.")


# ----------------------------------------------------------------------------
# Pagination (PRD §2.3) — invalid values clamp to bounds
# ----------------------------------------------------------------------------
def paginate(items):
    args = flask_request.args
    limit = 10
    offset = 0
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            limit = 10
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            offset = 0
        if offset < 0:
            offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


def sorted_by_created(items):
    # PRD §2.3: list endpoints sort by created_at ascending. _created_seq is the
    # stable monotonic tie-break for resources minted in the same clock instant.
    return sorted(items, key=lambda x: (x["_created_dt"], x["_created_seq"]))


def find_or_404(store, _id):
    if _id is None or _id not in store:
        raise err(ERR_NOT_FOUND, "Referenced resource not found.")
    return store[_id]


# ============================================================================
# Serializers
# ============================================================================
def ser_security(s):
    return {
        "id": s["id"], "created_at": s["created_at"], "updated_at": s["updated_at"],
        "version": s["version"],
        "ticker": s["ticker"], "asset_class": s["asset_class"],
        "price_cents": s["price_cents"], "correlated_with": s["correlated_with"],
        "is_active": s["is_active"],
    }


def ser_model(m):
    return {
        "id": m["id"], "created_at": m["created_at"], "updated_at": m["updated_at"],
        "version": m["version"],
        "name": m["name"],
        "min_risk_score": m["min_risk_score"], "max_risk_score": m["max_risk_score"],
        "targets": m["targets"], "drift_threshold_pct": m["drift_threshold_pct"],
        "lot_selection": m["lot_selection"], "is_active": m["is_active"],
    }


def ser_account(a):
    # invested/total/drift/ytd are computed live so reads always reflect current prices.
    services.recompute_account_aggregates(a)
    return {
        "id": a["id"], "created_at": a["created_at"], "updated_at": a["updated_at"],
        "version": a["version"],
        "client_email": a["client_email"],
        "model_portfolio_id": a["model_portfolio_id"],
        "risk_score": a["risk_score"],
        "status": a["status"],
        "cash_balance_cents": a["cash_balance_cents"],
        "invested_value_cents": a["invested_value_cents"],
        "total_value_cents": a["total_value_cents"],
        "max_drift_pct": a["max_drift_pct"],
        "realized_gain_cents_ytd": a["realized_gain_cents_ytd"],
        "wash_sale_disallowed_cents_ytd": a["wash_sale_disallowed_cents_ytd"],
    }


def ser_questionnaire(q):
    return {
        "id": q["id"], "created_at": q["created_at"],
        "account_id": q["account_id"],
        "horizon_years": q["horizon_years"],
        "loss_tolerance": q["loss_tolerance"],
        "liquidity_need": q["liquidity_need"],
        "income_band": q["income_band"],
        "risk_score": q["risk_score"],
        "assigned_model_portfolio_id": q["assigned_model_portfolio_id"],
        "status": q["status"],
    }


def ser_lot(l):
    sec = db.securities.get(l["security_id"])
    if l["status"] == "OPEN" and sec is not None:
        mv = market_value_cents(l["quantity"], sec["price_cents"])
        unrealized = mv - l["cost_basis_cents"]
    else:
        mv = 0
        unrealized = 0
    return {
        "id": l["id"], "created_at": l["created_at"], "updated_at": l["updated_at"],
        "version": l["version"],
        "account_id": l["account_id"], "security_id": l["security_id"],
        "quantity": l["quantity"], "cost_basis_cents": l["cost_basis_cents"],
        "acquired_at": l["acquired_at"], "status": l["status"],
        "market_value_cents": mv, "unrealized_gain_cents": unrealized,
        "disposed_at": l.get("disposed_at"), "proceeds_cents": l.get("proceeds_cents"),
        "realized_gain_cents": l.get("realized_gain_cents"),
        "wash_sale_disallowed_cents": l.get("wash_sale_disallowed_cents", 0),
        "closed_by_harvest_id": l.get("closed_by_harvest_id"),
    }


def ser_harvest(h):
    return {
        "id": h["id"], "created_at": h["created_at"], "updated_at": h["updated_at"],
        "version": h["version"],
        "account_id": h["account_id"], "source_lot_id": h["source_lot_id"],
        "replacement_security_id": h["replacement_security_id"],
        "expected_account_version": h["expected_account_version"],
        "realized_loss_cents": h["realized_loss_cents"],
        "disallowed_loss_cents": h["disallowed_loss_cents"],
        "replacement_lot_id": h["replacement_lot_id"],
        "status": h["status"],
    }


def ser_rebalance(r):
    return {
        "id": r["id"], "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
        "account_id": r["account_id"],
        "expected_account_version": r["expected_account_version"],
        "quarter_label": r["quarter_label"],
        "trades_count": r["trades_count"],
        "cash_consumed_cents": r["cash_consumed_cents"],
        "status": r["status"],
    }


def ser_form(f):
    if f["status"] != "FINALIZED":
        compute_form_totals(f)
    return {
        "id": f["id"], "created_at": f["created_at"], "updated_at": f["updated_at"],
        "version": f["version"],
        "account_id": f["account_id"], "tax_year": f["tax_year"],
        "total_proceeds_cents": f["total_proceeds_cents"],
        "total_cost_basis_cents": f["total_cost_basis_cents"],
        "net_realized_gain_cents": f["net_realized_gain_cents"],
        "total_wash_sale_disallowed_cents": f["total_wash_sale_disallowed_cents"],
        "line_count": f["line_count"],
        "status": f["status"],
    }


# ============================================================================
# Security
# ============================================================================
@app.route("/securities", methods=["POST"])
def create_security():
    role, _ = auth()
    require_role(role, {"Advisor", "Compliance"})
    body = get_body()
    ticker = require(body, "ticker")
    asset_class = require(body, "asset_class")
    price_cents = require_int(body, "price_cents", minimum=1)
    correlated_with = body.get("correlated_with", [])

    if not isinstance(ticker, str) or not ticker.strip():
        raise err(ERR_INVALID_REQUEST, "ticker is required and non-empty.")
    if ticker != ticker.upper():
        raise err(ERR_INVALID_REQUEST, "ticker must be uppercase.")
    if asset_class not in ASSET_CLASSES:
        raise err(ERR_INVALID_REQUEST, "Invalid asset_class.")
    if correlated_with is None:
        correlated_with = []
    if not isinstance(correlated_with, list):
        raise err(ERR_INVALID_REQUEST, "correlated_with must be an array.")
    for entry in correlated_with:
        if not isinstance(entry, dict) or "ticker" not in entry or "correlation" not in entry:
            raise err(ERR_INVALID_REQUEST, "correlated_with entries need ticker and correlation.")
        c = entry["correlation"]
        if isinstance(c, bool) or not isinstance(c, (int, float)):
            raise err(ERR_INVALID_REQUEST, "correlation must be a number.")
        if c < -1.0 or c > 1.0:
            raise err(ERR_INVALID_REQUEST, "correlation must be within [-1.0, 1.0].")

    # uniqueness (ERR_DUPLICATE_RESOURCE)
    for s in db.securities.values():
        if s["ticker"] == ticker:
            raise err(ERR_DUPLICATE_RESOURCE, "ticker already exists.")

    s = new_common()
    s.update({
        "ticker": ticker, "asset_class": asset_class, "price_cents": price_cents,
        "correlated_with": correlated_with, "is_active": True,
    })
    db.securities[s["id"]] = s
    return success(ser_security(s), 201)


@app.route("/securities/<sid>", methods=["GET"])
def get_security(sid):
    role, _ = auth()
    require_role(role, {"Advisor", "Compliance"})
    return success(ser_security(find_or_404(db.securities, sid)), 200)


@app.route("/securities", methods=["GET"])
def list_securities():
    role, _ = auth()
    require_role(role, {"Advisor", "Compliance"})
    asset_class = flask_request.args.get("asset_class")
    items = [s for s in db.securities.values()
             if asset_class is None or s["asset_class"] == asset_class]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success([ser_security(s) for s in page], 200, meta)


@app.route("/securities/<sid>/price", methods=["PATCH"])
def update_security_price(sid):
    role, _ = auth()
    require_role(role, {"Advisor", "Compliance"})
    s = find_or_404(db.securities, sid)
    body = get_body()
    price_cents = require_int(body, "price_cents", minimum=1)
    s["price_cents"] = price_cents
    touch(s)
    # Bubble-up: every account holding OPEN lots in this security recomputes drift.
    affected_account_ids = {
        l["account_id"] for l in db.tax_lots.values()
        if l["security_id"] == sid and l["status"] == "OPEN"
    }
    for aid in affected_account_ids:
        acct = db.accounts.get(aid)
        if acct is not None:
            services.bubble_up(acct)
    return success(ser_security(s), 200)


@app.route("/securities/<sid>/delist", methods=["POST"])
def delist_security(sid):
    role, _ = auth()
    require_role(role, {"Compliance"})
    s = find_or_404(db.securities, sid)
    s["is_active"] = False
    touch(s)
    return success(ser_security(s), 200)


# ============================================================================
# ModelPortfolio
# ============================================================================
@app.route("/model-portfolios", methods=["POST"])
def create_model():
    role, _ = auth()
    require_role(role, {"Advisor"})
    body = get_body()
    name = require(body, "name")
    min_rs = require_int(body, "min_risk_score", minimum=0, maximum=100)
    max_rs = require_int(body, "max_risk_score", minimum=0, maximum=100)
    targets = require(body, "targets")
    drift_threshold = require_int(body, "drift_threshold_pct", minimum=1)
    lot_selection = body.get("lot_selection", "FIFO")
    if lot_selection is None:
        lot_selection = "FIFO"

    if not isinstance(name, str) or not name.strip():
        raise err(ERR_INVALID_REQUEST, "name is required and non-empty.")
    if max_rs < min_rs:
        raise err(ERR_INVALID_REQUEST, "max_risk_score must be >= min_risk_score.")
    if lot_selection not in LOT_SELECTIONS:
        raise err(ERR_INVALID_REQUEST, "Invalid lot_selection.")
    if not isinstance(targets, list) or not targets:
        raise err(ERR_INVALID_REQUEST, "targets must be a non-empty array.")
    total = 0
    for t in targets:
        if not isinstance(t, dict) or "asset_class" not in t or "target_pct" not in t:
            raise err(ERR_INVALID_REQUEST, "Each target needs asset_class and target_pct.")
        if t["asset_class"] not in ASSET_CLASSES:
            raise err(ERR_INVALID_REQUEST, "Invalid target asset_class.")
        tp = t["target_pct"]
        if isinstance(tp, bool) or not isinstance(tp, int):
            raise err(ERR_INVALID_REQUEST, "target_pct must be an integer.")
        total += tp
    if total != 100:
        raise err(ERR_INVALID_REQUEST, "targets must sum to exactly 100.")

    m = new_common()
    m.update({
        "name": name, "min_risk_score": min_rs, "max_risk_score": max_rs,
        "targets": targets, "drift_threshold_pct": drift_threshold,
        "lot_selection": lot_selection, "is_active": True,
    })
    db.model_portfolios[m["id"]] = m
    return success(ser_model(m), 201)


@app.route("/model-portfolios/<mid>", methods=["GET"])
def get_model(mid):
    role, _ = auth()
    require_role(role, {"Advisor", "Compliance"})
    return success(ser_model(find_or_404(db.model_portfolios, mid)), 200)


@app.route("/model-portfolios", methods=["GET"])
def list_models():
    role, _ = auth()
    require_role(role, {"Advisor", "Compliance"})
    items = sorted_by_created(list(db.model_portfolios.values()))
    page, meta = paginate(items)
    return success([ser_model(m) for m in page], 200, meta)


@app.route("/model-portfolios/<mid>/retire", methods=["POST"])
def retire_model(mid):
    role, _ = auth()
    require_role(role, {"Advisor"})
    m = find_or_404(db.model_portfolios, mid)
    m["is_active"] = False
    touch(m)
    return success(ser_model(m), 200)


# ============================================================================
# Account
# ============================================================================
def _new_account_record(client_email):
    a = new_common()
    a.update({
        "client_email": client_email,
        "model_portfolio_id": None,
        "risk_score": None,
        "status": "PENDING_PROFILE",
        "cash_balance_cents": 0,
        "invested_value_cents": 0,
        "total_value_cents": 0,
        "max_drift_pct": 0,
        "realized_gain_cents_ytd": 0,
        "wash_sale_disallowed_cents_ytd": 0,
    })
    return a


@app.route("/accounts", methods=["POST"])
def create_account():
    role, _ = auth()
    require_role(role, {"Advisor"})
    body = get_body()
    client_email = require(body, "client_email")
    if not isinstance(client_email, str) or not client_email.strip():
        raise err(ERR_INVALID_REQUEST, "client_email is required and non-empty.")
    for a in db.accounts.values():
        if a["client_email"] == client_email:
            raise err(ERR_DUPLICATE_RESOURCE, "client_email already exists.")
    a = _new_account_record(client_email)
    db.accounts[a["id"]] = a
    return success(ser_account(a), 201)


@app.route("/accounts/<aid>", methods=["GET"])
def get_account(aid):
    role, _ = auth()
    require_role(role, {"Advisor", "Compliance"})
    return success(ser_account(find_or_404(db.accounts, aid)), 200)


@app.route("/accounts", methods=["GET"])
def list_accounts():
    role, _ = auth()
    require_role(role, {"Advisor", "Compliance"})
    a = flask_request.args
    items = list(db.accounts.values())
    status = a.get("status")
    model_portfolio_id = a.get("model_portfolio_id")
    if status is not None:
        items = [x for x in items if x["status"] == status]
    if model_portfolio_id is not None:
        items = [x for x in items if x["model_portfolio_id"] == model_portfolio_id]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success([ser_account(x) for x in page], 200, meta)


@app.route("/accounts/<aid>/freeze", methods=["POST"])
def freeze_account(aid):
    role, _ = auth()
    require_role(role, {"Compliance"})
    a = find_or_404(db.accounts, aid)
    if a["status"] not in ("ACTIVE", "REBALANCE_DUE"):
        raise err(ERR_INVALID_STATE, "Account cannot be frozen from its current status.")
    a["status"] = "FROZEN"
    touch(a)
    return success(ser_account(a), 200)


@app.route("/accounts/<aid>/unfreeze", methods=["POST"])
def unfreeze_account(aid):
    role, _ = auth()
    require_role(role, {"Compliance"})
    a = find_or_404(db.accounts, aid)
    if a["status"] != "FROZEN":
        raise err(ERR_INVALID_STATE, "Account is not FROZEN.")
    # Recompute drift; land in REBALANCE_DUE if >= threshold else ACTIVE.
    services.recompute_account_aggregates(a)
    model = db.model_portfolios.get(a["model_portfolio_id"])
    if model is not None and a["max_drift_pct"] >= model["drift_threshold_pct"]:
        a["status"] = "REBALANCE_DUE"
    else:
        a["status"] = "ACTIVE"
    touch(a)
    return success(ser_account(a), 200)


@app.route("/accounts/<aid>/close", methods=["POST"])
def close_account(aid):
    role, _ = auth()
    require_role(role, {"Advisor"})
    a = find_or_404(db.accounts, aid)
    if a["status"] == "CLOSED":
        raise err(ERR_INVALID_STATE, "Account is already CLOSED.")
    open_lots = [l for l in db.tax_lots.values()
                 if l["account_id"] == aid and l["status"] == "OPEN"]
    if open_lots:
        raise err(ERR_OPEN_LOTS_REMAIN, "Account has OPEN tax lots remaining.")
    a["status"] = "CLOSED"
    touch(a)
    return success(ser_account(a), 200)


# ============================================================================
# RiskQuestionnaire
# ============================================================================
@app.route("/questionnaires", methods=["POST"])
def create_questionnaire():
    role, _ = auth()
    require_role(role, {"Advisor"})
    body = get_body()
    account_id = require(body, "account_id")
    horizon_years = require_int(body, "horizon_years", minimum=0, maximum=50)
    loss_tolerance = require_int(body, "loss_tolerance", minimum=0, maximum=10)
    liquidity_need = require_int(body, "liquidity_need", minimum=0, maximum=10)
    income_band = require_int(body, "income_band", minimum=0, maximum=10)

    find_or_404(db.accounts, account_id)

    score = compute_risk_score(horizon_years, loss_tolerance, liquidity_need, income_band)
    assigned = _resolve_model_for_score(score)
    if assigned is None:
        raise err(ERR_NO_MODEL_FOR_SCORE, "No active model band contains the risk score.")

    q = new_common(with_version=False)
    q.update({
        "account_id": account_id,
        "horizon_years": horizon_years,
        "loss_tolerance": loss_tolerance,
        "liquidity_need": liquidity_need,
        "income_band": income_band,
        "risk_score": score,
        "assigned_model_portfolio_id": assigned["id"],
        "status": "SCORED",
    })
    db.questionnaires[q["id"]] = q
    return success(ser_questionnaire(q), 201)


def _resolve_model_for_score(score):
    """Active model whose [min,max] band contains score; smaller band width wins,
    tie-break created_at ASC (PRD §3.2)."""
    candidates = [
        m for m in db.model_portfolios.values()
        if m["is_active"] and m["min_risk_score"] <= score <= m["max_risk_score"]
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda m: (
        m["max_risk_score"] - m["min_risk_score"],
        m["_created_dt"], m["_created_seq"],
    ))
    return candidates[0]


@app.route("/questionnaires/<qid>", methods=["GET"])
def get_questionnaire(qid):
    role, _ = auth()
    require_role(role, {"Advisor", "Compliance"})
    return success(ser_questionnaire(find_or_404(db.questionnaires, qid)), 200)


@app.route("/questionnaires", methods=["GET"])
def list_questionnaires():
    role, _ = auth()
    require_role(role, {"Advisor", "Compliance"})
    a = flask_request.args
    items = list(db.questionnaires.values())
    for f in ("account_id", "assigned_model_portfolio_id", "status"):
        val = a.get(f)
        if val is not None:
            items = [q for q in items if q.get(f) == val]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success([ser_questionnaire(q) for q in page], 200, meta)


@app.route("/questionnaires/<qid>/accept", methods=["POST"])
def accept_questionnaire(qid):
    role, _ = auth()
    require_role(role, {"Advisor"})
    q = find_or_404(db.questionnaires, qid)
    account = db.accounts.get(q["account_id"])
    if account is None:
        raise err(ERR_NOT_FOUND, "Owning account not found.")

    # state: only SCORED is acceptable
    if q["status"] != "SCORED":
        raise err(ERR_INVALID_STATE, "Questionnaire is not SCORED.")

    # model must still be active
    model = db.model_portfolios.get(q["assigned_model_portfolio_id"])
    if model is None:
        raise err(ERR_NOT_FOUND, "Assigned model not found.")
    if not model["is_active"]:
        raise err(ERR_MODEL_RETIRED, "Assigned model has been retired.")

    was_pending = account["status"] == "PENDING_PROFILE"

    if not was_pending:
        # re-profile: supersede any prior ACCEPTED questionnaire for this account
        for other in db.questionnaires.values():
            if (other["account_id"] == account["id"]
                    and other["id"] != q["id"]
                    and other["status"] == "ACCEPTED"):
                other["status"] = "SUPERSEDED"

    q["status"] = "ACCEPTED"
    account["model_portfolio_id"] = model["id"]
    account["risk_score"] = q["risk_score"]

    if was_pending:
        account["status"] = "ACTIVE"
    else:
        # recompute drift against new model; land REBALANCE_DUE if >= threshold
        services.recompute_account_aggregates(account)
        if account["max_drift_pct"] >= model["drift_threshold_pct"]:
            account["status"] = "REBALANCE_DUE"
        else:
            account["status"] = "ACTIVE"

    touch(account)
    return success(ser_questionnaire(q), 200)


# ============================================================================
# TaxLot
# ============================================================================
@app.route("/tax-lots", methods=["POST"])
def create_lot():
    role, _ = auth()
    require_role(role, {"Advisor"})
    body = get_body()
    account_id = require(body, "account_id")
    security_id = require(body, "security_id")
    quantity = require(body, "quantity")
    cost_basis_cents = require_int(body, "cost_basis_cents", minimum=1)

    if isinstance(quantity, bool) or not isinstance(quantity, (int, float)):
        raise err(ERR_INVALID_REQUEST, "quantity must be a number.")
    if quantity <= 0:
        raise err(ERR_INVALID_REQUEST, "quantity must be > 0.")

    # existence left-to-right: account, then security
    account = find_or_404(db.accounts, account_id)
    find_or_404(db.securities, security_id)

    now = clock.now()
    lot = new_common()
    lot.update({
        "account_id": account_id, "security_id": security_id,
        "quantity": quantity, "cost_basis_cents": cost_basis_cents,
        "_acquired_dt": now, "acquired_at": iso_ms(now),
        "status": "OPEN",
        "_disposed_dt": None, "disposed_at": None,
        "proceeds_cents": None, "realized_gain_cents": None,
        "wash_sale_disallowed_cents": 0, "closed_by_harvest_id": None,
    })
    db.tax_lots[lot["id"]] = lot

    # bubble-up: invested/drift recomputed, account may auto-transition, version++
    services.bubble_up(account)
    return success(ser_lot(lot), 201)


@app.route("/tax-lots/<lid>", methods=["GET"])
def get_lot(lid):
    role, _ = auth()
    require_role(role, {"Advisor", "Compliance"})
    return success(ser_lot(find_or_404(db.tax_lots, lid)), 200)


@app.route("/tax-lots", methods=["GET"])
def list_lots():
    role, _ = auth()
    require_role(role, {"Advisor", "Compliance"})
    a = flask_request.args
    items = list(db.tax_lots.values())
    for f in ("account_id", "security_id", "closed_by_harvest_id", "status"):
        val = a.get(f)
        if val is not None:
            items = [l for l in items if l.get(f) == val]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success([ser_lot(l) for l in page], 200, meta)


# ============================================================================
# HarvestEvent
# ============================================================================
def _correlation_between(sec_a, sec_b):
    """Look up abs correlation between two securities via either's correlated_with
    map keyed by ticker. Returns None if no entry exists."""
    for entry in sec_a.get("correlated_with", []) or []:
        if entry.get("ticker") == sec_b["ticker"]:
            return abs(entry["correlation"])
    for entry in sec_b.get("correlated_with", []) or []:
        if entry.get("ticker") == sec_a["ticker"]:
            return abs(entry["correlation"])
    return None


@app.route("/harvest-events", methods=["POST"])
def create_harvest():
    role, _ = auth()
    require_role(role, {"Advisor"})
    body = get_body()
    account_id = require(body, "account_id")
    source_lot_id = require(body, "source_lot_id")
    replacement_security_id = require(body, "replacement_security_id")
    expected_version = require_int(body, "expected_account_version")

    # existence left-to-right: account, source lot, replacement security
    account = find_or_404(db.accounts, account_id)
    find_or_404(db.tax_lots, source_lot_id)
    find_or_404(db.securities, replacement_security_id)

    # operability gate precedes OCC (PRD §2.10)
    if account["status"] not in ("ACTIVE", "REBALANCE_DUE"):
        raise err(ERR_ACCOUNT_NOT_OPERABLE, "Account is not operable for harvesting.")

    # OCC on account version
    if expected_version != account["version"]:
        raise err(ERR_STALE_ACCOUNT_VERSION, "Stale account version.")

    h = new_common()
    h.update({
        "account_id": account_id, "source_lot_id": source_lot_id,
        "replacement_security_id": replacement_security_id,
        "expected_account_version": expected_version,
        "realized_loss_cents": None,
        "disallowed_loss_cents": None,
        "replacement_lot_id": None,
        "status": "PROPOSED",
    })
    db.harvest_events[h["id"]] = h
    return success(ser_harvest(h), 201)


@app.route("/harvest-events/<hid>", methods=["GET"])
def get_harvest(hid):
    role, _ = auth()
    require_role(role, {"Advisor", "Compliance"})
    return success(ser_harvest(find_or_404(db.harvest_events, hid)), 200)


@app.route("/harvest-events", methods=["GET"])
def list_harvests():
    role, _ = auth()
    require_role(role, {"Advisor", "Compliance"})
    a = flask_request.args
    items = list(db.harvest_events.values())
    for f in ("account_id", "source_lot_id", "replacement_security_id",
              "replacement_lot_id", "status"):
        val = a.get(f)
        if val is not None:
            items = [h for h in items if h.get(f) == val]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success([ser_harvest(h) for h in page], 200, meta)


@app.route("/harvest-events/<hid>/execute", methods=["POST"])
def execute_harvest_route(hid):
    role, _ = auth()
    require_role(role, {"Advisor"})
    h = find_or_404(db.harvest_events, hid)
    account = db.accounts.get(h["account_id"])
    if account is None:
        raise err(ERR_NOT_FOUND, "Owning account not found.")

    # state: only PROPOSED is executable
    if h["status"] != "PROPOSED":
        raise err(ERR_INVALID_STATE, "Harvest is not PROPOSED.")

    # operability gate
    if account["status"] not in ("ACTIVE", "REBALANCE_DUE"):
        raise err(ERR_ACCOUNT_NOT_OPERABLE, "Account is not operable for harvesting.")

    # OCC re-verify
    if h["expected_account_version"] != account["version"]:
        raise err(ERR_STALE_ACCOUNT_VERSION, "Stale account version.")

    source_lot = db.tax_lots.get(h["source_lot_id"])
    if source_lot is None:
        raise err(ERR_NOT_FOUND, "Source lot not found.")
    replacement = db.securities.get(h["replacement_security_id"])
    if replacement is None:
        raise err(ERR_NOT_FOUND, "Replacement security not found.")

    # source lot must be OPEN and belong to the named account
    if source_lot["status"] != "OPEN" or source_lot["account_id"] != account["id"]:
        raise err(ERR_INVALID_STATE, "Source lot is not an OPEN lot of this account.")

    # business screens in PRD §2.10 order: wash-sale (correlation), substantially
    # identical, loss-lot, delisted.
    source_security = db.securities.get(source_lot["security_id"])

    # substantially-identical: replacement must differ from source's security
    if replacement["id"] == source_lot["security_id"]:
        raise err(ERR_SUBSTANTIALLY_IDENTICAL,
                  "Replacement security is identical to the source security.")

    # correlation cap (abs correlation must be <= 0.95)
    corr = _correlation_between(source_security, replacement) if source_security else None
    if corr is not None and corr > float(MAX_REPLACEMENT_CORRELATION):
        raise err(ERR_REPLACEMENT_TOO_CORRELATED,
                  "Replacement is too correlated with the sold security.")

    # loss-lot screen: unrealized_gain_cents must be < 0
    mv = market_value_cents(source_lot["quantity"], source_security["price_cents"])
    unrealized = mv - source_lot["cost_basis_cents"]
    if unrealized >= 0:
        raise err(ERR_NOT_A_LOSS_LOT, "Source lot is not a loss lot.")

    # replacement must be active
    if not replacement["is_active"]:
        raise err(ERR_SECURITY_DELISTED, "Replacement security is delisted.")

    services.execute_harvest(h, account, source_lot, replacement)
    return success(ser_harvest(h), 200)


@app.route("/harvest-events/<hid>/reject", methods=["POST"])
def reject_harvest(hid):
    role, _ = auth()
    require_role(role, {"Compliance"})
    h = find_or_404(db.harvest_events, hid)
    if h["status"] != "PROPOSED":
        raise err(ERR_INVALID_STATE, "Harvest is not PROPOSED.")
    h["status"] = "REJECTED"
    touch(h)
    return success(ser_harvest(h), 200)


@app.route("/harvest-events/<hid>/reverse", methods=["POST"])
def reverse_harvest_route(hid):
    role, _ = auth()
    require_role(role, {"Compliance"})
    h = find_or_404(db.harvest_events, hid)
    account = db.accounts.get(h["account_id"])
    if account is None:
        raise err(ERR_NOT_FOUND, "Owning account not found.")
    if h["status"] != "EXECUTED":
        raise err(ERR_INVALID_STATE, "Harvest is not EXECUTED.")
    if account["status"] == "CLOSED":
        raise err(ERR_INVALID_STATE, "Owning account is CLOSED.")
    services.reverse_harvest(h, account)
    touch(h)
    return success(ser_harvest(h), 200)


# ============================================================================
# RebalanceEvent
# ============================================================================
@app.route("/rebalance-events", methods=["POST"])
def create_rebalance():
    role, _ = auth()
    require_role(role, {"Advisor"})
    body = get_body()
    account_id = require(body, "account_id")
    quarter_label = require(body, "quarter_label")
    expected_version = require_int(body, "expected_account_version")

    if not isinstance(quarter_label, str) or not QUARTER_RE.match(quarter_label):
        raise err(ERR_INVALID_REQUEST, "quarter_label must match YYYY-Qn.")

    account = find_or_404(db.accounts, account_id)

    # operability gate precedes OCC (PRD §2.10)
    if account["status"] not in ("ACTIVE", "REBALANCE_DUE"):
        raise err(ERR_ACCOUNT_NOT_OPERABLE, "Account is not operable for rebalancing.")

    if expected_version != account["version"]:
        raise err(ERR_STALE_ACCOUNT_VERSION, "Stale account version.")

    r = new_common()
    r.update({
        "account_id": account_id,
        "expected_account_version": expected_version,
        "quarter_label": quarter_label,
        "trades_count": 0,
        "cash_consumed_cents": 0,
        "status": "PLANNED",
    })
    db.rebalance_events[r["id"]] = r
    return success(ser_rebalance(r), 201)


@app.route("/rebalance-events/<rid>", methods=["GET"])
def get_rebalance(rid):
    role, _ = auth()
    require_role(role, {"Advisor", "Compliance"})
    return success(ser_rebalance(find_or_404(db.rebalance_events, rid)), 200)


@app.route("/rebalance-events", methods=["GET"])
def list_rebalances():
    role, _ = auth()
    require_role(role, {"Advisor", "Compliance"})
    a = flask_request.args
    items = list(db.rebalance_events.values())
    for f in ("account_id", "status"):
        val = a.get(f)
        if val is not None:
            items = [r for r in items if r.get(f) == val]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success([ser_rebalance(r) for r in page], 200, meta)


@app.route("/rebalance-events/<rid>/execute", methods=["POST"])
def execute_rebalance_route(rid):
    role, _ = auth()
    require_role(role, {"Advisor"})
    r = find_or_404(db.rebalance_events, rid)
    account = db.accounts.get(r["account_id"])
    if account is None:
        raise err(ERR_NOT_FOUND, "Owning account not found.")

    # state: only PLANNED is executable
    if r["status"] != "PLANNED":
        raise err(ERR_INVALID_STATE, "Rebalance is not PLANNED.")

    # account must be REBALANCE_DUE at execution time
    if account["status"] != "REBALANCE_DUE":
        raise err(ERR_NOT_REBALANCE_DUE, "Account is not REBALANCE_DUE.")

    # OCC re-verify
    if r["expected_account_version"] != account["version"]:
        raise err(ERR_STALE_ACCOUNT_VERSION, "Stale account version.")

    # quarter uniqueness among EXECUTED rebalances for this account
    for other in db.rebalance_events.values():
        if (other["account_id"] == account["id"]
                and other["id"] != r["id"]
                and other["status"] == "EXECUTED"
                and other["quarter_label"] == r["quarter_label"]):
            raise err(ERR_QUARTER_ALREADY_REBALANCED,
                      "An EXECUTED rebalance already exists for this quarter.")

    model = db.model_portfolios.get(account["model_portfolio_id"])
    if model is None:
        raise err(ERR_NOT_FOUND, "Account model not found.")

    services.execute_rebalance(r, account, model)
    touch(r)
    return success(ser_rebalance(r), 200)


@app.route("/rebalance-events/<rid>/cancel", methods=["POST"])
def cancel_rebalance(rid):
    role, _ = auth()
    require_role(role, {"Advisor"})
    r = find_or_404(db.rebalance_events, rid)
    if r["status"] != "PLANNED":
        raise err(ERR_INVALID_STATE, "Rebalance is not PLANNED.")
    r["status"] = "CANCELLED"
    touch(r)
    return success(ser_rebalance(r), 200)


# ============================================================================
# TaxForm1099B
# ============================================================================
def _reportable_lots(account_id, tax_year):
    lots = []
    for lot in db.tax_lots.values():
        if lot["account_id"] != account_id:
            continue
        if lot["status"] != "CLOSED":
            continue
        d = lot.get("_disposed_dt")
        if d is None or d.year != tax_year:
            continue
        lots.append(lot)
    lots.sort(key=lambda l: (l["_disposed_dt"], l["_created_seq"]))
    return lots


def compute_form_totals(f):
    lots = _reportable_lots(f["account_id"], f["tax_year"])
    total_proceeds = sum(l["proceeds_cents"] or 0 for l in lots)
    total_cost = sum(l["cost_basis_cents"] or 0 for l in lots)
    total_disallowed = sum(l.get("wash_sale_disallowed_cents", 0) or 0 for l in lots)
    f["total_proceeds_cents"] = total_proceeds
    f["total_cost_basis_cents"] = total_cost
    f["total_wash_sale_disallowed_cents"] = total_disallowed
    f["net_realized_gain_cents"] = (total_proceeds - total_cost) + total_disallowed
    f["line_count"] = len(lots)


@app.route("/tax-forms", methods=["POST"])
def create_form():
    role, _ = auth()
    require_role(role, {"Advisor", "Compliance"})
    body = get_body()
    account_id = require(body, "account_id")
    tax_year = require_int(body, "tax_year", minimum=2000, maximum=2100)
    find_or_404(db.accounts, account_id)

    f = new_common()
    f.update({
        "account_id": account_id, "tax_year": tax_year,
        "total_proceeds_cents": 0, "total_cost_basis_cents": 0,
        "net_realized_gain_cents": 0, "total_wash_sale_disallowed_cents": 0,
        "line_count": 0, "status": "DRAFT",
    })
    compute_form_totals(f)
    db.tax_forms[f["id"]] = f
    return success(ser_form(f), 201)


@app.route("/tax-forms/<fid>", methods=["GET"])
def get_form(fid):
    role, _ = auth()
    require_role(role, {"Advisor", "Compliance"})
    return success(ser_form(find_or_404(db.tax_forms, fid)), 200)


@app.route("/tax-forms", methods=["GET"])
def list_forms():
    role, _ = auth()
    require_role(role, {"Advisor", "Compliance"})
    a = flask_request.args
    items = list(db.tax_forms.values())
    if a.get("account_id") is not None:
        items = [f for f in items if f["account_id"] == a.get("account_id")]
    if a.get("status") is not None:
        items = [f for f in items if f["status"] == a.get("status")]
    if a.get("tax_year") is not None:
        try:
            ty = int(a.get("tax_year"))
            items = [f for f in items if f["tax_year"] == ty]
        except (ValueError, TypeError):
            items = []
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success([ser_form(f) for f in page], 200, meta)


@app.route("/tax-forms/<fid>/finalize", methods=["POST"])
def finalize_form(fid):
    role, _ = auth()
    require_role(role, {"Advisor", "Compliance"})
    f = find_or_404(db.tax_forms, fid)
    if f["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Form is not DRAFT.")
    # tax_year must be strictly before the clock's current calendar year
    if f["tax_year"] >= clock.now().year:
        raise err(ERR_TAX_YEAR_NOT_CLOSED, "Tax year is not yet closed.")
    compute_form_totals(f)  # final snapshot before freeze
    f["status"] = "FINALIZED"
    touch(f)
    return success(ser_form(f), 200)


# ============================================================================
# Test-driving clock
# ============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    role, _ = auth()
    require_role(role, {"Advisor", "Compliance"})
    body = get_body()
    to_iso = require(body, "to_iso8601")
    dt = parse_iso(to_iso)
    clock.set(dt)
    return success({"current_utc": iso_ms(dt)}, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
