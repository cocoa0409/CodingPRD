"""Domain services: derived-state recomputation and cascade side effects.

Every recompute/cascade is a genuine mutation of the affected resource —
its own updated_at refresh and version bump (PRD §2.4 / §2.10).
"""

import db
from db import touch
from services import calc


# --- Lookups -------------------------------------------------------------------
def stops_of_tour(tour_id):
    return [s for s in db.stops.values() if s["tour_id"] == tour_id]


def perfs_of_stop(stop_id):
    return [p for p in db.performances.values() if p["stop_id"] == stop_id]


def checks_of_stop(stop_id):
    return [c for c in db.tech_checks.values() if c["stop_id"] == stop_id]


def crew_of_stop(stop_id):
    return [c for c in db.crew_calls.values() if c["stop_id"] == stop_id]


def per_diems_of_stop(stop_id):
    return [p for p in db.per_diems.values() if p["stop_id"] == stop_id]


def settlement_of_stop(stop_id):
    for s in db.settlements.values():
        if s["stop_id"] == stop_id:
            return s
    return None


def tracks_of_tour(tour_id):
    return [t for t in db.tracks.values() if t["tour_id"] == tour_id]


def coverages_of_track(track_id):
    return [c for c in db.coverages.values() if c["track_id"] == track_id]


def coverages_of_member(cast_id):
    return [c for c in db.coverages.values() if c["cast_member_id"] == cast_id]


def principal_track_of(tour_id, cast_id):
    for t in tracks_of_tour(tour_id):
        if t.get("principal_member_id") == cast_id:
            return t
    return None


# --- Derived state ----------------------------------------------------------------
def recompute_compliance(stop):
    """compliance_status: PENDING (no checks) | NON_COMPLIANT (any FAIL) |
    COMPLIANT (>=1 check, all PASS|WAIVED) | IN_PROGRESS (>=1 PENDING, none FAIL).
    Cascade: FAIL on a READY stop revokes certification (READY -> ADVANCED)."""
    checks = checks_of_stop(stop["id"])
    statuses = [c["status"] for c in checks]
    if not statuses:
        new = "PENDING"
    elif any(s == "FAIL" for s in statuses):
        new = "NON_COMPLIANT"
    elif all(s in ("PASS", "WAIVED") for s in statuses):
        new = "COMPLIANT"
    else:
        new = "IN_PROGRESS"
    stop["compliance_status"] = new
    if new == "NON_COMPLIANT" and stop["booking_status"] == "READY":
        stop["booking_status"] = "ADVANCED"  # certification revoked (cascade)
    touch(stop)


def recompute_track(track):
    """available_covers = STANDBY coverages whose cast member is CONTRACTED.
    exposed = available_covers < required_covers (required_covers=0: never)."""
    avail = 0
    for c in coverages_of_track(track["id"]):
        if c["status"] != "STANDBY":
            continue
        member = db.cast_members.get(c["cast_member_id"])
        if member is not None and member["status"] == "CONTRACTED":
            avail += 1
    track["available_covers"] = avail
    track["exposed"] = False if track["required_covers"] == 0 else avail < track["required_covers"]
    touch(track)


# --- Stop lifecycle cascades ---------------------------------------------------------
def auto_close_stop_if_resolved(stop):
    """Bubble-up: every performance resolved (>= 1 exists) -> CLOSED and the
    settlement is auto-created in DRAFT with system_gross frozen over PLAYED."""
    perfs = perfs_of_stop(stop["id"])
    if not perfs:
        return
    if all(p["status"] in ("PLAYED", "CANCELLED") for p in perfs):
        if stop["booking_status"] in ("READY", "PLAYING"):
            stop["booking_status"] = "CLOSED"
            touch(stop)
            system_gross = sum(p["gross_cents"] for p in perfs if p["status"] == "PLAYED")
            rec = db.new_record()
            rec.update({
                "stop_id": stop["id"],
                "status": "DRAFT",
                "system_gross_cents": system_gross,
                "audited_gross_cents": None,
                "taxes_cents": None,
                "levies_cents": None,
                "adjusted_gross_cents": None,
                "venue_payment_cents": None,
                "producer_share_cents": None,
                "royalty_cents": None,
                "submitted_by": None,
                "approved_by": None,
                "dispute_reason": None,
            })
            db.settlements[rec["id"]] = rec


def wrap_stop(stop, tour):
    """CLOSED -> WRAPPED weekly wrap (calc_weekly_wrap). Settlement is PAID.
    Recoup flag is re-evaluated only AFTER this stop's totals post."""
    settlement = settlement_of_stop(stop["id"])
    crews = crew_of_stop(stop["id"])
    pds = per_diems_of_stop(stop["id"])
    stop_costs = (
        sum(c["total_pay_cents"] for c in crews if c["status"] == "SETTLED")
        + sum(c["cancellation_penalty_cents"] for c in crews if c["status"] == "CANCELLED")
        + sum(p["total_cents"] for p in pds if p["status"] in ("ISSUED", "PAID"))
    )
    producer_net = (settlement["producer_share_cents"]
                    - settlement["royalty_cents"] - stop_costs)
    stop["wrapped_total_cents"] = (settlement["venue_payment_cents"]
                                   + settlement["royalty_cents"] + stop_costs)
    stop["booking_status"] = "WRAPPED"
    touch(stop)
    tour["budget_committed_cents"] -= stop["guarantee_cents"]
    tour["budget_spent_cents"] += stop["wrapped_total_cents"]
    tour["cumulative_producer_net_cents"] += producer_net
    # >= boundary flips; flips only here, AFTER this stop's royalty was fixed.
    tour["recouped"] = tour["cumulative_producer_net_cents"] >= tour["capitalization_cents"]
    touch(tour)


