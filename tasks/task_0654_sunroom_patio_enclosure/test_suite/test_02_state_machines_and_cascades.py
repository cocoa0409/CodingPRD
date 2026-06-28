"""Non-linear state machines, transitive cascades, cross-entity state dependencies, and
compensating invariants. Translates Difficulty queue rules non_linear_state_machine,
transitive_cascade, cross_entity_state_dependency, and compensating_invariant.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_quote_payload, create_quote_accept_payload, create_permit_payload,
    create_permit_decide_payload, create_engineering_review_payload,
    create_manufacture_order_payload, create_crew_payload, create_install_job_payload,
    create_weather_payload,
    setup_designed_project, setup_permitting_project, setup_permit_in_review,
    setup_in_manufacture, setup_manufacture_ready, setup_installing_project,
    make_homeowner_headers, set_clock, TEST_USERS,
)

SD = TEST_USERS["sales_designer_headers"]
PO = TEST_USERS["permit_officer_headers"]
MF = TEST_USERS["manufacturer_headers"]
IM = TEST_USERS["install_manager_headers"]


def _quotes(api, project_id):
    body = api.list_project_quotes(project_id, SD).json()
    return body.get("data", []), body.get("meta", {})


def _measurements(api, project_id):
    body = api.list_project_measurements(project_id, SD).json()
    return body.get("data", []), body.get("meta", {})


# ─────────────────────────────────────────────────────────────────────────
# Rule 3: non_linear_state_machine
# ─────────────────────────────────────────────────────────────────────────

def test_weather_hold_leaves_progress_unchanged(api):
    """PRD §3.6: "The manager raises or releases a weather hold through the weather
    operation: a hold may be raised, moving `CLEAR → WEATHER_HOLD`, only while the weather
    is currently `CLEAR` and the progress is `SCHEDULED` or `IN_PROGRESS`; a hold is
    released, moving `WEATHER_HOLD → CLEAR`, only while the weather is currently
    `WEATHER_HOLD`. Either way only the weather axis moves; the progress axis is untouched."

    Design: Difficulty/non_linear_state_machine/install_job_parallel_weather_and_progress_axes
    """
    set_clock("2026-05-01T00:00:00Z")
    ho, pj, crew, ij = setup_installing_project()
    held = validate_success(api.set_install_job_weather(
        ij["id"], create_weather_payload("WEATHER_HOLD"), IM), 200)
    assert held["weather_status"] == "WEATHER_HOLD", held
    assert held["progress_status"] == "SCHEDULED", held


def test_clear_then_start_moves_progress_while_weather_clear(api):
    """PRD §3.6: "Starting the install moves `progress_status` `SCHEDULED → IN_PROGRESS`. It
    requires the job to be `SCHEDULED`, the weather to be `CLEAR`, and the `forecast_wind_mph`
    to be at most the assigned crew's `max_wind_mph`."

    Design: Difficulty/non_linear_state_machine/install_job_parallel_weather_and_progress_axes
    """
    set_clock("2026-05-01T00:00:00Z")
    ho, pj, crew, ij = setup_installing_project()
    get_success_data(api.set_install_job_weather(ij["id"],
                     create_weather_payload("WEATHER_HOLD"), IM))
    get_success_data(api.set_install_job_weather(ij["id"],
                     create_weather_payload("CLEAR"), IM))
    started = validate_success(api.start_install_job(ij["id"], IM), 200)
    assert started["progress_status"] == "IN_PROGRESS", started
    assert started["weather_status"] == "CLEAR", started


def test_permit_resubmit_loops_rejected_to_submitted(api):
    """PRD §3.4: "A `Homeowner` may resubmit a `REJECTED` permit, sending it
    `REJECTED → SUBMITTED`, provided its `resubmission_count` is below the cap of 3;
    resubmission increments `resubmission_count` by one."

    Design: Difficulty/non_linear_state_machine/permit_resubmission_cycle_rejected_back_to_submitted
    """
    ho, pj, q, pa = setup_permit_in_review()
    get_success_data(api.decide_permit(pa["id"], create_permit_decide_payload("REJECTED"), PO))
    resubmitted = validate_success(api.resubmit_permit(pa["id"],
                                   make_homeowner_headers(ho["id"])), 200)
    assert resubmitted["status"] == "SUBMITTED", resubmitted
    assert resubmitted["resubmission_count"] == 1, resubmitted


def test_permit_rejected_status_before_resubmit(api):
    """PRD §3.4: "A decision of rejection requires only that the permit be `IN_REVIEW`; it
    sets the permit to `REJECTED` and awaits resubmission, with no other effect."

    Design: Difficulty/non_linear_state_machine/permit_resubmission_cycle_rejected_back_to_submitted
    """
    ho, pj, q, pa = setup_permit_in_review()
    rejected = validate_success(api.decide_permit(
        pa["id"], create_permit_decide_payload("REJECTED"), PO), 200)
    assert rejected["status"] == "REJECTED", rejected
    assert rejected["resubmission_count"] == 0, rejected


# ─────────────────────────────────────────────────────────────────────────
# Rule 4: transitive_cascade
# ─────────────────────────────────────────────────────────────────────────

def test_manufacture_start_supersedes_estimate_and_repoints(api):
    """PRD §3.5: "it creates a new `FINAL`-variant `Quote` with `revision_no` one greater
    than the current highest, priced by the same base/add-ons/tax/total rules but recomputed
    against the currently accepted measurement, then supersedes the prior `ACCEPTED` quote
    and repoints `accepted_quote_id` to this final quote."

    Design: Difficulty/transitive_cascade/manufacture_start_final_quote_supersede_repoint_chain
    """
    ho, pj, q, mo = setup_in_manufacture(
        project_overrides={"structure_type": "THREE_SEASON", "material": "ALUMINUM"},
        measurement_overrides={"width_in": 120, "depth_in": 144, "wall_height_in": 96,
                               "existing_slab": True},
    )
    started = validate_success(api.start_manufacture_order(mo["id"], MF), 200)
    assert started["status"] == "IN_PRODUCTION", started
    q_after = get_success_data(api.get_quote(q["id"], SD))
    assert q_after["status"] == "SUPERSEDED", q_after
    quotes, _ = _quotes(api, pj["id"])
    final_accepted = [x for x in quotes if x["variant"] == "FINAL" and x["status"] == "ACCEPTED"]
    assert len(final_accepted) == 1, quotes
    pj_after = get_success_data(api.get_project(pj["id"], SD))
    assert pj_after["accepted_quote_id"] == final_accepted[0]["id"], pj_after
    assert pj_after["accepted_quote_id"] != q["id"], pj_after


def test_manufacture_start_moves_order_in_production(api):
    """PRD §3.5: "When the `Manufacturer` starts production, the order moves
    `QUEUED → IN_PRODUCTION`, and the system performs the dual-variant reconciliation"

    Design: Difficulty/transitive_cascade/manufacture_start_final_quote_supersede_repoint_chain
    """
    ho, pj, q, mo = setup_in_manufacture(
        project_overrides={"structure_type": "THREE_SEASON", "material": "ALUMINUM"},
        measurement_overrides={"width_in": 120, "depth_in": 144, "wall_height_in": 96,
                               "existing_slab": True},
    )
    started = validate_success(api.start_manufacture_order(mo["id"], MF), 200)
    assert started["status"] == "IN_PRODUCTION", started


def test_engineering_fail_cascades_to_reject_permit(api):
    """PRD §3.4: "When a review fails and its linked permit is currently `IN_REVIEW`, the
    engineering failure cascades to reject the permit, setting it to `REJECTED`."

    Design: Difficulty/transitive_cascade/engineering_fail_rejects_permit_chain
    """
    # FOUR_SEASON (requires_engineering), permit IN_REVIEW, engineering rated below required.
    ho, pj, q, pa = setup_permit_in_review(
        homeowner_overrides={"ground_snow_load_psf": 40, "design_wind_speed_mph": 140},
        project_overrides={"structure_type": "FOUR_SEASON",
                           "material": "THERMAL_BREAK_ALUMINUM"},
        measurement_overrides={"width_in": 180, "depth_in": 160, "wall_height_in": 108,
                               "existing_slab": False},
    )
    er = get_success_data(api.create_engineering_review(
        create_engineering_review_payload(pa["id"], pj["id"], rated_wind_mph=100,
                                          rated_snow_psf=20), SD))
    ruled = validate_success(api.rule_engineering_review(er["id"], PO), 200)
    assert ruled["status"] == "FAILED", ruled
    pa_after = get_success_data(api.get_permit_application(pa["id"], PO))
    assert pa_after["status"] == "REJECTED", pa_after


def test_engineering_fail_when_rated_below_required(api):
    """PRD §3.4: "It fails when `rated_wind_mph` is below `required_wind_mph` or
    `rated_snow_psf` is below `required_snow_psf`"

    Design: Difficulty/transitive_cascade/engineering_fail_rejects_permit_chain
    """
    ho, pj, q, pa = setup_permit_in_review(
        homeowner_overrides={"ground_snow_load_psf": 40, "design_wind_speed_mph": 140},
        project_overrides={"structure_type": "FOUR_SEASON",
                           "material": "THERMAL_BREAK_ALUMINUM"},
        measurement_overrides={"width_in": 180, "depth_in": 160, "wall_height_in": 108,
                               "existing_slab": False},
    )
    er = get_success_data(api.create_engineering_review(
        create_engineering_review_payload(pa["id"], pj["id"], rated_wind_mph=100,
                                          rated_snow_psf=20), SD))
    ruled = validate_success(api.rule_engineering_review(er["id"], PO), 200)
    # required wind 140 (from homeowner.design_wind_speed_mph), rated 100 < 140 -> FAILED.
    assert ruled["status"] == "FAILED", ruled


# ─────────────────────────────────────────────────────────────────────────
# Rule 7: cross_entity_state_dependency
# ─────────────────────────────────────────────────────────────────────────

def test_permit_approve_blocked_until_engineering_passed(api):
    """PRD §3.4: "if the project's `requires_engineering` is true, there must exist a passed
    engineering review for this permit, otherwise the approval is rejected with
    `ERR_ENGINEERING_PENDING` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/permit_approve_requires_engineering_passed
    """
    ho, pj, q, pa = setup_permit_in_review(
        homeowner_overrides={"ground_snow_load_psf": 40, "design_wind_speed_mph": 140},
        project_overrides={"structure_type": "FOUR_SEASON",
                           "material": "THERMAL_BREAK_ALUMINUM"},
        measurement_overrides={"width_in": 180, "depth_in": 160, "wall_height_in": 108,
                               "existing_slab": False},
    )
    # Submit a PENDING (not yet ruled) engineering review rated above required.
    get_success_data(api.create_engineering_review(
        create_engineering_review_payload(pa["id"], pj["id"], rated_wind_mph=150,
                                          rated_snow_psf=45), SD))
    res = api.decide_permit(pa["id"], create_permit_decide_payload("APPROVED"), PO)
    validate_error(res, "ERR_ENGINEERING_PENDING")
    pa_after = get_success_data(api.get_permit_application(pa["id"], PO))
    assert pa_after["status"] == "IN_REVIEW", pa_after


def test_permit_approve_succeeds_after_engineering_passed(api):
    """PRD §3.4: "On approval, the permit's `expires_at` is set to the logical clock now plus
    180 days (the permit validity window), and the project advances
    `PERMITTING → APPROVED_TO_BUILD`, incrementing `Project.version` by one."

    Design: Difficulty/cross_entity_state_dependency/permit_approve_requires_engineering_passed
    """
    ho, pj, q, pa = setup_permit_in_review(
        homeowner_overrides={"ground_snow_load_psf": 40, "design_wind_speed_mph": 140},
        project_overrides={"structure_type": "FOUR_SEASON",
                           "material": "THERMAL_BREAK_ALUMINUM"},
        measurement_overrides={"width_in": 180, "depth_in": 160, "wall_height_in": 108,
                               "existing_slab": False},
    )
    er = get_success_data(api.create_engineering_review(
        create_engineering_review_payload(pa["id"], pj["id"], rated_wind_mph=150,
                                          rated_snow_psf=45), SD))
    ruled = get_success_data(api.rule_engineering_review(er["id"], PO))
    assert ruled["status"] == "PASSED", ruled
    approved = validate_success(api.decide_permit(
        pa["id"], create_permit_decide_payload("APPROVED"), PO), 200)
    assert approved["status"] == "APPROVED", approved
    pj_after = get_success_data(api.get_project(pj["id"], SD))
    assert pj_after["status"] == "APPROVED_TO_BUILD", pj_after


def test_install_create_blocked_until_manufacture_ready(api):
    """PRD §3.6: "With the project `IN_MANUFACTURE` and its manufacture order `READY`, the
    manager schedules an `InstallJob`"
    PRD §2.7: "State legality — whether the target entity is in a state from which the
    requested transition is allowed — is fifth, yielding `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/install_create_requires_manufacture_ready
    """
    set_clock("2026-05-01T00:00:00Z")
    ho, pj, q, mo = setup_in_manufacture(
        project_overrides={"structure_type": "THREE_SEASON", "material": "ALUMINUM"},
        measurement_overrides={"width_in": 120, "depth_in": 144, "wall_height_in": 96,
                               "existing_slab": True},
    )
    # start (IN_PRODUCTION) but NOT ready.
    get_success_data(api.start_manufacture_order(mo["id"], MF))
    crew = get_success_data(api.create_crew(create_crew_payload(name="Crew D"), IM))
    res = api.create_install_job(create_install_job_payload(
        pj["id"], crew["id"], "2026-05-02T08:00:00Z", "2026-05-02T17:00:00Z"), IM)
    validate_error(res, "ERR_INVALID_STATE")


def test_install_create_succeeds_after_manufacture_ready(api):
    """PRD §3.6: "Scheduling drives the project `IN_MANUFACTURE → INSTALLING`, creates the
    job with `progress_status` of `SCHEDULED` and `weather_status` of `CLEAR`, and increments
    `Project.version` by one."

    Design: Difficulty/cross_entity_state_dependency/install_create_requires_manufacture_ready
    """
    set_clock("2026-05-01T00:00:00Z")
    ho, pj, mo = setup_manufacture_ready(
        project_overrides={"structure_type": "THREE_SEASON", "material": "ALUMINUM"},
        measurement_overrides={"width_in": 120, "depth_in": 144, "wall_height_in": 96,
                               "existing_slab": True},
    )
    crew = get_success_data(api.create_crew(create_crew_payload(name="Crew D"), IM))
    ij = validate_success(api.create_install_job(create_install_job_payload(
        pj["id"], crew["id"], "2026-05-02T08:00:00Z", "2026-05-02T17:00:00Z"), IM), 201)
    assert ij["progress_status"] == "SCHEDULED", ij
    pj_after = get_success_data(api.get_project(pj["id"], SD))
    assert pj_after["status"] == "INSTALLING", pj_after


# ─────────────────────────────────────────────────────────────────────────
# Rule 9: compensating_invariant
# ─────────────────────────────────────────────────────────────────────────

def test_single_accepted_measurement_after_remeasure(api):
    """PRD §3.1: "the prior `ACCEPTED` measurement is set to `SUPERSEDED`, the new one becomes
    `ACCEPTED`"

    Design: Difficulty/compensating_invariant/single_accepted_measurement_invariant_on_remeasure
    """
    # DESIGNED project with one ACCEPTED measurement (120x144); new PENDING (130x144) recorded.
    ho, pj, m1 = setup_designed_project(
        project_overrides={"structure_type": "THREE_SEASON", "material": "ALUMINUM"},
        measurement_overrides={"width_in": 120, "depth_in": 144, "wall_height_in": 96,
                               "existing_slab": True},
    )
    m2 = get_success_data(api.create_measurement(
        {"project_id": pj["id"], "width_in": 130, "depth_in": 144, "wall_height_in": 96,
         "existing_slab": True}, SD))
    get_success_data(api.accept_measurement(m2["id"], SD))
    m1_after = [x for x in _measurements(api, pj["id"])[0] if x["id"] == m1["id"]][0]
    m2_after = [x for x in _measurements(api, pj["id"])[0] if x["id"] == m2["id"]][0]
    assert m1_after["status"] == "SUPERSEDED", m1_after
    assert m2_after["status"] == "ACCEPTED", m2_after


def test_accepted_measurement_count_conserved_at_one(api):
    """PRD §3.1: "the prior `ACCEPTED` measurement is set to `SUPERSEDED`, the new one becomes
    `ACCEPTED`"

    Design: Difficulty/compensating_invariant/single_accepted_measurement_invariant_on_remeasure
    """
    ho, pj, m1 = setup_designed_project(
        project_overrides={"structure_type": "THREE_SEASON", "material": "ALUMINUM"},
        measurement_overrides={"width_in": 120, "depth_in": 144, "wall_height_in": 96,
                               "existing_slab": True},
    )
    m2 = get_success_data(api.create_measurement(
        {"project_id": pj["id"], "width_in": 130, "depth_in": 144, "wall_height_in": 96,
         "existing_slab": True}, SD))
    get_success_data(api.accept_measurement(m2["id"], SD))
    measurements, _ = _measurements(api, pj["id"])
    accepted = [x for x in measurements if x["status"] == "ACCEPTED"]
    assert len(accepted) == 1, measurements


def test_single_accepted_quote_after_final_supersede(api):
    """PRD §3.5: "it creates a new `FINAL`-variant `Quote` with `revision_no` one greater than
    the current highest, priced by the same base/add-ons/tax/total rules but recomputed against
    the currently accepted measurement, then supersedes the prior `ACCEPTED` quote and repoints
    `accepted_quote_id` to this final quote."

    Design: Difficulty/compensating_invariant/single_accepted_quote_invariant_on_final_supersede
    """
    ho, pj, q, mo = setup_in_manufacture(
        project_overrides={"structure_type": "THREE_SEASON", "material": "ALUMINUM"},
        measurement_overrides={"width_in": 120, "depth_in": 144, "wall_height_in": 96,
                               "existing_slab": True},
    )
    get_success_data(api.start_manufacture_order(mo["id"], MF))
    q_after = get_success_data(api.get_quote(q["id"], SD))
    assert q_after["status"] == "SUPERSEDED", q_after
    quotes, _ = _quotes(api, pj["id"])
    final_accepted = [x for x in quotes if x["variant"] == "FINAL" and x["status"] == "ACCEPTED"]
    assert len(final_accepted) == 1, quotes


def test_accepted_quote_count_conserved_at_one(api):
    """PRD §3.5: "then supersedes the prior `ACCEPTED` quote and repoints `accepted_quote_id`
    to this final quote."

    Design: Difficulty/compensating_invariant/single_accepted_quote_invariant_on_final_supersede
    """
    ho, pj, q, mo = setup_in_manufacture(
        project_overrides={"structure_type": "THREE_SEASON", "material": "ALUMINUM"},
        measurement_overrides={"width_in": 120, "depth_in": 144, "wall_height_in": 96,
                               "existing_slab": True},
    )
    get_success_data(api.start_manufacture_order(mo["id"], MF))
    quotes, _ = _quotes(api, pj["id"])
    accepted = [x for x in quotes if x["status"] == "ACCEPTED"]
    assert len(accepted) == 1, quotes
