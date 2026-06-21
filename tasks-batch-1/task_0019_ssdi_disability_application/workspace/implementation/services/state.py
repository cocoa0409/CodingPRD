"""Cross-resource state transitions and cascades."""
from datetime import datetime

import db
from services import calculations as calc
from services.utils import parse_iso8601


# ----- Helpers -----
def serialize_dt(dt):
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            from datetime import timezone

            dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return dt


# ----- Submit application: QC computation + auto-transition -----
def submit_application(app: dict):
    """Mutate the application record (in place): set filing_date, default PFD,
    compute QC counts and insured_status, route to MEDICAL_REVIEW or DENIED_QC.

    Caller must have already verified app.status == DRAFT and that the claimant
    exists. Bumps app.version once.
    """
    claimant = db.claimants.get(app["claimant_id"])
    filing_dt = db.now_utc()
    app["filing_date"] = serialize_dt(filing_dt)

    if not app.get("protective_filing_date"):
        app["protective_filing_date"] = app["filing_date"]

    filing_year = filing_dt.year
    total, recent = calc.compute_qc_counts(app["claimant_id"], filing_year)
    app["total_qc_at_filing"] = total
    app["recent_qc_in_lookback"] = recent

    dob = parse_iso8601(claimant["date_of_birth"], "date_of_birth")
    age_at_filing = _age_at(dob, filing_dt)

    required = calc.required_total_qc(age_at_filing)
    if total >= required and recent >= calc.RECENT_QC_THRESHOLD:
        app["insured_status"] = "INSURED"
        # DRAFT -> QC_REVIEW -> MEDICAL_REVIEW in the same logical step.
        app["status"] = "MEDICAL_REVIEW"
    else:
        app["insured_status"] = "NOT_INSURED"
        app["status"] = "DENIED_QC"

    db.stamp_update(app)


def _age_at(dob: datetime, at: datetime) -> int:
    years = at.year - dob.year
    if (at.month, at.day) < (dob.month, dob.day):
        years -= 1
    return years


# ----- Medical decision: create decision + transition + cascades -----
def apply_medical_decision(app: dict, decision_payload: dict, examiner_user_id: str):
    """Create MedicalDeterminationDecision, transition application, cascade-create
    BenefitAward + optional SSISupplement + CDRReview when decision is approving.

    Caller must have verified all preconditions. Returns the decision record.
    """
    decision_type = decision_payload["decision_type"]
    eod = decision_payload["established_onset_date"]  # ISO 8601 str
    listing_ref = decision_payload.get("listing_reference")
    rfc_score = decision_payload.get("rfc_score")

    decision = {
        "application_id": app["id"],
        "decision_type": decision_type,
        "listing_reference": listing_ref,
        "rfc_score": rfc_score,
        "established_onset_date": eod,
        "examiner_user_id": examiner_user_id,
    }
    db.stamp_create(decision)
    db.medical_decisions[decision["id"]] = decision

    if decision_type == "NOT_DISABLED":
        app["medical_decision"] = "NOT_DISABLED"
        app["status"] = "DENIED_MEDICAL"
        db.stamp_update(app)
        return decision

    # LISTING_MET or RFC_DISABLED -> approve initial
    app["medical_decision"] = decision_type
    app["established_onset_date"] = eod
    app["status"] = "APPROVED_INITIAL"
    db.stamp_update(app)

    # Cascade: create BenefitAward (INITIAL_APPROVAL variant)
    pia = calc.compute_pia_cents(app["claimant_id"])
    eod_dt = parse_iso8601(eod, "established_onset_date")
    pfd_dt = parse_iso8601(app["protective_filing_date"], "protective_filing_date")
    decision_dt = parse_iso8601(decision["created_at"], "decision.created_at")
    back_pay = calc.compute_back_pay(pia, eod_dt, pfd_dt, decision_dt)
    ent_start = calc.entitlement_start_date(eod_dt, pfd_dt)

    award = {
        "application_id": app["id"],
        "primary_insurance_amount_cents": pia,
        "monthly_benefit_cents": pia,
        "back_pay_cents": back_pay,
        "back_pay_variant": "INITIAL_APPROVAL",
        "entitlement_start_date": serialize_dt(ent_start),
        "status": "ACTIVE",
    }
    db.stamp_create(award)
    db.awards[award["id"]] = award

    # Optional SSI supplement
    if app.get("claim_type") == "CONCURRENT_SSDI_SSI":
        _create_ssi_supplement(app, award)

    # Schedule initial CDR
    _create_initial_cdr(award)

    # Auto-transition APPROVED_INITIAL -> AWARDED (separate version bump? PRD says
    # the cascade is one logical step with a single version bump from medical-decision.
    # We'll fold the awarded auto-step in without another bump.)
    app["status"] = "AWARDED"
    app["updated_at"] = db.iso_now()

    return decision


def _create_ssi_supplement(app: dict, award: dict):
    claimant = db.claimants[app["claimant_id"]]
    status, monthly, state_supp = calc.compute_ssi_supplement(
        claimant, award["monthly_benefit_cents"]
    )
    ssi = {
        "application_id": app["id"],
        "monthly_supplement_cents": monthly,
        "state_supplement_cents": state_supp,
        "status": status,
    }
    db.stamp_create(ssi)
    db.ssi_supplements[ssi["id"]] = ssi
    return ssi


