"""Values sitting exactly on a threshold, and the same values one unit past it."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.api_errors import ERR_ORPHAN_CRITERIA_NOT_MET
from test_helpers.assertions import (
    assert_cents,
    assert_fields,
    assert_score,
)
from test_helpers.factories import determination_decision_payload

DEEP_WELL = dict(
    spud_year=1969,
    total_depth_ft=8000,
    casing_strings=3,
    methane_scfd=310,
    groundwater_depth_ft=180,
    population_within_1000ft=3,
    surface_disturbance_acres=1.25,
)
QUIET_SHALLOW_WELL = dict(
    spud_year=1981,
    total_depth_ft=2500,
    casing_strings=2,
    methane_scfd=50,
    groundwater_depth_ft=600,
    population_within_1000ft=1,
    surface_disturbance_acres=0.5,
)


def _two_marginal_wells(api):
    """Two identical idle wells whose only difference is one thousand cubic feet of gas."""
    operator = fx.make_unbonded_operator(
        api, name="Twin Buttes Gas", region_code="NM"
    )
    at_boundary = fx.make_well(api, operator["id"], last_production_month="2024-01")
    over_boundary = fx.make_well(api, operator["id"], last_production_month="2024-01")

    fx.report_production(api, at_boundary["id"], "2024-01", oil_bbl=150, gas_mcf=180)
    fx.report_production(api, over_boundary["id"], "2024-01", oil_bbl=150, gas_mcf=181)

    det_a = fx.open_determination(
        api, at_boundary["id"], inspector_notes="de-minimis production only"
    )
    fx.submit_determination(api, det_a["id"])
    det_b = fx.open_determination(
        api, over_boundary["id"], inspector_notes="marginal production"
    )
    fx.submit_determination(api, det_b["id"])
    return {
        "operator": operator,
        "at_boundary": at_boundary,
        "over_boundary": over_boundary,
        "det_at_boundary": det_a,
        "det_over_boundary": det_b,
    }


def test_de_minimis_production_exactly_at_the_ceiling_still_confirms(api):
    """150 barrels plus 180 thousand cubic feet is exactly 180.00 and passes.

    The gas conversion contributes exactly 30.00 barrels of oil equivalent, the
    aggregate lands on the ceiling, and the inclusive comparison lets the confirmation
    through while the sibling well's figure reads 180.17.

    PRD: "the well's `idle_months` must be at least 24, its `cumulative_boe_60mo` must
    be no greater than 180.00, and its `screening_score` must be at least 40.00."

    Design: Difficulty/boundary_precision_check/de_minimis_boe_exactly_at_180_passes_and_180_17_fails
    """
    bundle = _two_marginal_wells(api)
    well = fx.read_well(api, bundle["at_boundary"]["id"])
    assert_score(well["cumulative_boe_60mo"], 180.00, "cumulative_boe_60mo")
    assert_fields(well, idle_months=31)
    assert_score(well["screening_score"], 59.90, "screening_score")

    sibling = fx.read_well(api, bundle["over_boundary"]["id"])
    assert_score(sibling["cumulative_boe_60mo"], 180.17, "sibling cumulative_boe_60mo")
    assert_fields(sibling, idle_months=31)

    confirmed = fx.decide_determination(
        api,
        bundle["det_at_boundary"]["id"],
        "CONFIRM",
        "exactly at the de-minimis boundary",
    )
    assert_fields(confirmed, status="CONFIRMED")
    assert_fields(
        fx.read_well(api, bundle["at_boundary"]["id"]),
        status="ORPHAN_CONFIRMED",
        orphan_confirmed_at="2026-08-01T00:00:00Z",
    )


def test_one_extra_thousand_cubic_feet_of_gas_defeats_the_de_minimis_test(api):
    """One more thousand cubic feet lifts the aggregate 0.17 over the ceiling and fails.

    181 divided by six is 30.1666..., summed unrounded and rounded once to 180.17, which
    is strictly greater than the ceiling; the confirmation is refused and neither the
    determination nor the well moves.

    PRD: "If any of the three fails — fewer than 24 idle months, more than 180.00
    barrels of oil equivalent across the trailing sixty months, or a screening score
    below 40.00 — the confirmation is rejected with `ERR_ORPHAN_CRITERIA_NOT_MET`
    (HTTP 422)."

    Design: Difficulty/boundary_precision_check/de_minimis_boe_exactly_at_180_passes_and_180_17_fails
    """
    bundle = _two_marginal_wells(api)
    det_id = bundle["det_over_boundary"]["id"]

    refused = api.decide_orphan_determination(
        det_id,
        determination_decision_payload("CONFIRM", "one mcf over the boundary"),
        users.REVIEWER,
    )
    validate_error(refused, ERR_ORPHAN_CRITERIA_NOT_MET)

    assert_fields(fx.read_determination(api, det_id), status="SUBMITTED")
    well = fx.read_well(api, bundle["over_boundary"]["id"])
    assert_fields(well, status="ORPHAN_CANDIDATE")
    assert_score(well["cumulative_boe_60mo"], 180.17, "cumulative_boe_60mo")
    assert well["orphan_confirmed_at"] is None, (
        "a refused confirmation must not stamp orphan_confirmed_at"
    )


def test_posting_exactly_the_requirement_keeps_an_operator_compliant(api):
    """A bond equal to the requirement to the cent is not a deficiency.

    Adding the 8000 ft well lifts the requirement from 250000 to 1250000, which is
    precisely what this operator has posted, so it stays ACTIVE.

    PRD: "The boundary is strict in both directions: posting exactly the required
    amount is compliant."

    Design: Difficulty/boundary_precision_check/bond_exactly_equal_to_requirement_is_compliant_one_cent_short_is_delinquent
    """
    operator = fx.make_operator(
        api,
        name="Equal Bond Operating",
        region_code="TX",
        bond_amount_cents=1250000,
    )
    fx.make_well(api, operator["id"], **QUIET_SHALLOW_WELL)

    before = fx.read_operator(api, operator["id"])
    assert_fields(before, status="ACTIVE", active_well_count=1)
    assert_cents(before["required_bond_cents"], 250000, "required_bond_cents before")

    fx.make_well(api, operator["id"], **DEEP_WELL)

    after = fx.read_operator(api, operator["id"])
    assert_cents(after["required_bond_cents"], 1250000, "required_bond_cents after")
    assert_cents(after["bond_amount_cents"], 1250000, "bond_amount_cents")
    assert_fields(after, status="ACTIVE", active_well_count=2)


def test_one_cent_short_of_the_requirement_makes_an_operator_delinquent(api):
    """The same inventory with one cent less posted is a deficiency.

    1249999 against a 1250000 requirement is strictly less, so the operator flips to
    DELINQUENT on exactly the same well addition that left its neighbour compliant.

    PRD: "An operator is deficient when its `bond_amount_cents` is strictly less than
    its `required_bond_cents`."

    Design: Difficulty/boundary_precision_check/bond_exactly_equal_to_requirement_is_compliant_one_cent_short_is_delinquent
    """
    operator = fx.make_operator(
        api,
        name="One Cent Short Operating",
        region_code="TX",
        bond_amount_cents=1249999,
    )
    fx.make_well(api, operator["id"], **QUIET_SHALLOW_WELL)

    before = fx.read_operator(api, operator["id"])
    assert_fields(before, status="ACTIVE", active_well_count=1)
    assert_cents(before["required_bond_cents"], 250000, "required_bond_cents before")

    fx.make_well(api, operator["id"], **DEEP_WELL)

    after = fx.read_operator(api, operator["id"])
    assert_cents(after["required_bond_cents"], 1250000, "required_bond_cents after")
    assert_cents(after["bond_amount_cents"], 1249999, "bond_amount_cents")
    assert_fields(after, status="DELINQUENT", active_well_count=2)
