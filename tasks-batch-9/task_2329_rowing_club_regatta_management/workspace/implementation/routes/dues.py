"""Dues invoices: assessment, payment, true-up, void and the delinquency run."""
from flask import Blueprint

import auth
import cascade
import clock
import db
import derive
import helpers
import response
import validate
from errors import fail

bp = Blueprint("dues", __name__)

PAYABLE = ("ISSUED", "PARTIALLY_PAID", "DELINQUENT")


def _payable(invoice):
    """Ladder rung 55 (rung 8 is carved out for payments and true-up)."""
    if invoice["status"] not in PAYABLE:
        fail("ERR_INVOICE_NOT_PAYABLE",
             "Invoice %s is %s and can no longer be billed or paid."
             % (invoice["id"], invoice["status"]))


@bp.post("/dues-invoices")
@auth.require("ClubAdmin")
def issue_invoice():
    data = validate.body()
    helpers.check_fk("member", data, "member_id")
    member_id = validate.string(data, "member_id")
    season_year = validate.integer(data, "season_year")
    billable_months = validate.integer(data, "billable_months", minimum=1, maximum=12)
    due_at, due_raw = validate.datetime_field(data, "due_at")
    locker = validate.boolean(data, "locker_requested", required=False, default=False)

    member = db.members[member_id]
    invoice = db.base_record()
    invoice["member_id"] = member_id
    invoice["season_year"] = season_year
    invoice["billable_months"] = billable_months
    invoice["locker_requested"] = locker
    db.set_dt(invoice, "due_at", due_at, due_raw)
    invoice["variant_basis"] = "PROVISIONAL"
    invoice["assessed_cents"] = derive.dues_provisional_cents(member, billable_months, locker)
    invoice["trueup_cents"] = None
    invoice["paid_cents"] = 0
    invoice["status"] = "ISSUED"
    db.invoices[invoice["id"]] = invoice
    # dues_balance_cents / boathouse_access_level are derived, but the member row
    # is materially changed by the new liability.
    db.touch(member)
    return response.created(derive.invoice_out(invoice))


@bp.get("/dues-invoices/<ident>")
@auth.require("ClubAdmin", "Member")
def get_invoice(ident):
    invoice = helpers.load("invoice", ident)
    return response.ok(derive.invoice_out(invoice))


@bp.post("/dues-invoices/<ident>/payments")
@auth.require("Member", "ClubAdmin")
def pay_invoice(ident):
    invoice = helpers.load("invoice", ident)
    data = validate.body()
    amount = validate.integer(data, "amount_cents", minimum=1)

    _payable(invoice)
    remaining = invoice["assessed_cents"] - invoice["paid_cents"]
    if amount > remaining:
        fail("ERR_PAYMENT_EXCEEDS_BALANCE",
             "The payment of %d cents exceeds the remaining balance of %d cents."
             % (amount, remaining))

    invoice["paid_cents"] += amount
    if invoice["paid_cents"] >= invoice["assessed_cents"]:
        invoice["status"] = "PAID"
    else:
        invoice["status"] = "PARTIALLY_PAID"
    db.touch(invoice)

    member = db.members.get(invoice["member_id"])
    if member is not None:
        db.touch(member)
        cascade.clear_member_dues_hold(member)
    return response.ok(derive.invoice_out(invoice))


@bp.post("/dues-invoices/<ident>/true-up")
@auth.require("ClubAdmin")
def true_up_invoice(ident):
    invoice = helpers.load("invoice", ident)
    data = validate.body()
    validate.string(data, "note", required=False, nullable=True)

    _payable(invoice)
    if invoice["variant_basis"] != "PROVISIONAL":
        fail("ERR_TRUEUP_ALREADY_APPLIED",
             "Invoice %s has already been trued up." % invoice["id"])
    if invoice["status"] != "PARTIALLY_PAID":
        helpers.invalid_transition(
            "Only a PARTIALLY_PAID invoice may be trued up; this one is %s."
            % invoice["status"])

    member = db.members.get(invoice["member_id"])
    previous = invoice["assessed_cents"]
    assessed = derive.dues_trueup_cents(member)
    invoice["assessed_cents"] = assessed
    invoice["trueup_cents"] = assessed - previous
    invoice["variant_basis"] = "TRUEUP"
    if invoice["paid_cents"] >= assessed:
        invoice["status"] = "PAID"
    db.touch(invoice)

    if member is not None:
        db.touch(member)
        cascade.clear_member_dues_hold(member)
    return response.ok(derive.invoice_out(invoice))


@bp.post("/dues-invoices/<ident>/void")
@auth.require("ClubAdmin")
def void_invoice(ident):
    invoice = helpers.load("invoice", ident)
    data = validate.body()
    validate.string(data, "reason")

    helpers.not_terminal("invoice", invoice)
    if invoice["paid_cents"] != 0:
        fail("ERR_INVOICE_HAS_PAYMENTS",
             "Invoice %s already carries %d cents of payments."
             % (invoice["id"], invoice["paid_cents"]))
    if invoice["status"] != "ISSUED":
        helpers.invalid_transition(
            "Only an ISSUED invoice may be voided; this one is %s." % invoice["status"])

    invoice["status"] = "VOIDED"
    db.touch(invoice)
    member = db.members.get(invoice["member_id"])
    if member is not None:
        db.touch(member)
        cascade.clear_member_dues_hold(member)
    return response.ok(derive.invoice_out(invoice))


@bp.post("/ops/dues-delinquency-run")
@auth.require("ClubAdmin")
def delinquency_run():
    data = validate.body()
    season_year = validate.integer(data, "season_year", required=False, nullable=True)

    now = clock.now()

    def past_due(inv):
        if inv["status"] not in ("ISSUED", "PARTIALLY_PAID"):
            return False
        if season_year is not None and inv["season_year"] != season_year:
            return False
        due = db.dt(inv, "due_at")
        if due is None or not due < now:
            return False
        return inv["paid_cents"] < inv["assessed_cents"]

    flagged = db.ordered(db.invoices, past_due)

    # Hop 1: the invoices themselves.
    member_ids = []
    for invoice in flagged:
        invoice["status"] = "DELINQUENT"
        db.touch(invoice)
        if invoice["member_id"] not in member_ids:
            member_ids.append(invoice["member_id"])

    # Hops 2 to 4: member hold, seat blocks, entry demotion and lane voiding.
    for member_id in member_ids:
        member = db.members.get(member_id)
        if member is None:
            continue
        db.touch(member)
        if member["membership_status"] == "ACTIVE":
            member["membership_status"] = "DUES_HOLD"
            db.touch(member)
        cascade.block_member_seats_for_dues(member)

    return response.ok_array([derive.invoice_out(i) for i in flagged])
