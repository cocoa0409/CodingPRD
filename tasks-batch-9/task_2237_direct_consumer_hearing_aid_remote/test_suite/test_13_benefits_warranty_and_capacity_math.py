"""Benefit waterfall, care-plan billing, warranty deductibles, capacity and cohort math."""
from test_helpers import (
    ADMIN,
    CARE_OPS,
    COMPLIANCE,
    FIRMWARE_ENGINEER,
    REIMBURSEMENT,
    REIMBURSEMENT_2,
    REPAIR_TECH,
    api_client,
    create_care_plan_payload,
    create_devices,
    create_inventory_pool,
    create_provider,
    create_state_policy,
    file_warranty_claim,
    get_success_data,
    make_patient_headers,
    place_order,
    register_patient,
    scan_shipment,
    screen_patient,
    set_clock,
    setup_active_care_plan,
    setup_delivered_order,
    simulate_payment,
    validate_error,
    validate_paginated,
    validate_success,
    ApiErrorId,
)

# Order economics used throughout: device subtotal 200000, no accessories, shipping 1495.
ORDER_ECONOMICS = {
    "list_price_cents": 200000,
    "discount_cents": 0,
    "accessory_subtotal_cents": 0,
    "shipping_cents": 1495,
}

DEVICE_ORDER_DOCUMENT_CODES = ["INVOICE", "AUDIOGRAM_OR_WAIVER", "PROOF_OF_PAYMENT", "LMN"]
OTHER_SUBJECT_DOCUMENT_CODES = ["INVOICE", "PROOF_OF_PAYMENT"]

# Monthly clocks: each instant is at or after the cycle_end_utc of the cycle it bills.
MONTHLY_CYCLE_CLOCKS = [
    "2026-09-01T00:00:00Z",
    "2026-10-01T00:00:00Z",
    "2026-11-01T00:00:00Z",
    "2026-12-01T00:00:00Z",
    "2027-01-01T00:00:00Z",
    "2027-02-01T00:00:00Z",
]
SEVENTH_CYCLE_CLOCK = "2027-03-01T00:00:00Z"


def _delivered_order_with_plan(plan_tier: str, base_fee_cents: int) -> dict:
    """Delivered order whose attached care plan was activated by the delivery scan."""
    return setup_active_care_plan(
        plan_overrides={
            "plan_tier": plan_tier,
            "base_fee_cents": base_fee_cents,
            "firmware_auto_update_enabled": True,
        },
        order_overrides=ORDER_ECONOMICS,
    )


def _run_six_monthly_cycles(plan_id: str) -> dict:
    """Six successful monthly runs, leaving cycle_ordinal at 6."""
    plan = None
    for clock in MONTHLY_CYCLE_CLOCKS:
        set_clock(clock)
        plan = get_success_data(
            api_client.run_billing_cycle(plan_id, {"charge_outcome": "SUCCEEDED"}, ADMIN)
        )
    assert plan["cycle_ordinal"] == 6, (
        f"Setup failed: expected cycle_ordinal 6 after six cycles, got {plan['cycle_ordinal']}"
    )
    return plan


# ---------------------------------------------------------------------------
# The benefit waterfall
# ---------------------------------------------------------------------------
def test_benefit_waterfall_fills_insurance_then_fsa_then_patient():
    """PRD §3.8: "Step one computes `eligible_amount_cents`: it is 0 outright when
    `documentation_complete` is false; for a `DEVICE_ORDER` subject it is the lesser of
    `claimed_amount_cents` and the order's `captured_cents` minus `refunded_cents` minus
    `retained_cents` floored at 0".

    PRD §3.8: "The remaining steps fill three ordered buckets with no proportional
    splitting: `insurance_paid_cents` is the lesser of the eligible amount and the declared
    `insurance_benefit_cap_cents` minus `insurance_benefit_used_cents` floored at 0; what
    remains after insurance is the eligible amount minus `insurance_paid_cents`;
    `fsa_paid_cents` is the lesser of that remainder and `fsa_balance_cents`; and
    `patient_responsibility_cents` is the eligible amount minus `insurance_paid_cents` minus
    `fsa_paid_cents`, absorbing any remainder by construction."

    PRD §3.8: "It records the acting operator identity as `submitted_by_user_id`"

    Design: Corner/calculations/calc_reimbursement_waterfall_fills_insurance_then_fsa_then_patient
    """
    env = setup_delivered_order(order_overrides=ORDER_ECONOMICS)
    patient_id = env["patient"]["id"]

    claim = get_success_data(
        api_client.create_reimbursement_claim(
            {
                "patient_id": patient_id,
                "subject_kind": "DEVICE_ORDER",
                "device_order_id": env["order"]["id"],
                "claimed_amount_cents": 150000,
                "document_codes": DEVICE_ORDER_DOCUMENT_CODES,
                "insurance_benefit_cap_cents": 100000,
                "insurance_benefit_used_cents": 20000,
                "fsa_balance_cents": 50000,
            },
            make_patient_headers(patient_id),
        )
    )

    data = validate_success(api_client.submit_reimbursement_claim(claim["id"], REIMBURSEMENT), 200)

    assert data["status"] == "SUBMITTED", f"Expected status SUBMITTED, got {data['status']}"
    assert data["documentation_complete"] is True, (
        f"Expected documentation_complete True, got {data['documentation_complete']}"
    )
    assert data["eligible_amount_cents"] == 150000, (
        f"Expected eligible_amount_cents 150000, got {data['eligible_amount_cents']}"
    )
    assert data["insurance_paid_cents"] == 80000, (
        f"Expected insurance_paid_cents 80000, got {data['insurance_paid_cents']}"
    )
    assert data["fsa_paid_cents"] == 50000, (
        f"Expected fsa_paid_cents 50000, got {data['fsa_paid_cents']}"
    )
    assert data["patient_responsibility_cents"] == 20000, (
        f"Expected patient_responsibility_cents 20000, got {data['patient_responsibility_cents']}"
    )
    bucket_sum = (
        data["insurance_paid_cents"] + data["fsa_paid_cents"] + data["patient_responsibility_cents"]
    )
    assert bucket_sum == data["eligible_amount_cents"], (
        f"Expected the three buckets to sum to eligible_amount_cents "
        f"{data['eligible_amount_cents']}, got {bucket_sum}"
    )
    assert data["submitted_by_user_id"] == REIMBURSEMENT["X-User-ID"], (
        f"Expected submitted_by_user_id {REIMBURSEMENT['X-User-ID']}, "
        f"got {data['submitted_by_user_id']}"
    )


