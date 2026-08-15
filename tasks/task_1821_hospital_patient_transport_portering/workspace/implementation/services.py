"""Business logic: travel estimates, eligibility, selection, auto-dispatch,
sweeps, delay records, and staffing adequacy. All rules follow PRD section 3
and the SCAFFOLD calculation table exactly."""

import uuid
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from db import store, now
from errors import ApiError
from util import fmt, parse_datetime, floor_minutes

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD calculations table)
# ---------------------------------------------------------------------------

EQUIPMENT_FACTOR = {
    "PORTER_ONLY": Decimal("1.0"),
    "WHEELCHAIR": Decimal("1.1"),
    "STRETCHER": Decimal("1.25"),
    "BARIATRIC_STRETCHER": Decimal("1.4"),
}
OXYGEN_SETUP_MINUTES = 2
CONGESTION_SURCHARGE_PER_TRIP = 2
CONGESTION_CAP = 5

TARGET_RESPONSE_MINUTES = {"ROUTINE": 120, "URGENT": 45, "STAT": 15}
OFFER_TTL_SECONDS = 10 * 60  # strictly greater than 10 minutes expires
DWELL_SECONDS_DEEP = 15 * 60  # inclusive

LOCATION_MULTIPLIER = {
    "OR": Decimal("2.0"),
    "IMAGING": Decimal("1.5"),
    "WARD": Decimal("1.0"),
    "ICU": Decimal("1.0"),
    "ED": Decimal("1.0"),
    "DISCHARGE_LOUNGE": Decimal("1.0"),
    "OTHER": Decimal("1.0"),
}

PRIORITY_RANK = {"STAT": 0, "URGENT": 1, "ROUTINE": 2}

LOCATION_TYPES = {"WARD", "ICU", "ED", "OR", "IMAGING", "DISCHARGE_LOUNGE", "OTHER"}
EQUIPMENT_TYPES = {"WHEELCHAIR", "STRETCHER", "BARIATRIC_STRETCHER"}
REQUIRED_EQUIPMENT = {"PORTER_ONLY", "WHEELCHAIR", "STRETCHER", "BARIATRIC_STRETCHER"}
PRIORITIES = {"ROUTINE", "URGENT", "STAT"}
ISOLATION_PRECAUTIONS = {"NONE", "CONTACT", "DROPLET", "AIRBORNE"}
CAUSE_CODES = {"NO_TRANSPORTER", "NO_EQUIPMENT", "CLEANING_BACKLOG", "PATIENT_NOT_READY", "SYSTEM", "OTHER"}
DAY_TYPES = {"WEEKDAY", "WEEKEND"}

ACTIVE_REQUEST_STATUSES = ("QUEUED", "ASSIGNED", "AT_PICKUP", "IN_TRANSIT")
TERMINAL_REQUEST_STATUSES = ("COMPLETED", "CANCELLED", "SUPERSEDED")

PATIENT_MIN_SEPARATION_SECONDS = 75 * 60  # strictly less than 75 min conflicts


# ---------------------------------------------------------------------------
# Record plumbing
# ---------------------------------------------------------------------------

def stamp_new(rec):
    """Assign system fields for a fresh primary resource (id/created/updated/version)."""
    ts = fmt(now())
    rec["id"] = str(uuid.uuid4())
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = store.next_seq()
    return rec


def touch(rec):
    """Refresh updated_at and increment version by exactly one."""
    rec["updated_at"] = fmt(now())
    rec["version"] += 1


# ---------------------------------------------------------------------------
# Travel edges and estimates (calculation: travel_time_estimate)
# ---------------------------------------------------------------------------

def find_edge(from_location_id, to_location_id):
    for e in store.travel_edges.values():
        if e["from_location_id"] == from_location_id and e["to_location_id"] == to_location_id:
            return e
    return None


def deadhead_minutes(transporter, req):
    """Deadhead leg minutes; None when the required edge is missing.
    Zero (no edge required) when the transporter already stands at the origin."""
    if transporter["current_location_id"] == req["origin_location_id"]:
        return 0
    e = find_edge(transporter["current_location_id"], req["origin_location_id"])
    return e["base_minutes"] if e is not None else None


