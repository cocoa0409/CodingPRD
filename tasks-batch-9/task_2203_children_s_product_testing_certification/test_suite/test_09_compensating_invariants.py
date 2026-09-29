"""Three conserved quantities driven forward and then compensated back."""

from test_helpers import (
    ApiErrorId,
    factories,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import COORDINATOR_HEADERS


FLAT_CATEGORY = {"durable_infant_product": False, "sampling_floor_units": 1}

LEAD_RULE = {
    "hazard_class": "LEAD_CONTENT",
    "severity_weight": 9,
    "limit_value": 100,
    "limit_unit": "PPM",
    "base_method_fee_cents": 18700,
}

WINDOW_TWO_UNIT = ("2026-08-02T00:00:00Z", "2026-08-03T00:00:00Z")
WINDOW_THREE_UNIT = ("2026-08-04T00:00:00Z", "2026-08-05T00:00:00Z")
WINDOW_SPARE = ("2026-08-06T00:00:00Z", "2026-08-07T00:00:00Z")


def _order_payload(env, sample_count, window):
    return factories.test_order_payload(
        env["product"]["id"],
        env["plan"]["id"],
        env["laboratory"]["id"],
        env["rules"][0]["id"],
        sample_count=sample_count,
        window_start=window[0],
        window_end=window[1],
    )


def _six_unit_plan_env(api):
    """A six-unit plan at a four-slot laboratory with a zero-surcharge accreditation."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    env = fx.booking_env(
        api,
        rule_specs=[dict(LEAD_RULE)],
        category=dict(FLAT_CATEGORY),
        product={"projected_annual_units": 6000},
        laboratory={"independence_class": "INDEPENDENT", "concurrent_slot_capacity": 4},
        accreditation_overrides=[{"fee_surcharge_basis_points": 0}],
        plan_overrides={"plan_type": "INITIAL"},
    )
    assert env["plan"]["units_authorized"] == 6
    return env


def _partially_committed_env(api):
    """Five of six authorised units committed across a two-unit and a three-unit order."""
    env = _six_unit_plan_env(api)
    env["order_two_unit"] = validate_success(
        api.create_test_order(
            _order_payload(env, 2, WINDOW_TWO_UNIT), headers=COORDINATOR_HEADERS
        ),
        201,
    )
    env["order_three_unit"] = validate_success(
        api.create_test_order(
            _order_payload(env, 3, WINDOW_THREE_UNIT), headers=COORDINATOR_HEADERS
        ),
        201,
    )
    return env


class TestSampleUnitLedger:
    """units_committed plus units_available never leaves units_authorized."""

    def test_a_rejected_over_booking_commits_nothing(self, api):
        """PRD 2.8: "The invariant is that `units_committed` plus `units_available` equals
        `units_authorized` at all times, and it must hold identically before an order is
        booked and after that same order is cancelled — cancellation returns exactly the
        units the booking took, with no drift."

        Design: Difficulty/compensating_invariant/compensating_invariant_sample_unit_ledger_survives_exhaustion_rejection_and_cancellation
        """
        env = _partially_committed_env(api)
        before = fx.get_plan(api, env["plan"]["id"])
        assert before["units_authorized"] == 6
        assert before["units_committed"] == 5
        assert before["units_available"] == 1

        validate_error(
            api.create_test_order(
                _order_payload(env, 2, WINDOW_SPARE), headers=COORDINATOR_HEADERS
            ),
            ApiErrorId.SAMPLE_UNITS_EXHAUSTED.value,
            422,
        )
        after = fx.get_plan(api, env["plan"]["id"])
        assert after["units_committed"] == 5
        assert after["units_available"] == 1
        assert after["units_authorized"] == 6

    def test_cancellation_returns_exactly_the_units_the_booking_took(self, api):
        """PRD 3.6: "Cancellation returns the order's `sample_count` from the plan's
        `units_committed` to its `units_available`, restoring the sample-unit invariant,
        and adds the order's `invoice_total_cents` to the laboratory's
        `credited_fee_cents_total`, restoring the fee invariant to exactly its pre-booking
        value."

        Design: Difficulty/compensating_invariant/compensating_invariant_sample_unit_ledger_survives_exhaustion_rejection_and_cancellation
        """
        env = _partially_committed_env(api)
        api.create_test_order(
            _order_payload(env, 2, WINDOW_SPARE), headers=COORDINATOR_HEADERS
        )
        validate_success(
            api.cancel_test_order(env["order_three_unit"]["id"], headers=COORDINATOR_HEADERS),
            200,
        )
        freed = fx.get_plan(api, env["plan"]["id"])
        assert freed["units_committed"] == 2
        assert freed["units_available"] == 4
        assert freed["units_authorized"] == 6

        rebooked = validate_success(
            api.create_test_order(
                _order_payload(env, 2, WINDOW_SPARE), headers=COORDINATOR_HEADERS
            ),
            201,
        )
        rebalanced = fx.get_plan(api, env["plan"]["id"])
        assert rebalanced["units_committed"] == 4
        assert rebalanced["units_available"] == 2
        assert rebalanced["units_authorized"] == 6
        env["order_rebooked"] = rebooked

    def test_cancelling_everything_restores_the_pre_booking_split(self, api):
        """PRD 2.8: "The invariant is that `units_committed` plus `units_available` equals
        `units_authorized` at all times, and it must hold identically before an order is
        booked and after that same order is cancelled — cancellation returns exactly the
        units the booking took, with no drift."

        Design: Difficulty/compensating_invariant/compensating_invariant_sample_unit_ledger_survives_exhaustion_rejection_and_cancellation
        """
        env = _partially_committed_env(api)
        api.create_test_order(
            _order_payload(env, 2, WINDOW_SPARE), headers=COORDINATOR_HEADERS
        )
        api.cancel_test_order(env["order_three_unit"]["id"], headers=COORDINATOR_HEADERS)
        rebooked = validate_success(
            api.create_test_order(
                _order_payload(env, 2, WINDOW_SPARE), headers=COORDINATOR_HEADERS
            ),
            201,
        )
        api.cancel_test_order(env["order_two_unit"]["id"], headers=COORDINATOR_HEADERS)
        api.cancel_test_order(rebooked["id"], headers=COORDINATOR_HEADERS)

        plan = fx.get_plan(api, env["plan"]["id"])
        assert plan["units_committed"] == 0
        assert plan["units_available"] == 6
        assert plan["units_authorized"] == 6

        _, meta = validate_paginated(
            api.list_test_orders(
                params={"sampling_plan_id": env["plan"]["id"]}, headers=COORDINATOR_HEADERS
            )
        )
        assert meta["total_count"] == 3


def _furnished_batches_env(api):
    """An issued and furnished certificate over held batches of 300 and 200 units."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    env = fx.certified_env(
        api,
        rule_specs=[dict(LEAD_RULE)],
        category=dict(FLAT_CATEGORY),
        product={"projected_annual_units": 2000},
        laboratory={"independence_class": "INDEPENDENT", "concurrent_slot_capacity": 4},
        measured_value=40,
        certificate_overrides={"manufacture_date_month": "2026-08"},
    )
    fx.furnish_certificate(api, env["certificate"]["id"])
    batches = [
        fx.create_batch(
            api,
            env["product"]["id"],
            env["certificate"]["id"],
            batch_code=code,
            produced_on="2026-08-01T00:00:00Z",
            quantity=quantity,
        )
        for code, quantity in (("RVR090-000101", 300), ("RVR090-000102", 200))
    ]
    env["first_batch"], env["second_batch"] = batches
    return env


