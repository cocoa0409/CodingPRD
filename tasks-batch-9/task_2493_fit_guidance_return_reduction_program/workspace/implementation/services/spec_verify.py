"""calculations.spec_grade_tolerance_verification (PRD 3.2).

The verification outcome is computed, never chosen, and nothing outside the
specification under verification participates in the walk.
"""

import constants as C
from numeric import floor_div, round_half_up


def resolve_tolerance_mm(rule, measurement_point, fabric_stretch_class):
    """The four resolution steps of PRD 3.2, in order."""
    # 1. percentage component of the increment, rounded half up
    percentage_component = round_half_up(
        rule["tolerance_pct_bp"] * rule["increment_mm"], 10000)
    # 2. raw tolerance is the larger of the absolute and percentage declarations
    raw = max(rule["tolerance_abs_mm"], percentage_component)
    # 3. capped downward to the per-point ceiling
    capped = min(raw, C.TOLERANCE_CEILING_MM[measurement_point])
    # 4. scaled by the stretch class and floored
    return floor_div(capped * C.STRETCH_MULTIPLIER_PCT[fabric_stretch_class], 100)


def run_verification(spec):
    """Return ``(tolerance_applied_mm, violations)`` for this specification."""
    rules = {rule["measurement_point"]: rule for rule in spec["grade_rules"]}
    points = sorted(spec["size_points"], key=lambda p: p["sort_index"])

    tolerance_applied = []
    violations = []

    for measurement_point in C.MEASUREMENT_POINT_ORDER:
        rule = rules.get(measurement_point)
        if rule is None:
            # a point with no matching grade rule is skipped entirely
            continue
        tolerance_mm = resolve_tolerance_mm(
            rule, measurement_point, spec["fabric_stretch_class"])
        tolerance_applied.append({
            "measurement_point": measurement_point,
            "tolerance_mm": tolerance_mm,
        })
        field = measurement_point.lower() + "_mm"
        for index in range(len(points) - 1):
            lower = points[index]
            higher = points[index + 1]
            observed_step = higher[field] - lower[field]
            deviation = abs(observed_step - rule["increment_mm"])
            # strictly greater: a deviation exactly equal to the tolerance passes
            if deviation > tolerance_mm:
                violations.append({
                    "measurement_point": measurement_point,
                    "from_size_label": lower["size_label"],
                })

    return tolerance_applied, violations
