"""Version ratcheting and read-your-write consistency across the project file.

The concern under test is that the storage project's version counter advances
exactly one step per write so the next write can quote the value the previous one
produced, and that the consequences of a write — the area-of-review delineation
cascade onto the project and its legacy wellbores, and a freshly added monitoring
method's effect on its plan's listing and derived score — are already visible to
the very next request.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories, fixtures
from test_helpers.constants import (
    MRV_METHODS_SCORE_70_FREE_TEXT,
    STARTUP_CLOCK_UTC,
    WELLBORE_SEAL_OPEN_HOLE_DEEP_NEAR,
)


def test_project_version_advances_one_step_per_geologic_model_create(
    api, program_admin_headers, project_developer_headers
):
    """`version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that resource — including mutations that arrive as a cascade from a sibling or parent operation rather than as a direct request against the resource.

    Creating a geologic model must carry `expected_project_version` equal to the target storage project's current `version`.

    A new model rests at `status` `DRAFT` with `plume_status` `NOT_RUN` and `revision_round_count` at 0; the create bumps the parent project's `version` by one.

    An optional `assessment_variant` nominates which parameter set governs the model's classification and is one of `DETERMINISTIC` or `PROBABILISTIC_P10`, defaulting to `DETERMINISTIC`.

    Design: Corner/cross_cutting_complexity_layers/project_version_advances_one_step_per_write_and_the_matching_version_is_accepted
    """
    fixtures.set_logical_clock(api, STARTUP_CLOCK_UTC)
    project = fixtures.open_project(api)
    assert project["version"] == 1

    first_model = fixtures.register_geologic_model(
        api, project["id"], project["version"], model_label="M1-DET"
    )
    after_first = fixtures.refresh_project(api, project["id"], program_admin_headers)
    assert after_first["version"] == 2

    response = api.create_geologic_model(
        factories.create_geologic_model_payload(
            project["id"],
            after_first["version"],
            model_label="M2-PROB",
            assessment_variant="PROBABILISTIC_P10",
        ),
        project_developer_headers,
    )

    second_model = validate_success(response, 201)
    assert second_model["version"] == 1
    assert second_model["assessment_variant"] == "PROBABILISTIC_P10"
    assert second_model["plume_status"] == "NOT_RUN"

    after_second = fixtures.refresh_project(api, project["id"], program_admin_headers)
    assert after_second["version"] == 3

    stored_first = fixtures.refresh_model(api, first_model["id"])
    assert stored_first["version"] == 1

    stored_second = fixtures.refresh_model(api, second_model["id"])
    assert stored_second["version"] == 1
    assert stored_second["assessment_variant"] == "PROBABILISTIC_P10"
    assert stored_second["plume_status"] == "NOT_RUN"


def test_finalize_aor_cascade_is_visible_in_the_response_and_the_next_read(
    api, program_admin_headers, project_developer_headers
):
    """The first link copies the model's computed `aor_radius_km` onto the project's `aor_radius_km`, publishing the delineation.

    The second link re-screens legacy wellbores: because the project's area of review has changed, every legacy wellbore of the project whose `corrective_action_status` is `OUT_OF_AOR` and whose `distance_from_injector_km` is less than or equal to the project's new `aor_radius_km` moves `OUT_OF_AOR → IDENTIFIED`, and every wellbore now inside the area of review has its `risk_score` and `ca_cost_estimate_usd` recomputed against the new radius.

    Immediately afterwards, each wellbore that has just reached `IDENTIFIED` and either has `penetrates_seal` true or carries a `risk_score` of at least 40.00 auto-advances `IDENTIFIED → CA_REQUIRED` in the same request — a wellbore that penetrates the confining zone is always obligated regardless of its score, and a wellbore that does not penetrate the seal is obligated only once its score reaches the 40.00 threshold.

    The third link recomputes the project's `corrective_action_completion_pct` and `required_financial_assurance_usd`, because the population of obligated wellbores has changed.

    Finally the model's `plume_status` moves `SIMULATED → AOR_FINALIZED`, and both the model's `version` and the project's `version` increment by one.

    When the project's `aor_radius_km` is 0, or when the wellbore's `distance_from_injector_km` exceeds the project's `aor_radius_km`, the wellbore begins at `OUT_OF_AOR` and waits for a future delineation to pull it in.

    The `risk_score` is 100.0 multiplied by the seal factor, multiplied by the plug factor, multiplied by the record factor, multiplied by the quantity 0.40 plus 0.60 times the proximity factor, rounded half up to 2 decimal places — so 40 percent of the score is fixed by the wellbore's own condition and 60 percent is modulated by how close it sits to the injector.

    The `ca_cost_estimate_usd` is a base mobilisation cost of 150,000.00 dollars, plus 120.00 dollars for every metre of `total_depth_m`, plus 2,000.00 dollars for every point of `risk_score`, with the total rounded half up to 2 decimal places.

    The project's `required_financial_assurance_usd` is the sum of those five already-rounded buckets, itself rounded half up to 2 decimal places.

    A project with nothing allocated therefore reads `UNFUNDED` even when its requirement happens to be zero.

    Design: Corner/consistency_model/finalize_aor_effects_are_visible_in_the_same_response_and_the_next_read
    """
    ctx = fixtures.setup_project_with_accepted_model(api)
    wellbore = fixtures.register_wellbore(
        api,
        ctx["project"]["id"],
        "15-001-00021",
        **WELLBORE_SEAL_OPEN_HOLE_DEEP_NEAR,
    )
    assert wellbore["corrective_action_status"] == "OUT_OF_AOR"
    assert wellbore["risk_score"] == 52.00

    model = validate_success(
        api.finalize_aor(ctx["model"]["id"], {}, project_developer_headers), 200
    )
    assert model["plume_status"] == "AOR_FINALIZED"
    assert model["aor_radius_km"] == 3.0

    project = validate_success(
        api.get_storage_project(ctx["project"]["id"], program_admin_headers), 200
    )
    assert project["aor_radius_km"] == 3.0
    assert project["required_financial_assurance_usd"] == 25259166.94
    assert project["corrective_action_completion_pct"] == 0.00
    assert project["assurance_coverage_status"] == "UNFUNDED"

    screened = validate_success(
        api.get_legacy_wellbore(wellbore["id"], project_developer_headers), 200
    )
    assert screened["corrective_action_status"] == "CA_REQUIRED"
    assert screened["risk_score"] == 92.00
    assert screened["ca_cost_estimate_usd"] == 622000.00


def test_added_atmospheric_method_visible_in_plan_listing_on_the_next_request(
    api, project_developer_headers
):
    """The `method_score` is the product of those three terms, rounded half up to 4 decimal places.

    Each domain subscore is the sum of the `method_score` values of that domain's methods whose `status` is `ACTIVE`, capped at 1.0000 and rounded half up to 4 decimal places — so `subsurface_subscore`, `surface_subscore` and `atmospheric_subscore` each saturate, and piling a fourth seismic survey onto an already-saturated subsurface domain adds nothing.

    The plan's `coverage_score` is 100.0 multiplied by the weighted sum of the three subscores, where `subsurface_subscore` carries a weight of 0.50, `surface_subscore` a weight of 0.30 and `atmospheric_subscore` a weight of 0.20, rounded half up to 2 decimal places.

    Adding a method computes that method's `method_score`, recomputes all three subscores and the plan's `coverage_score`, and bumps the plan's `version`.

    A new method rests at `status` `ACTIVE`.

    Every filter is optional, combinable, and applied before pagination so that `total_count` reflects the filtered population.

    Design: Corner/consistency_model/new_monitoring_method_is_visible_in_the_parent_listing_on_the_next_request
    """
    fixtures.set_logical_clock(api, STARTUP_CLOCK_UTC)
    project = fixtures.open_project(api)
    plan, _ = fixtures.create_monitoring_plan_with_methods(
        api,
        project["id"],
        methods=MRV_METHODS_SCORE_70_FREE_TEXT[:2],
        plan_label="MRV-1",
    )

    before = validate_success(
        api.get_monitoring_plan(plan["id"], project_developer_headers), 200
    )
    assert before["coverage_score"] == 65.00
    assert before["atmospheric_subscore"] == 0.0000

    response = api.add_monitoring_method(
        plan["id"],
        factories.create_monitoring_method_payload(**MRV_METHODS_SCORE_70_FREE_TEXT[2]),
        project_developer_headers,
    )
    atmospheric_method = validate_success(response, 201)
    assert atmospheric_method["method_score"] == 0.2500

    listed, meta = validate_paginated(
        api.list_monitoring_methods(
            plan["id"],
            project_developer_headers,
            params={
                "domain": "ATMOSPHERIC",
                "status": "ACTIVE",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert meta["total_count"] == 1
    assert [method["id"] for method in listed] == [atmospheric_method["id"]]
    assert listed[0]["status"] == "ACTIVE"

    after = validate_success(
        api.get_monitoring_plan(plan["id"], project_developer_headers), 200
    )
    assert after["coverage_score"] == 70.00
    assert after["atmospheric_subscore"] == 0.2500
    assert after["status"] == "DRAFT"
