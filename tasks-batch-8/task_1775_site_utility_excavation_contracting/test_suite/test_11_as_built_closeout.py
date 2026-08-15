"""As-built acceptance arithmetic, the revise loop, and project closeout."""

import pytest

from test_helpers import (
    PROJECT_MANAGER,
    ApiErrorId,
    as_built_payload,
    create_as_built,
    create_project,
    create_segment,
    create_utility_owner,
    get_as_built,
    get_project,
    make_utility_owner_rep_headers,
    setup_closeout_ready_project,
    setup_complete_segment,
    setup_installing_segment,
    validate_error,
    validate_success,
)


def test_as_built_tolerance_percentage_and_floor_branches(api):
    """PRD §3.9: "The length tolerance is the larger of 1.0 foot and one
    percent of the design length rounded half up to one decimal place; the
    invert tolerance is the larger of 0.1 foot and one half of one percent of
    the design invert depth rounded half up to two decimal places. The
    computed `within_tolerance` is true only when the absolute length variance
    is at most the length tolerance and the absolute invert variance is at
    most the invert tolerance — both boundaries inclusive."

    Design: Difficulty/combinatorial_formula/as_built_tolerance_nested_max
    """
    project = create_project(name="P-AB", contract_ref="C-400",
                             soil_class_default="SOIL_A")
    owner = create_utility_owner()
    segment = create_segment(
        project, owner, segment_label="WL-B-01", pipe_material="DUCTILE_IRON",
        diameter_in=8, length_ft=200.0, bedding_class="CLASS_C",
        design_invert_depth_ft=8.0, design_slope_pct=2.0,
    )

    package = create_as_built(
        segment, surveyor_stamp="SURV-77",
        measured_length_ft=202.0, measured_invert_ft=8.1,
    )
    assert package["length_variance_ft"] == pytest.approx(2.0, abs=1e-9)
    assert package["invert_variance_ft"] == pytest.approx(0.1, abs=1e-9)
    # length tol = max(1.0, round_half_up(2.0, 1)) == 2.0 (percentage branch);
    # invert tol = max(0.1, round_half_up(0.04, 2)) == 0.1 (floor branch).
    # Both variances land exactly on their inclusive boundaries.
    assert package["within_tolerance"] is True


def test_as_built_tolerance_floor_and_percentage_inverse(api):
    """PRD §3.9: "The length tolerance is the larger of 1.0 foot and one
    percent of the design length rounded half up to one decimal place; the
    invert tolerance is the larger of 0.1 foot and one half of one percent of
    the design invert depth rounded half up to two decimal places. The
    computed `within_tolerance` is true only when the absolute length variance
    is at most the length tolerance and the absolute invert variance is at
    most the invert tolerance — both boundaries inclusive."

    Design: Difficulty/combinatorial_formula/as_built_tolerance_nested_max
    """
    project = create_project(name="P-AB2", contract_ref="C-401",
                             soil_class_default="SOIL_A")
    owner = create_utility_owner()

    # Length leg on the floor branch (max(1.0, 0.5) == 1.0) and invert leg on
    # the percentage branch (max(0.1, 0.50) == 0.50), both at the boundary.
    s1 = create_segment(
        project, owner, segment_label="WL-B-02", pipe_material="HDPE",
        diameter_in=6, length_ft=50.0, bedding_class="CLASS_D",
        design_invert_depth_ft=100.0, design_slope_pct=0.5,
    )
    within = create_as_built(
        s1, surveyor_stamp="SURV-78",
        measured_length_ft=51.0, measured_invert_ft=100.5,
    )
    assert within["length_variance_ft"] == pytest.approx(1.0, abs=1e-9)
    assert within["invert_variance_ft"] == pytest.approx(0.5, abs=1e-9)
    assert within["within_tolerance"] is True

    # One step beyond the floor on the length leg flips the predicate.
    s2 = create_segment(
        project, owner, segment_label="WL-B-03", pipe_material="HDPE",
        diameter_in=6, length_ft=50.0, bedding_class="CLASS_D",
        design_invert_depth_ft=100.0, design_slope_pct=0.5,
    )
    beyond = create_as_built(
        s2, surveyor_stamp="SURV-79",
        measured_length_ft=51.1, measured_invert_ft=100.5,
    )
    assert beyond["within_tolerance"] is False


