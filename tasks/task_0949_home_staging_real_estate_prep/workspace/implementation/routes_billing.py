"""Closeout, invoices and deposits."""
import calc
import cascades
import consts as C
import lookup
import serializers as S
import store
from envelope import ok, paginate, pagination, qs
from errors import ApiError
from gates import (body, endpoint, fks, path_row, require, rung12_project_party,
                   rung14_project_closed, rung15_listing_terminated, types)
from store import D, add_days, money


def register(app):
    # ------------------------------------------------------------------
    # closeout
    # ------------------------------------------------------------------
    @app.post("/staging/projects/<project_id>/invoices")
    @endpoint("BillingClerk")
    def open_closeout(project_id):
        project = path_row("projects", project_id)
        rung14_project_closed(project)
        rung15_listing_terminated(lookup.listing_of(project))
        state = project["workflow_state"]
        if state not in ("PICKED_UP", "STAGED"):
            raise ApiError("ERR_PROJECT_INVALID_STATE")                 # rung 19
        if state == "STAGED" and project["pipeline"] != "OCCUPIED_PREP":
            raise ApiError("ERR_PROJECT_INVALID_STATE")
        if state == "PICKED_UP":
            pickup = lookup.active_pickup(project)
            if pickup is not None:
                for assessment in lookup.pickup_assessments(pickup):
                    if assessment["state"] != "FINAL":
                        raise ApiError("ERR_ASSESSMENT_INVALID_STATE")   # rung 29
        invoice = cascades.materialise_invoice(project)
        project["workflow_state"] = "CLOSEOUT"
        store.touch(project)
        return ok(S.invoice(invoice), 201)

    # ------------------------------------------------------------------
    # Invoice
    # ------------------------------------------------------------------
    @app.get("/staging/invoices")
    @endpoint("PlatformAdmin", "BillingClerk", "StagingCoordinator", "ListingAgent",
              "Seller", "BrokerageAdmin")
    def list_invoices():
        limit, offset = pagination()
        rows = store.where("invoices", project_id=qs("project_id"), state=qs("state"))
        return paginate(store.sort_default(rows), S.invoice, limit, offset)

    @app.get("/staging/invoices/<invoice_id>")
    @endpoint("PlatformAdmin", "BillingClerk", "StagingCoordinator", "ListingAgent",
              "Seller", "BrokerageAdmin")
    def read_invoice(invoice_id):
        return ok(S.invoice(path_row("invoices", invoice_id)), 200)

    @app.post("/staging/invoices/<invoice_id>/issue")
    @endpoint("BillingClerk")
    def issue_invoice(invoice_id):
        invoice = path_row("invoices", invoice_id)
        project = store.get("projects", invoice["project_id"])
        if invoice["state"] != "DRAFT":
            raise ApiError("ERR_INVOICE_INVALID_STATE")                 # rung 31
        if project["payer_type"] == "PAY_AT_CLOSING":
            raise ApiError("ERR_INVOICE_INVALID_STATE")
        if project["workflow_state"] != "CLOSEOUT":
            raise ApiError("ERR_INVOICE_INVALID_STATE")
        invoice["state"] = "ISSUED"
        invoice["issued_at"] = store.now()
        invoice["due_date"] = add_days(invoice["issued_at"], C.INVOICE_DUE_DAYS)
        calc.refresh_invoice(invoice)
        store.touch(invoice)
        project["payment_state"] = "INVOICED"
        store.touch(project)
        return ok(S.invoice(invoice), 200)

    @app.post("/staging/invoices/<invoice_id>/defer-to-closing")
    @endpoint("BillingClerk")
    def defer_invoice(invoice_id):
        invoice = path_row("invoices", invoice_id)
        project = store.get("projects", invoice["project_id"])
        listing = lookup.listing_of(project)
        if invoice["state"] != "DRAFT":
            raise ApiError("ERR_INVOICE_INVALID_STATE")                 # rung 31
        if project["payer_type"] != "PAY_AT_CLOSING":
            raise ApiError("ERR_INVOICE_INVALID_STATE")
        if listing is None or listing["listing_state"] not in (
                "ACTIVE", "UNDER_CONTRACT", "BACK_ON_MARKET"):
            raise ApiError("ERR_INVOICE_INVALID_STATE")
        invoice["state"] = "DEFERRED_CLOSING"
        invoice["issued_at"] = store.now()
        invoice["due_date"] = None
        calc.refresh_invoice(invoice)
        store.touch(invoice)
        project["payment_state"] = "DEFERRED"
        store.touch(project)
        return ok(S.invoice(invoice), 200)

    @app.post("/staging/invoices/<invoice_id>/escalate")
    @endpoint("BillingClerk", "PlatformAdmin")
    def escalate_invoice(invoice_id):
        invoice = path_row("invoices", invoice_id)
        project = store.get("projects", invoice["project_id"])
        if invoice["state"] != "PAID" and invoice["state"] != "DEFERRED_CLOSING":
            raise ApiError("ERR_INVOICE_INVALID_STATE")                 # rung 31
        if invoice["state"] == "PAID":
            raise ApiError("ERR_INVOICE_ALREADY_PAID")                  # rung 69
        invoice["state"] = "ESCALATED"
        project["closing_escalation_booked"] = money(
            D(project.get("closing_escalation_booked") or 0) + C.CLOSING_ESCALATION_FEE)
        calc.refresh_invoice(invoice)
        store.touch(invoice)
        project["payment_state"] = "ESCALATED"
        project["fiscal_hold"] = True
        store.touch(project)
        return ok(S.invoice(invoice), 200)

    @app.post("/staging/invoices/<invoice_id>/pay")
    @endpoint("BillingClerk", "BrokerageAdmin")
    def pay_invoice(invoice_id):
        invoice = path_row("invoices", invoice_id)
        payload = body()
        require(payload, ["amount_paid"])
        types(payload, {"amount_paid": ("num", 0, None)})
        project = store.get("projects", invoice["project_id"])
        rung12_project_party(project)
        if invoice["state"] not in ("ISSUED", "ESCALATED", "PAID"):
            raise ApiError("ERR_INVOICE_INVALID_STATE")                 # rung 31
        calc.refresh_invoice(invoice)
        if money(payload["amount_paid"]) != money(invoice["total_due"]):
            raise ApiError("ERR_OVERPAYMENT")                           # rung 68
        if invoice["state"] == "PAID":
            raise ApiError("ERR_INVOICE_ALREADY_PAID")                  # rung 69
        invoice["state"] = "PAID"
        invoice["paid_at"] = store.now()
        calc.refresh_invoice(invoice)
        store.touch(invoice)
        project["payment_state"] = "SETTLED"
        project["fiscal_hold"] = False
        store.touch(project)
        return ok(S.invoice(invoice), 200)

    @app.post("/staging/invoices/<invoice_id>/void")
    @endpoint("PlatformAdmin")
    def void_invoice(invoice_id):
        invoice = path_row("invoices", invoice_id)
        payload = body()
        require(payload, ["reason"])
        types(payload, {"reason": ("str",)})
        project = store.get("projects", invoice["project_id"])
        if invoice["state"] not in ("DRAFT", "ISSUED", "ESCALATED",
                                    "DEFERRED_CLOSING", "PAID"):
            raise ApiError("ERR_INVOICE_INVALID_STATE")                 # rung 31
        if invoice["state"] == "PAID":
            raise ApiError("ERR_INVOICE_ALREADY_PAID")                  # rung 69
        invoice["state"] = "VOID"
        calc.refresh_invoice(invoice)
        store.touch(invoice)
        project["payment_state"] = "WRITTEN_OFF"
        project["fiscal_hold"] = False
        store.touch(project)
        cascades.forfeit_deposit(project)
        return ok(S.invoice(invoice), 200)

    # ------------------------------------------------------------------
    # Deposit
    # ------------------------------------------------------------------
    @app.get("/staging/deposits")
    @endpoint("PlatformAdmin", "BillingClerk", "StagingCoordinator", "ListingAgent",
              "Seller", "BrokerageAdmin")
    def list_deposits():
        limit, offset = pagination()
        rows = store.where("deposits", project_id=qs("project_id"),
                           invoice_id=qs("invoice_id"), state=qs("state"))
        return paginate(store.sort_default(rows), S.deposit, limit, offset)

    @app.get("/staging/deposits/<deposit_id>")
    @endpoint("PlatformAdmin", "BillingClerk", "StagingCoordinator", "ListingAgent",
              "Seller", "BrokerageAdmin")
    def read_deposit(deposit_id):
        return ok(S.deposit(path_row("deposits", deposit_id)), 200)

    @app.post("/staging/deposits/<deposit_id>/collect")
    @endpoint("BillingClerk")
    def collect_deposit(deposit_id):
        deposit = path_row("deposits", deposit_id)
        project = store.get("projects", deposit["project_id"])
        if deposit["state"] != "REQUIRED":
            raise ApiError("ERR_DEPOSIT_INVALID_STATE")                 # rung 32
        amount = D(deposit["amount"])
        if amount != 0 and amount < C.DEPOSIT_MIN_AMOUNT:
            raise ApiError("ERR_DEPOSIT_BELOW_MINIMUM")                 # rung 67
        deposit["state"] = "HELD"
        deposit["held_remaining"] = money(amount)
        store.touch(deposit)
        if project["payment_state"] == "UNBILLED":
            project["payment_state"] = "DEPOSIT_HELD"
            store.touch(project)
        return ok(S.deposit(deposit), 200)

    @app.post("/staging/deposits/<deposit_id>/apply")
    @endpoint("BillingClerk")
    def apply_deposit(deposit_id):
        deposit = path_row("deposits", deposit_id)
        payload = body()
        require(payload, ["invoice_id"])
        types(payload, {"invoice_id": ("str",)})
        fks(payload, {"invoice_id": "invoices"})
        project = store.get("projects", deposit["project_id"])
        invoice = store.get("invoices", payload["invoice_id"])
        if deposit["state"] not in ("HELD", "PARTIALLY_APPLIED"):
            raise ApiError("ERR_DEPOSIT_INVALID_STATE")                 # rung 32
        calc.refresh_invoice(invoice)
        cascades.run_waterfall(project, deposit, invoice)
        return ok(S.deposit(deposit), 200)

    @app.post("/staging/deposits/<deposit_id>/refund")
    @endpoint("BillingClerk")
    def refund_deposit(deposit_id):
        deposit = path_row("deposits", deposit_id)
        project = store.get("projects", deposit["project_id"])
        if deposit["state"] not in ("HELD", "PARTIALLY_APPLIED"):
            raise ApiError("ERR_DEPOSIT_INVALID_STATE")                 # rung 32
        invoice = lookup.project_invoice(project)
        if invoice is None or invoice["state"] != "PAID":
            raise ApiError("ERR_DEPOSIT_INVALID_STATE")                 # rung 73
        deposit["refunded_amount"] = money(D(deposit.get("refunded_amount") or 0)
                                           + D(deposit["held_remaining"]))
        deposit["held_remaining"] = money(0)
        deposit["state"] = "REFUNDED"
        store.touch(deposit)
        return ok(S.deposit(deposit), 200)

    @app.post("/staging/deposits/<deposit_id>/forfeit")
    @endpoint("PlatformAdmin")
    def forfeit_deposit(deposit_id):
        deposit = path_row("deposits", deposit_id)
        payload = body()
        require(payload, ["reason"])
        types(payload, {"reason": ("str",)})
        if deposit["state"] not in ("HELD", "PARTIALLY_APPLIED"):
            raise ApiError("ERR_DEPOSIT_INVALID_STATE")                 # rung 32
        deposit["forfeited_amount"] = money(D(deposit.get("forfeited_amount") or 0)
                                            + D(deposit["held_remaining"]))
        deposit["held_remaining"] = money(0)
        deposit["state"] = "FORFEITED"
        store.touch(deposit)
        return ok(S.deposit(deposit), 200)
