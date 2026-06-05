"""Charge-total filtering, deductible-only responsibility, claim-line sum validation,
and filtered/reverse-reachability list endpoints.

Queue B (corner) — sections calculations, endpoints.
"""
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS, ApiErrorId,
    create_active_policy, create_encounter, add_charge,
    setup_submitted_claim,
    adjudicate, get_benefit_accumulator_for_policy,
)
from test_helpers import api_client as _api

REGISTRAR = TEST_USERS["registrar_headers"]
BILLING = TEST_USERS["billing_headers"]


# ===========================================================================
# calculations
# ===========================================================================
# total_charges_excludes_voided
def test_total_charges_excludes_voided(api):
    """PRD §3.3: "the encounter's total_charges_cents is recomputed as the exact sum of
    amount_cents across that encounter's charges whose status is POSTED - voided charges are
    excluded from the total."

    Post 100000 and 50000, void the second => total 100000.

    Design: Corner/calculations/total_charges_excludes_voided
    """
    payer, patient, policy = create_active_policy()
    encounter = create_encounter(patient["id"], policy["id"])
    add_charge(encounter["id"], cpt_code="99285", unit_price_cents=100000)
    charge2 = add_charge(encounter["id"], cpt_code="70450", unit_price_cents=50000)
    validate_success(api.void_charge(charge2["id"], REGISTRAR))
    enc = validate_success(api.get_encounter(encounter["id"], REGISTRAR))
    assert enc["total_charges_cents"] == 100000, (
        f"total should exclude voided => 100000, got {enc['total_charges_cents']}"
    )


# deductible_only_when_allowed_below_remaining_deductible
def test_deductible_only_responsibility_when_allowed_below_deductible(api):
    """PRD §3.8: "The deductible applied is the smaller of the allowed amount and that
    remaining deductible. The amount after the deductible is the allowed amount minus the
    deductible applied."

    allowed 80000 < remaining deductible 100000 => responsibility 80000 (all deductible, no
    coinsurance); accumulator deductible_met 80000.

    Design: Corner/calculations/deductible_only_when_allowed_below_remaining_deductible
    """
    payer, patient, policy, encounter, coding, claim = setup_submitted_claim(
        charge_cents=300000, deductible_cents=100000, coinsurance_pct=0.20, oop_max_cents=500000,
    )
    data = adjudicate(claim["id"], 80000)
    assert data["patient_responsibility_cents"] == 80000, (
        f"responsibility should be 80000, got {data['patient_responsibility_cents']}"
    )
    accum = get_benefit_accumulator_for_policy(policy["id"])
    assert accum["deductible_met_cents"] == 80000
    assert accum["oop_met_cents"] == 80000


# claim_lines_must_sum_to_allowed
def test_claim_lines_must_sum_to_allowed(api):
    """PRD §3.8: "The supplied lines must sum exactly to allowed_amount_cents; if they do not,
    adjudication is rejected with ERR_CLAIM_LINES_MISMATCH."

    allowed 200000 but lines sum to 150000 => rejected.

    Design: Corner/calculations/claim_lines_must_sum_to_allowed
    """
    payer, patient, policy, encounter, coding, claim = setup_submitted_claim(
        charge_cents=300000, deductible_cents=100000, coinsurance_pct=0.20, oop_max_cents=500000,
    )
    resp = _api.adjudicate_claim(
        claim["id"],
        {"allowed_amount_cents": 200000, "claim_lines": [{"cpt_code": "99285", "line_allowed_cents": 150000}]},
        BILLING,
    )
    validate_error(resp, ApiErrorId.ERR_CLAIM_LINES_MISMATCH.value, expected_status=422)


# ===========================================================================
# endpoints
# ===========================================================================
# get_charges_by_encounter_reverse_reachability
def test_list_charges_for_encounter(api):
    """PRD §3.12: "Charges, eligibility checks, coding assignments, claims, claim lines,
    statements, payments, and write-offs may each also be listed under their parent record."

    GET /encounters/{id}/charges returns the encounter's two POSTED charges.

    Design: Corner/endpoints/get_charges_by_encounter_reverse_reachability
    """
    payer, patient, policy = create_active_policy()
    encounter = create_encounter(patient["id"], policy["id"])
    add_charge(encounter["id"], cpt_code="99285", unit_price_cents=100000)
    add_charge(encounter["id"], cpt_code="70450", unit_price_cents=50000)
    body = api.list_charges_for_encounter(encounter["id"], BILLING).json()
    assert body["response_type"] == "array"
    rows = [c for c in body["data"] if c["encounter_id"] == encounter["id"]]
    assert len(rows) == 2, f"expected 2 charges for the encounter, got {len(rows)}"


# filter_claims_by_payer
def test_filter_claims_by_payer(api):
    """PRD §3.12: "Collection reads support filtering as well as pagination: ... and claims by
    policy_id, payer_id, and status."

    GET /claims?payer_id={id} returns only that payer's claims.

    Design: Corner/endpoints/filter_claims_by_payer
    """
    payer, patient, policy, encounter, coding, claim = setup_submitted_claim(
        charge_cents=300000, deductible_cents=100000, coinsurance_pct=0.20, oop_max_cents=500000,
    )
    body = api.list_claims(BILLING, params={"payer_id": payer["id"]}).json()
    assert body["response_type"] == "array"
    assert len(body["data"]) >= 1
    assert all(c["payer_id"] == payer["id"] for c in body["data"]), (
        "every returned claim must have the filtered payer_id"
    )
