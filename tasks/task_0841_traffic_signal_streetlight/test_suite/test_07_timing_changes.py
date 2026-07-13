"""Timing-change-request fork and revision loop, and terminal-state lockdown."""
from test_helpers import validate_success, validate_error
from test_helpers.fixtures import new_intersection, new_timing_change_request, get_timing_change_request


def _tcr_in_changes_requested(api, te_headers):
    inter = new_intersection()
    tcr = new_timing_change_request(inter["id"], proposed_cycle_length_sec=90,
                                    proposed_offset_sec=10, rationale="peak tuning")
    validate_success(api.start_review_timing_change_request(tcr["id"], te_headers), 200)
    validate_success(api.request_changes_timing_change_request(tcr["id"], te_headers), 200)
    return tcr


# ── Difficulty: UNDER_REVIEW fork + CHANGES_REQUESTED -> SUBMITTED loop ───────
def test_resubmit_from_changes_requested_returns_to_submitted(api, traffic_engineer_headers, dispatcher_headers):
    """PRD §3.6: "Requesting changes moves it to `CHANGES_REQUESTED` with no side
    effects, returning it to the submitter."
    PRD §3.6: "A `CHANGES_REQUESTED` request is resubmitted by a dispatcher or
    traffic engineer back to `SUBMITTED`, which increments `revision_count` by one
    and optionally overwrites `proposed_cycle_length_sec`, `proposed_offset_sec`,
    and `rationale` from the resubmission body."

    Design: Difficulty/non_linear_state_machine/timing_change_fork_and_revision_loop
    """
    tcr = _tcr_in_changes_requested(api, traffic_engineer_headers)
    res = api.resubmit_timing_change_request(tcr["id"], {"proposed_cycle_length_sec": 100},
                                             dispatcher_headers)
    resubmitted = validate_success(res, 200)
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision_count"] == 1, \
        f"expected revision_count 1, got {resubmitted['revision_count']}"


def test_resubmit_overwrites_proposed_cycle_length(api, traffic_engineer_headers, dispatcher_headers):
    """PRD §3.6: "A `CHANGES_REQUESTED` request is resubmitted by a dispatcher or
    traffic engineer back to `SUBMITTED`, which increments `revision_count` by one
    and optionally overwrites `proposed_cycle_length_sec`, `proposed_offset_sec`,
    and `rationale` from the resubmission body."

    Design: Difficulty/non_linear_state_machine/timing_change_fork_and_revision_loop
    """
    tcr = _tcr_in_changes_requested(api, traffic_engineer_headers)
    res = api.resubmit_timing_change_request(tcr["id"], {"proposed_cycle_length_sec": 100},
                                             dispatcher_headers)
    resubmitted = validate_success(res, 200)
    assert resubmitted["proposed_cycle_length_sec"] == 100


# ── Corner: reject twice on terminal REJECTED ────────────────────────────────
def test_reject_already_rejected_returns_invalid_state(api, traffic_engineer_headers):
    """PRD §3.6: "Rejection moves it to the terminal `REJECTED` state and only
    stamps `decided_at`, applying no change to the intersection."
    PRD §2.9: "State — the target resource is in a state from which the requested
    transition is defined, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/reject_terminal_timing_change_locked
    """
    inter = new_intersection()
    tcr = new_timing_change_request(inter["id"], proposed_cycle_length_sec=90,
                                    proposed_offset_sec=5, rationale="x")
    validate_success(api.start_review_timing_change_request(tcr["id"], traffic_engineer_headers), 200)
    validate_success(api.reject_timing_change_request(tcr["id"], traffic_engineer_headers), 200)
    res = api.reject_timing_change_request(tcr["id"], traffic_engineer_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    assert get_timing_change_request(tcr["id"])["status"] == "REJECTED"
