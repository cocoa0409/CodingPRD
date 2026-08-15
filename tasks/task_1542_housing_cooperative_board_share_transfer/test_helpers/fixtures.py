"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the system to be in a state that takes 5-15
API calls to reach (cooperative + units + shareholders + ledger + approved
charge schedule + clock advancement, or the full purchase pipeline from DRAFT
to APPROVED). These helpers encapsulate those chains so tests can focus on
assertions.

All helpers use get_success_data() (lenient validator) so setup failures
surface as clear setup errors rather than confusing assertion failures.

Identity threading: every Shareholder-role call that is ownership-gated uses
make_shareholder_headers(shareholder["id"]) with the real entity id — never
the shared TEST_USERS fallback.

Logical-clock discipline: the PRD leaves a charge's exact due_date to the
server ("typically the first of the month"), so helpers that need a charge in
PAST_DUE first force issuance with a small clock tick, read the server-assigned
due_date, and only then advance the clock past due_date + grace_days. This
keeps every downstream money assertion exact regardless of the due-date choice.
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import CERTIFIER_USER_ID, DEFAULT_PANEL_IDS, DEFAULT_VOTER_IDS
from .factories import (
    create_alteration_payload,
    create_arrears_action_payload,
    create_ballot_payload,
    create_charge_schedule_payload,
    create_cooperative_payload,
    create_meeting_payload,
    create_payment_payload,
    create_purchase_application_payload,
    create_resolution_payload,
    create_schedule_interview_payload,
    create_share_ledger_entry_payload,
    create_shareholder_payload,
    create_sublet_payload,
    create_unit_payload,
    create_vote_payload,
)
from .test_users import (
    TEST_USERS,
    make_board_member_headers,
    make_managing_agent_headers,
    make_shareholder_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OFFICER = TEST_USERS["board_officer_headers"]
AGENT = TEST_USERS["managing_agent_headers"]


# ─── Time helpers ─────────────────────────────────────────────────────

def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with or without fractional digits)."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def format_iso(dt: datetime) -> str:
    """Render a datetime as an ISO 8601 UTC string for the logical clock."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ─── Tier 2: entity hierarchy ─────────────────────────────────────────

def create_cooperative(**overrides) -> dict:
    """PlatformAdmin creates a cooperative. Returns the Cooperative."""
    return get_success_data(
        api_client.create_cooperative(create_cooperative_payload(**overrides), ADMIN))


def add_unit(coop_id, unit_label="1A", shares_allocated=100) -> dict:
    """Create a unit; bumps the cooperative's total_shares and version."""
    return get_success_data(api_client.create_unit(
        coop_id, create_unit_payload(unit_label=unit_label,
                                     shares_allocated=shares_allocated),
        ADMIN))


def add_shareholder(coop_id, full_name="Pat Shareholder", email="pat@example.com") -> dict:
    """Register a shareholder (born GOOD_STANDING, arrears 0)."""
    return get_success_data(api_client.create_shareholder(
        coop_id, create_shareholder_payload(full_name=full_name, email=email), OFFICER))


def assign_shares(coop_id, unit_id, shareholder_id, shares_held) -> dict:
    """Create an ACTIVE ShareLedgerEntry linking shareholder to unit."""
    return get_success_data(api_client.create_share_ledger_entry(
        coop_id,
        create_share_ledger_entry_payload(unit_id, shareholder_id,
                                          shares_held=shares_held),
        OFFICER))


def setup_coop_with_owner(coop_overrides=None, unit_label="1A", shares_allocated=100,
                          owner_name="Pat Shareholder", owner_email="pat@example.com"):
    """Cooperative + one unit + one shareholder holding the unit's full allocation.

    Returns {"coop", "unit", "owner", "entry"}.
    """
    coop = create_cooperative(**(coop_overrides or {}))
    unit = add_unit(coop["id"], unit_label, shares_allocated)
    owner = add_shareholder(coop["id"], owner_name, owner_email)
    entry = assign_shares(coop["id"], unit["id"], owner["id"], shares_allocated)
    return {"coop": coop, "unit": unit, "owner": owner, "entry": entry}


def setup_coop_with_units(coop_overrides=None, shares_list=(100, 200, 300),
                          labels=("1A", "2B", "3C")):
    """Cooperative + N units with the given share allocations (no shareholders).

    Returns {"coop", "units"} with units in creation order.
    """
    coop = create_cooperative(**(coop_overrides or {}))
    units = [add_unit(coop["id"], labels[i], shares)
             for i, shares in enumerate(shares_list)]
    return {"coop": coop, "units": units}


