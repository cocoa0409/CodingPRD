"""Computed reads, cross-index reachability, an outcome-branching write and a
filtered page.

These four tests exercise the read side of the contract: what a computed read
reports before anything has been stamped, which indexes a new row is reachable
from, what a branch of one endpoint deliberately does *not* cascade, and how a
filter composes with a page window.
"""

from test_helpers import (
    ADMIN,
    AGENT,
    FINANCE,
    LOGISTICS,
    api_client,
    assert_instant,
    complete_appointment,
    create_customer_row,
    create_model,
    file_attribution_claim,
    get_success_data,
    read_customer,
    read_order,
    read_refund_summary,
    read_return_case,
    read_route,
    set_clock,
    setup_partner_channel_order,
    setup_return_lifecycle,
    trial_order_payload,
    validate_paginated,
    validate_success,
)


class TestRefundSummaryBeforeAuthorization:
    """The computed read reports both formulas long before finance stamps either."""

    def test_the_summary_is_provisional_yet_already_reports_the_final_figure(self):
        """PRD §3.8: "A computed read on the return case exposes exactly this, reporting `variant_in_effect`, `gross_refundable_cents`, `proration_deduction_cents`, `bundle_unwind_cents`, `damage_offset_cents`, `provisional_refund_cents`, `final_refund_cents` and `variant_delta_cents`, the difference between the two variants."

        Read straight after inspection, the effective variant is the provisional
        one — a 13500-cent usage proration giving 106500 — yet the read also
        reports the 114000-cent tiered figure and their 7500-cent difference,
        while the case itself is still PENDING with nothing stamped.

        Design: Corner/endpoints/refund_summary_reports_the_provisional_variant_and_the_delta_before_authorization
        """
        scenario = setup_return_lifecycle(
            stage="INSPECTED",
            model_overrides={
                "sku": "MDL-Q-X1", "name": "Comfort Q", "list_price_cents": 120000
            },
            customer_overrides={
                "email": "x1@example.com",
                "full_name": "Xan One",
                "household_hash": "HH-X1",
            },
        )
        return_case = scenario["return_case"]

        summary = read_refund_summary(return_case["id"])

        assert summary["variant_in_effect"] == "PROVISIONAL", (
            "before authorization the provisional variant is in effect, got "
            f"{summary['variant_in_effect']}"
        )
        assert summary["gross_refundable_cents"] == 120000
        assert summary["proration_deduction_cents"] == 13500
        assert summary["bundle_unwind_cents"] == 0
        assert summary["damage_offset_cents"] == 0
        assert summary["provisional_refund_cents"] == 106500
        assert summary["final_refund_cents"] == 114000, (
            "the read reports the tiered figure even though nothing has been "
            f"authorized, got {summary['final_refund_cents']}"
        )
        assert abs(summary["variant_delta_cents"]) == 7500

        reloaded = read_return_case(return_case["id"])
        assert reloaded["financial_status"] == "PENDING"
        assert reloaded["final_refund_cents"] is None, (
            "a computed read stamps nothing on the case, got "
            f"{reloaded['final_refund_cents']}"
        )


class TestAttributionClaimIsReachableFromBothSides:
    """One row, two foreign keys, two indexes."""

    def test_a_new_claim_is_found_by_partner_and_by_order(self):
        """PRD §3.10: "Claims can be read individually with their priced commission or credit, or listed with filters on `partner_id`, `order_id`, `claim_type` and `status`."

        A single sales-attribution claim filed on 2026-08-10 opens at SUBMITTED
        with an empty revision counter and both money fields at zero, and the same
        row is returned by the partner-side listing and by the order-plus-type
        listing.

        Design: Corner/endpoints/an_attribution_claim_links_partner_and_order_on_both_sides
        """
        scenario = setup_partner_channel_order(
            partner_overrides={
                "name": "Sleep Gallery X2",
                "region_code": "CA",
                "commission_bps": 800,
            },
            model_overrides={
                "sku": "MDL-Q-X2", "name": "Comfort Q", "list_price_cents": 120000
            },
            customer_overrides={
                "email": "x2@example.com",
                "full_name": "Xia Two",
                "household_hash": "HH-X2",
            },
        )
        partner = scenario["partner"]
        order = scenario["order"]

        set_clock("2026-08-10T00:00:00Z")
        claim = file_attribution_claim(
            partner, order["id"], "SALES_ATTRIBUTION", 2
        )

        assert claim["status"] == "SUBMITTED"
        assert_instant(claim["submitted_at"], "2026-08-10T00:00:00Z", "submitted_at")
        assert claim["revision_round_count"] == 0
        assert claim["commission_cents"] == 0, (
            "nothing is priced until the claim is resolved, got "
            f"{claim['commission_cents']}"
        )
        assert claim["price_match_credit_cents"] == 0

        by_partner, partner_meta = validate_paginated(
            api_client.list_attribution_claims(
                FINANCE, params={"partner_id": partner["id"]}
            )
        )
        assert partner_meta["total_count"] == 1
        assert [row["id"] for row in by_partner] == [claim["id"]]

        by_order, order_meta = validate_paginated(
            api_client.list_attribution_claims(
                FINANCE,
                params={"order_id": order["id"], "claim_type": "SALES_ATTRIBUTION"},
            )
        )
        assert order_meta["total_count"] == 1
        assert [row["id"] for row in by_order] == [claim["id"]]


