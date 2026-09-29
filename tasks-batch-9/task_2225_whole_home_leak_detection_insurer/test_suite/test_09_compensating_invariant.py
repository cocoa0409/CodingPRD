"""Two ledgers that must reconcile after every compensating move.

The valve keeps a parity ledger: close_count less reopen_count is 1 while closed
and 0 while open, and both counters only ever climb.  The policy keeps a monetary
ledger: a clawback is booked as its own entry rather than by rewriting the awarded
attestation it reverses.
"""

import pytest

from test_helpers import (
    ApiClient,
    assert_credit_ledger_identity,
    assert_valve_ledger_monotonic,
)
from test_helpers.fixtures import (
    close_valve,
    ingest_burst_reading,
    label_drip_false_positive,
    read_attestation_list,
    read_device,
    read_events,
    read_irrigation_windows,
    read_live_baseline,
    read_policy,
    reopen_valve,
    set_clock,
    setup_finalized_credit_period,
    setup_irrigation_window,
)

BURST_AT = "2026-08-01T07:00:00Z"
WINDOW = ("2026-08-05T09:00:00Z", "2026-08-05T11:00:00Z")


def _auto_closed_valve_with_a_suspended_window(api: ApiClient) -> dict:
    """A burst shutoff that suspended the property's one irrigation window."""
    state = setup_irrigation_window(
        api, *WINDOW, expected_max_flow_gpm=9.0, label="Wednesday zone"
    )
    set_clock(api, BURST_AT)
    ingest_burst_reading(api, state["device_id"], BURST_AT)
    events = read_events(api, state["device_id"], event_state="ALERTED")
    assert len(events) == 1
    state["event_id"] = events[0]["id"]
    return state


def _only_window(api: ApiClient, state: dict) -> dict:
    windows = read_irrigation_windows(
        api, state["property_id"], state["homeowner_headers"]
    )
    assert len(windows) == 1
    return windows[0]


