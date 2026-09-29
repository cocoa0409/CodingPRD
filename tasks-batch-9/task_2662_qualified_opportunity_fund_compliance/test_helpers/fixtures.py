"""
Composite state builders for the Qualified Opportunity Fund compliance API.

Every test starts against an empty database, so all preconditions are built by
calling the declared endpoints in order. These builders are plain functions, not
pytest fixtures, so a test can compose them freely and read back intermediate
responses.

Identity threading: an Investor's `X-User-ID` must be that Investor's own `id`,
so every builder that creates an investor returns the created row and derives
its headers with `make_investor_headers(investor["id"])`. A FundManager's
`X-User-ID` must equal the owning `Fund.manager_user_id`.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .test_users import (
    ADMIN_HEADERS,
    CERTIFIER_HEADERS,
    FUND_MANAGER_USER_ID,
    MANAGER_HEADERS,
    MEASURER_HEADERS,
    OTHER_FUND_MANAGER_USER_ID,
    make_fund_manager_headers,
    make_investor_headers,
)


# =========================================================================
# Logical clock
# =========================================================================


def set_clock(api: ApiClient, current_utc: str) -> Dict[str, Any]:
    """Move the logical clock; returns {current_utc, previous_utc}."""
    return get_success_data(
        api.set_clock(f.set_clock_payload(current_utc=current_utc), ADMIN_HEADERS)
    )


def read_clock(api: ApiClient, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Read the logical clock."""
    return get_success_data(api.get_clock(headers or ADMIN_HEADERS))


def run_deadline_sweep(api: ApiClient) -> Dict[str, Any]:
    """Run the deadline sweep; returns the three counts plus swept_at."""
    return get_success_data(api.run_deadline_sweep(None, ADMIN_HEADERS))


# =========================================================================
# Tier 1 — single-entity state progression
# =========================================================================


