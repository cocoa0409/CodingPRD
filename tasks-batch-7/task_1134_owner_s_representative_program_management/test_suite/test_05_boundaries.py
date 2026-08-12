"""Boundary-precision checks (PRD §2.7, §3.4, §3.9)."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_active_program, create_drawdown, create_risk_entry, assess_risk,
    create_and_execute_contract, pm_headers,
    ApiErrorId,
)


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / contingency_exact_drain_boundary
# ---------------------------------------------------------------------------

def test_contingency_exact_drain_to_zero_succeeds(api):
    """PRD §3.5: "The requested amount must not exceed
    contingency_available_cents — equality is allowed, so an exact drain of the
    pool to zero succeeds — otherwise creation is rejected with
    ERR_CONTINGENCY_EXCEEDED (402)."

    Design: Difficulty/boundary_precision_check/contingency_exact_drain_boundary
    """
    prog = create_active_program(
        total_budget_cents=500_000, contingency_total_cents=100_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 500_000}], name="P-DRAIN",
    )
    pid = prog["id"]
    dd = create_drawdown(pid, 100_000, purpose="exact drain")
    assert dd["status"] == "RESERVED"
    p = get_success_data(api_client.get_program(pid, pm_headers()))
    assert p["contingency_available_cents"] == 0
    assert p["contingency_reserved_cents"] == 100_000


def test_contingency_one_cent_over_drained_pool_rejected(api):
    """PRD §3.5: "The requested amount must not exceed
    contingency_available_cents — equality is allowed, so an exact drain of the
    pool to zero succeeds — otherwise creation is rejected with
    ERR_CONTINGENCY_EXCEEDED (402)."

    Design: Difficulty/boundary_precision_check/contingency_exact_drain_boundary
    """
    prog = create_active_program(
        total_budget_cents=500_000, contingency_total_cents=100_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 500_000}], name="P-DRAIN2",
    )
    pid = prog["id"]
    create_drawdown(pid, 100_000, purpose="exact drain")
    resp = api_client.create_drawdown(
        {"program_id": pid, "purpose": "one cent over", "amount_cents": 1},
        pm_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_CONTINGENCY_EXCEEDED)


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / risk_escalation_threshold_equality
# ---------------------------------------------------------------------------

def test_risk_one_cent_below_threshold_stays_assessed(api):
    """PRD §3.4: "From IDENTIFIED: exposure at or above the threshold lands
    ESCALATED; below it lands ASSESSED." Threshold is $500,000.00 (50,000,000
    cents). 50 * 99_999_998 / 100 = 49_999_999 (just below).

    Design: Difficulty/boundary_precision_check/risk_escalation_threshold_equality
    """
    prog = create_active_program(
        total_budget_cents=1_000_000, contingency_total_cents=100_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 1_000_000}], name="P-THR",
    )
    pid = prog["id"]
    r = create_risk_entry(pid, probability_pct=1, impact_cents=1, title="R1", category="COST")
    assessed = assess_risk(r["id"], 50, 99_999_998)
    assert assessed["exposure_cents"] == 49_999_999
    assert assessed["status"] == "ASSESSED"


def test_risk_exactly_at_threshold_escalates(api):
    """PRD §3.4: "Assessment is threshold-driven against a fixed escalation
    line of $500,000.00 (50,000,000 cents)." And: "From ASSESSED: exposure at
    or above the threshold moves to ESCALATED" — the comparison is >=.

    Design: Difficulty/boundary_precision_check/risk_escalation_threshold_equality
    """
    prog = create_active_program(
        total_budget_cents=1_000_000, contingency_total_cents=100_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 1_000_000}], name="P-THR2",
    )
    pid = prog["id"]
    r = create_risk_entry(pid, probability_pct=1, impact_cents=1, title="R1", category="COST")
    assess_risk(r["id"], 50, 99_999_998)  # ASSESSED
    escalated = assess_risk(r["id"], 50, 100_000_000)
    assert escalated["exposure_cents"] == 50_000_000
    assert escalated["status"] == "ESCALATED"


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / begin_closing_zero_open_items
# ---------------------------------------------------------------------------

def test_begin_closing_blocked_by_one_open_contract(api):
    """PRD §3.9: "This gate is deliberately strict — five open-item families
    must all be empty, any violation surfacing ERR_PROGRAM_HAS_OPEN_ITEMS
    (409): zero contracts in SOLICITED, UNDER_NEGOTIATION, COUNTERED, or
    EXECUTED; ...".

    Design: Difficulty/boundary_precision_check/begin_closing_zero_open_items
    """
    prog = create_active_program(
        total_budget_cents=1_000_000, contingency_total_cents=100_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 1_000_000}], name="P-ZERO",
    )
    pid = prog["id"]
    create_and_execute_contract(pid, 400_000, solicitation_estimate_cents=400_000,
                                 vendor_name="V1", contract_type="CONTRACTOR")
    resp = api_client.begin_closing_program(pid, pm_headers())
    validate_error(resp, ApiErrorId.ERR_PROGRAM_HAS_OPEN_ITEMS)


def test_begin_closing_succeeds_after_last_open_item_closes(api):
    """PRD §3.9: "Wind-down begins when an OwnerRepPM moves the program
    ACTIVE → CLOSING." Gate passes at zero open items.

    Design: Difficulty/boundary_precision_check/begin_closing_zero_open_items
    """
    prog = create_active_program(
        total_budget_cents=1_000_000, contingency_total_cents=100_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 1_000_000}], name="P-ZERO2",
    )
    pid = prog["id"]
    ct = create_and_execute_contract(pid, 400_000, solicitation_estimate_cents=400_000,
                                       vendor_name="V1", contract_type="CONTRACTOR")
    resp = api_client.begin_closing_program(pid, pm_headers())
    validate_error(resp, ApiErrorId.ERR_PROGRAM_HAS_OPEN_ITEMS)
    # Close out the single open item
    done = get_success_data(api_client.complete_contract(ct["id"], pm_headers()))
    assert done["status"] == "COMPLETED"
    closing = get_success_data(api_client.begin_closing_program(pid, pm_headers()))
    assert closing["status"] == "CLOSING"
