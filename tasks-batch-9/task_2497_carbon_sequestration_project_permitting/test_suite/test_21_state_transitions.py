"""State transitions across the permitting lifecycles of a storage project.

Submission and acceptance of a geologic model revision, the resting state of a
freshly drafted Class VI permit, the refusals that guard a wellbore's
corrective-action track, a terminated pore-space lease and an already-submitted
monitoring plan, the coverage score a retired monitoring method leaves behind,
and the severity-dependent emergency draw an order takes out of the posted
reserve.
"""

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import ApiErrorId, REVIEWER_USER_ID, factories, fixtures
from test_helpers.constants import (
    DEFAULT_INJECTION_YEARS,
    MRV_METHODS_SCORE_70,
    MRV_METHODS_SCORE_85,
    STARTUP_CLOCK_UTC,
    WELLBORE_CEMENTED_DOCUMENTED_FAR,
)


def test_geologic_model_submit_advances_project_to_site_characterization(
    api, project_developer_headers
):
    """Completing the simulation moves `plume_status` from `NOT_RUN` to
    `SIMULATED` and bumps the model's `version`. Each submission increments
    `revision_round_count` by one and sets `status` to `SUBMITTED`, bumping the
    model's `version`. The very first submission for a project also drives the
    project's own `status` from `DRAFT` to `SITE_CHARACTERIZATION`, bumping the
    project's `version` — a project that is already past `DRAFT` is left where it
    is.

    Design: Corner/state_machines/geologic_model_draft_to_submitted_advances_project_to_site_characterization
    """
    fixtures.set_logical_clock(api, STARTUP_CLOCK_UTC)
    project = fixtures.open_project(api)
    model = fixtures.register_geologic_model(api, project["id"], project["version"])
    simulated = fixtures.simulate_plume(api, model["id"], DEFAULT_INJECTION_YEARS)

    assert simulated["plume_status"] == "SIMULATED", (
        "running the plume simulation must move plume_status to SIMULATED, got "
        f"{simulated['plume_status']}"
    )

    data = validate_success(
        api.submit_geologic_model(
            model["id"],
            {"submission_note": "initial site characterization"},
            project_developer_headers,
        ),
        200,
    )

    assert data["status"] == "SUBMITTED", (
        f"submission must set the model status to SUBMITTED, got {data['status']}"
    )
    assert data["revision_round_count"] == 1, (
        "the first submission increments revision_round_count to 1, got "
        f"{data['revision_round_count']}"
    )

    refreshed_project = fixtures.refresh_project(api, project["id"])
    assert refreshed_project["status"] == "SITE_CHARACTERIZATION", (
        "the very first submission drives the project DRAFT -> "
        f"SITE_CHARACTERIZATION, got {refreshed_project['status']}"
    )
    refreshed_model = fixtures.refresh_model(api, model["id"])
    assert refreshed_model["plume_status"] == "SIMULATED", (
        "submission leaves the simulation dimension at SIMULATED, got "
        f"{refreshed_model['plume_status']}"
    )


def test_geologic_model_submit_without_simulation_rejected(
    api, project_developer_headers
):
    """A new model rests at `status` `DRAFT` with `plume_status` `NOT_RUN` and
    `revision_round_count` at 0; the create bumps the parent project's `version`
    by one. Submission is admissible only from `status` `DRAFT` or
    `REVISION_REQUESTED`, requires the model's `plume_status` to already be
    `SIMULATED` or `AOR_FINALIZED`, and requires the parent project not to be
    `FROZEN`. Each entity's own current state must admit the requested
    transition, and each entity has its own error code: the project's `status` or
    `unitization_status` yields `ERR_INVALID_PROJECT_STATE`; a geologic model's
    `status` or `plume_status` yields `ERR_INVALID_MODEL_STATE`; a wellbore's
    `corrective_action_status` yields `ERR_INVALID_WELLBORE_CA_STATE`; a tract's
    `lease_status` yields `ERR_INVALID_TRACT_STATE`; a permit's `permit_status`
    yields `ERR_INVALID_PERMIT_STATE` (this also guards reporting an injection
    period against a permit); the construction sequence yields
    `ERR_INVALID_CONSTRUCTION_SEQUENCE`; an unproven mechanical integrity test
    yields `ERR_MIT_NOT_PASSED`; a monitoring plan's `status` or an already-closed
    review track yields `ERR_INVALID_PLAN_STATE` (this also guards adding or
    retiring a method); an instrument's `status` yields
    `ERR_INVALID_INSTRUMENT_STATE`; and a claim, injection period record or
    remediation order in the wrong `status` yields `ERR_INVALID_CLAIM_STATE`.

    Design: Corner/state_machines/geologic_model_submit_without_simulation_rejected
    """
    fixtures.set_logical_clock(api, STARTUP_CLOCK_UTC)
    project = fixtures.open_project(api)
    model = fixtures.register_geologic_model(api, project["id"], project["version"])

    validate_error(
        api.submit_geologic_model(
            model["id"],
            {"submission_note": "premature submission"},
            project_developer_headers,
        ),
        ApiErrorId.ERR_INVALID_MODEL_STATE.value,
        409,
    )

    refreshed_model = fixtures.refresh_model(api, model["id"])
    assert refreshed_model["status"] == "DRAFT", (
        f"the refused submission leaves the model in DRAFT, got {refreshed_model['status']}"
    )
    assert refreshed_model["plume_status"] == "NOT_RUN", (
        "an unsimulated model keeps plume_status NOT_RUN, got "
        f"{refreshed_model['plume_status']}"
    )
    assert refreshed_model["revision_round_count"] == 0, (
        "a refused submission increments no review round, got "
        f"{refreshed_model['revision_round_count']}"
    )
    refreshed_project = fixtures.refresh_project(api, project["id"])
    assert refreshed_project["status"] == "DRAFT", (
        "no submission succeeded, so the project stays in DRAFT, got "
        f"{refreshed_project['status']}"
    )