def travel_estimate(transporter, req):
    """Dispatch-variant travel estimate in integer minutes.
    Raises ERR_NO_TRAVEL_EDGE when a required leg has no edge."""
    dh = deadhead_minutes(transporter, req)
    if dh is None:
        raise ApiError("ERR_NO_TRAVEL_EDGE", 422, "no travel edge from transporter location to origin")
    e2 = find_edge(req["origin_location_id"], req["destination_location_id"])
    if e2 is None:
        raise ApiError("ERR_NO_TRAVEL_EDGE", 422, "no travel edge from origin to destination")
    if req["isolation_precaution"] == "AIRBORNE":
        loaded_base = e2["airborne_minutes"]
    else:
        loaded_base = e2["base_minutes"]
    loaded = int((Decimal(loaded_base) * EQUIPMENT_FACTOR[req["required_equipment"]]).to_integral_value(rounding=ROUND_CEILING))
    oxygen = OXYGEN_SETUP_MINUTES if req["oxygen_required"] else 0
    return dh + loaded + oxygen


# ---------------------------------------------------------------------------
# Transporter eligibility and selection (calculation: auto_dispatch_selection)
# ---------------------------------------------------------------------------

def has_active_assignment(transporter_id):
    for r in store.requests.values():
        if r["assigned_transporter_id"] == transporter_id and r["status"] in ("ASSIGNED", "AT_PICKUP", "IN_TRANSIT"):
            return True
    return False


def has_pending_offer_for(transporter_id):
    for o in store.offers.values():
        if o["transporter_id"] == transporter_id and o["status"] == "PENDING":
            return True
    return False


def pending_offer_for_request(request_id):
    for o in store.offers.values():
        if o["transport_request_id"] == request_id and o["status"] == "PENDING":
            return o
    return None


def transporter_eligible(t, req, check_isolation=True):
    """Full eligibility predicate. The isolation gate can be separated out so the
    manual path can raise ERR_ISOLATION_CAPABILITY_MISMATCH (tier 7) ahead of the
    general ERR_TRANSPORTER_INELIGIBLE (tier 10)."""
    if check_isolation and req["isolation_precaution"] != "NONE" and not t["isolation_certified"]:
        return False
    if t["status"] != "ON_SHIFT":
        return False
    if has_active_assignment(t["id"]):
        return False
    if has_pending_offer_for(t["id"]):
        return False
    if t["id"] in req["excluded_transporter_ids"]:
        return False
    if req["oxygen_required"] and not t["oxygen_certified"]:
        return False
    if req["required_equipment"] != "PORTER_ONLY" and req["required_equipment"] not in t["certified_equipment"]:
        return False
    return True


def eligible_pool(req):
    """Eligible transporters ranked by deadhead minutes ASC, then transporter
    created_at ASC. Transporters without a deadhead edge (and not at the origin)
    are excluded from the pool."""
    ranked = []
    for t in store.transporters.values():
        if not transporter_eligible(t, req):
            continue
        d = deadhead_minutes(t, req)
        if d is None:
            continue
        ranked.append((d, t))
    ranked.sort(key=lambda x: (x[0], x[1]["created_at"], x[1]["_seq"]))
    return [t for _, t in ranked]


def select_asset(equipment_type, extra=None):
    """Deterministic equipment pick: AVAILABLE, matching type, created_at ASC,
    then asset_tag ASC. `extra` is an additional candidate not currently
    AVAILABLE (the asset a pending offer is about to release on supersession)."""
    cands = [a for a in store.equipment_assets.values()
             if a["status"] == "AVAILABLE" and a["equipment_type"] == equipment_type]
    if extra is not None and all(a["id"] != extra["id"] for a in cands):
        cands.append(extra)
    cands.sort(key=lambda a: (a["created_at"], a["asset_tag"], a["_seq"]))
    return cands[0] if cands else None


# ---------------------------------------------------------------------------
# Offers
# ---------------------------------------------------------------------------

