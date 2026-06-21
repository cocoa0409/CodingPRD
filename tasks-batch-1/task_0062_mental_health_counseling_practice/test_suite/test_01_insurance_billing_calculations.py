"""Insurance adjudication: allowed-amount variant, rounding order, deductible split.

Queue A (Difficulty): dual_variant_calc, combinatorial_formula, transitive_cascade.
Queue B (Corner): calculations, cross_cutting_complexity_layers (reconciliation).
"""
from test_helpers import (
    api_client, validate_success, get_success_data,
    setup_submitted_claim, adjudicate, TEST_USERS,
)

BILLER = TEST_USERS["biller_headers"]


def _adjudicated_claim(ctx):
    claim = ctx["claim"]
    return adjudicate(claim["id"], claim["version"])


def test_in_network_allowed_amount_caps_at_contracted_rate():
    """PRD §2.11: "If the governing payer contract is in-network, the allowed amount
    is the smaller of that billed charge and the contract's contracted rate for the
    same code; if the payer is out-of-network, the allowed amount equals the full
    billed charge with no contracted cap."
    PRD §2.11: "Under a coinsurance model, the cost share is the post-deductible
    remainder multiplied by the coinsurance fraction, rounded half up to the nearest cent."

    Design: Difficulty/dual_variant_calc/insurance_allowed_in_network_vs_out_of_network
    """
    ctx = setup_submitted_claim(
        clock="2026-06-01T09:00:00Z", appt_start="2026-06-01T08:00:00Z",
        cpt_code="90834", duration_minutes=45, in_network=True, rate_90834=13000,
        cost_share_model="COINSURANCE", copay_cents=None, coinsurance_rate=0.20,
        deductible_total_cents=0)
    claim = _adjudicated_claim(ctx)
    assert claim["allowed_amount_cents"] == 13000
    assert claim["patient_responsibility_cents"] == 2600


def test_out_of_network_allowed_amount_uses_full_billed_charge():
    """PRD §2.11: "If the governing payer contract is in-network, the allowed amount
    is the smaller of that billed charge and the contract's contracted rate for the
    same code; if the payer is out-of-network, the allowed amount equals the full
    billed charge with no contracted cap."
    PRD §2.11: "Under a coinsurance model, the cost share is the post-deductible
    remainder multiplied by the coinsurance fraction, rounded half up to the nearest cent."

    Design: Difficulty/dual_variant_calc/insurance_allowed_in_network_vs_out_of_network
    """
    ctx = setup_submitted_claim(
        clock="2026-06-01T09:00:00Z", appt_start="2026-06-01T08:00:00Z",
        cpt_code="90834", duration_minutes=45, in_network=False, rate_90834=0,
        cost_share_model="COINSURANCE", copay_cents=None, coinsurance_rate=0.20,
        deductible_total_cents=0)
    claim = _adjudicated_claim(ctx)
    assert claim["allowed_amount_cents"] == 15000
    assert claim["patient_responsibility_cents"] == 3000


def test_deductible_first_then_rounded_coinsurance_order():
    """PRD §2.11: "From the allowed amount, the deductible is consumed first: the
    deductible applied is the smaller of the allowed amount and the policy's remaining
    deductible, where remaining deductible is the policy's total deductible minus the
    cents already met, floored at zero."
    PRD §2.11: "Under a coinsurance model, the cost share is the post-deductible
    remainder multiplied by the coinsurance fraction, rounded half up to the nearest cent."
    PRD §2.11: "The patient's total responsibility is the deductible applied plus the
    cost share, and the payer's payment is the allowed amount minus that patient
    responsibility."

    Design: Difficulty/combinatorial_formula/insurance_rounding_order_deductible_then_coinsurance
    """
    ctx = setup_submitted_claim(
        clock="2026-06-03T12:00:00Z", appt_start="2026-06-03T08:00:00Z",
        cpt_code="90834", duration_minutes=45, in_network=True, rate_90834=13333,
        cost_share_model="COINSURANCE", copay_cents=None, coinsurance_rate=0.175,
        deductible_total_cents=5000)
    # billed 15000, in-network cap 13333 -> allowed = min(15000, 13333) = 13333.
    # deductible = min(13333, 5000) = 5000; remainder = 8333.
    # cost share = round_half_up(8333 * 0.175) = round(1458.275) = 1458.
    # responsibility = 5000 + 1458 = 6458; payer = 13333 - 6458 = 6875.
    claim = _adjudicated_claim(ctx)
    assert claim["allowed_amount_cents"] == 13333
    assert claim["deductible_applied_cents"] == 5000
    assert claim["patient_responsibility_cents"] == 6458
    assert claim["payer_paid_cents"] == 6875


