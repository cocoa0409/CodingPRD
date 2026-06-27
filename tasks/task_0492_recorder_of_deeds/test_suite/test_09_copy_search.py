"""Certified copies and name searches: fee computation, index-hit counting, and the
recorded-document precondition for certified copies.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    fixtures,
)


# ===========================================================================
# Corner: calculations / copy_search_fee_certified_copy
# ===========================================================================
def test_certified_copy_fee_is_1500(api):
    """PRD Section 3.8: "its flat fee_cents is computed on creation: a CERTIFIED_COPY costs
    1,500 cents and a NAME_SEARCH costs 800 cents."
    PRD Section 3.8: "The request is born REQUESTED."

    A CERTIFIED_COPY request computes fee_cents == 1500 and is born REQUESTED.

    Design: Corner/calculations/copy_search_fee_certified_copy
    """
    office, submitter = fixtures.setup_office_and_submitter(escrow_cents=100000)
    _pkg_id, _assessment, rd = fixtures.create_recorded_package(
        office["id"], submitter["id"], doc_type="DEED",
        verified_page_count=1, verified_consideration_cents=0,
    )
    req = fixtures.create_copy_search_request(
        submitter["id"], "CERTIFIED_COPY", recorded_document_id=rd["id"]
    )
    assert req["fee_cents"] == 1500, f"certified copy fee must be 1500, got {req['fee_cents']}"
    assert req["status"] == "REQUESTED", f"status must be REQUESTED, got {req['status']}"


# ===========================================================================
# Corner: calculations / name_search_fulfill_counts_index_hits
# ===========================================================================
def test_name_search_fulfill_counts_indexed_matches(api):
    """PRD Section 3.8: "a NAME_SEARCH yields the count of INDEXED PartyEntry rows whose
    party_name equals the search_name."
    PRD Section 3.8: "a NAME_SEARCH costs 800 cents." PRD Section 3.8: "On fulfillment the
    request moves to FULFILLED."

    A NAME_SEARCH for 'Bob Buyer' against one recorded GRANTEE named 'Bob Buyer' yields
    result_count == 1, fee_cents == 800, status FULFILLED.

    Design: Corner/calculations/name_search_fulfill_counts_index_hits
    """
    office, submitter = fixtures.setup_office_and_submitter(escrow_cents=100000)
    fixtures.create_recorded_package(
        office["id"], submitter["id"], doc_type="DEED",
        verified_page_count=1, verified_consideration_cents=0,
        grantors=("Alice Seller",), grantees=("Bob Buyer",),
    )
    req = fixtures.create_copy_search_request(
        submitter["id"], "NAME_SEARCH", search_name="Bob Buyer"
    )
    assert req["fee_cents"] == 800, f"name search fee must be 800, got {req['fee_cents']}"
    resp = api.fulfill_copy_search_request(req["id"], fixtures._clerk())
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "FULFILLED", f"status must be FULFILLED, got {data['status']}"
    assert data["result_count"] == 1, f"result_count must be 1, got {data['result_count']}"


# ===========================================================================
# Corner: validations / certified_copy_for_unrecorded_document
# ===========================================================================
def test_certified_copy_for_voided_document_rejected(api):
    """PRD Section 3.8: "For a CERTIFIED_COPY, the referenced RecordedDocument must exist
    and be in RECORDED status, or the request is rejected with ERR_DOCUMENT_NOT_RECORDED."

    Fulfilling a CERTIFIED_COPY whose referenced RecordedDocument was same-day voided
    (CORRECTED_VOID) returns ERR_DOCUMENT_NOT_RECORDED.

    Design: Corner/validations/certified_copy_for_unrecorded_document
    """
    office, submitter = fixtures.setup_office_and_submitter(escrow_cents=100000)
    _pkg_id, _assessment, rd = fixtures.create_recorded_package(
        office["id"], submitter["id"], doc_type="DEED",
        verified_page_count=1, verified_consideration_cents=0,
    )
    fixtures.get_success_data(api.void_correction(rd["id"], fixtures._recorder()))
    req = fixtures.create_copy_search_request(
        submitter["id"], "CERTIFIED_COPY", recorded_document_id=rd["id"]
    )
    resp = api.fulfill_copy_search_request(req["id"], fixtures._clerk())
    validate_error(resp, ApiErrorId.ERR_DOCUMENT_NOT_RECORDED)
