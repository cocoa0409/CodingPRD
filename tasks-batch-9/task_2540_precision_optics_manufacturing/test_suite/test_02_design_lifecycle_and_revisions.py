"""Lodging a design, its declared defaults, and the revision chain."""

import pytest

from test_helpers import (
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_STALE_DESIGN_VERSION,
    add_allocation,
    assert_stack_outputs_null,
    assert_wavefront_value,
    build_design_revision_payload,
    build_optical_design_payload,
    create_design,
    create_released_design,
    create_toleranced_design,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_optics_engineer_headers,
    open_work_order,
    create_certified_lot,
    validate_error,
    validate_success,
)


def test_design_create_echoes_every_supplied_field_and_mints_the_system_fields(api):
    """A fully specified design is echoed back beside the fields the server mints.

    The PRD states that a newly lodged design "is created in `DRAFT` with
    `tolerance_verdict` set to `PENDING`, `design_revision` set to 1,
    `supersedes_design_id` set to null".

    Design: Corner/entities/optical_design_create_echoes_every_supplied_field_and_mints_the_system_fields
    """
    payload = build_optical_design_payload(
        design_code="OD-2540-ECHO",
        aperture_mm=120.0,
        wavelength_min_nm=450,
        wavelength_max_nm=700,
        required_rms_wavefront_waves=0.0400,
        tolerance_budget_waves=0.0800,
        transmitted_wavefront_budget_waves=0.1050,
        surface_figure_budget_waves=0.0300,
        surface_roughness_budget_nm=1.1000,
        min_center_thickness_um=5900.0,
        min_index_homogeneity_grade="H2",
        max_striae_grade="A",
        scratch_dig_scratch_limit=30,
        scratch_dig_dig_limit=15,
        cleanliness_limit_per_cm2=40,
        tolerance_method="WORST_CASE",
    )

    created = validate_success(
        api.create_optical_design(payload, make_optics_engineer_headers()),
        expected_status=201,
    )

    for field, expected in payload.items():
        assert created[field] == expected, (
            f"{field} must be echoed as {expected}, got {created[field]}"
        )
    assert is_valid_uuid(created["id"]), f"id must be a UUID, got {created['id']}"
    assert created["version"] == 1, f"version must start at 1, got {created['version']}"
    assert is_iso8601_timestamp(created["created_at"]), (
        f"created_at must be an ISO 8601 UTC timestamp, got {created['created_at']}"
    )
    assert is_iso8601_timestamp(created["updated_at"]), (
        f"updated_at must be an ISO 8601 UTC timestamp, got {created['updated_at']}"
    )
    assert created["design_status"] == "DRAFT"
    assert created["tolerance_verdict"] == "PENDING"
    assert created["design_revision"] == 1
    assert created["supersedes_design_id"] is None
    assert_stack_outputs_null(created)


