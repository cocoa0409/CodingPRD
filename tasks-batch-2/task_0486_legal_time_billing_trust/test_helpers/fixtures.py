"""Composite setup helpers.

Each test starts against an empty database (the harness restarts the server
before every test), so every fixture builds its preconditions from scratch using
only PRD-declared endpoints. Fixtures use get_success_data() (lenient) internally
so setup failures surface as clear "Setup failed" errors.

All three roles are opaque; the shared TEST_USERS headers are used for setup, and
the per-actor builders (make_attorney_headers / make_billing_clerk_headers) are
used where a specific X-User-ID must be recorded or compared (trust SoD).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_attorney_headers,
    make_billing_clerk_headers,
)
from . import factories as f

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]
ATT = TEST_USERS["attorney_headers"]


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------
def ensure_billing_codes(task=True, activity=True, expense=False):
    """Create the standard L110/A101 (and optionally E101) billing codes.

    Returns a dict of {kind: code_string} for convenience.
    """
    out = {}
    if task:
        get_success_data(api_client.create_billing_code(
            f.create_billing_code_payload("L110", "TASK", "Fact Investigation"), ADMIN))
        out["TASK"] = "L110"
    if activity:
        get_success_data(api_client.create_billing_code(
            f.create_billing_code_payload("A101", "ACTIVITY", "Plan and prepare"), ADMIN))
        out["ACTIVITY"] = "A101"
    if expense:
        get_success_data(api_client.create_billing_code(
            f.create_billing_code_payload("E101", "EXPENSE", "Copying"), ADMIN))
        out["EXPENSE"] = "E101"
    return out


def create_timekeeper(full_name="Pat Partner", role_kind="PARTNER",
                      standard_rate_cents=50000, **overrides):
    data = get_success_data(api_client.create_timekeeper(
        f.create_timekeeper_payload(
            full_name=full_name, role_kind=role_kind,
            standard_rate_cents=standard_rate_cents, **overrides), ADMIN))
    return data


def create_client(display_name="Acme Corp", client_type="ORGANIZATION", **overrides):
    data = get_success_data(api_client.create_client(
        f.create_client_payload(display_name=display_name, client_type=client_type,
                                **overrides), CLERK))
    return data


# ---------------------------------------------------------------------------
# Matter lifecycle (Tier 1: state progression)
# ---------------------------------------------------------------------------
def create_matter_in_intake(client_id=None, timekeeper_id=None, **matter_overrides):
    """Create (client+timekeeper if absent) and a Matter in INTAKE.

    Returns (matter, client_id, timekeeper_id).
    """
    if timekeeper_id is None:
        timekeeper_id = create_timekeeper()["id"]
    if client_id is None:
        client_id = create_client()["id"]
    matter = get_success_data(api_client.create_matter(
        f.create_matter_payload(client_id, timekeeper_id, **matter_overrides), CLERK))
    return matter, client_id, timekeeper_id


def create_matter_conflict_cleared(client_id=None, timekeeper_id=None,
                                   adverse_party_name="Opposing Co", **matter_overrides):
    """Matter walked to CONFLICT_CLEARED via a non-matching (CLEAR) conflict screen.

    Returns (matter, client_id, timekeeper_id).
    """
    matter, client_id, timekeeper_id = create_matter_in_intake(
        client_id=client_id, timekeeper_id=timekeeper_id, **matter_overrides)
    get_success_data(api_client.create_conflict_check(
        matter["id"], f.create_conflict_check_payload(adverse_party_name), CLERK))
    matter = get_success_data(api_client.get_matter(matter["id"], CLERK))
    return matter, client_id, timekeeper_id


def create_open_matter(client_id=None, timekeeper_id=None,
                       matter_rate_cents=50000, adverse_party_name="Opposing Co",
                       **matter_overrides):
    """Matter walked all the way to OPEN.

    Returns (matter, client_id, timekeeper_id). matter_rate_cents defaults to
    50000; pass matter_rate_cents=None to leave it unset (so the rate ladder
    falls to override/standard).
    """
    overrides = dict(matter_overrides)
    if matter_rate_cents is not None:
        overrides["matter_rate_cents"] = matter_rate_cents
    matter, client_id, timekeeper_id = create_matter_conflict_cleared(
        client_id=client_id, timekeeper_id=timekeeper_id,
        adverse_party_name=adverse_party_name, **overrides)
    matter = get_success_data(api_client.open_matter(matter["id"], ATT))
    return matter, client_id, timekeeper_id


def create_flagged_matter(subject_name="Acme Corp", adverse_name="Rival Inc"):
    """Adverse client exists, then a matter for the subject is screened against the
    adverse name -> FLAGGED -> matter CONFLICT_BLOCKED.

    Returns (matter, conflict_check, subject_client_id, adverse_client_id, timekeeper_id).
    The conflict_check is the FLAGGED check (from the create response).
    """
    timekeeper_id = create_timekeeper()["id"]
    adverse_client_id = create_client(display_name=adverse_name)["id"]
    subject_client_id = create_client(display_name=subject_name)["id"]
    matter = get_success_data(api_client.create_matter(
        f.create_matter_payload(subject_client_id, timekeeper_id, title="Subject v Adverse"),
        CLERK))
    cc = get_success_data(api_client.create_conflict_check(
        matter["id"], f.create_conflict_check_payload(adverse_name), CLERK))
    return matter, cc, subject_client_id, adverse_client_id, timekeeper_id


# ---------------------------------------------------------------------------
# Time / invoice lifecycle (Tier 3: full lifecycle shortcuts)
# ---------------------------------------------------------------------------
def capture_time_entry(matter_id, timekeeper_id, minutes=60,
                       worked_at="2026-05-01T09:00:00Z", actor=None, **overrides):
    data = get_success_data(api_client.create_time_entry(
        f.create_time_entry_payload(matter_id, timekeeper_id, minutes=minutes,
                                    worked_at=worked_at, **overrides),
        actor or ATT))
    return data


def setup_open_matter_with_time(matter_rate_cents=50000, minutes=60, expense_cents=None):
    """OPEN matter + one captured time entry (and optionally one expense entry).

    Returns dict: matter, client_id, timekeeper_id, time_entry, expense_entry(optional).
    """
    ensure_billing_codes(expense=expense_cents is not None)
    matter, client_id, timekeeper_id = create_open_matter(matter_rate_cents=matter_rate_cents)
    te = capture_time_entry(matter["id"], timekeeper_id, minutes=minutes)
    out = {
        "matter": matter,
        "client_id": client_id,
        "timekeeper_id": timekeeper_id,
        "time_entry": te,
    }
    if expense_cents is not None:
        ee = get_success_data(api_client.create_expense_entry(
            f.create_expense_entry_payload(matter["id"], expense_cents), ATT))
        out["expense_entry"] = ee
    return out


def setup_draft_invoice(matter_rate_cents=50000, minutes=60):
    """OPEN matter + one captured time entry + a DRAFT invoice (not finalized).

    Returns dict: matter, client_id, timekeeper_id, time_entry, invoice.
    """
    base = setup_open_matter_with_time(matter_rate_cents=matter_rate_cents, minutes=minutes)
    invoice = get_success_data(api_client.create_invoice(
        f.create_invoice_payload(base["matter"]["id"]), CLERK))
    base["invoice"] = invoice
    return base


def setup_issued_invoice(matter_rate_cents=50000, minutes=60):
    """OPEN matter + captured time entry + a finalized (ISSUED) invoice.

    Returns dict: matter, client_id, timekeeper_id, time_entry, invoice (post-finalize).
    """
    base = setup_draft_invoice(matter_rate_cents=matter_rate_cents, minutes=minutes)
    invoice = get_success_data(api_client.finalize_invoice(
        base["invoice"]["id"], {}, CLERK))
    base["invoice"] = invoice
    return base


# ---------------------------------------------------------------------------
# Trust lifecycle (Tier 4: funded ledgers)
# ---------------------------------------------------------------------------
def setup_trust_account_and_ledger(client_id=None, retainer_floor_cents=0):
    """Trust account + a client sub-ledger (balance 0).

    Returns dict: trust_account, ledger, client_id.
    """
    ta = get_success_data(api_client.create_trust_account(
        f.create_trust_account_payload(), ADMIN))
    if client_id is None:
        client_id = create_client()["id"]
    led = get_success_data(api_client.create_trust_ledger(
        f.create_trust_ledger_payload(ta["id"], client_id,
                                      retainer_floor_cents=retainer_floor_cents), CLERK))
    return {"trust_account": ta, "ledger": led, "client_id": client_id}


def post_deposit(ledger_id, amount_cents, initiated_by_user_id="clerk-1", confirm=False):
    """Post a DEPOSIT (PENDING); optionally confirm it. Returns the tx (create response)."""
    tx = get_success_data(api_client.create_trust_transaction(
        f.create_trust_transaction_payload(ledger_id, "DEPOSIT", amount_cents,
                                           initiated_by_user_id), CLERK))
    if confirm:
        get_success_data(api_client.confirm_trust_transaction(tx["id"], CLERK))
    return tx


def setup_funded_ledger(client_id=None, deposit_cents=100000, confirm=True,
                        retainer_floor_cents=0):
    """Trust account + sub-ledger + one DEPOSIT (confirmed by default).

    Returns dict: trust_account, ledger, client_id, deposit_tx.
    """
    base = setup_trust_account_and_ledger(client_id=client_id,
                                          retainer_floor_cents=retainer_floor_cents)
    tx = post_deposit(base["ledger"]["id"], deposit_cents, confirm=confirm)
    base["deposit_tx"] = tx
    return base


def setup_issued_invoice_with_funded_trust(matter_rate_cents=50000, minutes=60,
                                           deposit_cents=100000, confirm_deposit=True):
    """Full cross-aggregate setup: an ISSUED invoice for a client whose trust
    sub-ledger is funded — ready for a trust sweep.

    The client is shared between the matter/invoice and the trust ledger.
    Returns dict: matter, client_id, timekeeper_id, time_entry, invoice,
    trust_account, ledger, deposit_tx.
    """
    ensure_billing_codes()
    # Build the trust account + client + funded ledger FIRST so the client id is shared.
    client_id = create_client()["id"]
    timekeeper_id = create_timekeeper()["id"]
    trust = setup_funded_ledger(client_id=client_id, deposit_cents=deposit_cents,
                                confirm=confirm_deposit)
    matter, _, _ = create_open_matter(client_id=client_id, timekeeper_id=timekeeper_id,
                                      matter_rate_cents=matter_rate_cents)
    te = capture_time_entry(matter["id"], timekeeper_id, minutes=minutes)
    draft = get_success_data(api_client.create_invoice(
        f.create_invoice_payload(matter["id"]), CLERK))
    invoice = get_success_data(api_client.finalize_invoice(draft["id"], {}, CLERK))
    return {
        "matter": matter,
        "client_id": client_id,
        "timekeeper_id": timekeeper_id,
        "time_entry": te,
        "invoice": invoice,
        "trust_account": trust["trust_account"],
        "ledger": trust["ledger"],
        "deposit_tx": trust["deposit_tx"],
    }


def setup_ledger_with_active_hold(amount_cents=20000,
                                  hold_start_at="2026-06-01T00:00:00Z",
                                  hold_end_at="2026-06-10T00:00:00Z"):
    """Trust account + ledger + one ACTIVE retainer hold.

    Returns dict: trust_account, ledger, client_id, hold.
    """
    base = setup_trust_account_and_ledger()
    hold = get_success_data(api_client.create_retainer_hold(
        f.create_retainer_hold_payload(base["ledger"]["id"], amount_cents,
                                       hold_start_at, hold_end_at), CLERK))
    base["hold"] = hold
    return base


# ---------------------------------------------------------------------------
# Clock helper
# ---------------------------------------------------------------------------
def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(f.set_clock_payload(to_iso8601), ADMIN))