class TestValveCloseReopenParity:
    def test_the_shutoff_leaves_the_ledger_at_one_and_the_window_suspended(
        self, api: ApiClient
    ):
        """The starting position both later cycles must return to.

        "When no gate applies, the closure executes as a single atomic cascade: the
        device's `valve_state` moves `OPEN → CLOSED`, `close_count` increases by 1,
        `last_shutoff_at` is stamped with the clock, and the device's `version`
        increases by 1."
        "And every irrigation window belonging to the device's property whose
        `status` is `ACTIVE` moves to `SUSPENDED_BY_SHUTOFF` with `suspended_at`
        stamped at the clock; there is no point excusing sprinkler flow on a line
        that has no water in it."

        Design: Difficulty/compensating_invariant/valve_close_reopen_count_parity
        """
        state = _auto_closed_valve_with_a_suspended_window(api)

        device = read_device(api, state["device_id"])
        assert device["valve_state"] == "CLOSED"
        assert device["close_count"] == 1
        assert device["reopen_count"] == 0
        assert device["close_count"] - device["reopen_count"] == 1

        window = _only_window(api, state)
        assert window["status"] == "SUSPENDED_BY_SHUTOFF"
        assert window["suspended_at"].startswith("2026-08-01T07:00:00")

    def test_the_first_reopen_balances_by_incrementing_and_fully_compensates(
        self, api: ApiClient
    ):
        """Status and suspended_at both come back; a half-compensation fails.

        "When the reopen is accepted, `reopen_count` increases by 1 — restoring the
        parity invariant that `close_count` minus `reopen_count` equals 1 while the
        valve is `CLOSED` and 0 while it is `OPEN` — every irrigation window on the
        property whose `status` is `SUSPENDED_BY_SHUTOFF` returns to `ACTIVE` with
        `suspended_at` cleared back to null, and the device's `version` increases by
        1."
        "Because a device carries three independent posture dimensions rather than
        one status, a newly registered row lands in `lifecycle_state` `REGISTERED`,
        `valve_state` `OPEN`, and `monitor_mode` `NORMAL` simultaneously, with
        `close_count` and `reopen_count` both at 0 and `monitor_mode_updated_at`
        equal to `created_at`."

        Design: Difficulty/compensating_invariant/valve_close_reopen_count_parity
        """
        state = _auto_closed_valve_with_a_suspended_window(api)
        before = read_device(api, state["device_id"])

        reopened = reopen_valve(api, state["device_id"], state["homeowner_id"])
        assert reopened["valve_state"] == "OPEN"
        assert reopened["close_count"] == 1
        assert reopened["reopen_count"] == 1
        assert reopened["close_count"] - reopened["reopen_count"] == 0
        assert_valve_ledger_monotonic(before, reopened)

        window = _only_window(api, state)
        assert window["status"] == "ACTIVE"
        assert window["suspended_at"] is None

    def test_two_full_cycles_leave_the_ledger_and_the_window_with_no_drift(
        self, api: ApiClient
    ):
        """(1,0) then (1,1) then (2,1) then (2,2), never rewriting a counter.

        "A manual `CLOSE` behaves like the automatic one on the parts that matter:
        `close_count` increases by 1, `last_shutoff_at` is stamped, every `ACTIVE`
        irrigation window on the property moves to `SUSPENDED_BY_SHUTOFF`, and the
        device's `version` increases by 1."
        "When the reopen is accepted, `reopen_count` increases by 1 — restoring the
        parity invariant that `close_count` minus `reopen_count` equals 1 while the
        valve is `CLOSED` and 0 while it is `OPEN` — every irrigation window on the
        property whose `status` is `SUSPENDED_BY_SHUTOFF` returns to `ACTIVE` with
        `suspended_at` cleared back to null, and the device's `version` increases by
        1."
        "Every anomaly event on the device still sitting in `ALERTED` or `ESCALATED`
        has its `override_reopen_at` stamped at the clock, which both clears that
        event's `mitigation_credited` and starts the two-hour auto-shutoff immunity
        described above."

        Design: Difficulty/compensating_invariant/valve_close_reopen_count_parity
        """
        state = _auto_closed_valve_with_a_suspended_window(api)
        observed = [read_device(api, state["device_id"])]

        observed.append(reopen_valve(api, state["device_id"], state["homeowner_id"]))
        observed.append(close_valve(api, state["device_id"], state["homeowner_id"]))
        assert observed[-1]["valve_state"] == "CLOSED"
        assert observed[-1]["close_count"] == 2
        assert observed[-1]["reopen_count"] == 1
        resuspended = _only_window(api, state)
        assert resuspended["status"] == "SUSPENDED_BY_SHUTOFF"
        assert resuspended["suspended_at"].startswith("2026-08-01T07:00:00")

        observed.append(reopen_valve(api, state["device_id"], state["homeowner_id"]))
        final = observed[-1]
        assert final["valve_state"] == "OPEN"
        assert final["close_count"] == 2
        assert final["reopen_count"] == 2
        assert final["close_count"] - final["reopen_count"] == 0

        window = _only_window(api, state)
        assert window["status"] == "ACTIVE"
        assert window["suspended_at"] is None

        pairs = [(row["close_count"], row["reopen_count"]) for row in observed]
        assert pairs == [(1, 0), (1, 1), (2, 1), (2, 2)]
        for earlier, later in zip(observed, observed[1:]):
            assert_valve_ledger_monotonic(earlier, later)

        # The shutoff stamp and the override are each recorded exactly once.
        assert final["last_shutoff_at"].startswith("2026-08-01T07:00:00")
        event = read_events(api, state["device_id"])[0]
        assert event["override_reopen_at"].startswith("2026-08-01T07:00:00")
        assert event["mitigation_credited"] is False


DRIP_TIMES = (
    "2026-08-02T07:00:00Z",
    "2026-08-02T08:10:00Z",
    "2026-08-02T09:20:00Z",
)


def _awarded_period_then_two_false_positives(api: ApiClient) -> dict:
    """3748 cents booked and the tuning ladder one step short of a relearn."""
    state = setup_finalized_credit_period(api)
    for stamp in DRIP_TIMES[:2]:
        label_drip_false_positive(
            api, state["device_id"], state["homeowner_id"], stamp
        )
    return state


