"""Member bookings, transient bookings, occupancy lifecycle, surveys, exceptions."""

from flask import Blueprint, request

import auth
import calc
import clock
import engine
import guards
import response
import serializers
import store
import validators as v
from auth import CLUB_ADMIN, MEMBER, PARK_MANAGER, COMPLIANCE_OFFICER, TRANSIENT_GUEST
from errors import fail

bp = Blueprint("reservations", __name__)

_EXTENSION_REASONS = ("MEDICAL", "EMPLOYMENT", "WEATHER", "RIG_REPAIR")


def _new_reservation_row():
    row = store.base_row()
    row.update({
        "park_id": None,
        "membership_id": None,
        "booker_type": "MEMBER",
        "guest_name": None,
        "arrival_date": None,
        "departure_date": None,
        "scheduled_departure_date": None,
        "nights": 0,
        "status": "PENDING",
        "pool_charged": "NONE",
        "entitlement_nights_charged": 0,
        "affiliate_nights_charged": 0,
        "total_charge_cents": 0,
        "extension_count": 0,
        "extension_denied_count": 0,
        "cancellation_reason": None,
        "checked_in_at": None,
        "checked_out_at": None,
        "consecutive_run_nights": 0,
    })
    return row


# ---------------------------------------------------------------------------
# POST /reservations — the full booking ladder (rungs 25 through 45)
# ---------------------------------------------------------------------------
@bp.post("/reservations")
def create_reservation():
    actor = auth.authorize(MEMBER)
    data = v.body()
    raw_membership = v.raw_id(data, "membership_id")
    auth.require_member_owner(actor, guards.find("memberships", raw_membership))
    guards.maybe("memberships", raw_membership)
    guards.maybe("parks", v.raw_id(data, "park_id"))
    membership_id = v.req_id(data, "membership_id")
    park_id = v.req_id(data, "park_id")
    arrival = v.req_date(data, "arrival_date")
    departure = v.req_date(data, "scheduled_departure_date")
    if departure <= arrival:
        fail("ERR_INVALID_REQUEST",
             "scheduled_departure_date must be after arrival_date")

    membership = guards.fetch("memberships", membership_id)
    park = guards.fetch("parks", park_id)
    tier = engine.tier_of(membership)
    if tier is None:
        fail("ERR_TIER_NOT_FOUND", "the membership's tier no longer exists")
    agreement = engine.agreement_of(park)
    nights = (departure - arrival).days

    if membership["membership_status"] != "ACTIVE":
        fail("ERR_MEMBERSHIP_NOT_ACTIVE", "membership is not ACTIVE")
    if agreement is not None and agreement["status"] != "ACTIVE":
        fail("ERR_AFFILIATE_AGREEMENT_INACTIVE", "the park's agreement is not ACTIVE")
    if park["park_status"] != "OPEN":
        fail("ERR_PARK_NOT_OPEN", "park is not OPEN")
    if engine.has_maintenance_conflict(park_id, arrival, departure):
        fail("ERR_MAINTENANCE_WINDOW_CONFLICT", "a maintenance window blocks these nights")

    run_nights, _, _ = engine.merged_run(membership_id, park_id, arrival, departure)
    if run_nights > calc.ABSOLUTE_MAX_RUN_NIGHTS:
        fail("ERR_ABSOLUTE_OCCUPANCY_CAP",
             "the merged run would exceed %d nights" % calc.ABSOLUTE_MAX_RUN_NIGHTS)

    window_cap = tier["advance_window_days"]
    if agreement is not None:
        window_cap = min(window_cap, agreement["advance_window_cap_days"])
    if (arrival - clock.today()).days > window_cap:
        fail("ERR_ADVANCE_WINDOW_EXCEEDED", "arrival is beyond the advance window")
    if not engine.stay_inside_season(park, arrival, departure):
        fail("ERR_STAY_OUTSIDE_SEASON", "the stay falls outside the park's season")
    if run_nights > tier["max_consecutive_stay_nights"]:
        fail("ERR_STAY_LENGTH_EXCEEDED", "the merged run exceeds the tier limit")
    if agreement is not None and nights > agreement["per_stay_night_cap"]:
        fail("ERR_STAY_LENGTH_EXCEEDED", "the stay exceeds the partner per-stay cap")

    gap = engine.out_and_back_gap(membership_id, arrival)
    if gap is not None and gap < tier["min_out_nights_between_stays"]:
        fail("ERR_OUT_AND_BACK_VIOLATION", "the out-and-back buffer is not satisfied")
    if engine.has_overlapping_stay(membership_id, arrival, departure):
        fail("ERR_OVERLAPPING_STAY", "the membership already has a stay on these nights")
    if agreement is not None and (not tier["affiliate_access_enabled"]
                                 or tier["tier_rank"] < agreement["min_tier_rank"]):
        fail("ERR_AFFILIATE_TIER_INELIGIBLE", "the tier may not book this partner park")

    if membership["dues_status"] not in ("CURRENT", "GRACE"):
        fail("ERR_DUES_NOT_CURRENT", "dues standing does not permit booking")
    if membership["dues_status"] == "GRACE" and park["park_class"] == "CLASS_A":
        fail("ERR_CLASS_A_RESTRICTED_IN_GRACE",
             "a membership in GRACE may not book a CLASS_A park")
    if not engine.entitlement_headroom_ok(membership, tier, park, nights):
        fail("ERR_ENTITLEMENT_NIGHTS_EXHAUSTED", "entitlement nights are exhausted")
    quota_charge = engine.quota_charge_for(agreement, nights) if agreement else 0
    if agreement is not None and not engine.quota_headroom_ok(agreement, quota_charge):
        fail("ERR_AFFILIATE_QUOTA_EXHAUSTED", "the partner quota is exhausted")

    row = _new_reservation_row()
    row.update({
        "park_id": park_id,
        "membership_id": membership_id,
        "booker_type": "MEMBER",
        "arrival_date": clock.fmt_date(arrival),
        "departure_date": clock.fmt_date(departure),
        "scheduled_departure_date": clock.fmt_date(departure),
        "nights": nights,
    })
    pool = engine.allocate_member_pool(park, arrival, departure)
    if pool is None:
        row["status"] = "WAITLISTED"
        store.insert("reservations", row)
    else:
        row["status"] = "CONFIRMED"
        row["pool_charged"] = pool
        row["entitlement_nights_charged"] = nights
        row["consecutive_run_nights"] = run_nights
        if agreement is not None:
            row["affiliate_nights_charged"] = quota_charge
        store.insert("reservations", row)
        engine.debit_entitlement(membership, park, nights)
        if agreement is not None:
            engine.add_quota(agreement, quota_charge)
        store.touch(membership)
    return response.created(serializers.reservation(row))