def test_coinsurance_rounded_half_up_on_post_deductible_remainder():
    """PRD §2.11: "Under a coinsurance model, the cost share is the post-deductible
    remainder multiplied by the coinsurance fraction, rounded half up to the nearest cent."
    PRD §2.11: "The patient's total responsibility is the deductible applied plus the
    cost share, and the payer's payment is the allowed amount minus that patient
    responsibility."

    Design: Difficulty/combinatorial_formula/insurance_rounding_order_deductible_then_coinsurance
    """
    # OON 90834 allowed 15000, deductible 0, coinsurance 0.175.
    # cost_share = round(15000 * 0.175) = round(2625.0) = 2625; resp = 2625; payer = 12375.
    ctx = setup_submitted_claim(
        clock="2026-06-03T13:00:00Z", appt_start="2026-06-03T08:00:00Z",
        cpt_code="90834", duration_minutes=45, in_network=False, rate_90834=0,
        cost_share_model="COINSURANCE", copay_cents=None, coinsurance_rate=0.175,
        deductible_total_cents=0)
    claim = _adjudicated_claim(ctx)
    assert claim["allowed_amount_cents"] == 15000
    assert claim["deductible_applied_cents"] == 0
    assert claim["patient_responsibility_cents"] == 2625
    assert claim["payer_paid_cents"] == 12375


def test_in_network_copay_caps_allowed_and_applies_copay():
    """PRD §2.11: "If the governing payer contract is in-network, the allowed amount
    is the smaller of that billed charge and the contract's contracted rate for the
    same code; if the payer is out-of-network, the allowed amount equals the full
    billed charge with no contracted cap."
    PRD §2.11: "Under a copay model, the cost share is the smaller of the fixed copay
    and that post-deductible remainder."

    Design: Corner/calculations/in_network_copay_deductible_met_split
    """
    ctx = setup_submitted_claim(
        clock="2026-07-07T12:00:00Z", appt_start="2026-07-07T08:00:00Z",
        cpt_code="90791", duration_minutes=60, in_network=True, rate_90791=18000,
        cost_share_model="COPAY", copay_cents=2500, deductible_total_cents=0)
    claim = _adjudicated_claim(ctx)
    assert claim["allowed_amount_cents"] == 18000
    assert claim["patient_responsibility_cents"] == 2500
    assert claim["payer_paid_cents"] == 15500


