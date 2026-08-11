"""Billing endpoints: invoices, invoice lines, payments, refunds, disputes."""

from flask import request

from core import (
    db, get_caller, require_role, get_body, ok, parse_pagination, paginate,
    field_str, field_int, field_enum, field_date, stamp_new, touch, sort_created,
    ApiError, err_not_found, err_forbidden, err_invalid, err_family_access,
    family_member_of, check_family_active,
)
from domain import ser_invoice, ser_invoice_line, ser_payment
from billing import (
    generate_invoice, apply_payment_waterfall, reverse_refund, billable_rides,
)

PAYMENT_METHODS = {"CARD", "ACH", "CHECK"}
DISPUTE_ACTIONS = {"RAISE", "RESOLVE_ACCEPT", "RESOLVE_REJECT"}


def _invoice_or_404(iid):
    inv = db.invoices.get(iid)
    if inv is None:
        raise err_not_found("Invoice not found")
    return inv


def _invoice_read_access(caller, inv):
    if caller.role == "Client":
        if inv["client_id"] != caller.user_id:
            raise err_forbidden("Client may only access their own invoices")
    elif caller.role == "FamilyMember":
        member = family_member_of(caller)
        if member is None or member["status"] != "ACTIVE":
            raise err_forbidden("Family membership not active")
        if member["client_id"] != inv["client_id"]:
            raise err_forbidden("Family member may only access their own client's invoices")


