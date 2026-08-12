"""Retrofit projects: tiered contingency rounding variants, finalize gates
(empty project, budget, OCC stale version), and the trigger-finding state gate
at approval."""
from test_helpers import (
    ApiErrorId,
    add_line_item,
    assert_retrofit_project,
    create_estimated_project,
    create_retrofit_project,
    get_project_version,
    setup_inspection_with_finding,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ENGINEER = TEST_USERS["compliance_engineer_headers"]
MANAGER = TEST_USERS["compliance_manager_headers"]


def _project_with_two_low_lines(site_id: str, finding_id: str):
    """Project with two LOW line items of 107 and 144 cents."""
    project = create_retrofit_project(site_id, finding_id,
                                      scope_budget_cents=100000)
    add_line_item(site_id, project["id"], cost_cents=107, risk_tier="LOW",
                  description="l1")
    add_line_item(site_id, project["id"], cost_cents=144, risk_tier="LOW",
                  description="l2")
    return project


def test_contingency_per_line_then_sum(api):
    """PRD §3.8: "Each line item contributes a per-line contingency at a
    tier-specific rate: 5 percent of `cost_cents` for `LOW`, 12 percent for
    `MEDIUM`, 22 percent for `HIGH`. Each per-line contingency is rounded to
    the nearest cent, round-half-up, **before** summing."
    PRD §3.8: "`contingency_cents` is the sum of those per-line rounded
    contingencies."
    PRD §3.8: "`total_projected_cents` is `estimated_cost_cents +
    contingency_cents`."

    LOW 107 -> 5.35 -> 5; LOW 144 -> 7.2 -> 7; contingency 12, total 263.

    Design: Difficulty/dual_variant_calc/retrofit_contingency_per_line_then_sum_vs_sum_then_round
    """
    site, inspection, finding = setup_inspection_with_finding(
        severity="CRITICAL", insurer_id="FM-001")
    project = _project_with_two_low_lines(site["id"], finding["id"])

    after = validate_success(
        api.get_retrofit_project(site["id"], project["id"], ENGINEER), 200)
    assert_retrofit_project(after)
    assert after["estimated_cost_cents"] == 251
    assert after["contingency_cents"] == 12
    assert after["total_projected_cents"] == 263


def test_contingency_sum_then_round_insurer_variant(api):
    """PRD §3.8: "There is an **insurer-mandated reporting variant**. When the
    owning Site's `insurer_id` begins with the literal prefix `IC-`, the
    rounding order changes: per-line contingencies are summed *unrounded* and
    the total is rounded once to cents at the end. For projects with two or
    more line items this variant can produce a different `contingency_cents`
    than the default per-line-then-sum order."

    LOW 107 + LOW 144 unrounded: 5.35 + 7.2 = 12.55, rounded once -> 13;
    total 264.

    Design: Difficulty/dual_variant_calc/retrofit_contingency_per_line_then_sum_vs_sum_then_round
    """
    site, inspection, finding = setup_inspection_with_finding(
        severity="CRITICAL", insurer_id="IC-ACME")
    project = _project_with_two_low_lines(site["id"], finding["id"])

    after = validate_success(
        api.get_retrofit_project(site["id"], project["id"], ENGINEER), 200)
    assert after["estimated_cost_cents"] == 251
    assert after["contingency_cents"] == 13
    assert after["total_projected_cents"] == 264


def test_finalize_empty_project_rejected(api):
    """PRD §3.8: "the project must have at least one line item (else
    `ERR_PROJECT_EMPTY`, HTTP 422)".

    Design: Corner/validations/retrofit_finalize_empty_project_rejected
    """
    site, inspection, finding = setup_inspection_with_finding(
        severity="CRITICAL", insurer_id="FM-1")
    project = create_retrofit_project(site["id"], finding["id"],
                                      scope_budget_cents=100000)

    version = get_project_version(site["id"], project["id"])
    res = api.finalize_estimate(site["id"], project["id"], version, ENGINEER)
    validate_error(res, ApiErrorId.ERR_PROJECT_EMPTY)


def test_finalize_budget_exceeded_rejected(api):
    """PRD §3.8: "`total_projected_cents` must not exceed `scope_budget_cents`
    (else `ERR_BUDGET_EXCEEDED`, HTTP 422)".
    PRD §3.8: "Each line item contributes a per-line contingency at a
    tier-specific rate: 5 percent of `cost_cents` for `LOW`, 12 percent for
    `MEDIUM`, 22 percent for `HIGH`."

    One HIGH line of 2000 cents adds 440 contingency -> total 2440 > 1000.

    Design: Corner/errors/err_budget_exceeded
    """
    site, inspection, finding = setup_inspection_with_finding(
        severity="CRITICAL", insurer_id="FM-1")
    project = create_retrofit_project(site["id"], finding["id"],
                                      scope_budget_cents=1000)
    add_line_item(site["id"], project["id"], cost_cents=2000, risk_tier="HIGH")

    version = get_project_version(site["id"], project["id"])
    res = api.finalize_estimate(site["id"], project["id"], version, ENGINEER)
    validate_error(res, ApiErrorId.ERR_BUDGET_EXCEEDED)


def test_finalize_stale_project_version_rejected(api):
    """PRD §2.8: "**Finalizing a retrofit estimate** requires the request body
    to carry `expected_project_version`, which must equal the parent
    RetrofitProject's current `version`. Each line-item creation, update, or
    delete on the project legitimately mutates `estimated_cost_cents` and
    `contingency_cents` and bumps `RetrofitProject.version`. A stale expected
    version signals that the proposed totals were derived from a superseded
    estimate. The rejection carries `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/occ_retrofit_finalize_stale_project_version
    """
    site, inspection, finding = setup_inspection_with_finding(
        severity="CRITICAL", insurer_id="FM-1")
    project = create_retrofit_project(site["id"], finding["id"],
                                      scope_budget_cents=100000)
    add_line_item(site["id"], project["id"], cost_cents=100, risk_tier="LOW",
                  description="l1")

    stale_version = get_project_version(site["id"], project["id"])
    # This second line item bumps the project version past the captured one.
    add_line_item(site["id"], project["id"], cost_cents=100, risk_tier="LOW",
                  description="l2")

    res = api.finalize_estimate(site["id"], project["id"], stale_version,
                                ENGINEER)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)
    assert res.status_code == 412


