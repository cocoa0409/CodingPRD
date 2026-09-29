"""Sliding fee discount schedules and their FPG discount tiers."""

from flask import Blueprint, request

import db
import serializers
from errors import ApiError
from middleware import ALL_ROLES, authorize
from response import object_response
from routes.common import listing, owner_ref, require, seated_chair, state
from services import fee_schedule as fs
from services import health_center as hc_svc
from validation import Field, pagination, parse_body

bp = Blueprint("fees", __name__)

SCHEDULE_FIELDS = [
    Field("health_center_id", "string"),
    Field("fpg_year", "integer", required=True, minimum=2000, maximum=2100),
    Field("effective_start", "datetime", required=True),
    Field("effective_end", "datetime", required=True),
    Field("nominal_fee_cents", "integer", required=True, minimum=0),
    Field("board_vote_date", "datetime", nullable=True),
]

TIER_FIELDS = [
    Field("fee_schedule_id", "string"),
    Field("tier_label", "string", required=True),
    Field("fpg_min_pct", "number", required=True, minimum=0),
    Field("fpg_max_pct", "number", nullable=True, minimum=0),
    Field("discount_kind", "enum", required=True, enum=("NOMINAL", "PERCENT_DISCOUNT", "NONE")),
    Field("discount_pct", "number", nullable=True, exclusive_min=0, exclusive_max=1),
    Field("sort_order", "integer", required=True, minimum=1),
]


# --------------------------------------------------------------------------- #
# fee schedules
# --------------------------------------------------------------------------- #


@bp.post("/health-centers/<hc_id>/fee-schedules")
def create_fee_schedule(hc_id):
    authorize("ComplianceOfficer")
    body = parse_body(SCHEDULE_FIELDS)
    require("health_centers", hc_id)
    owner_ref(body, "health_center_id", "health_centers", hc_id)

    # Rung 21 — half-open period ordering.
    if body["effective_start"] >= body["effective_end"]:
        raise ApiError("ERR_INVALID_PERIOD")

    row = db.base_row()
    row.update(
        {
            "health_center_id": hc_id,
            "fpg_year": body["fpg_year"],
            "effective_start": body["effective_start"],
            "effective_end": body["effective_end"],
            "nominal_fee_cents": body["nominal_fee_cents"],
            "status": "DRAFT",
            "board_vote_date": body.get("board_vote_date"),
            "adopted_at": None,
            "adopted_by_user_id": None,
            "last_reviewed_at": None,
            "reviewed_against_guideline_year": None,
            "superseded_by_fee_schedule_id": None,
        }
    )
    db.db.fee_schedules[row["id"]] = row
    return object_response(serializers.fee_schedule(row), 201)


@bp.get("/fee-schedules/<schedule_id>")
def read_fee_schedule(schedule_id):
    authorize(*ALL_ROLES)
    return object_response(serializers.fee_schedule(require("fee_schedules", schedule_id)))


@bp.get("/fee-schedules")
def list_fee_schedules():
    authorize(*ALL_ROLES)
    limit, offset = pagination()

    wanted_review = request.args.get("review_status")

    def predicate(row):
        if wanted_review is not None and fs.review_status(row) != wanted_review:
            return False
        return True

    return listing(
        db.all_rows("fee_schedules"),
        serializers.fee_schedule,
        limit,
        offset,
        specs=[
            ("health_center_id", "health_center_id", "string"),
            (
                "superseded_by_fee_schedule_id",
                "superseded_by_fee_schedule_id",
                "string",
            ),
            ("status", "status", "string"),
            ("fpg_year", "fpg_year", "integer"),
        ],
        predicate=predicate,
    )


