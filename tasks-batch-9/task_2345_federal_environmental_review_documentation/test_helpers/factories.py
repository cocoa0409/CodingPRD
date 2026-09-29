"""Payload factories — one per creatable entity.

Each factory returns only the fields a caller may supply on the write endpoint;
server-derived and server-computed fields are never included. Every factory
accepts ``**overrides`` so a test can vary exactly one input, and an override
whose value is ``None`` removes the key entirely so a test can omit an optional
or required field on purpose.
"""
import itertools
from typing import Optional

_counter = itertools.count(1)


def _unique(prefix: str) -> str:
    return f"{prefix}{next(_counter):04d}"


def _apply(payload: dict, overrides: dict) -> dict:
    for key, value in overrides.items():
        if value is None and key in payload:
            del payload[key]
        else:
            payload[key] = value
    return payload


# --------------------------------------------------------------------------
# ReviewOffice (PRD 3.1, 2.10)
# --------------------------------------------------------------------------

def review_office_payload(**overrides) -> dict:
    payload = {
        "office_code": _unique("ERO"),
        "name": "Environmental Review Office 1",
    }
    return _apply(payload, overrides)


# --------------------------------------------------------------------------
# Agency (PRD 3.1)
# --------------------------------------------------------------------------

def agency_payload(**overrides) -> dict:
    payload = {
        "agency_code": _unique("AG"),
        "name": "US Fish and Wildlife Service",
        "agency_role": "CONSULTING",
        "status": "ACTIVE",
    }
    return _apply(payload, overrides)


# --------------------------------------------------------------------------
# ProposedAction (PRD 3.2)
# --------------------------------------------------------------------------

def proposed_action_payload(office_id: str, **overrides) -> dict:
    payload = {
        "office_id": office_id,
        "title": "Ridgeline Fuels Treatment",
        "disturbance_hectares": 40.0,
        "reference_cost_cents": 10000000,
        "in_critical_habitat": True,
        "affects_historic_property": False,
        "tribal_interest": False,
        "floodplain_or_wetland": False,
    }
    return _apply(payload, overrides)


# --------------------------------------------------------------------------
# ExtraordinaryCircumstanceScreen (PRD 3.2)
# --------------------------------------------------------------------------

def ec_finding(code: str, present: bool, severity: int,
               narrative: Optional[str] = None) -> dict:
    """One entry of the screen's ``findings`` array. ``narrative`` is required
    whenever ``present`` is true."""
    finding = {"code": code, "present": present, "severity": severity}
    if present:
        finding["narrative"] = narrative or f"{code} observed on site."
    elif narrative is not None:
        finding["narrative"] = narrative
    return finding


def ec_screen_payload(**overrides) -> dict:
    payload = {
        "findings": [
            ec_finding("EC_HISTORIC", False, 0,
                       "No historic properties in the action area"),
            ec_finding("EC_ENDANGERED_SPECIES", True, 2,
                       "Lynx transit habitat, discountable effects"),
            ec_finding("EC_WETLAND", False, 0, "No wetlands mapped"),
        ]
    }
    return _apply(payload, overrides)


def ec_adjudication_payload(disposition: str, **overrides) -> dict:
    payload = {
        "disposition": disposition,
        "adjudicator_note": f"Adjudicated as {disposition} after review.",
    }
    return _apply(payload, overrides)


# --------------------------------------------------------------------------
# PurposeNeedStatement (PRD 3.4)
# --------------------------------------------------------------------------

def purpose_need_payload(**overrides) -> dict:
    payload = {
        "purpose_text": "Reduce hazardous fuel loading on the Ridgeline unit",
        "need_text": (
            "Modelled fire behaviour exceeds the wildland-urban interface standard"
        ),
        "goal_codes": ["ACCESS", "SAFETY", "HABITAT", "COST"],
        "constraint_codes": ["NO_NEW_ROADS"],
    }
    return _apply(payload, overrides)


def adopt_payload(expected_action_version: int, **overrides) -> dict:
    payload = {"expected_action_version": expected_action_version}
    return _apply(payload, overrides)


# --------------------------------------------------------------------------
# ScopingPeriod (PRD 3.5)
# --------------------------------------------------------------------------

def scoping_period_payload(**overrides) -> dict:
    payload = {
        "scoping_kind": "PUBLIC",
        "start_at": "2026-08-03T00:00:00Z",
        "end_at": "2026-09-02T00:00:00Z",
    }
    return _apply(payload, overrides)


# --------------------------------------------------------------------------
# Issue (PRD 3.5)
# --------------------------------------------------------------------------

def issue_payload(scoping_period_id: str, **overrides) -> dict:
    payload = {
        "scoping_period_id": scoping_period_id,
        "resource_area": "BIOLOGICAL",
        "origin": "PUBLIC",
        "significance": "SIGNIFICANT",
        "summary": "Effects on lynx winter range",
    }
    return _apply(payload, overrides)


# --------------------------------------------------------------------------
# Alternative (PRD 3.4)
# --------------------------------------------------------------------------

