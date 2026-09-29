"""Derived counters and the eight calculation rules (PRD 2.9, 3.3, 3.5, 3.7-3.9).

Every derived field is computed from live store state so that a cascade can never
leave a stale value behind; version/updated_at bookkeeping is done by the callers
(see db.touch / db.DerivedWatch).
"""
from decimal import Decimal

from db import db
from util import dec, floor_days, floor_minutes, rhu, dedup

ZERO = Decimal("0")

# ---------------------------------------------------------------- sampling
VALUE_NORMALIZER_USD = Decimal("250000")
RECENCY_HORIZON_DAYS = 180
COMPETITOR_TIER_WEIGHT = {
    "PRIMARY": Decimal("0.30"),
    "SECONDARY": Decimal("0.20"),
    "EMERGING": Decimal("0.10"),
}
SEGMENT_RANK = {"ENTERPRISE": 1, "MIDMARKET": 2, "SMB": 3}
STRATIFIED_VALUE_WEIGHT = Decimal("0.40")
STRATIFIED_RECENCY_WEIGHT = Decimal("0.40")
VALUE_WEIGHTED_VALUE_WEIGHT = Decimal("0.65")
VALUE_WEIGHTED_RECENCY_WEIGHT = Decimal("0.15")
ENTERPRISE_MULTIPLIER = Decimal("1.25")

# ---------------------------------------------------------------- incentives
TITLE_BAND_BASE_USD = {
    "ECONOMIC_BUYER": Decimal("250.00"),
    "CHAMPION": Decimal("175.00"),
    "PROCUREMENT": Decimal("150.00"),
    "END_USER": Decimal("100.00"),
}
DURATION_LADDER = (
    (75, Decimal("1.25")),
    (45, Decimal("1.00")),
    (25, Decimal("0.60")),
)
EXTERNAL_VENDOR_UPLIFT = Decimal("1.10")
DEBRIEF_BUFFER_MINUTES = 15
NO_SHOW_GRACE_MINUTES = 15
COOLING_OFF_DAYS = 90
MAX_RESCHEDULES = 2

# ---------------------------------------------------------------- substantiation
SOURCE_WEIGHT = {
    "COMPETITOR_POSITIONING": Decimal("1.00"),
    "PRICING_PERCEPTION": Decimal("0.90"),
    "EVALUATION_CRITERIA": Decimal("0.70"),
    "LOSS_REASON": Decimal("0.50"),
    "PRODUCT_GAP": Decimal("0.40"),
}
RATING_BASE = Decimal("0.60")
RATING_STEP = Decimal("0.10")
RECENCY_WINDOW_DAYS = 90
STALE_RECENCY_FACTOR = Decimal("0.75")
CORROBORATED_MIN = Decimal("2.00")
ANECDOTAL_MIN = Decimal("0.90")
CLAIM_TYPE_POINTS = {
    "PRICING": 3, "PERFORMANCE": 3, "FEATURE": 2, "REFERENCE": 1,
}
LEVEL_ADJUSTMENT = {
    "UNSUBSTANTIATED": 1, "ANECDOTAL": 0, "CORROBORATED": -1,
}
RISK_POINTS = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
RISK_CLASS_BY_POINTS = {1: "LOW", 2: "MEDIUM", 3: "HIGH"}
HIGH_DISCOUNT_THRESHOLD = Decimal("2.50")
MEDIUM_DISCOUNT_THRESHOLD = Decimal("1.50")
HIGH_DISCOUNT = Decimal("0.25")
MEDIUM_DISCOUNT = Decimal("0.10")
CONDITIONAL_SURCHARGE = Decimal("0.15")
RISK_CEILING = Decimal("3.00")
PUBLISH_RISK_MAX = Decimal("2.20")

