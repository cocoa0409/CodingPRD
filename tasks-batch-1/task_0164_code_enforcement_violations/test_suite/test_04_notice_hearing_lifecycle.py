"""The non-linear notice/hearing lifecycle: the ISSUED->CONTESTED->UPHELD rejoin,
the SCHEDULED->CONTINUED->SCHEDULED continuance cycle, terminal-state lockdown, and
the hearing ripeness / continuance-limit / contest-window preconditions.

PRD coverage: §3.8 (contest window, hearing buffer, ripeness, continuance cap,
reschedule) and §3.9 (the upheld/dismissed effects).
"""
from test_helpers import validate_success, validate_error, ApiErrorId
from test_helpers import fixtures as F
from test_helpers.test_users import make_registrant_headers


OFFICER = F.OFFICER
HEARING = F.HEARING


# ==========================================================================
# Difficulty: non_linear_state_machine / notice_contest_cycle_issued_contested_upheld
# ==========================================================================
def test_contesting_an_issued_notice_moves_it_to_contested(api):
    """PRD §3.8: "A valid contest pauses accrual — `fine_total_cents` is frozen at
    its provisional value as of the contest filing instant — and creates a `Hearing`
    in `SCHEDULED` status, recording the contesting registrant's `Owner.id` as
    `requested_by_user_id`."
    PRD §3.8: "Acting as a `Registrant`, the owner contests a notice by supplying
    the `scheduled_for` instant at which they want the hearing set."

    Design: Difficulty/non_linear_state_machine/notice_contest_cycle_issued_contested_upheld
    """
    ctx = F.setup_issued_notice("MAJOR", clock="2026-01-01T00:00:00Z")
    hearing = F.contest_notice(
        ctx["notice"]["id"], ctx["owner"]["id"], "2026-01-10T00:00:00Z"
    )
    assert hearing["status"] == "SCHEDULED", f"hearing should be SCHEDULED, got {hearing['status']}"
    notice = validate_success(api.get_notice(ctx["notice"]["id"], OFFICER))
    assert notice["status"] == "CONTESTED", f"notice should be CONTESTED, got {notice['status']}"


def test_upheld_hearing_drives_notice_contested_to_upheld(api):
    """PRD §3.8: "An `UPHELD` decision moves the hearing to `HELD_UPHELD` and drives
    the parent notice from `CONTESTED` to `UPHELD`."
    PRD §3.8: "A hearing may be decided only once the current clock is at or after
    its `scheduled_for`"

    Design: Difficulty/non_linear_state_machine/notice_contest_cycle_issued_contested_upheld
    """
    ctx = F.setup_contested_notice(
        issue_clock="2026-01-01T00:00:00Z", scheduled_for="2026-01-10T00:00:00Z"
    )
    F.set_clock("2026-01-10T00:00:00Z")
    hearing = F.decide_hearing(ctx["hearing"]["id"], "UPHELD")
    assert hearing["status"] == "HELD_UPHELD", (
        f"hearing should be HELD_UPHELD, got {hearing['status']}"
    )
    notice = validate_success(api.get_notice(ctx["notice"]["id"], OFFICER))
    assert notice["status"] == "UPHELD", f"notice should be UPHELD, got {notice['status']}"


# ==========================================================================
# Difficulty: non_linear_state_machine / hearing_continuance_cycle_scheduled_continued_scheduled
# ==========================================================================
def test_continue_increments_count_and_moves_to_continued(api):
    """PRD §3.8: "Continuing moves the hearing to `CONTINUED` and increments
    `continuance_count` by one, but only while `continuance_count` is below the cap
    of two continuances"

    Design: Difficulty/non_linear_state_machine/hearing_continuance_cycle_scheduled_continued_scheduled
    """
    ctx = F.setup_contested_notice(
        issue_clock="2026-01-01T00:00:00Z", scheduled_for="2026-01-10T00:00:00Z"
    )
    cont = validate_success(api.continue_hearing(ctx["hearing"]["id"], HEARING))
    assert cont["status"] == "CONTINUED", f"expected CONTINUED, got {cont['status']}"
    assert cont["continuance_count"] == 1, (
        f"expected continuance_count 1, got {cont['continuance_count']}"
    )


def test_reschedule_cycles_continued_back_to_scheduled(api):
    """PRD §3.8: "From `CONTINUED`, the officer reschedules to put the hearing back
    to `SCHEDULED` with a new `scheduled_for`, which must be at or after the current
    clock or the reschedule is rejected with `ERR_HEARING_NOT_RIPE`."

    Design: Difficulty/non_linear_state_machine/hearing_continuance_cycle_scheduled_continued_scheduled
    """
    ctx = F.setup_contested_notice(
        issue_clock="2026-01-01T00:00:00Z", scheduled_for="2026-01-10T00:00:00Z"
    )
    validate_success(api.continue_hearing(ctx["hearing"]["id"], HEARING))
    payload = {"scheduled_for": "2026-01-20T00:00:00Z"}
    resch = validate_success(api.reschedule_hearing(ctx["hearing"]["id"], payload, HEARING))
    assert resch["status"] == "SCHEDULED", f"expected SCHEDULED, got {resch['status']}"
    assert resch["scheduled_for"] == "2026-01-20T00:00:00Z" or resch["scheduled_for"].startswith(
        "2026-01-20"
    ), f"expected scheduled_for 2026-01-20, got {resch['scheduled_for']}"


