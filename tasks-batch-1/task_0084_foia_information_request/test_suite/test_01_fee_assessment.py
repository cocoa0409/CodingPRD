"""Tiered fee assessment, free allotments, rounding order, waiver scoring, and balance.

Difficulty queue: dual_variant_calc, combinatorial_formula, boundary_precision (fee/waiver),
compensating_invariant (balance). Corner queue: calculations + consistency_model + the
outstanding-balance computed field.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, fixtures,
)


# ─────────────────────────────────────────────────────
# Difficulty/dual_variant_calc/fee_assessment_commercial_vs_other_tier
# ─────────────────────────────────────────────────────
def test_fee_commercial_vs_other_same_inputs_diverge(api):
    """PRD §3.4: "For a `COMMERCIAL` request, all three components apply with no free
    allotment, and the assessed fee is the sum of the rounded search, review, and
    duplication components."
    PRD §3.4: "For an `OTHER` (public, individual, or non-commercial) request, there is
    no review charge; the first 2 hours of search time are free and the first 100 pages
    are free."

    search 5h = 20 qh * 1000 = 20000; review 0; dup 300 pages * 10 = 3000;
    COMMERCIAL = 20000 + 0 + 3000 = 23000 (PRD-derived). OTHER frees the first 8 qh and
    the first 100 pages: 12 qh * 1000 + 200 pages * 10 = 12000 + 2000 = 14000.

    Design: Difficulty/dual_variant_calc/fee_assessment_commercial_vs_other_tier
    """
    # COMMERCIAL request
    ctx_c = fixtures.create_processing_request(fee_category="COMMERCIAL")
    fee_c = validate_success(api.create_fee_estimate(
        ctx_c["request"]["id"],
        {"search_hours": 5, "review_hours": 0, "billable_pages": 300,
         "expected_request_version": fixtures.current_version(ctx_c["officer_headers"], ctx_c["request"]["id"])},
        ctx_c["officer_headers"],
    ))
    assert fee_c["assessed_fee_cents"] == 23000, fee_c

    # OTHER request, identical inputs
    ctx_o = fixtures.create_processing_request(fee_category="OTHER")
    fee_o = validate_success(api.create_fee_estimate(
        ctx_o["request"]["id"],
        {"search_hours": 5, "review_hours": 0, "billable_pages": 300,
         "expected_request_version": fixtures.current_version(ctx_o["officer_headers"], ctx_o["request"]["id"])},
        ctx_o["officer_headers"],
    ))
    assert fee_o["assessed_fee_cents"] == 14000, fee_o
    assert fee_c["assessed_fee_cents"] != fee_o["assessed_fee_cents"]


def test_fee_other_tier_full_assessment_value(api):
    """PRD §3.4: "For an `OTHER` (public, individual, or non-commercial) request, there is
    no review charge; the first 2 hours of search time are free and the first 100 pages
    are free."

    Design: Difficulty/dual_variant_calc/fee_assessment_commercial_vs_other_tier
    """
    ctx = fixtures.create_processing_request(fee_category="OTHER")
    v0 = fixtures.current_version(ctx["officer_headers"], ctx["request"]["id"])
    fee = validate_success(api.create_fee_estimate(
        ctx["request"]["id"],
        {"search_hours": 5, "review_hours": 0, "billable_pages": 300, "expected_request_version": v0},
        ctx["officer_headers"],
    ))
    # 5h = 20qh; free 8qh => 12qh*1000 = 12000; pages 300-100=200*10 = 2000; total 14000.
    assert fee["assessed_fee_cents"] == 14000, fee


# ─────────────────────────────────────────────────────
# Difficulty/dual_variant_calc/waiver_score_vs_commercial_auto_fail
# ─────────────────────────────────────────────────────
def test_waiver_score_70_grants_on_other(api):
    """PRD §3.4: "The score is 100 multiplied by the weighted sum of the four findings,
    rounded half up to an integer in the range 0 through 100. The waiver is granted when
    the score is at least 70 (the threshold is inclusive)."

    Design: Difficulty/dual_variant_calc/waiver_score_vs_commercial_auto_fail
    """
    ctx = fixtures.create_processing_request(
        fee_category="OTHER", declared_category="NEWS_MEDIA",
        request_overrides={"fee_waiver_requested": True},
    )
    v0 = fixtures.current_version(ctx["officer_headers"], ctx["request"]["id"])
    # 0.40 + 0.30 = 0.70 -> score 70 -> granted
    updated = validate_success(api.adjudicate_fee_waiver(
        ctx["request"]["id"],
        {"f_public_understanding": True, "f_not_commercial_interest": True,
         "f_meaningful_contribution": False, "f_ability_to_disseminate": False,
         "expected_request_version": v0},
        ctx["officer_headers"],
    ))
    assert updated["fee_waiver_granted"] is True, updated


def test_waiver_commercial_auto_fail_rejected(api):
    """PRD §3.4: "A commercial requester is statutorily ineligible: when the request's
    `fee_category` is `COMMERCIAL`, the waiver cannot be granted regardless of score, and
    the attempt is rejected with `ERR_WAIVER_INELIGIBLE_COMMERCIAL`."

    Design: Difficulty/dual_variant_calc/waiver_score_vs_commercial_auto_fail
    """
    ctx = fixtures.create_processing_request(
        fee_category="COMMERCIAL", request_overrides={"fee_waiver_requested": True},
    )
    v0 = fixtures.current_version(ctx["officer_headers"], ctx["request"]["id"])
    resp = api.adjudicate_fee_waiver(
        ctx["request"]["id"],
        {"f_public_understanding": True, "f_not_commercial_interest": True,
         "f_meaningful_contribution": False, "f_ability_to_disseminate": False,
         "expected_request_version": v0},
        ctx["officer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_WAIVER_INELIGIBLE_COMMERCIAL.value)


# ─────────────────────────────────────────────────────
# Difficulty/combinatorial_formula/fee_other_tier_nested_max_branch_mode_a
# ─────────────────────────────────────────────────────
def test_fee_other_tier_nested_max_branches(api):
    """PRD §3.4: "The free search allotment is 2 hours expressed as quarter-hours (2
    multiplied by 4); the chargeable search quarter-hours are the total search quarter-hours
    less that free allotment, never below zero, and the search component is those chargeable
    quarter-hours multiplied by 1000 cents per quarter-hour, rounded half up. The chargeable
    pages are the billable pages less 100, never below zero, and the duplication component is
    those pages multiplied by 10 cents per page, rounded half up."

    Design: Difficulty/combinatorial_formula/fee_other_tier_nested_max_branch_mode_a
    """
    ctx = fixtures.create_processing_request(fee_category="OTHER")
    v0 = fixtures.current_version(ctx["officer_headers"], ctx["request"]["id"])
    fee = validate_success(api.create_fee_estimate(
        ctx["request"]["id"],
        {"search_hours": 5, "review_hours": 0, "billable_pages": 300, "expected_request_version": v0},
        ctx["officer_headers"],
    ))
    assert fee["assessed_fee_cents"] == 14000, fee
    assert fee["requires_advance_payment"] is False, fee  # 14000 <= 25000


def test_fee_other_tier_zero_when_under_allotments(api):
    """PRD §3.4: "the first 2 hours of search time are free and the first 100 pages are free."

    Design: Difficulty/combinatorial_formula/fee_other_tier_nested_max_branch_mode_a
    """
    ctx = fixtures.create_processing_request(fee_category="OTHER")
    v0 = fixtures.current_version(ctx["officer_headers"], ctx["request"]["id"])
    fee = validate_success(api.create_fee_estimate(
        ctx["request"]["id"],
        {"search_hours": 2, "review_hours": 0, "billable_pages": 100, "expected_request_version": v0},
        ctx["officer_headers"],
    ))
    # 2h = 8qh, free 8qh -> 0; 100 pages all free -> 0
    assert fee["assessed_fee_cents"] == 0, fee


# ─────────────────────────────────────────────────────
# Difficulty/combinatorial_formula/fee_rounding_order_per_component_then_sum_mode_b
# ─────────────────────────────────────────────────────
def test_fee_rounding_per_component_then_sum(api):
    """PRD §2.7: "The fee calculation is composed of separately computed components (search
    cost, review cost, and duplication cost); each component is rounded to whole cents first,
    and only then are the rounded components summed. This round-per-component-then-sum
    ordering is mandatory and is not interchangeable with summing first and rounding once."
    PRD §3.4: "Search time is billed per quarter-hour: the search hours are multiplied by four
    and rounded up to a whole number of quarter-hours, and review time is converted the same way."

    Design: Difficulty/combinatorial_formula/fee_rounding_order_per_component_then_sum_mode_b
    """
    ctx = fixtures.create_processing_request(fee_category="COMMERCIAL")
    v0 = fixtures.current_version(ctx["officer_headers"], ctx["request"]["id"])
    fee = validate_success(api.create_fee_estimate(
        ctx["request"]["id"],
        {"search_hours": 0.3, "review_hours": 0.1, "billable_pages": 5, "expected_request_version": v0},
        ctx["officer_headers"],
    ))
    # ceil(0.3*4)=2 -> 2000; ceil(0.1*4)=1 -> 1000; 5 pages -> 50; sum 3050
    assert fee["assessed_fee_cents"] == 3050, fee


def test_fee_commercial_includes_review_component(api):
    """PRD §3.4: "the review component is the review quarter-hours multiplied by the review
    rate of 1000 cents per quarter-hour".

    Design: Difficulty/combinatorial_formula/fee_rounding_order_per_component_then_sum_mode_b
    """
    ctx = fixtures.create_processing_request(fee_category="COMMERCIAL")
    v0 = fixtures.current_version(ctx["officer_headers"], ctx["request"]["id"])
    fee = validate_success(api.create_fee_estimate(
        ctx["request"]["id"],
        {"search_hours": 0, "review_hours": 1, "billable_pages": 0, "expected_request_version": v0},
        ctx["officer_headers"],
    ))
    # review 1h = 4qh * 1000 = 4000
    assert fee["assessed_fee_cents"] == 4000, fee


# ─────────────────────────────────────────────────────
# Difficulty/boundary_precision_check/advance_payment_threshold_gt_not_gte
# ─────────────────────────────────────────────────────
def test_advance_payment_threshold_exactly_25000_no_toll(api):
    """PRD §3.4: "the system marks the estimate as requiring advance payment exactly when
    the assessed fee is strictly greater than the advance-payment threshold of 25000 cents
    (250 dollars)."
    PRD §3.4: "If instead the estimate is at or below the threshold, or a waiver was granted,
    the request stays in `PROCESSING`, the deadline dimension is unchanged, and no tolling occurs"

    Design: Difficulty/boundary_precision_check/advance_payment_threshold_gt_not_gte
    """
    ctx = fixtures.create_processing_request(fee_category="COMMERCIAL")
    v0 = fixtures.current_version(ctx["officer_headers"], ctx["request"]["id"])
    fee = validate_success(api.create_fee_estimate(
        ctx["request"]["id"],
        {"search_hours": 6.25, "review_hours": 0, "billable_pages": 0, "expected_request_version": v0},
        ctx["officer_headers"],
    ))
    # 6.25h = 25qh * 1000 = 25000 exactly
    assert fee["assessed_fee_cents"] == 25000, fee
    assert fee["requires_advance_payment"] is False, fee  # 25000 NOT > 25000
    req = validate_success(api.get_request(ctx["request"]["id"], ctx["officer_headers"]))
    assert req["status"] == "PROCESSING", req


def test_advance_payment_threshold_above_25000_tolls(api):
    """PRD §3.4: "If the resulting estimate requires advance payment — its
    `requires_advance_payment` is true — and no waiver was granted, the request moves from
    `PROCESSING` to `AWAITING_PAYMENT`, the deadline dimension becomes `TOLLED`".

    Design: Difficulty/boundary_precision_check/advance_payment_threshold_gt_not_gte
    """
    ctx = fixtures.create_processing_request(fee_category="COMMERCIAL")
    v0 = fixtures.current_version(ctx["officer_headers"], ctx["request"]["id"])
    fee = validate_success(api.create_fee_estimate(
        ctx["request"]["id"],
        # 6.5h search = 26qh -> 26000 > 25000
        {"search_hours": 6.5, "review_hours": 0, "billable_pages": 0, "expected_request_version": v0},
        ctx["officer_headers"],
    ))
    assert fee["assessed_fee_cents"] == 26000, fee
    assert fee["requires_advance_payment"] is True, fee
    req = validate_success(api.get_request(ctx["request"]["id"], ctx["officer_headers"]))
    assert req["status"] == "AWAITING_PAYMENT", req
    assert req["deadline_status"] == "TOLLED", req


# ─────────────────────────────────────────────────────
# Difficulty/boundary_precision_check/waiver_score_threshold_gte_boundary
# ─────────────────────────────────────────────────────
def test_waiver_score_exactly_70_granted(api):
    """PRD §3.4: "The waiver is granted when the score is at least 70 (the threshold is
    inclusive)."

    Design: Difficulty/boundary_precision_check/waiver_score_threshold_gte_boundary
    """
    ctx = fixtures.create_processing_request(
        fee_category="OTHER", declared_category="NEWS_MEDIA",
        request_overrides={"fee_waiver_requested": True},
    )
    v0 = fixtures.current_version(ctx["officer_headers"], ctx["request"]["id"])
    updated = validate_success(api.adjudicate_fee_waiver(
        ctx["request"]["id"],
        {"f_public_understanding": True, "f_not_commercial_interest": True,
         "f_meaningful_contribution": False, "f_ability_to_disseminate": False,
         "expected_request_version": v0},
        ctx["officer_headers"],
    ))
    assert updated["fee_waiver_granted"] is True, updated  # score 70 >= 70


def test_waiver_score_below_70_denied(api):
    """PRD §3.4: "Each finding contributes its weight when true and nothing when false; the
    weights are 0.40 for public understanding, 0.30 for non-commercial interest, 0.20 for
    meaningful contribution, and 0.10 for ability to disseminate."

    Design: Difficulty/boundary_precision_check/waiver_score_threshold_gte_boundary
    """
    ctx = fixtures.create_processing_request(
        fee_category="OTHER", declared_category="NEWS_MEDIA",
        request_overrides={"fee_waiver_requested": True},
    )
    v0 = fixtures.current_version(ctx["officer_headers"], ctx["request"]["id"])
    # 0.40 + 0.20 = 0.60 -> score 60 < 70 -> not granted
    updated = validate_success(api.adjudicate_fee_waiver(
        ctx["request"]["id"],
        {"f_public_understanding": True, "f_not_commercial_interest": False,
         "f_meaningful_contribution": True, "f_ability_to_disseminate": False,
         "expected_request_version": v0},
        ctx["officer_headers"],
    ))
    assert updated["fee_waiver_granted"] is False, updated


# ─────────────────────────────────────────────────────
# Difficulty/compensating_invariant/payment_resume_conserves_outstanding_balance
# ─────────────────────────────────────────────────────
def test_payment_conserves_outstanding_balance(api):
    """PRD §3.4: "A valid payment requires the request to be in `AWAITING_PAYMENT` with a
    `fee_payment_status` of `DUE`; it sets `fee_payment_status` to `PAID`, returns the
    request to `PROCESSING`, recomputes the requester's `outstanding_balance_cents`".
    PRD §3.4: "A requester's `outstanding_balance_cents` is the exact sum, with no rounding,
    of the assessed fee of the current fee estimate of each of that requester's requests
    whose `fee_payment_status` is `DUE`. Requests whose payment status is `PAID`, `WAIVED`,
    or `NONE` contribute nothing to the sum."

    Design: Difficulty/compensating_invariant/payment_resume_conserves_outstanding_balance
    """
    ctx = fixtures.setup_awaiting_payment(
        declared_category="COMMERCIAL", fee_category="COMMERCIAL",
        search_hours=6, review_hours=4, billable_pages=500,
    )
    # 6h=24qh*1000=24000; 4h=16qh*1000=16000; 500 pages*10=5000 -> 45000
    assert ctx["fee_estimate"]["assessed_fee_cents"] == 45000, ctx["fee_estimate"]
    # Balance is 45000 while DUE
    bal_due = validate_success(api.get_requester(ctx["requester"]["id"], ctx["officer_headers"]))
    assert bal_due["outstanding_balance_cents"] == 45000, bal_due

    paid = fixtures.pay_request(ctx["requester_headers"], ctx["request"]["id"], 45000)
    assert paid["fee_payment_status"] == "PAID", paid
    assert paid["status"] == "PROCESSING", paid
    bal_after = validate_success(api.get_requester(ctx["requester"]["id"], ctx["officer_headers"]))
    assert bal_after["outstanding_balance_cents"] == 0, bal_after


def test_payment_sets_paid_and_resumes(api):
    """PRD §3.4: "it sets `fee_payment_status` to `PAID`, returns the request to `PROCESSING`,
    recomputes the requester's `outstanding_balance_cents`, sets the deadline dimension back
    to `RUNNING`".

    Design: Difficulty/compensating_invariant/payment_resume_conserves_outstanding_balance
    """
    ctx = fixtures.setup_awaiting_payment(
        declared_category="COMMERCIAL", fee_category="COMMERCIAL",
        search_hours=6, review_hours=4, billable_pages=500,
    )
    paid = fixtures.pay_request(ctx["requester_headers"], ctx["request"]["id"], 45000)
    assert paid["fee_payment_status"] == "PAID", paid
    assert paid["deadline_status"] == "RUNNING", paid


# ─────────────────────────────────────────────────────
# Corner/calculations/educational_first_100_pages_free_boundary
# ─────────────────────────────────────────────────────
def test_educational_first_100_pages_free(api):
    """PRD §3.4: "For an `EDUCATIONAL` or `NEWS_MEDIA` request, only duplication is charged:
    there is no search or review charge, and the first 100 pages are free. The chargeable
    pages are the billable pages less 100, but never below zero, and the assessed fee is
    those chargeable pages multiplied by 10 cents per page, rounded half up."

    Design: Corner/calculations/educational_first_100_pages_free_boundary
    """
    ctx = fixtures.create_processing_request(fee_category="EDUCATIONAL", declared_category="EDUCATIONAL")
    v0 = fixtures.current_version(ctx["officer_headers"], ctx["request"]["id"])
    fee = validate_success(api.create_fee_estimate(
        ctx["request"]["id"],
        {"search_hours": 10, "review_hours": 5, "billable_pages": 250, "expected_request_version": v0},
        ctx["officer_headers"],
    ))
    # (250-100)*10 = 1500; search/review ignored
    assert fee["assessed_fee_cents"] == 1500, fee


# ─────────────────────────────────────────────────────
# Corner/calculations/news_media_pages_at_free_allotment_zero_fee
# ─────────────────────────────────────────────────────
def test_news_media_pages_at_free_allotment_zero_fee(api):
    """PRD §3.4: "For an `EDUCATIONAL` or `NEWS_MEDIA` request, only duplication is charged:
    there is no search or review charge, and the first 100 pages are free. The chargeable
    pages are the billable pages less 100, but never below zero".

    Design: Corner/calculations/news_media_pages_at_free_allotment_zero_fee
    """
    ctx = fixtures.create_processing_request(fee_category="NEWS_MEDIA", declared_category="NEWS_MEDIA")
    v0 = fixtures.current_version(ctx["officer_headers"], ctx["request"]["id"])
    fee = validate_success(api.create_fee_estimate(
        ctx["request"]["id"],
        {"search_hours": 3, "review_hours": 0, "billable_pages": 100, "expected_request_version": v0},
        ctx["officer_headers"],
    ))
    # max(0, 100-100) = 0
    assert fee["assessed_fee_cents"] == 0, fee


# ─────────────────────────────────────────────────────
# Corner/calculations/waiver_granted_zeroes_fee
# ─────────────────────────────────────────────────────
def test_waiver_granted_zeroes_fee_and_sets_waived(api):
    """PRD §3.4: "If the request's fee waiver has been granted, the assessed fee is forced to
    0 regardless of the tiered computation."
    PRD §3.4: "A waived estimate sets the request's `fee_payment_status` to `WAIVED`".

    Design: Corner/calculations/waiver_granted_zeroes_fee
    """
    ctx = fixtures.create_processing_request(
        fee_category="OTHER", request_overrides={"fee_waiver_requested": True},
    )
    fixtures.grant_fee_waiver(ctx["officer_headers"], ctx["request"]["id"], findings=(1, 1, 1, 1))
    v1 = fixtures.current_version(ctx["officer_headers"], ctx["request"]["id"])
    fee = validate_success(api.create_fee_estimate(
        ctx["request"]["id"],
        {"search_hours": 5, "review_hours": 0, "billable_pages": 300, "expected_request_version": v1},
        ctx["officer_headers"],
    ))
    assert fee["assessed_fee_cents"] == 0, fee
    req = validate_success(api.get_request(ctx["request"]["id"], ctx["officer_headers"]))
    assert req["fee_payment_status"] == "WAIVED", req


# ─────────────────────────────────────────────────────
# Corner/calculations/tolled_working_days_extend_effective_due
# ─────────────────────────────────────────────────────
def test_tolled_working_days_extend_effective_due(api):
    """PRD §3.4: "closes the advance-payment tolling window by adding the working days that
    elapsed during it to the deadline's `tolled_working_days`".
    PRD §3.5: "The operative deadline is the base deadline advanced by the extension days
    plus the tolled working days, all counted in working days."

    Design: Corner/calculations/tolled_working_days_extend_effective_due
    """
    officer, off_h = fixtures.create_officer()
    fixtures.set_clock(off_h, "2026-01-12T00:00:00.000Z")
    requester, req_h = fixtures.create_requester(off_h, declared_category="COMMERCIAL")
    request = fixtures.submit_request(off_h, requester, received_at="2026-01-05T00:00:00.000Z")
    fixtures.perfect_request(off_h, request["id"], fee_category="COMMERCIAL")
    fixtures.assign_request(off_h, request["id"])
    fixtures.assess_fee(off_h, request["id"], search_hours=6, review_hours=4, billable_pages=500)  # 45000 -> toll
    fixtures.set_clock(off_h, "2026-01-19T00:00:00.000Z")
    fixtures.pay_request(req_h, request["id"], 45000)

    deadline = validate_success(api.get_deadline(request["id"], off_h))
    if isinstance(deadline, list):
        deadline = deadline[0]
    assert deadline["tolled_working_days"] >= 1, deadline
    assert deadline["effective_due_at"] >= deadline["base_due_at"], deadline
    req = validate_success(api.get_request(request["id"], off_h))
    assert req["deadline_status"] == "RUNNING", req


# ─────────────────────────────────────────────────────
# Corner/entities/requester_outstanding_balance_computed_field
# ─────────────────────────────────────────────────────
def test_requester_outstanding_balance_computed_field(api):
    """PRD §3.4: "A requester's `outstanding_balance_cents` is the exact sum, with no
    rounding, of the assessed fee of the current fee estimate of each of that requester's
    requests whose `fee_payment_status` is `DUE`."

    Design: Corner/entities/requester_outstanding_balance_computed_field
    """
    ctx = fixtures.create_processing_request(fee_category="NEWS_MEDIA", declared_category="NEWS_MEDIA")
    v0 = fixtures.current_version(ctx["officer_headers"], ctx["request"]["id"])
    fee = validate_success(api.create_fee_estimate(
        ctx["request"]["id"],
        {"search_hours": 0, "review_hours": 0, "billable_pages": 150, "expected_request_version": v0},
        ctx["officer_headers"],
    ))
    assert fee["assessed_fee_cents"] == 500, fee  # (150-100)*10 = 500, DUE (sub-threshold)
    requester = validate_success(api.get_requester(ctx["requester"]["id"], ctx["officer_headers"]))
    assert requester["outstanding_balance_cents"] == 500, requester


# ─────────────────────────────────────────────────────
# Corner/consistency_model/fee_estimate_visible_in_same_response
# ─────────────────────────────────────────────────────
def test_fee_estimate_immediate_consistency(api):
    """PRD §3.4: "Recording the estimate runs the tiered fee calculation, sets the estimate's
    `assessed_fee_cents`".
    PRD §3.4: "A single current fee estimate is maintained per request; recording a new
    estimate replaces the prior one."

    Design: Corner/consistency_model/fee_estimate_visible_in_same_response
    """
    ctx = fixtures.create_processing_request(fee_category="OTHER")
    v0 = fixtures.current_version(ctx["officer_headers"], ctx["request"]["id"])
    fee_inline = validate_success(api.create_fee_estimate(
        ctx["request"]["id"],
        {"search_hours": 5, "review_hours": 0, "billable_pages": 300, "expected_request_version": v0},
        ctx["officer_headers"],
    ))
    assert fee_inline["assessed_fee_cents"] == 14000, fee_inline

    fetched = validate_success(api.get_fee_estimate(ctx["request"]["id"], ctx["officer_headers"]))
    if isinstance(fetched, list):
        assert len(fetched) >= 1, fetched
        assert fetched[0]["assessed_fee_cents"] == 14000, fetched
    else:
        assert fetched["assessed_fee_cents"] == 14000, fetched
