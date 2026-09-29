"""One write propagating three and four links deep, and its exact compensations."""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    COMPLIANCE_CARL,
    FINANCE_FRANK,
    OPS_ALICE,
    REVIEWER_BOB,
    approx_money,
    approx_weight,
    assert_order_dimensions,
    factories as f,
    find_by,
    fixtures as fx,
)

Json = Dict[str, Any]


def _flagged_after_booking(api) -> Json:
    """A licence-cleared, fully booked order whose buyer is then designated."""
    ctx = fx.licensed_cleared_order(
        api,
        eccn="1C010",
        license_overrides={
            "license_number": "LIC-2195-A",
            "eccn": "1C010",
            "licensed_value_usd": 25000.00,
            "valid_from": "2026-07-01T00:00:00Z",
            "valid_to": "2026-12-31T00:00:00Z",
        },
    )
    ctx = fx.booked_order(
        api,
        base=ctx,
        sailing_overrides={"capacity_weight_kg": 1000.000},
        booking_overrides={"booked_weight_kg": 1000.000, "container_type": "LCL"},
    )
    ctx["flag_response"] = api.patch_restricted_party_flag(
        ctx["buyer_id"],
        {
            "restricted_party_flag": True,
            "restricted_party_reason": "denied party match on the ultimate parent",
        },
        COMPLIANCE_CARL,
    )
    ctx["buyer"] = fx.data(ctx["flag_response"])
    ctx["order"] = fx.read_order(api, ctx["order_id"])
    return ctx


class TestRestrictedPartyFourLinkCascade:
    def test_flag_blocks_the_order_cancels_the_booking_and_reopens_the_screening(
        self, api
    ):
        """PRD §3.1: "every freight booking of that order whose `status` is
        `BOOKED` or `CONFIRMED` moves to `CANCELLED` with `cancel_reason` set to
        the literal string `'RESTRICTED_PARTY_CASCADE'`."

        Design: Difficulty/transitive_cascade/restricted_party_flag_depth_four_cascade_releases_sailing_capacity_and_license_value
        """
        ctx = _flagged_after_booking(api)

        assert_order_dimensions(
            ctx["order"], fulfillment="COMPLIANCE_BLOCKED", settlement="UNSECURED"
        )

        booking = fx.data(api.get_booking(ctx["booking_id"], OPS_ALICE))
        assert booking["status"] == "CANCELLED"
        assert booking["cancel_reason"] == "RESTRICTED_PARTY_CASCADE"

        screening = fx.data(api.get_screening(ctx["screening_id"], COMPLIANCE_CARL))
        assert screening["status"] == "INITIATED"
        assert screening["ruleset_version"] == 2
        assert screening["cleared_at"] is None

    def test_flag_frees_the_sailing_capacity_and_hands_the_licence_value_back(self, api):
        """PRD §3.1: "`licensed_value_allocated_usd` is reset to 0.00 and the
        charged license's `consumed_value_usd` and `remaining_value_usd` are
        recomputed from the remaining charged orders."

        Design: Difficulty/transitive_cascade/restricted_party_flag_depth_four_cascade_releases_sailing_capacity_and_license_value
        """
        ctx = _flagged_after_booking(api)

        sailing = fx.read_sailing(api, ctx["sailing_id"])
        assert sailing["booked_weight_kg"] == approx_weight(0.000)
        assert sailing["status"] == "OPEN"

        licence = fx.data(api.get_license(ctx["license_id"], COMPLIANCE_CARL))
        assert licence["consumed_value_usd"] == approx_money(0.00)
        assert licence["remaining_value_usd"] == approx_money(25000.00)
        assert licence["status"] == "ACTIVE"

        assert ctx["order"]["licensed_value_allocated_usd"] == approx_money(0.00)


# ---------------------------------------------------------------------------
# Settlement three links deep: order, policy, buyer
# ---------------------------------------------------------------------------


def _settled_exactly_exhausting_policy(api) -> Json:
    """A policy whose limit equals the exposure, released again by settlement."""
    ctx = fx.cleared_order(api)
    ctx["policy"] = fx.create_policy(
        api,
        ctx["buyer_id"],
        policy_number="POL-D",
        credit_limit_usd=25000.00,
        insured_pct=90.00,
        deductible_usd=5000.00,
    )
    ctx["policy_id"] = ctx["policy"]["id"]
    ctx = fx.booked_order(api, base=ctx)
    ctx = fx.confirmed_booking(api, ctx)
    ctx = fx.shipped_order(api, ctx)
    ctx = fx.accepted_credit(api, ctx, lc_number="LC-2195-005")
    ctx["policy_after_charge"] = fx.read_policy(api, ctx["policy_id"])
    ctx = fx.lodged_presentation(api, ctx)
    ctx = fx.examined_presentation(api, ctx, [])
    ctx["presentation"] = fx.data(
        api.settle_presentation(
            ctx["presentation_id"],
            f.settlement_payload(24850.00, value_date="2026-08-01T00:00:00Z"),
            FINANCE_FRANK,
        )
    )
    ctx["order"] = fx.read_order(api, ctx["order_id"])
    return ctx


