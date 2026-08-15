"""Core domain services: computed fields, calculations, shared helpers.

Every behavior here traces to a PRD sentence. All temporal evaluation uses the
server-side logical clock (db.now()).
"""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db, parse_iso, iso_ms
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_NOT_FOUND,
)

# ---------------------------------------------------------------------------
# Calculation constants (SCAFFOLD Table 1.3)
# ---------------------------------------------------------------------------
BASE_PREP_MINUTES = 120
PER_CUSTOMER_MINUTES = 2
CUSTOMER_CAP = 5000
SWITCHING_OVERHEAD_MINUTES = 45
CAUSE_FACTOR = {
    "TREE": Decimal("1.5"),
    "LIGHTNING": Decimal("1.2"),
    "EQUIPMENT": Decimal("1.0"),
    "VEHICLE": Decimal("1.3"),
    "UNKNOWN": Decimal("1.4"),
}

MAX_SINGLE_EXTENSION_MINUTES = 360
PUBLIC_LOCK_MINUTES = 30
REWORK_EXTENSION_MINUTES = 180

CLUSTER_WINDOW_MINUTES = 60

LIFE_SUPPORT_BONUS = 10000
CRITICAL_FACILITY_BONUS = 4000
CUSTOMER_SCORE_CAP = 10000
AGE_HOURLY_POINTS = 50
MISSED_ETR_BONUS = 2000

MAX_CONTINUOUS_WORK_MINUTES = 960
DEFAULT_ESTIMATE_MINUTES = 120

EARLY_EXIT_PENALTY_PCT = Decimal("0.25")
LODGING_TAX_PCT = Decimal("0.07")
ELIGIBILITY_HOURS = 96

# Enum value sets
EVENT_TYPES = {"THUNDERSTORM", "HURRICANE", "ICE_STORM", "WILDFIRE_PSPS", "TORNADO"}
PRIORITY_CLASSES = {"LIFE_SUPPORT", "CRITICAL_FACILITY"}
SIGNAL_TYPES = {"METER_LAST_GASP", "CUSTOMER_CALL", "SCADA_TRIP", "METER_RESTORE_PING"}
CAUSE_CODES = {"TREE", "LIGHTNING", "EQUIPMENT", "VEHICLE", "UNKNOWN"}
REVISION_REASONS = {"INITIAL", "DAMAGE_FOUND", "CREW_DELAYED", "NESTED_DISCOVERED",
                    "WEATHER_DELAY", "CORRECTION", "VERIFICATION_FAILED"}
DAMAGE_CLASSES = {"MINOR", "MAJOR", "CATASTROPHIC"}
CREW_TYPES = {"LINE", "TREE", "DAMAGE_ASSESSOR", "SUBSTATION"}
WORK_TYPES = {"ASSESSMENT", "REPAIR", "REPLACE_POLE", "REPLACE_TRANSFORMER", "SWITCHING"}
VERIFY_OUTCOMES = {"PASSED", "FAILED"}
DEPARTURE_REASONS = {"COMPLETED", "EARLY_RELEASE"}
CAPITAL_WORK_TYPES = {"REPLACE_POLE", "REPLACE_TRANSFORMER"}

TERMINAL_OUTAGE = {"VERIFIED", "CANCELLED"}