def test_model_acceptance_sets_governing_model_and_assurance_requirement(
    api, regulatory_reviewer_headers
):
    """Every ruling requires the model to be in `SUBMITTED` and records the
    reviewer's `X-User-ID` in the model's `reviewer_user_id`. The model moves
    `SUBMITTED → ACCEPTED`. The project's `governing_geologic_model_id` is set to
    the newly accepted model. The project's `status` advances
    `SITE_CHARACTERIZATION → PERMITTING`. And because the governing model has
    changed, the project's `required_financial_assurance_usd` and
    `assurance_coverage_status` are recomputed. The post-injection site care
    bucket is the project's `pisc_duration_years` multiplied by its
    `effective_annual_monitoring_cost_usd`, rounded half up to 2 decimal places —
    fifty years of monitoring at the uplifted rate is by far the largest line
    item on most projects. The emergency reserve bucket is the larger of a
    two-million-dollar floor and the area-based figure obtained by multiplying
    500,000.00 dollars per square kilometre by pi and by the square of the
    project's `aor_radius_km`, that area-based figure being rounded half up to 2
    decimal places before the comparison. The administrative fee is tiered on the
    governing model's `effective_annual_injection_rate_tpy`: it is 250,000.00
    dollars when that rate is at most 500,000 tonnes per year, 500,000.00 dollars
    when the rate exceeds 500,000 but is at most 1,500,000 tonnes per year, and
    900,000.00 dollars when the rate exceeds 1,500,000 tonnes per year. The
    project's `required_financial_assurance_usd` is the sum of those five
    already-rounded buckets, itself rounded half up to 2 decimal places.
    `assurance_coverage_status` is then derived by comparing
    `allocated_assurance_usd` against `required_financial_assurance_usd`, and the
    tests are applied in this order: the status is `UNFUNDED` when
    `allocated_assurance_usd` is zero or below; otherwise it is `FUNDED` when
    `allocated_assurance_usd` is at least `required_financial_assurance_usd`;
    otherwise it is `UNDERFUNDED`. Until this delineation has happened for some
    accepted model, the project's `aor_radius_km` remains 0, and every operation
    that depends on a delineated area of review is refused with
    `ERR_AOR_NOT_DELINEATED` (HTTP 422).

    Design: Corner/state_machines/model_accept_sets_governing_model_and_requirement_snapshot
    """
    fixtures.set_logical_clock(api, STARTUP_CLOCK_UTC)
    project = fixtures.open_project(api)
    model = fixtures.register_geologic_model(api, project["id"], project["version"])
    fixtures.simulate_plume(api, model["id"], DEFAULT_INJECTION_YEARS)
    fixtures.submit_model(api, model["id"])

    data = validate_success(
        api.review_geologic_model(
            model["id"],
            {"decision": "ACCEPT", "review_note": "seal integrity acceptable"},
            regulatory_reviewer_headers,
        ),
        200,
    )

    assert data["status"] == "ACCEPTED", (
        f"an ACCEPT ruling moves the model to ACCEPTED, got {data['status']}"
    )
    assert data["reviewer_user_id"] == REVIEWER_USER_ID, (
        "the ruling records the acting reviewer identity "
        f"{REVIEWER_USER_ID} in reviewer_user_id, got {data['reviewer_user_id']}"
    )

    refreshed_project = fixtures.refresh_project(api, project["id"])
    assert refreshed_project["status"] == "PERMITTING", (
        "acceptance advances the project SITE_CHARACTERIZATION -> PERMITTING, got "
        f"{refreshed_project['status']}"
    )
    assert refreshed_project["governing_geologic_model_id"] == model["id"], (
        "governing_geologic_model_id must be the newly accepted model "
        f"{model['id']}, got {refreshed_project['governing_geologic_model_id']}"
    )
    assert refreshed_project["required_financial_assurance_usd"] == 12500000.00, (
        "10000000.00 of post-injection care plus the 2000000.00 emergency floor "
        "plus the 500000.00 administrative fee is 12500000.00, got "
        f"{refreshed_project['required_financial_assurance_usd']}"
    )
    assert refreshed_project["assurance_coverage_status"] == "UNFUNDED", (
        "nothing is allocated yet, so coverage reads UNFUNDED, got "
        f"{refreshed_project['assurance_coverage_status']}"
    )
    assert refreshed_project["aor_radius_km"] == 0, (
        "acceptance publishes no area of review, so aor_radius_km stays 0, got "
        f"{refreshed_project['aor_radius_km']}"
    )
    refreshed_model = fixtures.refresh_model(api, model["id"])
    assert refreshed_model["plume_status"] == "SIMULATED", (
        "the review dimension advanced without moving the simulation dimension, "
        f"got {refreshed_model['plume_status']}"
    )