# ---------------------------------------------------------------- posture
FROZEN_UTILIZATION = Decimal("1.0000")
RESTRICTED_UTILIZATION = Decimal("0.8500")
STATUS_POSTURE_FLOOR = {
    "DRAFT": "OPEN", "ACTIVE": "OPEN", "CLOSING": "RESTRICTED", "CLOSED": "FROZEN",
}
POSTURE_RANK = {"OPEN": 0, "RESTRICTED": 1, "FROZEN": 2}

# ---------------------------------------------------------------- adoption
QUIZ_PASS_SCORE = 80
ADOPTION_GATE = Decimal("0.6000")

# ---------------------------------------------------------------- product gaps
ACR_NORMALIZER_USD = Decimal("500000")
ACR_COMPONENT_WEIGHT = Decimal("40")
FREQUENCY_CAP = 10
FREQUENCY_WEIGHT = 4
PRESSURE_FACTOR = {
    "PRIMARY": Decimal("1.30"), "SECONDARY": Decimal("1.10"), "EMERGING": Decimal("1.00"),
}
BAND_LADDER = (
    (Decimal("70"), "P0"),
    (Decimal("45"), "P1"),
    (Decimal("20"), "P2"),
)
COVERAGE_CONFIDENCE_BASE = Decimal("0.40")
COVERAGE_CONFIDENCE_STEP = Decimal("0.20")


# =============================================================== navigation
def deal_of_interview(interview):
    return db.deals.get(interview["deal_id"])


def program_of_deal(deal):
    return db.programs.get(deal["program_id"])


def program_of_interview(interview):
    deal = deal_of_interview(interview)
    return db.programs.get(deal["program_id"]) if deal else None


def program_of_battlecard(card):
    competitor = db.competitors.get(card["competitor_id"])
    return db.programs.get(competitor["program_id"]) if competitor else None


def program_id_of_battlecard(card):
    competitor = db.competitors.get(card["competitor_id"])
    return competitor["program_id"] if competitor else None


def deal_of_response(response):
    interview = db.interviews.get(response["interview_id"])
    if interview is None:
        return None
    return db.deals.get(interview["deal_id"])


def program_id_of_response(response):
    deal = deal_of_response(response)
    return deal["program_id"] if deal else None


def interviews_of_program(program_id):
    out = []
    for interview in db.interviews.values():
        deal = db.deals.get(interview["deal_id"])
        if deal is not None and deal["program_id"] == program_id:
            out.append(interview)
    return out


def interviews_of_deal(deal_id):
    return [i for i in db.interviews.values() if i["deal_id"] == deal_id]


def interviews_of_analyst(analyst_id):
    return [i for i in db.interviews.values() if i["analyst_id"] == analyst_id]


def claims_of_battlecard(battlecard_id):
    return [c for c in db.battlecard_claims.values()
            if c["battlecard_id"] == battlecard_id]


def assignments_of_battlecard(battlecard_id):
    return [a for a in db.enablement_assignments.values()
            if a["battlecard_id"] == battlecard_id]


def battlecards_of_competitor(competitor_id):
    return [b for b in db.battlecards.values() if b["competitor_id"] == competitor_id]


def responses_of_interview(interview_id):
    return [r for r in db.interview_responses.values()
            if r["interview_id"] == interview_id]


# =============================================================== program ledger
def incentive_committed(program):
    total = ZERO
    for interview in interviews_of_program(program["id"]):
        if interview["incentive_status"] == "COMMITTED":
            total += dec(interview["incentive_provisional_usd"])
    return rhu(total, 2)


def incentive_paid(program):
    total = ZERO
    for interview in interviews_of_program(program["id"]):
        if interview["incentive_status"] == "PAID" and \
                interview["incentive_final_usd"] is not None:
            total += dec(interview["incentive_final_usd"])
    return rhu(total, 2)


def utilization(program):
    budget = dec(program["incentive_budget_usd"])
    if budget == 0:
        return FROZEN_UTILIZATION
    total = incentive_committed(program) + incentive_paid(program)
    return rhu(total / budget, 4)


