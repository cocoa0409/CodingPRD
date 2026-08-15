"""Financial document lifecycle, pagination, and freshness-window claims
(PRD §2.3, §3.1, §3.2)."""
from test_helpers import (
    ALT_STUDENT,
    ApiErrorId,
    assert_financial_document,
    assert_i20_form,
    create_i20_form,
    create_sevis_record,
    create_student,
    review_document,
    set_clock,
    submit_document,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_financial_document_lifecycle_and_double_review_rejected(api, dso_headers):
    """PRD §3.1: "Submission lands the document in `SUBMITTED` status."
    PRD §3.1: "Both outcomes are terminal — a document that has already been
    `VERIFIED` or `REJECTED` cannot be reviewed again, and any attempt to do so
    is rejected with `ERR_DOCUMENT_ALREADY_REVIEWED`."

    Design: Corner/entities/financial_document_lifecycle_and_double_review_rejected
    """
    student = create_student()
    doc = submit_document(student["id"], amount_usd_cents=500000, issue_date="2026-07-01")
    assert_financial_document(doc)
    assert doc["status"] == "SUBMITTED"

    rejected = validate_success(
        api.review_financial_document(
            doc["id"], {"decision": "REJECTED", "note": "Illegible scan"}, dso_headers,
        ),
        200,
    )
    assert rejected["status"] == "REJECTED"

    resp = api.review_financial_document(doc["id"], {"decision": "VERIFIED"}, dso_headers)
    validate_error(resp, ApiErrorId.ERR_DOCUMENT_ALREADY_REVIEWED, 409)


def test_financial_documents_pagination_limit_offset(api, dso_headers):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items
    to return; it defaults to 10, with a minimum of 1 and a maximum of 100. The
    `offset` parameter specifies the number of items to skip and defaults to 0."
    PRD §2.3: "List responses include `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/endpoints/financial_documents_pagination_limit_offset
    """
    student = create_student()
    submit_document(student["id"], 100000, "2026-07-01", "BANK_STATEMENT")
    submit_document(student["id"], 200000, "2026-07-02", "SPONSOR_AFFIDAVIT")
    submit_document(student["id"], 300000, "2026-07-03", "SCHOLARSHIP_LETTER")

    page1, meta1 = validate_paginated(
        api.list_financial_documents(student["id"], dso_headers,
                                     params={"limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_financial_documents(student["id"], dso_headers,
                                     params={"limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_stale_financial_document_excluded_at_183_day_boundary(api, dso_headers):
    """PRD §3.1: "A document counts toward funding totals only when its
    `issue_date` falls within a 183-day window ending on the current clock date
    — that is, issued no earlier than 183 days before today and no later than
    today. Documents dated in the future and documents older than 183 days are
    excluded from every funding computation."
    PRD §3.2: "Verified funding is the sum of `amount_usd_cents` over the
    student's documents that are in `VERIFIED` status and within the 183-day
    freshness window at issuance time; falling short is rejected with
    `ERR_INSUFFICIENT_VERIFIED_FUNDING` (HTTP 402)."

    Design: Corner/calculations/stale_financial_document_excluded_at_183_day_boundary
    """
    set_clock("2026-08-01T00:00:00Z")

    # Student A: document issued exactly 183 days before the clock date is inside
    # the window (inclusive boundary), so issuance succeeds.
    stu_a = create_student()
    rec_a = create_sevis_record(stu_a["id"])
    doc_a = submit_document(stu_a["id"], 2000000, "2026-01-30")
    review_document(doc_a["id"], "VERIFIED")
    i20_a = create_i20_form(stu_a["id"], rec_a["id"])
    issued = validate_success(api.issue_i20_form(i20_a["id"], dso_headers), 200)
    assert_i20_form(issued)
    assert issued["status"] == "ISSUED"
    assert issued["verified_funding_cents"] == 2000000

    # Student B: document issued 184 days before the clock date is outside the
    # window, so verified funding is zero and issuance is rejected.
    stu_b = create_student(**ALT_STUDENT)
    rec_b = create_sevis_record(stu_b["id"])
    doc_b = submit_document(stu_b["id"], 2000000, "2026-01-29")
    review_document(doc_b["id"], "VERIFIED")
    i20_b = create_i20_form(stu_b["id"], rec_b["id"])
    resp = api.issue_i20_form(i20_b["id"], dso_headers)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_VERIFIED_FUNDING, 402)
