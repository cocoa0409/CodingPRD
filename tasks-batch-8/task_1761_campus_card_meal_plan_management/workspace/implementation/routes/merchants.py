"""Merchant and MerchantSettlement endpoints (PRD 3.9)."""

from flask import Blueprint, g, request

from db import store
from errors import (
    err, ERR_VALIDATION, ERR_NOT_FOUND, ERR_NOT_RESOURCE_OWNER,
    ERR_INVALID_STATE_TRANSITION, ERR_DUPLICATE_NATURAL_KEY,
    ERR_MERCHANT_NOT_ACTIVE, ERR_SETTLEMENTS_OUTSTANDING,
    ERR_SETTLEMENT_PERIOD_OVERLAP, ERR_PERIOD_OUTSIDE_TERM,
    ERR_SOD_APPROVER_IS_SUBMITTER, ERR_SOD_PAYER_IS_APPROVER,
)
from middleware import (
    authenticate, require_roles, get_body, v_str, v_int, v_enum, v_dt,
    find_or_404, pub, paginate, fmt_dt,
)
from response import success
from services.core import new_row, touch, dt_of
from services.pricing import settlement_commission

bp = Blueprint("merchants", __name__)

CATEGORIES = {"RESTAURANT", "GROCERY", "COFFEE", "BOOKSTORE", "OTHER"}
COMMISSION_MODES = {"PER_TRANSACTION", "AGGREGATE"}
OPEN_SETTLEMENT_STATES = {"DRAFT", "SUBMITTED", "APPROVED"}


# ------------------------------------------------------------------ merchants
@bp.route("/api/merchants", methods=["POST"])
def create_merchant():
    authenticate()
    require_roles("BursarOffice")
    body = get_body()
    merchant_code = v_str(body, "merchant_code")
    legal_name = v_str(body, "legal_name")
    category = v_enum(body, "category", CATEGORIES)
    commission_bps = v_int(body, "commission_bps", min_v=0, max_v=2000)
    contact_email = v_str(body, "contact_email")
    commission_mode = v_enum(body, "commission_mode", COMMISSION_MODES,
                             required=False) or "PER_TRANSACTION"
    for m in store.merchants.values():
        if m["merchant_code"] == merchant_code:
            err(ERR_DUPLICATE_NATURAL_KEY, "merchant_code already exists")
    merchant = new_row()
    merchant.update({
        "merchant_code": merchant_code,
        "legal_name": legal_name,
        "category": category,
        "commission_bps": commission_bps,
        "commission_mode": commission_mode,
        "contact_email": contact_email,
        "status": "PENDING_CONTRACT",
    })
    store.merchants[merchant["id"]] = merchant
    return success(pub(merchant), 201)


@bp.route("/api/merchants", methods=["GET"])
def list_merchants():
    authenticate()
    require_roles("PlatformAdmin", "CardOfficeAdmin", "BursarOffice")
    rows = list(store.merchants.values())
    status = request.args.get("status")
    category = request.args.get("category")
    if status is not None:
        rows = [m for m in rows if m["status"] == status]
    if category is not None:
        rows = [m for m in rows if m["category"] == category]
    data, page = paginate(rows)
    return success(data, 200, page)


@bp.route("/api/merchants/<mid>", methods=["GET"])
def get_merchant(mid):
    authenticate()
    require_roles("PlatformAdmin", "CardOfficeAdmin", "BursarOffice", "MerchantUser")
    merchant = store.merchants.get(mid)
    if merchant is not None and g.role == "MerchantUser" and g.user_id != merchant["id"]:
        err(ERR_NOT_RESOURCE_OWNER, "MerchantUser may read only its own record")
    if merchant is None:
        err(ERR_NOT_FOUND, "Merchant not found")
    return success(pub(merchant), 200)


@bp.route("/api/merchants/<mid>/activate", methods=["POST"])
def activate_merchant(mid):
    authenticate()
    require_roles("BursarOffice")
    merchant = find_or_404(store.merchants, mid)
    if merchant["status"] not in ("PENDING_CONTRACT", "SUSPENDED"):
        err(ERR_INVALID_STATE_TRANSITION,
            "Only a PENDING_CONTRACT or SUSPENDED merchant can be activated")
    merchant["status"] = "ACTIVE"
    touch(merchant)
    return success(pub(merchant), 200)


@bp.route("/api/merchants/<mid>/suspend", methods=["POST"])
def suspend_merchant(mid):
    authenticate()
    require_roles("BursarOffice")
    merchant = find_or_404(store.merchants, mid)
    if merchant["status"] != "ACTIVE":
        err(ERR_INVALID_STATE_TRANSITION, "Only an ACTIVE merchant can be suspended")
    merchant["status"] = "SUSPENDED"
    touch(merchant)
    return success(pub(merchant), 200)


