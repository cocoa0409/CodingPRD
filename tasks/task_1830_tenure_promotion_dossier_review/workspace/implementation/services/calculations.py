"""Calculation rules (SCAFFOLD §1.3 / PRD §3) — exact decimal arithmetic,
round-half-up, pinned evaluation orders."""
from datetime import timedelta, timezone, datetime
from decimal import Decimal

from db import db
from util import D, round_half_up, ceil_decimal, parse_dt, dt_to_date, add_months, as_number

# --- dossier completeness / strength (PRD §3.2) ---
TEACHING_MIN = 2
RESEARCH_MIN = 3
SERVICE_MIN = 1
PEER_REVIEWED_RESEARCH_MIN = 1
TEACHING_WEIGHT = D("0.30")
RESEARCH_WEIGHT = D("0.50")
SERVICE_WEIGHT = D("0.20")
RATIO_CAP = D("2.0")

# --- clock (PRD §3.1/§3.3) ---
DAY_COUNT_TOTAL = 2192  # round_half_up(72 * 30.4375)
MAX_EXTENSION_DAYS = 730

# --- letters (PRD §3.4) ---
MIN_EXTERNAL_LETTERS = 3
MAX_ACTIVE_ASSIGNMENTS = 2

# --- tally (PRD §2.9/§3.6) ---
SUPERMAJORITY_RATIO = D("0.6667")

# --- score (PRD §3.6) ---
DEPT_WEIGHT = D("0.25")
COLLEGE_WEIGHT = D("0.35")
UNIV_WEIGHT = D("0.40")
FAIL_CAP = D("0.49")
GRANT_THRESHOLD = D("0.60")

# --- windows (PRD §3.7) ---
NOTIFICATION_WINDOW_DAYS = 10
APPEAL_WINDOW_DAYS = 30
RETENTION_DAYS = 2555
RESPONSE_DEADLINE_DAYS = 14


def submitted_items(case_id):
    return [
        i for i in db["dossier_items"].values()
        if i["case_id"] == case_id and i["status"] == "SUBMITTED"
    ]


def dossier_complete(case_id) -> bool:
    """calculation dossier_completeness: SUBMITTED-only counts vs minima."""
    items = submitted_items(case_id)
    t = sum(1 for i in items if i["category"] == "TEACHING")
    r = sum(1 for i in items if i["category"] == "RESEARCH")
    s = sum(1 for i in items if i["category"] == "SERVICE")
    pr = sum(1 for i in items if i["category"] == "RESEARCH" and i.get("is_peer_reviewed"))
    return t >= TEACHING_MIN and r >= RESEARCH_MIN and s >= SERVICE_MIN and pr >= PEER_REVIEWED_RESEARCH_MIN


def dossier_strength_index(case_id) -> float:
    """calculation dossier_strength_index — PINNED order: each ratio rounded to
    3dp first, then weighted and summed, total rounded to 4dp."""
    items = submitted_items(case_id)
    counts = {
        "TEACHING": sum(1 for i in items if i["category"] == "TEACHING"),
        "RESEARCH": sum(1 for i in items if i["category"] == "RESEARCH"),
        "SERVICE": sum(1 for i in items if i["category"] == "SERVICE"),
    }
    total = Decimal(0)
    for cat, minimum, weight in (
        ("TEACHING", TEACHING_MIN, TEACHING_WEIGHT),
        ("RESEARCH", RESEARCH_MIN, RESEARCH_WEIGHT),
        ("SERVICE", SERVICE_MIN, SERVICE_WEIGHT),
    ):
        ratio = D(counts[cat]) / D(minimum)
        if ratio > RATIO_CAP:
            ratio = RATIO_CAP
        ratio = round_half_up(ratio, 3)          # pinned: round ratio first
        total += ratio * weight                   # exact decimal arithmetic
    return as_number(round_half_up(total, 4))


def compute_mandatory_review_date(tenure_clock_start, clock_policy, extension_days) -> datetime:
    """calculation mandatory_review_date — date granularity (00:00:00Z)."""
    base = dt_to_date(parse_dt(tenure_clock_start))
    if clock_policy == "ANNIVERSARY":
        base_date = add_months(base, 72)
    else:  # DAY_COUNT
        base_date = base + timedelta(days=DAY_COUNT_TOTAL)
    result = base_date + timedelta(days=int(extension_days))
    return datetime(result.year, result.month, result.day, tzinfo=timezone.utc)


def _ext_interval_dates(ext):
    return dt_to_date(parse_dt(ext["interval_start"])), dt_to_date(parse_dt(ext["interval_end"]))


def merged_union_days(intervals) -> int:
    """calculation extension_day_merge: half-open [start, end) intervals merged
    over overlap OR touch; union length summed in whole days."""
    pts = sorted(intervals)
    total = 0
    cur_s = cur_e = None
    for s, e in pts:
        if cur_s is None:
            cur_s, cur_e = s, e
        elif s <= cur_e:  # overlapping or touching -> coalesce
            if e > cur_e:
                cur_e = e
        else:
            total += (cur_e - cur_s).days
            cur_s, cur_e = s, e
    if cur_s is not None:
        total += (cur_e - cur_s).days
    return total


def approved_extension_days(case_id) -> int:
    intervals = [
        _ext_interval_dates(e) for e in db["clock_extensions"].values()
        if e["case_id"] == case_id and e["status"] == "APPROVED"
    ]
    return merged_union_days(intervals)


def extension_overlaps_approved(case_id, start_d, end_d) -> bool:
    """calculation clock_extension_overlap: HALF-OPEN semantics — touching does
    NOT count as overlap."""
    for e in db["clock_extensions"].values():
        if e["case_id"] != case_id or e["status"] != "APPROVED":
            continue
        s, en = _ext_interval_dates(e)
        if start_d < en and s < end_d:
            return True
    return False


