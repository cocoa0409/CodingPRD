"""Derived-field computation, state-transition cascades, scheduler epoch.

Derived counters/flags are computed on read (never stored); stored fields are
only those the scaffold marks source: system that are not derivable.
Version bumps follow the scaffold side_effects tables literally.
"""
from datetime import datetime, timedelta, time as dtime

import clock
import db
from util import fmt_ts, new_id

GRACE_MINUTES = 30
SUPERVISION_RATIO = 8
NO_SHOW_THRESHOLD = 3
WAIVER_TTL_DAYS = 365
BED_BUFFER_DAYS = 14
KEY_REGISTRY_MAX = 4

SIGNUP_TERMINAL = {"COMPLETED", "NO_SHOW", "CANCELLED"}
SIGNUP_OCCUPYING = {"CONFIRMED", "CHECKED_IN"}
IRRIGATION_COMMITTED = {"SCHEDULED", "DUE", "MISSED"}
IRRIGATION_ACTUAL = {"LOGGED", "RECONCILED"}
IRRIGATION_OCCUPIED = {"SCHEDULED", "DUE", "MISSED", "LOGGED", "RECONCILED"}
ALLOCATION_ACTIVE = {"PENDING", "APPROVED", "DISTRIBUTED"}
PLAN_ALLOCATING = {"APPROVED", "PLANTED", "HARVESTING"}


def bump(entity: dict) -> None:
    entity["version"] += 1
    entity["updated_at"] = clock.now()


def create_record(fields: dict) -> dict:
    now = clock.now()
    rec = {"id": new_id(), "created_at": now, "updated_at": now, "version": 1}
    rec.update(fields)
    return rec


# --------------------------------------------------------------------------
# Volunteer derived fields
# --------------------------------------------------------------------------

def volunteer_is_minor(vol: dict) -> bool:
    dob = vol["_dob"]  # stored date object alongside the raw string
    d = clock.now().date()
    age = d.year - dob.year - ((d.month, d.day) < (dob.month, dob.day))
    return age < 18


def has_active_cert(volunteer_id: str, cert_type: str) -> bool:
    return any(
        c["volunteer_id"] == volunteer_id and c["cert_type"] == cert_type and c["status"] == "ACTIVE"
        for c in db.certifications.values()
    )


def volunteer_view(vol: dict) -> dict:
    vid = vol["id"]
    return {
        "id": vid,
        "full_name": vol["full_name"],
        "email": vol["email"],
        "phone": vol["phone"],
        "date_of_birth": vol["date_of_birth"],
        "is_minor": volunteer_is_minor(vol),
        "orientation_status": vol["orientation_status"],
        "waiver_status": vol["waiver_status"],
        "waiver_signed_at": fmt_ts(vol["waiver_signed_at"]) if vol["waiver_signed_at"] else None,
        "standing": vol["standing"],
        "can_supervise": has_active_cert(vid, "SUPERVISION"),
        "produce_safety_certified": has_active_cert(vid, "PRODUCE_SAFETY"),
        "tool_safety_certified": has_active_cert(vid, "TOOL_SAFETY"),
        "total_service_minutes": sum(
            s["credited_minutes"] for s in db.signups.values()
            if s["volunteer_id"] == vid and s["status"] in {"CHECKED_IN", "COMPLETED"}
        ),
        "no_show_count": sum(
            1 for s in db.signups.values() if s["volunteer_id"] == vid and s["status"] == "NO_SHOW"
        ),
        "held_key_count": sum(
            1 for k in db.keys.values()
            if k["current_holder_volunteer_id"] == vid and k["status"] in {"CHECKED_OUT", "OVERDUE"}
        ),
        "created_at": fmt_ts(vol["created_at"]),
        "updated_at": fmt_ts(vol["updated_at"]),
        "version": vol["version"],
    }


def certification_view(cert: dict) -> dict:
    return {
        "id": cert["id"],
        "volunteer_id": cert["volunteer_id"],
        "cert_type": cert["cert_type"],
        "issued_at": fmt_ts(cert["issued_at"]),
        "expires_at": fmt_ts(cert["expires_at"]),
        "status": cert["status"],
        "revoked_reason": cert["revoked_reason"],
        "created_at": fmt_ts(cert["created_at"]),
        "updated_at": fmt_ts(cert["updated_at"]),
        "version": cert["version"],
    }


