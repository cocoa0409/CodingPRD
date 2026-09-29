"""Space contracts: offering, negotiating, signing, money and rebooking."""
from flask import Blueprint, request

import calc
import guards
import services
import validate
import views
from db import by_created, db, fmt_dt, now, touch
from errors import ApiError
from middleware import (EXHIBITOR, FLOOR_MANAGER, SALES_REP, SHOW_DIRECTOR, authenticate)
from response import created, list_response, object_response, pagination

bp = Blueprint("contracts", __name__)

SELLING_STATUSES = ("SPACE_SELECTION", "SELLING")


@bp.route("/space-contracts", methods=["POST"])
def open_contract():
    body = validate.body()
    show_id = validate.text(body, "show_id", 1, 64)
    exhibitor_id = validate.text(body, "exhibitor_id", 1, 64)
    expected_show_version = validate.integer(body, "expected_show_version", minimum=0)
    requested_sqft = validate.integer(body, "requested_sqft", minimum=1)
    premium = validate.boolean(body, "premium_placement_requested", default=False)
    booth_ids = validate.id_list(body, "booth_ids", required=False)

    authenticate((SALES_REP, SHOW_DIRECTOR, EXHIBITOR))
    show = guards.get_show(show_id)
    exhibitor = guards.get_exhibitor(exhibitor_id)
    booths = guards.get_booths(booth_ids) if booth_ids else []

    guards.require_show_status(show, SELLING_STATUSES)
    guards.reject_merged_booths(booths)
    guards.check_show_version(show, expected_show_version)
    guards.require_exhibitor_active(exhibitor)
    guards.reject_frozen_floor(show)
    guards.require_booths_in_show(booths, show["id"])
    guards.require_booths_available(booths)
    if not booths:
        chosen = calc.select_booth(show["id"], requested_sqft, premium)
        if chosen is None:
            raise ApiError("ERR_NO_ELIGIBLE_BOOTH",
                           "no booth on this floor satisfies the request")
        booths = [chosen]
    guards.reject_duplicate_active_contract(show["id"], exhibitor["id"])

    contract = services.open_space_contract(show, exhibitor, requested_sqft,
                                            premium, booths)
    touch(show)
    return created(views.space_contract_view(contract))


@bp.route("/space-contracts/<contract_id>", methods=["GET"])
def read_contract(contract_id):
    authenticate((SHOW_DIRECTOR, SALES_REP, FLOOR_MANAGER, EXHIBITOR))
    contract = guards.get_contract(contract_id)
    return object_response(views.space_contract_view(contract))


@bp.route("/space-contracts", methods=["GET"])
def list_contracts():
    limit, offset = pagination()
    authenticate((SHOW_DIRECTOR, SALES_REP, FLOOR_MANAGER, EXHIBITOR))
    rows = by_created(list(db.space_contracts.values()))
    for field in ("show_id", "exhibitor_id", "rebooked_from_space_contract_id", "status"):
        wanted = request.args.get(field)
        if wanted:
            rows = [r for r in rows if r[field] == wanted]
    return list_response([views.space_contract_view(r) for r in rows], limit, offset)


