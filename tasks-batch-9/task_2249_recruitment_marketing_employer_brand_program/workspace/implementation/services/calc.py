"""Derived aggregates and every named calculation of SCAFFOLD.yaml."""

import math
from datetime import timedelta
from decimal import Decimal
from fractions import Fraction

import db
from db import clock, flr, largest_remainder, money2, rhu
from errors import ApiError

FAMILY_DEDICATED = "FAMILY_DEDICATED"
POOL_BY_TYPE = {
    "JOB_BOARD": "POOL_JOB_BOARD",
    "SOCIAL": "POOL_SOCIAL",
    "PROGRAMMATIC": "POOL_PROGRAMMATIC",
}
POOL_FIELD = {
    "POOL_JOB_BOARD": "pool_job_board_cents",
    "POOL_SOCIAL": "pool_social_cents",
    "POOL_PROGRAMMATIC": "pool_programmatic_cents",
    "FLEX_RESERVE": "flex_reserve_cents",
}
PAYABLE_TYPES = ("JOB_BOARD", "SOCIAL", "PROGRAMMATIC")
NON_TERMINAL_FLIGHT = ("RESERVED", "ACTIVE", "PAUSED_PACING", "SUSPENDED_CONTENT")
RESOLVED_REVIEW_STATES = ("RESPONSE_PUBLISHED", "CLOSED_NO_RESPONSE")


# ------------------------------------------------------------------ lookups
def must_get(collection, identifier, error_id):
    row = collection.get(identifier) if isinstance(identifier, str) else None
    if row is None:
        raise ApiError(error_id, "No such record: %s." % identifier)
    return row


def rows(collection):
    return list(collection.values())


def by_created(items):
    return sorted(items, key=lambda row: row["created_at"])


# --------------------------------------------------------------- the ledger
def program_entries(program_id):
    return [e for e in db.ledger.values() if e["program_id"] == program_id]


def committed_budget_cents(program):
    return sum(e["delta_cents"] for e in program_entries(program["id"]))


def bucket_committed(program_id, bucket):
    return sum(
        e["delta_cents"] for e in db.ledger.values()
        if e["program_id"] == program_id and e["bucket"] == bucket
    )


def family_reserved_cents(family):
    return sum(
        e["delta_cents"] for e in db.ledger.values()
        if e["job_family_id"] == family["id"] and e["bucket"] == FAMILY_DEDICATED
    )


def family_available_cents(family):
    return family["dedicated_budget_cents"] - family_reserved_cents(family)


def program_families(program_id):
    return [f for f in db.job_families.values() if f["program_id"] == program_id]


def available_budget_cents(program):
    total = (
        program["pool_job_board_cents"]
        + program["pool_social_cents"]
        + program["pool_programmatic_cents"]
        + program["flex_reserve_cents"]
    )
    total += sum(f["dedicated_budget_cents"] for f in program_families(program["id"]))
    return total - committed_budget_cents(program)


def bucket_available(program, family, bucket):
    if bucket == FAMILY_DEDICATED:
        return family_available_cents(family)
    return program[POOL_FIELD[bucket]] - bucket_committed(program["id"], bucket)


def next_sequence_no(program_id):
    return len(program_entries(program_id)) + 1


# ------------------------------------------------------------- program links
def program_of_family(family):
    return db.programs[family["program_id"]]


def program_of_channel(channel):
    return db.programs[channel["program_id"]]


def family_of_posting(posting):
    return db.job_families[posting["job_family_id"]]


def program_of_posting(posting):
    return program_of_family(family_of_posting(posting))


# ------------------------------------------------------- channel aggregates
def channel_flights(channel_id):
    return [f for f in db.flights.values() if f["channel_id"] == channel_id]


def channel_spent_cents(channel):
    return sum(f["spent_cents"] for f in channel_flights(channel["id"]))


def channel_active_flight_count(channel):
    return len([f for f in channel_flights(channel["id"]) if f["state"] == "ACTIVE"])


def channel_credited_qualified_bp(channel):
    total = 0
    for touch in db.touchpoints.values():
        if touch["channel_id"] != channel["id"] or not touch["credit_bp"]:
            continue
        app = db.applications.get(touch["application_id"])
        if app is not None and app["status"] == "QUALIFIED":
            total += touch["credit_bp"]
    return total


def flight_qualified_credit_bp(flight):
    total = 0
    for touch in db.touchpoints.values():
        if touch["media_flight_id"] != flight["id"] or not touch["credit_bp"]:
            continue
        app = db.applications.get(touch["application_id"])
        if app is not None and app["status"] == "QUALIFIED":
            total += touch["credit_bp"]
    return total


# ------------------------------------------------------- posting aggregates
def posting_applications(posting_id):
    return [a for a in db.applications.values() if a["job_posting_id"] == posting_id]


