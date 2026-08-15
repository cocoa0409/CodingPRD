"""Calculation rules from scaffold §1.3 — all money math in Decimal/cents."""

from decimal import Decimal, ROUND_HALF_UP

import db


def _round_cents(x: Decimal) -> int:
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- composite_score constants ---
TEST_WEIGHT = Decimal("0.6")
INTERVIEW_WEIGHT = Decimal("0.4")
SIBLING_POINTS = 10
LEGACY_POINTS = 5

# --- aid_award_amount constants ---
HOUSEHOLD_BASE_ALLOWANCE_CENTS = 2500000
HOUSEHOLD_PER_MEMBER_CENTS = 750000
TIER1_WIDTH_CENTS = 2500000
TIER2_WIDTH_CENTS = 5000000
TIER1_RATE = Decimal("0.12")
TIER2_RATE = Decimal("0.22")
TIER3_RATE = Decimal("0.30")
MAX_AWARD_PCT = Decimal("0.90")

# --- deposit_amount constants ---
DEPOSIT_PCT = Decimal("0.10")
MIN_DEPOSIT_CENTS = 50000

# --- reenrollment sibling discount ---
SIBLING_DISCOUNT_PCT = Decimal("0.10")


def compute_composite(application) -> tuple:
    """Return (composite_score, preference_points, sibling_verified)."""
    test_score = None
    interview_score = None
    for e in db.evaluations.values():
        if e["application_id"] != application["id"] or e["status"] != "SCORED":
            continue
        if e["kind"] == "TEST":
            test_score = e["score"]
        elif e["kind"] == "INTERVIEW":
            interview_score = e["score"]
    weighted = (TEST_WEIGHT * Decimal(test_score) + INTERVIEW_WEIGHT * Decimal(interview_score))
    weighted = weighted.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    applicant = db.applicants[application["applicant_id"]]
    sibling_verified = any(
        s["family_id"] == applicant["family_id"] and s["status"] == "ACTIVE"
        for s in db.students.values()
    )
    preference = (SIBLING_POINTS if sibling_verified else 0) + \
                 (LEGACY_POINTS if applicant["legacy_parent"] else 0)
    composite = float(weighted + Decimal(preference))
    return composite, preference, sibling_verified


def compute_aid_award(income_cents: int, household_size: int, tuition_cents: int) -> int:
    """aid_award_amount: fixed order allowance -> discretionary -> tiered EFC
    (each tier rounded half-up to whole cents before summing) -> need -> cap."""
    allowance = HOUSEHOLD_BASE_ALLOWANCE_CENTS + HOUSEHOLD_PER_MEMBER_CENTS * household_size
    discretionary = max(0, income_cents - allowance)
    d = Decimal(discretionary)
    t1 = _round_cents(TIER1_RATE * Decimal(min(discretionary, TIER1_WIDTH_CENTS)))
    t2 = _round_cents(TIER2_RATE * Decimal(min(max(0, discretionary - TIER1_WIDTH_CENTS),
                                               TIER2_WIDTH_CENTS)))
    t3 = _round_cents(TIER3_RATE * Decimal(max(0, discretionary - TIER1_WIDTH_CENTS
                                                - TIER2_WIDTH_CENTS)))
    efc = t1 + t2 + t3
    need = max(0, tuition_cents - efc)
    cap = _round_cents(MAX_AWARD_PCT * Decimal(tuition_cents))
    _ = d  # discretionary already consumed via ints; keeps symmetry with spec
    return min(need, cap)


def compute_deposit(tuition_cents: int, award_cents: int) -> int:
    net = tuition_cents - award_cents
    return max(MIN_DEPOSIT_CENTS, _round_cents(DEPOSIT_PCT * Decimal(net)))


def estimated_deposit_for_application(application) -> int:
    """Estimated (provisional) deposit variant shown on the offer letter."""
    section = db.grade_sections[application["grade_section_id"]]
    aid = None
    for a in db.aid_applications.values():
        if a["application_id"] == application["id"]:
            aid = a
            break
    award = aid["provisional_award_cents"] if aid is not None else 0
    return compute_deposit(section["tuition_cents"], award)


def rank_key(application):
    """Committee rank order: composite_score DESC, submitted_at ASC, created_at ASC.

    ids never consulted. submitted_at / created_at are ISO strings; equal-format
    ISO strings sort lexicographically in chronological order. _seq guarantees a
    deterministic creation order even within one wall-clock millisecond.
    """
    return (-(application["composite_score"] or 0),
            application["submitted_at"] or "",
            application["_seq"])


def sibling_discount_for(student, new_tuition_cents: int) -> int:
    """0 for the family's senior ACTIVE student (created_at ASC); 10% of the
    line's new tuition rounded half-up per line for each additional sibling."""
    family_students = sorted(
        (s for s in db.students.values()
         if s["family_id"] == student["family_id"] and s["status"] == "ACTIVE"),
        key=lambda s: (s["created_at"], s["_seq"]),
    )
    idx = next((i for i, s in enumerate(family_students) if s["id"] == student["id"]), 0)
    if idx == 0:
        return 0
    return _round_cents(SIBLING_DISCOUNT_PCT * Decimal(new_tuition_cents))


GRADE_ORDER = ["K", "G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8",
               "G9", "G10", "G11", "G12"]


def next_grade(grade_level: str):
    try:
        i = GRADE_ORDER.index(grade_level)
    except ValueError:
        return None
    if i + 1 >= len(GRADE_ORDER):
        return None  # G12 graduates
    return GRADE_ORDER[i + 1]
