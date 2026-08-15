"""Bill endpoints and the two credit variants."""

from flask import Blueprint, request

from errors import raise_err, ERR_SUBSCRIPTION_STATE_INVALID, \
    ERR_FUTURE_PERIOD, ERR_DUPLICATE_BILL, ERR_QUANTITY_INVALID, \
    ERR_BILL_STATE_INVALID, ERR_VALIDATION
from store import STORE, new_id, next_seq, now_ts, clock_now
from util import auth, require_role, ok_object, body_json, req_str, req_int, \
    opt_int, parse_month, get_or_404
from services import compute_provisional_credit, compute_final_credit, touch
from routes.generators import list_with_serializer

bp = Blueprint("bills", __name__)


def serialize_bill(b):
    return {k: v for k, v in b.items() if not k.startswith("_")}


@bp.post("/greenpower/bills")
def create_bill():
    uid, role = auth()
    require_role(role, "ProgramManager")
    body = body_json()
    subscription_id = req_str(body, "subscription_id")
    period_month = req_str(body, "period_month")
    py, pm = parse_month(period_month, "period_month")
    usage_kwh = req_int(body, "usage_kwh")
    charges_cents = req_int(body, "charges_cents")

    sub = get_or_404(STORE["subscriptions"], subscription_id, "Subscription")
    if sub["status"] not in ("ACTIVE", "SUSPENDED"):
        raise_err(ERR_SUBSCRIPTION_STATE_INVALID,
                  "Bills require an ACTIVE or SUSPENDED subscription")
    now = clock_now()
    if (py, pm) > (now.year, now.month):
        raise_err(ERR_FUTURE_PERIOD,
                  "period_month may not be later than the logical clock month")
    for b in STORE["bills"].values():
        if (b["subscription_id"] == subscription_id
                and b["period_month"] == period_month and b["status"] != "VOID"):
            raise_err(ERR_DUPLICATE_BILL,
                      "A non-VOID bill already exists for this subscription and month")
    if usage_kwh < 0 or charges_cents < 0:
        raise_err(ERR_QUANTITY_INVALID,
                  "usage_kwh and charges_cents must be non-negative integers")

    program = STORE["programs"].get(sub["program_id"])
    provisional = compute_provisional_credit(sub, program) if program else 0

    ts = now_ts()
    bill = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "subscription_id": subscription_id,
        "period_month": period_month,
        "usage_kwh": usage_kwh,
        "charges_cents": charges_cents,
        "status": "DRAFT",
        "provisional_credit_cents": provisional,
        "issued_credit_cents": None,
        "proration_active_days": None,
        "proration_days_in_period": None,
        "issued_at": None,
        "_seq": next_seq(),
    }
    STORE["bills"][bill["id"]] = bill
    return ok_object(serialize_bill(bill), 201)


@bp.get("/greenpower/bills")
def list_bills():
    auth()
    filters = {
        "subscription_id": request.args.get("subscription_id"),
        "status": request.args.get("status"),
        "period_month": request.args.get("period_month"),
    }
    return list_with_serializer(list(STORE["bills"].values()), filters, serialize_bill)


@bp.get("/greenpower/bills/<bid>")
def get_bill(bid):
    auth()
    bill = get_or_404(STORE["bills"], bid, "Bill")
    return ok_object(serialize_bill(bill))


def _issue(bill):
    sub = STORE["subscriptions"].get(bill["subscription_id"])
    program = STORE["programs"].get(sub["program_id"]) if sub else None
    credit, active_days, days_in_period = compute_final_credit(bill, sub, program)
    bill["issued_credit_cents"] = credit
    bill["proration_active_days"] = active_days
    bill["proration_days_in_period"] = days_in_period
    bill["issued_at"] = now_ts()
    bill["status"] = "ISSUED"
    touch(bill)


@bp.post("/greenpower/bills/<bid>/issue")
def issue_bill(bid):
    uid, role = auth()
    require_role(role, "ProgramManager")
    bill = get_or_404(STORE["bills"], bid, "Bill")
    if bill["status"] != "DRAFT":
        raise_err(ERR_BILL_STATE_INVALID, "Issue requires a DRAFT bill")
    _issue(bill)
    return ok_object(serialize_bill(bill))


@bp.post("/greenpower/bills/<bid>/dispute")
def dispute_bill(bid):
    uid, role = auth()
    require_role(role, "ProgramManager")
    bill = get_or_404(STORE["bills"], bid, "Bill")
    if bill["status"] != "ISSUED":
        raise_err(ERR_BILL_STATE_INVALID, "Dispute requires an ISSUED bill")
    body_json()  # optional reason is accepted for the audit trail
    bill["status"] = "DISPUTED"
    touch(bill)
    return ok_object(serialize_bill(bill))


@bp.post("/greenpower/bills/<bid>/reissue")
def reissue_bill(bid):
    uid, role = auth()
    require_role(role, "ProgramManager")
    bill = get_or_404(STORE["bills"], bid, "Bill")
    if bill["status"] != "DISPUTED":
        raise_err(ERR_BILL_STATE_INVALID, "Reissue requires a DISPUTED bill")
    body = body_json()
    usage = opt_int(body, "usage_kwh")
    charges = opt_int(body, "charges_cents")
    if usage is not None:
        if usage < 0:
            raise_err(ERR_QUANTITY_INVALID, "usage_kwh must be non-negative")
        bill["usage_kwh"] = usage
    if charges is not None:
        if charges < 0:
            raise_err(ERR_QUANTITY_INVALID, "charges_cents must be non-negative")
        bill["charges_cents"] = charges
    _issue(bill)
    return ok_object(serialize_bill(bill))


@bp.post("/greenpower/bills/<bid>/void")
def void_bill(bid):
    uid, role = auth()
    require_role(role, "ProgramManager")
    bill = get_or_404(STORE["bills"], bid, "Bill")
    if bill["status"] not in ("DRAFT", "DISPUTED"):
        raise_err(ERR_BILL_STATE_INVALID,
                  "Only a DRAFT or DISPUTED bill may be voided")
    bill["status"] = "VOID"
    touch(bill)
    return ok_object(serialize_bill(bill))
