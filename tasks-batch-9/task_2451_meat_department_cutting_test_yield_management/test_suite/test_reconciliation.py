"""Period reconciliation of the meat case: the two measurement bases, the scope
filter that keeps unpublished service days out of the books, and the gates that
guard a posting.

Every figure asserted here is recomputed from the PRD's own formulas (§3.6 for
required fill and markdown give-up, §3.9 for the reconciliation arithmetic).
"""

import pytest

from test_helpers import (
    ANALYST,
    MANAGER,
    activate_price_from_cutting_test,
    activate_price_from_grind_run,
    add_case_plan_line,
    add_cutting_test_line,
    add_grind_input,
    approve_cutting_test,
    assert_shrink_reconciliation,
    complete_grind_run,
    create_case_plan,
    create_cutting_test,
    create_grind_run,
    create_ground_item,
    create_primal_purchase,
    create_retail_item,
    create_trim_lot_from_line,
    draft_reconciliation,
    fill_line,
    get_success_data,
    mark_down_line,
    post_reconciliation,
    propose_price,
    publish_case_plan,
    read_case_plan,
    read_case_plan_line,
    read_primal_purchase,
    read_reconciliation,
    read_retail_item,
    resume_case_plan,
    seeded_department,
    start_grind_run,
    submit_cutting_test,
    suspend_case_plan,
    transition_payload,
    validate_error,
    write_off_line,
)


def _service_day_with_two_measured_lines(api):
    """Build one service day whose two case lines carry pounds on every axis a
    reconciliation reads: required fill, actual fill, markdown pounds and
    discarded pounds.

    The ribeye item is priced off the measured cut-test basis and the ground
    item off a completed grind blend, so both lines value their discards at a
    real `active_price_per_lb_cents`.

    Ribeye chain, all recomputed from §3.1-§3.4: net weight 100.0 - 1.5 = 98.50
    lb, landed total 84000 + 2500 - 500 = 86000 cents. The bench posts 62.0 lb
    salable at 1450, 12.0 lb lean trim at 420, 6.5 lb extra-lean trim at 520 and
    18.0 lb fat and bone, so the market-value weight base is 62.0 x 1450 +
    12.0 x 420 + 6.5 x 520 = 98320. Per-line half-up allocation gives 78635 +
    4408 + 2956 = 85999, and the 1-cent remainder goes to the heaviest candidate
    line, the 62.0 lb salable cut, which therefore holds 78636 cents, i.e.
    1268.3226 cents a pound. That basis prices at 1989 (first pass 1865 selects
    the two-hundredths bump, second pass 1982, nudged up to end in 9).

    Ground chain: the two trim lots inherit 367.3333 and 454.7692 cents a pound
    from their cutting-test lines, and 12.0 lb of the first plus 3.0 lb of the
    second blend to 384.8205 cents a pound at 80.80 lean, which prices at 569.
    """
    department = seeded_department(api)
    department_id = department["id"]

    ribeye = create_retail_item(api, department_id)
    ground = create_ground_item(api, department_id)
    purchase = create_primal_purchase(api, department_id)

    propose_price(api, ribeye["id"], purchase["id"])

    test = create_cutting_test(
        api, purchase["id"], purchase["net_weight_lb"], purchase["version"]
    )
    add_cutting_test_line(
        api,
        test["id"],
        1,
        "RIBEYE_STEAK",
        "SALABLE_CUT",
        62.0,
        1450,
        retail_item_id=ribeye["id"],
    )
    lean_trim_line = add_cutting_test_line(
        api, test["id"], 2, "RIBEYE_TRIM_LEAN", "GRIND_TRIM", 12.0, 420, lean_pct=78.0
    )
    extra_lean_trim_line = add_cutting_test_line(
        api,
        test["id"],
        3,
        "RIBEYE_TRIM_EXTRA_LEAN",
        "GRIND_TRIM",
        6.5,
        520,
        lean_pct=92.0,
    )
    add_cutting_test_line(api, test["id"], 4, "RIBEYE_FAT_BONE", "FAT_BONE_LOSS", 18.0, 0)
    submit_cutting_test(api, test["id"])
    approve_cutting_test(api, test["id"])

    ribeye = read_retail_item(api, ribeye["id"])
    ribeye = activate_price_from_cutting_test(
        api, ribeye["id"], ribeye["version"], test["id"]
    )
    assert ribeye["active_price_per_lb_cents"] == 1989

    propose_price(api, ground["id"], purchase["id"])
    lot_a = create_trim_lot_from_line(
        api, department_id, "TL-A78", 12.0, lean_trim_line["id"]
    )
    lot_b = create_trim_lot_from_line(
        api, department_id, "TL-B92", 6.5, extra_lean_trim_line["id"]
    )
    run = create_grind_run(
        api,
        department_id,
        ground["id"],
        "2026-08-06T06:00:00Z",
        "2026-08-06T07:00:00Z",
        declared_coo="USA",
        target_lean_pct=81.0,
    )
    add_grind_input(api, run["id"], lot_a["id"], 1, 12.0)
    add_grind_input(api, run["id"], lot_b["id"], 2, 3.0)
    start_grind_run(api, run["id"])
    complete_grind_run(api, run["id"])

    ground = read_retail_item(api, ground["id"])
    ground = activate_price_from_grind_run(api, ground["id"], ground["version"], run["id"])
    assert ground["active_price_per_lb_cents"] == 569

    plan = create_case_plan(api, department_id, "2026-08-05")
    ribeye_line = add_case_plan_line(api, plan["id"], ribeye["id"], 1, 4, 30.0)
    ground_line = add_case_plan_line(api, plan["id"], ground["id"], 2, 5, 40.0)
    # 4 whole-muscle facings give 24.00 presentation pounds against demand 34.50
    # and a five-day carry cap of 45.00, so the model asks for 34.50; 5 ground
    # facings give 20.00 against demand 46.00 and a two-day carry cap of 24.00,
    # so the model asks for 24.00.
    assert ribeye_line["required_fill_lb"] == pytest.approx(34.50, abs=0.01)
    assert ground_line["required_fill_lb"] == pytest.approx(24.00, abs=0.01)
    publish_case_plan(api, plan["id"])

    fill_line(api, ribeye_line["id"], 34.0)
    fill_line(api, ground_line["id"], 24.0)
    # The ribeye floor is round_half_up(1268.3226 x 1.10) = 1395, so a markdown
    # exactly at the floor is accepted.
    mark_down_line(api, ribeye_line["id"], 2.0, 1395)
    write_off_line(api, ribeye_line["id"], 1.0)
    write_off_line(api, ground_line["id"], 0.5)

    return {
        "department": department,
        "purchase": purchase,
        "ribeye_item": ribeye,
        "ground_item": ground,
        "plan": plan,
        "ribeye_line": ribeye_line,
        "ground_line": ground_line,
    }


