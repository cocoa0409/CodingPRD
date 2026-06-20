"""DrugOrder endpoints and chairside lifecycle."""
from flask import Blueprint, request

import errors
from db import db
from errors import err
from calculations import compute_dose
from middleware import get_auth, require_roles
from response import success, list_success
from store_helpers import (
    make_common, touch, public, sort_by_created,
    get_drug_order, get_cycle, get_order_set_item, get_prior_auth, get_nurse,
)
from validation import (
    get_body, require_str, require_number, optional_number,
    get_pagination, paginate,
)

bp = Blueprint("drug_orders", __name__)

ALL_ROLES = {"Pharmacist", "Nurse", "PriorAuthCoordinator"}


@bp.route("/drug-orders", methods=["POST"])
def create_drug_order():
    _, role = get_auth()
    require_roles(role, {"Pharmacist"})
    body = get_body()
    # Existence: FK ids resolved left-to-right (cycle, item, optional PA).
    cycle_id = require_str(body, "treatment_cycle_id")
    cycle = get_cycle(cycle_id)
    item_id = require_str(body, "order_set_item_id")
    item = get_order_set_item(item_id)
    prior_authorization_id = body.get("prior_authorization_id")
    pa = None
    if prior_authorization_id is not None:
        if not isinstance(prior_authorization_id, str):
            raise err(errors.ERR_INVALID_REQUEST, "prior_authorization_id must be a string")
        pa = get_prior_auth(prior_authorization_id)

    # Body well-formedness: dose_reduction_pct in [0, 100].
    dose_reduction_pct = optional_number(body, "dose_reduction_pct", default=0, ge=0, le=100)

    with db.lock:
        # State legality: parent cycle must be ACTIVE.
        if cycle["status"] != "ACTIVE":
            raise err(errors.ERR_CYCLE_NOT_ACTIVE, "Parent cycle is not ACTIVE")

        # Referential safety: specialty CHEMO order requires an APPROVED matching PA
        # for the same patient and drug_name.
        if item["role"] == "CHEMO" and prior_authorization_id is not None:
            # When a PA is supplied for a CHEMO order it must be an approved match.
            if not _is_approved_match(pa, cycle, item):
                raise err(errors.ERR_PRIOR_AUTH_REQUIRED,
                          "Prior authorization must be an APPROVED match for patient and drug")
        elif item["role"] == "CHEMO" and prior_authorization_id is None:
            # Specialty CHEMO drugs require authorization. We treat the presence of
            # any PriorAuthorization for this patient+drug as the signal that this drug
            # is a specialty drug requiring auth; if such a PA exists the order must
            # link an APPROVED one.
            if _specialty_required(cycle, item):
                raise err(errors.ERR_PRIOR_AUTH_REQUIRED,
                          "Specialty CHEMO drug order requires an APPROVED prior_authorization_id")

        dose = compute_dose(
            dosing_method=item["dosing_method"],
            dose_per_m2=item.get("dose_per_m2"),
            target_auc=item.get("target_auc"),
            flat_dose_mg=item.get("flat_dose_mg"),
            bsa_snapshot=cycle["bsa_snapshot_m2"],
            gfr_snapshot=cycle["gfr_snapshot_ml_min"],
            vial_size_mg=item["vial_size_mg"],
            dose_reduction_pct=dose_reduction_pct,
        )

        entity = make_common()
        entity.update({
            "treatment_cycle_id": cycle_id,
            "order_set_item_id": item_id,
            "prior_authorization_id": prior_authorization_id,
            "dose_reduction_pct": dose_reduction_pct,
            "ordered_dose_mg": dose["ordered_dose_mg"],
            "vials_drawn": dose["vials_drawn"],
            "supplied_mg": dose["supplied_mg"],
            "waste_mg": dose["waste_mg"],
            "jw_modifier": dose["jw_modifier"],
            "administered_dose_mg": 0,
            "prepared_by_nurse_id": None,
            "verified_by_nurse_id": None,
            "status": "ORDERED",
        })
        db.drug_orders[entity["id"]] = entity
        return success(public(entity), status=201)


def _is_approved_match(pa, cycle, item):
    return (
        pa is not None
        and pa["status"] == "APPROVED"
        and pa["patient_id"] == cycle["patient_id"]
        and pa["drug_name"] == item["drug_name"]
    )


def _specialty_required(cycle, item):
    """A drug is specialty-requiring-auth if a PriorAuthorization exists for this
    patient + drug_name. Such an order then must link an APPROVED PA."""
    for pa in db.prior_authorizations.values():
        if pa["patient_id"] == cycle["patient_id"] and pa["drug_name"] == item["drug_name"]:
            return True
    return False


@bp.route("/drug-orders", methods=["GET"])
def list_drug_orders():
    _, role = get_auth()
    require_roles(role, ALL_ROLES)
    limit, offset = get_pagination()
    filters = {
        "treatment_cycle_id": request.args.get("treatment_cycle_id"),
        "order_set_item_id": request.args.get("order_set_item_id"),
        "prior_authorization_id": request.args.get("prior_authorization_id"),
        "prepared_by_nurse_id": request.args.get("prepared_by_nurse_id"),
        "verified_by_nurse_id": request.args.get("verified_by_nurse_id"),
    }
    items = []
    for o in db.drug_orders.values():
        ok = True
        for field, val in filters.items():
            if val is not None and o.get(field) != val:
                ok = False
                break
        if ok:
            items.append(o)
    items = sort_by_created(items)
    total = len(items)
    window = [public(o) for o in paginate(items, limit, offset)]
    return list_success(window, limit, offset, total)


