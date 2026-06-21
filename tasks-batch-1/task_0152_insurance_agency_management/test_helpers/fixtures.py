"""Composite setup helpers for the Insurance Agency Management API.

Most interesting claims require the system to be walked through a multi-step
compliance + lifecycle preamble (clock -> carrier -> product -> producer ->
license -> appointment -> account -> policy -> bind -> activate). These helpers
encapsulate those sequences so tests focus on assertions.

All helpers use get_success_data() (lenient validator) internally so setup failures
produce clear "Setup step failed" messages. The Producer role is entity-backed:
ownership-gated calls thread make_producer_headers(producer_id).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_producer_headers
from . import factories


# ---------------------------------------------------------------------------
# Header shortcuts
# ---------------------------------------------------------------------------
def admin_headers():
    return TEST_USERS["agency_admin_headers"]


def manager_headers():
    return TEST_USERS["account_manager_headers"]


def trust_headers():
    return TEST_USERS["trust_accountant_headers"]


# ---------------------------------------------------------------------------
# Clock control (PRD §2.11)
# ---------------------------------------------------------------------------
def set_clock(iso8601: str):
    """Set the authoritative server clock. AgencyAdmin-only."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": iso8601}, admin_headers())
    )


# ---------------------------------------------------------------------------
# Tier 1: primitive create-and-progress helpers
# ---------------------------------------------------------------------------
def create_carrier(**overrides) -> dict:
    return get_success_data(
        api_client.create_carrier(factories.create_carrier_payload(**overrides), admin_headers())
    )


def create_active_carrier(**overrides) -> dict:
    """Create a carrier and activate it to ACTIVE. Returns the activated carrier."""
    carrier = create_carrier(**overrides)
    activated = get_success_data(
        api_client.activate_carrier(
            carrier["id"], {"expected_carrier_version": carrier["version"]}, admin_headers()
        )
    )
    return activated


def create_product(carrier_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_product(
            factories.create_product_payload(carrier_id, **overrides), admin_headers()
        )
    )


def create_producer(**overrides) -> dict:
    return get_success_data(
        api_client.create_producer(factories.create_producer_payload(**overrides), admin_headers())
    )


def create_license(producer_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_license(
            factories.create_license_payload(producer_id, **overrides), admin_headers()
        )
    )


def create_account(servicing_producer_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_account(
            factories.create_account_payload(servicing_producer_id, **overrides), admin_headers()
        )
    )


def create_active_appointment(carrier_id, producer_id, state_code="CA") -> dict:
    """Request -> approve -> activate an appointment. Requires the producer to hold an
    ACTIVE license in state_code (PRD §3.2). Returns the ACTIVE appointment."""
    appt = get_success_data(
        api_client.create_appointment(
            factories.create_appointment_payload(carrier_id, producer_id, state_code=state_code),
            admin_headers(),
        )
    )
    approved = get_success_data(
        api_client.approve_appointment(
            appt["id"], {"expected_appointment_version": appt["version"]}, admin_headers()
        )
    )
    active = get_success_data(
        api_client.activate_appointment(
            appt["id"], {"expected_appointment_version": approved["version"]}, admin_headers()
        )
    )
    return active


def create_trust_account(**overrides) -> dict:
    return get_success_data(
        api_client.create_trust_account(
            factories.create_trust_account_payload(**overrides), trust_headers()
        )
    )


def open_trust_account_with_balance(amount_cents, state_code="CA", minimum_balance_cents=0, **overrides) -> dict:
    """Create a trust account and seed it with an OPENING_BALANCE entry (PRD §3.9).
    Returns the trust account (re-read so balance_cents/version reflect the posting)."""
    trust = create_trust_account(
        state_code=state_code, minimum_balance_cents=minimum_balance_cents, **overrides
    )
    get_success_data(
        api_client.create_ledger_entry(
            trust["id"],
            factories.create_ledger_entry_payload(
                "OPENING_BALANCE", amount_cents, trust["version"]
            ),
            trust_headers(),
        )
    )
    return get_success_data(api_client.get_trust_account(trust["id"], trust_headers()))


# ---------------------------------------------------------------------------
# Tier 2: compliant producer + carrier + product (the "ready to write" base)
# ---------------------------------------------------------------------------
def setup_compliant_writer(
    carrier_overrides=None,
    product_overrides=None,
    producer_overrides=None,
    license_overrides=None,
    state_code="CA",
    line_of_business="AUTO",
) -> dict:
    """Build a fully compliant writing context:

      ACTIVE carrier + product + ACTIVE producer with an ACTIVE license matching
      (state_code, line_of_business) + an ACTIVE appointment for
      (producer, carrier, state_code) + an account servicing that producer.

    Returns dict with keys: carrier, product, producer, license, appointment, account.
    The producer is the writing producer of record.
    """
    carrier_overrides = carrier_overrides or {}
    product_overrides = product_overrides or {}
    producer_overrides = producer_overrides or {}
    license_overrides = license_overrides or {}

    carrier = create_active_carrier(**carrier_overrides)
    product = create_product(
        carrier["id"], line_of_business=line_of_business, **product_overrides
    )
    producer = create_producer(**producer_overrides)
    license_ = create_license(
        producer["id"], state_code=state_code, line_of_business=line_of_business, **license_overrides
    )
    appointment = create_active_appointment(carrier["id"], producer["id"], state_code=state_code)
    account = create_account(producer["id"])
    return {
        "carrier": carrier,
        "product": product,
        "producer": producer,
        "license": license_,
        "appointment": appointment,
        "account": account,
    }


