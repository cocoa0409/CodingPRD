"""Composite setup helpers.

Every fixture builds its preconditions from scratch against a fresh server
using only PRD-declared endpoints, and validates setup calls with the lenient
get_success_data so failures surface as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_attempt_payload,
    create_client_account_payload,
    create_debtor_payload,
    create_filing_request_payload,
    create_jurisdiction_profile_payload,
    create_lien_search_payload,
    create_secured_party_payload,
)
from .test_users import (
    TEST_USERS,
    make_client_manager_headers,
    make_filing_reviewer_headers,
    make_filing_specialist_headers,
)

ADMIN_HEADERS = TEST_USERS["admin_headers"]
SPEC_HEADERS = TEST_USERS["specialist_headers"]
REVIEWER_HEADERS = TEST_USERS["reviewer_headers"]
OFFICER_HEADERS = TEST_USERS["officer_headers"]
ANALYST_HEADERS = TEST_USERS["analyst_headers"]


def _setup_ok(response, what: str):
    data = get_success_data(response)
    assert isinstance(data, dict), (
        f"Setup failed for {what}: {response.status_code} {response.text}"
    )
    return data


# ---------------------------------------------------------------------------
# Tier 0: clock + plain entity creation
# ---------------------------------------------------------------------------

def set_clock_to(iso_timestamp):
    resp = api_client.set_clock({"to_iso8601": iso_timestamp}, ADMIN_HEADERS)
    return _setup_ok(resp, "set clock")


def seed_jurisdiction_profile(**overrides):
    """Register a jurisdiction profile. Defaults are the CA profile values."""
    resp = api_client.create_jurisdiction_profile(
        create_jurisdiction_profile_payload(**overrides), ADMIN_HEADERS)
    return _setup_ok(resp, "jurisdiction profile")


def create_client(name=None):
    """Create a client account. Returns the client dict."""
    payload = create_client_account_payload()
    if name is not None:
        payload["name"] = name
    resp = api_client.create_client_account(payload, ADMIN_HEADERS)
    return _setup_ok(resp, "client account")


def register_debtor(client_id, **overrides):
    """Register a debtor under the client (ownership-gated: ClientManager with the
    client id as X-User-ID). Returns the debtor dict."""
    resp = api_client.create_debtor(
        client_id, create_debtor_payload(**overrides),
        make_client_manager_headers(client_id))
    return _setup_ok(resp, "debtor")


def register_secured_party(client_id, **overrides):
    """Register a secured party under the client. Returns the secured party dict."""
    resp = api_client.create_secured_party(
        client_id, create_secured_party_payload(**overrides),
        make_client_manager_headers(client_id))
    return _setup_ok(resp, "secured party")


def setup_client_world(profile_overrides=None, debtor_overrides=None,
                       secured_party_overrides=None, with_profile=True):
    """Jurisdiction profile + client + debtor + secured party.

    Returns {"profile", "client", "debtor", "secured_party"}.
    """
    profile = seed_jurisdiction_profile(**(profile_overrides or {})) if with_profile else None
    client = create_client()
    debtor = register_debtor(client["id"], **(debtor_overrides or {}))
    secured_party = register_secured_party(client["id"], **(secured_party_overrides or {}))
    return {
        "profile": profile,
        "client": client,
        "debtor": debtor,
        "secured_party": secured_party,
    }


# ---------------------------------------------------------------------------
# Tier 1: FilingRequest state progression
# ---------------------------------------------------------------------------

def create_filing_request(client, debtor, secured_party, **overrides):
    """Intake a NEW_UCC1 (default) filing request. Returns the DRAFT_INTAKE request."""
    payload = create_filing_request_payload(**overrides)
    payload.setdefault("client_id", client["id"])
    payload.setdefault("debtor_id", debtor["id"])
    payload.setdefault("secured_party_id", secured_party["id"])
    resp = api_client.create_filing_request(payload, SPEC_HEADERS)
    return _setup_ok(resp, "filing request")


def create_ucc3_request(kind, client, debtor, secured_party, target_filing_id,
                        expected_target_filing_version=None, **overrides):
    """Intake an AMENDMENT / CONTINUATION / TERMINATION request against a root filing.

    Reads the target's current version for the OCC guard when not supplied.
    """
    if expected_target_filing_version is None:
        expected_target_filing_version = get_filing(target_filing_id)["version"]
    payload = create_filing_request_payload(**overrides)
    payload.update({
        "client_id": client["id"],
        "kind": kind,
        "debtor_id": debtor["id"],
        "secured_party_id": secured_party["id"],
        "target_filing_id": target_filing_id,
        "expected_target_filing_version": expected_target_filing_version,
    })
    resp = api_client.create_filing_request(payload, SPEC_HEADERS)
    return _setup_ok(resp, f"{kind} request")


def submit_intake(request_id, user_id="spec-1", role="FilingSpecialist"):
    """Move a request DRAFT_INTAKE -> IN_REVIEW, recording the submitter's user id."""
    if role == "FilingReviewer":
        headers = make_filing_reviewer_headers(user_id)
    else:
        headers = make_filing_specialist_headers(user_id)
    resp = api_client.submit_intake(request_id, headers)
    return _setup_ok(resp, "submit intake")


def approve_preparation(request_id, reviewer="rev-1"):
    """Move a request IN_REVIEW/CORRECTION_REQUIRED -> READY (snapshots quoted fee)."""
    resp = api_client.approve_preparation(
        request_id, make_filing_reviewer_headers(reviewer))
    return _setup_ok(resp, "approve preparation")


def create_in_review_request(client, debtor, secured_party, intake_user="spec-1",
                             **overrides):
    """Request taken through submit-intake. Returns the IN_REVIEW request."""
    request = create_filing_request(client, debtor, secured_party, **overrides)
    return submit_intake(request["id"], user_id=intake_user)