class TestDistributionUnitLedger:
    """The four product buckets always re-sum to every batch quantity produced."""

    def test_release_and_rescind_return_the_ledger_to_its_starting_split(self, api):
        """PRD 2.8: "It must hold identically before a batch is released and after the
        release is rescinded, since rescission moves the same quantity back to the counter
        it came from."

        Design: Difficulty/compensating_invariant/compensating_invariant_distribution_unit_ledger_restored_by_repeated_release_and_rescind_cycles
        """
        env = _furnished_batches_env(api)
        before = fx.get_summary(api, env["product"]["id"])
        assert before["units_total_produced"] == 500
        assert before["units_held"] == 500
        assert before["units_released"] == 0
        assert before["units_stopped"] == 0
        assert before["units_destroyed"] == 0
        assert before["ledger_balanced"] is True

        released = fx.release_batch(api, env["first_batch"]["id"])
        assert released["released_at"] == "2026-08-01T00:00:00Z"
        moved = fx.get_summary(api, env["product"]["id"])
        assert moved["units_held"] == 200
        assert moved["units_released"] == 300

        rescinded = fx.rescind_release(api, env["first_batch"]["id"])
        assert rescinded["distribution_state"] == "HELD"
        assert rescinded["release_rescind_count"] == 1
        assert rescinded["released_at"] is None
        restored = fx.get_summary(api, env["product"]["id"])
        assert restored["units_held"] == 500
        assert restored["units_released"] == 0
        assert restored["ledger_balanced"] is True

    def test_a_second_cycle_advances_only_the_rescind_counter(self, api):
        """PRD 3.8: "Rescinding a release moves the batch `RELEASED → HELD`, moves the
        same `quantity` from the product's `units_released` back to `units_held`, clears
        `released_at` to null, increments `release_rescind_count` by 1, and increments both
        the batch's and the product's `version` by 1."

        Design: Difficulty/compensating_invariant/compensating_invariant_distribution_unit_ledger_restored_by_repeated_release_and_rescind_cycles
        """
        env = _furnished_batches_env(api)
        fx.release_batch(api, env["first_batch"]["id"])
        fx.rescind_release(api, env["first_batch"]["id"])

        second_release = fx.release_batch(api, env["first_batch"]["id"])
        assert second_release["released_at"] == "2026-08-01T00:00:00Z"
        second_rescind = fx.rescind_release(api, env["first_batch"]["id"])
        assert second_rescind["release_rescind_count"] == 2
        assert second_rescind["released_at"] is None

        summary = fx.get_summary(api, env["product"]["id"])
        assert summary["units_held"] == 500
        assert summary["units_released"] == 0
        assert summary["ledger_balanced"] is True

    def test_the_conserved_total_grows_with_every_new_batch(self, api):
        """PRD 2.8: "The invariant is that the sum of those four counters equals the total
        `quantity` produced across every batch of the product, with no status filter
        applied to that total."

        Design: Difficulty/compensating_invariant/compensating_invariant_distribution_unit_ledger_restored_by_repeated_release_and_rescind_cycles
        """
        env = _furnished_batches_env(api)
        fx.release_batch(api, env["first_batch"]["id"])
        fx.rescind_release(api, env["first_batch"]["id"])

        third = fx.create_batch(
            api,
            env["product"]["id"],
            env["certificate"]["id"],
            batch_code="RVR090-000103",
            produced_on="2026-08-07T00:00:00Z",
            quantity=150,
        )
        grown = fx.get_summary(api, env["product"]["id"])
        assert grown["units_total_produced"] == 650
        assert grown["units_held"] == 650
        assert grown["ledger_balanced"] is True

        fx.release_batch(api, env["second_batch"]["id"])
        fx.release_batch(api, third["id"])
        final = fx.get_summary(api, env["product"]["id"])
        assert final["units_held"] == 300
        assert final["units_released"] == 350
        assert final["units_stopped"] == 0
        assert final["units_destroyed"] == 0
        assert final["units_total_produced"] == 650
        assert final["ledger_balanced"] is True


