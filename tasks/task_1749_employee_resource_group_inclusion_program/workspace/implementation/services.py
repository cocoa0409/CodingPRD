"""Business logic: computed fields, calculations (PRD section 3.8), cascades,
and entity serializers. All money is integer cents; all percentages/scores are
round-half-up at 2 decimal places via Decimal."""
import uuid
from datetime import timedelta
from decimal import Decimal

from db import STORE, clock_now, next_seq
from util import fmt_dt, rhu2, rhu_cents

# ---------------------------------------------------------------------------
# Calculation constants (scaffold table 1.3)
# ---------------------------------------------------------------------------
CATEGORY_WEIGHT_TENTHS = {"AFFINITY": 10, "PROFESSIONAL": 12, "COMMUNITY_OUTREACH": 15}
BASE_POINTS = {"WORKSHOP": 20, "SOCIAL": 10, "RECRUITING": 80, "COMMUNITY": 40}
SPONSOR_BONUS = 10
POINTS_CAP = 100
SCOUT_RATE = Decimal("0.10")
TIER1_CAP_CENTS = 1000000
HIGH_MATCH_RATE = Decimal("0.20")
LOW_MATCH_RATE = Decimal("0.05")
CLIMATE_THRESHOLD = Decimal("3.00")
MENTOR_BUFFER_DAYS = 14
LEADER_TENURE_DAYS = 90

GROUP_NON_TERMINAL = {"CHARTER_DRAFT", "SUBMITTED", "SPONSOR_ENDORSED",
                      "CHANGES_REQUESTED", "ACTIVE", "SUSPENDED"}
SPONSOR_GROUP_LOAD_STATUSES = GROUP_NON_TERMINAL
MEMBER_ACCEPTING = {"CHARTER_DRAFT", "SUBMITTED", "SPONSOR_ENDORSED",
                    "CHANGES_REQUESTED", "ACTIVE"}