def make_investor(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Create an investor; attestation stays at its default PENDING."""
    return get_success_data(
        api.create_investor(f.create_investor_payload(**overrides), ADMIN_HEADERS)
    )


def attest_investor(
    api: ApiClient, investor_id: str, status: str = "ATTESTED"
) -> Dict[str, Any]:
    """Move an investor's attestation posture."""
    return get_success_data(
        api.patch_investor_attestation(
            investor_id,
            f.investor_attestation_payload(compliance_attestation_status=status),
            ADMIN_HEADERS,
        )
    )


def make_attested_investor(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Create an investor and move it to ATTESTED, which elections require."""
    investor = make_investor(api, **overrides)
    return attest_investor(api, investor["id"])


def make_fund(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Create a fund; it is born DRAFT / UNTESTED."""
    return get_success_data(
        api.create_fund(f.create_fund_payload(**overrides), ADMIN_HEADERS)
    )


def self_certify_fund(
    api: ApiClient,
    fund_id: str,
    manager_user_id: str = FUND_MANAGER_USER_ID,
    first_taxable_month_iso8601: str = "2026-01-01T00:00:00Z",
) -> Dict[str, Any]:
    """Self-certify a fund as its rightful manager."""
    return get_success_data(
        api.self_certify_fund(
            fund_id,
            f.self_certify_payload(
                first_taxable_month_iso8601=first_taxable_month_iso8601
            ),
            make_fund_manager_headers(manager_user_id),
        )
    )


def make_self_certified_fund(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Create a fund and move certification_status to SELF_CERTIFIED."""
    fund = make_fund(api, **overrides)
    manager = fund["manager_user_id"]
    return self_certify_fund(api, fund["id"], manager)


def decertify_fund(api: ApiClient, fund_id: str) -> Dict[str, Any]:
    """Decertify a fund as a ComplianceOfficer."""
    return get_success_data(
        api.decertify_fund(fund_id, f.decertify_payload(), CERTIFIER_HEADERS)
    )


def read_fund(api: ApiClient, fund_id: str) -> Dict[str, Any]:
    """Read a fund, including its current version for optimistic concurrency."""
    return get_success_data(api.get_fund(fund_id, ADMIN_HEADERS))


def fund_version(api: ApiClient, fund_id: str) -> int:
    """Read the fund's current version, for use as expected_fund_version."""
    return int(read_fund(api, fund_id)["version"])


def make_fund_asset(
    api: ApiClient,
    fund_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """
    Record an asset on a fund; the fund must already be self-certified.

    `headers` selects the acting identity. It defaults to the manager handle the
    default fund is created with; a fund owned by a different `manager_user_id`
    must pass that manager's headers, because PRD §2.11 rule 9 fences asset
    registration behind `ERR_FUND_MANAGER_MISMATCH`.
    """
    return get_success_data(
        api.create_fund_asset(
            f.create_fund_asset_payload(fund_id, **overrides),
            headers or MANAGER_HEADERS,
        )
    )


def read_fund_asset(api: ApiClient, asset_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_fund_asset(asset_id, ADMIN_HEADERS))


def make_qoz_business(api: ApiClient, fund_id: str, **overrides: Any) -> Dict[str, Any]:
    """Register an operating business under a self-certified fund."""
    return get_success_data(
        api.create_qoz_business(
            f.create_qoz_business_payload(fund_id, **overrides), MANAGER_HEADERS
        )
    )


def read_qoz_business(api: ApiClient, business_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_qoz_business(business_id, ADMIN_HEADERS))


# =========================================================================
# Tier 1 — asset test progression
# =========================================================================


def make_asset_test(api: ApiClient, fund_id: str, **overrides: Any) -> Dict[str, Any]:
    """Open an asset test in DRAFT over a half-open testing period."""
    return get_success_data(
        api.create_asset_test(
            fund_id, f.create_asset_test_payload(**overrides), MANAGER_HEADERS
        )
    )


def measure_asset_test(
    api: ApiClient, test_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Measure an asset test; the measurer handle is recorded on the row."""
    return get_success_data(
        api.measure_asset_test(test_id, None, headers or MANAGER_HEADERS)
    )


def certify_asset_test(
    api: ApiClient, test_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Certify a measured asset test as a ComplianceOfficer."""
    return get_success_data(
        api.certify_asset_test(test_id, None, headers or CERTIFIER_HEADERS)
    )


def make_measured_asset_test(
    api: ApiClient,
    fund_id: str,
    measure_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Open and measure an asset test in one step."""
    test = make_asset_test(api, fund_id, **overrides)
    return measure_asset_test(api, test["id"], measure_headers)


def make_certified_asset_test(
    api: ApiClient,
    fund_id: str,
    measure_headers: Optional[Dict[str, str]] = None,
    certify_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Open, measure and certify an asset test in one step."""
    test = make_measured_asset_test(
        api, fund_id, measure_headers=measure_headers, **overrides
    )
    return certify_asset_test(api, test["id"], certify_headers)


def read_asset_test(api: ApiClient, test_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_asset_test(test_id, ADMIN_HEADERS))


# =========================================================================
# Tier 1 — business test progression
# =========================================================================


def make_business_test(
    api: ApiClient, business_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Open a QOZB three-prong test in DRAFT."""
    return get_success_data(
        api.create_business_test(
            business_id, f.create_business_test_payload(**overrides), MANAGER_HEADERS
        )
    )


def measure_business_test(
    api: ApiClient,
    test_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Measure a QOZB test's three prongs."""
    return get_success_data(
        api.measure_business_test(
            test_id,
            f.measure_business_test_payload(**overrides),
            headers or MANAGER_HEADERS,
        )
    )


def certify_business_test(
    api: ApiClient, test_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Certify a measured QOZB test as a ComplianceOfficer."""
    return get_success_data(
        api.certify_business_test(test_id, None, headers or CERTIFIER_HEADERS)
    )


def make_measured_business_test(
    api: ApiClient,
    business_id: str,
    testing_date: str = "2026-06-30T00:00:00Z",
    measure_headers: Optional[Dict[str, str]] = None,
    **measure_overrides: Any,
) -> Dict[str, Any]:
    """Open and measure a QOZB test in one step."""
    test = make_business_test(api, business_id, testing_date=testing_date)
    return measure_business_test(
        api, test["id"], measure_headers, **measure_overrides
    )


def make_certified_business_test(
    api: ApiClient,
    business_id: str,
    testing_date: str = "2026-06-30T00:00:00Z",
    measure_headers: Optional[Dict[str, str]] = None,
    certify_headers: Optional[Dict[str, str]] = None,
    **measure_overrides: Any,
) -> Dict[str, Any]:
    """Open, measure and certify a QOZB test in one step."""
    test = make_measured_business_test(
        api,
        business_id,
        testing_date=testing_date,
        measure_headers=measure_headers,
        **measure_overrides,
    )
    return certify_business_test(api, test["id"], certify_headers)


def read_business_test(api: ApiClient, test_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_business_test(test_id, ADMIN_HEADERS))


# =========================================================================
# Tier 1 — improvement project progression
# =========================================================================


def make_improvement_project(
    api: ApiClient, fund_asset_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Open a 30-month substantial-improvement window on an asset."""
    return get_success_data(
        api.create_improvement_project(
            f.create_improvement_project_payload(fund_asset_id, **overrides),
            MANAGER_HEADERS,
        )
    )


def add_project_expenditure(
    api: ApiClient,
    project_id: str,
    expected_project_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """Log a capital expenditure against an improvement project."""
    return get_success_data(
        api.create_project_expenditure(
            project_id,
            f.create_project_expenditure_payload(
                expected_project_version, **overrides
            ),
            MANAGER_HEADERS,
        )
    )


def evaluate_improvement_project(api: ApiClient, project_id: str) -> Dict[str, Any]:
    """Decide the substantial-improvement outcome."""
    return get_success_data(
        api.evaluate_improvement_project(project_id, None, MANAGER_HEADERS)
    )


def read_improvement_project(api: ApiClient, project_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_improvement_project(project_id, ADMIN_HEADERS))


def project_version(api: ApiClient, project_id: str) -> int:
    """Read the project's current version, for expected_project_version."""
    return int(read_improvement_project(api, project_id)["version"])


# =========================================================================
# Tier 1 — working capital plan progression
# =========================================================================


def make_wcsh_plan(
    api: ApiClient, qoz_business_id: str, **overrides: Any
) -> Dict[str, Any]:
    """File a working-capital safe-harbor plan; it is born DRAFT."""
    return get_success_data(
        api.create_wcsh_plan(
            f.create_wcsh_plan_payload(qoz_business_id, **overrides), MANAGER_HEADERS
        )
    )


def activate_wcsh_plan(api: ApiClient, plan_id: str) -> Dict[str, Any]:
    """Activate a documented plan, which shelters its unspent dollars."""
    return get_success_data(api.activate_wcsh_plan(plan_id, None, MANAGER_HEADERS))


def make_active_wcsh_plan(
    api: ApiClient, qoz_business_id: str, **overrides: Any
) -> Dict[str, Any]:
    """File and activate a plan in one step."""
    plan = make_wcsh_plan(api, qoz_business_id, **overrides)
    return activate_wcsh_plan(api, plan["id"])


def add_wcsh_expenditure(api: ApiClient, plan_id: str, **overrides: Any) -> Dict[str, Any]:
    """Log a spend against an active plan."""
    return get_success_data(
        api.create_wcsh_expenditure(
            plan_id, f.create_wcsh_expenditure_payload(**overrides), MANAGER_HEADERS
        )
    )


def evaluate_wcsh_checkpoint(
    api: ApiClient, plan_id: str, checkpoint_month_index: int
) -> Dict[str, Any]:
    """Evaluate the plan's pacing at a schedule month index."""
    return get_success_data(
        api.evaluate_wcsh_checkpoint(
            plan_id,
            f.evaluate_checkpoint_payload(checkpoint_month_index=checkpoint_month_index),
            MANAGER_HEADERS,
        )
    )


def read_wcsh_plan(api: ApiClient, plan_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_wcsh_plan(plan_id, ADMIN_HEADERS))


# =========================================================================
# Tier 1 — gain and election progression
# =========================================================================


def make_eligible_gain(
    api: ApiClient,
    investor_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """
    Intake a realized gain for an investor. Defaults to the investor's own
    headers, which is what the Investor scope rule requires.
    """
    return get_success_data(
        api.create_eligible_gain(
            f.create_eligible_gain_payload(investor_id, **overrides),
            headers or make_investor_headers(investor_id),
        )
    )


def read_eligible_gain(
    api: ApiClient, gain_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(api.get_eligible_gain(gain_id, headers or ADMIN_HEADERS))


def make_deferral_election(
    api: ApiClient,
    investor_id: str,
    eligible_gain_id: str,
    fund_id: str,
    expected_fund_version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """
    Elect gain dollars into a self-certified fund. When expected_fund_version is
    omitted it is read from the fund immediately before the call.
    """
    version = (
        expected_fund_version
        if expected_fund_version is not None
        else fund_version(api, fund_id)
    )
    return get_success_data(
        api.create_deferral_election(
            f.create_deferral_election_payload(
                eligible_gain_id, fund_id, version, **overrides
            ),
            headers or make_investor_headers(investor_id),
        )
    )


def read_deferral_election(
    api: ApiClient, election_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.get_deferral_election(election_id, headers or ADMIN_HEADERS)
    )


def revoke_deferral_election(
    api: ApiClient,
    election_id: str,
    investor_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Revoke an election, returning its dollars to the gain's remainder."""
    headers = (
        make_investor_headers(investor_id) if investor_id else ADMIN_HEADERS
    )
    return get_success_data(
        api.revoke_deferral_election(
            election_id, f.revoke_election_payload(**overrides), headers
        )
    )


def make_inclusion_event(
    api: ApiClient,
    election_id: str,
    investor_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Record an inclusion event against an election."""
    headers = (
        make_investor_headers(investor_id) if investor_id else ADMIN_HEADERS
    )
    return get_success_data(
        api.create_inclusion_event(
            election_id, f.create_inclusion_event_payload(**overrides), headers
        )
    )


def make_step_up_election(
    api: ApiClient,
    election_id: str,
    investor_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """File the ten-year-hold basis step-up election."""
    headers = (
        make_investor_headers(investor_id) if investor_id else ADMIN_HEADERS
    )
    return get_success_data(
        api.create_step_up_election(
            election_id, f.create_step_up_election_payload(**overrides), headers
        )
    )


def read_investor_statement(
    api: ApiClient, investor_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Read the computed investor statement."""
    return get_success_data(
        api.get_investor_statement(investor_id, headers or ADMIN_HEADERS)
    )


# =========================================================================
# Tier 2 — entity hierarchy shortcuts
# =========================================================================


def make_certified_fund_with_manager(
    api: ApiClient,
    manager_user_id: str = FUND_MANAGER_USER_ID,
    **overrides: Any,
) -> Dict[str, Any]:
    """A self-certified fund owned by a named manager handle."""
    return make_self_certified_fund(
        api, manager_user_id=manager_user_id, **overrides
    )


def make_fund_with_qualified_asset(
    api: ApiClient,
    unadjusted_cost_basis: float = 600000.00,
    afs_fair_value: float = 700000.00,
    **fund_overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    A self-certified fund holding one original-use QOZ business property asset,
    which is born QUALIFIED. Returns (fund_after_creation, asset).
    """
    fund = make_self_certified_fund(api, **fund_overrides)
    asset = make_fund_asset(
        api,
        fund["id"],
        unadjusted_cost_basis=unadjusted_cost_basis,
        afs_fair_value=afs_fair_value,
    )
    return read_fund(api, fund["id"]), asset


def make_fund_with_business(
    api: ApiClient, **business_overrides: Any
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A self-certified fund plus one registered operating business."""
    fund = make_self_certified_fund(api)
    business = make_qoz_business(api, fund["id"], **business_overrides)
    return fund, business


def make_qualified_business_with_equity_asset(
    api: ApiClient,
    equity_basis: float = 450000.00,
    equity_afs: float = 450000.00,
) -> Dict[str, Any]:
    """
    Drive a business to QUALIFIED through a passing three-prong test, then link
    a QOZB_EQUITY asset to it so the asset inherits the qualification.
    Returns a context dict of the rows involved.
    """
    fund, business = make_fund_with_business(api)
    certified = make_certified_business_test(
        api,
        business["id"],
        measure_headers=MEASURER_HEADERS,
        certify_headers=CERTIFIER_HEADERS,
    )
    equity = make_fund_asset(
        api,
        fund["id"],
        asset_class="QOZB_EQUITY",
        qoz_business_id=business["id"],
        unadjusted_cost_basis=equity_basis,
        afs_fair_value=equity_afs,
        original_use_in_zone=False,
    )
    return {
        "fund": read_fund(api, fund["id"]),
        "business": read_qoz_business(api, business["id"]),
        "business_test": certified,
        "equity_asset": equity,
    }


# =========================================================================
# Tier 3 — full-lifecycle shortcuts
# =========================================================================


def make_deferred_election_context(
    api: ApiClient,
    eligible_amount: float = 100000.00,
    elected_amount: float = 100000.00,
    realization_date: str = "2026-07-01T00:00:00Z",
    **gain_overrides: Any,
) -> Dict[str, Any]:
    """
    The shortest path to a DEFERRED election: an ATTESTED investor, a
    SELF_CERTIFIED fund, one eligible gain, and one election over it.

    Returns a context dict carrying the investor, the investor's headers, the
    fund as read after the election, the gain and the election.
    """
    investor = make_attested_investor(api)
    investor_headers = make_investor_headers(investor["id"])
    fund = make_self_certified_fund(api)
    gain = make_eligible_gain(
        api,
        investor["id"],
        headers=investor_headers,
        eligible_amount=eligible_amount,
        realization_date=realization_date,
        **gain_overrides,
    )
    election = make_deferral_election(
        api,
        investor["id"],
        gain["id"],
        fund["id"],
        headers=investor_headers,
        elected_amount=elected_amount,
    )
    return {
        "investor": investor,
        "investor_headers": investor_headers,
        "fund": read_fund(api, fund["id"]),
        "gain": read_eligible_gain(api, gain["id"], investor_headers),
        "election": election,
    }


def make_election_with_holding_period(
    api: ApiClient,
    clock_at_election: str = "2026-08-01T00:00:00Z",
    clock_after: str = "2036-08-01T00:00:00Z",
    eligible_amount: float = 400000.00,
    elected_amount: float = 400000.00,
) -> Dict[str, Any]:
    """
    A DEFERRED election whose investment_date sits at `clock_at_election`, with
    the clock then advanced to `clock_after` so a holding period has elapsed.
    """
    set_clock(api, clock_at_election)
    context = make_deferred_election_context(
        api,
        eligible_amount=eligible_amount,
        elected_amount=elected_amount,
    )
    set_clock(api, clock_after)
    return context


def make_improving_asset_context(
    api: ApiClient,
    unadjusted_cost_basis: float = 500000.00,
    afs_fair_value: float = 500000.00,
    window_start: str = "2026-08-01T00:00:00Z",
    **project_overrides: Any,
) -> Dict[str, Any]:
    """
    A self-certified fund holding a non-original-use asset with an OPEN
    30-month improvement window over it, so the asset is IMPROVING.
    """
    fund = make_self_certified_fund(api)
    asset = make_fund_asset(
        api,
        fund["id"],
        unadjusted_cost_basis=unadjusted_cost_basis,
        afs_fair_value=afs_fair_value,
        original_use_in_zone=False,
    )
    project = make_improvement_project(
        api, asset["id"], window_start=window_start, **project_overrides
    )
    return {
        "fund": read_fund(api, fund["id"]),
        "asset": read_fund_asset(api, asset["id"]),
        "project": project,
    }


def make_active_plan_context(
    api: ApiClient,
    covered_amount: float = 300000.00,
    schedule_month_count: int = 3,
    spend_schedule: Optional[List[Dict[str, Any]]] = None,
    window_start: str = "2026-01-01T00:00:00Z",
    **business_overrides: Any,
) -> Dict[str, Any]:
    """
    A self-certified fund, one operating business, and one ACTIVE
    working-capital plan sheltering its unspent dollars.
    """
    fund, business = make_fund_with_business(api, **business_overrides)
    plan = make_active_wcsh_plan(
        api,
        business["id"],
        window_start=window_start,
        covered_amount=covered_amount,
        schedule_month_count=schedule_month_count,
        spend_schedule=(
            spend_schedule
            if spend_schedule is not None
            else f.spend_schedule(
                *[covered_amount / schedule_month_count] * schedule_month_count
            )
        ),
    )
    return {
        "fund": fund,
        "business": read_qoz_business(api, business["id"]),
        "plan": plan,
    }


# =========================================================================
# Tier 4 — accumulation and threshold targeting
# =========================================================================


def make_fund_below_asset_threshold(
    api: ApiClient,
    qualified_basis: float = 800000.00,
    nonqualified_basis: float = 200000.00,
) -> Dict[str, Any]:
    """
    A self-certified fund whose qualified share sits deliberately below the
    90-percent bar: one original-use QOZ business property asset plus one CASH
    asset, which is always NONQUALIFIED.
    """
    fund = make_self_certified_fund(api)
    qualified_asset = make_fund_asset(
        api,
        fund["id"],
        unadjusted_cost_basis=qualified_basis,
        afs_fair_value=qualified_basis,
    )
    cash_asset = make_fund_asset(
        api,
        fund["id"],
        asset_class="CASH",
        unadjusted_cost_basis=nonqualified_basis,
        afs_fair_value=nonqualified_basis,
        original_use_in_zone=False,
    )
    return {
        "fund": read_fund(api, fund["id"]),
        "qualified_asset": qualified_asset,
        "cash_asset": cash_asset,
    }


def list_fund_penalty_assessments(
    api: ApiClient, fund_id: str
) -> List[Dict[str, Any]]:
    """
    List a fund's penalty assessments. This is the only discovery channel for
    assessments the certify cascade creates.
    """
    response = api.list_penalty_assessments(
        ADMIN_HEADERS, {"fund_id": fund_id, "limit": 100}
    )
    return get_success_data(response)


def read_penalty_assessment(api: ApiClient, assessment_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_penalty_assessment(assessment_id, ADMIN_HEADERS))


def make_penalty_assessment_context(
    api: ApiClient,
    qualified_basis: float = 800000.00,
    nonqualified_basis: float = 200000.00,
    measurement_date: str = "2026-12-31T00:00:00Z",
    period_start: str = "2026-07-01T00:00:00Z",
    period_end: str = "2027-01-01T00:00:00Z",
) -> Dict[str, Any]:
    """
    Drive a fund through a certified asset-test failure so the cascade creates a
    PenaltyAssessment, then hand back every row involved.
    """
    context = make_fund_below_asset_threshold(
        api,
        qualified_basis=qualified_basis,
        nonqualified_basis=nonqualified_basis,
    )
    fund_id = context["fund"]["id"]
    test = make_certified_asset_test(
        api,
        fund_id,
        measure_headers=MEASURER_HEADERS,
        certify_headers=CERTIFIER_HEADERS,
        measurement_date=measurement_date,
        period_start=period_start,
        period_end=period_end,
    )
    assessments = list_fund_penalty_assessments(api, fund_id)
    context["asset_test"] = test
    context["fund"] = read_fund(api, fund_id)
    context["assessments"] = assessments
    context["assessment"] = assessments[0] if assessments else None
    return context


def request_cure(
    api: ApiClient,
    assessment_id: str,
    cure_basis: str = "REASONABLE_CAUSE",
    narrative_reference: str = "CURE-2662-A",
) -> Dict[str, Any]:
    """File a cure request against an assessed penalty."""
    return get_success_data(
        api.create_cure_request(
            assessment_id,
            f.cure_request_payload(
                cure_basis=cure_basis, narrative_reference=narrative_reference
            ),
            MANAGER_HEADERS,
        )
    )


def decide_cure(
    api: ApiClient, assessment_id: str, decision: str = "APPROVE"
) -> Dict[str, Any]:
    """Decide a pending cure request as a ComplianceOfficer."""
    return get_success_data(
        api.create_cure_decision(
            assessment_id,
            f.cure_decision_payload(decision=decision),
            CERTIFIER_HEADERS,
        )
    )


def make_cure_requested_context(
    api: ApiClient,
    cure_basis: str = "REASONABLE_CAUSE",
    narrative_reference: str = "CURE-2662-A",
    **penalty_overrides: Any,
) -> Dict[str, Any]:
    """A penalty assessment already moved to CURE_REQUESTED."""
    context = make_penalty_assessment_context(api, **penalty_overrides)
    context["assessment"] = request_cure(
        api,
        context["assessment"]["id"],
        cure_basis=cure_basis,
        narrative_reference=narrative_reference,
    )
    context["fund"] = read_fund(api, context["fund"]["id"])
    return context


# =========================================================================
# Tier 5 — finalization and terminal states
# =========================================================================


def dispose_asset(
    api: ApiClient,
    asset_id: str,
    proceeds_amount: float = 800000.00,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Dispose an asset, moving it to the terminal DISPOSED state."""
    return get_success_data(
        api.dispose_fund_asset(
            asset_id,
            f.dispose_fund_asset_payload(proceeds_amount=proceeds_amount),
            headers or MANAGER_HEADERS,
        )
    )


def make_disposed_asset_context(
    api: ApiClient, proceeds_amount: float = 800000.00
) -> Dict[str, Any]:
    """A fund whose single asset has already been disposed."""
    fund, asset = make_fund_with_qualified_asset(api)
    disposed = dispose_asset(api, asset["id"], proceeds_amount=proceeds_amount)
    return {
        "fund": read_fund(api, fund["id"]),
        "asset": disposed,
    }


def make_revoked_election_context(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """A DEFERRED election already moved to the terminal REVOKED state."""
    context = make_deferred_election_context(api, **overrides)
    context["election"] = revoke_deferral_election(
        api, context["election"]["id"], context["investor"]["id"]
    )
    context["gain"] = read_eligible_gain(
        api, context["gain"]["id"], context["investor_headers"]
    )
    context["fund"] = read_fund(api, context["fund"]["id"])
    return context


def make_fully_included_election_context(
    api: ApiClient, **overrides: Any
) -> Dict[str, Any]:
    """An election driven to INCLUDED_FULL by a single whole-fraction event."""
    context = make_deferred_election_context(api, **overrides)
    context["inclusion_event"] = make_inclusion_event(
        api,
        context["election"]["id"],
        context["investor"]["id"],
        included_fraction=1.0000,
    )
    context["election"] = read_deferral_election(
        api, context["election"]["id"], context["investor_headers"]
    )
    return context


def make_decertified_fund_context(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """
    A fund driven to DECERTIFIED / FAILED_FINAL while one election was still
    outstanding, so the decertification cascade has fired.
    """
    context = make_deferred_election_context(api, **overrides)
    context["fund"] = decertify_fund(api, context["fund"]["id"])
    context["election"] = read_deferral_election(
        api, context["election"]["id"], context["investor_headers"]
    )
    return context


def make_terminal_asset_test_context(
    api: ApiClient, **overrides: Any
) -> Dict[str, Any]:
    """A fund with one asset test already certified, i.e. in a terminal state."""
    fund, asset = make_fund_with_qualified_asset(api)
    test = make_certified_asset_test(
        api,
        fund["id"],
        measure_headers=MEASURER_HEADERS,
        certify_headers=CERTIFIER_HEADERS,
        **overrides,
    )
    return {
        "fund": read_fund(api, fund["id"]),
        "asset": asset,
        "asset_test": test,
    }


# =========================================================================
# Listing helpers
# =========================================================================


def list_fund_assets(api: ApiClient, fund_id: str, **params: Any) -> List[Dict[str, Any]]:
    query = {"fund_id": fund_id, "limit": 100}
    query.update(params)
    return get_success_data(api.list_fund_assets(ADMIN_HEADERS, query))


def list_fund_asset_tests(
    api: ApiClient, fund_id: str, **params: Any
) -> List[Dict[str, Any]]:
    query = {"limit": 100}
    query.update(params)
    return get_success_data(api.list_fund_asset_tests(fund_id, ADMIN_HEADERS, query))


def list_gain_elections(
    api: ApiClient,
    gain_id: str,
    headers: Optional[Dict[str, str]] = None,
    **params: Any,
) -> List[Dict[str, Any]]:
    query = {"limit": 100}
    query.update(params)
    return get_success_data(
        api.list_gain_deferral_elections(gain_id, headers or ADMIN_HEADERS, query)
    )


def list_election_inclusion_events(
    api: ApiClient,
    election_id: str,
    headers: Optional[Dict[str, str]] = None,
    **params: Any,
) -> List[Dict[str, Any]]:
    query = {"limit": 100}
    query.update(params)
    return get_success_data(
        api.list_inclusion_events(election_id, headers or ADMIN_HEADERS, query)
    )


def list_project_expenditures(
    api: ApiClient, project_id: str, **params: Any
) -> List[Dict[str, Any]]:
    query = {"limit": 100}
    query.update(params)
    return get_success_data(
        api.list_project_expenditures(project_id, ADMIN_HEADERS, query)
    )


def list_plan_expenditures(
    api: ApiClient, plan_id: str, **params: Any
) -> List[Dict[str, Any]]:
    query = {"limit": 100}
    query.update(params)
    return get_success_data(api.list_wcsh_expenditures(plan_id, ADMIN_HEADERS, query))


def list_business_tests(
    api: ApiClient, business_id: str, **params: Any
) -> List[Dict[str, Any]]:
    query = {"limit": 100}
    query.update(params)
    return get_success_data(api.list_business_tests(business_id, ADMIN_HEADERS, query))
