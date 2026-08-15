"""Turn cost views, booked-cost rounding, completion rollups, and
repair-vs-replace decision economics with capital classification."""
from test_helpers import (
    TC,
    ApiErrorId,
    accept,
    add_scope_item,
    assert_replacement_decision,
    assert_turn_money_partition,
    complete,
    create_property,
    create_unit,
    create_vendor,
    finalize_turn,
    get_item,
    get_turn,
    open_turn,
    record_decision,
    schedule,
    setup_in_progress_turn,
    validate_error,
    validate_success,
)


# --- operating vs all-in views (Difficulty: turn_cost_operating_vs_all_in_views)

def _setup_expense_and_capital_turn(api):
    """Turn with an EXPENSE repair completed at 1010 and a CAPITAL appliance
    replacement completed at 60000."""
    prop = create_property()  # capital_threshold_cents 50000, PERCENT_OF_REPLACE
    unit = create_unit(prop["id"])
    turn = open_turn(unit["id"])
    repair_item = add_scope_item(turn["id"], "REPAIR", 2000, "drywall patch")
    appliance_item = add_scope_item(turn["id"], "APPLIANCE", 55000,
                                    "stove replacement")
    # REPLACE at 60000 >= 50000 capital threshold -> CAPITAL classification.
    record_decision(turn["id"], appliance_item["id"],
                    repair_estimate_cents=58000, replace_estimate_cents=60000,
                    repair_life_years=2, remaining_life_years=8,
                    decision="REPLACE")
    finalize_turn(turn["id"])
    vendor = create_vendor("FixCo", "REPAIR")
    asg_r = schedule(repair_item["id"], vendor["id"],
                     "2026-08-01", "2026-08-03")
    accept(asg_r["id"], vendor["id"])
    complete(asg_r["id"], vendor["id"], 1010)
    # APPLIANCE/FIXTURE/OTHER items are handled by REPAIR-trade vendors.
    asg_a = schedule(appliance_item["id"], vendor["id"],
                     "2026-08-03", "2026-08-05")
    accept(asg_a["id"], vendor["id"])
    complete(asg_a["id"], vendor["id"], 60000)
    return turn["id"], repair_item["id"], appliance_item["id"]


def test_operating_and_all_in_views_partition_spend(api):
    """PRD §2.7: "`expense_actual_cents` accumulates the `actual_cost_cents` of
    the turn's scope items whose status is `COMPLETED` or `FAILED` and whose
    `classification` is `EXPENSE`; `capital_actual_cents` accumulates the same
    over items classified `CAPITAL`. `total_actual_cents` is always exactly the
    sum of the two — a partition invariant guaranteeing that every booked cent
    lands in precisely one bucket, no cent counted twice and none dropped."
    PRD §2.7: "identical item histories yield a different number for the two
    views whenever any `CAPITAL`-classified item exists on the turn."

    Design: Difficulty/dual_variant_calc/turn_cost_operating_vs_all_in_views
    """
    turn_id, _, _ = _setup_expense_and_capital_turn(api)
    turn = get_turn(turn_id)
    assert turn["expense_actual_cents"] == 1010, "operating view"
    assert turn["capital_actual_cents"] == 60000, "capital bucket"
    assert turn["total_actual_cents"] == 61010, "all-in view"
    assert_turn_money_partition(turn)


def test_booked_expense_excludes_capital_and_carries_overhead(api):
    """PRD §3.4: "for each `EXPENSE`-classified item in `COMPLETED` or `FAILED`
    status, an overhead of 250 basis points — two and a half percent — of the
    item's `actual_cost_cents` is computed and rounded half up to whole cents
    *per item*, the item's booked cost is its actual plus its own overhead, and
    `booked_expense_cents` is the sum of those per-item booked costs."
    PRD §3.6: "`REPAIR` always classifies `EXPENSE`, while `REPLACE` classifies
    `CAPITAL` exactly when `replace_estimate_cents` is greater than or equal to
    the property's `capital_threshold_cents`, and `EXPENSE` otherwise."

    Design: Difficulty/dual_variant_calc/turn_cost_operating_vs_all_in_views
    """
    turn_id, repair_id, appliance_id = _setup_expense_and_capital_turn(api)
    turn = get_turn(turn_id)
    # 1010 + round_half_up(1010 * 250bp) = 1010 + 25 = 1035; CAPITAL excluded.
    assert turn["booked_expense_cents"] == 1035
    assert get_item(appliance_id)["classification"] == "CAPITAL"
    assert get_item(repair_id)["classification"] == "EXPENSE"


