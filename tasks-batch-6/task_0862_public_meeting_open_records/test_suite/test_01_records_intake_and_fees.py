"""Records-request intake, the copy-fee / labor-fee schedules, the estimated-vs-
assessed dual variant, the money ledger, and fee-gated closing (PRD §2.9, §3.7-§3.8)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_records_request, setup_request_under_review, setup_determined_request,
    release_document, issue_determination, assert_fee_ledger_invariant,
)


# ===========================================================================
# Dual variant: estimated (forward-looking) vs assessed (aggregation)
# ===========================================================================

def test_estimated_fee_is_forward_looking_copy_fee(api):
    """PRD §3.7: "It is computed by the copy-fee schedule applied to
    `estimated_page_count` and stored in `estimated_fee_cents`."
    PRD §3.7: "the first 450 pages (that is, pages up to a running total of 500)
    are charged 15 cents each, and every page beyond a running total of 500 is
    charged 10 cents each."

    600 pages: billable 550; tier-1 450*15=6750; tier-2 100*10=1000; total 7750.

    Design: Difficulty/dual_variant_calc/fee_estimate_vs_assessed_divergence
    """
    ctx = setup_records_request(api, estimated_page_count=600)
    assert ctx["request"]["estimated_fee_cents"] == 7750


def test_assessed_fee_diverges_from_estimate(api):
    """PRD §3.8: "The **assessed copy fee** applies the same copy-fee schedule
    described in §3.7, but over the sum of `page_count` across documents whose
    status is `RELEASED` or `REDACTED`; exempt and cancelled documents contribute
    zero pages."

    Same request: estimated 7750 over 600 declared pages, but assessed 2800 over
    two released docs (70 pages copy 300 + labor 2500) — the two numbers differ.

    Design: Difficulty/dual_variant_calc/fee_estimate_vs_assessed_divergence
    """
    ctx = setup_determined_request(api, decision="GRANTED", estimated_page_count=600,
                                   docs=[(30, 20), (40, 50)])
    req = ctx["request"]
    assert req["estimated_fee_cents"] == 7750
    assert req["assessed_fee_cents"] == 2800
    assert req["estimated_fee_cents"] != req["assessed_fee_cents"]


# ===========================================================================
# copy_fee tiered non-linear schedule
# ===========================================================================

def test_assessed_copy_fee_600_pages_tiered(api):
    """PRD §3.8: "The **assessed copy fee** applies the same copy-fee schedule
    described in §3.7, but over the sum of `page_count` across documents whose
    status is `RELEASED` or `REDACTED`; exempt and cancelled documents contribute
    zero pages."

    600 released pages, 0 review minutes: 450*15 + 100*10 = 7750; labor 0.

    Design: Difficulty/combinatorial_formula/copy_fee_tiered_nonlinear
    """
    ctx = setup_determined_request(api, decision="GRANTED", docs=[(600, 0)])
    assert ctx["request"]["assessed_fee_cents"] == 7750


def test_copy_fee_schedule_600_pages_via_estimate(api):
    """PRD §3.7: "the tier-one portion is those billable pages capped at 450; the
    tier-two portion is any billable pages beyond 450; and the copy fee in cents is
    the tier-one portion times 15 plus the tier-two portion times 10."

    The same tiered schedule over 600 declared pages yields 7750.

    Design: Difficulty/combinatorial_formula/copy_fee_tiered_nonlinear
    """
    ctx = setup_records_request(api, estimated_page_count=600)
    assert ctx["request"]["estimated_fee_cents"] == 7750


# ===========================================================================
# labor_fee: round-per-document-then-sum (pinned order)
# ===========================================================================

def test_labor_fee_round_per_document_then_sum(api):
    """PRD §3.8: "round that document's `review_minutes` up to the next whole
    15-minute increment; sum those per-document rounded minutes; subtract a free
    allowance of 30 minutes but not below 0; convert the remaining chargeable
    minutes to hours by dividing by 60; multiply by the labor rate of 2500 cents
    per hour; and round the result half-up to whole cents."

    Two docs 20 and 50 min -> ceil to 30 and 60 -> 90 - 30 free = 60 min = 1h *
    2500 = 2500; copy fee 0 (20 pages < 50 free).

    Design: Difficulty/combinatorial_formula/labor_fee_increment_rounding_order
    """
    ctx = setup_determined_request(api, decision="GRANTED", docs=[(10, 20), (10, 50)])
    assert ctx["request"]["assessed_fee_cents"] == 2500


def test_labor_fee_not_sum_then_round(api):
    """PRD §3.8: "The rounding is per-document-then-sum; summing raw minutes first
    and rounding once would give a different, incorrect result."

    Sum-then-round (70 -> 75 min = 1875) is the wrong answer; the pinned order
    gives 2500, which is observably different.

    Design: Difficulty/combinatorial_formula/labor_fee_increment_rounding_order
    """
    ctx = setup_determined_request(api, decision="GRANTED", docs=[(10, 20), (10, 50)])
    assert ctx["request"]["assessed_fee_cents"] == 2500
    assert ctx["request"]["assessed_fee_cents"] != 1875


# ===========================================================================
# copy_fee free-page allowance boundary (50 pages)
# ===========================================================================

def test_fifty_page_doc_assessed_fee_zero(api):
    """PRD §3.7: "billable pages are the page count minus 50 but not less than 0".

    A single 50-page released doc sits exactly at the free allowance: billable
    max(0, 50-50) = 0, so the assessed copy fee is 0.

    Design: Difficulty/boundary_precision_check/copy_fee_free_page_allowance_boundary
    """
    ctx = setup_determined_request(api, decision="GRANTED", docs=[(50, 0)])
    assert ctx["request"]["assessed_fee_cents"] == 0


def test_free_page_allowance_via_estimate(api):
    """PRD §3.7: "the first 50 pages are free".

    An estimate of exactly 50 pages produces an estimated copy fee of 0.

    Design: Difficulty/boundary_precision_check/copy_fee_free_page_allowance_boundary
    """
    ctx = setup_records_request(api, estimated_page_count=50)
    assert ctx["request"]["estimated_fee_cents"] == 0


# ===========================================================================
# Money-ledger conservation
# ===========================================================================

def test_ledger_conservation_after_waiver_and_payment(api):
    """PRD §2.9: "The balance is always the assessed fee minus the waiver minus
    the cumulative payments."

    Assessed 2800, waiver 800, payment 2000 -> balance 0.

    Design: Difficulty/compensating_invariant/fee_ledger_conservation_money
    """
    ctx = setup_determined_request(api, decision="GRANTED", estimated_page_count=70,
                                   docs=[(30, 20), (40, 50)], waive_fee_cents=800)
    pay = validate_success(api.pay_request(
        ctx["request"]["id"], {"amount_cents": 2000}, ctx["requester_headers"]))
    assert pay["assessed_fee_cents"] == 2800
    assert pay["amount_waived_cents"] == 800
    assert pay["amount_paid_cents"] == 2000
    assert pay["fee_balance_cents"] == 0


def test_ledger_conservation_identity_holds(api):
    """PRD §2.9: "For any determined request the conservation identity holds at all
    times: the assessed fee equals the sum of the waiver, the cumulative payments,
    and the outstanding balance."

    Design: Difficulty/compensating_invariant/fee_ledger_conservation_money
    """
    ctx = setup_determined_request(api, decision="GRANTED", estimated_page_count=70,
                                   docs=[(30, 20), (40, 50)], waive_fee_cents=800)
    pay = validate_success(api.pay_request(
        ctx["request"]["id"], {"amount_cents": 2000}, ctx["requester_headers"]))
    assert_fee_ledger_invariant(pay)


# ===========================================================================
# Corner: response deadline, waiver-exceeds-fee, close-with-balance
# ===========================================================================

def test_response_deadline_ten_business_days(api):
    """PRD §3.7: "For example, a request submitted `2026-06-01T09:00:00Z`, a
    Monday, yields a deadline of `2026-06-15T23:59:59Z`."

    Design: Corner/entities/records_request_response_deadline_business_days
    """
    from test_helpers import set_clock
    set_clock(api, "2026-06-01T09:00:00Z")
    ctx = setup_records_request(api, estimated_page_count=0)
    assert ctx["request"]["response_deadline"] == "2026-06-15T23:59:59Z"


def test_waiver_exceeding_assessed_fee_rejected(api):
    """PRD §3.8: "the waiver may not exceed the computed assessed fee, else
    `ERR_WAIVER_EXCEEDS_FEE`".

    One 51-page released doc -> assessed 15 cents; a waiver of 99999 exceeds it.

    Design: Corner/errors/waiver_exceeds_assessed_fee_rejected
    """
    ctx = setup_request_under_review(api)
    release_document(api, ctx, page_count=51, review_minutes=0)
    resp = issue_determination(api, ctx, decision="GRANTED", waive_fee_cents=99999)
    validate_error(resp, ApiErrorId.ERR_WAIVER_EXCEEDS_FEE.value)


def test_close_granted_request_with_balance_rejected(api):
    """PRD §3.8: "The officer closes a `GRANTED` or `PARTIALLY_GRANTED` request by
    advancing it to `CLOSED`, but only when `fee_balance_cents` is exactly 0; a
    positive balance blocks closing with `ERR_FEE_OUTSTANDING`".

    Design: Corner/errors/close_granted_with_balance_fee_outstanding
    """
    ctx = setup_determined_request(api, decision="GRANTED", docs=[(600, 0)])
    assert ctx["request"]["fee_balance_cents"] > 0
    resp = api.transition_records_request(
        ctx["request"]["id"], {"to_status": "CLOSED"}, ctx["officer_headers"])
    validate_error(resp, ApiErrorId.ERR_FEE_OUTSTANDING.value)
