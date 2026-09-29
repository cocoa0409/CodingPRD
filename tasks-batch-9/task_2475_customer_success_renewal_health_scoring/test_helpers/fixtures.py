"""Composite setup helpers for the customer-success API.

The harness restarts the API before every individual test, so each test opens
against an empty database and nothing here may assume shared state. Fixtures are
function-scoped by construction.

The file is layered:

1. single-call step helpers, each one write against one endpoint;
2. read helpers, including "find this row in a listing" for the entities PRD §4
   exposes only through their collection endpoints;
3. named specifications — the account, manager and signal shapes that recur
   across scenarios, kept in one place so the arithmetic in the tests always
   refers to the same inputs;
4. scenario builders, which chain the steps and return a mutable ``state`` dict
   of handles and observed versions;
5. pytest fixtures wrapping the builders.
"""

from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import get_success_data

from . import factories as build
from .api_client import ApiClient
from .constants import (
    CASE_ACTION_COMMIT,
    CODE_KICKOFF,
    COMMITMENT_ACTION_ACCEPT,
    COMMITMENT_ACTION_DELIVER,
    DEFAULT_CLOCK_UTC,
    ENROLLMENT_ACTION_ACTIVATE,
    ENROLLMENT_ACTION_APPROVE,
    OPPORTUNITY_ACTION_HANDOFF,
    OUTCOME_HELD,
    PLAY_ACTION_ACTIVATE,
    PROGRAM_REFERENCE,
    SEGMENT_ENTERPRISE,
    SEGMENT_SMB,
    SENIORITY_CXO,
    SEVERITY_HIGH,
    TIER_DIGITAL,
    TIER_HIGH_TOUCH,
)
from .test_users import (
    ADVOCACY_HEADERS,
    EXECUTIVE_HEADERS,
    FINANCE_HEADERS,
    OPS_ADMIN_HEADERS,
    SALES_AE_USER_ID,
    make_csm_headers,
    make_executive_headers,
)

State = Dict[str, Any]


# ===========================================================================
# 1. Single-call step helpers
# ===========================================================================


def set_clock(api: ApiClient, current_utc: str) -> Dict[str, Any]:
    """Move the logical clock of PRD §2.5."""
    return get_success_data(api.set_clock(current_utc, OPS_ADMIN_HEADERS))


def run_sweep(api: ApiClient) -> Dict[str, Any]:
    """Run the nightly sweep of PRD §3.9 and return its counter block."""
    return get_success_data(api.run_daily_sweep(OPS_ADMIN_HEADERS))


def create_csm(
    api: ApiClient,
    full_name: str = "Ada Lovelace",
    coverage_specialty: str = TIER_HIGH_TOUCH,
    capacity_units_total: int = 40,
) -> Dict[str, Any]:
    """Register a manager on the roster."""
    return get_success_data(
        api.create_csm(
            build.csm(
                full_name=full_name,
                coverage_specialty=coverage_specialty,
                capacity_units_total=capacity_units_total,
            ),
            OPS_ADMIN_HEADERS,
        )
    )


