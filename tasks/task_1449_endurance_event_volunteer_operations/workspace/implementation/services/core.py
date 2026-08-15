"""Core shared helpers: record factory, serializers, computed counters, gauntlet."""
from datetime import timedelta

from db import store
from util import (
    new_id, utc_now_iso, logical_now, compute_age_years,
    round_half_up, dec_to_number,
)
import errors

SEAT_OCCUPYING = {"APPROVED", "CONFIRMED", "CHECKED_IN", "COMPLETED"}
NON_TERMINAL_SIGNUP = {"REQUESTED", "WAITLISTED", "APPROVED", "CONFIRMED", "CHECKED_IN"}

TRAINING_VALIDITY_DAYS = {
    "SAFETY_BRIEFING": 30,
    "CAPTAIN_COURSE": 365,
    "MEDICAL_RESPONSE": 730,
}


def make_record(fields):
    now = utc_now_iso()
    rec = {"id": new_id(), "created_at": now, "updated_at": now, "version": 1}
    rec.update(fields)
    return rec


def touch(rec):
    rec["updated_at"] = utc_now_iso()
    rec["version"] += 1


# ------------------------------------------------------------------
# Lookups (404 helpers)
# ------------------------------------------------------------------

def get_event_or_404(event_id):
    ev = store.events.get(event_id)
    if ev is None:
        raise errors.event_not_found()
    return ev


def get_segment_or_404(segment_id):
    seg = store.course_segments.get(segment_id)
    if seg is None:
        raise errors.segment_not_found()
    return seg


def get_role_or_404(role_id):
    role = store.role_catalog_entries.get(role_id)
    if role is None:
        raise errors.role_entry_not_found()
    return role


def get_shift_or_404(shift_id):
    shift = store.shifts.get(shift_id)
    if shift is None:
        raise errors.shift_not_found()
    return shift


def get_group_or_404(group_id):
    grp = store.fundraising_groups.get(group_id)
    if grp is None:
        raise errors.group_not_found()
    return grp


def get_volunteer_or_404(volunteer_id):
    vol = store.volunteers.get(volunteer_id)
    if vol is None:
        raise errors.volunteer_not_found()
    return vol


def get_training_or_404(tr_id):
    tr = store.training_records.get(tr_id)
    if tr is None:
        raise errors.training_record_not_found()
    return tr


def get_signup_or_404(signup_id):
    su = store.signups.get(signup_id)
    if su is None:
        raise errors.signup_not_found()
    return su


def get_inventory_or_404(inv_id):
    inv = store.supply_inventories.get(inv_id)
    if inv is None:
        raise errors.inventory_not_found()
    return inv


def get_distribution_or_404(dist_id):
    dr = store.distribution_records.get(dist_id)
    if dr is None:
        raise errors.distribution_not_found()
    return dr


def get_hour_log_or_404(log_id):
    log = store.hour_logs.get(log_id)
    if log is None:
        raise errors.hour_log_not_found()
    return log


def get_debrief_or_404(debrief_id):
    deb = store.debrief_reports.get(debrief_id)
    if deb is None:
        raise errors.debrief_not_found()
    return deb


def get_adjustment_or_404(adj_id):
    adj = store.role_adjustments.get(adj_id)
    if adj is None:
        raise errors.adjustment_not_found()
    return adj


# ------------------------------------------------------------------
# Computed shift counters / inventory issued
# ------------------------------------------------------------------

def confirmed_count(shift_id):
    return sum(
        1 for s in store.signups.values()
        if s["shift_id"] == shift_id and s["status"] in SEAT_OCCUPYING
    )


def checked_in_count(shift_id):
    return sum(
        1 for s in store.signups.values()
        if s["shift_id"] == shift_id and s["status"] in {"CHECKED_IN", "COMPLETED"}
    )


def inventory_issued_count(inventory_id):
    return sum(
        1 for d in store.distribution_records.values()
        if d.get("inventory_id") == inventory_id
        and d["kind"] == "SUPPLY_ITEM"
        and d["status"] == "ISSUED"
    )


