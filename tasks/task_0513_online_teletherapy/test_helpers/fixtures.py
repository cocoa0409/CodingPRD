"""Composite setup helpers.

These encapsulate the multi-step preambles the difficulty- and corner-design
recipes share: set the logical clock, register a client and submit intake,
onboard/license/activate a therapist, propose and accept a match, create and
charge a subscription (which grants credits), schedule live sessions, and read
the OCC version of a match or subscription. They use get_success_data()
(lenient) internally so a setup misstep surfaces as a clear "Setup failed"
rather than a confusing assertion error.

Identity threading: Client and Therapist are entity-backed, so every
ownership-gated call uses make_client_headers(client["id"]) /
make_therapist_headers(therapist["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_client_headers,
    make_therapist_headers,
)
from . import factories as F


# --------------------------------------------------------------------------
# Header shortcuts
# --------------------------------------------------------------------------
def _clinical():
    return TEST_USERS["clinical_admin_headers"]


def _billing():
    return TEST_USERS["billing_admin_headers"]


def _client(client_id):
    return make_client_headers(client_id)


def _therapist(therapist_id):
    return make_therapist_headers(therapist_id)


# --------------------------------------------------------------------------
# Tier 0: atomic builders
# --------------------------------------------------------------------------
def set_clock(to_iso8601):
    """Move the logical clock; runs the clock sweep (license/credit/sub recompute)."""
    resp = api_client.set_clock(F.set_clock_payload(to_iso8601), _billing())
    get_success_data(resp)


def create_client(state_code="CA", **overrides):
    """Register a client (PENDING_INTAKE). Returns the Client resource."""
    payload = F.create_client_payload(state_code=state_code, **overrides)
    resp = api_client.create_client(payload, TEST_USERS["client_headers"])
    return get_success_data(resp)


def submit_intake(client_id, severity_score=3, presenting_concerns=None,
                  crisis_indicator=None):
    """Submit the intake questionnaire of record for a client."""
    extra = {}
    if presenting_concerns is not None:
        extra["presenting_concerns"] = list(presenting_concerns)
    if crisis_indicator is not None:
        extra["crisis_indicator"] = crisis_indicator
    payload = F.submit_intake_payload(severity_score=severity_score, **extra)
    resp = api_client.submit_intake(client_id, payload, _client(client_id))
    return get_success_data(resp)


def clear_intake(client_id):
    resp = api_client.clear_intake(client_id, _clinical())
    return get_success_data(resp)


def get_client(client_id):
    resp = api_client.get_client(client_id, _client(client_id))
    return get_success_data(resp)


def create_therapist(specialties=None, max_active_caseload=None, full_name="Test Therapist"):
    """Onboard a therapist (ONBOARDING). Returns the Therapist resource."""
    extra = {}
    if specialties is not None:
        extra["specialties"] = list(specialties)
    if max_active_caseload is not None:
        extra["max_active_caseload"] = max_active_caseload
    payload = F.create_therapist_payload(full_name=full_name, **extra)
    resp = api_client.create_therapist(payload, _clinical())
    return get_success_data(resp)


def add_license(therapist_id, state_code="CA", expires_on="2027-01-01T00:00:00Z"):
    payload = F.create_license_payload(state_code=state_code, expires_on=expires_on)
    resp = api_client.create_license(therapist_id, payload, _clinical())
    return get_success_data(resp)


def activate_therapist(therapist_id):
    resp = api_client.activate_therapist(therapist_id, _clinical())
    return get_success_data(resp)


def get_therapist(therapist_id):
    resp = api_client.get_therapist(therapist_id, _clinical())
    return get_success_data(resp)


def get_match(match_id):
    resp = api_client.get_match(match_id, _clinical())
    return get_success_data(resp)


def get_match_version(match_id):
    return get_match(match_id)["version"]


def get_subscription(subscription_id, client_id):
    resp = api_client.get_subscription(subscription_id, _client(client_id))
    return get_success_data(resp)


def get_subscription_version(subscription_id, client_id):
    return get_subscription(subscription_id, client_id)["version"]


# --------------------------------------------------------------------------
# Tier 1: cleared client ready to match
# --------------------------------------------------------------------------
def cleared_client(state_code="CA", severity_score=3, presenting_concerns=None):
    """Register a client and submit a non-gating intake so they reach
    AWAITING_MATCH. Returns the Client resource (re-fetched, status updated)."""
    client = create_client(state_code=state_code)
    submit_intake(client["id"], severity_score=severity_score,
                  presenting_concerns=presenting_concerns)
    return get_client(client["id"])


def accepting_therapist(state_code="CA", specialties=None, max_active_caseload=None,
                        full_name="Test Therapist"):
    """Onboard a therapist with a VALID license for `state_code` and activate
    them (ACCEPTING). Returns the Therapist resource (re-fetched)."""
    t = create_therapist(specialties=specialties, max_active_caseload=max_active_caseload,
                         full_name=full_name)
    add_license(t["id"], state_code=state_code)
    activate_therapist(t["id"])
    return get_therapist(t["id"])


# --------------------------------------------------------------------------
# Tier 2: proposed / active matches
# --------------------------------------------------------------------------
def propose_match(client_id, therapist_id):
    """ClinicalAdmin proposes a match (PROPOSED). Returns the Match resource."""
    payload = F.create_match_payload(client_id, therapist_id)
    resp = api_client.create_match(payload, _clinical())
    return get_success_data(resp)


def accept_match(match_id, client_id):
    """Client accepts a proposed match (PROPOSED -> ACTIVE). Returns the Match."""
    resp = api_client.accept_match(match_id, _client(client_id))
    return get_success_data(resp)


def active_match(state_code="CA", client_severity=3, client_concerns=None,
                 therapist_specialties=None, therapist_max_caseload=None):
    """Cleared client + accepting licensed therapist + an ACTIVE match (and its
    OPEN thread). Returns (client, therapist, match) where match is the accepted
    Match (with its post-accept version)."""
    client = cleared_client(state_code=state_code, severity_score=client_severity,
                            presenting_concerns=client_concerns)
    therapist = accepting_therapist(state_code=state_code,
                                    specialties=therapist_specialties,
                                    max_active_caseload=therapist_max_caseload)
    proposed = propose_match(client["id"], therapist["id"])
    match = accept_match(proposed["id"], client["id"])
    return client, therapist, match


def get_thread(match_id, client_id):
    """Fetch the match's thread (array of 0-1). Returns the first thread dict."""
    resp = api_client.get_match_thread(match_id, _client(client_id))
    data = get_success_data(resp)
    return data[0] if isinstance(data, list) else data


