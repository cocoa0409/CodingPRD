"""The conserved development ledger and the precedence of state and version checks."""
import pytest

from test_helpers import (
    assert_committed_budget_equals_live_sum,
    book_pilot_run,
    cancel_pilot_run,
    complete_pilot_run,
    create_formulation,
    formulation_version,
    intake_project,
    read_formulation,
    read_project,
    register_pilot_line,
    set_clock,
    setup_project_at_budget_cap,
    shelf_life_study_payload,
    start_pilot_run,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_superseded_revision_answers_state_before_version_conflict(api, rnd_lead_headers):
    """A stale version against a superseded revision reports the state error, not 412.

    PRD: "State is checked **before** optimistic concurrency, so a stale version supplied
    against an already-terminal row reports the state error rather than 412."

    Design: Difficulty/priority_pair_validation_conflict/state_check_precedes_occ_on_superseded_formulation
    """
    set_clock("2026-08-03T00:00:00Z")
    project = intake_project(name="State Beats OCC Probe", strategic_fit_score=7,
                             consumer_need_score=8, target_gross_margin_pct=32,
                             category_attractiveness_score=6)
    revision_one = create_formulation(project["id"])
    stale_version = revision_one["version"]
    create_formulation(project["id"], spec_summary="Yuzu base B", unit_cost_usd=1.0600)

    response = api.create_shelf_life_study(
        revision_one["id"],
        shelf_life_study_payload(stale_version, duration_days=30, committed_cost_usd=10000.00,
                                 start_at="2026-08-07T09:00:00Z"),
        rnd_lead_headers,
    )

    validate_error(response, "ERR_FORMULATION_INVALID_STATE", 409)
    assert read_formulation(revision_one["id"])["version"] > stale_version, (
        "the supersede cascade really did move the revision past the declared version"
    )


def test_the_refused_study_on_a_superseded_revision_writes_nothing(api, rnd_lead_headers):
    """The refusal leaves the revision superseded, storing no study and no commitment.

    PRD: "A rejected write leaves the prior formulation, its label approvals and the launch lock
    completely untouched; the cascade only ever runs inside an accepted write."

    Design: Difficulty/priority_pair_validation_conflict/state_check_precedes_occ_on_superseded_formulation
    """
    set_clock("2026-08-03T00:00:00Z")
    project = intake_project(name="State Beats OCC Probe", strategic_fit_score=7,
                            consumer_need_score=8, target_gross_margin_pct=32,
                            category_attractiveness_score=6)
    revision_one = create_formulation(project["id"])
    stale_version = revision_one["version"]
    revision_two = create_formulation(project["id"], spec_summary="Yuzu base B",
                                      unit_cost_usd=1.0600)

    validate_error(
        api.create_shelf_life_study(
            revision_one["id"],
            shelf_life_study_payload(stale_version, duration_days=30,
                                     committed_cost_usd=10000.00,
                                     start_at="2026-08-07T09:00:00Z"),
            rnd_lead_headers,
        ),
        "ERR_FORMULATION_INVALID_STATE",
        409,
    )

    assert read_formulation(revision_one["id"])["status"] == "SUPERSEDED"
    assert read_formulation(revision_two["id"])["revision"] == 2
    assert read_formulation(revision_two["id"])["status"] == "DRAFT"
    _, meta = validate_paginated(
        api.list_shelf_life_studies(revision_one["id"], rnd_lead_headers)
    )
    assert meta["total_count"] == 0, "the refused study was never stored"
    assert read_project(project["id"])["development_budget_committed_usd"] == pytest.approx(
        0.00, abs=0.01
    )


def test_a_stale_formulation_version_outranks_the_budget_cap(api, rnd_lead_headers):
    """A study that is both stale and unaffordable answers 412, not 422.

    PRD: "Concurrency runs after state and before every business rule, so a stale version
    outranks a budget overrun or a referential violation raised by the same request."

    Design: Difficulty/priority_pair_validation_conflict/occ_check_precedes_dev_budget_on_stale_formulation
    """
    set_clock("2026-08-03T00:00:00Z")
    line = register_pilot_line(line_code="AKR-2", hourly_cost_usd=800.00)
    project = intake_project(name="OCC Beats Budget Probe",
                             development_budget_cap_usd=100000.00)
    formulation = create_formulation(project["id"])
    run = book_pilot_run(formulation["id"], line["id"], committed_cost_usd=60000.00)
    set_clock("2026-08-06T08:00:00Z")
    start_pilot_run(run["id"])
    complete_pilot_run(run["id"], 8500)
    current_version = formulation_version(formulation["id"])

    response = api.create_shelf_life_study(
        formulation["id"],
        shelf_life_study_payload(current_version - 1, duration_days=30,
                                 committed_cost_usd=60000.00,
                                 start_at="2026-08-07T09:00:00Z"),
        rnd_lead_headers,
    )

    validate_error(response, "ERR_FORMULATION_VERSION_CONFLICT", 412)
    assert current_version > 1, (
        "completing the run advanced the formulation row, so the declared version is stale"
    )


def test_the_refused_stale_study_leaves_the_ledger_on_the_run_alone(api, rnd_lead_headers):
    """60000 committed plus a refused 60000 study still reads 60000, not a budget error.

    PRD: "This is the lowest band, so a stale formulation version or a pilot line window
    conflict is always reported ahead of a budget overrun."

    Design: Difficulty/priority_pair_validation_conflict/occ_check_precedes_dev_budget_on_stale_formulation
    """
    set_clock("2026-08-03T00:00:00Z")
    line = register_pilot_line(line_code="AKR-2", hourly_cost_usd=800.00)
    project = intake_project(name="OCC Beats Budget Probe",
                             development_budget_cap_usd=100000.00)
    formulation = create_formulation(project["id"])
    run = book_pilot_run(formulation["id"], line["id"], committed_cost_usd=60000.00)
    set_clock("2026-08-06T08:00:00Z")
    start_pilot_run(run["id"])
    complete_pilot_run(run["id"], 8500)

    validate_error(
        api.create_shelf_life_study(
            formulation["id"],
            shelf_life_study_payload(formulation_version(formulation["id"]) - 1,
                                     duration_days=30, committed_cost_usd=60000.00,
                                     start_at="2026-08-07T09:00:00Z"),
            rnd_lead_headers,
        ),
        "ERR_FORMULATION_VERSION_CONFLICT",
        412,
    )

    project = read_project(project["id"])
    assert_committed_budget_equals_live_sum(project, [60000.00])
    cleared = read_formulation(formulation["id"])
    assert cleared["status"] == "PILOT_PASSED"
    assert cleared["best_pilot_yield_pct"] == pytest.approx(85.00, abs=0.01)
    _, meta = validate_paginated(
        api.list_shelf_life_studies(formulation["id"], rnd_lead_headers)
    )
    assert meta["total_count"] == 0


def test_a_ledger_sitting_exactly_on_the_cap_refuses_one_more_cent(api, rnd_lead_headers):
    """Two runs and a study fill a 200000 cap to the cent, and the next cent is refused.

    PRD: "A create that would push the post-write value above the project's
    `development_budget_cap_usd` is rejected with `ERR_DEV_BUDGET_EXCEEDED` (422); the boundary
    itself is permitted, so a write that lands the committed total exactly on the cap succeeds
    while one cent more does not."

    Design: Difficulty/compensating_invariant/dev_budget_ledger_restored_after_pilot_run_cancel
    """
    ctx = setup_project_at_budget_cap()
    at_cap = read_project(ctx["project"]["id"])
    assert_committed_budget_equals_live_sum(at_cap, [20000.00, 100000.00, 80000.00])
    assert at_cap["development_budget_committed_usd"] == pytest.approx(200000.00, abs=0.01)

    response = api.create_shelf_life_study(
        ctx["formulation"]["id"],
        shelf_life_study_payload(formulation_version(ctx["formulation"]["id"]),
                                 duration_days=15, committed_cost_usd=0.01,
                                 start_at="2026-08-09T09:00:00Z"),
        rnd_lead_headers,
    )

    validate_error(response, "ERR_DEV_BUDGET_EXCEEDED", 422)
    _, meta = validate_paginated(
        api.list_shelf_life_studies(ctx["formulation"]["id"], rnd_lead_headers)
    )
    assert meta["total_count"] == 1, "the one affordable study is the only one stored"
    assert read_project(ctx["project"]["id"])[
        "development_budget_committed_usd"
    ] == pytest.approx(200000.00, abs=0.01)


def test_cancelling_a_run_releases_its_cost_and_its_line_window_exactly(api, rnd_lead_headers):
    """The released 100000 and the released window both come back with no drift.

    PRD: "Because the field is a sum over live contributors rather than an accumulator,
    releases are exact and drift-free: a run that moves to `CANCELLED` and a study that moves to
    `ABANDONED` both drop out of the basis, returning the field to precisely its pre-write
    value, which means the same cost can be committed again afterwards."

    Design: Difficulty/compensating_invariant/dev_budget_ledger_restored_after_pilot_run_cancel
    """
    ctx = setup_project_at_budget_cap()

    cancelled = cancel_pilot_run(ctx["pilot_run"]["id"],
                                 reason="Line released for a customer trial")
    released = read_project(ctx["project"]["id"])
    rebooked = validate_success(
        api.create_pilot_run(
            ctx["formulation"]["id"],
            {
                "pilot_line_id": ctx["pilot_line"]["id"],
                "window_start": ctx["pilot_run"]["window_start"],
                "window_end": ctx["pilot_run"]["window_end"],
                "planned_units": ctx["pilot_run"]["planned_units"],
                "committed_cost_usd": 100000.00,
            },
            rnd_lead_headers,
        ),
        201,
    )
    restored = read_project(ctx["project"]["id"])

    assert cancelled["status"] == "CANCELLED"
    assert_committed_budget_equals_live_sum(released, [20000.00, 80000.00])
    assert rebooked["status"] == "SCHEDULED", (
        "a cancelled run frees the line window as well as the money"
    )
    assert_committed_budget_equals_live_sum(restored, [20000.00, 100000.00, 80000.00])
    assert restored["development_budget_committed_usd"] == pytest.approx(200000.00, abs=0.01)
    study = validate_success(
        api.get_shelf_life_study(ctx["shelf_life_study"]["id"], rnd_lead_headers)
    )
    assert study["status"] == "ACTIVE", "the study's commitment never moved"
