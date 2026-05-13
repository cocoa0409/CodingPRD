"""BookTitle and Copy CRUD, validation, and weeding tests (PRD §3.1)."""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    assert_book_title,
    assert_copy,
    assert_version_increased,
    create_book_title,
    create_book_title_payload,
    create_book_title_with_copy,
    create_copy,
    create_copy_payload,
    LIBRARIAN_HEADERS,
    validate_error,
    validate_success,
    weed_copy_payload,
)


# =============================================================================
# BookTitle creation and field validation (PRD §3.1)
# =============================================================================


def test_create_book_title_initial_aggregates_zero(api):
    """PRD §3.1: "On creation the title begins life in ACTIVE status with both
    total_copies and available_copies equal to zero."

    Claim: a freshly cataloged title has status=ACTIVE, total_copies=0,
    available_copies=0.
    """
    res = api.create_book_title(create_book_title_payload(), LIBRARIAN_HEADERS)
    title = validate_success(res, 201)
    assert_book_title(title)
    assert title["status"] == "ACTIVE"
    assert title["total_copies"] == 0
    assert title["available_copies"] == 0


def test_duplicate_marc_control_number_rejected(api):
    """PRD §3.1: "Violations of any of these constraints — a duplicate
    marc_control_number ... are rejected with ERR_INVALID_INPUT (HTTP 422)."

    Claim: creating a second BookTitle with the same marc_control_number
    returns ERR_INVALID_INPUT with HTTP 422.
    """
    first = create_book_title()
    payload = create_book_title_payload(
        marc_control_number=first["marc_control_number"]
    )
    res = api.create_book_title(payload, LIBRARIAN_HEADERS)
    validate_error(res, "ERR_INVALID_INPUT", expected_status=422)


@pytest.mark.parametrize("bad_isbn", ["123", "1234567890123456", "abcdefghijklm", ""])
def test_isbn_wrong_length_rejected(api, bad_isbn):
    """PRD §3.1: "Violations of any of these constraints — ... an ISBN of the
    wrong length ... are rejected with ERR_INVALID_INPUT (HTTP 422)."

    Claim: ISBN that is not exactly 13 digits returns ERR_INVALID_INPUT (422).
    """
    payload = create_book_title_payload(isbn=bad_isbn)
    res = api.create_book_title(payload, LIBRARIAN_HEADERS)
    validate_error(res, "ERR_INVALID_INPUT", expected_status=422)


@pytest.mark.parametrize("bad_year", [1449, 100, 0])
def test_publication_year_below_min_rejected(api, bad_year):
    """PRD §3.1: "the publication_year (an integer that must be at least 1450
    and at most the current calendar year, inclusive on both ends) ... an
    out-of-range publication_year ... rejected with ERR_INVALID_INPUT (HTTP 422)."

    Claim: publication_year < 1450 returns ERR_INVALID_INPUT (422).
    """
    payload = create_book_title_payload(publication_year=bad_year)
    res = api.create_book_title(payload, LIBRARIAN_HEADERS)
    validate_error(res, "ERR_INVALID_INPUT", expected_status=422)


def test_publication_year_above_current_year_rejected(api):
    """PRD §3.1: "the publication_year ... at most the current calendar year".

    Claim: publication_year far in the future returns ERR_INVALID_INPUT.
    """
    payload = create_book_title_payload(publication_year=9999)
    res = api.create_book_title(payload, LIBRARIAN_HEADERS)
    validate_error(res, "ERR_INVALID_INPUT", expected_status=422)


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("classification_scheme", "NOTASCHEME"),
        ("subject_category", "NOTACATEGORY"),
        ("acquisition_source", "NOTASOURCE"),
    ],
)
def test_enum_outside_set_rejected(api, field, bad_value):
    """PRD §3.1: "an enum value outside the declared set — are rejected with
    ERR_INVALID_INPUT (HTTP 422)."

    Claim: enum values outside the PRD's declared set return ERR_INVALID_INPUT.
    """
    payload = create_book_title_payload(**{field: bad_value})
    res = api.create_book_title(payload, LIBRARIAN_HEADERS)
    validate_error(res, "ERR_INVALID_INPUT", expected_status=422)


def test_get_book_title_nonexistent(api):
    """PRD §2.6: "if the title does not exist the response is ERR_NOT_FOUND
    (HTTP 404)."

    Claim: GET on a non-existent BookTitle id returns ERR_NOT_FOUND 404.
    """
    res = api.get_book_title(NON_EXISTENT_UUID, LIBRARIAN_HEADERS)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


# =============================================================================
# Copy creation (PRD §3.1)
# =============================================================================


def test_create_copy_starts_available(api):
    """PRD §3.1: "Each new copy starts in AVAILABLE status".

    Claim: a freshly added Copy has status=AVAILABLE.
    """
    title = create_book_title()
    res = api.create_copy(title["id"], create_copy_payload(), LIBRARIAN_HEADERS)
    copy = validate_success(res, 201)
    assert_copy(copy)
    assert copy["status"] == "AVAILABLE"


