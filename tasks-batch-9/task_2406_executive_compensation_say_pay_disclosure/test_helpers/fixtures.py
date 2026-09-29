"""Composite setup helpers.

Every test starts against an empty database, so each helper here builds its
preconditions from scratch through PRD-declared endpoints only. The helpers come
in three layers:

* **atoms** — one call each (`create_company`, `screen_peer_group`, ...), all of
  which return the entity body;
* **read-backs** — `read_*` helpers that fetch current state. Several entities
  are only reachable through their parent's listing endpoint, so those helpers
  hide the list-and-filter step;
* **composites** — `setup_*` helpers that walk a whole chain (peer group to
  APPROVED, program to COMMITTEE_APPROVED / DISCLOSED, award to VESTED, a
  restatement all the way to a NOTICED determination) and return an `env` dict.

`env` keys used by the composites:
    issuer, peers (ticker -> company), peer, ceo, executives (label -> executive),
    peer_group, program, metrics (list), awards (label -> award), screens
    (advisor -> screen), cda_draft, engagements (list), restatement_event,
    determination.
"""

from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import COLD_START_UTC, REASONS
from .factories import (
    add_member_payload,
    adjustment_payload,
    analyze_payload,
    create_cda_draft_payload,
    create_company_payload,
    create_engagement_payload,
    create_executive_payload,
    create_incentive_metric_payload,
    create_pay_program_payload,
    create_payout_award_payload,
    create_peer_group_payload,
    create_restatement_event_payload,
    create_screen_payload,
    exclude_member_payload,
    hold_engagement_payload,
    market_data_payload,
    metric_result_payload,
    mix_reallocation_payload,
    remediation_payload,
    request_revision_payload,
    restated_metric_result,
    reverse_recovery_payload,
    schedule_engagement_payload,
    set_clock_payload,
    settlement_payload,
    vote_certification_payload,
)
from .test_users import (
    CHAIR_ONE,
    CHAIR_TWO,
    CONSULTANT,
    COUNSEL,
    COUNSEL_ONE,
    COUNSEL_TWO,
    IR_LEAD,
    make_comp_committee_chair_headers,
    make_named_executive_officer_headers,
    make_securities_counsel_headers,
)

LIST_ALL = {"limit": 100}


# ===========================================================================
# Atoms
# ===========================================================================
def set_clock(to_iso8601: str = COLD_START_UTC, headers: Dict[str, str] = CONSULTANT) -> str:
    """Pin the logical clock. Returns the reported current_utc."""
    data = get_success_data(api_client.set_current_utc(set_clock_payload(to_iso8601), headers))
    return data.get("current_utc", to_iso8601)


def create_company(
    template: str = "ACME", headers: Dict[str, str] = CONSULTANT, **overrides
) -> dict:
    """Register one company from the catalogue row named by `template`.

    `template` selects the catalogue row only, so callers may override
    `ticker=` to register two distinct companies off the same row.
    """
    return get_success_data(
        api_client.create_company(create_company_payload(template, **overrides), headers)
    )


def refresh_market_data(company_id: str, headers: Dict[str, str] = CONSULTANT, **fields) -> dict:
    return get_success_data(
        api_client.refresh_market_data(company_id, market_data_payload(**fields), headers)
    )


def create_executive(
    company_id: str, profile: str = "CEO", headers: Dict[str, str] = CONSULTANT, **overrides
) -> dict:
    return get_success_data(
        api_client.create_executive(
            company_id, create_executive_payload(profile, **overrides), headers
        )
    )


def create_peer_group(
    issuer_company_id: str,
    benchmark_basis: str = "RAW_MEDIAN",
    headers: Dict[str, str] = CONSULTANT,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_peer_group(
            create_peer_group_payload(issuer_company_id, benchmark_basis, **overrides), headers
        )
    )


def peer_group_version(peer_group_id: str, headers: Dict[str, str] = CONSULTANT) -> int:
    """Re-read the group so the stale-version guard carries the current value."""
    return read_peer_group(peer_group_id, headers)["version"]