@bp.route("/space-contracts/<contract_id>/negotiate", methods=["POST"])
def negotiate(contract_id):
    body = validate.body()
    action = validate.enum(body, "action", ("COUNTER", "REOFFER"))
    requested_discount_pct = validate.integer(
        body, "requested_discount_pct", minimum=0,
        maximum=calc.MAX_APPROVED_DISCOUNT_PCT, required=False, default=0)
    approved_discount_pct = validate.integer(
        body, "approved_discount_pct", minimum=0, maximum=100,
        required=False, default=0)
    booth_ids = validate.id_list(body, "booth_ids", required=False)

    ctx = authenticate((EXHIBITOR, SALES_REP, SHOW_DIRECTOR))
    if action == "COUNTER":
        ctx.require_role((EXHIBITOR,))
    else:
        ctx.require_role((SALES_REP, SHOW_DIRECTOR))

    known = db.space_contracts.get(contract_id)
    if known is not None:
        ctx.enforce_scope(known["exhibitor_id"])
        if (action == "REOFFER"
                and approved_discount_pct > calc.DISCOUNT_APPROVAL_THRESHOLD_PCT
                and known["last_offer_by_user_id"] is not None
                and known["last_offer_by_user_id"] == ctx.user_id):
            raise ApiError("ERR_SOD_DISCOUNT_APPROVAL",
                           "the operator who made the previous offer may not approve "
                           "this discount")
    booths = guards.get_booths(booth_ids) if booth_ids else []
    contract = guards.get_contract(contract_id)
    show = guards.get_show(contract["show_id"])

    guards.require_show_status(show, SELLING_STATUSES)
    guards.require_contract_status(
        contract, ("OFFERED",) if action == "COUNTER" else ("COUNTERED",))
    guards.reject_merged_booths(booths)
    if (action == "REOFFER"
            and approved_discount_pct > calc.DISCOUNT_APPROVAL_THRESHOLD_PCT):
        guards.require_open_floor(show)
    guards.require_booths_in_show(booths, show["id"])
    guards.require_booths_available(booths, contract_id=contract["id"])

    if action == "COUNTER":
        if contract["negotiation_round"] >= calc.MAX_NEGOTIATION_ROUNDS:
            raise ApiError("ERR_NEGOTIATION_ROUNDS_EXHAUSTED",
                           "the negotiation round budget is exhausted")
    else:
        if (approved_discount_pct > calc.DISCOUNT_APPROVAL_THRESHOLD_PCT
                and ctx.role != SHOW_DIRECTOR):
            raise ApiError("ERR_DISCOUNT_APPROVAL_REQUIRED",
                           "a discount above the sales threshold needs a ShowDirector")
        if approved_discount_pct > calc.MAX_APPROVED_DISCOUNT_PCT:
            raise ApiError("ERR_DISCOUNT_EXCEEDS_CAP",
                           "no role may approve more than %s percent"
                           % calc.MAX_APPROVED_DISCOUNT_PCT)

    booths_changed = False
    if booths:
        new_ids = [b["id"] for b in booths]
        if new_ids != list(contract["offered_booth_ids"]):
            booths_changed = True
            for booth in services.contract_held_or_assigned_booths(contract):
                if booth["id"] not in new_ids and booth["status"] == "HELD":
                    services.release_booth(booth)
            contract["offered_booth_ids"] = new_ids
            services.hold_booths(contract, [b for b in booths if b["status"] != "HELD"
                                            or b["space_contract_id"] != contract["id"]])

    if action == "COUNTER":
        contract["requested_discount_pct"] = requested_discount_pct
        contract["negotiation_round"] += 1
        contract["status"] = "COUNTERED"
        if booths_changed:
            calc.price_space_fee(contract)
        touch(contract)
        if booths_changed:
            touch(show)
    else:
        contract["approved_discount_pct"] = approved_discount_pct
        contract["last_offer_by_user_id"] = ctx.user_id
        contract["status"] = "OFFERED"
        calc.price_space_fee(contract)
        touch(contract)
        touch(show)
    return object_response(views.space_contract_view(contract))


