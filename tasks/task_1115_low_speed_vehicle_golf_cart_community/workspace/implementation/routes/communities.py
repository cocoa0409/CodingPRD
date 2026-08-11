"""Community endpoints: create, read, list, OCC-guarded update."""
from flask import Blueprint, request

import db
from db import touch
from errors import err_not_found, err_stale_version, err_validation
from middleware import get_caller, require_role
from response import ok_object, ok_list
from services import validate as v
from services.serializers import base_entity, community_view

bp = Blueprint("communities", __name__)

READ_ROLES = ["PlatformAdmin", "CommunityAdmin", "Inspector", "EnforcementOfficer", "PermitHolder"]


@bp.post("/api/communities")
def create_community():
    data = v.body()
    # Stage 1: schema
    name = v.require_str(data, "name")
    min_driver_age = v.optional_int(data, "min_driver_age", 12, 25, 16)
    insurance_required = v.optional_bool(data, "insurance_required", True)
    fleet_program_enabled = v.optional_bool(data, "fleet_program_enabled", False)
    min_liability = v.optional_int(data, "min_liability_coverage_cents", 0, None, 10000000)
    renewal_window_days = v.optional_int(data, "renewal_window_days", 0, None, 60)
    late_grace_days = v.optional_int(data, "late_grace_days", 0, None, 90)
    # Stage 2-3: auth + role
    caller = get_caller()
    require_role(caller, ["PlatformAdmin"])

    c = base_entity()
    c.update({
        "name": name,
        "min_driver_age": min_driver_age,
        "insurance_required": insurance_required,
        "fleet_program_enabled": fleet_program_enabled,
        "min_liability_coverage_cents": min_liability,
        "renewal_window_days": renewal_window_days,
        "late_grace_days": late_grace_days,
        "checked_out_count": 0,
    })
    db.communities[c["id"]] = c
    return ok_object(community_view(c), 201)


@bp.get("/api/communities/<cid>")
def get_community(cid):
    caller = get_caller()
    require_role(caller, READ_ROLES)
    c = db.communities.get(cid)
    if c is None:
        raise err_not_found("Community not found")
    return ok_object(community_view(c))


@bp.patch("/api/communities/<cid>")
def update_community(cid):
    data = v.body()
    # Stage 1: schema (types/ranges for provided fields; OCC field required)
    name = None
    if "name" in data:
        name = v.require_str(data, "name")
    min_driver_age = None
    if "min_driver_age" in data:
        min_driver_age = v.optional_int(data, "min_driver_age", 12, 25)
    insurance_required = None
    if "insurance_required" in data:
        insurance_required = v.require_bool(data, "insurance_required")
    fleet_program_enabled = None
    if "fleet_program_enabled" in data:
        fleet_program_enabled = v.require_bool(data, "fleet_program_enabled")
    min_liability = None
    if "min_liability_coverage_cents" in data:
        min_liability = v.optional_int(data, "min_liability_coverage_cents", 0, None)
    renewal_window_days = None
    if "renewal_window_days" in data:
        renewal_window_days = v.optional_int(data, "renewal_window_days", 0, None)
    late_grace_days = None
    if "late_grace_days" in data:
        late_grace_days = v.optional_int(data, "late_grace_days", 0, None)
    if "expected_community_version" not in data:
        raise err_validation("Field 'expected_community_version' is required")
    expected = v.require_int(data, "expected_community_version")

    caller = get_caller()
    require_role(caller, ["PlatformAdmin"])

    c = db.communities.get(cid)
    if c is None:
        raise err_not_found("Community not found")
    # Stage 5: OCC
    if expected != c["version"]:
        raise err_stale_version()

    if name is not None:
        c["name"] = name
    if min_driver_age is not None:
        c["min_driver_age"] = min_driver_age
    if insurance_required is not None:
        c["insurance_required"] = insurance_required
    if fleet_program_enabled is not None:
        c["fleet_program_enabled"] = fleet_program_enabled
    if min_liability is not None:
        c["min_liability_coverage_cents"] = min_liability
    if renewal_window_days is not None:
        c["renewal_window_days"] = renewal_window_days
    if late_grace_days is not None:
        c["late_grace_days"] = late_grace_days
    touch(c)
    return ok_object(community_view(c))


@bp.get("/api/communities")
def list_communities():
    caller = get_caller()
    require_role(caller, ["PlatformAdmin", "CommunityAdmin"])
    limit, offset = v.pagination_args()
    rows = v.sorted_by_created(list(db.communities.values()))
    page, total = v.paginate(rows, limit, offset)
    return ok_list([community_view(c) for c in page], limit, offset, total)
