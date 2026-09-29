"""Error identity: the 404 family, the uniqueness indexes and the ladder's winners."""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    COMPLIANCE_CARL,
    FINANCE_FRANK,
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

# One never-issued but well-formed identifier per single-row read below.
UNKNOWN_IDS = (
    "11111111-0000-4000-8000-000000000001",
    "11111111-0000-4000-8000-000000000002",
    "11111111-0000-4000-8000-000000000003",
    "11111111-0000-4000-8000-000000000004",
    "11111111-0000-4000-8000-000000000005",
    "11111111-0000-4000-8000-000000000006",
    "11111111-0000-4000-8000-000000000007",
    "11111111-0000-4000-8000-000000000008",
    "11111111-0000-4000-8000-000000000009",
    "11111111-0000-4000-8000-00000000000a",
)

PATH_ID_FAMILY = (
    ("get_credit", REVIEWER_BOB, ApiErrorId.ERR_LC_NOT_FOUND),
    ("get_terms_review", REVIEWER_BOB, ApiErrorId.ERR_REVIEW_NOT_FOUND),
    ("get_finding", REVIEWER_BOB, ApiErrorId.ERR_FINDING_NOT_FOUND),
    ("get_document", OPS_ALICE, ApiErrorId.ERR_DOCUMENT_NOT_FOUND),
    ("get_sailing", OPS_ALICE, ApiErrorId.ERR_SAILING_NOT_FOUND),
    ("get_booking", OPS_ALICE, ApiErrorId.ERR_BOOKING_NOT_FOUND),
    ("get_presentation", OPS_ALICE, ApiErrorId.ERR_PRESENTATION_NOT_FOUND),
    ("get_dispute", FINANCE_FRANK, ApiErrorId.ERR_DISPUTE_NOT_FOUND),
    ("get_license", COMPLIANCE_CARL, ApiErrorId.ERR_LICENSE_NOT_FOUND),
    ("get_policy", FINANCE_FRANK, ApiErrorId.ERR_POLICY_NOT_FOUND),
)


class TestEveryPathIdFamilyKeepsItsOwnNotFoundCode:
    def test_ten_unknown_identifiers_answer_with_ten_different_codes(self, api):
        """PRD §2.4: "A request naming both a screening and a license, for example,
        fails with `ERR_SCREENING_NOT_FOUND` before the license is even looked up."

        Design: Corner/errors/corner_every_path_id_family_returns_its_own_not_found_code
        """
        seen = []
        for unknown_id, (reader, headers, error) in zip(UNKNOWN_IDS, PATH_ID_FAMILY):
            body = validate_error(
                getattr(api, reader)(unknown_id, headers), error.value, 404
            )
            assert body["message"]
            assert set(body) == {"error_id", "message"}
            seen.append(body["error_id"])

        assert len(set(seen)) == len(PATH_ID_FAMILY)
        assert ApiErrorId.ERR_ORDER_NOT_FOUND.value not in seen


