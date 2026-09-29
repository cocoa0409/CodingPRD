"""Two endpoint-shape concerns: the sweep's counter payload and citation listing.

The continuous-monitoring checkpoint is the only operation whose success body is
a counter object rather than a resource, and it must answer with all four
reported values even when nothing was due. The citation list, by contrast, is an
ordinary paginated collection that has to honour its classification filter and
report the page metadata alongside it.
"""

from test_helpers import (
    InvestigationOrigin,
    Severity,
    fixtures as H,
    validate_paginated,
    validate_success,
)


def test_compliance_sweep_reports_all_three_counters_at_zero(api, board_admin_headers):
    """With nothing due the checkpoint still answers with its three counters.

    "The checkpoint reports what it did as `lapsed_coverage_count`,
    `expired_license_count`, `suspended_license_count` and the `swept_on` date
    it ran against."

    Design: Corner/endpoints/corner_compliance_sweep_returns_its_inline_counter_payload
    """
    H.set_clock(api, "2026-08-01T00:00:00Z")

    swept = validate_success(api.run_compliance_sweep(board_admin_headers))

    assert swept["lapsed_coverage_count"] == 0
    assert swept["expired_license_count"] == 0
    assert swept["suspended_license_count"] == 0


def test_compliance_sweep_stamps_swept_on_from_the_logical_clock(api, board_admin_headers):
    """The date the sweep reports is the clock date, not the host's wall clock.

    "Creation timestamps, licence issuance dates, application submission
    timestamps, hearing decision timestamps, disbursement dates and the date
    stamped by a compliance sweep all derive from it."

    Design: Corner/endpoints/corner_compliance_sweep_returns_its_inline_counter_payload
    """
    H.set_clock(api, "2026-08-01T00:00:00Z")

    swept = validate_success(api.run_compliance_sweep(board_admin_headers))

    assert swept["swept_on"] == "2026-08-01"


def _three_sting_citations(api):
    """Two unlicensed citations under C-10 and one under C-20."""
    H.set_clock(api, "2026-08-01T00:00:00Z")
    c10 = H.create_c10_classification(api)
    c20 = H.create_c20_classification(api)

    citations = []
    for business_name, severity, classification in (
        ("Handshake Electric", Severity.MINOR, c10),
        ("Cash Wiring Co", Severity.SERIOUS, c10),
        ("Ductless Dan", Severity.MINOR, c20),
    ):
        investigation = H.open_investigation(
            api,
            origin=InvestigationOrigin.STING,
            subject_business_name=business_name,
        )
        H.substantiate(
            api,
            investigation["id"],
            severity=severity,
            evidence_summary="Bid taken without a licence",
        )
        citations.append(
            H.issue_citation(
                api,
                investigation["id"],
                classification["id"],
                violation_code="B-7028",
                correction_due_date="2026-09-15",
            )
        )
    return c10, c20, citations


def test_citation_list_filters_by_classification_id(api, licensing_analyst_headers):
    """Filtering by the C-10 classification counts only the two C-10 citations.

    "Citations may be read individually, exposing the penalty, the
    `penalty_variant`, the prior-citation count and the appeal deadline; or
    listed filtered by `investigation_id`, `license_id`, `classification_id` or
    `status`."

    Design: Corner/endpoints/corner_citations_list_filters_by_classification_id
    """
    c10, _c20, _citations = _three_sting_citations(api)

    rows, meta = validate_paginated(
        api.list_citations(licensing_analyst_headers, {"classification_id": c10["id"]})
    )

    assert meta["total_count"] == 2
    assert [row["classification_id"] for row in rows] == [c10["id"], c10["id"]]


def test_citation_list_limit_of_one_reports_a_further_page(api, licensing_analyst_headers):
    """A limit of one returns a single C-10 row and flags more behind it.

    "`limit` caps the number of rows returned; it defaults to 10 when omitted,
    may not be smaller than 1, and may not exceed 100." "Every list response
    carries `limit`, `offset`, `total_count` and `has_more` inside the `meta`
    object of the envelope."

    Design: Corner/endpoints/corner_citations_list_filters_by_classification_id
    """
    c10, _c20, _citations = _three_sting_citations(api)

    rows, meta = validate_paginated(
        api.list_citations(
            licensing_analyst_headers,
            {"classification_id": c10["id"], "limit": 1, "offset": 0},
        )
    )

    assert len(rows) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert rows[0]["classification_id"] == c10["id"]


def test_citation_list_filter_isolates_the_other_classification(api, licensing_analyst_headers):
    """The C-20 filter sees only the single citation raised under that trade.

    "Citations may be read individually, exposing the penalty, the
    `penalty_variant`, the prior-citation count and the appeal deadline; or
    listed filtered by `investigation_id`, `license_id`, `classification_id` or
    `status`."

    Design: Corner/endpoints/corner_citations_list_filters_by_classification_id
    """
    _c10, c20, _citations = _three_sting_citations(api)

    rows, meta = validate_paginated(
        api.list_citations(licensing_analyst_headers, {"classification_id": c20["id"]})
    )

    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["classification_id"] == c20["id"]
