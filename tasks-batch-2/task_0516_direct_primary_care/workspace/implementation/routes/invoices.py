"""Invoice read + pay + void (PRD §3.7, §3.8)."""
from flask import Blueprint, request

import db
import errors
import response
import serialize
import validate
from clock import clock
from middleware import authenticate, require_roles
from routes.helpers import get_or_404, require_member_owns

bp = Blueprint("invoices", __name__)


@bp.route("/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin", "Provider", "Member"})
    inv = get_or_404("invoice", iid)
    _read_ownership(caller, inv)
    return response.object_response(serialize.invoice(inv), 200)


@bp.route("/invoices", methods=["GET"])
def list_invoices():
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin", "Provider", "Member"})
    limit, offset = validate.pagination()
    member_id = request.args.get("member_id")
    visit_id = request.args.get("visit_id")
    invoice_status = request.args.get("invoice_status")

    rows = list(db.invoices.values())
    if caller.role == "Member":
        rows = [r for r in rows if r["member_id"] == caller.user_id]
    elif caller.role == "Provider":
        rows = [r for r in rows
                if db.members.get(r["member_id"], {}).get("assigned_provider_id") == caller.user_id]
    if member_id is not None:
        rows = [r for r in rows if r["member_id"] == member_id]
    if visit_id is not None:
        rows = [r for r in rows if r["visit_id"] == visit_id]
    if invoice_status is not None:
        rows = [r for r in rows if r["invoice_status"] == invoice_status]

    page, total = validate.paginate(rows, limit, offset)
    return response.array_response(
        [serialize.invoice(r) for r in page], limit, offset, total, 200
    )


@bp.route("/invoices/<iid>/charge", methods=["POST"])
def charge_invoice(iid):
    caller = authenticate()
    require_roles(caller, {"Member"})
    inv = get_or_404("invoice", iid)
    require_member_owns(caller, inv["member_id"])
    data = validate.body()

    amount_cents = validate.require(data, "amount_cents", int)
    outcome = validate.require(data, "outcome", str)
    validate.enum(outcome, {"SUCCEEDED", "FAILED"}, "outcome")
    if amount_cents < 0:
        raise errors.invalid_request("amount_cents must be >= 0.")

    # State (priority 5): invoice must be ISSUED to be paid.
    if inv["invoice_status"] != "ISSUED":
        raise errors.invalid_state("Invoice is not ISSUED.")

    member = db.members[inv["member_id"]]
    wallet_available = member["wallet_credit_cents"]
    # Wallet applied first; capped at member_responsibility (PRD §3.8).
    wallet_applied = min(wallet_available, inv["member_responsibility_cents"])
    expected_amount = inv["member_responsibility_cents"] - wallet_applied

    # Charge-amount agreement (priority 15): amount == responsibility net of wallet.
    if amount_cents != expected_amount:
        raise errors.amount_mismatch(
            "amount_cents (%d) does not equal amount owed net of wallet (%d)."
            % (amount_cents, expected_amount)
        )

    payment = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "created_at": clock.now(),
        "member_id": inv["member_id"],
        "membership_id": None,
        "invoice_id": inv["id"],
        "charge_kind": "INVOICE",
        "amount_cents": amount_cents,
        "outcome": outcome,
        "wallet_applied_cents": wallet_applied,
    }
    db.payments[payment["id"]] = payment

    if outcome == "SUCCEEDED":
        inv["invoice_status"] = "PAID"
        db.touch(inv)
        member["wallet_credit_cents"] = max(0, wallet_available - wallet_applied)
        db.touch(member)

    return response.object_response(serialize.payment(payment), 201)


@bp.route("/invoices/<iid>/void", methods=["POST"])
def void_invoice(iid):
    caller = authenticate()
    require_roles(caller, {"Provider"})
    inv = get_or_404("invoice", iid)
    # Provider ownership via the linked member's PCP.
    if caller.role == "Provider":
        member = db.members.get(inv["member_id"])
        if member is None or member.get("assigned_provider_id") != caller.user_id:
            raise errors.forbidden("Provider does not own this invoice.")

    if inv["invoice_status"] != "ISSUED":
        raise errors.invalid_state("Only an ISSUED invoice can be voided.")

    inv["invoice_status"] = "VOID"
    db.touch(inv)
    # Compensating cross-entity write-off of the linked visit (PRD §3.8).
    visit = db.visits.get(inv["visit_id"])
    if visit is not None:
        visit["billing_status"] = "WRITTEN_OFF"
        db.touch(visit)

    return response.object_response(serialize.invoice(inv), 200)


def _read_ownership(caller, inv):
    if caller.role == "Member" and caller.user_id != inv["member_id"]:
        raise errors.forbidden("Member does not own this invoice.")
    if caller.role == "Provider":
        member = db.members.get(inv["member_id"])
        if member is None or member.get("assigned_provider_id") != caller.user_id:
            raise errors.forbidden("Provider does not own this invoice.")
