"""Planting agreements, amendments, deliveries."""
from flask import Blueprint

from db import clock_date, new_record, store, touch
from errors import ApiError
from routes_core import DPA, FM, KM, get_or_404
from services import (WEEKDAYS, breach_agreement, delivered_quantity, in_window,
                      line_coverage, find_forecast_line, posture,
                      scheduled_held_quantity, ser_agreement, ser_amendment,
                      ser_delivery, week_of, window_inside, window_weeks)
from util import (body, ctx, list_response, ok_object, opt_int, req_date, req_enum,
                  req_int, req_str, require_role)

bp = Blueprint("agreements", __name__)


def _agreement_farm(ag):
    off = store["offerings"][ag["offering_id"]]
    return store["farms"][off["farm_id"]]


def _check_agreement_ownership(ag, uid):
    farm = _agreement_farm(ag)
    if farm["id"] != uid:
        raise ApiError("ERR_RESOURCE_OWNERSHIP",
                       "FarmManager may only act on its own farm's agreements", 403)


# ---------------------------------------------------------------------------
# PlantingAgreement
# ---------------------------------------------------------------------------

@bp.route("/f2s/planting-agreements", methods=["POST"])
def create_agreement():
    uid, role = ctx()
    b = body()
    year_id = req_str(b, "program_year_id")
    offering_id = req_str(b, "offering_id")
    committed = req_int(b, "committed_quantity", mn=1)
    hs = req_int(b, "harvest_start_week", mn=1, mx=52)
    he = req_int(b, "harvest_end_week", mn=1, mx=52)
    require_role(role, DPA)
    year = store["program_years"].get(year_id)
    if year is None:
        raise ApiError("ERR_PROGRAM_YEAR_NOT_FOUND", "ProgramYear %s not found" % year_id, 404)
    off = store["offerings"].get(offering_id)
    if off is None:
        raise ApiError("ERR_OFFERING_NOT_FOUND", "Offering %s not found" % offering_id, 404)
    if year["status"] != "OPEN":
        raise ApiError("ERR_PROGRAM_YEAR_NOT_OPEN",
                       "Agreement creation requires an OPEN program year", 409)
    if off["status"] != "VERIFIED":
        raise ApiError("ERR_OFFERING_NOT_VERIFIED",
                       "Agreement creation requires a VERIFIED offering", 409)
    if off["program_year_id"] != year_id:
        raise ApiError("ERR_OFFERING_YEAR_MISMATCH",
                       "Agreement program year differs from offering program year", 422)
    if not window_inside(hs, he, off["harvest_start_week"], off["harvest_end_week"]):
        raise ApiError("ERR_AGREEMENT_WINDOW_OUTSIDE_OFFERING",
                       "Agreement window is not contained in the offering harvest window", 409)
    # Fiscal guard: committed <= MIN uncovered over covered weeks with a forecast line
    mins = []
    for w in sorted(window_weeks(hs, he)):
        line = find_forecast_line(year_id, off["product_id"], w)
        if line is not None:
            _, uncovered = line_coverage(line)
            mins.append(uncovered)
    if mins and committed > min(mins):
        raise ApiError("ERR_COMMITMENT_EXCEEDS_UNCOVERED",
                       "committed_quantity exceeds the minimum uncovered forecast "
                       "quantity over the agreement's covered weeks", 402)
    rec = new_record()
    rec.update({
        "program_year_id": year_id,
        "offering_id": offering_id,
        "committed_quantity": committed,
        "harvest_start_week": hs,
        "harvest_end_week": he,
        "unit_price_cents": off["price_cents_per_unit"],
        "local_eligible": off["is_local_eligible"],
        "released_quantity": 0,
        "status": "PROPOSED",
    })
    store["agreements"][rec["id"]] = rec
    return ok_object(ser_agreement(rec), 201)


@bp.route("/f2s/planting-agreements", methods=["GET"])
def list_agreements():
    ctx()
    return list_response(store["agreements"].values(), ser_agreement, {
        "program_year_id": "program_year_id", "offering_id": "offering_id",
        "status": "status",
    })


@bp.route("/f2s/planting-agreements/<rid>", methods=["GET"])
def get_agreement(rid):
    ctx()
    rec = get_or_404("agreements", rid, "ERR_AGREEMENT_NOT_FOUND")
    return ok_object(ser_agreement(rec))


