"""Back-issue sales: age-based pricing boundary, fulfillment's dependency on
issue finalization, and immediate revenue recognition at delivery."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    assert_back_issue_order,
    create_publication,
    create_issue,
    create_subscriber,
    drive_issue_to_mailed,
    drive_issue_to_finalized,
    set_clock,
    CM,
    FM,
)

CM_H = TEST_USERS["circulation_manager_headers"]
FM_H = TEST_USERS["fulfillment_manager_headers"]

BASE_PRICE = 1000


class TestBackIssueAgeMarkup:
    def _setup_finalized_back_issues(self, api):
        """Publication with base cover price 1000 and two FINALIZED issues:
        one whose cover date is exactly twelve months before the logical
        clock, one thirteen months before."""
        set_clock()  # 2026-08-01
        pub = create_publication(base_cover_price_cents=BASE_PRICE)
        issue_12mo = create_issue(
            pub["id"],
            cover_date="2025-08-01T00:00:00Z",
            editorial_close_date="2025-07-01T00:00:00Z",
            ad_close_date="2025-07-05T00:00:00Z",
            ship_to_printer_date="2025-07-10T00:00:00Z",
            mail_date="2025-08-01T00:00:00Z",
            newsstand_buffer_copies=100,
        )
        issue_13mo = create_issue(
            pub["id"],
            cover_date="2025-07-01T00:00:00Z",
            editorial_close_date="2025-06-01T00:00:00Z",
            ad_close_date="2025-06-05T00:00:00Z",
            ship_to_printer_date="2025-06-10T00:00:00Z",
            mail_date="2025-07-01T00:00:00Z",
            newsstand_buffer_copies=100,
        )
        drive_issue_to_finalized(pub["id"], issue_12mo["id"])
        drive_issue_to_finalized(pub["id"], issue_13mo["id"])
        subscriber = create_subscriber()
        return pub, issue_12mo, issue_13mo, subscriber

    def test_back_issue_at_exactly_twelve_months_has_no_markup(self, api):
        """The markup applies only when the cover date lies MORE than twelve
        months in the past; at exactly twelve months the unit price is the
        base price unchanged.

        PRD §3.7: "Pricing snapshots the publication's `base_cover_price_cents` at order time into `unit_price_cents`, with a markup for age: when the issue's `cover_date` lies more than twelve months in the past, the unit price is one and a half times the base, rounded half up to whole cents; otherwise it is the base price unchanged."
        PRD §3.7: "Either a `CirculationManager` or a `FulfillmentManager` may place a **BackIssueOrder** for a subscriber, naming the `issue_id` being ordered and a `quantity` greater than zero; the order is born `PENDING`."

        Design: Difficulty/boundary_precision_check/back_issue_markup_age_exactly_12_months
        """
        pub, issue_12mo, _, subscriber = self._setup_finalized_back_issues(api)
        resp = api.create_back_issue_order(
            pub["id"], subscriber["id"], {"issue_id": issue_12mo["id"], "quantity": 1}, CM_H
        )
        order = validate_success(resp, 201)
        assert_back_issue_order(order)
        assert order["status"] == "PENDING"
        assert order["unit_price_cents"] == BASE_PRICE, (
            f"cover date exactly twelve months back is not 'more than twelve months', "
            f"so the price stays at base 1000, got {order['unit_price_cents']}"
        )

    def test_back_issue_older_than_twelve_months_has_markup(self, api):
        """At thirteen months of age the markup applies: unit price is one and
        a half times the 1000-cent base, i.e. 1500.

        PRD §3.7: "Pricing snapshots the publication's `base_cover_price_cents` at order time into `unit_price_cents`, with a markup for age: when the issue's `cover_date` lies more than twelve months in the past, the unit price is one and a half times the base, rounded half up to whole cents; otherwise it is the base price unchanged."

        Design: Difficulty/boundary_precision_check/back_issue_markup_age_exactly_12_months
        """
        pub, _, issue_13mo, subscriber = self._setup_finalized_back_issues(api)
        resp = api.create_back_issue_order(
            pub["id"], subscriber["id"], {"issue_id": issue_13mo["id"], "quantity": 1}, CM_H
        )
        order = validate_success(resp, 201)
        assert order["unit_price_cents"] == 1500, (
            f"13 months old triggers the 1.5x markup: round_half_up(1000*1.5)=1500, "
            f"got {order['unit_price_cents']}"
        )


class TestFulfillDependsOnIssueFinalized:
    def _setup_mailed_issue_with_order(self, api):
        """Issue driven to MAILED (not yet FINALIZED) plus a PENDING order."""
        set_clock()
        pub = create_publication()
        issue = create_issue(pub["id"], newsstand_buffer_copies=50)
        drive_issue_to_mailed(pub["id"], issue["id"])
        subscriber = create_subscriber()
        order = validate_success(
            api.create_back_issue_order(
                pub["id"], subscriber["id"], {"issue_id": issue["id"], "quantity": 1}, CM_H
            ), 201,
        )
        return pub, issue, subscriber, order

    def test_fulfill_rejected_until_issue_finalized(self, api):
        """A MAILED-but-not-FINALIZED issue blocks fulfillment with
        ERR_ISSUE_NOT_FINALIZED.

        PRD §3.7: "Fulfillment walks the order through `PENDING → FULFILLED → SHIPPED → DELIVERED`, each step taken by a `FulfillmentManager`. Fulfilling requires the issue to be `FINALIZED` (`ERR_ISSUE_NOT_FINALIZED` otherwise) and sufficient remaining inventory, and it decrements the issue's available newsstand inventory."

        Design: Difficulty/cross_entity_state_dependency/back_issue_order_fulfill_depends_on_issue_finalized
        """
        pub, issue, subscriber, order = self._setup_mailed_issue_with_order(api)
        resp = api.fulfill_back_issue_order(pub["id"], order["id"], FM_H)
        validate_error(resp, ApiErrorId.ERR_ISSUE_NOT_FINALIZED, 409)

    def test_fulfill_succeeds_after_issue_finalized(self, api):
        """Once the issue crosses MAILED → FINALIZED, the same fulfill call
        succeeds and moves the order to FULFILLED.

        PRD §3.7: "Fulfillment walks the order through `PENDING → FULFILLED → SHIPPED → DELIVERED`, each step taken by a `FulfillmentManager`. Fulfilling requires the issue to be `FINALIZED` (`ERR_ISSUE_NOT_FINALIZED` otherwise) and sufficient remaining inventory, and it decrements the issue's available newsstand inventory."
        PRD §3.5: "Once the mail has gone, a `ProductionManager` finalizes the issue, moving it from `MAILED` to `FINALIZED`."

        Design: Difficulty/cross_entity_state_dependency/back_issue_order_fulfill_depends_on_issue_finalized
        """
        pub, issue, subscriber, order = self._setup_mailed_issue_with_order(api)
        finalized = validate_success(api.finalize_issue(pub["id"], issue["id"], TEST_USERS["production_manager_headers"]))
        assert finalized["status"] == "FINALIZED"

        fulfilled = validate_success(api.fulfill_back_issue_order(pub["id"], order["id"], FM_H))
        assert_back_issue_order(fulfilled)
        assert fulfilled["status"] == "FULFILLED", (
            f"fulfill on a FINALIZED issue must succeed, got {fulfilled['status']}"
        )


class TestDeliveryRecognition:
    def test_delivered_order_recognizes_revenue_immediately(self, api):
        """Delivery flips is_recognized_revenue to true: back-issue revenue is
        recognized at delivery, never deferred.

        PRD §3.7: "Shipping and delivery follow without further conditions, and at delivery `is_recognized_revenue` flips to true: back-issue revenue is recognized immediately, never deferred per §2.10."

        Design: Corner/state_machines/back_issue_order_delivered_sets_recognized_revenue_true
        """
        set_clock()
        pub = create_publication()
        issue = create_issue(pub["id"], newsstand_buffer_copies=10)
        drive_issue_to_finalized(pub["id"], issue["id"])
        subscriber = create_subscriber()
        order = validate_success(
            api.create_back_issue_order(
                pub["id"], subscriber["id"], {"issue_id": issue["id"], "quantity": 1}, CM_H
            ), 201,
        )
        assert order["is_recognized_revenue"] is False

        validate_success(api.fulfill_back_issue_order(pub["id"], order["id"], FM_H))
        validate_success(api.ship_back_issue_order(pub["id"], order["id"], FM_H))
        delivered = validate_success(api.deliver_back_issue_order(pub["id"], order["id"], FM_H))
        assert delivered["status"] == "DELIVERED"
        assert delivered["is_recognized_revenue"] is True, (
            "delivery recognizes back-issue revenue immediately"
        )
