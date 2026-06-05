"""Registration, activation, and freeze/unfreeze lifecycle.

Corner design index:
  entities / create_membership_plan_returns_201_with_all_fields
  entities / get_member_not_found_returns_404
  entities / create_member_missing_required_email_returns_invalid_request
  entities / create_member_invalid_plan_fk_returns_not_found
  entities / duplicate_member_email_returns_conflict
  entities / member_system_fields_generated_on_register
  state_machines / activate_already_active_member_returns_invalid_state
  state_machines / activate_before_invoice_paid_returns_activation_not_paid
  state_machines / cancel_already_cancelled_member_returns_invalid_state
  state_machines / freeze_blocked_when_suspended
  state_machines / freeze_cap_exceeded_returns_conflict
  state_machines / dues_invoice_pay_resets_cycle_credits
"""
from test_helpers import (
    validate_success, validate_error,
    setup_active_member, setup_suspended_member,
    register_member, create_plan, create_location, set_clock,
    PLAN_PLUS, PLAN_BASIC,
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
)

STAFF = TEST_USERS["staff_headers"]


# ===========================================================================
# entities
# ===========================================================================
def test_create_plan_returns_201_with_all_fields(api):
    """PRD §3.1: "A plan also carries an archived flag, which starts false"
    PRD §2.4: "The version field is an integer that starts at 1 on creation"

    Design: Corner/entities/create_membership_plan_returns_201_with_all_fields
    """
    resp = api.create_membership_plan(
        {"tier": "ELITE", "monthly_dues_cents": 9000, "included_class_credits": 12,
         "pt_discount_pct": 0.4, "contract_term_months": 12, "early_termination_fee_cents": 20000,
         "max_freeze_days_per_term": 45, "guest_passes_per_cycle": 4}, STAFF
    )
    data = validate_success(resp, 201)
    assert data["tier"] == "ELITE"
    assert data["monthly_dues_cents"] == 9000
    assert data["archived"] is False
    assert data["version"] == 1