@bp.route("/f2s/planting-agreements/<rid>/sign", methods=["POST"])
def sign_agreement(rid):
    uid, role = ctx()
    require_role(role, FM)
    rec = get_or_404("agreements", rid, "ERR_AGREEMENT_NOT_FOUND")
    _check_agreement_ownership(rec, uid)
    if rec["status"] != "PROPOSED":
        raise ApiError("ERR_AGREEMENT_NOT_PROPOSED", "sign requires status PROPOSED", 409)
    off = store["offerings"][rec["offering_id"]]
    if off["status"] != "VERIFIED":
        raise ApiError("ERR_OFFERING_NOT_VERIFIED", "sign requires offering VERIFIED", 409)
    farm = _agreement_farm(rec)
    if farm["status"] != "APPROVED":
        raise ApiError("ERR_FARM_NOT_APPROVED", "sign requires farm APPROVED", 409)
    rec["status"] = "SIGNED"
    touch(rec)
    return ok_object(ser_agreement(rec))


@bp.route("/f2s/planting-agreements/<rid>/cancel", methods=["POST"])
def cancel_agreement(rid):
    uid, role = ctx()
    require_role(role, DPA, FM)
    rec = get_or_404("agreements", rid, "ERR_AGREEMENT_NOT_FOUND")
    if role == FM:
        _check_agreement_ownership(rec, uid)
    if rec["status"] not in ("PROPOSED", "SIGNED", "AMENDMENT_PROPOSED"):
        raise ApiError("ERR_AGREEMENT_NOT_CANCELLABLE",
                       "cancel requires status PROPOSED, SIGNED, or AMENDMENT_PROPOSED", 409)
    rec["released_quantity"] = rec["committed_quantity"] - delivered_quantity(rec["id"])
    rec["status"] = "CANCELLED"
    touch(rec)
    for am in store["amendments"].values():
        if am["agreement_id"] == rid and am["status"] == "PROPOSED":
            am["status"] = "REJECTED"
            touch(am)
    for dv in store["deliveries"].values():
        if dv["agreement_id"] == rid and dv["status"] == "SCHEDULED":
            dv["status"] = "CANCELLED"
            touch(dv)
    return ok_object(ser_agreement(rec))


# ---------------------------------------------------------------------------
# AgreementAmendment
# ---------------------------------------------------------------------------

@bp.route("/f2s/planting-agreements/<rid>/amendments", methods=["POST"])
def create_amendment(rid):
    uid, role = ctx()
    b = body()
    expected = req_int(b, "expected_agreement_version")
    new_q = opt_int(b, "new_committed_quantity", mn=1)
    new_p = opt_int(b, "new_unit_price_cents", mn=1)
    require_role(role, DPA, FM)
    ag = get_or_404("agreements", rid, "ERR_AGREEMENT_NOT_FOUND")
    if role == FM:
        _check_agreement_ownership(ag, uid)
    if ag["status"] not in ("SIGNED", "AMENDMENT_PROPOSED", "FULFILLING"):
        raise ApiError("ERR_AGREEMENT_NOT_AMENDABLE",
                       "amendments require agreement SIGNED, AMENDMENT_PROPOSED, or "
                       "FULFILLING", 409)
    if new_q is None and new_p is None:
        raise ApiError("ERR_AMENDMENT_EMPTY",
                       "Amendment carries neither new_committed_quantity nor "
                       "new_unit_price_cents", 400)
    if new_q is not None and new_q < delivered_quantity(rid):
        raise ApiError("ERR_AMENDMENT_BELOW_DELIVERED",
                       "new_committed_quantity is below the agreement's "
                       "delivered_quantity", 409)
    if expected != ag["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_agreement_version does not match the current agreement "
                       "version", 412)
    for am in store["amendments"].values():
        if am["agreement_id"] == rid and am["status"] == "PROPOSED":
            am["status"] = "SUPERSEDED"
            touch(am)
    rec = new_record()
    rec.update({
        "agreement_id": rid,
        "proposed_by_role": role,
        "new_committed_quantity": new_q,
        "new_unit_price_cents": new_p,
        "status": "PROPOSED",
    })
    store["amendments"][rec["id"]] = rec
    ag["status"] = "AMENDMENT_PROPOSED"
    touch(ag)
    return ok_object(ser_amendment(rec), 201)


