"""Composite setup helpers for the IP Management API.

Every fixture builds the system into a specific state that downstream tests
need. They are the workhorses that let test functions stay focused on the
single PRD claim they are asserting.

Identity threading (PRD §2.1): For entity-backed roles (InternalAgent /
ExternalAgent), `X-User-ID` must equal the acting Agent.id. Every fixture that
operates an ownership-gated endpoint mints headers via
`make_internal_agent_headers(agent['id'])` instead of the shared fallback
constant. The shared fallback constant would always fail every ownership check
and mask the implementation's behavior.

Fixtures use `get_success_data` (lenient validator) internally so setup failures
surface as clear "Setup failed" errors, not test assertion failures.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient, api_client
from .constants import SECONDS_PER_DAY, TEST_DEFAULTS
from .factories import (
    _unique_party_id,
    advance_clock_payload,
    create_agent_payload,
    create_annual_fee_payload,
    create_business_unit_payload,
    create_contract_payload,
    create_contract_template_payload,
    create_cost_payload,
    create_evidence_payload,
    create_filing_payload,
    create_ip_right_payload,
    create_office_action_payload,
    create_protection_case_payload,
    create_royalty_schedule_payload,
    iso_in_days,
    iso_at,
    now_iso,
    parties_with_party_ids,
    register_filing_payload,
    resolve_protection_case_payload,
    route_protection_case_payload,
    sign_contract_payload,
)
from .test_users import (
    TEST_USERS,
    make_counsel_headers,
    make_external_agent_headers,
    make_finance_manager_headers,
    make_internal_agent_headers,
    make_ip_manager_headers,
)


# Re-export the canonical opaque-role header constants as module-level names so
# fixtures can read them without importing the dict each call.
ADMIN_HEADERS = TEST_USERS["admin_headers"]
IP_MANAGER_HEADERS = TEST_USERS["ip_manager_headers"]
FINANCE_MANAGER_HEADERS = TEST_USERS["finance_manager_headers"]
COUNSEL_HEADERS = TEST_USERS["counsel_headers"]


# ─────────────────────── Server-clock helpers ─────────────────────

from datetime import datetime, timedelta, timezone


def _iso_in_days_server(api: ApiClient, days: float) -> str:
    """Compute an ISO timestamp `days` after the server's CURRENT logical clock.

    PRD §3.8 lets `/_clock/advance` push the server's logical now forward
    independently of the test-process wall clock; that offset persists across
    tests in the same session, so wall-clock-relative timestamps drift out
    of the grace window for fees that were intended to be `due_in_days`
    relative to "now". This helper bounces a 0-second advance off the server
    to read its `now`, then offsets from THAT.
    """
    resp = api.advance_clock(advance_clock_payload(0), ADMIN_HEADERS)
    data = get_success_data(resp)
    server_now_str = data.get("now")
    # Parse the ISO Z-suffixed timestamp.
    if server_now_str.endswith("Z"):
        server_now = datetime.fromisoformat(server_now_str[:-1] + "+00:00")
    else:
        server_now = datetime.fromisoformat(server_now_str)
    if server_now.tzinfo is None:
        server_now = server_now.replace(tzinfo=timezone.utc)
    t = server_now + timedelta(days=days)
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


# ─────────────────────── Tier 0: primitives ───────────────────────


def create_business_unit(
    api: ApiClient,
    *,
    annual_budget_cents: int = TEST_DEFAULTS["BU_BUDGET_LARGE"],
    **overrides: Any,
) -> Dict[str, Any]:
    """Create one ACTIVE BusinessUnit (PRD §3.1)."""
    payload = create_business_unit_payload(
        annual_budget_cents=annual_budget_cents, **overrides
    )
    resp = api.create_business_unit(payload, ADMIN_HEADERS)
    return get_success_data(resp)


def archive_business_unit(api: ApiClient, bu_id: str) -> Dict[str, Any]:
    """Flip a BusinessUnit to ARCHIVED (PRD §3.1)."""
    resp = api.archive_business_unit(bu_id, {}, ADMIN_HEADERS)
    return get_success_data(resp)


def create_agent(
    api: ApiClient,
    *,
    jurisdictions: Optional[List[str]] = None,
    kind: str = "INTERNAL",
    verified: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create + (optionally) verify an Agent (PRD §3.1)."""
    payload = create_agent_payload(
        jurisdictions=list(jurisdictions or ["US"]), kind=kind, **overrides
    )
    resp = api.create_agent(payload, ADMIN_HEADERS)
    agent = get_success_data(resp)
    if verified:
        resp = api.verify_agent(agent["id"], {}, ADMIN_HEADERS)
        agent = get_success_data(resp)
    return agent


