"""Trade-in appraisal valuation variants and offer lifecycle (PRD §3.2)."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_customer, create_appraisal, evaluate_appraisal, create_offered_appraisal,
    make_customer_headers, set_clock,
    assert_appraisal,
)


def test_provisional_value_computed_at_creation(api, sales_associate_headers):
    """PRD §3.2: "The estimate works from the instrument's age — the calendar year of the
    current logical clock minus the `year_built` — and from category base values: 2,800,000
    cents for a `GRAND`, 900,000 for an `UPRIGHT`, 250,000 for a `DIGITAL`, and 600,000 for
    a `HYBRID`. An age factor of one minus three hundredths per year of age is applied, but
    it is never allowed to fall below 0.40 no matter how old the instrument is. The
    provisional value is the category base, multiplied by the age factor, multiplied by one
    minus a wear allowance — 0 percent for `EXCELLENT`, 5 percent for `GOOD`, 15 percent for
    `FAIR`, and 30 percent for `POOR` — rounded half-up to whole cents. The new appraisal
    sits in `SUBMITTED`."
    (GRAND 2016 at clock year 2026: age 10, factor 0.70, wear 5% -> 2800000 * 0.70 * 0.95
    == 1862000.)

    Design: Difficulty/dual_variant_calc/trade_in_provisional_vs_final_valuation
    """
    customer = create_customer(full_name="Ann Avery", email="ann@x.com")
    appraisal = validate_success(api.create_trade_in_appraisal(
        {"customer_id": customer["id"], "category": "GRAND", "manufacturer": "Steinway",
         "model": "D", "year_built": 2016, "condition_grade": "GOOD"},
        sales_associate_headers), 201)
    assert_appraisal(appraisal)
    assert appraisal["status"] == "SUBMITTED"
    assert appraisal["provisional_value_cents"] == 1_862_000, (
        f"expected provisional 1862000, got {appraisal['provisional_value_cents']}")


def test_final_value_differs_from_provisional_after_evaluate(api, sales_associate_headers, store_manager_headers):
    """PRD §3.2: "The final value takes the stored `provisional_value_cents`, subtracts the
    `reconditioning_cost_cents`, then multiplies by one plus the market adjustment after the
    adjustment has been clamped to the band from −0.15 to +0.15; a single round half-up to
    whole cents happens at the end, so the evaluation order — provisional first, then the
    reconditioning deduction, then the adjustment — is pinned. Because it deducts
    reconditioning and applies market judgment, the final value differs from the provisional
    estimate for identical instrument data. The result is stored as `final_value_cents`, the
    appraisal moves to `OFFERED`, and `offered_at` is stamped with the current logical
    clock."
    ((1862000 - 150000) * 1.10 == 1883200.)

    Design: Difficulty/dual_variant_calc/trade_in_provisional_vs_final_valuation
    """
    customer = create_customer(full_name="Ann Avery", email="ann@x.com")
    appraisal = create_appraisal(customer["id"], category="GRAND", manufacturer="Steinway",
                                 model="D", year_built=2016, condition_grade="GOOD")
    evaluated = validate_success(api.evaluate_appraisal(
        appraisal["id"], {"reconditioning_cost_cents": 150_000, "market_adjustment_pct": 0.10},
        store_manager_headers), 200)
    assert evaluated["status"] == "OFFERED"
    assert evaluated["provisional_value_cents"] == 1_862_000
    assert evaluated["final_value_cents"] == 1_883_200, (
        f"expected final 1883200, got {evaluated['final_value_cents']}")
    assert evaluated["final_value_cents"] != evaluated["provisional_value_cents"]


def test_counter_moves_offered_to_countered(api, store_manager_headers):
    """PRD §3.2: "The customer — and only that customer, matching `X-User-ID` to the
    appraisal's `customer_id` — may counter by submitting a `counter_value_cents`, moving
    the appraisal from `OFFERED` to `COUNTERED` so the dealer can evaluate again."

    Design: Difficulty/non_linear_state_machine/appraisal_counter_loop_cycle
    """
    customer = create_customer(full_name="Connie Counter", email="connie@x.com")
    appraisal = create_offered_appraisal(customer["id"], 0, 0.0,
                                         category="UPRIGHT", manufacturer="Kawai",
                                         model="K300", year_built=2016,
                                         condition_grade="EXCELLENT")
    countered = validate_success(api.counter_appraisal(
        appraisal["id"], {"counter_value_cents": 650_000},
        make_customer_headers(customer["id"])), 200)
    assert countered["status"] == "COUNTERED"
    assert countered["counter_value_cents"] == 650_000


def test_countered_appraisal_can_be_re_evaluated_to_offered(api, store_manager_headers):
    """PRD §3.2: "Evaluation is permitted from either `SUBMITTED` or `COUNTERED`; against
    any other state it is rejected with `ERR_APPRAISAL_NOT_OFFERED`."
    PRD §3.2: "A re-evaluation after a counter-offer recomputes `final_value_cents` and
    re-stamps `offered_at`, restarting the offer window."
    (Re-evaluation: (630000 - 50000) * 1.0 == 580000.)

    Design: Difficulty/non_linear_state_machine/appraisal_counter_loop_cycle
    """
    customer = create_customer(full_name="Connie Counter", email="connie@x.com")
    appraisal = create_offered_appraisal(customer["id"], 0, 0.0,
                                         category="UPRIGHT", manufacturer="Kawai",
                                         model="K300", year_built=2016,
                                         condition_grade="EXCELLENT")
    assert appraisal["final_value_cents"] == 630_000
    validate_success(api.counter_appraisal(appraisal["id"], {"counter_value_cents": 650_000},
                                           make_customer_headers(customer["id"])), 200)
    re_evaluated = validate_success(api.evaluate_appraisal(
        appraisal["id"], {"reconditioning_cost_cents": 50_000, "market_adjustment_pct": 0.0},
        store_manager_headers), 200)
    assert re_evaluated["status"] == "OFFERED", "COUNTERED re-enters OFFERED (cycle re-entry)"
    assert re_evaluated["final_value_cents"] == 580_000, (
        f"expected recomputed final 580000, got {re_evaluated['final_value_cents']}")


def test_appraisal_decline_from_submitted_rejected(api):
    """PRD §3.2: "Any of these self-service actions attempted under another user's identity
    is rejected with `ERR_UNAUTHORIZED_ROLE`, and any of them attempted while the appraisal
    is not `OFFERED` is rejected with `ERR_APPRAISAL_NOT_OFFERED`."

    Design: Corner/state_machines/appraisal_decline_from_submitted_rejected
    """
    customer = create_customer(full_name="Saul Submit", email="saul@x.com")
    appraisal = create_appraisal(customer["id"], category="UPRIGHT", manufacturer="Kawai",
                                 model="K200", year_built=2018, condition_grade="GOOD")
    res = api.decline_appraisal(appraisal["id"], make_customer_headers(customer["id"]))
    validate_error(res, "ERR_APPRAISAL_NOT_OFFERED")
    after = validate_success(api.get_trade_in_appraisal(
        appraisal["id"], make_customer_headers(customer["id"])), 200)
    assert after["status"] == "SUBMITTED", "rejected decline must not change state"


def test_appraisal_terminal_declined_lockdown(api):
    """PRD §3.2: "`ACCEPTED`, `DECLINED`, and `EXPIRED` are terminal; only an `ACCEPTED`
    appraisal can feed a sales order, as §3.4 describes."
    PRD §3.2: "Any of these self-service actions attempted under another user's identity is
    rejected with `ERR_UNAUTHORIZED_ROLE`, and any of them attempted while the appraisal is
    not `OFFERED` is rejected with `ERR_APPRAISAL_NOT_OFFERED`."

    Design: Corner/state_machines/appraisal_terminal_declined_lockdown
    """
    customer = create_customer(full_name="Tara Term", email="tara@x.com")
    appraisal = create_offered_appraisal(customer["id"], 0, 0.0,
                                         category="DIGITAL", manufacturer="Roland",
                                         model="RD88", year_built=2022,
                                         condition_grade="EXCELLENT")
    headers = make_customer_headers(customer["id"])
    validate_success(api.decline_appraisal(appraisal["id"], headers), 200)

    res = api.accept_appraisal(appraisal["id"], headers)
    validate_error(res, "ERR_APPRAISAL_NOT_OFFERED")
    after = validate_success(api.get_trade_in_appraisal(appraisal["id"], headers), 200)
    assert after["status"] == "DECLINED", "terminal DECLINED accepts no further transitions"


def test_appraisal_lazy_expiry_after_fourteen_days(api):
    """PRD §3.2: "An offer lives for fourteen days from `offered_at`."
    PRD §3.2: "If an accept or counter arrives after the fourteenth day, the appraisal flips
    lazily to `EXPIRED` and the request fails with `ERR_APPRAISAL_EXPIRED` (HTTP 409)."

    Design: Corner/state_machines/appraisal_lazy_expiry_after_fourteen_days
    """
    customer = create_customer(full_name="Eli Expire", email="eli@x.com")
    appraisal = create_offered_appraisal(customer["id"], 0, 0.0,
                                         category="UPRIGHT", manufacturer="Kawai",
                                         model="K300", year_built=2016,
                                         condition_grade="EXCELLENT")
    set_clock("2026-05-16T00:00:00Z")  # 15 days after the offer at the default 2026-05-01
    res = api.accept_appraisal(appraisal["id"], make_customer_headers(customer["id"]))
    validate_error(res, "ERR_APPRAISAL_EXPIRED")
    after = validate_success(api.get_trade_in_appraisal(
        appraisal["id"], make_customer_headers(customer["id"])), 200)
    assert after["status"] == "EXPIRED", "lazy expiry flips the appraisal to EXPIRED"
