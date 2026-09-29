"""Episode cadence: scheduling, releasing and rolling back (PRD 3.2)."""
from flask import Blueprint

import config
import db
import resolve
import validators as v
from db import ordered, serialize
from errors import fail
from middleware import authenticate
from response import object_response, touch
from services import calc, ledger

bp = Blueprint("episodes", __name__)

READ_ROLES = (
    config.ROLE_CONTENT_PRODUCER,
    config.ROLE_ECONOMY_DESIGNER,
    config.ROLE_LIVEOPS_COMMANDER,
    config.ROLE_COMPLIANCE_OFFICER,
)


def _season_episodes(season_id):
    return [e for e in db.db.episodes.values() if e["season_id"] == season_id]


def _inside_window(season, instant):
    return season["starts_at"] <= instant <= season["ends_at"]


@bp.post("/episodes")
def create_episode():
    authenticate(config.ROLE_CONTENT_PRODUCER)
    payload = v.body()
    season = resolve.body_fk(payload, "season_id", db.db.seasons, "ERR_SEASON_NOT_FOUND")
    v.req_string(payload, "season_id")
    sequence_no = v.req_int(payload, "sequence_no", minimum=1)
    title = v.req_string(payload, "title")
    planned_release_at = v.req_datetime(payload, "planned_release_at")
    xp_grant = v.req_int(payload, "xp_grant", minimum=0)
    soft_currency_grant_minor = v.req_int(payload, "soft_currency_grant_minor", minimum=0)

    siblings = _season_episodes(season["id"])
    highest = max([e["sequence_no"] for e in siblings], default=0)
    if sequence_no != highest + 1:
        fail(
            "ERR_EPISODE_SEQUENCE_GAP",
            "sequence_no must be exactly one greater than the season's highest sequence_no.",
        )
    if not _inside_window(season, planned_release_at):
        fail("ERR_SEASON_WINDOW_VIOLATION", "planned_release_at falls outside the season window.")

    episode = db.insert(
        db.db.episodes,
        {
            "season_id": season["id"],
            "sequence_no": sequence_no,
            "title": title,
            "planned_release_at": planned_release_at,
            "actual_release_at": None,
            "xp_grant": xp_grant,
            "soft_currency_grant_minor": soft_currency_grant_minor,
            "status": "DRAFT",
            "rollback_count": 0,
            "grant_batch_size": 0,
            "_grant_entry_ids": [],
        },
    )
    return object_response(serialize(episode), 201)


@bp.get("/episodes/<episode_id>")
def read_episode(episode_id):
    authenticate(*READ_ROLES)
    episode = resolve.episode(episode_id)
    return object_response(serialize(episode))


@bp.post("/episodes/<episode_id>/schedule")
def schedule_episode(episode_id):
    authenticate(config.ROLE_CONTENT_PRODUCER)
    episode = resolve.episode(episode_id)
    payload = v.body()
    supplied = v.opt_datetime(payload, "planned_release_at")
    season = db.db.seasons.get(episode["season_id"])

    status = episode["status"]
    if status not in ("DRAFT", "ROLLED_BACK"):
        fail("ERR_EPISODE_INVALID_STATE", "Only a DRAFT or ROLLED_BACK episode can be scheduled.")

    if status == "DRAFT":
        if season["status"] not in ("PLANNED", "LIVE"):
            fail("ERR_SEASON_NOT_LIVE", "The season must be PLANNED or LIVE to schedule an episode.")
    else:
        if season["status"] != "LIVE":
            fail("ERR_SEASON_NOT_LIVE", "The season must be LIVE to reschedule a rolled-back episode.")
        if supplied is None:
            v.bad("planned_release_at", "is required when rescheduling a ROLLED_BACK episode")

    effective = supplied if supplied is not None else episode["planned_release_at"]

    if status == "DRAFT" and episode["sequence_no"] > 1:
        predecessor = None
        for sibling in _season_episodes(episode["season_id"]):
            if sibling["sequence_no"] == episode["sequence_no"] - 1:
                predecessor = sibling
                break
        if predecessor is not None and predecessor["status"] == "DRAFT":
            fail("ERR_EPISODE_SEQUENCE_GAP", "The preceding episode is still in DRAFT.")

    if status == "ROLLED_BACK" and effective < db.now():
        fail("ERR_SEASON_WINDOW_VIOLATION", "planned_release_at must be at or after the current clock.")
    if not _inside_window(season, effective):
        fail("ERR_SEASON_WINDOW_VIOLATION", "planned_release_at falls outside the season window.")

    episode["planned_release_at"] = effective
    if status == "ROLLED_BACK":
        episode["actual_release_at"] = None
    episode["status"] = "SCHEDULED"
    touch(episode)

    season["scheduled_episode_count"] += 1
    calc.recompute_cadence(season)
    touch(season)
    return object_response(serialize(episode))