# --------------------------------------------------------------------------
# Tier 3: subscriptions + billing (granting credits)
# --------------------------------------------------------------------------
def create_subscription(client_id, base_weekly_fee_cents=None, weekly_credit_grant=None):
    """Create a TRIALING subscription. Returns the Subscription resource."""
    extra = {}
    if base_weekly_fee_cents is not None:
        extra["base_weekly_fee_cents"] = base_weekly_fee_cents
    if weekly_credit_grant is not None:
        extra["weekly_credit_grant"] = weekly_credit_grant
    payload = F.create_subscription_payload(client_id, **extra)
    resp = api_client.create_subscription(payload, _client(client_id))
    return get_success_data(resp)


def charge_cycle(subscription_id):
    """BillingAdmin charges a billing cycle. Returns the BillingCycle resource."""
    resp = api_client.charge_cycle(subscription_id, _billing())
    return get_success_data(resp)


def subscription_with_paid_cycle(client_id, base_weekly_fee_cents=None,
                                 weekly_credit_grant=None):
    """Create a subscription and charge its first cycle (TRIALING -> ACTIVE,
    grants credits). Returns (subscription, first_cycle) — both re-fetched as the
    charge response objects."""
    sub = create_subscription(client_id, base_weekly_fee_cents=base_weekly_fee_cents,
                              weekly_credit_grant=weekly_credit_grant)
    cycle = charge_cycle(sub["id"])
    return sub, cycle


def approve_financial_aid(client_id, annual_income_cents, household_size):
    """Submit and approve a financial-aid application (bands tier onto client).
    Returns the approved FinancialAidApplication resource."""
    payload = F.create_financial_aid_payload(annual_income_cents, household_size)
    resp = api_client.create_financial_aid_application(client_id, payload, _client(client_id))
    app = get_success_data(resp)
    approved = api_client.approve_financial_aid(app["id"], _billing())
    return get_success_data(approved)


# --------------------------------------------------------------------------
# Tier 4: live sessions
# --------------------------------------------------------------------------
def schedule_session(match_id, client_id, starts_at, ends_at, expected_match_version=None):
    """Schedule a live session against an ACTIVE match (reserves a credit).
    Reads the live match version when not supplied. Returns the LiveSession."""
    if expected_match_version is None:
        expected_match_version = get_match_version(match_id)
    payload = F.schedule_live_session_payload(starts_at, ends_at, expected_match_version)
    resp = api_client.schedule_live_session(match_id, payload, _client(client_id))
    return get_success_data(resp)


