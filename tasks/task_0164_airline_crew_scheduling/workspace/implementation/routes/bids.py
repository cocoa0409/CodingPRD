"""Bid endpoints + bid-window awarding sweep."""
from flask import Blueprint, request, g

import store
import validators
import serializers
import responses
from auth import require_roles
from errors import raise_error
from clock import parse_iso, get_now
from services import pairing_service, faa_service, counters


bp = Blueprint("bids", __name__)


@bp.post("/bids")
@require_roles("Pilot", "FlightAttendant")
def create_bid():
    body = request.get_json(silent=True)
    validators.require_dict(body)
    validators.require_fields(body, "pairing_id", "preference_rank", "bid_window_id")

    pairing_id = validators.require_string(body, "pairing_id")
    pref = validators.require_int(body, "preference_rank", min_value=1)
    bid_window_id = validators.require_string(body, "bid_window_id")

    pairing = store.pairings.get(pairing_id)
    if pairing is None:
        raise_error("ERR_REFERENCE_NOT_FOUND", "Pairing not found.")

    crew_id = g.user_id
    crew = store.crew_members.get(crew_id)
    if crew is None:
        raise_error("ERR_REFERENCE_NOT_FOUND",
                    "Authenticated crew member does not exist.")

    # Pairing state check. PRD §3.2: "A bid against a pairing that is no
    # longer BIDDING_OPEN is rejected with ERR_BID_WINDOW_CLOSED if the
    # pairing has just left that state through an awarding sweep, or
    # with ERR_PAIRING_INVALID_STATE otherwise."
    if pairing["status"] != "BIDDING_OPEN":
        if pairing["status"] == "AWARDED":
            raise_error("ERR_BID_WINDOW_CLOSED",
                        "Bid window for this pairing has closed.")
        raise_error("ERR_PAIRING_INVALID_STATE",
                    "Pairing is not open for bidding.")

    # Bid-too-late: now + 24h > start_at -> reject
    start_at = parse_iso(pairing["start_at"]) if pairing.get("start_at") else None
    now = get_now()
    if start_at is not None and (start_at - now).total_seconds() < 24 * 3600:
        raise_error("ERR_BID_TOO_LATE",
                    "Bid submitted within 24h of Pairing.start_at.")

    # Duplicate preference within (crew_member_id, bid_window_id)
    for b in store.bids.values():
        if (b["crew_member_id"] == crew_id
                and b["bid_window_id"] == bid_window_id
                and b["preference_rank"] == pref
                and b["status"] in {"SUBMITTED", "AWARDED"}):
            raise_error("ERR_DUPLICATE_BID_PREFERENCE",
                        "preference_rank already used in this bid window.")

    # Crew availability
    if crew.get("status") != "ACTIVE":
        raise_error("ERR_CREW_NOT_AVAILABLE",
                    "Crew member is not ACTIVE.")

    row = {
        "crew_member_id": crew_id,
        "pairing_id": pairing_id,
        "preference_rank": pref,
        "bid_window_id": bid_window_id,
        "status": "SUBMITTED",
    }
    store.init_common(row)
    store.bids[row["id"]] = row
    return responses.success(serializers.bid(row), http_status=201)


@bp.delete("/bids/<bid_id>")
@require_roles("Pilot", "FlightAttendant")
def withdraw_bid(bid_id):
    b = store.bids.get(bid_id)
    if b is None:
        raise_error("ERR_RESOURCE_NOT_FOUND", "Bid not found.")
    if b["crew_member_id"] != g.user_id:
        raise_error("ERR_FORBIDDEN", "Cannot withdraw another user's bid.")
    if b["status"] != "SUBMITTED":
        raise_error("ERR_INVALID_ASSIGNMENT_STATE",
                    "Only SUBMITTED bids may be withdrawn.")
    pairing = store.pairings.get(b["pairing_id"])
    if pairing is None or pairing["status"] != "BIDDING_OPEN":
        raise_error("ERR_PAIRING_INVALID_STATE",
                    "Bid window not open; cannot withdraw.")
    b["status"] = "WITHDRAWN"
    store.touch(b)
    return responses.no_content()


# ---------------------- Awarding sweep ----------------------

