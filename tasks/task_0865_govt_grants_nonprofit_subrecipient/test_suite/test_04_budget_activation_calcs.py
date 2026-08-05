"""Subaward activation gates and the indirect / federal-share calculations."""
from test_helpers import (
    validate_success,
    validate_error,
    setup_active_subaward,
    setup_draft_subaward,
    get_subaward,
    MTDC_BUDGET_LINES,
    make_program_officer_headers,
)


def test_indirect_de_minimis_rate_applied(api):
    """PRD §3.5: "Multiply that base by the applicable rate — a fixed 0.10 when the
    indirect_method is DE_MINIMIS, regardless of any stored negotiated_indirect_rate, or the
    subaward's negotiated_indirect_rate when the method is NEGOTIATED — and round the single
    product half up to whole cents. Identical budget lines therefore yield a different
    indirect_cost_cents under the two methods."

    Design: Difficulty/dual_variant_calc/indirect_recovery_de_minimis_vs_negotiated
    """
    ctx = setup_active_subaward(
        requested_amount_cents=11_000_000, indirect_method="DE_MINIMIS",
        budget_lines=[{"category": "PERSONNEL", "amount_cents": 10_000_000, "federal_share_pct": 1.0}],
    )
    assert ctx["subaward"]["indirect_cost_cents"] == 1_000_000
    assert ctx["subaward"]["status"] == "ACTIVE"


def test_indirect_negotiated_rate_applied(api):
    """PRD §3.5: "Multiply that base by the applicable rate — a fixed 0.10 when the
    indirect_method is DE_MINIMIS, regardless of any stored negotiated_indirect_rate, or the
    subaward's negotiated_indirect_rate when the method is NEGOTIATED — and round the single
    product half up to whole cents. Identical budget lines therefore yield a different
    indirect_cost_cents under the two methods."

    Design: Difficulty/dual_variant_calc/indirect_recovery_de_minimis_vs_negotiated
    """
    ctx = setup_active_subaward(
        requested_amount_cents=12_000_000, indirect_method="NEGOTIATED",
        negotiated_indirect_rate=0.20,
        budget_lines=[{"category": "PERSONNEL", "amount_cents": 10_000_000, "federal_share_pct": 1.0}],
    )
    assert ctx["subaward"]["indirect_cost_cents"] == 2_000_000
    assert ctx["subaward"]["status"] == "ACTIVE"


def test_indirect_mtdc_excludes_equipment_and_caps_contractual(api):
    """PRD §3.5: "The indirect_cost_cents is derived from a modified-total-direct-cost base:
    iterate the budget lines, excluding any EQUIPMENT line from the base entirely, counting
    each CONTRACTUAL line only up to the first 25,000 dollars — that is, the smaller of the
    line's amount_cents and 2,500,000 cents — and counting every other line at its full
    amount_cents."

    Base = 10000000+3000000+1000000+500000 + min(6000000,2500000)=17000000; *0.10 = 1700000.

    Design: Difficulty/combinatorial_formula/indirect_mtdc_excludes_equipment_and_caps_contractual
    """
    ctx = setup_active_subaward(
        requested_amount_cents=26_200_000, indirect_method="DE_MINIMIS",
        budget_lines=MTDC_BUDGET_LINES,
    )
    assert ctx["subaward"]["indirect_cost_cents"] == 1_700_000


def test_mtdc_budget_activation_succeeds(api):
    """PRD §3.5: "Finally the budget must balance exactly: the sum of every line's amount_cents
    plus the computed indirect recovery must equal total_budget_cents to the cent, and any
    nonzero variance — even a single cent — fails with ERR_BUDGET_NOT_BALANCED."

    Direct sum 24500000 + indirect 1700000 == total 26200000, so activation moves to ACTIVE.

    Design: Difficulty/combinatorial_formula/indirect_mtdc_excludes_equipment_and_caps_contractual
    """
    ctx = setup_active_subaward(
        requested_amount_cents=26_200_000, indirect_method="DE_MINIMIS",
        budget_lines=MTDC_BUDGET_LINES,
    )
    assert ctx["subaward"]["status"] == "ACTIVE"
    assert ctx["subaward"]["indirect_cost_cents"] == 1_700_000


