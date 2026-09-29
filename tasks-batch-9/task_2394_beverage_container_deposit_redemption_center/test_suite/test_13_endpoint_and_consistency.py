"""Cross-reference reads, filter composition and read-after-write freshness.

These four listing and action endpoints reach their rows sideways — a label's
lots across two visits, a distributor's own ledger lines, a filtered visit page,
a signed credit line — and the close-count response is checked against an
immediate re-read of all four aggregates it touched.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import (
    ADMIN_HEADERS,
    ADMIN_USER_ID,
    assert_created_at_ascending,
    assert_lot_settlement,
    assert_stamped_at,
    assert_visit_valuation,
    make_admin_headers,
    make_distributor_headers,
)
from test_helpers import factories as f
from test_helpers import fixtures as h

INSTANT = "2026-08-05T09:00:00Z"
OPERATOR_USER_ID = "operator-1"


class TestProductContainerLotsCrossReference:
    """One label's lots come back together however many visits produced them."""

    def test_the_label_listing_spans_two_visits_and_pages(self, api):
        """Two lots created under two visits are one collection of two rows.

        PRD: "First it snapshots the label's current per-container deposit into the lot's own
        `deposit_cents_per_container`, so that a later withdrawal of the label cannot
        retroactively change what this lot was worth."

        PRD: "`total_count` is the number of rows matching the filter before pagination is
        applied, and `has_more` is true when rows remain beyond the current window."

        Design: Corner/endpoints/product_container_lots_cross_reference_spans_two_visits
        """
        h.set_clock(api, INSTANT)
        distributor = h.create_distributor(api)
        product = h.create_registered_product(api, distributor["id"])
        fleet = h.create_operational_center(
            api,
            {"site_name": "Bend Redemption Center", "opening_cash_cents": 50000},
        )
        center, machine = fleet["center"], fleet["machine"]
        headers = h.make_center_headers(center["id"])

        first_visit = h.open_center_machine_visit(api, center["id"], machine["id"])
        first_lot = h.add_lot(
            api,
            first_visit["id"],
            product["id"],
            40,
            headers,
            expected_visit_version=first_visit["version"],
        )
        second_visit = h.open_center_machine_visit(api, center["id"], machine["id"])
        second_lot = h.add_lot(
            api,
            second_visit["id"],
            product["id"],
            25,
            headers,
            expected_visit_version=second_visit["version"],
        )

        response = api.list_product_container_lots(product["id"], ADMIN_HEADERS)
        rows, meta = validate_paginated(response)

        assert response.json()["response_type"] == "array"
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert sorted(row["id"] for row in rows) == sorted(
            [first_lot["id"], second_lot["id"]]
        )
        for row in rows:
            assert row["product_id"] == product["id"]
            assert row["deposit_cents_per_container"] == 10
        assert sorted(row["visit_id"] for row in rows) == sorted(
            [first_visit["id"], second_visit["id"]]
        )
        assert_created_at_ascending(rows)

        page_rows, page_meta = validate_paginated(
            api.list_product_container_lots(
                product["id"], ADMIN_HEADERS, params={"limit": 1, "offset": 1}
            )
        )
        assert page_meta["limit"] == 1
        assert page_meta["offset"] == 1
        assert page_meta["total_count"] == 2
        assert page_meta["has_more"] is False
        assert len(page_rows) == 1
        assert page_rows[0]["id"] in {first_lot["id"], second_lot["id"]}


