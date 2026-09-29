"""Cross-entity state dependencies: a transition on one aggregate is gated on
the state of a different aggregate.

Two pairs are exercised: Engagement <-> EngagementQualityReview (clearing
quality review needs a CONCURRED review) and PeerReview <-> InternalInspection
(entering fieldwork needs the firm's latest inspection cycle concluded).
"""
from prd_bench_local_runner.testing import validate_error

from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.api_errors import (
    ERR_EQR_NOT_CONCURRED,
    ERR_INSPECTION_NOT_CONCLUDED,
)
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_fields,
    created_entity,
    read_entity,
)
from test_helpers.constants import DEFAULT_CLOCK
from test_helpers.test_users import (
    make_committee_headers,
    make_engagement_partner_headers,
    make_eq_reviewer_headers,
    make_peer_reviewer_headers,
    make_qc_director_headers,
    make_system_admin_headers,
)


# ---------------------------------------------------------------------------
# Engagement <-> EngagementQualityReview
# ---------------------------------------------------------------------------
def _engagement_awaiting_concurrence(api):
    """Firm, reviewer and an eqr_required engagement in EQR_PENDING whose
    quality review is still only ASSIGNED."""
    fixtures.set_clock(api, DEFAULT_CLOCK)
    admin = make_system_admin_headers()
    firm = created_entity(
        api.create_firm(
            f.firm_payload(
                legal_name="Thurlow Cane LLP",
                state_code="CA",
                aa_hours_last_year=400,
                peer_review_year_end="2026-12-31",
            ),
            headers=admin,
        )
    )
    ep = created_entity(
        api.create_partner(
            firm["id"],
            f.partner_payload(
                full_name="Eli Parch",
                cpa_license_state="CA",
                designations=["ENGAGEMENT_PARTNER"],
                cpe_hours_last_3y=200,
            ),
            headers=admin,
        )
    )
    qc = created_entity(
        api.create_partner(
            firm["id"],
            f.partner_payload(
                full_name="Quinn Cade",
                cpa_license_state="CA",
                designations=["QC_DIRECTOR"],
                cpe_hours_last_3y=200,
            ),
            headers=admin,
        )
    )
    reviewer = created_entity(
        api.create_partner(
            firm["id"],
            f.partner_payload(
                full_name="Sable Ord",
                cpa_license_state="CA",
                designations=["EQ_REVIEWER"],
                cpe_hours_last_3y=200,
            ),
            headers=admin,
        )
    )
    ep_headers = make_engagement_partner_headers(ep["id"])
    qc_headers = make_qc_director_headers(qc["id"])
    reviewer_headers = make_eq_reviewer_headers(reviewer["id"])

    engagement = created_entity(
        api.create_engagement(
            f.engagement_payload(
                firm["id"],
                ep["id"],
                client_name="Cinder Utilities",
                engagement_type="AUDIT",
                period_end="2026-06-30",
                is_public_interest=True,
            ),
            headers=ep_headers,
        )
    )
    in_fieldwork = read_entity(
        api.create_workflow_transition(
            engagement["id"], f.workflow_transition_payload("FIELDWORK"),
            headers=ep_headers,
        )
    )
    eqr = created_entity(
        api.assign_quality_review(
            engagement["id"],
            f.quality_review_assignment_payload(
                reviewer["id"], in_fieldwork["version"]
            ),
            headers=qc_headers,
        )
    )
    read_entity(
        api.create_workflow_transition(
            engagement["id"], f.workflow_transition_payload("EQR_PENDING"),
            headers=ep_headers,
        )
    )
    return {
        "firm": firm,
        "ep": ep,
        "qc": qc,
        "reviewer": reviewer,
        "ep_headers": ep_headers,
        "qc_headers": qc_headers,
        "reviewer_headers": reviewer_headers,
        "engagement": engagement,
        "eqr": eqr,
    }


def test_eqr_cleared_refused_while_review_is_only_assigned(api):
    """An eqr_required engagement cannot leave EQR_PENDING while its quality
    review is merely ASSIGNED.

    "When the engagement's `eqr_required` is true, the firm must be able to
    point at an engagement quality review of this engagement whose state is
    `CONCURRED`; if it cannot, the leg is refused with
    `ERR_EQR_NOT_CONCURRED`."

    Design: Difficulty/cross_entity_state_dependency/engagement_eqr_cleared_gated_on_concurred_quality_review
    """
    ctx = _engagement_awaiting_concurrence(api)

    response = api.create_workflow_transition(
        ctx["engagement"]["id"], f.workflow_transition_payload("EQR_CLEARED"),
        headers=ctx["ep_headers"],
    )
    validate_error(response, ERR_EQR_NOT_CONCURRED, expected_status=409)

    engagement = read_entity(
        api.get_engagement(ctx["engagement"]["id"], headers=ctx["ep_headers"])
    )
    assert_fields(
        engagement,
        eqr_required=True,
        workflow_state="EQR_PENDING",
        eqr_concurred_at=None,
    )
    review = read_entity(
        api.get_quality_review(ctx["eqr"]["id"], headers=ctx["qc_headers"])
    )
    assert_fields(review, state="ASSIGNED", concern_round_count=0)