def posture(program):
    """program_incentive_posture: utilization ladder tightened by the status floor."""
    util = utilization(program)
    if util >= FROZEN_UTILIZATION:
        derived = "FROZEN"
    elif util >= RESTRICTED_UTILIZATION:
        derived = "RESTRICTED"
    else:
        derived = "OPEN"
    floor = STATUS_POSTURE_FLOOR[program["status"]]
    return derived if POSTURE_RANK[derived] >= POSTURE_RANK[floor] else floor


# =============================================================== competitor
def published_battlecard_count(competitor):
    return len([b for b in battlecards_of_competitor(competitor["id"])
                if b["status"] == "PUBLISHED"])


def ratified_loss_count(competitor):
    count = 0
    for deal in db.deals.values():
        if deal.get("primary_competitor_id") != competitor["id"]:
            continue
        if deal["outcome"] not in ("LOST", "NO_DECISION"):
            continue
        if deal["attribution_status"] == "RATIFIED":
            count += 1
    return count


def win_rate_vs(competitor):
    won = 0
    denominator = 0
    for deal in db.deals.values():
        if deal.get("primary_competitor_id") != competitor["id"]:
            continue
        if deal["outcome"] in ("WON", "LOST", "NO_DECISION"):
            denominator += 1
            if deal["outcome"] == "WON":
                won += 1
    if denominator == 0:
        return None
    return rhu(Decimal(won) / Decimal(denominator), 4)


def competitor_derived(competitor):
    return (published_battlecard_count(competitor),
            ratified_loss_count(competitor),
            win_rate_vs(competitor))


# =============================================================== deal
def interview_coverage_count(deal):
    return len([i for i in interviews_of_deal(deal["id"]) if i["status"] == "COMPLETED"])


# =============================================================== analyst
def open_interview_count(analyst):
    return len([i for i in interviews_of_analyst(analyst["id"])
                if i["status"] == "SCHEDULED"])


def committed_minutes(analyst):
    total = 0
    for interview in interviews_of_analyst(analyst["id"]):
        if interview["status"] != "SCHEDULED":
            continue
        total += floor_minutes(
            interview["scheduled_end_at"] - interview["scheduled_start_at"]
        ) + DEBRIEF_BUFFER_MINUTES
    return total


def analyst_derived(analyst):
    return (open_interview_count(analyst), committed_minutes(analyst))


# =============================================================== buyer contact
def completed_interviews_of_contact(contact_id):
    return [i for i in db.interviews.values()
            if i["buyer_contact_id"] == contact_id and i["status"] == "COMPLETED"]


def completed_interview_count(contact):
    return len(completed_interviews_of_contact(contact["id"]))


def last_completed_interview_end_at(contact):
    ends = [i["actual_end_at"] for i in completed_interviews_of_contact(contact["id"])
            if i["actual_end_at"] is not None]
    return max(ends) if ends else None


def contact_derived(contact):
    return (completed_interview_count(contact),
            last_completed_interview_end_at(contact))


# =============================================================== sampling frame
_STRATUM_FIELDS = {
    "WON": ("quota_won", "selected_won_count", "open_won_slots"),
    "LOST": ("quota_lost", "selected_lost_count", "open_lost_slots"),
    "NO_DECISION": ("quota_no_decision", "selected_no_decision_count",
                    "open_no_decision_slots"),
}


def selected_count(frame, stratum):
    count = 0
    for deal in db.deals.values():
        if deal.get("sampling_frame_id") != frame["id"]:
            continue
        if deal.get("stratum") != stratum:
            continue
        if deal["research_status"] in ("SELECTED", "INTERVIEWED", "SYNTHESIZED"):
            count += 1
    return count


def total_quota(frame):
    return frame["quota_won"] + frame["quota_lost"] + frame["quota_no_decision"]


def quota_for(frame, stratum):
    return frame[_STRATUM_FIELDS[stratum][0]]


def open_slots(frame, stratum):
    """Open slots are not materialised until the frame is sealed (PRD 3.3)."""
    if frame["status"] == "DRAFT":
        return 0
    return quota_for(frame, stratum) - selected_count(frame, stratum)


