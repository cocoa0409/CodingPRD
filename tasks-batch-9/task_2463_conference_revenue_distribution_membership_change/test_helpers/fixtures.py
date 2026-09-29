"""Composite setup helpers.

Every test starts against an empty database, so all state is built through the
public endpoints.  These helpers wrap the recurring bootstrap chains - seating a
charter roster, adopting a budget, funding the reserve, booking a media schedule,
distributing and posting a pool - so individual tests only have to express the
step they are actually about.

Setup steps use :func:`get_success_data`, which accepts any 2xx and raises a
descriptive ``AssertionError`` when a setup call fails, so a broken bootstrap is
never mistaken for a failing assertion.
"""

from typing import Any, Dict, Iterable, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .constants import (
    DEFAULT_LOGICAL_CLOCK,
    POST_ROSTER_CLOCK,
    ROSTER_CLOCKS,
    TEST_DEFAULTS,
)
from .factories import (
    make_action_ballot_payload,
    make_audit_report_payload,
    make_bowl_appearance_payload,
    make_budget_ballot_payload,
    make_budget_proposal_payload,
    make_championship_event_payload,
    make_conference_payload,
    make_distribution_run_payload,
    make_event_settlement_payload,
    make_member_payload,
    make_membership_action_payload,
    make_protected_rivalry_payload,
    make_reserve_transfer_payload,
    make_revenue_pool_payload,
    make_schedule_game_payload,
    make_venue_payload,
    make_withdrawal_notice_payload,
)
from .test_users import (
    AUDITOR_USER_ID,
    FINANCE_OFFICER_USER_ID,
    TREASURER_USER_ID,
    make_auditor_headers,
    make_commissioner_headers,
    make_compliance_officer_headers,
    make_finance_officer_headers,
    make_member_representative_headers,
    make_platform_admin_headers,
    make_schedule_coordinator_headers,
    make_treasurer_headers,
)
from .types import (
    ActionType,
    AdmissionPath,
    AllocationMethod,
    BallotChoice,
    PoolType,
    RunVariant,
    TransferType,
)

CHARTER_ROSTER: Sequence[Dict[str, str]] = (
    {"key": "north", "name": "North State University", "institution_code": "NOR", "venue": "north"},
    {"key": "south", "name": "South Valley University", "institution_code": "SOU", "venue": "north"},
    {"key": "east", "name": "East Harbor College", "institution_code": "EAS", "venue": "east"},
    {"key": "west", "name": "West Ridge University", "institution_code": "WES", "venue": "east"},
)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def set_logical_clock(api: ApiClient, to_iso8601: str = DEFAULT_LOGICAL_CLOCK) -> None:
    get_success_data(api.set_clock(to_iso8601, headers=make_platform_admin_headers()))


# ---------------------------------------------------------------------------
# Singletons and roster
# ---------------------------------------------------------------------------
def create_conference(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_conference(
            make_conference_payload(**overrides), headers=make_platform_admin_headers()
        )
    )


def read_conference(api: ApiClient) -> Dict[str, Any]:
    return get_success_data(api.get_conference(headers=make_treasurer_headers()))


def create_venue(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_venue(make_venue_payload(**overrides), headers=make_platform_admin_headers())
    )


def create_member(
    api: ApiClient, conference_id: str, home_venue_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_member(
            make_member_payload(conference_id, home_venue_id, **overrides),
            headers=make_commissioner_headers(),
        )
    )


def read_member(api: ApiClient, member_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_member(member_id, headers=make_commissioner_headers()))


def setup_conference_and_venues(api: ApiClient, **conference_overrides: Any) -> Dict[str, Any]:
    """Clock, conference and the two venues every later fixture builds on."""
    set_logical_clock(api)
    conference = create_conference(api, **conference_overrides)
    venue_north = create_venue(
        api, name="Northfield Dome", city="Northfield", seating_capacity=60000,
        concurrent_event_capacity=1,
    )
    venue_east = create_venue(
        api, name="Eastport Arena", city="Eastport", seating_capacity=45000,
        concurrent_event_capacity=2,
    )
    return {
        "conference": conference,
        "conference_id": conference["id"],
        "venue_north": venue_north,
        "venue_east": venue_east,
        "venues": {"north": venue_north, "east": venue_east},
    }


