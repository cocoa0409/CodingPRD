"""Entity surface: what a create echoes, what a read exposes, what a listing counts,
which inputs are required, which defaults apply, and which fields the server owns."""

from __future__ import annotations

from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_camp,
    assert_medication_record,
    assert_pct,
    assert_standards_set,
    find_by,
)
from test_helpers.constants import DEFAULT_CLOCK
from test_helpers.factories import visit_assignment_payload
from test_helpers.test_users import OFFICER_ONE_HEADERS, make_camp_director_headers
from test_helpers.types import (
    AccreditationStatus,
    AdministeredByRole,
    CampType,
    ComplianceFlag,
    CompliancePosture,
    CycleStatus,
    HealthIntakeStatus,
    HealthStaffingLevel,
    MedicationClass,
    MedRecordStatus,
    PopulationServed,
    ProgramElement,
    RiskIndexVariant,
    StandardDomain,
    StandardsSetStatus,
    StateLicenseStatus,
    TeamRole,
)
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_registering_a_camp_echoes_its_inputs_and_stamps_the_required_staffing_level(api):
    """PRD §3.1: "Registration also fixes the camp's derived state. `state_license_number`
    is null until a licensing agent supplies one, `state_license_status` starts at `NONE`,
    `accreditation_status` at `NOT_ACCREDITED`, `penalty_point_balance` at 0,
    `health_intake_status` at `OPEN`, both `controlled_intake_units` and
    `controlled_on_hand_units` at 0, `last_accredited_year` null, and `risk_index_variant`
    at `PRE_VISIT`. The server then computes `required_health_staffing_level`, the
    compliance posture, and the risk index under its pre-visit variant."

    Design: Corner/entities/camp_creation_returns_every_input_field_plus_derived_staffing_requirement
    """
    fx.set_clock(api, DEFAULT_CLOCK)

    camp = validate_success(
        api.create_camp(
            {
                "name": "Pine Hollow Resident Camp",
                "camp_type": CampType.RESIDENT,
                "state_code": "OH",
                "population_served": PopulationServed.MEDICALLY_FRAGILE,
                "program_elements": [ProgramElement.AQUATICS_OPEN_WATER],
                "resident_census": 200,
                "distance_to_hospital_km": 45,
                "max_daily_census": 240,
                "health_staffing_level": HealthStaffingLevel.RN_ONSITE,
            },
            OFFICER_ONE_HEADERS,
        ),
        201,
    )
    assert_camp(camp)
    assert is_valid_uuid(camp["id"])

    assert camp["camp_type"] == CampType.RESIDENT
    assert camp["population_served"] == PopulationServed.MEDICALLY_FRAGILE
    assert camp["resident_census"] == 200
    assert camp["distance_to_hospital_km"] == 45
    assert camp["max_daily_census"] == 240
    assert camp["health_staffing_level"] == HealthStaffingLevel.RN_ONSITE

    # Components 3, 4, 3, 3 and 3: the largest is 4 and the cap holds the bump at 4.
    assert camp["required_health_staffing_level"] == HealthStaffingLevel.PHYSICIAN_ONSITE
    assert camp["compliance_posture"] == CompliancePosture.RESTRICTED
    assert camp["health_intake_status"] == HealthIntakeStatus.OPEN

    # (10 base + 8 open-water programme + 15 staffing gap + 6 unlicensed) x 1.4.
    assert_pct(camp["risk_index"], 54.60)
    assert camp["risk_index_variant"] == RiskIndexVariant.PRE_VISIT

    assert camp["accreditation_status"] == AccreditationStatus.NOT_ACCREDITED
    assert camp["state_license_status"] == StateLicenseStatus.NONE
    assert camp["state_license_number"] is None
    assert camp["version"] == 1


