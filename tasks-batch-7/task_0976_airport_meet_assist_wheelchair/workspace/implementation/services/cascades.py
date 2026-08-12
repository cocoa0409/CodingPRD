"""Cascading side effects: posture, ops-epoch, agent suspend, cancel chains, completion."""
from datetime import timedelta

import db
from services import pricing


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _legs_of_request(request_id: str):
    return [l for l in db.legs.values() if l["assist_request_id"] == request_id]


def _assignments_of_leg(leg_id: str):
    return [a for a in db.assignments.values() if a["service_leg_id"] == leg_id]


def _assignments_of_request(request_id: str):
    return [a for a in db.assignments.values() if a["assist_request_id"] == request_id]


def _request_airport_ids(request_id: str) -> set:
    ids = set()
    for leg in _legs_of_request(request_id):
        seg = db.segments.get(leg["segment_id"])
        if seg:
            ids.add(seg["airport_id"])
    return ids


def _open_provisional_invoice(request_id: str):
    for inv in db.invoices.values():
        if (inv["assist_request_id"] == request_id
                and inv["invoice_kind"] == "PROVISIONAL"
                and inv["status"] == "OPEN"):
            return inv
    return None


def _void_invoice(inv):
    inv["status"] = "VOID"
    db.touch(inv)


def release_chair(chair_id):
    """CHECKED_OUT -> AVAILABLE (or MAINTENANCE when usage threshold reached)."""
    if not chair_id:
        return
    chair = db.wheelchairs.get(chair_id)
    if chair is None:
        return
    if chair["status"] != "CHECKED_OUT":
        return
    if chair.get("usage_count", 0) >= pricing.MAINT_INTERVAL:
        chair["status"] = "MAINTENANCE"
    else:
        chair["status"] = "AVAILABLE"
    db.touch(chair)


def _release_chair_no_maint(chair_id):
    """Release on cancel/suspend/lockdown: CHECKED_OUT -> AVAILABLE (no maintenance check,
    usage_count NOT decremented)."""
    if not chair_id:
        return
    chair = db.wheelchairs.get(chair_id)
    if chair is None:
        return
    if chair["status"] == "CHECKED_OUT":
        chair["status"] = "AVAILABLE"
        db.touch(chair)


# ---------------------------------------------------------------------------
# Assignment cancellation paths
# ---------------------------------------------------------------------------

def cancel_assignment_for_agent_suspend(asg):
    """Agent SUSPEND / OFF_SHIFT cascade: assignment CANCELLED, leg -> PLANNED (rebookable)."""
    if asg["status"] not in {"DISPATCHED", "AT_PICKUP", "IN_TRANSIT"}:
        return
    asg["status"] = "CANCELLED"
    db.touch(asg)
    leg = db.legs.get(asg["service_leg_id"])
    if leg is not None and leg["status"] in {"DISPATCHED", "AT_PICKUP", "IN_TRANSIT"}:
        leg["status"] = "PLANNED"
        db.touch(leg)
    _release_chair_no_maint(asg.get("wheelchair_asset_id"))
    agent = db.agents.get(asg["agent_id"])
    if agent is not None and agent.get("active_assignment_count", 0) > 0:
        agent["active_assignment_count"] -= 1
        db.touch(agent)


def cancel_assignment_direct(asg):
    """Direct CANCEL_ASSIGN (dispatcher) or LOCKDOWN: assignment CANCELLED, leg -> CANCELLED."""
    if asg["status"] not in {"DISPATCHED", "AT_PICKUP", "IN_TRANSIT", "AT_GATE"}:
        return
    asg["status"] = "CANCELLED"
    db.touch(asg)
    leg = db.legs.get(asg["service_leg_id"])
    if leg is not None and leg["status"] in {"DISPATCHED", "AT_PICKUP", "IN_TRANSIT", "AT_GATE"}:
        leg["status"] = "CANCELLED"
        db.touch(leg)
    _release_chair_no_maint(asg.get("wheelchair_asset_id"))
    agent = db.agents.get(asg["agent_id"])
    if agent is not None and agent.get("active_assignment_count", 0) > 0:
        agent["active_assignment_count"] -= 1
        db.touch(agent)


def _bubble_request_failure(request_id: str):
    """If every leg of the request is in {CANCELLED, FAILED}, request -> FAILED;
    void provisional invoice; billing -> UNBILLED."""
    request = db.assist_requests.get(request_id)
    if request is None:
        return
    if request["request_status"] in {"COMPLETED", "CANCELLED", "FAILED"}:
        return
    legs = _legs_of_request(request_id)
    if not legs:
        return
    if all(l["status"] in {"CANCELLED", "FAILED"} for l in legs):
        request["request_status"] = "FAILED"
        prov = _open_provisional_invoice(request_id)
        if prov is not None:
            _void_invoice(prov)
        if request["billing_status"] in {"PROVISIONAL"}:
            request["billing_status"] = "UNBILLED"
        db.touch(request)


