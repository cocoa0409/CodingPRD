"""Deferred counting: the advance, the true-up and the two compensations.

A drop bag is paid twice — once conservatively at drop time and once for real
once the plant has counted it — and every path out of the bag books a signed
credit journal line rather than editing a balance.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_HEADERS,
    PLANT_COUNTER_HEADERS,
    ApiErrorId,
    assert_bag_drop_valuation,
    assert_credit_entry,
    assert_ratio_precision,
)
from test_helpers import factories as f
from test_helpers import fixtures as h

INSTANT = "2026-08-05T09:00:00Z"


def _bag_world(api):
    """Clock, an OPEN quarter, an OPERATIONAL centre and an enrolled holder."""
    h.set_clock(api, INSTANT)
    period = h.create_period(api, operating_cost_cents=1000)
    fleet = h.create_operational_center(
        api,
        {
            "site_name": "Bend Redemption Center",
            "daily_account_cap_containers": 300,
            "opening_cash_cents": 50000,
        },
    )
    account = h.create_account(api, bag_drop_enrolled=True)
    return period, fleet["center"], account


class TestProvisionalAgainstFinalCredit:
    """The advance and the true-up are two different valuations of one bag."""

    def test_advance_is_capped_at_two_hundred_and_fifty_units(self, api):
        """A 300-container declaration is advanced for 250 units at eight cents.

        PRD: "`provisional_units` is the lesser of `declared_count` and 250 units, and
        `provisional_credit_cents` is `provisional_units` multiplied by 8 cents."

        Design: Difficulty/dual_variant_calc/bag_drop_provisional_vs_final_credit_divergence
        """
        _, center, account = _bag_world(api)
        center_headers = h.make_center_headers(center["id"])

        response = api.create_bag_drop(
            f.create_bag_drop_payload(
                account["id"], center["id"], tag_code="BAG-1001", declared_count=300
            ),
            center_headers,
        )
        bag = validate_success(response, expected_status=201)

        assert bag["status"] == "DROPPED"
        assert bag["provisional_units"] == 250
        assert bag["provisional_credit_cents"] == 2000

        holder = h.read_account(api, account["id"], ADMIN_HEADERS)
        assert holder["credit_balance_cents"] == 2000

        entries, meta = validate_paginated(
            api.list_credit_entries(account["id"], ADMIN_HEADERS)
        )
        assert meta["total_count"] == 1
        assert_credit_entry(
            entries[0],
            entry_type="PROVISIONAL",
            amount_cents=2000,
            balance_after_cents=2000,
            source_kind="BAG_DROP",
            source_ref_id=bag["id"],
        )

    def test_final_credit_posts_only_the_adjustment_delta(self, api):
        """285 counted containers justify 2800 cents, so the true-up is +800.

        PRD: "`adjustment_cents` is `final_credit_cents` less
        `provisional_credit_cents`, and it is signed — negative whenever the holder's
        advance turned out to be generous relative to what was actually in the bag."

        Design: Difficulty/dual_variant_calc/bag_drop_provisional_vs_final_credit_divergence
        """
        _, center, account = _bag_world(api)
        center_headers = h.make_center_headers(center["id"])
        bag = h.create_bag_drop(
            api, account["id"], center["id"], tag_code="BAG-1001", declared_count=300
        )

        counted = h.submit_bag_count(api, bag["id"], [120, 100, 65])
        assert_bag_drop_valuation(
            counted,
            counted_lines=3,
            counted_total=285,
            gross_final_cents=2850,
            final_credit_cents=2800,
            adjustment_cents=800,
            variance_pct=-0.05,
            variance_flag=False,
        )
        assert_ratio_precision(counted["variance_pct"])

        credited = validate_success(
            api.post_bag_drop_settlement_action(
                bag["id"], f.bag_drop_settlement_payload("CREDIT"), center_headers
            )
        )
        assert credited["status"] == "CREDITED"

        holder = h.read_account(api, account["id"], ADMIN_HEADERS)
        assert holder["credit_balance_cents"] == 2800
        assert holder["fraud_strikes"] == 0

        entries, meta = validate_paginated(
            api.list_credit_entries(account["id"], ADMIN_HEADERS)
        )
        assert meta["total_count"] == 2
        assert_credit_entry(entries[0], "PROVISIONAL", 2000, 2000, "BAG_DROP", bag["id"])
        assert_credit_entry(entries[1], "ADJUSTMENT", 800, 2800, "BAG_DROP", bag["id"])


class TestCreditRequiresAnActiveHolder:
    """A counted bag can only be credited while its account is ACTIVE."""

    @staticmethod
    def _flagged_holder_with_counted_bag(api):
        _, center, account = _bag_world(api)
        bag = h.create_bag_drop(
            api, account["id"], center["id"], tag_code="BAG-1001", declared_count=150
        )
        h.submit_bag_count(api, bag["id"], [100, 50])
        h.account_status_change(
            api, account["id"], "FLAG", "identity check pending on the drop bags"
        )
        return center, account, bag

    def test_credit_on_a_flagged_account_is_refused(self, api):
        """Flagging the holder blocks the settlement with the account error.

        PRD: "A `CenterOperator` credits a counted bag, moving it `COUNTED →
        CREDITED`, which requires the holder's account to be `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/bag_drop_credit_rejected_when_account_flagged
        """
        center, account, bag = self._flagged_holder_with_counted_bag(api)

        response = api.post_bag_drop_settlement_action(
            bag["id"],
            f.bag_drop_settlement_payload("CREDIT"),
            h.make_center_headers(center["id"]),
        )
        validate_error(response, ApiErrorId.ERR_ACCOUNT_FLAGGED.value)

        holder = h.read_account(api, account["id"], ADMIN_HEADERS)
        assert holder["status"] == "FLAGGED"

    def test_refused_credit_leaves_the_bag_counted_and_the_balance_provisional(
        self, api
    ):
        """The bag keeps its count result and the holder keeps only the advance.

        PRD: "a `FLAGGED` account may not be given a new visit, a new bag drop or a new
        credit action, refusing with `ERR_ACCOUNT_FLAGGED`."

        Design: Difficulty/cross_entity_state_dependency/bag_drop_credit_rejected_when_account_flagged
        """
        center, account, bag = self._flagged_holder_with_counted_bag(api)
        center_headers = h.make_center_headers(center["id"])

        response = api.post_bag_drop_settlement_action(
            bag["id"], f.bag_drop_settlement_payload("CREDIT"), center_headers
        )
        validate_error(response, ApiErrorId.ERR_ACCOUNT_FLAGGED.value)

        stored = h.read_bag_drop(api, bag["id"], PLANT_COUNTER_HEADERS)
        assert stored["status"] == "COUNTED"
        assert stored["counted_total"] == 150
        assert stored["variance_pct"] == 0
        assert stored["variance_flag"] is False
        assert stored["final_credit_cents"] == 1450
        assert stored["adjustment_cents"] == 250

        holder = h.read_account(api, account["id"], ADMIN_HEADERS)
        assert holder["credit_balance_cents"] == 1200


class TestVoidClawsBackTheAdvance:
    """Voiding a bag compensates the advance exactly, line for line."""

    def test_void_appends_a_clawback_that_zeroes_the_balance(self, api):
        """The CLAWBACK line of −2000 cents returns the holder to a nil balance.

        PRD: "a compensating credit journal line is appended with `entry_type`
        `CLAWBACK`, `amount_cents` equal to the negative of `provisional_credit_cents`,
        `source_kind` `BAG_DROP` and `source_ref_id` equal to this bag's `id`, clawing
        back exactly the advance that was paid at drop time".

        Design: Difficulty/compensating_invariant/bag_drop_void_clawback_restores_account_balance
        """
        _, center, account = _bag_world(api)
        bag = h.create_bag_drop(
            api, account["id"], center["id"], tag_code="BAG-1001", declared_count=300
        )
        assert (
            h.read_account(api, account["id"], ADMIN_HEADERS)["credit_balance_cents"]
            == 2000
        )

        voided = validate_success(
            api.post_bag_drop_settlement_action(
                bag["id"],
                f.bag_drop_settlement_payload("VOID", "bag tag mismatch at the plant intake"),
                ADMIN_HEADERS,
            )
        )

        assert voided["status"] == "VOIDED"
        assert voided["provisional_units"] == 250
        assert voided["provisional_credit_cents"] == 2000

        holder = h.read_account(api, account["id"], ADMIN_HEADERS)
        assert holder["credit_balance_cents"] == 0

        entries, meta = validate_paginated(
            api.list_credit_entries(account["id"], ADMIN_HEADERS)
        )
        assert meta["total_count"] == 2
        assert_credit_entry(entries[0], "PROVISIONAL", 2000, 2000, "BAG_DROP", bag["id"])
        assert_credit_entry(entries[1], "CLAWBACK", -2000, 0, "BAG_DROP", bag["id"])

    def test_voided_bag_leaves_the_account_closeable(self, api):
        """With the advance clawed back and no bag outstanding the holder may close.

        PRD: "The account's `credit_balance_cents` must equal 0, and none of the
        account's bag drops may still sit in `DROPPED`, `COUNTED` or `DISPUTED`".

        Design: Difficulty/compensating_invariant/bag_drop_void_clawback_restores_account_balance
        """
        _, center, account = _bag_world(api)
        bag = h.create_bag_drop(
            api, account["id"], center["id"], tag_code="BAG-1001", declared_count=300
        )
        h.settle_bag(
            api, bag["id"], "VOID", ADMIN_HEADERS, "bag tag mismatch at the plant intake"
        )

        closed = validate_success(
            api.post_account_status_change(
                account["id"], f.account_status_change_payload("CLOSE"), ADMIN_HEADERS
            )
        )

        assert closed["status"] == "CLOSED"
        assert closed["bag_drop_enrolled"] is False
