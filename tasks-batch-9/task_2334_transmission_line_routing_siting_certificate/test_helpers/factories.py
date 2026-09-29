"""Payload factories — one per write endpoint family.

Each factory returns the minimal PRD-declared payload with sane defaults and
lets a caller override any field with a keyword argument.  Passing ``None``
explicitly keeps the key present with a null value (needed for the polymorphic
pairings the PRD checks), while omitting the argument leaves the key out.
"""

from typing import Optional

_UNSET = object()


def _apply(payload: dict, overrides: dict) -> dict:
    for key, value in overrides.items():
        if value is _UNSET:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# ---------------------------------------------------------------------------
# Need case
# ---------------------------------------------------------------------------


def project_payload(
    name: str = "Harlan-Boone 345kV Rebuild",
    voltage_class: str = "KV_345",
    jurisdiction_state: str = "KY",
    target_energization_at: str = "2028-04-01T00:00:00Z",
    **overrides,
) -> dict:
    return _apply(
        {
            "name": name,
            "voltage_class": voltage_class,
            "jurisdiction_state": jurisdiction_state,
            "target_energization_at": target_energization_at,
        },
        overrides,
    )


def escrow_deposit_payload(
    amount_cents: int = 600_000_000, reference: str = "ESCROW-1", **overrides
) -> dict:
    return _apply({"amount_cents": amount_cents, "reference": reference}, overrides)


def planning_study_payload(
    project_id: str,
    horizon_year: int = 2032,
    reliability_deficit_mw: float = 400,
    transmission_capex_cents: int = 80_000_000_000,
    benefit_pv_cents: int = 80_000_000_000,
    **overrides,
) -> dict:
    return _apply(
        {
            "project_id": project_id,
            "horizon_year": horizon_year,
            "reliability_deficit_mw": reliability_deficit_mw,
            "transmission_capex_cents": transmission_capex_cents,
            "benefit_pv_cents": benefit_pv_cents,
        },
        overrides,
    )


def alternative_payload(
    study_id: str,
    kind: str = "TRANSMISSION",
    description: str = "New 345kV single-circuit line",
    capex_cents: int = 80_000_000_000,
    deliverable_mw: float = 400,
    **overrides,
) -> dict:
    return _apply(
        {
            "study_id": study_id,
            "kind": kind,
            "description": description,
            "capex_cents": capex_cents,
            "deliverable_mw": deliverable_mw,
        },
        overrides,
    )


def screening_payload(
    decision: str = "SCREEN_IN", screen_reason: str = "Meets deficit in full", **overrides
) -> dict:
    return _apply({"decision": decision, "screen_reason": screen_reason}, overrides)


def sufficiency_certification_payload(
    attestation_note: str = "Need case reviewed by independent engineer", **overrides
) -> dict:
    return _apply({"attestation_note": attestation_note}, overrides)


# ---------------------------------------------------------------------------
# Corridors
# ---------------------------------------------------------------------------


def route_payload(
    project_id: str,
    label: str = "Route A - river crossing",
    kind: str = "PROPOSED",
    **overrides,
) -> dict:
    return _apply({"project_id": project_id, "label": label, "kind": kind}, overrides)


def route_segment_payload(
    route_id: str,
    sequence_index: int = 1,
    miles: float = 10.0,
    land_use_rating: int = 3,
    environmental_rating: int = 4,
    cultural_rating: int = 2,
    engineering_rating: int = 3,
    county: str = "Harlan",
    crew_capacity: int = 12,
    survey_status: str = "FIELD_VERIFIED",
    habitat_blackout: bool = False,
    federal_crossing_kind: str = "NONE",
    **overrides,
) -> dict:
    return _apply(
        {
            "route_id": route_id,
            "sequence_index": sequence_index,
            "miles": miles,
            "land_use_rating": land_use_rating,
            "environmental_rating": environmental_rating,
            "cultural_rating": cultural_rating,
            "engineering_rating": engineering_rating,
            "county": county,
            "crew_capacity": crew_capacity,
            "survey_status": survey_status,
            "habitat_blackout": habitat_blackout,
            "federal_crossing_kind": federal_crossing_kind,
        },
        overrides,
    )


def federal_permit_action_payload(
    action: str = "APPLY",
    agency: Optional[str] = "USACE",
    determination_note: str = "Section 10 permit sought for the river crossing",
    **overrides,
) -> dict:
    return _apply(
        {
            "action": action,
            "agency": agency,
            "determination_note": determination_note,
        },
        overrides,
    )


def constraint_mapping_payload(
    mapping_note: str = "Desk study plus field-verified segments", **overrides
) -> dict:
    return _apply({"mapping_note": mapping_note}, overrides)


def publication_payload(comment_window_days: int = 30, **overrides) -> dict:
    return _apply({"comment_window_days": comment_window_days}, overrides)


def open_house_payload(
    county: str = "Harlan", attendee_count: int = 40, **overrides
) -> dict:
    return _apply({"county": county, "attendee_count": attendee_count}, overrides)


