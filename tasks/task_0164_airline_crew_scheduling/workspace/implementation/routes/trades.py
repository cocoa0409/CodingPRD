"""TradeRequest endpoints."""
from flask import Blueprint, request, g

import store
import validators
import serializers
import responses
from auth import require_roles
from errors import raise_error
from services import faa_service, counters


bp = Blueprint("trades", __name__)


def _check_version(body, row):
    """OCC version check. If body contains 'version', compare; mismatch -> error."""
    if body is not None and isinstance(body, dict) and "version" in body:
        if body["version"] != row["version"]:
            raise_error("ERR_VERSION_CONFLICT",
                        "Version conflict on trade request.")


@bp.post("/trade-requests")
@require_roles("Pilot", "FlightAttendant")
def create_trade():
    body = request.get_json(silent=True)
    validators.require_dict(body)
    validators.require_fields(body, "initiator_assignment_id",
                              "counterparty_assignment_id", "counterparty_id")
    ia = validators.require_string(body, "initiator_assignment_id")
    ca = validators.require_string(body, "counterparty_assignment_id")
    counterparty = validators.require_string(body, "counterparty_id")

    ia_row = store.assignments.get(ia)
    ca_row = store.assignments.get(ca)
    if ia_row is None or ca_row is None:
        raise_error("ERR_REFERENCE_NOT_FOUND", "Assignment not found.")
    if store.crew_members.get(counterparty) is None:
        raise_error("ERR_REFERENCE_NOT_FOUND", "Counterparty crew member not found.")

    # Initiator must own the initiator_assignment
    if ia_row["crew_member_id"] != g.user_id:
        raise_error("ERR_FORBIDDEN", "Initiator does not own initiator_assignment_id.")
    if ca_row["crew_member_id"] != counterparty:
        raise_error("ERR_FORBIDDEN", "Counterparty does not own counterparty_assignment_id.")

    row = {
        "initiator_assignment_id": ia,
        "counterparty_assignment_id": ca,
        "initiator_id": g.user_id,
        "counterparty_id": counterparty,
        "state": "PROPOSED",
        "revision_count": 0,
    }
    store.init_common(row)
    store.trade_requests[row["id"]] = row
    return responses.success(serializers.trade_request(row), http_status=201)


@bp.post("/trade-requests/<t_id>/counter")
@require_roles("Pilot", "FlightAttendant")
def counter_trade(t_id):
    t = store.trade_requests.get(t_id)
    if t is None:
        raise_error("ERR_RESOURCE_NOT_FOUND", "Trade request not found.")
    body = request.get_json(silent=True) or {}
    _check_version(body, t)

    # State must be PROPOSED or COUNTER_PROPOSED
    if t["state"] not in {"PROPOSED", "COUNTER_PROPOSED"}:
        raise_error("ERR_INVALID_TRADE_STATE",
                    "Trade not in PROPOSED/COUNTER_PROPOSED.")
    if t["revision_count"] >= 3:
        raise_error("ERR_INVALID_TRADE_STATE",
                    "Trade has exhausted counter-proposal rounds.")
    if g.user_id != t["counterparty_id"]:
        raise_error("ERR_FORBIDDEN", "Only the current counterparty may counter-propose.")

    validators.require_dict(body)
    validators.require_fields(body, "new_initiator_assignment_id",
                              "new_counterparty_assignment_id")
    new_ia = validators.require_string(body, "new_initiator_assignment_id")
    new_ca = validators.require_string(body, "new_counterparty_assignment_id")
    if store.assignments.get(new_ia) is None or store.assignments.get(new_ca) is None:
        raise_error("ERR_REFERENCE_NOT_FOUND", "New assignment not found.")

    # Swap ids and roles
    t["initiator_assignment_id"] = new_ia
    t["counterparty_assignment_id"] = new_ca
    t["initiator_id"], t["counterparty_id"] = t["counterparty_id"], t["initiator_id"]
    t["revision_count"] += 1
    t["state"] = "COUNTER_PROPOSED" if t["state"] == "PROPOSED" else "PROPOSED"
    store.touch(t)
    return responses.success(serializers.trade_request(t))


