"""Foreign-key reverse reachability: every child collection is listable through
its parent path with exact cardinalities on a deal driven to CLOSING
(PRD sections 2.10, 3.1-3.8, 4).
"""
from test_helpers import (
    approve_item, add_checklist_item, add_covenant, deal_closing, get_letter,
    propose_participation, request_funding, validate_paginated, api_client,
)


def test_fk_reverse_reachability_full_child_set():
    """PRD section 2.10: "For addressability, nested read paths are provided
    wherever a reverse traversal is natural (for example, listing the appraisals
    of an application or the appraisals of an appraiser)."
    PRD section 3.6: acceptance "creates a commitment letter in `DRAFT` status that
    mirrors the sheet's economics — the letter's `committed_amount_cents`,
    `rate_bps`, `term_months`, and `origination_fee_cents` equal the accepted
    sheet's."
    PRD section 3.7: "an `is_required` flag defaulting to `true` ... and a
    `severity` of `STANDARD` or `CRITICAL` defaulting to `STANDARD`".

    Design: Corner/entities/fk_reverse_reachability_full_child_set
    """
    ctx = deal_closing(
        borrower_kw={"legal_name": "Meridian Industrial Parks", "naics_code": "531120",
                     "relationship_since": "2010-01-01"},
        app_kw={"requested_amount_cents": 200_000_000, "term_months": 60},
        statement_shape="MERIDIAN",
        with_closing_condition=True)
    o = ctx["o"]
    app_id = ctx["application"]["id"]

    # One PROPOSED participation and one REQUESTED authorization before closing reads.
    p1 = propose_participation(o, app_id, participant_bank_name="Bank North",
                               allocated_amount_cents=10_000_000)
    fa = request_funding(o, app_id, amount_cents=50_000_000)

    an = o["an"]["headers"]

    rows, _ = validate_paginated(api_client.list_borrower_applications(ctx["borrower"]["id"], an))
    assert [r["id"] for r in rows] == [app_id]

    rows, _ = validate_paginated(api_client.list_application_appraisals(app_id, an))
    assert [r["id"] for r in rows] == [ctx["appraisal"]["id"]]

    rows, _ = validate_paginated(api_client.list_appraiser_appraisals(ctx["appraiser"]["id"], an))
    assert [r["id"] for r in rows] == [ctx["appraisal"]["id"]]

    rows, meta = validate_paginated(api_client.list_application_exceptions(app_id, an))
    assert rows == [], "the clean deal auto-created none"

    rows, _ = validate_paginated(api_client.list_application_term_sheets(app_id, an))
    assert len(rows) == 1
    assert rows[0]["id"] == ctx["sheet"]["id"]
    assert rows[0]["status"] == "ACCEPTED"

    rows, _ = validate_paginated(api_client.list_application_decisions(app_id, an))
    assert len(rows) == 1
    assert rows[0]["id"] == ctx["decision"]["id"]
    assert rows[0]["status"] == "APPROVED"

    rows, _ = validate_paginated(api_client.list_session_decisions(ctx["session"]["id"], an))
    assert [r["id"] for r in rows] == [ctx["decision"]["id"]]

    letters, _ = validate_paginated(api_client.list_commitment_letters(
        an, params={"loan_application_id": app_id}))
    assert len(letters) == 1
    letter = letters[0]
    assert letter["id"] == ctx["letter"]["id"]
    assert letter["committed_amount_cents"] == 200_000_000
    assert letter["rate_bps"] == 650
    assert letter["term_months"] == 60
    assert letter["origination_fee_cents"] == 1_750_000

    items, _ = validate_paginated(api_client.list_application_checklist_items(app_id, an))
    assert len(items) == 2
    for item in items:
        assert item["is_required"] is True, "created without the flag shows the default"
        assert item["severity"] == "STANDARD", "created without severity shows the default"

    covs, _ = validate_paginated(api_client.list_application_covenants(app_id, an))
    assert len(covs) == 1
    assert covs[0]["id"] == ctx["covenant"]["id"]
    assert covs[0]["status"] == "MONITORING"

    parts, _ = validate_paginated(api_client.list_application_participations(app_id, an))
    assert len(parts) == 1
    assert parts[0]["id"] == p1["id"]
    assert parts[0]["status"] == "PROPOSED"

    fas, _ = validate_paginated(api_client.list_application_funding_authorizations(app_id, an))
    assert len(fas) == 1
    assert fas[0]["id"] == fa["id"]
    assert fas[0]["status"] == "REQUESTED"

    stmts, _ = validate_paginated(api_client.list_financial_statements(
        an, params={"loan_application_id": app_id}))
    assert len(stmts) == 1
    assert stmts[0]["id"] == ctx["statement"]["id"]
    assert stmts[0]["status"] == "FINAL"
