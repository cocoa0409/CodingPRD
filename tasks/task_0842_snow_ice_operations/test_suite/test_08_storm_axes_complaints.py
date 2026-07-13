"""Parallel storm status axes (operational vs billing) and the cyclic complaint
workflow (OPEN -> INVESTIGATING -> RESOLVED -> REOPENED -> INVESTIGATING).

Difficulty queue: non_linear_state_machine.
"""
from test_helpers import (
    validate_success, TEST_USERS,
    new_storm, setup_closed_storm, setup_open_complaint, activate_storm, close_storm,
)

DISPATCH = TEST_USERS["dispatch_headers"]
CITIZEN = TEST_USERS["citizen_headers"]


# --- non_linear_state_machine / storm_parallel_axes -----------------------

def test_finalize_billing_advances_only_billing_axis(api):
    """PRD §3.2: "Finalizing billing moves `billing_status` from `OPEN` to `FINALIZED` and
    increments the storm's `version`. It carries the single cross-axis guard: the storm's
    `operational_status` must already be `CLOSED`." PRD §3.2: "The operational `CLOSED`
    state and the billing `FINALIZED` state are each terminal on their respective axis."

    Design: Difficulty/non_linear_state_machine/storm_parallel_axes
    """
    storm = setup_closed_storm()["storm"]
    data = validate_success(api.finalize_billing(storm["id"], DISPATCH), 200)
    assert data["billing_status"] == "FINALIZED", data
    assert data["operational_status"] == "CLOSED", data


def test_operational_transitions_leave_billing_open(api):
    """PRD §3.2: "A storm carries two independent status axes." PRD §3.2: "These axes are
    independent except for one guard described below." PRD §3.2: "The billing axis,
    `billing_status`, begins at `OPEN`".

    Design: Difficulty/non_linear_state_machine/storm_parallel_axes
    """
    storm = new_storm(severity="LIGHT")
    activate_storm(storm["id"])
    closed = close_storm(storm["id"])
    # operational axis has advanced to CLOSED, but the billing axis is untouched.
    assert closed["operational_status"] == "CLOSED", closed
    assert closed["billing_status"] == "OPEN", closed


# --- non_linear_state_machine / complaint_reopen_cycle --------------------

def test_complaint_reopen_then_reinvestigate_cycle(api):
    """PRD §3.8: "A `RESOLVED` complaint may be reopened to `REOPENED`, from which it can
    be investigated again, and so on indefinitely — complaints have no terminal state."
    PRD §3.8: "Investigation moves a complaint into `INVESTIGATING` — permitted from either
    `OPEN` or `REOPENED` — and while doing so sets `missed_street_confirmed` from the
    request's `confirm_missed` flag, recording whether the street was in fact never
    serviced."

    Design: Difficulty/non_linear_state_machine/complaint_reopen_cycle
    """
    cmp = setup_open_complaint(complaint_type="MISSED_STREET")["complaint"]
    investigated = validate_success(
        api.investigate_complaint(cmp["id"], {"confirm_missed": True}, CITIZEN), 200)
    assert investigated["status"] == "INVESTIGATING", investigated
    assert investigated["missed_street_confirmed"] is True, investigated
    validate_success(api.resolve_complaint(cmp["id"], CITIZEN), 200)
    validate_success(api.reopen_complaint(cmp["id"], CITIZEN), 200)
    reinvestigated = validate_success(api.investigate_complaint(cmp["id"], {}, CITIZEN), 200)
    assert reinvestigated["status"] == "INVESTIGATING", reinvestigated


def test_complaint_reopen_edge_from_resolved(api):
    """PRD §3.8: "Resolution moves an `INVESTIGATING` complaint to `RESOLVED`. A `RESOLVED`
    complaint may be reopened to `REOPENED`, from which it can be investigated again, and so
    on indefinitely — complaints have no terminal state."

    Design: Difficulty/non_linear_state_machine/complaint_reopen_cycle
    """
    cmp = setup_open_complaint(complaint_type="ICY_CONDITIONS")["complaint"]
    validate_success(api.investigate_complaint(cmp["id"], {}, CITIZEN), 200)
    validate_success(api.resolve_complaint(cmp["id"], CITIZEN), 200)
    reopened = validate_success(api.reopen_complaint(cmp["id"], CITIZEN), 200)
    assert reopened["status"] == "REOPENED", reopened
