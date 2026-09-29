"""Two inclusive limits where the edge itself must pass and the next
representable step must fail: the moisture gradient ceiling in tenths of a
percentage point, and the width tolerance in thousandths of an inch."""

import pytest

from test_helpers import (
    complete_milling_payload,
    record_stress_test_payload,
    setup_conditioning_charge,
    setup_planned_lot,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    OPERATOR,
    SUPERVISOR,
    refetch_lot,
)

# A single receipt of 4000 accepted board feet at 45.0 percent: the charge dries
# from a weighted moisture exactly on the schedule's design figure.
SINGLE_RECEIPT = (
    {
        "received_board_feet": 4200,
        "accepted_board_feet": 4000,
        "moisture_pct_at_receipt": 45.0,
        "receipt_grade": "FAS",
    },
)


class TestMoistureGradientCeiling:
    """The gradient check is inclusive at the species maximum, compared at one
    decimal place."""

    def test_gradient_exactly_at_the_species_ceiling_releases_the_charge(self, api):
        """PRD 3.5: "The charge is released when the gradient is at most the
        species' `max_moisture_gradient_pp` **and** the absolute difference between
        `average_moisture_pct` and the species' `target_moisture_pct` is at most 1.0
        percentage point; otherwise the charge goes back for redry."

        PRD 3.5: "With a species capped at a 2.0-point gradient and targeting 7.0
        percent: a shell of 6.4 against a core of 8.2 gives a gradient of 1.8 and an
        average of 7.3, and releases; a shell of 6.0 against a core of 8.0 gives a
        gradient of exactly 2.0, which is still within the cap and releases; a shell
        of 5.9 against a core of 8.0 gives 2.1 and does not."

        PRD 3.1: "From the density class the server derives
        `green_to_dry_shrink_pct`, the board-foot shrink from green to kiln-dry: 7.5
        percent for `DENSE`, 6.0 percent for `MEDIUM` and 5.0 percent for `SOFT`."

        Design: Difficulty/boundary_precision_check/moisture_gradient_exactly_at_ceiling_releases_charge
        """
        ctx = setup_conditioning_charge(api, receipts=[dict(r) for r in SINGLE_RECEIPT])

        charge = validate_success(
            api.record_stress_test(
                ctx["charge"]["id"], record_stress_test_payload(6.0, 8.0), OPERATOR
            ),
            expected_status=200,
        )

        assert charge["status"] == "RELEASED"
        assert charge["moisture_gradient_pp"] == pytest.approx(2.0, abs=0.01)
        assert charge["average_moisture_pct"] == pytest.approx(7.0, abs=0.01)
        assert charge["dry_bf_out"] == pytest.approx(3700.00, abs=0.01)
        assert charge["remaining_dry_bf"] == pytest.approx(3700.00, abs=0.01)
        assert charge["redry_count"] == 0

    def test_the_next_tenth_above_the_ceiling_sends_the_same_charge_back(self, api):
        """PRD 3.5: "Both readings are stored, and two derived figures follow:
        `moisture_gradient_pp` is the absolute difference between the core and shell
        readings, rounded half up to one decimal place, and `average_moisture_pct` is
        the mean of the two readings, likewise rounded half up to one decimal place."

        PRD 3.5: "On the redry branch the charge moves from `CONDITIONING` to
        `REDRY`."

        Design: Difficulty/boundary_precision_check/moisture_gradient_exactly_at_ceiling_releases_charge
        """
        ctx = setup_conditioning_charge(api, receipts=[dict(r) for r in SINGLE_RECEIPT])

        charge = validate_success(
            api.record_stress_test(
                ctx["charge"]["id"], record_stress_test_payload(5.9, 8.0), OPERATOR
            ),
            expected_status=200,
        )

        assert charge["status"] == "REDRY"
        assert charge["moisture_gradient_pp"] == pytest.approx(2.1, abs=0.01)
        assert charge["redry_count"] == 1
        assert charge["dry_bf_out"] is None