def make_offer(req, transporter, asset):
    """Create a PENDING DispatchOffer; reserves the asset (if any), advances the
    per-request sequence, and bumps the request version (cascade rule)."""
    req["offer_seq_count"] += 1
    offer = stamp_new({
        "transport_request_id": req["id"],
        "transporter_id": transporter["id"],
        "status": "PENDING",
        "offer_seq": req["offer_seq_count"],
        "estimated_travel_minutes": travel_estimate(transporter, req),
        "responded_at": None,
        "_reserved_asset_id": asset["id"] if asset is not None else None,
    })
    store.offers[offer["id"]] = offer
    if asset is not None:
        asset["status"] = "RESERVED"
        touch(asset)
        req["assigned_equipment_id"] = asset["id"]
    touch(req)
    return offer


def release_offer_asset(offer):
    """Return an offer's reserved asset to AVAILABLE. Caller decides whether to
    run auto-dispatch evaluation afterwards."""
    aid = offer.get("_reserved_asset_id")
    if not aid:
        return None
    a = store.equipment_assets.get(aid)
    if a is not None and a["status"] == "RESERVED":
        a["status"] = "AVAILABLE"
        touch(a)
        return a
    return None


# ---------------------------------------------------------------------------
# Auto-dispatch evaluation (calculation: auto_dispatch_selection)
# ---------------------------------------------------------------------------

def auto_dispatch_eval(asset):
    """Re-home a freed asset: pick the highest-priority QUEUED request with no
    PENDING offer whose required_equipment matches, then the best eligible
    transporter, and create a PENDING offer reserving this asset. An empty pool
    leaves the asset AVAILABLE. Never runs for PORTER_ONLY requests (they never
    match an asset type)."""
    if asset["status"] != "AVAILABLE":
        return
    etype = asset["equipment_type"]
    cands = [r for r in store.requests.values()
             if r["status"] == "QUEUED"
             and r["required_equipment"] == etype
             and pending_offer_for_request(r["id"]) is None]
    cands.sort(key=lambda r: (PRIORITY_RANK[r["priority"]], r["created_at"], r["_seq"]))
    if not cands:
        return
    req = cands[0]
    pool = eligible_pool(req)
    if not pool:
        return
    try:
        make_offer(req, pool[0], asset)
    except ApiError:
        # e.g. loaded-leg edge missing: no offer can be built; asset stays AVAILABLE.
        return


# ---------------------------------------------------------------------------
# SLA posture, escalation, delay records (calculations: sla_posture_evaluation,
# delay_impact)
# ---------------------------------------------------------------------------

def eval_posture(elapsed_minutes, target):
    if elapsed_minutes > target:
        return "BREACHED"
    if elapsed_minutes >= (3 * target) // 4:
        return "AT_RISK"
    return "ON_TRACK"


def delay_record_exists(request_id, record_kind):
    for d in store.delay_records.values():
        if d["transport_request_id"] == request_id and d["record_kind"] == record_kind:
            return True
    return False


def make_delay_record(req, record_kind, delay_minutes, cause_code, recorded_via):
    """DelayRecord carries only id + created_at as common fields (immutable)."""
    dest = store.locations.get(req["destination_location_id"])
    mult = LOCATION_MULTIPLIER.get(dest["location_type"], Decimal("1.0")) if dest else Decimal("1.0")
    impact = int((Decimal(delay_minutes) * mult).to_integral_value(rounding=ROUND_HALF_UP))
    rec = {
        "id": str(uuid.uuid4()),
        "created_at": fmt(now()),
        "_seq": store.next_seq(),
        "transport_request_id": req["id"],
        "record_kind": record_kind,
        "delay_minutes": int(delay_minutes),
        "impact_minutes": impact,
        "cause_code": cause_code,
        "recorded_via": recorded_via,
    }
    store.delay_records[rec["id"]] = rec
    return rec


