"""Breadth over the access-control layers: role gate, site scope, segregation of duties."""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_amount, assert_density
from test_helpers.factories import (
    aerial_survey_payload,
    cell_payload,
    closure_cost_estimate_payload,
    gas_well_payload,
    landfill_payload,
    liner_qa_package_payload,
    operating_day_payload,
)
from test_helpers.test_users import (
    CQA_ENGINEER_USER_ID,
    REGULATORY_AGENCY_USER_ID,
    TEST_USERS,
    make_cqa_engineer_headers,
    make_scale_operator_headers,
    make_site_operator_headers,
)

PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
CQA_ENGINEER = TEST_USERS["cqa_engineer_headers"]
SURVEYOR = TEST_USERS["surveyor_headers"]
ENV_MANAGER = TEST_USERS["environmental_manager_headers"]
AGENCY = TEST_USERS["regulatory_agency_headers"]
FINANCE_FILER = TEST_USERS["finance_filer_headers"]

FEE_SCHEDULE = {
    "community_name": "Ridgeview Township",
    "posted_tipping_fee_per_ton": 42.50,
    "host_fee_per_ton": 3.75,
    "tier1_monthly_tons": 100,
    "royalty_tier1_pct": 0.04,
    "royalty_tier2_pct": 0.07,
}
DAY_SHAPE = {
    "operating_date": "2026-08-01T00:00:00Z",
    "working_face_area_sf": 5000,
    "cover_material_type": "ALTERNATIVE_TARP",
}


def test_the_registration_and_construction_chain_runs_on_its_own_five_roles():
    """PlatformAdmin, SiteOperator, CqaEngineer, FinanceOfficer and the agency in sequence.

    PRD: "A `RegulatoryAgency` principal is the state solid-waste permitting authority, and is
    the only role that may authorize waste placement in a QA-certified cell."

    Design: Corner/rbac/each_declared_role_can_invoke_one_of_its_own_exclusive_operations
    """
    site = fixtures.setup_open_day(
        agreement_overrides=dict(FEE_SCHEDULE), day_overrides=dict(DAY_SHAPE)
    )

    assert site["cell"]["status"] == "ACTIVE"
    assert site["cell"]["authorized_by_agency_user_id"] == REGULATORY_AGENCY_USER_ID
    assert site["package"]["status"] == "APPROVED"
    assert site["package"]["submitted_by_user_id"] == site["landfill"]["id"], (
        "the entity-backed operator's own landfill id is stamped as the submitter"
    )
    assert site["package"]["reviewed_by_user_id"] == CQA_ENGINEER_USER_ID
    assert site["estimate"]["status"] == "CERTIFIED"
    assert site["landfill"]["financial_assurance_status"] == "FUNDED"
    assert site["agreement"]["status"] == "EXECUTED"
    assert site["day"]["status"] == "OPEN"


def test_the_surveyor_of_record_records_a_flight_and_reads_the_projection():
    """The licensed surveyor writes the survey and may read the derived projection.

    PRD: "A `SurveyorOfRecord` is the licensed surveyor who flies and certifies aerial
    topographic surveys and voids the ones flown on bad ground control."

    Design: Corner/rbac/each_declared_role_can_invoke_one_of_its_own_exclusive_operations
    """
    landfill = fixtures.create_landfill()
    fixtures.setup_qa_certified_cell(landfill["id"])

    survey = validate_success(
        api_client.create_aerial_survey(
            aerial_survey_payload(
                landfill["id"],
                flown_on="2026-08-01T00:00:00Z",
                coverage_period_start="2026-06-01T00:00:00Z",
                coverage_period_end="2026-07-31T00:00:00Z",
                measured_remaining_airspace_cy=900000,
                tons_placed_in_period=100000,
            ),
            SURVEYOR,
        ),
        201,
    )

    assert survey["status"] == "RECORDED"
    assert_amount(survey["airspace_consumed_in_period_cy"], 100000, "consumed in period")
    assert_density(survey["measured_density_tons_per_cy"], 1.0000, "measured density")
    projection = get_success_data(
        api_client.get_remaining_life_projection(landfill["id"], SURVEYOR)
    )
    assert projection["variant"] == "survey_based"
    assert_amount(projection["remaining_life_years"], 3.00, "remaining life")
    assert fixtures.read_landfill(landfill["id"])["operating_status"] == "OPEN"


