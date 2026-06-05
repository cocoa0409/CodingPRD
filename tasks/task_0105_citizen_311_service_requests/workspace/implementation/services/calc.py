"""Calculation rules (SCAFFOLD 1.3 / PRD §2.9-2.11)."""
import math
from decimal import Decimal, ROUND_HALF_UP

import db
import clock

CLUSTER_RADIUS_METERS = 150
REOPEN_WINDOW_HOURS = 72
EARTH_RADIUS_METERS = 6371000


def jurisdiction_match(lat, lng):
    """Return the id of the smallest-area containing jurisdiction box, else None.

    Half-open box on both axes: min <= v < max. Overlapping boxes -> smallest area
    wins; tie-break created_at ASC. (PRD §2.9 / calc smallest_box variant.)
    """
    if lat is None or lng is None:
        return None
    candidates = []
    for j in db.jurisdictions.values():
        if (j["min_lat"] <= lat < j["max_lat"] and
                j["min_lng"] <= lng < j["max_lng"]):
            candidates.append(j)
    if not candidates:
        return None

    def area(j):
        return (j["max_lat"] - j["min_lat"]) * (j["max_lng"] - j["min_lng"])

    winner = min(candidates, key=lambda j: (area(j), j.get("created_at", ""), j.get("_seq", 0)))
    return winner["id"]


def haversine_meters(lat1, lng1, lat2, lng2):
    """Great-circle distance in meters (PRD §2.9)."""
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlng / 2) ** 2)
    d = 2 * EARTH_RADIUS_METERS * math.asin(min(1, math.sqrt(a)))
    return d


def within_cluster_radius(lat, lng, center_lat, center_lng):
    """Inclusive boundary: distance <= 150m is eligible. No rounding before compare."""
    d = haversine_meters(lat, lng, center_lat, center_lng)
    return d <= CLUSTER_RADIUS_METERS


def find_sla_policy(category_id, priority):
    for p in db.sla_policies.values():
        if p["category_id"] == category_id and p["priority"] == priority:
            return p
    return None


def department_backlog(dept):
    """Recompute open_work_order_count + congested for a department (PRD §2.10).

    Count is WorkOrders of this dept whose status IN {OPEN, IN_PROGRESS, REOPENED}.
    congested = count >= backlog_threshold (inclusive). Mutation -> touch().
    """
    count = 0
    for wo in db.work_orders.values():
        if wo["department_id"] == dept["id"] and wo["status"] in ("OPEN", "IN_PROGRESS", "REOPENED"):
            count += 1
    dept["open_work_order_count"] = count
    dept["congested"] = count >= dept["backlog_threshold"]
    db.touch(dept)


def recompute_cluster_member_count(cluster):
    """member_count = #requests with cluster_id == cluster AND status == DUPLICATE.

    Excludes the canonical request. Mutation -> touch().
    """
    count = 0
    for r in db.service_requests.values():
        if r.get("cluster_id") == cluster["id"] and r["status"] == "DUPLICATE":
            count += 1
    cluster["member_count"] = count
    db.touch(cluster)


def avg_satisfaction(department_id):
    """Round-half-up mean of COMPLETED survey scores routed to this dept (PRD §2.11)."""
    scores = []
    for s in db.surveys.values():
        if s["status"] != "COMPLETED":
            continue
        req = db.service_requests.get(s["request_id"])
        if req is not None and req.get("department_id") == department_id:
            scores.append(s["score"])
    if not scores:
        return {"avg_score": None, "completed_count": 0}
    mean = Decimal(sum(scores)) / Decimal(len(scores))
    avg = mean.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {"avg_score": float(avg), "completed_count": len(scores)}


# ---- ServiceWindow overlap / routing-block semantics (PRD §3.8, calc window_overlap) ----

def windows_collide(a_type, a_start, a_end, b_start, b_end):
    """Admission overlap test for two same-type, same-scope windows.

    MAINTENANCE: closed intervals (touching endpoints collide).
    BLACKOUT:    half-open intervals (touching endpoints do NOT collide).
    """
    if a_type == "MAINTENANCE":
        return a_start <= b_end and b_start <= a_end
    return a_start < b_end and b_start < a_end


def maintenance_blocks(start, end, instant):
    """Point-in-closed-interval: starts_at <= instant <= ends_at."""
    return start <= instant <= end


def blackout_blocks(start, end, instant):
    """Point-in-half-open: starts_at <= instant < ends_at."""
    return start <= instant < end


def sla_breach_sweep():
    """Run the breach sweep at the current clock (PRD §3.9 / calc sla_breach_sweep).

    Walks ROUTED/IN_PROGRESS/REOPENED requests with sla_deadline_at set, in
    created_at ASC order. now > deadline (strict) -> breached. Idempotent
    auto-escalation per overdue hours. Returns (breached_request_ids, escalations_created).
    """
    now = db.CLOCK.now()
    breached_ids = []
    escalations_created = 0

    rows = db.ordered(
        db.service_requests,
        lambda r: r["status"] in ("ROUTED", "IN_PROGRESS", "REOPENED") and r.get("sla_deadline_at") is not None,
    )
    for r in rows:
        deadline = clock.parse_iso(r["sla_deadline_at"])
        if not (now > deadline):  # strict; at-deadline is NOT breached
            continue
        if not r.get("sla_breached"):
            r["sla_breached"] = True
            db.touch(r)
        else:
            # Already flagged breached previously; flag stays true. No re-touch
            # needed for the flag itself, but escalation creation continues below.
            pass

        overdue_seconds = (now - deadline).total_seconds()
        overdue_hours = math.floor(overdue_seconds / 3600)

        policy = find_sla_policy(r["category_id"], r["priority"])
        if policy is None:
            continue

        open_escs = [e for e in db.escalations.values()
                     if e["request_id"] == r["id"] and e["status"] == "OPEN"]
        has_open_tier2 = any(e["tier"] == "TIER2" for e in open_escs)
        has_any_open = len(open_escs) > 0

        if overdue_hours >= policy["escalation_tier2_hours"] and not has_open_tier2:
            _create_escalation(r["id"], "TIER2",
                               "SLA breached by {}h".format(overdue_hours))
            escalations_created += 1
        elif overdue_hours >= policy["escalation_tier1_hours"] and not has_any_open:
            _create_escalation(r["id"], "TIER1",
                               "SLA breached by {}h".format(overdue_hours))
            escalations_created += 1

        breached_ids.append(r["id"])

    return breached_ids, escalations_created


def _create_escalation(request_id, tier, reason):
    rec = {
        "request_id": request_id,
        "tier": tier,
        "reason": reason,
        "status": "OPEN",
        "resolved_by_role": None,
    }
    db.stamp_audit(rec)
    db.escalations[rec["id"]] = rec
    return rec
