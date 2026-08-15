"""Fleet accounts and invoices (PRD §3.9)."""
import calendar
from datetime import timedelta

from flask import Blueprint, request

import auth
import domain
import errors
import services
import util

bp = Blueprint("fleets", __name__)
FLEET_READ_ROLES = ("FleetManager", "NetworkAdmin")
OPEN_INVOICE_STATUSES = ("ISSUED", "PARTIALLY_PAID", "OVERDUE", "DISPUTED")


def _fleet_or_404(fleet_id):
    fleet = domain.get("fleet_accounts", fleet_id)
    if fleet is None:
        raise errors.not_found("FleetAccount not found")
    return fleet


def _serialize_fleet(fleet):
    return domain.serialize_fleet(fleet, services.fleet_balance(fleet["id"]))


def _own_fleet(ident, fleet_id):
    if ident.role == "FleetManager" and ident.user_id != fleet_id:
        raise errors.forbidden("FleetManager may access only their own fleet")


# --------------------------------------------------------------------------
# Fleet accounts
# --------------------------------------------------------------------------
@bp.post("/fleet-accounts")
def create_fleet():
    ident = auth.identity()
    auth.require_roles(ident, ("NetworkAdmin",))
    body = util.get_body(required=True)
    util.req_fields(body, ["company_name", "credit_limit_cents"])
    name = util.req_str(body, "company_name")
    limit = util.req_int(body, "credit_limit_cents")
    terms = util.opt_int(body, "payment_terms_days", 30)
    fleet = domain.new_entity("fleet_accounts", {
        "company_name": name,
        "credit_limit_cents": limit,
        "payment_terms_days": terms,
        "status": "ACTIVE",
        "auto_suspended": False,
        "credit_cents": 0,
    })
    return util.ok(_serialize_fleet(fleet), status=201)


@bp.get("/fleet-accounts/<fleet_id>")
def get_fleet(fleet_id):
    ident = auth.identity()
    auth.require_roles(ident, FLEET_READ_ROLES)
    _own_fleet(ident, fleet_id)
    return util.ok(_serialize_fleet(_fleet_or_404(fleet_id)))


@bp.post("/fleet-accounts/<fleet_id>/close")
def close_fleet(fleet_id):
    ident = auth.identity()
    auth.require_roles(ident, ("NetworkAdmin",))
    fleet = _fleet_or_404(fleet_id)
    if fleet["status"] not in ("ACTIVE", "SUSPENDED"):
        raise errors.invalid_state("FleetAccount is already CLOSED")
    if services.fleet_balance(fleet_id) != 0:
        raise errors.invalid_state("Fleet balance must be zero to close")
    for inv in domain.all_of("invoices"):
        if inv["fleet_account_id"] == fleet_id and inv["status"] in OPEN_INVOICE_STATUSES:
            raise errors.invalid_state("Open invoices prevent closure")
    fleet["status"] = "CLOSED"
    domain.touch(fleet)
    # Fleet close system-cancels future fleet-billed bookings, then revokes
    # every non-terminal authorization.
    now = domain.db.clock_now()
    bookings = [b for b in domain.all_of("bookings")
                if b["fleet_account_id"] == fleet_id
                and b["payment_mode"] == "FLEET_BILL"
                and b["status"] == "BOOKED" and b["checkin_open_at"] > now]
    for b in sorted(bookings, key=lambda x: (x["created_at"], x["_seq"])):
        services.system_cancel_booking(b)
    for a in domain.all_of("driver_authorizations"):
        if (a["fleet_account_id"] == fleet_id
                and a["status"] in ("PENDING", "ACTIVE", "SUSPENDED")):
            a["status"] = "REVOKED"
            domain.touch(a)
    return util.ok(_serialize_fleet(fleet))


@bp.post("/fleet-accounts/<fleet_id>/ops-run")
def fleet_ops(fleet_id):
    ident = auth.identity()
    auth.require_roles(ident, ("NetworkAdmin",))
    fleet = _fleet_or_404(fleet_id)
    services.fleet_ops_run(fleet)
    return util.ok(_serialize_fleet(fleet))


