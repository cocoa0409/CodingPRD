"""Requests that violate two rules at once report the higher-priority one only."""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    COMPLIANCE_CARL,
    OPS_ALICE,
    REVIEWER_BOB,
    USER_IDS,
    ApiErrorId,
    approx_money,
    approx_weight,
    assert_order_dimensions,
    factories as f,
    fixtures as fx,
    make_reviewer_headers,
    validate_error,
)

Json = Dict[str, Any]


# ---------------------------------------------------------------------------
# Conflict A: the compliance gate outranks the capacity ledger
# ---------------------------------------------------------------------------


def _pending_order_against_a_nearly_full_sailing(api) -> Json:
    """A sailing with 400 kg of headroom and a 500 kg request from a pending order."""
    ctx = fx.cleared_order(api)
    ctx = fx.booked_order(
        api,
        base=ctx,
        sailing_overrides={"capacity_weight_kg": 1000.000},
        booking_overrides={"booked_weight_kg": 600.000, "container_type": "LCL"},
    )
    order_a = fx.create_order(api, ctx["buyer_id"])
    fx.add_line(api, order_a["id"])
    ctx["order_a"] = fx.data(api.submit_for_compliance(order_a["id"], OPS_ALICE))
    ctx["order_a_id"] = order_a["id"]
    ctx["attempt"] = api.create_booking(
        f.booking_payload(
            order_a["id"],
            ctx["sailing_id"],
            fx.sailing_version(api, ctx["sailing_id"]),
            booked_weight_kg=500.000,
            container_type="LCL",
        ),
        OPS_ALICE,
    )
    return ctx


class TestConflictAComplianceGateOutranksCapacity:
    def test_uncleared_order_reports_the_compliance_gate_not_the_capacity_excess(
        self, api
    ):
        """PRD §2.11: "**Conflict A:** a booking request against an order that is
        *not* compliance cleared *and* a sailing with no headroom left reports this
        priority-12 error, and the capacity check at priority 31 is never reached."

        Design: Difficulty/priority_pair_validation_conflict/conflict_a_order_not_compliance_cleared_masks_sailing_capacity_exceeded
        """
        ctx = _pending_order_against_a_nearly_full_sailing(api)
        validate_error(ctx["attempt"], ApiErrorId.ERR_ORDER_NOT_COMPLIANCE_CLEARED.value)

    def test_rejected_booking_leaves_the_sailing_ledger_untouched(self, api):
        """PRD §2.12: "A sailing's `booked_weight_kg` always equals the sum of
        `booked_weight_kg` over its bookings whose `status` is `BOOKED`,
        `CONFIRMED` or `SHIPPED`; a `CANCELLED` booking contributes 0.000."

        Design: Difficulty/priority_pair_validation_conflict/conflict_a_order_not_compliance_cleared_masks_sailing_capacity_exceeded
        """
        ctx = _pending_order_against_a_nearly_full_sailing(api)

        sailing = fx.read_sailing(api, ctx["sailing_id"])
        assert sailing["booked_weight_kg"] == approx_weight(600.000)
        assert sailing["status"] == "OPEN"

        bookings = fx.rows(
            api.list_bookings(OPS_ALICE, {"export_order_id": ctx["order_a_id"]})
        )
        assert bookings == []


# ---------------------------------------------------------------------------
# Conflict B: the stale credit version outranks the restricted-party block
# ---------------------------------------------------------------------------


def _restricted_buyer_with_a_captured_credit(api) -> Json:
    ctx = fx.cleared_order(api)
    ctx = fx.captured_credit(api, ctx, lc_number="LC-2195-007")
    ctx["lc_version_at_capture"] = ctx["credit"]["version"]
    fx.data(
        api.patch_restricted_party_flag(
            ctx["buyer_id"],
            {
                "restricted_party_flag": True,
                "restricted_party_reason": "denied party match on the ultimate parent",
            },
            COMPLIANCE_CARL,
        )
    )
    return ctx


class TestConflictBStaleVersionOutranksRestrictedParty:
    def test_stale_expected_version_reports_the_concurrency_error(self, api):
        """PRD §2.11: "**Conflict B:** because state and concurrency checks
        precede compliance checks, a review request that is both stale *and* aimed
        at a restricted-party buyer reports `ERR_STALE_LC_VERSION` (412)."

        Design: Difficulty/priority_pair_validation_conflict/conflict_b_stale_lc_version_412_masks_restricted_party_blocked
        """
        ctx = _restricted_buyer_with_a_captured_credit(api)
        response = api.open_terms_review(
            ctx["lc_id"],
            {"expected_letter_of_credit_version": ctx["lc_version_at_capture"] - 1},
            REVIEWER_BOB,
        )
        validate_error(response, ApiErrorId.ERR_STALE_LC_VERSION.value)

    def test_refused_review_writes_no_row_and_leaves_the_credit_received(self, api):
        """PRD §3.4: "Opening the review creates one review row with `status`
        `DRAFTING`, `reviewer_user_id` taken from `X-User-ID`, `reviewed_lc_version`
        pinned to the credit's `version`"

        Design: Difficulty/priority_pair_validation_conflict/conflict_b_stale_lc_version_412_masks_restricted_party_blocked
        """
        ctx = _restricted_buyer_with_a_captured_credit(api)
        api.open_terms_review(
            ctx["lc_id"],
            {"expected_letter_of_credit_version": ctx["lc_version_at_capture"] - 1},
            REVIEWER_BOB,
        )

        assert (
            fx.rows(
                api.list_terms_reviews(
                    REVIEWER_BOB, {"letter_of_credit_id": ctx["lc_id"]}
                )
            )
            == []
        )
        assert fx.read_credit(api, ctx["lc_id"])["status"] == "RECEIVED"
        assert_order_dimensions(
            fx.read_order(api, ctx["order_id"]),
            fulfillment="COMPLIANCE_BLOCKED",
            settlement="UNSECURED",
        )


