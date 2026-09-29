"""Behaviour exactly on the numeric thresholds the permitting rules name.

A monitoring plan scoring precisely the minimum coverage, an annulus pressure
test losing precisely the maximum tolerated pressure, and a project whose
obligated corrective-action set is precisely empty are each sitting on a stated
boundary. These tests pin the outcome at the boundary and, where the rule has a
reachable neighbour, immediately on the other side of it.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId, REVIEWER_USER_ID, constants, factories, fixtures


def test_review_plan_coverage_exactly_seventy_approves_with_conditions(
    api, regulatory_reviewer_headers
):
    """The plan's `coverage_score` is 100.0 multiplied by the weighted sum of the
    three subscores, where `subsurface_subscore` carries a weight of 0.50,
    `surface_subscore` a weight of 0.30 and `atmospheric_subscore` a weight of
    0.20, rounded half up to 2 decimal places.

    Then the plan's `coverage_score` must be at least 70.00; below that it is
    refused with `ERR_MRV_COVERAGE_BELOW_MINIMUM` (HTTP 422).

    When `coverage_score` is at least 70.00 but below 85.00, the plan instead
    moves `REVIEW_COMPLETE → APPROVED_WITH_CONDITIONS`. Its `condition_count` is
    set to the `condition_count` supplied in the request body, the reviewer's
    `X-User-ID` is recorded in `approved_by_user_id`, and the project's
    `effective_annual_monitoring_cost_usd` is set to its
    `annual_monitoring_cost_usd` multiplied by 1.15 — a 15 percent uplift
    representing the extra surveillance the conditions impose — rounded half up
    to 2 decimal places.

    Design: Difficulty/boundary_precision_check/mrv_coverage_exactly_seventy_approves_with_conditions
    """
    fixtures.set_logical_clock(api)
    project = fixtures.open_project(api)
    plan, _methods = fixtures.create_monitoring_plan_with_methods(
        api, project["id"], methods=constants.MRV_METHODS_SCORE_70
    )
    submitted = fixtures.submit_plan(api, plan["id"])
    assert submitted["coverage_score"] == 70.00
    assert submitted["subsurface_subscore"] == 1.0000
    assert submitted["surface_subscore"] == 0.5000
    assert submitted["atmospheric_subscore"] == 0.2500
    fixtures.close_both_review_tracks(api, plan["id"])

    response = api.review_monitoring_plan(
        plan["id"],
        {
            "decision": "APPROVE",
            "condition_count": 3,
            "review_note": "approved subject to three conditions",
        },
        regulatory_reviewer_headers,
    )
    ruled = validate_success(response, 200)
    assert ruled["status"] == "APPROVED_WITH_CONDITIONS"
    assert ruled["condition_count"] == 3
    assert ruled["approved_by_user_id"] == REVIEWER_USER_ID

    plan_after = fixtures.refresh_plan(api, plan["id"])
    assert plan_after["coverage_score"] == 70.00
    assert plan_after["subsurface_subscore"] == 1.0000
    assert plan_after["surface_subscore"] == 0.5000
    assert plan_after["atmospheric_subscore"] == 0.2500
    assert plan_after["status"] == "APPROVED_WITH_CONDITIONS"
    assert plan_after["condition_count"] == 3


def test_conditioned_approval_at_minimum_coverage_uplifts_monitoring_cost(
    api, regulatory_reviewer_headers
):
    """When `coverage_score` is at least 70.00 but below 85.00, the plan instead
    moves `REVIEW_COMPLETE → APPROVED_WITH_CONDITIONS`. Its `condition_count` is
    set to the `condition_count` supplied in the request body, the reviewer's
    `X-User-ID` is recorded in `approved_by_user_id`, and the project's
    `effective_annual_monitoring_cost_usd` is set to its
    `annual_monitoring_cost_usd` multiplied by 1.15 — a 15 percent uplift
    representing the extra surveillance the conditions impose — rounded half up
    to 2 decimal places.

    The uplift persists on the project for as long as any of its plans holds
    `status` `APPROVED_WITH_CONDITIONS`.

    Design: Difficulty/boundary_precision_check/mrv_coverage_exactly_seventy_approves_with_conditions
    """
    fixtures.set_logical_clock(api)
    project = fixtures.open_project(api)
    assert project["annual_monitoring_cost_usd"] == 200000

    plan, _methods = fixtures.create_monitoring_plan_with_methods(
        api, project["id"], methods=constants.MRV_METHODS_SCORE_70
    )
    submitted = fixtures.submit_plan(api, plan["id"])
    assert submitted["coverage_score"] == 70.00
    fixtures.close_both_review_tracks(api, plan["id"])

    project_before = fixtures.refresh_project(api, project["id"])
    assert project_before["annual_monitoring_cost_usd"] == 200000

    response = api.review_monitoring_plan(
        plan["id"],
        {
            "decision": "APPROVE",
            "condition_count": 3,
            "review_note": "approved subject to three conditions",
        },
        regulatory_reviewer_headers,
    )
    ruled = validate_success(response, 200)
    assert ruled["status"] == "APPROVED_WITH_CONDITIONS"

    project_after = fixtures.refresh_project(api, project["id"])
    assert project_after["effective_annual_monitoring_cost_usd"] == 230000.00

    # The uplift is not transient: it still reads back on a later fetch while the
    # plan continues to hold APPROVED_WITH_CONDITIONS.
    project_reread = fixtures.refresh_project(api, project["id"])
    assert project_reread["effective_annual_monitoring_cost_usd"] == 230000.00
    assert fixtures.refresh_plan(api, plan["id"])["status"] == "APPROVED_WITH_CONDITIONS"


def test_record_mit_annulus_loss_just_above_three_psi_fails_and_blocks_completion(
    api, project_developer_headers
):
    """An annulus pressure test must carry an `annulus_pressure_loss_psi` value
    and produces a `PASS` verdict when that loss is at most 3.00 psi and a `FAIL`
    verdict when it exceeds 3.00 psi — a loss of exactly 3.00 psi is a `PASS`, and
    the comparison is made on the submitted value at 2 decimal places.

    Recording a test writes `last_mit_type` from the submitted `test_type`, writes
    the verdict to `last_mit_result`, stamps `last_mit_at` with the logical clock,
    and increases `mit_pass_count` by one when and only when the verdict was
    `PASS`.

    The last step, into `COMPLETED`, requires that the permit's `last_mit_result`
    be `PASS`; attempting it without a passing test is refused with
    `ERR_MIT_NOT_PASSED` (HTTP 409).

    Design: Difficulty/boundary_precision_check/mit_annulus_loss_exactly_three_psi_passes
    """
    ctx = fixtures.setup_project_with_finalized_aor(api)
    permit = fixtures.create_permit(api, ctx["project"]["id"], ctx["model"]["id"])
    permit = fixtures.approve_permit(api, permit["id"])
    fixtures.advance_construction_through(
        api, permit["id"], fixtures.CONSTRUCTION_SEQUENCE[:4]
    )

    response = api.record_mit(
        permit["id"],
        factories.record_mit_payload(annulus_pressure_loss_psi=3.01),
        project_developer_headers,
    )
    recorded = validate_success(response, 200)
    assert recorded["last_mit_type"] == "ANNULUS_PRESSURE"
    assert recorded["last_mit_result"] == "FAIL"
    assert recorded["mit_pass_count"] == 0

    refused = api.advance_construction(
        permit["id"],
        factories.advance_construction_payload("COMPLETED"),
        project_developer_headers,
    )
    validate_error(refused, ApiErrorId.ERR_MIT_NOT_PASSED.value, 409)

    permit_after = fixtures.refresh_permit(api, permit["id"])
    assert permit_after["construction_status"] == "MIT_PENDING"
    assert permit_after["last_mit_result"] == "FAIL"
    assert permit_after["mit_pass_count"] == 0


def test_record_mit_annulus_loss_exactly_three_psi_passes_and_allows_completion(
    api, project_developer_headers
):
    """An annulus pressure test must carry an `annulus_pressure_loss_psi` value
    and produces a `PASS` verdict when that loss is at most 3.00 psi and a `FAIL`
    verdict when it exceeds 3.00 psi — a loss of exactly 3.00 psi is a `PASS`, and
    the comparison is made on the submitted value at 2 decimal places.

    Recording a test writes `last_mit_type` from the submitted `test_type`, writes
    the verdict to `last_mit_result`, stamps `last_mit_at` with the logical clock,
    and increases `mit_pass_count` by one when and only when the verdict was
    `PASS`.

    The last step, into `COMPLETED`, requires that the permit's `last_mit_result`
    be `PASS`; attempting it without a passing test is refused with
    `ERR_MIT_NOT_PASSED` (HTTP 409).

    Design: Difficulty/boundary_precision_check/mit_annulus_loss_exactly_three_psi_passes
    """
    ctx = fixtures.setup_project_with_finalized_aor(api)
    permit = fixtures.create_permit(api, ctx["project"]["id"], ctx["model"]["id"])
    permit = fixtures.approve_permit(api, permit["id"])
    assert permit["permit_status"] == "APPROVED"
    fixtures.advance_construction_through(
        api, permit["id"], fixtures.CONSTRUCTION_SEQUENCE[:4]
    )

    response = api.record_mit(
        permit["id"],
        factories.record_mit_payload(annulus_pressure_loss_psi=3.00),
        project_developer_headers,
    )
    recorded = validate_success(response, 200)
    assert recorded["last_mit_type"] == "ANNULUS_PRESSURE"
    assert recorded["last_mit_result"] == "PASS"
    assert recorded["mit_pass_count"] == 1
    assert recorded["last_mit_at"].startswith("2026-08-01T00:00:00")

    completed = validate_success(
        api.advance_construction(
            permit["id"],
            factories.advance_construction_payload("COMPLETED"),
            project_developer_headers,
        ),
        200,
    )
    assert completed["construction_status"] == "COMPLETED"

    permit_after = fixtures.refresh_permit(api, permit["id"])
    assert permit_after["last_mit_type"] == "ANNULUS_PRESSURE"
    assert permit_after["last_mit_result"] == "PASS"
    assert permit_after["mit_pass_count"] == 1
    assert permit_after["construction_status"] == "COMPLETED"
    assert permit_after["permit_status"] == "APPROVED"


def test_finalize_aor_rescreens_far_cemented_wellbore_into_identified(
    api, project_developer_headers
):
    """When the project's `aor_radius_km` is 0, or when the wellbore's
    `distance_from_injector_km` exceeds the project's `aor_radius_km`, the
    wellbore begins at `OUT_OF_AOR` and waits for a future delineation to pull it
    in.

    The second link re-screens legacy wellbores: because the project's area of
    review has changed, every legacy wellbore of the project whose
    `corrective_action_status` is `OUT_OF_AOR` and whose
    `distance_from_injector_km` is less than or equal to the project's new
    `aor_radius_km` moves `OUT_OF_AOR → IDENTIFIED`, and every wellbore now inside
    the area of review has its `risk_score` and `ca_cost_estimate_usd` recomputed
    against the new radius.

    The `risk_score` is 100.0 multiplied by the seal factor, multiplied by the
    plug factor, multiplied by the record factor, multiplied by the quantity 0.40
    plus 0.60 times the proximity factor, rounded half up to 2 decimal places — so
    40 percent of the score is fixed by the wellbore's own condition and 60 percent
    is modulated by how close it sits to the injector.

    The `ca_cost_estimate_usd` is a base mobilisation cost of 150,000.00 dollars,
    plus 120.00 dollars for every metre of `total_depth_m`, plus 2,000.00 dollars
    for every point of `risk_score`, with the total rounded half up to 2 decimal
    places.

    Design: Difficulty/boundary_precision_check/corrective_action_completion_one_hundred_on_empty_obligated_set
    """
    ctx = fixtures.setup_project_with_accepted_model(api)
    assert ctx["project"]["aor_radius_km"] == 0

    wellbore = fixtures.register_wellbore(
        api,
        ctx["project"]["id"],
        "15-001-00003",
        **constants.WELLBORE_CEMENTED_DOCUMENTED_FAR,
    )
    assert wellbore["corrective_action_status"] == "OUT_OF_AOR"

    response = api.finalize_aor(ctx["model"]["id"], {}, project_developer_headers)
    model = validate_success(response, 200)
    assert model["plume_status"] == "AOR_FINALIZED"

    wellbore_after = fixtures.refresh_wellbore(api, wellbore["id"])
    assert wellbore_after["corrective_action_status"] == "IDENTIFIED"
    assert wellbore_after["risk_score"] == 7.65
    assert wellbore_after["ca_cost_estimate_usd"] == 261300.00

    project_after = fixtures.refresh_project(api, ctx["project"]["id"])
    assert project_after["aor_radius_km"] == 3.0


def test_finalize_aor_leaves_completion_at_one_hundred_with_no_obligated_wellbore(
    api, project_developer_headers
):
    """Of the remaining in-area-of-review wellbores, those bearing `IDENTIFIED`
    are counted as in-scope for cost purposes but are not yet obligated; the
    obligated set is those whose status is `CA_REQUIRED`, `CA_SCHEDULED`,
    `CA_COMPLETE` or `CA_WAIVED`, and the closed set is the subset of those whose
    status is `CA_COMPLETE` or `CA_WAIVED`. When the obligated set is empty,
    `corrective_action_completion_pct` is exactly 100.00.

    The corrective-action bucket totals the `ca_cost_estimate_usd` of the
    project's wellbores whose `corrective_action_status` is `IDENTIFIED`,
    `CA_REQUIRED` or `CA_SCHEDULED` — work that is still outstanding — with the
    sum of those already-rounded per-wellbore figures rounded half up to 2 decimal
    places.

    The project's `required_financial_assurance_usd` is the sum of those five
    already-rounded buckets, itself rounded half up to 2 decimal places.

    A project with nothing allocated therefore reads `UNFUNDED` even when its
    requirement happens to be zero.

    Design: Difficulty/boundary_precision_check/corrective_action_completion_one_hundred_on_empty_obligated_set
    """
    ctx = fixtures.setup_project_with_accepted_model(api)
    wellbore = fixtures.register_wellbore(
        api,
        ctx["project"]["id"],
        "15-001-00003",
        **constants.WELLBORE_CEMENTED_DOCUMENTED_FAR,
    )
    assert wellbore["corrective_action_status"] == "OUT_OF_AOR"

    response = api.finalize_aor(ctx["model"]["id"], {}, project_developer_headers)
    model = validate_success(response, 200)
    assert model["plume_status"] == "AOR_FINALIZED"

    wellbore_after = fixtures.refresh_wellbore(api, wellbore["id"])
    assert wellbore_after["corrective_action_status"] == "IDENTIFIED"
    assert wellbore_after["ca_cost_estimate_usd"] == 261300.00

    project_after = fixtures.refresh_project(api, ctx["project"]["id"])
    assert project_after["corrective_action_completion_pct"] == 100.00
    assert project_after["required_financial_assurance_usd"] == 24898466.94
    assert project_after["assurance_coverage_status"] == "UNFUNDED"
    assert project_after["allocated_assurance_usd"] == 0