@bp.post("/fleet-accounts/<fleet_id>/close-billing-period")
def close_billing_period(fleet_id):
    ident = auth.identity()
    auth.require_roles(ident, ("NetworkAdmin",))
    fleet = _fleet_or_404(fleet_id)
    body = util.get_body(required=True)
    util.req_fields(body, ["period"])
    period = util.req_str(body, "period")
    try:
        year_s, month_s = period.split("-")
        year, month = int(year_s), int(month_s)
        if len(year_s) != 4 or len(month_s) != 2 or not (1 <= month <= 12):
            raise ValueError
    except (ValueError, AttributeError):
        raise errors.validation("period must be YYYY-MM")

    members = [b for b in domain.all_of("bookings")
               if b["fleet_account_id"] == fleet_id
               and b["payment_mode"] == "FLEET_BILL"
               and b["billing_status"] == "UNBILLED"
               and b["final_total_cents"] is not None
               and b.get("settled_at") is not None
               and b["settled_at"].year == year and b["settled_at"].month == month]
    members = sorted(members, key=lambda x: (x["created_at"], x["_seq"]))
    if not members:
        raise errors.validation("No billable members in the period")

    gross = sum(b["final_total_cents"] for b in members)
    if gross >= 5000000:
        pct = 8
    elif gross >= 2000000:
        pct = 5
    elif gross >= 500000:
        pct = 2
    else:
        pct = 0
    discount = util.rhu_cents(util.Decimal(gross * pct) / util.Decimal(100))
    net = gross - discount
    last_day = calendar.monthrange(year, month)[1]
    from datetime import date as _date
    due = _date(year, month, last_day) + timedelta(days=fleet["payment_terms_days"])

    invoice = domain.new_entity("invoices", {
        "fleet_account_id": fleet_id,
        "period": period,
        "status": "ISSUED",
        "gross_cents": gross,
        "discount_pct": pct,
        "discount_cents": discount,
        "net_cents": net,
        "paid_cents": 0,
        "due_date": due,
        "booking_ids": [b["id"] for b in members],
    })
    for b in members:
        b["billing_status"] = "INVOICED"
        domain.touch(b)
    return util.ok(domain.serialize_invoice(invoice), status=201)


# --------------------------------------------------------------------------
# Invoices
# --------------------------------------------------------------------------
def _invoice_or_404(invoice_id):
    inv = domain.get("invoices", invoice_id)
    if inv is None:
        raise errors.not_found("Invoice not found")
    return inv


def _write_off(inv):
    """WRITTEN_OFF cascade (PRD §3.9)."""
    inv["status"] = "WRITTEN_OFF"
    domain.touch(inv)
    for bid in inv["booking_ids"]:
        b = domain.get("bookings", bid)
        if b is None or b["billing_status"] == "WAIVED":
            continue
        was_paid = b["billing_status"] == "PAID"
        b["billing_status"] = "WAIVED"
        domain.touch(b)
        if was_paid:
            services.loyalty_clawback(b)
    if inv["paid_cents"] > 0:
        fleet = domain.get("fleet_accounts", inv["fleet_account_id"])
        if fleet is not None:
            fleet["credit_cents"] += inv["paid_cents"]
            domain.touch(fleet)


@bp.get("/invoices")
def list_invoices():
    ident = auth.identity()
    auth.require_roles(ident, FLEET_READ_ROLES)
    fleet_f = request.args.get("fleet_account_id")
    status_f = request.args.get("status")
    period_f = request.args.get("period")
    items = list(domain.all_of("invoices"))
    if ident.role == "FleetManager":
        items = [i for i in items if i["fleet_account_id"] == ident.user_id]
    if fleet_f is not None:
        items = [i for i in items if i["fleet_account_id"] == fleet_f]
    if status_f is not None:
        items = [i for i in items if i["status"] == status_f]
    if period_f is not None:
        items = [i for i in items if i["period"] == period_f]
    items = util.sort_created(items)
    page, pg = util.paginate(items)
    return util.ok([domain.serialize_invoice(i) for i in page], pagination=pg)


