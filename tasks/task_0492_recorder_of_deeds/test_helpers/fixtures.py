"""Composite setup helpers.

Each helper builds preconditions from scratch using only PRD-declared endpoints.
The test harness restarts the server (empty DB) before every test, so nothing is
shared across tests. Helpers use get_success_data() (lenient) so setup failures
surface as clear "Setup failed" errors.

Identity threading: the Submitter role is entity_backed, so every ownership-gated
call uses make_submitter_headers(submitter["id"]). Opaque roles (Examiner, Recorder,
Clerk) use fixed operator ids by default but may be overridden for segregation tests.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    make_submitter_headers, make_examiner_headers,
    make_recorder_headers, make_clerk_headers,
)
from . import factories


# --- Default opaque operator ids ---
EX_USER = "ex-1"
REC_USER = "rec-1"
CLERK_USER = "clerk-1"


def _clerk():
    return make_clerk_headers(CLERK_USER)


def _examiner(user_id=EX_USER):
    return make_examiner_headers(user_id)


def _recorder(user_id=REC_USER):
    return make_recorder_headers(user_id)


# ---------------------------------------------------------------------------
# Tier 1/2: base entity setup
# ---------------------------------------------------------------------------
def create_office(book_capacity=3, instrument_seq_start=None, county_name="Acme"):
    """Create a RecordingOffice. Returns the office dict."""
    payload = factories.create_office_payload(
        county_name=county_name, book_capacity=book_capacity
    )
    if instrument_seq_start is not None:
        payload["instrument_seq_start"] = instrument_seq_start
    return get_success_data(api_client.create_office(payload, _clerk()))


def create_submitter(name="Title Co", submitter_type="TITLE_COMPANY"):
    """Register an ACTIVE Submitter. Returns the submitter dict."""
    payload = factories.create_submitter_payload(name=name, submitter_type=submitter_type)
    return get_success_data(api_client.create_submitter(payload, _clerk()))


def deposit_escrow(office_id, submitter_id, amount_cents):
    """Credit escrow to a submitter via the office cashier. Returns updated submitter."""
    payload = factories.deposit_escrow_payload(submitter_id, amount_cents)
    return get_success_data(api_client.deposit_escrow(office_id, payload, _clerk()))


def suspend_submitter(submitter_id):
    """Suspend a submitter. Returns updated submitter."""
    return get_success_data(api_client.suspend_submitter(submitter_id, _clerk()))


def set_clock(to_iso8601):
    """Advance the logical clock."""
    return api_client.set_clock(to_iso8601, _clerk())


def setup_office_and_submitter(book_capacity=3, instrument_seq_start=None,
                               submitter_name="Title Co", submitter_type="TITLE_COMPANY",
                               escrow_cents=0):
    """Office + ACTIVE submitter, optionally funded with escrow.
    Returns (office, submitter)."""
    office = create_office(book_capacity=book_capacity,
                           instrument_seq_start=instrument_seq_start)
    submitter = create_submitter(name=submitter_name, submitter_type=submitter_type)
    if escrow_cents:
        submitter = deposit_escrow(office["id"], submitter["id"], escrow_cents)
    return office, submitter


# ---------------------------------------------------------------------------
# Tier 3: DocumentPackage lifecycle shortcuts
# ---------------------------------------------------------------------------
def create_package(office_id, submitter_id, doc_type="DEED", declared_page_count=1,
                   declared_consideration_cents=0, first_page_top_margin_inches=3.0,
                   notary_present=True, **extra):
    """Submit a DocumentPackage. Returns the package dict."""
    payload = factories.create_package_payload(
        submitter_id, office_id,
        doc_type=doc_type,
        declared_page_count=declared_page_count,
        declared_consideration_cents=declared_consideration_cents,
        first_page_top_margin_inches=first_page_top_margin_inches,
        notary_present=notary_present,
        **extra,
    )
    return get_success_data(api_client.create_package(payload, make_submitter_headers(submitter_id)))


def add_party(package_id, submitter_id, party_role, party_name):
    """Add a PartyEntry. Returns the entry dict."""
    payload = factories.party_entry_payload(party_role, party_name)
    return get_success_data(
        api_client.add_party_entry(package_id, payload, make_submitter_headers(submitter_id))
    )


def add_grantor_grantee(package_id, submitter_id,
                        grantor_name="G", grantee_name="E"):
    """Add one GRANTOR and one GRANTEE entry (the minimum complete index)."""
    add_party(package_id, submitter_id, "GRANTOR", grantor_name)
    add_party(package_id, submitter_id, "GRANTEE", grantee_name)


def create_package_in_examination(office_id, submitter_id, *, doc_type="DEED",
                                  declared_page_count=1, declared_consideration_cents=0,
                                  first_page_top_margin_inches=3.0, notary_present=True,
                                  grantors=("G",), grantees=("E",)):
    """Submit a package, add the named GRANTOR/GRANTEE entries, and begin examination.
    Returns the package dict as observed after begin-examination (carries current version).
    """
    pkg = create_package(
        office_id, submitter_id, doc_type=doc_type,
        declared_page_count=declared_page_count,
        declared_consideration_cents=declared_consideration_cents,
        first_page_top_margin_inches=first_page_top_margin_inches,
        notary_present=notary_present,
    )
    for i, name in enumerate(grantors):
        add_party(pkg["id"], submitter_id, "GRANTOR", name)
    for i, name in enumerate(grantees):
        add_party(pkg["id"], submitter_id, "GRANTEE", name)
    return get_success_data(api_client.begin_examination(pkg["id"], _examiner()))


def assess_package(package_id, verified_page_count, verified_consideration_cents,
                   expected_package_version, examiner_user_id=EX_USER):
    """Finalize a FeeAssessment. Returns the assessment dict."""
    payload = factories.assessment_payload(
        verified_page_count, verified_consideration_cents, expected_package_version
    )
    return get_success_data(
        api_client.create_assessment(package_id, payload, _examiner(examiner_user_id))
    )


def create_assessed_package(office_id, submitter_id, *, doc_type="DEED",
                            declared_page_count=1, verified_page_count=1,
                            verified_consideration_cents=0, declared_consideration_cents=0,
                            first_page_top_margin_inches=3.0, notary_present=True,
                            grantors=("G",), grantees=("E",), examiner_user_id=EX_USER):
    """Drive a package to ASSESSED. Returns (package_after_assess, assessment).
    The returned package is the GET observed after assessment (carries fresh version)."""
    pkg = create_package_in_examination(
        office_id, submitter_id, doc_type=doc_type,
        declared_page_count=declared_page_count,
        declared_consideration_cents=declared_consideration_cents,
        first_page_top_margin_inches=first_page_top_margin_inches,
        notary_present=notary_present, grantors=grantors, grantees=grantees,
    )
    assessment = assess_package(
        pkg["id"], verified_page_count, verified_consideration_cents,
        pkg["version"], examiner_user_id=examiner_user_id,
    )
    pkg_after = get_success_data(
        api_client.get_package(pkg["id"], make_submitter_headers(submitter_id))
    )
    return pkg_after, assessment


def pay_package(package_id, submitter_id, amount_cents, expected_package_version,
                method="ESCROW"):
    """Capture a Payment against an ASSESSED package. Returns the payment dict."""
    payload = factories.payment_payload(amount_cents, method, expected_package_version)
    return get_success_data(
        api_client.create_payment(package_id, payload, make_submitter_headers(submitter_id))
    )


def create_paid_package(office_id, submitter_id, *, doc_type="DEED",
                        declared_page_count=1, verified_page_count=1,
                        verified_consideration_cents=0, first_page_top_margin_inches=3.0,
                        notary_present=True, grantors=("G",), grantees=("E",),
                        amount_cents=None, method="ESCROW", examiner_user_id=EX_USER):
    """Drive a package to PAID. Returns (package_after_pay, assessment, payment).
    amount_cents defaults to the assessment's total_due_cents."""
    pkg_after, assessment = create_assessed_package(
        office_id, submitter_id, doc_type=doc_type,
        declared_page_count=declared_page_count,
        verified_page_count=verified_page_count,
        verified_consideration_cents=verified_consideration_cents,
        first_page_top_margin_inches=first_page_top_margin_inches,
        notary_present=notary_present, grantors=grantors, grantees=grantees,
        examiner_user_id=examiner_user_id,
    )
    if amount_cents is None:
        amount_cents = assessment["total_due_cents"]
    payment = pay_package(
        pkg_after["id"], submitter_id, amount_cents, pkg_after["version"], method=method
    )
    return pkg_after, assessment, payment


