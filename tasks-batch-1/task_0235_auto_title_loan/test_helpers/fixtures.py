"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the system to be walked through 5-15 API calls to
reach a specific state (originated loan, delinquent loan, defaulted loan with a
repossession order recovered after grace, etc.). These helpers encapsulate those
preambles so test functions can focus on assertions.

All helpers use get_success_data() (lenient validator) internally so a setup
failure surfaces as a clear "Setup failed" error rather than a confusing
assertion failure deep in a test.

Segregation of duties: the Appraiser who finalizes an appraisal and the
Underwriter who approves the resulting application must have DIFFERENT X-User-IDs.
These helpers always finalize as a fixed Appraiser id and approve as a fixed,
distinct Underwriter id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CA_PROFILE,
    VA_PROFILE,
    DEFAULT_PRINCIPAL_CENTS,
    DEFAULT_CONTRACT_APR_BPS,
    DEFAULT_TERM_MONTHS,
)
from .factories import (
    create_regulatory_profile_payload,
    create_borrower_payload,
    create_vehicle_payload,
    create_appraisal_payload,
    create_application_payload,
    create_payment_payload,
    create_renewal_payload,
    create_title_lien_file_payload,
    create_repossession_order_payload,
    create_assignment_payload,
    create_sale_payload,
    create_device_payload,
    create_device_command_payload,
)
from .test_users import (
    TEST_USERS,
    make_appraiser_headers,
    make_underwriter_headers,
)

# Fixed, distinct identities so segregation of duties is satisfied by default.
APPRAISER_ID = "fixture-appraiser"
UNDERWRITER_ID = "fixture-underwriter"

_ADMIN = TEST_USERS["compliance_admin_headers"]
_UW = TEST_USERS["underwriter_headers"]
_APPR = TEST_USERS["appraiser_headers"]
_SERVICER = TEST_USERS["loan_servicer_headers"]
_RECOVERY = TEST_USERS["recovery_manager_headers"]
_CLERK = TEST_USERS["title_clerk_headers"]

# Default canonical clock instants reused across the design indices.
CLOCK_ORIGIN = "2026-01-01T00:00:00.000Z"
CLOCK_PAST_DUE = "2026-03-15T00:00:00.000Z"   # seq1 (due ~01-31) + seq2 (due ~03-02) past due


# ─── Clock helper ─────────────────────────────────────────────────────────
def set_clock(to_iso8601: str):
    """Set the server clock as ComplianceAdmin. Returns the echoed body."""
    return get_success_data(api_client.set_clock(to_iso8601, _ADMIN))


# ─── Tier 0: profile / borrower / vehicle ─────────────────────────────────
def ensure_profile(profile_overrides=None):
    """Create one regulatory profile (CA by default). Returns the profile."""
    payload = create_regulatory_profile_payload(**(profile_overrides or {}))
    return get_success_data(api_client.create_regulatory_profile(payload, _ADMIN))


def create_borrower(**overrides):
    return get_success_data(api_client.create_borrower(create_borrower_payload(**overrides), _UW))


def create_vehicle(borrower_id, **overrides):
    return get_success_data(
        api_client.create_vehicle(create_vehicle_payload(borrower_id, **overrides), _APPR)
    )


# ─── Tier 1: appraisal lifecycle ──────────────────────────────────────────
def create_draft_appraisal(vehicle_id, **overrides):
    return get_success_data(
        api_client.create_appraisal(create_appraisal_payload(vehicle_id, **overrides), _APPR)
    )


def create_finalized_appraisal(vehicle_id, appraiser_id=APPRAISER_ID, **overrides):
    """Create a DRAFT appraisal and finalize it as a specific Appraiser id."""
    appraisal = create_draft_appraisal(vehicle_id, **overrides)
    finalized = get_success_data(
        api_client.finalize_appraisal(appraisal["id"], make_appraiser_headers(appraiser_id))
    )
    return finalized


def setup_finalized_appraisal(profile_overrides=None, appraisal_overrides=None,
                              borrower_overrides=None, appraiser_id=APPRAISER_ID):
    """profile + borrower + vehicle + finalized appraisal.

    Returns (profile, borrower, vehicle, appraisal).
    """
    profile = ensure_profile(profile_overrides)
    borrower = create_borrower(**(borrower_overrides or {}))
    vehicle = create_vehicle(borrower["id"])
    appraisal = create_finalized_appraisal(
        vehicle["id"], appraiser_id=appraiser_id, **(appraisal_overrides or {})
    )
    return profile, borrower, vehicle, appraisal


