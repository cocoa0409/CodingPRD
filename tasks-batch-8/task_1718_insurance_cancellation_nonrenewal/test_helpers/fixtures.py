"""Composite setup helpers.

The interesting claims in this PRD all require the system to be in a
specific state: an ACTIVE profile, an issued policy, an approved and
notice-dispatched cancellation case, a swept clock, etc. These helpers
build those states from scratch using only PRD-declared endpoints.

All setup calls use get_success_data() so a setup failure surfaces as a
clear "Setup failed" style error rather than a confusing assertion.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    approve_cancellation_payload,
    clock_payload,
    create_appeal_payload,
    create_cancellation_case_payload,
    create_interest_payload,
    create_nonrenewal_case_payload,
    create_policy_payload,
    create_policyholder_payload,
    create_reinstatement_payload,
    create_state_profile_payload,
    dispatch_payload,
    notice_entry,
)
from .test_users import (
    TEST_USERS,
    make_policyholder_headers,
)

OFFICER = TEST_USERS["compliance_officer_headers"]
UNDERWRITER = TEST_USERS["underwriter_headers"]


# ---------------------------------------------------------------------------
# Tier 1 — clock and single-entity builders
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Advance the logical clock (runs the scheduled sweeps)."""
    resp = api_client.set_clock(clock_payload(to_iso8601), OFFICER)
    return get_success_data(resp)


def create_active_profile(state_code: str, **profile_over) -> dict:
    """Create a StateFilingProfile and activate it. Returns the ACTIVE profile."""
    resp = api_client.create_state_profile(
        create_state_profile_payload(state_code=state_code, **profile_over), OFFICER
    )
    profile = get_success_data(resp)
    resp = api_client.activate_state_profile(profile["id"], OFFICER)
    return get_success_data(resp)


def create_holder(**over) -> dict:
    """Create a Policyholder. Returns the created record."""
    resp = api_client.create_policyholder(create_policyholder_payload(**over), UNDERWRITER)
    return get_success_data(resp)


def issue_policy(profile_id: str, holder_id: str, policy_number: str, **policy_over) -> dict:
    """Issue a Policy against an ACTIVE profile. Returns the ACTIVE policy."""
    resp = api_client.create_policy(
        create_policy_payload(holder_id, profile_id, policy_number, **policy_over), UNDERWRITER
    )
    return get_success_data(resp)


def get_policy(policy_id: str) -> dict:
    return get_success_data(api_client.get_policy(policy_id, OFFICER))


def get_cancellation_case(case_id: str) -> dict:
    return get_success_data(api_client.get_cancellation_case(case_id, OFFICER))


def get_nonrenewal_case(case_id: str) -> dict:
    return get_success_data(api_client.get_nonrenewal_case(case_id, OFFICER))


def get_reinstatement_request(request_id: str) -> dict:
    return get_success_data(api_client.get_reinstatement_request(request_id, OFFICER))


def get_appeal(appeal_id: str) -> dict:
    return get_success_data(api_client.get_appeal(appeal_id, OFFICER))


def policy_ledger(policy_id: str) -> list:
    return get_success_data(api_client.list_policy_ledger_entries(policy_id, OFFICER))


# ---------------------------------------------------------------------------
# Tier 2 — entity hierarchy
# ---------------------------------------------------------------------------

def setup_active_policy(
    state_code: str,
    clock: str = "2026-08-01T00:00:00Z",
    profile_over: dict = None,
    policy_over: dict = None,
    holder_over: dict = None,
    policy_number: str = None,
    set_clock_first: bool = True,
):
    """ACTIVE profile + policyholder + ACTIVE policy.

    Returns (profile, holder, policy).
    """
    if set_clock_first:
        set_clock(clock)
    profile = create_active_profile(state_code, **(profile_over or {}))
    holder = create_holder(**(holder_over or {}))
    policy = issue_policy(
        profile["id"], holder["id"], policy_number or f"P-{state_code}-1", **(policy_over or {})
    )
    return profile, holder, policy


def attach_interest(policy_id: str, **over) -> dict:
    """Attach a mortgagee / lienholder / additional interest to a policy."""
    resp = api_client.create_interest(policy_id, create_interest_payload(**over), UNDERWRITER)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3 — cancellation lifecycle shortcuts
# ---------------------------------------------------------------------------

def open_cancellation_case(
    policy: dict,
    ground_code: str = "NONPAYMENT",
    by_policyholder: bool = False,
    holder_id: str = None,
    creator_headers=None,
) -> dict:
    """Open a CancellationCase against an ACTIVE policy (fresh OCC version).

    Returns the PENDING_APPROVAL case.
    """
    current = get_policy(policy["id"])
    payload = create_cancellation_case_payload(policy["id"], current["version"], ground_code=ground_code)
    if creator_headers is not None:
        headers = creator_headers
    elif by_policyholder:
        assert holder_id is not None, "holder_id required for policyholder-filed cases"
        headers = make_policyholder_headers(holder_id)
    else:
        headers = UNDERWRITER
    resp = api_client.create_cancellation_case(payload, headers)
    return get_success_data(resp)


def approve_cancellation(case_id: str, scheduled_effective_date: str, officer_headers=None) -> dict:
    """Approve a PENDING_APPROVAL case. Returns the APPROVED case."""
    resp = api_client.approve_cancellation_case(
        case_id, approve_cancellation_payload(scheduled_effective_date), officer_headers or OFFICER
    )
    return get_success_data(resp)