def test_repair_subject_eligible_amount_clipped_by_repair_cap():
    """PRD §3.8: "for a `REPAIR_ORDER` subject it is the lesser of `claimed_amount_cents` and
    a repair cap of 50,000 cents ($500.00)"

    PRD §3.8: "Creation computes `documentation_complete`, which is true exactly when
    `document_codes` is a superset of the required set for the claim's `subject_kind` —
    `INVOICE`, `AUDIOGRAM_OR_WAIVER`, `PROOF_OF_PAYMENT` and `LMN` for a `DEVICE_ORDER`, and
    `INVOICE` and `PROOF_OF_PAYMENT` for the other two kinds."

    PRD §2.9: "`claimed_amount_cents` is at most `eligible_amount_cents`, on
    `POST /reimbursement-claims/{id}/decide` with `decision` `APPROVE` — otherwise
    `ERR_CLAIM_AMOUNT_EXCEEDS_ELIGIBLE` (422)."

    Design: Corner/calculations/calc_reimbursement_repair_subject_clipped_by_50000_cap
    """
    env = setup_delivered_order(order_overrides=ORDER_ECONOMICS)
    patient_id = env["patient"]["id"]
    patient_headers = make_patient_headers(patient_id)

    repair = get_success_data(
        api_client.create_repair_order(
            {"device_id": env["assigned_device"]["id"], "fault_code": "MOISTURE"}, CARE_OPS
        )
    )
    claim = get_success_data(
        api_client.create_reimbursement_claim(
            {
                "patient_id": patient_id,
                "subject_kind": "REPAIR_ORDER",
                "repair_order_id": repair["id"],
                "claimed_amount_cents": 90000,
                "document_codes": OTHER_SUBJECT_DOCUMENT_CODES,
                "insurance_benefit_cap_cents": 0,
                "insurance_benefit_used_cents": 0,
                "fsa_balance_cents": 0,
            },
            patient_headers,
        )
    )

    data = validate_success(api_client.submit_reimbursement_claim(claim["id"], REIMBURSEMENT), 200)

    assert data["status"] == "SUBMITTED", f"Expected status SUBMITTED, got {data['status']}"
    assert data["documentation_complete"] is True, (
        f"Expected documentation_complete True, got {data['documentation_complete']}"
    )
    assert data["eligible_amount_cents"] == 50000, (
        f"Expected eligible_amount_cents 50000, got {data['eligible_amount_cents']}"
    )
    assert data["insurance_paid_cents"] == 0, (
        f"Expected insurance_paid_cents 0, got {data['insurance_paid_cents']}"
    )
    assert data["fsa_paid_cents"] == 0, f"Expected fsa_paid_cents 0, got {data['fsa_paid_cents']}"
    assert data["patient_responsibility_cents"] == 50000, (
        f"Expected patient_responsibility_cents 50000, got {data['patient_responsibility_cents']}"
    )

    get_success_data(api_client.start_reimbursement_review(claim["id"], REIMBURSEMENT))
    denied = api_client.decide_reimbursement_claim(
        claim["id"], {"decision": "APPROVE"}, REIMBURSEMENT_2
    )
    validate_error(denied, ApiErrorId.ERR_CLAIM_AMOUNT_EXCEEDS_ELIGIBLE.value)


# ---------------------------------------------------------------------------
# Care-plan cycle charge
# ---------------------------------------------------------------------------
def test_service_fee_waived_when_subtotal_exactly_hits_threshold():
    """PRD §3.8: "Step one: the subtotal is `base_fee_cents`, plus a premium surcharge of
    2,000 cents ($20.00) when `plan_tier` is `PREMIUM`. Step two: `service_fee_cents` is 0 when
    that subtotal is at least 9,900 cents ($99.00) — the threshold is inclusive, so a subtotal of
    exactly 9,900 waives the fee — and 495 cents ($4.95) otherwise."

    PRD §3.8: "Step four: the loyalty rate is 0.15 when `cycle_ordinal` is at least 12,
    otherwise 0.10 when `cycle_ordinal` is at least 6, otherwise 0.0"

    PRD §3.8: "On success the plan self-loops `ACTIVE → ACTIVE`: the five-step computation
    writes `service_fee_cents`, `loyalty_discount_cents` and `last_charge_cents`, credit is
    consumed, `cycle_ordinal` increments"

    Design: Corner/calculations/calc_care_plan_service_fee_waived_at_exactly_9900
    """
    env = _delivered_order_with_plan("STANDARD", 9900)
    set_clock(MONTHLY_CYCLE_CLOCKS[0])

    data = validate_success(
        api_client.run_billing_cycle(env["plan"]["id"], {"charge_outcome": "SUCCEEDED"}, ADMIN), 200
    )

    assert data["status"] == "ACTIVE", f"Expected status ACTIVE, got {data['status']}"
    assert data["service_fee_cents"] == 0, (
        f"Expected service_fee_cents 0, got {data['service_fee_cents']}"
    )
    assert data["last_charge_cents"] == 9900, (
        f"Expected last_charge_cents 9900, got {data['last_charge_cents']}"
    )
    assert data["cycle_ordinal"] == 1, f"Expected cycle_ordinal 1, got {data['cycle_ordinal']}"
    assert data["dunning_attempts"] == 0, (
        f"Expected dunning_attempts 0, got {data['dunning_attempts']}"
    )
    assert data["credit_balance_cents"] == 0, (
        f"Expected credit_balance_cents 0, got {data['credit_balance_cents']}"
    )


def test_service_fee_applied_one_cent_below_threshold():
    """PRD §3.8: "Step two: `service_fee_cents` is 0 when that subtotal is at least 9,900 cents
    ($99.00) — the threshold is inclusive, so a subtotal of exactly 9,900 waives the fee — and
    495 cents ($4.95) otherwise. Step three: the fee-inclusive base is the subtotal plus
    `service_fee_cents`."

    PRD §3.8: "Step five: `last_charge_cents` is the fee-inclusive base minus
    `loyalty_discount_cents`, floored at 0."

    Design: Corner/calculations/calc_care_plan_service_fee_applied_one_cent_below_threshold
    """
    env = _delivered_order_with_plan("STANDARD", 9899)
    set_clock(MONTHLY_CYCLE_CLOCKS[0])

    data = validate_success(
        api_client.run_billing_cycle(env["plan"]["id"], {"charge_outcome": "SUCCEEDED"}, ADMIN), 200
    )

    assert data["service_fee_cents"] == 495, (
        f"Expected service_fee_cents 495, got {data['service_fee_cents']}"
    )
    assert data["last_charge_cents"] == 10394, (
        f"Expected last_charge_cents 10394, got {data['last_charge_cents']}"
    )
    assert data["cycle_ordinal"] == 1, f"Expected cycle_ordinal 1, got {data['cycle_ordinal']}"


