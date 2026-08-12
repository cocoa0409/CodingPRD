"""ServiceOrder endpoints with buffered resource-unit scheduling."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import invalid_request, invalid_state, not_found, raise_err
from middleware import require_roles, ANY_ROLE
from response import ok_list, ok_object
from services import domain
from services.domain import DA_EDITABLE_STATUSES, SO_KIND_TO_LINE_CATEGORY
from services.serializers import serialize, serialize_many
from utils import (dec, is_int, new_entity, paginate, pagination_args, parse_dt,
                   rhu_cents, sort_created, touch)

bp = Blueprint("service_orders", __name__)

KINDS = {"PILOT", "TUG", "LINEBOAT", "LAUNCH"}
BUFFER = timedelta(minutes=45)


def _get_or_404(sid):
    ent = domain.get("service_orders", sid)
    if ent is None:
        not_found("service order")
    return ent


def _mirror_and_recompute(order):
    """Append the SERVICE_ORDER mirror line when the call's DA is editable."""
    da = domain.current_da_for_call(order["port_call_id"])
    if da is None or da["status"] not in DA_EDITABLE_STATUSES:
        return None
    line = new_entity("da_lines", {
        "da_id": da["id"],
        "category": SO_KIND_TO_LINE_CATEGORY[order["kind"]],
        "description": "%s service on %s" % (order["kind"], order["resource_unit"]),
        "estimated_cents": order["estimated_cents"],
        "actual_cents": None,
        "status": "ESTIMATED",
        "source_type": "SERVICE_ORDER",
        "source_ref": "ServiceOrder:%s" % order["id"],
        "tariff_id": None,
    })
    domain.recompute_da_totals(da)
    return line


@bp.post("/service-orders")
def create_service_order():
    require_roles(["AgencyOps"])
    body = request.get_json(silent=True) or {}
    # Stage 4: payload references
    call = None
    pcid = body.get("port_call_id")
    if isinstance(pcid, str):
        call = domain.get("port_calls", pcid)
        if call is None:
            not_found("port call")
    vendor = None
    vid = body.get("vendor_id")
    if vid is not None:
        if isinstance(vid, str):
            vendor = domain.get("vendors", vid)
            if vendor is None:
                not_found("vendor")
        else:
            invalid_request("vendor_id must be a string")
    window_start = parse_dt(body.get("window_start"))
    window_end = parse_dt(body.get("window_end"))
    # Stage 8: temporal window order
    if window_start is not None and window_end is not None and not window_start < window_end:
        raise_err("ERR_WINDOW_INVALID", "window_start must be strictly before window_end")
    # Stage 9: parent call editable
    if call is not None:
        domain.require_call_editable(call)
    # Stage 10: vendor status, then the kind-dependent vendor rule
    kind = body.get("kind")
    if vendor is not None and vendor["status"] != "ACTIVE":
        raise_err("ERR_VENDOR_SUSPENDED", "The referenced vendor is not ACTIVE")
    if kind in ("TUG", "LINEBOAT", "LAUNCH") and vid is None:
        raise_err("ERR_VENDOR_KIND_MISMATCH", "vendor_id is required for TUG/LINEBOAT/LAUNCH")
    if kind == "PILOT" and vid is not None:
        raise_err("ERR_VENDOR_KIND_MISMATCH", "vendor_id must be omitted for PILOT")
    # Stage 13: shape
    quantity = body.get("quantity", 1)
    if (call is None or kind not in KINDS
            or not isinstance(body.get("resource_unit"), str) or not body.get("resource_unit")
            or window_start is None or window_end is None
            or not is_int(body.get("estimated_cents")) or body.get("estimated_cents", -1) < 0
            or not is_int(quantity) or quantity < 1):
        invalid_request("invalid service order payload")
    ent = new_entity("service_orders", {
        "port_call_id": pcid,
        "kind": kind,
        "vendor_id": vid,
        "resource_unit": body["resource_unit"],
        "window_start": window_start,
        "window_end": window_end,
        "quantity": quantity,
        "estimated_cents": body["estimated_cents"],
        "actual_cents": None,
        "cancellation_fee_cents": 0,
        "status": "ORDERED",
    })
    _mirror_and_recompute(ent)
    return ok_object(serialize(ent), status=201)


