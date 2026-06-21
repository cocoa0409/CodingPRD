"""RentPayment routes: schedule, fetch, list, record, cure, forfeit."""

import math

from flask import Blueprint, request

import db
from errors import err
from middleware import get_auth, require_role
from response import object_response, array_response
from routes.helpers import lookup, paginate
from services import domain
from services import calc
import validation as V

bp = Blueprint("rent_payments", __name__)


# ---------------------------------------------------------------------------
# Schedule (Landlord)
# ---------------------------------------------------------------------------
@bp.post("/agreements/<aid>/rent-payments")
def create_rent_payment(aid):
    user_id, role = get_auth()
    require_role(role, {"Landlord"})
    agreement = lookup(db.agreements, aid)
    if agreement["landlord_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Landlord does not own this agreement")

    body = V.get_body()
    period_index = V.require_int(body, "period_index", minimum=1)
    due_date = V.parse_dt(V.require(body, "due_date"), "due_date")
    supersedes_payment_id = V.optional_str(body, "supersedes_payment_id")

    # Existence (priority 3): supersedes_payment_id, when given, must resolve.
    if supersedes_payment_id is not None:
        lookup(db.rent_payments, supersedes_payment_id)

    # Uniqueness (priority 14): (agreement_id, period_index) unique among
    # non-superseded rows. The incoming row, when it carries
    # supersedes_payment_id, supersedes that earlier row — so that row is
    # excluded from the uniqueness set (it is being re-billed, PRD §3.3).
    existing = domain.non_superseded(domain.agreement_payments(aid))
    for p in existing:
        if p["id"] == supersedes_payment_id:
            continue
        if p["period_index"] == period_index:
            raise err("ERR_DUPLICATE_PERIOD",
                      "A non-superseded payment for this period already exists")

    amount_cents = agreement["monthly_payment_cents"]
    credit_portion = calc.credit_portion(amount_cents, agreement["credit_pct"])
    rent_portion = amount_cents - credit_portion

    rec = {
        "id": db.new_id(),
        "agreement_id": aid,
        "period_index": period_index,
        "due_date": db.iso_millis(due_date),
        "amount_cents": amount_cents,
        "paid_at": None,
        "rent_portion_cents": rent_portion,
        "credit_portion_cents": credit_portion,
        "late_fee_cents": 0,
        "supersedes_payment_id": supersedes_payment_id,
        "status": "PENDING",
    }
    domain._stamp_new(rec)
    db.rent_payments[rec["id"]] = rec
    return object_response(domain.serialize_rent_payment(rec), 201)


# ---------------------------------------------------------------------------
# Fetch / list
# ---------------------------------------------------------------------------
@bp.get("/rent-payments/<rid>")
def get_rent_payment(rid):
    _, role = get_auth()
    require_role(role, {"Landlord", "Tenant", "EscrowAgent"})
    rec = lookup(db.rent_payments, rid)
    return object_response(domain.serialize_rent_payment(rec), 200)


@bp.get("/rent-payments")
def list_rent_payments():
    _, role = get_auth()
    require_role(role, {"Landlord", "Tenant", "EscrowAgent"})
    items = list(db.rent_payments.values())
    for field in ("agreement_id", "supersedes_payment_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [p for p in items if p.get(field) == val]
    page, limit, offset, total = paginate(items)
    return array_response([domain.serialize_rent_payment(p) for p in page],
                          limit, offset, total)


# ---------------------------------------------------------------------------
# Record (Tenant)
# ---------------------------------------------------------------------------
@bp.post("/rent-payments/<rid>/record")
def record_payment(rid):
    user_id, role = get_auth()
    require_role(role, {"Tenant"})
    payment = lookup(db.rent_payments, rid)
    agreement = lookup(db.agreements, payment["agreement_id"])
    if agreement["tenant_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Tenant does not own this payment")

    body = V.get_body()
    paid_at = V.parse_dt(V.require(body, "paid_at"), "paid_at")

    # State (priority 7): payment must be PENDING.
    if payment["status"] != "PENDING":
        raise err("ERR_PAYMENT_NOT_PENDING", "Payment is not PENDING")
    # Agreement must be ACTIVE.
    if agreement["status"] != "ACTIVE":
        raise err("ERR_AGREEMENT_NOT_ACTIVE", "Agreement is not ACTIVE")

    due_date = V.parse_dt(payment["due_date"], "due_date")
    elapsed_days = (paid_at - due_date).total_seconds() / 86400.0
    days_late = math.floor(elapsed_days)
    grace_days = agreement["grace_days"]

    payment["paid_at"] = db.iso_millis(paid_at)
    if days_late <= grace_days:
        # On time -> PAID, no fee, credit earned.
        payment["status"] = "PAID"
        payment["late_fee_cents"] = 0
    else:
        # Past grace -> LATE, fee assessed, credit not yet earned.
        payment["status"] = "LATE"
        payment["late_fee_cents"] = calc.late_fee(payment["amount_cents"])

    domain.touch(payment)
    domain.recompute_accruals(agreement)
    return object_response(domain.serialize_rent_payment(payment), 200)


# ---------------------------------------------------------------------------
# Cure (Landlord): LATE -> PAID
# ---------------------------------------------------------------------------
@bp.post("/rent-payments/<rid>/cure")
def cure_payment(rid):
    user_id, role = get_auth()
    require_role(role, {"Landlord"})
    payment = lookup(db.rent_payments, rid)
    agreement = lookup(db.agreements, payment["agreement_id"])
    if agreement["landlord_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Landlord does not own this payment")

    if payment["status"] != "LATE":
        raise err("ERR_PAYMENT_NOT_LATE", "Payment is not LATE")
    if agreement["status"] != "ACTIVE":
        raise err("ERR_AGREEMENT_NOT_ACTIVE", "Agreement is not ACTIVE")

    payment["status"] = "PAID"
    domain.touch(payment)
    domain.recompute_accruals(agreement)
    return object_response(domain.serialize_rent_payment(payment), 200)


# ---------------------------------------------------------------------------
# Forfeit (Landlord): PENDING/LATE -> FORFEITED
# ---------------------------------------------------------------------------
@bp.post("/rent-payments/<rid>/forfeit")
def forfeit_payment(rid):
    user_id, role = get_auth()
    require_role(role, {"Landlord"})
    payment = lookup(db.rent_payments, rid)
    agreement = lookup(db.agreements, payment["agreement_id"])
    if agreement["landlord_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Landlord does not own this payment")

    status = payment["status"]
    # Forfeit acts on PENDING or LATE. The status-specific error mirrors the
    # transition the caller implied: a non-PENDING row that is also non-LATE
    # falls through to the PENDING-precondition error.
    if status not in ("PENDING", "LATE"):
        if status == "LATE":
            raise err("ERR_PAYMENT_NOT_LATE", "Payment is not LATE")
        raise err("ERR_PAYMENT_NOT_PENDING", "Payment is not PENDING or LATE")
    if agreement["status"] != "ACTIVE":
        raise err("ERR_AGREEMENT_NOT_ACTIVE", "Agreement is not ACTIVE")

    payment["status"] = "FORFEITED"
    domain.touch(payment)
    domain.recompute_accruals(agreement)
    return object_response(domain.serialize_rent_payment(payment), 200)