def setup_charter_roster(
    api: ApiClient, member_keys: Iterable[str] = ("north", "south", "east", "west"), **conference_overrides: Any
) -> Dict[str, Any]:
    """Seat charter institutions, each at its own instant so created_at is strictly ordered.

    The allocation order and the remainder-cent tie-break both read Member
    created_at, so the roster is seated one logical second apart to make that
    order unambiguous.
    """
    ctx = setup_conference_and_venues(api, **conference_overrides)
    wanted = list(member_keys)
    members: Dict[str, Dict[str, Any]] = {}
    clock_index = 0
    for spec in CHARTER_ROSTER:
        if spec["key"] not in wanted:
            continue
        set_logical_clock(api, ROSTER_CLOCKS[clock_index])
        clock_index += 1
        members[spec["key"]] = create_member(
            api,
            ctx["conference_id"],
            ctx["venues"][spec["venue"]]["id"],
            name=spec["name"],
            institution_code=spec["institution_code"],
            admission_path=AdmissionPath.CHARTER.value,
            grant_of_rights_through_fiscal_year=TEST_DEFAULTS["GOR_THROUGH_FISCAL_YEAR"],
        )
    set_logical_clock(api, POST_ROSTER_CLOCK)
    ctx["members"] = members
    ctx["member_ids"] = {key: member["id"] for key, member in members.items()}
    return ctx


def create_petitioned_member(api: ApiClient, ctx: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": "Central Plains University",
        "institution_code": "CEN",
        "admission_path": AdmissionPath.PETITIONED.value,
        "grant_of_rights_through_fiscal_year": 2034,
        "entry_fee_cents": 0,
    }
    payload.update(overrides)
    member = create_member(api, ctx["conference_id"], ctx["venue_east"]["id"], **payload)
    ctx.setdefault("members", {})["central"] = member
    ctx.setdefault("member_ids", {})["central"] = member["id"]
    return member


# ---------------------------------------------------------------------------
# Budget, reserve and the graduation to OPERATING
# ---------------------------------------------------------------------------
def draft_budget_proposal(api: ApiClient, conference_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_budget_proposal(
            make_budget_proposal_payload(conference_id, **overrides),
            headers=make_finance_officer_headers(),
        )
    )


