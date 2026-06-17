"""Entity creation, defaults, range/uniqueness validation, FK existence, computed
reads, and the input-validation error catalogue (corner-coverage breadth).
"""
from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    create_account,
    create_vehicle_class,
    create_vehicle,
    create_reservation,
    create_confirmed_reservation,
    assert_reservation,
    assert_corporate_account,
    setup_completed_reservation,
    invoice_reservation,
    api_client,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_corporate_account_payload,
    create_vehicle_class_payload,
    create_vehicle_payload,
    create_reservation_payload,
)

ADMIN = TEST_USERS["dispatch_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


# ---------------------------------------------------------------------------
# Corner/entities/entity_create_reservation_minimal_required_fields
# ---------------------------------------------------------------------------
def test_create_reservation_starts_in_default_state():
    """PRD §3.2: "A new reservation starts with trip_status of DRAFT,
    settlement_status of UNBILLED, and fulfillment_mode of IN_HOUSE."

    Design: Corner/entities/entity_create_reservation_minimal_required_fields
    """
    account = create_account()
    vclass = create_vehicle_class()
    resp = api_client.create_reservation(
        create_reservation_payload(account["id"], vclass["id"], trip_type="POINT_TO_POINT",
                                   pickup_at="2026-08-01T12:00:00Z",
                                   planned_drop_at="2026-08-01T13:00:00Z", estimated_miles=10),
        DISPATCHER,
    )
    res = validate_success(resp, 201)
    assert_reservation(res)
    assert res["trip_status"] == "DRAFT"
    assert res["settlement_status"] == "UNBILLED"
    assert res["fulfillment_mode"] == "IN_HOUSE"
    assert res["version"] == 1


# ---------------------------------------------------------------------------
# Corner/entities/entity_get_reservation_not_found_returns_404
# ---------------------------------------------------------------------------
def test_get_reservation_not_found_returns_404():
    """PRD §2.5: "The first identifier in a path that does not resolve to an
    existing resource causes the request to fail with ERR_NOT_FOUND before any
    later identifier or body reference is examined"

    Design: Corner/entities/entity_get_reservation_not_found_returns_404
    """
    resp = api_client.get_reservation(NON_EXISTENT_UUID, DISPATCHER)
    validate_error(resp, "ERR_NOT_FOUND")


# ---------------------------------------------------------------------------
# Corner/entities/entity_create_reservation_missing_required_field_returns_400
# ---------------------------------------------------------------------------
def test_create_reservation_missing_trip_type_returns_400():
    """PRD §2.6: "Request-body well-formedness — required fields present with
    correct types and valid enum values (ERR_INVALID_REQUEST) — is fourth."

    Design: Corner/entities/entity_create_reservation_missing_required_field_returns_400
    """
    account = create_account()
    vclass = create_vehicle_class()
    payload = {
        "corporate_account_id": account["id"],
        "vehicle_class_id": vclass["id"],
        "pickup_at": "2026-08-02T12:00:00Z",
        "planned_drop_at": "2026-08-02T13:00:00Z",
        "estimated_miles": 10,
    }  # trip_type omitted
    resp = api_client.create_reservation(payload, DISPATCHER)
    validate_error(resp, "ERR_INVALID_REQUEST")


# ---------------------------------------------------------------------------
# Corner/entities/entity_create_account_default_gratuity_applied
# ---------------------------------------------------------------------------
def test_create_account_applies_gratuity_and_grace_defaults():
    """PRD §3.1: "a default_gratuity_pct auto-applied to that account's reservations
    (defaulting to 20 and constrained to between 0 and 30 inclusive), and a
    cancellation_grace_minutes lead-time window (defaulting to 120 and required to
    be zero or greater)."

    Design: Corner/entities/entity_create_account_default_gratuity_applied
    """
    resp = api_client.create_corporate_account(
        create_corporate_account_payload(company_name="Acme", billing_email="ap@acme.com"), ADMIN
    )
    account = validate_success(resp, 201)
    assert_corporate_account(account)
    assert account["default_gratuity_pct"] == 20
    assert account["cancellation_grace_minutes"] == 120
    assert account["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Corner/entities/entity_account_range_discount_out_of_range_returns_422
# ---------------------------------------------------------------------------
def test_account_discount_above_range_returns_422():
    """PRD §3.1: "The range constraints on all percent inputs — discount within 0
    to 40, gratuity (both default_gratuity_pct and a reservation's
    gratuity_pct_override) within 0 to 30, and payout share within 0 to 90 — are
    enforced at account, affiliate, and reservation creation respectively, and a
    value outside its band is rejected with ERR_VALIDATION_RANGE."

    Design: Corner/entities/entity_account_range_discount_out_of_range_returns_422
    """
    resp = api_client.create_corporate_account(
        create_corporate_account_payload(company_name="Acme", billing_email="ap@acme.com",
                                         negotiated_discount_pct=55),
        ADMIN,
    )
    validate_error(resp, "ERR_VALIDATION_RANGE")


# ---------------------------------------------------------------------------
# Corner/entities/entity_vehicle_duplicate_plate_returns_409
# ---------------------------------------------------------------------------
def test_vehicle_duplicate_plate_returns_409():
    """PRD §3.1: "The plate must be unique across every vehicle in the system; a
    duplicate is rejected with ERR_DUPLICATE_PLATE."

    Design: Corner/entities/entity_vehicle_duplicate_plate_returns_409
    """
    vclass = create_vehicle_class()
    create_vehicle(vclass["id"], plate="BLK-DUP")
    resp = api_client.create_vehicle(create_vehicle_payload(vclass["id"], plate="BLK-DUP"), ADMIN)
    validate_error(resp, "ERR_DUPLICATE_PLATE")


# ---------------------------------------------------------------------------
# Corner/entities/entity_vehicleclass_duplicate_code_returns_409
# ---------------------------------------------------------------------------
def test_vehicle_class_duplicate_code_returns_409():
    """PRD §3.1: "The code must be unique among all vehicle classes that are not
    SUSPENDED; a colliding code is rejected with ERR_DUPLICATE_CLASS_CODE."

    Design: Corner/entities/entity_vehicleclass_duplicate_code_returns_409
    """
    create_vehicle_class(code="SEDAN")
    resp = api_client.create_vehicle_class(
        create_vehicle_class_payload(code="SEDAN", base_fare_cents=6000, per_mile_cents=260,
                                     hourly_rate_cents=13000, wait_per_minute_cents=210),
        ADMIN,
    )
    validate_error(resp, "ERR_DUPLICATE_CLASS_CODE")


# ---------------------------------------------------------------------------
# Corner/entities/entity_vehicle_create_bad_class_fk_returns_404
# ---------------------------------------------------------------------------
def test_vehicle_create_with_unknown_class_fk_returns_404():
    """PRD §2.5: "body-borne references (for example, a reservation's
    corporate_account_id and vehicle_class_id, or an assignment's chauffeur_id and
    vehicle_id) are likewise checked for existence, and any unresolved reference
    yields ERR_NOT_FOUND."

    Design: Corner/entities/entity_vehicle_create_bad_class_fk_returns_404
    """
    resp = api_client.create_vehicle(create_vehicle_payload(NON_EXISTENT_UUID, plate="BLK-Z"), ADMIN)
    validate_error(resp, "ERR_NOT_FOUND")


# ---------------------------------------------------------------------------
# Corner/entities/entity_computed_outstanding_balance_after_invoice
# ---------------------------------------------------------------------------
def test_outstanding_balance_after_invoice_equals_final_total():
    """PRD §2.9: "A corporate account's outstanding_balance_cents is the sum of
    final_total_cents over that account's reservations whose settlement_status is
    INVOICED, less amounts that have moved on to SETTLED or WRITTEN_OFF; it is
    refreshed whenever a billing event changes a reservation's settlement state."

    Design: Corner/entities/entity_computed_outstanding_balance_after_invoice
    """
    set_clock("2026-08-03T09:00:00Z")
    # Zero chargeable wait (arrived 12:05, boarded 12:10 => raw 5 < grace 15) so
    # final equals the estimate, 9098.
    ctx = setup_completed_reservation(
        "2026-08-03T12:05:00Z", "2026-08-03T12:10:00Z",
        account_overrides={"negotiated_discount_pct": 10, "default_gratuity_pct": 20},
        class_overrides={"code": "SEDAN", "base_fare_cents": 5000, "per_mile_cents": 250,
                         "hourly_rate_cents": 12000, "wait_per_minute_cents": 200,
                         "included_wait_minutes": 15},
        res_overrides={"pickup_at": "2026-08-03T12:00:00Z",
                       "planned_drop_at": "2026-08-03T13:00:00Z",
                       "estimated_miles": 12.4, "tolls_cents": 350},
    )
    assert ctx["reservation_final"]["final_total_cents"] == 9098
    invoice_reservation(ctx["reservation_id"])
    account = validate_success(api_client.get_corporate_account(ctx["account_id"], DISPATCHER), 200)
    assert account["outstanding_balance_cents"] == 9098, (
        f"balance == sum of INVOICED finals = 9098, got {account['outstanding_balance_cents']}"
    )