class TestLaboratoryFeeLedger:
    """Crediting a cancellation never rewrites the billed accumulator."""

    def test_two_bookings_bill_their_own_invoice_totals(self, api):
        """PRD 3.6: "And the order's `invoice_total_cents` is added to the laboratory's
        `billed_fee_cents_total` at creation — every order is billed the moment it is
        booked, which is why a `SCHEDULED` order already counts toward the laboratory's
        outstanding balance."

        Design: Difficulty/compensating_invariant/compensating_invariant_laboratory_fee_ledger_credits_without_rewriting_billed_total
        """
        env = _partially_committed_env(api)
        assert env["order_two_unit"]["invoice_total_cents"] == 37400
        assert env["order_three_unit"]["invoice_total_cents"] == 56100

        laboratory = fx.get_laboratory(api, env["laboratory"]["id"])
        assert laboratory["billed_fee_cents_total"] == 93500
        assert laboratory["credited_fee_cents_total"] == 0

    def test_cancellation_credits_the_cancelled_order_s_own_amount(self, api):
        """PRD 2.8: "The invariant is that `billed_fee_cents_total` minus
        `credited_fee_cents_total` equals that outstanding balance. Every order is billed
        at creation, and cancellation or invalidation credits back the exact
        `invoice_total_cents` that was billed, so the difference returns to its pre-billing
        value with zero drift."

        Design: Difficulty/compensating_invariant/compensating_invariant_laboratory_fee_ledger_credits_without_rewriting_billed_total
        """
        env = _partially_committed_env(api)
        validate_success(
            api.cancel_test_order(env["order_three_unit"]["id"], headers=COORDINATOR_HEADERS),
            200,
        )
        laboratory = fx.get_laboratory(api, env["laboratory"]["id"])
        assert laboratory["credited_fee_cents_total"] == 56100
        assert laboratory["credited_fee_cents_total"] != 37400
        assert laboratory["billed_fee_cents_total"] == 93500
        assert (
            laboratory["billed_fee_cents_total"] - laboratory["credited_fee_cents_total"]
        ) == 37400

    def test_completing_the_remaining_work_is_not_a_ledger_event(self, api):
        """PRD 3.6: "No further billing occurs at this point, since the fee was taken at
        booking."

        Design: Difficulty/compensating_invariant/compensating_invariant_laboratory_fee_ledger_credits_without_rewriting_billed_total
        """
        env = _partially_committed_env(api)
        api.cancel_test_order(env["order_three_unit"]["id"], headers=COORDINATOR_HEADERS)
        lab_id = env["laboratory"]["id"]

        fx.start_order(api, env["order_two_unit"]["id"], lab_id)
        after_start = fx.get_laboratory(api, lab_id)
        assert after_start["billed_fee_cents_total"] == 93500
        assert after_start["credited_fee_cents_total"] == 56100

        reported = fx.report(api, env["order_two_unit"]["id"], lab_id, 40)
        assert reported["result"] == "PASS"
        after_report = fx.get_laboratory(api, lab_id)
        assert after_report["billed_fee_cents_total"] == 93500
        assert after_report["credited_fee_cents_total"] == 56100

        product = fx.get_product(api, env["product"]["id"])
        assert product["testing_budget_cents"] == 2000000
