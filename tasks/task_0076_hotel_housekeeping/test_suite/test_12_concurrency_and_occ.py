"""Concurrency and optimistic-concurrency tests for PRD §2.9.

PRD §2.9 spells out five guarantees:
- Two supervisors inspect the same SUBMITTED task → loser sees
  ERR_TASK_NOT_SUBMITTED.
- Two supervisors dispatch isolating tickets on the same room → loser
  sees ERR_ROOM_ALREADY_ISOLATED.
- Accept and reassign race on the same ASSIGNED task → loser sees
  ERR_TASK_NOT_ASSIGNED.
- Two posts on the same PENDING consumption → loser sees
  ERR_CONSUMPTION_NOT_PENDING.
- PATCH with a stale version → ERR_VERSION_CONFLICT.

Per the test-generator silence rules, race tests are only generated for
the four PRD-named loser error_ids above; the OCC version test is a
direct PATCH check.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    inspect_cleaning_task_payload,
    make_housekeeper_headers,
    reassign_cleaning_task_payload,
    run_race,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers.fixtures import (
    create_housekeeper_on_shift,
    create_maintenance_ticket,
    create_room,
    setup_consumption_in_state,
    setup_room_and_housekeeper,
    setup_room_hk_task,
    setup_task_in_state,
)


# ===========================================================================
# Race 1: two /inspect on the same SUBMITTED task (PRD §2.9)
# ===========================================================================
def test_race_two_inspects_on_same_submitted_task_one_wins(api):
    """PRD §2.9: "When two supervisors submit an inspection for the
    same SUBMITTED cleaning task at the same instant, exactly one
    wins; the loser observes that the task has already moved past
    SUBMITTED and receives ERR_TASK_NOT_SUBMITTED."

    PRD §3.3 also says "Touching a task in COMPLETED or CANCELLED with
    a state-changing request is rejected with ERR_TASK_TERMINAL."
    After the first inspect PASSes the task into COMPLETED, the second
    inspect lands on a terminal task — the terminal guard and the
    not-submitted guard both apply, and PRD §2.6 sequences them so
    closely (both state-family checks) that a faithful PRD-only reader
    may produce either id on the loser. Accept either.
    """
    room, hk, task = setup_task_in_state(
        target="SUBMITTED",
        clock_advance_minutes_between_start_submit=10,
    )
    payload = inspect_cleaning_task_payload(outcome="PASS")
    sup_a = TEST_USERS["supervisor_headers"]
    sup_b = TEST_USERS["supervisor_headers_alt"]
    results = run_race(
        lambda: api.inspect_cleaning_task(task["id"], payload, sup_a),
        lambda: api.inspect_cleaning_task(task["id"], payload, sup_b),
    )
    outcome = assert_race_outcome(results, expected_successes=1,
                                  expected_failures=1)
    loser = outcome["failures"][0]
    body = loser.json()
    assert body["data"]["error_id"] in {
        ApiErrorId.ERR_TASK_NOT_SUBMITTED.value,
        ApiErrorId.ERR_TASK_TERMINAL.value,
    }, (
        "PRD §2.9 names ERR_TASK_NOT_SUBMITTED; PRD §3.3 names "
        "ERR_TASK_TERMINAL for the terminal touch that arises when the "
        "first inspect already drove the task to COMPLETED."
    )


# ===========================================================================
# Race 2: two /dispatch on the same room with isolating tickets (PRD §2.9)
# ===========================================================================
def test_race_two_isolating_dispatches_on_same_room_one_wins(api):
    """PRD §2.9: "When two supervisors attempt to dispatch isolating
    maintenance tickets against the same room, exactly one wins by
    being the first to set Room.out_of_order_ticket_id; the loser
    receives ERR_ROOM_ALREADY_ISOLATED."
    """
    room, hk = setup_room_and_housekeeper()
    m1 = create_maintenance_ticket(
        room_id=room["id"], reporter_housekeeper_id=hk["id"],
        severity="CRITICAL",
    )
    m2 = create_maintenance_ticket(
        room_id=room["id"], reporter_housekeeper_id=hk["id"],
        severity="CRITICAL",
    )
    payload_a = {"engineering_assignee": "eng-A"}
    payload_b = {"engineering_assignee": "eng-B"}
    sup_a = TEST_USERS["supervisor_headers"]
    sup_b = TEST_USERS["supervisor_headers_alt"]
    results = run_race(
        lambda: api.dispatch_maintenance_ticket(
            m1["id"], payload_a, sup_a,
        ),
        lambda: api.dispatch_maintenance_ticket(
            m2["id"], payload_b, sup_b,
        ),
    )
    outcome = assert_race_outcome(results, 1, 1)
    loser = outcome["failures"][0]
    body = loser.json()
    assert body["data"]["error_id"] == \
        ApiErrorId.ERR_ROOM_ALREADY_ISOLATED.value, (
            "PRD §2.9: the loser must receive ERR_ROOM_ALREADY_ISOLATED."
        )


# ===========================================================================
# Race 3: accept vs reassign on the same ASSIGNED task (PRD §2.9)
# ===========================================================================
# NOTE: removed test_race_accept_vs_reassign_one_wins per the
# PRD-First / unique-derivability rule. PRD §2.9 asserts "exactly one
# operation succeeds and the loser receives ERR_TASK_NOT_ASSIGNED" for
# a concurrent accept-vs-reassign on the same ASSIGNED task, but PRD
# §3.3 separately states "A supervisor may reassign an ASSIGNED or
# ACCEPTED task" — i.e., reassign is explicitly legal from the ACCEPTED
# state. Under the natural serialisation imposed by §2.9 itself, the
# accept-first ordering leaves the task in ACCEPTED and the subsequent
# reassign is a PRD §3.3-legal write that must succeed; both
# operations therefore succeed and the "exactly one wins" axiom does
# not uniquely determine the system's behaviour from PRD prose alone.
# Per the diagnostic protocol (STEP 1b, unique-derivability silence),
# this test is removed.


# ===========================================================================
# Race 4: two /post on the same PENDING consumption (PRD §2.9)
# ===========================================================================
def test_race_two_posts_on_same_pending_consumption_one_wins(api):
    """PRD §2.9: "When two attempts to post the same PENDING minibar
    consumption arrive together, the first wins; the loser receives
    ERR_CONSUMPTION_NOT_PENDING."
    """
    room, items, pending = setup_consumption_in_state(target="PENDING")
    fd_a = TEST_USERS["frontdesk_headers"]
    fd_b = TEST_USERS["frontdesk_headers_alt"]
    results = run_race(
        lambda: api.post_minibar_consumption(pending["id"], fd_a),
        lambda: api.post_minibar_consumption(pending["id"], fd_b),
    )
    outcome = assert_race_outcome(results, 1, 1)
    loser = outcome["failures"][0]
    body = loser.json()
    assert body["data"]["error_id"] == \
        ApiErrorId.ERR_CONSUMPTION_NOT_PENDING.value


# ===========================================================================
# Optimistic concurrency (PRD §2.4, §2.9)
# ===========================================================================
def test_patch_with_stale_version_returns_version_conflict(api):
    """PRD §2.4: "PATCH endpoints accept an optional version field in
    the request body. When version is supplied, the server compares it
    for strict equality with the current server value and rejects a
    mismatch with ERR_VERSION_CONFLICT; when version is omitted, the
    optimistic-concurrency check is skipped."

    PRD §2.9: "the optimistic-concurrency version mismatch on any
    PATCH endpoint yields ERR_VERSION_CONFLICT."
    """
    room, hk, task = setup_room_hk_task(task_source="SCHEDULED")
    original_version = task["version"]
    # First PATCH succeeds and increments version (PRD §2.4: 'version
    # increments by one and updated_at refreshes to the moment of the
    # write.').
    res = api.patch_cleaning_task(
        task["id"], {"expedite_flag": True, "version": original_version},
        TEST_USERS["supervisor_headers"],
    )
    bumped = validate_success(res)
    assert bumped["version"] == original_version + 1
    # Second PATCH with the now-stale original version → conflict.
    res = api.patch_cleaning_task(
        task["id"], {"expedite_flag": False, "version": original_version},
        TEST_USERS["supervisor_headers"],
    )
    validate_error(res, ApiErrorId.ERR_VERSION_CONFLICT.value)


def test_patch_without_version_is_unconditional(api):
    """PRD §2.4: "when version is omitted, the optimistic-concurrency
    check is skipped."
    """
    room, hk, task = setup_room_hk_task(task_source="SCHEDULED")
    # Bump version with one PATCH:
    api.patch_cleaning_task(
        task["id"], {"expedite_flag": True},
        TEST_USERS["supervisor_headers"],
    )
    # A second PATCH without 'version' must still succeed (no conflict).
    res = api.patch_cleaning_task(
        task["id"], {"expedite_flag": False},
        TEST_USERS["supervisor_headers"],
    )
    data = validate_success(res)
    assert data["expedite_flag"] is False