def get_cooperative(coop_id) -> dict:
    return get_success_data(api_client.get_cooperative(coop_id, ADMIN))


def fresh_coop_version(coop_id) -> int:
    """Read the cooperative's current version (for OCC-guarded writes)."""
    return get_cooperative(coop_id)["version"]


def advance_clock(coop_id, to_iso8601) -> dict:
    """PlatformAdmin advances the logical clock; fires scheduled transitions."""
    return get_success_data(api_client.set_clock(coop_id, to_iso8601, ADMIN))


# ─── Tier 3: resolutions and charge-schedule lifecycle ────────────────

def open_resolution(coop_id, resolution_kind, subject_entity_kind, subject_entity_id,
                    payload_json=None, supersedes_resolution_id=None) -> dict:
    """BoardOfficer opens a resolution (OPEN, votes_required=3)."""
    overrides = {"payload_json": payload_json or {}}
    if supersedes_resolution_id is not None:
        overrides["supersedes_resolution_id"] = supersedes_resolution_id
    return get_success_data(api_client.create_resolution(
        coop_id,
        create_resolution_payload(resolution_kind, subject_entity_kind,
                                  subject_entity_id, **overrides),
        OFFICER))


def pass_resolution(coop_id, resolution_id, voter_ids=DEFAULT_VOTER_IDS) -> dict:
    """Cast len(voter_ids) FOR votes from distinct BoardMembers; returns the
    resolution after closure (PASSED when votes_for reaches votes_required)."""
    for voter_id in voter_ids:
        get_success_data(api_client.cast_vote(
            coop_id, resolution_id, create_vote_payload("FOR"),
            make_board_member_headers(voter_id)))
    return get_success_data(api_client.get_resolution(coop_id, resolution_id, OFFICER))


def create_draft_schedule(coop_id, annual_budget_cents=1200000,
                          allocation_method="PRO_RATA_SHARES", fiscal_year=2026,
                          effective_from="2026-08-01T00:00:00Z",
                          effective_to="2027-08-01T00:00:00Z") -> dict:
    """BoardOfficer creates a DRAFT schedule with a freshly observed version."""
    version = fresh_coop_version(coop_id)
    return get_success_data(api_client.create_charge_schedule(
        coop_id,
        create_charge_schedule_payload(
            version,
            annual_operating_budget_cents=annual_budget_cents,
            allocation_method=allocation_method,
            fiscal_year=fiscal_year,
            effective_from=effective_from,
            effective_to=effective_to),
        OFFICER))


def approve_schedule(coop_id, schedule_id, voter_ids=DEFAULT_VOTER_IDS):
    """Open + pass an APPROVE_SCHEDULE resolution. Returns (schedule, resolution)."""
    resolution = open_resolution(coop_id, "APPROVE_SCHEDULE", "ChargeSchedule",
                                 schedule_id)
    resolution = pass_resolution(coop_id, resolution["id"], voter_ids)
    schedule = get_success_data(
        api_client.get_charge_schedule(coop_id, schedule_id, OFFICER))
    return schedule, resolution


def setup_approved_schedule(coop_overrides=None, annual_budget_cents=1200000,
                            allocation_method="PRO_RATA_SHARES", fiscal_year=2026,
                            effective_from="2026-08-01T00:00:00Z",
                            effective_to="2027-08-01T00:00:00Z",
                            unit_label="1A", shares_allocated=100):
    """Coop + unit + owner + ledger entry + APPROVED charge schedule.

    Returns {"coop", "unit", "owner", "entry", "schedule", "schedule_resolution"}.
    """
    env = setup_coop_with_owner(coop_overrides, unit_label, shares_allocated)
    draft = create_draft_schedule(env["coop"]["id"], annual_budget_cents,
                                  allocation_method, fiscal_year,
                                  effective_from, effective_to)
    schedule, resolution = approve_schedule(env["coop"]["id"], draft["id"])
    env.update({"schedule": schedule, "schedule_resolution": resolution})
    return env