# --- per-item rounding order (Difficulty: booked_cost_per_item_rounding_order)

def _setup_two_items_at_1010(api):
    """Turn with REPAIR and CLEAN items each completed at 1010 cents."""
    prop = create_property()
    unit = create_unit(prop["id"])
    turn = open_turn(unit["id"])
    repair = add_scope_item(turn["id"], "REPAIR", 1000, "drywall")
    clean = add_scope_item(turn["id"], "CLEAN", 1000, "clean")
    finalize_turn(turn["id"])
    fixer = create_vendor("FixCo", "REPAIR")
    cleaner = create_vendor("CleanCo", "CLEAN")
    asg_r = schedule(repair["id"], fixer["id"], "2026-08-01", "2026-08-03")
    accept(asg_r["id"], fixer["id"])
    complete(asg_r["id"], fixer["id"], 1010)
    asg_c = schedule(clean["id"], cleaner["id"], "2026-08-03", "2026-08-04")
    accept(asg_c["id"], cleaner["id"])
    complete(asg_c["id"], cleaner["id"], 1010)
    return turn["id"]


def test_booked_expense_rounds_overhead_per_item(api):
    """PRD §3.4: "Rounding each item before summing is mandatory; summing first
    and rounding once is forbidden. Concretely, two items of 1010 cents each
    contribute 25 cents of overhead apiece — 50 cents total, for a booked 2070
    cents — whereas a sum-then-round scheme would round the combined 50.50
    cents of overhead to 51 and incorrectly report 2071."

    Design: Difficulty/combinatorial_formula/booked_cost_per_item_rounding_order
    """
    turn_id = _setup_two_items_at_1010(api)
    turn = get_turn(turn_id)
    assert turn["expense_actual_cents"] == 2020
    assert turn["booked_expense_cents"] == 2070, (
        "per-item rounding: 25 + 25 overhead"
    )


def test_sum_then_round_would_report_2071_and_is_forbidden(api):
    """PRD §3.4: "Rounding each item before summing is mandatory; summing first
    and rounding once is forbidden. Concretely, two items of 1010 cents each
    contribute 25 cents of overhead apiece — 50 cents total, for a booked 2070
    cents — whereas a sum-then-round scheme would round the combined 50.50
    cents of overhead to 51 and incorrectly report 2071."

    Design: Difficulty/combinatorial_formula/booked_cost_per_item_rounding_order
    """
    turn_id = _setup_two_items_at_1010(api)
    turn = get_turn(turn_id)
    overhead = turn["booked_expense_cents"] - turn["expense_actual_cents"]
    assert overhead == 50, "exactly 25 cents of overhead per 1010-cent item"
    assert turn["booked_expense_cents"] != 2071, (
        "2071 is the forbidden sum-then-round result"
    )


# --- completion rollup cascade (Difficulty: assignment_complete_item_turn_rollup_cascade)

def test_completion_sets_assignment_and_item_actuals(api):
    """PRD §3.4: "The assigned vendor completes an `ACCEPTED` assignment by
    reporting the invoiced `actual_cost_cents`; the assignment becomes
    `COMPLETED`, the vendor's `open_assignment_count` drops by one, and the
    scope item moves from `SCHEDULED` to `COMPLETED` with its own
    `actual_cost_cents` set from the assignment."

    Design: Difficulty/transitive_cascade/assignment_complete_item_turn_rollup_cascade
    """
    ctx = setup_in_progress_turn(5000)
    completed = complete(ctx["assignment"]["id"], ctx["vendor"]["id"], 4500)
    assert completed["status"] == "COMPLETED"
    item = get_item(ctx["item"]["id"])
    assert item["status"] == "COMPLETED"
    assert item["actual_cost_cents"] == 4500, "cost set from the assignment"


def test_completion_recomputes_turn_actuals_and_booked(api):
    """PRD §3.4: "That item completion recomputes the turn's actuals: the
    item's cost joins `expense_actual_cents` or `capital_actual_cents`
    according to its `classification`, `total_actual_cents` re-derives as their
    sum, and `booked_expense_cents` is rebuilt."
    PRD §3.4: "an overhead of 250 basis points — two and a half percent — of
    the item's `actual_cost_cents` is computed and rounded half up to whole
    cents *per item*, the item's booked cost is its actual plus its own
    overhead, and `booked_expense_cents` is the sum of those per-item booked
    costs."

    Design: Difficulty/transitive_cascade/assignment_complete_item_turn_rollup_cascade
    """
    ctx = setup_in_progress_turn(5000)
    complete(ctx["assignment"]["id"], ctx["vendor"]["id"], 4500)
    turn = get_turn(ctx["turn"]["id"])
    assert turn["expense_actual_cents"] == 4500
    assert turn["total_actual_cents"] == 4500
    # 4500 + round_half_up(4500 * 250bp = 112.50) = 4500 + 113.
    assert turn["booked_expense_cents"] == 4613