class TestDistributorInitiationsMatchItsCounters:
    """The distributor's lifetime counters are the sum of its own ledger lines."""

    def test_two_initiations_roll_up_to_four_thousand_two_hundred_cents(self, api):
        """300 then 120 containers give 3000 and 1200 cents against one quarter.

        PRD: "The initiation appends a deposit ledger line whose `entry_type` is
        `DEPOSIT_INITIATED`, whose `amount_cents` is the declared container count multiplied
        by the label's `deposit_cents` — a positive amount, because initiating deposits
        increases what the programme owes — whose `container_count` repeats the declared count,
        whose `source_kind` is `DISTRIBUTOR` and whose `source_ref_id` is the distributor's
        `id`."

        PRD: "The distributor's own `deposits_initiated_cents` and
        `containers_initiated_count` grow by the same two amounts, and the liability
        projection of §2.8 re-runs so that the quarter's `deposits_initiated_cents`,
        `containers_initiated_count` and `outstanding_liability_cents` all move together."

        Design: Corner/endpoints/distributor_deposit_initiations_read_matches_its_own_counters
        """
        h.set_clock(api, INSTANT)
        period = h.create_period(api, operating_cost_cents=0)
        distributor = h.create_distributor(api)
        product = h.create_registered_product(api, distributor["id"])
        headers = make_distributor_headers(distributor["id"])

        for container_count in (300, 120):
            validate_success(
                api.create_deposit_initiation(
                    distributor["id"],
                    f.deposit_initiation_payload(
                        product["id"], container_count, period["id"]
                    ),
                    headers,
                ),
                expected_status=201,
            )

        rows, meta = validate_paginated(
            api.list_deposit_initiations(distributor["id"], headers)
        )
        assert meta["total_count"] == 2
        assert_created_at_ascending(rows)
        for row in rows:
            assert row["entry_type"] == "DEPOSIT_INITIATED"
            assert row["source_kind"] == "DISTRIBUTOR"
            assert row["source_ref_id"] == distributor["id"]
        assert [row["amount_cents"] for row in rows] == [3000, 1200]
        assert [row["liability_after_cents"] for row in rows] == [3000, 4200]

        owner = validate_success(api.get_distributor(distributor["id"], headers))
        assert owner["deposits_initiated_cents"] == 4200
        assert owner["containers_initiated_count"] == 420

        stored_period = h.read_period(api, period["id"])
        assert stored_period["deposits_initiated_cents"] == 4200
        assert stored_period["containers_initiated_count"] == 420
        assert stored_period["outstanding_liability_cents"] == 4200


class TestVisitFiltersComposeWithPagination:
    """A filter narrows the collection before the page window is applied."""

    def test_count_status_and_visit_date_narrow_the_same_collection(self, api):
        """Three visits split two COUNTED and one COUNTING, and a page of one follows the filter.

        PRD: "Visits may be listed and filtered by `center_id`, `retailer_id`, `account_id`,
        `machine_id`, `count_status`, `payout_status` and `visit_date`."

        PRD: "`total_count` is the number of rows matching the filter before pagination is
        applied, and `has_more` is true when rows remain beyond the current window."

        Design: Corner/endpoints/visit_list_filters_compose_with_pagination
        """
        h.set_clock(api, INSTANT)
        distributor = h.create_distributor(api)
        product = h.create_registered_product(api, distributor["id"])
        fleet = h.create_operational_center(
            api,
            {"site_name": "Bend Redemption Center", "opening_cash_cents": 50000},
        )
        center, machine = fleet["center"], fleet["machine"]
        headers = h.make_center_headers(center["id"])

        closed = [
            h.create_counted_center_visit(
                api, center["id"], machine["id"], product["id"], [100]
            )
            for _ in range(2)
        ]
        counting = h.open_center_machine_visit(api, center["id"], machine["id"])
        h.add_lot(
            api,
            counting["id"],
            product["id"],
            50,
            headers,
            expected_visit_version=counting["version"],
        )

        _, all_meta = validate_paginated(
            api.list_redemption_visits(headers, params={"center_id": center["id"]})
        )
        assert all_meta["total_count"] == 3
        assert all_meta["has_more"] is False
        assert all_meta["limit"] == 10

        counted_rows, counted_meta = validate_paginated(
            api.list_redemption_visits(
                headers,
                params={"center_id": center["id"], "count_status": "COUNTED"},
            )
        )
        assert counted_meta["total_count"] == 2
        returned = {row["id"] for row in counted_rows}
        assert returned == {closed[0]["id"], closed[1]["id"]}
        assert counting["id"] not in returned

        page_rows, page_meta = validate_paginated(
            api.list_redemption_visits(
                headers,
                params={
                    "center_id": center["id"],
                    "count_status": "COUNTED",
                    "limit": 1,
                    "offset": 0,
                },
            )
        )
        assert page_meta["limit"] == 1
        assert page_meta["offset"] == 0
        assert page_meta["total_count"] == 2
        assert page_meta["has_more"] is True
        assert len(page_rows) == 1

        empty_rows, empty_meta = validate_paginated(
            api.list_redemption_visits(headers, params={"visit_date": "2026-08-04"})
        )
        assert empty_meta["total_count"] == 0
        assert empty_meta["has_more"] is False
        assert empty_rows == []