@bp.post("/episodes/<episode_id>/release")
def release_episode(episode_id):
    authenticate(config.ROLE_CONTENT_PRODUCER, config.ROLE_LIVEOPS_COMMANDER)
    episode = resolve.episode(episode_id)
    season = db.db.seasons.get(episode["season_id"])

    if episode["status"] != "SCHEDULED":
        fail("ERR_EPISODE_INVALID_STATE", "Only a SCHEDULED episode can be released.")
    if season["status"] != "LIVE":
        fail("ERR_SEASON_NOT_LIVE", "The season must be LIVE to release an episode.")
    if season["economy_health"] == "INFLATED":
        fail("ERR_ECONOMY_INFLATED_BLOCK", "The season economy is INFLATED.")
    clock = db.now()
    if clock < episode["planned_release_at"]:
        fail("ERR_EPISODE_NOT_DUE", "The episode is not due for release yet.")

    episode["status"] = "LIVE"
    episode["actual_release_at"] = clock
    touch(episode)

    season["scheduled_episode_count"] = max(0, season["scheduled_episode_count"] - 1)
    season["released_episode_count"] += 1

    for sibling in ordered(_season_episodes(episode["season_id"])):
        if (
            sibling["id"] != episode["id"]
            and sibling["status"] == "LIVE"
            and sibling["sequence_no"] < episode["sequence_no"]
        ):
            sibling["status"] = "CONCLUDED"
            touch(sibling)

    amount = episode["soft_currency_grant_minor"]
    recipients = calc.episode_grant_recipients(episode)
    entry_ids = []
    for account in recipients:
        entry = ledger.append_entry(
            account,
            "FAUCET",
            amount,
            "EPISODE_GRANT",
            episode["season_id"],
        )
        entry_ids.append(entry["id"])
    episode["grant_batch_size"] = len(recipients)
    episode["_grant_entry_ids"] = entry_ids

    calc.refresh_lifetime_ratio(season)
    calc.recompute_cadence(season)
    touch(season)
    return object_response(serialize(episode))


@bp.post("/episodes/<episode_id>/rollback")
def rollback_episode(episode_id):
    authenticate(config.ROLE_LIVEOPS_COMMANDER)
    episode = resolve.episode(episode_id)
    payload = v.body()
    v.req_string(payload, "reason")
    season = db.db.seasons.get(episode["season_id"])

    if episode["status"] != "LIVE":
        fail("ERR_EPISODE_INVALID_STATE", "Only a LIVE episode can be rolled back.")
    if season["status"] != "LIVE":
        fail("ERR_SEASON_NOT_LIVE", "The season must be LIVE to roll an episode back.")

    episode["status"] = "ROLLED_BACK"
    episode["rollback_count"] += 1
    touch(episode)
    season["released_episode_count"] = max(0, season["released_episode_count"] - 1)

    originals = [db.db.ledger[eid] for eid in episode["_grant_entry_ids"] if eid in db.db.ledger]
    for original in ordered(originals):
        account = db.db.accounts.get(original["currency_account_id"])
        if account is None:
            continue
        ledger.append_entry(
            account,
            "SINK",
            original["amount_minor"],
            "EPISODE_ROLLBACK_REVERSAL",
            original["season_id"],
            reversal_of_entry_id=original["id"],
        )

    calc.refresh_lifetime_ratio(season)
    calc.recompute_cadence(season)
    touch(season)
    return object_response(serialize(episode))
