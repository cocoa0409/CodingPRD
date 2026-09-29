"""Request-payload factories.

Each factory returns a dict with valid defaults for the endpoint's declared
fields; every field can be overridden through keyword arguments, and passing
the module's ``OMIT`` sentinel for a field removes the key entirely so tests
can probe missing-field handling.
"""
from typing import Any, Dict, List, Optional

OMIT = object()
_SENTINEL = OMIT


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for key, value in overrides.items():
        if value is _SENTINEL:
            out.pop(key, None)
        else:
            out[key] = value
    return out


def firm_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "legal_name": "Calder Mote LLP",
            "state_code": "CA",
            "aa_hours_last_year": 400,
            "enrolled_program": "AICPA_PRC",
            "peer_review_year_end": "2026-12-31",
        },
        overrides,
    )


def firm_update_payload(**overrides) -> Dict[str, Any]:
    return dict(overrides)


def partner_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "full_name": "Quinn Cade",
            "cpa_license_state": "CA",
            "designations": ["ENGAGEMENT_PARTNER"],
            "cpe_hours_last_3y": 200,
        },
        overrides,
    )


def qc_director_payload(**overrides) -> Dict[str, Any]:
    return partner_payload(
        **_merge(
            {"full_name": "Quinn Cade", "designations": ["QC_DIRECTOR"]}, overrides
        )
    )


def managing_partner_payload(**overrides) -> Dict[str, Any]:
    return partner_payload(
        **_merge(
            {"full_name": "Mara Deane", "designations": ["MANAGING_PARTNER"]}, overrides
        )
    )


def eq_reviewer_payload(**overrides) -> Dict[str, Any]:
    return partner_payload(
        **_merge(
            {
                "full_name": "Ivo Renn",
                "designations": ["EQ_REVIEWER"],
                "cpe_hours_last_3y": 200,
            },
            overrides,
        )
    )


def engagement_payload(firm_id: str, engagement_partner_id: str, **overrides):
    return _merge(
        {
            "firm_id": firm_id,
            "client_name": "Alder Foods",
            "engagement_type": "AUDIT",
            "period_end": "2026-06-30",
            "engagement_partner_id": engagement_partner_id,
        },
        overrides,
    )


def workflow_transition_payload(to_state: str, **overrides) -> Dict[str, Any]:
    return _merge({"to_state": to_state}, overrides)


def file_transition_payload(to_state: str, **overrides) -> Dict[str, Any]:
    return _merge({"to_state": to_state}, overrides)


def quality_review_assignment_payload(
    reviewer_partner_id: str, expected_engagement_version: int, **overrides
):
    return _merge(
        {
            "reviewer_partner_id": reviewer_partner_id,
            "objectivity_attested": True,
            "expected_engagement_version": expected_engagement_version,
        },
        overrides,
    )


def quality_review_transition_payload(to_state: str, **overrides) -> Dict[str, Any]:
    return _merge({"to_state": to_state}, overrides)


def quality_risk_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "component": "ENGAGEMENT_PERFORMANCE",
            "quality_objective_code": "QO-A",
            "risk_statement": "Insufficient partner review of significant judgements.",
            "likelihood": 5,
            "impact": 5,
        },
        overrides,
    )


def risk_response_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "response_type": "PREVENTIVE",
            "description": "Mandatory second partner review of significant judgements.",
        },
        overrides,
    )


def effectiveness_test_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "design_effectiveness": "EFFECTIVE",
            "operating_effectiveness": "EFFECTIVE",
        },
        overrides,
    )


def risk_evaluation_payload(basis: str = "DESIGN_BASIS", **overrides):
    return _merge({"basis": basis}, overrides)


def internal_inspection_payload(**overrides) -> Dict[str, Any]:
    return _merge({"inspection_year": 2026, "target_engagement_count": 1}, overrides)


def inspection_transition_payload(to_state: str, **overrides) -> Dict[str, Any]:
    return _merge({"to_state": to_state}, overrides)


def inspection_finding_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "title": "Group audit instructions not evidenced",
            "sqm_component": "ENGAGEMENT_PERFORMANCE",
        },
        overrides,
    )


def classification_payload(classification: str, **overrides) -> Dict[str, Any]:
    """PRD 3.7: "Classification is a single write carrying three values: the
    ``classification`` itself, the ``pervasiveness`` ... and
    ``affects_report_conclusion``" - so all three are always supplied."""
    base: Dict[str, Any] = {
        "classification": classification,
        "pervasiveness": (
            "SYSTEMIC"
            if classification in ("SIGNIFICANT_DEFICIENCY", "MATERIAL_FAILURE")
            else "ISOLATED"
        ),
        "affects_report_conclusion": classification == "MATERIAL_FAILURE",
    }
    return _merge(base, overrides)


def finding_transition_payload(to_state: str, **overrides) -> Dict[str, Any]:
    return _merge({"to_state": to_state}, overrides)


def rca_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "method": "FISHBONE",
            "root_cause_category": "SUPERVISION_REVIEW",
            "contributing_factor_count": 4,
            "narrative": (
                "Reviewer workload prevented timely review of sampling workpapers."
            ),
        },
        overrides,
    )


def rca_validation_payload(outcome: str = "VALIDATED", **overrides):
    return _merge({"outcome": outcome}, overrides)


def remediation_plan_payload(
    root_cause_analysis_id: str,
    owner_partner_id: str,
    expected_finding_version: int,
    **overrides,
):
    return _merge(
        {
            "root_cause_analysis_id": root_cause_analysis_id,
            "owner_partner_id": owner_partner_id,
            "target_completion_date": "2026-09-01",
            "action_count": 5,
            "action_specificity_score": 8.00,
            "expected_finding_version": expected_finding_version,
        },
        overrides,
    )


def remediation_transition_payload(to_state: str, **overrides) -> Dict[str, Any]:
    return _merge({"to_state": to_state}, overrides)


def peer_reviewer_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "reviewer_firm_name": "Kestrel Peer Review PC",
            "license_state": "CA",
            "qualified_categories": [],
            "max_concurrent_reviews": 2,
            "experience_hours": 5000,
        },
        overrides,
    )


def peer_review_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "review_type": "SYSTEM_REVIEW",
            "year_end": "2026-12-31",
            "scheduled_window_start": "2026-09-01",
            "scheduled_window_end": "2026-09-15",
        },
        overrides,
    )


def reviewer_assignment_payload(reviewer_id: Optional[str] = None, **overrides):
    base: Dict[str, Any] = {}
    if reviewer_id is not None:
        base["reviewer_id"] = reviewer_id
    return _merge(base, overrides)


def peer_review_selection_payload(
    engagement_id: str, expected_peer_review_version: int, hours_committed: int = 10,
    **overrides,
):
    return _merge(
        {
            "engagement_id": engagement_id,
            "hours_committed": hours_committed,
            "is_scope_limitation": False,
            "expected_peer_review_version": expected_peer_review_version,
        },
        overrides,
    )


def disposition_payload(disposition: str, non_conforming: bool = False, **overrides):
    return _merge(
        {"disposition": disposition, "non_conforming": non_conforming}, overrides
    )


def peer_review_transition_payload(to_state: str, **overrides) -> Dict[str, Any]:
    return _merge({"to_state": to_state}, overrides)


def corrective_action_evidence_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "evidence_summary": (
                "Pre-issuance review programme adopted; two files re-reviewed by an "
                "external consultant."
            )
        },
        overrides,
    )


def corrective_action_disposition_payload(outcome: str = "ACCEPTED", **overrides):
    return _merge({"outcome": outcome}, overrides)


def designations(*values: str) -> List[str]:
    return list(values)