# --------------------------------------------------------------------------
# Season / bed / crop plan derived fields
# --------------------------------------------------------------------------

def season_water(season_id: str):
    committed = sum(
        s["planned_gallons"] for s in db.irrigations.values()
        if s["season_id"] == season_id and s["status"] in IRRIGATION_COMMITTED
    )
    actual = sum(
        s["gallons_actual"] for s in db.irrigations.values()
        if s["season_id"] == season_id and s["status"] in IRRIGATION_ACTUAL
        and s["gallons_actual"] is not None
    )
    return committed, actual


def season_view(season: dict) -> dict:
    committed, actual = season_water(season["id"])
    return {
        "id": season["id"],
        "name": season["name"],
        "signup_opens_at": fmt_ts(season["signup_opens_at"]),
        "signup_closes_at": fmt_ts(season["signup_closes_at"]),
        "season_starts_at": fmt_ts(season["season_starts_at"]),
        "season_ends_at": fmt_ts(season["season_ends_at"]),
        "water_budget_gallons": season["water_budget_gallons"],
        "water_committed_gallons": committed,
        "water_actual_gallons": actual,
        "water_remaining_gallons": season["water_budget_gallons"] - committed - actual,
        "status": season["status"],
        "created_at": fmt_ts(season["created_at"]),
        "updated_at": fmt_ts(season["updated_at"]),
        "version": season["version"],
    }


def bed_allocated_sq_ft(bed_id: str) -> int:
    return sum(
        p["requested_sq_ft"] for p in db.crop_plans.values()
        if p["bed_id"] == bed_id and p["status"] in PLAN_ALLOCATING
    )


def bed_view(bed: dict) -> dict:
    return {
        "id": bed["id"],
        "bed_code": bed["bed_code"],
        "size_sq_ft": bed["size_sq_ft"],
        "sun_exposure": bed["sun_exposure"],
        "irrigation_zone": bed["irrigation_zone"],
        "soil_ph": bed["soil_ph"],
        "allocated_sq_ft": bed_allocated_sq_ft(bed["id"]),
        "last_plant_family": bed["last_plant_family"],
        "last_harvest_closed_at": fmt_ts(bed["last_harvest_closed_at"]) if bed["last_harvest_closed_at"] else None,
        "status": bed["status"],
        "created_at": fmt_ts(bed["created_at"]),
        "updated_at": fmt_ts(bed["updated_at"]),
        "version": bed["version"],
    }


def crop_plan_view(plan: dict) -> dict:
    return {
        "id": plan["id"],
        "season_id": plan["season_id"],
        "bed_id": plan["bed_id"],
        "proposer_volunteer_id": plan["proposer_volunteer_id"],
        "crop_type": plan["crop_type"],
        "plant_family": plan["plant_family"],
        "requested_sq_ft": plan["requested_sq_ft"],
        "planned_start_date": plan["planned_start_date"].isoformat(),
        "planned_end_date": plan["planned_end_date"].isoformat(),
        "expected_yield_grams": plan["expected_yield_grams"],
        "rejection_reason": plan["rejection_reason"],
        "status": plan["status"],
        "created_at": fmt_ts(plan["created_at"]),
        "updated_at": fmt_ts(plan["updated_at"]),
        "version": plan["version"],
    }


# --------------------------------------------------------------------------
# Slot occupancy / signup / booking derived fields
# --------------------------------------------------------------------------

def slot_pools(slot_id: str):
    signups = [s for s in db.signups.values() if s["slot_id"] == slot_id]
    bookings = [b for b in db.bookings.values() if b["slot_id"] == slot_id]
    confirmed = sum(1 for s in signups if s["status"] in SIGNUP_OCCUPYING)
    confirmed += sum(b["member_count"] for b in bookings if b["status"] in SIGNUP_OCCUPYING)
    youth = sum(1 for s in signups if s["status"] in SIGNUP_OCCUPYING and s["is_youth"])
    youth += sum(b["minor_count"] for b in bookings if b["status"] in SIGNUP_OCCUPYING)
    waitlist = sum(1 for s in signups if s["status"] == "WAITLISTED")
    return confirmed, youth, waitlist


