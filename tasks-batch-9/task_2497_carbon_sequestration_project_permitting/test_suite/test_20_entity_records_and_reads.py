"""Entity records of the storage-permitting file: what a create persists, what a
read of a project reports, and how a project's child collections page.

Each test registers one artefact of the permitting file — a geologic model
revision, a project file, a legacy wellbore, a pore-space tract, a Class VI
permit application, a monitoring method or a tax credit claim — and checks the
record the server keeps for it: the fields the developer supplied, the fields the
server owns, and the derived numbers the server refuses to take from the client.
"""

import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId, assertions, constants, factories, fixtures


def test_register_geologic_model_persists_subsurface_parameters(
    api, project_developer_headers
):
    """A new model rests at `status` `DRAFT` with `plume_status` `NOT_RUN` and
    `revision_round_count` at 0; the create bumps the parent project's `version` by one.
    An optional `assessment_variant` nominates which parameter set governs the model's
    classification and is one of `DETERMINISTIC` or `PROBABILISTIC_P10`, defaulting to
    `DETERMINISTIC`. `version` is an integer that starts at 1 on creation and increments
    by exactly 1 on every mutation of that resource — including mutations that arrive as
    a cascade from a sibling or parent operation rather than as a direct request against
    the resource. Status codes follow one rule throughout: an operation that brings a new
    resource into existence responds with 201 Created, and every other successful
    operation — including every action endpoint that advances a state machine, every
    listing and every read — responds with 200 OK.

    Design: Corner/entities/create_geologic_model_persists_input_fields_and_returns_201
    """
    fixtures.set_logical_clock(api, constants.STARTUP_CLOCK_UTC)
    project = fixtures.open_project(api)
    assert project["version"] == 1

    response = api.create_geologic_model(
        factories.create_geologic_model_payload(project["id"], project["version"]),
        project_developer_headers,
    )
    model = validate_success(response, 201)

    assert model["version"] == 1
    assert model["project_id"] == project["id"]
    assert model["model_label"] == "M1-DET"
    assert model["seal_thickness_m"] == 60
    assert model["p10_capillary_entry_pressure_psi"] == 700
    assert model["porosity_fraction"] == 0.20
    assert model["assessment_variant"] == "DETERMINISTIC"
    assert model["status"] == "DRAFT"
    assert model["plume_status"] == "NOT_RUN"
    assert model["revision_round_count"] == 0

    stored_model = fixtures.refresh_model(api, model["id"])
    assert stored_model["model_label"] == "M1-DET"
    assert stored_model["status"] == "DRAFT"
    assert stored_model["plume_status"] == "NOT_RUN"
    assert stored_model["revision_round_count"] == 0

    assert fixtures.refresh_project(api, project["id"])["version"] == 2


def test_read_storage_project_reports_governing_model_and_assurance_requirement(
    api, program_admin_headers
):
    """When a single storage project is read, the server recomputes its derived fields
    against the current logical clock before responding — in particular
    `pisc_elapsed_years`, which is a function of elapsed logical time and therefore
    changes without any write having occurred. The project's
    `governing_geologic_model_id` is set to the newly accepted model. The project's
    `status` advances `SITE_CHARACTERIZATION → PERMITTING`. The post-injection site care
    bucket is the project's `pisc_duration_years` multiplied by its
    `effective_annual_monitoring_cost_usd`, rounded half up to 2 decimal places — fifty
    years of monitoring at the uplifted rate is by far the largest line item on most
    projects. The emergency reserve bucket is the larger of a two-million-dollar floor
    and the area-based figure obtained by multiplying 500,000.00 dollars per square
    kilometre by pi and by the square of the project's `aor_radius_km`, that area-based
    figure being rounded half up to 2 decimal places before the comparison. The
    administrative fee is tiered on the governing model's
    `effective_annual_injection_rate_tpy`: it is 250,000.00 dollars when that rate is at
    most 500,000 tonnes per year, 500,000.00 dollars when the rate exceeds 500,000 but is
    at most 1,500,000 tonnes per year, and 900,000.00 dollars when the rate exceeds
    1,500,000 tonnes per year. The project's `required_financial_assurance_usd` is the
    sum of those five already-rounded buckets, itself rounded half up to 2 decimal
    places. Until this delineation has happened for some accepted model, the project's
    `aor_radius_km` remains 0, and every operation that depends on a delineated area of
    review is refused with `ERR_AOR_NOT_DELINEATED` (HTTP 422).

    Design: Corner/entities/get_storage_project_returns_persisted_and_derived_values
    """
    ctx = fixtures.setup_project_with_accepted_model(api)

    response = api.get_storage_project(ctx["project"]["id"], program_admin_headers)
    project = validate_success(response, 200)
    assertions.assert_storage_project(project)

    assert project["status"] == "PERMITTING"
    assert project["governing_geologic_model_id"] == ctx["model"]["id"]
    assert project["required_financial_assurance_usd"] == 12500000.00
    assert project["effective_annual_monitoring_cost_usd"] == 200000.00
    assert project["name"] == "Alpha Storage Hub"
    assert project["basin_code"] == "ILB-01"
    assert project["aor_radius_km"] == 0


