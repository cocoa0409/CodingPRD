"""Recording: instrument mint, book roll, page-stamp, and the void-correction
compensation that conserves office invariants.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    fixtures,
)


# ===========================================================================
# Difficulty: transitive_cascade / record_mints_instrument_then_rolls_book
# ===========================================================================
def _two_recorded_then_paid_third(office, submitter):
    """Record two DEED packages, then drive a third to PAID (ready to record)."""
    fixtures.create_recorded_package(
        office["id"], submitter["id"], doc_type="DEED",
        verified_page_count=1, verified_consideration_cents=0,
    )
    fixtures.create_recorded_package(
        office["id"], submitter["id"], doc_type="DEED",
        verified_page_count=1, verified_consideration_cents=0,
    )
    pkg_after, _assessment, _payment = fixtures.create_paid_package(
        office["id"], submitter["id"], doc_type="DEED",
        verified_page_count=1, verified_consideration_cents=0, amount_cents=3500,
    )
    return pkg_after


def test_record_mints_instrument_number_and_book(api):
    """PRD Section 3.5: "its instrument_number is taken from the office's
    next_instrument_number, its book from the office's current_book, its page from the
    office's current_page."
    PRD Section 2.5: "the office's next_instrument_number is initialized to
    instrument_seq_start ... defaulting to 1000000."

    The third recording (capacity 3) mints instrument 1000002 in book 1.

    Design: Difficulty/transitive_cascade/record_mints_instrument_then_rolls_book
    """
    office, submitter = fixtures.setup_office_and_submitter(
        book_capacity=3, instrument_seq_start=1000000, escrow_cents=100000,
    )
    pkg_after = _two_recorded_then_paid_third(office, submitter)
    resp = api.record_package(pkg_after["id"], fixtures._recorder())
    rd = validate_success(resp, expected_status=201)
    assert rd["instrument_number"] == 1000002, (
        f"third instrument must be 1000002, got {rd['instrument_number']}"
    )
    assert rd["book"] == 1, f"third recording is stamped in book 1, got {rd['book']}"


def test_third_record_rolls_book_and_resets_counters(api):
    """PRD Section 3.5: "If, after that increment, documents_in_current_book reaches the
    office's book_capacity, the book rolls: current_book increases by one,
    documents_in_current_book resets to 0, and current_page resets to 1."
    PRD Section 3.5: "next_instrument_number increases by one."

    Recording the third DEED (capacity 3) rolls the book: current_book 1->2,
    documents_in_current_book 0, current_page 1, next_instrument_number 1000003.

    Design: Difficulty/transitive_cascade/record_mints_instrument_then_rolls_book
    """
    office, submitter = fixtures.setup_office_and_submitter(
        book_capacity=3, instrument_seq_start=1000000, escrow_cents=100000,
    )
    pkg_after = _two_recorded_then_paid_third(office, submitter)
    fixtures.record_package(pkg_after["id"])
    off = validate_success(api.get_office(office["id"], fixtures._clerk()))
    assert off["next_instrument_number"] == 1000003, off["next_instrument_number"]
    assert off["current_book"] == 2, off["current_book"]
    assert off["documents_in_current_book"] == 0, off["documents_in_current_book"]
    assert off["current_page"] == 1, off["current_page"]


# ===========================================================================
# Difficulty: compensating_invariant / void_correction_conserves_index_entry_count
# ===========================================================================
def test_void_correction_returns_indexed_entries_to_zero(api):
    """PRD Section 3.5: "every PartyEntry for the package transitions from PENDING to
    INDEXED and the office's total_indexed_entries increases by that count." PRD Section
    3.5: "the package's PartyEntry rows move from INDEXED to VOIDED with the office's
    total_indexed_entries decreasing by that count."

    Recording a 2-party package raises total_indexed_entries to 2; the same-day void
    returns it to 0.

    Design: Difficulty/compensating_invariant/void_correction_conserves_index_entry_count
    """
    office, submitter = fixtures.setup_office_and_submitter(escrow_cents=100000)
    pkg_id, _assessment, rd = fixtures.create_recorded_package(
        office["id"], submitter["id"], doc_type="DEED",
        verified_page_count=1, verified_consideration_cents=0,
        grantors=("G",), grantees=("E",),
    )
    off = validate_success(api.get_office(office["id"], fixtures._clerk()))
    assert off["total_indexed_entries"] == 2, off["total_indexed_entries"]
    rd2 = validate_success(api.void_correction(rd["id"], fixtures._recorder()))
    assert rd2["status"] == "CORRECTED_VOID", rd2["status"]
    off2 = validate_success(api.get_office(office["id"], fixtures._clerk()))
    assert off2["total_indexed_entries"] == 0, (
        f"total_indexed_entries must return to 0 after void, got {off2['total_indexed_entries']}"
    )


def test_void_correction_sets_document_corrected_void(api):
    """PRD Section 3.5: "A void-correction sets the document's status to CORRECTED_VOID and
    reverses the compensable parts of the recording cascade."

    The voided recording's status is CORRECTED_VOID.

    Design: Difficulty/compensating_invariant/void_correction_conserves_index_entry_count
    """
    office, submitter = fixtures.setup_office_and_submitter(escrow_cents=100000)
    _pkg_id, _assessment, rd = fixtures.create_recorded_package(
        office["id"], submitter["id"], doc_type="DEED",
        verified_page_count=1, verified_consideration_cents=0,
    )
    rd2 = validate_success(api.void_correction(rd["id"], fixtures._recorder()))
    assert rd2["status"] == "CORRECTED_VOID", f"status must be CORRECTED_VOID, got {rd2['status']}"


# ===========================================================================
# Difficulty: compensating_invariant / void_correction_conserves_documents_in_book_count
# ===========================================================================
def test_void_correction_returns_documents_in_book_to_zero(api):
    """PRD Section 3.5: "the office's documents_in_current_book decreases by one, the
    office's daily_collected_cents decreases by that package's total_due_cents."
    PRD Section 3.5: "documents_in_current_book increases by one."

    Recording one DEED (total 3500) raises documents_in_current_book to 1 and
    daily_collected_cents to 3500; the same-day void returns both to 0.

    Design: Difficulty/compensating_invariant/void_correction_conserves_documents_in_book_count
    """
    office, submitter = fixtures.setup_office_and_submitter(escrow_cents=100000)
    _pkg_id, _assessment, rd = fixtures.create_recorded_package(
        office["id"], submitter["id"], doc_type="DEED",
        verified_page_count=1, verified_consideration_cents=0,
    )
    off = validate_success(api.get_office(office["id"], fixtures._clerk()))
    assert off["documents_in_current_book"] == 1, off["documents_in_current_book"]
    assert off["daily_collected_cents"] == 3500, off["daily_collected_cents"]
    fixtures.get_success_data(api.void_correction(rd["id"], fixtures._recorder()))
    off2 = validate_success(api.get_office(office["id"], fixtures._clerk()))
    assert off2["documents_in_current_book"] == 0, off2["documents_in_current_book"]
    assert off2["daily_collected_cents"] == 0, off2["daily_collected_cents"]


def test_void_correction_reverses_daily_collected_ledger(api):
    """PRD Section 3.5: "the office's daily_collected_cents decreases by that package's
    total_due_cents."
    PRD Section 2.5: "The daily_collected_cents is the sum of total_due_cents across the
    documents recorded on the office's current recording_date whose status is RECORDED."

    After the same-day void of the only recording, daily_collected_cents is back to 0.

    Design: Difficulty/compensating_invariant/void_correction_conserves_documents_in_book_count
    """
    office, submitter = fixtures.setup_office_and_submitter(escrow_cents=100000)
    _pkg_id, _assessment, rd = fixtures.create_recorded_package(
        office["id"], submitter["id"], doc_type="DEED",
        verified_page_count=1, verified_consideration_cents=0,
    )
    fixtures.get_success_data(api.void_correction(rd["id"], fixtures._recorder()))
    off = validate_success(api.get_office(office["id"], fixtures._clerk()))
    assert off["daily_collected_cents"] == 0, (
        f"daily_collected_cents must reverse to 0, got {off['daily_collected_cents']}"
    )


# ===========================================================================
# Corner: state_machines / correction_window_closed_next_day
# ===========================================================================
def test_void_correction_after_recording_day_rejected(api):
    """PRD Section 3.5: "A recording may be voided for correction by a Recorder, but only
    on the same recording day: the RecordedDocument's recorded_on must equal the office's
    current recording_date, otherwise the request is rejected with
    ERR_CORRECTION_WINDOW_CLOSED."

    Recording on 2026-01-01 then advancing the clock to 2026-01-02 closes the window:
    void-correction returns ERR_CORRECTION_WINDOW_CLOSED.

    Design: Corner/state_machines/correction_window_closed_next_day
    """
    office, submitter = fixtures.setup_office_and_submitter(escrow_cents=100000)
    _pkg_id, _assessment, rd = fixtures.create_recorded_package(
        office["id"], submitter["id"], doc_type="DEED",
        verified_page_count=1, verified_consideration_cents=0,
    )
    fixtures.set_clock("2026-01-02T00:00:00Z")
    resp = api.void_correction(rd["id"], fixtures._recorder())
    validate_error(resp, ApiErrorId.ERR_CORRECTION_WINDOW_CLOSED)
    data = validate_success(api.get_recorded_document(rd["id"], fixtures._clerk()))
    assert data["status"] == "RECORDED", f"document must stay RECORDED, got {data['status']}"


# ===========================================================================
# Corner: cross_cutting_complexity_layers / derived_daily_collected_reconciled_on_record
# ===========================================================================
def test_record_reconciles_daily_collected_from_assessment(api):
    """PRD Section 3.5: "the office's daily_collected_cents increases by the assessment's
    total_due_cents."
    PRD Section 2.5: "The daily_collected_cents is the sum of total_due_cents across the
    documents recorded on the office's current recording_date whose status is RECORDED."

    Recording a DEED (total 3500) sets daily_collected_cents to 3500 and
    documents_in_current_book to 1.

    Design: Corner/cross_cutting_complexity_layers/derived_daily_collected_reconciled_on_record
    """
    office, submitter = fixtures.setup_office_and_submitter(escrow_cents=100000)
    fixtures.create_recorded_package(
        office["id"], submitter["id"], doc_type="DEED",
        verified_page_count=1, verified_consideration_cents=0,
    )
    off = validate_success(api.get_office(office["id"], fixtures._clerk()))
    assert off["daily_collected_cents"] == 3500, off["daily_collected_cents"]
    assert off["documents_in_current_book"] == 1, off["documents_in_current_book"]