def test_complete_corrective_action_from_identified_rejected(
    api, project_developer_headers
):
    """The `risk_score` is 100.0 multiplied by the seal factor, multiplied by the
    plug factor, multiplied by the record factor, multiplied by the quantity 0.40
    plus 0.60 times the proximity factor, rounded half up to 2 decimal places —
    so 40 percent of the score is fixed by the wellbore's own condition and 60
    percent is modulated by how close it sits to the injector. Immediately
    afterwards, each wellbore that has just reached `IDENTIFIED` and either has
    `penetrates_seal` true or carries a `risk_score` of at least 40.00
    auto-advances `IDENTIFIED → CA_REQUIRED` in the same request — a wellbore
    that penetrates the confining zone is always obligated regardless of its
    score, and a wellbore that does not penetrate the seal is obligated only once
    its score reaches the 40.00 threshold. Completing the work moves the wellbore
    `CA_SCHEDULED → CA_COMPLETE`, and may optionally carry a `completion_note`.
    When the obligated set is empty, `corrective_action_completion_pct` is exactly
    100.00. Each entity's own current state must admit the requested transition,
    and each entity has its own error code: the project's `status` or
    `unitization_status` yields `ERR_INVALID_PROJECT_STATE`; a geologic model's
    `status` or `plume_status` yields `ERR_INVALID_MODEL_STATE`; a wellbore's
    `corrective_action_status` yields `ERR_INVALID_WELLBORE_CA_STATE`; a tract's
    `lease_status` yields `ERR_INVALID_TRACT_STATE`; a permit's `permit_status`
    yields `ERR_INVALID_PERMIT_STATE` (this also guards reporting an injection
    period against a permit); the construction sequence yields
    `ERR_INVALID_CONSTRUCTION_SEQUENCE`; an unproven mechanical integrity test
    yields `ERR_MIT_NOT_PASSED`; a monitoring plan's `status` or an already-closed
    review track yields `ERR_INVALID_PLAN_STATE` (this also guards adding or
    retiring a method); an instrument's `status` yields
    `ERR_INVALID_INSTRUMENT_STATE`; and a claim, injection period record or
    remediation order in the wrong `status` yields `ERR_INVALID_CLAIM_STATE`.

    Design: Corner/state_machines/complete_corrective_action_from_identified_rejected
    """
    ctx = fixtures.setup_project_with_finalized_aor(
        api, wellbore_specs=[WELLBORE_CEMENTED_DOCUMENTED_FAR]
    )
    wellbore = ctx["wellbores"][0]
    assert wellbore["corrective_action_status"] == "IDENTIFIED", (
        "a cemented, documented wellbore 2.0 km inside the area of review scores "
        "below the 40.00 obligation threshold and stays IDENTIFIED, got "
        f"{wellbore['corrective_action_status']}"
    )

    validate_error(
        api.complete_corrective_action(
            wellbore["id"], {"completion_note": "nothing to do"}, project_developer_headers
        ),
        ApiErrorId.ERR_INVALID_WELLBORE_CA_STATE.value,
        409,
    )

    refreshed = fixtures.refresh_wellbore(api, wellbore["id"])
    assert refreshed["corrective_action_status"] == "IDENTIFIED", (
        "the refused completion leaves the wellbore in IDENTIFIED, got "
        f"{refreshed['corrective_action_status']}"
    )
    assert refreshed["risk_score"] == 7.65, (
        "100.0 x 0.85 x 0.25 x 0.60 x (0.40 + 0.60 x (1 - 2.0 / 3.0)) is 7.65, got "
        f"{refreshed['risk_score']}"
    )
    assert refreshed.get("ca_window_start") is None, (
        "no work window was ever scheduled, so ca_window_start stays null, got "
        f"{refreshed.get('ca_window_start')}"
    )
    refreshed_project = fixtures.refresh_project(api, ctx["project"]["id"])
    assert refreshed_project["corrective_action_completion_pct"] == 100.00, (
        "the obligated set is empty, so the completion percentage is exactly "
        f"100.00, got {refreshed_project['corrective_action_completion_pct']}"
    )