def test_list_project_legacy_wellbores_pages_the_screened_population(
    api, program_admin_headers
):
    """Every list endpoint accepts two optional query parameters, `limit` and `offset`.
    The `meta` object of a list response carries four pagination fields — `limit` and
    `offset` echoing the effective values applied, `total_count` giving the number of
    rows matching the filter before pagination, and `has_more` indicating whether rows
    remain beyond the returned window. The `response_type` is either "object" for a
    single resource or "array" for a list of resources.

    Design: Corner/entities/list_legacy_wellbores_paginates_with_limit_offset_and_total_count
    """
    fixtures.set_logical_clock(api, constants.STARTUP_CLOCK_UTC)
    project = fixtures.open_project(api)
    first = fixtures.register_wellbore(
        api, project["id"], "15-001-00001", **constants.WELLBORE_SEAL_OPEN_HOLE_NEAR
    )
    second = fixtures.register_wellbore(
        api, project["id"], "15-001-00002", **constants.WELLBORE_PARTIALLY_PLUGGED_MID
    )
    third = fixtures.register_wellbore(
        api, project["id"], "15-001-00003", **constants.WELLBORE_CEMENTED_DOCUMENTED_FAR
    )

    first_page_response = api.list_project_legacy_wellbores(
        project["id"], program_admin_headers, params={"limit": 2, "offset": 0}
    )
    first_page, first_meta = validate_paginated(first_page_response)
    assert first_page_response.json()["response_type"] == "array"
    assert len(first_page) == 2
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True

    second_page_response = api.list_project_legacy_wellbores(
        project["id"], program_admin_headers, params={"limit": 2, "offset": 2}
    )
    second_page, second_meta = validate_paginated(second_page_response)
    assert second_page_response.json()["response_type"] == "array"
    assert len(second_page) == 1
    assert second_meta["limit"] == 2
    assert second_meta["offset"] == 2
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False

    paged_ids = [row["id"] for row in first_page] + [row["id"] for row in second_page]
    assert len(set(paged_ids)) == 3
    assert set(paged_ids) == {first["id"], second["id"], third["id"]}


def test_read_geologic_model_unknown_id_returns_geologic_model_not_found(
    api, project_developer_headers
):
    """A missing storage project yields `ERR_PROJECT_NOT_FOUND`; a missing geologic model
    yields `ERR_GEOLOGIC_MODEL_NOT_FOUND`; a missing legacy wellbore yields
    `ERR_WELLBORE_NOT_FOUND`; a missing pore space tract yields `ERR_TRACT_NOT_FOUND`; a
    missing injection well permit yields `ERR_PERMIT_NOT_FOUND`; a missing monitoring plan
    yields `ERR_MONITORING_PLAN_NOT_FOUND` (this also guards the plan reference carried in
    a claim-creation body); a missing monitoring method yields
    `ERR_MONITORING_METHOD_NOT_FOUND` on retirement; a missing financial instrument yields
    `ERR_INSTRUMENT_NOT_FOUND`; a missing injection period record yields
    `ERR_INJECTION_PERIOD_NOT_FOUND` on a void; a missing tax credit claim yields
    `ERR_CLAIM_NOT_FOUND`; and a missing remediation order yields
    `ERR_REMEDIATION_ORDER_NOT_FOUND` on a resolve.

    Design: Corner/entities/get_geologic_model_unknown_id_not_found
    """
    fixtures.set_logical_clock(api, constants.STARTUP_CLOCK_UTC)
    project = fixtures.open_project(api)
    model = fixtures.register_geologic_model(api, project["id"], project["version"])

    response = api.get_geologic_model(
        constants.MISSING_GEOLOGIC_MODEL_ID, project_developer_headers
    )
    validate_error(response, ApiErrorId.ERR_GEOLOGIC_MODEL_NOT_FOUND.value, 404)

    assert fixtures.refresh_model(api, model["id"])["status"] == "DRAFT"
    assert fixtures.refresh_project(api, project["id"])["status"] == "DRAFT"