# ---------------------------------------------------------------------------
# Conflict C: the duty boundary outranks the superseded revision
# ---------------------------------------------------------------------------


def _self_prepared_tender_with_a_regenerated_invoice(api) -> Json:
    """Every document prepared by one coordinator, whose invoice is then revised."""
    ctx = fx.full_tender(api, credit_overrides={"lc_number": "LC-2195-008"})
    ctx = fx.lodged_presentation(api, ctx)
    ctx["invoice_revision_two"] = fx.data(
        api.regenerate_document(
            ctx["invoice_id"],
            {"reason": "invoice reissued against corrected figures"},
            OPS_ALICE,
        )
    )
    return ctx


class TestConflictCDutyBoundaryOutranksRevision:
    def test_preparer_wearing_the_reviewer_hat_reports_the_duty_breach(self, api):
        """PRD §2.8: "An examination attempted by the document's own preparer
        against a superseded revision therefore reports the duty breach, not the
        revision problem."

        Design: Difficulty/priority_pair_validation_conflict/conflict_c_segregation_of_duties_masks_document_revision_superseded
        """
        ctx = _self_prepared_tender_with_a_regenerated_invoice(api)
        response = api.examine_presentation(
            ctx["presentation_id"],
            {"findings": []},
            make_reviewer_headers(USER_IDS["ops_alice"]),
        )
        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    def test_refused_examination_leaves_the_tender_and_money_axis_alone(self, api):
        """PRD §3.7: "`examined_by_user_id` and `examination_risk_score` are
        stored on both branches."

        Design: Difficulty/priority_pair_validation_conflict/conflict_c_segregation_of_duties_masks_document_revision_superseded
        """
        ctx = _self_prepared_tender_with_a_regenerated_invoice(api)
        api.examine_presentation(
            ctx["presentation_id"],
            {"findings": []},
            make_reviewer_headers(USER_IDS["ops_alice"]),
        )

        presentation = fx.data(api.get_presentation(ctx["presentation_id"], REVIEWER_BOB))
        assert presentation["status"] == "PRESENTED"
        assert presentation["examined_by_user_id"] is None
        assert presentation["examination_risk_score"] == approx_money(0.00)
        assert presentation["negotiable_amount_usd"] == approx_money(0.00)
        assert_order_dimensions(
            fx.read_order(api, ctx["order_id"]), settlement="DOCS_PRESENTED"
        )


# ---------------------------------------------------------------------------
# Conflict D: expiry outranks the over-drawn amount
# ---------------------------------------------------------------------------


def _over_drawn_tender_on_a_credit_at_its_expiry_instant(api) -> Json:
    """A 25,000.00 invoice tendered under a 20,000.00 credit, examined at expiry."""
    ctx = fx.full_tender(
        api,
        credit_overrides={
            "lc_number": "LC-2195-009",
            "amount_usd": 20000.00,
            "tolerance_pct": 0.00,
            "expiry_date": "2026-08-20T00:00:00Z",
        },
    )
    ctx = fx.lodged_presentation(api, ctx)
    fx.set_clock(api, "2026-08-20T00:00:00Z")
    return ctx


class TestConflictDExpiryOutranksOverDrawing:
    def test_examination_at_the_exact_expiry_instant_reports_the_expiry(self, api):
        """PRD §2.11: "**Conflict D:** an examination on an expired credit whose
        invoice also over-draws reports `ERR_LC_EXPIRED`, not the priority-33
        amount error."

        Design: Difficulty/priority_pair_validation_conflict/conflict_d_lc_expired_at_exact_expiry_masks_lc_amount_exceeded
        """
        ctx = _over_drawn_tender_on_a_credit_at_its_expiry_instant(api)
        response = api.examine_presentation(
            ctx["presentation_id"], {"findings": []}, REVIEWER_BOB
        )
        validate_error(response, ApiErrorId.ERR_LC_EXPIRED.value)

    def test_zero_tolerance_bounds_and_the_tender_survive_the_refusal(self, api):
        """PRD §3.4: "`max_drawable_usd` is `amount_usd` multiplied by the
        quantity one plus `tolerance_pct` divided by 100, rounded to two decimal
        places"

        Design: Difficulty/priority_pair_validation_conflict/conflict_d_lc_expired_at_exact_expiry_masks_lc_amount_exceeded
        """
        ctx = _over_drawn_tender_on_a_credit_at_its_expiry_instant(api)
        api.examine_presentation(ctx["presentation_id"], {"findings": []}, REVIEWER_BOB)

        credit = fx.read_credit(api, ctx["lc_id"])
        assert credit["status"] == "ACCEPTED"
        assert credit["max_drawable_usd"] == approx_money(20000.00)
        assert credit["min_drawable_usd"] == approx_money(20000.00)

        presentation = fx.data(api.get_presentation(ctx["presentation_id"], REVIEWER_BOB))
        assert presentation["status"] == "PRESENTED"
        assert presentation["presented_amount_usd"] == approx_money(25000.00)
        assert presentation["negotiable_amount_usd"] == approx_money(0.00)
        assert_order_dimensions(
            fx.read_order(api, ctx["order_id"]), settlement="DOCS_PRESENTED"
        )
