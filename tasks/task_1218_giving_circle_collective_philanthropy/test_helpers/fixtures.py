"""Composite setup helpers for the giving-circle test suite.

Every helper builds its preconditions from scratch against an empty database,
using only PRD-declared endpoints, so each test runs against a freshly started
server. Setup calls use the lenient get_success_data validator so a setup
failure surfaces as a clear "Setup step failed" message.

Context convention: helpers return / extend a plain dict ("ctx") holding the
entities built so far: circle, cycle, members, memberships, nonprofits,
nominations, finalists, ballots, contributions, award, payouts, reports.
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .constants import VISIT_END_ISO, VISIT_START_ISO, VOTING_CLOSED_CLOCK_ISO
from .test_users import (
    TEST_USERS,
    make_finance_headers,
    make_grantee_headers,
    make_member_headers,
)

ADMIN = TEST_USERS["admin_headers"]
FINANCE = TEST_USERS["finance_headers"]


# ---------------------------------------------------------------------------
# Primitive steps
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (PRD §2.4)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def advance_cycle(cycle_id: str, headers: dict = None) -> dict:
    """Read the current cycle version, then advance one phase hop under the
    optimistic-concurrency rule (PRD §2.8). Returns the updated cycle."""
    current = get_success_data(api_client.get_cycle(cycle_id, ADMIN))
    return get_success_data(
        api_client.advance_cycle(
            cycle_id,
            {"expected_cycle_version": current["version"]},
            headers or ADMIN,
        )
    )


def try_advance_cycle(cycle_id: str, headers: dict = None):
    """Same as advance_cycle but returns the raw Response so tests can assert
    a rejected advance."""
    current = get_success_data(api_client.get_cycle(cycle_id, ADMIN))
    return api_client.advance_cycle(
        cycle_id,
        {"expected_cycle_version": current["version"]},
        headers or ADMIN,
    )


def get_ledger(cycle_id: str) -> dict:
    return get_success_data(api_client.get_cycle_ledger(cycle_id, ADMIN))


def get_tally(cycle_id: str) -> dict:
    return get_success_data(api_client.get_cycle_tally(cycle_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1/2: circle, cycle, members, funding, nominations
# ---------------------------------------------------------------------------

def create_circle_and_cycle(name: str = "Circle", year_label: str = "2026", **cfg) -> dict:
    """A circle plus its DRAFT giving cycle (PRD §3.1)."""
    circle = get_success_data(
        api_client.create_circle(factories.create_circle_payload(name=name, **cfg), ADMIN)
    )
    cycle = get_success_data(
        api_client.create_cycle(
            factories.create_cycle_payload(circle["id"], year_label), ADMIN
        )
    )
    return {
        "circle": circle,
        "cycle": cycle,
        "members": [],
        "memberships": [],
        "nonprofits": [],
        "nominations": [],
        "finalists": [],
        "ballots": [],
        "contributions": [],
    }


def add_active_member(ctx: dict, full_name: str = None, tier: str = "STANDARD") -> tuple:
    """Register a member, invite into the circle, and accept the invitation as
    that member (PRD §3.2). Returns (member, ACTIVE membership)."""
    idx = len(ctx["members"]) + 1
    member = get_success_data(
        api_client.create_member(
            factories.create_member_payload(full_name or f"Member {idx}"), ADMIN
        )
    )
    membership = get_success_data(
        api_client.create_membership(
            factories.create_membership_payload(member["id"], ctx["circle"]["id"], tier),
            ADMIN,
        )
    )
    membership = get_success_data(
        api_client.accept_membership(
            membership["id"], make_member_headers(member["id"])
        )
    )
    ctx["members"].append(member)
    ctx["memberships"].append(membership)
    return member, membership


def contribute(ctx: dict, member_index: int, amount_cents: int, receive: bool = False) -> dict:
    """Pledge a contribution as the owning member (PRD §3.3); optionally record
    receipt as the administration."""
    member = ctx["members"][member_index]
    membership = ctx["memberships"][member_index]
    contribution = get_success_data(
        api_client.create_contribution(
            factories.create_contribution_payload(
                ctx["cycle"]["id"], membership["id"], amount_cents
            ),
            make_member_headers(member["id"]),
        )
    )
    if receive:
        contribution = get_success_data(
            api_client.receive_contribution(contribution["id"], ADMIN)
        )
    ctx["contributions"].append(contribution)
    return contribution


def add_nonprofit(ctx: dict, legal_name: str = None, mission_category: str = "arts") -> dict:
    """Register a nonprofit (PRD §3.4)."""
    idx = len(ctx["nonprofits"]) + 1
    nonprofit = get_success_data(
        api_client.create_nonprofit(
            factories.create_nonprofit_payload(
                legal_name=legal_name or f"Nonprofit {idx}",
                mission_category=mission_category,
            ),
            ADMIN,
        )
    )
    ctx["nonprofits"].append(nonprofit)
    return nonprofit


def nominate(ctx: dict, nonprofit_index: int, member_index: int, statement: str = "s") -> dict:
    """An active member nominates a nonprofit in the cycle (PRD §3.4)."""
    nonprofit = ctx["nonprofits"][nonprofit_index]
    member = ctx["members"][member_index]
    nomination = get_success_data(
        api_client.create_nomination(
            factories.create_nomination_payload(
                ctx["cycle"]["id"], nonprofit["id"], statement
            ),
            make_member_headers(member["id"]),
        )
    )
    ctx["nominations"].append(nomination)
    return nomination


# ---------------------------------------------------------------------------
# Tier 3: vetting lifecycle
# ---------------------------------------------------------------------------

def start_vetting(nomination_id: str) -> dict:
    return get_success_data(api_client.start_vetting(nomination_id, ADMIN))


def score_nomination(nomination_id: str, scores=(80, 80, 80)) -> dict:
    """Set the three vetting inputs; the weighted score recomputes per the
    circle's vetting profile (PRD §3.4). Returns the updated nomination."""
    fin, align, cap = scores
    return get_success_data(
        api_client.patch_nomination(
            nomination_id,
            factories.vetting_scores_payload(fin, align, cap),
            ADMIN,
        )
    )


