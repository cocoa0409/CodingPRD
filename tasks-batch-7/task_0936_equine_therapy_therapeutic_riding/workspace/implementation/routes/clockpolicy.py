"""POST /_clock/set_current_utc and the condition-policy catalogue."""

from flask import Blueprint, request

from core.constants import ACTIVITY_TYPES, POLICY_TIERS, CERT_LEVELS
from core.envelope import list_response, object_response
from core.ladder import Field, endpoint, pagination, paginate, query_enum, validate_body
from core.store import all_rows, clock, new_row
from domain import serialize

bp = Blueprint("clockpolicy", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint(["ProgramAdmin"])
def set_clock():
    payload = validate_body([Field("to_iso8601", "instant", required=True)])
    # §2.5: to_iso8601 is caller-supplied, so current_utc echoes it back exactly,
    # character for character - the server never re-renders it.
    clock.set(payload["to_iso8601"])
    return object_response({"current_utc": clock.raw()})


@bp.post("/condition-policies")
@endpoint(["ProgramAdmin"])
def create_condition_policy():
    payload = validate_body([
        Field("condition_code", "string", required=True),
        Field("activity_type", "enum", required=True, members=ACTIVITY_TYPES),
        Field("tier", "enum", required=True, members=POLICY_TIERS),
        Field("min_instructor_tier", "enum", members=CERT_LEVELS),
    ])
    row = new_row("condition_policies", versioned=False)
    row.update({
        "condition_code": payload["condition_code"],
        "activity_type": payload["activity_type"],
        "tier": payload["tier"],
        "min_instructor_tier": payload.get("min_instructor_tier") or "REGISTERED",
    })
    return object_response(serialize.condition_policy(row), 201)


@bp.get("/condition-policies")
@endpoint(["ProgramAdmin", "Instructor", "IntakeCoordinator"])
def list_condition_policies():
    limit, offset = pagination()
    # §2.9: activity_type in the QUERY string routes to ERR_VALIDATION, not to
    # ERR_INVALID_ENUM - the distinction is by position, not by field name.
    activity_type = query_enum("activity_type", ACTIVITY_TYPES)
    condition_code = _arg("condition_code")
    rows = all_rows("condition_policies")
    if activity_type is not None:
        rows = [r for r in rows if r["activity_type"] == activity_type]
    if condition_code is not None:
        rows = [r for r in rows if r["condition_code"] == condition_code]
    page = paginate(rows, limit, offset)
    return list_response([serialize.condition_policy(r) for r in page],
                         limit, offset, len(rows))


def _arg(name):
    return request.args.get(name)
