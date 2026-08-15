"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: Agent/BusinessManager/Publicist calls are entity-backed by
TeamMember, and Artist calls are entity-backed by Artist. Every workspace dict
carries per-instance headers built from the real entity ids via the make_*
builders; ownership-gated calls never fall back to the shared constants.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    DEFAULT_RATE_PROFILES,
    DEFAULT_TERM_END,
    DEFAULT_TERM_START,
)
from .factories import (
    create_advance_payload,
    create_agreement_payload,
    create_artist_payload,
    create_dispute_payload,
    create_engagement_payload,
    create_expense_payload,
    create_income_event_payload,
    create_opportunity_payload,
    create_option_payload,
    create_rate_schedule_payload,
    create_team_member_payload,
    generate_statement_payload,
    issue_findings_payload,
    resolve_dispute_payload,
    settle_payload,
)
from .test_users import (
    TEST_USERS,
    make_agent_headers,
    make_artist_headers,
    make_business_manager_headers,
    make_publicist_headers,
)

ADMIN = TEST_USERS["firm_admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def create_artist(stage_name="Test Act", legal_name=None, primary_genre="pop",
                  home_currency=None):
    """Create an artist (born ACTIVE, version 1). Returns the artist."""
    payload = create_artist_payload(
        stage_name=stage_name,
        legal_name=legal_name or f"{stage_name} LLC",
        primary_genre=primary_genre,
    )
    if home_currency is not None:
        payload["home_currency"] = home_currency
    return get_success_data(api_client.create_artist(payload, ADMIN))


def add_team_member(artist_id, member_role="AGENT", display_name="Member",
                    authority_cap=None, window_start="2026-01-01", window_end=None):
    """Assign a team member (born ACTIVE). Returns the member."""
    payload = create_team_member_payload(
        artist_id, member_role=member_role, display_name=display_name,
        window_start_date=window_start,
    )
    if authority_cap is not None:
        payload["authority_expense_cap_cents"] = authority_cap
    if window_end is not None:
        payload["window_end_date"] = window_end
    return get_success_data(api_client.create_team_member(payload, ADMIN))


def create_draft_agreement(artist, term_start=DEFAULT_TERM_START,
                           term_end=DEFAULT_TERM_END, touring_commission_base=None,
                           recoupment_policy=None):
    """Create a DRAFT agreement, threading the artist's current version (OCC)."""
    payload = create_agreement_payload(artist["id"], artist["version"],
                                       term_start_date=term_start,
                                       term_end_date=term_end)
    if touring_commission_base is not None:
        payload["touring_commission_base"] = touring_commission_base
    if recoupment_policy is not None:
        payload["recoupment_policy"] = recoupment_policy
    return get_success_data(api_client.create_agreement(payload, ADMIN))


def add_rate_schedule(agreement_id, income_type="TOURING", in_term_bps=None,
                      sunset_bps=None, sunset_months=None,
                      effective_from="2026-01-01", effective_to=None):
    """Create an effective-dated rate schedule. Defaults per income type."""
    default_in, default_sun, default_months = DEFAULT_RATE_PROFILES[income_type]
    payload = create_rate_schedule_payload(
        agreement_id,
        income_type=income_type,
        in_term_rate_bps=in_term_bps if in_term_bps is not None else default_in,
        sunset_rate_bps=sunset_bps if sunset_bps is not None else default_sun,
        sunset_months=sunset_months if sunset_months is not None else default_months,
        effective_from_date=effective_from,
    )
    if effective_to is not None:
        payload["effective_to_date"] = effective_to
    return get_success_data(api_client.create_rate_schedule(payload, ADMIN))


