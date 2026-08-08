"""Filing a return: per-line rounding, taxable floor, vendor discount, file guards."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    make_taxpayer_headers, make_admin_headers,
    create_active_taxpayer, register_taxpayer, create_jurisdiction,
    create_draft_return, file_return, set_clock,
    create_return_line,
)


def test_return_tax_rounds_per_line_then_sums(api):
    """PRD §3.3: "the return's `total_taxable_cents` is the sum of the per-line taxable
    amounts, and its `tax_due_cents` is the sum of the already-rounded per-line taxes;
    that is, tax is rounded per line first and only then summed, never summed and then rounded."

    Design: Difficulty/combinatorial_formula/return_tax_per_line_round_then_sum
    """
    tp = create_active_taxpayer(api)
    jur = create_jurisdiction(api, rate_bps=850)
    lines = [
        create_return_line(jur["id"], gross_sales_cents=333333),
        create_return_line(jur["id"], gross_sales_cents=333333),
    ]
    ret = create_draft_return(api, tp["id"], lines=lines,
                              period_key="2026-01",
                              period_start_date="2026-01-01T00:00:00Z",
                              period_end_date="2026-01-31T00:00:00Z",
                              filing_due_date="2026-02-20T00:00:00Z")
    filed = file_return(api, tp["id"], ret["id"])
    assert filed["tax_due_cents"] == 56666


def test_return_total_taxable_sums_per_line_bases(api):
    """PRD §3.3: "the return's `total_taxable_cents` is the sum of the per-line taxable
    amounts, and its `tax_due_cents` is the sum of the already-rounded per-line taxes;
    that is, tax is rounded per line first and only then summed, never summed and then rounded."

    Design: Difficulty/combinatorial_formula/return_tax_per_line_round_then_sum
    """
    tp = create_active_taxpayer(api)
    jur = create_jurisdiction(api, rate_bps=850)
    lines = [
        create_return_line(jur["id"], gross_sales_cents=333333),
        create_return_line(jur["id"], gross_sales_cents=333333),
    ]
    ret = create_draft_return(api, tp["id"], lines=lines,
                              period_key="2026-01",
                              period_start_date="2026-01-01T00:00:00Z",
                              period_end_date="2026-01-31T00:00:00Z",
                              filing_due_date="2026-02-20T00:00:00Z")
    filed = file_return(api, tp["id"], ret["id"])
    assert filed["total_taxable_cents"] == 666666


def test_return_taxable_floored_at_zero(api):
    """PRD §3.3: "the taxable base is the gross sales minus exempt sales minus deductions,
    floored at zero: `taxable_cents` is the larger of 0 and
    `gross_sales_cents − exempt_sales_cents − deduction_cents`."

    Design: Corner/calculations/return_taxable_floored_at_zero
    """
    tp = create_active_taxpayer(api)
    jur = create_jurisdiction(api, rate_bps=850)
    line = create_return_line(jur["id"], gross_sales_cents=100000, exempt_sales_cents=200000)
    ret = create_draft_return(api, tp["id"], lines=[line],
                              period_key="2026-01",
                              period_start_date="2026-01-01T00:00:00Z",
                              period_end_date="2026-01-31T00:00:00Z",
                              filing_due_date="2026-02-20T00:00:00Z")
    filed = file_return(api, tp["id"], ret["id"])
    assert filed["total_taxable_cents"] == 0
    assert filed["tax_due_cents"] == 0


def test_vendor_discount_on_due_date_amount(api):
    """PRD §3.3: "the `vendor_discount_cents` is one and a half percent of the tax due —
    `tax_due_cents` multiplied by 150 basis points and divided by 10000, rounded half-up —
    but never more than a cap of 100000 cents (one thousand dollars); the discount is the
    smaller of the computed amount and that cap."
    PRD §3.3: "filing on or before the due date is timely, and filing exactly on the due date qualifies."

    Design: Difficulty/boundary_precision_check/file_on_due_date_qualifies_for_vendor_discount
    """
    tp = create_active_taxpayer(api)
    jur = create_jurisdiction(api, rate_bps=850)
    line = create_return_line(jur["id"], gross_sales_cents=1000000, exempt_sales_cents=200000)
    ret = create_draft_return(api, tp["id"], lines=[line],
                              filing_due_date="2026-04-20T00:00:00Z")
    set_clock(api, "2026-04-20T00:00:00Z")
    filed = file_return(api, tp["id"], ret["id"])
    assert filed["tax_due_cents"] == 68000
    assert filed["vendor_discount_cents"] == 1020


def test_vendor_discount_on_due_date_net_due(api):
    """PRD §3.3: "In all cases the return's `net_return_due_cents` is `tax_due_cents`
    minus `vendor_discount_cents`, and this net figure is what the return contributes
    to the account balance."

    Design: Difficulty/boundary_precision_check/file_on_due_date_qualifies_for_vendor_discount
    """
    tp = create_active_taxpayer(api)
    jur = create_jurisdiction(api, rate_bps=850)
    line = create_return_line(jur["id"], gross_sales_cents=1000000, exempt_sales_cents=200000)
    ret = create_draft_return(api, tp["id"], lines=[line],
                              filing_due_date="2026-04-20T00:00:00Z")
    set_clock(api, "2026-04-20T00:00:00Z")
    filed = file_return(api, tp["id"], ret["id"])
    assert filed["net_return_due_cents"] == 66980


def test_vendor_discount_zero_when_filed_late(api):
    """PRD §3.3: "When the filing is late or the account is not active,
    `vendor_discount_cents` is zero."

    Design: Corner/calculations/vendor_discount_zero_when_filed_late
    """
    tp = create_active_taxpayer(api)
    jur = create_jurisdiction(api, rate_bps=850)
    line = create_return_line(jur["id"], gross_sales_cents=1000000, exempt_sales_cents=200000)
    ret = create_draft_return(api, tp["id"], lines=[line],
                              filing_due_date="2026-04-20T00:00:00Z")
    set_clock(api, "2026-04-21T00:00:00Z")
    filed = file_return(api, tp["id"], ret["id"])
    assert filed["vendor_discount_cents"] == 0
    assert filed["net_return_due_cents"] == 68000


def test_vendor_discount_capped(api):
    """PRD §3.3: "the `vendor_discount_cents` is one and a half percent of the tax due —
    `tax_due_cents` multiplied by 150 basis points and divided by 10000, rounded half-up —
    but never more than a cap of 100000 cents (one thousand dollars); the discount is the
    smaller of the computed amount and that cap."

    Design: Corner/calculations/vendor_discount_capped
    """
    tp = create_active_taxpayer(api)
    jur = create_jurisdiction(api, code="BIG", name="Big", rate_bps=1000)
    line = create_return_line(jur["id"], gross_sales_cents=100000000)
    ret = create_draft_return(api, tp["id"], lines=[line],
                              period_key="2026-01",
                              period_start_date="2026-01-01T00:00:00Z",
                              period_end_date="2026-01-31T00:00:00Z",
                              filing_due_date="2026-02-20T00:00:00Z")
    set_clock(api, "2026-02-20T00:00:00Z")
    filed = file_return(api, tp["id"], ret["id"])
    assert filed["tax_due_cents"] == 10000000
    assert filed["vendor_discount_cents"] == 100000
    assert filed["net_return_due_cents"] == 9900000


def test_file_already_filed_return_rejected(api):
    """PRD §3.3: "Filing transitions a return from `DRAFT` to `FILED`, and requires both
    that the return currently be in `DRAFT` (or `AMENDING`, per §3.4) — otherwise
    `ERR_RETURN_NOT_DRAFT`".

    Design: Corner/state_machines/file_already_filed_return_rejected
    """
    tp = create_active_taxpayer(api)
    jur = create_jurisdiction(api, rate_bps=850)
    ret = create_draft_return(api, tp["id"], jurisdiction_id=jur["id"])
    file_return(api, tp["id"], ret["id"])
    resp = api.file_return(ret["id"], make_taxpayer_headers(tp["id"]))
    validate_error(resp, ApiErrorId.ERR_RETURN_NOT_DRAFT, expected_status=409)


def test_file_return_blocked_when_account_pending(api):
    """PRD §3.3: "and that the owning taxpayer's `account_status` be `ACTIVE`, otherwise
    `ERR_ACCOUNT_NOT_ACTIVE`."

    Design: Corner/state_machines/file_return_blocked_when_account_pending
    """
    tp = register_taxpayer(api)  # PENDING, never activated
    jur = create_jurisdiction(api, rate_bps=850)
    ret = create_draft_return(api, tp["id"], jurisdiction_id=jur["id"])
    resp = api.file_return(ret["id"], make_taxpayer_headers(tp["id"]))
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE, expected_status=409)


def test_list_returns_filtered_by_taxpayer_is_paginated(api):
    """PRD §2.9: "List endpoints accept reverse-reachability filters — for example returns
    may be filtered by `taxpayer_id`, `exemption_certificate_id`, `status`, or `period_key`".
    PRD §2.3: "Every list response echoes `limit`, `offset`, `total_count`, and `has_more`
    inside the `meta` object."

    Design: Corner/endpoints/list_returns_filtered_by_taxpayer_paginated
    """
    tp = create_active_taxpayer(api)
    jur = create_jurisdiction(api, rate_bps=850)
    ret = create_draft_return(api, tp["id"], jurisdiction_id=jur["id"])
    resp = api.list_returns(make_admin_headers(), params={"taxpayer_id": tp["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert any(r["id"] == ret["id"] for r in data)
    assert all(r["taxpayer_id"] == tp["id"] for r in data)