def test_get_member_not_found_returns_404(api):
    """PRD §2.10: "the existence and non-archived status of every referenced resource is
    verified, evaluating path identifiers and body foreign keys left to right (ERR_NOT_FOUND)."

    Design: Corner/entities/get_member_not_found_returns_404
    """
    resp = api.get_member(NON_EXISTENT_UUID, STAFF)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_register_missing_email_returns_invalid_request(api):
    """PRD §2.10: "request-body well-formedness is checked: required fields present and
    correctly typed, enum values valid, and the temporal invariants ... (ERR_INVALID_REQUEST)."

    Design: Corner/entities/create_member_missing_required_email_returns_invalid_request
    """
    plan = create_plan(PLAN_BASIC)
    location = create_location()
    resp = api.create_member(
        {"plan_id": plan["id"], "home_location_id": location["id"], "full_name": "No Email",
         "period_start": "2026-06-10T00:00:00Z", "period_end": "2026-07-01T00:00:00Z",
         "due_date": "2026-06-10T00:00:00Z"}, STAFF
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_register_invalid_plan_fk_returns_not_found(api):
    """PRD §2.10: "Then the existence and non-archived status of every referenced resource is
    verified, evaluating path identifiers and body foreign keys left to right (ERR_NOT_FOUND)."

    Design: Corner/entities/create_member_invalid_plan_fk_returns_not_found
    """
    location = create_location()
    resp = api.create_member(
        {"plan_id": NON_EXISTENT_UUID, "home_location_id": location["id"], "full_name": "Bad FK",
         "email": "badfk@example.com", "period_start": "2026-06-10T00:00:00Z",
         "period_end": "2026-07-01T00:00:00Z", "due_date": "2026-06-10T00:00:00Z"}, STAFF
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_duplicate_member_email_returns_conflict(api):
    """PRD §3.2: "The email must be unique across non-archived members; a collision is rejected
    with ERR_DUPLICATE_EMAIL."

    Design: Corner/entities/duplicate_member_email_returns_conflict
    """
    plan = create_plan(PLAN_BASIC)
    location = create_location()
    set_clock("2026-06-10T00:00:00Z")
    validate_success(
        api.create_member(
            {"plan_id": plan["id"], "home_location_id": location["id"], "full_name": "First",
             "email": "dup@example.com", "period_start": "2026-06-10T00:00:00Z",
             "period_end": "2026-07-01T00:00:00Z", "due_date": "2026-06-10T00:00:00Z"}, STAFF
        ), 201
    )
    resp = api.create_member(
        {"plan_id": plan["id"], "home_location_id": location["id"], "full_name": "Second",
         "email": "dup@example.com", "period_start": "2026-06-10T00:00:00Z",
         "period_end": "2026-07-01T00:00:00Z", "due_date": "2026-06-10T00:00:00Z"}, STAFF
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMAIL.value)


def test_member_system_fields_generated_on_register(api):
    """PRD §3.2: "On successful registration the new member starts with membership_status of
    PENDING, dues_status of CURRENT, and contract_status of IN_COOLING_OFF."

    Design: Corner/entities/member_system_fields_generated_on_register
    """
    plan = create_plan(PLAN_PLUS)
    location = create_location()
    member, _ = register_member(plan["id"], location["id"], clock="2026-06-10T00:00:00Z")
    data = validate_success(api.get_member(member["id"], STAFF), 200)
    assert data["membership_status"] == "PENDING"
    assert data["dues_status"] == "CURRENT"
    assert data["contract_status"] == "IN_COOLING_OFF"
    assert data["version"] == 1


# ===========================================================================
# state_machines — activation
# ===========================================================================
def test_activate_before_invoice_paid_returns_activation_not_paid(api):
    """PRD §3.2: "It is permitted only once the joining invoice has reached PAID; an attempt to
    activate before that invoice is settled is rejected with ERR_ACTIVATION_NOT_PAID (HTTP 409)."

    Design: Corner/state_machines/activate_before_invoice_paid_returns_activation_not_paid
    """
    plan = create_plan(PLAN_PLUS)
    location = create_location()
    member, _ = register_member(plan["id"], location["id"], clock="2026-06-10T00:00:00Z")
    resp = api.activate_member(member["id"], STAFF)
    validate_error(resp, ApiErrorId.ERR_ACTIVATION_NOT_PAID.value)
    data = validate_success(api.get_member(member["id"], STAFF), 200)
    assert data["membership_status"] == "PENDING"


def test_activate_already_active_returns_invalid_state(api):
    """PRD §2.5: "A newly registered member begins PENDING"
    PRD §3.2: "Activation is the bridge from PENDING to ACTIVE, performed by a StaffManager."

    Design: Corner/state_machines/activate_already_active_member_returns_invalid_state
    """
    setup = setup_active_member(plan_shape=PLAN_PLUS)
    member = setup["member"]
    resp = api.activate_member(member["id"], STAFF)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    data = validate_success(api.get_member(member["id"], STAFF), 200)
    assert data["membership_status"] == "ACTIVE"


def test_cancel_already_cancelled_returns_invalid_state(api):
    """PRD §3.7: "Cancelling a membership ... is permitted from any non-terminal lifecycle state
    — PENDING, ACTIVE, or FROZEN — provided the member is not already CANCELLED."

    Design: Corner/state_machines/cancel_already_cancelled_member_returns_invalid_state
    """
    setup = setup_active_member(plan_shape=PLAN_PLUS)
    member = setup["member"]
    validate_success(api.cancel_member(member["id"], STAFF), 200)
    resp = api.cancel_member(member["id"], STAFF)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# state_machines — freeze
# ===========================================================================
def test_freeze_blocked_when_suspended(api):
    """PRD §3.3: "A member whose dues axis has reached SUSPENDED cannot be frozen; the attempt
    is rejected with ERR_FREEZE_BLOCKED_BY_DUES (HTTP 409)."

    Design: Corner/state_machines/freeze_blocked_when_suspended
    """
    setup = setup_suspended_member(plan_shape=PLAN_PLUS)
    member = setup["member"]
    assert member["dues_status"] == "SUSPENDED"
    resp = api.freeze_member(member["id"], {"freeze_days": 5}, STAFF)
    validate_error(resp, ApiErrorId.ERR_FREEZE_BLOCKED_BY_DUES.value)


def test_freeze_cap_exceeded_returns_conflict(api):
    """PRD §3.3: "when the requested freeze_days is added to the member's existing
    cumulative_freeze_days, the sum may not exceed the plan's max_freeze_days_per_term; a request
    that would push the total over that cap is rejected with ERR_FREEZE_CAP_EXCEEDED (HTTP 409)."

    Design: Corner/state_machines/freeze_cap_exceeded_returns_conflict
    """
    setup = setup_active_member(plan_shape=PLAN_BASIC, clock="2026-06-10T00:00:00Z")  # cap 14
    member = setup["member"]
    resp = api.freeze_member(member["id"], {"freeze_days": 20}, STAFF)
    validate_error(resp, ApiErrorId.ERR_FREEZE_CAP_EXCEEDED.value)
    data = validate_success(api.get_member(member["id"], STAFF), 200)
    assert data["membership_status"] == "ACTIVE"
    assert data["cumulative_freeze_days"] == 0


# ===========================================================================
# state_machines — dues pay resets cycle credits
# ===========================================================================
def test_paying_joining_invoice_resets_cycle_credits(api):
    """PRD §3.8: "Payment moves the invoice to PAID and resets the member's cycle allowances for
    the new cycle: class_credits_remaining is reset to the plan's included_class_credits and
    guest_passes_remaining to the plan's guest_passes_per_cycle."

    Design: Corner/state_machines/dues_invoice_pay_resets_cycle_credits
    """
    plan = create_plan(PLAN_PLUS)  # included_class_credits 8, guest_passes_per_cycle 2
    location = create_location()
    member, joining = register_member(plan["id"], location["id"], clock="2026-06-10T00:00:00Z")
    inv_data = validate_success(api.pay_dues_invoice(joining["id"], STAFF), 200)
    assert inv_data["status"] == "PAID"
    member_data = validate_success(api.get_member(member["id"], STAFF), 200)
    assert member_data["class_credits_remaining"] == 8
    assert member_data["guest_passes_remaining"] == 2