def record_package(package_id, recorder_user_id=REC_USER):
    """Record a paid package. Returns the RecordedDocument dict."""
    return get_success_data(api_client.record_package(package_id, _recorder(recorder_user_id)))


def create_recorded_package(office_id, submitter_id, *, doc_type="DEED",
                            declared_page_count=1, verified_page_count=1,
                            verified_consideration_cents=0, first_page_top_margin_inches=3.0,
                            notary_present=True, grantors=("G",), grantees=("E",),
                            examiner_user_id=EX_USER, recorder_user_id=REC_USER):
    """Drive a package all the way to RECORDED.
    Returns (package_id, assessment, recorded_document)."""
    pkg_after, assessment, _payment = create_paid_package(
        office_id, submitter_id, doc_type=doc_type,
        declared_page_count=declared_page_count,
        verified_page_count=verified_page_count,
        verified_consideration_cents=verified_consideration_cents,
        first_page_top_margin_inches=first_page_top_margin_inches,
        notary_present=notary_present, grantors=grantors, grantees=grantees,
        examiner_user_id=examiner_user_id,
    )
    rd = record_package(pkg_after["id"], recorder_user_id=recorder_user_id)
    return pkg_after["id"], assessment, rd


# ---------------------------------------------------------------------------
# Tier 4: rejection / re-record helpers
# ---------------------------------------------------------------------------
def reject_package(package_id, reason_code="MARGIN", detail=None, examiner_user_id=EX_USER):
    """Reject a package under examination. Returns the RejectionNotice dict."""
    payload = factories.reject_payload(reason_code)
    if detail is not None:
        payload["detail"] = detail
    return get_success_data(
        api_client.reject_package(package_id, payload, _examiner(examiner_user_id))
    )


