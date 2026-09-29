"""Domain assertion helpers.

Shape assertions follow the PRD's system-field rule: twelve types carry `id`,
`created_at`, `updated_at` and a monotonically increasing integer `version`,
while `MaintenanceCharge` — the one immutable event type — carries only `id`
and `created_at`.
"""

import re
from typing import Dict, Iterable, List, Optional

import pytest

from prd_bench_local_runner.testing import is_valid_uuid

from . import types as domain_types

_TIMESTAMP_MILLIS = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}(Z|\+00:00)$"
)
_CALENDAR_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def assert_utc_timestamp_with_millis(value: str, field: str = "timestamp") -> None:
    """ISO 8601 UTC with exactly three fractional-second digits."""
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert _TIMESTAMP_MILLIS.match(value), (
        f"{field} must be ISO 8601 UTC with exactly three fractional digits, "
        f"got {value!r}"
    )


def assert_calendar_date(value: str, field: str = "date") -> None:
    assert isinstance(value, str) and _CALENDAR_DATE.match(value), (
        f"{field} must be an ISO 8601 calendar date YYYY-MM-DD, got {value!r}"
    )


def assert_common_fields(entity: Dict, name: str = "entity") -> None:
    """The four system fields carried by every mutable type."""
    assert is_valid_uuid(entity.get("id")), (
        f"{name}.id must be a server-minted UUID with no prefix, "
        f"got {entity.get('id')!r}"
    )
    assert_utc_timestamp_with_millis(entity.get("created_at"), f"{name}.created_at")
    assert_utc_timestamp_with_millis(entity.get("updated_at"), f"{name}.updated_at")
    assert isinstance(entity.get("version"), int), (
        f"{name}.version must be an integer, got {entity.get('version')!r}"
    )
    assert entity["version"] >= 1, f"{name}.version starts at 1"


def assert_immutable_event_fields(entity: Dict, name: str = "charge") -> None:
    """Only `id` and `created_at`; no `updated_at` and no `version`."""
    assert is_valid_uuid(entity.get("id")), (
        f"{name}.id must be a server-minted UUID, got {entity.get('id')!r}"
    )
    assert_utc_timestamp_with_millis(entity.get("created_at"), f"{name}.created_at")
    assert "updated_at" not in entity, (
        f"{name} must not carry updated_at: {sorted(entity)}"
    )
    assert "version" not in entity, (
        f"{name} must not carry version: {sorted(entity)}"
    )


def assert_enum_value(value, allowed: Iterable, field: str) -> None:
    assert value in allowed, f"{field} must be one of {list(allowed)}, got {value!r}"


def assert_score(actual, expected: float, field: str = "score") -> None:
    """Non-money scores are carried to two decimal places."""
    assert actual == pytest.approx(expected, abs=0.01), (
        f"{field} expected {expected}, got {actual}"
    )


