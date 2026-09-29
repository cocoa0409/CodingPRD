"""Routes, segments, federal crossings, mapping, publication and nomination
(PRD §3.2, §3.3, §3.4, §3.5)."""

from datetime import timedelta

from flask import Blueprint

import response as resp
from db import insert, store
from errors import ApiError
from middleware import ALL_ROLES, endpoint
from services import calc, derive
from validation import (
    apply_filters,
    collection_list,
    find_path,
    fk,
    get_body,
    opt_bool,
    opt_dt,
    opt_enum,
    opt_str,
    paginate,
    req_enum,
    req_id,
    req_int,
    req_num,
    req_str,
)

bp = Blueprint("corridors", __name__)

ROUTE_KINDS = ("PROPOSED", "ALTERNATE")
SURVEY_STATUSES = ("DESKTOP", "FIELD_VERIFIED")
CROSSING_KINDS = ("NONE", "PUBLIC_LAND", "NAVIGABLE_WATERWAY", "WETLAND")
AGENCIES = ("BLM", "USACE", "USFS")
PERMIT_ACTIONS = ("APPLY", "ISSUE", "DENY")
AGENCY_FOR_CROSSING = {
    "PUBLIC_LAND": ("BLM", "USFS"),
    "NAVIGABLE_WATERWAY": ("USACE",),
    "WETLAND": ("USACE",),
}
ROUTE_TERMINAL = ("CERTIFIED", "REJECTED")


# ----------------------------------------------------------- reads ----
@bp.get("/siting/routes")
@endpoint(ALL_ROLES)
def list_routes():
    rows, pagination = collection_list(store.routes, ["project_id", "kind", "status"])
    return resp.listing(rows, pagination)


@bp.get("/siting/routes/<route_id>")
@endpoint(ALL_ROLES)
def read_route(route_id):
    return resp.ok(find_path(store.routes, route_id))


@bp.get("/siting/routes/<route_id>/segments")
@endpoint(ALL_ROLES)
def list_route_segments(route_id):
    find_path(store.routes, route_id)
    rows = apply_filters(
        derive.segments_of_route(route_id),
        ["survey_status", "construction_state", "federal_permit_status", "route_id"],
    )
    rows, pagination = paginate(rows)
    return resp.listing(rows, pagination)


@bp.get("/siting/route-segments")
@endpoint(ALL_ROLES)
def list_segments():
    rows, pagination = collection_list(
        store.route_segments,
        ["route_id", "survey_status", "federal_permit_status", "construction_state"],
    )
    return resp.listing(rows, pagination)


@bp.get("/siting/route-segments/<segment_id>")
@endpoint(ALL_ROLES)
def read_segment(segment_id):
    return resp.ok(find_path(store.route_segments, segment_id))


# ---------------------------------------------------------- writes ----
@bp.post("/siting/routes")
@endpoint(["RouteAnalyst", "Developer"])
def create_route():
    body = get_body()
    project = fk(body, "project_id", store.projects)
    project_id = req_id(body, "project_id")
    label = req_str(body, "label")
    kind = req_enum(body, "kind", ROUTE_KINDS)

    row = insert(
        store.routes,
        {
            "project_id": project_id,
            "label": label,
            "kind": kind,
            "status": "DRAFT",
            "total_miles": 0,
            "segment_count": 0,
            "unsurveyed_segment_count": 0,
            "constraint_score_preliminary": None,
            "constraint_score_certified": None,
            "constraint_density_certified": None,
            "refinement_round": 0,
            "refinement_target_segment_id": None,
            "comment_window_closes_at": None,
            "open_house_held_count": 0,
            "open_house_counties": [],
        },
    )

    # PLANNING -> ROUTING once a certified need case backs the corridor work.
    if project is not None and project["stage"] == "PLANNING":
        certified = [
            s
            for s in derive.studies_of_project(project_id)
            if s["status"] == "CERTIFIED_SUFFICIENT"
        ]
        if certified:
            derive.update(project, stage="ROUTING")

    return resp.created(row)


