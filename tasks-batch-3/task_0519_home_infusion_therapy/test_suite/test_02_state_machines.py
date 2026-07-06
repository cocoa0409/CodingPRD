"""State-machine transitions: referrals, orders, visits, compounds, kits, plus the
day-counting calculations that depend on visit states.

Translates Queue B (Corner) instances from sections: state_machines, calculations.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_visiting_nurse_headers,
    fixtures,
    factories as F,
)

INTAKE = TEST_USERS["intake_coordinator_headers"]
PHARM = TEST_USERS["pharmacist_headers"]
BILLER = TEST_USERS["biller_headers"]
WAREHOUSE = TEST_USERS["warehouse_clerk_headers"]


def test_reject_referral_from_received(api):
    """PRD 3.2: "or rejects it, moving `RECEIVED` to `REJECTED` — and `REJECTED` is terminal."
    PRD 3.2: "Each transition increments the referral's `version`."

    Design: Corner/state_machines/reject_referral_from_received
    """
    plan = fixtures.create_payer_plan()
    patient = fixtures.create_patient(plan["id"])
    referral = validate_success(
        api.create_referral(F.create_referral_payload(patient_id=patient["id"]), INTAKE),
        expected_status=201,
    )
    resp = api.reject_referral(referral["id"], INTAKE)
    data = validate_success(resp)
    assert data["status"] == "REJECTED"
    assert data["version"] == 2, f"version should be 2 after reject, got {data['version']}"


def test_accept_referral_twice_idempotency_error(api):
    """PRD 3.2: "Acceptance is permitted only while the referral is still `RECEIVED ...
    Attempting either transition from any other state yields `ERR_INVALID_STATE`."

    Design: Corner/state_machines/accept_referral_twice_idempotency_error
    """
    plan = fixtures.create_payer_plan()
    patient = fixtures.create_patient(plan["id"])
    referral = fixtures.create_accepted_referral(patient["id"])
    resp = api.accept_referral(referral["id"], INTAKE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_terminal_referral_rejected_cannot_accept(api):
    """PRD 3.2: "or rejects it, moving `RECEIVED` to `REJECTED` — and `REJECTED` is terminal ...
    Attempting either transition from any other state yields `ERR_INVALID_STATE`."

    Design: Corner/state_machines/terminal_referral_rejected_cannot_accept
    """
    plan = fixtures.create_payer_plan()
    patient = fixtures.create_patient(plan["id"])
    referral = validate_success(
        api.create_referral(F.create_referral_payload(patient_id=patient["id"]), INTAKE),
        expected_status=201,
    )
    validate_success(api.reject_referral(referral["id"], INTAKE))
    resp = api.accept_referral(referral["id"], INTAKE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_nonspecialty_submit_goes_straight_to_released(api):
    """PRD 3.3: "If the drug's `is_specialty` is false, the same submit instead moves the order directly from `DRAFT` to `RELEASED`, skipping authorization entirely."

    Design: Corner/state_machines/nonspecialty_submit_goes_straight_to_released
    """
    ctx = fixtures.setup_draft_order(drug_overrides={"is_specialty": False})
    resp = api.submit_order(ctx["order"]["id"], PHARM)
    data = validate_success(resp)
    assert data["status"] == "RELEASED", f"expected RELEASED, got {data['status']}"


def test_first_visit_complete_activates_order(api):
    """PRD 3.7: "When the visit being completed is the first `COMPLETED` visit for its order, completing it cascades the order from `RELEASED` to `ACTIVE`. On every completion the server recomputes the order's `administered_days` as the count of that order's nursing visits that are in `COMPLETED`."

    Design: Corner/state_machines/first_visit_complete_activates_order
    """
    ctx = fixtures.setup_released_nonspecialty_order(order_overrides={"daily_dose_mg": 1000})
    nurse = fixtures.add_nurse(ctx)
    visit = fixtures.schedule_visit(
        ctx["order"]["id"], nurse["id"], start_at="2026-06-10T09:00:00Z", duration_min=120
    )
    resp = api.complete_visit(visit["id"], make_visiting_nurse_headers(nurse["id"]))
    validate_success(resp)
    order = validate_success(api.get_order(ctx["order"]["id"], PHARM))
    assert order["status"] == "ACTIVE"
    assert order["administered_days"] == 1


def test_visit_miss_from_scheduled(api):
    """PRD 3.7: "A visit may instead be marked missed, moving `SCHEDULED` to `MISSED ...
    visits in `SCHEDULED`, `MISSED`, or `CANCELLED` are excluded from the count."

    Design: Corner/state_machines/visit_miss_from_scheduled
    """
    ctx = fixtures.setup_released_nonspecialty_order(order_overrides={"daily_dose_mg": 1000})
    nurse = fixtures.add_nurse(ctx)
    visit = fixtures.schedule_visit(
        ctx["order"]["id"], nurse["id"], start_at="2026-06-10T09:00:00Z", duration_min=120
    )
    resp = api.miss_visit(visit["id"], make_visiting_nurse_headers(nurse["id"]))
    data = validate_success(resp)
    assert data["status"] == "MISSED"
    order = validate_success(api.get_order(ctx["order"]["id"], PHARM))
    assert order["administered_days"] == 0


def test_deliver_compound_from_compounded(api):
    """PRD 3.4: "A `COMPOUNDED` batch may then be advanced from `COMPOUNDED` to `DELIVERED`."
    PRD 2.9: "Reserving vials for a compound debits `on_hand_vials`; wasting a compound that had reserved vials credits them back."

    Design: Corner/state_machines/deliver_compound_from_compounded
    """
    ctx = fixtures.setup_compounded_order(
        daily_dose_mg=2000, scheduled_days=7, lot_total_vials=100,
        drug_overrides={"awp_per_vial_cents": 4250}, activate=False,
    )
    resp = api.deliver_compound(ctx["compound"]["id"], PHARM)
    data = validate_success(resp)
    assert data["status"] == "DELIVERED"
    drug = validate_success(api.get_drug(ctx["drug"]["id"], PHARM))
    assert drug["on_hand_vials"] == 86, f"on_hand unchanged by deliver, got {drug['on_hand_vials']}"


def test_ship_supply_kit_from_picking(api):
    """PRD 3.8: "A `WarehouseClerk` ships it, moving `PICKING` to `SHIPPED`, but only while the kit is still `PICKING` and the order it supports is in `RELEASED` or `ACTIVE`."

    Design: Corner/state_machines/ship_supply_kit_from_picking
    """
    ctx = fixtures.setup_released_nonspecialty_order(order_overrides={"daily_dose_mg": 1000})
    kit = validate_success(
        api.create_supply_kit(
            F.create_supply_kit_payload(
                order_id=ctx["order"]["id"], kit_type="WEEKLY_RESUPPLY", line_count=3
            ),
            WAREHOUSE,
        ),
        expected_status=201,
    )
    resp = api.ship_supply_kit(kit["id"], WAREHOUSE)
    data = validate_success(resp)
    assert data["status"] == "SHIPPED"


# --- calculations (non-stub) ---
def test_per_diem_estimate_rate_selected_by_therapy_category(api):
    """PRD 3.12: "The **per-diem line**, written to `per_diem_cents`, is the plan's per-diem rate for the order drug's therapy category, multiplied by the billed-day count. The
    rate is selected from the plan's per_diem_rate_cents map using the drug's
    therapy_category."
    PRD 3.12: "Under `ESTIMATE` the billed-day count is the order's `scheduled_days`."

    Design: Corner/calculations/per_diem_estimate_rate_selected_by_therapy_category
    """
    ctx = fixtures.setup_active_order_with_completed_visits(
        num_completed=1,
        scheduled_days=3,
        drug_overrides={
            "therapy_category": "AMINOGLYCOSIDE_OR_VANCO",
            "awp_per_vial_cents": 2000,
        },
        plan_overrides={"per_diem_rate_cents": {"AMINOGLYCOSIDE_OR_VANCO": 12500}},
        order_overrides={"daily_dose_mg": 1000},
    )
    claim = fixtures.create_estimate_claim(ctx["order"]["id"])
    data = validate_success(api.get_claim(claim["id"], BILLER))
    assert data["variant"] == "ESTIMATE"
    assert data["billed_days"] == 3
    assert data["per_diem_cents"] == 37500, f"expected 37500, got {data['per_diem_cents']}"


def test_administered_days_excludes_missed_and_cancelled(api):
    """PRD 3.7: "the server recomputes the order's `administered_days` as the count of that order's nursing visits that are in `COMPLETED` (visits in `SCHEDULED`, `MISSED`, or `CANCELLED` are excluded from the count)."

    Design: Corner/calculations/administered_days_excludes_missed_and_cancelled
    """
    ctx = fixtures.setup_released_nonspecialty_order(order_overrides={"daily_dose_mg": 1000})
    nurse = fixtures.add_nurse(ctx)
    v1 = fixtures.schedule_visit(
        ctx["order"]["id"], nurse["id"], start_at="2026-06-10T09:00:00Z", duration_min=120
    )
    v2 = fixtures.schedule_visit(
        ctx["order"]["id"], nurse["id"], start_at="2026-06-11T09:00:00Z", duration_min=120
    )
    fixtures.complete_visit(v1["id"], nurse["id"])
    validate_success(api.miss_visit(v2["id"], make_visiting_nurse_headers(nurse["id"])))
    order = validate_success(api.get_order(ctx["order"]["id"], PHARM))
    assert order["administered_days"] == 1, f"MISSED excluded; expected 1, got {order['administered_days']}"
