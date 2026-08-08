"""Red flags: tiered escalation with a bounded promotion loop (PRD 3.6)."""
from flask import Blueprint

import constants as C
import domain
import envelope
import guards as G
import store
from errors import ApiError
from store import DB, serialize

bp = Blueprint("redflags", __name__)


@bp.post("/tcm/episodes/<episode_id>/red-flags")
def raise_red_flag(episode_id):
    user_id, role = G.auth(["CareNavigator", "Clinician"])
    data = G.body()
    category = G.req_string(data, "category")
    initial_tier = G.req_string(data, "initial_tier")
    G.enum(category, C.RED_FLAG_CATEGORIES, "category")
    G.enum(initial_tier, C.RED_FLAG_TIERS, "initial_tier")

    episode = G.get_episode(episode_id)
    G.require_episode_owner(episode, user_id, role)
    G.require_open_records(episode)

    flag = domain.create_red_flag(episode, category, initial_tier, user_id)
    return envelope.created(serialize(flag))


@bp.get("/tcm/red-flags/<red_flag_id>")
def read_red_flag(red_flag_id):
    G.auth(C.ALL_ROLES)
    return envelope.ok(serialize(G.get_row("red_flags", red_flag_id)))


@bp.get("/tcm/red-flags")
def list_red_flags():
    G.auth(C.ALL_ROLES)
    limit, offset = G.pagination()
    f = G.filters("episode_id", "source_barrier_id", "tier", "status")

    def keep(row):
        return all(row.get(key) == value for key, value in f.items())

    rows = store.sorted_rows("red_flags", keep)
    page = rows[offset : offset + limit]
    return envelope.listing([serialize(r) for r in page], limit, offset, len(rows))


@bp.post("/tcm/red-flags/<red_flag_id>/acknowledge")
def acknowledge_red_flag(red_flag_id):
    user_id, role = G.auth(["CareNavigator", "Clinician"])
    flag = G.get_row("red_flags", red_flag_id)
    episode = DB["episodes"][flag["episode_id"]]

    # Data-driven authorisation: only the routing role for the flag's CURRENT
    # tier may acknowledge it.
    if role != C.REDFLAG_ROUTING_ROLE[flag["tier"]]:
        raise ApiError("ERR_FORBIDDEN_ROLE")

    G.require_open_records(episode)
    if flag["status"] != "RAISED":
        raise ApiError("ERR_INVALID_STATE", "Only a RAISED red flag may be acknowledged.")

    flag["status"] = "ACKNOWLEDGED"
    flag["acknowledged_by_user_id"] = user_id
    flag["acknowledged_at"] = store.now()
    store.touch(flag)
    domain.recompute_episode_red_flags(episode)
    return envelope.ok(serialize(flag))


@bp.post("/tcm/red-flags/<red_flag_id>/resolve")
def resolve_red_flag(red_flag_id):
    user_id, _role = G.auth(["CareNavigator", "Clinician"])
    data = G.body()
    resolution_outcome = G.req_string(data, "resolution_outcome")
    G.enum(resolution_outcome, C.RESOLUTION_OUTCOMES, "resolution_outcome")

    flag = G.get_row("red_flags", red_flag_id)
    episode = DB["episodes"][flag["episode_id"]]
    G.require_open_records(episode)

    if flag["status"] != "ACKNOWLEDGED":
        raise ApiError("ERR_INVALID_STATE", "Only an ACKNOWLEDGED red flag may be resolved.")
    if user_id == flag["raised_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    flag["status"] = "RESOLVED"
    flag["resolution_outcome"] = resolution_outcome
    store.touch(flag)

    if resolution_outcome == "SENT_TO_ED":
        today = store.current_date_str()
        window_start = store.add_days(episode["discharge_date"], 1)
        window_end = episode["readmission_window_end_date"]
        if window_start <= today <= window_end:
            event = domain.create_readmission_event(
                episode, today, "ED_TREAT_AND_RELEASE", C.SYSTEM_USER_ID,
                source_red_flag_id=flag["id"],
            )
            flag["spawned_readmission_id"] = event["id"]
        else:
            flag["ed_event_suppressed"] = True

    domain.recompute_episode_red_flags(episode)
    return envelope.ok(serialize(flag))
