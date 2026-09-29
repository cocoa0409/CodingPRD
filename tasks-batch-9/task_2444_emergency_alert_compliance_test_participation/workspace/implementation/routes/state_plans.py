"""StatePlan endpoints (PRD 3.1)."""

from flask import Blueprint, request

import clock
import serializers
from auth import ANY_ROLE, guard
from envelope import object_response
from errors import ApiError
from routes.helpers import collection_response, filter_equals
from services.scoring import plan_supersede_cascade
from store import base_row, db, mark_created, touch
from validators import (
    EVENT_CODE_RE,
    SOURCE_TYPES,
    STATE_CODE_RE,
    get_state_plan,
    json_body,
    req_array,
    req_string,
)

bp = Blueprint("state_plans", __name__)


@bp.post("/state-plans")
@guard("ComplianceAdmin")
def create_state_plan():
    body = json_body(request)
    state_code = req_string(body, "state_code", pattern=STATE_CODE_RE)
    plan_version_label = req_string(body, "plan_version_label")
    required_source_types = req_array(
        body, "required_source_types", non_empty=True, distinct=True,
        member_enum=SOURCE_TYPES,
    )
    mandatory_relay_event_codes = req_array(
        body, "mandatory_relay_event_codes", non_empty=False,
        member_pattern=EVENT_CODE_RE,
    )

    plan = base_row()
    plan.update({
        "state_code": state_code,
        "plan_version_label": plan_version_label,
        "required_source_types": list(required_source_types),
        "mandatory_relay_event_codes": list(mandatory_relay_event_codes),
        "required_source_count": len(required_source_types),
        "status": "DRAFT",
        "activated_at": None,
        "superseded_at": None,
    })
    db.state_plans[plan["id"]] = plan
    mark_created(plan)
    return object_response(serializers.state_plan(plan), 201)


@bp.get("/state-plans/<plan_id>")
@guard(*ANY_ROLE)
def read_state_plan(plan_id):
    plan = get_state_plan(plan_id)
    return object_response(serializers.state_plan(plan))


@bp.get("/state-plans")
@guard(*ANY_ROLE)
def list_state_plans():
    rows = list(db.state_plans.values())
    rows = filter_equals(rows, request, (("state_code", "state_code"), ("status", "status")))
    return collection_response(rows, request, serializers.state_plan)


@bp.post("/state-plans/<plan_id>/activate")
@guard("ComplianceAdmin")
def activate_state_plan(plan_id):
    plan = get_state_plan(plan_id)
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_PLAN_NOT_DRAFT")
    if not plan["required_source_types"]:
        raise ApiError("ERR_INVALID_REQUEST", "required_source_types must not be empty.")

    plan["status"] = "ACTIVE"
    plan["activated_at"] = clock.now()
    touch(plan)
    plan_supersede_cascade(plan)
    return object_response(serializers.state_plan(plan))
