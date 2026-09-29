"""Nutrition consults and oral supplement regimens (PRD section 3.9)."""

from flask import Blueprint

import api
import calcs
import domain
import serialize
import store
from errors import ApiError

bp = Blueprint("consults", __name__, url_prefix="/nutrition/nutrition-consults")
sup_bp = Blueprint("supplement_orders", __name__,
                   url_prefix="/nutrition/supplement-orders")

CONSULT_STATUSES = ("REQUESTED", "ASSIGNED", "ASSESSED", "SIGNED", "CANCELLED")
ACUITIES = ("ROUTINE", "URGENT")
ASSESSMENT_VARIANTS = ("SCREENING", "COMPREHENSIVE")
SUPPLEMENT_STATUSES = ("PENDING", "ACTIVE", "CANCELLED")


# ---------------------------------------------------------------------------
# Nutrition consults
# ---------------------------------------------------------------------------
@bp.post("")
@api.require("Physician", "Dietitian")
def raise_consult():
    body = api.body()
    patient_id = api.req_id(body, "patient_id")
    reason_code = api.req_str(body, "reason_code")
    acuity = api.opt_enum(body, "acuity", ACUITIES, "ROUTINE")

    patient = store.get_patient(patient_id)
    if patient["status"] != "ADMITTED":
        raise ApiError("ERR_PATIENT_DISCHARGED", "The patient is DISCHARGED.")

    consult = domain.new_consult(patient_id, reason_code, acuity, api.actor(),
                                 auto_generated=False)
    return api.created(serialize.consult(consult))


@bp.get("")
@api.require(*api.ALL_ROLES)
def list_consults():
    patient_id = api.q_str("patient_id")
    status = api.q_enum("status", CONSULT_STATUSES)
    acuity = api.q_enum("acuity", ACUITIES)
    auto_generated = api.q_bool("auto_generated")
    item_id = api.q_str("recommended_supplement_item_id")
    rows = api.filtered(list(store.consults.values()),
                        [(patient_id, "patient_id"), (status, "status"),
                         (acuity, "acuity"), (auto_generated, "auto_generated"),
                         (item_id, "recommended_supplement_item_id")])
    return api.paged(rows, serialize.consult)


@bp.get("/<consult_id>")
@api.require(*api.ALL_ROLES)
def read_consult(consult_id):
    return api.ok(serialize.consult(store.get_consult(consult_id)))


@bp.post("/<consult_id>/assign")
@api.require("Dietitian")
def assign_consult(consult_id):
    consult = store.get_consult(consult_id)
    body = api.body()
    dietitian_user_id = api.req_str(body, "dietitian_user_id")
    if consult["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a REQUESTED consult may be assigned.")
    consult["assigned_dietitian_user_id"] = dietitian_user_id
    consult["status"] = "ASSIGNED"
    store.touch(consult)
    return api.ok(serialize.consult(consult))


@bp.post("/<consult_id>/assess")
@api.require("Dietitian")
def assess_consult(consult_id):
    consult = store.get_consult(consult_id)
    body = api.body()
    variant = api.req_enum(body, "assessment_variant", ASSESSMENT_VARIANTS)
    weight_loss_pct = api.req_num(body, "weight_loss_pct")
    intake_pct = api.req_num(body, "intake_pct")
    bmi = api.req_num(body, "bmi")
    albumin = api.opt_num(body, "albumin_g_dl", None)
    supplement_item_id = api.opt_id(body, "recommended_supplement_item_id")

    if supplement_item_id is not None:
        store.get_menu_item(supplement_item_id)

    if consult["status"] != "ASSIGNED":
        raise ApiError("ERR_INVALID_STATE", "Only an ASSIGNED consult may be assessed.")
    if variant == "COMPREHENSIVE" and albumin is None:
        raise ApiError("ERR_ALBUMIN_REQUIRED",
                       "albumin_g_dl is mandatory for a COMPREHENSIVE assessment.")

    score, tier = calcs.malnutrition_risk_score(
        variant, weight_loss_pct, intake_pct, bmi, albumin)

    consult["assessment_variant"] = variant
    consult["weight_loss_pct"] = weight_loss_pct
    consult["intake_pct"] = intake_pct
    consult["bmi"] = bmi
    consult["albumin_g_dl"] = albumin
    consult["malnutrition_risk_score"] = score
    consult["risk_tier"] = tier
    consult["recommended_supplement_item_id"] = supplement_item_id
    consult["status"] = "ASSESSED"
    store.touch(consult)
    return api.ok(serialize.consult(consult))


@bp.post("/<consult_id>/sign")
@api.require("Dietitian")
def sign_consult(consult_id):
    consult = store.get_consult(consult_id)
    if consult["status"] != "ASSESSED":
        raise ApiError("ERR_INVALID_STATE", "Only an ASSESSED consult may be signed.")
    if api.actor() == consult["requested_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The user who raised the consult may not sign it.")
    consult["signed_by_user_id"] = api.actor()
    consult["status"] = "SIGNED"
    store.touch(consult)
    return api.ok(serialize.consult(consult))


