"""Sponsorship packaging, deals, obligations and fulfillment credit (PRD 3.7)."""
from flask import Blueprint, request

import calc
import guards
import services
import validate
import views
from db import base_row, by_created, db, touch
from errors import ApiError
from middleware import (EXHIBITOR, FLOOR_MANAGER, SALES_REP, SHOW_DIRECTOR, authenticate)
from response import created, list_response, object_response, pagination
from validate import CODE_RE

bp = Blueprint("sponsorship", __name__)

PACKAGE_SHOW_STATUSES = ("PLANNING", "SPACE_SELECTION", "SELLING")


@bp.route("/shows/<show_id>/sponsorship-packages", methods=["POST"])
def create_package(show_id):
    body = validate.body()
    package_code = validate.text(body, "package_code", 1, 32, pattern=CODE_RE)
    list_price_cents = validate.integer(body, "list_price_cents", minimum=1)
    price_floor_cents = validate.integer(body, "price_floor_cents", minimum=1)
    inventory_total = validate.integer(body, "inventory_total", minimum=1)
    exclusivity_category = validate.text(body, "exclusivity_category", 1, 32,
                                         required=False, default="NONE",
                                         pattern=CODE_RE)
    obligation_codes = validate.code_list(body, "obligation_codes")
    priority_point_value = validate.integer(body, "priority_point_value", minimum=0)
    if price_floor_cents > list_price_cents:
        validate.bad("price_floor_cents may not exceed list_price_cents")

    authenticate((SHOW_DIRECTOR,))
    show = guards.get_show(show_id)
    guards.require_show_status(show, PACKAGE_SHOW_STATUSES)

    for other in calc.show_packages(show["id"]):
        if other["package_code"] == package_code:
            validate.bad("package_code must be unique among the packages of this show")

    row = base_row()
    row.update({
        "show_id": show["id"],
        "package_code": package_code,
        "list_price_cents": list_price_cents,
        "price_floor_cents": price_floor_cents,
        "inventory_total": inventory_total,
        "exclusivity_category": exclusivity_category,
        "obligation_codes": obligation_codes,
        "priority_point_value": priority_point_value,
    })
    db.sponsorship_packages[row["id"]] = row
    return created(views.package_view(row))


@bp.route("/shows/<show_id>/sponsorship-packages", methods=["GET"])
def list_packages(show_id):
    limit, offset = pagination()
    authenticate((SHOW_DIRECTOR, SALES_REP, EXHIBITOR))
    show = guards.get_show(show_id)
    rows = by_created(calc.show_packages(show["id"]))
    wanted = request.args.get("exclusivity_category")
    if wanted:
        rows = [r for r in rows if r["exclusivity_category"] == wanted]
    return list_response([views.package_view(r) for r in rows], limit, offset)


@bp.route("/sponsorship-packages/<package_id>/deals", methods=["POST"])
def propose_deal(package_id):
    body = validate.body()
    exhibitor_id = validate.text(body, "exhibitor_id", 1, 64)
    negotiated_price_cents = validate.integer(body, "negotiated_price_cents", minimum=1)

    ctx = authenticate((SALES_REP, SHOW_DIRECTOR))
    exhibitor = guards.get_exhibitor(exhibitor_id)
    package = guards.get_package(package_id)
    guards.require_exhibitor_active(exhibitor)

    if calc.inventory_available(package) < 1:
        raise ApiError("ERR_SPONSORSHIP_INVENTORY_EXHAUSTED",
                       "every unit of this package is already committed")

    category = package["exclusivity_category"]
    if category and category != "NONE":
        for sibling in calc.show_packages(package["show_id"]):
            if sibling["id"] == package["id"]:
                continue
            if sibling["exclusivity_category"] != category:
                continue
            for deal in calc.package_deals(sibling["id"]):
                if (deal["deal_status"] in ("PROPOSED", "SIGNED")
                        and deal["exhibitor_id"] != exhibitor["id"]):
                    raise ApiError("ERR_EXCLUSIVITY_CATEGORY_TAKEN",
                                   "another sponsor already holds this exclusivity category")

    floor = max(package["price_floor_cents"],
                calc.sponsor_discount_floor(package["list_price_cents"]))
    if negotiated_price_cents < floor:
        raise ApiError("ERR_SPONSORSHIP_PRICE_BELOW_FLOOR",
                       "the negotiated price is below the binding floor")

    row = base_row()
    row.update({
        "sponsorship_package_id": package["id"],
        "exhibitor_id": exhibitor["id"],
        "negotiated_price_cents": negotiated_price_cents,
        "deal_status": "PROPOSED",
        "fulfillment_credited": False,
        "proposed_by_user_id": ctx.user_id,
        "signed_by_user_id": None,
        "cancellation_reason": None,
    })
    db.sponsorship_deals[row["id"]] = row
    return created(views.deal_view(row))


@bp.route("/sponsorship-deals/<deal_id>", methods=["GET"])
def read_deal(deal_id):
    authenticate((SHOW_DIRECTOR, SALES_REP, FLOOR_MANAGER, EXHIBITOR))
    deal = guards.get_deal(deal_id)
    return object_response(views.deal_view(deal))