def test_loyalty_discount_first_earned_at_cycle_ordinal_six():
    """PRD §3.8: "Step four: the loyalty rate is 0.15 when `cycle_ordinal` is at least 12,
    otherwise 0.10 when `cycle_ordinal` is at least 6, otherwise 0.0; `loyalty_discount_cents` is
    the lesser of 1,500 cents ($15.00) and the fee-inclusive base multiplied by that rate, rounded
    half up. Step five: `last_charge_cents` is the fee-inclusive base minus
    `loyalty_discount_cents`, floored at 0. Testing the **discounted** amount against the
    service-fee waiver threshold is forbidden and produces a different total."

    Design: Corner/calculations/calc_care_plan_loyalty_tier1_discount_at_cycle_ordinal_6
    """
    env = _delivered_order_with_plan("STANDARD", 9900)
    _run_six_monthly_cycles(env["plan"]["id"])
    set_clock(SEVENTH_CYCLE_CLOCK)

    data = validate_success(
        api_client.run_billing_cycle(env["plan"]["id"], {"charge_outcome": "SUCCEEDED"}, ADMIN), 200
    )

    assert data["status"] == "ACTIVE", f"Expected status ACTIVE, got {data['status']}"
    assert data["service_fee_cents"] == 0, (
        f"Expected service_fee_cents 0, got {data['service_fee_cents']}"
    )
    assert data["loyalty_discount_cents"] == 990, (
        f"Expected loyalty_discount_cents 990, got {data['loyalty_discount_cents']}"
    )
    assert data["last_charge_cents"] == 8910, (
        f"Expected last_charge_cents 8910, got {data['last_charge_cents']}"
    )
    assert data["cycle_ordinal"] == 7, f"Expected cycle_ordinal 7, got {data['cycle_ordinal']}"


def test_loyalty_discount_clipped_by_cap_on_premium_plan():
    """PRD §3.8: "Step one: the subtotal is `base_fee_cents`, plus a premium surcharge of
    2,000 cents ($20.00) when `plan_tier` is `PREMIUM`."

    PRD §3.8: "`loyalty_discount_cents` is the lesser of 1,500 cents ($15.00) and the
    fee-inclusive base multiplied by that rate, rounded half up. Step five:
    `last_charge_cents` is the fee-inclusive base minus `loyalty_discount_cents`, floored at 0."

    Design: Corner/calculations/calc_care_plan_loyalty_discount_hits_1500_cap
    """
    env = _delivered_order_with_plan("PREMIUM", 14000)
    _run_six_monthly_cycles(env["plan"]["id"])
    set_clock(SEVENTH_CYCLE_CLOCK)

    data = validate_success(
        api_client.run_billing_cycle(env["plan"]["id"], {"charge_outcome": "SUCCEEDED"}, ADMIN), 200
    )

    assert data["loyalty_discount_cents"] == 1500, (
        f"Expected loyalty_discount_cents 1500, got {data['loyalty_discount_cents']}"
    )
    assert data["last_charge_cents"] == 14500, (
        f"Expected last_charge_cents 14500, got {data['last_charge_cents']}"
    )
    assert data["cycle_ordinal"] == 7, f"Expected cycle_ordinal 7, got {data['cycle_ordinal']}"


# ---------------------------------------------------------------------------
# Warranty deductibles
# ---------------------------------------------------------------------------
def test_damage_deductible_rounds_the_multiplicative_part_half_up():
    """PRD §3.7: "An age of at most 12 months — inclusive — takes a multiplier of 0.5; an age
    from 13 through 24 months takes 1.0; an age above 24 months takes 1.5. The kind factor is 0.0
    for `DEFECT`, 0.75 for `DAMAGE` and 1.0 for `LOSS`, so a manufacturing defect is never charged
    a deductible. The ordinal surcharge is 0 when `claim_ordinal` is 1 and 5,000 cents ($50.00)
    otherwise. `deductible_cents` is the base of 9,900 cents ($99.00) multiplied by the age
    multiplier and by the kind factor, rounded half up, with the integer surcharge added
    afterwards — the rounding touches the multiplicative part only."

    PRD §3.7: "Triage stamps `triaged_at`, computes `device_age_months` and `claim_ordinal`,
    mirrors the age onto the device's `age_months_at_last_claim`, and computes the deductible.
    `device_age_months` is the whole number of months between the device's `shipped_at` and the
    logical clock, floored."

    Design: Corner/calculations/calc_warranty_deductible_damage_tier1_rounds_multiplicative_part
    """
    env = setup_delivered_order(order_overrides=ORDER_ECONOMICS)
    claim = file_warranty_claim(env, claim_kind="DAMAGE")

    data = validate_success(api_client.triage_warranty_claim(claim["id"], REPAIR_TECH), 200)

    assert data["status"] == "TRIAGED", f"Expected status TRIAGED, got {data['status']}"
    assert data["device_age_months"] == 0, (
        f"Expected device_age_months 0, got {data['device_age_months']}"
    )
    assert data["claim_ordinal"] == 1, f"Expected claim_ordinal 1, got {data['claim_ordinal']}"
    assert data["deductible_cents"] == 3713, (
        f"Expected deductible_cents 3713, got {data['deductible_cents']}"
    )
    assert data["deductible_paid_cents"] == 0, (
        f"Expected deductible_paid_cents 0, got {data['deductible_paid_cents']}"
    )


