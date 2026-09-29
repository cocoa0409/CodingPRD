"""Access-control corners: exclusive endpoints, ownership, segregation of duties
and firm isolation.

Every actor here is built from a real persisted row, because the refusals under
test (PRD 2.1) compare `X-User-ID` against the resource's own partner or
reviewer foreign keys rather than against the endpoint's role list.
"""
from typing import Dict

from prd_bench_local_runner.testing import validate_error, validate_error_is_one_of

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_fields,
    created_entity,
    read_entity,
)
from test_helpers.constants import DEFAULT_CLOCK
from test_helpers.test_users import (
    make_eq_reviewer_headers,
    make_peer_reviewer_headers,
    make_qc_director_headers,
)

ALL_CATEGORIES = [
    "ERISA_AUDIT",
    "SINGLE_AUDIT",
    "BROKER_DEALER",
    "GOVERNMENTAL",
    "PUBLIC_INTEREST",
]


def _firm(api, legal_name: str, **overrides) -> Dict:
    """A Texas firm in the 10000-hour tier with its three firm-side partners."""
    payload = dict(
        legal_name=legal_name,
        state_code="TX",
        aa_hours_last_year=9000,
        peer_review_year_end="2026-06-30",
    )
    payload.update(overrides)
    return fixtures.firm_context(api, **payload)


def _run_selector(api, headers: Dict, inspection_id: str) -> None:
    """Run the deterministic engagement selector for a cycle (setup only)."""
    response = api.run_inspection_selector(inspection_id, headers=headers)
    assert response.status_code in (200, 201), (
        f"selector run failed: {response.status_code} {response.text}"
    )