def test_new_injection_well_permit_starts_in_draft_and_not_started(
    api, project_developer_headers
):
    """Status codes follow one rule throughout: an operation that brings a new
    resource into existence responds with 201 Created, and every other successful
    operation — including every action endpoint that advances a state machine,
    every listing and every read — responds with 200 OK. The permit rests at
    `permit_status` `DRAFT` and `construction_status` `NOT_STARTED`, with
    `authorized_injection_rate_tpy` at 0, `revision_round_count` at 0, and
    `last_mit_type`, `last_mit_result`, `last_mit_at` and `activated_at` all null
    with `mit_pass_count` at 0. Opening review records the reviewer's `X-User-ID`
    in `technical_reviewer_user_id` — the field that later disqualifies that same
    identity from certifying the project's closure — and moves `permit_status`
    `SUBMITTED → TECHNICAL_REVIEW`.

    Design: Corner/state_machines/new_injection_well_permit_starts_in_draft_not_started
    """
    ctx = fixtures.setup_project_with_accepted_model(api)

    data = validate_success(
        api.create_injection_well_permit(
            factories.create_injection_well_permit_payload(
                ctx["project"]["id"], ctx["model"]["id"]
            ),
            project_developer_headers,
        ),
        201,
    )

    assert data["permit_status"] == "DRAFT", (
        f"a drafted permit rests at permit_status DRAFT, got {data['permit_status']}"
    )
    assert data["construction_status"] == "NOT_STARTED", (
        "the physical dimension rests at NOT_STARTED, got "
        f"{data['construction_status']}"
    )

    permit = fixtures.refresh_permit(api, data["id"])
    assert permit.get("last_mit_result") is None, (
        f"last_mit_result starts null, got {permit.get('last_mit_result')}"
    )
    assert permit.get("last_mit_at") is None, (
        f"last_mit_at starts null, got {permit.get('last_mit_at')}"
    )
    assert permit["mit_pass_count"] == 0, (
        f"mit_pass_count starts at 0, got {permit['mit_pass_count']}"
    )
    assert permit.get("technical_reviewer_user_id") is None, (
        "no technical review has been opened, so technical_reviewer_user_id is "
        f"null, got {permit.get('technical_reviewer_user_id')}"
    )
    assert permit.get("activated_at") is None, (
        f"activated_at starts null, got {permit.get('activated_at')}"
    )
    assert permit["revision_round_count"] == 0, (
        f"revision_round_count starts at 0, got {permit['revision_round_count']}"
    )