def test_reading_a_camp_back_reports_both_status_axes_and_the_zeroed_ledgers(api):
    """PRD §2.7: "A camp record carries two lifecycle axes that never read or write each
    other."

    Design: Corner/entities/camp_retrieval_returns_the_stored_row_with_both_status_axes
    """
    fx.set_clock(api, DEFAULT_CLOCK)
    created = validate_success(
        api.create_camp(
            {
                "name": "Willow Day Camp",
                "camp_type": CampType.DAY,
                "state_code": "OH",
                "population_served": PopulationServed.YOUTH_ONLY,
                "health_staffing_level": HealthStaffingLevel.FIRST_AIDER_ONLY,
            },
            OFFICER_ONE_HEADERS,
        ),
        201,
    )

    camp = fx.read_camp(api, created["id"])
    assert camp["id"] == created["id"]
    assert camp["accreditation_status"] == AccreditationStatus.NOT_ACCREDITED
    assert camp["state_license_status"] == StateLicenseStatus.NONE

    assert camp["penalty_point_balance"] == 0
    assert camp["controlled_intake_units"] == 0
    assert camp["controlled_on_hand_units"] == 0
    assert camp["last_accredited_year"] is None

    assert camp["compliance_posture"] == CompliancePosture.OPEN
    assert camp["health_intake_status"] == HealthIntakeStatus.OPEN
    assert camp["required_health_staffing_level"] == HealthStaffingLevel.FIRST_AIDER_ONLY

    assert_pct(camp["risk_index"], 16.00)
    assert camp["risk_index_variant"] == RiskIndexVariant.PRE_VISIT


def test_camp_listing_counts_the_filtered_set_and_composes_two_filters(api):
    """PRD §2.3: "Every list response echoes `limit`, `offset`, `total_count` and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/camp_listing_filters_by_state_code_and_paginates_by_offset
    """
    for name, camp_type, state_code in (
        ("OH Camp One", CampType.DAY, "OH"),
        ("OH Camp Two", CampType.DAY, "OH"),
        ("OH Camp Three", CampType.RESIDENT, "OH"),
        ("PA Camp One", CampType.DAY, "PA"),
    ):
        fx.register_camp(api, name=name, camp_type=camp_type, state_code=state_code)

    first_page, first_meta = validate_paginated(
        api.list_camps({"state_code": "OH", "limit": 2, "offset": 0}, OFFICER_ONE_HEADERS)
    )
    assert len(first_page) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0

    second_page, second_meta = validate_paginated(
        api.list_camps({"state_code": "OH", "limit": 2, "offset": 2}, OFFICER_ONE_HEADERS)
    )
    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False

    day_camps, day_meta = validate_paginated(
        api.list_camps(
            {"state_code": "OH", "camp_type": CampType.DAY}, OFFICER_ONE_HEADERS
        )
    )
    assert len(day_camps) == 2
    assert day_meta["total_count"] == 2

    for rows in (first_page, second_page, day_camps):
        assert find_by(rows, name="PA Camp One") is None


def test_each_entity_read_owns_its_own_not_found_error_id(api):
    """PRD §2.5: "a camp reached through `campId` or a `camp_id` body field yields
    `ERR_CAMP_NOT_FOUND`; then a standards edition reached through `setId` or
    `standards_set_id` yields `ERR_STANDARDS_SET_NOT_FOUND`; then `standardId` yields
    `ERR_STANDARD_NOT_FOUND`; then a cycle reached through `cycleId` or `cycle_id` yields
    `ERR_CYCLE_NOT_FOUND`; then `evaluationId` yields `ERR_EVALUATION_NOT_FOUND`; then a
    plan reached through `planId` or `written_plan_id` yields `ERR_WRITTEN_PLAN_NOT_FOUND`;
    then a visitor reached through `visitorId` or `visitor_id` yields
    `ERR_VISITOR_NOT_FOUND`; then a visit reached through `visitId` or `visit_id` yields
    `ERR_VISIT_NOT_FOUND`; then `assignmentId` yields `ERR_ASSIGNMENT_NOT_FOUND`; then
    `deficiencyId` yields `ERR_DEFICIENCY_NOT_FOUND`; then `recordId` yields
    `ERR_MED_RECORD_NOT_FOUND`; then a report reached through `reportId` or
    `annual_report_id` yields `ERR_ANNUAL_REPORT_NOT_FOUND`; and finally `disclosureId`
    yields `ERR_DISCLOSURE_NOT_FOUND`."

    Design: Corner/entities/unknown_uuids_on_every_entity_read_return_that_entitys_not_found_error
    """
    reads = [
        (api.get_camp, ApiErrorId.CAMP_NOT_FOUND),
        (api.get_standards_set, ApiErrorId.STANDARDS_SET_NOT_FOUND),
        (api.get_standard, ApiErrorId.STANDARD_NOT_FOUND),
        (api.get_cycle, ApiErrorId.CYCLE_NOT_FOUND),
        (api.get_evaluation, ApiErrorId.EVALUATION_NOT_FOUND),
        (api.get_written_plan, ApiErrorId.WRITTEN_PLAN_NOT_FOUND),
        (api.get_visitor, ApiErrorId.VISITOR_NOT_FOUND),
        (api.get_visit, ApiErrorId.VISIT_NOT_FOUND),
        (api.get_visit_assignment, ApiErrorId.ASSIGNMENT_NOT_FOUND),
        (api.get_deficiency, ApiErrorId.DEFICIENCY_NOT_FOUND),
        (api.get_medication_record, ApiErrorId.MED_RECORD_NOT_FOUND),
        (api.get_annual_report, ApiErrorId.ANNUAL_REPORT_NOT_FOUND),
        (api.get_incident_disclosure, ApiErrorId.DISCLOSURE_NOT_FOUND),
    ]
    for read, error_id in reads:
        validate_error(read(NON_EXISTENT_UUID, OFFICER_ONE_HEADERS), error_id, 404)