def test_the_environmental_manager_opens_a_special_waste_profile():
    """Ruling on profiles belongs to the compliance manager and to nobody else.

    PRD: "An `EnvironmentalManager` is the site environmental compliance manager."

    Design: Corner/rbac/each_declared_role_can_invoke_one_of_its_own_exclusive_operations
    """
    landfill = fixtures.create_landfill()

    approval = fixtures.request_special_waste_approval(
        landfill["id"],
        generator_name="Northline Plating",
        waste_code="F006",
        profile_stream="INDUSTRIAL_SPECIAL",
        approved_tons_cap=500.00,
        effective_from="2026-07-01T00:00:00Z",
        expires_on="2026-12-31T00:00:00Z",
    )

    assert approval["status"] == "REQUESTED"
    assert approval["landfill_id"] == landfill["id"]
    assert_amount(approval["consumed_tons"], 0, "consumed tons")


def test_the_scale_house_attendant_receives_the_first_truck_of_the_day():
    """Inbound receipt is the ScaleOperator's own operation, on its own landfill id.

    PRD: "A `ScaleOperator` is the scale-house attendant for one specific site."

    Design: Corner/rbac/each_declared_role_can_invoke_one_of_its_own_exclusive_operations
    """
    site = fixtures.setup_open_day(
        agreement_overrides=dict(FEE_SCHEDULE), day_overrides=dict(DAY_SHAPE)
    )

    load = fixtures.receive_load(
        site["landfill"]["id"], site["day"]["id"], hauler_ref="H-1", manifest_tons=40.00
    )

    assert load["screening_status"] == "PENDING"
    assert load["billing_status"] == "UNBILLED"
    assert load["operating_day_id"] == site["day"]["id"]


def _site_with_a_submitted_package():
    """A cell in construction whose liner package is waiting for an independent reviewer."""
    landfill = fixtures.create_landfill()
    cell = fixtures.create_cell_under_construction(landfill["id"])
    package = fixtures.submit_liner_qa_package(landfill["id"], cell["id"])
    assert package["status"] == "SUBMITTED"
    return landfill, cell, package


def test_no_role_may_drive_an_operation_that_belongs_to_another_role():
    """Seven well-formed requests, each from the wrong role, each refused at the gate.

    PRD: "If both headers are well formed but the named role is not among the roles authorised
    for the addressed endpoint in §4, the request is refused with `ERR_ROLE_NOT_PERMITTED`
    (HTTP 403)."

    Design: Corner/rbac/roles_cannot_invoke_each_others_exclusive_operations
    """
    landfill, cell, package = _site_with_a_submitted_package()
    landfill_id = landfill["id"]
    version = fixtures.landfill_version(landfill_id)

    refusals = [
        api_client.create_cell(
            cell_payload(
                landfill_id,
                cell_code="C-9",
                design_airspace_cy=500000,
                design_area_sf=60000,
                liner_type="SINGLE_COMPOSITE",
            ),
            make_scale_operator_headers(landfill_id),
        ),
        api_client.approve_liner_qa_package(
            package["id"],
            {"certification_reference": "CQA-BAD"},
            make_site_operator_headers(landfill_id),
        ),
        api_client.create_landfill(
            landfill_payload(name="Rogue Site", permit_number="MSW-9999"), CQA_ENGINEER
        ),
        api_client.create_closure_cost_estimate(
            closure_cost_estimate_payload(landfill_id, version), ENV_MANAGER
        ),
        api_client.create_gas_well(
            gas_well_payload(cell["id"], well_code="W-9", depth_ft=70), FINANCE_FILER
        ),
        api_client.authorize_waste_placement(
            cell["id"], {"approval_reference": "RA-SELF"}, PLATFORM_ADMIN
        ),
        api_client.create_operating_day(
            operating_day_payload(
                landfill_id,
                cell["id"],
                operating_date="2026-08-01T00:00:00Z",
                working_face_area_sf=5000,
                cover_material_type="SOIL_6IN",
            ),
            AGENCY,
        ),
    ]

    for response in refusals:
        validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
    _rows, meta = validate_paginated(
        api_client.list_cells(AGENCY, {"landfill_id": landfill_id})
    )
    assert meta["total_count"] == 1, "no refused call created a cell"
    untouched = get_success_data(
        api_client.get_liner_qa_package(package["id"], CQA_ENGINEER)
    )
    assert untouched["status"] == "SUBMITTED"
    assert int(untouched["version"]) == int(package["version"])


