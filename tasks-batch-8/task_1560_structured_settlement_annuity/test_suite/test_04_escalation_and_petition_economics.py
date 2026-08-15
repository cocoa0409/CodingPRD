"""Escalation arithmetic and transfer-petition valuation (PRD §3.3, §3.6)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    setup_executed_with_draft_schedule, setup_active_case,
    create_petition, file_petition,
    TEST_USERS, make_case_manager_headers,
)

READER = TEST_USERS["reader_headers"]


# --- Escalation: carry-rounded vs end-rounded (PRD §3.3) -------------------------

def _setup_escalation_payments():
    """EXECUTED agreement; DRAFT schedule anchored 2026-02-01 with two payments:
    base 99994 at 333 bps due 2027-02-01 (n=1) and 2028-02-01 (n=2)."""
    ctx = setup_executed_with_draft_schedule(
        [{"due_date": "2027-02-01", "base_amount_cents": 99994, "escalation_rate_bps": 333},
         {"due_date": "2028-02-01", "base_amount_cents": 99994, "escalation_rate_bps": 333}],
        agreement_overrides={"case_number": "ESC-001"})
    return ctx["payments"]


def test_escalation_variants_agree_at_single_anniversary(api):
    """PRD §3.3: "The two figures coincide when n is zero or one; with two or more
    anniversaries, intermediate rounding can shed fractional cents and the figures
    diverge."
    PRD §3.3: "starting from `base_amount_cents`, each of the n annual steps multiplies
    the running value by one plus `escalation_rate_bps` divided by ten thousand and
    rounds half up to a whole cent".

    Design: Difficulty/dual_variant_calc/escalation_carry_vs_end_rounding
    """
    payments = _setup_escalation_payments()
    p1 = payments[0]  # due 2027-02-01: one anniversary (n=1)
    # carry-rounded: round_half_up(99994 * 1.0333) = round_half_up(103323.80) = 103324
    assert p1["amount_cents"] == 103324
    # end-rounded agrees at n=1: round_half_up(99994 * 1.0333^1) = 103324
    assert p1["disclosure_amount_cents"] == 103324


def test_escalation_variants_diverge_at_second_anniversary(api):
    """PRD §3.3: "The `disclosure_amount_cents` compounds unrounded — the base times the
    annual factor raised to the n-th power — and rounds half up to a whole cent exactly
    once at the end."
    PRD §3.3: "`amount_cents` is the only amount ever paid, moved between ledger buckets,
    or discounted in later workflows; the disclosure figure exists for statements."

    Design: Difficulty/dual_variant_calc/escalation_carry_vs_end_rounding
    """
    payments = _setup_escalation_payments()
    p2 = payments[1]  # due 2028-02-01: two anniversaries (n=2)
    # carry-rounded: round_half_up(103324 * 1.0333) = round_half_up(106764.69) = 106765
    assert p2["amount_cents"] == 106765
    # end-rounded: round_half_up(99994 * 1.0333^2) = round_half_up(106764.48) = 106764
    assert p2["disclosure_amount_cents"] == 106764
    assert p2["amount_cents"] - p2["disclosure_amount_cents"] == 1, (
        "carry-rounding sheds no fractional cents; the variants diverge by exactly one cent"
    )


def test_escalation_anniversary_inclusive_of_due_date(api):
    """PRD §3.3: "The exponent n is the number of anniversaries of the schedule's
    `escalation_anchor_date` that fall on or before the payment's `due_date` — an
    anniversary landing exactly on the due date counts."

    Design: Corner/calculations/escalation_n_counts_anniversaries_inclusive
    """
    ctx = setup_executed_with_draft_schedule(
        [{"due_date": "2027-01-31", "base_amount_cents": 50000, "escalation_rate_bps": 200},
         {"due_date": "2027-02-01", "base_amount_cents": 50000, "escalation_rate_bps": 200}],
        agreement_overrides={"case_number": "CC-002"})
    # 2027-01-31: the 2027-02-01 anniversary has not been reached -> n=0
    assert ctx["payments"][0]["amount_cents"] == 50000
    # 2027-02-01: the anniversary lands exactly on the due date -> n=1
    assert ctx["payments"][1]["amount_cents"] == 51000


# --- Transfer petition valuation (PRD §3.6) ---------------------------------------

def _setup_two_payment_case(policy_overrides=None, case_number="TR-001", clock_to="2029-01-01T00:00:00Z"):
    """Funded agreement, ACTIVE schedule with 100000 due 2030-01-01 and 100000 due
    2031-01-01 (esc 0); logical clock at 2029-01-01 so t1=1.0 and t2=2.0 ACT/365."""
    return setup_active_case(
        payments=[{"due_date": "2030-01-01", "base_amount_cents": 100000},
                  {"due_date": "2031-01-01", "base_amount_cents": 100000}],
        clock_to=clock_to,
        agreement_overrides={"case_number": case_number},
        policy_overrides=policy_overrides)


def test_transfer_rates_computed_at_creation(api):
    """PRD §3.6: "The `effective_annual_rate_bps`, the statutory figure, is ten thousand
    times the single positive rate at which the matched payments' discounted
    `amount_cents` exactly equal `purchase_price_cents`, rounded half up; on any
    discounted multi-payment set it is strictly greater than the aggregate figure, and
    the SSPA cap applies to this actuarial value alone."

    Design: Difficulty/dual_variant_calc/transfer_rate_aggregate_vs_irr
    """
    ctx = _setup_two_payment_case()
    petition = create_petition(ctx, 180000, "2030-01-01", "2031-12-31")
    # aggregate: round_half_up(10000 * 20000 / 200000 / 1.5) = 667
    assert petition["disclosed_discount_rate_bps"] == 667
    # IRR: solves 180000 = 100000/(1+r) + 100000/(1+r)^2 -> 732 bps
    assert petition["effective_annual_rate_bps"] == 732
    # PV at the contract rate 500 bps: 95238 + 90703
    assert petition["present_value_cents"] == 185941
    assert petition["effective_annual_rate_bps"] > petition["disclosed_discount_rate_bps"]
    assert petition["status"] == "DRAFT"


def test_file_rejected_when_irr_exceeds_cap_despite_aggregate_below(api):
    """PRD §3.6: "the petition's `effective_annual_rate_bps` must not exceed the
    governing profile's `sspa_max_discount_rate_bps` (`ERR_EFFECTIVE_RATE_EXCEEDS_CAP`,
    HTTP 422)".
    PRD §3.6: "the SSPA cap applies to this actuarial value alone."

    Design: Difficulty/dual_variant_calc/transfer_rate_aggregate_vs_irr
    """
    ctx = _setup_two_payment_case()
    petition = create_petition(ctx, 180000, "2030-01-01", "2031-12-31")
    # The disclosed aggregate 667 sits under the 700 cap, but the cap binds the IRR 732.
    assert petition["disclosed_discount_rate_bps"] <= 700
    resp = api.file_petition(petition["id"], make_case_manager_headers("cm-1"))
    validate_error(resp, ApiErrorId.ERR_EFFECTIVE_RATE_EXCEEDS_CAP)
    refreshed = validate_success(api.get_transfer_petition(petition["id"], READER))
    assert refreshed["status"] == "DRAFT", "a rejected file leaves the petition DRAFT"


def test_present_value_per_payment_rounding_then_sum(api):
    """PRD §3.6: "every payment's `amount_cents` divided by one plus the contract rate
    raised to that payment's time factor, each result rounded half up to whole cents
    first and only then summed — the pinned rounding order is the contract, since
    summing unrounded values and rounding once can differ by a cent or more."

    Design: Difficulty/combinatorial_formula/pv_per_payment_rounding_order
    """
    ctx = setup_active_case(
        payments=[{"due_date": "2030-01-01", "base_amount_cents": 99999},
                  {"due_date": "2030-01-01", "base_amount_cents": 100009}],
        clock_to="2029-01-01T00:00:00Z",
        agreement_overrides={"case_number": "PV-001"},
        policy_overrides={"contract_discount_rate_bps": 400})
    petition = create_petition(ctx, 150000, "2030-01-01", "2030-01-01")
    # per-payment: round_half_up(99999/1.04)=96153 and round_half_up(100009/1.04)=96163
    assert petition["present_value_cents"] == 192316
    assert petition["present_value_cents"] != 192315, (
        "sum-then-round would yield 192315; the pinned per-payment order is the contract"
    )


def test_petition_creation_records_matched_count_and_starts_draft(api):
    """PRD §3.6: "an empty set fails creation with `ERR_NO_TRANSFERRABLE_PAYMENTS`, and
    `transferred_payment_count` records the matched count."
    PRD §3.6: "The petition must be `DRAFT` (`ERR_PETITION_INVALID_STATE`)" — filing is
    the transition out of the initial DRAFT state.

    Design: Difficulty/combinatorial_formula/pv_per_payment_rounding_order
    """
    ctx = setup_active_case(
        payments=[{"due_date": "2030-01-01", "base_amount_cents": 99999},
                  {"due_date": "2030-01-01", "base_amount_cents": 100009}],
        clock_to="2029-01-01T00:00:00Z",
        agreement_overrides={"case_number": "PV-001"},
        policy_overrides={"contract_discount_rate_bps": 400})
    petition = create_petition(ctx, 150000, "2030-01-01", "2030-01-01")
    assert petition["transferred_payment_count"] == 2
    assert petition["status"] == "DRAFT"


def test_irr_rounding_boundary_price_at_cap_files(api):
    """PRD §3.6: "the petition's `effective_annual_rate_bps` must not exceed the
    governing profile's `sspa_max_discount_rate_bps` (`ERR_EFFECTIVE_RATE_EXCEEDS_CAP`,
    HTTP 422)" — 700 bps equals the 700 cap, so the petition files.

    Design: Difficulty/boundary_precision_check/irr_rounding_boundary_at_cap
    """
    ctx = setup_active_case(
        payments=[{"due_date": "2030-01-01", "base_amount_cents": 100000}],
        clock_to="2029-01-01T00:00:00Z",
        agreement_overrides={"case_number": "BD-001"})
    petition = create_petition(ctx, 93455, "2030-01-01", "2030-01-01")
    # round_half_up(10000 * (100000/93455 - 1)) = round_half_up(700.34) = 700
    assert petition["effective_annual_rate_bps"] == 700
    filed = file_petition(petition["id"])
    assert filed["status"] == "FILED", "700 <= 700 passes: the cap comparison is inclusive"


def test_irr_rounding_boundary_one_cent_lower_price_rejected(api):
    """PRD §3.6: "the petition's `effective_annual_rate_bps` must not exceed the
    governing profile's `sspa_max_discount_rate_bps` (`ERR_EFFECTIVE_RATE_EXCEEDS_CAP`,
    HTTP 422)" — the comparison is on the rounded basis-point figure.

    Design: Difficulty/boundary_precision_check/irr_rounding_boundary_at_cap
    """
    ctx = setup_active_case(
        payments=[{"due_date": "2030-01-01", "base_amount_cents": 100000}],
        clock_to="2029-01-01T00:00:00Z",
        agreement_overrides={"case_number": "BD-001"})
    petition = create_petition(ctx, 93453, "2030-01-01", "2030-01-01")
    # round_half_up(10000 * (100000/93453 - 1)) = round_half_up(700.55) = 701
    assert petition["effective_annual_rate_bps"] == 701
    resp = api.file_petition(petition["id"], make_case_manager_headers("cm-1"))
    validate_error(resp, ApiErrorId.ERR_EFFECTIVE_RATE_EXCEEDS_CAP)


def test_price_exceeds_present_value_returns_fiscal_error(api):
    """PRD §3.6: "`purchase_price_cents` must not exceed `present_value_cents`
    (`ERR_PRICE_EXCEEDS_PRESENT_VALUE`, HTTP 422)".

    Design: Corner/validations/price_exceeds_present_value_returns_fiscal_error
    """
    ctx = _setup_two_payment_case(case_number="VL-001")
    petition = create_petition(ctx, 185942, "2030-01-01", "2031-12-31")
    assert petition["present_value_cents"] == 185941
    assert petition["effective_annual_rate_bps"] <= 700, (
        "the rate cap is satisfied — only the fiscal guard fails"
    )
    resp = api.file_petition(petition["id"], make_case_manager_headers("cm-1"))
    validate_error(resp, ApiErrorId.ERR_PRICE_EXCEEDS_PRESENT_VALUE)
    refreshed = validate_success(api.get_transfer_petition(petition["id"], READER))
    assert refreshed["status"] == "DRAFT"


def test_no_transferrable_payments_returns_error(api):
    """PRD §3.6: "The matched set comprises payments of the agreement's `ACTIVE`
    schedule in `SCHEDULED` or `PAYABLE` status whose `due_date` falls inside the
    window; an empty set fails creation with `ERR_NO_TRANSFERRABLE_PAYMENTS`".

    Design: Corner/validations/no_transferrable_payments_returns_error
    """
    ctx = setup_active_case(
        payments=[{"due_date": "2030-01-01", "base_amount_cents": 100000}],
        agreement_overrides={"case_number": "VL-006"})
    resp = api.create_transfer_petition(
        {"settlement_agreement_id": ctx["agreement"]["id"], "payee_id": ctx["payee"]["id"],
         "factoring_company_name": "FactorCo", "purchase_price_cents": 1000,
         "transfer_start_date": "2025-01-01", "transfer_end_date": "2025-12-31"},
        TEST_USERS["case_manager_headers"])
    validate_error(resp, ApiErrorId.ERR_NO_TRANSFERRABLE_PAYMENTS)
