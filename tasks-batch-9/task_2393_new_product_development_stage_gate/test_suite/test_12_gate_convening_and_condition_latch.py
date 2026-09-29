"""Booking a review, the checklist screening builds, and the conditional-pass latch."""
import pytest

from test_helpers import (
    add_forecast_line,
    assert_deliverable,
    assert_gate_review,
    cast_vote,
    close_gate_review,
    deliverable_by_type,
    intake_project,
    make_gate_chair_headers,
    open_business_case,
    open_gate_review,
    read_project,
    register_stage_gate,
    schedule_gate_review,
    screen_project,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-03T00:00:00Z"

GATE_DEFAULTS = {
    "stage_from": "SCREENED",
    "stage_to": "PILOT_QUALIFIED",
    "required_deliverable_types": [],
    "quorum_size": 1,
    "veto_functions": [],
    "npv_hurdle_usd": 0.00,
    "payback_months_max": 24,
    "gross_margin_floor_pct": 0.00,
    "readiness_floor_index": 0.00,
}

# A bottom-up case with one grocery line that clears an NPV bar of 0.00, a payback bar of
# 24 months and a gross-margin floor of 0.00 percent.
CASE_KWARGS = {
    "variant_mode": "BOTTOM_UP",
    "category_size_units_year": 5000000,
    "target_share_pct": 3.00,
    "cogs_per_unit_usd": 3.2000,
    "slotting_fees_usd": 50000.00,
    "capex_usd": 300000.00,
    "discount_rate_pct": 9.00,
}

SCREENED_CHECKLIST_TYPES = [
    "CONSUMER_CONCEPT_TEST",
    "PRELIM_BUSINESS_CASE",
    "PILOT_SCALE_UP_REPORT",
]


def _snack_gate(gate_number=2, **overrides):
    kwargs = dict(GATE_DEFAULTS)
    kwargs.update({"gate_number": gate_number, "category": "SNACK"})
    kwargs.update(overrides)
    return register_stage_gate(**kwargs)


def _snack_project(owner_user_id, **overrides):
    payload = {
        "name": "Toffee Crunch Bites",
        "brand": "GrainWell",
        "category": "SNACK",
        "project_type": "LINE_EXTENSION",
        "strategic_fit_score": 8,
        "consumer_need_score": 7,
        "target_gross_margin_pct": 36,
        "category_attractiveness_score": 7,
        "development_budget_cap_usd": 500000.00,
    }
    payload.update(overrides)
    return intake_project(owner_user_id=owner_user_id, **payload)


def _screened_project(owner_user_id, chair_user_id, required_types=()):
    """Clock, a SNACK gate 2 and one screened SNACK project."""
    set_clock(CLOCK)
    gate2 = _snack_gate(2, required_deliverable_types=list(required_types))
    project = _snack_project(owner_user_id)
    screened = screen_project(project["id"], chair_user_id=chair_user_id)
    return {"gate2": gate2, "project": screened}


def _screened_with_computed_case(owner_user_id, chair_user_id):
    """A screened SNACK project carrying a COMPUTED case that clears all three bars."""
    ctx = _screened_project(owner_user_id, chair_user_id)
    case = open_business_case(ctx["project"]["id"], **CASE_KWARGS)
    add_forecast_line(case["id"])
    ctx["business_case"] = case
    ctx["project"] = read_project(ctx["project"]["id"])
    return ctx


def _conditionally_passed_project():
    """A gate-2 review closed CONDITIONAL_PASS with conditions due 2026-09-01T00:00:00Z."""
    ctx = _screened_with_computed_case("lead-cp", "chair-cp")
    ctx["gate3"] = _snack_gate(
        3, stage_from="PILOT_QUALIFIED", stage_to="LAUNCH_READY",
    )
    review = schedule_gate_review(
        ctx["project"]["id"], ctx["gate2"]["id"], chair_user_id="chair-cp",
        scheduled_at="2026-08-05T09:00:00Z",
    )
    open_gate_review(review["id"], chair_user_id="chair-cp")
    cast_vote(
        review["id"], function="OPERATIONS", vote="APPROVE_WITH_CONDITIONS",
        voter_user_id="rev-ops-cp", rationale="Co-packer capacity letter outstanding.",
    )
    ctx["review"] = close_gate_review(
        review["id"], "chair-cp",
        conditions="Confirm co-packer capacity in writing",
        conditions_due_at="2026-09-01T00:00:00Z",
    )
    ctx["project"] = read_project(ctx["project"]["id"])
    return ctx


def _passed_project():
    """A gate-2 review already closed PASSED on a single APPROVE ballot."""
    ctx = _screened_with_computed_case("lead-id", "chair-id")
    review = schedule_gate_review(
        ctx["project"]["id"], ctx["gate2"]["id"], chair_user_id="chair-id",
        scheduled_at="2026-08-05T09:00:00Z",
    )
    open_gate_review(review["id"], chair_user_id="chair-id")
    cast_vote(review["id"], function="OPERATIONS", vote="APPROVE",
              voter_user_id="rev-ops-id", rationale="Capacity confirmed.")
    ctx["review"] = close_gate_review(review["id"], "chair-id")
    ctx["project"] = read_project(ctx["project"]["id"])
    return ctx


def test_a_freshly_booked_gate_review_is_scheduled_with_zeroed_figures(api):
    """Booking documents intent only: no chair, no ballots, no computed figures yet.

    PRD: "A `GateChair` schedules a review against a gate configuration by supplying the
    `gate_id` and an informational `scheduled_at`; the review is created in `SCHEDULED` with
    `decision`, `chair_user_id`, `conditions`, `conditions_due_at` and `closed_at` all null,
    `vote_count` 0, and `deliverable_completeness_pct` and `readiness_index` both `0.00`."

    Design: Corner/state_machines/sm_new_gate_review_starts_scheduled
    """
    ctx = _screened_project("lead-i1", "chair-i1")

    booked = validate_success(
        api.create_gate_review(
            ctx["project"]["id"],
            {"gate_id": ctx["gate2"]["id"], "scheduled_at": "2026-08-12T09:00:00Z"},
            make_gate_chair_headers("chair-i1"),
        ),
        201,
    )

    assert_gate_review(booked)
    assert booked["status"] == "SCHEDULED"
    assert booked["decision"] is None
    assert booked["closed_at"] is None
    assert booked["chair_user_id"] is None, "the chair is only stamped at close"
    assert booked["conditions"] is None
    assert booked["conditions_due_at"] is None
    assert booked["vote_count"] == 0
    assert booked["deliverable_completeness_pct"] == pytest.approx(0.00, abs=0.01)
    assert booked["readiness_index"] == pytest.approx(0.00, abs=0.01)
    assert read_project(ctx["project"]["id"])["dev_status"] == "SCREENED", (
        "booking a review does not move the development track"
    )


def test_screening_a_passing_idea_materialises_the_gate_two_checklist(api):
    """One PENDING item per required type, each stamped with the mapped owner function.

    PRD: "First the margin criterion is normalised: `target_gross_margin_pct` is divided by the
    reference target of 40 percent, multiplied by 100, rounded half up to four decimal places,
    and then capped at 100 — so a project targeting a 60 percent gross margin normalises to 100
    rather than 150, and the extra ambition earns nothing."
    PRD: "- `LINE_EXTENSION` weights them 0.30, 0.25, 0.30 and 0.15."
    PRD: "The four weighted terms are summed and the sum is rounded half up to two decimal
    places to give `screening_score`."
    PRD: "It then creates one checklist item in status `PENDING` for each entry of that gate's
    `required_deliverable_types`, **in array order**, stamping each with the gate's `gate_id`
    and taking `owner_function` from the fixed type-to-function map: `CONSUMER_CONCEPT_TEST`
    and `MARKETING_LAUNCH_PLAN` belong to `MARKETING`; `PRELIM_BUSINESS_CASE` and
    `FINAL_BUSINESS_CASE` to `FINANCE`; `PILOT_SCALE_UP_REPORT` to `R_AND_D`;
    `SHELF_LIFE_REPORT` to `QUALITY`; `REGULATORY_CLEARANCE` to `REGULATORY`;
    `MANUFACTURING_READINESS` and `DISTRIBUTION_READINESS` to `OPERATIONS`; and
    `SALES_SELL_IN_PLAN` to `SALES`."
    PRD: "`next_gate_number` stays at 2, because gate 2 is now the gate to convene."

    Design: Corner/state_machines/sm_screen_pass_creates_checklist_in_declared_order
    """
    set_clock(CLOCK)
    gate2 = _snack_gate(2, required_deliverable_types=list(SCREENED_CHECKLIST_TYPES))
    project = _snack_project("lead-cl")

    screened = validate_success(
        api.screen_project(
            project["id"],
            {"screening_notes": "Strong fit with the better-for-you platform."},
            make_gate_chair_headers("chair-cl"),
        )
    )

    assert screened["screening_score"] == pytest.approx(79.00, abs=0.01), (
        "0.30 * 80 plus 0.25 * 70 plus 0.30 * 90 plus 0.15 * 70 under the line-extension weights"
    )
    assert screened["screening_decision"] == "PASSED"
    assert screened["dev_status"] == "SCREENED"
    assert screened["next_gate_number"] == 2
    items, meta = validate_paginated(
        api.list_deliverables(
            make_gate_chair_headers("chair-cl"),
            params={"project_id": project["id"], "gate_id": gate2["id"]},
        )
    )
    assert meta["total_count"] == 3, "one item per entry of the required list"
    expected_functions = {
        "CONSUMER_CONCEPT_TEST": "MARKETING",
        "PRELIM_BUSINESS_CASE": "FINANCE",
        "PILOT_SCALE_UP_REPORT": "R_AND_D",
    }
    assert sorted(item["deliverable_type"] for item in items) == sorted(expected_functions)
    for item in items:
        assert_deliverable(item)
        assert item["gate_id"] == gate2["id"]
        assert item["status"] == "PENDING"
        assert item["owner_function"] == expected_functions[item["deliverable_type"]], (
            "owner_function comes from the fixed type map, not from the acting chair"
        )


def test_every_auto_created_checklist_item_starts_unsubmitted_and_undecided(api):
    """The materialised rows carry no evidence, no submitter and no decider.

    PRD: "Each item starts in `PENDING` with `evidence_url`, `submitted_by_user_id` and
    `decided_by_user_id` all null, `due_at` null unless supplied,
    `prerequisite_deliverable_id` null unless supplied, and `submission_count` 0."

    Design: Corner/state_machines/sm_screen_pass_creates_checklist_in_declared_order
    """
    set_clock(CLOCK)
    gate2 = _snack_gate(2, required_deliverable_types=list(SCREENED_CHECKLIST_TYPES))
    project = _snack_project("lead-cl")

    validate_success(
        api.screen_project(
            project["id"], {"screening_notes": "Into stage 2."},
            make_gate_chair_headers("chair-cl"),
        )
    )

    for deliverable_type in SCREENED_CHECKLIST_TYPES:
        item = deliverable_by_type(project["id"], deliverable_type, gate_id=gate2["id"])
        assert item is not None, f"{deliverable_type} was not materialised at screening"
        assert item["status"] == "PENDING"
        assert item["submission_count"] == 0
        assert item["evidence_url"] is None
        assert item["submitted_by_user_id"] is None
        assert item["decided_by_user_id"] is None
        assert item["prerequisite_deliverable_id"] is None


def test_clearing_conditions_before_the_deadline_promotes_the_review_to_passed(api):
    """The decision is rewritten to PASSED and the project's condition latch drops.

    PRD: "`decision` becomes `CONDITIONAL_PASS`, the project's `open_gate_conditions` is set to
    true, `closed_at` and `chair_user_id` are stamped, the two frozen figures are re-frozen,
    the project's `dev_status` advances to the gate's `stage_to` exactly as on the passing
    branch, and the authoritative business case likewise moves `COMPUTED → LOCKED`."
    PRD: "Clearing takes the review `CONDITIONAL_PASS → PASSED`, rewrites `decision` to
    `PASSED`, and sets the project's `open_gate_conditions` back to false, unblocking the next
    gate."

    Design: Corner/state_machines/sm_conditional_pass_cleared_before_due_unblocks_next_gate
    """
    ctx = _conditionally_passed_project()
    assert ctx["review"]["decision"] == "CONDITIONAL_PASS"
    assert ctx["project"]["open_gate_conditions"] is True
    assert ctx["project"]["dev_status"] == "PILOT_QUALIFIED"

    cleared = validate_success(
        api.clear_gate_conditions(
            ctx["review"]["id"],
            {"resolution_note": "Capacity letter received from the co-packer."},
            make_gate_chair_headers("chair-cp"),
        )
    )

    assert cleared["status"] == "PASSED"
    assert cleared["decision"] == "PASSED"
    project = read_project(ctx["project"]["id"])
    assert project["open_gate_conditions"] is False
    assert project["dev_status"] == "PILOT_QUALIFIED"
    assert project["next_gate_number"] == 3
    assert project["recycle_count"] == 0, "clearing conditions is not a recycle"
    case = validate_success(
        api.get_business_case(
            ctx["business_case"]["id"], make_gate_chair_headers("chair-cp")
        )
    )
    assert case["status"] == "LOCKED", "the conditional close locked the case, not the clear"


def test_the_cleared_latch_lets_the_next_gate_open_with_its_frozen_figures(api):
    """With the latch down the stage-3 session opens and freezes its computed figures.

    PRD: "And `open_gate_conditions` on the project must be false, else
    `ERR_GATE_CONDITIONS_OPEN` (409) — unresolved conditions from an earlier conditional pass
    block the next gate entirely."
    PRD: "If the gate's `required_deliverable_types` array is empty the value is `100.00` — an
    empty checklist is vacuously complete, not zero and not a division error."
    PRD: "Those four — completeness, concept, hurdle, yield, in that order — are combined under
    a weight vector chosen by the project's `project_type`: `NEW_BRAND` weights them 0.35,
    0.30, 0.20 and 0.15; `LINE_EXTENSION` weights them 0.30, 0.25, 0.25 and 0.20;
    `RENOVATION` weights them 0.40, 0.20, 0.20 and 0.20."

    Design: Corner/state_machines/sm_conditional_pass_cleared_before_due_unblocks_next_gate
    """
    ctx = _conditionally_passed_project()
    validate_success(
        api.clear_gate_conditions(
            ctx["review"]["id"],
            {"resolution_note": "Capacity letter received from the co-packer."},
            make_gate_chair_headers("chair-cp"),
        )
    )

    gate3_review = schedule_gate_review(
        ctx["project"]["id"], ctx["gate3"]["id"], chair_user_id="chair-cp",
        scheduled_at="2026-08-20T09:00:00Z",
    )
    opened = validate_success(
        api.open_gate_review(gate3_review["id"], {}, make_gate_chair_headers("chair-cp"))
    )

    assert_gate_review(opened)
    assert opened["status"] == "IN_SESSION"
    assert opened["deliverable_completeness_pct"] == pytest.approx(100.00, abs=0.01)
    assert opened["readiness_index"] == pytest.approx(55.00, abs=0.01), (
        "0.30 * 100.00 completeness plus 0.25 * 100.00 hurdle, with no concept test and no "
        "formulation, at the snack category factor of 1.00"
    )


def test_a_second_close_on_a_passed_review_is_refused(api):
    """Replaying the close cannot advance the project a second time.

    PRD: "**Closing** is the branching heart of the system. A `GateChair` closes an
    `IN_SESSION` review, optionally supplying `conditions` and `conditions_due_at`."
    PRD: "**State** — the subject row and its governing parents admit the requested
    transition, else the entity's `ERR_..._INVALID_STATE` code (409)."
    PRD: "A passing close of a gate whose `stage_from` is `SCREENED` and whose `stage_to` is
    `PILOT_QUALIFIED` moves `dev_status` `SCREENED → PILOT_QUALIFIED`, sets `next_gate_number`
    to the gate's `gate_number` plus one, and then auto-creates the checklist of the stage gate
    registered for the project's `category` at that new `next_gate_number` — but only when such
    a configuration exists **and** its `stage_from` equals the project's new `dev_status`, and
    again skipping any combination of `gate_id` and `deliverable_type` that already exists."

    Design: Corner/state_machines/sm_second_close_on_a_closed_review_rejected
    """
    ctx = _passed_project()
    assert ctx["review"]["status"] == "PASSED"
    frozen_version = ctx["review"]["version"]

    response = api.close_gate_review(
        ctx["review"]["id"], {}, make_gate_chair_headers("chair-id")
    )

    validate_error(response, "ERR_GATE_REVIEW_INVALID_STATE", 409)
    review = validate_success(
        api.get_gate_review(ctx["review"]["id"], make_gate_chair_headers("chair-id"))
    )
    assert review["status"] == "PASSED"
    assert review["decision"] == "PASSED"
    assert review["version"] == frozen_version, "a refused close is not an accepted write"
    project = read_project(ctx["project"]["id"])
    assert project["dev_status"] == "PILOT_QUALIFIED"
    assert project["next_gate_number"] == 3, "the advance did not run twice"
    assert project["recycle_count"] == 0
    cases, meta = validate_paginated(
        api.list_business_cases(ctx["project"]["id"], make_gate_chair_headers("chair-id"))
    )
    assert meta["total_count"] == 1
    assert cases[0]["status"] == "LOCKED"


def test_opening_a_gate_from_the_wrong_stage_reports_the_state_error(api):
    """A stage-3 session refuses to open from dev_status SCREENED.

    PRD: "The project's `dev_status` must equal the gate's `stage_from`, else
    `ERR_PROJECT_INVALID_STATE`."
    PRD: "The server always evaluates checks in the following thirteen bands and answers with
    the **first** violated rule, so the reported error is a deterministic function of request
    and state rather than of implementation order."

    Design: Corner/state_machines/sm_open_on_wrong_stage_gate_rejected
    """
    ctx = _screened_project("lead-ws", "chair-ws")
    gate3 = _snack_gate(3, stage_from="PILOT_QUALIFIED", stage_to="LAUNCH_READY")
    review = schedule_gate_review(
        ctx["project"]["id"], gate3["id"], chair_user_id="chair-ws",
        scheduled_at="2026-08-20T09:00:00Z",
    )

    response = api.open_gate_review(review["id"], {}, make_gate_chair_headers("chair-ws"))

    validate_error(response, "ERR_PROJECT_INVALID_STATE", 409)
    unchanged = validate_success(
        api.get_gate_review(review["id"], make_gate_chair_headers("chair-ws"))
    )
    assert unchanged["status"] == "SCHEDULED"
    assert unchanged["deliverable_completeness_pct"] == pytest.approx(0.00, abs=0.01)
    assert unchanged["readiness_index"] == pytest.approx(0.00, abs=0.01)
    project = read_project(ctx["project"]["id"])
    assert project["dev_status"] == "SCREENED"
    assert project["next_gate_number"] == 2
