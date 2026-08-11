"""Business logic: packing, anesthesia, double-booking, release/reduction,
reallocation selector, scoring, committee decisions, surgeon scorecard."""

import uuid
from datetime import timedelta
from decimal import Decimal

from db import db
from util import (
    iso_seconds,
    now_iso,
    parse_date,
    prime_overlap,
    round_dec,
    round_half_up_int,
)

BENCHMARK = {"MINOR": 45, "STANDARD": 90, "COMPLEX": 180}
TURNOVER_BASE = {"MINOR": 15, "STANDARD": 25, "COMPLEX": 40}
HYBRID_BONUS = 10
MIN_SLOT_MINUTES = 30
GRACE_MINUTES = 10
COMMITTEE_QUORUM = 3
REDUCTION_KEEP_PCT_NUM = 9  # floor(0.9 * original) = original*9//10
BIAS_MIN_HISTORY = 5
BIAS_WINDOW = 20
BIAS_CLAMP_LO = Decimal("0.800")
BIAS_CLAMP_HI = Decimal("1.250")


# ---------------------------------------------------------------------------
# generic record helpers
# ---------------------------------------------------------------------------

def new_common():
    ts = now_iso()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_insert_seq": db.next_insert_seq(),
    }


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] += 1


# ---------------------------------------------------------------------------
# case packing / scheduling primitives
# ---------------------------------------------------------------------------

def turnover_for(procedure_class, room):
    return TURNOVER_BASE[procedure_class] + (HYBRID_BONUS if room["is_hybrid"] else 0)


def scheduled_cases_of_block(block_id):
    cases = [
        c
        for c in db.cases.values()
        if c.get("block_id") == block_id and c["status"] == "SCHEDULED"
    ]
    cases.sort(key=lambda c: c.get("_sched_seq", 0))
    return cases


def pack_positions(block, cases):
    """Return {case_id: (start, end)} for the block's packed sequence."""
    pos = {}
    prev_end = None
    for i, c in enumerate(cases):
        if i == 0:
            start = block["start_minute"]
        else:
            start = prev_end + c["turnover_minutes"]
        end = start + c["predicted_duration_minutes"]
        pos[c["id"]] = (start, end)
        prev_end = end
    return pos


def recompute_block_metrics(block):
    """Recompute reserved/occupied from the block's SCHEDULED cases.

    reserved_minutes: span from block start through last scheduled end while
    DRAFT/ACTIVE (0 when none); frozen at RELEASED/REDUCED (do not call this
    for reserved after freeze — handled by transitions).
    """
    cases = scheduled_cases_of_block(block["id"])
    occupied = 0
    for i, c in enumerate(cases):
        occupied += c["predicted_duration_minutes"]
        if i > 0:
            occupied += c["turnover_minutes"]
    block["occupied_minutes"] = occupied
    # reserved_minutes is recomputed only while DRAFT/ACTIVE; RELEASED/REDUCED
    # keep the value frozen at their transition, and CANCELLED keeps its own.
    # Use the ACTUAL scheduled end of the last case (bumps leave gaps; the
    # sequence is not repacked here).
    if block["status"] in ("DRAFT", "ACTIVE"):
        if cases:
            block["reserved_minutes"] = (
                cases[-1]["scheduled_end_minute"] - block["start_minute"]
            )
        else:
            block["reserved_minutes"] = 0


def repack_block(block):
    """Recompute scheduled start/end of remaining SCHEDULED cases in place,
    preserving their relative scheduling order."""
    cases = scheduled_cases_of_block(block["id"])
    pos = pack_positions(block, cases)
    for c in cases:
        s, e = pos[c["id"]]
        c["scheduled_start_minute"] = s
        c["scheduled_end_minute"] = e


def anesthesia_covers(or_id, date, start, end_with_turnover):
    for cov in db.coverages.values():
        if (
            cov["or_id"] == or_id
            and cov["date"] == date
            and cov["status"] == "ACTIVE"
            and cov["start_minute"] <= start
            and end_with_turnover <= cov["end_minute"]
        ):
            return True
    return False


