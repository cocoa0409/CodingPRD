"""ClaimInvoice endpoints."""

from datetime import timedelta

from flask import Blueprint, request

import clock
from db import db
from errors import (err_invalid_state, err_invoice_open_dispute, err_not_found,
                    err_write_off_cap)
from middleware import require_roles
from serializers import invoice_out
from services.core import (WRITE_OFF_MAX_CENTS, has_open_dispute,
                           invoice_status_from_paid,
                           maybe_advance_case_recovery,
                           recompute_debtor_outstanding,
                           recompute_invoice_amount_due, touch)
from util import get_pagination, paginate, success_envelope

bp = Blueprint("claim_invoices", __name__)

ALL_ROLES = ("IntakeCoordinator", "DamageInvestigator", "ClaimsAdjuster",
             "RecoveryManager", "Excavator", "Locator")


@bp.route("/damage-recovery/claim-invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    require_roles(*ALL_ROLES)
    inv = db.claim_invoices.get(iid)
    if inv is None:
        raise err_not_found("claim invoice not found")
    return success_envelope(invoice_out(inv), "object", 200)


@bp.route("/damage-recovery/claim-invoices", methods=["GET"])
def list_invoices():
    require_roles(*ALL_ROLES)
    limit, offset = get_pagination()
    items = list(db.claim_invoices.values())
    case_id = request.args.get("damage_case_id")
    alloc_id = request.args.get("fault_allocation_id")
    debtor_id = request.args.get("debtor_id")
    status = request.args.get("status")
    if case_id is not None:
        items = [i for i in items if i["damage_case_id"] == case_id]
    if alloc_id is not None:
        items = [i for i in items if i["fault_allocation_id"] == alloc_id]
    if debtor_id is not None:
        items = [i for i in items if i["debtor_id"] == debtor_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    page, meta = paginate(items, limit, offset)
    return success_envelope([invoice_out(i) for i in page], "array", 200, meta)


@bp.route("/damage-recovery/claim-invoices/<iid>/issue", methods=["POST"])
def issue_invoice(iid):
    require_roles("ClaimsAdjuster")
    inv = db.claim_invoices.get(iid)
    if inv is None:
        raise err_not_found("claim invoice not found")
    if inv["status"] != "DRAFT":
        raise err_invalid_state("invoice is not DRAFT")
    now = clock.get_current_utc()
    inv["status"] = "ISSUED"
    inv["issued_at"] = now
    inv["due_at"] = now + timedelta(days=30)
    touch(inv)
    recompute_debtor_outstanding(inv["debtor_type"], inv["debtor_id"])
    return success_envelope(invoice_out(inv), "object", 200)


@bp.route("/damage-recovery/claim-invoices/<iid>/write-off", methods=["POST"])
def write_off_invoice(iid):
    require_roles("RecoveryManager")
    inv = db.claim_invoices.get(iid)
    if inv is None:
        raise err_not_found("claim invoice not found")
    if inv["status"] not in ("ISSUED", "PARTIALLY_PAID", "DISPUTED"):
        raise err_invalid_state("invoice is not ISSUED or PARTIALLY_PAID")
    if has_open_dispute(inv["id"]):
        raise err_invoice_open_dispute()
    if inv["status"] == "DISPUTED":
        # disputes all terminal but status not yet recomputed: treat per paid amount
        inv["status"] = invoice_status_from_paid(inv)
    recompute_invoice_amount_due(inv)
    if inv["amount_due_cents"] > WRITE_OFF_MAX_CENTS:
        raise err_write_off_cap()
    inv["status"] = "WRITTEN_OFF"
    # PRD §3.5: "A successful write-off moves the invoice to `WRITTEN_OFF`,
    # forgives the remaining `amount_due_cents`..."
    inv["amount_due_cents"] = 0
    touch(inv)
    recompute_debtor_outstanding(inv["debtor_type"], inv["debtor_id"])
    case = db.damage_cases.get(inv["damage_case_id"])
    if case is not None:
        maybe_advance_case_recovery(case)
        touch(case)
    return success_envelope(invoice_out(inv), "object", 200)
