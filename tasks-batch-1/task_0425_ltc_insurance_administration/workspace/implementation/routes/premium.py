"""Premium-invoice endpoints (PRD §3.10, §3.11)."""
from flask import Blueprint, request

import errors
from db import STORE, new_id, common_fields, touch
from middleware import authenticate, authorize
from response import object_response, array_response
from services import common, serialize, lookup, core, calc

bp = Blueprint("premium", __name__)


@bp.route("/policies/<rid>/premium-invoices", methods=["POST"])
def create_invoice(rid):
    caller = authenticate()
    authorize(caller, ["Underwriter"])
    pol = lookup.policy_or_404(rid)
    body = common.get_json_body()
    period_index = common.require_int(body, "period_index")
    base_premium = common.require_int(body, "base_premium_cents")
    due_date = common.require_str(body, "due_date")
    grace_deadline = common.require_str(body, "grace_deadline")

    # amount via calc premium_amount with the applicable approved increase
    pct = core.applicable_increase_pct(rid, period_index)
    amount = calc.premium_amount(base_premium, pct)

    iid = new_id()
    inv = {
        "id": iid,
        "policy_id": rid,
        "period_index": period_index,
        "base_premium_cents": base_premium,
        "amount_cents": amount,
        "due_date": due_date,
        "grace_deadline": grace_deadline,
        "status": "OPEN",
    }
    inv.update(common_fields(STORE.next_seq()))
    STORE.premium_invoices[iid] = inv
    return object_response(serialize.premium_invoice(inv), 201)


@bp.route("/premium-invoices", methods=["GET"])
def list_invoices():
    caller = authenticate()
    authorize(caller, ["Underwriter", "ClaimsExaminer", "Policyholder"])
    records = list(STORE.premium_invoices.values())
    policy_id = request.args.get("policy_id")
    if policy_id is not None:
        records = [r for r in records if r["policy_id"] == policy_id]
    records = lookup.sorted_by_created(records)
    page, limit, offset, total = common.paginate(records)
    return array_response([serialize.premium_invoice(r) for r in page], limit, offset, total)


@bp.route("/premium-invoices/<rid>", methods=["GET"])
def get_invoice(rid):
    caller = authenticate()
    authorize(caller, ["Underwriter", "ClaimsExaminer", "Policyholder"])
    rec = lookup.premium_invoice_or_404(rid)
    return object_response(serialize.premium_invoice(rec), 200)


@bp.route("/premium-invoices/<rid>/pay", methods=["POST"])
def pay_invoice(rid):
    caller = authenticate()
    authorize(caller, ["Policyholder"])
    inv = lookup.premium_invoice_or_404(rid)
    pol = STORE.policies[inv["policy_id"]]

    if pol["premium_status"] == "PENDING":
        # First payment: requires coverage IN_FORCE and invoice OPEN.
        if pol["coverage_status"] != "IN_FORCE":
            raise errors.err(errors.ERR_INVALID_STATE, "Coverage not in force")
        if inv["status"] != "OPEN":
            raise errors.err(errors.ERR_INVOICE_NOT_OPEN, "Invoice not open")
        inv["status"] = "PAID"
        touch(inv)
        pol["premium_status"] = "PAID_CURRENT"
        touch(pol)
        return object_response(serialize.premium_invoice(inv), 200)

    if pol["premium_status"] == "GRACE":
        # Pay within grace: invoice OPEN and clock not past grace_deadline.
        if inv["status"] != "OPEN":
            raise errors.err(errors.ERR_INVOICE_NOT_OPEN, "Invoice not open")
        if STORE.clock_iso is not None and STORE.clock_iso[:10] > inv["grace_deadline"]:
            raise errors.err(errors.ERR_GRACE_EXPIRED, "Grace period expired")
        inv["status"] = "PAID"
        touch(inv)
        pol["premium_status"] = "PAID_CURRENT"
        touch(pol)
        return object_response(serialize.premium_invoice(inv), 200)

    # Any other premium posture: paying requires the invoice to be OPEN.
    if inv["status"] != "OPEN":
        raise errors.err(errors.ERR_INVOICE_NOT_OPEN, "Invoice not open")
    if STORE.clock_iso is not None and STORE.clock_iso[:10] > inv["grace_deadline"]:
        raise errors.err(errors.ERR_GRACE_EXPIRED, "Grace period expired")
    inv["status"] = "PAID"
    touch(inv)
    if pol["premium_status"] in ("PENDING", "GRACE"):
        pol["premium_status"] = "PAID_CURRENT"
        touch(pol)
    return object_response(serialize.premium_invoice(inv), 200)