def coverage_ratio(frame):
    total = total_quota(frame)
    if total == 0:
        return Decimal("0.0000")
    selected = sum(selected_count(frame, s) for s in ("WON", "LOST", "NO_DECISION"))
    return rhu(Decimal(selected) / Decimal(total), 4)


def frame_derived(frame):
    return (tuple(selected_count(frame, s) for s in ("WON", "LOST", "NO_DECISION")),
            tuple(open_slots(frame, s) for s in ("WON", "LOST", "NO_DECISION")),
            coverage_ratio(frame))


# =============================================================== loss reason
def children_of_reason(reason_id):
    return [r for r in db.loss_reasons.values()
            if r.get("parent_reason_id") == reason_id]


def is_leaf(reason):
    return len(children_of_reason(reason["id"])) == 0


def reason_ratified_attribution_count(reason):
    count = 0
    for attribution in db.loss_attributions.values():
        if attribution["status"] != "RATIFIED":
            continue
        if attribution["primary_reason_id"] == reason["id"]:
            count += 1
        elif attribution.get("secondary_reason_id") == reason["id"]:
            count += 1
    return count


def root_reason(reason):
    seen = set()
    current = reason
    while current is not None and current.get("parent_reason_id"):
        if current["id"] in seen:
            return current
        seen.add(current["id"])
        parent = db.loss_reasons.get(current["parent_reason_id"])
        if parent is None:
            return current
        current = parent
    return current


def descendants_of_reason(reason_id):
    out = []
    stack = list(children_of_reason(reason_id))
    while stack:
        node = stack.pop()
        out.append(node)
        stack.extend(children_of_reason(node["id"]))
    return out


def compute_depth(reason):
    if not reason.get("parent_reason_id"):
        return 1
    parent = db.loss_reasons.get(reason["parent_reason_id"])
    if parent is None:
        return 1
    return parent["depth"] + 1


def subtree_height(reason_id):
    """Number of levels occupied by a node and its descendants (1 for a leaf)."""
    children = children_of_reason(reason_id)
    if not children:
        return 1
    return 1 + max(subtree_height(child["id"]) for child in children)


# =============================================================== selector
def value_term(deal):
    ratio_value = dec(deal["acr_usd"]) / VALUE_NORMALIZER_USD
    if ratio_value > Decimal("1.0000"):
        ratio_value = Decimal("1.0000")
    return rhu(ratio_value, 4)


def recency_term(deal, clock):
    days = floor_days(clock - deal["close_date"])
    raw = (Decimal(RECENCY_HORIZON_DAYS) - Decimal(days)) / Decimal(RECENCY_HORIZON_DAYS)
    if raw < 0:
        raw = ZERO
    return rhu(raw, 4)


def competitor_term(deal):
    competitor_id = deal.get("primary_competitor_id")
    if not competitor_id:
        return Decimal("0.00")
    competitor = db.competitors.get(competitor_id)
    if competitor is None or competitor["status"] == "ARCHIVED":
        return Decimal("0.00")
    return COMPETITOR_TIER_WEIGHT.get(competitor["tier"], Decimal("0.00"))


def selection_rank_score(deal, frame, clock):
    """sample_selection_rank_score, per selection basis (PRD 3.3)."""
    value = value_term(deal)
    recency = recency_term(deal, clock)
    competitor = competitor_term(deal)
    if frame["selection_basis"] == "STRATIFIED_BY_SEGMENT":
        raw = (STRATIFIED_VALUE_WEIGHT * value
               + STRATIFIED_RECENCY_WEIGHT * recency
               + competitor)
        return rhu(raw, 4)
    raw = (VALUE_WEIGHTED_VALUE_WEIGHT * value
           + VALUE_WEIGHTED_RECENCY_WEIGHT * recency
           + competitor)
    multiplier = (ENTERPRISE_MULTIPLIER if deal["segment"] == "ENTERPRISE"
                  else Decimal("1.00"))
    return rhu(raw * multiplier, 4)


