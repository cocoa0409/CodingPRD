"""Claim adjudication: provisional vs final copay, cumulative annual cap,
copay floor, cash patient, immediate-consistency, computed read.

Translations of queue A dual_variant_calc / combinatorial_formula (copay) and
queue B calculations / endpoints / consistency_model instances.
"""
from test_helpers import (
    validate_success, validate_paginated, TEST_USERS, submit_claim_payload,
)
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]
TECH = TEST_USERS["technician_headers"]
PHARM = TEST_USERS["pharmacist_headers"]
CASH = TEST_USERS["cashier_headers"]


# ---------------------------------------------------------------------------
# Queue A — dual-variant copay divergence (two tests)
# ---------------------------------------------------------------------------
def _build_planB_second_fill(bin_, pcn_, ndc_):
    """Plan B (copay 0.20, max 4000), drug 800/unit allowed 600/unit. First fill
    DISPENSED with final_copay 3620; clock advanced 30 days; second fill created
    and run-dur'd up to ADJUDICATING. Returns (rx, f2_id)."""
    fx.set_clock("2026-01-01T00:00:00.000Z")
    plan = fx.create_plan(bin=bin_, pcn=pcn_, name="Plan B", copay_pct=0.20,
                          copay_min_cents=500, copay_max_cents=4000,
                          dispensing_fee_cents=100, refill_too_soon_threshold_pct=0.80)
    drug = fx.create_drug(ndc=ndc_, name="Alpha", unit_price_cents=800)
    fx.create_formulary(plan["id"], drug["id"], tier=2, allowed_amount_cents=600)
    patient = fx.create_patient(plan_id=plan["id"], full_name="Pat One",
                                date_of_birth="1980-01-01")
    prescriber = fx.create_prescriber(full_name="Dr A", npi=f"10000{ndc_[-5:-3]}001")
    rx = fx.create_prescription(patient["id"], prescriber["id"], drug["id"],
                                quantity_per_fill=30, days_supply=30,
                                refills_authorized=2, written_utc="2026-01-01T00:00:00.000Z")
    # First fill all the way to DISPENSED (final_copay 3620).
    fx.create_and_dispense_fill(rx["id"], 3620)
    # Advance clock past refill-too-soon, create second fill up to ADJUDICATING.
    fx.set_clock("2026-02-01T00:00:00.000Z")
    f2 = fx.create_fill_at_adjudicating(rx["id"])
    return rx, f2["id"]


def test_copay_provisional_vs_final_diverge_on_second_fill(api):
    """PRD §3.6: "Crucially, the provisional estimate applies `copay_max_cents`
    as a per-fill ceiling."
    PRD §3.6: "Because the provisional figure caps each fill independently while
    the final figure draws down a shared annual cap, on a patient's second and
    later fills — once earlier copays have neared the annual maximum — the
    provisional and final copays diverge."

    Design: Difficulty/dual_variant_calc/copay_provisional_vs_final_diverge_on_second_fill
    """
    rx, f2_id = _build_planB_second_fill("610001", "PB", "00000-0001-01")
    v = fx.get_rx_version(rx["id"])
    resp = api.submit_claim(f2_id, submit_claim_payload(v), TECH)
    data = validate_success(resp)
    assert data["provisional_copay_cents"] == 3620, \
        f"provisional (per-fill cap) must be 3620, got {data['provisional_copay_cents']}"
    assert data["final_copay_cents"] == 380, \
        f"final (annual cap 4000-3620) must be 380, got {data['final_copay_cents']}"
    assert data["plan_paid_cents"] == 17720, \
        f"plan_paid must be 17720, got {data['plan_paid_cents']}"


def test_final_copay_cumulative_cap_order_pinned_accumulation(api):
    """PRD §3.6: "The system then sums the `final_copay_cents` already contributed
    by the patient's earlier fills on the same plan ... totals their final copays
    to get the prior out-of-pocket. The remaining annual room is the plan's
    `copay_max_cents` minus that prior out-of-pocket, but never less than zero.
    The fill's `final_copay_cents` is the smaller of the current fill's tentative
    copay and that remaining room".

    Design: Difficulty/combinatorial_formula/final_copay_cumulative_cap_order_pinned_accumulation
    """
    rx, f2_id = _build_planB_second_fill("610004", "PB2", "00000-0004-01")
    # First fill's final copay must have been 3620.
    fills, _ = validate_paginated(api.list_fills(TECH, params={"prescription_id": rx["id"]}))
    first = [f for f in fills if f["fill_sequence"] == 1][0]
    assert first["final_copay_cents"] == 3620, \
        f"first fill final must be 3620, got {first['final_copay_cents']}"
    v = fx.get_rx_version(rx["id"])
    data = validate_success(api.submit_claim(f2_id, submit_claim_payload(v), TECH))
    assert data["final_copay_cents"] == 380, \
        f"second fill final (capped at 4000-3620) must be 380, got {data['final_copay_cents']}"


