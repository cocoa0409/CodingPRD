"""Treatment plans: drafting, approval quorum, scheduling, and completion."""
from datetime import timedelta

from flask import Blueprint

import calc
import domain
import store
import views
from common import (
    ALL_DISTRICT_READERS, ApiError, D, authenticate, authorize, created,
    get_body, logical_now, ok, ok_list, opt_int, opt_string, pagination,
    paginate, parse_dt, q2, query_enum, query_str, req_decimal, req_enum,
    req_int, req_present, req_string, validation,
)

bp = Blueprint("plan", __name__)

TREATMENT_TYPES = ("LARVICIDE", "ADULTICIDE", "AERIAL")
PLAN_STATUSES = ("DRAFT", "SUBMITTED", "RETURNED", "APPROVED", "SCHEDULED",
                 "IN_PROGRESS", "SUSPENDED", "COMPLETED", "CANCELLED")

PLAN_ACTORS = {
    "SUBMIT": "VectorEcologist",
    "REVISE": "VectorEcologist",
    "APPROVE": "AbatementManager",
    "RETURN": "AbatementManager",
    "SCHEDULE": "AbatementManager",
    "START": "AbatementManager",
    "SUSPEND": "AbatementManager",
    "RESUME": "AbatementManager",
    "COMPLETE": "AbatementManager",
    "CANCEL": "AbatementManager",
}

CANCELLABLE = ("DRAFT", "SUBMITTED", "RETURNED", "APPROVED", "SCHEDULED", "SUSPENDED")


def resolve_fk(body, key, kind):
    """Step-4 body reference resolution. Absent keys fall through to step 6."""
    value = body.get(key)
    if value is None:
        return None
    return store.fetch(kind, value)


# --------------------------------------------------------------------------
# Plan CRUD
# --------------------------------------------------------------------------


@bp.post("/treatment-plans")
def create_plan():
    authorize(authenticate(), ("VectorEcologist",))
    body = get_body()
    area = resolve_fk(body, "service_area_id", "ServiceArea")
    assessment = resolve_fk(body, "trigger_assessment_id", "RiskAssessment")

    req_string(body, "service_area_id", 1)
    req_string(body, "trigger_assessment_id", 1)
    treatment_type = req_enum(body, "treatment_type", TREATMENT_TYPES)

    if assessment["service_area_id"] != area["id"]:
        raise ApiError("ERR_AREA_MISMATCH", 422,
                       "The trigger assessment belongs to another service area.")

    record = store.new_record()
    record.update({
        "service_area_id": area["id"],
        "trigger_assessment_id": assessment["id"],
        "treatment_type": treatment_type,
        "status": "DRAFT",
        "required_approvals": 2 if treatment_type == "AERIAL" else 1,
        "submitted_by_user_id": None,
        "approver_user_ids": [],
        "notification_required": treatment_type in ("ADULTICIDE", "AERIAL"),
        "revision_count": 0,
        "scheduled_start_at": None,
        "estimated_total_ml": q2(0),
        "material_cost_cents": 0,
        "labor_cost_cents": 0,
        "subtotal_cents": 0,
        "admin_fee_rate": D("0.0"),
        "admin_fee_cents": 0,
        "total_cost_cents": 0,
        "completed_at": None,
        "cancel_reason": None,
        "return_reason": None,
    })
    store.TREATMENT_PLANS[record["id"]] = record
    return created(views.plan_view(record))


@bp.get("/treatment-plans")
def list_plans():
    authorize(authenticate(), ALL_DISTRICT_READERS)
    limit, offset = pagination()
    area_id = query_str("service_area_id")
    trigger_id = query_str("trigger_assessment_id")
    status = query_enum("status", PLAN_STATUSES)
    rows = [p for p in store.TREATMENT_PLANS.values()
            if (area_id is None or p["service_area_id"] == area_id)
            and (trigger_id is None or p["trigger_assessment_id"] == trigger_id)
            and (status is None or p["status"] == status)]
    page, total = paginate(store.ordered(rows), limit, offset)
    return ok_list([views.plan_view(r) for r in page], limit, offset, total)


