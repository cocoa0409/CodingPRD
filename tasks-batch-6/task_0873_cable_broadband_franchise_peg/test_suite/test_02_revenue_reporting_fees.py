"""Revenue reporting, the per-line-rounded fee, and audit re-statement of it."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    assert_revenue_report,
    TEST_USERS, make_operator_headers,
    create_revenue_report_payload,
)
from test_helpers import (
    create_active_franchise, create_filed_report, create_accepted_report,
    create_paid_report, set_clock, open_audit, finalize_finding,
)

AUTHORITY = TEST_USERS["authority_headers"]


# ---- Difficulty: franchise_fee_round_per_line_then_sum_mode_b ----
def test_fee_due_round_per_line_then_sum(api):
    """PRD 3.4: "the residential gross times the fee rate, rounded half up to a
    whole cent; the commercial gross times the fee rate, rounded half up; the
    advertising gross times the fee rate, rounded half up; and then the three
    rounded amounts are added to yield `fee_due_cents`."
    PRD 3.4: "Each line is rounded before the sum — the total is never produced
    by summing the raw products and rounding once."

    Design: Difficulty/combinatorial_formula/franchise_fee_round_per_line_then_sum_mode_b
    """
    fr = create_active_franchise(api)
    op = make_operator_headers(fr["id"])
    payload = create_revenue_report_payload(
        fr["id"], residential_gross_cents=100010,
        commercial_gross_cents=50010, advertising_gross_cents=33330,
    )
    data = validate_success(api.create_revenue_report(payload, op), 201)
    assert_revenue_report(data)
    # 5001 + 2501 + 1667 = 9169 (per-line), not 9168 (sum-then-round).
    assert data["fee_due_cents"] == 9169


def test_report_opens_filed_with_as_filed_basis(api):
    """PRD 3.4: "On filing, the system computes `fee_due_cents` from the reported
    grosses and the franchise's `fee_rate_pct`, sets `fee_basis` to `AS_FILED`,
    and opens the report at `status` `FILED` with `amount_paid_cents` 0."

    Design: Difficulty/combinatorial_formula/franchise_fee_round_per_line_then_sum_mode_b
    """
    fr = create_active_franchise(api)
    rr = create_filed_report(api, fr["id"])
    data = validate_success(api.get_revenue_report(rr["id"], AUTHORITY), 200)
    assert data["status"] == "FILED"
    assert data["fee_basis"] == "AS_FILED"
    assert data["fee_due_cents"] == 9169
    assert data["amount_paid_cents"] == 0


# ---- Difficulty: fee_as_filed_vs_as_audited_divergence ----
def test_fee_recomputed_as_audited_after_finding(api):
    """PRD 3.5 (Hop 2): "The target report advances from `UNDER_AUDIT` to
    `ADJUSTED`, its `fee_basis` becomes `AS_AUDITED`, and its `fee_due_cents` is
    recomputed from the audited grosses (the same per-line-rounded-then-summed
    formula, now over the audited figures)."

    Design: Difficulty/dual_variant_calc/fee_as_filed_vs_as_audited_divergence
    """
    fr = create_active_franchise(api)
    rr = create_paid_report(api, fr["id"])
    set_clock(api, "2026-07-09T00:00:00Z")
    au = open_audit(api, fr["id"], rr["id"])
    finalize_finding(api, au["id"], audited=(120010, 50010, 33330))

    data = validate_success(api.get_revenue_report(rr["id"], AUTHORITY), 200)
    # Audited fee: 6001 + 2501 + 1667 = 10169.
    assert data["fee_due_cents"] == 10169
    assert data["fee_basis"] == "AS_AUDITED"
    assert data["status"] == "ADJUSTED"


def test_fee_as_filed_differs_from_as_audited(api):
    """PRD 3.5 (Hop 2): "The audited fee differs from the filed fee precisely
    when the audited gross differs from the reported gross."

    Design: Difficulty/dual_variant_calc/fee_as_filed_vs_as_audited_divergence
    """
    fr = create_active_franchise(api)
    rr = create_accepted_report(api, fr["id"])
    assert rr["fee_due_cents"] == 9169  # as-filed value
    op = make_operator_headers(fr["id"])
    validate_success(api.pay_revenue_report(rr["id"], {"amount_cents": 9169}, op), 200)
    set_clock(api, "2026-07-09T00:00:00Z")
    au = open_audit(api, fr["id"], rr["id"])
    finalize_finding(api, au["id"], audited=(120010, 50010, 33330))

    adjusted = validate_success(api.get_revenue_report(rr["id"], AUTHORITY), 200)
    assert adjusted["fee_due_cents"] == 10169
    assert adjusted["fee_due_cents"] != 9169


# ---- Corner: validations / endpoints ----
def test_revenue_report_period_end_before_start_returns_error(api):
    """PRD 2.8: "a `period_end_date` earlier than `period_start_date`, a
    `window_end` at or before `window_start`, or a `term_end_date` at or before
    `term_start_date` yields `ERR_VALIDATION_PERIOD_INVALID` (400)."

    Design: Corner/validations/revenue_report_period_end_before_start_returns_error
    """
    fr = create_active_franchise(api)
    op = make_operator_headers(fr["id"])
    payload = create_revenue_report_payload(
        fr["id"], period_start_date="2026-03-31", period_end_date="2026-01-01",
        residential_gross_cents=1000, commercial_gross_cents=0, advertising_gross_cents=0,
    )
    resp = api.create_revenue_report(payload, op)
    validate_error(resp, ApiErrorId.ERR_VALIDATION_PERIOD_INVALID.value, 400)


def test_pay_wrong_amount_returns_fiscal_mismatch(api):
    """PRD 3.4: "the operator pays the outstanding fee by supplying
    `amount_cents`, which must equal exactly the report's outstanding balance —
    its `fee_due_cents` minus its `amount_paid_cents`. A mismatch is rejected
    with `ERR_PAYMENT_AMOUNT_MISMATCH`."

    Design: Corner/validations/revenue_report_pay_wrong_amount_fiscal_mismatch
    """
    fr = create_active_franchise(api)
    rr = create_accepted_report(api, fr["id"])
    op = make_operator_headers(fr["id"])
    resp = api.pay_revenue_report(rr["id"], {"amount_cents": 9000}, op)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH.value, 402)


def test_list_revenue_reports_by_franchise_paginated(api):
    """PRD 2.9: "each list endpoint accepts optional filters that select records
    by their foreign keys."
    PRD 2.3: "`total_count` (the total number of records matching the query
    before pagination), and `has_more` (true when records remain beyond the
    current page)."

    Design: Corner/endpoints/list_revenue_reports_by_franchise_paginated
    """
    fr = create_active_franchise(api)
    create_filed_report(api, fr["id"], period_start_date="2026-01-01",
                        period_end_date="2026-03-31", residential_gross_cents=100000,
                        commercial_gross_cents=0, advertising_gross_cents=0)
    create_filed_report(api, fr["id"], period_start_date="2026-04-01",
                        period_end_date="2026-06-30", residential_gross_cents=110000,
                        commercial_gross_cents=0, advertising_gross_cents=0)

    resp = api.list_revenue_reports(AUTHORITY, params={"franchise_id": fr["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1
