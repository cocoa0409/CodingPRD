"""Calculation rules (SCAFFOLD 1.3 / PRD 3).  Every figure here is derived and
never accepted from a client."""
from datetime import timedelta
from decimal import Decimal

from core import DB, all_rows, d, dt, fmt_date, num, round_half_up, today

# --- constants -------------------------------------------------------------
POINT_WEIGHT = Decimal("1.0")
SERIOUS_VIOLATION_WEIGHT = Decimal("4.0")
PREVENTABLE_CRASH_WEIGHT = Decimal("6.0")
EXPERIENCE_CREDIT_PER_YEAR = Decimal("1.5")
MAX_EXPERIENCE_CREDIT = Decimal("6.0")
SAFETY_MULTIPLIER = {
    "SATISFACTORY": Decimal("1.00"),
    "CONDITIONAL": Decimal("1.25"),
    "UNSATISFACTORY": Decimal("1.50"),
}

WEIGHT_PRETRIP = Decimal("0.25")
WEIGHT_SKILLS = Decimal("0.35")
WEIGHT_ROAD = Decimal("0.40")
ROAD_TEST_PASS_THRESHOLD = Decimal("80.0")
ROAD_TEST_ROAD_FLOOR = 70
MAX_ROAD_TEST_ATTEMPTS = 3

LOOKBACK_DAYS = 1095
MAX_UNEXPLAINED_GAP_DAYS = 30
NO_RESPONSE_WAIT_DAYS = 14
GOOD_FAITH_ROUNDS = 3

DISPUTE_WINDOW_DAYS = 5
CONSENT_VALIDITY_DAYS = 365
MAX_DILUTE_RECOLLECTIONS = 1
ROAD_TEST_SLOT_MINUTES = 180
ORIENTATION_BUFFER_HOURS = 12

TIER_HIGH_MIN_CENTS = 20000
TIER_MID_MIN_CENTS = 10000
BONUS_PCT_HIGH = Decimal("0.00")
BONUS_PCT_MID = Decimal("0.05")
BONUS_PCT_LOW = Decimal("0.10")

DEFICIENCY_RESTRICT_RATIO = Decimal("0.2500")
WATCH_WINDOW_DAYS = 60
IMMINENT_WINDOW_DAYS = 15

# --- DQ document catalogue -------------------------------------------------
DOC_TYPES = [
    "APPLICATION_FORM",
    "CDL_COPY",
    "MVR_INITIAL",
    "PSP_REPORT",
    "CRIMINAL_CHECK",
    "EMPLOYMENT_VERIFICATION",
    "CLEARINGHOUSE_QUERY",
    "DRUG_TEST_RESULT",
    "ROAD_TEST_CERT",
    "MEDICAL_CERT",
    "MVR_ANNUAL",
    "ANNUAL_REVIEW_CERT",
]

DOC_WEIGHTS = {
    "APPLICATION_FORM": 3,
    "CDL_COPY": 2,
    "MVR_INITIAL": 3,
    "PSP_REPORT": 2,
    "CRIMINAL_CHECK": 1,
    "EMPLOYMENT_VERIFICATION": 4,
    "CLEARINGHOUSE_QUERY": 3,
    "DRUG_TEST_RESULT": 3,
    "ROAD_TEST_CERT": 3,
    "MEDICAL_CERT": 4,
    "MVR_ANNUAL": 3,
    "ANNUAL_REVIEW_CERT": 2,
}

TOTAL_WEIGHT = sum(DOC_WEIGHTS.values())  # 33

PRE_HIRE_EXCLUDED = {"MVR_ANNUAL", "ANNUAL_REVIEW_CERT"}
ANNUAL_FINAL_EXCLUDED = {"PSP_REPORT", "CRIMINAL_CHECK"}

VARIANTS_COMPLETENESS = ("pre_hire_provisional", "annual_review_final")
VARIANTS_COVERAGE = ("strict_verified", "good_faith_projected")