def test_open_storage_project_without_operator_name_rejected(
    api, program_admin_headers
):
    """Creation captures the project `name` (non-empty, at most 200 characters), the
    `operator_name` of the legal operator of record (non-empty), the `basin_code`
    identifying the geologic basin (non-empty, at most 20 characters), the
    `total_project_acreage` of pore space inside the project boundary (strictly greater
    than zero), the developer's `requested_annual_injection_rate_tpy` in tonnes per year
    (strictly greater than zero), and the `annual_monitoring_cost_usd` that the
    financial-assurance calculation will use as its baseline (zero or greater).
    **Request shape.** Required body fields present, enum values inside their declared
    sets, numbers inside their declared ranges, timestamps parseable as ISO 8601, `limit`
    between 1 and 100, `offset` at least 0, and the conditional mechanical-integrity
    requirements (an `annulus_pressure_loss_psi` value is required when `test_type` is
    `ANNULUS_PRESSURE`, and an `anomaly_detected` value is required for the other two test
    types) — `ERR_INVALID_REQUEST`.

    Design: Corner/entities/create_storage_project_missing_required_operator_name_invalid_request
    """
    fixtures.set_logical_clock(api, constants.STARTUP_CLOCK_UTC)
    payload = factories.create_storage_project_payload()
    payload.pop("operator_name")

    response = api.create_storage_project(payload, program_admin_headers)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    rows, meta = validate_paginated(
        api.list_storage_projects(
            program_admin_headers, params={"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_open_storage_project_applies_statutory_defaults(api, program_admin_headers):
    """Two further parameters are optional and carry statutory defaults:
    `required_consent_pct`, the pore-space consent percentage a unitization ruling must
    meet, defaults to 60 and must be greater than 0 and at most 100; and `ca_rig_slots`,
    the number of workover rigs the project can run concurrently during overlapping
    corrective-action windows, defaults to 2 and must be at least 1. A newly created
    project is initialised into a well-defined resting state: `status` is `DRAFT`,
    `operational_posture` is `OPEN`, `unitization_status` is `NOT_FILED`, and
    `closure_status` is `NOT_REQUESTED`. Its `governing_geologic_model_id` is null
    because no model has yet been accepted, its `aor_radius_km` is 0 because no area of
    review has been delineated, its `secured_acreage` is 0 and its `outstanding_acreage`
    therefore equals the whole `total_project_acreage`, its `pore_space_consent_pct` and
    `pore_space_bonus_total_usd` are 0, its `corrective_action_completion_pct` is 100 (an
    empty obligation set is vacuously complete), its `cumulative_stored_tonnes` and
    `pending_credit_usd` are 0, its `required_financial_assurance_usd` and
    `allocated_assurance_usd` are 0 with `assurance_coverage_status` at `UNFUNDED`, its
    `effective_annual_monitoring_cost_usd` equals the supplied
    `annual_monitoring_cost_usd`, its `pisc_duration_years` is 50, its
    `open_remediation_count` is 0, and `unitization_consent_pct_at_filing`,
    `statutory_bonus_per_acre_usd`, `alternative_timeframe_years`, `pisc_start_at`,
    `closure_certified_by_user_id` and `closure_certified_at` are all null with
    `non_endangerment_demonstrated` false and `pisc_elapsed_years` at 0.

    Design: Corner/entities/create_storage_project_omitted_optionals_apply_declared_defaults
    """
    fixtures.set_logical_clock(api, constants.STARTUP_CLOCK_UTC)

    response = api.create_storage_project(
        dict(constants.BRAVO_PROJECT_MINIMAL), program_admin_headers
    )
    project = validate_success(response, 201)
    assertions.assert_storage_project(project)

    assert project["required_consent_pct"] == 60
    assert project["ca_rig_slots"] == 2
    assert project["pisc_duration_years"] == 50

    stored = fixtures.refresh_project(api, project["id"])
    assert stored["status"] == "DRAFT"
    assert stored["operational_posture"] == "OPEN"
    assert stored["unitization_status"] == "NOT_FILED"
    assert stored["closure_status"] == "NOT_REQUESTED"
    assert stored["outstanding_acreage"] == 4000.0000
    assert stored["effective_annual_monitoring_cost_usd"] == 200000.00
    assert stored["corrective_action_completion_pct"] == 100.00
    assert stored["assurance_coverage_status"] == "UNFUNDED"


def test_draft_injection_well_permit_derives_its_pressure_ceiling(
    api, project_developer_headers
):
    """The body carries the `project_id`, the `geologic_model_id` of the model revision
    the application relies upon, a `well_name` (non-empty and unique among the permits of
    the same project), a `casing_program` drawn from `LONG_STRING_CEMENTED_TO_SURFACE`,
    `LINER` or `SINGLE_STRING`, a `corrosion_resistant_material` boolean declaring whether
    the tubing and long-string casing use carbon-dioxide-resistant material, the
    `requested_injection_pressure_psi` the developer wants as a maximum surface injection
    pressure (strictly positive), and an optional `tubing_packer_installed` boolean
    declaring whether injection is through tubing set on a packer, which defaults to
    false. Creation immediately derives the well's pressure ceiling:
    `max_injection_pressure_psi` is 90 percent of the referenced model's
    `fracture_pressure_psi`, rounded half up to 2 decimal places. The permit rests at
    `permit_status` `DRAFT` and `construction_status` `NOT_STARTED`, with
    `authorized_injection_rate_tpy` at 0, `revision_round_count` at 0, and
    `last_mit_type`, `last_mit_result`, `last_mit_at` and `activated_at` all null with
    `mit_pass_count` at 0.

    Design: Corner/entities/create_injection_well_permit_computes_max_injection_pressure_from_model
    """
    ctx = fixtures.setup_project_with_accepted_model(api)

    response = api.create_injection_well_permit(
        factories.create_injection_well_permit_payload(
            ctx["project"]["id"], ctx["model"]["id"]
        ),
        project_developer_headers,
    )
    permit = validate_success(response, 201)
    assertions.assert_injection_well_permit(permit)

    assert permit["max_injection_pressure_psi"] == 4050.00
    assert permit["authorized_injection_rate_tpy"] == 0

    stored = fixtures.refresh_permit(api, permit["id"])
    assert stored["permit_status"] == "DRAFT"
    assert stored["construction_status"] == "NOT_STARTED"
    assert stored["geologic_model_id"] == ctx["model"]["id"]


def test_register_pore_space_tract_rests_unleased_with_nothing_settled(
    api, project_developer_headers
):
    """A new tract rests at `lease_status` `UNLEASED` with `negotiation_round_count`,
    `bonus_settlement_usd` and `net_acreage` all at 0. `version` is an integer that
    starts at 1 on creation and increments by exactly 1 on every mutation of that
    resource — including mutations that arrive as a cascade from a sibling or parent
    operation rather than as a direct request against the resource. At project level the
    holders are the tracts whose `lease_status` is `EXECUTED` or `UNITIZED`, summed in
    `created_at` ascending order: `secured_acreage` is the sum of their `net_acreage`
    values rounded half up to 4 decimal places, `outstanding_acreage` is
    `total_project_acreage` less `secured_acreage` rounded half up to 4 decimal places,
    `pore_space_consent_pct` is 100.0 multiplied by `secured_acreage` divided by
    `total_project_acreage` rounded half up to 2 decimal places, and
    `pore_space_bonus_total_usd` is the sum of the holders' already-rounded
    `bonus_settlement_usd` values rounded half up to 2 decimal places.

    Design: Corner/entities/create_pore_space_tract_initialises_system_fields
    """
    fixtures.set_logical_clock(api, constants.STARTUP_CLOCK_UTC)
    project = fixtures.open_project(api)

    response = api.create_pore_space_tract(
        factories.create_pore_space_tract_payload(project["id"], "T1"),
        project_developer_headers,
    )
    tract = validate_success(response, 201)
    assertions.assert_pore_space_tract(tract)

    assert tract["lease_status"] == "UNLEASED"
    assert tract["negotiation_round_count"] == 0
    assert tract["version"] == 1

    stored = fixtures.refresh_tract(api, tract["id"])
    assert stored["bonus_settlement_usd"] == 0
    assert stored["net_acreage"] == 0

    assert fixtures.refresh_project(api, project["id"])["secured_acreage"] == 0


def test_register_legacy_wellbore_with_out_of_set_plug_condition_rejected(
    api, project_developer_headers
):
    """Legacy wellbores are the pre-existing penetrations that could turn a competent
    seal into a leak path, and the developer registers each one with its `project_id`,
    its regulatory `api_number` (non-empty and unique among the wellbores of the same
    project), its `distance_from_injector_km` from the proposed injector (zero or
    greater), its `total_depth_m` in metres (strictly positive), a `penetrates_seal`
    boolean recording whether it crosses the confining zone, a `plug_condition` drawn
    from `CEMENTED`, `PARTIALLY_PLUGGED`, `OPEN_HOLE` or `UNKNOWN`, and a
    `plug_record_available` boolean recording whether the state archive holds a plugging
    record. **Request shape.** Required body fields present, enum values inside their
    declared sets, numbers inside their declared ranges, timestamps parseable as ISO
    8601, `limit` between 1 and 100, `offset` at least 0, and the conditional
    mechanical-integrity requirements (an `annulus_pressure_loss_psi` value is required
    when `test_type` is `ANNULUS_PRESSURE`, and an `anomaly_detected` value is required
    for the other two test types) — `ERR_INVALID_REQUEST`. When the obligated set is
    empty, `corrective_action_completion_pct` is exactly 100.00.

    Design: Corner/entities/create_legacy_wellbore_invalid_enum_plug_condition_invalid_request
    """
    fixtures.set_logical_clock(api, constants.STARTUP_CLOCK_UTC)
    project = fixtures.open_project(api)

    payload = factories.create_legacy_wellbore_payload(
        project["id"],
        "15-001-00009",
        distance_from_injector_km=1.0,
        total_depth_m=1500,
        penetrates_seal=False,
        plug_condition="GROUTED",
        plug_record_available=True,
    )
    response = api.create_legacy_wellbore(payload, project_developer_headers)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    rows, meta = validate_paginated(
        api.list_project_legacy_wellbores(
            project["id"], project_developer_headers, params={"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 0
    assert len(rows) == 0

    project_after = fixtures.refresh_project(api, project["id"])
    assert project_after["corrective_action_completion_pct"] == 100.00


def test_register_legacy_wellbore_scores_the_wellbore_itself(
    api, project_developer_headers
):
    """Clients never post a derived value; they post facts, and the server reconciles.
    Registration scores the wellbore immediately, against whatever `aor_radius_km` the
    project currently holds. The seal factor is 1.0 when `penetrates_seal` is true and
    0.85 when it is false. The plug factor is 1.00 for `OPEN_HOLE`, 0.70 for
    `PARTIALLY_PLUGGED`, 0.85 for `UNKNOWN` and 0.25 for `CEMENTED` — an uncemented open
    hole is the worst case and a properly cemented well the best. The record factor is
    0.60 when `plug_record_available` is true and 1.00 when it is false, so an
    undocumented well is penalised. The proximity factor is 0.20 flat whenever the
    project's `aor_radius_km` is zero or below, because an undelineated area of review
    carries no meaningful proximity signal; otherwise it is one minus the ratio of
    `distance_from_injector_km` to the project's `aor_radius_km`, clamped so that it is
    never above 1.00 and never below 0.20. The `risk_score` is 100.0 multiplied by the
    seal factor, multiplied by the plug factor, multiplied by the record factor,
    multiplied by the quantity 0.40 plus 0.60 times the proximity factor, rounded half up
    to 2 decimal places — so 40 percent of the score is fixed by the wellbore's own
    condition and 60 percent is modulated by how close it sits to the injector. The
    `ca_cost_estimate_usd` is a base mobilisation cost of 150,000.00 dollars, plus 120.00
    dollars for every metre of `total_depth_m`, plus 2,000.00 dollars for every point of
    `risk_score`, with the total rounded half up to 2 decimal places. When the project's
    `aor_radius_km` is 0, or when the wellbore's `distance_from_injector_km` exceeds the
    project's `aor_radius_km`, the wellbore begins at `OUT_OF_AOR` and waits for a future
    delineation to pull it in.

    Design: Corner/entities/create_legacy_wellbore_ignores_client_supplied_risk_score_input_ignored
    """
    fixtures.set_logical_clock(api, constants.STARTUP_CLOCK_UTC)
    project = fixtures.open_project(api)

    payload = factories.create_legacy_wellbore_payload(
        project["id"],
        "15-001-00007",
        risk_score=99.99,
        corrective_action_status="CA_WAIVED",
        **constants.WELLBORE_UNKNOWN_PLUG_MID,
    )
    response = api.create_legacy_wellbore(payload, project_developer_headers)
    wellbore = validate_success(response, 201)
    assertions.assert_legacy_wellbore(wellbore)

    assert wellbore["risk_score"] == pytest.approx(22.54, abs=0.01)
    assert wellbore["corrective_action_status"] == "OUT_OF_AOR"

    stored = fixtures.refresh_wellbore(api, wellbore["id"])
    assert stored["risk_score"] == pytest.approx(22.54, abs=0.01)
    assert stored["ca_cost_estimate_usd"] == pytest.approx(315080.00, abs=0.01)
    assert stored["corrective_action_status"] == "OUT_OF_AOR"

    project_after = fixtures.refresh_project(api, project["id"])
    assert project_after["corrective_action_completion_pct"] == 100.00


def test_add_monitoring_method_scores_only_its_own_plan(api, project_developer_headers):
    """Each method declares its `monitoring_plan_id` implicitly through the plan it is
    added to, a `domain` of `SUBSURFACE`, `SURFACE` or `ATMOSPHERIC`, a non-empty
    `technique` naming the measurement approach (for instance time-lapse seismic, soil
    flux or eddy covariance), a strictly positive `detection_threshold_tpy` giving the
    smallest annual leakage rate the method can detect in tonnes per year, a
    `frequency_per_year` of at least 1 campaign, and a `spatial_coverage_pct` greater
    than 0 and at most 100 recording the percentage of the area of review the method
    covers. A new method rests at `status` `ACTIVE`. The coverage term is
    `spatial_coverage_pct` divided by 100.0, capped at 1.00. The frequency term is
    `frequency_per_year` divided by the reference campaign count for the method's own
    domain, capped at 1.00; the reference is 2 campaigns per year for `SUBSURFACE`, 4 for
    `SURFACE` and 12 for `ATMOSPHERIC`, reflecting how much more often a cheap surface or
    atmospheric measurement is expected to be repeated. The detection term is the
    reference detection threshold for the method's domain divided by the method's own
    `detection_threshold_tpy`, capped at 1.00; the reference is 1000.0 tonnes per year
    for `SUBSURFACE`, 100.0 for `SURFACE` and 25.0 for `ATMOSPHERIC`, so a method
    claiming better sensitivity than its domain reference earns the full term while a
    less sensitive method is scaled down proportionally. The `method_score` is the product
    of those three terms, rounded half up to 4 decimal places. Each domain subscore is
    the sum of the `method_score` values of that domain's methods whose `status` is
    `ACTIVE`, capped at 1.0000 and rounded half up to 4 decimal places — so
    `subsurface_subscore`, `surface_subscore` and `atmospheric_subscore` each saturate,
    and piling a fourth seismic survey onto an already-saturated subsurface domain adds
    nothing. The plan's `coverage_score` is 100.0 multiplied by the weighted sum of the
    three subscores, where `subsurface_subscore` carries a weight of 0.50,
    `surface_subscore` a weight of 0.30 and `atmospheric_subscore` a weight of 0.20,
    rounded half up to 2 decimal places. A monitoring, reporting and verification plan is
    created by the developer against a `project_id` with a `plan_label`, and it rests at
    `status` `DRAFT` with `technical_review_complete` and `public_comment_complete` both
    false, all three domain subscores at 0, `coverage_score` at 0, `condition_count` at
    0, `approved_by_user_id` null and `revision_round_count` at 0.

    Design: Corner/entities/create_monitoring_method_nested_under_parent_plan
    """
    fixtures.set_logical_clock(api, constants.STARTUP_CLOCK_UTC)
    project = fixtures.open_project(api)
    receiving_plan, _ = fixtures.create_monitoring_plan_with_methods(
        api, project["id"], methods=[], plan_label="MRV-1"
    )
    sibling_plan, _ = fixtures.create_monitoring_plan_with_methods(
        api, project["id"], methods=[], plan_label="MRV-2"
    )

    response = api.add_monitoring_method(
        receiving_plan["id"],
        factories.create_monitoring_method_payload(**constants.MRV_METHODS_SCORE_85[0]),
        project_developer_headers,
    )
    method = validate_success(response, 201)
    assertions.assert_monitoring_method(method)

    assert method["monitoring_plan_id"] == receiving_plan["id"]
    assert method["method_score"] == 1.0000
    assert method["status"] == "ACTIVE"

    own_rows, own_meta = validate_paginated(
        api.list_monitoring_methods(
            receiving_plan["id"],
            project_developer_headers,
            params={"limit": 10, "offset": 0},
        )
    )
    assert own_meta["total_count"] == 1
    assert [row["id"] for row in own_rows] == [method["id"]]

    _, sibling_meta = validate_paginated(
        api.list_monitoring_methods(
            sibling_plan["id"],
            project_developer_headers,
            params={"limit": 10, "offset": 0},
        )
    )
    assert sibling_meta["total_count"] == 0

    receiving_stored = fixtures.refresh_plan(api, receiving_plan["id"])
    assertions.assert_monitoring_plan(receiving_stored)
    assert receiving_stored["subsurface_subscore"] == 1.0000
    assert receiving_stored["coverage_score"] == 50.00

    assert fixtures.refresh_plan(api, sibling_plan["id"])["coverage_score"] == 0.00


def test_open_tax_credit_claim_against_another_projects_plan_rejected(
    api, project_developer_headers
):
    """**Foreign-key coherence.** When a permit application, a tax credit claim or a
    geologic model is created, the geologic model or monitoring plan it names must belong
    to the same project named in the body. A cross-project reference is reported as
    `ERR_PROJECT_NOT_FOUND` (HTTP 404), not as a validation error. The named plan must
    belong to the named project.

    Design: Corner/entities/create_tax_credit_claim_with_foreign_project_monitoring_plan_rejected
    """
    fixtures.set_logical_clock(api, constants.STARTUP_CLOCK_UTC)
    alpha_project = fixtures.open_project(api)
    alpha_plan, _ = fixtures.create_monitoring_plan_with_methods(
        api, alpha_project["id"], methods=[], plan_label="MRV-A"
    )
    bravo_project = fixtures.open_project(
        api,
        name="Bravo Storage Hub",
        operator_name="Bravo CCS LLC",
        basin_code="ILB-02",
        total_project_acreage=2000,
        requested_annual_injection_rate_tpy=400000,
        annual_monitoring_cost_usd=100000,
    )

    response = api.create_tax_credit_claim(
        factories.create_tax_credit_claim_payload(
            bravo_project["id"],
            alpha_plan["id"],
            tax_year=2027,
            claim_variant="REPORTED",
            lca_upstream_emissions_factor=0.05,
        ),
        project_developer_headers,
    )
    validate_error(response, ApiErrorId.ERR_PROJECT_NOT_FOUND.value, 404)

    _, meta = validate_paginated(
        api.list_tax_credit_claims(
            project_developer_headers,
            params={"project_id": bravo_project["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 0

    assert fixtures.refresh_plan(api, alpha_plan["id"])["project_id"] == (
        alpha_project["id"]
    )
