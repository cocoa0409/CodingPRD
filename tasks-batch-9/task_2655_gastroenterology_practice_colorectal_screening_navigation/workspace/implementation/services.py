"""Lookups, ledger recomputation and the cross-resource cascades."""
from core import (
    by_seq,
    db,
    fail,
    new_record,
    now_iso,
    parse_instant,
    today,
    touch,
)
from calcs import (
    NAVIGATION_HIGH_PRIORITY_EPISODES,
    OPEN_CLINICAL_STATUSES,
    computed_interval_months,
    episode_due_date,
    finalized_pathology_aggregate,
    next_due_date,
    prep_adherence_score,
    price_claim,
    recompute_session_ledger,
    screening_eligibility,
)


# --------------------------------------------------------------------------
# Lookups (precedence 4 / 5)
# --------------------------------------------------------------------------
def get_plan(plan_id):
    row = db.plans.get(plan_id)
    if row is None:
        fail("ERR_PLAN_NOT_FOUND", "InsurancePlan %s was not found." % plan_id)
    return row


def get_patient(patient_id):
    row = db.patients.get(patient_id)
    if row is None:
        fail("ERR_PATIENT_NOT_FOUND", "Patient %s was not found." % patient_id)
    return row


def get_clinician(clinician_id):
    row = db.clinicians.get(clinician_id)
    if row is None:
        fail("ERR_CLINICIAN_NOT_FOUND", "Clinician %s was not found." % clinician_id)
    return row


def get_session(session_id):
    row = db.sessions.get(session_id)
    if row is None:
        fail("ERR_SESSION_NOT_FOUND", "EndoscopySession %s was not found." % session_id)
    return row


def get_coverage(coverage_id):
    row = db.coverages.get(coverage_id)
    if row is None:
        fail("ERR_COVERAGE_NOT_FOUND", "AnesthesiaCoverage %s was not found." % coverage_id)
    return row


def get_referral(referral_id):
    row = db.referrals.get(referral_id)
    if row is None:
        fail("ERR_REFERRAL_NOT_FOUND", "Referral %s was not found." % referral_id)
    return row


def get_episode(episode_id):
    row = db.episodes.get(episode_id)
    if row is None:
        fail("ERR_EPISODE_NOT_FOUND", "ScreeningEpisode %s was not found." % episode_id)
    return row


def get_test(test_id):
    row = db.tests.get(test_id)
    if row is None:
        fail("ERR_TEST_NOT_FOUND", "NoninvasiveTest %s was not found." % test_id)
    return row


def get_booking(booking_id):
    row = db.bookings.get(booking_id)
    if row is None:
        fail("ERR_BOOKING_NOT_FOUND", "ProcedureBooking %s was not found." % booking_id)
    return row


def get_report(report_id):
    row = db.reports.get(report_id)
    if row is None:
        fail("ERR_PATHOLOGY_NOT_FOUND", "PathologyReport %s was not found." % report_id)
    return row


def get_recommendation(recommendation_id):
    row = db.recommendations.get(recommendation_id)
    if row is None:
        fail("ERR_RECOMMENDATION_NOT_FOUND",
             "SurveillanceRecommendation %s was not found." % recommendation_id)
    return row


def get_claim(claim_id):
    row = db.claims.get(claim_id)
    if row is None:
        fail("ERR_CLAIM_NOT_FOUND", "BillingClaim %s was not found." % claim_id)
    return row


def get_period(period_id):
    row = db.periods.get(period_id)
    if row is None:
        fail("ERR_QUALITY_PERIOD_NOT_FOUND", "QualityPeriod %s was not found." % period_id)
    return row


# --------------------------------------------------------------------------
# Derived parent fields
# --------------------------------------------------------------------------
def recompute_patient_counts(patient):
    """Full recompute of open_episode_count / navigation_priority from all children."""
    count = sum(
        1 for e in db.episodes.values()
        if e["patient_id"] == patient["id"] and e["clinical_status"] in OPEN_CLINICAL_STATUSES
    )
    priority = "HIGH" if count >= NAVIGATION_HIGH_PRIORITY_EPISODES else "ROUTINE"
    changed = (patient["open_episode_count"] != count
               or patient["navigation_priority"] != priority)
    patient["open_episode_count"] = count
    patient["navigation_priority"] = priority
    if changed:
        touch(patient)
    return changed


def booking_claim(booking_id):
    for claim in db.claims.values():
        if claim["booking_id"] == booking_id:
            return claim
    return None


def episode_anchor_booking(episode_id):
    candidates = [b for b in db.bookings.values() if b["episode_id"] == episode_id]
    completed = [b for b in candidates if b["status"] == "COMPLETED"]
    pool = completed or [b for b in candidates if b["status"] != "CANCELLED"] or candidates
    if not pool:
        return None
    return by_seq(pool)[-1]


