"""Terminal lockout, the waiver asymmetry, the commitment ledger and refused-write atomicity."""
import pytest

from test_helpers import (
    READINESS_DELIVERABLE_TYPES,
    add_forecast_line,
    approve_readiness_deliverables,
    book_pilot_run,
    business_case_payload,
    cast_vote,
    close_gate_review,
    complete_pilot_run,
    create_formulation,
    decide_deliverable,
    deliverable_by_type,
    deliverable_payload,
    formulation_payload,
    intake_project,
    make_gate_chair_headers,
    make_innovation_lead_headers,
    make_portfolio_admin_headers,
    make_rnd_lead_headers,
    open_business_case,
    open_gate_review,
    open_shelf_life_study,
    project_version,
    read_project,
    register_pilot_line,
    register_stage_gate,
    run_gate_session,
    schedule_gate_review,
    screen_project,
    set_clock,
    start_pilot_run,
    submit_deliverable,
    validate_error,
    validate_paginated,
    validate_success,
    waive_deliverable,
)

CLOCK = "2026-08-03T00:00:00Z"
ADMIN = make_portfolio_admin_headers("admin-13")

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

# A bottom-up case with one grocery line, comfortably clearing a 0.00 NPV bar, a 24-month
# payback bar and a 0.00 percent margin floor.
CLEARING_CASE = {
    "variant_mode": "BOTTOM_UP",
    "category_size_units_year": 5000000,
    "target_share_pct": 3.00,
    "cogs_per_unit_usd": 3.2000,
    "slotting_fees_usd": 50000.00,
    "capex_usd": 300000.00,
    "discount_rate_pct": 9.00,
}


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


def _killed_at_screening():
    """A SNACK idea whose screening score lands one cent below the floor."""
    set_clock(CLOCK)
    gate2 = _snack_gate(2, required_deliverable_types=["MANUFACTURING_READINESS"])
    project = _snack_project(
        "lead-tk", name="Marginal Muesli Bar", strategic_fit_score=6, consumer_need_score=6,
        target_gross_margin_pct=23.99, category_attractiveness_score=6,
    )
    screened = screen_project(project["id"], chair_user_id="chair-tk")
    return {"gate2": gate2, "project": screened}


def _waiver_project():
    """A PILOT_QUALIFIED snack project with three readiness items approved, one still open."""
    set_clock(CLOCK)
    gate2 = _snack_gate(2)
    gate3 = _snack_gate(
        3, stage_from="PILOT_QUALIFIED", stage_to="LAUNCH_READY",
        required_deliverable_types=list(READINESS_DELIVERABLE_TYPES),
    )
    project = _snack_project("lead-wv")
    screen_project(project["id"], chair_user_id="chair-wv")
    case = open_business_case(project["id"], **CLEARING_CASE)
    add_forecast_line(case["id"])
    run_gate_session(
        project["id"], gate2["id"], votes=(("OPERATIONS", "APPROVE", "rev-ops-wv"),),
        chair_user_id="chair-wv", scheduled_at="2026-08-05T09:00:00Z",
    )
    approve_readiness_deliverables(
        project["id"], gate3["id"],
        ["MANUFACTURING_READINESS", "DISTRIBUTION_READINESS", "MARKETING_LAUNCH_PLAN"],
    )
    sales_item = deliverable_by_type(
        project["id"], "SALES_SELL_IN_PLAN", gate_id=gate3["id"]
    )
    return {
        "gate2": gate2, "gate3": gate3, "project": read_project(project["id"]),
        "sales_item": sales_item,
    }


def _ledger_project():
    """A snack project with one formulation and a fresh pilot line, nothing committed yet."""
    set_clock(CLOCK)
    line = register_pilot_line(
        plant_name="Toledo Pilot", line_code="TOL-7", changeover_buffer_minutes=240,
        allergen_regime="NONE", hourly_cost_usd=500.00,
    )
    project = _snack_project("lead-lg")
    formulation = create_formulation(
        project["id"], spec_summary="Toffee inclusion at 12 percent", allergen_regime="NONE",
        target_shelf_life_days=180, unit_cost_usd=3.2000,
    )
    return {"pilot_line": line, "project": project, "formulation": formulation}