def test_second_open_as_built_rejected(api):
    """PRD §3.9: "A segment may have at most one open package: creating while
    one exists in `DRAFT` or `SUBMITTED` is rejected with
    `ERR_ASBUILT_ALREADY_OPEN`."

    Design: Corner/validations/asbuilt_open_uniqueness
    """
    project = create_project(name="P-ABU", contract_ref="C-411",
                             soil_class_default="SOIL_A")
    owner = create_utility_owner()
    segment = create_segment(
        project, owner, segment_label="WL-V-10", pipe_material="HDPE",
        diameter_in=6, length_ft=100.0, bedding_class="CLASS_D",
        design_invert_depth_ft=1.0, design_slope_pct=0.5,
    )

    first = create_as_built(
        segment, surveyor_stamp="SURV-1",
        measured_length_ft=100.5, measured_invert_ft=1.0,
    )
    assert first["status"] == "DRAFT"

    response = api.create_as_built_package(
        as_built_payload(
            segment["id"], surveyor_stamp="SURV-2",
            measured_length_ft=100.2, measured_invert_ft=1.05,
        ),
        PROJECT_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_ASBUILT_ALREADY_OPEN, 409)
    assert get_as_built(first["id"])["status"] == "DRAFT"


def test_as_built_submit_requires_complete_segment(api):
    """PRD §3.9: "Submitting the package moves it `DRAFT → SUBMITTED` and
    requires the segment to be `COMPLETE` (`ERR_SEGMENT_NOT_COMPLETE`)."

    Design: Corner/validations/asbuilt_submit_requires_complete_segment
    """
    project = create_project(name="P-ABS", contract_ref="C-420",
                             soil_class_default="SOIL_A")
    owner = create_utility_owner()
    segment = create_segment(
        project, owner, segment_label="WL-V-13", pipe_material="HDPE",
        diameter_in=6, length_ft=100.0, bedding_class="CLASS_D",
        design_invert_depth_ft=1.0, design_slope_pct=0.5,
    )
    package = create_as_built(
        segment, surveyor_stamp="SURV-1",
        measured_length_ft=100.0, measured_invert_ft=1.0,
    )

    response = api.submit_as_built_package(package["id"], PROJECT_MANAGER)
    validate_error(response, ApiErrorId.ERR_SEGMENT_NOT_COMPLETE, 409)
    assert get_as_built(package["id"])["status"] == "DRAFT"


def test_as_built_accept_out_of_tolerance_rejected(api):
    """PRD §3.9: "The rep passes a `decision` of `ACCEPT` or `REJECT`, moving
    the package from `SUBMITTED` to `ACCEPTED` or `REJECTED`; an accept
    against a package whose `within_tolerance` is false is rejected with
    `ERR_ASBUILT_OUT_OF_TOLERANCE`."

    Design: Corner/validations/asbuilt_accept_out_of_tolerance_rejected
    """
    ctx = setup_complete_segment()
    segment, owner = ctx["segment"], ctx["owner"]

    # measured 102.0 vs design 100.0: tolerance max(1.0, 1.0) == 1.0 < 2.0.
    package = create_as_built(
        segment, surveyor_stamp="SURV-1",
        measured_length_ft=102.0, measured_invert_ft=1.0,
    )
    assert package["within_tolerance"] is False
    validate_success(api.submit_as_built_package(package["id"], PROJECT_MANAGER))

    rep = make_utility_owner_rep_headers(owner["id"])
    response = api.review_as_built_package(package["id"], "ACCEPT", rep)
    validate_error(response, ApiErrorId.ERR_ASBUILT_OUT_OF_TOLERANCE, 409)
    assert get_as_built(package["id"])["status"] == "SUBMITTED"

    # The rejection path on the same package stays open.
    rejected = validate_success(
        api.review_as_built_package(package["id"], "REJECT", rep)
    )
    assert rejected["status"] == "REJECTED"


