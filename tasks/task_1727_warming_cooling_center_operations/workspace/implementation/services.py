"""Business logic: breach evaluation, capacity pools, overnight coverage,
bed nights, meal stock, cascades, ops sweep, and entity serializers."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING

import clock
import db
from util import floor_minutes, midnight_crossings, render_dt, touch

MAX_GAP_MINUTES = 15
NO_SHOW_GRACE_MINUTES = 60
OVERNIGHT_MINUTES = 480

MEAL_BUFFERS = {
    "BREAKFAST": Decimal("1.10"),
    "LUNCH": Decimal("1.15"),
    "DINNER": Decimal("1.25"),
}

ACTIVE_STAY_STATUSES = ("RESERVED", "CHECKED_IN")


# ------------------------------------------------------------------ queries
def _created_key(rec):
    return (rec["created_at"], rec["_seq"])


def episodes_activations(episode_id):
    return [a for a in db.store["activations"].values()
            if a["episode_id"] == episode_id]


def activations_stays(act_id):
    return [s for s in db.store["stays"].values()
            if s["site_activation_id"] == act_id]


def activations_shifts(act_id):
    return [s for s in db.store["shifts"].values()
            if s["site_activation_id"] == act_id]


def activations_donations(act_id):
    return [d for d in db.store["donations"].values()
            if d["site_activation_id"] == act_id]


def activations_meal_services(act_id):
    return [m for m in db.store["meal_services"].values()
            if m["site_activation_id"] == act_id]


def episode_of_activation(act):
    return db.store["episodes"].get(act["episode_id"])


def episode_children(episode_id, kind):
    """All records of `kind` belonging to any activation of the episode."""
    out = []
    for act in episodes_activations(episode_id):
        out.extend([r for r in db.store[kind].values()
                    if r.get("site_activation_id") == act["id"]])
    return out


# ------------------------------------------------------- breach evaluation
def episode_readings(episode_id):
    rs = [r for r in db.store["readings"].values()
          if r["episode_id"] == episode_id]
    rs.sort(key=lambda r: (r["observed_at"], r["created_at"], r["_seq"]))
    return rs


def evaluate_breach(ep):
    """breach_run_evaluation (SCAFFOLD §1.3). Mutates trigger_met and
    breach_run_minutes in place; never touches version/updated_at."""
    readings = episode_readings(ep["id"])
    mode = ep["mode"]
    thr = ep["threshold_f"]
    run_start = None
    run_last = None
    for r in readings:
        if mode == "COOLING":
            breach = r["heat_index_f"] >= thr
        else:  # WARMING
            breach = r["temp_f"] <= thr
        if not breach:
            run_start = None
            run_last = None
            continue
        if run_start is None:
            run_start = r["observed_at"]
            run_last = r["observed_at"]
            continue
        gap_min = floor_minutes(r["observed_at"] - run_last)
        if gap_min <= MAX_GAP_MINUTES:
            run_last = r["observed_at"]
        else:
            run_start = r["observed_at"]
            run_last = r["observed_at"]
    if run_start is None:
        ep["breach_run_minutes"] = 0
        ep["trigger_met"] = False
    else:
        ep["breach_run_minutes"] = floor_minutes(run_last - run_start)
        ep["trigger_met"] = (
            ep["breach_run_minutes"] >= ep["sustained_hours_required"] * 60
        )


# ------------------------------------------------------- capacity pools
def pools(act):
    """capacity_recompute (SCAFFOLD §1.3) — live aggregation over stays."""
    stays = activations_stays(act["id"])
    occupied = sum(1 for s in stays if s["status"] == "CHECKED_IN")
    reserved = sum(1 for s in stays if s["status"] == "RESERVED")
    beds_eff = act["beds_effective"]
    beds_free = None
    if beds_eff is not None:
        beds_free = beds_eff - occupied - reserved
    site = db.store["sites"].get(act["site_id"])
    pet_cap = site["pet_capacity"] if site else 0
    locker_cap = site["locker_capacity"] if site else 0
    pet_used = sum(s["pet_slots_used"] for s in stays
                   if s["status"] in ACTIVE_STAY_STATUSES)
    locker_used = sum(s["lockers_used"] for s in stays
                      if s["status"] in ACTIVE_STAY_STATUSES)
    return {
        "occupied_beds": occupied,
        "reserved_beds": reserved,
        "beds_free": beds_free,
        "pet_slots_free": pet_cap - pet_used,
        "lockers_free": locker_cap - locker_used,
    }


# ------------------------------------------------------- overnight coverage
def overnight_window():
    """Tonight's half-open window [today 22:00, tomorrow 06:00) on the
    logical clock."""
    n = clock.now()
    start = datetime(n.year, n.month, n.day, 22, 0, 0, tzinfo=timezone.utc)
    end = datetime(n.year, n.month, n.day, 6, 0, 0,
                   tzinfo=timezone.utc) + timedelta(days=1)
    return start, end


def coverage(act):
    """overnight_coverage_gap (SCAFFOLD §1.3): interval merge of CONFIRMED
    shifts against tonight's window, plus SITE_LEAD full-containment."""
    win_start, win_end = overnight_window()
    segs = []
    lead_ok = False
    for sh in activations_shifts(act["id"]):
        if sh["status"] != "CONFIRMED":
            continue
        s = max(sh["start_at"], win_start)
        e = min(sh["end_at"], win_end)
        if s < e:
            segs.append((s, e))
        if (sh["role_on_shift"] == "SITE_LEAD"
                and sh["start_at"] <= win_start
                and sh["end_at"] >= win_end):
            lead_ok = True
    segs.sort(key=lambda x: x[0])
    covered_seconds = 0
    cur_s = None
    cur_e = None
    for s, e in segs:
        if cur_s is None:
            cur_s, cur_e = s, e
        elif s <= cur_e:  # overlapping or merely touching pieces merge
            cur_e = max(cur_e, e)
        else:
            covered_seconds += (cur_e - cur_s).total_seconds()
            cur_s, cur_e = s, e
    if cur_s is not None:
        covered_seconds += (cur_e - cur_s).total_seconds()
    covered = int(covered_seconds // 60)
    return OVERNIGHT_MINUTES - covered, lead_ok


# ------------------------------------------------------- supply stock
def meal_stock(act):
    on_hand = sum(d["quantity"] for d in activations_donations(act["id"])
                  if d["category"] == "MEAL" and d["status"] == "RECEIVED")
    on_hand -= sum(m["served_count"] or 0
                   for m in activations_meal_services(act["id"])
                   if m["status"] == "SERVED")
    projected = on_hand + sum(
        d["quantity"] for d in activations_donations(act["id"])
        if d["category"] == "MEAL" and d["status"] == "PLEDGED")
    return on_hand, projected


# ------------------------------------------------------- bed nights
def bed_nights_final(stay):
    if stay["checked_in_at"] is None or stay["checked_out_at"] is None:
        return None
    return midnight_crossings(stay["checked_in_at"], stay["checked_out_at"])


def bed_nights_provisional(stay):
    ci = stay["checked_in_at"]
    if ci is None:
        return 0
    extra = 1 if stay["status"] == "CHECKED_IN" else 0
    return midnight_crossings(ci, clock.now()) + extra


# ------------------------------------------------------- medical hold
def medical_hold(guest_id):
    return any(
        i for i in db.store["incidents"].values()
        if i["guest_id"] == guest_id
        and i["kind"] == "MEDICAL"
        and i["status"] == "ESCALATED"
    )


# ------------------------------------------------------- dispatch helpers
def reserved_bed_count(dispatch_id):
    return sum(
        1 for s in db.store["stays"].values()
        if s["transport_dispatch_id"] == dispatch_id
        and s["status"] == "RESERVED"
    )


def guest_active_stay_in_episode(guest_id, episode_id):
    for act in episodes_activations(episode_id):
        for s in activations_stays(act["id"]):
            if (s["guest_id"] == guest_id
                    and s["status"] in ACTIVE_STAY_STATUSES):
                return s
    return None


def lockers_for_bags(bag_count):
    return -(-bag_count // 2)  # ceil(bag_count / 2)


# ------------------------------------------------------- cascades
def close_activation(act):
    """SiteActivation -> CLOSED with its close side effects, including the
    possible immediate Episode DEACTIVATING -> DEACTIVATED settle."""
    act["status"] = "CLOSED"
    touch(act)
    for sh in activations_shifts(act["id"]):
        if sh["status"] in ("PLANNED", "CONFIRMED"):
            sh["status"] = "CANCELLED"
            touch(sh)
    ep = episode_of_activation(act)
    if ep and ep["status"] == "DEACTIVATING":
        settle_episode_if_drained(ep)


def settle_episode_if_drained(ep):
    if ep["status"] != "DEACTIVATING":
        return
    acts = episodes_activations(ep["id"])
    if acts and all(a["status"] == "CLOSED" for a in acts):
        ep["status"] = "DEACTIVATED"
        touch(ep)


def deactivate_episode(ep):
    """ACTIVE -> DEACTIVATING with the L1 -> L2 -> L3 cascade."""
    ep["status"] = "DEACTIVATING"
    ep["deactivated_at"] = clock.now()
    touch(ep)
    acts = episodes_activations(ep["id"])
    # L1a: OPEN -> DRAINING in created_at ASC order
    open_acts = sorted((a for a in acts if a["status"] == "OPEN"),
                       key=_created_key)
    for act in open_acts:
        act["status"] = "DRAINING"
        touch(act)
        # L2: every RESERVED stay -> CANCELLED, created_at ASC
        res_stays = sorted(
            (s for s in activations_stays(act["id"])
             if s["status"] == "RESERVED"),
            key=_created_key,
        )
        for stay in res_stays:
            stay["status"] = "CANCELLED"
            touch(stay)
            # L3: linked dispatch reserved count decrements; at zero on an
            # ASSIGNED dispatch the dispatch itself cancels.
            disp_id = stay["transport_dispatch_id"]
            if disp_id:
                disp = db.store["dispatches"].get(disp_id)
                if (disp is not None
                        and reserved_bed_count(disp_id) == 0
                        and disp["status"] == "ASSIGNED"):
                    disp["status"] = "CANCELLED"
                    touch(disp)
    # L1b: OPENING -> CLOSED with close side effects, created_at ASC
    opening_acts = sorted((a for a in acts if a["status"] == "OPENING"),
                          key=_created_key)
    for act in opening_acts:
        close_activation(act)


def resurge_episode(ep):
    """DEACTIVATING -> ACTIVE re-surge: DRAINING activations return to OPEN
    in created_at ASC order. Cancelled stays stay cancelled; CLOSED stays
    CLOSED."""
    ep["status"] = "ACTIVE"
    touch(ep)
    draining = sorted(
        (a for a in episodes_activations(ep["id"]) if a["status"] == "DRAINING"),
        key=_created_key,
    )
    for act in draining:
        act["status"] = "OPEN"
        touch(act)


def ops_sweep(ep):
    """ops_sweep (SCAFFOLD §1.3): pinned step order. Advances ops_run_index
    and the episode version by exactly one."""
    now = clock.now()
    ep["ops_run_index"] += 1
    # (1) CONFIRMED shifts with end_at <= now -> COMPLETED, created_at ASC
    shifts = sorted(
        (s for s in episode_children(ep["id"], "shifts")
         if s["status"] == "CONFIRMED" and s["end_at"] <= now),
        key=_created_key,
    )
    for sh in shifts:
        sh["status"] = "COMPLETED"
        touch(sh)
    # (2) RESERVED stays past the no-show grace -> NO_SHOW, created_at ASC
    grace = timedelta(minutes=NO_SHOW_GRACE_MINUTES)
    stays = sorted(
        (s for s in episode_children(ep["id"], "stays")
         if s["status"] == "RESERVED"),
        key=_created_key,
    )
    for stay in stays:
        disp = db.store["dispatches"].get(stay["transport_dispatch_id"] or "")
        if (disp is not None
                and disp["status"] == "ARRIVED"
                and disp["arrived_at"] is not None
                and now >= disp["arrived_at"] + grace):
            stay["status"] = "NO_SHOW"
            touch(stay)
    # (3) settle DEACTIVATING -> DEACTIVATED when all sites closed
    if ep["status"] == "DEACTIVATING":
        acts = episodes_activations(ep["id"])
        if acts and all(a["status"] == "CLOSED" for a in acts):
            ep["status"] = "DEACTIVATED"
    touch(ep)


# ------------------------------------------------------- serializers
def ser_episode(ep):
    evaluate_breach(ep)
    return {
        "id": ep["id"],
        "mode": ep["mode"],
        "threshold_f": ep["threshold_f"],
        "sustained_hours_required": ep["sustained_hours_required"],
        "scheduled_end_at": render_dt(ep["scheduled_end_at"]),
        "status": ep["status"],
        "trigger_met": ep["trigger_met"],
        "breach_run_minutes": ep["breach_run_minutes"],
        "activated_at": render_dt(ep["activated_at"]),
        "activated_by_user_id": ep["activated_by_user_id"],
        "deactivated_at": render_dt(ep["deactivated_at"]),
        "extension_count": ep["extension_count"],
        "ops_run_index": ep["ops_run_index"],
        "created_at": render_dt(ep["created_at"]),
        "updated_at": render_dt(ep["updated_at"]),
        "version": ep["version"],
    }


def ser_reading(r):
    return {
        "id": r["id"],
        "episode_id": r["episode_id"],
        "observed_at": render_dt(r["observed_at"]),
        "temp_f": r["temp_f"],
        "heat_index_f": r["heat_index_f"],
        "source": r["source"],
        "created_at": render_dt(r["created_at"]),
    }


def ser_site(s):
    return {
        "id": s["id"],
        "name": s["name"],
        "address": s["address"],
        "bed_capacity": s["bed_capacity"],
        "pet_capacity": s["pet_capacity"],
        "locker_capacity": s["locker_capacity"],
        "created_at": render_dt(s["created_at"]),
        "updated_at": render_dt(s["updated_at"]),
        "version": s["version"],
    }


def ser_activation(act):
    p = pools(act)
    gap, lead_ok = coverage(act)
    on_hand, projected = meal_stock(act)
    return {
        "id": act["id"],
        "episode_id": act["episode_id"],
        "site_id": act["site_id"],
        "capacity_override": act["capacity_override"],
        "status": act["status"],
        "beds_effective": act["beds_effective"],
        "occupied_beds": p["occupied_beds"],
        "reserved_beds": p["reserved_beds"],
        "beds_free": p["beds_free"],
        "pet_slots_free": p["pet_slots_free"],
        "lockers_free": p["lockers_free"],
        "overnight_coverage_gap_minutes": gap,
        "lead_coverage_ok": lead_ok,
        "meal_stock_on_hand": on_hand,
        "meal_stock_projected": projected,
        "opened_at": render_dt(act["opened_at"]),
        "created_at": render_dt(act["created_at"]),
        "updated_at": render_dt(act["updated_at"]),
        "version": act["version"],
    }


def ser_staff(s):
    return {
        "id": s["id"],
        "full_name": s["full_name"],
        "skills": list(s["skills"]),
        "active": s["active"],
        "created_at": render_dt(s["created_at"]),
        "updated_at": render_dt(s["updated_at"]),
        "version": s["version"],
    }


def ser_shift(sh):
    return {
        "id": sh["id"],
        "site_activation_id": sh["site_activation_id"],
        "staff_member_id": sh["staff_member_id"],
        "role_on_shift": sh["role_on_shift"],
        "start_at": render_dt(sh["start_at"]),
        "end_at": render_dt(sh["end_at"]),
        "status": sh["status"],
        "created_at": render_dt(sh["created_at"]),
        "updated_at": render_dt(sh["updated_at"]),
        "version": sh["version"],
    }


def ser_guest(g):
    return {
        "id": g["id"],
        "alias": g["alias"],
        "has_pets": g["has_pets"],
        "pet_count": g["pet_count"],
        "bag_count": g["bag_count"],
        "medical_flag": g["medical_flag"],
        "medical_hold_active": medical_hold(g["id"]),
        "created_at": render_dt(g["created_at"]),
        "updated_at": render_dt(g["updated_at"]),
        "version": g["version"],
    }


def ser_stay(s):
    return {
        "id": s["id"],
        "site_activation_id": s["site_activation_id"],
        "guest_id": s["guest_id"],
        "transport_dispatch_id": s["transport_dispatch_id"],
        "status": s["status"],
        "pet_slots_used": s["pet_slots_used"],
        "lockers_used": s["lockers_used"],
        "checked_in_at": render_dt(s["checked_in_at"]),
        "checked_out_at": render_dt(s["checked_out_at"]),
        "bed_nights_provisional": bed_nights_provisional(s),
        "bed_nights_final": bed_nights_final(s),
        "transfer_sequence": s["transfer_sequence"],
        "created_at": render_dt(s["created_at"]),
        "updated_at": render_dt(s["updated_at"]),
        "version": s["version"],
    }


def ser_vehicle(v):
    return {
        "id": v["id"],
        "label": v["label"],
        "seats": v["seats"],
        "turnaround_minutes": v["turnaround_minutes"],
        "created_at": render_dt(v["created_at"]),
        "updated_at": render_dt(v["updated_at"]),
        "version": v["version"],
    }


def ser_dispatch(d):
    return {
        "id": d["id"],
        "site_activation_id": d["site_activation_id"],
        "vehicle_id": d["vehicle_id"],
        "requested_by_user_id": d["requested_by_user_id"],
        "guest_ids": list(d["guest_ids"]),
        "pickup_window_start": render_dt(d["pickup_window_start"]),
        "pickup_window_end": render_dt(d["pickup_window_end"]),
        "has_pets": d["has_pets"],
        "status": d["status"],
        "reserved_bed_count": reserved_bed_count(d["id"]),
        "arrived_at": render_dt(d["arrived_at"]),
        "created_at": render_dt(d["created_at"]),
        "updated_at": render_dt(d["updated_at"]),
        "version": d["version"],
    }


def ser_donation(d):
    return {
        "id": d["id"],
        "site_activation_id": d["site_activation_id"],
        "partner_name": d["partner_name"],
        "category": d["category"],
        "quantity": d["quantity"],
        "status": d["status"],
        "created_at": render_dt(d["created_at"]),
        "updated_at": render_dt(d["updated_at"]),
        "version": d["version"],
    }


def ser_meal_service(m):
    return {
        "id": m["id"],
        "site_activation_id": m["site_activation_id"],
        "service_date": render_dt(m["service_date"]),
        "meal_period": m["meal_period"],
        "planned_meals": m["planned_meals"],
        "served_count": m["served_count"],
        "status": m["status"],
        "created_at": render_dt(m["created_at"]),
        "updated_at": render_dt(m["updated_at"]),
        "version": m["version"],
    }


def ser_incident(i):
    return {
        "id": i["id"],
        "site_activation_id": i["site_activation_id"],
        "guest_id": i["guest_id"],
        "kind": i["kind"],
        "severity": i["severity"],
        "reporter_user_id": i["reporter_user_id"],
        "status": i["status"],
        "resolved_by_user_id": i["resolved_by_user_id"],
        "resolution_note": i["resolution_note"],
        "created_at": render_dt(i["created_at"]),
        "updated_at": render_dt(i["updated_at"]),
        "version": i["version"],
    }


def ser_aar(a):
    return {
        "id": a["id"],
        "episode_id": a["episode_id"],
        "status": a["status"],
        "total_unique_guests": a["total_unique_guests"],
        "total_bed_nights": a["total_bed_nights"],
        "meals_served": a["meals_served"],
        "incidents_by_severity": dict(a["incidents_by_severity"]),
        "transports_arrived": a["transports_arrived"],
        "submitted_by_user_id": a["submitted_by_user_id"],
        "approved_by_user_id": a["approved_by_user_id"],
        "created_at": render_dt(a["created_at"]),
        "updated_at": render_dt(a["updated_at"]),
        "version": a["version"],
    }


def meal_planned(act, meal_period):
    """meal_planned_rounding: each service rounds UP individually at
    creation from the pinned attendance snapshot."""
    p = pools(act)
    attendance = p["occupied_beds"] + p["reserved_beds"]
    value = Decimal(attendance) * MEAL_BUFFERS[meal_period]
    return int(value.to_integral_value(rounding=ROUND_CEILING))
