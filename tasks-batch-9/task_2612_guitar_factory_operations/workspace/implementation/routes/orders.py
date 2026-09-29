"""Build orders: quoting, deposits, stage advance and cancellation
(PRD 3.6 and 3.8)."""

import re
from datetime import timedelta

from flask import Blueprint

import auth
import calc
import domain
import store
import validate as v
from constants import (ARTIST_TIERS, BASE_LEAD_DAYS, BUILD_STAGES,
                       COMMERCIAL_STATUSES, FINISH_SYSTEMS)
from envelope import object_response, paginate
from errors import ApiError
from serialize import order_view
from store import (BILLETS, CATALOG, COMPONENTS, INSPECTIONS, ORDERS,
                   RESERVATIONS, SELECTIONS, new_record, touch)

bp = Blueprint("orders", __name__)

MODEL_CODE_RE = re.compile(r"^[A-Z0-9-]{1,16}$")
IN_FLIGHT = ("ROUGH_SAWN", "CNC_ROUTED", "HAND_SHAPED", "QC_HELD", "REWORK")


def _order(build_order_id):
    return v.fetch(ORDERS, build_order_id, "ERR_BUILD_ORDER_NOT_FOUND")


@bp.post("/build-orders")
def create_order():
    auth.require(auth.CUSTOM_SHOP_COORDINATOR)
    body = v.body()
    order_code = v.get_str(body, "order_code", min_len=1, max_len=64)
    model_code = v.get_str(body, "model_code", min_len=1, max_len=16)
    if not MODEL_CODE_RE.match(model_code):
        v.bad("model_code must be uppercase alphanumerics and dashes")
    base_price = v.get_int(body, "base_price_cents", minimum=1)
    promised = v.get_ts(body, "promised_date")
    is_custom = v.get_bool(body, "is_custom_shop", required=False,
                           default=False)
    artist_tier = v.get_enum(body, "artist_tier", ARTIST_TIERS, required=False,
                             default="NONE")
    finish_system = v.get_enum(body, "finish_system", FINISH_SYSTEMS,
                               required=False, default="NITRO")
    v.unique_code(ORDERS, "order_code", order_code)
    rec = new_record(ORDERS, {
        "order_code": order_code,
        "model_code": model_code,
        "base_price_cents": base_price,
        "is_custom_shop": is_custom,
        "artist_tier": artist_tier,
        "finish_system": finish_system,
        "promised_date": promised,
        "provisional_quote_total_cents": 0,
        "binding_quote_total_cents": None,
        "deposit_paid_cents": 0,
        "deposit_held_cents": 0,
        "deposit_applied_cents": 0,
        "deposit_refunded_cents": 0,
        "deposit_forfeited_cents": 0,
        "serial_number": None,
        "rework_round_count": 0,
        "refinish_count": 0,
        "cites_permit_required": False,
        "strictest_cites_appendix": "NONE",
        "priority_score": 0,
        "stage_before_compliance_hold": None,
        "build_stage": "DRAFT",
        "commercial_status": "QUOTED",
    })
    calc.refresh_provisional_quote(rec)
    calc.refresh_priority(rec)
    return object_response(order_view(rec), 201)


@bp.get("/build-orders/<build_order_id>")
def read_order(build_order_id):
    auth.require_staff()
    return object_response(order_view(_order(build_order_id)))


@bp.get("/build-orders")
def list_orders():
    auth.require_staff()
    rows = v.apply_filters(list(ORDERS.values()), [
        ("build_stage", v.filter_enum("build_stage", BUILD_STAGES)),
        ("commercial_status", v.filter_enum("commercial_status",
                                           COMMERCIAL_STATUSES)),
        ("model_code", v.filter_value("model_code")),
        ("artist_tier", v.filter_enum("artist_tier", ARTIST_TIERS)),
        ("is_custom_shop", v.filter_bool("is_custom_shop")),
    ])
    rows.sort(key=lambda r: (-r["priority_score"], r["created_at"], r["_seq"]))
    return paginate(rows, order_view)