# ---------------------------------------------------------------------------
# Generic entity helpers
# ---------------------------------------------------------------------------
def new_entity(collection, fields):
    now = clock_now()
    ent = {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    ent.update(fields)
    STORE[collection][ent["id"]] = ent
    return ent


def touch(ent):
    """PRD 2.4: version increments and updated_at refreshes on every mutation."""
    ent["version"] += 1
    ent["updated_at"] = clock_now()


# ---------------------------------------------------------------------------
# Live computed aggregates
# ---------------------------------------------------------------------------
def active_member_count(group_id):
    return sum(1 for m in STORE["memberships"].values()
               if m["group_id"] == group_id and m["status"] == "ACTIVE")


def active_term_of(group_id):
    terms = [t for t in STORE["terms"].values()
             if t["group_id"] == group_id and t["status"] == "ACTIVE"]
    if not terms:
        return None
    return sorted(terms, key=lambda t: (t["created_at"], t["_seq"]))[0]


def has_active_leader(group_id):
    return active_term_of(group_id) is not None


def available_cents(group):
    return group["allocated_cents"] - group["reserved_cents"] - group["spent_cents"]


def unallocated_pool_cents(program):
    allocated = sum(g["allocated_cents"] for g in STORE["groups"].values()
                    if g["program_id"] == program["id"])
    return program["pool_total_cents"] - allocated


def registered_count(event_id):
    return sum(1 for r in STORE["rsvps"].values()
               if r["event_id"] == event_id and r["status"] in ("REGISTERED", "CHECKED_IN"))


def checked_in_count(event_id):
    return sum(1 for r in STORE["rsvps"].values()
               if r["event_id"] == event_id and r["status"] == "CHECKED_IN")


def response_count(survey_id):
    return sum(1 for r in STORE["responses"].values() if r["survey_id"] == survey_id)


def survey_responses(survey_id):
    return [r for r in STORE["responses"].values() if r["survey_id"] == survey_id]


def mean_score_2dp(scores):
    """Mean of stored 2dp scores, round-half-up to 2dp."""
    total = sum(Decimal(str(s)) for s in scores)
    return rhu2(total / Decimal(len(scores)))


def provisional_index(survey):
    if survey["status"] != "OPEN":
        return None
    scores = [r["response_score"] for r in survey_responses(survey["id"])]
    if not scores:
        return None
    return mean_score_2dp(scores)


def completed_events(group_id):
    return [e for e in STORE["events"].values()
            if e["group_id"] == group_id and e["status"] == "COMPLETED"]


def standing_score(group):
    """group_standing_score: 0.5 * mean(member_engagement_pct over COMPLETED
    events) + 0.5 * min(100, member_growth_pct); round-half-up 2dp.
    Null until the group has been activated (founding_member_count snapshot)."""
    founding = group.get("founding_member_count")
    if founding is None:
        return None
    events = completed_events(group["id"])
    if events:
        avg_engagement = sum(Decimal(str(e["member_engagement_pct"])) for e in events) \
            / Decimal(len(events))
    else:
        avg_engagement = Decimal("0")
    growth = Decimal(100) * Decimal(active_member_count(group["id"]) - founding) \
        / Decimal(founding)
    capped = min(Decimal("100"), growth)
    return rhu2(Decimal("0.5") * avg_engagement + Decimal("0.5") * capped)


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def matching_topup_award(requested_cents, external_matching_cents):
    """Pinned evaluation order: scouting provisional total picks the tier."""
    provisional_total = Decimal(requested_cents) + SCOUT_RATE * Decimal(external_matching_cents)
    rate = HIGH_MATCH_RATE if provisional_total <= Decimal(TIER1_CAP_CENTS) else LOW_MATCH_RATE
    match_cents = rhu_cents(rate * Decimal(external_matching_cents))
    return requested_cents + match_cents


def event_impact_points(event, group):
    util = Decimal(str(event["capacity_utilization_pct"]))
    if util < Decimal("25"):
        multiplier = Decimal("0.5")
    elif util < Decimal("75"):
        multiplier = Decimal("1.0")
    else:
        multiplier = Decimal("1.5")
    bonus = 0
    sponsor_id = group.get("sponsor_id")
    if sponsor_id:
        sponsor = STORE["sponsors"].get(sponsor_id)
        if sponsor:
            for r in STORE["rsvps"].values():
                if (r["event_id"] == event["id"] and r["status"] == "CHECKED_IN"
                        and r["employee_id"] == sponsor["employee_id"]):
                    bonus = SPONSOR_BONUS
                    break
    total = Decimal(BASE_POINTS[event["category"]]) * multiplier + Decimal(bonus)
    return int(min(Decimal(POINTS_CAP), total))


def allocation_waterfall(program):
    """Largest-remainder waterfall over the program's ACTIVE groups.
    Per-group floor first, then remainder one cent at a time by descending
    fractional part (ties: created_at ASC, then name ASC). Fractional parts
    share the same denominator so integer remainders order them exactly."""
    groups = [g for g in STORE["groups"].values()
              if g["program_id"] == program["id"] and g["status"] == "ACTIVE"]
    pool = program["pool_total_cents"]
    if not groups:
        return
    weights = {g["id"]: active_member_count(g["id"]) * CATEGORY_WEIGHT_TENTHS[g["category"]]
               for g in groups}
    total_weight = sum(weights.values())
    if total_weight == 0:
        # Degenerate case (all eligible groups empty): shares are all zero.
        for g in groups:
            g["allocated_cents"] = 0
            g["certified_standing_score"] = standing_score(g)
            touch(g)
        return
    floors = {}
    rema = {}
    for g in groups:
        num = pool * weights[g["id"]]
        floors[g["id"]] = num // total_weight
        rema[g["id"]] = num % total_weight
    remainder = pool - sum(floors.values())
    order = sorted(groups,
                   key=lambda g: (-rema[g["id"]], g["created_at"], g["name"]))
    for g in order[:remainder]:
        floors[g["id"]] += 1
    for g in groups:
        g["allocated_cents"] = floors[g["id"]]
        g["certified_standing_score"] = standing_score(g)
        touch(g)


def compute_response_score(b, g, f, s):
    return rhu2(Decimal("0.3") * b + Decimal("0.3") * g
                + Decimal("0.2") * f + Decimal("0.2") * s)


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------
def cancel_event_cascade(event):
    """Event -> CANCELLED: RSVPs in REGISTERED/WAITLISTED/CHECKED_IN ->
    CANCELLED (no waitlist promotion); funding_status RESERVED -> RELEASED."""
    if event["status"] not in ("PLANNED", "PUBLISHED"):
        return
    event["status"] = "CANCELLED"
    if event["funding_status"] == "RESERVED":
        event["funding_status"] = "RELEASED"
    touch(event)
    for r in STORE["rsvps"].values():
        if r["event_id"] == event["id"] and r["status"] in (
                "REGISTERED", "WAITLISTED", "CHECKED_IN"):
            r["status"] = "CANCELLED"
            touch(r)


def suspend_cascade(group):
    for e in STORE["events"].values():
        if e["group_id"] == group["id"] and e["status"] in ("PLANNED", "PUBLISHED"):
            cancel_event_cascade(e)


def dissolve_cascade(group):
    suspend_cascade(group)
    now = clock_now()
    for m in STORE["memberships"].values():
        if m["group_id"] == group["id"] and m["status"] == "ACTIVE":
            m["status"] = "INACTIVE"
            m["left_at"] = now
            touch(m)
    for fr in STORE["funding_requests"].values():
        if fr["group_id"] != group["id"]:
            continue
        if fr["status"] in ("SUBMITTED", "COUNTERED", "ENDORSED"):
            fr["status"] = "WITHDRAWN"
            touch(fr)
        elif fr["status"] == "APPROVED":
            group["reserved_cents"] -= fr["approved_cents"]
            fr["status"] = "WITHDRAWN"
            touch(fr)


def leadership_gap_cascade(group_id):
    """Fires when a group is left with no ACTIVE term: in-flight funding
    requests in SUBMITTED/COUNTERED are withdrawn."""
    if has_active_leader(group_id):
        return
    for fr in STORE["funding_requests"].values():
        if fr["group_id"] == group_id and fr["status"] in ("SUBMITTED", "COUNTERED"):
            fr["status"] = "WITHDRAWN"
            touch(fr)


def term_expiry_sweep(new_now):
    """Clock sweep: ACTIVE terms with ends_at <= new time -> EXPIRED, each
    firing the leadership-gap cascade for its group."""
    expired = [t for t in STORE["terms"].values()
               if t["status"] == "ACTIVE" and t["ends_at"] <= new_now]
    expired.sort(key=lambda t: (t["created_at"], t["_seq"]))
    for t in expired:
        t["status"] = "EXPIRED"
        touch(t)
        leadership_gap_cascade(t["group_id"])


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def program_json(p):
    return {
        "id": p["id"],
        "fiscal_year": p["fiscal_year"],
        "pool_total_cents": p["pool_total_cents"],
        "goals": p["goals"],
        "status": p["status"],
        "posture": p["posture"],
        "unallocated_pool_cents": unallocated_pool_cents(p),
        "created_at": fmt_dt(p["created_at"]),
        "updated_at": fmt_dt(p["updated_at"]),
        "version": p["version"],
    }


def sponsor_json(s):
    return {
        "id": s["id"],
        "employee_id": s["employee_id"],
        "max_groups": s["max_groups"],
        "max_mentees": s["max_mentees"],
        "status": s["status"],
        "created_at": fmt_dt(s["created_at"]),
        "updated_at": fmt_dt(s["updated_at"]),
        "version": s["version"],
    }


def group_json(g):
    return {
        "id": g["id"],
        "program_id": g["program_id"],
        "sponsor_id": g["sponsor_id"],
        "created_by_employee_id": g["created_by_employee_id"],
        "name": g["name"],
        "mission_statement": g["mission_statement"],
        "category": g["category"],
        "status": g["status"],
        "founding_member_count": g["founding_member_count"],
        "active_member_count": active_member_count(g["id"]),
        "has_active_leader": has_active_leader(g["id"]),
        "allocated_cents": g["allocated_cents"],
        "reserved_cents": g["reserved_cents"],
        "spent_cents": g["spent_cents"],
        "available_cents": available_cents(g),
        "certified_standing_score": g["certified_standing_score"],
        "provisional_standing_score": standing_score(g),
        "created_at": fmt_dt(g["created_at"]),
        "updated_at": fmt_dt(g["updated_at"]),
        "version": g["version"],
    }


def membership_json(m):
    return {
        "id": m["id"],
        "group_id": m["group_id"],
        "employee_id": m["employee_id"],
        "status": m["status"],
        "joined_at": fmt_dt(m["joined_at"]) if m["joined_at"] else None,
        "left_at": fmt_dt(m["left_at"]) if m["left_at"] else None,
        "created_at": fmt_dt(m["created_at"]),
        "updated_at": fmt_dt(m["updated_at"]),
        "version": m["version"],
    }


def term_json(t):
    return {
        "id": t["id"],
        "group_id": t["group_id"],
        "leader_employee_id": t["leader_employee_id"],
        "predecessor_term_id": t["predecessor_term_id"],
        "starts_at": fmt_dt(t["starts_at"]) if t["starts_at"] else None,
        "ends_at": fmt_dt(t["ends_at"]) if t["ends_at"] else None,
        "status": t["status"],
        "created_at": fmt_dt(t["created_at"]),
        "updated_at": fmt_dt(t["updated_at"]),
        "version": t["version"],
    }


def funding_json(f):
    return {
        "id": f["id"],
        "group_id": f["group_id"],
        "created_by_employee_id": f["created_by_employee_id"],
        "category": f["category"],
        "purpose": f["purpose"],
        "requested_cents": f["requested_cents"],
        "external_matching_cents": f["external_matching_cents"],
        "counter_amount_cents": f["counter_amount_cents"],
        "approved_cents": f["approved_cents"],
        "disbursed_cents": f["disbursed_cents"],
        "actual_spend_cents": f["actual_spend_cents"],
        "status": f["status"],
        "created_at": fmt_dt(f["created_at"]),
        "updated_at": fmt_dt(f["updated_at"]),
        "version": f["version"],
    }


def venue_json(v):
    return {
        "id": v["id"],
        "name": v["name"],
        "capacity": v["capacity"],
        "created_at": fmt_dt(v["created_at"]),
        "updated_at": fmt_dt(v["updated_at"]),
        "version": v["version"],
    }


def event_json(e):
    return {
        "id": e["id"],
        "group_id": e["group_id"],
        "venue_id": e["venue_id"],
        "funding_request_id": e["funding_request_id"],
        "title": e["title"],
        "category": e["category"],
        "starts_at": fmt_dt(e["starts_at"]) if e["starts_at"] else None,
        "ends_at": fmt_dt(e["ends_at"]) if e["ends_at"] else None,
        "capacity": e["capacity"],
        "status": e["status"],
        "funding_status": e["funding_status"],
        "registered_count": registered_count(e["id"]),
        "checked_in_count": checked_in_count(e["id"]),
        "capacity_utilization_pct": e["capacity_utilization_pct"],
        "member_engagement_pct": e["member_engagement_pct"],
        "impact_points": e["impact_points"],
        "low_attendance_flag": e["low_attendance_flag"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def rsvp_json(r):
    return {
        "id": r["id"],
        "event_id": r["event_id"],
        "employee_id": r["employee_id"],
        "status": r["status"],
        "waitlist_position": r["waitlist_position"],
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
    }


def survey_json(s):
    return {
        "id": s["id"],
        "program_id": s["program_id"],
        "title": s["title"],
        "opens_at": fmt_dt(s["opens_at"]),
        "closes_at": fmt_dt(s["closes_at"]),
        "min_responses": s["min_responses"],
        "status": s["status"],
        "response_count": response_count(s["id"]),
        "provisional_index": provisional_index(s),
        "final_index": s["final_index"],
        "created_at": fmt_dt(s["created_at"]),
        "updated_at": fmt_dt(s["updated_at"]),
        "version": s["version"],
    }


def response_json(r):
    # SurveyResponse carries only id and created_at (no updated_at / version).
    return {
        "id": r["id"],
        "survey_id": r["survey_id"],
        "respondent_employee_id": r["respondent_employee_id"],
        "belonging_score": r["belonging_score"],
        "growth_score": r["growth_score"],
        "fairness_score": r["fairness_score"],
        "safety_score": r["safety_score"],
        "response_score": r["response_score"],
        "created_at": fmt_dt(r["created_at"]),
    }


def engagement_json(e):
    return {
        "id": e["id"],
        "program_id": e["program_id"],
        "sponsor_id": e["sponsor_id"],
        "mentee_employee_id": e["mentee_employee_id"],
        "starts_at": fmt_dt(e["starts_at"]),
        "ends_at": fmt_dt(e["ends_at"]),
        "status": e["status"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }
