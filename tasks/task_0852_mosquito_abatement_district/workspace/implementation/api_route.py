"""Treatment routes: commitment compliance checkpoint, execution, settlement."""
from datetime import timedelta

from flask import Blueprint

import calc
import domain
import store
import views
from common import (
    ALL_DISTRICT_READERS, ApiError, D, authenticate, authorize, get_body,
    logical_now, ok, ok_list, opt_string, pagination, paginate, q2,
    query_enum, query_str, req_decimal,
)

bp = Blueprint("route", __name__)

ROUTE_STATUSES = ("PLANNED", "COMMITTED", "EXECUTED", "VERIFIED", "VOIDED", "RELEASED")
ROUTE_ACTORS = {
    "COMMIT": "AbatementManager",
    "EXECUTE": "FieldTech",
    "VERIFY": "AbatementManager",
    "VOID": "AbatementManager",
    "RELEASE": "AbatementManager",
}


@bp.get("/treatment-routes")
def list_routes():
    authorize(authenticate(), ALL_DISTRICT_READERS)
    limit, offset = pagination()
    plan_id = query_str("treatment_plan_id")
    applicator_id = query_str("applicator_id")
    product_id = query_str("pesticide_product_id")
    status = query_enum("status", ROUTE_STATUSES)
    rows = [r for r in store.TREATMENT_ROUTES.values()
            if (plan_id is None or r["treatment_plan_id"] == plan_id)
            and (applicator_id is None or r["applicator_id"] == applicator_id)
            and (product_id is None or r["pesticide_product_id"] == product_id)
            and (status is None or r["status"] == status)]
    page, total = paginate(store.ordered(rows), limit, offset)
    return ok_list([views.route_view(r) for r in page], limit, offset, total)


@bp.get("/treatment-routes/<route_id>")
def get_route(route_id):
    authorize(authenticate(), ALL_DISTRICT_READERS)
    route = store.fetch("TreatmentRoute", route_id)
    return ok(views.route_view(route))


@bp.post("/treatment-routes/<route_id>/transitions")
def transition_route(route_id):
    actor = authorize(authenticate(), ("AbatementManager", "FieldTech"))
    body = get_body()
    action, known = domain.read_action(body, ROUTE_ACTORS)
    domain.enforce_actor(action, known, ROUTE_ACTORS, actor)

    route = store.fetch("TreatmentRoute", route_id)

    if known and action == "EXECUTE":
        if actor.user_id != route["applicator_id"]:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                           "Only the assigned applicator may execute this route.")

    domain.require_action_supplied(action)
    actual_acres = None
    wind_speed_mph = None
    void_reason = None
    if known and action == "EXECUTE":
        actual_acres = req_decimal(body, "actual_acres", minimum=0, exclusive_min=True)
        wind_speed_mph = req_decimal(body, "wind_speed_mph", minimum=0)
    if known and action == "VOID":
        void_reason = opt_string(body, "void_reason", 1, 1000)
    domain.require_known_action(action, known)

    plan = store.TREATMENT_PLANS.get(route["treatment_plan_id"])

    if action == "COMMIT":
        _commit(route, plan)
    elif action == "EXECUTE":
        _execute(route, plan, actual_acres, wind_speed_mph)
    elif action == "VERIFY":
        if route["status"] != "EXECUTED":
            raise domain.invalid_transition("VERIFY requires an EXECUTED route.")
        route["status"] = "VERIFIED"
        store.touch(route)
    elif action == "VOID":
        _void(route, plan, void_reason)
    else:  # RELEASE
        _release(route, plan)

    return ok(views.route_view(route))


# --------------------------------------------------------------------------
# COMMIT — nine ordered conditions (PRD §3.9)
# --------------------------------------------------------------------------


