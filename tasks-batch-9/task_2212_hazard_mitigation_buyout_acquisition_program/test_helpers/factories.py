"""Payload factories -- one per entity or operation, client-supplied fields only.

Every factory takes ``**overrides`` so a test can pin exactly the values it
cares about and inherit sensible defaults for the rest.
"""

import itertools

from .constants import DEFAULT_LOGICAL_CLOCK_DATE, TEST_DEFAULTS


_counter = itertools.count(1)


def unique_suffix() -> str:
    """A short monotonically increasing suffix for unique-by-constraint fields."""
    return str(next(_counter))


# ─── Project and benefit-cost analysis ────────────────────────────────────────

def create_mitigation_project_payload(**overrides) -> dict:
    payload = {
        "project_code": f"BUYOUT-{unique_suffix()}",
        "grant_program": TEST_DEFAULTS["GRANT_PROGRAM"],
        "subrecipient_name": TEST_DEFAULTS["SUBRECIPIENT_NAME"],
        "total_federal_share_cap_cents": TEST_DEFAULTS["LARGE_CAP_CENTS"],
        "period_of_performance_end_date": TEST_DEFAULTS["PERIOD_OF_PERFORMANCE_END_DATE"],
    }
    payload.update(overrides)
    return payload


def create_benefit_cost_analysis_payload(project_id, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "analysis_method": "PRE_CALCULATED_BENEFIT",
        "hazard_type": "RIVERINE_FLOOD",
        "sfha_zone": "AE",
        "annualized_loss_avoided_cents": 4_000_000,
        "project_useful_life_years": 30,
        "mitigation_cost_cents": 45_000_000,
    }
    payload.update(overrides)
    return payload


def validate_bca_payload(bca_id, decision="VALIDATE", **overrides) -> dict:
    payload = {"bca_id": bca_id, "decision": decision}
    payload.update(overrides)
    return payload


def approve_project_payload(project_id, decision="APPROVE", **overrides) -> dict:
    payload = {"project_id": project_id, "decision": decision}
    payload.update(overrides)
    return payload


def closeout_payload(project_id, decision="INITIATE", **overrides) -> dict:
    payload = {"project_id": project_id, "decision": decision}
    payload.update(overrides)
    return payload


# ─── Parcels, adjacency and pre-event value ───────────────────────────────────

def create_parcel_payload(project_id, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "apn": f"APN-{unique_suffix()}",
        "site_address": "101 River Rd",
        "acreage": 0.34,
        "occupancy_type": "OWNER_OCCUPIED",
        "structure_type": "SINGLE_FAMILY",
    }
    payload.update(overrides)
    return payload


def create_parcel_adjacency_payload(project_id, parcel_a_id, parcel_b_id, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "parcel_a_id": parcel_a_id,
        "parcel_b_id": parcel_b_id,
        "shared_boundary_feet": 120.00,
    }
    payload.update(overrides)
    return payload


def pre_event_value_payload(parcel_id, **overrides) -> dict:
    payload = {
        "parcel_id": parcel_id,
        "pre_event_fmv_cents": TEST_DEFAULTS["PRE_EVENT_FMV_CENTS"],
        "pre_event_value_basis": "ASSESSOR_ROLL",
    }
    payload.update(overrides)
    return payload


def participation_payload(parcel_id, participation_decision, **overrides) -> dict:
    payload = {"parcel_id": parcel_id, "participation_decision": participation_decision}
    if participation_decision == "CONFIRM_VOLUNTARY":
        payload["voluntary_acknowledgement_signed_on"] = DEFAULT_LOGICAL_CLOCK_DATE
    payload.update(overrides)
    return payload


# ─── Appraisals ───────────────────────────────────────────────────────────────

