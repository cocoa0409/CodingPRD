"""Supportive-service payments: mileage per-trip rounding, non-mileage amounts, and
approval gates (active plan, supportive cap)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_area, intake_participant,
    setup_requested_supportive_payment,
    create_supportive_payload,
    CM, FO,
)


# --- Mileage: round each trip half-up, THEN sum ---
def test_mileage_rounds_per_trip_then_sums(api):
    """PRD §3.5: "the payment's `computed_amount_cents` is derived by multiplying each
    trip's mileage by the 65.5-cents-per-mile rate, rounding each trip's product half-up to
    a whole cent, and then summing those per-trip rounded cents. The rounding order is
    pinned: each trip is rounded before the sum is taken, which can differ from rounding a
    single summed product."

    Design: Difficulty/combinatorial_formula/mileage_round_per_trip_then_sum
    """
    area = create_area(api)
    p = intake_participant(api, area["id"])
    resp = api.create_supportive(p["id"], {"service_type": "MILEAGE", "trips": [5, 5, 5]}, CM)
    data = validate_success(resp, 201)
    # round_half_up(5 * 65.5) = 328 per trip; 328 * 3 = 984 (vs round(15*65.5)=983).
    assert data["computed_amount_cents"] == 984, data


def test_mileage_per_trip_rounding_diverges_from_summed_rounding(api):
    """PRD §3.5: "rounding each trip's product half-up to a whole cent, and then summing
    those per-trip rounded cents. The rounding order is pinned: each trip is rounded before
    the sum is taken, which can differ from rounding a single summed product."

    Design: Difficulty/combinatorial_formula/mileage_round_per_trip_then_sum
    """
    area = create_area(api)
    p = intake_participant(api, area["id"])
    resp = api.create_supportive(p["id"], {"service_type": "MILEAGE", "trips": [1, 1, 1]}, CM)
    data = validate_success(resp, 201)
    # round_half_up(1 * 65.5) = 66 per trip; 66 * 3 = 198 (vs round(3*65.5)=round(196.5)=197).
    assert data["computed_amount_cents"] == 198, data


def test_non_mileage_computed_amount_equals_amount_cents(api):
    """PRD §3.5: "For the non-mileage types (`CHILDCARE`, `TOOLS`, `OTHER`), the request
    supplies `amount_cents`, which must be strictly positive, and the payment's
    `computed_amount_cents` is simply that amount."

    Design: Corner/calculations/supportive_amount_non_mileage_equals_amount_cents
    """
    area = create_area(api)
    p = intake_participant(api, area["id"])
    resp = api.create_supportive(
        p["id"], create_supportive_payload(service_type="CHILDCARE", amount_cents=50000), CM)
    data = validate_success(resp, 201)
    assert data["computed_amount_cents"] == 50000, data


def test_approve_supportive_without_active_plan_rejected(api):
    """PRD §3.5: "rejected with `ERR_NO_ACTIVE_CAREER_PLAN` unless the participant has a
    career plan that is currently `ACTIVE` and whose `supportive_need_documented` flag is
    true".

    Design: Corner/validations/supportive_approve_without_active_plan_returns_no_active_plan
    """
    ctx = setup_requested_supportive_payment(
        api, amount_cents=50000, activate_plan_flag=False, supportive_need_documented=True)
    resp = api.approve_supportive(ctx["ss_id"], FO)
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_CAREER_PLAN.value)


def test_approve_supportive_over_available_cap_rejected(api):
    """PRD §3.5: "rejected with `ERR_SUPPORTIVE_CAP_EXCEEDED` unless the payment's
    `computed_amount_cents` is at most the participant's `supportive_available_cents`."

    Design: Corner/validations/supportive_approve_over_cap_returns_supportive_cap_exceeded
    """
    ctx = setup_requested_supportive_payment(
        api, amount_cents=250000, activate_plan_flag=True, supportive_need_documented=True)
    resp = api.approve_supportive(ctx["ss_id"], FO)
    validate_error(resp, ApiErrorId.ERR_SUPPORTIVE_CAP_EXCEEDED.value)