def slot_view(slot: dict) -> dict:
    confirmed, youth, waitlist = slot_pools(slot["id"])
    return {
        "id": slot["id"],
        "season_id": slot["season_id"],
        "task_type": slot["task_type"],
        "starts_at": fmt_ts(slot["starts_at"]),
        "ends_at": fmt_ts(slot["ends_at"]),
        "capacity_total": slot["capacity_total"],
        "capacity_youth": slot["capacity_youth"],
        "requires_produce_safety": slot["requires_produce_safety"],
        "required_tool_id": slot["required_tool_id"],
        "required_tool_qty": slot["required_tool_qty"],
        "confirmed_count": confirmed,
        "confirmed_youth_count": youth,
        "waitlist_count": waitlist,
        "next_waitlist_position": slot["next_waitlist_position"],
        "status": slot["status"],
        "created_at": fmt_ts(slot["created_at"]),
        "updated_at": fmt_ts(slot["updated_at"]),
        "version": slot["version"],
    }


def signup_view(signup: dict) -> dict:
    return {
        "id": signup["id"],
        "slot_id": signup["slot_id"],
        "volunteer_id": signup["volunteer_id"],
        "supervision_adult_signup_id": signup["supervision_adult_signup_id"],
        "is_youth": signup["is_youth"],
        "waitlist_position": signup["waitlist_position"],
        "checked_in_at": fmt_ts(signup["checked_in_at"]) if signup["checked_in_at"] else None,
        "checked_out_at": fmt_ts(signup["checked_out_at"]) if signup["checked_out_at"] else None,
        "credited_minutes": signup["credited_minutes"],
        "status": signup["status"],
        "created_at": fmt_ts(signup["created_at"]),
        "updated_at": fmt_ts(signup["updated_at"]),
        "version": signup["version"],
    }


def booking_view(booking: dict) -> dict:
    return {
        "id": booking["id"],
        "slot_id": booking["slot_id"],
        "leader_volunteer_id": booking["leader_volunteer_id"],
        "organization_name": booking["organization_name"],
        "member_count": booking["member_count"],
        "minor_count": booking["minor_count"],
        "chaperone_count": booking["chaperone_count"],
        "chaperone_volunteer_ids": list(booking["chaperone_volunteer_ids"]),
        "required_chaperones": booking["required_chaperones"],
        "rejection_reason": booking["rejection_reason"],
        "status": booking["status"],
        "created_at": fmt_ts(booking["created_at"]),
        "updated_at": fmt_ts(booking["updated_at"]),
        "version": booking["version"],
    }


