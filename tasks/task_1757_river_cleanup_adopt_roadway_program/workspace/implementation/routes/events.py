"""CleanupEvent endpoints (PRD 3.3, 3.5, 3.6): scheduling, briefing, postpone,
cancel, debris reporting with the completion cascade, and supply issuance."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from db import db, next_seq
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_EVENT_NOT_FOUND,
    ERR_AGREEMENT_NOT_FOUND,
    ERR_DEPOT_NOT_FOUND,
    ERR_WAIVER_NOT_FOUND,
    ERR_AGREEMENT_NOT_ACTIVE,
    ERR_EVENT_NOT_SCHEDULED,
    ERR_EVENT_TERMINAL,
    ERR_EVENT_NOT_BRIEFED,
    ERR_HAZARD_UNRESOLVED,
    ERR_WAIVER_INVALID_ATTENDEE,
    ERR_SUPERVISOR_ABSENT,
    ERR_EVENT_TOO_SOON,
    ERR_REPORT_WINDOW_CLOSED,
    ERR_EVENT_WINDOW_OVERLAP,
    ERR_WEIGHT_MISMATCH,
    ERR_SUPPLY_ALREADY_ISSUED,
    ERR_SUPPLY_STOCK_EXCEEDED,
)
from middleware import get_caller, check_role, check_ownership, COORD, LEADER
from response import success_object
from routes.helpers import list_response, event_owner_group_id
from services.compliance import recompute_standing
from services.core import (
    stamp_new, touch, public, cancel_event_cascade, distribution_for_event,
)
from util import CLOCK, new_id, parse_date, dec, round_half_up, ceil_div
from validate import (
    get_body, req_str, req_int, opt_int, req_enum, ref_id, require_resource,
    parse_iso_date,
)

bp = Blueprint("events", __name__)

EVENT_LEAD_DAYS = 14
REPORT_WINDOW_DAYS = 30
LIVE_EVENT_STATUSES = ("SCHEDULED", "BRIEFING_DONE", "POSTPONED")
TERMINAL_EVENT_STATUSES = ("COMPLETED", "CANCELLED", "NO_SHOW")
MATERIAL_TYPES = ["GENERAL_TRASH", "RECYCLABLES", "METALS", "YARD_WASTE", "OTHER"]
AVG_BAG_WEIGHT_LBS = {
    "GENERAL_TRASH": Decimal("12.75"),
    "RECYCLABLES": Decimal("7.25"),
    "METALS": Decimal("22.4"),
    "YARD_WASTE": Decimal("10.6"),
    "OTHER": Decimal("9.85"),
}
BAGS_PER_VOLUNTEER_MILE = 2
WATER_SURCHARGE = Decimal("1.25")


def _segment_id_of(event):
    ag = db["agreements"].get(event["agreement_id"])
    return ag["segment_id"] if ag else None


def _segment_has_open_hazard(segment_id):
    return any(
        h["segment_id"] == segment_id and h["status"] in ("REPORTED", "ACKNOWLEDGED")
        for h in db["hazards"].values()
    )


def _day_slot_taken(segment_id, scheduled_date, exclude_event_id=None):
    for ev in db["events"].values():
        if ev["id"] == exclude_event_id:
            continue
        if ev["status"] not in LIVE_EVENT_STATUSES:
            continue
        if ev["scheduled_date"] != scheduled_date:
            continue
        if _segment_id_of(ev) == segment_id:
            return True
    return False


@bp.post("/program/events")
def create_event():
    caller = get_caller()
    check_role(caller, [LEADER])
    body = get_body()
    agreement_id = ref_id(body, "agreement_id")
    agreement = None
    if agreement_id is not None:
        agreement = require_resource("agreements", agreement_id, ERR_AGREEMENT_NOT_FOUND)
    if agreement is not None:
        check_ownership(caller, agreement["group_id"])
    if agreement_id is None:
        raise_error(ERR_INVALID_REQUEST, "missing required field: agreement_id")
    sched = parse_iso_date(body.get("scheduled_date"), "scheduled_date").isoformat()
    scheduled_date = parse_date(sched)
    expected_volunteers = req_int(body, "expected_volunteers", minimum=1)
    # family 6: agreement state
    if agreement["status"] != "ACTIVE":
        raise_error(ERR_AGREEMENT_NOT_ACTIVE, "event scheduling requires an ACTIVE agreement")
    # family 7: open hazard on the segment blocks scheduling
    if _segment_has_open_hazard(agreement["segment_id"]):
        raise_error(ERR_HAZARD_UNRESOLVED,
                    "an unresolved hazard report shadows this segment")
    # family 8: scheduling lead time
    today = CLOCK.today()
    if scheduled_date < today + timedelta(days=EVENT_LEAD_DAYS):
        raise_error(ERR_EVENT_TOO_SOON,
                    "scheduled_date must be at least 14 days after the clock date")
    # family 9: one live event per segment per calendar day (half-open day-slot)
    if _day_slot_taken(agreement["segment_id"], sched):
        raise_error(ERR_EVENT_WINDOW_OVERLAP,
                    "another live event already occupies that segment day-slot")
    rec = stamp_new({
        "agreement_id": agreement_id,
        "scheduled_date": sched,
        "expected_volunteers": expected_volunteers,
        "status": "SCHEDULED",
        "briefing_attendee_count": 0,
        "postpone_count": 0,
        "completed_weight_lbs": None,
    })
    db["events"][rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.get("/program/events/<eid>")
def get_event(eid):
    caller = get_caller()
    check_role(caller, [COORD, LEADER])
    rec = require_resource("events", eid, ERR_EVENT_NOT_FOUND)
    check_ownership(caller, event_owner_group_id(rec))
    return success_object(public(rec))


@bp.get("/program/events")
def list_events():
    caller = get_caller()
    check_role(caller, [COORD, LEADER])
    filters = {
        "agreement_id": request.args.get("agreement_id"),
        "status": request.args.get("status"),
    }
    return list_response("events", caller, filters=filters,
                         owner_of=event_owner_group_id)


@bp.patch("/program/events/<eid>")
def edit_event(eid):
    caller = get_caller()
    check_role(caller, [LEADER])
    rec = require_resource("events", eid, ERR_EVENT_NOT_FOUND)
    check_ownership(caller, event_owner_group_id(rec))
    body = get_body()
    new_date = None
    if "scheduled_date" in body and body.get("scheduled_date") is not None:
        new_date = parse_iso_date(body.get("scheduled_date"), "scheduled_date")
    new_volunteers = opt_int(body, "expected_volunteers", None, minimum=1)
    # family 6: PATCH requires SCHEDULED (plain edits) or POSTPONED (reschedule)
    if rec["status"] not in ("SCHEDULED", "POSTPONED"):
        raise_error(ERR_EVENT_TERMINAL, "cannot edit a terminal event")
    if new_date is not None:
        today = CLOCK.today()
        if new_date < today + timedelta(days=EVENT_LEAD_DAYS):
            raise_error(ERR_EVENT_TOO_SOON,
                        "rescheduled date must be at least 14 days after the clock date")
        new_date_str = new_date.isoformat()
        if _day_slot_taken(_segment_id_of(rec), new_date_str, exclude_event_id=rec["id"]):
            raise_error(ERR_EVENT_WINDOW_OVERLAP,
                        "another live event already occupies that segment day-slot")
        rec["scheduled_date"] = new_date_str
        if rec["status"] == "POSTPONED":
            rec["status"] = "SCHEDULED"
    if new_volunteers is not None:
        rec["expected_volunteers"] = new_volunteers
    touch(rec)
    return success_object(public(rec))


@bp.post("/program/events/<eid>/briefing")
def record_briefing(eid):
    caller = get_caller()
    check_role(caller, [LEADER])
    rec = require_resource("events", eid, ERR_EVENT_NOT_FOUND)
    check_ownership(caller, event_owner_group_id(rec))
    body = get_body()
    raw = body.get("attendee_waiver_ids")
    if raw is None or not isinstance(raw, list) or any(not isinstance(x, str) for x in raw):
        raise_error(ERR_INVALID_REQUEST, "attendee_waiver_ids must be an array of strings")
    # family 3: every listed waiver must resolve
    waivers = [require_resource("waivers", wid, ERR_WAIVER_NOT_FOUND) for wid in raw]
    # family 6: the event must be SCHEDULED
    if rec["status"] != "SCHEDULED":
        raise_error(ERR_EVENT_NOT_SCHEDULED, "briefing requires a SCHEDULED event")
    # family 7: attendee validity, then supervisor presence
    today = CLOCK.today()
    if len(waivers) == 0:
        raise_error(ERR_WAIVER_INVALID_ATTENDEE, "attendee_waiver_ids must be non-empty")
    for w in waivers:
        if (w["status"] != "ACTIVE"
                or today > parse_date(w["expiry_date"])
                or w["agreement_id"] != rec["agreement_id"]):
            raise_error(ERR_WAIVER_INVALID_ATTENDEE,
                        "attendee waiver is not ACTIVE, is expired, or belongs to another agreement")
    attendee_ids = set(raw)
    for w in waivers:
        if w["is_minor"] and w.get("supervisor_waiver_id") not in attendee_ids:
            raise_error(ERR_SUPERVISOR_ABSENT,
                        "a minor attendee's supervisor waiver is not among the attendees")
    # family 8: the briefing happens on or before the event day
    if today > parse_date(rec["scheduled_date"]):
        raise_error(ERR_REPORT_WINDOW_CLOSED, "briefing after the scheduled date")
    rec["status"] = "BRIEFING_DONE"
    rec["briefing_attendee_count"] = len(raw)
    touch(rec)
    return success_object(public(rec))


@bp.post("/program/events/<eid>/postpone")
def postpone_event(eid):
    caller = get_caller()
    check_role(caller, [LEADER])
    rec = require_resource("events", eid, ERR_EVENT_NOT_FOUND)
    check_ownership(caller, event_owner_group_id(rec))
    get_body()  # optional reason; not persisted on the entity
    if rec["status"] not in ("SCHEDULED", "BRIEFING_DONE"):
        raise_error(ERR_EVENT_TERMINAL, "cannot postpone a terminal event")
    rec["status"] = "POSTPONED"
    rec["postpone_count"] += 1
    rec["briefing_attendee_count"] = 0  # re-briefing required after reschedule
    touch(rec)
    return success_object(public(rec))


@bp.post("/program/events/<eid>/cancel")
def cancel_event(eid):
    caller = get_caller()
    check_role(caller, [COORD, LEADER])
    rec = require_resource("events", eid, ERR_EVENT_NOT_FOUND)
    check_ownership(caller, event_owner_group_id(rec))
    get_body()
    if rec["status"] not in LIVE_EVENT_STATUSES:
        raise_error(ERR_EVENT_TERMINAL, "cannot cancel a terminal event")
    cancel_event_cascade(rec)
    return success_object(public(rec))


# ---------------------------------------------------------------------------
# Debris reporting (PRD 3.6)
# ---------------------------------------------------------------------------

def _validate_material_lines(body, weight_method):
    lines = body.get("material_lines")
    if not isinstance(lines, list) or len(lines) == 0:
        raise_error(ERR_INVALID_REQUEST, "material_lines must be a non-empty array")
    seen = set()
    for line in lines:
        if not isinstance(line, dict):
            raise_error(ERR_INVALID_REQUEST, "material_lines entries must be objects")
        mt = line.get("material_type")
        if mt not in MATERIAL_TYPES:
            raise_error(ERR_INVALID_REQUEST, f"invalid material_type: {mt}")
        if mt in seen:
            raise_error(ERR_INVALID_REQUEST, f"duplicate material_type: {mt}")
        seen.add(mt)
        if weight_method == "ESTIMATED":
            bc = line.get("bag_count")
            if bc is None or isinstance(bc, bool) or not isinstance(bc, int) or bc < 0:
                raise_error(ERR_INVALID_REQUEST, "bag_count is required (>= 0) under ESTIMATED")
        else:
            lw = line.get("line_weight_lbs")
            if lw is None or isinstance(lw, bool) or not isinstance(lw, (int, float)) or dec(lw) < 0:
                raise_error(ERR_INVALID_REQUEST, "line_weight_lbs is required (>= 0) under MEASURED")
    return lines


@bp.post("/program/events/<eid>/debris-report")
def file_debris_report(eid):
    caller = get_caller()
    check_role(caller, [LEADER])
    rec = require_resource("events", eid, ERR_EVENT_NOT_FOUND)
    check_ownership(caller, event_owner_group_id(rec))
    body = get_body()
    # family 5: shape
    weight_method = req_enum(body, "weight_method", ["MEASURED", "ESTIMATED"])
    measured_total = body.get("measured_total_weight_lbs")
    if weight_method == "MEASURED":
        if measured_total is None or isinstance(measured_total, bool) \
                or not isinstance(measured_total, (int, float)):
            raise_error(ERR_INVALID_REQUEST,
                        "measured_total_weight_lbs is required under MEASURED")
    else:
        if measured_total is not None:
            raise_error(ERR_INVALID_REQUEST,
                        "measured_total_weight_lbs is forbidden under ESTIMATED")
    lines = _validate_material_lines(body, weight_method)
    # family 6: the event must be BRIEFING_DONE (also enforces one report per event)
    if rec["status"] != "BRIEFING_DONE":
        raise_error(ERR_EVENT_NOT_BRIEFED, "debris report requires a BRIEFING_DONE event")
    # family 8: report window [scheduled_date, scheduled_date + 30 days], inclusive
    today = CLOCK.today()
    sched = parse_date(rec["scheduled_date"])
    if not (sched <= today <= sched + timedelta(days=REPORT_WINDOW_DAYS)):
        raise_error(ERR_REPORT_WINDOW_CLOSED,
                    "clock date is outside [scheduled_date, scheduled_date + 30 days]")
    # per-line rounding precedes summation (order pinned, PRD 2.10/3.6)
    breakdown = []
    if weight_method == "ESTIMATED":
        official = Decimal("0")
        for line in lines:
            lw = round_half_up(dec(line["bag_count"]) * AVG_BAG_WEIGHT_LBS[line["material_type"]], 1)
            breakdown.append({"material_type": line["material_type"],
                              "line_weight_lbs": float(lw)})
            official += lw
        official_f = float(round_half_up(official, 1))
        stored_total = None
    else:
        line_sum = Decimal("0")
        for line in lines:
            lw = round_half_up(dec(line["line_weight_lbs"]), 1)
            breakdown.append({"material_type": line["material_type"],
                              "line_weight_lbs": float(lw)})
            line_sum += lw
        total_dec = round_half_up(dec(measured_total), 1)
        # family 9: lines must reconcile to the scale reading exactly at 1dp
        if line_sum != total_dec:
            raise_error(ERR_WEIGHT_MISMATCH,
                        "material line weights do not sum to measured_total_weight_lbs")
        official_f = float(total_dec)
        stored_total = float(total_dec)
    report = {
        "id": new_id(),
        "created_at": CLOCK.now_iso(),
        "_seq": next_seq(),
        "event_id": rec["id"],
        "weight_method": weight_method,
        "measured_total_weight_lbs": stored_total,
        "material_lines": lines,
        "material_breakdown": breakdown,
        "official_weight_lbs": official_f,
    }
    db["debris_reports"][report["id"]] = report
    # completion cascade link 1: event completes with the denormalized weight
    rec["status"] = "COMPLETED"
    rec["completed_weight_lbs"] = official_f
    touch(rec)
    # link 2: recompute the parent agreement's rolling counter and standing
    agreement = db["agreements"].get(rec["agreement_id"])
    if agreement is not None:
        new_standing = recompute_standing(agreement, today)
        # link 3: automatic reinstatement of a SUSPENDED agreement now COMPLIANT
        if agreement["status"] == "SUSPENDED" and new_standing == "COMPLIANT":
            agreement["status"] = "ACTIVE"
            agreement["suspension_reason"] = None
            touch(agreement)
    return success_object(public(report), status=201)


@bp.get("/program/events/<eid>/debris-reports")
def list_debris_reports(eid):
    caller = get_caller()
    check_role(caller, [COORD, LEADER])
    rec = require_resource("events", eid, ERR_EVENT_NOT_FOUND)
    check_ownership(caller, event_owner_group_id(rec))
    items = [r for r in db["debris_reports"].values() if r["event_id"] == rec["id"]]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    from routes.helpers import get_pagination
    from response import success_list
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Supply issuance (PRD 3.5; calculations.supply_allocation)
# ---------------------------------------------------------------------------

def _ceil_decimal(d: Decimal) -> int:
    from decimal import ROUND_CEILING
    return int(d.to_integral_value(rounding=ROUND_CEILING))


@bp.post("/program/events/<eid>/supplies")
def issue_supplies(eid):
    caller = get_caller()
    check_role(caller, [LEADER])
    rec = require_resource("events", eid, ERR_EVENT_NOT_FOUND)
    check_ownership(caller, event_owner_group_id(rec))
    body = get_body()
    depot_id = ref_id(body, "depot_id")
    depot = None
    if depot_id is not None:
        depot = require_resource("depots", depot_id, ERR_DEPOT_NOT_FOUND)
    if depot_id is None:
        raise_error(ERR_INVALID_REQUEST, "missing required field: depot_id")
    # family 6: non-terminal event, then ACTIVE agreement
    if rec["status"] in TERMINAL_EVENT_STATUSES:
        raise_error(ERR_EVENT_TERMINAL, "cannot issue supplies for a terminal event")
    agreement = db["agreements"].get(rec["agreement_id"])
    if agreement is None or agreement["status"] != "ACTIVE":
        raise_error(ERR_AGREEMENT_NOT_ACTIVE, "supply issuance requires an ACTIVE agreement")
    # family 9: exactly one distribution per event
    if distribution_for_event(rec["id"]) is not None:
        raise_error(ERR_SUPPLY_ALREADY_ISSUED, "event already has a supply distribution")
    segment = db["segments"].get(agreement["segment_id"])
    volunteers = rec["expected_volunteers"]
    vests = volunteers
    grabbers = ceil_div(volunteers, 2)
    base_bags = _ceil_decimal(dec(volunteers) * BAGS_PER_VOLUNTEER_MILE * dec(segment["mile_length"]))
    if segment["water_adjacent"]:
        bags = _ceil_decimal(dec(base_bags) * WATER_SURCHARGE)
    else:
        bags = base_bags
    # family 10 (evaluated last): every computed line must fit depot on-hand
    if (bags > depot["bags_on_hand"] or vests > depot["vests_on_hand"]
            or grabbers > depot["grabbers_on_hand"]):
        raise_error(ERR_SUPPLY_STOCK_EXCEEDED,
                    "computed allocation exceeds depot on-hand stock")
    dist = stamp_new({
        "event_id": rec["id"],
        "depot_id": depot_id,
        "status": "ISSUED",
        "vests_issued": vests,
        "grabbers_issued": grabbers,
        "bags_issued": bags,
        "vests_returned": 0,
        "grabbers_returned": 0,
        "lost_vests": 0,
        "lost_grabbers": 0,
    })
    db["supplies"][dist["id"]] = dist
    depot["bags_on_hand"] -= bags
    depot["vests_on_hand"] -= vests
    depot["grabbers_on_hand"] -= grabbers
    touch(depot)
    return success_object(public(dist), status=201)
