"""Return endpoints: create/get/list (PRD §3.9)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import (
    authenticate, require_role, require_borrower_owns, require_merchant_owns,
)
from response import success
from services import engine
from services import calculations as calc
from services.engine import stamp_new, touch, serialize_return
from routes.common import (
    get_json_body, require_int, parse_pagination, paginate, sort_by_created,
    require_loan, require_return,
)

bp = Blueprint("returns", __name__)


@bp.route("/returns", methods=["POST"])
def create_return():
    uid, role = authenticate()
    require_role(role, {"Merchant"})
    body = get_json_body()

    loan_id = body.get("loan_id")
    if not loan_id or not isinstance(loan_id, str):
        raise err("ERR_INVALID_REQUEST", "Missing required field 'loan_id'.")
    loan = require_loan(loan_id)
    require_merchant_owns(role, uid, loan["merchant_id"])

    return_amount = require_int(body, "return_amount_cents", gt=0)

    # Fiscal (priority 11): return amount must not exceed the cart amount.
    app = db.applications.get(loan["application_id"])
    cart_amount = app["cart_amount_cents"] if app else None
    if cart_amount is not None and return_amount > cart_amount:
        raise err("ERR_INSUFFICIENT_CREDIT",
                  "return_amount_cents must not exceed the cart amount.")

    merchant = db.merchants[loan["merchant_id"]]

    # ── Reallocation (pinned order, PRD §3.9) ────────────────────────────────
    # 1) principal_reduction = min(return_amount, remaining_principal).
    remaining_principal = max(0, loan["remaining_principal_cents"])
    principal_reduction = min(return_amount, remaining_principal)

    # 2) Distribute newest-due-first across UNPAID installments (SCHEDULED/LATE),
    #    reducing each installment's outstanding before moving to the next.
    #    Mid-installment reductions are exact integer subtraction (no rounding).
    open_insts = [i for i in engine.loan_installments(loan["id"])
                  if i["status"] in ("SCHEDULED", "LATE")]
    open_insts.sort(key=lambda i: (i["sequence_no"], i["_seq"]), reverse=True)

    to_reduce = principal_reduction
    for inst in open_insts:
        if to_reduce <= 0:
            break
        outstanding = inst["amount_due_cents"] - inst["amount_paid_cents"]
        if outstanding <= 0:
            continue
        cut = min(to_reduce, outstanding)
        inst["amount_due_cents"] -= cut
        to_reduce -= cut
        if inst["amount_due_cents"] <= inst["amount_paid_cents"]:
            # outstanding fully covered -> CANCELLED
            inst["status"] = "CANCELLED"
        touch(inst)

    # Reduce loan remaining principal by the principal reduction.
    loan["remaining_principal_cents"] = max(
        0, loan["remaining_principal_cents"] - principal_reduction)

    # 4) MDR clawback: merchant keeps MDR on returned goods; net principal clawed back.
    mdr_on_return = calc.mdr_fee(return_amount, merchant["mdr_bps"])
    clawback = 0
    settlement = engine.settlement_for_loan(loan["id"])
    if settlement is not None:
        remaining_net = settlement["net_settlement_cents"] - settlement["clawed_back_cents"]
        clawback = min(return_amount - mdr_on_return, remaining_net)
        if clawback < 0:
            clawback = 0
        if clawback > 0:
            engine.apply_return_clawback(settlement, clawback)
            engine.reconcile_merchant(merchant["id"])

    ret = {
        "loan_id": loan["id"],
        "merchant_id": loan["merchant_id"],
        "return_amount_cents": return_amount,
        "principal_reduction_cents": principal_reduction,
        "settlement_clawback_cents": clawback,
        "status": "POSTED",
    }
    stamp_new(ret)
    db.returns[ret["id"]] = ret

    # Recompute posture, bump loan, possibly bubble to PAID_OFF.
    touch(loan)
    engine.recompute_posture(loan)
    engine.maybe_payoff(loan)
    engine.reconcile_borrower(loan["borrower_id"])
    engine.reconcile_merchant(loan["merchant_id"])

    return success(serialize_return(ret), status=201)


@bp.route("/returns/<return_id>", methods=["GET"])
def get_return(return_id):
    uid, role = authenticate()
    require_role(role, {"Servicer", "Borrower", "Merchant"})
    r = require_return(return_id)
    loan = db.loans.get(r["loan_id"])
    if loan is not None:
        require_borrower_owns(role, uid, loan["borrower_id"])
    require_merchant_owns(role, uid, r["merchant_id"])
    return success(serialize_return(r), status=200)


@bp.route("/returns", methods=["GET"])
def list_returns():
    uid, role = authenticate()
    require_role(role, {"Servicer", "Borrower", "Merchant"})
    limit, offset = parse_pagination()
    loan_filter = request.args.get("loan_id")
    merchant_filter = request.args.get("merchant_id")

    rows = list(db.returns.values())
    if loan_filter is not None:
        rows = [r for r in rows if r["loan_id"] == loan_filter]
    if merchant_filter is not None:
        rows = [r for r in rows if r["merchant_id"] == merchant_filter]
    if role == "Merchant":
        rows = [r for r in rows if r["merchant_id"] == uid]
    elif role == "Borrower":
        rows = [r for r in rows
                if (db.loans.get(r["loan_id"]) or {}).get("borrower_id") == uid]

    rows = sort_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return success([serialize_return(r) for r in page],
                   status=200, pagination=meta)