# ---------------------------------------------------------------------------
# POST /transient-reservations
# ---------------------------------------------------------------------------
@bp.post("/transient-reservations")
def create_transient_reservation():
    auth.authorize(TRANSIENT_GUEST)
    data = v.body()
    guards.maybe("parks", v.raw_id(data, "park_id"))
    park_id = v.req_id(data, "park_id")
    guest_name = v.req_str(data, "guest_name")
    arrival = v.req_date(data, "arrival_date")
    departure = v.req_date(data, "scheduled_departure_date")
    if departure <= arrival:
        fail("ERR_INVALID_REQUEST",
             "scheduled_departure_date must be after arrival_date")

    park = guards.fetch("parks", park_id)
    agreement = engine.agreement_of(park)
    if agreement is not None and agreement["status"] != "ACTIVE":
        fail("ERR_AFFILIATE_AGREEMENT_INACTIVE", "the park's agreement is not ACTIVE")
    if park["park_status"] != "OPEN":
        fail("ERR_PARK_NOT_OPEN", "park is not OPEN")
    if engine.has_maintenance_conflict(park_id, arrival, departure):
        fail("ERR_MAINTENANCE_WINDOW_CONFLICT", "a maintenance window blocks these nights")
    if not engine.stay_inside_season(park, arrival, departure):
        fail("ERR_STAY_OUTSIDE_SEASON", "the stay falls outside the park's season")
    if not engine.transient_available(park, arrival, departure):
        fail("ERR_NO_TRANSIENT_CAPACITY", "the transient pool is full on a requested night")

    nights = (departure - arrival).days
    row = _new_reservation_row()
    row.update({
        "park_id": park_id,
        "membership_id": None,
        "booker_type": "TRANSIENT",
        "guest_name": guest_name,
        "arrival_date": clock.fmt_date(arrival),
        "departure_date": clock.fmt_date(departure),
        "scheduled_departure_date": clock.fmt_date(departure),
        "nights": nights,
        "status": "CONFIRMED",
        "pool_charged": "TRANSIENT_POOL",
        "total_charge_cents": calc.transient_stay_charge(park["park_class"], arrival,
                                                        departure),
    })
    store.insert("reservations", row)
    store.touch(park)
    return response.created(serializers.reservation(row))


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------
@bp.get("/reservations/<reservation_id>")
def read_reservation(reservation_id):
    actor = auth.authorize(MEMBER, CLUB_ADMIN, PARK_MANAGER, TRANSIENT_GUEST)
    candidate = guards.find("reservations", reservation_id)
    if candidate is not None:
        auth.require_member_owner(actor, engine.membership_of(candidate))
    res = guards.fetch("reservations", reservation_id)
    return response.ok(serializers.reservation(res))