def test_yield_model_and_physical_count_bases_diverge_on_identical_case_lines(api):
    """The same service day drafted on both bases reports different expected and physical pounds, a different variance and a different tolerance verdict.

    "What the two bases disagree about is which pounds count as expected and
    which count as physical, and on identical line data they produce different
    answers."

    Design: Difficulty/dual_variant_calc/shrink_reconciliation_yield_model_vs_physical_count_divergence
    """
    context = _service_day_with_two_measured_lines(api)
    department_id = context["department"]["id"]

    ribeye_line = read_case_plan_line(api, context["ribeye_line"]["id"])
    ground_line = read_case_plan_line(api, context["ground_line"]["id"])
    assert ribeye_line["actual_fill_lb"] == pytest.approx(34.00, abs=0.01)
    assert ribeye_line["markdown_lb"] == pytest.approx(2.00, abs=0.01)
    assert ribeye_line["shrink_lb"] == pytest.approx(1.00, abs=0.01)
    assert ground_line["actual_fill_lb"] == pytest.approx(24.00, abs=0.01)
    assert ground_line["shrink_lb"] == pytest.approx(0.50, abs=0.01)

    yield_model = draft_reconciliation(
        api, department_id, "2026-08-05", "2026-08-05", basis="YIELD_MODEL"
    )
    physical_count = draft_reconciliation(
        api, department_id, "2026-08-05", "2026-08-05", basis="PHYSICAL_COUNT"
    )
    assert_shrink_reconciliation(yield_model)
    assert_shrink_reconciliation(physical_count)

    # The yield model measures the pounds that arrived against the pounds the
    # model asked for: 34.00 + 24.00 = 58.00 against 34.50 + 24.00 = 58.50, so
    # the shortfall is 0.50 lb and -0.50 / 58.50 rounds to -0.0085.
    assert yield_model["basis"] == "YIELD_MODEL"
    assert yield_model["expected_salable_lb"] == pytest.approx(58.50, abs=0.01)
    assert yield_model["physical_salable_lb"] == pytest.approx(58.00, abs=0.01)
    assert yield_model["variance_lb"] == pytest.approx(-0.50, abs=0.01)
    assert yield_model["variance_pct"] == pytest.approx(-0.0085, abs=0.0001)
    assert yield_model["within_tolerance"] is True
    assert yield_model["status"] == "DRAFT"

    # The physical count measures what stayed salable against what was put in
    # the case: (34.00 - 2.00 - 1.00) + (24.00 - 0.00 - 0.50) = 54.50 against
    # 58.00, so the shortfall is 3.50 lb and -3.50 / 58.00 rounds to -0.0603.
    assert physical_count["basis"] == "PHYSICAL_COUNT"
    assert physical_count["expected_salable_lb"] == pytest.approx(58.00, abs=0.01)
    assert physical_count["physical_salable_lb"] == pytest.approx(54.50, abs=0.01)
    assert physical_count["variance_lb"] == pytest.approx(-3.50, abs=0.01)
    assert physical_count["variance_pct"] == pytest.approx(-0.0603, abs=0.0001)
    assert physical_count["within_tolerance"] is False
    assert physical_count["status"] == "DRAFT"

    # Same lines, different books: the model basis is 58.50 expected pounds
    # where the count basis is 58.00, and the count basis is 3.00 lb lighter on
    # the physical side because markdowns and discards come off it.
    assert yield_model["expected_salable_lb"] != physical_count["expected_salable_lb"]
    assert yield_model["physical_salable_lb"] != physical_count["physical_salable_lb"]
    assert yield_model["variance_pct"] != physical_count["variance_pct"]
    # The department's tolerance is 0.015, which 0.0085 clears and 0.0603 does not.
    assert context["department"]["shrink_tolerance_pct"] == pytest.approx(0.015, abs=0.0001)