def posting_conversion_metrics(posting):
    apps = posting_applications(posting["id"])
    apply_start = len(apps)
    submitted = len([a for a in apps if a["status"] in
                     ("SUBMITTED", "SCREENED", "QUALIFIED", "DISQUALIFIED")])
    qualified = len([a for a in apps if a["status"] == "QUALIFIED"])
    if apply_start == 0:
        rate = None
    else:
        rate = flr(Fraction(10000 * submitted, apply_start))
    return {
        "apply_start_count": apply_start,
        "submitted_count": submitted,
        "qualified_count": qualified,
        "conversion_rate_bp": rate,
    }


# -------------------------------------------------------- member aggregates
def member_sends(member_id):
    return [s for s in db.sends.values()
            if s["member_id"] == member_id and s["outcome"] == "SENT"]


def member_sent_count_total(member):
    return len(member_sends(member["id"]))


def member_last_sent_at(member):
    stamps = [s["sent_at"] for s in member_sends(member["id"]) if s["sent_at"]]
    return max(stamps) if stamps else None


def campaign_sends(campaign_id):
    return [s for s in db.sends.values() if s["campaign_id"] == campaign_id]


def campaign_counters(campaign):
    written = campaign_sends(campaign["id"])
    return {
        "audience_size": len(written),
        "sent_count": len([s for s in written if s["outcome"] == "SENT"]),
        "suppressed_consent_count":
            len([s for s in written if s["outcome"] == "SUPPRESSED_CONSENT"]),
        "suppressed_frequency_count":
            len([s for s in written if s["outcome"] == "SUPPRESSED_FREQUENCY"]),
    }


def send_quota_used(program):
    used = 0
    for campaign in db.campaigns.values():
        if campaign["program_id"] == program["id"]:
            used += len([s for s in campaign_sends(campaign["id"])
                         if s["outcome"] == "SENT"])
    return used


# --------------------------------------------------------- review aggregates
def sla_status(review):
    """The stored verdict; it is only ever rewritten at the points PRD 3.8 names."""
    return review["sla_status"]


def reevaluate_sla(review):
    """Re-evaluate an unresolved review's verdict against the logical clock.

    PRD 2.4 - moving the clock "re-evaluates `sla_status` on every
    `EmployerReview` - a review still sitting in an unresolved state whose
    `response_due_at` the clock has now passed flips from `PENDING` to
    `BREACHED`".  PRD 3.8 - "Triage re-evaluates `sla_status` against
    `response_due_at` and the current logical clock."  A review that already
    reached a resolved state keeps the verdict frozen at resolution time.
    """
    if review["state"] in RESOLVED_REVIEW_STATES:
        return
    review["sla_status"] = (
        "PENDING" if clock() <= review["response_due_at"] else "BREACHED")


def review_response_deadline(posted_at, rating):
    hours = 24 if rating <= 2 else (72 if rating == 3 else 168)
    return posted_at + timedelta(hours=hours)


def brand_health_score(program):
    now = clock()
    lower = now - timedelta(days=90)
    windowed = [r for r in db.reviews.values()
                if r["program_id"] == program["id"]
                and lower < r["posted_at"] <= now]
    rating_penalty = Decimal(0)
    breached = 0
    for review in windowed:
        age_days = math.floor((now - review["posted_at"]).total_seconds() / 86400)
        if age_days <= 30:
            weight = Decimal("1.00")
        elif age_days <= 60:
            weight = Decimal("0.50")
        else:
            weight = Decimal("0.25")
        shortfall = max(0, 3 - review["rating"])
        rating_penalty += Decimal(shortfall) * Decimal("2.5") * weight
        if sla_status(review) == "BREACHED":
            breached += 1
    score = Decimal(100) - rating_penalty - Decimal("5.0") * breached
    if score < 0:
        score = Decimal(0)
    if score > 100:
        score = Decimal(100)
    return float(money2(score))