# --------------------------------------------------------------------------
# Claims
# --------------------------------------------------------------------------
def create_claim_for_booking(booking, session, episode, patient):
    plan = db.plans[patient["insurance_plan_id"]]
    priced = price_claim("PROVISIONAL", booking, session, episode, plan, patient)
    claim = new_record({
        "booking_id": booking["id"],
        "insurance_plan_id": patient["insurance_plan_id"],
        "classification": priced["classification"],
        "variant": "PROVISIONAL",
        "line_items": priced["line_items"],
        "base_allowed_cents": priced["base_allowed_cents"],
        "complexity_tier": priced["complexity_tier"],
        "allowed_amount_cents": priced["allowed_amount_cents"],
        "deductible_applied_cents": priced["deductible_applied_cents"],
        "coinsurance_cents": priced["coinsurance_cents"],
        "patient_responsibility_cents": priced["patient_responsibility_cents"],
        "plan_paid_cents": priced["plan_paid_cents"],
        "status": "PROVISIONAL_PRICED",
        "reprice_count": 0,
        "dispute_reason": None,
    })
    db.claims[claim["id"]] = claim
    booking["planned_classification"] = priced["classification"]
    return claim


def apply_final_pricing(claim, touch_booking=True):
    booking = db.bookings[claim["booking_id"]]
    session = db.sessions[booking["session_id"]]
    episode = db.episodes[booking["episode_id"]]
    patient = db.patients[episode["patient_id"]]
    plan = db.plans[claim["insurance_plan_id"]]
    priced = price_claim("FINAL", booking, session, episode, plan, patient)
    claim.update(priced)
    claim["variant"] = "FINAL"
    claim["status"] = "REPRICED"
    claim["reprice_count"] = int(claim["reprice_count"]) + 1
    touch(claim)
    booking["final_classification"] = priced["classification"]
    if touch_booking:
        touch(booking)
    return claim


def void_claim(claim):
    claim["status"] = "VOIDED"
    claim["line_items"] = []
    claim["base_allowed_cents"] = 0
    claim["allowed_amount_cents"] = 0
    claim["deductible_applied_cents"] = 0
    claim["coinsurance_cents"] = 0
    claim["patient_responsibility_cents"] = 0
    claim["plan_paid_cents"] = 0
    touch(claim)


# --------------------------------------------------------------------------
# Episodes
# --------------------------------------------------------------------------
def build_episode(patient, indication, referral_id, preceding_episode_id, origin):
    index_date = today()
    eligibility = screening_eligibility(indication, patient, index_date)
    episode = new_record({
        "patient_id": patient["id"],
        "referral_id": referral_id,
        "preceding_episode_id": preceding_episode_id,
        "indication": indication,
        "origin": origin,
        "index_date": index_date.isoformat(),
        "eligibility_status": eligibility,
        "risk_tier_snapshot": patient["risk_tier"],
        "assigned_interval_months": None,
        "due_date": episode_due_date(indication, index_date, None),
        "clinical_status": "OPEN",
        "navigation_status": "NOT_STARTED",
        "outreach_log": [],
        "prep_attestation": "NONE",
        "prep_adherence_score": 0.00,
        "closure_reason": None,
    })
    db.episodes[episode["id"]] = episode
    return episode


# --------------------------------------------------------------------------
# Surveillance recommendations
# --------------------------------------------------------------------------
def create_recommendation(episode, booking, report_id, override_months,
                          override_reason, attesting_user_id):
    agg = finalized_pathology_aggregate(booking["id"])
    computed = computed_interval_months(
        agg, episode["risk_tier_snapshot"], booking.get("prep_quality_bbps")
    )
    if override_months is not None:
        assigned = override_months
        basis = "OVERRIDE_ATTESTED"
        attesting = attesting_user_id
    else:
        assigned = computed
        basis = "GUIDELINE"
        attesting = None
    rec = new_record({
        "episode_id": episode["id"],
        "pathology_report_id": report_id,
        "attesting_endoscopist_id": attesting,
        "computed_interval_months": computed,
        "override_interval_months": override_months,
        "override_reason": override_reason if override_months is not None else None,
        "assigned_interval_months": assigned,
        "next_due_date": next_due_date(booking, assigned),
        "basis": basis,
        "status": "ACTIVE",
    })
    for other in db.recommendations.values():
        if other["episode_id"] == episode["id"] and other["status"] == "ACTIVE":
            other["status"] = "SUPERSEDED"
            touch(other)
    db.recommendations[rec["id"]] = rec
    episode["assigned_interval_months"] = rec["assigned_interval_months"]
    episode["due_date"] = rec["next_due_date"]
    return rec


