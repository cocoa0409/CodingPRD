"""The grant-match read: two variants, two included sets, two rounding orders."""

import pytest

from test_helpers import (
    TEST_USERS,
    assert_money_usd,
    certify_hours,
    check_in,
    check_out,
    complete_party,
    confirm_party,
    register_volunteer_on_party,
    set_clock,
    setup_approved_plan,
    setup_briefed_party,
    setup_completed_party_with_hours,
    start_party,
    validate_success,
    verify_hours,
)

COORD = TEST_USERS["coordinator_headers"]
GRANTS = TEST_USERS["grants_admin_headers"]


def _two_certified_shifts():
    """A certified sawyer and a general volunteer, each credited 6.50 hours."""
    world = setup_briefed_party()
    shift_saw = register_volunteer_on_party(
        world["party_id"],
        world["lead_id"],
        world["saw_id"],
        expected_version=world["party_version_after_briefing"],
        role_on_crew="SAWYER",
    )
    shift_gen = register_volunteer_on_party(
        world["party_id"], world["lead_id"], world["gen_id"], role_on_crew="CREW_MEMBER"
    )
    confirm_party(world["party_id"], world["lead_id"])
    set_clock("2026-09-05T09:00:00.000Z")
    start_party(world["party_id"], world["lead_id"])
    check_in(shift_saw["id"], world["lead_id"])
    check_in(shift_gen["id"], world["lead_id"])

    set_clock("2026-09-05T15:20:00.000Z")
    world["shift_saw"] = check_out(shift_saw["id"], world["lead_id"])
    set_clock("2026-09-05T15:22:00.000Z")
    world["shift_gen"] = check_out(shift_gen["id"], world["lead_id"])
    complete_party(world["party_id"], world["lead_id"])

    verify_hours(shift_saw["id"])
    verify_hours(shift_gen["id"])
    certify_hours(shift_saw["id"])
    certify_hours(shift_gen["id"])
    world["shift_saw_id"] = shift_saw["id"]
    world["shift_gen_id"] = shift_gen["id"]
    return world


def test_certified_variant_prices_each_shift_at_its_own_snapshot_rate(api):
    """PRD 3.7: "Under the `CERTIFIED` variant — the figure actually submitted on the grant match report — the included set narrows to shifts whose status is `HOURS_CERTIFIED` only, but each shift is valued at its own `skill_class_snapshot` rate: 28.54 dollars per hour for `GENERAL`, 41.20 for `SKILLED_TRAIL`, 63.75 for `CERTIFIED_SAWYER` and 89.00 for `PROFESSIONAL`."
    PRD 3.7: "Here the rounding order is inverted: each shift's `credited_hours` is multiplied by that shift's rate and rounded half up to two decimal places **first**, and those per-shift dollar figures are then summed to give `labor_match_usd`."
    PRD 3.7: "The `average_rate_usd` is 0.00 when `total_credited_hours` is 0, and otherwise `labor_match_usd` divided by `total_credited_hours`, rounded half up to two decimal places."

    Design: Difficulty/dual_variant_calc/grant_match_provisional_vs_certified_diverges
    """
    world = _two_certified_shifts()
    assert float(world["shift_saw"]["credited_hours"]) == 6.50
    assert world["shift_saw"]["skill_class_snapshot"] == "CERTIFIED_SAWYER"
    assert float(world["shift_gen"]["credited_hours"]) == 6.50
    assert world["shift_gen"]["skill_class_snapshot"] == "GENERAL"

    figures = validate_success(
        api.get_grant_match(world["plan_id"], GRANTS, params={"variant": "CERTIFIED"})
    )
    assert figures["included_shift_count"] == 2
    assert float(figures["total_credited_hours"]) == 13.00
    assert float(figures["labor_match_usd"]) == pytest.approx(599.89, abs=0.001)
    assert float(figures["grant_match_total_usd"]) == pytest.approx(599.89, abs=0.001)
    assert float(figures["average_rate_usd"]) == pytest.approx(46.15, abs=0.001)
    assert_money_usd(figures["labor_match_usd"], "labor_match_usd")


def test_provisional_variant_prices_every_hour_at_the_flat_general_rate(api):
    """PRD 3.7: "Every one of those hours is valued at the flat general rate of 28.54 US dollars regardless of who worked them: `labor_match_usd` is the total hours multiplied by 28.54 and rounded half up to two decimal places — summed first, multiplied once, rounded once."
    PRD 3.7: "Delivered materials are excluded entirely, so `material_match_usd` is 0.00."
    PRD 3.7: "Because the two variants draw on different shift sets and round in different orders, the same underlying work will produce a different `labor_match_usd`, a different hour total and a different `average_rate_usd` under each."

    Design: Difficulty/dual_variant_calc/grant_match_provisional_vs_certified_diverges
    """
    world = _two_certified_shifts()

    provisional = validate_success(
        api.get_grant_match(world["plan_id"], GRANTS, params={"variant": "PROVISIONAL"})
    )
    certified = validate_success(
        api.get_grant_match(world["plan_id"], GRANTS, params={"variant": "CERTIFIED"})
    )

    assert provisional["included_shift_count"] == 2
    assert float(provisional["total_credited_hours"]) == 13.00
    assert float(provisional["labor_match_usd"]) == pytest.approx(371.02, abs=0.001)
    assert float(provisional["material_match_usd"]) == pytest.approx(0.00, abs=0.001)
    assert float(provisional["grant_match_total_usd"]) == pytest.approx(371.02, abs=0.001)
    assert float(provisional["average_rate_usd"]) == pytest.approx(28.54, abs=0.001)
    assert float(provisional["labor_match_usd"]) != float(certified["labor_match_usd"])


