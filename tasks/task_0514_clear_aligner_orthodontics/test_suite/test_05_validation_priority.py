"""Validation-priority conflict tests (PRD §2.10 fixed evaluation order).

PRD §2.10 pins a single deterministic order, so these tests assert the
higher-priority error fires when two checks could both fail.
"""
from test_helpers import (
    validate_success, validate_error,
    setup_submitted_plan,
    api_client, TEST_USERS, NON_EXISTENT_UUID,
)

BILLING = TEST_USERS["billing_headers"]
MFG = TEST_USERS["manufacturing_headers"]


def test_activate_under_review_unsettled_returns_invalid_state_over_fiscal(api):
    """PRD §2.10: "then whether the target resource is in a state from which the
    requested transition is defined (`ERR_INVALID_STATE`), then the
    optimistic-concurrency version check on guarded writes ... Only after all of
    those pass are the domain-specific business rules of Section 3 evaluated."
    PRD §3.8: "An activation attempt that meets neither condition is rejected
    with `ERR_PAYMENT_NOT_SETTLED` (HTTP 422)."

    A case still UNDER_REVIEW (no financing, money unsettled) fails the state
    check (priority 5) before the fiscal check (priority 19), so the returned
    error is ERR_INVALID_STATE, never ERR_PAYMENT_NOT_SETTLED.

    Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_on_activate
    """
    ctx = setup_submitted_plan(proposed_step_count=10, list_price_cents=300000)
    # Case is UNDER_REVIEW (plan SUBMITTED, never approved), no financing exists.
    res = api.activate_case(ctx["case"]["id"], MFG)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    case = validate_success(api.get_case(ctx["case"]["id"], BILLING), 200)
    assert case["status"] == "UNDER_REVIEW", case["status"]


def test_activate_intake_pending_returns_invalid_state_over_fiscal(api):
    """PRD §2.10: "then whether the target resource is in a state from which the
    requested transition is defined (`ERR_INVALID_STATE`) ... Only after all of
    those pass are the domain-specific business rules of Section 3 evaluated."
    PRD §3.8: "Activating a case moves it from `PLAN_APPROVED` to `ACTIVE`".

    A second instance of the same priority pair: a fresh INTAKE_PENDING case with
    no settled money still fails the state precondition first, returning
    ERR_INVALID_STATE rather than the fiscal ERR_PAYMENT_NOT_SETTLED.

    Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_on_activate
    """
    from test_helpers import create_patient, create_case
    patient = create_patient(state_code="CA")
    case = create_case(patient["id"], intake_channel="IMPRESSION_KIT", list_price_cents=300000)
    res = api.activate_case(case["id"], MFG)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    fetched = validate_success(api.get_case(case["id"], BILLING), 200)
    assert fetched["status"] == "INTAKE_PENDING", fetched["status"]


def test_shipment_bad_fk_and_inverted_window_returns_fk_not_found(api):
    """PRD §2.10: "then existence of body foreign keys (`ERR_FK_NOT_FOUND`),
    then whether the target resource is in a state ... Only after all of those
    pass are the domain-specific business rules of Section 3 evaluated."
    PRD §3.8: "The `window_start` must be strictly before `window_end`; an
    inverted or empty window is rejected with `ERR_WINDOW_INVERTED` (HTTP 422)."

    A POST /shipments carrying a non-existent step_id AND an inverted window
    fails the FK-existence check (priority 4) before the temporal check
    (priority 16), so it returns ERR_FK_NOT_FOUND.

    Design: Difficulty/priority_pair_validation_conflict/existence_before_temporal_on_shipment_create
    """
    res = api.create_shipment(
        {
            "step_id": NON_EXISTENT_UUID,
            "carrier_code": "GROUND",
            "window_start": "2026-05-05T00:00:00Z",
            "window_end": "2026-05-02T00:00:00Z",
        },
        MFG,
    )
    validate_error(res, "ERR_FK_NOT_FOUND", expected_status=404)


def test_shipment_bad_fk_with_valid_window_returns_fk_not_found(api):
    """PRD §2.10: "then existence of body foreign keys (`ERR_FK_NOT_FOUND`) ...
    Only after all of those pass are the domain-specific business rules of
    Section 3 evaluated."

    Confirming the existence layer's behavior with a well-formed window: a
    non-existent step_id alone still yields ERR_FK_NOT_FOUND, so the FK check is
    the gate the inverted-window companion test contrasts against.

    Design: Difficulty/priority_pair_validation_conflict/existence_before_temporal_on_shipment_create
    """
    res = api.create_shipment(
        {
            "step_id": NON_EXISTENT_UUID,
            "carrier_code": "GROUND",
            "window_start": "2026-05-02T00:00:00Z",
            "window_end": "2026-05-05T00:00:00Z",
        },
        MFG,
    )
    validate_error(res, "ERR_FK_NOT_FOUND", expected_status=404)
