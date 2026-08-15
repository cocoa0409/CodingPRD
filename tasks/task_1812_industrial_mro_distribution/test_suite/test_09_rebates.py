"""National-account rebates: accrual cascade, true-up variants, windows, lifecycle."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    complete_order,
    confirm_order,
    create_active_rebate_agreement,
    create_branch,
    create_customer,
    create_item,
    create_national_customer,
    create_rebate_agreement,
    get_customer,
    get_rebate_agreement,
    mark_fulfilled,
    mark_ready,
    place_order,
    restock,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]

TWO_TIERS = [
    {"threshold_cents": 0, "rebate_bps": 100},
    {"threshold_cents": 10000000, "rebate_bps": 200},
]


def _national_with_agreement(api, account_number, tiers=None):
    """National-account customer (credit 100,000,000) with an ACTIVE agreement
    over the closed period [2026-07-01, 2026-09-30]."""
    customer = create_national_customer(
        account_number=account_number, credit_limit_cents=100000000,
        primary_ship_to_state="OH",
    )
    agreement = create_active_rebate_agreement(
        customer["id"],
        period_start="2026-07-01",
        period_end="2026-09-30",
        tiers=tiers if tiers is not None else TWO_TIERS,
    )
    return customer, agreement


def _complete_will_call_order(api, customer_id, branch_id, item_id, qty=1):
    order = place_order(
        customer_id, branch_id, [{"item_id": item_id, "qty": qty}]
    )
    confirm_order(order["id"])
    mark_ready(order["id"])
    mark_fulfilled(order["id"])
    return complete_order(order["id"])


class TestRebateProvisionalAverageVsFinalMarginal:
    def _setup(self, api):
        """ACTIVE agreement tiers [{0,100bps},{10M,200bps}]; one WILL_CALL order
        of a 15,000,000-cent STOCKED item completed on the default clock."""
        customer, agreement = _national_with_agreement(api, "NAT-1")
        item = create_item(sku="BIG-1", list_price_cents=15000000)
        branch = create_branch(location_code="BR-1")
        restock(branch["id"], item["id"], 1)
        _complete_will_call_order(
            api, customer["id"], branch["id"], item["id"]
        )
        return customer, agreement

    def test_provisional_uses_average_rate_at_reached_tier(self, api,
                                                           admin_headers):
        """PRD §3.9: "After each movement the agreement re-evaluates
        `current_tier_index` as the highest tier whose `threshold_cents` is less
        than or equal to the accrued figure — spend exactly equal to a threshold
        reaches that tier — and recomputes the provisional rebate on an
        average-rate basis: `accrued_spend_cents` multiplied by the reached
        tier's `rebate_bps`, divided by ten thousand, rounded half up to the cent,
        with the reached tier's rate applied to the entire accrued spend."

        Design: Difficulty/dual_variant_calc/rebate_provisional_average_vs_final_marginal
        """
        _customer, agreement = self._setup(api)
        current = get_rebate_agreement(agreement["id"])
        assert current["accrued_spend_cents"] == 15000000
        assert current["current_tier_index"] == 1
        assert current["provisional_rebate_cents"] == 300000

    def test_close_computes_marginal_bands_and_clawback(self, api, admin_headers):
        """PRD §3.9: "Consider an agreement whose tiers grant 100 basis points
        from zero and 200 basis points from 10,000,000 cents: with 15,000,000
        cents accrued, the provisional average-rate figure stands at 300,000 cents
        while the final marginal figure is 200,000 cents, producing a true-up of
        negative 100,000 cents."

        Design: Difficulty/dual_variant_calc/rebate_provisional_average_vs_final_marginal
        """
        _customer, agreement = self._setup(api)
        set_clock("2026-10-01T00:00:00Z")
        closed = validate_success(
            api.close_rebate_agreement(agreement["id"], admin_headers)
        )
        assert closed["status"] == "CLOSED"
        assert closed["final_rebate_cents"] == 200000
        assert closed["true_up_delta_cents"] == -100000


class TestRebateTierThresholdExactEquality:
    def _setup(self, api):
        """ACTIVE agreement tiers [{0,100bps},{10M,200bps}]; one WILL_CALL order
        of a 10,000,000-cent STOCKED item completed -> accrued exactly 10M."""
        customer, agreement = _national_with_agreement(api, "NAT-3")
        item = create_item(sku="TIER-10M", list_price_cents=10000000)
        branch = create_branch(location_code="BR-12")
        restock(branch["id"], item["id"], 1)
        _complete_will_call_order(
            api, customer["id"], branch["id"], item["id"]
        )
        return customer, agreement

    def test_exact_threshold_spend_reaches_tier(self, api, admin_headers):
        """PRD §3.9: "the agreement re-evaluates `current_tier_index` as the
        highest tier whose `threshold_cents` is less than or equal to the accrued
        figure — spend exactly equal to a threshold reaches that tier"

        Design: Difficulty/boundary_precision_check/rebate_tier_threshold_exact_equality
        """
        _customer, agreement = self._setup(api)
        current = get_rebate_agreement(agreement["id"])
        assert current["accrued_spend_cents"] == 10000000
        assert current["current_tier_index"] == 1
        assert current["provisional_rebate_cents"] == 200000

    def test_close_with_empty_upper_band(self, api, admin_headers):
        """PRD §3.9: "for every tier, the band is the portion of
        `accrued_spend_cents` lying between that tier's threshold and the next
        tier's threshold, unbounded for the top tier and never below zero, and
        `final_rebate_cents` is the sum over tiers of each band times its tier's
        basis points divided by ten thousand, with a single round half up at the
        end."

        Design: Difficulty/boundary_precision_check/rebate_tier_threshold_exact_equality
        """
        _customer, agreement = self._setup(api)
        set_clock("2026-10-01T00:00:00Z")
        closed = validate_success(
            api.close_rebate_agreement(agreement["id"], admin_headers)
        )
        # 10,000,000 * 100bps + 0 * 200bps = 100,000
        assert closed["final_rebate_cents"] == 100000
        assert closed["true_up_delta_cents"] == -100000


class TestCompletionAccrualCascade:
    def _setup(self, api):
        """ACTIVE agreement tiers [{0,100bps},{10M,200bps}]; STOCKED item list
        6,000,000 with 2 on hand; order 1 completed; order 2 fulfilled, awaiting
        completion."""
        customer, agreement = _national_with_agreement(api, "NAT-2")
        item = create_item(sku="AC-6M", list_price_cents=6000000)
        branch = create_branch(location_code="BR-7")
        restock(branch["id"], item["id"], 2)
        _complete_will_call_order(api, customer["id"], branch["id"], item["id"])
        return customer, agreement, item, branch

    def test_first_completion_accrues_below_threshold(self, api, admin_headers):
        """PRD §3.9: "While `ACTIVE`, every order completion dated inside the
        period adds that order's `total_cents` to `accrued_spend_cents`"
        PRD §3.9: "recomputes the provisional rebate on an average-rate basis:
        `accrued_spend_cents` multiplied by the reached tier's `rebate_bps`,
        divided by ten thousand, rounded half up to the cent"

        Design: Difficulty/transitive_cascade/completion_accrual_cascade
        """
        _customer, agreement, _item, _branch = self._setup(api)
        current = get_rebate_agreement(agreement["id"])
        assert current["accrued_spend_cents"] == 6000000
        assert current["current_tier_index"] == 0
        assert current["provisional_rebate_cents"] == 60000

    def test_second_completion_crosses_tier_and_recomputes(self, api,
                                                           admin_headers):
        """PRD §3.7: "Completion moves the order to `COMPLETED`, stamps
        `completed_at`, credits the account's `net_spend_cents` with the order's
        `total_cents`, releases the same amount from
        `open_credit_exposure_cents`, and fires the rebate accrual cascade of
        §3.9 against the completion date."

        Design: Difficulty/transitive_cascade/completion_accrual_cascade
        """
        customer, agreement, item, branch = self._setup(api)
        _complete_will_call_order(api, customer["id"], branch["id"], item["id"])

        account = get_customer(customer["id"])
        assert account["net_spend_cents"] == 12000000

        current = get_rebate_agreement(agreement["id"])
        assert current["accrued_spend_cents"] == 12000000
        assert current["current_tier_index"] == 1
        assert current["provisional_rebate_cents"] == 240000


class TestRebateAgreementClosedIntervalOverlap:
    def _setup(self, api):
        customer = create_national_customer(
            account_number="NAT-4", credit_limit_cents=1000000,
            primary_ship_to_state="OH",
        )
        first = create_rebate_agreement(
            customer["id"], period_start="2026-01-01", period_end="2026-03-31",
            tiers=[{"threshold_cents": 0, "rebate_bps": 100}],
        )
        return customer, first

    def test_agreement_starting_day_after_period_end_allowed(self, api,
                                                             admin_headers):
        """PRD §3.9: "a new agreement whose period shares even a single day with
        another agreement of the same customer is rejected with
        `ERR_AGREEMENT_WINDOW_OVERLAP`, so a `period_start` equal to an existing
        agreement's `period_end` still overlaps, while starting the day after is
        allowed."

        Design: Difficulty/resource_temporal_overlap/rebate_agreement_closed_interval_overlap
        """
        customer, first = self._setup(api)
        assert first["status"] == "DRAFT"
        second = validate_success(
            api.create_rebate_agreement(
                customer["id"],
                {
                    "period_start": "2026-04-01",
                    "period_end": "2026-06-30",
                    "tiers": [{"threshold_cents": 0, "rebate_bps": 100}],
                },
                admin_headers,
            ),
            201,
        )
        assert second["status"] == "DRAFT"

    def test_agreement_sharing_period_end_day_rejected(self, api, admin_headers):
        """PRD §3.9: "Closed intervals make adjacency impossible: a new agreement
        whose period shares even a single day with another agreement of the same
        customer is rejected with `ERR_AGREEMENT_WINDOW_OVERLAP`"

        Design: Difficulty/resource_temporal_overlap/rebate_agreement_closed_interval_overlap
        """
        customer, _first = self._setup(api)
        res = api.create_rebate_agreement(
            customer["id"],
            {
                "period_start": "2026-03-31",
                "period_end": "2026-05-31",
                "tiers": [{"threshold_cents": 0, "rebate_bps": 100}],
            },
            admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_AGREEMENT_WINDOW_OVERLAP)


class TestRebateLifecycleGates:
    def test_rebate_create_for_non_national_customer_rejected(
        self, api, admin_headers
    ):
        """PRD §3.9: "Creation is restricted to customers whose
        `is_national_account` flag is set — an agreement for any other customer
        is rejected with `ERR_CUSTOMER_NOT_NATIONAL_ACCOUNT`"

        Design: Corner/entities/rebate_create_for_non_national_customer_rejected
        """
        customer = create_customer(
            account_number="NN-1", credit_limit_cents=50000,
            primary_ship_to_state="OH",
        )
        res = api.create_rebate_agreement(
            customer["id"],
            {
                "period_start": "2026-01-01",
                "period_end": "2026-03-31",
                "tiers": [{"threshold_cents": 0, "rebate_bps": 100}],
            },
            admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_CUSTOMER_NOT_NATIONAL_ACCOUNT)

    def test_rebate_settle_before_close_returns_invalid_state(
        self, api, admin_headers
    ):
        """PRD §3.9: "Settlement is the final step, moving a `CLOSED` agreement
        to `SETTLED` — the terminal state — and issuing the credit:
        `settled_credit_cents` is set equal to `final_rebate_cents`, null until
        that moment."
        PRD §2.10: "Sixth, the state preconditions of the targeted transition are
        enforced, which is where stale-version rejections (`ERR_STALE_VERSION`)
        and invalid-transition rejections (`ERR_INVALID_STATE_TRANSITION`) surface
        alongside the state gates named in §3."

        Design: Corner/state_machines/rebate_settle_before_close_returns_invalid_state
        """
        customer, agreement = _national_with_agreement(
            api, "STL-1", tiers=[{"threshold_cents": 0, "rebate_bps": 100}]
        )
        assert agreement["status"] == "ACTIVE"
        res = api.settle_rebate_agreement(agreement["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_rebate_close_before_period_end_returns_temporal_error(
        self, api, admin_headers
    ):
        """PRD §3.9: "Closing is allowed only once the logical-clock date has
        moved strictly past `period_end`; closing on or before that date is
        rejected with `ERR_AGREEMENT_PERIOD_NOT_ENDED`."

        Design: Corner/state_machines/rebate_close_before_period_end_returns_temporal_error
        """
        customer, agreement = _national_with_agreement(
            api, "CLS-1", tiers=[{"threshold_cents": 0, "rebate_bps": 100}]
        )
        set_clock("2026-09-30T12:00:00Z")
        res = api.close_rebate_agreement(agreement["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_AGREEMENT_PERIOD_NOT_ENDED)

    def test_agreement_activate_after_period_expired(self, api, admin_headers):
        """PRD §3.9: "Activation is permitted while the logical-clock date is on
        or before `period_end`; attempting it after the period has closed is
        rejected with `ERR_AGREEMENT_PERIOD_EXPIRED`."
        PRD §2.4: "At server startup, before any explicit set, the logical clock
        reads exactly `2026-08-01T00:00:00Z`, and it must never fall back to
        wall-clock time."

        Design: Corner/errors/agreement_activate_after_period_expired
        """
        customer = create_national_customer(
            account_number="EXP-1", credit_limit_cents=100000,
            primary_ship_to_state="OH",
        )
        agreement = create_rebate_agreement(
            customer["id"], period_start="2026-06-01", period_end="2026-06-30",
            tiers=[{"threshold_cents": 0, "rebate_bps": 100}],
        )
        res = api.activate_rebate_agreement(agreement["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_AGREEMENT_PERIOD_EXPIRED)