# --------------------------------------------------------------------------
# Cascades
# --------------------------------------------------------------------------
def no_specimen_closure(booking, episode):
    """Completion with specimen_count == 0 - close the episode and reprice."""
    create_recommendation(episode, booking, None, None, None, None)
    episode["clinical_status"] = "CLOSED_SURVEILLANCE_SET"
    claim = booking_claim(booking["id"])
    if claim is not None and claim["status"] in ("PROVISIONAL_PRICED", "REPRICED"):
        apply_final_pricing(claim, touch_booking=False)


def pathology_finalize_cascade(report, booking, episode):
    """Four hops: route, recommend, close the episode, reprice the claim."""
    report["status"] = "FINALIZED"
    report["finalized_at"] = now_iso()
    report["routed_to_endoscopist_id"] = booking["performing_endoscopist_id"]
    touch(report)

    create_recommendation(episode, booking, report["id"], None, None, None)

    episode["clinical_status"] = "CLOSED_SURVEILLANCE_SET"
    touch(episode)

    claim = booking_claim(booking["id"])
    if claim is not None and claim["status"] in ("PROVISIONAL_PRICED", "REPRICED"):
        apply_final_pricing(claim, touch_booking=True)

    patient = db.patients.get(episode["patient_id"])
    if patient is not None:
        recompute_patient_counts(patient)


def positive_noninvasive_cascade(test, ordering_episode):
    """Four hops: new episode, back-link, patient counters, due date + outreach."""
    patient = db.patients[ordering_episode["patient_id"]]
    new_episode = build_episode(
        patient, "DIAGNOSTIC_FOLLOWUP", None, ordering_episode["id"], "NONINVASIVE_POSITIVE"
    )
    test["follow_up_episode_id"] = new_episode["id"]
    recompute_patient_counts(patient)
    new_episode["due_date"] = episode_due_date(
        "DIAGNOSTIC_FOLLOWUP",
        parse_instant(new_episode["index_date"] + "T00:00:00Z").date(),
        patient["navigation_priority"],
    )
    new_episode["navigation_status"] = "OUTREACH_ACTIVE"
    return new_episode


def refresh_prep_score(episode):
    episode["prep_adherence_score"] = prep_adherence_score(episode)
    return episode["prep_adherence_score"]


# --------------------------------------------------------------------------
# Specimens (PRD 3.8)
# --------------------------------------------------------------------------
HISTOLOGIES = (
    "TUBULAR_ADENOMA",
    "TUBULOVILLOUS_ADENOMA",
    "SESSILE_SERRATED_LESION",
    "HYPERPLASTIC",
    "ADENOCARCINOMA",
    "NORMAL_MUCOSA",
)
ADENOMA_HISTOLOGIES = ("TUBULAR_ADENOMA", "TUBULOVILLOUS_ADENOMA")


def validate_specimens(data, name="specimens"):
    if name not in data or data[name] is None:
        fail("ERR_INVALID_REQUEST", "Field %s is required." % name)
    raw = data[name]
    if not isinstance(raw, list):
        fail("ERR_INVALID_REQUEST", "Field %s must be an array." % name)
    cleaned = []
    for item in raw:
        if not isinstance(item, dict):
            fail("ERR_INVALID_REQUEST", "Each specimen must be an object.")
        label = item.get("label")
        if not isinstance(label, str) or label == "":
            fail("ERR_INVALID_REQUEST", "Each specimen requires a label string.")
        histology = item.get("histology")
        if not isinstance(histology, str) or histology not in HISTOLOGIES:
            fail("ERR_INVALID_REQUEST",
                 "Each specimen requires a histology in %s." % ", ".join(HISTOLOGIES))
        size_mm = item.get("size_mm")
        if isinstance(size_mm, bool) or not isinstance(size_mm, int) or size_mm < 0:
            fail("ERR_INVALID_REQUEST", "Each specimen requires a size_mm integer >= 0.")
        cleaned.append({"label": label, "histology": histology, "size_mm": size_mm})
    return cleaned


def derive_findings(specimens):
    adenomas = [s for s in specimens if s["histology"] in ADENOMA_HISTOLOGIES]
    return {
        "adenoma_count": len(adenomas),
        "sessile_serrated_count": sum(
            1 for s in specimens if s["histology"] == "SESSILE_SERRATED_LESION"
        ),
        "largest_adenoma_mm": max([s["size_mm"] for s in adenomas], default=0),
        "villous_component": any(s["histology"] == "TUBULOVILLOUS_ADENOMA" for s in specimens),
        "adenocarcinoma_present": any(s["histology"] == "ADENOCARCINOMA" for s in specimens),
    }
