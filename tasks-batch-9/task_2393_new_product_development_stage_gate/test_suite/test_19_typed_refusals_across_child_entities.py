"""Typed not-found codes, configuration uniqueness, child-entity state and the R&D calendar."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    add_timepoint,
    book_pilot_run,
    create_formulation,
    deliverable_payload,
    draft_label,
    forecast_line_payload,
    intake_project,
    label_approval_payload,
    open_business_case,
    open_reset_window,
    pilot_line_payload,
    pilot_run_payload,
    read_formulation,
    read_project,
    read_window,
    register_pilot_line,
    register_retailer,
    register_stage_gate,
    retailer_payload,
    sell_in_presentation_payload,
    set_clock,
    setup_cleared_formulation,
    stage_gate_payload,
    start_pilot_run,
    timepoint_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

SNACK_GATE = {"gate_number": 2, "category": "SNACK", "stage_from": "SCREENED",
              "stage_to": "PILOT_QUALIFIED"}


def test_each_unresolved_path_identifier_answers_its_own_typed_not_found(
    api, portfolio_admin_headers
):
    """Thirteen reads against thirteen unknown identifiers report thirteen distinct codes.

    PRD: "**Path existence** — every identifier in the URL resolves to a stored row, resolved
    outer to inner, so a nested path with two unknown identifiers reports the outer resource
    first. Each resource family has its own 404 code: `ERR_PROJECT_NOT_FOUND` for a project,
    `ERR_STAGE_GATE_NOT_FOUND` for a gate configuration, `ERR_GATE_REVIEW_NOT_FOUND` for a
    review, `ERR_DELIVERABLE_NOT_FOUND` for a checklist item, `ERR_BUSINESS_CASE_NOT_FOUND` for
    a business case, `ERR_FORMULATION_NOT_FOUND` for a formulation revision,
    `ERR_PILOT_LINE_NOT_FOUND` for a pilot line, `ERR_PILOT_RUN_NOT_FOUND` for a pilot run,
    `ERR_SHELF_LIFE_STUDY_NOT_FOUND` for a stability study, `ERR_LABEL_APPROVAL_NOT_FOUND` for a
    label approval, `ERR_RETAILER_NOT_FOUND` for a retailer, `ERR_RESET_WINDOW_NOT_FOUND` for a
    reset window, and `ERR_PRESENTATION_NOT_FOUND` for a trade presentation."

    Design: Corner/errors/err_every_unresolved_id_reports_its_own_typed_not_found
    """
    probes = [
        (api.get_project, "ERR_PROJECT_NOT_FOUND"),
        (api.get_stage_gate, "ERR_STAGE_GATE_NOT_FOUND"),
        (api.get_gate_review, "ERR_GATE_REVIEW_NOT_FOUND"),
        (api.get_deliverable, "ERR_DELIVERABLE_NOT_FOUND"),
        (api.get_business_case, "ERR_BUSINESS_CASE_NOT_FOUND"),
        (api.get_formulation, "ERR_FORMULATION_NOT_FOUND"),
        (api.get_pilot_line, "ERR_PILOT_LINE_NOT_FOUND"),
        (api.get_pilot_run, "ERR_PILOT_RUN_NOT_FOUND"),
        (api.get_shelf_life_study, "ERR_SHELF_LIFE_STUDY_NOT_FOUND"),
        (api.get_label_approval, "ERR_LABEL_APPROVAL_NOT_FOUND"),
        (api.get_retailer, "ERR_RETAILER_NOT_FOUND"),
        (api.get_shelf_reset_window, "ERR_RESET_WINDOW_NOT_FOUND"),
        (api.get_sell_in_presentation, "ERR_PRESENTATION_NOT_FOUND"),
    ]

    reported = []
    for reader, expected_error_id in probes:
        response = reader(NON_EXISTENT_UUID, portfolio_admin_headers)
        validate_error(response, expected_error_id, 404)
        reported.append(expected_error_id)

    assert len(set(reported)) == 13, "each resource family carries its own not-found code"


def test_an_unresolved_prerequisite_reports_the_prerequisite_code_not_the_item_code(
    api, innovation_lead_headers, portfolio_admin_headers
):
    """Pointing a real item at an unknown prerequisite is a prerequisite 404, not an item 404.

    PRD: "Either way, if the named prerequisite does not resolve the answer is
    `ERR_PREREQUISITE_NOT_FOUND` (404), and if the proposed edge would close a loop in the
    project's existing prerequisite chain the answer is `ERR_DELIVERABLE_CYCLE` (409) — a
    self-edge is the shortest such loop and is rejected on exactly the same footing as a longer
    one, so the server walks the whole chain rather than only comparing the two endpoints."

    Design: Corner/errors/err_every_unresolved_id_reports_its_own_typed_not_found
    """
    set_clock("2026-08-03T00:00:00Z")
    gate = register_stage_gate(**SNACK_GATE)
    project = intake_project(owner_user_id="lead-nf", name="Toffee Crunch Bites",
                             category="SNACK", project_type="LINE_EXTENSION")
    item = validate_success(
        api.create_deliverable(project["id"], deliverable_payload(gate["id"]),
                               innovation_lead_headers),
        201,
    )

    response = api.set_deliverable_prerequisite(
        item["id"], {"prerequisite_deliverable_id": NON_EXISTENT_UUID}, innovation_lead_headers
    )

    validate_error(response, "ERR_PREREQUISITE_NOT_FOUND", 404)
    validate_error(
        api.set_deliverable_prerequisite(
            NON_EXISTENT_UUID, {"prerequisite_deliverable_id": item["id"]},
            innovation_lead_headers,
        ),
        "ERR_DELIVERABLE_NOT_FOUND",
        404,
    )
    stored = validate_success(api.get_deliverable(item["id"], portfolio_admin_headers))
    assert stored["prerequisite_deliverable_id"] is None, "the refused edge was never stored"


def test_body_references_answer_their_own_not_found_before_any_state_check(
    api, rnd_lead_headers, innovation_lead_headers, sales_account_manager_headers
):
    """A pilot line, a formulation, a retailer and a window each report their own 404.

    PRD: "**Body foreign-key existence** — every identifier supplied in the body resolves,
    checked left to right in the order the fields are declared for that operation. Answers the
    matching 404 code. This band applies to gate-review scheduling, checklist creation and
    prerequisite setting, pilot-run booking, label drafting, trade-presentation booking and the
    launch date lock."

    Design: Corner/errors/err_every_unresolved_id_reports_its_own_typed_not_found
    """
    set_clock("2026-08-03T00:00:00Z")
    project = intake_project(owner_user_id="lead-bd", name="Toffee Crunch Bites",
                            category="SNACK", project_type="LINE_EXTENSION")
    formulation = create_formulation(project["id"])
    retailer = register_retailer(name="MidStates Grocery", channel="GROCERY",
                                 acv_contribution_pct=30.00, presentation_lead_days=14)
    window = open_reset_window(retailer["id"], category="SNACK",
                               window_start="2026-10-05T00:00:00Z",
                               window_end="2026-11-30T00:00:00Z", max_presentations=2)

    validate_error(
        api.create_pilot_run(formulation["id"], pilot_run_payload(NON_EXISTENT_UUID),
                             rnd_lead_headers),
        "ERR_PILOT_LINE_NOT_FOUND",
        404,
    )
    validate_error(
        api.create_label_approval(project["id"], label_approval_payload(NON_EXISTENT_UUID),
                                  innovation_lead_headers),
        "ERR_FORMULATION_NOT_FOUND",
        404,
    )
    validate_error(
        api.create_sell_in_presentation(
            project["id"],
            sell_in_presentation_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID,
                                         scheduled_at="2026-09-20T09:00:00Z"),
            sales_account_manager_headers,
        ),
        "ERR_RETAILER_NOT_FOUND",
        404,
    )
    validate_error(
        api.create_sell_in_presentation(
            project["id"],
            sell_in_presentation_payload(retailer["id"], NON_EXISTENT_UUID,
                                         scheduled_at="2026-09-20T09:00:00Z"),
            sales_account_manager_headers,
        ),
        "ERR_RESET_WINDOW_NOT_FOUND",
        404,
    )

    refused = read_project(project["id"])
    assert refused["dev_status"] == "IDEA", (
        "body existence is reported although this project's state admits no booking at all"
    )
    assert refused["commercial_status"] == "NOT_STARTED"
    _, meta = validate_paginated(
        api.list_sell_in_presentations(sales_account_manager_headers,
                                       params={"project_id": project["id"]})
    )
    assert meta["total_count"] == 0
    assert read_window(window["id"])["booked_slot_count"] == 0


def test_the_gate_configuration_key_is_the_category_and_gate_number_pair(
    api, portfolio_admin_headers
):
    """A second snack gate 2 is a duplicate while a dairy gate 2 is a fresh registration.

    PRD: "Gate numbering starts at 2 because gate 1 *is* the screening step, and the pair of
    `category` and `gate_number` must be unique — a second registration of the same pair is
    rejected with `ERR_DUPLICATE_RESOURCE`."

    Design: Corner/errors/err_uniqueness_guards_key_on_the_declared_tuple
    """
    set_clock("2026-08-03T00:00:00Z")
    register_stage_gate(**SNACK_GATE)

    response = api.create_stage_gate(
        stage_gate_payload(gate_number=2, category="SNACK", stage_from="SCREENED",
                           stage_to="PILOT_QUALIFIED", quorum_size=3),
        portfolio_admin_headers,
    )

    validate_error(response, "ERR_DUPLICATE_RESOURCE", 409)
    other_category = validate_success(
        api.create_stage_gate(
            stage_gate_payload(gate_number=2, category="DAIRY", stage_from="SCREENED",
                               stage_to="PILOT_QUALIFIED"),
            portfolio_admin_headers,
        ),
        201,
    )
    assert other_category["category"] == "DAIRY"
    assert other_category["gate_number"] == 2
    _, meta = validate_paginated(api.list_stage_gates(portfolio_admin_headers))
    assert meta["total_count"] == 2, "only the genuinely duplicate pair was refused"


def test_line_codes_are_unique_across_plants_and_retailer_names_across_channels(
    api, portfolio_admin_headers
):
    """A line code collides at a second plant and a retailer name collides in a second channel.

    PRD: "A **pilot line** carries a `plant_name`, a `line_code` unique across all lines
    (duplicates answer `ERR_DUPLICATE_RESOURCE`), a base `changeover_buffer_minutes` between 0
    and 1440, the `allergen_regime` currently set up on the line, and an informational
    `hourly_cost_usd`."

    PRD: "Retailer names are unique, and a duplicate answers `ERR_DUPLICATE_RESOURCE`."

    Design: Corner/errors/err_uniqueness_guards_key_on_the_declared_tuple
    """
    set_clock("2026-08-03T00:00:00Z")
    register_pilot_line(plant_name="Toledo Pilot", line_code="TOL-41")
    register_retailer(name="MidStates Grocery", channel="GROCERY")

    validate_error(
        api.create_pilot_line(
            pilot_line_payload(plant_name="Reno Pilot", line_code="TOL-41",
                               allergen_regime="NUT"),
            portfolio_admin_headers,
        ),
        "ERR_DUPLICATE_RESOURCE",
        409,
    )
    validate_error(
        api.create_retailer(
            retailer_payload(name="MidStates Grocery", channel="CLUB"),
            portfolio_admin_headers,
        ),
        "ERR_DUPLICATE_RESOURCE",
        409,
    )

    accepted = validate_success(
        api.create_pilot_line(
            pilot_line_payload(plant_name="Reno Pilot", line_code="TOL-42"),
            portfolio_admin_headers,
        ),
        201,
    )
    assert accepted["line_code"] == "TOL-42"
    _, line_meta = validate_paginated(api.list_pilot_lines(portfolio_admin_headers))
    assert line_meta["total_count"] == 2
    _, retailer_meta = validate_paginated(api.list_retailers(portfolio_admin_headers))
    assert retailer_meta["total_count"] == 1, "the name collision stored nothing"


def test_one_forecast_line_per_channel_per_case(api, innovation_lead_headers,
                                                portfolio_admin_headers):
    """A second grocery line is refused while a mass line joins the same case.

    PRD: "At most one line per channel per case: a second line on the same `channel` is rejected
    with `ERR_DUPLICATE_CHANNEL_LINE`."

    Design: Corner/errors/err_uniqueness_guards_key_on_the_declared_tuple
    """
    set_clock("2026-08-03T00:00:00Z")
    project = intake_project(owner_user_id="lead-fl", name="Toffee Crunch Bites",
                            category="SNACK", project_type="LINE_EXTENSION")
    case = open_business_case(project["id"], variant_mode="TOP_DOWN",
                              category_size_units_year=4000000, target_share_pct=4.00,
                              cogs_per_unit_usd=2.5000, slotting_fees_usd=0.00,
                              capex_usd=100000.00, discount_rate_pct=10.00)
    validate_success(
        api.create_forecast_line(case["id"], forecast_line_payload(channel="GROCERY"),
                                 innovation_lead_headers),
        201,
    )

    response = api.create_forecast_line(
        case["id"], forecast_line_payload(channel="GROCERY", store_count=900),
        innovation_lead_headers,
    )

    validate_error(response, "ERR_DUPLICATE_CHANNEL_LINE", 409)
    validate_success(
        api.create_forecast_line(
            case["id"], forecast_line_payload(channel="MASS", store_count=900),
            innovation_lead_headers,
        ),
        201,
    )
    _, meta = validate_paginated(
        api.list_forecast_lines(case["id"], portfolio_admin_headers)
    )
    assert meta["total_count"] == 2, "the refused duplicate never joined the line set"
    recomputed = validate_success(
        api.get_business_case(case["id"], portfolio_admin_headers)
    )
    assert recomputed["annual_units"] == 160000, (
        "a top-down case takes its volume from the category share, not the line count"
    )


def test_deciding_an_unsubmitted_checklist_item_answers_the_deliverable_state_error(
    api, innovation_lead_headers, functional_reviewer_headers, portfolio_admin_headers
):
    """A PENDING item cannot be approved, and the refusal leaves no decider behind.

    PRD: "Deciding an item in any other state answers `ERR_DELIVERABLE_INVALID_STATE`, and
    because state outranks segregation of duties, that state error is what a submitter sees if
    they try to approve their own still-`PENDING` item."

    Design: Corner/errors/err_child_state_guards_refuse_out_of_sequence_transitions
    """
    set_clock("2026-08-03T00:00:00Z")
    gate = register_stage_gate(**SNACK_GATE)
    project = intake_project(owner_user_id="lead-cs", name="Toffee Crunch Bites",
                             category="SNACK", project_type="LINE_EXTENSION")
    item = validate_success(
        api.create_deliverable(project["id"], deliverable_payload(gate["id"]),
                               innovation_lead_headers),
        201,
    )
    assert item["status"] == "PENDING"

    response = api.decide_deliverable(item["id"], {"decision": "APPROVE"},
                                      functional_reviewer_headers)

    validate_error(response, "ERR_DELIVERABLE_INVALID_STATE", 409)
    stored = validate_success(api.get_deliverable(item["id"], portfolio_admin_headers))
    assert stored["status"] == "PENDING"
    assert stored["decided_by_user_id"] is None
    assert stored["submission_count"] == 0


def test_the_pilot_run_ladder_refuses_completion_a_second_start_and_a_late_cancel(
    api, rnd_lead_headers
):
    """Completing a SCHEDULED run, restarting a RUNNING one and cancelling a finished one all fail.

    PRD: "Completing a run requires it to be `RUNNING` and cancelling one requires it to be
    `SCHEDULED` or `RUNNING`; from any other status both answer `ERR_PILOT_RUN_INVALID_STATE`."

    Design: Corner/errors/err_child_state_guards_refuse_out_of_sequence_transitions
    """
    set_clock("2026-08-03T00:00:00Z")
    line = register_pilot_line(plant_name="Toledo Pilot", line_code="TOL-41")
    project = intake_project(owner_user_id="lead-pr", name="Toffee Crunch Bites",
                             category="SNACK", project_type="LINE_EXTENSION")
    formulation = create_formulation(project["id"])
    run = book_pilot_run(formulation["id"], line["id"],
                         window_start="2026-08-01T08:00:00Z",
                         window_end="2026-08-01T16:00:00Z", planned_units=10000)

    validate_error(
        api.complete_pilot_run(run["id"], {"actual_units": 9000}, rnd_lead_headers),
        "ERR_PILOT_RUN_INVALID_STATE",
        409,
    )
    running = start_pilot_run(run["id"])
    assert running["status"] == "RUNNING"
    validate_error(
        api.start_pilot_run(run["id"], {}, rnd_lead_headers),
        "ERR_PILOT_RUN_INVALID_STATE",
        409,
    )
    completed = validate_success(
        api.complete_pilot_run(run["id"], {"actual_units": 10000}, rnd_lead_headers)
    )
    assert completed["status"] == "COMPLETED"

    validate_error(
        api.cancel_pilot_run(run["id"], {"reason": "Line released for a customer trial"},
                             rnd_lead_headers),
        "ERR_PILOT_RUN_INVALID_STATE",
        409,
    )
    settled = validate_success(api.get_pilot_run(run["id"], rnd_lead_headers))
    assert settled["status"] == "COMPLETED", "the refused cancel never moved the run"


def test_a_closed_stability_study_refuses_even_a_later_reading(api, rnd_lead_headers):
    """Once the study has closed PASSED, a strictly later day index is still refused.

    PRD: "Appending to a closed study answers `ERR_STUDY_INVALID_STATE`."

    Design: Corner/errors/err_child_state_guards_refuse_out_of_sequence_transitions
    """
    set_clock("2026-08-03T00:00:00Z")
    project = intake_project(owner_user_id="lead-st", name="Toffee Crunch Bites",
                             category="SNACK", project_type="LINE_EXTENSION")
    ctx = setup_cleared_formulation(project["id"], line_code="TOL-41", duration_days=180,
                                   timepoint=(180, 88.00))
    closed = ctx["shelf_life_study"]
    assert closed["status"] == "PASSED"
    assert closed["verdict"] == "PASS"

    response = api.add_timepoint(closed["id"],
                                timepoint_payload(day_index=200, quality_score=84.00),
                                rnd_lead_headers)

    validate_error(response, "ERR_STUDY_INVALID_STATE", 409)
    stored = validate_success(api.get_shelf_life_study(closed["id"], rnd_lead_headers))
    assert len(stored["timepoints"]) == 1, "the refused reading was never appended"
    assert stored["min_quality_score"] == pytest.approx(88.00, abs=0.01)
    assert read_formulation(ctx["formulation"]["id"])["status"] == "SHELF_LIFE_CLEARED"


def test_a_superseded_case_and_a_draft_label_each_answer_their_own_state_error(
    api, innovation_lead_headers, regulatory_approver_headers, portfolio_admin_headers
):
    """A superseded case takes no line and an undecided draft label takes no decision.

    PRD: "Lines may be added while the case is `DRAFT` or `COMPUTED`; a case that is `LOCKED` or
    `SUPERSEDED` takes no further lines and answers `ERR_BUSINESS_CASE_INVALID_STATE`."

    PRD: "A `RegulatoryApprover` then records a `decision` on an `IN_REVIEW` label, optionally
    with a `comment`, along three branches."

    PRD: "**State** — the subject row and its governing parents admit the requested transition,
    else the entity's `ERR_..._INVALID_STATE` code (409)."

    Design: Corner/errors/err_child_state_guards_refuse_out_of_sequence_transitions
    """
    set_clock("2026-08-03T00:00:00Z")
    project = intake_project(owner_user_id="lead-ss", name="Toffee Crunch Bites",
                            category="SNACK", project_type="LINE_EXTENSION")
    superseded = open_business_case(project["id"])
    live = open_business_case(project["id"])
    formulation = create_formulation(project["id"])
    label = draft_label(project["id"], formulation["id"])

    validate_error(
        api.create_forecast_line(superseded["id"], forecast_line_payload(),
                                 innovation_lead_headers),
        "ERR_BUSINESS_CASE_INVALID_STATE",
        409,
    )
    validate_error(
        api.decide_label_approval(label["id"], {"decision": "APPROVE"},
                                  regulatory_approver_headers),
        "ERR_LABEL_INVALID_STATE",
        409,
    )

    assert validate_success(
        api.get_business_case(superseded["id"], portfolio_admin_headers)
    )["status"] == "SUPERSEDED"
    assert validate_success(
        api.get_business_case(live["id"], portfolio_admin_headers)
    )["status"] == "DRAFT"
    _, meta = validate_paginated(
        api.list_forecast_lines(superseded["id"], portfolio_admin_headers)
    )
    assert meta["total_count"] == 0
    stored_label = validate_success(
        api.get_label_approval(label["id"], portfolio_admin_headers)
    )
    assert stored_label["status"] == "DRAFT"
    assert stored_label["decided_by_user_id"] is None


def test_a_pilot_run_cannot_start_before_its_window_opens(api, rnd_lead_headers):
    """The run is refused a week early and accepted at the exact opening instant.

    PRD: "A run starts in `SCHEDULED` and moves `SCHEDULED → RUNNING` when the `RnDLead` starts
    it; the run must actually be `SCHEDULED`, else `ERR_PILOT_RUN_INVALID_STATE` (409), the
    current instant must have reached `window_start`, else `ERR_PILOT_RUN_NOT_DUE` (409), and the
    parent formulation must still not be `SUPERSEDED`."

    Design: Corner/errors/err_rnd_temporal_guards_hold_the_calendar_and_the_reading_order
    """
    set_clock("2026-08-03T00:00:00Z")
    line = register_pilot_line(plant_name="Toledo Pilot", line_code="TOL-41")
    project = intake_project(owner_user_id="lead-nd", name="Toffee Crunch Bites",
                             category="SNACK", project_type="LINE_EXTENSION")
    formulation = create_formulation(project["id"])
    run = book_pilot_run(formulation["id"], line["id"],
                         window_start="2026-08-10T08:00:00Z",
                         window_end="2026-08-10T16:00:00Z", planned_units=10000)

    validate_error(api.start_pilot_run(run["id"], {}, rnd_lead_headers),
                   "ERR_PILOT_RUN_NOT_DUE", 409)
    assert validate_success(
        api.get_pilot_run(run["id"], rnd_lead_headers)
    )["status"] == "SCHEDULED"

    set_clock("2026-08-10T08:00:00Z")
    running = validate_success(api.start_pilot_run(run["id"], {}, rnd_lead_headers))

    assert running["status"] == "RUNNING", "the opening instant itself is due"
    finished = validate_success(
        api.complete_pilot_run(run["id"], {"actual_units": 10000}, rnd_lead_headers)
    )
    assert finished["yield_pct"] == pytest.approx(100.00, abs=0.01)
    assert read_formulation(formulation["id"])["status"] == "PILOT_PASSED"


def test_a_repeated_day_index_is_refused_exactly_like_a_backwards_one(api, rnd_lead_headers):
    """Day 30 twice and then day 20 are both out of order, and neither touches the minimum.

    PRD: "Each `day_index` must be strictly greater than every `day_index` already recorded on
    the study, else `ERR_TIMEPOINT_OUT_OF_ORDER` (409); the stored `timepoints` list is therefore
    kept sorted by `day_index` ascending by construction."

    Design: Corner/errors/err_rnd_temporal_guards_hold_the_calendar_and_the_reading_order
    """
    set_clock("2026-08-03T00:00:00Z")
    project = intake_project(owner_user_id="lead-tp", name="Toffee Crunch Bites",
                             category="SNACK", project_type="LINE_EXTENSION")
    ctx = setup_cleared_formulation(project["id"], line_code="TOL-41", duration_days=180,
                                    timepoint=(30, 90.00))
    study = ctx["shelf_life_study"]
    assert study["status"] == "ACTIVE"
    assert study["min_quality_score"] == pytest.approx(90.00, abs=0.01)

    validate_error(
        api.add_timepoint(study["id"], timepoint_payload(day_index=30, quality_score=95.00),
                          rnd_lead_headers),
        "ERR_TIMEPOINT_OUT_OF_ORDER",
        409,
    )
    validate_error(
        api.add_timepoint(study["id"], timepoint_payload(day_index=20, quality_score=95.00),
                          rnd_lead_headers),
        "ERR_TIMEPOINT_OUT_OF_ORDER",
        409,
    )
    assert validate_success(
        api.get_shelf_life_study(study["id"], rnd_lead_headers)
    )["min_quality_score"] == pytest.approx(90.00, abs=0.01)

    advanced = add_timepoint(study["id"], 60, 80.00)

    assert [tp["day_index"] for tp in advanced["timepoints"]] == [30, 60], (
        "only the two strictly increasing readings were ever stored"
    )
    assert advanced["min_quality_score"] == pytest.approx(80.00, abs=0.01)
    assert advanced["status"] == "ACTIVE"
