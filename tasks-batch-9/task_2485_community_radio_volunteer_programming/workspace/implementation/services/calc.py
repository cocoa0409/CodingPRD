"""Every derived figure the station computes (PRD 3.x calculations).

All money and score arithmetic uses decimal.Decimal with ROUND_HALF_UP.
"""

import re
from decimal import Decimal, ROUND_HALF_UP, getcontext

from db import clock, db, quarter_start, whole_months_between

getcontext().prec = 60

ZERO2 = Decimal("0.00")

CORE_CERT_TYPES = ("BOARD_OPERATION", "STATION_POLICY", "BROADCAST_REGULATION")
CERT_TYPES = CORE_CERT_TYPES + ("UNDERWRITING_COPY",)

ROLE_TRACKS = ("PROGRAMMER", "ENGINEER", "DEVELOPMENT")
VOLUNTEER_STATUSES = ("PROSPECT", "IN_TRAINING", "CERTIFIED", "PROBATION", "SUSPENDED", "RESIGNED")

FORMAT_CODES = ("MUSIC", "PUBLIC_AFFAIRS", "TALK", "NEWS", "CULTURAL")
DAYPARTS = ("MORNING_DRIVE", "MIDDAY", "AFTERNOON_DRIVE", "EVENING", "OVERNIGHT")
RECOMMENDATIONS = ("APPROVE", "REVISE", "DECLINE")

PLAY_SOURCES = ("LIBRARY_CD", "LIBRARY_VINYL", "DIGITAL", "LIVE_PERFORMANCE", "PRODUCTION_MUSIC")
FEATURED_SOURCES = ("LIBRARY_CD", "LIBRARY_VINYL", "DIGITAL")

SPOT_CLASSES = ("UNDERWRITING", "POLITICAL_CANDIDATE", "ISSUE_ADVOCACY", "PSA")
INCIDENT_CATEGORIES = ("INDECENCY", "POLITICAL_CONTENT", "PUBLIC_FILE", "SPONSOR_ID", "VOLUNTEER_CONFLICT")
SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")
SANCTIONS = ("NONE", "WARNING", "SUSPENSION", "TERMINATION")

PA_FORMATS = ("PUBLIC_AFFAIRS", "NEWS")
DIVERSITY_BONUS_FORMATS = ("PUBLIC_AFFAIRS", "CULTURAL")

WEEK_MINUTE_CAP = 10080
DIVERSITY_QUOTA_PCT = Decimal("8.00")
SENIORITY_PREEMPT_MARGIN = Decimal("5.00")
ROYALTY_RATE_CENTS_PER_MINUTE = Decimal("65")
SURVEY_UPLIFT = Decimal("1.10")

LIVE_SLOT_STATUSES = ("TENTATIVE", "CONFIRMED")


def rhu(value, places=2):
    quantum = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Volunteer derived figures (PRD 3.1 / 3.2)
# ---------------------------------------------------------------------------

def volunteer_certifications(volunteer_id):
    return [c for c in db.certifications.values() if c["volunteer_id"] == volunteer_id]


def certification_is_live(cert):
    return (
        cert["status"] == "PASSED"
        and cert["expires_on"] is not None
        and cert["expires_on"] > clock.now
    )


def holds_live_cert(volunteer_id, cert_type):
    for cert in db.certifications.values():
        if cert["volunteer_id"] == volunteer_id and cert["cert_type"] == cert_type and certification_is_live(cert):
            return True
    return False


def current_certification_count(volunteer_id):
    return sum(1 for c in volunteer_certifications(volunteer_id) if certification_is_live(c))


def core_set_complete(volunteer_id):
    return all(holds_live_cert(volunteer_id, cert_type) for cert_type in CORE_CERT_TYPES)


def holds_passed_cert(volunteer_id, cert_type):
    for cert in db.certifications.values():
        if (
            cert["volunteer_id"] == volunteer_id
            and cert["cert_type"] == cert_type
            and cert["status"] == "PASSED"
        ):
            return True
    return False


def needs_core_renewal(volunteer_id):
    """PRD 3.1 states this one in terms of record *status*: it is true whenever a
    core curriculum is absent, EXPIRED or REVOKED.  A ticket whose expires_on the
    clock has passed is still `PASSED` until the daily sweep lapses it, so this
    flag — unlike current_certification_count, which the PRD defines against the
    clock — only flips once the sweep has run."""
    return not all(holds_passed_cert(volunteer_id, ct) for ct in CORE_CERT_TYPES)


