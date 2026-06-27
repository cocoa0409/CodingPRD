"""Composite setup helpers for multi-step test prerequisites.

Every test runs against a freshly restarted, empty server, so each fixture builds
all of its own state from PRD-declared endpoints. Uses get_success_data()
(lenient) for setup calls so a setup break surfaces as a clear "Setup failed".

Identity threading: Server and Client are entity_backed. Any ownership-gated call
(accept, attempts, services, stakeouts, sign, ...) passes make_server_headers(
server_id) / make_client_headers(client_id) with the real entity id, never the
shared constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_client_payload,
    create_county_payload,
    create_server_payload,
    create_service_request_payload,
    create_document_payload,
    offer_assignment_payload,
    create_attempt_payload,
    record_service_payload,
    create_filing_payload,
)
from .test_users import (
    TEST_USERS,
    make_server_headers,
    make_notary_headers,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


# ─── Atomic reference-data builders ───────────────────────────────────────
def make_county(**overrides) -> dict:
    return get_success_data(api_client.create_county(create_county_payload(**overrides), ADMIN))


def make_client(deposit_cents: int = 0, **overrides) -> dict:
    client = get_success_data(api_client.create_client(create_client_payload(**overrides), ADMIN))
    if deposit_cents:
        client = get_success_data(
            api_client.deposit(client["id"], {"amount_cents": deposit_cents}, ADMIN)
        )
    return client


def make_server(**overrides) -> dict:
    return get_success_data(api_client.create_server(create_server_payload(**overrides), ADMIN))


def grant_territory(server_id: str, county_id: str) -> dict:
    return get_success_data(
        api_client.create_territory(server_id, {"county_id": county_id}, ADMIN)
    )


# ─── Tier 2: reference scenario (county + covering server + funded client) ──
def setup_reference_data(
    deposit_cents: int = 100_000,
    county_overrides: dict = None,
    server_overrides: dict = None,
):
    """Active county + one server covering it + one funded client.

    Returns (county, server, client). The server already has a ServerTerritory
    for the county, so offers to it pass the territory check.
    """
    county = make_county(**(county_overrides or {}))
    server = make_server(**(server_overrides or {}))
    grant_territory(server["id"], county["id"])
    client = make_client(deposit_cents=deposit_cents)
    return county, server, client


# ─── Tier 1/3: ServiceRequest state-progression shortcuts ──────────────────
def create_draft_request(client_id, county_id, documents=None, **sr_overrides) -> dict:
    """Create a DRAFT request and attach documents (default one 1-page SUMMONS).

    `documents` is a list of dicts merged into create_document_payload.
    """
    sr = get_success_data(
        api_client.create_service_request(
            create_service_request_payload(client_id, county_id, **sr_overrides), DISPATCHER
        )
    )
    docs = documents if documents is not None else [{"doc_type": "SUMMONS", "page_count": 1}]
    for d in docs:
        get_success_data(
            api_client.create_document(sr["id"], create_document_payload(**d), DISPATCHER)
        )
    return sr


def create_submitted_request(client_id, county_id, documents=None, **sr_overrides) -> dict:
    """DRAFT → SUBMITTED. Returns the submitted request (carrying its version)."""
    sr = create_draft_request(client_id, county_id, documents=documents, **sr_overrides)
    return get_success_data(api_client.submit_request(sr["id"], DISPATCHER))


def offer_to_server(sr_id, server_id, expected_version) -> dict:
    """Create an OFFERED assignment (OCC-guarded). Returns the assignment."""
    return get_success_data(
        api_client.offer_assignment(
            sr_id, offer_assignment_payload(server_id, expected_version), DISPATCHER
        )
    )


def setup_active_assignment(
    deposit_cents: int = 100_000,
    county_overrides: dict = None,
    server_overrides: dict = None,
    documents=None,
    **sr_overrides,
):
    """Drive a request all the way to an ACTIVE assignment (request == ASSIGNED).

    Returns (county, server, client, sr, assignment). The sr dict is the
    SUBMITTED snapshot (its version is the value used for the offer).
    """
    county, server, client = setup_reference_data(
        deposit_cents=deposit_cents,
        county_overrides=county_overrides,
        server_overrides=server_overrides,
    )
    sr = create_submitted_request(client["id"], county["id"], documents=documents, **sr_overrides)
    asg = offer_to_server(sr["id"], server["id"], sr["version"])
    get_success_data(
        api_client.accept_assignment(asg["id"], make_server_headers(server["id"]))
    )
    return county, server, client, sr, asg


def log_attempt(assignment_id, server_id, attempted_at_utc, outcome, **overrides):
    """Log one attempt on an ACTIVE assignment (server-owned)."""
    return get_success_data(
        api_client.create_attempt(
            assignment_id,
            create_attempt_payload(attempted_at_utc, outcome, **overrides),
            make_server_headers(server_id),
        )
    )


# ─── Tier 3: drive to SERVED / affidavit lifecycle ─────────────────────────
def setup_served_request(
    deposit_cents: int = 100_000,
    county_overrides: dict = None,
    service_type: str = "PERSONAL",
    served_at_utc: str = "2026-01-01T09:05:00Z",
    contact_attempt_at: str = "2026-01-01T09:00:00Z",
    documents=None,
    **sr_overrides,
):
    """Drive a request to SERVED via a single CONTACT_MADE attempt + PERSONAL
    service. Returns (county, server, client, sr, assignment, affidavit).

    The affidavit is the auto-created DRAFT affidavit. County defaults to
    min_diligent_attempts=1 unless overridden.
    """
    co = {"min_diligent_attempts": 1}
    co.update(county_overrides or {})
    county, server, client, sr, asg = setup_active_assignment(
        deposit_cents=deposit_cents,
        county_overrides=co,
        documents=documents,
        **sr_overrides,
    )
    log_attempt(asg["id"], server["id"], contact_attempt_at, "CONTACT_MADE")
    get_success_data(
        api_client.record_service(
            sr["id"],
            record_service_payload(asg["id"], service_type, served_at_utc),
            make_server_headers(server["id"]),
        )
    )
    affidavits = get_success_data(
        api_client.list_request_affidavits(sr["id"], make_server_headers(server["id"]))
    )
    affidavit = affidavits[0]
    return county, server, client, sr, asg, affidavit


def setup_notarized_request(
    deposit_cents: int = 100_000,
    county_overrides: dict = None,
    notary_user_id: str = "notary-fixture",
    documents=None,
    **sr_overrides,
):
    """SERVED request whose affidavit is SIGNED then NOTARIZED.

    Returns (county, server, client, sr, assignment, affidavit). The notary id
    is distinct from the declarant server, satisfying separation of duties.
    """
    county, server, client, sr, asg, affidavit = setup_served_request(
        deposit_cents=deposit_cents,
        county_overrides=county_overrides,
        documents=documents,
        **sr_overrides,
    )
    get_success_data(
        api_client.sign_affidavit(affidavit["id"], make_server_headers(server["id"]))
    )
    affidavit = get_success_data(
        api_client.notarize_affidavit(affidavit["id"], make_notary_headers(notary_user_id))
    )
    return county, server, client, sr, asg, affidavit


def create_filing(sr_id, affidavit_id, window_start_utc, window_end_utc) -> dict:
    return get_success_data(
        api_client.create_filing(
            sr_id,
            create_filing_payload(affidavit_id, window_start_utc, window_end_utc),
            DISPATCHER,
        )
    )


def setup_submitted_filing(
    deposit_cents: int = 100_000,
    county_overrides: dict = None,
    notary_user_id: str = "notary-fixture",
    window_start_utc: str = "2026-01-02T00:00:00Z",
    window_end_utc: str = "2026-01-02T01:00:00Z",
    documents=None,
    **sr_overrides,
):
    """NOTARIZED request with a Filing driven PENDING → SUBMITTED in an e-file
    county. Returns (county, server, client, sr, assignment, affidavit, filing).
    County defaults to e_file_enabled=true, min_diligent_attempts=1.
    """
    co = {"e_file_enabled": True, "min_diligent_attempts": 1}
    co.update(county_overrides or {})
    county, server, client, sr, asg, affidavit = setup_notarized_request(
        deposit_cents=deposit_cents,
        county_overrides=co,
        notary_user_id=notary_user_id,
        documents=documents,
        **sr_overrides,
    )
    filing = create_filing(sr["id"], affidavit["id"], window_start_utc, window_end_utc)
    filing = get_success_data(
        api_client.set_filing_state(filing["id"], {"to_status": "SUBMITTED"}, DISPATCHER)
    )
    return county, server, client, sr, asg, affidavit, filing


def setup_filed_request(
    deposit_cents: int = 100_000,
    county_overrides: dict = None,
    notary_user_id: str = "notary-fixture",
    documents=None,
    **sr_overrides,
):
    """Full chain to a FILED request: filing SUBMITTED → ACCEPTED bubbles the
    request SERVED → FILED. Returns
    (county, server, client, sr, assignment, affidavit, filing).
    """
    county, server, client, sr, asg, affidavit, filing = setup_submitted_filing(
        deposit_cents=deposit_cents,
        county_overrides=county_overrides,
        notary_user_id=notary_user_id,
        documents=documents,
        **sr_overrides,
    )
    filing = get_success_data(
        api_client.set_filing_state(filing["id"], {"to_status": "ACCEPTED"}, DISPATCHER)
    )
    return county, server, client, sr, asg, affidavit, filing


def get_request(sr_id, headers=None) -> dict:
    return get_success_data(api_client.get_service_request(sr_id, headers or DISPATCHER))


def get_invoice_lines(sr_id, headers=None) -> list:
    return get_success_data(api_client.list_invoice_lines(sr_id, headers or DISPATCHER))


def get_server_entity(server_id, headers=None) -> dict:
    return get_success_data(api_client.get_server(server_id, headers or DISPATCHER))
