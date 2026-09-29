"""Every calculation and derived-field rule (PRD sections 2.8, 2.10, 2.11, 3)."""
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from fractions import Fraction

from clock import clock
from store import by_created, db

D = Decimal
ONE = D("1.00")
DAY = 86400

# ---------------------------------------------------------------- constants
DECISION_WEIGHT = {"IRREVERSIBLE": D("40.0"), "REVERSIBLE": D("22.0")}
GAP_POINTS = {"NONE": D("0.0"), "PARTIAL": D("12.0"), "FULL": D("25.0")}
REACH_BUCKET_USERS = 10000
REACH_POINTS_PER_BUCKET = D("5.0")
REACH_POINTS_CAP = D("30.0")
URGENCY_TIER_1_DAYS = 14
URGENCY_TIER_2_DAYS = 45
SCORE_CAP = D("100.0")

METHOD_TABLE = {
    "DISCOVERY": "INTERVIEW",
    "EVALUATIVE": "USABILITY_TEST",
    "BEHAVIORAL_LONGITUDINAL": "DIARY_STUDY",
    "MEASUREMENT": "SURVEY",
}
SURVEY_MIN_AUDIENCE = 5000

SEGMENT_POINTS = D("40.0")
LOCALE_POINTS = D("20.0")
TARGET_POINTS_PER_HIT = D("15.0")
TARGET_POINTS_CAP = D("40.0")
SCREEN_IN_MIN = D("60.00")

SURCHARGE_TIER_1_UTIL = Fraction(1, 2)
SURCHARGE_TIER_2_UTIL = Fraction(4, 5)
SURCHARGE_TIER_1_PCT = D("0.05")
SURCHARGE_TIER_2_PCT = D("0.10")

SCREENOUT_STIPEND_CENTS = 200

CLASS_WEIGHT = {"DIRECT_QUOTE": D("1.00"), "OBSERVED_BEHAVIOR": D("0.85"), "SELF_REPORT": D("0.50")}
METHOD_MULT = {
    "USABILITY_TEST": D("1.20"),
    "DIARY_STUDY": D("1.10"),
    "INTERVIEW": D("1.00"),
    "SURVEY": D("0.70"),
}
PROVISIONAL_DIVISOR = D("4.00")
CORROBORATED_DIVISOR = D("3.00")
CORROBORATION_TARGET = 5
MIN_DISTINCT_PARTICIPANTS = 3
MIN_PUBLISH_STRENGTH = D("0.45")

SEVERITY_MULT = {"HIGH": D("1.50"), "MEDIUM": D("1.00"), "LOW": D("0.60")}
THEME_ESTABLISH_MIN = D("1.20")
THEME_MAX_DEPTH = 3

CONFIDENCE_DIVISOR = D("1.00")
LOCK_MIN_CONFIDENCE = D("0.60")

MAX_RETENTION_DAYS = {"RECORDING": 180, "TRANSCRIPT": 365, "PII_QUOTE": 90}
ARTIFACT_SCOPE = {"RECORDING": "RECORDING", "TRANSCRIPT": "TRANSCRIPT", "PII_NOTE": "PII_QUOTE"}

POSTURE_CLOSED_UTIL = Fraction(19, 20)
POSTURE_RESTRICTED_UTIL = Fraction(4, 5)
POSTURE_SUPPRESSED_RATIO = Fraction(1, 2)

NO_SHOW_SUPPRESSION_STRIKES = 2
POOL_MAX_CONCURRENT_FIELDING = 2
RESCHEDULE_LIMIT = 2
MAX_REVISION_ROUNDS = 2
SESSION_BUFFER = timedelta(minutes=30)

IMPACT_FINDINGS_TARGET = 3
IMPACT_ACCEPTED_POINTS = D("40.0")
IMPACT_FINDINGS_POINTS = D("30.0")
IMPACT_RECRUIT_POINTS = D("20.0")
IMPACT_FOLLOWUP_POINTS = D("10.0")


# ---------------------------------------------------------------- rounding
def r2(value):
    return D(value).quantize(D("0.01"), rounding=ROUND_HALF_UP)


def r4(value):
    return D(value).quantize(D("0.0001"), rounding=ROUND_HALF_UP)


def ceil_int(value):
    return int(D(value).to_integral_value(rounding=ROUND_CEILING))


def floor_days(later, earlier):
    """Whole days, floored, where one day is 86,400 seconds."""
    return (later - earlier).days


def set_field(entity, key, value):
    if entity.get(key) != value:
        entity[key] = value
        db.mark(entity)
        return True
    return False


