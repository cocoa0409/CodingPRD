"""Calculation rules per SCAFFOLD table 3 / PRD section 3."""
import re
from decimal import Decimal, ROUND_HALF_UP

import db
from helpers import make_record, touch, dec4

_Q4 = Decimal("0.0001")


def round4_dec(value):
    return Decimal(value).quantize(_Q4, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# case_priority_score (PRD 3.2)
# ---------------------------------------------------------------------------

def acuity_multiplier(soi, rom):
    """Tier 2 acuity multiplier, non-linear in SOI/ROM.

    Enumerated bands: (1,1)->1.00; (2,<=2)->1.10; soi==3 or rom==3 ->1.25;
    soi==4 or rom==4 ->1.50. Bands are severity-ascending, so the highest
    applicable band wins; equivalently driven by max(soi, rom).
    """
    m = max(soi, rom)
    if m <= 1:
        return Decimal("1.00")
    if m == 2:
        return Decimal("1.10")
    if m == 3:
        return Decimal("1.25")
    return Decimal("1.50")


def los_factor(current_period_index, discharge_period):
    """Tier 3 length-of-stay pressure."""
    if current_period_index > discharge_period:
        return Decimal("1.30")
    if current_period_index == discharge_period:
        return Decimal("1.15")
    return Decimal("1.00")


def compute_priority(case):
    """Recompute priority_score in place (no version bump — a system refresh).

    Provisional variant: case in {OPEN, UNDER_REVIEW} with at least one query
    in {DRAFT, SENT, ESCALATED} -> base uses max(working, best proposed).
    Residual variant: otherwise (incl. RECONCILED) -> working - initial only.
    Cases in FINAL_CODED / CLOSED are excluded from the computation.
    """
    if case["status"] not in ("OPEN", "UNDER_REVIEW", "RECONCILED"):
        return
    program = db.programs.get(case["cdi_program_id"])
    now_p = program["current_period_index"] if program is not None else 0
    open_qs = [
        q for q in db.queries.values()
        if q["patient_case_id"] == case["id"]
        and q["status"] in ("DRAFT", "SENT", "ESCALATED")
    ]
    initial = dec4(case["initial_drg_weight"])
    working = dec4(case["working_drg_weight"])
    if case["status"] in ("OPEN", "UNDER_REVIEW") and open_qs:
        best = max([working] + [dec4(q["proposed_drg_weight"]) for q in open_qs])
        base = best - initial
    else:
        base = working - initial
    if base < 0:
        base = Decimal("0")
    acuity = acuity_multiplier(case["working_soi"], case["working_rom"])
    los = los_factor(now_p, case["discharge_period"])
    score = (base * acuity * los * Decimal("100")).quantize(_Q4, rounding=ROUND_HALF_UP)
    case["priority_score"] = float(score)


# ---------------------------------------------------------------------------
# non_leading_lint (PRD 3.4)
# ---------------------------------------------------------------------------

LEADING_PHRASES = [
    "do you agree that",
    "isn't it true",
    "clearly indicates",
    "should be coded as",
    "please document",
    "the patient has",
    "confirm the diagnosis of",
]


def lint_query(query_text, clinical_indicators, proposed_drg_code):
    """Return the list of lint finding codes for a candidate query."""
    findings = []
    lower = query_text.lower()
    for phrase in LEADING_PHRASES:
        if phrase in lower:
            findings.append(f"LEADING_PHRASE({phrase})")
    if proposed_drg_code:
        token = re.escape(str(proposed_drg_code))
        if re.search(r"(?<![0-9A-Za-z])" + token + r"(?![0-9A-Za-z])", query_text):
            findings.append("ANSWER_IN_QUESTION")
    if not clinical_indicators:
        findings.append("NO_INDICATORS")
    return findings


# ---------------------------------------------------------------------------
# provider_education_band (PRD 3.8)
# ---------------------------------------------------------------------------

def education_band(score):
    if score >= 85:
        return "NONE"
    if score >= 70:
        return "WATCH"
    if score >= 50:
        return "COACHING"
    return "INTENSIVE_REVIEW"


def refresh_provider_standing(provider):
    """Recompute education_score / education_flag / pattern tally from the
    provider's full event history, then mark the provider modified."""
    events = [
        e for e in db.education_events.values()
        if e["provider_id"] == provider["id"]
    ]
    total = sum(e["points_deducted"] for e in events)
    provider["education_score"] = max(0, 100 - total)
    provider["education_flag"] = education_band(provider["education_score"])
    tally = {}
    for e in events:
        tally[e["pattern_tag"]] = tally.get(e["pattern_tag"], 0) + 1
    provider["pattern_tally_json"] = tally
    touch(provider)


def record_education(provider, pattern_tag, points, source_query_id, note):
    """Create a ProviderEducationEvent (auto or manual) and refresh standing."""
    program = db.programs.get(provider["cdi_program_id"])
    period = program["current_period_index"] if program is not None else 0
    event = make_record(db.education_events, {
        "provider_id": provider["id"],
        "cdi_program_id": provider["cdi_program_id"],
        "pattern_tag": pattern_tag,
        "points_deducted": points,
        "source_query_id": source_query_id,
        "note": note,
        "recorded_period": period,
    })
    refresh_provider_standing(provider)
    return event


# ---------------------------------------------------------------------------
# review_opportunity_deltas (PRD 3.6)
# ---------------------------------------------------------------------------

def recompute_review_deltas(review):
    """Cumulative realized wins over the review's RESPONDED-with-AGREE queries."""
    case = db.cases.get(review["patient_case_id"])
    initial = dec4(case["initial_drg_weight"]) if case is not None else Decimal("0")
    weight = Decimal("0")
    soi = 0
    rom = 0
    for q in db.queries.values():
        if q["cdi_review_id"] != review["id"] or q["status"] != "RESPONDED":
            continue
        resp = db.responses.get(q["response_id"] or "")
        if resp is None or resp["response_type"] != "AGREE":
            continue
        weight += dec4(q["proposed_drg_weight"]) - initial
        soi += q["proposed_soi"] - 1
        rom += q["proposed_rom"] - 1
    review["opportunity_weight_delta"] = float(round4_dec(weight))
    review["opportunity_soi_delta"] = soi
    review["opportunity_rom_delta"] = rom


# ---------------------------------------------------------------------------
# Clock-advance sweep: auto-escalation and NO_RESPONSE closure (PRD 3.5)
# ---------------------------------------------------------------------------

def bump_review(query):
    """A child query advancing (auto-escalation / NO_RESPONSE) moves the owning
    review forward too (see OCC rule cdi-review-close-stale-version)."""
    review = db.reviews.get(query["cdi_review_id"])
    if review is not None:
        touch(review)


def run_clock_sweep(program):
    """One escalation evaluation per open query, then priority recomputation."""
    now_p = program["current_period_index"]
    pending = [
        q for q in db.queries.values()
        if q["cdi_program_id"] == program["id"] and q["status"] in ("SENT", "ESCALATED")
    ]
    pending.sort(key=lambda q: q["_seq"])
    for q in pending:
        policy = db.policies.get(q["escalation_policy_id"])
        if policy is None:
            continue
        stage = q["escalation_stage"]
        threshold = q["due_period"] + stage * policy["escalation_stage_periods"]
        if now_p <= threshold:
            continue
        provider = db.providers.get(q["provider_id"])
        if stage < policy["max_escalation_stage"]:
            q["escalation_stage"] = stage + 1
            q["status"] = "ESCALATED"
            q["last_escalated_period"] = now_p
            touch(q)
            if provider is not None:
                record_education(provider, "NO_RESPONSE_PATTERN", 3, q["id"], "")
            bump_review(q)
        else:
            # stage == policy.max_escalation_stage and final threshold crossed.
            q["status"] = "NO_RESPONSE"
            touch(q)
            if provider is not None:
                record_education(provider, "NO_RESPONSE_PATTERN", 6, q["id"], "")
            bump_review(q)
    for case in db.cases.values():
        if case["cdi_program_id"] == program["id"] and case["status"] in (
            "OPEN", "UNDER_REVIEW", "RECONCILED",
        ):
            compute_priority(case)


# ---------------------------------------------------------------------------
# Denial-prevention helpers (PRD 3.7 / 3.9)
# ---------------------------------------------------------------------------

def agreed_indicators(case):
    """Union of clinical_indicators across the case's RESPONDED+AGREE queries."""
    agreed = set()
    for q in db.queries.values():
        if q["patient_case_id"] != case["id"] or q["status"] != "RESPONDED":
            continue
        resp = db.responses.get(q["response_id"] or "")
        if resp is not None and resp["response_type"] == "AGREE":
            agreed.update(q["clinical_indicators"])
    return agreed


def applicable_targets(program_id, drg_code, period):
    """Targets whose DRG matches and whose inclusive window contains period."""
    return [
        t for t in db.targets.values()
        if t["cdi_program_id"] == program_id
        and t["drg_code"] == drg_code
        and t["active_from_period"] <= period <= t["active_to_period"]
    ]


def target_unmet(target, case, agreed):
    if any(tag not in agreed for tag in target["required_evidence_tags"]):
        return True
    return case["working_soi"] < target["severity_floor"]
