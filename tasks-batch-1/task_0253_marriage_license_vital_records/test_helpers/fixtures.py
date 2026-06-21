"""Composite setup helpers for the Marriage License & Vital Records API.

Each test starts against an empty database (the runner restarts the server before
every test), so every fixture builds its preconditions from scratch using only
PRD-declared endpoints. All setup calls use get_success_data() so setup failures
surface as clear "Setup failed" errors rather than confusing assertion failures.

Identity threading: opaque operator ids (clerk-1, clerk-2, registrar-1, registrar-2,
wo-1) are chosen so segregation-of-duties separations hold by construction. The
Officiant (entity-backed) files returns under make_officiant_headers(officiant_id).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    make_clerk_headers,
    make_registrar_headers,
    make_waiver_officer_headers,
    make_officiant_headers,
    make_applicant_headers,
)
from .factories import (
    create_applicant_payload,
    create_officiant_payload,
    create_application_payload,
    create_return_payload,
    create_certified_copy_payload,
    create_amendment_payload,
    create_apostille_payload,
    create_fee_waiver_payload,
)

# Default operator identities used across fixtures.
CLERK_1 = make_clerk_headers("clerk-1")
CLERK_2 = make_clerk_headers("clerk-2")
REGISTRAR_1 = make_registrar_headers("registrar-1")
REGISTRAR_2 = make_registrar_headers("registrar-2")
WAIVER_OFFICER_1 = make_waiver_officer_headers("wo-1")

# Default clock instants reused by the standard chain.
DEFAULT_ISSUE_CLOCK = "2026-01-10T09:00:00Z"
DEFAULT_CEREMONY_CLOCK = "2026-01-20T12:00:00Z"
DEFAULT_CEREMONY_DATE = "2026-01-20T12:00:00Z"


# ---------------------------------------------------------------------------
# Tier 0: primitives
# ---------------------------------------------------------------------------
def set_clock(iso8601: str):
    """Set the logical clock to an absolute instant."""
    get_success_data(api_client.set_clock({"to_iso8601": iso8601}, CLERK_1))


def advance_clock(iso8601: str):
    """Advance the clock and run the license-expiry sweep."""
    get_success_data(api_client.advance_clock({"to_iso8601": iso8601}, CLERK_1))


def create_applicant(**overrides) -> dict:
    return get_success_data(api_client.create_applicant(create_applicant_payload(**overrides), CLERK_1))


def create_officiant(**overrides) -> dict:
    return get_success_data(api_client.create_officiant(create_officiant_payload(**overrides), CLERK_1))


# ---------------------------------------------------------------------------
# Tier 1: application -> approved -> ISSUED license
# ---------------------------------------------------------------------------
def create_two_applicants(a_overrides=None, b_overrides=None):
    """Two distinct adult applicants (default DOB makes both adults at the
    standard 2026 clock). Returns (applicant_a, applicant_b).

    Caller overrides take precedence over the built-in defaults (so a caller
    may supply its own full_name / date_of_birth without colliding with the
    default keyword arguments)."""
    a_args = {"full_name": "Party A", "date_of_birth": "1990-01-01", **(a_overrides or {})}
    b_args = {"full_name": "Party B", "date_of_birth": "1991-02-02", **(b_overrides or {})}
    a = create_applicant(**a_args)
    b = create_applicant(**b_args)
    return a, b


def create_draft_application(applicant_a_id, applicant_b_id, **overrides) -> dict:
    """Create a DRAFT application linking two applicants."""
    payload = create_application_payload(applicant_a_id, applicant_b_id, **overrides)
    return get_success_data(api_client.create_application(payload, CLERK_1))


def create_under_review_application(applicant_a_id, applicant_b_id, **overrides) -> dict:
    """Create + submit -> UNDER_REVIEW. Submitter is an Applicant party (entity-backed)."""
    app = create_draft_application(applicant_a_id, applicant_b_id, **overrides)
    get_success_data(api_client.submit_application(app["id"], make_applicant_headers(applicant_a_id)))
    return get_success_data(api_client.get_application(app["id"], CLERK_1))


def setup_issued_license(
    issue_clock=DEFAULT_ISSUE_CLOCK,
    a_overrides=None,
    b_overrides=None,
    is_confidential=False,
    approving_clerk=CLERK_1,
):
    """Standard chain to an ISSUED license.

    set clock -> two applicants -> application (is_confidential) -> submit ->
    approve (by approving_clerk) -> fetch the license.

    Returns dict: applicant_a, applicant_b, application, license.
    """
    set_clock(issue_clock)
    a, b = create_two_applicants(a_overrides, b_overrides)
    app = create_draft_application(a["id"], b["id"], is_confidential=is_confidential)
    get_success_data(api_client.submit_application(app["id"], make_applicant_headers(a["id"])))
    get_success_data(api_client.decide_application(app["id"], {"decision": "APPROVE"}, approving_clerk))
    app = get_success_data(api_client.get_application(app["id"], CLERK_1))
    licenses = get_success_data(api_client.list_application_licenses(app["id"], CLERK_1))
    return {
        "applicant_a": a,
        "applicant_b": b,
        "application": app,
        "license": licenses[0],
    }


# ---------------------------------------------------------------------------
# Tier 2: license -> SUBMITTED return
# ---------------------------------------------------------------------------
def setup_submitted_return(
    issue_clock=DEFAULT_ISSUE_CLOCK,
    ceremony_clock=DEFAULT_CEREMONY_CLOCK,
    ceremony_date=DEFAULT_CEREMONY_DATE,
    officiant_overrides=None,
    is_confidential=False,
):
    """ISSUED license + a registered officiant + a SUBMITTED return at ceremony_date.

    Returns dict adding: officiant, return.
    """
    base = setup_issued_license(issue_clock=issue_clock, is_confidential=is_confidential)
    officiant = create_officiant(**(officiant_overrides or {}))
    set_clock(ceremony_clock)
    ret = get_success_data(api_client.create_return(
        create_return_payload(base["license"]["id"], officiant["id"], ceremony_date),
        make_officiant_headers(officiant["id"]),
    ))
    base["officiant"] = officiant
    base["return"] = ret
    return base


# ---------------------------------------------------------------------------
# Tier 3: accepted return -> REGISTERED record
# ---------------------------------------------------------------------------
def setup_registered_record(
    issue_clock=DEFAULT_ISSUE_CLOCK,
    ceremony_clock=DEFAULT_CEREMONY_CLOCK,
    ceremony_date=DEFAULT_CEREMONY_DATE,
    officiant_overrides=None,
    is_confidential=False,
    accepting_registrar=REGISTRAR_1,
):
    """Full chain to a REGISTERED MarriageRecord.

    ISSUED license -> SUBMITTED return -> accept (registrar, segregated from the
    approving clerk) -> the cascade registers a record. Returns dict adding: record.
    """
    base = setup_submitted_return(
        issue_clock=issue_clock,
        ceremony_clock=ceremony_clock,
        ceremony_date=ceremony_date,
        officiant_overrides=officiant_overrides,
        is_confidential=is_confidential,
    )
    get_success_data(api_client.accept_return(base["return"]["id"], accepting_registrar))
    records = get_success_data(api_client.list_records(CLERK_1, params={"return_id": base["return"]["id"]}))
    base["return"] = get_success_data(api_client.get_return(base["return"]["id"], CLERK_1))
    base["license"] = get_success_data(api_client.get_license(base["license"]["id"], CLERK_1))
    base["record"] = records[0]
    return base


# ---------------------------------------------------------------------------
# Tier 4: certified copies & waivers
# ---------------------------------------------------------------------------
def setup_pending_copy(
    requester_kind="PUBLIC",
    copies_requested=1,
    fee_waiver_id=None,
    is_confidential=False,
):
    """REGISTERED record + a PENDING certified-copy request. Returns dict adding:
    copy, record_version (the record version captured right after the request)."""
    base = setup_registered_record(is_confidential=is_confidential)
    payload = create_certified_copy_payload(
        base["record"]["id"], requester_kind, copies_requested,
    )
    if fee_waiver_id is not None:
        payload["fee_waiver_id"] = fee_waiver_id
    copy = get_success_data(api_client.create_certified_copy(payload, CLERK_1))
    rec = get_success_data(api_client.get_record(base["record"]["id"], CLERK_1))
    base["copy"] = copy
    base["record"] = rec
    base["record_version"] = rec["version"]
    return base


def request_fee_waiver(applicant_id, income_cents, household_size=1) -> dict:
    """Create a REQUESTED fee waiver."""
    return get_success_data(api_client.create_fee_waiver(
        create_fee_waiver_payload(applicant_id, income_cents, household_size), CLERK_1,
    ))


def grant_fee_waiver(waiver_id, officer=WAIVER_OFFICER_1) -> dict:
    """Grant a REQUESTED waiver (computes max_waivable_cents)."""
    return get_success_data(api_client.decide_fee_waiver(waiver_id, {"decision": "GRANT"}, officer))


def setup_granted_waiver_for_party(income_cents=100000, household_size=1):
    """REGISTERED record + a GRANTED waiver belonging to applicant_a (a party of
    the record). Returns dict adding: waiver."""
    base = setup_registered_record()
    waiver = request_fee_waiver(base["applicant_a"]["id"], income_cents, household_size)
    waiver = grant_fee_waiver(waiver["id"])
    base["waiver"] = waiver
    return base


def issue_copy(copy_id, expected_record_version=None, expected_waiver_version=None,
               issuing_clerk=CLERK_2) -> dict:
    """Issue a PENDING certified copy (PENDING -> ISSUED) with optional version pins."""
    payload = {"decision": "ISSUE"}
    if expected_record_version is not None:
        payload["expected_record_version"] = expected_record_version
    if expected_waiver_version is not None:
        payload["expected_waiver_version"] = expected_waiver_version
    return get_success_data(api_client.decide_certified_copy(copy_id, payload, issuing_clerk))


# ---------------------------------------------------------------------------
# Tier 5: amendments
# ---------------------------------------------------------------------------
def setup_submitted_amendment(amendment_type="CLERICAL", new_value="Corrected Name"):
    """REGISTERED record + a SUBMITTED amendment by applicant_a. Returns dict adding:
    amendment."""
    base = setup_registered_record()
    amendment = get_success_data(api_client.create_amendment(
        create_amendment_payload(base["record"]["id"], amendment_type, new_value=new_value),
        make_applicant_headers(base["applicant_a"]["id"]),
    ))
    base["amendment"] = amendment
    return base


def cycle_amendment_once(amendment_id, applicant_id):
    """RETURN then resubmit one amendment cycle (resubmit_count += 1). Returns the
    amendment after resubmission."""
    get_success_data(api_client.decide_amendment(amendment_id, {"decision": "RETURN"}, REGISTRAR_1))
    get_success_data(api_client.resubmit_amendment(amendment_id, make_applicant_headers(applicant_id)))
    return get_success_data(api_client.get_amendment(amendment_id, CLERK_1))


# ---------------------------------------------------------------------------
# Tier 6: sealed records
# ---------------------------------------------------------------------------
def seal_record(record_id, registrar=REGISTRAR_1):
    """Seal a record (forces is_confidential=true)."""
    return get_success_data(api_client.seal_record(record_id, registrar))


# ---------------------------------------------------------------------------
# Tier 7: apostilles
# ---------------------------------------------------------------------------
def setup_issued_copy_with_apostille(destination_country="France"):
    """REGISTERED record -> issue a PUBLIC 1-copy request -> create a REQUESTED
    apostille on it. Returns dict adding: copy, apostille."""
    base = setup_registered_record()
    copy = get_success_data(api_client.create_certified_copy(
        create_certified_copy_payload(base["record"]["id"], "PUBLIC", 1), CLERK_1,
    ))
    rec = get_success_data(api_client.get_record(base["record"]["id"], CLERK_1))
    copy = issue_copy(copy["id"], expected_record_version=rec["version"])
    apostille = get_success_data(api_client.create_apostille(
        create_apostille_payload(copy["id"], destination_country),
        make_applicant_headers(base["applicant_a"]["id"]),
    ))
    base["copy"] = copy
    base["apostille"] = apostille
    return base