def selector_sort_key(deal, frame, score):
    close_epoch = deal["close_date"].timestamp()
    created_epoch = deal["created_at"].timestamp()
    if frame["selection_basis"] == "STRATIFIED_BY_SEGMENT":
        return (-score, SEGMENT_RANK[deal["segment"]], -close_epoch,
                created_epoch, deal["_seq"])
    return (-score, -dec(deal["acr_usd"]), -close_epoch, created_epoch, deal["_seq"])


# =============================================================== incentives
def duration_factor(minutes):
    for threshold, factor in DURATION_LADDER:
        if minutes >= threshold:
            return factor
    return Decimal("0.00")


def incentive_amount(contact, analyst, program, start, end):
    """interview_incentive_amount (PRD 3.5). Rounds twice on the uplift path."""
    if contact["incentive_eligibility"] != "ELIGIBLE":
        return Decimal("0.00")
    base = TITLE_BAND_BASE_USD[contact["title_band"]]
    minutes = floor_minutes(end - start)
    factor = duration_factor(minutes)
    gross = rhu(base * factor, 2)
    if analyst["employment_type"] == "EXTERNAL_VENDOR":
        gross = rhu(gross * EXTERNAL_VENDOR_UPLIFT, 2)
    cap = rhu(program["interview_incentive_cap_usd"], 2)
    return gross if gross <= cap else cap


# =============================================================== substantiation
def substantiation(evidence_ids, claim_type, clock):
    """claim_substantiation_score: round each item, then sum, then round."""
    total = ZERO
    for response_id in dedup(evidence_ids):
        response = db.interview_responses.get(response_id)
        if response is None:
            continue
        weight = SOURCE_WEIGHT[response["question_key"]]
        if response.get("rating") is None:
            rating_factor = Decimal("1.00")
        else:
            rating_factor = RATING_BASE + RATING_STEP * Decimal(response["rating"])
        age_days = floor_days(clock - response["recorded_at"])
        recency_factor = (Decimal("1.00") if age_days <= RECENCY_WINDOW_DAYS
                          else STALE_RECENCY_FACTOR)
        total += rhu(weight * rating_factor * recency_factor, 2)
    score = rhu(total, 2)
    if score >= CORROBORATED_MIN:
        level = "CORROBORATED"
    elif score >= ANECDOTAL_MIN:
        level = "ANECDOTAL"
    else:
        level = "UNSUBSTANTIATED"
    points = CLAIM_TYPE_POINTS[claim_type] + LEVEL_ADJUSTMENT[level]
    points = max(1, min(3, points))
    return score, level, RISK_CLASS_BY_POINTS[points]


# =============================================================== risk index
def risk_indices(card):
    """battlecard_risk_index: five ordered stages (PRD 3.7)."""
    active = [c for c in claims_of_battlecard(card["id"])
              if c["legal_status"] != "REJECTED"]
    if not active:
        return Decimal("0.00"), Decimal("0.00")
    points = sum(RISK_POINTS[c["risk_class"]] for c in active)
    pre = rhu(Decimal(points) / Decimal(len(active)), 2)
    if pre >= HIGH_DISCOUNT_THRESHOLD:
        discount = HIGH_DISCOUNT
    elif pre >= MEDIUM_DISCOUNT_THRESHOLD:
        discount = MEDIUM_DISCOUNT
    else:
        discount = Decimal("0.00")
    cleared = len([c for c in active
                   if c["legal_status"] in ("APPROVED", "CONDITIONAL")])
    scale = rhu(Decimal(cleared) / Decimal(len(active)), 4)
    applied = rhu(discount * scale, 4)
    after_discount = rhu(pre * (Decimal("1") - applied), 2)
    conditional = len([c for c in active if c["legal_status"] == "CONDITIONAL"])
    final = after_discount + CONDITIONAL_SURCHARGE * Decimal(conditional)
    if final > RISK_CEILING:
        final = RISK_CEILING
    return pre, rhu(final, 2)


