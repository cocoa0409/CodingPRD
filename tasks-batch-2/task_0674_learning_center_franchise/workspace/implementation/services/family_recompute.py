"""Family-wide recompute: sibling_count + per-enrollment monthly_rate_cents.

Triggered whenever an enrollment becomes active, pauses, resumes, completes, or
withdraws (PRD §3.3, §3.6, §2.5). Each entity touched gets version++/updated_at.
"""
from db import db
from services import calculations


def recompute_family(family_id):
    """Recompute Family.sibling_count and the monthly_rate_cents of every
    still-ACTIVE enrollment across the family. Versions each mutated entity."""
    family = db.families.get(family_id)
    if family is None:
        return

    new_sib = calculations.family_sibling_count(family_id)
    if family["sibling_count"] != new_sib:
        family["sibling_count"] = new_sib
        db.touch(family)

    # Recompute monthly_rate_cents for every ACTIVE enrollment of every student
    # in the family.
    student_ids = {s["id"] for s in db.students.values() if s["family_id"] == family_id}
    for enr in db.enrollments.values():
        if enr["student_id"] not in student_ids:
            continue
        if enr["status"] != "ACTIVE":
            continue
        center = db.centers.get(enr["center_id"])
        base = center["monthly_tuition_cents"] if center else 0
        new_rate = calculations.compute_monthly_rate(enr, base, new_sib)
        if enr["monthly_rate_cents"] != new_rate:
            enr["monthly_rate_cents"] = new_rate
            db.touch(enr)