@bp.route("/api/merchants/<mid>/terminate", methods=["POST"])
def terminate_merchant(mid):
    authenticate()
    require_roles("BursarOffice")
    merchant = find_or_404(store.merchants, mid)
    if merchant["status"] not in ("ACTIVE", "SUSPENDED"):
        err(ERR_INVALID_STATE_TRANSITION,
            "Only an ACTIVE or SUSPENDED merchant can be terminated")
    for st in store.settlements.values():
        if st["merchant_id"] == merchant["id"] and st["status"] in OPEN_SETTLEMENT_STATES:
            err(ERR_SETTLEMENTS_OUTSTANDING,
                "The merchant has settlements in DRAFT, SUBMITTED or APPROVED")
    merchant["status"] = "TERMINATED"
    touch(merchant)
    return success(pub(merchant), 200)


# ---------------------------------------------------------------- settlements
@bp.route("/api/merchants/<mid>/settlements", methods=["POST"])
def create_settlement(mid):
    authenticate()
    require_roles("MerchantUser", "BursarOffice")
    # Priority 3: MerchantUser acts only for its own merchant.
    if g.role == "MerchantUser" and g.user_id != mid:
        err(ERR_NOT_RESOURCE_OWNER,
            "MerchantUser may create settlements only for its own merchant")
    body = get_body()
    term_id = v_str(body, "term_id")
    period_start = v_dt(body, "period_start")
    period_end = v_dt(body, "period_end")
    if period_end < period_start:
        err(ERR_VALIDATION, "period_end must be on or after period_start")
    merchant = find_or_404(store.merchants, mid)
    term = find_or_404(store.terms, term_id)
    if merchant["status"] != "ACTIVE":
        err(ERR_MERCHANT_NOT_ACTIVE, "Merchant is not ACTIVE")
    if not (dt_of(term, "start_date") <= period_start
            and period_end <= dt_of(term, "end_date")):
        err(ERR_PERIOD_OUTSIDE_TERM,
            "The settlement period must lie within the term bounds")
    for st in store.settlements.values():
        if (st["merchant_id"] == merchant["id"] and st["status"] != "REJECTED"
                and period_start <= dt_of(st, "period_end")
                and dt_of(st, "period_start") <= period_end):
            err(ERR_SETTLEMENT_PERIOD_OVERLAP,
                "The settlement period overlaps an existing settlement")
    settlement = new_row()
    settlement.update({
        "merchant_id": merchant["id"],
        "term_id": term["id"],
        "period_start": fmt_dt(period_start),
        "period_end": fmt_dt(period_end),
        "status": "DRAFT",
        "gross_cents": None,
        "commission_cents": None,
        "net_cents": None,
        "transaction_count": None,
        "carried_from_settlement_id": None,
        "submitted_by": None,
        "approved_by": None,
        "paid_by": None,
        "rejection_reason": None,
    })
    store.settlements[settlement["id"]] = settlement
    return success(pub(settlement), 201)


def _own_settlement_or_403(st):
    if g.role == "MerchantUser" and st["merchant_id"] != g.user_id:
        err(ERR_NOT_RESOURCE_OWNER,
            "MerchantUser may act only on its own settlements")


@bp.route("/api/settlements", methods=["GET"])
def list_settlements():
    authenticate()
    require_roles("PlatformAdmin", "CardOfficeAdmin", "BursarOffice", "MerchantUser")
    rows = list(store.settlements.values())
    if g.role == "MerchantUser":
        rows = [s for s in rows if s["merchant_id"] == g.user_id]
    merchant_id = request.args.get("merchant_id")
    term_id = request.args.get("term_id")
    status = request.args.get("status")
    carried = request.args.get("carried_from_settlement_id")
    if merchant_id is not None:
        if g.role == "MerchantUser" and merchant_id != g.user_id:
            err(ERR_NOT_RESOURCE_OWNER, "Cannot filter by another merchant")
        rows = [s for s in rows if s["merchant_id"] == merchant_id]
    if term_id is not None:
        rows = [s for s in rows if s["term_id"] == term_id]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    if carried is not None:
        rows = [s for s in rows if s.get("carried_from_settlement_id") == carried]
    data, page = paginate(rows)
    return success(data, 200, page)


@bp.route("/api/settlements/<sid>", methods=["GET"])
def get_settlement(sid):
    authenticate()
    require_roles("PlatformAdmin", "CardOfficeAdmin", "BursarOffice", "MerchantUser")
    st = store.settlements.get(sid)
    if st is not None:
        _own_settlement_or_403(st)
    if st is None:
        err(ERR_NOT_FOUND, "Settlement not found")
    return success(pub(st), 200)