@bp.post("/trade-requests/<t_id>/accept")
@require_roles("Pilot", "FlightAttendant")
def accept_trade(t_id):
    t = store.trade_requests.get(t_id)
    if t is None:
        raise_error("ERR_RESOURCE_NOT_FOUND", "Trade request not found.")
    body = request.get_json(silent=True) or {}
    _check_version(body, t)
    if t["state"] not in {"PROPOSED", "COUNTER_PROPOSED"}:
        raise_error("ERR_INVALID_TRADE_STATE",
                    "Trade not in a state to accept.")
    if g.user_id != t["counterparty_id"]:
        raise_error("ERR_FORBIDDEN", "Only the counterparty may accept.")
    t["state"] = "ACCEPTED"
    store.touch(t)
    return responses.success(serializers.trade_request(t))


@bp.post("/trade-requests/<t_id>/reject")
@require_roles("Pilot", "FlightAttendant")
def reject_trade(t_id):
    t = store.trade_requests.get(t_id)
    if t is None:
        raise_error("ERR_RESOURCE_NOT_FOUND", "Trade request not found.")
    body = request.get_json(silent=True) or {}
    _check_version(body, t)
    if t["state"] not in {"PROPOSED", "COUNTER_PROPOSED"}:
        raise_error("ERR_INVALID_TRADE_STATE",
                    "Trade not in a state to reject.")
    if g.user_id != t["counterparty_id"]:
        raise_error("ERR_FORBIDDEN", "Only the counterparty may reject.")
    t["state"] = "REJECTED"
    store.touch(t)
    return responses.success(serializers.trade_request(t))


@bp.post("/trade-requests/<t_id>/union-bless")
@require_roles("UnionSteward")
def union_bless(t_id):
    t = store.trade_requests.get(t_id)
    if t is None:
        raise_error("ERR_RESOURCE_NOT_FOUND", "Trade request not found.")
    local = g.union_local_id
    if not local:
        raise_error("ERR_VALIDATION_FAILED",
                    "X-Union-Local-Id header required for blessing.")
    blessings = store.union_blessings.setdefault(t_id, set())
    blessings.add(local)
    store.touch(t)
    return responses.success(serializers.trade_request(t))


