"""Complaint revision cycle and resident notification counting.

Translates the queue A (Difficulty) non_linear_state_machine complaint-cycle
instance and the queue B (Corner) notify derived-field instance.
"""
from test_helpers import (
    validate_success,
    TEST_USERS,
    setup_resolved_complaint, reopen_complaint, resolve_complaint,
    create_route, create_block, create_resident, create_sweep_event,
)

DISPATCHER = TEST_USERS["route_dispatcher_headers"]


def test_complaint_full_revision_cycle_returns_resolved(api):
    """PRD §3.8: "A reopened complaint can be resolved again by a dispatcher, advancing it `REOPENED → RESOLVED` with a fresh `resolution_note`. The full revision cycle is therefore `OPEN → RESOLVED → REOPENED → RESOLVED`."

    Design: Difficulty/non_linear_state_machine/complaint_reopen_cycle
    """
    block, resident, resolved = setup_resolved_complaint()
    assert resolved["status"] == "RESOLVED"
    reopened = reopen_complaint(resolved["id"], resident["id"], reason="still dirty")
    assert reopened["status"] == "REOPENED"
    re_resolved = resolve_complaint(resolved["id"], resolution_note="re-swept")
    assert re_resolved["status"] == "RESOLVED"


def test_reopened_complaint_records_fresh_resolution_note(api):
    """PRD §3.8: "The owning resident may reopen a resolved complaint, advancing it `RESOLVED → REOPENED` (permitted only from `RESOLVED`, and only when the caller's `X-User-ID` equals the complaint's `resident_id`); an optional `reason` may accompany the reopen."

    Design: Difficulty/non_linear_state_machine/complaint_reopen_cycle
    """
    block, resident, resolved = setup_resolved_complaint()
    reopen_complaint(resolved["id"], resident["id"], reason="still dirty")
    re_resolved = resolve_complaint(resolved["id"], resolution_note="re-swept")
    assert re_resolved["resolution_note"] == "re-swept"


def test_notify_counts_optin_residents_on_block(api):
    """PRD §3.8: "A dispatcher triggers a notification run on a scheduled sweep, optionally naming a `channel`; the run sets the event's `notified_resident_count` to the number of opted-in residents on that event's block."

    Design: Corner/cross_cutting_complexity_layers/notify_counts_optin_residents_on_block
    """
    route = create_route()
    block = create_block(route["id"], restriction_start_local="06:00", restriction_end_local="12:00")
    create_resident(block["id"], email="in@x.com", full_name="In", notify_opt_in=True)
    create_resident(block["id"], email="out@x.com", full_name="Out", notify_opt_in=False)
    ev = create_sweep_event(block["id"])
    notified = validate_success(api.notify_sweep_event(ev["id"], {"channel": "EMAIL"}, DISPATCHER), 200)
    assert notified["notified_resident_count"] == 1