@bp.route("/sponsorship-deals", methods=["GET"])
def list_deals():
    limit, offset = pagination()
    authenticate((SHOW_DIRECTOR, SALES_REP, FLOOR_MANAGER, EXHIBITOR))
    rows = by_created(list(db.sponsorship_deals.values()))
    for field in ("sponsorship_package_id", "exhibitor_id", "deal_status"):
        wanted = request.args.get(field)
        if wanted:
            rows = [r for r in rows if r[field] == wanted]
    fulfillment = request.args.get("fulfillment_status")
    if fulfillment:
        rows = [r for r in rows
                if calc.derived_fulfillment_status(r) == fulfillment]
    return list_response([views.deal_view(r) for r in rows], limit, offset)


@bp.route("/sponsorship-deals/<deal_id>/sign", methods=["POST"])
def sign_deal(deal_id):
    validate.body()
    ctx = authenticate((SHOW_DIRECTOR,))
    known = db.sponsorship_deals.get(deal_id)
    if (known is not None and known["proposed_by_user_id"] is not None
            and known["proposed_by_user_id"] == ctx.user_id):
        raise ApiError("ERR_SOD_SPONSORSHIP_SIGN",
                       "the operator who proposed this deal may not sign it")
    deal = guards.get_deal(deal_id)
    package = guards.get_package(deal["sponsorship_package_id"])
    show = guards.get_show(package["show_id"])

    guards.require_show_status(show, PACKAGE_SHOW_STATUSES)
    guards.require_deal_status(deal, ("PROPOSED",))
    exhibitor = guards.get_exhibitor(deal["exhibitor_id"])
    guards.require_exhibitor_active(exhibitor)
    if calc.inventory_available(package) + 1 < 1:
        raise ApiError("ERR_SPONSORSHIP_INVENTORY_EXHAUSTED",
                       "every unit of this package is already committed")

    deal["deal_status"] = "SIGNED"
    deal["signed_by_user_id"] = ctx.user_id
    services.materialise_obligations(deal, package, show)
    touch(deal)
    touch(exhibitor)
    services.reprice_exhibitor_contracts(exhibitor["id"], show["id"])
    return object_response(views.deal_view(deal))


@bp.route("/sponsorship-deals/<deal_id>/cancel", methods=["POST"])
def cancel_deal(deal_id):
    body = validate.body()
    cancellation_reason = validate.text(body, "cancellation_reason", 1, 500)

    ctx = authenticate((SHOW_DIRECTOR, EXHIBITOR))
    known = db.sponsorship_deals.get(deal_id)
    if known is not None:
        ctx.enforce_scope(known["exhibitor_id"])
    deal = guards.get_deal(deal_id)
    package = guards.get_package(deal["sponsorship_package_id"])
    show = guards.get_show(package["show_id"])

    if deal["deal_status"] == "SIGNED" and show["status"] == "CLOSED":
        raise ApiError("ERR_INVALID_SHOW_STATUS",
                       "a signed deal may not be cancelled once the show is CLOSED")
    guards.require_deal_status(deal, ("PROPOSED", "SIGNED"))

    services.cancel_sponsorship_deal(deal, cancellation_reason)
    return object_response(views.deal_view(deal))


@bp.route("/sponsorship-deals/<deal_id>/obligations", methods=["GET"])
def list_obligations(deal_id):
    limit, offset = pagination()
    authenticate((SHOW_DIRECTOR, SALES_REP, FLOOR_MANAGER, EXHIBITOR))
    deal = guards.get_deal(deal_id)
    rows = by_created(calc.deal_obligations(deal["id"]))
    wanted = request.args.get("status")
    if wanted:
        rows = [r for r in rows if r["status"] == wanted]
    return list_response([views.obligation_view(r) for r in rows], limit, offset)


@bp.route("/sponsorship-deals/<deal_id>/obligations/<obligation_id>/resolve",
          methods=["POST"])
def resolve_obligation(deal_id, obligation_id):
    body = validate.body()
    disposition = validate.enum(body, "disposition", ("DELIVERED", "WAIVED"))
    # PRD 3.7 pins the empty-note case to ERR_WAIVER_REASON_REQUIRED, so an empty
    # note must not be intercepted as a structural failure.
    note = validate.text(body, "note", 0, 500, required=False)

    ctx = authenticate((FLOOR_MANAGER, SHOW_DIRECTOR))
    if disposition == "WAIVED":
        ctx.require_role((SHOW_DIRECTOR,))
    deal = guards.get_deal(deal_id)
    obligation = guards.get_obligation(deal, obligation_id)

    guards.require_deal_status(deal, ("SIGNED",))
    guards.require_obligation_pending(obligation)
    if disposition == "WAIVED" and not note:
        raise ApiError("ERR_WAIVER_REASON_REQUIRED",
                       "a WAIVED obligation requires a note")

    obligation["status"] = disposition
    obligation["resolved_by_user_id"] = ctx.user_id
    obligation["note"] = note
    touch(obligation)
    touch(deal)
    services.credit_fulfillment_if_complete(deal)
    return object_response(views.obligation_view(obligation))