class TestCreditLedgerClawbackReconciliation:
    def test_the_ledger_stands_at_3748_with_no_clawback_before_the_relearn(
        self, api: ApiClient
    ):
        """The baseline the single trigger call must move by exactly minus 3748.

        "The **provisional period accrual** runs on every finalize:
        `credit_cents_awarded` is the policy's `annual_premium_cents` multiplied by
        `tier_pct`, divided by the two attestation periods that make up a policy
        year, and rounded half up to a whole cent."
        "Fourth and last, when the recomputed `false_positive_count` reaches **three
        or more**, the platform stops tuning and demands a fresh start."

        Design: Difficulty/compensating_invariant/credit_ledger_clawback_reconciliation
        """
        state = _awarded_period_then_two_false_positives(api)

        policy = read_policy(api, state["policy_id"])
        assert policy["credit_state"] == "CREDIT_ACTIVE"
        assert policy["credited_cents_total"] == 3748
        assert policy["clawback_cents_total"] == 0
        assert policy["current_credit_tier_pct"] == pytest.approx(0.05, abs=0.01)

        profile = read_live_baseline(api, state["device_id"])
        assert profile["false_positive_count"] == 2
        assert profile["learning_state"] == "COMPLETE"
        assert profile["drip_threshold_gpm"] == pytest.approx(0.17, abs=0.01)

        device = read_device(api, state["device_id"])
        assert device["lifecycle_state"] == "ARMED"

    def test_the_third_feedback_books_a_compensating_clawback_of_3748(
        self, api: ApiClient
    ):
        """One call tunes, invalidates, demotes and reverses the credit.

        "Third, the live baseline is widened: `drip_threshold_gpm` becomes the
        smaller of an absolute ceiling of 0.50 gallons per minute and the current
        threshold increased by twenty percent, rounded half up to two decimal
        places; `last_false_positive_at` is stamped at the clock; and
        `baseline_version` increments by 1."
        "That amount is added to `clawback_cents_total` and subtracted from
        `credited_cents_total`, `current_credit_tier_pct` is reset to 0, and the
        policy's `version` increments by 1."

        Design: Difficulty/compensating_invariant/credit_ledger_clawback_reconciliation
        """
        state = _awarded_period_then_two_false_positives(api)
        label_drip_false_positive(
            api, state["device_id"], state["homeowner_id"], DRIP_TIMES[2]
        )

        profile = read_live_baseline(api, state["device_id"])
        assert profile["false_positive_count"] == 3
        assert profile["learning_state"] == "INVALIDATED"
        assert profile["invalidated_reason"] == "FALSE_POSITIVE_THRESHOLD"
        assert profile["completed_at"] is None
        # The widening still ran before the relearn check fired.
        assert profile["drip_threshold_gpm"] == pytest.approx(0.20, abs=0.01)
        assert profile["last_false_positive_at"].startswith("2026-08-02T09:20:00")

        device = read_device(api, state["device_id"])
        assert device["lifecycle_state"] == "LEARNING"
        assert device["baseline_ready"] is False

        policy = read_policy(api, state["policy_id"])
        assert policy["credit_state"] == "CREDIT_SUSPENDED"
        assert policy["suspended_reason"] == "DEVICE_NOT_ARMED"
        assert policy["clawback_cents_total"] == 3748
        assert policy["credited_cents_total"] == 0
        assert policy["current_credit_tier_pct"] == pytest.approx(0.00, abs=0.01)

    def test_the_clawback_reconciles_against_an_untouched_award_history(
        self, api: ApiClient
    ):
        """Awards less clawbacks equals the net credit, with no residual cent.

        "The attestation rows themselves are never rewritten: `credited_cents_total`
        is defined as the sum of `credit_cents_awarded` across awarded periods, plus
        the `true_up_cents` of any policy-year-closing period, minus
        `clawback_cents_total`."
        "Two policy figures are derived rather than accumulated and are recomputed
        at this point: `finalized_period_count` is the number of the policy's
        attestations whose `status` is either `FINALIZED_AWARDED` or
        `FINALIZED_DENIED`, and `avg_uptime_pct` is the arithmetic mean of
        `uptime_pct` across those same rows, rounded half up to two decimal places,
        or null when the policy has no finalized period yet."

        Design: Difficulty/compensating_invariant/credit_ledger_clawback_reconciliation
        """
        state = _awarded_period_then_two_false_positives(api)
        label_drip_false_positive(
            api, state["device_id"], state["homeowner_id"], DRIP_TIMES[2]
        )

        rows = read_attestation_list(api, state["policy_id"])
        assert len(rows) == 1
        awarded = rows[0]
        assert awarded["id"] == state["attestation_id"]
        assert awarded["status"] == "FINALIZED_AWARDED"
        assert awarded["credit_cents_awarded"] == 3748
        assert awarded["true_up_cents"] == 0
        assert awarded["uptime_pct"] == pytest.approx(95.00, abs=0.01)
        assert awarded["tier_pct"] == pytest.approx(0.05, abs=0.01)

        policy = read_policy(api, state["policy_id"])
        awarded_total = sum(
            row["credit_cents_awarded"] + row["true_up_cents"]
            for row in rows
            if row["status"] == "FINALIZED_AWARDED"
        )
        assert awarded_total == 3748
        assert_credit_ledger_identity(policy, awarded_total)

        # The derived policy fields still read from the untouched row.
        assert policy["finalized_period_count"] == 1
        assert policy["avg_uptime_pct"] == pytest.approx(95.00, abs=0.01)