class TestProfileToleranceLimit:
    """A planned 3.188-inch face tolerates a milled 3.194 and refuses a 3.195."""

    def test_a_width_exactly_at_the_tolerance_is_accepted_with_its_mass_balance(
        self, api
    ):
        """PRD 3.6: "The first check is dimensional: the absolute difference between
        `actual_milled_width_in` and `planned_finished_width_in` may be at most 0.006
        inch, or the report is refused with `ERR_PROFILE_TOLERANCE_EXCEEDED`."

        PRD 3.6: "Against a planned 3.188 inches, an actual 3.190 sits 0.002 inside
        tolerance and passes, an actual 3.194 sits exactly at 0.006 and still passes,
        and an actual 3.195 exceeds it and fails."

        PRD 3.6: "A 3.250-inch nominal face on a species with a coefficient of 0.145
        dried to 7.3 percent moves 0.0009 inch and plans to 3.188 inches; the same
        face at 7.0 percent moves 0.0024 inch and plans to 3.190 inches."

        PRD 3.6: "A lot drawing 6000 board feet that reports 4680 net, 180 in
        shorts, 1.20 tons of sawdust and 0.80 tons of shavings yields 570.00 residue
        board feet and 570.00 waste board feet against a ceiling of 720.00, and is
        accepted."

        Design: Difficulty/boundary_precision_check/profile_tolerance_exactly_at_limit_passes_next_thousandth_fails
        """
        ctx = setup_planned_lot(api)
        assert ctx["lot"]["dimensional_growth_allowance_in"] == pytest.approx(
            0.0009, abs=0.00001
        )
        assert ctx["lot"]["planned_finished_width_in"] == pytest.approx(3.188, abs=0.0001)

        lot = validate_success(
            api.complete_milling(
                ctx["lot"]["id"],
                complete_milling_payload(actual_milled_width_in=3.194),
                SUPERVISOR,
            ),
            expected_status=200,
        )

        assert lot["status"] == "MILLED"
        assert lot["actual_milled_width_in"] == pytest.approx(3.194, abs=0.0001)
        assert lot["residue_bf"] == pytest.approx(570.00, abs=0.01)
        assert lot["waste_bf"] == pytest.approx(570.00, abs=0.01)
        assert lot["provisional_yield_pct"] == pytest.approx(78.00, abs=0.01)

        _rows, meta = validate_paginated(
            api.list_byproduct_batches(ADMIN, params={"flooring_lot_id": ctx["lot"]["id"]})
        )
        assert meta["total_count"] == 3

    def test_one_thousandth_beyond_the_tolerance_is_refused_and_opens_no_ledger(
        self, api
    ):
        """PRD 3.6: "The result is rounded half up to three decimal places, and the
        two roundings happen in that order: movement first to four places, then the
        planned width to three."

        PRD 3.6: "Milling completion also opens the byproduct ledger. Three batches
        are created against the lot, one per stream, each with its `byproduct_type`
        set to `SAWDUST`, `SHAVINGS` and `SHORTS` respectively, `sold_tons` at 0, and
        `available_tons` fixed once from the milling report: the sawdust batch takes
        `sawdust_tons`, the shavings batch takes `shavings_tons`, and the shorts
        batch takes `shorts_bf` divided by the same 285 board feet per ton, rounded
        half up to two decimal places."

        Design: Difficulty/boundary_precision_check/profile_tolerance_exactly_at_limit_passes_next_thousandth_fails
        """
        ctx = setup_planned_lot(api, input_dry_bf=2900)
        assert ctx["lot"]["planned_finished_width_in"] == pytest.approx(3.188, abs=0.0001)

        response = api.complete_milling(
            ctx["lot"]["id"],
            complete_milling_payload(
                actual_milled_width_in=3.195,
                net_flooring_bf=2500,
                shorts_bf=100,
                sawdust_tons=0.80,
                shavings_tons=0.20,
            ),
            SUPERVISOR,
        )
        validate_error(response, "ERR_PROFILE_TOLERANCE_EXCEEDED", expected_status=422)

        lot = refetch_lot(api, ctx["lot"]["id"])
        assert lot["status"] == "PLANNED"
        assert lot["net_flooring_bf"] is None

        _rows, meta = validate_paginated(
            api.list_byproduct_batches(ADMIN, params={"flooring_lot_id": ctx["lot"]["id"]})
        )
        assert meta["total_count"] == 0
