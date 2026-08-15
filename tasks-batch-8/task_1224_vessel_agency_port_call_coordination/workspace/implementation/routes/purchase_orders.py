"""PurchaseOrder endpoints with the invoice variance fork."""
from flask import Blueprint, request

from errors import invalid_request, invalid_state, not_found, raise_err
from middleware import require_roles, ANY_ROLE
from response import ok_list, ok_object
from services import domain
from services.domain import DA_EDITABLE_STATUSES
from services.serializers import serialize, serialize_many
from utils import (is_int, new_entity, paginate, pagination_args, parse_dt,
                   sort_created, touch)

bp = Blueprint("purchase_orders", __name__)

CATEGORIES = {"PROVISIONS", "BUNKERS", "REPAIRS", "STORES"}


def _get_or_404(pid):
    ent = domain.get("purchase_orders", pid)
    if ent is None:
        not_found("purchase order")
    return ent


def _require_owner(user_id, po):
    if user_id != po["vendor_id"]:
        raise_err("ERR_NOT_RESOURCE_OWNER", "The caller does not own this purchase order")


def _mirror(po):
    da = domain.current_da_for_call(po["port_call_id"])
    if da is None:
        return None, None
    return da, domain.mirror_line(da["id"], "PurchaseOrder:%s" % po["id"])


@bp.post("/purchase-orders")
def create_purchase_order():
    require_roles(["AgencyOps"])
    body = request.get_json(silent=True) or {}
    call = None
    pcid = body.get("port_call_id")
    if isinstance(pcid, str):
        call = domain.get("port_calls", pcid)
        if call is None:
            not_found("port call")
    vendor = None
    vid = body.get("vendor_id")
    if isinstance(vid, str):
        vendor = domain.get("vendors", vid)
        if vendor is None:
            not_found("vendor")
    if call is not None:
        domain.require_call_editable(call)
    category = body.get("category")
    if vendor is not None and vendor["status"] != "ACTIVE":
        raise_err("ERR_VENDOR_SUSPENDED", "The vendor is not ACTIVE")
    if vendor is not None and isinstance(category, str) and category not in vendor["categories"]:
        raise_err("ERR_VENDOR_CATEGORY_MISMATCH", "The category is not in the vendor's categories")
    needed_by = parse_dt(body.get("needed_by"))
    if (call is None or vendor is None
            or category not in CATEGORIES
            or not is_int(body.get("estimated_cents")) or body.get("estimated_cents", 0) <= 0
            or needed_by is None):
        invalid_request("invalid purchase order payload")
    ent = new_entity("purchase_orders", {
        "port_call_id": pcid,
        "vendor_id": vid,
        "category": category,
        "estimated_cents": body["estimated_cents"],
        "needed_by": needed_by,
        "status": "DRAFT",
        "invoiced_cents": None,
        "variance_pct": None,
        "da_line_id": None,
    })
    da = domain.current_da_for_call(pcid)
    if da is not None and da["status"] in DA_EDITABLE_STATUSES:
        line = new_entity("da_lines", {
            "da_id": da["id"],
            "category": category,
            "description": "Purchase order %s" % ent["id"],
            "estimated_cents": ent["estimated_cents"],
            "actual_cents": None,
            "status": "ESTIMATED",
            "source_type": "PURCHASE_ORDER",
            "source_ref": "PurchaseOrder:%s" % ent["id"],
            "tariff_id": None,
        })
        ent["da_line_id"] = line["id"]
        touch(ent)
        domain.recompute_da_totals(da)
    return ok_object(serialize(ent), status=201)