class TestMissedOutcomeSkipsTheCollectionCascade:
    """The same endpoint branches on outcome, and MISSED only frees capacity."""

    def test_a_missed_visit_closes_the_slot_and_nothing_else(self):
        """PRD §3.7: "An `outcome` of `MISSED` — nobody home, or the crew ran out of daylight — advances the appointment `BOOKED → MISSED`, stamps `closed_at` from the logical clock, subtracts the slot's `units` from the route's `booked_units` so `available_units` is restored, reverts the return case `PICKUP_SCHEDULED → REQUESTED`, and bumps the route's `version`."

        None of the four hops that a COMPLETED outcome would fire happen here: the
        case is not priced, the order's axes do not move, the customer's return
        counter stays at zero and no abuse signal is appended — only the two units
        of truck capacity come back.

        Design: Corner/endpoints/a_missed_pickup_closes_the_visit_without_running_the_return_cascade
        """
        scenario = setup_return_lifecycle(
            stage="PICKUP_SCHEDULED",
            model_overrides={
                "sku": "MDL-Q-X3", "name": "Comfort Q", "list_price_cents": 120000
            },
            customer_overrides={
                "email": "x3@example.com",
                "full_name": "Xen Three",
                "household_hash": "HH-X3",
            },
            route_overrides={"capacity_units": 6},
        )
        appointment = scenario["appointment"]
        return_case = scenario["return_case"]
        customer = scenario["customer"]

        missed = complete_appointment(
            appointment["id"], "MISSED", at="2026-09-15T00:00:00Z"
        )
        assert missed["status"] == "MISSED"
        assert missed["units"] == 2

        route = read_route(scenario["route"]["id"])
        assert route["booked_units"] == 0
        assert route["available_units"] == 6

        reloaded_case = read_return_case(return_case["id"])
        assert reloaded_case["logistics_status"] == "REQUESTED", (
            "a missed visit reverts the case so it can be rebooked, got "
            f"{reloaded_case['logistics_status']}"
        )
        assert reloaded_case["picked_up_at"] is None
        assert reloaded_case["nights_used"] is None

        order = read_order(scenario["order"]["id"])
        assert order["trial_status"] == "RETURN_REQUESTED"
        assert order["fulfillment_status"] == "DELIVERED"

        reloaded_customer = read_customer(customer["id"])
        assert reloaded_customer["completed_return_count"] == 0
        assert reloaded_customer["signal_count"] == 0

        _rows, meta = validate_paginated(
            api_client.list_customer_abuse_signals(customer["id"], ADMIN)
        )
        assert meta["total_count"] == 0, (
            "hop three never ran, so no abuse signal exists"
        )


class TestFilteringHappensBeforePaging:
    """total_count counts the filtered population, not the whole collection."""

    def test_a_status_filter_narrows_the_population_the_page_window_slides_over(self):
        """PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`, `total_count` (the number of records matching the filters before pagination is applied) and `has_more` (true when records remain beyond the current page)."

        One customer holds three orders created on three different days, of which
        only the first two were delivered. A DELIVERED filter with limit 1 and
        offset 1 therefore reports total_count 2 — not 3 — returns the second
        delivered order in created_at order, and reports has_more false because the
        window has reached the end of the filtered set.

        Design: Corner/endpoints/trial_order_listing_combines_a_status_filter_with_limit_and_offset
        """
        set_clock("2026-07-25T00:00:00Z")
        model = create_model(
            sku="MDL-Q-X4", name="Comfort Q", list_price_cents=120000
        )
        customer = create_customer_row(
            email="x4@example.com", full_name="Xia Four", household_hash="HH-X4"
        )

        orders = []
        for day in ("2026-07-25", "2026-07-26", "2026-07-27"):
            set_clock(f"{day}T00:00:00Z")
            orders.append(
                validate_success(
                    api_client.create_trial_order(
                        trial_order_payload(
                            customer["id"], model["id"], gross_price_cents=120000
                        ),
                        AGENT,
                    ),
                    201,
                )
            )

        set_clock("2026-08-01T00:00:00Z")
        for order in orders[:2]:
            get_success_data(api_client.dispatch_trial_order(order["id"], {}, LOGISTICS))
            get_success_data(api_client.deliver_trial_order(order["id"], {}, LOGISTICS))

        rows, meta = validate_paginated(
            api_client.list_trial_orders(
                AGENT,
                params={
                    "customer_id": customer["id"],
                    "fulfillment_status": "DELIVERED",
                    "limit": 1,
                    "offset": 1,
                },
            )
        )
        assert meta["total_count"] == 2, (
            "only two of the three orders are DELIVERED, got "
            f"{meta['total_count']}"
        )
        assert meta["limit"] == 1
        assert meta["offset"] == 1
        assert meta["has_more"] is False
        assert len(rows) == 1
        assert rows[0]["id"] == orders[1]["id"], (
            "created_at ascending puts the second delivered order at offset 1"
        )

        _all_rows, all_meta = validate_paginated(
            api_client.list_trial_orders(AGENT, params={"customer_id": customer["id"]})
        )
        assert all_meta["total_count"] == 3
        assert all_meta["limit"] == 10, (
            f"limit defaults to 10 when omitted, got {all_meta['limit']}"
        )
        assert all_meta["offset"] == 0
        assert all_meta["has_more"] is False

        third = read_order(orders[2]["id"])
        assert third["fulfillment_status"] == "CREATED"
        assert third["trial_status"] == "NOT_STARTED"
