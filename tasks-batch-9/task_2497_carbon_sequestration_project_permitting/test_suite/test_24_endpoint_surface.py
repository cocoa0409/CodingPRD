"""Endpoint surface of the permitting record: what a write leaves readable.

Each test here drives one published operation and then reads the result back
through the shape the regulator would use — the single-resource read, the
project-scoped sub-resource listing, or the filtered top-level listing — so the
values the server derived are checked where a client would actually see them.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import (
    LANDOWNER_1_USER_ID,
    LANDOWNER_2_USER_ID,
    ApiErrorId,
    constants,
    fixtures,
)


def test_pore_space_tract_readable_through_single_read_and_filtered_project_listing(
    api, project_developer_headers
):
    """A new tract rests at `lease_status` `UNLEASED` with `negotiation_round_count`, `bonus_settlement_usd` and `net_acreage` all at 0.
    A project's own sub-resource listings accept a filter on the child's state — `corrective_action_status` for legacy wellbores, `lease_status` for pore space tracts, and `status` for monitoring plans, financial instruments and remediation orders — alongside `limit` and `offset`.
    List results are ordered by `created_at` ascending unless a specific workflow states a different ordering for a specific computation.
    The `meta` object of a list response carries four pagination fields — `limit` and `offset` echoing the effective values applied, `total_count` giving the number of rows matching the filter before pagination, and `has_more` indicating whether rows remain beyond the returned window.

    Design: Corner/endpoints/pore_space_tract_create_read_and_filtered_list_round_trip
    """
    fixtures.set_logical_clock(api, constants.STARTUP_CLOCK_UTC)
    project = fixtures.open_project(api)
    first_tract = fixtures.register_tract(
        api,
        project["id"],
        "T1",
        acreage=1000,
        ownership_pct=100,
        landowner_user_id=LANDOWNER_1_USER_ID,
    )
    second_tract = fixtures.register_tract(
        api,
        project["id"],
        "T2",
        acreage=500,
        ownership_pct=100,
        landowner_user_id=LANDOWNER_2_USER_ID,
    )

    read = validate_success(
        api.get_pore_space_tract(first_tract["id"], project_developer_headers)
    )
    assert read["tract_label"] == "T1"
    assert read["acreage"] == 1000
    assert read["lease_status"] == "UNLEASED"

    rows, meta = validate_paginated(
        api.list_project_pore_space_tracts(
            project["id"],
            project_developer_headers,
            params={"lease_status": "UNLEASED", "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert [row["id"] for row in rows] == [first_tract["id"], second_tract["id"]]

    assert fixtures.refresh_tract(api, second_tract["id"])[
        "negotiation_round_count"
    ] == 0


def test_unitization_petition_snapshots_pore_space_consent_pct(
    api, project_developer_headers
):
    """At project level the holders are the tracts whose `lease_status` is `EXECUTED` or `UNITIZED`, summed in `created_at` ascending order: `secured_acreage` is the sum of their `net_acreage` values rounded half up to 4 decimal places, `outstanding_acreage` is `total_project_acreage` less `secured_acreage` rounded half up to 4 decimal places, `pore_space_consent_pct` is 100.0 multiplied by `secured_acreage` divided by `total_project_acreage` rounded half up to 2 decimal places, and `pore_space_bonus_total_usd` is the sum of the holders' already-rounded `bonus_settlement_usd` values rounded half up to 2 decimal places.
    The very first submission for a project also drives the project's own `status` from `DRAFT` to `SITE_CHARACTERIZATION`, bumping the project's `version` — a project that is already past `DRAFT` is left where it is.
    A petition is admissible only when the project's `unitization_status` is `NOT_FILED` and the project's `status` is `SITE_CHARACTERIZATION` or `PERMITTING`.
    Filing snapshots the project's current `pore_space_consent_pct` into `unitization_consent_pct_at_filing` — a permanent record of the consent level at the moment the developer went to the regulator — and moves `unitization_status` `NOT_FILED → FILED`, bumping the project's `version`.

    Design: Corner/endpoints/file_unitization_petition_snapshots_consent_pct
    """
    fixtures.set_logical_clock(api, constants.STARTUP_CLOCK_UTC)
    project = fixtures.open_project(api)
    tract = fixtures.register_tract(
        api,
        project["id"],
        "T1",
        acreage=1000,
        ownership_pct=100,
        landowner_user_id=LANDOWNER_1_USER_ID,
    )
    fixtures.execute_tract_lease(api, tract)

    project = fixtures.refresh_project(api, project["id"])
    assert project["pore_space_consent_pct"] == 25.00
    assert project["unitization_status"] == "NOT_FILED"

    model = fixtures.register_geologic_model(api, project["id"], project["version"])
    fixtures.simulate_plume(api, model["id"])
    fixtures.submit_model(api, model["id"])

    project = fixtures.refresh_project(api, project["id"])
    assert project["status"] == "SITE_CHARACTERIZATION"
    version_before = project["version"]

    filed = validate_success(
        api.file_unitization_petition(
            project["id"],
            {
                "petition_note": (
                    "statutory unitization sought for the outstanding 3000 acres"
                )
            },
            project_developer_headers,
        )
    )
    assert filed["unitization_status"] == "FILED"
    assert filed["unitization_consent_pct_at_filing"] == 25.00

    refreshed = fixtures.refresh_project(api, project["id"])
    assert refreshed["pore_space_consent_pct"] == 25.00
    assert refreshed["statutory_bonus_per_acre_usd"] is None
    assert refreshed["outstanding_acreage"] == 3000.0000
    assert refreshed["version"] == version_before + 1


def test_geologic_model_listing_filtered_by_supersedes_model_id(
    api, project_developer_headers
):
    """Geologic models may be filtered by `project_id`, by `supersedes_model_id` (which retrieves the revisions that replaced a given predecessor), or by `status`.
    A new model rests at `status` `DRAFT` with `plume_status` `NOT_RUN` and `revision_round_count` at 0; the create bumps the parent project's `version` by one.
    The project's `governing_geologic_model_id` is set to the newly accepted model.

    Design: Corner/endpoints/list_geologic_models_filtered_by_supersedes_model_id
    """
    fixtures.set_logical_clock(api, constants.STARTUP_CLOCK_UTC)
    project = fixtures.open_project(api)
    first_model = fixtures.register_geologic_model(
        api, project["id"], project["version"]
    )
    fixtures.simulate_plume(api, first_model["id"])
    fixtures.submit_model(api, first_model["id"])
    fixtures.rule_on_model(api, first_model["id"], "ACCEPT")

    project = fixtures.refresh_project(api, project["id"])
    assert project["governing_geologic_model_id"] == first_model["id"]

    revision = fixtures.register_geologic_model(
        api,
        project["id"],
        project["version"],
        model_label="M2-DET",
        injection_zone_thickness_m=55,
        supersedes_model_id=first_model["id"],
    )

    successors, successors_meta = validate_paginated(
        api.list_geologic_models(
            project_developer_headers,
            params={
                "supersedes_model_id": first_model["id"],
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert successors_meta["total_count"] == 1
    assert [row["id"] for row in successors] == [revision["id"]]

    accepted, accepted_meta = validate_paginated(
        api.list_geologic_models(
            project_developer_headers,
            params={
                "project_id": project["id"],
                "status": "ACCEPTED",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert accepted_meta["total_count"] == 1
    assert [row["id"] for row in accepted] == [first_model["id"]]

    refreshed_revision = fixtures.refresh_model(api, revision["id"])
    assert refreshed_revision["supersedes_model_id"] == first_model["id"]
    assert refreshed_revision["status"] == "DRAFT"
    assert fixtures.refresh_model(api, first_model["id"])["status"] == "ACCEPTED"


def test_monitoring_plan_read_exposes_computed_domain_subscores(
    api, project_developer_headers
):
    """The detection term is the reference detection threshold for the method's domain divided by the method's own `detection_threshold_tpy`, capped at 1.00; the reference is 1000.0 tonnes per year for `SUBSURFACE`, 100.0 for `SURFACE` and 25.0 for `ATMOSPHERIC`, so a method claiming better sensitivity than its domain reference earns the full term while a less sensitive method is scaled down proportionally.
    The `method_score` is the product of those three terms, rounded half up to 4 decimal places.
    Each domain subscore is the sum of the `method_score` values of that domain's methods whose `status` is `ACTIVE`, capped at 1.0000 and rounded half up to 4 decimal places — so `subsurface_subscore`, `surface_subscore` and `atmospheric_subscore` each saturate, and piling a fourth seismic survey onto an already-saturated subsurface domain adds nothing.
    The plan's `coverage_score` is 100.0 multiplied by the weighted sum of the three subscores, where `subsurface_subscore` carries a weight of 0.50, `surface_subscore` a weight of 0.30 and `atmospheric_subscore` a weight of 0.20, rounded half up to 2 decimal places.
    A new method rests at `status` `ACTIVE`.

    Design: Corner/endpoints/monitoring_plan_read_exposes_computed_domain_subscores
    """
    fixtures.set_logical_clock(api, constants.STARTUP_CLOCK_UTC)
    project = fixtures.open_project(api)
    plan, methods = fixtures.create_monitoring_plan_with_methods(
        api, project["id"], methods=constants.MRV_METHODS_SCORE_70_FREE_TEXT
    )
    subsurface_method, surface_method, atmospheric_method = methods
    assert subsurface_method["method_score"] == 1.0000

    read = validate_success(api.get_monitoring_plan(plan["id"], project_developer_headers))
    assert read["subsurface_subscore"] == 1.0000
    assert read["surface_subscore"] == 0.5000
    assert read["atmospheric_subscore"] == 0.2500
    assert read["coverage_score"] == 70.00
    assert read["status"] == "DRAFT"
    assert read["revision_round_count"] == 0

    rows, _ = validate_paginated(
        api.list_monitoring_methods(plan["id"], project_developer_headers)
    )
    by_id = {row["id"]: row for row in rows}
    assert by_id[subsurface_method["id"]]["status"] == "ACTIVE"
    assert by_id[surface_method["id"]]["method_score"] == 0.5000
    assert by_id[atmospheric_method["id"]]["method_score"] == 0.2500


def test_begin_pisc_on_draft_project_rejected(api, project_developer_headers):
    """Beginning post-injection site care requires the project's `status` to be `INJECTION_ACTIVE`, requires its `operational_posture` not to be `FROZEN`, requires that no remediation order of the project have `status` `OPEN` (otherwise `ERR_OPEN_REMEDIATION_ORDER`, HTTP 409), and requires that no permit of the project sit at `permit_status` `ACTIVE` with a `construction_status` other than `COMPLETED`.
    Each entity's own current state must admit the requested transition, and each entity has its own error code: the project's `status` or `unitization_status` yields `ERR_INVALID_PROJECT_STATE`; a geologic model's `status` or `plume_status` yields `ERR_INVALID_MODEL_STATE`; a wellbore's `corrective_action_status` yields `ERR_INVALID_WELLBORE_CA_STATE`; a tract's `lease_status` yields `ERR_INVALID_TRACT_STATE`; a permit's `permit_status` yields `ERR_INVALID_PERMIT_STATE` (this also guards reporting an injection period against a permit); the construction sequence yields `ERR_INVALID_CONSTRUCTION_SEQUENCE`; an unproven mechanical integrity test yields `ERR_MIT_NOT_PASSED`; a monitoring plan's `status` or an already-closed review track yields `ERR_INVALID_PLAN_STATE` (this also guards adding or retiring a method); an instrument's `status` yields `ERR_INVALID_INSTRUMENT_STATE`; and a claim, injection period record or remediation order in the wrong `status` yields `ERR_INVALID_CLAIM_STATE`.
    Its `governing_geologic_model_id` is null because no model has yet been accepted, its `aor_radius_km` is 0 because no area of review has been delineated, its `secured_acreage` is 0 and its `outstanding_acreage` therefore equals the whole `total_project_acreage`, its `pore_space_consent_pct` and `pore_space_bonus_total_usd` are 0, its `corrective_action_completion_pct` is 100 (an empty obligation set is vacuously complete), its `cumulative_stored_tonnes` and `pending_credit_usd` are 0, its `required_financial_assurance_usd` and `allocated_assurance_usd` are 0 with `assurance_coverage_status` at `UNFUNDED`, its `effective_annual_monitoring_cost_usd` equals the supplied `annual_monitoring_cost_usd`, its `pisc_duration_years` is 50, its `open_remediation_count` is 0, and `unitization_consent_pct_at_filing`, `statutory_bonus_per_acre_usd`, `alternative_timeframe_years`, `pisc_start_at`, `closure_certified_by_user_id` and `closure_certified_at` are all null with `non_endangerment_demonstrated` false and `pisc_elapsed_years` at 0.

    Design: Corner/endpoints/begin_pisc_outside_injection_active_rejected
    """
    fixtures.set_logical_clock(api, constants.STARTUP_CLOCK_UTC)
    project = fixtures.open_project(api)
    version_before = project["version"]

    response = api.begin_pisc(
        project["id"],
        {"alternative_timeframe_years": 20},
        project_developer_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_PROJECT_STATE.value, 409)

    refreshed = fixtures.refresh_project(api, project["id"])
    assert refreshed["status"] == "DRAFT"
    assert refreshed["pisc_start_at"] is None
    assert refreshed["alternative_timeframe_years"] is None
    assert refreshed["pisc_duration_years"] == 50
    assert refreshed["pisc_elapsed_years"] == 0
    assert refreshed["version"] == version_before
