"""Producer payouts: compliance/fiscal gates, OCC, balance derivation
(PRD §3.8)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    cancel_policy,
    create_and_mark_payout_paid,
    create_payout_fresh_version,
    fresh_producer_version,
    get_producer,
    setup_bound_policy,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestPayoutTaxHoldPriority:
    """Difficulty instance: the tax-hold compliance gate outranks the
    balance fiscal check."""

    def _setup_no_tax_form(self):
        return setup_bound_policy(
            premium_annual_cents=2400000,
            commission_rate_bps=5000,
            policy_number="P-H1",
            producer_overrides={"name": "Writer H", "license_number": "LIC-H1"},
        )

    def test_tax_hold_reported_over_excess_amount(self):
        """PRD §2.9: "Compliance gates therefore outrank cross-entity state
        checks: on payout creation, for instance, a missing tax form surfaces
        as `ERR_PRODUCER_TAX_HOLD` before a non-active producer would surface
        as `ERR_PRODUCER_NOT_ACTIVE`."
        PRD §3.8: "the producer's `tax_form_on_file` must be true, else
        `ERR_PRODUCER_TAX_HOLD`; the producer must have no `PENDING`
        chargebacks at all, else `ERR_OUTSTANDING_CHARGEBACK`; and the amount
        must not exceed the producer's `commission_balance_cents` at that
        moment, else `ERR_PAYOUT_EXCEEDS_BALANCE`."

        Design: Difficulty/priority_pair_validation_conflict/payout_tax_hold_beats_balance
        """
        bundle = self._setup_no_tax_form()
        assert bundle["producer"]["tax_form_on_file"] is False
        res = api_client.create_payout(
            bundle["producer"]["id"],
            {
                "amount_cents": 99999999,
                "expected_producer_version": fresh_producer_version(
                    bundle["producer"]["id"]
                ),
            },
            ADMIN,
        )
        validate_error(res, ApiErrorId.ERR_PRODUCER_TAX_HOLD, expected_status=409)

    def test_tax_hold_not_balance_error(self):
        """PRD §3.8: "the producer's `tax_form_on_file` must be true, else
        `ERR_PRODUCER_TAX_HOLD`; the producer must have no `PENDING`
        chargebacks at all, else `ERR_OUTSTANDING_CHARGEBACK`; and the amount
        must not exceed the producer's `commission_balance_cents` at that
        moment, else `ERR_PAYOUT_EXCEEDS_BALANCE`."

        Design: Difficulty/priority_pair_validation_conflict/payout_tax_hold_beats_balance
        """
        bundle = self._setup_no_tax_form()
        # Balance is 1200000; the requested 99999999 also violates the
        # fiscal check, yet the compliance gate's error must surface.
        res = api_client.create_payout(
            bundle["producer"]["id"],
            {
                "amount_cents": 99999999,
                "expected_producer_version": fresh_producer_version(
                    bundle["producer"]["id"]
                ),
            },
            ADMIN,
        )
        assert res.status_code == 409
        body = res.json()
        assert body["data"]["error_id"] == "ERR_PRODUCER_TAX_HOLD"
        assert body["data"]["error_id"] != "ERR_PAYOUT_EXCEEDS_BALANCE"


class TestPayoutFiscalGates:
    def test_payout_blocked_by_pending_chargeback(self):
        """PRD §3.8: "the producer must have no `PENDING` chargebacks at all,
        else `ERR_OUTSTANDING_CHARGEBACK`".

        Design: Corner/validations/payout_with_pending_chargeback_blocked
        """
        bundle = setup_bound_policy(
            premium_annual_cents=2400000,
            commission_rate_bps=5000,
            policy_number="P-V2V",
            producer_overrides={"tax_form_on_file": True},
        )
        # Cancel at 11 whole months: earned 1100000, unearned 100000 ->
        # PENDING chargeback below the suspension threshold.
        cancel_policy(bundle["policy"]["id"], "2027-07-01")
        producer = get_producer(bundle["producer"]["id"])
        assert producer["status"] == "ACTIVE"
        assert producer["pending_chargebacks_cents"] == 100000

        res = api_client.create_payout(
            bundle["producer"]["id"],
            {
                "amount_cents": 50000,
                "expected_producer_version": producer["version"],
            },
            ADMIN,
        )
        validate_error(res, ApiErrorId.ERR_OUTSTANDING_CHARGEBACK, expected_status=409)

    def test_payout_above_balance_rejected(self):
        """PRD §3.8: "the amount must not exceed the producer's
        `commission_balance_cents` at that moment, else
        `ERR_PAYOUT_EXCEEDS_BALANCE`."

        Design: Corner/validations/payout_above_balance_returns_409
        """
        bundle = setup_bound_policy(
            premium_annual_cents=2400000,
            commission_rate_bps=5000,
            policy_number="P-V9V",
            producer_overrides={"tax_form_on_file": True},
        )
        assert (
            get_producer(bundle["producer"]["id"])["commission_balance_cents"]
            == 1200000
        )
        res = api_client.create_payout(
            bundle["producer"]["id"],
            {
                "amount_cents": 1200001,
                "expected_producer_version": fresh_producer_version(
                    bundle["producer"]["id"]
                ),
            },
            ADMIN,
        )
        validate_error(res, ApiErrorId.ERR_PAYOUT_EXCEEDS_BALANCE, expected_status=409)


class TestPayoutLifecycle:
    def _setup_paid_payout(self):
        bundle = setup_bound_policy(
            premium_annual_cents=2400000,
            commission_rate_bps=5000,
            policy_number="P-S7C",
            producer_overrides={"tax_form_on_file": True},
        )
        payout = create_and_mark_payout_paid(bundle["producer"]["id"], 400000)
        return bundle, payout

    def test_mark_paid_twice_rejected_balance_debited_once(self):
        """PRD §3.8: "Marking the payout paid re-verifies the producer's
        position at that moment — the producer must still be `ACTIVE` (else
        `ERR_PRODUCER_NOT_ACTIVE`) and the payout amount must still fit
        within the current `commission_balance_cents` (else
        `ERR_PAYOUT_EXCEEDS_BALANCE`) — then moves the payout from
        `INITIATED` to `PAID`, stamps `paid_at` with the logical clock's
        current instant, and subtracts the amount from the producer's
        balance."
        PRD §2.9: "4. **State admissibility** — the target resource is in a
        state that allows the operation, and the optimistic-concurrency check
        of §2.7 passes, else `ERR_INVALID_STATE` or `ERR_STALE_VERSION`.
        Terminal-state lockdowns, such as paying or reversing an already
        `PAID` invoice, fail here."

        Design: Corner/state_machines/mark_paid_twice_returns_409
        """
        bundle, payout = self._setup_paid_payout()
        assert payout["status"] == "PAID"
        res = api_client.mark_payout_paid(payout["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        # 1200000 - 400000 debited exactly once.
        assert (
            get_producer(bundle["producer"]["id"])["commission_balance_cents"]
            == 800000
        )

    def test_computed_balance_read_after_mark_paid(self):
        """PRD §3.8: "A producer's `commission_balance_cents` is the
        earned-but-unpaid ledger position: the sum of `amount_cents` over
        every commission entry — of any entry type — for which the producer
        is the recipient and the status is `EXPECTED` or `MATCHED`, minus the
        sum of `amount_cents` over the producer's payouts already in `PAID`
        status."
        PRD §3.8: "then moves the payout from `INITIATED` to `PAID`, stamps
        `paid_at` with the logical clock's current instant, and subtracts the
        amount from the producer's balance."

        Design: Corner/endpoints/computed_read_matches_calculation
        """
        bundle = setup_bound_policy(
            premium_annual_cents=2400000,
            commission_rate_bps=5000,
            policy_number="P-E1E",
            producer_overrides={"tax_form_on_file": True},
        )
        assert (
            get_producer(bundle["producer"]["id"])["commission_balance_cents"]
            == 1200000
        )
        payout = create_payout_fresh_version(bundle["producer"]["id"], 400000)
        validate_success(api_client.mark_payout_paid(payout["id"], ADMIN), 200)
        after = get_producer(bundle["producer"]["id"])
        assert after["commission_balance_cents"] == 800000, (
            "the read immediately after mark-paid must reflect the debit"
        )


class TestPayoutOcc:
    def test_stale_producer_version_rejected(self):
        """PRD §2.7: "Creating a producer payout requires the request to
        carry `expected_producer_version`, holding the client last-observed
        `version` of the producer. Because any successful payout creation,
        and any cascade such as chargeback-driven suspension, legitimately
        advances the producer's `version`, a stale value means the client's
        view of `commission_balance_cents` is no longer current; the create
        is likewise rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_payout_create_stale_version
        """
        bundle = setup_bound_policy(
            premium_annual_cents=2400000,
            commission_rate_bps=5000,
            policy_number="P-O2",
            producer_overrides={"tax_form_on_file": True},
        )
        observed = fresh_producer_version(bundle["producer"]["id"])
        first = validate_success(
            api_client.create_payout(
                bundle["producer"]["id"],
                {"amount_cents": 100000, "expected_producer_version": observed},
                ADMIN,
            ),
            201,
        )
        assert first["status"] == "INITIATED"

        res = api_client.create_payout(
            bundle["producer"]["id"],
            {"amount_cents": 100000, "expected_producer_version": observed},
            ADMIN,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    def test_payout_create_increments_producer_version_by_one(self):
        """PRD §3.8: "A created payout starts in `INITIATED` status, and its
        creation advances the producer's `version` by one."
        PRD §2.5: "`version` (integer): a system-managed integer that
        increments by one on every mutation of the resource and backs the
        optimistic concurrency rules in §2.7."

        Design: Corner/cross_cutting_layers/version_increments_on_mutation
        """
        bundle = setup_bound_policy(
            premium_annual_cents=2400000,
            commission_rate_bps=5000,
            policy_number="P-O3",
            producer_overrides={"tax_form_on_file": True},
        )
        before = fresh_producer_version(bundle["producer"]["id"])
        validate_success(
            api_client.create_payout(
                bundle["producer"]["id"],
                {"amount_cents": 100000, "expected_producer_version": before},
                ADMIN,
            ),
            201,
        )
        after = fresh_producer_version(bundle["producer"]["id"])
        assert after == before + 1
