"""TripRequest routes: create, get, list, submit, decision, cancel."""
from flask import Blueprint, request, g

import calc
from common import (get_json_body, require_fields, require_string,
                    require_nonneg_int, require_enum, parse_date, paginate,
                    list_response, date_diff_days)
from db import store, base_fields, touch
from errors import err
from middleware import require_roles
from response import success
from services import get_or_404, active_policy, perdiem_for_state

bp = Blueprint("trips", __name__)

# Statuses that participate in date-overlap collision (PRD 3.2)
OVERLAP_STATUSES = ("PENDING", "PENDING_OOP_APPROVAL", "AUTO_APPROVED", "APPROVED")


def _trip_view(t):
    return dict(t)


def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Closed-interval [start, end] overlap on both ends inclusive."""
    return a_start <= b_end and b_start <= a_end


@bp.route("/trip-requests", methods=["POST"])
@require_roles("Traveler")
def create_trip():
    body = get_json_body()
    require_fields(body, ["traveler_id", "destination_state", "start_date",
                          "end_date", "budget_total_cents"])
    traveler_id = require_string(body, "traveler_id")
    destination_state = require_string(body, "destination_state")
    # FK existence (left-to-right): traveler_id
    traveler = get_or_404(store.travelers, traveler_id)
    # ownership: acting Traveler must own (create own trip)
    if g.user_id != traveler_id:
        raise err("ERR_NOT_OWNER", "Traveler may only create trips for themselves")
    # body well-formedness
    start_str = require_string(body, "start_date")
    end_str = require_string(body, "end_date")
    start_d = parse_date(start_str, "start_date")
    end_d = parse_date(end_str, "end_date")
    budget = require_nonneg_int(body, "budget_total_cents")
    # business: exactly one ACTIVE policy
    policy = active_policy()
    if policy is None:
        raise err("ERR_NO_ACTIVE_POLICY", "No active travel policy")
    # business: date overlap vs traveler's live trips (closed interval)
    for t in store.trip_requests.values():
        if t["traveler_id"] != traveler_id:
            continue
        if t["status"] not in OVERLAP_STATUSES:
            continue
        if _intervals_overlap(start_d, end_d,
                              parse_date(t["start_date"], "start_date"),
                              parse_date(t["end_date"], "end_date")):
            raise err("ERR_TRIP_DATE_OVERLAP", "Trip dates overlap an existing trip")

    t = base_fields()
    t.update({
        "traveler_id": traveler_id,
        "policy_id": policy["id"],
        "destination_state": destination_state,
        "start_date": start_str,
        "end_date": end_str,
        "budget_total_cents": budget,
        "committed_amount_cents": None,
        "remaining_budget_cents": None,
        "requires_oop": None,
        "status": "PENDING",
    })
    store.trip_requests[t["id"]] = t
    return success(_trip_view(t), status=201)


@bp.route("/trip-requests/<trip_id>", methods=["GET"])
@require_roles("FinanceAdmin", "Traveler", "Approver")
def get_trip(trip_id):
    t = get_or_404(store.trip_requests, trip_id)
    return success(_trip_view(t))


@bp.route("/trip-requests", methods=["GET"])
@require_roles("FinanceAdmin", "Traveler", "Approver")
def list_trips():
    limit, offset = paginate()
    items = list(store.trip_requests.values())
    traveler_id = request.args.get("traveler_id")
    policy_id = request.args.get("policy_id")
    if traveler_id is not None:
        items = [t for t in items if t["traveler_id"] == traveler_id]
    if policy_id is not None:
        items = [t for t in items if t["policy_id"] == policy_id]
    page, pagination = list_response(items, limit, offset)
    return success([_trip_view(t) for t in page], pagination=pagination)


@bp.route("/trip-requests/<trip_id>/submit", methods=["POST"])
@require_roles("Traveler")
def submit_trip(trip_id):
    t = get_or_404(store.trip_requests, trip_id)
    # ownership
    if t["traveler_id"] != g.user_id:
        raise err("ERR_NOT_OWNER", "Traveler does not own this trip")
    # state
    if t["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Trip is not PENDING")
    # compute requires_oop
    pd = perdiem_for_state(t["destination_state"])
    lodging = pd["lodging_cap_cents"] if pd else 0
    mie = pd["mie_cents"] if pd else 0
    requires_oop = calc.trip_requires_oop(t, lodging, mie)
    t["requires_oop"] = requires_oop
    if requires_oop:
        t["status"] = "PENDING_OOP_APPROVAL"
    else:
        # AUTO_APPROVED then immediate join to APPROVED; init ledger
        t["status"] = "APPROVED"
        t["committed_amount_cents"] = 0
        t["remaining_budget_cents"] = t["budget_total_cents"]
    touch(t)
    return success(_trip_view(t))


@bp.route("/trip-requests/<trip_id>/decision", methods=["POST"])
@require_roles("Approver")
def decide_trip(trip_id):
    t = get_or_404(store.trip_requests, trip_id)
    traveler = store.travelers.get(t["traveler_id"])
    # ownership: acting Approver is traveler's manager
    if traveler is None or traveler["manager_id"] != g.user_id:
        raise err("ERR_NOT_OWNER", "Approver is not the traveler's manager")
    body = get_json_body()
    require_fields(body, ["decision"])
    decision = require_enum(body, "decision", {"APPROVE", "DENY"})
    # state
    if t["status"] != "PENDING_OOP_APPROVAL":
        raise err("ERR_INVALID_STATE", "Trip is not awaiting OOP approval")
    if decision == "APPROVE":
        t["status"] = "APPROVED"
        t["committed_amount_cents"] = 0
        t["remaining_budget_cents"] = t["budget_total_cents"]
    else:  # DENY
        t["status"] = "DENIED"
    touch(t)
    return success(_trip_view(t))


@bp.route("/trip-requests/<trip_id>/cancel", methods=["POST"])
@require_roles("Traveler")
def cancel_trip(trip_id):
    t = get_or_404(store.trip_requests, trip_id)
    if t["traveler_id"] != g.user_id:
        raise err("ERR_NOT_OWNER", "Traveler does not own this trip")
    if t["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Trip is not PENDING")
    t["status"] = "CANCELLED"
    touch(t)
    return success(_trip_view(t))