def cancel_stop(stop, tour):
    """-> CANCELLED. Penalty from the logical clock; budget buckets shift;
    cascades to SCHEDULED performances and POSTED crew calls (whose penalties
    also land in budget_spent_cents)."""
    import util  # local import to avoid a cycle at module import time
    prior = stop["booking_status"]
    pws = util.parse_iso_date(stop["play_week_start"], "play_week_start")
    penalty = calc.calc_cancellation_penalty(prior, stop["guarantee_cents"], pws,
                                             db.logical_clock["dt"])
    stop["cancellation_penalty_cents"] = penalty
    tour_touched = False
    if prior in ("CONTRACTED", "ADVANCED", "READY"):
        tour["budget_committed_cents"] -= stop["guarantee_cents"]
        tour["budget_spent_cents"] += penalty
        tour_touched = True
    for p in perfs_of_stop(stop["id"]):
        if p["status"] == "SCHEDULED":
            p["status"] = "CANCELLED"
            touch(p)
    crew_pen_total = 0
    for c in crew_of_stop(stop["id"]):
        if c["status"] == "POSTED":
            sched = util.parse_iso_datetime(c["scheduled_start"], "scheduled_start")
            c["cancellation_penalty_cents"] = calc.crew_cancellation_penalty(
                c["lines"], sched, db.logical_clock["dt"])
            c["status"] = "CANCELLED"
            touch(c)
            crew_pen_total += c["cancellation_penalty_cents"]
    if crew_pen_total:
        tour["budget_spent_cents"] += crew_pen_total
        tour_touched = True
    stop["booking_status"] = "CANCELLED"
    touch(stop)
    if tour_touched:
        touch(tour)


# --- Injury / coverage cascades --------------------------------------------------------
def select_coverage(track):
    """calc_coverage_selection: STANDBY + member CONTRACTED; UNDERSTUDY before
    SWING, then priority_rank ASC, then created_at ASC (insertion order)."""
    pool = []
    for c in coverages_of_track(track["id"]):
        if c["status"] != "STANDBY":
            continue
        member = db.cast_members.get(c["cast_member_id"])
        if member is not None and member["status"] == "CONTRACTED":
            pool.append(c)
    pool.sort(key=lambda c: (0 if c["kind"] == "UNDERSTUDY" else 1,
                             c["priority_rank"], c["_seq"]))
    return pool[0] if pool else None


def run_injury_cascade(member, notes):
    """Atomic fork at creation. Returns the created InjuryEvent record.
    Caller has already validated: member CONTRACTED, no open COVERED injury,
    and (for the empty-pool branch) that the member is principal of some track."""
    track = principal_track_of(member["tour_id"], member["id"])
    selected = select_coverage(track) if track is not None else None

    rec = db.new_record()
    rec.update({
        "cast_member_id": member["id"],
        "notes": notes,
        "status": "COVERED" if selected is not None else "REPLACED",
        "covered_by_coverage_id": selected["id"] if selected is not None else None,
    })
    db.injuries[rec["id"]] = rec

    tracks_to_recompute = set()
    if selected is not None:
        # COVERED branch: member ON_LEAVE; member's own coverages on OTHER
        # tracks SUSPENDED; selected coverage ACTIVATED.
        member["status"] = "ON_LEAVE"
        touch(member)
        for c in coverages_of_member(member["id"]):
            if c["status"] in ("STANDBY", "ACTIVATED") and c["track_id"] != track["id"]:
                c["status"] = "SUSPENDED"
                touch(c)
                tracks_to_recompute.add(c["track_id"])
        selected["status"] = "ACTIVATED"
        touch(selected)
        tracks_to_recompute.add(track["id"])
    else:
        # REPLACED branch: CONTRACTED -> REPLACED directly; no activation; the
        # principal's track keeps pointing at the REPLACED member.
        member["status"] = "REPLACED"
        touch(member)
        if track is not None:
            tracks_to_recompute.add(track["id"])
        # A REPLACED member's own STANDBY coverages no longer count as
        # available (member not CONTRACTED) — refresh those benches too.
        for c in coverages_of_member(member["id"]):
            tracks_to_recompute.add(c["track_id"])

    for tid in tracks_to_recompute:
        recompute_track(db.tracks[tid])
    return rec


def resolve_injury(injury):
    """COVERED -> RESOLVED: member returns CONTRACTED; the recorded ACTIVATED
    coverage returns STANDBY; the member's SUSPENDED coverages restore."""
    member = db.cast_members[injury["cast_member_id"]]
    injury["status"] = "RESOLVED"
    touch(injury)
    if member["status"] == "ON_LEAVE":
        member["status"] = "CONTRACTED"
        touch(member)
    tracks_to_recompute = set()
    cov_id = injury.get("covered_by_coverage_id")
    if cov_id:
        cov = db.coverages.get(cov_id)
        if cov is not None and cov["status"] in ("ACTIVATED", "SUSPENDED"):
            cov["status"] = "STANDBY"
            touch(cov)
            tracks_to_recompute.add(cov["track_id"])
    for c in coverages_of_member(member["id"]):
        if c["status"] == "SUSPENDED":
            c["status"] = "STANDBY"
            touch(c)
            tracks_to_recompute.add(c["track_id"])
    for tid in tracks_to_recompute:
        recompute_track(db.tracks[tid])
