"""QuitAttempt cyclic state machine: COMMITTED -> RELAPSED -> COMMITTED recommit."""
from test_helpers import (
    validate_success, TEST_USERS,
    set_clock, setup_active_enrollment, create_quit_attempt,
)

CM = TEST_USERS["case_manager_headers"]


def _committed_attempt(api):
    set_clock(api, "2026-06-01T00:00:00Z")
    ctx = setup_active_enrollment(api, cpd=10, sponsored=False)
    qa = create_quit_attempt(api, ctx["enrollment_id"], "2026-06-02T00:00:00Z", "COLD_TURKEY")
    return ctx, qa


def test_quit_attempt_relapse_then_recommit_updates_quit_date(api):
    """PRD §3.4: "a `RELAPSED` attempt may recommit back to `COMMITTED`, which
    requires the enrollment to be `ACTIVE` (else `ERR_ENROLLMENT_NOT_ACTIVE`) and a
    new `quit_date` in the request, and updates the attempt's `quit_date` to that
    recommit value."

    Design: Difficulty/non_linear_state_machine/quit_attempt_relapse_recommit_cycle
    """
    ctx, qa = _committed_attempt(api)
    validate_success(api.transition_quit_attempt(qa["id"], {"to_status": "RELAPSED"}, CM))
    recommitted = validate_success(
        api.transition_quit_attempt(
            qa["id"], {"to_status": "COMMITTED", "quit_date": "2026-06-15T00:00:00Z"}, CM
        )
    )
    assert recommitted["status"] == "COMMITTED"
    assert recommitted["quit_date"] == "2026-06-15T00:00:00Z"


def test_quit_attempt_relapse_from_committed(api):
    """PRD §3.4: "A quit attempt may be marked `RELAPSED` from either `COMMITTED` or
    `QUIT_ACHIEVED`; relapse forfeits the enrollment's `EARNED` awards whose
    `milestone_type` is `SEVEN_DAY_ABSTINENT` or `THIRTY_DAY_ABSTINENT`, moving each
    to `FORFEITED`, crediting the sponsor budget by each forfeited amount, and
    incrementing the program's `version` per credit."

    Design: Difficulty/non_linear_state_machine/quit_attempt_relapse_recommit_cycle
    """
    ctx, qa = _committed_attempt(api)
    relapsed = validate_success(
        api.transition_quit_attempt(qa["id"], {"to_status": "RELAPSED"}, CM)
    )
    assert relapsed["status"] == "RELAPSED"