def surgeon_double_booked(surgeon_id, date, new_start, new_end_pad, exclude_case_id=None):
    """True when another SCHEDULED case of the surgeon on that date has a
    turnover-padded interval intersecting [new_start, new_end_pad).

    Padded intervals are half-open on the padded end, so touching at a padded
    boundary is allowed (PRD §3.4).
    """
    for c in db.cases.values():
        if c["id"] == exclude_case_id:
            continue
        if c["surgeon_id"] != surgeon_id or c["status"] != "SCHEDULED":
            continue
        if c.get("date") != date:
            continue
        e_start = c["scheduled_start_minute"]
        e_end_pad = c["scheduled_end_minute"] + (c.get("turnover_minutes") or 0)
        if new_start < e_end_pad and e_start < new_end_pad:
            return True
    return False


# ---------------------------------------------------------------------------
# surgeon scorecard
# ---------------------------------------------------------------------------

def recompute_surgeon_scorecard(surgeon):
    completed = [
        c
        for c in db.cases.values()
        if c["surgeon_id"] == surgeon["id"] and c["status"] == "COMPLETED"
    ]
    surgeon["completed_cases_count"] = len(completed)

    # duration bias
    if len(completed) < BIAS_MIN_HISTORY:
        surgeon["duration_bias_factor"] = 1.0
    else:
        ordered = sorted(
            completed,
            key=lambda c: (c["actual_end_minute"], c["created_at"], c["_insert_seq"]),
        )
        window = ordered[-BIAS_WINDOW:]
        ratios = [
            Decimal(c["actual_end_minute"] - c["actual_start_minute"])
            / Decimal(BENCHMARK[c["procedure_class"]])
            for c in window
        ]
        mean = sum(ratios) / Decimal(len(ratios))
        bias = round_dec(mean, 3)
        if bias < BIAS_CLAMP_LO:
            bias = BIAS_CLAMP_LO
        if bias > BIAS_CLAMP_HI:
            bias = BIAS_CLAMP_HI
        surgeon["duration_bias_factor"] = float(bias)

    # on-time rate over started first-cases
    started_first = [
        c
        for c in db.cases.values()
        if c["surgeon_id"] == surgeon["id"]
        and c.get("first_case_delay_minutes") is not None
    ]
    if not started_first:
        surgeon["on_time_rate_pct"] = 0.0
    else:
        on_time = sum(
            1 for c in started_first if c["first_case_delay_minutes"] <= GRACE_MINUTES
        )
        rate = round_dec(
            Decimal(100) * Decimal(on_time) / Decimal(len(started_first)), 2
        )
        surgeon["on_time_rate_pct"] = float(rate)


# ---------------------------------------------------------------------------
# block release / reduction (shared by endpoints, sweep, governance)
# ---------------------------------------------------------------------------

def create_slot(block, start_minute, minutes):
    rec = new_common()
    rec.update(
        {
            "block_id": block["id"],
            "or_id": block["or_id"],
            "date": block["date"],
            "start_minute": start_minute,
            "original_minutes": minutes,
            "remaining_minutes": minutes,
            "forfeited_minutes": 0,
            "status": "OPEN",
        }
    )
    db.slots[rec["id"]] = rec
    return rec


def release_block(block):
    """ACTIVE -> RELEASED. Returns list of newly created slots."""
    cases = scheduled_cases_of_block(block["id"])
    if cases:
        last_end = cases[-1]["scheduled_end_minute"]
    else:
        last_end = block["start_minute"]
    tail = block["end_minute"] - last_end
    new_slots = []
    if tail >= MIN_SLOT_MINUTES:
        new_slots.append(create_slot(block, last_end, tail))
    else:
        block["forfeited_minutes"] += tail
    # freeze reserved at occupied span
    block["reserved_minutes"] = (last_end - block["start_minute"]) if cases else 0
    block["status"] = "RELEASED"
    touch(block)
    return new_slots


