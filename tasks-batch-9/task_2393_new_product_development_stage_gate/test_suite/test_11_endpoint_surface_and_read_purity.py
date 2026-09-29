"""Status-code discipline, reverse reachability of every stored reference, the mutated
row returned by each transition, the computed launch-readiness read and read purity."""
import pytest

from test_helpers import (
    add_forecast_line,
    book_pilot_run,
    business_case_payload,
    cast_vote,
    complete_pilot_run,
    concept_test_payload,
    create_formulation,
    deliverable_payload,
    draft_label,
    forecast_line_payload,
    formulation_payload,
    gate_review_payload,
    gate_vote_payload,
    intake_project,
    label_approval_payload,
    make_functional_reviewer_headers,
    make_gate_chair_headers,
    make_innovation_lead_headers,
    make_portfolio_admin_headers,
    make_rnd_lead_headers,
    open_business_case,
    open_gate_review,
    open_reset_window,
    open_shelf_life_study,
    pilot_line_payload,
    pilot_run_payload,
    project_payload,
    read_formulation,
    read_project,
    record_concept_test,
    register_pilot_line,
    register_retailer,
    register_stage_gate,
    retailer_payload,
    schedule_gate_review,
    screen_project,
    set_clock,
    shelf_life_study_payload,
    shelf_reset_window_payload,
    stage_gate_payload,
    start_pilot_run,
    timepoint_payload,
    validate_paginated,
    validate_success,
)

