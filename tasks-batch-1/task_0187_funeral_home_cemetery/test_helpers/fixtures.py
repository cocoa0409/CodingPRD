"""Composite setup helpers.

Most interesting test claims require the system to be driven through several
API calls to reach the state under test. These helpers encapsulate those
multi-step preambles so test bodies focus on the trigger + assertions.

All setup calls use get_success_data() (lenient 2xx validator) so a broken
precondition surfaces as a clear "Setup failed" rather than a confusing
assertion later. Every helper builds its preconditions from scratch — the
server starts against an empty database before each test.

Role identity model is OPAQUE (PRD §2.1): X-User-ID is never matched against
an entity id, so shared role headers are safe for ownership-free calls. Where
segregation of duties is exercised, the caller passes explicit headers built
via test_users.make_headers().
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_headers
from . import factories as f


ADMIN = TEST_USERS["admin_headers"]
ARRANGER = TEST_USERS["arranger_headers"]
TRUST = TEST_USERS["trust_officer_headers"]
CLERK = TEST_USERS["cemetery_clerk_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


# --------------------------------------------------------------------------
# Tier 1 / 2: establishment + catalog primitives
# --------------------------------------------------------------------------
def create_funeral_home(**overrides) -> dict:
    """Create a funeral home (Admin). Returns the FuneralHome object."""
    resp = api_client.create_funeral_home(f.create_funeral_home_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_gpl_item(home_id, **overrides) -> dict:
    """Create a GPL catalog item (Admin). Returns the GplItem object."""
    resp = api_client.create_gpl_item(
        f.create_gpl_item_payload(home_id, **overrides), ADMIN)
    return get_success_data(resp)


def create_plot(home_id, **overrides) -> dict:
    """Create an AVAILABLE plot. Returns the Plot object."""
    resp = api_client.create_plot(f.create_plot_payload(home_id, **overrides), CLERK)
    return get_success_data(resp)


def create_venue(home_id, **overrides) -> dict:
    """Create a venue (Admin). Returns the Venue object."""
    resp = api_client.create_venue(f.create_venue_payload(home_id, **overrides), ADMIN)
    return get_success_data(resp)


def create_case(home_id, arranger_headers=ARRANGER, **overrides) -> dict:
    """Open a case (Arranger). Returns the Case object."""
    resp = api_client.create_case(
        f.create_case_payload(home_id, **overrides), arranger_headers)
    return get_success_data(resp)


# --------------------------------------------------------------------------
# Tier 1: case state progression
# --------------------------------------------------------------------------
def create_disclosed_case(home_id, arranger_headers=ARRANGER, **case_overrides) -> dict:
    """Open a case and acknowledge the FTC disclosure (INTAKE -> DISCLOSED).
    Returns the Case after acknowledgement."""
    case = create_case(home_id, arranger_headers=arranger_headers, **case_overrides)
    resp = api_client.acknowledge_disclosure(case["id"], arranger_headers)
    return get_success_data(resp)


def add_line(case_id, gpl_item_id, arranger_headers=ARRANGER, **overrides) -> dict:
    """Add a statement line to a disclosed case. Returns the StatementLine."""
    resp = api_client.add_statement_line(
        case_id, f.add_statement_line_payload(gpl_item_id, **overrides), arranger_headers)
    return get_success_data(resp)


def select_line(case_id, line_id, arranger_headers=ARRANGER) -> dict:
    resp = api_client.select_statement_line(case_id, line_id, arranger_headers)
    return get_success_data(resp)


def create_contract(case_id, funding_type, arranger_headers=ARRANGER) -> dict:
    """Create the single contract for a case. Returns the Contract."""
    resp = api_client.create_contract(
        case_id, f.create_contract_payload(funding_type), arranger_headers)
    return get_success_data(resp)


# --------------------------------------------------------------------------
# Tier 2: case with a non-declinable line + contract, ready to issue GFS
# --------------------------------------------------------------------------
def setup_case_with_nondeclinable_line_and_contract(
    funding_type="AT_NEED_DIRECT",
    case_mode="AT_NEED",
    svc_price=100000,
    home_overrides=None,
    arranger_headers=ARRANGER,
):
    """Disclosed case + one non-declinable SERVICE line (auto-SELECTED) +
    a contract. Returns (home, case, svc_item, contract).

    A non-declinable line is created already SELECTED (PRD §3.3), so the
    statement is non-empty and GFS issuance can proceed.
    """
    home = create_funeral_home(**(home_overrides or {}))
    svc = create_gpl_item(
        home["id"], code="SVC-BASIC", name="Basic services", category="SERVICE",
        taxable=False, non_declinable=True, preneed_trustable=True,
        unit_price_cents=svc_price)
    case_kwargs = {"case_mode": case_mode}
    if case_mode == "PRENEED":
        case_kwargs["date_of_death"] = None
    case = create_disclosed_case(home["id"], arranger_headers=arranger_headers, **case_kwargs)
    add_line(case["id"], svc["id"], arranger_headers=arranger_headers)
    contract = create_contract(case["id"], funding_type, arranger_headers=arranger_headers)
    return home, case, svc, contract


def setup_arranged_case(
    funding_type="AT_NEED_DIRECT",
    case_mode="AT_NEED",
    svc_price=100000,
    home_overrides=None,
    arranger_headers=ARRANGER,
):
    """Drive a case to ARRANGED (GFS issued) with a non-declinable SERVICE
    line and a contract. Returns (home, case_after_gfs, svc_item, contract)."""
    home, case, svc, contract = setup_case_with_nondeclinable_line_and_contract(
        funding_type=funding_type, case_mode=case_mode, svc_price=svc_price,
        home_overrides=home_overrides, arranger_headers=arranger_headers)
    resp = api_client.issue_gfs(case["id"], arranger_headers)
    case = get_success_data(resp)
    return home, case, svc, contract


# --------------------------------------------------------------------------
# Tier 3 / 4: funding lifecycle shortcuts
# --------------------------------------------------------------------------
def post_principal(contract_id, amount_cents, trust_headers=TRUST) -> dict:
    resp = api_client.post_trust_deposit(
        contract_id, f.trust_deposit_payload("PRINCIPAL", amount_cents), trust_headers)
    return get_success_data(resp)


def post_earnings(contract_id, amount_cents, trust_headers=TRUST) -> dict:
    resp = api_client.post_trust_deposit(
        contract_id, f.trust_deposit_payload("EARNINGS", amount_cents), trust_headers)
    return get_success_data(resp)


def submit_for_funding(contract_id, arranger_headers=ARRANGER) -> dict:
    resp = api_client.submit_for_funding(contract_id, arranger_headers)
    return get_success_data(resp)


def current_contract_version(contract_id, headers=TRUST) -> int:
    resp = api_client.get_contract(contract_id, headers)
    return get_success_data(resp)["version"]


def setup_contract_pending_funding(
    funding_type="AT_NEED_DIRECT",
    case_mode="AT_NEED",
    svc_price=100000,
    principal_cents=None,
    earnings_cents=None,
    home_overrides=None,
    arranger_headers=ARRANGER,
    trust_headers=TRUST,
):
    """Drive a contract to PENDING_FUNDING after posting optional deposits.
    Returns (home, case, svc_item, contract). The returned contract reflects
    its state after submit-for-funding (re-fetch for the live version)."""
    home, case, svc, contract = setup_arranged_case(
        funding_type=funding_type, case_mode=case_mode, svc_price=svc_price,
        home_overrides=home_overrides, arranger_headers=arranger_headers)
    if principal_cents is not None:
        post_principal(contract["id"], principal_cents, trust_headers=trust_headers)
    if earnings_cents is not None:
        post_earnings(contract["id"], earnings_cents, trust_headers=trust_headers)
    submit_for_funding(contract["id"], arranger_headers=arranger_headers)
    resp = api_client.get_contract(contract["id"], trust_headers)
    contract = get_success_data(resp)
    return home, case, svc, contract


def setup_funded_contract(
    funding_type="AT_NEED_DIRECT",
    case_mode="AT_NEED",
    svc_price=100000,
    principal_cents=100000,
    home_overrides=None,
    arranger_headers=ARRANGER,
    trust_headers=TRUST,
):
    """Drive a contract all the way to FUNDED (deposits cover contract_amount,
    distinct disclosure/funding identities). Returns (home, case, svc, contract)."""
    home, case, svc, contract = setup_contract_pending_funding(
        funding_type=funding_type, case_mode=case_mode, svc_price=svc_price,
        principal_cents=principal_cents, home_overrides=home_overrides,
        arranger_headers=arranger_headers, trust_headers=trust_headers)
    c_v = current_contract_version(contract["id"], trust_headers)
    resp = api_client.mark_funded(
        contract["id"], f.mark_funded_payload(c_v), trust_headers)
    contract = get_success_data(resp)
    return home, case, svc, contract


# --------------------------------------------------------------------------
# Tier 1: plot reservation
# --------------------------------------------------------------------------
def reserve_plot(plot_id, case_id, expected_version, clerk_headers=CLERK) -> dict:
    resp = api_client.reserve_plot(
        plot_id, f.reserve_plot_payload(case_id, expected_version), clerk_headers)
    return get_success_data(resp)


def setup_reserved_plot(home_id, case_id, clerk_headers=CLERK, **plot_overrides):
    """Create an AVAILABLE plot and reserve it for the given case.
    Returns (plot_after_reserve)."""
    plot = create_plot(home_id, **plot_overrides)
    return reserve_plot(plot["id"], case_id, plot["version"], clerk_headers=clerk_headers)


# --------------------------------------------------------------------------
# Tier 1: permit issuance path
# --------------------------------------------------------------------------
def apply_permit(case_id, permit_type, headers=REGISTRAR) -> dict:
    resp = api_client.apply_permit(case_id, f.apply_permit_payload(permit_type), headers)
    return get_success_data(resp)


def issue_permit(permit_id, reference_number, headers=REGISTRAR) -> dict:
    resp = api_client.issue_permit(
        permit_id, f.issue_permit_payload(reference_number), headers)
    return get_success_data(resp)


def setup_case_interment_ready(home_id, case_id):
    """Apply + issue both DEATH_CERTIFICATE and BURIAL_TRANSIT permits so the
    case bubbles to interment_status READY (PRD §3.7).
    Returns (dc_permit, bt_permit)."""
    dc = apply_permit(case_id, "DEATH_CERTIFICATE")
    issue_permit(dc["id"], "DC-1")
    bt = apply_permit(case_id, "BURIAL_TRANSIT")
    bt = issue_permit(bt["id"], "BT-1")
    return dc, bt


# --------------------------------------------------------------------------
# Tier 2/3: insurance assignment
# --------------------------------------------------------------------------
def attach_assignment(contract_id, assigned_value_cents=100000, trust_headers=TRUST) -> dict:
    resp = api_client.attach_insurance_assignment(
        contract_id, f.insurance_assignment_payload(assigned_value_cents), trust_headers)
    return get_success_data(resp)


# --------------------------------------------------------------------------
# Tier 1: chapel event scheduling
# --------------------------------------------------------------------------
def schedule_chapel(case_id, venue_id, starts_at, ends_at, arranger_headers=ARRANGER) -> dict:
    resp = api_client.create_event(
        case_id,
        f.create_event_payload("CHAPEL", venue_id, starts_at, ends_at=ends_at),
        arranger_headers)
    return get_success_data(resp)


def schedule_graveside(case_id, plot_id, starts_at, arranger_headers=ARRANGER) -> dict:
    resp = api_client.create_event(
        case_id,
        f.create_event_payload("GRAVESIDE", plot_id, starts_at),
        arranger_headers)
    return get_success_data(resp)