class TestSettlementThreeLinkCascade:
    def test_settlement_pays_the_order_and_utilises_the_credit(self, api):
        """PRD §3.8: "Settlement stores both fields, moves the presentation from
        `COMPLIED` to `HONOURED`, and increases the credit's `drawn_amount_usd`
        by the received amount."

        Design: Difficulty/transitive_cascade/settlement_depth_three_cascade_returns_exhausted_policy_to_active_and_zeroes_buyer_exposure
        """
        ctx = _settled_exactly_exhausting_policy(api)

        assert ctx["presentation"]["status"] == "HONOURED"
        assert ctx["presentation"]["negotiable_amount_usd"] == approx_money(24850.00)
        assert_order_dimensions(ctx["order"], fulfillment="CLOSED", settlement="PAID")
        assert ctx["order"]["outstanding_receivable_usd"] == approx_money(150.00)

        credit = fx.read_credit(api, ctx["lc_id"])
        assert credit["status"] == "UTILISED"
        assert credit["drawn_amount_usd"] == approx_money(24850.00)

    def test_exhausted_policy_returns_to_active_and_the_buyer_exposure_zeroes(self, api):
        """PRD §3.8: "a policy that had been `EXHAUSTED` returns to `ACTIVE` once
        `available_limit_usd` becomes strictly greater than 0.00."

        Design: Difficulty/transitive_cascade/settlement_depth_three_cascade_returns_exhausted_policy_to_active_and_zeroes_buyer_exposure
        """
        ctx = _settled_exactly_exhausting_policy(api)

        assert ctx["policy_after_charge"]["status"] == "EXHAUSTED"
        assert ctx["policy_after_charge"]["available_limit_usd"] == approx_money(0.00)

        policy = fx.read_policy(api, ctx["policy_id"])
        assert policy["utilized_usd"] == approx_money(0.00)
        assert policy["available_limit_usd"] == approx_money(25000.00)
        assert policy["status"] == "ACTIVE"
        assert policy["premium_usd"] == approx_money(191.25)

        buyer = fx.data(api.get_buyer(ctx["buyer_id"], COMPLIANCE_CARL))
        assert buyer["aggregate_exposure_usd"] == approx_money(0.00)


# ---------------------------------------------------------------------------
# Voiding the tendered invoice three links deep
# ---------------------------------------------------------------------------


def _voided_tendered_invoice(api) -> Json:
    """A lodged, unexamined tender whose commercial invoice is then voided."""
    ctx = fx.full_tender(api, credit_overrides={"lc_number": "LC-2195-006"})
    ctx = fx.lodged_presentation(api, ctx)
    links = fx.presentation_links(api, ctx["presentation_id"])
    ctx["invoice_link"] = find_by(links, trade_document_id=ctx["invoice_id"])
    ctx["invoice"] = fx.data(
        api.void_document(
            ctx["invoice_id"],
            {"void_reason": "invoice reissued against corrected figures"},
            OPS_ALICE,
        )
    )
    ctx["order"] = fx.read_order(api, ctx["order_id"])
    return ctx


class TestInvoiceVoidThreeLinkCascade:
    def test_void_invalidates_the_link_and_drives_the_tender_to_discrepant(self, api):
        """PRD §3.5: "Every link referencing the voided document with
        `link_status` `ACTIVE` moves to `INVALIDATED`."

        Design: Difficulty/transitive_cascade/invoice_void_depth_three_cascade_reverts_presentation_and_order_money_dimension
        """
        ctx = _voided_tendered_invoice(api)

        assert ctx["invoice"]["status"] == "VOIDED"

        link = fx.data(api.get_presentation_link(ctx["invoice_link"]["id"], OPS_ALICE))
        assert link["link_status"] == "INVALIDATED"

        presentation = fx.data(api.get_presentation(ctx["presentation_id"], REVIEWER_BOB))
        assert presentation["status"] == "DISCREPANT"
        assert presentation["open_finding_count"] == 1
        assert presentation["presentation_round"] == 1

    def test_void_raises_one_critical_document_finding_and_reverts_the_money_axis(
        self, api
    ):
        """PRD §3.5: "the system raises a finding of its own accord with `source`
        `DOCUMENT`, `code` `DOC_VOIDED`, `severity` `CRITICAL`, `clause_ref`
        `DOCUMENTS`, `cure_status` `OPEN` and `raised_in_round` equal to that
        presentation's current `presentation_round`."

        Design: Difficulty/transitive_cascade/invoice_void_depth_three_cascade_reverts_presentation_and_order_money_dimension
        """
        ctx = _voided_tendered_invoice(api)

        findings = fx.findings_for_presentation(api, ctx["presentation_id"])
        assert len(findings) == 1
        finding = findings[0]
        assert finding["source"] == "DOCUMENT"
        assert finding["code"] == "DOC_VOIDED"
        assert finding["severity"] == "CRITICAL"
        assert finding["clause_ref"] == "DOCUMENTS"
        assert finding["cure_status"] == "OPEN"
        assert finding["raised_in_round"] == 1

        assert_order_dimensions(
            ctx["order"], fulfillment="SHIPPED", settlement="LC_ACCEPTED"
        )
        credit = fx.read_credit(api, ctx["lc_id"])
        assert credit["status"] == "ACCEPTED"
        assert credit["drawn_amount_usd"] == approx_money(0.00)
