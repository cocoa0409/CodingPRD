"""Composite setup helpers used across the test suite.

Every fixture builds its preconditions from scratch against an empty DB. Each
helper uses get_success_data() (lenient) so setup failures produce clear
"Setup step failed" errors instead of confusing assertion failures.
"""
import uuid
from typing import Optional, Tuple, List

from prd_bench_local_runner.testing import get_success_data, validate_success

from .api_client import api_client
from .factories import (
    create_client_payload,
    create_service_agreement_payload,
    create_batch_payload,
    create_box_payload,
    create_document_payload,
    create_scanner_unit_payload,
    create_shelf_slot_payload,
    create_shelf_assignment_payload,
    create_custody_event_payload,
    create_page_log_payload,
    create_index_record_payload,
    create_access_grant_payload,
    create_destruction_certificate_payload,
    create_payment_payload,
    create_void_invoice_payload,
    create_clock_payload,
)
from .test_users import (
    make_platform_admin_headers,
    make_intake_clerk_headers,
    make_prep_technician_headers,
    make_scan_operator_headers,
    make_qa_reviewer_headers,
    make_indexer_headers,
    make_destruction_specialist_headers,
    make_compliance_officer_headers,
    make_billing_clerk_headers,
    make_client_user_headers,
)


# Canonical actor ids (opaque for the 9 bureau roles). Tests may override.
ADMIN = "admin-1"
CLERK = "clerk-1"
PREP = "prep-1"
SCAN = "scan-1"
QA = "qa-1"
IDX = "idx-1"
DS = "ds-1"
CO = "co-1"
BILL = "bill-1"
WITNESS = "wit-1"


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def create_client(name="Test Client", hipaa_covered=False, admin_headers=None):
    headers = admin_headers or make_platform_admin_headers(ADMIN)
    resp = api_client.create_client(
        create_client_payload(name=name, hipaa_covered=hipaa_covered), headers
    )
    return get_success_data(resp)


def create_agreement(client_id, admin_headers=None, **overrides):
    headers = admin_headers or make_platform_admin_headers(ADMIN)
    resp = api_client.create_service_agreement(
        client_id, create_service_agreement_payload(**overrides), headers
    )
    return get_success_data(resp)


def create_client_with_agreement(name="Test Client", hipaa_covered=False, **agreement_overrides):
    """Return (client, agreement)."""
    client = create_client(name=name, hipaa_covered=hipaa_covered)
    agreement = create_agreement(client["id"], **agreement_overrides)
    return client, agreement


def create_batch(client_id, priority="STANDARD", clerk_headers=None):
    headers = clerk_headers or make_intake_clerk_headers(CLERK)
    resp = api_client.create_batch(
        create_batch_payload(client_id=client_id, priority=priority), headers
    )
    return get_success_data(resp)


def create_box(batch_id, box_label="BX-1", intake_weight_grams=600, clerk_headers=None):
    headers = clerk_headers or make_intake_clerk_headers(CLERK)
    resp = api_client.create_box(
        batch_id,
        create_box_payload(box_label=box_label, intake_weight_grams=intake_weight_grams),
        headers,
    )
    return get_success_data(resp)


def create_document(box_id, doc_type="CONTRACT", pages=100, contains_phi=False,
                    ocr_confidence=95, clerk_headers=None):
    headers = clerk_headers or make_intake_clerk_headers(CLERK)
    resp = api_client.create_document(
        box_id,
        create_document_payload(
            doc_type=doc_type, pages=pages, contains_phi=contains_phi,
            ocr_confidence=ocr_confidence,
        ),
        headers,
    )
    return get_success_data(resp)


def create_scanner_unit(scanner_code=None, capacity=500, admin_headers=None):
    # PRD §3.3: scanner_code is unique. Default to a fresh code per call so
    # tests needing multiple units (e.g. batch_in_scanning twice, or a test
    # that also creates its own unit) never collide on "SCN-1".
    if scanner_code is None:
        scanner_code = "SCN-" + uuid.uuid4().hex[:8].upper()
    headers = admin_headers or make_platform_admin_headers(ADMIN)
    resp = api_client.create_scanner_unit(
        create_scanner_unit_payload(scanner_code=scanner_code, capacity_pages_per_session=capacity),
        headers,
    )
    return get_success_data(resp)


def create_shelf_slot(shelf_code="SH-G1", zone="GENERAL", capacity_grams=2000, admin_headers=None):
    headers = admin_headers or make_platform_admin_headers(ADMIN)
    resp = api_client.create_shelf_slot(
        create_shelf_slot_payload(shelf_code=shelf_code, zone=zone, capacity_grams=capacity_grams),
        headers,
    )
    return get_success_data(resp)


def shelve_box(box_id, slot_id, clerk_headers=None):
    headers = clerk_headers or make_intake_clerk_headers(CLERK)
    resp = api_client.create_shelf_assignment(
        box_id, create_shelf_assignment_payload(shelf_slot_id=slot_id), headers
    )
    return get_success_data(resp)