def refinement_payload(
    refinement_note: str = "Corridor shifted away from the burial ground", **overrides
) -> dict:
    return _apply({"refinement_note": refinement_note}, overrides)


def nomination_payload(
    nomination_note: str = "Comment window closed with no open material comments",
    **overrides,
) -> dict:
    return _apply({"nomination_note": nomination_note}, overrides)


# ---------------------------------------------------------------------------
# Public comments
# ---------------------------------------------------------------------------


def public_comment_payload(
    route_id: str,
    commenter_kind: str = "PUBLIC",
    commenter_name: str = "Harlan County Grange",
    body: str = "The corridor crosses our hay ground at its narrowest point.",
    materiality: str = "GENERAL",
    **overrides,
) -> dict:
    return _apply(
        {
            "route_id": route_id,
            "commenter_kind": commenter_kind,
            "commenter_name": commenter_name,
            "body": body,
            "materiality": materiality,
        },
        overrides,
    )


def comment_disposition_payload(
    disposition: str = "ACKNOWLEDGE",
    disposition_note: str = "Concern noted and reflected in the corridor narrative",
    **overrides,
) -> dict:
    return _apply(
        {"disposition": disposition, "disposition_note": disposition_note}, overrides
    )


# ---------------------------------------------------------------------------
# Docket
# ---------------------------------------------------------------------------


def application_payload(
    project_id: str,
    study_id: str,
    proposed_route_id: str,
    docket_number: str = "EL-2026-0334",
    filing_fee_cents: int = 2_500_000,
    **overrides,
) -> dict:
    return _apply(
        {
            "project_id": project_id,
            "study_id": study_id,
            "proposed_route_id": proposed_route_id,
            "docket_number": docket_number,
            "filing_fee_cents": filing_fee_cents,
        },
        overrides,
    )


def sufficiency_review_payload(outcome: str = "ACCEPT", **overrides) -> dict:
    return _apply({"outcome": outcome}, overrides)


def amendment_payload(
    expected_application_version: int,
    amendment_summary: str = "Alternate route impact assessment added",
    **overrides,
) -> dict:
    return _apply(
        {
            "expected_application_version": expected_application_version,
            "amendment_summary": amendment_summary,
        },
        overrides,
    )


def hearing_session_payload(
    application_id: str,
    kind: str = "EVIDENTIARY",
    window_start_at: str = "2026-10-05T09:00:00Z",
    window_end_at: str = "2026-10-05T12:00:00Z",
    **overrides,
) -> dict:
    return _apply(
        {
            "application_id": application_id,
            "kind": kind,
            "window_start_at": window_start_at,
            "window_end_at": window_end_at,
        },
        overrides,
    )


def holding_payload(exhibits_admitted_count: int = 12, **overrides) -> dict:
    return _apply({"exhibits_admitted_count": exhibits_admitted_count}, overrides)


def record_closure_payload(closure_note: str = "Evidence closed", **overrides) -> dict:
    return _apply({"closure_note": closure_note}, overrides)


def intervention_payload(
    application_id: str,
    petitioner_kind: str = "LANDOWNER",
    grounds: str = "Crossing severs the home pasture",
    **overrides,
) -> dict:
    return _apply(
        {
            "application_id": application_id,
            "petitioner_kind": petitioner_kind,
            "grounds": grounds,
        },
        overrides,
    )


def intervention_ruling_payload(
    ruling: str = "GRANT",
    ruling_reason: str = "Direct property interest shown",
    **overrides,
) -> dict:
    return _apply({"ruling": ruling, "ruling_reason": ruling_reason}, overrides)


# ---------------------------------------------------------------------------
# The order
# ---------------------------------------------------------------------------


def standard_conditions() -> list:
    """The three-condition order used throughout: weights 4, 2 and 4."""
    return [
        {
            "code": "ENV-BLACKOUT-1",
            "category": "ENVIRONMENTAL",
            "constraint_kind": "SEASONAL_BLACKOUT",
            "severity_weight": 4,
            "blackout_start_mmdd": "04-01",
            "blackout_end_mmdd": "07-15",
        },
        {
            "code": "CUL-MON-1",
            "category": "CULTURAL",
            "constraint_kind": "MONITORING",
            "severity_weight": 2,
        },
        {
            "code": "ENG-CREW-1",
            "category": "ENGINEERING",
            "constraint_kind": "CREW_LIMIT",
            "severity_weight": 4,
            "crew_limit": 9,
        },
    ]


def decision_payload(
    outcome: str = "GRANT",
    certified_route_id: Optional[str] = None,
    eminent_domain_authorized: bool = True,
    mitigation_base_cents: int = 480_000_000,
    conditions: Optional[list] = None,
    **overrides,
) -> dict:
    payload: dict = {"outcome": outcome}
    if outcome == "GRANT":
        payload.update(
            {
                "certified_route_id": certified_route_id,
                "eminent_domain_authorized": eminent_domain_authorized,
                "mitigation_base_cents": mitigation_base_cents,
                "conditions": standard_conditions() if conditions is None else conditions,
            }
        )
    return _apply(payload, overrides)