@bp.post("/build-orders/<build_order_id>/confirm")
def confirm_order(build_order_id):
    auth.require(auth.CUSTOM_SHOP_COORDINATOR)
    body = v.body()
    deposit = v.get_int(body, "deposit_cents", minimum=0)
    order = _order(build_order_id)
    if order["commercial_status"] != "QUOTED":
        raise ApiError("ERR_COMMERCIAL_STATUS_INVALID",
                       "only a QUOTED order may be confirmed")
    if order["is_custom_shop"]:
        selected = [s for s in SELECTIONS.values()
                    if s["build_order_id"] == order["id"]
                    and s["status"] == "SELECTED"]
        if not selected:
            raise ApiError("ERR_OPTIONS_NOT_SELECTED",
                           "a custom shop order needs an approved option")
    if deposit < calc.min_deposit_cents(order):
        raise ApiError("ERR_DEPOSIT_INSUFFICIENT",
                       "the deposit is below ten percent of the quote")
    order["commercial_status"] = "CONFIRMED"
    order["deposit_paid_cents"] += deposit
    order["deposit_held_cents"] += deposit
    calc.refresh_priority(order)
    touch(order)
    return object_response(order_view(order))


@bp.post("/build-orders/<build_order_id>/lock-options")
def lock_options(build_order_id):
    auth.require(auth.CUSTOM_SHOP_COORDINATOR)
    order = _order(build_order_id)
    if order["commercial_status"] != "CONFIRMED":
        raise ApiError("ERR_COMMERCIAL_STATUS_INVALID",
                       "only a CONFIRMED order may lock its options")
    order["commercial_status"] = "OPTIONS_LOCKED"
    max_lead = 0
    rows = [s for s in SELECTIONS.values()
            if s["build_order_id"] == order["id"]]
    rows.sort(key=lambda s: (CATALOG[s["option_id"]]["option_code"],
                             s["created_at"], s["_seq"]))
    for sel in rows:
        option = CATALOG[sel["option_id"]]
        if sel["status"] == "SELECTED":
            sel["status"] = "LOCKED"
            sel["locked_upcharge_cents"] = option["upcharge_cents"]
            touch(sel)
            if option["lead_time_days"] > max_lead:
                max_lead = option["lead_time_days"]
        elif sel["status"] == "PENDING_APPROVAL":
            sel["status"] = "REJECTED"
            touch(sel)
    calc.compute_binding_quote(order)
    computed = store.now_utc().replace(hour=0, minute=0, second=0,
                                       microsecond=0) \
        + timedelta(days=BASE_LEAD_DAYS + max_lead)
    if computed > order["promised_date"]:
        order["promised_date"] = computed
    calc.refresh_priority(order)
    touch(order)
    return object_response(order_view(order))


@bp.post("/build-orders/<build_order_id>/release-components")
def release_components(build_order_id):
    auth.require(auth.MACHINIST)
    order = _order(build_order_id)
    if order["build_stage"] != "DRAFT":
        raise ApiError("ERR_BUILD_STAGE_INVALID",
                       "the order has already left DRAFT")
    if order["commercial_status"] != "OPTIONS_LOCKED":
        raise ApiError("ERR_COMMERCIAL_STATUS_INVALID",
                       "the configuration must be locked before wood is cut")
    order["build_stage"] = "COMPONENTS_RELEASED"
    touch(order)
    return object_response(order_view(order))


@bp.post("/build-orders/<build_order_id>/start-assembly")
def start_assembly(build_order_id):
    auth.require(auth.LUTHIER)
    order = _order(build_order_id)
    if order["build_stage"] != "COMPONENTS_RELEASED":
        raise ApiError("ERR_BUILD_STAGE_INVALID",
                       "assembly starts from COMPONENTS_RELEASED")
    parts = domain.order_components(order)
    accepted = [c for c in parts if c["status"] == "ACCEPTED"]
    if not accepted:
        raise ApiError("ERR_COMPONENTS_NOT_ACCEPTED",
                       "no accepted part is available for assembly")
    if any(c["status"] in IN_FLIGHT for c in parts):
        raise ApiError("ERR_COMPONENT_IN_FLIGHT",
                       "a part on this order is still in flight")
    for comp in accepted:
        comp["status"] = "INSTALLED"
        touch(comp)
        billet = BILLETS.get(comp["billet_id"])
        if billet is not None and billet["status"] == "RESERVED":
            domain.consume_billet(billet)
    order["build_stage"] = "IN_ASSEMBLY"
    calc.refresh_protected_species(order)
    touch(order)
    return object_response(order_view(order))


