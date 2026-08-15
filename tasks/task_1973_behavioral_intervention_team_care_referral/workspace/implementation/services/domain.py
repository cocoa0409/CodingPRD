from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import errors as E
from db import store, now, new_record, touch, all_sorted
from errors import ApiError

# ---------------------------------------------------------------------------
# followup_cadence_schedule constants
# ---------------------------------------------------------------------------
CADENCE_DAYS = {"IMMINENT": 2, "HIGH": 7, "MODERATE": 14, "LOW": 30}
GRACE_DAYS = 1
REENTRY_FIRST_CHECKIN_DAYS = 7

CONCERN_CATEGORIES = [
    "ACADEMIC_DISTRESS",
    "BEHAVIORAL_THREAT",
    "SELF_HARM_RISK",
    "SUBSTANCE_CONCERN",
    "WELLBEING_GENERAL",
]

OFFICES = [
    "FACULTY_AFFAIRS",
    "RESIDENCE_LIFE",
    "COUNSELING_CENTER",
    "DEAN_OF_STUDENTS",
    "BIT_OFFICE",
    "CAMPUS_SAFETY",
    "PRIVACY_OFFICE",
]


def cadence_days(tier):
    return CADENCE_DAYS.get(tier, CADENCE_DAYS["LOW"])


def r1(x: Decimal) -> float:
    """Round half-up to exactly one decimal place, returned as float."""
    return float(x.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# triage_risk_score
# ---------------------------------------------------------------------------
def latest_scoring(case_id):
    scorings = [s for s in all_sorted(store.scorings) if s["case_id"] == case_id]
    return scorings[-1] if scorings else None


def compute_score_and_tier(case, mode, harm_self, harm_others, academic, substance):
    base = Decimal(4) * (
        Decimal("0.35") * harm_self
        + Decimal("0.35") * harm_others
        + Decimal("0.15") * academic
        + Decimal("0.15") * substance
    )
    if mode == "INITIAL":
        score_d = base.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    else:
        prev = latest_scoring(case["id"])
        prev_score = Decimal(str(prev["score"]))
        score_d = (Decimal("0.6") * base + Decimal("0.4") * prev_score).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )
    if score_d >= Decimal(80):
        tier = "IMMINENT"
    elif score_d >= Decimal(60):
        tier = "HIGH"
    elif score_d >= Decimal(30):
        tier = "MODERATE"
    else:
        tier = "LOW"
    # Ratchet: a case at IMMINENT cannot de-escalate below HIGH in one reassessment.
    if case.get("current_risk_tier") == "IMMINENT" and tier in ("MODERATE", "LOW"):
        tier = "HIGH"
    return float(score_d), tier


# ---------------------------------------------------------------------------
# Follow-up check-ins
# ---------------------------------------------------------------------------
def schedule_checkin(case_id, due_at):
    rec = new_record()
    rec.update(
        {
            "case_id": case_id,
            "due_at": due_at,
            "completed_at": None,
            "outcome": None,
            "note": None,
            "status": "SCHEDULED",
        }
    )
    store.checkins[rec["id"]] = rec
    return rec


def cancel_scheduled_checkins(case_id):
    for c in store.checkins.values():
        if c["case_id"] == case_id and c["status"] == "SCHEDULED":
            c["status"] = "CANCELLED"
            touch(c)


# ---------------------------------------------------------------------------
# Disclosure grants
# ---------------------------------------------------------------------------
def create_auto_grants_for_imminent(case):
    """IMMINENT-crossing safety exception: two APPROVED SAFETY_MINIMUM grants."""
    n = now()
    for office in ("COUNSELING_CENTER", "CAMPUS_SAFETY"):
        g = new_record()
        g.update(
            {
                "case_id": case["id"],
                "requested_by": None,
                "approved_by": None,
                "to_office": office,
                "scope": "SAFETY_MINIMUM",
                "effective_from": n,
                "expires_at": n + timedelta(hours=72),
                "purpose": "Auto-approved safety disclosure on IMMINENT risk tier crossing",
                "auto_approved": True,
                "status": "APPROVED",
            }
        )
        store.grants[g["id"]] = g