@bp.post("/siting/route-segments")
@endpoint(["RouteAnalyst"])
def create_segment():
    body = get_body()
    route = fk(body, "route_id", store.routes)
    route_id = req_id(body, "route_id")
    sequence_index = req_int(body, "sequence_index", minimum=1)
    miles = req_num(body, "miles", exclusive_min=0)
    land_use_rating = req_int(body, "land_use_rating", minimum=0, maximum=5)
    environmental_rating = req_int(body, "environmental_rating", minimum=0, maximum=5)
    cultural_rating = req_int(body, "cultural_rating", minimum=0, maximum=5)
    engineering_rating = req_int(body, "engineering_rating", minimum=0, maximum=5)
    county = req_str(body, "county")
    crew_capacity = req_int(body, "crew_capacity", minimum=0)
    survey_status = opt_enum(body, "survey_status", SURVEY_STATUSES, "DESKTOP")
    habitat_blackout = opt_bool(body, "habitat_blackout", False)
    federal_crossing_kind = opt_enum(body, "federal_crossing_kind", CROSSING_KINDS, "NONE")

    for existing in derive.segments_of_route(route_id):
        if existing["sequence_index"] == sequence_index:
            raise ApiError(
                "ERR_SEGMENT_SEQUENCE_DUPLICATE",
                "sequence_index %s is already used on this route." % sequence_index,
            )

    row = insert(
        store.route_segments,
        {
            "route_id": route_id,
            "sequence_index": sequence_index,
            "miles": miles,
            "land_use_rating": land_use_rating,
            "environmental_rating": environmental_rating,
            "cultural_rating": cultural_rating,
            "engineering_rating": engineering_rating,
            "survey_status": survey_status,
            "county": county,
            "crew_capacity": crew_capacity,
            "committed_crew_count": 0,
            "construction_state": "PENDING",
            "habitat_blackout": habitat_blackout,
            "federal_crossing_kind": federal_crossing_kind,
            "federal_permit_status": "NOT_REQUIRED" if federal_crossing_kind == "NONE" else "REQUIRED",
            "federal_permit_agency": None,
            "material_comment_count": 0,
            "refinement_count": 0,
        },
    )
    if route is not None:
        derive.recompute_route_counters(route)
    return resp.created(row)


@bp.post("/siting/route-segments/<segment_id>/federal-permit-actions")
@endpoint(["FederalPermitOfficer"])
def federal_permit_action(segment_id):
    segment = find_path(store.route_segments, segment_id)
    body = get_body()
    action = req_enum(body, "action", PERMIT_ACTIONS)
    agency = opt_enum(body, "agency", AGENCIES)
    determination_note = opt_str(body, "determination_note")

    # A segment with no federal crossing has no permit dimension to drive at all;
    # the PRD names the agency mismatch for this case even though NOT_REQUIRED is terminal.
    if segment["federal_crossing_kind"] == "NONE":
        raise ApiError(
            "ERR_FEDERAL_AGENCY_MISMATCH",
            "The segment carries no federal crossing, so no permit action applies.",
        )

    status = segment["federal_permit_status"]
    if status in ("NOT_REQUIRED", "ISSUED"):
        raise ApiError("ERR_TERMINAL_STATE", "The federal permit dimension is already %s." % status)

    if action == "APPLY" and status not in ("REQUIRED", "DENIED"):
        raise ApiError("ERR_INVALID_STATE", "No APPLY transition leaves %s." % status)
    if action in ("ISSUE", "DENY") and status != "APPLIED":
        raise ApiError("ERR_INVALID_STATE", "No %s transition leaves %s." % (action, status))

    if action == "APPLY":
        allowed = AGENCY_FOR_CROSSING[segment["federal_crossing_kind"]]
        if agency is None or agency not in allowed:
            raise ApiError(
                "ERR_FEDERAL_AGENCY_MISMATCH",
                "A %s crossing must be handled by %s."
                % (segment["federal_crossing_kind"], " or ".join(allowed)),
            )
        derive.apply(segment, federal_permit_status="APPLIED", federal_permit_agency=agency)
    elif action == "ISSUE":
        derive.apply(segment, federal_permit_status="ISSUED")
    else:
        derive.apply(segment, federal_permit_status="DENIED")
        derive.suspend_activities(
            derive.activities_of_segment(segment["id"]), "FEDERAL_PERMIT_DENIED"
        )

    _ = determination_note
    return resp.created(segment)