# --- policy variants (Difficulty: replacement_policy_percent_vs_cost_per_year)

def _open_turn_with_appliance(replacement_policy):
    prop = create_property(replacement_policy=replacement_policy)
    unit = create_unit(prop["id"])
    turn = open_turn(unit["id"])
    item = add_scope_item(turn["id"], "APPLIANCE", 55000, "dishwasher")
    return turn, item


def test_percent_of_replace_permits_borderline_repair(api):
    """PRD §3.6: "Identical inputs can yield opposite verdicts under the two
    variants: a 49000-cent repair against a 100000-cent replacement with a
    three-year repair life and a ten-year new-asset life is permitted by the
    percentage variant (49000 falls strictly below the 50000-cent ceiling) yet
    denied by the cost-per-year variant (490000 — the repair estimate times the
    ten-year new-asset life — is not strictly less than 300000, the replacement
    estimate times the three-year repair life)."
    PRD §3.6: "the item's `estimated_cost_cents` is overwritten with the chosen
    path's estimate — `repair_estimate_cents` for a repair,
    `replace_estimate_cents` for a replacement — and its `classification`
    becomes `resulting_classification`."

    Design: Difficulty/dual_variant_calc/replacement_policy_percent_vs_cost_per_year
    """
    turn, item = _open_turn_with_appliance("PERCENT_OF_REPLACE")
    decision = validate_success(api.create_replacement_decision(
        turn["id"],
        {"scope_item_id": item["id"], "repair_estimate_cents": 49000,
         "replace_estimate_cents": 100000, "repair_life_years": 3,
         "remaining_life_years": 10, "decision": "REPAIR"},
        TC), 201)
    assert_replacement_decision(decision)
    assert decision["policy_applied"] == "PERCENT_OF_REPLACE"
    assert decision["resulting_classification"] == "EXPENSE"
    assert get_item(item["id"])["estimated_cost_cents"] == 49000


def test_cost_per_year_denies_the_same_repair(api):
    """PRD §3.6: "Under `COST_PER_YEAR`, a repair is economical only when
    `repair_estimate_cents` multiplied by `remaining_life_years` is strictly
    less than `replace_estimate_cents` multiplied by `repair_life_years` — an
    integer-exact, cross-multiplied comparison of cost per year of service,
    with no floating point involved."
    PRD §3.6: "An uneconomical `REPAIR` is rejected with
    `ERR_UNECONOMICAL_REPAIR`; a `REPLACE` decision is never rejected by this
    rule."

    Design: Difficulty/dual_variant_calc/replacement_policy_percent_vs_cost_per_year
    """
    turn, item = _open_turn_with_appliance("COST_PER_YEAR")
    resp = api.create_replacement_decision(
        turn["id"],
        {"scope_item_id": item["id"], "repair_estimate_cents": 49000,
         "replace_estimate_cents": 100000, "repair_life_years": 3,
         "remaining_life_years": 10, "decision": "REPAIR"},
        TC)
    validate_error(resp, ApiErrorId.ERR_UNECONOMICAL_REPAIR, 422)
    assert get_item(item["id"])["estimated_cost_cents"] == 55000, (
        "no decision recorded: the item is untouched"
    )


# --- capital threshold boundary (Corner: capital_threshold_equality_boundary)