def run_sweep():
    """Pinned order: (1) expire PENDING offers past TTL, oldest first; (2) recompute
    sla_posture for QUEUED/ASSIGNED in created_at ASC; (3) escalate QUEUED+BREACHED
    one tier with posture recompute; (4) create missing SLA_BREACH records."""
    n = now()

    offers_expired = 0
    pend = [o for o in store.offers.values() if o["status"] == "PENDING"]
    pend.sort(key=lambda o: (o["created_at"], o["_seq"]))
    for o in pend:
        created = parse_datetime(o["created_at"], "created_at")
        if (n - created).total_seconds() > OFFER_TTL_SECONDS:
            o["status"] = "EXPIRED"
            touch(o)
            # Asset returns to AVAILABLE with NO auto-dispatch eval on expiry.
            release_offer_asset(o)
            offers_expired += 1

    requests_escalated = 0
    sla_records_created = 0
    reqs = [r for r in store.requests.values() if r["status"] in ("QUEUED", "ASSIGNED")]
    reqs.sort(key=lambda r: (r["created_at"], r["_seq"]))
    for r in reqs:
        elapsed = floor_minutes(n - parse_datetime(r["created_at"], "created_at"))
        posture = eval_posture(elapsed, TARGET_RESPONSE_MINUTES[r["priority"]])
        if posture != r["sla_posture"]:
            r["sla_posture"] = posture
            touch(r)
        if r["status"] == "QUEUED" and posture == "BREACHED" and r["priority"] != "STAT":
            r["priority"] = "URGENT" if r["priority"] == "ROUTINE" else "STAT"
            r["escalation_count"] += 1
            requests_escalated += 1
            # Recompute posture fresh against the NEW target; may drop downward.
            posture = eval_posture(elapsed, TARGET_RESPONSE_MINUTES[r["priority"]])
            r["sla_posture"] = posture
            touch(r)
        if r["sla_posture"] == "BREACHED" and r["status"] in ("QUEUED", "ASSIGNED"):
            if not delay_record_exists(r["id"], "SLA_BREACH"):
                make_delay_record(r, "SLA_BREACH", elapsed - TARGET_RESPONSE_MINUTES[r["priority"]],
                                  "SYSTEM", "SWEEP")
                sla_records_created += 1

    return {
        "offers_expired": offers_expired,
        "requests_escalated": requests_escalated,
        "sla_records_created": sla_records_created,
    }


# ---------------------------------------------------------------------------
# Staffing adequacy (calculation: staffing_requirement)
# ---------------------------------------------------------------------------

def staffing_adequacy(date_dt, hour_block, window_hours, variant):
    required = 0
    if variant == "FORECAST":
        day_type = "WEEKDAY" if date_dt.weekday() < 5 else "WEEKEND"
        for h in range(hour_block, hour_block + window_hours):
            tot = Decimal(0)
            for dc in store.demand_curves.values():
                if dc["day_type"] == day_type and dc["hour_block"] == h:
                    tot += Decimal(str(dc["expected_requests"])) * Decimal(dc["mean_service_minutes"])
            required += int((tot / Decimal(60)).to_integral_value(rounding=ROUND_CEILING))
    else:  # REPLAY
        n = now()
        window_start = n - timedelta(hours=24)
        for h in range(hour_block, hour_block + window_hours):
            secs = Decimal(0)
            for r in store.requests.values():
                if r["status"] != "COMPLETED" or not r["completed_at"] or not r["at_pickup_at"]:
                    continue
                comp = parse_datetime(r["completed_at"], "completed_at")
                if not (window_start <= comp < n):
                    continue
                if parse_datetime(r["created_at"], "created_at").hour != h:
                    continue
                secs += Decimal((comp - parse_datetime(r["at_pickup_at"], "at_pickup_at")).total_seconds())
            required += int((secs / Decimal(3600)).to_integral_value(rounding=ROUND_CEILING))

    scheduled_ids = set()
    for h in range(hour_block, hour_block + window_hours):
        block_start = date_dt + timedelta(hours=h)
        block_end = block_start + timedelta(hours=1)
        for s in store.shifts.values():
            if s["status"] != "PLANNED":
                continue
            if parse_datetime(s["shift_start"], "shift_start") < block_end and \
                    parse_datetime(s["shift_end"], "shift_end") > block_start:
                scheduled_ids.add(s["transporter_id"])
    scheduled = len(scheduled_ids)
    return {
        "required_transporters": required,
        "scheduled_transporters": scheduled,
        "gap": scheduled - required,
    }