def test_adjudicate_cascade_deductible_and_appointment_charge():
    """PRD §3.7: "Adjudication then cascades: it increases the policy's
    deductible_met_cents by the deductible just applied, and it copies the computed
    patient responsibility onto the linked appointment's patient_charge_cents."
    PRD §2.11: "the deductible applied is the smaller of the allowed amount and the
    policy's remaining deductible, where remaining deductible is the policy's total
    deductible minus the cents already met, floored at zero."

    Design: Difficulty/transitive_cascade/claim_adjudicate_cascade_depth3
    """
    # Policy deductible_total 20000; a first in-network 90791 claim (contracted 18000)
    # is adjudicated, consuming min(18000, 20000) = 18000 of the deductible -> met 18000.
    # The 90834 claim under test then sees remaining deductible 2000 and applies it,
    # exercising the depth-3 cascade: claim ledger -> policy.deductible_met -> appt charge.
    from test_helpers import schedule_appointment, render_sign_complete
    ctx = setup_submitted_claim(
        clock="2026-06-06T12:00:00Z", appt_start="2026-06-06T03:00:00Z",
        cpt_code="90791", duration_minutes=60, in_network=True, rate_90791=18000,
        rate_90834=13000, cost_share_model="COINSURANCE", copay_cents=None,
        coinsurance_rate=0.20, deductible_total_cents=20000)
    therapist, patient, policy = ctx["therapist"], ctx["patient"], ctx["policy"]
    first = _adjudicated_claim(ctx)
    assert first["deductible_applied_cents"] == 18000  # met now 18000

    appt2 = schedule_appointment(
        therapist["id"], patient["id"], cpt_code="90834", duration_minutes=45,
        start_at="2026-06-06T08:00:00Z", payment_path="INSURANCE",
        insurance_policy_id=policy["id"])
    completed2 = render_sign_complete(appt2["id"], therapist["id"])
    claim2 = get_success_data(api_client.create_claim(
        {"appointment_id": completed2["id"],
         "expected_appointment_version": completed2["version"]}, BILLER))
    adj2 = adjudicate(claim2["id"], claim2["version"])
    # allowed=13000; remaining_ded=20000-18000=2000; applied=min(13000,2000)=2000
    # after_ded=13000-2000=11000; coins=round(11000*0.20)=2200; resp=2000+2200=4200
    assert adj2["deductible_applied_cents"] == 2000
    assert adj2["patient_responsibility_cents"] == 4200
    pol = get_success_data(api_client.get_insurance_policy(policy["id"], BILLER))
    assert pol["deductible_met_cents"] == 20000
    appt_after = get_success_data(api_client.get_appointment(completed2["id"], BILLER))
    assert appt_after["patient_charge_cents"] == 4200


def test_single_adjudication_cascades_through_three_hops():
    """PRD §3.7: "Adjudication then cascades: it increases the policy's
    deductible_met_cents by the deductible just applied, and it copies the computed
    patient responsibility onto the linked appointment's patient_charge_cents."

    Design: Difficulty/transitive_cascade/claim_adjudicate_cascade_depth3
    """
    # In-network 90834 (allowed 13000), deductible 5000, coinsurance 0.20.
    # Hop A: claim ledger stamped. Hop B: policy.deductible_met += 5000.
    # Hop C: appointment.patient_charge_cents := patient_responsibility.
    ctx = setup_submitted_claim(
        clock="2026-06-20T12:00:00Z", appt_start="2026-06-20T08:00:00Z",
        cpt_code="90834", duration_minutes=45, in_network=True, rate_90834=13000,
        cost_share_model="COINSURANCE", copay_cents=None, coinsurance_rate=0.20,
        deductible_total_cents=5000)
    policy = ctx["policy"]
    appt = ctx["appointment"]
    claim = ctx["claim"]
    adj = adjudicate(claim["id"], claim["version"])
    # applied=min(13000,5000)=5000; after_ded=8000; coins=round(8000*0.20)=1600; resp=6600
    assert adj["deductible_applied_cents"] == 5000
    assert adj["patient_responsibility_cents"] == 6600
    pol = get_success_data(api_client.get_insurance_policy(policy["id"], BILLER))
    assert pol["deductible_met_cents"] == 5000
    appt_after = get_success_data(api_client.get_appointment(appt["id"], BILLER))
    assert appt_after["patient_charge_cents"] == 6600


