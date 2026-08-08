"""Care-team handoff: a two-sided handshake under optimistic concurrency (PRD 3.7)."""
from datetime import timedelta

from flask import Blueprint

import constants as C
import domain
import envelope
import guards as G
import store
from errors import ApiError
from store import DB, serialize

bp = Blueprint("handoffs", __name__)


@bp.post("/tcm/episodes/<episode_id>/handoffs")
def propose_handoff(episode_id):
    user_id, role = G.auth(["CareNavigator"])
    data = G.body()
    to_navigator_id = G.req_string(data, "to_navigator_id")
    handoff_type = G.req_string(data, "handoff_type")
    expected_version = G.req_int(data, "expected_episode_version")
    G.enum(handoff_type, C.HANDOFF_TYPES, "handoff_type")

    episode = G.get_episode(episode_id)
    G.get_row("navigators", to_navigator_id)

    if to_navigator_id == episode["navigator_id"]:
        raise ApiError("ERR_ENTITY_LINK_MISMATCH")

    G.require_episode_owner(episode, user_id, role)
    G.require_open_records(episode)

    if expected_version != episode["version"]:
        raise ApiError("ERR_STALE_VERSION")

    proposed_at = store.now()
    row = store.new_row(
        "handoffs",
        {
            "episode_id": episode["id"],
            "from_navigator_id": episode["navigator_id"],
            "to_navigator_id": to_navigator_id,
            "handoff_type": handoff_type,
            "status": "PROPOSED",
            "proposed_at": proposed_at,
            "expires_at": proposed_at + timedelta(hours=C.HANDOFF_RESPONSE_WINDOW_HOURS),
            "responded_at": None,
            "decline_reason": None,
            "superseded_by_id": None,
        },
    )

    for other in DB["handoffs"].values():
        if (
            other["id"] != row["id"]
            and other["episode_id"] == episode["id"]
            and other["status"] == "PROPOSED"
        ):
            other["status"] = "SUPERSEDED"
            other["superseded_by_id"] = row["id"]
            store.touch(other)

    store.touch(episode)
    return envelope.created(serialize(row))


@bp.get("/tcm/handoffs/<handoff_id>")
def read_handoff(handoff_id):
    G.auth(C.ALL_ROLES)
    return envelope.ok(serialize(G.get_row("handoffs", handoff_id)))


@bp.get("/tcm/handoffs")
def list_handoffs():
    G.auth(C.ALL_ROLES)
    limit, offset = G.pagination()
    f = G.filters("episode_id", "from_navigator_id", "to_navigator_id", "status")

    def keep(row):
        return all(row.get(key) == value for key, value in f.items())

    rows = store.sorted_rows("handoffs", keep)
    page = rows[offset : offset + limit]
    return envelope.listing([serialize(r) for r in page], limit, offset, len(rows))


@bp.post("/tcm/handoffs/<handoff_id>/respond")
def respond_handoff(handoff_id):
    user_id, _role = G.auth(["CareNavigator"])
    data = G.body()
    response = G.req_string(data, "response")
    decline_reason = G.opt_string(data, "decline_reason")
    G.enum(response, C.HANDOFF_RESPONSES, "response")

    handoff = G.get_row("handoffs", handoff_id)
    episode = DB["episodes"][handoff["episode_id"]]

    # Ownership here is measured against the handoff, not against the episode.
    if user_id != handoff["to_navigator_id"]:
        raise ApiError("ERR_NOT_EPISODE_OWNER")

    G.require_open_records(episode)

    if handoff["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", "Only a PROPOSED handoff may be answered.")

    if store.now() > handoff["expires_at"]:
        handoff["status"] = "EXPIRED"
        store.touch(handoff)
        raise ApiError("ERR_HANDOFF_EXPIRED")

    if response == "ACCEPT":
        receiver = DB["navigators"][handoff["to_navigator_id"]]
        if handoff["handoff_type"] == "INTERNAL_NAVIGATOR":
            weight = domain.incoming_weight(receiver, episode)
            if receiver["workload_score"] + weight > receiver["active_episode_cap"]:
                raise ApiError("ERR_NAVIGATOR_CAP_EXCEEDED")
        sender_id = handoff["from_navigator_id"]
        handoff["status"] = "ACCEPTED"
        handoff["responded_at"] = store.now()
        store.touch(handoff)
        episode["navigator_id"] = handoff["to_navigator_id"]
        store.touch(episode)
        domain.recompute_navigator(sender_id)
        domain.recompute_navigator(handoff["to_navigator_id"])
    else:
        handoff["status"] = "DECLINED"
        handoff["decline_reason"] = decline_reason
        handoff["responded_at"] = store.now()
        store.touch(handoff)

    return envelope.ok(serialize(handoff))
