"""Error catalogue: every declared error id is reachable and distinguishable.

The probes here drive each family of the catalogue in §5 through the endpoints
that own it, so that no collection reuses a neighbour's id and no guard is
collapsed into a sibling guard.
"""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, factories as f, fixtures
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_fields,
    created_entity,
    read_entity,
)
from test_helpers.constants import DEFAULT_CLOCK
from test_helpers.test_users import (
    NO_AUTH_HEADERS,
    UNKNOWN_PARTNER_ID,
    make_committee_headers,
    make_engagement_partner_headers,
    make_eq_reviewer_headers,
    make_managing_partner_headers,
    make_peer_reviewer_headers,
    make_qc_director_headers,
    make_system_admin_headers,
)

UNKNOWN_ID = "11111111-1111-4111-8111-111111111111"

FIRM_A = dict(
    legal_name="Harbor & Vance LLP",
    state_code="TX",
    aa_hours_last_year=9000,
    enrolled_program="AICPA_PRC",
    peer_review_year_end="2026-06-30",
)
FIRM_B = dict(
    legal_name="Northgate Audit Group",
    state_code="NV",
    aa_hours_last_year=400,
    peer_review_year_end="2026-06-30",
)
ENG_A = dict(
    client_name="Aurora Metals Inc", engagement_type="REVIEW", period_end="2026-03-31"
)
ENG_ERISA = dict(
    client_name="Borealis Pension Trust",
    engagement_type="ERISA_AUDIT",
    period_end="2026-04-30",
)
ALL_CATEGORIES = [
    "ERISA_AUDIT",
    "SINGLE_AUDIT",
    "BROKER_DEALER",
    "GOVERNMENTAL",
    "PUBLIC_INTEREST",
]
PEER_REVIEWER_A = dict(
    reviewer_firm_name="Calder & Boone PC",
    license_state="TX",
    qualified_categories=ALL_CATEGORIES,
    max_concurrent_reviews=2,
    experience_hours=4000,
)
PEER_REVIEW_A = dict(
    review_type="SYSTEM_REVIEW",
    year_end="2026-06-30",
    scheduled_window_start="2026-10-01",
    scheduled_window_end="2026-10-15",
)


def _staff(api, firm: Dict[str, Any], state: str, names) -> Dict[str, Any]:
    """Add a managing partner, an engagement partner and a QC director."""
    firm_id = firm["id"]
    mp_name, ep_name, qc_name = names
    mp = fixtures.new_partner(
        api, firm_id, full_name=mp_name, cpa_license_state=state,
        designations=["MANAGING_PARTNER"], cpe_hours_last_3y=40,
    )
    ep = fixtures.new_partner(
        api, firm_id, full_name=ep_name, cpa_license_state=state,
        designations=["ENGAGEMENT_PARTNER"], cpe_hours_last_3y=60,
    )
    qc = fixtures.new_partner(
        api, firm_id, full_name=qc_name, cpa_license_state=state,
        designations=["QC_DIRECTOR"], cpe_hours_last_3y=80,
    )
    return {
        "firm": firm,
        "firm_id": firm_id,
        "mp": mp,
        "mp_headers": make_managing_partner_headers(mp["id"]),
        "ep": ep,
        "ep_headers": make_engagement_partner_headers(ep["id"]),
        "qc": qc,
        "qc_headers": make_qc_director_headers(qc["id"]),
    }


def _firm_a(api) -> Dict[str, Any]:
    fixtures.set_clock(api, DEFAULT_CLOCK)
    firm = fixtures.new_firm(api, **FIRM_A)
    return _staff(api, firm, "TX", ("Dana Vance", "Ravi Shah", "Marcus Bell"))


def _firm_b(api) -> Dict[str, Any]:
    firm = fixtures.new_firm(api, **FIRM_B)
    return _staff(
        api, firm, "NV", ("Greta Lindqvist", "Owen Fairchild", "Tilda Brooks")
    )


def _new_engagement(api, ctx, headers: Optional[Dict] = None, **overrides):
    payload = f.engagement_payload(ctx["firm_id"], ctx["ep"]["id"], **overrides)
    return created_entity(
        api.create_engagement(payload, headers=headers or ctx["mp_headers"])
    )


def _release_simple(api, ctx, engagement):
    """Drive an engagement whose ``eqr_required`` is false to REPORT_RELEASED."""
    latest = engagement
    for state in ("FIELDWORK", "EQR_PENDING", "EQR_CLEARED", "REPORT_RELEASED"):
        latest = fixtures.workflow_step(api, engagement, state, ctx["ep_headers"])
    return latest


def _eq_reviewer(api, ctx, full_name="Lena Ortiz", **overrides):
    payload = dict(
        cpa_license_state="TX", designations=["EQ_REVIEWER"], cpe_hours_last_3y=150
    )
    payload.update(overrides)
    return fixtures.new_partner(api, ctx["firm_id"], full_name=full_name, **payload)


def _assign_eqr(api, ctx, engagement_id: str, reviewer_id: str, **overrides):
    current = read_entity(
        api.get_engagement(engagement_id, headers=ctx["mp_headers"])
    )
    return api.assign_quality_review(
        engagement_id,
        f.quality_review_assignment_payload(
            reviewer_id, current["version"], **overrides
        ),
        headers=ctx["mp_headers"],
    )