@bp.get("/treatment-plans/<plan_id>")
def get_plan(plan_id):
    authorize(authenticate(), ALL_DISTRICT_READERS)
    plan = store.fetch("TreatmentPlan", plan_id)
    return ok(views.plan_view(plan))


# --------------------------------------------------------------------------
# Route creation (child of a plan)
# --------------------------------------------------------------------------


@bp.post("/treatment-plans/<plan_id>/routes")
def create_route(plan_id):
    authorize(authenticate(), ("VectorEcologist",))
    plan = store.fetch("TreatmentPlan", plan_id)
    body = get_body()
    applicator = resolve_fk(body, "applicator_id", "Applicator")
    product = resolve_fk(body, "pesticide_product_id", "PesticideProduct")

    req_string(body, "applicator_id", 1)
    req_string(body, "pesticide_product_id", 1)
    route_code = req_string(body, "route_code", 1, 16)
    window_start = parse_dt(req_present(body, "window_start"), "window_start")
    window_end = parse_dt(req_present(body, "window_end"), "window_end")
    if window_end <= window_start:
        raise validation("window_end must be strictly after window_start.")
    planned_acres = req_decimal(body, "planned_acres", minimum=0, exclusive_min=True)
    center_x_m = req_int(body, "center_x_m")
    center_y_m = req_int(body, "center_y_m")
    swath_radius_m = opt_int(body, "swath_radius_m", minimum=0, default=0)

    for existing in store.TREATMENT_ROUTES.values():
        if existing["treatment_plan_id"] == plan["id"] and existing["route_code"] == route_code:
            raise ApiError("ERR_DUPLICATE_RESOURCE", 409,
                           "route_code '%s' already exists on this plan." % route_code)

    if plan["status"] not in ("DRAFT", "RETURNED"):
        raise domain.invalid_transition("Routes may only be added to a DRAFT or RETURNED plan.")

    duration_minutes = int((window_end - window_start).total_seconds() // 60)

    record = store.new_record()
    record.update({
        "treatment_plan_id": plan["id"],
        "applicator_id": applicator["id"],
        "pesticide_product_id": product["id"],
        "route_code": route_code,
        "window_start": window_start,
        "window_end": window_end,
        "planned_acres": q2(planned_acres),
        "center_x_m": center_x_m,
        "center_y_m": center_y_m,
        "swath_radius_m": swath_radius_m,
        "status": "PLANNED",
        "duration_minutes": duration_minutes,
        "estimated_volume_ml": q2(0),
        "actual_acres": None,
        "wind_speed_mph": None,
        "actual_volume_ml": None,
        "executed_at": None,
        "void_reason": None,
    })
    store.TREATMENT_ROUTES[record["id"]] = record
    return created(views.route_view(record))


# --------------------------------------------------------------------------
# Plan state machine
# --------------------------------------------------------------------------


@bp.post("/treatment-plans/<plan_id>/transitions")
def transition_plan(plan_id):
    actor = authorize(authenticate(), ("VectorEcologist", "AbatementManager"))
    body = get_body()
    action, known = domain.read_action(body, PLAN_ACTORS)
    domain.enforce_actor(action, known, PLAN_ACTORS, actor)

    plan = store.fetch("TreatmentPlan", plan_id)

    domain.require_action_supplied(action)
    scheduled_start_at = None
    return_reason = None
    cancel_reason = None
    if known and action == "SCHEDULE":
        scheduled_start_at = parse_dt(req_present(body, "scheduled_start_at"),
                                      "scheduled_start_at")
    if known and action == "RETURN":
        return_reason = opt_string(body, "return_reason", 1, 1000)
    if known and action == "CANCEL":
        cancel_reason = opt_string(body, "cancel_reason", 1, 1000)
    domain.require_known_action(action, known)

    handler = _PLAN_HANDLERS[action]
    handler(plan, actor, {
        "scheduled_start_at": scheduled_start_at,
        "return_reason": return_reason,
        "cancel_reason": cancel_reason,
    })
    return ok(views.plan_view(plan))


def _submit(plan, actor, args):
    if plan["status"] != "DRAFT":
        raise domain.invalid_transition("SUBMIT requires a DRAFT plan.")
    routes = domain.routes_of_plan(plan["id"])
    if not any(r["status"] == "PLANNED" for r in routes):
        raise domain.invalid_transition("The plan has no PLANNED route.")
    assessment = store.RISK_ASSESSMENTS.get(plan["trigger_assessment_id"])
    if assessment is None or assessment["status"] != "CONFIRMED":
        raise ApiError("ERR_TRIGGER_ASSESSMENT_NOT_CONFIRMED", 409,
                       "The triggering assessment is not CONFIRMED.")
    plan["status"] = "SUBMITTED"
    plan["submitted_by_user_id"] = actor.user_id
    store.touch(plan)


def _approve(plan, actor, args):
    if plan["status"] != "SUBMITTED":
        raise domain.invalid_transition("APPROVE requires a SUBMITTED plan.")
    if plan["submitted_by_user_id"] == actor.user_id:
        raise ApiError("ERR_SELF_APPROVAL", 403,
                       "The submitter may not approve their own plan.")
    if actor.user_id in (plan["approver_user_ids"] or []):
        raise ApiError("ERR_DUPLICATE_APPROVER", 409,
                       "This approver has already signed the plan.")
    plan["approver_user_ids"] = list(plan["approver_user_ids"] or []) + [actor.user_id]
    if len(plan["approver_user_ids"]) >= plan["required_approvals"]:
        plan["status"] = "APPROVED"
    store.touch(plan)


def _return(plan, actor, args):
    if plan["status"] != "SUBMITTED":
        raise domain.invalid_transition("RETURN requires a SUBMITTED plan.")
    if plan["submitted_by_user_id"] == actor.user_id:
        raise ApiError("ERR_SELF_APPROVAL", 403,
                       "The submitter may not return their own plan.")
    plan["status"] = "RETURNED"
    plan["return_reason"] = args["return_reason"]
    plan["revision_count"] = plan["revision_count"] + 1
    store.touch(plan)


def _revise(plan, actor, args):
    if plan["status"] != "RETURNED":
        raise domain.invalid_transition("REVISE requires a RETURNED plan.")
    plan["status"] = "DRAFT"
    plan["approver_user_ids"] = []
    plan["submitted_by_user_id"] = None
    store.touch(plan)


def _schedule(plan, actor, args):
    if plan["status"] != "APPROVED":
        raise domain.invalid_transition("SCHEDULE requires an APPROVED plan.")
    routes = domain.routes_of_plan(plan["id"])
    committed = [r for r in routes if r["status"] == "COMMITTED"]
    if not committed or any(r["status"] == "PLANNED" for r in routes):
        raise ApiError("ERR_NO_COMMITTED_ROUTE", 409,
                       "The plan needs at least one COMMITTED route and no PLANNED route.")

    notifications = domain.notifications_of_plan(plan["id"])
    for notification in notifications:
        if notification["status"] not in ("ACKNOWLEDGED", "EXPIRED"):
            raise ApiError("ERR_NOTIFICATION_INCOMPLETE", 409,
                           "A spray notice of this plan is not yet settled.")

    served_sites = set(n["sensitive_site_id"] for n in notifications
                       if n["status"] in ("ACKNOWLEDGED", "EXPIRED"))
    for site in domain.sensitive_sites_of_area(plan["service_area_id"]):
        if site["site_type"] not in ("APIARY", "ORGANIC_FARM"):
            continue
        if not any(calc.encroaches(r, site) for r in committed):
            continue
        if site["id"] not in served_sites:
            raise ApiError("ERR_NOTIFICATION_INCOMPLETE", 409,
                           "An encroached protected site has no served notice.")

    lead_hours = (calc.AERIAL_NOTIFICATION_LEAD_HOURS
                  if plan["treatment_type"] == "AERIAL"
                  else calc.GROUND_NOTIFICATION_LEAD_HOURS)
    if args["scheduled_start_at"] - logical_now() < timedelta(hours=lead_hours):
        raise ApiError("ERR_NOTIFICATION_LEAD_TIME", 422,
                       "The scheduled start does not honour the notification lead time.")

    plan["status"] = "SCHEDULED"
    plan["scheduled_start_at"] = args["scheduled_start_at"]
    store.touch(plan)


def _start(plan, actor, args):
    if plan["status"] != "SCHEDULED":
        raise domain.invalid_transition("START requires a SCHEDULED plan.")
    if logical_now() < plan["scheduled_start_at"]:
        raise ApiError("ERR_PLAN_START_TOO_EARLY", 409,
                       "The scheduled start instant has not been reached.")
    plan["status"] = "IN_PROGRESS"
    store.touch(plan)


def _suspend(plan, actor, args):
    if plan["status"] != "IN_PROGRESS":
        raise domain.invalid_transition("SUSPEND requires an IN_PROGRESS plan.")
    plan["status"] = "SUSPENDED"
    store.touch(plan)


def _resume(plan, actor, args):
    if plan["status"] != "SUSPENDED":
        raise domain.invalid_transition("RESUME requires a SUSPENDED plan.")
    plan["status"] = "IN_PROGRESS"
    store.touch(plan)


def _complete(plan, actor, args):
    if plan["status"] != "IN_PROGRESS":
        raise domain.invalid_transition("COMPLETE requires an IN_PROGRESS plan.")
    routes = domain.routes_of_plan(plan["id"])
    settled = all(r["status"] in ("VERIFIED", "VOIDED", "RELEASED") for r in routes)
    if not settled or not any(r["status"] == "VERIFIED" for r in routes):
        raise ApiError("ERR_ROUTES_NOT_SETTLED", 409,
                       "Every route must be settled with at least one VERIFIED.")
    allocation = calc.treatment_cost_allocation(plan["id"])
    plan.update(allocation)
    plan["status"] = "COMPLETED"
    plan["completed_at"] = logical_now()
    store.touch(plan)


def _cancel(plan, actor, args):
    if plan["status"] not in CANCELLABLE:
        raise domain.invalid_transition("CANCEL is not available from %s." % plan["status"])
    plan["status"] = "CANCELLED"
    plan["cancel_reason"] = args["cancel_reason"]
    store.touch(plan)

    for route in domain.routes_of_plan(plan["id"]):
        if route["status"] == "PLANNED":
            route["status"] = "RELEASED"
            store.touch(route)
        elif route["status"] == "COMMITTED":
            product = store.PESTICIDE_PRODUCTS.get(route["pesticide_product_id"])
            if product is not None:
                domain.ledger_release(product, route["estimated_volume_ml"])
            applicator = store.APPLICATORS.get(route["applicator_id"])
            if applicator is not None:
                applicator["assigned_route_count"] = applicator["assigned_route_count"] - 1
                store.touch(applicator)
            route["status"] = "RELEASED"
            store.touch(route)

    for notification in domain.notifications_of_plan(plan["id"]):
        if notification["status"] in ("QUEUED", "SENT"):
            notification["status"] = "EXPIRED"
            store.touch(notification)

    domain.recompute_plan_estimated_total(plan)


_PLAN_HANDLERS = {
    "SUBMIT": _submit,
    "APPROVE": _approve,
    "RETURN": _return,
    "REVISE": _revise,
    "SCHEDULE": _schedule,
    "START": _start,
    "SUSPEND": _suspend,
    "RESUME": _resume,
    "COMPLETE": _complete,
    "CANCEL": _cancel,
}