def test_only_the_inputs_without_a_declared_default_are_required(api):
    """PRD §2.5: "**Schema** — the body parses, every required input field is present and
    non-null, every enum value belongs to its declared domain, integers declared
    non-negative are non-negative, calendar dates are ISO 8601 dates and instants are ISO
    8601 UTC timestamps: `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/camp_and_visitor_creation_missing_required_input_returns_invalid_request
    """
    no_name = api.create_camp(
        {
            "camp_type": CampType.DAY,
            "state_code": "OH",
            "population_served": PopulationServed.YOUTH_ONLY,
        },
        OFFICER_ONE_HEADERS,
    )
    validate_error(no_name, ApiErrorId.INVALID_REQUEST, 400)

    no_type = api.create_camp(
        {
            "name": "No Type Camp",
            "state_code": "OH",
            "population_served": PopulationServed.YOUTH_ONLY,
        },
        OFFICER_ONE_HEADERS,
    )
    validate_error(no_type, ApiErrorId.INVALID_REQUEST, 400)

    no_training_year = api.create_visitor(
        {"full_name": "Dana Reed", "home_state_code": "PA"}, OFFICER_ONE_HEADERS
    )
    validate_error(no_training_year, ApiErrorId.INVALID_REQUEST, 400)

    minimal = validate_success(
        api.create_camp(
            {
                "name": "Minimal Camp",
                "camp_type": CampType.DAY,
                "state_code": "OH",
                "population_served": PopulationServed.YOUTH_ONLY,
            },
            OFFICER_ONE_HEADERS,
        ),
        201,
    )
    assert minimal["name"] == "Minimal Camp"


def test_omitted_optional_camp_inputs_take_their_declared_defaults(api):
    """PRD §3.1: "`resident_census` (peak overnight camper count), `max_daily_census`
    (maximum campers on site on any single day) and `distance_to_hospital_km` (road
    distance from the health centre to the nearest emergency department) each default to 0
    and may not be negative. `health_staffing_level` records the staffing actually provided
    and defaults to `NONE`."

    Design: Corner/entities/camp_creation_omitting_optional_inputs_applies_declared_defaults
    """
    fx.set_clock(api, DEFAULT_CLOCK)
    camp = validate_success(
        api.create_camp(
            {
                "name": "Bare Defaults Camp",
                "camp_type": CampType.DAY,
                "state_code": "OH",
                "population_served": PopulationServed.YOUTH_ONLY,
            },
            OFFICER_ONE_HEADERS,
        ),
        201,
    )
    assert camp["program_elements"] == []
    assert camp["resident_census"] == 0
    assert camp["distance_to_hospital_km"] == 0
    assert camp["max_daily_census"] == 0
    assert camp["prior_accredited_cycle_count"] == 0
    assert camp["health_staffing_level"] == HealthStaffingLevel.NONE

    # Rank 0 provided against rank 1 demanded, so the gap clause fires on the defaults.
    assert camp["required_health_staffing_level"] == HealthStaffingLevel.FIRST_AIDER_ONLY
    assert camp["compliance_posture"] == CompliancePosture.RESTRICTED
    assert_pct(camp["risk_index"], 31.00)


