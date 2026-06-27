"""Loyalty tiering boundary, livestock-sale accrual, and clinic loyalty accrual."""
from test_helpers import (
    validate_success,
    TEST_USERS,
    create_livestock_sale_payload, create_clinic_appointment_payload,
    make_store, make_customer, make_healthy_on_floor_batch,
    make_completed_vet_exam, set_clock,
)

CLERK = TEST_USERS["store_clerk_headers"]
VET = TEST_USERS["clinic_vet_headers"]


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / loyalty tier silver threshold
# ---------------------------------------------------------------------------
def test_loyalty_tier_silver_threshold_inclusive(api):
    """PRD §2.8: "a customer whose lifetime spend is at least 5,000,000 cents
    (fifty thousand dollars) is `SILVER`; ... Both thresholds are inclusive
    lower bounds: a lifetime spend exactly equal to 5,000,000 cents is `SILVER`".
    PRD §3.4: "That net amount is added to the customer's `lifetime_spend_cents`."

    Design: Difficulty/boundary_precision_check/loyalty_tier_silver_threshold_inclusive
    """
    store = make_store()
    customer = make_customer(store["id"])
    # head=100 @ 50000, BRONZE 0% discount → net = 5,000,000 exactly.
    batch = make_healthy_on_floor_batch(
        store["id"], head_count=100, unit_price_cents=50000, species="tetra",
    )
    api.create_livestock_sale(
        create_livestock_sale_payload(batch["id"], customer["id"]), CLERK
    )
    refreshed = validate_success(api.get_customer(customer["id"], CLERK), 200)
    assert refreshed["lifetime_spend_cents"] == 5000000
    assert refreshed["loyalty_tier"] == "SILVER"


def test_loyalty_tier_just_below_silver_stays_bronze(api):
    """PRD §2.8: "otherwise the customer is `BRONZE`. ... a lifetime spend exactly
    equal to 5,000,000 cents is `SILVER`".
    PRD §3.4: "That net amount is added to the customer's `lifetime_spend_cents`.
    ... Finally the customer's `loyalty_tier` is recomputed from the new
    `lifetime_spend_cents` per the thresholds in §2.8."

    Design: Difficulty/boundary_precision_check/loyalty_tier_silver_threshold_inclusive
    """
    store = make_store()
    customer = make_customer(store["id"])
    # head=100 @ 49999 → net = 4,999,900 < 5,000,000 → still BRONZE.
    batch = make_healthy_on_floor_batch(
        store["id"], head_count=100, unit_price_cents=49999, species="tetra",
    )
    api.create_livestock_sale(
        create_livestock_sale_payload(batch["id"], customer["id"]), CLERK
    )
    refreshed = validate_success(api.get_customer(customer["id"], CLERK), 200)
    assert refreshed["lifetime_spend_cents"] == 4999900
    assert refreshed["loyalty_tier"] == "BRONZE"


# ---------------------------------------------------------------------------
# Corner: calculations / livestock sale accrual
# ---------------------------------------------------------------------------
def test_livestock_sale_accrual_correct_points(api):
    """PRD §3.4: "Earned loyalty points equal the net amount in cents divided by
    100 and rounded down to a whole number (that is, whole dollars of net spend),
    multiplied by one point per dollar; those points are added to the customer's
    `loyalty_points`."
    PRD §3.4: "That net amount is added to the customer's `lifetime_spend_cents`."

    Design: Corner/calculations/livestock_sale_accrual_correct_points
    """
    store = make_store()
    customer = make_customer(store["id"])
    # head=10 @ 4999, BRONZE 0% → net = 49,990; points = floor(49990/100) = 499.
    batch = make_healthy_on_floor_batch(
        store["id"], head_count=10, unit_price_cents=4999, species="tetra",
    )
    api.create_livestock_sale(
        create_livestock_sale_payload(batch["id"], customer["id"]), CLERK
    )
    refreshed = validate_success(api.get_customer(customer["id"], CLERK), 200)
    assert refreshed["lifetime_spend_cents"] == 49990
    assert refreshed["loyalty_points"] == 499


# ---------------------------------------------------------------------------
# Corner: calculations / clinic loyalty service multiplier
# ---------------------------------------------------------------------------
def test_clinic_loyalty_vet_exam_triple_multiplier(api):
    """PRD §3.7: "it grants loyalty points equal to the fee in cents divided by
    100 and rounded down to whole dollars, multiplied by one point per dollar,
    and further multiplied by a service multiplier of 1 for `GROOMING`, 2 for
    `VACCINE`, and 3 for `VET_EXAM`; those points are added to `loyalty_points`".
    PRD §3.7: "The clinic accrual adds the appointment's `fee_cents` to the
    customer's `lifetime_spend_cents`".

    Design: Corner/calculations/clinic_loyalty_vet_exam_triple_multiplier
    """
    store = make_store()
    customer = make_customer(store["id"])
    # fee=8000 VET_EXAM → floor(8000/100)*3 = 80*3 = 240 points.
    make_completed_vet_exam(store["id"], customer["id"], fee_cents=8000)
    refreshed = validate_success(api.get_customer(customer["id"], CLERK), 200)
    assert refreshed["loyalty_points"] == 240
    assert refreshed["lifetime_spend_cents"] == 8000