def test_certified_grant_match_over_an_empty_shift_set_returns_zeroes(api):
    """PRD 3.7: "An empty included set yields `total_credited_hours` 0, `labor_match_usd` 0.00, `average_rate_usd` 0.00, and a `grant_match_total_usd` equal to `material_match_usd` — which is 0.00 under `PROVISIONAL`."
    PRD 3.7: "The response reports the `variant` used, the `included_shift_count`, the `total_credited_hours`, the `labor_match_usd`, the `material_match_usd`, the `grant_match_total_usd` and the `average_rate_usd`."
    PRD 3.7: "This variant also counts delivered materials as match: `material_match_usd` is the sum of `total_cents` over the plan's material orders in `DELIVERED`, divided by 100 and rounded half up to two decimal places."

    Design: Difficulty/boundary_precision_check/grant_match_certified_variant_on_empty_shift_set_returns_zero
    """
    world = setup_approved_plan()

    figures = validate_success(
        api.get_grant_match(world["plan_id"], GRANTS, params={"variant": "CERTIFIED"})
    )
    assert figures["included_shift_count"] == 0
    assert float(figures["total_credited_hours"]) == 0
    assert float(figures["labor_match_usd"]) == pytest.approx(0.00, abs=0.001)
    assert float(figures["material_match_usd"]) == pytest.approx(0.00, abs=0.001)
    assert float(figures["grant_match_total_usd"]) == pytest.approx(0.00, abs=0.001)
    assert float(figures["average_rate_usd"]) == pytest.approx(0.00, abs=0.001)


def test_provisional_grant_match_over_an_empty_shift_set_returns_zeroes(api):
    """PRD 3.7: "An empty included set yields `total_credited_hours` 0, `labor_match_usd` 0.00, `average_rate_usd` 0.00, and a `grant_match_total_usd` equal to `material_match_usd` — which is 0.00 under `PROVISIONAL`."
    PRD 3.7: "The `average_rate_usd` is 0.00 when `total_credited_hours` is 0, and otherwise `labor_match_usd` divided by `total_credited_hours`, rounded half up to two decimal places."

    Design: Difficulty/boundary_precision_check/grant_match_certified_variant_on_empty_shift_set_returns_zero
    """
    world = setup_approved_plan()

    figures = validate_success(
        api.get_grant_match(world["plan_id"], GRANTS, params={"variant": "PROVISIONAL"})
    )
    assert figures["included_shift_count"] == 0
    assert float(figures["grant_match_total_usd"]) == pytest.approx(0.00, abs=0.001)
    assert float(figures["average_rate_usd"]) == pytest.approx(0.00, abs=0.001)


def test_a_merely_checked_out_shift_is_absent_from_the_certified_included_set(api):
    """PRD 3.7: "Under the `PROVISIONAL` variant — the figure a crew quotes to a funder before the audit closes — the included set is every shift under the plan's parties whose status is `CHECKED_OUT`, `HOURS_DISPUTED`, `HOURS_VERIFIED` or `HOURS_CERTIFIED`."
    PRD 3.7: "Under the `CERTIFIED` variant — the figure actually submitted on the grant match report — the included set narrows to shifts whose status is `HOURS_CERTIFIED` only, but each shift is valued at its own `skill_class_snapshot` rate: 28.54 dollars per hour for `GENERAL`, 41.20 for `SKILLED_TRAIL`, 63.75 for `CERTIFIED_SAWYER` and 89.00 for `PROFESSIONAL`."

    Design: Corner/calculations/grant_match_input_set_excludes_uncertified_shift_from_certified_variant
    """
    world = setup_completed_party_with_hours()
    assert float(world["shift_saw"]["credited_hours"]) == 6.50
    assert world["shift_saw"]["status"] == "CHECKED_OUT"

    provisional = validate_success(
        api.get_grant_match(world["plan_id"], GRANTS, params={"variant": "PROVISIONAL"})
    )
    assert provisional["included_shift_count"] == 1
    assert float(provisional["total_credited_hours"]) == 6.50
    assert float(provisional["labor_match_usd"]) == pytest.approx(185.51, abs=0.001)

    certified = validate_success(
        api.get_grant_match(world["plan_id"], GRANTS, params={"variant": "CERTIFIED"})
    )
    assert certified["included_shift_count"] == 0
    assert float(certified["total_credited_hours"]) == 0
    assert float(certified["labor_match_usd"]) == pytest.approx(0.00, abs=0.001)