def test_client_supplied_values_for_computed_camp_fields_are_discarded(api):
    """PRD §2.7: "`accreditation_status` is the national office's axis and takes one of
    `NOT_ACCREDITED`, `ACCREDITED`, `ACCREDITED_WITH_CORRECTION`, `PROVISIONAL` or
    `REVOKED`; it starts at `NOT_ACCREDITED` and moves only through cycle decisions,
    correction clearances and escalations."

    Design: Corner/entities/computed_and_system_camp_fields_ignore_extra_field_client_values
    """
    fx.set_clock(api, DEFAULT_CLOCK)
    camp = validate_success(
        api.create_camp(
            {
                "name": "Overreach Camp",
                "camp_type": CampType.DAY,
                "state_code": "OH",
                "population_served": PopulationServed.YOUTH_ONLY,
                "health_staffing_level": HealthStaffingLevel.FIRST_AIDER_ONLY,
                "penalty_point_balance": 99,
                "accreditation_status": AccreditationStatus.ACCREDITED,
                "risk_index": 1.00,
                "compliance_posture": CompliancePosture.OPEN,
                "state_license_status": StateLicenseStatus.ACTIVE,
                "controlled_on_hand_units": 500,
            },
            OFFICER_ONE_HEADERS,
        ),
        201,
    )
    assert camp["penalty_point_balance"] == 0
    assert camp["controlled_on_hand_units"] == 0
    assert camp["controlled_intake_units"] == 0
    assert camp["accreditation_status"] == AccreditationStatus.NOT_ACCREDITED
    assert camp["state_license_status"] == StateLicenseStatus.NONE
    assert_pct(camp["risk_index"], 16.00)
    assert camp["compliance_posture"] == CompliancePosture.OPEN


def test_edition_status_and_published_at_are_server_owned_across_both_writes(api):
    """PRD §3.2: "A new edition begins with `status` `DRAFT`, a null `published_at`, and
    both `standard_count` and `mandatory_count` at 0."

    Design: Corner/entities/standards_set_system_fields_are_server_generated_and_version_increments_on_publish
    """
    fx.set_clock(api, DEFAULT_CLOCK)

    edition = fx.create_edition(api, "ACA-2026-SYS")
    assert_standards_set(edition)
    assert edition["status"] == StandardsSetStatus.DRAFT
    assert edition["published_at"] is None
    assert edition["standard_count"] == 0
    assert edition["mandatory_count"] == 0
    assert edition["version"] == 1
    assert is_iso8601_timestamp(edition["created_at"])
    assert is_iso8601_timestamp(edition["updated_at"])

    fx.add_standard(
        api,
        edition["id"],
        code="SU.1",
        title="Supervision ratios",
        domain=StandardDomain.SUPERVISION,
        mandatory=True,
        scoring_weight=1,
    )
    with_standard = fx.read_edition(api, edition["id"])
    assert with_standard["standard_count"] == 1
    assert with_standard["mandatory_count"] == 1
    assert with_standard["version"] == 2

    published = fx.publish_edition(api, edition["id"])
    assert published["status"] == StandardsSetStatus.PUBLISHED
    assert is_iso8601_timestamp(published["published_at"])
    assert published["published_at"].startswith("2026-08-01T00:00:00")
    assert published["version"] == 3


def test_enum_membership_and_declared_ranges_are_rejected_at_the_schema_gate(api):
    """PRD §3.5: "An `AccreditationOfficer` adds a visitor with a `full_name` of 1 to 120
    characters, a two-uppercase-letter `home_state_code`, and a `trained_through_year`
    between 2000 and 2100 naming the last calendar year for which the visitor's ACA
    training is current."

    Design: Corner/entities/camp_and_visitor_enum_and_range_inputs_rejected_as_invalid_enum
    """
    bad_type = api.create_camp(
        {
            "name": "Bad Type Camp",
            "camp_type": "OVERNIGHT",
            "state_code": "OH",
            "population_served": PopulationServed.YOUTH_ONLY,
        },
        OFFICER_ONE_HEADERS,
    )
    validate_error(bad_type, ApiErrorId.INVALID_REQUEST, 400)

    negative_census = api.create_camp(
        {
            "name": "Negative Census Camp",
            "camp_type": CampType.DAY,
            "state_code": "OH",
            "population_served": PopulationServed.YOUTH_ONLY,
            "resident_census": -5,
        },
        OFFICER_ONE_HEADERS,
    )
    validate_error(negative_census, ApiErrorId.INVALID_REQUEST, 400)

    bad_element = api.create_camp(
        {
            "name": "Bad Element Camp",
            "camp_type": CampType.DAY,
            "state_code": "OH",
            "population_served": PopulationServed.YOUTH_ONLY,
            "program_elements": ["ARCHERY"],
        },
        OFFICER_ONE_HEADERS,
    )
    validate_error(bad_element, ApiErrorId.INVALID_REQUEST, 400)

    bad_year = api.create_visitor(
        {
            "full_name": "Time Traveller",
            "home_state_code": "PA",
            "trained_through_year": 1999,
        },
        OFFICER_ONE_HEADERS,
    )
    validate_error(bad_year, ApiErrorId.INVALID_REQUEST, 400)

    _camps, camp_meta = validate_paginated(api.list_camps({}, OFFICER_ONE_HEADERS))
    assert camp_meta["total_count"] == 0
    _visitors, visitor_meta = validate_paginated(api.list_visitors({}, OFFICER_ONE_HEADERS))
    assert visitor_meta["total_count"] == 0