class TestCreditActionSigns:
    """One endpoint writes a positive grant and a negative withdrawal."""

    def test_a_grant_and_a_withdrawal_net_to_zero_over_two_versions(self, api):
        """+1000 then -1000 leave the balance at 0 and the account at version 3.

        PRD: "The posted line's `entry_type` is `PAYOUT_WITHDRAWAL` for a `WITHDRAW`,
        `MANUAL_GRANT` for a `MANUAL_GRANT` and `CLAWBACK` for a `CLAWBACK`; its `source_kind`
        is `PROGRAM_ACTION` and its `source_ref_id` is the acting operator's `X-User-ID`."

        PRD: "Amounts are signed, and both `PAYOUT_WITHDRAWAL` and `CLAWBACK` lines carry
        negative amounts, because both remove value from the holder."

        PRD: "On success the account's `credit_balance_cents` is recomputed,
        `balance_after_cents` is written onto the new line, and the account's `version`
        increments by 1."

        Design: Corner/endpoints/credit_action_endpoint_appends_a_signed_line_and_bumps_the_account
        """
        h.set_clock(api, INSTANT)
        account = h.create_account(api)

        grant = validate_success(
            api.post_credit_action(
                account["id"],
                f.credit_action_payload(
                    "MANUAL_GRANT", 1000, account["version"], memo="goodwill"
                ),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )
        assert grant["entry_type"] == "MANUAL_GRANT"
        assert grant["amount_cents"] == 1000
        assert grant["balance_after_cents"] == 1000
        assert grant["source_kind"] == "PROGRAM_ACTION"
        assert grant["source_ref_id"] == ADMIN_USER_ID

        after_grant = h.read_account(api, account["id"], ADMIN_HEADERS)
        assert after_grant["credit_balance_cents"] == 1000
        assert after_grant["version"] == 2

        withdrawal = validate_success(
            api.post_credit_action(
                account["id"],
                f.credit_action_payload(
                    "WITHDRAW", 1000, after_grant["version"]
                ),
                make_admin_headers(OPERATOR_USER_ID),
            ),
            expected_status=201,
        )
        assert withdrawal["entry_type"] == "PAYOUT_WITHDRAWAL"
        assert withdrawal["amount_cents"] == -1000
        assert withdrawal["balance_after_cents"] == 0
        assert withdrawal["source_ref_id"] == OPERATOR_USER_ID

        stored = h.read_account(api, account["id"], ADMIN_HEADERS)
        assert stored["credit_balance_cents"] == 0
        assert stored["version"] == 3

        rows, meta = validate_paginated(
            api.list_credit_entries(
                account["id"],
                ADMIN_HEADERS,
                params={"entry_type": "PAYOUT_WITHDRAWAL"},
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [withdrawal["id"]]


class TestCloseCountResponseIsAlreadyConsistent:
    """The close-count body is the same data a later read returns."""

    def test_the_response_matches_an_immediate_reread_of_all_four_aggregates(self, api):
        """160 containers over two lots are valued, allocated, bucketed and binned at once.

        PRD: "Closing stamps `counted_at` with the current logical instant and increments the
        visit's `version` by 1."

        PRD: "The visit's `payable_count` is then added to `containers_redeemed_today`."

        PRD: "On a machine-counted visit the whole `raw_accepted_count` is added to the
        serving machine's `bin_filled_count`, which is what eventually makes a bin-full
        declaration legitimate."

        Design: Corner/consistency_model/close_count_response_already_carries_every_derived_field
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
        headers = h.make_center_headers(center["id"])

        visit = h.open_center_machine_visit(
            api, center["id"], machine["id"], account["id"]
        )
        first_lot = h.add_lot(
            api,
            visit["id"],
            product["id"],
            100,
            headers,
            expected_visit_version=visit["version"],
        )
        second_lot = h.add_lot(api, visit["id"], product["id"], 60, headers)

        closed = validate_success(api.close_count(visit["id"], headers))

        assert closed["count_status"] == "COUNTED"
        assert_stamped_at(closed["counted_at"], INSTANT)
        assert_visit_valuation(
            closed,
            visit_limit_applied=240,
            capped_count=160,
            shrink_adjustment_count=0,
            payable_count=160,
            refused_over_limit_count=0,
            payout_cents=1600,
        )

        reread = h.read_visit(api, visit["id"], headers)
        assert reread == closed

        lots = {lot["id"]: lot for lot in h.list_lots(api, visit["id"], headers)}
        assert_lot_settlement(
            lots[first_lot["id"]], paid_quantity=100, reconciliation_flag="PAID_FULL"
        )
        assert_lot_settlement(
            lots[second_lot["id"]], paid_quantity=60, reconciliation_flag="PAID_FULL"
        )

        holder = h.read_account(api, account["id"], ADMIN_HEADERS)
        assert holder["containers_redeemed_today"] == 160
        assert holder["redemption_day"] == "2026-08-05"
        assert holder["cap_reached_today"] is False

        assert h.read_machine(api, machine["id"], headers)["bin_filled_count"] == 160
