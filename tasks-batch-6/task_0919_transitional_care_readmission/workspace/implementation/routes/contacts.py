"""Interactive follow-up contact: the bounded, ordered outreach ladder (PRD 3.3)."""
from datetime import timedelta

from flask import Blueprint

import constants as C
import domain
import envelope
import guards as G
import store
from errors import ApiError
from store import DB, serialize

bp = Blueprint("contacts", __name__)


@bp.post("/tcm/episodes/<episode_id>/contact-attempts")
def log_contact_attempt(episode_id):
    user_id, role = G.auth(["CareNavigator"])
    data = G.body()
    modality = G.req_string(data, "modality")
    notes = G.opt_string(data, "notes", default="")
    G.enum(modality, C.CONTACT_MODALITIES, "modality")

    episode = G.get_episode(episode_id)
    G.require_episode_owner(episode, user_id, role)
    G.require_open_records(episode)

    attempts = [a for a in DB["contact_attempts"].values() if a["episode_id"] == episode["id"]]

    # rung 10 - state
    if episode["contact_status"] in ("SUCCESSFUL", "REFUSED"):
        raise ApiError(
            "ERR_INVALID_STATE", "No further attempt may be logged once contact has concluded."
        )
    if any(a["attempt_status"] == "LOGGED" for a in attempts):
        raise ApiError("ERR_INVALID_STATE", "An earlier attempt is still awaiting its disposition.")

    # rung 18 - the four-attempt cap
    if episode["contact_attempt_count"] >= C.MAX_CONTACT_ATTEMPTS:
        raise ApiError("ERR_CONTACT_ATTEMPT_LIMIT")

    # rung 19 - the cooldown
    if attempts:
        previous = max(attempts, key=lambda a: a["attempt_number"])
        elapsed = store.now() - previous["attempted_at"]
        if elapsed < timedelta(minutes=C.CONTACT_ATTEMPT_COOLDOWN_MINUTES):
            raise ApiError("ERR_SCHEDULE_CONFLICT")

    # rung 20 - the modality ladder
    attempt_number = episode["contact_attempt_count"] + 1
    if modality != C.CONTACT_MODALITY_LADDER[attempt_number - 1]:
        raise ApiError("ERR_MODALITY_OUT_OF_SEQUENCE")

    row = store.new_row(
        "contact_attempts",
        {
            "episode_id": episode["id"],
            "attempt_number": attempt_number,
            "modality": modality,
            "attempt_status": "LOGGED",
            "attempted_at": store.now(),
            "disposition_at": None,
            "notes": notes,
        },
    )

    if episode["status"] == "INTAKE":
        episode["status"] = "ACTIVE"
    if episode["contact_status"] == "NOT_STARTED":
        episode["contact_status"] = "IN_PROGRESS"
    store.touch(episode)
    domain.recompute_episode_contact_attempts(episode)
    domain.recompute_navigator(episode["navigator_id"])

    return envelope.created(serialize(row))


@bp.get("/tcm/contact-attempts/<contact_attempt_id>")
def read_contact_attempt(contact_attempt_id):
    G.auth(C.ALL_ROLES)
    return envelope.ok(serialize(G.get_row("contact_attempts", contact_attempt_id)))


@bp.get("/tcm/contact-attempts")
def list_contact_attempts():
    G.auth(C.ALL_ROLES)
    limit, offset = G.pagination()
    f = G.filters("episode_id", "attempt_status")

    def keep(row):
        return all(row.get(key) == value for key, value in f.items())

    rows = store.sorted_rows("contact_attempts", keep)
    page = rows[offset : offset + limit]
    return envelope.listing([serialize(r) for r in page], limit, offset, len(rows))


@bp.post("/tcm/contact-attempts/<contact_attempt_id>/disposition")
def disposition_contact_attempt(contact_attempt_id):
    user_id, role = G.auth(["CareNavigator"])
    data = G.body()
    outcome = G.req_string(data, "outcome")
    G.enum(outcome, C.CONTACT_DISPOSITION_OUTCOMES, "outcome")

    attempt = G.get_row("contact_attempts", contact_attempt_id)
    episode = DB["episodes"][attempt["episode_id"]]
    G.require_episode_owner(episode, user_id, role)
    G.require_open_records(episode)

    if attempt["attempt_status"] != "LOGGED":
        raise ApiError("ERR_INVALID_STATE", "The attempt has already been dispositioned.")

    attempt["attempt_status"] = outcome
    attempt["disposition_at"] = store.now()
    store.touch(attempt)

    if outcome == "CONNECTED":
        episode["contact_status"] = "SUCCESSFUL"
        episode["successful_contact_at"] = store.now()
        store.touch(episode)
        domain.recompute_contact_timely(episode)
    elif outcome == "REFUSED":
        episode["contact_status"] = "REFUSED"
        store.touch(episode)
        domain.create_red_flag(
            episode, "CONTACT_REFUSED", C.CONTACT_REFUSED_RED_FLAG_TIER, C.SYSTEM_USER_ID
        )

    return envelope.ok(serialize(attempt))