def test_approve_rejected_for_non_critical_trigger(api):
    """PRD §3.8: "The `trigger_finding_id` must reference an InspectionFinding
    with severity `CRITICAL` whose current status is `OPEN`, `IN_PROGRESS`, or
    `RESOLVED`; any other status is rejected with
    `ERR_TRIGGER_FINDING_INVALID` (HTTP 422)."

    An OBSERVATION-severity trigger finding fails the severity requirement.

    Design: Difficulty/cross_entity_state_dependency/retrofit_approve_blocked_by_trigger_finding_state
    """
    site, inspection, finding = setup_inspection_with_finding(
        severity="OBSERVATION", insurer_id="FM-1")
    project = create_estimated_project(site["id"], finding["id"],
                                       scope_budget_cents=100000,
                                       line_items=((1000, "LOW"),))
    assert project["status"] == "ESTIMATED"

    res = api.approve_retrofit_project(site["id"], project["id"], MANAGER)
    validate_error(res, ApiErrorId.ERR_TRIGGER_FINDING_INVALID)

    after = validate_success(
        api.get_retrofit_project(site["id"], project["id"], ENGINEER), 200)
    assert after["status"] == "ESTIMATED"


def test_approve_rejected_for_verified_trigger(api):
    """PRD §3.8: "The `trigger_finding_id` must reference an InspectionFinding
    with severity `CRITICAL` whose current status is `OPEN`, `IN_PROGRESS`, or
    `RESOLVED`; any other status is rejected with
    `ERR_TRIGGER_FINDING_INVALID` (HTTP 422)."
    PRD §3.7: "A `ComplianceManager` verifies the resolution (`RESOLVED →
    VERIFIED`)".

    A CRITICAL trigger finding already in VERIFIED fails the status
    requirement.

    Design: Difficulty/cross_entity_state_dependency/retrofit_approve_blocked_by_trigger_finding_state
    """
    site, inspection, finding = setup_inspection_with_finding(
        severity="CRITICAL", insurer_id="FM-1")
    validate_success(api.finding_start_work(site["id"], inspection["id"],
                                            finding["id"], ENGINEER), 200)
    validate_success(api.finding_resolve(site["id"], inspection["id"],
                                         finding["id"], ENGINEER), 200)
    verified = validate_success(api.finding_verify(site["id"], inspection["id"],
                                                   finding["id"], MANAGER), 200)
    assert verified["status"] == "VERIFIED"

    project = create_estimated_project(site["id"], finding["id"],
                                       scope_budget_cents=100000,
                                       line_items=((1000, "LOW"),))
    res = api.approve_retrofit_project(site["id"], project["id"], MANAGER)
    validate_error(res, ApiErrorId.ERR_TRIGGER_FINDING_INVALID)

    after = validate_success(
        api.get_retrofit_project(site["id"], project["id"], ENGINEER), 200)
    assert after["status"] == "ESTIMATED"
