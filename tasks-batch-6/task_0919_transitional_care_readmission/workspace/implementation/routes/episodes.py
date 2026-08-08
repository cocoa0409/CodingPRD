"""Care episode reads, service-period closure, administrative closure and the
operational sweep (PRD 3.1, 3.6, 3.8, 3.9)."""
from datetime import timedelta

from flask import Blueprint

import constants as C
import domain
import envelope
import guards as G
import store
from errors import ApiError
from store import DB, serialize

bp = Blueprint("episodes", __name__)


@bp.get("/tcm/episodes/<episode_id>")
def read_episode(episode_id):
    G.auth(C.ALL_ROLES)
    return envelope.ok(serialize(G.get_episode(episode_id)))


@bp.get("/tcm/episodes")
def list_episodes():
    G.auth(C.ALL_ROLES)
    limit, offset = G.pagination()
    f = G.filters("patient_id", "navigator_id", "referral_id", "payer_id", "facility_id", "status")

    def keep(row):
        return all(row.get(key) == value for key, value in f.items())

    rows = store.sorted_rows("episodes", keep)
    page = rows[offset : offset + limit]
    return envelope.listing([serialize(r) for r in page], limit, offset, len(rows))


# --------------------------------------------------- close service period
@bp.post("/tcm/episodes/<episode_id>/close-service-period")
def close_service_period(episode_id):
    G.auth(["ProgramAdmin"])
    episode = G.get_episode(episode_id)
    G.require_open_records(episode)

    if episode["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "The service period may only be closed from ACTIVE.")
    if not store.now() > store.end_of_day(episode["service_period_end_date"]):
        raise ApiError("ERR_SERVICE_PERIOD_OPEN")

    episode["status"] = "SERVICE_PERIOD_CLOSED"
    episode["_flags_frozen"] = True
    store.touch(episode)

    domain.recompute_navigator(episode["navigator_id"])
    domain.recompute_patient(episode["patient_id"])
    domain.evaluate_freeze(episode)
    return envelope.ok(serialize(episode))


# ------------------------------------------------------------ admin close
@bp.post("/tcm/episodes/<episode_id>/admin-close")
def admin_close(episode_id):
    G.auth(["ProgramAdmin"])
    data = G.body()
    G.opt_string(data, "reason")
    episode = G.get_episode(episode_id)
    G.require_open_records(episode)

    if episode["status"] not in C.OPEN_EPISODE_STATUSES:
        raise ApiError("ERR_INVALID_STATE", "The episode cannot be administratively closed.")

    episode["status"] = "ADMIN_CLOSED"
    store.touch(episode)

    claim = domain.episode_claim(episode)
    if claim is not None and claim["status"] in C.NON_TERMINAL_CLAIM_STATUSES:
        domain.void_claim(claim)

    domain.recompute_navigator(episode["navigator_id"])
    domain.recompute_patient(episode["patient_id"])
    domain.evaluate_freeze(episode)
    return envelope.ok(serialize(episode))


# --------------------------------------------------------------- sla sweep
@bp.post("/tcm/episodes/<episode_id>/sla-sweep")
def sla_sweep(episode_id):
    G.auth(["ProgramAdmin"])
    episode = G.get_episode(episode_id)
    G.require_open_records(episode)

    now = store.now()
    barriers_escalated = 0
    red_flags_created = 0
    red_flags_promoted = 0
    red_flags_breached = 0
    handoffs_expired = 0

    # -- phase 1: blocking barriers past their SLA --------------------------
    spawned_ids = set()
    barriers = [b for b in DB["barriers"].values() if b["episode_id"] == episode["id"]]
    barriers.sort(key=lambda b: (b["created_at"], b["_seq"]))
    for barrier in barriers:
        if barrier["status"] != "OPEN" or not barrier["blocking_class"]:
            continue
        if not now > barrier["sla_due_at"]:
            continue
        barrier["status"] = "ESCALATED"
        flag = domain.create_red_flag(
            episode,
            "BARRIER_SLA_BREACH",
            C.BARRIER_ESCALATION_RED_FLAG_TIER,
            C.SYSTEM_USER_ID,
            source_barrier_id=barrier["id"],
        )
        flag["ack_due_at"] = now + timedelta(
            minutes=C.REDFLAG_ACK_SLA_MINUTES[C.BARRIER_ESCALATION_RED_FLAG_TIER]
        )
        spawned_ids.add(flag["id"])
        barrier["escalated_red_flag_id"] = flag["id"]
        store.touch(barrier)
        barriers_escalated += 1
        red_flags_created += 1
        for visit in DB["visits"].values():
            if (
                visit["episode_id"] == episode["id"]
                and visit["encounter_status"] == "SCHEDULED"
                and visit["confirmation_status"] == "CONFIRMED"
            ):
                visit["confirmation_status"] = "UNCONFIRMED"
                store.touch(visit)

    # -- phase 2: unacknowledged red flags ----------------------------------
    flags = [f for f in DB["red_flags"].values() if f["episode_id"] == episode["id"]]
    flags.sort(key=lambda f: (f["created_at"], f["_seq"]))
    for flag in flags:
        if flag["id"] in spawned_ids:
            continue
        if flag["status"] != "RAISED":
            continue
        if not now > flag["ack_due_at"]:
            continue
        if flag["tier"] != "TIER_1" and flag["promotion_count"] < C.MAX_REDFLAG_PROMOTIONS:
            new_tier = C.REDFLAG_PROMOTION_STEP[flag["tier"]]
            flag["tier"] = new_tier
            flag["promotion_count"] += 1
            flag["ack_due_at"] = now + timedelta(minutes=C.REDFLAG_ACK_SLA_MINUTES[new_tier])
            store.touch(flag)
            red_flags_promoted += 1
        else:
            flag["status"] = "BREACHED"
            store.touch(flag)
            red_flags_breached += 1

    # -- phase 3: stale handoff proposals -----------------------------------
    handoffs = [h for h in DB["handoffs"].values() if h["episode_id"] == episode["id"]]
    handoffs.sort(key=lambda h: (h["created_at"], h["_seq"]))
    for handoff in handoffs:
        if handoff["status"] != "PROPOSED":
            continue
        if not now > handoff["expires_at"]:
            continue
        handoff["status"] = "EXPIRED"
        store.touch(handoff)
        handoffs_expired += 1

    domain.recompute_episode_red_flags(episode)

    return envelope.ok(
        {
            "barriers_escalated": barriers_escalated,
            "red_flags_created": red_flags_created,
            "red_flags_promoted": red_flags_promoted,
            "red_flags_breached": red_flags_breached,
            "handoffs_expired": handoffs_expired,
        }
    )
