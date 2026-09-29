"""Writes the server refuses at the door, and the append-only evidence it keeps instead."""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import ApiErrorId
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import SYSTEM_ADMIN_HEADERS, api_client

UNKNOWN_JOURNAL_ID = "22222222-3333-4444-8555-666666666666"


def _submit_manuscript_request(journal_id, author, author_headers, **overrides):
    payload = f.manuscript_payload(journal_id, author["id"], **overrides)
    return payload, api_client.create_manuscript(payload, author_headers)


def _submit_without_page_count(journal_id, author, author_headers):
    payload = f.manuscript_payload(journal_id, author["id"])
    del payload["page_count"]
    return api_client.create_manuscript(payload, author_headers)


def test_submission_without_a_page_count_is_refused_as_invalid():
    """A required field missing from the body is a validation failure, not a default.

    PRD: "The body carries every required field, each of its declared JSON type, every enum field carrying a declared member, every monetary and count field a non-negative integer, and every percentage field within 0 to 100 inclusive — otherwise `ERR_INVALID_REQUEST` (400), on every write endpoint."

    Design: Corner/entities/manuscript_create_missing_required_page_count_rejected
    """
    journal = fx.create_journal()
    author, author_headers = fx.create_author()

    response = _submit_without_page_count(journal["id"], author, author_headers)

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


def test_refused_submission_never_reaches_the_journal_intake_counter():
    """The rejected request leaves no manuscript and no counted intake behind.

    PRD: "A journal's `manuscript_intake_count` counts every manuscript ever submitted to it and never decreases, which is what makes a manuscript's `journal_sequence_number` permanently unique within its journal even after desk rejections and retractions."

    Design: Corner/entities/manuscript_create_missing_required_page_count_rejected
    """
    journal = fx.create_journal()
    author, author_headers = fx.create_author()

    _submit_without_page_count(journal["id"], author, author_headers)

    assert fx.get_journal(journal["id"])["manuscript_intake_count"] == 0
    _rows, meta = validate_paginated(
        api_client.list_manuscripts(
            SYSTEM_ADMIN_HEADERS, params={"journal_id": journal["id"]}
        )
    )
    assert meta["total_count"] == 0, f"Expected no manuscripts, got {meta['total_count']}"


def test_submission_with_an_undeclared_licence_member_is_refused():
    """A licence outside the declared four is not a storable value.

    PRD: "The body carries every required field, each of its declared JSON type, every enum field carrying a declared member, every monetary and count field a non-negative integer, and every percentage field within 0 to 100 inclusive — otherwise `ERR_INVALID_REQUEST` (400), on every write endpoint."

    Design: Corner/entities/manuscript_create_invalid_oa_license_enum_rejected
    """
    journal = fx.create_journal()
    author, author_headers = fx.create_author()

    _payload, response = _submit_manuscript_request(
        journal["id"], author, author_headers, oa_license="CC_BY_SA"
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)
    assert fx.get_journal(journal["id"])["manuscript_intake_count"] == 0


def test_submission_naming_an_unknown_journal_is_a_not_found_foreign_key():
    """The body's journal reference must resolve before the manuscript can exist.

    PRD: "Every foreign key in the request body references an existing row — otherwise the matching not-found error for that entity (404), on every write endpoint that carries a foreign key."

    Design: Corner/entities/manuscript_create_unknown_journal_id_returns_journal_not_found
    """
    author, author_headers = fx.create_author()

    _payload, response = _submit_manuscript_request(
        UNKNOWN_JOURNAL_ID, author, author_headers
    )

    validate_error(response, ApiErrorId.ERR_JOURNAL_NOT_FOUND.value, expected_status=404)
    _rows, meta = validate_paginated(api_client.list_manuscripts(SYSTEM_ADMIN_HEADERS))
    assert meta["total_count"] == 0, f"Expected no manuscripts, got {meta['total_count']}"


def test_editor_registration_naming_an_unknown_journal_is_a_not_found_foreign_key():
    """An editor cannot be attached to a journal that does not exist.

    PRD: "Every foreign key in the request body references an existing row — otherwise the matching not-found error for that entity (404), on every write endpoint that carries a foreign key."

    Design: Corner/entities/editor_create_unknown_journal_id_cross_reference_integrity
    """
    response = api_client.create_editor(
        f.editor_payload(UNKNOWN_JOURNAL_ID, role_level="HANDLING"), SYSTEM_ADMIN_HEADERS
    )

    validate_error(response, ApiErrorId.ERR_JOURNAL_NOT_FOUND.value, expected_status=404)
    _rows, meta = validate_paginated(api_client.list_editors(SYSTEM_ADMIN_HEADERS))
    assert meta["total_count"] == 0, f"Expected no editors, got {meta['total_count']}"


def test_second_plagiarism_screening_in_the_same_round_collides():
    """One scan type per manuscript per round, so the repeat scan is refused.

    PRD: "The server stamps the screening's `round` with the manuscript's current `revision_round`, and only one screening of each `scan_type` may exist per manuscript per round; a second one collides with `ERR_DUPLICATE_KEY`."

    Design: Corner/entities/integrity_screening_immutable_row_has_no_version_or_update_route
    """
    world = fx.setup_submitted_manuscript()
    manuscript_id = world["manuscript"]["id"]
    fx.file_plagiarism_screening(manuscript_id, 5.0)

    response = api_client.create_integrity_screening(
        manuscript_id, f.plagiarism_screening_payload(35.0), SYSTEM_ADMIN_HEADERS
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_KEY.value, expected_status=409)
    rows, meta = validate_paginated(
        api_client.list_integrity_screenings(manuscript_id, SYSTEM_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 1, f"Expected 1 screening, got {meta['total_count']}"
    a.assert_fields(rows[0], scan_type="PLAGIARISM", round=0)
    a.assert_score_equals(rows[0]["similarity_pct"], 5.0, "similarity_pct")


def test_integrity_screening_row_carries_neither_version_nor_updated_at():
    """The screening is evidence, so it has no mutable-record fields to amend.

    PRD: "Three record types are append-only evidence rather than mutable state, and they carry only `id` and `created_at`: an `IntegrityScreening`, a `Review` and a `Decision` are each written once and never amended, so none of the three has an `updated_at` field and none of the three has a `version` field."

    Design: Corner/entities/integrity_screening_immutable_row_has_no_version_or_update_route
    """
    world = fx.setup_submitted_manuscript()

    screening = fx.file_plagiarism_screening(world["manuscript"]["id"], 5.0)

    a.assert_append_only_record_fields(screening)
    a.assert_fields(screening, scan_type="PLAGIARISM")
