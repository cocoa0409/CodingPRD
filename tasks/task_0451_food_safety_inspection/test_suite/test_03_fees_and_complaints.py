"""Fee calculations (plan-review marginal tiering, risk-tier permit fee) and complaint
triage severity / priority banding.

Queue B (Corner): calculations.
"""
from test_helpers import (
    api_client,
    validate_success,
    create_establishment, create_permitted_establishment,
    create_complaint, set_clock,
    create_plan_review_payload,
    TEST_USERS,
)

CLERK = TEST_USERS["permit_clerk_headers"]


def test_plan_review_fee_marginal_square_footage_tiers(api):
    """PRD §3.2: "The base fee is 20,000 cents. The first 500 square feet add nothing.
    Each square foot from the 501st through the 1,500th adds 50 cents. Each square foot
    beyond the 1,500th adds 80 cents. To this the system adds 1,500 cents per item of
    declared equipment."

    A 2000 sqft / 0 equip plan: 20000 + 1000*50 + 500*80 = 110000 cents.

    Design: Corner/calculations/calc_plan_review_fee_marginal_tiers
    """
    est = create_establishment(name="Diner E1", address="1 Main St", seating_capacity=40)
    res = api.create_plan_review(
        create_plan_review_payload(est["id"], submitted_layout_sqft=2000, equipment_count=0), CLERK)
    pr = validate_success(res, 201)
    assert pr["plan_fee_cents"] == 110000, f"expected 110000 cents, got {pr['plan_fee_cents']}"


def test_permit_fee_scaled_by_category_3(api):
    """PRD §3.3: "The annual permit fee is a flat figure scaled by the establishment's risk
    category at issuance: 30,000 cents for `CATEGORY_1`, 60,000 cents for `CATEGORY_2`, and
    120,000 cents for `CATEGORY_3`."

    A CATEGORY_3 establishment (seating 160 -> CATEGORY_3 base) issues annual_fee_cents 120000.

    Design: Corner/calculations/calc_permit_fee_risk_tier_scaled
    """
    # seating 160 (>=150) is CATEGORY_3 on its own; serves_raw bump stays capped at CATEGORY_3.
    est, pr, permit = create_permitted_establishment(
        name="Smokehouse", address="9 Pit Rd", seating_capacity=160, serves_raw_animal_foods=True)
    assert est["risk_category"] == "CATEGORY_3", f"seating 160 is CATEGORY_3, got {est['risk_category']}"
    assert permit["annual_fee_cents"] == 120000, f"expected 120000 cents, got {permit['annual_fee_cents']}"


def test_complaint_severity_foodborne_on_category_3_is_urgent(api):
    """PRD §3.9: "A type weight is assigned by complaint type: 40 for `FOODBORNE_ILLNESS`,
    15 for `SANITATION`, and 5 for `OTHER`. An illness weight is the reported ill count
    capped at 10, then multiplied by 4 points each. A risk weight is drawn from the parent
    establishment's risk category: 0 for `CATEGORY_1`, 5 for `CATEGORY_2`, and 10 for
    `CATEGORY_3`."
    PRD §3.9: "a score of at least 60 is `URGENT`".

    FOODBORNE_ILLNESS (40) + 5 ill * 4 (20) + CATEGORY_3 (10) = 70 -> URGENT.

    Design: Corner/calculations/calc_complaint_severity_foodborne_urgent
    """
    est, _, _ = create_permitted_establishment(
        name="Smokehouse", address="9 Pit Rd", seating_capacity=60,
        serves_raw_animal_foods=True, does_onsite_processing=True)
    complaint = create_complaint(est["id"], "FOODBORNE_ILLNESS", reported_ill_count=5)
    res = api.triage_complaint(complaint["id"], CLERK)
    triaged = validate_success(res, 200)
    assert triaged["severity_score"] == 70, f"40+20+10 = 70, got {triaged['severity_score']}"
    assert triaged["priority"] == "URGENT", f"score 70 (>=60) is URGENT, got {triaged['priority']}"


def test_complaint_ill_count_capped_at_ten(api):
    """PRD §3.9: "An illness weight is the reported ill count capped at 10, then multiplied
    by 4 points each."
    PRD §3.9: "a score of at least 30 but below 60 is `PRIORITY`".

    OTHER (5) on CATEGORY_1 (0) with reported_ill_count 12 capped at 10: 5 + 10*4 + 0 = 45
    -> PRIORITY (the 11th/12th ill report add nothing).

    Design: Corner/calculations/calc_complaint_severity_ill_count_capped_at_ten
    """
    est, _, _ = create_permitted_establishment(
        name="Diner E1", address="1 Main St", seating_capacity=40)
    complaint = create_complaint(est["id"], "OTHER", reported_ill_count=12)
    res = api.triage_complaint(complaint["id"], CLERK)
    triaged = validate_success(res, 200)
    assert triaged["severity_score"] == 45, f"5 + 10*4 + 0 = 45, got {triaged['severity_score']}"
    assert triaged["priority"] == "PRIORITY", f"score 45 is PRIORITY, got {triaged['priority']}"
