"""Two calculations that answer differently depending on which variant is asked.

Continuing-education attribution and per-loan commission both come in two
flavours over identical stored rows, and the whole point of each pair is that
the two flavours disagree. These tests pin both answers and the exact gap
between them.
"""
from test_helpers.constants import TEST_DEFAULTS
from test_helpers.fixtures import (
    create_originator,
    file_elective_credit,
    file_license,
    get_license,
    get_loan,
    get_originator,
    list_records_for_loan,
    read_ce_compliance,
    run_reconciliation,
    set_clock,
    setup_ce_baseline_seven_hours,
    setup_closed_loan,
    sole_record_for_loan,
)

# --- local scenario builders -------------------------------------------------


def _build_ce_scenario(api):
    """Seven 2026 hours plus a one-hour make-up credit completed 2027-01-15.

    The three non-make-up credits (3 federal-law, 2 ethics, 2 non-traditional)
    are completed in June 2026. The make-up elective is completed after the
    calendar year turns but is filed for reporting_period_year 2026, which is
    the single row the two attribution variants disagree about.
    """
    originator = create_originator(api)
    licence = file_license(
        api,
        originator["id"],
        state_code=TEST_DEFAULTS["STATE_CODE"],
        ce_reporting_year=2026,
        required_ce_hours=8,
    )
    baseline = setup_ce_baseline_seven_hours(
        api, originator["id"], completion_date="2026-06-15T00:00:00Z", reporting_period_year=2026
    )
    set_clock(api, "2027-01-20T00:00:00Z")
    makeup = file_elective_credit(
        api,
        originator["id"],
        credit_hours=1,
        completion_date="2027-01-15T00:00:00Z",
        reporting_period_year=2026,
        is_makeup=True,
    )
    return {
        "originator": originator,
        "license": licence,
        "baseline": baseline,
        "makeup_credit": makeup["credit"],
    }


def _build_divergent_commission_loan(api):
    """A loan locked at 20,000,000 cents but funded at 20,500,000 cents.

    The plan pays 105 basis points with the volume tier enabled but with a
    file quality score of 95 and 80 percent hours worked, so the tier adder is
    zero and the only difference between the two variants is which amount they
    multiply.
    """
    return setup_closed_loan(
        api,
        plan_overrides={
            "base_basis_points": 105,
            "min_fee_cents": 100_000,
            "max_fee_cents": 900_000,
            "volume_tier_enabled": True,
            "concession_absorption_enabled": False,
        },
        lock_overrides={"note_rate_bps": 650, "locked_amount_cents": 20_000_000},
        close_overrides={
            "funded_amount_cents": 20_500_000,
            "funded_at": "2026-09-01T00:00:00Z",
            "lender_paid_comp_cents": 215_250,
            "borrower_paid_comp_cents": 0,
            "file_quality_score": 95,
            "hours_worked_pct": 80,
        },
    )


# --- MAKEUP_ATTRIBUTION vs CALENDAR_YEAR_ATTRIBUTION ------------------------


def test_makeup_attribution_counts_the_january_make_up_credit(api):
    """PRD §3.2: "A credit filed with `is_makeup` true is attributed instead to its
    `reporting_period_year`; `reporting_period_year` is ignored entirely for attribution
    purposes unless `is_makeup` is true."
    PRD §3.2: "Under `MAKEUP_ATTRIBUTION` a credit is counted when its `attributed_year`
    equals the target year."
    PRD §3.2: "The licence's `ce_satisfied` is set true only when all four of the following
    minimums are met: the overall total is at least the licence's own `required_ce_hours`,
    the federal-law total is at least three hours, the ethics total is at least two hours,
    and the non-traditional total is at least two hours."

    Design: Difficulty/dual_variant_calc/ce_attribution_variant_flips_ce_satisfied
    """
    scenario = _build_ce_scenario(api)

    assert scenario["makeup_credit"]["attributed_year"] == 2026, (
        "a make-up credit is attributed to its reporting_period_year, not its completion year"
    )
    assert scenario["makeup_credit"]["credit_status"] == "APPLIED"

    report = read_ce_compliance(
        api,
        scenario["originator"]["id"],
        attribution_variant="MAKEUP_ATTRIBUTION",
        reporting_year=2026,
    )
    assert report["attribution_variant"] == "MAKEUP_ATTRIBUTION"
    assert report["reporting_year"] == 2026
    assert report["total_hours"] == 8, f"expected 8 counted hours, got {report['total_hours']}"
    assert report["federal_law_hours"] == 3
    assert report["ethics_hours"] == 2
    assert report["nontraditional_hours"] == 2
    assert report["ce_satisfied"] is True, "eight hours against a required eight satisfies CE"


