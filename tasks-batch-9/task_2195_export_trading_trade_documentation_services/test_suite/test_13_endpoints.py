"""Endpoint surfaces: computed reads, buyer-owned writes, filters and guard order."""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    ADMIN_PAT,
    COMPLIANCE_CARL,
    FINANCE_FRANK,
    NON_EXISTENT_UUID,
    OPS_ALICE,
    REVIEWER_BOB,
    ApiErrorId,
    approx_money,
    approx_weight,
    assert_order_dimensions,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)

Json = Dict[str, Any]


class TestCostAllocationReadIsAProjection:
    def test_two_readers_get_the_same_buckets_and_the_order_is_never_written(
        self, api
    ):
        """PRD §3.6: "An `ExportOpsCoordinator`, `FinanceCollectionsOfficer` or
        `PlatformAdmin` may ask for both variants of an order's allocation to be
        recomputed and returned without persisting either."

        Design: Corner/endpoints/corner_cost_allocation_read_recomputes_both_variants_without_persisting
        """
        ctx = fx.cleared_order(
            api,
            buyer_overrides={
                "legal_name": "Rheinwerk Import GmbH",
                "country_code": "DE",
                "credit_rating": "A",
            },
            order_overrides={
                "incoterm_named_place": "FOB Oakland",
                "destination_country_code": "DE",
            },
        )
        ctx = fx.booked_order(
            api,
            base=ctx,
            sailing_overrides={
                "carrier_scac": "MAEU",
                "vessel_name": "MV Corner Trader",
                "port_of_discharge": "DEHAM",
                "capacity_weight_kg": 50000.000,
            },
        )
        version_before = fx.order_version(api, ctx["order_id"])

        first = validate_success(api.get_cost_allocation(ctx["order_id"], OPS_ALICE))
        assert first["provisional_seller_cost_usd"] == approx_money(584.00)
        assert first["provisional_buyer_cost_usd"] == approx_money(2816.25)
        # PRD §4 says only that the read "recomputes and returns both incoterm
        # cost-allocation variants"; it fixes no value for the final variant before a
        # bill of lading exists, so only its presence is asserted here.
        assert "final_seller_cost_usd" in first
        assert "final_buyer_cost_usd" in first
        assert "cost_allocation_variance_usd" in first

        second = validate_success(
            api.get_cost_allocation(ctx["order_id"], FINANCE_FRANK)
        )
        assert (
            second["provisional_seller_cost_usd"]
            == first["provisional_seller_cost_usd"]
        )
        assert (
            second["provisional_buyer_cost_usd"] == first["provisional_buyer_cost_usd"]
        )

        assert fx.order_version(api, ctx["order_id"]) == version_before