def test_terminated_tract_cannot_be_terminated_again(api, project_developer_headers):
    """Terminating an executed lease is the developer's exit, and it supplies a
    `termination_reason`. It is admissible only from `lease_status` `EXECUTED`,
    and only while the project's `status` is `DRAFT`, `SITE_CHARACTERIZATION` or
    `PERMITTING` — once injection has been authorized, acreage cannot be handed
    back. Termination clears `executed_bonus_per_acre_usd`,
    `executed_royalty_rate_pct`, `lease_term_start` and `lease_term_end` to null,
    zeroes both `bonus_settlement_usd` and `net_acreage`, and moves the tract
    `EXECUTED → TERMINATED`, which is terminal. At project level the holders are
    the tracts whose `lease_status` is `EXECUTED` or `UNITIZED`, summed in
    `created_at` ascending order: `secured_acreage` is the sum of their
    `net_acreage` values rounded half up to 4 decimal places,
    `outstanding_acreage` is `total_project_acreage` less `secured_acreage`
    rounded half up to 4 decimal places, `pore_space_consent_pct` is 100.0
    multiplied by `secured_acreage` divided by `total_project_acreage` rounded
    half up to 2 decimal places, and `pore_space_bonus_total_usd` is the sum of
    the holders' already-rounded `bonus_settlement_usd` values rounded half up to
    2 decimal places. Each entity's own current state must admit the requested
    transition, and each entity has its own error code: the project's `status` or
    `unitization_status` yields `ERR_INVALID_PROJECT_STATE`; a geologic model's
    `status` or `plume_status` yields `ERR_INVALID_MODEL_STATE`; a wellbore's
    `corrective_action_status` yields `ERR_INVALID_WELLBORE_CA_STATE`; a tract's
    `lease_status` yields `ERR_INVALID_TRACT_STATE`; a permit's `permit_status`
    yields `ERR_INVALID_PERMIT_STATE` (this also guards reporting an injection
    period against a permit); the construction sequence yields
    `ERR_INVALID_CONSTRUCTION_SEQUENCE`; an unproven mechanical integrity test
    yields `ERR_MIT_NOT_PASSED`; a monitoring plan's `status` or an already-closed
    review track yields `ERR_INVALID_PLAN_STATE` (this also guards adding or
    retiring a method); an instrument's `status` yields
    `ERR_INVALID_INSTRUMENT_STATE`; and a claim, injection period record or
    remediation order in the wrong `status` yields `ERR_INVALID_CLAIM_STATE`.

    Design: Corner/state_machines/terminated_tract_cannot_be_terminated_again
    """
    fixtures.set_logical_clock(api, STARTUP_CLOCK_UTC)
    project = fixtures.open_project(api)
    tract = fixtures.register_tract(api, project["id"], "T1", acreage=1000, ownership_pct=100)
    executed = fixtures.execute_tract_lease(api, tract)
    assert executed["lease_status"] == "EXECUTED", (
        f"the landowner's acceptance executes the lease, got {executed['lease_status']}"
    )

    first = get_success_data(
        api.terminate_lease(
            tract["id"],
            {"termination_reason": "title defect discovered"},
            project_developer_headers,
        )
    )
    assert first["lease_status"] == "TERMINATED", (
        f"the first termination moves the tract to TERMINATED, got {first['lease_status']}"
    )

    validate_error(
        api.terminate_lease(
            tract["id"],
            {"termination_reason": "duplicate termination attempt"},
            project_developer_headers,
        ),
        ApiErrorId.ERR_INVALID_TRACT_STATE.value,
        409,
    )

    refreshed = fixtures.refresh_tract(api, tract["id"])
    assert refreshed["lease_status"] == "TERMINATED", (
        "TERMINATED is terminal, so the refused second termination leaves it "
        f"there, got {refreshed['lease_status']}"
    )
    assert refreshed.get("executed_bonus_per_acre_usd") is None, (
        "termination cleared the executed bonus to null, got "
        f"{refreshed.get('executed_bonus_per_acre_usd')}"
    )
    assert refreshed["bonus_settlement_usd"] == 0, (
        f"termination zeroed the settlement, got {refreshed['bonus_settlement_usd']}"
    )

    refreshed_project = fixtures.refresh_project(api, project["id"])
    assert refreshed_project["secured_acreage"] == 0, (
        "the only holder left the holder set, so secured_acreage is 0, got "
        f"{refreshed_project['secured_acreage']}"
    )
    assert refreshed_project["outstanding_acreage"] == 4000.0000, (
        "the whole 4000 acres are outstanding again, got "
        f"{refreshed_project['outstanding_acreage']}"
    )
    assert refreshed_project["pore_space_consent_pct"] == 0.00, (
        f"consent falls back to 0.00, got {refreshed_project['pore_space_consent_pct']}"
    )