def setup_multi_unit_approved_schedule(shares_list=(100, 200, 300),
                                       labels=("1A", "2B", "3C"),
                                       coop_overrides=None,
                                       annual_budget_cents=120000000,
                                       allocation_method="PRO_RATA_SHARES",
                                       fiscal_year=2027,
                                       effective_from="2027-01-01T00:00:00Z",
                                       effective_to="2028-01-01T00:00:00Z"):
    """Coop with several units + one APPROVED schedule. No shareholders needed:
    charge generation runs per unit regardless of occupancy.

    Returns {"coop", "units", "schedule", "schedule_resolution"}.
    """
    env = setup_coop_with_units(coop_overrides, shares_list, labels)
    draft = create_draft_schedule(env["coop"]["id"], annual_budget_cents,
                                  allocation_method, fiscal_year,
                                  effective_from, effective_to)
    schedule, resolution = approve_schedule(env["coop"]["id"], draft["id"])
    env.update({"schedule": schedule, "schedule_resolution": resolution})
    return env


# ─── Maintenance charge / payment helpers ─────────────────────────────

def list_charges(coop_id, **filters) -> list:
    """List maintenance charges with exact-match filters (limit raised)."""
    filters.setdefault("limit", 100)
    data, _meta = validate_paginated(
        api_client.list_maintenance_charges(coop_id, OFFICER, params=filters))
    return data


def get_charge(coop_id, charge_id) -> dict:
    return get_success_data(api_client.get_maintenance_charge(coop_id, charge_id, OFFICER))


def charge_for_month(coop_id, billing_month, unit_id=None) -> dict:
    """Fetch the single charge for a billing month (optionally per unit)."""
    filters = {"billing_month": billing_month}
    if unit_id is not None:
        filters["unit_id"] = unit_id
    matches = list_charges(coop_id, **filters)
    assert len(matches) == 1, (
        f"Expected exactly 1 charge for billing_month={billing_month} "
        f"unit_id={unit_id}, got {len(matches)}")
    return matches[0]


def force_charge_issuance(coop_id, billing_month_start="2026-08-01T00:00:00Z"):
    """Nudge the logical clock one hour past the billing-month start so the
    month's charge is ISSUED and carries its server-assigned due_date."""
    tick = parse_iso(billing_month_start) + timedelta(hours=1)
    advance_clock(coop_id, format_iso(tick))


def make_charge_past_due(coop_id, grace_days, billing_month="2026-08", unit_id=None,
                         days_past_grace=1) -> dict:
    """Drive the given month's charge into PAST_DUE with an exact day count.

    Forces issuance first (small clock tick), reads the server-assigned
    due_date, then advances the clock to due_date + grace_days + days_past_grace
    so the charge is past due by exactly days_past_grace full days.
    Returns the refreshed charge.
    """
    force_charge_issuance(coop_id)
    charge = charge_for_month(coop_id, billing_month, unit_id)
    assert charge.get("due_date"), f"Charge {charge['id']} has no due_date after issuance"
    due = parse_iso(charge["due_date"])
    target = due + timedelta(days=grace_days + days_past_grace)
    advance_clock(coop_id, format_iso(target))
    return get_charge(coop_id, charge["id"])


def post_payment(coop_id, charge_id, shareholder_id, amount_cents) -> dict:
    """ManagingAgent posts a payment; returns the POSTED Payment."""
    return get_success_data(api_client.post_payment(
        coop_id, charge_id,
        create_payment_payload(shareholder_id, amount_cents), AGENT))


def setup_delinquent_shareholder(coop_overrides=None, annual_budget_cents=1200000,
                                 grace_days=5, days_past_grace=1):
    """Approved schedule + clock run past the grace window: the owner of the
    single unit is DELINQUENT with one PAST_DUE charge.

    Defaults to zero late fee and zero interest so the outstanding balance is
    exactly the monthly base. Returns env with extra key "charge".
    """
    overrides = {"arrears_grace_days": grace_days,
                 "arrears_late_fee_flat_cents": 0,
                 "arrears_interest_rate_bps": 0}
    overrides.update(coop_overrides or {})
    env = setup_approved_schedule(overrides,
                                  annual_budget_cents=annual_budget_cents)
    charge = make_charge_past_due(env["coop"]["id"], grace_days=grace_days,
                                  days_past_grace=days_past_grace)
    env["charge"] = charge
    env["owner"] = get_success_data(
        api_client.get_shareholder(env["coop"]["id"], env["owner"]["id"], OFFICER))
    return env


