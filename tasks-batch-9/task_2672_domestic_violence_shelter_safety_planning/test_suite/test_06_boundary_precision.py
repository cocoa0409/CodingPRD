"""Exact boundaries: a secondary-trauma index sitting on the freeze threshold to the
tenth of a point, and a safety plan whose component set is empty by exactly one row.
"""

from test_helpers import (
    ApiErrorId,
    CLOCK_STARTUP_UTC,
    MODERATE_FACTORS,
    api_client,
    assert_component_scoring,
    assert_immutable_event,
    assert_wellness_check,
    client_version,
    create_plan_component_payload,
    create_safety_plan_payload,
    create_wellness_check_payload,
    get_success_data,
    read_plan,
    read_staff,
    seed_client_with_assessed_call,
    seed_draft_plan_by_disposition,
    seed_hotline_advocate,
    seed_shelter_manager,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_seventy_point_check_freezes_the_advocate_on_the_inclusive_boundary():
    """70.0 is inside the FROZEN band because the comparison is at-or-above.

    PRD: "A same-day check with `distress_scale` 10, `exposure_hours` 20.0 and no debrief
    contributes 70.0 and freezes the advocate outright; the same check with `exposure_hours`
    19.8 contributes 69.9 and only restricts them."

    Design: Difficulty/boundary_precision_check/trauma_index_at_exactly_seventy_freezes_advocate
    """
    advocate = seed_hotline_advocate("Rosa Marin")
    manager = seed_shelter_manager("Dana Whit")

    response = api_client.create_wellness_check(
        advocate.id,
        create_wellness_check_payload(
            checked_on_utc=CLOCK_STARTUP_UTC,
            exposure_hours=20.0,
            distress_scale=10,
            debrief_completed=False,
        ),
        manager.headers,
    )

    check = validate_success(response, 201)
    assert_wellness_check(check)
    assert_immutable_event(check)
    assert check["contribution_points"] == 70.0
    after = read_staff(advocate.id)
    assert after["secondary_trauma_index"] == 70.0
    assert after["wellness_posture"] == "FROZEN"
    assert after["active_caseload_count"] == 0
    rows, _meta = validate_paginated(
        api_client.list_wellness_checks(
            advocate.id, manager.headers, params={"limit": 100, "offset": 0}
        )
    )
    assert [row["contribution_points"] for row in rows] == [70.0]


def test_one_tenth_of_a_point_below_the_boundary_only_restricts():
    """69.9 misses FROZEN and lands in RESTRICTED instead.

    PRD: "`wellness_posture` is the threshold band over that index: `FROZEN` at 70.0 or
    above, otherwise `RESTRICTED` at 40.0 or above, otherwise `OPEN`."

    Design: Difficulty/boundary_precision_check/trauma_index_at_exactly_seventy_freezes_advocate
    """
    advocate = seed_hotline_advocate("Bea Cole")
    manager = seed_shelter_manager("Dana Whit")

    response = api_client.create_wellness_check(
        advocate.id,
        create_wellness_check_payload(
            checked_on_utc=CLOCK_STARTUP_UTC,
            exposure_hours=19.8,
            distress_scale=10,
            debrief_completed=False,
        ),
        manager.headers,
    )

    check = validate_success(response, 201)
    assert check["contribution_points"] == 69.9
    after = read_staff(advocate.id)
    assert after["secondary_trauma_index"] == 69.9
    assert after["wellness_posture"] == "RESTRICTED"
    assert after["active_caseload_count"] == 0


def _componentless_draft_plan():
    """A DRAFT plan authored for C-9201 that carries no components at all."""
    advocate = seed_hotline_advocate("Rosa Marin")
    client, call, assessment = seed_client_with_assessed_call(
        advocate,
        client_overrides={
            "client_code": "C-9201",
            "legal_name": "Nadia Roe",
            "household_size": 1,
            "minor_children_count": 0,
            "hmis_disclosure_consent": "DENIED",
        },
        assessment_overrides=dict(MODERATE_FACTORS),
        call_overrides={
            "presenting_concerns": "Wants to talk through options before deciding anything."
        },
    )
    seed_draft_plan_by_disposition(advocate, client["id"], call["id"])
    plan = get_success_data(
        api_client.create_safety_plan(
            create_safety_plan_payload(
                client["id"], assessment["id"], client_version(client["id"], advocate.headers)
            ),
            advocate.headers,
        )
    )
    assert plan["status"] == "DRAFT"
    assert plan["coverage_score"] == 0.0
    return advocate, plan


def test_activation_of_a_plan_with_zero_components_is_refused():
    """The empty component set is the boundary that blocks activation.

    PRD: "Activation requires at least one component on the plan — the empty component set
    is the exact boundary that blocks it, and an attempt on a plan with zero components is
    refused with `ERR_PLAN_HAS_NO_COMPONENTS` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/empty_component_set_blocks_plan_activation
    """
    advocate, plan = _componentless_draft_plan()

    response = api_client.activate_safety_plan(plan["id"], advocate.headers)

    validate_error(response, ApiErrorId.ERR_PLAN_HAS_NO_COMPONENTS.value, 422)
    unchanged = read_plan(plan["id"], advocate.headers)
    assert unchanged["status"] == "DRAFT"
    assert unchanged["coverage_score"] == 0.0
    assert unchanged["version"] == plan["version"]


def test_activation_succeeds_the_moment_the_component_count_reaches_one():
    """One component is enough, and activation then scores that single component.

    PRD: "Activating a plan moves it from `DRAFT` to `ACTIVE` and is the gate that makes
    housing work possible for the survivor."

    Design: Difficulty/boundary_precision_check/empty_component_set_blocks_plan_activation
    """
    advocate, plan = _componentless_draft_plan()
    validate_error(
        api_client.activate_safety_plan(plan["id"], advocate.headers),
        ApiErrorId.ERR_PLAN_HAS_NO_COMPONENTS.value,
        422,
    )
    component = get_success_data(
        api_client.create_plan_component(
            plan["id"],
            create_plan_component_payload(
                "COMMUNICATION",
                detail="Agree a code word with her neighbour and keep a spare charger at work.",
                target_completion_date="2026-08-14",
            ),
            advocate.headers,
        )
    )

    response = api_client.activate_safety_plan(plan["id"], advocate.headers)

    activated = validate_success(response, 200)
    assert activated["status"] == "ACTIVE"
    assert activated["coverage_score"] == 0.88
    rows = get_success_data(
        api_client.list_plan_components(
            plan["id"], advocate.headers, params={"limit": 100, "offset": 0}
        )
    )
    scored = [row for row in rows if row["id"] == component["id"]][0]
    assert_component_scoring(scored, 25, 0.88, "DRAFT")