# ─── Tier 2: application lifecycle ────────────────────────────────────────
def create_submitted_application(borrower_id, appraisal_id, **overrides):
    return get_success_data(
        api_client.create_application(
            create_application_payload(borrower_id, appraisal_id, **overrides), _UW
        )
    )


def setup_submitted_application(profile_overrides=None, appraisal_overrides=None,
                                application_overrides=None, appraiser_id=APPRAISER_ID):
    """profile + borrower + vehicle + finalized appraisal + SUBMITTED application.

    Returns (borrower, vehicle, appraisal, application).
    """
    profile, borrower, vehicle, appraisal = setup_finalized_appraisal(
        profile_overrides, appraisal_overrides, appraiser_id=appraiser_id
    )
    application = create_submitted_application(
        borrower["id"], appraisal["id"], **(application_overrides or {})
    )
    return borrower, vehicle, appraisal, application


def setup_originated_loan(profile_overrides=None, appraisal_overrides=None,
                          application_overrides=None, with_clock_origin=True,
                          appraiser_id=APPRAISER_ID, underwriter_id=UNDERWRITER_ID):
    """Full origination: optionally set the clock to origin, then
    profile -> borrower -> vehicle -> finalized appraisal -> SUBMITTED application
    -> approve -> Loan (OUTSTANDING/CURRENT).

    Returns dict with profile, borrower, vehicle, appraisal, application, loan.
    """
    if with_clock_origin:
        set_clock(CLOCK_ORIGIN)
    profile = ensure_profile(profile_overrides)
    borrower = create_borrower()
    vehicle = create_vehicle(borrower["id"])
    appraisal = create_finalized_appraisal(
        vehicle["id"], appraiser_id=appraiser_id, **(appraisal_overrides or {})
    )
    application = create_submitted_application(
        borrower["id"], appraisal["id"], **(application_overrides or {})
    )
    # Approval acts on the application and returns the (now APPROVED) application
    # (PRD §2.2: operations return the modified resource; the endpoint targets the
    # application). The originated Loan is fetched by reverse reference — Loans can
    # be listed filtered by application_id (PRD §3.4).
    application = get_success_data(
        api_client.approve_application(application["id"], make_underwriter_headers(underwriter_id))
    )
    loan = loan_for_application(application["id"])
    return {
        "profile": profile,
        "borrower": borrower,
        "vehicle": vehicle,
        "appraisal": appraisal,
        "application": application,
        "loan": loan,
    }


# ─── Tier 3: device installation ──────────────────────────────────────────
def install_device(vehicle_id, **overrides):
    return get_success_data(
        api_client.create_device(create_device_payload(vehicle_id, **overrides), _SERVICER)
    )


# ─── Tier 4: lien filing ──────────────────────────────────────────────────
def get_loan_lien(loan_id):
    """Return the single (PENDING) title lien created at origination for a loan."""
    data, _meta = _list(api_client.list_loan_title_liens(loan_id, _CLERK))
    return data[0]


def file_loan_lien(loan_id, dmv_reference="DMV-FIX-1"):
    """File the loan's origination lien (PENDING -> FILED). Returns the FILED lien."""
    lien = get_loan_lien(loan_id)
    return get_success_data(
        api_client.file_title_lien(lien["id"], create_title_lien_file_payload(dmv_reference), _CLERK)
    ), lien["id"]


# ─── Tier 5: delinquency / default progression ────────────────────────────
def setup_delinquent_loan(install_dev=True, file_lien=False,
                          clock_past_due=CLOCK_PAST_DUE, appraisal_overrides=None):
    """Originate a CA loan, optionally install a device and file the lien, advance
    the clock so seq1+seq2 are past due, and assess delinquency.

    Returns a dict (origination keys) plus device (or None) and lien_id (or None).
    Loan is DELINQUENT after this with seq1+seq2 PAST_DUE; fees_balance 10000,
    accrued_interest 30176 on the canonical 600000/3600/3-month loan.
    """
    ctx = setup_originated_loan(appraisal_overrides=appraisal_overrides)
    loan_id = ctx["loan"]["id"]
    device = install_device(ctx["vehicle"]["id"]) if install_dev else None
    lien_id = None
    if file_lien:
        _filed, lien_id = file_loan_lien(loan_id)
    set_clock(clock_past_due)
    ctx["loan"] = get_success_data(api_client.assess_delinquency(loan_id, _SERVICER))
    ctx["device"] = device
    ctx["lien_id"] = lien_id
    return ctx