def _review_missing_the_hurdles():
    """An IN_SESSION gate 2 review with one APPROVE ballot and a case that misses two bars."""
    set_clock(CLOCK)
    gate2 = _snack_gate(
        2, npv_hurdle_usd=500000.00, payback_months_max=24, gross_margin_floor_pct=0.00,
    )
    project = _snack_project("lead-at", name="Thin Margin Thins",
                             development_budget_cap_usd=300000.00)
    screen_project(project["id"], chair_user_id="chair-at")
    case = open_business_case(
        project["id"], variant_mode="TOP_DOWN", category_size_units_year=1000000,
        target_share_pct=5.00, cogs_per_unit_usd=2.0000, slotting_fees_usd=0.00,
        capex_usd=300000.00, discount_rate_pct=10.00,
    )
    add_forecast_line(
        case["id"], channel="GROCERY", store_count=1000,
        base_velocity_units_per_store_week=1.00, promo_weeks=0, promo_lift_pct=0.00,
        list_price_usd=4.0000,
    )
    review = schedule_gate_review(project["id"], gate2["id"], chair_user_id="chair-at",
                                  scheduled_at="2026-08-10T09:00:00Z")
    opened = open_gate_review(review["id"], chair_user_id="chair-at")
    cast_vote(review["id"], function="FINANCE", vote="APPROVE", voter_user_id="rev-fin-at",
              rationale="Strategically worth the stretch.")
    return {
        "gate2": gate2, "project": read_project(project["id"]), "business_case": case,
        "review": opened,
    }


def _half_complete_session():
    """An IN_SESSION gate 2 review opened with one of two required items approved."""
    set_clock(CLOCK)
    gate2 = _snack_gate(
        2, required_deliverable_types=["MANUFACTURING_READINESS", "SALES_SELL_IN_PLAN"],
        payback_months_max=999,
    )
    project = _snack_project("lead-fz", name="Snapshot Crisps",
                             development_budget_cap_usd=300000.00)
    screen_project(project["id"], chair_user_id="chair-fz")
    case = open_business_case(
        project["id"], variant_mode="TOP_DOWN", category_size_units_year=4000000,
        target_share_pct=4.00, cogs_per_unit_usd=2.5000, slotting_fees_usd=0.00,
        capex_usd=100000.00, discount_rate_pct=10.00,
    )
    add_forecast_line(
        case["id"], channel="GROCERY", store_count=2000,
        base_velocity_units_per_store_week=1.00, promo_weeks=0, promo_lift_pct=0.00,
        list_price_usd=5.0000,
    )
    manufacturing = deliverable_by_type(
        project["id"], "MANUFACTURING_READINESS", gate_id=gate2["id"]
    )
    sales = deliverable_by_type(project["id"], "SALES_SELL_IN_PLAN", gate_id=gate2["id"])
    submit_deliverable(manufacturing["id"], submitter_user_id="sub-fz")
    decide_deliverable(manufacturing["id"], "APPROVE", decider_user_id="rev-fz")
    review = schedule_gate_review(project["id"], gate2["id"], chair_user_id="chair-fz",
                                  scheduled_at="2026-08-10T09:00:00Z")
    opened = open_gate_review(review["id"], chair_user_id="chair-fz")
    return {
        "gate2": gate2, "project": read_project(project["id"]), "business_case": case,
        "manufacturing": manufacturing, "sales": sales, "review": opened,
    }


