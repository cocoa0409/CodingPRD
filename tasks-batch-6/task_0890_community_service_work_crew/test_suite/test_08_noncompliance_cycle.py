"""Non-compliance, reinstatement, and the ACTIVE -> NON_COMPLIANT -> ACTIVE cycle.

Covers Difficulty queue: non_linear_state_machine (referral cycle). Covers Corner queue:
reinstate-on-active invalid transition.
"""
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS,
)
from test_helpers import fixtures as fx

COORD = TEST_USERS["coordinator_headers"]
CLERK = TEST_USERS["clerk_headers"]


def test_reportback_then_reinstate_returns_to_active(api):
    """PRD §3.7: "A `REPORT_BACK` reports the participant back to court and drives the referral from `ACTIVE`
    to `NON_COMPLIANT`".
    PRD §3.7: "Reinstatement, filed by a `CourtClerk`, returns the referral from `NON_COMPLIANT` to
    `ACTIVE`".

    Design: Difficulty/non_linear_state_machine/nlsm_referral_active_noncompliant_active_cycle
    """
    part = fx.new_participant()
    ref = fx.new_referral(part["id"], hours_ordered=20, court_case_number="CR-5")
    action = fx.report_back(ref["id"], reason="Missed sessions")
    assert action["resulting_referral_status"] == "NON_COMPLIANT"
    non_compliant = validate_success(api.get_referral(ref["id"], COORD), 200)
    assert non_compliant["status"] == "NON_COMPLIANT"
    reinstated = validate_success(api.reinstate_referral(ref["id"], CLERK), 200)
    assert reinstated["status"] == "ACTIVE"


def test_reinstatement_loop_runs_more_than_once(api):
    """PRD §3.7: "This forms the reinstatement loop: a referral may pass `ACTIVE → NON_COMPLIANT → ACTIVE`
    more than once."

    Design: Difficulty/non_linear_state_machine/nlsm_referral_active_noncompliant_active_cycle
    """
    part = fx.new_participant()
    ref = fx.new_referral(part["id"], hours_ordered=20, court_case_number="CR-5B")
    for _ in range(2):
        fx.report_back(ref["id"], reason="Missed sessions")
        nc = validate_success(api.get_referral(ref["id"], COORD), 200)
        assert nc["status"] == "NON_COMPLIANT"
        back = validate_success(api.reinstate_referral(ref["id"], CLERK), 200)
        assert back["status"] == "ACTIVE"


def test_reinstate_active_referral_returns_invalid_state(api):
    """PRD §3.7: "Reinstatement, filed by a `CourtClerk`, returns the referral from `NON_COMPLIANT` to
    `ACTIVE`".
    PRD §2.9: "the generic state check that a resource admits the requested transition, else
    `ERR_INVALID_STATE`".

    Design: Corner/state_machines/reinstate_active_referral_returns_invalid_state
    """
    part = fx.new_participant()
    ref = fx.new_referral(part["id"], hours_ordered=20, court_case_number="CR-D6")
    res = api.reinstate_referral(ref["id"], CLERK)
    validate_error(res, "ERR_INVALID_STATE", 409)