def schedule_visit(nomination_id: str, starts_at: str = VISIT_START_ISO, ends_at: str = VISIT_END_ISO) -> dict:
    return get_success_data(
        api_client.create_site_visit(
            factories.create_site_visit_payload(nomination_id, starts_at, ends_at),
            ADMIN,
        )
    )


def complete_visit(visit_id: str, findings_note: str = "ok") -> dict:
    """Complete a visit whose window has fully elapsed on the logical clock
    (PRD §3.5). Caller is responsible for the clock position."""
    return get_success_data(
        api_client.complete_site_visit(visit_id, {"findings_note": findings_note}, ADMIN)
    )


def vet_to_finalist(nomination_id: str, scores=(80, 80, 80)) -> dict:
    """Walk a nomination SUBMITTED -> VETTING -> FINALIST: start vetting, score,
    run one site visit to completion, advance to finalist (PRD §3.4)."""
    start_vetting(nomination_id)
    score_nomination(nomination_id, scores)
    visit = schedule_visit(nomination_id)
    set_clock(VISIT_END_ISO)
    complete_visit(visit["id"])
    return get_success_data(api_client.advance_to_finalist(nomination_id, ADMIN))


# ---------------------------------------------------------------------------
# Phase composites
# ---------------------------------------------------------------------------

def setup_pooling(name: str = "Circle", num_members: int = 2, funding=None, **cfg) -> dict:
    """Circle + cycle advanced DRAFT -> RECRUITMENT -> POOLING with active
    members. funding: list of (member_index, amount_cents, receive) tuples."""
    ctx = create_circle_and_cycle(name, **cfg)
    for _ in range(num_members):
        add_active_member(ctx)
    advance_cycle(ctx["cycle"]["id"])  # DRAFT -> RECRUITMENT
    advance_cycle(ctx["cycle"]["id"])  # RECRUITMENT -> POOLING
    for member_index, amount, receive in (funding or []):
        contribute(ctx, member_index, amount, receive=receive)
    return ctx


def setup_nomination_phase(
    name: str = "Circle",
    num_members: int = 2,
    funding=((0, 100000, True),),
    num_nominations: int = 0,
    **cfg,
) -> dict:
    """Cycle in NOMINATION (the pool guard requires money actually received,
    PRD §3.1). Optionally creates nominations, one per membership."""
    ctx = setup_pooling(name, num_members=num_members, funding=funding, **cfg)
    advance_cycle(ctx["cycle"]["id"])  # POOLING -> NOMINATION
    for i in range(num_nominations):
        add_nonprofit(ctx)
        nominate(ctx, i, i % num_members)
    return ctx