def set_clock(to_iso8601: str, admin_headers=None):
    headers = admin_headers or make_platform_admin_headers(ADMIN)
    resp = api_client.set_current_utc(create_clock_payload(to_iso8601), headers)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: batch in a specific pipeline state
# ---------------------------------------------------------------------------

def batch_in_intake(client_id=None, priority="STANDARD", **agreement_overrides):
    """Return dict with client, batch, invoice_id (via list)."""
    if client_id is None:
        client, _ = create_client_with_agreement(**agreement_overrides)
        client_id = client["id"]
    else:
        client = get_success_data(api_client.get_client(client_id, make_platform_admin_headers(ADMIN)))
    batch = create_batch(client_id, priority=priority)
    return {"client": client, "batch": batch}


def batch_with_box(client_id=None, box_weight=600, box_label="BX-1", priority="STANDARD", **agreement_overrides):
    ctx = batch_in_intake(client_id=client_id, priority=priority, **agreement_overrides)
    box = create_box(ctx["batch"]["id"], box_label=box_label, intake_weight_grams=box_weight)
    ctx["box"] = box
    return ctx


def batch_with_documents(doc_specs: List[dict], client_id=None, priority="STANDARD",
                         box_weight=600, box_label="BX-1", **agreement_overrides):
    """Create batch + one box + documents per doc_specs (list of dicts with
    keys: doc_type, pages, contains_phi, ocr_confidence). Returns ctx with
    documents list."""
    ctx = batch_with_box(client_id=client_id, box_weight=box_weight, box_label=box_label,
                         priority=priority, **agreement_overrides)
    docs = []
    for spec in doc_specs:
        docs.append(create_document(
            ctx["box"]["id"],
            doc_type=spec.get("doc_type", "CONTRACT"),
            pages=spec.get("pages", 100),
            contains_phi=spec.get("contains_phi", False),
            ocr_confidence=spec.get("ocr_confidence", 95),
        ))
    ctx["documents"] = docs
    return ctx


def batch_in_scanning(doc_specs: List[dict], client_id=None, priority="STANDARD",
                      box_weight=600, scanner_capacity=500, **agreement_overrides):
    """Advance batch to SCANNING. Adds scanner to ctx."""
    ctx = batch_with_documents(doc_specs, client_id=client_id, priority=priority,
                               box_weight=box_weight, **agreement_overrides)
    bid = ctx["batch"]["id"]
    get_success_data(api_client.start_prep(bid, make_intake_clerk_headers(CLERK)))
    get_success_data(api_client.start_scan(bid, make_scan_operator_headers(SCAN)))
    scanner = create_scanner_unit(capacity=scanner_capacity)
    ctx["scanner"] = scanner
    return ctx


def open_session_with_logs(ctx, page_log_specs: List[Tuple[str, int]], scanner_id=None):
    """Open a scan session on the batch (must be SCANNING), log pages per
    page_log_specs of (document_id, pages). Returns the OPEN session."""
    bid = ctx["batch"]["id"]
    scanner_id = scanner_id or ctx["scanner"]["id"]
    session = get_success_data(api_client.create_scan_session(
        bid, {"scanner_id": scanner_id}, make_scan_operator_headers(SCAN)
    ))
    for doc_id, pages in page_log_specs:
        get_success_data(api_client.create_page_log(
            session["id"], create_page_log_payload(document_id=doc_id, pages=pages),
            make_scan_operator_headers(SCAN),
        ))
    return session


def get_batch_version(batch_id, headers=None) -> int:
    headers = headers or make_scan_operator_headers(SCAN)
    data = get_success_data(api_client.get_batch(batch_id, headers))
    return data["version"]


def commit_session(session_id, batch_id, expected_version=None):
    if expected_version is None:
        expected_version = get_batch_version(batch_id)
    return get_success_data(api_client.commit_scan_session(
        session_id, {"expected_batch_version": expected_version},
        make_scan_operator_headers(SCAN),
    ))


def scan_and_commit(ctx, page_log_specs: List[Tuple[str, int]], scanner_id=None):
    """Open a session, log pages, capture batch version, commit. Returns the
    committed session."""
    session = open_session_with_logs(ctx, page_log_specs, scanner_id=scanner_id)
    return commit_session(session["id"], ctx["batch"]["id"])


def batch_in_qa(doc_specs: List[dict], client_id=None, priority="STANDARD", **agreement_overrides):
    """Advance to QA with all documents scanned/committed."""
    ctx = batch_in_scanning(doc_specs, client_id=client_id, priority=priority, **agreement_overrides)
    specs = [(d["id"], d["pages"]) for d in ctx["documents"]]
    scan_and_commit(ctx, specs)
    get_success_data(api_client.submit_qa(ctx["batch"]["id"], make_scan_operator_headers(SCAN)))
    return ctx