CHECK_TYPE_TO_DOC = {
    "MVR": "MVR_INITIAL",
    "PSP": "PSP_REPORT",
    "CRIMINAL": "CRIMINAL_CHECK",
}


# ---------------------------------------------------------------------------
# collection helpers
# ---------------------------------------------------------------------------
def rows_where(collection, **kw):
    out = []
    for row in all_rows(collection):
        if all(row.get(k) == v for k, v in kw.items()):
            out.append(row)
    return out


def documents_of(dq_file):
    return rows_where("dq_documents", dq_file_id=dq_file["id"])


def document_of(dq_file, doc_type):
    for row in documents_of(dq_file):
        if row["doc_type"] == doc_type:
            return row
    return None


def file_of_application(application):
    for row in all_rows("dq_files"):
        if row["application_id"] == application["id"]:
            return row
    return None


# ---------------------------------------------------------------------------
# calculations.mvr_adjudication_score
# ---------------------------------------------------------------------------
def mvr_adjudication_score(check, applicant, carrier):
    raw = (
        Decimal(check.get("violation_points") or 0) * POINT_WEIGHT
        + Decimal(check.get("serious_violation_count") or 0) * SERIOUS_VIOLATION_WEIGHT
        + Decimal(check.get("crash_preventable_count") or 0) * PREVENTABLE_CRASH_WEIGHT
    )
    if check["check_type"] != "MVR":
        return num(raw, 2)
    years = int(applicant.get("experience_months") or 0) // 12
    credit = Decimal(years) * EXPERIENCE_CREDIT_PER_YEAR
    if credit > MAX_EXPERIENCE_CREDIT:
        credit = MAX_EXPERIENCE_CREDIT
    net = raw - credit
    if net < 0:
        net = Decimal(0)
    multiplier = SAFETY_MULTIPLIER.get(carrier.get("safety_rating"), Decimal("1.00"))
    return num(net * multiplier, 2)


# ---------------------------------------------------------------------------
# calculations.road_test_composite_score
# ---------------------------------------------------------------------------
def road_test_composite_score(score_pretrip, score_skills, score_road):
    w_pretrip = round_half_up(Decimal(score_pretrip) * WEIGHT_PRETRIP, 2)
    w_skills = round_half_up(Decimal(score_skills) * WEIGHT_SKILLS, 2)
    w_road = round_half_up(Decimal(score_road) * WEIGHT_ROAD, 2)
    composite = round_half_up(w_pretrip + w_skills + w_road, 1)
    return composite


def road_test_passes(composite, score_road):
    return composite >= ROAD_TEST_PASS_THRESHOLD and int(score_road) >= ROAD_TEST_ROAD_FLOOR


# ---------------------------------------------------------------------------
# calculations.dq_completeness_score
# ---------------------------------------------------------------------------
def _variant_scope(variant):
    if variant == "annual_review_final":
        return [t for t in DOC_TYPES if t not in ANNUAL_FINAL_EXCLUDED]
    return [t for t in DOC_TYPES if t not in PRE_HIRE_EXCLUDED]


def _variant_satisfying(variant):
    if variant == "annual_review_final":
        return {"PRESENT"}
    return {"PRESENT", "WAIVED"}


def dq_completeness(dq_file, variant="pre_hire_provisional"):
    scope = _variant_scope(variant)
    satisfying = _variant_satisfying(variant)
    clock_date = today()
    docs = {row["doc_type"]: row for row in documents_of(dq_file)}
    in_scope = [docs[t] for t in scope if t in docs]
    denominator = sum(row["weight"] for row in in_scope)
    satisfied = []
    for row in in_scope:
        if row["status"] not in satisfying:
            continue
        expires = d(row.get("expires_on"))
        if expires is not None and expires < clock_date:
            continue
        satisfied.append(row)
    satisfied_weight = sum(row["weight"] for row in satisfied)
    if denominator == 0:
        pct = Decimal("0.00")
    else:
        pct = round_half_up(
            Decimal(satisfied_weight) / Decimal(denominator) * Decimal(100), 2
        )
    satisfied_ids = {row["id"] for row in satisfied}
    missing_doc_types = [
        row["doc_type"] for row in in_scope if row["id"] not in satisfied_ids
    ]
    return {
        "variant": variant,
        "completeness_pct": float(pct),
        "deficiency_count": len(in_scope) - len(satisfied),
        "satisfied_weight": satisfied_weight,
        "denominator_weight": denominator,
        "missing_doc_types": missing_doc_types,
        "_pct_decimal": pct,
    }