def _run_sweep(settlement):
    """merchant_settlement_sweep + dispute_carryover_sweep (PRD 3.9)."""
    merchant = store.merchants[settlement["merchant_id"]]
    period_start = dt_of(settlement, "period_start")
    period_end = dt_of(settlement, "period_end")
    merchant_txs = [t for t in store.transactions.values()
                    if t.get("merchant_id") == merchant["id"]]
    # Record dispute exclusions attributable to this sweep.
    for tx in merchant_txs:
        if (tx["status"] == "UNDER_DISPUTE"
                and tx.get("settled_in_settlement_id") is None
                and period_start <= dt_of(tx, "created_at") <= period_end):
            tx["_excluded_by_settlement_id"] = settlement["id"]
    swept = []
    for tx in merchant_txs:
        if tx["status"] != "POSTED" or tx.get("settled_in_settlement_id") is not None:
            continue
        in_period = period_start <= dt_of(tx, "created_at") <= period_end
        if in_period or tx.get("_carried"):
            swept.append(tx)
    gross, commission, net = settlement_commission(
        merchant, [t["amount_cents"] for t in swept])
    # carried_from_settlement_id: most recent prior non-REJECTED settlement
    # whose excluded disputed transactions entered this sweep.
    excluder_ids = {t["_excluded_by_settlement_id"] for t in swept
                    if t.get("_excluded_by_settlement_id")}
    carried_from = None
    candidates = [s for s in store.settlements.values()
                  if s["id"] in excluder_ids and s["status"] != "REJECTED"
                  and s["id"] != settlement["id"]]
    if candidates:
        carried_from = sorted(candidates,
                              key=lambda s: (s["created_at"], s["_seq"]))[-1]["id"]
    for tx in sorted(swept, key=lambda t: (t["created_at"], t["_seq"])):
        tx["settled_in_settlement_id"] = settlement["id"]
        tx.pop("_carried", None)
        tx.pop("_excluded_by_settlement_id", None)
        touch(tx)
    settlement["gross_cents"] = gross
    settlement["commission_cents"] = commission
    settlement["net_cents"] = net
    settlement["transaction_count"] = len(swept)
    settlement["carried_from_settlement_id"] = carried_from


@bp.route("/api/settlements/<sid>/submit", methods=["POST"])
def submit_settlement(sid):
    authenticate()
    require_roles("MerchantUser", "BursarOffice")
    st = store.settlements.get(sid)
    if st is not None:
        _own_settlement_or_403(st)
    if st is None:
        err(ERR_NOT_FOUND, "Settlement not found")
    if st["status"] not in ("DRAFT", "REJECTED"):
        err(ERR_INVALID_STATE_TRANSITION,
            "Only a DRAFT or REJECTED settlement can be submitted")
    _run_sweep(st)
    st["status"] = "SUBMITTED"
    st["submitted_by"] = g.user_id
    st["rejection_reason"] = None
    touch(st)
    return success(pub(st), 200)


@bp.route("/api/settlements/<sid>/approve", methods=["POST"])
def approve_settlement(sid):
    authenticate()
    require_roles("BursarOffice")
    st = find_or_404(store.settlements, sid)
    if st["status"] != "SUBMITTED":
        err(ERR_INVALID_STATE_TRANSITION,
            "Only a SUBMITTED settlement can be approved")
    if st["submitted_by"] == g.user_id:
        err(ERR_SOD_APPROVER_IS_SUBMITTER,
            "The settlement approver must differ from its submitter")
    st["status"] = "APPROVED"
    st["approved_by"] = g.user_id
    touch(st)
    for tx in store.transactions.values():
        if tx.get("settled_in_settlement_id") == st["id"] and tx["status"] == "POSTED":
            tx["status"] = "SETTLED"
            touch(tx)
    return success(pub(st), 200)


@bp.route("/api/settlements/<sid>/reject", methods=["POST"])
def reject_settlement(sid):
    authenticate()
    require_roles("BursarOffice")
    body = get_body()
    rejection_reason = v_str(body, "rejection_reason")
    st = find_or_404(store.settlements, sid)
    if st["status"] != "SUBMITTED":
        err(ERR_INVALID_STATE_TRANSITION,
            "Only a SUBMITTED settlement can be rejected")
    st["status"] = "REJECTED"
    st["rejection_reason"] = rejection_reason
    touch(st)
    for tx in store.transactions.values():
        if tx.get("settled_in_settlement_id") == st["id"]:
            tx["settled_in_settlement_id"] = None
            touch(tx)
    return success(pub(st), 200)


@bp.route("/api/settlements/<sid>/pay", methods=["POST"])
def pay_settlement(sid):
    authenticate()
    require_roles("BursarOffice")
    st = find_or_404(store.settlements, sid)
    if st["status"] != "APPROVED":
        err(ERR_INVALID_STATE_TRANSITION,
            "Only an APPROVED settlement can be paid")
    if st["approved_by"] == g.user_id:
        err(ERR_SOD_PAYER_IS_APPROVER,
            "The settlement payer must differ from its approver")
    st["status"] = "PAID"
    st["paid_by"] = g.user_id
    touch(st)
    return success(pub(st), 200)
