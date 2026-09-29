"""Public comment intake and disposition (PRD §3.4)."""

from flask import Blueprint, g

import response as resp
from db import insert, store
from errors import ApiError
from middleware import ALL_ROLES, endpoint
from services import derive
from validation import (
    collection_list,
    find_path,
    fk,
    get_body,
    must_be_absent,
    opt_id,
    req_enum,
    req_id,
    req_str,
)

bp = Blueprint("comments", __name__)

COMMENTER_KINDS = ("LANDOWNER", "AGENCY", "PUBLIC")
MATERIALITIES = ("MATERIAL", "GENERAL")
DISPOSITIONS = ("ACKNOWLEDGE", "DISMISS")
OPEN_ROUTE_STATUSES = ("PUBLISHED_FOR_COMMENT", "REFINING")
COMMENT_TERMINAL = ("INCORPORATED", "DISMISSED")


@bp.get("/siting/public-comments")
@endpoint(ALL_ROLES)
def list_comments():
    rows, pagination = collection_list(
        store.public_comments,
        ["route_id", "segment_id", "commenter_landowner_id", "materiality", "status"],
    )
    return resp.listing(rows, pagination)


@bp.get("/siting/public-comments/<comment_id>")
@endpoint(ALL_ROLES)
def read_comment(comment_id):
    return resp.ok(find_path(store.public_comments, comment_id))


@bp.post("/siting/public-comments")
@endpoint(["Landowner", "RouteAnalyst", "CommissionStaff"])
def create_comment():
    body = get_body()

    # tier 4 — body references
    route = fk(body, "route_id", store.routes)
    segment = fk(body, "segment_id", store.route_segments)
    fk(body, "commenter_landowner_id", store.landowners)

    # tier 5 — shape
    route_id = req_id(body, "route_id")
    commenter_kind = req_enum(body, "commenter_kind", COMMENTER_KINDS)
    commenter_name = req_str(body, "commenter_name")
    text = req_str(body, "body")
    materiality = req_enum(body, "materiality", MATERIALITIES)
    segment_id = opt_id(body, "segment_id")
    if materiality == "MATERIAL" and segment_id is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'segment_id' is required for a MATERIAL comment.")
    if commenter_kind == "LANDOWNER":
        commenter_landowner_id = req_id(body, "commenter_landowner_id")
    else:
        must_be_absent(body, "commenter_landowner_id", "unless commenter_kind is LANDOWNER")
        commenter_landowner_id = None

    # tier 6 — landowner ownership
    if g.role == "Landowner" and commenter_landowner_id != g.user_id:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER", "A landowner may only file a comment under their own identifier."
        )

    # tier 10/12 — the route must be taking comment
    if route["status"] not in OPEN_ROUTE_STATUSES:
        raise ApiError("ERR_ROUTE_NOT_PUBLISHED", "The route is not open for public comment.")

    # tier 14 — the window
    closes_at = route["comment_window_closes_at"]
    if closes_at is not None and store.now() >= closes_at:
        raise ApiError("ERR_COMMENT_WINDOW_CLOSED", "The comment window has closed.")

    # tier 15 — cross-family belonging, checked last
    if segment is not None and segment["route_id"] != route_id:
        raise ApiError(
            "ERR_ROUTE_PROJECT_MISMATCH", "The named segment does not belong to the named route."
        )

    row = insert(
        store.public_comments,
        {
            "route_id": route_id,
            "segment_id": segment_id,
            "commenter_landowner_id": commenter_landowner_id,
            "commenter_kind": commenter_kind,
            "commenter_name": commenter_name,
            "body": text,
            "materiality": materiality,
            "status": "RECEIVED",
            "received_at": store.now(),
            "disposition_note": None,
        },
    )
    if segment is not None and materiality == "MATERIAL":
        derive.recompute_segment_material_count(segment)
    return resp.created(row)


@bp.post("/siting/public-comments/<comment_id>/disposition")
@endpoint(["RouteAnalyst"])
def disposition_comment(comment_id):
    comment = find_path(store.public_comments, comment_id)
    body = get_body()
    disposition = req_enum(body, "disposition", DISPOSITIONS)
    disposition_note = req_str(body, "disposition_note")

    if comment["status"] in COMMENT_TERMINAL:
        raise ApiError("ERR_TERMINAL_STATE", "The comment is already %s." % comment["status"])
    if disposition == "ACKNOWLEDGE" and comment["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE", "Only a RECEIVED comment may be acknowledged.")

    route = store.routes.get(comment["route_id"])
    if route is None or route["status"] not in OPEN_ROUTE_STATUSES:
        raise ApiError("ERR_ROUTE_NOT_PUBLISHED", "The route is not open for public comment.")

    target = "ACKNOWLEDGED" if disposition == "ACKNOWLEDGE" else "DISMISSED"
    derive.apply(comment, status=target, disposition_note=disposition_note)

    segment = store.route_segments.get(comment["segment_id"]) if comment["segment_id"] else None
    if segment is not None and comment["materiality"] == "MATERIAL":
        derive.recompute_segment_material_count(segment)
    return resp.created(comment)
