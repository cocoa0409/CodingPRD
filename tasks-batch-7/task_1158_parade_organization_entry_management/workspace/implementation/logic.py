"""Domain logic: derived fields, calculations, state-transition cascades,
not-found resolvers, and serializers."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from db import STORE, touch
from errors import api_err
from util import fmt_ts

AGENCIES = ("POLICE", "FIRE", "TRANSIT", "SANITATION")
ENTRY_CATEGORIES = ("FLOAT", "BAND", "WALKING_GROUP", "VEHICLE", "EQUESTRIAN")
BASE_CENTS = {
    "FLOAT": 50000,
    "BAND": 30000,
    "WALKING_GROUP": 15000,
    "VEHICLE": 40000,
    "EQUESTRIAN": 35000,
}
TIER_MIN_SECONDS = {"GOLD": 120, "SILVER": 60, "BRONZE": 30}
ITEM_TYPES = ("SPONSOR_READ", "ENTRY_INTRO", "SAFETY_ANNOUNCEMENT", "AWARD_ANNOUNCEMENT")
AWARD_CATEGORIES = ("BEST_FLOAT", "BEST_BAND", "BEST_WALKING", "GRAND_PRIZE")
ELIGIBLE_CATEGORIES = ENTRY_CATEGORIES + ("ANY",)
VEHICLE_CLASSES = ("SELF_PROPELLED", "TOWED", "PUSHED")
FUEL_TYPES = ("GASOLINE", "DIESEL", "ELECTRIC", "NONE")
SPONSOR_TIERS = ("GOLD", "SILVER", "BRONZE")

LIVE_LINEUP_STATUSES = ("TENTATIVE", "CONFIRMED", "CHECKED_IN")
TERMINAL_LINEUP_STATUSES = ("RELEASED", "PULLED", "NO_SHOW")


# ---------------------------------------------------------------------------
# Not-found resolvers (validated left to right along the path)
# ---------------------------------------------------------------------------

def _get(coll, rid, error_id, label):
    rec = coll.get(rid)
    if rec is None:
        raise api_err(error_id, f"No {label} with the given id")
    return rec


def parade_or_404(rid):
    return _get(STORE.parades, rid, "ERR_PARADE_NOT_FOUND", "ParadeEvent")


def permit_or_404(rid):
    return _get(STORE.permits, rid, "ERR_PERMIT_NOT_FOUND", "PermitApplication")


def endorsement_or_404(rid):
    return _get(STORE.endorsements, rid, "ERR_ENDORSEMENT_NOT_FOUND", "AgencyEndorsement")


def entry_or_404(rid):
    return _get(STORE.entries, rid, "ERR_ENTRY_NOT_FOUND", "EntryApplication")


def float_or_404(rid):
    return _get(STORE.floats, rid, "ERR_FLOAT_NOT_FOUND", "Float")


def inspection_or_404(rid):
    return _get(STORE.inspections, rid, "ERR_INSPECTION_NOT_FOUND", "SafetyInspection")


def staging_or_404(rid):
    return _get(STORE.staging_areas, rid, "ERR_STAGING_AREA_NOT_FOUND", "StagingArea")


def segment_or_404(rid):
    return _get(STORE.route_segments, rid, "ERR_ROUTE_SEGMENT_NOT_FOUND", "RouteSegment")


def lineup_or_404(rid):
    return _get(STORE.lineup_assignments, rid, "ERR_LINEUP_ASSIGNMENT_NOT_FOUND", "LineupAssignment")


def marshal_or_404(rid):
    return _get(STORE.marshal_assignments, rid, "ERR_MARSHAL_ASSIGNMENT_NOT_FOUND", "MarshalAssignment")


def sheet_or_404(rid):
    return _get(STORE.score_sheets, rid, "ERR_SCORE_SHEET_NOT_FOUND", "JudgingScoreSheet")


def award_or_404(rid):
    return _get(STORE.awards, rid, "ERR_AWARD_NOT_FOUND", "Award")


def sponsor_or_404(rid):
    return _get(STORE.sponsors, rid, "ERR_SPONSOR_NOT_FOUND", "SponsorPackage")


def script_item_or_404(rid):
    return _get(STORE.script_items, rid, "ERR_SCRIPT_ITEM_NOT_FOUND", "AnnouncerScriptItem")


def plan_or_404(rid):
    return _get(STORE.dispersal_plans, rid, "ERR_DISPERSAL_PLAN_NOT_FOUND", "DispersalPlan")


# ---------------------------------------------------------------------------
# Derived fields (immediate consistency: computed from source data on read)
# ---------------------------------------------------------------------------

def permit_of(parade_id):
    for p in STORE.permits.values():
        if p["parade_id"] == parade_id:
            return p
    return None


def plan_of(parade_id):
    for d in STORE.dispersal_plans.values():
        if d["parade_id"] == parade_id:
            return d
    return None


def parade_posture(parade):
    if parade["status"] == "CANCELLED":
        return "FROZEN"
    permit = permit_of(parade["id"])
    if permit is not None and permit["status"] in ("DENIED", "REVOKED"):
        return "FROZEN"
    plan = plan_of(parade["id"])
    if (
        permit is not None
        and permit["status"] == "GRANTED"
        and plan is not None
        and plan["status"] == "APPROVED"
        and parade["status"] in ("PERMIT_GRANTED", "LOCKED", "LINEUP_PUBLISHED")
    ):
        return "OPERATIONAL"
    return "RESTRICTED"


def approved_entry_count(parade_id):
    return sum(
        1
        for e in STORE.entries.values()
        if e["parade_id"] == parade_id and e["status"] == "APPROVED"
    )


def sponsor_seconds_allocated(parade_id):
    return sum(
        it["duration_seconds"]
        for it in STORE.script_items.values()
        if it["parade_id"] == parade_id
        and it["item_type"] == "SPONSOR_READ"
        and it["status"] in ("APPROVED", "LOCKED")
    )


def endorsed_count(permit_id):
    return sum(
        1
        for e in STORE.endorsements.values()
        if e["permit_id"] == permit_id and e["status"] == "ENDORSED"
    )


def reserved_slots(staging_area_id):
    return sum(
        1
        for a in STORE.lineup_assignments.values()
        if a["staging_area_id"] == staging_area_id and a["status"] in ("CONFIRMED", "CHECKED_IN")
    )


def allocated_seconds(sponsor_id):
    return sum(
        it["duration_seconds"]
        for it in STORE.script_items.values()
        if it["item_type"] == "SPONSOR_READ"
        and it.get("sponsor_id") == sponsor_id
        and it["status"] in ("APPROVED", "LOCKED")
    )


def _mean2(values):
    q = (Decimal(sum(values)) / Decimal(len(values))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return float(q)


def provisional_score(entry_id):
    totals = [
        s["sheet_total"]
        for s in STORE.score_sheets.values()
        if s["entry_id"] == entry_id and s["status"] in ("SUBMITTED", "FINALIZED")
    ]
    if not totals:
        return None
    return _mean2(totals)


def final_score(entry_id):
    totals = [
        s["sheet_total"]
        for s in STORE.score_sheets.values()
        if s["entry_id"] == entry_id and s["status"] == "FINALIZED"
    ]
    if not totals:
        return None
    if len(totals) >= 3:
        ordered = sorted(totals)
        totals = ordered[1:-1]  # drop one lowest and one highest
    return _mean2(totals)


def finalized_sheet_count(entry_id):
    return sum(
        1
        for s in STORE.score_sheets.values()
        if s["entry_id"] == entry_id and s["status"] == "FINALIZED"
    )


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def compute_entry_fee(entry, parade, submission_instant):
    basis = entry["assigned_category"] or entry["requested_category"]
    subtotal = BASE_CENTS[basis]
    p = entry["estimated_participants"]
    subtotal += min(p, 50) * 300
    subtotal += min(max(p - 50, 0), 150) * 200
    subtotal += max(p - 200, 0) * 100
    late = submission_instant > (parade["entry_deadline"] - timedelta(days=7))
    surcharge = 0
    if late:
        surcharge = int(
            (Decimal(subtotal) * Decimal("0.25")).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
    return subtotal + surcharge


def compute_permit_final_fee(parade, submitted_at):
    base = 30000 + 25000 + 20000 + 15000  # 90000
    expedited = submitted_at > (parade["parade_date"] - timedelta(days=14))
    if expedited:
        surcharge = int(
            (Decimal(base) * Decimal("0.20")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
        return base + surcharge  # 108000
    return base


def compute_duration_seconds(duration_minutes):
    return int(
        (Decimal(str(duration_minutes)) * 60).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def _cancel_entry_intro_items(parade_id, entry_id):
    for it in STORE.script_items.values():
        if (
            it["parade_id"] == parade_id
            and it["item_type"] == "ENTRY_INTRO"
            and it.get("entry_id") == entry_id
            and it["status"] == "APPROVED"
        ):
            it["status"] = "CANCELLED"
            touch(it)


def pull_assignment(assignment):
    """TENTATIVE|CONFIRMED|CHECKED_IN -> PULLED with per-pull side effects."""
    assignment["status"] = "PULLED"
    touch(assignment)
    _cancel_entry_intro_items(assignment["parade_id"], assignment["entry_id"])


def pull_live_assignments_of_entry(entry, statuses=("CONFIRMED", "CHECKED_IN")):
    for a in STORE.lineup_assignments.values():
        if a["entry_id"] == entry["id"] and a["status"] in statuses:
            pull_assignment(a)


def suspend_entry(entry):
    """APPROVED -> SUSPENDED with the lineup-pull cascade."""
    if entry["status"] != "APPROVED":
        return
    entry["status"] = "SUSPENDED"
    touch(entry)
    pull_live_assignments_of_entry(entry)


def certify_compensation(entry):
    """SUSPENDED -> APPROVED compensation when a float re-certifies."""
    if entry["status"] != "SUSPENDED":
        return
    entry["status"] = "APPROVED"
    touch(entry)


def parade_cancel_cascade(parade):
    pid = parade["id"]
    for e in STORE.entries.values():
        if e["parade_id"] == pid and e["status"] in (
            "SUBMITTED",
            "UNDER_REVIEW",
            "REVISION_REQUESTED",
            "APPROVED",
            "SUSPENDED",
        ):
            e["status"] = "WITHDRAWN"
            touch(e)
    for a in STORE.lineup_assignments.values():
        if a["parade_id"] == pid and a["status"] in LIVE_LINEUP_STATUSES:
            pull_assignment(a)
    for s in STORE.sponsors.values():
        if s["parade_id"] == pid and s["status"] == "ACTIVE":
            s["status"] = "DEFAULTED"
            touch(s)


def parade_complete_cascade(parade):
    for s in STORE.sponsors.values():
        if s["parade_id"] == parade["id"] and s["status"] == "ACTIVE":
            if allocated_seconds(s["id"]) >= TIER_MIN_SECONDS[s["tier"]]:
                s["status"] = "FULFILLED"
            else:
                s["status"] = "DEFAULTED"
            touch(s)


def lock_approved_script_items(parade_id):
    for it in STORE.script_items.values():
        if it["parade_id"] == parade_id and it["status"] == "APPROVED":
            it["status"] = "LOCKED"
            touch(it)


# ---------------------------------------------------------------------------
# Serializers (exactly the declared fields)
# ---------------------------------------------------------------------------

def ser_parade(p):
    return {
        "id": p["id"],
        "name": p["name"],
        "parade_date": fmt_ts(p["parade_date"]),
        "entry_deadline": fmt_ts(p["entry_deadline"]),
        "status": p["status"],
        "posture": parade_posture(p),
        "approved_entry_count": approved_entry_count(p["id"]),
        "sponsor_seconds_allocated": sponsor_seconds_allocated(p["id"]),
        "script_finalized": p["script_finalized"],
        "created_at": fmt_ts(p["created_at"]),
        "updated_at": fmt_ts(p["updated_at"]),
        "version": p["version"],
    }


def ser_segment(s):
    return {
        "id": s["id"],
        "parade_id": s["parade_id"],
        "order_index": s["order_index"],
        "name": s["name"],
        "length_meters": s["length_meters"],
        "emergency_lane_width_m": s["emergency_lane_width_m"],
        "segment_window_start": fmt_ts(s["segment_window_start"]),
        "segment_window_end": fmt_ts(s["segment_window_end"]),
        "created_at": fmt_ts(s["created_at"]),
        "updated_at": fmt_ts(s["updated_at"]),
        "version": s["version"],
    }


def ser_permit(p):
    return {
        "id": p["id"],
        "parade_id": p["parade_id"],
        "status": p["status"],
        "provisional_fee_cents": p["provisional_fee_cents"],
        "final_fee_cents": p["final_fee_cents"],
        "submitted_at": fmt_ts(p["submitted_at"]),
        "required_agency_count": p["required_agency_count"],
        "endorsed_count": endorsed_count(p["id"]),
        "created_at": fmt_ts(p["created_at"]),
        "updated_at": fmt_ts(p["updated_at"]),
        "version": p["version"],
    }


def ser_endorsement(e):
    return {
        "id": e["id"],
        "permit_id": e["permit_id"],
        "agency_type": e["agency_type"],
        "status": e["status"],
        "decided_at": fmt_ts(e["decided_at"]),
        "permit_version": e["permit_version"],
        "created_at": fmt_ts(e["created_at"]),
        "updated_at": fmt_ts(e["updated_at"]),
        "version": e["version"],
    }


def ser_entry(e):
    return {
        "id": e["id"],
        "parade_id": e["parade_id"],
        "applicant_user_id": e["applicant_user_id"],
        "org_name": e["org_name"],
        "requested_category": e["requested_category"],
        "assigned_category": e["assigned_category"],
        "estimated_participants": e["estimated_participants"],
        "status": e["status"],
        "revision_count": e["revision_count"],
        "fee_cents": e["fee_cents"],
        "fee_paid": e["fee_paid"],
        "provisional_score": provisional_score(e["id"]),
        "final_score": final_score(e["id"]),
        "created_at": fmt_ts(e["created_at"]),
        "updated_at": fmt_ts(e["updated_at"]),
        "version": e["version"],
    }


def ser_float(f):
    return {
        "id": f["id"],
        "entry_id": f["entry_id"],
        "length_m": f["length_m"],
        "width_m": f["width_m"],
        "height_m": f["height_m"],
        "weight_kg": f["weight_kg"],
        "vehicle_class": f["vehicle_class"],
        "fuel_type": f["fuel_type"],
        "compliance_status": f["compliance_status"],
        "created_at": fmt_ts(f["created_at"]),
        "updated_at": fmt_ts(f["updated_at"]),
        "version": f["version"],
    }


def ser_inspection(i):
    return {
        "id": i["id"],
        "float_id": i["float_id"],
        "inspector_user_id": i["inspector_user_id"],
        "scheduled_at": fmt_ts(i["scheduled_at"]),
        "status": i["status"],
        "checklist_score": i["checklist_score"],
        "decided_at": fmt_ts(i["decided_at"]),
        "created_at": fmt_ts(i["created_at"]),
        "updated_at": fmt_ts(i["updated_at"]),
        "version": i["version"],
    }


def ser_staging(s):
    return {
        "id": s["id"],
        "parade_id": s["parade_id"],
        "name": s["name"],
        "capacity": s["capacity"],
        "open_time": fmt_ts(s["open_time"]),
        "close_time": fmt_ts(s["close_time"]),
        "reserved_slots": reserved_slots(s["id"]),
        "created_at": fmt_ts(s["created_at"]),
        "updated_at": fmt_ts(s["updated_at"]),
        "version": s["version"],
    }


def ser_lineup(a):
    return {
        "id": a["id"],
        "parade_id": a["parade_id"],
        "entry_id": a["entry_id"],
        "staging_area_id": a["staging_area_id"],
        "position_number": a["position_number"],
        "arrive_at": fmt_ts(a["arrive_at"]),
        "depart_at": fmt_ts(a["depart_at"]),
        "status": a["status"],
        "created_at": fmt_ts(a["created_at"]),
        "updated_at": fmt_ts(a["updated_at"]),
        "version": a["version"],
    }


def ser_marshal(m):
    return {
        "id": m["id"],
        "parade_id": m["parade_id"],
        "route_segment_id": m["route_segment_id"],
        "marshal_user_id": m["marshal_user_id"],
        "shift_start": fmt_ts(m["shift_start"]),
        "shift_end": fmt_ts(m["shift_end"]),
        "status": m["status"],
        "created_at": fmt_ts(m["created_at"]),
        "updated_at": fmt_ts(m["updated_at"]),
        "version": m["version"],
    }


def ser_sheet(s):
    return {
        "id": s["id"],
        "entry_id": s["entry_id"],
        "judge_user_id": s["judge_user_id"],
        "creativity": s["creativity"],
        "craftsmanship": s["craftsmanship"],
        "theme": s["theme"],
        "crowd_appeal": s["crowd_appeal"],
        "sheet_total": s["sheet_total"],
        "status": s["status"],
        "created_at": fmt_ts(s["created_at"]),
        "updated_at": fmt_ts(s["updated_at"]),
        "version": s["version"],
    }


def ser_award(a):
    return {
        "id": a["id"],
        "parade_id": a["parade_id"],
        "award_category": a["award_category"],
        "eligible_entry_category": a["eligible_entry_category"],
        "winner_entry_id": a["winner_entry_id"],
        "status": a["status"],
        "announced_at": fmt_ts(a["announced_at"]),
        "created_at": fmt_ts(a["created_at"]),
        "updated_at": fmt_ts(a["updated_at"]),
        "version": a["version"],
    }


def ser_sponsor(s):
    return {
        "id": s["id"],
        "parade_id": s["parade_id"],
        "sponsor_name": s["sponsor_name"],
        "tier": s["tier"],
        "contribution_cents": s["contribution_cents"],
        "status": s["status"],
        "allocated_seconds": allocated_seconds(s["id"]),
        "created_at": fmt_ts(s["created_at"]),
        "updated_at": fmt_ts(s["updated_at"]),
        "version": s["version"],
    }


def ser_script_item(it):
    return {
        "id": it["id"],
        "parade_id": it["parade_id"],
        "item_type": it["item_type"],
        "sponsor_id": it.get("sponsor_id"),
        "entry_id": it.get("entry_id"),
        "sequence_index": it["sequence_index"],
        "duration_minutes": it["duration_minutes"],
        "duration_seconds": it["duration_seconds"],
        "status": it["status"],
        "created_at": fmt_ts(it["created_at"]),
        "updated_at": fmt_ts(it["updated_at"]),
        "version": it["version"],
    }


def ser_plan(d):
    return {
        "id": d["id"],
        "parade_id": d["parade_id"],
        "emergency_lane_width_m": d["emergency_lane_width_m"],
        "dispersal_corridors": d["dispersal_corridors"],
        "evacuation_notes": d.get("evacuation_notes"),
        "status": d["status"],
        "created_at": fmt_ts(d["created_at"]),
        "updated_at": fmt_ts(d["updated_at"]),
        "version": d["version"],
    }


def ensure_not_frozen(parade):
    if parade_posture(parade) == "FROZEN":
        raise api_err("ERR_EVENT_FROZEN", "ParadeEvent posture is FROZEN")