class TestPolicyNumberIndexIsGlobal:
    def test_a_second_buyer_may_not_reuse_a_policy_number(self, api):
        """PRD §3.8: "A `FinanceCollectionsOfficer` writes a buyer credit insurance
        policy by naming the `buyer_id`, a `policy_number` unique across all policies"

        Design: Corner/errors/corner_policy_number_uniqueness_is_global_not_per_buyer
        """
        first_buyer = fx.create_buyer(
            api, legal_name="Casablanca Textiles SARL", country_code="MA",
            credit_rating="BB",
        )
        second_buyer = fx.create_buyer(
            api, legal_name="Lima Andes Foods SA", country_code="PE",
            credit_rating="BBB",
        )
        first_policy = fx.create_policy(
            api,
            first_buyer["id"],
            policy_number="POL-CORNER-7501",
            credit_limit_usd=40000.00,
            insured_pct=80.00,
            deductible_usd=500.00,
        )

        validate_error(
            api.create_policy(
                f.policy_payload(
                    second_buyer["id"],
                    policy_number="POL-CORNER-7501",
                    credit_limit_usd=90000.00,
                    insured_pct=95.00,
                    deductible_usd=0.00,
                    effective_from="2027-07-01T00:00:00Z",
                    effective_to="2028-06-30T00:00:00Z",
                ),
                FINANCE_FRANK,
            ),
            ApiErrorId.ERR_DUPLICATE_POLICY_NUMBER.value,
            409,
        )

        _, meta = validate_paginated(
            api.list_policies(
                FINANCE_FRANK,
                {"buyer_id": second_buyer["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 0

        untouched = fx.read_policy(api, first_policy["id"])
        assert untouched["status"] == "ACTIVE"
        assert untouched["version"] == first_policy["version"]
        assert untouched["exposure_tier"] == "TIER_1"
        assert untouched["credit_limit_usd"] == approx_money(40000.00)


class TestSanctionsGateOutranksTheEmptyOrderGuard:
    def test_an_embargoed_buyer_with_no_lines_reports_the_destination_block(self, api):
        """PRD §3.1: "Separately from the flag, a `sanctions_tier` of `EMBARGOED`
        blocks compliance submission, the screening decision and freight booking with
        a distinct 409, as does an order whose `destination_country_code` falls on the
        embargoed-destination list implied by that tier."

        Design: Corner/errors/corner_embargoed_buyer_outranks_the_empty_shipment_line_guard
        """
        buyer = fx.create_buyer(
            api,
            legal_name="Embargo Zone Machinery LLC",
            country_code="IR",
            credit_rating="CCC",
            sanctions_tier="EMBARGOED",
        )
        order = fx.create_order(
            api,
            buyer["id"],
            incoterm="EXW",
            incoterm_named_place="EXW Cleveland",
            destination_country_code="IR",
            destination_zone="ZONE_3",
        )

        failure = validate_error(
            api.submit_for_compliance(order["id"], OPS_ALICE),
            ApiErrorId.ERR_PROHIBITED_DESTINATION.value,
            409,
        )
        assert failure["error_id"] != ApiErrorId.ERR_NO_SHIPMENT_LINES.value

        _, meta = validate_paginated(
            api.list_screenings(
                COMPLIANCE_CARL,
                {"export_order_id": order["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 0

        unchanged = fx.read_order(api, order["id"])
        assert_order_dimensions(unchanged, fulfillment="DRAFT", settlement="UNSECURED")
        assert unchanged["version"] == order["version"]


# ---------------------------------------------------------------------------
# One wired order, four repeat transitions
# ---------------------------------------------------------------------------

WINCH_LINE = [
    {
        "line_no": 1,
        "goods_description": "marine winches",
        "hs_code": "842542",
        "quantity": 100.000,
        "unit_price_usd": 250.0000,
        "net_weight_kg": 1000.000,
        "gross_weight_kg": 1200.000,
        "package_count": 10,
    }
]


class TestStateTableRejectsRepeatTransitions:
    def test_four_aggregates_answer_with_four_different_state_errors(self, api):
        """PRD §2.11: "The target row is in a state from which the requested
        transition is declared, on every state-changing endpoint — otherwise the
        owning entity's state error: `ERR_ORDER_STATE_INVALID`,
        `ERR_LC_STATE_INVALID`, `ERR_REVIEW_ALREADY_SUBMITTED`,
        `ERR_DOCUMENT_STATE_INVALID`, `ERR_SCREENING_STATE_INVALID`,
        `ERR_BOOKING_STATE_INVALID`, `ERR_PRESENTATION_STATE_INVALID` or
        `ERR_DISPUTE_STATE_INVALID`, all 409."

        Design: Corner/errors/corner_state_table_rejects_repeat_transitions_across_four_aggregates
        """
        ctx = fx.cleared_order(
            api,
            buyer_overrides={
                "legal_name": "Genoa Marine Supply Srl",
                "country_code": "IT",
                "credit_rating": "A",
            },
            order_overrides={
                "incoterm_named_place": "FOB Oakland",
                "destination_country_code": "IT",
            },
            lines=WINCH_LINE,
            decision_overrides={"eccn": "3A991"},
        )
        ctx = fx.accepted_credit(
            api,
            ctx,
            lc_number="LC-CORNER-7601",
            tolerance_pct=5.00,
            expiry_date="2026-12-31T00:00:00Z",
            required_document_types=["COMMERCIAL_INVOICE", "PACKING_LIST"],
        )
        ctx = fx.booked_order(
            api,
            base=ctx,
            sailing_overrides={
                "carrier_scac": "CMDU",
                "vessel_name": "MV Ligurian Corner",
                "port_of_discharge": "ITGOA",
                "capacity_weight_kg": 40000.000,
            },
        )

        validate_error(
            api.raise_terms_finding(
                ctx["review_id"],
                f.terms_finding_payload(
                    code="AMOUNT_MISMATCH",
                    severity="MINOR",
                    clause_ref="AMOUNT",
                    detail="late finding on a submitted review",
                ),
                REVIEWER_BOB,
            ),
            ApiErrorId.ERR_REVIEW_ALREADY_SUBMITTED.value,
            409,
        )
        assert fx.data(api.get_terms_review(ctx["review_id"], REVIEWER_BOB))[
            "finding_count"
        ] == 0

        validate_error(
            api.open_terms_review(
                ctx["lc_id"],
                {
                    "expected_letter_of_credit_version": fx.credit_version(
                        api, ctx["lc_id"]
                    )
                },
                REVIEWER_BOB,
            ),
            ApiErrorId.ERR_LC_STATE_INVALID.value,
            409,
        )

        validate_error(
            api.record_screening_decision(
                ctx["screening_id"],
                f.screening_decision_payload(eccn="3A991"),
                COMPLIANCE_CARL,
            ),
            ApiErrorId.ERR_SCREENING_STATE_INVALID.value,
            409,
        )

        premature = validate_error(
            api.issue_bill_of_lading(
                ctx["booking_id"],
                f.bill_of_lading_payload(
                    [f.shipped_line(ctx["line_ids"][0], 100.000)],
                ),
                OPS_ALICE,
            ),
            ApiErrorId.ERR_BOOKING_STATE_INVALID.value,
            409,
        )
        assert premature["error_id"] != ApiErrorId.ERR_BOOKING_NOT_CONFIRMED.value

        _, meta = validate_paginated(
            api.list_documents(
                OPS_ALICE,
                {
                    "export_order_id": ctx["order_id"],
                    "doc_type": "BILL_OF_LADING",
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert meta["total_count"] == 0

        booking = fx.data(api.get_booking(ctx["booking_id"], OPS_ALICE))
        assert booking["status"] == "BOOKED"
        assert booking["version"] == ctx["booking"]["version"]


# ---------------------------------------------------------------------------
# Issuance: the pinned source version, then the issued-uniqueness index
# ---------------------------------------------------------------------------

WOOL_LINES = [
    {
        "line_no": 1,
        "goods_description": "combing machine parts",
        "hs_code": "844811",
        "quantity": 40.000,
        "unit_price_usd": 250.0000,
        "net_weight_kg": 400.000,
        "gross_weight_kg": 500.000,
        "package_count": 4,
    }
]

SECOND_WOOL_LINE = {
    "line_no": 2,
    "goods_description": "spare card clothing",
    "hs_code": "844819",
    "quantity": 20.000,
    "uom": "SET",
    "unit_price_usd": 250.0000,
    "net_weight_kg": 200.000,
    "gross_weight_kg": 250.000,
    "package_count": 2,
}


class TestIssuanceChecksThePinBeforeTheUniquenessIndex:
    def test_a_stale_draft_is_refused_then_regenerated_and_the_duplicate_blocked(
        self, api
    ):
        """PRD §2.7: "A trade document stores `pinned_order_version` equal to the
        export order's `version` at generation time; issuing that document requires
        the pinned value to still equal the order's current `version`, and a mismatch
        is refused with `ERR_DOCUMENT_STALE_SOURCE` (409)."

        Design: Corner/errors/corner_issue_checks_pinned_source_version_then_issued_uniqueness
        """
        ctx = fx.order_with_lines(
            api,
            buyer_overrides={
                "legal_name": "Montevideo Wool Exporters SA",
                "country_code": "UY",
                "credit_rating": "BB",
            },
            order_overrides={
                "incoterm_named_place": "FOB Houston",
                "destination_country_code": "UY",
            },
            lines=WOOL_LINES,
        )
        first_draft = validate_success(
            api.generate_document(f.document_payload(ctx["order_id"]), OPS_ALICE), 201
        )
        assert first_draft["revision"] == 1
        assert first_draft["pinned_order_version"] == fx.order_version(
            api, ctx["order_id"]
        )

        fx.add_line(api, ctx["order_id"], **SECOND_WOOL_LINE)

        validate_error(
            api.issue_document(first_draft["id"], OPS_ALICE),
            ApiErrorId.ERR_DOCUMENT_STALE_SOURCE.value,
            409,
        )

        second_draft = validate_success(
            api.regenerate_document(
                first_draft["id"],
                {"reason": "re-pin the invoice to the two-line order"},
                OPS_ALICE,
            ),
            201,
        )
        assert second_draft["revision"] == 2
        assert second_draft["supersedes_document_id"] == first_draft["id"]
        assert second_draft["status"] == "DRAFT"
        assert second_draft["pinned_order_version"] == fx.order_version(
            api, ctx["order_id"]
        )
        assert fx.data(api.get_document(first_draft["id"], OPS_ALICE))[
            "status"
        ] == "SUPERSEDED"

        issued = validate_success(
            api.issue_document(second_draft["id"], OPS_ALICE), 200
        )
        assert issued["status"] == "ISSUED"
        assert issued["declared_total_usd"] == approx_money(15000.00)
        assert issued["total_gross_weight_kg"] == approx_weight(750.000)

        duplicate_draft = validate_success(
            api.generate_document(f.document_payload(ctx["order_id"]), OPS_ALICE), 201
        )
        assert duplicate_draft["pinned_order_version"] == fx.order_version(
            api, ctx["order_id"]
        )
        clash = validate_error(
            api.issue_document(duplicate_draft["id"], OPS_ALICE),
            ApiErrorId.ERR_DUPLICATE_ISSUED_DOCUMENT.value,
            409,
        )
        assert clash["error_id"] != ApiErrorId.ERR_DOCUMENT_STALE_SOURCE.value

        _, meta = validate_paginated(
            api.list_documents(
                OPS_ALICE,
                {
                    "export_order_id": ctx["order_id"],
                    "doc_type": "COMMERCIAL_INVOICE",
                    "status": "ISSUED",
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert meta["total_count"] == 1
        assert fx.data(api.get_document(duplicate_draft["id"], OPS_ALICE))[
            "status"
        ] == "DRAFT"


class TestLicenceValueAndNumberGuardsAreIndependent:
    def test_a_short_licence_cannot_clear_and_its_number_cannot_be_reused(self, api):
        """PRD §3.3: "The charge is gated: the license's current `consumed_value_usd`
        plus the order's `ordered_goods_value_usd` rounded to two decimal places must
        be at most `licensed_value_usd`."

        Design: Corner/errors/corner_license_value_and_number_guards_on_one_screening
        """
        ctx = fx.submitted_for_compliance(
            api,
            buyer_overrides={
                "legal_name": "Ankara Aero Components AS",
                "country_code": "TR",
                "credit_rating": "BBB",
                "sanctions_tier": "WATCHLIST",
            },
            order_overrides={
                "incoterm": "FCA",
                "incoterm_named_place": "FCA Wichita",
                "destination_country_code": "TR",
            },
            lines=[
                {
                    "line_no": 1,
                    "goods_description": "avionics housings",
                    "hs_code": "880330",
                    "quantity": 100.000,
                    "unit_price_usd": 250.0000,
                    "net_weight_kg": 700.000,
                    "gross_weight_kg": 800.000,
                    "package_count": 8,
                }
            ],
        )
        fx.data(
            api.record_screening_decision(
                ctx["screening_id"],
                f.screening_decision_payload(
                    license_determination="LICENSE_REQUIRED", eccn="3A991"
                ),
                COMPLIANCE_CARL,
            )
        )
        licence = validate_success(
            api.create_license(
                ctx["screening_id"],
                f.license_payload(
                    license_number="BIS-CORNER-7701",
                    eccn="3A991",
                    valid_from="2026-07-01T00:00:00Z",
                    valid_to="2026-08-31T00:00:00Z",
                    licensed_value_usd=20000.00,
                ),
                COMPLIANCE_CARL,
            ),
            201,
        )

        validate_error(
            api.clear_with_license(
                ctx["screening_id"],
                {"export_license_id": licence["id"]},
                COMPLIANCE_CARL,
            ),
            ApiErrorId.ERR_LICENSE_VALUE_EXHAUSTED.value,
            409,
        )

        screening = fx.data(api.get_screening(ctx["screening_id"], COMPLIANCE_CARL))
        assert screening["status"] == "PENDING_LICENSE"
        assert screening.get("export_license_id") is None
        assert screening.get("cleared_at") is None
        assert_order_dimensions(
            fx.read_order(api, ctx["order_id"]), fulfillment="COMPLIANCE_PENDING"
        )

        untouched = fx.data(api.get_license(licence["id"], COMPLIANCE_CARL))
        assert untouched["status"] == "ISSUED"
        assert untouched["consumed_value_usd"] == approx_money(0.00)
        assert untouched["remaining_value_usd"] == approx_money(20000.00)

        validate_error(
            api.create_license(
                ctx["screening_id"],
                f.license_payload(
                    license_number="BIS-CORNER-7701",
                    authority="DDTC",
                    eccn="3A991",
                    valid_from="2026-09-01T00:00:00Z",
                    valid_to="2026-10-31T00:00:00Z",
                    licensed_value_usd=50000.00,
                ),
                COMPLIANCE_CARL,
            ),
            ApiErrorId.ERR_DUPLICATE_LICENSE_NUMBER.value,
            409,
        )

        _, meta = validate_paginated(
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


# ---------------------------------------------------------------------------
# The cut-off instant and the swept sailing status are different gates
# ---------------------------------------------------------------------------

PAST_SAILING = {
    "carrier_scac": "EGYS",
    "vessel_name": "MV Nile Corner",
    "voyage_no": "CD-2701",
    "port_of_loading": "USSAV",
    "port_of_discharge": "EGALY",
    "cutoff_at": "2026-07-15T00:00:00Z",
    "etd": "2026-07-20T00:00:00Z",
    "eta": "2026-07-28T00:00:00Z",
    "capacity_weight_kg": 40000.000,
}

NEAR_SAILING = {
    "carrier_scac": "EGYS",
    "vessel_name": "MV Delta Corner",
    "voyage_no": "CD-2702",
    "port_of_loading": "USSAV",
    "port_of_discharge": "EGALY",
    "cutoff_at": "2026-08-10T00:00:00Z",
    "etd": "2026-08-14T00:00:00Z",
    "eta": "2026-08-30T00:00:00Z",
    "capacity_weight_kg": 40000.000,
}


class TestSailingGatesSplitBetweenInstantAndSweptStatus:
    def test_a_past_cutoff_answers_on_the_instant_and_a_swept_one_on_the_status(
        self, api
    ):
        """PRD §2.5: "Every vessel sailing whose `status` is `OPEN` or `FULL` moves to
        `CUTOFF_PASSED` once the new instant is at or after its `cutoff_at`, and then
        on to `DEPARTED` once the new instant is at or after its `etd`."

        Design: Corner/errors/corner_sailing_gates_split_between_cutoff_instant_and_swept_status
        """
        ctx = fx.cleared_order(
            api,
            buyer_overrides={
                "legal_name": "Alexandria Cotton Export SAE",
                "country_code": "EG",
                "credit_rating": "BB",
            },
            order_overrides={
                "incoterm_named_place": "FOB Savannah",
                "destination_country_code": "EG",
            },
            lines=[
                {
                    "line_no": 1,
                    "goods_description": "ginning spares",
                    "hs_code": "844790",
                    "quantity": 100.000,
                    "unit_price_usd": 250.0000,
                    "net_weight_kg": 900.000,
                    "gross_weight_kg": 1000.000,
                    "package_count": 10,
                }
            ],
            decision_overrides={"eccn": "3A991"},
        )

        past = fx.create_sailing(api, **PAST_SAILING)
        assert past["status"] == "OPEN"
        assert past["booked_weight_kg"] == approx_weight(0.000)

        validate_error(
            api.create_booking(
                f.booking_payload(
                    ctx["order_id"], past["id"], past["version"], booked_weight_kg=1000.000
                ),
                OPS_ALICE,
            ),
            ApiErrorId.ERR_SAILING_CUTOFF_PASSED.value,
            409,
        )

        near = fx.create_sailing(api, **NEAR_SAILING)
        assert near["status"] == "OPEN"

        fx.set_clock(api, "2026-08-10T00:00:00Z")

        swept_near = fx.read_sailing(api, near["id"])
        assert swept_near["status"] == "CUTOFF_PASSED"
        assert swept_near["version"] == near["version"] + 1
        assert fx.read_sailing(api, past["id"])["status"] == "DEPARTED"

        blocked = validate_error(
            api.create_booking(
                f.booking_payload(
                    ctx["order_id"],
                    near["id"],
                    swept_near["version"],
                    booked_weight_kg=1000.000,
                ),
                OPS_ALICE,
            ),
            ApiErrorId.ERR_SAILING_NOT_OPEN.value,
            409,
        )
        assert blocked["error_id"] != ApiErrorId.ERR_SAILING_CUTOFF_PASSED.value

        _, meta = validate_paginated(
            api.list_bookings(
                OPS_ALICE,
                {"export_order_id": ctx["order_id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 0
        assert fx.read_sailing(api, past["id"])["booked_weight_kg"] == approx_weight(
            0.000
        )
        assert fx.read_sailing(api, near["id"])["booked_weight_kg"] == approx_weight(
            0.000
        )


# ---------------------------------------------------------------------------
# Shipment and presentation deadlines
# ---------------------------------------------------------------------------

CRUSHER_LINE = [
    {
        "line_no": 1,
        "goods_description": "crusher liners",
        "hs_code": "847420",
        "quantity": 100.000,
        "unit_price_usd": 250.0000,
        "net_weight_kg": 1000.000,
        "gross_weight_kg": 1200.000,
        "package_count": 10,
    }
]


class TestDeadlinesRejectBeforeAnyDocumentIsWritten:
    def test_the_shipment_date_and_the_presentation_period_are_separate_gates(
        self, api
    ):
        """PRD §2.11: "A bill of lading's `on_board_date` is at or before both the
        credit's `latest_shipment_date` and the order's `ship_by_date`, on
        bill-of-lading issuance — otherwise `ERR_LATEST_SHIPMENT_DATE_PASSED` (409)."

        Design: Corner/errors/corner_shipment_and_presentation_deadlines_reject_before_any_document_is_written
        """
        ctx = fx.cleared_order(
            api,
            buyer_overrides={
                "legal_name": "Durban Mining Spares Pty",
                "country_code": "ZA",
                "credit_rating": "BB",
            },
            order_overrides={
                "incoterm_named_place": "FOB Oakland",
                "destination_country_code": "ZA",
                "destination_zone": "ZONE_3",
            },
            lines=CRUSHER_LINE,
            decision_overrides={"eccn": "3A991"},
        )
        ctx = fx.accepted_credit(
            api,
            ctx,
            lc_number="LC-CORNER-7801",
            latest_shipment_date="2026-08-31T00:00:00Z",
            expiry_date="2026-12-31T00:00:00Z",
            presentation_period_days=5,
            required_document_types=["COMMERCIAL_INVOICE", "PACKING_LIST"],
        )
        ctx = fx.booked_order(
            api,
            base=ctx,
            sailing_overrides={
                "carrier_scac": "SAFM",
                "vessel_name": "MV Cape Corner",
                "port_of_discharge": "ZADUR",
                "destination_zone": "ZONE_3",
                "cutoff_at": "2026-08-20T00:00:00Z",
                "etd": "2026-08-23T00:00:00Z",
                "eta": "2026-09-18T00:00:00Z",
                "capacity_weight_kg": 40000.000,
                "tariff_rate_per_1000kg_usd": 320.00,
            },
        )
        ctx = fx.confirmed_booking(api, ctx)
        line_id = ctx["line_ids"][0]

        validate_error(
            api.issue_bill_of_lading(
                ctx["booking_id"],
                f.bill_of_lading_payload([f.shipped_line(line_id, 0.000)]),
                OPS_ALICE,
            ),
            ApiErrorId.ERR_ZERO_SHIPPED_QUANTITY.value,
            422,
        )

        validate_error(
            api.issue_bill_of_lading(
                ctx["booking_id"],
                f.bill_of_lading_payload(
                    [f.shipped_line(line_id, 100.000)],
                    on_board_date="2026-09-15T00:00:00Z",
                ),
                OPS_ALICE,
            ),
            ApiErrorId.ERR_LATEST_SHIPMENT_DATE_PASSED.value,
            409,
        )

        bill = validate_success(
            api.issue_bill_of_lading(
                ctx["booking_id"],
                f.bill_of_lading_payload([f.shipped_line(line_id, 100.000)]),
                OPS_ALICE,
            ),
            201,
        )
        assert bill["doc_type"] == "BILL_OF_LADING"
        assert bill["status"] == "ISSUED"
        assert bill["on_board_date"] == "2026-08-01T00:00:00Z"
        assert fx.data(api.get_booking(ctx["booking_id"], OPS_ALICE))[
            "status"
        ] == "SHIPPED"
        assert_order_dimensions(
            fx.read_order(api, ctx["order_id"]),
            fulfillment="SHIPPED",
            settlement="LC_ACCEPTED",
        )

        fx.set_clock(api, "2026-08-10T00:00:00Z")

        validate_error(
            api.lodge_presentation(
                f.presentation_payload(
                    ctx["lc_id"],
                    ctx["order_id"],
                    [ctx["invoice_id"], ctx["packing_list_id"], bill["id"]],
                    fx.order_version(api, ctx["order_id"]),
                ),
                OPS_ALICE,
            ),
            ApiErrorId.ERR_PRESENTATION_PERIOD_ELAPSED.value,
            409,
        )

        _, meta = validate_paginated(
            api.list_presentations(
                REVIEWER_BOB,
                {"export_order_id": ctx["order_id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 0
        assert_order_dimensions(
            fx.read_order(api, ctx["order_id"]), settlement="LC_ACCEPTED"
        )

        _, meta = validate_paginated(
            api.list_documents(
                OPS_ALICE,
                {
                    "export_order_id": ctx["order_id"],
                    "doc_type": "BILL_OF_LADING",
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert meta["total_count"] == 1


class TestClaimOnASweptPolicyReportsPolicyState:
    def test_the_policy_status_gate_outranks_the_pinned_version(self, api):
        """PRD §2.11: "Cross-entity state preconditions hold. Booking freight requires
        the order's screening to be `CLEARED` (`ERR_ORDER_NOT_COMPLIANCE_CLEARED`) and
        the sailing to be bookable (`ERR_SAILING_NOT_OPEN`); confirming a booking
        requires the sailing not to have passed its cut-off or departed
        (`ERR_SAILING_NOT_OPEN`); lodging a presentation requires the credit to be
        `ACCEPTED` (`ERR_LC_NOT_ACCEPTED`); issuing a bill of lading requires the
        booking to be `CONFIRMED` (`ERR_BOOKING_NOT_CONFIRMED`); filing a claim
        requires the policy to be `ACTIVE` (`ERR_POLICY_NOT_ACTIVE`)."

        Design: Corner/errors/corner_claim_on_a_swept_expired_policy_reports_policy_state_not_staleness
        """
        ctx = fx.cleared_order(
            api,
            buyer_overrides={
                "legal_name": "Manila Coldchain Inc",
                "country_code": "PH",
                "credit_rating": "BB",
            },
            order_overrides={
                "incoterm_named_place": "FOB Long Beach",
                "destination_country_code": "PH",
                "destination_zone": "ZONE_3",
            },
            decision_overrides={"eccn": "3A991"},
        )
        policy = fx.create_policy(
            api,
            ctx["buyer_id"],
            policy_number="POL-CORNER-7901",
            credit_limit_usd=40000.00,
            insured_pct=85.00,
            deductible_usd=1000.00,
            effective_from="2026-07-01T00:00:00Z",
            effective_to="2026-08-25T00:00:00Z",
        )
        version_at_creation = policy["version"]

        ctx = fx.booked_order(
            api,
            base=ctx,
            sailing_overrides={
                "carrier_scac": "APLU",
                "vessel_name": "MV Luzon Corner",
                "port_of_discharge": "PHMNL",
                "destination_zone": "ZONE_3",
                "cutoff_at": "2026-08-18T00:00:00Z",
                "etd": "2026-08-21T00:00:00Z",
                "eta": "2026-09-14T00:00:00Z",
                "capacity_weight_kg": 40000.000,
                "tariff_rate_per_1000kg_usd": 315.00,
            },
        )
        ctx = fx.confirmed_booking(api, ctx)
        ctx = fx.shipped_order(api, ctx)
        ctx = fx.accepted_credit(
            api,
            ctx,
            lc_number="LC-CORNER-7901",
            expiry_date="2026-12-31T00:00:00Z",
            required_document_types=["COMMERCIAL_INVOICE", "PACKING_LIST"],
        )
        assert fx.read_order(api, ctx["order_id"])[
            "insured_exposure_usd"
        ] == approx_money(25000.00)

        ctx = fx.lodged_presentation(
            api, ctx, document_ids=[ctx["invoice_id"], ctx["packing_list_id"]]
        )
        ctx = fx.examined_presentation(api, ctx, [])
        assert ctx["presentation"]["status"] == "COMPLIED"
        assert ctx["presentation"]["presented_amount_usd"] == approx_money(25000.00)

        refused = validate_success(
            api.dishonour_presentation(
                ctx["presentation_id"],
                {"refusal_reason": "issuing bank refused to remit on maturity"},
                FINANCE_FRANK,
            ),
            200,
        )
        assert refused["status"] == "REFUSED"
        assert_order_dimensions(
            fx.read_order(api, ctx["order_id"]), settlement="DISHONORED"
        )

        dispute = validate_success(
            api.open_dispute(
                f.dispute_payload(
                    ctx["order_id"],
                    dispute_type="NON_PAYMENT",
                    claimed_amount_usd=25000.00,
                ),
                FINANCE_FRANK,
            ),
            201,
        )

        version_before_sweep = fx.policy_version(api, policy["id"])
        assert version_before_sweep > version_at_creation
        fx.set_clock(api, "2026-09-01T00:00:00Z")

        swept = fx.read_policy(api, policy["id"])
        assert swept["status"] == "EXPIRED"
        assert swept["version"] == version_before_sweep + 1

        validate_error(
            api.file_claim(
                policy["id"],
                {
                    "dispute_case_id": dispute["id"],
                    "expected_credit_insurance_policy_version": swept["version"],
                },
                FINANCE_FRANK,
            ),
            ApiErrorId.ERR_POLICY_NOT_ACTIVE.value,
            409,
        )
        stale = validate_error(
            api.file_claim(
                policy["id"],
                {
                    "dispute_case_id": dispute["id"],
                    "expected_credit_insurance_policy_version": version_at_creation,
                },
                FINANCE_FRANK,
            ),
            ApiErrorId.ERR_POLICY_NOT_ACTIVE.value,
            409,
        )
        assert stale["error_id"] != ApiErrorId.ERR_STALE_POLICY_VERSION.value

        unchanged = fx.data(api.get_dispute(dispute["id"], FINANCE_FRANK))
        assert unchanged["status"] == "OPEN"
        assert unchanged.get("credit_insurance_policy_id") is None
        assert_order_dimensions(
            fx.read_order(api, ctx["order_id"]), settlement="DISHONORED"
        )
