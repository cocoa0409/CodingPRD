"""Contract bid adjudication (revision loop, closed-window overlap), sample
trial conversion (credit math, trial_end boundary, single-active-trial), and
the monotonic logical clock."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    award_bid,
    bid_to_under_review,
    create_contract_bid,
    create_product,
    create_trial_program,
    get_order,
    get_trial_program,
    make_facility_manager_headers,
    setup_facility_with_product,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["distributor_admin_headers"]


class TestBidRevisionLoop:
    def test_return_for_revision_drops_to_draft_with_bump(self, api):
        """PRD: "returning for revision drops back to `DRAFT` and increments
        `revision_number` by one, closing the revision loop"

        Design: Difficulty/non_linear_state_machine/contract_bid_revision_loop
        """
        product = create_product(sku="SKU-B1", name="BidProd")
        bid = create_contract_bid(product, facility_group_code="GPO-2",
                                  bid_reference="BID-1")
        bid = bid_to_under_review(bid)
        assert bid["status"] == "UNDER_REVIEW"
        revised = validate_success(api.return_bid_for_revision(
            bid["id"], TEST_USERS["sales_rep_headers"]))
        assert revised["status"] == "DRAFT"
        assert revised["revision_number"] == 1

    def test_revision_loop_closes_and_repeats(self, api):
        """PRD: "The bid lifecycle is a cycle with adjudication at its apex.
        Submitting moves `DRAFT → SUBMITTED` (stamping `submitted_at`),
        opening review moves `SUBMITTED → UNDER_REVIEW`, and from
        `UNDER_REVIEW` a `SalesRep` has two exits — returning for revision
        drops back to `DRAFT` and increments `revision_number` by one,
        closing the revision loop, while marking lost lands in the terminal
        `LOST` state."

        Design: Difficulty/non_linear_state_machine/contract_bid_revision_loop
        """
        product = create_product(sku="SKU-B1", name="BidProd")
        bid = create_contract_bid(product, facility_group_code="GPO-2",
                                  bid_reference="BID-1")
        bid_to_under_review(bid)
        validate_success(api.return_bid_for_revision(
            bid["id"], TEST_USERS["sales_rep_headers"]))
        resubmitted = validate_success(api.submit_bid(
            bid["id"], TEST_USERS["sales_rep_headers"]))
        assert resubmitted["status"] == "SUBMITTED"
        reopened = validate_success(api.open_review_bid(
            bid["id"], TEST_USERS["sales_rep_headers"]))
        assert reopened["status"] == "UNDER_REVIEW", (
            "The cycle may repeat")


class TestProtectionWindowOverlap:
    def _setup_touching_bids(self, api):
        product = create_product(sku="SKU-BID", name="BidChem",
                                 category="CHEMICAL", base_price_cents=2500,
                                 unit_of_measure="GAL",
                                 chemical_family="NEUTRAL", qty_on_hand=50)
        bid_one = create_contract_bid(
            product, facility_group_code="GPO-3", bid_price_cents=2000,
            bid_reference="BID-W1",
            protection_start="2026-09-01T00:00:00Z",
            protection_end="2026-12-31T00:00:00Z")
        bid_to_under_review(bid_one)
        award_bid(bid_one["id"])
        bid_two = create_contract_bid(
            product, facility_group_code="GPO-3", bid_price_cents=1900,
            bid_reference="BID-W2",
            protection_start="2026-12-31T00:00:00Z",
            protection_end="2027-03-31T00:00:00Z")
        bid_two = bid_to_under_review(bid_two)
        return bid_one, bid_two

    def test_touching_closed_window_endpoints_conflict(self, api):
        """PRD: "no other `AWARDED` bid for the same `facility_group_code`
        sharing any line product may have a protection window that intersects
        this bid's window, where windows are closed intervals — both endpoints
        inclusive — and windows that merely touch at an endpoint do intersect;
        a conflict is rejected with `ERR_PROTECTION_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/awarded_bid_closed_windows_endpoint_touch_conflicts
        """
        _bid_one, bid_two = self._setup_touching_bids(api)
        resp = api.award_bid(bid_two["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_PROTECTION_WINDOW_OVERLAP)

    def test_rejected_award_leaves_bid_under_review(self, api):
        """PRD: "no other `AWARDED` bid for the same `facility_group_code`
        sharing any line product may have a protection window that intersects
        this bid's window, where windows are closed intervals — both endpoints
        inclusive — and windows that merely touch at an endpoint do intersect;
        a conflict is rejected with `ERR_PROTECTION_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/awarded_bid_closed_windows_endpoint_touch_conflicts
        """
        _bid_one, bid_two = self._setup_touching_bids(api)
        resp = api.award_bid(bid_two["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_PROTECTION_WINDOW_OVERLAP)
        after = validate_success(api.get_contract_bid(bid_two["id"], ADMIN))
        assert after["status"] == "UNDER_REVIEW", (
            "The rejected award leaves the bid UNDER_REVIEW")


class TestTrialConversion:
    def test_trial_conversion_credit_math(self, api):
        """PRD: "The trial's reward is a credit: `conversion_credit_cents` is
        the smaller of the trial's `sample_value_cents` and the conversion
        order's `merchandise_subtotal_cents`, applied to the order as
        `trial_credit_cents` so the rollup floors the total at zero."
        PRD: "On success the trial moves to the terminal `CONVERTED` state
        with its `conversion_order_id` set, and the facility's
        `committed_cents` rises by the conversion order's `total_cents`."

        Design: Corner/calculations/trial_conversion_credit_math
        """
        facility, product = setup_facility_with_product(
            facility_name="Fac AF", category="EQUIPMENT",
            base_price_cents=2500, unit_of_measure="EACH")
        trial = create_trial_program(facility, product,
                                     sample_value_cents=4000)
        converted = validate_success(api.convert_trial(
            trial["id"], qty=2, delivery_date="2026-08-10T00:00:00Z",
            fuel_index=2.5,
            headers=make_facility_manager_headers(facility["id"])))
        assert converted["status"] == "CONVERTED"
        assert converted["conversion_credit_cents"] == 4000, (
            "min(sample_value 4000, subtotal 5000) = 4000")
        order = get_order(converted["conversion_order_id"])
        assert order["source"] == "TRIAL_CONVERSION"
        assert order["status"] == "PLACED"
        assert order["merchandise_subtotal_cents"] == 5000
        assert order["delivery_fee_cents"] == 0
        assert order["fuel_surcharge_cents"] == 200
        assert order["trial_credit_cents"] == 4000
        assert order["total_cents"] == 1200
        refreshed = validate_success(api.get_facility(facility["id"], ADMIN))
        assert refreshed["committed_cents"] == 1200

    def test_trial_convert_at_trial_end_boundary_allowed(self, api):
        """PRD: "The trial must be `ACTIVE`, and the clock must be on or
        before `trial_end` — conversion at the exact `trial_end` instant is
        allowed."

        Design: Corner/calculations/trial_convert_at_trial_end_boundary_allowed
        """
        facility, product = setup_facility_with_product(
            facility_name="Fac AG", category="EQUIPMENT",
            base_price_cents=2500, unit_of_measure="EACH")
        trial = create_trial_program(facility, product,
                                     sample_value_cents=1000)
        validate_success(api.set_clock("2026-08-15T00:00:00Z", ADMIN))
        converted = validate_success(api.convert_trial(
            trial["id"], qty=1, delivery_date="2026-08-16T00:00:00Z",
            fuel_index=2.5,
            headers=make_facility_manager_headers(facility["id"])))
        assert converted["status"] == "CONVERTED", (
            "Conversion at the exact trial_end instant is allowed")
        assert converted["conversion_order_id"]

    def test_trial_already_active_returns_error(self, api):
        """PRD: "Trials are born `ACTIVE`, and at most one `ACTIVE` trial may
        exist per facility-and-product pairing — a duplicate create draws
        `ERR_TRIAL_ALREADY_ACTIVE`."

        Design: Corner/validations/trial_already_active_returns_error
        """
        facility, product = setup_facility_with_product(
            facility_name="Fac AL", category="EQUIPMENT",
            base_price_cents=2500, unit_of_measure="EACH")
        create_trial_program(facility, product, sample_value_cents=1000)
        resp = api.create_trial_program(
            {"facility_id": facility["id"], "product_id": product["id"],
             "trial_start": "2026-08-02T00:00:00Z",
             "trial_end": "2026-08-20T00:00:00Z",
             "sample_value_cents": 500},
            TEST_USERS["sales_rep_headers"])
        validate_error(resp, ApiErrorId.ERR_TRIAL_ALREADY_ACTIVE)


class TestLogicalClock:
    def test_clock_regression_returns_error(self, api):
        """PRD: "The clock is monotonic: an administrator advances it by
        supplying a `to_iso8601` timestamp, and the capability returns the new
        `current_utc`. Setting the clock to a timestamp earlier than the
        current logical time is rejected with `ERR_CLOCK_REGRESSION`; setting
        it to the current time or any later time is accepted."

        Design: Corner/errors/clock_regression_returns_error
        """
        first = validate_success(api.set_clock("2026-08-02T00:00:00Z", ADMIN))
        assert first["current_utc"].startswith("2026-08-02T00:00:00")
        resp = api.set_clock("2026-08-01T00:00:00Z", ADMIN)
        validate_error(resp, ApiErrorId.ERR_CLOCK_REGRESSION, 400)