def test_loss_deductible_at_thirteen_months_uses_second_age_tier():
    """PRD §3.7: "An age of at most 12 months — inclusive — takes a multiplier of 0.5; an age
    from 13 through 24 months takes 1.0; an age above 24 months takes 1.5. The kind factor is 0.0
    for `DEFECT`, 0.75 for `DAMAGE` and 1.0 for `LOSS`"

    PRD §3.7: "`device_age_months` is the whole number of months between the device's
    `shipped_at` and the logical clock, floored."

    Design: Corner/calculations/calc_warranty_deductible_age_tier_boundary_thirteen_months_loss
    """
    env = setup_delivered_order(order_overrides=ORDER_ECONOMICS)
    set_clock("2027-09-01T00:00:00Z")
    claim = file_warranty_claim(env, claim_kind="LOSS")

    data = validate_success(api_client.triage_warranty_claim(claim["id"], REPAIR_TECH), 200)

    assert data["device_age_months"] == 13, (
        f"Expected device_age_months 13, got {data['device_age_months']}"
    )
    assert data["deductible_cents"] == 9900, (
        f"Expected deductible_cents 9900, got {data['deductible_cents']}"
    )
    assert data["claim_ordinal"] == 1, f"Expected claim_ordinal 1, got {data['claim_ordinal']}"


def test_defect_deductible_is_zero_even_in_the_oldest_age_tier():
    """PRD §3.7: "The kind factor is 0.0 for `DEFECT`, 0.75 for `DAMAGE` and 1.0 for `LOSS`, so a
    manufacturing defect is never charged a deductible."

    PRD §3.7: "an age above 24 months takes 1.5"

    Design: Corner/calculations/calc_warranty_deductible_defect_zero_factor_beats_tier3_multiplier
    """
    env = setup_delivered_order(order_overrides=ORDER_ECONOMICS)
    set_clock("2029-02-01T00:00:00Z")
    claim = file_warranty_claim(env, claim_kind="DEFECT")

    data = validate_success(api_client.triage_warranty_claim(claim["id"], REPAIR_TECH), 200)

    assert data["device_age_months"] == 30, (
        f"Expected device_age_months 30, got {data['device_age_months']}"
    )
    assert data["deductible_cents"] == 0, (
        f"Expected deductible_cents 0, got {data['deductible_cents']}"
    )

    reread = validate_success(api_client.get_warranty_claim(claim["id"], REPAIR_TECH), 200)
    assert reread["status"] == "TRIAGED", (
        f"Expected the re-read claim status TRIAGED, got {reread['status']}"
    )
    assert reread["deductible_cents"] == 0, (
        f"Expected the re-read deductible_cents 0, got {reread['deductible_cents']}"
    )


def test_second_claim_surcharge_is_added_after_the_rounding():
    """PRD §3.7: "The ordinal surcharge is 0 when `claim_ordinal` is 1 and 5,000 cents ($50.00)
    otherwise. `deductible_cents` is the base of 9,900 cents ($99.00) multiplied by the age
    multiplier and by the kind factor, rounded half up, with the integer surcharge added
    afterwards — the rounding touches the multiplicative part only."

    PRD §3.7: "`claim_ordinal` is one more than the number of prior claims on the same `device_id`
    whose `status` is `APPROVED_REPLACEMENT`, `APPROVED_REPAIR` or `FULFILLED`, ordered by
    `created_at` ascending, and is at least 1; withdrawn claims are excluded from the count."

    PRD §3.7: "A `REPAIR` decision moves the claim `TRIAGED → APPROVED_REPAIR`; it requires
    `claim_kind` to be `DEFECT` or `DAMAGE` and `warranty_expires_at` to be strictly after the
    clock."

    Design: Corner/calculations/calc_warranty_deductible_second_claim_surcharge_added_after_rounding
    """
    env = setup_delivered_order(order_overrides=ORDER_ECONOMICS)
    device_id = env["assigned_device"]["id"]

    first = file_warranty_claim(env, claim_kind="DAMAGE")
    first_triaged = get_success_data(api_client.triage_warranty_claim(first["id"], REPAIR_TECH))
    assert first_triaged["deductible_cents"] == 3713, (
        f"Setup failed: expected the first deductible 3713, got {first_triaged['deductible_cents']}"
    )
    get_success_data(
        api_client.decide_warranty_claim(first["id"], {"decision": "REPAIR"}, COMPLIANCE)
    )

    second = file_warranty_claim(env, claim_kind="DAMAGE")
    data = validate_success(api_client.triage_warranty_claim(second["id"], REPAIR_TECH), 200)

    assert data["claim_ordinal"] == 2, f"Expected claim_ordinal 2, got {data['claim_ordinal']}"
    assert data["deductible_cents"] == 8713, (
        f"Expected deductible_cents 8713, got {data['deductible_cents']}"
    )

    first_reread = validate_success(api_client.get_warranty_claim(first["id"], REPAIR_TECH), 200)
    assert first_reread["deductible_cents"] == 3713, (
        f"Expected the first claim to keep deductible_cents 3713 with no retroactive surcharge, "
        f"got {first_reread['deductible_cents']}"
    )

    rows, meta = validate_paginated(
        api_client.list_warranty_claims(REPAIR_TECH, params={"device_id": device_id})
    )
    assert meta["total_count"] == 2, (
        f"Expected total_count 2 for the device's claims, got {meta['total_count']}"
    )
    assert len(rows) == 2, f"Expected 2 listed claims for the device, got {len(rows)}"


# ---------------------------------------------------------------------------
# Provider capacity and slot geometry
# ---------------------------------------------------------------------------
def _telecare_booking_environment(daily_capacity_minutes: int, buffer_minutes: int) -> dict:
    """One telecare fitter plus one patient in a telehealth-permitting state."""
    set_clock("2026-08-01T00:00:00Z")
    policy = create_state_policy()
    provider = create_provider(
        provider_type="TELECARE_FITTER",
        daily_capacity_minutes=daily_capacity_minutes,
        buffer_minutes=buffer_minutes,
    )
    patient = register_patient(policy["id"])
    return {"policy": policy, "provider": provider, "patient": patient}


def _book_follow_up(env: dict, start_utc: str, end_utc: str):
    return api_client.create_remote_fitting_session(
        {
            "patient_id": env["patient"]["id"],
            "session_type": "FOLLOW_UP",
            "provider_id": env["provider"]["id"],
            "scheduled_start_utc": start_utc,
            "scheduled_end_utc": end_utc,
        },
        make_patient_headers(env["patient"]["id"]),
    )