def _commit(route, plan):
    if route["status"] != "PLANNED":
        raise domain.invalid_transition("COMMIT requires a PLANNED route.")

    # 1 — parent plan approved
    if plan is None or plan["status"] != "APPROVED":
        raise ApiError("ERR_PLAN_NOT_APPROVED", 409, "The parent plan is not APPROVED.")

    applicator = store.APPLICATORS.get(route["applicator_id"])
    product = store.PESTICIDE_PRODUCTS.get(route["pesticide_product_id"])
    area = store.SERVICE_AREAS.get(plan["service_area_id"])

    # 2 — applicator fitness
    fit = (applicator is not None
           and applicator["status"] == "ACTIVE"
           and applicator["license_expires_on"] >= route["window_start"].date()
           and product is not None
           and product["application_method"] in calc.LICENSE_COVERAGE[
               applicator["license_category"]])
    if not fit:
        raise ApiError("ERR_APPLICATOR_LICENSE_INVALID", 422,
                       "The applicator is not fit for this route.")

    # 3 — product method vs plan modality
    if product["application_method"] != plan["treatment_type"]:
        raise ApiError("ERR_PRODUCT_METHOD_MISMATCH", 422,
                       "The product's application method differs from the plan modality.")

    # 4 — posture gate
    if plan["treatment_type"] in ("ADULTICIDE", "AERIAL"):
        if area is None or area["risk_posture"] not in ("ELEVATED", "EMERGENCY"):
            raise ApiError("ERR_POSTURE_TOO_LOW", 409,
                           "The area's risk posture does not justify adult spraying.")

    # 5 — protected-site clearance
    if plan["treatment_type"] in ("ADULTICIDE", "AERIAL"):
        cleared_sites = set(
            n["sensitive_site_id"] for n in domain.notifications_of_plan(plan["id"])
            if n["status"] in ("SENT", "ACKNOWLEDGED"))
        for site in domain.sensitive_sites_of_area(plan["service_area_id"]):
            if site["site_type"] not in ("APIARY", "ORGANIC_FARM"):
                continue
            if not calc.encroaches(route, site):
                continue
            if site["id"] not in cleared_sites:
                raise ApiError("ERR_SENSITIVE_SITE_NOT_CLEARED", 409,
                               "An encroached protected site has no served notice.")

    # 6 — re-entry interval, per active ingredient across the whole area
    quarantine = timedelta(hours=product["reentry_interval_hours"])
    for other in store.TREATMENT_ROUTES.values():
        if other["id"] == route["id"]:
            continue
        if other["status"] not in ("EXECUTED", "VERIFIED"):
            continue
        other_plan = store.TREATMENT_PLANS.get(other["treatment_plan_id"])
        if other_plan is None or other_plan["service_area_id"] != plan["service_area_id"]:
            continue
        other_product = store.PESTICIDE_PRODUCTS.get(other["pesticide_product_id"])
        if other_product is None or other_product["active_ingredient"] != product["active_ingredient"]:
            continue
        if route["window_start"] <= other["window_end"] + quarantine:
            raise ApiError("ERR_REENTRY_INTERVAL_VIOLATION", 409,
                           "The route falls inside an active re-entry quarantine.")

    # 7 — applicator occupancy with a trailing turnaround buffer
    buffer = timedelta(minutes=calc.ROUTE_SETUP_BUFFER_MINUTES)
    for other in store.TREATMENT_ROUTES.values():
        if other["id"] == route["id"]:
            continue
        if other["applicator_id"] != route["applicator_id"]:
            continue
        if other["status"] not in ("COMMITTED", "EXECUTED", "VERIFIED"):
            continue
        if (route["window_start"] < other["window_end"] + buffer
                and other["window_start"] < route["window_end"] + buffer):
            raise ApiError("ERR_APPLICATOR_ROUTE_CONFLICT", 409,
                           "The applicator is already occupied in that window.")

    # 8 — seasonal cap
    if area is not None and area["seasonal_application_count"] >= calc.MAX_SEASONAL_APPLICATIONS:
        raise ApiError("ERR_SEASONAL_LIMIT_EXCEEDED", 409,
                       "The area has reached its seasonal application cap.")

    # 9 — inventory sufficiency
    estimated = calc.estimated_volume(route["planned_acres"], product["label_rate_ml_per_acre"])
    if D(product["on_hand_ml"]) < estimated:
        raise ApiError("ERR_INSUFFICIENT_INVENTORY", 409,
                       "On-hand stock is below the route's estimated volume.")

    route["estimated_volume_ml"] = estimated
    route["status"] = "COMMITTED"
    store.touch(route)
    domain.ledger_commit(product, estimated)
    applicator["assigned_route_count"] = applicator["assigned_route_count"] + 1
    store.touch(applicator)
    domain.recompute_plan_estimated_total(plan)


