"""Concept-design surface: conveyor segments and flow links."""

from flask import Blueprint

from auth import ALL_ROLES, authenticate
from errors import ApiError
from lookups import get_flow_link, get_project, get_segment
from response import list_response, object_response
from serializers import flow_link_out, segment_out
from services import calculations as calc
from services.cascade import advance_design_baseline
from store import new_record, ordered, segments_of, store, touch
from validate import (
    body,
    opt_int,
    pagination,
    paginate,
    query_filter,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("design", __name__)

EQUIPMENT_CLASSES = ("BELT", "ROLLER", "SORTATION", "MERGE")


def _require_design_state(project):
    if project["delivery_status"] != "DESIGN":
        raise ApiError(
            "ERR_PROJECT_NOT_IN_DESIGN",
            "Design mutations are only legal while delivery_status is DESIGN.",
        )


@bp.post("/segments")
def create_segment():
    authenticate(("DesignEngineer",))
    data = body()

    project_id = req_str(data, "project_id")
    segment_code = req_str(data, "segment_code")
    equipment_class = req_enum(data, "equipment_class", EQUIPMENT_CLASSES)
    rated_capacity_cph = req_int(data, "rated_capacity_cph", minimum=1)
    availability_pct = req_int(data, "availability_pct", minimum=1, maximum=100)
    source_share_bps = opt_int(data, "source_share_bps", minimum=1, maximum=10000)

    project = get_project(project_id)
    _require_design_state(project)

    for existing in segments_of(project["id"]):
        if existing["segment_code"] == segment_code:
            raise ApiError(
                "ERR_DUPLICATE_SEGMENT_CODE",
                "segment_code %s is already used on this project." % segment_code,
            )

    segment = new_record()
    segment.update(
        {
            "project_id": project["id"],
            "segment_code": segment_code,
            "equipment_class": equipment_class,
            "rated_capacity_cph": rated_capacity_cph,
            "availability_pct": availability_pct,
            "source_share_bps": source_share_bps,
            "inbound_link_count": 0,
            "outbound_link_count": 0,
            "flow_share_bps": 0,
            "derated_capacity_cph": 0,
        }
    )
    store.segments[segment["id"]] = segment

    advance_design_baseline(project)
    return object_response(segment_out(segment), 201)


@bp.patch("/segments/<segment_id>")
def update_segment(segment_id):
    authenticate(("DesignEngineer",))
    segment = get_segment(segment_id)
    data = body()

    rated_capacity_cph = None
    availability_pct = None
    if "rated_capacity_cph" in data:
        rated_capacity_cph = req_int(data, "rated_capacity_cph", minimum=1)
    if "availability_pct" in data:
        availability_pct = req_int(data, "availability_pct", minimum=1, maximum=100)
    source_share_supplied = "source_share_bps" in data
    source_share_bps = None
    if source_share_supplied and data["source_share_bps"] is not None:
        source_share_bps = req_int(data, "source_share_bps", minimum=1, maximum=10000)

    project = get_project(segment["project_id"])
    _require_design_state(project)

    if rated_capacity_cph is not None:
        segment["rated_capacity_cph"] = rated_capacity_cph
    if availability_pct is not None:
        segment["availability_pct"] = availability_pct
    if source_share_supplied:
        segment["source_share_bps"] = source_share_bps
    touch(segment)

    advance_design_baseline(project)
    return object_response(segment_out(segment))


@bp.get("/segments/<segment_id>")
def read_segment(segment_id):
    authenticate(ALL_ROLES)
    segment = get_segment(segment_id)
    return object_response(segment_out(segment))


@bp.post("/flow-links")
def create_flow_link():
    authenticate(("DesignEngineer",))
    data = body()

    project_id = req_str(data, "project_id")
    from_segment_id = req_str(data, "from_segment_id")
    to_segment_id = req_str(data, "to_segment_id")
    split_share_bps = req_int(data, "split_share_bps", minimum=1, maximum=10000)

    project = get_project(project_id)
    from_segment = get_segment(from_segment_id)
    to_segment = get_segment(to_segment_id)

    _require_design_state(project)

    if (
        from_segment["project_id"] != project["id"]
        or to_segment["project_id"] != project["id"]
    ):
        raise ApiError(
            "ERR_CROSS_PROJECT_REFERENCE",
            "Both endpoints of a flow link must belong to the named project.",
        )

    if calc.has_cycle_with(project["id"], from_segment["id"], to_segment["id"]):
        raise ApiError("ERR_FLOW_CYCLE", "The requested flow link would close a cycle.")

    link = new_record(versioned=False)
    link.update(
        {
            "project_id": project["id"],
            "from_segment_id": from_segment["id"],
            "to_segment_id": to_segment["id"],
            "split_share_bps": split_share_bps,
        }
    )
    store.flow_links[link["id"]] = link

    from_segment["outbound_link_count"] += 1
    touch(from_segment)
    to_segment["inbound_link_count"] += 1
    touch(to_segment)

    advance_design_baseline(project)
    return object_response(flow_link_out(link), 201)


@bp.get("/flow-links/<link_id>")
def read_flow_link(link_id):
    authenticate(ALL_ROLES)
    link = get_flow_link(link_id)
    return object_response(flow_link_out(link))


@bp.get("/flow-links")
def list_flow_links():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    project_id = query_filter("project_id")
    from_segment_id = query_filter("from_segment_id")
    to_segment_id = query_filter("to_segment_id")

    records = ordered(list(store.flow_links.values()))
    if project_id is not None:
        records = [r for r in records if r["project_id"] == project_id]
    if from_segment_id is not None:
        records = [r for r in records if r["from_segment_id"] == from_segment_id]
    if to_segment_id is not None:
        records = [r for r in records if r["to_segment_id"] == to_segment_id]
    page, total = paginate(records, limit, offset)
    return list_response([flow_link_out(r) for r in page], limit, offset, total)