def test_omitted_optional_fields_fall_back_to_their_declared_defaults(api):
    """Every optional specification limit takes its shop default.

    The PRD states that "`surface_figure_budget_waves`, the per-surface figure RMS
    budget referenced at the figuring stage, defaults to 0.0250 waves." and that
    "`min_center_thickness_um`, the minimum admissible centre thickness after
    material removal, defaults to 5800.0 micrometres — that is, 5.8 millimetres of
    glass must remain."

    Design: Corner/entities/omitted_optional_fields_fall_back_to_their_declared_defaults
    """
    payload = {
        "design_code": "OD-2540-DEF",
        "aperture_mm": 120.0,
        "wavelength_min_nm": 450,
        "wavelength_max_nm": 700,
        "required_rms_wavefront_waves": 0.0400,
        "tolerance_budget_waves": 0.0800,
        "transmitted_wavefront_budget_waves": 0.1050,
    }

    created = validate_success(
        api.create_optical_design(payload, make_optics_engineer_headers()),
        expected_status=201,
    )

    assert_wavefront_value(
        created["surface_figure_budget_waves"], 0.0250, "surface_figure_budget_waves"
    )
    assert_wavefront_value(
        created["surface_roughness_budget_nm"], 1.2000, "surface_roughness_budget_nm"
    )
    assert created["min_center_thickness_um"] == pytest.approx(5800.0, abs=0.01), (
        f"min_center_thickness_um must default to 5800.0, got "
        f"{created['min_center_thickness_um']}"
    )
    assert created["min_index_homogeneity_grade"] == "H3", (
        "min_index_homogeneity_grade must default to H3, got "
        f"{created['min_index_homogeneity_grade']}"
    )
    assert created["max_striae_grade"] == "B", (
        f"max_striae_grade must default to B, got {created['max_striae_grade']}"
    )
    assert created["scratch_dig_scratch_limit"] == 40
    assert created["scratch_dig_dig_limit"] == 20
    assert created["cleanliness_limit_per_cm2"] == 50
    assert created["tolerance_method"] == "STATISTICAL", (
        f"tolerance_method must default to STATISTICAL, got {created['tolerance_method']}"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("aperture_mm", 0.0),
        ("wavelength_min_nm", 199),
        ("wavelength_max_nm", 450),
        ("required_rms_wavefront_waves", 0.0),
        ("tolerance_budget_waves", 0.0),
        ("transmitted_wavefront_budget_waves", 0.0),
        ("cleanliness_limit_per_cm2", -1),
        ("min_index_homogeneity_grade", "H9"),
        ("max_striae_grade", "Z"),
        ("tolerance_method", "AVERAGE"),
    ],
)
def test_design_create_rejects_out_of_range_and_non_enum_values(api, field, value):
    """Range and enum membership are checked before anything is persisted.

    The PRD states that "every enum value is a member of its declared set; numeric
    fields are non-negative and inside their declared range" on pain of
    `ERR_INVALID_REQUEST`.

    Design: Corner/entities/optical_design_create_rejects_out_of_range_and_non_enum_values
    """
    payload = build_optical_design_payload(design_code="OD-2540-BAD", **{field: value})

    response = api.create_optical_design(payload, make_optics_engineer_headers())

    validate_error(response, ERR_INVALID_REQUEST)


def test_design_release_moves_toleranced_to_released_without_touching_the_stack(api):
    """Release advances the status and leaves every computed figure alone.

    The PRD states that "Releasing a design for manufacture moves it
    `TOLERANCED → RELEASED`" and that release "is the only place the budget is
    enforced".

    Design: Corner/state_machines/design_release_moves_toleranced_to_released_without_touching_the_stack
    """
    toleranced = create_toleranced_design(api, design_code="OD-2540-REL")

    released = validate_success(
        api.release_optical_design(toleranced["id"], make_optics_engineer_headers()),
        expected_status=200,
    )

    assert released["design_status"] == "RELEASED", (
        f"design_status must be RELEASED, got {released['design_status']}"
    )
    for field in (
        "rss_stack_waves",
        "worst_case_stack_waves",
        "governing_stack_waves",
        "allocated_tolerance_waves",
        "tolerance_verdict",
    ):
        assert released[field] == toleranced[field], (
            f"{field} must be untouched by release, was {toleranced[field]} and is "
            f"now {released[field]}"
        )
    assert released["version"] == toleranced["version"] + 1, (
        "release increments the design version by exactly one, got "
        f"{released['version']} after {toleranced['version']}"
    )


def test_release_before_analysis_and_analysis_after_it_are_both_rejected(api):
    """A draft cannot be released and a toleranced design cannot be re-analysed.

    The PRD states that "The addressed row's current state is a declared origin
    state of the requested transition. This covers terminal-state lockdown and the
    rejection of a second application of the same step."

    Design: Corner/state_machines/release_before_analysis_and_analysis_after_it_are_both_rejected
    """
    design = create_design(api, design_code="OD-2540-ORD")
    add_allocation(api, design["id"])

    premature_release = api.release_optical_design(
        design["id"], make_optics_engineer_headers()
    )
    analysed = validate_success(
        api.run_tolerance_analysis(design["id"], make_optics_engineer_headers()),
        expected_status=200,
    )
    second_analysis = api.run_tolerance_analysis(
        design["id"], make_optics_engineer_headers()
    )

    validate_error(premature_release, ERR_INVALID_STATE_TRANSITION)
    assert analysed["design_status"] == "TOLERANCED"
    validate_error(second_analysis, ERR_INVALID_STATE_TRANSITION)
    after = validate_success(
        api.get_optical_design(design["id"], make_optics_engineer_headers()),
        expected_status=200,
    )
    assert after["design_status"] == "TOLERANCED", (
        f"the refused second analysis leaves TOLERANCED, got {after['design_status']}"
    )