@bp.post("/siting/routes/<route_id>/constraint-mapping")
@endpoint(["RouteAnalyst"])
def constraint_mapping(route_id):
    route = find_path(store.routes, route_id)
    body = get_body()
    opt_str(body, "mapping_note")

    if route["status"] in ROUTE_TERMINAL:
        raise ApiError("ERR_TERMINAL_STATE", "The route is already %s." % route["status"])
    if route["status"] not in ("DRAFT", "CONSTRAINT_MAPPED", "REFINING"):
        raise ApiError("ERR_INVALID_STATE", "No mapping transition leaves %s." % route["status"])

    segments = derive.segments_of_route(route_id)
    for segment in segments:
        if segment["federal_crossing_kind"] != "NONE" and segment["federal_permit_status"] == "DENIED":
            raise ApiError(
                "ERR_INVALID_STATE",
                "A segment's federal crossing permit was denied; the corridor is not mappable.",
            )

    indices = sorted(s["sequence_index"] for s in segments)
    if len(segments) < 2 or indices != list(range(1, len(segments) + 1)):
        raise ApiError(
            "ERR_SEGMENT_SEQUENCE_GAP",
            "Mapping requires at least two segments numbered contiguously from 1.",
        )

    project = store.projects[route["project_id"]]
    preliminary, certified, total_miles, density = calc.route_constraint_score(project, segments)
    derive.apply(
        route,
        segment_count=len(segments),
        total_miles=total_miles,
        unsurveyed_segment_count=sum(1 for s in segments if s["survey_status"] == "DESKTOP"),
        constraint_score_preliminary=preliminary,
        constraint_score_certified=certified,
        constraint_density_certified=density,
        status="CONSTRAINT_MAPPED",
    )
    return resp.created(route)