def test_selector_run_is_exclusive_to_the_quality_control_director(api):
    """Running the inspection selector is refused to roles the endpoint does not
    authorise, before any selection row is written.

    "When `X-User-Role` is not listed among the roles authorised for the
    requested endpoint (see the table in 4), the request fails with
    `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/qc_director_exclusive_selector_run_is_denied_to_other_roles
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    ctx = _firm(api, "Harbor & Vance LLP")
    inspection = fixtures.new_inspection(
        api, ctx, inspection_year=2026, target_engagement_count=1
    )

    denied = api.run_inspection_selector(inspection["id"], headers=ctx["ep_headers"])
    validate_error(denied, E.ERR_ROLE_NOT_PERMITTED, expected_status=403)

    untouched = read_entity(
        api.get_internal_inspection(inspection["id"], headers=ctx["qc_headers"])
    )
    assert_fields(
        untouched, state="PLANNING", engagements_selected_count=0, version=1
    )

    _run_selector(api, ctx["qc_headers"], inspection["id"])
    after = read_entity(
        api.get_internal_inspection(inspection["id"], headers=ctx["qc_headers"])
    )
    assert_fields(after, state="SELECTION_COMPLETE")

    # Partner maintenance belongs to the managing partner, not the QC director.
    validate_error(
        api.update_partner(
            ctx["ep"]["id"], {"cpe_hours_last_3y": 130}, headers=ctx["qc_headers"]
        ),
        E.ERR_ROLE_NOT_PERMITTED,
        expected_status=403,
    )
    # The reviewer roster belongs to the peer review committee.
    validate_error(
        api.create_peer_reviewer(f.peer_reviewer_payload(), headers=ctx["mp_headers"]),
        E.ERR_ROLE_NOT_PERMITTED,
        expected_status=403,
    )


def test_peer_reviewer_cannot_scope_a_review_assigned_to_another_reviewer(api):
    """A peer reviewer may only act on the review whose assigned_reviewer_id is
    their own id; a fellow reviewer is refused as a non-owner.

    "when a `PeerReviewer` performs it, `X-User-ID` must equal
    `assigned_reviewer_id`, otherwise `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/peer_reviewer_cannot_scope_another_reviewers_review
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    ctx = _firm(api, "Harbor & Vance LLP")
    reviewer_a = fixtures.new_peer_reviewer(
        api,
        reviewer_firm_name="Calder & Boone PC",
        license_state="TX",
        qualified_categories=ALL_CATEGORIES,
        experience_hours=4000,
    )
    reviewer_b = fixtures.new_peer_reviewer(
        api,
        reviewer_firm_name="Halstead Peer Review LLC",
        license_state="TX",
        qualified_categories=ALL_CATEGORIES,
        experience_hours=3000,
    )
    headers_a = make_peer_reviewer_headers(reviewer_a["id"])
    headers_b = make_peer_reviewer_headers(reviewer_b["id"])
    review = fixtures.new_peer_review(
        api,
        ctx["firm_id"],
        year_end="2026-06-30",
        scheduled_window_start="2026-10-01",
        scheduled_window_end="2026-10-15",
    )
    fixtures.assign_reviewer(api, review["id"], reviewer_a["id"])

    denied = api.set_peer_review_scope(review["id"], {}, headers=headers_b)
    validate_error(denied, E.ERR_NOT_RESOURCE_OWNER, expected_status=403)

    still_planning = read_entity(api.get_peer_review(review["id"], headers=headers_a))
    assert_fields(
        still_planning,
        state="PLANNING",
        total_scope_hours=None,
        unallocated_hours=None,
    )

    scoped = read_entity(api.set_peer_review_scope(review["id"], {}, headers=headers_a))
    assert_fields(scoped, state="SCOPE_SET")

    engagement = fixtures.new_engagement(
        api,
        ctx,
        client_name="Aurora Metals Inc",
        engagement_type="REVIEW",
        period_end="2026-03-31",
    )
    validate_error(
        api.create_peer_review_selection(
            review["id"],
            f.peer_review_selection_payload(
                engagement["id"], scoped["version"], hours_committed=12
            ),
            headers=headers_b,
        ),
        E.ERR_NOT_RESOURCE_OWNER,
        expected_status=403,
    )

    selection = fixtures.select_engagement(
        api, review["id"], reviewer_a["id"], engagement["id"], hours_committed=12
    )
    validate_error(
        api.delete_peer_review_selection(
            review["id"], selection["id"], headers=headers_b
        ),
        E.ERR_NOT_RESOURCE_OWNER,
        expected_status=403,
    )

    # The same ownership rule binds the internal engagement quality reviewer.
    second = fixtures.new_engagement(
        api,
        ctx,
        client_name="Borealis Pension Trust",
        engagement_type="ERISA_AUDIT",
        period_end="2026-04-30",
    )
    fixtures.workflow_step(api, second, "FIELDWORK", ctx["ep_headers"])
    assigned_reviewer = fixtures.add_eq_reviewer(api, ctx, full_name="Lena Ortiz")
    other_partner = fixtures.add_eq_reviewer(api, ctx, full_name="Nils Braga")
    current = fixtures.read_engagement(api, second["id"], ctx["qc_headers"])
    eqr = created_entity(
        api.assign_quality_review(
            second["id"],
            f.quality_review_assignment_payload(
                assigned_reviewer["id"], current["version"]
            ),
            headers=ctx["qc_headers"],
        )
    )
    validate_error(
        api.create_quality_review_transition(
            eqr["id"],
            f.quality_review_transition_payload("IN_PROGRESS"),
            headers=make_eq_reviewer_headers(other_partner["id"]),
        ),
        E.ERR_NOT_RESOURCE_OWNER,
        expected_status=403,
    )


def test_quality_control_director_cannot_raise_a_finding_on_his_own_engagement(api):
    """A director who personally led the inspected engagement is refused the
    finding even though the role list admits him.

    "the acting director must not be that engagement's own engagement partner,
    otherwise `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/qc_director_cannot_raise_a_finding_on_his_own_engagement
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    ctx = _firm(api, "Harbor & Vance LLP")
    dual = fixtures.new_partner(
        api,
        ctx["firm_id"],
        full_name="Tobias Reyes",
        cpa_license_state="TX",
        designations=["ENGAGEMENT_PARTNER", "QC_DIRECTOR"],
        cpe_hours_last_3y=100,
    )
    engagement = fixtures.released_engagement(
        api,
        ctx,
        partner=dual,
        client_name="Kestrel Foundry Co",
        engagement_type="REVIEW",
        period_end="2026-02-28",
    )
    inspection = fixtures.new_inspection(
        api, ctx, inspection_year=2026, target_engagement_count=1
    )
    _run_selector(api, ctx["qc_headers"], inspection["id"])
    selections = fixtures.selections_of(api, ctx, inspection["id"])
    assert len(selections) == 1, f"expected one selection, got {selections}"
    selection = selections[0]
    assert selection["engagement_id"] == engagement["id"]
    fixtures.inspection_step(api, ctx, inspection["id"], "IN_PROGRESS")

    finding_payload = f.inspection_finding_payload(
        title="Estimate testing lacked corroborating evidence",
        sqm_component="ENGAGEMENT_PERFORMANCE",
    )
    denied = api.create_inspection_finding(
        selection["id"], finding_payload, headers=make_qc_director_headers(dual["id"])
    )
    validate_error(denied, E.ERR_SEGREGATION_OF_DUTIES, expected_status=403)

    untouched = read_entity(
        api.get_inspection_selection(selection["id"], headers=ctx["qc_headers"])
    )
    assert_fields(untouched, finding_count=0)
    firm = read_entity(api.get_firm(ctx["firm_id"], headers=ctx["qc_headers"]))
    assert_fields(firm, open_deficiency_count=0)

    allowed = created_entity(
        api.create_inspection_finding(
            selection["id"], finding_payload, headers=ctx["qc_headers"]
        )
    )
    assert_fields(allowed, classification="UNCLASSIFIED", state="IDENTIFIED")