def test_calendar_year_attribution_drops_the_january_make_up_credit(api):
    """PRD §3.2: "Under `CALENDAR_YEAR_ATTRIBUTION` a credit is counted when the calendar
    year of its `completion_date` equals the target year, whatever `is_makeup` says."
    PRD §3.2: "Under `CALENDAR_YEAR_ATTRIBUTION` it is attributed to 2027 and does **not**
    enter the 2026 total; under `MAKEUP_ATTRIBUTION` it is attributed to 2026 and **does**
    enter it."

    Design: Difficulty/dual_variant_calc/ce_attribution_variant_flips_ce_satisfied
    """
    scenario = _build_ce_scenario(api)
    originator_id = scenario["originator"]["id"]

    calendar = read_ce_compliance(
        api,
        originator_id,
        attribution_variant="CALENDAR_YEAR_ATTRIBUTION",
        reporting_year=2026,
    )
    makeup = read_ce_compliance(
        api,
        originator_id,
        attribution_variant="MAKEUP_ATTRIBUTION",
        reporting_year=2026,
    )

    assert calendar["attribution_variant"] == "CALENDAR_YEAR_ATTRIBUTION"
    assert calendar["total_hours"] == 7, (
        f"the 2027-completed make-up hour must not count, got {calendar['total_hours']}"
    )
    assert calendar["ce_satisfied"] is False, "seven hours against a required eight fails CE"
    assert calendar["federal_law_hours"] == 3, (
        "the federal-law minimum is met under both variants, so only the make-up credit's "
        "attributed year can explain the flip"
    )
    assert makeup["federal_law_hours"] == 3
    assert makeup["total_hours"] - calendar["total_hours"] == 1, (
        "the two variants must differ by exactly the one make-up hour"
    )
    assert makeup["ce_satisfied"] is True


def test_filing_the_make_up_credit_persists_the_make_up_total_on_the_licence(api):
    """PRD §3.2: "The overall total is written to the licence's `ce_hours_applied`."
    PRD §3.2: "`MAKEUP_ATTRIBUTION` is used when a renewal is completed, when a credit is
    filed, when a credit is voided, and when a course provider is rescinded."

    Design: Difficulty/dual_variant_calc/ce_attribution_variant_flips_ce_satisfied
    """
    scenario = _build_ce_scenario(api)

    licence = get_license(api, scenario["license"]["id"])
    assert licence["ce_reporting_year"] == 2026
    assert licence["required_ce_hours"] == 8
    assert licence["ce_hours_applied"] == 8, (
        "filing a credit recomputes the licence with MAKEUP_ATTRIBUTION, so the make-up hour "
        f"counts: got {licence['ce_hours_applied']}"
    )
    assert licence["ce_satisfied"] is True


# --- PROVISIONAL locked amount vs FINAL funded amount -----------------------


def test_provisional_line_at_close_prices_the_locked_amount(api):
    """PRD §3.5: "The **provisional variant** — the one written at close — supplies those two
    inputs chronologically: the amount is the loan's `locked_amount_cents`, the amount at rate
    lock, and the unit count is the loan's `closed_unit_index` less one, that is, the
    originator's closed-unit count strictly *before* this loan."
    PRD §3.5: "A unit count of four or fewer yields a tier value of zero basis points."
    PRD §3.5: "A line's `paid_cents` reads `0` while its `status` is `ACCRUED` and equals its
    `accrued_cents` once the line reaches `RECONCILED`; `clawback_cents` reads `0` unless the
    line has been clawed back; and `days_held` and `recapture_pct` both read null until a
    payoff is recorded against the loan."

    Design: Difficulty/dual_variant_calc/comp_accrual_provisional_locked_vs_final_funded_divergence
    """
    context = _build_divergent_commission_loan(api)

    assert context["loan"]["status"] == "CLOSED"
    assert context["loan"]["compensation_status"] == "ACCRUED"
    assert context["loan"]["closed_unit_index"] == 1

    record = sole_record_for_loan(api, context["loan"]["id"])
    assert record["variant"] == "PROVISIONAL"
    assert record["status"] == "ACCRUED"
    assert record["tier_bps_adder"] == 0, (
        "the first closed unit earns tier zero, and quality 95 with 80 percent hours adds nothing"
    )
    assert record["base_comp_cents"] == 210_000, (
        "20,000,000 cents at 105 basis points is 210,000 cents"
    )
    assert record["comp_impact_cents"] == 0
    assert record["accrued_cents"] == 210_000
    assert record["paid_cents"] == 0
    assert record["days_held"] is None
    assert record["recapture_pct"] is None


