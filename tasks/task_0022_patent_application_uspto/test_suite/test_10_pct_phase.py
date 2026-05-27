"""PCT national-phase entry: the 30-month boundary (inclusive ≤) for
acceptance, and the at-most-one PCTPhaseEntry-per-Application singleton.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_applicant_headers,
    set_clock, create_applicant, create_application,
    setup_pct_application_with_entry,
    create_pct_phase_entry_payload,
)


# =============================================================================
# Difficulty / boundary_precision_check / pct_phase_entry_exact_30_month_boundary_accepted
# =============================================================================

def test_pct_phase_entry_at_exact_30_month_boundary_accepted(api):
    """Creating a PCTPhaseEntry at EXACTLY pct_international_filing_date + 30
    months (current_utc == national_phase_due_date) is ACCEPTED. The
    boundary is inclusive (≤).

    PRD §3.10: "A national phase entry created on or before that due date
    is accepted with `phase_status` set to `ENTERED`; an entry whose
    `created_at` is strictly after the due date is rejected with
    `ERR_PCT_NATIONAL_PHASE_LATE`."

    Design: Difficulty/boundary_precision_check/pct_phase_entry_exact_30_month_boundary_accepted
    """
    set_clock("2026-05-27T00:00:00.000Z")
    applicant = create_applicant(legal_name="PCT Co", entity_size="LARGE")
    application = create_application(
        applicant, application_type="PCT_NATIONAL",
        title="PCT widget", claim_count=10, independent_claim_count=2,
    )
    # current_utc == pct_international_filing_date + 30mo exactly
    res = api.create_pct_phase_entry(
        create_pct_phase_entry_payload(
            application_id=application["id"],
            pct_international_filing_date="2023-11-27T00:00:00.000Z",
        ),
        make_applicant_headers(applicant["id"]),
    )
    entry = validate_success(res, 201)
    assert entry["phase_status"] == "ENTERED", (
        f"Boundary entry must be ENTERED, got {entry['phase_status']}"
    )
    assert entry["national_phase_due_date"] == "2026-05-27T00:00:00.000Z"


def test_pct_phase_entry_one_microsecond_past_boundary_rejected(api):
    """Symmetric to the boundary-accepted test: at one tick past 30 months
    the entry is rejected with ERR_PCT_NATIONAL_PHASE_LATE — confirming the
    boundary semantics is strict ">".

    PRD §3.10: "A national phase entry created on or before that due date
    is accepted with `phase_status` set to `ENTERED`; an entry whose
    `created_at` is strictly after the due date is rejected with
    `ERR_PCT_NATIONAL_PHASE_LATE`."

    Design: Difficulty/boundary_precision_check/pct_phase_entry_exact_30_month_boundary_accepted
    """
    # Clock one millisecond past 30-month deadline.
    set_clock("2026-05-27T00:00:00.001Z")
    applicant = create_applicant(legal_name="PCT Late Co", entity_size="LARGE")
    application = create_application(
        applicant, application_type="PCT_NATIONAL",
        title="PCT past widget", claim_count=10, independent_claim_count=2,
    )
    res = api.create_pct_phase_entry(
        create_pct_phase_entry_payload(
            application_id=application["id"],
            pct_international_filing_date="2023-11-27T00:00:00.000Z",
        ),
        make_applicant_headers(applicant["id"]),
    )
    validate_error(res, ApiErrorId.ERR_PCT_NATIONAL_PHASE_LATE.value)


# =============================================================================
# Difficulty / resource_temporal_overlap / pct_phase_entry_singleton_per_application
# =============================================================================

def test_second_pct_phase_entry_against_same_application_rejected(api):
    """A second PCTPhaseEntry against the same application_id is rejected
    with ERR_PCT_PHASE_ENTRY_DUPLICATE.

    PRD §3.10: "At most one `PCTPhaseEntry` may exist per application: a
    second entry against the same application is rejected with
    `ERR_PCT_PHASE_ENTRY_DUPLICATE`."

    Design: Difficulty/resource_temporal_overlap/pct_phase_entry_singleton_per_application
    """
    set_clock("2026-01-01T00:00:00.000Z")
    applicant, application, first_entry = setup_pct_application_with_entry(
        entity_size="LARGE",
        pct_international_filing_date="2024-01-01T00:00:00.000Z",
    )
    res = api.create_pct_phase_entry(
        create_pct_phase_entry_payload(
            application_id=application["id"],
            pct_international_filing_date="2024-01-01T00:00:00.000Z",
        ),
        make_applicant_headers(applicant["id"]),
    )
    validate_error(res, ApiErrorId.ERR_PCT_PHASE_ENTRY_DUPLICATE.value)


def test_pct_phase_entry_singleton_only_one_listed_after_duplicate_attempt(api):
    """After the duplicate-creation rejection, exactly one PCTPhaseEntry
    exists on the application — the singleton invariant holds.

    PRD §3.10: "At most one `PCTPhaseEntry` may exist per application: a
    second entry against the same application is rejected with
    `ERR_PCT_PHASE_ENTRY_DUPLICATE`."

    Design: Difficulty/resource_temporal_overlap/pct_phase_entry_singleton_per_application
    """
    set_clock("2026-01-01T00:00:00.000Z")
    applicant, application, first_entry = setup_pct_application_with_entry(
        entity_size="LARGE",
        pct_international_filing_date="2024-01-01T00:00:00.000Z",
    )
    # Attempt duplicate
    api.create_pct_phase_entry(
        create_pct_phase_entry_payload(
            application_id=application["id"],
            pct_international_filing_date="2024-01-01T00:00:00.000Z",
        ),
        make_applicant_headers(applicant["id"]),
    )

    list_res = api.list_pct_phase_entries(
        make_applicant_headers(applicant["id"]),
        params={"application_id": application["id"]},
    )
    entries = validate_success(list_res, 200)
    assert len(entries) == 1, (
        f"Exactly one PCTPhaseEntry must exist per application, got {len(entries)}"
    )
    assert entries[0]["id"] == first_entry["id"]
