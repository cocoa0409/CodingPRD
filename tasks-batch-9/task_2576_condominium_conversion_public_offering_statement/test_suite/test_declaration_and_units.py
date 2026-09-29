"""Declaration package and units: creation constraints, the plat-certification and
recording gates, withdrawal reallocation and the withdrawal cascade.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from test_helpers.assertions import (
    assert_decimal_equals,
    assert_instant,
    assert_page,
    ids_of,
)
from test_helpers.constants import TOTAL_UNDIVIDED_INTEREST_BP
from test_helpers.factories import (
    component_payload,
    package_payload,
    roof_standard,
    unit_payload,
)
from test_helpers.fixtures import (
    adopt_budget,
    assign_agreement,
    build_registered_project,
    certify_plat,
    deliver_pos,
    evaluate_threshold,
    fund_escrow,
    harden,
    make_agreement,
    make_batch,
    make_budget,
    make_package,
    make_passed_gate,
    make_project,
    make_reserve_study,
    make_unit,
    make_units,
    release_batch,
    set_clock,
)
from test_helpers.test_users import regulator_headers, sponsor_headers

STD_PROJECT = ("44 Cove Lane, Bangor ME", 1968, 2)


def test_withdraw_unit_with_unknown_id_returns_declaration_artifact_not_found(api):
    """PRD: A missing declaration artifact — a declaration package or a unit — fails
    with `ERR_DECLARATION_ARTIFACT_NOT_FOUND`, HTTP 404.

    Design: Corner/entities/withdraw_unit_with_unknown_id_returns_declaration_artifact_not_found
    """
    response = api.withdraw_unit(
        NON_EXISTENT_UUID, sponsor_headers(), {"withdrawal_reason": "probe"}
    )
    validate_error(
        response, "ERR_DECLARATION_ARTIFACT_NOT_FOUND", expected_status=404
    )
    # Per the envelope spec, `response_type` is a top-level field; the `meta` of an
    # error response carries only api_request_id and api_request_timestamp.
    assert response.json()["response_type"] == "error"


def test_create_unit_base_bp_above_declared_range_returns_invalid_request(api):
    """PRD: `base_percentage_interest_bp` is a whole number of basis points of at least
    1 and at most 10000, both endpoints accepted.

    Design: Corner/entities/create_unit_base_bp_above_declared_range_returns_invalid_request
    """
    project = make_project(api, *STD_PROJECT)
    package = make_package(api, project["id"], "PAINT_TO_PAINT", "decl-1", "bylaws-1")

    validate_error(
        api.create_unit(
            package["id"],
            unit_payload("101", 10001, 1, 900, "paint to paint"),
            sponsor_headers(),
        ),
        "ERR_INVALID_REQUEST",
        expected_status=422,
    )
    validate_error(
        api.create_unit(
            package["id"],
            unit_payload("102", 0, 1, 900, "paint to paint"),
            sponsor_headers(),
        ),
        "ERR_INVALID_REQUEST",
        expected_status=422,
    )
    assert validate_success(api.get_package(package["id"], sponsor_headers()))[
        "allocated_bp_total"
    ] == 0
    assert validate_success(api.get_project(project["id"], sponsor_headers()))[
        "included_unit_count"
    ] == 0


def test_second_declaration_package_on_same_project_returns_duplicate_key(api):
    """PRD: A project holds at most one declaration package; a second attempt fails
    with `ERR_DUPLICATE_KEY`.

    Design: Corner/state_machines/second_declaration_package_on_same_project_returns_duplicate_key
    """
    project = make_project(api, *STD_PROJECT)
    package = make_package(api, project["id"], "PAINT_TO_PAINT", "decl-1", "bylaws-1")

    validate_error(
        api.create_package(
            project["id"],
            package_payload("decl-1", "bylaws-1", "PAINT_TO_PAINT"),
            sponsor_headers(),
        ),
        "ERR_DUPLICATE_KEY",
        expected_status=409,
    )
    reread = validate_success(api.get_package(package["id"], sponsor_headers()))
    assert reread["status"] == "DRAFT"
    assert reread["version"] == package["version"]
    _, meta = validate_paginated(api.list_packages(project["id"], sponsor_headers()))
    assert_page(meta, total_count=1)


def test_plat_certification_without_passed_suitability_gate_returns_gate_failed(api):
    """PRD: Plat certification requires the project's `suitability_gate` to be
    `PASSED`, or the request fails with `ERR_SUITABILITY_GATE_FAILED`.

    Design: Corner/state_machines/plat_certification_without_passed_suitability_gate_returns_gate_failed
    """
    project = make_project(api, "44 Cove Lane, Bangor ME", 1968, 2)
    package = make_package(api, project["id"], "PAINT_TO_PAINT", "decl-1", "bylaws-1")
    make_unit(api, package["id"], "101", 10000, 1, 900, "as-built")

    validate_error(
        api.certify_plat(package["id"], sponsor_headers()),
        "ERR_SUITABILITY_GATE_FAILED",
        expected_status=409,
    )
    assert validate_success(api.get_project(project["id"], sponsor_headers()))[
        "suitability_gate"
    ] == "UNEVALUATED"
    reread = validate_success(api.get_package(package["id"], sponsor_headers()))
    assert reread["allocated_bp_total"] == 0
    assert reread["status"] == "DRAFT"
    assert reread["plat_revision"] == 0
    assert validate_success(api.get_project(project["id"], sponsor_headers()))[
        "included_unit_count"
    ] == 1


def test_recording_declaration_stamps_project_warranty_start_and_advances_status(api):
    """PRD: Recording stamps `recorded_at` on the package from the logical clock, copies
    that instant onto the project as `declaration_recorded_at` and `warranty_start_at`,
    and advances the project to `REGISTRATION`.

    Design: Corner/state_machines/recording_declaration_stamps_project_warranty_start_and_advances_status
    """
    project = make_project(api, "44 Cove Lane, Bangor ME", 1968, 2)
    gate = make_passed_gate(api, project["id"])
    package = make_package(api, project["id"], "PAINT_TO_PAINT", "decl-1", "bylaws-1")
    make_unit(api, package["id"], "101", 10000, 1, 900, "as-built")
    study = make_reserve_study(
        api, project["id"], gate["report"]["id"], "COMPONENT_METHOD", 0
    )
    budget = make_budget(api, project["id"], study["id"], 1000000)
    adopt_budget(api, budget["id"])
    certify_plat(api, package["id"])

    before = validate_success(api.get_project(project["id"], sponsor_headers()))
    assert before["status"] == "DOCUMENTS_PREPARATION"
    assert before["warranty_start_at"] is None
    assert validate_success(api.get_budget(budget["id"], sponsor_headers()))[
        "status"
    ] == "ADOPTED"
    assert validate_success(api.get_reserve_study(study["id"], sponsor_headers()))[
        "adoption_status"
    ] == "ADOPTED"

    recorded = validate_success(api.record_package(package["id"], sponsor_headers()))
    assert recorded["status"] == "RECORDED"
    assert_instant(recorded["recorded_at"], "2026-08-01T00:00:00Z")

    after = validate_success(api.get_project(project["id"], sponsor_headers()))
    assert_instant(after["declaration_recorded_at"], "2026-08-01T00:00:00Z")
    assert_instant(after["warranty_start_at"], "2026-08-01T00:00:00Z")
    assert after["status"] == "REGISTRATION"
    assert after["posture"] == "RESTRICTED"


def test_record_declaration_with_unadopted_budget_returns_reserve_study_not_adopted(api):
    """PRD: Recording requires the project's initial budget to be `ADOPTED`, or the
    request fails with `ERR_RESERVE_STUDY_NOT_ADOPTED`.

    Design: Corner/state_machines/record_declaration_with_unadopted_budget_returns_reserve_study_not_adopted
    """
    project = make_project(api, "44 Cove Lane, Bangor ME", 1968, 2)
    gate = make_passed_gate(api, project["id"])
    package = make_package(api, project["id"], "PAINT_TO_PAINT", "decl-1", "bylaws-1")
    make_unit(api, package["id"], "101", 10000, 1, 900, "as-built")
    study = make_reserve_study(
        api, project["id"], gate["report"]["id"], "COMPONENT_METHOD", 0
    )
    budget = make_budget(api, project["id"], study["id"], 1000000)
    certify_plat(api, package["id"])

    validate_error(
        api.record_package(package["id"], sponsor_headers()),
        "ERR_RESERVE_STUDY_NOT_ADOPTED",
        expected_status=409,
    )
    assert validate_success(api.get_budget(budget["id"], sponsor_headers()))[
        "status"
    ] == "DRAFT"
    assert validate_success(api.get_reserve_study(study["id"], sponsor_headers()))[
        "adoption_status"
    ] == "PROPOSED"
    reread = validate_success(api.get_package(package["id"], sponsor_headers()))
    assert reread["status"] == "PLAT_CERTIFIED"
    assert reread["recorded_at"] is None
    after = validate_success(api.get_project(project["id"], sponsor_headers()))
    assert after["status"] == "DOCUMENTS_PREPARATION"
    assert after["declaration_recorded_at"] is None
    assert after["warranty_start_at"] is None


def test_withdrawing_the_last_included_unit_is_refused(api):
    """PRD: A withdrawal that would leave the package with no `INCLUDED` unit at all is
    refused with `ERR_LAST_INCLUDED_UNIT`.

    Design: Corner/validations/withdrawing_the_last_included_unit_is_refused
    """
    project = make_project(api, *STD_PROJECT)
    package = make_package(api, project["id"])
    first, second = make_units(
        api, package["id"], (("101", 5000), ("102", 5000))
    )

    withdrawn = validate_success(
        api.withdraw_unit(
            second["id"],
            sponsor_headers(),
            {"withdrawal_reason": "sponsor retains 102 as a rental"},
        )
    )
    assert withdrawn["declaration_status"] == "WITHDRAWN"
    assert withdrawn["percentage_interest_bp"] == 0
    assert validate_success(api.get_unit(first["id"], sponsor_headers()))[
        "percentage_interest_bp"
    ] == TOTAL_UNDIVIDED_INTEREST_BP
    assert validate_success(api.get_package(package["id"], sponsor_headers()))[
        "allocated_bp_total"
    ] == TOTAL_UNDIVIDED_INTEREST_BP
    assert validate_success(api.get_project(project["id"], sponsor_headers()))[
        "included_unit_count"
    ] == 1

    validate_error(
        api.withdraw_unit(
            first["id"],
            sponsor_headers(),
            {"withdrawal_reason": "sponsor changes plan entirely"},
        ),
        "ERR_LAST_INCLUDED_UNIT",
        expected_status=409,
    )
    survivor = validate_success(api.get_unit(first["id"], sponsor_headers()))
    assert survivor["declaration_status"] == "INCLUDED"
    assert survivor["percentage_interest_bp"] == TOTAL_UNDIVIDED_INTEREST_BP
    assert validate_success(api.get_package(package["id"], sponsor_headers()))[
        "allocated_bp_total"
    ] == TOTAL_UNDIVIDED_INTEREST_BP
    assert validate_success(api.get_project(project["id"], sponsor_headers()))[
        "included_unit_count"
    ] == 1


def test_life_safety_component_below_five_years_blocks_plat_certification(api):
    """PRD: no `MajorComponent` of the project's `ACCEPTED` engineering report may be at
    once `verification_status` `VERIFIED`, `is_life_safety` true and carrying
    `remaining_useful_life_years` strictly fewer than 5, and a component that breaches
    this is refused with `ERR_LIFE_SAFETY_COMPONENT_EXPIRED` (422).

    Design: Corner/validations/life_safety_component_below_five_years_blocks_plat_certification
    """
    project = make_project(api, "44 Cove Lane, Bangor ME", 1968, 2)
    gate = make_passed_gate(
        api,
        project["id"],
        (
            component_payload("ROOF", 30, 4, 2500000, 0, "EXCELLENT"),
            component_payload(
                "ELEVATOR",
                4,
                26,
                250000,
                0,
                "EXCELLENT",
                planned_remediation_gain_years=1,
                is_life_safety=True,
            ),
        ),
        variant="POST_REMEDIATION",
    )
    roof, elevator = gate["components"]
    assert validate_success(api.get_project(project["id"], sponsor_headers()))[
        "suitability_gate"
    ] == "PASSED"

    package = make_package(api, project["id"])
    unit = make_unit(api, package["id"], "101", 10000, 1, 900, "interior finish surfaces")

    validate_error(
        api.certify_plat(package["id"], sponsor_headers()),
        "ERR_LIFE_SAFETY_COMPONENT_EXPIRED",
        expected_status=422,
    )
    elevator_now = validate_success(api.get_component(elevator["id"], sponsor_headers()))
    assert elevator_now["verification_status"] == "VERIFIED"
    assert elevator_now["remaining_useful_life_years"] == 4
    assert validate_success(api.get_component(roof["id"], sponsor_headers()))[
        "verification_status"
    ] == "VERIFIED"
    assert validate_success(api.get_report(gate["report"]["id"], sponsor_headers()))[
        "status"
    ] == "ACCEPTED"
    reread = validate_success(api.get_package(package["id"], sponsor_headers()))
    assert reread["status"] == "DRAFT"
    assert reread["plat_revision"] == 0
    assert validate_success(api.get_unit(unit["id"], sponsor_headers()))[
        "declaration_status"
    ] == "INCLUDED"


def test_life_safety_component_at_exactly_five_years_certifies_the_plat(api):
    """PRD: the comparison is strict, so a life-safety component with exactly 5
    remaining years certifies without complaint while one with 4 does not.

    Design: Corner/validations/life_safety_component_at_exactly_five_years_certifies_the_plat
    """
    project = make_project(api, "44 Cove Lane, Bangor ME", 1968, 2)
    gate = make_passed_gate(
        api,
        project["id"],
        (
            component_payload("ROOF", 30, 4, 2500000, 0, "EXCELLENT"),
            component_payload(
                "ELEVATOR", 5, 25, 250000, 0, "EXCELLENT", is_life_safety=True
            ),
        ),
    )
    roof, elevator = gate["components"]
    assessment = validate_success(
        api.get_assessment(gate["assessment"]["id"], sponsor_headers())
    )
    assert_decimal_equals(assessment["score"], "92.42", "score")
    assert assessment["critical_cap_applied"] is False
    assert assessment["verdict"] == "PASSED"
    assert assessment["basis"] == "VERIFIED_COMPONENTS"
    project_now = validate_success(api.get_project(project["id"], sponsor_headers()))
    assert project_now["suitability_gate"] == "PASSED"
    assert_decimal_equals(project_now["suitability_score"], "92.42", "suitability_score")

    package = make_package(api, project["id"])
    make_unit(api, package["id"], "101", 10000, 1, 900, "interior finish surfaces")

    certified = validate_success(api.certify_plat(package["id"], sponsor_headers()))
    assert validate_success(api.get_component(elevator["id"], sponsor_headers()))[
        "remaining_useful_life_years"
    ] == 5
    assert validate_success(api.get_component(roof["id"], sponsor_headers()))[
        "verification_status"
    ] == "VERIFIED"
    assert certified["status"] == "PLAT_CERTIFIED"
    assert certified["allocated_bp_total"] == TOTAL_UNDIVIDED_INTEREST_BP
    assert certified["plat_revision"] == 0


def test_parent_path_existence_precedes_body_validation(api):
    """PRD: Rung 3 — existence of every referenced entity. Unknown ids in the path or
    the body fail with the entity's own not-found error at HTTP 404. Rung 4 — request
    shape.

    Design: Corner/validations/parent_path_existence_precedes_body_validation
    """
    project = make_project(api, *STD_PROJECT)
    package = make_package(api, project["id"])
    bad_body = unit_payload("101", 0)

    validate_error(
        api.create_unit(NON_EXISTENT_UUID, bad_body, sponsor_headers()),
        "ERR_DECLARATION_ARTIFACT_NOT_FOUND",
        expected_status=404,
    )
    validate_error(
        api.create_unit(package["id"], bad_body, sponsor_headers()),
        "ERR_INVALID_REQUEST",
        expected_status=422,
    )
    validate_error(
        api.create_package(NON_EXISTENT_UUID, package_payload(), sponsor_headers()),
        "ERR_PROJECT_NOT_FOUND",
        expected_status=404,
    )

    _, meta = validate_paginated(
        api.list_package_units(package["id"], sponsor_headers())
    )
    assert_page(meta, total_count=0)
    after = validate_success(api.get_package(package["id"], sponsor_headers()))
    assert after["allocated_bp_total"] == 0
    # `included_unit_count` is a ConversionProject field, not a package field.
    parent = validate_success(api.get_project(project["id"], sponsor_headers()))
    assert parent["included_unit_count"] == 0


def test_plat_certification_with_an_empty_included_set_is_refused(api):
    """PRD: the reallocation must balance, meaning the sum of
    `percentage_interest_bp` over `INCLUDED` units equals exactly `10000`, otherwise
    `ERR_PERCENTAGE_INTEREST_NOT_BALANCED` (409).

    Design: Corner/errors/plat_certification_with_an_empty_included_set_is_refused
    """
    project = make_project(api, *STD_PROJECT)
    gate = make_passed_gate(api, project["id"], [roof_standard()])
    assert_decimal_equals(gate["assessment"]["score"], "100.00")
    package = make_package(api, project["id"])

    # The PRD lists "the package must have at least one child unit whose
    # `declaration_status` is `INCLUDED`" as its own precondition, ahead of and
    # separate from the balance check, but assigns it no error id of its own.  An
    # empty `INCLUDED` set is therefore refusable either as that unnamed state
    # precondition or through the balance check it also fails (0 != 10000), and the
    # document does not choose between them.  What it does pin is the refusal at 409
    # leaving the package untouched.
    empty_set = api.certify_plat(package["id"], sponsor_headers())
    assert empty_set.status_code == 409, (
        "certifying an empty included set must be refused with 409, got %d"
        % empty_set.status_code
    )
    validate_error_is_one_of(
        empty_set,
        ["ERR_PERCENTAGE_INTEREST_NOT_BALANCED", "ERR_INVALID_STATE_TRANSITION"],
    )
    refused = validate_success(api.get_package(package["id"], sponsor_headers()))
    assert refused["status"] == "DRAFT"
    assert refused["plat_revision"] == 0

    # "for the plat to certify, the sum of `base_percentage_interest_bp` over all
    # sibling units must itself total 10000" — so the sole unit of a certifiable
    # package is declared at the full 10000 basis points.
    half = make_unit(api, package["id"], "101", 5000)
    validate_error(
        api.certify_plat(package["id"], sponsor_headers()),
        "ERR_PERCENTAGE_INTEREST_NOT_BALANCED",
        expected_status=409,
    )
    validate_success(
        api.patch_unit(half["id"], {"base_percentage_interest_bp": 10000}, sponsor_headers())
    )

    certified = validate_success(api.certify_plat(package["id"], sponsor_headers()))
    assert certified["status"] == "PLAT_CERTIFIED"
    assert certified["allocated_bp_total"] == 10000

    only_unit = validate_success(api.get_unit(half["id"], sponsor_headers()))
    assert only_unit["base_percentage_interest_bp"] == 10000
    assert only_unit["percentage_interest_bp"] == 10000
    parent = validate_success(api.get_project(project["id"], sponsor_headers()))
    assert parent["bp_conservation_total"] == 10000


def test_unit_list_filters_and_offset_compose_over_one_page(api):
    """PRD: Collection reads accept `limit` (1..100, default 10) and `offset`
    (default 0) and return `total_count`, `has_more`, `limit` and `offset` in
    `meta.pagination`.

    Design: Corner/endpoints/unit_list_filters_and_offset_compose_over_one_page
    """
    project = make_project(api, "44 Cove Lane, Bangor ME", 1968, 3)
    package = make_package(api, project["id"])
    u101 = make_unit(api, package["id"], "101", 3334, 1, 900, "interior finish surfaces")
    u102 = make_unit(api, package["id"], "102", 3333, 2, 900, "interior finish surfaces")
    u103 = make_unit(api, package["id"], "103", 3333, 3, 900, "interior finish surfaces")
    validate_success(
        api.withdraw_unit(
            u103["id"], sponsor_headers(), {"withdrawal_reason": "sponsor retains 103"}
        )
    )

    included = {"conversion_project_id": project["id"], "declaration_status": "INCLUDED"}
    page_one, meta_one = validate_paginated(
        api.list_units(regulator_headers(), params=dict(included, limit=1, offset=0))
    )
    assert_page(meta_one, total_count=2, limit=1, offset=0, has_more=True)
    assert len(page_one) == 1
    assert page_one[0]["id"] in (u101["id"], u102["id"])

    page_two, meta_two = validate_paginated(
        api.list_units(regulator_headers(), params=dict(included, limit=1, offset=1))
    )
    assert_page(meta_two, total_count=2, limit=1, offset=1, has_more=False)
    assert len(page_two) == 1
    assert page_two[0]["id"] != page_one[0]["id"]
    assert set(ids_of(page_one + page_two)) == {u101["id"], u102["id"]}
    assert u103["id"] not in ids_of(page_one + page_two)

    withdrawn, meta_three = validate_paginated(
        api.list_units(
            regulator_headers(),
            params={
                "conversion_project_id": project["id"],
                "declaration_status": "WITHDRAWN",
            },
        )
    )
    assert_page(meta_three, total_count=1)
    assert withdrawn[0]["id"] == u103["id"]
    assert withdrawn[0]["declaration_status"] == "WITHDRAWN"

    all_rows, meta_four = validate_paginated(
        api.list_package_units(package["id"], regulator_headers())
    )
    assert_page(meta_four, total_count=3, limit=10, offset=0, has_more=False)
    assert len(all_rows) == 3

    parent = validate_success(api.get_project(project["id"], regulator_headers()))
    assert parent["included_unit_count"] == 2
    plat = validate_success(api.get_package(package["id"], regulator_headers()))
    assert plat["allocated_bp_total"] == 10000


def test_withdrawal_reallocation_floors_then_sweeps_residual_by_fraction(api):
    """PRD: Each remaining `INCLUDED` unit receives the floor of its base share times
    `10000` divided by the surviving base total, and the residual basis points left by
    that flooring are handed out one at a time, largest fractional part first, ties
    broken by ascending `unit_number`.

    Design: Corner/calculations/withdrawal_reallocation_floors_then_sweeps_residual_by_fraction
    """
    project = make_project(api, "44 Cove Lane, Bangor ME", 1968, 3)
    package = make_package(api, project["id"], "PAINT_TO_PAINT", "decl-1", "bylaws-1")
    u1 = make_unit(api, package["id"], "101", 3333, 1, 900, "as-built")
    u2 = make_unit(api, package["id"], "102", 3333, 2, 900, "as-built")
    u3 = make_unit(api, package["id"], "103", 3334, 3, 920, "as-built")

    assert validate_success(api.get_unit(u1["id"], sponsor_headers()))[
        "percentage_interest_bp"
    ] == 3333
    assert validate_success(api.get_unit(u3["id"], sponsor_headers()))[
        "percentage_interest_bp"
    ] == 3334
    # A new package carries `allocated_bp_total` 0, and the reallocation sweep runs
    # only when a plat is certified or a unit is withdrawn or reinstated — defining
    # units seeds each unit's own `percentage_interest_bp` but does not sweep.
    assert validate_success(api.get_package(package["id"], sponsor_headers()))[
        "allocated_bp_total"
    ] == 0

    withdrawn = validate_success(
        api.withdraw_unit(
            u1["id"],
            sponsor_headers(),
            {"withdrawal_reason": "retained as sponsor rental"},
        )
    )
    assert withdrawn["declaration_status"] == "WITHDRAWN"
    assert withdrawn["percentage_interest_bp"] == 0
    assert withdrawn["base_percentage_interest_bp"] == 3333

    assert validate_success(api.get_unit(u2["id"], sponsor_headers()))[
        "percentage_interest_bp"
    ] == 4999
    assert validate_success(api.get_unit(u3["id"], sponsor_headers()))[
        "percentage_interest_bp"
    ] == 5001

    assert validate_success(api.get_package(package["id"], sponsor_headers()))[
        "allocated_bp_total"
    ] == 10000
    parent = validate_success(api.get_project(project["id"], sponsor_headers()))
    assert parent["bp_conservation_total"] == 10000
    assert parent["included_unit_count"] == 2


def test_undivided_share_bp_restored_byte_identically_by_withdraw_then_reinstate(api):
    """PRD: Reinstatement puts a `WITHDRAWN` unit back to `INCLUDED` and re-runs the same
    reallocation over the widened included set. Recertification of the plat is required
    afterwards because the package has fallen back to `DRAFT`.

    Design: Difficulty/compensating_invariant/undivided_share_bp_restored_byte_identically_by_withdraw_then_reinstate
    """
    project = make_project(api, "3 Lintel Way, Waltham MA", 1972, 3)
    make_passed_gate(
        api,
        project["id"],
        [
            component_payload(
                "FOUNDATION",
                40,
                20,
                10000000,
                5000,
                "EXCELLENT",
                planned_remediation_gain_years=0,
                is_life_safety=False,
                is_structural=True,
            )
        ],
        "ER-L",
    )
    package = make_package(
        api, project["id"], "STUD_TO_STUD", "s3://decl/lintel.pdf", "s3://bylaws/lintel.pdf"
    )
    u1 = make_unit(api, package["id"], "L-1", 3333, 1, 1000, "stud faces")
    u2 = make_unit(api, package["id"], "L-2", 3333, 2, 1000, "stud faces")
    u3 = make_unit(api, package["id"], "L-3", 3334, 3, 1010, "stud faces")
    certify_plat(api, package["id"])

    def read(unit_id):
        return validate_success(api.get_unit(unit_id, sponsor_headers()))

    first = [read(u1["id"]), read(u2["id"]), read(u3["id"])]
    assert [row["percentage_interest_bp"] for row in first] == [3333, 3333, 3334]
    assert sum(row["percentage_interest_bp"] for row in first) == 10000
    assert validate_success(api.get_project(project["id"], sponsor_headers()))[
        "bp_conservation_total"
    ] == 10000

    withdrawn = validate_success(
        api.withdraw_unit(
            u3["id"],
            sponsor_headers(),
            {
                "withdrawal_reason": (
                    "sponsor removed L-3 from the conversion after a title defect surfaced"
                )
            },
        )
    )
    assert withdrawn["declaration_status"] == "WITHDRAWN"

    rows, meta = validate_paginated(
        api.list_units(
            sponsor_headers(),
            params={
                "conversion_project_id": project["id"],
                "declaration_status": "INCLUDED",
            },
        )
    )
    assert_page(meta, total_count=2)
    assert len(rows) == 2
    assert read(u1["id"])["percentage_interest_bp"] == 5000
    assert read(u2["id"])["percentage_interest_bp"] == 5000
    gone = read(u3["id"])
    assert gone["percentage_interest_bp"] == 0
    assert gone["unit_annual_assessment_cents"] == 0
    assert gone["unit_monthly_assessment_cents"] == 0
    assert sum(row["percentage_interest_bp"] for row in rows) == 10000
    mid_project = validate_success(api.get_project(project["id"], sponsor_headers()))
    assert mid_project["bp_conservation_total"] == 10000
    assert mid_project["included_unit_count"] == 2
    assert mid_project["total_unit_count"] == 3

    reinstated = validate_success(api.reinstate_unit(u3["id"], sponsor_headers()))
    assert reinstated["declaration_status"] == "INCLUDED"

    third = [read(u1["id"]), read(u2["id"]), read(u3["id"])]
    assert [row["percentage_interest_bp"] for row in third] == [3333, 3333, 3334]
    assert [row["unit_annual_assessment_cents"] for row in third] == [
        row["unit_annual_assessment_cents"] for row in first
    ]
    assert sum(row["percentage_interest_bp"] for row in third) == 10000
    end_project = validate_success(api.get_project(project["id"], sponsor_headers()))
    assert end_project["bp_conservation_total"] == 10000
    assert end_project["included_unit_count"] == 3
    assert validate_success(api.get_package(package["id"], sponsor_headers()))[
        "status"
    ] == "DRAFT"


def test_unit_withdrawal_cascade_unit_agreement_escrow_batch_project(api):
    """PRD: Withdrawing a unit voids any live purchase agreement on that unit, refunds
    its escrow, re-evaluates any closing batch that held the agreement and forces the
    public offering statement into `AMENDMENT_REQUIRED`.

    Design: Difficulty/transitive_cascade/unit_withdrawal_cascade_unit_agreement_escrow_batch_project
    """
    built = build_registered_project(
        api,
        "12 Basalt Row, Quincy MA",
        1968,
        unit_specs=(("B-1", 5000), ("B-2", 5000)),
        components=[
            component_payload(
                "FOUNDATION",
                40,
                20,
                10000000,
                5000,
                "EXCELLENT",
                planned_remediation_gain_years=0,
                is_life_safety=False,
                is_structural=True,
            )
        ],
        annual_operating_expense_cents=875000,
        boundary_convention="PAINT_TO_PAINT",
        opening_reserve_balance_cents=0,
    )
    project, package, pos = built["project"], built["package"], built["pos"]
    u1, u2 = built["units"]

    agreement = make_agreement(
        api, u1["id"], "Frank Basalt", "TAX-OO-9", "OWNER_OCCUPANT", 24000000, 2400000
    )
    deliver_pos(api, agreement["id"])
    fund_escrow(api, agreement["id"], 2400000)
    set_clock(api, "2026-08-16T00:00:00Z")
    harden(api, agreement["id"])
    batch = make_batch(
        api,
        project["id"],
        1,
        "2026-08-16T00:00:00Z",
        "2026-09-16T00:00:00Z",
        50.00,
        1,
    )
    assign_agreement(api, batch["id"], agreement["id"])
    evaluate_threshold(api, batch["id"])
    release_batch(api, batch["id"])

    before_package = validate_success(api.get_package(package["id"], sponsor_headers()))
    assert before_package["status"] == "RECORDED"

    withdrawn = validate_success(
        api.withdraw_unit(
            u1["id"], sponsor_headers(), {"withdrawal_reason": "sponsor retains B-1 as a rental"}
        )
    )
    assert withdrawn["declaration_status"] == "WITHDRAWN"
    assert withdrawn["percentage_interest_bp"] == 0
    assert withdrawn["unit_annual_assessment_cents"] == 0
    assert withdrawn["unit_monthly_assessment_cents"] == 0

    voided = validate_success(api.get_agreement(agreement["id"], sponsor_headers()))
    assert voided["contract_status"] == "VOID"
    assert voided["escrow_status"] == "REFUNDED"

    short = validate_success(api.get_batch(batch["id"], sponsor_headers()))
    assert short["status"] == "THRESHOLD_SHORT"
    assert short["qualifying_agreement_count"] == 0
    assert_decimal_equals(short["presale_pct"], "0.00", "presale_pct")
    assert short["released_at"] is None

    assert validate_success(api.get_pos(pos["id"], sponsor_headers()))[
        "status"
    ] == "AMENDMENT_REQUIRED"

    survivor = validate_success(api.get_unit(u2["id"], sponsor_headers()))
    assert survivor["percentage_interest_bp"] == 10000
    assert survivor["unit_annual_assessment_cents"] == 1080000
    assert survivor["unit_monthly_assessment_cents"] == 90000

    after = validate_success(api.get_project(project["id"], sponsor_headers()))
    assert after["escrow_balance_cents"] == 0
    assert after["escrow_refunded_cents"] == 2400000
    assert after["escrow_deposits_received_cents"] == 2400000
    assert after["escrow_disbursed_cents"] == 0
    assert after["escrow_reconciliation_delta_cents"] == 0
    assert after["posture"] == "RESTRICTED"
    assert after["included_unit_count"] == 1
    assert after["bp_conservation_total"] == 10000
    assert after["total_unit_count"] == 2

    end_package = validate_success(api.get_package(package["id"], sponsor_headers()))
    assert end_package["status"] == "RECORDED"
    assert end_package["plat_revision"] == before_package["plat_revision"]
    end_budget = validate_success(api.get_budget(built["budget"]["id"], sponsor_headers()))
    assert end_budget["status"] == "ADOPTED"
    assert end_budget["total_annual_expense_cents"] == 1080000
