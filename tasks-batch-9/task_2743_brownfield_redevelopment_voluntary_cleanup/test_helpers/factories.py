"""
Payload builders: one per declared write endpoint.

Each builder supplies a valid default for every required input the contract names, so
a test only has to state the field whose rule it is exercising. Every keyword argument
overrides its default, and passing ``None`` for an optional field sends an explicit
null rather than omitting the key — which matters for the fields the contract says
must be absent under one branch and present under another.

The values here are ordinary domain data. Nothing in a factory encodes a rule; the
rules are asserted in the tests.
"""

from typing import Any, Dict, List, Optional

_OMITTED = object()

# Public alias: pass ``OMIT`` for any field a test needs to leave out of the body
# entirely, as opposed to sending it as an explicit null.
OMIT = _OMITTED


def _apply(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Merge overrides, letting a caller drop a key entirely with ``_OMITTED``."""
    for key, value in overrides.items():
        if value is _OMITTED:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# ─── Parties and laboratories ─────────────────────────────────────────────────


def party_payload(
    legal_name: str = "Ironbridge Redevelopment LLC",
    party_type: str = "REDEVELOPER",
    state_code: str = "OH",
    licence_number=_OMITTED,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": legal_name,
        "party_type": party_type,
        "state_code": state_code,
    }
    if licence_number is not _OMITTED:
        payload["licence_number"] = licence_number
    return _apply(payload, overrides)


def _typed_party_payload(defaults: Dict[str, Any],
                         overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Seed the per-type defaults, then let the caller override any of them."""
    merged = dict(defaults)
    merged.update(overrides)
    return party_payload(**merged)


def redeveloper_payload(**overrides) -> Dict[str, Any]:
    return _typed_party_payload(
        {
            "legal_name": "Ironbridge Redevelopment LLC",
            "party_type": "REDEVELOPER",
            "state_code": "OH",
        },
        overrides,
    )


def consultant_payload(**overrides) -> Dict[str, Any]:
    return _typed_party_payload(
        {
            "legal_name": "Terraline Environmental PC",
            "party_type": "CONSULTANT",
            "state_code": "OH",
            "licence_number": "OH-PG-4417",
        },
        overrides,
    )


def insurer_payload(**overrides) -> Dict[str, Any]:
    return _typed_party_payload(
        {
            "legal_name": "Meridian Specialty Insurance Co",
            "party_type": "INSURER",
            "state_code": "OH",
            "licence_number": "OH-INS-2290",
        },
        overrides,
    )


def laboratory_payload(
    lab_name: str = "GreatLakes Analytical",
    certification_code: str = "NELAP-OH-118",
    concurrent_capacity: int = 10,
    **overrides,
) -> Dict[str, Any]:
    return _apply(
        {
            "lab_name": lab_name,
            "certification_code": certification_code,
            "concurrent_capacity": concurrent_capacity,
        },
        overrides,
    )


# ─── Sites ────────────────────────────────────────────────────────────────────


def site_payload(
    owner_party_id: str,
    site_name: str = "Kinnickinnic Rail Yard",
    county_code: str = "OH-039",
    acreage: float = 12.4,
    intended_reuse: str = "COMMERCIAL",
    planned_acquisition_date: str = "2026-10-15",
    institutional_control_committed=True,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "owner_party_id": owner_party_id,
        "site_name": site_name,
        "county_code": county_code,
        "acreage": acreage,
        "intended_reuse": intended_reuse,
        "planned_acquisition_date": planned_acquisition_date,
    }
    if institutional_control_committed is not _OMITTED:
        payload["institutional_control_committed"] = institutional_control_committed
    return _apply(payload, overrides)


def acquisition_payload(
    acquisition_date: str = "2026-10-15", **overrides
) -> Dict[str, Any]:
    return _apply({"acquisition_date": acquisition_date}, overrides)


# ─── Assessment phases and findings ───────────────────────────────────────────


def assessment_phase_payload(
    site_id: str,
    consultant_party_id: str,
    phase_type: str = "PHASE_I",
    field_start_date: str = "2026-06-01",
    field_end_date: str = "2026-07-10",
    delineation_confidence: str = "SCREENING",
    aai_report_date=_OMITTED,
    delineation_complete=_OMITTED,
    supersedes_phase_id=_OMITTED,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "site_id": site_id,
        "consultant_party_id": consultant_party_id,
        "phase_type": phase_type,
        "field_start_date": field_start_date,
        "field_end_date": field_end_date,
        "delineation_confidence": delineation_confidence,
    }
    if aai_report_date is _OMITTED and phase_type == "PHASE_I":
        payload["aai_report_date"] = "2026-07-20"
    elif aai_report_date is not _OMITTED:
        payload["aai_report_date"] = aai_report_date
    if delineation_complete is not _OMITTED:
        payload["delineation_complete"] = delineation_complete
    if supersedes_phase_id is not _OMITTED:
        payload["supersedes_phase_id"] = supersedes_phase_id
    return _apply(payload, overrides)


def phase_ii_payload(
    site_id: str,
    consultant_party_id: str,
    delineation_confidence: str = "FULL",
    delineation_complete: bool = True,
    field_start_date: str = "2026-11-01",
    field_end_date: str = "2026-12-05",
    **overrides,
) -> Dict[str, Any]:
    return assessment_phase_payload(
        site_id,
        consultant_party_id,
        phase_type="PHASE_II",
        field_start_date=field_start_date,
        field_end_date=field_end_date,
        delineation_confidence=delineation_confidence,
        delineation_complete=delineation_complete,
        **overrides,
    )


def finding_payload(
    contaminant_code: str = "TCE",
    media: str = "SOIL_VAPOR",
    sample_location_code: str = "SV-01",
    max_concentration_ugl: float = 480.0,
    screening_level_ugl: float = 5.0,
    delineated: bool = False,
    **overrides,
) -> Dict[str, Any]:
    return _apply(
        {
            "contaminant_code": contaminant_code,
            "media": media,
            "sample_location_code": sample_location_code,
            "max_concentration_ugl": max_concentration_ugl,
            "screening_level_ugl": screening_level_ugl,
            "delineated": delineated,
        },
        overrides,
    )


def phase_review_payload(
    decision: str = "APPROVE", review_comment=_OMITTED, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if review_comment is _OMITTED:
        payload["review_comment"] = "Reviewed against the programme checklist."
    else:
        payload["review_comment"] = review_comment
    return _apply(payload, overrides)


# ─── Liability protection, inquiry and obligations ────────────────────────────


def liability_protection_payload(site_id: str, **overrides) -> Dict[str, Any]:
    return _apply({"site_id": site_id}, overrides)


def inquiry_completion_payload(aai_phase_id: str, **overrides) -> Dict[str, Any]:
    return _apply({"aai_phase_id": aai_phase_id}, overrides)


def continuing_obligation_payload(
    obligation_category: str = "REASONABLE_STEPS",
    description: str = "Maintain the sub-slab depressurisation system and report failures.",
    due_date: str = "2027-03-01",
    recurrence_days: int = 90,
    **overrides,
) -> Dict[str, Any]:
    return _apply(
        {
            "obligation_category": obligation_category,
            "description": description,
            "due_date": due_date,
            "recurrence_days": recurrence_days,
        },
        overrides,
    )


# ─── Cleanup goals ────────────────────────────────────────────────────────────


def cleanup_goal_payload(
    contaminant_code: str = "TCE",
    media: str = "SOIL_VAPOR",
    screening_level_ugl: float = 5.0,
    basis: str = "RESTRICTED",
    control_credit_type=_OMITTED,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "contaminant_code": contaminant_code,
        "media": media,
        "screening_level_ugl": screening_level_ugl,
        "basis": basis,
    }
    if control_credit_type is _OMITTED:
        if basis == "RESTRICTED":
            payload["control_credit_type"] = "VAPOR_MITIGATION"
    else:
        payload["control_credit_type"] = control_credit_type
    return _apply(payload, overrides)


# ─── Enrollments ──────────────────────────────────────────────────────────────


def enrollment_payload(
    site_id: str,
    program_track: str = "RESTRICTED_CLOSURE",
    applicant_statement: str = (
        "Rail yard redevelopment to commercial reuse with vapor mitigation."
    ),
    **overrides,
) -> Dict[str, Any]:
    return _apply(
        {
            "site_id": site_id,
            "program_track": program_track,
            "applicant_statement": applicant_statement,
        },
        overrides,
    )


def eligibility_decision_payload(
    decision: str = "ENROLL", decision_note=_OMITTED, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if decision_note is _OMITTED:
        payload["decision_note"] = "AAI complete and institutional control committed."
    else:
        payload["decision_note"] = decision_note
    return _apply(payload, overrides)


# ─── Cost lines ───────────────────────────────────────────────────────────────


def cost_line(
    cost_category: str,
    media: str,
    quantity,
    unit_cost_cents: int,
) -> Dict[str, Any]:
    """One element of a plan's ordered ``cost_lines`` array."""
    return {
        "cost_category": cost_category,
        "media": media,
        "quantity": quantity,
        "unit_cost_cents": unit_cost_cents,
    }


def canonical_cost_lines() -> List[Dict[str, Any]]:
    """
    Six lines spanning three media and four categories, in a fixed array order.

    The mixed fractional quantities matter: several products land on a half cent, so
    the array distinguishes a per-line rounding from a rounding of the total.
    """
    return [
        cost_line("EXCAVATION_DISPOSAL", "SOIL", 100.13, 4325),
        cost_line("EXCAVATION_DISPOSAL", "SOIL", 200.13, 4325),
        cost_line("EXCAVATION_DISPOSAL", "SOIL", 12500, 4325),
        cost_line("GW_TREATMENT", "GROUNDWATER", 875.25, 15750),
        cost_line("VAPOR_MITIGATION", "SOIL_VAPOR", 3.5, 2875000),
        cost_line("MONITORING", "GROUNDWATER", 48, 65500),
    ]


def single_excavation_line(quantity=12000, unit_cost_cents=5000) -> List[Dict[str, Any]]:
    """One large soil excavation line; the media factor is 1.00 so the maths is plain."""
    return [cost_line("EXCAVATION_DISPOSAL", "SOIL", quantity, unit_cost_cents)]


def single_monitoring_line(quantity=10, unit_cost_cents=100000) -> List[Dict[str, Any]]:
    """One small groundwater monitoring line, used where a tiny estimate is wanted."""
    return [cost_line("MONITORING", "GROUNDWATER", quantity, unit_cost_cents)]


# ─── Remedial action plans ────────────────────────────────────────────────────


def plan_payload(
    vcp_enrollment_id: str,
    site_id: str,
    basis_assessment_phase_id: str,
    expected_vcp_enrollment_version: int,
    remedy_narrative: str = (
        "Excavation and off-site disposal of impacted soil, pump-and-treat of the "
        "shallow aquifer, sub-slab vapor mitigation and 5-year performance monitoring."
    ),
    years_to_construction_start: int = 3,
    cost_lines: Optional[List[Dict[str, Any]]] = None,
    **overrides,
) -> Dict[str, Any]:
    return _apply(
        {
            "vcp_enrollment_id": vcp_enrollment_id,
            "site_id": site_id,
            "remedy_narrative": remedy_narrative,
            "basis_assessment_phase_id": basis_assessment_phase_id,
            "years_to_construction_start": years_to_construction_start,
            "cost_lines": canonical_cost_lines() if cost_lines is None else cost_lines,
            "expected_vcp_enrollment_version": expected_vcp_enrollment_version,
        },
        overrides,
    )


def plan_patch_payload(**fields) -> Dict[str, Any]:
    """An edit carries only the subset of editable inputs a test names."""
    return dict(fields)


def technical_review_payload(
    decision: str = "PASS", review_comment=_OMITTED, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if review_comment is _OMITTED:
        payload["review_comment"] = "Remedy technically adequate for the delineation."
    else:
        payload["review_comment"] = review_comment
    return _apply(payload, overrides)


def public_comment_close_payload(
    public_comment_count: int = 7, **overrides
) -> Dict[str, Any]:
    return _apply({"public_comment_count": public_comment_count}, overrides)


# ─── Cost-cap policies ────────────────────────────────────────────────────────


def policy_payload(
    remedial_action_plan_id: str,
    insurer_party_id: str,
    expected_remedial_action_plan_version: int,
    policy_reference: str = "CCP-2743-A1",
    term_years: int = 5,
    **overrides,
) -> Dict[str, Any]:
    return _apply(
        {
            "remedial_action_plan_id": remedial_action_plan_id,
            "insurer_party_id": insurer_party_id,
            "policy_reference": policy_reference,
            "term_years": term_years,
            "expected_remedial_action_plan_version": expected_remedial_action_plan_version,
        },
        overrides,
    )


# ─── Site controls ────────────────────────────────────────────────────────────


def site_control_payload(
    site_id: str,
    remedial_action_plan_id: str,
    control_type: str = "VAPOR_MITIGATION",
    sub_area_code: str = "BLDG-A-SLAB",
    coverage_from: str = "2027-01-01",
    coverage_to: str = "2027-12-31",
    inspection_interval_days: int = 90,
    **overrides,
) -> Dict[str, Any]:
    return _apply(
        {
            "site_id": site_id,
            "remedial_action_plan_id": remedial_action_plan_id,
            "control_type": control_type,
            "sub_area_code": sub_area_code,
            "coverage_from": coverage_from,
            "coverage_to": coverage_to,
            "inspection_interval_days": inspection_interval_days,
        },
        overrides,
    )


def operation_certification_payload(
    condition: str = "PASS", certification_date: str = "2027-01-15", **overrides
) -> Dict[str, Any]:
    return _apply(
        {"condition": condition, "certification_date": certification_date}, overrides
    )


def decommission_payload(
    decommission_note="Control no longer required.", **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if decommission_note is not _OMITTED:
        payload["decommission_note"] = decommission_note
    return _apply(payload, overrides)


# ─── Funding awards ───────────────────────────────────────────────────────────


def funding_award_payload(
    site_id: str,
    program_code: str = "OH-BROWNFIELD-CLEANUP",
    funding_kind: str = "GRANT",
    program_priority: int = 1,
    max_award_cents: int = 30000000,
    max_share_pct: float = 0.40,
    match_requirement_pct: float = 0.20,
    eligible_cost_categories: Optional[List[str]] = None,
    eligibility_documents: Optional[List[str]] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "site_id": site_id,
        "program_code": program_code,
        "funding_kind": funding_kind,
        "program_priority": program_priority,
        "max_award_cents": max_award_cents,
        "max_share_pct": max_share_pct,
        "match_requirement_pct": match_requirement_pct,
        "eligible_cost_categories": (
            ["EXCAVATION_DISPOSAL", "MONITORING"]
            if eligible_cost_categories is None
            else eligible_cost_categories
        ),
    }
    if eligibility_documents is not _OMITTED:
        payload["eligibility_documents"] = (
            [
                "SITE_CONTROL_EVIDENCE",
                "PHASE_II_REPORT",
                "COST_ESTIMATE",
                "MATCH_COMMITMENT",
            ]
            if eligibility_documents is None
            else eligibility_documents
        )
    return _apply(payload, overrides)


def tax_credit_award_payload(
    site_id: str,
    program_code: str = "OH-REMEDIATION-TAX-CREDIT",
    program_priority: int = 2,
    max_award_cents: int = 60000000,
    max_share_pct: float = 0.75,
    match_requirement_pct: float = 0.00,
    eligible_cost_categories: Optional[List[str]] = None,
    eligibility_documents: Optional[List[str]] = None,
    **overrides,
) -> Dict[str, Any]:
    return funding_award_payload(
        site_id,
        program_code=program_code,
        funding_kind="TAX_CREDIT",
        program_priority=program_priority,
        max_award_cents=max_award_cents,
        max_share_pct=max_share_pct,
        match_requirement_pct=match_requirement_pct,
        eligible_cost_categories=(
            ["GW_TREATMENT", "VAPOR_MITIGATION"]
            if eligible_cost_categories is None
            else eligible_cost_categories
        ),
        eligibility_documents=(
            ["BFPP_CERTIFICATION", "PHASE_II_REPORT", "COST_ESTIMATE"]
            if eligibility_documents is None
            else eligibility_documents
        ),
        **overrides,
    )


def funding_decision_payload(
    decision: str = "AWARD", decision_note=_OMITTED, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if decision_note is _OMITTED:
        payload["decision_note"] = "Application processed."
    else:
        payload["decision_note"] = decision_note
    return _apply(payload, overrides)


# ─── Closure letters ──────────────────────────────────────────────────────────


def nfa_letter_payload(
    site_id: str,
    vcp_enrollment_id: str,
    requested_scope: str = "RESTRICTED_WITH_CONTROLS",
    **overrides,
) -> Dict[str, Any]:
    return _apply(
        {
            "site_id": site_id,
            "vcp_enrollment_id": vcp_enrollment_id,
            "requested_scope": requested_scope,
        },
        overrides,
    )


def lender_acceptance_payload(
    lender_reference: str = "LOAN-2743-CRE-118", **overrides
) -> Dict[str, Any]:
    return _apply({"lender_reference": lender_reference}, overrides)


# ─── Monitoring events ────────────────────────────────────────────────────────


def monitoring_event_payload(
    site_id: str,
    laboratory_id: str,
    cleanup_goal_id: str,
    event_type: str = "SAMPLING",
    monitoring_period_code: str = "2027-M02",
    sample_date: str = "2027-02-05",
    window_start: str = "2027-02-01T00:00:00Z",
    window_end: str = "2027-02-15T00:00:00Z",
    site_control_id=_OMITTED,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "site_id": site_id,
        "laboratory_id": laboratory_id,
        "cleanup_goal_id": cleanup_goal_id,
        "event_type": event_type,
        "monitoring_period_code": monitoring_period_code,
        "sample_date": sample_date,
        "window_start": window_start,
        "window_end": window_end,
    }
    if site_control_id is not _OMITTED:
        payload["site_control_id"] = site_control_id
    return _apply(payload, overrides)


def sampling_result_payload(result_value_ugl, **overrides) -> Dict[str, Any]:
    return _apply({"result_value_ugl": result_value_ugl}, overrides)


def inspection_result_payload(control_condition: str = "PASS", **overrides) -> Dict[str, Any]:
    return _apply({"control_condition": control_condition}, overrides)


def void_payload(
    void_reason: str = "Certification photographs did not match the parcel.", **overrides
) -> Dict[str, Any]:
    return _apply({"void_reason": void_reason}, overrides)


def withdrawal_payload(
    withdrawal_reason: str = "Buyer walked away from the transaction.", **overrides
) -> Dict[str, Any]:
    return _apply({"withdrawal_reason": withdrawal_reason}, overrides)
