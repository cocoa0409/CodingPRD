"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints, because the server database is empty at the start of each test.
Identity threading: ownership-gated calls use make_counselor_headers(counselor_id)
and make_creditor_rep_headers(creditor_id) with the real entity ids.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    make_agency_admin_headers,
    make_counselor_headers,
    make_creditor_rep_headers,
)
from .factories import (
    create_agency_payload,
    create_counselor_payload,
    create_creditor_payload,
    create_client_payload,
    open_session_payload,
    create_debt_account_payload,
    activate_payload,
    deposit_payload,
)


# ---------------------------------------------------------------------------
# Tier 0: provisioning primitives
# ---------------------------------------------------------------------------
def create_agency(setup_fee_cents=5000, monthly_fee_cents=3500, name="MMI"):
    admin = make_agency_admin_headers()
    resp = api_client.create_agency(
        create_agency_payload(
            name=name, setup_fee_cents=setup_fee_cents, monthly_fee_cents=monthly_fee_cents
        ),
        admin,
    )
    return get_success_data(resp)


def create_counselor(agency_id, full_name="Cy", hud_certified=False):
    admin = make_agency_admin_headers()
    resp = api_client.create_counselor(
        create_counselor_payload(agency_id, full_name=full_name, hud_certified=hud_certified),
        admin,
    )
    return get_success_data(resp)


def create_creditor(agency_id, name="Cap", default_concession_apr=0.0699,
                    waives_late_fees=True, min_proposed_payment_pct=0.02):
    admin = make_agency_admin_headers()
    resp = api_client.create_creditor(
        create_creditor_payload(
            agency_id, name=name, default_concession_apr=default_concession_apr,
            waives_late_fees=waives_late_fees, min_proposed_payment_pct=min_proposed_payment_pct,
        ),
        admin,
    )
    return get_success_data(resp)


def create_client(agency_id, counselor_id, full_name="Dan",
                  gross_monthly_income_cents=500000, housing_payment_cents=150000):
    cn = make_counselor_headers(counselor_id)
    resp = api_client.create_client(
        create_client_payload(
            agency_id, counselor_id, full_name=full_name,
            gross_monthly_income_cents=gross_monthly_income_cents,
            housing_payment_cents=housing_payment_cents,
        ),
        cn,
    )
    return get_success_data(resp)


def base_agency_counselor_creditor(monthly_fee_cents=3500, setup_fee_cents=5000,
                                   default_concession_apr=0.0699,
                                   min_proposed_payment_pct=0.02, hud_certified=False):
    """Returns (agency, counselor, creditor) with real ids for identity threading."""
    agency = create_agency(setup_fee_cents=setup_fee_cents, monthly_fee_cents=monthly_fee_cents)
    counselor = create_counselor(agency["id"], hud_certified=hud_certified)
    creditor = create_creditor(
        agency["id"], default_concession_apr=default_concession_apr,
        min_proposed_payment_pct=min_proposed_payment_pct,
    )
    return agency, counselor, creditor


# ---------------------------------------------------------------------------
# Tier 1: sessions
# ---------------------------------------------------------------------------
def open_intake_session(client_id, counselor_id, session_type="BUDGET_INTAKE"):
    cn = make_counselor_headers(counselor_id)
    resp = api_client.open_session(
        client_id, open_session_payload(counselor_id, session_type=session_type), cn
    )
    return get_success_data(resp)


def complete_session(session_id, counselor_id):
    cn = make_counselor_headers(counselor_id)
    resp = api_client.complete_session(session_id, cn)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: debt accounts + proposals
# ---------------------------------------------------------------------------
def add_debt_account(client_id, counselor_id, creditor_id, account_ref,
                     original_balance_cents, proposed_monthly_payment_cents,
                     original_apr=0.2499, min_payment_cents=9000,
                     requested_concession_apr=0.0699):
    cn = make_counselor_headers(counselor_id)
    resp = api_client.create_debt_account(
        client_id,
        create_debt_account_payload(
            creditor_id, account_ref=account_ref,
            original_balance_cents=original_balance_cents,
            proposed_monthly_payment_cents=proposed_monthly_payment_cents,
            original_apr=original_apr, min_payment_cents=min_payment_cents,
            requested_concession_apr=requested_concession_apr,
        ),
        cn,
    )
    return get_success_data(resp)


