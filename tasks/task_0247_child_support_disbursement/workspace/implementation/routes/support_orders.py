"""SupportOrder routes: create, get, list, and the lifecycle transitions."""

from flask import Blueprint, request

import errors
import lookup
from common import (
    stamp_create, touch, get_body, as_int, fk, pagination, paginate, sort_by_created,
)
from db import store
from middleware import require_roles
from response import object_response, array_response
from services import serialize, ledger, calc

bp = Blueprint("support_orders", __name__)

FREQUENCIES = {"MONTHLY"}


@bp.route("/support-orders", methods=["POST"])
@require_roles("CaseWorker")
def create_support_order(auth):
    body = get_body()
    # Existence (priority 3): FK references resolved left-to-right. A referenced
    # id that is present-and-string is resolved here; an absent/non-string FK is
    # a structural error handled by as_str (priority 5).
    cp = lookup.custodial_party(fk(body, "custodial_party_id"))
    ncp = lookup.noncustodial_party(fk(body, "noncustodial_party_id"))

    # Structural validity (priority 5).
    current_support_cents = as_int(body, "current_support_cents")
    frequency = body.get("frequency", "MONTHLY")
    if frequency is None:
        frequency = "MONTHLY"
    if frequency not in FREQUENCIES:
        raise errors.invalid_request("frequency must be one of %s" % sorted(FREQUENCIES))
    interest_rate_bps = as_int(body, "interest_rate_bps", required=False, default=1000)
    assigned_arrears_cents = as_int(body, "assigned_arrears_cents", required=False, default=0)

    rec = stamp_create({
        "custodial_party_id": cp["id"],
        "noncustodial_party_id": ncp["id"],
        "current_support_cents": current_support_cents,
        "frequency": frequency,
        "interest_rate_bps": interest_rate_bps,
        "arrears_distribution_rule": calc.derive_distribution_rule(cp["assistance_status"]),
        "assigned_arrears_cents": assigned_arrears_cents,
        "obligation_status": "ESTABLISHED",
        "enforcement_status": "NONE",
        "last_interest_accrual_at": None,
        "first_activated": False,
    })
    store.support_orders[rec["id"]] = rec
    return object_response(serialize.support_order(rec), 201)


@bp.route("/support-orders/<rid>", methods=["GET"])
@require_roles("CaseWorker", "FinanceOfficer", "CustodialParty")
def get_support_order(auth, rid):
    rec = lookup.support_order(rid)
    lookup.require(lookup.owns_order(auth, rec))
    return object_response(serialize.support_order(rec), 200)


@bp.route("/support-orders", methods=["GET"])
@require_roles("CaseWorker", "FinanceOfficer")
def list_support_orders(auth):
    ncp_id = request.args.get("noncustodial_party_id")
    cp_id = request.args.get("custodial_party_id")
    items = list(store.support_orders.values())
    if ncp_id is not None:
        items = [o for o in items if o["noncustodial_party_id"] == ncp_id]
    if cp_id is not None:
        items = [o for o in items if o["custodial_party_id"] == cp_id]
    items = sort_by_created(items)
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return array_response([serialize.support_order(o) for o in page],
                          limit, offset, total, 200)


@bp.route("/support-orders/<rid>/activate", methods=["POST"])
@require_roles("CaseWorker")
def activate_support_order(auth, rid):
    rec = lookup.support_order(rid)
    status = rec["obligation_status"]
    # State (priority 7): only ESTABLISHED, SUSPENDED, MODIFIED may activate.
    if status not in ("ESTABLISHED", "SUSPENDED", "MODIFIED"):
        raise errors.invalid_state()
    # From ESTABLISHED also requires current_support_cents > 0 (priority 13).
    if status == "ESTABLISHED" and rec["current_support_cents"] <= 0:
        raise errors.invalid_amount()
    rec["obligation_status"] = "ACTIVE"
    if not rec["first_activated"]:
        rec["first_activated"] = True
        rec["last_interest_accrual_at"] = store.now_iso()
        ledger.post_entry(rec["id"], "CHARGE", "CURRENT_SUPPORT",
                          rec["current_support_cents"], rec["id"])
    touch(rec)
    return object_response(serialize.support_order(rec), 200)


@bp.route("/support-orders/<rid>/suspend", methods=["POST"])
@require_roles("CaseWorker")
def suspend_support_order(auth, rid):
    rec = lookup.support_order(rid)
    if rec["obligation_status"] != "ACTIVE":
        raise errors.invalid_state()
    rec["obligation_status"] = "SUSPENDED"
    touch(rec)
    return object_response(serialize.support_order(rec), 200)


@bp.route("/support-orders/<rid>/terminate", methods=["POST"])
@require_roles("CaseWorker")
def terminate_support_order(auth, rid):
    rec = lookup.support_order(rid)
    # State (priority 7).
    if rec["obligation_status"] not in ("ACTIVE", "SUSPENDED", "MODIFIED"):
        raise errors.invalid_state()
    # Arrears guard (priority 14). Interest re-evaluated as part of eligibility.
    if (ledger.arrears_principal_cents(rec["id"]) != 0
            or ledger.interest_balance_cents(rec["id"]) != 0):
        raise errors.arrears_outstanding()
    # Enforcement guard (priority 15).
    if rec["enforcement_status"] in ("INTERCEPT_PENDING", "INTERCEPT_ACTIVE"):
        raise errors.enforcement_active()
    rec["obligation_status"] = "TERMINATED"
    # Cascade: ISSUED/ACKNOWLEDGED IWOs on this order -> TERMINATED.
    for iwo in store.income_withholding_orders.values():
        if iwo["support_order_id"] == rec["id"] and iwo["status"] in ("ISSUED", "ACKNOWLEDGED"):
            iwo["status"] = "TERMINATED"
            touch(iwo)
    touch(rec)
    return object_response(serialize.support_order(rec), 200)


@bp.route("/support-orders/<rid>/accrue-interest", methods=["POST"])
@require_roles("CaseWorker", "FinanceOfficer")
def accrue_interest(auth, rid):
    rec = lookup.support_order(rid)
    changed = calc.accrue_interest(rec)
    # A whole-day accrual advances last_interest_accrual_at (and may post a row)
    # — that is a mutation. PRD 3.6 leaves the order unchanged when < 1 day.
    if changed:
        touch(rec)
    return object_response(serialize.support_order(rec), 200)


@bp.route("/support-orders/<rid>/post-charge", methods=["POST"])
@require_roles("CaseWorker")
def post_charge(auth, rid):
    rec = lookup.support_order(rid)
    # arrears_rollover: move any unpaid current-support balance to principal.
    carry = ledger.current_support_due_cents(rec["id"])
    if carry > 0:
        ledger.post_entry(rec["id"], "PAYMENT", "CURRENT_SUPPORT", carry, rec["id"])
        ledger.post_entry(rec["id"], "CHARGE", "PRINCIPAL", carry, rec["id"])
    # Fresh CURRENT_SUPPORT charge only when ACTIVE or MODIFIED.
    if rec["obligation_status"] in ("ACTIVE", "MODIFIED"):
        ledger.post_entry(rec["id"], "CHARGE", "CURRENT_SUPPORT",
                          rec["current_support_cents"], rec["id"])
    touch(rec)
    return object_response(serialize.support_order(rec), 200)