# ---------------------------------------------------------------------------
# calculations.employment_history_coverage
# ---------------------------------------------------------------------------
def employment_coverage(application, variant="strict_verified"):
    if variant == "good_faith_projected":
        accepted = {"RESPONDED_VERIFIED", "GOOD_FAITH_DOCUMENTED"}
    else:
        accepted = {"RESPONDED_VERIFIED"}
    window_end = today()
    window_start = window_end - timedelta(days=LOOKBACK_DAYS)
    segments = []
    for ev in rows_where("employment_verifications", application_id=application["id"]):
        if ev["status"] not in accepted:
            continue
        lo = d(ev["employed_from"])
        hi = d(ev["employed_to"])
        if lo is None or hi is None:
            continue
        if lo < window_start:
            lo = window_start
        if hi > window_end:
            hi = window_end
        if hi > lo:
            segments.append((lo, hi))
    segments.sort(key=lambda s: (s[0], s[1]))
    merged = []
    for lo, hi in segments:
        if merged and lo <= merged[-1][1]:
            if hi > merged[-1][1]:
                merged[-1] = (merged[-1][0], hi)
        else:
            merged.append((lo, hi))
    covered = sum((hi - lo).days for lo, hi in merged)
    return {
        "variant": variant,
        "verified_coverage_days": covered,
        "gap_days_unexplained": LOOKBACK_DAYS - covered,
        "merged_segment_count": len(merged),
    }


# ---------------------------------------------------------------------------
# calculations.tuition_schedule
# ---------------------------------------------------------------------------
def tuition_schedule(total_cents, commitment_months):
    base = total_cents // commitment_months
    if base >= TIER_HIGH_MIN_CENTS:
        bonus_pct = BONUS_PCT_HIGH
    elif base >= TIER_MID_MIN_CENTS:
        bonus_pct = BONUS_PCT_MID
    else:
        bonus_pct = BONUS_PCT_LOW
    bonus = int(round_half_up(Decimal(base) * bonus_pct, 0))
    monthly = base + bonus
    forgiven = total_cents - (base * commitment_months)
    return {
        "base_monthly_cents": base,
        "monthly_reimbursement_cents": monthly,
        "forgiven_cents": forgiven,
        "outstanding_cents": total_cents - forgiven,
    }


# ---------------------------------------------------------------------------
# calculations.carrier_posture
# ---------------------------------------------------------------------------
def carrier_posture(carrier):
    active_hires = [
        h for h in all_rows("hire_records")
        if h["carrier_id"] == carrier["id"] and h["status"] == "ACTIVE"
    ]
    filled = len(active_hires)
    active_app_ids = {h["application_id"] for h in active_hires}
    deficient = 0
    for f in all_rows("dq_files"):
        if f["status"] == "DEFICIENT" and f["application_id"] in active_app_ids:
            deficient += 1
    if filled == 0:
        ratio = Decimal("0.0")
    else:
        ratio = round_half_up(Decimal(deficient) / Decimal(filled), 4)
    if carrier.get("safety_rating") == "UNSATISFACTORY":
        posture = "FROZEN"
    elif ratio >= DEFICIENCY_RESTRICT_RATIO:
        posture = "RESTRICTED"
    else:
        posture = "OPEN"
    return {
        "filled_requisitions": filled,
        "deficiency_ratio": float(ratio),
        "posture": posture,
    }


