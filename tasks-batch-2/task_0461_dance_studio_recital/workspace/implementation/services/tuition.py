"""Tuition discount engine (PRD 3.3) and family-profile reconciliation."""
from decimal import ROUND_HALF_UP, Decimal

from db import db, touch

MULTI_CLASS_2ND_PCT = Decimal("0.10")
MULTI_CLASS_3RD_PLUS_PCT = Decimal("0.20")
FAMILY_2_PCT = Decimal("0.05")
FAMILY_3_PLUS_PCT = Decimal("0.08")


def _round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _section_tuition(enr):
    sec = db.sections.get(enr["section_id"])
    return sec["monthly_tuition_cents"] if sec else 0


def _multiclass_pct(index):
    # index is 0-based position within the student's billing-active enrollments.
    if index == 0:
        return Decimal("0")
    if index == 1:
        return MULTI_CLASS_2ND_PCT
    return MULTI_CLASS_3RD_PLUS_PCT


def _family_pct(sibling_count):
    if sibling_count <= 1:
        return Decimal("0")
    if sibling_count == 2:
        return FAMILY_2_PCT
    return FAMILY_3_PLUS_PCT


def _family_enrollments(family_id):
    return [e for e in db.enrollments.values() if e.get("family_id") == family_id]


def compute_sibling_count(family_id):
    """Count of ACTIVE students with >=1 BILLING_ACTIVE enrollment (PRD 2.9)."""
    active_students = set()
    for e in _family_enrollments(family_id):
        if e["billing_status"] != "BILLING_ACTIVE":
            continue
        st = db.students.get(e["student_id"])
        if st and st["status"] == "ACTIVE":
            active_students.add(st["id"])
    return len(active_students)


def recompute_family(family_id):
    """Recompute monthly_charge_cents for every BILLING_ACTIVE enrollment of the
    family, plus the family's sibling_count. Bumps version/updated_at on every
    enrollment whose monthly_charge_cents changes and on the family if its
    sibling_count changes (PRD 2.6)."""
    family = db.families.get(family_id)
    if family is None:
        return

    # Recompute sibling_count first (drives the family discount tier).
    new_sibling = compute_sibling_count(family_id)
    if family["sibling_count"] != new_sibling:
        family["sibling_count"] = new_sibling
        touch(family)
    sibling_count = family["sibling_count"]
    family_pct = _family_pct(sibling_count)

    active = [e for e in _family_enrollments(family_id)
              if e["billing_status"] == "BILLING_ACTIVE"]

    # Multi-class index is per-student, ordered by section tuition DESC then
    # created_at ASC (tie-break by created_at, never id).
    by_student = {}
    for e in active:
        by_student.setdefault(e["student_id"], []).append(e)

    charge_for = {}
    for student_id, enrs in by_student.items():
        ordered = sorted(
            enrs,
            key=lambda e: (-_section_tuition(e), e["created_at"], e["_seq"]),
        )
        for idx, e in enumerate(ordered):
            base = _section_tuition(e)
            mc_pct = _multiclass_pct(idx)
            after_mc = _round_half_up(Decimal(base) * (Decimal("1") - mc_pct))
            after_fam = _round_half_up(Decimal(after_mc) * (Decimal("1") - family_pct))
            charge_for[e["id"]] = after_fam

    for e in active:
        new_charge = charge_for.get(e["id"], 0)
        if e["monthly_charge_cents"] != new_charge:
            e["monthly_charge_cents"] = new_charge
            touch(e)
