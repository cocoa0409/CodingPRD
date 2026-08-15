"""Routes: tours, tour registrations, committees, fundraiser pledges."""

from decimal import Decimal

import store
from domain import (
    COMMITTEE_ACTIONS, TOUR_ACTIONS, compute_performance_eligible, dec,
    gate_season, member_dues_balance, promote_tour_waitlist, rhu_cents,
    sync_committee_raised, sync_tour_confirmed, tour_refund_amount,
    treasury_credit, treasury_debit,
)
from errors import ApiError
from routes_common import (
    apply_filters, many, member_ownership_check, one, route,
    scope_member_filter,
)
from serializers import committee_view, pledge_view, registration_view, tour_view
from store import all_of, new_row, touch
from timeutil import clock, parse_instant
from validate import check_body, check_enum, get_or_404, resolve_ids

ALL_ROLES = ("President", "Treasurer", "ChoirDirector", "Librarian", "Member")
REG_READ_ROLES = ("President", "Treasurer", "ChoirDirector", "Member")
PLEDGE_READ_ROLES = ("President", "Treasurer", "ChoirDirector", "Member")


# --------------------------------------------------------------------- tours
@route("POST", "/v1/tours", roles=["President"], code=201)
def create_tour(ctx):
    ids = resolve_ids(ctx["body"], (store.seasons, "season_id"))
    body = check_body(ctx["body"], {
        "season_id": ("string", True),
        "name": ("string", True),
        "destination": ("string", True),
        "departure_at": ("datetime", True),
        "return_at": ("datetime", True),
        "seat_count": ("int", True),
        "min_seats": ("int", True),
        "transport_lodging_cost_cents": ("int", True),
    })
    season = ids.get("season_id") or get_or_404(store.seasons, body["season_id"])
    gate_season(season, None)
    tour = new_row(
        store.tours,
        season_id=season["id"],
        name=body["name"],
        destination=body["destination"],
        departure_at=body["departure_at"],
        return_at=body["return_at"],
        seat_count=body["seat_count"],
        min_seats=body["min_seats"],
        transport_lodging_cost_cents=body["transport_lodging_cost_cents"],
        provisional_share_cents=None,
        final_share_cents=None,
        confirmed_count=0,
        status="PLANNING",
    )
    tour["_departure_dt"] = parse_instant(body["departure_at"])
    tour["_return_dt"] = parse_instant(body["return_at"])
    return one(tour_view, tour, 201)


@route("GET", "/v1/tours/{rid}", roles=ALL_ROLES)
def get_tour(ctx):
    return one(tour_view, get_or_404(store.tours, ctx["path"]["rid"]))


@route("GET", "/v1/tours", roles=ALL_ROLES)
def list_tours(ctx):
    rows = apply_filters(all_of(store.tours), {
        "season_id": ctx["args"].get("season_id"),
        "status": ctx["args"].get("status"),
    })
    return many(tour_view, rows, ctx["args"])


