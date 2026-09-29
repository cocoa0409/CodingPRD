"""Composite state builders.

Every test starts against an empty database, so all state is built here from
scratch through the endpoints the PRD declares.  Callers that need an
ownership-gated or firm-scoped call always receive headers built from the id of
the entity backing the role, never a shared placeholder identity.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_success

from . import factories as f
from .constants import DEFAULT_CLOCK
from .test_users import (
    make_committee_headers,
    make_engagement_partner_headers,
    make_eq_reviewer_headers,
    make_managing_partner_headers,
    make_peer_reviewer_headers,
    make_qc_director_headers,
    make_system_admin_headers,
)

ADMIN = make_system_admin_headers()
COMMITTEE = make_committee_headers()


def _data(response, status: int) -> Dict[str, Any]:
    validate_success(response, expected_status=status)
    return get_success_data(response)


def set_clock(api, current_utc: str = DEFAULT_CLOCK) -> None:
    validate_success(api.set_clock(current_utc, headers=ADMIN), expected_status=200)


# ---------------------------------------------------------------------------
# Firm and staff
# ---------------------------------------------------------------------------
def new_firm(api, **overrides) -> Dict[str, Any]:
    return _data(api.create_firm(f.firm_payload(**overrides), headers=ADMIN), 201)


def new_partner(api, firm_id: str, **overrides) -> Dict[str, Any]:
    return _data(
        api.create_partner(firm_id, f.partner_payload(**overrides), headers=ADMIN), 201
    )


def firm_context(api, **firm_overrides) -> Dict[str, Any]:
    """A firm with a managing partner, a QC director and one engagement partner."""
    firm = new_firm(api, **firm_overrides)
    firm_id = firm["id"]
    mp = new_partner(
        api, firm_id, full_name="Mara Deane", designations=["MANAGING_PARTNER"]
    )
    qc = new_partner(
        api, firm_id, full_name="Quinn Cade", designations=["QC_DIRECTOR"]
    )
    ep = new_partner(
        api, firm_id, full_name="Eli Parch", designations=["ENGAGEMENT_PARTNER"]
    )
    return {
        "firm": firm,
        "firm_id": firm_id,
        "mp": mp,
        "mp_headers": make_managing_partner_headers(mp["id"]),
        "qc": qc,
        "qc_headers": make_qc_director_headers(qc["id"]),
        "ep": ep,
        "ep_headers": make_engagement_partner_headers(ep["id"]),
    }


def add_engagement_partner(api, ctx, full_name: str, **overrides) -> Dict[str, Any]:
    partner = new_partner(
        api,
        ctx["firm_id"],
        full_name=full_name,
        designations=["ENGAGEMENT_PARTNER"],
        **overrides,
    )
    return partner


def add_eq_reviewer(api, ctx, full_name: str = "Ivo Renn", **overrides):
    """A partner eligible to act as engagement quality reviewer."""
    payload = dict(
        full_name=full_name, designations=["EQ_REVIEWER"], cpe_hours_last_3y=200
    )
    payload.update(overrides)
    return new_partner(api, ctx["firm_id"], **payload)


# ---------------------------------------------------------------------------
# Engagements
# ---------------------------------------------------------------------------
def new_engagement(api, ctx, partner: Optional[Dict] = None, **overrides):
    partner = partner or ctx["ep"]
    headers = make_engagement_partner_headers(partner["id"])
    return _data(
        api.create_engagement(
            f.engagement_payload(ctx["firm_id"], partner["id"], **overrides),
            headers=headers,
        ),
        201,
    )


def workflow_step(api, engagement: Dict, to_state: str, headers: Dict) -> Dict:
    return _data(
        api.create_workflow_transition(
            engagement["id"], f.workflow_transition_payload(to_state), headers=headers
        ),
        200,
    )


def file_step(api, engagement: Dict, to_state: str, headers: Dict) -> Dict:
    return _data(
        api.create_file_transition(
            engagement["id"], f.file_transition_payload(to_state), headers=headers
        ),
        200,
    )


def read_engagement(api, engagement_id: str, headers: Dict) -> Dict:
    return _data(api.get_engagement(engagement_id, headers=headers), 200)


def concurred_quality_review(
    api, ctx, engagement: Dict, reviewer: Dict, assigner_headers: Optional[Dict] = None
) -> Dict:
    """Assign a reviewer to an engagement in its review window and concur."""
    headers = assigner_headers or ctx["qc_headers"]
    current = read_engagement(api, engagement["id"], headers)
    eqr = _data(
        api.assign_quality_review(
            engagement["id"],
            f.quality_review_assignment_payload(reviewer["id"], current["version"]),
            headers=headers,
        ),
        201,
    )
    reviewer_headers = make_eq_reviewer_headers(reviewer["id"])
    _data(
        api.create_quality_review_transition(
            eqr["id"],
            f.quality_review_transition_payload("IN_PROGRESS"),
            headers=reviewer_headers,
        ),
        200,
    )
    return _data(
        api.create_quality_review_transition(
            eqr["id"],
            f.quality_review_transition_payload("CONCURRED"),
            headers=reviewer_headers,
        ),
        200,
    )


def released_engagement(
    api, ctx, partner: Optional[Dict] = None, reviewer: Optional[Dict] = None,
    **overrides,
) -> Dict[str, Any]:
    """An engagement driven all the way to REPORT_RELEASED."""
    partner = partner or ctx["ep"]
    ep_headers = make_engagement_partner_headers(partner["id"])
    engagement = new_engagement(api, ctx, partner=partner, **overrides)
    workflow_step(api, engagement, "FIELDWORK", ep_headers)
    workflow_step(api, engagement, "EQR_PENDING", ep_headers)
    current = read_engagement(api, engagement["id"], ep_headers)
    if current["eqr_required"]:
        if reviewer is None:
            reviewer = add_eq_reviewer(
                api, ctx, full_name=f"Reviewer for {current['client_name']}"
            )
        concurred_quality_review(api, ctx, engagement, reviewer)
    workflow_step(api, engagement, "EQR_CLEARED", ep_headers)
    return workflow_step(api, engagement, "REPORT_RELEASED", ep_headers)


# ---------------------------------------------------------------------------
# Quality risks
# ---------------------------------------------------------------------------
def new_quality_risk(api, ctx, **overrides) -> Dict[str, Any]:
    return _data(
        api.create_quality_risk(
            ctx["firm_id"], f.quality_risk_payload(**overrides), headers=ctx["qc_headers"]
        ),
        201,
    )


def new_risk_response(api, ctx, risk_id: str, **overrides) -> Dict[str, Any]:
    return _data(
        api.create_risk_response(
            risk_id, f.risk_response_payload(**overrides), headers=ctx["qc_headers"]
        ),
        201,
    )


def record_effectiveness_test(api, ctx, response_id: str, **overrides) -> Dict[str, Any]:
    return _data(
        api.create_effectiveness_test(
            response_id, f.effectiveness_test_payload(**overrides),
            headers=ctx["qc_headers"],
        ),
        200,
    )


# ---------------------------------------------------------------------------
# Internal inspections
# ---------------------------------------------------------------------------
def new_inspection(api, ctx, **overrides) -> Dict[str, Any]:
    return _data(
        api.create_internal_inspection(
            ctx["firm_id"], f.internal_inspection_payload(**overrides),
            headers=ctx["qc_headers"],
        ),
        201,
    )


def run_selector(api, ctx, inspection_id: str) -> Dict[str, Any]:
    """A selector run is a modification, so it answers 200 with the cycle."""
    return _data(
        api.run_inspection_selector(inspection_id, headers=ctx["qc_headers"]), 200
    )


def selections_of(api, ctx, inspection_id: str) -> List[Dict[str, Any]]:
    response = api.list_inspection_selections(
        headers=ctx["qc_headers"], params={"inspection_id": inspection_id}
    )
    validate_success(response, expected_status=200)
    return response.json()["data"]


def inspection_step(api, ctx, inspection_id: str, to_state: str, **extra):
    return _data(
        api.create_inspection_transition(
            inspection_id, f.inspection_transition_payload(to_state, **extra),
            headers=ctx["qc_headers"],
        ),
        200,
    )


def new_finding(api, ctx, selection_id: str, **overrides) -> Dict[str, Any]:
    return _data(
        api.create_inspection_finding(
            selection_id, f.inspection_finding_payload(**overrides),
            headers=ctx["qc_headers"],
        ),
        201,
    )


def classify(api, ctx, finding_id: str, classification: str, **overrides):
    return _data(
        api.classify_finding(
            finding_id, f.classification_payload(classification, **overrides),
            headers=ctx["qc_headers"],
        ),
        200,
    )


def validated_rca(api, ctx, finding_id: str, **overrides) -> Dict[str, Any]:
    rca = _data(
        api.create_root_cause_analysis(
            finding_id, f.rca_payload(**overrides), headers=ctx["qc_headers"]
        ),
        201,
    )
    return _data(
        api.create_rca_validation(
            rca["id"], f.rca_validation_payload("VALIDATED"), headers=ctx["qc_headers"]
        ),
        200,
    )


def new_remediation_plan(api, ctx, finding_id: str, rca_id: str, owner_id: str, **overrides):
    finding = _data(
        api.get_inspection_finding(finding_id, headers=ctx["qc_headers"]), 200
    )
    return _data(
        api.create_remediation_plan(
            finding_id,
            f.remediation_plan_payload(
                rca_id, owner_id, finding["version"], **overrides
            ),
            headers=ctx["qc_headers"],
        ),
        201,
    )


def plan_step(api, ctx, plan_id: str, to_state: str, **extra) -> Dict[str, Any]:
    return _data(
        api.create_remediation_plan_transition(
            plan_id, f.remediation_transition_payload(to_state, **extra),
            headers=ctx["qc_headers"],
        ),
        200,
    )


# ---------------------------------------------------------------------------
# Peer review
# ---------------------------------------------------------------------------
def new_peer_reviewer(api, **overrides) -> Dict[str, Any]:
    return _data(
        api.create_peer_reviewer(f.peer_reviewer_payload(**overrides), headers=COMMITTEE),
        201,
    )


def new_peer_review(api, firm_id: str, **overrides) -> Dict[str, Any]:
    return _data(
        api.create_peer_review(firm_id, f.peer_review_payload(**overrides), headers=COMMITTEE),
        201,
    )


def assign_reviewer(api, peer_review_id: str, reviewer_id: Optional[str] = None):
    return _data(
        api.assign_peer_reviewer(
            peer_review_id, f.reviewer_assignment_payload(reviewer_id), headers=COMMITTEE
        ),
        200,
    )


def set_scope(api, peer_review_id: str, reviewer_id: str) -> Dict[str, Any]:
    return _data(
        api.set_peer_review_scope(
            peer_review_id, {}, headers=make_peer_reviewer_headers(reviewer_id)
        ),
        200,
    )


def select_engagement(
    api, peer_review_id: str, reviewer_id: str, engagement_id: str,
    hours_committed: int = 10, **overrides,
) -> Dict[str, Any]:
    headers = make_peer_reviewer_headers(reviewer_id)
    review = _data(api.get_peer_review(peer_review_id, headers=headers), 200)
    return _data(
        api.create_peer_review_selection(
            peer_review_id,
            f.peer_review_selection_payload(
                engagement_id, review["version"], hours_committed, **overrides
            ),
            headers=headers,
        ),
        201,
    )


def peer_review_step(api, peer_review_id: str, to_state: str, headers: Dict):
    return _data(
        api.create_peer_review_transition(
            peer_review_id, f.peer_review_transition_payload(to_state), headers=headers
        ),
        200,
    )


def record_disposition(
    api, selection_id: str, reviewer_id: str, disposition: str,
    non_conforming: bool = False,
) -> Dict[str, Any]:
    return _data(
        api.create_selection_disposition(
            selection_id,
            f.disposition_payload(disposition, non_conforming),
            headers=make_peer_reviewer_headers(reviewer_id),
        ),
        200,
    )


def corrective_action_plans_of(api, peer_review_id: str) -> List[Dict[str, Any]]:
    response = api.list_corrective_action_plans(
        headers=COMMITTEE, params={"peer_review_id": peer_review_id}
    )
    validate_success(response, expected_status=200)
    return response.json()["data"]