def continuous_service_months(volunteer):
    return whole_months_between(volunteer["seniority_start_date"], clock.now)


def hosted_scored_programs(volunteer_id):
    return [
        p for p in db.programs.values()
        if p["host_volunteer_id"] == volunteer_id
        and p["programming_status"] != "CANCELLED"
        and p["performance_score"] is not None
    ]


def seniority_score(volunteer):
    service_term = Decimal(min(60, continuous_service_months(volunteer)))
    cert_term = Decimal(10 * current_certification_count(volunteer["id"]))
    scored = hosted_scored_programs(volunteer["id"])
    if scored:
        mean_score = sum((p["performance_score"] for p in scored), Decimal(0)) / Decimal(len(scored))
        perf_term = rhu(Decimal("0.20") * mean_score, 2)
    else:
        perf_term = ZERO2
    strike_term = Decimal(15 * volunteer.get("strike_count", 0))
    total = rhu(service_term + cert_term + perf_term - strike_term, 2)
    return total if total > ZERO2 else ZERO2


# ---------------------------------------------------------------------------
# Committee scoring (PRD 3.3)
# ---------------------------------------------------------------------------

def seated_committee(exclude_volunteer_id=None):
    return [
        v for v in db.volunteers.values()
        if v.get("committee_seat") is True
        and v["status"] not in ("SUSPENDED", "RESIGNED")
        and (exclude_volunteer_id is None or v["id"] != exclude_volunteer_id)
    ]


def published_public_affairs_share():
    published = [g for g in db.grids.values() if g["status"] == "PUBLISHED"]
    if len(published) != 1:
        return ZERO2
    return grid_figures(published[0])[1]


def round_ballots(proposal):
    return [
        vote for vote in db.votes.values()
        if vote["proposal_id"] == proposal["id"] and vote["review_round"] == proposal["review_round"]
    ]


def composite_score(proposal, ballots):
    count = Decimal(len(ballots))
    mean_format = sum(Decimal(b["format_fit_score"]) for b in ballots) / count
    mean_diversity = sum(Decimal(b["diversity_score"]) for b in ballots) / count
    mean_quality = sum(Decimal(b["quality_score"]) for b in ballots) / count
    weighted = (
        Decimal("0.40") * mean_format
        + Decimal("0.35") * mean_diversity
        + Decimal("0.25") * mean_quality
    )
    bonus = Decimal("0")
    if proposal["format_code"] in DIVERSITY_BONUS_FORMATS and published_public_affairs_share() < DIVERSITY_QUOTA_PCT:
        bonus += Decimal("0.50")
    if (proposal["language_code"] or "").upper() != "EN":
        bonus += Decimal("0.25")
    score = rhu(weighted + bonus, 2)
    return min(Decimal("5.00"), score)


def required_quorum(seated_count):
    sixty_percent = (Decimal(seated_count) * Decimal("0.60")).to_integral_value(rounding="ROUND_CEILING")
    return max(3, int(sixty_percent))


def decline_majority(ballots):
    declines = sum(1 for b in ballots if b["recommendation"] == "DECLINE")
    return (2 * declines) > len(ballots)


# ---------------------------------------------------------------------------
# Grid figures (PRD 3.4)
# ---------------------------------------------------------------------------

def grid_live_slots(grid_id):
    return [
        s for s in db.slots.values()
        if s["grid_id"] == grid_id and s["status"] in LIVE_SLOT_STATUSES
    ]


def grid_figures(grid):
    live = grid_live_slots(grid["id"])
    total = sum(s["duration_minutes"] for s in live)
    if total == 0:
        return 0, ZERO2
    public_affairs = 0
    for slot in live:
        program = db.programs.get(slot["program_id"])
        if program is not None and program["format_code"] in PA_FORMATS:
            public_affairs += slot["duration_minutes"]
    pct = rhu(Decimal(100) * Decimal(public_affairs) / Decimal(total), 2)
    return total, pct


