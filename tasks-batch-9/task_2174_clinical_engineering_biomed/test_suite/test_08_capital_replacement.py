"""The capital-replacement score and the fiscal funding waterfall."""

from test_helpers import (
    assert_device,
    bootstrap_pump_campus,
    read_device,
    setup_replacement_plan_scene,
    setup_tied_replacement_scores,
    validate_paginated,
)


def test_replacement_score_rounds_half_up_at_the_third_decimal(api, ce_manager_headers):
    """PRD §3.9: "The score is 100 multiplied by the sum of the age factor times 0.35, the
    condition factor times 0.30, the burden factor times 0.20 and the risk weight times 0.15,
    rounded half up to two decimal places — so a third decimal of exactly 5 rounds the second
    decimal up."
    PRD §3.9: "The **burden factor** is the unit's `lifetime_maintenance_cost_cents` divided by
    the model's `replacement_cost_cents`, capped at 1.0 — a unit that has cost more in repairs
    than a new one would cost contributes a full share."

    Design: Corner/calculations/replacement_priority_score_rounds_half_up_at_third_decimal
    """
    scene = bootstrap_pump_campus()
    device = read_device(scene["device"]["id"])
    assert_device(device)

    assert device["risk_score"] == 38
    assert device["risk_class"] == "CRITICAL"
    assert device["lifetime_maintenance_cost_cents"] == 0
    assert float(device["replacement_priority_score"]) == 60.63, (
        f"An exact 60.625 must round half up to 60.63, got "
        f"{device['replacement_priority_score']}"
    )


def test_the_funding_waterfall_skips_an_unaffordable_unit_and_continues(api, ce_manager_headers):
    """PRD §3.9: "Supplying `fiscal_budget_cents` turns the read into a funding waterfall.
    Starting from the full budget, the ranked units are walked in order; for each, the cost
    considered is that unit's catalogue model `replacement_cost_cents`. When that cost is less
    than or equal to the remaining budget, the unit's `plan_funded` is set to `true` and the
    cost is subtracted from the remaining budget. When it is greater, the unit's `plan_funded`
    is set to `false` and the walk **continues to the next unit** — it does not stop at the
    first miss, so a cheap low-priority unit can be funded after an expensive high-priority one
    was skipped."
    PRD §3.9: "The comparison is inclusive: a unit costing exactly the remaining budget is
    funded."

    Design: Corner/calculations/replacement_plan_waterfall_skips_and_continues
    """
    scene = setup_replacement_plan_scene()

    data, _ = validate_paginated(
        api.get_replacement_plan(scene["facility"]["id"], ce_manager_headers,
                                 params={"fiscal_budget_cents": 1_800_000})
    )
    returned = [row["id"] for row in data]
    assert returned == [scene["device"]["id"], scene["monitor_device"]["id"],
                        scene["scale_device"]["id"]], (
        "Devices must be ranked by descending replacement_priority_score"
    )

    by_id = {row["id"]: row for row in data}
    pump = by_id[scene["device"]["id"]]
    monitor = by_id[scene["monitor_device"]["id"]]
    scale = by_id[scene["scale_device"]["id"]]

    assert float(pump["replacement_priority_score"]) == 60.63
    assert pump["plan_rank"] == 1 and pump["plan_funded"] is False
    assert float(monitor["replacement_priority_score"]) == 54.50
    assert monitor["plan_rank"] == 2 and monitor["plan_funded"] is True
    assert float(scale["replacement_priority_score"]) == 21.75
    assert scale["plan_rank"] == 3 and scale["plan_funded"] is True, (
        "A 300000-cent unit costing exactly the remaining budget is funded"
    )


def test_the_plan_read_persists_rank_and_funding_on_the_device(api, ce_manager_headers):
    """PRD §3.9: "Both `plan_rank` and `plan_funded` are **persisted** on the device rows by
    this read, so the plan is not a transient projection but a recorded decision."
    PRD §3.9: "Each returned unit's `plan_rank` is written as its 1-based position in that
    ranking — a device that has never appeared in a plan read carries `plan_rank` 0."

    Design: Corner/calculations/replacement_plan_waterfall_skips_and_continues
    """
    scene = setup_replacement_plan_scene()
    assert scene["scale_device"]["plan_rank"] == 0

    validate_paginated(
        api.get_replacement_plan(scene["facility"]["id"], ce_manager_headers,
                                 params={"fiscal_budget_cents": 1_800_000})
    )

    scale = read_device(scene["scale_device"]["id"])
    assert scale["plan_rank"] == 3
    assert scale["plan_funded"] is True


def test_equal_scores_break_on_acquisition_date_not_on_insertion_order(api, ce_manager_headers):
    """PRD §3.9: "It returns every device at that campus whose `operational_state` is not
    `RETIRED`, ranked by descending `replacement_priority_score`, then by ascending
    `acquisition_date`, then by ascending `created_at`, and it recomputes each returned unit's
    score against the current logical clock before ranking."
    PRD §3.9: "The **age factor** is the unit's age in whole years — the whole-day difference
    between the current logical-clock date and `acquisition_date`, divided by 365 and rounded
    down — divided by the catalogue model's `expected_life_years`, capped at 1.0, so a unit
    past its expected life contributes a full share and no more."

    Design: Corner/calculations/replacement_plan_ties_break_on_acquisition_date
    """
    scene = setup_tied_replacement_scores()

    data, _ = validate_paginated(
        api.get_replacement_plan(scene["facility"]["id"], ce_manager_headers)
    )
    by_id = {row["id"]: row for row in data}
    older = by_id[scene["older_device"]["id"]]
    newer = by_id[scene["newer_device"]["id"]]

    assert float(older["replacement_priority_score"]) == 57.50
    assert float(newer["replacement_priority_score"]) == 57.50
    assert older["plan_rank"] == 1, (
        "The 2015 unit ranks first even though it was created second"
    )
    assert newer["plan_rank"] == 2


def test_a_plan_read_without_a_budget_funds_nothing(api, ce_manager_headers):
    """PRD §3.9: "When `fiscal_budget_cents` is omitted, every returned unit keeps
    `plan_funded` at `false`."
    PRD §3.9: "The **risk weight** is read from the frozen `risk_class`: 1.0 for `CRITICAL`,
    0.75 for `HIGH`, 0.5 for `MEDIUM` and 0.25 for `LOW`."

    Design: Corner/calculations/replacement_plan_ties_break_on_acquisition_date
    """
    scene = setup_tied_replacement_scores()

    data, meta = validate_paginated(
        api.get_replacement_plan(scene["facility"]["id"], ce_manager_headers)
    )
    assert meta["total_count"] == 2
    for row in data:
        assert row["plan_funded"] is False, (
            f"Device {row['id']} must stay unfunded when no budget is supplied"
        )