def get_shareholder(coop_id, shareholder_id) -> dict:
    return get_success_data(api_client.get_shareholder(coop_id, shareholder_id, OFFICER))


def find_shareholder_by_email(coop_id, email):
    """Locate a shareholder by email via the nested list endpoint."""
    data, _meta = validate_paginated(
        api_client.list_shareholders(coop_id, OFFICER, params={"limit": 100}))
    matches = [s for s in data if s.get("email") == email]
    return matches[0] if matches else None


def issue_arrears_action(coop_id, shareholder_id, action_type) -> dict:
    """BoardOfficer issues an ArrearsAction (ISSUED)."""
    return get_success_data(api_client.create_arrears_action(
        coop_id, create_arrears_action_payload(shareholder_id, action_type), OFFICER))


# ─── Tier 3: purchase application lifecycle ───────────────────────────

def create_purchase_app(coop_id, unit_id, seller_id, **overrides) -> dict:
    """Seller drafts a purchase application (DRAFT). Ownership-gated."""
    return get_success_data(api_client.create_purchase_application(
        coop_id, create_purchase_application_payload(unit_id, seller_id, **overrides),
        make_shareholder_headers(seller_id)))


def submit_purchase_app(coop_id, app_id, seller_id) -> dict:
    return get_success_data(api_client.submit_purchase_application(
        coop_id, app_id, make_shareholder_headers(seller_id)))


def certify_purchase_app(coop_id, app_id, agent_user_id=CERTIFIER_USER_ID) -> dict:
    return get_success_data(api_client.certify_purchase_application(
        coop_id, app_id, make_managing_agent_headers(agent_user_id)))


def schedule_interview_for_app(coop_id, app_id, scheduled_at="2026-08-15T14:00:00Z",
                               panel=DEFAULT_PANEL_IDS) -> dict:
    """BoardOfficer schedules the interview; returns the SCHEDULED Interview."""
    return get_success_data(api_client.schedule_interview(
        coop_id, app_id,
        create_schedule_interview_payload(scheduled_at=scheduled_at,
                                          panel_member_user_ids=list(panel)),
        OFFICER))


def complete_interview(coop_id, interview_id, outcome="FAVORABLE",
                       panel_user_id=DEFAULT_PANEL_IDS[0],
                       advance_to="2026-08-15T15:00:00Z") -> dict:
    """Advance the clock to/after scheduled_at, then a panel member records
    the outcome. Returns the COMPLETED Interview."""
    advance_clock(coop_id, advance_to)
    return get_success_data(api_client.complete_interview(
        coop_id, interview_id, {"interview_outcome": outcome},
        make_board_member_headers(panel_user_id)))


def setup_application_under_review(coop_overrides=None, app_overrides=None,
                                   shares_allocated=100):
    """Env + purchase application certified into UNDER_REVIEW.

    Returns {"coop", "unit", "owner", "entry", "app"}.
    """
    env = setup_coop_with_owner(coop_overrides, shares_allocated=shares_allocated)
    app = create_purchase_app(env["coop"]["id"], env["unit"]["id"],
                              env["owner"]["id"], **(app_overrides or {}))
    submit_purchase_app(env["coop"]["id"], app["id"], env["owner"]["id"])
    app = certify_purchase_app(env["coop"]["id"], app["id"])
    env["app"] = app
    return env


def setup_application_interview_scheduled(coop_overrides=None, app_overrides=None,
                                          shares_allocated=100,
                                          scheduled_at="2026-08-15T14:00:00Z",
                                          panel=DEFAULT_PANEL_IDS):
    """Env + application INTERVIEW_SCHEDULED. Adds "interview" to the env."""
    env = setup_application_under_review(coop_overrides, app_overrides, shares_allocated)
    interview = schedule_interview_for_app(env["coop"]["id"], env["app"]["id"],
                                           scheduled_at=scheduled_at, panel=panel)
    env["interview"] = interview
    env["app"] = get_success_data(api_client.get_purchase_application(
        env["coop"]["id"], env["app"]["id"], OFFICER))
    return env


