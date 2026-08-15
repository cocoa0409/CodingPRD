"""Composite setup helpers.

Each helper builds a multi-step precondition chain using only PRD-declared
endpoints. Setup calls use the lenient get_success_data() so failures surface
as clear 'Setup step failed' errors. Every test runs against a freshly
restarted server (empty database, logical clock at 2026-08-01T00:00:00Z), so
helpers create everything they need from scratch.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    QUARTER_SNAPSHOT_SERIES,
    FISCAL_YEAR_END_SERIES,
    PROGRAM_WINDOW_OPEN,
    PROGRAM_WINDOW_CLOSE,
    PROGRAM_WINDOW_AFTER_CLOSE,
)
from .factories import (
    create_fund_payload,
    create_agreement_payload,
    create_advisor_payload,
    create_contribution_payload,
    create_lot_payload,
    create_pool_payload,
    create_grantee_payload,
    create_grant_payload,
    create_program_payload,
    create_member_payload,
    create_application_payload,
    create_score_payload,
)
from .test_users import (
    TEST_USERS,
    make_officer_headers,
    make_advisor_headers,
    make_applicant_headers,
    make_committee_member_headers,
)

ADMIN = TEST_USERS["foundation_admin_headers"]
GIFT = TEST_USERS["gift_officer_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]
PROGRAM = TEST_USERS["program_officer_headers"]
INVESTMENT = TEST_USERS["investment_manager_headers"]


# --- clock -------------------------------------------------------------------

def set_logical_clock(iso_ts: str) -> str:
    """Advance the logical clock (FoundationAdmin); returns current_utc."""
    data = get_success_data(
        api_client.set_clock({"to_iso8601": iso_ts}, ADMIN)
    )
    return data["current_utc"]


# --- funds & agreements (Tier 1: state progression) --------------------------

def create_active_fund(
    *,
    fund_name=None,
    fund_type="DESIGNATED",
    endowed=False,
    seed_amount=50000.00,
    agreement_overrides=None,
) -> dict:
    """Fund -> agreement -> execute -> CASH seed contribution -> accept -> activate.

    Returns {"fund", "agreement", "seed_contribution"} with the fund freshly
    re-read after activation.
    """
    fund_payload = create_fund_payload()
    if fund_name is not None:
        fund_payload["fund_name"] = fund_name
    fund_payload["fund_type"] = fund_type
    fund_payload["endowed"] = endowed
    fund = get_success_data(api_client.create_fund(fund_payload, ADMIN))

    agreement = get_success_data(
        api_client.create_agreement(
            fund["id"], create_agreement_payload(**(agreement_overrides or {})), ADMIN
        )
    )
    get_success_data(api_client.execute_agreement(agreement["id"], ADMIN))

    contribution = get_success_data(
        api_client.create_contribution(
            create_contribution_payload(fund_id=fund["id"], declared_value=seed_amount),
            GIFT,
        )
    )
    get_success_data(api_client.accept_contribution(contribution["id"], GIFT))
    fund = get_success_data(api_client.activate_fund(fund["id"], ADMIN))
    return {"fund": fund, "agreement": agreement, "seed_contribution": contribution}


def get_fund(fund_id: str) -> dict:
    return get_success_data(api_client.get_fund(fund_id, ADMIN))


def get_fund_version(fund_id: str) -> int:
    return get_fund(fund_id)["version"]


# --- advisors -----------------------------------------------------------------

def invite_and_accept_advisor(fund_id: str, *, advisor_kind="PRIMARY", **overrides) -> dict:
    """Invite an advisor and accept the invitation as that advisor (self-service)."""
    advisor = get_success_data(
        api_client.invite_advisor(fund_id, create_advisor_payload(advisor_kind=advisor_kind, **overrides), ADMIN)
    )
    return get_success_data(
        api_client.accept_advisor(advisor["id"], make_advisor_headers(advisor["id"]))
    )


# --- grantees -----------------------------------------------------------------

def create_cleared_grantee(*, irs_subsection="C3_501", **overrides) -> dict:
    """Register a grantee and walk UNVETTED -> IN_REVIEW -> CLEARED."""
    grantee = get_success_data(
        api_client.create_grantee(
            create_grantee_payload(irs_subsection=irs_subsection, **overrides), COMPLIANCE
        )
    )
    get_success_data(api_client.begin_grantee_review(grantee["id"], COMPLIANCE))
    return get_success_data(api_client.clear_grantee(grantee["id"], COMPLIANCE))


# --- grants (Tier 3: lifecycle shortcuts) ------------------------------------

def create_draft_grant(
    *,
    fund_id: str,
    grantee_id: str,
    amount: float,
    purpose: str = "Charitable purpose",
    advisor_id=None,
) -> dict:
    """Create a DRAFT grant, threading expected_fund_version from a fresh read.

    advisor_id set -> created by that Advisor (donor-advised flow); otherwise
    created by FoundationAdmin (staff-initiated flow).
    """
    payload = create_grant_payload(
        fund_id=fund_id,
        grantee_id=grantee_id,
        amount=amount,
        purpose=purpose,
        expected_fund_version=get_fund_version(fund_id),
    )
    if advisor_id is not None:
        payload["recommended_by_advisor_id"] = advisor_id
        headers = make_advisor_headers(advisor_id)
    else:
        headers = ADMIN
    return get_success_data(api_client.create_grant(payload, headers))


def submit_grant(grant: dict, *, advisor_id=None) -> dict:
    """Submit a DRAFT/RETURNED grant. Advisor submits donor-advised grants."""
    headers = make_advisor_headers(advisor_id) if advisor_id else ADMIN
    return get_success_data(api_client.submit_grant(grant["id"], headers))


def create_grant_in_review(
    *,
    fund_id: str,
    grantee_id: str,
    amount: float,
    claimer_id: str = "co-1",
    advisor_id=None,
) -> dict:
    """DRAFT -> SUBMITTED -> COMPLIANCE_REVIEW (claimed by claimer_id)."""
    grant = create_draft_grant(
        fund_id=fund_id, grantee_id=grantee_id, amount=amount, advisor_id=advisor_id
    )
    submit_grant(grant, advisor_id=advisor_id)
    return get_success_data(
        api_client.claim_grant_review(
            grant["id"], make_officer_headers("ComplianceOfficer", claimer_id)
        )
    )


def create_approved_grant(
    *,
    fund_id: str,
    grantee_id: str,
    amount: float,
    claimer_id: str = "co-1",
    approver_id: str = "co-2",
    advisor_id=None,
) -> dict:
    """Full path to APPROVED with distinct claimer/approver (segregation of duties)."""
    grant = create_grant_in_review(
        fund_id=fund_id,
        grantee_id=grantee_id,
        amount=amount,
        claimer_id=claimer_id,
        advisor_id=advisor_id,
    )
    return get_success_data(
        api_client.approve_grant(
            grant["id"], {}, make_officer_headers("ComplianceOfficer", approver_id)
        )
    )


# --- pools & unitization ------------------------------------------------------

def create_pool(*, initial_nav=1000000.00, initial_units=50000.0000, **overrides) -> dict:
    return get_success_data(
        api_client.create_pool(
            create_pool_payload(
                initial_nav=initial_nav, initial_units=initial_units, **overrides
            ),
            INVESTMENT,
        )
    )


def get_pool(pool_id: str) -> dict:
    return get_success_data(api_client.get_pool(pool_id, INVESTMENT))


def buy_in(pool_id: str, fund_id: str, cash_amount: float) -> dict:
    """BUY_IN at the pool's current version (OCC field threaded fresh)."""
    pool = get_pool(pool_id)
    return get_success_data(
        api_client.create_unitization_event(
            pool_id,
            {
                "event_kind": "BUY_IN",
                "fund_id": fund_id,
                "cash_amount": cash_amount,
                "expected_pool_version": pool["version"],
            },
            INVESTMENT,
        )
    )