def _maybe_advance_to_assigned(request_id: str):
    """SUBMITTED -> ASSIGNED when every PLANNED leg has at least one DISPATCHED assignment."""
    request = db.assist_requests.get(request_id)
    if request is None or request["request_status"] != "SUBMITTED":
        return
    legs = _legs_of_request(request_id)
    if not legs:
        return
    later = {"DISPATCHED", "AT_PICKUP", "IN_TRANSIT", "AT_GATE", "HANDED_OFF", "COMPLETED"}
    if all(l["status"] in later for l in legs):
        request["request_status"] = "ASSIGNED"
        db.touch(request)


def _maybe_advance_to_in_service(request_id: str):
    request = db.assist_requests.get(request_id)
    if request is None or request["request_status"] != "ASSIGNED":
        return
    request["request_status"] = "IN_SERVICE"
    db.touch(request)


def finalize_request_if_complete(request_id: str):
    """When every sibling leg COMPLETED: IN_SERVICE -> COMPLETED; compute final charge;
    issue FINAL invoice; void PROVISIONAL; billing FINALIZED."""
    request = db.assist_requests.get(request_id)
    if request is None or request["request_status"] != "IN_SERVICE":
        return
    if request["billing_status"] == "DISPUTED":
        return
    legs = _legs_of_request(request_id)
    if not legs:
        return
    if not all(l["status"] == "COMPLETED" for l in legs):
        return
    request["final_charge_cents"] = pricing.request_final_total(request_id)
    request["request_status"] = "COMPLETED"
    request["billing_status"] = "FINALIZED"
    prov = _open_provisional_invoice(request_id)
    prov_id = prov["id"] if prov else None
    if prov is not None:
        _void_invoice(prov)
    inv = db.common_fields()
    inv.update({
        "assist_request_id": request_id,
        "invoice_kind": "FINAL",
        "amount_cents": request["final_charge_cents"],
        "status": "OPEN",
        "bill_to": request["bill_to"],
        "supersedes_invoice_id": prov_id,
        "writeoff_baseline_cents": None,
        "created_by_user_id": None,
    })
    db.invoices[inv["id"]] = inv
    db.touch(request)


# ---------------------------------------------------------------------------
# Posture transitions
# ---------------------------------------------------------------------------

def apply_posture_change(airport, new_posture: str):
    """Apply posture transition side effects. Caller has already validated the ladder."""
    old = airport["posture"]
    airport["posture"] = new_posture
    db.touch(airport)
    airport_id = airport["id"]

    if old == "NORMAL" and new_posture == "DEGRADED":
        _reprice_requests_at_airport(airport_id)
    elif old == "DEGRADED" and new_posture == "NORMAL":
        _reprice_requests_at_airport(airport_id)
    elif old == "DEGRADED" and new_posture == "LOCKDOWN":
        _lockdown_cascade(airport_id)
    elif old == "LOCKDOWN" and new_posture == "NORMAL":
        pass  # no auto-revival


def _reprice_requests_at_airport(airport_id: str):
    for request in list(db.assist_requests.values()):
        if request["request_status"] not in {"SUBMITTED", "ASSIGNED"}:
            continue
        if airport_id not in _request_airport_ids(request["id"]):
            continue
        pricing.recompute_provisional_for_request(request["id"])
        db.touch(request)


def _lockdown_cascade(airport_id: str):
    # Cancel legs PLANNED/DISPATCHED/AT_PICKUP at this airport.
    affected_requests = set()
    for leg in list(db.legs.values()):
        seg = db.segments.get(leg["segment_id"])
        if seg is None or seg["airport_id"] != airport_id:
            continue
        if leg["status"] not in {"PLANNED", "DISPATCHED", "AT_PICKUP"}:
            continue
        # Cancel any in-flight assignment for this leg (direct-cancel path).
        for asg in _assignments_of_leg(leg["id"]):
            if asg["status"] in {"DISPATCHED", "AT_PICKUP", "IN_TRANSIT", "AT_GATE"}:
                asg["status"] = "CANCELLED"
                db.touch(asg)
                _release_chair_no_maint(asg.get("wheelchair_asset_id"))
                agent = db.agents.get(asg["agent_id"])
                if agent is not None and agent.get("active_assignment_count", 0) > 0:
                    agent["active_assignment_count"] -= 1
                    db.touch(agent)
        leg["status"] = "CANCELLED"
        leg["cancel_reason"] = "LOCKDOWN"
        db.touch(leg)
        affected_requests.add(leg["assist_request_id"])
    for rid in affected_requests:
        _bubble_request_failure(rid)


# ---------------------------------------------------------------------------
# Ops epoch advance
# ---------------------------------------------------------------------------

