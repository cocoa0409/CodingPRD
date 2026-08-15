"""Voluntary cancellation, unearned-commission chargebacks, recovery,
write-off, and the suspension cascade (PRD §3.6, §3.8)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    get_producer,
    get_single_chargeback,
    get_single_entry,
    setup_cancelled_policy,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestVoluntaryCancelCascade:
    """Difficulty instance: cancel -> entry CHARGED_BACK + EARNED_ADJUSTMENT +
    Chargeback PENDING -> producer SUSPENDED (depth-3 chain)."""

    def _setup(self):
        return setup_cancelled_policy(
            premium_annual_cents=12000000,
            commission_rate_bps=5500,
            cancel_effective_date="2027-02-01",
            policy_number="P-C1",
        )

    def test_cancel_charges_back_entry_and_splits_earned(self):
        """PRD §3.6: "Each such entry then moves to `CHARGED_BACK`, and two
        records fall out per entry. An `EARNED_ADJUSTMENT` entry is always
        created — even when the earned portion is zero — carrying the earned
        amount, `status` `MATCHED`, `matched_at` stamped with the current
        time, and `source_entry_id` pointing back to the original entry. A
        **Chargeback** is created only when the unearned portion is greater
        than zero, starting in `PENDING` status with `amount_cents` equal to
        the unearned portion, `recovered_cents` at zero, and
        `outstanding_cents` — always the amount minus what has been recovered
        — equal to the full amount."

        Design: Difficulty/transitive_cascade/voluntary_cancel_suspends_producer
        """
        bundle = self._setup()
        policy = bundle["cancelled_policy"]
        assert policy["status"] == "CANCELLED_VOLUNTARY"
        assert policy["cancel_effective_date"] == "2027-02-01"

        base = get_single_entry(policy["id"], "BASE")
        assert base["status"] == "CHARGED_BACK"
        assert base["amount_cents"] == 6600000

        # 6 whole months earned of 12: 6600000 * 6 / 12 = 3300000.
        adjustment = get_single_entry(policy["id"], "EARNED_ADJUSTMENT")
        assert adjustment["amount_cents"] == 3300000
        assert adjustment["status"] == "MATCHED"
        assert adjustment["source_entry_id"] == base["id"]

        chargeback = get_single_chargeback(policy_id=policy["id"])
        assert chargeback["status"] == "PENDING"
        assert chargeback["amount_cents"] == 3300000
        assert chargeback["reason"] == "CANCELLATION_UNEARNED"
        assert chargeback["outstanding_cents"] == 3300000

    def test_chargeback_creation_suspends_producer(self):
        """PRD §3.8: "Immediately after any chargeback is created — from the
        cancellation cascade of §3.6 or the variance resolution of §3.7 — if
        the producer's `PENDING` chargeback outstanding total is strictly
        greater than $5,000.00 (500000 cents) and the producer is still
        `ACTIVE`, the system moves the producer to `SUSPENDED`, incrementing
        the producer's `version` and refreshing `updated_at`."
        PRD §3.8: "A producer's `commission_balance_cents` is the
        earned-but-unpaid ledger position: the sum of `amount_cents` over
        every commission entry — of any entry type — for which the producer
        is the recipient and the status is `EXPECTED` or `MATCHED`, minus the
        sum of `amount_cents` over the producer's payouts already in `PAID`
        status."

        Design: Difficulty/transitive_cascade/voluntary_cancel_suspends_producer
        """
        bundle = self._setup()
        producer = get_producer(bundle["producer"]["id"])
        # 3300000 PENDING > 500000 -> SUSPENDED.
        assert producer["status"] == "SUSPENDED"
        # BASE is CHARGED_BACK (excluded); only the 3300000 MATCHED
        # EARNED_ADJUSTMENT counts toward the balance.
        assert producer["commission_balance_cents"] == 3300000
        assert producer["pending_chargebacks_cents"] == 3300000


class TestCancelEarnedIdentity:
    """Difficulty instance: chargeback + earned-adjustment amounts conserve
    the original booked amount."""

    def test_earned_and_unearned_halves(self):
        """PRD §3.6: "The earned month count is the number of whole calendar
        months from the policy's `effective_date` to its
        `cancel_effective_date`: take the cancellation year minus the
        effective year, multiply by twelve, add the cancellation month minus
        the effective month, and if the cancellation day-of-month is earlier
        than the effective day-of-month, subtract one; the result is clamped
        so it never falls below zero and never exceeds twelve."

        Design: Difficulty/compensating_invariant/cancel_chargeback_earned_identity
        """
        bundle = setup_cancelled_policy(
            premium_annual_cents=12000000,
            commission_rate_bps=5500,
            cancel_effective_date="2027-02-01",
            policy_number="P-E1",
        )
        # 2026-08-01 -> 2027-02-01 is exactly 6 whole months.
        adjustment = get_single_entry(bundle["policy"]["id"], "EARNED_ADJUSTMENT")
        chargeback = get_single_chargeback(policy_id=bundle["policy"]["id"])
        assert adjustment["amount_cents"] == 3300000
        assert chargeback["amount_cents"] == 3300000

    def test_conservation_identity_holds(self):
        """PRD §3.6: "The conservation invariant is exact: for every
        clawed-back entry, the chargeback's amount plus the earned-adjustment
        entry's amount equals the original entry's booked amount."

        Design: Difficulty/compensating_invariant/cancel_chargeback_earned_identity
        """
        bundle = setup_cancelled_policy(
            premium_annual_cents=12000000,
            commission_rate_bps=5500,
            cancel_effective_date="2027-02-01",
            policy_number="P-E2",
        )
        base = get_single_entry(bundle["policy"]["id"], "BASE")
        adjustment = get_single_entry(bundle["policy"]["id"], "EARNED_ADJUSTMENT")
        chargeback = get_single_chargeback(policy_id=bundle["policy"]["id"])
        assert (
            chargeback["amount_cents"] + adjustment["amount_cents"]
            == base["amount_cents"]
            == 6600000
        )


class TestCancelMonthCounting:
    def test_zero_whole_months_claws_back_everything(self):
        """PRD §3.6: "The earned month count is the number of whole calendar
        months from the policy's `effective_date` to its
        `cancel_effective_date`: take the cancellation year minus the
        effective year, multiply by twelve, add the cancellation month minus
        the effective month, and if the cancellation day-of-month is earlier
        than the effective day-of-month, subtract one; the result is clamped
        so it never falls below zero and never exceeds twelve."
        PRD §3.6: "An `EARNED_ADJUSTMENT` entry is always created — even when
        the earned portion is zero — carrying the earned amount, `status`
        `MATCHED`, `matched_at` stamped with the current time, and
        `source_entry_id` pointing back to the original entry."

        Design: Corner/calculations/cancel_month_zero_full_chargeback
        """
        bundle = setup_cancelled_policy(
            premium_annual_cents=2400000,
            commission_rate_bps=5000,
            cancel_effective_date="2026-08-15",
            policy_number="P-C2T",
        )
        # 2026-08-01 -> 2026-08-15 earns 0 whole months; full 1200000 clawback.
        chargeback = get_single_chargeback(policy_id=bundle["policy"]["id"])
        assert chargeback["amount_cents"] == 1200000
        adjustment = get_single_entry(bundle["policy"]["id"], "EARNED_ADJUSTMENT")
        assert adjustment["amount_cents"] == 0

    def test_twelve_months_earned_creates_no_chargeback(self):
        """PRD §3.6: "A **Chargeback** is created only when the unearned
        portion is greater than zero, starting in `PENDING` status with
        `amount_cents` equal to the unearned portion, `recovered_cents` at
        zero, and `outstanding_cents` — always the amount minus what has been
        recovered — equal to the full amount."

        Design: Corner/calculations/cancel_after_twelve_months_creates_no_chargeback
        """
        bundle = setup_cancelled_policy(
            premium_annual_cents=2400000,
            commission_rate_bps=5000,
            cancel_effective_date="2027-08-01",
            policy_number="P-C3T",
        )
        data, meta = validate_paginated(
            api_client.list_chargebacks(
                ADMIN, params={"policy_id": bundle["policy"]["id"]}
            )
        )
        assert data == []
        assert meta["total_count"] == 0
        adjustment = get_single_entry(bundle["policy"]["id"], "EARNED_ADJUSTMENT")
        assert adjustment["amount_cents"] == 1200000
        assert get_producer(bundle["producer"]["id"])["status"] == "ACTIVE"


class TestCancelTerminalLockdown:
    def test_second_cancel_rejected_no_new_chargeback(self):
        """PRD §3.6: "An `AgencyAdmin` or `AgencyAccountant` may voluntarily
        cancel a policy in `ACTIVE` or `GRACE` by supplying a
        `cancel_effective_date`; the date must not fall before the policy's
        `effective_date`, or the request fails with `ERR_INVALID_REQUEST`."
        PRD §2.9: "4. **State admissibility** — the target resource is in a
        state that allows the operation, and the optimistic-concurrency check
        of §2.7 passes, else `ERR_INVALID_STATE` or `ERR_STALE_VERSION`.
        Terminal-state lockdowns, such as paying or reversing an already
        `PAID` invoice, fail here."

        Design: Corner/state_machines/cancel_terminal_lockdown
        """
        bundle = setup_cancelled_policy(
            premium_annual_cents=2400000,
            commission_rate_bps=5000,
            cancel_effective_date="2027-02-01",
            policy_number="P-S3C",
        )
        res = api_client.cancel_policy(
            bundle["policy"]["id"], {"cancel_effective_date": "2027-03-01"}, ADMIN
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        _, meta = validate_paginated(
            api_client.list_chargebacks(
                ADMIN, params={"policy_id": bundle["policy"]["id"]}
            )
        )
        assert meta["total_count"] == 1, "the rejected cancel must not re-fire"


class TestChargebackRecoveryAndWriteOff:
    def _setup_suspended_with_chargeback(self):
        """2400000 @ 5000 bps, cancel at 6 months -> 600000 PENDING chargeback
        and a SUSPENDED producer."""
        return setup_cancelled_policy(
            premium_annual_cents=2400000,
            commission_rate_bps=5000,
            cancel_effective_date="2027-02-01",
        )

    def test_recovery_above_outstanding_rejected(self):
        """PRD §3.6: "Each recovery's `amount_cents` must be positive (else
        `ERR_INVALID_REQUEST`) and must not exceed the chargeback's
        `outstanding_cents`, or it is rejected with
        `ERR_RECOVERY_EXCEEDS_OUTSTANDING`."

        Design: Corner/validations/recovery_above_outstanding_returns_409
        """
        bundle = self._setup_suspended_with_chargeback()
        chargeback = get_single_chargeback(policy_id=bundle["policy"]["id"])
        assert chargeback["outstanding_cents"] == 600000
        res = api_client.record_recovery(
            chargeback["id"], {"amount_cents": 600001}, ADMIN
        )
        validate_error(
            res, ApiErrorId.ERR_RECOVERY_EXCEEDS_OUTSTANDING, expected_status=409
        )
        after = validate_success(
            api_client.get_chargeback(chargeback["id"], ADMIN), 200
        )
        assert after["recovered_cents"] == 0
        assert after["status"] == "PENDING"

    def test_writeoff_requires_terminated_producer(self):
        """PRD §3.6: "When the producer has been terminated and the debt is
        uncollectable, an `AgencyAdmin` may write the chargeback off — but
        only while the chargeback's producer is `TERMINATED`; otherwise the
        attempt is rejected with `ERR_PRODUCER_NOT_TERMINATED`."

        Design: Difficulty/cross_entity_state_dependency/writeoff_requires_terminated_producer
        """
        bundle = self._setup_suspended_with_chargeback()
        chargeback = get_single_chargeback(policy_id=bundle["policy"]["id"])
        res = api_client.write_off_chargeback(chargeback["id"], ADMIN)
        validate_error(
            res, ApiErrorId.ERR_PRODUCER_NOT_TERMINATED, expected_status=409
        )
        after = validate_success(
            api_client.get_chargeback(chargeback["id"], ADMIN), 200
        )
        assert after["status"] == "PENDING"

    def test_writeoff_succeeds_after_termination(self):
        """PRD §3.6: "When the producer has been terminated and the debt is
        uncollectable, an `AgencyAdmin` may write the chargeback off — but
        only while the chargeback's producer is `TERMINATED`; otherwise the
        attempt is rejected with `ERR_PRODUCER_NOT_TERMINATED`."
        PRD §3.1: "Termination, reserved to the `AgencyAdmin`, moves a
        producer from `ACTIVE` to `TERMINATED` or from `SUSPENDED` to
        `TERMINATED`; the terminal state admits no further transitions."

        Design: Difficulty/cross_entity_state_dependency/writeoff_requires_terminated_producer
        """
        bundle = self._setup_suspended_with_chargeback()
        chargeback = get_single_chargeback(policy_id=bundle["policy"]["id"])
        validate_error(
            api_client.write_off_chargeback(chargeback["id"], ADMIN),
            ApiErrorId.ERR_PRODUCER_NOT_TERMINATED,
            expected_status=409,
        )
        terminated = validate_success(
            api_client.terminate_producer(bundle["producer"]["id"], ADMIN), 200
        )
        assert terminated["status"] == "TERMINATED"
        written_off = validate_success(
            api_client.write_off_chargeback(chargeback["id"], ADMIN), 200
        )
        assert written_off["status"] == "WRITTEN_OFF"

    def test_reactivate_with_pending_chargeback_rejected(self):
        """PRD §3.1: "A suspended producer is restored to `ACTIVE` by an
        `AgencyAdmin` or `AgencyAccountant` through reactivation, which is
        permitted only when the producer has no `PENDING` chargebacks
        remaining — otherwise the attempt is rejected with
        `ERR_PRODUCER_STILL_SUSPENDED`."

        Design: Corner/validations/reactivate_with_pending_chargeback_returns_409
        """
        bundle = self._setup_suspended_with_chargeback()
        assert get_producer(bundle["producer"]["id"])["status"] == "SUSPENDED"
        res = api_client.reactivate_producer(bundle["producer"]["id"], ADMIN)
        validate_error(
            res, ApiErrorId.ERR_PRODUCER_STILL_SUSPENDED, expected_status=409
        )
        assert get_producer(bundle["producer"]["id"])["status"] == "SUSPENDED"
