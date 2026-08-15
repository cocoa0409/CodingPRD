"""Warranty proration dual variant: LINEAR_PRORATION vs DECLINING_BALANCE
(PRD §3.9)."""
from test_helpers import (
    AFTER_PRESS_WINDOW,
    INSIDE_PRESS_WINDOW,
    TEST_USERS,
    api_client,
    assert_warranty_claim,
    file_shot_report,
    file_warranty_claim,
    set_clock,
    setup_tool_in_production,
    validate_success,
)

QM = TEST_USERS["quality_manager_headers"]


def _tool_at_100k_shots(company_name, part_number, warranty_terms, machine_id,
                        press_id, tracking_number, machine_window=None,
                        press_window=None, submit_clock=INSIDE_PRESS_WINDOW,
                        after_window_clock=AFTER_PRESS_WINDOW,
                        report_period_end="2026-08-20T00:00:00Z"):
    """Tool IN_PRODUCTION with lifetime_shots driven to exactly 100,000
    (500 tryout shots + one 99,500-shot report).

    The window/clock parameters let a test run a second full scenario after
    the first has advanced the logical clock: PRD §2.4 forbids moving the
    clock backward and PRD §2.9 requires every reservation start at or after
    the current logical time, so the second scenario's windows must be later.
    """
    ctx = setup_tool_in_production(
        company_name=company_name,
        part_number=part_number,
        warranty_terms=warranty_terms,
        machine_id=machine_id,
        press_id=press_id,
        tracking_number=tracking_number,
        machine_window=machine_window,
        press_window=press_window,
        submit_clock=submit_clock,
    )
    set_clock(after_window_clock)
    file_shot_report(
        ctx["tool"]["id"], ctx["customer"]["id"],
        report_period_end=report_period_end, shots_in_period=99_500,
    )
    return ctx


def _approve_claim(ctx, estimated_cost=500_000):
    res = file_warranty_claim(
        ctx["tool"]["id"], ctx["customer"]["id"],
        estimated_repair_cost_cents=estimated_cost,
    )
    claim = validate_success(res, 201)
    return validate_success(
        api_client.review_warranty_claim(claim["id"], {"decision": "APPROVE"}, QM),
        200,
    )


def test_linear_proration_credit_at_partial_shot_life(api):
    """PRD §3.9: "The credit calculation first caps the repair base at the
    contract snapshot: the base is the smaller of `estimated_repair_cost_cents`
    and the tool's `contract_snapshot_cents`."
    PRD §3.9: "Under `LINEAR_PRORATION`, the credit is the repair base
    multiplied by the fraction of shot life remaining — the shot limit minus
    the claim's shot-count snapshot, floored at zero, divided by the shot
    limit — rounded half-up to integer cents at the final step."
    PRD §3.9: "Filing snapshots `claimed_at_shot_count` from the tool's
    current `lifetime_shots`."

    Design: Difficulty/dual_variant_calc/warranty_linear_vs_declining_balance_divergence
    """
    ctx = _tool_at_100k_shots("Cust A", "PN-3001", "LINEAR_PRORATION",
                              "CNC_1", "PRESS_500T", "TRK-A")
    claim = _approve_claim(ctx)

    assert_warranty_claim(claim)
    assert claim["claimed_at_shot_count"] == 100_000
    # base = min(500,000, 10,500,000); credit = 500,000 * (250,000-100,000)/250,000.
    assert claim["approved_credit_cents"] == 300_000, (
        f"LINEAR_PRORATION credit mismatch: {claim['approved_credit_cents']}"
    )
    assert ctx["tool"]["warranty_terms"] == "LINEAR_PRORATION"


def test_declining_balance_credit_is_strictly_smaller(api):
    """PRD §3.9: "Under `DECLINING_BALANCE`, the credit is the repair base
    multiplied by the square of that same remaining-life fraction, again
    rounded half-up at the final step. Identical inputs therefore yield a
    strictly smaller credit than linear proration whenever the snapshot lies
    strictly between zero shots and the limit."

    Design: Difficulty/dual_variant_calc/warranty_linear_vs_declining_balance_divergence
    """
    ctx_linear = _tool_at_100k_shots("Cust A", "PN-3001", "LINEAR_PRORATION",
                                     "CNC_1", "PRESS_500T", "TRK-A")
    # The first scenario leaves the logical clock at 2026-08-25; the second
    # scenario's reservation windows and report period must all lie at or
    # after that instant (PRD §2.4 no-backward clock, §2.9 start>=now).
    ctx_declining = _tool_at_100k_shots(
        "Cust B", "PN-3002", "DECLINING_BALANCE",
        "CNC_2", "PRESS_800T", "TRK-B",
        machine_window=("2026-08-26T08:00:00Z", "2026-08-26T16:00:00Z"),
        press_window=("2026-09-01T08:00:00Z", "2026-09-01T16:00:00Z"),
        submit_clock="2026-09-01T10:00:00Z",
        after_window_clock="2026-09-10T00:00:00Z",
        report_period_end="2026-09-05T00:00:00Z",
    )
    claim_linear = _approve_claim(ctx_linear)
    claim_declining = _approve_claim(ctx_declining)

    assert_warranty_claim(claim_declining)
    assert claim_declining["claimed_at_shot_count"] == 100_000
    # base 500,000 * (150,000/250,000)^2 = 500,000 * 0.36.
    assert claim_declining["approved_credit_cents"] == 180_000, (
        f"DECLINING_BALANCE credit mismatch: {claim_declining['approved_credit_cents']}"
    )
    assert claim_linear["approved_credit_cents"] == 300_000
    divergence = claim_linear["approved_credit_cents"] - claim_declining["approved_credit_cents"]
    assert divergence == 120_000, f"variant divergence mismatch: {divergence}"
    assert ctx_declining["tool"]["warranty_terms"] == "DECLINING_BALANCE"