def test_first_fill_copay_provisional_equals_final_before_cap(api):
    """PRD §3.6: "The **provisional** copay is a forward-looking estimate computed
    at submission from the static formulary allowed amount, ignoring the patient's
    prior fills."
    PRD §3.6: "The **final** copay is the adjudicated, chronological figure locked
    when the claim pays".

    Design: Difficulty/dual_variant_calc/copay_provisional_vs_final_diverge_on_second_fill
    """
    # On the FIRST fill there is no prior out-of-pocket, so provisional and final
    # agree (both 3620) — the divergence only appears on the second fill.
    fx.set_clock("2026-01-01T00:00:00.000Z")
    plan = fx.create_plan(bin="610021", pcn="PB3", name="Plan B3", copay_pct=0.20,
                          copay_min_cents=500, copay_max_cents=4000,
                          dispensing_fee_cents=100, refill_too_soon_threshold_pct=0.80)
    drug = fx.create_drug(ndc="00000-0021-01", name="AlphaF", unit_price_cents=800)
    fx.create_formulary(plan["id"], drug["id"], tier=2, allowed_amount_cents=600)
    patient = fx.create_patient(plan_id=plan["id"], full_name="Pat F1",
                                date_of_birth="1980-01-01")
    prescriber = fx.create_prescriber(full_name="Dr AF", npi="1000021001")
    rx = fx.create_prescription(patient["id"], prescriber["id"], drug["id"],
                                quantity_per_fill=30, days_supply=30,
                                refills_authorized=2, written_utc="2026-01-01T00:00:00.000Z")
    fill = fx.create_fill_at_adjudicating(rx["id"])
    v = fx.get_rx_version(rx["id"])
    data = validate_success(api.submit_claim(fill["id"], submit_claim_payload(v), TECH))
    # allowed_total = 600*30 + 100 = 18100; raw = round(18100*0.20) = 3620;
    # provisional cap (per-fill) and final cap (4000 - 0 prior) both leave 3620.
    assert data["provisional_copay_cents"] == 3620
    assert data["final_copay_cents"] == 3620


def test_final_copay_second_fill_draws_down_remaining_annual_room(api):
    """PRD §3.6: "The remaining annual room is the plan's `copay_max_cents` minus
    that prior out-of-pocket, but never less than zero. The fill's
    `final_copay_cents` is the smaller of the current fill's tentative copay and
    that remaining room, and `plan_paid_cents` is the allowed total minus
    `final_copay_cents`."

    Design: Difficulty/combinatorial_formula/final_copay_cumulative_cap_order_pinned_accumulation
    """
    rx, f2_id = _build_planB_second_fill("610022", "PB4", "00000-0022-01")
    v = fx.get_rx_version(rx["id"])
    data = validate_success(api.submit_claim(f2_id, submit_claim_payload(v), TECH))
    # remaining room = 4000 - 3620 = 380; plan_paid = 18100 - 380 = 17720.
    assert data["final_copay_cents"] == 380
    assert data["plan_paid_cents"] == 17720


# ---------------------------------------------------------------------------
# Queue B — copay constants / variants / reads
# ---------------------------------------------------------------------------
def test_provisional_copay_min_floor_applied(api):
    """PRD §3.6: "clamping that figure to lie at or above the plan's
    `copay_min_cents` and at or below the plan's `copay_max_cents`."

    Design: Corner/calculations/provisional_copay_min_floor_applied
    """
    fx.set_clock()
    plan = fx.create_plan(bin="700004", pcn="CD", name="Floor Plan", copay_pct=0.10,
                          copay_min_cents=500, copay_max_cents=10000, dispensing_fee_cents=100)
    drug = fx.create_drug(ndc="77777-0009-01", name="FloorDrug", unit_price_cents=800)
    fx.create_formulary(plan["id"], drug["id"], tier=1, allowed_amount_cents=500)
    patient = fx.create_patient(plan_id=plan["id"], full_name="Floor P",
                                date_of_birth="1980-01-01")
    prescriber = fx.create_prescriber(full_name="Dr Floor", npi="2000000018")
    rx = fx.create_prescription(patient["id"], prescriber["id"], drug["id"],
                                quantity_per_fill=1, days_supply=30)
    fill = fx.create_fill_at_adjudicating(rx["id"])
    v = fx.get_rx_version(rx["id"])
    data = validate_success(api.submit_claim(fill["id"], submit_claim_payload(v), TECH))
    # allowed_total = 500*1 + 100 = 600; raw = round(600*0.10)=60 -> floored to 500.
    assert data["provisional_copay_cents"] == 500
    assert data["final_copay_cents"] == 500


