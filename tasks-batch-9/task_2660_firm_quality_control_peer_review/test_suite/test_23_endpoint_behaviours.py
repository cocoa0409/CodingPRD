"""Endpoint-behaviour tests for the Firm Quality Control & Peer Review API.

Each test exercises one declared endpoint end to end — its status code, the shape of
the resource it returns, and the side effects the PRD attaches to it.
"""
from test_helpers import assertions, factories as f, fixtures
from test_helpers.test_users import (
    make_committee_headers,
    make_peer_reviewer_headers,
    make_system_admin_headers,
)

CLOCK = "2026-08-01T00:00:00Z"

FIRM_KWARGS = dict(
    legal_name="Harbor & Vance LLP",
    state_code="TX",
    aa_hours_last_year=9000,
    enrolled_program="AICPA_PRC",
    peer_review_year_end="2026-06-30",
)

REVIEW_ENGAGEMENT = dict(
    client_name="Aurora Metals Inc",
    engagement_type="REVIEW",
    period_end="2026-03-31",
)

ERISA_ENGAGEMENT = dict(
    client_name="Borealis Pension Trust",
    engagement_type="ERISA_AUDIT",
    period_end="2026-04-30",
)

ROSTER_REVIEWER = dict(
    reviewer_firm_name="Calder & Boone PC",
    license_state="TX",
    qualified_categories=[
        "ERISA_AUDIT",
        "SINGLE_AUDIT",
        "BROKER_DEALER",
        "GOVERNMENTAL",
        "PUBLIC_INTEREST",
    ],
    max_concurrent_reviews=2,
    experience_hours=4000,
)

SYSTEM_REVIEW = dict(
    review_type="SYSTEM_REVIEW",
    year_end="2026-06-30",
    scheduled_window_start="2026-10-01",
    scheduled_window_end="2026-10-15",
)


def _scope(api, review_id, reviewer_id):
    return assertions.read_entity(
        api.set_peer_review_scope(
            review_id, {}, headers=make_peer_reviewer_headers(reviewer_id)
        ),
        200,
    )


def test_firm_patch_raises_the_base_tier_of_a_later_scope(api):
    """Committee maintenance of aa_hours_last_year re-tiers a scope determined afterwards.

    "A revision to `aa_hours_last_year` changes the base tier of any peer review whose
    scope is determined afterwards but never restates a scope already set."

    Design: Corner/endpoints/firm_patch_raises_the_base_tier_of_a_later_scope
    """
    fixtures.set_clock(api, CLOCK)
    committee = make_committee_headers()
    ctx = fixtures.firm_context(api, **FIRM_KWARGS)
    fixtures.released_engagement(api, ctx, **REVIEW_ENGAGEMENT)
    reviewer = fixtures.new_peer_reviewer(api, **ROSTER_REVIEWER)
    review = fixtures.new_peer_review(api, ctx["firm_id"], **SYSTEM_REVIEW)
    fixtures.assign_reviewer(api, review["id"], reviewer["id"])
    assertions.read_entity(
        api.update_firm(
            ctx["firm_id"], {"aa_hours_last_year": 20000}, headers=committee
        ),
        200,
    )

    scoped = _scope(api, review["id"], reviewer["id"])

    assertions.assert_fields(
        scoped,
        total_scope_hours=64,
        unallocated_hours=64,
        must_select_categories=[],
    )
    firm = assertions.read_entity(api.get_firm(ctx["firm_id"], headers=committee), 200)
    assertions.assert_fields(
        firm,
        aa_hours_last_year=20000,
        version=2,
        state_code="TX",
        peer_review_year_end="2026-06-30",
        enrolled_program="AICPA_PRC",
    )


