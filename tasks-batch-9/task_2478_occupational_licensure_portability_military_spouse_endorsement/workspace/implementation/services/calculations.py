"""Every calculation rule of SCAFFOLD §1.3, written to the prose of PRD §3."""
from decimal import Decimal

import clock
import db
from constants import (
    CONVERSION_FACTOR, CRITICAL_MISS_PENALTY, DECAY_FLOOR, DECAY_PER_FULL_YEAR,
    EXPEDITE_PROCESSING_DAYS, GOOD_STANDING_MAX_INDEX, INDEX_CEILING,
    MILITARY_ELIGIBLE, MILITARY_FULL_WAIVER_CAP_CENTS, PERMIT_GRACE_DAYS,
    PERMIT_MAX_DAYS, SEVERITY_POINTS, W_HOURS, W_SCOPE, W_STANDING,
    BLOCKING_SEVERITIES,
)
from numbers_util import dec, rhu1, rhu2, rhu_cents

ZERO = Decimal("0")


# ---------------------------------------------------------------------------
# helpers over the store
# ---------------------------------------------------------------------------
def application_ledger(application_id):
    return db.ordered([e for e in db.ledger_entries.values()
                       if e["application_id"] == application_id])


def unexpired_compact(profession_id, state_code):
    """The single reciprocal agreement covering (profession, applicant state)
    that has not expired at the logical clock; the compact applies while
    clock_now <= expires_on."""
    now = clock.now()
    for row in db.ordered(db.reciprocal_agreements.values()):
        if (row["profession_id"] == profession_id
                and row["partner_state"] == state_code
                and now <= row["expires_on"]):
            return row
    return None


# ---------------------------------------------------------------------------
# calculations.application_fee_balance
# ---------------------------------------------------------------------------
def fee_balance_cents(application_id):
    return sum(e["amount_cents"] for e in db.ledger_entries.values()
               if e["application_id"] == application_id)


# ---------------------------------------------------------------------------
# calculations.applicant_disciplinary_risk_index
# ---------------------------------------------------------------------------
def _sweep(rows, variant_key):
    ordered_rows = sorted(rows, key=lambda r: (r[variant_key], r["created_at"],
                                               r["_seq"]))
    now = clock.now()
    running = Decimal("0.00")
    for row in ordered_rows:
        age_years = clock.whole_365_day_blocks(now, row[variant_key])
        factor = Decimal("1.0") - DECAY_PER_FULL_YEAR * dec(age_years)
        if factor < DECAY_FLOOR:
            factor = DECAY_FLOOR
        contribution = rhu2(SEVERITY_POINTS[row["severity"]] * factor)
        running = running + contribution
        if running > INDEX_CEILING:
            running = INDEX_CEILING
    return rhu2(running)


def disciplinary_risk_indexes(applicant_id):
    """Returns (reported_index, effective_index, good_standing_flag)."""
    rows = [r for r in db.disciplinary_records.values()
            if r["applicant_id"] == applicant_id and not r["resolved"]]
    reported = _sweep(rows, "reported_at")
    effective = _sweep(rows, "action_effective_at")
    blocking = any(r["severity"] in BLOCKING_SEVERITIES for r in rows)
    good_standing = (not blocking) and reported < GOOD_STANDING_MAX_INDEX
    return reported, effective, good_standing


def pathway_risk_index(application):
    applicant = db.applicants.get(application["applicant_id"])
    if applicant is None:
        return Decimal("0.00")
    if application["pathway"] == "UNIVERSAL_RECOGNITION":
        return applicant["disciplinary_risk_index_reported"]
    return applicant["disciplinary_risk_index_effective"]


# ---------------------------------------------------------------------------
# calculations.review_deadline
# ---------------------------------------------------------------------------
def review_deadline(application, profession, submitted_at):
    if application["expedited"] or application["pathway"] == "MILITARY_SPOUSE_EXPEDITED":
        processing_days = EXPEDITE_PROCESSING_DAYS
    else:
        processing_days = profession["standard_processing_days"]
    return clock.add_days(submitted_at, processing_days)


