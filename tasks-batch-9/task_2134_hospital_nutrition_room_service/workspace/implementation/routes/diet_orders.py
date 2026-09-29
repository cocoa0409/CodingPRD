"""Prescribing a diet: draft, submit, revision, cosign, discontinue (PRD section 3.3)."""

from flask import Blueprint

import api
import calcs
import domain
import serialize
import store
from calcs import LIQUID_LEVELS, TEXTURE_LEVELS
from errors import ApiError

bp = Blueprint("diet_orders", __name__, url_prefix="/nutrition/diet-orders")

DIET_ORDER_STATUSES = ("DRAFT", "PENDING_COSIGN", "REVISION_REQUESTED", "ACTIVE",
                       "SUPERSEDED", "DISCONTINUED")


def _require_active_rules(order):
    """Validation priority 24 -- every referenced therapeutic rule is ACTIVE."""
    for rule in domain.rules_of(order):
        if rule["status"] != "ACTIVE":
            raise ApiError("ERR_DIET_RULE_RETIRED",
                           "Therapeutic diet rule '%s' is RETIRED." % rule["diet_code"])


def _activate(order, cosigned_by_user_id):
    """Shared activation: envelope, effective_from, version bump, four-level cascade."""
    order["cosigned_by_user_id"] = cosigned_by_user_id
    order["effective_from"] = store.now()
    order["status"] = "ACTIVE"
    domain.apply_envelope(order)
    store.touch(order)
    domain.run_activation_cascade(order)


@bp.post("")
@api.require("Physician")
def draft_diet_order():
    body = api.body()
    patient_id = api.req_id(body, "patient_id")
    primary_id = api.req_id(body, "primary_diet_rule_id")
    secondary_id = api.opt_id(body, "secondary_diet_rule_id")
    texture = api.opt_enum(body, "texture_level", TEXTURE_LEVELS, "REGULAR")
    liquid = api.opt_enum(body, "liquid_level", LIQUID_LEVELS, "THIN")

    patient = store.get_patient(patient_id)
    primary = store.get_diet_rule(primary_id)
    secondary = store.get_diet_rule(secondary_id) if secondary_id else None

    if patient["status"] != "ADMITTED":
        raise ApiError("ERR_PATIENT_DISCHARGED", "The patient is DISCHARGED.")

    for rule in [primary] + ([secondary] if secondary else []):
        if rule["status"] != "ACTIVE":
            raise ApiError("ERR_DIET_RULE_RETIRED",
                           "Therapeutic diet rule '%s' is RETIRED." % rule["diet_code"])

    order = {
        "patient_id": patient_id,
        "primary_diet_rule_id": primary_id,
        "secondary_diet_rule_id": secondary_id,
        "supersedes_diet_order_id": None,
        "superseded_by_diet_order_id": None,
        "ordering_physician_user_id": api.actor(),
        "cosigned_by_user_id": None,
        "texture_level": texture,
        "liquid_level": liquid,
        "status": "DRAFT",
        "revision_round": 0,
        "revision_note": None,
        "effective_from": None,
        "effective_sodium_cap_mg": None,
        "effective_potassium_cap_mg": None,
        "effective_carb_cap_g": None,
        "effective_texture_level": None,
        "effective_liquid_level": None,
        "forbidden_tag_codes_effective": [],
        "linked_meal_order_count": 0,
    }
    store.stamp_new(order)
    store.diet_orders[order["id"]] = order
    return api.created(serialize.diet_order(order))


@bp.get("")
@api.require(*api.ALL_ROLES)
def list_diet_orders():
    patient_id = api.q_str("patient_id")
    status = api.q_enum("status", DIET_ORDER_STATUSES)
    primary_id = api.q_str("primary_diet_rule_id")
    secondary_id = api.q_str("secondary_diet_rule_id")
    supersedes_id = api.q_str("supersedes_diet_order_id")
    rows = api.filtered(list(store.diet_orders.values()),
                        [(patient_id, "patient_id"), (status, "status"),
                         (primary_id, "primary_diet_rule_id"),
                         (secondary_id, "secondary_diet_rule_id"),
                         (supersedes_id, "supersedes_diet_order_id")])
    return api.paged(rows, serialize.diet_order)