def accept_proposal(proposal_id, creditor_id):
    rep = make_creditor_rep_headers(creditor_id)
    resp = api_client.accept_proposal(proposal_id, rep)
    return get_success_data(resp)


def add_and_accept_account(client_id, counselor_id, creditor_id, account_ref,
                           original_balance_cents, proposed_monthly_payment_cents,
                           original_apr=0.2499, min_payment_cents=9000,
                           requested_concession_apr=0.0699):
    """Create a debt account and accept its auto-created proposal. Returns account dict."""
    acct = add_debt_account(
        client_id, counselor_id, creditor_id, account_ref,
        original_balance_cents, proposed_monthly_payment_cents,
        original_apr=original_apr, min_payment_cents=min_payment_cents,
        requested_concession_apr=requested_concession_apr,
    )
    accept_proposal(acct["proposal_id"], creditor_id)
    return acct


# ---------------------------------------------------------------------------
# Tier 3: activation
# ---------------------------------------------------------------------------
def activate(client_id, counselor_id):
    """Read fresh version then activate. Returns the activated client dict."""
    cn = make_counselor_headers(counselor_id)
    cur = get_success_data(api_client.get_client(client_id, cn))
    resp = api_client.activate_client(client_id, activate_payload(cur["version"]), cn)
    return get_success_data(resp)


def setup_active_client(accounts, monthly_fee_cents=3500,
                        gross_monthly_income_cents=500000, housing_payment_cents=150000,
                        default_concession_apr=0.0699, min_proposed_payment_pct=0.02):
    """Full setup to an ACTIVE client with a list of ENROLLED accounts.

    `accounts` is a list of dicts each with keys:
      account_ref, original_balance_cents, proposed_monthly_payment_cents,
      and optionally original_apr, min_payment_cents, requested_concession_apr.

    Returns (agency, counselor, creditor, client, accounts_by_ref) where
    accounts_by_ref maps account_ref -> created account dict (pre-activation ids).
    """
    agency, counselor, creditor = base_agency_counselor_creditor(
        monthly_fee_cents=monthly_fee_cents,
        default_concession_apr=default_concession_apr,
        min_proposed_payment_pct=min_proposed_payment_pct,
    )
    client = create_client(
        agency["id"], counselor["id"],
        gross_monthly_income_cents=gross_monthly_income_cents,
        housing_payment_cents=housing_payment_cents,
    )
    session = open_intake_session(client["id"], counselor["id"])
    accounts_by_ref = {}
    for a in accounts:
        acct = add_and_accept_account(
            client["id"], counselor["id"], creditor["id"],
            account_ref=a["account_ref"],
            original_balance_cents=a["original_balance_cents"],
            proposed_monthly_payment_cents=a["proposed_monthly_payment_cents"],
            original_apr=a.get("original_apr", 0.2499),
            min_payment_cents=a.get("min_payment_cents", 9000),
            requested_concession_apr=a.get("requested_concession_apr", 0.0699),
        )
        accounts_by_ref[a["account_ref"]] = acct
    complete_session(session["id"], counselor["id"])
    client = activate(client["id"], counselor["id"])
    return agency, counselor, creditor, client, accounts_by_ref


# ---------------------------------------------------------------------------
# Tier 4: deposits + disbursement
# ---------------------------------------------------------------------------
def record_deposit(client_id, counselor_id, amount_cents):
    cn = make_counselor_headers(counselor_id)
    resp = api_client.record_deposit(client_id, deposit_payload(amount_cents), cn)
    return get_success_data(resp)


def run_disbursement(agency_id):
    admin = make_agency_admin_headers()
    resp = api_client.run_disbursement(agency_id, admin)
    return get_success_data(resp)


def lines_for_run(run_id, debt_account_id=None):
    """Return the list of DisbursementLine dicts for a run, optionally filtered
    by debt_account_id (client-side filter as a fallback)."""
    admin = make_agency_admin_headers()
    params = {"disbursement_run_id": run_id}
    if debt_account_id is not None:
        params["debt_account_id"] = debt_account_id
    resp = api_client.list_disbursement_lines(admin, params=params)
    data = get_success_data(resp)
    # list endpoints return the array directly in `data`.
    lines = data if isinstance(data, list) else []
    if debt_account_id is not None:
        lines = [ln for ln in lines if ln.get("debt_account_id") == debt_account_id]
    return lines