def test_daily_capacity_accepts_exact_equality_and_reports_full_utilization():
    """PRD §3.4: "The booking is accepted when the already-booked minutes plus the candidate's
    `duration_minutes` is at most `daily_capacity_minutes`; exact equality is accepted, so a
    provider with 480 minutes of capacity may take a 60-minute session on top of 420 already
    booked but not on top of 421. Exceeding the ceiling is rejected with
    `ERR_PROVIDER_CAPACITY_EXCEEDED`."

    PRD §3.4: "The focus date is the UTC calendar date of the candidate's `scheduled_start_utc`,
    and `booked_minutes_on_focus_date` is the sum of `duration_minutes` over that provider's
    sessions whose `status` is `SCHEDULED`, `IN_PROGRESS` or `COMPLETED` and whose own
    `scheduled_start_utc` falls on that same UTC date."

    PRD §3.4: "the provider's `booked_minutes_on_focus_date` and `utilization_pct` are recomputed,
    the latter as 100 multiplied by `booked_minutes_on_focus_date` divided by
    `daily_capacity_minutes`, rounded half up to one decimal place."

    Design: Corner/calculations/calc_provider_capacity_equality_accepted_and_utilization_hits_100
    """
    env = _telecare_booking_environment(daily_capacity_minutes=120, buffer_minutes=0)
    get_success_data(_book_follow_up(env, "2026-08-20T10:00:00Z", "2026-08-20T11:00:00Z"))

    data = validate_success(
        _book_follow_up(env, "2026-08-20T11:00:00Z", "2026-08-20T12:00:00Z"), 201
    )

    assert data["status"] == "SCHEDULED", f"Expected status SCHEDULED, got {data['status']}"
    assert data["duration_minutes"] == 60, (
        f"Expected duration_minutes 60, got {data['duration_minutes']}"
    )

    provider = validate_success(api_client.get_provider(env["provider"]["id"], CARE_OPS), 200)
    assert provider["booked_minutes_on_focus_date"] == 120, (
        f"Expected booked_minutes_on_focus_date 120, "
        f"got {provider['booked_minutes_on_focus_date']}"
    )
    assert provider["utilization_pct"] == 100.0, (
        f"Expected utilization_pct 100.0, got {provider['utilization_pct']}"
    )

    over = _book_follow_up(env, "2026-08-20T13:00:00Z", "2026-08-20T13:15:00Z")
    validate_error(over, ApiErrorId.ERR_PROVIDER_CAPACITY_EXCEEDED.value)

    next_day = validate_success(
        _book_follow_up(env, "2026-08-21T10:00:00Z", "2026-08-21T11:00:00Z"), 201
    )
    assert next_day["status"] == "SCHEDULED", (
        f"Expected the next-date booking to land in SCHEDULED, got {next_day['status']}"
    )


def test_buffered_adjacency_is_accepted_while_one_minute_earlier_conflicts():
    """PRD §3.4: "**Slot overlap** widens only the *candidate* interval by the provider's
    `buffer_minutes` on both sides — the candidate is treated as starting `buffer_minutes` earlier
    and ending `buffer_minutes` later — and compares that widened candidate against each existing
    session of the same provider whose `status` is `SCHEDULED` or `IN_PROGRESS`, using those
    existing sessions' un-widened half-open intervals. A conflict exists when the widened candidate
    start is strictly before the existing end **and** the existing start is strictly before the
    widened candidate end; both comparisons are strict, so exact adjacency at the buffered
    boundary — a widened candidate start falling precisely on an existing end — is accepted."

    PRD §3.4: "A conflict is rejected with `ERR_PROVIDER_SLOT_CONFLICT`."

    PRD §3.4: "the latter as 100 multiplied by `booked_minutes_on_focus_date` divided by
    `daily_capacity_minutes`, rounded half up to one decimal place."

    Design: Corner/calculations/calc_fitting_slot_buffered_adjacency_is_accepted_not_a_conflict
    """
    env = _telecare_booking_environment(daily_capacity_minutes=480, buffer_minutes=10)
    get_success_data(_book_follow_up(env, "2026-08-20T10:00:00Z", "2026-08-20T11:00:00Z"))

    data = validate_success(
        _book_follow_up(env, "2026-08-20T11:10:00Z", "2026-08-20T12:10:00Z"), 201
    )

    assert data["status"] == "SCHEDULED", f"Expected status SCHEDULED, got {data['status']}"

    provider = validate_success(api_client.get_provider(env["provider"]["id"], CARE_OPS), 200)
    assert provider["booked_minutes_on_focus_date"] == 120, (
        f"Expected booked_minutes_on_focus_date 120, "
        f"got {provider['booked_minutes_on_focus_date']}"
    )
    assert provider["utilization_pct"] == 25.0, (
        f"Expected utilization_pct 25.0, got {provider['utilization_pct']}"
    )

    conflicting = _book_follow_up(env, "2026-08-20T11:05:00Z", "2026-08-20T12:05:00Z")
    validate_error(conflicting, ApiErrorId.ERR_PROVIDER_SLOT_CONFLICT.value)


# ---------------------------------------------------------------------------
# Firmware campaign windows
# ---------------------------------------------------------------------------
def _campaign_payload(campaign_code: str, **overrides) -> dict:
    payload = {
        "campaign_code": campaign_code,
        "model": "NEO",
        "from_version": "4.0.0",
        "to_version": "4.1.0",
        "window_start_utc": "2026-09-01T00:00:00Z",
        "window_end_utc": "2026-09-10T00:00:00Z",
        "batch_size": 2,
        "max_concurrent_installs": 2,
        "is_mandatory_safety": False,
    }
    payload.update(overrides)
    return payload


