"""Contract value on the two arms, the travel zones and the package tier changes."""

from test_helpers import (
    COORD,
    ApiErrorId,
    assert_money,
    assert_project,
    setup_occupied_mixed_scope_draft,
    setup_vacant_at_room_cap_scope_approved,
    setup_vacant_project_draft,
    setup_vacant_project_staged,
    setup_vacant_zone1_scope_approved,
    validate_error,
    validate_success,
)


def test_vacant_contract_value_carries_three_cycles_of_forward_rent(api):
    """PRD §3.2: "On a `VACANT_STAGING` project the forward-looking part is the tier's
    `monthly_rent_rate` multiplied by 3 cycles and rounded half-up to two decimal places,
    and the labour part is exactly 0.00 — a forward commitment to three cycles of package
    rent, made before any pull exists."
    PRD §3.2: "It is assembled from six parts: the tier's `base_price`, the room overage,
    the accessory overage, the travel fee, a forward-looking rental commitment, and a
    labour figure."

    Design: Difficulty/dual_variant_calc/contract_value_diverges_by_pipeline_on_project_cost_accounting
    """
    ctx = setup_vacant_project_draft()

    project = validate_success(api.get_project(ctx["proj_id"], COORD))

    assert_project(project)
    assert project["pipeline"] == "VACANT_STAGING"
    assert_money(project["contract_value"], 7690.00, "project.contract_value")


def test_vacant_contract_value_counts_rooms_and_accessory_sets_from_the_scope(api):
    """PRD §3.2: "**Room overage** is the number of rooms beyond the tier's `room_cap`,
    floored at zero, multiplied by 375.00 and rounded half-up to two decimal places."
    PRD §3.2: "**Accessory overage** is the number of accessory sets beyond the tier's
    `included_accessory_sets`, floored at zero, multiplied by 120.00 and rounded the same
    way."
    PRD §3.2: "The new row starts in `workflow_state` `DRAFT` and `payment_state`
    `UNBILLED`, with `window_extension_count` 0, `restage_count` 0, `photo_sessions_consumed`
    0, `reshoot_credits_remaining` 1, `destage_eligible` false and `fiscal_hold` false."

    Design: Difficulty/dual_variant_calc/contract_value_diverges_by_pipeline_on_project_cost_accounting
    """
    ctx = setup_vacant_project_draft()

    project = validate_success(api.get_project(ctx["proj_id"], COORD))

    assert project["room_count"] == 4
    assert project["accessory_set_count"] == 3
    assert project["workflow_state"] == "DRAFT"


def test_occupied_contract_value_prices_consultant_hours_and_the_first_visit_surcharge(api):
    """PRD §3.2: "On an `OCCUPIED_PREP` project the forward part is exactly 0.00 and the
    labour part is the consultation's `estimated_hours` multiplied by an hourly rate of
    165.00, rounded half-up to two decimal places, with a first-visit surcharge of 95.00
    added *after* that rounding."
    PRD §3.2: "The same property with the same tier therefore yields a different
    `contract_value` on each arm, by construction."

    Design: Difficulty/dual_variant_calc/contract_value_occupied_arm_prices_hours_not_lease
    """
    ctx = setup_occupied_mixed_scope_draft()

    project = validate_success(api.get_project(ctx["proj_id"], COORD))

    assert_project(project)
    assert project["pipeline"] == "OCCUPIED_PREP"
    assert_money(project["contract_value"], 4265.00, "project.contract_value")


def test_occupied_room_count_ignores_the_accessory_only_room(api):
    """PRD §3.2: "The project's `room_count` is the count of scope items on the
    consultation whose `action` is not `ACCESSORY_ONLY` — accessory-only rooms are excluded
    from the room count while still contributing their accessory sets."
    PRD §3.2: "The project's `accessory_set_count` is the sum of `accessory_set_count` over
    every scope item on that consultation."

    Design: Difficulty/dual_variant_calc/contract_value_occupied_arm_prices_hours_not_lease
    """
    ctx = setup_occupied_mixed_scope_draft()

    project = validate_success(api.get_project(ctx["proj_id"], COORD))

    assert project["room_count"] == 2
    assert project["accessory_set_count"] == 2