@bp.get("/reservations")
def list_reservations():
    auth.authorize(CLUB_ADMIN, PARK_MANAGER)
    rows = store.ordered(store.all_rows("reservations"))
    for field in ("park_id", "membership_id", "status", "booker_type"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r.get(field) == value]
    arrival_from = request.args.get("arrival_from")
    if arrival_from:
        rows = [r for r in rows if r["arrival_date"] >= arrival_from]
    arrival_to = request.args.get("arrival_to")
    if arrival_to:
        rows = [r for r in rows if r["arrival_date"] <= arrival_to]
    return response.paginate(rows, serializers.reservation)


@bp.get("/reservations/<reservation_id>/satisfaction-surveys")
def list_reservation_surveys(reservation_id):
    auth.authorize(MEMBER, CLUB_ADMIN, PARK_MANAGER, COMPLIANCE_OFFICER)
    guards.fetch("reservations", reservation_id)
    rows = store.ordered([s for s in store.all_rows("satisfaction_surveys")
                          if s.get("reservation_id") == reservation_id])
    return response.paginate(rows, serializers.survey)


@bp.get("/reservations/<reservation_id>/occupancy-exceptions")
def list_reservation_exceptions(reservation_id):
    auth.authorize(MEMBER, CLUB_ADMIN, COMPLIANCE_OFFICER, PARK_MANAGER)
    guards.fetch("reservations", reservation_id)
    rows = store.ordered([e for e in store.all_rows("occupancy_exceptions")
                          if e.get("reservation_id") == reservation_id])
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return response.paginate(rows, serializers.occupancy_exception)


