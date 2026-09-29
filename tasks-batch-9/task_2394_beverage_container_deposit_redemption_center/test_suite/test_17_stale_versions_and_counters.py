"""Optimistic concurrency on the three additive writes, and the counters they feed.

The version field is compared before any business rule runs, so a replayed body
is refused with 412 and writes nothing; re-reading the parent and resending the
identical body succeeds. The last two cases follow derived state instead: a
fraud-strike threshold that flags and resets, and a centre's four projections
re-derived after every source event.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_HEADERS,
    ADMIN_USER_ID,
    PLANT_COUNTER_HEADERS,
    ApiErrorId,
    assert_account_standing,
    assert_center_pool,
    assert_created_at_ascending,
    assert_fraud_posture,
    assert_visit_valuation,
    make_account_headers,
    make_center_headers,
)
from test_helpers import factories as f
from test_helpers import fixtures as h

INSTANT = "2026-08-05T09:00:00Z"


class TestStaleVisitVersionOnLotAdd:
    """The second lot cannot reuse the version the first lot consumed."""

    def test_a_replayed_version_is_refused_and_the_reread_value_is_accepted(self, api):
        """412 with nothing written, then the identical body succeeds at version 2.

        PRD: "If the visit's `version` has advanced since the client read it, the addition is
        rejected with `ERR_STALE_VISIT_VERSION` (HTTP 412)."

        PRD: "Every accepted lot increments the visit's `version` by 1."

        PRD: "The lots of a visit may be listed back in `created_at` ascending order, which is
        exactly the order the payout waterfall will walk them in."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_visit_version_is_refused_then_accepted_after_a_reread
        """
        h.set_clock(api, INSTANT)
        distributor = h.create_distributor(api)
        product = h.create_registered_product(api, distributor["id"])
        fleet = h.create_operational_center(
            api,
            {"site_name": "Bend Redemption Center", "opening_cash_cents": 50000},
        )
        center, machine = fleet["center"], fleet["machine"]
        headers = make_center_headers(center["id"])

        visit = h.open_center_machine_visit(api, center["id"], machine["id"])
        assert visit["version"] == 1

        first_lot = validate_success(
            api.create_container_lot(
                visit["id"],
                f.create_lot_payload(product["id"], 10, visit["version"]),
                headers,
            ),
            expected_status=201,
        )
        after_first = h.read_visit(api, visit["id"], headers)
        assert after_first["version"] == 2
        assert after_first["presented_total"] == 10

        validate_error(
            api.create_container_lot(
                visit["id"],
                f.create_lot_payload(product["id"], 20, visit["version"]),
                headers,
            ),
            ApiErrorId.ERR_STALE_VISIT_VERSION.value,
            expected_status=412,
        )

        unchanged = h.read_visit(api, visit["id"], headers)
        assert unchanged["presented_total"] == 10
        assert unchanged["version"] == 2
        _, meta = validate_paginated(api.list_visit_lots(visit["id"], headers))
        assert meta["total_count"] == 1

        second_lot = validate_success(
            api.create_container_lot(
                visit["id"],
                f.create_lot_payload(product["id"], 20, unchanged["version"]),
                headers,
            ),
            expected_status=201,
        )
        accepted = h.read_visit(api, visit["id"], headers)
        assert accepted["version"] == 3
        assert accepted["presented_total"] == 30
        assert accepted["raw_accepted_count"] == 30

        rows, final_meta = validate_paginated(
            api.list_visit_lots(visit["id"], headers)
        )
        assert final_meta["total_count"] == 2
        assert [row["id"] for row in rows] == [first_lot["id"], second_lot["id"]]
        assert_created_at_ascending(rows)


class TestStaleBagDropVersionBeatsTheStateCheck:
    """Rung 10 answers before the from-state rung, even on a legitimate recount."""

    def test_the_drop_time_version_is_refused_although_the_bag_is_disputed(self, api):
        """The recount is valid in every way except its version, so the code is the stale one.

        PRD: "Because a recount fully replaces the previous count result, a submission made
        against a superseded view of the bag would silently overwrite a newer count; instead it
        is rejected with `ERR_STALE_BAG_DROP_VERSION` (HTTP 412)."

        PRD: "Submitting against a bag in `DROPPED` moves it `DROPPED → COUNTED` and requires
        the receiving centre to still be `OPERATIONAL`; submitting against a bag in `DISPUTED`
        moves it `DISPUTED → COUNTED` as a recount."

        PRD: "`variance_pct` is `counted_total` less `declared_count`, divided by
        `declared_count`, rounded to 4 decimal places, and `variance_flag` is true exactly when
        the **absolute value** of `variance_pct` is strictly greater than one tenth."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_bag_drop_version_is_refused_before_the_state_check
        """
        h.set_clock(api, INSTANT)
        fleet = h.create_operational_center(
            api,
            {"site_name": "Bend Redemption Center", "opening_cash_cents": 50000},
        )
        center = fleet["center"]
        account = h.create_account(api, bag_drop_enrolled=True)
        bag = h.create_bag_drop(api, account["id"], center["id"], declared_count=100)
        dropped_version = bag["version"]

        h.submit_bag_count(api, bag["id"], [100], dropped_version)
        disputed = h.settle_bag(
            api, bag["id"], "DISPUTE", make_account_headers(account["id"])
        )
        assert disputed["status"] == "DISPUTED"
        assert disputed["version"] == 3

        validate_error(
            api.post_bag_drop_count_result(
                bag["id"],
                f.bag_drop_count_payload([90, 5], dropped_version),
                PLANT_COUNTER_HEADERS,
            ),
            ApiErrorId.ERR_STALE_BAG_DROP_VERSION.value,
            expected_status=412,
        )

        untouched = h.read_bag_drop(api, bag["id"], PLANT_COUNTER_HEADERS)
        assert untouched["status"] == "DISPUTED"
        assert untouched["counted_total"] == 100
        assert untouched["version"] == 3

        recounted = validate_success(
            api.post_bag_drop_count_result(
                bag["id"],
                f.bag_drop_count_payload([90, 5], untouched["version"]),
                PLANT_COUNTER_HEADERS,
            )
        )
        assert recounted["status"] == "COUNTED"
        assert recounted["counted_lines"] == 2
        assert recounted["counted_total"] == 95
        assert recounted["gross_final_cents"] == 950
        assert recounted["final_credit_cents"] == 900
        assert recounted["adjustment_cents"] == 100
        assert recounted["variance_pct"] == -0.05
        assert recounted["variance_flag"] is False
        assert recounted["version"] == 4


class TestStaleAccountVersionOnCreditAction:
    """The endpoint answers with a journal line, so the account must be re-read."""

    def test_the_replayed_grant_posts_nothing_and_the_reread_version_posts_a_second_line(
        self, api
    ):
        """250 lands once, the replay is 412, and the re-read version brings the balance to 500.

        PRD: "Credit movements are additive journal lines that no state field forbids, so an
        operator acting on a superseded `credit_balance_cents` would post an amount derived from
        a balance the account no longer holds; that request is rejected with
        `ERR_STALE_ACCOUNT_VERSION` (HTTP 412)."

        PRD: "On success the account's `credit_balance_cents` is recomputed,
        `balance_after_cents` is written onto the new line, and the account's `version`
        increments by 1."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_account_version_is_refused_on_the_second_credit_action
        """
        h.set_clock(api, INSTANT)
        account = h.create_account(api)
        assert account["version"] == 1

        first_entry = validate_success(
            api.post_credit_action(
                account["id"],
                f.credit_action_payload("MANUAL_GRANT", 250, account["version"]),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )
        assert first_entry["balance_after_cents"] == 250
        after_first = h.read_account(api, account["id"], ADMIN_HEADERS)
        assert after_first["version"] == 2

        validate_error(
            api.post_credit_action(
                account["id"],
                f.credit_action_payload("MANUAL_GRANT", 250, account["version"]),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_STALE_ACCOUNT_VERSION.value,
            expected_status=412,
        )

        _, meta = validate_paginated(
            api.list_credit_entries(account["id"], ADMIN_HEADERS)
        )
        assert meta["total_count"] == 1
        held = h.read_account(api, account["id"], ADMIN_HEADERS)
        assert held["credit_balance_cents"] == 250
        assert held["version"] == 2

        second_entry = validate_success(
            api.post_credit_action(
                account["id"],
                f.credit_action_payload("MANUAL_GRANT", 250, held["version"]),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )
        assert second_entry["balance_after_cents"] == 500
        assert second_entry["source_ref_id"] == ADMIN_USER_ID
        stored = h.read_account(api, account["id"], ADMIN_HEADERS)
        assert stored["credit_balance_cents"] == 500
        assert stored["version"] == 3


class TestFraudStrikeThreshold:
    """One strike withholds, the second flags, and UNFLAG wipes the slate."""

    def test_two_marked_visits_flag_the_holder_and_a_clean_one_afterwards_does_not(
        self, api
    ):
        """13.33 % out-of-state twice reaches the limit of two strikes; the third visit is clean.

        PRD: "The first is out-of-state marking: if the visit's `out_of_state_ratio` — computed
        as in §3.4, rounded to 4 decimal places — is **strictly greater** than one tenth,
        `fraud_hold` becomes true, `withhold_reason` becomes `OUT_OF_STATE_RATIO`, and the
        account's `fraud_strikes` increments by 1 with `last_strike_reason`
        `OUT_OF_STATE_RATIO`."

        PRD: "And if the strikes recorded in this request bring the account's `fraud_strikes`
        to 2, the account moves `ACTIVE → FLAGGED` as described in §3.3 and the visit's
        `withhold_reason` is overwritten with `ACCOUNT_FLAGGED`."

        PRD: "Unflagging with `UNFLAG`, a `ProgramAdmin` prerogative, moves the account
        `FLAGGED → ACTIVE` and wipes the slate: `fraud_strikes` returns to 0 and
        `last_strike_reason` to null."

        Design: Corner/cross_cutting_complexity_layers/fraud_strike_threshold_flags_at_two_and_resets_on_unflag
        """
        h.set_clock(api, INSTANT)
        distributor = h.create_distributor(api)
        product = h.create_registered_product(api, distributor["id"])
        fleet = h.create_operational_center(
            api,
            {
                "site_name": "Bend Redemption Center",
                "daily_account_cap_containers": 300,
                "opening_cash_cents": 50000,
            },
        )
        center, machine = fleet["center"], fleet["machine"]
        account = h.create_account(api)
        headers = make_center_headers(center["id"])

        marked = []
        for _ in range(2):
            visit = h.open_center_machine_visit(
                api, center["id"], machine["id"], account["id"]
            )
            h.add_lot(
                api,
                visit["id"],
                product["id"],
                30,
                headers,
                out_of_state_marked_quantity=4,
                expected_visit_version=visit["version"],
            )
            marked.append(visit)

        first_closed = h.close_count(api, marked[0]["id"], headers)
        assert first_closed["out_of_state_ratio"] == 0.1333
        assert_fraud_posture(
            first_closed,
            fraud_hold=True,
            withhold_reason="OUT_OF_STATE_RATIO",
            payout_status="WITHHELD",
        )
        assert first_closed["payable_count"] == 26
        assert first_closed["payout_cents"] == 260
        assert_account_standing(
            h.read_account(api, account["id"], ADMIN_HEADERS),
            status="ACTIVE",
            fraud_strikes=1,
            last_strike_reason="OUT_OF_STATE_RATIO",
        )

        second_closed = h.close_count(api, marked[1]["id"], headers)
        assert_fraud_posture(
            second_closed,
            fraud_hold=True,
            withhold_reason="ACCOUNT_FLAGGED",
            payout_status="WITHHELD",
        )
        flagged = h.read_account(api, account["id"], ADMIN_HEADERS)
        assert_account_standing(
            flagged,
            status="FLAGGED",
            fraud_strikes=2,
            last_strike_reason="OUT_OF_STATE_RATIO",
        )
        assert flagged["containers_redeemed_today"] == 52
        assert flagged["cap_reached_today"] is False

        unflagged = h.account_status_change(api, account["id"], "UNFLAG")
        assert_account_standing(
            unflagged, status="ACTIVE", fraud_strikes=0, last_strike_reason=None
        )

        clean = h.open_center_machine_visit(
            api, center["id"], machine["id"], account["id"]
        )
        h.add_lot(
            api,
            clean["id"],
            product["id"],
            30,
            headers,
            expected_visit_version=clean["version"],
        )
        clean_closed = h.close_count(api, clean["id"], headers)
        assert clean_closed["out_of_state_ratio"] == 0.0
        assert_fraud_posture(
            clean_closed,
            fraud_hold=False,
            withhold_reason=None,
            payout_status="PENDING",
        )
        assert clean_closed["payable_count"] == 30
        assert clean_closed["payout_cents"] == 300

        after_clean = h.read_account(api, account["id"], ADMIN_HEADERS)
        assert after_clean["fraud_strikes"] == 0
        assert after_clean["containers_redeemed_today"] == 82

        assert_center_pool(
            h.read_center(api, center["id"], headers), withheld_visit_count=2
        )


class TestCenterCountersReconcileAfterEveryEvent:
    """Four projections on one row, re-derived after each source event."""

    def test_counting_batching_and_a_hold_move_the_right_counters_only(self, api):
        """The pool grows with each close, shifts on a batch draw, and a hold touches neither.

        PRD: "A centre's `accepted_container_count` is the running sum of `accepted_quantity`
        over the container lots of its visits whose `count_status` is `COUNTED`; its
        `batched_container_count` is the running sum of `container_count` over its commodity
        batches whose `status` is `ACCUMULATING`, `SORTED`, `BALED` or `SOLD`; and
        `unbatched_container_count` is `accepted_container_count` minus
        `batched_container_count` — the pool a new batch may draw from."

        PRD: "Either way the hosting centre's `withheld_visit_count` is recomputed."

        PRD: "Releasing sets `fraud_hold` back to false and `withhold_reason` back to null, and
        recomputes the centre's `withheld_visit_count`."

        Design: Corner/cross_cutting_complexity_layers/center_pool_counters_reconcile_across_counting_batching_and_release
        """
        h.set_clock(api, INSTANT)
        distributor = h.create_distributor(api)
        product = h.create_registered_product(api, distributor["id"])
        fleet = h.create_operational_center(
            api,
            {"site_name": "Bend Redemption Center", "opening_cash_cents": 50000},
        )
        center, machine = fleet["center"], fleet["machine"]
        headers = make_center_headers(center["id"])

        first = h.create_counted_center_visit(
            api, center["id"], machine["id"], product["id"], [100]
        )
        assert_visit_valuation(
            first,
            visit_limit_applied=144,
            capped_count=100,
            shrink_adjustment_count=0,
            payable_count=100,
            refused_over_limit_count=0,
            payout_cents=1000,
        )
        assert_center_pool(
            h.read_center(api, center["id"], headers),
            accepted_container_count=100,
            batched_container_count=0,
            unbatched_container_count=100,
            withheld_visit_count=0,
        )

        second = h.create_counted_center_visit(
            api, center["id"], machine["id"], product["id"], [50]
        )
        assert_center_pool(
            h.read_center(api, center["id"], headers),
            accepted_container_count=150,
            unbatched_container_count=150,
        )

        h.create_batch(api, center["id"], 120)
        assert_center_pool(
            h.read_center(api, center["id"], headers),
            accepted_container_count=150,
            batched_container_count=120,
            unbatched_container_count=30,
        )

        withheld = h.payout_action(
            api, second["id"], "WITHHOLD", headers, reason="manual review"
        )
        assert withheld["payout_status"] == "WITHHELD"
        assert withheld["withhold_reason"] == "MANUAL_REVIEW"
        assert_center_pool(
            h.read_center(api, center["id"], headers),
            accepted_container_count=150,
            batched_container_count=120,
            unbatched_container_count=30,
            withheld_visit_count=1,
        )

        released = h.payout_action(api, second["id"], "RELEASE_HOLD", ADMIN_HEADERS)
        assert released["payout_status"] == "PENDING"
        assert released["withhold_reason"] is None

        final = h.read_center(api, center["id"], headers)
        assert_center_pool(
            final,
            accepted_container_count=150,
            batched_container_count=120,
            unbatched_container_count=30,
            withheld_visit_count=0,
        )
        assert final["machine_count"] == 1
        assert final["cash_drawer_balance_cents"] == 50000