@bp.route("/f2s/planting-agreements/<rid>/amendments", methods=["GET"])
def list_amendments(rid):
    ctx()
    get_or_404("agreements", rid, "ERR_AGREEMENT_NOT_FOUND")
    items = [a for a in store["amendments"].values() if a["agreement_id"] == rid]
    return list_response(items, ser_amendment, {})


@bp.route("/f2s/agreement-amendments/<rid>", methods=["GET"])
def get_amendment(rid):
    ctx()
    rec = get_or_404("amendments", rid, "ERR_AMENDMENT_NOT_FOUND")
    return ok_object(ser_amendment(rec))


def _counterparty_check(am, uid, role):
    if role == am["proposed_by_role"]:
        raise ApiError("ERR_NOT_COUNTERPARTY",
                       "Amendment may only be answered by the counterparty", 403)
    if role == FM:
        ag = store["agreements"][am["agreement_id"]]
        _check_agreement_ownership(ag, uid)


def _amendment_return_state(ag):
    has_deliveries = any(d["agreement_id"] == ag["id"] for d in store["deliveries"].values())
    return "FULFILLING" if has_deliveries else "SIGNED"


@bp.route("/f2s/agreement-amendments/<rid>/accept", methods=["POST"])
def accept_amendment(rid):
    uid, role = ctx()
    require_role(role, DPA, FM)
    am = get_or_404("amendments", rid, "ERR_AMENDMENT_NOT_FOUND")
    _counterparty_check(am, uid, role)
    if am["status"] != "PROPOSED":
        raise ApiError("ERR_AMENDMENT_NOT_OPEN", "accept requires amendment PROPOSED", 409)
    ag = store["agreements"][am["agreement_id"]]
    if ag["status"] != "AMENDMENT_PROPOSED":
        raise ApiError("ERR_AGREEMENT_NOT_AMENDABLE",
                       "accept requires agreement AMENDMENT_PROPOSED", 409)
    if am["new_committed_quantity"] is not None:
        ag["committed_quantity"] = am["new_committed_quantity"]
    if am["new_unit_price_cents"] is not None:
        ag["unit_price_cents"] = am["new_unit_price_cents"]
    ag["status"] = _amendment_return_state(ag)
    touch(ag)
    am["status"] = "ACCEPTED"
    touch(am)
    return ok_object(ser_amendment(am))


@bp.route("/f2s/agreement-amendments/<rid>/reject", methods=["POST"])
def reject_amendment(rid):
    uid, role = ctx()
    require_role(role, DPA, FM)
    am = get_or_404("amendments", rid, "ERR_AMENDMENT_NOT_FOUND")
    _counterparty_check(am, uid, role)
    if am["status"] != "PROPOSED":
        raise ApiError("ERR_AMENDMENT_NOT_OPEN", "reject requires amendment PROPOSED", 409)
    ag = store["agreements"][am["agreement_id"]]
    ag["status"] = _amendment_return_state(ag)
    touch(ag)
    am["status"] = "REJECTED"
    touch(am)
    return ok_object(ser_amendment(am))


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------