@bp.get("/purchase-orders")
def list_purchase_orders():
    require_roles(ANY_ROLE)
    items = list(domain.all_of("purchase_orders"))
    for param in ("port_call_id", "vendor_id", "da_line_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [p for p in items if p[param] == value]
    items = sort_created(items)
    limit, offset = pagination_args(request.args)
    page, total, has_more = paginate(items, limit, offset)
    return ok_list(serialize_many(page), total, limit, offset, has_more)


@bp.get("/purchase-orders/<pid>")
def get_purchase_order(pid):
    require_roles(ANY_ROLE)
    return ok_object(serialize(_get_or_404(pid)))


@bp.post("/purchase-orders/<pid>/send")
def send_purchase_order(pid):
    require_roles(["AgencyOps"])
    ent = _get_or_404(pid)
    if ent["status"] != "DRAFT":
        invalid_state("Only a DRAFT purchase order can be sent")
    vendor = domain.get("vendors", ent["vendor_id"])
    if vendor is not None and vendor["status"] != "ACTIVE":
        raise_err("ERR_VENDOR_SUSPENDED", "The vendor is not ACTIVE")
    ent["status"] = "SENT"
    touch(ent)
    return ok_object(serialize(ent))


@bp.post("/purchase-orders/<pid>/acknowledge")
def acknowledge_purchase_order(pid):
    user_id, _ = require_roles(["VendorRep"])
    ent = _get_or_404(pid)
    _require_owner(user_id, ent)
    if ent["status"] != "SENT":
        invalid_state("Only a SENT purchase order can be acknowledged")
    vendor = domain.get("vendors", ent["vendor_id"])
    if vendor is not None and vendor["status"] != "ACTIVE":
        raise_err("ERR_VENDOR_SUSPENDED", "The vendor is not ACTIVE")
    ent["status"] = "ACKNOWLEDGED"
    touch(ent)
    return ok_object(serialize(ent))


@bp.post("/purchase-orders/<pid>/deliver")
def deliver_purchase_order(pid):
    user_id, _ = require_roles(["VendorRep"])
    ent = _get_or_404(pid)
    _require_owner(user_id, ent)
    if ent["status"] != "ACKNOWLEDGED":
        invalid_state("Only an ACKNOWLEDGED purchase order can be delivered")
    ent["status"] = "DELIVERED"
    touch(ent)
    return ok_object(serialize(ent))


def _record_invoice(ent, invoiced_cents):
    ent["invoiced_cents"] = invoiced_cents
    ent["variance_pct"] = domain.po_variance_pct(ent["estimated_cents"], invoiced_cents)


@bp.post("/purchase-orders/<pid>/invoice")
def invoice_purchase_order(pid):
    user_id, _ = require_roles(["VendorRep"])
    ent = _get_or_404(pid)
    _require_owner(user_id, ent)
    if ent["status"] != "DELIVERED":
        invalid_state("Only a DELIVERED purchase order can be invoiced")
    body = request.get_json(silent=True) or {}
    invoiced = body.get("invoiced_cents")
    if not is_int(invoiced) or invoiced < 0:
        invalid_request("invoiced_cents must be a non-negative integer")
    _record_invoice(ent, invoiced)
    da, line = _mirror(ent)
    if domain.within_tolerance(ent["variance_pct"]):
        ent["status"] = "INVOICED"
        touch(ent)
        if da is not None and line is not None:
            line["actual_cents"] = invoiced
            line["status"] = "ACTUALIZED"
            touch(line)
            domain.recompute_da_totals(da)
    else:
        # Variance fork: PO -> DISPUTED, mirror -> DISPUTED, DA FINAL -> DISPUTED
        ent["status"] = "DISPUTED"
        touch(ent)
        if da is not None and line is not None:
            line["actual_cents"] = invoiced
            line["status"] = "DISPUTED"
            touch(line)
            if da["status"] == "FINAL":
                da["status"] = "DISPUTED"
            domain.recompute_da_totals(da)
    return ok_object(serialize(ent))


@bp.post("/purchase-orders/<pid>/reinvoice")
def reinvoice_purchase_order(pid):
    user_id, _ = require_roles(["VendorRep"])
    ent = _get_or_404(pid)
    _require_owner(user_id, ent)
    if ent["status"] != "DISPUTED":
        invalid_state("Only a DISPUTED purchase order can be reinvoiced")
    body = request.get_json(silent=True) or {}
    invoiced = body.get("invoiced_cents")
    if not is_int(invoiced) or invoiced < 0:
        invalid_request("invoiced_cents must be a non-negative integer")
    _record_invoice(ent, invoiced)
    ent["status"] = "INVOICED"
    touch(ent)
    da, line = _mirror(ent)
    if da is not None and line is not None:
        line["actual_cents"] = invoiced
        line["status"] = "ACTUALIZED"
        touch(line)
        domain.recompute_da_totals(da)
    return ok_object(serialize(ent))


@bp.post("/purchase-orders/<pid>/match")
def match_purchase_order(pid):
    require_roles(["AgencyFinance"])
    ent = _get_or_404(pid)
    if ent["status"] != "INVOICED":
        invalid_state("Only an INVOICED purchase order can be matched")
    if domain.within_tolerance(ent["variance_pct"]):
        ent["status"] = "MATCHED"
        touch(ent)
    else:
        ent["status"] = "DISPUTED"
        touch(ent)
        da, line = _mirror(ent)
        if da is not None and line is not None:
            line["status"] = "DISPUTED"
            touch(line)
            if da["status"] == "FINAL":
                da["status"] = "DISPUTED"
            domain.recompute_da_totals(da)
    return ok_object(serialize(ent))


def _cancel_purchase_order(ent):
    if ent["status"] not in ("DRAFT", "SENT", "ACKNOWLEDGED"):
        invalid_state("Only a DRAFT, SENT or ACKNOWLEDGED purchase order can be cancelled")
    ent["status"] = "CANCELLED"
    touch(ent)
    da, line = _mirror(ent)
    if da is not None and line is not None:
        if line["estimated_cents"] != 0:
            line["estimated_cents"] = 0
            touch(line)
        domain.recompute_da_totals(da)


@bp.post("/purchase-orders/<pid>/cancel")
def cancel_purchase_order(pid):
    require_roles(["AgencyOps"])
    ent = _get_or_404(pid)
    _cancel_purchase_order(ent)
    return ok_object(serialize(ent))
