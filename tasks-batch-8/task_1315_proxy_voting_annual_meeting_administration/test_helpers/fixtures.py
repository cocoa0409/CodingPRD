"""Composite setup helpers for the proxy-voting lifecycle (PRD §3).

The harness restarts the server before every test, so each helper builds its
preconditions from scratch using only PRD-declared endpoints. Setup calls use
the lenient get_success_data() so failures surface as clear setup errors.

Standard chain encoded here:
  create meeting -> create accounts -> lock record date -> create proposals
  -> generate material distributions -> open voting -> cast votes
  -> advance clock -> convene -> conclude -> create certification -> sign.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import MEETING_DATETIME
from .factories import (
    create_meeting_payload,
    create_shareholder_account_payload,
    create_proposal_payload,
    create_vote_instruction_payload,
    create_broker_search_payload,
)
from .test_users import (
    TEST_USERS,
    make_shareholder_headers,
    make_inspector_headers,
)

ADMIN = TEST_USERS["proxy_admin_headers"]
AGENT = TEST_USERS["transfer_agent_headers"]
BROKER = TEST_USERS["broker_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]


# ---------------------------------------------------------------------------
# Tier 1: state progression
# ---------------------------------------------------------------------------

def create_draft_meeting(**meeting_overrides) -> dict:
    """Create a meeting in DRAFT. Returns the meeting object."""
    resp = api_client.create_meeting(create_meeting_payload(**meeting_overrides), ADMIN)
    return get_success_data(resp)


def add_account(meeting_id, account_number="A-1001", **account_overrides) -> dict:
    """Add a shareholder account to a DRAFT meeting. Returns the account
    (including its system-minted control_number)."""
    payload = create_shareholder_account_payload(meeting_id, account_number, **account_overrides)
    resp = api_client.create_shareholder_account(payload, AGENT)
    return get_success_data(resp)


def add_proposal(meeting_id, proposal_number=1, **proposal_overrides) -> dict:
    """Create a proposal (meeting DRAFT or RECORD_DATE_LOCKED). Returns it."""
    payload = create_proposal_payload(meeting_id, proposal_number, **proposal_overrides)
    resp = api_client.create_proposal(payload, ADMIN)
    return get_success_data(resp)


def lock_record_date(meeting_id) -> dict:
    """DRAFT -> RECORD_DATE_LOCKED; accounts flip PENDING -> ELIGIBLE."""
    resp = api_client.lock_record_date(meeting_id, ADMIN)
    return get_success_data(resp)


def generate_distributions(meeting_id) -> list:
    """Generate (or regenerate) material packages. Returns the package list."""
    resp = api_client.generate_material_distributions({"meeting_id": meeting_id}, ADMIN)
    return get_success_data(resp)


def open_voting(meeting_id) -> dict:
    """MATERIALS_DISTRIBUTED -> VOTING_OPEN."""
    resp = api_client.open_voting(meeting_id, ADMIN)
    return get_success_data(resp)


def advance_clock_to_meeting(meeting_datetime: str = MEETING_DATETIME) -> None:
    """Move the logical clock to the meeting start so convene is permitted."""
    resp = api_client.set_current_utc({"to_iso8601": meeting_datetime}, ADMIN)
    get_success_data(resp)


def convene_meeting(meeting_id, meeting_datetime: str = MEETING_DATETIME) -> dict:
    """Advance the logical clock to meeting start, then convene."""
    advance_clock_to_meeting(meeting_datetime)
    resp = api_client.convene(meeting_id, ADMIN)
    return get_success_data(resp)


def conclude_meeting(meeting_id, walk_in_shares=None) -> dict:
    """MEETING_IN_PROGRESS -> MEETING_HELD (FINAL quorum must be met)."""
    payload = {} if walk_in_shares is None else {"walk_in_shares": walk_in_shares}
    resp = api_client.conclude(meeting_id, ADMIN, payload)
    return get_success_data(resp)


def current_meeting_version(meeting_id) -> int:
    """Read the meeting and return its current version (for OCC writes)."""
    resp = api_client.get_meeting(meeting_id, INSPECTOR)
    return get_success_data(resp)["version"]


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy
# ---------------------------------------------------------------------------

def setup_locked_meeting(account_specs=None, proposal_specs=None, **meeting_overrides) -> dict:
    """Meeting -> accounts -> record-date lock -> proposals.

    account_specs: list of kwargs dicts for add_account (account_number auto-
    assigned A-1001, A-1002, ... when not given). Defaults to one 6000-COMMON
    account. proposal_specs: list of kwargs dicts for add_proposal; default
    none (proposals may be created before or after the lock).
    Returns {"meeting", "accounts", "proposals"}.
    """
    meeting = create_draft_meeting(**meeting_overrides)
    if account_specs is None:
        account_specs = [{}]
    accounts = []
    for i, spec in enumerate(account_specs):
        spec = dict(spec)
        spec.setdefault("account_number", f"A-100{i + 1}")
        accounts.append(add_account(meeting["id"], **spec))
    locked = lock_record_date(meeting["id"])
    proposals = []
    for j, pspec in enumerate(proposal_specs or []):
        pspec = dict(pspec)
        pspec.setdefault("proposal_number", j + 1)
        proposals.append(add_proposal(meeting["id"], **pspec))
    return {"meeting": locked, "accounts": accounts, "proposals": proposals}


def setup_materials_distributed(account_specs=None, proposal_specs=None, **meeting_overrides) -> dict:
    """Locked meeting + proposals + first material-distribution generation.

    Meeting ends in MATERIALS_DISTRIBUTED; DRAFT proposals flip to ACTIVE.
    Returns {"meeting", "accounts", "proposals", "packages"}.
    """
    ctx = setup_locked_meeting(account_specs, proposal_specs or [{}], **meeting_overrides)
    packages = generate_distributions(ctx["meeting"]["id"])
    ctx["packages"] = packages
    resp = api_client.get_meeting(ctx["meeting"]["id"], ADMIN)
    ctx["meeting"] = get_success_data(resp)
    return ctx


def setup_voting_open(account_specs=None, proposal_specs=None, **meeting_overrides) -> dict:
    """Materials distributed + voting opened. Meeting ends in VOTING_OPEN."""
    ctx = setup_materials_distributed(account_specs, proposal_specs, **meeting_overrides)
    ctx["meeting"] = open_voting(ctx["meeting"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: vote capture and late-lifecycle shortcuts
# ---------------------------------------------------------------------------

def cast_vote(meeting_id, proposal_id, account, choice="FOR", channel="INTERNET",
              shares_voted=None, as_role="Shareholder", actor_headers=None) -> dict:
    """Cast a vote as the account's owning shareholder (or explicit headers).

    `account` is the account object; its minted control_number is threaded in
    automatically. Returns the created VoteInstruction.
    """
    payload = create_vote_instruction_payload(
        meeting_id, proposal_id, account["id"],
        channel=channel, choice=choice,
    )
    if shares_voted is not None:
        payload["shares_voted"] = shares_voted
    if channel in ("INTERNET", "PHONE", "MAIL"):
        payload["control_number"] = account["control_number"]
    headers = actor_headers if actor_headers is not None else make_shareholder_headers(account["id"])
    resp = api_client.create_vote_instruction(payload, headers)
    return get_success_data(resp)


def setup_meeting_in_progress(vote_specs=None, account_specs=None, proposal_specs=None,
                              **meeting_overrides) -> dict:
    """Voting open + votes cast + clock advanced + convened.

    vote_specs: list of {"account": int index, "choice": ..., "channel": ...,
    "shares_voted": ...} dicts; defaults to no votes. Meeting ends in
    MEETING_IN_PROGRESS. Adds "votes" to the returned context.
    """
    ctx = setup_voting_open(account_specs, proposal_specs, **meeting_overrides)
    m_id = ctx["meeting"]["id"]
    ctx["votes"] = []
    for vspec in vote_specs or []:
        vspec = dict(vspec)
        account = ctx["accounts"][vspec.pop("account", 0)]
        proposal = ctx["proposals"][vspec.pop("proposal", 0)]
        ctx["votes"].append(cast_vote(m_id, proposal["id"], account, **vspec))
    ctx["meeting"] = convene_meeting(m_id, ctx["meeting"]["meeting_datetime"])
    return ctx


def setup_meeting_held(vote_specs=None, walk_in_shares=None, account_specs=None,
                       proposal_specs=None, **meeting_overrides) -> dict:
    """Full chain through conclusion. Meeting ends in MEETING_HELD with voting
    permanently closed. Default: one 6000-COMMON account voting FOR, which
    meets the default 50% quorum (6000bp >= 5000bp)."""
    if vote_specs is None and account_specs is None:
        vote_specs = [{"account": 0, "choice": "FOR"}]
    ctx = setup_meeting_in_progress(vote_specs, account_specs, proposal_specs, **meeting_overrides)
    ctx["meeting"] = conclude_meeting(ctx["meeting"]["id"], walk_in_shares)
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: certification / terminal state
# ---------------------------------------------------------------------------

def create_certification_draft(meeting_id, creator_user_id="insp-1") -> dict:
    """Create a DRAFT inspector certification (meeting MEETING_HELD, no OPEN
    challenges). creator identity is recorded as created_by_user_id."""
    resp = api_client.create_inspector_certification(
        {"meeting_id": meeting_id}, make_inspector_headers(creator_user_id)
    )
    return get_success_data(resp)


def sign_certification(certification_id, meeting_id, signer_user_id="insp-2") -> dict:
    """Sign a DRAFT certification with a fresh OCC read of the meeting version.
    Meeting advances to RESULTS_CERTIFIED; ACTIVE proposals resolve."""
    version = current_meeting_version(meeting_id)
    resp = api_client.sign_certification(
        certification_id,
        {"expected_meeting_version": version},
        make_inspector_headers(signer_user_id),
    )
    return get_success_data(resp)


def setup_certified_meeting(vote_specs=None, account_specs=None, proposal_specs=None,
                            creator_user_id="insp-1", signer_user_id="insp-2",
                            **meeting_overrides) -> dict:
    """Full chain through certification signing. Meeting ends in
    RESULTS_CERTIFIED. Adds "certification" to the returned context."""
    ctx = setup_meeting_held(vote_specs, account_specs, proposal_specs, **meeting_overrides)
    cert = create_certification_draft(ctx["meeting"]["id"], creator_user_id)
    ctx["certification"] = sign_certification(cert["id"], ctx["meeting"]["id"], signer_user_id)
    resp = api_client.get_meeting(ctx["meeting"]["id"], ADMIN)
    ctx["meeting"] = get_success_data(resp)
    return ctx


def setup_filed_meeting(filing_reference="8-K-2026-0001", **kwargs) -> dict:
    """Full lifecycle through FILED_8K (terminal)."""
    ctx = setup_certified_meeting(**kwargs)
    resp = api_client.file_8k(ctx["meeting"]["id"], {"filing_reference": filing_reference}, ADMIN)
    ctx["meeting"] = get_success_data(resp)
    return ctx


# ---------------------------------------------------------------------------
# Broker search helpers
# ---------------------------------------------------------------------------

def add_broker_search(meeting_id, broker_code="BRK-1", **overrides) -> dict:
    """Create a broker search record (meeting RECORD_DATE_LOCKED or
    MATERIALS_DISTRIBUTED). Returns the REQUESTED record."""
    payload = create_broker_search_payload(meeting_id, broker_code, **overrides)
    resp = api_client.create_broker_search(payload, AGENT)
    return get_success_data(resp)


def respond_broker_search(search_id, shares_reported=2500) -> dict:
    """Broker answers a search; record transitions REQUESTED -> RESPONDED."""
    resp = api_client.respond_broker_search(search_id, {"shares_reported": shares_reported}, BROKER)
    return get_success_data(resp)