# ---------------------------------------------------------------------------
# calculations.cdl_downgrade_risk
# ---------------------------------------------------------------------------
def cdl_downgrade_risk(applicant, carrier):
    app_ids = {
        a["id"] for a in all_rows("driver_applications")
        if a["applicant_id"] == applicant["id"]
    }
    file_ids = {}
    for f in all_rows("dq_files"):
        if f["application_id"] in app_ids and f["status"] != "ARCHIVED":
            file_ids[f["id"]] = f
    candidates = []
    for doc in all_rows("dq_documents"):
        if doc["dq_file_id"] not in file_ids:
            continue
        if doc["doc_type"] != "MEDICAL_CERT":
            continue
        if doc["status"] not in ("PRESENT", "EXPIRED"):
            continue
        if doc.get("expires_on") is None:
            continue
        candidates.append(doc)
    if not candidates:
        return {"cdl_downgrade_risk": "NO_CERTIFICATE",
                "governing_medical_cert_expires_on": None}
    candidates.sort(key=lambda r: (d(r["expires_on"]), r["created_at"], r["_seq"]))
    governing = candidates[-1]
    expires = d(governing["expires_on"])
    delta = (expires - today()).days
    grace = int((carrier or {}).get("medical_cert_grace_days") or 0)
    if delta > WATCH_WINDOW_DAYS:
        band = "NONE"
    elif delta > IMMINENT_WINDOW_DAYS:
        band = "WATCH"
    elif delta >= 0:
        band = "IMMINENT"
    elif (today() - expires).days <= grace:
        band = "EXPIRED_GRACE"
    else:
        band = "DOWNGRADED"
    return {"cdl_downgrade_risk": band,
            "governing_medical_cert_expires_on": governing["expires_on"]}


# ---------------------------------------------------------------------------
# calculations.dq_review_schedule
# ---------------------------------------------------------------------------
def dq_review_schedule(dq_file, carrier):
    last = dt(dq_file.get("last_annual_review_at"))
    baseline = last.date() if last is not None else d(dq_file["opened_on"])
    interval = int(carrier.get("annual_review_interval_days") or 365)
    grace = int(carrier.get("annual_review_grace_days") or 0)
    next_due = baseline + timedelta(days=interval)
    grace_end = next_due + timedelta(days=grace)
    clock_date = today()
    if clock_date < next_due:
        state = "NOT_DUE"
    elif clock_date <= grace_end:
        state = "DUE"
    else:
        state = "OVERDUE"
    return {"next_review_due_on": fmt_date(next_due), "review_state": state}


# ---------------------------------------------------------------------------
# calculations.rehire_eligibility
# ---------------------------------------------------------------------------
def rehire_eligibility(applicant, carrier):
    clawback = 0
    for t in all_rows("tuition_agreements"):
        if t["applicant_id"] == applicant["id"] and t["status"] == "TERMINATED_CLAWBACK":
            clawback += int(t.get("clawback_cents") or 0)
    terminated = [
        h for h in all_rows("hire_records")
        if h["applicant_id"] == applicant["id"] and h["status"] == "TERMINATED"
    ]
    terminated.sort(key=lambda h: (d(h["terminated_on"]), h["created_at"], h["_seq"]),
                    reverse=True)
    if not terminated and clawback == 0:
        verdict = "ELIGIBLE"
    elif clawback > 0:
        verdict = "PERMANENTLY_INELIGIBLE"
    else:
        latest = terminated[0]
        cooldown = int((carrier or {}).get("rehire_cooldown_days") or 0)
        if latest.get("termination_type") in ("INVOLUNTARY_SAFETY", "ABANDONMENT"):
            verdict = "PERMANENTLY_INELIGIBLE"
        elif latest.get("rehire_flag") == "NOT_ELIGIBLE":
            verdict = "PERMANENTLY_INELIGIBLE"
        elif today() < d(latest["terminated_on"]) + timedelta(days=cooldown):
            verdict = "COOLDOWN"
        else:
            verdict = "ELIGIBLE"
    return {"rehire_eligibility": verdict, "outstanding_clawback_cents": clawback}
