"""A request refused because of a state on a neighbouring row, not on its own target."""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    COMPLIANCE_CARL,
    OPS_ALICE,
    REVIEWER_BOB,
    ApiErrorId,
    approx_weight,
    assert_order_dimensions,
    factories as f,
    fixtures as fx,
    validate_error,
)

Json = Dict[str, Any]


def _sailing_swept_to_cutoff_passed(api) -> Json:
    """A sailing whose cut-off instant the clock lands on exactly."""
    ctx = fx.cleared_order(api)
    ctx["sailing"] = fx.create_sailing(
        api,
        cutoff_at="2026-08-15T00:00:00Z",
        etd="2026-08-17T00:00:00Z",
        eta="2026-09-01T00:00:00Z",
        capacity_weight_kg=5000.000,
    )
    ctx["sailing_id"] = ctx["sailing"]["id"]
    fx.set_clock(api, "2026-08-15T00:00:00Z")
    ctx["sailing"] = fx.read_sailing(api, ctx["sailing_id"])
    ctx["attempt"] = api.create_booking(
        f.booking_payload(
            ctx["order_id"],
            ctx["sailing_id"],
            ctx["sailing"]["version"],
            booked_weight_kg=400.000,
            container_type="LCL",
        ),
        OPS_ALICE,
    )
    return ctx


class TestBookingBlockedBySweptSailingStatus:
    def test_swept_sailing_reports_its_status_not_the_cutoff_or_a_stale_version(
        self, api
    ):
        """PRD §2.11: "Booking freight requires the order's screening to be
        `CLEARED` (`ERR_ORDER_NOT_COMPLIANCE_CLEARED`) and the sailing to be
        bookable (`ERR_SAILING_NOT_OPEN`)"

        Design: Difficulty/cross_entity_state_dependency/booking_blocked_by_swept_sailing_status_not_by_the_cutoff_rule
        """
        ctx = _sailing_swept_to_cutoff_passed(api)
        error = validate_error(ctx["attempt"], ApiErrorId.ERR_SAILING_NOT_OPEN.value)

        assert error["error_id"] != ApiErrorId.ERR_SAILING_CUTOFF_PASSED.value
        assert error["error_id"] != ApiErrorId.ERR_STALE_SAILING_VERSION.value

    def test_clock_sweep_left_the_sailing_cutoff_passed_and_empty(self, api):
        """PRD §2.5: "Every vessel sailing whose `status` is `OPEN` or `FULL` moves
        to `CUTOFF_PASSED` once the new instant is at or after its `cutoff_at`, and
        then on to `DEPARTED` once the new instant is at or after its `etd`."

        Design: Difficulty/cross_entity_state_dependency/booking_blocked_by_swept_sailing_status_not_by_the_cutoff_rule
        """
        ctx = _sailing_swept_to_cutoff_passed(api)

        sailing = fx.read_sailing(api, ctx["sailing_id"])
        assert sailing["status"] == "CUTOFF_PASSED"
        assert sailing["booked_weight_kg"] == approx_weight(0.000)


# ---------------------------------------------------------------------------
# A review blocked by a designation applied after the credit was captured
# ---------------------------------------------------------------------------


def _credit_captured_then_buyer_designated(api) -> Json:
    ctx = fx.cleared_order(api)
    ctx = fx.captured_credit(api, ctx, lc_number="LC-2195-007")
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
    ctx["attempt"] = api.open_terms_review(
        ctx["lc_id"],
        {"expected_letter_of_credit_version": fx.credit_version(api, ctx["lc_id"])},
        REVIEWER_BOB,
    )
    return ctx


class TestTermsReviewBlockedByABuyerDesignation:
    def test_current_version_exposes_the_restricted_party_block(self, api):
        """PRD §2.11: "This guards seven operations: compliance submission, credit
        capture, opening a terms review, booking freight, generating a trade
        document, issuing a trade document, and lodging a presentation — otherwise
        `ERR_RESTRICTED_PARTY_BLOCKED` (409)."

        Design: Difficulty/cross_entity_state_dependency/terms_review_blocked_by_buyer_restriction_set_after_the_credit_was_captured
        """
        ctx = _credit_captured_then_buyer_designated(api)
        validate_error(ctx["attempt"], ApiErrorId.ERR_RESTRICTED_PARTY_BLOCKED.value)

    def test_blocked_review_writes_nothing_and_the_credit_stays_received(self, api):
        """PRD §3.1: "While the flag stands true, seven operations against that
        buyer's orders are refused outright with a 409: submitting an order for
        compliance, capturing a credit against it, opening a terms review on that
        credit, booking freight, generating a trade document, issuing a trade
        document, and lodging a presentation."

        Design: Difficulty/cross_entity_state_dependency/terms_review_blocked_by_buyer_restriction_set_after_the_credit_was_captured
        """
        ctx = _credit_captured_then_buyer_designated(api)

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
            fx.read_order(api, ctx["order_id"]), fulfillment="COMPLIANCE_BLOCKED"
        )
