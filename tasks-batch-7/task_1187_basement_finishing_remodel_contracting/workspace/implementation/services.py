"""Business logic: calculations (SCAFFOLD §1.3) and shared state helpers."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import stores, clock_date, clock_now, next_seq, now_ts, parse_date

TRADES = {
    "DEMOLITION", "FRAMING", "PLUMBING", "ELECTRICAL", "HVAC",
    "INSULATION", "DRYWALL", "FLOORING", "PAINT", "GENERAL",
}
ROUGH_IN_TRADES = {"PLUMBING", "ELECTRICAL", "HVAC"}

PROJECT_TERMINAL = {"COMPLETED", "CANCELLED"}
PACKAGE_TERMINAL = {"APPROVED", "SUPERSEDED"}
PERMIT_TERMINAL = {"CLOSED", "EXPIRED"}
CO_TERMINAL = {"APPROVED", "REJECTED", "WITHDRAWN", "SUPERSEDED"}
INSPECTION_TERMINAL = {"PASSED", "FAILED", "CANCELLED"}
CLAIM_TERMINAL = {"APPROVED", "DENIED"}
PHASE_TERMINAL = {"COMPLETED", "CANCELLED"}

# States in which allowance lines / change orders may be created (PRD §2.7):
# INTAKE..IN_PROGRESS excluding SUSPENDED.
ALLOWANCE_CO_STATES = {"INTAKE", "ASSESSMENT", "DESIGN", "PERMITTING", "SCHEDULING", "IN_PROGRESS"}

NOISE_DB_LIMIT = 65
STRIKE_WINDOW_DAYS = 14
STRIKE_SUSPEND_THRESHOLD = 3
DRYWALL_BUFFER_DAYS = 2
MAX_DAILY_CREW = 4
PERMIT_VALID_DAYS = 180
FULL_COVERAGE_DAYS = 365
WARRANTY_TERM_DAYS = 730
RECURRENCE_DELTA_LBS = Decimal("1.5")
MAX_AWARD_CENTS = 200000
MARKUP = Decimal("1.15")
CONTINGENCY_PCT = Decimal("0.10")
EGRESS_NET_CLEAR_MIN_SQFT = Decimal("5.7")
EGRESS_SILL_MAX_IN = 44


def dec(x):
    return Decimal(str(x))


def rhu(d):
    """Round half up to whole cents (PRD §2.9)."""
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def touch(entity):
    """Every mutation bumps version and refreshes updated_at (PRD §2.4)."""
    entity["version"] += 1
    entity["updated_at"] = now_ts()


# ---------------------------------------------------------------------------
# moisture_risk_score (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------

def moisture_risk(kind, slab, rh, efflorescence, grading):
    if kind == "SCREENING":
        slab_pts = 0 if dec(slab) <= Decimal("3.0") else (25 if dec(slab) <= Decimal("5.0") else 50)
        rh_pts = 0 if dec(rh) <= Decimal("60") else (15 if dec(rh) <= Decimal("70") else 30)
        low_max, mod_max = 24, 49
    else:  # VERIFICATION
        slab_pts = 0 if dec(slab) <= Decimal("2.0") else (25 if dec(slab) <= Decimal("4.0") else 50)
        rh_pts = 0 if dec(rh) <= Decimal("55") else (15 if dec(rh) <= Decimal("65") else 30)
        low_max, mod_max = 15, 39
    score = slab_pts + rh_pts + (20 if efflorescence else 0) + (15 if grading else 0)
    band = "LOW" if score <= low_max else ("MODERATE" if score <= mod_max else "HIGH")
    return score, band


def band_acceptable(kind, band):
    """SCREENING accepts LOW|MODERATE; VERIFICATION accepts only LOW."""
    if kind == "SCREENING":
        return band in ("LOW", "MODERATE")
    return band == "LOW"


# ---------------------------------------------------------------------------
# egress_ceiling_compliance (R1, R2, R3)
# ---------------------------------------------------------------------------

def egress_r1(bedroom_count, windows):
    ok = sum(
        1
        for w in windows
        if dec(w["net_clear_sqft"]) >= EGRESS_NET_CLEAR_MIN_SQFT
        and dec(w["sill_height_in"]) <= EGRESS_SILL_MAX_IN
    )
    return ok >= bedroom_count


def ceiling_r2_r3(finished_area_sqft, low_area_sqft, prohibited_area_sqft):
    r2 = (finished_area_sqft - low_area_sqft - prohibited_area_sqft) * 2 >= finished_area_sqft
    r3 = prohibited_area_sqft == 0
    return r2 and r3


# ---------------------------------------------------------------------------
# change_order_pricing (pinned per-line rounding order)
# ---------------------------------------------------------------------------

def items_total_cents(scope_items):
    total = 0
    for item in scope_items:
        total += rhu(dec(item["qty"]) * dec(item["unit_cost_cents"]) * MARKUP)
    return total


def price_delta(kind, scope_items, allowance_draws):
    items = items_total_cents(scope_items)
    draws = sum(d["amount_cents"] for d in allowance_draws)
    if kind == "ADD":
        return items - draws, items, draws
    return -items, items, draws


# ---------------------------------------------------------------------------
# AllowanceLine derived fields + project_price
# ---------------------------------------------------------------------------

def line_remaining(line):
    return line["budgeted_cents"] - line["reserved_cents"] - line["drawn_cents"] - line["actual_cents"]


def line_variance(line):
    if not line["selected"]:
        return None
    return line["actual_cents"] + line["drawn_cents"] - line["budgeted_cents"]


def project_lines(project_id):
    return [l for l in stores["allowance_lines"].values() if l["project_id"] == project_id]


def project_price(project):
    lines = project_lines(project["id"])
    approved_delta = sum(
        co["price_delta_cents"]
        for co in stores["change_orders"].values()
        if co["project_id"] == project["id"] and co["status"] == "APPROVED"
    )
    variance = sum(line_variance(l) for l in lines if l["selected"])
    unselected = [l for l in lines if not l["selected"]]
    variant = "FINAL" if (len(lines) == 0 or len(unselected) == 0) else "PROVISIONAL"
    price = project["base_contract_cents"] + approved_delta + variance
    if variant == "PROVISIONAL":
        contingency = rhu(CONTINGENCY_PCT * dec(sum(l["budgeted_cents"] - l["drawn_cents"] for l in unselected)))
        price += contingency
    return price, variant


# ---------------------------------------------------------------------------
# cleanup_strike_escalation
# ---------------------------------------------------------------------------

def compute_violation(log):
    return (
        (not log["containment_intact"])
        or (not log["cleanup_completed"])
        or dec(log["noise_db_max"]) > NOISE_DB_LIMIT
    )


def strike_count(project):
    """Violation logs with work_date in [today-13, today]; after a resume only
    logs created after last_resumed_at count (SCAFFOLD §1.3)."""
    today = clock_date()
    window_start = today - timedelta(days=STRIKE_WINDOW_DAYS - 1)
    count = 0
    for log in stores["site_logs"].values():
        if log["project_id"] != project["id"] or not log["violation"]:
            continue
        d = parse_date(log["work_date"])
        if d is None or d < window_start or d > today:
            continue
        # "Created after the last resume" is decided by insertion sequence,
        # not raw timestamps: the logical clock does not advance between
        # requests, so pre-resume logs, the resume, and post-resume logs can
        # all share one clock instant (PRD §3.7).
        if project["last_resumed_at"] is not None and log["_seq"] <= project["_last_resumed_seq"]:
            continue
        count += 1
    return count


# ---------------------------------------------------------------------------
# phase_sequence_gate / zone_schedule_overlap / daily_crew_capacity
# ---------------------------------------------------------------------------

def project_phases(project_id, include_cancelled=False):
    out = []
    for p in stores["work_phases"].values():
        if p["project_id"] != project_id:
            continue
        if not include_cancelled and p["status"] == "CANCELLED":
            continue
        out.append(p)
    return out


def creates_cycle(project_id, new_id, predecessor_ids):
    """Adding edges predecessor -> new must keep the DAG acyclic. A fresh node
    has no outgoing edges, so a cycle can only arise through existing edges."""
    succ = {}
    for p in project_phases(project_id, include_cancelled=True):
        for pred in p["predecessor_ids"]:
            succ.setdefault(pred, []).append(p["id"])
    # DFS from new node through successor edges looking for any predecessor.
    stack = [new_id]
    seen = set()
    pred_set = set(predecessor_ids)
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        if cur in pred_set:
            return True
        stack.extend(succ.get(cur, []))
    return False


def zone_conflict(project_id, zone, trade, start_d, end_d):
    """Half-open interval overlap plus the DRYWALL two-day dust buffer."""
    for p in project_phases(project_id):
        if p["zone"] != zone:
            continue
        ps = parse_date(p["start_date"])
        pe = parse_date(p["end_date"])
        if ps is None or pe is None:
            continue
        # Overlap: a.start < b.end AND b.start < a.end; touching endpoints OK.
        if start_d < pe and ps < end_d:
            return True
        if p["trade"] == "DRYWALL":
            buffer = timedelta(days=DRYWALL_BUFFER_DAYS)
            if start_d >= pe and start_d < pe + buffer:
                return True
            if ps >= end_d and ps < end_d + buffer:
                return True
    return False


def crew_capacity_exceeded(project_id, start_d, end_d, crew_count):
    """Aggregate per-day crew over the whole project must stay <= 4 (inclusive)."""
    d = start_d
    while d < end_d:
        total = crew_count
        for p in project_phases(project_id):
            ps = parse_date(p["start_date"])
            pe = parse_date(p["end_date"])
            if ps is None or pe is None:
                continue
            if ps <= d < pe:
                total += p["crew_count"]
        if total > MAX_DAILY_CREW:
            return True
        d += timedelta(days=1)
    return False


def promote_successors(project, completed_phase):
    """Successors whose predecessors are all COMPLETED promote PLANNED->READY,
    processed in created_at ascending order (never id)."""
    phases = sorted(project_phases(project["id"]), key=lambda p: (p["created_at"], p["_seq"]))
    for s in phases:
        if completed_phase["id"] not in s["predecessor_ids"]:
            continue
        if s["status"] != "PLANNED":
            continue
        preds = [stores["work_phases"].get(pid) for pid in s["predecessor_ids"]]
        if all(pr is not None and pr["status"] == "COMPLETED" for pr in preds):
            s["status"] = "READY"
            s["pre_block_status"] = None
            touch(s)


# ---------------------------------------------------------------------------
# Change-order draw helpers
# ---------------------------------------------------------------------------

def release_draws(co):
    for draw in co["allowance_draws"]:
        line = stores["allowance_lines"].get(draw["allowance_line_id"])
        if line is not None:
            line["reserved_cents"] -= draw["amount_cents"]
            touch(line)


def reserve_draws(co):
    for draw in co["allowance_draws"]:
        line = stores["allowance_lines"].get(draw["allowance_line_id"])
        if line is not None:
            line["reserved_cents"] += draw["amount_cents"]
            touch(line)


def supersede_proposed(project):
    """Every existing PROPOSED change order on the project -> SUPERSEDED with
    draws released (ChangeOrder machine)."""
    for co in stores["change_orders"].values():
        if co["project_id"] == project["id"] and co["status"] == "PROPOSED":
            release_draws(co)
            co["status"] = "SUPERSEDED"
            touch(co)


# ---------------------------------------------------------------------------
# Project-level cascades
# ---------------------------------------------------------------------------

def suspend_project(project):
    """IN_PROGRESS -> SUSPENDED: block active phases, cancel requested
    inspections, bump project version (Project machine)."""
    project["status"] = "SUSPENDED"
    touch(project)
    for p in project_phases(project["id"]):
        if p["status"] in ("IN_PROGRESS", "READY"):
            p["pre_block_status"] = p["status"]
            p["status"] = "BLOCKED"
            touch(p)
    for ins in stores["inspections"].values():
        if ins["project_id"] == project["id"] and ins["status"] == "REQUESTED":
            ins["status"] = "CANCELLED"
            touch(ins)


def resume_project(project):
    """SUSPENDED -> IN_PROGRESS: re-anchor strike window, restore BLOCKED
    phases to their captured pre_block_status (Project machine)."""
    project["last_resumed_at"] = now_ts()
    project["_last_resumed_dt"] = clock_now()
    project["_last_resumed_seq"] = next_seq()
    project["status"] = "IN_PROGRESS"
    touch(project)
    for p in project_phases(project["id"]):
        if p["status"] == "BLOCKED":
            p["status"] = p["pre_block_status"] if p["pre_block_status"] in ("READY", "IN_PROGRESS") else "READY"
            p["pre_block_status"] = None
            touch(p)


def cancel_project(project):
    """-> CANCELLED: non-terminal phases -> CANCELLED; PROPOSED change orders
    -> WITHDRAWN with draws released (Project machine)."""
    project["status"] = "CANCELLED"
    touch(project)
    for p in project_phases(project["id"], include_cancelled=True):
        if p["status"] not in PHASE_TERMINAL:
            p["status"] = "CANCELLED"
            p["pre_block_status"] = None
            touch(p)
    for co in stores["change_orders"].values():
        if co["project_id"] == project["id"] and co["status"] == "PROPOSED":
            release_draws(co)
            co["status"] = "WITHDRAWN"
            touch(co)


def advance_project(project, to_status):
    project["status"] = to_status
    touch(project)


# ---------------------------------------------------------------------------
# warranty_coverage
# ---------------------------------------------------------------------------

def baseline_assessment(project_id):
    """The most recently created ACCEPTED assessment (created_at wins)."""
    accepted = [
        a for a in stores["assessments"].values()
        if a["project_id"] == project_id and a["status"] == "ACCEPTED"
    ]
    if not accepted:
        return None
    return max(accepted, key=lambda a: (a["created_at"], a["_seq"]))


def warranty_coverage(project, certificate, claim_created_date, fresh_slab):
    elapsed = (claim_created_date - certificate["_warranty_start_date"]).days
    if elapsed < 0:
        elapsed = 0
    base = baseline_assessment(project["id"])
    recurrence = False
    if base is not None:
        recurrence = dec(fresh_slab) >= dec(base["slab_moisture_lbs"]) + RECURRENCE_DELTA_LBS
    if recurrence:
        coverage = 100
    elif elapsed <= FULL_COVERAGE_DAYS:
        coverage = 100
    elif elapsed <= WARRANTY_TERM_DAYS:
        coverage = 50
    else:
        coverage = 50
    return recurrence, coverage


def award_for(claimed_cents, coverage_pct):
    return rhu(dec(min(claimed_cents, MAX_AWARD_CENTS)) * dec(coverage_pct) / Decimal("100"))


# ---------------------------------------------------------------------------
# Clock sweeps (PRD §2.5)
# ---------------------------------------------------------------------------

def expiry_sweep():
    today = clock_date()
    for permit in stores["permits"].values():
        if permit["status"] != "ISSUED":
            continue
        project = stores["projects"].get(permit["project_id"])
        if project is not None and project["status"] == "COMPLETED":
            continue
        if permit["_issued_date"] is not None and today > permit["_issued_date"] + timedelta(days=PERMIT_VALID_DAYS):
            permit["status"] = "EXPIRED"
            touch(permit)
    for cert in stores["certificates"].values():
        if cert["status"] != "ACTIVE":
            continue
        if today > cert["_warranty_end_date"]:
            cert["status"] = "EXPIRED"
            touch(cert)
