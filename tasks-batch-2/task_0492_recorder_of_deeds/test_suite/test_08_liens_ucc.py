"""Liens and UCC filings: lapse, continuation self-loop, tax-lien exclusivity,
termination, and parcel filtering.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    fixtures,
)


# ===========================================================================
# Difficulty: resource_temporal_overlap / tax_lien_half_open_period_grace_buffer_overlap
# ===========================================================================
def test_tax_lien_overlap_within_grace_buffer_rejected(api):
    """PRD Section 3.7: "A new TAX_LIEN is rejected with ERR_TAX_LIEN_OVERLAP if there
    exists an ACTIVE TAX_LIEN on the same parcel_id whose buffered period contains the
    new lien's effective date — that is, when the new lien's effective_date is earlier
    than the existing lien's lapse_date plus the tax-lien grace buffer of 30 days, and the
    new lien's effective_date is at the same time on or after the existing lien's
    effective_date."

    Existing TAX_LIEN on P-7 eff 2026-01-01 (lapse 2031-01-01) blocks a new TAX_LIEN
    eff 2031-01-15 because 2031-01-15 < 2031-01-31 (lapse + 30-day grace).

    Design: Difficulty/resource_temporal_overlap/tax_lien_half_open_period_grace_buffer_overlap
    """
    office, submitter = fixtures.setup_office_and_submitter(submitter_name="County Tax",
                                                            submitter_type="GOVERNMENT")
    fixtures.create_ucc_filing(office["id"], submitter["id"], lien_type="TAX_LIEN",
                               parcel_id="P-7", debtor_name="Owner",
                               effective_date="2026-01-01T00:00:00Z")
    resp = api.create_ucc_filing(
        {"submitter_id": submitter["id"], "office_id": office["id"],
         "lien_type": "TAX_LIEN", "parcel_id": "P-7", "debtor_name": "Owner",
         "effective_date": "2031-01-15T00:00:00Z"},
        fixtures.make_submitter_headers(submitter["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TAX_LIEN_OVERLAP)


def test_tax_lien_overlap_creates_no_second_filing(api):
    """PRD Section 3.7: "A new TAX_LIEN is rejected with ERR_TAX_LIEN_OVERLAP if there
    exists an ACTIVE TAX_LIEN on the same parcel_id whose buffered period contains the
    new lien's effective date."

    The rejected overlapping TAX_LIEN leaves only the original filing on parcel P-7.

    Design: Difficulty/resource_temporal_overlap/tax_lien_half_open_period_grace_buffer_overlap
    """
    office, submitter = fixtures.setup_office_and_submitter(submitter_name="County Tax",
                                                            submitter_type="GOVERNMENT")
    fixtures.create_ucc_filing(office["id"], submitter["id"], lien_type="TAX_LIEN",
                               parcel_id="P-7", debtor_name="Owner",
                               effective_date="2026-01-01T00:00:00Z")
    api.create_ucc_filing(
        {"submitter_id": submitter["id"], "office_id": office["id"],
         "lien_type": "TAX_LIEN", "parcel_id": "P-7", "debtor_name": "Owner",
         "effective_date": "2031-01-15T00:00:00Z"},
        fixtures.make_submitter_headers(submitter["id"]),
    )
    rows, meta = validate_paginated(
        api.list_ucc_filings(fixtures._clerk(), params={"parcel_id": "P-7"})
    )
    assert meta["total_count"] == 1, f"only one filing must exist on P-7, got {meta['total_count']}"


# ===========================================================================
# Difficulty: non_linear_state_machine / ucc_continuation_active_self_loop
# ===========================================================================
def test_continuation_keeps_active_and_increments_count(api):
    """PRD Section 3.7: "A successful continuation pushes the lapse_date forward by another
    five years and increments continuation_count by one."
    PRD Section 3.7: "Continuation extends a still-active filing and forms a self-loop on
    ACTIVE."

    A continuation within the window keeps status ACTIVE and raises continuation_count to 1.

    Design: Difficulty/non_linear_state_machine/ucc_continuation_active_self_loop
    """
    office, submitter = fixtures.setup_office_and_submitter(submitter_name="Lender",
                                                            submitter_type="ATTORNEY")
    filing = fixtures.create_ucc_filing(office["id"], submitter["id"], lien_type="UCC1",
                                        parcel_id="P-1", debtor_name="Debtor A",
                                        effective_date="2026-01-01T00:00:00Z")
    fixtures.set_clock("2030-08-01T00:00:00Z")
    resp = api.continue_ucc_filing(filing["id"], fixtures.make_submitter_headers(submitter["id"]))
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "ACTIVE", f"status must stay ACTIVE, got {data['status']}"
    assert data["continuation_count"] == 1, (
        f"continuation_count must increment to 1, got {data['continuation_count']}"
    )


def test_continuation_pushes_lapse_date_five_years(api):
    """PRD Section 3.7: "On creation the filing's lapse_date is set to the effective date
    plus the lapse term of five years."
    PRD Section 3.7: "A successful continuation pushes the lapse_date forward by another
    five years and increments continuation_count by one."

    A UCC1 eff 2026-01-01 (lapse 2031-01-01) continued once extends lapse_date to 2036-01-01.

    Design: Difficulty/non_linear_state_machine/ucc_continuation_active_self_loop
    """
    office, submitter = fixtures.setup_office_and_submitter(submitter_name="Lender",
                                                            submitter_type="ATTORNEY")
    filing = fixtures.create_ucc_filing(office["id"], submitter["id"], lien_type="UCC1",
                                        parcel_id="P-1", debtor_name="Debtor A",
                                        effective_date="2026-01-01T00:00:00Z")
    fixtures.set_clock("2030-08-01T00:00:00Z")
    resp = api.continue_ucc_filing(filing["id"], fixtures.make_submitter_headers(submitter["id"]))
    data = validate_success(resp, expected_status=200)
    assert data["lapse_date"].startswith("2036-01-01"), (
        f"lapse_date must extend to 2036-01-01, got {data['lapse_date']}"
    )


# ===========================================================================
# Corner: state_machines / ucc_lapsed_blocks_continuation
# ===========================================================================
def test_lapsed_filing_blocks_continuation(api):
    """PRD Section 3.7: "the office's recording_date be strictly before the lapse_date, or
    the request is rejected with ERR_FILING_ALREADY_LAPSED."
    PRD Section 3.7: "A filing's status becomes LAPSED when the office's recording_date
    reaches or passes its lapse_date."

    After the clock advances to 2031-06-01 (past lapse 2031-01-01), continuation is
    rejected with ERR_FILING_ALREADY_LAPSED.

    Design: Corner/state_machines/ucc_lapsed_blocks_continuation
    """
    office, submitter = fixtures.setup_office_and_submitter(submitter_name="Lender",
                                                            submitter_type="ATTORNEY")
    filing = fixtures.create_ucc_filing(office["id"], submitter["id"], lien_type="UCC1",
                                        parcel_id="P-9", debtor_name="D",
                                        effective_date="2026-01-01T00:00:00Z")
    fixtures.set_clock("2031-06-01T00:00:00Z")
    resp = api.continue_ucc_filing(filing["id"], fixtures.make_submitter_headers(submitter["id"]))
    validate_error(resp, ApiErrorId.ERR_FILING_ALREADY_LAPSED)


# ===========================================================================
# Corner: state_machines / ucc_continuation_too_early
# ===========================================================================
def test_continuation_before_window_too_early(api):
    """PRD Section 3.7: "the office's recording_date be on or after the lapse date minus
    the continuation window of 180 days — meaning continuation is permitted only within
    the 180 days immediately before lapse — or the request is rejected with
    ERR_CONTINUATION_TOO_EARLY."

    With lapse 2031-01-01 the window opens 2030-07-05; a continuation at clock 2030-06-01
    returns ERR_CONTINUATION_TOO_EARLY.

    Design: Corner/state_machines/ucc_continuation_too_early
    """
    office, submitter = fixtures.setup_office_and_submitter(submitter_name="Lender",
                                                            submitter_type="ATTORNEY")
    filing = fixtures.create_ucc_filing(office["id"], submitter["id"], lien_type="UCC1",
                                        parcel_id="P-10", debtor_name="D",
                                        effective_date="2026-01-01T00:00:00Z")
    fixtures.set_clock("2030-06-01T00:00:00Z")
    resp = api.continue_ucc_filing(filing["id"], fixtures.make_submitter_headers(submitter["id"]))
    validate_error(resp, ApiErrorId.ERR_CONTINUATION_TOO_EARLY)


# ===========================================================================
# Corner: endpoints / ucc_terminate_action
# ===========================================================================
def test_terminate_moves_filing_to_terminated(api):
    """PRD Section 3.7: "The owning submitter may also terminate the filing, moving its
    status to TERMINATED."

    POST /ucc-filings/{id}/terminate moves an ACTIVE filing to TERMINATED.

    Design: Corner/endpoints/ucc_terminate_action
    """
    office, submitter = fixtures.setup_office_and_submitter(submitter_name="Lender",
                                                            submitter_type="ATTORNEY")
    filing = fixtures.create_ucc_filing(office["id"], submitter["id"], lien_type="UCC1",
                                        parcel_id="P-5", debtor_name="D",
                                        effective_date="2026-01-01T00:00:00Z")
    resp = api.terminate_ucc_filing(filing["id"], fixtures.make_submitter_headers(submitter["id"]))
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "TERMINATED", f"filing must be TERMINATED, got {data['status']}"


# ===========================================================================
# Corner: endpoints / filter_ucc_by_parcel
# ===========================================================================
def test_filter_ucc_filings_by_parcel(api):
    """PRD Section 2.3: "Every list-based response includes the fields limit, offset,
    total_count, and has_more inside the meta object of the envelope."

    GET /ucc-filings?parcel_id=P-3 returns only the filing on parcel P-3 (one of two).

    Design: Corner/endpoints/filter_ucc_by_parcel
    """
    office, submitter = fixtures.setup_office_and_submitter(submitter_name="Lender",
                                                            submitter_type="ATTORNEY")
    fixtures.create_ucc_filing(office["id"], submitter["id"], lien_type="UCC1",
                               parcel_id="P-3", debtor_name="D1",
                               effective_date="2026-01-01T00:00:00Z")
    fixtures.create_ucc_filing(office["id"], submitter["id"], lien_type="UCC1",
                               parcel_id="P-4", debtor_name="D2",
                               effective_date="2026-01-01T00:00:00Z")
    rows, meta = validate_paginated(
        api.list_ucc_filings(fixtures._clerk(), params={"parcel_id": "P-3"})
    )
    assert meta["total_count"] == 1, f"only one filing on P-3, got {meta['total_count']}"