def register(app):

    @app.route("/invoices/generate", methods=["POST"])
    def generate():
        body = get_body()
        client_id = field_str(body, "client_id", required=True)
        period_start = field_date(body, "period_start", required=True)
        period_end = field_date(body, "period_end", required=True)
        caller = get_caller()
        require_role(caller, {"BillingAdmin"})
        client = db.clients.get(client_id)
        if client is None:
            raise err_not_found("Client not found")
        if period_end <= period_start:
            raise ApiError(
                "ERR_INVOICE_PERIOD_INVALID", 422,
                "period_end must be strictly after period_start",
            )
        for inv in db.invoices.values():
            if inv["client_id"] != client_id or inv["issuance_status"] == "VOIDED":
                continue
            if (
                period_start < inv["period_end"]
                and inv["period_start"] < period_end
            ):
                raise ApiError(
                    "ERR_INVOICE_PERIOD_OVERLAP", 409,
                    "Period intersects an existing non-VOIDED invoice",
                )
        if not billable_rides(client_id, period_start, period_end):
            raise ApiError(
                "ERR_INVOICE_EMPTY", 422,
                "No billable rides in the requested period",
            )
        invoice = generate_invoice(client, period_start, period_end)
        return ok(ser_invoice(invoice), status=201)

    @app.route("/invoices/<iid>", methods=["GET"])
    def get_invoice(iid):
        caller = get_caller()
        require_role(caller, {"BillingAdmin", "Coordinator", "Client", "FamilyMember"})
        inv = _invoice_or_404(iid)
        _invoice_read_access(caller, inv)
        return ok(ser_invoice(inv))

    @app.route("/invoices", methods=["GET"])
    def list_invoices():
        caller = get_caller()
        require_role(caller, {"BillingAdmin", "Coordinator", "Client", "FamilyMember"})
        limit, offset = parse_pagination()
        items = sort_created(db.invoices.values())
        if caller.role == "Client":
            items = [i for i in items if i["client_id"] == caller.user_id]
        elif caller.role == "FamilyMember":
            member = family_member_of(caller)
            if member is None or member["status"] != "ACTIVE":
                raise err_forbidden("Family membership not active")
            items = [i for i in items if i["client_id"] == member["client_id"]]
        client_id = request.args.get("client_id")
        issuance = request.args.get("issuance_status")
        if client_id is not None:
            items = [i for i in items if i["client_id"] == client_id]
        if issuance is not None:
            items = [i for i in items if i["issuance_status"] == issuance]
        page, meta = paginate(items, limit, offset)
        return ok([ser_invoice(i) for i in page], response_type="array", pagination=meta)

    @app.route("/invoices/<iid>/lines", methods=["GET"])
    def invoice_lines(iid):
        caller = get_caller()
        require_role(caller, {"BillingAdmin", "Coordinator", "Client", "FamilyMember"})
        inv = _invoice_or_404(iid)
        _invoice_read_access(caller, inv)
        limit, offset = parse_pagination()
        items = sort_created(
            [l for l in db.invoice_lines.values() if l["invoice_id"] == iid]
        )
        page, meta = paginate(items, limit, offset)
        return ok(
            [ser_invoice_line(l) for l in page], response_type="array", pagination=meta
        )

    @app.route("/invoice-lines/<lid>", methods=["GET"])
    def get_invoice_line(lid):
        caller = get_caller()
        require_role(caller, {"BillingAdmin", "Coordinator"})
        line = db.invoice_lines.get(lid)
        if line is None:
            raise err_not_found("Invoice line not found")
        return ok(ser_invoice_line(line))

    @app.route("/invoice-lines", methods=["GET"])
    def list_invoice_lines():
        caller = get_caller()
        require_role(caller, {"BillingAdmin", "Coordinator"})
        limit, offset = parse_pagination()
        items = sort_created(db.invoice_lines.values())
        ride_id = request.args.get("ride_id")
        invoice_id = request.args.get("invoice_id")
        line_kind = request.args.get("line_kind")
        if ride_id is not None:
            items = [l for l in items if l["ride_id"] == ride_id]
        if invoice_id is not None:
            items = [l for l in items if l["invoice_id"] == invoice_id]
        if line_kind is not None:
            items = [l for l in items if l["line_kind"] == line_kind]
        page, meta = paginate(items, limit, offset)
        return ok(
            [ser_invoice_line(l) for l in page], response_type="array", pagination=meta
        )

    @app.route("/invoices/<iid>/issue", methods=["POST"])
    def issue_invoice(iid):
        get_body()
        caller = get_caller()
        require_role(caller, {"BillingAdmin"})
        inv = _invoice_or_404(iid)
        if inv["issuance_status"] != "DRAFT":
            raise ApiError(
                "ERR_INVOICE_NOT_ISSUABLE", 409,
                "Only a DRAFT invoice can be issued",
            )
        inv["issuance_status"] = "ISSUED"
        touch(inv)
        return ok(ser_invoice(inv))

    @app.route("/invoices/<iid>/void", methods=["POST"])
    def void_invoice(iid):
        body = get_body()
        field_str(body, "void_reason")
        caller = get_caller()
        require_role(caller, {"BillingAdmin"})
        inv = _invoice_or_404(iid)
        if inv["issuance_status"] not in ("DRAFT", "ISSUED") or inv["paid_cents"] > 0:
            raise ApiError(
                "ERR_INVOICE_NOT_VOIDABLE", 409,
                "Invoice cannot be voided in its current state",
            )
        inv["issuance_status"] = "VOIDED"
        touch(inv)
        if inv["credit_applied_cents"] > 0:
            client = db.clients.get(inv["client_id"])
            if client is not None:
                client["credit_balance_cents"] += inv["credit_applied_cents"]
                touch(client)
        return ok(ser_invoice(inv))

    @app.route("/invoices/<iid>/dispute-events", methods=["POST"])
    def dispute_event(iid):
        body = get_body()
        action = field_enum(body, "action", DISPUTE_ACTIONS, required=True)
        credit_cents = field_int(body, "credit_cents", minimum=0)
        caller = get_caller()
        require_role(caller, {"BillingAdmin", "Client", "FamilyMember"})
        # action-level role gate
        if action == "RAISE" and caller.role == "BillingAdmin":
            raise ApiError(
                "ERR_UNAUTHORIZED_ROLE", 403,
                "BillingAdmin may not raise disputes",
            )
        if action in ("RESOLVE_ACCEPT", "RESOLVE_REJECT") and caller.role != "BillingAdmin":
            raise ApiError(
                "ERR_UNAUTHORIZED_ROLE", 403,
                "Only BillingAdmin may resolve disputes",
            )
        inv = _invoice_or_404(iid)
        # stage-4 ownership: client match only; stage-5 tier check handles
        # revoked memberships and insufficient access levels.
        if caller.role == "Client":
            if inv["client_id"] != caller.user_id:
                raise err_forbidden("Client may only dispute their own invoices")
        elif caller.role == "FamilyMember":
            member = family_member_of(caller)
            if member is None:
                raise err_forbidden("Family member not recognized")
            if member["client_id"] != inv["client_id"]:
                raise err_forbidden(
                    "Family member may only dispute their own client's invoices"
                )
        if caller.role == "FamilyMember":
            member = check_family_active(caller)
            if member["access_level"] != "BILLING_PAYER":
                raise err_family_access(
                    "Dispute actions require BILLING_PAYER access"
                )
        # state preconditions on the two dimensions
        if action == "RAISE":
            if (
                inv["issuance_status"] not in ("ISSUED", "PARTIALLY_PAID")
                or inv["dispute_status"] != "NONE"
            ):
                raise ApiError(
                    "ERR_DISPUTE_ACTION_INVALID", 409,
                    "Dispute can only be raised on an ISSUED or PARTIALLY_PAID "
                    "invoice with no existing dispute",
                )
            inv["dispute_status"] = "DISPUTED"
            touch(inv)
            return ok(ser_invoice(inv))
        # resolutions
        if inv["dispute_status"] != "DISPUTED":
            raise ApiError(
                "ERR_DISPUTE_ACTION_INVALID", 409,
                "Invoice is not in DISPUTED state",
            )
        if action == "RESOLVE_ACCEPT":
            credit = credit_cents if credit_cents is not None else 0
            if credit > inv["total_due_cents"]:
                raise err_invalid("credit_cents exceeds total_due_cents")
            _check_sod(caller, inv)
            inv["dispute_status"] = "RESOLVED_ACCEPTED"
            inv["resolution_credit_cents"] = credit
            inv["resolved_by_user_id"] = caller.user_id
            touch(inv)
            if credit > 0:
                client = db.clients.get(inv["client_id"])
                if client is not None:
                    client["credit_balance_cents"] += credit
                    touch(client)
            return ok(ser_invoice(inv))
        # RESOLVE_REJECT
        _check_sod(caller, inv)
        inv["dispute_status"] = "RESOLVED_REJECTED"
        inv["resolved_by_user_id"] = caller.user_id
        touch(inv)
        return ok(ser_invoice(inv))

    # ------------------------------------------------------------------
    # Payments
    # ------------------------------------------------------------------

    @app.route("/payments", methods=["POST"])
    def create_payment():
        body = get_body()
        client_id = field_str(body, "client_id", required=True)
        amount = field_int(body, "amount_cents", required=True)
        method = field_enum(body, "method", PAYMENT_METHODS, required=True)
        caller = get_caller()
        require_role(caller, {"FamilyMember", "BillingAdmin"})
        if caller.role == "FamilyMember":
            member = family_member_of(caller)
            if member is None:
                raise err_forbidden("Family member not recognized")
            if member["client_id"] != client_id:
                raise err_forbidden("Family member may only pay for their own client")
            member = check_family_active(caller)
            if member["access_level"] != "BILLING_PAYER":
                raise err_family_access("Payments require BILLING_PAYER access")
        client = db.clients.get(client_id)
        if client is None:
            raise err_not_found("Client not found")
        if amount <= 0:
            raise ApiError(
                "ERR_PAYMENT_AMOUNT_INVALID", 422,
                "Payment amount must be positive",
            )
        payment = {
            "client_id": client_id,
            "amount_cents": amount,
            "method": method,
            "status": "SETTLED",
            "refunded_cents": 0,
            "applications": [],
        }
        stamp_new(payment)
        db.payments[payment["id"]] = payment
        apply_payment_waterfall(payment, client)
        return ok(ser_payment(payment), status=201)

    @app.route("/payments/<pid>", methods=["GET"])
    def get_payment(pid):
        caller = get_caller()
        require_role(caller, {"BillingAdmin", "FamilyMember", "Client"})
        payment = db.payments.get(pid)
        if payment is None:
            raise err_not_found("Payment not found")
        if caller.role == "Client":
            if payment["client_id"] != caller.user_id:
                raise err_forbidden("Client may only access their own payments")
        elif caller.role == "FamilyMember":
            member = family_member_of(caller)
            if member is None or member["status"] != "ACTIVE":
                raise err_forbidden("Family membership not active")
            if member["client_id"] != payment["client_id"]:
                raise err_forbidden("Family member may only access their own client's payments")
        return ok(ser_payment(payment))

    @app.route("/payments", methods=["GET"])
    def list_payments():
        caller = get_caller()
        require_role(caller, {"BillingAdmin", "Coordinator"})
        limit, offset = parse_pagination()
        items = sort_created(db.payments.values())
        client_id = request.args.get("client_id")
        status = request.args.get("status")
        if client_id is not None:
            items = [p for p in items if p["client_id"] == client_id]
        if status is not None:
            items = [p for p in items if p["status"] == status]
        page, meta = paginate(items, limit, offset)
        return ok(
            [ser_payment(p) for p in page], response_type="array", pagination=meta
        )

    @app.route("/payments/<pid>/refund", methods=["POST"])
    def refund_payment(pid):
        body = get_body()
        amount = field_int(body, "amount_cents", required=True)
        field_str(body, "reason")
        caller = get_caller()
        require_role(caller, {"BillingAdmin"})
        payment = db.payments.get(pid)
        if payment is None:
            raise err_not_found("Payment not found")
        if payment["status"] == "REFUNDED":
            raise ApiError(
                "ERR_PAYMENT_NOT_REFUNDABLE", 409,
                "Payment is fully refunded",
            )
        if amount <= 0:
            raise err_invalid("Refund amount must be positive")
        if amount > payment["amount_cents"] - payment["refunded_cents"]:
            raise ApiError(
                "ERR_REFUND_EXCEEDS_SETTLED", 422,
                "Refund exceeds the un-refunded remainder",
            )
        client = db.clients.get(payment["client_id"])
        reverse_refund(payment, client, amount)
        return ok(ser_payment(payment))


def _check_sod(caller, invoice):
    """Segregation of duties: resolver must not have dispatched any billed ride."""
    billed_ride_ids = {
        l["ride_id"] for l in db.invoice_lines.values() if l["invoice_id"] == invoice["id"]
    }
    for asg in db.assignments.values():
        if asg["ride_id"] in billed_ride_ids and asg["matched_by_user_id"] == caller.user_id:
            raise ApiError(
                "ERR_SOD_CONFLICT", 403,
                "Resolver dispatched a ride billed on this invoice",
            )