# ---------------------------------------------------------------------------
# Tier 3: policy lifecycle shortcuts
# ---------------------------------------------------------------------------
def create_quoted_policy(ctx, **policy_overrides) -> dict:
    """Create a QUOTED policy in the given compliant context. Created by the writing
    producer (entity-backed ownership). Returns the policy."""
    producer = ctx["producer"]
    payload = factories.create_policy_payload(
        ctx["account"]["id"], ctx["product"]["id"], producer["id"], **policy_overrides
    )
    return get_success_data(
        api_client.create_policy(payload, make_producer_headers(producer["id"]))
    )


def add_writing_split(ctx, policy, split_pct=1.0, role="WRITING", producer_id=None):
    """Add a commission split to a policy, threading the current Policy.version.
    Returns (split, refreshed_policy_version)."""
    producer = ctx["producer"]
    target_producer = producer_id or producer["id"]
    split = get_success_data(
        api_client.create_commission_split(
            factories.create_commission_split_payload(
                policy["id"], target_producer, policy["version"],
                split_pct=split_pct, role=role,
            ),
            make_producer_headers(producer["id"]),
        )
    )
    refreshed = get_success_data(
        api_client.get_policy(policy["id"], make_producer_headers(producer["id"]))
    )
    return split, refreshed["version"]


def bind_policy(ctx, policy_id, expected_version) -> dict:
    """Bind a QUOTED policy as the writing producer (Producer role, ownership-gated)."""
    producer = ctx["producer"]
    return get_success_data(
        api_client.bind_policy(
            policy_id, {"expected_policy_version": expected_version},
            make_producer_headers(producer["id"]),
        )
    )


def activate_policy(policy_id, expected_version) -> dict:
    """Activate a BOUND policy as AccountManager."""
    return get_success_data(
        api_client.activate_policy(
            policy_id, {"expected_policy_version": expected_version}, manager_headers()
        )
    )


def setup_active_policy(ctx=None, policy_overrides=None, **ctx_kwargs) -> dict:
    """Full lifecycle to an ACTIVE policy with a single WRITING split_pct=1.0.

    QUOTED -> (add WRITING split 1.0) -> BOUND -> ACTIVE.

    Returns dict: ctx, policy (latest read), split. Builds its own compliant context
    if `ctx` is not supplied.
    """
    if ctx is None:
        ctx = setup_compliant_writer(**ctx_kwargs)
    policy_overrides = policy_overrides or {}
    policy = create_quoted_policy(ctx, **policy_overrides)
    split, version_after_split = add_writing_split(ctx, policy, split_pct=1.0, role="WRITING")
    bound = bind_policy(ctx, policy["id"], version_after_split)
    active = activate_policy(policy["id"], bound["version"])
    return {"ctx": ctx, "policy": active, "split": split}


def setup_active_policy_no_split(ctx=None, policy_overrides=None, **ctx_kwargs) -> dict:
    """QUOTED -> BOUND -> ACTIVE without adding any commission split. Useful for
    return-premium / status tests that do not assert commission figures.

    Returns dict: ctx, policy (latest read).
    """
    if ctx is None:
        ctx = setup_compliant_writer(**ctx_kwargs)
    policy_overrides = policy_overrides or {}
    policy = create_quoted_policy(ctx, **policy_overrides)
    bound = bind_policy(ctx, policy["id"], policy["version"])
    active = activate_policy(policy["id"], bound["version"])
    return {"ctx": ctx, "policy": active}


# ---------------------------------------------------------------------------
# Tier 4: renewal-pipeline shortcuts
# ---------------------------------------------------------------------------
def open_renewal_task(policy_id, target_effective_date) -> dict:
    """Open a renewal task (moves the policy to PENDING_RENEWAL). AccountManager."""
    return get_success_data(
        api_client.create_renewal_task(
            factories.create_renewal_task_payload(policy_id, target_effective_date),
            manager_headers(),
        )
    )


def advance_renewal_task(task_id, expected_version) -> dict:
    return get_success_data(
        api_client.advance_renewal_task(
            task_id, {"expected_renewaltask_version": expected_version}, manager_headers()
        )
    )


def setup_renewal_task_offered(active_setup=None, target_effective_date="2027-01-01T00:00:00Z",
                              window_clock="2026-11-15T00:00:00Z") -> dict:
    """Take an ACTIVE policy into its renewal window, open a RenewalTask, and advance it
    IDENTIFIED -> REVIEW -> QUOTED -> OFFERED.

    `active_setup` is the dict returned by setup_active_policy*/None (built fresh with a
    standard term 2026-01-01..2027-01-01 if None). Sets the clock to window_clock first.

    Returns dict: ctx, policy, task (latest read in OFFERED).
    """
    if active_setup is None:
        active_setup = setup_active_policy_no_split()
    set_clock(window_clock)
    policy = active_setup["policy"]
    task = open_renewal_task(policy["id"], target_effective_date)
    t2 = advance_renewal_task(task["id"], task["version"])       # IDENTIFIED -> REVIEW
    t3 = advance_renewal_task(task["id"], t2["version"])         # REVIEW -> QUOTED
    t4 = advance_renewal_task(task["id"], t3["version"])         # QUOTED -> OFFERED
    return {"ctx": active_setup["ctx"], "policy": policy, "task": t4}


# ---------------------------------------------------------------------------
# Tier 5: commission-statement shortcuts
# ---------------------------------------------------------------------------
def open_statement(producer_id, period_start, period_end) -> dict:
    return get_success_data(
        api_client.create_commission_statement(
            factories.create_commission_statement_payload(producer_id, period_start, period_end),
            trust_headers(),
        )
    )


def get_statement(statement_id) -> dict:
    return get_success_data(
        api_client.get_commission_statement(statement_id, trust_headers())
    )


def finalize_statement(statement_id, expected_version) -> dict:
    return get_success_data(
        api_client.finalize_statement(
            statement_id, {"expected_commissionstatement_version": expected_version}, trust_headers()
        )
    )