def update_shift_posture(shift):
    """Recompute shift FULL/OPEN shadowing while event PUBLISHED and shift OPEN|FULL.
    Also clears understaffed_alert when headcount is reached."""
    shift["confirmed_count"] = confirmed_count(shift["id"])
    shift["checked_in_count"] = checked_in_count(shift["id"])
    if shift["confirmed_count"] >= shift["required_headcount"]:
        shift["understaffed_alert"] = False
    ev = store.events.get(shift["event_id"])
    if ev and ev["status"] == "PUBLISHED" and shift["status"] in {"OPEN", "FULL"}:
        if shift["confirmed_count"] >= shift["required_headcount"]:
            if shift["status"] != "FULL":
                shift["status"] = "FULL"
                touch(shift)
        else:
            if shift["status"] != "OPEN":
                shift["status"] = "OPEN"
                touch(shift)


# ------------------------------------------------------------------
# Safety gauntlet (age / skill / training) and overlap rule
# ------------------------------------------------------------------

def check_age(volunteer, role):
    if volunteer["age_years_on_event"] < role["min_age_years"]:
        raise errors.min_age_not_met()


def check_skill(volunteer, role):
    req = role["required_skill"]
    if req != "NONE" and req not in (volunteer.get("skill_tags") or []):
        raise errors.required_skill_missing()


def training_current(volunteer_id, module_code, now):
    """True when the volunteer holds a PASSED record for module_code with valid_until >= now."""
    for tr in store.training_records.values():
        if (
            tr["volunteer_id"] == volunteer_id
            and tr["module_code"] == module_code
            and tr["status"] == "PASSED"
            and tr.get("valid_until") is not None
        ):
            from util import parse_dt
            if parse_dt(tr["valid_until"]) >= now:
                return True
    return False


def check_training(volunteer, role, now):
    module = role["required_training_module"]
    if module == "NONE":
        return
    if not training_current(volunteer["id"], module, now):
        raise errors.training_not_current()


def shifts_overlap(candidate_shift, other_shift):
    """Half-open interval overlap with a 30-minute cross-segment buffer."""
    from util import parse_dt
    buffer = timedelta(0)
    if candidate_shift["segment_id"] != other_shift["segment_id"]:
        buffer = timedelta(minutes=30)
    s_start = parse_dt(candidate_shift["start_at"])
    s_end = parse_dt(candidate_shift["end_at"])
    t_start = parse_dt(other_shift["start_at"])
    t_end = parse_dt(other_shift["end_at"])
    return (s_start < t_end + buffer) and (t_start < s_end + buffer)


def check_overlap(volunteer_id, candidate_shift):
    """ERR_SHIFT_TIME_OVERLAP if the volunteer holds an APPROVED/CONFIRMED signup
    on a shift overlapping the candidate under buffer semantics."""
    for su in store.signups.values():
        if (
            su["volunteer_id"] == volunteer_id
            and su["status"] in {"APPROVED", "CONFIRMED"}
            and su["shift_id"] != candidate_shift["id"]
        ):
            other = store.shifts.get(su["shift_id"])
            if other and shifts_overlap(candidate_shift, other):
                raise errors.shift_time_overlap()


def run_safety_gauntlet(volunteer, shift, now):
    """Age -> skill -> training (priority 5,6,7), then overlap is checked separately at 9."""
    role = store.role_catalog_entries.get(shift["role_entry_id"])
    check_age(volunteer, role)
    check_skill(volunteer, role)
    check_training(volunteer, role, now)


# ------------------------------------------------------------------
# Hour-log computations
# ------------------------------------------------------------------