def create_appraisal_payload(parcel_id, **overrides) -> dict:
    payload = {
        "parcel_id": parcel_id,
        "appraisal_type": "INITIAL",
        "valuation_basis": "PRE_EVENT",
        "appraiser_license_no": "LIC-SA-1",
        "effective_date": TEST_DEFAULTS["APPRAISAL_EFFECTIVE_DATE"],
        "indicated_value_cents": TEST_DEFAULTS["PRE_EVENT_FMV_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_review_appraisal_payload(parcel_id, reviewed_appraisal_id, **overrides) -> dict:
    payload = {
        "parcel_id": parcel_id,
        "appraisal_type": "REVIEW",
        "valuation_basis": "PRE_EVENT",
        "appraiser_license_no": "LIC-RA-1",
        "effective_date": TEST_DEFAULTS["REVIEW_APPRAISAL_EFFECTIVE_DATE"],
        "indicated_value_cents": TEST_DEFAULTS["PRE_EVENT_FMV_CENTS"],
        "reviewed_appraisal_id": reviewed_appraisal_id,
    }
    payload.update(overrides)
    return payload


def submit_appraisal_payload(appraisal_id, **overrides) -> dict:
    payload = {"appraisal_id": appraisal_id}
    payload.update(overrides)
    return payload


def review_decision_payload(appraisal_id, decision="ACCEPT", **overrides) -> dict:
    payload = {"appraisal_id": appraisal_id, "decision": decision}
    payload.update(overrides)
    return payload


# ─── Duplication of benefits and offers ───────────────────────────────────────

def create_dob_record_payload(parcel_id, **overrides) -> dict:
    payload = {
        "parcel_id": parcel_id,
        "benefit_source": "NFIP_CLAIM",
        "amount_cents": 1_200_000,
        "received_on": "2026-05-01",
    }
    payload.update(overrides)
    return payload


def reverse_dob_record_payload(dob_record_id, reversal_reason="not a duplication", **overrides) -> dict:
    payload = {"dob_record_id": dob_record_id, "reversal_reason": reversal_reason}
    payload.update(overrides)
    return payload


def create_purchase_offer_payload(parcel_id, source_appraisal_id, expected_parcel_version, **overrides) -> dict:
    payload = {
        "parcel_id": parcel_id,
        "source_appraisal_id": source_appraisal_id,
        "offer_basis": "PRE_EVENT_FMV",
        "expected_parcel_version": expected_parcel_version,
    }
    payload.update(overrides)
    return payload


def owner_response_payload(offer_id, response="ACCEPT", **overrides) -> dict:
    payload = {"offer_id": offer_id, "response": response}
    payload.update(overrides)
    return payload


def withdraw_offer_payload(offer_id, withdrawal_reason="owner requested more time", **overrides) -> dict:
    payload = {"offer_id": offer_id, "withdrawal_reason": withdrawal_reason}
    payload.update(overrides)
    return payload


# ─── Relocation ───────────────────────────────────────────────────────────────

def create_relocation_case_payload(parcel_id, **overrides) -> dict:
    payload = {
        "parcel_id": parcel_id,
        "displacee_type": "OWNER_OCCUPANT",
        "household_reference": f"HH-{unique_suffix()}",
        "rhp_method": "COMPARABLE_DWELLING",
        "rental_assistance_start_date": "2026-09-01",
        "comparable_dwelling_price_cents": 22_000_000,
        "moving_expense_cents": 175_000,
    }
    payload.update(overrides)
    # An override of None means "leave the optional input out of the body entirely".
    return {key: value for key, value in payload.items() if value is not None}


def resolve_claim_payload(case_id, decision="PAY", **overrides) -> dict:
    payload = {"case_id": case_id, "decision": decision}
    payload.update(overrides)
    return payload


def appeal_payload(case_id, appeal_basis="comparable dwelling was mispriced", **overrides) -> dict:
    payload = {"case_id": case_id, "appeal_basis": appeal_basis}
    payload.update(overrides)
    return payload


# ─── Closing and deed recording ───────────────────────────────────────────────

def create_closing_record_payload(parcel_id, accepted_offer_id, **overrides) -> dict:
    payload = {
        "parcel_id": parcel_id,
        "accepted_offer_id": accepted_offer_id,
        "scheduled_closing_date": "2026-08-15",
        "settlement_cost_cents": 400_000,
    }
    payload.update(overrides)
    return payload


def record_deed_payload(closing_id, **overrides) -> dict:
    payload = {
        "closing_id": closing_id,
        "recording_reference": f"REC-{unique_suffix()}",
        "maintenance_responsible_party": "City of Riverbend Parks Department",
    }
    payload.update(overrides)
    return payload


# ─── Demolition ───────────────────────────────────────────────────────────────

def create_demolition_contractor_payload(**overrides) -> dict:
    suffix = unique_suffix()
    payload = {
        "name": f"Wrecking Co {suffix}",
        "license_no": f"DEM-{suffix}",
        "asbestos_certified": True,
        "max_concurrent_work_orders": 1,
    }
    payload.update(overrides)
    return payload


def contractor_status_payload(contractor_id, status, **overrides) -> dict:
    payload = {"contractor_id": contractor_id, "status": status}
    payload.update(overrides)
    return payload


def create_work_order_payload(parcel_id, contractor_id, **overrides) -> dict:
    payload = {
        "parcel_id": parcel_id,
        "contractor_id": contractor_id,
        "asbestos_survey_status": "CLEARED",
        "scheduled_start": "2026-10-05T08:00:00Z",
        "scheduled_end": "2026-10-06T17:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_utility_disconnection_payload(work_order_id, utility_type, **overrides) -> dict:
    payload = {
        "work_order_id": work_order_id,
        "utility_type": utility_type,
        "provider_name": f"Riverbend {utility_type.title()}",
    }
    payload.update(overrides)
    return payload


def resolve_disconnection_payload(disconnection_id, outcome="CONFIRMED", **overrides) -> dict:
    payload = {"disconnection_id": disconnection_id, "outcome": outcome}
    if outcome == "CONFIRMED":
        payload["confirmation_reference"] = f"CONF-{unique_suffix()}"
    payload.update(overrides)
    return payload


def complete_work_order_payload(work_order_id, **overrides) -> dict:
    payload = {
        "work_order_id": work_order_id,
        "total_debris_tons": 100.00,
        "recycled_tons": 30.00,
        "disposal_manifest_no": f"MAN-{unique_suffix()}",
        "disposal_facility_type": "COMBINED",
    }
    payload.update(overrides)
    return payload


def fail_inspection_payload(work_order_id, inspection_note="debris left on site", **overrides) -> dict:
    payload = {"work_order_id": work_order_id, "inspection_note": inspection_note}
    payload.update(overrides)
    return payload


# ─── Monitoring and restrictions ──────────────────────────────────────────────

def create_monitoring_inspection_payload(restriction_id, finding="COMPLIANT", **overrides) -> dict:
    payload = {
        "restriction_id": restriction_id,
        "inspection_date": DEFAULT_LOGICAL_CLOCK_DATE,
        "finding": finding,
        "narrative": "Routine open-space site visit.",
    }
    payload.update(overrides)
    return payload


def cure_payload(restriction_id, cure_date=DEFAULT_LOGICAL_CLOCK_DATE, **overrides) -> dict:
    payload = {
        "restriction_id": restriction_id,
        "cure_date": cure_date,
        "cure_narrative": "Prohibited use removed and site restored.",
    }
    payload.update(overrides)
    return payload


def terminate_restriction_payload(restriction_id, **overrides) -> dict:
    payload = {
        "restriction_id": restriction_id,
        "termination_authorization_reference": f"FEMA-OSR-{unique_suffix()}",
    }
    payload.update(overrides)
    return payload


# ─── Program income ───────────────────────────────────────────────────────────

def create_program_income_entry_payload(project_id, expected_project_version, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "entry_type": "LEASE_REVENUE",
        "amount_cents": 100_002,
        "posted_on": DEFAULT_LOGICAL_CLOCK_DATE,
        "expected_project_version": expected_project_version,
    }
    payload.update(overrides)
    return payload


def reverse_program_income_entry_payload(entry_id, reversal_note="posted to the wrong project", **overrides) -> dict:
    payload = {"entry_id": entry_id, "reversal_note": reversal_note}
    payload.update(overrides)
    return payload
