"""Reminder cadence: 24h first window, 48h spacing, cap of three, skip semantics."""
from test_helpers import (
    assert_reminder_event,
    get_invite,
    set_clock,
    setup_cycle_with_field_results,
    validate_paginated,
    validate_success,
    api_client,
)
from test_helpers import TEST_USERS

PEOPLE_ANALYST = TEST_USERS["people_analyst_headers"]

CLOSES_LATE = "2026-09-30T00:00:00Z"


def _open_one_invite_cycle(api, unit_name, manager_id):
    return setup_cycle_with_field_results(
        unit_name=unit_name,
        manager_user_id=manager_id,
        num_employees=1,
        target_state="OPEN",
        closes_at=CLOSES_LATE,
    )


def test_three_reminder_sweeps_each_remind_once(api):
    """PRD §3.4: "An invitation in `INVITED` status becomes `REMINDED` when all
    of the following hold: the cycle is `OPEN`; the invitation's
    `reminder_count` is below the cap of three; and either the invitation has
    never been reminded and at least twenty-four hours have elapsed since the
    cycle opened, or at least forty-eight hours have elapsed since
    `last_reminded_at`. An invitation already in `REMINDED` status is reminded
    again under the same rules — cap below three, and at least forty-eight
    hours elapsed since `last_reminded_at`."

    Design: Difficulty/non_linear_state_machine/invite_reminded_self_loop_with_cap
    """
    sc = _open_one_invite_cycle(api, "RemindA", "mgr-ra")
    invite_id = sc["invites"][0]["id"]

    for i, ts in enumerate(
        ["2026-09-02T00:00:01Z", "2026-09-04T00:00:02Z", "2026-09-06T00:00:03Z"],
        start=1,
    ):
        set_clock(ts)
        resp = api.remind_cycle(sc["cycle"]["id"], PEOPLE_ANALYST)
        data = validate_success(resp, 200)
        assert data["reminded_count"] == 1, f"sweep {i}: one eligible invite reminded"
        assert invite_id in data["reminded_invite_ids"]

    invite = get_invite(invite_id)
    assert invite["status"] == "REMINDED"
    assert invite["reminder_count"] == 3, "three successful self-loops, one increment each"
    assert invite["last_reminded_at"] is not None


def test_fourth_sweep_is_cap_blocked_and_reminder_events_accumulate(api):
    """PRD §3.4: "Invitations blocked by the cap or the cadence are not errors
    — the sweep simply skips them and returns success with `reminded_count`
    and `reminded_invite_ids` reflecting the reminders actually sent."
    PRD §3.4: "Each successful reminder appends a reminder event recording
    `sent_at` and the next 1-based `sequence_no` for that invitation,
    increments `reminder_count` by 1, stamps `last_reminded_at` with the
    current logical time, and increments the invitation's `version` by 1."

    Design: Difficulty/non_linear_state_machine/invite_reminded_self_loop_with_cap
    """
    sc = _open_one_invite_cycle(api, "RemindB", "mgr-rb")
    invite_id = sc["invites"][0]["id"]

    for ts in ["2026-09-02T00:00:01Z", "2026-09-04T00:00:02Z", "2026-09-06T00:00:03Z"]:
        set_clock(ts)
        validate_success(api.remind_cycle(sc["cycle"]["id"], PEOPLE_ANALYST), 200)

    set_clock("2026-09-08T00:00:04Z")
    resp = api.remind_cycle(sc["cycle"]["id"], PEOPLE_ANALYST)
    data = validate_success(resp, 200)
    assert data["reminded_count"] == 0, (
        "fourth sweep: invite is cap-blocked at reminder_count == 3 and skipped, not an error"
    )

    events, meta = validate_paginated(api.list_invite_reminders(invite_id, PEOPLE_ANALYST))
    assert meta["total_count"] == 3
    assert len(events) == 3, "exactly three reminder events were appended"
    for event in events:
        assert_reminder_event(event)
    sequence = [e["sequence_no"] for e in events]
    assert sequence == [1, 2, 3], "events carry the next 1-based sequence_no per send"
    invite = get_invite(invite_id)
    assert invite["reminder_count"] == 3, "cap-blocked sweep adds nothing"


def test_first_reminder_one_second_before_24h_is_skipped(api):
    """PRD §3.4: "An invitation in `INVITED` status becomes `REMINDED` when all
    of the following hold: the cycle is `OPEN`; the invitation's
    `reminder_count` is below the cap of three; and either the invitation has
    never been reminded and at least twenty-four hours have elapsed since the
    cycle opened, or at least forty-eight hours have elapsed since
    `last_reminded_at`."

    Design: Difficulty/boundary_precision_check/reminder_first_window_exactly_24h
    """
    sc = _open_one_invite_cycle(api, "CadenceEarly", "mgr-ke")
    set_clock("2026-09-01T23:59:59Z")
    resp = api.remind_cycle(sc["cycle"]["id"], PEOPLE_ANALYST)
    data = validate_success(resp, 200)
    assert data["reminded_count"] == 0, (
        "one second before opens_at + 24h the invite is not yet eligible"
    )
    invite = get_invite(sc["invites"][0]["id"])
    assert invite["status"] == "INVITED"
    assert invite["reminder_count"] == 0


def test_first_reminder_at_exactly_24h_fires(api):
    """PRD §3.4: "An invitation in `INVITED` status becomes `REMINDED` when all
    of the following hold: the cycle is `OPEN`; the invitation's
    `reminder_count` is below the cap of three; and either the invitation has
    never been reminded and at least twenty-four hours have elapsed since the
    cycle opened, or at least forty-eight hours have elapsed since
    `last_reminded_at`."

    Design: Difficulty/boundary_precision_check/reminder_first_window_exactly_24h
    """
    sc = _open_one_invite_cycle(api, "CadenceExact", "mgr-kx")
    set_clock("2026-09-02T00:00:00Z")
    resp = api.remind_cycle(sc["cycle"]["id"], PEOPLE_ANALYST)
    data = validate_success(resp, 200)
    assert data["reminded_count"] == 1, (
        "at exactly opens_at + 24h the boundary is inclusive: eligible"
    )
    invite = get_invite(sc["invites"][0]["id"])
    assert invite["status"] == "REMINDED"
    assert invite["reminder_count"] == 1