def setup_defaulted_loan(install_dev=True, clock_past_due=CLOCK_PAST_DUE):
    """Originate -> delinquent -> declare default. The default cascade opens a
    RepossessionOrder in ORDERED. Returns the delinquency context plus
    repo_order (the ORDERED order).
    """
    ctx = setup_delinquent_loan(install_dev=install_dev, clock_past_due=clock_past_due)
    loan_id = ctx["loan"]["id"]
    ctx["loan"] = get_success_data(api_client.declare_default(loan_id, _SERVICER))
    ctx["repo_order"] = _first_repo_order(loan_id)
    return ctx


def setup_recovered_repo(install_dev=True,
                         clock_past_due=CLOCK_PAST_DUE,
                         recover_clock="2026-03-20T00:00:00.000Z",
                         window_start="2026-03-20T08:00:00.000Z",
                         window_end="2026-03-20T12:00:00.000Z",
                         agent_name="Agent Fixture"):
    """Originate -> default -> attach assignment -> assign -> set recover clock ->
    recover. Returns the default context with repo_order now RECOVERED. The
    redemption_deadline is recover_clock + grace days.
    """
    ctx = setup_defaulted_loan(install_dev=install_dev, clock_past_due=clock_past_due)
    repo_id = ctx["repo_order"]["id"]
    get_success_data(api_client.create_assignment(
        repo_id, create_assignment_payload(agent_name, window_start, window_end), _RECOVERY))
    get_success_data(api_client.assign_repossession_order(repo_id, _RECOVERY))
    set_clock(recover_clock)
    ctx["repo_order"] = get_success_data(api_client.recover_repossession_order(repo_id, _RECOVERY))
    return ctx


def setup_charged_off_loan(sale_proceeds_cents=500000,
                           clock_past_due=CLOCK_PAST_DUE,
                           recover_clock="2026-03-20T00:00:00.000Z",
                           sell_clock="2026-03-30T00:00:00.000Z"):
    """Full path to charge-off: originate -> default -> recover -> advance past
    redemption_deadline -> sell. Loan becomes CHARGED_OFF and the borrower BARRED.
    Returns the recovered context with repo_order now SOLD.
    """
    ctx = setup_recovered_repo(clock_past_due=clock_past_due, recover_clock=recover_clock)
    repo_id = ctx["repo_order"]["id"]
    set_clock(sell_clock)
    ctx["repo_order"] = get_success_data(
        api_client.sell_repossession_order(repo_id, create_sale_payload(sale_proceeds_cents), _RECOVERY)
    )
    return ctx


# ─── Renewal helpers ──────────────────────────────────────────────────────
def renew_loan(loan_id, new_term_months):
    """Read the current loan version and create a renewal with it. Returns the Renewal."""
    loan = get_success_data(api_client.get_loan(loan_id, _SERVICER))
    return get_success_data(
        api_client.create_renewal(
            loan_id, create_renewal_payload(loan["version"], new_term_months), _SERVICER
        )
    )


def setup_loan_at_renewal_cap(max_renewals=2):
    """Originate a clean CA loan and renew it max_renewals times so renewal_count
    == max_renewals (CURRENT, OUTSTANDING). Returns origination context.
    """
    ctx = setup_originated_loan()
    loan_id = ctx["loan"]["id"]
    base_term = 6
    for i in range(max_renewals):
        renew_loan(loan_id, base_term + 3 * i)
    ctx["loan"] = get_success_data(api_client.get_loan(loan_id, _SERVICER))
    return ctx


# ─── Internal list / lookup helpers ───────────────────────────────────────
def _list(response):
    """Return (data_list, meta_dict) from a paginated list response (lenient)."""
    body = get_success_data(response)
    # get_success_data returns the data payload (a list for array responses).
    # The meta is not surfaced here; callers that need it use validate_paginated.
    if isinstance(body, list):
        return body, {}
    return body, {}


def _first_repo_order(loan_id):
    data, _meta = _list(api_client.list_loan_repossession_orders(loan_id, _RECOVERY))
    return data[0]


def loan_for_application(application_id):
    """Resolve the Loan originated by an approved application via reverse-reference
    list (Loans are listable filtered by application_id, PRD §3.4)."""
    data, _meta = _list(api_client.list_loans(_SERVICER, params={"application_id": application_id}))
    return data[0]


def get_loan(loan_id, headers=None):
    return get_success_data(api_client.get_loan(loan_id, headers or _SERVICER))


def get_device(device_id, headers=None):
    return get_success_data(api_client.get_device(device_id, headers or _SERVICER))


def get_payoff_quote(loan_id, headers=None):
    return get_success_data(api_client.get_payoff_quote(loan_id, headers or _SERVICER))
