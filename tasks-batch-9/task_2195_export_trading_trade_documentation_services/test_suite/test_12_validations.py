"""The validation ladder: which of two simultaneous failures the client is told about."""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    COMPLIANCE_CARL,
    FINANCE_FRANK,
    NON_EXISTENT_UUID,
    OPS_ALICE,
    REVIEWER_BOB,
    USER_IDS,
    ApiErrorId,
    approx_money,
    assert_order_dimensions,
    factories as f,
    fixtures as fx,
    make_buyer_headers,
    make_reviewer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

Json = Dict[str, Any]


class TestRoleCheckOutranksResolution:
    def test_an_unauthorised_role_hears_about_the_role_not_the_missing_row(self, api):
        """PRD §2.1: "If the role is recognised but is not listed among the
        authorised roles for the endpoint being called (see the table in §4), the
        rejection is `ERR_ROLE_NOT_PERMITTED` (403)."

        Design: Corner/validations/corner_role_check_precedes_path_parameter_resolution
        """
        buyer = fx.create_buyer(api)

        body = validate_error(
            api.get_policy(NON_EXISTENT_UUID, make_buyer_headers(buyer["id"])),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
            403,
        )
        assert body["error_id"] != ApiErrorId.ERR_POLICY_NOT_FOUND.value
        assert body["error_id"] != ApiErrorId.ERR_BUYER_SCOPE_VIOLATION.value
        assert isinstance(body["message"], str) and body["message"]

        _, meta = validate_paginated(
            api.list_policies(FINANCE_FRANK, {"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 0


class TestPathParametersOutrankBodyForeignKeys:
    def test_a_double_miss_names_the_path_identifier(self, api):
        """PRD §2.4: "Path parameters are resolved left to right, and the first
        identifier in the path that does not resolve determines the 404 that is
        returned."

        Design: Corner/validations/corner_path_parameter_resolves_before_body_foreign_key
        """
        body = validate_error(
            api.clear_with_license(
                NON_EXISTENT_UUID,
                {"export_license_id": "00000000-0000-0000-0000-00000000beef"},
                COMPLIANCE_CARL,
            ),
            ApiErrorId.ERR_SCREENING_NOT_FOUND.value,
            404,
        )
        assert body["error_id"] != ApiErrorId.ERR_LICENSE_NOT_FOUND.value
        assert "00000000-0000-0000-0000-00000000beef" not in body["message"]

        _, meta = validate_paginated(
            api.list_screenings(COMPLIANCE_CARL, {"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 0


class TestPaginationBoundsAreCheckedBeforeFilters:
    def test_a_limit_of_one_hundred_and_one_is_refused_while_one_hundred_passes(
        self, api
    ):
        """PRD §2.3: "A `limit` that is not an integer within 1 through 100
        inclusive, or an `offset` that is not an integer of at least 0, is rejected
        with `ERR_INVALID_PAGINATION` (422)."

        Design: Corner/validations/corner_pagination_bounds_rejected_before_any_filtering
        """
        over = validate_error(
            api.list_documents(OPS_ALICE, {"limit": 101, "offset": 0}),
            ApiErrorId.ERR_INVALID_PAGINATION.value,
            422,
        )
        assert over["error_id"] != ApiErrorId.ERR_VALIDATION.value

        under = validate_error(
            api.list_documents(OPS_ALICE, {"limit": 10, "offset": -1}),
            ApiErrorId.ERR_INVALID_PAGINATION.value,
            422,
        )
        assert under["error_id"] != ApiErrorId.ERR_VALIDATION.value

        rows, meta = validate_paginated(
            api.list_documents(OPS_ALICE, {"limit": 100, "offset": 0})
        )
        assert rows == []
        assert meta["total_count"] == 0
        assert meta["has_more"] is False


class TestCrossFieldConsistencyInsideOneBody:
    def test_a_sight_credit_with_a_tenor_is_inconsistent_rather_than_invalid(self, api):
        """PRD §3.4: "`usance_days` and `availability` must agree inside the same
        body: `usance_days` must be exactly 0 when `availability` is `SIGHT`, and at
        least 30 when `availability` is `USANCE`."

        Design: Corner/validations/corner_sight_credit_with_usance_days_is_inconsistent_terms
        """
        buyer = fx.create_buyer(api)
        order = fx.create_order(api, buyer["id"])

        sight = validate_error(
            api.capture_credit(
                f.credit_payload(
                    order["id"],
                    lc_number="LC-2026-0010",
                    availability="SIGHT",
                    usance_days=45,
                ),
                OPS_ALICE,
            ),
            ApiErrorId.ERR_INCONSISTENT_TERMS.value,
            422,
        )
        assert sight["error_id"] != ApiErrorId.ERR_VALIDATION.value

        usance = validate_error(
            api.capture_credit(
                f.credit_payload(
                    order["id"],
                    lc_number="LC-2026-0011",
                    availability="USANCE",
                    usance_days=15,
                ),
                OPS_ALICE,
            ),
            ApiErrorId.ERR_INCONSISTENT_TERMS.value,
            422,
        )
        assert usance["error_id"] != ApiErrorId.ERR_VALIDATION.value

        _, meta = validate_paginated(
            api.list_credits(
                OPS_ALICE,
                {"export_order_id": order["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 0


class TestDecimalScaleIsARangeOfItsOwn:
    def test_a_fourth_decimal_on_a_three_decimal_quantity_is_refused(self, api):
        """PRD §2.11: "Body field types, enum membership, decimal scale and numeric
        ranges match the field constraints described in §3, on every endpoint —
        otherwise `ERR_VALIDATION` (422)."

        Design: Corner/validations/corner_decimal_scale_over_declared_precision_is_rejected
        """
        buyer = fx.create_buyer(api)
        order = fx.create_order(api, buyer["id"])
        version_before = order["version"]

        validate_error(
            api.add_shipment_line(
                order["id"], f.shipment_line_payload(quantity=10.0001), OPS_ALICE
            ),
            ApiErrorId.ERR_VALIDATION.value,
            422,
        )

        _, meta = validate_paginated(
            api.list_order_shipment_lines(
                order["id"], OPS_ALICE, {"limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 0

        after = fx.read_order(api, order["id"])
        assert after["ordered_goods_value_usd"] == approx_money(0.00)
        assert after["version"] == version_before


class TestDisputeMoneyBoundsAreTypeConditional:
    def test_a_short_shipment_claim_is_bounded_by_the_short_shipped_value(self, api):
        """PRD §2.11: "Dispute money bounds hold: `claimed_amount_usd` is at most the
        order's `ordered_goods_value_usd`, and for a `SHORT_SHIPMENT` dispute
        additionally at most the order's `short_shipped_value_usd`
        (`ERR_CLAIM_AMOUNT_INVALID`)"

        Design: Corner/validations/corner_short_shipment_claim_is_bounded_by_short_shipped_value_not_order_value
        """
        ctx = fx.order_with_lines(api)
        order = fx.read_order(api, ctx["order_id"])
        assert order["ordered_goods_value_usd"] == approx_money(25000.00)
        assert order["short_shipped_value_usd"] == approx_money(0.00)

        validate_error(
            api.open_dispute(
                f.dispute_payload(
                    ctx["order_id"],
                    dispute_type="SHORT_SHIPMENT",
                    claimed_amount_usd=5000.00,
                ),
                ctx["buyer_headers"],
            ),
            ApiErrorId.ERR_CLAIM_AMOUNT_INVALID.value,
            422,
        )

        quality = validate_success(
            api.open_dispute(
                f.dispute_payload(
                    ctx["order_id"],
                    dispute_type="QUALITY",
                    claimed_amount_usd=5000.00,
                ),
                ctx["buyer_headers"],
            ),
            201,
        )
        assert quality["status"] == "OPEN"
        assert quality["claimed_amount_usd"] == approx_money(5000.00)

        rows, meta = validate_paginated(
            api.list_disputes(
                FINANCE_FRANK,
                {"export_order_id": ctx["order_id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["dispute_type"] == "QUALITY"


class TestOfferBoundsAreInclusive:
    def test_one_cent_above_the_claim_is_refused_and_the_claim_itself_is_accepted(
        self, api
    ):
        """PRD §2.11: "an offer is at most `claimed_amount_usd` and, when made from
        `COUNTERED`, additionally at most the standing `current_offer_usd`; a counter
        is strictly above the standing `current_offer_usd` and at most
        `claimed_amount_usd` (`ERR_OFFER_AMOUNT_INVALID`)"

        Design: Corner/validations/corner_offer_above_claimed_amount_is_rejected
        """
        ctx = fx.order_with_lines(api)
        dispute = fx.data(
            api.open_dispute(
                f.dispute_payload(
                    ctx["order_id"],
                    dispute_type="NON_PAYMENT",
                    claimed_amount_usd=5000.00,
                ),
                FINANCE_FRANK,
            )
        )

        validate_error(
            api.make_offer(dispute["id"], {"offer_amount_usd": 5000.01}, FINANCE_FRANK),
            ApiErrorId.ERR_OFFER_AMOUNT_INVALID.value,
            422,
        )

        standing = fx.data(api.get_dispute(dispute["id"], FINANCE_FRANK))
        assert standing["status"] == "OPEN"
        assert standing["current_offer_usd"] is None
        assert standing["negotiation_round"] == 0

        offered = validate_success(
            api.make_offer(dispute["id"], {"offer_amount_usd": 5000.00}, FINANCE_FRANK),
            200,
        )
        assert offered["status"] == "OFFERED"
        assert offered["current_offer_usd"] == approx_money(5000.00)


# ---------------------------------------------------------------------------
# Uniqueness indices and the scope each one is drawn over
# ---------------------------------------------------------------------------

SECOND_LINE = {
    "line_no": 1,
    "goods_description": "Valve bonnet",
    "quantity": 5.000,
    "unit_price_usd": 120.0000,
    "net_weight_kg": 150.000,
    "gross_weight_kg": 200.000,
    "package_count": 5,
}


class TestLineNumberIndexIsPerOrder:
    def test_the_same_line_number_collides_inside_one_order_and_passes_on_another(
        self, api
    ):
        """PRD §2.11: "Uniqueness holds: `lc_number` across credits whose `status` is
        neither `REJECTED` nor `EXPIRED` (`ERR_DUPLICATE_LC_NUMBER`);
        `license_number` globally (`ERR_DUPLICATE_LICENSE_NUMBER`); `policy_number`
        globally (`ERR_DUPLICATE_POLICY_NUMBER`); `line_no` within an order
        (`ERR_DUPLICATE_LINE_NO`)"

        Design: Corner/validations/corner_line_no_uniqueness_is_scoped_to_the_owning_order
        """
        buyer = fx.create_buyer(api)
        order_a = fx.create_order(api, buyer["id"])
        order_b = fx.create_order(api, buyer["id"], ship_by_date="2026-10-05T00:00:00Z")
        fx.add_line(
            api,
            order_a["id"],
            line_no=1,
            goods_description="Valve body",
            quantity=10.000,
            unit_price_usd=100.0000,
            net_weight_kg=350.000,
            gross_weight_kg=400.000,
        )

        validate_error(
            api.add_shipment_line(
                order_a["id"], f.shipment_line_payload(**SECOND_LINE), OPS_ALICE
            ),
            ApiErrorId.ERR_DUPLICATE_LINE_NO.value,
            409,
        )
        assert fx.read_order(api, order_a["id"])[
            "ordered_goods_value_usd"
        ] == approx_money(1000.00)

        accepted = validate_success(
            api.add_shipment_line(
                order_b["id"], f.shipment_line_payload(**SECOND_LINE), OPS_ALICE
            ),
            201,
        )
        assert accepted["line_no"] == 1

        for order_id in (order_a["id"], order_b["id"]):
            _, meta = validate_paginated(
                api.list_order_shipment_lines(
                    order_id, OPS_ALICE, {"limit": 10, "offset": 0}
                )
            )
            assert meta["total_count"] == 1


class TestVoyageIndexIsPerCarrier:
    def test_one_voyage_number_may_be_reused_by_a_different_carrier(self, api):
        """PRD §2.11: "`voyage_no` within a `carrier_scac` (`ERR_DUPLICATE_VOYAGE`)"

        Design: Corner/validations/corner_voyage_uniqueness_is_scoped_to_carrier_scac
        """
        fx.create_sailing(
            api, carrier_scac="HLCU", vessel_name="MV Pacific Trader", voyage_no="V2609E"
        )

        validate_error(
            api.create_sailing(
                f.sailing_payload(
                    carrier_scac="HLCU",
                    vessel_name="MV Pacific Voyager",
                    voyage_no="V2609E",
                    port_of_loading="USOAK",
                    cutoff_at="2026-09-20T00:00:00Z",
                    etd="2026-09-22T00:00:00Z",
                    eta="2026-10-10T00:00:00Z",
                    capacity_weight_kg=50000.000,
                    tariff_rate_per_1000kg_usd=310.00,
                ),
                OPS_ALICE,
            ),
            ApiErrorId.ERR_DUPLICATE_VOYAGE.value,
            409,
        )

        other_carrier = validate_success(
            api.create_sailing(
                f.sailing_payload(
                    carrier_scac="MAEU",
                    vessel_name="MV Gulf Runner",
                    voyage_no="V2609E",
                    port_of_discharge="AEJEA",
                    destination_zone="ZONE_3",
                    cutoff_at="2026-09-20T00:00:00Z",
                    etd="2026-09-22T00:00:00Z",
                    eta="2026-10-15T00:00:00Z",
                    capacity_weight_kg=50000.000,
                    tariff_rate_per_1000kg_usd=320.00,
                ),
                OPS_ALICE,
            ),
            201,
        )
        assert other_carrier["status"] == "OPEN"
        assert other_carrier["booked_weight_kg"] == 0.000

        validate_error(
            api.create_sailing(
                f.sailing_payload(
                    carrier_scac="ONEY",
                    vessel_name="MV Kyoto Bay",
                    voyage_no="V2610W",
                    cutoff_at="2026-09-22T00:00:00Z",
                    etd="2026-09-20T00:00:00Z",
                    eta="2026-10-10T00:00:00Z",
                ),
                OPS_ALICE,
            ),
            ApiErrorId.ERR_INCONSISTENT_TERMS.value,
            422,
        )


class TestCreditNumberIndexSkipsRejectedRows:
    def test_a_rejected_credit_frees_its_number_for_the_replacement(self, api):
        """PRD §3.4: "A `supersedes_lc_id` may be supplied to point at an earlier
        credit whose `status` is `REJECTED` or `EXPIRED`, forming a replacement
        chain; it is null for an original credit."

        Design: Corner/validations/corner_lc_number_may_be_reused_once_the_prior_credit_is_rejected
        """
        ctx = fx.order_with_lines(api)
        ctx = fx.captured_credit(api, ctx, lc_number="LC-2026-0020")
        ctx = fx.opened_terms_review(api, ctx)
        fx.data(
            api.raise_terms_finding(
                ctx["review_id"],
                f.terms_finding_payload(
                    code="AMOUNT_MISMATCH",
                    severity="CRITICAL",
                    clause_ref="AMOUNT",
                    detail="Credit amount below the order value",
                ),
                REVIEWER_BOB,
            )
        )

        replacement = f.credit_payload(
            ctx["order_id"],
            lc_number="LC-2026-0020",
            amount_usd=26000.00,
            expiry_date="2026-12-15T00:00:00Z",
            latest_shipment_date="2026-09-20T00:00:00Z",
        )
        validate_error(
            api.capture_credit(replacement, OPS_ALICE),
            ApiErrorId.ERR_DUPLICATE_LC_NUMBER.value,
            409,
        )
        assert fx.read_credit(api, ctx["lc_id"])["status"] == "UNDER_REVIEW"

        review = validate_success(
            api.submit_terms_review(
                ctx["review_id"], {"recommendation": "REJECT"}, REVIEWER_BOB
            ),
            200,
        )
        assert review["terms_risk_score"] == approx_money(60.00)
        assert fx.read_credit(api, ctx["lc_id"])["status"] == "REJECTED"

        second = validate_success(
            api.capture_credit(
                dict(replacement, supersedes_lc_id=ctx["lc_id"]), OPS_ALICE
            ),
            201,
        )
        assert second["supersedes_lc_id"] == ctx["lc_id"]
        assert second["amendment_round"] == 0
        assert second["status"] == "RECEIVED"
        assert second["lc_number"] == "LC-2026-0020"

        rows, meta = validate_paginated(
            api.list_credits(
                OPS_ALICE,
                {"export_order_id": ctx["order_id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 2
        assert {row["lc_number"] for row in rows} == {"LC-2026-0020"}


# ---------------------------------------------------------------------------
# Licence windows: closed intervals, inclusive on both ends
# ---------------------------------------------------------------------------


def _pending_license_screening(api, **license_overrides) -> Json:
    """A PENDING_LICENSE screening for ECCN 3A001 carrying one recorded licence."""
    ctx = fx.submitted_for_compliance(api)
    ctx["screening"] = fx.data(
        api.record_screening_decision(
            ctx["screening_id"],
            f.screening_decision_payload(
                license_determination="LICENSE_REQUIRED", eccn="3A001"
            ),
            COMPLIANCE_CARL,
        )
    )
    ctx["license"] = fx.data(
        api.create_license(
            ctx["screening_id"], f.license_payload(**license_overrides), COMPLIANCE_CARL
        )
    )
    ctx["license_id"] = ctx["license"]["id"]
    return ctx


class TestLicenceWindowsAreClosedIntervals:
    def test_a_second_licence_starting_on_the_first_ones_last_day_overlaps(self, api):
        """PRD §3.3: "No other license for the same buyer and the same `eccn`, in
        `status` `ISSUED`, `ACTIVE` or `EXHAUSTED`, may have a validity interval that
        intersects the requested one, and because both endpoints are inclusive,
        **touching intervals do overlap**"

        Design: Corner/validations/corner_license_window_overlap_uses_closed_interval_so_touching_endpoints_collide
        """
        ctx = _pending_license_screening(
            api,
            license_number="EL-2026-0001",
            valid_from="2026-08-01T00:00:00Z",
            valid_to="2026-09-30T00:00:00Z",
            licensed_value_usd=100000.00,
        )

        touching = f.license_payload(
            license_number="EL-2026-0002",
            valid_from="2026-09-30T00:00:00Z",
            valid_to="2026-11-30T00:00:00Z",
            licensed_value_usd=80000.00,
        )
        validate_error(
            api.create_license(ctx["screening_id"], touching, COMPLIANCE_CARL),
            ApiErrorId.ERR_LICENSE_WINDOW_OVERLAP.value,
            409,
        )

        rows, meta = validate_paginated(
            api.list_licenses(
                COMPLIANCE_CARL,
                {
                    "export_control_screening_id": ctx["screening_id"],
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["license_number"] == "EL-2026-0001"

        clear = validate_success(
            api.create_license(
                ctx["screening_id"],
                dict(touching, valid_from="2026-10-01T00:00:00Z"),
                COMPLIANCE_CARL,
            ),
            201,
        )
        assert clear["status"] == "ISSUED"
        assert clear["consumed_value_usd"] == approx_money(0.00)
        assert clear["remaining_value_usd"] == approx_money(80000.00)

    def test_clearance_becomes_possible_at_the_exact_instant_of_valid_from(self, api):
        """PRD §3.3: "the logical clock is at or after `valid_from` and at or before
        `valid_to`, both bounds inclusive; and the license's `remaining_value_usd` is
        at least the order's `ordered_goods_value_usd`, equality being accepted."

        Design: Corner/validations/corner_license_validity_window_lower_bound_is_inclusive_under_clock_control
        """
        ctx = _pending_license_screening(
            api,
            license_number="EL-2026-0005",
            valid_from="2026-09-01T00:00:00Z",
            valid_to="2026-12-31T00:00:00Z",
            licensed_value_usd=100000.00,
        )

        validate_error(
            api.clear_with_license(
                ctx["screening_id"],
                {"export_license_id": ctx["license_id"]},
                COMPLIANCE_CARL,
            ),
            ApiErrorId.ERR_LICENSE_NOT_VALID_AT_DATE.value,
            409,
        )
        too_early = fx.data(api.get_screening(ctx["screening_id"], COMPLIANCE_CARL))
        assert too_early["status"] == "PENDING_LICENSE"
        assert too_early["export_license_id"] is None
        assert too_early["cleared_at"] is None

        fx.set_clock(api, "2026-09-01T00:00:00Z")

        cleared = validate_success(
            api.clear_with_license(
                ctx["screening_id"],
                {"export_license_id": ctx["license_id"]},
                COMPLIANCE_CARL,
            ),
            200,
        )
        assert cleared["status"] == "CLEARED"
        assert cleared["export_license_id"] == ctx["license_id"]
        assert cleared["cleared_at"] == "2026-09-01T00:00:00Z"

        assert fx.data(api.get_license(ctx["license_id"], COMPLIANCE_CARL))[
            "status"
        ] == "ACTIVE"
        assert_order_dimensions(
            fx.read_order(api, ctx["order_id"]), fulfillment="COMPLIANCE_CLEARED"
        )


# ---------------------------------------------------------------------------
# The four named conflicts, each pinned to its winning priority
# ---------------------------------------------------------------------------


class TestConflictAComplianceGateBeatsCapacity:
    def test_an_uncleared_order_never_reaches_the_capacity_arithmetic(self, api):
        """PRD §2.11: "**Conflict A:** a booking request against an order that is
        *not* compliance cleared *and* a sailing with no headroom left reports this
        priority-12 error, and the capacity check at priority 31 is never reached."

        Design: Corner/validations/corner_conflict_a_compliance_gate_outranks_sailing_capacity
        """
        ctx = fx.order_with_lines(api)
        sailing = fx.create_sailing(
            api,
            capacity_weight_kg=1000.000,
            cutoff_at="2026-09-10T00:00:00Z",
            etd="2026-09-12T00:00:00Z",
            eta="2026-09-30T00:00:00Z",
        )

        body = validate_error(
            api.create_booking(
                f.booking_payload(
                    ctx["order_id"],
                    sailing["id"],
                    sailing["version"],
                    booked_weight_kg=5000.000,
                ),
                OPS_ALICE,
            ),
            ApiErrorId.ERR_ORDER_NOT_COMPLIANCE_CLEARED.value,
            409,
        )
        assert body["error_id"] != ApiErrorId.ERR_SAILING_CAPACITY_EXCEEDED.value

        after = fx.read_sailing(api, sailing["id"])
        assert after["booked_weight_kg"] == 0.000
        assert after["status"] == "OPEN"
        assert after["version"] == sailing["version"]

        order = fx.read_order(api, ctx["order_id"])
        assert_order_dimensions(order, fulfillment="DRAFT")
        assert order["provisional_seller_cost_usd"] == approx_money(0.00)

        _, meta = validate_paginated(
            api.list_bookings(
                OPS_ALICE,
                {"export_order_id": ctx["order_id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 0


class TestConflictBStaleVersionBeatsRestrictedParty:
    def test_the_client_is_told_to_re_read_before_it_is_told_it_is_blocked(self, api):
        """PRD §2.11: "**Conflict B:** because state and concurrency checks precede
        compliance checks, a review request that is both stale *and* aimed at a
        restricted-party buyer reports `ERR_STALE_LC_VERSION` (412)."

        Design: Corner/validations/corner_conflict_b_stale_credit_version_outranks_restricted_party_block
        """
        ctx = fx.order_with_lines(api)
        ctx = fx.captured_credit(api, ctx, lc_number="LC-2026-0030")
        stale_version = ctx["credit"]["version"]

        # PRD §3.4: an amendment is applied from AMENDMENT_REQUESTED or ACCEPTED,
        # so the credit is walked to ACCEPTED before it is amended in place.
        ctx = fx.opened_terms_review(api, ctx)
        fx.data(
            api.submit_terms_review(
                ctx["review_id"], {"recommendation": "ACCEPT"}, REVIEWER_BOB
            )
        )
        amended = fx.data(
            api.amend_credit(
                ctx["lc_id"],
                {
                    "expected_letter_of_credit_version": fx.credit_version(
                        api, ctx["lc_id"]
                    ),
                    "tolerance_pct": 5.00,
                },
                OPS_ALICE,
            )
        )
        fresh_version = amended["version"]
        assert fresh_version != stale_version

        fx.data(
            api.patch_restricted_party_flag(
                ctx["buyer_id"],
                {
                    "restricted_party_flag": True,
                    "restricted_party_reason": "MANUAL_WATCHLIST_MATCH",
                },
                COMPLIANCE_CARL,
            )
        )

        body = validate_error(
            api.open_terms_review(
                ctx["lc_id"],
                {"expected_letter_of_credit_version": stale_version},
                REVIEWER_BOB,
            ),
            ApiErrorId.ERR_STALE_LC_VERSION.value,
            412,
        )
        assert body["error_id"] != ApiErrorId.ERR_RESTRICTED_PARTY_BLOCKED.value

        credit = fx.read_credit(api, ctx["lc_id"])
        assert credit["status"] == "RECEIVED"
        assert credit["amendment_round"] == 1
        assert credit["tolerance_pct"] == approx_money(5.00)
        assert credit["version"] == fresh_version

        # PRD §3.4: the amendment moved every SUBMITTED review to SUPERSEDED, and the
        # refused stale request wrote no new review row.
        review_rows, meta = validate_paginated(
            api.list_terms_reviews(
                REVIEWER_BOB,
                {"letter_of_credit_id": ctx["lc_id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 1
        assert review_rows[0]["status"] == "SUPERSEDED"

        validate_error(
            api.open_terms_review(
                ctx["lc_id"],
                {"expected_letter_of_credit_version": fresh_version},
                REVIEWER_BOB,
            ),
            ApiErrorId.ERR_RESTRICTED_PARTY_BLOCKED.value,
            409,
        )


class TestOneLiveBookingPerOrderShadowsTheWindowRule:
    def test_a_second_booking_is_refused_on_state_and_admitted_after_a_cancel(
        self, api
    ):
        """PRD §2.11: "The target row is in a state from which the requested
        transition is declared, on every state-changing endpoint — otherwise the
        owning entity's state error: `ERR_ORDER_STATE_INVALID`,
        `ERR_LC_STATE_INVALID`, `ERR_REVIEW_ALREADY_SUBMITTED`,
        `ERR_DOCUMENT_STATE_INVALID`, `ERR_SCREENING_STATE_INVALID`,
        `ERR_BOOKING_STATE_INVALID`, `ERR_PRESENTATION_STATE_INVALID` or
        `ERR_DISPUTE_STATE_INVALID`, all 409."

        Design: Corner/validations/corner_second_booking_on_a_booked_order_shadows_the_window_overlap_rule
        """
        ctx = fx.cleared_order(api)
        ctx = fx.booked_order(
            api,
            base=ctx,
            sailing_overrides={
                "carrier_scac": "HLCU",
                "vessel_name": "MV Pacific Trader",
                "cutoff_at": "2026-09-10T00:00:00Z",
                "etd": "2026-09-12T00:00:00Z",
                "eta": "2026-09-30T00:00:00Z",
                "capacity_weight_kg": 100000.000,
            },
        )
        sailing_b = fx.create_sailing(
            api,
            carrier_scac="MAEU",
            vessel_name="MV Gulf Runner",
            cutoff_at="2026-09-11T00:00:00Z",
            etd="2026-09-13T00:00:00Z",
            eta="2026-10-02T00:00:00Z",
            capacity_weight_kg=100000.000,
            tariff_rate_per_1000kg_usd=305.00,
        )

        body = validate_error(
            api.create_booking(
                f.booking_payload(
                    ctx["order_id"], sailing_b["id"], sailing_b["version"]
                ),
                OPS_ALICE,
            ),
            ApiErrorId.ERR_ORDER_STATE_INVALID.value,
            409,
        )
        assert body["error_id"] != ApiErrorId.ERR_BOOKING_WINDOW_OVERLAP.value

        _, meta = validate_paginated(
            api.list_bookings(
                OPS_ALICE,
                {"export_order_id": ctx["order_id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 1
        assert fx.read_sailing(api, sailing_b["id"])["booked_weight_kg"] == 0.000

        first = fx.data(api.get_booking(ctx["booking_id"], OPS_ALICE))
        assert first["effective_window_start"] == "2026-09-10T00:00:00Z"
        assert first["effective_window_end"] == "2026-09-13T00:00:00Z"

        fx.data(
            api.cancel_booking(
                ctx["booking_id"],
                {"cancel_reason": "carrier rolled the container to a later sailing"},
                OPS_ALICE,
            )
        )
        assert_order_dimensions(
            fx.read_order(api, ctx["order_id"]), fulfillment="COMPLIANCE_CLEARED"
        )

        second = validate_success(
            api.create_booking(
                f.booking_payload(
                    ctx["order_id"],
                    sailing_b["id"],
                    fx.sailing_version(api, sailing_b["id"]),
                ),
                OPS_ALICE,
            ),
            201,
        )
        assert second["status"] == "BOOKED"


THREE_REQUIRED_TYPES = ["COMMERCIAL_INVOICE", "PACKING_LIST", "BILL_OF_LADING"]


class TestConflictCSegregationOfDutiesBeatsDocumentIntegrity:
    def test_the_preparers_own_examination_is_barred_before_the_stale_revision(
        self, api
    ):
        """PRD §2.11: "**Conflict C:** an examination by the document's own preparer
        against a superseded revision reports this error, not the priority-27
        revision error."

        Design: Corner/validations/corner_conflict_c_segregation_of_duties_outranks_superseded_revision
        """
        ctx = fx.full_tender(
            api,
            required_document_types=THREE_REQUIRED_TYPES,
            credit_overrides={"lc_number": "LC-2026-0040"},
        )
        ctx = fx.lodged_presentation(api, ctx)

        revision_two = fx.data(
            api.regenerate_document(
                ctx["invoice_id"],
                {"reason": "Buyer requested a corrected description of goods"},
                OPS_ALICE,
            )
        )

        body = validate_error(
            api.examine_presentation(
                ctx["presentation_id"],
                {"findings": []},
                make_reviewer_headers(USER_IDS["ops_alice"]),
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
            409,
        )
        assert body["error_id"] != ApiErrorId.ERR_DOCUMENT_REVISION_SUPERSEDED.value
        assert body["error_id"] != ApiErrorId.ERR_REQUIRED_DOCUMENT_MISSING.value

        presentation = fx.data(
            api.get_presentation(ctx["presentation_id"], REVIEWER_BOB)
        )
        assert presentation["status"] == "PRESENTED"
        assert presentation["examined_by_user_id"] is None

        links = {
            link["doc_type"]: link
            for link in fx.presentation_links(api, ctx["presentation_id"])
        }
        assert links["COMMERCIAL_INVOICE"]["link_status"] == "REPLACED"
        assert links["PACKING_LIST"]["link_status"] == "ACTIVE"
        assert links["BILL_OF_LADING"]["link_status"] == "ACTIVE"

        assert fx.data(api.get_document(ctx["invoice_id"], OPS_ALICE))[
            "status"
        ] == "SUPERSEDED"
        assert revision_two["revision"] == 2
        assert revision_two["status"] == "DRAFT"
        assert revision_two["supersedes_document_id"] == ctx["invoice_id"]


class TestConflictDExpiryBeatsTheDrawingBound:
    def test_an_examination_on_the_expiry_instant_reports_expiry_not_the_amount(
        self, api
    ):
        """PRD §2.11: "**Conflict D:** an examination on an expired credit whose
        invoice also over-draws reports `ERR_LC_EXPIRED`, not the priority-33 amount
        error."

        Design: Corner/validations/corner_conflict_d_expired_credit_outranks_over_drawn_presentation
        """
        ctx = fx.full_tender(
            api,
            required_document_types=THREE_REQUIRED_TYPES,
            credit_overrides={
                "lc_number": "LC-2026-0041",
                "amount_usd": 20000.00,
                "tolerance_pct": 0.00,
                "expiry_date": "2026-08-20T00:00:00Z",
                "latest_shipment_date": "2026-08-15T00:00:00Z",
            },
        )
        ctx = fx.lodged_presentation(api, ctx)
        fx.set_clock(api, "2026-08-20T00:00:00Z")

        body = validate_error(
            api.examine_presentation(
                ctx["presentation_id"], {"findings": []}, REVIEWER_BOB
            ),
            ApiErrorId.ERR_LC_EXPIRED.value,
            409,
        )
        assert body["error_id"] != ApiErrorId.ERR_LC_AMOUNT_EXCEEDED.value

        credit = fx.read_credit(api, ctx["lc_id"])
        assert credit["status"] == "ACCEPTED"
        assert credit["max_drawable_usd"] == approx_money(20000.00)
        assert credit["min_drawable_usd"] == approx_money(20000.00)

        presentation = fx.data(
            api.get_presentation(ctx["presentation_id"], REVIEWER_BOB)
        )
        assert presentation["status"] == "PRESENTED"
        assert presentation["presented_amount_usd"] == approx_money(25000.00)
        assert presentation["days_after_on_board"] == 0
        assert presentation["negotiable_amount_usd"] == approx_money(0.00)

        assert_order_dimensions(
            fx.read_order(api, ctx["order_id"]), settlement="DOCS_PRESENTED"
        )
