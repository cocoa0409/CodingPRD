"""Payment routes (PRD §3.7) — binding & reinstatement; drives Policy transitions."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import require_roles
from response import success
from services.calc import to_money, REINSTATEMENT_FEE
from services.common import (
    get_json_body, require_field, as_number, as_enum,
    get_or_404, parse_pagination, paginate,
)
from services.ledger import post
from services.models import base_record, serialize, touch

bp = Blueprint("payments", __name__)


def _coverage_overlap(property_id, effective_date, expiration_date, exclude_policy_id):
    """True if another ACTIVE/REINSTATED policy covers property over an overlapping
    closed interval [effective_date, expiration_date] (inclusive both ends)."""
    for pol in db.policies.values():
        if pol["id"] == exclude_policy_id:
            continue
        if pol["property_id"] != property_id:
            continue
        if pol["status"] not in ("ACTIVE", "REINSTATED"):
            continue
        # closed intervals overlap when they share any instant
        if pol["effective_date"] <= expiration_date and effective_date <= pol["expiration_date"]:
            return True
    return False


@bp.post("/payments")
@require_roles("Agent")
def create_payment():
    body = get_json_body()
    # Routing essentials: policy_id (existence) and purpose (selects the state gate).
    policy_id = require_field(body, "policy_id")
    purpose = as_enum(require_field(body, "purpose"), "purpose", {"BINDING", "REINSTATEMENT"})
    amount = as_number(require_field(body, "amount"), "amount")

    with db.lock:
        pol = get_or_404("policy", policy_id)
        if purpose == "BINDING":
            _settle_binding(pol, amount)
        else:
            _settle_reinstatement(pol, amount)
        # record the payment only on success
        pay = base_record()
        pay.update({
            "policy_id": policy_id,
            "purpose": purpose,
            "amount": to_money(amount),
            "status": "SETTLED",
        })
        db.payments[pay["id"]] = pay
        return success(serialize(pay), status=201)


def _settle_binding(pol, amount):
    if pol["status"] != "PENDING_PAYMENT":
        raise err("ERR_POLICY_NOT_PENDING_PAYMENT", "binding payment requires Policy in PENDING_PAYMENT.")
    if to_money(amount) != to_money(pol["annual_premium"]):
        raise err("ERR_PAYMENT_AMOUNT_MISMATCH", "amount must equal the policy's annual_premium.")
    if _coverage_overlap(pol["property_id"], pol["effective_date"], pol["expiration_date"], pol["id"]):
        raise err("ERR_COVERAGE_PERIOD_OVERLAP",
                  "Another ACTIVE/REINSTATED policy already covers this property over an overlapping period.")
    pol["status"] = "ACTIVE"
    touch(pol)
    post(pol, "DEBIT", to_money(pol["annual_premium"]), "BIND_PREMIUM")


def _settle_reinstatement(pol, amount):
    if pol["status"] != "LAPSED":
        raise err("ERR_POLICY_NOT_LAPSED", "reinstatement payment requires Policy in LAPSED.")
    if pol["lapse_count"] > 2:
        raise err("ERR_REINSTATEMENT_LIMIT_EXCEEDED", "Policy.lapse_count > 2 cannot reinstate.")
    required = to_money(to_money(pol["annual_premium"]) + REINSTATEMENT_FEE)
    if to_money(amount) != required:
        raise err("ERR_PAYMENT_AMOUNT_MISMATCH",
                  "amount must equal annual_premium + reinstatement fee.")
    pol["status"] = "REINSTATED"
    touch(pol)
    post(pol, "DEBIT", to_money(pol["annual_premium"]), "BIND_PREMIUM")
    post(pol, "DEBIT", REINSTATEMENT_FEE, "REINSTATEMENT_FEE")


@bp.get("/payments")
@require_roles("Admin", "Agent", "Underwriter")
def list_payments():
    limit, offset = parse_pagination()
    policy_id = request.args.get("policy_id")
    with db.lock:
        items = list(db.payments.values())
        if policy_id is not None:
            items = [p for p in items if p["policy_id"] == policy_id]
        window, meta = paginate(items, limit, offset)
        data = [serialize(p) for p in window]
    return success(data, status=200, list_meta=meta)


@bp.get("/payments/<rid>")
@require_roles("Admin", "Agent", "Underwriter")
def get_payment(rid):
    with db.lock:
        rec = get_or_404("payment", rid)
        return success(serialize(rec), status=200)