# ---------------------------------------------------------------------------
# cancellation
# ---------------------------------------------------------------------------
@bp.post("/reservations/<reservation_id>/cancellation")
def cancel_reservation(reservation_id):
    actor = auth.authorize(MEMBER, CLUB_ADMIN, TRANSIENT_GUEST)
    candidate = guards.find("reservations", reservation_id)
    if candidate is not None:
        auth.require_member_owner(actor, engine.membership_of(candidate))
    res = guards.fetch("reservations", reservation_id)
    if res["status"] not in ("PENDING", "CONFIRMED", "WAITLISTED"):
        fail("ERR_INVALID_RESERVATION_STATE", "this stay can no longer be cancelled")

    membership = engine.membership_of(res)
    released = False
    if res["status"] in ("PENDING", "CONFIRMED"):
        charged = res.get("entitlement_nights_charged") or 0
        released = engine.release_debits(res)
        if membership is not None and not charged:
            store.touch(membership)
    res["status"] = "CANCELLED"
    res["cancellation_reason"] = "MEMBER_REQUEST"
    store.touch(res)
    if released:
        engine.waitlist_sweep(res["park_id"])
    return response.ok(serializers.reservation(res))


# ---------------------------------------------------------------------------
# check-in / check-out
# ---------------------------------------------------------------------------
@bp.post("/reservations/<reservation_id>/check-in")
def check_in(reservation_id):
    actor = auth.authorize(MEMBER, PARK_MANAGER)
    candidate = guards.find("reservations", reservation_id)
    if candidate is not None:
        auth.require_member_owner(actor, engine.membership_of(candidate))
    res = guards.fetch("reservations", reservation_id)
    if res["status"] != "CONFIRMED":
        fail("ERR_INVALID_RESERVATION_STATE", "only a CONFIRMED stay may check in")
    park = engine.park_of(res)
    if park is None or park["park_status"] != "OPEN":
        fail("ERR_INVALID_PARK_STATE", "park is not OPEN")
    membership = engine.membership_of(res)
    if membership is not None and membership["membership_status"] != "ACTIVE":
        fail("ERR_MEMBERSHIP_NOT_ACTIVE", "membership is not ACTIVE")
    today = clock.today()
    if today < engine.as_date(res["arrival_date"]):
        fail("ERR_INVALID_RESERVATION_STATE", "check-in is before the arrival date")
    if today >= engine.as_date(res["departure_date"]):
        fail("ERR_INVALID_RESERVATION_STATE", "the stay has already run out")

    res["status"] = "CHECKED_IN"
    res["checked_in_at"] = clock.now_iso()
    store.touch(res)
    return response.ok(serializers.reservation(res))


@bp.post("/reservations/<reservation_id>/check-out")
def check_out(reservation_id):
    actor = auth.authorize(MEMBER, PARK_MANAGER)
    candidate = guards.find("reservations", reservation_id)
    if candidate is not None:
        auth.require_member_owner(actor, engine.membership_of(candidate))
    res = guards.fetch("reservations", reservation_id)
    data = v.body()
    actual = v.req_date(data, "actual_departure_date")
    if res["status"] != "CHECKED_IN":
        fail("ERR_INVALID_RESERVATION_STATE", "only a CHECKED_IN stay may check out")
    arrival = engine.as_date(res["arrival_date"])
    departure = engine.as_date(res["departure_date"])
    if actual <= arrival or actual > departure:
        fail("ERR_INVALID_REQUEST",
             "actual_departure_date must be after arrival_date and no later than "
             "departure_date")

    park = engine.park_of(res)
    membership = engine.membership_of(res)
    final_nights = (actual - arrival).days
    charged = res.get("entitlement_nights_charged") or 0
    unused = charged - final_nights
    if membership is not None and park is not None and unused > 0:
        engine.credit_entitlement(membership, park, unused)
    res["entitlement_nights_charged"] = final_nights

    agreement = engine.agreement_of(park)
    if agreement is not None:
        new_charge = engine.quota_charge_for(agreement, final_nights)
        previous = res.get("affiliate_nights_charged") or 0
        if previous > new_charge:
            engine.credit_quota(agreement, previous - new_charge)
        res["affiliate_nights_charged"] = new_charge

    res["status"] = "COMPLETED"
    res["checked_out_at"] = clock.now_iso()
    res["departure_date"] = clock.fmt_date(actual)
    res["nights"] = final_nights
    store.touch(res)
    if membership is not None:
        store.touch(membership)
    engine.waitlist_sweep(res["park_id"])
    return response.ok(serializers.reservation(res))