def waiver_payload(
    waiver_reason: str = "Monitoring folded into the federal permit conditions",
    **overrides,
) -> dict:
    return _apply({"waiver_reason": waiver_reason}, overrides)


def closeout_payload(
    closeout_note: str = "Construction compliance demonstrated", **overrides
) -> dict:
    return _apply({"closeout_note": closeout_note}, overrides)


# ---------------------------------------------------------------------------
# Easements
# ---------------------------------------------------------------------------


def landowner_payload(
    name: str = "Ada Wren",
    email: str = "ada@example.com",
    mailing_address: str = "18 Ridge Rd, Harlan KY",
    **overrides,
) -> dict:
    return _apply(
        {"name": name, "email": email, "mailing_address": mailing_address}, overrides
    )


def easement_tract_payload(
    project_id: str,
    segment_id: str,
    landowner_id: str,
    parcel_number: str = "H-104-22",
    acres: float = 12.35,
    per_acre_value_cents: int = 487_500,
    easement_factor: float = 0.65,
    structure_damages_cents: int = 250_000,
    before_value_cents: int = 90_000_000,
    after_value_cents: int = 82_500_000,
    severance_damages_cents: int = 400_000,
    **overrides,
) -> dict:
    return _apply(
        {
            "project_id": project_id,
            "segment_id": segment_id,
            "landowner_id": landowner_id,
            "parcel_number": parcel_number,
            "acres": acres,
            "per_acre_value_cents": per_acre_value_cents,
            "easement_factor": easement_factor,
            "structure_damages_cents": structure_damages_cents,
            "before_value_cents": before_value_cents,
            "after_value_cents": after_value_cents,
            "severance_damages_cents": severance_damages_cents,
        },
        overrides,
    )


def offer_payload(
    expected_tract_version: int,
    offer_note: str = "Initial appraisal-based offer",
    **overrides,
) -> dict:
    return _apply(
        {
            "expected_tract_version": expected_tract_version,
            "offer_note": offer_note,
        },
        overrides,
    )


def offer_response_payload(
    response: str = "ACCEPT", response_note: str = "Terms accepted", **overrides
) -> dict:
    return _apply({"response": response, "response_note": response_note}, overrides)


def condemnation_payload(
    court_docket_number: str = "CC-2027-77", deposit_cents: int = 5_000_000, **overrides
) -> dict:
    return _apply(
        {"court_docket_number": court_docket_number, "deposit_cents": deposit_cents},
        overrides,
    )


def award_payload(award_note: str = "Commissioners' award entered", **overrides) -> dict:
    return _apply({"award_note": award_note}, overrides)


def payment_payload(payment_reference: str = "WIRE-1", **overrides) -> dict:
    return _apply({"payment_reference": payment_reference}, overrides)


def rescission_payload(
    rescission_reason: str = "Wire returned by the receiving bank", **overrides
) -> dict:
    return _apply({"rescission_reason": rescission_reason}, overrides)


# ---------------------------------------------------------------------------
# Construction and compliance
# ---------------------------------------------------------------------------


def construction_activity_payload(
    certificate_id: str,
    segment_id: str,
    activity_kind: str = "CLEARING",
    crew_count: int = 6,
    window_start_at: str = "2027-08-02T00:00:00Z",
    window_end_at: str = "2027-08-12T00:00:00Z",
    **overrides,
) -> dict:
    return _apply(
        {
            "certificate_id": certificate_id,
            "segment_id": segment_id,
            "activity_kind": activity_kind,
            "crew_count": crew_count,
            "window_start_at": window_start_at,
            "window_end_at": window_end_at,
        },
        overrides,
    )


def activity_start_payload(start_note: str = "Crew mobilized", **overrides) -> dict:
    return _apply({"start_note": start_note}, overrides)


def activity_completion_payload(
    completion_note: str = "Right of way cleared", **overrides
) -> dict:
    return _apply({"completion_note": completion_note}, overrides)


def activity_cancellation_payload(
    cancellation_reason: str = "Foundations rescoped to the alternate structure family",
    **overrides,
) -> dict:
    return _apply({"cancellation_reason": cancellation_reason}, overrides)


def nonconformance_payload(
    certificate_id: str,
    condition_id: str,
    severity: str = "SEVERE",
    observation: str = "Clearing inside the seasonal habitat blackout",
    **overrides,
) -> dict:
    return _apply(
        {
            "certificate_id": certificate_id,
            "condition_id": condition_id,
            "severity": severity,
            "observation": observation,
        },
        overrides,
    )


def correction_payload(
    corrective_action: str = "Habitat restoration completed and monitor sign-off obtained",
    **overrides,
) -> dict:
    return _apply({"corrective_action": corrective_action}, overrides)


def void_payload(
    corrective_action: str = "Finding withdrawn on the record", **overrides
) -> dict:
    return _apply(
        {"corrective_action": corrective_action, "void_finding": True}, overrides
    )
