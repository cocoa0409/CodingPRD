"""The two independent state dimensions of a note, the upward cure cascade from
the ledger to the statutory notice, and the closed re-notice blackout window.
"""

from test_helpers import (
    ApiErrorId,
    factories,
    fixtures,
    late_fee_cents,
    rule_of_78_rebate_cents,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import (
    ANALYST_NOTICE,
    ANALYST_ORIGIN,
    ANALYST_POA,
)


def _pay_installment_one(api, bundle):
    """Retire installment 1 with an exact 154761 tender on its due date."""
    fixtures.set_clock(api, "2026-10-01T00:00:00Z")
    return validate_success(
        api.create_payment(
            bundle["agreement_id"],
            factories.payment(154761, "2026-10-01"),
            ANALYST_ORIGIN,
        ),
        201,
    )


def _assess_the_fee(api, bundle):
    """Run the pass on 2026-11-12, one day past the grace boundary."""
    report = fixtures.advance_and_service(api, "2026-11-12T00:00:00Z")
    fees = fixtures.read_late_fees(api, bundle["agreement_id"])
    assert len(fees) == 1
    bundle["fee"] = fees[0]
    bundle["fee_id"] = fees[0]["id"]
    return report


def _issue_the_notice(api, bundle):
    """Issue the notice on 2026-11-13 under the notice handle."""
    fixtures.set_clock(api, "2026-11-13T00:00:00Z")
    notice = validate_success(
        api.issue_cancellation_notice(bundle["agreement_id"], ANALYST_NOTICE), 201
    )
    bundle["notice"] = notice
    bundle["notice_id"] = notice["id"]
    return notice


def _post_the_cure(api, bundle):
    """Tender 162499 — the 7738 fee plus the whole past-due installment 2."""
    return validate_success(
        api.create_payment(
            bundle["agreement_id"],
            factories.payment(162499, "2026-11-13"),
            ANALYST_ORIGIN,
        ),
        201,
    )


class TestParallelStatusAndDelinquencyDimensions:
    """One row carries two independent state machines, and the delinquency one has
    a backward edge."""

    def test_activation_sets_both_dimensions_and_the_first_payment_moves_neither(
        self, api
    ):
        """A note leaves activation ACTIVE and CURRENT, and an on-time payment
        leaves both dimensions alone.

        The PRD states: "Bucket two pays `PAST_DUE` installments, ordered by
        `due_date` ascending then `installment_number` ascending, and inside a
        single installment the `finance_charge_component_cents` is retired before
        the `principal_component_cents`".

        Design: Difficulty/non_linear_state_machine/agreement_parallel_status_and_delinquency_dimensions
        """
        bundle = fixtures.tx9_note(api, single_policy=False)

        assert bundle["activated"]["status"] == "ACTIVE"
        assert bundle["activated"]["delinquency_stage"] == "CURRENT"
        assert bundle["activated"]["amount_financed_cents"] == 1252000
        assert bundle["activated"]["finance_charge_cents"] == 140850

        posted = _pay_installment_one(api, bundle)

        assert posted["allocation_variant"] == "STANDARD"
        assert posted["applied_finance_charge_cents"] == 15650
        assert posted["applied_principal_cents"] == 139111
        after = fixtures.read_agreement(api, bundle["agreement_id"])
        assert after["status"] == "ACTIVE"
        assert after["delinquency_stage"] == "CURRENT"

    def test_the_servicing_pass_moves_only_the_delinquency_dimension(self, api):
        """A missed installment walks the delinquency stage while the financing
        status stands still.

        The PRD states: "An agreement that acquires a newly past-due installment
        while `CURRENT` advances `CURRENT` → `LATE` in the same pass."

        Design: Difficulty/non_linear_state_machine/agreement_parallel_status_and_delinquency_dimensions
        """
        bundle = fixtures.tx9_note(api, single_policy=False)
        _pay_installment_one(api, bundle)

        report = _assess_the_fee(api, bundle)

        assert report["past_due_marked"] == 1
        assert report["late_fees_assessed"] == 1
        assert report["agreements_advanced_to_late"] == 1
        assert bundle["fee"]["amount_cents"] == late_fee_cents(154761, 500, 500, 10000)
        assert bundle["fee"]["amount_cents"] == 7738

        d1 = fixtures.read_agreement(api, bundle["agreement_id"])
        assert d1["status"] == "ACTIVE", "the financing dimension did not move"
        assert d1["delinquency_stage"] == "LATE", "the delinquency dimension did"
        assert d1["late_fee_balance_cents"] == 7738

    def test_the_notice_produces_the_combined_active_and_noic_issued_state(self, api):
        """ACTIVE crossed with NOIC_ISSUED is a representable combination.

        The PRD states: "The note's `delinquency_stage` advances `LATE` →
        `NOIC_ISSUED` and its `version` advances."

        Design: Difficulty/non_linear_state_machine/agreement_parallel_status_and_delinquency_dimensions
        """
        bundle = fixtures.tx9_note(api, single_policy=False)
        _pay_installment_one(api, bundle)
        _assess_the_fee(api, bundle)

        notice = _issue_the_notice(api, bundle)

        assert notice["notice_days"] == 10, (
            "notice_days is snapshotted from the regime's noic_notice_days"
        )
        assert notice["effective_cancel_date"] == "2026-11-23", (
            "effective_cancel_date is issued_date advanced by notice_days "
            "calendar days"
        )
        assert notice["past_due_amount_cents"] == 162499, (
            "the snapshot is the past-due installment's 154761 unpaid balance "
            "plus the note's 7738 late fee balance"
        )
        d2 = fixtures.read_agreement(api, bundle["agreement_id"])
        assert d2["status"] == "ACTIVE"
        assert d2["delinquency_stage"] == "NOIC_ISSUED"

    def test_the_cure_walks_the_delinquency_dimension_backwards(self, api):
        """NOIC_ISSUED returns to CURRENT, which a forward-only machine cannot do.

        The PRD states: "If the allocation leaves no `PAST_DUE` installment and a
        `late_fee_balance_cents` of zero, the delinquency dimension is cured:
        `LATE` → `CURRENT`, or `NOIC_ISSUED` → `CURRENT`, and any notice of intent
        to cancel still in `ISSUED` moves to `CURED` with its `cured_date` set to
        the clock date".

        Design: Difficulty/non_linear_state_machine/agreement_parallel_status_and_delinquency_dimensions
        """
        bundle = fixtures.tx9_note(api, single_policy=False)
        _pay_installment_one(api, bundle)
        _assess_the_fee(api, bundle)
        _issue_the_notice(api, bundle)

        cure = _post_the_cure(api, bundle)

        assert cure["allocation_variant"] == "STANDARD"
        assert cure["applied_late_fee_cents"] == 7738, (
            "bucket one settles the outstanding fee before bucket two reaches the "
            "past-due installment"
        )
        d3 = fixtures.read_agreement(api, bundle["agreement_id"])
        assert d3["status"] == "ACTIVE", "the financing dimension still has not moved"
        assert d3["delinquency_stage"] == "CURRENT", "the backward edge fires"
        assert d3["principal_balance_cents"] == 973778
        assert d3["unpaid_finance_charge_cents"] == 109550
        notices = fixtures.read_notices(api, bundle["agreement_id"])
        assert notices[0]["status"] == "CURED"
        assert notices[0]["cured_date"] == "2026-11-13"

    def test_the_payoff_moves_only_the_financing_dimension(self, api):
        """Now the financing status advances while the delinquency stage stands
        still.

        The PRD states: "If the allocation drives `principal_balance_cents`,
        `unpaid_finance_charge_cents` and `late_fee_balance_cents` all to zero, the
        financing dimension completes: the note moves `ACTIVE` → `PAID_IN_FULL`,
        every installment still `SCHEDULED` or `PAST_DUE` moves to `PAID`, and
        `refund_due_cents` is set to the surviving `unapplied_credit_cents`".

        Design: Difficulty/non_linear_state_machine/agreement_parallel_status_and_delinquency_dimensions
        """
        bundle = fixtures.tx9_note(api, single_policy=False)
        _pay_installment_one(api, bundle)
        _assess_the_fee(api, bundle)
        _issue_the_notice(api, bundle)
        _post_the_cure(api, bundle)

        quote = validate_success(
            api.get_payoff_quote(
                bundle["agreement_id"], ANALYST_ORIGIN, {"as_of_date": "2026-11-13"}
            ),
            200,
        )
        assert quote["rebate_method"] == "RULE_OF_78"
        assert quote["unearned_finance_charge_rebate_cents"] == rule_of_78_rebate_cents(
            140850, 7, 9
        )
        assert quote["unearned_finance_charge_rebate_cents"] == 87640, (
            "seven of the nine installments are still unretired"
        )
        assert quote["net_payoff_cents"] == 995688

        payoff = validate_success(
            api.create_payment(
                bundle["agreement_id"],
                factories.payment(995688, "2026-11-13", method="CHECK"),
                ANALYST_ORIGIN,
            ),
            201,
        )
        assert payoff["allocation_variant"] == "PAYOFF", (
            "the payment runs as the PAYOFF variant when the tendered amount_cents "
            "is greater than or equal to the net payoff"
        )
        assert payoff["rebate_applied_cents"] == 87640

        d4 = fixtures.read_agreement(api, bundle["agreement_id"])
        assert d4["status"] == "PAID_IN_FULL", "the financing dimension moves"
        assert d4["delinquency_stage"] == "CURRENT", (
            "the delinquency dimension stands still through the payoff"
        )
        assert d4["refund_due_cents"] == 0
        assert d4["principal_balance_cents"] == 0
        assert d4["unpaid_finance_charge_cents"] == 0
        assert d4["late_fee_balance_cents"] == 0
        rows = fixtures.read_installments(api, bundle["agreement_id"])
        assert len(rows) == 9
        assert all(row["status"] == "PAID" for row in rows), (
            "every installment still SCHEDULED or PAST_DUE moves to PAID"
        )


class TestPaymentCureCascadeToTheNoticeAndThePowerOfAttorney:
    """One posting propagates upward from ledger rows to the statutory notice and
    revokes the power of attorney."""

    def _noticed(self, api):
        """A TX9 note carrying an ISSUED notice with effective_cancel_date
        2026-11-23, one OUTSTANDING 7738 fee and a PAST_DUE installment 2."""
        bundle = fixtures.tx9_note(api, single_policy=False)
        _pay_installment_one(api, bundle)
        _assess_the_fee(api, bundle)
        notice = _issue_the_notice(api, bundle)
        assert bundle["fee"]["status"] == "OUTSTANDING"
        assert bundle["fee"]["amount_cents"] == 7738
        assert notice["effective_cancel_date"] == "2026-11-23"
        return bundle

    def test_hop_one_the_posting_settles_the_fee_then_the_installment(self, api):
        """Bucket one empties before bucket two, and finance charge before
        principal.

        The PRD states: "Bucket one settles `OUTSTANDING` late fees, ordered by
        `assessed_date` ascending, then `installment_number` ascending, then
        `created_at` ascending; a fee is settled only if the unallocated remainder
        covers its `amount_cents` whole, and a remainder smaller than the fee
        leaves that fee `OUTSTANDING` and flows on rather than part-paying it."

        Design: Difficulty/transitive_cascade/payment_cure_cascade_to_notice_and_power_of_attorney
        """
        bundle = self._noticed(api)

        cure = _post_the_cure(api, bundle)

        assert cure["allocation_variant"] == "STANDARD", (
            "162499 is far below the net payoff, so no rebate is granted"
        )
        assert cure["applied_late_fee_cents"] == 7738
        assert cure["applied_finance_charge_cents"] == 15650
        assert cure["applied_principal_cents"] == 139111
        assert cure["applied_unapplied_cents"] == 0

        fees = fixtures.read_late_fees(api, bundle["agreement_id"])
        assert fees[0]["status"] == "PAID"
        rows = fixtures.read_installments(api, bundle["agreement_id"])
        rows.sort(key=lambda row: row["installment_number"])
        assert rows[1]["status"] == "PAID"
        assert rows[1]["paid_cents"] == 154761

    def test_hop_two_the_delinquency_clears_but_the_lifetime_counter_does_not(
        self, api
    ):
        """The stage walks back to CURRENT while `late_fee_count` holds.

        The PRD states: "`late_fee_count` is a lifetime counter that never moves
        backwards, so neither a waiver nor a reversal restores it."

        Design: Difficulty/transitive_cascade/payment_cure_cascade_to_notice_and_power_of_attorney
        """
        bundle = self._noticed(api)

        _post_the_cure(api, bundle)

        agreement = fixtures.read_agreement(api, bundle["agreement_id"])
        assert agreement["status"] == "ACTIVE"
        assert agreement["delinquency_stage"] == "CURRENT"
        assert agreement["late_fee_balance_cents"] == 0
        assert agreement["late_fee_count"] == 1

    def test_hop_three_the_issued_notice_reaches_cured(self, api):
        """The statutory instrument follows the ledger.

        The PRD states: "It reaches `CURED`, with `cured_date` stamped at the clock
        date, when a payment or a late-fee waiver clears every past-due obligation
        — no `PAST_DUE` installment and a `late_fee_balance_cents` of zero."

        Design: Difficulty/transitive_cascade/payment_cure_cascade_to_notice_and_power_of_attorney
        """
        bundle = self._noticed(api)

        _post_the_cure(api, bundle)

        notices, meta = validate_paginated(
            api.list_cancellation_notices(
                bundle["agreement_id"], ANALYST_ORIGIN, {"limit": 50}
            )
        )
        assert meta["total_count"] == 1
        assert notices[0]["status"] == "CURED"
        assert notices[0]["cured_date"] == "2026-11-13"

    def test_hop_four_the_power_of_attorney_can_no_longer_be_exercised(self, api):
        """On the very date the notice matured, the cancellation is refused.

        The PRD states: "It requires an `ACTIVE` note whose `delinquency_stage` is
        `NOIC_ISSUED` and a notice in `ISSUED` status".

        Design: Difficulty/transitive_cascade/payment_cure_cascade_to_notice_and_power_of_attorney
        """
        bundle = self._noticed(api)
        _post_the_cure(api, bundle)
        fixtures.set_clock(api, "2026-11-23T00:00:00Z")

        validate_error(
            api.execute_cancellation(bundle["agreement_id"], ANALYST_POA),
            ApiErrorId.DELINQUENCY_STATE_INVALID.value,
            409,
        )

    def test_hop_four_leaves_the_policies_uncancelled(self, api):
        """No policy was pulled and no carrier request was raised.

        The PRD states: "Every policy of the note whose `status` is `VERIFIED`
        moves to `CANCELLED`, its `cancellation_effective_date` set to the notice's
        `effective_cancel_date`".

        Design: Difficulty/transitive_cascade/payment_cure_cascade_to_notice_and_power_of_attorney
        """
        bundle = self._noticed(api)
        _post_the_cure(api, bundle)
        fixtures.set_clock(api, "2026-11-23T00:00:00Z")
        validate_error(
            api.execute_cancellation(bundle["agreement_id"], ANALYST_POA),
            ApiErrorId.DELINQUENCY_STATE_INVALID.value,
            409,
        )

        policy = fixtures.read_policy(api, bundle["policy_ids"][0])
        assert policy["status"] == "VERIFIED", (
            "a refused execution may not cancel a policy with its carrier"
        )
        _requests, meta = validate_paginated(
            api.list_carrier_cancellation_requests(
                ANALYST_ORIGIN,
                {"agreement_id": bundle["agreement_id"], "limit": 50},
            )
        )
        assert meta["total_count"] == 0, (
            "no carrier cancellation request may exist for a note that cured"
        )


class TestRenoticeBlackoutClosedWindow:
    """The cure blackout is closed at both ends, and it keeps running even after a
    reversal drags the account back into delinquency."""

    def _cured_then_reversed(self, api):
        """A note whose cure payment has been reversed as an NSF item, leaving a
        CURED notice with cured_date 2026-11-13 and a LATE account."""
        bundle = fixtures.tx9_note(api, single_policy=True)
        _pay_installment_one(api, bundle)
        _assess_the_fee(api, bundle)
        _issue_the_notice(api, bundle)
        cure = _post_the_cure(api, bundle)
        notices = fixtures.read_notices(api, bundle["agreement_id"])
        assert notices[0]["status"] == "CURED"
        assert notices[0]["cured_date"] == "2026-11-13"
        bundle["reversal"] = validate_success(
            api.reverse_payment(cure["id"], factories.reversal(), ANALYST_ORIGIN), 200
        )
        return bundle

    def test_the_reversal_reopens_the_delinquency_while_the_cured_notice_stands(
        self, api
    ):
        """Nothing but the blackout stands between the analyst and a fresh notice.

        The PRD states: "A notice of intent to cancel that had already reached
        `CURED` stays `CURED`, because that state is terminal, and its blackout
        window keeps running regardless of the returned item."

        Design: Difficulty/resource_temporal_overlap/renotice_blackout_closed_window_on_agreement
        """
        bundle = self._cured_then_reversed(api)

        assert bundle["reversal"]["status"] == "REVERSED"
        agreement = fixtures.read_agreement(api, bundle["agreement_id"])
        assert agreement["delinquency_stage"] == "LATE"
        assert agreement["late_fee_balance_cents"] == 7738
        assert agreement["principal_balance_cents"] == 1112889
        notices = fixtures.read_notices(api, bundle["agreement_id"])
        assert notices[0]["status"] == "CURED", (
            "the CURED state is terminal and the returned item does not undo it"
        )

    def test_the_blackout_lower_bound_is_inclusive(self, api):
        """On the cure date itself a fresh notice is refused.

        The PRD states: "the issuance is refused with
        `ERR_NOTICE_BLACKOUT_ACTIVE` (HTTP 409) for as long as `cured_date`
        advanced by `noic_notice_days` is greater than or equal to the clock date,
        and is accepted only once the clock date is strictly beyond that."

        Design: Difficulty/resource_temporal_overlap/renotice_blackout_closed_window_on_agreement
        """
        bundle = self._cured_then_reversed(api)

        validate_error(
            api.issue_cancellation_notice(bundle["agreement_id"], ANALYST_NOTICE),
            ApiErrorId.NOTICE_BLACKOUT_ACTIVE.value,
            409,
        )

    def test_the_blackout_interior_is_blocked(self, api):
        """Nine days into the breathing space the slot is still occupied.

        The PRD states: "And a borrower who cures a delinquency earns a breathing
        space: for the most recently `CURED` notice of the note, the closed window
        running from its `cured_date` through its `cured_date` advanced by the
        regime's `noic_notice_days` blocks a fresh notice."

        Design: Difficulty/resource_temporal_overlap/renotice_blackout_closed_window_on_agreement
        """
        bundle = self._cured_then_reversed(api)
        fixtures.set_clock(api, "2026-11-22T00:00:00Z")

        validate_error(
            api.issue_cancellation_notice(bundle["agreement_id"], ANALYST_NOTICE),
            ApiErrorId.NOTICE_BLACKOUT_ACTIVE.value,
            409,
        )

    def test_the_blackout_upper_bound_is_also_inclusive(self, api):
        """The day equal to the upper bound is blocked, unlike a half-open term.

        The PRD states: "the closed window running from its `cured_date` through
        its `cured_date` advanced by the regime's `noic_notice_days` blocks a fresh
        notice."  2026-11-23 is exactly 2026-11-13 advanced by ten days.

        Design: Difficulty/resource_temporal_overlap/renotice_blackout_closed_window_on_agreement
        """
        bundle = self._cured_then_reversed(api)
        fixtures.set_clock(api, "2026-11-23T00:00:00Z")

        validate_error(
            api.issue_cancellation_notice(bundle["agreement_id"], ANALYST_NOTICE),
            ApiErrorId.NOTICE_BLACKOUT_ACTIVE.value,
            409,
        )

    def test_one_day_past_the_upper_bound_the_slot_is_free(self, api):
        """The day after the closed window a fresh notice issues on the restored
        arrears.

        The PRD states: "A successful issuance writes a notice in `ISSUED` status
        with `issued_date` set to the clock date, `issued_by_user_id` taken from
        `X-User-ID`, `notice_days` snapshotted from the regime's `noic_notice_days`
        at that moment, and `effective_cancel_date` set to `issued_date` advanced
        by `notice_days` calendar days."

        Design: Difficulty/resource_temporal_overlap/renotice_blackout_closed_window_on_agreement
        """
        bundle = self._cured_then_reversed(api)
        fixtures.set_clock(api, "2026-11-24T00:00:00Z")

        fresh = validate_success(
            api.issue_cancellation_notice(bundle["agreement_id"], ANALYST_NOTICE), 201
        )

        assert fresh["status"] == "ISSUED"
        assert fresh["issued_date"] == "2026-11-24"
        assert fresh["effective_cancel_date"] == "2026-12-04"
        assert fresh["past_due_amount_cents"] == 162499, (
            "the reversal put the arrears back exactly: the restored 154761 "
            "past-due installment plus the restored 7738 late fee"
        )
        notices, meta = validate_paginated(
            api.list_cancellation_notices(
                bundle["agreement_id"], ANALYST_ORIGIN, {"limit": 50}
            )
        )
        assert meta["total_count"] == 2
        assert sorted(row["status"] for row in notices) == ["CURED", "ISSUED"]

    def test_the_refused_attempts_write_nothing(self, api):
        """Three blocked issuances leave no notice row and no state change.

        The PRD states: "A note may carry only one open notice at a time: if any
        notice of the note is already `ISSUED`, the request is refused with
        `ERR_NOTICE_WINDOW_OPEN` (HTTP 409)".

        Design: Difficulty/resource_temporal_overlap/renotice_blackout_closed_window_on_agreement
        """
        bundle = self._cured_then_reversed(api)

        for clock in (None, "2026-11-22T00:00:00Z", "2026-11-23T00:00:00Z"):
            if clock is not None:
                fixtures.set_clock(api, clock)
            validate_error(
                api.issue_cancellation_notice(bundle["agreement_id"], ANALYST_NOTICE),
                ApiErrorId.NOTICE_BLACKOUT_ACTIVE.value,
                409,
            )

        notices, meta = validate_paginated(
            api.list_cancellation_notices(
                bundle["agreement_id"], ANALYST_ORIGIN, {"limit": 50}
            )
        )
        assert meta["total_count"] == 1, (
            "the three refused attempts may not create a CancellationNotice row"
        )
        assert notices[0]["status"] == "CURED"
        agreement = fixtures.read_agreement(api, bundle["agreement_id"])
        assert agreement["delinquency_stage"] == "LATE", (
            "a refused issuance may not move the delinquency stage"
        )
