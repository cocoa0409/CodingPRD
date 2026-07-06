"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the system to be walked through several API calls
(fee schedule -> account -> notary -> signer -> request -> documents -> quote ->
assign -> verify -> schedule -> start -> journal -> complete). These helpers
encapsulate those preambles so tests focus on assertions.

Setup uses get_success_data() (lenient) so a broken precondition surfaces as a
clear "Setup failed" rather than a confusing assertion error.

Identity threading: the Notary role is entity-backed. After a notary is created,
every ownership-gated Notary call below uses make_notary_headers(notary["id"]).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_fee_schedule_payload, create_account_payload, create_notary_payload,
    create_signer_payload, create_request_payload, create_document_payload,
    create_ron_session_payload, create_id_verification_payload,
    create_journal_entry_payload, create_loan_package_payload,
    create_apostille_order_payload,
)
from .test_users import TEST_USERS, make_notary_headers

COORD = TEST_USERS["coordinator_headers"]
CLERK = TEST_USERS["apostille_clerk_headers"]
VIEWER = TEST_USERS["viewer_headers"]

# Standard session window helpers (UTC, after the default clock instant).
SESSION_START = "2026-03-02T10:00:00Z"
SESSION_END = "2026-03-02T11:00:00Z"


# ─── Tier 0: Base entities ──────────────────────────────────────────────────

def create_fee_schedule(**overrides):
    """Create a per-state FeeSchedule. Returns the schedule entity."""
    res = api_client.create_fee_schedule(create_fee_schedule_payload(**overrides), COORD)
    return get_success_data(res)


def create_account(**overrides):
    res = api_client.create_account(create_account_payload(**overrides), COORD)
    return get_success_data(res)


def create_notary(account_id, **overrides):
    res = api_client.create_notary(create_notary_payload(account_id, **overrides), COORD)
    return get_success_data(res)


def create_signer(account_id, **overrides):
    res = api_client.create_signer(create_signer_payload(account_id, **overrides), COORD)
    return get_success_data(res)


def create_request(account_id, signer_id, **overrides):
    res = api_client.create_request(create_request_payload(account_id, signer_id, **overrides), COORD)
    return get_success_data(res)


def create_document(request_id, **overrides):
    res = api_client.create_document(create_document_payload(request_id, **overrides), COORD)
    return get_success_data(res)


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, COORD))


# ─── Tier 1: Common world ───────────────────────────────────────────────────

def setup_world(fee_overrides=None, account_overrides=None, notary_overrides=None,
                signer_overrides=None):
    """Fee schedule + account + ACTIVE notary + signer.

    Returns a dict with keys: fee, account, notary, signer.
    """
    fee = create_fee_schedule(**(fee_overrides or {}))
    account = create_account(**(account_overrides or {}))
    notary = create_notary(account["id"], **(notary_overrides or {}))
    signer = create_signer(account["id"], **(signer_overrides or {}))
    return {"fee": fee, "account": account, "notary": notary, "signer": signer}


def setup_world_no_fee(account_overrides=None, notary_overrides=None, signer_overrides=None):
    """Account + ACTIVE notary + signer, with NO fee schedule created."""
    account = create_account(**(account_overrides or {}))
    notary = create_notary(account["id"], **(notary_overrides or {}))
    signer = create_signer(account["id"], **(signer_overrides or {}))
    return {"account": account, "notary": notary, "signer": signer}


# ─── Tier 2: Request lifecycle shortcuts ────────────────────────────────────

def setup_draft_request_with_doc(world=None, request_overrides=None, doc_overrides=None):
    """World + a DRAFT request carrying one document.

    Returns (world, request, document).
    """
    world = world or setup_world()
    request = create_request(world["account"]["id"], world["signer"]["id"],
                             **(request_overrides or {}))
    document = create_document(request["id"], **(doc_overrides or {}))
    return world, request, document


def setup_quoted_request(world=None, request_overrides=None, doc_overrides=None):
    """World + a QUOTED request (one document quoted). Returns (world, request, document).

    The returned request reflects the post-quote body (carries estimate_fee_cents
    and the bumped version).
    """
    world, request, document = setup_draft_request_with_doc(
        world, request_overrides, doc_overrides)
    quoted = get_success_data(api_client.quote_request(request["id"], COORD))
    return world, quoted, document


def setup_assigned_request(world=None, request_overrides=None, doc_overrides=None):
    """World + an ASSIGNED request (quoted then assigned to the world notary).

    Returns (world, request, document).
    """
    world, request, document = setup_quoted_request(world, request_overrides, doc_overrides)
    assigned = get_success_data(api_client.assign_request(
        request["id"],
        {"notary_id": world["notary"]["id"], "expected_request_version": request["version"]},
        COORD,
    ))
    return world, assigned, document


def add_pass_verification(world, request, kba=80, credential=90, biometric=80):
    """Record a PASS IdVerification for (request, request.signer). Returns verification."""
    nheaders = make_notary_headers(world["notary"]["id"])
    res = api_client.create_id_verification(
        create_id_verification_payload(request["id"], world["signer"]["id"],
                                       kba_score=kba, credential_score=credential,
                                       biometric_score=biometric),
        nheaders,
    )
    return get_success_data(res)