def _release_with_eqr(api, ctx, engagement, reviewer):
    """Drive an engagement whose ``eqr_required`` is true to REPORT_RELEASED."""
    ep_headers = ctx["ep_headers"]
    fixtures.workflow_step(api, engagement, "FIELDWORK", ep_headers)
    eqr = created_entity(_assign_eqr(api, ctx, engagement["id"], reviewer["id"]))
    reviewer_headers = make_eq_reviewer_headers(reviewer["id"])
    read_entity(
        api.create_quality_review_transition(
            eqr["id"], f.quality_review_transition_payload("IN_PROGRESS"),
            headers=reviewer_headers,
        )
    )
    fixtures.workflow_step(api, engagement, "EQR_PENDING", ep_headers)
    read_entity(
        api.create_quality_review_transition(
            eqr["id"], f.quality_review_transition_payload("CONCURRED"),
            headers=reviewer_headers,
        )
    )
    fixtures.workflow_step(api, engagement, "EQR_CLEARED", ep_headers)
    return fixtures.workflow_step(api, engagement, "REPORT_RELEASED", ep_headers)


def _concluded_inspection(api, ctx):
    """Run a 2026 cycle with no findings all the way to CONCLUDED."""
    inspection = fixtures.new_inspection(api, ctx)
    fixtures.run_selector(api, ctx, inspection["id"])
    fixtures.inspection_step(api, ctx, inspection["id"], "IN_PROGRESS")
    fixtures.inspection_step(
        api, ctx, inspection["id"], "FINDINGS_CLASSIFIED",
        severity_index_basis="ENGAGEMENT_WEIGHTED",
    )
    return fixtures.inspection_step(api, ctx, inspection["id"], "CONCLUDED")


def _total_count(response) -> int:
    validate_success(response)
    return response.json()["meta"]["total_count"]


def _set_clock(api, instant: str) -> None:
    validate_success(
        api.set_clock(instant, headers=make_system_admin_headers()), expected_status=200
    )


def test_missing_x_user_headers_returns_unauthenticated(api):
    """A request with no identity headers is unauthenticated, a permitted-but-wrong role is forbidden, and an unresolvable actor id is a third distinct failure.

    "Authentication ... then role authorization ... then actor identity
    resolution for entity-backed roles".

    Design: Corner/errors/missing_x_user_headers_returns_unauthenticated
    """
    ctx = _firm_a(api)
    engagement = _new_engagement(api, ctx, **ENG_A)

    payload = f.workflow_transition_payload("FIELDWORK")
    validate_error(
        api.create_workflow_transition(
            engagement["id"], payload, headers=NO_AUTH_HEADERS
        ),
        api_errors.ERR_UNAUTHENTICATED,
    )
    validate_error(
        api.create_workflow_transition(
            engagement["id"], payload, headers=make_committee_headers()
        ),
        api_errors.ERR_ROLE_NOT_PERMITTED,
    )
    validate_error(
        api.create_workflow_transition(
            engagement["id"], payload,
            headers=make_engagement_partner_headers(UNKNOWN_PARTNER_ID),
        ),
        api_errors.ERR_ROLE_IDENTITY_UNKNOWN,
    )

    after = read_entity(
        api.get_engagement(engagement["id"], headers=ctx["mp_headers"])
    )
    assert_fields(after, workflow_state="PLANNING", version=1)