# ---------------------------------------------------------------------------
# calculations.net_fee_due_cents
# ---------------------------------------------------------------------------
def net_fee_due(application, applicant, profession):
    # STEP 1 — components, pre-waiver
    base_component = profession["base_fee_cents"]
    endorsement_component = (
        profession["endorsement_fee_cents"]
        if application["pathway"] in ("ENDORSEMENT", "UNIVERSAL_RECOGNITION") else 0
    )
    exam_component = profession["exam_fee_cents"]
    jurisprudence_component = (
        profession["jurisprudence_fee_cents"]
        if profession["jurisprudence_exam_required"] else 0
    )
    gross_subtotal = (base_component + endorsement_component
                      + exam_component + jurisprudence_component)
    # STEP 2 — expedite surcharge, keyed on the STEP 1 subtotal
    expedite_surcharge = (
        rhu_cents(dec(gross_subtotal) * profession["expedite_surcharge_pct"])
        if application["expedited"] else 0
    )
    # STEP 3
    gross_total = gross_subtotal + expedite_surcharge
    # STEP 4 — waiver tier, keyed on gross_total (never on the net)
    if (application["pathway"] == "MILITARY_SPOUSE_EXPEDITED"
            or applicant["military_status"] in MILITARY_ELIGIBLE):
        waiver_pct = (Decimal("1.00")
                      if gross_total <= MILITARY_FULL_WAIVER_CAP_CENTS
                      else Decimal("0.50"))
    else:
        compact = unexpired_compact(application["profession_id"],
                                    applicant["state_code"])
        waiver_pct = compact["fee_waiver_pct"] if compact else Decimal("0.00")
    # STEP 5 — round per component, then sum
    waiver_credit = (
        rhu_cents(dec(base_component) * waiver_pct)
        + rhu_cents(dec(endorsement_component) * waiver_pct)
        + rhu_cents(dec(exam_component) * waiver_pct)
        + rhu_cents(dec(jurisprudence_component) * waiver_pct)
        + rhu_cents(dec(expedite_surcharge) * waiver_pct)
    )
    # STEP 6
    return {
        "gross_subtotal_cents": gross_subtotal,
        "expedite_surcharge_cents": expedite_surcharge,
        "gross_total_cents": gross_total,
        "statutory_waiver_pct": waiver_pct,
        "waiver_credit_cents": waiver_credit,
        "net_fee_due_cents": gross_total - waiver_credit,
    }


# ---------------------------------------------------------------------------
# calculations.substantial_equivalency_score
# ---------------------------------------------------------------------------
def scope_comparison(profession, credential):
    required = profession["required_scope_elements"]
    granted = set(credential["scope_elements"])
    matched = [e for e in required if e in granted]
    missing = [e for e in required if e not in granted]
    return matched, missing


def substantial_equivalency_score(evaluation, profession, credential, applicant):
    required = profession["required_scope_elements"]
    matched = evaluation["matched_scope_elements"]
    missing = evaluation["missing_scope_elements"]
    scope_ratio = dec(len(matched)) / dec(len(required))
    hours_ratio = dec(credential["practice_hours"]) / dec(profession["required_practice_hours"])
    if hours_ratio > Decimal("1.0"):
        hours_ratio = Decimal("1.0")
    if (evaluation["variant"] == "UNIVERSAL_RECOGNITION"
            and applicant["residency_months"]
            >= profession["universal_recognition_min_residency_months"]):
        hours_ratio = Decimal("1.0")
    standing = Decimal("1.0") if credential["verified_good_standing"] else Decimal("0.0")
    raw = W_SCOPE * scope_ratio + W_HOURS * hours_ratio + W_STANDING * standing
    critical = set(profession["critical_scope_elements"])
    critical_miss = len([e for e in missing if e in critical])
    penalty = (CRITICAL_MISS_PENALTY * dec(critical_miss)
               if evaluation["variant"] == "STRICT_SCOPE" else Decimal("0.0"))
    score = rhu2(raw * Decimal(100) - penalty)
    if score < Decimal("0.00"):
        score = Decimal("0.00")
    if score > Decimal("100.00"):
        score = Decimal("100.00")
    return score