@route("POST", "/v1/tours/{rid}/transition", roles=["President"])
def tour_transition(ctx):
    tour = get_or_404(store.tours, ctx["path"]["rid"])
    body = check_body(ctx["body"], {"action": ("string", True)})
    check_enum(body, "action", TOUR_ACTIONS)
    gate_season(store.seasons[tour["season_id"]], None)
    action = body["action"]
    season = store.seasons[tour["season_id"]]

    if action == "OPEN_REGISTRATION":
        if tour["status"] != "PLANNING":
            raise ApiError("ERR_INVALID_STATE", "OPEN_REGISTRATION is not legal from %s" % tour["status"])
        if tour["_departure_dt"] <= clock.now:
            raise ApiError("ERR_TOUR_IN_PAST", "departure_at is not in the future")
        if not (tour["seat_count"] >= tour["min_seats"] >= 1):
            raise ApiError("ERR_INVALID_REQUEST", "seat_count >= min_seats >= 1 is required")
        tour["provisional_share_cents"] = rhu_cents(
            Decimal(tour["transport_lodging_cost_cents"]) / Decimal(tour["min_seats"])
        )
        tour["status"] = "REGISTRATION_OPEN"
        touch(tour)
        return one(tour_view, tour)

    if action == "LOCK_ROSTER":
        if tour["status"] != "REGISTRATION_OPEN":
            raise ApiError("ERR_INVALID_STATE", "LOCK_ROSTER is not legal from %s" % tour["status"])
        sync_tour_confirmed(tour)
        confirmed = tour["confirmed_count"]
        if confirmed < tour["min_seats"]:
            raise ApiError("ERR_BELOW_MIN_SEATS", "confirmed_count is below min_seats")
        final_share = rhu_cents(Decimal(tour["transport_lodging_cost_cents"]) / Decimal(confirmed))
        tour["final_share_cents"] = final_share
        for reg in store.tour_registrations.values():
            if reg["tour_id"] != tour["id"]:
                continue
            if reg["status"] == "CONFIRMED":
                reg["share_charge_cents"] = final_share
                refund = reg["deposit_paid_cents"] - final_share
                reg["refund_cents"] = refund
                treasury_debit(season, refund, check=False)
                touch(reg)
            elif reg["status"] == "WAITLISTED":
                reg["status"] = "CANCELLED"
                touch(reg)
        tour["status"] = "ROSTER_LOCKED"
        touch(tour)
        return one(tour_view, tour)

    if action == "COMPLETE":
        if tour["status"] != "ROSTER_LOCKED":
            raise ApiError("ERR_INVALID_STATE", "COMPLETE is not legal from %s" % tour["status"])
        if clock.now < tour["_return_dt"]:
            raise ApiError("ERR_TOUR_NOT_RETURNED", "return_at has not been reached")
        tour["status"] = "COMPLETED"
        touch(tour)
        return one(tour_view, tour)

    # CANCEL
    if tour["status"] not in ("PLANNING", "REGISTRATION_OPEN"):
        raise ApiError("ERR_INVALID_STATE", "CANCEL is not legal from %s" % tour["status"])
    regs = [r for r in store.tour_registrations.values() if r["tour_id"] == tour["id"]]
    if tour["status"] == "REGISTRATION_OPEN":
        total_refund = sum(r["deposit_paid_cents"] for r in regs if r["status"] == "CONFIRMED")
        treasury_debit(season, total_refund, check=True)
        for reg in regs:
            if reg["status"] == "CONFIRMED":
                reg["refund_cents"] = reg["deposit_paid_cents"]
                reg["status"] = "REFUNDED"
                touch(reg)
            elif reg["status"] in ("REGISTERED", "WAITLISTED"):
                reg["status"] = "CANCELLED"
                touch(reg)
    else:
        for reg in regs:
            if reg["status"] in ("REGISTERED", "CONFIRMED", "WAITLISTED"):
                reg["status"] = "CANCELLED"
                touch(reg)
    tour["status"] = "CANCELLED"
    touch(tour)
    return one(tour_view, tour)


# ---------------------------------------------------------- tour registrations
@route("POST", "/v1/tour-registrations", roles=["Member"], code=201)
def create_registration(ctx):
    ids = resolve_ids(ctx["body"], (store.tours, "tour_id"))
    body = check_body(ctx["body"], {"tour_id": ("string", True)})
    tour = ids.get("tour_id") or get_or_404(store.tours, body["tour_id"])
    member = get_or_404(store.members, ctx["uid"])
    gate_season(store.seasons[tour["season_id"]], None)
    if tour["status"] != "REGISTRATION_OPEN":
        raise ApiError("ERR_TOUR_NOT_OPEN", "the tour is not REGISTRATION_OPEN")
    dues = member_dues_balance(member["id"])
    if dues != 0 or not compute_performance_eligible(member, dues_balance=dues):
        raise ApiError("ERR_DUES_NOT_CURRENT", "the member's dues are not current or they are not eligible")
    if any(
        r["tour_id"] == tour["id"] and r["member_id"] == member["id"]
        and r["status"] in ("REGISTERED", "CONFIRMED", "WAITLISTED")
        for r in store.tour_registrations.values()
    ):
        raise ApiError("ERR_ALREADY_REGISTERED", "the member already has a non-terminal registration")
    taken = sum(
        1 for r in store.tour_registrations.values()
        if r["tour_id"] == tour["id"] and r["status"] in ("REGISTERED", "CONFIRMED")
    )
    status = "REGISTERED" if taken < tour["seat_count"] else "WAITLISTED"
    registration = new_row(
        store.tour_registrations,
        tour_id=tour["id"],
        member_id=member["id"],
        status=status,
        deposit_paid_cents=0,
        share_charge_cents=None,
        refund_cents=0,
    )
    return one(registration_view, registration, 201)


@route("GET", "/v1/tour-registrations/{rid}", roles=REG_READ_ROLES)
def get_registration(ctx):
    registration = get_or_404(store.tour_registrations, ctx["path"]["rid"])
    member_ownership_check(ctx, registration["member_id"])
    return one(registration_view, registration)


