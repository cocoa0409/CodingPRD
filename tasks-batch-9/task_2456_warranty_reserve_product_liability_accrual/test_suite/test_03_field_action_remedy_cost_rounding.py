"""The pinned rounding order of the field-action remedy cost model.

PRD §3.5: "The order is pinned and observable: the take-rate weighting is rounded
to whole cents **per unit first**, and only then multiplied up by the unit count."
"""

from test_helpers import (
    ENGINEER_HEADERS,
    create_family,
    create_field_action,
    create_remedy_option,
    select_remedy,
    success_data,
)


def _build_world(api):
    family = create_family(
        api,
        family_code="FAM-K",
        name="Compact Chest Freezer",
        launch_date="2024-03-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=18000,
        reserve_cap_cents=400000000,
    )
    action = create_field_action(
        api,
        family["id"],
        action_code="FA-K-01",
        action_type="SERVICE_CAMPAIGN",
        affected_build_start_date="2025-01-01",
        affected_build_end_date="2025-03-31",
        affected_unit_count=12000,
        regulatory_notice_filed=False,
    )
    option = create_remedy_option(
        api,
        action["id"],
        option_code="OPT-PERM",
        remedy_class="PERMANENT_REPAIR",
        parts_cost_cents=4200,
        labor_hours_centi=150,
        admin_cost_cents=800,
        expected_take_rate_bps=6500,
        is_engineering_approved=True,
    )
    return {"family": family, "action": action, "option": option}


def _stored_option(api, field_action_id, option_id):
    rows = success_data(api.list_remedy_options(ENGINEER_HEADERS, field_action_id))
    return next(row for row in rows if row["id"] == option_id)


def test_remedy_option_rounds_the_take_rate_weighting_into_whole_cents_per_unit(api):
    """The stored per-unit figure is a rounded, not exact, weighted cost.

    PRD §3.5: "Convert labour first: multiply `labor_hours_centi` by the standard
    field labour rate of 9500 cents per hour — ninety-five dollars an hour — divide
    by 100 to undo the hundredths-of-an-hour scaling, and round to the nearest
    integer to obtain per-unit labour cost in cents. Add `parts_cost_cents`, that
    per-unit labour cost, and `admin_cost_cents` to obtain the per-unit gross cost
    of remedying one unit. Then weight for take-up: multiply the per-unit gross
    cost by `expected_take_rate_bps`, divide by 10000, and round to the nearest
    integer; that figure is stored on the option as `per_unit_expected_cents`."
    Labour is 14250 cents, gross is 19250 cents, and the 6500-bps weighting lands
    exactly halfway at 12512.5, which PRD §2.6 rounds "away from zero" to 12513.

    Design: Difficulty/combinatorial_formula/field_action_accrual_rounds_per_unit_before_multiplying_by_population
    """
    world = _build_world(api)

    select_remedy(
        api,
        world["action"]["id"],
        remedy_option_id=world["option"]["id"],
        expected_field_action_version=1,
    )
    stored = _stored_option(api, world["action"]["id"], world["option"]["id"])

    assert stored["per_unit_expected_cents"] == 12513


def test_specific_accrual_multiplies_the_already_rounded_per_unit_figure(api):
    """Rounding per unit first yields 150156000, not 150150000.

    PRD §3.5: "the action's `specific_accrual_cents` is that stored,
    already-rounded `per_unit_expected_cents` multiplied by the action's
    `affected_unit_count`." PRD §3.5 also rules out the other order: "Multiplying
    the unrounded per-unit gross by the unit count and by the take rate and
    rounding once at the end is wrong, and yields a different total whenever the
    product of the per-unit gross and the take rate is not an exact multiple of
    10000." Here 12513 times 12000 units is 150156000 cents, while the rejected
    order would give 150150000.

    Design: Difficulty/combinatorial_formula/field_action_accrual_rounds_per_unit_before_multiplying_by_population
    """
    world = _build_world(api)

    selected = select_remedy(
        api,
        world["action"]["id"],
        remedy_option_id=world["option"]["id"],
        expected_field_action_version=1,
    )

    assert selected["specific_accrual_cents"] == 150156000
    assert selected["specific_accrual_cents"] != 150150000


def test_selecting_a_remedy_advances_only_the_field_action_version(api):
    """Selection is a DRAFT self-loop that leaves execution untouched.

    PRD §3.5: "A successful selection writes `selected_remedy_option_id`,
    recomputes the selected option's `per_unit_expected_cents` and the action's
    `specific_accrual_cents`, and advances the action's `version` by 1." PRD §3.5:
    "From `DRAFT` the action stays in `DRAFT` — a self-loop that lets the engineer
    re-price freely before submitting", and "the execution dimension is untouched".

    Design: Difficulty/combinatorial_formula/field_action_accrual_rounds_per_unit_before_multiplying_by_population
    """
    world = _build_world(api)
    assert world["action"]["version"] == 1
    assert world["action"]["selected_remedy_option_id"] is None
    assert world["action"]["specific_accrual_cents"] == 0

    selected = select_remedy(
        api,
        world["action"]["id"],
        remedy_option_id=world["option"]["id"],
        expected_field_action_version=1,
    )

    assert selected["selected_remedy_option_id"] == world["option"]["id"]
    assert selected["version"] == 2
    assert selected["approval_state"] == "DRAFT"
    assert selected["execution_state"] == "NOT_STARTED"
