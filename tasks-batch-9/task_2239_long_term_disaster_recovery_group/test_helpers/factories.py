"""Payload factories — one per resource, carrying only client-supplied fields."""

from typing import Any, Dict

from .constants import TEST_DEFAULTS


def survivor_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "household_name": "Test Household",
        "primary_contact_phone": "555-0100",
        "household_size": 3,
        "income_band": "VLI",
        "head_of_household_age": 45,
        "has_member_with_disability": False,
        "is_uninsured": False,
        "consent_on_file": True,
        "follow_up_opt_in": True,
    }
    payload.update(overrides)
    return payload


def recovery_case_payload(survivor_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "survivor_id": survivor_id,
        "disaster_code": TEST_DEFAULTS["DISASTER_CODE"],
        "assigned_case_manager_user_id": TEST_DEFAULTS["CASE_MANAGER_USER_ID"],
        "primary_residence_status": "OWNER_OCCUPIED",
    }
    payload.update(overrides)
    return payload


def damage_item_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "category": "STRUCTURE",
        "item_description": "Framing and sheathing",
        "documented_cost_cents": 1_000_000,
        "photo_count": 4,
        "is_habitability_critical": True,
    }
    payload.update(overrides)
    return payload


def verification_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "verification_status": "VERIFIED",
        "verified_cost_cents": 1_000_000,
    }
    payload.update(overrides)
    return payload


def assistance_record_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "source_type": "NONPROFIT_GRANT",
        "purpose_code": "STRUCTURE_REPAIR",
        "awarded_cents": 100_000,
        "received_on": "2026-08-02",
        "documentation_status": "DOCUMENTED",
    }
    payload.update(overrides)
    return payload


def assessment_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"variant": "PURPOSE_MATCHED"}
    payload.update(overrides)
    return payload


def member_organization_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "org_name": "First Presbyterian Relief",
        "org_type": "FAITH_BASED",
        "contact_email": "relief@fpc.example",
        "annual_pledge_cap_cents": 5_000_000,
    }
    payload.update(overrides)
    return payload


def table_session_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "session_label": "UNT 2026-09-10",
        "scheduled_for": "2026-09-10T15:00:00Z",
        "quorum_min_member_orgs": 1,
    }
    payload.update(overrides)
    return payload


def case_presentation_payload(
    case_id: str, session_id: str, assessment_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "case_id": case_id,
        "session_id": session_id,
        "assessment_id": assessment_id,
        "prepared_by_user_id": TEST_DEFAULTS["CASE_MANAGER_USER_ID"],
        "narrative": "Household needs long-term repair support.",
    }
    payload.update(overrides)
    return payload


def funding_commitment_payload(
    presentation_id: str,
    member_org_id: str,
    pledged_cents: int,
    expected_presentation_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "presentation_id": presentation_id,
        "member_org_id": member_org_id,
        "pledged_cents": pledged_cents,
        "purpose_code": "STRUCTURE_REPAIR",
        "expected_presentation_version": expected_presentation_version,
    }
    payload.update(overrides)
    return payload


def funding_source_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "label": "General donations 2026",
        "source_type": "INDIVIDUAL_DONATION",
        "restriction_code": "UNRESTRICTED",
        "total_cents": 2_000_000,
        "admin_retention_allowed": True,
    }
    payload.update(overrides)
    return payload


def disbursement_payload(
    case_id: str, requested_cents: int, expected_case_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "case_id": case_id,
        "purpose_code": "CONTENTS_REPLACEMENT",
        "requested_cents": requested_cents,
        "payee_name": "Valley Furniture Co",
        "expected_case_version": expected_case_version,
    }
    payload.update(overrides)
    return payload


def construction_project_payload(case_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "case_id": case_id,
        "scope_code": "INTERIOR_REPAIR",
        "required_trade_hours": {"GENERAL_LABOR": 160},
        "estimated_material_cents": 500_000,
    }
    payload.update(overrides)
    return payload


def volunteer_group_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "group_name": "Redwood Baptist Crew",
        "home_organization": "Redwood Baptist",
        "member_count": 12,
        "skill_profile": {"FRAMING": 5, "ROOFING": 2, "GENERAL_LABOR": 12},
        "requires_housing": False,
        "brings_own_tools": True,
    }
    payload.update(overrides)
    return payload


def volunteer_deployment_payload(
    group_id: str, project_id: str, arrival_date: str, departure_date: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "group_id": group_id,
        "project_id": project_id,
        "arrival_date": arrival_date,
        "departure_date": departure_date,
    }
    payload.update(overrides)
    return payload


def lodging_site_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "site_name": "Grace Chapel Bunkhouse",
        "bed_capacity": 20,
        "has_showers": True,
        "nightly_cost_cents": 0,
    }
    payload.update(overrides)
    return payload


def housing_assignment_payload(
    group_id: str, lodging_site_id: str, check_in_date: str, check_out_date: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "group_id": group_id,
        "lodging_site_id": lodging_site_id,
        "check_in_date": check_in_date,
        "check_out_date": check_out_date,
    }
    payload.update(overrides)
    return payload


def follow_up_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "contact_type": "CHECK_IN_30_DAY",
        "contacted_on": "2026-09-05",
        "outcome": "REACHED",
        "notes": "Household reached by phone; repairs on track.",
    }
    payload.update(overrides)
    return payload
