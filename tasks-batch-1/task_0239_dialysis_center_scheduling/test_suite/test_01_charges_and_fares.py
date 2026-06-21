"""Pricing and fare calculations: session charge variants, transport fare tiers,
and the per-session-rounded statement rollup.

Difficulty queue (A): dual_variant_calc, combinatorial_formula.
Corner queue (B): calculations section, consistency_model.
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    setup_bookable_scenario, book_and_check_in, book_complete_bill,
    create_transport_trip_payload, create_statement_payload,
    TEST_USERS,
)

SCHED = TEST_USERS["scheduler_headers"]
BILL = TEST_USERS["billing_clerk_headers"]
NEPH = TEST_USERS["nephrologist_headers"]


# ─── dual_variant_calc / session_charge_contracted_vs_standard ────────────
def test_session_charge_contracted_patient_discounted(api):
    """PRD §3.6: "That gross is then adjusted by the patient's `payer_class`: for
    a `CONTRACTED` patient the gross is multiplied by 0.82 (the in-network
    discount), and for a `STANDARD` patient the gross is taken at full value,
    multiplied by 1.00. The product is rounded once to whole cents using
    round-half-up to yield `billed_amount_cents`."
    PRD §3.6: "a base amount selected by the order's `modality` — 28,500 cents
    for `HEMODIALYSIS`, 34,000 cents for `HEMODIAFILTRATION`, and 22,000 cents
    for `PERITONEAL`"

    Design: Difficulty/dual_variant_calc/session_charge_contracted_vs_standard
    """
    scenario = setup_bookable_scenario(modality="HEMODIALYSIS", dialyzer_reuse_limit=12,
                                       payer_class="CONTRACTED", coinsurance_pct=0.0,
                                       order_overrides={"epo_units": 0, "iron_ordered": False})
    session = book_and_check_in(scenario)
    completed = validate_success(api.complete_session(session["id"], SCHED), 200)
    # gross 28500 * 0.82 = 23370.0 -> 23370
    assert completed["billed_amount_cents"] == 23370, \
        f"CONTRACTED HD should bill 23370, got {completed['billed_amount_cents']}"


def test_session_charge_standard_patient_full_price(api):
    """PRD §3.6: "for a `STANDARD` patient the gross is taken at full value,
    multiplied by 1.00. The product is rounded once to whole cents using
    round-half-up to yield `billed_amount_cents`."

    Design: Difficulty/dual_variant_calc/session_charge_contracted_vs_standard
    """
    scenario = setup_bookable_scenario(modality="HEMODIALYSIS", dialyzer_reuse_limit=12,
                                       payer_class="STANDARD", coinsurance_pct=0.0,
                                       order_overrides={"epo_units": 0, "iron_ordered": False})
    session = book_and_check_in(scenario)
    completed = validate_success(api.complete_session(session["id"], SCHED), 200)
    # gross 28500 * 1.00 = 28500 (variant delta 5130 vs contracted)
    assert completed["billed_amount_cents"] == 28500, \
        f"STANDARD HD should bill 28500, got {completed['billed_amount_cents']}"


# ─── Corner: calculations / session_charge_standard_with_addons ───────────
def test_session_charge_standard_with_epo_and_iron_addons(api):
    """PRD §3.6: "plus an EPO add-on of 1,200 cents for each whole 1,000-unit
    block of the order's `epo_units` (the number of `epo_units` divided by 1,000
    discarding any remainder, multiplied by 1,200 cents), plus a flat iron add-on
    of 4,500 cents when `iron_ordered` is true and 0 otherwise."

    Design: Corner/calculations/session_charge_standard_with_addons
    """
    scenario = setup_bookable_scenario(modality="HEMODIALYSIS", dialyzer_reuse_limit=12,
                                       payer_class="STANDARD", coinsurance_pct=0.0,
                                       order_overrides={"epo_units": 4000, "iron_ordered": True})
    session = book_and_check_in(scenario)
    completed = validate_success(api.complete_session(session["id"], SCHED), 200)
    # 28500 + 4*1200 + 4500 = 37800
    assert completed["billed_amount_cents"] == 37800, \
        f"expected 37800, got {completed['billed_amount_cents']}"


# ─── Corner: consistency_model / immediate_visibility_of_billed_amount ────
def test_billed_amount_present_in_complete_response(api):
    """PRD §3.6: "Completion is where money is first recognized. The session's
    `billed_amount_cents` is computed by the session charge rule."
    PRD §3.6: "Completing the session moves it `CHECKED_IN → COMPLETED`, which is
    terminal on the clinical axis."

    Design: Corner/consistency_model/immediate_visibility_of_billed_amount
    """
    scenario = setup_bookable_scenario(modality="HEMODIALYSIS", dialyzer_reuse_limit=12,
                                       payer_class="STANDARD", coinsurance_pct=0.0)
    session = book_and_check_in(scenario)
    completed = validate_success(api.complete_session(session["id"], SCHED), 200)
    assert completed["billed_amount_cents"] == 28500
    assert completed["clinical_status"] == "COMPLETED"


# ─── combinatorial_formula / transport_fare_tiered_with_pinned_multiplier ─
def test_transport_fare_full_combination_pinned_order(api):
    """PRD §3.8: "the first 5 miles cost 250 cents per mile, the next 10 miles
    (miles beyond 5 up to 15) cost 200 cents per mile, and every mile beyond 15
    costs 150 cents per mile. A base flag-drop of 800 cents is added to the
    mileage charge to form a subtotal. If `shared_ride` is true, that subtotal is
    multiplied by 0.75; otherwise it is multiplied by 1. This product ... is
    rounded once to whole cents using round-half-up. Only after that rounding are
    the flat add-ons applied: 1,500 cents is added when `wheelchair` is true, and
    500 cents is added when `cross_county` is true."

    Design: Difficulty/combinatorial_formula/transport_fare_tiered_with_pinned_multiplier_order
    """
    scenario = setup_bookable_scenario(coinsurance_pct=0.0)
    session = scenario_session(api, scenario)
    trip = validate_success(api.create_transport_trip(
        create_transport_trip_payload(session["id"], direction="INBOUND", miles=12,
                                       cross_county=True, wheelchair=True, shared_ride=True),
        SCHED), 201)
    # mileage: 5*250 + 7*200 = 1250 + 1400 = 2650; +800 base = 3450
    # *0.75 = 2587.5 -> round 2588; + 1500 wheelchair + 500 cross_county = 4588
    assert trip["fare_cents"] == 4588, f"expected 4588, got {trip['fare_cents']}"


def test_transport_fare_plain_trip_no_surcharges(api):
    """PRD §3.8: "the first 5 miles cost 250 cents per mile, the next 10 miles
    (miles beyond 5 up to 15) cost 200 cents per mile ... A base flag-drop of 800
    cents is added to the mileage charge to form a subtotal."
    PRD §3.8: "If `shared_ride` is true, that subtotal is multiplied by 0.75;
    otherwise it is multiplied by 1."

    Design: Difficulty/combinatorial_formula/transport_fare_tiered_with_pinned_multiplier_order
    """
    scenario = setup_bookable_scenario(coinsurance_pct=0.0)
    session = scenario_session(api, scenario)
    trip = validate_success(api.create_transport_trip(
        create_transport_trip_payload(session["id"], direction="INBOUND", miles=8),
        SCHED), 201)
    # mileage: 5*250 + 3*200 = 1250 + 600 = 1850; +800 = 2650; *1; no add-ons
    assert trip["fare_cents"] == 2650, f"expected 2650, got {trip['fare_cents']}"


# ─── Corner: calculations / transport_fare_shared_discount_rounding ───────
def test_transport_fare_shared_discount_rounds_half_up(api):
    """PRD §3.8: "If `shared_ride` is true, that subtotal is multiplied by 0.75 ...
    This product — the base-plus-mileage subtotal after the shared multiplier — is
    rounded once to whole cents using round-half-up."

    Design: Corner/calculations/transport_fare_shared_discount_rounding
    """
    scenario = setup_bookable_scenario(coinsurance_pct=0.0)
    session = scenario_session(api, scenario)
    trip = validate_success(api.create_transport_trip(
        create_transport_trip_payload(session["id"], direction="INBOUND", miles=12,
                                       shared_ride=True),
        SCHED), 201)
    # 5*250 + 7*200 = 2650; +800 = 3450; *0.75 = 2587.5 -> 2588 (half-up); no add-ons
    assert trip["fare_cents"] == 2588, f"expected 2588, got {trip['fare_cents']}"


# ─── combinatorial_formula / statement_rollup_per_session_round_then_sum ──
def test_statement_coinsurance_rounds_per_session_then_sums(api):
    """PRD §3.10: "The `coinsurance_due_cents` is the sum, over exactly those
    included sessions, of each session's `billed_amount_cents` multiplied by the
    patient's `coinsurance_pct` and rounded half-up to whole cents per session
    before summing — the rounding is pinned to happen per session and then sum,
    never sum-then-round."
    PRD §3.10: "The `session_count` is the number of the patient's sessions whose
    `clinical_status` is `COMPLETED`, whose `billing_status` is `BILLED` at run
    time, and whose `service_date` falls inside the `period_month`."

    Design: Difficulty/combinatorial_formula/statement_rollup_per_session_round_then_sum
    """
    scenario = setup_bookable_scenario(modality="HEMODIALYSIS", dialyzer_reuse_limit=99,
                                       payer_class="STANDARD", coinsurance_pct=0.125,
                                       order_overrides={"epo_units": 0})
    order_id = scenario["order"]["id"]
    patient_id = scenario["patient"]["id"]

    # Session 1: epo 0 -> billed 28500
    book_complete_bill(scenario, service_date="2026-06-01")
    # Revise order to epo 1000 -> billed 29700
    api.open_revision(order_id, NEPH)
    api.commit_revision(order_id, NEPH, {"epo_units": 1000})
    book_complete_bill(scenario, service_date="2026-06-03")
    # Revise order to epo 2000 -> billed 30900
    api.open_revision(order_id, NEPH)
    api.commit_revision(order_id, NEPH, {"epo_units": 2000})
    book_complete_bill(scenario, service_date="2026-06-05")

    statement = validate_success(api.create_statement(
        create_statement_payload(patient_id, period_month="2026-06"), BILL), 201)
    # per-session: round(28500*.125)=3563, round(29700*.125)=3713, round(30900*.125)=3863
    # sum = 11139 (sum-then-round would be 11138)
    assert statement["coinsurance_due_cents"] == 11139, \
        f"expected 11139 (per-session round-then-sum), got {statement['coinsurance_due_cents']}"
    assert statement["session_count"] == 3, \
        f"expected session_count 3, got {statement['session_count']}"


def test_statement_total_due_sums_coinsurance_and_missed_fees(api):
    """PRD §3.10: "The `total_due_cents` is the `coinsurance_due_cents` plus the
    `missed_fee_total_cents`."
    PRD §3.10: "The `missed_fee_total_cents` is the sum of `missed_fee_cents` over
    the patient's sessions whose `clinical_status` is `MISSED` and whose
    `service_date` falls inside the `period_month`."

    Design: Difficulty/combinatorial_formula/statement_rollup_per_session_round_then_sum
    """
    from test_helpers import book_session
    scenario = setup_bookable_scenario(modality="HEMODIALYSIS", dialyzer_reuse_limit=99,
                                       payer_class="STANDARD", coinsurance_pct=0.125,
                                       order_overrides={"epo_units": 0})
    patient_id = scenario["patient"]["id"]
    # One COMPLETED+BILLED session (billed 28500, coinsurance round(3562.5)=3563)
    book_complete_bill(scenario, service_date="2026-06-01")
    # One MISSED session in the same period (missed_fee 7500)
    missed = book_session(scenario, service_date="2026-06-03")
    api.mark_missed_session(missed["id"], SCHED)

    statement = validate_success(api.create_statement(
        create_statement_payload(patient_id, period_month="2026-06"), BILL), 201)
    assert statement["coinsurance_due_cents"] == 3563
    assert statement["missed_fee_total_cents"] == 7500
    # total_due = 3563 + 7500
    assert statement["total_due_cents"] == 11063, \
        f"expected total_due 11063, got {statement['total_due_cents']}"


# ─── shared helper used by transport tests ────────────────────────────────
def scenario_session(api, scenario, service_date="2026-06-01"):
    """Book one BOOKED session for the scenario's patient using the live version."""
    patient = scenario["patient"]
    pv = get_success_data(api.get_patient(patient["id"], SCHED))["version"]
    from test_helpers import create_session_payload
    payload = create_session_payload(
        patient["id"], scenario["order"]["id"], scenario["station"]["id"],
        scenario["shift"]["id"], service_date, pv)
    return validate_success(api.create_session(payload, SCHED), 201)
