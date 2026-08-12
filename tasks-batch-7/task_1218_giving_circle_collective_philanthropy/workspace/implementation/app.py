"""Giving Circle API — Flask entry point with all routes."""

import math
import os
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

from db import store
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_UNAUTHENTICATED, ERR_FORBIDDEN,
    ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_CYCLE_PHASE, ERR_MEMBERSHIP_NOT_ACTIVE,
    ERR_NONPROFIT_SUSPENDED, ERR_EIN_CONFLICT, ERR_DUPLICATE_NOMINATION,
    ERR_DUPLICATE_BALLOT, ERR_ALREADY_RSVPED, ERR_SESSION_FULL,
    ERR_SESSION_OVERLAP_BUFFER, ERR_SITE_VISIT_OVERLAP, ERR_INFO_ROUND_EXHAUSTED,
    ERR_VETTING_SCORE_BELOW_THRESHOLD, ERR_SITE_VISIT_REQUIRED, ERR_NOT_FINALIST,
    ERR_POINTS_BUDGET, ERR_BELOW_TIER_MINIMUM, ERR_REFUND_WINDOW_CLOSED,
    ERR_REFUND_UNDERFUNDS_AWARDS, ERR_VOTING_WINDOW_CLOSED, ERR_VOTING_STILL_OPEN,
    ERR_QUORUM_NOT_MET, ERR_NO_ACTIVE_MEMBERS, ERR_EMPTY_POOL, ERR_NO_NOMINATIONS,
    ERR_NO_FINALISTS, ERR_NO_PAYOUT_RELEASED, ERR_ROLLOVER_REQUIRED,
    ERR_INTERIM_REPORT_NOT_ACCEPTED, ERR_SEGREGATION_OF_DUTIES, ERR_STALE_VERSION,
    invalid_request, unauthenticated, forbidden, not_found, invalid_state, conflict,
)
from middleware import get_auth, require_roles
from response import (
    success_object, success_list, error_response, parse_pagination, paginate, iso3,
)
from services import (
    now_logical, parse_iso, round_half_up_cents, fee_on, stamp_new, touch,
    get_or_404, memberships_of_circle, contributions_of_cycle, nominations_of_cycle,
    ballots_of_cycle, payouts_of_award, reports_of_award, awards_of_cycle,
    recompute_circle_counts, recompute_cycle_ledger, recompute_award_payout_status,
    recompute_award_reporting_status, recompute_nonprofit_standing,
    recompute_vetting_score, compute_tally, pick_winner, evaluate_time_transitions,
)

ALL_ROLES = ("CircleAdmin", "FinanceOfficer", "Member", "GranteeContact")

app = Flask(__name__)


# ------------------------------------------------------------------ error handling

@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ERR_NOT_FOUND, 404, "Resource does not exist")


