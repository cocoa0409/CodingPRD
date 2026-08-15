"""Resupply order endpoints (PRD 3.5): the request-to-invoice pipeline with
parallel auth/fulfillment dimensions, segregation of duties, and optimistic
concurrency on the patient record (PRD 2.6)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_PATIENT_NOT_IN_ACTIVE_THERAPY,
    ERR_PLAN_NOT_ACTIVE,
    ERR_QUANTITY_MISMATCH,
    ERR_CADENCE_NOT_MET,
    ERR_PRIOR_AUTH_REQUIRED,
    ERR_ORDER_NOT_PENDING_CLINICAL,
    ERR_COMPLIANCE_NOT_CURRENT,
    ERR_ORDER_NOT_PENDING_AUTH,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_PATIENT_VERSION,
    ERR_ORDER_NOT_AUTHORIZED,
    ERR_ORDER_NOT_READY_TO_SHIP,
    ERR_ORDER_NOT_SHIPPED,
    ERR_ORDER_NOT_DELIVERED,
    ERR_ORDER_NOT_CANCELLABLE,
)
from middleware import authorized, ROLE_INTAKE, ROLE_RT, ROLE_BILLING
from response import success_object
from routes.helpers import get_one, list_response
from services.core import (
    new_record,
    public,
    touch,
    payer_for_patient,
    cadence_days_for,
    FEE_SCHEDULE_CENTS,
)
from util import today, parse_date, add_days, coinsurance_share_cents
from validate import (
    get_body,
    req_str,
    opt_int,
    require_path_resource,
    fk_if_present,
)

bp = Blueprint("resupply_orders", __name__, url_prefix="/sleep-therapy")

PRIOR_AUTH_FIELD_CANDIDATES = (
    "prior_auth_reference",
    "prior_authorization_reference",
    "prior_auth_ref",
    "prior_auth",
)


def _expected_version(body):
    """expected_patient_version: non-optional integer on authorize/ship (PRD 2.6)."""
    v = body.get("expected_patient_version")
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_INVALID_REQUEST,
                    "missing or invalid integer field: expected_patient_version")
    return v


@bp.post("/resupply-orders")
def create_resupply_order():
    authorized([ROLE_INTAKE])
    body = get_body()

    # Priority 4: body FK existence (patient_id, then component_supply_plan_id).
    patient_id = body.get("patient_id")
    plan_id = body.get("component_supply_plan_id")
    patient = fk_if_present("patients", patient_id)
    if patient_id is not None and patient is None:
        from errors import ERR_FK_NOT_FOUND
        raise_error(ERR_FK_NOT_FOUND, f"patient_id does not resolve: {patient_id}")
    plan = fk_if_present("component_supply_plans", plan_id)
    if plan_id is not None and plan is None:
        from errors import ERR_FK_NOT_FOUND
        raise_error(ERR_FK_NOT_FOUND, f"component_supply_plan_id does not resolve: {plan_id}")

    # Priority 5: patient state.
    if patient is None:
        raise_error(ERR_INVALID_REQUEST, "missing required field: patient_id")
    if patient["patient_status"] != "ACTIVE_THERAPY":
        raise_error(ERR_PATIENT_NOT_IN_ACTIVE_THERAPY,
                    "patient must be in ACTIVE_THERAPY to create a resupply order")

    # Priority 6: plan state.
    if plan is None:
        raise_error(ERR_INVALID_REQUEST, "missing required field: component_supply_plan_id")
    if plan["plan_status"] != "ACTIVE":
        raise_error(ERR_PLAN_NOT_ACTIVE, "component supply plan must be ACTIVE")

    # Priority 7: full-cycle quantity.
    requested_quantity = body.get("requested_quantity")
    if (requested_quantity is None or isinstance(requested_quantity, bool)
            or not isinstance(requested_quantity, int)):
        raise_error(ERR_INVALID_REQUEST, "missing or invalid integer field: requested_quantity")
    if requested_quantity != plan["quantity_per_cycle"]:
        raise_error(ERR_QUANTITY_MISMATCH,
                    "requested_quantity must equal the plan's quantity_per_cycle")

    # Priority 8: cadence gate (inclusive: ordering ON next_eligible_on is eligible).
    next_eligible = plan.get("next_eligible_on")
    if next_eligible is not None and today() < parse_date(next_eligible):
        raise_error(ERR_CADENCE_NOT_MET, "component cadence window has not elapsed")

    # Priority 9: prior authorization reference when the payer requires it.
    payer = payer_for_patient(patient)
    if payer is not None and payer.get("requires_prior_auth"):
        supplied = any(
            isinstance(body.get(name), str) and body.get(name).strip() != ""
            for name in PRIOR_AUTH_FIELD_CANDIDATES
        )
        if not supplied:
            raise_error(ERR_PRIOR_AUTH_REQUIRED,
                        "payer requires a prior-authorization reference")

    # Lowest priority: remaining body shape (expected_patient_version optional on
    # creation; the OCC check itself applies only to authorize/ship per PRD 2.6).
    expected_patient_version = opt_int(body, "expected_patient_version", default=None)

    rec = new_record("resupply_orders", {
        "patient_id": patient_id,
        "component_supply_plan_id": plan_id,
        "expected_patient_version": expected_patient_version,
        "auth_status": "PENDING_CLINICAL_CLEARANCE",
        "fulfillment_status": "NOT_READY",
        "requested_quantity": requested_quantity,
        "unit_allowable_cents": None,
        "patient_responsibility_cents": None,
        "clinical_cleared_by_user_id": None,
        "authorized_by_user_id": None,
        "shipped_on": None,
        "denial_reason_code": None,
    })
    return success_object(public(rec), status=201)


@bp.get("/resupply-orders")
def list_resupply_orders():
    filters = {
        "patient_id": request.args.get("patient_id"),
        "component_supply_plan_id": request.args.get("component_supply_plan_id"),
        "auth_status": request.args.get("auth_status"),
        "fulfillment_status": request.args.get("fulfillment_status"),
    }
    return list_response("resupply_orders", filters)


@bp.get("/resupply-orders/<rid>")
def get_resupply_order(rid):
    return get_one("resupply_orders", rid)


@bp.post("/resupply-orders/<rid>/clinical-clear")
def clinical_clear(rid):
    caller = authorized([ROLE_RT])
    order = require_path_resource("resupply_orders", rid)
    if order["auth_status"] != "PENDING_CLINICAL_CLEARANCE":
        raise_error(ERR_ORDER_NOT_PENDING_CLINICAL,
                    "order must be in PENDING_CLINICAL_CLEARANCE for clinical clearance")
    patient = db["patients"].get(order["patient_id"])
    has_finalized = any(
        r["patient_id"] == order["patient_id"] and r["report_status"] == "FINALIZED"
        for r in db["adherence_reports"].values()
    )
    # First-fill grace: no FINALIZED adherence report yet clears regardless.
    if has_finalized and not (patient and patient.get("is_compliance_current")):
        raise_error(ERR_COMPLIANCE_NOT_CURRENT,
                    "patient compliance is not current and no first-fill grace applies")
    order["auth_status"] = "PENDING_PAYER_AUTH"
    order["clinical_cleared_by_user_id"] = caller.user_id
    touch(order)
    return success_object(public(order))


@bp.post("/resupply-orders/<rid>/authorize")
def authorize_order(rid):
    caller = authorized([ROLE_BILLING])
    order = require_path_resource("resupply_orders", rid)
    # Check order (PRD 3.5): state -> segregation of duties -> OCC.
    if order["auth_status"] != "PENDING_PAYER_AUTH" or order["fulfillment_status"] != "NOT_READY":
        raise_error(ERR_ORDER_NOT_PENDING_AUTH,
                    "order must be in PENDING_PAYER_AUTH with fulfillment NOT_READY")
    if caller.user_id == order.get("clinical_cleared_by_user_id"):
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    "authorizer must differ from the clinician who cleared the order")
    body = get_body()
    expected = _expected_version(body)
    patient = db["patients"].get(order["patient_id"])
    if patient is None or expected != patient["version"]:
        raise_error(ERR_STALE_PATIENT_VERSION,
                    "expected_patient_version does not match the patient's current version")

    plan = db["component_supply_plans"].get(order["component_supply_plan_id"])
    allowable = opt_int(body, "unit_allowable_cents", default=None, minimum=0)
    if allowable is None:
        allowable = FEE_SCHEDULE_CENTS.get(plan["component_type"], 0) if plan else 0

    order["auth_status"] = "AUTHORIZED"
    order["fulfillment_status"] = "READY_TO_SHIP"
    order["unit_allowable_cents"] = allowable
    order["authorized_by_user_id"] = caller.user_id
    touch(order)
    # Authorization advances the patient record, invalidating stale snapshots.
    touch(patient)
    return success_object(public(order))


@bp.post("/resupply-orders/<rid>/deny")
def deny_order(rid):
    authorized([ROLE_BILLING])
    order = require_path_resource("resupply_orders", rid)
    if order["auth_status"] != "PENDING_PAYER_AUTH":
        raise_error(ERR_ORDER_NOT_PENDING_AUTH,
                    "order must be in PENDING_PAYER_AUTH to deny")
    body = get_body()
    reason = req_str(body, "denial_reason_code")
    order["auth_status"] = "DENIED"
    order["denial_reason_code"] = reason
    touch(order)
    patient = db["patients"].get(order["patient_id"])
    if patient is not None:
        touch(patient)
    return success_object(public(order))


@bp.post("/resupply-orders/<rid>/ship")
def ship_order(rid):
    authorized([ROLE_INTAKE])
    order = require_path_resource("resupply_orders", rid)
    body = get_body()
    # OCC is evaluated before the readiness checks (PRD 3.5).
    expected = _expected_version(body)
    patient = db["patients"].get(order["patient_id"])
    if patient is None or expected != patient["version"]:
        raise_error(ERR_STALE_PATIENT_VERSION,
                    "expected_patient_version does not match the patient's current version")
    if order["auth_status"] != "AUTHORIZED":
        raise_error(ERR_ORDER_NOT_AUTHORIZED, "order must be AUTHORIZED to ship")
    if order["fulfillment_status"] != "READY_TO_SHIP":
        raise_error(ERR_ORDER_NOT_READY_TO_SHIP,
                    "order fulfillment must be READY_TO_SHIP to ship")

    current = today()
    order["fulfillment_status"] = "SHIPPED"
    order["shipped_on"] = current.isoformat()
    touch(order)

    # Shipment resets the component cadence clock.
    plan = db["component_supply_plans"].get(order["component_supply_plan_id"])
    payer = payer_for_patient(patient)
    if plan is not None and payer is not None:
        plan["last_dispensed_on"] = current.isoformat()
        plan["next_eligible_on"] = add_days(
            current, cadence_days_for(payer, plan["component_type"])
        ).isoformat()
        touch(plan)

    touch(patient)
    return success_object(public(order))


@bp.post("/resupply-orders/<rid>/mark-delivered")
def mark_delivered(rid):
    authorized([ROLE_INTAKE])
    order = require_path_resource("resupply_orders", rid)
    if order["fulfillment_status"] != "SHIPPED":
        raise_error(ERR_ORDER_NOT_SHIPPED, "order must be SHIPPED to mark delivered")
    order["fulfillment_status"] = "DELIVERED"
    touch(order)
    return success_object(public(order))


@bp.post("/resupply-orders/<rid>/invoice")
def invoice_order(rid):
    authorized([ROLE_BILLING])
    order = require_path_resource("resupply_orders", rid)
    if order["fulfillment_status"] != "DELIVERED":
        raise_error(ERR_ORDER_NOT_DELIVERED, "order must be DELIVERED to invoice")

    line_total = int(order["unit_allowable_cents"]) * int(order["requested_quantity"])
    share = coinsurance_share_cents(line_total)  # 20% of the line total, half-up
    order["fulfillment_status"] = "INVOICED"
    order["patient_responsibility_cents"] = share
    touch(order)

    patient = db["patients"].get(order["patient_id"])
    if patient is not None:
        patient["outstanding_balance_cents"] = int(
            patient.get("outstanding_balance_cents") or 0
        ) + share
        touch(patient)
    return success_object(public(order))


@bp.post("/resupply-orders/<rid>/mark-returned")
def mark_returned(rid):
    authorized([ROLE_INTAKE])
    order = require_path_resource("resupply_orders", rid)
    if order["fulfillment_status"] != "DELIVERED":
        raise_error(ERR_ORDER_NOT_DELIVERED,
                    "order must be DELIVERED to mark returned")
    order["fulfillment_status"] = "RETURNED"
    touch(order)
    return success_object(public(order))


@bp.post("/resupply-orders/<rid>/cancel")
def cancel_order(rid):
    authorized([ROLE_INTAKE])
    order = require_path_resource("resupply_orders", rid)
    if not (order["auth_status"] in ("PENDING_CLINICAL_CLEARANCE", "PENDING_PAYER_AUTH")
            and order["fulfillment_status"] == "NOT_READY"):
        raise_error(ERR_ORDER_NOT_CANCELLABLE,
                    "only pre-authorization orders with fulfillment NOT_READY can cancel")
    order["auth_status"] = "CANCELLED"
    touch(order)
    return success_object(public(order))
