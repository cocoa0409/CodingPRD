"""Refusals on the retail-partner side and in the pickup, disposition and refund lanes.

Each rule is isolated by making every neighbouring rule pass, so the error id the
API returns is the only one it could legitimately choose.
"""

from test_helpers import (
    FINANCE,
    LOGISTICS,
    ApiErrorId,
    api_client,
    attribution_claim_payload,
    create_retail_partner_row,
    disposition_payload,
    make_finance_controller_headers,
    make_retail_partner_headers,
    pickup_appointment_payload,
    read_return_case,
    read_route,
    refund_authorization_payload,
    set_clock,
    setup_delivered_order,
    setup_partner_channel_order,
    setup_published_route,
    setup_return_lifecycle,
    validate_error,
    validate_paginated,
)

AUTHORIZER_V19 = make_finance_controller_headers("fin-v19-a")


class TestAttributionWindowIsInclusive:
    """Day thirty is still open; day thirty-one is not."""

    def test_a_claim_thirty_one_days_after_delivery_is_refused(self):
        """PRD §3.10: "The attribution window is the whole number of complete days between the order's `delivered_at` and the claim's `submitted_at`, and it may not exceed the partner's `attribution_window_days`; the boundary is inclusive, so a claim submitted exactly on the window's last day is still open, and anything later is refused with `ERR_ATTRIBUTION_WINDOW_CLOSED`."

        With the default 30-day window and a 2026-08-01 delivery, 2026-09-01 is 31
        whole days out — the first refused day — and no claim row is written.

        Design: Corner/validations/attribution_claim_one_day_past_the_window_returns_attribution_window_closed
        """
        scenario = setup_partner_channel_order(
            partner_overrides={"name": "Sleep Gallery V5", "region_code": "CA"},
            model_overrides={
                "sku": "MDL-Q-V5", "name": "Comfort Q", "list_price_cents": 120000
            },
            customer_overrides={
                "email": "v5@example.com",
                "full_name": "Vic Five",
                "household_hash": "HH-V5",
            },
        )
        partner = scenario["partner"]
        order = scenario["order"]
        assert partner["attribution_window_days"] == 30

        set_clock("2026-09-01T00:00:00Z")
        response = api_client.create_attribution_claim(
            attribution_claim_payload(
                partner["id"], order["id"], "SALES_ATTRIBUTION", 3
            ),
            scenario["partner_headers"],
        )
        validate_error(response, ApiErrorId.ERR_ATTRIBUTION_WINDOW_CLOSED)

        _rows, meta = validate_paginated(
            api_client.list_attribution_claims(FINANCE, params={"order_id": order["id"]})
        )
        assert meta["total_count"] == 0
        assert order["price_match_credit_cents"] == 0


class TestAttributionEvidenceFloor:
    """Two evidence links are the minimum on any attribution claim."""

    def test_a_claim_with_a_single_evidence_link_is_refused(self):
        """PRD §3.10: "Independently, at least two evidence links are required on any claim, whether at first submission or on a resubmission, and falling short answers `ERR_INSUFFICIENT_EVIDENCE`."

        The clock sits at 2026-08-10, well inside the 30-day window, so the only
        defect is the single evidence link, and the partner ends up with no claims
        on file at all.

        Design: Corner/validations/attribution_claim_with_one_evidence_url_returns_insufficient_evidence
        """
        scenario = setup_partner_channel_order(
            partner_overrides={"name": "Sleep Gallery V10", "region_code": "CA"},
            model_overrides={
                "sku": "MDL-Q-V10", "name": "Comfort Q", "list_price_cents": 120000
            },
            customer_overrides={
                "email": "v10@example.com",
                "full_name": "Vin Ten",
                "household_hash": "HH-V10",
            },
        )
        partner = scenario["partner"]

        set_clock("2026-08-10T00:00:00Z")
        response = api_client.create_attribution_claim(
            attribution_claim_payload(
                partner["id"], scenario["order"]["id"], "SALES_ATTRIBUTION", 1
            ),
            scenario["partner_headers"],
        )
        validate_error(response, ApiErrorId.ERR_INSUFFICIENT_EVIDENCE)

        _rows, meta = validate_paginated(
            api_client.list_attribution_claims(
                FINANCE, params={"partner_id": partner["id"]}
            )
        )
        assert meta["total_count"] == 0