@route("GET", "/v1/tour-registrations", roles=REG_READ_ROLES)
def list_registrations(ctx):
    filters = scope_member_filter(ctx, {
        "tour_id": ctx["args"].get("tour_id"),
        "member_id": ctx["args"].get("member_id"),
        "status": ctx["args"].get("status"),
    })
    rows = apply_filters(all_of(store.tour_registrations), filters)
    return many(registration_view, rows, ctx["args"])


@route("POST", "/v1/tour-registrations/{rid}/confirm", roles=["Treasurer"])
def confirm_registration(ctx):
    registration = get_or_404(store.tour_registrations, ctx["path"]["rid"])
    check_body(ctx["body"], {})
    tour = store.tours[registration["tour_id"]]
    gate_season(store.seasons[tour["season_id"]], None)
    if registration["status"] != "REGISTERED":
        raise ApiError("ERR_INVALID_STATE", "only a REGISTERED registration can be confirmed")
    season = store.seasons[tour["season_id"]]
    registration["deposit_paid_cents"] = tour["provisional_share_cents"]
    treasury_credit(season, registration["deposit_paid_cents"])
    registration["status"] = "CONFIRMED"
    touch(registration)
    sync_tour_confirmed(tour)
    return one(registration_view, registration)


@route("POST", "/v1/tour-registrations/{rid}/cancel", roles=["Member", "Treasurer"])
def cancel_registration(ctx):
    registration = get_or_404(store.tour_registrations, ctx["path"]["rid"])
    member_ownership_check(ctx, registration["member_id"])
    check_body(ctx["body"], {})
    tour = store.tours[registration["tour_id"]]
    gate_season(store.seasons[tour["season_id"]], None)
    if registration["status"] not in ("REGISTERED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE", "the registration is already terminal")
    if tour["status"] in ("ROSTER_LOCKED", "COMPLETED"):
        raise ApiError("ERR_ROSTER_LOCKED", "the roster is locked")
    if tour["status"] != "REGISTRATION_OPEN":
        raise ApiError("ERR_INVALID_STATE", "the tour is not open for cancellation")
    if registration["status"] == "CONFIRMED":
        season = store.seasons[tour["season_id"]]
        refund = tour_refund_amount(tour, registration)
        treasury_debit(season, refund, check=True)
        registration["refund_cents"] = refund
    registration["status"] = "CANCELLED"
    touch(registration)
    sync_tour_confirmed(tour)
    promote_tour_waitlist(tour)
    return one(registration_view, registration)


# ----------------------------------------------------------------- committees
@route("POST", "/v1/committees", roles=["President"], code=201)
def create_committee(ctx):
    ids = resolve_ids(ctx["body"], (store.seasons, "season_id"), (store.members, "chair_member_id"))
    body = check_body(ctx["body"], {
        "season_id": ("string", True),
        "name": ("string", True),
        "chair_member_id": ("string", True),
        "fundraising_goal_cents": ("int", True),
    })
    season = ids.get("season_id") or get_or_404(store.seasons, body["season_id"])
    if "chair_member_id" not in ids:
        get_or_404(store.members, body["chair_member_id"])
    gate_season(season, None)
    committee = new_row(
        store.committees,
        season_id=season["id"],
        name=body["name"],
        chair_member_id=body["chair_member_id"],
        fundraising_goal_cents=body["fundraising_goal_cents"],
        raised_cents=0,
        status="FORMING",
    )
    return one(committee_view, committee, 201)


@route("GET", "/v1/committees/{rid}", roles=ALL_ROLES)
def get_committee(ctx):
    return one(committee_view, get_or_404(store.committees, ctx["path"]["rid"]))


@route("GET", "/v1/committees", roles=ALL_ROLES)
def list_committees(ctx):
    rows = apply_filters(all_of(store.committees), {
        "season_id": ctx["args"].get("season_id"),
        "chair_member_id": ctx["args"].get("chair_member_id"),
        "status": ctx["args"].get("status"),
    })
    return many(committee_view, rows, ctx["args"])


