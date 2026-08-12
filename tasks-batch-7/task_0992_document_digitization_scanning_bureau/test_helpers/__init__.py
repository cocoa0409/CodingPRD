"""Barrel export: framework generics + PRD-specific code."""
# Framework generics (re-exported for convenience)
from prd_bench_local_runner.testing import (
    validate_success,
    validate_error,
    validate_paginated,
    validate_error_is_one_of,
    get_success_data,
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
    assert_version_incremented,
    assert_timestamp_format,
    assert_race_outcome,
    assert_exactly_one_succeeds,
    assert_at_least_one_succeeds,
    run_race,
    build_user_headers,
    NON_EXISTENT_UUID,
)

# PRD-specific
from .types import (
    UserRole,
    ClientStatus, BatchStatus, BatchPriority, DeliveryStatus,
    BoxStatus, DocumentStatus, DocType,
    ScanSessionStatus, AccessGrantStatus, AccessGrantScope,
    DestructionMethod, ScannerUnitStatus, ShelfZone, ShelfAssignmentStatus,
    InvoiceStatus, PriceTier,
    Client, ServiceAgreement, Batch, Box, Document, ScanSession, PageLog,
    IndexRecord, AccessGrant, CustodyEvent, DestructionCertificate,
    ScannerUnit, ShelfSlot, ShelfAssignment, Invoice,
)
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_client, assert_service_agreement, assert_batch, assert_box,
    assert_document, assert_scan_session, assert_page_log, assert_index_record,
    assert_access_grant, assert_custody_event, assert_destruction_certificate,
    assert_scanner_unit, assert_shelf_slot, assert_shelf_assignment, assert_invoice,
)
from .factories import (
    create_client_payload, create_service_agreement_payload,
    create_batch_payload, create_box_payload, create_document_payload,
    create_scanner_unit_payload, create_shelf_slot_payload,
    create_shelf_assignment_payload, create_custody_event_payload,
    create_page_log_payload, create_index_record_payload,
    create_access_grant_payload, create_destruction_certificate_payload,
    create_payment_payload, create_void_invoice_payload, create_clock_payload,
)
from .constants import (
    CLOCK_STARTUP_DEFAULT,
    STANDARD_PAGE_RATE_USD, VOLUME_PAGE_RATE_USD,
    MIN_OCR_CONFIDENCE, RUSH_ADMISSION_LIMIT,
    REJECT_FRACTION_NUM, REJECT_FRACTION_DEN,
    TEST_DEFAULTS,
)
from .test_users import (
    TEST_USERS,
    make_platform_admin_headers, make_intake_clerk_headers,
    make_prep_technician_headers, make_scan_operator_headers,
    make_qa_reviewer_headers, make_indexer_headers,
    make_destruction_specialist_headers, make_compliance_officer_headers,
    make_billing_clerk_headers, make_client_user_headers,
)
from .fixtures import (
    ADMIN, CLERK, PREP, SCAN, QA, IDX, DS, CO, BILL, WITNESS,
    create_client, create_agreement, create_client_with_agreement,
    create_batch, create_box, create_document,
    create_scanner_unit, create_shelf_slot, shelve_box, set_clock,
    batch_in_intake, batch_with_box, batch_with_documents,
    batch_in_scanning, open_session_with_logs,
    get_batch_version, commit_session, scan_and_commit,
    batch_in_qa, batch_in_indexing, index_document, batch_delivered,
    get_invoice_id_for_batch, get_invoice,
    deliver_and_sweep, destroy_box,
    get_box, get_shelf_slot, get_document, get_scan_session,
    get_shelf_assignment, get_access_grant,
)
