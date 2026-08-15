"""Quality inspections: the FAIL rework loop, its cascading recomputation,
PASS finalization, and the immutability of inspection records."""
from test_helpers import (
    INSP,
    accept,
    add_scope_item,
    assert_inspection,
    complete,
    create_commitment,
    create_property,
    create_unit,
    create_vendor,
    fail_inspection,
    finalize_turn,
    find_rework_item,
    get_item,
    get_turn,
    get_unit,
    list_commitments,
    open_turn,
    pass_inspection,
    schedule,
    setup_completed_turn_item,
    validate_success,
)


def _setup_completed_paint_turn(api, item_estimate=8000, actual=5000,
                                committed=None):
    """IN_PROGRESS turn with a single COMPLETED PAINT item; optionally an
    ACTIVE lease commitment on the unit."""
    prop = create_property()
    unit = create_unit(prop["id"])
    turn = open_turn(unit["id"])
    item = add_scope_item(turn["id"], "PAINT", item_estimate, "repaint")
    finalize_turn(turn["id"])
    painter = create_vendor("PaintPros", "PAINT")
    asg = schedule(item["id"], painter["id"], "2026-08-01", "2026-08-03")
    accept(asg["id"], painter["id"])
    complete(asg["id"], painter["id"], actual)
    commitment = None
    if committed is not None:
        commitment = create_commitment(unit["id"], committed)
    return {"unit": unit, "turn": turn, "item": item, "vendor": painter,
            "commitment": commitment}


# --- rework loop (Difficulty: turn_rework_loop_inprogress_to_ready_cycle)

def test_failed_inspection_spawns_rework_item(api):
    """PRD §3.7: "Each listed item moves from `COMPLETED` to `FAILED`, and for
    each failed item the system auto-creates a rework scope item: same
    `category` as the failed original, born in `PLANNED` status, its
    `estimated_cost_cents` seeded from the failed item's `actual_cost_cents`,
    its `classification` forced to `EXPENSE`, its `approval_tier` forced to
    `NONE`, and its `rework_of_item_id` pointing back at the failed original."

    Design: Difficulty/non_linear_state_machine/turn_rework_loop_inprogress_to_ready_cycle
    """
    ctx = _setup_completed_paint_turn(api)
    fail_inspection(ctx["turn"]["id"], [ctx["item"]["id"]], "streaks on wall")

    assert get_item(ctx["item"]["id"])["status"] == "FAILED"
    rework = find_rework_item(ctx["item"]["id"])
    assert rework["rework_of_item_id"] == ctx["item"]["id"]
    assert rework["category"] == "PAINT"
    assert rework["status"] == "PLANNED"
    assert rework["estimated_cost_cents"] == 5000, "seeded from the actual"
    assert rework["classification"] == "EXPENSE"
    assert rework["approval_tier"] == "NONE"
    assert get_turn(ctx["turn"]["id"])["status"] == "REWORK"


def test_rework_cycle_returns_turn_to_ready(api):
    """PRD §3.4: "likewise, when the turn is `REWORK`, acceptance of an
    assignment on a rework item — one whose `rework_of_item_id` is set —
    returns the turn to `IN_PROGRESS`."
    PRD §3.7: "A `PASS` is the happy ending: `actual_ready_date` is stamped
    with the current logical-clock date, the turn moves `IN_PROGRESS` → `READY`
    with its `version` incremented by one, the unit moves from `IN_TURN` to
    `READY`, and the projection machinery runs once more with commitment risk
    re-evaluated."
    PRD §2.5: "At startup, before any operator intervention, the logical clock
    reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock
    time on its own."

    Design: Difficulty/non_linear_state_machine/turn_rework_loop_inprogress_to_ready_cycle
    """
    ctx = _setup_completed_paint_turn(api)
    fail_inspection(ctx["turn"]["id"], [ctx["item"]["id"]], "streaks on wall")
    rework = find_rework_item(ctx["item"]["id"])

    asg2 = schedule(rework["id"], ctx["vendor"]["id"],
                    "2026-08-03", "2026-08-05")
    accept(asg2["id"], ctx["vendor"]["id"])
    assert get_turn(ctx["turn"]["id"])["status"] == "IN_PROGRESS", (
        "REWORK -> IN_PROGRESS on rework-item acceptance (cycle traversed)"
    )
    complete(asg2["id"], ctx["vendor"]["id"], 4500)
    pass_inspection(ctx["turn"]["id"], "ok now")

    turn = get_turn(ctx["turn"]["id"])
    assert turn["status"] == "READY"
    assert turn["actual_ready_date"] == "2026-08-01", "logical clock unchanged"
    assert get_unit(ctx["unit"]["id"])["status"] == "READY"