def create_contract_template(
    api: ApiClient, *, contract_type: str = "EXCLUSIVE_LICENSE"
) -> Dict[str, Any]:
    """Create one ContractTemplate (PRD §3.1)."""
    payload = create_contract_template_payload(contract_type=contract_type)
    resp = api.create_contract_template(payload, ADMIN_HEADERS)
    return get_success_data(resp)


# ─────────────────────── Tier 1: foundational scenario ───────────────────────


def setup_foundation(
    api: ApiClient,
    *,
    bu_budget: int = TEST_DEFAULTS["BU_BUDGET_LARGE"],
    agent_jurisdictions: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """One ACTIVE BU + one verified INTERNAL Agent. The base for almost every
    workflow test.

    Returns a dict with keys: business_unit, agent.
    """
    bu = create_business_unit(api, annual_budget_cents=bu_budget)
    agent = create_agent(
        api,
        jurisdictions=list(agent_jurisdictions or ["US"]),
        kind="INTERNAL",
        verified=True,
    )
    return {"business_unit": bu, "agent": agent}


# ─────────────────────── Tier 2: IPRight progression ───────────────────────


def create_ip_right_in_draft(
    api: ApiClient,
    *,
    business_unit_id: str,
    agent_id: str,
    primary_jurisdiction: str = "US",
    ip_type: str = "PATENT",
    handling_mode: str = "AGENCY",
    title: Optional[str] = None,
) -> Dict[str, Any]:
    """Create an IPRight in DRAFT under the given BU and verified Agent."""
    payload = create_ip_right_payload(
        ip_type=ip_type,
        handling_mode=handling_mode,
        assigned_agent_id=agent_id if handling_mode == "AGENCY" else None,
        business_unit_id=business_unit_id,
        primary_jurisdiction=primary_jurisdiction,
    )
    if title is not None:
        payload["title"] = title
    resp = api.create_ip_right(payload, IP_MANAGER_HEADERS)
    return get_success_data(resp)


def walk_ip_right_to_filed(
    api: ApiClient,
    *,
    business_unit_id: str,
    agent_id: str,
    primary_jurisdiction: str = "US",
    ip_type: str = "PATENT",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """DRAFT → MATERIALS_READY → FILED. Returns (ip_right, first_filing)."""
    ip = create_ip_right_in_draft(
        api,
        business_unit_id=business_unit_id,
        agent_id=agent_id,
        primary_jurisdiction=primary_jurisdiction,
        ip_type=ip_type,
    )
    resp = api.mark_materials_ready(ip["id"], {}, IP_MANAGER_HEADERS)
    ip = get_success_data(resp)
    filing_payload = create_filing_payload(
        jurisdiction=primary_jurisdiction, filed_at=now_iso()
    )
    resp = api.create_jurisdiction_filing(
        ip["id"], filing_payload, IP_MANAGER_HEADERS
    )
    filing = get_success_data(resp)
    # Re-fetch IP to surface FILED status.
    resp = api.get_ip_right(ip["id"], IP_MANAGER_HEADERS)
    ip = get_success_data(resp)
    return ip, filing


def walk_ip_right_to_registered(
    api: ApiClient,
    *,
    business_unit_id: str,
    agent_id: str,
    primary_jurisdiction: str = "US",
    ip_type: str = "PATENT",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """DRAFT → MATERIALS_READY → FILED → REGISTERED. Returns (ip_right, filing)."""
    ip, filing = walk_ip_right_to_filed(
        api,
        business_unit_id=business_unit_id,
        agent_id=agent_id,
        primary_jurisdiction=primary_jurisdiction,
        ip_type=ip_type,
    )
    resp = api.register_filing(
        filing["id"], register_filing_payload(), IP_MANAGER_HEADERS
    )
    get_success_data(resp)  # response is the parent IPRight per PRD §3.2
    resp = api.get_ip_right(ip["id"], IP_MANAGER_HEADERS)
    ip = get_success_data(resp)
    return ip, filing


def open_office_action(
    api: ApiClient,
    *,
    ip_right_id: str,
    jurisdiction_filing_id: str,
    assigned_agent_id: str,
    response_due_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Open an ApplicationOfficeAction (IP transitions FILED → OFFICE_ACTION)."""
    payload = create_office_action_payload(
        jurisdiction_filing_id=jurisdiction_filing_id,
        assigned_agent_id=assigned_agent_id,
        response_due_at=response_due_at or _iso_in_days_server(api, 30),
    )
    resp = api.create_office_action(ip_right_id, payload, IP_MANAGER_HEADERS)
    return get_success_data(resp)


# ─────────────────────── Tier 3: Contract progression ───────────────────────


def setup_contract_in_draft(
    api: ApiClient,
    *,
    ip_right_id: str,
    business_unit_id: str,
    contract_type: str = "EXCLUSIVE_LICENSE",
    royalty_rate: Optional[float] = 0.10,
    min_guarantee_cents: Optional[int] = 800_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """Create a ContractTemplate + Contract (DRAFT). Returns
    (template, contract, parties)."""
    template = create_contract_template(api, contract_type=contract_type)
    licensor_id = _unique_party_id("LICENSOR")
    licensee_id = _unique_party_id("LICENSEE")
    parties = parties_with_party_ids(licensor_id, licensee_id)
    payload = create_contract_payload(
        ip_right_id=ip_right_id,
        template_id=template["id"],
        contract_type=contract_type,
        parties=parties,
        royalty_rate=royalty_rate if contract_type != "TRANSFER" else None,
        min_guarantee_cents=(
            min_guarantee_cents if contract_type == "EXCLUSIVE_LICENSE" else None
        ),
        business_unit_id=business_unit_id,
    )
    resp = api.create_contract(payload, IP_MANAGER_HEADERS)
    contract = get_success_data(resp)
    return template, contract, parties


def walk_contract_to_signed(
    api: ApiClient,
    *,
    ip_right_id: str,
    business_unit_id: str,
    contract_type: str = "EXCLUSIVE_LICENSE",
    royalty_rate: Optional[float] = 0.10,
    min_guarantee_cents: Optional[int] = 800_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """DRAFT → SIGNING → SIGNED. Returns (template, signed_contract, parties)."""
    template, contract, parties = setup_contract_in_draft(
        api,
        ip_right_id=ip_right_id,
        business_unit_id=business_unit_id,
        contract_type=contract_type,
        royalty_rate=royalty_rate,
        min_guarantee_cents=min_guarantee_cents,
    )
    resp = api.start_signing(contract["id"], {}, IP_MANAGER_HEADERS)
    contract = get_success_data(resp)
    # Sign each signature-required party
    for p in parties:
        if not p["signature_required"]:
            continue
        resp = api.sign_contract(
            contract["id"], sign_contract_payload(p["party_id"]), IP_MANAGER_HEADERS
        )
        contract = get_success_data(resp)
    return template, contract, parties


def walk_contract_to_filed(
    api: ApiClient,
    *,
    ip_right_id: str,
    business_unit_id: str,
    contract_type: str = "EXCLUSIVE_LICENSE",
    royalty_rate: Optional[float] = 0.10,
    min_guarantee_cents: Optional[int] = 800_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """DRAFT → SIGNING → SIGNED → FILED. Requires the referenced IPRight to be
    REGISTERED — caller must arrange that. Returns (template, filed_contract,
    parties)."""
    template, contract, parties = walk_contract_to_signed(
        api,
        ip_right_id=ip_right_id,
        business_unit_id=business_unit_id,
        contract_type=contract_type,
        royalty_rate=royalty_rate,
        min_guarantee_cents=min_guarantee_cents,
    )
    resp = api.file_contract_with_authority(contract["id"], {}, IP_MANAGER_HEADERS)
    contract = get_success_data(resp)
    return template, contract, parties


# ─────────────────────── Tier 4: Annual-fee fixtures ───────────────────


def setup_registered_ip_with_annual_fee(
    api: ApiClient,
    *,
    base_fee_cents: int = TEST_DEFAULTS["BASE_FEE_DEFAULT"],
    due_in_days: float = 1.0,
    bu_budget: int = TEST_DEFAULTS["BU_BUDGET_LARGE"],
    auto_pay_authorized: bool = False,
) -> Dict[str, Any]:
    """Full ramp: BU + verified Agent + IPRight walked to REGISTERED + one
    PENDING AnnualFeeSchedule with the supplied `due_date`.

    `due_date` is computed relative to the SERVER's logical clock (PRD §3.8),
    not the test process wall clock, so prior tests that advanced the clock
    don't push the new fee outside its grace window.

    Returns: {business_unit, agent, ip_right, filing, annual_fee}.
    """
    found = setup_foundation(api, bu_budget=bu_budget)
    ip, filing = walk_ip_right_to_registered(
        api,
        business_unit_id=found["business_unit"]["id"],
        agent_id=found["agent"]["id"],
    )
    fee_payload = create_annual_fee_payload(
        base_fee_cents=base_fee_cents,
        due_date=_iso_in_days_server(api, due_in_days),
        assigned_agent_id=found["agent"]["id"],
        jurisdiction="US",
        fee_year=2,  # year-1 fee auto-created on registration; tests work on year-2
        auto_pay_authorized=auto_pay_authorized,
    )
    resp = api.create_annual_fee(ip["id"], fee_payload, FINANCE_MANAGER_HEADERS)
    annual_fee = get_success_data(resp)
    return {
        "business_unit": found["business_unit"],
        "agent": found["agent"],
        "ip_right": ip,
        "filing": filing,
        "annual_fee": annual_fee,
    }


def advance_clock_days(api: ApiClient, days: float) -> Dict[str, Any]:
    """Advance the server clock by N days (PRD §3.8)."""
    resp = api.advance_clock(
        advance_clock_payload(int(round(days * SECONDS_PER_DAY))),
        ADMIN_HEADERS,
    )
    return get_success_data(resp)


# ─────────────────────── Tier 5: ProtectionCase fixtures ─────────


def setup_protection_case_open(
    api: ApiClient,
    *,
    primary_jurisdiction: str = "US",
    agent_jurisdictions: Optional[List[str]] = None,
    walk_ip_to: str = "REGISTERED",
) -> Dict[str, Any]:
    """Foundation + IPRight walked to `walk_ip_to` + ProtectionCase in OPEN.

    walk_ip_to may be "DRAFT", "FILED", "REGISTERED" — controls how far the
    parent IPRight is taken, since some PRD §3.6 rules (LITIGATION routing,
    case-resolve) require REGISTERED.

    `agent_jurisdictions` controls the jurisdictions of the agent assigned to
    the CASE. The IPRight is always walked with an internal agent whose
    jurisdictions cover `primary_jurisdiction` so progression to REGISTERED
    succeeds — otherwise PRD §3.2's materials-ready gate
    (ERR_AGENT_JURISDICTION_MISMATCH) would block setup before the test can
    exercise the case-route rule it's actually checking.

    Returns: {business_unit, agent, ip_right, filing, case}.
    """
    # The IPRight needs an agent whose jurisdictions cover its
    # primary_jurisdiction. The case may need a DIFFERENT agent — one with the
    # supplied (possibly mismatched) jurisdictions — to exercise the
    # ERR_AGENT_JURISDICTION_MISMATCH path on /route.
    found = setup_foundation(api, agent_jurisdictions=[primary_jurisdiction])
    bu = found["business_unit"]
    ip_agent = found["agent"]

    if agent_jurisdictions is not None and primary_jurisdiction not in agent_jurisdictions:
        # Mint a second agent specifically for the case so we can exercise the
        # PRD §3.6 jurisdiction-mismatch rule on /route.
        case_agent = create_agent(
            api, kind="INTERNAL", jurisdictions=list(agent_jurisdictions)
        )
    else:
        case_agent = ip_agent

    if walk_ip_to == "DRAFT":
        ip = create_ip_right_in_draft(
            api,
            business_unit_id=bu["id"],
            agent_id=ip_agent["id"],
            primary_jurisdiction=primary_jurisdiction,
        )
        filing = None
    elif walk_ip_to == "FILED":
        ip, filing = walk_ip_right_to_filed(
            api,
            business_unit_id=bu["id"],
            agent_id=ip_agent["id"],
            primary_jurisdiction=primary_jurisdiction,
        )
    else:  # REGISTERED
        ip, filing = walk_ip_right_to_registered(
            api,
            business_unit_id=bu["id"],
            agent_id=ip_agent["id"],
            primary_jurisdiction=primary_jurisdiction,
        )

    case_payload = create_protection_case_payload(
        ip_right_id=ip["id"],
        assigned_agent_id=case_agent["id"],
        business_unit_id=bu["id"],
    )
    resp = api.create_protection_case(case_payload, COUNSEL_HEADERS)
    case = get_success_data(resp)

    return {
        "business_unit": bu,
        "agent": case_agent,
        "ip_right": ip,
        "filing": filing,
        "case": case,
    }


def add_evidence(
    api: ApiClient,
    *,
    case_id: str,
    with_chain_of_custody_hash: bool = True,
    kind: str = "DOCUMENT",
) -> Dict[str, Any]:
    """Attach one Evidence row, optionally with chain_of_custody_hash set.

    PRD §3.6: LITIGATION route requires at least one Evidence row with
    chain_of_custody_hash != null.
    """
    payload = create_evidence_payload(
        kind=kind,
        chain_of_custody_hash=("a" * 64) if with_chain_of_custody_hash else None,
    )
    resp = api.add_evidence(case_id, payload, COUNSEL_HEADERS)
    return get_success_data(resp)


def setup_case_in_progress(
    api: ApiClient,
    *,
    route: str = "LITIGATION",
    primary_jurisdiction: str = "US",
) -> Dict[str, Any]:
    """Full ramp: foundation + IPRight REGISTERED + ProtectionCase OPEN with
    Evidence (chain_of_custody_hash) → routed to IN_PROGRESS."""
    pre = setup_protection_case_open(
        api,
        primary_jurisdiction=primary_jurisdiction,
        agent_jurisdictions=[primary_jurisdiction],
        walk_ip_to="REGISTERED",
    )
    case_id = pre["case"]["id"]
    add_evidence(
        api,
        case_id=case_id,
        with_chain_of_custody_hash=(route == "LITIGATION"),
    )
    resp = api.route_protection_case(
        case_id, route_protection_case_payload(route=route), COUNSEL_HEADERS
    )
    pre["case"] = get_success_data(resp)
    return pre


# ─────────────────────── Tier 6: Royalty fixtures ─────────


def setup_contract_filed_for_royalty(
    api: ApiClient,
    *,
    contract_type: str = "EXCLUSIVE_LICENSE",
    royalty_rate: float = 0.10,
    min_guarantee_cents: Optional[int] = 800_000,
) -> Dict[str, Any]:
    """Foundation + IPRight REGISTERED + Contract walked to FILED, ready for
    /royalty-schedules.

    Returns: {business_unit, agent, ip_right, filing, template, contract,
    parties}.
    """
    found = setup_foundation(api)
    ip, filing = walk_ip_right_to_registered(
        api,
        business_unit_id=found["business_unit"]["id"],
        agent_id=found["agent"]["id"],
    )
    template, contract, parties = walk_contract_to_filed(
        api,
        ip_right_id=ip["id"],
        business_unit_id=found["business_unit"]["id"],
        contract_type=contract_type,
        royalty_rate=royalty_rate,
        min_guarantee_cents=(
            min_guarantee_cents if contract_type == "EXCLUSIVE_LICENSE" else None
        ),
    )
    return {
        "business_unit": found["business_unit"],
        "agent": found["agent"],
        "ip_right": ip,
        "filing": filing,
        "template": template,
        "contract": contract,
        "parties": parties,
    }


def create_royalty_period(
    api: ApiClient,
    *,
    contract_id: str,
    period_index: int = 1,
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
    forecast_revenue_cents: int = 10_000_000,
) -> Dict[str, Any]:
    """Create one RoyaltySchedule row."""
    payload = create_royalty_schedule_payload(
        period_index=period_index,
        period_start=period_start or iso_at(2026, 1, 1),
        period_end=period_end or iso_at(2026, 4, 1),
        forecast_revenue_cents=forecast_revenue_cents,
    )
    resp = api.create_royalty_schedule(contract_id, payload, IP_MANAGER_HEADERS)
    return get_success_data(resp)


# ─────────────────────── Tier 7: Identity headers ────────


def assigned_agent_headers(agent: Dict[str, Any]) -> Dict[str, str]:
    """For PRD §2.1 entity-backed access: an InternalAgent acts under its own
    Agent.id."""
    if agent.get("kind") == "EXTERNAL":
        return make_external_agent_headers(agent["id"])
    return make_internal_agent_headers(agent["id"])


# ─────────────────────── Tier 8: Helpers re-exported ─────


def fresh_party_id(prefix: str = "PARTY") -> str:
    """Generate a unique party_id for ad-hoc contract construction tests."""
    return _unique_party_id(prefix)
