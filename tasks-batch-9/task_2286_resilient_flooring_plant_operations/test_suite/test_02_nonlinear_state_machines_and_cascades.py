"""Cyclic lifecycles and multi-hop cascades of the plant-operations API.

These tests walk the non-linear edges of the recipe review loop (PRD §3.1) and
the laboratory retest loop (PRD §3.4), and they follow the deep cascades the PRD
declares: a raw-material restriction reaching from the material library through
recipes, SKUs, batches and allocation lines to the owning allocation (PRD §3.1,
§3.5, §3.7, §3.8), a design-grant termination running the same chain from the
licence side (PRD §3.2), a batch scrap stepping a filled allocation backwards
(PRD §3.7, §3.8), and a failing laboratory measurement collapsing certification,
aborting a planned run and compensating the licensed-volume ledger (PRD §3.4,
§3.6).
"""

from test_helpers import (
    CASCADE_HELD_BY_USER_ID,
    CLOCK_BOOT_UTC,
    HOLD_REASON_SKU_ON_HOLD,
    PLANT_ADMIN,
    PRODUCTION_PLANNER,
    QA_TECHNICIAN,
    QA_TECHNICIAN_B,
    TECHNICAL_DIRECTOR,
    FORMULATOR,
    ApiErrorId,
    add_component,
    assert_version_advanced,
    assert_version_unchanged,
    batch_of_run,
    begin_testing,
    build_released_sku,
    build_sku,
    build_stock_batch,
    complete_run,
    create_allocation,
    create_distributor,
    create_formulation,
    create_panel,
    create_press_line,
    create_raw_material,
    create_run,
    fill_allocation,
    hold_status_payload,
    license_status_payload,
    raw_material_status_payload,
    review_decision_payload,
    set_clock,
    set_qc_disposition,
    setup_run,
    start_panel,
    start_run,
    test_result_payload as measurement_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def _component_id_for_material(api, formulation_id, raw_material_id):
    """Read back a recipe's component row for one material (PRD §3.1)."""
    rows, _ = validate_paginated(
        api.list_formulation_components(formulation_id, FORMULATOR, params={"limit": 100})
    )
    matching = [row for row in rows if row["raw_material_id"] == raw_material_id]
    assert len(matching) == 1, (
        f"expected exactly one component dosing {raw_material_id}, got {matching}"
    )
    return matching[0]


# ---------------------------------------------------------------------------
# The DRAFT -> UNDER_REVIEW -> REJECTED -> DRAFT recipe loop.
# ---------------------------------------------------------------------------


def test_formulation_rejection_returns_to_draft_on_component_add_without_resetting_count(
    api,
):
    """A rejection counts once and adding a component reopens the recipe as DRAFT.

    "Rejection takes the recipe `UNDER_REVIEW → REJECTED` and increments
    `rejection_count` by one; nothing else moves, and the recipe remains
    editable, which is how the revision loop closes."
    "Either edit applied to a `REJECTED` recipe returns it to `DRAFT`, closing
    the revision loop `DRAFT → UNDER_REVIEW → REJECTED → DRAFT`; the recipe's
    `rejection_count` is **not** reset by that return."
    "A newly created recipe is `DRAFT` with `revision` 1, `cost_basis` `LIVE`,
    `rejection_count` and `open_revision_count` both 0, and
    `authored_by_user_id` set to the acting `X-User-ID`."
    "It is permitted only from `DRAFT`, taking the recipe
    `DRAFT → UNDER_REVIEW`, and it stamps `submitted_by_user_id` with the acting
    user."

    Design: Difficulty/non_linear_state_machine/formulation_rejected_to_draft_revision_loop_preserves_rejection_count
    """
    set_clock(api, CLOCK_BOOT_UTC)
    resin = create_raw_material(api, "RM-RESIN")
    stabiliser = create_raw_material(api, "RM-STAB")
    recipe = create_formulation(api, "F-CYC")
    assert recipe["status"] == "DRAFT"
    assert recipe["rejection_count"] == 0
    add_component(api, recipe["id"], resin["id"], 100)

    submitted = validate_success(api.submit_formulation(recipe["id"], FORMULATOR))
    assert submitted["status"] == "UNDER_REVIEW"

    rejected = validate_success(
        api.review_formulation(
            recipe["id"],
            review_decision_payload("REJECT", review_note="no stabiliser package"),
            TECHNICAL_DIRECTOR,
        )
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_count"] == 1

    add_component(api, recipe["id"], stabiliser["id"], 3)

    reopened = validate_success(api.get_formulation(recipe["id"], FORMULATOR))
    assert reopened["status"] == "DRAFT"
    assert reopened["rejection_count"] == 1
    assert reopened["revision"] == 1
    assert reopened["open_revision_count"] == 0


def test_formulation_second_rejection_counts_two_and_component_delete_reopens_draft(api):
    """Twice round the loop leaves rejection_count at 2, and a delete also reopens DRAFT.

    "Rejection takes the recipe `UNDER_REVIEW → REJECTED` and increments
    `rejection_count` by one; nothing else moves, and the recipe remains
    editable, which is how the revision loop closes."
    "Removing a component is permitted from the same states and, like adding
    one, returns the recomputed parent recipe."
    "Either edit applied to a `REJECTED` recipe returns it to `DRAFT`, closing
    the revision loop `DRAFT → UNDER_REVIEW → REJECTED → DRAFT`; the recipe's
    `rejection_count` is **not** reset by that return."
    "The four category subtotals — `resin_phr`, `plasticizer_phr`, `filler_phr`
    and `stabilizer_phr` — are the sums of the `phr` of the components whose
    material sits in the corresponding category, each rounded half up to two
    decimal places, and `total_phr` is the sum of `phr` across all components,
    likewise at two decimal places."

    Design: Difficulty/non_linear_state_machine/formulation_rejected_to_draft_revision_loop_preserves_rejection_count
    """
    set_clock(api, CLOCK_BOOT_UTC)
    resin = create_raw_material(api, "RM-RESIN")
    stabiliser = create_raw_material(api, "RM-STAB")
    recipe = create_formulation(api, "F-CYC")
    add_component(api, recipe["id"], resin["id"], 100)

    validate_success(api.submit_formulation(recipe["id"], FORMULATOR))
    validate_success(
        api.review_formulation(
            recipe["id"],
            review_decision_payload("REJECT", review_note="no stabiliser package"),
            TECHNICAL_DIRECTOR,
        )
    )
    add_component(api, recipe["id"], stabiliser["id"], 3)
    stab_component = _component_id_for_material(api, recipe["id"], stabiliser["id"])

    validate_success(api.submit_formulation(recipe["id"], FORMULATOR))
    second_rejection = validate_success(
        api.review_formulation(
            recipe["id"],
            review_decision_payload(
                "REJECT", review_note="stabiliser dosage above target cost"
            ),
            TECHNICAL_DIRECTOR,
        )
    )
    assert second_rejection["status"] == "REJECTED"
    assert second_rejection["rejection_count"] == 2

    validate_success(
        api.delete_formulation_component(
            recipe["id"], stab_component["id"], FORMULATOR
        )
    )

    reopened = validate_success(api.get_formulation(recipe["id"], FORMULATOR))
    assert reopened["status"] == "DRAFT"
    assert reopened["rejection_count"] == 2
    assert reopened["total_phr"] == 100.00
    assert reopened["resin_phr"] == 100.00
    assert reopened["stabilizer_phr"] == 0.00


def test_formulation_approved_after_two_rejections_keeps_count_and_revision_one(api):
    """Approval after two rejections reads count 2, revision 1 and pinned costs.

    "Rejection takes the recipe `UNDER_REVIEW → REJECTED` and increments
    `rejection_count` by one; nothing else moves, and the recipe remains
    editable, which is how the revision loop closes."
    "Either edit applied to a `REJECTED` recipe returns it to `DRAFT`, closing
    the revision loop `DRAFT → UNDER_REVIEW → REJECTED → DRAFT`; the recipe's
    `rejection_count` is **not** reset by that return."
    "On approval the recipe moves `UNDER_REVIEW → APPROVED` and four things are
    written."
    "First, **cost pinning**: every component of the recipe receives
    `material_cost_snapshot_cents` set to its material's `cost_per_kg_cents` as
    of that instant, and `snapshot_at` set to the logical clock."
    "Second, the recipe's `cost_basis` flips to `PINNED` and
    `blended_cost_per_kg_cents` is re-derived from those snapshots rather than
    from live material costs."
    "Add those products together, divide the total by `total_phr`, and round
    half up to a whole cent."
    "Those three indices are weighted at forty percent, thirty-five percent and
    twenty-five percent respectively and added together."
    "The `indentation_resistance_class` is derived from the blended indentation
    index **alone**, never from `performance_score`: the class is `CLASS_34_43`
    when that index is at least 88.00, `CLASS_33_42` when it is at least 70.00
    but below 88.00, and `CLASS_23_31` otherwise."
    "The parent's `open_revision_count` is incremented and its `version`
    advanced, but the parent **stays** `APPROVED`; it only becomes `SUPERSEDED`
    when the revision is itself approved."

    Design: Difficulty/non_linear_state_machine/formulation_rejected_to_draft_revision_loop_preserves_rejection_count
    """
    set_clock(api, CLOCK_BOOT_UTC)
    resin = create_raw_material(api, "RM-RESIN")
    stabiliser = create_raw_material(api, "RM-STAB")
    recipe = create_formulation(api, "F-CYC")
    add_component(api, recipe["id"], resin["id"], 100)

    validate_success(api.submit_formulation(recipe["id"], FORMULATOR))
    validate_success(
        api.review_formulation(
            recipe["id"],
            review_decision_payload("REJECT", review_note="no stabiliser package"),
            TECHNICAL_DIRECTOR,
        )
    )
    add_component(api, recipe["id"], stabiliser["id"], 3)
    stab_component = _component_id_for_material(api, recipe["id"], stabiliser["id"])
    validate_success(api.submit_formulation(recipe["id"], FORMULATOR))
    validate_success(
        api.review_formulation(
            recipe["id"],
            review_decision_payload(
                "REJECT", review_note="stabiliser dosage above target cost"
            ),
            TECHNICAL_DIRECTOR,
        )
    )
    validate_success(
        api.delete_formulation_component(
            recipe["id"], stab_component["id"], FORMULATOR
        )
    )
    validate_success(api.submit_formulation(recipe["id"], FORMULATOR))

    approved = validate_success(
        api.review_formulation(
            recipe["id"], review_decision_payload("APPROVE"), TECHNICAL_DIRECTOR
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["rejection_count"] == 2
    assert approved["performance_score"] == 89.50
    assert approved["blended_cost_per_kg_cents"] == 180
    assert approved["total_phr"] == 100.00
    assert approved["resin_phr"] == 100.00
    assert approved["indentation_resistance_class"] == "CLASS_34_43"
    assert approved["revision"] == 1
    assert approved["open_revision_count"] == 0
    assert approved["cost_basis"] == "PINNED"

    resin_component = _component_id_for_material(api, recipe["id"], resin["id"])
    assert resin_component["material_cost_snapshot_cents"] == 180


# ---------------------------------------------------------------------------
# The IN_TEST -> RETEST_REQUIRED -> IN_TEST panel loop and its bound.
# ---------------------------------------------------------------------------


def test_marginal_indentation_at_edge_parks_panel_in_retest_required_at_count_one(api):
    """A measurement exactly on the marginal edge parks the panel for retest.

    "Every panel requires `RESIDUAL_INDENTATION` and
    `DIMENSIONAL_STABILITY_HEAT`."
    "A new panel is `SCHEDULED` with `attempt_no` 1, `retest_count` 0,
    `void_reason` and `started_by_user_id` null, and `required_test_types`
    derived from the SKU."
    "`RESIDUAL_INDENTATION` is measured in `mm` and lower is better, with a
    limit of 0.10 when the SKU's recipe sits in `CLASS_34_43`, 0.20 for
    `CLASS_33_42` and 0.30 for `CLASS_23_31`."
    "For a lower-is-better test the marginal edge is the limit multiplied by
    1.05, rounded half up to four decimal places; a `measured_value` no greater
    than the limit is `PASS`, a value above the limit but no greater than the
    marginal edge is `MARGINAL`, and anything larger is `FAIL`."
    "Both limits are inclusive, so a reading exactly on the limit passes, and a
    reading exactly on the marginal edge is `MARGINAL` while one increment
    beyond it fails."
    "`DIMENSIONAL_STABILITY_HEAT` is measured in `PCT` and lower is better, with
    a limit of 0.15 for `CLICK_LOCK_SPC` and `CLICK_LOCK_WPC` constructions and
    0.25 for every other construction."
    "If coverage is complete, no outcome is `FAIL`, and at least one is
    `MARGINAL`, the panel moves `IN_TEST → RETEST_REQUIRED` and `retest_count`
    is incremented by one — unconditionally, with no cap applied at this edge."
    "A restart from `RETEST_REQUIRED` additionally increments `attempt_no` by
    one; measurements recorded under earlier attempts remain immutable but no
    longer count toward coverage."

    Design: Difficulty/non_linear_state_machine/test_panel_marginal_retest_loop_terminates_at_max_retests
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_sku(api)
    begin_testing(api, built["sku"]["id"])
    panel = create_panel(api, built["sku"]["id"], "TP-RT")
    assert panel["required_test_types"] == [
        "RESIDUAL_INDENTATION",
        "DIMENSIONAL_STABILITY_HEAT",
    ]
    assert panel["attempt_no"] == 1
    assert panel["retest_count"] == 0

    started = validate_success(api.start_test_panel(panel["id"], QA_TECHNICIAN))
    assert started["status"] == "IN_TEST"
    assert started["attempt_no"] == 1

    indentation = validate_success(
        api.record_test_result(
            panel["id"],
            measurement_payload("RESIDUAL_INDENTATION", 0.1050),
            QA_TECHNICIAN,
        ),
        201,
    )
    assert indentation["spec_limit"] == 0.10
    assert indentation["unit"] == "mm"
    assert indentation["outcome"] == "MARGINAL"
    assert indentation["attempt_no"] == 1

    stability = validate_success(
        api.record_test_result(
            panel["id"],
            measurement_payload("DIMENSIONAL_STABILITY_HEAT", 0.12),
            QA_TECHNICIAN,
        ),
        201,
    )
    assert stability["spec_limit"] == 0.25
    assert stability["outcome"] == "PASS"

    parked = validate_success(api.get_test_panel(panel["id"], QA_TECHNICIAN))
    assert parked["status"] == "RETEST_REQUIRED"
    assert parked["retest_count"] == 1
    assert parked["attempt_no"] == 1

    restarted = validate_success(api.start_test_panel(panel["id"], QA_TECHNICIAN))
    assert restarted["status"] == "IN_TEST"
    assert restarted["attempt_no"] == 2
    assert restarted["retest_count"] == 1


def test_three_marginal_attempts_walk_attempt_no_and_retest_count_to_three(api):
    """Three identical marginal rounds walk attempt_no and retest_count to 3.

    "Starting a panel takes it `SCHEDULED → IN_TEST` or
    `RETEST_REQUIRED → IN_TEST`; the states `PASSED`, `FAILED` and `VOIDED`
    accept nothing, and a start from any of them is `ERR_INVALID_PANEL_STATE`
    (HTTP 409)."
    "A restart from `RETEST_REQUIRED` additionally increments `attempt_no` by
    one; measurements recorded under earlier attempts remain immutable but no
    longer count toward coverage."
    "If coverage is complete, no outcome is `FAIL`, and at least one is
    `MARGINAL`, the panel moves `IN_TEST → RETEST_REQUIRED` and `retest_count`
    is incremented by one — unconditionally, with no cap applied at this edge."
    "A `MARGINAL` never fails a panel; the only cap in the retest loop lives on
    the restart, as described above."

    Design: Difficulty/non_linear_state_machine/test_panel_marginal_retest_loop_terminates_at_max_retests
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_sku(api)
    begin_testing(api, built["sku"]["id"])
    panel = create_panel(api, built["sku"]["id"], "TP-RT")

    for expected_attempt_no, expected_retest_count in ((1, 1), (2, 2), (3, 3)):
        started = validate_success(api.start_test_panel(panel["id"], QA_TECHNICIAN))
        assert started["attempt_no"] == expected_attempt_no
        assert started["status"] == "IN_TEST"

        marginal = validate_success(
            api.record_test_result(
                panel["id"],
                measurement_payload("RESIDUAL_INDENTATION", 0.1050),
                QA_TECHNICIAN,
            ),
            201,
        )
        assert marginal["outcome"] == "MARGINAL"
        assert marginal["attempt_no"] == expected_attempt_no

        passing = validate_success(
            api.record_test_result(
                panel["id"],
                measurement_payload("DIMENSIONAL_STABILITY_HEAT", 0.12),
                QA_TECHNICIAN,
            ),
            201,
        )
        assert passing["outcome"] == "PASS"

        looped = validate_success(api.get_test_panel(panel["id"], QA_TECHNICIAN))
        assert looped["status"] == "RETEST_REQUIRED"
        assert looped["retest_count"] == expected_retest_count
        assert looped["attempt_no"] == expected_attempt_no


def test_fourth_panel_start_refused_with_retest_limit_and_leaves_panel_parked(api):
    """The fourth start of the same panel is refused and nothing moves.

    "A restart is refused with `ERR_RETEST_LIMIT_EXCEEDED` (HTTP 422) once
    `retest_count` has passed the two permitted retests — that is, once
    `retest_count` is greater than 2, which happens after three attempts have
    each ended marginal."
    "A panel parked that way stays in `RETEST_REQUIRED`, and voiding is its only
    exit."
    "A restart from `RETEST_REQUIRED` additionally increments `attempt_no` by
    one; measurements recorded under earlier attempts remain immutable but no
    longer count toward coverage."
    "Two of those resolutions reach the SKU."
    "A panel that reaches `FAILED` collapses the SKU's certification:
    `TESTING → UNCERTIFIED`, or `PROVISIONAL → SUSPENDED`, or
    `CERTIFIED → SUSPENDED`."

    Design: Difficulty/non_linear_state_machine/test_panel_marginal_retest_loop_terminates_at_max_retests
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_sku(api)
    begin_testing(api, built["sku"]["id"])
    panel = create_panel(api, built["sku"]["id"], "TP-RT")

    for _ in range(3):
        start_panel(api, panel["id"])
        validate_success(
            api.record_test_result(
                panel["id"],
                measurement_payload("RESIDUAL_INDENTATION", 0.1050),
                QA_TECHNICIAN,
            ),
            201,
        )
        validate_success(
            api.record_test_result(
                panel["id"],
                measurement_payload("DIMENSIONAL_STABILITY_HEAT", 0.12),
                QA_TECHNICIAN,
            ),
            201,
        )

    parked = validate_success(api.get_test_panel(panel["id"], QA_TECHNICIAN))
    assert parked["status"] == "RETEST_REQUIRED"
    assert parked["retest_count"] == 3
    assert parked["attempt_no"] == 3

    refused = api.start_test_panel(panel["id"], QA_TECHNICIAN)
    validate_error(refused, ApiErrorId.RETEST_LIMIT_EXCEEDED.value)

    after = validate_success(api.get_test_panel(panel["id"], QA_TECHNICIAN))
    assert after["status"] == "RETEST_REQUIRED"
    assert after["attempt_no"] == 3
    assert after["retest_count"] == 3

    _, results_meta = validate_paginated(
        api.list_test_results(panel["id"], QA_TECHNICIAN, params={"limit": 100})
    )
    assert results_meta["total_count"] == 6

    sku = validate_success(api.get_product_sku(built["sku"]["id"], PLANT_ADMIN))
    assert sku["certification_status"] == "TESTING"


# ---------------------------------------------------------------------------
# FILLED -> PARTIALLY_FILLED -> OPEN driven only by batch scraps.
# ---------------------------------------------------------------------------


def _two_batch_filled_allocation(api):
    """Two IN_STOCK batches (100.00 then 300.00) and a FILLED 300.00 allocation."""
    built = build_released_sku(api)
    sku_id = built["sku"]["id"]
    press_line = create_press_line(api)

    run_x = create_run(
        api,
        sku_id,
        press_line["id"],
        run_code="RUN-SX",
        planned_start_utc="2026-08-01T01:00:00Z",
        planned_end_utc="2026-08-01T03:00:00Z",
        planned_quantity_sqm=100.00,
    )
    setup_run(api, run_x["id"])
    start_run(api, run_x["id"])
    complete_run(api, run_x["id"], 100.00)
    set_qc_disposition(api, run_x["id"], "RELEASED")
    batch_x = batch_of_run(api, run_x["id"])

    set_clock(api, "2026-08-01T03:30:00Z")
    run_y = create_run(
        api,
        sku_id,
        press_line["id"],
        run_code="RUN-SY",
        planned_start_utc="2026-08-01T05:00:00Z",
        planned_end_utc="2026-08-01T07:00:00Z",
        planned_quantity_sqm=300.00,
    )
    setup_run(api, run_y["id"])
    start_run(api, run_y["id"])
    complete_run(api, run_y["id"], 300.00)
    set_qc_disposition(api, run_y["id"], "RELEASED")
    batch_y = batch_of_run(api, run_y["id"])

    distributor = create_distributor(api)
    allocation = create_allocation(
        api,
        distributor["id"],
        sku_id,
        allocation_code="AL-S",
        requested_quantity_sqm=300.00,
        substitution_policy="STRICT_SKU",
    )
    filled = fill_allocation(
        api, allocation["id"], distributor["id"], allocation["version"]
    )
    assert filled["status"] == "FILLED"
    assert filled["allocated_quantity_sqm"] == 300.00
    return {
        "allocation": filled,
        "batch_x": batch_x,
        "batch_y": batch_y,
        "distributor": distributor,
    }


def test_first_batch_scrap_steps_filled_allocation_back_to_partially_filled(api):
    """Scrapping the second source batch steps FILLED back to PARTIALLY_FILLED.

    "Candidates are ordered by substitution kind first — exact matches ahead of
    underlayment upgrades, which are ahead of wear-layer upgrades — then by the
    batch's `created_at` ascending, then by `batch_code` ascending."
    "The first candidate is drained completely before the second is touched,
    even when the second alone would have covered the whole request."
    "`SCRAP` from `IN_STOCK` or `HELD` sets `available_quantity_sqm` to 0 and
    voids every `ACTIVE` line with `void_reason` `BATCH_SCRAPPED`, recomputing
    each owning allocation."
    "The reverse edges are driven by cascades rather than by requests."
    "When a batch is held or scrapped and voids one of an allocation's `ACTIVE`
    lines, the allocation recomputes `allocated_quantity_sqm` and
    `upgrade_cost_total_cents` and moves `FILLED → PARTIALLY_FILLED`; when the
    last `ACTIVE` line goes, both figures become 0 and the allocation moves
    `PARTIALLY_FILLED → OPEN`, completing the
    `OPEN → PARTIALLY_FILLED → FILLED → PARTIALLY_FILLED → OPEN` cycle."
    "Whenever this document says that a cascade "touches" a row, it means the
    row's `updated_at` is refreshed and its `version` is advanced by one."

    Design: Difficulty/non_linear_state_machine/allocation_filled_steps_backwards_to_open_on_successive_batch_scraps
    """
    set_clock(api, CLOCK_BOOT_UTC)
    state = _two_batch_filled_allocation(api)
    allocation = state["allocation"]
    batch_x = state["batch_x"]
    batch_y = state["batch_y"]

    validate_success(
        api.set_batch_hold_status(
            batch_y["id"],
            hold_status_payload("SCRAP", hold_reason="forklift damage in bay 4"),
            QA_TECHNICIAN_B,
        )
    )

    stepped = validate_success(api.get_allocation(allocation["id"], PLANT_ADMIN))
    assert stepped["status"] == "PARTIALLY_FILLED"
    assert stepped["allocated_quantity_sqm"] == 100.00
    assert_version_advanced(allocation, stepped)

    scrapped = validate_success(api.get_batch(batch_y["id"], QA_TECHNICIAN))
    assert scrapped["status"] == "SCRAPPED"
    assert scrapped["available_quantity_sqm"] == 0.00

    lines, meta = validate_paginated(
        api.list_allocation_lines(allocation["id"], PLANT_ADMIN, params={"limit": 100})
    )
    assert meta["total_count"] == 2
    by_batch = {row["batch_id"]: row for row in lines}
    voided = by_batch[batch_y["id"]]
    assert voided["status"] == "VOIDED"
    assert voided["void_reason"] == "BATCH_SCRAPPED"
    assert voided["quantity_sqm"] == 200.00
    surviving = by_batch[batch_x["id"]]
    assert surviving["status"] == "ACTIVE"
    assert surviving["quantity_sqm"] == 100.00


def test_second_batch_scrap_steps_allocation_back_to_open_with_both_lines_voided(api):
    """The second scrap empties the allocation and returns it to OPEN.

    "`SCRAP` from `IN_STOCK` or `HELD` sets `available_quantity_sqm` to 0 and
    voids every `ACTIVE` line with `void_reason` `BATCH_SCRAPPED`, recomputing
    each owning allocation."
    "When a batch is held or scrapped and voids one of an allocation's `ACTIVE`
    lines, the allocation recomputes `allocated_quantity_sqm` and
    `upgrade_cost_total_cents` and moves `FILLED → PARTIALLY_FILLED`; when the
    last `ACTIVE` line goes, both figures become 0 and the allocation moves
    `PARTIALLY_FILLED → OPEN`, completing the
    `OPEN → PARTIALLY_FILLED → FILLED → PARTIALLY_FILLED → OPEN` cycle."
    "The allocation's resulting `status` follows from the arithmetic: `FILLED`
    when `allocated_quantity_sqm` has reached `requested_quantity_sqm`,
    `PARTIALLY_FILLED` when it is above zero but short of the request, and
    `OPEN` when it is zero."
    "Each line's `upgrade_cost_delta_cents` is 0 when its `substitution_kind` is
    `EXACT`."

    Design: Difficulty/non_linear_state_machine/allocation_filled_steps_backwards_to_open_on_successive_batch_scraps
    """
    set_clock(api, CLOCK_BOOT_UTC)
    state = _two_batch_filled_allocation(api)
    allocation = state["allocation"]
    batch_x = state["batch_x"]
    batch_y = state["batch_y"]

    validate_success(
        api.set_batch_hold_status(
            batch_y["id"],
            hold_status_payload("SCRAP", hold_reason="forklift damage in bay 4"),
            QA_TECHNICIAN_B,
        )
    )
    partially = validate_success(api.get_allocation(allocation["id"], PLANT_ADMIN))
    assert partially["status"] == "PARTIALLY_FILLED"

    validate_success(
        api.set_batch_hold_status(
            batch_x["id"],
            hold_status_payload("SCRAP", hold_reason="water ingress in bay 1"),
            QA_TECHNICIAN_B,
        )
    )

    reopened = validate_success(api.get_allocation(allocation["id"], PLANT_ADMIN))
    assert reopened["status"] == "OPEN"
    assert reopened["allocated_quantity_sqm"] == 0.00
    assert reopened["upgrade_cost_total_cents"] == 0
    assert_version_advanced(partially, reopened)

    for batch_id in (batch_x["id"], batch_y["id"]):
        batch = validate_success(api.get_batch(batch_id, QA_TECHNICIAN))
        assert batch["status"] == "SCRAPPED"
        assert batch["available_quantity_sqm"] == 0.00

    lines, meta = validate_paginated(
        api.list_allocation_lines(allocation["id"], PLANT_ADMIN, params={"limit": 100})
    )
    assert meta["total_count"] == 2
    for row in lines:
        assert row["status"] == "VOIDED"
        assert row["void_reason"] == "BATCH_SCRAPPED"
        assert row["upgrade_cost_delta_cents"] == 0


# ---------------------------------------------------------------------------
# RawMaterial -> Formulation -> ProductSku -> Batch -> AllocationLine.
# ---------------------------------------------------------------------------


def test_raw_material_restriction_retires_recipe_and_suspends_holds_sku(api):
    """Restricting one material retires its recipe and collapses both SKU dimensions.

    "Moving a material to `RESTRICTED` starts the plant's deepest cascade."
    "Every recipe in `APPROVED` or `SUPERSEDED` that doses the material
    transitions to `RETIRED` (`APPROVED → RETIRED` or `SUPERSEDED → RETIRED`)."
    "Because those recipes are `RETIRED`, every SKU pinned to one of them whose
    `certification_status` is `TESTING`, `PROVISIONAL` or `CERTIFIED` moves to
    `SUSPENDED`, and every such SKU whose `commercial_status` is `RELEASED`
    moves to `HOLD`."
    "Whenever the SKU's recipe moves to `SUPERSEDED` or `RETIRED`, or its
    `version` ceases to equal the SKU's `pinned_formulation_version`,
    `pin_stale` becomes true."
    "Every row in that five-hop chain is touched."

    Design: Difficulty/transitive_cascade/raw_material_restriction_five_hop_cascade_to_allocation
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_released_sku(api)
    stabiliser_id = built["materials"]["RM-STAB"]["id"]
    resin_id = built["materials"]["RM-RESIN"]["id"]
    formulation_before = validate_success(
        api.get_formulation(built["formulation"]["id"], PLANT_ADMIN)
    )

    restricted = validate_success(
        api.set_raw_material_status(
            stabiliser_id, raw_material_status_payload("RESTRICTED"), PLANT_ADMIN
        )
    )
    assert restricted["status"] == "RESTRICTED"

    retired = validate_success(
        api.get_formulation(built["formulation"]["id"], PLANT_ADMIN)
    )
    assert retired["status"] == "RETIRED"
    assert_version_advanced(formulation_before, retired)

    sku = validate_success(api.get_product_sku(built["sku"]["id"], PLANT_ADMIN))
    assert sku["certification_status"] == "SUSPENDED"
    assert sku["commercial_status"] == "HOLD"
    assert sku["pin_stale"] is True

    untouched_material = validate_success(api.get_raw_material(resin_id, PLANT_ADMIN))
    assert untouched_material["status"] == "ACTIVE"


def test_raw_material_restriction_holds_batch_and_voids_line_restoring_area_to_stock(
    api,
):
    """The five-hop cascade returns 1200.00 sqm to stock and empties the allocation.

    "Because those SKUs went on hold, each of their batches in `IN_STOCK` moves
    to `HELD` with `hold_reason` recorded as `SKU_ON_HOLD`."
    "`IN_STOCK → HELD` records `held_by_user_id` as the acting user — or the
    string `system` when the transition arrived through a SKU-hold cascade
    rather than an operator action — and voids every `ACTIVE` allocation line on
    the batch with `void_reason` `BATCH_HELD`, adding each line's `quantity_sqm`
    back to `available_quantity_sqm` and stepping the owning allocations back as
    above."
    "Because those batches were held, every `ACTIVE` allocation line drawn on
    them becomes `VOIDED` with `void_reason` `BATCH_HELD`, each line's
    `quantity_sqm` is added back to its batch's `available_quantity_sqm`, and
    each owning allocation recomputes `allocated_quantity_sqm` and
    `upgrade_cost_total_cents` and steps back from `FILLED` to
    `PARTIALLY_FILLED`, or from `PARTIALLY_FILLED` to `OPEN` when its last
    active line is gone."
    "When a run completes with positive output, the batch is minted with a
    `batch_code` formed as the producing run's `run_code` followed by the suffix
    `-B1`, a `production_run_id` pointing at that run, a `sku_id` denormalised
    from it for stock selection, a `quantity_sqm` equal to the run's
    `actual_quantity_sqm` that never changes thereafter, an
    `available_quantity_sqm` of 0, and a `wear_layer_measured_mil` copied from
    the run's measurement — the reading that will later serve as warranty defect
    evidence."
    "Every row in that five-hop chain is touched."

    Design: Difficulty/transitive_cascade/raw_material_restriction_five_hop_cascade_to_allocation
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_stock_batch(api)
    distributor = create_distributor(api)
    allocation = create_allocation(
        api,
        distributor["id"],
        built["sku"]["id"],
        allocation_code="AL-C1",
        requested_quantity_sqm=1500.00,
        substitution_policy="STRICT_SKU",
    )
    filled = fill_allocation(
        api, allocation["id"], distributor["id"], allocation["version"]
    )
    assert filled["status"] == "PARTIALLY_FILLED"
    assert filled["allocated_quantity_sqm"] == 1200.00
    run_before = validate_success(
        api.get_production_run(built["run"]["id"], PRODUCTION_PLANNER)
    )

    validate_success(
        api.set_raw_material_status(
            built["materials"]["RM-STAB"]["id"],
            raw_material_status_payload("RESTRICTED"),
            PLANT_ADMIN,
        )
    )

    held = validate_success(api.get_batch(built["batch"]["id"], QA_TECHNICIAN))
    assert held["status"] == "HELD"
    assert held["hold_reason"] == HOLD_REASON_SKU_ON_HOLD
    assert held["held_by_user_id"] == CASCADE_HELD_BY_USER_ID
    assert held["available_quantity_sqm"] == 1200.00
    assert held["quantity_sqm"] == 1200.00

    lines, meta = validate_paginated(
        api.list_allocation_lines(allocation["id"], PLANT_ADMIN, params={"limit": 100})
    )
    assert meta["total_count"] == 1
    assert lines[0]["status"] == "VOIDED"
    assert lines[0]["void_reason"] == "BATCH_HELD"
    assert lines[0]["quantity_sqm"] == 1200.00

    reopened = validate_success(api.get_allocation(allocation["id"], PLANT_ADMIN))
    assert reopened["status"] == "OPEN"
    assert reopened["allocated_quantity_sqm"] == 0.00
    assert reopened["upgrade_cost_total_cents"] == 0
    assert_version_advanced(filled, reopened)

    run_after = validate_success(
        api.get_production_run(built["run"]["id"], PRODUCTION_PLANNER)
    )
    assert run_after["run_status"] == "COMPLETED"
    assert run_after["qc_disposition"] == "RELEASED"
    assert_version_unchanged(run_before, run_after)


# ---------------------------------------------------------------------------
# DesignLicense -> PrintFilm -> ProductSku -> Batch -> AllocationLine.
# ---------------------------------------------------------------------------


def test_license_termination_withdraws_film_and_suspends_sku_only_for_technical_director(
    api,
):
    """Only a TechnicalDirector may terminate, and termination withdraws the film.

    "One endpoint splits its authorisation by payload rather than by path:
    changing a design grant's status to `TERMINATED` is reserved to
    `TechnicalDirector`, while moving a grant to `ACTIVE` or `SUSPENDED` is
    reserved to `PlantAdmin`."
    "Both roles are nominally authorised for the endpoint, so the mismatch
    surfaces as `ERR_UNAUTHORIZED` (HTTP 403) after the general role check
    rather than before it."
    "Termination is a `TechnicalDirector` action reachable from either `ACTIVE`
    or `SUSPENDED`, and it runs four hops."
    "Every film on the grant moves to `WITHDRAWN`."
    "Every SKU on a withdrawn film whose `commercial_status` is `RELEASED` moves
    to `HOLD`, and every such SKU whose `certification_status` is `PROVISIONAL`
    or `CERTIFIED` moves to `SUSPENDED`."

    Design: Difficulty/transitive_cascade/license_termination_four_hop_cascade_to_allocation_line
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_released_sku(api)

    refused = api.set_license_status(
        built["license"]["id"], license_status_payload("TERMINATED"), PLANT_ADMIN
    )
    validate_error(refused, ApiErrorId.UNAUTHORIZED.value)
    still_active = validate_success(
        api.get_design_license(built["license"]["id"], PLANT_ADMIN)
    )
    assert still_active["status"] == "ACTIVE"

    terminated = validate_success(
        api.set_license_status(
            built["license"]["id"],
            license_status_payload("TERMINATED"),
            TECHNICAL_DIRECTOR,
        )
    )
    assert terminated["status"] == "TERMINATED"

    film = validate_success(api.get_print_film(built["film"]["id"], PLANT_ADMIN))
    assert film["status"] == "WITHDRAWN"

    sku = validate_success(api.get_product_sku(built["sku"]["id"], PLANT_ADMIN))
    assert sku["certification_status"] == "SUSPENDED"
    assert sku["commercial_status"] == "HOLD"

    recipe = validate_success(
        api.get_formulation(built["formulation"]["id"], PLANT_ADMIN)
    )
    assert recipe["status"] == "APPROVED"


def test_license_termination_holds_batch_and_voids_allocation_line_keeping_ledger(api):
    """Termination holds the batch, voids the line and leaves the royalty ledger.

    "Every `IN_STOCK` batch of those SKUs moves to `HELD` with `hold_reason`
    `SKU_ON_HOLD`."
    "And every `ACTIVE` allocation line on those batches becomes `VOIDED` with
    `void_reason` `BATCH_HELD`, its `quantity_sqm` returning to the batch's
    `available_quantity_sqm`, with each owning allocation recomputing
    `allocated_quantity_sqm` and stepping `FILLED → PARTIALLY_FILLED` or
    `PARTIALLY_FILLED → OPEN`."
    "Second, the licensed-volume ledger settles on an actual basis: the run's
    `planned_quantity_sqm` is subtracted from the grant's `reserved_volume_sqm`
    and the measured `actual_quantity_sqm` is added to its
    `consumed_volume_sqm`."
    "The run's `actual_quantity_sqm` is multiplied by the SKU's
    `royalty_basis_price_cents_per_sqm` and by the grant's `royalty_rate_bps`
    divided by 10000, and the product is rounded half up to a whole cent."
    "That integer is stored in the run's `royalty_accrued_cents` and added to
    the grant's `accrued_royalty_cents`, one run at a time, per the
    rounding-order rule of §2.6."

    Design: Difficulty/transitive_cascade/license_termination_four_hop_cascade_to_allocation_line
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_stock_batch(api)
    distributor = create_distributor(api)
    allocation = create_allocation(
        api,
        distributor["id"],
        built["sku"]["id"],
        allocation_code="AL-C2",
        requested_quantity_sqm=400.00,
        substitution_policy="STRICT_SKU",
    )
    filled = fill_allocation(
        api, allocation["id"], distributor["id"], allocation["version"]
    )
    assert filled["status"] == "FILLED"
    before = validate_success(api.get_batch(built["batch"]["id"], QA_TECHNICIAN))
    assert before["available_quantity_sqm"] == 800.00

    validate_success(
        api.set_license_status(
            built["license"]["id"],
            license_status_payload("TERMINATED"),
            TECHNICAL_DIRECTOR,
        )
    )

    held = validate_success(api.get_batch(built["batch"]["id"], QA_TECHNICIAN))
    assert held["status"] == "HELD"
    assert held["hold_reason"] == HOLD_REASON_SKU_ON_HOLD
    assert held["available_quantity_sqm"] == 1200.00

    lines, meta = validate_paginated(
        api.list_allocation_lines(allocation["id"], PLANT_ADMIN, params={"limit": 100})
    )
    assert meta["total_count"] == 1
    assert lines[0]["status"] == "VOIDED"
    assert lines[0]["void_reason"] == "BATCH_HELD"
    assert lines[0]["quantity_sqm"] == 400.00

    reopened = validate_success(api.get_allocation(allocation["id"], PLANT_ADMIN))
    assert reopened["status"] == "OPEN"
    assert reopened["allocated_quantity_sqm"] == 0.00
    assert_version_advanced(filled, reopened)

    utilization = validate_success(
        api.get_license_utilization(built["license"]["id"], PLANT_ADMIN)
    )
    assert utilization["consumed_volume_sqm"] == 1200.00
    assert utilization["accrued_royalty_cents"] == 126000


# ---------------------------------------------------------------------------
# TestResult -> TestPanel -> ProductSku -> ProductionRun -> licence ledger.
# ---------------------------------------------------------------------------


def test_failing_indentation_measurement_fails_panel_and_uncertifies_sku(api):
    """A single FAIL reading fails the panel at once and collapses certification.

    "`RESIDUAL_INDENTATION` is measured in `mm` and lower is better, with a
    limit of 0.10 when the SKU's recipe sits in `CLASS_34_43`, 0.20 for
    `CLASS_33_42` and 0.30 for `CLASS_23_31`."
    "For a lower-is-better test the marginal edge is the limit multiplied by
    1.05, rounded half up to four decimal places; a `measured_value` no greater
    than the limit is `PASS`, a value above the limit but no greater than the
    marginal edge is `MARGINAL`, and anything larger is `FAIL`."
    "The instant coverage completes, the panel resolves in one of three ways,
    and a `FAIL` short-circuits the other two: any measurement graded `FAIL`
    takes the panel `IN_TEST → FAILED` immediately, without waiting for
    coverage."
    "Every panel requires `RESIDUAL_INDENTATION` and
    `DIMENSIONAL_STABILITY_HEAT`."
    "A panel that reaches `FAILED` collapses the SKU's certification:
    `TESTING → UNCERTIFIED`, or `PROVISIONAL → SUSPENDED`, or
    `CERTIFIED → SUSPENDED`."
    "A new panel is `SCHEDULED` with `attempt_no` 1, `retest_count` 0,
    `void_reason` and `started_by_user_id` null, and `required_test_types`
    derived from the SKU."

    Design: Difficulty/transitive_cascade/panel_failure_aborts_planned_runs_and_releases_reservation
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_sku(api)
    begin_testing(api, built["sku"]["id"])
    panel = create_panel(api, built["sku"]["id"], "TP-F")
    start_panel(api, panel["id"])

    failing = validate_success(
        api.record_test_result(
            panel["id"],
            measurement_payload("RESIDUAL_INDENTATION", 0.30),
            QA_TECHNICIAN,
        ),
        201,
    )
    assert failing["spec_limit"] == 0.10
    assert failing["outcome"] == "FAIL"

    failed = validate_success(api.get_test_panel(panel["id"], QA_TECHNICIAN))
    assert failed["status"] == "FAILED"
    assert failed["retest_count"] == 0
    assert failed["attempt_no"] == 1

    _, results_meta = validate_paginated(
        api.list_test_results(panel["id"], QA_TECHNICIAN, params={"limit": 100})
    )
    assert results_meta["total_count"] == 1

    sku = validate_success(api.get_product_sku(built["sku"]["id"], PLANT_ADMIN))
    assert sku["certification_status"] == "UNCERTIFIED"


def test_panel_failure_aborts_planned_run_and_restores_reserved_volume_exactly(api):
    """The panel failure aborts the PLANNED run and returns the reservation to 0.00.

    "On success, the run's `planned_quantity_sqm` is added to the grant's
    `reserved_volume_sqm` and the grant's `version` is advanced."
    "Because the certification collapsed, every production run for that SKU
    whose `run_status` is `PLANNED` or `SETUP` is aborted with `abort_reason`
    recorded as `SKU_CERTIFICATION_LOST`, releasing each such run's
    licensed-volume reservation exactly as an operator abort would."
    "Aborting is available from `PLANNED`, `SETUP` or `RUNNING` with an
    `abort_reason`, and it is an exact compensation: the run's
    `planned_quantity_sqm` is subtracted from the grant's `reserved_volume_sqm`,
    restoring that figure to its pre-scheduling value bit for bit."
    "No batch is minted and no royalty is accrued, so a schedule-then-abort pair
    leaves the ledger indistinguishable from never having scheduled."
    "Fourth, provided `actual_quantity_sqm` is strictly greater than zero,
    exactly one batch is minted."

    Design: Difficulty/transitive_cascade/panel_failure_aborts_planned_runs_and_releases_reservation
    """
    set_clock(api, CLOCK_BOOT_UTC)
    built = build_sku(api)
    begin_testing(api, built["sku"]["id"])
    press_line = create_press_line(api)
    run = create_run(api, built["sku"]["id"], press_line["id"])
    assert run["run_status"] == "PLANNED"

    reserved_before = validate_success(
        api.get_license_utilization(built["license"]["id"], PRODUCTION_PLANNER)
    )
    assert reserved_before["reserved_volume_sqm"] == 1200.00

    panel = create_panel(api, built["sku"]["id"], "TP-F")
    start_panel(api, panel["id"])
    validate_success(
        api.record_test_result(
            panel["id"],
            measurement_payload("RESIDUAL_INDENTATION", 0.30),
            QA_TECHNICIAN,
        ),
        201,
    )

    aborted = validate_success(api.get_production_run(run["id"], PRODUCTION_PLANNER))
    assert aborted["run_status"] == "ABORTED"
    assert aborted["abort_reason"] == "SKU_CERTIFICATION_LOST"
    assert aborted["royalty_accrued_cents"] == 0

    utilization = validate_success(
        api.get_license_utilization(built["license"]["id"], PRODUCTION_PLANNER)
    )
    assert utilization["reserved_volume_sqm"] == 0.00
    assert utilization["consumed_volume_sqm"] == 0.00
    assert utilization["accrued_royalty_cents"] == 0

    _, batches_meta = validate_paginated(
        api.list_batches(
            PRODUCTION_PLANNER, params={"production_run_id": run["id"], "limit": 100}
        )
    )
    assert batches_meta["total_count"] == 0
