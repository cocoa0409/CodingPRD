"""Auditoriums, distributors, titles and the logical clock (PRD 3.1, 2.4)."""
from flask import Blueprint

import serialize
from auth import (ROLE_ANON, ROLE_BOX, ROLE_EXEC, ROLE_MEMBER, ROLE_PROGRAMMER,
                  ROLE_RIGHTS, ROLE_TECH, PUBLIC_READ, authorize)
from errors import ApiError
from response import object_response, paged
from store import new_record, ordered, set_clock
from timeutil import fmt_instant
from validate import (FORMATS, TERMS_VARIANTS, bad, body, insert, must_find,
                      opt_bool, opt_int, opt_positive_share, opt_signed_int,
                      query_bool, query_str, req_bool, req_enum, req_format_list,
                      req_hhmm, req_id, req_instant, req_int, req_share, req_str,
                      rows)

bp = Blueprint("catalog", __name__)

STAFF = (ROLE_PROGRAMMER, ROLE_RIGHTS, ROLE_TECH, ROLE_BOX, ROLE_EXEC)


@bp.post("/venues")
def create_venue():
    authorize((ROLE_EXEC,))
    payload = body()
    seat_capacity = req_int(payload, "seat_capacity", minimum=1)
    house_hold_seats = opt_int(payload, "house_hold_seats", 0, minimum=0)
    if house_hold_seats >= seat_capacity:
        raise bad("house_hold_seats must be strictly less than seat_capacity.")
    row = new_record(
        name=req_str(payload, "name"),
        seat_capacity=seat_capacity,
        house_hold_seats=house_hold_seats,
        trailer_reel_minutes=req_int(payload, "trailer_reel_minutes", minimum=0),
        turnaround_minutes=req_int(payload, "turnaround_minutes", minimum=0),
        min_useful_gap_minutes=opt_int(payload, "min_useful_gap_minutes", 45, minimum=0),
        dcp_ingest_lane_count=req_int(payload, "dcp_ingest_lane_count", minimum=1),
        open_local_time=req_hhmm(payload, "open_local_time"),
        last_start_local_time=req_hhmm(payload, "last_start_local_time"),
        utc_offset_minutes=opt_signed_int(payload, "utc_offset_minutes", 0),
        max_first_run_share=opt_positive_share(payload, "max_first_run_share", 0.60),
        weekly_repertory_target=opt_int(payload, "weekly_repertory_target", 6, minimum=0),
        supported_formats=req_format_list(payload, "supported_formats"),
        base_house_nut_weekly_cents=opt_int(payload, "base_house_nut_weekly_cents",
                                            480000, minimum=0),
    )
    insert("venues", row)
    return object_response(serialize.venue(row), 201)


@bp.get("/venues/<venue_id>")
def read_venue(venue_id):
    authorize(PUBLIC_READ)
    return object_response(serialize.venue(must_find("venues", venue_id)))


@bp.post("/distributors")
def create_distributor():
    authorize((ROLE_PROGRAMMER, ROLE_EXEC))
    payload = body()
    row = new_record(
        name=req_str(payload, "name"),
        contact_email=req_str(payload, "contact_email"),
        default_terms_variant=req_enum(payload, "default_terms_variant", TERMS_VARIANTS),
        default_min_run_days=req_int(payload, "default_min_run_days", minimum=1),
        default_distributor_share_pct=req_share(payload, "default_distributor_share_pct"),
        requires_advance_guarantee=opt_bool(payload, "requires_advance_guarantee", False),
    )
    insert("distributors", row)
    return object_response(serialize.distributor(row), 201)


@bp.get("/distributors/<distributor_id>")
def read_distributor(distributor_id):
    authorize((ROLE_PROGRAMMER, ROLE_RIGHTS, ROLE_BOX, ROLE_EXEC))
    return object_response(serialize.distributor(must_find("distributors", distributor_id)))


@bp.post("/titles")
def create_title():
    authorize((ROLE_PROGRAMMER, ROLE_EXEC))
    payload = body()
    title_name = req_str(payload, "title_name")
    release_year = req_int(payload, "release_year", minimum=0)
    runtime_minutes = req_int(payload, "runtime_minutes", minimum=1)
    is_first_run = req_bool(payload, "is_first_run")
    native_format = req_enum(payload, "native_format", FORMATS)
    distributor_id = req_id(payload, "rights_holder_distributor_id")
    must_find("distributors", distributor_id)
    row = new_record(
        title_name=title_name,
        release_year=release_year,
        runtime_minutes=runtime_minutes,
        is_first_run=is_first_run,
        native_format=native_format,
        rights_holder_distributor_id=distributor_id,
    )
    insert("titles", row)
    return object_response(serialize.title(row), 201)


@bp.get("/titles/<title_id>")
def read_title(title_id):
    authorize(PUBLIC_READ)
    return object_response(serialize.title(must_find("titles", title_id)))


@bp.get("/titles")
def list_titles():
    authorize(PUBLIC_READ)
    holder = query_str("rights_holder_distributor_id")
    first_run = query_bool("is_first_run")
    found = rows("titles")
    if holder is not None:
        found = [t for t in found if t["rights_holder_distributor_id"] == holder]
    if first_run is not None:
        found = [t for t in found if t["is_first_run"] == first_run]
    return paged(ordered(found), serialize.title)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authorize((ROLE_EXEC,))
    payload = body()
    instant = req_instant(payload, "current_utc")
    set_clock(instant)
    return object_response({"current_utc": fmt_instant(instant)})