def test_a_stale_expected_design_version_outranks_the_revision_state_gate(api):
    """The version guard is adjudicated before the origin-state check.

    The PRD states that "The stale-version guard of §2.7 holds on design revision,
    work-order creation and component kitting" at priority six, ahead of "The
    addressed row's current state is a declared origin state of the requested
    transition" at priority seven.

    Design: Corner/validations/a_stale_expected_design_version_outranks_the_revision_state_gate
    """
    toleranced = create_toleranced_design(api, design_code="OD-2540-OCC")
    assert toleranced["version"] == 2, (
        f"a toleranced design carries version 2, got {toleranced['version']}"
    )

    stale = api.create_design_revision(
        toleranced["id"],
        build_design_revision_payload(
            expected_design_version=1, design_code="OD-2540-OCC-R1"
        ),
        make_optics_engineer_headers(),
    )
    fresh_but_undraftable = api.create_design_revision(
        toleranced["id"],
        build_design_revision_payload(
            expected_design_version=2, design_code="OD-2540-OCC-R1"
        ),
        make_optics_engineer_headers(),
    )

    validate_error(stale, ERR_STALE_DESIGN_VERSION)
    validate_error(fresh_but_undraftable, ERR_INVALID_STATE_TRANSITION)
    unchanged = validate_success(
        api.get_optical_design(toleranced["id"], make_optics_engineer_headers()),
        expected_status=200,
    )
    assert unchanged["version"] == 2, (
        f"neither refusal may mutate the design, got version {unchanged['version']}"
    )

    released = validate_success(
        api.release_optical_design(toleranced["id"], make_optics_engineer_headers()),
        expected_status=200,
    )
    assert released["version"] == 3
    revision = validate_success(
        api.create_design_revision(
            toleranced["id"],
            build_design_revision_payload(
                expected_design_version=3, design_code="OD-2540-OCC-R1"
            ),
            make_optics_engineer_headers(),
        ),
        expected_status=201,
    )

    assert revision["design_revision"] == 2, (
        f"design_revision must be 2, got {revision['design_revision']}"
    )
    assert revision["supersedes_design_id"] == toleranced["id"], (
        "supersedes_design_id must point at the predecessor, got "
        f"{revision['supersedes_design_id']}"
    )
    predecessor = validate_success(
        api.get_optical_design(toleranced["id"], make_optics_engineer_headers()),
        expected_status=200,
    )
    assert predecessor["design_status"] == "SUPERSEDED", (
        f"predecessor must be SUPERSEDED, got {predecessor['design_status']}"
    )
    assert predecessor["version"] == 4, (
        f"predecessor version must be incremented to 4, got {predecessor['version']}"
    )


def test_work_order_pinned_design_revision_is_frozen_against_a_later_revision(api):
    """A later revision does not disturb an order already in the shop.

    The PRD states that "Work orders already opened against the predecessor are
    entirely unaffected: each carries a `pinned_design_revision` captured when it
    was opened".

    Design: Corner/entities/work_order_pinned_design_revision_is_frozen_against_a_later_revision
    """
    design = create_released_design(api, design_code="OD-2540-PIN")
    lot = create_certified_lot(api, lot_code="GL-2540-PIN")
    work_order = open_work_order(api, design["id"], lot["id"], lot["version"])
    assert work_order["pinned_design_revision"] == 1, (
        f"pinned_design_revision must be 1, got {work_order['pinned_design_revision']}"
    )

    revision = validate_success(
        api.create_design_revision(
            design["id"],
            build_design_revision_payload(
                expected_design_version=design["version"],
                design_code="OD-2540-PIN-R2",
            ),
            make_optics_engineer_headers(),
        ),
        expected_status=201,
    )

    after = validate_success(
        api.get_work_order(work_order["id"], make_optics_engineer_headers()),
        expected_status=200,
    )
    assert revision["design_revision"] == 2
    assert after["pinned_design_revision"] == 1, (
        "the order keeps the generation it was released against, got "
        f"{after['pinned_design_revision']}"
    )
    assert after["design_id"] == design["id"], (
        f"design_id must still name the predecessor, got {after['design_id']}"
    )
    assert after["process_status"] == "BLANKS_RESERVED", (
        f"process_status must be BLANKS_RESERVED, got {after['process_status']}"
    )