def approve_annual_budget(
    api: ApiClient,
    conference_id: str,
    voter_member_ids: Sequence[str],
    choices: Optional[Sequence[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Draft, open, canvass and close a budget ballot; all-FOR by default."""
    proposal = draft_budget_proposal(api, conference_id, **overrides)
    get_success_data(
        api.open_budget_voting(proposal["id"], headers=make_finance_officer_headers())
    )
    ballot_choices = list(choices) if choices else [BallotChoice.FOR.value] * len(voter_member_ids)
    for member_id, choice in zip(voter_member_ids, ballot_choices):
        get_success_data(
            api.cast_budget_ballot(
                proposal["id"],
                make_budget_ballot_payload(member_id, choice),
                headers=make_member_representative_headers(member_id),
            )
        )
    return get_success_data(
        api.close_budget_voting(proposal["id"], headers=make_finance_officer_headers())
    )


def fund_reserve(
    api: ApiClient,
    amount_cents: int,
    transfer_type: str = TransferType.CONTRIBUTION.value,
    expected_conference_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Move reserve money, reading the conference version when none is supplied."""
    if expected_conference_version is None:
        expected_conference_version = read_conference(api)["version"]
    return get_success_data(
        api.create_reserve_transfer(
            make_reserve_transfer_payload(
                amount_cents, expected_conference_version, transfer_type=transfer_type
            ),
            headers=make_treasurer_headers(),
        )
    )


def setup_operating_conference(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """A charter roster with the first budget adopted, so the conference is OPERATING."""
    ctx = setup_charter_roster(api, **kwargs)
    ctx["budget_proposal"] = approve_annual_budget(
        api, ctx["conference_id"], list(ctx["member_ids"].values())
    )
    return ctx


def setup_operating_conference_with_reserve(
    api: ApiClient, reserve_cents: int = TEST_DEFAULTS["RESERVE_SEED_CENTS"], **kwargs: Any
) -> Dict[str, Any]:
    """OPERATING with a part-funded reserve, which leaves the posture OPEN."""
    ctx = setup_operating_conference(api, **kwargs)
    ctx["conference"] = fund_reserve(api, reserve_cents)
    return ctx


# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------
def create_schedule_game(
    api: ApiClient,
    conference_id: str,
    home_member_id: str,
    away_member_id: str,
    venue_id: str,
    game_date: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_schedule_game(
            make_schedule_game_payload(
                conference_id, home_member_id, away_member_id, venue_id, game_date, **overrides
            ),
            headers=make_schedule_coordinator_headers(),
        )
    )


def play_game(api: ApiClient, game_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.play_schedule_game(game_id, headers=make_schedule_coordinator_headers())
    )


def cancel_game(api: ApiClient, game_id: str, reason: str = "Weather") -> Dict[str, Any]:
    return get_success_data(
        api.cancel_schedule_game(
            game_id, {"reason": reason}, headers=make_schedule_coordinator_headers()
        )
    )


def create_protected_rivalry(
    api: ApiClient, conference_id: str, member_a_id: str, member_b_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_protected_rivalry(
            make_protected_rivalry_payload(conference_id, member_a_id, member_b_id, **overrides),
            headers=make_schedule_coordinator_headers(),
        )
    )


def setup_media_schedule(api: ApiClient, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Four media-designated FY2027 games; three played, the North-West game still scheduled."""
    conference_id = ctx["conference_id"]
    ids = ctx["member_ids"]
    v1 = ctx["venue_north"]["id"]
    games = {
        "north_south": create_schedule_game(
            api, conference_id, ids["north"], ids["south"], v1, "2026-09-05T19:00:00Z"
        ),
        "north_east": create_schedule_game(
            api, conference_id, ids["north"], ids["east"], v1, "2026-09-12T19:00:00Z"
        ),
        "north_west": create_schedule_game(
            api, conference_id, ids["north"], ids["west"], v1, "2026-09-19T19:00:00Z"
        ),
        "south_east": create_schedule_game(
            api, conference_id, ids["south"], ids["east"], v1, "2026-09-26T19:00:00Z"
        ),
    }
    play_game(api, games["north_south"]["id"])
    play_game(api, games["north_east"]["id"])
    play_game(api, games["south_east"]["id"])
    ctx["games"] = games
    return games


# ---------------------------------------------------------------------------
# Bowl appearances and postseason units
# ---------------------------------------------------------------------------
def submit_bowl_appearance(api: ApiClient, member_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_bowl_appearance(
            member_id,
            make_bowl_appearance_payload(**overrides),
            headers=make_compliance_officer_headers(),
        )
    )


def begin_bowl_review(api: ApiClient, appearance_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.begin_bowl_review(appearance_id, headers=make_compliance_officer_headers())
    )


def request_bowl_revision(
    api: ApiClient, appearance_id: str, note: str = "Documentation does not support the claim"
) -> Dict[str, Any]:
    return get_success_data(
        api.request_bowl_revision(
            appearance_id, {"note": note}, headers=make_compliance_officer_headers()
        )
    )


def resubmit_bowl_appearance(
    api: ApiClient, appearance_id: str, member_id: str, **payload: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.resubmit_bowl_appearance(
            appearance_id, payload, headers=make_member_representative_headers(member_id)
        )
    )


def approve_bowl_appearance(api: ApiClient, appearance_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.approve_bowl_appearance(appearance_id, headers=make_compliance_officer_headers())
    )


def void_bowl_appearance(
    api: ApiClient, appearance_id: str, reason: str = "Appearance withdrawn by the institution"
) -> Dict[str, Any]:
    return get_success_data(
        api.void_bowl_appearance(
            appearance_id, {"reason": reason}, headers=make_compliance_officer_headers()
        )
    )


def setup_approved_bowl_appearance(api: ApiClient, member_id: str, **overrides: Any) -> Dict[str, Any]:
    """Submit, review and approve an appearance so its units reach VALIDATED."""
    appearance = submit_bowl_appearance(api, member_id, **overrides)
    begin_bowl_review(api, appearance["id"])
    return approve_bowl_appearance(api, appearance["id"])


# ---------------------------------------------------------------------------
# Revenue pools and distribution runs
# ---------------------------------------------------------------------------
def create_revenue_pool(api: ApiClient, conference_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_revenue_pool(
            make_revenue_pool_payload(conference_id, **overrides),
            headers=make_finance_officer_headers(),
        )
    )


def open_revenue_pool(api: ApiClient, pool_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.open_revenue_pool(pool_id, headers=make_finance_officer_headers())
    )


def read_revenue_pool(api: ApiClient, pool_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_revenue_pool(pool_id, headers=make_finance_officer_headers())
    )


def close_pool_books(api: ApiClient, pool_id: str, audited_expense_cents: int) -> Dict[str, Any]:
    return get_success_data(
        api.close_revenue_pool_books(
            pool_id,
            {"audited_expense_cents": audited_expense_cents},
            headers=make_finance_officer_headers(),
        )
    )


def compute_run(
    api: ApiClient,
    pool_id: str,
    variant: str = RunVariant.PROVISIONAL.value,
    expected_pool_version: Optional[int] = None,
    user_id: str = FINANCE_OFFICER_USER_ID,
    **overrides: Any,
) -> Dict[str, Any]:
    """Compute a run, reading the pool's current version when none is supplied."""
    if expected_pool_version is None:
        expected_pool_version = read_revenue_pool(api, pool_id)["version"]
    return get_success_data(
        api.create_distribution_run(
            pool_id,
            make_distribution_run_payload(expected_pool_version, variant, **overrides),
            headers=make_finance_officer_headers(user_id),
        )
    )


def read_run_lines(api: ApiClient, run_id: str, **params: Any) -> List[Dict[str, Any]]:
    return get_success_data(
        api.list_distribution_run_lines(
            run_id, params=params or None, headers=make_finance_officer_headers()
        )
    )


def post_run(api: ApiClient, run_id: str, user_id: str = TREASURER_USER_ID) -> Dict[str, Any]:
    return get_success_data(
        api.post_distribution_run(run_id, headers=make_treasurer_headers(user_id))
    )


def draft_audit_report(
    api: ApiClient, conference_id: str, run_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_audit_report(
            make_audit_report_payload(conference_id, run_id, **overrides),
            headers=make_auditor_headers(),
        )
    )


def issue_audit_report(
    api: ApiClient, report_id: str, user_id: str = AUDITOR_USER_ID
) -> Dict[str, Any]:
    return get_success_data(
        api.issue_audit_report(report_id, headers=make_auditor_headers(user_id))
    )


def accept_audit_report(api: ApiClient, report_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.accept_audit_report(report_id, headers=make_commissioner_headers())
    )


def setup_fy2027_media_pool(api: ApiClient, ctx: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    """An OPEN FY2027 media-rights pool allocated by appearance and performance."""
    pool = create_revenue_pool(api, ctx["conference_id"], **overrides)
    pool = open_revenue_pool(api, pool["id"])
    ctx["pool"] = pool
    ctx["pool_id"] = pool["id"]
    return pool


def setup_full_media_fixture(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """The whole FY2027 media picture: roster, budget, reserve, games, appearances, OPEN pool.

    North's tournament appearance is APPROVED and West's bowl appearance is left
    in SUBMITTED, which is what makes the two run variants diverge.
    """
    ctx = setup_operating_conference_with_reserve(api, **kwargs)
    setup_media_schedule(api, ctx)
    ctx["appearance_north"] = setup_approved_bowl_appearance(
        api,
        ctx["member_ids"]["north"],
        event_name="Prairie Bowl",
        event_tier="TOURNAMENT",
        payout_cents=12_000_000,
        submitted_expense_cents=9_500_000,
        travel_miles=1400,
        units_claimed=2,
    )
    ctx["appearance_west"] = submit_bowl_appearance(
        api,
        ctx["member_ids"]["west"],
        event_name="Harvest Bowl",
        event_tier="BOWL",
        payout_cents=6_000_000,
        submitted_expense_cents=4_200_000,
        travel_miles=900,
        units_claimed=1,
    )
    setup_fy2027_media_pool(api, ctx)
    return ctx


def setup_books_closed_media_fixture(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """The FY2027 media fixture with West's appearance voided and the books closed."""
    ctx = setup_full_media_fixture(api, **kwargs)
    void_bowl_appearance(api, ctx["appearance_west"]["id"])
    ctx["pool"] = close_pool_books(
        api, ctx["pool_id"], TEST_DEFAULTS["MEDIA_POOL_AUDITED_EXPENSE_CENTS"]
    )
    return ctx


def setup_unit_based_pool(api: ApiClient, ctx: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    """An OPEN unit-based postseason pool, whose basis is the validated unit count."""
    defaults: Dict[str, Any] = {
        "pool_type": PoolType.POSTSEASON_UNIT.value,
        "allocation_method": AllocationMethod.UNIT_BASED.value,
        "gross_revenue_cents": 100_000_000,
        "estimated_expense_cents": 0,
    }
    defaults.update(overrides)
    pool = create_revenue_pool(api, ctx["conference_id"], **defaults)
    pool = open_revenue_pool(api, pool["id"])
    ctx["unit_pool"] = pool
    ctx["unit_pool_id"] = pool["id"]
    return pool


def setup_computed_fy2026_final_run(
    api: ApiClient,
    ctx: Dict[str, Any],
    gross_revenue_cents: int = TEST_DEFAULTS["FY2026_POOL_GROSS_CENTS"],
    audited_expense_cents: int = TEST_DEFAULTS["FY2026_POOL_AUDITED_EXPENSE_CENTS"],
) -> Dict[str, Any]:
    """A BOOKS_CLOSED FY2026 equal-share pool carrying one COMPUTED final audited run."""
    pool = create_revenue_pool(
        api,
        ctx["conference_id"],
        fiscal_year=2026,
        pool_type=PoolType.MEDIA_RIGHTS.value,
        allocation_method=AllocationMethod.EQUAL_SHARE.value,
        gross_revenue_cents=gross_revenue_cents,
        estimated_expense_cents=audited_expense_cents,
    )
    open_revenue_pool(api, pool["id"])
    pool = close_pool_books(api, pool["id"], audited_expense_cents)
    run = compute_run(
        api,
        pool["id"],
        RunVariant.FINAL_AUDITED.value,
        expected_pool_version=pool["version"],
        memo="FY2026 final",
    )
    ctx["pool_2026"] = pool
    ctx["pool_2026_id"] = pool["id"]
    ctx["run_2026"] = run
    ctx["run_2026_id"] = run["id"]
    return run


def setup_posted_fy2026_distribution(
    api: ApiClient,
    ctx: Dict[str, Any],
    gross_revenue_cents: int = TEST_DEFAULTS["FY2026_POOL_GROSS_CENTS"],
    audited_expense_cents: int = TEST_DEFAULTS["FY2026_POOL_AUDITED_EXPENSE_CENTS"],
) -> Dict[str, Any]:
    """Carry an FY2026 equal-share pool all the way to POSTED.

    Posting a FINAL_AUDITED media-rights run is the only thing that writes
    ``last_full_annual_distribution_cents``, which every exit settlement is then
    assessed against.
    """
    run = setup_computed_fy2026_final_run(
        api, ctx, gross_revenue_cents=gross_revenue_cents,
        audited_expense_cents=audited_expense_cents,
    )
    report = draft_audit_report(api, ctx["conference_id"], run["id"], fiscal_year=2026)
    issue_audit_report(api, report["id"])
    posted = post_run(api, run["id"])
    ctx["audit_report_2026"] = report
    ctx["run_2026"] = posted
    return posted


def setup_closed_media_pool(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """An FY2026 pool driven all the way to CLOSED, which needs a posted run behind it."""
    ctx = setup_operating_conference_with_reserve(api, **kwargs)
    setup_posted_fy2026_distribution(api, ctx)
    ctx["pool_2026"] = get_success_data(
        api.close_revenue_pool(ctx["pool_2026_id"], headers=make_finance_officer_headers())
    )
    return ctx


# ---------------------------------------------------------------------------
# Membership actions
# ---------------------------------------------------------------------------
def propose_membership_action(
    api: ApiClient, conference_id: str, member_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_membership_action(
            make_membership_action_payload(conference_id, member_id, **overrides),
            headers=make_commissioner_headers(),
        )
    )


def open_action_voting(api: ApiClient, action_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.open_action_voting(action_id, headers=make_commissioner_headers())
    )


def read_membership_action(api: ApiClient, action_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_membership_action(action_id, headers=make_commissioner_headers())
    )


def cast_action_ballot(
    api: ApiClient, action_id: str, member_id: str, choice: str = BallotChoice.FOR.value
) -> Dict[str, Any]:
    """Cast one weighted ballot, echoing the action version read immediately before."""
    version = read_membership_action(api, action_id)["version"]
    return get_success_data(
        api.cast_action_ballot(
            action_id,
            make_action_ballot_payload(member_id, version, choice),
            headers=make_member_representative_headers(member_id),
        )
    )


def cast_action_ballots(
    api: ApiClient, action_id: str, choices: Sequence[Sequence[str]]
) -> List[Dict[str, Any]]:
    """Cast a sequence of ``(member_id, choice)`` ballots in order."""
    return [cast_action_ballot(api, action_id, member_id, choice) for member_id, choice in choices]


def close_action_voting(api: ApiClient, action_id: str) -> Dict[str, Any]:
    """Close the ballot as the ComplianceOfficer, who is never the proposer."""
    return get_success_data(
        api.close_action_voting(action_id, headers=make_compliance_officer_headers())
    )


def execute_membership_action(api: ApiClient, action_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.execute_membership_action(action_id, headers=make_commissioner_headers())
    )


def setup_admit_action_in_voting(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """An OPERATING conference, a petitioner, and an ADMIT action already in VOTING."""
    ctx = setup_operating_conference_with_reserve(api, **kwargs)
    create_petitioned_member(api, ctx)
    action = propose_membership_action(
        api,
        ctx["conference_id"],
        ctx["member_ids"]["central"],
        action_type=ActionType.ADMIT.value,
        effective_fiscal_year=2028,
        entry_fee_cents=0,
        rationale="Footprint expansion",
    )
    ctx["action"] = open_action_voting(api, action["id"])
    ctx["action_id"] = action["id"]
    return ctx


def file_withdrawal_notice(
    api: ApiClient, member_id: str, withdrawal_effective_fiscal_year: int = 2030, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.file_withdrawal_notice(
            member_id,
            make_withdrawal_notice_payload(withdrawal_effective_fiscal_year, **overrides),
            headers=make_commissioner_headers(),
        )
    )


def rescind_withdrawal_notice(api: ApiClient, member_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.rescind_withdrawal_notice(member_id, headers=make_commissioner_headers())
    )


# ---------------------------------------------------------------------------
# Championship events
# ---------------------------------------------------------------------------
def award_championship_event(
    api: ApiClient,
    conference_id: str,
    venue_id: str,
    host_member_id: str,
    revenue_pool_id: str,
    window_start: str,
    window_end: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_championship_event(
            make_championship_event_payload(
                conference_id, venue_id, host_member_id, revenue_pool_id,
                window_start, window_end, **overrides,
            ),
            headers=make_commissioner_headers(),
        )
    )


def host_championship_event(api: ApiClient, event_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.host_championship_event(event_id, headers=make_commissioner_headers())
    )


def settle_championship_event(
    api: ApiClient,
    event_id: str,
    ticket_revenue_cents: int,
    sponsorship_revenue_cents: int,
    event_expense_cents: int,
) -> Dict[str, Any]:
    return get_success_data(
        api.settle_championship_event(
            event_id,
            make_event_settlement_payload(
                ticket_revenue_cents, sponsorship_revenue_cents, event_expense_cents
            ),
            headers=make_finance_officer_headers(),
        )
    )


def setup_championship_settlement_fixture(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """A HOSTED championship linked to a pool that already carries a COMPUTED run.

    Settling it is what drives the pool back to DRAFT and cascades onto the run
    and its lines.
    """
    ctx = setup_full_media_fixture(api, **kwargs)
    ctx["run"] = compute_run(api, ctx["pool_id"], memo="cascade fixture")
    ctx["run_id"] = ctx["run"]["id"]
    event = award_championship_event(
        api,
        ctx["conference_id"],
        ctx["venue_north"]["id"],
        ctx["member_ids"]["south"],
        ctx["pool_id"],
        "2027-03-05T00:00:00Z",
        "2027-03-08T00:00:00Z",
    )
    ctx["event"] = host_championship_event(api, event["id"])
    ctx["event_id"] = event["id"]
    return ctx


def setup_venue_capacity_fixture(api: ApiClient) -> Dict[str, Any]:
    """One member, a DRAFT pool, and two overlapping events on the capacity-2 venue."""
    ctx = setup_charter_roster(api, member_keys=("south",))
    ctx["pool"] = create_revenue_pool(api, ctx["conference_id"])
    ctx["pool_id"] = ctx["pool"]["id"]
    ctx["event_wrestling"] = award_championship_event(
        api, ctx["conference_id"], ctx["venue_east"]["id"], ctx["member_ids"]["south"],
        ctx["pool_id"], "2027-03-01T00:00:00Z", "2027-03-05T00:00:00Z", sport="WRESTLING",
    )
    ctx["event_swimming"] = award_championship_event(
        api, ctx["conference_id"], ctx["venue_east"]["id"], ctx["member_ids"]["south"],
        ctx["pool_id"], "2027-03-03T00:00:00Z", "2027-03-07T00:00:00Z", sport="SWIMMING",
    )
    return ctx


def setup_withdraw_cascade_fixture(api: ApiClient) -> Dict[str, Any]:
    """South hosts a championship, and an APPROVED WITHDRAW against North is ready to execute.

    South's two home games sit six calendar days apart, the separation the rest
    buffer accepts, and North's notice is filed after the ballot closes so that
    the vote is cast at full weight and the subject is nevertheless in
    WITHDRAWAL_NOTICED when the action executes.
    """
    ctx = setup_operating_conference_with_reserve(api)
    ids = ctx["member_ids"]
    ctx["pool"] = create_revenue_pool(api, ctx["conference_id"])
    ctx["pool_id"] = ctx["pool"]["id"]
    ctx["rivalry_border"] = create_protected_rivalry(
        api, ctx["conference_id"], ids["south"], ids["north"],
        required_annual_meetings=1, label="Border Trophy",
    )
    ctx["rivalry_harbor"] = create_protected_rivalry(
        api, ctx["conference_id"], ids["south"], ids["east"],
        required_annual_meetings=1, label="Harbor Cup",
    )
    ctx["game_border"] = create_schedule_game(
        api, ctx["conference_id"], ids["south"], ids["north"], ctx["venue_north"]["id"],
        "2026-10-03T19:00:00Z", media_designated=False,
        protected_rivalry_id=ctx["rivalry_border"]["id"],
    )
    ctx["game_harbor"] = create_schedule_game(
        api, ctx["conference_id"], ids["south"], ids["east"], ctx["venue_north"]["id"],
        "2026-10-09T19:00:00Z", media_designated=False,
        protected_rivalry_id=ctx["rivalry_harbor"]["id"],
    )
    ctx["event"] = award_championship_event(
        api, ctx["conference_id"], ctx["venue_north"]["id"], ids["south"], ctx["pool_id"],
        "2027-03-05T00:00:00Z", "2027-03-08T00:00:00Z",
    )
    ctx["event_id"] = ctx["event"]["id"]
    action = propose_membership_action(
        api, ctx["conference_id"], ids["north"],
        action_type=ActionType.WITHDRAW.value, effective_fiscal_year=2028,
        rationale="Persistent bylaw breach",
    )
    open_action_voting(api, action["id"])
    cast_action_ballots(
        api,
        action["id"],
        (
            (ids["south"], BallotChoice.FOR.value),
            (ids["east"], BallotChoice.FOR.value),
            (ids["west"], BallotChoice.FOR.value),
            (ids["north"], BallotChoice.AGAINST.value),
        ),
    )
    ctx["action"] = close_action_voting(api, action["id"])
    ctx["action_id"] = action["id"]
    file_withdrawal_notice(api, ids["north"], withdrawal_effective_fiscal_year=2028)
    return ctx