def test_eqr_cleared_refused_while_review_is_in_progress(api):
    """A review that has merely begun does not satisfy the concurrence gate.

    "the firm must be able to point at an engagement quality review of this
    engagement whose state is `CONCURRED`"

    Design: Difficulty/cross_entity_state_dependency/engagement_eqr_cleared_gated_on_concurred_quality_review
    """
    ctx = _engagement_awaiting_concurrence(api)

    read_entity(
        api.create_quality_review_transition(
            ctx["eqr"]["id"], f.quality_review_transition_payload("IN_PROGRESS"),
            headers=ctx["reviewer_headers"],
        )
    )

    response = api.create_workflow_transition(
        ctx["engagement"]["id"], f.workflow_transition_payload("EQR_CLEARED"),
        headers=ctx["ep_headers"],
    )
    validate_error(response, ERR_EQR_NOT_CONCURRED, expected_status=409)

    engagement = read_entity(
        api.get_engagement(ctx["engagement"]["id"], headers=ctx["ep_headers"])
    )
    assert_fields(
        engagement, workflow_state="EQR_PENDING", eqr_concurred_at=None,
    )
    review = read_entity(
        api.get_quality_review(ctx["eqr"]["id"], headers=ctx["qc_headers"])
    )
    assert_fields(review, state="IN_PROGRESS")
    reviewer = read_entity(
        api.get_partner(ctx["reviewer"]["id"], headers=ctx["qc_headers"])
    )
    assert_fields(reviewer, open_eqr_count=1)


def test_eqr_cleared_succeeds_once_the_review_concurs(api):
    """The identical clearing call succeeds the moment the review reaches
    CONCURRED, stamping eqr_concurred_at.

    "On success the engagement's `eqr_concurred_at` is set to the
    `concluded_at` instant of the concurring review"

    Design: Difficulty/cross_entity_state_dependency/engagement_eqr_cleared_gated_on_concurred_quality_review
    """
    ctx = _engagement_awaiting_concurrence(api)

    read_entity(
        api.create_quality_review_transition(
            ctx["eqr"]["id"], f.quality_review_transition_payload("IN_PROGRESS"),
            headers=ctx["reviewer_headers"],
        )
    )
    concurred = read_entity(
        api.create_quality_review_transition(
            ctx["eqr"]["id"], f.quality_review_transition_payload("CONCURRED"),
            headers=ctx["reviewer_headers"],
        )
    )
    assert_fields(concurred, state="CONCURRED", concern_round_count=0)

    cleared = read_entity(
        api.create_workflow_transition(
            ctx["engagement"]["id"], f.workflow_transition_payload("EQR_CLEARED"),
            headers=ctx["ep_headers"],
        )
    )
    assert_fields(cleared, eqr_required=True, workflow_state="EQR_CLEARED")
    assert cleared["eqr_concurred_at"] is not None, (
        "eqr_concurred_at must be stamped from the concurring review"
    )

    engagement = read_entity(
        api.get_engagement(ctx["engagement"]["id"], headers=ctx["ep_headers"])
    )
    assert_fields(
        engagement,
        eqr_required=True,
        workflow_state="EQR_CLEARED",
        eqr_concurred_at=concurred["concluded_at"],
    )
    reviewer = read_entity(
        api.get_partner(ctx["reviewer"]["id"], headers=ctx["qc_headers"])
    )
    assert_fields(reviewer, open_eqr_count=0)


# ---------------------------------------------------------------------------
# PeerReview <-> InternalInspection
# ---------------------------------------------------------------------------
def _run_selector(api, inspection_id, headers):
    """Run the deterministic engagement selector for a cycle."""
    response = api.run_inspection_selector(inspection_id, headers=headers)
    assert response.status_code in (200, 201), (
        f"selector run failed: {response.status_code} {response.text}"
    )
    return response.json()["data"]