@bp.route("/space-contracts/<contract_id>/sign", methods=["POST"])
def sign_contract(contract_id):
    body = validate.body()
    expected_show_version = validate.integer(body, "expected_show_version", minimum=0)
    deposit_paid_cents = validate.integer(body, "deposit_paid_cents", minimum=0)

    ctx = authenticate((EXHIBITOR,))
    known = db.space_contracts.get(contract_id)
    if known is not None:
        ctx.enforce_scope(known["exhibitor_id"])
    contract = guards.get_contract(contract_id)
    show = guards.get_show(contract["show_id"])

    guards.require_show_status(show, SELLING_STATUSES)
    guards.require_contract_status(contract, ("OFFERED",))
    guards.check_show_version(show, expected_show_version)
    exhibitor = guards.get_exhibitor(contract["exhibitor_id"])
    guards.require_exhibitor_active(exhibitor)

    booths = [db.booths[b] for b in contract["offered_booth_ids"] if b in db.booths]
    if not booths or len(booths) != len(contract["offered_booth_ids"]):
        raise ApiError("ERR_BOOTH_NOT_AVAILABLE", "the contract holds no booths to assign")
    for booth in booths:
        if booth["status"] != "HELD" or booth["space_contract_id"] != contract["id"]:
            raise ApiError("ERR_BOOTH_NOT_AVAILABLE",
                           "booth %s is no longer held by this contract" % booth["booth_number"])

    if deposit_paid_cents < contract["min_deposit_cents"]:
        raise ApiError("ERR_DEPOSIT_BELOW_MINIMUM",
                       "the tendered deposit is below min_deposit_cents")
    if deposit_paid_cents > contract["invoice_total_cents"]:
        raise ApiError("ERR_DEPOSIT_EXCEEDS_INVOICE",
                       "the tendered deposit exceeds invoice_total_cents")

    for booth in booths:
        booth["status"] = "ASSIGNED"
        touch(booth)
    contract["status"] = "SIGNED"
    contract["deposit_paid_cents"] = deposit_paid_cents
    contract["signed_at"] = fmt_dt(now())
    assigned = calc.contract_assigned_net_sqft(contract)
    contract["points_awarded"] = (assigned // calc.SQFT_PER_POINT_BLOCK) * calc.POINTS_PER_BLOCK
    touch(contract)
    touch(exhibitor)
    touch(show)
    return object_response(views.space_contract_view(contract))


@bp.route("/space-contracts/<contract_id>/deposits", methods=["POST"])
def post_deposit(contract_id):
    body = validate.body()
    amount_cents = validate.integer(body, "amount_cents", minimum=1)

    ctx = authenticate((EXHIBITOR, SALES_REP))
    known = db.space_contracts.get(contract_id)
    if known is not None:
        ctx.enforce_scope(known["exhibitor_id"])
    contract = guards.get_contract(contract_id)
    guards.require_contract_status(contract, ("SIGNED",))

    if contract["deposit_paid_cents"] + amount_cents > contract["invoice_total_cents"]:
        raise ApiError("ERR_DEPOSIT_EXCEEDS_INVOICE",
                       "the payment would push the deposit past the invoice total")
    contract["deposit_paid_cents"] += amount_cents
    touch(contract)
    return object_response(views.space_contract_view(contract))


@bp.route("/space-contracts/<contract_id>/cancel", methods=["POST"])
def cancel_contract(contract_id):
    body = validate.body()
    cancellation_reason = validate.text(body, "cancellation_reason", 1, 500)

    ctx = authenticate((EXHIBITOR, SHOW_DIRECTOR))
    known = db.space_contracts.get(contract_id)
    if known is not None:
        ctx.enforce_scope(known["exhibitor_id"])
    contract = guards.get_contract(contract_id)
    show = guards.get_show(contract["show_id"])

    guards.require_show_status(show, ("SPACE_SELECTION", "SELLING", "ON_SITE"))
    guards.require_contract_status(contract, calc.ACTIVE_CONTRACT_STATUSES)

    services.cancel_space_contract(contract, cancellation_reason)
    touch(show)
    return object_response(views.space_contract_view(contract))


@bp.route("/space-contracts/<contract_id>/rebook", methods=["POST"])
def rebook_contract(contract_id):
    body = validate.body()
    target_show_id = validate.text(body, "target_show_id", 1, 64)
    expected_target_show_version = validate.integer(
        body, "expected_target_show_version", minimum=0)
    requested_sqft = validate.integer(body, "requested_sqft", minimum=1)
    premium = validate.boolean(body, "premium_placement_requested", default=False)
    booth_ids = validate.id_list(body, "booth_ids", required=False)

    ctx = authenticate((SALES_REP, SHOW_DIRECTOR, EXHIBITOR))
    known = db.space_contracts.get(contract_id)
    if known is not None:
        ctx.enforce_scope(known["exhibitor_id"])
    contract = guards.get_contract(contract_id)
    target = guards.get_show(target_show_id)
    booths = guards.get_booths(booth_ids) if booth_ids else []

    guards.require_show_status(target, SELLING_STATUSES)
    guards.require_contract_status(contract, ("CLOSED_OUT",))
    guards.reject_merged_booths(booths)
    guards.check_show_version(target, expected_target_show_version)
    exhibitor = guards.get_exhibitor(contract["exhibitor_id"])
    guards.require_exhibitor_active(exhibitor)
    guards.reject_frozen_floor(target)
    guards.require_booths_in_show(booths, target["id"])

    source_show = guards.get_show(contract["show_id"])
    if (target["id"] == source_show["id"]
            or target["venue_contract_id"] != source_show["venue_contract_id"]
            or target["edition_year"] <= source_show["edition_year"]):
        raise ApiError("ERR_REBOOK_TARGET_INVALID",
                       "the target edition is not a later edition of the same event")

    guards.require_booths_available(booths)
    if not booths:
        chosen = calc.select_booth(target["id"], requested_sqft, premium)
        if chosen is None:
            raise ApiError("ERR_NO_ELIGIBLE_BOOTH",
                           "no booth on the target floor satisfies the request")
        booths = [chosen]
    guards.reject_duplicate_active_contract(target["id"], exhibitor["id"])

    fresh = services.open_space_contract(target, exhibitor, requested_sqft, premium,
                                        booths, rebooked_from=contract["id"])
    exhibitor["consecutive_years"] += 1
    touch(exhibitor)
    touch(target)
    return created(views.space_contract_view(fresh))