def test_repeated_monitoring_plan_submit_rejected_without_round_increment(
    api, project_developer_headers
):
    """Submitting a plan for review, optionally with a `submission_note`, is
    admissible from `status` `DRAFT` or `REVISION_REQUESTED` and requires the plan
    to hold at least one method whose `status` is `ACTIVE`. Submission resets both
    `technical_review_complete` and `public_comment_complete` to false, increments
    `revision_round_count` by one, recomputes all three subscores and the
    `coverage_score` from the current active methods, sets `status` to
    `SUBMITTED`, and bumps the plan's `version`. Each entity's own current state
    must admit the requested transition, and each entity has its own error code:
    the project's `status` or `unitization_status` yields
    `ERR_INVALID_PROJECT_STATE`; a geologic model's `status` or `plume_status`
    yields `ERR_INVALID_MODEL_STATE`; a wellbore's `corrective_action_status`
    yields `ERR_INVALID_WELLBORE_CA_STATE`; a tract's `lease_status` yields
    `ERR_INVALID_TRACT_STATE`; a permit's `permit_status` yields
    `ERR_INVALID_PERMIT_STATE` (this also guards reporting an injection period
    against a permit); the construction sequence yields
    `ERR_INVALID_CONSTRUCTION_SEQUENCE`; an unproven mechanical integrity test
    yields `ERR_MIT_NOT_PASSED`; a monitoring plan's `status` or an already-closed
    review track yields `ERR_INVALID_PLAN_STATE` (this also guards adding or
    retiring a method); an instrument's `status` yields
    `ERR_INVALID_INSTRUMENT_STATE`; and a claim, injection period record or
    remediation order in the wrong `status` yields `ERR_INVALID_CLAIM_STATE`.

    Design: Corner/state_machines/repeated_monitoring_plan_submit_rejected_without_second_round_increment
    """
    fixtures.set_logical_clock(api, STARTUP_CLOCK_UTC)
    project = fixtures.open_project(api)
    plan, _methods = fixtures.create_monitoring_plan_with_methods(
        api, project["id"], methods=[MRV_METHODS_SCORE_85[0]]
    )

    first = validate_success(
        api.submit_monitoring_plan(
            plan["id"], {"submission_note": "first submission"}, project_developer_headers
        ),
        200,
    )
    assert first["revision_round_count"] == 1, (
        "the first submission increments revision_round_count to 1, got "
        f"{first['revision_round_count']}"
    )

    validate_error(
        api.submit_monitoring_plan(
            plan["id"],
            {"submission_note": "same submission again"},
            project_developer_headers,
        ),
        ApiErrorId.ERR_INVALID_PLAN_STATE.value,
        409,
    )

    refreshed = fixtures.refresh_plan(api, plan["id"])
    assert refreshed["status"] == "SUBMITTED", (
        f"the plan stays where the first submission left it, got {refreshed['status']}"
    )
    assert refreshed["revision_round_count"] == 1, (
        "a refused re-submission adds no review round, got "
        f"{refreshed['revision_round_count']}"
    )
    assert refreshed["technical_review_complete"] is False, (
        "the technical track is still open, got "
        f"{refreshed['technical_review_complete']}"
    )
    assert refreshed["public_comment_complete"] is False, (
        "the public comment track is still open, got "
        f"{refreshed['public_comment_complete']}"
    )


def test_monitoring_method_retirement_lowers_plan_coverage_score(
    api, project_developer_headers
):
    """The `method_score` is the product of those three terms, rounded half up to
    4 decimal places. Each domain subscore is the sum of the `method_score` values
    of that domain's methods whose `status` is `ACTIVE`, capped at 1.0000 and
    rounded half up to 4 decimal places — so `subsurface_subscore`,
    `surface_subscore` and `atmospheric_subscore` each saturate, and piling a
    fourth seismic survey onto an already-saturated subsurface domain adds
    nothing. Methods whose `status` is `RETIRED` contribute exactly 0 to their
    domain. The plan's `coverage_score` is 100.0 multiplied by the weighted sum of
    the three subscores, where `subsurface_subscore` carries a weight of 0.50,
    `surface_subscore` a weight of 0.30 and `atmospheric_subscore` a weight of
    0.20, rounded half up to 2 decimal places. Retiring a method requires a
    `retirement_reason`, sets the method's `status` to `RETIRED`, recomputes the
    same four figures, and bumps both the method's `version` and the plan's
    `version`.

    Design: Corner/state_machines/monitoring_method_retirement_lowers_plan_coverage_score
    """
    fixtures.set_logical_clock(api, STARTUP_CLOCK_UTC)
    project = fixtures.open_project(api)
    plan, methods = fixtures.create_monitoring_plan_with_methods(
        api, project["id"], methods=MRV_METHODS_SCORE_70
    )
    surface_method = methods[1]
    assert surface_method["method_score"] == 0.5000, (
        "50 percent coverage at the surface reference frequency and reference "
        f"detection threshold scores 0.5000, got {surface_method['method_score']}"
    )

    before = fixtures.refresh_plan(api, plan["id"])
    assert before["coverage_score"] == 70.00, (
        "100 x (0.50 x 1.0000 + 0.30 x 0.5000 + 0.20 x 0.2500) is 70.00, got "
        f"{before['coverage_score']}"
    )
    assert before["surface_subscore"] == 0.5000, (
        f"the only surface method carries the domain, got {before['surface_subscore']}"
    )

    retired = validate_success(
        api.retire_monitoring_method(
            surface_method["id"],
            {"retirement_reason": "soil gas array decommissioned"},
            project_developer_headers,
        ),
        200,
    )
    assert retired["status"] == "RETIRED", (
        f"retirement sets the method status to RETIRED, got {retired['status']}"
    )

    listed, _meta = validate_paginated(
        api.list_monitoring_methods(plan["id"], project_developer_headers)
    )
    stored = [method for method in listed if method["id"] == surface_method["id"]]
    assert stored, "the retired method must still be listed under its plan"
    assert stored[0]["method_score"] == 0.5000, (
        "the retired row keeps its own method_score, got "
        f"{stored[0]['method_score']}"
    )

    after = fixtures.refresh_plan(api, plan["id"])
    assert after["surface_subscore"] == 0.0000, (
        "a retired method contributes exactly 0 to its domain, got "
        f"{after['surface_subscore']}"
    )
    assert after["subsurface_subscore"] == 1.0000, (
        f"the subsurface domain is untouched, got {after['subsurface_subscore']}"
    )
    assert after["atmospheric_subscore"] == 0.2500, (
        f"the atmospheric domain is untouched, got {after['atmospheric_subscore']}"
    )
    assert after["coverage_score"] == 55.00, (
        "100 x (0.50 x 1.0000 + 0.30 x 0.0000 + 0.20 x 0.2500) is 55.00, got "
        f"{after['coverage_score']}"
    )
    assert after["status"] == "DRAFT", (
        f"retirement does not move the plan's own status, got {after['status']}"
    )


