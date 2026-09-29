"""Headers before bodies, owners before payloads, and a clock that never runs back."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import (
    SYSTEM_ADMIN_HEADERS,
    api_client,
    headers_without_role,
    make_author_headers,
)

UNKNOWN_AUTHOR_ID = "author-does-not-exist"


def _count_manuscripts(journal_id):
    rows, meta = validate_paginated(
        api_client.list_manuscripts(
            SYSTEM_ADMIN_HEADERS, params={"journal_id": journal_id}
        )
    )
    assert len(rows) == meta["total_count"], "the whole set fits in one page"
    return meta["total_count"]


def _setup_journal_and_author():
    journal = fx.create_journal()
    author, author_headers = fx.create_author()
    return journal, author, author_headers


def _untitled_submission_without_a_role_header(journal_id, author):
    """A body missing the required `title`, sent with no `X-User-Role` at all."""
    payload = f.manuscript_payload(journal_id, author["id"])
    del payload["title"]
    return api_client.create_manuscript(payload, headers_without_role(author["id"]))


def _revision_request(manuscript_id, headers):
    return api_client.submit_revision(
        manuscript_id,
        f.revision_payload(
            page_count=18,
            figure_count=2,
            response_letter="Every reviewer comment is addressed in turn.",
        ),
        headers,
    )


def test_missing_role_header_is_reported_before_the_invalid_body():
    """Two violations in one request, and the first rung of the ladder answers.

    PRD: "When a single request violates more than one rule, exactly one error is returned: the one belonging to the **highest-priority** violated rule."

    Design: Corner/validations/manuscript_create_missing_header_outranks_invalid_payload
    """
    journal, author, _author_headers = _setup_journal_and_author()

    response = _untitled_submission_without_a_role_header(journal["id"], author)

    error = validate_error(
        response, ApiErrorId.ERR_ROLE_HEADER_MISSING.value, expected_status=400
    )
    assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value, (
        "the missing title is a lower-priority violation and must not be reported"
    )


def test_rejected_submission_never_consumed_a_sequence_number():
    """No manuscript row, and the journal's intake counter never moved.

    PRD: "It receives a `journal_sequence_number` equal to the journal's `manuscript_intake_count` plus 1, and the journal's `manuscript_intake_count` then rises by 1 — this is the deterministic component of the DOI the article will eventually carry, and because the intake counter never decreases, no two manuscripts on one journal ever share a sequence number."

    Design: Corner/validations/manuscript_create_missing_header_outranks_invalid_payload
    """
    journal, author, _author_headers = _setup_journal_and_author()

    _untitled_submission_without_a_role_header(journal["id"], author)

    assert _count_manuscripts(journal["id"]) == 0
    a.assert_fields(fx.get_journal(journal["id"]), manuscript_intake_count=0)


def test_unknown_acting_identity_is_refused_before_the_body_is_read():
    """The body's author resolves; the acting principal does not.

    PRD: "For any of those four roles, a missing `X-User-ID`, or one that matches no `Editor`, `Reviewer` or `Author` row, is rejected with `ERR_IDENTITY_NOT_FOUND` (HTTP 403)."

    Design: Corner/validations/manuscript_create_with_unknown_x_user_id_rejected
    """
    journal, author, _author_headers = _setup_journal_and_author()

    response = api_client.create_manuscript(
        f.manuscript_payload(journal["id"], author["id"]),
        make_author_headers(UNKNOWN_AUTHOR_ID),
    )

    error = validate_error(
        response, ApiErrorId.ERR_IDENTITY_NOT_FOUND.value, expected_status=403
    )
    assert error["error_id"] != ApiErrorId.ERR_AUTHOR_NOT_FOUND.value, (
        "the body's corresponding author exists; it is the caller who does not"
    )
    assert _count_manuscripts(journal["id"]) == 0
    a.assert_fields(fx.get_journal(journal["id"]), manuscript_intake_count=0)


def test_another_author_cannot_submit_the_revision():
    """Ownership is compared against the acting identity, not against the role.

    PRD: "The acting entity-backed identity owns the resource it addresses — otherwise `ERR_NOT_RESOURCE_OWNER` (403)."

    Design: Corner/validations/second_author_cannot_submit_a_revision_for_another_authors_manuscript
    """
    world = fx.setup_revision_requested_manuscript()
    a.assert_fields(world["manuscript"], status="REVISION_REQUESTED", page_count=20)
    _second_author, second_author_headers = fx.create_author()

    response = _revision_request(world["manuscript"]["id"], second_author_headers)

    validate_error(
        response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, expected_status=403
    )
    manuscript = fx.get_manuscript(world["manuscript"]["id"])
    a.assert_fields(
        manuscript,
        status="REVISION_REQUESTED",
        revision_round=0,
        page_count=20,
        figure_count=5,
    )


def test_the_corresponding_author_opens_the_next_round():
    """The same request from the owner is the one the workflow expects.

    PRD: "The manuscript moves `REVISION_REQUESTED → REVISION_SUBMITTED`, its `revision_round` rises by 1, the supplied `page_count`, `figure_count` and `data_availability_statement` replace the stored ones so that `formatting_status` is recomputed against the journal's limits, its `integrity_status` returns to `PENDING` because the new round has no screening yet, its `submitted_review_count` is recomputed for the new round and is therefore 0, and its `version` advances by 1."

    Design: Corner/validations/second_author_cannot_submit_a_revision_for_another_authors_manuscript
    """
    world = fx.setup_revision_requested_manuscript()

    revised = validate_success(
        _revision_request(world["manuscript"]["id"], world["author_headers"])
    )

    a.assert_fields(
        revised,
        status="REVISION_SUBMITTED",
        revision_round=1,
        page_count=18,
        figure_count=2,
        integrity_status="PENDING",
        submitted_review_count=0,
        formatting_status="COMPLIANT",
    )


def test_second_reviewer_registration_under_a_taken_email_collides():
    """Reviewer emails are unique across the society, not merely per journal.

    PRD: "Reviewer and author emails are each unique across the whole database; a collision is `ERR_DUPLICATE_KEY`."

    Design: Corner/validations/duplicate_reviewer_email_rejected
    """
    fx.create_reviewer(
        email="rev_d@inst.org", full_name="Reviewer D", affiliation="Univ Delta"
    )

    response = api_client.create_reviewer(
        f.reviewer_payload(
            email="rev_d@inst.org",
            full_name="Another Person",
            affiliation="Univ Omega",
        ),
        SYSTEM_ADMIN_HEADERS,
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_KEY.value, expected_status=409)


def test_the_colliding_registration_leaves_the_stored_reviewer_alone():
    """One reviewer row survives, still carrying its original details.

    PRD: "Declared unique keys do not collide — otherwise `ERR_DUPLICATE_KEY` (409)."

    Design: Corner/validations/duplicate_reviewer_email_rejected
    """
    first, _headers = fx.create_reviewer(
        email="rev_d@inst.org", full_name="Reviewer D", affiliation="Univ Delta"
    )

    api_client.create_reviewer(
        f.reviewer_payload(
            email="rev_d@inst.org",
            full_name="Another Person",
            affiliation="Univ Omega",
        ),
        SYSTEM_ADMIN_HEADERS,
    )

    rows, meta = validate_paginated(
        api_client.list_reviewers(SYSTEM_ADMIN_HEADERS, params={"limit": 100})
    )
    assert meta["total_count"] == 1, "the collision created no second reviewer"
    a.assert_fields(
        rows[0],
        id=first["id"],
        email="rev_d@inst.org",
        full_name="Reviewer D",
        affiliation="Univ Delta",
    )


def test_the_clock_refuses_to_run_backwards():
    """An instant earlier than the stored one is a rewind, not a move.

    PRD: "A `SystemAdmin` moves it by supplying a `current_utc` instant; the clock may only move forward, so a `current_utc` earlier than the stored value is rejected with `ERR_CLOCK_REWIND` (HTTP 409)."

    Design: Corner/validations/clock_rewind_rejected_while_equal_timestamp_is_accepted
    """
    fx.set_clock("2026-08-01T00:00:00Z")

    response = api_client.set_clock(
        f.clock_payload("2026-07-31T00:00:00Z"), SYSTEM_ADMIN_HEADERS
    )

    validate_error(response, ApiErrorId.ERR_CLOCK_REWIND.value, expected_status=409)


def test_setting_the_clock_to_the_instant_it_already_holds_is_accepted():
    """Equal is not earlier, so a forward-only clock takes the identical instant.

    PRD: "The logical clock moves only forward — otherwise `ERR_CLOCK_REWIND` (409)."

    Design: Corner/validations/clock_rewind_rejected_while_equal_timestamp_is_accepted
    """
    fx.set_clock("2026-08-05T00:00:00Z")

    validate_success(
        api_client.set_clock(
            f.clock_payload("2026-08-05T00:00:00Z"), SYSTEM_ADMIN_HEADERS
        )
    )


def test_a_refused_rewind_leaves_clock_derived_stamps_at_the_epoch():
    """The stored clock never moved, so the next invitation is stamped at the epoch.

    PRD: "Every clock-derived field reads the stored logical clock at the moment its request is served: an invitation's `invited_at` and `due_at`, a reviewer's `responded_at`, a review's `submitted_at`, an invoice's `settled_at`, an ethics case's `resolved_at`, a production job's `published_at`, a manuscript's `retracted_at`, an invitation's `last_reminder_at`, an appeal's `adjudicated_at`, and the lower boundary of the rolling reliability window."

    Design: Corner/validations/clock_rewind_rejected_while_equal_timestamp_is_accepted
    """
    api_client.set_clock(
        f.clock_payload("2026-07-31T00:00:00Z"), SYSTEM_ADMIN_HEADERS
    )
    world = fx.setup_under_review_manuscript()
    reviewer, _headers = fx.create_reviewer()

    invitation = fx.invite_reviewer(
        world["manuscript"]["id"],
        world["handling_headers"],
        reviewer_id=reviewer["id"],
    )

    a.assert_fields(
        invitation,
        invited_at="2026-08-01T00:00:00.000Z",
        due_at="2026-08-22T00:00:00.000Z",
    )