def add_peer_member(
    peer_group_id: str,
    peer_company_id: str,
    inclusion_reason: str = "SIZE_MATCH",
    expected_peer_group_version: Optional[int] = None,
    headers: Dict[str, str] = CONSULTANT,
    **overrides,
) -> dict:
    """Add one peer, threading the group's current version unless one is given."""
    if expected_peer_group_version is None:
        expected_peer_group_version = peer_group_version(peer_group_id, headers)
    return get_success_data(
        api_client.add_peer_group_member(
            peer_group_id,
            add_member_payload(
                peer_company_id, expected_peer_group_version, inclusion_reason, **overrides
            ),
            headers,
        )
    )


def exclude_peer_member(
    member_id: str,
    exclusion_reason: str = REASONS["exclusion"],
    headers: Dict[str, str] = CONSULTANT,
) -> dict:
    return get_success_data(
        api_client.exclude_peer_group_member(
            member_id, exclude_member_payload(exclusion_reason), headers
        )
    )


def screen_peer_group(peer_group_id: str, headers: Dict[str, str] = CONSULTANT) -> dict:
    return get_success_data(api_client.screen_peer_group(peer_group_id, headers))


def approve_peer_group(peer_group_id: str, chair_user_id: str = CHAIR_ONE) -> dict:
    return get_success_data(
        api_client.approve_peer_group(
            peer_group_id, make_comp_committee_chair_headers(chair_user_id)
        )
    )


def create_pay_program(
    issuer_company_id: str,
    peer_group_id: str,
    ceo_executive_id: str,
    headers: Dict[str, str] = CONSULTANT,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_pay_program(
            create_pay_program_payload(
                issuer_company_id, peer_group_id, ceo_executive_id, **overrides
            ),
            headers,
        )
    )


def approve_pay_program(program_id: str, chair_user_id: str = CHAIR_ONE) -> dict:
    return get_success_data(
        api_client.approve_pay_program(
            program_id, make_comp_committee_chair_headers(chair_user_id)
        )
    )


def program_version(program_id: str, headers: Dict[str, str] = CONSULTANT) -> int:
    return read_pay_program(program_id, headers)["version"]


def reallocate_mix(
    program_id: str,
    from_component: str,
    to_component: str,
    points: float,
    expected_pay_program_version: Optional[int] = None,
    headers: Dict[str, str] = CONSULTANT,
) -> dict:
    if expected_pay_program_version is None:
        expected_pay_program_version = program_version(program_id, headers)
    return get_success_data(
        api_client.reallocate_pay_mix(
            program_id,
            mix_reallocation_payload(
                from_component, to_component, points, expected_pay_program_version
            ),
            headers,
        )
    )


def add_metric(
    program_id: str, curve: str = "ADJ_EPS_LINEAR", headers: Dict[str, str] = CONSULTANT, **overrides
) -> dict:
    return get_success_data(
        api_client.create_incentive_metric(
            program_id, create_incentive_metric_payload(curve, **overrides), headers
        )
    )


def metric_version(program_id: str, metric_id: str, headers: Dict[str, str] = CONSULTANT) -> int:
    return read_metric(program_id, metric_id, headers)["version"]


def adjust_metric(
    metric_id: str,
    expected_incentive_metric_version: int,
    chair_user_id: str = CHAIR_TWO,
    result_adjustment_reason: str = REASONS["goal_adjustment"],
    **overrides,
) -> dict:
    """Adjust a locked goal. The adjusting chair may not later certify the result."""
    return get_success_data(
        api_client.adjust_incentive_metric(
            metric_id,
            adjustment_payload(
                expected_incentive_metric_version, result_adjustment_reason, **overrides
            ),
            make_comp_committee_chair_headers(chair_user_id),
        )
    )


def submit_metric_result(
    metric_id: str, as_reported_value: float, headers: Dict[str, str] = CONSULTANT, **overrides
) -> dict:
    return get_success_data(
        api_client.submit_metric_result(
            metric_id, metric_result_payload(as_reported_value, **overrides), headers
        )
    )


