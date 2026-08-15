"""ProductionOrder endpoints (PRD §3.4) — plan/trim-grossing/holds, cutting,
finish with trim-reservation release."""

from flask import Blueprint, request

from db import store
from middleware import require_roles, ALL_ROLES, ROLE_PRODUCTION_PLANNER
from response import success_object
from util import get_body, req_str, validate_size_quantities, fk_exists
from errors import (
    invalid_request, invalid_state, content_claim_violation,
    tech_pack_not_approved, order_not_planned, no_approved_marker,
    trim_hold_active, order_not_finishable,
)
from services.core import (
    base_record, touch, public, get_production_order, get_style,
    pack_requirements, order_bundles,
)
from services.calc import (
    trim_grossing_lines, shortage_report, apply_reservations,
    release_reservations, wip_by_sku,
)
from routes.common import list_response, active_filters

bp = Blueprint("production_orders", __name__)


def _bom_all_us(pack_id):
    return all(
        store.trim_items[r["trim_item_id"]]["origin_country"] == "US"
        for r in pack_requirements(pack_id)
    )


@bp.route("/production-orders", methods=["POST"])
def create_production_order():
    require_roles([ROLE_PRODUCTION_PLANNER])
    body = get_body()
    fk_exists(body, "style_id", store.styles, "Style")
    style_id = req_str(body, "style_id")
    color = req_str(body, "color")
    size_quantities = validate_size_quantities(body)
    style = get_style(style_id)
    for line in size_quantities:
        if line["size"] not in style["size_run"]:
            raise invalid_request(
                f"size {line['size']!r} is not a member of the style's size_run")

    rec = base_record()
    rec.update({
        "style_id": style_id,
        "color": color,
        "size_quantities": size_quantities,
        "tech_pack_id": None,
        "total_order_qty": sum(l["qty"] for l in size_quantities),
        "production_status": "PLANNED",
        "trim_hold_status": "MATERIALS_OK",
        "quality_status": "QC_PENDING",
        "made_in_usa_eligible": None,
        "trim_shortages": [],
        "_order_seq": store.next_order_seq(),
        "_reserved": [],
    })
    store.production_orders[rec["id"]] = rec
    # Auto-activate the style on its first order (PRD §3.1).
    if style["status"] == "DRAFT":
        style["status"] = "ACTIVE"
        touch(style)
    return success_object(public(rec), status=201)


@bp.route("/production-orders", methods=["GET"])
def list_production_orders():
    require_roles(ALL_ROLES)
    filters = active_filters([
        ("style_id", request.args.get("style_id")),
        ("tech_pack_id", request.args.get("tech_pack_id")),
    ])
    return list_response(store.production_orders.values(), filters)


@bp.route("/production-orders/<order_id>", methods=["GET"])
def get_production_order_endpoint(order_id):
    require_roles(ALL_ROLES)
    return success_object(public(get_production_order(order_id)))


@bp.route("/production-orders/<order_id>/wip", methods=["GET"])
def get_order_wip(order_id):
    require_roles(ALL_ROLES)
    order = get_production_order(order_id)
    return success_object(wip_by_sku(order))


@bp.route("/production-orders/<order_id>/plan", methods=["POST"])
def plan_order(order_id):
    require_roles([ROLE_PRODUCTION_PLANNER])
    order = get_production_order(order_id)
    body = get_body()
    fk_exists(body, "tech_pack_id", store.tech_packs, "TechPack")
    tech_pack_id = req_str(body, "tech_pack_id")
    pack = store.tech_packs[tech_pack_id]
    style = get_style(order["style_id"])
    if order["tech_pack_id"] is not None:
        raise invalid_state(
            "order already has a pinned tech pack; the pin is immutable")

    # Content-claim safety gate (pipeline step 7) — evaluated BEFORE the
    # candidate pack's approval check (PRD §2.6, §3.4).
    if style["target_content_claim"] == "MADE_IN_USA":
        if not style["declared_fabric_domestic"] or not _bom_all_us(pack["id"]):
            raise content_claim_violation(
                "planning under a MADE_IN_USA target requires domestic shell "
                "fabric and an all-US trim bill of materials")

    # Candidate pack must belong to the order's style and be APPROVED (step 8).
    if pack["style_id"] != style["id"] or pack["status"] != "APPROVED":
        raise tech_pack_not_approved(
            "candidate tech pack must belong to the order's style and be "
            "APPROVED")

    order["tech_pack_id"] = pack["id"]
    order["made_in_usa_eligible"] = bool(
        style["declared_fabric_domestic"]) and _bom_all_us(pack["id"])

    # Trim grossing: per-line ceiling first, then coverage (PRD §3.4).
    lines = trim_grossing_lines(order, pack)
    shortages = shortage_report(lines)
    if shortages:
        # All-or-nothing: no units reserved, order goes on hold.
        order["trim_hold_status"] = "TRIM_HOLD"
        order["trim_shortages"] = shortages
        order["_reserved"] = []
    else:
        apply_reservations(order, lines)
        order["trim_hold_status"] = "MATERIALS_OK"
        order["trim_shortages"] = []
    touch(order)
    return success_object(public(order))


@bp.route("/production-orders/<order_id>/start-cutting", methods=["POST"])
def start_cutting(order_id):
    require_roles([ROLE_PRODUCTION_PLANNER])
    get_body()
    order = get_production_order(order_id)
    if order["production_status"] != "PLANNED":
        raise invalid_state("production order must be PLANNED to start cutting")
    if order["tech_pack_id"] is None:
        raise order_not_planned("order has no pinned tech pack")
    has_approved_marker = any(
        m["production_order_id"] == order["id"] and m["status"] == "APPROVED"
        for m in store.markers.values())
    if not has_approved_marker:
        raise no_approved_marker(
            "start-cutting requires at least one APPROVED marker")
    # Marker-presence gate is evaluated before the trim-hold gate (PRD §3.4).
    if order["trim_hold_status"] != "MATERIALS_OK":
        raise trim_hold_active("order is on TRIM_HOLD")
    order["production_status"] = "CUTTING"
    touch(order)
    return success_object(public(order))


@bp.route("/production-orders/<order_id>/finish", methods=["POST"])
def finish_order(order_id):
    require_roles([ROLE_PRODUCTION_PLANNER])
    get_body()
    order = get_production_order(order_id)
    if order["production_status"] != "SEWING":
        raise invalid_state("production order must be SEWING to finish")
    bundles = order_bundles(order["id"])
    if (not all(b["status"] == "COMPLETED" for b in bundles)
            or order["quality_status"] != "QC_PASSED"):
        raise order_not_finishable(
            "finish requires every bundle COMPLETED and quality_status "
            "QC_PASSED")
    release_reservations(order)
    order["production_status"] = "FINISHED"
    touch(order)
    return success_object(public(order))