# --- spending policy & fees (Tier 4: threshold targeting) ---------------------

def post_snapshot(fund_id: str, snapshot_kind: str, effective_date: str, market_value: float):
    return get_success_data(
        api_client.create_snapshot(
            fund_id,
            {
                "snapshot_kind": snapshot_kind,
                "effective_date": effective_date,
                "market_value": market_value,
            },
            FINANCE,
        )
    )


def setup_endowed_fund_with_12q_allowance(*, seed_amount=200000.00, rate=4.5) -> dict:
    """ACTIVE endowed fund with the 12 quarter-end snapshots recorded and the
    FY2026 AVERAGE_12Q spending policy run executed.

    Returns {"fund", "run"} — fund freshly re-read (current_spending_allowance
    set, allowance_used reset to 0).
    """
    bundle = create_active_fund(
        fund_type="DESIGNATED",
        endowed=True,
        seed_amount=seed_amount,
        agreement_overrides={"spending_rate_pct": rate, "spending_formula": "AVERAGE_12Q"},
    )
    fund_id = bundle["fund"]["id"]
    for effective_date, market_value in QUARTER_SNAPSHOT_SERIES:
        post_snapshot(fund_id, "QUARTER_END", effective_date, market_value)
    run = get_success_data(
        api_client.create_spending_run(fund_id, {"fiscal_year": 2026}, FINANCE)
    )
    return {"fund": get_fund(fund_id), "run": run}