def certify_metric(metric_id: str, chair_user_id: str = CHAIR_ONE) -> dict:
    return get_success_data(
        api_client.certify_metric_result(
            metric_id, make_comp_committee_chair_headers(chair_user_id)
        )
    )


def create_award(
    program_id: str,
    executive_id: str,
    vehicle: str = "ANNUAL_INCENTIVE",
    headers: Dict[str, str] = CONSULTANT,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_payout_award(
            program_id, create_payout_award_payload(executive_id, vehicle, **overrides), headers
        )
    )


def settle_award(
    award_id: str,
    disposition: str = "VEST",
    settlement_date: str = "2026-09-30T00:00:00Z",
    headers: Dict[str, str] = CONSULTANT,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.settle_payout_award(
            award_id, settlement_payload(disposition, settlement_date, **overrides), headers
        )
    )


def create_screen(program_id: str, advisor: str = "ISS", headers: Dict[str, str] = IR_LEAD) -> dict:
    return get_success_data(
        api_client.create_proxy_advisor_screen(program_id, create_screen_payload(advisor), headers)
    )


def rerun_screen(screen_id: str, headers: Dict[str, str] = IR_LEAD) -> dict:
    return get_success_data(api_client.rerun_proxy_advisor_screen(screen_id, headers))


def create_cda_draft(
    program_id: str,
    section_code: str = "CD_AND_A",
    word_count: int = 2000,
    required_tables_included: bool = True,
    author_user_id: str = COUNSEL_ONE,
) -> dict:
    return get_success_data(
        api_client.create_cda_draft(
            program_id,
            create_cda_draft_payload(section_code, word_count, required_tables_included),
            make_securities_counsel_headers(author_user_id),
        )
    )


def submit_cda_review(draft_id: str, user_id: str = COUNSEL_ONE, **payload) -> dict:
    return get_success_data(
        api_client.submit_cda_review(
            draft_id, make_securities_counsel_headers(user_id), dict(payload)
        )
    )


def request_cda_revision(
    draft_id: str,
    user_id: str = COUNSEL_TWO,
    feedback_summary: str = REASONS["cda_feedback"],
    headers: Optional[Dict[str, str]] = None,
) -> dict:
    """Ask for another revision. Pass `headers` to send this as the chair."""
    return get_success_data(
        api_client.request_cda_revision(
            draft_id,
            headers or make_securities_counsel_headers(user_id),
            request_revision_payload(feedback_summary),
        )
    )


def legal_clear_cda_draft(draft_id: str, user_id: str = COUNSEL_TWO) -> dict:
    return get_success_data(
        api_client.legal_clear_cda_draft(draft_id, make_securities_counsel_headers(user_id))
    )


def file_cda_draft(draft_id: str, user_id: str = COUNSEL_TWO) -> dict:
    return get_success_data(
        api_client.file_cda_draft(draft_id, make_securities_counsel_headers(user_id))
    )


def carry_cda_draft_to_filed(
    program_id: str,
    section_code: str = "CD_AND_A",
    word_count: int = 2000,
    required_tables_included: bool = True,
    author_user_id: str = COUNSEL_ONE,
    clearer_user_id: str = COUNSEL_TWO,
) -> dict:
    """Author, review, clear and file one section. Author and clearer differ."""
    draft = create_cda_draft(
        program_id, section_code, word_count, required_tables_included, author_user_id
    )
    submit_cda_review(draft["id"], author_user_id)
    legal_clear_cda_draft(draft["id"], clearer_user_id)
    return file_cda_draft(draft["id"], clearer_user_id)


def create_engagement(
    program_id: str,
    investor_name: str = "BlackRock",
    ownership_pct: float = 20.00,
    channel: str = "MEETING",
    headers: Dict[str, str] = IR_LEAD,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_outreach_engagement(
            program_id,
            create_engagement_payload(investor_name, ownership_pct, channel, **overrides),
            headers,
        )
    )