def test_as_built_reject_revise_accept_loop(api):
    """PRD §3.9: "An accepted package is terminal; a `REJECTED` package may be
    revised back to `DRAFT` by the `ProjectManager`, incrementing `revision`
    and optionally applying a new `surveyor_stamp`, `measured_length_ft`, or
    `measured_invert_ft`, with the variances and `within_tolerance` recomputed
    from whatever was supplied."

    Design: Corner/state_machines/asbuilt_reject_revise_accept_loop
    """
    ctx = setup_complete_segment()
    segment, owner = ctx["segment"], ctx["owner"]

    package = create_as_built(
        segment, surveyor_stamp="SURV-1",
        measured_length_ft=105.0, measured_invert_ft=1.0,
    )
    validate_success(api.submit_as_built_package(package["id"], PROJECT_MANAGER))
    rep = make_utility_owner_rep_headers(owner["id"])
    rejected = validate_success(
        api.review_as_built_package(package["id"], "REJECT", rep)
    )
    assert rejected["status"] == "REJECTED"

    revised = validate_success(
        api.revise_as_built_package(
            package["id"], {"measured_length_ft": 100.5}, PROJECT_MANAGER
        )
    )
    assert revised["status"] == "DRAFT"
    assert revised["revision"] == 2
    assert revised["length_variance_ft"] == pytest.approx(0.5, abs=1e-9)
    # 0.5 <= max(1.0, 1.0) and 0.0 <= 0.1 — back inside tolerance.
    assert revised["within_tolerance"] is True

    validate_success(api.submit_as_built_package(package["id"], PROJECT_MANAGER))
    accepted = validate_success(
        api.review_as_built_package(package["id"], "ACCEPT", rep)
    )
    assert accepted["status"] == "ACCEPTED"


def test_closeout_blocked_by_incomplete_segment(api):
    """PRD §3.9: "Beginning closeout moves the project `ACTIVE → CLOSING` —
    the intermediate `CLOSING` status marks that closeout has been initiated —
    only when the completeness bundle passes in full: every pipe segment of
    the project is `COMPLETE`, every pipe segment has an as-built package in
    `ACCEPTED`, no unforeseen condition remains in `OPEN` or `MITIGATING`, no
    change order remains in `DRAFT`, `SUBMITTED`, or `APPROVED`, and the
    project's `work_posture` is `CLEAR`. Any shortfall is rejected with
    `ERR_CLOSEOUT_INCOMPLETE`."

    Design: Corner/validations/closeout_blocked_by_incomplete_segment
    """
    ctx = setup_installing_segment(shallow=False)
    project = ctx["project"]
    assert ctx["segment"]["status"] == "INSTALLING"

    response = api.begin_closeout(project["id"], PROJECT_MANAGER)
    validate_error(response, ApiErrorId.ERR_CLOSEOUT_INCOMPLETE, 409)
    assert get_project(project["id"])["status"] == "ACTIVE"


def test_full_closeout_golden_path(api):
    """PRD §3.9: "Beginning closeout moves the project `ACTIVE → CLOSING` —
    the intermediate `CLOSING` status marks that closeout has been initiated —
    only when the completeness bundle passes in full: every pipe segment of
    the project is `COMPLETE`, every pipe segment has an as-built package in
    `ACCEPTED`, no unforeseen condition remains in `OPEN` or `MITIGATING`, no
    change order remains in `DRAFT`, `SUBMITTED`, or `APPROVED`, and the
    project's `work_posture` is `CLEAR`. Any shortfall is rejected with
    `ERR_CLOSEOUT_INCOMPLETE`. Closing then moves `CLOSING → CLOSED` and
    stamps `closed_at` with the current logical clock time; `CLOSED` is
    terminal, and no further actions may be taken on the project."

    Design: Corner/endpoints/full_closeout_golden_path
    """
    ctx = setup_closeout_ready_project()
    project, segment = ctx["project"], ctx["segment"]
    assert segment["status"] == "COMPLETE"
    assert ctx["as_built"]["status"] == "ACCEPTED"

    closing = validate_success(api.begin_closeout(project["id"], PROJECT_MANAGER))
    assert closing["status"] == "CLOSING"

    closed = validate_success(api.close_project(project["id"], PROJECT_MANAGER))
    assert closed["status"] == "CLOSED"
    # The logical clock stands at 2026-08-03T00:00:00Z (ticket activation).
    assert closed["closed_at"].startswith("2026-08-03T00:00:00")
