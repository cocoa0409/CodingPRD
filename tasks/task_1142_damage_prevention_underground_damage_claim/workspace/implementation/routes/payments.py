"""Payment endpoints: create (explicit or waterfall), reverse."""

from flask import Blueprint, request

import clock
from db import db
from errors import (err_invalid_request, err_invalid_state, err_not_found,
                    err_ownership, err_payment_exceeds)
from middleware import require_roles
from serializers import payment_out
from services.core import (invoice_status_from_paid, maybe_advance_case_recovery,
                           recompute_debtor_outstanding,
                           recompute_invoice_amount_due, touch)
from util import (get_pagination, new_id, paginate, parse_body, require_enum,
                  require_positive_int, require_string, success_envelope)

bp = Blueprint("payments", __name__)

ALL_ROLES = ("IntakeCoordinator", "DamageInvestigator", "ClaimsAdjuster",
             "RecoveryManager", "Excavator", "Locator")


def _payer_entity(payer_type, payer_id):
    if payer_type == "EXCAVATOR":
        return db.excavators.get(payer_id)
    return db.locators.get(payer_id)


def _apply_leg(inv, amount, case_cache):
    inv["amount_paid_cents"] += amount
    recompute_invoice_amount_due(inv)
    if inv["status"] in ("ISSUED", "PARTIALLY_PAID"):
        inv["status"] = invoice_status_from_paid(inv)
    touch(inv)
    case = case_cache.get(inv["damage_case_id"])
    if case is None:
        case = db.damage_cases.get(inv["damage_case_id"])
        case_cache[inv["damage_case_id"]] = case
    if case is not None:
        if case["recovery_status"] == "INVOICED" and amount > 0:
            case["recovery_status"] = "COLLECTING"
        maybe_advance_case_recovery(case)


@bp.route("/damage-recovery/payments", methods=["POST"])
def create_payment():
    user_id, role = require_roles("Excavator", "Locator", "RecoveryManager")
    body = parse_body(required_fields=["payer_type", "payer_id", "amount_cents"])
    payer_type = require_enum(body["payer_type"], ("EXCAVATOR", "LOCATOR"), "payer_type")
    payer_id = require_string(body["payer_id"], "payer_id")
    amount = require_positive_int(body["amount_cents"], "amount_cents")
    if role in ("Excavator", "Locator") and payer_id != user_id:
        raise err_ownership("payer_id must equal X-User-ID")
    payer = _payer_entity(payer_type, payer_id)
    if payer is None:
        raise err_not_found("payer not found")
    claim_invoice_id = body.get("claim_invoice_id")

    now = clock.get_current_utc()
    allocations = []
    case_cache = {}

    if claim_invoice_id is not None:
        inv = db.claim_invoices.get(claim_invoice_id)
        if inv is None:
            raise err_not_found("claim invoice not found")
        recompute_invoice_amount_due(inv)
        if amount > inv["amount_due_cents"]:
            raise err_payment_exceeds()
        allocations.append({"claim_invoice_id": inv["id"], "amount_cents": amount})
        _apply_leg(inv, amount, case_cache)
    else:
        # waterfall across payer's open invoices: due_at ASC, created_at ASC
        candidates = [i for i in db.claim_invoices.values()
                      if i["debtor_type"] == payer_type and i["debtor_id"] == payer_id
                      and i["status"] in ("ISSUED", "PARTIALLY_PAID")]
        candidates.sort(key=lambda i: (i["due_at"], i["created_at"], i["_seq"]))
        remaining = amount
        for inv in candidates:
            if remaining <= 0:
                break
            recompute_invoice_amount_due(inv)
            leg = min(remaining, inv["amount_due_cents"])
            if leg <= 0:
                continue
            allocations.append({"claim_invoice_id": inv["id"], "amount_cents": leg})
            _apply_leg(inv, leg, case_cache)
            remaining -= leg
        if remaining > 0:
            payer["credit_balance_cents"] += remaining
            payer["updated_at"] = now
            payer["version"] += 1

    # recompute debtor outstanding for affected debtors
    affected = {(i["debtor_type"], i["debtor_id"]) for i in db.claim_invoices.values()}
    for leg in allocations:
        inv = db.claim_invoices[leg["claim_invoice_id"]]
        recompute_debtor_outstanding(inv["debtor_type"], inv["debtor_id"])

    pid = new_id()
    payment = {
        "id": pid,
        "payer_type": payer_type,
        "payer_id": payer_id,
        "amount_cents": amount,
        "claim_invoice_id": claim_invoice_id,
        "status": "APPLIED",
        "allocations": allocations,
        "applied_at": now,
        "credit_remainder_cents": (amount - sum(l["amount_cents"] for l in allocations)),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_insert_seq(),
    }
    db.payments[pid] = payment
    return success_envelope(payment_out(payment), "object", 201)


