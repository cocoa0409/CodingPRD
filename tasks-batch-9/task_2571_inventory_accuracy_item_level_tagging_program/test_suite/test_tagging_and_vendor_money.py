"""
The tag-batch rework loop and the vendor money ledger.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CHARGEBACK_ALREADY_ISSUED,
    ERR_CREDIT_EXCEEDS_BALANCE,
    ERR_REWORK_LIMIT_REACHED,
)
from test_helpers.assertions import (
    assert_tag_batch_counters_cleared,
    assert_vendor_ledger_identity,
)
from test_helpers.test_users import CONTROLLER, SUPERVISOR


class TestTagBatchReworkLoop:
    def test_a_failed_read_rate_blocks_the_position_and_penalises_the_vendor(self, api):
        """
        The failure cascade runs four hops.

        "On a failure the cascade runs four hops. First, the sample is stored,
        `read_rate_bps` is computed, `verification_outcome` becomes `FAIL`, and the
        batch moves from `RECEIVED` to `VERIFICATION_FAILED`; at the same time the
        vendor's `tag_compliance_score_bps` falls by 1500 basis points but never
        below 0, and `required_verification_sample_pct` is re-derived from the
        reduced score."

        Design: Difficulty/non_linear_state_machine/tag_batch_rework_cycle_returns_to_encoded
        """
        world = fx.encoded_tag_batch_world(api, quantity=1000, baseline=100)
        assert world["encoded_batch"]["required_sample_units"] == 50

        failed = validate_success(
            api.verify_tag_batch(
                world["batch_id"],
                f.verify_payload(sampled_units=50, readable_units=48),
                world["store_headers"],
            )
        )
        assert failed["read_rate_bps"] == 9600
        assert failed["verification_outcome"] == "FAIL"
        assert failed["status"] == "VERIFICATION_FAILED"

        vendor = fx.read_vendor(api, world["vendor_id"])
        assert vendor["tag_compliance_score_bps"] == 8500
        assert vendor["required_verification_sample_pct"] == 10

        position = fx.read_position(api, world["position_id"])
        assert position["tag_integrity_hold"] is True
        assert position["promising_state"] == "BLOCKED"

    def test_rework_returns_the_batch_to_encoded_with_a_larger_obligation(self, api):
        """
        Rework re-freezes the sample from the already-penalised band.

        "A `VendorRep` or `InventorySupervisor` may send it back for re-encoding,
        which returns it from `VERIFICATION_FAILED` to `ENCODED`, increments
        `rework_round` by 1, resets `sampled_units`, `readable_units`,
        `duplicate_epc_count`, `unencoded_units` and `read_rate_bps` to 0 and
        `verification_outcome` to null, and re-freezes `required_sample_units` from
        the vendor's current — that is, already penalised — band."

        Design: Difficulty/non_linear_state_machine/tag_batch_rework_cycle_returns_to_encoded
        """
        world = fx.failed_verification_world(api, sampled=50, readable=48)

        reworked = validate_success(api.rework_tag_batch(world["batch_id"], SUPERVISOR))
        assert reworked["status"] == "ENCODED"
        assert reworked["rework_round"] == 1
        assert reworked["required_sample_units"] == 100
        assert reworked["verification_outcome"] is None
        assert_tag_batch_counters_cleared(reworked)

        held = fx.read_position(api, world["position_id"])
        assert held["tag_integrity_hold"] is True
        assert held["promising_state"] == "BLOCKED"

    def test_the_third_rework_attempt_is_refused(self, api):
        """
        The loop may be traversed at most twice.

        "Rework is permitted only while `rework_round` is strictly below 2; a third
        attempt is rejected with `ERR_REWORK_LIMIT_REACHED`."

        Design: Difficulty/non_linear_state_machine/tag_batch_rework_cycle_returns_to_encoded
        """
        world = fx.failed_verification_world(api, sampled=50, readable=48)

        first_rework = validate_success(
            api.rework_tag_batch(world["batch_id"], SUPERVISOR)
        )
        assert first_rework["rework_round"] == 1
        get_success_data(api.receive_tag_batch(world["batch_id"], world["store_headers"]))
        second_failure = validate_success(
            api.verify_tag_batch(
                world["batch_id"],
                f.verify_payload(sampled_units=100, readable_units=96),
                world["store_headers"],
            )
        )
        assert second_failure["read_rate_bps"] == 9600
        assert second_failure["status"] == "VERIFICATION_FAILED"
        assert fx.read_vendor(api, world["vendor_id"])["required_verification_sample_pct"] == 20

        second_rework = validate_success(
            api.rework_tag_batch(world["batch_id"], SUPERVISOR)
        )
        assert second_rework["rework_round"] == 2
        assert second_rework["required_sample_units"] == 200
        get_success_data(api.receive_tag_batch(world["batch_id"], world["store_headers"]))
        validate_success(
            api.verify_tag_batch(
                world["batch_id"],
                f.verify_payload(sampled_units=200, readable_units=192),
                world["store_headers"],
            )
        )

        validate_error(
            api.rework_tag_batch(world["batch_id"], SUPERVISOR),
            ERR_REWORK_LIMIT_REACHED,
            409,
        )
        assert fx.read_tag_batch(api, world["batch_id"])["rework_round"] == 2


class TestChargebackTierKeying:
    def test_the_credit_rate_is_keyed_on_the_gross_tier(self, api):
        """
        Re-tiering off the net is forbidden.

        "A gross shortage of 205000 cents falls in `TIER_3`, so the rate is 10000
        basis points and `chargeback_gross_cents` is 205000. Keyed correctly on the
        gross tier, the credit rate is 500 basis points, `vendor_credit_cents` is
        10250 and `net_chargeback_cents` is 194750."

        Design: Difficulty/combinatorial_formula/vendor_chargeback_gross_tier_pins_credit
        """
        world = fx.vendor_shortage_world(api, counted_units=141, baseline=100)

        issued = get_success_data(
            api.create_chargeback(
                world["vendor_id"],
                f.chargeback_payload(world["shrink_period_id"]),
                CONTROLLER,
            )
        )
        assert issued["vendor_id"] == world["vendor_id"]
        assert issued["shrink_period_id"] == world["shrink_period_id"]
        assert issued["attributable_shortage_cents"] == 205000
        assert issued["tier"] == "TIER_3"
        assert issued["chargeback_gross_cents"] == 205000
        assert issued["vendor_credit_cents"] == 10250
        assert issued["net_chargeback_cents"] == 194750
        assert issued["vendor_credit_cents"] != 20500
        assert issued["net_chargeback_cents"] != 184500

    def test_the_vendor_ledger_and_the_period_record_the_charge(self, api):
        """
        Step five writes the ledger and marks the period.

        "Step five writes the vendor ledger: `lifetime_chargeback_gross_cents`
        grows by `chargeback_gross_cents`, `credited_cents` grows by
        `vendor_credit_cents`, `chargeback_balance_cents` is re-derived as
        `lifetime_chargeback_gross_cents` minus `credited_cents`, and the vendor is
        appended to the period's `chargeback_issued_vendor_ids`."

        Design: Difficulty/combinatorial_formula/vendor_chargeback_gross_tier_pins_credit
        """
        world = fx.vendor_shortage_world(api, counted_units=141, baseline=100)
        issued = get_success_data(
            api.create_chargeback(
                world["vendor_id"],
                f.chargeback_payload(world["shrink_period_id"]),
                CONTROLLER,
            )
        )
        assert issued["lifetime_chargeback_gross_cents"] == 205000
        assert issued["credited_cents"] == 10250
        assert issued["chargeback_balance_cents"] == 194750

        vendor = fx.read_vendor(api, world["vendor_id"])
        assert vendor["lifetime_chargeback_gross_cents"] == 205000
        assert vendor["credited_cents"] == 10250
        assert vendor["chargeback_balance_cents"] == 194750
        assert_vendor_ledger_identity(vendor)

        period = validate_success(
            api.get_shrink_period(world["shrink_period_id"], CONTROLLER)
        )
        assert world["vendor_id"] in period["chargeback_issued_vendor_ids"]


class TestCreditConservesGross:
    def test_a_credit_grows_credited_cents_and_never_the_gross(self, api):
        """
        Gross is add-only.

        "`lifetime_chargeback_gross_cents` is never rewritten by a credit, which is
        what keeps the money invariant of §2.10 intact."

        Design: Difficulty/compensating_invariant/vendor_chargeback_credit_conserves_gross
        """
        world = fx.chargeback_issued_world(api)

        granted = get_success_data(
            api.create_chargeback_credit(
                world["vendor_id"], f.chargeback_credit_payload(4750), CONTROLLER
            )
        )
        assert granted["credit_cents"] == 4750
        assert granted["lifetime_chargeback_gross_cents"] == 205000
        assert granted["credited_cents"] == 15000
        assert granted["chargeback_balance_cents"] == 190000

        vendor = fx.read_vendor(api, world["vendor_id"])
        assert vendor["lifetime_chargeback_gross_cents"] == 205000
        assert vendor["credited_cents"] == 15000
        assert vendor["chargeback_balance_cents"] == 190000
        assert_vendor_ledger_identity(vendor)

    def test_a_credit_one_cent_above_the_balance_is_rejected(self, api):
        """
        The balance may never go negative.

        "The credit may not exceed the vendor's current
        `chargeback_balance_cents`; an excess is rejected with
        `ERR_CREDIT_EXCEEDS_BALANCE`, and a credit exactly equal to the balance is
        allowed and drives it to 0."

        Design: Difficulty/compensating_invariant/vendor_chargeback_credit_conserves_gross
        """
        world = fx.chargeback_issued_world(api)
        get_success_data(
            api.create_chargeback_credit(
                world["vendor_id"], f.chargeback_credit_payload(4750), CONTROLLER
            )
        )

        validate_error(
            api.create_chargeback_credit(
                world["vendor_id"], f.chargeback_credit_payload(190001), CONTROLLER
            ),
            ERR_CREDIT_EXCEEDS_BALANCE,
            422,
        )

        untouched = fx.read_vendor(api, world["vendor_id"])
        assert untouched["lifetime_chargeback_gross_cents"] == 205000
        assert untouched["credited_cents"] == 15000
        assert untouched["chargeback_balance_cents"] == 190000

        exact = get_success_data(
            api.create_chargeback_credit(
                world["vendor_id"], f.chargeback_credit_payload(190000), CONTROLLER
            )
        )
        assert exact["lifetime_chargeback_gross_cents"] == 205000
        assert exact["credited_cents"] == 205000
        assert exact["chargeback_balance_cents"] == 0

        validate_error(
            api.create_chargeback_credit(
                world["vendor_id"], f.chargeback_credit_payload(1), CONTROLLER
            ),
            ERR_CREDIT_EXCEEDS_BALANCE,
            422,
        )
        assert fx.read_vendor(api, world["vendor_id"])["chargeback_balance_cents"] == 0

    def test_the_same_period_may_not_charge_the_same_vendor_twice(self, api):
        """
        One charge per vendor per period.

        "A vendor may be charged out of a given period only once: if the vendor
        already appears in that period's `chargeback_issued_vendor_ids`, the
        request is rejected with `ERR_CHARGEBACK_ALREADY_ISSUED`."

        Design: Difficulty/compensating_invariant/vendor_chargeback_credit_conserves_gross
        """
        world = fx.chargeback_issued_world(api)

        validate_error(
            api.create_chargeback(
                world["vendor_id"],
                f.chargeback_payload(world["shrink_period_id"]),
                CONTROLLER,
            ),
            ERR_CHARGEBACK_ALREADY_ISSUED,
            409,
        )

        vendor = fx.read_vendor(api, world["vendor_id"])
        assert vendor["lifetime_chargeback_gross_cents"] == 205000
        assert vendor["credited_cents"] == 10250
        assert vendor["chargeback_balance_cents"] == 194750
        assert vendor["shortage_event_count"] == 1