@bp.post("/bid-windows/<window_id>/award")
@require_roles("CrewScheduler")
def award_window(window_id):
    # All pairings in BIDDING_OPEN with this window
    pairings_in_window = [
        p for p in store.pairings.values()
        if p.get("bid_window_id") == window_id and p["status"] == "BIDDING_OPEN"
    ]

    if not pairings_in_window:
        # Either already awarded or never opened
        if window_id in store.awarded_bid_windows:
            raise_error("ERR_BID_WINDOW_ALREADY_AWARDED",
                        "Bid window has already been awarded.")
        raise_error("ERR_PAIRING_INVALID_STATE",
                    "No BIDDING_OPEN pairings in this window.")

    # Order pairings: ascending start_at, then created_at
    pairings_in_window.sort(key=lambda p: (
        parse_iso(p["start_at"]) if p.get("start_at") else None,
        p["created_at"],
    ))

    award_summary = {
        "window_id": window_id,
        "pairings_processed": 0,
        "assignments_created": 0,
        "bids_awarded": 0,
        "bids_not_awarded": 0,
    }

    for pairing in pairings_in_window:
        comp = pairing.get("required_rank_composition") or {}
        mode = "SENIORITY_FIRST"
        if isinstance(comp, dict) and comp.get("mode") == "LOAD_BALANCED":
            mode = "LOAD_BALANCED"

        # Required rank slots
        rank_counts = {}
        for k, v in comp.items():
            if k == "mode":
                continue
            if isinstance(v, int) and v > 0:
                rank_counts[k] = v

        # Bids on this pairing
        bids_for_pairing = [
            b for b in store.bids.values()
            if b["pairing_id"] == pairing["id"] and b["status"] == "SUBMITTED"
        ]

        awarded_crews_in_pairing = set()

        for slot_rank, required_count in rank_counts.items():
            filled = 0
            # Candidate bids: matching rank, ACTIVE
            candidates = []
            for b in bids_for_pairing:
                crew = store.crew_members.get(b["crew_member_id"])
                if not crew or crew.get("status") != "ACTIVE":
                    continue
                if crew.get("rank") != slot_rank:
                    continue
                # Exclude crews already awarded in this pairing
                if crew["id"] in awarded_crews_in_pairing:
                    continue
                candidates.append((b, crew))

            # Sort candidates per mode
            if mode == "LOAD_BALANCED":
                candidates.sort(key=lambda x: (
                    x[1].get("cumulative_block_minutes_30d", 0),
                    x[1].get("union_seniority_number", 0),
                ))
            else:  # SENIORITY_FIRST
                candidates.sort(key=lambda x: x[1].get("union_seniority_number", 0))

            for b, crew in candidates:
                if filled >= required_count:
                    break
                # FAA check (silent)
                err = faa_service.faa_duty_rest_check(crew, pairing, raise_on_fail=False)
                if err is not None:
                    # Mark bid NOT_AWARDED with FAA reason; remove from candidate pool
                    b["status"] = "NOT_AWARDED"
                    store.touch(b)
                    award_summary["bids_not_awarded"] += 1
                    continue
                # Check slot not already covered
                slot_taken = False
                for a in store.assignments.values():
                    if (a["pairing_id"] == pairing["id"]
                            and a["assigned_rank_slot"] == slot_rank
                            and a["status"] in {"SCHEDULED", "IN_PROGRESS", "COMPLETED"}):
                        # If load_balanced needs N slots, multiple assignments may exist
                        # but we count those already created
                        pass
                # Award
                assignment_row = {
                    "pairing_id": pairing["id"],
                    "crew_member_id": crew["id"],
                    "assigned_rank_slot": slot_rank,
                    "source": "BID_AWARD",
                    "status": "SCHEDULED",
                    "scheduled_block_minutes": int(pairing.get("total_block_minutes", 0) or 0),
                    "actual_block_minutes": 0,
                    "pay_credit_minutes": 0,
                }
                store.init_common(assignment_row)
                store.assignments[assignment_row["id"]] = assignment_row
                award_summary["assignments_created"] += 1

                b["status"] = "AWARDED"
                store.touch(b)
                award_summary["bids_awarded"] += 1

                counters.increment_for_assignment(crew, pairing)
                awarded_crews_in_pairing.add(crew["id"])
                filled += 1

        # Mark remaining SUBMITTED bids on this pairing as NOT_AWARDED
        for b in bids_for_pairing:
            if b["status"] == "SUBMITTED":
                b["status"] = "NOT_AWARDED"
                store.touch(b)
                award_summary["bids_not_awarded"] += 1

        # Pairing -> AWARDED
        pairing["status"] = "AWARDED"
        store.touch(pairing)
        award_summary["pairings_processed"] += 1

    store.awarded_bid_windows.add(window_id)
    return responses.success(award_summary)