def batch_in_indexing(doc_specs: List[dict], client_id=None, priority="STANDARD", **agreement_overrides):
    ctx = batch_in_qa(doc_specs, client_id=client_id, priority=priority, **agreement_overrides)
    get_success_data(api_client.pass_qa(ctx["batch"]["id"], make_qa_reviewer_headers(QA)))
    return ctx


def index_document(doc_id, title="T", record_date="2026-01-01", subject="S", ocr_text_ref="ocr://x"):
    return api_client.create_index_record(
        doc_id,
        create_index_record_payload(
            metadata_json={"title": title, "record_date": record_date, "subject": subject},
            ocr_text_ref=ocr_text_ref,
        ),
        make_indexer_headers(IDX),
    )


def batch_delivered(doc_specs: List[dict], client_id=None, priority="STANDARD",
                    deliver_at: Optional[str] = None, **agreement_overrides):
    """Advance all the way to DELIVERED. Indexes every doc (caller must ensure
    ocr_confidence meets the deliverability allowance). Returns ctx with
    refreshed batch."""
    ctx = batch_in_indexing(doc_specs, client_id=client_id, priority=priority, **agreement_overrides)
    for d in ctx["documents"]:
        resp = index_document(d["id"])
        # For OCR-rejected docs the endpoint returns 200 with the Document
        # instead of 201 IndexRecord; get_success_data accepts any 2xx.
        get_success_data(resp)
    if deliver_at is not None:
        set_clock(deliver_at)
    get_success_data(api_client.deliver_batch(ctx["batch"]["id"], make_qa_reviewer_headers(QA)))
    ctx["batch"] = get_success_data(api_client.get_batch(ctx["batch"]["id"], make_qa_reviewer_headers(QA)))
    return ctx


def get_invoice_id_for_batch(batch_id) -> str:
    data, _meta = __import__("prd_bench_local_runner.testing", fromlist=["validate_paginated"]).validate_paginated(
        api_client.list_batch_invoices(batch_id, make_billing_clerk_headers(BILL))
    )
    assert len(data) == 1, f"expected exactly one invoice for batch {batch_id}, got {len(data)}"
    return data[0]["id"]


def get_invoice(invoice_id):
    return get_success_data(api_client.get_invoice(invoice_id, make_billing_clerk_headers(BILL)))


# ---------------------------------------------------------------------------
# Tier 3: disposition & destruction helpers
# ---------------------------------------------------------------------------

def deliver_and_sweep(ctx, deliver_at: str, sweep_at: str):
    """Deliver at deliver_at, then advance clock to sweep_at to trigger the
    disposition sweep. Returns refreshed batch."""
    set_clock(deliver_at)
    get_success_data(api_client.deliver_batch(ctx["batch"]["id"], make_qa_reviewer_headers(QA)))
    set_clock(sweep_at)
    ctx["batch"] = get_success_data(api_client.get_batch(ctx["batch"]["id"], make_compliance_officer_headers(CO)))
    return ctx


def destroy_box(box_id, method="SHRED", witness=WITNESS, ds_user=DS, cert_user="ds-2"):
    """Begin destruction and record certificate. Returns the certificate.

    PRD §3.3: the DESTRUCTION link appended by begin-destruction is recorded
    with the acting user's id and counts as the previous link for the
    certificate recording's custody-adjacency check — so the certificate must
    be recorded by a different DestructionSpecialist than the one who began
    destruction (default ds-1 begins, ds-2 certifies).
    """
    get_success_data(api_client.begin_destruction(box_id, make_destruction_specialist_headers(ds_user)))
    cert = get_success_data(api_client.create_destruction_certificate(
        box_id,
        create_destruction_certificate_payload(witness_user_id=witness, method=method),
        make_destruction_specialist_headers(cert_user),
    ))
    return cert


def get_box(box_id, headers=None):
    headers = headers or make_intake_clerk_headers(CLERK)
    return get_success_data(api_client.get_box(box_id, headers))


def get_shelf_slot(slot_id, headers=None):
    headers = headers or make_intake_clerk_headers(CLERK)
    return get_success_data(api_client.get_shelf_slot(slot_id, headers))


def get_document(doc_id, headers=None):
    headers = headers or make_qa_reviewer_headers(QA)
    return get_success_data(api_client.get_document(doc_id, headers))


def get_scan_session(session_id, headers=None):
    headers = headers or make_scan_operator_headers(SCAN)
    return get_success_data(api_client.get_scan_session(session_id, headers))


def get_shelf_assignment(assignment_id, headers=None):
    headers = headers or make_intake_clerk_headers(CLERK)
    return get_success_data(api_client.get_shelf_assignment(assignment_id, headers))


def get_access_grant(grant_id, client_id):
    return get_success_data(api_client.get_access_grant(grant_id, make_client_user_headers(client_id)))