class TestBuyerOwnedWaiverStampsTheAuthenticatedIdentity:
    def test_the_waiver_takes_the_buyer_id_from_the_header_not_the_body(self, api):
        """PRD §3.7: "The waiver sets the finding's `cure_status` to `WAIVED` and its
        `waived_by_buyer_id` to the caller's `X-User-ID`, then recomputes the owning
        presentation's `open_finding_count`."

        Design: Corner/endpoints/corner_buyer_waives_a_minor_terms_finding_and_stamps_its_own_identity
        """
        ctx = fx.order_with_lines(
            api,
            buyer_overrides={
                "legal_name": "Kobe Marine Trading KK",
                "country_code": "JP",
                "credit_rating": "AA",
            },
        )
        ctx = fx.captured_credit(api, ctx, lc_number="LC-CORNER-7001")
        ctx = fx.opened_terms_review(api, ctx)
        finding = fx.data(
            api.raise_terms_finding(
                ctx["review_id"],
                f.terms_finding_payload(
                    code="PARTIAL_SHIPMENT_BARRED",
                    severity="MINOR",
                    clause_ref="DOCUMENTS",
                    detail="partial shipment barred although the order ships in two parcels",
                ),
                REVIEWER_BOB,
            )
        )

        waived = validate_success(
            api.waive_finding(
                finding["id"],
                {"buyer_reference": "BR-2026-0042"},
                ctx["buyer_headers"],
            ),
            200,
        )
        assert waived["cure_status"] == "WAIVED"
        assert waived["waived_by_buyer_id"] == ctx["buyer_id"]
        assert waived["buyer_reference"] == "BR-2026-0042"
        assert waived["source"] == "TERMS"
        assert waived["severity"] == "MINOR"
        assert waived["raised_in_round"] == 0

        rows, meta = validate_paginated(
            api.list_findings(
                REVIEWER_BOB,
                {
                    "lc_terms_review_id": ctx["review_id"],
                    "cure_status": "WAIVED",
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == finding["id"]


# ---------------------------------------------------------------------------
# The admin-only exit from a deadlocked negotiation
# ---------------------------------------------------------------------------

ESCALATION_WALK = (
    ("offer", 3000.00),
    ("counter", 4000.00),
    ("offer", 3500.00),
    ("counter", 4500.00),
    ("offer", 4000.00),
    ("counter", 5000.00),
    ("counter", 6000.00),
)


def _escalated_quality_dispute(api) -> Json:
    """Walk the negotiation to its round ceiling so the case escalates."""
    ctx = fx.order_with_lines(
        api,
        buyer_overrides={
            "legal_name": "Valparaiso Agro SpA",
            "country_code": "CL",
        },
    )
    dispute = fx.data(
        api.open_dispute(
            f.dispute_payload(ctx["order_id"], claimed_amount_usd=8000.00),
            ctx["buyer_headers"],
        )
    )
    ctx["dispute_id"] = dispute["id"]
    for move, amount in ESCALATION_WALK:
        if move == "offer":
            ctx["dispute"] = fx.data(
                api.make_offer(
                    ctx["dispute_id"], {"offer_amount_usd": amount}, FINANCE_FRANK
                )
            )
        else:
            ctx["dispute"] = fx.data(
                api.counter_offer(
                    ctx["dispute_id"],
                    {"counter_amount_usd": amount},
                    ctx["buyer_headers"],
                )
            )
    return ctx


class TestAdminCloseZeroesEveryBucket:
    def test_closing_an_escalated_case_settles_nothing_and_locks_the_row(self, api):
        """PRD §3.9: "A `PlatformAdmin` closes an `ESCALATED` case with a `reason`.
        All three buckets are set to 0.00 and the case moves to
        `CLOSED_NO_SETTLEMENT`, which is terminal."

        Design: Corner/endpoints/corner_admin_closes_escalated_dispute_and_zeroes_the_three_waterfall_buckets
        """
        ctx = _escalated_quality_dispute(api)
        assert ctx["dispute"]["status"] == "ESCALATED"
        assert ctx["dispute"]["negotiation_round"] == 3
        assert ctx["dispute"]["current_offer_usd"] == approx_money(5000.00)

        closed = validate_success(
            api.close_dispute(
                ctx["dispute_id"],
                {
                    "reason": "no commercial agreement reachable after three negotiation rounds"
                },
                ADMIN_PAT,
            ),
            200,
        )
        assert closed["status"] == "CLOSED_NO_SETTLEMENT"
        assert closed["receivable_offset_usd"] == approx_money(0.00)
        assert closed["insurance_indemnity_usd"] == approx_money(0.00)
        assert closed["seller_credit_note_usd"] == approx_money(0.00)
        assert closed["settlement_amount_usd"] is None

        order = fx.read_order(api, ctx["order_id"])
        assert_order_dimensions(order, settlement="UNSECURED")
        assert order["outstanding_receivable_usd"] == approx_money(0.00)

        validate_error(
            api.close_dispute(
                ctx["dispute_id"], {"reason": "duplicate close"}, ADMIN_PAT
            ),
            ApiErrorId.ERR_DISPUTE_STATE_INVALID.value,
            409,
        )
        late = validate_error(
            api.counter_offer(
                ctx["dispute_id"],
                {"counter_amount_usd": 7000.00},
                ctx["buyer_headers"],
            ),
            ApiErrorId.ERR_DISPUTE_STATE_INVALID.value,
            409,
        )
        assert late["error_id"] != ApiErrorId.ERR_NEGOTIATION_ROUNDS_EXHAUSTED.value


# ---------------------------------------------------------------------------
# One populated aggregate, seven filtered collection reads
# ---------------------------------------------------------------------------

TWO_DISTINCT_HS_LINES = [
    {
        "line_no": 1,
        "goods_description": "spindle assemblies",
        "hs_code": "847989",
        "quantity": 60.000,
        "unit_price_usd": 250.0000,
        "net_weight_kg": 600.000,
        "gross_weight_kg": 700.000,
        "package_count": 6,
    },
    {
        "line_no": 2,
        "goods_description": "irrigation valves",
        "hs_code": "848180",
        "quantity": 40.000,
        "unit_price_usd": 250.0000,
        "net_weight_kg": 400.000,
        "gross_weight_kg": 500.000,
        "package_count": 4,
    },
]

BALTIC_SAILING = {
    "carrier_scac": "HLCU",
    "vessel_name": "MV Baltic Corner",
    "voyage_no": "CD-2101",
    "port_of_loading": "USNYC",
    "port_of_discharge": "PLGDN",
    "destination_zone": "ZONE_2",
    "cutoff_at": "2026-08-20T00:00:00Z",
    "etd": "2026-08-23T00:00:00Z",
    "eta": "2026-09-08T00:00:00Z",
    "capacity_weight_kg": 40000.000,
    "tariff_rate_per_1000kg_usd": 280.00,
}


def _populated_aggregate(api) -> Json:
    """One buyer carrying every collection this module then filters."""
    ctx = fx.order_with_lines(
        api,
        buyer_overrides={
            "legal_name": "Gdansk Steelworks Sp z o o",
            "country_code": "PL",
            "credit_rating": "A",
        },
        order_overrides={
            "incoterm": "CFR",
            "incoterm_named_place": "CFR Gdansk",
            "destination_country_code": "PL",
        },
        lines=TWO_DISTINCT_HS_LINES,
    )
    ctx = fx.captured_credit(
        api,
        ctx,
        lc_number="LC-CORNER-7101",
        issuing_bank_swift="BPKOPLPW",
        tolerance_pct=5.00,
        expiry_date="2026-12-31T00:00:00Z",
        latest_shipment_date="2026-09-20T00:00:00Z",
        required_document_types=["COMMERCIAL_INVOICE", "PACKING_LIST"],
    )
    ctx = fx.opened_terms_review(api, ctx)
    ctx["policy"] = fx.create_policy(
        api,
        ctx["buyer_id"],
        policy_number="POL-CORNER-7101",
        credit_limit_usd=40000.00,
        insured_pct=85.00,
        deductible_usd=1000.00,
    )
    fx.data(api.submit_for_compliance(ctx["order_id"], OPS_ALICE))
    ctx["screening_id"] = fx.screening_for_order(api, ctx["order_id"])["id"]
    ctx["screening"] = fx.data(
        api.record_screening_decision(
            ctx["screening_id"],
            f.screening_decision_payload(eccn="3A991"),
            COMPLIANCE_CARL,
        )
    )
    ctx["sailing"] = fx.create_sailing(api, **BALTIC_SAILING)
    ctx["booking"] = fx.data(
        api.create_booking(
            f.booking_payload(
                ctx["order_id"],
                ctx["sailing"]["id"],
                ctx["sailing"]["version"],
                container_type="DRY_20",
            ),
            OPS_ALICE,
        )
    )
    return ctx


class TestEveryCollectionFiltersOnItsOwnDimensions:
    def test_total_count_shrinks_with_the_filter_on_all_seven_collections(self, api):
        """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and
        `has_more` inside the `meta` object of the envelope, where `total_count` is the
        number of rows matching the filters before pagination is applied and `has_more`
        indicates whether rows remain beyond the current window."

        Design: Corner/endpoints/corner_every_collection_endpoint_filters_by_its_own_declared_dimensions
        """
        ctx = _populated_aggregate(api)
        second_line_id = ctx["line_ids"][1]

        nested, meta = validate_paginated(
            api.list_order_shipment_lines(
                ctx["order_id"], REVIEWER_BOB, {"limit": 1, "offset": 1}
            )
        )
        assert [row["id"] for row in nested] == [second_line_id]
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert meta["limit"] == 1
        assert meta["offset"] == 1

        flat, meta = validate_paginated(
            api.list_shipment_lines(
                OPS_ALICE,
                {
                    "export_order_id": ctx["order_id"],
                    "hs_code": "848180",
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert [row["id"] for row in flat] == [second_line_id]
        assert meta["total_count"] == 1
        assert meta["has_more"] is False

        credits, meta = validate_paginated(
            api.list_credits(
                REVIEWER_BOB,
                {
                    "export_order_id": ctx["order_id"],
                    "status": "UNDER_REVIEW",
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert [row["id"] for row in credits] == [ctx["lc_id"]]
        assert meta["total_count"] == 1
        _, meta = validate_paginated(
            api.list_credits(
                REVIEWER_BOB,
                {
                    "export_order_id": ctx["order_id"],
                    "status": "RECEIVED",
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert meta["total_count"] == 0

        reviews, meta = validate_paginated(
            api.list_terms_reviews(
                REVIEWER_BOB,
                {
                    "letter_of_credit_id": ctx["lc_id"],
                    "status": "DRAFTING",
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert [row["id"] for row in reviews] == [ctx["review_id"]]
        assert reviews[0]["status"] == "DRAFTING"
        assert meta["total_count"] == 1

        bookings, meta = validate_paginated(
            api.list_bookings(
                FINANCE_FRANK,
                {
                    "vessel_sailing_id": ctx["sailing"]["id"],
                    "status": "BOOKED",
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert [row["id"] for row in bookings] == [ctx["booking"]["id"]]
        assert bookings[0]["chargeable_weight_kg"] == approx_weight(8000.000)
        assert meta["total_count"] == 1

        policies, meta = validate_paginated(
            api.list_policies(
                FINANCE_FRANK,
                {
                    "buyer_id": ctx["buyer_id"],
                    "status": "ACTIVE",
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert [row["id"] for row in policies] == [ctx["policy"]["id"]]
        assert policies[0]["utilized_usd"] == approx_money(0.00)
        assert policies[0]["available_limit_usd"] == approx_money(40000.00)
        assert meta["total_count"] == 1

        screenings, meta = validate_paginated(
            api.list_screenings(
                OPS_ALICE,
                {
                    "export_order_id": ctx["order_id"],
                    "status": "CLEARED",
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert [row["id"] for row in screenings] == [ctx["screening_id"]]
        assert screenings[0]["license_determination"] == "NLR"
        assert screenings[0].get("export_license_id") is None
        assert meta["total_count"] == 1
        assert meta["limit"] == 10
        assert meta["offset"] == 0


# ---------------------------------------------------------------------------
# Item reads over the LICENSE_REQUIRED branch
# ---------------------------------------------------------------------------

DISCOUNTED_LINE = [
    {
        "line_no": 1,
        "goods_description": "encoder modules",
        "hs_code": "903180",
        "quantity": 100.000,
        "unit_price_usd": 250.0000,
        "line_discount_pct": 10.00,
        "net_weight_kg": 1000.000,
        "gross_weight_kg": 1200.000,
        "package_count": 12,
    }
]

COROMANDEL_SAILING = {
    "carrier_scac": "ONEY",
    "vessel_name": "MV Coromandel Corner",
    "voyage_no": "CD-2201",
    "port_of_loading": "USLAX",
    "port_of_discharge": "INMAA",
    "destination_zone": "ZONE_3",
    "cutoff_at": "2026-08-18T00:00:00Z",
    "etd": "2026-08-21T00:00:00Z",
    "eta": "2026-09-19T00:00:00Z",
    "capacity_weight_kg": 40000.000,
    "tariff_rate_per_1000kg_usd": 310.00,
}


class TestItemReadsEchoTheLedgerWritesOfTheirCreators:
    def test_the_licence_is_consumed_at_booking_and_not_at_clearance(self, api):
        """PRD §3.3: "The charge fires when an order with determination
        `LICENSE_REQUIRED` enters `BOOKED`."

        Design: Corner/endpoints/corner_item_reads_echo_the_ledger_fields_the_creating_calls_wrote
        """
        ctx = fx.licensed_cleared_order(
            api,
            eccn="3A991",
            license_overrides={
                "license_number": "BIS-CORNER-7201",
                "licensed_value_usd": 30000.00,
                "valid_from": "2026-07-01T00:00:00Z",
                "valid_to": "2026-12-31T00:00:00Z",
            },
            buyer_overrides={
                "legal_name": "Chennai Precision Pvt Ltd",
                "country_code": "IN",
            },
            order_overrides={
                "incoterm_named_place": "FOB Oakland",
                "destination_country_code": "IN",
                "destination_zone": "ZONE_3",
            },
            lines=DISCOUNTED_LINE,
        )

        before = validate_success(
            api.get_license(ctx["license_id"], COMPLIANCE_CARL)
        )
        assert before["consumed_value_usd"] == approx_money(0.00)
        assert before["remaining_value_usd"] == approx_money(30000.00)
        assert before["status"] == "ACTIVE"

        sailing = fx.create_sailing(api, **COROMANDEL_SAILING)
        booking = validate_success(
            api.create_booking(
                f.booking_payload(
                    ctx["order_id"],
                    sailing["id"],
                    sailing["version"],
                    container_type="DRY_20",
                ),
                OPS_ALICE,
            ),
            201,
        )

        line = validate_success(
            api.get_shipment_line(ctx["line_ids"][0], REVIEWER_BOB)
        )
        assert line["line_extended_usd"] == approx_money(25000.00)
        assert line["line_net_usd"] == approx_money(22500.00)
        # PRD §3.2: shipped_quantity "is system-maintained, starts at 0.000, and is
        # written only by bill-of-lading issuance", which has not happened yet.
        assert line["shipped_quantity"] == approx_weight(0.000)

        screening = validate_success(
            api.get_screening(ctx["screening_id"], COMPLIANCE_CARL)
        )
        assert screening["status"] == "CLEARED"
        assert screening["license_determination"] == "LICENSE_REQUIRED"
        assert screening["export_license_id"] == ctx["license_id"]
        assert screening["cleared_at"] == "2026-08-01T00:00:00Z"

        after = validate_success(api.get_license(ctx["license_id"], COMPLIANCE_CARL))
        assert after["consumed_value_usd"] == approx_money(25000.00)
        assert after["remaining_value_usd"] == approx_money(5000.00)
        assert after["status"] == "ACTIVE"

        read_sailing = validate_success(api.get_sailing(sailing["id"], FINANCE_FRANK))
        assert read_sailing["booked_weight_kg"] == approx_weight(1200.000)
        assert read_sailing["status"] == "OPEN"

        read_booking = validate_success(
            api.get_booking(booking["id"], COMPLIANCE_CARL)
        )
        assert read_booking["chargeable_weight_kg"] == approx_weight(8000.000)
        assert read_booking["effective_window_start"] == "2026-08-18T00:00:00Z"
        assert read_booking["effective_window_end"] == "2026-08-22T00:00:00Z"

        order = fx.read_order(api, ctx["order_id"])
        assert order["licensed_value_allocated_usd"] == approx_money(25000.00)
        assert_order_dimensions(order, fulfillment="BOOKED")


# ---------------------------------------------------------------------------
# The cure loop and its round ceiling
# ---------------------------------------------------------------------------

THREE_REQUIRED_TYPES = ["COMMERCIAL_INVOICE", "PACKING_LIST", "BILL_OF_LADING"]

GOODS_FINDING_WALK = (
    ("DESCRIPTION_MISMATCH", "goods description on the invoice does not mirror the credit"),
    ("WEIGHT_MISMATCH", "gross weight still disagrees with the packing list"),
    ("ORIGIN_MISMATCH", "origin statement still wrong"),
)


def _major_goods_finding(code: str, detail: str) -> Json:
    return {
        "code": code,
        "severity": "MAJOR",
        "clause_ref": "GOODS",
        "detail": detail,
    }


def _next_invoice_revision(api, document_id: str, reason: str) -> str:
    """Mint and issue the next revision of a commercial invoice."""
    revision = validate_success(
        api.regenerate_document(document_id, {"reason": reason}, OPS_ALICE), 201
    )
    assert revision["status"] == "DRAFT"
    validate_success(api.issue_document(revision["id"], OPS_ALICE), 200)
    return revision["id"]


class TestCureCycleRelinksRevisionsUntilTheCeiling:
    def test_two_cures_land_and_the_third_is_refused_at_round_three(self, api):
        """PRD §3.7: "The cure moves the presentation from `DISCREPANT` to `CURING`
        and then from `CURING` back to `PRESENTED` within the same request."

        Design: Corner/endpoints/corner_cure_cycle_relinks_revisions_until_the_round_ceiling_stops_it
        """
        ctx = fx.full_tender(
            api,
            required_document_types=THREE_REQUIRED_TYPES,
            buyer_overrides={
                "legal_name": "Antwerp Cure Trading NV",
                "country_code": "BE",
                "credit_rating": "A",
            },
            order_overrides={
                "incoterm_named_place": "FOB Oakland",
                "destination_country_code": "BE",
            },
            sailing_overrides={
                "carrier_scac": "MSCU",
                "vessel_name": "MV Scheldt Corner",
                "port_of_discharge": "BEANR",
                "capacity_weight_kg": 40000.000,
                "tariff_rate_per_1000kg_usd": 290.00,
            },
            credit_overrides={
                "lc_number": "LC-CORNER-7301",
                "expiry_date": "2026-12-31T00:00:00Z",
            },
        )
        first_invoice_id = ctx["invoice_id"]
        ctx = fx.lodged_presentation(api, ctx)
        ctx = fx.examined_presentation(
            api, ctx, [_major_goods_finding(*GOODS_FINDING_WALK[0])]
        )
        assert ctx["presentation"]["status"] == "DISCREPANT"
        assert ctx["presentation"]["open_finding_count"] == 1
        opened = fx.findings_for_presentation(api, ctx["presentation_id"])
        assert len(opened) == 1
        assert opened[0]["raised_in_round"] == 1

        validate_error(
            api.cure_presentation(
                ctx["presentation_id"], {"replacement_document_ids": []}, OPS_ALICE
            ),
            ApiErrorId.ERR_NO_REPLACEMENT_DOCUMENTS.value,
            422,
        )

        second_invoice_id = _next_invoice_revision(
            api, first_invoice_id, "restate goods description to mirror the credit"
        )
        cured = validate_success(
            api.cure_presentation(
                ctx["presentation_id"],
                {"replacement_document_ids": [second_invoice_id]},
                OPS_ALICE,
            ),
            200,
        )
        assert cured["status"] == "PRESENTED"
        assert cured["presentation_round"] == 2
        assert cured["open_finding_count"] == 0
        assert cured["presented_amount_usd"] == approx_money(25000.00)
        assert fx.read_credit(api, ctx["lc_id"])[
            "max_drawable_usd"
        ] == approx_money(27500.00)

        links = fx.presentation_links(api, ctx["presentation_id"])
        by_document = {row["trade_document_id"]: row for row in links}
        assert by_document[first_invoice_id]["link_status"] == "REPLACED"
        fresh = by_document[second_invoice_id]
        assert fresh["link_status"] == "ACTIVE"
        assert fresh["pinned_document_revision"] == 2
        assert fresh["linked_in_round"] == 2
        for carried in (ctx["packing_list_id"], ctx["bill_of_lading_id"]):
            assert by_document[carried]["link_status"] == "ACTIVE"
            assert by_document[carried]["linked_in_round"] == 1

        assert [row["cure_status"] for row in
                fx.findings_for_presentation(api, ctx["presentation_id"])] == ["CURED"]
        assert_order_dimensions(
            fx.read_order(api, ctx["order_id"]), settlement="DOCS_PRESENTED"
        )

        validate_error(
            api.cure_presentation(
                ctx["presentation_id"],
                {"replacement_document_ids": [second_invoice_id]},
                OPS_ALICE,
            ),
            ApiErrorId.ERR_PRESENTATION_STATE_INVALID.value,
            409,
        )

        ctx = fx.examined_presentation(
            api, ctx, [_major_goods_finding(*GOODS_FINDING_WALK[1])]
        )
        assert ctx["presentation"]["status"] == "DISCREPANT"
        third_invoice_id = _next_invoice_revision(
            api, second_invoice_id, "restate gross weight"
        )
        third_round = validate_success(
            api.cure_presentation(
                ctx["presentation_id"],
                {"replacement_document_ids": [third_invoice_id]},
                OPS_ALICE,
            ),
            200,
        )
        assert third_round["presentation_round"] == 3

        ctx = fx.examined_presentation(
            api, ctx, [_major_goods_finding(*GOODS_FINDING_WALK[2])]
        )
        fourth_invoice_id = _next_invoice_revision(
            api, third_invoice_id, "restate origin"
        )
        validate_error(
            api.cure_presentation(
                ctx["presentation_id"],
                {"replacement_document_ids": [fourth_invoice_id]},
                OPS_ALICE,
            ),
            ApiErrorId.ERR_CURE_ROUNDS_EXHAUSTED.value,
            409,
        )
        assert fx.data(
            api.get_presentation(ctx["presentation_id"], OPS_ALICE)
        )["presentation_round"] == 3


class TestLodgingGuardsFireInPriorityOrder:
    def test_credit_state_then_body_key_then_concurrency(self, api):
        """PRD §2.11: "All checks are evaluated in ascending priority order, and the
        **first** failure wins: once a check fails, the request is rejected with that
        check's error and no later check is evaluated."

        Design: Corner/endpoints/corner_presentation_lodging_guards_reject_in_declared_priority_order
        """
        ctx = fx.order_with_lines(
            api,
            buyer_overrides={
                "legal_name": "Busan Fastener Co Ltd",
                "country_code": "KR",
                "credit_rating": "A",
            },
            order_overrides={"destination_zone": "ZONE_3"},
        )
        ctx = fx.captured_credit(
            api,
            ctx,
            lc_number="LC-CORNER-7401",
            issuing_bank_swift="KOEXKRSE",
            expiry_date="2026-12-31T00:00:00Z",
            latest_shipment_date="2026-09-20T00:00:00Z",
            required_document_types=["COMMERCIAL_INVOICE", "PACKING_LIST"],
        )
        version_before_accept = fx.order_version(api, ctx["order_id"])

        validate_error(
            api.lodge_presentation(
                f.presentation_payload(
                    ctx["lc_id"], ctx["order_id"], [], version_before_accept
                ),
                OPS_ALICE,
            ),
            ApiErrorId.ERR_LC_NOT_ACCEPTED.value,
            409,
        )

        ctx = fx.opened_terms_review(api, ctx)
        validate_success(
            api.submit_terms_review(
                ctx["review_id"], {"recommendation": "ACCEPT"}, REVIEWER_BOB
            ),
            200,
        )
        version_after_accept = fx.order_version(api, ctx["order_id"])
        assert version_after_accept > version_before_accept

        validate_error(
            api.lodge_presentation(
                f.presentation_payload(
                    ctx["lc_id"],
                    ctx["order_id"],
                    [NON_EXISTENT_UUID],
                    version_after_accept,
                ),
                OPS_ALICE,
            ),
            ApiErrorId.ERR_DOCUMENT_NOT_FOUND.value,
            404,
        )

        validate_error(
            api.lodge_presentation(
                f.presentation_payload(
                    ctx["lc_id"], ctx["order_id"], [], version_before_accept
                ),
                OPS_ALICE,
            ),
            ApiErrorId.ERR_STALE_ORDER_VERSION.value,
            412,
        )

        _, meta = validate_paginated(
            api.list_presentations(
                REVIEWER_BOB,
                {"export_order_id": ctx["order_id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 0

        order = fx.read_order(api, ctx["order_id"])
        assert_order_dimensions(order, settlement="LC_ACCEPTED")
        assert order["version"] == version_after_accept
