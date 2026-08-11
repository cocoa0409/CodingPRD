"""ActivityRelationship endpoints (PRD §3.2).

Business-rule order for creation (PRD §2.6 / §3.2):
  relationship_type validity -> self-relationship -> cycle check -> membership
  (the cycle check fires BEFORE the same-version membership check).
"""

from flask import Blueprint

from db import store
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_INVALID_RELATIONSHIP_TYPE,
    ERR_SELF_RELATIONSHIP,
    ERR_CYCLE_DETECTED,
    ERR_ACTIVITY_NOT_IN_VERSION,
)
from middleware import (
    require_roles, json_body, req_field, as_str, as_int, paginate,
    sorted_items, serialize, ANY_ROLE,
)
from response import ok_object, ok_list
from util import new_id, clock_iso
from routes.common import get_version, activities_of, relationships_of
from services.cpm import creates_cycle

bp = Blueprint("relationships", __name__)

REL_TYPES = {"FS", "SS", "FF", "SF"}


@bp.route("/construction-projects/<pid>/schedule-versions/<vid>/relationships",
          methods=["POST"], strict_slashes=False)
def create_relationship(pid, vid):
    require_roles("ContractorScheduler")
    project, version = get_version(pid, vid)
    data = json_body()
    pred = as_str(req_field(data, "predecessor_activity_id"),
                  "predecessor_activity_id")
    succ = as_str(req_field(data, "successor_activity_id"),
                  "successor_activity_id")
    rtype_raw = req_field(data, "relationship_type")
    lag = as_int(data.get("lag_days", 0), "lag_days")
    if version["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Relationships may only be added to a DRAFT schedule")
    if not isinstance(rtype_raw, str) or rtype_raw not in REL_TYPES:
        raise ApiError(ERR_INVALID_RELATIONSHIP_TYPE, 422,
                       "relationship_type not in {FS,SS,FF,SF}")
    if pred == succ:
        raise ApiError(ERR_SELF_RELATIONSHIP, 422,
                       "predecessor_activity_id == successor_activity_id")
    if creates_cycle(version["id"], pred, succ):
        raise ApiError(ERR_CYCLE_DETECTED, 422,
                       "Relationship would introduce a cycle in the "
                       "schedule DAG")
    member_ids = {a["id"] for a in activities_of(version["id"])}
    if pred not in member_ids or succ not in member_ids:
        raise ApiError(ERR_ACTIVITY_NOT_IN_VERSION, 422,
                       "Both activities must belong to the schedule version "
                       "in the path")
    relationship = {
        "id": new_id(),
        "schedule_version_id": version["id"],
        "predecessor_activity_id": pred,
        "successor_activity_id": succ,
        "relationship_type": rtype_raw,
        "lag_days": lag,
        "created_at": clock_iso(),
        "_seq": store.next_seq(),
    }
    store.relationships[relationship["id"]] = relationship
    return ok_object(serialize(relationship), 201)


@bp.route("/construction-projects/<pid>/schedule-versions/<vid>/relationships",
          methods=["GET"], strict_slashes=False)
def list_relationships(pid, vid):
    require_roles(*ANY_ROLE)
    project, version = get_version(pid, vid)
    items = sorted_items(relationships_of(version["id"]))
    page, pg = paginate(items)
    return ok_list([serialize(r) for r in page], pg)