def test_quality_management_summary_is_a_pure_computed_read(api):
    """The summary agrees with the rows it derives from and mutates nothing.

    "Computed read of the firm's current quality-management posture: `risk_posture`,
    `critical_risk_count`, `open_deficiency_count`, `open_material_failure_count`,
    `last_peer_review_rating`, `unassigned_review_flag`, the must-select categories the
    firm would attract this cycle, and the state of its latest inspection cycle."

    Design: Corner/endpoints/quality_management_summary_is_a_pure_computed_read
    """
    fixtures.set_clock(api, CLOCK)
    ctx = fixtures.firm_context(api, **FIRM_KWARGS)
    fixtures.released_engagement(api, ctx, **REVIEW_ENGAGEMENT)
    fixtures.released_engagement(api, ctx, **ERISA_ENGAGEMENT)
    risk = fixtures.new_quality_risk(
        api,
        ctx,
        component="INFORMATION_COMMUNICATION",
        quality_objective_code="IC-01",
        risk_statement=(
            "Firm-wide quality communications may not reach seasonal staff."
        ),
        likelihood=2,
        impact=2,
    )
    response = fixtures.new_risk_response(
        api,
        ctx,
        risk["id"],
        response_type="PREVENTIVE",
        description=(
            "Quarterly quality bulletin acknowledged by every engagement team member."
        ),
    )
    fixtures.record_effectiveness_test(
        api,
        ctx,
        response["id"],
        design_effectiveness="EFFECTIVE",
        operating_effectiveness="EFFECTIVE",
    )
    assertions.read_entity(
        api.create_risk_evaluation(
            risk["id"],
            f.risk_evaluation_payload("DESIGN_BASIS"),
            headers=ctx["qc_headers"],
        ),
        200,
    )
    inspection = fixtures.new_inspection(
        api, ctx, inspection_year=2026, target_engagement_count=1
    )
    selector_response = api.run_inspection_selector(
        inspection["id"], headers=ctx["qc_headers"]
    )
    assert selector_response.status_code in (200, 201), (
        f"selector run failed: {selector_response.status_code}"
    )

    summary = assertions.read_entity(
        api.get_quality_management_summary(ctx["firm_id"], headers=ctx["qc_headers"]),
        200,
    )

    assertions.assert_fields(
        summary,
        risk_posture="STABLE",
        critical_risk_count=0,
        open_deficiency_count=0,
        open_material_failure_count=0,
        last_peer_review_rating="NONE",
        unassigned_review_flag=False,
        must_select_categories=["ERISA_AUDIT"],
    )
    stored_risk = assertions.read_entity(
        api.get_quality_risk(risk["id"], headers=ctx["qc_headers"]), 200
    )
    assertions.assert_decimal_equals(stored_risk["residual_risk_score"], 2.60)
    assertions.assert_fields(stored_risk, severity_band="LOW")
    firm = assertions.read_entity(
        api.get_firm(ctx["firm_id"], headers=ctx["mp_headers"]), 200
    )
    assertions.assert_fields(firm, version=1)


def test_selection_delete_restores_hours_on_both_sides(api):
    """Withdrawing a committed selection returns both conserved hour balances exactly.

    "the review's `unallocated_hours` is credited back by that selection's
    `hours_committed` and the reviewer's `committed_hours_balance` debited by the same
    amount, restoring both to the values they held before the selection existed".

    Design: Corner/endpoints/selection_delete_restores_hours_on_both_sides
    """
    fixtures.set_clock(api, CLOCK)
    committee = make_committee_headers()
    ctx = fixtures.firm_context(api, **FIRM_KWARGS)
    engagement = fixtures.released_engagement(api, ctx, **REVIEW_ENGAGEMENT)
    reviewer = fixtures.new_peer_reviewer(api, **ROSTER_REVIEWER)
    review = fixtures.new_peer_review(api, ctx["firm_id"], **SYSTEM_REVIEW)
    fixtures.assign_reviewer(api, review["id"], reviewer["id"])
    _scope(api, review["id"], reviewer["id"])
    selection = fixtures.select_engagement(
        api,
        review["id"],
        reviewer["id"],
        engagement["id"],
        hours_committed=12,
        is_scope_limitation=True,
    )
    reviewer_headers = make_peer_reviewer_headers(reviewer["id"])

    response = api.delete_peer_review_selection(
        review["id"], selection["id"], headers=reviewer_headers
    )

    assert response.status_code == 204, (
        f"expected HTTP 204, got {response.status_code}: {response.text}"
    )
    if response.content:
        assert response.json().get("data") == {}, (
            f"expected an empty data object, got {response.text}"
        )
    stored_review = assertions.read_entity(
        api.get_peer_review(review["id"], headers=reviewer_headers), 200
    )
    assertions.assert_fields(
        stored_review,
        unallocated_hours=40,
        total_scope_hours=40,
        scope_limitation_count=0,
        state="SCOPE_SET",
    )
    stored_reviewer = assertions.read_entity(
        api.get_peer_reviewer(reviewer["id"], headers=committee), 200
    )
    assertions.assert_fields(stored_reviewer, committed_hours_balance=0)
    stored_selection = assertions.read_entity(
        api.get_peer_review_selection(selection["id"], headers=committee), 200
    )
    assertions.assert_fields(
        stored_selection, status="WITHDRAWN", hours_committed=12
    )


