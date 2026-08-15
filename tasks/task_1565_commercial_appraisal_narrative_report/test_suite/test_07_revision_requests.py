"""Client revision requests: the thirty-day window, value-pressure
independence, open/escalated queue gates, reviewer resolution of escalated
requests, and optimistic concurrency on the report version (PRD §2.7, §3.7)."""
from test_helpers import (
    TEST_USERS,
    fresh_report,
    setup_report_client_review,
    setup_report_revision_requested,
    validate_error,
    validate_success,
)

EM = TEST_USERS["engagement_manager_headers"]


def test_value_pressure_accept_rejected_409(api):
    """PRD §2.8: "Client pressure on value conclusions is never actionable: a
    revision request whose `category` is `VALUE_PRESSURE` may be declined,
    escalated, or withdrawn, but any attempt to accept it is rejected with
    `ERR_INDEPENDENCE_COMPROMISE` (HTTP 409)." The request stays `OPEN` and
    the report's conclusion (106,571,429) is untouched.

    Design: Corner/errors/value_pressure_accept_rejected_409
    """
    bundle = setup_report_revision_requested(
        category="VALUE_PRESSURE",
        requested_change="Need value at 100M for loan sizing",
        proposed_value_cents=99999999)
    report = fresh_report(bundle, bundle["report"]["id"])
    res = api.accept_revision_request(
        bundle["request"]["id"],
        {"expected_report_version": report["version"],
         "resolution_note": "Accepting per client ask",
         "value_adjustment_cents": 1000000},
        bundle["author_headers"])
    validate_error(res, "ERR_INDEPENDENCE_COMPROMISE", expected_status=409)
    req_after = validate_success(
        api.get_revision_request(bundle["request"]["id"], EM), 200)
    assert req_after["status"] == "OPEN"
    report_after = fresh_report(bundle, report["id"])
    assert report_after["value_conclusion_cents"] == 106571429


def test_reissue_with_open_request_returns_409(api):
    """PRD §3.7: "Reissuing the report — `REVISION_REQUESTED` back to
    `CLIENT_REVIEW` — requires that no request on the report remain `OPEN`
    (`ERR_REVISION_REQUESTS_OPEN`)".

    Design: Corner/errors/reissue_with_open_request_returns_409
    """
    bundle = setup_report_revision_requested(
        category="CLARIFICATION", requested_change="Clarify zoning")
    res = api.reissue_report(bundle["report"]["id"], bundle["author_headers"])
    validate_error(res, "ERR_REVISION_REQUESTS_OPEN", expected_status=409)


def test_finalize_with_escalated_request_returns_409(api):
    """PRD §3.7: "Finalizing — `CLIENT_REVIEW` to `FINAL` — requires that no
    request stand `OPEN` or `ESCALATED` (`ERR_REVISION_REQUESTS_OPEN`)" —
    stricter than reissue, which §3.7 gates only on `OPEN` requests, so the
    escalated request permits reissue but still blocks finalize.

    Design: Corner/errors/finalize_with_escalated_request_returns_409
    """
    bundle = setup_report_revision_requested(
        category="METHODOLOGY_QUESTION",
        requested_change="Why was the trailing NOI used in the DCF?")
    escalated = validate_success(api.escalate_revision_request(
        bundle["request"]["id"], bundle["author_headers"]), 200)
    assert escalated["status"] == "ESCALATED"
    reissued = validate_success(
        api.reissue_report(bundle["report"]["id"], bundle["author_headers"]), 200)
    assert reissued["status"] == "CLIENT_REVIEW"
    res = api.finalize_report(bundle["report"]["id"], bundle["author_headers"])
    validate_error(res, "ERR_REVISION_REQUESTS_OPEN", expected_status=409)


def test_escalated_request_declined_by_reviewer(api):
    """PRD §3.7: "Declining is split by seat: from `OPEN` the author
    declines, and from `ESCALATED` only the assigned reviewer may decline
    (`ERR_NOT_ASSIGNED_REVIEWER`); either way a `resolution_note` is
    required, and its absence is `ERR_INVALID_REQUEST`."

    Design: Corner/rbac/escalated_request_declined_by_reviewer
    """
    bundle = setup_report_revision_requested(
        category="VALUE_PRESSURE", requested_change="Stretch the value",
        proposed_value_cents=99999999)
    validate_success(api.escalate_revision_request(
        bundle["request"]["id"], bundle["author_headers"]), 200)
    declined = validate_success(api.decline_revision_request(
        bundle["request"]["id"],
        {"resolution_note": "Reviewer upholds independence; value unchanged"},
        bundle["reviewer_headers"]), 200)
    assert declined["status"] == "DECLINED"