def create_account(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register an account."""
    return get_success_data(
        api.create_account(build.account(**overrides), OPS_ADMIN_HEADERS)
    )


def add_usage_signal(
    api: ApiClient,
    account_id: str,
    csm_id: str,
    period_end_date: str,
    weekly_active_users: int,
    licensed_seats: int,
    feature_depth_pct: float,
) -> Dict[str, Any]:
    """Record one USAGE_PERIOD signal."""
    return get_success_data(
        api.create_signal(
            account_id,
            build.usage_signal(
                period_end_date, weekly_active_users, licensed_seats, feature_depth_pct
            ),
            make_csm_headers(csm_id),
        )
    )


def add_support_signal(
    api: ApiClient,
    account_id: str,
    csm_id: str,
    opened_at: str,
    ticket_severity: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Record one SUPPORT_TICKET signal."""
    return get_success_data(
        api.create_signal(
            account_id,
            build.support_signal(opened_at, ticket_severity, **overrides),
            make_csm_headers(csm_id),
        )
    )


def add_sponsor(
    api: ApiClient,
    account_id: str,
    csm_id: str,
    full_name: str = "Dana Reed",
    seniority: str = SENIORITY_CXO,
    is_economic_buyer: bool = True,
) -> Dict[str, Any]:
    """Register a sponsor contact on the account."""
    return get_success_data(
        api.create_sponsor_contact(
            account_id,
            build.sponsor_contact(
                full_name=full_name,
                seniority=seniority,
                is_economic_buyer=is_economic_buyer,
            ),
            make_csm_headers(csm_id),
        )
    )


def schedule_engagement(
    api: ApiClient,
    account_id: str,
    csm_id: str,
    sponsor_id: str,
    start_at: str,
    end_at: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Schedule an executive engagement against a sponsor of the same account."""
    return get_success_data(
        api.create_executive_engagement(
            account_id,
            build.executive_engagement(sponsor_id, start_at, end_at, **overrides),
            make_csm_headers(csm_id),
        )
    )


def record_outcome(
    api: ApiClient, engagement_id: str, csm_id: str, outcome: str = OUTCOME_HELD
) -> Dict[str, Any]:
    """Close an engagement with an outcome."""
    return get_success_data(
        api.record_engagement_outcome(
            engagement_id, build.engagement_outcome(outcome), make_csm_headers(csm_id)
        )
    )


def add_outcome_goal(
    api: ApiClient,
    account_id: str,
    csm_id: str,
    weight_bp: int,
    target_value: float,
    **overrides: Any,
) -> Dict[str, Any]:
    """Define a weighted outcome goal."""
    return get_success_data(
        api.create_outcome_goal(
            account_id,
            build.outcome_goal(weight_bp, target_value, **overrides),
            make_csm_headers(csm_id),
        )
    )


def record_goal_progress(
    api: ApiClient, goal_id: str, csm_id: str, status: str, **overrides: Any
) -> Dict[str, Any]:
    """Record progress against a goal."""
    return get_success_data(
        api.record_goal_progress(
            goal_id, build.goal_progress(status, **overrides), make_csm_headers(csm_id)
        )
    )


def add_milestone(
    api: ApiClient,
    account_id: str,
    csm_id: str,
    sequence_index: int,
    due_date: str,
    milestone_code: str = CODE_KICKOFF,
) -> Dict[str, Any]:
    """Add an onboarding milestone."""
    return get_success_data(
        api.create_milestone(
            account_id,
            build.milestone(sequence_index, due_date, milestone_code),
            make_csm_headers(csm_id),
        )
    )


def transition_milestone(
    api: ApiClient, milestone_id: str, csm_id: str, action: str, **overrides: Any
) -> Dict[str, Any]:
    """Complete or waive a milestone."""
    return get_success_data(
        api.transition_milestone(
            milestone_id,
            build.milestone_transition(action, **overrides),
            make_csm_headers(csm_id),
        )
    )


def segment_account(api: ApiClient, account_id: str) -> Dict[str, Any]:
    """Re-derive the account's coverage tier and return the updated account."""
    return get_success_data(api.segment_account(account_id, OPS_ADMIN_HEADERS))


def recompute_health(api: ApiClient, account_id: str) -> Dict[str, Any]:
    """Recompute every health figure and return the updated account."""
    return get_success_data(api.health_recompute(account_id, OPS_ADMIN_HEADERS))


def assign_coverage(
    api: ApiClient, account_id: str, expected_account_version: int, **overrides: Any
) -> Dict[str, Any]:
    """Staff an account, quoting the account version PRD §2.7 requires."""
    return get_success_data(
        api.create_coverage_assignment(
            build.coverage_assignment(
                account_id, expected_account_version, **overrides
            ),
            OPS_ADMIN_HEADERS,
        )
    )


def release_coverage(
    api: ApiClient, assignment_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Release a committed assignment."""
    return get_success_data(
        api.release_coverage_assignment(
            assignment_id, OPS_ADMIN_HEADERS, build.release(**overrides)
        )
    )


def draft_save_play(
    api: ApiClient,
    account_id: str,
    csm_id: str,
    window_start_date: str,
    window_end_date: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Draft a save play over a closed calendar window."""
    return get_success_data(
        api.create_save_play(
            build.save_play(
                account_id, csm_id, window_start_date, window_end_date, **overrides
            ),
            make_csm_headers(csm_id),
        )
    )


def transition_save_play(
    api: ApiClient, play_id: str, csm_id: str, action: str, **overrides: Any
) -> Dict[str, Any]:
    """Activate, succeed, fail or abandon a save play."""
    return get_success_data(
        api.transition_save_play(
            play_id,
            build.save_play_transition(action, **overrides),
            make_csm_headers(csm_id),
        )
    )


def raise_escalation(
    api: ApiClient,
    account_id: str,
    save_play_id: str,
    severity: str = SEVERITY_HIGH,
    **overrides: Any,
) -> Dict[str, Any]:
    """Raise an escalation case against a save play of the same account."""
    return get_success_data(
        api.create_escalation_case(
            build.escalation_case(account_id, save_play_id, severity, **overrides),
            EXECUTIVE_HEADERS,
        )
    )


def transition_escalation(
    api: ApiClient,
    case_id: str,
    action: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Commit, resolve or withdraw an escalation case."""
    return get_success_data(
        api.transition_escalation_case(
            case_id,
            build.escalation_transition(action, **overrides),
            headers if headers is not None else EXECUTIVE_HEADERS,
        )
    )


def propose_commitment(
    api: ApiClient,
    case_id: str,
    credit_cents: int,
    due_date: str,
    expected_escalation_case_version: int,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Propose a remediation commitment, quoting the case version of PRD §2.7."""
    return get_success_data(
        api.create_remediation_commitment(
            case_id,
            build.remediation_commitment(
                credit_cents, due_date, expected_escalation_case_version, **overrides
            ),
            headers if headers is not None else EXECUTIVE_HEADERS,
        )
    )


def transition_commitment(
    api: ApiClient,
    commitment_id: str,
    action: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Accept, reject or deliver a remediation commitment."""
    return get_success_data(
        api.transition_remediation_commitment(
            commitment_id,
            build.commitment_transition(action, **overrides),
            headers if headers is not None else EXECUTIVE_HEADERS,
        )
    )


def open_forecast(
    api: ApiClient, account_id: str, csm_id: str, fiscal_period: str = "2026Q3", **overrides: Any
) -> Dict[str, Any]:
    """Open a renewal forecast for one fiscal quarter."""
    return get_success_data(
        api.create_renewal_forecast(
            build.renewal_forecast(account_id, fiscal_period, **overrides),
            make_csm_headers(csm_id),
        )
    )


def submit_forecast(
    api: ApiClient, forecast_id: str, csm_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Submit the CS number, or take the revision edge."""
    return get_success_data(
        api.submit_renewal_forecast(
            forecast_id, make_csm_headers(csm_id), build.forecast_submit(**overrides)
        )
    )


def reconcile_forecast(
    api: ApiClient,
    forecast_id: str,
    action: str,
    finance_amount_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Reconcile or lock a forecast as finance."""
    return get_success_data(
        api.reconcile_renewal_forecast(
            forecast_id,
            build.forecast_reconcile(action, finance_amount_cents, **overrides),
            FINANCE_HEADERS,
        )
    )


def identify_opportunity(
    api: ApiClient, account_id: str, csm_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Identify an expansion opportunity."""
    return get_success_data(
        api.create_expansion_opportunity(
            build.expansion_opportunity(account_id, **overrides),
            make_csm_headers(csm_id),
        )
    )


def transition_opportunity(
    api: ApiClient,
    opportunity_id: str,
    action: str,
    headers: Dict[str, str],
    **overrides: Any,
) -> Dict[str, Any]:
    """Hand off, accept, reject or recycle an opportunity."""
    return get_success_data(
        api.transition_expansion_opportunity(
            opportunity_id, build.opportunity_transition(action, **overrides), headers
        )
    )


def nominate_enrollment(
    api: ApiClient, account_id: str, program_type: str = PROGRAM_REFERENCE, **overrides: Any
) -> Dict[str, Any]:
    """Nominate an account into an advocacy programme."""
    return get_success_data(
        api.create_advocacy_enrollment(
            account_id,
            build.advocacy_enrollment(program_type, **overrides),
            ADVOCACY_HEADERS,
        )
    )


def transition_enrollment(
    api: ApiClient, enrollment_id: str, action: str, **overrides: Any
) -> Dict[str, Any]:
    """Drive an advocacy enrollment action."""
    return get_success_data(
        api.transition_advocacy_enrollment(
            enrollment_id, build.enrollment_transition(action, **overrides), ADVOCACY_HEADERS
        )
    )


def drive_lifecycle(
    api: ApiClient, account_id: str, action: str, **overrides: Any
) -> Dict[str, Any]:
    """Drive an account lifecycle action."""
    return get_success_data(
        api.account_lifecycle(
            account_id, build.lifecycle_action(action, **overrides), OPS_ADMIN_HEADERS
        )
    )


# ===========================================================================
# 2. Read helpers
# ===========================================================================


def read_account(api: ApiClient, account_id: str) -> Dict[str, Any]:
    """GET the account as CS operations."""
    return get_success_data(api.get_account(account_id, OPS_ADMIN_HEADERS))


def read_csm(api: ApiClient, csm_id: str) -> Dict[str, Any]:
    """GET the manager row as CS operations."""
    return get_success_data(api.get_csm(csm_id, OPS_ADMIN_HEADERS))


def read_assignment(api: ApiClient, assignment_id: str) -> Dict[str, Any]:
    """GET a coverage assignment as CS operations."""
    return get_success_data(
        api.get_coverage_assignment(assignment_id, OPS_ADMIN_HEADERS)
    )


def read_save_play(api: ApiClient, play_id: str) -> Dict[str, Any]:
    """GET a save play as CS operations."""
    return get_success_data(api.get_save_play(play_id, OPS_ADMIN_HEADERS))


def read_case(api: ApiClient, case_id: str) -> Dict[str, Any]:
    """GET an escalation case as CS operations."""
    return get_success_data(api.get_escalation_case(case_id, OPS_ADMIN_HEADERS))


def read_forecast(api: ApiClient, forecast_id: str) -> Dict[str, Any]:
    """GET a renewal forecast as CS operations."""
    return get_success_data(api.get_renewal_forecast(forecast_id, OPS_ADMIN_HEADERS))


def read_opportunity(api: ApiClient, opportunity_id: str) -> Dict[str, Any]:
    """GET an expansion opportunity as CS operations."""
    return get_success_data(
        api.get_expansion_opportunity(opportunity_id, OPS_ADMIN_HEADERS)
    )


def read_sponsor(api: ApiClient, sponsor_id: str) -> Dict[str, Any]:
    """GET a sponsor contact as CS operations."""
    return get_success_data(api.get_sponsor_contact(sponsor_id, OPS_ADMIN_HEADERS))


def read_health_summary(api: ApiClient, account_id: str) -> Dict[str, Any]:
    """GET the read-only health projection of PRD §3.2."""
    return get_success_data(api.get_health_summary(account_id, OPS_ADMIN_HEADERS))


def list_rows(response: Any) -> List[Dict[str, Any]]:
    """Return the rows of a successful listing response."""
    return get_success_data(response)


def _find(rows: List[Dict[str, Any]], row_id: str) -> Dict[str, Any]:
    for row in rows:
        if row.get("id") == row_id:
            return row
    raise AssertionError(f"row {row_id} is absent from the listing")


def read_milestone(api: ApiClient, account_id: str, milestone_id: str) -> Dict[str, Any]:
    """Find a milestone in its account listing; PRD §4 has no single-row read."""
    rows = list_rows(api.list_milestones(account_id, OPS_ADMIN_HEADERS, {"limit": 100}))
    return _find(rows, milestone_id)


def read_goal(api: ApiClient, account_id: str, goal_id: str) -> Dict[str, Any]:
    """Find an outcome goal in its account listing."""
    rows = list_rows(
        api.list_outcome_goals(account_id, OPS_ADMIN_HEADERS, {"limit": 100})
    )
    return _find(rows, goal_id)


def read_signal(api: ApiClient, account_id: str, signal_id: str) -> Dict[str, Any]:
    """Find a signal in its account listing."""
    rows = list_rows(api.list_signals(account_id, OPS_ADMIN_HEADERS, {"limit": 100}))
    return _find(rows, signal_id)


def read_engagement(
    api: ApiClient, account_id: str, engagement_id: str
) -> Dict[str, Any]:
    """Find an executive engagement in its account listing."""
    rows = list_rows(
        api.list_account_engagements(account_id, OPS_ADMIN_HEADERS, {"limit": 100})
    )
    return _find(rows, engagement_id)


def read_commitment(api: ApiClient, case_id: str, commitment_id: str) -> Dict[str, Any]:
    """Find a remediation commitment in its case listing."""
    rows = list_rows(
        api.list_remediation_commitments(case_id, OPS_ADMIN_HEADERS, {"limit": 100})
    )
    return _find(rows, commitment_id)


def read_enrollment(
    api: ApiClient, account_id: str, enrollment_id: str
) -> Dict[str, Any]:
    """Find an advocacy enrollment in its account listing."""
    rows = list_rows(
        api.list_advocacy_enrollments(account_id, ADVOCACY_HEADERS, {"limit": 100})
    )
    return _find(rows, enrollment_id)


# ===========================================================================
# 3. Named specifications
# ===========================================================================

# The recurring ENTERPRISE account: 30,000,000 cents of revenue on a full-year
# 2026 term, the same inputs every worked example in the PRD uses.
NORTHWIND = {
    "name": "Northwind Traders",
    "arr_cents": 30_000_000,
    "segment_band": SEGMENT_ENTERPRISE,
    "contract_start_date": "2026-01-01",
    "contract_end_date": "2026-12-31",
}

# A small DIGITAL-bound account: SMB band at 100,000 cents.
CORNERSHOP = {
    "name": "Corner Shop Supplies",
    "arr_cents": 100_000,
    "segment_band": SEGMENT_SMB,
    "contract_start_date": "2026-01-01",
    "contract_end_date": "2026-12-31",
}

# Three usage periods whose `usage_row_index` values are 36.00, 56.00 and 86.00:
# the newest row alone gives an adoption term of 86.00, while the recency
# weighted mean of all three gives 67.00.
RISING_USAGE_ROWS = (
    {
        "period_end_date": "2026-05-31",
        "weekly_active_users": 40,
        "licensed_seats": 100,
        "feature_depth_pct": 30.00,
    },
    {
        "period_end_date": "2026-06-30",
        "weekly_active_users": 60,
        "licensed_seats": 100,
        "feature_depth_pct": 50.00,
    },
    {
        "period_end_date": "2026-07-31",
        "weekly_active_users": 90,
        "licensed_seats": 100,
        "feature_depth_pct": 80.00,
    },
)

# The newest of the rising rows on its own: `usage_row_index` 86.00.
NEWEST_USAGE_ROW = RISING_USAGE_ROWS[2]


# ===========================================================================
# 4. Scenario builders
# ===========================================================================


def build_roster_and_account(
    api: ApiClient,
    capacity_units_total: int = 40,
    coverage_specialty: str = TIER_HIGH_TOUCH,
    account_spec: Optional[Dict[str, Any]] = None,
) -> State:
    """One manager and one freshly registered account, no signals.

    The account rests on the PRD §3.1 baseline: both health scores 43.75, tier
    RED, likelihood AT_RISK, tier UNASSIGNED and posture RESTRICTED.
    """
    csm = create_csm(
        api, coverage_specialty=coverage_specialty, capacity_units_total=capacity_units_total
    )
    account = create_account(api, **(account_spec or NORTHWIND))
    return {
        "csm": csm,
        "csm_id": csm["id"],
        "csm_headers": make_csm_headers(csm["id"]),
        "account": account,
        "account_id": account["id"],
    }


def add_rising_usage_rows(api: ApiClient, state: State) -> State:
    """Add the three rising usage periods and refresh the account handle."""
    signals = [
        add_usage_signal(
            api,
            state["account_id"],
            state["csm_id"],
            row["period_end_date"],
            row["weekly_active_users"],
            row["licensed_seats"],
            row["feature_depth_pct"],
        )
        for row in RISING_USAGE_ROWS
    ]
    state["usage_signals"] = signals
    state["account"] = read_account(api, state["account_id"])
    return state


def build_trending_account(
    api: ApiClient, capacity_units_total: int = 40, account_spec: Optional[Dict[str, Any]] = None
) -> State:
    """A manager, an account and the three rising usage periods.

    Leaves the account at `adoption_index` 67.00, `snapshot_health_score` 73.85,
    `trended_health_score` 67.20 and `health_tier` AMBER.
    """
    state = build_roster_and_account(
        api, capacity_units_total=capacity_units_total, account_spec=account_spec
    )
    return add_rising_usage_rows(api, state)


def build_green_account(api: ApiClient, capacity_units_total: int = 40) -> State:
    """An account whose snapshot variant clears the GREEN floor.

    The three rising usage periods plus an active economic buyer at CXO
    seniority lift `snapshot_health_score` to 77.60 while the trailing variant
    stays at 70.95 — the pair the tier-derivation rule of PRD §3.2 separates.
    """
    state = build_roster_and_account(api, capacity_units_total=capacity_units_total)
    state = add_rising_usage_rows(api, state)
    state["sponsor"] = add_sponsor(api, state["account_id"], state["csm_id"])
    state["sponsor_id"] = state["sponsor"]["id"]
    state["account"] = read_account(api, state["account_id"])
    return state


def add_buyer_sponsor(api: ApiClient, state: State, **overrides: Any) -> State:
    """Give the account an ACTIVE economic buyer and refresh the handle."""
    sponsor = add_sponsor(api, state["account_id"], state["csm_id"], **overrides)
    state["sponsor"] = sponsor
    state["sponsor_id"] = sponsor["id"]
    state["account"] = read_account(api, state["account_id"])
    return state


def open_coverage(api: ApiClient, state: State, **overrides: Any) -> State:
    """Segment the account and commit a coverage assignment.

    PRD §2.9 rule 15 refuses a coverage assignment before segmentation, and the
    committed assignment is what moves the posture from RESTRICTED to OPEN, so
    the two calls always travel together. The account version observed from the
    segmentation response is what PRD §2.7 requires the create to quote.
    """
    segmented = segment_account(api, state["account_id"])
    state["segmented_account"] = segmented
    state["account_version"] = segmented["version"]
    assignment = assign_coverage(
        api, state["account_id"], segmented["version"], **overrides
    )
    state["assignment"] = assignment
    state["assignment_id"] = assignment["id"]
    state["account"] = read_account(api, state["account_id"])
    state["csm"] = read_csm(api, state["csm_id"])
    return state


def build_open_account(
    api: ApiClient, capacity_units_total: int = 40
) -> State:
    """A trending AMBER account with committed coverage and an OPEN posture."""
    state = build_trending_account(api, capacity_units_total=capacity_units_total)
    return open_coverage(api, state)


def build_open_green_account(api: ApiClient, capacity_units_total: int = 40) -> State:
    """A GREEN account with committed coverage and an OPEN posture."""
    state = build_green_account(api, capacity_units_total=capacity_units_total)
    return open_coverage(api, state)


def add_active_save_play(
    api: ApiClient,
    state: State,
    window_start_date: str = "2026-08-01",
    window_end_date: str = "2026-08-31",
    **overrides: Any,
) -> State:
    """Draft a save play and activate it.

    Activation requires a RED or AMBER tier per PRD §2.9 rule 18, so this runs
    on the trending-account chain rather than the GREEN one.
    """
    play = draft_save_play(
        api,
        state["account_id"],
        state["csm_id"],
        window_start_date,
        window_end_date,
        **overrides,
    )
    play = transition_save_play(
        api, play["id"], state["csm_id"], PLAY_ACTION_ACTIVATE
    )
    state["save_play"] = play
    state["save_play_id"] = play["id"]
    state["account"] = read_account(api, state["account_id"])
    return state


def build_active_play_account(api: ApiClient) -> State:
    """An AMBER account with committed coverage and one ACTIVE save play."""
    state = build_open_account(api)
    return add_active_save_play(api, state)


def add_open_escalation(
    api: ApiClient, state: State, severity: str = SEVERITY_HIGH, **overrides: Any
) -> State:
    """Raise an escalation case against the account's active save play."""
    case = raise_escalation(
        api, state["account_id"], state["save_play_id"], severity, **overrides
    )
    state["case"] = case
    state["case_id"] = case["id"]
    state["case_version"] = case["version"]
    state["account"] = read_account(api, state["account_id"])
    return state


def build_escalated_account(api: ApiClient, severity: str = SEVERITY_HIGH) -> State:
    """An account with an ACTIVE save play and an OPEN escalation case.

    Also gives the account an ACTIVE economic buyer, because PRD §2.9 rule 17
    demands executive cover before the case may be committed.
    """
    state = build_active_play_account(api)
    state = add_buyer_sponsor(api, state)
    return add_open_escalation(api, state, severity)


def add_accepted_commitment(
    api: ApiClient,
    state: State,
    credit_cents: int = 600_000,
    due_date: str = "2026-09-30",
    accept_headers: Optional[Dict[str, str]] = None,
) -> State:
    """Propose a commitment against the case's current round and accept it."""
    case = read_case(api, state["case_id"])
    commitment = propose_commitment(
        api, state["case_id"], credit_cents, due_date, case["version"]
    )
    commitment = transition_commitment(
        api, commitment["id"], COMMITMENT_ACTION_ACCEPT, accept_headers
    )
    state["commitment"] = commitment
    state["commitment_id"] = commitment["id"]
    state["account"] = read_account(api, state["account_id"])
    state["case"] = read_case(api, state["case_id"])
    return state


def commit_case(api: ApiClient, state: State) -> State:
    """Carry the escalation case to COMMITTED."""
    case = transition_escalation(api, state["case_id"], CASE_ACTION_COMMIT)
    state["case"] = case
    state["case_version"] = case["version"]
    state["account"] = read_account(api, state["account_id"])
    return state


def build_committed_case(
    api: ApiClient, credit_cents: int = 600_000, due_date: str = "2026-09-30"
) -> State:
    """An escalation case in COMMITTED with one ACCEPTED commitment."""
    state = build_escalated_account(api)
    state = add_accepted_commitment(
        api, state, credit_cents=credit_cents, due_date=due_date
    )
    return commit_case(api, state)


def deliver_commitment(api: ApiClient, state: State) -> State:
    """Deliver the case's accepted commitment as a second executive.

    PRD §2.9 rule 8 keys segregation of duties on the acting user identifier, so
    delivery must come from an executive other than the one who accepted.
    """
    commitment = transition_commitment(
        api,
        state["commitment_id"],
        COMMITMENT_ACTION_DELIVER,
        make_executive_headers("exec-2"),
    )
    state["commitment"] = commitment
    state["account"] = read_account(api, state["account_id"])
    return state


def build_delivered_case(api: ApiClient, credit_cents: int = 600_000) -> State:
    """A COMMITTED case whose single commitment has been DELIVERED."""
    state = build_committed_case(api, credit_cents=credit_cents)
    return deliver_commitment(api, state)


def add_draft_forecast(
    api: ApiClient, state: State, fiscal_period: str = "2026Q3", **overrides: Any
) -> State:
    """Open a forecast on the account, leaving both axes at their entry states."""
    forecast = open_forecast(
        api, state["account_id"], state["csm_id"], fiscal_period, **overrides
    )
    state["forecast"] = forecast
    state["forecast_id"] = forecast["id"]
    return state


def build_submitted_forecast(
    api: ApiClient, fiscal_period: str = "2026Q3", **overrides: Any
) -> State:
    """An OPEN-posture account with a forecast whose CS axis is SUBMITTED.

    PRD §2.9 rule 16 requires a COMMITTED coverage assignment before the CS
    number may be submitted, which is why the coverage chain runs first.
    """
    state = build_open_account(api)
    state = add_draft_forecast(api, state, fiscal_period, **overrides)
    state["forecast"] = submit_forecast(api, state["forecast_id"], state["csm_id"])
    return state


def add_identified_opportunity(api: ApiClient, state: State, **overrides: Any) -> State:
    """Identify an expansion opportunity on the account."""
    opportunity = identify_opportunity(
        api, state["account_id"], state["csm_id"], **overrides
    )
    state["opportunity"] = opportunity
    state["opportunity_id"] = opportunity["id"]
    return state


def build_handed_off_opportunity(
    api: ApiClient, ae_user_id: str = SALES_AE_USER_ID
) -> State:
    """A GREEN, OPEN-posture account with an opportunity in HANDED_OFF.

    PRD §2.9 rule 14 requires an OPEN posture and PRD §3.7 an AMBER or GREEN
    tier with a qualification score of at least 65.00, so the GREEN chain is the
    one that can carry a handoff.
    """
    state = build_open_green_account(api)
    state = add_identified_opportunity(api, state)
    state["opportunity"] = transition_opportunity(
        api,
        state["opportunity_id"],
        OPPORTUNITY_ACTION_HANDOFF,
        state["csm_headers"],
        handoff_ae_user_id=ae_user_id,
    )
    state["handoff_ae_user_id"] = ae_user_id
    return state


def add_nominated_enrollment(
    api: ApiClient, state: State, program_type: str = PROGRAM_REFERENCE
) -> State:
    """Nominate the account into an advocacy programme."""
    enrollment = nominate_enrollment(api, state["account_id"], program_type)
    state["enrollment"] = enrollment
    state["enrollment_id"] = enrollment["id"]
    return state


def build_active_enrollment(
    api: ApiClient, program_type: str = PROGRAM_REFERENCE
) -> State:
    """A GREEN, OPEN-posture account with an ACTIVE advocacy enrollment.

    Approval demands a GREEN tier and an OPEN posture per PRD §3.8, so the
    enrollment rides the GREEN coverage chain.
    """
    state = build_open_green_account(api)
    state = add_nominated_enrollment(api, state, program_type)
    transition_enrollment(api, state["enrollment_id"], ENROLLMENT_ACTION_APPROVE)
    state["enrollment"] = transition_enrollment(
        api, state["enrollment_id"], ENROLLMENT_ACTION_ACTIVATE
    )
    return state


def build_two_managers_one_account(
    api: ApiClient, first_capacity: int = 17, second_capacity: int = 40
) -> State:
    """Two HIGH_TOUCH managers of differing capacity plus one account.

    The ranking rule of PRD §3.4 orders the pool by `capacity_units_available`
    descending, so the second manager is the one the system picks unaided.
    """
    first = create_csm(
        api, full_name="Ada Lovelace", capacity_units_total=first_capacity
    )
    second = create_csm(
        api, full_name="Grace Hopper", capacity_units_total=second_capacity
    )
    account = create_account(api, **NORTHWIND)
    return {
        "csm": first,
        "csm_id": first["id"],
        "csm_headers": make_csm_headers(first["id"]),
        "second_csm": second,
        "second_csm_id": second["id"],
        "second_csm_headers": make_csm_headers(second["id"]),
        "account": account,
        "account_id": account["id"],
    }


def build_digital_smb_account(api: ApiClient, capacity_units_total: int = 40) -> State:
    """An SMB account bound for the DIGITAL tier, with a DIGITAL manager.

    At 100,000 cents the segmentation clauses of PRD §3.4 fall through to
    DIGITAL, whose load formula floors at a single unit.
    """
    state = build_roster_and_account(
        api,
        capacity_units_total=capacity_units_total,
        coverage_specialty=TIER_DIGITAL,
        account_spec=CORNERSHOP,
    )
    state["sponsor"] = add_sponsor(api, state["account_id"], state["csm_id"])
    state["sponsor_id"] = state["sponsor"]["id"]
    state["usage_signals"] = [
        add_usage_signal(
            api,
            state["account_id"],
            state["csm_id"],
            NEWEST_USAGE_ROW["period_end_date"],
            NEWEST_USAGE_ROW["weekly_active_users"],
            NEWEST_USAGE_ROW["licensed_seats"],
            NEWEST_USAGE_ROW["feature_depth_pct"],
        )
    ]
    state["account"] = read_account(api, state["account_id"])
    return state


# ===========================================================================
# 5. pytest fixtures
# ===========================================================================


@pytest.fixture
def api() -> ApiClient:
    """A client bound to the API under test."""
    return ApiClient()


@pytest.fixture
def clock(api: ApiClient) -> str:
    """Pin the logical clock to the default declared by PRD §2.5."""
    set_clock(api, DEFAULT_CLOCK_UTC)
    return DEFAULT_CLOCK_UTC


@pytest.fixture
def roster_and_account(api: ApiClient) -> State:
    """A manager and a baseline account with no signals."""
    return build_roster_and_account(api)


@pytest.fixture
def trending_account(api: ApiClient) -> State:
    """A manager, an account and the three rising usage periods."""
    return build_trending_account(api)


@pytest.fixture
def green_account(api: ApiClient) -> State:
    """An account whose snapshot variant clears the GREEN floor."""
    return build_green_account(api)


@pytest.fixture
def open_account(api: ApiClient) -> State:
    """A trending AMBER account with committed coverage and an OPEN posture."""
    return build_open_account(api)


@pytest.fixture
def open_green_account(api: ApiClient) -> State:
    """A GREEN account with committed coverage and an OPEN posture."""
    return build_open_green_account(api)


@pytest.fixture
def active_play_account(api: ApiClient) -> State:
    """An AMBER account with committed coverage and one ACTIVE save play."""
    return build_active_play_account(api)


@pytest.fixture
def escalated_account(api: ApiClient) -> State:
    """An account with an ACTIVE save play and an OPEN escalation case."""
    return build_escalated_account(api)


@pytest.fixture
def committed_case(api: ApiClient) -> State:
    """An escalation case in COMMITTED with one ACCEPTED commitment."""
    return build_committed_case(api)


@pytest.fixture
def delivered_case(api: ApiClient) -> State:
    """A COMMITTED case whose single commitment has been DELIVERED."""
    return build_delivered_case(api)


@pytest.fixture
def submitted_forecast(api: ApiClient) -> State:
    """An account with a forecast whose CS axis is SUBMITTED."""
    return build_submitted_forecast(api)


@pytest.fixture
def handed_off_opportunity(api: ApiClient) -> State:
    """A GREEN account with an opportunity in HANDED_OFF."""
    return build_handed_off_opportunity(api)


@pytest.fixture
def active_enrollment(api: ApiClient) -> State:
    """A GREEN account with an ACTIVE advocacy enrollment."""
    return build_active_enrollment(api)


@pytest.fixture
def two_managers_one_account(api: ApiClient) -> State:
    """Two HIGH_TOUCH managers of differing capacity plus one account."""
    return build_two_managers_one_account(api)


@pytest.fixture
def digital_smb_account(api: ApiClient) -> State:
    """An SMB account bound for the DIGITAL tier, with a DIGITAL manager."""
    return build_digital_smb_account(api)