def setup_nomination_in_vetting(
    name: str = "Circle",
    vetting_profile: str = "BALANCED",
    scores=None,
    with_visit: bool = False,
    complete_the_visit: bool = True,
    num_members: int = 1,
) -> dict:
    """Cycle in VETTING with one nomination moved SUBMITTED -> VETTING.
    Optionally scored (scores triple) and optionally given a site visit
    (completed when complete_the_visit, otherwise left SCHEDULED)."""
    ctx = setup_nomination_phase(
        name,
        num_members=num_members,
        funding=((0, 100000, True),),
        num_nominations=1,
        vetting_profile=vetting_profile,
    )
    advance_cycle(ctx["cycle"]["id"])  # NOMINATION -> VETTING
    nomination = ctx["nominations"][0]
    start_vetting(nomination["id"])
    if scores is not None:
        ctx["scored_nomination"] = score_nomination(nomination["id"], scores)
    if with_visit:
        ctx["visit"] = schedule_visit(nomination["id"])
        if complete_the_visit:
            set_clock(VISIT_END_ISO)
            ctx["visit"] = complete_visit(ctx["visit"]["id"])
    return ctx


def setup_voting(
    name: str = "Circle",
    num_members: int = 2,
    quorum_percent: int = 50,
    vetting_profile: str = "BALANCED",
    funding=((0, 100000, True),),
    num_finalists: int = 1,
    extra_submitted: int = 0,
    ballot_points=None,
    scores=(80, 80, 80),
) -> dict:
    """Full pipeline through the VETTING -> VOTING advance: circle, active
    members, received funding, nominations, finalists, voting window opened
    (PRD §3.6), then ballots cast per ballot_points.

    ballot_points: list of (member_index, [points per finalist in order]).
    Default None: every member casts 100 points on the single finalist (only
    valid when num_finalists == 1); pass [] to cast no ballots.
    """
    total_nominations = num_finalists + extra_submitted
    ctx = setup_nomination_phase(
        name,
        num_members=num_members,
        funding=funding,
        num_nominations=total_nominations,
        quorum_percent=quorum_percent,
        vetting_profile=vetting_profile,
    )
    advance_cycle(ctx["cycle"]["id"])  # NOMINATION -> VETTING
    for i in range(num_finalists):
        finalist = vet_to_finalist(ctx["nominations"][i]["id"], scores)
        ctx["finalists"].append(finalist)
    ctx["cycle"] = advance_cycle(ctx["cycle"]["id"])  # VETTING -> VOTING
    if ballot_points is None:
        ballot_points = [(i, [100]) for i in range(num_members)] if num_finalists == 1 else []
    for member_index, points_list in ballot_points:
        cast_ballot(ctx, member_index, points_list)
    return ctx


def cast_ballot(ctx: dict, member_index: int, points_list) -> dict:
    """Cast a ballot distributing points over the cycle's finalists in order
    (PRD §3.6). Entries with 0 points are omitted."""
    member = ctx["members"][member_index]
    membership = ctx["memberships"][member_index]
    allocations = [
        factories.allocation(ctx["finalists"][i]["id"], points)
        for i, points in enumerate(points_list)
        if points > 0
    ]
    ballot = get_success_data(
        api_client.create_ballot(
            factories.create_ballot_payload(
                ctx["cycle"]["id"], membership["id"], allocations
            ),
            make_member_headers(member["id"]),
        )
    )
    ctx["ballots"].append(ballot)
    return ballot


def close_voting_window(ctx: dict) -> None:
    """Move the logical clock strictly past voting_closes_at (PRD §3.7)."""
    set_clock(VOTING_CLOSED_CLOCK_ISO)


