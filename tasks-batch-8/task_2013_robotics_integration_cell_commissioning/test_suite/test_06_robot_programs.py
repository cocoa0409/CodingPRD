"""Robot programs: dual dev/sim axes, release gating, rework revision
monotonicity (PRD §3.5)."""
from test_helpers import (
    ApiErrorId,
    assert_robot_program,
    create_acceptance_test_payload,
    create_released_program,
    create_robot_program_payload,
    make_controls_programmer_headers,
    make_site_supervisor_headers,
    record_simulation_payload,
    setup_project_in_design,
    setup_project_in_fat,
    validate_error,
    validate_success,
)


def test_program_release_without_sim_pass_rejected(api):
    """PRD §3.5: "Release moves `PEER_REVIEWED` to `RELEASED` and additionally
    requires the simulation axis to stand at `SIM_PASSED`."

    Design: Corner/state_machines/program_release_without_sim_pass_rejected
    """
    ctx = setup_project_in_design(project_overrides={"project_code": "P-PRE"})
    p1 = ctx["users"]["CONTROLS_PROGRAMMER"]
    p2 = ctx["users"]["CONTROLS_PROGRAMMER_2"]
    prog = make_controls_programmer_headers(p1["id"])
    rev = make_controls_programmer_headers(p2["id"])

    rp = validate_success(
        api.create_robot_program(
            ctx["project"]["id"], create_robot_program_payload(program_name="NS"), prog
        ),
        201,
    )
    validate_success(api.code_complete_robot_program(rp["id"], prog))
    reviewed = validate_success(api.peer_review_robot_program(rp["id"], rev))
    assert reviewed["dev_status"] == "PEER_REVIEWED"
    assert reviewed["sim_status"] == "UNSIMULATED"

    resp = api.release_robot_program(rp["id"], prog)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_robot_program_parallel_dev_and_sim_axes(api):
    """PRD §3.5: "The simulation axis cycles independently. ... Either way,
    `sim_iteration_count` increments by one." And "Release moves
    `PEER_REVIEWED` to `RELEASED` and additionally requires the simulation
    axis to stand at `SIM_PASSED`" — so a release while dev is `CODED` (not
    `PEER_REVIEWED`) is rejected as an invalid state.

    Design: Difficulty/non_linear_state_machine/robot_program_parallel_dev_and_sim_axes
    """
    ctx = setup_project_in_design(project_overrides={"project_code": "P-PAR"})
    p1 = ctx["users"]["CONTROLS_PROGRAMMER"]
    prog = make_controls_programmer_headers(p1["id"])

    rp = validate_success(
        api.create_robot_program(
            ctx["project"]["id"], create_robot_program_payload(program_name="AXIS"), prog
        ),
        201,
    )
    validate_success(api.code_complete_robot_program(rp["id"], prog))

    # Run a sim that exceeds the contract -> SIM_FAILED.
    validate_success(api.simulate_robot_program(rp["id"], prog))
    after_fail = validate_success(
        api.record_simulation(
            rp["id"], record_simulation_payload(11.0), prog
        )
    )
    assert_robot_program(after_fail)
    # Dev axis unchanged (still CODED); sim axis moved independently.
    assert after_fail["dev_status"] == "CODED"
    assert after_fail["sim_status"] == "SIM_FAILED"
    assert after_fail["sim_iteration_count"] == 1

    # Release while dev CODED (not PEER_REVIEWED) is rejected.
    resp = api.release_robot_program(rp["id"], prog)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_rework_cycle_preserves_release_revision_monotonicity(api):
    """PRD §3.5: "every release increments `release_revision` by one, so a
    program released, sent to `REWORK`, and released again accumulates release
    revisions." PRD §3.6: "Either failure increments the project's
    `rework_count` by one, moves every `RELEASED` robot program to `REWORK`
    (with `sim_status` untouched)".

    Design: Difficulty/compensating_invariant/rework_cycle_preserves_release_revision_monotonicity
    """
    ctx = setup_project_in_fat(project_overrides={"project_code": "P-CI2"})
    proj = ctx["project"]
    sup = ctx["users"]["SITE_SUPERVISOR"]
    p1 = ctx["users"]["CONTROLS_PROGRAMMER"]
    p2 = ctx["users"]["CONTROLS_PROGRAMMER_2"]
    sup_hdrs = make_site_supervisor_headers(sup["id"])
    prog_hdrs = make_controls_programmer_headers(p1["id"])
    rev_hdrs = make_controls_programmer_headers(p2["id"])

    from test_helpers import validate_paginated

    programs, _ = validate_paginated(api.list_robot_programs(proj["id"], sup_hdrs))
    rp = programs[0]
    assert rp["release_revision"] == 1

    # Fail FAT to trigger rework (RELEASED -> REWORK).
    fat = validate_success(
        api.create_acceptance_test(
            proj["id"],
            create_acceptance_test_payload(
                "FAT",
                measured_cycle_time_s=12.0,
                measured_oee_pct=70.0,
                defects_observed=5,
            ),
            sup_hdrs,
        ),
        201,
    )
    validate_success(api.fail_acceptance_test(fat["id"], sup_hdrs))

    # Second forward pass: REWORK -> CODED -> PEER_REVIEWED -> RELEASED.
    validate_success(api.code_complete_robot_program(rp["id"], prog_hdrs))
    validate_success(api.peer_review_robot_program(rp["id"], rev_hdrs))
    rel2 = validate_success(api.release_robot_program(rp["id"], prog_hdrs))

    assert rel2["release_revision"] == 2
    assert rel2["dev_status"] == "RELEASED"
    # Sim axis was untouched by the rework cascade, so SIM_PASSED survives.
    assert rel2["sim_status"] == "SIM_PASSED"

    from test_helpers import get_project

    proj_after = get_project(proj["id"], sup_hdrs)
    assert proj_after["rework_count"] == 1
