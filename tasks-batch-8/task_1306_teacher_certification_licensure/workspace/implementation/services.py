"""Business logic: calculations, state machine side effects, cascades, sweeps."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import errors
import util
from db import db

# ---------------------------------------------------------------------------
# Calculation constants
# ---------------------------------------------------------------------------

BASE_FEE = {
    "TRADITIONAL": 10000,
    "ALTERNATIVE": 15000,
    "RECIPROCITY": 20000,
    "REINSTATEMENT": 15000,
}
TRANSCRIPT_EVAL_FEE_CENTS = 2500
EXPEDITE_RATE = Decimal("0.20")

RENEWAL_BASE_CENTS = 15000
LATE_FEE_TIER1_MAX_DAYS = 365
LATE_FEE_TIER1_CENTS = 5000
LATE_FEE_TIER2_MAX_DAYS = 730
LATE_FEE_TIER2_CENTS = 15000

GRADE_POINTS = {"A": Decimal("4.0"), "A_MINUS": Decimal("3.7"), "B": Decimal("3.0"),
                "C": Decimal("2.0"), "D": Decimal("1.0"), "F": Decimal("0.0")}

RECOGNITION_CAP = 18
TEST_GAP_PENALTY = 6
ALTERNATIVE_ADDON = 6
DEFICIENCY_MAX = 30
SUBJECT_BASE = {"ELEMENTARY": 24, "MATHEMATICS": 30, "SCIENCE": 30, "SPECIAL_EDUCATION": 27}

CAP_STANDARD = {"PEDAGOGY": 30, "CONTENT": 60, "ETHICS": 5, "TECHNOLOGY": 10}
CAP_RESTORATION = {"PEDAGOGY": 45, "CONTENT": 90, "ETHICS": 8, "TECHNOLOGY": 15}
REQUIRED_STANDARD = 60
REQUIRED_RESTORATION = 90

RECIPROCITY_TABLE = {
    ("TX", "STANDARD"): ("FULL", 0),
    ("FL", "PROFESSIONAL"): ("PARTIAL", 6),
    ("NV", "PROVISIONAL"): ("DENIED", 0),
}
COMMITTEE_MIN_YEARS = 3
COMMITTEE_HOURS_REDUCTION = 6
COMMITTEE_DENIED_TO_PARTIAL_HOURS = 12
DEFAULT_PARTIAL_HOURS = 12

SCALING = {
    "PRAXIS_CORE": {"OFFSET": 100, "FACTOR": 1, "PASSING": 150},
    "PRAXIS_SUBJECT": {"OFFSET": 100, "FACTOR": 1, "PASSING": 157},
    "PEDAGOGY": {"OFFSET": 100, "FACTOR": 2, "PASSING": 160},
}

RISK_WEIGHT = {"FELONY_VIOLENT": 100, "FELONY_OTHER": 60, "MISDEMEANOR_DRUG": 40,
               "MISDEMEANOR_OTHER": 25, "INFRACTION": 10}
CLEAR_THRESHOLD_EXCLUSIVE = 40
FORCED_FLAG_LOOKBACK_YEARS = 10

APP_TERMINAL = {"APPROVED", "DENIED", "WITHDRAWN"}
BG_TERMINAL = {"CLEARED", "DENIED"}
AUDIT_OPEN = {"INITIATED", "UNDER_REVIEW", "REMEDIATION"}
CASE_OPEN = {"OPENED", "INVESTIGATING", "HEARING"}

PATHWAYS = {"TRADITIONAL", "ALTERNATIVE", "RECIPROCITY", "REINSTATEMENT"}
SUBJECT_AREAS = {"ELEMENTARY", "MATHEMATICS", "SCIENCE", "SPECIAL_EDUCATION"}
GRADE_BANDS = {"PK_6", "G5_8", "G7_12"}


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def transcripts_of(application_id):
    return [t for t in db.transcripts.values() if t["application_id"] == application_id]


def test_scores_of(application_id):
    return [t for t in db.test_scores.values() if t["application_id"] == application_id]


def background_checks_of(application_id):
    return [b for b in db.background_checks.values() if b["application_id"] == application_id]


def reciprocity_evals_of(application_id):
    return [r for r in db.reciprocity_evaluations.values() if r["application_id"] == application_id]


def deficiency_plans_of(application_id):
    return [p for p in db.deficiency_plans.values() if p["application_id"] == application_id]


def permits_of_application(application_id):
    return [p for p in db.emergency_permits.values() if p["application_id"] == application_id]


def permits_of_applicant(applicant_id):
    return [p for p in db.emergency_permits.values() if p["applicant_id"] == applicant_id]


def endorsements_of(license_id):
    return [e for e in db.endorsements.values() if e["license_id"] == license_id]


def ce_credits_of(license_id):
    return [c for c in db.ce_credits.values() if c["license_id"] == license_id]


def ce_audits_of(license_id):
    return [a for a in db.ce_audits.values() if a["license_id"] == license_id]


def misconduct_cases_of(license_id):
    return [c for c in db.misconduct_cases.values() if c["license_id"] == license_id]


def disciplinary_actions_of_case(case_id):
    return [a for a in db.disciplinary_actions.values() if a["case_id"] == case_id]


def disciplinary_actions_of_license(license_id):
    return [a for a in db.disciplinary_actions.values() if a["license_id"] == license_id]


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def _rhup(value, places=0):
    """Round half up to given decimal places, returning int when places == 0."""
    q = Decimal(1).scaleb(-places)
    d = Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)
    if places == 0:
        return int(d)
    return d


def compute_application_fee(application):
    """application_fee: base + 2500/transcript, +20% surcharge if expedite (round half up)."""
    base = BASE_FEE[application["pathway"]]
    eval_fee = TRANSCRIPT_EVAL_FEE_CENTS * len(transcripts_of(application["id"]))
    subtotal = base + eval_fee
    if application.get("expedite_requested"):
        surcharge = _rhup(Decimal(subtotal) * EXPEDITE_RATE)
    else:
        surcharge = 0
    return subtotal + surcharge


def compute_reinstatement_fee(license_):
    """reinstatement_fee: pinned tiered pricing per scaffold."""
    now = db.now()
    expires = util.parse_iso(license_["expires_on"])
    days_overdue = (now.date() - expires.date()).days
    if days_overdue < 1:
        days_overdue = 1
    if days_overdue <= LATE_FEE_TIER1_MAX_DAYS:
        late_fee = LATE_FEE_TIER1_CENTS
    else:
        late_fee = LATE_FEE_TIER2_CENTS
    subtotal = RENEWAL_BASE_CENTS + late_fee
    if subtotal < 25000:
        rate = Decimal("0")
    elif subtotal <= 39999:
        rate = Decimal("0.10")
    else:
        rate = Decimal("0.20")
    surcharge = _rhup(Decimal(subtotal) * rate)
    return subtotal + surcharge


def compute_scaled_gpa(courses):
    """coursework_gpa_scaling: round per course first (2dp half-up), then sum, then divide."""
    total_qp = Decimal("0")
    total_hours = Decimal("0")
    for c in courses:
        ch = Decimal(str(c["credit_hours"]))
        gp = GRADE_POINTS[c["letter_grade"]]
        qp = (ch * gp).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total_qp += qp
        total_hours += ch
    if total_hours == 0:
        return 0.0
    gpa = (total_qp / total_hours).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(gpa)


def required_exams(application):
    """Required exams per pathway and (for RECIPROCITY) finalized outcome."""
    pathway = application["pathway"]
    if pathway in ("TRADITIONAL", "ALTERNATIVE"):
        return ["PRAXIS_SUBJECT", "PEDAGOGY"]
    if pathway == "RECIPROCITY":
        ev = final_reciprocity_eval(application["id"])
        if ev is not None and ev.get("outcome") == "FULL":
            return []
        return ["PRAXIS_SUBJECT"]
    return []  # REINSTATEMENT


def final_reciprocity_eval(application_id):
    evs = [r for r in reciprocity_evals_of(application_id) if r.get("finalized")]
    if not evs:
        return None
    return util.sorted_by_created(evs)[-1]


def compute_deficiency_hours(application):
    """deficiency_credit_computation with sticky-zero override and final clamp."""
    app_id = application["id"]
    # sticky zero: a COMPLETED plan zeroes the deficiency
    if any(p["status"] == "COMPLETED" for p in deficiency_plans_of(app_id)):
        return 0
    recognized = sum(t.get("subject_relevant_hours") or 0
                     for t in transcripts_of(app_id)
                     if t["verification_status"] == "VERIFIED")
    recognized = min(recognized, RECOGNITION_CAP)
    if application["pathway"] == "RECIPROCITY":
        ev = final_reciprocity_eval(app_id)
        subject_gap = (ev.get("deficiency_subject_hours") or 0) if ev else 0
    else:
        subject_gap = max(0, SUBJECT_BASE[application["subject_area"]] - recognized)
    # test gap penalty
    verified_passing = {(t["exam_code"]) for t in test_scores_of(app_id)
                        if t["verification_status"] == "VERIFIED" and t.get("passing")}
    test_gap = TEST_GAP_PENALTY if any(e not in verified_passing for e in required_exams(application)) else 0
    addon = ALTERNATIVE_ADDON if application["pathway"] == "ALTERNATIVE" else 0
    return min(DEFICIENCY_MAX, int(subject_gap) + test_gap + addon)


def recompute_deficiency(application):
    application["deficiency_hours_required"] = compute_deficiency_hours(application)


def compute_test_scaling(exam_code, raw_score):
    s = SCALING[exam_code]
    scaled = s["OFFSET"] + raw_score * s["FACTOR"]
    return scaled, scaled >= s["PASSING"]


def compute_risk_score(adverse_findings, fingerprint_submitted_at):
    """background_risk_score; returns (risk_score, forced_flag)."""
    total = Decimal("0")
    forced = False
    for f in adverse_findings:
        cat = f["offense_category"]
        disp = f["disposition"]
        offense_date = util.parse_iso(f["offense_date"], "offense_date")
        age_days = (fingerprint_submitted_at - offense_date).total_seconds() / 86400.0
        age_years = Decimal(str(age_days)) / Decimal("365.0")
        if age_years <= 3:
            decay = Decimal("1.0")
        elif age_years <= 7:
            decay = Decimal("0.5")
        else:
            decay = Decimal("0.25")
        weight = Decimal(RISK_WEIGHT[cat])
        if disp == "CONVICTION":
            contrib = weight * decay
        elif disp == "PENDING":
            contrib = Decimal("0.5") * weight * decay
        else:  # DISMISSED
            contrib = Decimal("0")
        total += contrib
        if cat == "FELONY_VIOLENT" and disp == "CONVICTION" and age_years <= FORCED_FLAG_LOOKBACK_YEARS:
            forced = True
    risk = total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(risk), forced


def compute_ce_audit_totals(audit):
    """ce_credit_audit_total: chronological whole-credit fit-or-skip."""
    license_ = db.licenses.get(audit["license_id"])
    variant = audit["audit_variant"]
    caps = dict(CAP_STANDARD if variant == "STANDARD" else CAP_RESTORATION)
    required = REQUIRED_STANDARD if variant == "STANDARD" else REQUIRED_RESTORATION
    cycle_start = util.parse_iso(audit["cycle_start"])
    cycle_end = util.parse_iso(audit["cycle_end"])
    if variant == "RESTORATION":
        window_start = util.add_months(cycle_start, -12)
    else:
        window_start = cycle_start
    candidates = []
    for c in ce_credits_of(audit["license_id"]):
        if c["status"] != "VERIFIED":
            continue
        earned = util.parse_iso(c["earned_on"])
        if window_start <= earned < cycle_end:
            candidates.append((earned, c))
    candidates.sort(key=lambda x: (x[0], x[1].get("created_at", "")))
    verified_hours = 0
    for _, c in candidates:
        cat = c["category"]
        h = c["hours"]
        if h <= caps.get(cat, 0):
            caps[cat] = caps.get(cat, 0) - h
            verified_hours += h
    return verified_hours, required


def compute_reciprocity_outcome(source_state, source_license_type, years_teaching, mapping_mode):
    outcome, hours = RECIPROCITY_TABLE.get((source_state, source_license_type),
                                           ("PARTIAL", DEFAULT_PARTIAL_HOURS))
    if mapping_mode == "COMMITTEE" and years_teaching >= COMMITTEE_MIN_YEARS:
        if outcome == "DENIED":
            outcome, hours = "PARTIAL", COMMITTEE_DENIED_TO_PARTIAL_HOURS
        elif outcome == "PARTIAL":
            outcome = "FULL"
            hours = max(0, hours - COMMITTEE_HOURS_REDUCTION)
        # FULL unchanged
    return outcome, hours


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def cascade_application_denied(application):
    """Application -> DENIED side effects: revoke ISSUED/ACTIVE permits of the application."""
    for p in permits_of_application(application["id"]):
        if p["status"] in ("ISSUED", "ACTIVE"):
            p["status"] = "REVOKED"
            util.touch(p)


def cascade_application_approved(application):
    """Application -> APPROVED side effects: create license, applicant LICENSED, permits CONVERTED."""
    now = db.now()
    lic = util.stamp_new({
        "id": util.new_id(),
        "application_id": application["id"],
        "applicant_id": application["applicant_id"],
        "license_number": db.next_license_number(),
        "subject_area": application["subject_area"],
        "grade_band": application["grade_band"],
        "issued_on": util.to_iso(now),
        "expires_on": util.to_iso(util.add_months(now, 60)),
        "status": "ACTIVE",
    })
    db.licenses[lic["id"]] = lic
    applicant = db.applicants.get(application["applicant_id"])
    if applicant is not None and applicant["status"] != "BARRED":
        applicant["status"] = "LICENSED"
        util.touch(applicant)
    for p in permits_of_application(application["id"]):
        if p["status"] in ("ISSUED", "ACTIVE"):
            p["status"] = "CONVERTED"
            util.touch(p)


def cascade_applicant_barred(applicant):
    """Applicant -> BARRED: revoke every ISSUED/ACTIVE permit of that applicant."""
    for p in permits_of_applicant(applicant["id"]):
        if p["status"] in ("ISSUED", "ACTIVE"):
            p["status"] = "REVOKED"
            util.touch(p)


def cascade_license_revoked(license_):
    """License -> REVOKED: applicant BARRED, endorsements REVOKED, permits revoked via BARRED."""
    applicant = db.applicants.get(license_["applicant_id"])
    if applicant is not None and applicant["status"] != "BARRED":
        applicant["status"] = "BARRED"
        util.touch(applicant)
    for e in endorsements_of(license_["id"]):
        if e["status"] in ("PENDING_EVALUATION", "ACTIVE"):
            e["status"] = "REVOKED"
            util.touch(e)
    if applicant is not None:
        cascade_applicant_barred(applicant)


def cascade_program_withdrawn(program):
    """Program PROBATION -> APPROVAL_WITHDRAWN: force matching EVALUATION apps to DEFICIENCY_PENDING."""
    for app in db.applications.values():
        if (app.get("program_id") == program["id"]
                and app["pathway"] == "TRADITIONAL"
                and app["status"] == "EVALUATION"):
            app["status"] = "DEFICIENCY_PENDING"
            app["deficiency_hours_required"] = min(30, (app.get("deficiency_hours_required") or 0) + 12)
            util.touch(app)


def cascade_application_withdrawn(application):
    """Withdrawal from EVALUATION/DEFICIENCY_PENDING tears down permits and plans."""
    for p in permits_of_application(application["id"]):
        if p["status"] in ("ISSUED", "ACTIVE"):
            p["status"] = "REVOKED"
            util.touch(p)
    for plan in deficiency_plans_of(application["id"]):
        if plan["status"] in ("PROPOSED", "ACCEPTED", "IN_PROGRESS", "EXTENDED"):
            plan["status"] = "SUPERSEDED"
            util.touch(plan)


# ---------------------------------------------------------------------------
# Clock sweep
# ---------------------------------------------------------------------------

def sweep_clock():
    """Run every time-based transition after a clock set."""
    now = db.now()

    # Licenses: ACTIVE -> EXPIRED when expires_on reached
    for lic in db.licenses.values():
        if lic["status"] == "ACTIVE" and now >= util.parse_iso(lic["expires_on"]):
            lic["status"] = "EXPIRED"
            util.touch(lic)

    # Emergency permits: ISSUED -> ACTIVE (window open), ISSUED/ACTIVE -> EXPIRED
    for p in db.emergency_permits.values():
        vf = util.parse_iso(p["valid_from"])
        vu = util.parse_iso(p["valid_until"])
        if p["status"] == "ISSUED":
            if now >= vu:
                p["status"] = "EXPIRED"
                util.touch(p)
            elif now >= vf:
                p["status"] = "ACTIVE"
                util.touch(p)
        elif p["status"] == "ACTIVE":
            if now >= vu:
                p["status"] = "EXPIRED"
                util.touch(p)

    # Deficiency plans: IN_PROGRESS -> DEFAULTED when past deadline and incomplete
    for plan in db.deficiency_plans.values():
        if plan["status"] == "IN_PROGRESS":
            deadline = util.parse_iso(plan["deadline"])
            if now > deadline and plan["completed_hours"] < plan["required_hours"]:
                plan["status"] = "DEFAULTED"
                util.touch(plan)
                if plan.get("extension_used"):
                    app = db.applications.get(plan["application_id"])
                    if app is not None and app["status"] == "DEFICIENCY_PENDING":
                        app["status"] = "DENIED"
                        util.touch(app)
                        cascade_application_denied(app)

    # Disciplinary actions: ISSUED SUSPENSION -> SERVED when suspension_end reached
    for action in db.disciplinary_actions.values():
        if (action["status"] == "ISSUED"
                and action["sanction_type"] == "SUSPENSION"
                and action.get("suspension_end")
                and now >= util.parse_iso(action["suspension_end"])):
            action["status"] = "SERVED"
            util.touch(action)
            lic = db.licenses.get(action["license_id"])
            if lic is not None and lic["status"] == "SUSPENDED":
                still_open = any(
                    a["status"] == "ISSUED" and a["sanction_type"] == "SUSPENSION"
                    for a in disciplinary_actions_of_license(lic["id"])
                )
                if not still_open:
                    lic["status"] = "ACTIVE"
                    util.touch(lic)