def test_reconciliation_dollar_columns_are_basis_independent_and_round_per_line(api):
    """The markdown give-up and the retail value of discarded pounds come out identical on both bases, with the discard value rounded half up one line at a time.

    "The row also carries two dollar figures: `markdown_dollars_cents` is the
    sum of each scope line's `markdown_dollars_cents`, and `shrink_dollars_cents`
    is the retail value of the discarded pounds, computed by multiplying each
    scope line's `shrink_lb` by its item's `active_price_per_lb_cents` and
    rounding half up to a whole cent **per line**, then summing those per-line
    values."

    Design: Difficulty/dual_variant_calc/shrink_reconciliation_yield_model_vs_physical_count_divergence
    """
    context = _service_day_with_two_measured_lines(api)
    department_id = context["department"]["id"]

    # The single markdown event gave up 2.0 lb x (1989 - 1395) = 1188 cents.
    ribeye_line = read_case_plan_line(api, context["ribeye_line"]["id"])
    assert ribeye_line["markdown_dollars_cents"] == 1188

    yield_model = draft_reconciliation(
        api, department_id, "2026-08-05", "2026-08-05", basis="YIELD_MODEL"
    )
    physical_count = draft_reconciliation(
        api, department_id, "2026-08-05", "2026-08-05", basis="PHYSICAL_COUNT"
    )

    # Both dollar columns read the same line events whichever pounds the basis
    # chose to compare, so they agree across the two rows.
    assert yield_model["markdown_dollars_cents"] == 1188
    assert physical_count["markdown_dollars_cents"] == 1188

    # Discard value line by line: the ribeye line is 1.0 lb x 1989 = 1989 cents
    # exactly, and the ground line is 0.5 lb x 569 = 284.5 cents, which rounds
    # half up to 285. Summing the two rounded values gives 2274 — summing the
    # exact values first and rounding once would have given 2273.
    assert yield_model["shrink_dollars_cents"] == 2274
    assert physical_count["shrink_dollars_cents"] == 2274
    assert yield_model["shrink_dollars_cents"] == 1989 + 285
    assert yield_model["shrink_dollars_cents"] != 2273

    assert yield_model["markdown_dollars_cents"] == physical_count["markdown_dollars_cents"]
    assert yield_model["shrink_dollars_cents"] == physical_count["shrink_dollars_cents"]


