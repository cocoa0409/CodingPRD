"""The athlete village: accommodation blocks and stays."""
from datetime import timedelta

from flask import Blueprint

import calc
import domain
import store
import web
from core import Field, as_date, authenticate, fail, parse_body
from web import PREFIX

bp = Blueprint("village", __name__)

BLOCK_FIELDS = [
    Field("games_edition_id", "id"),
    Field("name", "str"),
    Field("bed_capacity", "int", minimum=1),
    Field("nightly_rate_cents", "int", minimum=0),
    Field("accessible_units", "int", required=False, default=0, minimum=0),
]


@bp.post(PREFIX + "/accommodation-blocks")
def create_accommodation_block():
    authenticate("GamesAdmin")
    body = parse_body(BLOCK_FIELDS)
    store.must_get("games_edition", body["games_edition_id"])
    row = store.insert(
        "accommodation_block",
        {
            "games_edition_id": body["games_edition_id"],
            "name": body["name"],
            "bed_capacity": body["bed_capacity"],
            "nightly_rate_cents": body["nightly_rate_cents"],
            "accessible_units": body["accessible_units"],
            "reserved_bed_nights": 0,
        },
    )
    return web.obj(row, 201)


@bp.get(PREFIX + "/accommodation-blocks/<accommodation_block_id>")
def read_accommodation_block(accommodation_block_id):
    return web.single("accommodation_block", accommodation_block_id)


@bp.get(PREFIX + "/accommodation-blocks")
def list_accommodation_blocks():
    return web.collection("accommodation_block", ("games_edition_id",))


STAY_FIELDS = [
    Field("athlete_id", "id"),
    Field("accommodation_block_id", "id"),
    Field("check_in_date", "date"),
    Field("check_out_date", "date"),
    Field("expected_block_version", "int"),
]


def _village_window(edition):
    opens = as_date(edition["competition_start_date"]) - timedelta(
        days=calc.VILLAGE_LEAD_DAYS
    )
    closes = as_date(edition["competition_end_date"]) + timedelta(
        days=calc.VILLAGE_TRAIL_DAYS
    )
    return opens, closes


@bp.post(PREFIX + "/village-stays")
def create_village_stay():
    user_id, role = authenticate("GamesAdmin", "Athlete")
    body = parse_body(STAY_FIELDS)
    athlete = store.must_get("athlete", body["athlete_id"])
    block = store.must_get("accommodation_block", body["accommodation_block_id"])
    web.guard_owner(role, user_id, athlete["id"])
    if body["expected_block_version"] != block["version"]:
        fail("ERR_STALE_BLOCK_VERSION")
    check_in = as_date(body["check_in_date"])
    check_out = as_date(body["check_out_date"])
    edition = store.get("games_edition", block["games_edition_id"])
    if check_out <= check_in:
        fail("ERR_STAY_OUTSIDE_VILLAGE_WINDOW")
    if edition is not None:
        opens, closes = _village_window(edition)
        if not (opens <= check_in <= closes) or not (opens <= check_out <= closes):
            fail("ERR_STAY_OUTSIDE_VILLAGE_WINDOW")
    domain.bed_night_gate(block, check_in, check_out)
    nights = calc.nights_between(check_in, check_out)
    row = store.insert(
        "village_stay",
        {
            "athlete_id": athlete["id"],
            "accommodation_block_id": block["id"],
            "check_in_date": body["check_in_date"],
            "check_out_date": body["check_out_date"],
            "nights": nights,
            "total_charge_cents": nights * block["nightly_rate_cents"],
            "status": "RESERVED",
        },
    )
    block["reserved_bed_nights"] += nights
    store.touch(block)
    return web.obj(row, 201)


@bp.get(PREFIX + "/village-stays/<village_stay_id>")
def read_village_stay(village_stay_id):
    return web.single("village_stay", village_stay_id)


@bp.get(PREFIX + "/village-stays")
def list_village_stays():
    return web.collection(
        "village_stay", ("athlete_id", "accommodation_block_id", "status")
    )


@bp.post(PREFIX + "/village-stays/<village_stay_id>/cancel")
def cancel_village_stay(village_stay_id):
    user_id, role = authenticate("GamesAdmin", "Athlete")
    parse_body([Field("reason", "str", required=False, default=None, allow_empty=True)])
    stay = store.must_get("village_stay", village_stay_id)
    web.guard_owner(role, user_id, stay["athlete_id"])
    web.guard_state(stay["status"], ("RESERVED", "CHECKED_IN"))
    web.guard_terminal("village_stay", stay)
    domain.cancel_stay(stay)
    return web.obj(stay)