# ---------------------------------------------------------------------------
# calculations.military_credit_hours
# ---------------------------------------------------------------------------
def awarded_hours_for(training_record):
    return rhu1(dec(training_record["documented_hours"])
                * CONVERSION_FACTOR[training_record["category"]])


def recompute_requirement_hours(application, profession):
    awards = db.ordered([a for a in db.credit_awards.values()
                         if a["application_id"] == application["id"]
                         and a["status"] == "AWARDED"])
    raw_sum = Decimal("0.0")
    for award in awards:
        raw_sum = raw_sum + award["awarded_hours"]
    total = profession["requirement_hours_total"]
    satisfied = rhu1(raw_sum)
    if satisfied > total:
        satisfied = total
    application["requirement_hours_satisfied"] = satisfied
    application["requirement_hours_remaining"] = rhu1(total - satisfied)


# ---------------------------------------------------------------------------
# calculations.permit_window
# ---------------------------------------------------------------------------
def permit_window(application, profession, effective_at):
    permit_max_days = PERMIT_MAX_DAYS[application["pathway"]]
    candidate_pathway_cap = clock.add_days(effective_at, permit_max_days)
    candidate_review_cap = clock.add_days(application["review_deadline_at"],
                                          PERMIT_GRACE_DAYS)
    expires_at = min(candidate_pathway_cap, candidate_review_cap)
    permit_fee = profession["permit_fee_cents"] - rhu_cents(
        dec(profession["permit_fee_cents"]) * application["statutory_waiver_pct"])
    return permit_max_days, expires_at, permit_fee


# ---------------------------------------------------------------------------
# calculations.permit_conversion_credit_cents
# ---------------------------------------------------------------------------
def permit_conversion_credit_cents(permit, pre_truncation_expires_at, now):
    total_days = clock.whole_days(pre_truncation_expires_at, permit["effective_at"])
    elapsed_days = clock.whole_days(now, permit["effective_at"])
    unused_days = total_days - elapsed_days
    if unused_days < 0:
        unused_days = 0
    if total_days == 0:
        return 0
    return rhu_cents(dec(permit["permit_fee_cents"]) * dec(unused_days)
                     / dec(total_days))


# ---------------------------------------------------------------------------
# calculations.evaluation_overall_status
# ---------------------------------------------------------------------------
def evaluation_overall_status(evaluation):
    if (evaluation["scope_review_status"] != "PENDING"
            and evaluation["discipline_review_status"] != "PENDING"
            and evaluation["finalized_at"] is not None):
        return "COMPLETE"
    return "IN_PROGRESS"


# ---------------------------------------------------------------------------
# calculations.evaluator_open_assignment_count
# ---------------------------------------------------------------------------
def open_assignment_count(evaluator_id):
    return len([a for a in db.assignments.values()
                if a["evaluator_id"] == evaluator_id and a["status"] == "ASSIGNED"])


def refresh_open_assignment_count(evaluator):
    evaluator["open_assignment_count"] = open_assignment_count(evaluator["id"])


# ---------------------------------------------------------------------------
# calculations.processing_time_metrics
# ---------------------------------------------------------------------------
def processing_time_metrics(application):
    decided_at = application["decided_at"]
    reference = decided_at if decided_at is not None else clock.now()
    if application["submitted_at"] is None:
        elapsed = 0
    else:
        elapsed = clock.whole_days(reference, application["submitted_at"])
    if decided_at is None:
        standard_met = None
    else:
        standard_met = decided_at <= application["review_deadline_at"]
    return elapsed, standard_met