@bp.post("/<consult_id>/cancel")
@api.require("Dietitian")
def cancel_consult(consult_id):
    consult = store.get_consult(consult_id)
    if consult["status"] not in ("REQUESTED", "ASSIGNED", "ASSESSED"):
        raise ApiError("ERR_INVALID_STATE",
                       "A %s consult cannot be cancelled." % consult["status"])
    consult["status"] = "CANCELLED"
    store.touch(consult)

    for order in store.sort_rows([s for s in store.supplement_orders.values()
                                  if s["consult_id"] == consult["id"]
                                  and s["status"] == "PENDING"]):
        order["status"] = "CANCELLED"
        order["cancelled_at"] = store.now()
        store.touch(order)
    return api.ok(serialize.consult(consult))


# ---------------------------------------------------------------------------
# Supplement orders
# ---------------------------------------------------------------------------
@sup_bp.post("")
@api.require("Dietitian")
def create_supplement_order():
    body = api.body()
    consult_id = api.req_id(body, "consult_id")
    menu_item_id = api.req_id(body, "menu_item_id")
    doses_per_day = api.req_int(body, "doses_per_day", lo=1, hi=6)
    expected_version = api.req_int(body, "expected_consult_version")

    consult = store.get_consult(consult_id)
    item = store.get_menu_item(menu_item_id)

    if expected_version != consult["version"]:
        raise ApiError("ERR_STALE_CONSULT_VERSION",
                       "expected_consult_version does not match the consult.")
    if item["status"] != "ACTIVE":
        raise ApiError("ERR_MENU_ITEM_DISCONTINUED",
                       "Menu item '%s' is DISCONTINUED." % item["item_code"])

    order = {
        "consult_id": consult_id,
        "patient_id": consult["patient_id"],
        "menu_item_id": menu_item_id,
        "doses_per_day": doses_per_day,
        "status": "PENDING",
        "daily_cost_cents": item["unit_cost_cents"] * doses_per_day,
        "ordered_by_user_id": api.actor(),
        "activated_at": None,
        "cancelled_at": None,
    }
    store.stamp_new(order)
    store.supplement_orders[order["id"]] = order

    consult["linked_supplement_order_count"] += 1
    store.touch(consult)
    return api.created(serialize.supplement_order(order))


@sup_bp.get("")
@api.require(*api.ALL_ROLES)
def list_supplement_orders():
    consult_id = api.q_str("consult_id")
    patient_id = api.q_str("patient_id")
    menu_item_id = api.q_str("menu_item_id")
    status = api.q_enum("status", SUPPLEMENT_STATUSES)
    rows = api.filtered(list(store.supplement_orders.values()),
                        [(consult_id, "consult_id"), (patient_id, "patient_id"),
                         (menu_item_id, "menu_item_id"), (status, "status")])
    return api.paged(rows, serialize.supplement_order)


@sup_bp.get("/<order_id>")
@api.require(*api.ALL_ROLES)
def read_supplement_order(order_id):
    return api.ok(serialize.supplement_order(store.get_supplement_order(order_id)))


@sup_bp.post("/<order_id>/activate")
@api.require("Dietitian")
def activate_supplement_order(order_id):
    order = store.get_supplement_order(order_id)
    patient = store.patients[order["patient_id"]]
    consult = store.consults[order["consult_id"]]
    item = store.menu_items[order["menu_item_id"]]

    if patient["status"] != "ADMITTED":
        raise ApiError("ERR_PATIENT_DISCHARGED", "The patient is DISCHARGED.")
    if order["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a PENDING supplement order may be activated.")
    if consult["status"] != "SIGNED":
        raise ApiError("ERR_CONSULT_NOT_SIGNED", "The backing consult is not SIGNED.")
    if item["status"] != "ACTIVE":
        raise ApiError("ERR_MENU_ITEM_DISCONTINUED",
                       "Menu item '%s' is DISCONTINUED." % item["item_code"])

    order["status"] = "ACTIVE"
    order["activated_at"] = store.now()
    store.touch(order)
    patient["daily_supplement_cost_cents"] += order["daily_cost_cents"]
    store.touch(patient)
    return api.ok(serialize.supplement_order(order))


@sup_bp.post("/<order_id>/cancel")
@api.require("Dietitian")
def cancel_supplement_order(order_id):
    order = store.get_supplement_order(order_id)
    if order["status"] not in ("PENDING", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE",
                       "A %s supplement order cannot be cancelled." % order["status"])

    was_active = order["status"] == "ACTIVE"
    order["status"] = "CANCELLED"
    order["cancelled_at"] = store.now()
    store.touch(order)

    if was_active:
        patient = store.patients[order["patient_id"]]
        patient["daily_supplement_cost_cents"] -= order["daily_cost_cents"]
        store.touch(patient)
    return api.ok(serialize.supplement_order(order))