def activate_agreement(agreement_id):
    return get_success_data(api_client.activate_agreement(agreement_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: the artist workspace (artist + agreement + rates + team)
# ---------------------------------------------------------------------------

def setup_artist_team(stage_name="Test Act", primary_genre="pop",
                          income_types=("TOURING",), rates=None,
                          term_start=DEFAULT_TERM_START, term_end=DEFAULT_TERM_END,
                          touring_commission_base=None, recoupment_policy=None,
                          create_agreement=True, activate=True,
                          with_agent=True, with_bm=True, bm_cap=None):
    """Artist + DRAFT/ACTIVE agreement + rate schedules + agent/BM members.

    Returns a dict: artist, agreement, schedules, agent, bm, and per-instance
    headers (admin_headers, auditor_headers, agent_headers, bm_headers,
    artist_headers).
    """
    artist = create_artist(stage_name=stage_name, primary_genre=primary_genre)
    sc = {
        "artist": artist,
        "agreement": None,
        "schedules": {},
        "agent": None,
        "bm": None,
        "admin_headers": ADMIN,
        "auditor_headers": AUDITOR,
        "agent_headers": None,
        "bm_headers": None,
        "artist_headers": make_artist_headers(artist["id"]),
    }
    if create_agreement:
        agreement = create_draft_agreement(
            artist, term_start=term_start, term_end=term_end,
            touring_commission_base=touring_commission_base,
            recoupment_policy=recoupment_policy,
        )
        sc["agreement"] = agreement
        for income_type in income_types:
            profile = (rates or {}).get(income_type, DEFAULT_RATE_PROFILES[income_type])
            sc["schedules"][income_type] = add_rate_schedule(
                agreement["id"], income_type=income_type,
                in_term_bps=profile[0], sunset_bps=profile[1], sunset_months=profile[2],
            )
        if activate:
            sc["agreement"] = activate_agreement(agreement["id"])
    if with_agent:
        sc["agent"] = add_team_member(artist["id"], "AGENT", f"Agent {stage_name}")
        sc["agent_headers"] = make_agent_headers(sc["agent"]["id"])
    if with_bm:
        kwargs = {"authority_cap": bm_cap} if bm_cap is not None else {}
        sc["bm"] = add_team_member(artist["id"], "BUSINESS_MANAGER",
                                   f"BM {stage_name}", **kwargs)
        sc["bm_headers"] = make_business_manager_headers(sc["bm"]["id"])
    return sc


def refresh_artist(sc):
    """Re-GET the artist and update the workspace copy. Returns the artist."""
    sc["artist"] = get_success_data(
        api_client.get_artist(sc["artist"]["id"], sc["admin_headers"]))
    return sc["artist"]


def refresh_agreement(sc):
    sc["agreement"] = get_success_data(
        api_client.get_agreement(sc["agreement"]["id"], sc["admin_headers"]))
    return sc["agreement"]


# ---------------------------------------------------------------------------
# Tier 3: income events (report / verify / settle)
# ---------------------------------------------------------------------------

def report_event(sc, gross_amount_cents=100000, recognition_date="2026-03-10",
                 income_type="TOURING", source_name="Promoter",
                 linked_engagement_id=None, kind=None, parent_event_id=None,
                 reporter="agent"):
    """Report an income event (born REPORTED). reporter: 'agent' or 'bm'."""
    payload = create_income_event_payload(
        sc["artist"]["id"],
        income_type=income_type,
        gross_amount_cents=gross_amount_cents,
        recognition_date=recognition_date,
        source_name=source_name,
    )
    if linked_engagement_id is not None:
        payload["linked_engagement_id"] = linked_engagement_id
    if kind is not None:
        payload["kind"] = kind
    if parent_event_id is not None:
        payload["parent_event_id"] = parent_event_id
    headers = sc["agent_headers"] if reporter == "agent" else sc["bm_headers"]
    return get_success_data(api_client.create_income_event(payload, headers))


def verify_event(sc, event_id, verifier="bm"):
    headers = sc["bm_headers"] if verifier == "bm" else sc["agent_headers"]
    return get_success_data(api_client.verify_income_event(event_id, headers))


def settle_event(sc, event_id, received_date="2026-03-12", received_amount_cents=None):
    payload = settle_payload(received_date=received_date,
                             received_amount_cents=received_amount_cents)
    return get_success_data(api_client.settle_income_event(event_id, payload,
                                                           sc["bm_headers"]))


def create_and_verify_event(sc, gross_amount_cents=100000,
                            recognition_date="2026-03-10", income_type="TOURING",
                            source_name="Promoter", linked_engagement_id=None):
    """Report (as agent) + verify (as BM). Returns the VERIFIED event."""
    event = report_event(sc, gross_amount_cents, recognition_date, income_type,
                         source_name, linked_engagement_id=linked_engagement_id)
    return verify_event(sc, event["id"])


def create_verified_and_settled_event(sc, gross_amount_cents=100000,
                                      recognition_date="2026-03-10",
                                      received_date="2026-03-12",
                                      received_amount_cents=None,
                                      income_type="TOURING", source_name="Promoter"):
    """Report + verify + settle. Returns the settled event."""
    event = create_and_verify_event(sc, gross_amount_cents, recognition_date,
                                    income_type, source_name)
    return settle_event(sc, event["id"], received_date,
                        received_amount_cents or gross_amount_cents)


# ---------------------------------------------------------------------------
# Tier 3: advances
# ---------------------------------------------------------------------------

def issue_advance(sc, principal_cents=50000, issued_date="2026-01-05",
                  recoup_pct_bps=None, applies_to_income_types=None):
    payload = create_advance_payload(sc["artist"]["id"],
                                     principal_cents=principal_cents,
                                     issued_date=issued_date)
    if recoup_pct_bps is not None:
        payload["recoup_pct_bps"] = recoup_pct_bps
    if applies_to_income_types is not None:
        payload["applies_to_income_types"] = applies_to_income_types
    return get_success_data(api_client.create_advance(payload, sc["bm_headers"]))


def get_advance(sc, advance_id):
    return get_success_data(api_client.get_advance(advance_id, sc["bm_headers"]))


# ---------------------------------------------------------------------------
# Tier 3: expenses + approval requests
# ---------------------------------------------------------------------------

def file_expense(sc, amount_cents=5000, category="OTHER", incurred_date="2026-07-01",
                 description="Test expense", engagement_id=None, filer="agent"):
    payload = create_expense_payload(
        sc["artist"]["id"], category=category, amount_cents=amount_cents,
        incurred_date=incurred_date, description=description,
    )
    if engagement_id is not None:
        payload["engagement_id"] = engagement_id
    headers = sc["agent_headers"] if filer == "agent" else sc["bm_headers"]
    return get_success_data(api_client.create_expense(payload, headers))


def list_requests_for_target(sc, target_id, status=None):
    params = {"artist_id": sc["artist"]["id"], "target_id": target_id}
    if status is not None:
        params["status"] = status
    data, _meta = validate_paginated(
        api_client.list_approval_requests(sc["bm_headers"] or sc["admin_headers"],
                                          params=params))
    return data


def approve_all_pending_for_target(sc, target_id):
    """Approve every PENDING request for a target using the matching role:
    BUSINESS_MANAGER requests by the workspace BM, ARTIST requests by the
    artist themself, FIRM_ADMIN requests by the firm admin."""
    for req in list_requests_for_target(sc, target_id):
        if req["status"] != "PENDING":
            continue
        approver = req["required_approver"]
        if approver == "BUSINESS_MANAGER":
            headers = sc["bm_headers"]
        elif approver == "ARTIST":
            headers = sc["artist_headers"]
        else:
            headers = sc["admin_headers"]
        get_success_data(api_client.approve_request(req["id"], headers))


def create_approved_expense(sc, amount_cents, category="PRODUCTION",
                            incurred_date="2026-02-10", description="Expense",
                            engagement_id=None):
    """File (as agent) + approve every routed request. Returns APPROVED expense."""
    expense = file_expense(sc, amount_cents, category=category,
                           incurred_date=incurred_date, description=description,
                           engagement_id=engagement_id)
    approve_all_pending_for_target(sc, expense["id"])
    return get_success_data(api_client.get_expense(expense["id"], sc["bm_headers"]))


# ---------------------------------------------------------------------------
# Tier 3: opportunities / engagements / options
# ---------------------------------------------------------------------------

def create_opportunity(sc, proposed_value_cents=5000000, income_type="TOURING",
                       counterparty_name="FestCo", offer_expiry_date="2026-12-31",
                       window=("2026-10-01T00:00:00Z", "2026-10-02T00:00:00Z"),
                       fit_score=60):
    payload = create_opportunity_payload(
        sc["artist"]["id"], income_type=income_type,
        counterparty_name=counterparty_name,
        proposed_value_cents=proposed_value_cents,
        offer_expiry_date=offer_expiry_date,
        proposed_window_start=window[0], proposed_window_end=window[1],
        fit_score=fit_score,
    )
    return get_success_data(api_client.create_opportunity(payload, sc["agent_headers"]))


def evaluate_opportunity(sc, opportunity_id):
    return get_success_data(
        api_client.evaluate_opportunity(opportunity_id, sc["agent_headers"]))


def negotiate_opportunity(sc, opportunity_id):
    return get_success_data(
        api_client.negotiate_opportunity(opportunity_id, sc["agent_headers"]))


def create_evaluated_opportunity(sc, **kwargs):
    """Create + evaluate. Returns the UNDER_EVALUATION opportunity."""
    opp = create_opportunity(sc, **kwargs)
    return evaluate_opportunity(sc, opp["id"])


def create_negotiating_opportunity(sc, **kwargs):
    """Create + evaluate + negotiate. Returns the NEGOTIATING opportunity."""
    opp = create_evaluated_opportunity(sc, **kwargs)
    return negotiate_opportunity(sc, opp["id"])


def create_hold_engagement(sc, start="2026-09-10T18:00:00Z",
                           end="2026-09-10T23:00:00Z", buffer_hours=0,
                           guarantee_cents=100000, income_type="TOURING",
                           counterparty_name="Venue", opportunity_id=None):
    payload = create_engagement_payload(
        sc["artist"]["id"], income_type=income_type,
        counterparty_name=counterparty_name, start_datetime=start,
        end_datetime=end, guarantee_cents=guarantee_cents,
        travel_buffer_hours=buffer_hours,
    )
    if opportunity_id is not None:
        payload["opportunity_id"] = opportunity_id
    return get_success_data(api_client.create_engagement(payload, sc["agent_headers"]))


def confirm_engagement(sc, engagement_id):
    return get_success_data(api_client.confirm_engagement(engagement_id,
                                                          sc["agent_headers"]))


def create_confirmed_engagement(sc, **kwargs):
    hold = create_hold_engagement(sc, **kwargs)
    return confirm_engagement(sc, hold["id"])


def create_option(sc, window=("2026-07-01T00:00:00Z", "2026-09-01T00:00:00Z"),
                  engagement_window=("2027-03-01T20:00:00Z", "2027-03-01T23:00:00Z"),
                  option_type="TOUR_LEG", income_type="TOURING",
                  exercise_value_cents=500000, source_opportunity_id=None):
    payload = create_option_payload(
        sc["artist"]["id"], sc["agreement"]["id"],
        option_type=option_type, income_type=income_type,
        exercise_window_start=window[0], exercise_window_end=window[1],
        engagement_start_datetime=engagement_window[0],
        engagement_end_datetime=engagement_window[1],
        exercise_value_cents=exercise_value_cents,
    )
    if source_opportunity_id is not None:
        payload["source_opportunity_id"] = source_opportunity_id
    return get_success_data(api_client.create_option(payload, sc["agent_headers"]))


# ---------------------------------------------------------------------------
# Tier 4: statements
# ---------------------------------------------------------------------------

def generate_statement(sc, period_start="2026-01-01", period_end="2026-03-31",
                       basis="ACCRUAL"):
    payload = generate_statement_payload(sc["artist"]["id"],
                                         period_start_date=period_start,
                                         period_end_date=period_end, basis=basis)
    return get_success_data(api_client.generate_statement(payload, sc["bm_headers"]))


def issue_statement(sc, statement_id):
    return get_success_data(api_client.issue_statement(statement_id, sc["bm_headers"]))


def get_statement(sc, statement_id):
    return get_success_data(api_client.get_statement(statement_id, sc["bm_headers"]))


def generate_and_issue_statement(sc, period_start="2026-01-01",
                                 period_end="2026-03-31", basis="ACCRUAL"):
    statement = generate_statement(sc, period_start, period_end, basis)
    return issue_statement(sc, statement["id"])


def setup_issued_statement_with_event(sc, gross_amount_cents=200000,
                                      recognition_date="2026-03-10",
                                      period=("2026-01-01", "2026-03-31"),
                                      basis="ACCRUAL", income_type="TOURING"):
    """Verified event swept onto an issued statement. Returns (statement, event)."""
    event = create_and_verify_event(sc, gross_amount_cents, recognition_date,
                                    income_type)
    statement = generate_and_issue_statement(sc, period[0], period[1], basis)
    return statement, event


# ---------------------------------------------------------------------------
# Tier 4: disputes / audits
# ---------------------------------------------------------------------------

def open_dispute(sc, statement_id, reason="OTHER", claimed_amount_cents=1000):
    payload = create_dispute_payload(sc["artist"]["id"], statement_id,
                                     reason=reason,
                                     claimed_amount_cents=claimed_amount_cents)
    return get_success_data(api_client.create_dispute(payload, sc["artist_headers"]))


def resolve_dispute(sc, dispute_id, outcome="UPHELD", awarded_amount_cents=None,
                    resolution_note=None):
    payload = resolve_dispute_payload(outcome)
    if awarded_amount_cents is not None:
        payload["awarded_amount_cents"] = awarded_amount_cents
    if resolution_note is not None:
        payload["resolution_note"] = resolution_note
    return get_success_data(api_client.resolve_dispute(dispute_id, payload,
                                                       sc["bm_headers"]))


def demand_audit(sc, statement_id):
    payload = {"artist_id": sc["artist"]["id"], "scope_statement_id": statement_id}
    return get_success_data(api_client.create_audit(payload, sc["artist_headers"]))


def begin_audit(audit_id):
    return get_success_data(api_client.begin_audit(audit_id, AUDITOR))


def issue_audit_findings(audit_id, findings_underpayment_cents=0, audit_cost_cents=0):
    payload = issue_findings_payload(findings_underpayment_cents, audit_cost_cents)
    return get_success_data(api_client.issue_findings(audit_id, payload, AUDITOR))


def reopen_audit(sc, audit_id):
    return get_success_data(api_client.reopen_audit(audit_id, sc["artist_headers"]))


# ---------------------------------------------------------------------------
# Tier 5: clock
# ---------------------------------------------------------------------------

def advance_clock(to_iso8601):
    """Advance the logical clock (FirmAdmin). Returns the sweep count dict."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))