def test_selection_link_derives_the_must_select_category_from_the_engagement(api):
    """The junction row derives must_select_category from the linked engagement's type.

    "its `must_select_category` is derived by the server from the engagement rather
    than supplied by the caller".

    Design: Corner/endpoints/selection_link_derives_the_must_select_category_from_the_engagement
    """
    fixtures.set_clock(api, CLOCK)
    committee = make_committee_headers()
    ctx = fixtures.firm_context(api, **FIRM_KWARGS)
    fixtures.released_engagement(api, ctx, **REVIEW_ENGAGEMENT)
    erisa = fixtures.released_engagement(api, ctx, **ERISA_ENGAGEMENT)
    reviewer = fixtures.new_peer_reviewer(api, **ROSTER_REVIEWER)
    review = fixtures.new_peer_review(api, ctx["firm_id"], **SYSTEM_REVIEW)
    fixtures.assign_reviewer(api, review["id"], reviewer["id"])
    scoped = _scope(api, review["id"], reviewer["id"])
    reviewer_headers = make_peer_reviewer_headers(reviewer["id"])

    selection = assertions.created_entity(
        api.create_peer_review_selection(
            review["id"],
            {
                "engagement_id": erisa["id"],
                "hours_committed": 16,
                "expected_peer_review_version": scoped["version"],
            },
            headers=reviewer_headers,
        )
    )

    assertions.assert_fields(
        selection,
        must_select_category="ERISA_AUDIT",
        is_scope_limitation=False,
        status="COMMITTED",
        disposition="NONE",
        non_conforming=False,
    )
    stored_review = assertions.read_entity(
        api.get_peer_review(review["id"], headers=reviewer_headers), 200
    )
    assertions.assert_fields(stored_review, unallocated_hours=32)
    stored_reviewer = assertions.read_entity(
        api.get_peer_reviewer(reviewer["id"], headers=committee), 200
    )
    assertions.assert_fields(stored_reviewer, committed_hours_balance=16)


def test_partner_patch_recomputes_eqr_eligible_from_cpe_hours(api):
    """A PATCH raising CPE hours to exactly 120 flips eqr_eligible true.

    "`eqr_eligible` is recomputed on every partner write and is true only when all
    three of the following hold: the partner's `status` is `ACTIVE`, their
    `cpe_hours_last_3y` is at least 120, and their `designations` array contains
    `EQ_REVIEWER`."

    Design: Corner/endpoints/partner_patch_recomputes_eqr_eligible_from_cpe_hours
    """
    fixtures.set_clock(api, CLOCK)
    admin = make_system_admin_headers()
    firm = fixtures.new_firm(api, **FIRM_KWARGS)
    partner = fixtures.new_partner(
        api,
        firm["id"],
        full_name="Nadia Kwon",
        cpa_license_state="TX",
        designations=["EQ_REVIEWER"],
        cpe_hours_last_3y=90,
    )
    assertions.assert_fields(partner, eqr_eligible=False)

    patched = assertions.read_entity(
        api.update_partner(partner["id"], {"cpe_hours_last_3y": 120}, headers=admin),
        200,
    )

    assertions.assert_fields(
        patched,
        cpe_hours_last_3y=120,
        eqr_eligible=True,
        designations=["EQ_REVIEWER"],
        status="ACTIVE",
        version=2,
    )