@app.errorhandler(405)
def handle_405(err):
    return error_response(ERR_INVALID_REQUEST, 400, "Method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err.error_id, err.http_status, err.message)
    return error_response(ERR_INVALID_REQUEST, 400, str(err) or "Bad request")


def body():
    """Return parsed JSON body as dict; empty/missing body -> {}."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise invalid_request("Request body must be valid JSON")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise invalid_request("Request body must be a JSON object")
    return data


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise invalid_request(f"Missing required field: {f}")


def require_int(data, field, minimum=None, maximum=None):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid_request(f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        raise invalid_request(f"Field {field} below minimum")
    if maximum is not None and v > maximum:
        raise invalid_request(f"Field {field} above maximum")
    return v


def require_enum(data, field, allowed):
    v = data.get(field)
    if v not in allowed:
        raise invalid_request(f"Field {field} must be one of {sorted(allowed)}")
    return v


# ------------------------------------------------------------------ logical clock

@app.route("/api/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("CircleAdmin")
    data = body()
    require_fields(data, ["to_iso8601"])
    try:
        new_time = parse_iso(data["to_iso8601"])
    except (ValueError, TypeError):
        raise invalid_request("to_iso8601 must be an ISO 8601 timestamp")
    store.clock = new_time
    evaluate_time_transitions()
    return success_object({"current_utc": iso3(store.clock)})


# ------------------------------------------------------------------ circles

@app.route("/api/circles", methods=["POST"])
def create_circle():
    require_roles("CircleAdmin")
    data = body()
    require_fields(data, ["name", "admin_fee_percent", "quorum_percent",
                          "standard_minimum_cents", "leader_minimum_cents",
                          "operating_reserve_cents", "vetting_profile"])
    name = data["name"]
    if not isinstance(name, str) or not name:
        raise invalid_request("name must be a non-empty string")
    admin_fee = require_int(data, "admin_fee_percent", 0, 20)
    quorum = require_int(data, "quorum_percent", 1, 100)
    std_min = require_int(data, "standard_minimum_cents", 1)
    leader_min = require_int(data, "leader_minimum_cents")
    if leader_min <= std_min:
        raise invalid_request("leader_minimum_cents must be > standard_minimum_cents")
    reserve = require_int(data, "operating_reserve_cents", 0)
    profile = require_enum(data, "vetting_profile", ("BALANCED", "EQUITY_FIRST"))

    circle = stamp_new({
        "name": name,
        "admin_fee_percent": admin_fee,
        "quorum_percent": quorum,
        "standard_minimum_cents": std_min,
        "leader_minimum_cents": leader_min,
        "operating_reserve_cents": reserve,
        "vetting_profile": profile,
        "active_member_count": 0,
        "renewed_member_count": 0,
    })
    store.circles[circle["id"]] = circle
    return success_object(circle, 201)


@app.route("/api/circles/<circle_id>", methods=["GET"])
def get_circle(circle_id):
    require_roles(*ALL_ROLES)
    circle = get_or_404(store.circles, circle_id)
    return success_object(circle)


@app.route("/api/circles", methods=["GET"])
def list_circles():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    items = sorted(store.circles.values(), key=lambda c: c["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list(page, total, limit, offset)


# ------------------------------------------------------------------ cycles

@app.route("/api/cycles", methods=["POST"])
def create_cycle():
    require_roles("CircleAdmin")
    data = body()
    require_fields(data, ["circle_id", "year_label"])
    circle = get_or_404(store.circles, data["circle_id"])
    year_label = data["year_label"]
    if not isinstance(year_label, str) or not year_label:
        raise invalid_request("year_label must be a non-empty string")

    cycle = stamp_new({
        "circle_id": circle["id"],
        "year_label": year_label,
        "phase": "DRAFT",
        "quorum_percent": circle["quorum_percent"],
        "admin_fee_percent": circle["admin_fee_percent"],
        "operating_reserve_cents": circle["operating_reserve_cents"],
        "voting_opens_at": None,
        "voting_closes_at": None,
        "active_member_snapshot": None,
        "received_total_cents": 0,
        "pledged_outstanding_cents": 0,
        "refunded_total_cents": 0,
        "released_total_cents": 0,
        "admin_fee_transferred_cents": 0,
        "rollover_in_cents": 0,
        "rollover_out_cents": 0,
        "pooled_balance_cents": 0,
        "grant_budget_provisional_cents": 0 - fee_on(0, circle["admin_fee_percent"]) - circle["operating_reserve_cents"],
        "grant_budget_final_cents": 0 - fee_on(0, circle["admin_fee_percent"]) - circle["operating_reserve_cents"],
        "budget_locked": False,
        "ballots_cast_count": 0,
    })
    store.cycles[cycle["id"]] = cycle
    return success_object(cycle, 201)


@app.route("/api/cycles/<cycle_id>", methods=["GET"])
def get_cycle(cycle_id):
    require_roles(*ALL_ROLES)
    cycle = get_or_404(store.cycles, cycle_id)
    return success_object(cycle)


@app.route("/api/cycles", methods=["GET"])
def list_cycles():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(store.cycles.values())
    circle_id = request.args.get("circle_id")
    phase = request.args.get("phase")
    if circle_id is not None:
        items = [c for c in items if c["circle_id"] == circle_id]
    if phase is not None:
        items = [c for c in items if c["phase"] == phase]
    items.sort(key=lambda c: c["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list(page, total, limit, offset)


PHASE_ORDER = ["DRAFT", "RECRUITMENT", "POOLING", "NOMINATION", "VETTING",
               "VOTING", "AWARD", "REPORTING", "CLOSED"]


@app.route("/api/cycles/<cycle_id>/advance", methods=["POST"])
def advance_cycle(cycle_id):
    user_id, _ = require_roles("CircleAdmin")
    data = body()
    cycle = get_or_404(store.cycles, cycle_id)

    # OCC first, per §2.9
    expected = data.get("expected_cycle_version")
    if expected is None:
        raise invalid_request("expected_cycle_version is required")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise invalid_request("expected_cycle_version must be an integer")
    if expected != cycle["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_cycle_version does not match current version")

    current = cycle["phase"]
    if current == "CLOSED":
        raise invalid_state("Cycle is CLOSED")
    nxt = PHASE_ORDER[PHASE_ORDER.index(current) + 1]
    now = now_logical()

    if current == "DRAFT":
        pass  # no guard beyond OCC
    elif current == "RECRUITMENT":
        active = sum(1 for m in memberships_of_circle(cycle["circle_id"])
                     if m["status"] == "ACTIVE")
        if active < 1:
            raise conflict(ERR_NO_ACTIVE_MEMBERS,
                           "No ACTIVE memberships in circle")
    elif current == "POOLING":
        if cycle["received_total_cents"] <= 0:
            raise conflict(ERR_EMPTY_POOL, "received_total_cents == 0")
    elif current == "NOMINATION":
        has_submitted = any(n["status"] == "SUBMITTED"
                            for n in nominations_of_cycle(cycle["id"]))
        if not has_submitted:
            raise conflict(ERR_NO_NOMINATIONS, "No SUBMITTED nomination")
    elif current == "VETTING":
        has_finalist = any(n["status"] == "FINALIST"
                           for n in nominations_of_cycle(cycle["id"]))
        if not has_finalist:
            raise conflict(ERR_NO_FINALISTS, "No FINALIST nomination")
    elif current == "VOTING":
        closes = parse_iso(cycle["voting_closes_at"])
        if not now > closes:
            raise conflict(ERR_VOTING_STILL_OPEN,
                           "Voting window has not closed")
        tally = compute_tally(cycle)
        if not tally["quorum_met"]:
            raise conflict(ERR_QUORUM_NOT_MET, "Quorum not met")
    elif current == "AWARD":
        released_any = False
        for award in awards_of_cycle(cycle["id"]):
            for p in payouts_of_award(award["id"]):
                if p["status"] == "RELEASED":
                    released_any = True
        if not released_any:
            raise conflict(ERR_NO_PAYOUT_RELEASED,
                           "No payout of this cycle's award is RELEASED")
    elif current == "REPORTING":
        for award in awards_of_cycle(cycle["id"]):
            for p in payouts_of_award(award["id"]):
                if p["status"] != "RELEASED":
                    raise invalid_state("Unreleased payouts remain")
            for r in reports_of_award(award["id"]):
                if r["status"] != "ACCEPTED":
                    raise invalid_state("Unaccepted reports remain")
        if cycle["pooled_balance_cents"] != 0:
            executed = any(
                d["status"] == "EXECUTED" and d["source_cycle_id"] == cycle["id"]
                for d in store.rollover_decisions.values())
            if not executed:
                raise conflict(ERR_ROLLOVER_REQUIRED,
                               "Residual pool requires an EXECUTED rollover decision")

    # ---- commit side effects per hop
    if current == "VETTING":  # -> VOTING
        cycle["voting_opens_at"] = iso3(now)
        closes = now + timedelta(days=7)
        cycle["voting_closes_at"] = iso3(closes)
        snapshot = sum(1 for m in memberships_of_circle(cycle["circle_id"])
                       if m["status"] == "ACTIVE")
        cycle["active_member_snapshot"] = snapshot
        cycle["phase"] = nxt
        touch(cycle)
    elif current == "VOTING":  # -> AWARD
        tally = compute_tally(cycle)
        winner = pick_winner(cycle, tally)
        # lock budget + transfer admin fee (computed on current received_total)
        received = cycle["received_total_cents"]
        fee = round_half_up_cents(Decimal(received) *
                                  Decimal(cycle["admin_fee_percent"]) / Decimal(100))
        cycle["admin_fee_transferred_cents"] = fee
        cycle["budget_locked"] = True
        cycle["phase"] = nxt

        finalists = [n for n in nominations_of_cycle(cycle["id"])
                     if n["status"] == "FINALIST"]
        for n in finalists:
            if winner is not None and n["id"] == winner["id"]:
                n["status"] = "AWARDED"
            else:
                n["status"] = "NOT_SELECTED"
            touch(n)

        if winner is not None:
            winner_fp = next(fp for fp in tally["finalist_points"]
                             if fp["nomination_id"] == winner["id"])
            winner_points = winner_fp["total_points"]
            total_cast = tally["total_points_cast"]
            final_budget = cycle["grant_budget_final_cents"]
            if total_cast > 0:
                share = Decimal(winner_points) / Decimal(total_cast)
                raw = share * Decimal(final_budget)
                raw_int = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            else:
                raw_int = 0
            amount = min(final_budget, max(50000, raw_int))

            award = stamp_new({
                "cycle_id": cycle["id"],
                "nomination_id": winner["id"],
                "nonprofit_id": winner["nonprofit_id"],
                "amount_cents": amount,
                "winner_points": winner_points,
                "payout_status": "UNPAID",
                "reporting_status": "AWAITING_REPORTS",
            })
            store.awards[award["id"]] = award

            t1 = (amount * 70) // 100
            t2 = amount - t1
            for tranche, amt in ((1, t1), (2, t2)):
                payout = stamp_new({
                    "award_id": award["id"],
                    "tranche": tranche,
                    "amount_cents": amt,
                    "status": "SCHEDULED",
                    "requested_by_user_id": user_id,
                    "approved_by_user_id": None,
                })
                store.payouts[payout["id"]] = payout

            for rtype, days in (("INTERIM", 90), ("FINAL", 365)):
                report = stamp_new({
                    "award_id": award["id"],
                    "report_type": rtype,
                    "due_at": iso3(now + timedelta(days=days)),
                    "status": "DUE",
                    "narrative": None,
                    "expenditure_cents": None,
                    "submitted_at": None,
                    "reject_reason": None,
                })
                store.reports[report["id"]] = report

        # recompute ledger last so pooled balance reflects the fee transfer
        # (recompute_cycle_ledger touches the cycle, bumping version by 1)
        recompute_cycle_ledger(cycle)
    elif current == "REPORTING":  # -> CLOSED
        for m in memberships_of_circle(cycle["circle_id"]):
            if m["status"] == "ACTIVE":
                m["status"] = "RENEWAL_DUE"
                touch(m)
        cycle["phase"] = nxt
        touch(cycle)
        circle = store.circles.get(cycle["circle_id"])
        if circle:
            recompute_circle_counts(circle)
    else:
        cycle["phase"] = nxt
        touch(cycle)

    return success_object(cycle)


@app.route("/api/cycles/<cycle_id>/ledger", methods=["GET"])
def cycle_ledger(cycle_id):
    require_roles(*ALL_ROLES)
    cycle = get_or_404(store.cycles, cycle_id)
    data = {
        "received_total_cents": cycle["received_total_cents"],
        "pledged_outstanding_cents": cycle["pledged_outstanding_cents"],
        "refunded_total_cents": cycle["refunded_total_cents"],
        "released_total_cents": cycle["released_total_cents"],
        "admin_fee_transferred_cents": cycle["admin_fee_transferred_cents"],
        "rollover_in_cents": cycle["rollover_in_cents"],
        "rollover_out_cents": cycle["rollover_out_cents"],
        "pooled_balance_cents": cycle["pooled_balance_cents"],
        "grant_budget_provisional_cents": cycle["grant_budget_provisional_cents"],
        "grant_budget_final_cents": cycle["grant_budget_final_cents"],
    }
    return success_object(data)


@app.route("/api/cycles/<cycle_id>/tally", methods=["GET"])
def cycle_tally(cycle_id):
    require_roles(*ALL_ROLES)
    cycle = get_or_404(store.cycles, cycle_id)
    return success_object(compute_tally(cycle))


# ------------------------------------------------------------------ members

@app.route("/api/members", methods=["POST"])
def create_member():
    require_roles("CircleAdmin")
    data = body()
    require_fields(data, ["full_name", "email"])
    full_name = data["full_name"]
    email = data["email"]
    if not isinstance(full_name, str) or not full_name:
        raise invalid_request("full_name must be a non-empty string")
    if not isinstance(email, str) or not email:
        raise invalid_request("email must be a non-empty string")
    for m in store.members.values():
        if m["email"].lower() == email.lower():
            raise invalid_request("Duplicate member email")
    member = stamp_new({"full_name": full_name, "email": email})
    store.members[member["id"]] = member
    return success_object(member, 201)


@app.route("/api/members/<member_id>", methods=["GET"])
def get_member(member_id):
    require_roles(*ALL_ROLES)
    member = get_or_404(store.members, member_id)
    return success_object(member)


@app.route("/api/members", methods=["GET"])
def list_members():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(store.members.values())
    email = request.args.get("email")
    if email is not None:
        items = [m for m in items if m["email"] == email]
    items.sort(key=lambda m: m["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list(page, total, limit, offset)


# ------------------------------------------------------------------ memberships

@app.route("/api/memberships", methods=["POST"])
def create_membership():
    require_roles("CircleAdmin")
    data = body()
    require_fields(data, ["member_id", "circle_id", "tier"])
    member = get_or_404(store.members, data["member_id"])
    circle = get_or_404(store.circles, data["circle_id"])
    tier = require_enum(data, "tier", ("STANDARD", "LEADER"))
    membership = stamp_new({
        "circle_id": circle["id"],
        "member_id": member["id"],
        "tier": tier,
        "status": "INVITED",
        "renewal_count": 0,
        "credit_balance_cents": 0,
    })
    store.memberships[membership["id"]] = membership
    return success_object(membership, 201)


@app.route("/api/memberships/<membership_id>", methods=["GET"])
def get_membership(membership_id):
    require_roles(*ALL_ROLES)
    membership = get_or_404(store.memberships, membership_id)
    return success_object(membership)


@app.route("/api/memberships", methods=["GET"])
def list_memberships():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(store.memberships.values())
    circle_id = request.args.get("circle_id")
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    if circle_id is not None:
        items = [m for m in items if m["circle_id"] == circle_id]
    if member_id is not None:
        items = [m for m in items if m["member_id"] == member_id]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    items.sort(key=lambda m: m["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list(page, total, limit, offset)


def _void_pledged_contributions(membership):
    for c in list(store.contributions.values()):
        if c["membership_id"] == membership["id"] and c["status"] == "PLEDGED":
            c["status"] = "VOIDED"
            touch(c)
            cycle = store.cycles.get(c["cycle_id"])
            if cycle:
                recompute_cycle_ledger(cycle)


@app.route("/api/memberships/<membership_id>/accept", methods=["POST"])
def accept_membership(membership_id):
    user_id, _ = require_roles("Member")
    membership = get_or_404(store.memberships, membership_id)
    if membership["member_id"] != user_id:
        raise forbidden("Member may only accept own membership")
    if membership["status"] != "INVITED":
        raise invalid_state("Membership not INVITED")
    membership["status"] = "ACTIVE"
    touch(membership)
    circle = store.circles.get(membership["circle_id"])
    if circle:
        recompute_circle_counts(circle)
    return success_object(membership)


@app.route("/api/memberships/<membership_id>/renew", methods=["POST"])
def renew_membership(membership_id):
    user_id, _ = require_roles("Member")
    membership = get_or_404(store.memberships, membership_id)
    if membership["member_id"] != user_id:
        raise forbidden("Member may only renew own membership")
    if membership["status"] != "RENEWAL_DUE":
        raise invalid_state("Membership not RENEWAL_DUE")
    membership["status"] = "ACTIVE"
    membership["renewal_count"] = membership.get("renewal_count", 0) + 1
    touch(membership)
    circle = store.circles.get(membership["circle_id"])
    if circle:
        recompute_circle_counts(circle)
    return success_object(membership)


@app.route("/api/memberships/<membership_id>/lapse", methods=["POST"])
def lapse_membership(membership_id):
    require_roles("CircleAdmin")
    membership = get_or_404(store.memberships, membership_id)
    if membership["status"] != "RENEWAL_DUE":
        raise invalid_state("Membership not RENEWAL_DUE")
    membership["status"] = "LAPSED"
    touch(membership)
    circle = store.circles.get(membership["circle_id"])
    if circle:
        recompute_circle_counts(circle)
    return success_object(membership)


@app.route("/api/memberships/<membership_id>/withdraw", methods=["POST"])
def withdraw_membership(membership_id):
    user_id, _ = require_roles("Member")
    membership = get_or_404(store.memberships, membership_id)
    if membership["member_id"] != user_id:
        raise forbidden("Member may only withdraw own membership")
    if membership["status"] not in ("ACTIVE", "RENEWAL_DUE"):
        raise invalid_state("Membership cannot be withdrawn from this state")
    membership["status"] = "WITHDRAWN"
    touch(membership)
    _void_pledged_contributions(membership)
    circle = store.circles.get(membership["circle_id"])
    if circle:
        recompute_circle_counts(circle)
    return success_object(membership)


# ------------------------------------------------------------------ contributions

@app.route("/api/contributions", methods=["POST"])
def create_contribution():
    user_id, _ = require_roles("Member")
    data = body()
    require_fields(data, ["cycle_id", "membership_id", "amount_cents"])
    cycle = get_or_404(store.cycles, data["cycle_id"])
    membership = get_or_404(store.memberships, data["membership_id"])
    if membership["member_id"] != user_id:
        raise forbidden("Member may only pledge from own membership")
    amount = data["amount_cents"]
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise invalid_request("amount_cents must be a positive integer")
    if cycle["phase"] != "POOLING":
        raise conflict(ERR_CYCLE_PHASE, "Cycle not in POOLING")
    if membership["status"] != "ACTIVE":
        raise conflict(ERR_MEMBERSHIP_NOT_ACTIVE, "Membership not ACTIVE")
    circle = store.circles.get(membership["circle_id"])
    minimum = (circle["leader_minimum_cents"] if membership["tier"] == "LEADER"
               else circle["standard_minimum_cents"])
    if amount < minimum:
        raise conflict(ERR_BELOW_TIER_MINIMUM,
                       "Contribution below tier minimum")
    contribution = stamp_new({
        "cycle_id": cycle["id"],
        "membership_id": membership["id"],
        "amount_cents": amount,
        "status": "PLEDGED",
        "received_at": None,
    })
    store.contributions[contribution["id"]] = contribution
    recompute_cycle_ledger(cycle)
    return success_object(contribution, 201)


@app.route("/api/contributions/<contribution_id>", methods=["GET"])
def get_contribution(contribution_id):
    require_roles(*ALL_ROLES)
    contribution = get_or_404(store.contributions, contribution_id)
    return success_object(contribution)


@app.route("/api/contributions", methods=["GET"])
def list_contributions():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(store.contributions.values())
    cycle_id = request.args.get("cycle_id")
    membership_id = request.args.get("membership_id")
    status = request.args.get("status")
    if cycle_id is not None:
        items = [c for c in items if c["cycle_id"] == cycle_id]
    if membership_id is not None:
        items = [c for c in items if c["membership_id"] == membership_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda c: c["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list(page, total, limit, offset)


@app.route("/api/contributions/<contribution_id>/receive", methods=["POST"])
def receive_contribution(contribution_id):
    require_roles("CircleAdmin")
    contribution = get_or_404(store.contributions, contribution_id)
    if contribution["status"] != "PLEDGED":
        raise invalid_state("Contribution not PLEDGED")
    cycle = store.cycles.get(contribution["cycle_id"])
    if cycle is None:
        raise not_found("Cycle does not exist")
    if cycle["phase"] != "POOLING":
        raise conflict(ERR_CYCLE_PHASE, "Cycle not in POOLING")
    contribution["status"] = "RECEIVED"
    contribution["received_at"] = iso3(now_logical())
    touch(contribution)
    recompute_cycle_ledger(cycle)
    return success_object(contribution)


REFUND_WINDOW_PHASES = ("POOLING", "NOMINATION", "VETTING", "VOTING", "AWARD")


@app.route("/api/contributions/<contribution_id>/request-refund", methods=["POST"])
def request_refund(contribution_id):
    user_id, _ = require_roles("Member")
    contribution = get_or_404(store.contributions, contribution_id)
    membership = store.memberships.get(contribution["membership_id"])
    if membership is None or membership["member_id"] != user_id:
        raise forbidden("Member may only request refund on own contribution")
    if contribution["status"] != "RECEIVED":
        raise invalid_state("Contribution not RECEIVED")
    cycle = store.cycles.get(contribution["cycle_id"])
    if cycle is None:
        raise not_found("Cycle does not exist")
    if cycle["phase"] not in REFUND_WINDOW_PHASES:
        raise conflict(ERR_REFUND_WINDOW_CLOSED, "Refund window closed")
    contribution["status"] = "REFUND_REQUESTED"
    touch(contribution)
    return success_object(contribution)


@app.route("/api/contributions/<contribution_id>/approve-refund", methods=["POST"])
def approve_refund(contribution_id):
    require_roles("CircleAdmin")
    contribution = get_or_404(store.contributions, contribution_id)
    if contribution["status"] != "REFUND_REQUESTED":
        raise invalid_state("Contribution not REFUND_REQUESTED")
    cycle = store.cycles.get(contribution["cycle_id"])
    if cycle is None:
        raise not_found("Cycle does not exist")
    obligations = 0
    for award in awards_of_cycle(cycle["id"]):
        for p in payouts_of_award(award["id"]):
            if p["status"] in ("SCHEDULED", "APPROVED"):
                obligations += p["amount_cents"]
    if cycle["pooled_balance_cents"] - contribution["amount_cents"] < obligations:
        raise conflict(ERR_REFUND_UNDERFUNDS_AWARDS,
                       "Refund would underfund award obligations")
    contribution["status"] = "REFUNDED"
    touch(contribution)
    recompute_cycle_ledger(cycle)
    return success_object(contribution)


@app.route("/api/contributions/<contribution_id>/deny-refund", methods=["POST"])
def deny_refund(contribution_id):
    require_roles("CircleAdmin")
    contribution = get_or_404(store.contributions, contribution_id)
    if contribution["status"] != "REFUND_REQUESTED":
        raise invalid_state("Contribution not REFUND_REQUESTED")
    contribution["status"] = "RECEIVED"
    touch(contribution)
    return success_object(contribution)


# ------------------------------------------------------------------ nonprofits

@app.route("/api/nonprofits", methods=["POST"])
def create_nonprofit():
    require_roles("CircleAdmin")
    data = body()
    require_fields(data, ["ein", "legal_name", "mission_category"])
    ein = data["ein"]
    if not isinstance(ein, str) or not ein:
        raise invalid_request("ein must be a non-empty string")
    if not isinstance(data["legal_name"], str) or not data["legal_name"]:
        raise invalid_request("legal_name must be a non-empty string")
    if not isinstance(data["mission_category"], str) or not data["mission_category"]:
        raise invalid_request("mission_category must be a non-empty string")
    for n in store.nonprofits.values():
        if n["ein"] == ein:
            raise conflict(ERR_EIN_CONFLICT, "EIN already registered")
    nonprofit = stamp_new({
        "ein": ein,
        "legal_name": data["legal_name"],
        "mission_category": data["mission_category"],
        "standing": "GOOD",
    })
    store.nonprofits[nonprofit["id"]] = nonprofit
    return success_object(nonprofit, 201)


@app.route("/api/nonprofits/<nonprofit_id>", methods=["GET"])
def get_nonprofit(nonprofit_id):
    require_roles(*ALL_ROLES)
    nonprofit = get_or_404(store.nonprofits, nonprofit_id)
    return success_object(nonprofit)


@app.route("/api/nonprofits", methods=["GET"])
def list_nonprofits():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(store.nonprofits.values())
    ein = request.args.get("ein")
    standing = request.args.get("standing")
    if ein is not None:
        items = [n for n in items if n["ein"] == ein]
    if standing is not None:
        items = [n for n in items if n["standing"] == standing]
    items.sort(key=lambda n: n["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list(page, total, limit, offset)


# ------------------------------------------------------------------ nominations

@app.route("/api/nominations", methods=["POST"])
def create_nomination():
    user_id, _ = require_roles("Member")
    data = body()
    require_fields(data, ["cycle_id", "nonprofit_id", "statement"])
    cycle = get_or_404(store.cycles, data["cycle_id"])
    nonprofit = get_or_404(store.nonprofits, data["nonprofit_id"])
    statement = data["statement"]
    if not isinstance(statement, str) or not statement:
        raise invalid_request("statement must be a non-empty string")
    if cycle["phase"] != "NOMINATION":
        raise conflict(ERR_CYCLE_PHASE, "Cycle not in NOMINATION")
    # resolve acting member's ACTIVE membership in the cycle's circle
    membership = None
    for m in memberships_of_circle(cycle["circle_id"]):
        if m["member_id"] == user_id and m["status"] == "ACTIVE":
            membership = m
            break
    if membership is None:
        raise conflict(ERR_MEMBERSHIP_NOT_ACTIVE,
                       "Acting member has no ACTIVE membership in this circle")
    if nonprofit["standing"] != "GOOD":
        raise conflict(ERR_NONPROFIT_SUSPENDED, "Nonprofit standing is SUSPENDED")
    for n in nominations_of_cycle(cycle["id"]):
        if n["nominated_by_membership_id"] == membership["id"]:
            raise conflict(ERR_DUPLICATE_NOMINATION,
                           "Membership already nominated in this cycle")
    nomination = stamp_new({
        "cycle_id": cycle["id"],
        "nonprofit_id": nonprofit["id"],
        "nominated_by_membership_id": membership["id"],
        "statement": statement,
        "status": "SUBMITTED",
        "financial_health": None,
        "mission_alignment": None,
        "org_capacity": None,
        "vetting_score": None,
        "info_rounds_used": 0,
    })
    store.nominations[nomination["id"]] = nomination
    return success_object(nomination, 201)


@app.route("/api/nominations/<nomination_id>", methods=["GET"])
def get_nomination(nomination_id):
    require_roles(*ALL_ROLES)
    nomination = get_or_404(store.nominations, nomination_id)
    return success_object(nomination)


@app.route("/api/nominations", methods=["GET"])
def list_nominations():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(store.nominations.values())
    cycle_id = request.args.get("cycle_id")
    nonprofit_id = request.args.get("nonprofit_id")
    nominated_by = request.args.get("nominated_by_membership_id")
    status = request.args.get("status")
    if cycle_id is not None:
        items = [n for n in items if n["cycle_id"] == cycle_id]
    if nonprofit_id is not None:
        items = [n for n in items if n["nonprofit_id"] == nonprofit_id]
    if nominated_by is not None:
        items = [n for n in items if n["nominated_by_membership_id"] == nominated_by]
    if status is not None:
        items = [n for n in items if n["status"] == status]
    items.sort(key=lambda n: n["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list(page, total, limit, offset)


@app.route("/api/nominations/<nomination_id>", methods=["PATCH"])
def patch_nomination(nomination_id):
    require_roles("CircleAdmin")
    nomination = get_or_404(store.nominations, nomination_id)
    data = body()
    touched = False
    for field in ("financial_health", "mission_alignment", "org_capacity"):
        if field in data and data[field] is not None:
            v = data[field]
            if isinstance(v, bool) or not isinstance(v, int) or v < 0 or v > 100:
                raise invalid_request(f"{field} must be an integer 0-100")
            nomination[field] = v
            touched = True
    if touched:
        recompute_vetting_score(nomination)
        touch(nomination)
    return success_object(nomination)


@app.route("/api/nominations/<nomination_id>/start-vetting", methods=["POST"])
def start_vetting(nomination_id):
    require_roles("CircleAdmin")
    nomination = get_or_404(store.nominations, nomination_id)
    cycle = store.cycles.get(nomination["cycle_id"])
    if cycle is None:
        raise not_found("Cycle does not exist")
    if cycle["phase"] != "VETTING":
        raise conflict(ERR_CYCLE_PHASE, "Cycle not in VETTING")
    if nomination["status"] != "SUBMITTED":
        raise invalid_state("Nomination not SUBMITTED")
    nomination["status"] = "VETTING"
    touch(nomination)
    return success_object(nomination)


@app.route("/api/nominations/<nomination_id>/request-info", methods=["POST"])
def request_info(nomination_id):
    require_roles("CircleAdmin")
    nomination = get_or_404(store.nominations, nomination_id)
    if nomination["status"] != "VETTING":
        raise invalid_state("Nomination not VETTING")
    if nomination["info_rounds_used"] >= 2:
        raise conflict(ERR_INFO_ROUND_EXHAUSTED, "No further info rounds")
    nomination["status"] = "NEEDS_INFO"
    nomination["info_rounds_used"] += 1
    touch(nomination)
    return success_object(nomination)


@app.route("/api/nominations/<nomination_id>/submit-info", methods=["POST"])
def submit_info(nomination_id):
    user_id, _ = require_roles("GranteeContact")
    nomination = get_or_404(store.nominations, nomination_id)
    if nomination["nonprofit_id"] != user_id:
        raise forbidden("GranteeContact may only act on own nonprofit's nomination")
    if nomination["status"] != "NEEDS_INFO":
        raise invalid_state("Nomination not NEEDS_INFO")
    nomination["status"] = "VETTING"
    touch(nomination)
    return success_object(nomination)


@app.route("/api/nominations/<nomination_id>/advance-to-finalist", methods=["POST"])
def advance_to_finalist(nomination_id):
    require_roles("CircleAdmin")
    nomination = get_or_404(store.nominations, nomination_id)
    cycle = store.cycles.get(nomination["cycle_id"])
    if cycle is None:
        raise not_found("Cycle does not exist")
    if cycle["phase"] != "VETTING":
        raise conflict(ERR_CYCLE_PHASE, "Cycle not in VETTING")
    if nomination["status"] != "VETTING":
        raise invalid_state("Nomination not VETTING")
    nonprofit = store.nonprofits.get(nomination["nonprofit_id"])
    if nonprofit is None:
        raise not_found("Nonprofit does not exist")
    if nonprofit["standing"] != "GOOD":
        raise conflict(ERR_NONPROFIT_SUSPENDED, "Nonprofit standing is SUSPENDED")
    score = nomination.get("vetting_score")
    if score is None or score < 70:
        raise conflict(ERR_VETTING_SCORE_BELOW_THRESHOLD,
                       "vetting_score < 70")
    has_completed_visit = any(
        v["nomination_id"] == nomination["id"] and v["status"] == "COMPLETED"
        for v in store.site_visits.values())
    if not has_completed_visit:
        raise conflict(ERR_SITE_VISIT_REQUIRED,
                       "Finalist advance requires a COMPLETED site visit")
    nomination["status"] = "FINALIST"
    touch(nomination)
    return success_object(nomination)


@app.route("/api/nominations/<nomination_id>/reject", methods=["POST"])
def reject_nomination(nomination_id):
    require_roles("CircleAdmin")
    nomination = get_or_404(store.nominations, nomination_id)
    if nomination["status"] not in ("SUBMITTED", "VETTING", "NEEDS_INFO"):
        raise invalid_state("Nomination cannot be rejected from this state")
    nomination["status"] = "REJECTED"
    touch(nomination)
    return success_object(nomination)


@app.route("/api/nominations/<nomination_id>/withdraw", methods=["POST"])
def withdraw_nomination(nomination_id):
    user_id, _ = require_roles("Member")
    nomination = get_or_404(store.nominations, nomination_id)
    membership = store.memberships.get(nomination["nominated_by_membership_id"])
    if membership is None or membership["member_id"] != user_id:
        raise forbidden("Member may only withdraw own nomination")
    if nomination["status"] not in ("SUBMITTED", "VETTING", "NEEDS_INFO"):
        raise invalid_state("Nomination cannot be withdrawn from this state")
    nomination["status"] = "WITHDRAWN"
    touch(nomination)
    return success_object(nomination)


# ------------------------------------------------------------------ site visits

def _visit_overlaps(nonprofit_id, starts, ends, exclude_id=None):
    """Half-open overlap against SCHEDULED/COMPLETED visits of the same nonprofit."""
    for v in store.site_visits.values():
        if exclude_id is not None and v["id"] == exclude_id:
            continue
        nom = store.nominations.get(v["nomination_id"])
        if nom is None or nom["nonprofit_id"] != nonprofit_id:
            continue
        if v["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        v_start = parse_iso(v["starts_at"])
        v_end = parse_iso(v["ends_at"])
        # half-open: overlap iff new.start < existing.end and existing.start < new.end
        if starts < v_end and v_start < ends:
            return True
    return False


@app.route("/api/site-visits", methods=["POST"])
def create_site_visit():
    require_roles("CircleAdmin")
    data = body()
    require_fields(data, ["nomination_id", "starts_at", "ends_at"])
    nomination = get_or_404(store.nominations, data["nomination_id"])
    try:
        starts = parse_iso(data["starts_at"])
        ends = parse_iso(data["ends_at"])
    except (ValueError, TypeError):
        raise invalid_request("starts_at / ends_at must be ISO 8601 timestamps")
    if not starts < ends:
        raise invalid_request("starts_at must be strictly earlier than ends_at")
    if _visit_overlaps(nomination["nonprofit_id"], starts, ends):
        raise conflict(ERR_SITE_VISIT_OVERLAP,
                       "Visit overlaps another visit for the same nonprofit")
    visit = stamp_new({
        "nomination_id": nomination["id"],
        "starts_at": iso3(starts),
        "ends_at": iso3(ends),
        "status": "SCHEDULED",
        "findings_note": None,
    })
    store.site_visits[visit["id"]] = visit
    return success_object(visit, 201)


@app.route("/api/site-visits/<visit_id>", methods=["GET"])
def get_site_visit(visit_id):
    require_roles(*ALL_ROLES)
    visit = get_or_404(store.site_visits, visit_id)
    return success_object(visit)


@app.route("/api/site-visits", methods=["GET"])
def list_site_visits():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(store.site_visits.values())
    nomination_id = request.args.get("nomination_id")
    status = request.args.get("status")
    if nomination_id is not None:
        items = [v for v in items if v["nomination_id"] == nomination_id]
    if status is not None:
        items = [v for v in items if v["status"] == status]
    items.sort(key=lambda v: v["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list(page, total, limit, offset)


@app.route("/api/site-visits/<visit_id>/complete", methods=["POST"])
def complete_site_visit(visit_id):
    require_roles("CircleAdmin")
    visit = get_or_404(store.site_visits, visit_id)
    data = body()
    if visit["status"] != "SCHEDULED":
        raise invalid_state("Visit not SCHEDULED")
    if now_logical() < parse_iso(visit["ends_at"]):
        raise invalid_state("Visit has not ended yet")
    if "findings_note" in data and data["findings_note"] is not None:
        if not isinstance(data["findings_note"], str):
            raise invalid_request("findings_note must be a string")
        visit["findings_note"] = data["findings_note"]
    visit["status"] = "COMPLETED"
    touch(visit)
    return success_object(visit)


@app.route("/api/site-visits/<visit_id>/cancel", methods=["POST"])
def cancel_site_visit(visit_id):
    require_roles("CircleAdmin")
    visit = get_or_404(store.site_visits, visit_id)
    if visit["status"] != "SCHEDULED":
        raise invalid_state("Visit not SCHEDULED")
    visit["status"] = "CANCELLED"
    touch(visit)
    return success_object(visit)


@app.route("/api/site-visits/<visit_id>/reschedule", methods=["POST"])
def reschedule_site_visit(visit_id):
    require_roles("CircleAdmin")
    visit = get_or_404(store.site_visits, visit_id)
    data = body()
    require_fields(data, ["starts_at", "ends_at"])
    if visit["status"] not in ("CANCELLED", "NO_SHOW"):
        raise invalid_state("Visit not CANCELLED or NO_SHOW")
    try:
        starts = parse_iso(data["starts_at"])
        ends = parse_iso(data["ends_at"])
    except (ValueError, TypeError):
        raise invalid_request("starts_at / ends_at must be ISO 8601 timestamps")
    if not starts < ends:
        raise invalid_request("starts_at must be strictly earlier than ends_at")
    nomination = store.nominations.get(visit["nomination_id"])
    if nomination is None:
        raise not_found("Nomination does not exist")
    if _visit_overlaps(nomination["nonprofit_id"], starts, ends, exclude_id=visit["id"]):
        raise conflict(ERR_SITE_VISIT_OVERLAP,
                       "Visit overlaps another visit for the same nonprofit")
    visit["starts_at"] = iso3(starts)
    visit["ends_at"] = iso3(ends)
    visit["status"] = "SCHEDULED"
    touch(visit)
    return success_object(visit)


# ------------------------------------------------------------------ learning sessions

def _session_buffer_conflict(cycle_id, starts, ends, exclude_id=None):
    """15-minute buffer against other SCHEDULED sessions in the same cycle."""
    buffer = timedelta(minutes=15)
    for s in store.learning_sessions.values():
        if exclude_id is not None and s["id"] == exclude_id:
            continue
        if s["cycle_id"] != cycle_id:
            continue
        if s["status"] != "SCHEDULED":
            continue
        s_start = parse_iso(s["starts_at"])
        s_end = parse_iso(s["ends_at"])
        # conflict unless new ends at least 15 min before existing starts,
        # or new starts at least 15 min after existing ends
        if ends + buffer <= s_start or starts >= s_end + buffer:
            continue
        return True
    return False


@app.route("/api/learning-sessions", methods=["POST"])
def create_learning_session():
    require_roles("CircleAdmin")
    data = body()
    require_fields(data, ["cycle_id", "title", "starts_at", "ends_at", "capacity"])
    cycle = get_or_404(store.cycles, data["cycle_id"])
    title = data["title"]
    if not isinstance(title, str) or not title:
        raise invalid_request("title must be a non-empty string")
    capacity = data["capacity"]
    if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
        raise invalid_request("capacity must be an integer >= 1")
    try:
        starts = parse_iso(data["starts_at"])
        ends = parse_iso(data["ends_at"])
    except (ValueError, TypeError):
        raise invalid_request("starts_at / ends_at must be ISO 8601 timestamps")
    if not starts < ends:
        raise invalid_request("starts_at must be strictly earlier than ends_at")
    if _session_buffer_conflict(cycle["id"], starts, ends):
        raise conflict(ERR_SESSION_OVERLAP_BUFFER,
                       "Session violates the 15-minute buffer")
    session = stamp_new({
        "cycle_id": cycle["id"],
        "title": title,
        "starts_at": iso3(starts),
        "ends_at": iso3(ends),
        "capacity": capacity,
        "seats_taken": 0,
        "rsvp_membership_ids": [],
        "status": "SCHEDULED",
    })
    store.learning_sessions[session["id"]] = session
    return success_object(session, 201)


@app.route("/api/learning-sessions/<session_id>", methods=["GET"])
def get_learning_session(session_id):
    require_roles(*ALL_ROLES)
    session = get_or_404(store.learning_sessions, session_id)
    return success_object(session)


@app.route("/api/learning-sessions", methods=["GET"])
def list_learning_sessions():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(store.learning_sessions.values())
    cycle_id = request.args.get("cycle_id")
    status = request.args.get("status")
    if cycle_id is not None:
        items = [s for s in items if s["cycle_id"] == cycle_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items.sort(key=lambda s: s["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list(page, total, limit, offset)


@app.route("/api/learning-sessions/<session_id>/rsvp", methods=["POST"])
def rsvp_session(session_id):
    user_id, _ = require_roles("Member")
    session = get_or_404(store.learning_sessions, session_id)
    data = body()
    require_fields(data, ["membership_id"])
    membership = get_or_404(store.memberships, data["membership_id"])
    if membership["member_id"] != user_id:
        raise forbidden("Member may only RSVP with own membership")
    if membership["status"] != "ACTIVE":
        raise conflict(ERR_MEMBERSHIP_NOT_ACTIVE, "Membership not ACTIVE")
    if membership["id"] in session["rsvp_membership_ids"]:
        raise conflict(ERR_ALREADY_RSVPED, "Membership already holds a seat")
    if session["seats_taken"] >= session["capacity"]:
        raise conflict(ERR_SESSION_FULL, "Session is full")
    session["rsvp_membership_ids"].append(membership["id"])
    session["seats_taken"] += 1
    touch(session)
    return success_object(session)


@app.route("/api/learning-sessions/<session_id>/complete", methods=["POST"])
def complete_session(session_id):
    require_roles("CircleAdmin")
    session = get_or_404(store.learning_sessions, session_id)
    if session["status"] != "SCHEDULED":
        raise invalid_state("Session not SCHEDULED")
    session["status"] = "COMPLETED"
    touch(session)
    return success_object(session)


@app.route("/api/learning-sessions/<session_id>/cancel", methods=["POST"])
def cancel_session(session_id):
    require_roles("CircleAdmin")
    session = get_or_404(store.learning_sessions, session_id)
    if session["status"] != "SCHEDULED":
        raise invalid_state("Session not SCHEDULED")
    session["status"] = "CANCELLED"
    touch(session)
    return success_object(session)


# ------------------------------------------------------------------ ballots

def _validate_allocations(cycle, allocations):
    """Returns list of (nomination_id, points) pairs after validation."""
    if not isinstance(allocations, list):
        raise invalid_request("allocations must be an array")
    # points-budget shape
    if not (1 <= len(allocations) <= 5):
        raise conflict(ERR_POINTS_BUDGET, "allocations must hold 1-5 entries")
    entries = []
    total = 0
    for entry in allocations:
        if not isinstance(entry, dict):
            raise invalid_request("allocation entries must be objects")
        nid = entry.get("nomination_id")
        pts = entry.get("points")
        if not isinstance(nid, str) or not nid:
            raise invalid_request("allocation nomination_id must be a string")
        if isinstance(pts, bool) or not isinstance(pts, int):
            raise invalid_request("allocation points must be an integer")
        if pts < 10:
            raise conflict(ERR_POINTS_BUDGET, "each allocation needs >= 10 points")
        total += pts
        entries.append((nid, pts))
    if total != 100:
        raise conflict(ERR_POINTS_BUDGET, "allocations must sum to 100")
    # finalist references
    for nid, _ in entries:
        nom = store.nominations.get(nid)
        if nom is None:
            raise not_found("Referenced nomination does not exist")
        if nom["cycle_id"] != cycle["id"] or nom["status"] != "FINALIST":
            raise conflict(ERR_NOT_FINALIST,
                           "Allocation references a non-FINALIST nomination")
    return entries


def _check_voting_window(cycle):
    if cycle["phase"] != "VOTING":
        raise conflict(ERR_VOTING_WINDOW_CLOSED, "Voting window is closed")
    now = now_logical()
    opens = parse_iso(cycle["voting_opens_at"])
    closes = parse_iso(cycle["voting_closes_at"])
    if not (opens <= now <= closes):
        raise conflict(ERR_VOTING_WINDOW_CLOSED, "Voting window is closed")


@app.route("/api/ballots", methods=["POST"])
def create_ballot():
    user_id, _ = require_roles("Member")
    data = body()
    require_fields(data, ["cycle_id", "membership_id", "allocations"])
    cycle = get_or_404(store.cycles, data["cycle_id"])
    membership = get_or_404(store.memberships, data["membership_id"])
    if membership["member_id"] != user_id:
        raise forbidden("Member may only cast with own membership")
    if membership["status"] != "ACTIVE":
        raise conflict(ERR_MEMBERSHIP_NOT_ACTIVE, "Membership not ACTIVE")
    _check_voting_window(cycle)
    for b in ballots_of_cycle(cycle["id"]):
        if b["membership_id"] == membership["id"]:
            raise conflict(ERR_DUPLICATE_BALLOT,
                           "Membership already cast a ballot in this cycle")
    entries = _validate_allocations(cycle, data["allocations"])
    ballot = stamp_new({
        "cycle_id": cycle["id"],
        "membership_id": membership["id"],
        "allocations": [{"nomination_id": nid, "points": pts}
                        for nid, pts in entries],
        "status": "CAST",
    })
    store.ballots[ballot["id"]] = ballot
    recompute_cycle_ledger(cycle)  # bumps ballots_cast_count and cycle version
    return success_object(ballot, 201)


@app.route("/api/ballots/<ballot_id>", methods=["GET"])
def get_ballot(ballot_id):
    require_roles(*ALL_ROLES)
    ballot = get_or_404(store.ballots, ballot_id)
    return success_object(ballot)


@app.route("/api/ballots", methods=["GET"])
def list_ballots():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(store.ballots.values())
    cycle_id = request.args.get("cycle_id")
    membership_id = request.args.get("membership_id")
    status = request.args.get("status")
    if cycle_id is not None:
        items = [b for b in items if b["cycle_id"] == cycle_id]
    if membership_id is not None:
        items = [b for b in items if b["membership_id"] == membership_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    items.sort(key=lambda b: b["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list(page, total, limit, offset)


@app.route("/api/ballots/<ballot_id>/recast", methods=["POST"])
def recast_ballot(ballot_id):
    user_id, _ = require_roles("Member")
    ballot = get_or_404(store.ballots, ballot_id)
    data = body()
    membership = store.memberships.get(ballot["membership_id"])
    if membership is None or membership["member_id"] != user_id:
        raise forbidden("Member may only recast own ballot")
    expected = data.get("expected_ballot_version")
    if expected is None:
        raise invalid_request("expected_ballot_version is required")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise invalid_request("expected_ballot_version must be an integer")
    if expected != ballot["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_ballot_version does not match current version")
    cycle = store.cycles.get(ballot["cycle_id"])
    if cycle is None:
        raise not_found("Cycle does not exist")
    _check_voting_window(cycle)
    if membership["status"] != "ACTIVE":
        raise conflict(ERR_MEMBERSHIP_NOT_ACTIVE, "Membership not ACTIVE")
    if "allocations" not in data:
        raise invalid_request("allocations is required")
    entries = _validate_allocations(cycle, data["allocations"])
    ballot["allocations"] = [{"nomination_id": nid, "points": pts}
                             for nid, pts in entries]
    touch(ballot)
    return success_object(ballot)


# ------------------------------------------------------------------ awards

@app.route("/api/awards/<award_id>", methods=["GET"])
def get_award(award_id):
    require_roles(*ALL_ROLES)
    award = get_or_404(store.awards, award_id)
    return success_object(award)


@app.route("/api/awards", methods=["GET"])
def list_awards():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(store.awards.values())
    cycle_id = request.args.get("cycle_id")
    nomination_id = request.args.get("nomination_id")
    nonprofit_id = request.args.get("nonprofit_id")
    if cycle_id is not None:
        items = [a for a in items if a["cycle_id"] == cycle_id]
    if nomination_id is not None:
        items = [a for a in items if a["nomination_id"] == nomination_id]
    if nonprofit_id is not None:
        items = [a for a in items if a["nonprofit_id"] == nonprofit_id]
    items.sort(key=lambda a: a["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list(page, total, limit, offset)


# ------------------------------------------------------------------ payouts

@app.route("/api/payouts/<payout_id>", methods=["GET"])
def get_payout(payout_id):
    require_roles(*ALL_ROLES)
    payout = get_or_404(store.payouts, payout_id)
    return success_object(payout)


@app.route("/api/payouts", methods=["GET"])
def list_payouts():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(store.payouts.values())
    award_id = request.args.get("award_id")
    status = request.args.get("status")
    if award_id is not None:
        items = [p for p in items if p["award_id"] == award_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items.sort(key=lambda p: (p["tranche"], p["created_at"]))
    page, total = paginate(items, limit, offset)
    return success_list(page, total, limit, offset)


@app.route("/api/payouts/<payout_id>/approve", methods=["POST"])
def approve_payout(payout_id):
    user_id, _ = require_roles("FinanceOfficer")
    payout = get_or_404(store.payouts, payout_id)
    if payout["status"] != "SCHEDULED":
        raise invalid_state("Payout not SCHEDULED")
    if payout["requested_by_user_id"] == user_id:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "Approver may not be the requesting administrator")
    payout["status"] = "APPROVED"
    payout["approved_by_user_id"] = user_id
    touch(payout)
    return success_object(payout)


@app.route("/api/payouts/<payout_id>/release", methods=["POST"])
def release_payout(payout_id):
    user_id, _ = require_roles("FinanceOfficer")
    payout = get_or_404(store.payouts, payout_id)
    if payout["status"] != "APPROVED":
        raise invalid_state("Payout not APPROVED")
    award = store.awards.get(payout["award_id"])
    if award is None:
        raise not_found("Award does not exist")
    cycle = store.cycles.get(award["cycle_id"])
    if cycle is None:
        raise not_found("Cycle does not exist")
    if cycle["phase"] not in ("AWARD", "REPORTING"):
        raise conflict(ERR_CYCLE_PHASE, "Cycle not in AWARD or REPORTING")
    if payout["tranche"] == 2:
        interim = next((r for r in reports_of_award(award["id"])
                        if r["report_type"] == "INTERIM"), None)
        if interim is None or interim["status"] != "ACCEPTED":
            raise conflict(ERR_INTERIM_REPORT_NOT_ACCEPTED,
                           "INTERIM report must be ACCEPTED before tranche 2 release")
    payout["status"] = "RELEASED"
    touch(payout)
    recompute_cycle_ledger(cycle)
    recompute_award_payout_status(award)
    return success_object(payout)


@app.route("/api/payouts/<payout_id>/mark-failed", methods=["POST"])
def mark_failed_payout(payout_id):
    require_roles("FinanceOfficer")
    payout = get_or_404(store.payouts, payout_id)
    if payout["status"] != "APPROVED":
        raise invalid_state("Payout not APPROVED")
    payout["status"] = "FAILED"
    touch(payout)
    return success_object(payout)


@app.route("/api/payouts/<payout_id>/retry", methods=["POST"])
def retry_payout(payout_id):
    require_roles("FinanceOfficer")
    payout = get_or_404(store.payouts, payout_id)
    if payout["status"] != "FAILED":
        raise invalid_state("Payout not FAILED")
    payout["status"] = "SCHEDULED"
    payout["approved_by_user_id"] = None
    touch(payout)
    return success_object(payout)


# ------------------------------------------------------------------ grantee reports

@app.route("/api/reports/<report_id>", methods=["GET"])
def get_report(report_id):
    require_roles(*ALL_ROLES)
    report = get_or_404(store.reports, report_id)
    return success_object(report)


@app.route("/api/reports", methods=["GET"])
def list_reports():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(store.reports.values())
    award_id = request.args.get("award_id")
    status = request.args.get("status")
    if award_id is not None:
        items = [r for r in items if r["award_id"] == award_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items.sort(key=lambda r: (r["due_at"], r["created_at"]))
    page, total = paginate(items, limit, offset)
    return success_list(page, total, limit, offset)


@app.route("/api/reports/<report_id>/submit", methods=["POST"])
def submit_report(report_id):
    user_id, _ = require_roles("GranteeContact")
    report = get_or_404(store.reports, report_id)
    award = store.awards.get(report["award_id"])
    if award is None:
        raise not_found("Award does not exist")
    if award["nonprofit_id"] != user_id:
        raise forbidden("GranteeContact may only submit own nonprofit's reports")
    if report["status"] not in ("DUE", "OVERDUE", "REJECTED"):
        raise invalid_state("Report cannot be submitted from this state")
    data = body()
    require_fields(data, ["narrative", "expenditure_cents"])
    narrative = data["narrative"]
    expenditure = data["expenditure_cents"]
    if not isinstance(narrative, str) or not narrative:
        raise invalid_request("narrative must be a non-empty string")
    if isinstance(expenditure, bool) or not isinstance(expenditure, int) or expenditure < 0:
        raise invalid_request("expenditure_cents must be a non-negative integer")
    was_rejected = report["status"] == "REJECTED"
    report["narrative"] = narrative
    report["expenditure_cents"] = expenditure
    report["submitted_at"] = iso3(now_logical())
    if was_rejected:
        report["reject_reason"] = None
    report["status"] = "SUBMITTED"
    touch(report)
    return success_object(report)


@app.route("/api/reports/<report_id>/accept", methods=["POST"])
def accept_report(report_id):
    require_roles("CircleAdmin")
    report = get_or_404(store.reports, report_id)
    if report["status"] != "SUBMITTED":
        raise invalid_state("Report not SUBMITTED")
    report["status"] = "ACCEPTED"
    touch(report)
    award = store.awards.get(report["award_id"])
    if award is not None:
        nonprofit = store.nonprofits.get(award["nonprofit_id"])
        if nonprofit is not None:
            recompute_nonprofit_standing(nonprofit)
        recompute_award_reporting_status(award)
    return success_object(report)


@app.route("/api/reports/<report_id>/reject", methods=["POST"])
def reject_report(report_id):
    require_roles("CircleAdmin")
    report = get_or_404(store.reports, report_id)
    if report["status"] != "SUBMITTED":
        raise invalid_state("Report not SUBMITTED")
    data = body()
    reason = data.get("reject_reason")
    if not isinstance(reason, str) or not reason:
        raise invalid_request("reject_reason is required")
    report["status"] = "REJECTED"
    report["reject_reason"] = reason
    touch(report)
    return success_object(report)


# ------------------------------------------------------------------ rollover decisions

@app.route("/api/rollover-decisions", methods=["POST"])
def create_rollover_decision():
    require_roles("CircleAdmin")
    data = body()
    require_fields(data, ["source_cycle_id", "mode"])
    source = get_or_404(store.cycles, data["source_cycle_id"])
    mode = require_enum(data, "mode", ("CARRY_FORWARD", "RETURN_PRO_RATA"))
    if source["phase"] != "REPORTING":
        raise conflict(ERR_CYCLE_PHASE, "Source cycle not in REPORTING")
    target = None
    if mode == "CARRY_FORWARD":
        target_id = data.get("target_cycle_id")
        if not target_id:
            raise invalid_request("target_cycle_id is required for CARRY_FORWARD")
        target = store.cycles.get(target_id)
        if target is None:
            raise invalid_request("target_cycle_id does not reference an existing cycle")
        if target["circle_id"] != source["circle_id"]:
            raise invalid_request("Target cycle must belong to the same circle")
        if target["phase"] not in ("DRAFT", "RECRUITMENT"):
            raise invalid_request("Target cycle must be DRAFT or RECRUITMENT")
    decision = stamp_new({
        "source_cycle_id": source["id"],
        "target_cycle_id": target["id"] if target else None,
        "mode": mode,
        "amount_cents": None,
        "status": "PROPOSED",
    })
    store.rollover_decisions[decision["id"]] = decision
    return success_object(decision, 201)


@app.route("/api/rollover-decisions/<decision_id>", methods=["GET"])
def get_rollover_decision(decision_id):
    require_roles(*ALL_ROLES)
    decision = get_or_404(store.rollover_decisions, decision_id)
    return success_object(decision)


@app.route("/api/rollover-decisions", methods=["GET"])
def list_rollover_decisions():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(store.rollover_decisions.values())
    source_cycle_id = request.args.get("source_cycle_id")
    target_cycle_id = request.args.get("target_cycle_id")
    status = request.args.get("status")
    if source_cycle_id is not None:
        items = [d for d in items if d["source_cycle_id"] == source_cycle_id]
    if target_cycle_id is not None:
        items = [d for d in items if d.get("target_cycle_id") == target_cycle_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items.sort(key=lambda d: d["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list(page, total, limit, offset)


@app.route("/api/rollover-decisions/<decision_id>/approve", methods=["POST"])
def approve_rollover_decision(decision_id):
    require_roles("CircleAdmin")
    decision = get_or_404(store.rollover_decisions, decision_id)
    if decision["status"] != "PROPOSED":
        raise invalid_state("Decision not PROPOSED")
    decision["status"] = "APPROVED"
    touch(decision)
    return success_object(decision)


@app.route("/api/rollover-decisions/<decision_id>/execute", methods=["POST"])
def execute_rollover_decision(decision_id):
    require_roles("CircleAdmin")
    decision = get_or_404(store.rollover_decisions, decision_id)
    if decision["status"] != "APPROVED":
        raise invalid_state("Decision not APPROVED")
    source = store.cycles.get(decision["source_cycle_id"])
    if source is None:
        raise not_found("Source cycle does not exist")
    if source["phase"] != "REPORTING":
        raise conflict(ERR_CYCLE_PHASE, "Source cycle not in REPORTING")
    residual = source["pooled_balance_cents"]
    decision["amount_cents"] = residual
    if decision["mode"] == "CARRY_FORWARD":
        target = store.cycles.get(decision.get("target_cycle_id"))
        if target is None:
            raise invalid_request("target_cycle_id does not reference an existing cycle")
        target["rollover_in_cents"] = target.get("rollover_in_cents", 0) + residual
        recompute_cycle_ledger(target)
        source["rollover_out_cents"] = source.get("rollover_out_cents", 0) + residual
    else:  # RETURN_PRO_RATA
        eligible = [m for m in memberships_of_circle(source["circle_id"])
                    if m["status"] in ("ACTIVE", "RENEWAL_DUE")]
        eligible.sort(key=lambda m: m["created_at"])
        weights = {}
        total_weight = 0
        for m in eligible:
            w = sum(c["amount_cents"] for c in store.contributions.values()
                    if c["membership_id"] == m["id"]
                    and c["cycle_id"] == source["id"]
                    and c["status"] in ("RECEIVED", "REFUND_REQUESTED"))
            weights[m["id"]] = w
            total_weight += w
        if total_weight > 0 and residual > 0:
            distributed = 0
            for m in eligible:
                w = weights[m["id"]]
                credit = (residual * w) // total_weight
                if credit:
                    m["credit_balance_cents"] = m.get("credit_balance_cents", 0) + credit
                    touch(m)
                distributed += credit
            # leftover goes to host admin: not credited anywhere
        source["rollover_out_cents"] = source.get("rollover_out_cents", 0) + residual
    decision["status"] = "EXECUTED"
    touch(decision)
    recompute_cycle_ledger(source)
    return success_object(decision)


# ------------------------------------------------------------------ main

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