@bp.post("/build-orders/<build_order_id>/fretwork")
def fretwork(build_order_id):
    auth.require(auth.LUTHIER)
    order = _order(build_order_id)
    if order["build_stage"] != "FINISH_CURED":
        raise ApiError("ERR_BUILD_STAGE_INVALID",
                       "fretwork follows a cured finish")
    order["build_stage"] = "FRETWORK"
    touch(order)
    return object_response(order_view(order))


@bp.post("/build-orders/<build_order_id>/setup")
def setup(build_order_id):
    auth.require(auth.LUTHIER)
    order = _order(build_order_id)
    if order["build_stage"] != "FRETWORK":
        raise ApiError("ERR_BUILD_STAGE_INVALID", "setup follows fretwork")
    order["build_stage"] = "SETUP"
    touch(order)
    return object_response(order_view(order))


@bp.post("/build-orders/<build_order_id>/assign-serial")
def assign_serial(build_order_id):
    auth.require(auth.CUSTOM_SHOP_COORDINATOR)
    order = _order(build_order_id)
    if order["serial_number"] is not None:
        raise ApiError("ERR_SERIAL_ALREADY_ASSIGNED",
                       "the order already carries a serial number")
    if order["build_stage"] != "INSPECTION":
        raise ApiError("ERR_BUILD_STAGE_INVALID",
                       "serialization happens from INSPECTION")
    rounds = [r for r in INSPECTIONS.values()
              if r["build_order_id"] == order["id"]]
    latest = max(rounds, key=lambda r: r["round_number"]) if rounds else None
    if latest is None or latest["status"] != "SIGNED" \
            or latest["verdict"] != "PASS":
        raise ApiError("ERR_INSPECTION_NOT_SIGNED",
                       "the latest inspection round has not passed")
    order["serial_number"] = calc.next_serial(order)
    order["build_stage"] = "SERIALIZED"
    if order["commercial_status"] in ("OPTIONS_LOCKED", "AT_RISK"):
        order["commercial_status"] = "INVOICED"
    applied = min(order["deposit_held_cents"],
                  order.get("binding_quote_total_cents") or 0)
    order["deposit_applied_cents"] += applied
    order["deposit_held_cents"] -= applied
    touch(order)
    return object_response(order_view(order))


@bp.post("/build-orders/<build_order_id>/clear-compliance-hold")
def clear_compliance_hold(build_order_id):
    auth.require(auth.COMPLIANCE_OFFICER)
    order = _order(build_order_id)
    if order["build_stage"] != "COMPLIANCE_HOLD":
        raise ApiError("ERR_BUILD_STAGE_INVALID",
                       "the order is not on a compliance hold")
    still_held = [c for c in domain.order_components(order)
                  if c["qc_hold_reason"] == "PROTECTED_SPECIES"]
    if still_held:
        raise ApiError("ERR_PROTECTED_SPECIES_QUARANTINED",
                       "a part is still impounded for protected species")
    order["build_stage"] = order["stage_before_compliance_hold"] or "DRAFT"
    order["stage_before_compliance_hold"] = None
    touch(order)
    return object_response(order_view(order))


@bp.post("/build-orders/<build_order_id>/cancel")
def cancel_order(build_order_id):
    auth.require(auth.CUSTOM_SHOP_COORDINATOR)
    body = v.body()
    v.get_str(body, "reason", required=False)
    order = _order(build_order_id)
    if order["build_stage"] == "SERIALIZED" \
            or order["commercial_status"] in ("INVOICED", "CLOSED",
                                             "CANCELLED"):
        raise ApiError("ERR_COMMERCIAL_STATUS_INVALID",
                       "the order can no longer be cancelled")
    forfeit, refund = calc.cancellation_disposition(order)
    for comp in domain.order_components(order):
        if comp["status"] in ("INSTALLED", "SCRAPPED"):
            continue
        comp["status"] = "SCRAPPED"
        touch(comp)
        billet = BILLETS.get(comp["billet_id"])
        if billet is not None and billet["status"] == "RESERVED":
            domain.recover_billet(billet)
    for res in list(RESERVATIONS.values()):
        if res["build_order_id"] == order["id"] and res["status"] == "HELD":
            domain.release_reservation(res)
    order["deposit_forfeited_cents"] += forfeit
    order["deposit_refunded_cents"] += refund
    order["deposit_held_cents"] = 0
    order["commercial_status"] = "CANCELLED"
    order["build_stage"] = "SCRAPPED"
    touch(order)
    return object_response(order_view(order))
