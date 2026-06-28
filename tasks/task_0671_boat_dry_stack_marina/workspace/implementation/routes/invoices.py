from flask import Blueprint, request

from db import db
from clock import parse_iso
from middleware import require_role
from response import object_response, array_response
from errors import (
    err, ERR_INVALID_STATE, ERR_INVALID_PERIOD, ERR_INVALID_REQUEST,
    ERR_NOT_RESOURCE_OWNER,
)
from services.common import (
    stamp_create, touch, get_json_body, require_fields, require_string,
    require_enum, parse_pagination, paginate,
)
from services.lookups import (
    get_owner, get_invoice, resolve_polymorphic_source, get_vessel,
)
from services.serialize import invoice_view
from services.calculations import compute_invoice_amount, DELINQUENCY_THRESHOLD_CENTS
from services.reconcile import account_balance

invoices_bp = Blueprint("invoices", __name__)

READ_ROLES = {"DockMaster", "BillingClerk", "BoatOwner"}
SOURCE_KINDS = {"STORAGE_AGREEMENT", "LAUNCH_REQUEST", "SERVICE_ORDER"}
VARIANTS = {"PROVISIONAL", "FINAL"}


def _source_vessel_id(source_kind, source):
    """The vessel tied to an invoice source (for delinquency flips)."""
    if source_kind == "STORAGE_AGREEMENT":
        return source["vessel_id"]
    if source_kind == "LAUNCH_REQUEST":
        return source["vessel_id"]
    if source_kind == "SERVICE_ORDER":
        return source["vessel_id"]
    return None


@invoices_bp.route("/marina/invoices", methods=["POST"])
def create_invoice():
    require_role({"BillingClerk"})
    body = get_json_body()
    require_fields(body, ["owner_id", "source_kind", "source_id"])
    require_string(body["owner_id"], "owner_id")
    require_enum(body["source_kind"], SOURCE_KINDS, "source_kind")
    require_string(body["source_id"], "source_id")

    variant = body.get("variant", "FINAL")
    if variant is None:
        variant = "FINAL"
    require_enum(variant, VARIANTS, "variant")

    source_kind = body["source_kind"]
    # For non-storage sources, variant is treated as FINAL regardless.
    if source_kind != "STORAGE_AGREEMENT":
        variant = "FINAL"

    period_start = body.get("period_start")
    period_end = body.get("period_end")

    with db.lock:
        # Priority 4: owner existence.
        get_owner(body["owner_id"])
        # Priority 5: polymorphic source existence (of declared kind).
        source = resolve_polymorphic_source(source_kind, body["source_id"])

        # Priority 18: invoice period validity for storage invoices.
        if source_kind == "STORAGE_AGREEMENT":
            if period_start is None or period_end is None:
                raise err(ERR_INVALID_PERIOD, "Storage invoice requires period_start and period_end.")
            try:
                ps = parse_iso(period_start)
                pe = parse_iso(period_end)
            except (ValueError, TypeError):
                raise err(ERR_INVALID_REQUEST, "period_start/period_end must be ISO-8601 instants.")
            if variant == "FINAL" and not (pe > ps):
                raise err(ERR_INVALID_PERIOD, "period_end must be strictly after period_start.")
            amount = compute_invoice_amount(
                source_kind, variant, agreement=source,
                period_start_dt=ps, period_end_dt=pe)
        elif source_kind == "LAUNCH_REQUEST":
            amount = compute_invoice_amount(source_kind, variant, launch=source)
        else:  # SERVICE_ORDER
            amount = compute_invoice_amount(source_kind, variant, service_order=source)

        rec = {
            "owner_id": body["owner_id"],
            "source_kind": source_kind,
            "source_id": body["source_id"],
            "variant": variant,
            "period_start": period_start,
            "period_end": period_end,
            "amount_cents": amount,
            "status": "ISSUED",
        }
        stamp_create(rec)
        db.invoices[rec["id"]] = rec

        # May flip the source vessel's billing_status to DELINQUENT.
        balance = account_balance(body["owner_id"])
        if balance >= DELINQUENCY_THRESHOLD_CENTS:
            vessel_id = _source_vessel_id(source_kind, source)
            vessel = db.vessels.get(vessel_id) if vessel_id else None
            if vessel is not None and vessel["billing_status"] != "DELINQUENT":
                vessel["billing_status"] = "DELINQUENT"
                touch(vessel)
    return object_response(invoice_view(rec), 201)


@invoices_bp.route("/marina/invoices/<invoice_id>", methods=["GET"])
def fetch_invoice(invoice_id):
    require_role(READ_ROLES)
    rec = get_invoice(invoice_id)
    return object_response(invoice_view(rec), 200)


@invoices_bp.route("/marina/invoices", methods=["GET"])
def list_invoices():
    require_role(READ_ROLES)
    limit, offset = parse_pagination()
    records = list(db.invoices.values())
    owner_id = request.args.get("owner_id")
    source_kind = request.args.get("source_kind")
    source_id = request.args.get("source_id")
    status = request.args.get("status")
    if owner_id is not None:
        records = [r for r in records if r["owner_id"] == owner_id]
    if source_kind is not None:
        records = [r for r in records if r["source_kind"] == source_kind]
    if source_id is not None:
        records = [r for r in records if r["source_id"] == source_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = paginate(records, limit, offset)
    return array_response([invoice_view(r) for r in page], limit, offset, total)


@invoices_bp.route("/marina/invoices/<invoice_id>/pay", methods=["POST"])
def pay_invoice(invoice_id):
    user_id, role = require_role({"BoatOwner"})
    with db.lock:
        rec = get_invoice(invoice_id)
        # Ownership: BoatOwner may only pay their own invoices.
        if role == "BoatOwner" and rec["owner_id"] != user_id:
            raise err(ERR_NOT_RESOURCE_OWNER, "Caller does not own this invoice.")
        if rec["status"] != "ISSUED":
            raise err(ERR_INVALID_STATE, "Invoice must be ISSUED to pay.")
        rec["status"] = "PAID"
        touch(rec)
        # Recompute owner balance; if no other ISSUED invoices remain and the
        # source vessel was DELINQUENT, restore it to ACTIVE_STORAGE.
        remaining = account_balance(rec["owner_id"])
        if remaining == 0:
            source = _resolve_source_quiet(rec["source_kind"], rec["source_id"])
            vessel_id = _source_vessel_id(rec["source_kind"], source) if source else None
            vessel = db.vessels.get(vessel_id) if vessel_id else None
            if vessel is not None and vessel["billing_status"] == "DELINQUENT":
                vessel["billing_status"] = "ACTIVE_STORAGE"
                touch(vessel)
    return object_response(invoice_view(rec), 200)


@invoices_bp.route("/marina/invoices/<invoice_id>/void", methods=["POST"])
def void_invoice(invoice_id):
    require_role({"BillingClerk"})
    with db.lock:
        rec = get_invoice(invoice_id)
        if rec["status"] != "ISSUED":
            raise err(ERR_INVALID_STATE, "Invoice must be ISSUED to void.")
        rec["status"] = "VOIDED"
        touch(rec)
    return object_response(invoice_view(rec), 200)


def _resolve_source_quiet(source_kind, source_id):
    coll = {
        "STORAGE_AGREEMENT": db.agreements,
        "LAUNCH_REQUEST": db.launches,
        "SERVICE_ORDER": db.service_orders,
    }.get(source_kind)
    if coll is None:
        return None
    return coll.get(source_id)