def test_reconciliation_reprices_the_line_on_the_funded_amount(api):
    """PRD §3.7: "The amount it multiplies is the loan's `funded_amount_cents` — the amount
    actually funded — rather than `locked_amount_cents`."
    PRD §3.7: "The run reports `originator_id`, a `reconciled_count` giving how many lines it
    rewrote, a `total_final_cents` equal to the sum of the rewritten lines' new
    `accrued_cents`, a `total_delta_cents` equal to that total less the sum of those same
    lines' pre-run `accrued_cents`, and the `compensation_record_ids` of the lines it touched."
    PRD §3.7: "The line's `variant` flips `PROVISIONAL → FINAL`; its `tier_bps_adder`,
    `base_comp_cents` and `accrued_cents` are recomputed using the final variant's inputs; its
    `status` advances `ACCRUED → RECONCILED`; its `paid_cents` is set equal to its freshly
    computed `accrued_cents`, which is what makes the money recapturable later; and its
    `reconciled_at` is stamped from the logical clock."

    Design: Difficulty/dual_variant_calc/comp_accrual_provisional_locked_vs_final_funded_divergence
    """
    context = _build_divergent_commission_loan(api)
    loan_id = context["loan"]["id"]
    provisional = sole_record_for_loan(api, loan_id)
    assert provisional["accrued_cents"] == 210_000

    run = run_reconciliation(api, context["originator"]["id"])
    assert run["reconciled_count"] == 1
    assert run["total_final_cents"] == 215_250, (
        "20,500,000 cents at 105 basis points is 215,250 cents"
    )
    assert run["total_delta_cents"] == 5_250, (
        "the funded amount exceeds the locked amount by 500,000 cents, worth 5,250 cents of "
        "commission at 105 basis points"
    )
    assert run["compensation_record_ids"] == [provisional["id"]]

    record = sole_record_for_loan(api, loan_id)
    assert record["id"] == provisional["id"]
    assert record["variant"] == "FINAL"
    assert record["status"] == "RECONCILED"
    assert record["tier_bps_adder"] == 0
    assert record["base_comp_cents"] == 215_250
    assert record["accrued_cents"] == 215_250
    assert record["paid_cents"] == 215_250


def test_reconciliation_rewrites_the_single_line_and_moves_the_ledger_totals(api):
    """PRD §3.7: "For each eligible loan the run rewrites that loan's existing provisional
    ledger line in place rather than creating a second one."
    PRD §3.7: "The owning loan's `compensation_status` advances `ACCRUED → RECONCILED` in step."
    PRD §2.11: "An originator's `lifetime_accrued_cents` is at all times the sum of
    `accrued_cents` over every one of that originator's ledger lines in any status,
    `lifetime_clawed_back_cents` is at all times the sum of `clawback_cents` over the same set,
    and `net_compensation_cents` is at all times exactly `lifetime_accrued_cents` less
    `lifetime_clawed_back_cents` — it is a derived balance and is never written directly."

    Design: Difficulty/dual_variant_calc/comp_accrual_provisional_locked_vs_final_funded_divergence
    """
    context = _build_divergent_commission_loan(api)
    loan_id = context["loan"]["id"]

    run_reconciliation(api, context["originator"]["id"])

    records = list_records_for_loan(api, loan_id)
    assert len(records) == 1, f"reconciliation must not add a second line: {records}"

    loan = get_loan(api, loan_id)
    assert loan["status"] == "CLOSED"
    assert loan["compensation_status"] == "RECONCILED"

    originator = get_originator(api, context["originator"]["id"])
    assert originator["lifetime_accrued_cents"] == 215_250
    assert originator["lifetime_clawed_back_cents"] == 0
    assert originator["net_compensation_cents"] == 215_250