@bp.route("/drug-orders/<oid>", methods=["GET"])
def get_one_drug_order(oid):
    _, role = get_auth()
    require_roles(role, ALL_ROLES)
    entity = get_drug_order(oid)
    return success(public(entity), status=200)


@bp.route("/drug-orders/<oid>/prepare", methods=["POST"])
def prepare_order(oid):
    user_id, role = get_auth()
    require_roles(role, {"Nurse"})
    order = get_drug_order(oid)
    with db.lock:
        cycle = db.treatment_cycles.get(order["treatment_cycle_id"])
        # Parent cycle ACTIVE precedes order-state check per scaffold transition order.
        if cycle["status"] != "ACTIVE":
            raise err(errors.ERR_CYCLE_NOT_ACTIVE, "Parent cycle is not ACTIVE")
        if order["status"] != "ORDERED":
            raise err(errors.ERR_ORDER_NOT_ORDERED, "Order is not ORDERED")
        order["prepared_by_nurse_id"] = user_id
        order["status"] = "PREPARED"
        touch(order, bump_version=True)
        return success(public(order), status=200)


@bp.route("/drug-orders/<oid>/verify", methods=["POST"])
def verify_order(oid):
    user_id, role = get_auth()
    require_roles(role, {"Nurse"})
    order = get_drug_order(oid)
    body = get_body()
    # Body well-formedness (recomputed_dose_mg present, numeric) before state checks.
    recomputed_dose_mg = require_number(body, "recomputed_dose_mg")
    with db.lock:
        # Gate order (matches scaffold precondition order):
        # 1. PREPARED state, 2. chemo-certified, 3. segregation of duties, 4. dose match.
        if order["status"] != "PREPARED":
            raise err(errors.ERR_ORDER_NOT_PREPARED, "Order is not PREPARED")
        nurse = db.nurses.get(user_id)
        # Acting nurse identity comes from X-User-ID; if it does not resolve to a Nurse
        # it cannot be chemo-certified.
        if nurse is None or not nurse.get("is_chemo_certified", False):
            raise err(errors.ERR_NURSE_NOT_CERTIFIED, "Verifying nurse is not chemo-certified")
        if user_id == order.get("prepared_by_nurse_id"):
            raise err(errors.ERR_SAME_NURSE_VERIFICATION,
                      "Verifying nurse must differ from preparing nurse")
        if recomputed_dose_mg != order["ordered_dose_mg"]:
            raise err(errors.ERR_DOSE_VERIFICATION_MISMATCH,
                      "Recomputed dose does not match ordered dose")
        order["verified_by_nurse_id"] = user_id
        order["status"] = "VERIFIED"
        touch(order, bump_version=True)
        return success(public(order), status=200)


@bp.route("/drug-orders/<oid>/reject", methods=["POST"])
def reject_order(oid):
    user_id, role = get_auth()
    require_roles(role, {"Nurse"})
    order = get_drug_order(oid)
    with db.lock:
        if order["status"] != "PREPARED":
            raise err(errors.ERR_ORDER_NOT_PREPARED, "Order is not PREPARED")
        if user_id == order.get("prepared_by_nurse_id"):
            raise err(errors.ERR_SAME_NURSE_VERIFICATION,
                      "Rejecting nurse must differ from preparing nurse")
        order["prepared_by_nurse_id"] = None
        order["status"] = "ORDERED"
        touch(order, bump_version=True)
        return success(public(order), status=200)


@bp.route("/drug-orders/<oid>/administer", methods=["POST"])
def administer_order(oid):
    user_id, role = get_auth()
    require_roles(role, {"Nurse"})
    order = get_drug_order(oid)
    with db.lock:
        if order["status"] != "VERIFIED":
            raise err(errors.ERR_ORDER_NOT_VERIFIED, "Order is not VERIFIED")
        cycle = db.treatment_cycles.get(order["treatment_cycle_id"])
        if cycle["status"] != "ACTIVE":
            raise err(errors.ERR_CYCLE_NOT_ACTIVE, "Parent cycle is not ACTIVE")
        pa = None
        if order.get("prior_authorization_id") is not None:
            pa = db.prior_authorizations.get(order["prior_authorization_id"])
            remaining = None
            if pa is not None and pa["status"] == "APPROVED" and pa.get("authorized_units_mg") is not None:
                remaining = pa["authorized_units_mg"] - pa["consumed_units_mg"]
            if pa is None or pa["status"] != "APPROVED" or remaining is None or remaining < order["ordered_dose_mg"]:
                raise err(errors.ERR_PRIOR_AUTH_INSUFFICIENT,
                          "Prior authorization cannot cover the ordered dose")
        order["administered_dose_mg"] = order["ordered_dose_mg"]
        order["status"] = "ADMINISTERED"
        touch(order, bump_version=True)
        if pa is not None:
            pa["consumed_units_mg"] = pa["consumed_units_mg"] + order["ordered_dose_mg"]
            if pa["consumed_units_mg"] >= pa["authorized_units_mg"]:
                pa["status"] = "EXHAUSTED"
            touch(pa, bump_version=True)
        return success(public(order), status=200)


@bp.route("/drug-orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    _, role = get_auth()
    require_roles(role, {"Nurse", "Pharmacist"})
    order = get_drug_order(oid)
    with db.lock:
        if order["status"] not in ("ORDERED", "PREPARED", "VERIFIED"):
            raise err(errors.ERR_ORDER_TERMINAL, "Order is in a terminal state")
        order["status"] = "CANCELLED"
        # A cancelled (even previously VERIFIED) order reverses no reservation.
        touch(order, bump_version=True)
        return success(public(order), status=200)
