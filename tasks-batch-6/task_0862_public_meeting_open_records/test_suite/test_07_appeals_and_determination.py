"""Determinations (OCC-guarded), the appeal branches, segregation of duties, and
the appeal window (PRD §2.8, §3.8, §3.9)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, ANON_HEADERS, set_clock,
    make_appeals_officer_headers, TEST_USERS,
    create_appeal_payload, create_document_payload,
    setup_appeal_under_review, setup_request_under_review, setup_determined_request,
    setup_denied_request, setup_records_request, file_appeal, attach_document,
    issue_determination,
)

RECORDS_OFFICER = TEST_USERS["records_officer_headers"]


# ===========================================================================
# Appeal branch: OVERTURNED mutates the request; UPHELD does not
# ===========================================================================

def test_overturned_appeal_grants_request(api):
    """PRD §3.9: "Overturning (`UNDER_REVIEW → OVERTURNED`) sets the decision to
    `OVERTURNED` and cascades the request from `DENIED` to `GRANTED`, recomputing the
    assessed fee over the now-released documents."

    Design: Difficulty/non_linear_state_machine/appeal_branch_overturned_mutates_request
    """
    ctx = setup_appeal_under_review(api)
    appeal = validate_success(api.transition_appeal(
        ctx["request"]["id"], ctx["appeal"]["id"], {"to_status": "OVERTURNED"},
        ctx["appeals_headers"]))
    assert appeal["status"] == "OVERTURNED"
    assert appeal["decision"] == "OVERTURNED"
    req = validate_success(api.get_records_request(ctx["request"]["id"], RECORDS_OFFICER))
    assert req["status"] == "GRANTED"
    assert req["decision"] == "GRANTED"


def test_upheld_appeal_leaves_request_denied(api):
    """PRD §3.9: "Upholding (`UNDER_REVIEW → UPHELD`) sets the appeal `decision` to
    `UPHELD` and leaves the request unchanged — the denial stands."

    Design: Difficulty/non_linear_state_machine/appeal_branch_overturned_mutates_request
    """
    ctx = setup_appeal_under_review(api)
    appeal = validate_success(api.transition_appeal(
        ctx["request"]["id"], ctx["appeal"]["id"], {"to_status": "UPHELD"},
        ctx["appeals_headers"]))
    assert appeal["status"] == "UPHELD"
    assert appeal["decision"] == "UPHELD"
    req = validate_success(api.get_records_request(ctx["request"]["id"], RECORDS_OFFICER))
    assert req["status"] == "DENIED"


# ===========================================================================
# Cross-entity: filing an appeal requires the request DENIED/PARTIALLY_GRANTED
# ===========================================================================

def test_file_appeal_while_under_review_rejected(api):
    """PRD §3.9: "An appeal may be filed only while the request is `DENIED` or
    `PARTIALLY_GRANTED`, else `ERR_REQUEST_NOT_DENIED`".

    Design: Difficulty/cross_entity_state_dependency/appeal_file_requires_request_denied
    """
    ctx = setup_request_under_review(api)
    resp = api.create_appeal(ctx["request"]["id"], create_appeal_payload(grounds="Too slow"),
                             ctx["requester_headers"])
    validate_error(resp, ApiErrorId.ERR_REQUEST_NOT_DENIED.value)


def test_file_appeal_on_granted_request_rejected(api):
    """PRD §3.9: "An appeal may be filed only while the request is `DENIED` or
    `PARTIALLY_GRANTED`, else `ERR_REQUEST_NOT_DENIED`".

    A GRANTED request (fee-free, within the window) is still not an appealable state.

    Design: Difficulty/cross_entity_state_dependency/appeal_file_requires_request_denied
    """
    ctx = setup_determined_request(api, decision="GRANTED", docs=[(50, 0)])
    resp = api.create_appeal(ctx["request"]["id"], create_appeal_payload(grounds="Want more"),
                             ctx["requester_headers"])
    validate_error(resp, ApiErrorId.ERR_REQUEST_NOT_DENIED.value)


# ===========================================================================
# Corner: SoD, appeal window, OCC, auth, document precondition
# ===========================================================================

def test_same_officer_cannot_review_own_appeal(api):
    """PRD §3.9: "the acting officer's `X-User-ID` must differ from the request's
    `determined_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`".

    Design: Corner/rbac/same_officer_cannot_review_own_appeal_sod
    """
    ctx = setup_denied_request(api, officer_id="officer-7")
    ctx["appeal"] = file_appeal(api, ctx, grounds="unfair")
    resp = api.transition_appeal(
        ctx["request"]["id"], ctx["appeal"]["id"], {"to_status": "UNDER_REVIEW"},
        make_appeals_officer_headers("officer-7"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


def test_appeal_after_window_closed_rejected(api):
    """PRD §3.9: "only within the appeal window — the logical clock must be at or
    before `determined_at` plus 30 days, else `ERR_APPEAL_WINDOW_CLOSED`."

    Determined at 2026-05-01; filing at 2026-06-02 is past the 30-day window.

    Design: Corner/errors/appeal_after_window_closed_rejected
    """
    ctx = setup_denied_request(api, officer_id="officer-2")
    set_clock(api, "2026-06-02T00:00:00Z")
    resp = api.create_appeal(ctx["request"]["id"], create_appeal_payload(grounds="late"),
                             ctx["requester_headers"])
    validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED.value)


def test_determination_stale_version_rejected(api):
    """PRD §2.8: "If that value does not equal the request's current `version`, the
    determination is rejected with `ERR_STALE_VERSION` (HTTP 412)".
    PRD §2.8: "Attaching a responsive document to a request increments the request's
    `version`".

    Design: Corner/cross_cutting_complexity_layers/determination_stale_version_conflict
    """
    ctx = setup_request_under_review(api)
    old_version = ctx["request"]["version"]
    attach_document(api, ctx, page_count=5, review_minutes=0, title="Late add")
    resp = issue_determination(api, ctx, decision="GRANTED", expected_version=old_version)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_determination_correct_version_succeeds(api):
    """PRD §3.8: "The officer issues a **determination** advancing the request from
    `UNDER_REVIEW` to `GRANTED`, `PARTIALLY_GRANTED`, or `DENIED`" ... "sets
    `decision` and `status` to match the branch."

    A determination carrying the current version succeeds.

    Design: Corner/cross_cutting_complexity_layers/determination_correct_version_increments
    """
    ctx = setup_request_under_review(api)
    req = validate_success(issue_determination(api, ctx, decision="DENIED"))
    assert req["decision"] == "DENIED"
    assert req["status"] == "DENIED"


def test_determination_without_auth_unauthenticated(api):
    """PRD §2.1: "A request that omits or supplies an invalid header pair on a
    protected endpoint is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_on_determination_unauthenticated
    """
    ctx = setup_request_under_review(api)
    version = ctx["request"]["version"]
    resp = api.determine_request(
        ctx["request"]["id"],
        {"decision": "DENIED", "expected_records_request_version": version},
        ANON_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_attach_document_while_received_rejected(api):
    """PRD §3.8: "Attaching a document is permitted only while the parent request is
    `UNDER_REVIEW`, else `ERR_DOCUMENT_REQUEST_NOT_UNDER_REVIEW`".

    Design: Corner/errors/create_document_in_received_request_rejected
    """
    ctx = setup_records_request(api)
    resp = api.create_document(
        ctx["request"]["id"],
        create_document_payload(title="Premature", page_count=5, review_minutes=0),
        RECORDS_OFFICER)
    validate_error(resp, ApiErrorId.ERR_DOCUMENT_REQUEST_NOT_UNDER_REVIEW.value)