# --- FAIL cascade depth (Difficulty: inspection_fail_rework_commitment_cascade)

def test_fail_cascade_fails_item_and_spawns_rework(api):
    """PRD §3.7: "Each listed item moves from `COMPLETED` to `FAILED`, and for
    each failed item the system auto-creates a rework scope item: same
    `category` as the failed original, born in `PLANNED` status, its
    `estimated_cost_cents` seeded from the failed item's `actual_cost_cents`,
    its `classification` forced to `EXPENSE`, its `approval_tier` forced to
    `NONE`, and its `rework_of_item_id` pointing back at the failed original."

    Design: Difficulty/transitive_cascade/inspection_fail_rework_commitment_cascade
    """
    ctx = _setup_completed_paint_turn(api, committed="2026-08-02")
    fail_inspection(ctx["turn"]["id"], [ctx["item"]["id"]], "paint peeling")

    assert get_item(ctx["item"]["id"])["status"] == "FAILED"
    rework = find_rework_item(ctx["item"]["id"])
    assert rework["status"] == "PLANNED"
    assert rework["category"] == "PAINT"
    assert rework["estimated_cost_cents"] == 5000
    assert rework["rework_of_item_id"] == ctx["item"]["id"]


def test_fail_cascade_reprojects_and_flips_commitment_to_at_risk(api):
    """PRD §3.7: "Because failed items remain in the estimate's input set and
    their actuals stay in the expense actuals, the turn's
    `estimated_cost_cents`, `expense_actual_cents`, `capital_actual_cents`,
    `total_actual_cents`, and `booked_expense_cents` are all re-derived, and —
    driven by the newly created rework items — `projected_ready_date` is
    recomputed; if the projection now lands after some `ACTIVE` commitment's
    promised date on the unit, that commitment flips to `AT_RISK`."

    Design: Difficulty/transitive_cascade/inspection_fail_rework_commitment_cascade
    """
    ctx = _setup_completed_paint_turn(api, committed="2026-08-02")
    assert ctx["commitment"]["status"] == "ACTIVE"

    fail_inspection(ctx["turn"]["id"], [ctx["item"]["id"]], "paint peeling")

    turn = get_turn(ctx["turn"]["id"])
    assert turn["status"] == "REWORK"
    # 8000 (FAILED item still counted) + 5000 (rework PLANNED).
    assert turn["estimated_cost_cents"] == 13000
    # anchor = clock 2026-08-01 (no SCHEDULED|ACCEPTED assignments);
    # PLANNED rework PAINT adds 2 days -> 2026-08-03.
    assert turn["projected_ready_date"] == "2026-08-03"
    commitments = list_commitments(ctx["unit"]["id"])
    assert commitments[0]["status"] == "AT_RISK", (
        "projected 08-03 lands after the promised 08-02"
    )


# --- inspection immutability (Corner: inspection_immutable_entity_has_no_version)

def test_inspection_record_has_no_version_or_updated_at(api):
    """PRD §2.4: "An **Inspection** and a **ReplacementDecision** are immutable
    records of a one-time event: each carries only `id` and `created_at`, and
    both `updated_at` and `version` are absent from them entirely."
    PRD §3.7: "Inspections are immutable once submitted, carrying `id` and
    `created_at` but no `updated_at` or `version`, and the full inspection
    history of a turn can be listed."

    Design: Corner/entities/inspection_immutable_entity_has_no_version
    """
    ctx = setup_completed_turn_item(5000, 4000)
    inspection = validate_success(
        api.submit_inspection(ctx["turn"]["id"], {"result": "PASS"}, INSP),
        201,
    )
    assert_inspection(inspection)
    assert inspection["result"] == "PASS"
    assert inspection["turn_id"] == ctx["turn"]["id"]
    assert "version" not in inspection
    assert "updated_at" not in inspection
