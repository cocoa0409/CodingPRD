"""Writes that must be fully computed by the time they return, and their undo."""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    OPS_ALICE,
    REVIEWER_BOB,
    approx_money,
    approx_weight,
    assert_order_dimensions,
    factories as f,
    fixtures as fx,
    validate_paginated,
    validate_success,
)

Json = Dict[str, Any]

ROLLER_LINE = [
    {
        "line_no": 1,
        "goods_description": "fish grading rollers",
        "hs_code": "843880",
        "quantity": 100.000,
        "unit_price_usd": 250.0000,
        "net_weight_kg": 1000.000,
        "gross_weight_kg": 1200.000,
        "package_count": 10,
    }
]

VIGO_SAILING = {
    "carrier_scac": "MAEU",
    "vessel_name": "MV Iberia Corner",
    "voyage_no": "CD-9101",
    "port_of_loading": "USBAL",
    "port_of_discharge": "ESVGO",
    "destination_zone": "ZONE_2",
    "cutoff_at": "2026-08-18T00:00:00Z",
    "etd": "2026-08-21T00:00:00Z",
    "eta": "2026-09-02T00:00:00Z",
    "capacity_weight_kg": 20000.000,
    "tariff_rate_per_1000kg_usd": 300.00,
}


class TestASingleBookingWriteIsAlreadyVisibleEverywhere:
    def test_the_container_minimum_proves_the_reads_show_computed_state(self, api):
        """PRD §3.6: "`chargeable_weight_kg` is the greater of `booked_weight_kg` and
        the container minimum for the booked equipment, at 3 decimal places, where the
        minimums are 0 kilograms for `LCL`, 8,000 for `DRY_20`, 15,000 for `DRY_40` and
        12,000 for `REEFER_40`."

        Design: Corner/consistency_model/corner_one_booking_write_is_already_visible_in_four_aggregates
        """
        ctx = fx.cleared_order(
            api,
            decision_overrides={"eccn": "3A991"},
            buyer_overrides={
                "legal_name": "Vigo Seafood Equipment SL",
                "country_code": "ES",
                "credit_rating": "A",
            },
            order_overrides={
                "incoterm_named_place": "Port of Baltimore",
                "destination_country_code": "ES",
                "destination_zone": "ZONE_2",
            },
            lines=ROLLER_LINE,
        )
        sailing = fx.create_sailing(api, **VIGO_SAILING)
        assert sailing["booked_weight_kg"] == approx_weight(0.000)

        booking = validate_success(
            api.create_booking(
                f.booking_payload(
                    ctx["order_id"],
                    sailing["id"],
                    sailing["version"],
                    booked_weight_kg=1200.000,
                    container_type="DRY_20",
                ),
                OPS_ALICE,
            ),
            201,
        )
        assert booking["status"] == "BOOKED"
        assert booking["chargeable_weight_kg"] == approx_weight(8000.000)
        assert booking["effective_window_start"].startswith("2026-08-18T00:00:00")
        assert booking["effective_window_end"].startswith("2026-08-22T00:00:00")

        charged = fx.read_sailing(api, sailing["id"])
        assert charged["booked_weight_kg"] == approx_weight(1200.000)
        assert charged["status"] == "OPEN"
        assert charged["version"] == sailing["version"] + 1

        order = fx.read_order(api, ctx["order_id"])
        assert_order_dimensions(order, fulfillment="BOOKED")
        assert order["provisional_seller_cost_usd"] == approx_money(836.00)
        assert order["provisional_buyer_cost_usd"] == approx_money(5216.25)

        allocation = validate_success(
            api.get_cost_allocation(ctx["order_id"], OPS_ALICE)
        )
        assert allocation["provisional_seller_cost_usd"] == approx_money(836.00)
        assert allocation["provisional_buyer_cost_usd"] == approx_money(5216.25)
        assert fx.order_version(api, ctx["order_id"]) == order["version"]

        reread = fx.data(api.get_booking(booking["id"], OPS_ALICE))
        assert reread["chargeable_weight_kg"] == approx_weight(8000.000)
        assert reread["status"] == "BOOKED"
        assert reread["booked_weight_kg"] == approx_weight(1200.000)


# ---------------------------------------------------------------------------
# The discrepant branch as a scoped compensation
# ---------------------------------------------------------------------------

WINCH_LINE = [
    {
        "line_no": 1,
        "goods_description": "deck winch spares",
        "hs_code": "843110",
        "quantity": 100.000,
        "unit_price_usd": 250.0000,
        "net_weight_kg": 1000.000,
        "gross_weight_kg": 1200.000,
        "package_count": 10,
    }
]

