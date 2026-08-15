"""PaymentRun, PaymentRunItem, and RemittanceAdvice endpoints."""

from flask import request

import db
from db import STORE, create_entity, touch, public, sort_default, today, parse_date
from errors import (ApiError, ERR_INVALID_STATE, ERR_NOT_FOUND,
                    ERR_INVALID_REQUEST, ERR_STALE_VERSION, ERR_RUN_DATE_PAST,
                    ERR_EMPTY_PAYMENT_RUN, ERR_INVOICE_NOT_PAYABLE,
                    ERR_CARRIER_NOT_ACTIVE, ERR_FX_RATE_MISSING,
                    ERR_SEGREGATION_OF_DUTIES)
from middleware import (authenticate, require_roles, guard_read_scope,
                        guard_mutation_scope, in_read_scope,
                        require_client_active, resolve, READ_ROLES)
from response import success_object, success_list
from services import (add_run_item, auto_fill_run, lock_run, release_run,
                      settle_run, delete_run_items, run_items_of,
                      invoice_in_open_run, has_fx_path)
from validate import get_body, check_shape, parse_pagination


def _check_run_occ(body, run):
    if "expected_payment_run_version" not in body \
            or not isinstance(body["expected_payment_run_version"], int) \
            or isinstance(body["expected_payment_run_version"], bool):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Missing or invalid field: expected_payment_run_version")
    if body["expected_payment_run_version"] != run["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_payment_run_version does not match current version")


