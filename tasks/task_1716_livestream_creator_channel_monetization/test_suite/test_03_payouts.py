"""Payout opening gates, settlement lifecycle, retries, and hold cascades."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_payout,
    create_channel,
    create_moderator,
    create_verified_channel,
    get_channel,
    get_success_data,
    ingest_revenue_event,
    issue_strike,
    make_creator_headers,
    make_moderator_headers,
    open_payout,
    run_ops,
    set_clock,
    setup_channel_with_cleared_events,
    setup_channel_with_open_payout,
    submit_tax_form,
    transition_payout_admin,
    transition_payout_owner,
    validate_error,
    validate_paginated,
    validate_success,
    verify_tax_form,
)

ADMIN = TEST_USERS["platform_admin_headers"]


class TestPayoutTerminalLockdown:
    def test_payout_paid_terminal_lockdown(self, api):
        """PRD §3.3: "From `SCHEDULED`, a `PlatformAdmin` drives settlement:
        processing moves the payout to `PROCESSING`, a successful settle moves
        it to `PAID` — adding `net_transfer_cents` to the channel's
        `lifetime_paid_cents` — and a failed settle requires a
        `failure_reason`, records it, and moves the payout to `FAILED`.
        `PAID` is terminal."
        PRD §2.9: "**State admissibility.** The target entity must be in a
        state that admits the requested transition — wrong-from-state,
        terminal lockdown, and duplicate or repeat triggers all fail here with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/payout_paid_terminal_lockdown
        """
        channel, payout = setup_channel_with_open_payout("sm_lock")
        transition_payout_admin(payout["id"], "PROCESS")
        paid = transition_payout_admin(payout["id"], "SETTLE_SUCCESS")
        assert paid["payout_status"] == "PAID"
        assert paid["net_transfer_cents"] == 99_500, "100000 - 500 fee"

        resp = api.transition_payout(payout["id"], {"action": "CANCEL"},
                                     make_creator_headers(channel["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = get_success_data(api.list_payouts(
            channel["id"], make_creator_headers(channel["id"])))
        current = [p for p in after if p["id"] == payout["id"]][0]
        assert current["payout_status"] == "PAID"
        channel_after = get_channel(channel["id"])
        assert channel_after["balance_payable_cents"] == 0, (
            "no compensating restore on a PAID payout")
        assert channel_after["lifetime_paid_cents"] == 99_500


class TestPayoutRetryCycle:
    def _failed_payout(self, handle):
        """Open -> PROCESS -> SETTLE_FAILURE. Returns (channel, payout)."""
        channel, payout = setup_channel_with_open_payout(handle)
        transition_payout_admin(payout["id"], "PROCESS")
        failed = transition_payout_admin(payout["id"], "SETTLE_FAILURE",
                                         failure_reason="bank_reject")
        assert failed["payout_status"] == "FAILED"
        return channel, failed

    def test_payout_retry_returns_to_scheduled_once(self, api):
        """PRD §3.3: "Failure is recoverable by the owner through a retry,
        which returns the payout from `FAILED` to `SCHEDULED`."
        PRD §3.3: "A successful retry increments `retry_count` by 1 and clears
        `failure_reason`."

        Design: Difficulty/non_linear_state_machine/payout_retry_cycle
        """
        channel, failed = self._failed_payout("nl_pay")
        retried = transition_payout_owner(failed["id"], channel["id"], "RETRY")
        assert retried["payout_status"] == "SCHEDULED", (
            "the FAILED -> SCHEDULED cycle edge is traversed")
        assert retried["retry_count"] == 1
        assert retried["failure_reason"] is None, "retry clears failure_reason"

    def test_payout_retry_cycle_second_loop(self, api):
        """PRD §3.3: "Failure is recoverable by the owner through a retry,
        which returns the payout from `FAILED` to `SCHEDULED`."
        PRD §3.3: "From `SCHEDULED`, a `PlatformAdmin` drives settlement:
        processing moves the payout to `PROCESSING`, a successful settle moves
        it to `PAID` — adding `net_transfer_cents` to the channel's
        `lifetime_paid_cents` — and a failed settle requires a
        `failure_reason`, records it, and moves the payout to `FAILED`."

        Design: Difficulty/non_linear_state_machine/payout_retry_cycle
        """
        channel, failed = self._failed_payout("nl_pay2")
        first = transition_payout_owner(failed["id"], channel["id"], "RETRY")
        assert first["retry_count"] == 1

        transition_payout_admin(failed["id"], "PROCESS")
        failed_again = transition_payout_admin(failed["id"], "SETTLE_FAILURE",
                                               failure_reason="bank_reject_2")
        assert failed_again["payout_status"] == "FAILED", (
            "the cycle re-enters PROCESSING and fails again")

        second = transition_payout_owner(failed["id"], channel["id"], "RETRY")
        assert second["payout_status"] == "SCHEDULED"
        assert second["retry_count"] == 2


class TestPayoutRetryLimit:
    def test_payout_retry_limit_reached(self, api):
        """PRD §3.3: "The retry cap is a state-level gate evaluated before the
        fiscal gates of §2.9: when `retry_count` has already reached 3, the
        retry is rejected with `ERR_RETRY_LIMIT_REACHED`."

        Design: Corner/errors/payout_retry_limit_reached
        """
        channel, payout = setup_channel_with_open_payout("err_rl")
        for round_no in (1, 2, 3):
            transition_payout_admin(payout["id"], "PROCESS")
            transition_payout_admin(payout["id"], "SETTLE_FAILURE",
                                    failure_reason=f"f{round_no}")
            retried = transition_payout_owner(payout["id"], channel["id"], "RETRY")
            assert retried["retry_count"] == round_no
        transition_payout_admin(payout["id"], "PROCESS")
        transition_payout_admin(payout["id"], "SETTLE_FAILURE",
                                failure_reason="f4")

        resp = api.transition_payout(payout["id"], {"action": "RETRY"},
                                     make_creator_headers(channel["id"]))
        validate_error(resp, ApiErrorId.ERR_RETRY_LIMIT_REACHED)

        current = [p for p in get_success_data(api.list_payouts(
            channel["id"], make_creator_headers(channel["id"])))
            if p["id"] == payout["id"]][0]
        assert current["payout_status"] == "FAILED"
        assert current["retry_count"] == 3


class TestPayoutRetryWrongStateBeatsTaxGate:
    def _cancelled_payout_with_unverified_form(self, handle):
        """Payout opened then CANCELLED; afterwards a new tax form is
        submitted (supersession), so the current form is SUBMITTED — the
        fiscal gate is armed while the state gate must fire first."""
        channel, payout = setup_channel_with_open_payout(handle)
        cancelled = transition_payout_owner(payout["id"], channel["id"], "CANCEL")
        assert cancelled["payout_status"] == "CANCELLED"
        channel_now = get_channel(channel["id"])
        new_form = submit_tax_form(channel_now, legal_name="PP Retry LLC v2",
                                   tax_id_last4="1213")
        return channel_now, payout, new_form

    def test_retry_on_cancelled_payout_reports_invalid_state(self, api):
        """PRD §2.9: "When several checks could reject the same request, they
        are evaluated in the following fixed priority order, so the error a
        caller sees is deterministic:"
        PRD §2.9: "**State admissibility.** The target entity must be in a
        state that admits the requested transition — wrong-from-state,
        terminal lockdown, and duplicate or repeat triggers all fail here with
        `ERR_INVALID_STATE`." (priority 6)
        PRD §2.9: "**Tax gate.** Opening or retrying a payout while the
        channel's current tax form is missing or not `VERIFIED` is rejected
        with `ERR_TAX_FORM_NOT_VERIFIED` (HTTP 402)." (priority 24)

        Design: Difficulty/priority_pair_validation_conflict/payout_retry_wrong_state_beats_threshold
        """
        channel, payout, _form = self._cancelled_payout_with_unverified_form(
            "pp_retry")
        resp = api.transition_payout(payout["id"], {"action": "RETRY"},
                                     make_creator_headers(channel["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_retry_wrong_state_leaves_payout_untouched(self, api):
        """PRD §2.9: "**State admissibility.** The target entity must be in a
        state that admits the requested transition — wrong-from-state,
        terminal lockdown, and duplicate or repeat triggers all fail here with
        `ERR_INVALID_STATE`." (priority 6, ahead of the priority-24 tax gate)
        PRD §3.1: "Submission is **supersession**: the new form is born
        `SUBMITTED`, its `submitted_at` is stamped with the logical clock, the
        channel's `tax_form_current_id` swings to it, its `prior_form_id`
        chains back to the previously current form (null for a channel's first
        submission), the channel's `version` increments by 1, and posture is
        recomputed."

        Design: Difficulty/priority_pair_validation_conflict/payout_retry_wrong_state_beats_threshold
        """
        channel, payout, new_form = self._cancelled_payout_with_unverified_form(
            "pp_retry2")
        # The fiscal gate is armed: the current form is SUBMITTED, not VERIFIED.
        channel_armed = get_channel(channel["id"])
        assert channel_armed["tax_form_current_id"] == new_form["id"]
        assert get_success_data(
            api.get_tax_form(new_form["id"], ADMIN))["tax_status"] == "SUBMITTED"

        resp = api.transition_payout(payout["id"], {"action": "RETRY"},
                                     make_creator_headers(channel["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        current = [p for p in get_success_data(api.list_payouts(
            channel["id"], make_creator_headers(channel["id"])))
            if p["id"] == payout["id"]][0]
        assert current["payout_status"] == "CANCELLED"
        assert current["retry_count"] == 0


class TestPayoutOpenGates:
    def test_payout_open_no_eligible_revenue(self, api):
        """PRD §2.9: "**Non-empty sweep.** Opening a payout with no eligible
        `CLEARED` revenue event is rejected with `ERR_NO_ELIGIBLE_REVENUE`
        (HTTP 422); a zero-balance channel fails here, before the threshold
        check."

        Design: Corner/errors/payout_open_no_eligible_revenue
        """
        channel, _form = create_verified_channel("err_ne")
        resp = api.open_payout(channel["id"], make_creator_headers(channel["id"]))
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_REVENUE)

    def test_second_payout_open_blocked_in_flight(self, api):
        """PRD §2.9: "**Uniqueness.** Channel handles are unique across all
        channels — a duplicate is rejected with `ERR_INVALID_REQUEST`; at most
        one `ACTIVE` tier per `tier_code` exists per channel — a conflicting
        creation or reactivation is rejected with `ERR_TIER_CODE_IN_USE`; and
        at most one payout per channel is in flight in `SCHEDULED`,
        `PROCESSING`, `FAILED`, or `HELD` status — a conflicting open is
        rejected with `ERR_PAYOUT_IN_FLIGHT`."

        Design: Corner/validations/second_payout_open_blocked_in_flight
        """
        channel, first = setup_channel_with_open_payout("val_inf")
        assert first["payout_status"] == "SCHEDULED"

        resp = api.open_payout(channel["id"], make_creator_headers(channel["id"]))
        validate_error(resp, ApiErrorId.ERR_PAYOUT_IN_FLIGHT)

        _payouts, meta = validate_paginated(api.list_payouts(
            channel["id"], make_creator_headers(channel["id"])))
        assert meta["total_count"] == 1, "exactly one payout may exist"

    def test_payout_open_requires_verified_tax_form(self, api):
        """PRD §2.9: "**Tax gate.** Opening or retrying a payout while the
        channel's current tax form is missing or not `VERIFIED` is rejected
        with `ERR_TAX_FORM_NOT_VERIFIED` (HTTP 402)."

        Design: Difficulty/cross_entity_state_dependency/payout_open_requires_verified_tax_form
        """
        channel = create_channel(handle="ce_tax", home_platform="TWITCH")
        form = submit_tax_form(channel, legal_name="CE Tax LLC",
                               tax_id_last4="0004")
        # No VERIFY: the current form stays SUBMITTED.
        set_clock("2026-08-03T00:00:00Z")
        ingest_revenue_event(channel["id"], kind="TIP", gross_cents=100000,
                             platform_fee_bps=0,
                             occurred_at="2026-08-03T01:00:00Z")
        set_clock("2026-09-01T00:00:00Z")
        run_ops()

        resp = api.open_payout(channel["id"], make_creator_headers(channel["id"]))
        validate_error(resp, ApiErrorId.ERR_TAX_FORM_NOT_VERIFIED)

    def test_payout_open_succeeds_after_tax_verify(self, api):
        """PRD §2.9: "**Tax gate.** Opening or retrying a payout while the
        channel's current tax form is missing or not `VERIFIED` is rejected
        with `ERR_TAX_FORM_NOT_VERIFIED` (HTTP 402)."
        PRD §3.1: "Verification moves a `SUBMITTED` form to `VERIFIED`, stamps
        `verified_at`, computes `expires_on` as exactly 365 days after
        `verified_at`, recomputes the channel's posture, and — provided the
        posture is not `SUSPENDED` — releases each of the channel's payouts
        held with `hold_reason` `TAX_FORM` back to `SCHEDULED`, clearing their
        `hold_reason` to `NONE`."

        Design: Difficulty/cross_entity_state_dependency/payout_open_requires_verified_tax_form
        """
        channel = create_channel(handle="ce_tax2", home_platform="TWITCH")
        form = submit_tax_form(channel, legal_name="CE Tax LLC",
                               tax_id_last4="0004")
        set_clock("2026-08-03T00:00:00Z")
        ingest_revenue_event(channel["id"], kind="TIP", gross_cents=100000,
                             platform_fee_bps=0,
                             occurred_at="2026-08-03T01:00:00Z")
        set_clock("2026-09-01T00:00:00Z")
        run_ops()

        verify_tax_form(form["id"])
        payout = validate_success(
            api.open_payout(channel["id"], make_creator_headers(channel["id"])),
            201)
        assert_payout(payout)
        assert payout["payout_status"] == "SCHEDULED"
        assert payout["amount_cents"] == 100000


class TestPayoutThresholdBoundary:
    def _channel_with_payable(self, handle, home_platform, ad_share_gross):
        """Threshold 50000; cleared = 30000 (SUBSCRIPTION) + ad_share_gross."""
        return setup_channel_with_cleared_events(
            handle,
            [{"kind": "SUBSCRIPTION", "gross_cents": 50000,
              "platform_fee_bps": 4000, "occurred_at": "2026-08-05T00:00:00Z"},
             {"kind": "AD_SHARE", "gross_cents": ad_share_gross,
              "platform_fee_bps": 0, "occurred_at": "2026-08-05T01:00:00Z"}],
            payout_threshold_cents=50000,
            ingest_clock="2026-08-01T00:00:00Z")

    def test_payout_threshold_exact_boundary_eligible(self, api):
        """PRD §3.3: "The threshold comparison is inclusive — a balance
        exactly at the threshold is eligible."

        Design: Difficulty/boundary_precision_check/payout_threshold_exact_boundary
        """
        channel, _form, _events = self._channel_with_payable(
            "bp_a", "TWITCH", 20000)
        assert channel["balance_payable_cents"] == 50000

        payout = validate_success(
            api.open_payout(channel["id"], make_creator_headers(channel["id"])),
            201)
        assert payout["payout_status"] == "SCHEDULED"
        assert payout["amount_cents"] == 50000

    def test_payout_one_cent_below_threshold_rejected(self, api):
        """PRD §2.9: "**Threshold gate.** Opening a payout while
        `balance_payable_cents` is strictly below `payout_threshold_cents` is
        rejected with `ERR_BELOW_PAYOUT_THRESHOLD` (HTTP 422);
        exactly-at-threshold is eligible, because the boundary is inclusive."

        Design: Difficulty/boundary_precision_check/payout_threshold_exact_boundary
        """
        channel, _form, _events = self._channel_with_payable(
            "bp_b", "YOUTUBE", 19999)
        assert channel["balance_payable_cents"] == 49999

        resp = api.open_payout(channel["id"], make_creator_headers(channel["id"]))
        validate_error(resp, ApiErrorId.ERR_BELOW_PAYOUT_THRESHOLD)

        _payouts, meta = validate_paginated(api.list_payouts(
            channel["id"], make_creator_headers(channel["id"])))
        assert meta["total_count"] == 0, "no payout may be created"


class TestPayoutMoneyConservation:
    def test_payout_open_deducts_amount_from_payable(self, api):
        """PRD §2.6: "Two compensating pairs keep the invariant intact across
        the payout lifecycle — opening a payout deducts exactly `amount_cents`
        from the payable balance, and cancelling that payout restores exactly
        `amount_cents`, so an open followed by a cancel leaves the payable
        balance unchanged."
        PRD §3.3: "In the same response, the channel's
        `balance_payable_cents` drops by `amount_cents` — the swept money is
        now reserved."

        Design: Difficulty/compensating_invariant/payout_open_cancel_money_conservation
        """
        channel, _form, _events = setup_channel_with_cleared_events(
            "ci_pay",
            [{"kind": "TIP", "gross_cents": 100000, "platform_fee_bps": 0,
              "occurred_at": "2026-08-03T01:00:00Z"}])
        assert channel["balance_payable_cents"] == 100000

        payout = open_payout(channel["id"])
        assert payout["amount_cents"] == 100000
        assert payout["fee_cents"] == 500, (
            "snapshot 100000 >= 100000 selects 50bps")
        assert get_channel(channel["id"])["balance_payable_cents"] == 0, (
            "100000 moved into the in-flight payout; 0 + 100000 == 100000")

    def test_payout_cancel_restores_payable_exactly(self, api):
        """PRD §2.6: "Two compensating pairs keep the invariant intact across
        the payout lifecycle — opening a payout deducts exactly `amount_cents`
        from the payable balance, and cancelling that payout restores exactly
        `amount_cents`, so an open followed by a cancel leaves the payable
        balance unchanged."
        PRD §3.3: "Cancellation is the compensating half of the §2.6 pair: the
        channel's `balance_payable_cents` is restored by exactly
        `amount_cents`, leaving the ledger as if the payout had never been
        opened."

        Design: Difficulty/compensating_invariant/payout_open_cancel_money_conservation
        """
        channel, payout = setup_channel_with_open_payout("ci_pay2")
        assert get_channel(channel["id"])["balance_payable_cents"] == 0

        cancelled = transition_payout_owner(payout["id"], channel["id"], "CANCEL")
        assert cancelled["payout_status"] == "CANCELLED"
        assert get_channel(channel["id"])["balance_payable_cents"] == 100000, (
            "the compensating restore is exact — no drift")


class TestPayoutHoldCascadeOnSuspension:
    def test_severe_strike_suspends_channel(self, api):
        """PRD §2.7: "`SUSPENDED` applies whenever the active strike weight
        reaches three or more — the comparison is inclusive."
        PRD §2.7: "The canonical active strike weight is a hard-window sum:
        over the channel's strikes in `ISSUED`, `UNDER_APPEAL`, or `UPHELD`
        status whose `expires_at` is still in the future, add each strike's
        severity weight — one for `MINOR`, two for `MAJOR`, three for
        `SEVERE`."

        Design: Difficulty/transitive_cascade/strike_suspension_payout_hold_cascade
        """
        channel, _payout = setup_channel_with_open_payout("tc_hold")
        strike = issue_strike(channel["id"], policy_code="HATE_SPEECH",
                              severity="SEVERE", evidence_ref="clip://10")
        assert strike["strike_status"] == "ISSUED"
        channel_after = get_channel(channel["id"])
        assert channel_after["monetization_posture"] == "SUSPENDED", (
            "one SEVERE strike is weight 3, reaching the inclusive gate")

    def test_severe_strike_holds_scheduled_payout_with_posture_reason(self, api):
        """PRD §2.7: "When a channel leaves `STANDARD`, every payout of that
        channel currently `SCHEDULED` is moved to `HELD`: the drop to
        `RESTRICTED` stamps each held payout's `hold_reason` as `TAX_FORM` or
        `POSTURE` according to the cause, and the drop to `SUSPENDED` always
        stamps `POSTURE`."

        Design: Difficulty/transitive_cascade/strike_suspension_payout_hold_cascade
        """
        channel, payout = setup_channel_with_open_payout("tc_hold2")
        issue_strike(channel["id"], policy_code="HATE_SPEECH",
                     severity="SEVERE", evidence_ref="clip://10")

        payouts = get_success_data(api.list_payouts(
            channel["id"], make_creator_headers(channel["id"])))
        current = [p for p in payouts if p["id"] == payout["id"]][0]
        assert current["payout_status"] == "HELD"
        assert current["hold_reason"] == "POSTURE", (
            "the suspension cascade stamps POSTURE, cascading through the "
            "posture transition rather than from the strike directly")


class TestPayoutRbac:
    def test_moderator_cannot_process_payout_rejected(self, api):
        """PRD §2.1: "A caller whose role is not listed on the endpoint — or,
        on the transition-style endpoints, whose role is not permitted for the
        specific `action` requested — is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."
        PRD §4: the payout transition endpoint lists "Payout lifecycle:
        PROCESS, SETTLE_SUCCESS, SETTLE_FAILURE (PlatformAdmin); RETRY, CANCEL
        (Creator owner)".

        Design: Corner/rbac/moderator_cannot_process_payout_rejected
        """
        channel, payout = setup_channel_with_open_payout("rb_proc")
        moderator = create_moderator(channel["id"], moderator_handle="mod_x",
                                     scopes=["TIMEOUT", "BAN"])

        resp = api.transition_payout(payout["id"], {"action": "PROCESS"},
                                     make_moderator_headers(moderator["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

        current = [p for p in get_success_data(api.list_payouts(
            channel["id"], make_creator_headers(channel["id"])))
            if p["id"] == payout["id"]][0]
        assert current["payout_status"] == "SCHEDULED"