@route("POST", "/v1/committees/{rid}/transition", roles=["President"])
def committee_transition(ctx):
    committee = get_or_404(store.committees, ctx["path"]["rid"])
    body = check_body(ctx["body"], {"action": ("string", True)})
    check_enum(body, "action", COMMITTEE_ACTIONS)
    gate_season(store.seasons[committee["season_id"]], None)
    if body["action"] == "ACTIVATE":
        if committee["status"] != "FORMING":
            raise ApiError("ERR_INVALID_STATE", "ACTIVATE is not legal from %s" % committee["status"])
        chair = store.members[committee["chair_member_id"]]
        if chair["status"] != "ACTIVE":
            raise ApiError("ERR_CHAIR_NOT_ACTIVE", "the chair member is not ACTIVE")
        committee["status"] = "ACTIVE"
        touch(committee)
        return one(committee_view, committee)
    # DISSOLVE
    if committee["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "DISSOLVE is not legal from %s" % committee["status"])
    for pledge in store.pledges.values():
        if pledge["committee_id"] == committee["id"] and pledge["status"] == "PLEDGED":
            pledge["status"] = "CANCELLED"
            touch(pledge)
    committee["status"] = "DISSOLVED"
    touch(committee)
    return one(committee_view, committee)


# -------------------------------------------------------------------- pledges
@route("POST", "/v1/pledges", roles=["Treasurer"], code=201)
def create_pledge(ctx):
    ids = resolve_ids(ctx["body"], (store.committees, "committee_id"))
    body = check_body(ctx["body"], {
        "committee_id": ("string", True),
        "donor_name": ("string", True),
        "amount_cents": ("int", True),
    })
    committee = ids.get("committee_id") or get_or_404(store.committees, body["committee_id"])
    gate_season(store.seasons[committee["season_id"]], None)
    if committee["status"] != "ACTIVE":
        raise ApiError("ERR_COMMITTEE_NOT_ACTIVE", "the committee is not ACTIVE")
    pledge = new_row(
        store.pledges,
        committee_id=committee["id"],
        donor_name=body["donor_name"],
        amount_cents=body["amount_cents"],
        status="PLEDGED",
        recognition_tier=None,
        recorded_by_user_id=ctx["uid"],
        fulfilled_by_user_id=None,
    )
    return one(pledge_view, pledge, 201)


@route("GET", "/v1/pledges/{rid}", roles=PLEDGE_READ_ROLES)
def get_pledge(ctx):
    return one(pledge_view, get_or_404(store.pledges, ctx["path"]["rid"]))


@route("GET", "/v1/pledges", roles=PLEDGE_READ_ROLES)
def list_pledges(ctx):
    rows = apply_filters(all_of(store.pledges), {
        "committee_id": ctx["args"].get("committee_id"),
        "status": ctx["args"].get("status"),
    })
    return many(pledge_view, rows, ctx["args"])


@route("POST", "/v1/pledges/{rid}/fulfill", roles=["Treasurer"])
def fulfill_pledge(ctx):
    pledge = get_or_404(store.pledges, ctx["path"]["rid"])
    check_body(ctx["body"], {})
    committee = store.committees[pledge["committee_id"]]
    gate_season(store.seasons[committee["season_id"]], None)
    if pledge["status"] != "PLEDGED":
        raise ApiError("ERR_INVALID_STATE", "only a PLEDGED pledge can be fulfilled")
    if ctx["uid"] == pledge["recorded_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", "the fulfiller must differ from the recorder")
    season = store.seasons[committee["season_id"]]
    treasury_credit(season, pledge["amount_cents"])
    pledge["status"] = "FULFILLED"
    pledge["fulfilled_by_user_id"] = ctx["uid"]
    amount = pledge["amount_cents"]
    pledge["recognition_tier"] = "GOLD" if amount >= 50000 else ("SILVER" if amount >= 10000 else "BRONZE")
    touch(pledge)
    sync_committee_raised(committee)
    return one(pledge_view, pledge)


@route("POST", "/v1/pledges/{rid}/cancel", roles=["Treasurer"])
def cancel_pledge(ctx):
    pledge = get_or_404(store.pledges, ctx["path"]["rid"])
    check_body(ctx["body"], {})
    committee = store.committees[pledge["committee_id"]]
    gate_season(store.seasons[committee["season_id"]], None)
    if pledge["status"] != "PLEDGED":
        raise ApiError("ERR_INVALID_STATE", "only a PLEDGED pledge can be cancelled")
    pledge["status"] = "CANCELLED"
    touch(pledge)
    return one(pledge_view, pledge)


@route("POST", "/v1/pledges/{rid}/refund", roles=["Treasurer"])
def refund_pledge(ctx):
    pledge = get_or_404(store.pledges, ctx["path"]["rid"])
    check_body(ctx["body"], {})
    committee = store.committees[pledge["committee_id"]]
    gate_season(store.seasons[committee["season_id"]], None)
    if pledge["status"] != "FULFILLED":
        raise ApiError("ERR_INVALID_STATE", "only a FULFILLED pledge can be refunded")
    season = store.seasons[committee["season_id"]]
    treasury_debit(season, pledge["amount_cents"], check=True)
    pledge["status"] = "REFUNDED"
    touch(pledge)
    sync_committee_raised(committee)
    return one(pledge_view, pledge)
