"""Self-pay financing: round-then-split schedule math, pathway gating, fiscal limit,
and optimistic concurrency.

Covers difficulty queue A (financing schedule rounding order, NOT_SELF_PAY precedence)
and corner queue B (down-payment fiscal limit, stale program version).
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_cleared_self_pay_program, create_program_for_new_patient, create_insurance_plan,
    program_version,
    create_financing_plan_payload,
)

PC = TEST_USERS["program_coordinator_headers"]
BILL = TEST_USERS["billing_specialist_headers"]


# ---------------- Difficulty A: financing schedule round-then-split ----------------

def test_financing_interest_rounded_once_over_principal(api):
    """PRD §3.8: "interest_cents is computed once over the whole principal — the
    principal multiplied by the APR as a fraction (basis points divided by 10,000)
    multiplied by the term expressed in years (term_months divided by 12) — and that
    single product is rounded half-up to whole cents."

    Design: Difficulty/combinatorial_formula/financing_schedule_round_then_split
    """
    prog = create_cleared_self_pay_program(api)  # FEMALE 170/120 => bundle 1944000
    v = program_version(api, prog["id"])
    data = validate_success(api.create_financing_plan(
        prog["id"],
        create_financing_plan_payload(v, procedure_type="SLEEVE_GASTRECTOMY",
                                      down_payment_cents=400000, term_months=12, apr_bps=1200),
        BILL), expected_status=201)
    assert data["bundle_price_cents"] == 1944000, f"expected 1944000, got {data['bundle_price_cents']}"
    assert data["interest_cents"] == 185280, f"expected 185280, got {data['interest_cents']}"


def test_financing_installments_waterfall_remainder(api):
    """PRD §3.8: "The per-installment amount, installment_cents, is the financed total
    divided by the number of months and rounded down to whole cents (the floor) ... The
    final_installment_cents absorbs the rounding remainder and is the financed total minus
    the per-installment amount times the count of all-but-the-last installments."

    Design: Difficulty/combinatorial_formula/financing_schedule_round_then_split
    """
    prog = create_cleared_self_pay_program(api)
    v = program_version(api, prog["id"])
    data = validate_success(api.create_financing_plan(
        prog["id"],
        create_financing_plan_payload(v, procedure_type="SLEEVE_GASTRECTOMY",
                                      down_payment_cents=400000, term_months=12, apr_bps=1200),
        BILL), expected_status=201)
    assert data["installment_cents"] == 144106, f"expected 144106, got {data['installment_cents']}"
    assert data["final_installment_cents"] == 144114, f"expected 144114, got {data['final_installment_cents']}"


# ---------------- Difficulty A: NOT_SELF_PAY beats DOWN_PAYMENT_EXCEEDS ----------------

def test_financing_on_insurance_returns_not_self_pay(api):
    """PRD §3.8: "Financing is available only when the program's payment_pathway is
    SELF_PAY; requesting a plan on an insurance program is rejected with ERR_NOT_SELF_PAY
    (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/financing_not_self_pay_beats_down_payment_exceeds
    """
    plan = create_insurance_plan(api, required_supervised_diet_months=3)
    prog = create_program_for_new_patient(api, payment_pathway="INSURANCE",
                                          insurance_plan_id=plan["id"])
    v = program_version(api, prog["id"])
    resp = api.create_financing_plan(
        prog["id"],
        create_financing_plan_payload(v, procedure_type="SLEEVE_GASTRECTOMY",
                                      down_payment_cents=99999999, term_months=12, apr_bps=1200),
        BILL)
    validate_error(resp, ApiErrorId.ERR_NOT_SELF_PAY.value)


def test_financing_on_insurance_creates_no_plan(api):
    """PRD §3.8: "requesting a plan on an insurance program is rejected with
    ERR_NOT_SELF_PAY (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/financing_not_self_pay_beats_down_payment_exceeds
    """
    plan = create_insurance_plan(api, required_supervised_diet_months=3)
    prog = create_program_for_new_patient(api, payment_pathway="INSURANCE",
                                          insurance_plan_id=plan["id"])
    v = program_version(api, prog["id"])
    api.create_financing_plan(
        prog["id"],
        create_financing_plan_payload(v, procedure_type="SLEEVE_GASTRECTOMY",
                                      down_payment_cents=99999999, term_months=12, apr_bps=1200),
        BILL)
    plans = validate_success(api.list_financing_plans(prog["id"], BILL))
    assert plans == [], f"no financing plan may be created for an insurance program, got {plans}"


# ---------------- Corner B: fiscal limit ----------------

def test_down_payment_exceeds_bundle_returns_422(api):
    """PRD §3.8: "The collected down payment may not exceed this bundle price; a
    down_payment_cents greater than the computed bundle_price_cents is rejected with
    ERR_DOWN_PAYMENT_EXCEEDS_BUNDLE (HTTP 422)."

    Design: Corner/validations/down_payment_exceeds_bundle_returns_422
    """
    prog = create_program_for_new_patient(api, payment_pathway="SELF_PAY")  # bundle 1944000
    v = program_version(api, prog["id"])
    resp = api.create_financing_plan(
        prog["id"],
        create_financing_plan_payload(v, procedure_type="SLEEVE_GASTRECTOMY",
                                      down_payment_cents=99999999, term_months=12, apr_bps=1200),
        BILL)
    validate_error(resp, ApiErrorId.ERR_DOWN_PAYMENT_EXCEEDS_BUNDLE.value)


# ---------------- Corner B: optimistic concurrency ----------------

def test_financing_stale_program_version_returns_412(api):
    """PRD §2.5 / §3.8: "If expected_program_version does not match the program's current
    version — for instance, because an earlier plan creation already bumped the version
    after the client last read it — the request is rejected with ERR_STALE_PROGRAM_VERSION
    (HTTP 412)."

    Design: Corner/errors/financing_stale_program_version_returns_412
    """
    prog = create_program_for_new_patient(api, payment_pathway="SELF_PAY")
    v0 = program_version(api, prog["id"])
    validate_success(api.create_financing_plan(
        prog["id"],
        create_financing_plan_payload(v0, procedure_type="SLEEVE_GASTRECTOMY",
                                      down_payment_cents=100000, term_months=12, apr_bps=1200),
        BILL), expected_status=201)
    # Second create carries the pre-advance version -> stale.
    resp = api.create_financing_plan(
        prog["id"],
        create_financing_plan_payload(v0, procedure_type="SLEEVE_GASTRECTOMY",
                                      down_payment_cents=100000, term_months=12, apr_bps=1200),
        BILL)
    validate_error(resp, ApiErrorId.ERR_STALE_PROGRAM_VERSION.value)