def test_remediation_plan_owner_cannot_accept_his_own_plan(api):
    """The identity that must submit a remediation plan is the identity forbidden
    to return or accept it.

    "The same code refuses the owner of a remediation plan who attempts to return
    or accept that plan"

    Design: Corner/rbac/remediation_plan_owner_cannot_accept_his_own_plan
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    ctx = _firm(api, "Harbor & Vance LLP")
    fixtures.released_engagement(
        api,
        ctx,
        client_name="Aurora Metals Inc",
        engagement_type="REVIEW",
        period_end="2026-03-31",
    )
    inspection = fixtures.new_inspection(
        api, ctx, inspection_year=2026, target_engagement_count=1
    )
    _run_selector(api, ctx["qc_headers"], inspection["id"])
    selection = fixtures.selections_of(api, ctx, inspection["id"])[0]
    fixtures.inspection_step(api, ctx, inspection["id"], "IN_PROGRESS")
    finding = fixtures.new_finding(
        api,
        ctx,
        selection["id"],
        title="Review notes not cleared before report release",
        sqm_component="ENGAGEMENT_PERFORMANCE",
    )
    fixtures.classify(
        api,
        ctx,
        finding["id"],
        "DEFICIENCY",
        pervasiveness="ISOLATED",
        affects_report_conclusion=False,
    )
    rca = fixtures.validated_rca(
        api,
        ctx,
        finding["id"],
        method="FISHBONE",
        root_cause_category="SUPERVISION_REVIEW",
        contributing_factor_count=3,
    )
    plan = fixtures.new_remediation_plan(
        api,
        ctx,
        finding["id"],
        rca["id"],
        ctx["mp"]["id"],
        target_completion_date="2026-09-30",
        action_count=4,
        action_specificity_score=8.00,
    )

    # The owner's own submission leg is mandatory, and it scores the plan.
    submitted = read_entity(
        api.create_remediation_plan_transition(
            plan["id"],
            f.remediation_transition_payload("SUBMITTED", completed_action_count=4),
            headers=ctx["mp_headers"],
        )
    )
    assert_fields(submitted, state="SUBMITTED", completeness_tier="STRONG")
    assert_decimal_equals(submitted["acceptance_score"], 8.90)

    validate_error(
        api.create_remediation_plan_transition(
            plan["id"],
            f.remediation_transition_payload("RETURNED"),
            headers=ctx["mp_headers"],
        ),
        E.ERR_SEGREGATION_OF_DUTIES,
        expected_status=403,
    )
    validate_error(
        api.create_remediation_plan_transition(
            plan["id"],
            f.remediation_transition_payload("ACCEPTED"),
            headers=ctx["mp_headers"],
        ),
        E.ERR_SEGREGATION_OF_DUTIES,
        expected_status=403,
    )

    still_submitted = read_entity(
        api.get_remediation_plan(plan["id"], headers=ctx["qc_headers"])
    )
    assert_fields(
        still_submitted,
        state="SUBMITTED",
        accepted_at=None,
        completeness_tier="STRONG",
    )
    assert_decimal_equals(still_submitted["acceptance_score"], 8.90)
    finding_now = read_entity(
        api.get_inspection_finding(finding["id"], headers=ctx["qc_headers"])
    )
    assert_fields(finding_now, state="REMEDIATION_ASSIGNED")

    accepted = read_entity(
        api.create_remediation_plan_transition(
            plan["id"],
            f.remediation_transition_payload("ACCEPTED"),
            headers=ctx["qc_headers"],
        )
    )
    assert_fields(accepted, state="ACCEPTED")
    assert accepted["accepted_at"] is not None, "acceptance must stamp accepted_at"


def test_managing_partner_cannot_reach_another_firms_engagement(api):
    """A Partner-backed actor is confined to the firm named by their own
    Partner.firm_id, while the resource's own firm reads it successfully.

    "Such an actor may only read or write resources belonging to the firm named
    by their own `Partner.firm_id` ... A cross-firm attempt is refused with
    `ERR_CROSS_FIRM_ACCESS_DENIED` (HTTP 403)."

    Design: Corner/rbac/managing_partner_cannot_reach_another_firms_engagement
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    firm_a = _firm(api, "Harbor & Vance LLP")
    engagement = fixtures.new_engagement(
        api,
        firm_a,
        client_name="Aurora Metals Inc",
        engagement_type="REVIEW",
        period_end="2026-03-31",
    )
    firm_b = _firm(
        api, "Northgate Audit Group", state_code="NV", aa_hours_last_year=400
    )
    fixtures.new_engagement(
        api,
        firm_b,
        client_name="Silverbrook Utilities",
        engagement_type="REVIEW",
        period_end="2026-05-31",
    )

    denied = api.get_engagement(engagement["id"], headers=firm_b["mp_headers"])
    validate_error(denied, E.ERR_CROSS_FIRM_ACCESS_DENIED, expected_status=403)

    own = read_entity(api.get_engagement(engagement["id"], headers=firm_a["mp_headers"]))
    assert_fields(own, client_name="Aurora Metals Inc")

    # A cross-firm write is refused on identity grounds and leaks nothing: the
    # PRD's evaluation order runs the ownership comparison (step 9) ahead of firm
    # isolation (step 10), so either identity refusal is a conforming answer.
    write = api.create_workflow_transition(
        engagement["id"],
        f.workflow_transition_payload("FIELDWORK"),
        headers=firm_b["mp_headers"],
    )
    assert write.status_code == 403, (
        f"cross-firm write must be refused with 403, got {write.status_code}"
    )
    validate_error_is_one_of(
        write, [E.ERR_CROSS_FIRM_ACCESS_DENIED, E.ERR_NOT_RESOURCE_OWNER]
    )

    validate_error(
        api.get_firm(firm_a["firm_id"], headers=firm_b["mp_headers"]),
        E.ERR_CROSS_FIRM_ACCESS_DENIED,
        expected_status=403,
    )

    after = read_entity(
        api.get_engagement(engagement["id"], headers=firm_a["mp_headers"])
    )
    assert_fields(after, workflow_state="PLANNING", version=1)


