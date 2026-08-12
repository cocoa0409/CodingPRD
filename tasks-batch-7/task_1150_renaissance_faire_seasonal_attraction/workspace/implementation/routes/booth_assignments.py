"""BoothAssignment endpoints."""
from flask import Blueprint

from db import store, new_id, next_seq, clock_now
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_BOOTH_NOT_FOUND,
    ERR_APPLICATION_NOT_FOUND,
    ERR_APPLICATION_NOT_JURIED_IN,
    ERR_SEASON_INVALID_STATE,
    ERR_APPLICATION_ALREADY_BOOKED,
    ERR_BOOTH_OVERLAP,
    ERR_BOOTH_NOT_CONFIRMABLE,
    ERR_BOOTH_NOT_RELEASEABLE,
    ERR_BOOTH_NOT_SETTLEABLE,
    ERR_FOOD_PERMIT_NOT_ISSUED,
    conflict,
)
from middleware import (
    require_roles,
    require_owner,
    get_body,
    load,
    parse_pagination,
    apply_filters,
    sorted_by_creation,
)
from response import obj_response, list_response
from services import (
    provisional_fee,
    settlement_fees,
    promote_waitlist,
    booths_of_application,
    BOOTH_TERMINAL,
)
from util import req, check_unknown, new_record, mutate, public_view

bp = Blueprint("booth_assignments", __name__)

CREATE_FIELDS = {"application_id", "booth_site", "residency_start_date", "residency_end_date"}
BOOTH_LIVE = {"RESERVED", "CONFIRMED", "SUSPENDED"}


def load_booth(bid):
    return load(store.booths, bid, ERR_BOOTH_NOT_FOUND, "booth assignment")


@bp.route("/booth-assignments", methods=["POST"])
def create_booth():
    require_roles("VendorCoordinator")
    body = get_body()
    if isinstance(body.get("application_id"), str):
        load(store.applications, body["application_id"], ERR_APPLICATION_NOT_FOUND, "vendor application")
    check_unknown(body, CREATE_FIELDS)
    application_id = req(body, "application_id", "str")
    booth_site = req(body, "booth_site", "str")
    start = req(body, "residency_start_date", "dt")
    end = req(body, "residency_end_date", "dt")
    if end <= start:
        raise ApiError(ERR_INVALID_REQUEST, 400, "residency_end_date must be > residency_start_date")

    application = store.applications[application_id]
    if application["status"] != "JURIED_IN":
        raise conflict(ERR_APPLICATION_NOT_JURIED_IN, "booth reservation requires JURIED_IN")
    season = store.seasons[application["season_id"]]
    if season["status"] not in ("PLANNING", "BUILD"):
        raise conflict(ERR_SEASON_INVALID_STATE, "booth reservation requires season PLANNING or BUILD")
    for other in booths_of_application(application_id):
        if other["status"] not in BOOTH_TERMINAL:
            raise conflict(
                ERR_APPLICATION_ALREADY_BOOKED,
                "application already has a non-terminal booth assignment",
            )
    for other in store.booths.values():
        if other["booth_site"] != booth_site or other["status"] not in BOOTH_LIVE:
            continue
        if start < other["residency_end_date"] and other["residency_start_date"] < end:
            raise conflict(ERR_BOOTH_OVERLAP, "booth site is occupied in that residency window")

    booth = new_record()
    booth.update(
        {
            "id": new_id(),
            "_seq": next_seq(),
            "season_id": application["season_id"],
            "application_id": application_id,
            "booth_site": booth_site,
            "residency_start_date": start,
            "residency_end_date": end,
            "status": "RESERVED",
            "provisional_fee_cents": provisional_fee(application, season),
            "weather_credit_cents": 0,
            "final_fee_cents": None,
            "settlement_delta_cents": None,
        }
    )
    store.booths[booth["id"]] = booth
    return obj_response(public_view(booth), 201)


@bp.route("/booth-assignments", methods=["GET"])
def list_booths():
    require_roles()
    limit, offset = parse_pagination()
    items = apply_filters(
        sorted_by_creation(store.booths),
        [
            ("season_id", "season_id"),
            ("application_id", "application_id"),
            ("booth_site", "booth_site"),
            ("status", "status"),
        ],
    )
    total = len(items)
    page = items[offset : offset + limit]
    return list_response([public_view(b) for b in page], limit, offset, total)


@bp.route("/booth-assignments/<bid>", methods=["GET"])
def get_booth(bid):
    require_roles()
    return obj_response(public_view(load_booth(bid)))


@bp.route("/booth-assignments/<bid>/confirm", methods=["POST"])
def confirm_booth(bid):
    uid, _ = require_roles("Vendor")
    booth = load_booth(bid)
    application = store.applications[booth["application_id"]]
    require_owner(uid == application["vendor_id"])
    check_unknown(get_body(), set())
    if booth["status"] not in ("RESERVED", "SUSPENDED"):
        raise conflict(ERR_BOOTH_NOT_CONFIRMABLE, "confirm requires RESERVED or SUSPENDED")
    vendor = store.vendors.get(application["vendor_id"])
    if vendor is not None and vendor["category"] in ("FOOD", "BEVERAGE"):
        now = clock_now()
        ok = False
        for permit in store.permits.values():
            if (
                permit["application_id"] == application["id"]
                and permit["status"] == "ISSUED"
                and permit.get("expiry_date") is not None
                and permit["expiry_date"] >= now
            ):
                ok = True
                break
        if not ok:
            raise conflict(
                ERR_FOOD_PERMIT_NOT_ISSUED,
                "FOOD/BEVERAGE booth confirm requires an ISSUED, unexpired food permit",
            )
    mutate(booth, status="CONFIRMED")
    return obj_response(public_view(booth))


@bp.route("/booth-assignments/<bid>/release", methods=["POST"])
def release_booth(bid):
    require_roles("VendorCoordinator")
    booth = load_booth(bid)
    check_unknown(get_body(), set())
    if booth["status"] != "RESERVED":
        raise conflict(ERR_BOOTH_NOT_RELEASEABLE, "release requires RESERVED")
    mutate(booth, status="RELEASED")
    season = store.seasons.get(booth["season_id"])
    if season is not None:
        promote_waitlist(season)
    return obj_response(public_view(booth))


@bp.route("/booth-assignments/<bid>/settle", methods=["POST"])
def settle_booth(bid):
    require_roles("VendorCoordinator")
    booth = load_booth(bid)
    check_unknown(get_body(), set())
    if booth["status"] not in ("CONFIRMED", "SUSPENDED"):
        raise conflict(ERR_BOOTH_NOT_SETTLEABLE, "settle requires CONFIRMED or SUSPENDED")
    season = store.seasons[booth["season_id"]]
    if season["status"] != "STRIKE":
        raise conflict(ERR_SEASON_INVALID_STATE, "settle requires season STRIKE")
    application = store.applications[booth["application_id"]]
    final_fee, delta = settlement_fees(booth, application)
    mutate(
        booth,
        status="SETTLED",
        final_fee_cents=final_fee,
        settlement_delta_cents=delta,
    )
    return obj_response(public_view(booth))