@bp.route("/f2s/deliveries", methods=["POST"])
def create_delivery():
    uid, role = ctx()
    b = body()
    agreement_id = req_str(b, "agreement_id")
    kitchen_id = req_str(b, "kitchen_id")
    window_id = req_str(b, "window_id")
    delivery_date = req_date(b, "delivery_date")
    quantity = req_int(b, "quantity", mn=1)
    require_role(role, FM)
    ag = store["agreements"].get(agreement_id)
    if ag is None:
        raise ApiError("ERR_AGREEMENT_NOT_FOUND", "Agreement %s not found" % agreement_id, 404)
    kitchen = store["kitchens"].get(kitchen_id)
    if kitchen is None:
        raise ApiError("ERR_KITCHEN_NOT_FOUND", "Kitchen %s not found" % kitchen_id, 404)
    window = store["windows"].get(window_id)
    if window is None:
        raise ApiError("ERR_WINDOW_NOT_FOUND", "Window %s not found" % window_id, 404)
    _check_agreement_ownership(ag, uid)
    if ag["status"] not in ("SIGNED", "FULFILLING"):
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE",
                       "Delivery scheduling requires agreement SIGNED or FULFILLING", 409)
    farm = _agreement_farm(ag)
    if posture(farm, clock_date()) != "COMPLIANT":
        raise ApiError("ERR_FARM_NOT_COMPLIANT",
                       "Farm compliance posture at the current date is NON_COMPLIANT", 422)
    if window["kitchen_id"] != kitchen_id:
        raise ApiError("ERR_WINDOW_KITCHEN_MISMATCH",
                       "window_id does not belong to kitchen_id", 422)
    if WEEKDAYS[delivery_date.weekday()] != window["weekday"]:
        raise ApiError("ERR_WINDOW_WEEKDAY_MISMATCH",
                       "window weekday differs from weekday(delivery_date)", 422)
    if delivery_date < clock_date():
        raise ApiError("ERR_DELIVERY_DATE_IN_PAST",
                       "delivery_date precedes the current logical clock date", 409)
    year = store["program_years"][ag["program_year_id"]]
    week = week_of(delivery_date, year["start_date"])
    in_year = (year["start_date"] <= delivery_date <= year["end_date"]) and 1 <= week <= 52
    if not in_year or not in_window(week, ag["harvest_start_week"], ag["harvest_end_week"]):
        raise ApiError("ERR_DELIVERY_OUTSIDE_HARVEST_WINDOW",
                       "delivery week is outside the agreement window or the program year",
                       409)
    active_count = sum(
        1 for d in store["deliveries"].values()
        if d["window_id"] == window_id and d["delivery_date"] == delivery_date
        and d["status"] in ("SCHEDULED", "CHECKED_IN"))
    if active_count >= window["capacity_deliveries"]:
        raise ApiError("ERR_WINDOW_CAPACITY_FULL",
                       "Window is already at capacity_deliveries for that date", 409)
    remaining = (ag["committed_quantity"] - delivered_quantity(agreement_id)
                 - scheduled_held_quantity(agreement_id))
    if quantity > remaining:
        raise ApiError("ERR_QUANTITY_EXCEEDS_REMAINING",
                       "quantity exceeds committed minus delivered minus scheduled", 409)
    rec = new_record()
    rec.update({
        "agreement_id": agreement_id,
        "kitchen_id": kitchen_id,
        "window_id": window_id,
        "delivery_date": delivery_date,
        "quantity": quantity,
        "week_number": week,
        "accepted_quantity": None,
        "rejection_reason": None,
        "status": "SCHEDULED",
    })
    store["deliveries"][rec["id"]] = rec
    if ag["status"] == "SIGNED":
        ag["status"] = "FULFILLING"
        touch(ag)
    return ok_object(ser_delivery(rec), 201)


@bp.route("/f2s/deliveries", methods=["GET"])
def list_deliveries():
    ctx()
    return list_response(store["deliveries"].values(), ser_delivery, {
        "agreement_id": "agreement_id", "kitchen_id": "kitchen_id",
        "window_id": "window_id", "status": "status",
        "delivery_date": lambda d: d["delivery_date"].isoformat(),
    })


@bp.route("/f2s/deliveries/<rid>", methods=["GET"])
def get_delivery(rid):
    ctx()
    rec = get_or_404("deliveries", rid, "ERR_DELIVERY_NOT_FOUND")
    return ok_object(ser_delivery(rec))


def _kitchen_owned_delivery(rid, uid):
    rec = get_or_404("deliveries", rid, "ERR_DELIVERY_NOT_FOUND")
    if rec["kitchen_id"] != uid:
        raise ApiError("ERR_RESOURCE_OWNERSHIP",
                       "KitchenManager may only act on its own kitchen's deliveries", 403)
    return rec


def _farm_owned_delivery(rid, uid):
    rec = get_or_404("deliveries", rid, "ERR_DELIVERY_NOT_FOUND")
    ag = store["agreements"][rec["agreement_id"]]
    _check_agreement_ownership(ag, uid)
    return rec


def _accept_effects(dv):
    ag = store["agreements"][dv["agreement_id"]]
    if ag["status"] == "FULFILLING" and delivered_quantity(ag["id"]) == ag["committed_quantity"]:
        ag["status"] = "COMPLETED"
        touch(ag)