def test_a_killed_project_refuses_every_child_creating_write(api):
    """Nothing may be hung off a project the screening killed.

    PRD: "First the margin criterion is normalised: `target_gross_margin_pct` is divided by the
    reference target of 40 percent, multiplied by 100, rounded half up to four decimal places,
    and then capped at 100 — so a project targeting a 60 percent gross margin normalises to 100
    rather than 150, and the extra ambition earns nothing."
    PRD: "- `LINE_EXTENSION` weights them 0.30, 0.25, 0.30 and 0.15."
    PRD: "The screening floor is `60.00`. When `screening_score` is at least `60.00`,
    `screening_decision` becomes `PASSED` and `dev_status` advances `IDEA → SCREENED`; a score
    one cent below the floor sets `screening_decision` to `REJECTED` and moves `dev_status`
    `IDEA → KILLED` instead."
    PRD: "On the killing branch no checklist is created at all."
    PRD: "- Business-case creation, formulation creation, checklist creation and gate-review
    scheduling admit `dev_status` in `IDEA`, `SCREENED`, `PILOT_QUALIFIED` or `LAUNCH_READY`."
    PRD: "`DISCONTINUED` and `KILLED` are the two terminal development states; a project in
    either accepts no further checklist submissions and no further development or commercial
    work."

    Design: Corner/state_machines/sm_killed_project_locks_out_further_writes
    """
    ctx = _killed_at_screening()
    project_id = ctx["project"]["id"]
    assert ctx["project"]["screening_score"] == pytest.approx(59.99, abs=0.01)
    assert ctx["project"]["screening_decision"] == "REJECTED"
    assert ctx["project"]["dev_status"] == "KILLED"
    version_at_kill = ctx["project"]["version"]

    refusals = [
        api.create_business_case(
            project_id, business_case_payload(version_at_kill),
            make_innovation_lead_headers("lead-tk"),
        ),
        api.create_formulation(
            project_id, formulation_payload(version_at_kill),
            make_rnd_lead_headers("rnd-tk"),
        ),
        api.create_deliverable(
            project_id, deliverable_payload(ctx["gate2"]["id"]),
            make_gate_chair_headers("chair-tk"),
        ),
        api.create_gate_review(
            project_id,
            {"gate_id": ctx["gate2"]["id"], "scheduled_at": "2026-08-12T09:00:00Z"},
            make_gate_chair_headers("chair-tk"),
        ),
        api.screen_project(
            project_id, {"screening_notes": "Second look, better mood."},
            make_gate_chair_headers("chair-tk"),
        ),
    ]

    for response in refusals:
        validate_error(response, "ERR_PROJECT_INVALID_STATE", 409)
    _, case_meta = validate_paginated(api.list_business_cases(project_id, ADMIN))
    assert case_meta["total_count"] == 0
    _, formulation_meta = validate_paginated(api.list_formulations(project_id, ADMIN))
    assert formulation_meta["total_count"] == 0
    _, item_meta = validate_paginated(
        api.list_deliverables(ADMIN, params={"project_id": project_id})
    )
    assert item_meta["total_count"] == 0, "the killing branch created no checklist either"
    _, review_meta = validate_paginated(
        api.list_gate_reviews(ADMIN, params={"project_id": project_id})
    )
    assert review_meta["total_count"] == 0
    after = read_project(project_id)
    assert after["dev_status"] == "KILLED"
    assert after["screening_score"] == pytest.approx(59.99, abs=0.01)
    assert after["version"] == version_at_kill, "no refused request touched the project row"


def test_a_stale_version_against_a_killed_project_still_reports_the_state_error(api):
    """The terminal state outranks the concurrency check on the very same request.

    PRD: "State is checked **before** optimistic concurrency, so a stale version supplied
    against an already-terminal row reports the state error rather than 412."
    PRD: "Concurrency runs after state and before every business rule, so a stale version
    outranks a budget overrun or a referential violation raised by the same request."

    Design: Corner/state_machines/sm_killed_project_locks_out_further_writes
    """
    ctx = _killed_at_screening()
    project_id = ctx["project"]["id"]
    live_version = project_version(project_id)
    stale_version = live_version - 1
    assert stale_version >= 1, "the kill already advanced the project row past version 1"

    response = api.create_formulation(
        project_id, formulation_payload(stale_version), make_rnd_lead_headers("rnd-tk")
    )

    validate_error(response, "ERR_PROJECT_INVALID_STATE", 409)
    _, meta = validate_paginated(api.list_formulations(project_id, ADMIN))
    assert meta["total_count"] == 0
    assert project_version(project_id) == live_version