def setup_application_approved(coop_overrides=None, app_overrides=None,
                               shares_allocated=100,
                               panel=DEFAULT_PANEL_IDS,
                               voter_ids=DEFAULT_VOTER_IDS):
    """Full pipeline: DRAFT -> SUBMITTED -> UNDER_REVIEW -> INTERVIEW_SCHEDULED
    -> FAVORABLE interview -> APPROVE_PURCHASE resolution PASSED -> APPROVED.

    Returns env with "app" (APPROVED), "interview", "approval_resolution".
    """
    env = setup_application_interview_scheduled(coop_overrides, app_overrides,
                                                shares_allocated, panel=panel)
    env["interview"] = complete_interview(env["coop"]["id"], env["interview"]["id"],
                                          outcome="FAVORABLE", panel_user_id=panel[0])
    resolution = open_resolution(env["coop"]["id"], "APPROVE_PURCHASE",
                                 "PurchaseApplication", env["app"]["id"])
    resolution = pass_resolution(env["coop"]["id"], resolution["id"], voter_ids)
    env["approval_resolution"] = resolution
    env["app"] = get_success_data(api_client.get_purchase_application(
        env["coop"]["id"], env["app"]["id"], OFFICER))
    assert env["app"]["application_status"] == "APPROVED", (
        f"Setup failed: application not APPROVED "
        f"({env['app']['application_status']})")
    return env


def record_transfer(coop_id, app_id) -> dict:
    """BoardOfficer records the transfer with a freshly observed cooperative
    version. Returns the TRANSFERRED PurchaseApplication."""
    version = fresh_coop_version(coop_id)
    return get_success_data(api_client.record_transfer(
        coop_id, app_id, {"expected_cooperative_version": version}, OFFICER))


# ─── Sublet / alteration helpers ──────────────────────────────────────

def create_sublet(coop_id, unit_id, shareholder_id, start_date, end_date,
                  subtenant_name="Sam Subtenant") -> dict:
    """Owner drafts a sublet (DRAFT). Ownership-gated."""
    return get_success_data(api_client.create_sublet_agreement(
        coop_id,
        create_sublet_payload(unit_id, shareholder_id,
                              subtenant_name=subtenant_name,
                              sublet_start_date=start_date,
                              sublet_end_date=end_date),
        make_shareholder_headers(shareholder_id)))


def submit_sublet(coop_id, sublet_id, shareholder_id) -> dict:
    return get_success_data(api_client.submit_sublet(
        coop_id, sublet_id, make_shareholder_headers(shareholder_id)))


def approve_sublet(coop_id, sublet_id, voter_ids=DEFAULT_VOTER_IDS) -> dict:
    """Open + pass an APPROVE_SUBLET resolution. Returns the APPROVED sublet."""
    resolution = open_resolution(coop_id, "APPROVE_SUBLET", "SubletAgreement",
                                 sublet_id)
    pass_resolution(coop_id, resolution["id"], voter_ids)
    return get_success_data(api_client.get_sublet_agreement(coop_id, sublet_id, OFFICER))


def setup_completed_sublet(coop_overrides=None, shares_allocated=100,
                           first_window=("2026-09-01T00:00:00Z",
                                         "2027-09-01T00:00:00Z")):
    """Walk a first sublet through SUBMITTED -> APPROVED -> ACTIVE -> COMPLETED
    by driving the logical clock through its window, so the unit's
    last_sublet_end_date is set and the gap rule becomes testable.

    Returns env with "sublet1" (COMPLETED) and refreshed "unit".
    """
    overrides = {"sublet_policy_years_max": 2, "sublet_policy_gap_years": 1}
    overrides.update(coop_overrides or {})
    env = setup_coop_with_owner(overrides, shares_allocated=shares_allocated)
    coop_id = env["coop"]["id"]
    sub1 = create_sublet(coop_id, env["unit"]["id"], env["owner"]["id"],
                         first_window[0], first_window[1], subtenant_name="First Tenant")
    submit_sublet(coop_id, sub1["id"], env["owner"]["id"])
    sub1 = approve_sublet(coop_id, sub1["id"])
    # Drive the clock into the window (activates), then past its end (completes).
    mid_window = parse_iso(first_window[0]) + timedelta(days=30)
    advance_clock(coop_id, format_iso(mid_window))
    after_end = parse_iso(first_window[1]) + timedelta(days=30)
    advance_clock(coop_id, format_iso(after_end))
    env["sublet1"] = get_success_data(
        api_client.get_sublet_agreement(coop_id, sub1["id"], OFFICER))
    env["unit"] = get_success_data(api_client.get_unit(coop_id, env["unit"]["id"], OFFICER))
    return env