def create_ready_request(client, debtor, secured_party, intake_user="spec-1",
                         approver="rev-1", **overrides):
    """Request taken through intake + approval. Returns the READY request."""
    request = create_in_review_request(
        client, debtor, secured_party, intake_user=intake_user, **overrides)
    return approve_preparation(request["id"], reviewer=approver)


# ---------------------------------------------------------------------------
# Tier 2/3: attempt lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_draft_attempt(request_id, **overrides):
    """Create a DRAFT attempt under a READY request. Returns the attempt dict."""
    resp = api_client.create_attempt(
        request_id, create_attempt_payload(**overrides), SPEC_HEADERS)
    return _setup_ok(resp, "filing attempt")


def submit_attempt(attempt_id, user_id="spec-1"):
    """Move an attempt DRAFT -> SUBMITTED (locks charged fee, debits the ledger)."""
    resp = api_client.submit_filing(
        attempt_id, make_filing_specialist_headers(user_id))
    return _setup_ok(resp, "attempt submit")


def accept_attempt(attempt_id, filing_number=None, filed_at=None, officer="officer-1"):
    """Record filing-office acceptance. Returns the ACTIVE filing dict."""
    payload = {
        "filing_number": filing_number or TEST_DEFAULTS["FILING_NUMBER"],
        "filed_at": filed_at or TEST_DEFAULTS["CLOCK_START_ISO"],
    }
    resp = api_client.record_acceptance(attempt_id, payload, OFFICER_HEADERS)
    return _setup_ok(resp, "record acceptance")


def reject_attempt(attempt_id, reason="NAME_MISMATCH", note=None):
    """Record filing-office rejection. Returns the REJECTED filing dict."""
    payload = {"rejection_reason_code": reason}
    if note is not None:
        payload["rejection_note"] = note
    resp = api_client.record_rejection(attempt_id, payload, OFFICER_HEADERS)
    return _setup_ok(resp, "record rejection")


def setup_active_initial_filing(world=None, filed_at=None, filing_number=None,
                                secured_amount_cents=None, request_overrides=None,
                                attempt_overrides=None):
    """Full chain: world -> READY NEW_UCC1 request -> DRAFT attempt -> SUBMITTED ->
    ACTIVE INITIAL filing. Returns a context dict with every artifact."""
    if world is None:
        world = setup_client_world()
    request = create_ready_request(
        world["client"], world["debtor"], world["secured_party"],
        **(request_overrides or {}))
    attempt_kwargs = dict(attempt_overrides or {})
    if secured_amount_cents is not None:
        attempt_kwargs["secured_amount_cents"] = secured_amount_cents
    attempt = create_draft_attempt(request["id"], **attempt_kwargs)
    submit_attempt(attempt["id"])
    filing = accept_attempt(
        attempt["id"],
        filing_number=filing_number or TEST_DEFAULTS["FILING_NUMBER"],
        filed_at=filed_at or TEST_DEFAULTS["CLOCK_START_ISO"])
    ctx = dict(world)
    ctx.update({"request": request, "attempt": filing, "filing": filing})
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: searches and reports
# ---------------------------------------------------------------------------

def order_lien_search(client, debtor, jurisdiction_code="CA", purpose="PRE_FILING",
                      subject_filing_id=None, county_name=None):
    """Order a lien search. Returns the ORDERED search dict."""
    payload = create_lien_search_payload(
        client_id=client["id"], debtor_id=debtor["id"],
        jurisdiction_code=jurisdiction_code, purpose=purpose)
    if subject_filing_id is not None:
        payload["subject_filing_id"] = subject_filing_id
    if county_name is not None:
        payload["county_name"] = county_name
    resp = api_client.create_lien_search(payload, SPEC_HEADERS)
    return _setup_ok(resp, "lien search")


def record_search_results(search_id, through_date, hits):
    """Record certified results. Returns the resolved search dict."""
    resp = api_client.record_search_results(
        search_id, {"through_date": through_date, "hits": hits}, ANALYST_HEADERS)
    return _setup_ok(resp, "record search results")


def order_completed_pre_filing_search(client, debtor, through_date, hits=None,
                                      jurisdiction_code="CA"):
    """PRE_FILING search recorded to COMPLETED. Returns the search dict."""
    search = order_lien_search(client, debtor, jurisdiction_code=jurisdiction_code,
                               purpose="PRE_FILING")
    return record_search_results(search["id"], through_date, hits or [])


def generate_report(client_id, mode="AS_OF_NOW", horizon_days=90, user_id=None):
    """Generate a perfection report (ClientManager is entity-backed on this path)."""
    payload = {"mode": mode, "horizon_days": horizon_days}
    resp = api_client.create_perfection_report(
        client_id, payload, make_client_manager_headers(user_id or client_id))
    return _setup_ok(resp, "perfection report")


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def get_filing(filing_id):
    return _setup_ok(api_client.get_filing(filing_id, ADMIN_HEADERS), "filing get")


def get_request(request_id):
    return _setup_ok(api_client.get_filing_request(request_id, ADMIN_HEADERS),
                     "request get")


def get_client_account(client_id):
    return _setup_ok(api_client.get_client_account(client_id, ADMIN_HEADERS),
                     "client get")


def get_search(search_id):
    return _setup_ok(api_client.get_lien_search(search_id, ADMIN_HEADERS),
                     "search get")


def list_filing_events(filing_id):
    resp = api_client.list_filing_events(filing_id, ADMIN_HEADERS)
    data = get_success_data(resp)
    assert isinstance(data, list), f"Setup failed for event list: {resp.status_code}"
    return data
