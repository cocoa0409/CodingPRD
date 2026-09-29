"""PLA capacity ceilings, cap parking and the unblock waterfall (PRD 3.3, 3.12)."""
from db import claims_of_student, db, order_rows
from util import RESERVING_STATES, touch


def program_ceiling(program):
    pct_component = (program["total_credits_required"] * program["pla_max_pct_bp"]) // 10000
    return min(program["pla_max_credits"], pct_component)


def effective_cap_program(program):
    """Programme-level advertised cap: transfer credits treated as zero."""
    headroom = program["total_credits_required"] - program["residency_min_credits"]
    return min(program_ceiling(program), max(0, headroom))


def residency_headroom(program, student):
    return max(0, program["total_credits_required"] - program["residency_min_credits"]
               - student["transfer_credits_accepted"])


def effective_cap_student(program, student):
    return min(program_ceiling(program), residency_headroom(program, student))


def consumed_credits(student):
    return student["pla_credits_reserved"] + student["pla_credits_awarded"] + student["pla_credits_posted"]


def own_reservation(claim):
    return claim["credits_requested"] if claim["assessment_status"] in RESERVING_STATES else 0


def remaining_reserved_inclusive(program, student, claim=None):
    consumed = consumed_credits(student)
    if claim is not None:
        consumed -= own_reservation(claim)
    return effective_cap_student(program, student) - consumed


def remaining_posted_only(program, student):
    return effective_cap_student(program, student) - student["pla_credits_posted"]


def upper_division_remaining(program, student, claim=None, course=None):
    committed = student["pla_upper_division_committed"]
    if claim is not None and course is not None and course["level"] == "UPPER":
        committed -= own_reservation(claim)
    return program["pla_upper_division_max_credits"] - committed


def program_of_student(student):
    return db.programs.get(student["program_id"])


# ---------------------------------------------------------------- reservations
def take_reservation(student, claim, course):
    student["pla_credits_reserved"] += claim["credits_requested"]
    if course["level"] == "UPPER":
        student["pla_upper_division_committed"] += claim["credits_requested"]
    touch(student)


def release_reservation(student, claim, course):
    student["pla_credits_reserved"] -= claim["credits_requested"]
    if course["level"] == "UPPER":
        student["pla_upper_division_committed"] -= claim["credits_requested"]
    touch(student)


# ---------------------------------------------------------------- waterfall
def _claim_order(rows):
    return order_rows(rows, [(lambda r: r["created_at"], False), (lambda r: r["claim_number"], False)])


def unblock_waterfall(student):
    """Skip-and-continue first-fit release of CAP_BLOCKED claims (PRD 3.12)."""
    program = program_of_student(student)
    if program is None:
        return []
    remaining = remaining_reserved_inclusive(program, student)
    upper_remaining = program["pla_upper_division_max_credits"] - student["pla_upper_division_committed"]
    unblocked = []
    blocked = [c for c in claims_of_student(student["id"]) if c["assessment_status"] == "CAP_BLOCKED"]
    for claim in _claim_order(blocked):
        course = db.courses.get(claim["course_id"])
        want = claim["credits_requested"]
        if want > remaining:
            continue
        if course is not None and course["level"] == "UPPER" and want > upper_remaining:
            continue
        claim["assessment_status"] = "SUBMITTED"
        claim["hold_reason"] = None
        student["pla_credits_reserved"] += want
        remaining -= want
        if course is not None and course["level"] == "UPPER":
            student["pla_upper_division_committed"] += want
            upper_remaining -= want
        touch(claim)
        unblocked.append(claim)
    if unblocked:
        touch(student)
    return unblocked


BLOCKABLE_STATES = ("SUBMITTED", "UNDER_ASSESSMENT", "SCORED")


def cap_block_cascade(student, skip_claim_id=None):
    """When reserved-inclusive remaining hits zero, park live sibling claims."""
    program = program_of_student(student)
    if program is None:
        return []
    if remaining_reserved_inclusive(program, student) > 0:
        return []
    from services.sla import revoke_open_assignments
    blocked = []
    live = [c for c in claims_of_student(student["id"])
            if c["assessment_status"] in BLOCKABLE_STATES and c["id"] != skip_claim_id]
    for claim in _claim_order(live):
        course = db.courses.get(claim["course_id"])
        claim["assessment_status"] = "CAP_BLOCKED"
        claim["hold_reason"] = "PLA_CAP"
        student["pla_credits_reserved"] -= claim["credits_requested"]
        if course is not None and course["level"] == "UPPER":
            student["pla_upper_division_committed"] -= claim["credits_requested"]
        revoke_open_assignments(claim, "CAP_BLOCKED")
        touch(claim)
        blocked.append(claim)
    if blocked:
        touch(student)
    return blocked