def test_campaign_windows_touching_at_an_endpoint_collide():
    """PRD §3.9: "Scheduling moves the campaign `DRAFT → SCHEDULED` and enforces three
    conditions: `window_start_utc` must be strictly before `window_end_utc`, `to_version` must
    differ from `from_version`, and no other campaign for the same `model` whose `status` is
    `SCHEDULED`, `ROLLING` or `PAUSED` may occupy an intersecting window. **Window collision uses
    non-strict comparisons on both sides**: a conflict exists when this campaign's
    `window_start_utc` is at or before the other's `window_end_utc` and the other's
    `window_start_utc` is at or before this campaign's `window_end_utc`. Touching endpoints
    therefore collide — a window starting at the exact instant another ends is a conflict, which is
    the opposite of the strict, buffer-widened session geometry in §3.4. Campaigns in `DRAFT`,
    `COMPLETED` or `ABORTED` occupy no window, and only same-model campaigns can collide. A
    collision is refused with `ERR_CAMPAIGN_WINDOW_CONFLICT`."

    Design: Corner/calculations/calc_campaign_window_touching_endpoints_collide
    """
    set_clock("2026-08-01T00:00:00Z")
    camp_a = get_success_data(
        api_client.create_firmware_campaign(_campaign_payload("CAMP-A"), FIRMWARE_ENGINEER)
    )
    camp_b = get_success_data(
        api_client.create_firmware_campaign(
            _campaign_payload(
                "CAMP-B",
                to_version="4.2.0",
                window_start_utc="2026-09-10T00:00:00Z",
                window_end_utc="2026-09-20T00:00:00Z",
            ),
            FIRMWARE_ENGINEER,
        )
    )
    get_success_data(api_client.schedule_firmware_campaign(camp_a["id"], FIRMWARE_ENGINEER))

    conflicting = api_client.schedule_firmware_campaign(camp_b["id"], FIRMWARE_ENGINEER)
    validate_error(conflicting, ApiErrorId.ERR_CAMPAIGN_WINDOW_CONFLICT.value)

    reread = validate_success(
        api_client.get_firmware_campaign(camp_b["id"], FIRMWARE_ENGINEER), 200
    )
    assert reread["status"] == "DRAFT", (
        f"Expected the refused campaign to stay DRAFT, got {reread['status']}"
    )

    camp_c = get_success_data(
        api_client.create_firmware_campaign(
            _campaign_payload(
                "CAMP-C",
                model="LINK",
                to_version="4.2.0",
                window_start_utc="2026-09-10T00:00:00Z",
                window_end_utc="2026-09-20T00:00:00Z",
            ),
            FIRMWARE_ENGINEER,
        )
    )
    other_model = validate_success(
        api_client.schedule_firmware_campaign(camp_c["id"], FIRMWARE_ENGINEER), 200
    )
    assert other_model["status"] == "SCHEDULED", (
        f"Expected a different-model campaign over the identical window to reach SCHEDULED, "
        f"got {other_model['status']}"
    )


# ---------------------------------------------------------------------------
# Fit exchange fees
# ---------------------------------------------------------------------------
def _exchange_environment(plan_tier: str, base_fee_cents: int) -> dict:
    """Delivered M/OPEN order with an active plan, plus stock for S/OPEN, L/OPEN and M/CLOSED."""
    env = setup_active_care_plan(
        plan_overrides={
            "plan_tier": plan_tier,
            "base_fee_cents": base_fee_cents,
            "firmware_auto_update_enabled": True,
        },
        order_overrides=ORDER_ECONOMICS,
    )
    create_inventory_pool(restock_units=5, sku="NEO-S-OPEN", dome_size="S", tip_type="OPEN")
    create_inventory_pool(restock_units=5, sku="NEO-L-OPEN", dome_size="L", tip_type="OPEN")
    create_inventory_pool(restock_units=5, sku="NEO-M-CLOSED", dome_size="M", tip_type="CLOSED")
    return env


def _request_exchange(env: dict, to_dome_size: str, to_tip_type: str):
    patient_headers = make_patient_headers(env["patient"]["id"])
    order = get_success_data(api_client.get_device_order(env["order"]["id"], patient_headers))
    return api_client.create_fit_exchange(
        order["id"],
        {
            "to_dome_size": to_dome_size,
            "to_tip_type": to_tip_type,
            "expected_device_order_version": order["version"],
            "allow_backorder": False,
        },
        patient_headers,
    )


def _complete_exchange(env: dict, to_dome_size: str, to_tip_type: str) -> dict:
    exchange = get_success_data(_request_exchange(env, to_dome_size, to_tip_type))
    get_success_data(api_client.ship_fit_exchange(exchange["id"], CARE_OPS))
    return get_success_data(
        api_client.confirm_fit_exchange(
            exchange["id"], make_patient_headers(env["patient"]["id"])
        )
    )


def _expire_trial(env: dict) -> dict:
    set_clock("2026-09-20T00:00:00Z")
    rows, _ = validate_paginated(
        api_client.list_trial_periods(CARE_OPS, params={"device_order_id": env["order"]["id"]})
    )
    assert rows, f"Setup failed: no trial period for order {env['order']['id']}"
    return rows[0]


def test_third_post_trial_exchange_costs_the_full_fee():
    """PRD §3.6: "`exchange_ordinal` is one more than the number of prior exchanges on the same
    order whose `status` is `SHIPPED` or `COMPLETED`, ordered by `created_at` ascending, and is
    always at least 1; exchanges in `REQUESTED`, `RESERVED`, `REJECTED` or `CANCELLED` never count
    toward it. If the order's trial is `ACTIVE` or `PAUSED`, the fee is 0 — exchanges are always
    free inside the trial. Otherwise, if `exchange_ordinal` is at most 2, the fee is 0, so the
    first two post-trial exchanges are free as well. Otherwise, if the patient holds a plan whose
    `plan_tier` is `PREMIUM` and whose `status` is `ACTIVE` or `PAST_DUE`, the fee is 1,900 cents
    multiplied by 0.5, rounded half up — a premium subscriber pays half. Otherwise the fee is the
    full 1,900 cents ($19.00)."

    PRD §3.6: "When the clock passes `effective_end_utc` with no authorization in `ISSUED`,
    `IN_TRANSIT`, `RECEIVED` or `INSPECTED`, the trial moves `ACTIVE → EXPIRED_KEPT`"

    Design: Corner/calculations/calc_fit_exchange_third_exchange_after_trial_charges_1900
    """
    env = _exchange_environment("STANDARD", 9900)
    trial = _expire_trial(env)
    assert trial["status"] == "EXPIRED_KEPT", (
        f"Expected the lazily expired trial to read EXPIRED_KEPT, got {trial['status']}"
    )

    first = _complete_exchange(env, "S", "OPEN")
    second = _complete_exchange(env, "L", "OPEN")

    data = validate_success(_request_exchange(env, "M", "CLOSED"), 201)

    assert data["status"] == "RESERVED", f"Expected status RESERVED, got {data['status']}"
    assert data["exchange_ordinal"] == 3, (
        f"Expected exchange_ordinal 3, got {data['exchange_ordinal']}"
    )
    assert data["exchange_fee_cents"] == 1900, (
        f"Expected exchange_fee_cents 1900, got {data['exchange_fee_cents']}"
    )

    rows, meta = validate_paginated(
        api_client.list_fit_exchanges(CARE_OPS, params={"device_order_id": env["order"]["id"]})
    )
    assert meta["total_count"] == 3, (
        f"Expected total_count 3 for the order's exchanges, got {meta['total_count']}"
    )
    fees = {row["id"]: row["exchange_fee_cents"] for row in rows}
    assert fees.get(first["id"]) == 0, (
        f"Expected the first exchange to carry exchange_fee_cents 0, got {fees.get(first['id'])}"
    )
    assert fees.get(second["id"]) == 0, (
        f"Expected the second exchange to carry exchange_fee_cents 0, got {fees.get(second['id'])}"
    )