def test_tolerance_verdict_decides_which_basis_posts_without_an_override(api):
    """Because the two bases land on opposite sides of the department's shrink tolerance, the yield-model row posts on its own while the physical-count row over the same lines needs a written excursion.

    "`within_tolerance` is `true` exactly when the absolute value of
    `variance_pct` is no greater than the department's `shrink_tolerance_pct` —
    a variance exactly at the tolerance is inside it."

    Design: Difficulty/dual_variant_calc/shrink_reconciliation_yield_model_vs_physical_count_divergence
    """
    context = _service_day_with_two_measured_lines(api)
    department_id = context["department"]["id"]

    yield_model = draft_reconciliation(
        api, department_id, "2026-08-05", "2026-08-05", basis="YIELD_MODEL"
    )
    physical_count = draft_reconciliation(
        api, department_id, "2026-08-05", "2026-08-05", basis="PHYSICAL_COUNT"
    )
    # -0.0085 is inside the 0.015 tolerance; -0.0603 is not.
    assert yield_model["within_tolerance"] is True
    assert physical_count["within_tolerance"] is False

    # The primal was cut-tested and received on 2026-08-05, inside the period.
    purchase_before = read_primal_purchase(api, context["purchase"]["id"])
    assert purchase_before["status"] == "CUT_TESTED"

    posted = post_reconciliation(api, yield_model["id"])
    assert posted["status"] == "POSTED"
    assert posted["posted_by_user_id"] == MANAGER["X-User-ID"]
    assert read_primal_purchase(api, context["purchase"]["id"])["status"] == "RECONCILED"

    refused = api.transition_shrink_reconciliation(
        physical_count["id"], transition_payload("POST"), MANAGER
    )
    validate_error(refused, "ERR_SHRINK_EXCEEDS_TOLERANCE", 422)
    assert read_reconciliation(api, physical_count["id"])["status"] == "DRAFT"

    overridden = post_reconciliation(
        api,
        physical_count["id"],
        override_reason="markdown and discard pounds accepted by the store director",
    )
    assert overridden["status"] == "POSTED"
    assert overridden["within_tolerance"] is False
    assert overridden["variance_pct"] == pytest.approx(-0.0603, abs=0.0001)


def test_reconciliation_scope_leaves_an_unpublished_service_day_out(api):
    """A case plan still sitting in draft inside the period contributes none of its required or actual pounds to the reconciliation.

    "Plans in `DRAFT` are excluded, and plans in `SUSPENDED` are excluded too —
    although in practice a suspended plan inside the period blocks the posting
    outright rather than being quietly skipped."

    Design: Corner/calculations/shrink_reconciliation_scope_excludes_draft_plans
    """
    department = seeded_department(api)
    department_id = department["id"]
    ribeye = create_retail_item(api, department_id)
    purchase = create_primal_purchase(api, department_id)
    ribeye = propose_price(api, ribeye["id"], purchase["id"])
    assert ribeye["price_status"] == "PROPOSED"
    assert ribeye["active_price_per_lb_cents"] == 2149

    published_plan = create_case_plan(api, department_id, "2026-08-05")
    published_line = add_case_plan_line(
        api, published_plan["id"], ribeye["id"], 1, 4, 30.0
    )
    assert published_line["required_fill_lb"] == pytest.approx(34.50, abs=0.01)
    publish_case_plan(api, published_plan["id"])
    fill_line(api, published_line["id"], 34.0)

    # A second service day inside the same period is planned but never
    # published, so it never becomes part of the books.
    draft_plan = create_case_plan(api, department_id, "2026-08-06")
    draft_line = add_case_plan_line(api, draft_plan["id"], ribeye["id"], 1, 2, 10.0)
    assert read_case_plan(api, draft_plan["id"])["plan_status"] == "DRAFT"
    # Two whole-muscle facings give 12.00 presentation pounds against demand
    # 11.50 and a five-day carry cap of 15.00, so the model asks for 12.00.
    assert draft_line["required_fill_lb"] == pytest.approx(12.00, abs=0.01)
    assert draft_line["actual_fill_lb"] == pytest.approx(0.00, abs=0.01)

    reconciliation = draft_reconciliation(
        api, department_id, "2026-08-01", "2026-08-07", basis="YIELD_MODEL"
    )
    assert_shrink_reconciliation(reconciliation)

    # Only the published day counts: 34.50 required and 34.00 filled, not the
    # 46.50 required and 34.00 filled the draft day would have added.
    assert reconciliation["expected_salable_lb"] == pytest.approx(34.50, abs=0.01)
    assert reconciliation["expected_salable_lb"] != pytest.approx(46.50, abs=0.01)
    assert reconciliation["physical_salable_lb"] == pytest.approx(34.00, abs=0.01)
    assert reconciliation["variance_lb"] == pytest.approx(-0.50, abs=0.01)
    # -0.50 / 34.50 rounds half up to -0.0145, inside the 0.015 tolerance; over
    # the wider 46.50 base the shortfall would have been -12.50 / 46.50.
    assert reconciliation["variance_pct"] == pytest.approx(-0.0145, abs=0.0001)
    assert reconciliation["within_tolerance"] is True
    assert reconciliation["markdown_dollars_cents"] == 0
    assert reconciliation["shrink_dollars_cents"] == 0
    assert reconciliation["status"] == "DRAFT"


