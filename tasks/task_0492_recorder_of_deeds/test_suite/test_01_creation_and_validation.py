"""Resource creation, required-field / enum validation, defaults, system fields,
listing, and not-found handling.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    fixtures,
)


# ===========================================================================
# Corner: entities / create_package_returns_201_with_fields
# ===========================================================================
def test_create_package_returns_201_submitted(api):
    """PRD Section 3.2: "The package is born in SUBMITTED status ... and its
    resubmission_count starts at 0."
    PRD Section 2.4: "version, an integer that begins at its initial value and increments
    by one on each mutation."

    POST /packages with all required fields returns 201, a SUBMITTED package echoing
    doc_type, with resubmission_count 0 and version 1.

    Design: Corner/entities/create_package_returns_201_with_fields
    """
    office, submitter = fixtures.setup_office_and_submitter()
    resp = api.create_package(
        {"submitter_id": submitter["id"], "office_id": office["id"],
         "doc_type": "MORTGAGE", "declared_page_count": 4,
         "declared_consideration_cents": 0, "first_page_top_margin_inches": 3.5,
         "notary_present": True},
        fixtures.make_submitter_headers(submitter["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "SUBMITTED", f"status must be SUBMITTED, got {data['status']}"
    assert data["doc_type"] == "MORTGAGE", f"doc_type must echo MORTGAGE, got {data['doc_type']}"
    assert data["resubmission_count"] == 0, f"resubmission_count must be 0, got {data['resubmission_count']}"
    assert data["version"] == 1, f"version must begin at 1, got {data['version']}"


# ===========================================================================
# Corner: entities / get_package_not_found
# ===========================================================================
def test_get_package_not_found(api):
    """PRD Section 2.8: "The first identifier in the path that does not resolve to an
    existing resource causes the request to be rejected with ERR_NOT_FOUND, and that
    check precedes any business-rule evaluation."

    GET /packages/{random-uuid} returns ERR_NOT_FOUND (404).

    Design: Corner/entities/get_package_not_found
    """
    submitter = fixtures.create_submitter(name="Reader", submitter_type="SELF")
    resp = api.get_package(NON_EXISTENT_UUID, fixtures.make_submitter_headers(submitter["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


# ===========================================================================
# Corner: entities / create_package_missing_required_field
# ===========================================================================
def test_create_package_missing_doc_type_rejected(api):
    """PRD Section 2.10: "on any POST or PATCH the request body is validated for required
    fields, correct types and enum values, non-negative numeric amounts, and the
    copy/search field-combination rule, with failures yielding ERR_INVALID_REQUEST."
    PRD Section 3.2: "declares the doc_type — one of DEED, MORTGAGE, LIEN, UCC, PLAT, or
    OTHER."

    POST /packages omitting doc_type returns ERR_INVALID_REQUEST (422).

    Design: Corner/entities/create_package_missing_required_field
    """
    office, submitter = fixtures.setup_office_and_submitter()
    resp = api.create_package(
        {"submitter_id": submitter["id"], "office_id": office["id"],
         "declared_page_count": 1, "first_page_top_margin_inches": 3.0,
         "notary_present": True},
        fixtures.make_submitter_headers(submitter["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# ===========================================================================
# Corner: entities / package_declared_consideration_defaults_zero
# ===========================================================================
def test_declared_consideration_defaults_to_zero(api):
    """PRD Section 3.2: "The submitter may also declare a declared_consideration_cents for
    the transfer-tax estimate; for non-conveyance documents this is 0, and 0 is its
    default when omitted."

    Omitting declared_consideration_cents applies the default 0.

    Design: Corner/entities/package_declared_consideration_defaults_zero
    """
    office, submitter = fixtures.setup_office_and_submitter()
    resp = api.create_package(
        {"submitter_id": submitter["id"], "office_id": office["id"],
         "doc_type": "OTHER", "declared_page_count": 1,
         "first_page_top_margin_inches": 3.0, "notary_present": True},
        fixtures.make_submitter_headers(submitter["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["declared_consideration_cents"] == 0, (
        f"declared_consideration_cents must default to 0, got {data['declared_consideration_cents']}"
    )


# ===========================================================================
# Corner: entities / system_fields_minted_on_office_create
# ===========================================================================
def test_office_create_mints_system_counters(api):
    """PRD Section 2.5: "At creation the office's next_instrument_number is initialized to
    instrument_seq_start, current_book is set to 1, current_page is set to 1, and
    documents_in_current_book is set to 0."

    Office create with instrument_seq_start 1000000 mints next_instrument_number 1000000,
    current_book 1, current_page 1, documents_in_current_book 0.

    Design: Corner/entities/system_fields_minted_on_office_create
    """
    resp = api.create_office(
        {"county_name": "Acme", "book_capacity": 3, "instrument_seq_start": 1000000},
        fixtures._clerk(),
    )
    data = validate_success(resp, expected_status=201)
    assert data["next_instrument_number"] == 1000000, data["next_instrument_number"]
    assert data["current_book"] == 1, data["current_book"]
    assert data["documents_in_current_book"] == 0, data["documents_in_current_book"]
    assert data["current_page"] == 1, data["current_page"]


# ===========================================================================
# Corner: entities / list_packages_paginated_envelope
# ===========================================================================
def test_list_packages_paginated_envelope(api):
    """PRD Section 2.3: "Every list-based response includes the fields limit, offset,
    total_count, and has_more inside the meta object of the envelope."

    GET /packages returns an array envelope with total_count 1 and has_more false for a
    single-package result set.

    Design: Corner/entities/list_packages_paginated_envelope
    """
    office, submitter = fixtures.setup_office_and_submitter()
    fixtures.create_package(office["id"], submitter["id"], doc_type="DEED")
    rows, meta = validate_paginated(
        api.list_packages(fixtures._clerk(), params={"submitter_id": submitter["id"], "limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 1, f"total_count must be 1, got {meta['total_count']}"
    assert meta["has_more"] is False, f"has_more must be False, got {meta['has_more']}"


# ===========================================================================
# Corner: entities / enum_invalid_doc_type_rejected
# ===========================================================================
def test_create_package_invalid_doc_type_rejected(api):
    """PRD Section 2.10: "Fourth, on any POST or PATCH the request body is validated for
    required fields, correct types and enum values, non-negative numeric amounts, and the
    copy/search field-combination rule, with failures yielding ERR_INVALID_REQUEST."
    PRD Section 3.2: "declares the doc_type — one of DEED, MORTGAGE, LIEN, UCC, PLAT, or
    OTHER."

    POST /packages with doc_type 'BOGUS' returns ERR_INVALID_REQUEST (422).

    Design: Corner/entities/enum_invalid_doc_type_rejected
    """
    office, submitter = fixtures.setup_office_and_submitter()
    resp = api.create_package(
        {"submitter_id": submitter["id"], "office_id": office["id"],
         "doc_type": "BOGUS", "declared_page_count": 1,
         "first_page_top_margin_inches": 3.0, "notary_present": True},
        fixtures.make_submitter_headers(submitter["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# ===========================================================================
# Corner: entities / copy_search_field_combination_invalid
# ===========================================================================
def test_name_search_with_recorded_document_id_rejected(api):
    """PRD Section 3.8: "The field combination is strict: for a CERTIFIED_COPY the request
    must carry a recorded_document_id and must not carry a search_name; for a NAME_SEARCH
    it must carry a search_name and must not carry a recorded_document_id. A violation of
    this combination is an ERR_INVALID_REQUEST."

    POST /copy-search-requests with request_type NAME_SEARCH plus a recorded_document_id
    violates the combination -> ERR_INVALID_REQUEST.

    Design: Corner/entities/copy_search_field_combination_invalid
    """
    submitter = fixtures.create_submitter(name="Requestor", submitter_type="SELF")
    resp = api.create_copy_search_request(
        {"submitter_id": submitter["id"], "request_type": "NAME_SEARCH",
         "recorded_document_id": NON_EXISTENT_UUID},
        fixtures.make_submitter_headers(submitter["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# ===========================================================================
# Corner: entities / fk_party_entry_wrong_package_not_found
# ===========================================================================
def test_party_entry_on_missing_package_not_found(api):
    """PRD Section 2.8: "The first identifier in the path that does not resolve to an
    existing resource causes the request to be rejected with ERR_NOT_FOUND, and that
    check precedes any business-rule evaluation."

    POST /packages/{nonexistent}/party-entries returns ERR_NOT_FOUND (404).

    Design: Corner/entities/fk_party_entry_wrong_package_not_found
    """
    submitter = fixtures.create_submitter(name="Title Co", submitter_type="TITLE_COMPANY")
    resp = api.add_party_entry(
        NON_EXISTENT_UUID, {"party_role": "GRANTOR", "party_name": "X"},
        fixtures.make_submitter_headers(submitter["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