# ------------------------------------------------- 3.1 intake scoring rules
def request_priority_score(req, decision):
    decision_points = DECISION_WEIGHT[decision["reversibility"]]
    gap_points = GAP_POINTS[req["evidence_gap"]]
    users = decision["impacted_user_count"]
    buckets = -(-users // REACH_BUCKET_USERS)
    reach_points = min(REACH_POINTS_CAP, D(buckets) * REACH_POINTS_PER_BUCKET)
    base = decision_points + gap_points + reach_points
    days = floor_days(decision["decision_deadline"], clock.now())
    if days <= URGENCY_TIER_1_DAYS:
        multiplier = D("1.30")
    elif days <= URGENCY_TIER_2_DAYS:
        multiplier = D("1.15")
    else:
        multiplier = D("1.00")
    return r2(min(SCORE_CAP, base * multiplier))


def method_recommendation(req, decision):
    recommended = METHOD_TABLE[req["question_type"]]
    if req["question_type"] == "MEASUREMENT" and decision["impacted_user_count"] < SURVEY_MIN_AUDIENCE:
        recommended = "INTERVIEW"
    return recommended


# ---------------------------------------------------- 3.5 screening scoring
def screen_score(recruitment, study):
    answers = recruitment.get("screening_answers") or {}
    criteria = study.get("screening_criteria") or {}
    submitted = answers.get("answers") or []
    disqualifying = criteria.get("disqualifying_answers") or []
    for item in submitted:
        if item in disqualifying:
            return r2(D("0.00"))
    segment_points = SEGMENT_POINTS if answers.get("segment") == criteria.get("required_segment") else D("0.0")
    locale_points = LOCALE_POINTS if answers.get("locale") == criteria.get("required_locale") else D("0.0")
    targets = criteria.get("target_answers") or []
    hits = sum(1 for item in submitted if item in targets)
    target_points = min(TARGET_POINTS_CAP, D(hits) * TARGET_POINTS_PER_HIT)
    return r2(segment_points + locale_points + target_points)


# ------------------------------------------- 3.2 / 2.10 pool ledger posture
def pool_utilization(pool):
    budget = pool["incentive_budget_cents"]
    committed = pool["incentive_reserved_cents"] + pool["incentive_paid_cents"]
    if budget <= 0:
        return Fraction(0)
    return Fraction(committed, budget)


def pool_participants(pool):
    return [p for p in db.participants.values() if p["pool_id"] == pool["id"]]


def recompute_pool(pool):
    """pool_posture: derived status plus the re-derived available balance."""
    people = pool_participants(pool)
    set_field(pool, "participant_count", len(people))
    suppressed = sum(1 for p in people if p["status"] == "SUPPRESSED")
    set_field(pool, "suppressed_participant_count", suppressed)
    set_field(
        pool,
        "incentive_available_cents",
        pool["incentive_budget_cents"] - pool["incentive_reserved_cents"] - pool["incentive_paid_cents"],
    )
    utilization = pool_utilization(pool)
    ratio = Fraction(suppressed, len(people)) if people else Fraction(0)
    if utilization >= POSTURE_CLOSED_UTIL:
        status = "CLOSED"
    elif utilization >= POSTURE_RESTRICTED_UTIL or ratio > POSTURE_SUPPRESSED_RATIO:
        status = "RESTRICTED"
    else:
        status = "OPEN"
    set_field(pool, "status", status)
    return pool


def reservation_amount(pool, study):
    """incentive_reservation, read from the pool state BEFORE the reservation."""
    utilization = pool_utilization(pool)
    if utilization < SURCHARGE_TIER_1_UTIL:
        pct = D("0.00")
    elif utilization < SURCHARGE_TIER_2_UTIL:
        pct = SURCHARGE_TIER_1_PCT
    else:
        pct = SURCHARGE_TIER_2_PCT
    base = study["incentive_amount_cents"]
    surcharge = ceil_int(D(base) * pct)
    return base + surcharge


# ------------------------------------------------ 3.2 participant posture
def participant_recruitments(participant):
    return [r for r in db.recruitments.values() if r["participant_id"] == participant["id"]]


def recompute_participant(participant):
    """participant_eligibility: rolling contact window plus derived posture."""
    pool = db.pools.get(participant["pool_id"])
    now = clock.now()
    window_days = pool["contact_window_days"] if pool else 0
    lower = now - timedelta(days=window_days)
    count = 0
    for row in participant_recruitments(participant):
        created = row["created_at"]
        if created > lower and created <= now:
            count += 1
    set_field(participant, "contacts_in_window", count)
    cap = pool["contact_cap_per_window"] if pool else 0
    if participant["no_show_strikes"] >= NO_SHOW_SUPPRESSION_STRIKES:
        status = "SUPPRESSED"
    elif count >= cap:
        status = "COOLDOWN"
    else:
        status = "ELIGIBLE"
    set_field(participant, "status", status)
    return participant


# ------------------------------------------------------ 3.3 study counters
def study_recruitments(study):
    return [r for r in db.recruitments.values() if r["study_id"] == study["id"]]


def recompute_study_counters(study):
    rows = study_recruitments(study)
    set_field(study, "invited_count", len(rows))
    set_field(
        study,
        "screened_in_count",
        sum(1 for r in rows if r["status"] in ("SCREENED_IN", "SCHEDULED", "COMPLETED", "NO_SHOW")),
    )
    set_field(study, "completed_count", sum(1 for r in rows if r["status"] == "COMPLETED"))


def recompute_recruitment_status(study):
    """RECRUITING <-> QUOTA_MET. NOT_STARTED and RECRUITMENT_FAILED do not move
    here: the first is left to the first invitation, the second is terminal."""
    current = study["recruitment_status"]
    if current in ("NOT_STARTED", "RECRUITMENT_FAILED"):
        return
    filled = sum(1 for r in study_recruitments(study) if r["status"] in ("SCHEDULED", "COMPLETED"))
    target = study["target_participant_count"]
    set_field(study, "recruitment_status", "QUOTA_MET" if filled >= target else "RECRUITING")


# ----------------------------------------------- 3.7 evidence and strength
def link_contribution(weight_class, method):
    """Each link's contribution is rounded to two decimals FIRST; the raw total
    is the sum of those already-rounded terms."""
    return r2(CLASS_WEIGHT[weight_class] * METHOD_MULT[method])


def finding_links(finding):
    return [l for l in db.links.values() if l["finding_id"] == finding["id"]]


def admissible_links(finding):
    return [l for l in finding_links(finding) if l["is_admissible"]]


def link_participant_id(link):
    artifact = db.artifacts.get(link["artifact_id"])
    if artifact is None:
        return None
    recruitment = db.recruitments.get(artifact["recruitment_id"])
    if recruitment is None:
        return None
    return recruitment["participant_id"]


def evidence_strength(raw_total, distinct_participants, variant):
    if variant == "PROVISIONAL":
        return r2(min(ONE, D(raw_total) / PROVISIONAL_DIVISOR))
    density = r4(min(ONE, D(raw_total) / CORROBORATED_DIVISOR))
    factor = r2(min(ONE, D(distinct_participants) / D(CORROBORATION_TARGET)))
    return r2(density * factor)


def recompute_finding(finding):
    """evidence_strength under the finding's own current variant, plus the two
    counters that feed it."""
    links = admissible_links(finding)
    raw_total = sum((l["contribution"] for l in links), D("0.00"))
    people = set()
    for link in links:
        pid = link_participant_id(link)
        if pid is not None:
            people.add(pid)
    variant = "PROVISIONAL" if finding["status"] == "DRAFT" else "CORROBORATED"
    set_field(finding, "admissible_link_count", len(links))
    set_field(finding, "distinct_participant_count", len(people))
    set_field(finding, "strength_variant", variant)
    set_field(finding, "evidence_strength", evidence_strength(raw_total, len(people), variant))
    return finding


# ------------------------------------------------- 3.7 theme weight rollup
def theme_children(theme):
    return [t for t in db.themes.values() if t["parent_theme_id"] == theme["id"]]


def theme_findings(theme):
    return [f for f in db.findings.values() if f["theme_id"] == theme["id"]]


def theme_subtree_ids(theme):
    ids = {theme["id"]}
    for child in theme_children(theme):
        ids |= theme_subtree_ids(child)
    return ids


def _theme_own_weight(theme):
    total = D("0.00")
    for finding in theme_findings(theme):
        if finding["status"] != "PUBLISHED":
            continue
        total += r2(D(finding["evidence_strength"]) * SEVERITY_MULT[finding["severity"]])
    return r2(total)


def _theme_rollup(theme):
    total = D(theme["own_evidence_weight"])
    for child in theme_children(theme):
        total += D(child["evidence_weight"])
    return r2(total)


def _recompute_theme_row(theme):
    set_field(theme, "own_evidence_weight", _theme_own_weight(theme))
    set_field(theme, "evidence_weight", _theme_rollup(theme))
    set_field(
        theme,
        "status",
        "ESTABLISHED" if D(theme["evidence_weight"]) >= THEME_ESTABLISH_MIN else "EMERGING",
    )


def _post_order(theme):
    for child in theme_children(theme):
        _post_order(child)
    _recompute_theme_row(theme)


def refresh_theme_weights(theme):
    """Children before parents in a post-order walk, then the affected theme's
    ancestors from that theme upward to the root one level at a time."""
    if theme is None:
        return
    _post_order(theme)
    current = db.themes.get(theme["parent_theme_id"]) if theme["parent_theme_id"] else None
    while current is not None:
        _recompute_theme_row(current)
        current = db.themes.get(current["parent_theme_id"]) if current["parent_theme_id"] else None


def bump_theme_reuse(theme):
    """reuse_count rises for the theme of a cited finding and for each of that
    theme's ancestors up to the root."""
    current = theme
    while current is not None:
        set_field(current, "reuse_count", current["reuse_count"] + 1)
        current = db.themes.get(current["parent_theme_id"]) if current["parent_theme_id"] else None


# ------------------------------------------- 3.8 decision evidence confidence
def decision_readouts(decision):
    return [r for r in db.readouts.values() if r["roadmap_decision_id"] == decision["id"]]


def study_findings(study_id):
    return [f for f in db.findings.values() if f["study_id"] == study_id]


def readout_contribution(readout):
    study = db.studies.get(readout["study_id"])
    published = [f for f in study_findings(readout["study_id"]) if f["status"] == "PUBLISHED"]
    if not published or study is None:
        return D("0.00")
    total = sum((D(f["evidence_strength"]) for f in published), D("0"))
    mean = r4(total / D(len(published)))
    return r2(mean * METHOD_MULT[study["method"]])


def decision_evidence_confidence(decision):
    accepted = [r for r in decision_readouts(decision) if r["status"] == "ACCEPTED"]
    total = D("0.00")
    for readout in by_created(accepted):
        total += readout_contribution(readout)
    return r2(min(ONE, total / CONFIDENCE_DIVISOR))


def recompute_decision_confidence(decision):
    value = decision_evidence_confidence(decision)
    set_field(decision, "evidence_confidence", value)
    return value


# ------------------------------------------------------ 3.6 retention horizon
def retention_horizon(granted_at, scopes, retention_days):
    """The tighter of what was asked for and what the scopes permit."""
    scope_cap = min(MAX_RETENTION_DAYS[s] for s in scopes)
    days = min(scope_cap, retention_days)
    return granted_at + timedelta(days=days)


# ------------------------------------------------------- 3.4 batch selector
def auto_invite_candidates(study, pool):
    """Deterministic candidate set and total ranking."""
    required_segment = (study.get("screening_criteria") or {}).get("required_segment")
    already = {r["participant_id"] for r in study_recruitments(study)}
    candidates = []
    for person in db.participants.values():
        if person["pool_id"] != pool["id"]:
            continue
        if person["status"] != "ELIGIBLE":
            continue
        if person["segment"] != required_segment:
            continue
        if person["no_show_strikes"] >= NO_SHOW_SUPPRESSION_STRIKES:
            continue
        if person["contacts_in_window"] >= pool["contact_cap_per_window"]:
            continue
        if person["id"] in already:
            continue
        candidates.append(person)
    candidates.sort(
        key=lambda p: (p["contacts_in_window"], p["no_show_strikes"], p["created_at"], p["_seq"])
    )
    return candidates


# ----------------------------------------------------------- 3.9 study metrics
def study_readouts(study):
    return [r for r in db.readouts.values() if r["study_id"] == study["id"]]


def study_metrics(study):
    readouts = study_readouts(study)
    delivered = [
        r for r in readouts
        if r["status"] in ("DELIVERED", "ACCEPTED", "DEFERRED") and r["delivered_at"] is not None
    ]
    if delivered:
        earliest = sorted(delivered, key=lambda r: (r["delivered_at"], r["created_at"], r["_seq"]))[0]
        cycle_time_days = floor_days(earliest["delivered_at"], study["created_at"])
    else:
        cycle_time_days = None
    if study["fielding_closed_at"] is not None and study["fielded_at"] is not None:
        fielding_days = floor_days(study["fielding_closed_at"], study["fielded_at"])
    else:
        fielding_days = None
    invited = study["invited_count"]
    if invited == 0:
        efficiency = r4(D("0"))
    else:
        efficiency = r4(D(study["completed_count"]) / D(invited))
    published = sum(1 for f in study_findings(study["id"]) if f["status"] == "PUBLISHED")

    acceptance_term = IMPACT_ACCEPTED_POINTS if any(r["status"] == "ACCEPTED" for r in readouts) else D("0.0")
    acceptance_term = r2(acceptance_term)
    findings_term = r2(min(D("1.0"), D(published) / D(IMPACT_FINDINGS_TARGET)) * IMPACT_FINDINGS_POINTS)
    recruit_term = r2(efficiency * IMPACT_RECRUIT_POINTS)
    followups = []
    for readout in readouts:
        followups.extend([f for f in db.followups.values() if f["readout_id"] == readout["id"]])
    if followups and all(f["status"] == "DONE" for f in followups):
        followup_term = r2(IMPACT_FOLLOWUP_POINTS)
    else:
        followup_term = r2(D("0.0"))
    impact = r2(acceptance_term + findings_term + recruit_term + followup_term)
    return {
        "study_id": study["id"],
        "cycle_time_days": cycle_time_days,
        "fielding_days": fielding_days,
        "recruitment_efficiency": float(efficiency),
        "published_findings": published,
        "impact_score": float(impact),
    }