# ---------------------------------------------------------------------------
# extensions
# ---------------------------------------------------------------------------
@bp.post("/reservations/<reservation_id>/extensions")
def extend_reservation(reservation_id):
    actor = auth.authorize(MEMBER)
    candidate = guards.find("reservations", reservation_id)
    if candidate is not None:
        auth.require_member_owner(actor, engine.membership_of(candidate))
    res = guards.fetch("reservations", reservation_id)
    data = v.body()
    new_departure = v.req_date(data, "new_departure_date")
    reason = v.opt_enum(data, "reason", _EXTENSION_REASONS, default="RIG_REPAIR")
    if res["status"] != "CHECKED_IN":
        fail("ERR_INVALID_RESERVATION_STATE", "only a CHECKED_IN stay may be extended")

    arrival = engine.as_date(res["arrival_date"])
    current_departure = engine.as_date(res["departure_date"])
    if new_departure <= current_departure:
        fail("ERR_INVALID_REQUEST", "new_departure_date must extend the stay")
    added = (new_departure - current_departure).days
    new_nights = (new_departure - arrival).days

    park = guards.fetch("parks", res["park_id"])
    membership = engine.membership_of(res)
    if membership is None:
        fail("ERR_MEMBERSHIP_NOT_FOUND", "membership not found")
    tier = engine.tier_of(membership)
    if tier is None:
        fail("ERR_TIER_NOT_FOUND", "the membership's tier no longer exists")
    agreement = engine.agreement_of(park)

    if membership["membership_status"] != "ACTIVE":
        fail("ERR_MEMBERSHIP_NOT_ACTIVE", "membership is not ACTIVE")
    if engine.has_maintenance_conflict(res["park_id"], arrival, new_departure):
        fail("ERR_MAINTENANCE_WINDOW_CONFLICT", "a maintenance window blocks these nights")

    run_nights, _, _ = engine.merged_run(membership["id"], park["id"], arrival,
                                        new_departure,
                                        exclude_res_id=res["id"],
                                        created_at=res.get("created_at"),
                                        seq=res.get("_seq"))
    if run_nights > calc.ABSOLUTE_MAX_RUN_NIGHTS:
        fail("ERR_ABSOLUTE_OCCUPANCY_CAP",
             "the merged run would exceed %d nights" % calc.ABSOLUTE_MAX_RUN_NIGHTS)
    if not engine.stay_inside_season(park, arrival, new_departure):
        fail("ERR_STAY_OUTSIDE_SEASON", "the extension falls outside the park's season")
    if agreement is not None and new_nights > agreement["per_stay_night_cap"]:
        fail("ERR_STAY_LENGTH_EXCEEDED", "the stay exceeds the partner per-stay cap")
    if engine.has_overlapping_stay(membership["id"], arrival, new_departure,
                                  exclude_res_id=res["id"]):
        fail("ERR_OVERLAPPING_STAY", "the membership already has a stay on these nights")
    if membership["dues_status"] not in ("CURRENT", "GRACE"):
        fail("ERR_DUES_NOT_CURRENT", "dues standing does not permit an extension")
    if membership["dues_status"] == "GRACE" and park["park_class"] == "CLASS_A":
        fail("ERR_CLASS_A_RESTRICTED_IN_GRACE",
             "a membership in GRACE may not extend at a CLASS_A park")
    if not engine.entitlement_headroom_ok(membership, tier, park, added):
        fail("ERR_ENTITLEMENT_NIGHTS_EXHAUSTED", "entitlement nights are exhausted")
    quota_delta = 0
    if agreement is not None:
        quota_delta = (engine.quota_charge_for(agreement, new_nights)
                       - (res.get("affiliate_nights_charged") or 0))
        if quota_delta > 0 and not engine.quota_headroom_ok(agreement, quota_delta):
            fail("ERR_AFFILIATE_QUOTA_EXHAUSTED", "the partner quota is exhausted")

    res["_pre_extension_departure_date"] = res["departure_date"]
    res["departure_date"] = clock.fmt_date(new_departure)

    if run_nights <= tier["max_consecutive_stay_nights"]:
        res["nights"] = new_nights
        res["entitlement_nights_charged"] = (res.get("entitlement_nights_charged") or 0) + added
        engine.debit_entitlement(membership, park, added)
        if agreement is not None and quota_delta > 0:
            res["affiliate_nights_charged"] = ((res.get("affiliate_nights_charged") or 0)
                                               + quota_delta)
            engine.add_quota(agreement, quota_delta)
        res["extension_count"] = res["extension_count"] + 1
        res["consecutive_run_nights"] = run_nights
        store.touch(res)
        store.touch(membership)
        return response.ok(serializers.reservation(res))

    res["status"] = "EXTENSION_REVIEW"
    res["nights"] = new_nights
    store.touch(res)
    exception = store.base_row()
    exception.update({
        "reservation_id": res["id"],
        "requested_run_nights": run_nights,
        "tier_limit_nights": tier["max_consecutive_stay_nights"],
        "reason": reason,
        "status": "REQUESTED",
        "granted_run_nights": 0,
        "requested_by_user_id": actor.user_id,
        "decided_by_user_id": None,
        "decision_note": None,
    })
    store.insert("occupancy_exceptions", exception)
    store.touch(membership)
    return response.ok(serializers.reservation(res))


