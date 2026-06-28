"""Invalid transitions, idempotency, terminal lockdown, the inspection rework cycle, and the
engineering-underrated ruling. Translates Corner queue section state_machines.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_project_payload, create_homeowner_payload,
    create_engineering_review_payload, create_inspection_fail_payload,
    create_inspection_payload,
    setup_designed_project, setup_permit_in_review, setup_completed_project,
    setup_inspecting_project, TEST_USERS, set_clock, make_homeowner_headers,
)

SD = TEST_USERS["sales_designer_headers"]
PO = TEST_USERS["permit_officer_headers"]
IM = TEST_USERS["install_manager_headers"]
INS = TEST_USERS["inspector_headers"]


def test_finalize_design_from_draft_invalid_state(api):
    """PRD §3.1: "a `SalesDesigner` finalizes the design, which requires the project to be in
    `MEASURED` with both its `structure_type` and `material` set"
    PRD §3.1: "Any attempt to drive a transition from a state the entity is not in is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/finalize_design_from_draft_invalid_state
    """
    ho = get_success_data(api.create_homeowner(create_homeowner_payload(email="s1@x.com"), SD))
    pj = get_success_data(api.create_project(create_project_payload(
        ho["id"], address_line="B1", structure_type="THREE_SEASON", material="ALUMINUM"), SD))
    res = api.finalize_design(pj["id"], SD)
    validate_error(res, "ERR_INVALID_STATE")
    pj_after = get_success_data(api.get_project(pj["id"], SD))
    assert pj_after["status"] == "DRAFT", pj_after


def test_accept_measurement_twice_second_fails(api):
    """PRD §3.1: "When a `SalesDesigner` accepts a `PENDING` measurement, the project must not
    be cancelled or completed and the measurement's `project_id` must match the target
    project."
    PRD §3.1: "Any attempt to drive a transition from a state the entity is not in is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/accept_measurement_twice_idempotency_second_fails
    """
    ho = get_success_data(api.create_homeowner(create_homeowner_payload(email="s2@x.com"), SD))
    pj = get_success_data(api.create_project(create_project_payload(
        ho["id"], address_line="B2", structure_type="THREE_SEASON", material="ALUMINUM"), SD))
    m = get_success_data(api.create_measurement(
        {"project_id": pj["id"], "width_in": 120, "depth_in": 144, "wall_height_in": 96,
         "existing_slab": True}, SD))
    get_success_data(api.accept_measurement(m["id"], SD))
    res = api.accept_measurement(m["id"], SD)
    validate_error(res, "ERR_INVALID_STATE")


def test_cancel_completed_project_terminal_lockdown(api):
    """PRD §3.1: "A `Homeowner` may cancel a project while it sits in any non-terminal pre-build
    state — that is, while its status is `DRAFT`, `MEASURED`, `DESIGNED`, `QUOTED`, or
    `PERMITTING`."
    PRD §3.1: "Any attempt to drive a transition from a state the entity is not in is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_completed_project_terminal_lockdown
    """
    set_clock("2026-05-10T00:00:00Z")
    ho, pj, ins = setup_completed_project(
        project_overrides={"structure_type": "THREE_SEASON", "material": "ALUMINUM"},
        scheduled_start="2026-05-11T08:00:00Z", scheduled_end="2026-05-11T17:00:00Z",
    )
    assert pj["status"] == "COMPLETED", pj
    res = api.cancel_project(pj["id"], make_homeowner_headers(ho["id"]))
    validate_error(res, "ERR_INVALID_STATE")
    pj_after = get_success_data(api.get_project(pj["id"], SD))
    assert pj_after["status"] == "COMPLETED", pj_after


def test_inspection_fail_then_reinspect_cycle(api):
    """PRD §3.7: "A failure requires the inspection to be `SCHEDULED` and the request to carry
    `punchlist_items` of at least 1; it sets the `result` to `FAILED_PUNCHLIST`, reopens the
    install job by setting its `progress_status` back to `IN_PROGRESS` for rework, drives the
    project `INSPECTING → INSTALLING`, and increments `Project.version` by one."
    PRD §3.7: "creates the inspection in `SCHEDULED` with an `attempt_no` one greater than the
    highest existing attempt on the project (never less than 1)"

    Design: Corner/state_machines/inspection_fail_then_reinspect_pass_cycle
    """
    set_clock("2026-05-10T00:00:00Z")
    ho, pj, ij, ins1 = setup_inspecting_project(
        project_overrides={"structure_type": "THREE_SEASON", "material": "ALUMINUM"},
        scheduled_start="2026-05-11T08:00:00Z", scheduled_end="2026-05-11T17:00:00Z",
    )
    failed = validate_success(api.fail_inspection(
        ins1["id"], create_inspection_fail_payload(2), INS), 200)
    assert failed["result"] == "FAILED_PUNCHLIST", failed
    # install job reopened to IN_PROGRESS; project back to INSTALLING.
    body = api.list_project_install_jobs(pj["id"], IM).json()
    ij_after = [x for x in body["data"] if x["id"] == ij["id"]][0]
    assert ij_after["progress_status"] == "IN_PROGRESS", ij_after
    pj_mid = get_success_data(api.get_project(pj["id"], SD))
    assert pj_mid["status"] == "INSTALLING", pj_mid
    # re-complete and schedule a second inspection -> attempt_no 2.
    get_success_data(api.complete_install_job(ij["id"], IM))
    ins2 = validate_success(api.create_inspection(
        create_inspection_payload(pj["id"], ij["id"]), IM), 201)
    assert ins2["attempt_no"] == 2, ins2
    pj_after = get_success_data(api.get_project(pj["id"], SD))
    assert pj_after["status"] == "INSPECTING", pj_after


def test_engineering_underrated_ruling_yields_failed(api):
    """PRD §3.4: "It fails when `rated_wind_mph` is below `required_wind_mph` or
    `rated_snow_psf` is below `required_snow_psf`; an attempt to mark a review passed while it
    is underrated on either axis is rejected with `ERR_ENGINEERING_UNDERRATED` (HTTP 422)."

    Design: Corner/state_machines/engineering_underrated_pass_attempt_rejected
    """
    # required wind 140 (homeowner.design_wind_speed_mph); rated wind 100 < 140 -> FAILED.
    ho, pj, q, pa = setup_permit_in_review(
        homeowner_overrides={"ground_snow_load_psf": 40, "design_wind_speed_mph": 140},
        project_overrides={"structure_type": "FOUR_SEASON",
                           "material": "THERMAL_BREAK_ALUMINUM"},
        measurement_overrides={"width_in": 180, "depth_in": 160, "wall_height_in": 108,
                               "existing_slab": False},
    )
    er = get_success_data(api.create_engineering_review(
        create_engineering_review_payload(pa["id"], pj["id"], rated_wind_mph=100,
                                          rated_snow_psf=50), SD))
    ruled = validate_success(api.rule_engineering_review(er["id"], PO), 200)
    assert ruled["status"] == "FAILED", ruled
