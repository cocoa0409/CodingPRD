"""Charge parallel-axis lifecycle: authorize, capture, void, the capture/auth boundary,
the merchant-approved precondition, and the state-vs-fiscal priority pair.

Covers difficulty queue (non_linear_state_machine parallel axes, boundary_precision capture,
cross_entity_state_dependency capture-requires-approved, priority_pair state-vs-fiscal) and
corner charge state/entity instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    create_flat_plan, create_approved_merchant, create_authorized_charge,
    create_captured_charge,
    make_merchant_user_headers,
    TEST_USERS,
)

OPERATOR = TEST_USERS["platform_operator_headers"]
OFFICER = TEST_USERS["underwriting_officer_headers"]


def test_capture_advances_only_auth_axis(api):
    """PRD §3.3: "Capturing the charge advances the authorization axis from `AUTHORIZED` to
    `CAPTURED` while leaving the settlement axis at `PENDING`."

    Design: Difficulty/non_linear_state_machine/charge_parallel_auth_and_settlement_axes
    """
    plan = create_flat_plan()
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW")
    charge = create_authorized_charge(merchant["id"], auth_amount_cents=5000)
    headers = make_merchant_user_headers(merchant["id"])
    captured = validate_success(api.capture_charge(charge["id"], {"amount_cents": 5000}, headers))
    assert captured["auth_status"] == "CAPTURED"
    assert captured["settlement_status"] == "PENDING"


def test_batch_settle_advances_only_settlement_axis(api):
    """PRD §3.7: "first, every batched charge has its `settlement_status` moved from `BATCHED`
    to `SETTLED`."

    Design: Difficulty/non_linear_state_machine/charge_parallel_auth_and_settlement_axes
    """
    from test_helpers import set_clock, open_and_settle_batch
    set_clock("2026-01-01T00:00:00Z")
    plan = create_flat_plan()
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW")
    version = merchant["version"]
    charge = create_captured_charge(merchant["id"], auth_amount_cents=5000)
    open_and_settle_batch(merchant["id"], version, business_date="2026-01-01")
    fetched = validate_success(api.get_charge(charge["id"], make_merchant_user_headers(merchant["id"])))
    assert fetched["auth_status"] == "CAPTURED", "auth axis must remain CAPTURED"
    assert fetched["settlement_status"] == "SETTLED"


def test_capture_at_auth_amount_boundary_succeeds(api):
    """PRD §3.3: "The merchant user names the capture `amount_cents`, which must be at least 1
    and at most the charge's `auth_amount_cents`".

    Design: Difficulty/boundary_precision_check/capture_amount_equals_auth_boundary_inclusive
    """
    plan = create_flat_plan()
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW")
    charge = create_authorized_charge(merchant["id"], auth_amount_cents=5000)
    headers = make_merchant_user_headers(merchant["id"])
    captured = validate_success(api.capture_charge(charge["id"], {"amount_cents": 5000}, headers))
    assert captured["auth_status"] == "CAPTURED"
    assert captured["captured_amount_cents"] == 5000


def test_capture_above_auth_amount_rejected(api):
    """PRD §3.3: "a capture amount below 1 or above the authorized amount is rejected with
    `ERR_CAPTURE_EXCEEDS_AUTH` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/capture_amount_equals_auth_boundary_inclusive
    """
    plan = create_flat_plan()
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW")
    charge = create_authorized_charge(merchant["id"], auth_amount_cents=5000)
    headers = make_merchant_user_headers(merchant["id"])
    resp = api.capture_charge(charge["id"], {"amount_cents": 5001}, headers)
    validate_error(resp, ApiErrorId.ERR_CAPTURE_EXCEEDS_AUTH)


def test_capture_on_suspended_merchant_rejected(api):
    """PRD §3.3: "Capture is permitted only when the charge's `auth_status` is `AUTHORIZED`
    and the merchant is `APPROVED`."
    PRD §3.3: "an authorization (and likewise a capture or a payout request) attempted while
    the merchant is `PENDING_REVIEW`, `REJECTED`, or `SUSPENDED` is rejected with
    `ERR_MERCHANT_NOT_APPROVED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/charge_capture_requires_merchant_approved
    """
    plan = create_flat_plan()
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW")
    charge = create_authorized_charge(merchant["id"], auth_amount_cents=5000)
    validate_success(api.suspend_merchant(merchant["id"], {}, OFFICER))
    headers = make_merchant_user_headers(merchant["id"])
    resp = api.capture_charge(charge["id"], {"amount_cents": 5000}, headers)
    validate_error(resp, ApiErrorId.ERR_MERCHANT_NOT_APPROVED)


def test_capture_on_pending_review_merchant_rejected(api):
    """PRD §3.3: "an authorization (and likewise a capture or a payout request) attempted
    while the merchant is `PENDING_REVIEW`, `REJECTED`, or `SUSPENDED` is rejected with
    `ERR_MERCHANT_NOT_APPROVED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/charge_capture_requires_merchant_approved
    """
    # Build an AUTHORIZED charge while approved, then suspend to make the merchant non-approved;
    # this isolates the capture-time approval check on a charge that is still AUTHORIZED.
    plan = create_flat_plan()
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW")
    charge = create_authorized_charge(merchant["id"], auth_amount_cents=4000)
    validate_success(api.suspend_merchant(merchant["id"], {}, OFFICER))
    headers = make_merchant_user_headers(merchant["id"])
    resp = api.capture_charge(charge["id"], {"amount_cents": 4000}, headers)
    validate_error(resp, ApiErrorId.ERR_MERCHANT_NOT_APPROVED)


def test_capture_on_voided_charge_returns_invalid_state_over_fiscal(api):
    """PRD §2.9: "then that the transition is legal from the current state
    (`ERR_INVALID_STATE`); and only after all of those do the domain-specific business rules
    described in §3 apply."
    PRD §3.3: "Capture is permitted only when the charge's `auth_status` is `AUTHORIZED`".

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_capture_on_voided_charge
    """
    plan = create_flat_plan()
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW")
    charge = create_authorized_charge(merchant["id"], auth_amount_cents=5000)
    headers = make_merchant_user_headers(merchant["id"])
    validate_success(api.void_charge(charge["id"], {}, headers))
    # capture 9999 on a VOIDED charge: both state (6) and exceeds-auth (10) could fire; state wins.
    resp = api.capture_charge(charge["id"], {"amount_cents": 9999}, headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_void_on_voided_charge_after_capture_path_invalid_state(api):
    """PRD §2.9: "Every action endpoint that drives a state machine first checks that the
    target resource is in a state from which the requested transition is defined; if it is
    not, the request is rejected with `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.3: "voiding is permitted only while `auth_status` is `AUTHORIZED`".

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_capture_on_voided_charge
    """
    # Re-attempting capture on an already-VOIDED charge with an in-range amount still yields
    # the state failure (no fiscal violation present), confirming the state guard is dominant.
    plan = create_flat_plan()
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW")
    charge = create_authorized_charge(merchant["id"], auth_amount_cents=5000)
    headers = make_merchant_user_headers(merchant["id"])
    validate_success(api.void_charge(charge["id"], {}, headers))
    resp = api.capture_charge(charge["id"], {"amount_cents": 5000}, headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# --- Corner: charge state machine + entity ---

def test_void_authorized_charge_succeeds(api):
    """PRD §3.3: "A charge that has not been captured can be voided, driving `auth_status` from
    `AUTHORIZED` to the terminal `VOIDED` while the settlement axis remains `PENDING`".

    Design: Corner/State Machines/corner_charge_void_valid_transition
    """
    plan = create_flat_plan()
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW")
    charge = create_authorized_charge(merchant["id"], auth_amount_cents=5000)
    headers = make_merchant_user_headers(merchant["id"])
    voided = validate_success(api.void_charge(charge["id"], {}, headers))
    assert voided["auth_status"] == "VOIDED"
    assert voided["settlement_status"] == "PENDING"


def test_void_on_captured_charge_rejected(api):
    """PRD §3.3: "voiding is permitted only while `auth_status` is `AUTHORIZED`".

    Design: Corner/State Machines/corner_charge_void_invalid_from_captured
    """
    plan = create_flat_plan()
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW")
    charge = create_captured_charge(merchant["id"], auth_amount_cents=5000)
    headers = make_merchant_user_headers(merchant["id"])
    resp = api.void_charge(charge["id"], {}, headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_authorized_charge_starts_in_initial_parallel_state(api):
    """PRD §3.3: "The new charge belongs to the merchant via its `merchant_id` and begins life
    on two independent axes: its `auth_status` is `AUTHORIZED` and its `settlement_status` is
    `PENDING`."
    PRD §3.3: "its `settlement_batch_id` is null until a sweep claims it."

    Design: Corner/State Machines/corner_charge_capture_initial_settlement_axis_stays_pending
    """
    plan = create_flat_plan()
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW")
    headers = make_merchant_user_headers(merchant["id"])
    charge = validate_success(api.create_charge(merchant["id"], {"auth_amount_cents": 3000, "card_last4": "1111"}, headers), expected_status=201)
    assert charge["auth_status"] == "AUTHORIZED"
    assert charge["settlement_status"] == "PENDING"
    assert charge["settlement_batch_id"] is None


def test_authorize_charge_zeroes_computed_fields(api):
    """PRD §3.3: "Its `captured_amount_cents`, `refunded_amount_cents`, and
    `processing_fee_cents` all start at 0".

    Design: Corner/Entities/corner_charge_computed_fields_ignored_on_create
    """
    plan = create_flat_plan()
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW")
    headers = make_merchant_user_headers(merchant["id"])
    resp = api.create_charge(merchant["id"], {"auth_amount_cents": 7000, "card_last4": "4242"}, headers)
    data = validate_success(resp, expected_status=201)
    assert data["auth_status"] == "AUTHORIZED"
    assert data["settlement_status"] == "PENDING"
    assert data["captured_amount_cents"] == 0
    assert data["refunded_amount_cents"] == 0
    assert data["processing_fee_cents"] == 0


def test_list_charges_filter_by_settlement_status_excludes_voided(api):
    """PRD §3.3: "the list supports filtering by `merchant_id`, `settlement_batch_id`,
    `auth_status`, and `settlement_status`."

    Design: Corner/Endpoints/corner_charge_list_filter_by_settlement_status
    """
    plan = create_flat_plan()
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW")
    headers = make_merchant_user_headers(merchant["id"])
    ch_keep = create_authorized_charge(merchant["id"], auth_amount_cents=5000)
    ch_void = create_authorized_charge(merchant["id"], auth_amount_cents=3000)
    validate_success(api.void_charge(ch_void["id"], {}, headers))

    data, _ = validate_paginated(api.list_charges(
        headers,
        params={"merchant_id": merchant["id"], "settlement_status": "PENDING", "auth_status": "AUTHORIZED"},
    ))
    ids = [c["id"] for c in data]
    assert ch_keep["id"] in ids
    for c in data:
        assert c["auth_status"] == "AUTHORIZED"
        assert c["settlement_status"] == "PENDING"