class TestSalesAttributionNeedsThePartnerChannel:
    """A partner cannot claim commission on a direct sale."""

    def test_a_claim_on_a_dtc_order_is_refused(self):
        """PRD §3.10: "A sales-attribution claim additionally requires that the order's `channel` be `RETAIL_PARTNER` and that its `retail_partner_id` equal the claiming `partner_id`; a claim on a direct-channel order, or on an order attributed to somebody else, is refused with `ERR_ATTRIBUTION_CHANNEL_MISMATCH`."

        The claim payload itself is perfectly good — three evidence links, ten days
        after delivery — but the order was sold on the DTC channel and carries no
        partner at all.

        Design: Corner/validations/sales_attribution_on_a_dtc_order_returns_attribution_channel_mismatch
        """
        set_clock("2026-08-01T00:00:00Z")
        partner = create_retail_partner_row(
            name="Sleep Gallery V14", region_code="CA", commission_bps=800
        )
        scenario = setup_delivered_order(
            model_overrides={
                "sku": "MDL-Q-V14", "name": "Comfort Q", "list_price_cents": 120000
            },
            customer_overrides={
                "email": "v14@example.com",
                "full_name": "Vera Fourteen",
                "household_hash": "HH-V14",
            },
            order_overrides={"channel": "DTC"},
        )
        order = scenario["order"]

        set_clock("2026-08-10T00:00:00Z")
        response = api_client.create_attribution_claim(
            attribution_claim_payload(
                partner["id"], order["id"], "SALES_ATTRIBUTION", 3
            ),
            make_retail_partner_headers(partner["id"]),
        )
        validate_error(response, ApiErrorId.ERR_ATTRIBUTION_CHANNEL_MISMATCH)

        _rows, meta = validate_paginated(
            api_client.list_attribution_claims(
                FINANCE, params={"partner_id": partner["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert order["channel"] == "DTC"
        assert order["retail_partner_id"] is None


class TestPriceMatchRequiresAPolicy:
    """A partner who does not price-match cannot file a price-match claim."""

    def test_a_price_match_claim_against_a_no_match_partner_is_refused(self):
        """PRD §3.10: "A price-match claim additionally requires that the partner's `price_match_policy` not be `NO_MATCH`, and a claim against a partner who simply does not price-match is refused with `ERR_PRICE_MATCH_NOT_OFFERED`."

        The competitor's 100000-cent price really is lower than the 120000-cent
        order and the evidence count is sufficient, but the partner's configured
        policy is NO_MATCH, so nothing is filed and the order's credit stays zero.

        Design: Corner/validations/price_match_against_a_no_match_partner_returns_price_match_not_offered
        """
        scenario = setup_partner_channel_order(
            partner_overrides={
                "name": "Sleep Gallery V15",
                "region_code": "CA",
                "price_match_policy": "NO_MATCH",
            },
            model_overrides={
                "sku": "MDL-Q-V15", "name": "Comfort Q", "list_price_cents": 120000
            },
            customer_overrides={
                "email": "v15@example.com",
                "full_name": "Val Fifteen",
                "household_hash": "HH-V15",
            },
        )
        partner = scenario["partner"]
        order = scenario["order"]

        set_clock("2026-08-10T00:00:00Z")
        response = api_client.create_attribution_claim(
            attribution_claim_payload(
                partner["id"],
                order["id"],
                "PRICE_MATCH",
                3,
                competitor_price_cents=100000,
            ),
            scenario["partner_headers"],
        )
        validate_error(response, ApiErrorId.ERR_PRICE_MATCH_NOT_OFFERED)

        _rows, meta = validate_paginated(
            api_client.list_attribution_claims(
                FINANCE, params={"partner_id": partner["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert order["price_match_credit_cents"] == 0


class TestSlotMustLieInsideTheRouteWindow:
    """Containment is checked on both endpoints, before any capacity arithmetic."""

    def test_a_slot_starting_an_hour_early_is_refused(self):
        """PRD §3.7: "First, the slot must lie wholly inside the service window: `slot_start_at` must be at or after `window_start_at`, `slot_end_at` must be at or before `window_end_at`, and both instants must fall on the route's `route_date` when read in UTC. A slot that spills outside is refused with `ERR_SLOT_OUTSIDE_ROUTE_WINDOW`."

        A 07:00-09:00 slot starts one hour before the route's 08:00 window on an
        otherwise empty six-unit truck, so the booking is refused with the route's
        capacity ledger and version completely untouched.

        Design: Corner/validations/booking_a_slot_before_the_route_window_returns_slot_outside_route_window
        """
        scenario = setup_return_lifecycle(
            stage="REQUESTED",
            model_overrides={
                "sku": "MDL-Q-V16", "name": "Comfort Q", "list_price_cents": 120000
            },
            customer_overrides={
                "email": "v16@example.com",
                "full_name": "Vic Sixteen",
                "household_hash": "HH-V16",
            },
        )
        return_case = scenario["return_case"]
        route = setup_published_route(capacity_units=6)

        response = api_client.create_pickup_appointment(
            pickup_appointment_payload(
                route["id"],
                return_case["id"],
                route["version"],
                slot_start_at="2026-09-15T07:00:00Z",
                slot_end_at="2026-09-15T09:00:00Z",
            ),
            LOGISTICS,
        )
        validate_error(response, ApiErrorId.ERR_SLOT_OUTSIDE_ROUTE_WINDOW)

        reloaded = read_route(route["id"])
        assert reloaded["booked_units"] == 0
        assert reloaded["available_units"] == 6
        assert reloaded["version"] == route["version"], (
            "a refused booking must not bump the route version, got "
            f"{reloaded['version']} against {route['version']}"
        )
        assert read_return_case(return_case["id"])["logistics_status"] == "REQUESTED"

        _rows, meta = validate_paginated(
            api_client.list_pickup_appointments(
                LOGISTICS, params={"route_id": route["id"]}
            )
        )
        assert meta["total_count"] == 0


class TestDonationPreFilterRunsBeforePartnerSelection:
    """Grade C is not donatable, whatever the charity says it accepts."""

    def test_donating_a_grade_c_unit_is_refused(self):
        """PRD §3.8: "A donation request is pre-filtered before any partner is even considered: the mattress model's `donation_eligible` must be true, the `condition_grade` must be `A` or `B`, and `soil_flag` must be false. A request failing any of those three is refused outright with `ERR_DONATION_INELIGIBLE` — a soiled or badly worn mattress is not something a charity should be offered."

        An in-region charity that explicitly accepts grades A through D with six
        units a day is on file, yet the grade-C unit never reaches it: the request
        is refused and the case stays INSPECTED with its disposition PENDING.

        Design: Corner/validations/donating_a_grade_c_unit_returns_donation_ineligible
        """
        scenario = setup_return_lifecycle(
            stage="INSPECTED",
            model_overrides={
                "sku": "MDL-Q-V17",
                "name": "Comfort Q",
                "list_price_cents": 120000,
                "donation_eligible": True,
            },
            customer_overrides={
                "email": "v17@example.com",
                "full_name": "Val Seventeen",
                "household_hash": "HH-V17",
            },
            partner_specs=[
                {
                    "name": "Charity WIDE",
                    "partner_type": "CHARITY",
                    "region_code": "CA",
                    "daily_intake_capacity_units": 6,
                    "accepts_condition_grades": ["A", "B", "C", "D"],
                    "soil_policy": "REJECT_SOILED",
                    "priority_rank": 1,
                }
            ],
            condition_grade="C",
            soil_flag=False,
        )
        return_case = scenario["return_case"]
        inspected_version = return_case["version"]

        response = api_client.disposition_return_case(
            return_case["id"], disposition_payload("DONATION", "2026-09-16"), LOGISTICS
        )
        validate_error(response, ApiErrorId.ERR_DONATION_INELIGIBLE)

        _rows, meta = validate_paginated(
            api_client.list_disposition_assignments(
                LOGISTICS, params={"return_case_id": return_case["id"]}
            )
        )
        assert meta["total_count"] == 0

        reloaded = read_return_case(return_case["id"])
        assert reloaded["logistics_status"] == "INSPECTED"
        assert reloaded["disposition"] == "PENDING"
        assert reloaded["version"] == inspected_version


class TestEmptyPartnerPoolPicksTheRightFailureCode:
    """Nobody in region is a different failure from everybody being full."""

    def test_recycling_with_only_an_out_of_region_recycler_is_refused(self):
        """PRD §3.8: "When the waterfall exhausts every type without finding an eligible partner, the two failure codes are distinguished by *why* nobody could take it, tested in a fixed order. If some partner of the last type tried satisfies every eligibility clause except the capacity clause — the right region, the right grade, the right soil policy, but its day is already full — the refusal is `ERR_PARTNER_INTAKE_CAPACITY_EXCEEDED`. Otherwise the refusal is `ERR_NO_DISPOSITION_PARTNER`."

        The only recycler on file serves TX while the route that collected the unit
        was in CA, so no partner passes even the non-capacity clauses and the
        refusal is the generic one, not the capacity one.

        Design: Corner/validations/recycling_with_no_in_region_partner_returns_no_disposition_partner
        """
        scenario = setup_return_lifecycle(
            stage="INSPECTED",
            model_overrides={
                "sku": "MDL-Q-V18",
                "name": "Comfort Q",
                "list_price_cents": 120000,
                "donation_eligible": False,
            },
            customer_overrides={
                "email": "v18@example.com",
                "full_name": "Vin Eighteen",
                "household_hash": "HH-V18",
            },
            partner_specs=[
                {
                    "name": "Recycler TX",
                    "partner_type": "RECYCLER",
                    "region_code": "TX",
                    "daily_intake_capacity_units": 20,
                    "accepts_condition_grades": ["A", "B", "C", "D"],
                    "soil_policy": "ACCEPT_SOILED",
                    "priority_rank": 1,
                    "recycle_fee_cents_per_unit": 5000,
                }
            ],
            condition_grade="A",
            soil_flag=False,
        )
        return_case = scenario["return_case"]
        out_of_region = scenario["partners"][0]
        inspected_version = return_case["version"]

        response = api_client.disposition_return_case(
            return_case["id"], disposition_payload("RECYCLE", "2026-09-16"), LOGISTICS
        )
        validate_error(response, ApiErrorId.ERR_NO_DISPOSITION_PARTNER)

        _rows, meta = validate_paginated(
            api_client.list_disposition_assignments(
                LOGISTICS, params={"partner_id": out_of_region["id"]}
            )
        )
        assert meta["total_count"] == 0

        reloaded = read_return_case(return_case["id"])
        assert reloaded["logistics_status"] == "INSPECTED"
        assert reloaded["disposition"] == "PENDING"
        assert reloaded["version"] == inspected_version


class TestOnlyOneLiveRefundAuthorizationPerCase:
    """A second authorization needs a voided predecessor to point at."""

    def test_a_second_authorization_without_a_supersede_reference_is_refused(self):
        """PRD §3.9: "The supersede reference has its own rule with two branches. When `supersedes_refund_id` is supplied, it must reference a refund authorization on this same return case whose `status` is `VOIDED`. When it is omitted, no non-voided authorization may already exist on this return case."

        The first authorization is still AUTHORIZED, so the ledger already carries a
        live claim on the money and the second attempt is refused; the original
        114000-cent authorization and the case's own money axis are untouched.

        Design: Corner/validations/second_refund_without_a_voided_predecessor_returns_refund_supersede_invalid
        """
        scenario = setup_return_lifecycle(
            stage="AUTHORIZED",
            model_overrides={
                "sku": "MDL-Q-V19",
                "name": "Comfort Q",
                "list_price_cents": 120000,
                "donation_eligible": True,
            },
            customer_overrides={
                "email": "v19@example.com",
                "full_name": "Vera Nineteen",
                "household_hash": "HH-V19",
            },
            authorizer_headers=AUTHORIZER_V19,
        )
        return_case = scenario["return_case"]
        first_refund = scenario["refund"]
        authorized_version = return_case["version"]

        response = api_client.create_refund_authorization(
            refund_authorization_payload(return_case["id"], authorized_version),
            AUTHORIZER_V19,
        )
        validate_error(response, ApiErrorId.ERR_REFUND_SUPERSEDE_INVALID)

        rows, meta = validate_paginated(
            api_client.list_refund_authorizations(
                AUTHORIZER_V19, params={"return_case_id": return_case["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [first_refund["id"]]
        assert rows[0]["status"] == "AUTHORIZED"
        assert rows[0]["net_refund_cents"] == 114000

        reloaded = read_return_case(return_case["id"])
        assert reloaded["financial_status"] == "AUTHORIZED"
        assert reloaded["version"] == authorized_version, (
            "a refused authorization must not bump the case version, got "
            f"{reloaded['version']} against {authorized_version}"
        )
