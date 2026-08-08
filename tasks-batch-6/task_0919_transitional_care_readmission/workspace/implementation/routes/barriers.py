"""Typed barriers: SLA, owning role and blocking class (PRD 3.6)."""
from datetime import timedelta

from flask import Blueprint

import constants as C
import envelope
import guards as G
import store
from errors import ApiError
from store import DB, serialize

bp = Blueprint("barriers", __name__)


@bp.post("/tcm/episodes/<episode_id>/barriers")
def raise_barrier(episode_id):
    user_id, role = G.auth(["CareNavigator"])
    data = G.body()
    barrier_type = G.req_string(data, "barrier_type")
    description = G.opt_string(data, "description", default="")
    G.enum(barrier_type, C.BARRIER_TYPES, "barrier_type")

    episode = G.get_episode(episode_id)
    G.require_episode_owner(episode, user_id, role)
    G.require_open_records(episode)

    opened_at = store.now()
    sla_hours = C.BARRIER_SLA_HOURS[barrier_type]
    row = store.new_row(
        "barriers",
        {
            "episode_id": episode["id"],
            "barrier_type": barrier_type,
            "blocking_class": barrier_type in C.BARRIER_BLOCKING_TYPES,
            "owner_role": C.BARRIER_OWNER_ROLE[barrier_type],
            "sla_hours": sla_hours,
            "opened_at": opened_at,
            "sla_due_at": opened_at + timedelta(hours=sla_hours),
            "status": "OPEN",
            "closed_at": None,
            "description": description,
            "escalated_red_flag_id": None,
        },
    )
    return envelope.created(serialize(row))


@bp.get("/tcm/barriers/<barrier_id>")
def read_barrier(barrier_id):
    G.auth(C.ALL_ROLES)
    return envelope.ok(serialize(G.get_row("barriers", barrier_id)))


@bp.get("/tcm/barriers")
def list_barriers():
    G.auth(C.ALL_ROLES)
    limit, offset = G.pagination()
    f = G.filters("episode_id", "barrier_type", "status")

    def keep(row):
        return all(row.get(key) == value for key, value in f.items())

    rows = store.sorted_rows("barriers", keep)
    page = rows[offset : offset + limit]
    return envelope.listing([serialize(r) for r in page], limit, offset, len(rows))


@bp.post("/tcm/barriers/<barrier_id>/close")
def close_barrier(barrier_id):
    _user_id, role = G.auth(["CareNavigator", "BillingSpecialist", "Clinician", "ProgramAdmin"])
    data = G.body()
    outcome = G.req_string(data, "outcome")
    G.enum(outcome, C.BARRIER_CLOSE_OUTCOMES, "outcome")

    barrier = G.get_row("barriers", barrier_id)
    episode = DB["episodes"][barrier["episode_id"]]

    # Data-driven authorisation (PRD 2.1): resolving belongs to the barrier's
    # own owner_role; waiving belongs to ProgramAdmin.
    if outcome == "RESOLVED":
        if role != barrier["owner_role"]:
            raise ApiError("ERR_FORBIDDEN_ROLE")
    else:
        if role != "ProgramAdmin":
            raise ApiError("ERR_FORBIDDEN_ROLE")

    G.require_open_records(episode)
    if barrier["status"] not in ("OPEN", "ESCALATED"):
        raise ApiError("ERR_INVALID_STATE", "The barrier is already closed.")

    barrier["status"] = outcome
    barrier["closed_at"] = store.now()
    store.touch(barrier)
    return envelope.ok(serialize(barrier))