def test_a_waived_item_satisfies_the_gate_checklist_at_full_completeness(api):
    """The waiver takes the fourth item off the critical path for the gate.

    PRD: "A `WAIVED` item counts as **satisfied** for gate checklist completeness but
    contributes **nothing** to launch readiness — waiving a manufacturing readiness plan lets a
    gate close but will never let a launch date lock."
    PRD: "Otherwise the server counts how many of the required types have an item on that
    combination of `project_id` and `gate_id` whose `status` is `APPROVED` or `WAIVED`, divides
    by the number of required types, multiplies by 100 and rounds half up to two decimal
    places."

    Design: Corner/state_machines/sm_waived_deliverable_satisfies_checklist_but_not_launch_readiness
    """
    ctx = _waiver_project()
    assert ctx["sales_item"]["status"] == "PENDING"

    waived = validate_success(
        api.waive_deliverable(
            ctx["sales_item"]["id"],
            {"reason": "Retailer plan deferred to the next reset"},
            make_gate_chair_headers("chair-wv"),
        )
    )

    assert waived["status"] == "WAIVED"
    review = schedule_gate_review(
        ctx["project"]["id"], ctx["gate3"]["id"], chair_user_id="chair-wv",
        scheduled_at="2026-08-20T09:00:00Z",
    )
    opened = validate_success(
        api.open_gate_review(review["id"], {}, make_gate_chair_headers("chair-wv"))
    )
    assert opened["deliverable_completeness_pct"] == pytest.approx(100.00, abs=0.01), (
        "three approvals plus one waiver satisfy all four required types"
    )


def test_a_waived_item_contributes_nothing_to_launch_readiness(api):
    """Launch readiness stays at 80.00 and still names the waived type as blocking.

    PRD: "The denominator is the sum of the weights over that required set; the numerator is
    the sum of the weights over those required types whose checklist item is `APPROVED`, and a
    `WAIVED` item contributes nothing to the numerator even though it satisfies gate
    completeness."
    PRD: "A dedicated launch-readiness read exposes the live picture without storing anything
    new: the current `launch_readiness_pct`, a `blocking_deliverable_types` array listing the
    required readiness types not yet `APPROVED` in checklist order, the current
    `authorized_acv_pct`, the locked `launch_date` if any, and an `earliest_lockable_date`
    computed on every read as the current instant plus the 45-whole-day lock lead time."
    PRD: "The type weights are `MANUFACTURING_READINESS` 0.35, `DISTRIBUTION_READINESS` 0.25,
    `MARKETING_LAUNCH_PLAN` 0.20 and `SALES_SELL_IN_PLAN` 0.20."

    Design: Corner/state_machines/sm_waived_deliverable_satisfies_checklist_but_not_launch_readiness
    """
    ctx = _waiver_project()
    assert read_project(ctx["project"]["id"])["launch_readiness_pct"] == pytest.approx(
        80.00, abs=0.01
    )

    waive_deliverable(
        ctx["sales_item"]["id"], reason="Retailer plan deferred to the next reset",
        chair_user_id="chair-wv",
    )

    readiness = validate_success(
        api.get_launch_readiness(ctx["project"]["id"], ADMIN)
    )
    assert readiness["launch_readiness_pct"] == pytest.approx(80.00, abs=0.01), (
        "0.35 plus 0.25 plus 0.20 over a denominator of 1.00; the waiver adds nothing"
    )
    assert readiness["blocking_deliverable_types"] == ["SALES_SELL_IN_PLAN"], (
        "a waived type is still not APPROVED, so it still blocks the date lock"
    )
    assert readiness["authorized_acv_pct"] == pytest.approx(0.00, abs=0.01)
    assert readiness["launch_date"] is None
    assert str(readiness["earliest_lockable_date"]).startswith("2026-09-17T00:00:00"), (
        "45 whole days after the current instant of 2026-08-03T00:00:00Z"
    )
    assert read_project(ctx["project"]["id"])["launch_readiness_pct"] == pytest.approx(
        80.00, abs=0.01
    )


