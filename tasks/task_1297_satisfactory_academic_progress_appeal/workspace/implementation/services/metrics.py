"""Metric calculations: pace, GPA (raw-sums, single rounding), max timeframe.

All rounding is ROUND_HALF_UP; pace at 2 decimal places, GPA at 3.
Decimals, never floats, carry the arithmetic.
"""

from decimal import Decimal, ROUND_HALF_UP

from db import store

BASIS_STATUSES = ("POSTED", "AMENDED")


def round_half_up(value, places):
    quantum = Decimal(1).scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def to_decimal(value):
    """JSON number -> exact Decimal (via shortest repr, never raw float)."""
    return Decimal(str(value))


def basis_rows(student_id):
    return [
        e for e in store.enrollments.values()
        if e["student_id"] == student_id and e["status"] in BASIS_STATUSES
    ]


def compute_cumulatives(student_id):
    """Official basis: POSTED | AMENDED rows only.

    Returns (attempted, earned, quality_points(Decimal), gpa_hours,
             cumulative_gpa(Decimal|None), pace_pct(Decimal|None)).
    GPA divides the raw cumulative sums and rounds exactly once at the end.
    """
    rows = basis_rows(student_id)
    attempted = sum(r["attempted_credits"] for r in rows)
    earned = sum(r["earned_credits"] for r in rows)
    qp = sum((r["quality_points"] for r in rows), Decimal("0"))
    gh = sum(r["gpa_hours"] for r in rows)
    gpa = round_half_up(qp / gh, 3) if gh > 0 else None
    pace = round_half_up(Decimal(100) * earned / attempted, 2) if attempted > 0 else None
    return attempted, earned, qp, gh, gpa, pace


def recompute_student(student):
    """Refresh the student's stored cumulative fields from the official basis."""
    attempted, earned, qp, gh, gpa, pace = compute_cumulatives(student["id"])
    student["cumulative_attempted_credits"] = attempted
    student["cumulative_earned_credits"] = earned
    student["cumulative_quality_points"] = qp
    student["cumulative_gpa_hours"] = gh
    student["cumulative_gpa"] = gpa
    student["pace_pct"] = pace
    return attempted, earned, qp, gh, gpa, pace


def max_tf_cap(program):
    """floor(required_credits * 1.5) in whole credits."""
    return int(
        (Decimal(program["required_credits"]) * Decimal("1.5"))
        .to_integral_value(rounding="ROUND_FLOOR")
    )


def max_tf_projection_exceeded(program, attempted, earned):
    """Projection variant: attempted + max(0, required - earned) > cap."""
    cap = max_tf_cap(program)
    remaining = max(0, program["required_credits"] - earned)
    return (attempted + remaining) > cap


def max_tf_attempted_only_exceeded(program, attempted):
    """Advisory weaker variant: attempted alone exceeds the cap."""
    return attempted > max_tf_cap(program)


def max_tf_headroom(program, attempted):
    return max_tf_cap(program) - attempted


def term_metrics(student_id, term_id):
    """Single-term figures over this term's POSTED | AMENDED rows.

    Returns (attempted, earned, term_gpa(Decimal|None), term_pace(Decimal|None)).
    """
    rows = [
        e for e in store.enrollments.values()
        if e["student_id"] == student_id and e["term_id"] == term_id
        and e["status"] in BASIS_STATUSES
    ]
    attempted = sum(r["attempted_credits"] for r in rows)
    earned = sum(r["earned_credits"] for r in rows)
    qp = sum((r["quality_points"] for r in rows), Decimal("0"))
    gh = sum(r["gpa_hours"] for r in rows)
    gpa = round_half_up(qp / gh, 3) if gh > 0 else None
    pace = round_half_up(Decimal(100) * earned / attempted, 2) if attempted > 0 else None
    return attempted, earned, gpa, pace
