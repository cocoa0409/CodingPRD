"""Late-filing penalty: provisional estimate vs final tiered assessment, the cap, and the
on-time boundary.

Queue A: dual_variant_calc (provisional vs final), combinatorial_formula (tiered+category+cap),
boundary_precision_check (submitted exactly at due).
"""
from test_helpers import (
    validate_success, validate_paginated,
    setup_submitted_statement, setup_accepted_late_statement, latest_penalty_for,
)


def test_provisional_estimate_stamped_at_submit(api):
    """PRD 3.4: "is a deliberately simple estimate: the jurisdiction's `penalty_base_fee_cents`
    plus its `penalty_daily_rate_cents` multiplied by `days_late`. It ignores the tier structure,
    the category multiplier, and the cap."

    Design: Difficulty/dual_variant_calc/late_penalty_provisional_vs_final
    """
    ctx = setup_submitted_statement(category="ELECTED", clock="2026-05-25T00:00:00Z",
                                    due_at="2026-04-15T00:00:00Z")
    pen = latest_penalty_for(ctx["filer"]["id"], statement_id=ctx["statement"]["id"])
    # base 5000 + daily 250 * 40 days = 15000, ignoring tier/category/cap.
    assert pen["provisional_amount_cents"] == 15000
    assert pen["status"] == "ACCRUING"


def test_final_assessment_differs_from_provisional_on_accept(api):
    """PRD 3.4: "A raw amount is then formed as `penalty_base_fee_cents` plus the product of the
    tier rate, `days_late`, and the filer's category multiplier, where the category multiplier is
    2.0 for `ELECTED`".
    PRD 3.4: "if `days_late` is greater than 30 but at most 90, the tier rate is
    `penalty_daily_rate_cents` multiplied by 2".

    Design: Difficulty/dual_variant_calc/late_penalty_provisional_vs_final
    """
    ctx = setup_accepted_late_statement(category="ELECTED", clock="2026-05-25T00:00:00Z",
                                        due_at="2026-04-15T00:00:00Z")
    pen = ctx["penalty"]
    # tier2 rate 500 * 40 * 2.0 + base 5000 = 45000; min(cap 50000, 45000) = 45000.
    assert pen["provisional_amount_cents"] == 15000
    assert pen["assessed_amount_cents"] == 45000
    assert pen["status"] == "ASSESSED"
    assert pen["provisional_amount_cents"] != pen["assessed_amount_cents"]


def test_tier3_category_capped_final_assessment(api):
    """PRD 3.4: "if `days_late` is greater than 90, the tier rate is `penalty_daily_rate_cents`
    multiplied by 3."
    PRD 3.4: "The raw amount is rounded half-up to whole cents, and the final assessed amount is
    the lesser of that rounded value and the jurisdiction's `penalty_cap_cents`."

    Design: Difficulty/combinatorial_formula/late_penalty_tiered_category_capped
    """
    ctx = setup_accepted_late_statement(category="ELECTED", clock="2026-09-15T00:00:00Z",
                                        due_at="2026-04-15T00:00:00Z")
    pen = ctx["penalty"]
    # 153 days late, tier3 rate 750 * 153 * 2.0 + 5000 = 234500 -> capped to 50000.
    assert pen["days_late"] == 153
    assert pen["assessed_amount_cents"] == 50000


def test_tier3_capped_penalty_drives_ledger(api, registrar_headers):
    """PRD 3.4: "the assessment increments the owning filer's `outstanding_penalty_cents` by
    `assessed_amount_cents` and recomputes `compliance_status`. If that recomputation flips the
    filer to `DELINQUENT`".

    Design: Difficulty/combinatorial_formula/late_penalty_tiered_category_capped
    """
    ctx = setup_accepted_late_statement(category="ELECTED", clock="2026-09-15T00:00:00Z",
                                        due_at="2026-04-15T00:00:00Z")
    assert ctx["penalty"]["assessed_amount_cents"] == 50000
    filer = validate_success(api.get_filer(ctx["filer"]["id"], registrar_headers), 200)
    assert filer["outstanding_penalty_cents"] == 50000
    assert filer["compliance_status"] == "DELINQUENT"


def test_submit_exactly_at_due_is_on_time(api):
    """PRD 3.3: "The statement `is_late` when `submitted_at` is strictly after `due_at_snapshot`;
    otherwise it is on time. When on time, `days_late` is 0".

    Design: Difficulty/boundary_precision_check/statement_submitted_exactly_at_due
    """
    ctx = setup_submitted_statement(category="ELECTED", clock="2026-04-15T00:00:00Z",
                                    due_at="2026-04-15T00:00:00Z")
    stmt = ctx["statement"]
    assert stmt["is_late"] is False
    assert stmt["days_late"] == 0


def test_on_time_submit_creates_no_penalty(api, ethics_officer_headers):
    """PRD 3.3: "If the submission is late, the server creates a companion **penalty** of type
    `LATE_FILING` in `ACCRUING` status linked to this statement".

    Design: Difficulty/boundary_precision_check/statement_submitted_exactly_at_due
    """
    ctx = setup_submitted_statement(category="ELECTED", clock="2026-04-15T00:00:00Z",
                                    due_at="2026-04-15T00:00:00Z")
    data, meta = validate_paginated(
        api.list_penalties(ethics_officer_headers, params={"filer_id": ctx["filer"]["id"]}))
    assert meta["total_count"] == 0