def test_cash_patient_copay_equals_gross(api):
    """PRD §3.6: "For a cash patient (one whose `plan_id` is null) both copay
    variants collapse to the same simple rule: there is no formulary lookup, the
    `provisional_copay_cents` and the `final_copay_cents` are both set equal to
    `gross_amount_cents`, and `plan_paid_cents` is 0."

    Design: Corner/calculations/cash_patient_copay_equals_gross
    """
    fx.set_clock()
    drug = fx.create_drug(ndc="77777-0010-01", name="CashDrug", unit_price_cents=800)
    patient = fx.create_patient(full_name="Cash P", date_of_birth="1980-01-01")
    prescriber = fx.create_prescriber(full_name="Dr Cash", npi="2000000019")
    rx = fx.create_prescription(patient["id"], prescriber["id"], drug["id"],
                                quantity_per_fill=10, days_supply=30)
    fill = fx.create_fill_at_adjudicating(rx["id"])
    v = fx.get_rx_version(rx["id"])
    data = validate_success(api.submit_claim(fill["id"], submit_claim_payload(v), TECH))
    assert data["provisional_copay_cents"] == 8000  # 800*10
    assert data["final_copay_cents"] == 8000
    assert data["plan_paid_cents"] == 0


def test_computed_read_fill_exposes_copays(api):
    """PRD §3.4: "an individual fetch returns the fill's `claim_status`, its copay
    fields, and its `dur_severity`."

    Design: Corner/endpoints/computed_read_fill_exposes_copays
    """
    fx.set_clock()
    plan = fx.create_plan(bin="700012", pcn="CL", name="Read Plan", copay_pct=0.20,
                          copay_min_cents=500, copay_max_cents=10000, dispensing_fee_cents=100)
    drug = fx.create_drug(ndc="77777-0023-01", name="ReadDrug", unit_price_cents=800)
    fx.create_formulary(plan["id"], drug["id"], tier=2, allowed_amount_cents=600)
    patient = fx.create_patient(plan_id=plan["id"], full_name="Read P",
                                date_of_birth="1980-01-01")
    prescriber = fx.create_prescriber(full_name="Dr Read", npi="2000000031")
    rx = fx.create_prescription(patient["id"], prescriber["id"], drug["id"],
                                quantity_per_fill=30, days_supply=30)
    fill = fx.create_fill_paid(rx["id"])
    data = validate_success(api.get_fill(fill["id"], PHARM))
    # allowed_total = 600*30 + 100 = 18100; raw = round(18100*0.20)=3620.
    assert data["provisional_copay_cents"] == 3620
    assert data["final_copay_cents"] == 3620
    assert data["plan_paid_cents"] == 14480


def test_immediate_consistency_copay_visible_in_submit_response(api):
    """PRD §3.6: "On the pay branch the fill transitions from `ADJUDICATING` to
    `READY_FILL`, the system computes the copays described below, sets the fill's
    `claim_status` to `PAID`".

    Design: Corner/consistency_model/immediate_consistency_copay_visible_in_submit_response
    """
    fx.set_clock()
    plan = fx.create_plan(bin="700018", pcn="CR", name="Imm Plan", copay_pct=0.20,
                          copay_min_cents=500, copay_max_cents=10000, dispensing_fee_cents=100)
    drug = fx.create_drug(ndc="77777-0032-01", name="ImmDrug", unit_price_cents=800)
    fx.create_formulary(plan["id"], drug["id"], tier=2, allowed_amount_cents=600)
    patient = fx.create_patient(plan_id=plan["id"], full_name="Imm P",
                                date_of_birth="1980-01-01")
    prescriber = fx.create_prescriber(full_name="Dr Imm", npi="2000000040")
    rx = fx.create_prescription(patient["id"], prescriber["id"], drug["id"],
                                quantity_per_fill=30, days_supply=30)
    fill = fx.create_fill_at_adjudicating(rx["id"])
    v = fx.get_rx_version(rx["id"])
    data = validate_success(api.submit_claim(fill["id"], submit_claim_payload(v), TECH))
    assert data["final_copay_cents"] == 3620
    assert data["status"] == "READY_FILL"