@bp.route("/f2s/deliveries/<rid>/check-in", methods=["POST"])
def check_in_delivery(rid):
    uid, role = ctx()
    require_role(role, KM)
    rec = _kitchen_owned_delivery(rid, uid)
    if rec["status"] != "SCHEDULED":
        raise ApiError("ERR_DELIVERY_NOT_SCHEDULED", "check-in requires status SCHEDULED", 409)
    rec["status"] = "CHECKED_IN"
    touch(rec)
    return ok_object(ser_delivery(rec))


@bp.route("/f2s/deliveries/<rid>/accept", methods=["POST"])
def accept_delivery(rid):
    uid, role = ctx()
    b = body()
    accepted = req_int(b, "accepted_quantity")
    require_role(role, KM)
    rec = _kitchen_owned_delivery(rid, uid)
    if rec["status"] != "CHECKED_IN":
        raise ApiError("ERR_DELIVERY_NOT_CHECKED_IN", "accept requires status CHECKED_IN", 409)
    if not (1 <= accepted <= rec["quantity"]):
        raise ApiError("ERR_ACCEPTED_QUANTITY_OUT_OF_RANGE",
                       "accepted_quantity must be between 1 and the delivery quantity", 422)
    rec["accepted_quantity"] = accepted
    rec["status"] = "ACCEPTED"
    touch(rec)
    _accept_effects(rec)
    return ok_object(ser_delivery(rec))


@bp.route("/f2s/deliveries/<rid>/reject", methods=["POST"])
def reject_delivery(rid):
    uid, role = ctx()
    b = body()
    reason = req_str(b, "reason")
    require_role(role, KM)
    rec = _kitchen_owned_delivery(rid, uid)
    if rec["status"] != "CHECKED_IN":
        raise ApiError("ERR_DELIVERY_NOT_CHECKED_IN", "reject requires status CHECKED_IN", 409)
    rec["rejection_reason"] = reason
    rec["status"] = "REJECTED"
    touch(rec)
    return ok_object(ser_delivery(rec))


@bp.route("/f2s/deliveries/<rid>/dispute", methods=["POST"])
def dispute_delivery(rid):
    uid, role = ctx()
    require_role(role, FM)
    rec = _farm_owned_delivery(rid, uid)
    if rec["status"] != "REJECTED":
        raise ApiError("ERR_DELIVERY_NOT_REJECTED", "dispute requires status REJECTED", 409)
    rec["status"] = "DISPUTED"
    touch(rec)
    return ok_object(ser_delivery(rec))


@bp.route("/f2s/deliveries/<rid>/resolve-dispute", methods=["POST"])
def resolve_dispute(rid):
    uid, role = ctx()
    b = body()
    resolution = req_enum(b, "resolution", {"ACCEPTED", "CLOSED_REJECTED"})
    accepted = opt_int(b, "accepted_quantity")
    if resolution == "ACCEPTED" and accepted is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "accepted_quantity is required when resolution is ACCEPTED", 400)
    require_role(role, DPA)
    rec = get_or_404("deliveries", rid, "ERR_DELIVERY_NOT_FOUND")
    if rec["status"] != "DISPUTED":
        raise ApiError("ERR_DELIVERY_NOT_DISPUTED", "resolve-dispute requires status DISPUTED",
                       409)
    if resolution == "ACCEPTED":
        if not (1 <= accepted <= rec["quantity"]):
            raise ApiError("ERR_ACCEPTED_QUANTITY_OUT_OF_RANGE",
                           "accepted_quantity must be between 1 and the delivery quantity",
                           422)
        rec["accepted_quantity"] = accepted
        rec["status"] = "ACCEPTED"
        touch(rec)
        _accept_effects(rec)
    else:
        rec["status"] = "CLOSED_REJECTED"
        touch(rec)
    return ok_object(ser_delivery(rec))


@bp.route("/f2s/deliveries/<rid>/cancel", methods=["POST"])
def cancel_delivery(rid):
    uid, role = ctx()
    require_role(role, FM)
    rec = _farm_owned_delivery(rid, uid)
    if rec["status"] != "SCHEDULED":
        raise ApiError("ERR_DELIVERY_NOT_SCHEDULED", "cancel requires status SCHEDULED", 409)
    rec["status"] = "CANCELLED"
    touch(rec)
    return ok_object(ser_delivery(rec))