def test_third_post_trial_exchange_is_halved_for_a_premium_subscriber():
    """PRD §3.6: "Otherwise, if the patient holds a plan whose `plan_tier` is `PREMIUM` and whose
    `status` is `ACTIVE` or `PAST_DUE`, the fee is 1,900 cents multiplied by 0.5, rounded half up —
    a premium subscriber pays half. Otherwise the fee is the full 1,900 cents ($19.00)."

    Design: Corner/calculations/calc_fit_exchange_third_exchange_after_trial_charges_1900
    """
    env = _exchange_environment("PREMIUM", 14000)
    _expire_trial(env)
    _complete_exchange(env, "S", "OPEN")
    _complete_exchange(env, "L", "OPEN")

    data = validate_success(_request_exchange(env, "M", "CLOSED"), 201)

    assert data["exchange_ordinal"] == 3, (
        f"Expected exchange_ordinal 3, got {data['exchange_ordinal']}"
    )
    assert data["exchange_fee_cents"] == 950, (
        f"Expected exchange_fee_cents 950, got {data['exchange_fee_cents']}"
    )


# ---------------------------------------------------------------------------
# Repair SLA credits
# ---------------------------------------------------------------------------
def _closed_repair(plan_tier: str, base_fee_cents: int, fault_code: str,
                   received_at: str, closed_at: str) -> dict:
    """Repair opened on a delivered order with a plan, received then resolved on the given days."""
    env = setup_active_care_plan(
        plan_overrides={
            "plan_tier": plan_tier,
            "base_fee_cents": base_fee_cents,
            "firmware_auto_update_enabled": True,
        },
        order_overrides=ORDER_ECONOMICS,
    )
    repair = get_success_data(
        api_client.create_repair_order(
            {"device_id": env["assigned_device"]["id"], "fault_code": fault_code}, CARE_OPS
        )
    )
    get_success_data(api_client.send_repair_kit(repair["id"], CARE_OPS))
    set_clock(received_at)
    get_success_data(api_client.receive_repair_order(repair["id"], REPAIR_TECH))
    get_success_data(api_client.start_repair_order(repair["id"], REPAIR_TECH))
    set_clock(closed_at)
    get_success_data(
        api_client.resolve_repair_order(repair["id"], {"resolution": "REPAIRED"}, REPAIR_TECH)
    )
    env["repair"] = repair
    return env


def test_premium_sla_credit_is_capped_after_the_multiplier_is_applied():
    """PRD §3.7: "`sla_days` is 5 when a plan is linked whose `plan_tier` is `PREMIUM`, 10 when
    the linked plan's tier is `STANDARD`, and 15 when there is no plan at all"

    PRD §3.7: "`turnaround_days` is the whole number of days between `received_at` and
    `closed_at`, floored. Days over is `turnaround_days` minus `sla_days`, floored at 0 — closing
    exactly on the SLA day yields zero. The multiplier is 2.0 when a plan is linked whose
    `plan_tier` is `PREMIUM` and 1.0 otherwise. `sla_credit_cents` is the days over multiplied by
    500 cents per day and by that multiplier, rounded half up, and then capped at 5,000 cents
    ($50.00) — the cap is applied **after** the multiplied product has been rounded."

    PRD §3.7: "Closure stamps `closed_at`, computes `turnaround_days` and `sla_credit_cents`,
    credits the linked plan's `credit_balance_cents` by the credit amount when a plan exists, sets
    the device back to `WITH_PATIENT`, and — when this repair paused the trial — drives the trial
    `PAUSED → ACTIVE`, extending `effective_end_utc` by the accumulated `paused_days`."

    Design: Corner/calculations/calc_repair_sla_credit_premium_multiplier_clipped_by_5000_cap
    """
    env = _closed_repair("PREMIUM", 14000, "NO_SOUND", "2026-08-05T00:00:00Z",
                         "2026-08-25T00:00:00Z")

    data = validate_success(
        api_client.return_repair_to_patient(env["repair"]["id"], REPAIR_TECH), 200
    )

    assert data["status"] == "RETURNED_TO_PATIENT", (
        f"Expected status RETURNED_TO_PATIENT, got {data['status']}"
    )
    assert data["sla_days"] == 5, f"Expected sla_days 5, got {data['sla_days']}"
    assert data["turnaround_days"] == 20, (
        f"Expected turnaround_days 20, got {data['turnaround_days']}"
    )
    assert data["sla_credit_cents"] == 5000, (
        f"Expected sla_credit_cents 5000, got {data['sla_credit_cents']}"
    )

    plan = validate_success(
        api_client.get_care_plan_subscription(env["plan"]["id"], CARE_OPS), 200
    )
    assert plan["credit_balance_cents"] == 5000, (
        f"Expected the plan credit_balance_cents 5000, got {plan['credit_balance_cents']}"
    )

    rows, _ = validate_paginated(
        api_client.list_trial_periods(CARE_OPS, params={"device_order_id": env["order"]["id"]})
    )
    trial = rows[0]
    assert trial["status"] == "ACTIVE", (
        f"Expected the resumed trial status ACTIVE, got {trial['status']}"
    )
    assert trial["paused_days"] == 20, (
        f"Expected the trial paused_days 20, got {trial['paused_days']}"
    )
    assert trial["effective_end_utc"].startswith("2026-10-05T00:00:00"), (
        f"Expected effective_end_utc on 2026-10-05T00:00:00, got {trial['effective_end_utc']}"
    )