def schedule_engagement(
    engagement_id: str, window_start: str, window_end: str, headers: Dict[str, str] = IR_LEAD
) -> dict:
    return get_success_data(
        api_client.schedule_outreach_engagement(
            engagement_id, schedule_engagement_payload(window_start, window_end), headers
        )
    )


def hold_engagement(
    engagement_id: str, feedback_position: str = "SUPPORTIVE", headers: Dict[str, str] = IR_LEAD
) -> dict:
    return get_success_data(
        api_client.hold_outreach_engagement(
            engagement_id, hold_engagement_payload(feedback_position), headers
        )
    )


def run_engagement_to_held(
    program_id: str,
    investor_name: str,
    ownership_pct: float,
    window_start: str = "2027-03-01T00:00:00Z",
    window_end: str = "2027-03-05T00:00:00Z",
    channel: str = "MEETING",
    feedback_position: str = "SUPPORTIVE",
) -> dict:
    """Request, schedule and hold one engagement so it counts toward coverage."""
    engagement = create_engagement(program_id, investor_name, ownership_pct, channel)
    schedule_engagement(engagement["id"], window_start, window_end)
    return hold_engagement(engagement["id"], feedback_position)


def certify_vote(
    program_id: str,
    votes_for: int,
    votes_against: int,
    abstentions: int = 0,
    chair_user_id: str = CHAIR_ONE,
) -> dict:
    return get_success_data(
        api_client.certify_vote(
            program_id,
            vote_certification_payload(votes_for, votes_against, abstentions),
            make_comp_committee_chair_headers(chair_user_id),
        )
    )


def remediate_program(
    program_id: str,
    feedback_summary: str = REASONS["remediation"],
    chair_user_id: str = CHAIR_ONE,
) -> dict:
    return get_success_data(
        api_client.remediate_pay_program(
            program_id,
            remediation_payload(feedback_summary),
            make_comp_committee_chair_headers(chair_user_id),
        )
    )


def create_restatement_event(
    company_id: str, counsel_user_id: str = COUNSEL_ONE, **overrides
) -> dict:
    return get_success_data(
        api_client.create_restatement_event(
            company_id,
            create_restatement_event_payload(**overrides),
            make_securities_counsel_headers(counsel_user_id),
        )
    )


def analyze_restatement(
    event_id: str, restated_metric_results: List[Dict[str, Any]], counsel_user_id: str = COUNSEL_ONE
) -> dict:
    return get_success_data(
        api_client.analyze_restatement_event(
            event_id,
            analyze_payload(restated_metric_results),
            make_securities_counsel_headers(counsel_user_id),
        )
    )


def order_recovery(event_id: str, chair_user_id: str = CHAIR_ONE) -> dict:
    return get_success_data(
        api_client.order_restatement_recovery(
            event_id, make_comp_committee_chair_headers(chair_user_id)
        )
    )


def acknowledge_determination(determination_id: str, executive_id: str) -> dict:
    """The officer acknowledges with the identity of the executive who was paid."""
    return get_success_data(
        api_client.acknowledge_clawback_determination(
            determination_id, make_named_executive_officer_headers(executive_id)
        )
    )


def recover_determination(determination_id: str, chair_user_id: str = CHAIR_ONE) -> dict:
    return get_success_data(
        api_client.recover_clawback_determination(
            determination_id, make_comp_committee_chair_headers(chair_user_id)
        )
    )


def reverse_recovery(
    determination_id: str,
    reversal_reason: str = REASONS["reversal"],
    chair_user_id: str = CHAIR_ONE,
) -> dict:
    return get_success_data(
        api_client.reverse_clawback_recovery(
            determination_id,
            reverse_recovery_payload(reversal_reason),
            make_comp_committee_chair_headers(chair_user_id),
        )
    )


# ===========================================================================
# Read-backs
# ===========================================================================
def read_company(company_id: str, headers: Dict[str, str] = CONSULTANT) -> dict:
    return get_success_data(api_client.get_company(company_id, headers))