def register(app):

    @app.route("/fap/clients/<cid>/payment-runs", methods=["POST"])
    def create_run(cid):
        uid, role = authenticate()
        require_roles(role, {"FinanceController"})
        client = resolve(STORE.clients, cid)
        require_client_active(client)
        body = get_body(allow_empty=False)
        check_shape(body, {
            "run_date": {"kind": "date", "required": True},
            "currency": {"kind": "string", "required": True},
            "country_scope": {"kind": "string", "required": False},
        })
        # Stage 8: run date must not lie before the current logical date.
        if parse_date(body["run_date"]) < today():
            raise ApiError(ERR_RUN_DATE_PAST, 409,
                           "run_date before current logical date")
        run = create_entity(STORE.runs, {
            "client_id": cid,
            "run_date": body["run_date"],
            "currency": body["currency"],
            "country_scope": body.get("country_scope"),
            "status": "DRAFT",
            "gross_total_minor": 0,
            "discount_total_minor": 0,
            "total_minor": 0,
            "created_by_user_id": uid,
            "locked_by_user_id": None,
        })
        return success_object(public(run), status=201)

    @app.route("/fap/payment-runs/<rid>", methods=["GET"])
    def get_run(rid):
        uid, role = authenticate()
        require_roles(role, READ_ROLES)
        run = guard_read_scope(role, uid, "run", STORE.runs.get(rid))
        return success_object(public(run))

    @app.route("/fap/payment-runs", methods=["GET"])
    def list_runs():
        uid, role = authenticate()
        require_roles(role, READ_ROLES)
        limit, offset = parse_pagination()
        rows = [r for r in STORE.runs.values()
                if in_read_scope(role, uid, "run", r)]
        for param in ("client_id", "status"):
            value = request.args.get(param)
            if value is not None:
                rows = [r for r in rows if str(r.get(param)) == value]
        rows = sort_default(rows)
        total = len(rows)
        page = rows[offset:offset + limit]
        return success_list([public(r) for r in page], limit, offset, total)

    @app.route("/fap/payment-runs/<rid>/items", methods=["POST"])
    def add_item(rid):
        uid, role = authenticate()
        require_roles(role, {"FinanceController"})
        run = resolve(STORE.runs, rid)
        body = get_body(allow_empty=False)
        # Stage 3: body FK — invoice_id exists and belongs to the run's client.
        invoice_id = body.get("invoice_id")
        invoice = None
        if invoice_id is not None:
            invoice = STORE.invoices.get(invoice_id)
            if invoice is None or invoice["client_id"] != run["client_id"]:
                raise ApiError(ERR_NOT_FOUND, 404,
                               "Referenced invoice_id does not exist")
        # Stage 4: optimistic concurrency on the run version.
        _check_run_occ(body, run)
        require_client_active(STORE.clients.get(run["client_id"]))
        check_shape(body, {
            "expected_payment_run_version": {"kind": "integer", "required": True},
            "invoice_id": {"kind": "string", "required": True},
        })
        if run["status"] != "DRAFT":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Items cannot be added to a run in %s" % run["status"])
        # Stage 10: referential status — payable invoice, active carrier.
        if invoice["audit_status"] != "CLEARED" \
                or invoice["payment_status"] != "UNPAID":
            raise ApiError(ERR_INVOICE_NOT_PAYABLE, 409,
                           "Invoice not in audit CLEARED + payment UNPAID")
        if invoice_in_open_run(invoice["id"]):
            raise ApiError(ERR_INVOICE_NOT_PAYABLE, 409,
                           "Invoice is already an item of an open payment run")
        carrier = STORE.carriers.get(invoice["carrier_id"])
        if carrier is None or carrier["status"] != "ACTIVE":
            raise ApiError(ERR_CARRIER_NOT_ACTIVE, 409,
                           "Payment scheduling references a carrier not ACTIVE")
        # Stage 11: fiscal — cross-currency scheduling needs an FX path.
        if not has_fx_path(run["client_id"], invoice["currency"],
                           run["currency"], run["run_date"]):
            raise ApiError(ERR_FX_RATE_MISSING, 409,
                           "No FX rate path from invoice currency to run currency")
        item = add_run_item(run, invoice)
        return success_object(public(item), status=201)

    @app.route("/fap/payment-runs/<rid>/auto_fill", methods=["POST"])
    def auto_fill(rid):
        uid, role = authenticate()
        require_roles(role, {"FinanceController"})
        run = resolve(STORE.runs, rid)
        body = get_body(allow_empty=False)
        # Stage 4: optimistic concurrency on the run version.
        _check_run_occ(body, run)
        require_client_active(STORE.clients.get(run["client_id"]))
        check_shape(body, {
            "expected_payment_run_version": {"kind": "integer", "required": True},
        })
        if run["status"] != "DRAFT":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Auto-fill requires a run in DRAFT, not %s" % run["status"])
        auto_fill_run(run)
        return success_object(public(run))

    @app.route("/fap/payment-runs/<rid>/items", methods=["GET"])
    def list_run_items(rid):
        uid, role = authenticate()
        require_roles(role, READ_ROLES)
        run = guard_read_scope(role, uid, "run", STORE.runs.get(rid))
        limit, offset = parse_pagination()
        rows = run_items_of(run["id"])
        rows = [i for i in rows if in_read_scope(role, uid, "run_item", i)]
        total = len(rows)
        page = rows[offset:offset + limit]
        return success_list([public(i) for i in page], limit, offset, total)

    @app.route("/fap/payment-runs/<rid>/lock", methods=["POST"])
    def lock(rid):
        uid, role = authenticate()
        require_roles(role, {"FinanceController"})
        run = resolve(STORE.runs, rid)
        require_client_active(STORE.clients.get(run["client_id"]))
        body = get_body()
        check_shape(body, {})
        if run["status"] != "DRAFT":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Run cannot be locked from %s" % run["status"])
        if not run_items_of(run["id"]):
            raise ApiError(ERR_EMPTY_PAYMENT_RUN, 409,
                           "Lock attempted on a run with zero items")
        lock_run(run, uid)
        return success_object(public(run))

    @app.route("/fap/payment-runs/<rid>/unlock", methods=["POST"])
    def unlock(rid):
        uid, role = authenticate()
        require_roles(role, {"FinanceController"})
        run = resolve(STORE.runs, rid)
        require_client_active(STORE.clients.get(run["client_id"]))
        body = get_body()
        check_shape(body, {})
        if run["status"] != "LOCKED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Run cannot be unlocked from %s" % run["status"])
        delete_run_items(run)
        run["gross_total_minor"] = 0
        run["discount_total_minor"] = 0
        run["total_minor"] = 0
        run["locked_by_user_id"] = None
        run["status"] = "DRAFT"
        touch(run)
        return success_object(public(run))

    @app.route("/fap/payment-runs/<rid>/release", methods=["POST"])
    def release(rid):
        uid, role = authenticate()
        require_roles(role, {"TreasuryApprover"})
        run = resolve(STORE.runs, rid)
        require_client_active(STORE.clients.get(run["client_id"]))
        body = get_body()
        check_shape(body, {})
        if run["status"] != "LOCKED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Run cannot be released from %s" % run["status"])
        # Stage 7: segregation of duties.
        if uid == run["created_by_user_id"] or uid == run.get("locked_by_user_id"):
            raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                           "Release attempted by the user who created or locked the run")
        release_run(run)
        return success_object(public(run))

    @app.route("/fap/payment-runs/<rid>/settle", methods=["POST"])
    def settle(rid):
        uid, role = authenticate()
        require_roles(role, {"TreasuryApprover"})
        run = resolve(STORE.runs, rid)
        require_client_active(STORE.clients.get(run["client_id"]))
        body = get_body()
        check_shape(body, {})
        if run["status"] != "RELEASED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Run cannot be settled from %s" % run["status"])
        settle_run(run)
        return success_object(public(run))

    @app.route("/fap/payment-runs/<rid>/cancel", methods=["POST"])
    def cancel(rid):
        uid, role = authenticate()
        require_roles(role, {"FinanceController"})
        run = resolve(STORE.runs, rid)
        require_client_active(STORE.clients.get(run["client_id"]))
        body = get_body()
        check_shape(body, {})
        if run["status"] != "DRAFT":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Run cannot be cancelled from %s" % run["status"])
        delete_run_items(run)
        run["status"] = "CANCELLED"
        touch(run)
        return success_object(public(run))

    # --- remittance advices -------------------------------------------------

    @app.route("/fap/payment-runs/<rid>/remittance-advices", methods=["GET"])
    def list_run_advices(rid):
        uid, role = authenticate()
        require_roles(role, READ_ROLES)
        run = guard_read_scope(role, uid, "run", STORE.runs.get(rid))
        limit, offset = parse_pagination()
        rows = [a for a in STORE.advices.values()
                if a["payment_run_id"] == run["id"]]
        rows = [a for a in rows if in_read_scope(role, uid, "advice", a)]
        rows = sort_default(rows)
        total = len(rows)
        page = rows[offset:offset + limit]
        return success_list([public(a) for a in page], limit, offset, total)

    @app.route("/fap/carriers/<carrier_id>/remittance-advices", methods=["GET"])
    def list_carrier_advices(carrier_id):
        uid, role = authenticate()
        require_roles(role, READ_ROLES)
        carrier = guard_read_scope(role, uid, "carrier",
                                   STORE.carriers.get(carrier_id))
        limit, offset = parse_pagination()
        rows = [a for a in STORE.advices.values()
                if a["carrier_id"] == carrier["id"]]
        rows = [a for a in rows if in_read_scope(role, uid, "advice", a)]
        rows = sort_default(rows)
        total = len(rows)
        page = rows[offset:offset + limit]
        return success_list([public(a) for a in page], limit, offset, total)

    @app.route("/fap/remittance-advices/<aid>/acknowledge", methods=["POST"])
    def acknowledge_advice(aid):
        uid, role = authenticate()
        require_roles(role, {"CarrierRep"})
        advice = resolve(STORE.advices, aid)
        guard_mutation_scope(role, uid, "advice", advice)
        run = STORE.runs.get(advice["payment_run_id"])
        require_client_active(STORE.clients.get(run["client_id"]))
        body = get_body()
        check_shape(body, {})
        if advice["status"] != "SENT":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Advice cannot be acknowledged from %s"
                           % advice["status"])
        advice["status"] = "ACKNOWLEDGED"
        touch(advice)
        return success_object(public(advice))