@bp.get("/<order_id>")
@api.require(*api.ALL_ROLES)
def read_diet_order(order_id):
    return api.ok(serialize.diet_order(store.get_diet_order(order_id)))


@bp.post("/<order_id>/submit")
@api.require("Physician")
def submit_diet_order(order_id):
    order = store.get_diet_order(order_id)
    patient = store.patients[order["patient_id"]]

    if patient["status"] != "ADMITTED":
        raise ApiError("ERR_PATIENT_DISCHARGED", "The patient is DISCHARGED.")
    if order["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError("ERR_INVALID_STATE",
                       "A %s diet order cannot be submitted." % order["status"])
    _require_active_rules(order)

    rules = domain.rules_of(order)
    primary = rules[0]
    secondary = rules[1] if len(rules) > 1 else None
    needs_cosign = primary["requires_dietitian_cosign"] or (
        secondary is not None and secondary["requires_dietitian_cosign"])

    if order["status"] == "REVISION_REQUESTED":
        # Resubmission always returns the order to PENDING_COSIGN.
        order["status"] = "PENDING_COSIGN"
        domain.apply_envelope(order)
        store.touch(order)
    elif needs_cosign:
        order["status"] = "PENDING_COSIGN"
        domain.apply_envelope(order)
        store.touch(order)
    else:
        _activate(order, None)
    return api.ok(serialize.diet_order(order))


@bp.post("/<order_id>/request-revision")
@api.require("Dietitian")
def request_revision(order_id):
    order = store.get_diet_order(order_id)
    body = api.body()
    note = api.req_str(body, "revision_note")

    if order["status"] != "PENDING_COSIGN":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a PENDING_COSIGN diet order may be sent back.")
    if order["revision_round"] >= calcs.MAX_REVISION_ROUNDS:
        raise ApiError("ERR_REVISION_LIMIT_EXCEEDED",
                       "The diet order has exhausted its revision rounds.")

    order["status"] = "REVISION_REQUESTED"
    order["revision_note"] = note
    order["revision_round"] += 1
    store.touch(order)
    return api.ok(serialize.diet_order(order))


@bp.post("/<order_id>/cosign")
@api.require("Dietitian")
def cosign_diet_order(order_id):
    order = store.get_diet_order(order_id)
    patient = store.patients[order["patient_id"]]

    if patient["status"] != "ADMITTED":
        raise ApiError("ERR_PATIENT_DISCHARGED", "The patient is DISCHARGED.")
    if order["status"] != "PENDING_COSIGN":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a PENDING_COSIGN diet order may be cosigned.")
    if api.actor() == order["ordering_physician_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The ordering physician may not cosign their own order.")

    _activate(order, api.actor())
    return api.ok(serialize.diet_order(order))


@bp.post("/<order_id>/discontinue")
@api.require("Physician")
def discontinue_diet_order(order_id):
    order = store.get_diet_order(order_id)
    if order["status"] not in ("ACTIVE", "PENDING_COSIGN"):
        raise ApiError("ERR_INVALID_STATE",
                       "A %s diet order cannot be discontinued." % order["status"])

    was_active = order["status"] == "ACTIVE"
    order["status"] = "DISCONTINUED"
    store.touch(order)

    if was_active:
        for tray in store.sort_rows([o for o in store.meal_orders.values()
                                     if o["diet_order_id"] == order["id"]
                                     and o["fulfillment_status"] in ("PENDING_VALIDATION",
                                                                     "VALIDATED")]):
            tray["revalidation_required"] = True
            store.touch(tray)
    return api.ok(serialize.diet_order(order))
