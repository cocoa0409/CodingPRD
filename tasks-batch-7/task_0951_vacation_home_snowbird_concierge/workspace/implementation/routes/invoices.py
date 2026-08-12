from flask import Blueprint

import calc
import core
import gates
import serialize
from core import fail, get, new_row, now, touch
from gates import check_state

bp = Blueprint("invoices", __name__)

READ_ROLES = ["AccountManager", "PlatformAdmin", "Owner", "Auditor"]


@bp.post("/property-care/billing-cycles/<cid>/invoices")
def open_invoice(cid):
    gates.begin(["AccountManager", "PlatformAdmin"])
    cycle = gates.fetch_path("billing_cycles", cid)
    sub = get("subscriptions", cycle["subscription_id"])
    if sub is None or sub["status"] == "CANCELLED":
        fail("ERR_NO_ACTIVE_SUBSCRIPTION", "The property has no active subscription.")
    prop = get("properties", sub["property_id"])
    invoice = new_row(
        "invoices",
        billing_cycle_id=cycle["id"],
        property_id=sub["property_id"],
        owner_id=(prop or {}).get("owner_id"),
        status="DRAFT",
        storm_surcharge_pct=0.0, gross_service_cents=0, entitlement_offset_cents=0,
        storm_surcharge_cents=0, guarantee_credit_cents=0, subtotal_cents=0, tax_cents=0,
        late_fee_cents=0, total_cents=0, amount_paid_cents=0, balance_due_cents=0,
        issued_at=None, paid_at=None, dispute_count=0,
    )
    calc.append_invoice_line(invoice, "SUBSCRIPTION_FEE", "Subscription fee",
                             cycle["prorated_fee_cents"], taxable=True)
    calc.recompute_invoice(invoice)
    return core.ok(serialize.invoice(invoice), 201)


@bp.get("/property-care/invoices")
def list_invoices():
    gates.begin(READ_ROLES)
    return gates.list_response("invoices", ["billing_cycle_id", "property_id", "owner_id", "status"],
                               serialize.invoice)


@bp.get("/property-care/invoices/<iid>")
def read_invoice(iid):
    role, user_id = gates.begin(READ_ROLES)
    invoice = gates.fetch_path("invoices", iid)
    gates.owner_scope(role, user_id, invoice.get("owner_id"))
    return core.ok(serialize.invoice(invoice))


LINE_SPEC = [
    ("line_type", "string", True),
    ("description", "string", True),
    ("amount_cents", "integer", True),
    ("taxable", "boolean", False),
    ("visit_id", "string", False),
    ("work_order_id", "string", False),
    ("security_incident_id", "string", False),
    ("mail_hold_id", "string", False),
]


@bp.post("/property-care/invoices/<iid>/lines")
def append_line(iid):
    gates.begin(["AccountManager", "PlatformAdmin"])
    invoice = gates.fetch_path("invoices", iid)
    body = gates.body_json()
    gates.resolve_optional_fks(body, ["visit_id", "work_order_id", "security_incident_id",
                                      "mail_hold_id"])
    if invoice["status"] != "DRAFT":
        fail("ERR_INVOICE_NOT_DRAFT", "Lines may only be appended to a draft invoice.")
    gates.validate_payload(body, LINE_SPEC)
    line_type = body["line_type"]
    amount = body["amount_cents"]
    if line_type in core.NEGATIVE_LINE_TYPES:
        if amount > 0:
            fail("ERR_LINE_SIGN_INVALID", "That line type must carry a non-positive amount.")
    elif amount < 0:
        fail("ERR_LINE_SIGN_INVALID", "That line type must carry a non-negative amount.")

    line = calc.append_invoice_line(
        invoice, line_type, body["description"], amount,
        taxable=body.get("taxable", True),
        visit_id=body.get("visit_id"), work_order_id=body.get("work_order_id"),
        security_incident_id=body.get("security_incident_id"),
        mail_hold_id=body.get("mail_hold_id"))
    return core.ok(serialize.invoice_line(line), 201)


@bp.get("/property-care/invoice-lines")
def list_lines():
    gates.begin(READ_ROLES)
    return gates.list_response(
        "invoice_lines",
        ["invoice_id", "visit_id", "work_order_id", "security_incident_id", "mail_hold_id",
         "line_type", "status"],
        serialize.invoice_line)


@bp.get("/property-care/invoice-lines/<lid>")
def read_line(lid):
    role, user_id = gates.begin(READ_ROLES)
    line = gates.fetch_path("invoice_lines", lid)
    invoice = get("invoices", line["invoice_id"])
    gates.owner_scope(role, user_id, (invoice or {}).get("owner_id"))
    return core.ok(serialize.invoice_line(line))