def test_no_sla_credit_when_turnaround_equals_the_sla_days():
    """PRD §3.7: "Days over is `turnaround_days` minus `sla_days`, floored at 0 — closing exactly
    on the SLA day yields zero."

    PRD §3.7: "`sla_days` is 5 when a plan is linked whose `plan_tier` is `PREMIUM`, 10 when the
    linked plan's tier is `STANDARD`, and 15 when there is no plan at all"

    Design: Corner/calculations/calc_repair_sla_credit_zero_when_turnaround_equals_sla_days
    """
    env = _closed_repair("STANDARD", 9900, "BATTERY", "2026-08-05T00:00:00Z",
                         "2026-08-15T00:00:00Z")

    data = validate_success(
        api_client.return_repair_to_patient(env["repair"]["id"], REPAIR_TECH), 200
    )

    assert data["sla_days"] == 10, f"Expected sla_days 10, got {data['sla_days']}"
    assert data["turnaround_days"] == 10, (
        f"Expected turnaround_days 10, got {data['turnaround_days']}"
    )
    assert data["sla_credit_cents"] == 0, (
        f"Expected sla_credit_cents 0, got {data['sla_credit_cents']}"
    )

    plan = validate_success(
        api_client.get_care_plan_subscription(env["plan"]["id"], CARE_OPS), 200
    )
    assert plan["credit_balance_cents"] == 0, (
        f"Expected the plan credit_balance_cents 0, got {plan['credit_balance_cents']}"
    )


# ---------------------------------------------------------------------------
# Firmware cohort ordering
# ---------------------------------------------------------------------------
def _delivered_order_for_cohort(policy_id: str, ship_clock: str) -> dict:
    """One patient, one auto-update STANDARD plan and one order shipped at the given instant."""
    patient = register_patient(policy_id)
    screen_patient(patient["id"])
    order = place_order(patient["id"], **ORDER_ECONOMICS)
    get_success_data(
        api_client.create_care_plan_subscription(
            create_care_plan_payload(
                patient["id"],
                order["id"],
                plan_tier="STANDARD",
                base_fee_cents=9900,
                firmware_auto_update_enabled=True,
            ),
            make_patient_headers(patient["id"]),
        )
    )
    simulate_payment(order["id"])
    get_success_data(api_client.confirm_fit(order["id"], CARE_OPS))
    set_clock(ship_clock)
    get_success_data(api_client.ship_device_order(order["id"], CARE_OPS))
    scan_shipment(order["id"], "DELIVERED")
    devices = api_client.list_devices(CARE_OPS, params={"device_order_id": order["id"]}).json()
    assert devices["data"], f"Setup failed: no device assigned to order {order['id']}"
    return {"patient": patient, "order": order, "device": devices["data"][0]}


def test_cohort_is_ranked_by_warranty_expiry_ascending():
    """PRD §3.9: "Candidates are ordered by `warranty_expires_at` ascending — the units closest to
    falling out of warranty are updated first — with `created_at` ascending and then
    `serial_number` ascending as tie-breaks; `id` never participates in the ordering. The first
    `batch_size` candidates are taken, and for each one a `FirmwareRollout` is created in `PENDING`
    with `selection_rank` counting from 1 in that order and with `from_version_observed` captured
    from the device's current `firmware_version`. An empty candidate set is refused with
    `ERR_NO_ELIGIBLE_DEVICES`."

    PRD §3.9: "The first advance moves it `SCHEDULED → ROLLING` and requires the clock to be at
    or after `window_start_utc` and at or before `window_end_utc`"

    PRD §3.5: "stamps the device's `shipped_at` from the logical clock and sets its
    `warranty_expires_at` to `shipped_at` plus 730 days (two years)"

    Design: Corner/calculations/calc_firmware_cohort_ranks_by_warranty_then_created_then_serial
    """
    set_clock("2026-08-01T00:00:00Z")
    policy = create_state_policy()
    create_inventory_pool(restock_units=5)
    create_devices(1, serial_number="SN-A001")
    create_devices(1, serial_number="SN-B002")

    earlier = _delivered_order_for_cohort(policy["id"], "2026-08-01T00:00:00Z")
    later = _delivered_order_for_cohort(policy["id"], "2026-08-02T00:00:00Z")

    campaign = get_success_data(
        api_client.create_firmware_campaign(
            _campaign_payload(
                "COH-1",
                window_start_utc="2026-09-01T00:00:00Z",
                window_end_utc="2026-09-30T00:00:00Z",
            ),
            FIRMWARE_ENGINEER,
        )
    )
    get_success_data(api_client.schedule_firmware_campaign(campaign["id"], FIRMWARE_ENGINEER))
    set_clock("2026-09-05T00:00:00Z")

    data = validate_success(
        api_client.advance_firmware_campaign(campaign["id"], FIRMWARE_ENGINEER), 200
    )

    assert data["status"] == "ROLLING", f"Expected status ROLLING, got {data['status']}"
    assert data["rollout_count"] == 2, f"Expected rollout_count 2, got {data['rollout_count']}"
    assert data["installed_count"] == 0, (
        f"Expected installed_count 0, got {data['installed_count']}"
    )

    rows, meta = validate_paginated(
        api_client.list_campaign_rollouts(campaign["id"], FIRMWARE_ENGINEER)
    )
    assert meta["total_count"] == 2, (
        f"Expected total_count 2 for the campaign's rollouts, got {meta['total_count']}"
    )
    by_device = {row["device_id"]: row for row in rows}
    assert by_device[earlier["device"]["id"]]["selection_rank"] == 1, (
        f"Expected selection_rank 1 for the device shipped 2026-08-01, "
        f"got {by_device[earlier['device']['id']]['selection_rank']}"
    )
    assert by_device[later["device"]["id"]]["selection_rank"] == 2, (
        f"Expected selection_rank 2 for the device shipped 2026-08-02, "
        f"got {by_device[later['device']['id']]['selection_rank']}"
    )
    for row in rows:
        assert row["status"] == "PENDING", (
            f"Expected rollout status PENDING, got {row['status']}"
        )
        assert row["from_version_observed"] == "4.0.0", (
            f"Expected from_version_observed 4.0.0, got {row['from_version_observed']}"
        )

    repeat = api_client.advance_firmware_campaign(campaign["id"], FIRMWARE_ENGINEER)
    validate_error(repeat, ApiErrorId.ERR_NO_ELIGIBLE_DEVICES.value)