def test_booking_a_pilot_run_lands_on_the_project_ledger(api):
    """A SCHEDULED run is already a live commitment against the cap.

    PRD: "Committed development spend is a **conserved quantity**, not a running total.
    `development_budget_committed_usd` on a project is, at every observable instant, exactly the
    sum of `committed_cost_usd` across that project's live pilot runs — those whose `status` is
    `SCHEDULED`, `RUNNING` or `COMPLETED` — plus `committed_cost_usd` across its live stability
    studies — those whose `status` is `ACTIVE`, `PASSED` or `FAILED` — rounded half up to two
    decimal places."

    Design: Corner/state_machines/sm_run_and_study_commitments_sync_the_project_ledger
    """
    ctx = _ledger_project()
    assert ctx["project"]["development_budget_committed_usd"] == pytest.approx(0.00, abs=0.01)

    run = validate_success(
        api.create_pilot_run(
            ctx["formulation"]["id"],
            {
                "pilot_line_id": ctx["pilot_line"]["id"],
                "window_start": "2026-08-10T08:00:00Z",
                "window_end": "2026-08-10T20:00:00Z",
                "planned_units": 10000,
                "committed_cost_usd": 60000.00,
            },
            make_rnd_lead_headers("rnd-lg"),
        ),
        201,
    )

    assert run["status"] == "SCHEDULED"
    assert run["committed_cost_usd"] == pytest.approx(60000.00, abs=0.01)
    project = read_project(ctx["project"]["id"])
    assert project["development_budget_committed_usd"] == pytest.approx(60000.00, abs=0.01)
    assert project["development_budget_cap_usd"] == pytest.approx(500000.00, abs=0.01)


def test_opening_a_study_adds_its_commitment_to_the_same_ledger(api):
    """A completed run and an ACTIVE study are both live, so the ledger is their exact sum.

    PRD: "The study starts `ACTIVE` with an empty `timepoints` list, `min_quality_score` null
    and `verdict` null, and its `committed_cost_usd` joins the project's live commitments
    immediately — so the same `ERR_DEV_BUDGET_EXCEEDED` cap applies here as to pilot runs."
    PRD: "A run or study belongs to the project through the formulation it hangs off."

    Design: Corner/state_machines/sm_run_and_study_commitments_sync_the_project_ledger
    """
    ctx = _ledger_project()
    run = book_pilot_run(
        ctx["formulation"]["id"], ctx["pilot_line"]["id"],
        window_start="2026-08-10T08:00:00Z", window_end="2026-08-10T20:00:00Z",
        planned_units=10000, committed_cost_usd=60000.00,
    )
    set_clock("2026-08-10T08:00:00Z")
    start_pilot_run(run["id"])
    completed = complete_pilot_run(run["id"], 10000)
    assert completed["status"] == "COMPLETED"
    assert read_project(ctx["project"]["id"])[
        "development_budget_committed_usd"
    ] == pytest.approx(60000.00, abs=0.01), "a COMPLETED run is still a live commitment"

    study = open_shelf_life_study(
        ctx["formulation"]["id"], duration_days=180, committed_cost_usd=40000.00,
        start_at="2026-08-11T00:00:00Z",
    )

    assert study["status"] == "ACTIVE"
    assert study["timepoints"] == []
    assert study["verdict"] is None
    assert study["min_quality_score"] is None
    assert study["committed_cost_usd"] == pytest.approx(40000.00, abs=0.01)
    project = read_project(ctx["project"]["id"])
    assert project["development_budget_committed_usd"] == pytest.approx(100000.00, abs=0.01), (
        "60000.00 of live run cost plus 40000.00 of live study cost"
    )


