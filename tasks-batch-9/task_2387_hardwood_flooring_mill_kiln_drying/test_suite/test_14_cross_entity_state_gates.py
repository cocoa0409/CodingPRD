"""Operations whose outcome is decided by the state of a different entity: a
chamber out of service blocks a ready charge, and a restricted product line
blocks a held prefinish run."""

import pytest

from test_helpers import (
    adjudicate_claim_payload,
    fund_warranty_payload,
    setup_charge_with_receipts,
    setup_claim_with_scheduled_prefinish_run,
    start_maintenance_payload,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    OPERATOR,
    SCHEDULER,
    refetch_charge,
    refetch_chamber,
    refetch_prefinish_run,
    refetch_receipt,
)
from test_helpers.test_users import (
    CLAIM_ADJUDICATOR_USER_ID,
    make_warranty_adjudicator_headers,
)

SINGLE_RECEIPT = (
    {
        "received_board_feet": 6000,
        "accepted_board_feet": 5800,
        "moisture_pct_at_receipt": 45.0,
        "receipt_grade": "FAS",
    },
)


class TestChargeLoadGatedByChamberState:
    """The charge is ready in every respect; only the chamber decides."""

    def _charge_with_chamber_out_of_service(self, api):
        ctx = setup_charge_with_receipts(
            api, receipts=[dict(r) for r in SINGLE_RECEIPT]
        )
        validate_success(
            api.start_chamber_maintenance(
                ctx["chamber"]["id"],
                start_maintenance_payload(maintenance_note="Fan bearing replacement"),
                OPERATOR,
            ),
            expected_status=200,
        )
        return ctx

    def test_a_chamber_in_maintenance_refuses_a_load_and_changes_nothing(self, api):
        """PRD 3.4: "The chamber must be `AVAILABLE` and must have no other charge
        on it in `LOADED`, `DRYING`, `CONDITIONING` or `REDRY` status, or the load is
        refused with `ERR_CHAMBER_STATE_INVALID`."

        PRD 3.1: "A `KilnOperator` or `MillAdmin` may take an `AVAILABLE` chamber to
        `MAINTENANCE`, recording the supplied `maintenance_note`, and later bring it
        from `MAINTENANCE` back to `AVAILABLE`, clearing that note."

        Design: Difficulty/cross_entity_state_dependency/charge_load_blocked_by_chamber_in_maintenance
        """
        ctx = self._charge_with_chamber_out_of_service(api)

        response = api.load_charge(ctx["charge"]["id"], OPERATOR)
        validate_error(response, "ERR_CHAMBER_STATE_INVALID", expected_status=409)

        charge = refetch_charge(api, ctx["charge"]["id"])
        assert charge["status"] == "SCHEDULED"
        assert charge["charged_green_bf"] == pytest.approx(5800, abs=0.01)
        assert refetch_receipt(api, ctx["receipts"][0]["id"])["status"] == "ALLOCATED"

    def test_returning_the_chamber_to_service_lets_the_same_load_through(self, api):
        """PRD 3.1: "A chamber that is `OCCUPIED` cannot be taken out of service,
        and a chamber that is not in `MAINTENANCE` cannot be returned from it; both
        are rejected with `ERR_CHAMBER_STATE_INVALID`."

        PRD 3.4: "A successful load has two cascades. The chamber moves from
        `AVAILABLE` to `OCCUPIED`, and every receipt allocated to the charge moves
        from `ALLOCATED` to `CONSUMED`, freezing its `accepted_board_feet` and its
        `kiln_charge_id` against any further allocation change — a consumed receipt
        can no longer be deallocated."

        Design: Difficulty/cross_entity_state_dependency/charge_load_blocked_by_chamber_in_maintenance
        """
        ctx = self._charge_with_chamber_out_of_service(api)

        chamber = validate_success(
            api.complete_chamber_maintenance(ctx["chamber"]["id"], OPERATOR),
            expected_status=200,
        )
        assert chamber["status"] == "AVAILABLE"
        assert chamber["maintenance_note"] is None

        charge = validate_success(
            api.load_charge(ctx["charge"]["id"], OPERATOR), expected_status=200
        )
        assert charge["status"] == "LOADED"
        assert charge["charged_green_bf"] == pytest.approx(5800, abs=0.01)

        assert refetch_chamber(api, ctx["chamber"]["id"])["status"] == "OCCUPIED"
        assert refetch_receipt(api, ctx["receipts"][0]["id"])["status"] == "CONSUMED"


class TestHoldReleaseGatedByProductLinePosture:
    """The run is `HELD` and stays that way until the line's derived posture says
    otherwise."""

    def _held_run_on_restricted_line(self, api):
        ctx = setup_claim_with_scheduled_prefinish_run(api)
        validate_success(
            api.adjudicate_claim(
                ctx["claim"]["id"],
                adjudicate_claim_payload(),
                make_warranty_adjudicator_headers(CLAIM_ADJUDICATOR_USER_ID),
            ),
            expected_status=200,
        )
        return ctx

    def test_a_restricted_line_refuses_the_hold_release(self, api):
        """PRD 3.8: "Releasing a hold moves the run from `HELD` back to `SCHEDULED`
        and clears `hold_reason`, and requires the product line's posture to be
        `OPEN` at that moment, or the release is refused with
        `ERR_PRODUCT_LINE_POSTURE_BLOCKED`."

        PRD 3.9: "The `posture` is then `FROZEN` whenever `freeze_override` is true,
        regardless of money; otherwise it is `RESTRICTED` when
        `warranty_balance_cents` is below the restriction floor of 500000 cents; and
        otherwise it is `OPEN`."

        Design: Difficulty/cross_entity_state_dependency/prefinish_release_hold_blocked_by_restricted_product_line
        """
        ctx = self._held_run_on_restricted_line(api)
        assert refetch_prefinish_run(api, ctx["prefinish_run"]["id"])["status"] == "HELD"

        response = api.release_prefinish_hold(ctx["prefinish_run"]["id"], SCHEDULER)
        validate_error(
            response, "ERR_PRODUCT_LINE_POSTURE_BLOCKED", expected_status=409
        )

        assert refetch_prefinish_run(api, ctx["prefinish_run"]["id"])["status"] == "HELD"

    def test_funding_the_reserve_reopens_the_line_but_not_the_run_by_itself(self, api):
        """PRD 3.9: "A `MillAdmin` funds a reserve by supplying an `amount_cents` to
        add, which increases both `warranty_funded_total_cents` and
        `warranty_balance_cents` before the posture is recomputed — the path by which
        a `RESTRICTED` line returns to `OPEN`."

        PRD 3.8: "Held runs do not resume by themselves: even after the line's
        posture returns to `OPEN`, a held run stays `HELD` until someone explicitly
        releases it."

        Design: Difficulty/cross_entity_state_dependency/prefinish_release_hold_blocked_by_restricted_product_line
        """
        ctx = self._held_run_on_restricted_line(api)

        line = validate_success(
            api.fund_warranty(
                ctx["product_line"]["id"], fund_warranty_payload(100000), ADMIN
            ),
            expected_status=200,
        )
        assert line["warranty_funded_total_cents"] == 700000
        assert line["warranty_balance_cents"] == 548526
        assert line["warranty_committed_cents"] == 151474
        assert line["posture"] == "OPEN"

        assert refetch_prefinish_run(api, ctx["prefinish_run"]["id"])["status"] == "HELD"

        run = validate_success(
            api.release_prefinish_hold(ctx["prefinish_run"]["id"], SCHEDULER),
            expected_status=200,
        )
        assert run["status"] == "SCHEDULED"
        assert run["hold_reason"] is None
