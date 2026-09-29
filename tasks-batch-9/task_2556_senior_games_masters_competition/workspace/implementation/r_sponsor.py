"""Sponsorship commitments: pledge, recognition allocation, withdrawal."""
from flask import Blueprint

import calc
import store
import web
from core import Field, authenticate, fail, parse_body
from web import PREFIX

bp = Blueprint("sponsor", __name__)

COMMITMENT_FIELDS = [
    Field("games_edition_id", "id"),
    Field("sponsor_name", "str"),
    Field("sponsor_kind", "str", enum=("CORPORATE", "MUNICIPAL", "FOUNDATION")),
    Field("tier", "str", enum=("BRONZE", "SILVER", "GOLD", "PLATINUM")),
    Field("pledged_cents", "int", minimum=1),
]


@bp.post(PREFIX + "/sponsorship-commitments")
def create_sponsorship_commitment():
    authenticate("SponsorLiaison")
    body = parse_body(COMMITMENT_FIELDS)
    store.must_get("games_edition", body["games_edition_id"])
    row = store.insert(
        "sponsorship_commitment",
        {
            "games_edition_id": body["games_edition_id"],
            "sponsor_name": body["sponsor_name"],
            "sponsor_kind": body["sponsor_kind"],
            "tier": body["tier"],
            "pledged_cents": body["pledged_cents"],
            "recognized_cents": 0,
            "allocation_map": {},
            "status": "PLEDGED",
        },
    )
    return web.obj(row, 201)


@bp.get(PREFIX + "/sponsorship-commitments/<sponsorship_commitment_id>")
def read_sponsorship_commitment(sponsorship_commitment_id):
    return web.single("sponsorship_commitment", sponsorship_commitment_id)


@bp.get(PREFIX + "/sponsorship-commitments")
def list_sponsorship_commitments():
    return web.collection("sponsorship_commitment", ("games_edition_id", "status"))


@bp.post(PREFIX + "/sponsorship-commitments/<sponsorship_commitment_id>/allocate")
def allocate_sponsorship_commitment(sponsorship_commitment_id):
    authenticate("SponsorLiaison")
    body = parse_body([Field("expected_games_edition_version", "int")])
    commitment = store.must_get("sponsorship_commitment", sponsorship_commitment_id)
    edition = store.get("games_edition", commitment["games_edition_id"])
    if edition is None or body["expected_games_edition_version"] != edition["version"]:
        fail("ERR_STALE_GAMES_EDITION_VERSION")
    if edition["status"] == "IMPACT_FINALIZED":
        fail("ERR_EDITION_STATE_INVALID")
    web.guard_state(commitment["status"], ("PLEDGED",))
    web.guard_terminal("sponsorship_commitment", commitment)
    recognized, allocation_map = calc.allocate_sponsorship(
        commitment["pledged_cents"], commitment["tier"]
    )
    commitment["recognized_cents"] = recognized
    commitment["allocation_map"] = allocation_map
    commitment["status"] = "ALLOCATED"
    store.touch(commitment)
    edition["sponsorship_recognized_cents"] += recognized
    store.touch(edition)
    return web.obj(commitment)


@bp.post(PREFIX + "/sponsorship-commitments/<sponsorship_commitment_id>/withdraw")
def withdraw_sponsorship_commitment(sponsorship_commitment_id):
    authenticate("SponsorLiaison")
    parse_body([Field("reason", "str", required=False, default=None, allow_empty=True)])
    commitment = store.must_get("sponsorship_commitment", sponsorship_commitment_id)
    web.guard_state(commitment["status"], ("PLEDGED", "ALLOCATED"))
    web.guard_terminal("sponsorship_commitment", commitment)
    edition = store.get("games_edition", commitment["games_edition_id"])
    if commitment["status"] == "ALLOCATED":
        if edition is not None and edition["status"] == "IMPACT_FINALIZED":
            fail("ERR_EDITION_STATE_INVALID")
        recognized = commitment["recognized_cents"]
        commitment["recognized_cents"] = 0
        commitment["allocation_map"] = {}
        commitment["status"] = "WITHDRAWN"
        store.touch(commitment)
        if edition is not None:
            edition["sponsorship_recognized_cents"] -= recognized
            store.touch(edition)
    else:
        commitment["status"] = "WITHDRAWN"
        store.touch(commitment)
    return web.obj(commitment)