def _create_initial_cdr(award: dict):
    diary = "MIE"
    scheduled = calc.cdr_schedule_date(diary)
    cdr = {
        "benefit_award_id": award["id"],
        "scheduled_review_date": serialize_dt(scheduled),
        "diary_classification": diary,
        "outcome": "PENDING",
        "completion_date": None,
    }
    db.stamp_create(cdr)
    db.cdr_reviews[cdr["id"]] = cdr
    return cdr


# ----- ALJ APPROVED cascade -----
def apply_alj_approved(hearing: dict, app: dict):
    """Cascade: set application ALJ_APPROVED + medical_decision=RFC_DISABLED,
    create BenefitAward (ALJ_APPROVAL variant), optional SSI, schedule CDR,
    auto-transition to AWARDED. Mutates app and creates child records.
    Returns the new award.
    """
    app["status"] = "ALJ_APPROVED"
    app["medical_decision"] = "RFC_DISABLED"
    db.stamp_update(app)

    pia = calc.compute_pia_cents(app["claimant_id"])
    eod_str = app.get("established_onset_date")
    if eod_str is None:
        # Conservatively use AOD as fallback (should not happen if flow is correct).
        eod_str = app["alleged_onset_date"]
    eod_dt = parse_iso8601(eod_str, "established_onset_date")
    pfd_dt = parse_iso8601(app["protective_filing_date"], "protective_filing_date")
    decision_dt = db.now_utc()
    back_pay = calc.compute_back_pay(pia, eod_dt, pfd_dt, decision_dt)
    ent_start = calc.entitlement_start_date(eod_dt, pfd_dt)

    award = {
        "application_id": app["id"],
        "primary_insurance_amount_cents": pia,
        "monthly_benefit_cents": pia,
        "back_pay_cents": back_pay,
        "back_pay_variant": "ALJ_APPROVAL",
        "entitlement_start_date": serialize_dt(ent_start),
        "status": "ACTIVE",
    }
    db.stamp_create(award)
    db.awards[award["id"]] = award

    if app.get("claim_type") == "CONCURRENT_SSDI_SSI":
        _create_ssi_supplement(app, award)

    _create_initial_cdr(award)

    app["status"] = "AWARDED"
    app["updated_at"] = db.iso_now()

    return award


# ----- CDR completion cascade -----
def cdr_complete_cessation(cdr: dict, app: dict):
    """Cascade: app -> CESSATION, terminate BenefitAward, child auxiliaries,
    SSI supplement. Bumps app.version once. Each affected child record gets its
    own updated_at and (where applicable) version bump.
    """
    cdr["outcome"] = "CESSATION"
    cdr["completion_date"] = db.iso_now()
    db.stamp_update(cdr)

    app["status"] = "CESSATION"
    db.stamp_update(app)

    # Cascade: terminate every BenefitAward for this app.
    for award in list(db.awards.values()):
        if award.get("application_id") == app["id"]:
            award["status"] = "TERMINATED"
            db.stamp_update(award)
            # Cascade: terminate every active child auxiliary on this award.
            for aux in db.child_aux.values():
                if (
                    aux.get("benefit_award_id") == award["id"]
                    and aux.get("status") == "ACTIVE"
                ):
                    aux["status"] = "TERMINATED_PARENT"
                    db.stamp_update(aux)

    # Cascade: terminate SSI supplements tied to the application.
    for ssi in db.ssi_supplements.values():
        if ssi.get("application_id") == app["id"] and ssi.get("status") != "TERMINATED":
            ssi["status"] = "TERMINATED"
            db.stamp_update(ssi)


def cdr_complete_continued(cdr: dict, app: dict):
    cdr["outcome"] = "CONTINUED"
    cdr["completion_date"] = db.iso_now()
    db.stamp_update(cdr)

    app["status"] = "AWARDED"
    db.stamp_update(app)

    # Schedule next CDR (same diary classification)
    # Use the same award_id and diary classification of the just-completed CDR.
    award_id = cdr.get("benefit_award_id")
    diary = cdr.get("diary_classification", "MIE")
    scheduled = calc.cdr_schedule_date(diary)
    new_cdr = {
        "benefit_award_id": award_id,
        "scheduled_review_date": serialize_dt(scheduled),
        "diary_classification": diary,
        "outcome": "PENDING",
        "completion_date": None,
    }
    db.stamp_create(new_cdr)
    db.cdr_reviews[new_cdr["id"]] = new_cdr


# ----- Award suspension cascade -----
def suspend_award(award: dict):
    award["status"] = "SUSPENDED"
    db.stamp_update(award)
    for aux in db.child_aux.values():
        if aux.get("benefit_award_id") == award["id"] and aux.get("status") == "ACTIVE":
            aux["status"] = "TERMINATED_PARENT"
            db.stamp_update(aux)


def reinstate_award(award: dict):
    award["status"] = "ACTIVE"
    db.stamp_update(award)
    # Child auxiliaries are NOT auto-reinstated.
