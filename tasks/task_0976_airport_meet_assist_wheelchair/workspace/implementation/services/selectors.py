"""Agent and wheelchair selectors per SCAFFOLD §1.3 / PRD §3.4."""
from datetime import timedelta

import db
from errors import no_eligible_agent, no_available_wheelchair
from services.pricing import ESTIMATED_TRANSFER_MINUTES, MAINT_INTERVAL


def estimate_transfer_minutes(leg_kind: str) -> int:
    return ESTIMATED_TRANSFER_MINUTES[leg_kind]


def _overlap(a_start, a_end, b_start, b_end) -> bool:
    """Half-open interval intersection: [a_start,a_end) ∩ [b_start,b_end) != ∅.
    Adjacency (end == start) is NOT a conflict."""
    return a_start < b_end and b_start < a_end


def _agent_has_overlap(agent_id: str, leg: dict) -> bool:
    leg_start = leg["scheduled_pickup_utc"]
    leg_end = leg_start + timedelta(minutes=estimate_transfer_minutes(leg["leg_kind"]))
    for asg in db.assignments.values():
        if asg["agent_id"] != agent_id:
            continue
        if asg["status"] not in {"DISPATCHED", "AT_PICKUP", "IN_TRANSIT", "AT_GATE"}:
            continue
        other_leg = db.legs.get(asg["service_leg_id"])
        if other_leg is None:
            continue
        a_start = other_leg["scheduled_pickup_utc"]
        a_end = asg["scheduled_completion_utc"]
        if _overlap(a_start, a_end, leg_start, leg_end):
            return True
    return False


def select_agent(leg: dict, airport_id: str):
    """Eligibility filter + deterministic ranking. Raises ERR_NO_ELIGIBLE_AGENT."""
    now = db.now()
    segment = db.segments[leg["segment_id"]]
    eligible = []
    for agent in db.agents.values():
        if agent["airport_id"] != airport_id:
            continue
        if agent["status"] != "ACTIVE":
            continue
        # Shift window: now within [shift_start_utc, shift_end_utc] inclusive
        if not (agent["shift_start_utc"] <= now <= agent["shift_end_utc"]):
            continue
        if leg.get("requires_tsa_escort"):
            if agent["tsa_cleared_until"] is None or agent["tsa_cleared_until"] <= now:
                continue
        if leg.get("requires_ummr_agent") and not agent.get("ummr_certified"):
            continue
        if leg.get("requires_senior_agent") and not agent.get("senior_trained"):
            continue
        if leg.get("requires_wchc_chair") and not agent.get("wc_certified"):
            continue
        if _agent_has_overlap(agent["id"], leg):
            continue
        eligible.append(agent)
    if not eligible:
        raise no_eligible_agent("No eligible agent for this leg")
    eligible.sort(key=lambda a: (
        a.get("active_assignment_count", 0),
        a.get("cumulative_delay_minutes", 0),
        a["shift_start_utc"],
        a["created_at"],
    ))
    return eligible[0]


def any_agent_with_tsa(airport_id: str) -> bool:
    """Precondition: at least one candidate agent (ACTIVE, in-shift) holds tsa_cleared_until > now."""
    now = db.now()
    for agent in db.agents.values():
        if agent["airport_id"] != airport_id:
            continue
        if agent["status"] != "ACTIVE":
            continue
        if not (agent["shift_start_utc"] <= now <= agent["shift_end_utc"]):
            continue
        if agent["tsa_cleared_until"] is not None and agent["tsa_cleared_until"] > now:
            return True
    return False


def select_wheelchair(leg: dict, airport_id: str):
    """Eligibility filter + ranking. Raises ERR_NO_AVAILABLE_WHEELCHAIR."""
    eligible = []
    for chair in db.wheelchairs.values():
        if chair["airport_id"] != airport_id:
            continue
        if chair["status"] != "AVAILABLE":
            continue
        if chair.get("usage_count", 0) >= MAINT_INTERVAL:
            continue
        if leg.get("requires_wchc_chair"):
            if not chair.get("is_wchc_rated"):
                continue
            if chair["chair_class"] not in {"POWER", "BARIATRIC"}:
                continue
        eligible.append(chair)
    if not eligible:
        raise no_available_wheelchair("No available wheelchair")
    # usage_count ASC, last_maintenance_utc DESC NULLS LAST, created_at ASC
    def key(c):
        lm = c.get("last_maintenance_utc")
        # NULLS LAST for DESC: use a tuple flag — False (not null) sorts before True (null)
        return (
            c.get("usage_count", 0),
            lm is None,                       # False < True -> non-null first
            -lm.timestamp() if lm else 0,     # DESC
            c["created_at"],
        )
    eligible.sort(key=key)
    return eligible[0]
