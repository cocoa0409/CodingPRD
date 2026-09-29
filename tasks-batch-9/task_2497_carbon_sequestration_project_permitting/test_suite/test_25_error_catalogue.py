"""Refusals the permitting record must issue, and the state it must not disturb.

Each test walks a project to the exact posture in which one catalogued refusal is
the only possible answer — a zero assurance requirement, a superseded parent
version, an ineligible corrective-action waiver, a monitoring plan blind to one
domain, a pressure request above the confining zone's ceiling — and then checks
that the rejected call left every affected row untouched.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers import (
    LANDOWNER_1_USER_ID,
    ApiErrorId,
    constants,
    factories,
    fixtures,
    make_landowner_headers,
)


def test_allocate_against_zero_assurance_requirement_rejected(
    api, project_developer_headers
):
    """Allocation carries the `expected_instrument_version` guard of §2.5, is admissible from `status` `POSTED` or `ALLOCATED` (so it may legitimately be re-run after the requirement moves), and requires the project's `required_financial_assurance_usd` to be strictly greater than 0; running it against a zero requirement, where no bucket requirement exists to fill, is refused with `ERR_ALLOCATION_EXCEEDS_FACE_AMOUNT` (HTTP 422).
    A posted instrument rests at `status` `POSTED` with all four allocated buckets — `allocated_ca_usd`, `allocated_plugging_usd`, `allocated_pisc_usd` and `allocated_emergency_usd` — at 0, `unallocated_usd` equal to the full `face_amount_usd`, `drawn_usd` at 0 and `released_at` null.
    A project with nothing allocated therefore reads `UNFUNDED` even when its requirement happens to be zero.

    Design: Corner/errors/allocate_against_zero_requirement_snapshot_rejected
    """
    fixtures.set_logical_clock(api, constants.STARTUP_CLOCK_UTC)
    project = fixtures.open_project(api)
    assert project["required_financial_assurance_usd"] == 0

    instrument = fixtures.post_instrument(
        api, project["id"], instrument_type="TRUST_FUND", face_amount_usd=5000000
    )

    response = api.allocate_financial_instrument(
        instrument["id"],
        factories.allocate_payload(instrument["version"]),
        project_developer_headers,
    )
    validate_error(response, ApiErrorId.ERR_ALLOCATION_EXCEEDS_FACE_AMOUNT.value, 422)

    refreshed = fixtures.refresh_instrument(api, instrument["id"])
    assert refreshed["status"] == "POSTED"
    assert refreshed["allocated_pisc_usd"] == 0.00
    assert refreshed["allocated_emergency_usd"] == 0.00
    assert refreshed["unallocated_usd"] == 5000000.00

    refreshed_project = fixtures.refresh_project(api, project["id"])
    assert refreshed_project["allocated_assurance_usd"] == 0
    assert refreshed_project["assurance_coverage_status"] == "UNFUNDED"


def test_reallocate_with_superseded_instrument_version_rejected(
    api, project_developer_headers
):
    """`version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that resource — including mutations that arrive as a cascade from a sibling or parent operation rather than as a direct request against the resource.
    If `expected_instrument_version` does not equal the instrument's stored `version`, the allocation is rejected with `ERR_STALE_INSTRUMENT_VERSION` (HTTP 412).
    It zeroes the four allocated buckets, restores `unallocated_usd` to the full `face_amount_usd`, sets `status` back to `POSTED`, recomputes the project's `allocated_assurance_usd` and `assurance_coverage_status`, and bumps both versions.

    Design: Corner/errors/reallocate_with_superseded_instrument_version_rejected
    """
    ctx = fixtures.setup_project_with_accepted_model(api)
    instrument = fixtures.post_instrument(
        api,
        ctx["project"]["id"],
        instrument_type="SURETY_BOND",
        face_amount_usd=11000000,
    )
    superseded_version = instrument["version"]
    fixtures.allocate_instrument(api, instrument)

    deallocated = get_success_data(
        api.deallocate_financial_instrument(
            instrument["id"],
            {"deallocation_reason": "instrument replaced by a larger trust fund"},
            project_developer_headers,
        )
    )
    assert deallocated["status"] == "POSTED"
    assert deallocated["version"] == 3

    response = api.allocate_financial_instrument(
        instrument["id"],
        factories.allocate_payload(superseded_version),
        project_developer_headers,
    )
    validate_error(response, ApiErrorId.ERR_STALE_INSTRUMENT_VERSION.value, 412)

    refreshed = fixtures.refresh_instrument(api, instrument["id"])
    assert refreshed["status"] == "POSTED"
    assert refreshed["version"] == 3
    assert refreshed["allocated_pisc_usd"] == 0.00
    assert refreshed["unallocated_usd"] == 11000000.00
    assert (
        fixtures.refresh_project(api, ctx["project"]["id"])["allocated_assurance_usd"]
        == 0.00
    )


def test_lease_offer_with_superseded_tract_version_rejected(
    api, project_developer_headers
):
    """Every offer increments `negotiation_round_count` by one and sets `lease_status` to `OFFER_SENT`, bumping the tract's `version`.
    A `COUNTER` response must supply a `counter_bonus_per_acre_usd` strictly greater than the tract's `current_offer_bonus_per_acre_usd` — a counter that does not improve on the developer's own number is not a counter — and it stores that figure and moves the tract `OFFER_SENT → COUNTERED`.
    An offer is admissible from `lease_status` `UNLEASED` or `COUNTERED`, and requires the project not to be `FROZEN`.
    If `expected_tract_version` does not equal the tract's stored `version`, the offer is rejected with `ERR_STALE_TRACT_VERSION` (HTTP 412).

    Design: Corner/errors/offer_with_superseded_tract_version_rejected
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
    superseded_version = tract["version"]
    fixtures.send_offer(api, tract, bonus_per_acre_usd=15.00, royalty_rate_pct=12.5)

    countered = get_success_data(
        api.respond_to_lease_offer(
            tract["id"],
            factories.counter_offer_payload(30.00),
            make_landowner_headers(tract["landowner_user_id"]),
        )
    )
    assert countered["lease_status"] == "COUNTERED"
    assert countered["version"] == 3
    assert countered["negotiation_round_count"] == 1

    response = api.send_lease_offer(
        tract["id"],
        factories.lease_offer_payload(
            superseded_version, bonus_per_acre_usd=22.00, royalty_rate_pct=12.5
        ),
        project_developer_headers,
    )
    validate_error(response, ApiErrorId.ERR_STALE_TRACT_VERSION.value, 412)

    refreshed = fixtures.refresh_tract(api, tract["id"])
    assert refreshed["lease_status"] == "COUNTERED"
    assert refreshed["negotiation_round_count"] == 1
    assert refreshed["current_offer_bonus_per_acre_usd"] == 15.00
    assert refreshed["counter_bonus_per_acre_usd"] == 30.00
    assert refreshed["version"] == 3


def test_second_geologic_model_with_superseded_project_version_rejected(
    api, project_developer_headers
):
    """A new model rests at `status` `DRAFT` with `plume_status` `NOT_RUN` and `revision_round_count` at 0; the create bumps the parent project's `version` by one.
    If `expected_project_version` does not equal the project's stored `version`, the create is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412).

    Design: Corner/errors/second_geologic_model_with_superseded_project_version_rejected
    """
    fixtures.set_logical_clock(api, constants.STARTUP_CLOCK_UTC)
    project = fixtures.open_project(api)
    superseded_version = project["version"]
    first_model = fixtures.register_geologic_model(
        api, project["id"], superseded_version
    )
    assert fixtures.refresh_project(api, project["id"])["version"] == 2

    response = api.create_geologic_model(
        factories.create_geologic_model_payload(
            project["id"],
            superseded_version,
            model_label="M2-DET",
            injection_zone_thickness_m=55,
        ),
        project_developer_headers,
    )
    validate_error(response, ApiErrorId.ERR_STALE_PROJECT_VERSION.value, 412)

    rows, meta = validate_paginated(
        api.list_geologic_models(
            project_developer_headers,
            params={"project_id": project["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [first_model["id"]]
    assert fixtures.refresh_model(api, first_model["id"])["status"] == "DRAFT"

    refreshed_project = fixtures.refresh_project(api, project["id"])
    assert refreshed_project["version"] == 2
    assert refreshed_project["status"] == "DRAFT"


def test_waive_corrective_action_on_seal_penetrating_wellbore_rejected(
    api, regulatory_reviewer_headers
):
    """The `risk_score` is 100.0 multiplied by the seal factor, multiplied by the plug factor, multiplied by the record factor, multiplied by the quantity 0.40 plus 0.60 times the proximity factor, rounded half up to 2 decimal places — so 40 percent of the score is fixed by the wellbore's own condition and 60 percent is modulated by how close it sits to the injector.
    The `ca_cost_estimate_usd` is a base mobilisation cost of 150,000.00 dollars, plus 120.00 dollars for every metre of `total_depth_m`, plus 2,000.00 dollars for every point of `risk_score`, with the total rounded half up to 2 decimal places.
    A waiver requested on a wellbore that penetrates the seal, or whose `risk_score` exceeds 60.00, is refused with `ERR_CA_WAIVER_NOT_ELIGIBLE` (HTTP 422).
    Otherwise it is 100.0 multiplied by the count of closed wellbores divided by the count of obligated wellbores, rounded half up to 2 decimal places.
    The project's `required_financial_assurance_usd` is the sum of those five already-rounded buckets, itself rounded half up to 2 decimal places.

    Design: Corner/errors/waive_corrective_action_on_seal_penetrating_wellbore_rejected
    """
    ctx = fixtures.setup_project_with_finalized_aor(
        api, wellbore_specs=[constants.WELLBORE_SEAL_OPEN_HOLE_DEEP_NEAR]
    )
    wellbore = ctx["wellbores"][0]
    assert wellbore["risk_score"] == 92.00
    assert wellbore["ca_cost_estimate_usd"] == 622000.00
    assert wellbore["corrective_action_status"] == "CA_REQUIRED"

    response = api.waive_corrective_action(
        wellbore["id"],
        {
            "waiver_rationale": (
                "operator asserts the bore is naturally sealed by shale creep"
            )
        },
        regulatory_reviewer_headers,
    )
    validate_error(response, ApiErrorId.ERR_CA_WAIVER_NOT_ELIGIBLE.value, 422)

    refreshed = fixtures.refresh_wellbore(api, wellbore["id"])
    assert refreshed["corrective_action_status"] == "CA_REQUIRED"
    assert refreshed.get("waiver_reviewer_user_id") is None

    refreshed_project = fixtures.refresh_project(api, ctx["project"]["id"])
    assert refreshed_project["corrective_action_completion_pct"] == 0.00
    assert refreshed_project["required_financial_assurance_usd"] == 25259166.94


def test_approve_monitoring_plan_without_atmospheric_method_rejected(
    api, regulatory_reviewer_headers
):
    """Symmetrically, the reviewer closes the public comment track with a `decision` of `COMPLETE_PUBLIC_COMMENT`, admissible only while `status` is `SUBMITTED` and `public_comment_complete` is still false; it sets `public_comment_complete` to true and sets `status` to `REVIEW_COMPLETE` only when `technical_review_complete` is already true, otherwise leaving `status` at `SUBMITTED`.
    An `APPROVE` ruling first enforces two quality gates in order.
    Every one of `subsurface_subscore`, `surface_subscore` and `atmospheric_subscore` must be strictly greater than 0 — a plan that monitors only the subsurface, however well, is refused with `ERR_MRV_DOMAIN_COVERAGE_MISSING` (HTTP 422).
    Then the plan's `coverage_score` must be at least 70.00; below that it is refused with `ERR_MRV_COVERAGE_BELOW_MINIMUM` (HTTP 422).
    The plan's `coverage_score` is 100.0 multiplied by the weighted sum of the three subscores, where `subsurface_subscore` carries a weight of 0.50, `surface_subscore` a weight of 0.30 and `atmospheric_subscore` a weight of 0.20, rounded half up to 2 decimal places.
    Submission resets both `technical_review_complete` and `public_comment_complete` to false, increments `revision_round_count` by one, recomputes all three subscores and the `coverage_score` from the current active methods, sets `status` to `SUBMITTED`, and bumps the plan's `version`.
    Its `governing_geologic_model_id` is null because no model has yet been accepted, its `aor_radius_km` is 0 because no area of review has been delineated, its `secured_acreage` is 0 and its `outstanding_acreage` therefore equals the whole `total_project_acreage`, its `pore_space_consent_pct` and `pore_space_bonus_total_usd` are 0, its `corrective_action_completion_pct` is 100 (an empty obligation set is vacuously complete), its `cumulative_stored_tonnes` and `pending_credit_usd` are 0, its `required_financial_assurance_usd` and `allocated_assurance_usd` are 0 with `assurance_coverage_status` at `UNFUNDED`, its `effective_annual_monitoring_cost_usd` equals the supplied `annual_monitoring_cost_usd`, its `pisc_duration_years` is 50, its `open_remediation_count` is 0, and `unitization_consent_pct_at_filing`, `statutory_bonus_per_acre_usd`, `alternative_timeframe_years`, `pisc_start_at`, `closure_certified_by_user_id` and `closure_certified_at` are all null with `non_endangerment_demonstrated` false and `pisc_elapsed_years` at 0.

    Design: Corner/errors/approve_monitoring_plan_without_atmospheric_method_rejected
    """
    fixtures.set_logical_clock(api, constants.STARTUP_CLOCK_UTC)
    project = fixtures.open_project(api)
    plan, _methods = fixtures.create_monitoring_plan_with_methods(
        api, project["id"], methods=constants.MRV_METHODS_SCORE_70_FREE_TEXT[:2]
    )

    submitted = fixtures.submit_plan(
        api, plan["id"], submission_note="MRV plan for review"
    )
    assert submitted["coverage_score"] == 65.00
    assert submitted["atmospheric_subscore"] == 0.0000

    joined = fixtures.close_both_review_tracks(api, plan["id"])
    assert joined["status"] == "REVIEW_COMPLETE"

    response = api.review_monitoring_plan(
        plan["id"],
        {"decision": "APPROVE", "condition_count": 0, "review_note": "approving"},
        regulatory_reviewer_headers,
    )
    validate_error(response, ApiErrorId.ERR_MRV_DOMAIN_COVERAGE_MISSING.value, 422)

    refreshed = fixtures.refresh_plan(api, plan["id"])
    assert refreshed["status"] == "REVIEW_COMPLETE"
    assert refreshed["approved_by_user_id"] is None
    assert refreshed["condition_count"] == 0
    assert (
        fixtures.refresh_project(api, project["id"])[
            "effective_annual_monitoring_cost_usd"
        ]
        == 200000.00
    )


def test_permit_submit_above_computed_pressure_ceiling_rejected(
    api, project_developer_headers
):
    """Creation immediately derives the well's pressure ceiling: `max_injection_pressure_psi` is 90 percent of the referenced model's `fracture_pressure_psi`, rounded half up to 2 decimal places.
    The permit rests at `permit_status` `DRAFT` and `construction_status` `NOT_STARTED`, with `authorized_injection_rate_tpy` at 0, `revision_round_count` at 0, and `last_mit_type`, `last_mit_result`, `last_mit_at` and `activated_at` all null with `mit_pass_count` at 0.
    Submission further requires the project's `aor_radius_km` to be strictly greater than 0, and requires `requested_injection_pressure_psi` to be at most `max_injection_pressure_psi` — a request above the 90-percent-of-fracture ceiling is refused with `ERR_INJECTION_PRESSURE_EXCEEDS_LIMIT` (HTTP 422).

    Design: Corner/errors/permit_submit_above_computed_pressure_limit_rejected
    """
    ctx = fixtures.setup_project_with_finalized_aor(api)
    permit = fixtures.create_permit(
        api,
        ctx["project"]["id"],
        ctx["model"]["id"],
        requested_injection_pressure_psi=4051,
    )
    assert permit["max_injection_pressure_psi"] == 4050.00

    response = api.submit_injection_well_permit(
        permit["id"],
        {"submission_note": "Class VI application"},
        project_developer_headers,
    )
    validate_error(
        response, ApiErrorId.ERR_INJECTION_PRESSURE_EXCEEDS_LIMIT.value, 422
    )

    refreshed = fixtures.refresh_permit(api, permit["id"])
    assert refreshed["permit_status"] == "DRAFT"
    assert refreshed["version"] == 1