def test_a_property_at_exactly_fifteen_miles_pays_no_travel_fee(api):
    """PRD §3.2: "A distance of at most 15 miles is zone 1 and costs 0.00."
    PRD §3.2: "Both zone boundaries are inclusive at the top, so exactly 15.0 miles is zone
    1 and exactly 40.0 miles is zone 2."

    Design: Corner/cross_cutting_complexity_layers/travel_fee_threshold_is_inclusive_at_the_zone_ceiling
    """
    ctx = setup_vacant_zone1_scope_approved()

    resp = api.create_project(
        {"property_id": ctx["prop_id"], "consultation_id": ctx["cons_id"],
         "listing_id": ctx["listing_id"], "package_tier_id": ctx["tier_sig"],
         "payer_client_id": ctx["seller_id"], "payer_type": "SELLER"}, COORD)

    project = validate_success(resp, 201)
    assert_money(project["contract_value"], 7050.00, "project.contract_value")
    assert project["room_count"] == 2
    assert project["accessory_set_count"] == 0


def test_rooms_exactly_at_the_tier_cap_incur_no_overage(api):
    """PRD §3.2: "**Room overage** is the number of rooms beyond the tier's `room_cap`,
    floored at zero, multiplied by 375.00 and rounded half-up to two decimal places."
    PRD §3.2: "**Accessory overage** is the number of accessory sets beyond the tier's
    `included_accessory_sets`, floored at zero, multiplied by 120.00 and rounded the same
    way."

    Design: Corner/calculations/room_count_exactly_at_the_cap_charges_no_overage
    """
    ctx = setup_vacant_at_room_cap_scope_approved()

    resp = api.create_project(
        {"property_id": ctx["prop_id"], "consultation_id": ctx["cons_id"],
         "listing_id": ctx["listing_id"], "package_tier_id": ctx["tier_sig"],
         "payer_client_id": ctx["seller_id"], "payer_type": "SELLER"}, COORD)

    project = validate_success(resp, 201)
    assert project["room_count"] == 3
    assert project["accessory_set_count"] == 2
    assert_money(project["contract_value"], 7050.00, "project.contract_value")


def test_upgrade_then_matching_downgrade_restores_the_tier_but_not_the_price_path(api):
    """PRD §3.2: "On an upgrade the service takes the price delta between the new tier's
    `base_price` and the old one's, and prorates it: if the project has a lease, the
    remaining days are the days from the logical clock to the lease's `end_date`, floored
    at zero, and the delta is multiplied by the smaller of 1.0 and those remaining days
    divided by a 30-day proration basis; if no lease row exists yet, the full delta is
    charged with no proration at all."
    PRD §3.2: "Because the credit rate is zero and a restocking fee applies, an upgrade
    followed by the matching downgrade does not restore the project's original
    `contract_value`: the round trip costs the restocking fee plus the whole prorated
    upgrade charge, while the reverse order costs the restocking fee plus a re-charged full
    price delta."
    PRD §3.2: "Both are computed against the tier the project currently holds, so both are
    re-derived whenever the tier changes."

    Design: Corner/cross_cutting_complexity_layers/package_upgrade_and_downgrade_are_not_price_symmetric
    """
    ctx = setup_vacant_project_staged()
    validate_success(api.upgrade_package(ctx["proj_id"], ctx["tier_luxe"], COORD))

    resp = api.downgrade_package(ctx["proj_id"], ctx["tier_sig"], COORD)

    validate_success(resp)
    project = validate_success(api.get_project(ctx["proj_id"], COORD))
    assert project["package_tier_id"] == ctx["tier_sig"]
    assert_money(project["contract_value"], 7690.00, "project.contract_value")


def test_upgrading_to_the_tier_already_held_is_an_invalid_tier_change(api):
    """PRD §2.7: "Rung 47: an upgrade target has a strictly greater `tier_rank` than the
    project's current tier, and a downgrade target a strictly smaller one; otherwise
    `ERR_INVALID_TIER_CHANGE`, HTTP 422."
    PRD §3.2: "An **upgrade** must name a tier of strictly greater `tier_rank`; a
    **downgrade**, one of strictly smaller rank; either violation is
    `ERR_INVALID_TIER_CHANGE`."

    Design: Corner/validations/upgrade_to_the_same_tier_rejected_as_invalid_tier_change
    """
    ctx = setup_vacant_project_staged()

    resp = api.upgrade_package(ctx["proj_id"], ctx["tier_sig"], COORD)

    validate_error(resp, ApiErrorId.ERR_INVALID_TIER_CHANGE.value, 422)
    project = validate_success(api.get_project(ctx["proj_id"], COORD))
    assert project["package_tier_id"] == ctx["tier_sig"]
    assert_money(project["contract_value"], 7690.00, "project.contract_value")