def test_the_role_gate_answers_before_the_body_of_the_request_is_examined():
    """The survey body is also malformed, and the role error is still the one reported.

    PRD: "These two checks run before anything else in the system, ahead of body parsing and
    ahead of any lookup."

    Design: Corner/rbac/roles_cannot_invoke_each_others_exclusive_operations
    """
    landfill, _cell, _package = _site_with_a_submitted_package()

    response = api_client.create_aerial_survey(
        aerial_survey_payload(
            landfill["id"],
            flown_on="2026-08-01T00:00:00Z",
            coverage_period_start="2026-06-01T00:00:00Z",
            coverage_period_end="2026-05-01T00:00:00Z",
            measured_remaining_airspace_cy=900000,
            tons_placed_in_period=100000,
        ),
        PLATFORM_ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
    _rows, meta = validate_paginated(
        api_client.list_aerial_surveys(SURVEYOR, {"landfill_id": landfill["id"]})
    )
    assert meta["total_count"] == 0


SECOND_SITE = {
    "name": "Eastvale MSW",
    "permit_number": "MSW-5520",
    "permitted_total_airspace_cy": 4000000,
    "design_footprint_sf": 300000,
    "planned_density_tons_per_cy": 0.88,
    "annual_tonnage_forecast": 250000,
}


def _two_sites_with_one_cell_on_the_first():
    """LF-A owns cell C-A; LF-B is only ever used as the acting operator identity."""
    lfa = fixtures.create_landfill()
    lfb = fixtures.create_landfill(**SECOND_SITE)
    cell = fixtures.create_cell(lfa["id"], cell_code="C-A")
    assert cell["landfill_id"] == lfa["id"]
    return lfa, lfb, cell


def test_an_operator_of_one_site_cannot_write_against_another_site():
    """Direct, path-resolved and one-hop-transitive scope are all enforced.

    PRD: "**Site scope**: because `SiteOperator` and `ScaleOperator` are entity-backed, every
    *write* they perform must address a resource whose owning landfill is the landfill named by
    `X-User-ID` — directly through a `landfill_id`, or transitively through the `landfill_id`
    of the cell, operating day or treatment agreement involved."

    Design: Corner/rbac/entity_backed_roles_cannot_write_against_another_landfill
    """
    lfa, lfb, cell = _two_sites_with_one_cell_on_the_first()
    intruder = make_site_operator_headers(lfb["id"])

    by_body = api_client.create_cell(
        cell_payload(
            lfa["id"],
            cell_code="C-A2",
            design_airspace_cy=400000,
            design_area_sf=50000,
            liner_type="SINGLE_COMPOSITE",
        ),
        intruder,
    )
    by_path = api_client.begin_cell_construction(cell["id"], intruder)
    by_reference = api_client.create_liner_qa_package(
        liner_qa_package_payload(cell["id"]), intruder
    )

    for response in (by_body, by_path, by_reference):
        validate_error(response, ApiErrorId.ERR_SITE_SCOPE_VIOLATION.value, 403)
    _rows, meta = validate_paginated(api_client.list_cells(AGENCY, {"landfill_id": lfa["id"]}))
    assert meta["total_count"] == 1, "the refused creation stored nothing"


def test_the_same_out_of_scope_identity_may_still_read_and_the_owner_may_still_write():
    """Scope guards writes only, and the refusals consumed nothing on the way through.

    PRD: "Read endpoints are deliberately *not* site-scoped: any of the eight roles may read
    any resource."

    Design: Corner/rbac/entity_backed_roles_cannot_write_against_another_landfill
    """
    lfa, lfb, cell = _two_sites_with_one_cell_on_the_first()
    api_client.begin_cell_construction(cell["id"], make_site_operator_headers(lfb["id"]))

    outsider_read = get_success_data(
        api_client.get_cell(cell["id"], make_scale_operator_headers(lfb["id"]))
    )

    assert outsider_read["status"] == "DESIGN"
    started = fixtures.begin_construction(lfa["id"], cell["id"])
    assert started["status"] == "UNDER_CONSTRUCTION"
    assert int(started["version"]) == int(cell["version"]) + 1


def test_the_operator_who_submitted_a_liner_package_cannot_open_its_review():
    """The forbidden reviewer id is data: it is the submitting landfill's own id.

    PRD: "The engineer who opens review may not be the person recorded in
    `submitted_by_user_id`; an attempt is refused with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/the_submitter_of_a_liner_package_cannot_review_it
    """
    landfill, _cell, package = _site_with_a_submitted_package()
    assert package["submitted_by_user_id"] == landfill["id"]

    response = api_client.begin_liner_qa_review(
        package["id"], make_cqa_engineer_headers(landfill["id"])
    )

    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    unchanged = get_success_data(api_client.get_liner_qa_package(package["id"], CQA_ENGINEER))
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["reviewed_by_user_id"] is None
    assert int(unchanged["version"]) == int(package["version"])


def test_the_bar_also_covers_returning_and_approving_the_package():
    """An independent engineer holds the review, and the submitter is still locked out.

    PRD: "The same prohibition applies to returning and to approving the package, so a single
    individual can never carry a liner from submission through to certification."

    Design: Corner/rbac/the_submitter_of_a_liner_package_cannot_review_it
    """
    landfill, _cell, package = _site_with_a_submitted_package()
    under_review = fixtures.begin_liner_review(package["id"])
    assert under_review["status"] == "UNDER_REVIEW"
    assert under_review["reviewed_by_user_id"] == CQA_ENGINEER_USER_ID
    submitter_as_engineer = make_cqa_engineer_headers(landfill["id"])

    returned = api_client.return_liner_qa_package(
        package["id"],
        {"return_note": "Panel 17 destructive test log missing"},
        submitter_as_engineer,
    )
    approved = api_client.approve_liner_qa_package(
        package["id"], {"certification_reference": "CQA-2026-01"}, submitter_as_engineer
    )

    for response in (returned, approved):
        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    still_open = get_success_data(api_client.get_liner_qa_package(package["id"], CQA_ENGINEER))
    assert still_open["status"] == "UNDER_REVIEW"
    assert still_open["certification_reference"] is None


def test_an_independent_engineer_carries_the_package_through_to_certification():
    """With the submitter excluded, the approval runs and the cell is certified.

    PRD: "Three preconditions apply, and they are checked in the ladder order of §2.9: the
    package must be in `UNDER_REVIEW`; the approver's `X-User-ID` must differ from
    `submitted_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`; and the `qa_conformance_score`
    must be at least 85.0, where exactly 85.0 passes, else `ERR_QA_SCORE_BELOW_THRESHOLD`."

    Design: Corner/rbac/the_submitter_of_a_liner_package_cannot_review_it
    """
    _landfill, cell, package = _site_with_a_submitted_package()
    fixtures.begin_liner_review(package["id"])

    certified = fixtures.approve_liner_package(package["id"], "CQA-2026-01")

    assert certified["status"] == "APPROVED"
    assert certified["certification_reference"] == "CQA-2026-01"
    assert float(certified["qa_conformance_score"]) >= 85.0
    parent = get_success_data(api_client.get_cell(cell["id"], AGENCY))
    assert parent["status"] == "QA_CERTIFIED"