def setup_award(name: str = "Circle", **kwargs) -> dict:
    """Full pipeline through VOTING -> AWARD: quorum satisfied, window closed,
    the award committed, both payout tranches and both grantee reports created
    (PRD §3.7). Adds award / payouts (tranche ascending) / reports (INTERIM
    first, PRD §2.3) to the context."""
    ctx = setup_voting(name, **kwargs)
    close_voting_window(ctx)
    ctx["cycle"] = advance_cycle(ctx["cycle"]["id"])  # VOTING -> AWARD
    awards = get_success_data(
        api_client.list_awards(ADMIN, params={"cycle_id": ctx["cycle"]["id"]})
    )
    ctx["award"] = awards[0]
    ctx["payouts"] = get_success_data(
        api_client.list_payouts(FINANCE, params={"award_id": ctx["award"]["id"]})
    )
    ctx["reports"] = get_success_data(
        api_client.list_reports(ADMIN, params={"award_id": ctx["award"]["id"]})
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 3/5: payout pipeline, reports, close, rollover
# ---------------------------------------------------------------------------

def approve_and_release_payout(ctx: dict, payout: dict, officer: str = "fin-1") -> dict:
    """FinanceOfficer approval then release (PRD §3.7); the officer id differs
    from the requesting administrator's id."""
    headers = make_finance_headers(officer)
    get_success_data(api_client.approve_payout(payout["id"], headers))
    return get_success_data(api_client.release_payout(payout["id"], headers))


def submit_and_accept_report(ctx: dict, report: dict, narrative: str = "n", expenditure_cents: int = 10000) -> dict:
    """Grantee submits, administration accepts (PRD §3.8)."""
    get_success_data(
        api_client.submit_report(
            report["id"],
            factories.submit_report_payload(narrative, expenditure_cents),
            make_grantee_headers(ctx["award"]["nonprofit_id"]),
        )
    )
    return get_success_data(api_client.accept_report(report["id"], ADMIN))


def setup_reporting(name: str = "Circle", **kwargs) -> dict:
    """Cycle in REPORTING with every payout RELEASED and every report ACCEPTED
    (PRD §3.7-§3.8)."""
    ctx = setup_award(name, **kwargs)
    t1, t2 = ctx["payouts"][0], ctx["payouts"][1]
    interim, final = ctx["reports"][0], ctx["reports"][1]
    approve_and_release_payout(ctx, t1)
    submit_and_accept_report(ctx, interim, "interim", 30000)
    approve_and_release_payout(ctx, t2)
    submit_and_accept_report(ctx, final, "final", 90000)
    ctx["cycle"] = advance_cycle(ctx["cycle"]["id"])  # AWARD -> REPORTING
    return ctx


def setup_second_cycle_nomination(ctx: dict, year_label: str = "2027") -> dict:
    """A second cycle of the same circle walked to NOMINATION phase: the first
    member (still ACTIVE) funds it with one received contribution (PRD §3.1
    phase guards)."""
    cycle2 = get_success_data(
        api_client.create_cycle(
            factories.create_cycle_payload(ctx["circle"]["id"], year_label), ADMIN
        )
    )
    advance_cycle(cycle2["id"])  # DRAFT -> RECRUITMENT
    advance_cycle(cycle2["id"])  # RECRUITMENT -> POOLING (member 0 is ACTIVE)
    contribution = get_success_data(
        api_client.create_contribution(
            factories.create_contribution_payload(
                cycle2["id"], ctx["memberships"][0]["id"], 100000
            ),
            make_member_headers(ctx["members"][0]["id"]),
        )
    )
    get_success_data(api_client.receive_contribution(contribution["id"], ADMIN))
    advance_cycle(cycle2["id"])  # POOLING -> NOMINATION
    return cycle2


def nominate_in_cycle(ctx: dict, cycle_id: str, nonprofit_index: int, member_index: int = 0, statement: str = "s") -> dict:
    """Nominate one of the context's nonprofits in a specific cycle (used for
    the second cycle of the circle)."""
    nonprofit = ctx["nonprofits"][nonprofit_index]
    member = ctx["members"][member_index]
    nomination = get_success_data(
        api_client.create_nomination(
            factories.create_nomination_payload(cycle_id, nonprofit["id"], statement),
            make_member_headers(member["id"]),
        )
    )
    ctx["nominations"].append(nomination)
    return nomination


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def create_session(cycle_id: str, title: str, starts_at: str, ends_at: str, capacity: int) -> dict:
    return get_success_data(
        api_client.create_learning_session(
            factories.create_learning_session_payload(
                cycle_id, title, starts_at, ends_at, capacity
            ),
            ADMIN,
        )
    )


def rsvp(session_id: str, membership_id: str, member_id: str) -> dict:
    return get_success_data(
        api_client.rsvp_session(
            session_id, {"membership_id": membership_id}, make_member_headers(member_id)
        )
    )