@bp.post("/fee-schedules/<schedule_id>/adopt")
def adopt_fee_schedule(schedule_id):
    user_id = authorize("BoardChair")
    body = parse_body([Field("expected_health_center_version", "integer", required=True)])
    schedule = require("fee_schedules", schedule_id)
    hc = db.db.health_centers.get(schedule["health_center_id"])
    if hc is None:
        raise ApiError("ERR_HEALTH_CENTER_NOT_FOUND")

    # Rung 10 — OCC on the grantee.
    if body["expected_health_center_version"] != hc["version"]:
        raise ApiError("ERR_STALE_HEALTH_CENTER_VERSION")

    state(schedule, "status", ("DRAFT",))
    seated_chair(user_id, hc["id"])

    # Rung 24 — period exclusivity on the half-open convention; an identical
    # effective_start supersedes instead of colliding.
    same_start = []
    for other in db.in_creation_order(hc_svc.schedules_of(hc["id"])):
        if other["id"] == schedule_id or other["status"] != "ADOPTED":
            continue
        overlaps = (
            other["effective_start"] < schedule["effective_end"]
            and schedule["effective_start"] < other["effective_end"]
        )
        if not overlaps:
            continue
        if other["effective_start"] == schedule["effective_start"]:
            same_start.append(other)
        else:
            raise ApiError("ERR_FEE_SCHEDULE_PERIOD_OVERLAP")

    # Rung 32 — the whole tier ladder is validated here.
    if not fs.ladder_is_well_formed(schedule_id):
        raise ApiError("ERR_TIER_BANDS_INVALID")

    # Rung 37 — the guideline year the tiers were built from must exist.
    if fs.guideline_for_year(schedule["fpg_year"]) is None:
        raise ApiError("ERR_POVERTY_GUIDELINE_MISSING")

    # Rung 41 — the nominal fee may not exceed the grantee's cap.
    if schedule["nominal_fee_cents"] > hc["nominal_fee_cap_cents"]:
        raise ApiError("ERR_NOMINAL_FEE_ABOVE_CAP")

    clock = db.now()
    schedule["status"] = "ADOPTED"
    schedule["adopted_at"] = clock
    schedule["last_reviewed_at"] = clock
    schedule["adopted_by_user_id"] = user_id
    schedule["reviewed_against_guideline_year"] = schedule["fpg_year"]
    db.touch(schedule)

    for other in same_start:
        other["status"] = "SUPERSEDED"
        other["superseded_by_fee_schedule_id"] = schedule_id
        db.touch(other)

    hc_svc.bump(hc)
    return object_response(serializers.fee_schedule(schedule))


@bp.post("/fee-schedules/<schedule_id>/annual-review")
def annual_review(schedule_id):
    authorize("ComplianceOfficer")
    body = parse_body(
        [
            Field(
                "reviewed_against_guideline_year",
                "integer",
                required=True,
                minimum=2000,
                maximum=2100,
            )
        ]
    )
    schedule = require("fee_schedules", schedule_id)

    schedule["last_reviewed_at"] = db.now()
    schedule["reviewed_against_guideline_year"] = body["reviewed_against_guideline_year"]
    db.touch(schedule)
    return object_response(serializers.fee_schedule(schedule))


# --------------------------------------------------------------------------- #
# discount tiers
# --------------------------------------------------------------------------- #


@bp.post("/fee-schedules/<schedule_id>/discount-tiers")
def create_discount_tier(schedule_id):
    authorize("ComplianceOfficer")
    body = parse_body(TIER_FIELDS)
    require("fee_schedules", schedule_id)
    owner_ref(body, "fee_schedule_id", "fee_schedules", schedule_id)

    # Rung 29 — tier_label and sort_order are unique within the schedule.
    for existing in fs.tiers_of(schedule_id):
        if existing["tier_label"] == body["tier_label"]:
            raise ApiError("ERR_DUPLICATE_CHILD_KEY")
        if existing["sort_order"] == body["sort_order"]:
            raise ApiError("ERR_DUPLICATE_CHILD_KEY")

    # Rung 31 — conditional tier fields.
    discount_kind = body["discount_kind"]
    discount_pct = body.get("discount_pct")
    if discount_kind == "PERCENT_DISCOUNT":
        if discount_pct is None:
            raise ApiError("ERR_TIER_DISCOUNT_MISMATCH")
    elif discount_pct is not None:
        raise ApiError("ERR_TIER_DISCOUNT_MISMATCH")

    row = db.base_row()
    row.update(
        {
            "fee_schedule_id": schedule_id,
            "tier_label": body["tier_label"],
            "fpg_min_pct": body["fpg_min_pct"],
            "fpg_max_pct": body.get("fpg_max_pct"),
            "discount_kind": discount_kind,
            "discount_pct": discount_pct,
            "sort_order": body["sort_order"],
        }
    )
    db.db.discount_tiers[row["id"]] = row
    return object_response(serializers.discount_tier(row), 201)


@bp.get("/discount-tiers/<tier_id>")
def read_discount_tier(tier_id):
    authorize(*ALL_ROLES)
    return object_response(serializers.discount_tier(require("discount_tiers", tier_id)))


@bp.get("/fee-schedules/<schedule_id>/discount-tiers")
def list_discount_tiers(schedule_id):
    authorize(*ALL_ROLES)
    limit, offset = pagination()
    require("fee_schedules", schedule_id)
    return listing(fs.tiers_of(schedule_id), serializers.discount_tier, limit, offset)