def dispatch_cancellation_notices(
    case_id: str,
    mailed_on_date: str,
    interests: list = None,
    tracking_prefix: str = "T",
) -> list:
    """Dispatch the full statutory notice set for an APPROVED case.

    Builds one POLICYHOLDER notice plus one notice per insured interest
    (recipient_kind matching the interest's type). Returns NoticeRecords.
    """
    notices = [notice_entry("POLICYHOLDER", mailed_on_date, f"{tracking_prefix}-PH")]
    for i, interest in enumerate(interests or []):
        notices.append(
            notice_entry(
                interest["interest_type"],
                mailed_on_date,
                f"{tracking_prefix}-I{i + 1}",
                insured_interest_id=interest["id"],
            )
        )
    resp = api_client.dispatch_cancellation_notices(case_id, dispatch_payload(notices), UNDERWRITER)
    return get_success_data(resp)


def cancel_policy_effective(
    state_code: str,
    request_clock: str,
    scheduled_effective_date: str,
    mailed_on_date: str,
    ground_code: str = "NONPAYMENT",
    premium_cents: int = 10000,
    term_start: str = "2026-01-01",
    term_end: str = "2027-01-01",
    profile_over: dict = None,
    policy_number: str = None,
) -> dict:
    """Full walk to a CANCELLED policy.

    Sets the clock, builds profile/holder/policy, opens + approves +
    dispatches a cancellation case, then advances the clock to
    scheduled_effective_date so the effectiveness sweep runs.

    Returns dict(profile, holder, policy, case, notices).
    """
    set_clock(request_clock)
    profile, holder, policy = setup_active_policy(
        state_code,
        clock=request_clock,
        profile_over=profile_over,
        policy_over={"total_premium_cents": premium_cents, "term_start_date": term_start, "term_end_date": term_end},
        policy_number=policy_number,
        set_clock_first=False,
    )
    by_ph = ground_code == "INSURED_REQUEST"
    case = open_cancellation_case(policy, ground_code=ground_code, by_policyholder=by_ph, holder_id=holder["id"])
    case = approve_cancellation(case["id"], scheduled_effective_date)
    notices = dispatch_cancellation_notices(case["id"], mailed_on_date, tracking_prefix=f"T-{state_code}")
    set_clock(_eod(scheduled_effective_date))
    return {
        "profile": profile,
        "holder": holder,
        "policy": get_policy(policy["id"]),
        "case": get_cancellation_case(case["id"]),
        "notices": notices,
    }


def _eod(date_str: str) -> str:
    """Date (YYYY-MM-DD) to an ISO instant at start of that day (UTC)."""
    return f"{date_str}T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 4 — reinstatement / appeal shortcuts
# ---------------------------------------------------------------------------

def submit_reinstatement(policy_id: str, case_id: str, holder_id: str) -> dict:
    """Submit a ReinstatementRequest as the policyholder (fresh OCC version)."""
    current = get_policy(policy_id)
    payload = create_reinstatement_payload(policy_id, case_id, current["version"])
    resp = api_client.create_reinstatement_request(payload, make_policyholder_headers(holder_id))
    return get_success_data(resp)


def approve_reinstatement(request_id: str, officer_headers=None) -> dict:
    resp = api_client.approve_reinstatement_request(request_id, officer_headers or OFFICER)
    return get_success_data(resp)


def file_appeal_under_review(
    case_id: str,
    holder_id: str,
    grounds_text: str = "Dispute",
    accept_officer_id: str = "officer-accept-1",
) -> dict:
    """File an appeal as the policyholder and move it to UNDER_REVIEW."""
    from .test_users import make_compliance_officer_headers

    resp = api_client.create_appeal(
        create_appeal_payload(case_id, filed_by="POLICYHOLDER", grounds_text=grounds_text),
        make_policyholder_headers(holder_id),
    )
    appeal = get_success_data(resp)
    resp = api_client.accept_appeal_for_review(
        appeal["id"], make_compliance_officer_headers(accept_officer_id)
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 5 — nonrenewal lifecycle shortcuts
# ---------------------------------------------------------------------------

def open_nonrenewal_case(policy_id: str, **over) -> dict:
    """Open a NonrenewalCase. Returns the PENDING_APPROVAL case."""
    resp = api_client.create_nonrenewal_case(
        create_nonrenewal_case_payload(policy_id, **over), UNDERWRITER
    )
    return get_success_data(resp)


def approve_nonrenewal(case_id: str, officer_headers=None) -> dict:
    resp = api_client.approve_nonrenewal_case(case_id, officer_headers or OFFICER)
    return get_success_data(resp)


def dispatch_nonrenewal_notices(
    case_id: str,
    mailed_on_date: str,
    interests: list = None,
    tracking_prefix: str = "T",
) -> list:
    notices = [notice_entry("POLICYHOLDER", mailed_on_date, f"{tracking_prefix}-PH")]
    for i, interest in enumerate(interests or []):
        notices.append(
            notice_entry(
                interest["interest_type"],
                mailed_on_date,
                f"{tracking_prefix}-I{i + 1}",
                insured_interest_id=interest["id"],
            )
        )
    resp = api_client.dispatch_nonrenewal_notices(case_id, dispatch_payload(notices), UNDERWRITER)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def find_report(profile_id: str, period: str) -> dict:
    """Return the single RegulatoryReport for (profile, period); fails if absent."""
    data = get_success_data(
        api_client.list_regulatory_reports(
            OFFICER, params={"state_profile_id": profile_id, "report_period": period}
        )
    )
    rows = data if isinstance(data, list) else data.get("data", [])
    assert len(rows) == 1, f"Setup failed: expected 1 report for {profile_id}/{period}, got {len(rows)}"
    return rows[0]