# ---------------------------------------------------------------------------
# Leave-decision cascade (shared by NOT_CLEARED outcome and EXPIRED sweep)
# ---------------------------------------------------------------------------
def leave_decision_cascade(assessment):
    case = store.cases[assessment["case_id"]]
    # LINK 2: case -> LEAVE_DECISION
    case["status"] = "LEAVE_DECISION"
    touch(case)
    # LINK 3: create PENDING LeaveDecision
    ld = new_record()
    ld.update(
        {
            "case_id": case["id"],
            "requested_by": assessment["ordered_by"],
            "decided_by": None,
            "decision": None,
            "rationale": None,
            "decided_at": None,
            "status": "PENDING",
        }
    )
    store.leave_decisions[ld["id"]] = ld
    # LINK 4: suspend follow-up cadence
    cancel_scheduled_checkins(case["id"])
    return ld


# ---------------------------------------------------------------------------
# Clock sweeps
# ---------------------------------------------------------------------------
def run_sweeps():
    n = now()
    # 1. Mandated assessments: SCHEDULED with now > due_at -> EXPIRED + cascade
    for a in list(store.assessments.values()):
        if a["status"] == "SCHEDULED" and n > a["due_at"]:
            a["status"] = "EXPIRED"
            touch(a)
            leave_decision_cascade(a)
    # 2. Check-ins: SCHEDULED with now > due_at + 1 day -> MISSED + successor.
    # Loop to a fixpoint: a successor anchored to the missed due_at may itself
    # already be past the grace window.
    while True:
        progressed = False
        for c in list(store.checkins.values()):
            if c["status"] == "SCHEDULED" and n > c["due_at"] + timedelta(days=GRACE_DAYS):
                c["status"] = "MISSED"
                touch(c)
                case = store.cases.get(c["case_id"])
                if case is not None:
                    case["consecutive_stable_checkins"] = 0
                    touch(case)
                    schedule_checkin(
                        case["id"],
                        c["due_at"] + timedelta(days=cadence_days(case.get("current_risk_tier"))),
                    )
                progressed = True
        if not progressed:
            break
    # 3. Disclosure grants: APPROVED with now >= expires_at -> EXPIRED
    for g in list(store.grants.values()):
        if g["status"] == "APPROVED" and n >= g["expires_at"]:
            g["status"] = "EXPIRED"
            touch(g)


# ---------------------------------------------------------------------------
# Privacy partitioning (PRD 2.7)
# ---------------------------------------------------------------------------
REDACTED_CASE_FIELDS = ("id", "student_id", "status", "current_risk_tier", "current_risk_score")


def case_view_level(case, uid, role):
    """Returns 'full' or 'redacted'; raises ERR_PRIVACY_SCOPE_INSUFFICIENT."""
    if role in ("BITChair", "PrivacyOfficer", "DeanOfStudents"):
        return "full"
    if role == "CaseManager" and case["assigned_case_manager_id"] == uid:
        return "full"
    if role == "CounselingEvaluator":
        for a in store.assessments.values():
            if (
                a["case_id"] == case["id"]
                and a["evaluator_id"] == uid
                and a["status"] in ("SCHEDULED", "COMPLETED")
            ):
                return "full"
    member = store.staff.get(uid)
    office = member["office"] if member else None
    n = now()
    qualifying = [
        g
        for g in store.grants.values()
        if g["case_id"] == case["id"]
        and g["to_office"] == office
        and g["status"] == "APPROVED"
        and g["effective_from"] <= n < g["expires_at"]
    ]
    if any(g["scope"] == "FULL_RECORD" for g in qualifying):
        return "full"
    if qualifying:
        return "redacted"
    raise ApiError(
        E.ERR_PRIVACY_SCOPE_INSUFFICIENT,
        403,
        "Caller has no role-based access and no APPROVED unexpired DisclosureGrant for their office on this case",
    )


def serialize_case_scoped(case, level, serialize_fn):
    full = serialize_fn(case)
    if level == "full":
        return full
    return {k: full[k] for k in REDACTED_CASE_FIELDS}