def create_alteration(coop_id, unit_id, shareholder_id, window_start, window_end,
                      **overrides) -> dict:
    """Owner drafts an alteration (DRAFT). Ownership-gated."""
    return get_success_data(api_client.create_alteration_agreement(
        coop_id,
        create_alteration_payload(unit_id, shareholder_id,
                                  work_window_start=window_start,
                                  work_window_end=window_end, **overrides),
        make_shareholder_headers(shareholder_id)))


def submit_alteration(coop_id, alteration_id, shareholder_id) -> dict:
    return get_success_data(api_client.submit_alteration(
        coop_id, alteration_id, make_shareholder_headers(shareholder_id)))


def approve_alteration(coop_id, alteration_id, payload_json=None,
                       voter_ids=DEFAULT_VOTER_IDS) -> dict:
    """Open + pass an APPROVE_ALTERATION resolution. Returns the APPROVED alteration."""
    resolution = open_resolution(coop_id, "APPROVE_ALTERATION", "AlterationAgreement",
                                 alteration_id, payload_json=payload_json)
    pass_resolution(coop_id, resolution["id"], voter_ids)
    return get_success_data(
        api_client.get_alteration_agreement(coop_id, alteration_id, OFFICER))


# ─── Meeting / ballot helpers ─────────────────────────────────────────

def setup_meeting_env(coop_overrides=None, shares_list=(100,)):
    """Cooperative + one unit per share allocation, each with an owning
    shareholder holding the unit's full allocation.

    Returns {"coop", "units", "owners"} (parallel lists, creation order).
    """
    overrides = {"annual_meeting_quorum_percent_bps": 5000}
    overrides.update(coop_overrides or {})
    coop = create_cooperative(**overrides)
    units, owners = [], []
    for i, shares in enumerate(shares_list):
        unit = add_unit(coop["id"], f"U{i + 1}", shares)
        owner = add_shareholder(coop["id"], f"Owner {i + 1}",
                                f"owner{i + 1}@example.com")
        assign_shares(coop["id"], unit["id"], owner["id"], shares)
        units.append(unit)
        owners.append(owner)
    return {"coop": coop, "units": units, "owners": owners}


def create_meeting(coop_id, meeting_kind="ANNUAL",
                   scheduled_at="2026-08-20T18:00:00Z") -> dict:
    """BoardOfficer schedules a meeting (SCHEDULED/PREPARING/QUORUM_PENDING)."""
    return get_success_data(api_client.create_meeting(
        coop_id, create_meeting_payload(meeting_kind=meeting_kind,
                                        scheduled_at=scheduled_at),
        OFFICER))


def send_notice(coop_id, meeting_id) -> dict:
    return get_success_data(api_client.send_meeting_notice(coop_id, meeting_id, OFFICER))


def open_meeting(coop_id, meeting_id, open_at="2026-08-20T18:30:00Z") -> dict:
    """Advance the clock to/after scheduled_at, then open (IN_SESSION)."""
    advance_clock(coop_id, open_at)
    return get_success_data(api_client.open_meeting(coop_id, meeting_id, OFFICER))


def setup_meeting_in_session(coop_overrides=None, shares_list=(100,),
                             scheduled_at="2026-08-20T18:00:00Z",
                             open_at="2026-08-20T18:30:00Z"):
    """Meeting env with notice sent and the meeting opened (IN_SESSION).

    Returns {"coop", "units", "owners", "meeting"}.
    """
    env = setup_meeting_env(coop_overrides, shares_list)
    meeting = create_meeting(env["coop"]["id"], scheduled_at=scheduled_at)
    send_notice(env["coop"]["id"], meeting["id"])
    meeting = open_meeting(env["coop"]["id"], meeting["id"], open_at=open_at)
    env["meeting"] = meeting
    return env


def cast_ballot(coop_id, meeting_id, shareholder_id, candidates=("cand-1",),
                ballot_kind="IN_PERSON") -> dict:
    """Shareholder casts a ballot. Ownership-gated. Returns the Ballot."""
    return get_success_data(api_client.cast_ballot(
        coop_id, meeting_id,
        create_ballot_payload(shareholder_id, ballot_kind=ballot_kind,
                              candidate_user_ids=list(candidates)),
        make_shareholder_headers(shareholder_id)))


def get_meeting(coop_id, meeting_id) -> dict:
    return get_success_data(api_client.get_meeting(coop_id, meeting_id, OFFICER))
