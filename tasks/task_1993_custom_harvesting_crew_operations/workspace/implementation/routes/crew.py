"""CrewMember endpoints (§3.3)."""

from flask import Blueprint, request

from db import db
from errors import (
    ApiError,
    ERR_CREW_NOT_ONBOARDED,
    ERR_CREW_NOT_ACTIVE,
    ERR_ACTIVE_LODGING_EXISTS,
    ERR_VISA_EXPIRED,
    ERR_SEASON_NOT_OPEN_FOR_COMMIT,
)
from helpers import (
    get_json_body,
    require_fields,
    require_type,
    require_enum,
    optional_type,
    is_bool,
    parse_date,
    logical_clock_date,
    stamp_new,
    touch,
    public,
    sort_key,
    get_season_or_404,
    get_crew_or_404,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list, parse_pagination, paginate

bp = Blueprint("crew", __name__)

VISA_TYPES = ("US_CITIZEN", "H2A", "TN", "PERMANENT_RESIDENT")


@bp.route("/harvest/seasons/<seasonId>/crew-members", methods=["POST"])
def create_crew_member(seasonId):
    require_roles("HarvestOperator")
    season = get_season_or_404(seasonId)
    body = get_json_body()
    require_fields(
        body, ["full_name", "visa_type", "visa_expiry_date", "hourly_rate_cents"]
    )
    full_name = require_type(body, "full_name", "string")
    visa_type = require_enum(body, "visa_type", VISA_TYPES)
    visa_expiry_date = require_type(body, "visa_expiry_date", "string")
    # Validate the date form when provided (required for H2A/TN; ignored
    # otherwise, but still must be well-formed when supplied).
    parse_date(visa_expiry_date, "visa_expiry_date")
    hourly_rate_cents = require_type(body, "hourly_rate_cents", "int")
    requires_housing = body.get("requires_housing", True)
    if not is_bool(requires_housing):
        from errors import ERR_INVALID_REQUEST
        raise ApiError(ERR_INVALID_REQUEST, 400, "requires_housing must be a boolean")

    record = stamp_new(
        {
            "season_id": season["id"],
            "full_name": full_name,
            "visa_type": visa_type,
            "visa_expiry_date": visa_expiry_date,
            "hourly_rate_cents": hourly_rate_cents,
            "requires_housing": requires_housing,
            "status": "ONBOARDED",
        }
    )
    db.crew_members[record["id"]] = record
    return success_object(public(record), status=201)


@bp.route("/harvest/seasons/<seasonId>/crew-members", methods=["GET"])
def list_crew_for_season(seasonId):
    require_roles(*ALL_ROLES)
    season = get_season_or_404(seasonId)
    pagination = parse_pagination(request.args)
    items = [c for c in db.crew_members.values() if c["season_id"] == season["id"]]
    items.sort(key=sort_key)
    page, pag = paginate(items, pagination)
    return success_list([public(r) for r in page], pag)


@bp.route("/harvest/crew-members", methods=["GET"])
def list_crew_members():
    require_roles(*ALL_ROLES)
    pagination = parse_pagination(request.args)
    season_id = request.args.get("season_id")
    items = list(db.crew_members.values())
    if season_id is not None:
        items = [c for c in items if c["season_id"] == season_id]
    items.sort(key=sort_key)
    page, pag = paginate(items, pagination)
    return success_list([public(r) for r in page], pag)


@bp.route("/harvest/crew-members/<crewId>", methods=["GET"])
def get_crew_member(crewId):
    require_roles(*ALL_ROLES)
    crew = get_crew_or_404(crewId)
    return success_object(public(crew))


@bp.route("/harvest/crew-members/<crewId>/activate", methods=["POST"])
def activate_crew(crewId):
    require_roles("HarvestOperator")
    crew = get_crew_or_404(crewId)
    if crew["status"] != "ONBOARDED":
        raise ApiError(ERR_CREW_NOT_ONBOARDED, 409, "activate requires crew ONBOARDED")
    season = get_season_or_404(crew["season_id"])
    if season["status"] not in ("DRAFT", "ACTIVE"):
        raise ApiError(
            ERR_SEASON_NOT_OPEN_FOR_COMMIT,
            409,
            "Crew activation requires season DRAFT or ACTIVE",
        )
    # Visa safety gate (priority 5): H2A/TN expiry must be strictly greater
    # than the current logical date.
    if crew["visa_type"] in ("H2A", "TN"):
        expiry = parse_date(crew["visa_expiry_date"], "visa_expiry_date")
        if expiry <= logical_clock_date():
            raise ApiError(
                ERR_VISA_EXPIRED,
                422,
                "H2A/TN visa_expiry_date is not strictly greater than the current logical date",
            )
    crew["status"] = "ACTIVE"
    touch(crew)
    return success_object(public(crew))


@bp.route("/harvest/crew-members/<crewId>/release", methods=["POST"])
def release_crew(crewId):
    require_roles("HarvestOperator")
    crew = get_crew_or_404(crewId)
    if crew["status"] != "ACTIVE":
        raise ApiError(ERR_CREW_NOT_ACTIVE, 409, "release requires crew ACTIVE")
    today = logical_clock_date()
    # Blocked while the member holds ANY reservation in BOOKED or
    # CHECKED_IN status overlapping any future date (a stay whose end date
    # falls after the current logical date).
    for r in db.lodging_reservations.values():
        if r["crew_member_id"] != crew["id"]:
            continue
        if r["status"] not in ("BOOKED", "CHECKED_IN"):
            continue
        stay_end = parse_date(r["stay_end_date"], "stay_end_date")
        if stay_end > today:
            raise ApiError(
                ERR_ACTIVE_LODGING_EXISTS,
                409,
                "release blocked by future BOOKED/CHECKED_IN reservation",
            )
    crew["status"] = "RELEASED"
    touch(crew)
    # Side effect: all future BOOKED reservations for this member → CANCELLED.
    # (Reachable only when none overlap a future date, per the gate above;
    # cancel any remaining BOOKED reservations whose stay is entirely past
    # for defensive consistency.)
    for r in db.lodging_reservations.values():
        if r["crew_member_id"] == crew["id"] and r["status"] == "BOOKED":
            r["status"] = "CANCELLED"
            touch(r)
    return success_object(public(crew))
