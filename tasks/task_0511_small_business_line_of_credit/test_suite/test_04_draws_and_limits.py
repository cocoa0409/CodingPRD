"""Draws against the line: limit boundary precision, the line-not-drawable cross-entity guard,
computed draw fee, input validation, and immediate balance consistency.

Covers difficulty instances (boundary_precision_check, cross_entity_state_dependency) and
corner instances (entities, consistency_model).
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    create_active_credit_line,
    take_draw,
    create_draw_payload,
    get_line,
    SV1,
    CO1,
)


class TestDrawLimitBoundary:
    def test_draw_at_exact_available_credit_succeeds(self, api):
        """A draw of principal exactly equal to available credit is allowed.

        PRD §3.4: "A principal exactly equal to available credit is allowed; a principal that
        would push outstanding principal above the credit limit is rejected with
        ERR_LIMIT_EXCEEDED."

        Design: Difficulty/boundary_precision_check/draw_at_exact_available_credit_boundary_succeeds
        """
        _, _, _, line = create_active_credit_line(cadence="DAILY")
        assert line["available_credit_cents"] == 1_000_000
        draw = take_draw(line["id"], 1_000_000)
        assert draw["status"] == "OUTSTANDING"
        assert draw["principal_cents"] == 1_000_000
        line_after = get_line(line["id"])
        assert line_after["available_credit_cents"] == 0

    def test_draw_one_cent_over_available_credit_rejected(self, api):
        """A draw exceeding available credit by one cent is rejected with ERR_LIMIT_EXCEEDED.

        PRD §3.4: "a principal that would push outstanding principal above the credit limit is
        rejected with ERR_LIMIT_EXCEEDED."

        Design: Difficulty/boundary_precision_check/draw_at_exact_available_credit_boundary_succeeds
        """
        _, _, _, line = create_active_credit_line(cadence="DAILY")
        res = api.create_draw(line["id"], create_draw_payload(1_000_001), SV1)
        validate_error(res, "ERR_LIMIT_EXCEEDED")
        line_after = get_line(line["id"])
        assert line_after["outstanding_principal_cents"] == 0


class TestLineNotDrawable:
    def test_draw_on_frozen_line_rejected(self, api):
        """A draw on a FROZEN line is rejected with ERR_LINE_NOT_DRAWABLE.

        PRD §3.4: "the parent line must be ACTIVE; a draw on a line in any other status
        (FROZEN, DELINQUENT, DEFAULTED, CHARGED_OFF, or CLOSED) is rejected with
        ERR_LINE_NOT_DRAWABLE."

        Design: Difficulty/cross_entity_state_dependency/draw_requires_credit_line_active
        """
        _, _, _, line = create_active_credit_line(cadence="DAILY")
        validate_success(api.freeze_credit_line(line["id"], SV1), 200)
        res = api.create_draw(line["id"], create_draw_payload(100_000), SV1)
        validate_error(res, "ERR_LINE_NOT_DRAWABLE")
        line_after = get_line(line["id"])
        assert line_after["outstanding_principal_cents"] == 0


class TestDrawComputedFeeAndValidation:
    def test_draw_fee_computed_on_create(self, api):
        """Draw fee is round(principal * fee_factor_bps / 10000); not a client input.

        PRD §3.4: "the principal multiplied by the line's fee_factor_bps, divided by 10000 (the
        basis-point denominator), with the result rounded half up to a whole cent in a single
        multiply-then-round step."

        Design: Corner/entities/draw_fee_computed_on_create_ignores_client_value
        """
        _, _, _, line = create_active_credit_line(cadence="DAILY")
        assert line["fee_factor_bps"] == 800  # TIER_A
        draw = take_draw(line["id"], 300_000)
        assert draw["fee_cents"] == 24000
        assert draw["principal_repaid_cents"] == 0

    def test_draw_principal_zero_rejected(self, api):
        """A draw with principal_cents == 0 violates the >0 constraint.

        PRD §3.4: "the principal_cents to advance, which must be strictly greater than zero."

        Design: Corner/entities/draw_principal_zero_returns_invalid_request
        """
        _, _, _, line = create_active_credit_line(cadence="DAILY")
        res = api.create_draw(line["id"], create_draw_payload(0), SV1)
        validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


class TestImmediateConsistency:
    def test_draw_updates_outstanding_immediately(self, api):
        """A draw is immediately reflected on the line read in the same request cycle.

        PRD §2.5: "Whenever a Draw is created, repaid, or written off, the parent CreditLine's
        outstanding figures are recomputed"
        PRD §3.4: "recomputes the parent line's outstanding figures and available credit"

        Design: Corner/consistency_model/draw_updates_outstanding_in_same_response
        """
        _, _, _, line = create_active_credit_line(cadence="DAILY")
        take_draw(line["id"], 300_000)  # TIER_A fee 24000
        line_after = validate_success(api.get_credit_line(line["id"], SV1), 200)
        assert line_after["outstanding_principal_cents"] == 300_000
        assert line_after["available_credit_cents"] == 700_000
        assert line_after["outstanding_fee_cents"] == 24000
