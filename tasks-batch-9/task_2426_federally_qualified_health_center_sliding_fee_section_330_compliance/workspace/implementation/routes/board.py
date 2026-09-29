"""The governing board roster."""

from flask import Blueprint

import db
import serializers
from errors import ApiError
from middleware import ALL_ROLES, authorize
from response import object_response
from routes.common import listing, owner_ref, require, state
from services import health_center as hc_svc
from validation import Field, pagination, parse_body

bp = Blueprint("board", __name__)

MAX_BOARD_SEATS = 25

SEAT_FIELDS = [
    Field("health_center_id", "string"),
    Field("seat_number", "integer", required=True, minimum=1),
    Field("seat_type", "enum", required=True, enum=("PATIENT", "NON_PATIENT")),
    Field("patient_id", "string", nullable=True),
    Field(
        "expertise_category",
        "enum",
        enum=("FINANCE", "LEGAL", "COMMUNITY", "HEALTH_PROFESSION"),
        nullable=True,
    ),
    Field("derives_over_10pct_income_from_healthcare", "boolean"),
    Field("term_start", "datetime", required=True),
    Field("term_end", "datetime", required=True),
]


def _patient_seen_at_grantee(patient_id, hc_id):
    for enc in db.db.encounters.values():
        if enc["patient_id"] != patient_id or enc["pps_claim_status"] == "VOID":
            continue
        site = db.db.service_sites.get(enc["service_site_id"])
        if site is not None and site["health_center_id"] == hc_id:
            return True
    return False


@bp.post("/health-centers/<hc_id>/board-members")
def seat_board_member(hc_id):
    authorize("ComplianceOfficer")
    body = parse_body(SEAT_FIELDS)
    hc = require("health_centers", hc_id)
    owner_ref(body, "health_center_id", "health_centers", hc_id)

    patient_id = body.get("patient_id")
    if patient_id is not None:
        require("patients", patient_id)
        # Rung 8 — a board seat's patient must have been seen at this grantee.
        if not _patient_seen_at_grantee(patient_id, hc_id):
            raise ApiError("ERR_CROSS_GRANTEE_REFERENCE")

    # Rung 22 — closed term ordering.
    if body["term_start"] > body["term_end"]:
        raise ApiError("ERR_INVALID_TERM")

    # Rung 25 — seat exclusivity; closed terms make adjacency an overlap.
    for member in hc_svc.board_of(hc_id):
        if member["status"] != "SEATED" or member["seat_number"] != body["seat_number"]:
            continue
        if member["term_start"] <= body["term_end"] and body["term_start"] <= member["term_end"]:
            raise ApiError("ERR_BOARD_SEAT_OVERLAP")

    # Rung 30 — conditional seat fields.
    seat_type = body["seat_type"]
    expertise = body.get("expertise_category")
    healthcare = body.get("derives_over_10pct_income_from_healthcare", False)
    if seat_type == "PATIENT":
        if patient_id is None or expertise is not None or healthcare:
            raise ApiError("ERR_SEAT_FIELD_MISMATCH")
    else:
        if expertise is None or patient_id is not None:
            raise ApiError("ERR_SEAT_FIELD_MISMATCH")

    # Rung 39 — roster ceiling.
    if hc_svc.seated_board_count(hc_id) + 1 > MAX_BOARD_SEATS:
        raise ApiError("ERR_BOARD_SEAT_LIMIT")

    row = db.base_row()
    row.update(
        {
            "health_center_id": hc_id,
            "seat_number": body["seat_number"],
            "seat_type": seat_type,
            "patient_id": patient_id,
            "expertise_category": expertise,
            "derives_over_10pct_income_from_healthcare": healthcare,
            "term_start": body["term_start"],
            "term_end": body["term_end"],
            "status": "SEATED",
            "resignation_date": None,
        }
    )
    db.db.board_members[row["id"]] = row

    hc_svc.bump(hc)
    return object_response(serializers.board_member(row), 201)


@bp.get("/board-members/<member_id>")
def read_board_member(member_id):
    authorize(*ALL_ROLES)
    return object_response(serializers.board_member(require("board_members", member_id)))


@bp.get("/board-members")
def list_board_members():
    authorize(*ALL_ROLES)
    limit, offset = pagination()
    return listing(
        db.all_rows("board_members"),
        serializers.board_member,
        limit,
        offset,
        specs=[
            ("health_center_id", "health_center_id", "string"),
            ("patient_id", "patient_id", "string"),
            ("status", "status", "string"),
            ("seat_type", "seat_type", "string"),
            ("seat_number", "seat_number", "integer"),
        ],
    )


@bp.post("/board-members/<member_id>/resign")
def resign_board_member(member_id):
    authorize("ComplianceOfficer")
    body = parse_body([Field("resignation_date", "datetime", required=True)])
    member = require("board_members", member_id)

    state(member, "status", ("SEATED",))
    if body["resignation_date"] < member["term_start"]:
        raise ApiError("ERR_INVALID_TERM")

    member["status"] = "RESIGNED"
    member["resignation_date"] = body["resignation_date"]
    member["term_end"] = body["resignation_date"]
    db.touch(member)

    hc = db.db.health_centers.get(member["health_center_id"])
    if hc is not None:
        hc_svc.bump(hc)
    return object_response(serializers.board_member(member))