def test_suspended_service_day_reports_ahead_of_the_missing_tolerance_override(api):
    """A posting that both covers a suspended service day (rung 33) and sits outside tolerance with no override (rung 40) reports the suspended-plan rung, the lower of the two.

    "No case plan of the department whose `service_date` falls inside the period
    may sit in `plan_status` `SUSPENDED`, or the posting is refused with
    `ERR_PERIOD_HAS_SUSPENDED_PLAN` — the department must settle its cold-chain
    business before it settles its books."

    Design: Corner/validations/suspended_plan_in_the_period_outranks_the_tolerance_override
    """
    department = seeded_department(api)
    department_id = department["id"]
    ribeye = create_retail_item(api, department_id)
    purchase = create_primal_purchase(api, department_id)
    ribeye = propose_price(api, ribeye["id"], purchase["id"])

    plan = create_case_plan(api, department_id, "2026-08-05")
    line = add_case_plan_line(api, plan["id"], ribeye["id"], 1, 4, 30.0)
    assert line["required_fill_lb"] == pytest.approx(34.50, abs=0.01)
    publish_case_plan(api, plan["id"])
    # The case is filled well short of what the model asked for, which puts the
    # yield-model variance far outside the 0.015 tolerance.
    fill_line(api, line["id"], 20.0)

    reconciliation = draft_reconciliation(
        api, department_id, "2026-08-01", "2026-08-07", basis="YIELD_MODEL"
    )
    assert reconciliation["expected_salable_lb"] == pytest.approx(34.50, abs=0.01)
    assert reconciliation["physical_salable_lb"] == pytest.approx(20.00, abs=0.01)
    assert reconciliation["variance_lb"] == pytest.approx(-14.50, abs=0.01)
    # -14.50 / 34.50 rounds half up to -0.4203.
    assert reconciliation["variance_pct"] == pytest.approx(-0.4203, abs=0.0001)
    assert reconciliation["within_tolerance"] is False

    # With every plan in the period published, only the tolerance gate bites.
    tolerance_only = api.transition_shrink_reconciliation(
        reconciliation["id"], transition_payload("POST"), MANAGER
    )
    validate_error(tolerance_only, "ERR_SHRINK_EXCEEDS_TOLERANCE", 422)

    # Suspending the service day violates the earlier gate as well, and the
    # earlier gate is the one the caller hears about.
    assert suspend_case_plan(api, plan["id"])["plan_status"] == "SUSPENDED"
    both_violated = api.transition_shrink_reconciliation(
        reconciliation["id"], transition_payload("POST"), MANAGER
    )
    validate_error(both_violated, "ERR_PERIOD_HAS_SUSPENDED_PLAN", 422)

    still_draft = read_reconciliation(api, reconciliation["id"])
    assert still_draft["status"] == "DRAFT"
    assert still_draft["within_tolerance"] is False

    # Settle the cold-chain business first, then the tolerance gate is the only
    # thing left and an override clears it.
    assert resume_case_plan(api, plan["id"])["plan_status"] == "PUBLISHED"
    excursion = "case reset after a compressor repair; shortfall accepted by the store director"
    posted = get_success_data(
        api.transition_shrink_reconciliation(
            reconciliation["id"],
            transition_payload("POST", override_reason=excursion),
            MANAGER,
        ),
        200,
    )
    assert posted["status"] == "POSTED"
    assert posted["override_reason"] == excursion
    assert posted["posted_by_user_id"] == MANAGER["X-User-ID"]
    # Nothing was cut-tested in this period, so no purchase closes on the post.
    assert read_primal_purchase(api, purchase["id"])["status"] == "RECEIVED"
    assert read_reconciliation(api, reconciliation["id"], ANALYST)["status"] == "POSTED"