def slots_collide(day_a, start_a, duration_a, day_b, start_b, duration_b):
    """Two-minute changeover buffer (PRD 3.4)."""
    if day_a != day_b:
        return False
    end_a = start_a + duration_a
    end_b = start_b + duration_b
    return start_a < end_b + 2 and start_b < end_a + 2


# ---------------------------------------------------------------------------
# Royalties (PRD 3.5)
# ---------------------------------------------------------------------------

def episode_entries(episode_id):
    entries = [e for e in db.entries.values() if e["episode_id"] == episode_id]
    entries.sort(key=lambda e: e["sequence_number"])
    return entries


def royalty_class(play_source, duration_seconds):
    if play_source == "PRODUCTION_MUSIC":
        return "EXEMPT"
    if play_source in FEATURED_SOURCES and duration_seconds >= 30:
        return "FEATURED"
    return "INCIDENTAL"


def featured_entries(episode_id):
    return [e for e in episode_entries(episode_id) if e["royalty_class"] == "FEATURED"]


def per_entry_cents(entry):
    exact = Decimal(entry["duration_seconds"]) / Decimal(60) * ROYALTY_RATE_CENTS_PER_MINUTE
    return int(rhu(exact, 0))


def survey_royalty_cents(episode_id):
    featured = featured_entries(episode_id)
    if not featured:
        return 0
    total_seconds = sum(e["duration_seconds"] for e in featured)
    raw = Decimal(total_seconds) / Decimal(60) * ROYALTY_RATE_CENTS_PER_MINUTE
    return int(rhu(raw * SURVEY_UPLIFT, 0))


def census_royalty_cents(episode_id):
    featured = featured_entries(episode_id)
    if not featured:
        return 0
    return sum(per_entry_cents(e) for e in featured)


# ---------------------------------------------------------------------------
# Noncommercial copy risk screen (PRD 3.6)
# ---------------------------------------------------------------------------

_WHITESPACE_RE = re.compile(r"\s+")
_PRICE_RE = re.compile(r"\$\d")

CALL_TO_ACTION_PHRASES = (
    "call now",
    "act now",
    "visit us today",
    "stop by today",
    "shop now",
    "limited time offer",
)
PRICE_PHRASES = ("% off", "percent off", "save $")
COMPARATIVE_PHRASES = ("best", "lowest prices", "number one", "unbeatable")


def normalize_copy(text):
    return _WHITESPACE_RE.sub(" ", (text or "").lower()).strip()


def risk_screen(copy_text, underwriter_name, spot_class):
    if spot_class == "POLITICAL_CANDIDATE":
        return 0, []
    normalized = normalize_copy(copy_text)
    flags = []
    score = 0
    if any(phrase in normalized for phrase in CALL_TO_ACTION_PHRASES):
        flags.append("CALL_TO_ACTION")
        score += 40
    if _PRICE_RE.search(normalized) or any(phrase in normalized for phrase in PRICE_PHRASES):
        flags.append("PRICE_INFO")
        score += 35
    if any(phrase in normalized for phrase in COMPARATIVE_PHRASES):
        flags.append("COMPARATIVE_CLAIM")
        score += 25
    if normalize_copy(underwriter_name) not in normalized:
        flags.append("MISSING_SPONSOR_ID")
        score += 10
    return min(100, score), sorted(flags)


def edited_copy_score(copy_text, underwriter_name):
    """The screen applied to a proposed edit, ignoring any class bypass."""
    return risk_screen(copy_text, underwriter_name, "UNDERWRITING")[0]


# ---------------------------------------------------------------------------
# Compliance penalty points (PRD 3.7)
# ---------------------------------------------------------------------------

BASE_POINTS = {
    "INDECENCY": {"MINOR": 2, "MAJOR": 5, "CRITICAL": 9},
    "POLITICAL_CONTENT": {"MINOR": 1, "MAJOR": 3, "CRITICAL": 6},
    "PUBLIC_FILE": {"MINOR": 1, "MAJOR": 3, "CRITICAL": 5},
    "SPONSOR_ID": {"MINOR": 1, "MAJOR": 2, "CRITICAL": 4},
    "VOLUNTEER_CONFLICT": {"MINOR": 1, "MAJOR": 2, "CRITICAL": 4},
}


def safe_harbor_violation(category, occurred_at):
    if category != "INDECENCY":
        return False
    return 6 <= occurred_at.hour < 22