@bp.get("/invoices/<invoice_id>")
def get_invoice(invoice_id):
    ident = auth.identity()
    auth.require_roles(ident, FLEET_READ_ROLES)
    inv = _invoice_or_404(invoice_id)
    _own_fleet(ident, inv["fleet_account_id"])
    return util.ok(domain.serialize_invoice(inv))


@bp.post("/invoices/<invoice_id>/payments")
def pay_invoice(invoice_id):
    ident = auth.identity()
    auth.require_roles(ident, ("FleetManager",))
    inv = _invoice_or_404(invoice_id)
    if inv["fleet_account_id"] != ident.user_id:
        raise errors.forbidden("FleetManager may pay only own-fleet invoices")
    body = util.get_body(required=True)
    util.req_fields(body, ["amount_cents"])
    amount = util.req_int(body, "amount_cents")
    if amount <= 0:
        raise errors.validation("amount_cents must be positive")
    if inv["status"] not in ("ISSUED", "PARTIALLY_PAID", "OVERDUE"):
        raise errors.invoice_not_payable()
    remaining = inv["net_cents"] - inv["paid_cents"]
    if amount > remaining:
        raise errors.overpayment()
    if amount == remaining:
        inv["paid_cents"] = inv["net_cents"]
        inv["status"] = "PAID"
        domain.touch(inv)
        # Cascade: every member booking flips INVOICED -> PAID and earns points.
        for bid in inv["booking_ids"]:
            b = domain.get("bookings", bid)
            if b is not None and b["billing_status"] == "INVOICED":
                b["billing_status"] = "PAID"
                domain.touch(b)
                services.loyalty_earn(b)
    else:
        inv["paid_cents"] += amount
        inv["status"] = "PARTIALLY_PAID"
        domain.touch(inv)
    return util.ok(domain.serialize_invoice(inv), status=201)


@bp.post("/invoices/<invoice_id>/dispute")
def dispute_invoice(invoice_id):
    ident = auth.identity()
    auth.require_roles(ident, ("FleetManager",))
    inv = _invoice_or_404(invoice_id)
    if inv["fleet_account_id"] != ident.user_id:
        raise errors.forbidden("FleetManager may dispute only own-fleet invoices")
    body = util.get_body(required=True)
    util.req_fields(body, ["reason"])
    util.req_str(body, "reason")
    if inv["status"] not in ("ISSUED", "PARTIALLY_PAID", "OVERDUE", "PAID"):
        raise errors.invalid_state("Invoice not in a disputable status")
    inv["status"] = "DISPUTED"
    domain.touch(inv)
    return util.ok(domain.serialize_invoice(inv))


@bp.post("/invoices/<invoice_id>/resolve-dispute")
def resolve_dispute(invoice_id):
    ident = auth.identity()
    auth.require_roles(ident, ("NetworkAdmin",))
    inv = _invoice_or_404(invoice_id)
    body = util.get_body(required=True)
    util.req_fields(body, ["outcome"])
    outcome = util.req_enum(body, "outcome", ("UPHELD", "WAIVED"))
    if inv["status"] != "DISPUTED":
        raise errors.invalid_state("Invoice is not DISPUTED")
    if outcome == "UPHELD":
        inv["status"] = "ISSUED"  # due_date unchanged
        domain.touch(inv)
    else:
        _write_off(inv)
    return util.ok(domain.serialize_invoice(inv))


@bp.post("/invoices/<invoice_id>/write-off")
def write_off_invoice(invoice_id):
    ident = auth.identity()
    auth.require_roles(ident, ("NetworkAdmin",))
    inv = _invoice_or_404(invoice_id)
    if inv["status"] != "OVERDUE":
        raise errors.invalid_state("Only an OVERDUE invoice may be written off")
    _write_off(inv)
    return util.ok(domain.serialize_invoice(inv))
