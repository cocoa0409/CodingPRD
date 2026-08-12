from flask import Blueprint

import core
import gates
import serialize
from core import fail, new_row, touch

bp = Blueprint("plans", __name__)

CREATE_SPEC = [
    ("tier", "string", True),
    ("monthly_fee_cents", "integer", True),
    ("included_visit_units", "integer", True),
    ("covered_visit_types", "array", True),
    ("entitlement_rollover_policy", "string", False),
    ("storm_guarantee_included", "boolean", False),
    ("status", "string", False),
]


@bp.post("/property-care/service-plans")
def create_plan():
    gates.begin(["PlatformAdmin"])
    body = gates.body_json()
    gates.validate_payload(body, CREATE_SPEC)
    covered = body["covered_visit_types"]
    # rung 68 - non-empty subset of the entitlement-consuming visit types
    if not covered or any(v not in core.ENTITLEMENT_CONSUMING_VISIT_TYPES for v in covered):
        fail("ERR_UNIQUENESS_VIOLATION",
             "covered_visit_types must be a non-empty subset of the entitlement-consuming types.")
    plan = new_row(
        "service_plans",
        tier=body["tier"],
        monthly_fee_cents=body["monthly_fee_cents"],
        included_visit_units=body["included_visit_units"],
        entitlement_rollover_policy=body.get("entitlement_rollover_policy", "EXPIRE"),
        storm_guarantee_included=body.get("storm_guarantee_included", False),
        covered_visit_types=covered,
        status=body.get("status", "ACTIVE"),
    )
    return core.ok(serialize.service_plan(plan), 201)


@bp.get("/property-care/service-plans")
def list_plans():
    gates.begin(["PlatformAdmin", "AccountManager", "Auditor", "Owner"])
    return gates.list_response("service_plans", ["tier", "status"], serialize.service_plan)


@bp.get("/property-care/service-plans/<sid>")
def read_plan(sid):
    gates.begin(["PlatformAdmin", "AccountManager", "Auditor", "Owner"])
    plan = gates.fetch_path("service_plans", sid)
    return core.ok(serialize.service_plan(plan))


@bp.post("/property-care/service-plans/<sid>/retire")
def retire_plan(sid):
    gates.begin(["PlatformAdmin"])
    plan = gates.fetch_path("service_plans", sid)
    plan["status"] = "RETIRED"
    touch(plan)
    return core.ok(serialize.service_plan(plan))
