"""Completion bubble-up cascade and the conserved program budget partition
(reserve on execute, release on completion), plus initial partition at program creation."""
from test_helpers import (
    validate_success,
    create_program, create_parcel, create_application, submit_application,
    start_review, approve_application, execute_agreement, activate_agreement,
    add_covenant, submit_report, accept_report, setup_active_agreement,
    create_program_payload,
    make_director_headers,
)

DIRECTOR = make_director_headers("director-1")


def test_accept_drives_last_covenant_to_met(api):
    """PRD §3.5: "A covenant whose recomputed attainment is greater than or equal to 100.00
    advances to `MET`; a covenant below 100.00 advances to `BREACHED`." Jobs 100/100 -> MET.

    Design: Difficulty/transitive_cascade/accept_covenant_completion_bubble_depth3
    """
    ctx = setup_active_agreement(app_overrides={"but_for_attested": True})
    agr_id = ctx["agreement"]["id"]
    cov = add_covenant(agr_id, covenant_type="JOBS", target_value=100)
    rep = submit_report(agr_id, actual_jobs=100, attestation=True)
    accept_report(rep["id"])
    got = validate_success(api.get_covenant(cov["id"], DIRECTOR))
    assert got["status"] == "MET"


def test_completion_bubbles_agreement_to_completed(api):
    """PRD §3.5: "If the recomputation leaves every covenant on the agreement in `MET` or
    `WAIVED`, the agreement bubbles from `ACTIVE` to `COMPLETED` and the remaining reservation is
    released to available budget."

    Design: Difficulty/transitive_cascade/accept_covenant_completion_bubble_depth3
    """
    ctx = setup_active_agreement(app_overrides={"but_for_attested": True})
    agr_id = ctx["agreement"]["id"]
    add_covenant(agr_id, covenant_type="JOBS", target_value=100)
    rep = submit_report(agr_id, actual_jobs=100, attestation=True)
    accept_report(rep["id"])
    agr = validate_success(api.get_agreement(agr_id, DIRECTOR))
    assert agr["status"] == "COMPLETED"


def _budget_lifecycle(api):
    """Full GRANT lifecycle (cap 50,000,000) to COMPLETED. Returns program snapshots after
    execute and after completion, plus the final agreement."""
    prog = create_program()
    parcel = create_parcel()
    app = create_application(prog["id"], but_for_attested=True)
    submit_application(app["id"], "applicant-1")
    start_review(app["id"], "analyst-1")
    approve_application(app["id"], "director-1")
    agr = execute_agreement(app["id"], parcel["id"], awarded_jobs=100)
    prog_after_execute = validate_success(api.get_program(prog["id"], DIRECTOR))
    activate_agreement(agr["id"])
    add_covenant(agr["id"], covenant_type="JOBS", target_value=100)
    rep = submit_report(agr["id"], actual_jobs=100, attestation=True)
    accept_report(rep["id"])
    prog_after_complete = validate_success(api.get_program(prog["id"], DIRECTOR))
    agr_final = validate_success(api.get_agreement(agr["id"], DIRECTOR))
    return prog_after_execute, prog_after_complete, agr_final


def test_execute_reserves_award_into_committed(api):
    """PRD §2.6: "When an agreement is executed, its award cap is moved from available into
    committed: `committed_cents` increases by the agreement's `max_incentive_cents` and
    `available_budget_cents` decreases by the same amount."

    Design: Difficulty/compensating_invariant/program_budget_partition_conserved
    """
    prog_exec, _, _ = _budget_lifecycle(api)
    assert prog_exec["committed_cents"] == 50_000_000, prog_exec["committed_cents"]
    assert prog_exec["available_budget_cents"] == 950_000_000, prog_exec["available_budget_cents"]
    assert (prog_exec["available_budget_cents"] + prog_exec["committed_cents"]
            + prog_exec["disbursed_cents"]) == prog_exec["total_budget_cents"]


def test_completion_releases_reservation(api):
    """PRD §2.6: "When an agreement reaches `COMPLETED` or `CLOSED`, any remaining reservation is
    released: `committed_cents` decreases by the agreement's `max_incentive_cents` and
    `available_budget_cents` increases by the same amount."

    Design: Difficulty/compensating_invariant/program_budget_partition_conserved
    """
    _, prog_done, agr_final = _budget_lifecycle(api)
    assert agr_final["status"] == "COMPLETED"
    assert prog_done["committed_cents"] == 0, prog_done["committed_cents"]
    assert prog_done["available_budget_cents"] == 1_000_000_000, prog_done["available_budget_cents"]
    assert prog_done["disbursed_cents"] == 0, prog_done["disbursed_cents"]


def test_program_create_returns_201_with_partition(api):
    """PRD §2.6: "At program creation, `committed_cents` and `disbursed_cents` are both 0 and
    `available_budget_cents` equals `total_budget_cents`."
    PRD §3.1: "`but_for_pass_threshold`, the minimum eligibility score for a passing review,
    which defaults to 60 when omitted".

    Design: Corner/entities/program_create_returns_201_with_partition
    """
    data = validate_success(api.create_program(
        create_program_payload(total_budget_cents=500_000_000), DIRECTOR), expected_status=201)
    assert data["total_budget_cents"] == 500_000_000
    assert data["available_budget_cents"] == 500_000_000
    assert data["committed_cents"] == 0
    assert data["disbursed_cents"] == 0
    assert data["but_for_pass_threshold"] == 60