def test_replace_classification_at_capital_threshold(api):
    """PRD §3.6: "Every recorded decision stamps `resulting_classification`:
    `REPAIR` always classifies `EXPENSE`, while `REPLACE` classifies `CAPITAL`
    exactly when `replace_estimate_cents` is greater than or equal to the
    property's `capital_threshold_cents`, and `EXPENSE` otherwise."
    PRD §3.6: "the item's `estimated_cost_cents` is overwritten with the chosen
    path's estimate — `repair_estimate_cents` for a repair,
    `replace_estimate_cents` for a replacement — and its `classification`
    becomes `resulting_classification`."

    Design: Corner/calculations/capital_threshold_equality_boundary
    """
    prop = create_property()  # capital_threshold_cents 50000
    unit = create_unit(prop["id"])
    turn = open_turn(unit["id"])
    stove = add_scope_item(turn["id"], "APPLIANCE", 1000, "stove")
    dishwasher = add_scope_item(turn["id"], "APPLIANCE", 1000, "dishwasher")

    d1 = validate_success(api.create_replacement_decision(
        turn["id"],
        {"scope_item_id": stove["id"], "repair_estimate_cents": 30000,
         "replace_estimate_cents": 50000, "repair_life_years": 2,
         "remaining_life_years": 8, "decision": "REPLACE"},
        TC), 201)
    d2 = validate_success(api.create_replacement_decision(
        turn["id"],
        {"scope_item_id": dishwasher["id"], "repair_estimate_cents": 30000,
         "replace_estimate_cents": 49999, "repair_life_years": 2,
         "remaining_life_years": 8, "decision": "REPLACE"},
        TC), 201)

    assert d1["resulting_classification"] == "CAPITAL", "50000 >= 50000"
    assert get_item(stove["id"])["classification"] == "CAPITAL"
    assert get_item(stove["id"])["estimated_cost_cents"] == 50000
    assert d2["resulting_classification"] == "EXPENSE", "49999 < 50000"
    assert get_item(dishwasher["id"])["classification"] == "EXPENSE"
    assert get_item(dishwasher["id"])["estimated_cost_cents"] == 49999


# --- decision applicability (Corner: decision_on_non_appliance_item_rejected)

def test_decision_on_repair_item_rejected(api):
    """PRD §3.6: "Two referential guards apply, before any economics: a
    decision on an item whose category is not `APPLIANCE` or `FIXTURE` is
    rejected with `ERR_DECISION_NOT_APPLICABLE`, and a second decision on an
    item that already has one is rejected with `ERR_DECISION_ALREADY_EXISTS` —
    at most one decision ever attaches to an item, so the per-item decision
    listing returns at most one element, while the per-turn listing returns
    every decision recorded on the turn."

    Design: Corner/validations/decision_on_non_appliance_item_rejected
    """
    prop = create_property()
    unit = create_unit(prop["id"])
    turn = open_turn(unit["id"])
    item = add_scope_item(turn["id"], "REPAIR", 5000, "drywall")
    resp = api.create_replacement_decision(
        turn["id"],
        {"scope_item_id": item["id"], "repair_estimate_cents": 3000,
         "replace_estimate_cents": 8000, "repair_life_years": 2,
         "remaining_life_years": 8, "decision": "REPAIR"},
        TC)
    validate_error(resp, ApiErrorId.ERR_DECISION_NOT_APPLICABLE, 422)


# --- one decision per item (Corner: second_decision_on_same_item_rejected)

def test_second_decision_on_same_item_rejected(api):
    """PRD §3.6: "Two referential guards apply, before any economics: a
    decision on an item whose category is not `APPLIANCE` or `FIXTURE` is
    rejected with `ERR_DECISION_NOT_APPLICABLE`, and a second decision on an
    item that already has one is rejected with `ERR_DECISION_ALREADY_EXISTS` —
    at most one decision ever attaches to an item, so the per-item decision
    listing returns at most one element, while the per-turn listing returns
    every decision recorded on the turn."

    Design: Corner/validations/second_decision_on_same_item_rejected
    """
    prop = create_property()  # capital threshold 50000 -> 40000 REPLACE is EXPENSE
    unit = create_unit(prop["id"])
    turn = open_turn(unit["id"])
    item = add_scope_item(turn["id"], "APPLIANCE", 1000, "stove")
    record_decision(turn["id"], item["id"], repair_estimate_cents=30000,
                    replace_estimate_cents=40000, repair_life_years=2,
                    remaining_life_years=8, decision="REPLACE")

    resp = api.create_replacement_decision(
        turn["id"],
        {"scope_item_id": item["id"], "repair_estimate_cents": 5000,
         "replace_estimate_cents": 40000, "repair_life_years": 2,
         "remaining_life_years": 8, "decision": "REPAIR"},
        TC)
    validate_error(resp, ApiErrorId.ERR_DECISION_ALREADY_EXISTS, 422)
    item_after = get_item(item["id"])
    assert item_after["estimated_cost_cents"] == 40000, "first decision stands"
    assert item_after["classification"] == "EXPENSE"
