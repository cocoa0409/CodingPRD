"""Endpoint cross-reference links and the filing-deadline error complement:
cascade-created invoices discoverable only via filtered list, the three
auto-created compliance records, and claim-line filtering by entry."""
from test_helpers import ApiErrorId, add_claim, add_claim_line, add_import_entry, file_claim, set_clock, setup_draft_claim_with_line, setup_paid_claim, setup_trade_scenario, TEST_USERS, validate_error, validate_paginated, validate_success

ADMIN = TEST_USERS["firm_admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
BROKER = TEST_USERS["broker_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


def test_invoice_discovered_via_filtered_list(api):
    """PRD 3.5: "Second, an `Invoice` is auto-created in `ISSUED` status with
    its `claim_id` and `client_id` copied from the claim, `recovered_duty_cents`
    snapshotting `paid_duty_cents`, `fee_bps_snapshot` capturing the client's
    `contingency_fee_bps` at that instant — so a later fee renegotiation never
    reopens a settled invoice — and `fee_cents` computed per the settled tiered
    schedule of §3.7."
    PRD 2.3: "Paginated list responses carry `limit`,
    `offset`, `total_count`, and `has_more` in the `meta` object of the
    envelope."

    Design: Corner/endpoints/invoice_discovered_via_filtered_list
    """
    ctx = setup_paid_claim(approved_duty_cents=32670)

    data, meta = validate_paginated(
        api.list_invoices(ADMIN, params={"claim_id": ctx["claim"]["id"]})
    )
    assert meta["total_count"] == 1
    invoice = data[0]
    assert invoice["claim_id"] == ctx["claim"]["id"]
    assert invoice["recovered_duty_cents"] == 32670
    assert invoice["fee_bps_snapshot"] == 2500, "fee snapshot frozen at creation"


def test_records_auto_created_on_file_via_filtered_list(api):
    """PRD 3.4: "Filing also auto-creates the claim's evidentiary package: three
    `ComplianceRecord` resources with `doc_type` `ENTRY_DOCS`, `EXPORT_PROOF`,
    and `MATCHING_WORKSHEET`, each in `RETAINED` status with `retention_until`
    still null, because the three-year retention clock has not yet started."
    PRD 2.3: "Paginated list responses carry `limit`,
    `offset`, `total_count`, and `has_more` in the `meta` object of the
    envelope."

    Design: Corner/endpoints/records_auto_created_on_file_via_filtered_list
    """
    ctx = setup_draft_claim_with_line(matched_quantity=40)
    file_claim(ctx["claim"]["id"])

    data, meta = validate_paginated(
        api.list_records(COMPLIANCE, params={"claim_id": ctx["claim"]["id"]})
    )
    assert meta["total_count"] == 3
    doc_types = {rec["doc_type"] for rec in data}
    assert doc_types == {"ENTRY_DOCS", "EXPORT_PROOF", "MATCHING_WORKSHEET"}
    for rec in data:
        assert rec["status"] == "RETAINED"
        assert rec["retention_until"] is None, "unpaid claim retains indefinitely"


def test_claim_lines_filtered_by_entry(api):
    """PRD 2.3: "Paginated list responses carry `limit`,
    `offset`, `total_count`, and `has_more` in the `meta` object of the
    envelope."

    Design: Corner/endpoints/claim_lines_filtered_by_entry
    """
    ctx = setup_trade_scenario()
    entry_b = add_import_entry(ctx["client"]["id"], ctx["classification"]["id"],
                               entry_number="E200")
    claim = add_claim(ctx["client"]["id"])
    add_claim_line(claim["id"], ctx["entry"]["id"], ctx["export"]["id"],
                   matched_quantity=40)

    data, meta = validate_paginated(
        api.list_claim_lines(ANALYST, params={"import_entry_id": ctx["entry"]["id"]})
    )
    assert meta["total_count"] == 1
    assert data[0]["import_entry_id"] == ctx["entry"]["id"]

    _, meta_none = validate_paginated(
        api.list_claim_lines(ANALYST, params={"import_entry_id": entry_b["id"]})
    )
    assert meta_none["total_count"] == 0


def test_file_past_deadline_returns_deadline_error(api):
    """PRD 3.4: "When a `LicensedBroker` files the claim, four preconditions
    hold: the client must still be `ACTIVE` (`ERR_CLIENT_NOT_ACTIVE`); the claim
    must have at least one `ACTIVE` line (`ERR_INVALID_REQUEST`); the broker's
    `X-User-ID` must differ from `prepared_by_user_id`
    (`ERR_SEGREGATION_OF_DUTIES`); and the logical clock must not have passed
    the claim's `filing_deadline` (`ERR_FILING_DEADLINE_PASSED`). The deadline
    itself is statutory: five years after the earliest `entry_date` among the
    entries referenced by the claim's `ACTIVE` lines, and the comparison is
    inclusive — filing at the exact deadline second is still permitted."

    Design: Corner/errors/file_past_deadline_returns_deadline_error
    """
    ctx = setup_trade_scenario(
        entry_overrides={"entry_date": "2026-05-01T00:00:00Z"},
        export_overrides={"export_date": "2026-05-02T00:00:00Z"},
    )
    claim = add_claim(
        ctx["client"]["id"],
        period_start="2026-05-01T00:00:00Z",
        period_end="2026-05-31T00:00:00Z",
    )
    add_claim_line(claim["id"], ctx["entry"]["id"], ctx["export"]["id"],
                   matched_quantity=40)

    # One second past the deadline (entry_date 2026-05-01 + 5 years).
    set_clock("2031-05-01T00:00:01Z")
    res = api.file_claim(claim["id"], BROKER)
    validate_error(res, ApiErrorId.ERR_FILING_DEADLINE_PASSED)

    claim_after = validate_success(api.get_claim(claim["id"], ANALYST))
    assert claim_after["status"] == "DRAFT"