def test_opening_a_cycle_materialises_only_the_pinned_editions_standards(api):
    """PRD §3.3: "Opening the cycle materialises exactly one standard evaluation row for
    every standard belonging to the pinned edition, regardless of the order in which those
    standards were created."

    Design: Corner/entities/cycle_creation_materialises_one_evaluation_per_standard_of_the_pinned_parent_set
    """
    fx.set_clock(api, DEFAULT_CLOCK)
    camp = fx.register_camp(
        api,
        name="Parent Scope Camp",
        max_daily_census=0,
        health_staffing_level=HealthStaffingLevel.FIRST_AIDER_ONLY,
    )

    pinned, pinned_standards = fx.publish_edition_with_standards(
        api,
        "ACA-2026-PIN",
        [
            {
                "code": "SU.1",
                "title": "Supervision ratios",
                "domain": StandardDomain.SUPERVISION,
                "mandatory": True,
                "scoring_weight": 3,
            },
            {
                "code": "OM.4",
                "title": "Operations records",
                "domain": StandardDomain.OPERATIONS,
                "mandatory": False,
                "scoring_weight": 1,
            },
            {
                "code": "PA.2",
                "title": "Open water swim area",
                "domain": StandardDomain.AQUATICS,
                "mandatory": True,
                "scoring_weight": 2,
                "requires_program_elements_any": [ProgramElement.AQUATICS_OPEN_WATER],
            },
        ],
    )
    fx.publish_edition_with_standards(
        api,
        "ACA-2026-RIVAL",
        [
            {
                "code": "RV.1",
                "title": "Rival edition standard one",
                "domain": StandardDomain.SUPERVISION,
                "mandatory": True,
                "scoring_weight": 5,
            },
            {
                "code": "RV.2",
                "title": "Rival edition standard two",
                "domain": StandardDomain.OPERATIONS,
                "mandatory": True,
                "scoring_weight": 5,
            },
        ],
    )

    fresh = fx.read_camp(api, camp["id"])
    cycle = fx.open_cycle(api, camp["id"], pinned["id"], 2026, fresh["version"])
    assert cycle["standards_set_id"] == pinned["id"]
    assert cycle["status"] == CycleStatus.SELF_ASSESSMENT

    rows, meta = validate_paginated(
        api.list_evaluations({"cycle_id": cycle["id"]}, OFFICER_ONE_HEADERS)
    )
    assert meta["total_count"] == 3

    pinned_ids = {standard["id"] for standard in pinned_standards.values()}
    assert {row["standard_id"] for row in rows} == pinned_ids

    by_standard = {row["standard_id"]: row for row in rows}
    assert by_standard[pinned_standards["PA.2"]["id"]]["applicable"] is False
    assert by_standard[pinned_standards["SU.1"]["id"]]["applicable"] is True
    assert by_standard[pinned_standards["OM.4"]["id"]]["applicable"] is True

    assert cycle["applicable_standard_count"] == 2
    assert cycle["applicable_mandatory_count"] == 1

    for code, mandatory, weight in (("SU.1", True, 3), ("OM.4", False, 1), ("PA.2", True, 2)):
        row = by_standard[pinned_standards[code]["id"]]
        assert row["mandatory"] is mandatory
        assert row["scoring_weight"] == weight