# --------------------------------------------------------------------------
# EXECUTE
# --------------------------------------------------------------------------


def _execute(route, plan, actual_acres, wind_speed_mph):
    if route["status"] != "COMMITTED":
        raise domain.invalid_transition("EXECUTE requires a COMMITTED route.")
    if plan is None or plan["status"] != "IN_PROGRESS":
        raise ApiError("ERR_PLAN_NOT_IN_PROGRESS", 409,
                       "The parent plan is not IN_PROGRESS.")
    if logical_now() < route["window_start"]:
        raise ApiError("ERR_ROUTE_WINDOW_NOT_OPEN", 409,
                       "The route window has not opened yet.")

    product = store.PESTICIDE_PRODUCTS.get(route["pesticide_product_id"])
    actual = calc.actual_volume(actual_acres, product["label_rate_ml_per_acre"],
                                wind_speed_mph)
    estimated = D(route["estimated_volume_ml"])
    if D(product["on_hand_ml"]) + estimated - actual < D("0.00"):
        raise ApiError("ERR_INSUFFICIENT_INVENTORY", 409,
                       "The actual application would drive on-hand stock negative.")

    route["actual_acres"] = q2(actual_acres)
    route["wind_speed_mph"] = wind_speed_mph
    route["actual_volume_ml"] = actual
    route["executed_at"] = logical_now()
    route["status"] = "EXECUTED"
    store.touch(route)

    domain.ledger_execute(product, estimated, actual)

    area = store.SERVICE_AREAS.get(plan["service_area_id"])
    if area is not None:
        area["seasonal_application_count"] = area["seasonal_application_count"] + 1
        store.touch(area)


# --------------------------------------------------------------------------
# VOID — three-hop compensation
# --------------------------------------------------------------------------


def _void(route, plan, void_reason):
    if route["status"] not in ("EXECUTED", "VERIFIED"):
        raise domain.invalid_transition("VOID requires an EXECUTED or VERIFIED route.")
    route["status"] = "VOIDED"
    route["void_reason"] = void_reason
    store.touch(route)

    product = store.PESTICIDE_PRODUCTS.get(route["pesticide_product_id"])
    if product is not None:
        domain.ledger_void(product, route["actual_volume_ml"] or 0)

    if plan is not None:
        area = store.SERVICE_AREAS.get(plan["service_area_id"])
        if area is not None:
            area["seasonal_application_count"] = area["seasonal_application_count"] - 1
            store.touch(area)

    applicator = store.APPLICATORS.get(route["applicator_id"])
    if applicator is not None:
        applicator["assigned_route_count"] = applicator["assigned_route_count"] - 1
        store.touch(applicator)

    if plan is not None:
        siblings = domain.routes_of_plan(plan["id"])
        if plan["status"] == "COMPLETED" and not any(
                r["status"] in ("EXECUTED", "VERIFIED") for r in siblings):
            plan["status"] = "IN_PROGRESS"
            plan["completed_at"] = None
            plan["material_cost_cents"] = 0
            plan["labor_cost_cents"] = 0
            plan["subtotal_cents"] = 0
            plan["admin_fee_rate"] = D("0.0")
            plan["admin_fee_cents"] = 0
            plan["total_cost_cents"] = 0
            store.touch(plan)
        domain.recompute_plan_estimated_total(plan)


# --------------------------------------------------------------------------
# RELEASE
# --------------------------------------------------------------------------


def _release(route, plan):
    if route["status"] not in ("PLANNED", "COMMITTED"):
        raise domain.invalid_transition("RELEASE requires a PLANNED or COMMITTED route.")
    was_committed = route["status"] == "COMMITTED"
    route["status"] = "RELEASED"
    store.touch(route)
    if was_committed:
        product = store.PESTICIDE_PRODUCTS.get(route["pesticide_product_id"])
        if product is not None:
            domain.ledger_release(product, route["estimated_volume_ml"])
        applicator = store.APPLICATORS.get(route["applicator_id"])
        if applicator is not None:
            applicator["assigned_route_count"] = applicator["assigned_route_count"] - 1
            store.touch(applicator)
    if plan is not None:
        domain.recompute_plan_estimated_total(plan)
