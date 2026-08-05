"""Payoff quotes: PROVISIONAL vs BINDING dual-variant interest, and the
multi-input interest formula with a charge_type exclusion."""
from test_helpers import (
    validate_success, get_success_data,
    TEST_USERS,
    fixtures,
)

AGENT = TEST_USERS["collections_agent_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


# --- dual_variant_calc / dv_payoff_provisional_vs_binding (queue A, >=2 tests) ---

def _single_regular_100k(api):
    fixtures.set_clock(api, "2026-05-01T00:00:00Z")
    assoc, acct = fixtures.setup_account(api, {"name": "Oak HOA", "state_code": "CA",
                                               "interest_rate_annual_pct": 12.0})
    fixtures.create_assessment(api, acct["id"], 100000, due_date="2026-01-01T00:00:00Z")
    return acct


def test_payoff_provisional_interest_through_now(api):
    """PRD §3.8: "The quote comes in two variants selected by `variant`: `PROVISIONAL` (the
    default) accrues interest through today, while `BINDING` projects interest forward
    through the good-through date, which is the logical-clock now plus 15 days."
    PRD §3.8: "The `payoff_amount_cents` is the account's `total_balance_cents` plus
    `accrued_interest_cents`."

    Design: Difficulty/dual_variant_calc/dv_payoff_provisional_vs_binding
    """
    acct = _single_regular_100k(api)
    data = validate_success(api.get_payoff_quote(acct["id"], AGENT, variant="PROVISIONAL"))
    assert data["total_balance_cents"] == 100000
    assert data["accrued_interest_cents"] == 3945, data["accrued_interest_cents"]
    assert data["payoff_amount_cents"] == 103945, data["payoff_amount_cents"]


def test_payoff_binding_projects_interest_forward(api):
    """PRD §3.8: "`BINDING` projects interest forward through the good-through date, which is
    the logical-clock now plus 15 days."
    PRD §3.8: "The `payoff_amount_cents` is the account's `total_balance_cents` plus
    `accrued_interest_cents`."

    Design: Difficulty/dual_variant_calc/dv_payoff_provisional_vs_binding
    """
    acct = _single_regular_100k(api)
    prov = validate_success(api.get_payoff_quote(acct["id"], AGENT, variant="PROVISIONAL"))
    binding = validate_success(api.get_payoff_quote(acct["id"], AGENT, variant="BINDING"))
    assert binding["accrued_interest_cents"] == 4438, binding["accrued_interest_cents"]
    assert binding["payoff_amount_cents"] == 104438, binding["payoff_amount_cents"]
    assert binding["payoff_amount_cents"] - prov["payoff_amount_cents"] == 493


# --- combinatorial_formula / cf_payoff_interest_multiinput_mode_a (queue A, >=2 tests) ---

def _regular_100k_plus_attorney_50k(api):
    fixtures.set_clock(api, "2026-05-01T00:00:00Z")
    assoc, acct = fixtures.setup_account(api, {"name": "Pine HOA", "state_code": "CA",
                                               "interest_rate_annual_pct": 12.0})
    fixtures.create_assessment(api, acct["id"], 100000, charge_type="REGULAR",
                               due_date="2026-01-01T00:00:00Z")
    fixtures.create_assessment(api, acct["id"], 50000, charge_type="ATTORNEY_COST",
                               due_date="2026-01-01T00:00:00Z")
    return acct


def test_payoff_interest_excludes_attorney_cost(api):
    """PRD §3.8: "Interest accrues only on **principal** — assessments in `OPEN` or `PARTIAL`
    whose `charge_type` is `REGULAR` or `SPECIAL`; late fees, prior interest, attorney costs,
    and fines are excluded from the interest base (though they remain part of the account's
    `total_balance_cents`)."

    Design: Difficulty/combinatorial_formula/cf_payoff_interest_multiinput_mode_a
    """
    acct = _regular_100k_plus_attorney_50k(api)
    data = validate_success(api.get_payoff_quote(acct["id"], OFFICER, variant="PROVISIONAL"))
    # only the 100000 REGULAR accrues interest -> same 3945 as the single-REGULAR case
    assert data["accrued_interest_cents"] == 3945, data["accrued_interest_cents"]


def test_payoff_total_includes_attorney_cost(api):
    """PRD §3.8: "The `payoff_amount_cents` is the account's `total_balance_cents` plus
    `accrued_interest_cents`."

    Design: Difficulty/combinatorial_formula/cf_payoff_interest_multiinput_mode_a
    """
    acct = _regular_100k_plus_attorney_50k(api)
    data = validate_success(api.get_payoff_quote(acct["id"], OFFICER, variant="PROVISIONAL"))
    assert data["total_balance_cents"] == 150000
    assert data["payoff_amount_cents"] == 153945, data["payoff_amount_cents"]