def test_a_close_that_misses_the_financial_hurdles_is_refused(api):
    """Two of the three bars are missed and the case stays unlocked at COMPUTED.

    PRD: "A gate's passing branches require the project's authoritative case to clear all three
    of the gate's bars together: `npv_usd` at or above `npv_hurdle_usd`, `payback_months` at or
    below `payback_months_max`, and `gross_margin_pct` at or above `gross_margin_floor_pct`.
    Missing any one on a passing close answers `ERR_BUSINESS_CASE_HURDLE_NOT_MET` (422)."

    Design: Corner/consistency model/cs_a_refused_close_leaves_every_side_effect_unwritten
    """
    ctx = _review_missing_the_hurdles()
    case = validate_success(api.get_business_case(ctx["business_case"]["id"], ADMIN))
    assert case["npv_usd"] == pytest.approx(-76589.03, abs=0.01)
    assert case["payback_months"] == 999, "the three modelled years never repay the capex"
    assert case["gross_margin_pct"] == pytest.approx(44.44, abs=0.01)

    response = api.close_gate_review(
        ctx["review"]["id"], {}, make_gate_chair_headers("chair-at")
    )

    validate_error(response, "ERR_BUSINESS_CASE_HURDLE_NOT_MET", 422)
    unlocked = validate_success(api.get_business_case(ctx["business_case"]["id"], ADMIN))
    assert unlocked["status"] == "COMPUTED", "the COMPUTED to LOCKED move belongs to a pass"
    assert unlocked["version"] == case["version"]


def test_the_refused_close_leaves_the_review_project_and_ballots_unmoved(api):
    """Not one of the passing branch's side effects was written.

    PRD: "The review's `decision` becomes `PASSED`, `closed_at` takes the current instant,
    `chair_user_id` takes the acting identifier, and `deliverable_completeness_pct` and
    `readiness_index` are recomputed and re-frozen at their closing values."
    PRD: "Cascades are not best-effort: every secondary effect named in §3 is part of the same
    accepted write as the primary effect, and each mutated row refreshes its own `updated_at`
    and increments its own `version` per §2.4."

    Design: Corner/consistency model/cs_a_refused_close_leaves_every_side_effect_unwritten
    """
    ctx = _review_missing_the_hurdles()
    project_version_before = ctx["project"]["version"]

    validate_error(
        api.close_gate_review(ctx["review"]["id"], {}, make_gate_chair_headers("chair-at")),
        "ERR_BUSINESS_CASE_HURDLE_NOT_MET",
        422,
    )

    review = validate_success(api.get_gate_review(ctx["review"]["id"], ADMIN))
    assert review["status"] == "IN_SESSION"
    assert review["decision"] is None
    assert review["closed_at"] is None
    assert review["chair_user_id"] is None
    assert review["vote_count"] == 1, "the ballot already cast is untouched"
    _, vote_meta = validate_paginated(api.list_gate_votes(ctx["review"]["id"], ADMIN))
    assert vote_meta["total_count"] == 1
    project = read_project(ctx["project"]["id"])
    assert project["dev_status"] == "SCREENED"
    assert project["next_gate_number"] == 2
    assert project["recycle_count"] == 0
    assert project["open_gate_conditions"] is False
    assert project["version"] == project_version_before