def test_quality_risk_creation_is_shared_while_response_design_is_not(api):
    """Recording a quality risk is shared by the two firm-side quality roles, but
    designing a response against it is the QC director's alone.

    "`ERR_ROLE_NOT_PERMITTED` (HTTP 403)" is raised "When `X-User-Role` is not
    listed among the roles authorised for the requested endpoint".

    Design: Corner/rbac/quality_risk_creation_is_shared_while_response_design_is_not
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    ctx = _firm(api, "Harbor & Vance LLP")
    risk_payload = f.quality_risk_payload(
        component="GOVERNANCE_LEADERSHIP",
        quality_objective_code="GL-01",
        risk_statement=(
            "Firm leadership may not reinforce quality objectives in partner "
            "evaluations."
        ),
        likelihood=3,
        impact=4,
    )

    risk = created_entity(
        api.create_quality_risk(ctx["firm_id"], risk_payload, headers=ctx["mp_headers"])
    )
    assert_fields(
        risk,
        state="ASSESSED",
        inherent_risk_score=12,
        response_count=0,
        version=1,
    )

    validate_error(
        api.create_risk_response(
            risk["id"], f.risk_response_payload(), headers=ctx["mp_headers"]
        ),
        E.ERR_ROLE_NOT_PERMITTED,
        expected_status=403,
    )
    created_entity(
        api.create_risk_response(
            risk["id"], f.risk_response_payload(), headers=ctx["qc_headers"]
        )
    )
    responded = read_entity(
        api.get_quality_risk(risk["id"], headers=ctx["qc_headers"])
    )
    assert_fields(responded, state="RESPONDED")

    validate_error(
        api.create_quality_risk(
            ctx["firm_id"], risk_payload, headers=ctx["ep_headers"]
        ),
        E.ERR_ROLE_NOT_PERMITTED,
        expected_status=403,
    )