def read_peer_group(peer_group_id: str, headers: Dict[str, str] = CONSULTANT) -> dict:
    return get_success_data(api_client.get_peer_group(peer_group_id, headers))


def read_peer_group_members(peer_group_id: str, headers: Dict[str, str] = CONSULTANT) -> List[dict]:
    rows, _ = validate_paginated(
        api_client.list_peer_group_members(peer_group_id, headers, dict(LIST_ALL))
    )
    return rows


def read_peer_group_member(
    peer_group_id: str, member_id: str, headers: Dict[str, str] = CONSULTANT
) -> Optional[dict]:
    for row in read_peer_group_members(peer_group_id, headers):
        if row["id"] == member_id:
            return row
    return None


def read_pay_program(program_id: str, headers: Dict[str, str] = CONSULTANT) -> dict:
    return get_success_data(api_client.get_pay_program(program_id, headers))


def read_pay_for_performance(program_id: str, headers: Dict[str, str] = CONSULTANT) -> dict:
    return get_success_data(api_client.get_pay_for_performance(program_id, headers))


def read_metrics(program_id: str, headers: Dict[str, str] = CONSULTANT, **params) -> List[dict]:
    query = dict(LIST_ALL)
    query.update(params)
    rows, _ = validate_paginated(api_client.list_incentive_metrics(program_id, headers, query))
    return rows


def read_metric(program_id: str, metric_id: str, headers: Dict[str, str] = CONSULTANT) -> Optional[dict]:
    for row in read_metrics(program_id, headers):
        if row["id"] == metric_id:
            return row
    return None


def read_award(award_id: str, headers: Dict[str, str] = CONSULTANT) -> dict:
    return get_success_data(api_client.get_payout_award(award_id, headers))


def read_awards(headers: Dict[str, str] = CONSULTANT, **params) -> List[dict]:
    query = dict(LIST_ALL)
    query.update(params)
    rows, _ = validate_paginated(api_client.list_payout_awards(headers, query))
    return rows


def read_cda_drafts(program_id: str, headers: Dict[str, str] = COUNSEL, **params) -> List[dict]:
    query = dict(LIST_ALL)
    query.update(params)
    rows, _ = validate_paginated(api_client.list_cda_drafts(program_id, headers, query))
    return rows


def read_cda_draft(program_id: str, draft_id: str, headers: Dict[str, str] = COUNSEL) -> Optional[dict]:
    for row in read_cda_drafts(program_id, headers):
        if row["id"] == draft_id:
            return row
    return None


def read_screens(program_id: str, headers: Dict[str, str] = IR_LEAD, **params) -> List[dict]:
    query = dict(LIST_ALL)
    query.update(params)
    rows, _ = validate_paginated(api_client.list_proxy_advisor_screens(program_id, headers, query))
    return rows


def read_screen(program_id: str, screen_id: str, headers: Dict[str, str] = IR_LEAD) -> Optional[dict]:
    for row in read_screens(program_id, headers):
        if row["id"] == screen_id:
            return row
    return None


def read_engagements(program_id: str, headers: Dict[str, str] = IR_LEAD, **params) -> List[dict]:
    query = dict(LIST_ALL)
    query.update(params)
    rows, _ = validate_paginated(api_client.list_outreach_engagements(program_id, headers, query))
    return rows


def read_engagement(
    program_id: str, engagement_id: str, headers: Dict[str, str] = IR_LEAD
) -> Optional[dict]:
    for row in read_engagements(program_id, headers):
        if row["id"] == engagement_id:
            return row
    return None


def read_restatement_events(company_id: str, headers: Dict[str, str] = COUNSEL, **params) -> List[dict]:
    query = dict(LIST_ALL)
    query.update(params)
    rows, _ = validate_paginated(
        api_client.list_company_restatement_events(company_id, headers, query)
    )
    return rows


