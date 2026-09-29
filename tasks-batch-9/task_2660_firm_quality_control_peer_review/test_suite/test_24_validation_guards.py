"""Validation guards: boundary values, evaluation order and aggregate budgets.

Each test builds its own world from scratch through the PRD's endpoints and
then probes exactly one guard, including the three worked collisions of §2.5
where two rules are violated by the same request and the PRD pins which
``error_id`` the caller must see.
"""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, factories as f, fixtures
from test_helpers.assertions import (
    assert_fields,
    created_entity,
    read_entity,
)
from test_helpers.constants import DEFAULT_CLOCK
from test_helpers.test_users import (
    make_engagement_partner_headers,
    make_eq_reviewer_headers,
    make_managing_partner_headers,
    make_peer_reviewer_headers,
    make_qc_director_headers,
    make_system_admin_headers,
)

# --------------------------------------------------------------------------
# Fixed inputs shared by the probes below
# --------------------------------------------------------------------------
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
PEER_REVIEWER_A = dict(
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


def _release_with_eqr(api, ctx, engagement, reviewer):
    """Drive an engagement whose ``eqr_required`` is true to REPORT_RELEASED."""
    ep_headers = ctx["ep_headers"]
    fixtures.workflow_step(api, engagement, "FIELDWORK", ep_headers)
    current = fixtures.read_engagement(api, engagement["id"], ep_headers)
    eqr = created_entity(
        api.assign_quality_review(
            engagement["id"],
            f.quality_review_assignment_payload(reviewer["id"], current["version"]),
            headers=ctx["qc_headers"],
        )
    )
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


def _total_count(response) -> int:
    validate_success(response)
    return response.json()["meta"]["total_count"]


def _set_clock(api, instant: str) -> None:
    validate_success(
        api.set_clock(instant, headers=make_system_admin_headers()), expected_status=200
    )


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------
def test_eqr_window_outranks_cooling_off(api):
    """A quality-reviewer assignment on a released engagement fails on the review window even when the candidate also breaches the 730-day cooling-off gate.

    "the response is `ERR_ENGAGEMENT_NOT_IN_EQR_WINDOW`, because the
    target-state precondition outranks the independence-and-objectivity band."

    Design: Corner/validations/eqr_window_check_outranks_cooling_off_and_returns_not_in_eqr_window
    """
    ctx = _firm_a(api)
    engagement = _new_engagement(api, ctx, **ENG_A)
    released = _release_simple(api, ctx, engagement)

    candidate = fixtures.new_partner(
        api, ctx["firm_id"], full_name="Priya Raman", cpa_license_state="TX",
        designations=["EQ_REVIEWER"], cpe_hours_last_3y=160,
        prior_engagement_team_clients=[
            {"client_name": "Aurora Metals Inc", "exit_date": "2025-02-24"}
        ],
    )

    response = api.assign_quality_review(
        engagement["id"],
        f.quality_review_assignment_payload(candidate["id"], released["version"]),
        headers=ctx["mp_headers"],
    )
    validate_error(response, api_errors.ERR_ENGAGEMENT_NOT_IN_EQR_WINDOW)

    assert _total_count(
        api.list_quality_reviews(
            headers=ctx["mp_headers"], params={"engagement_id": engagement["id"]}
        )
    ) == 0
    partner = read_entity(api.get_partner(candidate["id"], headers=ctx["mp_headers"]))
    assert_fields(partner, open_eqr_count=0)


def test_engagement_firm_mismatch_outranks_scope_hours_exceeded(api):
    """A peer review selection naming another firm's engagement with more hours than remain fails on referential consistency, not on the hours budget.

    "Referential integrity is evaluated first" — the fiscal
    `ERR_SCOPE_HOURS_EXCEEDED` "runs last of all".

    Design: Corner/validations/engagement_firm_mismatch_outranks_scope_hours_exceeded
    """
    ctx = _firm_a(api)
    engagement = _new_engagement(api, ctx, **ENG_A)
    _release_simple(api, ctx, engagement)

    reviewer = fixtures.new_peer_reviewer(api, **PEER_REVIEWER_A)
    review = fixtures.new_peer_review(api, ctx["firm_id"], **PEER_REVIEW_A)
    fixtures.assign_reviewer(api, review["id"], reviewer["id"])
    scoped = fixtures.set_scope(api, review["id"], reviewer["id"])
    assert_fields(scoped, state="SCOPE_SET", total_scope_hours=40, unallocated_hours=40)

    ctx_b = _firm_b(api)
    other_engagement = _new_engagement(
        api, ctx_b, client_name="Silverbrook Utilities",
        engagement_type="REVIEW", period_end="2026-05-31",
    )

    reviewer_headers = make_peer_reviewer_headers(reviewer["id"])
    response = api.create_peer_review_selection(
        review["id"],
        f.peer_review_selection_payload(
            other_engagement["id"], scoped["version"], 200
        ),
        headers=reviewer_headers,
    )
    validate_error(response, api_errors.ERR_ENGAGEMENT_FIRM_MISMATCH)

    after = read_entity(api.get_peer_review(review["id"], headers=reviewer_headers))
    assert_fields(after, unallocated_hours=40, state="SCOPE_SET")
    assert _total_count(
        api.list_peer_review_selections(
            headers=reviewer_headers, params={"peer_review_id": review["id"]}
        )
    ) == 0


def test_reviewer_window_conflict_outranks_reviewer_at_capacity(api):
    """Assigning a fully committed reviewer to a window that collides with their existing engagement under the travel buffer reports the window conflict, not the capacity cap.

    "the response is `ERR_REVIEWER_WINDOW_CONFLICT`, because the temporal window
    check sits ahead of capacity in the ordering."

    Design: Corner/validations/reviewer_window_conflict_outranks_reviewer_at_capacity
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    firm_a = fixtures.new_firm(api, **FIRM_A)
    firm_b = fixtures.new_firm(api, **FIRM_B)

    reviewer = fixtures.new_peer_reviewer(
        api,
        reviewer_firm_name="Halloway & Reid LLP",
        license_state="TX",
        accepts_out_of_state=True,
        qualified_categories=PEER_REVIEWER_A["qualified_categories"],
        max_concurrent_reviews=1,
        experience_hours=3000,
    )
    other_review = fixtures.new_peer_review(
        api, firm_b["id"], review_type="SYSTEM_REVIEW", year_end="2026-06-30",
        scheduled_window_start="2026-10-12", scheduled_window_end="2026-10-20",
    )
    fixtures.assign_reviewer(api, other_review["id"], reviewer["id"])

    review = fixtures.new_peer_review(api, firm_a["id"], **PEER_REVIEW_A)
    response = api.assign_peer_reviewer(
        review["id"],
        f.reviewer_assignment_payload(reviewer["id"]),
        headers=fixtures.COMMITTEE,
    )
    validate_error(response, api_errors.ERR_REVIEWER_WINDOW_CONFLICT)

    after = read_entity(
        api.get_peer_review(review["id"], headers=fixtures.COMMITTEE)
    )
    assert_fields(after, state="SCHEDULED", assigned_reviewer_id=None)
    roster_entry = read_entity(
        api.get_peer_reviewer(reviewer["id"], headers=fixtures.COMMITTEE)
    )
    assert_fields(roster_entry, active_review_count=1)
    firm = read_entity(api.get_firm(firm_a["id"], headers=fixtures.ADMIN))
    assert_fields(firm, unassigned_review_flag=False)


def test_documentation_lock_at_exactly_sixty_days_is_accepted(api):
    """Locking an assembled file on the sixtieth day after report release succeeds, because the window rule is inclusive.

    "the logical clock's date is on or before 60 days after
    `report_release_date`".

    Design: Corner/validations/documentation_lock_at_exactly_sixty_days_is_accepted
    """
    ctx = _firm_a(api)
    engagement = _new_engagement(api, ctx, **ENG_A)
    _release_simple(api, ctx, engagement)
    assembled = fixtures.file_step(api, engagement, "ASSEMBLED", ctx["ep_headers"])
    assert_fields(assembled, file_state="ASSEMBLED", version=6)

    _set_clock(api, "2026-09-30T00:00:00Z")

    locked = read_entity(
        api.create_file_transition(
            engagement["id"], f.file_transition_payload("LOCKED"),
            headers=ctx["ep_headers"],
        )
    )
    assert_fields(
        locked,
        file_state="LOCKED",
        workflow_state="REPORT_RELEASED",
        report_release_date="2026-08-01",
        reopened_count=0,
        version=7,
    )


def test_documentation_lock_on_day_sixty_one_is_rejected(api):
    """Locking an assembled file on the sixty-first day after report release is refused and leaves the file assembled.

    "A lock attempt after that window is refused with
    `ERR_DOCUMENTATION_WINDOW_CLOSED`".

    Design: Corner/validations/documentation_lock_on_day_sixty_one_is_rejected
    """
    ctx = _firm_a(api)
    engagement = _new_engagement(api, ctx, **ENG_A)
    _release_simple(api, ctx, engagement)
    fixtures.file_step(api, engagement, "ASSEMBLED", ctx["ep_headers"])

    _set_clock(api, "2026-10-01T00:00:00Z")

    response = api.create_file_transition(
        engagement["id"], f.file_transition_payload("LOCKED"), headers=ctx["ep_headers"]
    )
    validate_error(response, api_errors.ERR_DOCUMENTATION_WINDOW_CLOSED)

    after = fixtures.read_engagement(api, engagement["id"], ctx["ep_headers"])
    assert_fields(after, file_state="ASSEMBLED", version=6)


def test_material_failure_without_report_impact_is_rejected(api):
    """A MATERIAL_FAILURE classification that denies any report impact is refused and none of the material-failure cascade runs.

    "A `MATERIAL_FAILURE` classification requires `affects_report_conclusion`
    true, otherwise `ERR_MATERIAL_FAILURE_REQUIRES_REPORT_IMPACT`".

    Design: Corner/validations/material_failure_without_report_impact_is_rejected
    """
    ctx = _firm_a(api)
    engagement = _new_engagement(api, ctx, **ENG_A)
    _release_simple(api, ctx, engagement)

    inspection = fixtures.new_inspection(api, ctx)
    fixtures.run_selector(api, ctx, inspection["id"])
    selection = fixtures.selections_of(api, ctx, inspection["id"])[0]
    fixtures.inspection_step(api, ctx, inspection["id"], "IN_PROGRESS")
    finding = fixtures.new_finding(
        api, ctx, selection["id"],
        title="Review notes not cleared before report release",
        sqm_component="ENGAGEMENT_PERFORMANCE",
    )

    response = api.classify_finding(
        finding["id"],
        f.classification_payload(
            "MATERIAL_FAILURE", pervasiveness="SYSTEMIC",
            affects_report_conclusion=False,
        ),
        headers=ctx["qc_headers"],
    )
    validate_error(response, api_errors.ERR_MATERIAL_FAILURE_REQUIRES_REPORT_IMPACT)

    after = read_entity(
        api.get_inspection_finding(finding["id"], headers=ctx["qc_headers"])
    )
    assert_fields(
        after, classification="UNCLASSIFIED", state="IDENTIFIED", class_points=0
    )
    firm = read_entity(api.get_firm(ctx["firm_id"], headers=fixtures.ADMIN))
    assert_fields(firm, open_material_failure_count=0, risk_posture="STABLE")
    assert_fields(
        fixtures.read_engagement(api, engagement["id"], ctx["ep_headers"]),
        reopened_count=0,
    )


def test_operating_basis_without_a_tested_response_is_rejected(api):
    """Evaluating a risk on the operating basis when its only response has never been tested is refused rather than folding an empty input set.

    "an evaluation whose input set is empty — `OPERATING_BASIS` with no tested
    response — is refused with `ERR_NO_TESTED_RESPONSE`".

    Design: Corner/validations/operating_basis_without_a_tested_response_is_rejected
    """
    ctx = _firm_a(api)
    risk = fixtures.new_quality_risk(
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
    response_row = fixtures.new_risk_response(
        api, ctx, risk["id"], response_type="PREVENTIVE"
    )

    response = api.create_risk_evaluation(
        risk["id"], f.risk_evaluation_payload("OPERATING_BASIS"),
        headers=ctx["qc_headers"],
    )
    validate_error(response, api_errors.ERR_NO_TESTED_RESPONSE)

    after = read_entity(api.get_quality_risk(risk["id"], headers=ctx["qc_headers"]))
    assert_fields(
        after,
        state="RESPONDED",
        residual_risk_score=None,
        severity_band="NONE",
        evaluation_basis="NONE",
    )
    assert_fields(
        read_entity(
            api.get_risk_response(response_row["id"], headers=ctx["qc_headers"])
        ),
        status="DESIGNED",
        operating_effectiveness="NOT_TESTED",
    )


def test_second_selection_exceeding_the_remaining_hours_is_rejected(api):
    """Hours are budgeted against the live unallocated balance, so a second selection that fits the total but not the remainder is refused.

    "`hours_committed` may not exceed the review's remaining
    `unallocated_hours`, otherwise `ERR_SCOPE_HOURS_EXCEEDED`".

    Design: Corner/validations/second_selection_exceeding_the_remaining_hours_is_rejected
    """
    ctx = _firm_a(api)
    engagement = _new_engagement(api, ctx, **ENG_A)
    _release_simple(api, ctx, engagement)

    eq_reviewer = _eq_reviewer(api, ctx)
    erisa = _new_engagement(api, ctx, **ENG_ERISA)
    _release_with_eqr(api, ctx, erisa, eq_reviewer)

    reviewer = fixtures.new_peer_reviewer(api, **PEER_REVIEWER_A)
    review = fixtures.new_peer_review(api, ctx["firm_id"], **PEER_REVIEW_A)
    fixtures.assign_reviewer(api, review["id"], reviewer["id"])
    scoped = fixtures.set_scope(api, review["id"], reviewer["id"])
    assert_fields(
        scoped,
        must_select_categories=["ERISA_AUDIT"],
        total_scope_hours=48,
        unallocated_hours=48,
    )

    fixtures.select_engagement(
        api, review["id"], reviewer["id"], engagement["id"], hours_committed=30
    )
    reviewer_headers = make_peer_reviewer_headers(reviewer["id"])
    reread = read_entity(api.get_peer_review(review["id"], headers=reviewer_headers))
    assert_fields(reread, unallocated_hours=18)

    response = api.create_peer_review_selection(
        review["id"],
        f.peer_review_selection_payload(erisa["id"], reread["version"], 20),
        headers=reviewer_headers,
    )
    validate_error(response, api_errors.ERR_SCOPE_HOURS_EXCEEDED)

    after = read_entity(api.get_peer_review(review["id"], headers=reviewer_headers))
    assert_fields(after, total_scope_hours=48, unallocated_hours=18)
    assert _total_count(
        api.list_peer_review_selections(
            headers=reviewer_headers, params={"peer_review_id": review["id"]}
        )
    ) == 1
    assert_fields(
        read_entity(
            api.get_peer_reviewer(reviewer["id"], headers=fixtures.COMMITTEE)
        ),
        committed_hours_balance=30,
    )


def test_peer_review_fieldwork_without_a_concluded_inspection_is_rejected(api):
    """Fieldwork cannot open while the firm's newest internal inspection cycle is unfinished.

    "The firm's internal inspection cycle with the highest `inspection_year`
    must exist and must have reached `CONCLUDED`".

    Design: Corner/validations/peer_review_fieldwork_without_a_concluded_inspection_is_rejected
    """
    ctx = _firm_a(api)
    engagement = _new_engagement(api, ctx, **ENG_A)
    _release_simple(api, ctx, engagement)

    inspection = fixtures.new_inspection(api, ctx)
    fixtures.run_selector(api, ctx, inspection["id"])

    reviewer = fixtures.new_peer_reviewer(api, **PEER_REVIEWER_A)
    review = fixtures.new_peer_review(api, ctx["firm_id"], **PEER_REVIEW_A)
    fixtures.assign_reviewer(api, review["id"], reviewer["id"])
    fixtures.set_scope(api, review["id"], reviewer["id"])
    fixtures.select_engagement(
        api, review["id"], reviewer["id"], engagement["id"], hours_committed=12
    )

    reviewer_headers = make_peer_reviewer_headers(reviewer["id"])
    response = api.create_peer_review_transition(
        review["id"], f.peer_review_transition_payload("FIELDWORK"),
        headers=reviewer_headers,
    )
    validate_error(response, api_errors.ERR_INSPECTION_NOT_CONCLUDED)

    assert_fields(
        read_entity(api.get_peer_review(review["id"], headers=reviewer_headers)),
        state="SCOPE_SET",
    )
    assert_fields(
        read_entity(
            api.get_internal_inspection(inspection["id"], headers=ctx["qc_headers"])
        ),
        state="SELECTION_COMPLETE",
    )


def test_list_read_with_limit_zero_returns_pagination_out_of_range(api):
    """A limit of zero and a negative offset are both out-of-range pagination inputs, never a clamped or empty page.

    "`limit` defaults to 10, must be at least 1 and at most 100, while `offset`
    defaults to 0 and may never be negative; violations are
    `ERR_PAGINATION_OUT_OF_RANGE`".

    Design: Corner/validations/list_read_with_limit_zero_returns_pagination_out_of_range
    """
    ctx = _firm_a(api)
    _new_engagement(api, ctx, **ENG_A)

    validate_error(
        api.list_engagements(
            headers=ctx["mp_headers"], params={"firm_id": ctx["firm_id"], "limit": 0}
        ),
        api_errors.ERR_PAGINATION_OUT_OF_RANGE,
    )
    validate_error(
        api.list_engagements(
            headers=ctx["mp_headers"], params={"firm_id": ctx["firm_id"], "offset": -1}
        ),
        api_errors.ERR_PAGINATION_OUT_OF_RANGE,
    )
    assert _total_count(
        api.list_engagements(
            headers=ctx["mp_headers"], params={"firm_id": ctx["firm_id"], "limit": 1}
        )
    ) == 1