# ---------------------------------------------------------------------------
# satisfaction surveys
# ---------------------------------------------------------------------------
@bp.post("/reservations/<reservation_id>/satisfaction-surveys")
def submit_survey(reservation_id):
    actor = auth.authorize(MEMBER)
    candidate = guards.find("reservations", reservation_id)
    if candidate is not None:
        auth.require_member_owner(actor, engine.membership_of(candidate))
    res = guards.fetch("reservations", reservation_id)
    data = v.body()
    overall = v.req_int(data, "overall_rating", minimum=1, maximum=5)
    cleanliness = v.req_int(data, "cleanliness_rating", minimum=1, maximum=5)
    staff = v.req_int(data, "staff_rating", minimum=1, maximum=5)
    value = v.req_int(data, "value_rating", minimum=1, maximum=5)
    if res["status"] != "COMPLETED":
        fail("ERR_INVALID_RESERVATION_STATE", "only a COMPLETED stay may be rated")

    row = store.base_row(versioned=False)
    row.update({
        "reservation_id": res["id"],
        "park_id": res["park_id"],
        "membership_id": res.get("membership_id"),
        "overall_rating": overall,
        "cleanliness_rating": cleanliness,
        "staff_rating": staff,
        "value_rating": value,
        "weighted_score": float(calc.survey_weighted_score(overall, cleanliness,
                                                           staff, value)),
        "submitted_at": clock.now_iso(),
    })
    store.insert("satisfaction_surveys", row)

    park = engine.park_of(res)
    if park is not None:
        engine.recompute_park_rating(park)
        engine.recompute_project_scores(park)
        store.touch(park)
    return response.created(serializers.survey(row))


# ---------------------------------------------------------------------------
# occupancy exceptions
# ---------------------------------------------------------------------------
@bp.get("/occupancy-exceptions/<exception_id>")
def read_exception(exception_id):
    auth.authorize(CLUB_ADMIN, COMPLIANCE_OFFICER, MEMBER)
    row = guards.fetch("occupancy_exceptions", exception_id)
    return response.ok(serializers.occupancy_exception(row))