@bp.post("/trade-requests/<t_id>/approve")
@require_roles("CrewScheduler")
def approve_trade(t_id):
    t = store.trade_requests.get(t_id)
    if t is None:
        raise_error("ERR_RESOURCE_NOT_FOUND", "Trade request not found.")
    body = request.get_json(silent=True) or {}
    _check_version(body, t)
    if t["state"] != "ACCEPTED":
        raise_error("ERR_INVALID_TRADE_STATE",
                    "Trade must be ACCEPTED to approve.")

    ia_row = store.assignments.get(t["initiator_assignment_id"])
    ca_row = store.assignments.get(t["counterparty_assignment_id"])
    if ia_row is None or ca_row is None:
        raise_error("ERR_REFERENCE_NOT_FOUND", "Trade assignment missing.")
    if ia_row["status"] != "SCHEDULED" or ca_row["status"] != "SCHEDULED":
        raise_error("ERR_INVALID_ASSIGNMENT_STATE",
                    "Both assignments must still be SCHEDULED.")

    initiator_crew = store.crew_members.get(t["initiator_id"])
    counterparty_crew = store.crew_members.get(t["counterparty_id"])
    if initiator_crew is None or counterparty_crew is None:
        raise_error("ERR_REFERENCE_NOT_FOUND", "Crew member missing.")

    # Identify pairings
    initiator_pairing = store.pairings.get(ia_row["pairing_id"])
    counterparty_pairing = store.pairings.get(ca_row["pairing_id"])
    if not initiator_pairing or not counterparty_pairing:
        raise_error("ERR_REFERENCE_NOT_FOUND", "Pairing missing.")

    # Trade legality
    if initiator_crew["rank"] != counterparty_crew["rank"]:
        raise_error("ERR_TRADE_RULE_VIOLATION",
                    "Crew members must share the same rank.")
    if ia_row["assigned_rank_slot"] != counterparty_crew["rank"]:
        raise_error("ERR_TRADE_RULE_VIOLATION",
                    "assigned_rank_slot of initiator must match counterparty rank.")
    if ca_row["assigned_rank_slot"] != initiator_crew["rank"]:
        raise_error("ERR_TRADE_RULE_VIOLATION",
                    "assigned_rank_slot of counterparty must match initiator rank.")

    if initiator_crew["union_local_id"] != counterparty_crew["union_local_id"]:
        blessings = store.union_blessings.get(t_id, set())
        required = {initiator_crew["union_local_id"], counterparty_crew["union_local_id"]}
        if not required.issubset(blessings):
            raise_error("ERR_TRADE_RULE_VIOLATION",
                        "Cross-local trade missing union-steward blessings.")

    # FAA check both legs (swap perspective).
    # Initiator's crew checked against counterparty's pairing.
    # Temporarily debit initiator's counters of their own pairing to simulate swap.
    def _faa_after_swap(crew, current_pairing, target_pairing):
        """Check FAA as if crew moves from current_pairing to target_pairing."""
        # Compute hypothetical counter values:
        block_self = int(current_pairing.get("total_block_minutes", 0) or 0)
        duty_self = int(current_pairing.get("total_duty_minutes", 0) or 0)
        hyp = dict(crew)
        hyp["cumulative_block_minutes_30d"] = max(
            0, crew.get("cumulative_block_minutes_30d", 0) - block_self
        )
        hyp["cumulative_duty_minutes_7d"] = max(
            0, crew.get("cumulative_duty_minutes_7d", 0) - duty_self
        )
        # FAA: now apply target_pairing on top
        return faa_service.faa_duty_rest_check(hyp, target_pairing, raise_on_fail=False)

    err1 = _faa_after_swap(initiator_crew, initiator_pairing, counterparty_pairing)
    if err1:
        raise_error(err1, "Initiator FAA check fails on counterparty pairing.")
    err2 = _faa_after_swap(counterparty_crew, counterparty_pairing, initiator_pairing)
    if err2:
        raise_error(err2, "Counterparty FAA check fails on initiator pairing.")

    # APPROVED -> EXECUTED within same request
    t["state"] = "APPROVED"
    store.touch(t)

    # Swap crew_member_id between the two assignments
    ia_row["crew_member_id"], ca_row["crew_member_id"] = (
        ca_row["crew_member_id"], ia_row["crew_member_id"]
    )
    store.touch(ia_row)
    store.touch(ca_row)

    # Recompute counters for both crew members
    counters.recompute_for_crew(initiator_crew)
    counters.recompute_for_crew(counterparty_crew)

    t["state"] = "EXECUTED"
    store.touch(t)
    return responses.success(serializers.trade_request(t))


@bp.delete("/trade-requests/<t_id>")
@require_roles("Pilot", "FlightAttendant")
def cancel_trade(t_id):
    t = store.trade_requests.get(t_id)
    if t is None:
        raise_error("ERR_RESOURCE_NOT_FOUND", "Trade request not found.")
    if t["state"] != "PROPOSED":
        raise_error("ERR_INVALID_TRADE_STATE",
                    "Only PROPOSED trades may be cancelled.")
    if g.user_id != t["initiator_id"]:
        raise_error("ERR_FORBIDDEN", "Only the initiator may cancel.")
    t["state"] = "CANCELLED"
    store.touch(t)
    return responses.no_content()


@bp.get("/trade-requests/<t_id>")
@require_roles("Pilot", "FlightAttendant", "CrewScheduler", "UnionSteward")
def get_trade(t_id):
    t = store.trade_requests.get(t_id)
    if t is None:
        raise_error("ERR_RESOURCE_NOT_FOUND", "Trade request not found.")
    if g.role in ("Pilot", "FlightAttendant"):
        if g.user_id not in (t["initiator_id"], t["counterparty_id"]):
            raise_error("ERR_FORBIDDEN", "Only parties to the trade may view.")
    return responses.success(serializers.trade_request(t))