def reduce_block(block):
    """ACTIVE -> REDUCED via committee decision. Returns (reduced?, new_slots)."""
    kept = (block["original_minutes"] * REDUCTION_KEEP_PCT_NUM) // 10
    new_end = block["start_minute"] + kept
    cases = scheduled_cases_of_block(block["id"])
    if cases:
        last_end = cases[-1]["scheduled_end_minute"]
        if last_end > new_end:
            return False, []  # skip: stays ACTIVE
    old_end = block["end_minute"]
    block["end_minute"] = new_end
    tail = old_end - new_end
    new_slots = []
    if tail >= MIN_SLOT_MINUTES:
        new_slots.append(create_slot(block, new_end, tail))
    else:
        block["forfeited_minutes"] += tail
    recompute_block_metrics(block)  # reserved recomputed (still ACTIVE here)
    block["status"] = "REDUCED"
    touch(block)
    return True, new_slots


def bump_case(case):
    """SCHEDULED -> BUMPED: clear schedule fields, retain block_id for audit."""
    case["scheduled_start_minute"] = None
    case["scheduled_end_minute"] = None
    case["status"] = "BUMPED"
    touch(case)


# ---------------------------------------------------------------------------
# reallocation selector (waterfall)
# ---------------------------------------------------------------------------

def latest_report_for_line(service_line_id):
    latest = None
    for r in db.reports.values():
        if r["service_line_id"] == service_line_id:
            if latest is None or (r["created_at"], r["_insert_seq"]) > (
                latest["created_at"],
                latest["_insert_seq"],
            ):
                latest = r
    return latest


def run_selector(slot):
    """Run the reallocation selector once over an OPEN slot.

    Returns the number of requests approved (0 or 1).
    """
    if slot["status"] != "OPEN":
        return 0
    pending = [
        r
        for r in db.requests.values()
        if r["slot_id"] == slot["id"] and r["status"] == "PENDING"
    ]
    if not pending:
        return 0

    eligible = []
    for req in pending:
        case = db.cases.get(req["case_id"])
        if case is None or case["status"] not in ("POSTED", "BUMPED"):
            continue
        if req["needed_minutes"] > slot["remaining_minutes"]:
            continue
        if not anesthesia_covers(
            slot["or_id"],
            slot["date"],
            slot["start_minute"],
            slot["start_minute"] + req["needed_minutes"],
        ):
            continue
        eligible.append(req)
    if not eligible:
        return 0

    def line_metrics(req):
        case = db.cases[req["case_id"]]
        surgeon = db.surgeons.get(case["surgeon_id"])
        line = db.service_lines.get(surgeon["service_line_id"]) if surgeon else None
        if line is None:
            return (None, None)
        report = latest_report_for_line(line["id"])
        pct = report["prime_time_utilization_pct"] if report else None
        return (line, pct)

    # tier1: line with no report, or latest report pct strictly below target
    tier1 = []
    for req in eligible:
        line, pct = line_metrics(req)
        if line is None or pct is None:
            tier1.append(req)
        elif Decimal(str(pct)) < Decimal(str(line["target_utilization_pct"])):
            tier1.append(req)
    pool = tier1 if tier1 else eligible

    def rank_key(req):
        line, pct = line_metrics(req)
        # lineless (no report) first, then pct ASC, then created_at ASC
        no_report = 0 if pct is None else 1
        pct_key = Decimal("0") if pct is None else Decimal(str(pct))
        return (no_report, pct_key, req["created_at"], req["_insert_seq"])

    winner = min(pool, key=rank_key)
    _approve_request(winner, slot)
    return 1


def _approve_request(req, slot):
    case = db.cases[req["case_id"]]
    room = db.rooms[slot["or_id"]]
    start = slot["start_minute"]
    case["block_id"] = None
    case["or_id"] = slot["or_id"]
    case["date"] = slot["date"]
    case["turnover_minutes"] = turnover_for(case["procedure_class"], room)
    case["scheduled_start_minute"] = start
    case["scheduled_end_minute"] = start + case["predicted_duration_minutes"]
    case["status"] = "SCHEDULED"
    case["_sched_seq"] = db.next_sched_seq()
    touch(case)

    req["status"] = "APPROVED"
    touch(req)

    slot["remaining_minutes"] -= req["needed_minutes"]
    if slot["remaining_minutes"] < MIN_SLOT_MINUTES:
        slot["forfeited_minutes"] += slot["remaining_minutes"]
        slot["remaining_minutes"] = 0
        slot["status"] = "CLAIMED"
    touch(slot)