def schedule_session(world, request, start=SESSION_START, end=SESSION_END):
    """Schedule a RON session for an ASSIGNED request as the assigned notary."""
    nheaders = make_notary_headers(world["notary"]["id"])
    res = api_client.create_ron_session(
        create_ron_session_payload(request["id"], start, end), nheaders)
    return get_success_data(res)


def setup_scheduled_session(world=None, request_overrides=None, doc_overrides=None,
                            verify=True):
    """World + ASSIGNED request + (optional PASS verification) + SCHEDULED session.

    Returns (world, request, document, session). The session is SCHEDULED /
    NOT_STARTED. When verify=True a PASS IdVerification is also recorded so the
    request is ready for start-session.
    """
    world, request, document = setup_assigned_request(world, request_overrides, doc_overrides)
    if verify:
        add_pass_verification(world, request)
    session = schedule_session(world, request)
    return world, request, document, session


def setup_in_session_request(world=None, request_overrides=None, doc_overrides=None):
    """World through to IN_SESSION (started). Returns (world, request, document, session).

    The session is LIVE / RECORDING after start-session.
    """
    world, request, document, session = setup_scheduled_session(
        world, request_overrides, doc_overrides, verify=True)
    nheaders = make_notary_headers(world["notary"]["id"])
    get_success_data(api_client.start_session(request["id"], nheaders))
    started_session = get_success_data(api_client.get_ron_session(session["id"], VIEWER))
    return world, request, document, started_session


def setup_completed_request(world=None, request_overrides=None, doc_overrides=None,
                            act_types=("ACKNOWLEDGMENT",), complete_payload=None):
    """World through to COMPLETED, recording one journal act per entry in act_types.

    Returns (world, request, document, journal_ids). The returned request body is
    the post-complete body (carries final_fee_cents).
    """
    world, request, document, session = setup_in_session_request(
        world, request_overrides, doc_overrides)
    nheaders = make_notary_headers(world["notary"]["id"])
    journal_ids = []
    for act in act_types:
        je = get_success_data(api_client.create_journal_entry(
            create_journal_entry_payload(request["id"], document["id"], act_type=act),
            nheaders))
        journal_ids.append(je["id"])
    completed = get_success_data(api_client.complete_request(
        request["id"], complete_payload or {}, nheaders))
    return world, completed, document, journal_ids


# ─── Tier 3: Apostille lifecycle ────────────────────────────────────────────

def setup_submitted_apostille(world=None, destination_country="FR",
                              request_overrides=None, doc_overrides=None,
                              complete_request=True):
    """A document marked requires_apostille with a SUBMITTED ApostilleOrder.

    When complete_request is True the wrapped request is driven to COMPLETED first
    (so the order is route-eligible). Returns (world, request, document, order).
    """
    req_over = {"doc_category": "APOSTILLE_BOUND", "delivery_mode": "RON"}
    req_over.update(request_overrides or {})
    doc_over = {"title": "Cert", "doc_type": "BIRTH_CERT",
                "requires_apostille": True, "signing_fee_cents": 1000}
    doc_over.update(doc_overrides or {})

    if complete_request:
        world, request, document, _ = setup_completed_request(
            world, request_overrides=req_over, doc_overrides=doc_over,
            act_types=("ACKNOWLEDGMENT",))
    else:
        world, request, document = setup_draft_request_with_doc(
            world, request_overrides=req_over, doc_overrides=doc_over)

    order = get_success_data(api_client.create_apostille_order(
        create_apostille_order_payload(document["id"],
                                       destination_country=destination_country,
                                       sos_office_state="CA"),
        CLERK))
    return world, request, document, order


def setup_returned_apostille(world=None, destination_country="FR"):
    """An ApostilleOrder driven SUBMITTED -> ROUTED -> RETURNED (resubmit_count 0).

    Returns (world, request, document, order).
    """
    world, request, document, order = setup_submitted_apostille(
        world, destination_country=destination_country, complete_request=True)
    get_success_data(api_client.route_apostille_order(order["id"], CLERK))
    order = get_success_data(api_client.return_apostille_order(order["id"], CLERK))
    return world, request, document, order


# ─── Tier 4: Loan-package lifecycle ─────────────────────────────────────────

def setup_loan_package(world=None, request_overrides=None, doc_specs=None,
                       package_overrides=None):
    """A LOAN_SIGNING request with documents and a DRAFT LoanPackage.

    doc_specs is a list of dicts passed to create_document (defaults to one DEED).
    Returns (world, request, documents, package).
    """
    world = world or setup_world()
    req_over = {"doc_category": "LOAN_SIGNING", "delivery_mode": "MOBILE", "expected_stamp_count": 1}
    req_over.update(request_overrides or {})
    request = create_request(world["account"]["id"], world["signer"]["id"], **req_over)

    if doc_specs is None:
        doc_specs = [{"title": "Deed", "doc_type": "DEED", "signing_fee_cents": 5000}]
    documents = [create_document(request["id"], **spec) for spec in doc_specs]

    nheaders = make_notary_headers(world["notary"]["id"])
    package = get_success_data(api_client.create_loan_package(
        create_loan_package_payload(request["id"], **(package_overrides or {})), nheaders))
    return world, request, documents, package


def scrub_package(world, package):
    nheaders = make_notary_headers(world["notary"]["id"])
    return get_success_data(api_client.scrub_loan_package(package["id"], nheaders))