@bp.route("/damage-recovery/payments/<pid>", methods=["GET"])
def get_payment(pid):
    require_roles(*ALL_ROLES)
    p = db.payments.get(pid)
    if p is None:
        raise err_not_found("payment not found")
    return success_envelope(payment_out(p), "object", 200)


@bp.route("/damage-recovery/payments", methods=["GET"])
def list_payments():
    require_roles(*ALL_ROLES)
    limit, offset = get_pagination()
    items = list(db.payments.values())
    payer_id = request.args.get("payer_id")
    invoice_id = request.args.get("claim_invoice_id")
    status = request.args.get("status")
    if payer_id is not None:
        items = [p for p in items if p["payer_id"] == payer_id]
    if invoice_id is not None:
        items = [p for p in items if p["claim_invoice_id"] == invoice_id
                 or any(l["claim_invoice_id"] == invoice_id for l in p["allocations"])]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    page, meta = paginate(items, limit, offset)
    return success_envelope([payment_out(p) for p in page], "array", 200, meta)


@bp.route("/damage-recovery/payments/<pid>/reverse", methods=["POST"])
def reverse_payment(pid):
    require_roles("RecoveryManager")
    p = db.payments.get(pid)
    if p is None:
        raise err_not_found("payment not found")
    if p["status"] != "APPLIED":
        raise err_invalid_state("payment is not APPLIED")
    now = clock.get_current_utc()
    case_cache = {}
    for leg in p["allocations"]:
        inv = db.claim_invoices.get(leg["claim_invoice_id"])
        if inv is None:
            continue
        inv["amount_paid_cents"] -= leg["amount_cents"]
        recompute_invoice_amount_due(inv)
        if inv["status"] in ("ISSUED", "PARTIALLY_PAID", "PAID"):
            inv["status"] = invoice_status_from_paid(inv)
        elif inv["status"] == "DISPUTED":
            # remain disputed until disputes resolve; status recomputed then
            pass
        touch(inv)
        recompute_debtor_outstanding(inv["debtor_type"], inv["debtor_id"])
        case = case_cache.get(inv["damage_case_id"])
        if case is None:
            case = db.damage_cases.get(inv["damage_case_id"])
            case_cache[inv["damage_case_id"]] = case
        if case is not None:
            # reopen RECOVERED -> COLLECTING if a terminal invoice reopened
            if case["recovery_status"] == "RECOVERED":
                case["recovery_status"] = "COLLECTING"
            maybe_advance_case_recovery(case)
    # credit clawback of remainder leg this payment created
    remainder = p.get("credit_remainder_cents", 0)
    if remainder > 0:
        payer = _payer_entity(p["payer_type"], p["payer_id"])
        if payer is not None:
            payer["credit_balance_cents"] -= remainder
            payer["updated_at"] = now
            payer["version"] += 1
    p["status"] = "REVERSED"
    p["updated_at"] = now
    p["version"] += 1
    return success_envelope(payment_out(p), "object", 200)