def test_revision_window_boundary(api):
    """PRD §3.7: "a filing later than thirty days after
    `issued_to_client_at` is rejected with `ERR_REVISION_WINDOW_CLOSED`" — a
    filing at exactly thirty days is not later and is accepted; and
    "Reissuing the report — `REVISION_REQUESTED` back to `CLIENT_REVIEW` —
    requires that no request on the report remain `OPEN`
    (`ERR_REVISION_REQUESTS_OPEN`) and refreshes `issued_to_client_at`,
    restarting the thirty-day window", so a filing one second past the
    restarted window closes with `ERR_REVISION_WINDOW_CLOSED`.

    Design: Corner/calculations/revision_window_boundary
    """
    bundle = setup_report_client_review()
    report = bundle["report"]
    api.set_clock({"to_iso8601": "2026-08-31T00:00:00Z"},
                  TEST_USERS["engagement_manager_headers"])
    req1 = validate_success(api.create_revision_request(
        report["id"],
        {"category": "CLARIFICATION",
         "requested_change": "Clarify zoning paragraph"},
        bundle["client_headers"]), 201)
    assert req1["status"] == "OPEN", (
        "a filing at exactly issued_to_client_at + 30 days is inside the window")

    validate_success(api.withdraw_revision_request(
        req1["id"], bundle["client_headers"]), 200)
    reissued = validate_success(
        api.reissue_report(report["id"], bundle["author_headers"]), 200)
    assert reissued["status"] == "CLIENT_REVIEW"

    api.set_clock({"to_iso8601": "2026-09-30T00:00:01Z"},
                  TEST_USERS["engagement_manager_headers"])
    res = api.create_revision_request(
        report["id"],
        {"category": "CLARIFICATION", "requested_change": "Late request"},
        bundle["client_headers"])
    validate_error(res, "ERR_REVISION_WINDOW_CLOSED", expected_status=409)


def test_occ_revision_accept_stale_version(api):
    """PRD §3.7: "The author may accept an `OPEN` request — the second
    optimistic-concurrency write of §2.7, so the request must carry
    `expected_report_version` matching the report's current `version`, else
    `ERR_STALE_REPORT_VERSION` (HTTP 412)". After the first accept applies
    its adjustment and bumps the report, a second accept carrying the
    pre-acceptance version is stale; and "when the accept supplies
    `value_adjustment_cents`, that signed amount is added to the report's
    `value_conclusion_cents`" — applied exactly once (106,571,429 + 10,000 =
    106,581,429).

    Design: Corner/cross_cutting_complexity_layers/occ_revision_accept_stale_version
    """
    bundle = setup_report_revision_requested(
        category="FACTUAL_CORRECTION",
        requested_change="Correct the site area figure")
    req1 = bundle["request"]
    report_pre = fresh_report(bundle, bundle["report"]["id"])
    accepted = validate_success(api.accept_revision_request(
        req1["id"],
        {"expected_report_version": report_pre["version"],
         "resolution_note": "Site area corrected",
         "value_adjustment_cents": 10000},
        bundle["author_headers"]), 200)
    assert accepted["status"] == "ACCEPTED"

    validate_success(
        api.reissue_report(report_pre["id"], bundle["author_headers"]), 200)
    req2 = validate_success(api.create_revision_request(
        report_pre["id"],
        {"category": "CLARIFICATION",
         "requested_change": "Clarify the cap-rate narrative"},
        bundle["client_headers"]), 201)

    res = api.accept_revision_request(
        req2["id"],
        {"expected_report_version": report_pre["version"],
         "resolution_note": "Narrative clarified"},
        bundle["author_headers"])
    validate_error(res, "ERR_STALE_REPORT_VERSION", expected_status=412)

    report_end = fresh_report(bundle, report_pre["id"])
    assert report_end["value_conclusion_cents"] == 106581429, (
        "the accepted request's adjustment must be applied exactly once; "
        f"expected 106581429, got {report_end['value_conclusion_cents']}")
