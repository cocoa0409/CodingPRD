"""Evidence-based wellness programs and enrollments: the projected-vs-final
graduation divergence, the ACTIVE<->LAPSED re-engagement cycle, the finalize
fidelity boundary, and terminal-state lockdown.

Translates queue A instances dv_wellness_projected_vs_final and
nl_wellness_active_lapsed_cycle, plus queue B corner instances for finalize
terminal lockdown and the exact-fidelity graduation boundary.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    fixtures,
)

COORD = TEST_USERS["coordinator_headers"]


# ---------------------------------------------------------------------------
# Queue A — dual_variant_calc/dv_wellness_projected_vs_final
# ---------------------------------------------------------------------------
def test_wellness_projected_will_graduate_before_finalize(api):
    """PRD 3.7: "It is `WILL_GRADUATE` when the program's `total_sessions` minus the enrollment's `absences_total` is at least the program's `fidelity_min_sessions`, and `AT_RISK` otherwise."

    Design: Difficulty/dual_variant_calc/dv_wellness_projected_vs_final
    """
    ctx = fixtures.setup_enrollment(total_sessions=6, fidelity_min_sessions=5)
    enr_id = ctx["enrollment"]["id"]
    for _ in range(3):
        fixtures.log_session(enr_id, True)
    fixtures.log_session(enr_id, False)  # first absence: stays ACTIVE, absences_total=1

    data = validate_success(api.get_enrollment(enr_id, COORD))
    assert data["projected_graduation_status"] == "WILL_GRADUATE", (
        f"6 - 1 = 5 >= fidelity 5, got {data['projected_graduation_status']}"
    )
    assert data["sessions_attended"] == 3, f"expected 3, got {data['sessions_attended']}"
    assert data["absences_total"] == 1, f"expected 1, got {data['absences_total']}"


def test_wellness_finalizes_to_withdrawn_despite_will_graduate_projection(api):
    """PRD 3.7: "Note that the projected outlook and the final outcome can diverge: an enrollment reading `WILL_GRADUATE` can still be finalized to `WITHDRAWN` if it is finalized before enough sessions have actually been attended."

    Design: Difficulty/dual_variant_calc/dv_wellness_projected_vs_final
    """
    ctx = fixtures.setup_enrollment(total_sessions=6, fidelity_min_sessions=5)
    enr_id = ctx["enrollment"]["id"]
    for _ in range(3):
        fixtures.log_session(enr_id, True)
    fixtures.log_session(enr_id, False)

    data = validate_success(api.finalize_enrollment(enr_id, COORD))
    assert data["status"] == "WITHDRAWN", (
        f"sessions_attended 3 < fidelity 5 finalizes to WITHDRAWN, got {data['status']}"
    )


# ---------------------------------------------------------------------------
# Queue A — non_linear_state_machine/nl_wellness_active_lapsed_cycle
# ---------------------------------------------------------------------------
def test_wellness_reengagement_returns_lapsed_to_active(api):
    """PRD 3.7: "Logging an attended session (`attended` true) while the enrollment is `LAPSED` is a re-engagement: it increments `sessions_attended` by 1, resets `consecutive_absences` to 0, and moves the enrollment from `LAPSED` back to `ACTIVE`, closing the cycle."

    Design: Difficulty/non_linear_state_machine/nl_wellness_active_lapsed_cycle
    """
    ctx = fixtures.setup_enrollment(total_sessions=8, fidelity_min_sessions=5, model="MATTER_OF_BALANCE")
    enr_id = ctx["enrollment"]["id"]
    fixtures.log_session(enr_id, False)
    fixtures.log_session(enr_id, False)  # now LAPSED (consecutive_absences=2)

    data = validate_success(api.log_session(enr_id, True, COORD))
    assert data["status"] == "ACTIVE", f"re-engagement must return to ACTIVE, got {data['status']}"
    assert data["sessions_attended"] == 1, f"expected 1, got {data['sessions_attended']}"
    assert data["consecutive_absences"] == 0, f"expected 0, got {data['consecutive_absences']}"
    assert data["absences_total"] == 2, f"absences_total is monotonic, got {data['absences_total']}"


def test_wellness_lapses_at_second_consecutive_absence(api):
    """PRD 3.7: "Whether the enrollment lapses depends on the resulting streak against a lapse threshold of 2 consecutive absences: if the value `consecutive_absences` would reach after this log (its current value plus one) is at least 2, the enrollment transitions from `ACTIVE` to `LAPSED`; if that value is still below 2 (that is, this is the first absence in the streak), the enrollment stays `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/nl_wellness_active_lapsed_cycle
    """
    ctx = fixtures.setup_enrollment(total_sessions=8, fidelity_min_sessions=5, model="MATTER_OF_BALANCE")
    enr_id = ctx["enrollment"]["id"]

    after_first = validate_success(api.log_session(enr_id, False, COORD))
    assert after_first["status"] == "ACTIVE", (
        f"first absence stays ACTIVE (consecutive 1 < 2), got {after_first['status']}"
    )
    assert after_first["consecutive_absences"] == 1, f"expected 1, got {after_first['consecutive_absences']}"

    after_second = validate_success(api.log_session(enr_id, False, COORD))
    assert after_second["status"] == "LAPSED", (
        f"second consecutive absence lapses the enrollment, got {after_second['status']}"
    )


# ---------------------------------------------------------------------------
# Queue B — finalize boundary and terminal lockdown
# ---------------------------------------------------------------------------
def test_finalize_graduates_at_exact_fidelity_threshold(api):
    """PRD 3.7: "Finalize decides the outcome by the pessimistic final variant, which counts only sessions actually attended: if `sessions_attended` is at least the program's `fidelity_min_sessions`, the enrollment moves to `GRADUATED`; otherwise it moves to `WITHDRAWN`."

    Design: Corner/state_machines/corner_wellness_finalize_graduates_at_exact_fidelity_threshold
    """
    ctx = fixtures.setup_enrollment(total_sessions=6, fidelity_min_sessions=3, model="DPP")
    enr_id = ctx["enrollment"]["id"]
    for _ in range(3):
        fixtures.log_session(enr_id, True)

    data = validate_success(api.finalize_enrollment(enr_id, COORD))
    assert data["status"] == "GRADUATED", (
        f"sessions_attended 3 >= fidelity 3 graduates at equality, got {data['status']}"
    )
    assert data["sessions_attended"] == 3, f"expected 3, got {data['sessions_attended']}"


def test_finalize_already_graduated_enrollment_rejected(api):
    """PRD 3.7: "Finalizing an enrollment is a `Coordinator` action, permitted only while the enrollment's `status` is `ACTIVE` or `LAPSED` (finalizing from any other state is `ERR_INVALID_STATE`, 409)."

    Design: Corner/state_machines/corner_finalize_graduated_enrollment_terminal_lockdown
    """
    ctx = fixtures.setup_enrollment(total_sessions=6, fidelity_min_sessions=1, model="CDSMP")
    enr_id = ctx["enrollment"]["id"]
    fixtures.log_session(enr_id, True)
    graduated = fixtures.finalize(enr_id)
    assert graduated["status"] == "GRADUATED", f"precondition: must be GRADUATED, got {graduated['status']}"

    resp = api.finalize_enrollment(enr_id, COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
