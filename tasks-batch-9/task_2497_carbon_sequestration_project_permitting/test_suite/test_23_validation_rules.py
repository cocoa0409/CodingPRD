"""Request-level validation gates on permits and legacy wellbore registration.

The rules exercised here are the construction-standard conjunction that a Class VI
permit application must satisfy before it may be submitted, the conditional
request-shape requirement that an annulus pressure test carry its measured
pressure loss, and the project-scoped uniqueness of a legacy wellbore's regulatory
API number — each checked for the error it raises and for the writes it must not
leave behind.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import ApiErrorId, fixtures
from test_helpers.constants import STARTUP_CLOCK_UTC, WELLBORE_UNKNOWN_PLUG_MID


def test_permit_submit_with_single_string_casing_rejected(
    api, project_developer_headers
):
    """Creation immediately derives the well's pressure ceiling: `max_injection_pressure_psi` is 90 percent of the referenced model's `fracture_pressure_psi`, rounded half up to 2 decimal places.

    Submission is admissible from `permit_status` `DRAFT` or `REVISION_REQUESTED`, and it enforces three construction requirements together: `casing_program` must be `LONG_STRING_CEMENTED_TO_SURFACE`, `corrosion_resistant_material` must be true, and `tubing_packer_installed` must be true.

    A `LINER` or `SINGLE_STRING` programme, or a missing corrosion-resistant completion, or injection that is not through tubing on a packer, is refused with `ERR_CASING_PROGRAM_NONCOMPLIANT` (HTTP 422).

    On success `revision_round_count` increments by one, `permit_status` moves to `SUBMITTED`, and the permit's `version` increments.

    Design: Corner/validations/permit_submit_with_single_string_casing_rejected
    """
    ctx = fixtures.setup_project_with_finalized_aor(api)
    permit = fixtures.create_permit(
        api,
        ctx["project"]["id"],
        ctx["model"]["id"],
        well_name="BRAVO-1",
        casing_program="SINGLE_STRING",
        corrosion_resistant_material=True,
        tubing_packer_installed=True,
        requested_injection_pressure_psi=4000,
    )
    assert permit["max_injection_pressure_psi"] == 4050.00

    response = api.submit_injection_well_permit(
        permit["id"], {"submission_note": "Class VI application"}, project_developer_headers
    )
    validate_error(response, ApiErrorId.ERR_CASING_PROGRAM_NONCOMPLIANT.value, 422)

    unchanged = fixtures.refresh_permit(api, permit["id"])
    assert unchanged["permit_status"] == "DRAFT"
    assert unchanged["revision_round_count"] == 0
    assert unchanged["version"] == 1


def test_permit_submit_with_compliant_construction_standards_accepted(
    api, project_developer_headers
):
    """Submission is admissible from `permit_status` `DRAFT` or `REVISION_REQUESTED`, and it enforces three construction requirements together: `casing_program` must be `LONG_STRING_CEMENTED_TO_SURFACE`, `corrosion_resistant_material` must be true, and `tubing_packer_installed` must be true.

    Submission further requires the project's `aor_radius_km` to be strictly greater than 0, and requires `requested_injection_pressure_psi` to be at most `max_injection_pressure_psi` — a request above the 90-percent-of-fracture ceiling is refused with `ERR_INJECTION_PRESSURE_EXCEEDS_LIMIT` (HTTP 422).

    On success `revision_round_count` increments by one, `permit_status` moves to `SUBMITTED`, and the permit's `version` increments.

    Creation immediately derives the well's pressure ceiling: `max_injection_pressure_psi` is 90 percent of the referenced model's `fracture_pressure_psi`, rounded half up to 2 decimal places.

    Design: Corner/validations/permit_submit_with_compliant_construction_standards_passes
    """
    ctx = fixtures.setup_project_with_finalized_aor(api)
    assert ctx["model"]["aor_radius_km"] == 3.0

    permit = fixtures.create_permit(
        api,
        ctx["project"]["id"],
        ctx["model"]["id"],
        well_name="ALPHA-1",
        casing_program="LONG_STRING_CEMENTED_TO_SURFACE",
        corrosion_resistant_material=True,
        tubing_packer_installed=True,
        requested_injection_pressure_psi=4050,
    )

    response = api.submit_injection_well_permit(
        permit["id"], {"submission_note": "Class VI application"}, project_developer_headers
    )
    submitted = validate_success(response, 200)

    assert submitted["permit_status"] == "SUBMITTED"
    assert submitted["version"] == 2

    stored = fixtures.refresh_permit(api, permit["id"])
    assert stored["requested_injection_pressure_psi"] == 4050
    assert stored["max_injection_pressure_psi"] == 4050.00


def test_record_mit_annulus_test_without_pressure_loss_rejected(
    api, project_developer_headers
):
    """The system evaluates checks in a fixed precedence ladder, and the first failing check produces the response; later checks are not evaluated.

    Required body fields present, enum values inside their declared sets, numbers inside their declared ranges, timestamps parseable as ISO 8601, `limit` between 1 and 100, `offset` at least 0, and the conditional mechanical-integrity requirements (an `annulus_pressure_loss_psi` value is required when `test_type` is `ANNULUS_PRESSURE`, and an `anomaly_detected` value is required for the other two test types) — `ERR_INVALID_REQUEST`.

    An annulus pressure test must carry an `annulus_pressure_loss_psi` value and produces a `PASS` verdict when that loss is at most 3.00 psi and a `FAIL` verdict when it exceeds 3.00 psi — a loss of exactly 3.00 psi is a `PASS`, and the comparison is made on the submitted value at 2 decimal places.

    Recording a test writes `last_mit_type` from the submitted `test_type`, writes the verdict to `last_mit_result`, stamps `last_mit_at` with the logical clock, and increases `mit_pass_count` by one when and only when the verdict was `PASS`.

    Design: Corner/validations/record_mit_annulus_test_without_pressure_loss_invalid_request
    """
    ctx = fixtures.setup_project_with_accepted_model(api)
    permit = fixtures.create_permit(
        api, ctx["project"]["id"], ctx["model"]["id"], well_name="ALPHA-1"
    )

    # The payload deliberately omits annulus_pressure_loss_psi, which the
    # conditional shape requirement makes mandatory for this test type.
    response = api.record_mit(
        permit["id"], {"test_type": "ANNULUS_PRESSURE"}, project_developer_headers
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    unchanged = fixtures.refresh_permit(api, permit["id"])
    assert unchanged["last_mit_type"] is None
    assert unchanged["last_mit_result"] is None
    assert unchanged["mit_pass_count"] == 0
    assert unchanged["version"] == 1


def test_duplicate_api_number_rejected_without_creating_second_wellbore(
    api, project_developer_headers, program_admin_headers
):
    """Registering a second wellbore with an `api_number` already used inside the same project is refused with `ERR_DUPLICATE_API_NUMBER` (HTTP 409).

    When the project's `aor_radius_km` is 0, or when the wellbore's `distance_from_injector_km` exceeds the project's `aor_radius_km`, the wellbore begins at `OUT_OF_AOR` and waits for a future delineation to pull it in.

    Wellbores whose `corrective_action_status` is `OUT_OF_AOR` are excluded entirely, from both numerator and denominator — they are outside the regulator's concern.

    When the obligated set is empty, `corrective_action_completion_pct` is exactly 100.00.

    `version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that resource — including mutations that arrive as a cascade from a sibling or parent operation rather than as a direct request against the resource.

    Design: Corner/validations/duplicate_api_number_rejected_without_creating_second_wellbore
    """
    fixtures.set_logical_clock(api, STARTUP_CLOCK_UTC)
    project = fixtures.open_project(api)
    first_wellbore = fixtures.register_wellbore(
        api, project["id"], "15-001-00007", **WELLBORE_UNKNOWN_PLUG_MID
    )

    before = fixtures.refresh_project(api, project["id"])
    assert before["corrective_action_completion_pct"] == 100.00

    response = api.create_legacy_wellbore(
        {
            "project_id": project["id"],
            "api_number": "15-001-00007",
            "distance_from_injector_km": 0.4,
            "total_depth_m": 2400,
            "penetrates_seal": True,
            "plug_condition": "OPEN_HOLE",
            "plug_record_available": False,
        },
        project_developer_headers,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_API_NUMBER.value, 409)

    survivor = fixtures.refresh_wellbore(api, first_wellbore["id"])
    assert survivor["corrective_action_status"] == "OUT_OF_AOR"

    wellbores, meta = validate_paginated(
        api.list_project_legacy_wellbores(project["id"], program_admin_headers)
    )
    assert meta["total_count"] == 1
    assert [wellbore["id"] for wellbore in wellbores] == [first_wellbore["id"]]

    after = fixtures.refresh_project(api, project["id"])
    assert after["corrective_action_completion_pct"] == 100.00
    assert after["version"] == before["version"]
    assert (
        after["required_financial_assurance_usd"]
        == before["required_financial_assurance_usd"]
    )
