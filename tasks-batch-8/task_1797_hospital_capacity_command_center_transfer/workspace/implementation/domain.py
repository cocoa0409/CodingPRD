"""Domain computations, derived fields, cascades, and serializers."""

import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from store import db, now, new_entity, touch
from domain_time import fmt

# ---------------------------------------------------------------------------
# Enums, ranks, constants
# ---------------------------------------------------------------------------

SERVICES = ["CARDIAC", "NEURO", "TRAUMA", "MEDICAL", "SURGICAL", "ONCOLOGY"]
ACUITY_LEVELS = [
    "ACUITY_1_CRITICAL",
    "ACUITY_2_STEPDOWN",
    "ACUITY_3_MEDICAL_SURGICAL",
    "ACUITY_4_OBSERVATION",
]
ISO_LEVELS = ["NONE", "CONTACT", "DROPLET", "AIRBORNE"]
PRIORITIES = ["EMERGENT", "URGENT", "ELECTIVE"]
MANUAL_DECLINE_REASONS = ["PHYSICIAN_DECLINED", "NO_CAPACITY", "CLINICAL"]

ACUITY_RANK = {
    "ACUITY_4_OBSERVATION": 1,
    "ACUITY_3_MEDICAL_SURGICAL": 2,
    "ACUITY_2_STEPDOWN": 3,
    "ACUITY_1_CRITICAL": 4,
}
ISO_RANK = {"NONE": 0, "CONTACT": 1, "DROPLET": 2, "AIRBORNE": 3}

HELD_WEIGHT = Decimal("0.5")
BOARDING_WEIGHT = Decimal("0.75")
INBOUND_WEIGHT = Decimal("0.5")
DIVERSION_RECOMMEND_THRESHOLD = Decimal("95.0")

SERVICE_WEIGHTS = {
    "CARDIAC": Decimal("0.5"),
    "MEDICAL": Decimal("0.3"),
    "NEURO": Decimal("0.2"),
    "TRAUMA": Decimal("0.2"),
    "SURGICAL": Decimal("0.2"),
    "ONCOLOGY": Decimal("0.2"),
}

ED_CONVERSION_RATE = Decimal("0.8")
ELECTIVE_BUFFER = 2

HOLD_TTL_MINUTES = 60
EXTEND_MINUTES = 30
HOLD_EXTEND_MAX = 2
HOLD_QUOTA_PER_FACILITY = 6
CONSULT_TTL_MINUTES = 30
MIN_DIVERSION_MINUTES = 30
BOARDING_HUDDLE_THRESHOLD_MINUTES = 120
EXECUTIVE_ESCALATION_MINUTES = 240
HUDDLE_MAX_PER_WINDOW = 3
HUDDLE_WINDOW_HOURS = 24
REBALANCE_MARGIN = Decimal("10.0")

NON_TERMINAL_TRANSFER_STATUSES = {
    "INTAKE",
    "CONSULT_PENDING",
    "DECLINED",
    "EXPIRED",
    "ACCEPTED",
    "HOLD_PLACED",
    "ASSIGNED",
}


def is_ed_unit(unit):
    return isinstance(unit, str) and unit.startswith("ED")