# --- scholarship programs (Tier 2/3: hierarchy + lifecycle) -------------------

def create_scholarship_program(
    *,
    fund_id: str,
    member_count: int = 3,
    program_overrides=None,
) -> dict:
    """Program in SETUP with member_count seated members."""
    program = get_success_data(
        api_client.create_program(
            fund_id, create_program_payload(**(program_overrides or {})), PROGRAM
        )
    )
    members = [
        get_success_data(
            api_client.seat_committee_member(
                program["id"], create_member_payload(), PROGRAM
            )
        )
        for _ in range(member_count)
    ]
    return {"program": program, "members": members}


def setup_open_program(*, seed_amount=100000.00, member_count=3, program_overrides=None) -> dict:
    """ACTIVE SCHOLARSHIP fund + program opened for applications.

    Sets the logical clock to the window open instant first so the open check
    (clock < application_close) passes.
    """
    set_logical_clock(PROGRAM_WINDOW_OPEN)
    bundle = create_active_fund(fund_type="SCHOLARSHIP", seed_amount=seed_amount)
    built = create_scholarship_program(
        fund_id=bundle["fund"]["id"],
        member_count=member_count,
        program_overrides=program_overrides,
    )
    program = get_success_data(api_client.open_program(built["program"]["id"], PROGRAM))
    return {"fund": bundle["fund"], "program": program, "members": built["members"]}


def submit_application(program_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.submit_application(
            program_id,
            create_application_payload(**overrides),
            TEST_USERS["applicant_headers"],
        )
    )


def setup_scoring_program(*, num_applications=1, seed_amount=100000.00) -> dict:
    """Program walked OPEN -> SCORING with applications cascaded to UNDER_SCORING.

    Returns {"fund", "program", "members", "applications"}.
    """
    env = setup_open_program(seed_amount=seed_amount)
    applications = [
        submit_application(env["program"]["id"]) for _ in range(num_applications)
    ]
    set_logical_clock(PROGRAM_WINDOW_AFTER_CLOSE)
    program = get_success_data(
        api_client.close_program_applications(env["program"]["id"], PROGRAM)
    )
    return {
        "fund": env["fund"],
        "program": program,
        "members": env["members"],
        "applications": applications,
    }


def score_application(application_id: str, member_id: str, **components) -> dict:
    payload = create_score_payload(member_id=member_id, **components)
    return get_success_data(
        api_client.create_score(
            application_id, payload, make_committee_member_headers(member_id)
        )
    )


def setup_awarded_program(*, seed_amount=100000.00, score=90) -> dict:
    """Program walked all the way to AWARDED with exactly one winner.

    The winner application receives quorum-reaching scores (two entries at the
    given uniform component score). Returns env plus "award_ids".
    """
    env = setup_scoring_program(num_applications=1, seed_amount=seed_amount)
    app_id = env["applications"][0]["id"]
    members = env["members"]
    score_application(app_id, members[0]["id"], academic=score, financial_need=score, essay=score, interview=score)
    score_application(app_id, members[1]["id"], academic=score, financial_need=score, essay=score, interview=score)
    result = get_success_data(
        api_client.select_winners(env["program"]["id"], {"winner_application_ids": [app_id]}, PROGRAM)
    )
    env["award_ids"] = result["award_ids"]
    env["program"] = get_success_data(api_client.get_program(env["program"]["id"], PROGRAM))
    return env
