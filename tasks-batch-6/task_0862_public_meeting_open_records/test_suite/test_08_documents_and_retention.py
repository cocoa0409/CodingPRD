"""Document disposition: the state gate precedes the temporal retention gate
(PRD §2.10, §3.9)."""
from test_helpers import (
    validate_error, ApiErrorId, TEST_USERS,
    setup_request_under_review, attach_document, release_document,
)

CLERK = TEST_USERS["clerk_headers"]


def test_dispose_identified_doc_fails_on_state(api):
    """PRD §3.9: "A `Clerk` or `RecordsOfficer` disposes a document by advancing a
    `RELEASED`, `REDACTED`, or `EXEMPT` document to `DISPOSED`".
    PRD §2.10: "(9) legality of the requested state transition ... failing with
    `ERR_INVALID_STATE` ... (10) temporal compliance gates for notice, appeal
    window, and retention".

    An IDENTIFIED document is not a legal from-state for DISPOSED, so the state
    check fires before the (also-failing) retention check.

    Design: Difficulty/priority_pair_validation_conflict/dispose_state_before_retention_temporal
    """
    ctx = setup_request_under_review(api)
    doc = attach_document(api, ctx, page_count=5, review_minutes=0,
                          retention_series="PERMANENT", title="DocR")
    resp = api.transition_document(ctx["request"]["id"], doc["id"],
                                   {"to_status": "DISPOSED"}, CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_dispose_released_doc_surfaces_retention_gate(api):
    """PRD §3.9: "permitted only when the logical clock is at or after the
    document's `created_at` plus the retention period for its `retention_series`,
    else `ERR_RETENTION_NOT_ELAPSED`".

    A RELEASED document is a legal from-state, so the state check passes and the
    lower-priority temporal retention gate surfaces — confirming state precedes
    temporal.

    Design: Difficulty/priority_pair_validation_conflict/dispose_state_before_retention_temporal
    """
    ctx = setup_request_under_review(api)
    doc = release_document(api, ctx, page_count=5, review_minutes=0,
                           retention_series="ADMIN", title="Keeper")
    resp = api.transition_document(ctx["request"]["id"], doc["id"],
                                   {"to_status": "DISPOSED"}, CLERK)
    validate_error(resp, ApiErrorId.ERR_RETENTION_NOT_ELAPSED.value)


def test_dispose_released_doc_before_retention_rejected(api):
    """PRD §3.9: "permitted only when the logical clock is at or after the document's
    `created_at` plus the retention period for its `retention_series`, else
    `ERR_RETENTION_NOT_ELAPSED`."
    PRD §3.9: "Retention periods, measured in years of 365 days each, are 9999 years
    for `PERMANENT`, 7 years for `FISCAL`, 3 years for `ADMIN`, and 1 year for
    `TRANSITORY`; the comparison is inclusive at day resolution."

    Disposing an ADMIN document at the startup clock (2026-05-01), well before three
    years elapse, is rejected.

    Design: Corner/errors/dispose_released_doc_before_retention_rejected
    """
    ctx = setup_request_under_review(api)
    doc = release_document(api, ctx, page_count=5, review_minutes=0,
                           retention_series="ADMIN", title="Keeper")
    resp = api.transition_document(ctx["request"]["id"], doc["id"],
                                   {"to_status": "DISPOSED"}, CLERK)
    validate_error(resp, ApiErrorId.ERR_RETENTION_NOT_ELAPSED.value)