# ------------------------------------------------------ persona_channel_mix
def persona_channel_mix(persona):
    """Recompute channel_mix, mix_confidence_pct and signal_count."""
    now = clock()
    lower = now - timedelta(days=persona["research_window_days"])
    selected = [s for s in db.signals.values()
                if s["persona_id"] == persona["id"]
                and lower < s["collected_at"] <= now]
    count = len(selected)
    if count == 0:
        return {"channel_mix": [], "mix_confidence_pct": 0, "signal_count": 0}

    confidence = min(100, flr(Fraction(sum(s["sample_size"] for s in selected), 10)))
    scores = {}
    for signal in selected:
        if persona["mix_method"] == "SURVEY_WEIGHTED":
            weight = Fraction(signal["sample_size"])
        else:
            age_days = math.floor((now - signal["collected_at"]).total_seconds() / 86400)
            decay_pct = max(10, 100 - 10 * (age_days // 30))
            weight = Fraction(signal["engagement_events"] * decay_pct, 100)
        contribution = weight * signal["preference_score"]
        scores[signal["channel_id"]] = scores.get(signal["channel_id"], Fraction(0)) + contribution

    total = sum(scores.values(), Fraction(0))
    if total == 0:
        return {"channel_mix": [], "mix_confidence_pct": confidence, "signal_count": count}

    def channel_key(channel_id):
        channel = db.channels.get(channel_id)
        if channel is None:
            return (db.DEFAULT_CLOCK, "")
        return (channel["created_at"], channel["name"])

    ordered = sorted(scores.keys(), key=channel_key)
    shares = largest_remainder(
        [(cid, Fraction(10000) * scores[cid] / total) for cid in ordered])
    mix = [{"channel_id": cid, "share_bp": shares[cid]}
           for cid in ordered if scores[cid] > 0]
    mix.sort(key=lambda item: (-item["share_bp"], channel_key(item["channel_id"])[0]))
    return {"channel_mix": mix, "mix_confidence_pct": confidence, "signal_count": count}


# -------------------------------------------------------- flight_gross_cost
DISCOUNT_RATE = {
    "TIER_1": Fraction(0),
    "TIER_2": Fraction(5, 100),
    "TIER_3": Fraction(8, 100),
}
FEE_RATE = {
    "JOB_BOARD": {"TIER_1": Fraction(3, 100), "TIER_2": Fraction(3, 100), "TIER_3": Fraction(2, 100)},
    "SOCIAL": {"TIER_1": Fraction(6, 100), "TIER_2": Fraction(5, 100), "TIER_3": Fraction(4, 100)},
    "PROGRAMMATIC": {"TIER_1": Fraction(10, 100), "TIER_2": Fraction(9, 100), "TIER_3": Fraction(7, 100)},
}


def flight_days(start_day, end_day):
    return (db.parse_day(end_day) - db.parse_day(start_day)).days


def flight_pricing(channel, days, daily_cap_cents):
    base_gross = daily_cap_cents * days
    if base_gross < 500000:
        tier = "TIER_1"
    elif base_gross < 2000000:
        tier = "TIER_2"
    else:
        tier = "TIER_3"
    discount = flr(base_gross * DISCOUNT_RATE[tier])
    net_media = base_gross - discount
    fee = rhu(net_media * FEE_RATE[channel["channel_type"]][tier])
    return {
        "flight_days": days,
        "base_gross_cents": base_gross,
        "cost_tier": tier,
        "volume_discount_cents": discount,
        "platform_fee_cents": fee,
        "total_cost_cents": net_media + fee,
    }


# --------------------------------------------------- application_touch_credit
def eligible_touchpoints(app):
    anchor = app["submitted_at"]
    if anchor is None:
        return []
    lower = anchor - timedelta(days=30)
    selected = [t for t in db.touchpoints.values()
                if t["application_id"] == app["id"]
                and lower < t["occurred_at"] <= anchor]
    return sorted(selected, key=lambda t: (t["occurred_at"], t["created_at"]))


def attribution_weights(model, count):
    if model == "LINEAR" or count <= 2:
        return [Fraction(1)] * count
    weights = [Fraction(2000, count - 2)] * count
    weights[0] = Fraction(4000)
    weights[count - 1] = Fraction(4000)
    return weights


def attribution_credit(app, model):
    """{touchpoint_id: credit_bp} for the eligible set, exactly 10000 bp."""
    selected = eligible_touchpoints(app)
    count = len(selected)
    if count == 0:
        return {}, []
    weights = attribution_weights(model, count)
    total = sum(weights, Fraction(0))
    exact = [(selected[i]["id"], Fraction(10000) * weights[i] / total)
             for i in range(count)]
    return largest_remainder(exact), selected


# ------------------------------------------------ channel_blended_cpqa_target
def channel_blended_target_cents(channel):
    program_id = channel["program_id"]
    per_family = {}
    for touch in db.touchpoints.values():
        if touch["channel_id"] != channel["id"] or not touch["credit_bp"]:
            continue
        app = db.applications.get(touch["application_id"])
        if app is None or app["status"] != "QUALIFIED":
            continue
        posting = db.postings.get(app["job_posting_id"])
        if posting is None:
            continue
        family = db.job_families.get(posting["job_family_id"])
        if family is None or family["program_id"] != program_id:
            continue
        per_family[family["id"]] = per_family.get(family["id"], 0) + touch["credit_bp"]
    total = sum(per_family.values())
    if total == 0:
        return None
    accumulated = sum(db.job_families[fid]["cpqa_target_cents"] * bp
                      for fid, bp in per_family.items())
    return rhu(Fraction(accumulated, total))