@bp.post("/occupancy-exceptions/<exception_id>/decision")
def decide_exception(exception_id):
    actor = auth.authorize(COMPLIANCE_OFFICER)
    exception = guards.fetch("occupancy_exceptions", exception_id)
    data = v.body()
    decision = v.req_enum(data, "decision", ("GRANT", "DENY"))
    note = v.opt_str(data, "decision_note")
    granted = None
    if decision == "GRANT":
        granted = v.req_int(data, "granted_run_nights", minimum=1)
        if granted < exception["tier_limit_nights"]:
            fail("ERR_INVALID_REQUEST",
                 "granted_run_nights must be at least tier_limit_nights")
    if exception["status"] != "REQUESTED":
        fail("ERR_EXCEPTION_ALREADY_DECIDED", "this exception is already decided")

    res = guards.fetch("reservations", exception["reservation_id"])
    park = guards.fetch("parks", res["park_id"])
    membership = engine.membership_of(res)
    agreement = engine.agreement_of(park)
    arrival = engine.as_date(res["arrival_date"])

    if decision == "DENY":
        exception["status"] = "DENIED"
        exception["decided_by_user_id"] = actor.user_id
        exception["decision_note"] = note
        store.touch(exception)
        rolled_back = res.get("_pre_extension_departure_date") or res["departure_date"]
        res["departure_date"] = rolled_back
        res["nights"] = (engine.as_date(rolled_back) - arrival).days
        res["status"] = "CHECKED_IN"
        res["extension_denied_count"] = res["extension_denied_count"] + 1
        store.touch(res)
        if membership is not None:
            store.touch(membership)
        return response.ok(serializers.occupancy_exception(exception))

    if granted > calc.ABSOLUTE_MAX_RUN_NIGHTS:
        fail("ERR_ABSOLUTE_OCCUPANCY_CAP",
             "a grant may not exceed %d nights" % calc.ABSOLUTE_MAX_RUN_NIGHTS)
    _, run_arrival, _ = engine.merged_run(res.get("membership_id"), park["id"],
                                         res["arrival_date"], res["departure_date"],
                                         exclude_res_id=res["id"],
                                         created_at=res.get("created_at"),
                                         seq=res.get("_seq"))
    new_departure = clock.add_days(run_arrival, granted)
    if new_departure <= arrival:
        fail("ERR_INVALID_REQUEST", "the granted run is shorter than the stay's start")
    new_nights = (new_departure - arrival).days
    delta = new_nights - (res.get("entitlement_nights_charged") or 0)
    tier = engine.tier_of(membership) if membership is not None else None
    if (membership is None or tier is None
            or (delta > 0 and not engine.entitlement_headroom_ok(membership, tier, park,
                                                                delta))):
        fail("ERR_ENTITLEMENT_NIGHTS_EXHAUSTED", "entitlement nights are exhausted")

    exception["status"] = "GRANTED"
    exception["granted_run_nights"] = granted
    exception["decided_by_user_id"] = actor.user_id
    exception["decision_note"] = note
    store.touch(exception)

    res["departure_date"] = clock.fmt_date(new_departure)
    res["nights"] = new_nights
    res["status"] = "CHECKED_IN"
    res["extension_count"] = res["extension_count"] + 1
    if delta > 0:
        res["entitlement_nights_charged"] = new_nights
        engine.debit_entitlement(membership, park, delta)
        if agreement is not None:
            quota_delta = (engine.quota_charge_for(agreement, new_nights)
                           - (res.get("affiliate_nights_charged") or 0))
            if quota_delta > 0:
                res["affiliate_nights_charged"] = ((res.get("affiliate_nights_charged") or 0)
                                                   + quota_delta)
                engine.add_quota(agreement, quota_delta)
    run_nights, _, _ = engine.merged_run(res.get("membership_id"), park["id"],
                                        res["arrival_date"], res["departure_date"],
                                        exclude_res_id=res["id"],
                                        created_at=res.get("created_at"),
                                        seq=res.get("_seq"))
    res["consecutive_run_nights"] = run_nights
    store.touch(res)
    store.touch(membership)
    return response.ok(serializers.occupancy_exception(exception))