SPLIT_SAILING = {
    "carrier_scac": "MSCU",
    "vessel_name": "MV Adriatic Corner",
    "voyage_no": "CD-9201",
    "port_of_loading": "USSAV",
    "port_of_discharge": "HRSPU",
    "destination_zone": "ZONE_2",
    "cutoff_at": "2026-08-18T00:00:00Z",
    "etd": "2026-08-21T00:00:00Z",
    "eta": "2026-09-09T00:00:00Z",
    "capacity_weight_kg": 25000.000,
    "tariff_rate_per_1000kg_usd": 295.00,
}

EXAMINATION_FINDINGS = [
    {
        "code": "WEIGHT_MISMATCH",
        "severity": "MAJOR",
        "clause_ref": "GOODS",
        "detail": "packing list gross weight disagrees with the bill of lading",
    },
    {
        "code": "DESCRIPTION_MISMATCH",
        "severity": "MINOR",
        "clause_ref": "GOODS",
        "detail": "goods description abbreviated on the invoice",
    },
]


def _tender_awaiting_examination(api) -> Json:
    """A two-document tender lodged at round 1 against an accepted credit."""
    ctx = fx.full_tender(
        api,
        buyer_overrides={
            "legal_name": "Split Shipyard Supplies doo",
            "country_code": "HR",
            "credit_rating": "BBB",
        },
        order_overrides={
            "incoterm_named_place": "Port of Savannah",
            "destination_country_code": "HR",
            "destination_zone": "ZONE_2",
        },
        lines=WINCH_LINE,
        sailing_overrides=SPLIT_SAILING,
        credit_overrides={
            "lc_number": "LC-CORNER-9201",
            "issuing_bank_swift": "ZABAHR2X",
            "tolerance_pct": 10.00,
            "expiry_date": "2026-12-31T00:00:00Z",
            "latest_shipment_date": "2026-09-20T00:00:00Z",
            "required_document_types": ["COMMERCIAL_INVOICE", "PACKING_LIST"],
        },
    )
    ctx["order_version_before_lodging"] = fx.order_version(api, ctx["order_id"])
    ctx = fx.lodged_presentation(
        api, ctx, [ctx["invoice_id"], ctx["packing_list_id"]]
    )
    return ctx


class TestADiscrepantExaminationUndoesOnlyTheLodgingStep:
    def test_the_money_axis_reverts_while_the_tender_and_the_credit_stand(self, api):
        """PRD §3.7: "When the examination raises **at least one** finding of `severity`
        `CRITICAL` or `MAJOR`, the presentation moves `PRESENTED` to `DISCREPANT`,
        `open_finding_count` is stored, and the order's `settlement_status` moves from
        `DOCS_PRESENTED` back to `LC_ACCEPTED`."

        Design: Corner/consistency_model/corner_a_discrepant_examination_compensates_the_order_back_to_lc_accepted
        """
        ctx = _tender_awaiting_examination(api)

        assert ctx["presentation"]["status"] == "PRESENTED"
        assert ctx["presentation"]["presentation_round"] == 1
        assert_order_dimensions(ctx["order"], settlement="DOCS_PRESENTED")
        assert ctx["order"]["outstanding_receivable_usd"] == approx_money(25000.00)

        examined = validate_success(
            api.examine_presentation(
                ctx["presentation_id"], {"findings": EXAMINATION_FINDINGS}, REVIEWER_BOB
            ),
            200,
        )
        assert examined["status"] == "DISCREPANT"
        assert examined["open_finding_count"] == 2
        assert examined["examination_risk_score"] > 0

        order = fx.read_order(api, ctx["order_id"])
        assert_order_dimensions(order, fulfillment="SHIPPED", settlement="LC_ACCEPTED")
        assert order["version"] == ctx["order_version_before_lodging"] + 2
        assert order["outstanding_receivable_usd"] == approx_money(25000.00)

        findings, meta = validate_paginated(
            api.list_findings(
                REVIEWER_BOB,
                {
                    "document_presentation_id": ctx["presentation_id"],
                    "cure_status": "OPEN",
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert meta["total_count"] == 2
        assert {row["source"] for row in findings} == {"DOCUMENT"}
        assert {row["raised_in_round"] for row in findings} == {1}

        links = fx.presentation_links(api, ctx["presentation_id"])
        assert len(links) == 2
        assert {link["link_status"] for link in links} == {"ACTIVE"}
        assert {link["linked_in_round"] for link in links} == {1}

        credit = fx.read_credit(api, ctx["lc_id"])
        assert credit["status"] == "ACCEPTED"
        assert credit["drawn_amount_usd"] == approx_money(0.00)