def scheduled_minutes(slot: dict) -> int:
    return int((slot["ends_at"] - slot["starts_at"]).total_seconds() // 60)


def recompute_slot_status(slot: dict) -> None:
    """OPEN<->FULL auto-determination; bumps slot version on a flip."""
    if slot["status"] not in {"OPEN", "FULL"}:
        return
    confirmed, _, _ = slot_pools(slot["id"])
    target = "FULL" if confirmed == slot["capacity_total"] else "OPEN"
    if target != slot["status"]:
        slot["status"] = target
        bump(slot)


def promote_waitlist(slot: dict) -> None:
    """waitlist_promotion_select: promote the lowest-position WAITLISTED signup
    satisfying both pools, then re-evaluate OPEN/FULL."""
    if slot["status"] not in {"OPEN", "FULL"}:
        return
    candidates = sorted(
        (s for s in db.signups.values() if s["slot_id"] == slot["id"] and s["status"] == "WAITLISTED"),
        key=lambda s: s["waitlist_position"],
    )
    for cand in candidates:
        confirmed, youth, _ = slot_pools(slot["id"])
        if confirmed + 1 > slot["capacity_total"]:
            continue
        if cand["is_youth"] and youth + 1 > slot["capacity_youth"]:
            continue
        cand["status"] = "CONFIRMED"
        cand["waitlist_position"] = None
        bump(cand)
        break
    recompute_slot_status(slot)


def cancel_signup(signup: dict) -> None:
    """Shared cancel path (manual + slot-cancel cascade + suspension cascade +
    supervision-loss cascade). No lock check here; callers enforce it where
    the machine requires it."""
    was_confirmed = signup["status"] == "CONFIRMED"
    signup["status"] = "CANCELLED"
    signup["waitlist_position"] = None
    bump(signup)
    slot = db.slots.get(signup["slot_id"])
    if slot is not None and was_confirmed:
        promote_waitlist(slot)
    # supervision-loss cascade: youth signups supervised by this one are cancelled
    dependents = [
        s for s in db.signups.values()
        if s["supervision_adult_signup_id"] == signup["id"]
        and s["slot_id"] == signup["slot_id"]
        and s["status"] in {"REQUESTED", "CONFIRMED"}
    ]
    dependents.sort(key=lambda s: (s["created_at"], s["id"]))
    for dep in dependents:
        cancel_signup(dep)


def auto_close_checkouts_for_signup(signup_id: str) -> None:
    for co in db.checkouts.values():
        if co["signup_id"] == signup_id and co["status"] == "OPEN":
            co["status"] = "AUTO_CLOSED"
            bump(co)


def cancel_slot_cascade(slot: dict) -> None:
    """ShiftSlot -> CANCELLED side effects (manual or season cascade)."""
    affected_signups = [
        s for s in db.signups.values()
        if s["slot_id"] == slot["id"] and s["status"] in {"REQUESTED", "CONFIRMED", "WAITLISTED"}
    ]
    affected_signups.sort(key=lambda s: (s["created_at"], s["id"]))
    for s in affected_signups:
        s["status"] = "CANCELLED"
        s["waitlist_position"] = None
        bump(s)
    for s in affected_signups:
        auto_close_checkouts_for_signup(s["id"])
    for b in db.bookings.values():
        if b["slot_id"] == slot["id"] and b["status"] in {"REQUESTED", "CONFIRMED"}:
            b["status"] = "CANCELLED"
            bump(b)


def complete_slot_cascade(slot: dict) -> None:
    """ShiftSlot LOCKED -> COMPLETED side effects: no-shows, standing drops,
    booking resolution."""
    no_show_signups = [
        s for s in db.signups.values() if s["slot_id"] == slot["id"] and s["status"] == "CONFIRMED"
    ]
    no_show_signups.sort(key=lambda s: (s["created_at"], s["id"]))
    for s in no_show_signups:
        s["status"] = "NO_SHOW"
        s["credited_minutes"] = 0
        bump(s)
        vol = db.volunteers.get(s["volunteer_id"])
        if vol is not None:
            count = sum(
                1 for x in db.signups.values()
                if x["volunteer_id"] == vol["id"] and x["status"] == "NO_SHOW"
            )
            if count >= NO_SHOW_THRESHOLD and vol["standing"] == "GOOD":
                vol["standing"] = "PROBATION"
                bump(vol)
    for b in db.bookings.values():
        if b["slot_id"] == slot["id"]:
            if b["status"] == "CHECKED_IN":
                b["status"] = "COMPLETED"
                bump(b)
            elif b["status"] == "CONFIRMED":
                b["status"] = "CANCELLED"
                bump(b)


def suspend_volunteer_cascade(vol: dict) -> None:
    """Volunteer -> SUSPENDED: cancel own REQUESTED/CONFIRMED signups; each freed
    CONFIRMED spot triggers waitlist promotion on its slot."""
    affected = [
        s for s in db.signups.values()
        if s["volunteer_id"] == vol["id"] and s["status"] in {"REQUESTED", "CONFIRMED"}
    ]
    affected.sort(key=lambda s: (s["created_at"], s["id"]))
    for s in affected:
        cancel_signup(s)


# --------------------------------------------------------------------------
# Tools / keys
# --------------------------------------------------------------------------

def tool_checked_out_count(tool_id: str) -> int:
    return sum(
        co["qty"] - co["qty_returned"] for co in db.checkouts.values()
        if co["tool_id"] == tool_id and co["status"] in {"OPEN", "PARTIAL_RETURN"}
    )


def tool_view(tool: dict) -> dict:
    checked_out = tool_checked_out_count(tool["id"])
    available = tool["total_count"] - checked_out - tool["in_maintenance_count"] - tool["written_off_count"]
    return {
        "id": tool["id"],
        "tool_name": tool["tool_name"],
        "category": tool["category"],
        "total_count": tool["total_count"],
        "available_count": available,
        "checked_out_count": checked_out,
        "in_maintenance_count": tool["in_maintenance_count"],
        "written_off_count": tool["written_off_count"],
        "status": tool["status"],
        "created_at": fmt_ts(tool["created_at"]),
        "updated_at": fmt_ts(tool["updated_at"]),
        "version": tool["version"],
    }


def checkout_view(co: dict) -> dict:
    return {
        "id": co["id"],
        "tool_id": co["tool_id"],
        "volunteer_id": co["volunteer_id"],
        "signup_id": co["signup_id"],
        "qty": co["qty"],
        "qty_returned": co["qty_returned"],
        "condition_on_return": co["condition_on_return"],
        "status": co["status"],
        "created_at": fmt_ts(co["created_at"]),
        "updated_at": fmt_ts(co["updated_at"]),
        "version": co["version"],
    }


def key_view(key: dict) -> dict:
    return {
        "id": key["id"],
        "key_code": key["key_code"],
        "current_holder_volunteer_id": key["current_holder_volunteer_id"],
        "due_back_at": fmt_ts(key["due_back_at"]) if key["due_back_at"] else None,
        "status": key["status"],
        "created_at": fmt_ts(key["created_at"]),
        "updated_at": fmt_ts(key["updated_at"]),
        "version": key["version"],
    }


# --------------------------------------------------------------------------
# Harvest / donation / irrigation
# --------------------------------------------------------------------------

def harvest_view(log: dict) -> dict:
    return {
        "id": log["id"],
        "season_id": log["season_id"],
        "bed_id": log["bed_id"],
        "crop_plan_id": log["crop_plan_id"],
        "logged_by_volunteer_id": log["logged_by_volunteer_id"],
        "crop_type": log["crop_type"],
        "weight_grams": log["weight_grams"],
        "quality_grade": log["quality_grade"],
        "harvested_at": fmt_ts(log["harvested_at"]),
        "safety_attestation": log["safety_attestation"],
        "rejection_reason": log["rejection_reason"],
        "status": log["status"],
        "created_at": fmt_ts(log["created_at"]),
        "updated_at": fmt_ts(log["updated_at"]),
        "version": log["version"],
    }


def _iso_week_bounds():
    now = clock.now()
    monday = (now - timedelta(days=now.weekday())).date()
    start = datetime.combine(monday, dtime(0, 0, 0), tzinfo=now.tzinfo)
    return start, start + timedelta(days=7)


def recipient_committed_this_week(recipient_id: str, exclude_allocation_id: str = None) -> int:
    week_start, week_end = _iso_week_bounds()
    total = 0
    for alloc in db.allocations.values():
        if exclude_allocation_id is not None and alloc["id"] == exclude_allocation_id:
            continue
        if alloc["status"] not in ALLOCATION_ACTIVE:
            continue
        created = alloc["created_at"]
        if not (week_start <= created < week_end):
            continue
        for line in alloc["lines"]:
            if line["recipient_id"] == recipient_id:
                total += line["grams"]
    return total


def recipient_view(rec: dict) -> dict:
    return {
        "id": rec["id"],
        "org_name": rec["org_name"],
        "contact_email": rec["contact_email"],
        "weekly_capacity_grams": rec["weekly_capacity_grams"],
        "priority_tier": rec["priority_tier"],
        "accepts_grade_c": rec["accepts_grade_c"],
        "active": rec["active"],
        "committed_this_week_grams": recipient_committed_this_week(rec["id"]),
        "created_at": fmt_ts(rec["created_at"]),
        "updated_at": fmt_ts(rec["updated_at"]),
        "version": rec["version"],
    }


def allocation_view(alloc: dict) -> dict:
    return {
        "id": alloc["id"],
        "harvest_log_id": alloc["harvest_log_id"],
        "volunteer_share_grams": alloc["volunteer_share_grams"],
        "donatable_grams": alloc["donatable_grams"],
        "lines": [dict(line) for line in alloc["lines"]],
        "rejection_reason": alloc["rejection_reason"],
        "status": alloc["status"],
        "created_at": fmt_ts(alloc["created_at"]),
        "updated_at": fmt_ts(alloc["updated_at"]),
        "version": alloc["version"],
    }


def irrigation_view(sched: dict) -> dict:
    actual = sched["gallons_actual"]
    variance = False if actual is None else actual > (sched["planned_gallons"] * 11) // 10
    return {
        "id": sched["id"],
        "season_id": sched["season_id"],
        "zone": sched["zone"],
        "planned_start_at": fmt_ts(sched["planned_start_at"]),
        "planned_end_at": fmt_ts(sched["planned_end_at"]),
        "planned_gallons": sched["planned_gallons"],
        "gallons_actual": actual,
        "variance_flag": variance,
        "status": sched["status"],
        "created_at": fmt_ts(sched["created_at"]),
        "updated_at": fmt_ts(sched["updated_at"]),
        "version": sched["version"],
    }


# --------------------------------------------------------------------------
# Scheduler epoch run (PRD section 2.5)
# --------------------------------------------------------------------------

def run_epoch() -> dict:
    now = clock.now()
    counts = {
        "certifications_expired": 0,
        "waivers_expired": 0,
        "shed_keys_overdue": 0,
        "shift_slots_locked": 0,
        "irrigation_schedules_due": 0,
        "irrigation_schedules_missed": 0,
    }
    for cert in db.certifications.values():
        if cert["status"] == "ACTIVE" and now >= cert["expires_at"]:
            cert["status"] = "EXPIRED"
            bump(cert)
            counts["certifications_expired"] += 1
    for vol in db.volunteers.values():
        if vol["waiver_status"] == "SIGNED" and vol["waiver_signed_at"] is not None:
            if now > vol["waiver_signed_at"] + timedelta(days=WAIVER_TTL_DAYS):
                vol["waiver_status"] = "EXPIRED"
                bump(vol)
                counts["waivers_expired"] += 1
    for key in db.keys.values():
        if key["status"] == "CHECKED_OUT" and key["due_back_at"] is not None and now > key["due_back_at"]:
            key["status"] = "OVERDUE"
            bump(key)
            counts["shed_keys_overdue"] += 1
    for slot in db.slots.values():
        if slot["status"] in {"OPEN", "FULL"} and now >= slot["starts_at"] - timedelta(hours=24):
            slot["status"] = "LOCKED"
            bump(slot)
            counts["shift_slots_locked"] += 1
    for sched in db.irrigations.values():
        if sched["status"] in {"SCHEDULED", "DUE"} and now > sched["planned_end_at"]:
            sched["status"] = "MISSED"
            bump(sched)
            counts["irrigation_schedules_missed"] += 1
        elif sched["status"] == "SCHEDULED" and now >= sched["planned_start_at"]:
            sched["status"] = "DUE"
            bump(sched)
            counts["irrigation_schedules_due"] += 1
    return counts


# --------------------------------------------------------------------------
# List helper: filter + sort + paginate
# --------------------------------------------------------------------------

def list_view(items, filters: dict, args, view_fn):
    """filters: {query_param: stored_record_key_or_callable}."""
    result = []
    for rec in items:
        keep = True
        for param, key in filters.items():
            raw = args.get(param)
            if raw is None:
                continue
            value = key(rec) if callable(key) else rec.get(key)
            if isinstance(value, bool):
                if raw.lower() not in {"true", "false"} or value != (raw.lower() == "true"):
                    keep = False
                    break
            elif value is None or str(value) != raw:
                keep = False
                break
        if keep:
            result.append(rec)
    # Stable sort: created_at ascending; dict insertion order breaks ties.
    result.sort(key=lambda r: r["created_at"])
    return result