def alternative_payload(action_id: str, **overrides) -> dict:
    payload = {
        "action_id": action_id,
        "label": "B - Proposed Treatment",
        "alternative_kind": "PROPOSED_ACTION",
        "goal_alignment_codes": ["ACCESS", "SAFETY", "HABITAT"],
        "estimated_cost_cents": 12000000,
    }
    return _apply(payload, overrides)


def screen_alternative_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    return _apply(payload, overrides)


# --------------------------------------------------------------------------
# CumulativeAction (PRD 3.7)
# --------------------------------------------------------------------------

def cumulative_action_payload(**overrides) -> dict:
    payload = {
        "resource_area": "BIOLOGICAL",
        "label": _unique("Legacy grazing allotment "),
        "intensity_contribution": 20.0,
        "footprint_hectares": 100.0,
        "distance_km": 10.0,
        "temporal_scope": "PAST",
    }
    return _apply(payload, overrides)


# --------------------------------------------------------------------------
# ResourceAnalysis (PRD 3.7)
# --------------------------------------------------------------------------

def resource_analysis_payload(**overrides) -> dict:
    payload = {
        "resource_area": "BIOLOGICAL",
        "intensity_score": 72.0,
        "context_sensitivity_score": 55.0,
        "affected_area_hectares": 4.0,
        "mitigation_reduction_points": 12.0,
    }
    return _apply(payload, overrides)


def finalize_analysis_payload(basis: str, **overrides) -> dict:
    payload = {"basis": basis}
    return _apply(payload, overrides)


# --------------------------------------------------------------------------
# ConsultationRequest (PRD 3.6)
# --------------------------------------------------------------------------

def consultation_payload(action_id: str, agency_id: str, **overrides) -> dict:
    payload = {
        "action_id": action_id,
        "agency_id": agency_id,
        "consultation_type": "ESA_SECTION_7",
        "requested_start_at": "2026-08-05T00:00:00Z",
    }
    return _apply(payload, overrides)


def consultation_response_payload(outcome: str, **overrides) -> dict:
    payload = {"outcome": outcome}
    if outcome == "CONDITIONAL_CONCURRENCE":
        payload["conditions_text"] = "Concurrence conditioned on seasonal timing limits."
    return _apply(payload, overrides)


# --------------------------------------------------------------------------
# NepaDocument (PRD 3.8)
# --------------------------------------------------------------------------

def document_payload(**overrides) -> dict:
    payload = {
        "document_type": "ENVIRONMENTAL_ASSESSMENT",
        "title": "Ridgeline Fuels Treatment Environmental Assessment",
    }
    return _apply(payload, overrides)


def publish_document_payload(comment_period_end_at: str, **overrides) -> dict:
    payload = {"comment_period_end_at": comment_period_end_at}
    return _apply(payload, overrides)


# --------------------------------------------------------------------------
# PublicComment (PRD 3.8)
# --------------------------------------------------------------------------

def comment_payload(document_id: str, **overrides) -> dict:
    payload = {
        "document_id": document_id,
        "commenter_name": "J. Rivera",
        "resource_area": "BIOLOGICAL",
        "is_substantive": True,
        "body": "The habitat analysis omits winter range connectivity",
    }
    return _apply(payload, overrides)


def comment_response_payload(response_category: str, **overrides) -> dict:
    payload = {
        "response_text": "Winter range connectivity added to section 3.2",
        "response_category": response_category,
    }
    return _apply(payload, overrides)


# --------------------------------------------------------------------------
# DecisionDocument (PRD 3.9)
# --------------------------------------------------------------------------

def decision_payload(action_id: str, selected_alternative_id: str,
                     decision_type: str = "MITIGATED_FONSI", **overrides) -> dict:
    payload = {
        "action_id": action_id,
        "selected_alternative_id": selected_alternative_id,
        "decision_type": decision_type,
    }
    return _apply(payload, overrides)


# --------------------------------------------------------------------------
# MitigationCommitment (PRD 3.9)
# --------------------------------------------------------------------------

def mitigation_payload(source_analysis_id: str, expected_decision_version: int,
                       **overrides) -> dict:
    payload = {
        "source_analysis_id": source_analysis_id,
        "expected_decision_version": expected_decision_version,
        "measure_text": "Seasonal closure of the winter range unit",
        "cost_estimate_cents": 1200000,
        "monitoring_years": 3,
        "annual_monitoring_cost_cents": 450000,
        "reduction_points": 9.0,
    }
    return _apply(payload, overrides)


# --------------------------------------------------------------------------
# Objection (PRD 3.9)
# --------------------------------------------------------------------------

def objection_payload(**overrides) -> dict:
    payload = {
        "objector_name": "Ridgeline Watershed Alliance",
        "objector_type": "COMMENTER",
        "basis_issue_area": "BIOLOGICAL",
        "standing_basis": "SUBSTANTIVE_COMMENT",
    }
    return _apply(payload, overrides)


def resolve_objection_payload(disposition: str, **overrides) -> dict:
    payload = {
        "disposition": disposition,
        "resolution_note": f"Objection {disposition.lower()} after independent review.",
    }
    return _apply(payload, overrides)