def test_deductible_reconciled_across_two_sequential_adjudications():
    """PRD §3.7: "Adjudication then cascades: it increases the policy's
    deductible_met_cents by the deductible just applied, and it copies the computed
    patient responsibility onto the linked appointment's patient_charge_cents."
    PRD §2.11: "the deductible applied is the smaller of the allowed amount and the
    policy's remaining deductible, where remaining deductible is the policy's total
    deductible minus the cents already met, floored at zero."

    Design: Corner/cross_cutting_complexity_layers/deductible_reconciliation_after_two_adjudications
    """
    ctx = setup_submitted_claim(
        clock="2026-07-16T12:00:00Z", appt_start="2026-07-16T03:00:00Z",
        cpt_code="90834", duration_minutes=45, in_network=True, rate_90834=13000,
        cost_share_model="COINSURANCE", copay_cents=None, coinsurance_rate=0.20,
        deductible_total_cents=20000)
    therapist, patient, policy = ctx["therapist"], ctx["patient"], ctx["policy"]
    claim1 = _adjudicated_claim(ctx)
    assert claim1["deductible_applied_cents"] == 13000

    from test_helpers import schedule_appointment, render_sign_complete
    appt2 = schedule_appointment(
        therapist["id"], patient["id"], cpt_code="90834", duration_minutes=45,
        start_at="2026-07-16T08:00:00Z", payment_path="INSURANCE",
        insurance_policy_id=policy["id"])
    completed2 = render_sign_complete(appt2["id"], therapist["id"])
    claim2 = get_success_data(api_client.create_claim(
        {"appointment_id": completed2["id"],
         "expected_appointment_version": completed2["version"]}, BILLER))
    adj2 = adjudicate(claim2["id"], claim2["version"])
    assert adj2["deductible_applied_cents"] == 7000
    assert adj2["patient_responsibility_cents"] == 8200
    pol = get_success_data(api_client.get_insurance_policy(policy["id"], BILLER))
    assert pol["deductible_met_cents"] == 20000


def test_self_pay_charge_stamped_at_render():
    """PRD §3.6: "On a successful render, a self-pay session has its
    patient_charge_cents stamped from the self-pay pricing calculation — the standard
    procedure rate (22,000 cents for 90791, 15,000 cents for 90834) multiplied by the
    patient's sliding_fee_multiplier, rounded half up to the nearest whole cent"

    Design: Corner/calculations/self_pay_charge_stamped_at_render
    """
    from test_helpers import create_independent_therapist, create_patient, \
        schedule_appointment, render_appointment, set_clock
    set_clock("2026-07-06T12:00:00Z")
    therapist = create_independent_therapist()
    # income 30000 / household 2 -> FPL 20440 -> 146.77% -> <=150 band -> 0.20
    patient = create_patient(income=30000, household=2)
    assert patient["sliding_fee_multiplier"] == 0.20
    appt = schedule_appointment(
        therapist["id"], patient["id"], cpt_code="90834", duration_minutes=45,
        start_at="2026-07-06T08:00:00Z", payment_path="SELF_PAY")
    rendered = render_appointment(appt["id"], therapist["id"])
    assert rendered["patient_charge_cents"] == 3000


def test_render_self_pay_charge_visible_in_same_response():
    """PRD §3.6: "On a successful render, a self-pay session has its
    patient_charge_cents stamped from the self-pay pricing calculation — the standard
    procedure rate (22,000 cents for 90791, 15,000 cents for 90834) multiplied by the
    patient's sliding_fee_multiplier, rounded half up to the nearest whole cent"
    PRD §2.4: "All such effects settle atomically within the single request that
    triggers them; the system never leaves a cascade half-applied."

    Design: Corner/consistency_model/render_self_pay_charge_visible_in_same_response
    """
    from test_helpers import create_licensed_associate, create_patient, \
        schedule_appointment, set_clock
    set_clock("2026-07-17T12:00:00Z")
    therapist = create_licensed_associate()
    patient = create_patient(income=30000, household=2)
    appt = schedule_appointment(
        therapist["id"], patient["id"], cpt_code="90834", duration_minutes=45,
        start_at="2026-07-17T08:00:00Z", payment_path="SELF_PAY")
    from test_helpers import make_therapist_headers
    resp = api_client.render_appointment(appt["id"], make_therapist_headers(therapist["id"]))
    data = validate_success(resp, 200)
    assert data["status"] == "RENDERED"
    assert data["patient_charge_cents"] == 3000