def create_rejected_package(office_id, submitter_id, *, reason_code="MARGIN",
                            first_page_top_margin_inches=3.0, notary_present=True,
                            grantors=("G",), grantees=("E",), examiner_user_id=EX_USER):
    """Drive a package to REJECTED (begin-examination then reject).
    Returns (package_id, rejection_notice)."""
    pkg = create_package_in_examination(
        office_id, submitter_id,
        first_page_top_margin_inches=first_page_top_margin_inches,
        notary_present=notary_present, grantors=grantors, grantees=grantees,
    )
    rn = reject_package(pkg["id"], reason_code=reason_code, examiner_user_id=examiner_user_id)
    return pkg["id"], rn


# ---------------------------------------------------------------------------
# Tier 5: Plats
# ---------------------------------------------------------------------------
def create_plat(office_id, submitter_id, start_lot, end_lot,
                subdivision_name="MAPLE", block_number=1):
    """Submit a PlatSurvey. Returns the plat dict."""
    payload = factories.create_plat_payload(
        submitter_id, office_id, start_lot, end_lot,
        subdivision_name=subdivision_name, block_number=block_number,
    )
    return get_success_data(api_client.create_plat(payload, make_submitter_headers(submitter_id)))


def create_recorded_plat(office_id, submitter_id, start_lot, end_lot,
                         subdivision_name="MAPLE", block_number=1):
    """Submit, approve, and record a plat. Returns the recorded plat dict."""
    plat = create_plat(office_id, submitter_id, start_lot, end_lot,
                       subdivision_name=subdivision_name, block_number=block_number)
    get_success_data(api_client.approve_plat(plat["id"], _examiner()))
    return get_success_data(api_client.record_plat(plat["id"], _recorder()))


# ---------------------------------------------------------------------------
# Tier 5: Lien / UCC filings
# ---------------------------------------------------------------------------
def create_ucc_filing(office_id, submitter_id, lien_type="UCC1", parcel_id="P-1",
                      debtor_name="Debtor A", effective_date="2026-01-01T00:00:00Z"):
    """File a LienUccFiling. Returns the filing dict."""
    payload = factories.create_ucc_filing_payload(
        submitter_id, office_id, lien_type, parcel_id, debtor_name, effective_date
    )
    return get_success_data(api_client.create_ucc_filing(payload, make_submitter_headers(submitter_id)))


# ---------------------------------------------------------------------------
# Tier 5: Copy / search requests
# ---------------------------------------------------------------------------
def create_copy_search_request(submitter_id, request_type, recorded_document_id=None,
                               search_name=None):
    """Create a CopySearchRequest. Returns the request dict."""
    extra = {}
    if recorded_document_id is not None:
        extra["recorded_document_id"] = recorded_document_id
    if search_name is not None:
        extra["search_name"] = search_name
    payload = factories.create_copy_search_payload(submitter_id, request_type, **extra)
    return get_success_data(
        api_client.create_copy_search_request(payload, make_submitter_headers(submitter_id))
    )