def test_create_copy_updates_title_aggregates(api):
    """PRD §3.1: "the title's total_copies and available_copies aggregates are
    recomputed: total_copies is the count of all copies of the title regardless
    of status, and available_copies is the count of those copies whose status
    equals AVAILABLE."

    Claim: after adding two AVAILABLE copies, the title shows total_copies=2
    and available_copies=2.
    """
    title = create_book_title()
    create_copy(title["id"])
    create_copy(title["id"])
    refreshed = validate_success(
        api.get_book_title(title["id"], LIBRARIAN_HEADERS), 200
    )
    assert refreshed["total_copies"] == 2
    assert refreshed["available_copies"] == 2


def test_duplicate_barcode_rejected(api):
    """PRD §3.1: "A duplicate barcode or an empty location_code is rejected
    with ERR_INVALID_INPUT."

    Claim: creating a second Copy with the same barcode returns ERR_INVALID_INPUT.
    """
    title = create_book_title()
    first = create_copy(title["id"])
    title2 = create_book_title()
    res = api.create_copy(
        title2["id"],
        create_copy_payload(barcode=first["barcode"]),
        LIBRARIAN_HEADERS,
    )
    validate_error(res, "ERR_INVALID_INPUT", expected_status=422)


def test_empty_location_code_rejected(api):
    """PRD §3.1: "A duplicate barcode or an empty location_code is rejected
    with ERR_INVALID_INPUT."

    Claim: empty location_code on Copy creation returns ERR_INVALID_INPUT 422.
    """
    title = create_book_title()
    res = api.create_copy(
        title["id"],
        create_copy_payload(location_code=""),
        LIBRARIAN_HEADERS,
    )
    validate_error(res, "ERR_INVALID_INPUT", expected_status=422)


def test_copy_under_nonexistent_title_returns_not_found(api):
    """PRD §2.6: "every path segment that names a resource must resolve, and
    the first unresolved segment determines the error."

    Claim: adding a Copy under a non-existent BookTitle id returns ERR_NOT_FOUND.
    """
    res = api.create_copy(
        NON_EXISTENT_UUID, create_copy_payload(), LIBRARIAN_HEADERS
    )
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


# =============================================================================
# Weeding (PRD §3.1)
# =============================================================================


def test_weed_copy_moves_to_weeded_and_updates_aggregates(api):
    """PRD §3.1: "The successful weed transitions the copy into WEEDED ...
    refreshes the title's total_copies and available_copies".

    Claim: weeding an AVAILABLE copy sets status=WEEDED and decrements
    available_copies on its parent title.
    """
    title, copy = create_book_title_with_copy()
    create_copy(title["id"])  # keep title alive (not all-weeded)
    before_version = copy["version"]

    res = api.weed_copy(copy["id"], weed_copy_payload(), LIBRARIAN_HEADERS)
    weeded = validate_success(res, 200)
    assert weeded["status"] == "WEEDED"
    assert_version_increased(weeded, before_version)

    refreshed_title = validate_success(
        api.get_book_title(title["id"], LIBRARIAN_HEADERS), 200
    )
    # total_copies counts ALL copies regardless of status; the WEEDED copy
    # remains counted in total_copies, but is excluded from available_copies.
    assert refreshed_title["total_copies"] == 2
    assert refreshed_title["available_copies"] == 1


def test_weed_without_reason_rejected(api):
    """PRD §3.1: "A weed without a weeding_reason is rejected with
    ERR_INVALID_INPUT."

    Claim: omitting weeding_reason returns ERR_INVALID_INPUT (HTTP 422).
    """
    title, copy = create_book_title_with_copy()
    res = api.weed_copy(copy["id"], {}, LIBRARIAN_HEADERS)
    validate_error(res, "ERR_INVALID_INPUT", expected_status=422)


def test_weed_already_weeded_copy_rejected(api):
    """PRD §3.1: "a copy that is ON_LOAN, RESERVED, IN_TRANSIT_ILL, or already
    WEEDED is rejected with ERR_INVALID_STATE for any transition the state
    machine does not declare".

    Claim: weeding a WEEDED copy returns ERR_INVALID_STATE (HTTP 409).
    """
    title, copy = create_book_title_with_copy()
    create_copy(title["id"])
    validate_success(
        api.weed_copy(copy["id"], weed_copy_payload(), LIBRARIAN_HEADERS), 200
    )
    res = api.weed_copy(copy["id"], weed_copy_payload(), LIBRARIAN_HEADERS)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_all_copies_weeded_withdraws_title(api):
    """PRD §3.1: "when every copy of the title is in WEEDED, advances the
    parent BookTitle from ACTIVE to WITHDRAWN."

    Claim: after weeding all copies, BookTitle.status becomes WITHDRAWN.
    """
    title, copy_a = create_book_title_with_copy()
    copy_b = create_copy(title["id"])
    validate_success(
        api.weed_copy(copy_a["id"], weed_copy_payload(), LIBRARIAN_HEADERS), 200
    )
    refreshed = validate_success(
        api.get_book_title(title["id"], LIBRARIAN_HEADERS), 200
    )
    # One copy is still AVAILABLE — title should still be ACTIVE.
    assert refreshed["status"] == "ACTIVE"

    validate_success(
        api.weed_copy(copy_b["id"], weed_copy_payload(), LIBRARIAN_HEADERS), 200
    )
    after = validate_success(
        api.get_book_title(title["id"], LIBRARIAN_HEADERS), 200
    )
    assert after["status"] == "WITHDRAWN"