# ---------------------------------------------------------------------------
# Body validation helpers
# ---------------------------------------------------------------------------
def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def req_string(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v == "":
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' is required and must be a non-empty string")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None or v not in allowed:
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' must be one of {sorted(allowed)}")
    return v


def req_int(body, field, minimum=None):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' is required and must be an integer")
    if minimum is not None and v < minimum:
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' must be >= {minimum}")
    return v


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' is required and must be a boolean")
    return v


def req_datetime(body, field):
    raw = body.get(field)
    if raw is None:
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' is required")
    dt = parse_iso(raw)
    if dt is None:
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' must be an ISO 8601 datetime")
    return dt


def opt_int(body, field, minimum=None, default=None):
    v = body.get(field)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' must be an integer")
    if minimum is not None and v < minimum:
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' must be >= {minimum}")
    return v


def parse_pagination(args):
    """Parse limit/offset query params with defaults limit=10, min 1, max 100, offset 0."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_err(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(items):
    from flask import request
    limit, offset = parse_pagination(request.args)
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


# ---------------------------------------------------------------------------
# Entity lookup helpers
# ---------------------------------------------------------------------------
def _lookup(table, entity_id, label):
    obj = table.get(entity_id)
    if obj is None:
        raise_err(ERR_NOT_FOUND, f"{label} {entity_id} not found")
    return obj


def get_event(eid):
    return _lookup(db.storm_events, eid, "StormEvent")


def get_feeder(fid):
    return _lookup(db.feeders, fid, "Feeder")


def get_priority_customer(pid):
    return _lookup(db.priority_customers, pid, "PriorityCustomer")


def get_signal(sid):
    return _lookup(db.trouble_signals, sid, "TroubleSignal")


def get_outage(oid):
    return _lookup(db.outages, oid, "Outage")


def get_assessment(aid):
    return _lookup(db.damage_assessments, aid, "DamageAssessment")


def get_crew(cid):
    return _lookup(db.crews, cid, "Crew")


def get_ma_crew(mid):
    return _lookup(db.mutual_aid_crews, mid, "MutualAidCrew")


def get_block(bid):
    return _lookup(db.lodging_blocks, bid, "LodgingBlock")


def get_work_order(wid):
    return _lookup(db.work_orders, wid, "WorkOrder")


def get_switching_order(sid):
    return _lookup(db.switching_orders, sid, "SwitchingOrder")


def get_stock(sid):
    return _lookup(db.material_stocks, sid, "MaterialStock")


def get_requisition(rid):
    return _lookup(db.material_requisitions, rid, "MaterialRequisition")


def get_ledger_entry(eid):
    return _lookup(db.cost_ledger_entries, eid, "CostLedgerEntry")


def get_claim(cid):
    return _lookup(db.fema_claims, cid, "FemaClaim")


# ---------------------------------------------------------------------------
# Mutation bookkeeping: version / updated_at
# ---------------------------------------------------------------------------
def bump(obj):
    """Increment version and refresh updated_at (logical clock).

    Append-style records (trouble signals, ETR revisions, cost ledger entries)
    carry only id and created_at, so they never call this.
    """
    obj["version"] += 1
    obj["updated_at"] = iso_ms(db.now())


def new_common():
    """Fresh common fields for a full record (id/created_at/updated_at/version)."""
    return {
        "id": db.new_id(),
        "created_at": iso_ms(db.now()),
        "updated_at": iso_ms(db.now()),
        "version": 1,
        "_mono": db.next_mono(),
    }


def new_append():
    """Fresh fields for an append-style record (id/created_at only)."""
    return {
        "id": db.new_id(),
        "created_at": iso_ms(db.now()),
        "_mono": db.next_mono(),
    }


# ---------------------------------------------------------------------------
# Computed fields — reconciled on read (never stale)
# ---------------------------------------------------------------------------
def feeder_certified_count(feeder_id):
    return sum(
        1 for pc in db.priority_customers.values()
        if pc["feeder_id"] == feeder_id and pc["certification_status"] == "CERTIFIED"
    )


def feeder_has_certified(feeder_id, cls=None):
    for pc in db.priority_customers.values():
        if pc["feeder_id"] == feeder_id and pc["certification_status"] == "CERTIFIED":
            if cls is None or pc["priority_class"] == cls:
                return True
    return False


def outage_etr_missed(outage):
    etr = outage.get("current_etr")
    if etr is None:
        return False
    return db.now() > parse_iso(etr)


def outage_priority_score(outage):
    feeder_id = outage["feeder_id"]
    score = 0
    if feeder_has_certified(feeder_id, "LIFE_SUPPORT"):
        score += LIFE_SUPPORT_BONUS
    if feeder_has_certified(feeder_id, "CRITICAL_FACILITY"):
        score += CRITICAL_FACILITY_BONUS
    ca = outage.get("customers_affected")
    if ca is not None:
        score += min(ca, CUSTOMER_SCORE_CAP)
    confirmed_at = outage.get("confirmed_at")
    if confirmed_at is not None:
        delta = db.now() - parse_iso(confirmed_at)
        hours = int(delta.total_seconds() // 3600)
        if hours > 0:
            score += hours * AGE_HOURLY_POINTS
    if outage_etr_missed(outage):
        score += MISSED_ETR_BONUS
    return score


def recompute_outage_scores_for_feeder(feeder_id):
    """Sweep-side recomputation hook: scores are derived on read, so nothing is
    persisted here — reading any outage on this feeder will reflect the change.
    This function exists to pin the PRD-mandated reconciliation point."""
    for o in db.outages.values():
        if o["feeder_id"] == feeder_id and o["outage_status"] not in TERMINAL_OUTAGE:
            # touch recomputation point; values are derived at serialization
            pass


def crew_worked_minutes(crew):
    """worked_minutes_this_shift: sum over completed WOs since shift_started_at
    of (completed_at - arrived_at) minutes, plus (now - arrived_at) if the crew
    is currently ON_SITE on an IN_PROGRESS work order."""
    total = 0
    shift_start = crew.get("shift_started_at")
    for wo in db.work_orders.values():
        if wo.get("assigned_crew_id") != crew["id"]:
            continue
        if wo.get("arrived_at") is None:
            continue
        if wo["execution_status"] == "COMPLETED" and wo.get("completed_at") is not None:
            arr = parse_iso(wo["arrived_at"])
            comp = parse_iso(wo["completed_at"])
            if shift_start is None or arr >= parse_iso(shift_start):
                total += int((comp - arr).total_seconds() // 60)
        elif wo["execution_status"] == "IN_PROGRESS" and crew["crew_status"] == "ON_SITE":
            arr = parse_iso(wo["arrived_at"])
            if shift_start is None or arr >= parse_iso(shift_start):
                total += int((db.now() - arr).total_seconds() // 60)
    return total


def stock_reserved(stock_id):
    return sum(
        r["quantity"] for r in db.material_requisitions.values()
        if r["material_stock_id"] == stock_id and r["requisition_status"] == "STAGED"
    )


def block_rooms_allocated(block_id):
    return sum(
        c["roster_size"] for c in db.mutual_aid_crews.values()
        if c.get("lodging_block_id") == block_id
    )


def event_open_outage_count(event_id):
    return sum(
        1 for o in db.outages.values()
        if o["storm_event_id"] == event_id and o["outage_status"] not in TERMINAL_OUTAGE
    )


def event_cost_totals(event_id):
    entries = [e for e in db.cost_ledger_entries.values() if e["storm_event_id"] == event_id]
    total_labor = sum(e["amount_cents"] for e in entries
                      if e["entry_type"] in ("LABOR_INTERNAL", "LABOR_MUTUAL_AID"))
    total_material = sum(e["amount_cents"] for e in entries if e["entry_type"] == "MATERIAL")
    total_ma = sum(e["amount_cents"] for e in entries
                   if e["entry_type"] in ("LABOR_MUTUAL_AID", "MUTUAL_AID_PENALTY"))
    total_lodging = sum(e["amount_cents"] for e in entries if e["entry_type"] == "LODGING")
    total_event = sum(e["amount_cents"] for e in entries)
    capital = sum(e["amount_cents"] for e in entries if e["cost_class"] == "CAPITAL")
    om = sum(e["amount_cents"] for e in entries if e["cost_class"] == "O_AND_M")
    return {
        "total_labor_cents": total_labor,
        "total_material_cents": total_material,
        "total_mutual_aid_cents": total_ma,
        "total_lodging_cents": total_lodging,
        "total_event_cost_cents": total_event,
        "capital_cost_cents": capital,
        "om_cost_cents": om,
    }


def fema_eligible_cost(claim):
    """FEMA eligibility: LABOR_INTERNAL/LABOR_MUTUAL_AID/MATERIAL entries for the
    claim's county, posted within [activated_at, activated_at + 96h] inclusive.
    LODGING and MUTUAL_AID_PENALTY are excluded."""
    event = db.storm_events.get(claim["storm_event_id"])
    if event is None:
        return 0
    activated = event.get("activated_at")
    if activated is None:
        return 0
    start = parse_iso(activated)
    end = start + timedelta(hours=ELIGIBILITY_HOURS)
    total = 0
    for e in db.cost_ledger_entries.values():
        if e["storm_event_id"] != claim["storm_event_id"]:
            continue
        if e["county_code"] != claim["county_code"]:
            continue
        if e["entry_type"] not in ("LABOR_INTERNAL", "LABOR_MUTUAL_AID", "MATERIAL"):
            continue
        posted = parse_iso(e["posted_at"])
        if posted < start or posted > end:
            continue
        total += e["amount_cents"]
    return total


# ---------------------------------------------------------------------------
# ETR calculations
# ---------------------------------------------------------------------------
def etr_provisional(cause_code, customers_affected, confirmed_at):
    """Provisional variant: base 120 + round_half_up(min(ca, 5000) * 2 * cause_factor)."""
    mult = Decimal(min(customers_affected, CUSTOMER_CAP)) * Decimal(PER_CUSTOMER_MINUTES) \
        * CAUSE_FACTOR[cause_code]
    add_minutes = int(mult.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return confirmed_at + timedelta(minutes=BASE_PREP_MINUTES + add_minutes)


def etr_post_assessment(assessment, outage, accepted_at):
    """Post-assessment variant: crew_factor 1.0 if any non-cancelled WO on the
    outage has an assignee, else 1.5; repair = round_half_up(est * factor);
    + 45 switching overhead when requires_switching."""
    crew_factor = Decimal("1.5")
    for wo in db.work_orders.values():
        if wo["outage_id"] != outage["id"]:
            continue
        if wo["execution_status"] == "CANCELLED":
            continue
        if wo.get("assigned_crew_id") or wo.get("assigned_mutual_aid_crew_id"):
            crew_factor = Decimal("1.0")
            break
    repair_dec = Decimal(assessment["estimated_repair_minutes"]) * crew_factor
    repair = int(repair_dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    total = repair + (SWITCHING_OVERHEAD_MINUTES if assessment.get("requires_switching") else 0)
    return accepted_at + timedelta(minutes=total)


def fatigue_projection(crew, outage):
    """projected = worked_minutes_this_shift + estimate, where estimate is the
    ACCEPTED assessment's estimated_repair_minutes, else 120."""
    estimate = DEFAULT_ESTIMATE_MINUTES
    for a in db.damage_assessments.values():
        if a["outage_id"] == outage["id"] and a["assessment_status"] == "ACCEPTED":
            estimate = a["estimated_repair_minutes"]
            break
    return crew_worked_minutes(crew) + estimate


# ---------------------------------------------------------------------------
# Ledger posting
# ---------------------------------------------------------------------------
def post_ledger_entry(storm_event_id, work_order_id, entry_type, cost_class,
                      county_code, amount_cents, reversed_entry_id=None):
    entry = new_append()
    entry.update({
        "storm_event_id": storm_event_id,
        "work_order_id": work_order_id,
        "entry_type": entry_type,
        "cost_class": cost_class,
        "county_code": county_code,
        "amount_cents": amount_cents,
        "posted_at": iso_ms(db.now()),
        "reversed_entry_id": reversed_entry_id,
    })
    db.cost_ledger_entries[entry["id"]] = entry
    return entry


def create_etr_revision(outage, reason, published_etr_dt, issued_by):
    """Append an EtrRevision and move the outage's current_etr.

    revision_seq is per-outage monotonic starting at 1; previous_etr is the
    outage's current_etr immediately before this revision (null for seq 1).
    Caller is responsible for the outage version increment.
    """
    seqs = [r["revision_seq"] for r in db.etr_revisions.values()
            if r["outage_id"] == outage["id"]]
    next_seq = (max(seqs) + 1) if seqs else 1
    rev = new_append()
    rev.update({
        "outage_id": outage["id"],
        "revision_seq": next_seq,
        "revision_reason": reason,
        "published_etr": iso_ms(published_etr_dt),
        "previous_etr": outage.get("current_etr"),
        "issued_by": issued_by,
    })
    db.etr_revisions[rev["id"]] = rev
    outage["current_etr"] = rev["published_etr"]
    return rev


# ---------------------------------------------------------------------------
# Event-closure gate
# ---------------------------------------------------------------------------
def check_event_not_closed(event):
    if event["event_status"] == "CLOSED":
        from errors import ERR_EVENT_CLOSED
        raise_err(ERR_EVENT_CLOSED, "Mutations scoped to a CLOSED event are rejected")


# ---------------------------------------------------------------------------
# Serializers (computed fields reconciled at read time)
# ---------------------------------------------------------------------------
def serialize_event(e):
    totals = event_cost_totals(e["id"])
    return {
        "id": e["id"],
        "event_name": e["event_name"],
        "event_type": e["event_type"],
        "event_status": e["event_status"],
        "activated_at": e.get("activated_at"),
        "open_outage_count": event_open_outage_count(e["id"]),
        "total_labor_cents": totals["total_labor_cents"],
        "total_material_cents": totals["total_material_cents"],
        "total_mutual_aid_cents": totals["total_mutual_aid_cents"],
        "total_lodging_cents": totals["total_lodging_cents"],
        "total_event_cost_cents": totals["total_event_cost_cents"],
        "capital_cost_cents": totals["capital_cost_cents"],
        "om_cost_cents": totals["om_cost_cents"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_feeder(f):
    return {
        "id": f["id"],
        "feeder_code": f["feeder_code"],
        "county_code": f["county_code"],
        "service_customer_count": f["service_customer_count"],
        "cluster_signal_threshold": f["cluster_signal_threshold"],
        "cluster_call_threshold": f["cluster_call_threshold"],
        "certified_priority_count": feeder_certified_count(f["id"]),
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def serialize_priority_customer(pc):
    return {
        "id": pc["id"],
        "account_ref": pc["account_ref"],
        "priority_class": pc["priority_class"],
        "feeder_id": pc["feeder_id"],
        "certification_status": pc["certification_status"],
        "certified_through": pc.get("certified_through"),
        "created_at": pc["created_at"],
        "updated_at": pc["updated_at"],
        "version": pc["version"],
    }


def serialize_signal(s):
    return {
        "id": s["id"],
        "signal_type": s["signal_type"],
        "feeder_id": s["feeder_id"],
        "outage_id": s.get("outage_id"),
        "occurred_at": s["occurred_at"],
        "disposition": s["disposition"],
        "created_at": s["created_at"],
    }


def serialize_outage(o):
    return {
        "id": o["id"],
        "storm_event_id": o["storm_event_id"],
        "feeder_id": o["feeder_id"],
        "parent_outage_id": o.get("parent_outage_id"),
        "outage_status": o["outage_status"],
        "cause_code": o.get("cause_code"),
        "customers_affected": o.get("customers_affected"),
        "confirmed_at": o.get("confirmed_at"),
        "current_etr": o.get("current_etr"),
        "etr_missed": outage_etr_missed(o),
        "has_priority_customers": feeder_has_certified(o["feeder_id"]),
        "priority_score": outage_priority_score(o),
        "restoration_reported_at": o.get("restoration_reported_at"),
        "merged_into_outage_id": o.get("merged_into_outage_id"),
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def serialize_revision(r):
    return {
        "id": r["id"],
        "outage_id": r["outage_id"],
        "revision_seq": r["revision_seq"],
        "revision_reason": r["revision_reason"],
        "published_etr": r["published_etr"],
        "previous_etr": r["previous_etr"],
        "issued_by": r["issued_by"],
        "created_at": r["created_at"],
    }


def serialize_assessment(a):
    return {
        "id": a["id"],
        "outage_id": a["outage_id"],
        "assessor_crew_id": a["assessor_crew_id"],
        "assessment_status": a["assessment_status"],
        "damage_class": a["damage_class"],
        "estimated_repair_minutes": a["estimated_repair_minutes"],
        "requires_switching": a["requires_switching"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_crew(c):
    return {
        "id": c["id"],
        "crew_code": c["crew_code"],
        "crew_type": c["crew_type"],
        "home_base": c["home_base"],
        "hourly_rate_cents": c["hourly_rate_cents"],
        "crew_status": c["crew_status"],
        "shift_started_at": c.get("shift_started_at"),
        "worked_minutes_this_shift": crew_worked_minutes(c),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_ma_crew(c):
    return {
        "id": c["id"],
        "storm_event_id": c["storm_event_id"],
        "company_name": c["company_name"],
        "crew_type": c["crew_type"],
        "roster_size": c["roster_size"],
        "service_county_code": c["service_county_code"],
        "daily_rate_cents": c["daily_rate_cents"],
        "per_diem_cents": c["per_diem_cents"],
        "committed_window_start": c["committed_window_start"],
        "committed_window_end": c["committed_window_end"],
        "ma_status": c["ma_status"],
        "arrived_at": c.get("arrived_at"),
        "departed_at": c.get("departed_at"),
        "lodging_block_id": c.get("lodging_block_id"),
        "engagement_cost_cents": c.get("engagement_cost_cents"),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_block(b):
    return {
        "id": b["id"],
        "storm_event_id": b["storm_event_id"],
        "hotel_name": b["hotel_name"],
        "county_code": b["county_code"],
        "room_count": b["room_count"],
        "nightly_rate_cents": b["nightly_rate_cents"],
        "window_start": b["window_start"],
        "window_end": b["window_end"],
        "block_status": b["block_status"],
        "rooms_allocated": block_rooms_allocated(b["id"]),
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def serialize_work_order(w):
    return {
        "id": w["id"],
        "outage_id": w["outage_id"],
        "work_type": w["work_type"],
        "required_crew_type": w["required_crew_type"],
        "requires_switching_order": w["requires_switching_order"],
        "execution_status": w["execution_status"],
        "verification_status": w["verification_status"],
        "assigned_crew_id": w.get("assigned_crew_id"),
        "assigned_mutual_aid_crew_id": w.get("assigned_mutual_aid_crew_id"),
        "switching_order_id": w.get("switching_order_id"),
        "arrived_at": w.get("arrived_at"),
        "completed_at": w.get("completed_at"),
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def serialize_switching_order(s):
    return {
        "id": s["id"],
        "work_order_id": s["work_order_id"],
        "switching_steps": s["switching_steps"],
        "so_status": s["so_status"],
        "issuer_user_id": s["issuer_user_id"],
        "approver_user_id": s.get("approver_user_id"),
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_stock(s):
    reserved = stock_reserved(s["id"])
    return {
        "id": s["id"],
        "warehouse_code": s["warehouse_code"],
        "material_sku": s["material_sku"],
        "quantity_on_hand": s["quantity_on_hand"],
        "unit_cost_cents": s["unit_cost_cents"],
        "quantity_reserved": reserved,
        "quantity_available": s["quantity_on_hand"] - reserved,
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_requisition(r):
    return {
        "id": r["id"],
        "work_order_id": r["work_order_id"],
        "material_stock_id": r["material_stock_id"],
        "quantity": r["quantity"],
        "requisition_status": r["requisition_status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_ledger_entry(e):
    return {
        "id": e["id"],
        "storm_event_id": e["storm_event_id"],
        "work_order_id": e["work_order_id"],
        "entry_type": e["entry_type"],
        "cost_class": e["cost_class"],
        "county_code": e["county_code"],
        "amount_cents": e["amount_cents"],
        "posted_at": e["posted_at"],
        "reversed_entry_id": e.get("reversed_entry_id"),
        "created_at": e["created_at"],
    }


def serialize_claim(c):
    eligible = fema_eligible_cost(c)
    snapshot = c.get("eligible_snapshot_cents")
    variance = (eligible - snapshot) if snapshot is not None else None
    return {
        "id": c["id"],
        "storm_event_id": c["storm_event_id"],
        "county_code": c["county_code"],
        "threshold_cents": c["threshold_cents"],
        "claim_status": c["claim_status"],
        "eligible_cost_cents": eligible,
        "eligible_snapshot_cents": snapshot,
        "variance_cents": variance,
        "preparer_user_id": c.get("preparer_user_id"),
        "certifier_user_id": c.get("certifier_user_id"),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def sort_created_asc(items):
    """Default list ordering: created_at ASC; stable tie-break via insertion
    sequence (never id)."""
    return sorted(items, key=lambda x: (x["created_at"], x["_mono"]))