def run_ops_epoch(airport):
    airport["ops_epoch"] = airport.get("ops_epoch", 0) + 1
    db.touch(airport)
    airport_id = airport["id"]
    now = db.now()

    # Agents past shift end -> OFF_SHIFT with unassign cascade
    for agent in list(db.agents.values()):
        if agent["airport_id"] != airport_id:
            continue
        if agent["status"] == "ACTIVE" and now > agent["shift_end_utc"]:
            agent["status"] = "OFF_SHIFT"
            db.touch(agent)
            for asg in list(db.assignments.values()):
                if asg["agent_id"] == agent["id"]:
                    cancel_assignment_for_agent_suspend(asg)

    # DISPATCHED assignments past scheduled_pickup + 30 min -> NO_SHOW
    for asg in list(db.assignments.values()):
        if asg["status"] != "DISPATCHED":
            continue
        leg = db.legs.get(asg["service_leg_id"])
        if leg is None:
            continue
        seg = db.segments.get(leg["segment_id"])
        if seg is None or seg["airport_id"] != airport_id:
            continue
        if now > leg["scheduled_pickup_utc"] + timedelta(minutes=30):
            asg["status"] = "NO_SHOW"
            db.touch(asg)
            _release_chair_no_maint(asg.get("wheelchair_asset_id"))
            agent = db.agents.get(asg["agent_id"])
            if agent is not None and agent.get("active_assignment_count", 0) > 0:
                agent["active_assignment_count"] -= 1
                db.touch(agent)
            # Bubble: if every other leg is terminal -> request FAILED
            request = db.assist_requests.get(asg["assist_request_id"])
            if request is not None:
                legs = _legs_of_request(request["id"])
                others_terminal = all(
                    l["status"] in {"COMPLETED", "NO_SHOW", "CANCELLED", "FAILED"}
                    for l in legs if l["id"] != leg["id"]
                )
                if others_terminal:
                    leg["status"] = "NO_SHOW"
                    db.touch(leg)
                    request["request_status"] = "FAILED"
                    prov = _open_provisional_invoice(request["id"])
                    if prov is not None:
                        _void_invoice(prov)
                    if request["billing_status"] == "PROVISIONAL":
                        request["billing_status"] = "UNBILLED"
                    db.touch(request)

    # Stale SUBMITTED requests: unchanged through 2 consecutive ticks -> FAILED
    for request in list(db.assist_requests.values()):
        if request["request_status"] != "SUBMITTED":
            continue
        if airport_id not in _request_airport_ids(request["id"]):
            continue
        last_epoch = request.get("_last_change_epoch", {}).get(airport_id, None)
        current_epoch = airport["ops_epoch"]
        if last_epoch is not None and current_epoch - last_epoch >= 2:
            request["request_status"] = "FAILED"
            prov = _open_provisional_invoice(request["id"])
            if prov is not None:
                _void_invoice(prov)
            if request["billing_status"] == "PROVISIONAL":
                request["billing_status"] = "UNBILLED"
            db.touch(request)


# ---------------------------------------------------------------------------
# Completion chain
# ---------------------------------------------------------------------------

def complete_assignment(asg, confirmer_user_id: str):
    """HANDED_OFF -> COMPLETED. Releases chair, computes final leg charge, bubbles."""
    now = db.now()
    leg = db.legs[asg["service_leg_id"]]
    request = db.assist_requests[asg["assist_request_id"]]
    segment = db.segments[leg["segment_id"]]
    airport = db.airports[segment["airport_id"]]

    asg["status"] = "COMPLETED"
    asg["completed_by_user_id"] = confirmer_user_id
    db.touch(asg)

    # Chair release (with maintenance threshold check)
    release_chair(asg.get("wheelchair_asset_id"))

    # Agent counters
    agent = db.agents.get(asg["agent_id"])
    if agent is not None:
        if agent.get("active_assignment_count", 0) > 0:
            agent["active_assignment_count"] -= 1
        scheduled_completion = asg.get("scheduled_completion_utc")
        if scheduled_completion is not None:
            delay_seconds = (now - scheduled_completion).total_seconds()
            if delay_seconds > 0:
                agent["cumulative_delay_minutes"] = (
                    agent.get("cumulative_delay_minutes", 0) + int(delay_seconds // 60)
                )
        db.touch(agent)

    leg["status"] = "COMPLETED"
    leg["completed_utc"] = now
    leg["final_leg_cents"] = pricing.final_leg_charge(leg, request, airport, segment)
    db.touch(leg)

    # Connection-chain onward recompute
    if leg["leg_kind"] == "CONNECTION_TRANSFER" and leg.get("onward_leg_id"):
        onward = db.legs.get(leg["onward_leg_id"])
        if onward is not None and onward["status"] not in {"CANCELLED", "FAILED", "COMPLETED", "NO_SHOW"}:
            onward_seg = db.segments[onward["segment_id"]]
            onward_airport = db.airports[onward_seg["airport_id"]]
            candidate = now + timedelta(minutes=onward_airport["meet_buffer_minutes"])
            if candidate > onward["scheduled_pickup_utc"]:
                onward["scheduled_pickup_utc"] = candidate
            onward["provisional_leg_cents"] = pricing.provisional_leg_charge(
                onward, request, onward_airport)
            db.touch(onward)

    db.touch(request)  # parent request version bump per assignment-event rule
    finalize_request_if_complete(request["id"])