@bp.get("/service-orders")
def list_service_orders():
    require_roles(ANY_ROLE)
    items = list(domain.all_of("service_orders"))
    for param in ("port_call_id", "vendor_id", "resource_unit", "kind", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [o for o in items if o[param] == value]
    items = sort_created(items)
    limit, offset = pagination_args(request.args)
    page, total, has_more = paginate(items, limit, offset)
    return ok_list(serialize_many(page), total, limit, offset, has_more)


@bp.get("/service-orders/<sid>")
def get_service_order(sid):
    require_roles(ANY_ROLE)
    return ok_object(serialize(_get_or_404(sid)))


@bp.post("/service-orders/<sid>/confirm")
def confirm_service_order(sid):
    user_id, role = require_roles(["PortAuthority", "VendorRep"])
    ent = _get_or_404(sid)
    if ent["status"] != "ORDERED":
        invalid_state("Only an ORDERED service order can be confirmed")
    # Buffer-inflated closed-interval overlap on the same resource_unit
    for other in domain.all_of("service_orders"):
        if (other["id"] == ent["id"] or other["resource_unit"] != ent["resource_unit"]
                or other["status"] not in ("CONFIRMED", "IN_PROGRESS")):
            continue
        if (other["window_start"] - BUFFER <= ent["window_end"] + BUFFER
                and ent["window_start"] - BUFFER <= other["window_end"] + BUFFER):
            raise_err("ERR_RESOURCE_UNIT_OVERLAP",
                      "The buffered window overlaps a committed order on the same resource_unit")
    # Kind-matched actor and vendor activity
    if ent["kind"] != "PILOT":
        vendor = domain.get("vendors", ent["vendor_id"])
        if vendor is not None and vendor["status"] != "ACTIVE":
            raise_err("ERR_VENDOR_SUSPENDED", "The owning vendor is not ACTIVE")
    if ent["kind"] == "PILOT":
        if role != "PortAuthority":
            raise_err("ERR_CONFIRM_ROLE_MISMATCH", "PILOT orders are confirmed by PortAuthority")
    else:
        if role != "VendorRep" or user_id != ent["vendor_id"]:
            raise_err("ERR_CONFIRM_ROLE_MISMATCH",
                      "Non-PILOT orders are confirmed by the owning VendorRep")
    ent["status"] = "CONFIRMED"
    touch(ent)
    return ok_object(serialize(ent))


@bp.post("/service-orders/<sid>/start")
def start_service_order(sid):
    require_roles(["AgencyOps"])
    ent = _get_or_404(sid)
    if ent["status"] != "CONFIRMED":
        invalid_state("Only a CONFIRMED service order can be started")
    if db.now() < ent["window_start"] - timedelta(minutes=60):
        raise_err("ERR_WINDOW_NOT_STARTED",
                  "Service may start no earlier than 60 minutes before window_start")
    ent["status"] = "IN_PROGRESS"
    touch(ent)
    return ok_object(serialize(ent))


@bp.post("/service-orders/<sid>/complete")
def complete_service_order(sid):
    require_roles(["AgencyOps"])
    ent = _get_or_404(sid)
    if ent["status"] != "IN_PROGRESS":
        invalid_state("Only an IN_PROGRESS service order can be completed")
    body = request.get_json(silent=True) or {}
    actual = body.get("actual_cents")
    if not is_int(actual) or actual < 0:
        invalid_request("actual_cents must be a non-negative integer")
    ent["actual_cents"] = actual
    ent["status"] = "COMPLETED"
    touch(ent)
    da = domain.current_da_for_call(ent["port_call_id"])
    if da is not None and da["status"] in DA_EDITABLE_STATUSES:
        line = domain.mirror_line(da["id"], "ServiceOrder:%s" % ent["id"])
        if line is not None:
            line["actual_cents"] = actual
            line["status"] = "ACTUALIZED"
            touch(line)
        domain.recompute_da_totals(da)
    return ok_object(serialize(ent))


def _cancel_service_order(ent, via_cascade):
    if ent["status"] not in ("ORDERED", "CONFIRMED"):
        invalid_state("Only an ORDERED or CONFIRMED service order can be cancelled")
    fee = 0
    if not via_cascade and db.now() > ent["window_start"] - timedelta(hours=2):
        fee = rhu_cents(dec(ent["estimated_cents"]) * domain.LATE_CANCEL_PCT)
    ent["cancellation_fee_cents"] = fee
    ent["status"] = "CANCELLED"
    touch(ent)
    da = domain.current_da_for_call(ent["port_call_id"])
    if da is not None:
        line = domain.mirror_line(da["id"], "ServiceOrder:%s" % ent["id"])
        if line is not None and line["estimated_cents"] != 0:
            line["estimated_cents"] = 0
            touch(line)
        if fee > 0 and da["status"] in DA_EDITABLE_STATUSES:
            new_entity("da_lines", {
                "da_id": da["id"],
                "category": "CANCELLATION_FEE",
                "description": "Late cancellation fee for ServiceOrder:%s" % ent["id"],
                "estimated_cents": 0,
                "actual_cents": fee,
                "status": "ACTUALIZED",
                "source_type": "MANUAL",
                "source_ref": None,
                "tariff_id": None,
            })
        domain.recompute_da_totals(da)


@bp.post("/service-orders/<sid>/cancel")
def cancel_service_order(sid):
    require_roles(["AgencyOps"])
    ent = _get_or_404(sid)
    _cancel_service_order(ent, via_cascade=False)
    return ok_object(serialize(ent))