def round1(value):
    """Round half-up to exactly one decimal place; returns a float."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return float(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def facility_beds(facility_id):
    return [b for b in db.beds.values() if b["facility_id"] == facility_id]


def facility_transfers(facility_id):
    return [t for t in db.transfers.values() if t["facility_id"] == facility_id]


def facility_boarding(facility_id):
    return [r for r in db.boarding.values() if r["facility_id"] == facility_id]


def facility_admissions(facility_id):
    return [a for a in db.admissions.values() if a["facility_id"] == facility_id]


def facility_diversions(facility_id):
    return [d for d in db.diversions.values() if d["facility_id"] == facility_id]


def facility_forecasts(facility_id):
    return [f for f in db.forecasts.values() if f["facility_id"] == facility_id]


def boarding_waiters_count(facility_id):
    return sum(
        1
        for r in facility_boarding(facility_id)
        if r["placement_status"] in ("WAITING", "OFFERED")
    )


def active_inbound_count(facility_id):
    return sum(
        1
        for t in facility_transfers(facility_id)
        if t["status"] in NON_TERMINAL_TRANSFER_STATUSES
    )


# ---------------------------------------------------------------------------
# Derived facility posture (PRD 3.2, 3.7, 3.9)
# ---------------------------------------------------------------------------

def diversion_status_of(facility_id):
    ts = now()
    has_full = False
    has_service = False
    for d in facility_diversions(facility_id):
        if d["status"] != "ACTIVE":
            continue
        if d["starts_at"] <= ts < d["ends_at"]:  # half-open [starts_at, ends_at)
            if d["level"] == "FULL":
                has_full = True
            else:
                has_service = True
    if has_full:
        return "DIVERT_FULL"
    if has_service:
        return "DIVERT_SERVICE"
    return "ACCEPTING"


def load_scores(facility_id):
    beds = facility_beds(facility_id)
    staffed = [b for b in beds if b["staffed"]]
    n_staffed = len(staffed)
    occupied = sum(1 for b in staffed if b["status"] == "OCCUPIED")
    held = sum(1 for b in staffed if b["status"] == "HELD")
    boarders = boarding_waiters_count(facility_id)
    inbound = active_inbound_count(facility_id)
    if n_staffed == 0:
        return {
            "staffed_beds": 0,
            "occupied_beds": occupied,
            "held_beds": held,
            "boarding_waiters": boarders,
            "active_inbound_transfers": inbound,
            "raw": 0.0,
            "weighted": 0.0,
            "diversion_recommended": False,
        }
    s = Decimal(n_staffed)
    raw = round1(Decimal(100) * Decimal(occupied) / s)
    pressure = (
        Decimal(occupied)
        + HELD_WEIGHT * held
        + BOARDING_WEIGHT * boarders
        + INBOUND_WEIGHT * inbound
    )
    weighted = round1(Decimal(100) * pressure / s)
    return {
        "staffed_beds": n_staffed,
        "occupied_beds": occupied,
        "held_beds": held,
        "boarding_waiters": boarders,
        "active_inbound_transfers": inbound,
        "raw": raw,
        "weighted": weighted,
        "diversion_recommended": Decimal(str(weighted)) >= DIVERSION_RECOMMEND_THRESHOLD,
    }


def service_weighted_occupancy(facility_id):
    """Per-service pct rounded to 1dp FIRST, then weighted aggregate rounded."""
    beds = [b for b in facility_beds(facility_id) if b["staffed"] and not is_ed_unit(b["unit"])]
    by_service = {}
    for b in beds:
        by_service.setdefault(b["service"], []).append(b)
    num = Decimal("0")
    den = Decimal("0")
    for svc, rows in by_service.items():
        total = len(rows)
        if total == 0:
            continue
        occ = sum(1 for b in rows if b["status"] == "OCCUPIED")
        occ_pct = (Decimal(100) * Decimal(occ) / Decimal(total)).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )
        w = SERVICE_WEIGHTS[svc]
        num += w * occ_pct
        den += w
    if den == 0:
        return 0.0
    return round1(num / den)


def inpatient_bed_count(facility_id):
    return sum(
        1
        for b in facility_beds(facility_id)
        if b["staffed"] and not is_ed_unit(b["unit"])
    )


def latest_published_forecast(facility_id, require_non_stale=False):
    cands = [
        f
        for f in facility_forecasts(facility_id)
        if f["status"] == "PUBLISHED" and (not require_non_stale or not f["stale"])
    ]
    if not cands:
        return None
    return max(cands, key=lambda f: f["_seq"])


def next_elective_window_start(facility_id):
    fc = latest_published_forecast(facility_id, require_non_stale=True)
    if fc is None:
        return None
    threshold = inpatient_bed_count(facility_id) - ELECTIVE_BUFFER
    for idx, census in enumerate(fc["variant_snapshots"]["provisional"]):
        h = idx + 1
        if census <= threshold:
            return fc["generated_at"] + timedelta(hours=h)
    return None


def compute_facility_fields(facility_id):
    scores = load_scores(facility_id)
    beds = facility_beds(facility_id)
    staffed = [b for b in beds if b["staffed"]]
    news = next_elective_window_start(facility_id)
    return {
        "diversion_status": diversion_status_of(facility_id),
        "diversion_recommended": scores["diversion_recommended"],
        "staffed_beds": scores["staffed_beds"],
        "occupied_beds": scores["occupied_beds"],
        "held_beds": scores["held_beds"],
        "available_beds": sum(1 for b in staffed if b["status"] == "AVAILABLE"),
        "out_of_service_beds": sum(1 for b in beds if b["status"] == "OUT_OF_SERVICE"),
        "boarding_waiters": scores["boarding_waiters"],
        "active_inbound_transfers": scores["active_inbound_transfers"],
        "load_score_raw": scores["raw"],
        "load_score_weighted": scores["weighted"],
        "service_weighted_occupancy_pct": service_weighted_occupancy(facility_id),
        "next_elective_window_start": fmt(news) if news else None,
    }


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def mark_latest_published_forecast_stale(facility_id):
    """Bed-availability mutation cascade (PRD 3.9): latest PUBLISHED forecast
    is marked stale; PROVISIONAL forecasts are never marked stale."""
    fc = latest_published_forecast(facility_id)
    if fc is not None and not fc["stale"]:
        fc["stale"] = True
        touch(fc)


def release_hold_effects(hold, end_status):
    """Shared RELEASED/EXPIRED downstream effects (PRD 3.4)."""
    hold["status"] = end_status
    touch(hold)
    bed = db.beds.get(hold["bed_id"])
    if bed is not None and bed["status"] == "HELD":
        bed["status"] = "AVAILABLE"
        bed["cooling_until"] = now() + timedelta(minutes=bed["turnover_minutes"])
        touch(bed)
    req = db.transfers.get(hold["transfer_request_id"])
    if req is not None and req["status"] == "HOLD_PLACED":
        req["status"] = "ACCEPTED"
        touch(req)


# ---------------------------------------------------------------------------
# Bed selector (PRD 3.4)
# ---------------------------------------------------------------------------

def bed_is_eligible(bed, req):
    if bed["status"] != "AVAILABLE" or not bed["staffed"] or is_ed_unit(bed["unit"]):
        return False
    if ACUITY_RANK[bed["max_acuity"]] < ACUITY_RANK[req["acuity"]]:
        return False
    if ISO_RANK[bed["isolation_capability"]] < ISO_RANK[req["isolation_need"]]:
        return False
    if bed["service"] != req["service"] and bed["service"] != "MEDICAL":
        return False
    return True


def bed_score(bed, req):
    score = 0
    if bed["service"] == req["service"]:
        score += 1000
    score += 100 * (4 - (ACUITY_RANK[bed["max_acuity"]] - ACUITY_RANK[req["acuity"]]))
    if ISO_RANK[bed["isolation_capability"]] == ISO_RANK[req["isolation_need"]]:
        score += 10
    if req.get("preferred_unit") is not None and bed["unit"] == req["preferred_unit"]:
        score += 5
    return score


def bed_candidates(facility_id, req):
    """Eligible beds ordered by score DESC, then created_at ASC (never id)."""
    eligible = [b for b in facility_beds(facility_id) if bed_is_eligible(b, req)]
    eligible.sort(key=lambda b: (-bed_score(b, req), b["created_at"], b["_seq"]))
    return eligible


def active_hold_count(facility_id):
    bed_ids = {b["id"] for b in facility_beds(facility_id)}
    return sum(
        1 for h in db.holds.values() if h["bed_id"] in bed_ids and h["status"] == "ACTIVE"
    )


# ---------------------------------------------------------------------------
# Boarding (PRD 3.8)
# ---------------------------------------------------------------------------

def boarding_minutes_of(record):
    heartbeat = record["last_heartbeat_minutes"] if record["last_heartbeat_minutes"] is not None else 0
    clock_component = int((now() - record["started_at"]).total_seconds() // 60)
    return max(heartbeat, clock_component)


def huddle_count_24h_of(record):
    cutoff = now() - timedelta(hours=HUDDLE_WINDOW_HOURS)
    return sum(
        1
        for h in db.huddles.values()
        if h["boarding_record_id"] == record["id"] and h["called_at"] >= cutoff
    )


def create_huddle(record, trigger_reason):
    h = new_entity()
    h.update(
        {
            "boarding_record_id": record["id"],
            "trigger_reason": trigger_reason,
            "status": "CALLED",
            "called_at": now(),
            "resolved_at": None,
            "resolution": None,
        }
    )
    db.huddles[h["id"]] = h
    record["escalation_status"] = "HUDDLE_CALLED"
    touch(record)
    return h


def boarding_escalation_check(record):
    """Returns True when an auto-threshold huddle was called."""
    escalated = False
    bm = boarding_minutes_of(record)
    if (
        record["placement_status"] in ("WAITING", "OFFERED")
        and record["escalation_status"] in ("NONE", "HUDDLE_RESOLVED")
        and bm >= BOARDING_HUDDLE_THRESHOLD_MINUTES
    ):
        create_huddle(record, "AUTO_THRESHOLD")
        escalated = True
    if bm >= EXECUTIVE_ESCALATION_MINUTES and not record["executive_escalation"]:
        record["executive_escalation"] = True
        touch(record)
    return escalated


# ---------------------------------------------------------------------------
# Forecast generation (PRD 3.9)
# ---------------------------------------------------------------------------

def generate_forecast_snapshots(facility_id, horizon_hours, generated_at):
    beds = facility_beds(facility_id)
    noned_staffed = [b for b in beds if b["staffed"] and not is_ed_unit(b["unit"])]
    base = sum(1 for b in noned_staffed if b["status"] == "OCCUPIED")
    pending = []
    for a in facility_admissions(facility_id):
        if a["status"] != "PENDING_DISCHARGE":
            continue
        bed = db.beds.get(a["bed_id"])
        if bed is not None and not is_ed_unit(bed["unit"]):
            pending.append(a)
    boarders = boarding_waiters_count(facility_id)
    ed_adds = math.ceil(boarders * 0.8) if boarders else 0  # ceil(boarders * 0.8)
    committed = []
    provisional = []
    for h in range(1, horizon_hours + 1):
        limit = generated_at + timedelta(hours=h)
        signed = sum(
            1
            for a in pending
            if a["discharge_order_signed"] and a["expected_discharge_at"] <= limit
        )
        unsigned = sum(
            1
            for a in pending
            if not a["discharge_order_signed"] and a["expected_discharge_at"] <= limit
        )
        committed.append(base - signed)
        provisional.append(base - signed - unsigned + ed_adds)
    ip_count = len(noned_staffed)
    if ip_count == 0:
        pct_committed = 0.0
        pct_provisional = 0.0
    else:
        mean_c = Decimal(sum(committed)) / Decimal(horizon_hours)
        mean_p = Decimal(sum(provisional)) / Decimal(horizon_hours)
        pct_committed = round1(Decimal(100) * mean_c / Decimal(ip_count))
        pct_provisional = round1(Decimal(100) * mean_p / Decimal(ip_count))
    return {
        "variant_snapshots": {"committed": committed, "provisional": provisional},
        "occupancy_pct_committed": pct_committed,
        "occupancy_pct_provisional": pct_provisional,
    }


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _common(e):
    return {
        "id": e["id"],
        "created_at": fmt(e["created_at"]),
        "updated_at": fmt(e["updated_at"]),
        "version": e["version"],
    }


def _dt(value):
    return fmt(value) if value is not None else None


def facility_json(f):
    out = {"name": f["name"], "region": f["region"]}
    out.update(compute_facility_fields(f["id"]))
    out.update(_common(f))
    # Canonical ordering: id first is not required; keep declared order readable.
    ordered = {"id": out["id"], "name": out["name"], "region": out["region"]}
    for k in (
        "diversion_status",
        "diversion_recommended",
        "staffed_beds",
        "occupied_beds",
        "held_beds",
        "available_beds",
        "out_of_service_beds",
        "boarding_waiters",
        "active_inbound_transfers",
        "load_score_raw",
        "load_score_weighted",
        "service_weighted_occupancy_pct",
        "next_elective_window_start",
        "created_at",
        "updated_at",
        "version",
    ):
        ordered[k] = out[k]
    return ordered


def bed_json(b):
    out = {
        "id": b["id"],
        "facility_id": b["facility_id"],
        "unit": b["unit"],
        "label": b["label"],
        "service": b["service"],
        "max_acuity": b["max_acuity"],
        "isolation_capability": b["isolation_capability"],
        "staffed": b["staffed"],
        "turnover_minutes": b["turnover_minutes"],
        "status": b["status"],
        "projected_free_at": _dt(b["projected_free_at"]),
        "cooling_until": _dt(b["cooling_until"]),
    }
    out.update(_common(b))
    return out


def physician_json(p):
    out = {
        "id": p["id"],
        "facility_id": p["facility_id"],
        "full_name": p["full_name"],
        "services": list(p["services"]),
        "status": p["status"],
    }
    out.update(_common(p))
    return out


def admission_json(a):
    out = {
        "id": a["id"],
        "facility_id": a["facility_id"],
        "bed_id": a["bed_id"],
        "patient_ref": a["patient_ref"],
        "acuity": a["acuity"],
        "isolation_need": a["isolation_need"],
        "service": a["service"],
        "status": a["status"],
        "expected_discharge_at": _dt(a["expected_discharge_at"]),
        "discharge_order_signed": a["discharge_order_signed"],
        "pending_discharge_at": _dt(a["pending_discharge_at"]),
        "confirmed_discharge_at": _dt(a["confirmed_discharge_at"]),
    }
    out.update(_common(a))
    return out


def transfer_json(t):
    out = {
        "id": t["id"],
        "facility_id": t["facility_id"],
        "source_facility_name": t["source_facility_name"],
        "patient_ref": t["patient_ref"],
        "acuity": t["acuity"],
        "isolation_need": t["isolation_need"],
        "service": t["service"],
        "priority": t["priority"],
        "preferred_unit": t["preferred_unit"],
        "status": t["status"],
        "accepting_physician_id": t["accepting_physician_id"],
        "consult_deadline": _dt(t["consult_deadline"]),
        "consult_count": t["consult_count"],
        "decline_reason": t["decline_reason"],
        "intake_coordinator_id": t["intake_coordinator_id"],
        "assigned_bed_id": t["assigned_bed_id"],
    }
    out.update(_common(t))
    return out


def hold_json(h):
    out = {
        "id": h["id"],
        "bed_id": h["bed_id"],
        "transfer_request_id": h["transfer_request_id"],
        "starts_at": _dt(h["starts_at"]),
        "ttl_minutes": h["ttl_minutes"],
        "expires_at": _dt(h["expires_at"]),
        "status": h["status"],
        "extend_count": h["extend_count"],
    }
    out.update(_common(h))
    return out


def assignment_json(a):
    out = {
        "id": a["id"],
        "transfer_request_id": a["transfer_request_id"],
        "bed_hold_id": a["bed_hold_id"],
        "bed_id": a["bed_id"],
        "created_by_user_id": a["created_by_user_id"],
        "status": a["status"],
        "completed_at": _dt(a["completed_at"]),
    }
    out.update(_common(a))
    return out


def diversion_json(d):
    out = {
        "id": d["id"],
        "facility_id": d["facility_id"],
        "level": d["level"],
        "service": d["service"],
        "starts_at": _dt(d["starts_at"]),
        "ends_at": _dt(d["ends_at"]),
        "declared_by_user_id": d["declared_by_user_id"],
        "status": d["status"],
        "lifted_at": _dt(d["lifted_at"]),
        "lifted_by_user_id": d["lifted_by_user_id"],
    }
    out.update(_common(d))
    return out


def boarding_json(r):
    out = {
        "id": r["id"],
        "facility_id": r["facility_id"],
        "admission_id": r["admission_id"],
        "started_at": _dt(r["started_at"]),
        "boarding_minutes": boarding_minutes_of(r),
        "placement_status": r["placement_status"],
        "escalation_status": r["escalation_status"],
        "huddle_count_24h": huddle_count_24h_of(r),
        "executive_escalation": r["executive_escalation"],
        "last_heartbeat_minutes": r["last_heartbeat_minutes"],
    }
    out.update(_common(r))
    return out


def huddle_json(h):
    out = {
        "id": h["id"],
        "boarding_record_id": h["boarding_record_id"],
        "trigger_reason": h["trigger_reason"],
        "status": h["status"],
        "called_at": _dt(h["called_at"]),
        "resolved_at": _dt(h["resolved_at"]),
        "resolution": h["resolution"],
    }
    out.update(_common(h))
    return out


def forecast_json(f):
    out = {
        "id": f["id"],
        "facility_id": f["facility_id"],
        "horizon_hours": f["horizon_hours"],
        "generated_at": _dt(f["generated_at"]),
        "variant_snapshots": {
            "committed": list(f["variant_snapshots"]["committed"]),
            "provisional": list(f["variant_snapshots"]["provisional"]),
        },
        "occupancy_pct_committed": f["occupancy_pct_committed"],
        "occupancy_pct_provisional": f["occupancy_pct_provisional"],
        "status": f["status"],
        "stale": f["stale"],
        "published_at": _dt(f["published_at"]),
    }
    out.update(_common(f))
    return out