def assert_money(actual, expected: int, field: str = "amount") -> None:
    """Money is whole cents; an exact integer comparison is the contract."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{field} must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{field} expected {expected} cents, got {actual}"


def assert_request_envelope_meta(meta: Dict) -> None:
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must carry the 'req_' prefix, got {meta['api_request_id']!r}"
    )
    assert_utc_timestamp_with_millis(meta.get("api_request_timestamp"),
                                    "meta.api_request_timestamp")


def assert_pagination_meta(meta: Dict, total_count: Optional[int] = None,
                           has_more: Optional[bool] = None,
                           limit: Optional[int] = None,
                           offset: Optional[int] = None) -> None:
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"total_count expected {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"has_more expected {has_more}, got {meta['has_more']}"
        )
    if limit is not None:
        assert meta["limit"] == limit, f"limit expected {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, (
            f"offset expected {offset}, got {meta['offset']}"
        )


# --------------------------------------------------------------------------
# Entity shape assertions
# --------------------------------------------------------------------------


def assert_agency_site_shape(site: Dict) -> None:
    assert_common_fields(site, "site")
    for field in ("site_code", "name", "address_line"):
        assert isinstance(site.get(field), str) and site[field], (
            f"site.{field} must be a non-empty string"
        )
    assert isinstance(site.get("parcel_area_sqft"), int)
    assert_enum_value(site.get("acquisition_funding_source"),
                     domain_types.ACQUISITION_FUNDING_SOURCES,
                     "site.acquisition_funding_source")
    assert isinstance(site.get("federal_interest_pct"), (int, float))
    assert isinstance(site.get("transit_facility_present"), bool)
    assert_enum_value(site.get("status"), domain_types.SITE_STATUSES, "site.status")
    if site.get("readiness_tier") is not None:
        assert_enum_value(site["readiness_tier"], domain_types.READINESS_TIERS,
                         "site.readiness_tier")
    for field in ("federal_interest_basis_cents",
                  "federal_interest_encumbered_cents",
                  "federal_interest_unencumbered_cents"):
        assert isinstance(site.get(field), int), f"site.{field} must be integer cents"


def assert_readiness_assessment_shape(assessment: Dict) -> None:
    assert_common_fields(assessment, "assessment")
    assert is_valid_uuid(assessment.get("site_id"))
    for field in ("environmental_score", "utility_score", "access_score",
                  "entitlement_score", "encumbrance_count"):
        assert isinstance(assessment.get(field), int), f"assessment.{field} integer"
    assert isinstance(assessment.get("assessment_notes"), str)
    assert isinstance(assessment.get("composite_score"), (int, float))
    assert_enum_value(assessment.get("variant_applied"),
                     domain_types.ASSESSMENT_VARIANTS, "assessment.variant_applied")
    assert_enum_value(assessment.get("status"), domain_types.ASSESSMENT_STATUSES,
                     "assessment.status")
    if assessment.get("tier") is not None:
        assert_enum_value(assessment["tier"], domain_types.READINESS_TIERS,
                         "assessment.tier")


def assert_developer_shape(developer: Dict) -> None:
    assert_common_fields(developer, "developer")
    assert isinstance(developer.get("legal_name"), str)
    assert isinstance(developer.get("contact_email"), str)
    assert isinstance(developer.get("prequalified"), bool)
    assert_enum_value(developer.get("debarment_status"),
                     domain_types.DEBARMENT_STATUSES, "developer.debarment_status")


def assert_solicitation_shape(solicitation: Dict) -> None:
    assert_common_fields(solicitation, "solicitation")
    assert is_valid_uuid(solicitation.get("site_id"))
    assert_enum_value(solicitation.get("solicitation_type"),
                     domain_types.SOLICITATION_TYPES,
                     "solicitation.solicitation_type")
    assert isinstance(solicitation.get("benchmark_value_cents"), int)
    assert isinstance(solicitation.get("min_proposals_required"), int)
    assert isinstance(solicitation.get("joint_use_required"), bool)
    assert isinstance(solicitation.get("responsive_proposal_count"), int)
    assert_enum_value(solicitation.get("status"),
                     domain_types.SOLICITATION_STATUSES, "solicitation.status")


def assert_proposal_shape(proposal: Dict) -> None:
    assert_common_fields(proposal, "proposal")
    assert is_valid_uuid(proposal.get("solicitation_id"))
    assert is_valid_uuid(proposal.get("developer_id"))
    assert_enum_value(proposal.get("proposed_structure"),
                     domain_types.PROPOSED_STRUCTURES,
                     "proposal.proposed_structure")
    for field in ("affordable_units", "total_units", "transit_ridership_uplift",
                  "design_compliance_score"):
        assert isinstance(proposal.get(field), int), f"proposal.{field} integer"
    assert isinstance(proposal.get("joint_use_committed"), bool)
    assert isinstance(proposal.get("affordable_pct"), (int, float))
    assert isinstance(proposal.get("evaluation_score"), (int, float))
    assert_enum_value(proposal.get("status"), domain_types.PROPOSAL_STATUSES,
                     "proposal.status")


def assert_negotiation_period_shape(period: Dict) -> None:
    assert_common_fields(period, "period")
    assert is_valid_uuid(period.get("site_id"))
    assert is_valid_uuid(period.get("proposal_id"))
    assert_calendar_date(period.get("start_date"), "period.start_date")
    assert_calendar_date(period.get("end_date"), "period.end_date")
    assert isinstance(period.get("extension_count"), int)
    assert_enum_value(period.get("status"),
                     domain_types.NEGOTIATION_PERIOD_STATUSES, "period.status")


def assert_valuation_shape(valuation: Dict) -> None:
    assert_common_fields(valuation, "valuation")
    assert is_valid_uuid(valuation.get("site_id"))
    assert_enum_value(valuation.get("method"), domain_types.VALUATION_METHODS,
                     "valuation.method")
    assert_enum_value(valuation.get("transfer_basis"), domain_types.TRANSFER_BASES,
                     "valuation.transfer_basis")
    for field in ("appraised_value_cents", "transit_supportive_credit_cents",
                  "federal_interest_floor_cents", "permissible_floor_cents"):
        assert isinstance(valuation.get(field), int), f"valuation.{field} cents"
    assert_calendar_date(valuation.get("effective_date"), "valuation.effective_date")
    assert_enum_value(valuation.get("status"), domain_types.VALUATION_STATUSES,
                     "valuation.status")


def assert_agreement_shape(agreement: Dict) -> None:
    assert_common_fields(agreement, "agreement")
    for field in ("site_id", "developer_id", "proposal_id", "valuation_id"):
        assert is_valid_uuid(agreement.get(field)), f"agreement.{field} must be a UUID"
    assert_enum_value(agreement.get("structure"), domain_types.PROPOSED_STRUCTURES,
                     "agreement.structure")
    assert isinstance(agreement.get("term_years"), int)
    assert isinstance(agreement.get("revenue_share_pct"), (int, float))
    for field in ("projected_gross_revenue_cents", "capital_credit_cents",
                  "annual_revenue_to_agency_cents", "consideration_value_cents"):
        assert isinstance(agreement.get(field), int), f"agreement.{field} cents"
    for field in ("affordable_units_committed", "total_units"):
        assert isinstance(agreement.get(field), int), f"agreement.{field} integer"
    assert isinstance(agreement.get("site_area_share_pct"), (int, float))
    assert isinstance(agreement.get("joint_use_committed"), bool)
    assert_enum_value(agreement.get("negotiation_status"),
                     domain_types.NEGOTIATION_STATUSES, "agreement.negotiation_status")
    assert_enum_value(agreement.get("federal_approval_status"),
                     domain_types.FEDERAL_APPROVAL_STATUSES,
                     "agreement.federal_approval_status")


def assert_disposition_request_shape(request: Dict) -> None:
    assert_common_fields(request, "disposition_request")
    assert is_valid_uuid(request.get("jda_id"))
    assert isinstance(request.get("narrative"), str)
    assert isinstance(request.get("federal_interest_amount_cents"), int)
    assert_enum_value(request.get("determination"),
                     domain_types.DISPOSITION_DETERMINATIONS,
                     "disposition_request.determination")


def assert_facility_replacement_shape(replacement: Dict) -> None:
    assert_common_fields(replacement, "replacement")
    assert is_valid_uuid(replacement.get("jda_id"))
    assert_enum_value(replacement.get("facility_type"),
                     domain_types.REPLACEMENT_FACILITY_TYPES,
                     "replacement.facility_type")
    for field in ("original_capacity", "replacement_capacity", "interim_capacity",
                  "capacity_deficit"):
        assert isinstance(replacement.get(field), int), f"replacement.{field} integer"
    assert replacement["capacity_deficit"] >= 0, "capacity_deficit is never negative"
    assert_calendar_date(replacement.get("milestone_date"),
                        "replacement.milestone_date")
    assert_enum_value(replacement.get("status"), domain_types.REPLACEMENT_STATUSES,
                     "replacement.status")


def assert_shared_facility_shape(facility: Dict) -> None:
    assert_common_fields(facility, "facility")
    assert is_valid_uuid(facility.get("site_id"))
    assert_enum_value(facility.get("facility_type"),
                     domain_types.SHARED_FACILITY_TYPES, "facility.facility_type")
    assert isinstance(facility.get("total_bay_capacity"), int)
    assert isinstance(facility.get("available_bay_capacity"), int)
    assert_enum_value(facility.get("maintenance_responsibility"),
                     domain_types.MAINTENANCE_RESPONSIBILITIES,
                     "facility.maintenance_responsibility")
    assert isinstance(facility.get("cost_share_pct_developer"), (int, float))


def assert_staging_window_shape(window: Dict) -> None:
    assert_common_fields(window, "window")
    assert is_valid_uuid(window.get("jda_id"))
    assert is_valid_uuid(window.get("shared_facility_id"))
    assert isinstance(window.get("bays_occupied"), int)
    assert isinstance(window.get("purpose"), str)
    assert isinstance(window.get("capacity_released"), bool)
    assert_enum_value(window.get("status"), domain_types.STAGING_WINDOW_STATUSES,
                     "window.status")


def assert_maintenance_charge_shape(charge: Dict) -> None:
    assert_immutable_event_fields(charge, "charge")
    assert is_valid_uuid(charge.get("shared_facility_id"))
    assert is_valid_uuid(charge.get("jda_id"))
    assert_calendar_date(charge.get("period_start"), "charge.period_start")
    assert_calendar_date(charge.get("period_end"), "charge.period_end")
    assert isinstance(charge.get("line_items"), list) and charge["line_items"]
    assert isinstance(charge.get("effective_share_applied"), (int, float))
    for field in ("total_cost_cents", "developer_share_cents", "agency_share_cents"):
        assert isinstance(charge.get(field), int), f"charge.{field} cents"


# --------------------------------------------------------------------------
# Cross-record invariants
# --------------------------------------------------------------------------


def assert_federal_ledger_identity(site: Dict) -> None:
    """basis = encumbered + unencumbered, always, on every read."""
    basis = site["federal_interest_basis_cents"]
    encumbered = site["federal_interest_encumbered_cents"]
    unencumbered = site["federal_interest_unencumbered_cents"]
    assert encumbered + unencumbered == basis, (
        "federal_interest_encumbered_cents plus "
        "federal_interest_unencumbered_cents must equal "
        f"federal_interest_basis_cents: {encumbered} + {unencumbered} != {basis}"
    )


def assert_bay_capacity_identity(facility: Dict,
                                 approved_windows: List[Dict]) -> None:
    """available capacity plus the approved windows' bays equals the total."""
    occupied = sum(window["bays_occupied"] for window in approved_windows)
    assert facility["available_bay_capacity"] + occupied == \
        facility["total_bay_capacity"], (
        "available_bay_capacity plus the bays_occupied of APPROVED windows must "
        f"equal total_bay_capacity: {facility['available_bay_capacity']} + "
        f"{occupied} != {facility['total_bay_capacity']}"
    )


def assert_maintenance_split_conserved(charge: Dict) -> None:
    """The agency share is exactly the remainder of the plain total."""
    assert charge["developer_share_cents"] + charge["agency_share_cents"] == \
        charge["total_cost_cents"], (
        "developer_share_cents plus agency_share_cents must equal "
        f"total_cost_cents: {charge['developer_share_cents']} + "
        f"{charge['agency_share_cents']} != {charge['total_cost_cents']}"
    )


def assert_version_bumped_by(before: int, after: int, bumps: int = 1,
                             name: str = "record") -> None:
    assert after == before + bumps, (
        f"{name}.version expected {before + bumps} after {bumps} write(s), "
        f"got {after}"
    )