def test_federal_share_rounds_per_line_before_summing(api):
    """PRD §3.5: "The federal_share_cents is computed by taking each budget line in created_at
    ascending order, multiplying its amount_cents by its federal_share_pct, rounding that line's
    product half up to the cent, and summing those already-rounded per-line values; the indirect
    recovery is not a budget line and contributes no federal share."

    12345 * 0.5 = 6172.5 -> 6173 per line; 6173 + 6173 == 12346 (not sum-then-round 12345).

    Design: Difficulty/combinatorial_formula/federal_share_per_line_rounding
    """
    ctx = setup_active_subaward(
        requested_amount_cents=27_159, indirect_method="DE_MINIMIS",
        budget_lines=[
            {"category": "PERSONNEL", "amount_cents": 12_345, "federal_share_pct": 0.5},
            {"category": "SUPPLIES", "amount_cents": 12_345, "federal_share_pct": 0.5},
        ],
    )
    assert ctx["subaward"]["federal_share_cents"] == 12_346


def test_federal_share_persisted_on_fetch(api):
    """PRD §3.5: "rounding that line's product half up to the cent, and summing those
    already-rounded per-line values; the indirect recovery is not a budget line and contributes
    no federal share."

    Design: Difficulty/combinatorial_formula/federal_share_per_line_rounding
    """
    ctx = setup_active_subaward(
        requested_amount_cents=27_159, indirect_method="DE_MINIMIS",
        budget_lines=[
            {"category": "PERSONNEL", "amount_cents": 12_345, "federal_share_pct": 0.5},
            {"category": "SUPPLIES", "amount_cents": 12_345, "federal_share_pct": 0.5},
        ],
    )
    fetched = get_subaward(ctx["sub_id"])
    assert fetched["federal_share_cents"] == 12_346


def test_budget_off_by_one_cent_rejected(api):
    """PRD §3.5: "any nonzero variance — even a single cent — fails with
    ERR_BUDGET_NOT_BALANCED."

    Single PERSONNEL line 10000001 -> indirect round(10000001*0.10)=1000000; sum 11000001 != 11000000.

    Design: Difficulty/boundary_precision_check/budget_balance_off_by_one_cent_rejected
    """
    ctx = setup_draft_subaward(
        requested_amount_cents=11_000_000, indirect_method="DE_MINIMIS",
        budget_lines=[{"category": "PERSONNEL", "amount_cents": 10_000_001, "federal_share_pct": 1.0}],
    )
    res = api.activate_subaward(ctx["sub_id"], make_program_officer_headers())
    validate_error(res, "ERR_BUDGET_NOT_BALANCED")


def test_budget_off_by_one_cent_leaves_subaward_draft(api):
    """PRD §3.5: "Finally the budget must balance exactly: the sum of every line's `amount_cents`
    plus the computed indirect recovery must equal `total_budget_cents` to the cent, and any
    nonzero variance — even a single cent — fails with `ERR_BUDGET_NOT_BALANCED`."

    A rejected activation must not advance the subaward out of DRAFT.

    Design: Difficulty/boundary_precision_check/budget_balance_off_by_one_cent_rejected
    """
    ctx = setup_draft_subaward(
        requested_amount_cents=11_000_000, indirect_method="DE_MINIMIS",
        budget_lines=[{"category": "PERSONNEL", "amount_cents": 10_000_001, "federal_share_pct": 1.0}],
    )
    validate_error(
        api.activate_subaward(ctx["sub_id"], make_program_officer_headers()),
        "ERR_BUDGET_NOT_BALANCED",
    )
    assert get_subaward(ctx["sub_id"])["status"] == "DRAFT"


def test_activate_with_no_budget_lines_rejected(api):
    """PRD §3.5: "At least one budget line must exist, or activation fails with
    ERR_NO_BUDGET_LINES."

    Design: Corner/validations/activate_with_no_budget_lines_rejected
    """
    ctx = setup_draft_subaward(budget_lines=[])
    res = api.activate_subaward(ctx["sub_id"], make_program_officer_headers())
    validate_error(res, "ERR_NO_BUDGET_LINES")
