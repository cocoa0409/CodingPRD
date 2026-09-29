"""Compensating invariants: three conserved quantities taken away and given
back exactly, each with a follow-on operation that only succeeds when the
restoration was exact.

The quantities are a peer review's hours budget (held jointly with the
reviewer's committed balance), the firm's open deficiency counters, and a
partner's held engagement-quality-review capacity.
"""
from prd_bench_local_runner.testing import validate_error

from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.api_errors import ERR_STALE_VERSION
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
    make_managing_partner_headers,
    make_peer_reviewer_headers,
    make_qc_director_headers,
    make_system_admin_headers,
)


def _assert_no_content(response):
    """A withdrawal of a committed peer review selection returns HTTP 204."""
    assert response.status_code == 204, (
        f"Expected 204, got {response.status_code}: {response.text}"
    )
    if response.text and response.text.strip():
        body = response.json()
        assert body.get("data") == {}, f"expected an empty data object: {body}"


# ---------------------------------------------------------------------------
# PeerReview.unallocated_hours / PeerReviewer.committed_hours_balance
# ---------------------------------------------------------------------------
def _review_with_one_committed_scope_limitation(api):
    """A scoped peer review of 16 hours with a single 10-hour scope-limitation
    selection committed against one in-scope engagement."""
    fixtures.set_clock(api, DEFAULT_CLOCK)
    admin = make_system_admin_headers()
    committee = make_committee_headers()
    firm = created_entity(
        api.create_firm(
            f.firm_payload(
                legal_name="Rushmere Vale LLP",
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
                full_name="Ines Vale",
                cpa_license_state="CA",
                designations=["ENGAGEMENT_PARTNER"],
                cpe_hours_last_3y=200,
            ),
            headers=admin,
        )
    )
    engagement = created_entity(
        api.create_engagement(
            f.engagement_payload(
                firm["id"],
                ep["id"],
                client_name="Tarn Logistics",
                engagement_type="AUDIT",
                period_end="2026-06-30",
                is_public_interest=False,
            ),
            headers=make_engagement_partner_headers(ep["id"]),
        )
    )
    reviewer = created_entity(
        api.create_peer_reviewer(
            f.peer_reviewer_payload(
                reviewer_firm_name="Vessel Peer Review PC",
                license_state="CA",
                qualified_categories=[],
                max_concurrent_reviews=2,
                experience_hours=4000,
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
    assert_fields(scoped, total_scope_hours=16, unallocated_hours=16)

    selection = created_entity(
        api.create_peer_review_selection(
            review["id"],
            f.peer_review_selection_payload(
                engagement["id"], scoped["version"], 10, is_scope_limitation=True
            ),
            headers=reviewer_headers,
        )
    )
    return {
        "committee": committee,
        "firm": firm,
        "engagement": engagement,
        "reviewer": reviewer,
        "reviewer_headers": reviewer_headers,
        "review": scoped,
        "selection": selection,
    }


def test_withdrawing_a_selection_restores_the_hours_exactly(api):
    """Withdrawing a committed selection credits the review's hours back and
    debits the reviewer's balance by the same amount.

    "the review's `unallocated_hours` is credited back by that selection's
    `hours_committed` and the reviewer's `committed_hours_balance` debited by
    the same amount, restoring both to the values they held before the
    selection existed"

    Design: Difficulty/compensating_invariant/peer_review_hours_conservation_survives_a_selection_withdrawal
    """
    ctx = _review_with_one_committed_scope_limitation(api)

    committed_review = read_entity(
        api.get_peer_review(ctx["review"]["id"], headers=ctx["reviewer_headers"])
    )
    assert_fields(
        committed_review,
        total_scope_hours=16,
        unallocated_hours=6,
        scope_limitation_count=1,
    )
    committed_reviewer = read_entity(
        api.get_peer_reviewer(ctx["reviewer"]["id"], headers=ctx["committee"])
    )
    assert_fields(committed_reviewer, committed_hours_balance=10)

    _assert_no_content(
        api.delete_peer_review_selection(
            ctx["review"]["id"], ctx["selection"]["id"],
            headers=ctx["reviewer_headers"],
        )
    )

    selection = read_entity(
        api.get_peer_review_selection(
            ctx["selection"]["id"], headers=ctx["reviewer_headers"]
        )
    )
    assert_fields(selection, status="WITHDRAWN", hours_committed=10)

    review = read_entity(
        api.get_peer_review(ctx["review"]["id"], headers=ctx["reviewer_headers"])
    )
    assert_fields(
        review,
        total_scope_hours=16,
        unallocated_hours=16,
        scope_limitation_count=0,
    )
    reviewer = read_entity(
        api.get_peer_reviewer(ctx["reviewer"]["id"], headers=ctx["committee"])
    )
    assert_fields(reviewer, committed_hours_balance=0)


def test_withdrawn_hours_can_be_recommitted_in_full(api):
    """The restored budget is genuinely spendable: the same engagement may be
    re-selected for the review's whole scope.

    "at every instant the review's `total_scope_hours` equals its
    `unallocated_hours` plus the sum of `hours_committed` across its committed
    selections"

    Design: Difficulty/compensating_invariant/peer_review_hours_conservation_survives_a_selection_withdrawal
    """
    ctx = _review_with_one_committed_scope_limitation(api)

    _assert_no_content(
        api.delete_peer_review_selection(
            ctx["review"]["id"], ctx["selection"]["id"],
            headers=ctx["reviewer_headers"],
        )
    )

    refreshed = read_entity(
        api.get_peer_review(ctx["review"]["id"], headers=ctx["reviewer_headers"])
    )
    second = created_entity(
        api.create_peer_review_selection(
            ctx["review"]["id"],
            f.peer_review_selection_payload(
                ctx["engagement"]["id"], refreshed["version"], 16
            ),
            headers=ctx["reviewer_headers"],
        )
    )
    assert_fields(second, status="COMMITTED", hours_committed=16)

    review = read_entity(
        api.get_peer_review(ctx["review"]["id"], headers=ctx["reviewer_headers"])
    )
    assert_fields(
        review,
        total_scope_hours=16,
        unallocated_hours=0,
        scope_limitation_count=0,
    )
    reviewer = read_entity(
        api.get_peer_reviewer(ctx["reviewer"]["id"], headers=ctx["committee"])
    )
    assert_fields(reviewer, committed_hours_balance=16)

    withdrawn = read_entity(
        api.get_peer_review_selection(
            ctx["selection"]["id"], headers=ctx["reviewer_headers"]
        )
    )
    assert_fields(withdrawn, status="WITHDRAWN", hours_committed=10)


# ---------------------------------------------------------------------------
# Firm.open_deficiency_count / Firm.open_material_failure_count
# ---------------------------------------------------------------------------
def _assert_same_instant(actual, expected):
    """Compare two ISO-8601 UTC instants regardless of fractional-digit form."""
    from datetime import datetime

    def parse(value):
        assert value is not None, f"expected instant {expected}, got None"
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    assert parse(actual) == parse(expected), (
        f"expected instant {expected}, got {actual}"
    )


def _run_selector(api, inspection_id, headers):
    response = api.run_inspection_selector(inspection_id, headers=headers)
    assert response.status_code in (200, 201), (
        f"selector run failed: {response.status_code} {response.text}"
    )
    return response.json()["data"]


def _remediated_finding_with_completed_plan(api):
    """One DEFICIENCY finding in REMEDIATED whose remediation plan has reached
    COMPLETED, so the firm carries exactly one open deficiency."""
    fixtures.set_clock(api, DEFAULT_CLOCK)
    admin = make_system_admin_headers()
    firm = created_entity(
        api.create_firm(
            f.firm_payload(
                legal_name="Weald Chandler LLP",
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
                full_name="Ines Vale",
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
    owner = created_entity(
        api.create_partner(
            firm["id"],
            f.partner_payload(
                full_name="Marek Doyle",
                cpa_license_state="CA",
                designations=["MANAGING_PARTNER"],
                cpe_hours_last_3y=200,
            ),
            headers=admin,
        )
    )
    ep_headers = make_engagement_partner_headers(ep["id"])
    qc_headers = make_qc_director_headers(qc["id"])
    owner_headers = make_managing_partner_headers(owner["id"])

    engagement = created_entity(
        api.create_engagement(
            f.engagement_payload(
                firm["id"],
                ep["id"],
                client_name="Harrow Textiles",
                engagement_type="AUDIT",
                period_end="2026-06-30",
                is_public_interest=False,
            ),
            headers=ep_headers,
        )
    )
    for to_state in ("FIELDWORK", "EQR_PENDING", "EQR_CLEARED", "REPORT_RELEASED"):
        read_entity(
            api.create_workflow_transition(
                engagement["id"], f.workflow_transition_payload(to_state),
                headers=ep_headers,
            )
        )

    inspection = created_entity(
        api.create_internal_inspection(
            firm["id"],
            f.internal_inspection_payload(
                inspection_year=2026, target_engagement_count=1
            ),
            headers=qc_headers,
        )
    )
    _run_selector(api, inspection["id"], qc_headers)
    listed = api.list_inspection_selections(
        headers=qc_headers, params={"inspection_id": inspection["id"]}
    )
    selections = read_entity(listed)
    assert len(selections) == 1, f"expected one selection, got {selections}"
    selection = selections[0]

    read_entity(
        api.create_inspection_transition(
            inspection["id"], f.inspection_transition_payload("IN_PROGRESS"),
            headers=qc_headers,
        )
    )
    finding = created_entity(
        api.create_inspection_finding(
            selection["id"],
            f.inspection_finding_payload(
                title="Inadequate review of revenue cut-off testing",
                sqm_component="ENGAGEMENT_PERFORMANCE",
            ),
            headers=qc_headers,
        )
    )
    read_entity(
        api.classify_finding(
            finding["id"],
            f.classification_payload(
                "DEFICIENCY", pervasiveness="ISOLATED",
                affects_report_conclusion=False,
            ),
            headers=qc_headers,
        )
    )
    rca = created_entity(
        api.create_root_cause_analysis(
            finding["id"],
            f.rca_payload(
                method="FISHBONE",
                root_cause_category="SUPERVISION_REVIEW",
                contributing_factor_count=3,
                narrative=(
                    "Manager review of cut-off testing was not evidenced; workload "
                    "peaked in the same week."
                ),
            ),
            headers=qc_headers,
        )
    )
    validated = read_entity(
        api.create_rca_validation(
            rca["id"], f.rca_validation_payload("VALIDATED"), headers=qc_headers
        )
    )
    assert_decimal_equals(validated["depth_score"], 9.00)

    current = read_entity(api.get_inspection_finding(finding["id"], headers=qc_headers))
    plan = created_entity(
        api.create_remediation_plan(
            finding["id"],
            f.remediation_plan_payload(
                rca["id"],
                owner["id"],
                current["version"],
                target_completion_date="2026-12-31",
                action_count=2,
                action_specificity_score=10.00,
            ),
            headers=owner_headers,
        )
    )
    submitted = read_entity(
        api.create_remediation_plan_transition(
            plan["id"],
            f.remediation_transition_payload("SUBMITTED", completed_action_count=0),
            headers=owner_headers,
        )
    )
    assert_decimal_equals(submitted["raw_completeness"], 7.10)
    assert_fields(submitted, completeness_tier="STANDARD")
    assert_decimal_equals(submitted["acceptance_score"], 7.10)

    read_entity(
        api.create_remediation_plan_transition(
            plan["id"], f.remediation_transition_payload("ACCEPTED"),
            headers=qc_headers,
        )
    )
    read_entity(
        api.create_remediation_plan_transition(
            plan["id"],
            f.remediation_transition_payload("COMPLETED", completed_action_count=2),
            headers=owner_headers,
        )
    )
    firm_now = read_entity(api.get_firm(firm["id"], headers=qc_headers))
    assert_fields(firm_now, open_deficiency_count=1, open_material_failure_count=0)
    return {
        "firm": firm,
        "owner": owner,
        "owner_headers": owner_headers,
        "qc_headers": qc_headers,
        "finding": finding,
        "rca": rca,
        "plan": plan,
    }


def test_reopening_a_verified_finding_restores_the_firm_counters_exactly(api):
    """Verification consumes the firm's single open deficiency and reopening
    restores it to exactly one.

    "`VERIFIED -> REOPENED` clears `verified_at` back to null, increments the
    finding's `reopen_count` by 1, and **compensates the firm's counters
    exactly**"

    Design: Difficulty/compensating_invariant/firm_open_deficiency_count_is_restored_exactly_by_a_reopen
    """
    ctx = _remediated_finding_with_completed_plan(api)

    verified = read_entity(
        api.create_finding_transition(
            ctx["finding"]["id"], f.finding_transition_payload("VERIFIED"),
            headers=ctx["qc_headers"],
        )
    )
    assert_fields(verified, state="VERIFIED")
    _assert_same_instant(verified["verified_at"], DEFAULT_CLOCK)

    firm_after_verify = read_entity(
        api.get_firm(ctx["firm"]["id"], headers=ctx["qc_headers"])
    )
    assert_fields(
        firm_after_verify, open_deficiency_count=0, open_material_failure_count=0
    )

    reopened = read_entity(
        api.create_finding_transition(
            ctx["finding"]["id"], f.finding_transition_payload("REOPENED"),
            headers=ctx["qc_headers"],
        )
    )
    assert_fields(reopened, state="REOPENED", verified_at=None, reopen_count=1)

    firm_after_reopen = read_entity(
        api.get_firm(ctx["firm"]["id"], headers=ctx["qc_headers"])
    )
    assert_fields(
        firm_after_reopen,
        open_deficiency_count=1,
        open_material_failure_count=0,
        risk_posture="STABLE",
    )


def test_a_reopened_finding_accepts_a_superseding_remediation_plan(api):
    """The restored deficiency is a genuinely open one: a second remediation
    plan may be raised against it, closing the completed plan.

    "the earlier plan is moved to `CLOSED` and the new plan becomes the
    finding's active plan"

    Design: Difficulty/compensating_invariant/firm_open_deficiency_count_is_restored_exactly_by_a_reopen
    """
    ctx = _remediated_finding_with_completed_plan(api)

    read_entity(
        api.create_finding_transition(
            ctx["finding"]["id"], f.finding_transition_payload("VERIFIED"),
            headers=ctx["qc_headers"],
        )
    )
    read_entity(
        api.create_finding_transition(
            ctx["finding"]["id"], f.finding_transition_payload("REOPENED"),
            headers=ctx["qc_headers"],
        )
    )

    reopened = read_entity(
        api.get_inspection_finding(ctx["finding"]["id"], headers=ctx["qc_headers"])
    )
    second = created_entity(
        api.create_remediation_plan(
            ctx["finding"]["id"],
            f.remediation_plan_payload(
                ctx["rca"]["id"],
                ctx["owner"]["id"],
                reopened["version"],
                target_completion_date="2027-03-31",
                action_count=3,
                action_specificity_score=9.00,
            ),
            headers=ctx["owner_headers"],
        )
    )
    assert_fields(second, state="DRAFTED")

    first = read_entity(
        api.get_remediation_plan(ctx["plan"]["id"], headers=ctx["qc_headers"])
    )
    assert_fields(first, state="CLOSED")

    finding = read_entity(
        api.get_inspection_finding(ctx["finding"]["id"], headers=ctx["qc_headers"])
    )
    assert_fields(finding, state="REMEDIATION_ASSIGNED", reopen_count=1)

    firm = read_entity(api.get_firm(ctx["firm"]["id"], headers=ctx["qc_headers"]))
    assert_fields(
        firm, open_deficiency_count=1, open_material_failure_count=0
    )


# ---------------------------------------------------------------------------
# Partner.open_eqr_count released by a withdrawal
# ---------------------------------------------------------------------------
def _engagement_with_one_assigned_quality_review(api):
    """An engagement in FIELDWORK holding one ASSIGNED quality review, plus the
    engagement version the caller observed after that assignment."""
    fixtures.set_clock(api, DEFAULT_CLOCK)
    admin = make_system_admin_headers()
    firm = created_entity(
        api.create_firm(
            f.firm_payload(
                legal_name="Yarrow Deane LLP",
                state_code="CA",
                aa_hours_last_year=400,
                peer_review_year_end="2026-12-31",
            ),
            headers=admin,
        )
    )

    def partner(full_name, designation, cpe=200):
        return created_entity(
            api.create_partner(
                firm["id"],
                f.partner_payload(
                    full_name=full_name,
                    cpa_license_state="CA",
                    designations=[designation],
                    cpe_hours_last_3y=cpe,
                ),
                headers=admin,
            )
        )

    ep = partner("Ines Vale", "ENGAGEMENT_PARTNER")
    qc = partner("Quinn Cade", "QC_DIRECTOR")
    managing = partner("Marek Doyle", "MANAGING_PARTNER")
    reviewer = partner("Odile Frey", "EQ_REVIEWER", cpe=240)

    ep_headers = make_engagement_partner_headers(ep["id"])
    qc_headers = make_qc_director_headers(qc["id"])
    managing_headers = make_managing_partner_headers(managing["id"])

    engagement = created_entity(
        api.create_engagement(
            f.engagement_payload(
                firm["id"],
                ep["id"],
                client_name="Cinder Utilities",
                engagement_type="AUDIT",
                period_end="2026-06-30",
                is_public_interest=False,
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
    assert_fields(eqr, state="ASSIGNED", reviewer_partner_id=reviewer["id"])
    observed = read_entity(api.get_engagement(engagement["id"], headers=ep_headers))
    held = read_entity(api.get_partner(reviewer["id"], headers=qc_headers))
    assert_fields(held, open_eqr_count=1)
    return {
        "firm": firm,
        "reviewer": reviewer,
        "ep_headers": ep_headers,
        "qc_headers": qc_headers,
        "managing_headers": managing_headers,
        "engagement": engagement,
        "observed_version": observed["version"],
        "eqr": eqr,
    }


def test_withdrawal_releases_the_capacity_but_invalidates_the_stale_version(api):
    """A withdrawal returns the reviewer's held capacity and advances the
    engagement's version, so the pre-withdrawal version is refused.

    "the reviewer's `open_eqr_count` is recomputed downward by one, and - this
    is the part callers most often miss - the linked engagement's `version` is
    incremented by 1"

    Design: Difficulty/compensating_invariant/partner_open_eqr_count_is_returned_by_a_withdrawal_and_re_consumed
    """
    ctx = _engagement_with_one_assigned_quality_review(api)

    withdrawn = read_entity(
        api.create_quality_review_transition(
            ctx["eqr"]["id"], f.quality_review_transition_payload("WITHDRAWN"),
            headers=ctx["managing_headers"],
        )
    )
    assert_fields(withdrawn, state="WITHDRAWN")
    assert withdrawn["concluded_at"] is not None, (
        "withdrawal must stamp concluded_at from the logical clock"
    )

    released = read_entity(
        api.get_partner(ctx["reviewer"]["id"], headers=ctx["qc_headers"])
    )
    assert_fields(released, open_eqr_count=0)

    response = api.assign_quality_review(
        ctx["engagement"]["id"],
        f.quality_review_assignment_payload(
            ctx["reviewer"]["id"], ctx["observed_version"]
        ),
        headers=ctx["qc_headers"],
    )
    validate_error(response, ERR_STALE_VERSION, expected_status=412)

    reviewer = read_entity(
        api.get_partner(ctx["reviewer"]["id"], headers=ctx["qc_headers"])
    )
    assert_fields(reviewer, open_eqr_count=0)


def test_released_capacity_is_re_consumed_by_a_fresh_assignment(api):
    """With the engagement re-read, the freed capacity is spendable again on the
    very same reviewer.

    "Withdrawal exists to free the engagement for a fresh reviewer"

    Design: Difficulty/compensating_invariant/partner_open_eqr_count_is_returned_by_a_withdrawal_and_re_consumed
    """
    ctx = _engagement_with_one_assigned_quality_review(api)

    read_entity(
        api.create_quality_review_transition(
            ctx["eqr"]["id"], f.quality_review_transition_payload("WITHDRAWN"),
            headers=ctx["managing_headers"],
        )
    )

    refreshed = read_entity(
        api.get_engagement(ctx["engagement"]["id"], headers=ctx["ep_headers"])
    )
    assert refreshed["version"] != ctx["observed_version"], (
        "the withdrawal must have advanced the engagement version"
    )

    replacement = created_entity(
        api.assign_quality_review(
            ctx["engagement"]["id"],
            f.quality_review_assignment_payload(
                ctx["reviewer"]["id"], refreshed["version"]
            ),
            headers=ctx["qc_headers"],
        )
    )
    assert_fields(
        replacement, state="ASSIGNED", reviewer_partner_id=ctx["reviewer"]["id"]
    )
    assert replacement["concluded_at"] is None, (
        "a freshly assigned review has an open interval"
    )

    reviewer = read_entity(
        api.get_partner(ctx["reviewer"]["id"], headers=ctx["qc_headers"])
    )
    assert_fields(reviewer, open_eqr_count=1)

    engagement = read_entity(
        api.get_engagement(ctx["engagement"]["id"], headers=ctx["ep_headers"])
    )
    assert_fields(engagement, workflow_state="FIELDWORK")