# ==========================================================================
# Corner: state_machines / complied_notice_is_terminal_contest_rejected
# ==========================================================================
def test_contesting_a_complied_notice_is_rejected_as_invalid_state(api):
    """PRD §3.6: "a notice that is cured within its window goes from `ISSUED` to
    `COMPLIED` when a re-inspection passes while the current clock is at or before
    the `compliance_deadline`"
    PRD §2.9: "State-machine legality is then checked: a transition requested from a
    state where it is not defined yields `ERR_INVALID_STATE`."

    Design: Corner/state_machines/complied_notice_is_terminal_contest_rejected
    """
    ctx = F.setup_issued_notice("MAJOR", clock="2026-01-01T00:00:00Z")
    # Cure within the window (clock still 2026-01-01, before the 2026-01-15 deadline).
    F.cure_notice_to_complied(ctx["notice"]["id"])
    complied = validate_success(api.get_notice(ctx["notice"]["id"], OFFICER))
    assert complied["status"] == "COMPLIED", f"setup expected COMPLIED, got {complied['status']}"

    headers = make_registrant_headers(ctx["owner"]["id"])
    resp = api.contest_notice(
        ctx["notice"]["id"], {"scheduled_for": "2026-01-10T00:00:00Z"}, headers
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ==========================================================================
# Corner: state_machines / hearing_decided_before_scheduled_for_returns_not_ripe
# ==========================================================================
def test_deciding_hearing_before_scheduled_for_is_not_ripe(api):
    """PRD §3.8: "A hearing may be decided only once the current clock is at or
    after its `scheduled_for`; deciding early is rejected with
    `ERR_HEARING_NOT_RIPE`."

    Design: Corner/state_machines/hearing_decided_before_scheduled_for_returns_not_ripe
    """
    ctx = F.setup_contested_notice(
        issue_clock="2026-01-01T00:00:00Z", scheduled_for="2026-01-10T00:00:00Z"
    )
    F.set_clock("2026-01-05T00:00:00Z")  # still before 2026-01-10
    resp = api.decide_hearing(ctx["hearing"]["id"], {"decision": "UPHELD"}, HEARING)
    validate_error(resp, ApiErrorId.ERR_HEARING_NOT_RIPE.value)


# ==========================================================================
# Corner: state_machines / third_continuance_exceeds_limit
# ==========================================================================
def test_third_continuance_exceeds_limit(api):
    """PRD §3.8: "Continuing moves the hearing to `CONTINUED` and increments
    `continuance_count` by one, but only while `continuance_count` is below the cap
    of two continuances; a third attempt is rejected with `ERR_CONTINUANCE_LIMIT`."

    Design: Corner/state_machines/third_continuance_exceeds_limit
    """
    ctx = F.setup_contested_notice(
        issue_clock="2026-01-01T00:00:00Z", scheduled_for="2026-01-10T00:00:00Z"
    )
    hid = ctx["hearing"]["id"]
    # Continue twice (count -> 2), rescheduling back to SCHEDULED each time.
    validate_success(api.continue_hearing(hid, HEARING))
    validate_success(api.reschedule_hearing(hid, {"scheduled_for": "2026-01-12T00:00:00Z"}, HEARING))
    validate_success(api.continue_hearing(hid, HEARING))
    validate_success(api.reschedule_hearing(hid, {"scheduled_for": "2026-01-14T00:00:00Z"}, HEARING))
    # Third continuance attempt.
    resp = api.continue_hearing(hid, HEARING)
    validate_error(resp, ApiErrorId.ERR_CONTINUANCE_LIMIT.value)


# ==========================================================================
# Corner: state_machines / contest_after_window_closed_returns_error
# ==========================================================================
def test_contest_after_grace_window_closed_is_rejected(api):
    """PRD §3.8: "From `OVERDUE`, the window is extended by a three-day grace
    period, so the contest must be filed while the current clock is at or before the
    `compliance_deadline` plus three days. A contest filed past the applicable
    window is rejected with `ERR_CONTEST_WINDOW_CLOSED`."

    Design: Corner/state_machines/contest_after_window_closed_returns_error
    """
    ctx = F.setup_issued_notice("MAJOR", clock="2026-01-01T00:00:00Z")
    # Deadline 2026-01-15; grace +3 = 2026-01-18. Clock at 2026-01-20 is past both.
    F.set_clock("2026-01-20T00:00:00Z")
    headers = make_registrant_headers(ctx["owner"]["id"])
    resp = api.contest_notice(
        ctx["notice"]["id"], {"scheduled_for": "2026-01-25T00:00:00Z"}, headers
    )
    validate_error(resp, ApiErrorId.ERR_CONTEST_WINDOW_CLOSED.value)