def test_critical_remediation_order_draws_reserve_while_minor_does_not(
    api, regulatory_reviewer_headers
):
    """Opening stamps `opened_at` with the logical clock, sets the order's
    `status` to `OPEN`, and computes its `reserve_draw_usd`. The draw is zero —
    exactly 0.00 — for `MINOR` and `MAJOR` severity. For `CRITICAL` severity it is
    the smaller of the chosen instrument's `allocated_emergency_usd` and one
    quarter of the project's `required_financial_assurance_usd`, rounded half up
    to 2 decimal places. The instrument chosen is the project's instrument whose
    `status` is `ALLOCATED`; where several qualify, the one with the largest
    `allocated_emergency_usd` is chosen, breaking ties by `created_at` ascending;
    where none qualifies, the draw is 0.00 and no instrument changes state at all.
    When a draw does occur, that instrument's `drawn_usd` is set to the order's
    `reserve_draw_usd`, its `allocated_emergency_usd` is reduced by the drawn
    amount, its `status` moves `ALLOCATED → DRAWN`, the project's
    `allocated_assurance_usd` and `assurance_coverage_status` are recomputed, and
    both the instrument's `version` and the project's `version` increment. The
    project's `open_remediation_count` increments by one. When the `severity` is
    `MAJOR` or `CRITICAL`, the project's `operational_posture` is set to `FROZEN`
    — which then drives every `ACTIVE` permit of the project to `SUSPENDED` with
    its `authorized_injection_rate_tpy` zeroed, which in turn reverts every
    `SUBMITTED` claim of the project to `DRAFT`, which in turn forces a
    recomputation of the project's `pending_credit_usd`. A `MINOR` order
    increments the count and is recorded, but does not freeze the project.
    Allocation sets the instrument's `status` to `ALLOCATED`, recomputes the
    project's `allocated_assurance_usd` as the sum, over the project's instruments
    whose `status` is `ALLOCATED`, of their four allocated buckets (rounded half
    up to 2 decimal places), resets `assurance_coverage_status`, and bumps both
    the instrument's `version` and the project's `version`.
    `assurance_coverage_status` is then derived by comparing
    `allocated_assurance_usd` against `required_financial_assurance_usd`, and the
    tests are applied in this order: the status is `UNFUNDED` when
    `allocated_assurance_usd` is zero or below; otherwise it is `FUNDED` when
    `allocated_assurance_usd` is at least `required_financial_assurance_usd`;
    otherwise it is `UNDERFUNDED`.

    Design: Corner/state_machines/critical_remediation_order_draws_reserve_while_minor_does_not
    """
    ctx = fixtures.setup_authorized_project(api)
    project_id = ctx["project"]["id"]
    instrument_id = ctx["instrument"]["id"]

    assert ctx["project"]["status"] == "INJECTION_AUTHORIZED", (
        "the project must reach INJECTION_AUTHORIZED before an order may be "
        f"opened, got {ctx['project']['status']}"
    )
    assert ctx["project"]["required_financial_assurance_usd"] == pytest.approx(
        25487166.94, abs=0.01
    ), (
        "the five buckets sum to 25487166.94, got "
        f"{ctx['project']['required_financial_assurance_usd']}"
    )
    assert ctx["instrument"]["allocated_emergency_usd"] == pytest.approx(
        14637166.94, abs=0.01
    ), (
        "the emergency bucket takes the reserve plus the administrative fee, "
        f"14637166.94, got {ctx['instrument']['allocated_emergency_usd']}"
    )

    minor = validate_success(
        api.create_remediation_order(
            factories.create_remediation_order_payload(
                project_id,
                trigger_type="GROUNDWATER_IMPACT",
                severity="MINOR",
                narrative="shallow monitoring well shows a minor chloride rise",
            ),
            regulatory_reviewer_headers,
        ),
        201,
    )
    assert minor["reserve_draw_usd"] == 0.00, (
        f"a MINOR order draws exactly 0.00, got {minor['reserve_draw_usd']}"
    )
    assert minor["status"] == "OPEN", (
        f"a newly opened order rests at OPEN, got {minor['status']}"
    )

    after_minor = fixtures.refresh_instrument(api, instrument_id)
    assert after_minor["status"] == "ALLOCATED", (
        "no draw occurred, so the instrument stays ALLOCATED, got "
        f"{after_minor['status']}"
    )
    assert after_minor["drawn_usd"] == 0.00, (
        f"no dollars left the instrument, got {after_minor['drawn_usd']}"
    )
    project_after_minor = fixtures.refresh_project(api, project_id)
    assert project_after_minor["operational_posture"] == "OPEN", (
        "a MINOR order does not freeze the project, got "
        f"{project_after_minor['operational_posture']}"
    )
    assert project_after_minor["open_remediation_count"] == 1, (
        "the order count increments by one, got "
        f"{project_after_minor['open_remediation_count']}"
    )

    critical = validate_success(
        api.create_remediation_order(
            factories.create_remediation_order_payload(
                project_id,
                trigger_type="SEAL_BREACH_INDICATION",
                severity="CRITICAL",
                narrative=(
                    "pressure signature indicates seal breach above the injection zone"
                ),
            ),
            regulatory_reviewer_headers,
        ),
        201,
    )
    assert critical["reserve_draw_usd"] == pytest.approx(6371791.74, abs=0.01), (
        "round(min(14637166.94, 0.25 x 25487166.94), 2) is 6371791.74, got "
        f"{critical['reserve_draw_usd']}"
    )

    drawn = fixtures.refresh_instrument(api, instrument_id)
    assert drawn["status"] == "DRAWN", (
        f"the draw moves the instrument ALLOCATED -> DRAWN, got {drawn['status']}"
    )
    assert drawn["drawn_usd"] == pytest.approx(6371791.74, abs=0.01), (
        f"drawn_usd takes the order's reserve draw, got {drawn['drawn_usd']}"
    )
    assert drawn["allocated_emergency_usd"] == pytest.approx(8265375.20, abs=0.01), (
        "14637166.94 less the 6371791.74 drawn is 8265375.20, got "
        f"{drawn['allocated_emergency_usd']}"
    )
    assert drawn["allocated_pisc_usd"] == pytest.approx(10000000.00, abs=0.01), (
        "the post-injection bucket is untouched by the draw, got "
        f"{drawn['allocated_pisc_usd']}"
    )
    assert drawn["allocated_plugging_usd"] == pytest.approx(850000.00, abs=0.01), (
        f"the plugging bucket is untouched by the draw, got {drawn['allocated_plugging_usd']}"
    )
    assert drawn["unallocated_usd"] == pytest.approx(512833.06, abs=0.01), (
        f"the unallocated remainder is untouched by the draw, got {drawn['unallocated_usd']}"
    )

    project_after_critical = fixtures.refresh_project(api, project_id)
    assert project_after_critical["open_remediation_count"] == 2, (
        "both orders are open, got "
        f"{project_after_critical['open_remediation_count']}"
    )
    assert project_after_critical["operational_posture"] == "FROZEN", (
        "a CRITICAL order freezes the posture, got "
        f"{project_after_critical['operational_posture']}"
    )
    assert project_after_critical["allocated_assurance_usd"] == pytest.approx(
        0.00, abs=0.01
    ), (
        "no instrument is ALLOCATED any longer, so allocated_assurance_usd is "
        f"0.00, got {project_after_critical['allocated_assurance_usd']}"
    )
    assert project_after_critical["assurance_coverage_status"] == "UNFUNDED", (
        "nothing allocated reads UNFUNDED, got "
        f"{project_after_critical['assurance_coverage_status']}"
    )
