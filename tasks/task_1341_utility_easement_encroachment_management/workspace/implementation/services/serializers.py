"""Serializers: project internal entity dicts to their public field sets."""

from __future__ import annotations

CASE_FIELDS = [
    "id", "case_code", "utility_district", "county", "parcel_id",
    "easement_width_ft", "easement_area_sqft", "fair_market_value_per_sqft",
    "acquisition_budget_cents", "compensation_committed_cents",
    "compensation_balance_cents", "open_encroachment_count",
    "encroachment_pressure_score", "title_cleared", "active_permit_count",
    "status", "created_at", "updated_at", "version",
]

DOCUMENT_FIELDS = [
    "id", "case_id", "doc_kind", "instrument_number", "recording_date",
    "grantor_name", "grantee_name", "gis_polygon_wkt", "encumbrance_rank",
    "width_ft", "supersedes_document_id", "status",
    "created_at", "updated_at", "version",
]

ENCROACHMENT_FIELDS = [
    "id", "case_id", "discovered_via", "encroachment_type",
    "encroachment_area_sqft", "depth_into_easement_ft", "encroaches_document_id",
    "severity_tier", "estimated_removal_cost_cents", "owner_response_due_date",
    "negotiation_round", "status", "created_at", "updated_at", "version",
]

OFFER_FIELDS = [
    "id", "case_id", "landowner_name", "landowner_contact", "offered_area_sqft",
    "base_compensation_cents", "negotiated_compensation_cents",
    "severance_damages_cents", "total_compensation_cents", "negotiation_round",
    "negotiation_deadline", "requires_director_approval", "status",
    "created_at", "updated_at", "version",
]

PERMIT_FIELDS = [
    "id", "case_id", "encroachment_id", "permittee_name", "permit_type",
    "requested_area_sqft", "requested_start_date", "requested_end_date",
    "annual_fee_cents", "approval_status", "field_inspection_status",
    "insurance_certificate_on_file", "created_at", "updated_at", "version",
]

ZONE_FIELDS = [
    "id", "case_id", "zone_label", "max_allowed_height_ft", "prohibited_species",
    "wire_zone_width_ft", "border_zone_width_ft", "last_inspection_date",
    "violation_count", "status", "created_at", "updated_at", "version",
]

VIOLATION_FIELDS = [
    "id", "zone_id", "case_id", "species", "observed_height_ft",
    "location_within_zone", "excess_height_ft", "remediation_deadline",
    "status", "created_at", "updated_at", "version",
]

TASK_FIELDS = [
    "id", "case_id", "search_scope", "ordered_by", "completed_by",
    "liens_found", "defects_found", "chain_of_title_json", "status",
    "created_at", "updated_at", "version",
]

REFERRAL_FIELDS = [
    "id", "case_id", "encroachment_id", "referral_reason", "referred_by",
    "accepted_by", "filing_deadline", "status",
    "created_at", "updated_at", "version",
]


def _project(entity: dict, fields: list[str]) -> dict:
    return {name: entity.get(name) for name in fields}


def serialize_case(e): return _project(e, CASE_FIELDS)
def serialize_document(e): return _project(e, DOCUMENT_FIELDS)
def serialize_encroachment(e): return _project(e, ENCROACHMENT_FIELDS)
def serialize_offer(e): return _project(e, OFFER_FIELDS)
def serialize_permit(e): return _project(e, PERMIT_FIELDS)
def serialize_zone(e): return _project(e, ZONE_FIELDS)
def serialize_violation(e): return _project(e, VIOLATION_FIELDS)
def serialize_task(e): return _project(e, TASK_FIELDS)
def serialize_referral(e): return _project(e, REFERRAL_FIELDS)


def serialize_list(items, fn):
    return [fn(it) for it in items]
