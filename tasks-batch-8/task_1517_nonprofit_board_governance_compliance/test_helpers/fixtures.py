"""Composite setup helpers.

Every fixture builds preconditions from scratch via PRD-declared endpoints (the
harness restarts the server before each test, so each test starts empty).
Setup calls use get_success_data() so failures surface as clear setup errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_amendment_payload,
    create_appointment_payload,
    create_bylaws_payload,
    create_committee_payload,
    create_disclosure_payload,
    create_evaluation_payload,
    create_filing_payload,
    create_meeting_payload,
    create_member_payload,
    create_motion_payload,
    create_nonprofit_payload,
    create_policy_payload,
    create_registration_payload,
    create_succession_plan_payload,
    create_term_payload,
    make_scores,
)
from .test_users import (
    TEST_USERS,
    headers_for_member,
    make_board_chair_headers,
)

ADMIN = TEST_USERS["governance_admin_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]

DEFAULT_TERM_START = "2026-01-01T00:00:00Z"
DEFAULT_MEETING_START = "2026-08-01T00:00:00Z"


# ---------------------------------------------------------------- clock / org

def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def sweep(nonprofit_id, as_officer=False):
    headers = OFFICER if as_officer else ADMIN
    return get_success_data(api_client.compliance_sweep(nonprofit_id, headers))


def create_nonprofit(name="Org", ein="EIN-1", state="CA", fye_month=12,
                     receipts=4_000_000_000):
    payload = create_nonprofit_payload(
        name=name, ein=ein, state_of_incorporation=state,
        fiscal_year_end_month=fye_month, annual_gross_receipts_cents=receipts,
    )
    return get_success_data(api_client.create_nonprofit(payload, ADMIN))


def create_adopted_bylaws(nonprofit_id, **overrides):
    bylaws = get_success_data(api_client.create_bylaws(
        create_bylaws_payload(nonprofit_id, **overrides), ADMIN))
    return get_success_data(api_client.adopt_bylaws(bylaws["id"], ADMIN))


def create_board_member(nonprofit_id, name, email, skills=None, officer_role=None,
                        is_independent=None):
    overrides = {}
    if skills is not None:
        overrides["skill_tags"] = skills
    if officer_role is not None:
        overrides["officer_role"] = officer_role
    if is_independent is not None:
        overrides["is_independent"] = is_independent
    return get_success_data(api_client.create_board_member(
        create_member_payload(nonprofit_id, name, email, **overrides), ADMIN))


def elect_member(nonprofit_id, member_id, start_date=DEFAULT_TERM_START):
    """Elect a member via GovernanceAdmin; returns the created term."""
    return get_success_data(api_client.create_board_term(
        create_term_payload(nonprofit_id, member_id, start_date=start_date), ADMIN))


_MEMBER_SKILL_CYCLE = ["GOVERNANCE", "FINANCE", "LEGAL", "PROGRAM", "HR",
                       "MARKETING", "TECHNOLOGY", "FUNDRAISING"]


def setup_org_with_board(num_directors=1, officers=("CHAIR",), bylaws=None,
                         receipts=4_000_000_000, fye_month=12,
                         term_start=DEFAULT_TERM_START, ein="EIN-1", name="Org"):
    """Org + adopted bylaws + members, all elected to ACTIVE terms.

    officers holds the officer_role per leading member (e.g. ("CHAIR", "TREASURER"));
    remaining members are plain directors. Returns a dict with the org, bylaws,
    chair (first CHAIR officer, else None), treasurer likewise, and members list.
    """
    nonprofit = create_nonprofit(name=name, ein=ein, fye_month=fye_month, receipts=receipts)
    bylaws_doc = create_adopted_bylaws(nonprofit["id"], **(bylaws or {}))
    members = []
    total = len(officers) + num_directors
    for i in range(total):
        officer_role = officers[i] if i < len(officers) else None
        member = create_board_member(
            nonprofit["id"], f"M{i}", f"m{i}@{ein.lower()}.org",
            skills=[_MEMBER_SKILL_CYCLE[i % len(_MEMBER_SKILL_CYCLE)]],
            officer_role=officer_role,
        )
        elect_member(nonprofit["id"], member["id"], start_date=term_start)
        member = get_success_data(api_client.get_board_member(member["id"], ADMIN))
        members.append(member)
    chair = next((m for m in members if m["officer_role"] == "CHAIR"), None)
    treasurer = next((m for m in members if m["officer_role"] == "TREASURER"), None)
    return {
        "nonprofit": nonprofit,
        "bylaws": bylaws_doc,
        "members": members,
        "chair": chair,
        "treasurer": treasurer,
    }


# -------------------------------------------------------------------- COI

def file_coi(nonprofit_id, member, fiscal_year=2026, answers=None):
    """Self-service disclosure filing by the member themself."""
    payload = create_disclosure_payload(nonprofit_id, member["id"], fiscal_year)
    if answers is not None:
        payload["answers"] = answers
    return get_success_data(api_client.file_disclosure(payload, headers_for_member(member)))


def review_disclosure(disclosure_id, reviewer):
    """Start review as the reviewer, then clear. Returns the cleared disclosure."""
    headers = headers_for_member(reviewer)
    get_success_data(api_client.start_review(disclosure_id, headers))
    return get_success_data(api_client.clear_disclosure(disclosure_id, headers))


def file_and_clear_coi(nonprofit_id, member, reviewer, fiscal_year=2026, answers=None):
    disclosure = file_coi(nonprofit_id, member, fiscal_year=fiscal_year, answers=answers)
    return review_disclosure(disclosure["id"], reviewer)


def clear_coi_for_all(nonprofit_id, members, fiscal_year=2026):
    """Every member files; each is reviewed+cleared by the next member in the ring."""
    disclosures = [file_coi(nonprofit_id, m, fiscal_year=fiscal_year) for m in members]
    for i, disclosure in enumerate(disclosures):
        reviewer = members[(i + 1) % len(members)]
        review_disclosure(disclosure["id"], reviewer)
    return disclosures


# --------------------------------------------------------------- committees

def create_committee(nonprofit_id, name="Gov Cttee", type="GOVERNANCE",
                     min_members=1, authorized_size=3, requires_all_independent=None,
                     via=None):
    overrides = {"type": type, "min_members": min_members, "authorized_size": authorized_size}
    if requires_all_independent is not None:
        overrides["requires_all_independent"] = requires_all_independent
    headers = via if via is not None else ADMIN
    return get_success_data(api_client.create_committee(
        create_committee_payload(nonprofit_id, name, **overrides), headers))


def appoint(nonprofit_id, committee_id, member, chair, committee_role=None):
    overrides = {}
    if committee_role is not None:
        overrides["committee_role"] = committee_role
    return get_success_data(api_client.create_appointment(
        create_appointment_payload(nonprofit_id, committee_id, member["id"], **overrides),
        make_board_chair_headers(chair["id"])))


def setup_active_committee(nonprofit_id, chair, appointees, name="Cttee",
                           type="GOVERNANCE", min_members=1, authorized_size=3):
    """CHARTERED committee + all appointees appointed + activated -> ACTIVE.

    Every appointee must already hold a CLEARED/RESTRICTIONS_IMPOSED current-FY
    disclosure (call clear_coi_for_all first).
    """
    committee = create_committee(nonprofit_id, name=name, type=type,
                                 min_members=min_members, authorized_size=authorized_size)
    appointments = [appoint(nonprofit_id, committee["id"], m, chair) for m in appointees]
    committee = get_success_data(api_client.activate_committee(
        committee["id"], make_board_chair_headers(chair["id"])))
    return committee, appointments


# ----------------------------------------------------------------- meetings

def create_meeting(nonprofit_id, start=DEFAULT_MEETING_START, duration=60,
                   committee_id=None, notice_waived=True, notice_sent_at=None,
                   via=None):
    overrides = {"scheduled_start": start, "duration_minutes": duration,
                 "notice_waived": notice_waived}
    if committee_id is not None:
        overrides["committee_id"] = committee_id
    if notice_sent_at is not None:
        overrides["notice_sent_at"] = notice_sent_at
    headers = via if via is not None else ADMIN
    return get_success_data(api_client.create_meeting(
        create_meeting_payload(nonprofit_id, **overrides), headers))


def call_to_order(meeting_id, chair, attendance_ids):
    return get_success_data(api_client.call_to_order(
        meeting_id, {"attendance": attendance_ids}, make_board_chair_headers(chair["id"])))


def setup_meeting_in_session(nonprofit_id, chair, attendee_ids, **meeting_kw):
    meeting = create_meeting(nonprofit_id, **meeting_kw)
    return call_to_order(meeting["id"], chair, attendee_ids)


# ------------------------------------------------------------------ motions

def introduce_motion(nonprofit_id, meeting_id, introducer, title="Motion",
                     category="GOVERNANCE", **kw):
    payload = create_motion_payload(nonprofit_id, meeting_id, title=title,
                                    category=category, **kw)
    return get_success_data(api_client.create_motion(payload, headers_for_member(introducer)))


def setup_open_motion(nonprofit_id, meeting_id, chair, **motion_kw):
    motion = introduce_motion(nonprofit_id, meeting_id, chair, **motion_kw)
    return get_success_data(api_client.open_voting(
        motion["id"], make_board_chair_headers(chair["id"])))


def cast_vote(nonprofit_id, motion_id, member, choice):
    return get_success_data(api_client.cast_vote(
        {"nonprofit_id": nonprofit_id, "motion_id": motion_id,
         "board_member_id": member["id"], "choice": choice},
        headers_for_member(member)))


def setup_voting_scenario(num_members=2, category="GOVERNANCE", motion_kw=None,
                          bylaws=None, meeting_start=DEFAULT_MEETING_START,
                          receipts=4_000_000_000, ein="EIN-1"):
    """Org + board + meeting IN_SESSION with all members present + motion VOTING_OPEN."""
    scenario = setup_org_with_board(
        num_directors=num_members - 1, officers=("CHAIR",),
        bylaws=bylaws, receipts=receipts, ein=ein)
    np_id = scenario["nonprofit"]["id"]
    chair = scenario["chair"]
    member_ids = [m["id"] for m in scenario["members"]]
    meeting = setup_meeting_in_session(np_id, chair, member_ids, start=meeting_start)
    motion = setup_open_motion(np_id, meeting["id"], chair, category=category,
                               **(motion_kw or {}))
    scenario.update({"meeting": meeting, "motion": motion})
    return scenario


# ---------------------------------------------------------- bylaws amendment

def create_proposed_amendment(nonprofit_id, bylaws_id, chair, title="Amendment",
                              proposed_fields=None):
    amendment = get_success_data(api_client.create_amendment(
        create_amendment_payload(nonprofit_id, bylaws_id, title=title,
                                 proposed_fields=proposed_fields or {"quorum_pct": 60}),
        make_board_chair_headers(chair["id"])))
    return get_success_data(api_client.propose_amendment(
        amendment["id"], make_board_chair_headers(chair["id"])))


def setup_amendment_motion_open(num_members=6, board_size=8, amendment_threshold_pct=67,
                                quorum_pct=50, proposed_fields=None, title="Amend",
                                ein="EIN-1"):
    """Org + board + PROPOSED amendment + meeting IN_SESSION + BYLAWS motion VOTING_OPEN."""
    scenario = setup_org_with_board(
        num_directors=num_members - 1, officers=("CHAIR",),
        bylaws={"board_size": board_size, "quorum_pct": quorum_pct,
                "amendment_threshold_pct": amendment_threshold_pct},
        ein=ein)
    np_id = scenario["nonprofit"]["id"]
    chair = scenario["chair"]
    amendment = create_proposed_amendment(
        np_id, scenario["bylaws"]["id"], chair, title=title,
        proposed_fields=proposed_fields)
    member_ids = [m["id"] for m in scenario["members"]]
    meeting = setup_meeting_in_session(np_id, chair, member_ids, duration=120)
    motion = setup_open_motion(np_id, meeting["id"], chair, title="Adopt amendment",
                               category="BYLAWS", bylaws_amendment_id=amendment["id"])
    scenario.update({"amendment": amendment, "meeting": meeting, "motion": motion})
    return scenario


# -------------------------------------------------------------- evaluations

def create_evaluation(nonprofit_id, chair, fiscal_year=2026, executive_name="ED"):
    return get_success_data(api_client.create_evaluation(
        create_evaluation_payload(nonprofit_id, fiscal_year,
                                  executive_name=executive_name),
        make_board_chair_headers(chair["id"])))


def patch_scores(evaluation_id, recorder, scores):
    """PATCH scores as the recorder, reading the current version first (OCC)."""
    current = get_success_data(api_client.get_evaluation(evaluation_id, ADMIN))
    return get_success_data(api_client.patch_scores(
        evaluation_id,
        {"expected_evaluation_version": current["version"], "scores": scores},
        headers_for_member(recorder)))


def setup_evaluation_scored(nonprofit_id, chair, scores, fiscal_year=2026):
    evaluation = create_evaluation(nonprofit_id, chair, fiscal_year=fiscal_year)
    return patch_scores(evaluation["id"], chair, scores)


def setup_evaluation_in_review(nonprofit_id, chair, scores, fiscal_year=2026):
    evaluation = setup_evaluation_scored(nonprofit_id, chair, scores, fiscal_year)
    return get_success_data(api_client.submit_evaluation_review(
        evaluation["id"], make_board_chair_headers(chair["id"])))


# ------------------------------------------------------------------ filings

def create_filing(nonprofit_id, creator, fiscal_year, preparer="staff-1",
                  supersedes_filing_id=None, **amount_overrides):
    payload = create_filing_payload(nonprofit_id, fiscal_year,
                                    preparer_user_id=preparer, **amount_overrides)
    if supersedes_filing_id is not None:
        payload["supersedes_filing_id"] = supersedes_filing_id
    return get_success_data(api_client.create_filing(payload, headers_for_member(creator)))


def record_review(filing_id, member):
    return get_success_data(api_client.record_review(filing_id, headers_for_member(member)))


def setup_filing_in_review(nonprofit_id, creator, fiscal_year, preparer="staff-1",
                           supersedes_filing_id=None, **amount_overrides):
    filing = create_filing(nonprofit_id, creator, fiscal_year, preparer=preparer,
                           supersedes_filing_id=supersedes_filing_id, **amount_overrides)
    return get_success_data(api_client.submit_filing_for_review(
        filing["id"], headers_for_member(creator)))


def setup_filing_approved(nonprofit_id, creator, chair, reviewers, fiscal_year,
                          preparer="staff-1", supersedes_filing_id=None, **amount_overrides):
    """Create -> submit -> exactly review_required_count distinct reviews -> approve."""
    filing = setup_filing_in_review(nonprofit_id, creator, fiscal_year, preparer=preparer,
                                    supersedes_filing_id=supersedes_filing_id,
                                    **amount_overrides)
    required = filing["review_required_count"]
    assert len(reviewers) >= required, "reviewer pool smaller than review_required_count"
    for member in reviewers[:required]:
        record_review(filing["id"], member)
    return get_success_data(api_client.approve_filing(
        filing["id"], make_board_chair_headers(chair["id"])))


def setup_filing_filed(nonprofit_id, creator, chair, reviewers, fiscal_year,
                       preparer="staff-1", supersedes_filing_id=None, **amount_overrides):
    filing = setup_filing_approved(nonprofit_id, creator, chair, reviewers, fiscal_year,
                                   preparer=preparer,
                                   supersedes_filing_id=supersedes_filing_id,
                                   **amount_overrides)
    return get_success_data(api_client.mark_filed(
        filing["id"], headers_for_member(creator)))


# ------------------------------------------------------- registrations/insurance

def create_registration(nonprofit_id, state_code="CA",
                        current_period_end="2027-06-01T00:00:00Z", contributions=None,
                        renewal_cycle_months=None):
    overrides = {}
    if contributions is not None:
        overrides["contributions_in_state_cents"] = contributions
    if renewal_cycle_months is not None:
        overrides["renewal_cycle_months"] = renewal_cycle_months
    return get_success_data(api_client.create_registration(
        create_registration_payload(nonprofit_id, state_code, current_period_end,
                                    **overrides),
        OFFICER))


def create_policy(nonprofit_id, policy_type="DNO", coverage=1_000_000_000,
                  premium=100_000, start="2026-01-01T00:00:00Z",
                  end="2027-01-01T00:00:00Z", prior_policy_id=None,
                  acknowledge_gap=None, carrier="Carrier1"):
    overrides = {"policy_type": policy_type, "carrier": carrier,
                 "coverage_limit_cents": coverage, "premium_cents": premium,
                 "policy_start_date": start, "policy_end_date": end}
    if prior_policy_id is not None:
        overrides["prior_policy_id"] = prior_policy_id
    if acknowledge_gap is not None:
        overrides["acknowledge_gap"] = acknowledge_gap
    return get_success_data(api_client.create_policy(
        create_policy_payload(nonprofit_id, **overrides), OFFICER))


def bind_policy(policy_id):
    return get_success_data(api_client.bind_policy(policy_id, OFFICER))


def activate_policy(policy_id):
    return get_success_data(api_client.activate_policy(policy_id, OFFICER))


def cancel_policy(policy_id):
    return get_success_data(api_client.cancel_policy(policy_id, OFFICER))


def setup_active_dno(nonprofit_id, coverage=1_000_000_000,
                     start="2026-01-01T00:00:00Z", end="2027-01-01T00:00:00Z"):
    policy = create_policy(nonprofit_id, coverage=coverage, start=start, end=end)
    bind_policy(policy["id"])
    return activate_policy(policy["id"])


# ------------------------------------------------------------------ succession

def create_succession_plan(nonprofit_id, creator, target_role="EXECUTIVE_DIRECTOR",
                           readiness="READY_NOW", **overrides):
    payload = create_succession_plan_payload(
        nonprofit_id, target_role=target_role, readiness=readiness, **overrides)
    return get_success_data(api_client.create_succession_plan(
        payload, headers_for_member(creator)))


def approve_plan(plan_id, chair):
    return get_success_data(api_client.approve_plan(
        plan_id, make_board_chair_headers(chair["id"])))
