"""PurchaseOrder endpoints: intake, get/list, accept (fiscal cap), cancel, close."""
from flask import Blueprint, request

from db import new_record, public, store, touch
from errors import (
    ERR_AWARD_NOT_ACTIVE,
    ERR_DISTRICT_FISCAL_CAP_EXCEEDED,
    ERR_DUPLICATE_PO_NUMBER,
    ERR_INVALID_STATE,
    raise_err,
)
from middleware import ALL_ROLES, authenticate, require_roles, scope_district
from response import success
from services.cascade import (
    award_of_po,
    lines_of_po,
    recompute_po,
    recompute_spec_line,
    resolve_open_notice,
)
from services.pricing import install_closeout_total
from validation import (
    body,
    get_or_404,
    paginate,
    parse_pagination,
    req_int,
    req_str,
)

bp = Blueprint("purchase_orders", __name__)

CAP_COUNTED_STATUSES = ("ACCEPTED", "IN_FULFILLMENT", "FULFILLED", "CLOSED")


def _load_scoped_po(caller, rid):
    rec = store.purchase_orders.get(rid)
    if rec is not None:
        scope_district(caller, _district_of(rec))  # priority 3
    return get_or_404(store.purchase_orders, rid, "purchase order")  # priority 4


def _district_of(po):
    award = award_of_po(po)
    return award["district_id"] if award else None


@bp.route("/v1/purchase-orders", methods=["POST"])
def create_purchase_order():
    caller = authenticate()
    require_roles(caller, ["DistrictBuyer"])
    data = body()

    award_id = data.get("award_id")
    award = store.awards.get(award_id) if isinstance(award_id, str) else None
    if award is not None:
        scope_district(caller, award["district_id"])  # priority 3
    if isinstance(award_id, str):
        get_or_404(store.awards, award_id, "award")  # priority 4

    award_id = req_str(data, "award_id")
    po_number = req_str(data, "po_number")
    fiscal_year = req_int(data, "fiscal_year")

    # priority 7: PO creation requires an ACCEPTED award
    if award["status"] != "ACCEPTED":
        raise_err(ERR_AWARD_NOT_ACTIVE, "Purchase order creation requires an ACCEPTED award")

    # priority 14: po_number unique per (district, fiscal_year) among non-CANCELLED POs
    for other in store.purchase_orders.values():
        if other["status"] == "CANCELLED":
            continue
        if other["po_number"] != po_number or other["fiscal_year"] != fiscal_year:
            continue
        if _district_of(other) == award["district_id"]:
            raise_err(ERR_DUPLICATE_PO_NUMBER, "po_number already used by a non-CANCELLED PO of this district in this fiscal_year")

    rec = new_record({
        "award_id": award_id,
        "po_number": po_number,
        "fiscal_year": fiscal_year,
        "status": "RECEIVED",
        "posture": "ON_TRACK",
        "open_backorder_count": 0,
        "total_cents": 0,
        "closeout_total_cents": None,
    })
    store.purchase_orders[rec["id"]] = rec
    return success(public(rec), code=201)


@bp.route("/v1/purchase-orders/<rid>", methods=["GET"])
def get_purchase_order(rid):
    caller = authenticate()
    require_roles(caller, ALL_ROLES)
    rec = get_or_404(store.purchase_orders, rid, "purchase order")
    return success(public(rec), code=200)


@bp.route("/v1/purchase-orders", methods=["GET"])
def list_purchase_orders():
    caller = authenticate()
    require_roles(caller, ALL_ROLES)
    limit, offset = parse_pagination()
    records = list(store.purchase_orders.values())
    award_id = request.args.get("award_id")
    status = request.args.get("status")
    if award_id is not None:
        records = [r for r in records if r["award_id"] == award_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, pg = paginate(records, limit, offset)
    return success([public(r) for r in page], code=200, response_type="array", pagination=pg)


@bp.route("/v1/purchase-orders/<rid>/accept", methods=["POST"])
def accept_purchase_order(rid):
    caller = authenticate()
    require_roles(caller, ["FulfillmentCoordinator"])
    po = get_or_404(store.purchase_orders, rid, "purchase order")

    if po["status"] != "RECEIVED":
        raise_err(ERR_INVALID_STATE, f"Cannot accept a purchase order in status {po['status']}")

    # priority 15: district fiscal-year commitment cap
    award = award_of_po(po)
    district = store.districts.get(award["district_id"])
    committed = sum(
        other["total_cents"]
        for other in store.purchase_orders.values()
        if other["status"] in CAP_COUNTED_STATUSES
        and other["fiscal_year"] == po["fiscal_year"]
        and _district_of(other) == award["district_id"]
    )
    if committed + po["total_cents"] > district["annual_cap_cents"]:
        raise_err(ERR_DISTRICT_FISCAL_CAP_EXCEEDED, "Accepting this PO would exceed the district's fiscal-year cap")

    po["status"] = "ACCEPTED"
    touch(po)
    for line in lines_of_po(po["id"]):
        if line["status"] == "PENDING":
            line["status"] = "ORDERED"
            touch(line)
    return success(public(po), code=200)


@bp.route("/v1/purchase-orders/<rid>/cancel", methods=["POST"])
def cancel_purchase_order(rid):
    caller = authenticate()
    require_roles(caller, ["DistrictBuyer"])
    po = _load_scoped_po(caller, rid)
    body()  # optional cancel_reason is accepted and ignored

    if po["status"] == "RECEIVED":
        cancellable = ("PENDING",)
    elif po["status"] == "ACCEPTED":
        has_shipments = any(s["purchase_order_id"] == po["id"] for s in store.shipments.values())
        if has_shipments:
            raise_err(ERR_INVALID_STATE, "Cannot cancel an ACCEPTED purchase order with linked shipments")
        cancellable = ("ORDERED", "BACKORDERED")
    else:
        raise_err(ERR_INVALID_STATE, f"Cannot cancel a purchase order in status {po['status']}")

    for line in lines_of_po(po["id"]):
        if line["status"] in cancellable:
            was_backordered = line["status"] == "BACKORDERED"
            line["status"] = "CANCELLED"
            touch(line)
            sl = store.spec_lines.get(line["spec_line_id"])
            if sl is not None:
                recompute_spec_line(sl)  # compensating release of the drawdown
            if was_backordered:
                resolve_open_notice(line)

    po["status"] = "CANCELLED"
    touch(po)
    recompute_po(po)  # total_cents, open_backorder_count, posture
    return success(public(po), code=200)


@bp.route("/v1/purchase-orders/<rid>/close", methods=["POST"])
def close_purchase_order(rid):
    caller = authenticate()
    require_roles(caller, ["FulfillmentCoordinator"])
    po = get_or_404(store.purchase_orders, rid, "purchase order")

    if po["status"] != "FULFILLED":
        raise_err(ERR_INVALID_STATE, f"Cannot close a purchase order in status {po['status']}")

    po["closeout_total_cents"] = install_closeout_total(po)
    po["status"] = "CLOSED"
    touch(po)
    return success(public(po), code=200)