@bp.post("/property-care/invoice-lines/<lid>/void")
def void_line(lid):
    gates.begin(["AccountManager", "PlatformAdmin"])
    line = gates.fetch_path("invoice_lines", lid)
    if line["status"] == "VOID":
        fail("ERR_LINE_ALREADY_VOID", "That line is already void.")
    line["status"] = "VOID"
    line["tax_cents"] = 0
    touch(line)
    invoice = get("invoices", line["invoice_id"])
    if invoice is not None:
        calc.recompute_invoice(invoice)
        touch(invoice)
    return core.ok(serialize.invoice_line(line))


@bp.post("/property-care/invoices/<iid>/issue")
def issue(iid):
    gates.begin(["AccountManager", "PlatformAdmin"])
    invoice = gates.fetch_path("invoices", iid)
    check_state("invoice", invoice, ["DRAFT"])
    cycle = get("billing_cycles", invoice["billing_cycle_id"])
    sub = get("subscriptions", (cycle or {}).get("subscription_id"))
    if sub is not None and sub["status"] == "CANCELLED":
        fail("ERR_SUBSCRIPTION_CANCELLED", "The subscription is cancelled.")
    active = [l for l in calc.invoice_lines_of(invoice["id"]) if l["status"] == "ACTIVE"]
    if not active:
        fail("ERR_INVOICE_HAS_NO_LINES", "The invoice carries no active line.")
    calc.recompute_invoice(invoice)
    invoice["status"] = "ISSUED"
    invoice["issued_at"] = now()
    touch(invoice)
    return core.ok(serialize.invoice(invoice))


@bp.post("/property-care/invoices/<iid>/pay")
def pay(iid):
    role, user_id = gates.begin(["AccountManager", "PlatformAdmin", "Owner"])
    invoice = gates.fetch_path("invoices", iid)
    gates.owner_scope(role, user_id, invoice.get("owner_id"))
    check_state("invoice", invoice, ["ISSUED", "PARTIALLY_PAID"])
    body = gates.body_json()
    amount = body.get("amount_cents")
    if isinstance(amount, int) and not isinstance(amount, bool) and amount <= 0:
        fail("ERR_PAYMENT_AMOUNT_INVALID", "The payment amount must be strictly positive.")
    gates.validate_payload(body, [("amount_cents", "integer", True)])
    amount = body["amount_cents"]

    if amount >= invoice["balance_due_cents"]:
        invoice["amount_paid_cents"] = invoice["total_cents"]
        invoice["balance_due_cents"] = 0
        invoice["paid_at"] = now()
        invoice["status"] = "PAID"
    else:
        invoice["amount_paid_cents"] += amount
        invoice["balance_due_cents"] = invoice["total_cents"] - invoice["amount_paid_cents"]
        invoice["status"] = "PARTIALLY_PAID"
    touch(invoice)
    return core.ok(serialize.invoice(invoice))


@bp.post("/property-care/invoices/<iid>/dispute")
def dispute(iid):
    role, user_id = gates.begin(["Owner"])
    invoice = gates.fetch_path("invoices", iid)
    gates.owner_scope(role, user_id, invoice.get("owner_id"))
    check_state("invoice", invoice, ["ISSUED"])
    body = gates.body_json()
    gates.validate_payload(body, [("resolution_note", "string", False)])
    invoice["status"] = "DISPUTED"
    invoice["dispute_count"] += 1
    touch(invoice)
    return core.ok(serialize.invoice(invoice))


@bp.post("/property-care/invoices/<iid>/resolve-dispute")
def resolve_dispute(iid):
    gates.begin(["AccountManager", "PlatformAdmin"])
    invoice = gates.fetch_path("invoices", iid)
    check_state("invoice", invoice, ["DISPUTED"])
    calc.recompute_invoice(invoice)
    invoice["status"] = "ISSUED"
    touch(invoice)
    return core.ok(serialize.invoice(invoice))


@bp.post("/property-care/invoices/<iid>/void")
def void_invoice(iid):
    gates.begin(["AccountManager", "PlatformAdmin"])
    invoice = gates.fetch_path("invoices", iid)
    check_state("invoice", invoice, ["DRAFT", "ISSUED"])
    if invoice["status"] == "ISSUED" and invoice["amount_paid_cents"] != 0:
        fail("ERR_INVOICE_ALREADY_PAID", "A part-paid invoice may not be voided.")
    for line in calc.invoice_lines_of(invoice["id"]):
        if line["status"] == "ACTIVE":
            line["status"] = "VOID"
            line["tax_cents"] = 0
            touch(line)
    invoice["status"] = "VOID"
    calc.recompute_invoice(invoice)
    touch(invoice)
    return core.ok(serialize.invoice(invoice))