def test_unresolvable_body_foreign_keys_404_ahead_of_every_business_rule(api):
    """PRD §2.5: "**Existence** — identifiers are resolved strictly left to right along the
    URL path first and then in the order the body fields are listed below."

    Design: Corner/entities/flat_topology_cross_collection_foreign_keys_are_validated_not_found_before_body_rules
    """
    edition, _standards = fx.publish_edition_with_standards(
        api,
        "ACA-2026-FK",
        [fx.universal_mandatory_standard("SU.1", domain=StandardDomain.SUPERVISION)],
    )

    unknown_camp = api.create_cycle(
        {
            "camp_id": NON_EXISTENT_UUID,
            "standards_set_id": edition["id"],
            "cycle_year": 2026,
            "expected_camp_version": 99,
        },
        OFFICER_ONE_HEADERS,
    )
    validate_error(unknown_camp, ApiErrorId.CAMP_NOT_FOUND, 404)

    seated_visitor = fx.add_visitor(api, full_name="Roster One", home_state_code="NY")
    unknown_visit = api.create_visit_assignment(
        visit_assignment_payload(
            NON_EXISTENT_UUID, seated_visitor["id"], TeamRole.LEAD, "2026-09-01", "2026-09-03"
        ),
        OFFICER_ONE_HEADERS,
    )
    validate_error(unknown_visit, ApiErrorId.VISIT_NOT_FOUND, 404)

    unknown_report = api.create_incident_disclosure(
        {
            "annual_report_id": NON_EXISTENT_UUID,
            "incident_type": "SERIOUS_INJURY",
            "occurred_at": "2026-07-04T15:00:00.000Z",
        },
        make_camp_director_headers(NON_EXISTENT_UUID),
    )
    validate_error(unknown_report, ApiErrorId.ANNUAL_REPORT_NOT_FOUND, 404)

    for lister in (api.list_cycles, api.list_visit_assignments, api.list_incident_disclosures):
        _rows, meta = validate_paginated(lister({}, OFFICER_ONE_HEADERS))
        assert meta["total_count"] == 0


def test_compliance_flag_is_stamped_from_the_class_and_the_witness_flag(api):
    """PRD §3.9: "A record is created with `record_status` `RECORDED`, `void_reason` null,
    and a `compliance_flag` stamped at creation: `DOCUMENTATION_INCOMPLETE` when the
    `medication_class` is `PRESCRIPTION` and `second_signature_present` is false, and
    `COMPLIANT` in every other case."

    Design: Corner/entities/medication_record_creation_stamps_compliance_flag_from_class_and_signature
    """
    fx.set_clock(api, DEFAULT_CLOCK)
    camp = fx.register_camp(
        api,
        name="Med Flag Camp",
        max_daily_census=0,
        health_staffing_level=HealthStaffingLevel.RN_ONSITE,
    )

    unwitnessed_rx = fx.administer_medication(
        api,
        camp["id"],
        camper_reference="CR-01",
        medication_class=MedicationClass.PRESCRIPTION,
        dose_units=1,
        administered_at="2026-08-01T09:00:00.000Z",
        administered_by_role=AdministeredByRole.RN,
    )
    assert_medication_record(unwitnessed_rx)
    assert unwitnessed_rx["compliance_flag"] == ComplianceFlag.DOCUMENTATION_INCOMPLETE
    assert unwitnessed_rx["record_status"] == MedRecordStatus.RECORDED

    witnessed_rx = fx.administer_medication(
        api,
        camp["id"],
        camper_reference="CR-01",
        medication_class=MedicationClass.PRESCRIPTION,
        dose_units=1,
        administered_at="2026-08-01T13:00:00.000Z",
        administered_by_role=AdministeredByRole.RN,
        second_signature_present=True,
    )
    assert witnessed_rx["compliance_flag"] == ComplianceFlag.COMPLIANT

    otc = fx.administer_medication(
        api,
        camp["id"],
        camper_reference="CR-01",
        medication_class=MedicationClass.OTC,
        dose_units=1,
        administered_at="2026-08-01T17:00:00.000Z",
        administered_by_role=AdministeredByRole.FIRST_AIDER,
    )
    assert otc["compliance_flag"] == ComplianceFlag.COMPLIANT

    assert fx.read_camp(api, camp["id"])["controlled_on_hand_units"] == 0
