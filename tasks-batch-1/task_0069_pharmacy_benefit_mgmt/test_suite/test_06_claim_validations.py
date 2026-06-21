"""Claim adjudication validation errors (PRD §3.4). Corner queue: validations section.
"""
from test_helpers import fixtures as fx, validate_error, ApiErrorId
from test_helpers.api_client import api_client


# ─── Corner / validations.error_step_therapy_not_met_no_prior_first_line ────
def test_step_therapy_not_met_without_prior_first_line(api):
    """PRD §3.4: "if the drug carries a `step_therapy_protocol_id`, the member must satisfy that protocol or the claim is rejected with `ERR_STEP_THERAPY_NOT_MET`."

    Design: Corner/validations/error_step_therapy_not_met_no_prior_first_line
    """
    fx.set_clock("2026-07-18T00:00:00.000Z")
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    proto = fx.create_protocol(plan["id"], name="ST", first_line_ndcs=["FL1"])
    second = fx.create_drug(plan["id"], ndc="SL1", drug_name="Second", tier="TIER_2",
                            ingredient_cost_cents=30000, step_therapy_protocol_id=proto["id"])
    m = fx.create_member(plan["id"])
    resp = api_client.create_claim(
        {"member_id": m["id"], "formulary_drug_id": second["id"], "days_supply": 30,
         "pharmacy_type": "RETAIL"},
        fx.PROVIDER,
    )
    validate_error(resp, ApiErrorId.ERR_STEP_THERAPY_NOT_MET.value)


# ─── Corner / validations.error_specialty_pharmacy_required_wrong_channel ───
def test_specialty_drug_at_retail_rejected(api):
    """PRD §3.4: "if the drug is a specialty product and its plan has `specialty_requires_specialty_pharmacy` set to true, then the claim's `pharmacy_type` must be `SPECIALTY`, otherwise the claim is rejected with `ERR_SPECIALTY_PHARMACY_REQUIRED`."

    Design: Corner/validations/error_specialty_pharmacy_required_wrong_channel
    """
    fx.set_clock("2026-07-20T00:00:00.000Z")
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    drug = fx.create_drug(plan["id"], ndc="SP", drug_name="Spec", tier="SPECIALTY",
                          ingredient_cost_cents=200000, is_specialty=True)
    m = fx.create_member(plan["id"])
    resp = api_client.create_claim(
        {"member_id": m["id"], "formulary_drug_id": drug["id"], "days_supply": 30,
         "pharmacy_type": "RETAIL"},
        fx.PROVIDER,
    )
    validate_error(resp, ApiErrorId.ERR_SPECIALTY_PHARMACY_REQUIRED.value)


# ─── Corner / validations.error_invalid_days_supply_mail_order_30 ───────────
def test_mail_order_with_30_days_rejected(api):
    """PRD §3.4: "days_supply` must be exactly 30 or 90, and if `pharmacy_type` is `MAIL_ORDER` then `days_supply` must be 90 — any other combination is rejected with `ERR_INVALID_DAYS_SUPPLY`."

    Design: Corner/validations/error_invalid_days_supply_mail_order_30
    """
    fx.set_clock("2026-07-22T00:00:00.000Z")
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    drug = fx.create_drug(plan["id"], ndc="T1", drug_name="T1", tier="TIER_1",
                          ingredient_cost_cents=10000)
    m = fx.create_member(plan["id"])
    resp = api_client.create_claim(
        {"member_id": m["id"], "formulary_drug_id": drug["id"], "days_supply": 30,
         "pharmacy_type": "MAIL_ORDER"},
        fx.PROVIDER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_DAYS_SUPPLY.value)


# ─── Corner / validations.error_copay_card_mismatched_drug ──────────────────
def test_copay_card_for_different_drug_rejected(api):
    """PRD §3.4: "if the claim carries a `copay_card_id`, that card must belong to the
    same member and the same drug as the claim and must be `ACTIVE`; a card that does
    not match the claim's member and drug, or one that is `EXHAUSTED`, is rejected with
    `ERR_COPAY_CARD_INVALID`."

    Design: Corner/validations/error_copay_card_mismatched_drug
    """
    fx.set_clock("2026-07-24T00:00:00.000Z")
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    d1 = fx.create_drug(plan["id"], ndc="D1", drug_name="D1", tier="TIER_2", ingredient_cost_cents=30000)
    d2 = fx.create_drug(plan["id"], ndc="D2", drug_name="D2", tier="TIER_2", ingredient_cost_cents=30000)
    m = fx.create_member(plan["id"])
    card = fx.create_copay_card(m["id"], d1["id"], max_benefit_cents=20000)
    resp = api_client.create_claim(
        {"member_id": m["id"], "formulary_drug_id": d2["id"], "days_supply": 30,
         "pharmacy_type": "RETAIL", "copay_card_id": card["id"]},
        fx.PROVIDER,
    )
    validate_error(resp, ApiErrorId.ERR_COPAY_CARD_INVALID.value)


# ─── Corner / validations.claim_for_nonexistent_drug_returns_not_found ──────
def test_claim_for_nonexistent_drug_returns_not_found(api):
    """PRD §2.7: "every resource referenced by a path identifier or a foreign-key body
    field must exist, validated left to right in the order the references are read —
    member, then drug, then plan, then prior authorization, then copay card — and the
    first missing reference yields `ERR_NOT_FOUND`."

    Design: Corner/validations/claim_for_nonexistent_drug_returns_not_found
    """
    fx.set_clock("2026-07-26T00:00:00.000Z")
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    m = fx.create_member(plan["id"])
    resp = api_client.create_claim(
        {"member_id": m["id"], "formulary_drug_id": "00000000-0000-4000-8000-000000000000",
         "days_supply": 30, "pharmacy_type": "RETAIL"},
        fx.PROVIDER,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