SNACK_IDEA = {
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

TOP_DOWN_CASE = {
    "variant_mode": "TOP_DOWN",
    "category_size_units_year": 4000000,
    "target_share_pct": 4.00,
    "cogs_per_unit_usd": 2.5000,
    "slotting_fees_usd": 0.00,
    "capex_usd": 100000.00,
    "discount_rate_pct": 10.00,
}

GROCERY_LINE = {
    "channel": "GROCERY",
    "store_count": 2000,
    "base_velocity_units_per_store_week": 1.00,
    "promo_weeks": 0,
    "promo_lift_pct": 0.00,
    "list_price_usd": 5.0000,
}

MONADIC_STUDY = {
    "test_type": "MONADIC",
    "sample_size": 300,
    "purchase_intent_top2_pct": 80.00,
    "uniqueness_pct": 40.00,
    "fielded_at": "2026-07-01T00:00:00Z",
}


def _reference_world(api):
    """One project carrying at least one row of every child kind, all cross-linked."""
    set_clock("2026-08-03T00:00:00Z")
    chair = make_gate_chair_headers("chair-rr")
    gate2 = register_stage_gate(
        gate_number=2, category="SNACK", stage_from="SCREENED",
        stage_to="PILOT_QUALIFIED", required_deliverable_types=[], quorum_size=1,
        payback_months_max=24,
    )
    retailer = register_retailer(name="MidStates Grocery", channel="GROCERY",
                                acv_contribution_pct=30.00, presentation_lead_days=14)
    window = open_reset_window(retailer["id"], category="SNACK",
                               window_start="2026-10-05T00:00:00Z",
                               window_end="2026-11-30T00:00:00Z", max_presentations=2)
    pilot_line = register_pilot_line(plant_name="Toledo", line_code="TOL-23",
                                     changeover_buffer_minutes=240, allergen_regime="NONE",
                                     hourly_cost_usd=500.00)
    project = intake_project(owner_user_id="lead-rr", **dict(SNACK_IDEA))
    concept_test = record_concept_test(project["id"], **MONADIC_STUDY)
    screen_project(project["id"], chair_user_id="chair-rr", screening_notes="Into stage 2.")
    business_case = open_business_case(project["id"], **TOP_DOWN_CASE)
    forecast_line = add_forecast_line(business_case["id"], **GROCERY_LINE)
    first_item = validate_success(
        api.create_deliverable(
            project["id"],
            deliverable_payload(gate2["id"], deliverable_type="CONSUMER_CONCEPT_TEST",
                                owner_function="MARKETING"),
            chair,
        ),
        201,
    )
    second_item = validate_success(
        api.create_deliverable(
            project["id"],
            deliverable_payload(gate2["id"], deliverable_type="PILOT_SCALE_UP_REPORT",
                                owner_function="OPERATIONS"),
            chair,
        ),
        201,
    )
    validate_success(
        api.set_deliverable_prerequisite(
            second_item["id"], {"prerequisite_deliverable_id": first_item["id"]}, chair
        )
    )
    review = schedule_gate_review(project["id"], gate2["id"], chair_user_id="chair-rr",
                                  scheduled_at="2026-08-12T09:00:00Z")
    open_gate_review(review["id"], chair_user_id="chair-rr")
    vote = cast_vote(review["id"], function="OPERATIONS", vote="APPROVE",
                     voter_user_id="rev-ops-rr", rationale="Feasible.")
    formulation = create_formulation(project["id"],
                                     spec_summary="Toffee inclusion at 12 percent",
                                     allergen_regime="NONE", target_shelf_life_days=180,
                                     unit_cost_usd=2.5000)
    pilot_run = book_pilot_run(formulation["id"], pilot_line["id"],
                               window_start="2026-08-01T08:00:00Z",
                               window_end="2026-08-01T16:00:00Z", planned_units=10000,
                               committed_cost_usd=10000.00)
    start_pilot_run(pilot_run["id"])
    complete_pilot_run(pilot_run["id"], 10000)
    study = open_shelf_life_study(formulation["id"], duration_days=180,
                                  committed_cost_usd=20000.00,
                                  start_at="2026-08-05T00:00:00Z")
    label = draft_label(project["id"], formulation["id"], label_version="v1",
                        claims=["Made with real toffee"])
    return {
        "gate2": gate2, "retailer": retailer, "window": window, "pilot_line": pilot_line,
        "project": project, "concept_test": concept_test, "business_case": business_case,
        "forecast_line": forecast_line, "first_item": first_item,
        "second_item": second_item, "review": review, "vote": vote,
        "formulation": formulation, "pilot_run": pilot_run, "study": study, "label": label,
    }


def _launch_readiness_world(api):
    """A snack project with both readiness items of its commercialisation gate outstanding."""
    set_clock("2026-08-03T00:00:00Z")
    chair = make_gate_chair_headers("chair-lr")
    gate3 = register_stage_gate(
        gate_number=3, category="SNACK", stage_from="PILOT_QUALIFIED",
        stage_to="LAUNCH_READY",
        required_deliverable_types=["MANUFACTURING_READINESS", "SALES_SELL_IN_PLAN"],
        quorum_size=1, payback_months_max=24,
    )
    project = intake_project(owner_user_id="lead-lr", **dict(SNACK_IDEA))
    manufacturing = validate_success(
        api.create_deliverable(
            project["id"],
            deliverable_payload(gate3["id"], deliverable_type="MANUFACTURING_READINESS",
                                owner_function="OPERATIONS"),
            chair,
        ),
        201,
    )
    sales = validate_success(
        api.create_deliverable(
            project["id"],
            deliverable_payload(gate3["id"], deliverable_type="SALES_SELL_IN_PLAN",
                                owner_function="SALES"),
            chair,
        ),
        201,
    )
    return project, gate3, manufacturing, sales


def _approve_manufacturing(api, manufacturing_id):
    """Submit and approve the manufacturing item through two different identifiers."""
    validate_success(
        api.submit_deliverable(
            manufacturing_id, {"evidence_url": "https://npd.example/lr/mfg"},
            make_innovation_lead_headers("sub-lr"),
        )
    )
    validate_success(
        api.decide_deliverable(
            manufacturing_id, {"decision": "APPROVE", "comment": "Line qualified."},
            make_functional_reviewer_headers("rev-lr"),
        )
    )


def test_every_row_creating_call_answers_201_with_its_audit_fields(api):
    """Fifteen different creations all answer 201, and each body carries the four audit
    fields except the ballot, which carries no version at all.

    PRD: "Operations that create a new stored row return `201 Created`."
    PRD: "Alongside `id`, every entity in this system also carries `created_at`,
    `updated_at` and `version`: `created_at` and `updated_at` are ISO 8601 UTC timestamps
    with three fractional digits, and `version` is an integer that starts at 1 on insert and
    increments by one on every accepted write to that row. There is exactly one exception —
    `GateVote` is immutable once cast and therefore carries only `id` and `created_at`; it
    has neither `updated_at` nor `version`."

    Design: Corner/endpoints/ep_creations_return_201_while_transitions_and_reads_return_200
    """
    set_clock("2026-08-03T00:00:00Z")
    admin = make_portfolio_admin_headers("admin-sc")
    lead = make_innovation_lead_headers("lead-sc")
    chair = make_gate_chair_headers("chair-sc")
    rnd = make_rnd_lead_headers("rnd-sc")
    created = {}

    created["stage gate"] = validate_success(
        api.create_stage_gate(
            stage_gate_payload(gate_number=2, category="SNACK",
                               required_deliverable_types=[], quorum_size=1,
                               payback_months_max=24),
            admin,
        ),
        201,
    )
    created["retailer"] = validate_success(
        api.create_retailer(
            retailer_payload(name="MidStates Grocery", acv_contribution_pct=30.00,
                             presentation_lead_days=14),
            admin,
        ),
        201,
    )
    created["reset window"] = validate_success(
        api.create_shelf_reset_window(
            created["retailer"]["id"],
            shelf_reset_window_payload(category="SNACK",
                                       window_start="2026-10-05T00:00:00Z",
                                       window_end="2026-11-30T00:00:00Z"),
            admin,
        ),
        201,
    )
    created["pilot line"] = validate_success(
        api.create_pilot_line(
            pilot_line_payload(plant_name="Toledo", line_code="TOL-21",
                               hourly_cost_usd=500.00),
            admin,
        ),
        201,
    )
    created["project"] = validate_success(
        api.create_project(project_payload(**SNACK_IDEA), lead), 201
    )
    project_id = created["project"]["id"]
    created["concept test"] = validate_success(
        api.create_concept_test(project_id, concept_test_payload(**MONADIC_STUDY), lead), 201
    )
    screened = validate_success(
        api.screen_project(project_id, {"screening_notes": "Into stage 2."}, chair)
    )
    created["business case"] = validate_success(
        api.create_business_case(
            project_id, business_case_payload(screened["version"], **TOP_DOWN_CASE), lead
        ),
        201,
    )
    created["forecast line"] = validate_success(
        api.create_forecast_line(
            created["business case"]["id"], forecast_line_payload(**GROCERY_LINE), lead
        ),
        201,
    )
    created["checklist item"] = validate_success(
        api.create_deliverable(
            project_id,
            deliverable_payload(created["stage gate"]["id"],
                                deliverable_type="PILOT_SCALE_UP_REPORT",
                                owner_function="OPERATIONS"),
            chair,
        ),
        201,
    )
    created["gate review"] = validate_success(
        api.create_gate_review(
            project_id,
            gate_review_payload(created["stage gate"]["id"],
                                scheduled_at="2026-08-12T09:00:00Z"),
            chair,
        ),
        201,
    )
    validate_success(api.open_gate_review(created["gate review"]["id"], {}, chair))
    created["gate vote"] = validate_success(
        api.cast_gate_vote(
            created["gate review"]["id"],
            gate_vote_payload(rationale="Scale-up feasible."),
            make_functional_reviewer_headers("rev-ops-sc"),
        ),
        201,
    )
    created["formulation"] = validate_success(
        api.create_formulation(
            project_id,
            formulation_payload(read_project(project_id)["version"],
                                spec_summary="Toffee inclusion at 12 percent",
                                target_shelf_life_days=180, unit_cost_usd=2.5000),
            rnd,
        ),
        201,
    )
    created["pilot run"] = validate_success(
        api.create_pilot_run(
            created["formulation"]["id"],
            pilot_run_payload(created["pilot line"]["id"],
                              window_start="2026-08-01T08:00:00Z",
                              window_end="2026-08-01T16:00:00Z", planned_units=10000,
                              committed_cost_usd=10000.00),
            rnd,
        ),
        201,
    )
    start_pilot_run(created["pilot run"]["id"])
    complete_pilot_run(created["pilot run"]["id"], 10000)
    created["stability study"] = validate_success(
        api.create_shelf_life_study(
            created["formulation"]["id"],
            shelf_life_study_payload(read_formulation(created["formulation"]["id"])["version"],
                                     duration_days=180, committed_cost_usd=20000.00,
                                     start_at="2026-08-05T00:00:00Z"),
            rnd,
        ),
        201,
    )
    created["label approval"] = validate_success(
        api.create_label_approval(
            project_id,
            label_approval_payload(created["formulation"]["id"], label_version="v1",
                                   claims=["Made with real toffee"]),
            lead,
        ),
        201,
    )

    assert len(created) == 15, "every distinct creation shape is exercised once"
    for label, row in created.items():
        assert row["id"], f"the {label} creation returns the new row's id"
        assert row["created_at"], f"the {label} creation stamps created_at"
        if label == "gate vote":
            assert "version" not in row and "updated_at" not in row, (
                "a ballot is append-only and carries neither field"
            )
        else:
            assert row["version"] == 1, f"the {label} row starts at version 1"
            assert row["updated_at"], f"the {label} row carries updated_at"


def test_the_clock_setter_transitions_and_reads_all_answer_200(api,
                                                              portfolio_admin_headers,
                                                              sales_account_manager_headers):
    """Setting the clock, six state transitions and two reads all answer 200, and none of
    them answers 201.

    PRD: "Operations that mutate an existing row — every state transition, every waiver,
    every decision, the clock setter, and the launch date lock — return `200 OK`, as do all
    reads."

    PRD: "Every stored resource is addressed by an `id` that the server mints as a UUID."

    Design: Corner/endpoints/ep_creations_return_201_while_transitions_and_reads_return_200
    """
    clock = validate_success(
        api.set_clock({"to_iso8601": "2026-08-03T00:00:00Z"}, portfolio_admin_headers)
    )
    assert clock["current_utc"].startswith("2026-08-03T00:00:00"), (
        f"the clock setter echoes the instant it was moved to, got {clock['current_utc']!r}"
    )

    chair = make_gate_chair_headers("chair-t2")
    gate2 = register_stage_gate(
        gate_number=2, category="SNACK", stage_from="SCREENED",
        stage_to="PILOT_QUALIFIED", required_deliverable_types=[], quorum_size=1,
        payback_months_max=24,
    )
    project = intake_project(owner_user_id="lead-t2", **dict(SNACK_IDEA))
    pilot_line = register_pilot_line(plant_name="Toledo", line_code="TOL-22",
                                     hourly_cost_usd=500.00)

    screened = validate_success(
        api.screen_project(project["id"], {"screening_notes": "Into stage 2."}, chair)
    )
    assert screened["dev_status"] == "SCREENED"

    item = validate_success(
        api.create_deliverable(
            project["id"],
            deliverable_payload(gate2["id"], deliverable_type="PILOT_SCALE_UP_REPORT",
                                owner_function="OPERATIONS"),
            chair,
        ),
        201,
    )
    submitted = validate_success(
        api.submit_deliverable(
            item["id"], {"evidence_url": "https://npd.example/t2/scale-up"},
            make_rnd_lead_headers("sub-t2"),
        )
    )
    assert submitted["status"] == "SUBMITTED"
    decided = validate_success(
        api.decide_deliverable(
            item["id"], {"decision": "APPROVE", "comment": "Yield acceptable."},
            make_functional_reviewer_headers("rev-t2"),
        )
    )
    assert decided["status"] == "APPROVED"

    review = schedule_gate_review(project["id"], gate2["id"], chair_user_id="chair-t2",
                                  scheduled_at="2026-08-12T09:00:00Z")
    opened = validate_success(api.open_gate_review(review["id"], {}, chair))
    assert opened["status"] == "IN_SESSION"

    formulation = create_formulation(project["id"],
                                     spec_summary="Toffee inclusion at 12 percent",
                                     target_shelf_life_days=180, unit_cost_usd=2.5000)
    pilot_run = book_pilot_run(formulation["id"], pilot_line["id"],
                               window_start="2026-08-01T08:00:00Z",
                               window_end="2026-08-01T16:00:00Z", planned_units=10000,
                               committed_cost_usd=10000.00)
    started = validate_success(
        api.start_pilot_run(pilot_run["id"], {}, make_rnd_lead_headers("rnd-t2"))
    )
    assert started["status"] == "RUNNING"
    completed = validate_success(
        api.complete_pilot_run(pilot_run["id"], {"actual_units": 10000},
                               make_rnd_lead_headers("rnd-t2"))
    )
    assert completed["status"] == "COMPLETED"

    validate_success(api.get_project(project["id"], sales_account_manager_headers))
    readiness = validate_success(
        api.get_launch_readiness(project["id"], sales_account_manager_headers)
    )
    assert "earliest_lockable_date" in readiness, (
        "the launch-readiness read returns a computed object rather than a stored row"
    )


def test_every_parent_scoped_collection_reaches_its_stored_children(api,
                                                                   portfolio_admin_headers):
    """Each nested collection read returns exactly the child stored under that parent, and
    the two empty ones answer with a count of zero rather than a not-found.

    PRD: "Both `limit` and `offset` are echoed in the `meta` object alongside `total_count`
    (the number of rows matching the filters before pagination) and `has_more` (true when
    rows remain beyond the current page)."
    PRD: "Every write endpoint returns the affected primary resource in `data`; the
    launch-readiness read returns a computed object rather than a stored row."

    Design: Corner/endpoints/ep_every_stored_reference_is_reverse_reachable
    """
    world = _reference_world(api)
    project_id = world["project"]["id"]

    expectations = [
        (api.list_concept_tests(project_id, portfolio_admin_headers),
         world["concept_test"]["id"]),
        (api.list_business_cases(project_id, portfolio_admin_headers),
         world["business_case"]["id"]),
        (api.list_forecast_lines(world["business_case"]["id"], portfolio_admin_headers),
         world["forecast_line"]["id"]),
        (api.list_formulations(project_id, portfolio_admin_headers),
         world["formulation"]["id"]),
        (api.list_shelf_life_studies(world["formulation"]["id"], portfolio_admin_headers),
         world["study"]["id"]),
        (api.list_shelf_reset_windows(world["retailer"]["id"], portfolio_admin_headers),
         world["window"]["id"]),
        (api.list_gate_votes(world["review"]["id"], portfolio_admin_headers),
         world["vote"]["id"]),
    ]
    for response, expected_id in expectations:
        rows, meta = validate_paginated(response)
        assert meta["total_count"] == 1, (
            f"expected exactly one child row, got {meta['total_count']}"
        )
        assert [row["id"] for row in rows] == [expected_id]

    empty, meta = validate_paginated(
        api.list_post_launch_periods(project_id, portfolio_admin_headers)
    )
    assert empty == [] and meta["total_count"] == 0 and meta["has_more"] is False, (
        "the reverse route exists before any post-launch row does"
    )


def test_every_flat_collection_filter_reaches_the_reference_it_names(api,
                                                                    portfolio_admin_headers):
    """The flat collections reach each stored foreign key through its declared filter,
    including the prerequisite edge and the window reference on the project.

    PRD: "List endpoints also accept optional equality filters drawn from the listed
    entity's own fields. Stage gates filter on `category` and `gate_number`; retailers and
    pilot lines on `channel` and `allergen_regime` respectively; reset windows on `category`;
    projects on `dev_status`, `commercial_status`, `category` and `shelf_reset_window_id`;
    business cases on `status` and `variant_mode`; checklist items on `project_id`,
    `gate_id`, `prerequisite_deliverable_id`, `status` and `owner_function`; gate reviews on
    `project_id`, `gate_id` and `status`; formulations and stability studies on `status`;
    pilot runs on `formulation_id`, `pilot_line_id` and `status`; label approvals on
    `project_id`, `formulation_id` and `status`; trade presentations on `project_id`,
    `retailer_id`, `shelf_reset_window_id` and `status`."
    PRD: "- Checklist items are ordered by `created_at` ascending, then `deliverable_type`
    ascending."

    Design: Corner/endpoints/ep_every_stored_reference_is_reverse_reachable
    """
    world = _reference_world(api)
    project_id = world["project"]["id"]

    items, items_meta = validate_paginated(
        api.list_deliverables(
            portfolio_admin_headers,
            params={"project_id": project_id, "gate_id": world["gate2"]["id"]},
        )
    )
    assert items_meta["total_count"] == 2
    assert [row["id"] for row in items] == [
        world["first_item"]["id"], world["second_item"]["id"]
    ], "the checklist reads back in creation order"

    dependents, dependents_meta = validate_paginated(
        api.list_deliverables(
            portfolio_admin_headers,
            params={"prerequisite_deliverable_id": world["first_item"]["id"]},
        )
    )
    assert dependents_meta["total_count"] == 1
    assert [row["id"] for row in dependents] == [world["second_item"]["id"]], (
        "the prerequisite edge is walkable from the prerequisite to its dependent"
    )

    reviews, reviews_meta = validate_paginated(
        api.list_gate_reviews(
            portfolio_admin_headers,
            params={"project_id": project_id, "gate_id": world["gate2"]["id"]},
        )
    )
    assert reviews_meta["total_count"] == 1
    assert [row["id"] for row in reviews] == [world["review"]["id"]]

    runs, runs_meta = validate_paginated(
        api.list_pilot_runs(
            portfolio_admin_headers,
            params={"formulation_id": world["formulation"]["id"],
                    "pilot_line_id": world["pilot_line"]["id"]},
        )
    )
    assert runs_meta["total_count"] == 1
    assert [row["id"] for row in runs] == [world["pilot_run"]["id"]]

    labels, labels_meta = validate_paginated(
        api.list_label_approvals(
            portfolio_admin_headers,
            params={"project_id": project_id,
                    "formulation_id": world["formulation"]["id"]},
        )
    )
    assert labels_meta["total_count"] == 1
    assert [row["id"] for row in labels] == [world["label"]["id"]]

    presentations, presentations_meta = validate_paginated(
        api.list_sell_in_presentations(
            portfolio_admin_headers,
            params={"project_id": project_id, "retailer_id": world["retailer"]["id"],
                    "shelf_reset_window_id": world["window"]["id"]},
        )
    )
    assert presentations == [] and presentations_meta["total_count"] == 0
    assert presentations_meta["has_more"] is False

    parked, parked_meta = validate_paginated(
        api.list_projects(portfolio_admin_headers,
                          params={"shelf_reset_window_id": world["window"]["id"]})
    )
    assert parked == [] and parked_meta["total_count"] == 0, (
        "no launch lock has parked the window on a project yet"
    )


def test_a_transition_answers_with_the_row_it_just_changed(api, portfolio_admin_headers):
    """Screening and submitting each answer with the mutated row, already recomputed and
    identical to a follow-up read at a strictly greater version.

    PRD: "Every write endpoint returns the affected primary resource in `data`; the
    launch-readiness read returns a computed object rather than a stored row."
    PRD: "An accepted submission records `evidence_url` and the acting opaque identifier as
    `submitted_by_user_id`, and increments `submission_count`."

    Design: Corner/endpoints/ep_transition_endpoints_return_the_mutated_row
    """
    set_clock("2026-08-03T00:00:00Z")
    chair = make_gate_chair_headers("chair-rs")
    gate2 = register_stage_gate(
        gate_number=2, category="SNACK", stage_from="SCREENED",
        stage_to="PILOT_QUALIFIED", required_deliverable_types=[], quorum_size=1,
        payback_months_max=24,
    )
    project = intake_project(owner_user_id="lead-rs", **dict(SNACK_IDEA))
    item = validate_success(
        api.create_deliverable(
            project["id"],
            deliverable_payload(gate2["id"], deliverable_type="PILOT_SCALE_UP_REPORT",
                                owner_function="OPERATIONS"),
            chair,
        ),
        201,
    )

    screened = validate_success(
        api.screen_project(project["id"], {"screening_notes": "Into stage 2."}, chair)
    )
    submitted = validate_success(
        api.submit_deliverable(
            item["id"], {"evidence_url": "https://npd.example/rs/scale-up"},
            make_rnd_lead_headers("sub-rs"),
        )
    )

    assert screened["id"] == project["id"]
    assert screened["screening_score"] == pytest.approx(79.00, abs=0.01)
    assert screened["screening_decision"] == "PASSED"
    assert screened["dev_status"] == "SCREENED", "the score arrives in one round trip"
    assert screened["version"] > project["version"]
    assert screened == read_project(project["id"]), (
        "the transition body already is the row a follow-up read returns"
    )

    assert submitted["id"] == item["id"]
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submission_count"] == 1
    assert submitted["submitted_by_user_id"] == "sub-rs"
    assert submitted["evidence_url"] == "https://npd.example/rs/scale-up"
    assert submitted["version"] > item["version"]
    assert submitted == validate_success(
        api.get_deliverable(item["id"], portfolio_admin_headers)
    ), "the submit body already is the row a follow-up read returns"


def test_appending_a_stability_observation_answers_with_the_parent_study(api):
    """A timepoint append returns the study it changed, rescored, and exposes no separate
    observation resource.

    PRD: "The study starts `ACTIVE` with an empty `timepoints` list, `min_quality_score`
    null and `verdict` null, and its `committed_cost_usd` joins the project's live
    commitments immediately — so the same `ERR_DEV_BUDGET_EXCEEDED` cap applies here as to
    pilot runs."
    PRD: "Each append refreshes `min_quality_score` to the lowest `quality_score` recorded
    so far."

    Design: Corner/endpoints/ep_transition_endpoints_return_the_mutated_row
    """
    set_clock("2026-08-03T00:00:00Z")
    project = intake_project(owner_user_id="lead-tp", **dict(SNACK_IDEA))
    pilot_line = register_pilot_line(plant_name="Toledo", line_code="TOL-24",
                                     hourly_cost_usd=500.00)
    formulation = create_formulation(project["id"],
                                     spec_summary="Toffee inclusion at 12 percent",
                                     target_shelf_life_days=180, unit_cost_usd=2.5000)
    pilot_run = book_pilot_run(formulation["id"], pilot_line["id"],
                               window_start="2026-08-01T08:00:00Z",
                               window_end="2026-08-01T16:00:00Z", planned_units=10000,
                               committed_cost_usd=10000.00)
    start_pilot_run(pilot_run["id"])
    complete_pilot_run(pilot_run["id"], 10000)
    study = open_shelf_life_study(formulation["id"], duration_days=180,
                                  committed_cost_usd=20000.00,
                                  start_at="2026-08-05T00:00:00Z")
    assert study["timepoints"] == []
    assert study["min_quality_score"] is None

    rescored = validate_success(
        api.add_timepoint(
            study["id"], timepoint_payload(day_index=30, quality_score=92.00),
            make_rnd_lead_headers("rnd-tp"),
        )
    )

    assert rescored["id"] == study["id"], (
        "the body is the parent study, not a new observation row with its own id"
    )
    assert rescored["min_quality_score"] == pytest.approx(92.00, abs=0.01)
    assert rescored["status"] == "ACTIVE", "day 30 of a 180 day plan closes nothing"
    assert len(rescored["timepoints"]) == 1, "the observation joined the stored series"
    assert rescored["verdict"] is None


def test_the_launch_readiness_read_renormalises_over_the_gate_it_answers_to(
        api, sales_account_manager_headers):
    """With two readiness types demanded, one approval reads 63.64 and leaves only the
    sales plan blocking.

    PRD: "Renormalisation matters: a gate demanding all four types shows `35.00` when only
    manufacturing is approved, whereas a gate demanding only manufacturing and sales shows
    `63.64` for the same single approval, and reaches `100.00` — the value that unlocks the
    date lock — with just those two approved."
    PRD: "A dedicated launch-readiness read exposes the live picture without storing
    anything new: the current `launch_readiness_pct`, a `blocking_deliverable_types` array
    listing the required readiness types not yet `APPROVED` in checklist order, the current
    `authorized_acv_pct`, the locked `launch_date` if any, and an `earliest_lockable_date`
    computed on every read as the current instant plus the 45-whole-day lock lead time."

    Design: Corner/endpoints/ep_launch_readiness_aggregate_tracks_the_clock_and_the_lock
    """
    project, _, manufacturing, _ = _launch_readiness_world(api)

    before = validate_success(
        api.get_launch_readiness(project["id"], sales_account_manager_headers)
    )
    assert before["launch_readiness_pct"] == pytest.approx(0.00, abs=0.01)
    assert before["blocking_deliverable_types"] == [
        "MANUFACTURING_READINESS", "SALES_SELL_IN_PLAN"
    ], "both required readiness types block, listed in checklist order"
    assert before["authorized_acv_pct"] == pytest.approx(0.00, abs=0.01)
    assert before["launch_date"] is None

    _approve_manufacturing(api, manufacturing["id"])

    after = validate_success(
        api.get_launch_readiness(project["id"], sales_account_manager_headers)
    )
    assert after["launch_readiness_pct"] == pytest.approx(63.64, abs=0.01), (
        "0.35 renormalised over 0.35 + 0.20 is 63.64, not 35.00"
    )
    assert after["blocking_deliverable_types"] == ["SALES_SELL_IN_PLAN"]
    assert after["launch_date"] is None


def test_the_earliest_lockable_date_follows_the_clock_without_any_write(
        api, sales_account_manager_headers):
    """Moving the clock ten days moves the earliest lockable date ten days while the
    readiness figure and the project's version stand still.

    PRD: "`earliest_lockable_date` is derived on demand and never persisted."
    PRD: "The `launch_date` must be at least 45 whole days after the current instant, else
    `ERR_LOCK_LEAD_TIME_VIOLATION` (409); because containment is checked first, a date both
    outside the window and too soon reports the containment error."

    Design: Corner/endpoints/ep_launch_readiness_aggregate_tracks_the_clock_and_the_lock
    """
    project, _, manufacturing, _ = _launch_readiness_world(api)
    _approve_manufacturing(api, manufacturing["id"])
    version_before = read_project(project["id"])["version"]

    first = validate_success(
        api.get_launch_readiness(project["id"], sales_account_manager_headers)
    )
    set_clock("2026-08-13T00:00:00Z")
    second = validate_success(
        api.get_launch_readiness(project["id"], sales_account_manager_headers)
    )

    assert first["earliest_lockable_date"].startswith("2026-09-17T00:00:00"), (
        f"45 whole days after 2026-08-03, got {first['earliest_lockable_date']!r}"
    )
    assert second["earliest_lockable_date"].startswith("2026-09-27T00:00:00"), (
        f"45 whole days after 2026-08-13, got {second['earliest_lockable_date']!r}"
    )
    assert second["launch_readiness_pct"] == pytest.approx(63.64, abs=0.01), (
        "only the date moved"
    )
    assert second["launch_date"] is None, "no lock has been taken"
    assert read_project(project["id"])["version"] == version_before, (
        "three computed reads wrote nothing back to the project"
    )


def test_a_full_read_sweep_leaves_every_version_and_computed_field_alone(
        api, portfolio_admin_headers, functional_reviewer_headers):
    """Eleven reads across every family leave version, updated_at, the authoritative flag
    and the case's net present value exactly where they were.

    PRD: "Operations that mutate an existing row — every state transition, every waiver,
    every decision, the clock setter, and the launch date lock — return `200 OK`, as do all
    reads."
    PRD: "`version` is an integer that starts at 1 on insert and increments by one on every
    accepted write to that row."

    Design: Corner/endpoints/ep_reads_never_mutate
    """
    set_clock("2026-08-03T00:00:00Z")
    chair = make_gate_chair_headers("chair-rp")
    gate2 = register_stage_gate(
        gate_number=2, category="SNACK", stage_from="SCREENED",
        stage_to="PILOT_QUALIFIED", required_deliverable_types=[], quorum_size=1,
        payback_months_max=24,
    )
    retailer = register_retailer(name="MidStates Grocery", channel="GROCERY",
                                acv_contribution_pct=30.00, presentation_lead_days=14)
    window = open_reset_window(retailer["id"], category="SNACK",
                               window_start="2026-10-05T00:00:00Z",
                               window_end="2026-11-30T00:00:00Z", max_presentations=2)
    pilot_line = register_pilot_line(plant_name="Toledo", line_code="TOL-25",
                                     hourly_cost_usd=500.00)
    project = intake_project(owner_user_id="lead-rp", **dict(SNACK_IDEA))
    concept_test = record_concept_test(project["id"], **MONADIC_STUDY)
    screen_project(project["id"], chair_user_id="chair-rp", screening_notes="Into stage 2.")
    business_case = open_business_case(project["id"], **TOP_DOWN_CASE)
    add_forecast_line(business_case["id"], **GROCERY_LINE)
    item = validate_success(
        api.create_deliverable(
            project["id"],
            deliverable_payload(gate2["id"], deliverable_type="PILOT_SCALE_UP_REPORT",
                                owner_function="OPERATIONS"),
            chair,
        ),
        201,
    )
    project_before = validate_success(api.get_project(project["id"], portfolio_admin_headers))
    case_before = validate_success(
        api.get_business_case(business_case["id"], portfolio_admin_headers)
    )
    item_before = validate_success(api.get_deliverable(item["id"], portfolio_admin_headers))
    assert case_before["npv_usd"] == pytest.approx(793643.87, abs=0.01)

    validate_success(api.get_project(project["id"], functional_reviewer_headers))
    first_readiness = validate_success(
        api.get_launch_readiness(project["id"], functional_reviewer_headers)
    )
    validate_paginated(api.list_concept_tests(project["id"], functional_reviewer_headers))
    validate_paginated(api.list_business_cases(project["id"], functional_reviewer_headers))
    validate_success(api.get_business_case(business_case["id"], functional_reviewer_headers))
    validate_paginated(
        api.list_forecast_lines(business_case["id"], functional_reviewer_headers)
    )
    validate_success(api.get_deliverable(item["id"], functional_reviewer_headers))
    validate_success(api.get_stage_gate(gate2["id"], functional_reviewer_headers))
    validate_success(api.get_shelf_reset_window(window["id"], functional_reviewer_headers))
    validate_success(api.get_pilot_line(pilot_line["id"], functional_reviewer_headers))
    validate_success(api.get_retailer(retailer["id"], functional_reviewer_headers))
    second_readiness = validate_success(
        api.get_launch_readiness(project["id"], functional_reviewer_headers)
    )

    project_after = validate_success(api.get_project(project["id"], portfolio_admin_headers))
    case_after = validate_success(
        api.get_business_case(business_case["id"], portfolio_admin_headers)
    )
    item_after = validate_success(api.get_deliverable(item["id"], portfolio_admin_headers))

    assert project_after["version"] == project_before["version"]
    assert case_after["version"] == case_before["version"]
    assert item_after["version"] == item_before["version"]
    assert project_after["updated_at"] == project_before["updated_at"]
    assert case_after["updated_at"] == case_before["updated_at"]
    assert item_after["updated_at"] == item_before["updated_at"]
    assert case_after["npv_usd"] == pytest.approx(793643.87, abs=0.01), (
        "the derived financials are recomputed on write, never on read"
    )
    tests, _ = validate_paginated(
        api.list_concept_tests(project["id"], portfolio_admin_headers)
    )
    assert [row["id"] for row in tests] == [concept_test["id"]]
    assert tests[0]["is_authoritative"] is True
    assert first_readiness["launch_readiness_pct"] == pytest.approx(0.00, abs=0.01)
    assert second_readiness["launch_readiness_pct"] == pytest.approx(0.00, abs=0.01), (
        "no commercialisation gate exists for this category, so the denominator is zero"
    )