def read_restatement_event(
    company_id: str, event_id: str, headers: Dict[str, str] = COUNSEL
) -> Optional[dict]:
    for row in read_restatement_events(company_id, headers):
        if row["id"] == event_id:
            return row
    return None


def read_determinations(headers: Dict[str, str] = COUNSEL, **params) -> List[dict]:
    query = dict(LIST_ALL)
    query.update(params)
    rows, _ = validate_paginated(api_client.list_clawback_determinations(headers, query))
    return rows


def read_determination(determination_id: str, headers: Dict[str, str] = COUNSEL) -> dict:
    return get_success_data(api_client.get_clawback_determination(determination_id, headers))


# ===========================================================================
# Composites
# ===========================================================================
def setup_issuer(
    clock: str = COLD_START_UTC, executive_profiles: Iterable[str] = ("CEO",), **issuer_overrides
) -> Dict[str, Any]:
    """Pin the clock, register ACME as issuer, and create the named executives."""
    set_clock(clock)
    issuer = create_company("ACME", **issuer_overrides)
    executives = {
        profile: create_executive(issuer["id"], profile) for profile in executive_profiles
    }
    env: Dict[str, Any] = {
        "issuer": issuer,
        "executives": executives,
        "peers": {},
    }
    if "CEO" in executives:
        env["ceo"] = executives["CEO"]
    return env