# ---------------------------------------------------------------------------
# utilization scoring
# ---------------------------------------------------------------------------

def compute_report(line, period_start, period_end):
    blocks = [
        b
        for b in db.blocks.values()
        if b["service_line_id"] == line["id"]
        and b["status"] != "CANCELLED"
        and period_start <= parse_date(b["date"]) < period_end
    ]
    block_ids = {b["id"] for b in blocks}

    allocated_prime = sum(
        prime_overlap(
            b["start_minute"], b["start_minute"] + b["original_minutes"], b["date"]
        )
        for b in blocks
    )
    occupied_prime = 0
    for c in db.cases.values():
        if c.get("block_id") not in block_ids:
            continue
        if c["status"] not in ("SCHEDULED", "IN_PROGRESS", "COMPLETED"):
            continue
        occupied_prime += prime_overlap(
            c["scheduled_start_minute"], c["scheduled_end_minute"], c["date"]
        )

    if allocated_prime == 0:
        prime_pct = 0.0
    else:
        prime_pct = float(
            round_dec(
                Decimal(100) * Decimal(occupied_prime) / Decimal(allocated_prime), 2
            )
        )

    allocated_raw = sum(b["original_minutes"] for b in blocks)
    surgeon_ids = {
        s["id"] for s in db.surgeons.values() if s["service_line_id"] == line["id"]
    }
    occupied_raw = 0
    for c in db.cases.values():
        if c["surgeon_id"] not in surgeon_ids:
            continue
        if c["status"] not in ("SCHEDULED", "IN_PROGRESS", "COMPLETED"):
            continue
        if not c.get("date"):
            continue
        if not (period_start <= parse_date(c["date"]) < period_end):
            continue
        occupied_raw += c["scheduled_end_minute"] - c["scheduled_start_minute"]

    if allocated_raw == 0:
        raw_pct = 0.0
    else:
        raw_pct = float(
            round_dec(
                Decimal(100) * Decimal(occupied_raw) / Decimal(allocated_raw), 2
            )
        )

    return {
        "allocated_prime_minutes": allocated_prime,
        "occupied_prime_minutes": occupied_prime,
        "prime_time_utilization_pct": prime_pct,
        "raw_utilization_pct": raw_pct,
    }


def create_report(line, period_start, period_end, metrics):
    rec = {
        "id": str(uuid.uuid4()),
        "created_at": now_iso(),
        "_insert_seq": db.next_insert_seq(),
        "service_line_id": line["id"],
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
    }
    rec.update(metrics)
    db.reports[rec["id"]] = rec
    return rec


def create_review(line, report, period_end):
    rec = new_common()
    rec.update(
        {
            "service_line_id": line["id"],
            "utilization_report_id": report["id"],
            "period_end": period_end.isoformat(),
            "status": "OPEN",
            "decision": "NONE",
            "tally_reduce": 0,
            "tally_maintain": 0,
            "tally_abstain": 0,
        }
    )
    db.reviews[rec["id"]] = rec
    return rec


# ---------------------------------------------------------------------------
# committee decision application
# ---------------------------------------------------------------------------

def apply_reduce_decision(review):
    """Reduce every ACTIVE block of the line dated strictly after period_end."""
    period_end = parse_date(review["period_end"])
    for block in list(db.blocks.values()):
        if block["service_line_id"] != review["service_line_id"]:
            continue
        if block["status"] != "ACTIVE":
            continue
        if not (parse_date(block["date"]) > period_end):
            continue
        reduced, new_slots = reduce_block(block)
        if reduced:
            for slot in new_slots:
                run_selector(slot)


def recompute_review_tallies(review):
    rows = [v for v in db.votes.values() if v["review_id"] == review["id"]]
    review["tally_reduce"] = sum(1 for v in rows if v["vote"] == "REDUCE")
    review["tally_maintain"] = sum(1 for v in rows if v["vote"] == "MAINTAIN")
    review["tally_abstain"] = sum(1 for v in rows if v["vote"] == "ABSTAIN")