def claim_counts(card):
    claims = claims_of_battlecard(card["id"])
    return (
        len([c for c in claims if c["legal_status"] == "APPROVED"]),
        len([c for c in claims if c["legal_status"] == "CONDITIONAL"]),
        len([c for c in claims if c["legal_status"] == "REJECTED"]),
        len([c for c in claims if c["substantiation_level"] == "CORROBORATED"]),
    )


# =============================================================== adoption
def adoption_counts(card):
    assignments = assignments_of_battlecard(card["id"])
    assigned = len([a for a in assignments
                    if a["status"] in ("ASSIGNED", "FAILED", "TRAINED", "EXPIRED")])
    trained = len([a for a in assignments if a["status"] == "TRAINED"])
    if assigned == 0:
        rate = Decimal("0.0000")
    else:
        rate = rhu(Decimal(trained) / Decimal(assigned), 4)
    return assigned, trained, rate


def battlecard_derived(card):
    return (risk_indices(card), claim_counts(card), adoption_counts(card))


# =============================================================== product gaps
def gap_evidence_ids(gap):
    return dedup([gap["source_response_id"]] + list(gap.get("additional_response_ids") or []))


def gap_linked_deals(gap):
    deals = []
    seen = set()
    for response_id in gap_evidence_ids(gap):
        response = db.interview_responses.get(response_id)
        if response is None:
            continue
        deal = deal_of_response(response)
        if deal is None or deal["id"] in seen:
            continue
        seen.add(deal["id"])
        deals.append(deal)
    return deals


def gap_derived_competitor_id(gap):
    response = db.interview_responses.get(gap["source_response_id"])
    if response is None:
        return None
    deal = deal_of_response(response)
    if deal is None:
        return None
    return deal.get("primary_competitor_id")


def gap_metrics(gap):
    """product_gap_impact_score (PRD 3.9)."""
    deals = gap_linked_deals(gap)
    linked_deal_count = len(deals)
    ratified = [d for d in deals if d["attribution_status"] == "RATIFIED"]
    affected = rhu(sum((dec(d["acr_usd"]) for d in ratified), ZERO), 2)
    capped = affected / ACR_NORMALIZER_USD
    if capped > Decimal("1.0000"):
        capped = Decimal("1.0000")
    acr_component = rhu(rhu(capped, 4) * ACR_COMPONENT_WEIGHT, 2)
    frequency_component = Decimal(min(FREQUENCY_CAP, linked_deal_count) * FREQUENCY_WEIGHT)
    competitor_id = gap_derived_competitor_id(gap)
    competitor = db.competitors.get(competitor_id) if competitor_id else None
    pressure = (PRESSURE_FACTOR.get(competitor["tier"], Decimal("1.00"))
                if competitor else Decimal("1.00"))
    impact = rhu((acr_component + frequency_component) * pressure, 2)
    band = "P3"
    for threshold, name in BAND_LADDER:
        if impact >= threshold:
            band = name
            break
    return competitor_id, linked_deal_count, affected, impact, band


def gap_current_metrics(gap):
    """Live metrics while the gap is still re-scorable, frozen ones afterwards.

    The attribution supersede cascade re-scores only gaps in NEW or TRIAGED, so a
    gap leaving those states keeps the score it carried at that moment.
    """
    frozen = gap.get("_metrics")
    if frozen is not None:
        return frozen
    return gap_metrics(gap)


def freeze_gap_metrics(gap):
    gap["_metrics"] = gap_metrics(gap)


# =============================================================== attribution
def confidence_score(weight_primary, coverage_count):
    factor = COVERAGE_CONFIDENCE_BASE + COVERAGE_CONFIDENCE_STEP * Decimal(coverage_count)
    if factor > Decimal("1.00"):
        factor = Decimal("1.00")
    return rhu(dec(weight_primary) * factor, 2)