def test_the_gate_snapshot_stays_frozen_while_the_live_checklist_moves(api):
    """The review keeps the 50.00 it froze at opening until the close re-freezes it.

    PRD: "Opening computes and stores `deliverable_completeness_pct` and `readiness_index`;
    note carefully that **checklist completeness is not required to open** a review, only to
    close one on a passing branch."
    PRD: "The review's `decision` becomes `PASSED`, `closed_at` takes the current instant,
    `chair_user_id` takes the acting identifier, and `deliverable_completeness_pct` and
    `readiness_index` are recomputed and re-frozen at their closing values."

    Design: Corner/consistency model/cs_frozen_gate_snapshot_and_live_aggregate_disagree_by_design
    """
    ctx = _half_complete_session()
    assert ctx["review"]["deliverable_completeness_pct"] == pytest.approx(50.00, abs=0.01), (
        "one of the two required types was APPROVED when the session opened"
    )

    submit_deliverable(ctx["sales"]["id"], submitter_user_id="sub-fz")
    decide_deliverable(ctx["sales"]["id"], "APPROVE", decider_user_id="rev-fz")

    stale = validate_success(api.get_gate_review(ctx["review"]["id"], ADMIN))
    assert stale["deliverable_completeness_pct"] == pytest.approx(50.00, abs=0.01), (
        "the stored snapshot is not recomputed on read"
    )
    _, approved_meta = validate_paginated(
        api.list_deliverables(
            ADMIN,
            params={
                "project_id": ctx["project"]["id"], "gate_id": ctx["gate2"]["id"],
                "status": "APPROVED",
            },
        )
    )
    assert approved_meta["total_count"] == 2, "the live checklist has moved on to both types"

    cast_vote(ctx["review"]["id"], function="OPERATIONS", vote="APPROVE",
              voter_user_id="rev-ops-fz", rationale="Both readiness packs are in.")
    closed = validate_success(
        api.close_gate_review(ctx["review"]["id"], {}, make_gate_chair_headers("chair-fz"))
    )

    assert closed["decision"] == "PASSED"
    assert closed["deliverable_completeness_pct"] == pytest.approx(100.00, abs=0.01), (
        "the close re-freezes the figure at its closing value"
    )
    assert read_project(ctx["project"]["id"])["dev_status"] == "PILOT_QUALIFIED"


def test_launch_readiness_reads_zero_while_no_gate_advances_into_launch_ready(api):
    """With no commercialisation gate configured the required set is empty, so the figure is 0.00.

    PRD: "The required set is the intersection of those four types with the
    `required_deliverable_types` of the stage gate whose `stage_to` is `LAUNCH_READY`."
    PRD: "`launch_readiness_pct` is `0.00` when the denominator is zero, and otherwise the
    numerator divided by the denominator, multiplied by 100, rounded half up to two decimal
    places."

    Design: Corner/consistency model/cs_frozen_gate_snapshot_and_live_aggregate_disagree_by_design
    """
    ctx = _half_complete_session()
    project_id = ctx["project"]["id"]
    opening_view = validate_success(api.get_launch_readiness(project_id, ADMIN))
    assert opening_view["launch_readiness_pct"] == pytest.approx(0.00, abs=0.01)
    assert opening_view["blocking_deliverable_types"] == []

    submit_deliverable(ctx["sales"]["id"], submitter_user_id="sub-fz")
    decide_deliverable(ctx["sales"]["id"], "APPROVE", decider_user_id="rev-fz")
    after_approval = validate_success(api.get_launch_readiness(project_id, ADMIN))
    cast_vote(ctx["review"]["id"], function="OPERATIONS", vote="APPROVE",
              voter_user_id="rev-ops-fz", rationale="Both readiness packs are in.")
    close_gate_review(ctx["review"]["id"], "chair-fz")
    after_close = validate_success(api.get_launch_readiness(project_id, ADMIN))

    assert after_approval["launch_readiness_pct"] == pytest.approx(0.00, abs=0.01), (
        "approving a readiness type raises nothing while the required set is empty"
    )
    assert after_close["launch_readiness_pct"] == pytest.approx(0.00, abs=0.01)
    assert after_close["blocking_deliverable_types"] == []
    assert read_project(project_id)["launch_readiness_pct"] == pytest.approx(0.00, abs=0.01)