def usable_letter_count(case_id) -> int:
    """calculation usable_letter_count: LETTER_RECEIVED invitations only."""
    return sum(
        1 for i in db["invitations"].values()
        if i["case_id"] == case_id and i["status"] == "LETTER_RECEIVED"
    )


def reviewer_capacity_ok(reviewer_id, new_start, new_end) -> bool:
    """calculation reviewer_capacity: CLOSED semantics — touching counts as
    overlap; >= 2 overlapping SOLICITED/ACCEPTED assignments rejects."""
    active = [
        i for i in db["invitations"].values()
        if i["reviewer_id"] == reviewer_id and i["status"] in ("SOLICITED", "ACCEPTED")
    ]
    overlaps = 0
    for i in active:
        s = parse_dt(i["review_window_start"])
        e = parse_dt(i["review_window_end"])
        if s <= new_end and new_start <= e:
            overlaps += 1
    return overlaps < MAX_ACTIVE_ASSIGNMENTS


# ---------------------------------------------------------------------------
# Vote tally (PRD §2.9/§3.6, calculation vote_tally)
# ---------------------------------------------------------------------------

def cast_votes(round_id):
    return [
        v for v in db["votes"].values()
        if v["round_id"] == round_id and v["status"] == "CAST"
    ]


def recompute_round_tallies(round_rec):
    """Recompute live tallies. Pinned order: M (fixed at open) -> R -> eligible
    -> quorum_required -> quorum_met. RECUSE never counts as cast; ABSTAIN
    counts toward votes_cast but never toward yes_percentage's denominator."""
    committee = db["committees"].get(round_rec["committee_id"])
    votes = cast_votes(round_rec["id"])
    recuse = sum(1 for v in votes if v["ballot"] == "RECUSE")
    yes = sum(1 for v in votes if v["ballot"] == "YES")
    no = sum(1 for v in votes if v["ballot"] == "NO")
    abstain = sum(1 for v in votes if v["ballot"] == "ABSTAIN")
    round_rec["recusal_count"] = recuse
    m = round_rec.get("active_member_count")
    if m is not None:
        eligible = m - recuse
        round_rec["eligible_voter_count"] = eligible
        frac = D(committee["quorum_fraction"]) if committee else D("0.5")
        round_rec["quorum_required"] = ceil_decimal(frac * eligible)
    round_rec["yes_count"] = yes
    round_rec["no_count"] = no
    round_rec["abstain_count"] = abstain
    round_rec["votes_cast"] = yes + no + abstain
    eligible = round_rec.get("eligible_voter_count")
    quorum_required = round_rec.get("quorum_required")
    round_rec["quorum_met"] = bool(
        eligible is not None and quorum_required is not None
        and round_rec["votes_cast"] >= quorum_required and eligible >= 1
    )


def compute_yes_percentage(round_rec):
    """round_half_up(yes / (yes + no), 4); null when yes + no == 0."""
    yes = round_rec["yes_count"]
    no = round_rec["no_count"]
    if yes + no == 0:
        return None
    return as_number(round_half_up(D(yes) / D(yes + no), 4))


def compute_passed(round_rec) -> bool:
    """Pass verdict per committee.pass_rule (dual variant)."""
    committee = db["committees"].get(round_rec["committee_id"])
    yes = round_rec["yes_count"]
    no = round_rec["no_count"]
    eligible = round_rec.get("eligible_voter_count") or 0
    if committee and committee["pass_rule"] == "SUPERMAJORITY_OF_ENTITLED":
        # yes / eligible_voter_count >= 2/3 — an exact two-thirds passes
        if eligible < 1:
            return False
        ratio = round_half_up(D(yes) / D(eligible), 4)
        return ratio >= SUPERMAJORITY_RATIO
    # STRICT_MAJORITY_OF_CAST: yes / (yes + no) > 0.5 — an exact tie fails
    if yes + no == 0:
        return False
    return 2 * yes > (yes + no)


def latest_round_at_level(case_id, level, completed_only=False):
    """Latest round of the case at a level by created_at (tie-break _seq)."""
    rounds = [
        r for r in db["rounds"].values()
        if r["case_id"] == case_id and r["level"] == level
    ]
    if completed_only:
        rounds = [r for r in rounds if r["status"] == "COMPLETED"]
    if not rounds:
        return None
    rounds.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rounds[-1]


def compute_recommendation_score(case):
    """calculation case_recommendation_score: weighted certified percentages,
    fail-capped at 0.49 when any selected round did not pass."""
    selected = {}
    for level in ("DEPARTMENT", "COLLEGE", "UNIVERSITY"):
        rounds = [
            r for r in db["rounds"].values()
            if r["case_id"] == case["id"] and r["level"] == level and r["status"] == "COMPLETED"
        ]
        if not rounds:
            return None
        # latest certified_at; tie-break latest created_at
        rounds.sort(key=lambda r: (r.get("certified_at") or "", r["created_at"], r["_seq"]))
        selected[level] = rounds[-1]
    pct = {lvl: D(str(selected[lvl]["yes_percentage"])) if selected[lvl]["yes_percentage"] is not None else D(0)
           for lvl in selected}
    raw = DEPT_WEIGHT * pct["DEPARTMENT"] + COLLEGE_WEIGHT * pct["COLLEGE"] + UNIV_WEIGHT * pct["UNIVERSITY"]
    score = round_half_up(raw, 4)
    if any(selected[lvl]["passed"] is False for lvl in selected):
        score = min(score, FAIL_CAP)
    return as_number(score)