def test_unknown_ids_return_the_per_collection_not_found_error(api):
    """Every collection owns its own not-found error id, and an unknown parent in the path is resolved before the request body.

    "Path parameter resolution — the per-collection not-found errors".

    Design: Corner/errors/unknown_ids_return_the_per_collection_not_found_error
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    firm = fixtures.new_firm(api, **FIRM_A)
    admin = fixtures.ADMIN

    validate_error(
        api.get_firm(UNKNOWN_ID, headers=admin), api_errors.ERR_FIRM_NOT_FOUND
    )
    validate_error(
        api.get_partner(UNKNOWN_ID, headers=admin), api_errors.ERR_PARTNER_NOT_FOUND
    )
    validate_error(
        api.get_engagement(UNKNOWN_ID, headers=admin),
        api_errors.ERR_ENGAGEMENT_NOT_FOUND,
    )
    validate_error(
        api.get_quality_review(UNKNOWN_ID, headers=admin),
        api_errors.ERR_QUALITY_REVIEW_NOT_FOUND,
    )
    validate_error(
        api.get_quality_risk(UNKNOWN_ID, headers=admin),
        api_errors.ERR_QUALITY_RISK_NOT_FOUND,
    )
    validate_error(
        api.get_risk_response(UNKNOWN_ID, headers=admin),
        api_errors.ERR_RISK_RESPONSE_NOT_FOUND,
    )
    validate_error(
        api.get_internal_inspection(UNKNOWN_ID, headers=admin),
        api_errors.ERR_INSPECTION_NOT_FOUND,
    )
    validate_error(
        api.get_inspection_selection(UNKNOWN_ID, headers=admin),
        api_errors.ERR_INSPECTION_SELECTION_NOT_FOUND,
    )
    validate_error(
        api.get_inspection_finding(UNKNOWN_ID, headers=admin),
        api_errors.ERR_FINDING_NOT_FOUND,
    )
    validate_error(
        api.get_root_cause_analysis(UNKNOWN_ID, headers=admin),
        api_errors.ERR_RCA_NOT_FOUND,
    )
    validate_error(
        api.get_remediation_plan(UNKNOWN_ID, headers=admin),
        api_errors.ERR_REMEDIATION_PLAN_NOT_FOUND,
    )
    validate_error(
        api.get_peer_reviewer(UNKNOWN_ID, headers=admin),
        api_errors.ERR_PEER_REVIEWER_NOT_FOUND,
    )
    validate_error(
        api.get_peer_review_selection(UNKNOWN_ID, headers=admin),
        api_errors.ERR_PEER_REVIEW_SELECTION_NOT_FOUND,
    )
    validate_error(
        api.get_corrective_action_plan(UNKNOWN_ID, headers=admin),
        api_errors.ERR_CORRECTIVE_ACTION_PLAN_NOT_FOUND,
    )
    validate_error(
        api.create_partner(UNKNOWN_ID, f.partner_payload(), headers=admin),
        api_errors.ERR_FIRM_NOT_FOUND,
    )
    read_entity(api.get_firm(firm["id"], headers=admin))


def test_duplicate_unique_keys_return_their_own_error_ids(api):
    """The three composite unique keys of the domain each report their own duplicate error and leave the first row untouched.

    A firm "may hold only one cycle per year", "may not hold two risks sharing
    the same `component` and `quality_objective_code`" and "may not hold two
    engagements sharing the same `client_name` and `period_end`".

    Design: Corner/errors/duplicate_unique_keys_return_their_own_error_ids
    """
    ctx = _firm_a(api)
    _new_engagement(api, ctx, **ENG_A)
    fixtures.new_quality_risk(
        api, ctx,
        component="ENGAGEMENT_PERFORMANCE",
        quality_objective_code="EP-01",
        risk_statement=(
            "Engagement teams may not obtain sufficient appropriate evidence over "
            "significant estimates."
        ),
        likelihood=5,
        impact=5,
    )
    inspection = fixtures.new_inspection(api, ctx)

    validate_error(
        api.create_internal_inspection(
            ctx["firm_id"],
            f.internal_inspection_payload(
                inspection_year=2026, target_engagement_count=3
            ),
            headers=ctx["qc_headers"],
        ),
        api_errors.ERR_DUPLICATE_INSPECTION_YEAR,
    )
    validate_error(
        api.create_quality_risk(
            ctx["firm_id"],
            f.quality_risk_payload(
                component="ENGAGEMENT_PERFORMANCE", quality_objective_code="EP-01"
            ),
            headers=ctx["qc_headers"],
        ),
        api_errors.ERR_DUPLICATE_QUALITY_OBJECTIVE,
    )
    validate_error(
        api.create_engagement(
            f.engagement_payload(ctx["firm_id"], ctx["ep"]["id"], **ENG_A),
            headers=ctx["mp_headers"],
        ),
        api_errors.ERR_DUPLICATE_ENGAGEMENT,
    )

    assert_fields(
        read_entity(
            api.get_internal_inspection(inspection["id"], headers=ctx["qc_headers"])
        ),
        target_engagement_count=1,
    )
    assert _total_count(
        api.list_engagements(
            headers=ctx["mp_headers"], params={"firm_id": ctx["firm_id"]}
        )
    ) == 1


def test_eqr_eligibility_clauses_surface_the_first_failing_error(api):
    """The reviewer eligibility clauses are ordered, so each candidate reports the first clause it fails and never a later one.

    "The clauses are evaluated in this order and the first failure decides the
    error".

    Design: Corner/errors/eqr_eligibility_clauses_surface_the_first_failing_error
    """
    ctx = _firm_a(api)
    eqrp = _eq_reviewer(api, ctx)
    engagement = _new_engagement(api, ctx, **ENG_A)
    fielded = fixtures.workflow_step(api, engagement, "FIELDWORK", ctx["ep_headers"])
    version = fielded["version"]

    # Clause 3: the engagement partner may not review his own engagement, even
    # though he also lacks the EQ_REVIEWER designation and the CPE hours.
    validate_error(
        _assign_eqr(api, ctx, engagement["id"], ctx["ep"]["id"]),
        api_errors.ERR_EQR_SELF_REVIEW,
    )

    # Clause 4: designated reviewer, but only 90 CPE hours.
    thin_cpe = _eq_reviewer(api, ctx, full_name="Nadia Solberg", cpe_hours_last_3y=90)
    validate_error(
        _assign_eqr(api, ctx, engagement["id"], thin_cpe["id"]),
        api_errors.ERR_CPE_REQUIREMENT_NOT_MET,
    )

    # Clause 5: a declared conflict against this engagement's client.
    read_entity(
        api.update_partner(
            eqrp["id"],
            {"independence_conflict_client_names": ["Aurora Metals Inc"]},
            headers=fixtures.ADMIN,
        )
    )
    validate_error(
        _assign_eqr(api, ctx, engagement["id"], eqrp["id"]),
        api_errors.ERR_REVIEWER_INDEPENDENCE_CONFLICT,
    )

    # Clause 6: objectivity must be attested on the request itself.
    read_entity(
        api.update_partner(
            eqrp["id"],
            {"independence_conflict_client_names": []},
            headers=fixtures.ADMIN,
        )
    )
    validate_error(
        _assign_eqr(
            api, ctx, engagement["id"], eqrp["id"], objectivity_attested=False
        ),
        api_errors.ERR_OBJECTIVITY_NOT_ATTESTED,
    )

    # Clause 1 precedes clause 3: an inactive partner named as his own reviewer
    # reports the inactivity, not the self-review.
    read_entity(
        api.update_partner(
            ctx["ep"]["id"], {"status": "INACTIVE"}, headers=fixtures.ADMIN
        )
    )
    validate_error(
        _assign_eqr(api, ctx, engagement["id"], ctx["ep"]["id"]),
        api_errors.ERR_PARTNER_INACTIVE,
    )

    assert _total_count(
        api.list_quality_reviews(
            headers=ctx["mp_headers"], params={"engagement_id": engagement["id"]}
        )
    ) == 0
    assert_fields(
        read_entity(api.get_engagement(engagement["id"], headers=ctx["mp_headers"])),
        version=version,
    )


def test_fourth_open_quality_review_exceeds_the_eqr_capacity(api):
    """A reviewer already holding three open reviews is refused a fourth on capacity, while a second review on an already-covered engagement is a different error.

    "a partner may hold at most three concurrent open engagement quality
    reviews".

    Design: Corner/errors/fourth_open_quality_review_exceeds_the_eqr_capacity
    """
    ctx = _firm_a(api)
    eqrp = _eq_reviewer(api, ctx)

    engagements = []
    for client in (
        "Aurora Metals Inc", "Bellhaven Clinics", "Corvid Logistics", "Dunmore Paper Co"
    ):
        row = _new_engagement(
            api, ctx, client_name=client, engagement_type="REVIEW",
            period_end="2026-03-31",
        )
        fixtures.workflow_step(api, row, "FIELDWORK", ctx["ep_headers"])
        engagements.append(row)

    for row in engagements[:3]:
        created_entity(_assign_eqr(api, ctx, row["id"], eqrp["id"]))

    fourth = engagements[3]
    validate_error(
        _assign_eqr(api, ctx, fourth["id"], eqrp["id"]),
        api_errors.ERR_EQR_CAPACITY_EXCEEDED,
    )

    assert_fields(
        read_entity(api.get_partner(eqrp["id"], headers=ctx["mp_headers"])),
        open_eqr_count=3,
    )
    assert _total_count(
        api.list_quality_reviews(
            headers=ctx["mp_headers"], params={"engagement_id": fourth["id"]}
        )
    ) == 0

    # The already-assigned guard sits after aggregate capacity, so it is probed
    # with a reviewer who still has free slots.
    spare = _eq_reviewer(api, ctx, full_name="Tomas Iriarte")
    validate_error(
        _assign_eqr(api, ctx, engagements[0]["id"], spare["id"]),
        api_errors.ERR_EQR_ALREADY_ASSIGNED,
    )


def test_explicitly_named_reviewer_rejections_are_each_distinct(api):
    """Naming a reviewer explicitly turns each eligibility clause into its own error instead of a silent exclusion from the pool.

    "the clauses are evaluated in the order given and the first failure decides
    the error" when "`reviewer_id` is supplied".

    Design: Corner/errors/explicitly_named_reviewer_rejections_are_each_distinct
    """
    ctx = _firm_a(api)
    eqrp = _eq_reviewer(api, ctx)
    erisa = _new_engagement(api, ctx, **ENG_ERISA)
    _release_with_eqr(api, ctx, erisa, eqrp)

    suspended = fixtures.new_peer_reviewer(
        api, reviewer_firm_name="Marlow Sturgis PC", license_state="TX",
        qualified_categories=["ERISA_AUDIT"], status="SUSPENDED",
    )
    out_of_state = fixtures.new_peer_reviewer(
        api, reviewer_firm_name="Bassett Nolan LLP", license_state="NV",
        accepts_out_of_state=False, qualified_categories=["ERISA_AUDIT"],
    )
    unqualified = fixtures.new_peer_reviewer(
        api, reviewer_firm_name="Quillen Advisory PC", license_state="TX",
        qualified_categories=[],
    )
    read_entity(
        api.update_firm(
            ctx["firm_id"], {"prior_reviewer_ids": [unqualified["id"]]},
            headers=fixtures.COMMITTEE,
        )
    )
    review = fixtures.new_peer_review(api, ctx["firm_id"], **PEER_REVIEW_A)

    def _assign(reviewer_id):
        return api.assign_peer_reviewer(
            review["id"], f.reviewer_assignment_payload(reviewer_id),
            headers=fixtures.COMMITTEE,
        )

    validate_error(_assign(suspended["id"]), api_errors.ERR_REVIEWER_SUSPENDED)
    validate_error(
        _assign(out_of_state["id"]), api_errors.ERR_REVIEWER_STATE_NOT_LICENSED
    )
    validate_error(
        _assign(unqualified["id"]), api_errors.ERR_REVIEWER_ROTATION_REQUIRED
    )

    read_entity(
        api.update_firm(
            ctx["firm_id"], {"prior_reviewer_ids": []}, headers=fixtures.COMMITTEE
        )
    )
    validate_error(
        _assign(unqualified["id"]), api_errors.ERR_MUST_SELECT_CATEGORY_NOT_QUALIFIED
    )

    assert_fields(
        read_entity(api.get_peer_review(review["id"], headers=fixtures.COMMITTEE)),
        state="SCHEDULED",
        assigned_reviewer_id=None,
    )


def test_inspection_cycle_transition_guards_are_each_distinct(api):
    """Each leg of the inspection cycle owns its own refusal: an empty selector run, a finding raised too early, an unclassified finding and an open significant finding.

    "a cycle whose selector produced nothing is refused with
    `ERR_NO_ELIGIBLE_ENGAGEMENTS`".

    Design: Corner/errors/inspection_cycle_transition_guards_are_each_distinct
    """
    ctx = _firm_a(api)
    _new_engagement(api, ctx, **ENG_A)  # never released, so nothing is eligible
    empty_cycle = fixtures.new_inspection(api, ctx)
    fixtures.run_selector(api, ctx, empty_cycle["id"])

    validate_error(
        api.create_inspection_transition(
            empty_cycle["id"], f.inspection_transition_payload("IN_PROGRESS"),
            headers=ctx["qc_headers"],
        ),
        api_errors.ERR_NO_ELIGIBLE_ENGAGEMENTS,
    )
    after = read_entity(
        api.get_internal_inspection(empty_cycle["id"], headers=ctx["qc_headers"])
    )
    assert_fields(
        after,
        state="SELECTION_COMPLETE",
        engagements_selected_count=0,
        deficiency_severity_index=None,
    )
    assert_decimal_equals(after["must_select_coverage_pct"], 100.00)

    # A second firm carries the remaining guards, since a firm may hold only one
    # cycle per inspection year.
    ctx_b = _firm_b(api)
    engagement_b = _new_engagement(
        api, ctx_b, client_name="Silverbrook Utilities", engagement_type="REVIEW",
        period_end="2026-05-31",
    )
    _release_simple(api, ctx_b, engagement_b)
    cycle = fixtures.new_inspection(api, ctx_b)
    fixtures.run_selector(api, ctx_b, cycle["id"])
    selection = fixtures.selections_of(api, ctx_b, cycle["id"])[0]

    validate_error(
        api.create_inspection_finding(
            selection["id"], f.inspection_finding_payload(),
            headers=ctx_b["qc_headers"],
        ),
        api_errors.ERR_INSPECTION_NOT_IN_PROGRESS,
    )

    fixtures.inspection_step(api, ctx_b, cycle["id"], "IN_PROGRESS")
    finding = fixtures.new_finding(
        api, ctx_b, selection["id"],
        title="Review notes not cleared before report release",
        sqm_component="ENGAGEMENT_PERFORMANCE",
    )
    validate_error(
        api.create_inspection_transition(
            cycle["id"],
            f.inspection_transition_payload(
                "FINDINGS_CLASSIFIED", severity_index_basis="ENGAGEMENT_WEIGHTED"
            ),
            headers=ctx_b["qc_headers"],
        ),
        api_errors.ERR_UNCLASSIFIED_FINDINGS_PRESENT,
    )

    fixtures.classify(
        api, ctx_b, finding["id"], "SIGNIFICANT_DEFICIENCY",
        pervasiveness="ISOLATED", affects_report_conclusion=False,
    )
    fixtures.inspection_step(
        api, ctx_b, cycle["id"], "FINDINGS_CLASSIFIED",
        severity_index_basis="ENGAGEMENT_WEIGHTED",
    )
    validate_error(
        api.create_inspection_transition(
            cycle["id"], f.inspection_transition_payload("CONCLUDED"),
            headers=ctx_b["qc_headers"],
        ),
        api_errors.ERR_OPEN_SIGNIFICANT_FINDINGS,
    )


def test_remediation_chain_guards_reject_each_premature_step(api):
    """Each step of the remediation chain has its own gate: an unvalidated analysis, a sub-threshold acceptance score, unfinished actions and an analysis belonging to another finding.

    "Citing an analysis whose state is not `VALIDATED` is refused with
    `ERR_RCA_NOT_VALIDATED`".

    Design: Corner/errors/remediation_chain_guards_reject_each_premature_step
    """
    ctx = _firm_a(api)
    engagement = _new_engagement(api, ctx, **ENG_A)
    _release_simple(api, ctx, engagement)
    inspection = fixtures.new_inspection(api, ctx)
    fixtures.run_selector(api, ctx, inspection["id"])
    selection = fixtures.selections_of(api, ctx, inspection["id"])[0]
    fixtures.inspection_step(api, ctx, inspection["id"], "IN_PROGRESS")

    narrative = (
        "Supervisory review was performed after the report date and was not "
        "documented."
    )

    def _deficiency_finding(title):
        row = fixtures.new_finding(
            api, ctx, selection["id"], title=title,
            sqm_component="ENGAGEMENT_PERFORMANCE",
        )
        fixtures.classify(
            api, ctx, row["id"], "DEFICIENCY", pervasiveness="ISOLATED",
            affects_report_conclusion=False,
        )
        return row

    finding = _deficiency_finding("Review notes not cleared before report release")
    drafted_rca = created_entity(
        api.create_root_cause_analysis(
            finding["id"],
            f.rca_payload(
                method="FISHBONE", root_cause_category="SUPERVISION_REVIEW",
                contributing_factor_count=3, narrative=narrative,
            ),
            headers=ctx["qc_headers"],
        )
    )
    current = read_entity(
        api.get_inspection_finding(finding["id"], headers=ctx["qc_headers"])
    )

    validate_error(
        api.create_remediation_plan(
            finding["id"],
            f.remediation_plan_payload(
                drafted_rca["id"], ctx["qc"]["id"], current["version"],
                target_completion_date="2026-09-30", action_count=4,
                action_specificity_score=2.00,
            ),
            headers=ctx["mp_headers"],
        ),
        api_errors.ERR_RCA_NOT_VALIDATED,
    )
    assert_fields(
        read_entity(
            api.get_inspection_finding(finding["id"], headers=ctx["qc_headers"])
        ),
        state="RCA_PENDING",
    )
    assert _total_count(
        api.list_remediation_plans(
            headers=ctx["qc_headers"], params={"finding_id": finding["id"]}
        )
    ) == 0

    # Validating the analysis unblocks the create; the resulting score is too low
    # for acceptance.
    validated = read_entity(
        api.create_rca_validation(
            drafted_rca["id"], f.rca_validation_payload("VALIDATED"),
            headers=ctx["qc_headers"],
        )
    )
    assert_decimal_equals(validated["depth_score"], 9.00)
    plan = fixtures.new_remediation_plan(
        api, ctx, finding["id"], drafted_rca["id"], ctx["qc"]["id"],
        target_completion_date="2026-09-30", action_count=4,
        action_specificity_score=2.00,
    )
    submitted = fixtures.plan_step(
        api, ctx, plan["id"], "SUBMITTED", completed_action_count=0
    )
    assert_decimal_equals(submitted["raw_completeness"], 4.30)
    assert_decimal_equals(submitted["acceptance_score"], 4.30)
    assert_fields(submitted, completeness_tier="CRITICAL")
    validate_error(
        api.create_remediation_plan_transition(
            plan["id"], f.remediation_transition_payload("ACCEPTED"),
            headers=ctx["mp_headers"],
        ),
        api_errors.ERR_ACCEPTANCE_SCORE_BELOW_THRESHOLD,
    )

    # A better specified plan clears the threshold but still cannot be reported
    # complete while two of its four actions are outstanding.
    finding_2 = _deficiency_finding("Engagement letter not signed before fieldwork")
    rca_2 = fixtures.validated_rca(
        api, ctx, finding_2["id"], method="FISHBONE",
        root_cause_category="SUPERVISION_REVIEW", contributing_factor_count=3,
        narrative=narrative,
    )
    plan_2 = fixtures.new_remediation_plan(
        api, ctx, finding_2["id"], rca_2["id"], ctx["qc"]["id"],
        target_completion_date="2026-09-30", action_count=4,
        action_specificity_score=8.00,
    )
    submitted_2 = fixtures.plan_step(
        api, ctx, plan_2["id"], "SUBMITTED", completed_action_count=2
    )
    assert_decimal_equals(submitted_2["raw_completeness"], 7.65)
    read_entity(
        api.create_remediation_plan_transition(
            plan_2["id"], f.remediation_transition_payload("ACCEPTED"),
            headers=ctx["mp_headers"],
        )
    )
    validate_error(
        api.create_remediation_plan_transition(
            plan_2["id"], f.remediation_transition_payload("COMPLETED"),
            headers=ctx["qc_headers"],
        ),
        api_errors.ERR_REMEDIATION_ACTIONS_INCOMPLETE,
    )

    # Citing a validated analysis that belongs to a different finding.
    finding_3 = _deficiency_finding("Independence confirmations missing for staff")
    fixtures.validated_rca(
        api, ctx, finding_3["id"], method="FISHBONE",
        root_cause_category="SUPERVISION_REVIEW", contributing_factor_count=3,
        narrative=narrative,
    )
    third = read_entity(
        api.get_inspection_finding(finding_3["id"], headers=ctx["qc_headers"])
    )
    validate_error(
        api.create_remediation_plan(
            finding_3["id"],
            f.remediation_plan_payload(
                rca_2["id"], ctx["qc"]["id"], third["version"],
                target_completion_date="2026-09-30", action_count=4,
                action_specificity_score=8.00,
            ),
            headers=ctx["mp_headers"],
        ),
        api_errors.ERR_RCA_FINDING_MISMATCH,
    )


def test_peer_review_scope_and_rating_guards_are_each_distinct(api):
    """Four separate guards protect a peer review's scope and rating: a missing disposition, a duplicate selection, an out-of-period engagement and an uncovered must-select category.

    "`FIELDWORK → RATING_DRAFTED` requires every committed selection to carry a
    `disposition` other than `NONE`, otherwise
    `ERR_SELECTION_DISPOSITION_MISSING`".

    Design: Corner/errors/peer_review_scope_and_rating_guards_are_each_distinct
    """
    ctx = _firm_a(api)
    engagement = _new_engagement(api, ctx, **ENG_A)
    _release_simple(api, ctx, engagement)
    _concluded_inspection(api, ctx)

    reviewer = fixtures.new_peer_reviewer(api, **PEER_REVIEWER_A)
    reviewer_headers = make_peer_reviewer_headers(reviewer["id"])
    review = fixtures.new_peer_review(api, ctx["firm_id"], **PEER_REVIEW_A)
    fixtures.assign_reviewer(api, review["id"], reviewer["id"])
    fixtures.set_scope(api, review["id"], reviewer["id"])
    selection = fixtures.select_engagement(
        api, review["id"], reviewer["id"], engagement["id"], hours_committed=12
    )
    fixtures.peer_review_step(api, review["id"], "FIELDWORK", reviewer_headers)

    def _select(review_id, engagement_id, hours=12, **overrides):
        current = read_entity(api.get_peer_review(review_id, headers=reviewer_headers))
        return api.create_peer_review_selection(
            review_id,
            f.peer_review_selection_payload(
                engagement_id, current["version"], hours, **overrides
            ),
            headers=reviewer_headers,
        )

    validate_error(
        api.create_peer_review_transition(
            review["id"], f.peer_review_transition_payload("RATING_DRAFTED"),
            headers=reviewer_headers,
        ),
        api_errors.ERR_SELECTION_DISPOSITION_MISSING,
    )
    assert_fields(
        read_entity(api.get_peer_review(review["id"], headers=reviewer_headers)),
        state="FIELDWORK",
        rating="NONE",
    )

    validate_error(
        _select(review["id"], engagement["id"]), api_errors.ERR_DUPLICATE_SELECTION
    )

    late_period = _new_engagement(
        api, ctx, client_name="Thistledown Grain Co", engagement_type="REVIEW",
        period_end="2026-08-31",
    )
    validate_error(
        _select(review["id"], late_period["id"]),
        api_errors.ERR_ENGAGEMENT_OUTSIDE_REVIEW_SCOPE,
    )

    # A second review whose must-select categories are not covered by its only
    # selection cannot enter fieldwork.
    erisa = _new_engagement(api, ctx, **ENG_ERISA)
    _release_with_eqr(api, ctx, erisa, _eq_reviewer(api, ctx))
    second = fixtures.new_peer_review(
        api, ctx["firm_id"], review_type="SYSTEM_REVIEW", year_end="2026-06-30",
        scheduled_window_start="2026-11-01", scheduled_window_end="2026-11-10",
    )
    fixtures.assign_reviewer(api, second["id"], reviewer["id"])
    scoped_second = fixtures.set_scope(api, second["id"], reviewer["id"])
    assert_fields(scoped_second, must_select_categories=["ERISA_AUDIT"])
    fixtures.select_engagement(
        api, second["id"], reviewer["id"], engagement["id"], hours_committed=12
    )
    validate_error(
        api.create_peer_review_transition(
            second["id"], f.peer_review_transition_payload("FIELDWORK"),
            headers=reviewer_headers,
        ),
        api_errors.ERR_MUST_SELECT_CATEGORY_NOT_COVERED,
    )

    # Once the first review is rated, further scope work on it is refused.
    fixtures.record_disposition(api, selection["id"], reviewer["id"], "NO_MATTER")
    rated = fixtures.peer_review_step(
        api, review["id"], "RATING_DRAFTED", reviewer_headers
    )
    assert_fields(rated, rating="PASS")
    validate_error(
        api.create_selection_disposition(
            selection["id"], f.disposition_payload("DEFICIENCY"),
            headers=reviewer_headers,
        ),
        api_errors.ERR_PEER_REVIEW_ALREADY_RATED,
    )


def test_locked_file_and_unconcurred_eqr_block_engagement_writes(api):
    """A locked documentation file blocks further file writes, and the two quality-review gates on the performance dimension are separate errors.

    "A locked file blocks writes to both dimensions"; clearing quality review
    without a `CONCURRED` review "is refused with `ERR_EQR_NOT_CONCURRED`".

    Design: Corner/errors/locked_file_and_unconcurred_eqr_block_engagement_writes
    """
    ctx = _firm_a(api)
    engagement = _new_engagement(api, ctx, **ENG_A)
    _release_simple(api, ctx, engagement)
    fixtures.file_step(api, engagement, "ASSEMBLED", ctx["ep_headers"])
    fixtures.file_step(api, engagement, "LOCKED", ctx["ep_headers"])

    validate_error(
        api.create_file_transition(
            engagement["id"], f.file_transition_payload("ASSEMBLED"),
            headers=ctx["ep_headers"],
        ),
        api_errors.ERR_ENGAGEMENT_FILE_LOCKED,
    )
    assert_fields(
        read_entity(api.get_engagement(engagement["id"], headers=ctx["mp_headers"])),
        file_state="LOCKED",
        workflow_state="REPORT_RELEASED",
        reopened_count=0,
        version=7,
    )

    # An engagement that requires a quality review cannot clear it unaided.
    erisa = _new_engagement(api, ctx, **ENG_ERISA)
    fixtures.workflow_step(api, erisa, "FIELDWORK", ctx["ep_headers"])
    fixtures.workflow_step(api, erisa, "EQR_PENDING", ctx["ep_headers"])
    validate_error(
        api.create_workflow_transition(
            erisa["id"], f.workflow_transition_payload("EQR_CLEARED"),
            headers=ctx["ep_headers"],
        ),
        api_errors.ERR_EQR_NOT_CONCURRED,
    )

    # A review carrying unresolved concerns cannot concur.
    eqrp = _eq_reviewer(api, ctx)
    eqr = created_entity(_assign_eqr(api, ctx, erisa["id"], eqrp["id"]))
    reviewer_headers = make_eq_reviewer_headers(eqrp["id"])
    read_entity(
        api.create_quality_review_transition(
            eqr["id"], f.quality_review_transition_payload("IN_PROGRESS"),
            headers=reviewer_headers,
        )
    )
    read_entity(
        api.create_quality_review_transition(
            eqr["id"],
            f.quality_review_transition_payload(
                "CONCERNS_RAISED",
                concern_summary="Sampling of participant data is not documented.",
            ),
            headers=reviewer_headers,
        )
    )
    validate_error(
        api.create_quality_review_transition(
            eqr["id"], f.quality_review_transition_payload("CONCURRED"),
            headers=reviewer_headers,
        ),
        api_errors.ERR_UNRESOLVED_CONCERNS,
    )


def test_corrective_action_evidence_after_the_due_date_is_rejected(api):
    """Evidence filed one day after a synthesized corrective action plan's due date is refused, and the two ratings that fork the review produce different plans.

    "The logical clock's date must be on or before the plan's `due_date`; a late
    submission is refused with `ERR_CORRECTIVE_ACTION_PAST_DUE`".

    Design: Corner/errors/corrective_action_evidence_after_the_due_date_is_rejected
    """
    ctx = _firm_a(api)
    engagement = _new_engagement(api, ctx, **ENG_A)
    _release_simple(api, ctx, engagement)
    _concluded_inspection(api, ctx)

    def _issued_review(reviewer, window, disposition, scope_limitation):
        review = fixtures.new_peer_review(
            api, ctx["firm_id"], review_type="SYSTEM_REVIEW", year_end="2026-06-30",
            scheduled_window_start=window[0], scheduled_window_end=window[1],
        )
        headers = make_peer_reviewer_headers(reviewer["id"])
        fixtures.assign_reviewer(api, review["id"], reviewer["id"])
        fixtures.set_scope(api, review["id"], reviewer["id"])
        selection = fixtures.select_engagement(
            api, review["id"], reviewer["id"], engagement["id"], hours_committed=12,
            is_scope_limitation=scope_limitation,
        )
        fixtures.peer_review_step(api, review["id"], "FIELDWORK", headers)
        fixtures.record_disposition(
            api, selection["id"], reviewer["id"], disposition
        )
        fixtures.peer_review_step(api, review["id"], "RATING_DRAFTED", headers)
        return fixtures.peer_review_step(api, review["id"], "REPORT_ISSUED", headers)

    # A single scope limitation with an FFC disposition rates PASS_WITH_DEFICIENCY.
    deficient = _issued_review(
        fixtures.new_peer_reviewer(api, **PEER_REVIEWER_A),
        ("2026-10-01", "2026-10-15"), "FFC", True,
    )
    assert_fields(
        deficient, state="CORRECTIVE_ACTION_REQUIRED", rating="PASS_WITH_DEFICIENCY"
    )
    plan = fixtures.corrective_action_plans_of(api, deficient["id"])[0]

    # A SIGNIFICANT_DEFICIENCY disposition rates FAIL, which forks to a
    # preissuance review due 45 rather than 90 days after issuance.
    failed = _issued_review(
        fixtures.new_peer_reviewer(
            api, reviewer_firm_name="Ostend & Frayne LLP", license_state="TX",
            qualified_categories=ALL_CATEGORIES, max_concurrent_reviews=2,
            experience_hours=3500,
        ),
        ("2026-11-01", "2026-11-10"), "SIGNIFICANT_DEFICIENCY", False,
    )
    assert_fields(failed, rating="FAIL")
    fail_plan = fixtures.corrective_action_plans_of(api, failed["id"])[0]
    assert_fields(
        fail_plan, action_code="PREISSUANCE_REVIEW", due_date="2026-09-15"
    )

    _set_clock(api, "2026-10-31T00:00:00Z")

    validate_error(
        api.create_corrective_action_evidence(
            plan["id"],
            f.corrective_action_evidence_payload(
                evidence_summary=(
                    "Monitoring visit completed; supervision checklist rolled out "
                    "firm-wide."
                )
            ),
            headers=ctx["qc_headers"],
        ),
        api_errors.ERR_CORRECTIVE_ACTION_PAST_DUE,
    )

    assert_fields(
        read_entity(
            api.get_corrective_action_plan(plan["id"], headers=ctx["qc_headers"])
        ),
        action_code="MONITORING_VISIT",
        due_date="2026-10-30",
        status="REQUIRED",
        evidence_submitted_at=None,
        rejection_count=0,
    )
    assert_fields(
        read_entity(api.get_peer_review(deficient["id"], headers=fixtures.COMMITTEE)),
        state="CORRECTIVE_ACTION_REQUIRED",
        rating="PASS_WITH_DEFICIENCY",
    )
    assert_fields(
        read_entity(api.get_firm(ctx["firm_id"], headers=fixtures.ADMIN)),
        last_peer_review_rating="NONE",
    )