def compute_hour_log_fields(checked_in_at, checked_out_at, break_minutes):
    from util import parse_dt
    from decimal import Decimal
    ci = parse_dt(checked_in_at)
    co = parse_dt(checked_out_at)
    elapsed = int((co - ci).total_seconds() // 60)
    raw = max(0, elapsed - int(break_minutes))
    claimed = round_half_up(Decimal(raw) / Decimal(60), 2)
    quarters = round_half_up(Decimal(raw) / Decimal(15), 0)
    credited = quarters * Decimal("0.25")
    return raw, claimed, credited


# ------------------------------------------------------------------
# Serializers
# ------------------------------------------------------------------

def serialize_event(ev):
    return {
        "id": ev["id"],
        "name": ev["name"],
        "event_start_at": ev["event_start_at"],
        "event_end_at": ev["event_end_at"],
        "early_access_opens_at": ev["early_access_opens_at"],
        "signup_opens_at": ev["signup_opens_at"],
        "signup_closes_at": ev["signup_closes_at"],
        "status": ev["status"],
        "created_at": ev["created_at"],
        "updated_at": ev["updated_at"],
        "version": ev["version"],
    }


def serialize_segment(seg):
    return {
        "id": seg["id"],
        "event_id": seg["event_id"],
        "segment_code": seg["segment_code"],
        "mile_start": seg["mile_start"],
        "mile_end": seg["mile_end"],
        "terrain_type": seg["terrain_type"],
        "created_at": seg["created_at"],
        "updated_at": seg["updated_at"],
        "version": seg["version"],
    }


def serialize_role(role):
    return {
        "id": role["id"],
        "event_id": role["event_id"],
        "role_code": role["role_code"],
        "title": role["title"],
        "min_age_years": role["min_age_years"],
        "required_skill": role["required_skill"],
        "required_training_module": role["required_training_module"],
        "credit_weight": role["credit_weight"],
        "status": role["status"],
        "created_at": role["created_at"],
        "updated_at": role["updated_at"],
        "version": role["version"],
    }


def serialize_shift(shift):
    shift["confirmed_count"] = confirmed_count(shift["id"])
    shift["checked_in_count"] = checked_in_count(shift["id"])
    return {
        "id": shift["id"],
        "event_id": shift["event_id"],
        "role_entry_id": shift["role_entry_id"],
        "segment_id": shift["segment_id"],
        "start_at": shift["start_at"],
        "end_at": shift["end_at"],
        "required_headcount": shift["required_headcount"],
        "confirmed_count": shift["confirmed_count"],
        "checked_in_count": shift["checked_in_count"],
        "understaffed_alert": shift["understaffed_alert"],
        "status": shift["status"],
        "created_at": shift["created_at"],
        "updated_at": shift["updated_at"],
        "version": shift["version"],
    }


def serialize_group(grp):
    return {
        "id": grp["id"],
        "event_id": grp["event_id"],
        "name": grp["name"],
        "charity_code": grp["charity_code"],
        "status": grp["status"],
        "created_at": grp["created_at"],
        "updated_at": grp["updated_at"],
        "version": grp["version"],
    }


def serialize_volunteer(vol):
    return {
        "id": vol["id"],
        "event_id": vol["event_id"],
        "group_id": vol["group_id"],
        "full_name": vol["full_name"],
        "date_of_birth": vol["date_of_birth"],
        "skill_tags": vol["skill_tags"],
        "float_opt_in": vol["float_opt_in"],
        "is_returning": vol["is_returning"],
        "status": vol["status"],
        "age_years_on_event": vol["age_years_on_event"],
        "no_show_strikes": vol["no_show_strikes"],
        "created_at": vol["created_at"],
        "updated_at": vol["updated_at"],
        "version": vol["version"],
    }


def serialize_training(tr):
    return {
        "id": tr["id"],
        "event_id": tr["event_id"],
        "volunteer_id": tr["volunteer_id"],
        "module_code": tr["module_code"],
        "status": tr["status"],
        "passed_at": tr["passed_at"],
        "valid_until": tr["valid_until"],
        "attempt_count": tr["attempt_count"],
        "created_at": tr["created_at"],
        "updated_at": tr["updated_at"],
        "version": tr["version"],
    }


def serialize_signup(su):
    return {
        "id": su["id"],
        "event_id": su["event_id"],
        "volunteer_id": su["volunteer_id"],
        "shift_id": su["shift_id"],
        "status": su["status"],
        "origin": su["origin"],
        "replaces_signup_id": su["replaces_signup_id"],
        "is_captain": su["is_captain"],
        "requested_at": su["requested_at"],
        "approved_at": su["approved_at"],
        "confirm_by_at": su["confirm_by_at"],
        "confirmed_at": su["confirmed_at"],
        "checked_in_at": su["checked_in_at"],
        "checked_out_at": su["checked_out_at"],
        "created_at": su["created_at"],
        "updated_at": su["updated_at"],
        "version": su["version"],
    }


def serialize_inventory(inv):
    return {
        "id": inv["id"],
        "event_id": inv["event_id"],
        "item_code": inv["item_code"],
        "description": inv["description"],
        "quantity_total": inv["quantity_total"],
        "quantity_issued": inventory_issued_count(inv["id"]),
        "created_at": inv["created_at"],
        "updated_at": inv["updated_at"],
        "version": inv["version"],
    }


def serialize_distribution(dr):
    return {
        "id": dr["id"],
        "event_id": dr["event_id"],
        "signup_id": dr["signup_id"],
        "inventory_id": dr["inventory_id"],
        "kind": dr["kind"],
        "status": dr["status"],
        "issued_at": dr["issued_at"],
        "returned_at": dr["returned_at"],
        "created_at": dr["created_at"],
        "updated_at": dr["updated_at"],
        "version": dr["version"],
    }


def serialize_hour_log(log):
    return {
        "id": log["id"],
        "event_id": log["event_id"],
        "signup_id": log["signup_id"],
        "status": log["status"],
        "break_minutes": log["break_minutes"],
        "raw_minutes": log["raw_minutes"],
        "claimed_hours": dec_to_number(log["claimed_hours"]),
        "credited_hours": dec_to_number(log["credited_hours"]),
        "verified_by_role": log["verified_by_role"],
        "created_at": log["created_at"],
        "updated_at": log["updated_at"],
        "version": log["version"],
    }


def serialize_debrief(deb):
    return {
        "id": deb["id"],
        "event_id": deb["event_id"],
        "shift_id": deb["shift_id"],
        "author_volunteer_id": deb["author_volunteer_id"],
        "headcount_actual": deb["headcount_actual"],
        "role_effectiveness_rating": deb["role_effectiveness_rating"],
        "supply_shortage_flag": deb["supply_shortage_flag"],
        "notes": deb["notes"],
        "status": deb["status"],
        "created_at": deb["created_at"],
        "updated_at": deb["updated_at"],
        "version": deb["version"],
    }


def serialize_adjustment(adj):
    return {
        "id": adj["id"],
        "event_id": adj["event_id"],
        "role_entry_id": adj["role_entry_id"],
        "debrief_report_id": adj["debrief_report_id"],
        "proposed_min_age_years": adj["proposed_min_age_years"],
        "proposed_required_skill": adj["proposed_required_skill"],
        "proposed_credit_weight": adj["proposed_credit_weight"],
        "proposed_retire": adj["proposed_retire"],
        "status": adj["status"],
        "applied_at": adj["applied_at"],
        "created_at": adj["created_at"],
        "updated_at": adj["updated_at"],
        "version": adj["version"],
    }


def paginate(items, request_args):
    """Apply limit/offset per scaffold pagination defaults. Returns (page, limit, offset, total)."""
    raw_limit = request_args.get("limit")
    raw_offset = request_args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise errors.invalid_request("limit must be an integer.")
        if limit < 1 or limit > 100:
            raise errors.invalid_request("limit must be between 1 and 100.")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise errors.invalid_request("offset must be an integer.")
        if offset < 0:
            raise errors.invalid_request("offset must be >= 0.")
    total = len(items)
    return items[offset:offset + limit], limit, offset, total


def sort_by_created(records):
    return sorted(records, key=lambda r: (r["created_at"], r["id"]))