def penalty_points(category, severity, safe_harbor):
    base = BASE_POINTS[category][severity]
    return base * 2 if safe_harbor else base


def program_penalty_points(program_id):
    return sum(
        i["penalty_points"] for i in db.incidents.values()
        if i.get("program_id") == program_id and i["status"] == "SUBSTANTIATED"
    )


def standing_for_points(points):
    if points >= 6:
        return "RESTRICTED"
    if points >= 1:
        return "WATCH"
    return "CLEAR"


# ---------------------------------------------------------------------------
# Program performance score (PRD 3.8)
# ---------------------------------------------------------------------------

AIRED_STATUSES = ("AIRED", "SUBSTITUTE_AIRED")
LOGGED_STATUSES = ("SUBMITTED", "CERTIFIED")
LOG_REQUIRED_STATUSES = ("PENDING", "SUBMITTED", "CERTIFIED", "DELINQUENT")


def performance_window(program_id, review_window):
    candidates = [
        e for e in db.episodes.values()
        if e["program_id"] == program_id
        and e["air_status"] != "CANCELLED"
        and e["scheduled_start_utc"] <= clock.now
    ]
    if review_window == "TRAILING_SIX":
        candidates.sort(key=lambda e: (e["scheduled_start_utc"], e["_seq"]), reverse=True)
        return candidates[:6]
    start = quarter_start(clock.now)
    inside = [e for e in candidates if e["scheduled_start_utc"] >= start]
    inside.sort(key=lambda e: (e["scheduled_start_utc"], e["_seq"]))
    return inside


def performance_score(program, review_window):
    window = performance_window(program["id"], review_window)
    aired = sum(1 for e in window if e["air_status"] in AIRED_STATUSES)
    missed = sum(1 for e in window if e["air_status"] == "MISSED")
    reliability = Decimal(1) if aired + missed == 0 else Decimal(aired) / Decimal(aired + missed)

    logged = sum(1 for e in window if e["log_status"] in LOGGED_STATUSES)
    log_required = sum(1 for e in window if e["log_status"] in LOG_REQUIRED_STATUSES)
    log_compliance = Decimal(1) if log_required == 0 else Decimal(logged) / Decimal(log_required)

    featured_total = sum(e["featured_performance_count"] for e in window)
    local_total = sum(e["local_featured_count"] for e in window)
    local_share = Decimal(1) if featured_total == 0 else Decimal(local_total) / Decimal(featured_total)

    base = Decimal(100) * (
        Decimal("0.55") * reliability
        + Decimal("0.30") * log_compliance
        + Decimal("0.15") * local_share
    )
    penalty = Decimal(5 * program_penalty_points(program["id"]))
    raw = base - penalty
    if raw < 0:
        raw = Decimal(0)
    if raw > 100:
        raw = Decimal(100)
    return rhu(raw, 2)


# ---------------------------------------------------------------------------
# Development aggregates (PRD 3.9)
# ---------------------------------------------------------------------------

def drive_pledges(drive_id):
    return [p for p in db.pledges.values() if p["drive_id"] == drive_id]


def drive_aggregates(drive):
    pledges = drive_pledges(drive["id"])
    gross = sum(p["amount_cents"] for p in pledges)
    pledged = sum(p["amount_cents"] for p in pledges if p["payment_status"] in ("PENDING", "PAID"))
    fulfilled = sum(p["amount_cents"] for p in pledges if p["payment_status"] == "PAID")
    refunded = sum(p["amount_cents"] for p in pledges if p["payment_status"] == "REFUNDED")
    lapsed = sum(p["amount_cents"] for p in pledges if p["payment_status"] == "LAPSED")
    goal = drive["goal_cents"]
    attainment = ZERO2 if not goal else rhu(Decimal(100) * Decimal(pledged) / Decimal(goal), 2)
    return {
        "gross_pledged_cents": gross,
        "pledged_total_cents": pledged,
        "fulfilled_total_cents": fulfilled,
        "refunded_total_cents": refunded,
        "lapsed_total_cents": lapsed,
        "attainment_pct": attainment,
    }


def premium_available(item):
    return item["on_hand_qty"] - item["reserved_qty"]


def premium_status(item):
    return "AVAILABLE" if premium_available(item) > 0 else "DEPLETED"
