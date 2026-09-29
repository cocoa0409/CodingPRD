"""Two partial updates on disjoint field groups each return the whole camp, bump the version by
exactly one, and rebuild the staffing requirement, the posture and the risk index from scratch."""

from __future__ import annotations

from test_helpers import fixtures as fx
from test_helpers.assertions import assert_camp, assert_risk_index_breakdown
from test_helpers.factories import health_center_payload
from test_helpers.test_users import (
    STATE_AGENT_HEADERS,
    make_camp_director_headers,
    make_health_care_staff_headers,
)
from test_helpers.types import (
    AccreditationStatus,
    CampType,
    CompliancePosture,
    HealthStaffingLevel,
    PopulationServed,
    RiskIndexVariant,
    StateLicenseStatus,
)
from prd_bench_local_runner.testing import validate_success


def _camp_whose_numbers_demand_nothing_yet(api):
    """A day camp with no census, no distance and no licence: base 10 plus 6 unlicensed."""
    fx.reset_clock(api)
    camp = fx.register_camp(
        api,
        name="Patch Camp",
        camp_type=CampType.DAY,
        state_code="OH",
        population_served=PopulationServed.YOUTH_ONLY,
        resident_census=0,
        max_daily_census=0,
        distance_to_hospital_km=0,
        health_staffing_level=HealthStaffingLevel.FIRST_AIDER_ONLY,
    )
    assert camp["version"] == 1
    assert camp["required_health_staffing_level"] == HealthStaffingLevel.FIRST_AIDER_ONLY
    assert camp["compliance_posture"] == CompliancePosture.OPEN
    assert float(camp["risk_index"]) == 16.00
    return camp


def _camp_on_probation(api):
    """The licence walked NONE to ACTIVE to PROBATION, the only route the PRD permits."""
    camp = _camp_whose_numbers_demand_nothing_yet(api)
    licensed = fx.move_state_license(
        api, camp["id"], StateLicenseStatus.ACTIVE, "OH-CAMP-51002"
    )
    assert licensed["version"] == 2
    assert float(licensed["risk_index"]) == 10.00
    return fx.move_state_license(api, camp["id"], StateLicenseStatus.PROBATION)


def test_a_licensing_write_returns_the_whole_camp_and_rebuilds_posture_and_risk(api):
    """PRD §3.1: "Every licensing write recomputes the compliance posture and the risk index and
    increments the camp's `version` by one, and none of them touches `accreditation_status`."

    Design: Corner/endpoints/patch_endpoints_return_the_whole_camp_and_rebuild_every_derived_field
    """
    on_probation = _camp_on_probation(api)

    assert_camp(on_probation)
    assert on_probation["state_license_status"] == StateLicenseStatus.PROBATION
    assert on_probation["state_license_number"] == "OH-CAMP-51002"
    assert on_probation["version"] == 3
    assert on_probation["compliance_posture"] == CompliancePosture.RESTRICTED
    # The probation penalty of 10 replaces the 6 the camp paid while unlicensed.
    assert float(on_probation["risk_index"]) == 20.00
    assert on_probation["accreditation_status"] == AccreditationStatus.NOT_ACCREDITED


def test_the_census_and_distance_edit_alone_promotes_the_staffing_requirement(api):
    """PRD §3.1: "The required rank is then the largest of those five components, plus one further
    step when at least three of the five components are themselves 2 or greater, with the total
    capped at 4."

    Design: Corner/endpoints/patch_endpoints_return_the_whole_camp_and_rebuild_every_derived_field
    """
    on_probation = _camp_on_probation(api)

    resized = validate_success(
        api.patch_health_center(
            on_probation["id"],
            health_center_payload(resident_census=130, distance_to_hospital_km=25),
            make_health_care_staff_headers(on_probation["id"]),
        )
    )
    assert_camp(resized)
    assert resized["resident_census"] == 130
    assert resized["distance_to_hospital_km"] == 25
    assert resized["version"] == on_probation["version"] + 1
    # Census rank 3 is the maximum and only two components reach 2, so no combination step.
    assert resized["required_health_staffing_level"] == HealthStaffingLevel.RN_ONSITE
    # 10 base plus the 15-point gap plus 10 for probation.
    assert float(resized["risk_index"]) == 35.00
    # The endpoint touched only the fields present in the payload.
    assert resized["health_staffing_level"] == HealthStaffingLevel.FIRST_AIDER_ONLY
    assert resized["max_daily_census"] == 0


def test_staffing_up_to_the_requirement_closes_the_gap_the_previous_edit_opened(api):
    """PRD §3.1: "Because the staffing-gap clause of §2.7 compares actual against required,
    lowering `health_staffing_level` or lengthening the hospital distance can move a camp from
    `OPEN` to `RESTRICTED` without any accreditation event at all."

    Design: Corner/endpoints/patch_endpoints_return_the_whole_camp_and_rebuild_every_derived_field
    """
    camp_id = _camp_on_probation(api)["id"]
    resized = fx.revise_health_center(api, camp_id, resident_census=130, distance_to_hospital_km=25)

    staffed = validate_success(
        api.patch_health_center(
            camp_id,
            health_center_payload(health_staffing_level=HealthStaffingLevel.RN_ONSITE),
            make_camp_director_headers(camp_id),
        )
    )
    assert_camp(staffed)
    assert staffed["health_staffing_level"] == HealthStaffingLevel.RN_ONSITE
    assert staffed["version"] == resized["version"] + 1
    assert staffed["required_health_staffing_level"] == HealthStaffingLevel.RN_ONSITE
    # The gap penalty is gone, but probation still costs 10 and still holds the posture.
    assert float(staffed["risk_index"]) == 20.00
    assert staffed["compliance_posture"] == CompliancePosture.RESTRICTED


def test_the_component_read_matches_the_stored_field_under_the_pre_visit_variant(api):
    """PRD §2.9: "A dedicated computed read exposes it broken out by component, answering with
    `camp_id`, `risk_index_variant`, `incident_component`, `program_component`,
    `staffing_gap_penalty`, `license_penalty`, `compliance_component`, `population_multiplier`
    and `risk_index`."

    Design: Corner/endpoints/patch_endpoints_return_the_whole_camp_and_rebuild_every_derived_field
    """
    camp_id = _camp_on_probation(api)["id"]
    fx.revise_health_center(api, camp_id, resident_census=130, distance_to_hospital_km=25)
    fx.revise_health_center(api, camp_id, health_staffing_level=HealthStaffingLevel.RN_ONSITE)

    components = fx.read_risk_index(api, camp_id, STATE_AGENT_HEADERS)
    assert_risk_index_breakdown(components)
    # The camp holds no cycle at all, so the pre-visit variant answers with a zero component.
    assert components["risk_index_variant"] == RiskIndexVariant.PRE_VISIT
    assert float(components["staffing_gap_penalty"]) == 0.00
    assert float(components["license_penalty"]) == 10.00
    assert float(components["compliance_component"]) == 0.00
    assert float(components["risk_index"]) == 20.00
    assert float(components["risk_index"]) == float(fx.read_camp(api, camp_id)["risk_index"])
