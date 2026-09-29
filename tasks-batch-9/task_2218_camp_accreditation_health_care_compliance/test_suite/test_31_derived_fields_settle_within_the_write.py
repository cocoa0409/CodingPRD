"""No write returns a stale or deferred view: the body that produced a derived value already carries
it, and the follow-up read plus the computed read agree with that body digit for digit."""

from __future__ import annotations

from test_helpers import fixtures as fx
from test_helpers.assertions import assert_camp, assert_risk_index_breakdown
from test_helpers.factories import health_center_payload, state_license_payload
from test_helpers.test_users import STATE_AGENT_HEADERS, make_health_care_staff_headers
from test_helpers.types import (
    CampType,
    CompliancePosture,
    HealthIntakeStatus,
    HealthStaffingLevel,
    PopulationServed,
    ProgramElement,
    RiskIndexVariant,
    StateLicenseStatus,
)
from prd_bench_local_runner.testing import validate_success

IMMEDIATE_CAMP = {
    "name": "Immediate Camp",
    "camp_type": CampType.RESIDENT,
    "state_code": "OH",
    "population_served": PopulationServed.YOUTH_ONLY,
    "program_elements": [ProgramElement.AQUATICS_OPEN_WATER, ProgramElement.TRANSPORTATION],
    "resident_census": 200,
    "distance_to_hospital_km": 45,
    "health_staffing_level": HealthStaffingLevel.FIRST_AIDER_ONLY,
}


def _a_camp_whose_configuration_demands_a_physician(api):
    """Resident type 3, census 3, distance 3 and open water 3, so four components reach 2."""
    fx.reset_clock(api)
    return fx.register_camp(api, **IMMEDIATE_CAMP)


def _suspend_the_licence(api, camp_id):
    """NONE to ACTIVE to SUSPENDED, the only route into suspension the PRD permits."""
    fx.move_state_license(api, camp_id, StateLicenseStatus.ACTIVE, "OH-CAMP-77001")
    return fx.move_state_license(api, camp_id, StateLicenseStatus.SUSPENDED)


def test_the_registration_body_already_carries_every_computed_field(api):
    """PRD §3.1: "The server then computes `required_health_staffing_level`, the compliance
    posture, and the risk index under its pre-visit variant."

    Design: Corner/consistency_model/every_derived_field_is_readable_in_the_same_response_that_changed_it
    """
    registered = _a_camp_whose_configuration_demands_a_physician(api)

    assert_camp(registered)
    # The largest component is 3 and four of the five reach 2, so the bump lands on rank 4.
    assert registered["required_health_staffing_level"] == HealthStaffingLevel.PHYSICIAN_ONSITE
    assert registered["compliance_posture"] == CompliancePosture.RESTRICTED
    assert registered["health_intake_status"] == HealthIntakeStatus.OPEN
    assert registered["risk_index_variant"] == RiskIndexVariant.PRE_VISIT
    # 10 base plus 12 programme plus 15 staffing gap plus 6 unlicensed, at multiplier 1.0.
    assert float(registered["risk_index"]) == 43.00
    assert registered["version"] == 1

    # The read adds nothing and changes nothing.
    reread = fx.read_camp(api, registered["id"])
    for field in (
        "required_health_staffing_level",
        "compliance_posture",
        "health_intake_status",
        "risk_index_variant",
        "risk_index",
        "version",
    ):
        assert reread[field] == registered[field]


def test_the_computed_read_decomposes_the_number_the_write_already_returned(api):
    """PRD §2.9: "A dedicated computed read exposes it broken out by component, answering with
    `camp_id`, `risk_index_variant`, `incident_component`, `program_component`,
    `staffing_gap_penalty`, `license_penalty`, `compliance_component`, `population_multiplier`
    and `risk_index`."

    Design: Corner/consistency_model/every_derived_field_is_readable_in_the_same_response_that_changed_it
    """
    registered = _a_camp_whose_configuration_demands_a_physician(api)

    components = fx.read_risk_index(api, registered["id"])
    assert_risk_index_breakdown(components)
    assert components["camp_id"] == registered["id"]
    assert float(components["incident_component"]) == 0.00
    # Open water weighs 8 and transportation weighs 4.
    assert float(components["program_component"]) == 12.00
    assert float(components["staffing_gap_penalty"]) == 15.00
    assert float(components["license_penalty"]) == 6.00
    assert float(components["compliance_component"]) == 0.00
    assert float(components["population_multiplier"]) == 1.0
    assert float(components["risk_index"]) == float(registered["risk_index"])


