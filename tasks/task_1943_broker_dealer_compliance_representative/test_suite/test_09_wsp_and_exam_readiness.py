"""Written supervisory procedures (versioning, publish singleton, SoD) and
examination document requests (sweep, fulfillment timeliness) (PRD §3.9).
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_exam_request_payload,
    create_wsp_payload,
    make_analyst_headers,
    make_principal_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST_1 = make_analyst_headers("analyst-1")
PRINCIPAL_A = TEST_USERS["principal_a_headers"]
ANY = TEST_USERS["any_headers"]


def _draft(policy_area, title, effective_date="2026-08-01",
           drafter=ANALYST_1):
    """Draft a WSP document as the given analyst. Returns the DRAFT dict."""
    return validate_success(
        api_client.create_wsp_document(
            create_wsp_payload(policy_area=policy_area, title=title,
                               effective_date=effective_date),
            drafter,
        ),
        201,
    )


# ─── WSP publish singleton ────────────────────────────

def test_publish_supersedes_predecessor_in_same_request(api, any_headers):
    """PRD §3.9: "Drafting stamps `drafted_by` with the analyst's identifier
    and assigns `version_number` as one greater than the highest existing
    `version_number` within the same policy area — or 1 when the area has no
    documents yet." and "In the same atomic request, the policy area's
    currently published document, if one exists, moves to `SUPERSEDED`, and
    the newly published document's `supersedes_id` is set to that document's
    `id`" — the count of PUBLISHED documents per policy area stays exactly
    one.

    Design: Corner/calculations/compensating_wsp_publish_supersede
    """
    first = _draft("CORRESPONDENCE", "Corr WSP v1", "2026-08-01")
    second = _draft("CORRESPONDENCE", "Corr WSP v2", "2026-09-01")
    assert first["version_number"] == 1
    assert second["version_number"] == 2
    assert first.get("drafted_by") == "analyst-1"

    published1 = validate_success(
        api.publish_wsp_document(first["id"], PRINCIPAL_A), 200
    )
    assert published1["status"] == "PUBLISHED"
    assert published1.get("supersedes_id") is None

    published2 = validate_success(
        api.publish_wsp_document(second["id"], PRINCIPAL_A), 200
    )
    assert published2["status"] == "PUBLISHED"
    assert published2.get("supersedes_id") == first["id"]

    first_after = validate_success(api.get_wsp_document(first["id"], ANY), 200)
    assert first_after["status"] == "SUPERSEDED"

    data, _meta = validate_paginated(
        api.list_wsp_documents(
            ANY, params={"policy_area": "CORRESPONDENCE", "status": "PUBLISHED"}
        )
    )
    assert [d["id"] for d in data] == [second["id"]]


def test_supersede_chain_is_queryable(api, any_headers):
    """PRD §3.9: "the document listing filters by `policy_area`, `status`,
    and `supersedes_id`" — the supersede chain is reachable in both
    directions: filtering by the predecessor's id returns exactly the
    successor, and the area's PUBLISHED filter returns exactly the current
    document.

    Design: Corner/calculations/selector_published_wsp_lookup
    """
    first = _draft("OBA_PST", "OBA v1", "2026-08-01")
    validate_success(api.publish_wsp_document(first["id"], PRINCIPAL_A), 200)
    second = _draft("OBA_PST", "OBA v2", "2026-09-01")
    validate_success(api.publish_wsp_document(second["id"], PRINCIPAL_A), 200)

    successors, _ = validate_paginated(
        api.list_wsp_documents(ANY, params={"supersedes_id": first["id"]})
    )
    assert [d["id"] for d in successors] == [second["id"]]

    published, _ = validate_paginated(
        api.list_wsp_documents(
            ANY, params={"policy_area": "OBA_PST", "status": "PUBLISHED"}
        )
    )
    assert [d["id"] for d in published] == [second["id"]]


def test_publish_twice_rejected(api, any_headers):
    """PRD §3.9: "the document must be in `DRAFT`, else `ERR_WSP_NOT_DRAFT`"
    — a second publish of the same document is rejected.

    Design: Corner/state_machines/wsp_publish_twice_rejected
    """
    doc = _draft("COMPLAINTS", "Complaint WSP v1", "2026-08-01")
    validate_success(api.publish_wsp_document(doc["id"], PRINCIPAL_A), 200)
    res = api.publish_wsp_document(doc["id"], PRINCIPAL_A)
    validate_error(res, ApiErrorId.ERR_WSP_NOT_DRAFT)


def test_wsp_publisher_must_differ_from_drafter(api, any_headers):
    """PRD §2.6: "a WSP document may only be published by a principal whose
    `X-User-ID` differs from the identifier recorded in the document's
    `drafted_by` field; an attempt by the drafting analyst to publish their
    own document is rejected with `ERR_SOD_WSP_PUBLISHER` (HTTP 403)."

    Design: Corner/rbac/wsp_publish_sod
    """
    doc = _draft("BOOKS_RECORDS", "Records WSP", "2026-08-01",
                 drafter=make_analyst_headers("analyst-7"))
    assert doc.get("drafted_by") == "analyst-7"

    res = api.publish_wsp_document(
        doc["id"], make_principal_headers("analyst-7")
    )
    validate_error(res, ApiErrorId.ERR_SOD_WSP_PUBLISHER)

    published = validate_success(
        api.publish_wsp_document(doc["id"], make_principal_headers("principal-9")),
        200,
    )
    assert published["status"] == "PUBLISHED"
    assert published.get("published_by") == "principal-9"


# ─── exam document requests ───────────────────────────

def test_exam_fulfill_after_due_date_marks_late(api, any_headers):
    """PRD §2.5: "Any ExamDocumentRequest in `OPEN` whose `due_date` is
    earlier than the new clock date transitions to `OVERDUE`." PRD §3.9:
    "Fulfillment, also an analyst act, is permitted from `OPEN` or `OVERDUE`
    — fulfilling an already `FULFILLED` request is rejected with
    `ERR_EXAM_REQUEST_INVALID_STATE` — and records the
    `produced_document_ref`, stamps `fulfilled_at` from the logical clock,
    and computes `is_late`, true when the calendar date of `fulfilled_at`
    falls after the `due_date`." The request due 2026-08-03 is swept at
    2026-08-05 and fulfills late; the one due 2026-08-10 fulfills on time.

    Design: Corner/cross_cutting/exam_fulfill_late_marks_flag
    """
    first = validate_success(
        api_client.create_exam_request(
            create_exam_request_payload(regulator="FINRA", request_ref="R-1",
                                        document_type="TRADE_BLOTTER",
                                        due_date="2026-08-03"),
            ANALYST_1,
        ),
        201,
    )
    second = validate_success(
        api_client.create_exam_request(
            create_exam_request_payload(regulator="SEC", request_ref="R-2",
                                        document_type="WSP_COPY",
                                        due_date="2026-08-10"),
            ANALYST_1,
        ),
        201,
    )

    set_clock("2026-08-05T09:00:00Z")
    swept = validate_success(api.get_exam_request(first["id"], ANY), 200)
    assert swept["status"] == "OVERDUE"

    late = validate_success(
        api.fulfill_exam_request(first["id"],
                                 {"produced_document_ref": "worm://store/r1"},
                                 ANALYST_1),
        200,
    )
    assert late["status"] == "FULFILLED"
    assert late["is_late"] is True
    assert late.get("produced_document_ref") == "worm://store/r1"

    on_time = validate_success(
        api.fulfill_exam_request(second["id"],
                                 {"produced_document_ref": "worm://store/r2"},
                                 ANALYST_1),
        200,
    )
    assert on_time["is_late"] is False


def test_double_fulfill_exam_rejected(api, any_headers):
    """PRD §3.9: "fulfilling an already `FULFILLED` request is rejected with
    `ERR_EXAM_REQUEST_INVALID_STATE`".

    Design: Corner/cross_cutting/double_fulfill_exam_rejected
    """
    request = validate_success(
        api_client.create_exam_request(
            create_exam_request_payload(regulator="STATE", request_ref="R-9",
                                        document_type="COMPLAINT_FILE",
                                        due_date="2026-08-10"),
            ANALYST_1,
        ),
        201,
    )
    fulfilled = validate_success(
        api.fulfill_exam_request(request["id"],
                                 {"produced_document_ref": "worm://store/r9"},
                                 ANALYST_1),
        200,
    )
    assert fulfilled["status"] == "FULFILLED"

    res = api.fulfill_exam_request(
        request["id"], {"produced_document_ref": "worm://store/r9b"}, ANALYST_1
    )
    validate_error(res, ApiErrorId.ERR_EXAM_REQUEST_INVALID_STATE)