def active_match_with_credits(state_code="CA", weekly_credit_grant=1,
                              base_weekly_fee_cents=None, client_severity=3):
    """Full happy path up to schedulable state: cleared client, accepting
    licensed therapist, ACTIVE match, and a PAID subscription cycle granting
    `weekly_credit_grant` AVAILABLE credits.

    Returns a dict with keys: client, therapist, match, subscription, cycle.
    `match` carries its post-accept version.
    """
    client, therapist, match = active_match(state_code=state_code,
                                            client_severity=client_severity)
    sub, cycle = subscription_with_paid_cycle(
        client["id"], base_weekly_fee_cents=base_weekly_fee_cents,
        weekly_credit_grant=weekly_credit_grant,
    )
    return {
        "client": client,
        "therapist": therapist,
        "match": match,
        "subscription": sub,
        "cycle": cycle,
    }


def count_credits(client_id, status):
    """Count a client's session credits filtered by status."""
    resp = api_client.list_client_session_credits(
        client_id, _client(client_id), params={"status": status}
    )
    data = get_success_data(resp)
    if isinstance(data, list):
        return len(data)
    return 0


# --------------------------------------------------------------------------
# Tier 5: subscriptions in late lifecycle (paused / cancel-scheduled)
# --------------------------------------------------------------------------
def paused_subscription(client_id, subscription_id, resume_on):
    """Pause an ACTIVE subscription (reads the live version). Returns the
    paused Subscription resource."""
    version = get_subscription_version(subscription_id, client_id)
    payload = F.pause_subscription_payload(resume_on, version)
    resp = api_client.pause_subscription(subscription_id, payload, _client(client_id))
    return get_success_data(resp)


def cancel_scheduled_subscription(client_id, subscription_id):
    """Schedule cancellation of an ACTIVE/TRIALING subscription
    (-> CANCEL_SCHEDULED). Returns the Subscription resource."""
    resp = api_client.cancel_subscription(subscription_id, _client(client_id))
    return get_success_data(resp)


# --------------------------------------------------------------------------
# Tier 6: crisis escalation lifecycle
# --------------------------------------------------------------------------
def raise_escalation(client_id, severity="ACUTE", as_clinical=False):
    """Raise a crisis escalation for a client. Returns the CrisisEscalation.
    `as_clinical` raises it as ClinicalAdmin instead of the owning client."""
    headers = _clinical() if as_clinical else _client(client_id)
    payload = F.create_crisis_escalation_payload(severity=severity)
    resp = api_client.create_crisis_escalation(client_id, payload, headers)
    return get_success_data(resp)


def acknowledge_escalation(escalation_id):
    resp = api_client.acknowledge_escalation(escalation_id, _clinical())
    return get_success_data(resp)


# --------------------------------------------------------------------------
# Tier 7: superbills
# --------------------------------------------------------------------------
def draft_superbill(client_id, period_start, period_end):
    payload = F.create_superbill_payload(period_start, period_end)
    resp = api_client.create_superbill(client_id, payload, _billing())
    return get_success_data(resp)


def completed_session_in_window(state_code="CA", weekly_credit_grant=1,
                                base_weekly_fee_cents=None,
                                session_start="2026-06-02T10:00:00Z",
                                session_end="2026-06-02T11:00:00Z"):
    """Set up a client with an ACTIVE match, a PAID cycle, and one COMPLETED
    live session at `session_start`. Returns a dict with keys: client, therapist,
    match, subscription, cycle, live_session. Assumes the clock is already at
    period_start before this call; advances the clock to session_start to allow
    completion.

    NOTE: caller must have set the clock to the subscription period_start before
    invoking, then this advances to session_start for completion.
    """
    info = active_match_with_credits(state_code=state_code,
                                     weekly_credit_grant=weekly_credit_grant,
                                     base_weekly_fee_cents=base_weekly_fee_cents)
    set_clock(session_start)
    ls = schedule_session(info["match"]["id"], info["client"]["id"],
                          session_start, session_end)
    resp = api_client.complete_live_session(ls["id"], _therapist(info["therapist"]["id"]))
    completed = get_success_data(resp)
    info["live_session"] = completed
    return info