def test_each_licensing_body_shows_the_posture_cascade_without_a_follow_up_read(api):
    """PRD §3.1: "`ACTIVE → SUSPENDED` and `PROBATION → SUSPENDED` drive it to `FROZEN` through
    the suspension clause, which runs the full freeze cascade of §2.8: `health_intake_status`
    becomes `SUSPENDED`, every `VERIFIED` written plan of the camp becomes
    `REVALIDATION_REQUIRED`, and every evaluation citing one of those plans with `self_status`
    `VERIFIED` is knocked to `REJECTED`."

    Design: Corner/consistency_model/every_derived_field_is_readable_in_the_same_response_that_changed_it
    """
    registered = _a_camp_whose_configuration_demands_a_physician(api)

    licensed = validate_success(
        api.patch_state_license(
            registered["id"],
            state_license_payload(StateLicenseStatus.ACTIVE, "OH-CAMP-77001"),
            STATE_AGENT_HEADERS,
        )
    )
    assert licensed["state_license_status"] == StateLicenseStatus.ACTIVE
    assert float(licensed["risk_index"]) == 37.00
    assert licensed["version"] == 2
    # The staffing gap alone still holds the posture at RESTRICTED.
    assert licensed["compliance_posture"] == CompliancePosture.RESTRICTED

    suspended = validate_success(
        api.patch_state_license(
            registered["id"],
            state_license_payload(StateLicenseStatus.SUSPENDED),
            STATE_AGENT_HEADERS,
        )
    )
    assert suspended["state_license_status"] == StateLicenseStatus.SUSPENDED
    assert suspended["compliance_posture"] == CompliancePosture.FROZEN
    assert suspended["health_intake_status"] == HealthIntakeStatus.SUSPENDED
    assert float(suspended["risk_index"]) == 57.00
    assert suspended["version"] == 3

    components = fx.read_risk_index(api, registered["id"])
    assert float(components["license_penalty"]) == 20.00
    assert float(components["risk_index"]) == float(suspended["risk_index"])


def test_closing_the_staffing_gap_settles_in_its_own_response_but_cannot_thaw_the_camp(api):
    """PRD §2.7: "The posture is `FROZEN` when the camp's `penalty_point_balance` is at least 12,
    or its `state_license_status` is `SUSPENDED`, or at least one deficiency of the camp sits in
    `ESCALATED`."

    Design: Corner/consistency_model/every_derived_field_is_readable_in_the_same_response_that_changed_it
    """
    registered = _a_camp_whose_configuration_demands_a_physician(api)
    _suspend_the_licence(api, registered["id"])

    staffed = validate_success(
        api.patch_health_center(
            registered["id"],
            health_center_payload(health_staffing_level=HealthStaffingLevel.PHYSICIAN_ONSITE),
            make_health_care_staff_headers(registered["id"]),
        )
    )
    assert staffed["health_staffing_level"] == HealthStaffingLevel.PHYSICIAN_ONSITE
    assert staffed["required_health_staffing_level"] == HealthStaffingLevel.PHYSICIAN_ONSITE
    # The 15-point gap is gone; the 20-point suspension penalty stays.
    assert float(staffed["risk_index"]) == 42.00
    assert staffed["version"] == 4
    assert staffed["compliance_posture"] == CompliancePosture.FROZEN
    assert staffed["health_intake_status"] == HealthIntakeStatus.SUSPENDED

    assert float(fx.read_risk_index(api, registered["id"])["risk_index"]) == 42.00
