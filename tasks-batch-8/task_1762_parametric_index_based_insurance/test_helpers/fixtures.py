"""Composite setup helpers.

Most testable claims in this PRD require a deep precondition stack — an ACTIVE
program with an ACTIVE index, a COMMISSIONED station, an ACTIVE policyholder,
a PAID invoice and a BOUND policy, then observation -> event -> verify ->
claim. These helpers encapsulate that plumbing so tests focus on assertions.

All helpers use get_success_data() so a setup failure surfaces as a clear
"Setup failed" pytest error rather than a confusing assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_index_definition_payload,
    create_observation_payload,
    create_policy_payload,
    create_policyholder_payload,
    create_program_payload,
    create_station_payload,
    create_treaty_payload,
)
from .test_users import TEST_USERS, make_claims_adjuster_headers

PM = TEST_USERS["program_manager_headers"]
ACT = TEST_USERS["actuary_headers"]
UW = TEST_USERS["underwriter_headers"]
ADJ = TEST_USERS["claims_adjuster_headers"]
TRE = TEST_USERS["treasury_officer_headers"]
FRA = TEST_USERS["fraud_analyst_headers"]
DOPS = TEST_USERS["data_operations_headers"]
SVC = TEST_USERS["servicing_agent_headers"]


# ---------------------------------------------------------------------------
# Tier 1: program / index / station / holder building blocks
# ---------------------------------------------------------------------------

def create_program(**overrides):
    """Create a program (DRAFT). Returns the program dict."""
    resp = api_client.create_program(create_program_payload(**overrides), PM)
    return get_success_data(resp)


def create_station(program_id, **overrides):
    """Register a station (COMMISSIONED). Returns the station dict."""
    resp = api_client.create_station(program_id, create_station_payload(**overrides), DOPS)
    return get_success_data(resp)


def create_index(program_id, **overrides):
    """Create an index definition (PENDING_AGREEMENT). Returns the index dict."""
    resp = api_client.create_index_definition(
        program_id, create_index_definition_payload(**overrides), ACT
    )
    return get_success_data(resp)


def activate_index(program_id, index_id):
    resp = api_client.activate_index(program_id, index_id, ACT)
    return get_success_data(resp)


def activate_program(program_id):
    resp = api_client.activate_program(program_id, PM)
    return get_success_data(resp)


def create_policyholder(program_id, acknowledged=True, **overrides):
    """Register a policyholder. With acknowledged=True (default) the holder is
    ACTIVE immediately; otherwise PROSPECT."""
    payload = create_policyholder_payload(**overrides)
    if acknowledged:
        payload["basis_risk_disclosure_acknowledged"] = True
    resp = api_client.create_policyholder(program_id, payload, SVC)
    return get_success_data(resp)


def setup_active_program(**program_overrides):
    """Program + station + index, all the way to program ACTIVE.

    Returns (program, station, index).
    """
    program = create_program(**program_overrides)
    station = create_station(program["id"])
    index = create_index(program["id"])
    activate_index(program["id"], index["id"])
    program = activate_program(program["id"])
    return program, station, index


# ---------------------------------------------------------------------------
# Tier 2: policy hierarchy — holder + quoted policy + paid invoice + bind
# ---------------------------------------------------------------------------

def get_invoice_for_policy(program_id, policy_id):
    """Fetch the single invoice cascade-created with the policy."""
    resp = api_client.list_invoices(program_id, SVC, params={"policy_id": policy_id})
    data = get_success_data(resp)
    assert isinstance(data, list) and len(data) == 1, (
        f"Setup failed: expected exactly 1 invoice for policy {policy_id}, got {data}"
    )
    return data[0]


def pay_invoice_in_full(program_id, invoice_id, amount_cents=None):
    """Pay an invoice in a single full payment; amount defaults to billed."""
    if amount_cents is None:
        inv = get_success_data(api_client.get_invoice(program_id, invoice_id, SVC))
        amount_cents = inv["invoice_amount_cents"]
    resp = api_client.pay_invoice(
        program_id, invoice_id, {"amount_cents": amount_cents}, SVC
    )
    return get_success_data(resp)


def create_quoted_policy(program_id, holder_id, index_id, **overrides):
    """Quote a policy. Returns (policy, invoice)."""
    payload = create_policy_payload(index_definition_id=index_id, **overrides)
    resp = api_client.create_policy(program_id, holder_id, payload, UW)
    policy = get_success_data(resp)
    invoice = get_invoice_for_policy(program_id, policy["id"])
    return policy, invoice


def create_bound_policy(program_id, holder_id, index_id, **overrides):
    """Quote -> pay invoice in full -> bind. Returns (policy, invoice)."""
    policy, invoice = create_quoted_policy(program_id, holder_id, index_id, **overrides)
    pay_invoice_in_full(program_id, invoice["id"])
    resp = api_client.bind_policy(program_id, holder_id, policy["id"], UW)
    policy = get_success_data(resp)
    return policy, invoice


def setup_program_with_bound_policy(
    sum_insured_cents=TEST_DEFAULTS["SUM_INSURED"],
    trigger_thresholds=None,
    strike_direction="BELOW",
    program_overrides=None,
    index_overrides=None,
    policy_overrides=None,
    **program_kwargs,
):
    """The canonical deep stack: ACTIVE program + ACTIVE index + COMMISSIONED
    station + ACTIVE holder + BOUND policy with a PAID invoice.

    Extra keyword arguments (e.g. ``program_code``) are treated as overrides to
    the program payload so callers can pin identity fields inline.

    Returns a dict with every handle a claim-lifecycle test needs.
    """
    program_overrides = dict(program_overrides or {})
    program_overrides.update(program_kwargs)
    index_overrides = dict(index_overrides or {})
    policy_overrides = dict(policy_overrides or {})
    if trigger_thresholds is not None:
        index_overrides["trigger_thresholds"] = trigger_thresholds
    index_overrides["strike_direction"] = strike_direction

    # Build the stack manually so index_overrides actually reach create_index —
    # setup_active_program does not accept per-entity overrides.
    program = create_program(**program_overrides)
    station = create_station(program["id"])
    index = create_index(program["id"], **index_overrides)
    activate_index(program["id"], index["id"])
    program = activate_program(program["id"])
    index = get_success_data(api_client.get_index_definition(program["id"], index["id"], ACT))
    holder = create_policyholder(program["id"])
    policy, invoice = create_bound_policy(
        program["id"], holder["id"], index["id"],
        sum_insured_cents=sum_insured_cents, **policy_overrides,
    )
    return {
        "program": program,
        "station": station,
        "index": index,
        "holder": holder,
        "policy": policy,
        "invoice": invoice,
    }


# ---------------------------------------------------------------------------
# Tier 3: event + claim lifecycle shortcuts
# ---------------------------------------------------------------------------

def ingest_observation(program_id, index_id, station_id, window_end_date, measured_value,
                       supersedes_observation_id=None):
    """Ingest one observation. Returns the observation dict."""
    payload = create_observation_payload(
        station_id=station_id,
        window_end_date=window_end_date,
        measured_value=measured_value,
    )
    if supersedes_observation_id is not None:
        payload["supersedes_observation_id"] = supersedes_observation_id
    resp = api_client.create_observation(program_id, index_id, payload, DOPS)
    return get_success_data(resp)


def find_event_for_window(program_id, index_id, window_end_date=None):
    """Locate the auto-detected trigger event for an index (optionally pinned
    to a window). Returns the event dict."""
    params = {"index_definition_id": index_id}
    resp = api_client.list_trigger_events_in_program(program_id, ADJ, params=params)
    events = get_success_data(resp)
    if window_end_date is not None:
        events = [e for e in events if e["window_end_date"] == window_end_date]
    assert len(events) == 1, (
        f"Setup failed: expected exactly 1 trigger event for window {window_end_date}, "
        f"got {len(events)}"
    )
    return events[0]


def verify_event(program_id, index_id, event_id):
    """open-review -> verify. Returns the VERIFIED event dict."""
    get_success_data(api_client.open_event_review(program_id, index_id, event_id, ADJ))
    resp = api_client.verify_event(program_id, index_id, event_id, ADJ)
    return get_success_data(resp)


def list_claims_for_policy(program_id, policy_id):
    resp = api_client.list_claims(program_id, ADJ, params={"policy_id": policy_id})
    return get_success_data(resp)


def list_claims_for_event(program_id, event_id):
    resp = api_client.list_claims(program_id, ADJ, params={"trigger_event_id": event_id})
    return get_success_data(resp)


def create_verified_event_with_claim(
    stack,
    window_end_date=TEST_DEFAULTS["WINDOW_END_DATE"],
    measured_value=40,
    station_key="station",
):
    """Ingest a breaching observation and verify the resulting event.

    `stack` is the dict from setup_program_with_bound_policy. Returns
    (event, claim) where claim is the single claim generated for the policy.
    """
    program_id = stack["program"]["id"]
    index_id = stack["index"]["id"]
    ingest_observation(
        program_id, index_id, stack[station_key]["id"], window_end_date, measured_value
    )
    event = find_event_for_window(program_id, index_id, window_end_date)
    event = verify_event(program_id, index_id, event["id"])
    claims = list_claims_for_event(program_id, event["id"])
    assert len(claims) >= 1, f"Setup failed: no claims generated by verify of {event['id']}"
    return event, claims


def approve_claim(program_id, claim_id, approver_user_id="adjuster-1"):
    """Approve a claim as ClaimsAdjuster with a pinned approver id (recorded as
    approver_user_id for the segregation-of-duties check at release)."""
    resp = api_client.approve_claim(
        program_id, claim_id, make_claims_adjuster_headers(approver_user_id)
    )
    return get_success_data(resp)


def setup_approved_claim(
    stack=None,
    window_end_date=TEST_DEFAULTS["WINDOW_END_DATE"],
    measured_value=40,
    approver_user_id="adjuster-1",
    **stack_kwargs,
):
    """Full stack through claim APPROVED. Returns (stack, event, claim)."""
    if stack is None:
        stack = setup_program_with_bound_policy(**stack_kwargs)
    event, claims = create_verified_event_with_claim(
        stack, window_end_date, measured_value
    )
    claim = approve_claim(stack["program"]["id"], claims[0]["id"], approver_user_id)
    return stack, event, claim


def setup_paid_claim(
    stack=None,
    window_end_date=TEST_DEFAULTS["WINDOW_END_DATE"],
    measured_value=40,
    approver_user_id="adjuster-1",
    releaser_user_id="treasury-1",
    **stack_kwargs,
):
    """Full stack through claim PAID (no treaties -> cession is zero).
    Returns (stack, event, claim)."""
    stack, event, claim = setup_approved_claim(
        stack, window_end_date, measured_value, approver_user_id, **stack_kwargs
    )
    from .test_users import make_treasury_officer_headers
    resp = api_client.release_payment(
        stack["program"]["id"], claim["id"], make_treasury_officer_headers(releaser_user_id)
    )
    claim = get_success_data(resp)
    return stack, event, claim


# ---------------------------------------------------------------------------
# Tier 4: treaties
# ---------------------------------------------------------------------------

def create_and_bind_treaty(program_id, **overrides):
    """Create a treaty proposal and bind it (OCC reads the fresh version).
    Returns the ACTIVE treaty dict."""
    treaty = get_success_data(
        api_client.create_treaty(program_id, create_treaty_payload(**overrides), PM)
    )
    program = get_success_data(api_client.get_program(program_id, PM))
    resp = api_client.bind_treaty(
        program_id, treaty["id"], {"expected_program_version": program["version"]}, PM
    )
    return get_success_data(resp)
