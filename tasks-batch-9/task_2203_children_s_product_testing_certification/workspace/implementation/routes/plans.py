"""Sampling plans and the periodic verification cycle (PRD 3.5)."""

from flask import Blueprint

import auth
import clock
import db
import paging
import refs
import response
import validation
from errors import ApiError
from routes.products import guard_not_archived
from services import calc, engine

bp = Blueprint("plans", __name__)

PLAN_TYPES = {"INITIAL", "PERIODIC"}
PLAN_STATES = {"DRAFT", "ACTIVE", "RESAMPLE_DUE", "LAPSED", "SUPERSEDED"}
PLAN_READ_ROLES = (
    "ComplianceAdministrator",
    "TestCoordinator",
    "CertificationOfficer",
)
ACTIVATABLE_PRODUCT_STATES = (
    "SCOPED",
    "EVIDENCE_RELIANCE",
    "FULL_TEST_PROGRAM",
    "EVIDENCE_COMPLETE",
    "CERTIFIED",
    "REMEDIATION",
)


@bp.post("/products/<product_id>/sampling-plans")
def create_plan(product_id):
    auth.require_roles("TestCoordinator")
    body = validation.json_body()
    plan_type = validation.enum_field(body, "plan_type", PLAN_TYPES)
    baseline_units_produced = validation.int_field(
        body, "baseline_units_produced", minimum=0, required=False, default=0
    )
    resample_grace_days = validation.int_field(
        body, "resample_grace_days", minimum=0, maximum=365, required=False, default=30
    )
    product = refs.product(product_id)
    guard_not_archived(product)
    category = refs.category(product["category_id"])

    draft = {
        "product_id": product["id"],
        "plan_type": plan_type,
        "baseline_units_produced": baseline_units_produced,
        "units_authorized": 0,
        "units_committed": 0,
        "units_available": 0,
        "plan_state": "DRAFT",
        "activated_at": None,
        "last_verified_at": None,
        "periodic_due_at": None,
        "resample_trigger": "NONE",
        "resample_grace_days": resample_grace_days,
    }
    draft["units_authorized"] = calc.sampling_plan_units_authorized(
        product, category, draft
    )
    draft["units_available"] = draft["units_authorized"]
    row = db.insert("sampling_plans", draft)
    return response.object_response(db.serialize("sampling_plans", row), 201)


@bp.get("/sampling-plans/<plan_id>")
def get_plan(plan_id):
    auth.require_roles(*PLAN_READ_ROLES)
    row = refs.plan(plan_id)
    return response.object_response(db.serialize("sampling_plans", row))


@bp.get("/sampling-plans")
def list_plans():
    auth.require_roles(*PLAN_READ_ROLES)
    product_id = validation.query_string("product_id")
    plan_type = validation.query_enum("plan_type", PLAN_TYPES)
    plan_state = validation.query_enum("plan_state", PLAN_STATES)
    return paging.build(
        "sampling_plans",
        [
            paging.eq_filter("product_id", product_id),
            paging.eq_filter("plan_type", plan_type),
            paging.eq_filter("plan_state", plan_state),
        ],
    )


@bp.post("/sampling-plans/<plan_id>/activate")
def activate_plan(plan_id):
    auth.require_roles("TestCoordinator")
    plan = refs.plan(plan_id)
    product = refs.product(plan["product_id"])
    guard_not_archived(product)
    # PRD 2.11 rank 9 applies to submission, archival, order booking and
    # certificate issuance only, so the plan's own state (rank 11) is decided
    # first on activation; the product-state precondition of PRD 3.5 follows.
    if plan["plan_state"] not in ("DRAFT", "RESAMPLE_DUE"):
        raise ApiError("ERR_PLAN_STATE_INVALID")
    if product["certification_state"] not in ACTIVATABLE_PRODUCT_STATES:
        raise ApiError("ERR_PRODUCT_STATE_INVALID")
    category = refs.category(product["category_id"])
    if plan["units_authorized"] < category["sampling_floor_units"]:
        raise ApiError("ERR_SAMPLING_FLOOR_NOT_MET")

    now = clock.now()
    plan["plan_state"] = "ACTIVE"
    plan["activated_at"] = now
    plan["last_verified_at"] = now
    plan["resample_trigger"] = "NONE"
    engine.stamp_periodic_due(plan, product)
    engine.bump("sampling_plans", plan)

    for other in db.find("sampling_plans", product_id=product["id"]):
        if other["id"] == plan["id"]:
            continue
        if other["plan_type"] != plan["plan_type"]:
            continue
        if other["plan_state"] in ("DRAFT", "ACTIVE", "RESAMPLE_DUE"):
            other["plan_state"] = "SUPERSEDED"
            engine.bump("sampling_plans", other)
    return response.object_response(db.serialize("sampling_plans", plan))


@bp.post("/sampling-plans/<plan_id>/periodic-review")
def periodic_review(plan_id):
    auth.require_roles("TestCoordinator")
    plan = refs.plan(plan_id)
    product = refs.product(plan["product_id"])
    guard_not_archived(product)
    if plan["plan_state"] not in ("ACTIVE", "RESAMPLE_DUE"):
        raise ApiError("ERR_PLAN_STATE_INVALID")

    now = clock.now()
    due_at = plan["periodic_due_at"]
    if plan["plan_state"] == "ACTIVE":
        if due_at is None or now < due_at:
            raise ApiError("ERR_PERIODIC_REVIEW_NOT_DUE")
        plan["plan_state"] = "RESAMPLE_DUE"
        plan["resample_trigger"] = "PERIODIC_INTERVAL"
        engine.resize_plan(plan, product)
        engine.bump("sampling_plans", plan)
        engine.recompute_product_derived(product)
        product["compliance_posture"] = "RESTRICTED"
        engine.bump("products", product)
    else:
        if due_at is None:
            raise ApiError("ERR_PERIODIC_REVIEW_NOT_DUE")
        deadline = clock.add_days(due_at, plan["resample_grace_days"])
        if not now > deadline:
            raise ApiError("ERR_PERIODIC_REVIEW_NOT_DUE")
        plan["plan_state"] = "LAPSED"
        engine.bump("sampling_plans", plan)
        engine.recompute_product_derived(product)
        product["compliance_posture"] = "SUSPENDED"
        engine.bump("products", product)
    return response.object_response(db.serialize("sampling_plans", plan))
