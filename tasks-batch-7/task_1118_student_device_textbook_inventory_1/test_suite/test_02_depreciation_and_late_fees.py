"""Depreciation variants (PRD §3.1, §3.9) and late-return tier math (PRD §3.5)."""

from test_helpers import (
    intake_asset,
    list_fees,
    return_assignment_payload,
    set_clock,
    setup_active_program_with_fleet,
    setup_student_with_assignment,
    setup_retired_unit,
    validate_success,
    get_success_data,
)


class TestDepreciatedValueVariants:
    def test_linear_depreciation_formula_at_eleven_months(self, api, admin_headers):
        """PRD §3.1: "A unit's `months_in_service` is the number of whole months between the fleet's `in_service_date` and the server's current clock — elapsed days divided by 30.44, the average month length, rounded down — and it never exceeds the fleet's `useful_life_months`."
        PRD §3.1: "The `depreciated_value_cents` is then the replacement cost minus accumulated straight-line depreciation: the depreciable amount is `unit_replacement_cost_cents` minus `salvage_value_cents`, each month in service consumes an equal share of that amount (the monthly share multiplied by the months in service, rounded half up to a whole cent), and the result never falls below `salvage_value_cents`."

        in_service 2025-05-01, boot clock 2026-05-01: floor(365/30.44) = 11 months.
        depreciated = 100000 - round_half_up(11 * 90000 / 24) = 100000 - 41250 = 58750.

        Design: Difficulty/dual_variant_calc/depreciated_value_linear_vs_forced_terminal
        """
        program, fleet = setup_active_program_with_fleet(
            fleet_overrides={"useful_life_months": 24,
                             "in_service_date": "2025-05-01T00:00:00Z"}
        )
        asset = intake_asset(program["id"], fleet["id"], "BC-LIN-1", "SN-LIN-1", "C")
        asset = get_success_data(
            api.get_asset_unit(program["id"], asset["id"], admin_headers)
        )
        assert asset["months_in_service"] == 11, (
            f"Expected 11 months in service, got {asset['months_in_service']}"
        )
        assert asset["depreciated_value_cents"] == 58750, (
            f"Expected linear depreciated value 58750, "
            f"got {asset['depreciated_value_cents']}"
        )

    def test_dispose_forces_depreciated_value_to_salvage(self, api, admin_headers):
        """PRD §3.9: "Disposal and donation both require the unit's `assigned_to_student_id` to be null — a unit still on a student's books cannot leave, and the attempt meets `ERR_STILL_ASSIGNED` — and both force the `depreciated_value_cents` to the fleet's `salvage_value_cents`, appending `DISPOSE` or `DONATE` respectively."

        A retired unit (END_OF_LIFE) is disposed: the linear formula is
        overridden and depreciated_value_cents is forced to the salvage floor.

        Design: Difficulty/dual_variant_calc/depreciated_value_linear_vs_forced_terminal
        """
        program, fleet, retired = setup_retired_unit()
        assert retired["lifecycle_status"] == "END_OF_LIFE"
        disposed = validate_success(
            api.dispose_asset_unit(program["id"], retired["id"], admin_headers), 200
        )
        assert disposed["lifecycle_status"] == "DISPOSED"
        assert disposed["depreciated_value_cents"] == 10000, (
            f"Expected forced salvage 10000, got {disposed['depreciated_value_cents']}"
        )


def _return_late(api, expected_return, clock_at_return, tech_headers,
                 return_grade="A"):
    """Assignment with the given expected_return_date, returned at the given
    logical time. Returns (ctx, returned_assignment)."""
    ctx = setup_student_with_assignment(expected_return_date=expected_return)
    set_clock(clock_at_return)
    returned = validate_success(
        api.return_assignment(
            ctx["program"]["id"], ctx["student"]["id"], ctx["assignment"]["id"],
            return_assignment_payload(return_condition_grade=return_grade),
            tech_headers,
        ),
        200,
    )
    return ctx, returned


class TestLateReturnTierBoundaries:
    def test_ten_days_late_straddles_tier_boundary(self, api, tech_headers,
                                                   admin_headers):
        """PRD §3.5: "Otherwise a `LATE_RETURN` fee is created on a three-tier daily schedule whose boundaries are inclusive on the lower edge: each of the first through seventh late days costs 100 cents, each of the eighth through thirtieth costs 250 cents, and every day from the thirty-first onward costs 500 cents."

        10 days late = 7*100 + 3*250 = 1450 (NOT 10*250 — the tier-1 lower
        edge is inclusive, so days 1..7 bill at tier 1).

        Design: Difficulty/combinatorial_formula/late_return_fee_mode_c_tiered_boundary_straddle
        """
        ctx, returned = _return_late(
            api, "2026-06-01T00:00:00Z", "2026-06-11T00:00:00Z", tech_headers
        )
        assert returned["status"] == "RETURNED"
        assert returned["late_return_days"] == 10
        late_fees = [f for f in list_fees(ctx) if f["fee_type"] == "LATE_RETURN"]
        assert len(late_fees) == 1, f"Expected one LATE_RETURN fee, got {late_fees}"
        assert late_fees[0]["amount_cents"] == 1450, (
            f"Expected 1450 (7*100 + 3*250), got {late_fees[0]['amount_cents']}"
        )

    def test_eight_days_late_charges_day_eight_at_tier_two(self, api, tech_headers):
        """PRD §3.5: "Otherwise a `LATE_RETURN` fee is created on a three-tier daily schedule whose boundaries are inclusive on the lower edge: each of the first through seventh late days costs 100 cents, each of the eighth through thirtieth costs 250 cents, and every day from the thirty-first onward costs 500 cents."

        8 days late = 7*100 + 1*250 = 950: day 8 is the first tier-2 day.

        Design: Difficulty/combinatorial_formula/late_return_fee_mode_c_tiered_boundary_straddle
        """
        ctx, returned = _return_late(
            api, "2026-06-01T00:00:00Z", "2026-06-09T00:00:00Z", tech_headers
        )
        assert returned["late_return_days"] == 8
        late_fees = [f for f in list_fees(ctx) if f["fee_type"] == "LATE_RETURN"]
        assert len(late_fees) == 1
        assert late_fees[0]["amount_cents"] == 950, (
            f"Expected 950 (7*100 + 1*250), got {late_fees[0]['amount_cents']}"
        )


def test_return_on_expected_date_generates_no_late_fee(api, tech_headers):
    """PRD §3.5: "A return with zero late days generates no fee."
    PRD §3.5: "The assignment closes to `RETURNED`, `checked_in_at` is stamped from the server clock, and `late_return_days` is computed as the number of whole calendar days the check-in falls after the `expected_return_date`, never less than zero."

    Design: Corner/calculations/late_return_fee_zero_days_no_fee
    """
    ctx = setup_student_with_assignment(
        expected_return_date="2026-05-01T00:00:00Z"
    )
    returned = validate_success(
        api.return_assignment(
            ctx["program"]["id"], ctx["student"]["id"], ctx["assignment"]["id"],
            return_assignment_payload(return_condition_grade="A"), tech_headers,
        ),
        200,
    )
    assert returned["late_return_days"] == 0
    late_fees = [f for f in list_fees(ctx) if f["fee_type"] == "LATE_RETURN"]
    assert late_fees == [], f"Expected no LATE_RETURN fee, got {late_fees}"
