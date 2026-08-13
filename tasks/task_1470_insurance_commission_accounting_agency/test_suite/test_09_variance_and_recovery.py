"""Variance resolution cascades and recovery error ordering (PRD §3.6, §3.7,
§3.8)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    get_producer,
    get_single_chargeback,
    get_single_entry,
    setup_cancelled_policy,
    setup_reconciling_statement,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestVarianceResolutionCascade:
    """Difficulty instance: resolve-variance -> negative VARIANCE_ADJUSTMENT ->
    PENDING chargeback -> producer SUSPENDED (depth-3 chain)."""

    def _setup(self):
        # BASE = 12000000 * 5000 / 10000 = 6000000; statement reports 5400000,
        # |5400000 - 6000000| = 600000 > 100 tolerance -> VARIANCE.
        bundle = setup_reconciling_statement(
            premium_annual_cents=12000000,
            commission_rate_bps=5000,
            reported_amount_cents=5400000,
            policy_number="P-V1",
        )
        assert bundle["entry"]["status"] == "VARIANCE"
        resolved = validate_success(
            api_client.resolve_variance(
                bundle["entry"]["id"], {"accept_amount_cents": 5400000}, ADMIN
            ),
            200,
        )
        bundle["resolved"] = resolved
        return bundle

    def test_entry_matched_amount_immutable_adjustment_created(self):
        """PRD §3.7: "The original entry's booked amount is immutable and
        does not change; instead the entry moves from `VARIANCE` to `MATCHED`
        with `matched_at` stamped, the flagging statement line moves from
        `VARIANCE_FLAGGED` to `MATCHED`, and a `VARIANCE_ADJUSTMENT` entry is
        created with `status` `MATCHED`, `source_entry_id` pointing at the
        resolved entry, and an `amount_cents` equal to the accepted amount
        minus the original booked amount — negative when the agency accepts
        less than it booked."

        Design: Difficulty/transitive_cascade/variance_resolution_chargeback_suspends
        """
        bundle = self._setup()
        resolved = bundle["resolved"]
        assert resolved["status"] == "MATCHED"
        assert resolved["amount_cents"] == 6000000
        assert resolved["matched_at"] is not None

        adjustment = get_single_entry(
            bundle["policy"]["id"], "VARIANCE_ADJUSTMENT"
        )
        assert adjustment["amount_cents"] == -600000
        assert adjustment["status"] == "MATCHED"
        assert adjustment["source_entry_id"] == resolved["id"]

        statement = validate_success(
            api_client.get_carrier_statement(bundle["statement"]["id"], ADMIN), 200
        )
        line = next(
            l for l in statement["lines"] if l["line_ref"] == "P-V1"
        )
        assert line["match_status"] == "MATCHED"

    def test_negative_adjustment_creates_chargeback_and_suspends(self):
        """PRD §3.7: "When that adjustment is negative, a `PENDING`
        chargeback is created with `reason` `OVERPAYMENT_VARIANCE` for the
        absolute shortfall, and the producer-suspension check of §3.8 runs on
        the result."
        PRD §3.8: "Immediately after any chargeback is created — from the
        cancellation cascade of §3.6 or the variance resolution of §3.7 — if
        the producer's `PENDING` chargeback outstanding total is strictly
        greater than $5,000.00 (500000 cents) and the producer is still
        `ACTIVE`, the system moves the producer to `SUSPENDED`, incrementing
        the producer's `version` and refreshing `updated_at`."

        Design: Difficulty/transitive_cascade/variance_resolution_chargeback_suspends
        """
        bundle = self._setup()
        chargeback = get_single_chargeback(producer_id=bundle["producer"]["id"])
        assert chargeback["status"] == "PENDING"
        assert chargeback["amount_cents"] == 600000
        assert chargeback["reason"] == "OVERPAYMENT_VARIANCE"

        producer = get_producer(bundle["producer"]["id"])
        # 600000 > 500000 -> SUSPENDED.
        assert producer["status"] == "SUSPENDED"
        # Balance: MATCHED BASE 6000000 + MATCHED adjustment -600000.
        assert producer["commission_balance_cents"] == 5400000


class TestRecoveryErrorOrdering:
    """Difficulty instance: on a terminal RECOVERED chargeback, the state
    check outranks the fiscal check."""

    def _setup_recovered_chargeback(self):
        # 2400000 @ 5000 bps -> BASE 1200000; cancel at 6 months ->
        # earned 600000, unearned 600000 -> chargeback 600000 PENDING.
        bundle = setup_cancelled_policy(
            premium_annual_cents=2400000,
            commission_rate_bps=5000,
            cancel_effective_date="2027-02-01",
            policy_number="P-S1",
        )
        chargeback = get_single_chargeback(policy_id=bundle["policy"]["id"])
        recovered = validate_success(
            api_client.record_recovery(
                chargeback["id"], {"amount_cents": 600000}, ADMIN
            ),
            200,
        )
        return bundle, recovered

    def test_full_recovery_reaches_recovered(self):
        """PRD §3.6: "Recoveries accumulate into `recovered_cents`; the
        chargeback reaches `RECOVERED` exactly when `recovered_cents` equals
        `amount_cents`, and a partial recovery leaves it `PENDING`."

        Design: Difficulty/priority_pair_validation_conflict/recovery_on_recovered_chargeback_state_beats_fiscal
        """
        _, recovered = self._setup_recovered_chargeback()
        assert recovered["status"] == "RECOVERED"
        assert recovered["recovered_cents"] == 600000
        assert recovered["outstanding_cents"] == 0

    def test_recovery_on_recovered_returns_state_error(self):
        """PRD §3.6: "`RECOVERED` and `WRITTEN_OFF` are both terminal."
        PRD §2.9: "Every request is evaluated against an ordered cascade of
        checks; the earliest failing check determines the error returned, and
        later checks do not run."
        PRD §2.9: "4. **State admissibility** — the target resource is in a
        state that allows the operation, and the optimistic-concurrency check
        of §2.7 passes, else `ERR_INVALID_STATE` or `ERR_STALE_VERSION`.
        Terminal-state lockdowns, such as paying or reversing an already
        `PAID` invoice, fail here."

        Design: Difficulty/priority_pair_validation_conflict/recovery_on_recovered_chargeback_state_beats_fiscal
        """
        _, recovered = self._setup_recovered_chargeback()
        # 700000 also exceeds outstanding 0 (fiscal), but the terminal-state
        # check fires first.
        res = api_client.record_recovery(
            recovered["id"], {"amount_cents": 700000}, ADMIN
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