def _scoped_review_with_unfinished_inspection(api):
    """A peer review in SCOPE_SET whose firm's only inspection cycle - the
    highest inspection_year - sits in SELECTION_COMPLETE."""
    fixtures.set_clock(api, DEFAULT_CLOCK)
    admin = make_system_admin_headers()
    committee = make_committee_headers()
    firm = created_entity(
        api.create_firm(
            f.firm_payload(
                legal_name="Underhill Sway LLP",
                state_code="CA",
                aa_hours_last_year=400,
                peer_review_year_end="2026-12-31",
            ),
            headers=admin,
        )
    )
    qc = created_entity(
        api.create_partner(
            firm["id"],
            f.partner_payload(
                full_name="Quinn Cade",
                cpa_license_state="CA",
                designations=["QC_DIRECTOR"],
                cpe_hours_last_3y=200,
            ),
            headers=admin,
        )
    )
    qc_headers = make_qc_director_headers(qc["id"])
    reviewer = created_entity(
        api.create_peer_reviewer(
            f.peer_reviewer_payload(
                reviewer_firm_name="Kestrel Peer Review PC",
                license_state="CA",
                qualified_categories=[],
                max_concurrent_reviews=2,
                experience_hours=5000,
            ),
            headers=committee,
        )
    )
    reviewer_headers = make_peer_reviewer_headers(reviewer["id"])
    review = created_entity(
        api.create_peer_review(
            firm["id"],
            f.peer_review_payload(
                review_type="SYSTEM_REVIEW",
                year_end="2026-12-31",
                scheduled_window_start="2026-09-01",
                scheduled_window_end="2026-09-15",
            ),
            headers=committee,
        )
    )
    read_entity(
        api.assign_peer_reviewer(
            review["id"], f.reviewer_assignment_payload(reviewer["id"]),
            headers=committee,
        )
    )
    scoped = read_entity(
        api.set_peer_review_scope(review["id"], {}, headers=reviewer_headers)
    )
    inspection = created_entity(
        api.create_internal_inspection(
            firm["id"],
            f.internal_inspection_payload(inspection_year=2024, target_engagement_count=2),
            headers=qc_headers,
        )
    )
    _run_selector(api, inspection["id"], qc_headers)
    return {
        "firm": firm,
        "qc_headers": qc_headers,
        "committee": committee,
        "reviewer": reviewer,
        "reviewer_headers": reviewer_headers,
        "review": scoped,
        "inspection": inspection,
    }


def test_peer_review_fieldwork_refused_while_inspection_unfinished(api):
    """A scoped peer review cannot enter fieldwork while the firm's
    highest-year internal inspection cycle is not CONCLUDED.

    "The firm's internal inspection cycle with the highest `inspection_year`
    must exist and must have reached `CONCLUDED`; a firm with no cycle at all,
    or whose latest cycle is unfinished, blocks fieldwork with
    `ERR_INSPECTION_NOT_CONCLUDED`."

    Design: Difficulty/cross_entity_state_dependency/peer_review_fieldwork_gated_on_concluded_internal_inspection
    """
    ctx = _scoped_review_with_unfinished_inspection(api)

    inspection = read_entity(
        api.get_internal_inspection(
            ctx["inspection"]["id"], headers=ctx["qc_headers"]
        )
    )
    assert_fields(inspection, state="SELECTION_COMPLETE", engagements_selected_count=0)

    response = api.create_peer_review_transition(
        ctx["review"]["id"], f.peer_review_transition_payload("FIELDWORK"),
        headers=ctx["reviewer_headers"],
    )
    validate_error(response, ERR_INSPECTION_NOT_CONCLUDED, expected_status=409)

    review = read_entity(
        api.get_peer_review(ctx["review"]["id"], headers=ctx["reviewer_headers"])
    )
    assert_fields(
        review,
        state="SCOPE_SET",
        must_select_categories=[],
        total_scope_hours=16,
        unallocated_hours=16,
    )


def test_peer_review_fieldwork_succeeds_once_inspection_concluded(api):
    """The identical fieldwork call succeeds once that inspection cycle
    reaches CONCLUDED.

    "from `SELECTION_COMPLETE` it may go straight to `CONCLUDED` provided
    `engagements_selected_count` is 0 and `must_select_coverage_pct` is
    100.00"

    Design: Difficulty/cross_entity_state_dependency/peer_review_fieldwork_gated_on_concluded_internal_inspection
    """
    ctx = _scoped_review_with_unfinished_inspection(api)

    response = api.create_peer_review_transition(
        ctx["review"]["id"], f.peer_review_transition_payload("FIELDWORK"),
        headers=ctx["reviewer_headers"],
    )
    validate_error(response, ERR_INSPECTION_NOT_CONCLUDED, expected_status=409)

    concluded = read_entity(
        api.create_inspection_transition(
            ctx["inspection"]["id"], f.inspection_transition_payload("CONCLUDED"),
            headers=ctx["qc_headers"],
        )
    )
    assert_fields(concluded, state="CONCLUDED")
    assert_decimal_equals(concluded["must_select_coverage_pct"], 100.00)

    entered = read_entity(
        api.create_peer_review_transition(
            ctx["review"]["id"], f.peer_review_transition_payload("FIELDWORK"),
            headers=ctx["reviewer_headers"],
        )
    )
    assert_fields(entered, state="FIELDWORK")

    review = read_entity(
        api.get_peer_review(ctx["review"]["id"], headers=ctx["reviewer_headers"])
    )
    assert_fields(
        review,
        state="FIELDWORK",
        must_select_categories=[],
        total_scope_hours=16,
        unallocated_hours=16,
    )
