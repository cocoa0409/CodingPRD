"""Energy labels, NFRC rating bases, and energy-code rule windows (PRD §3.3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_line,
    advance_unit_to_gas_filled,
    assign_order,
    confirm_order,
    create_dealer,
    create_draft_order,
    create_energy_rule,
    create_glass_gp3,
    create_open_wave,
    create_series_v200,
    get_success_data,
    list_line_units,
    lock_and_release,
    produce_line,
    qc_unit,
    setup_mn_catalog,
    setup_order_in_production,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["plant_manager_headers"]
PE = TEST_USERS["plant_engineer_headers"]


def _label_of(api, line_id):
    data, meta = validate_paginated(api.get_line_energy_label(line_id, PM))
    assert len(data) == 1, f"expected exactly one EnergyLabel for line {line_id}"
    return data[0]


def test_provisional_vs_certified_rating_divergence(api):
    """PRD §3.3: "While a line is being configured, its label is provisional:
    `u_factor` is the glass package's `catalog_u_factor` and `shgc` is its
    `catalog_shgc`, taken verbatim."
    PRD §3.3: "When the line completes production, the label certifies on a
    worst-unit basis: the server takes the lowest `argon_measured_pct` among the
    line's `QC_PASSED` units, derates the catalog U-factor by 0.002 for every
    percentage point of argon shortfall below the package's `argon_target_pct`,
    adds a spacer thermal-bridge derate of 0.01 for `ALUMINUM` spacers or 0.0
    for `WARM_EDGE`, and rounds the result half-up to two decimal places."
    PRD §3.3: "The SHGC stays at the catalog value, unchanged by fill."

    Design: Difficulty/dual_variant_calc/nfrc_provisional_vs_certified_rating_divergence
    """
    env = setup_order_in_production(quantity=2)
    line_id = env["line"]["id"]

    provisional = _label_of(api, line_id)
    assert provisional["basis"] == "PROVISIONAL"
    assert provisional["u_factor"] == pytest.approx(0.28, abs=0.001)

    units = list_line_units(line_id)
    advance_unit_to_gas_filled(units[0]["id"])
    advance_unit_to_gas_filled(units[1]["id"])
    qc_unit(units[0]["id"], 95)
    qc_unit(units[1]["id"], 90)

    certified = _label_of(api, line_id)
    assert certified["basis"] == "CERTIFIED"
    # worst-unit argon min(95, 90) = 90: 0.28 + (95-90)*0.002 + 0.01 = 0.30
    assert certified["u_factor"] == pytest.approx(0.30, abs=0.001)
    assert certified["shgc"] == pytest.approx(0.40, abs=0.001)


def test_line_completion_certifies_label_and_completes_order(api):
    """PRD §3.5: "A unit that clears both gates becomes `QC_PASSED` with its
    `argon_measured_pct` recorded; when the last unfinished unit of a line
    passes, the line bubbles up to `COMPLETED`, its energy label certifies on
    the worst-unit basis of §3.3, and if that was the order's final incomplete
    line the order itself moves `IN_PROGRESS → COMPLETED` and its
    `compliance_status` becomes `CERTIFIED`."

    Design: Difficulty/dual_variant_calc/nfrc_provisional_vs_certified_rating_divergence
    """
    env = setup_order_in_production(quantity=2)
    line_id = env["line"]["id"]
    units = list_line_units(line_id)
    for unit, fill in ((units[0], 95), (units[1], 90)):
        advance_unit_to_gas_filled(unit["id"])
        qc_unit(unit["id"], fill)

    line = validate_success(api.get_order_line(line_id, PM), 200)
    assert line["status"] == "COMPLETED"
    order = validate_success(api.get_order(env["order"]["id"], PM), 200)
    assert order["production_status"] == "COMPLETED"
    assert order["compliance_status"] == "CERTIFIED"
    assert _label_of(api, line_id)["status"] == "CERTIFIED"


def test_energy_label_auto_created_unevaluated_without_rule(api):
    """PRD §3.2: "Every line creation automatically creates the line's
    `EnergyLabel` in `PROVISIONAL` form, prices the line, recomputes the order
    totals and `promised_date`, and increments the order's `version`."
    PRD §3.3: "When no rule qualifies, `applied_energy_code_rule_id` stays null
    and `compliance` remains `UNEVALUATED`, which the confirm gate treats as
    passing."

    Design: Corner/entities/energy_label_auto_created_unevaluated_without_rule
    """
    cat = setup_mn_catalog(dealer_name="LakeLine", dealer_state="WI", with_rule=False)
    order = create_draft_order(cat["dealer"]["id"])
    line = add_line(order["id"], cat["series"]["id"], cat["glass"]["id"])

    labels, meta = validate_paginated(api.get_line_energy_label(line["id"], PM))
    assert len(labels) == 1
    label = labels[0]
    assert label["basis"] == "PROVISIONAL"
    assert label["status"] == "PROVISIONAL"
    assert label["compliance"] == "UNEVALUATED"
    assert label["applied_energy_code_rule_id"] is None
    assert label["u_factor"] == pytest.approx(0.28, abs=0.001)
    assert label["shgc"] == pytest.approx(0.40, abs=0.001)


def test_energy_rule_adjacency_legal_overlap_rejected(api):
    """PRD §3.3: "Two rules for the same state may not have overlapping windows;
    an overlapping creation is rejected with `ERR_ENERGY_RULE_WINDOW_OVERLAP`."
    PRD §3.3: "Adjacency is allowed: one rule's `effective_to` may coincide with
    the next rule's `effective_from`."

    Design: Difficulty/resource_temporal_overlap/energy_rule_half_open_adjacency_and_selection
    """
    create_energy_rule(payload={
        "state_code": "TX", "max_u_factor": 0.35, "max_shgc": 0.30,
        "effective_from": "2024-01-01T00:00:00Z", "effective_to": "2026-01-01T00:00:00Z",
    })
    adjacent = api.create_energy_code_rule({
        "state_code": "TX", "max_u_factor": 0.30, "max_shgc": 0.28,
        "effective_from": "2026-01-01T00:00:00Z",
    }, PE)
    validate_success(adjacent, 201)

    overlapping = api.create_energy_code_rule({
        "state_code": "TX", "max_u_factor": 0.33, "max_shgc": 0.29,
        "effective_from": "2025-06-01T00:00:00Z", "effective_to": "2027-01-01T00:00:00Z",
    }, PE)
    validate_error(overlapping, ApiErrorId.ERR_ENERGY_RULE_WINDOW_OVERLAP, expected_status=409)


def test_energy_rule_boundary_date_selection(api):
    """PRD §3.3: "Windows are half-open — a rule applies from its
    `effective_from` (inclusive) up to but not including its `effective_to`."
    PRD §3.3: "The label's rule is the `EnergyCodeRule` whose `state_code`
    equals the order's `ship_to_state_code` and whose half-open window contains
    the order's `order_date` — `effective_from` on or before the order date, and
    `effective_to` strictly after it when set."
    PRD §3.3: "When a rule qualifies, `compliance` is `PASS` when the label's
    current `u_factor` is no greater than the rule's `max_u_factor` and its
    `shgc` is no greater than the rule's `max_shgc` — both boundaries inclusive —
    and `FAIL` otherwise."

    Design: Difficulty/resource_temporal_overlap/energy_rule_half_open_adjacency_and_selection
    """
    rule1 = create_energy_rule(payload={
        "state_code": "TX", "max_u_factor": 0.35, "max_shgc": 0.30,
        "effective_from": "2024-01-01T00:00:00Z", "effective_to": "2026-01-01T00:00:00Z",
    })
    rule2 = get_success_data(api.create_energy_code_rule({
        "state_code": "TX", "max_u_factor": 0.30, "max_shgc": 0.28,
        "effective_from": "2026-01-01T00:00:00Z",
    }, PE))
    series = create_series_v200()
    glass = create_glass_gp3()  # catalog u 0.31, shgc 0.23
    dealer = create_dealer(name="LoneStar", state="TX")

    order_old = create_draft_order(dealer["id"], order_date="2025-12-31T00:00:00Z")
    line_old = add_line(order_old["id"], series["id"], glass["id"])
    order_new = create_draft_order(dealer["id"], order_date="2026-01-01T00:00:00Z")
    line_new = add_line(order_new["id"], series["id"], glass["id"])

    label_old = _label_of(api, line_old["id"])
    assert label_old["applied_energy_code_rule_id"] == rule1["id"]
    assert label_old["compliance"] == "PASS"  # 0.31 <= 0.35 and 0.23 <= 0.30

    label_new = _label_of(api, line_new["id"])
    assert label_new["applied_energy_code_rule_id"] == rule2["id"]
    assert label_new["compliance"] == "FAIL"  # 0.31 > 0.30 — boundary belongs to the new window


def test_energy_code_no_rule_unevaluated_passes_confirm(api):
    """PRD §3.3: "When no rule qualifies, `applied_energy_code_rule_id` stays
    null and `compliance` remains `UNEVALUATED`, which the confirm gate treats
    as passing."
    PRD §3.2: "On success the server reprices every line one final time, freezes
    `subtotal_cents`, `discount_cents`, and `total_price_cents`, moves
    `compliance_status` to `PROVISIONALLY_COMPLIANT`, cascades each line from
    `PENDING` to `CONFIRMED`, and increments the order's `version`."

    Design: Corner/calculations/energy_code_no_rule_unevaluated_passes_confirm
    """
    cat = setup_mn_catalog(dealer_name="LakeLine", dealer_state="WI", with_rule=False)
    order = create_draft_order(cat["dealer"]["id"])
    add_line(order["id"], cat["series"]["id"], cat["glass"]["id"])
    confirmed = validate_success(api.confirm_order(order["id"], PM), 200)
    assert confirmed["production_status"] == "CONFIRMED"
    assert confirmed["compliance_status"] == "PROVISIONALLY_COMPLIANT"


def test_energy_labels_filtered_by_applied_rule(api):
    """PRD §3.3: "Labels may also be listed across the plant filtered by
    `order_line_id` or `applied_energy_code_rule_id`."
    PRD §3.3: "While a line is being configured, its label is provisional:
    `u_factor` is the glass package's `catalog_u_factor` and `shgc` is its
    `catalog_shgc`, taken verbatim."

    Design: Corner/endpoints/energy_labels_filtered_by_applied_rule
    """
    cat = setup_mn_catalog()
    order1 = create_draft_order(cat["dealer"]["id"])
    add_line(order1["id"], cat["series"]["id"], cat["glass"]["id"])
    order2 = create_draft_order(cat["dealer"]["id"], order_date="2026-08-03T00:00:00Z")
    add_line(order2["id"], cat["series"]["id"], cat["glass"]["id"],
             width_in=36, height_in=48, quantity=2, grid_style="COLONIAL")

    data, meta = validate_paginated(
        api.list_energy_labels(PM, params={"applied_energy_code_rule_id": cat["rule"]["id"]})
    )
    assert meta["total_count"] == 2
    assert len(data) == 2
    for row in data:
        assert row["applied_energy_code_rule_id"] == cat["rule"]["id"]
        assert row["compliance"] == "PASS"
        assert row["u_factor"] == pytest.approx(0.28, abs=0.001)
