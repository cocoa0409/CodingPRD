"""One reachable not-found error per entity: every path identifier is resolved first."""

import pytest

from prd_bench_local_runner.testing import NON_EXISTENT_UUID, validate_error

from test_helpers import ApiErrorId
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import PRODUCTION_STAFF_HEADERS, SYSTEM_ADMIN_HEADERS, api_client

MISSING = NON_EXISTENT_UUID

# One single-identifier read per entity that owns a not-found identifier, each
# reachable by the opaque editorial-office role so that no entity-backed
# identity check can intervene ahead of the path lookup.
SINGLE_ID_READS = [
    (
        "journal",
        lambda: api_client.get_journal(MISSING, SYSTEM_ADMIN_HEADERS),
        ApiErrorId.ERR_JOURNAL_NOT_FOUND.value,
    ),
    (
        "editor",
        lambda: api_client.get_editor(MISSING, SYSTEM_ADMIN_HEADERS),
        ApiErrorId.ERR_EDITOR_NOT_FOUND.value,
    ),
    (
        "author",
        lambda: api_client.get_author(MISSING, SYSTEM_ADMIN_HEADERS),
        ApiErrorId.ERR_AUTHOR_NOT_FOUND.value,
    ),
    (
        "reviewer",
        lambda: api_client.get_reviewer(MISSING, SYSTEM_ADMIN_HEADERS),
        ApiErrorId.ERR_REVIEWER_NOT_FOUND.value,
    ),
    (
        "manuscript",
        lambda: api_client.get_manuscript(MISSING, SYSTEM_ADMIN_HEADERS),
        ApiErrorId.ERR_MANUSCRIPT_NOT_FOUND.value,
    ),
    (
        "editor_assignment",
        lambda: api_client.get_editor_assignment(MISSING, SYSTEM_ADMIN_HEADERS),
        ApiErrorId.ERR_EDITOR_ASSIGNMENT_NOT_FOUND.value,
    ),
    (
        "review_invitation",
        lambda: api_client.get_review_invitation(MISSING, SYSTEM_ADMIN_HEADERS),
        ApiErrorId.ERR_REVIEW_INVITATION_NOT_FOUND.value,
    ),
    (
        "decision",
        lambda: api_client.get_decision(MISSING, SYSTEM_ADMIN_HEADERS),
        ApiErrorId.ERR_DECISION_NOT_FOUND.value,
    ),
    (
        "appeal",
        lambda: api_client.get_appeal(MISSING, SYSTEM_ADMIN_HEADERS),
        ApiErrorId.ERR_APPEAL_NOT_FOUND.value,
    ),
    (
        "ethics_case",
        lambda: api_client.get_ethics_case(MISSING, SYSTEM_ADMIN_HEADERS),
        ApiErrorId.ERR_ETHICS_CASE_NOT_FOUND.value,
    ),
    (
        "production_job",
        lambda: api_client.get_production_job(MISSING, SYSTEM_ADMIN_HEADERS),
        ApiErrorId.ERR_PRODUCTION_JOB_NOT_FOUND.value,
    ),
    (
        "apc_invoice",
        lambda: api_client.get_apc_invoice(MISSING, SYSTEM_ADMIN_HEADERS),
        ApiErrorId.ERR_APC_INVOICE_NOT_FOUND.value,
    ),
]


@pytest.mark.parametrize(
    "entity,call,expected_error_id",
    SINGLE_ID_READS,
    ids=[case[0] for case in SINGLE_ID_READS],
)
def test_missing_row_behind_a_path_id_answers_with_that_entitys_not_found_error(
    entity, call, expected_error_id
):
    """Each entity addressed by an unknown identifier answers with its own 404.

    PRD: "Every path parameter references an existing row of its entity — otherwise the matching not-found error for that entity (404), on every endpoint that has a path parameter."

    Design: Corner/errors/every_path_id_not_found_error_is_reachable
    """
    response = call()

    error = validate_error(response, expected_error_id, expected_status=404)
    assert error["error_id"] == expected_error_id, (
        f"the {entity} route must name its own not-found identifier"
    )


def test_nested_invoice_read_reports_the_missing_manuscript_first():
    """The parent identifier is resolved before the child, so the manuscript answers.

    PRD: "On a nested read such as `GET /manuscripts/{manuscript_id}/apc-invoices/{invoice_id}`, the manuscript named by `manuscript_id` is resolved first; if no such manuscript exists the answer is `ERR_MANUSCRIPT_NOT_FOUND` (HTTP 404)."

    Design: Corner/errors/every_path_id_not_found_error_is_reachable
    """
    response = api_client.get_manuscript_apc_invoice(
        MISSING, MISSING, SYSTEM_ADMIN_HEADERS
    )

    validate_error(response, ApiErrorId.ERR_MANUSCRIPT_NOT_FOUND.value, expected_status=404)


def test_slot_booking_on_a_missing_job_is_a_not_found_and_not_a_body_complaint():
    """A write endpoint resolves its path identifier before it looks at the body.

    PRD: "Every path parameter references an existing row of its entity — otherwise the matching not-found error for that entity (404), on every endpoint that has a path parameter."

    Design: Corner/errors/every_path_id_not_found_error_is_reachable
    """
    response = api_client.book_typeset_slot(
        MISSING,
        f.typeset_slot_payload("2026-09-01", "2026-09-05", 1),
        PRODUCTION_STAFF_HEADERS,
    )

    error = validate_error(
        response, ApiErrorId.ERR_PRODUCTION_JOB_NOT_FOUND.value, expected_status=404
    )
    assert error["error_id"] != ApiErrorId.ERR_STALE_PRODUCTION_JOB_VERSION.value, (
        "the version guard belongs to a later rung than the path lookup"
    )


def test_nested_invoice_read_reports_the_missing_child_once_the_parent_resolves():
    """With a real manuscript in the path, the unresolved child identifier answers.

    PRD: "The invoice named by `invoice_id` is resolved next; a missing invoice yields `ERR_APC_INVOICE_NOT_FOUND` (HTTP 404)."

    Design: Corner/errors/every_path_id_not_found_error_is_reachable
    """
    world = fx.setup_submitted_manuscript()

    response = api_client.get_manuscript_apc_invoice(
        world["manuscript"]["id"], MISSING, SYSTEM_ADMIN_HEADERS
    )

    error = validate_error(
        response, ApiErrorId.ERR_APC_INVOICE_NOT_FOUND.value, expected_status=404
    )
    assert error["error_id"] != ApiErrorId.ERR_MANUSCRIPT_NOT_FOUND.value, (
        "the parent resolved, so the child identifier is the one that failed"
    )


def test_settlement_of_a_missing_invoice_is_a_not_found():
    """The settlement endpoint answers for the invoice identifier it cannot resolve.

    PRD: "Every path parameter references an existing row of its entity — otherwise the matching not-found error for that entity (404), on every endpoint that has a path parameter."

    Design: Corner/errors/every_path_id_not_found_error_is_reachable
    """
    response = api_client.settle_apc_invoice(
        MISSING, f.pay_settlement_payload(180000), PRODUCTION_STAFF_HEADERS
    )

    validate_error(
        response, ApiErrorId.ERR_APC_INVOICE_NOT_FOUND.value, expected_status=404
    )
