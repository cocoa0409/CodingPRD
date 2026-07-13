"""Violation adjudication, penalty scoring (rolling vs lifetime), and the appeal window."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    TEST_USERS, make_operator_headers,
    set_clock, create_operator,
    issue_violation, transition_violation_authority, transition_violation_operator,
)

AA = TEST_USERS["airport_authority_headers"]


def _get_operator(api, op_id):
    return validate_success(api.get_operator(op_id, AA))


def _assess(api, op_id, violation_type):
    vio = issue_violation(api, op_id, violation_type)
    return transition_violation_authority(api, vio["id"], "ASSESS")


# --- dual_variant: rolling vs lifetime penalty totals ---------------------
def test_rolling_penalty_excludes_aged_violation(api):
    """PRD §3.7: "it additionally contributes to the rolling total only if its
    `assessed_at` falls within the trailing 90-day window measured back from the
    current logical clock. The lifetime total therefore diverges from the rolling
    total once a counting violation ages past 90 days."

    Design: Difficulty/dual_variant_calc/operator_penalty_rolling_vs_lifetime_diverge
    """
    set_clock(api, "2026-03-01T00:00:00Z")
    op = create_operator(api, operator_type="TAXI", legal_name="Beta Taxi", activate=True)
    _assess(api, op["id"], "AVI_MISMATCH")  # assessed_at 2026-03-01, 6 points
    set_clock(api, "2026-09-17T00:00:00Z")
    _assess(api, op["id"], "STAGING")       # assessed_at 2026-09-17, 3 points
    data = _get_operator(api, op["id"])
    assert data["rolling_penalty_points"] == 3, (
        f"aged AVI (>90d) must drop from rolling; expected 3, got {data['rolling_penalty_points']}"
    )


def test_lifetime_penalty_counts_all_assessed(api):
    """PRD §3.7: "Each such violation contributes its type's points to the lifetime
    total; it additionally contributes to the rolling total only if its
    `assessed_at` falls within the trailing 90-day window measured back from the
    current logical clock."

    Design: Difficulty/dual_variant_calc/operator_penalty_rolling_vs_lifetime_diverge
    """
    set_clock(api, "2026-03-01T00:00:00Z")
    op = create_operator(api, operator_type="TAXI", legal_name="Beta Taxi", activate=True)
    _assess(api, op["id"], "AVI_MISMATCH")
    set_clock(api, "2026-09-17T00:00:00Z")
    _assess(api, op["id"], "STAGING")
    data = _get_operator(api, op["id"])
    assert data["lifetime_penalty_points"] == 9, (
        f"lifetime counts all-time (6 + 3); expected 9, got {data['lifetime_penalty_points']}"
    )
    assert data["status"] == "ACTIVE", f"rolling never reached 12; expected ACTIVE, got {data['status']}"


# --- non-linear machine: appeal fork (overturn vs uphold) -----------------
def _assessed_appealed_staging(api, op_name):
    set_clock(api, "2026-03-10T00:00:00Z")
    op = create_operator(api, operator_type="TAXI", legal_name=op_name, activate=True)
    vio = issue_violation(api, op["id"], "STAGING")
    transition_violation_authority(api, vio["id"], "ASSESS")
    transition_violation_operator(api, op["id"], vio["id"], "APPEAL")
    return op, vio


def test_appeal_overturn_removes_penalty_points(api):
    """PRD §3.7: "If the regulator overturns it (`APPEALED → OVERTURNED`), the
    violation stops counting and the operator's `rolling_penalty_points` and
    `lifetime_penalty_points` are recomputed downward; an operator already suspended
    is not automatically reinstated by an overturn."

    Design: Difficulty/non_linear_state_machine/violation_appeal_overturn_branch
    """
    op, vio = _assessed_appealed_staging(api, "Branch Co")
    overturned = transition_violation_authority(api, vio["id"], "OVERTURN")
    assert overturned["status"] == "OVERTURNED"
    data = _get_operator(api, op["id"])
    assert data["lifetime_penalty_points"] == 0, (
        f"overturn recomputes lifetime downward; expected 0, got {data['lifetime_penalty_points']}"
    )
    assert data["rolling_penalty_points"] == 0, (
        f"overturn recomputes rolling downward; expected 0, got {data['rolling_penalty_points']}"
    )


def test_appeal_uphold_keeps_penalty_points(api):
    """PRD §3.7: "If the regulator upholds the appeal outcome against the operator
    (`APPEALED → UPHELD`), the violation continues to count toward the rolling and
    lifetime totals exactly as before — no recomputation is needed."

    Design: Difficulty/non_linear_state_machine/violation_appeal_overturn_branch
    """
    op, vio = _assessed_appealed_staging(api, "Branch2 Co")
    upheld = transition_violation_authority(api, vio["id"], "UPHOLD")
    assert upheld["status"] == "UPHELD"
    data = _get_operator(api, op["id"])
    assert data["lifetime_penalty_points"] == 3, (
        f"uphold keeps the STAGING points; expected 3, got {data['lifetime_penalty_points']}"
    )


# --- boundary precision: suspension threshold at 12 points ----------------
def test_penalty_exactly_twelve_suspends_operator(api):
    """PRD §3.7: "The regulator assesses an `OPEN` violation (`OPEN → ASSESSED`),
    which stamps `assessed_at` from the logical clock, recomputes the cited
    operator's `rolling_penalty_points` and `lifetime_penalty_points`, and, if the
    operator was `ACTIVE` and its recomputed rolling total now stands at twelve
    points or more, auto-suspends the operator with `suspended_reason`
    `PENALTY_THRESHOLD` and its cascade."

    Design: Difficulty/boundary_precision_check/penalty_threshold_ge_12_boundary
    """
    set_clock(api, "2026-03-01T00:00:00Z")
    op = create_operator(api, operator_type="TNC", legal_name="Edge Co", activate=True)
    _assess(api, op["id"], "AVI_MISMATCH")  # 6
    _assess(api, op["id"], "NO_DECAL")      # +6 -> 12 (crosses threshold)
    data = _get_operator(api, op["id"])
    assert data["rolling_penalty_points"] == 12, f"expected rolling 12, got {data['rolling_penalty_points']}"
    assert data["status"] == "SUSPENDED", f"12 >= 12 must suspend; got {data['status']}"


def test_penalty_eleven_stays_active(api):
    """PRD §3.7: "if the operator was `ACTIVE` and its recomputed rolling total now
    stands at twelve points or more, auto-suspends the operator with
    `suspended_reason` `PENALTY_THRESHOLD` and its cascade."

    Design: Difficulty/boundary_precision_check/penalty_threshold_ge_12_boundary
    """
    set_clock(api, "2026-03-01T00:00:00Z")
    op = create_operator(api, operator_type="TNC", legal_name="Below Co", activate=True)
    _assess(api, op["id"], "CURB")     # 4
    _assess(api, op["id"], "CURB")     # +4 -> 8
    _assess(api, op["id"], "STAGING")  # +3 -> 11
    data = _get_operator(api, op["id"])
    assert data["rolling_penalty_points"] == 11, f"expected rolling 11, got {data['rolling_penalty_points']}"
    assert data["status"] == "ACTIVE", f"11 < 12 must stay ACTIVE; got {data['status']}"


def test_penalty_thirteen_suspends_operator(api):
    """PRD §3.7: "if the operator was `ACTIVE` and its recomputed rolling total now
    stands at twelve points or more, auto-suspends the operator with
    `suspended_reason` `PENALTY_THRESHOLD` and its cascade."

    Design: Difficulty/boundary_precision_check/penalty_threshold_ge_12_boundary
    """
    set_clock(api, "2026-03-01T00:00:00Z")
    op = create_operator(api, operator_type="TNC", legal_name="Above Co", activate=True)
    _assess(api, op["id"], "AVI_MISMATCH")  # 6
    _assess(api, op["id"], "CURB")          # +4 -> 10
    _assess(api, op["id"], "STAGING")       # +3 -> 13 (crosses threshold)
    data = _get_operator(api, op["id"])
    assert data["rolling_penalty_points"] == 13, f"expected rolling 13, got {data['rolling_penalty_points']}"
    assert data["status"] == "SUSPENDED", f"13 >= 12 must suspend; got {data['status']}"


# --- temporal validation: appeal window --------------------------------
def test_appeal_after_window_returns_appeal_window_closed(api):
    """PRD §3.7: "The operator may appeal an `ASSESSED` violation
    (`ASSESSED → APPEALED`), but only while the logical clock is within 14 days of
    `assessed_at`; an appeal filed more than 14 days after assessment is rejected
    with `ERR_APPEAL_WINDOW_CLOSED`."

    Design: Corner/validations/appeal_after_window_returns_appeal_window_closed
    """
    set_clock(api, "2026-03-01T00:00:00Z")
    op = create_operator(api, operator_type="TAXI", legal_name="Late Co", activate=True)
    vio = issue_violation(api, op["id"], "STAGING")
    transition_violation_authority(api, vio["id"], "ASSESS")
    set_clock(api, "2026-03-21T00:00:00Z")  # 20 days later, window is 14
    resp = api.transition_violation(vio["id"], {"action": "APPEAL"}, make_operator_headers(op["id"]))
    validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED.value, 409)