@bp.post("/siting/routes/<route_id>/publication")
@endpoint(["Developer"])
def publish_route(route_id):
    route = find_path(store.routes, route_id)
    body = get_body()
    comment_window_days = req_int(body, "comment_window_days", minimum=30, maximum=90)

    if route["status"] in ROUTE_TERMINAL:
        raise ApiError("ERR_TERMINAL_STATE", "The route is already %s." % route["status"])
    if route["kind"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", "Only a PROPOSED route may be published for comment.")
    if route["status"] != "CONSTRAINT_MAPPED":
        raise ApiError("ERR_INVALID_STATE", "No publication transition leaves %s." % route["status"])
    if route["constraint_score_certified"] is None:
        raise ApiError("ERR_INVALID_STATE", "The route has no certified constraint score.")

    derive.apply(
        route,
        comment_window_closes_at=store.now() + timedelta(days=comment_window_days),
        status="PUBLISHED_FOR_COMMENT",
    )
    return resp.created(route)


@bp.post("/siting/routes/<route_id>/open-houses")
@endpoint(["Developer"])
def record_open_house(route_id):
    route = find_path(store.routes, route_id)
    body = get_body()
    county = req_str(body, "county")
    req_int(body, "attendee_count", minimum=0)
    opt_dt(body, "held_at")

    counties = list(route["open_house_counties"])
    if county not in counties:
        counties.append(county)
    derive.apply(
        route,
        open_house_held_count=route["open_house_held_count"] + 1,
        open_house_counties=counties,
    )
    return resp.created(route)


@bp.post("/siting/routes/<route_id>/refinements")
@endpoint(["RouteAnalyst"])
def refine_route(route_id):
    route = find_path(store.routes, route_id)
    body = get_body()
    req_str(body, "refinement_note")

    if route["status"] in ROUTE_TERMINAL:
        raise ApiError("ERR_TERMINAL_STATE", "The route is already %s." % route["status"])
    if route["status"] not in ("PUBLISHED_FOR_COMMENT", "REFINING"):
        raise ApiError("ERR_ROUTE_NOT_PUBLISHED", "The route is not published for comment.")
    if route["status"] == "REFINING":
        raise ApiError("ERR_INVALID_STATE", "The route is already being refined.")
    if route["refinement_round"] >= calc.MAX_REFINEMENT_ROUNDS:
        raise ApiError(
            "ERR_REFINEMENT_LIMIT_REACHED",
            "The route has already completed %d refinement cycles." % calc.MAX_REFINEMENT_ROUNDS,
        )

    candidates = [s for s in derive.segments_of_route(route_id) if s["material_comment_count"] >= 1]
    if not candidates:
        raise ApiError("ERR_NO_REFINEMENT_TARGET", "No segment carries a material comment.")

    target = sorted(
        candidates,
        key=lambda s: (
            -s["material_comment_count"],
            -s["environmental_rating"],
            s["sequence_index"],
        ),
    )[0]

    derive.apply(
        target,
        survey_status="FIELD_VERIFIED",
        refinement_count=target["refinement_count"] + 1,
    )
    for comment in derive.comments_of_segment(target["id"]):
        if comment["status"] in ("RECEIVED", "ACKNOWLEDGED"):
            derive.apply(comment, status="INCORPORATED")
    derive.recompute_segment_material_count(target)

    derive.apply(
        route,
        refinement_target_segment_id=target["id"],
        refinement_round=route["refinement_round"] + 1,
        status="REFINING",
    )
    return resp.created(route)


@bp.post("/siting/routes/<route_id>/nomination")
@endpoint(["Developer"])
def nominate_route(route_id):
    route = find_path(store.routes, route_id)
    body = get_body()
    opt_str(body, "nomination_note")

    if route["status"] in ROUTE_TERMINAL:
        raise ApiError("ERR_TERMINAL_STATE", "The route is already %s." % route["status"])

    proposed = route["kind"] == "PROPOSED"
    required_status = "PUBLISHED_FOR_COMMENT" if proposed else "CONSTRAINT_MAPPED"
    if route["status"] != required_status:
        raise ApiError(
            "ERR_INVALID_STATE",
            "A %s route is nominated out of %s, not %s."
            % (route["kind"], required_status, route["status"]),
        )

    if proposed:
        closes_at = route["comment_window_closes_at"]
        if closes_at is None or store.now() < closes_at:
            raise ApiError("ERR_COMMENT_WINDOW_OPEN", "The comment window has not closed yet.")

    density = route["constraint_density_certified"]
    if density is None or calc.D(density) > calc.DENSITY_LIMIT:
        raise ApiError(
            "ERR_CONSTRAINT_DENSITY_EXCEEDED",
            "constraint_density_certified must be no greater than %s." % calc.DENSITY_LIMIT,
        )

    if proposed:
        if route["open_house_held_count"] < 2 or len(route["open_house_counties"]) < 2:
            raise ApiError(
                "ERR_OPEN_HOUSE_COVERAGE_INSUFFICIENT",
                "At least two open houses across two distinct counties are required.",
            )
        open_material = [
            c
            for c in derive.comments_of_route(route_id)
            if c["materiality"] == "MATERIAL" and c["status"] == "RECEIVED"
        ]
        if open_material:
            raise ApiError(
                "ERR_MATERIAL_COMMENTS_OPEN", "Material comments are still awaiting disposition."
            )

    derive.apply(route, status="NOMINATED")
    return resp.created(route)