def setup_peer_group(
    peer_tickers: Iterable[str] = ("BRVO",),
    benchmark_basis: str = "RAW_MEDIAN",
    target_status: str = "APPROVED",
    inclusion_reason: str = "SIZE_MATCH",
    clock: str = COLD_START_UTC,
    executive_profiles: Iterable[str] = ("CEO",),
    env: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a peer group over the named peers and walk it to `target_status`.

    `target_status` is one of DRAFT, SCREENED or APPROVED. With the default
    single BRVO peer the screened group reports median_revenue_usd
    8,000,000,000.00, median_market_cap_usd 16,000,000,000.00, size_fit_score
    80.00 and benchmark_target_tdc_usd 12,000,000.00 on the RAW_MEDIAN basis.
    """
    if env is None:
        env = setup_issuer(clock=clock, executive_profiles=executive_profiles)
    for ticker in peer_tickers:
        if ticker not in env["peers"]:
            env["peers"][ticker] = create_company(ticker)
    peer_group = create_peer_group(env["issuer"]["id"], benchmark_basis)
    members = {}
    for ticker in peer_tickers:
        members[ticker] = add_peer_member(
            peer_group["id"], env["peers"][ticker]["id"], inclusion_reason
        )
    if target_status in ("SCREENED", "APPROVED"):
        peer_group = screen_peer_group(peer_group["id"])
    if target_status == "APPROVED":
        peer_group = approve_peer_group(peer_group["id"])
    env["peer_group"] = peer_group
    env["members"] = members
    peer_list = list(peer_tickers)
    if peer_list:
        env["peer"] = env["peers"][peer_list[0]]
    return env


def setup_mini_peer_group(
    target_status: str = "APPROVED", benchmark_basis: str = "RAW_MEDIAN", **kwargs
) -> Dict[str, Any]:
    """ACME issuer plus BRVO as the single peer — the most reused base."""
    return setup_peer_group(
        peer_tickers=("BRVO",),
        benchmark_basis=benchmark_basis,
        target_status=target_status,
        **kwargs,
    )


def setup_four_peer_group(
    benchmark_basis: str = "RAW_MEDIAN", target_status: str = "SCREENED", **kwargs
) -> Dict[str, Any]:
    """ACME issuer plus BRVO, CHRL, DLTA and ECHO, all inside both size bands."""
    return setup_peer_group(
        peer_tickers=("BRVO", "CHRL", "DLTA", "ECHO"),
        benchmark_basis=benchmark_basis,
        target_status=target_status,
        **kwargs,
    )


def setup_pay_program(
    metric_curves: Iterable[str] = (),
    approve: bool = True,
    program_overrides: Optional[Dict[str, Any]] = None,
    metric_overrides: Optional[List[Dict[str, Any]]] = None,
    executive_label: str = "CEO",
    env: Optional[Dict[str, Any]] = None,
    peer_tickers: Iterable[str] = ("BRVO",),
    benchmark_basis: str = "RAW_MEDIAN",
    peer_group_status: str = "APPROVED",
    executive_profiles: Iterable[str] = ("CEO",),
) -> Dict[str, Any]:
    """Create a program over an approved peer group, optionally with metrics.

    With the default 15/25/60 mix on the one-peer RAW_MEDIAN group the program
    reports fixed_leg_usd 3,000,000.00, benchmark_ratio 0.6250, lti_multiple 4.0,
    lti_target_usd 12,000,000.00, target_tdc_usd 15,000,000.00,
    benchmark_posture ABOVE_MARKET and performance_based_pct 61.00.

    Metrics are added while the program is still DRAFT so committee approval
    locks them; pass `approve=False` to stop at DRAFT.
    """
    if env is None or "peer_group" not in env:
        env = setup_peer_group(
            peer_tickers=peer_tickers,
            benchmark_basis=benchmark_basis,
            target_status=peer_group_status,
            executive_profiles=executive_profiles,
            env=env,
        )
    program = create_pay_program(
        env["issuer"]["id"],
        env["peer_group"]["id"],
        env["executives"][executive_label]["id"],
        **(program_overrides or {}),
    )
    curves = list(metric_curves)
    overrides = list(metric_overrides or [{} for _ in curves])
    metrics = [
        add_metric(program["id"], curve, **(overrides[i] if i < len(overrides) else {}))
        for i, curve in enumerate(curves)
    ]
    if approve:
        program = approve_pay_program(program["id"])
    env["program"] = program
    env["metrics"] = metrics
    env["awards"] = {}
    env["screens"] = {}
    env["engagements"] = []
    return env


def setup_program_with_certified_metrics(
    achievements: Iterable[float] = (5.50, 0.63),
    metric_curves: Iterable[str] = ("ADJ_EPS_LINEAR", "COST_RATIO_STEP"),
    certify: bool = True,
    env: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Program with metrics carried to CERTIFIED.

    The default pair (ADJ_EPS weight 60.00 achieving 5.50, COST_RATIO weight
    40.00 achieving 0.63) yields payout factors 150.00 and 100.00 and therefore
    a weighted award factor of 130.00.
    """
    env = setup_pay_program(metric_curves=metric_curves, env=env, **kwargs)
    for metric, achieved in zip(env["metrics"], achievements):
        submit_metric_result(metric["id"], achieved)
    if certify:
        for metric in env["metrics"]:
            certify_metric(metric["id"])
        env["metrics"] = [read_metric(env["program"]["id"], m["id"]) for m in env["metrics"]]
    return env


def setup_award(
    env: Dict[str, Any],
    label: str = "annual_incentive",
    vehicle: str = "ANNUAL_INCENTIVE",
    executive_label: str = "CEO",
    **overrides,
) -> Dict[str, Any]:
    """Grant one award on the program already present in `env`."""
    award = create_award(
        env["program"]["id"], env["executives"][executive_label]["id"], vehicle, **overrides
    )
    env.setdefault("awards", {})[label] = award
    return env


def setup_vested_annual_incentive_award(
    settlement_date: str = "2026-09-30T00:00:00Z", env: Optional[Dict[str, Any]] = None, **kwargs
) -> Dict[str, Any]:
    """Certified two-metric program with one ANNUAL_INCENTIVE award VESTED.

    The award reports certified_factor_pct 130.00, earned_amount_usd
    2,340,000.00 and realized_value_usd 2,340,000.00.
    """
    env = setup_program_with_certified_metrics(env=env, certify=False, **kwargs)
    env = setup_award(env)
    for metric in env["metrics"]:
        certify_metric(metric["id"])
    env["metrics"] = [read_metric(env["program"]["id"], m["id"]) for m in env["metrics"]]
    env["awards"]["annual_incentive"] = settle_award(
        env["awards"]["annual_incentive"]["id"], "VEST", settlement_date
    )
    env["program"] = read_pay_program(env["program"]["id"])
    return env


def setup_disclosed_program(
    env: Optional[Dict[str, Any]] = None,
    advisor: str = "ISS",
    author_user_id: str = COUNSEL_ONE,
    clearer_user_id: str = COUNSEL_TWO,
    **kwargs,
) -> Dict[str, Any]:
    """Carry a committee-approved program to design_status DISCLOSED.

    Legal clearance requires a current screen for the advisor, so the screen is
    run first; the CD&A section is then authored, reviewed, cleared by a second
    counsel and filed, which discloses the program.
    """
    if env is None or "program" not in env:
        env = setup_pay_program(env=env, **kwargs)
    screen = create_screen(env["program"]["id"], advisor)
    env.setdefault("screens", {})[advisor] = screen
    env["cda_draft"] = carry_cda_draft_to_filed(
        env["program"]["id"],
        author_user_id=author_user_id,
        clearer_user_id=clearer_user_id,
    )
    env["program"] = read_pay_program(env["program"]["id"])
    return env


def setup_program_with_outreach_coverage(
    investors: Iterable[Any] = (("BlackRock", 20.00), ("Vanguard", 11.00)),
    env: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Hold one engagement per investor so outreach_coverage_pct accumulates.

    The default pair holds 20.00 and 11.00 percent holders, which rounds to an
    outreach_coverage_pct of 31.00.
    """
    if env is None or "program" not in env:
        env = setup_pay_program(env=env, **kwargs)
    windows = [
        ("2027-03-01T00:00:00Z", "2027-03-05T00:00:00Z"),
        ("2027-03-05T00:00:00Z", "2027-03-08T00:00:00Z"),
        ("2027-03-08T00:00:00Z", "2027-03-11T00:00:00Z"),
        ("2027-03-11T00:00:00Z", "2027-03-14T00:00:00Z"),
    ]
    env.setdefault("engagements", [])
    for index, (investor_name, ownership_pct) in enumerate(investors):
        window_start, window_end = windows[index % len(windows)]
        env["engagements"].append(
            run_engagement_to_held(
                env["program"]["id"], investor_name, ownership_pct, window_start, window_end
            )
        )
    env["program"] = read_pay_program(env["program"]["id"])
    return env


def setup_restatement_with_determination(
    env: Optional[Dict[str, Any]] = None,
    restated_achieved_value: float = 5.00,
    restated_metric_index: int = 0,
    order: bool = True,
    acknowledge: bool = True,
    recover: bool = False,
    event_overrides: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Full clawback chain over a VESTED award.

    Restating ADJ_EPS from 5.50 down to 5.00 drops the metric factor from 150.00
    to 100.00, the award factor from 130.00 to 100.00 and the restated amount to
    1,800,000.00, leaving recoverable_amount_usd 540,000.00.
    """
    if env is None or "awards" not in env or not env.get("awards"):
        env = setup_vested_annual_incentive_award(env=env, **kwargs)
    event = create_restatement_event(env["issuer"]["id"], **(event_overrides or {}))
    analyze_restatement(
        event["id"],
        [
            restated_metric_result(
                env["metrics"][restated_metric_index]["id"], restated_achieved_value
            )
        ],
    )
    determinations = read_determinations(restatement_event_id=event["id"])
    env["determination"] = determinations[0] if determinations else None
    if order:
        order_recovery(event["id"])
    if acknowledge and env["determination"]:
        acknowledge_determination(env["determination"]["id"], env["executives"]["CEO"]["id"])
    if recover and env["determination"]:
        recover_determination(env["determination"]["id"])
    if env["determination"]:
        env["determination"] = read_determination(env["determination"]["id"])
    env["restatement_event"] = read_restatement_event(env["issuer"]["id"], event["id"])
    return env
