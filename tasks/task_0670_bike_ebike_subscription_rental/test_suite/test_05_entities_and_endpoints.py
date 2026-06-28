"""Entity CRUD, creation defaults, uniqueness, computed counts, listing, and action endpoints.

Covers bike-model creation defaults, not-found, required-field and enum validation,
default rental_cap, computed available_count/total_bikes, duplicate email/serial,
inspection-report immutability, parent-existence on bike creation, paginated listing,
and the advance-cycle / pay action endpoints.
"""
from test_helpers import (
    api_client,
    get_success_data,
    validate_success,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    make_subscriber_headers,
    make_fleet_manager_headers,
    make_field_tech_headers,
    make_ops_admin_headers,
    make_anonymous_headers,
    create_bike_model_payload,
    inspect_payload,
    assert_bike_model,
    assert_no_version_field,
    setup_active_rental,
)
from test_helpers.fixtures import (
    set_clock, create_model, add_bikes, create_account, read_model_version,
    reserve, schedule_and_complete_initial_delivery, activate,
)

OPS = make_ops_admin_headers()
TECH = make_field_tech_headers()
ANON = make_anonymous_headers()


# ===========================================================================
# Corner/entities/create_bike_model_returns_201_with_defaults
# ===========================================================================
def test_create_bike_model_returns_201_with_defaults(api):
    """PRD §3.1: "A freshly created model starts with total_bikes and available_count both
    at zero and its status set to ACTIVE".
    PRD §2.4: "a version integer that begins at its initial value on creation".
    PRD §2.8: "Creating a new, standalone resource returns HTTP 201."

    Design: Corner/entities/create_bike_model_returns_201_with_defaults
    """
    resp = api_client.create_bike_model(
        create_bike_model_payload(name="City E", model_class="EBIKE",
                                  monthly_fee_cents=12000, daily_rate_cents=4000,
                                  purchase_price_cents=180000, deposit_cents=20000,
                                  fleet_size=10), OPS)
    data = validate_success(resp, 201)
    assert_bike_model(data)
    assert data["status"] == "ACTIVE"
    assert data["total_bikes"] == 0
    assert data["available_count"] == 0
    assert data["version"] == 1


# ===========================================================================
# Corner/entities/get_bike_model_not_found
# ===========================================================================
def test_get_bike_model_not_found(api):
    """PRD §2.5: "the first identifier that does not resolve to an existing resource
    produces ERR_NOT_FOUND (HTTP 404)".

    Design: Corner/entities/get_bike_model_not_found
    """
    resp = api_client.get_bike_model(NON_EXISTENT_UUID, OPS)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


# ===========================================================================
# Corner/entities/create_account_missing_required_field_returns_invalid_request
# ===========================================================================
def test_create_account_missing_account_type_rejected(api):
    """PRD §3.2: "An account is created with an account_type that is either SUBSCRIBER
    (an individual rider) or FLEET (a delivery-rider business), a display_name, and an
    email".
    PRD §3.3: "the request-body well-formedness check that required fields are present,
    enums are valid, and money values are non-negative (ERR_INVALID_REQUEST, HTTP 400)".

    POST /accounts omitting account_type -> ERR_INVALID_REQUEST 400.

    Design: Corner/entities/create_account_missing_required_field_returns_invalid_request
    """
    resp = api_client.create_account({"display_name": "NoType", "email": "nt@x.com"}, ANON)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


# ===========================================================================
# Corner/entities/create_account_default_rental_cap_applied
# ===========================================================================
def test_create_account_default_rental_cap_is_one(api):
    """PRD §3.2: "The optional rental_cap sets the maximum number of concurrently active
    rentals the account may hold; it defaults to 1 and must be at least 1".

    POST /accounts without rental_cap applies the default of 1.

    Design: Corner/entities/create_account_default_rental_cap_applied
    """
    resp = api_client.create_account(
        {"account_type": "SUBSCRIBER", "display_name": "Sam", "email": "sam@x.com"}, ANON)
    data = validate_success(resp, 201)
    assert data["rental_cap"] == 1


# ===========================================================================
# Corner/entities/bike_model_computed_available_count_tracks_pool
# ===========================================================================
def test_bike_model_counts_track_pool(api):
    """PRD §2.5: "total_bikes is the count of Bike rows whose model_id equals that
    model's id regardless of their status, and available_count is the count of those Bike
    rows whose bike_status is AVAILABLE".

    Adding 2 bikes makes available_count and total_bikes both 2 (server-computed).

    Design: Corner/entities/bike_model_computed_available_count_tracks_pool
    """
    model = create_model()
    add_bikes(model["id"], 2)
    data = get_success_data(api_client.get_bike_model(model["id"], OPS))
    assert data["available_count"] == 2
    assert data["total_bikes"] == 2


# ===========================================================================
# Corner/entities/bike_model_invalid_enum_class_rejected
# ===========================================================================
def test_bike_model_invalid_model_class_rejected(api):
    """PRD §3.1: "a model_class that is one of STANDARD, EBIKE, or CARGO_EBIKE".
    PRD §3.3: "the request-body well-formedness check that required fields are present,
    enums are valid, and money values are non-negative (ERR_INVALID_REQUEST, HTTP 400)".

    A model_class outside the allowed set -> ERR_INVALID_REQUEST 400.

    Design: Corner/entities/bike_model_invalid_enum_class_rejected
    """
    resp = api_client.create_bike_model(
        create_bike_model_payload(name="Bad", model_class="SCOOTER"), OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


# ===========================================================================
# Corner/entities/duplicate_account_email_rejected
# ===========================================================================
def test_duplicate_account_email_rejected(api):
    """PRD §3.2: "an email that is globally unique and compared case-insensitively across
    all accounts; a duplicate email is rejected with ERR_DUPLICATE_RESOURCE."

    Design: Corner/entities/duplicate_account_email_rejected
    """
    get_success_data(api_client.create_account(
        {"account_type": "SUBSCRIBER", "display_name": "First", "email": "dup@x.com"}, ANON))
    resp = api_client.create_account(
        {"account_type": "SUBSCRIBER", "display_name": "Second", "email": "dup@x.com"}, ANON)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE.value, 409)


# ===========================================================================
# Corner/entities/duplicate_bike_serial_rejected
# ===========================================================================
def test_duplicate_bike_serial_rejected(api):
    """PRD §3.1: "a serial_number that must be globally unique across all bikes; a serial
    collision is rejected with ERR_DUPLICATE_RESOURCE (HTTP 409)."

    Design: Corner/entities/duplicate_bike_serial_rejected
    """
    model = create_model()
    add_bikes(model["id"], 1, prefix="DUP")  # serial DUP-1
    resp = api_client.create_bike({"model_id": model["id"], "serial_number": "DUP-1"}, OPS)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE.value, 409)


# ===========================================================================
# Corner/entities/inspection_report_immutable_no_version_field
# ===========================================================================
def test_inspection_report_has_no_version_field(api):
    """PRD §2.4: "The InspectionReport is the one exception: it is written once at return
    time and never mutated. It carries only id and created_at; it has neither an
    updated_at field nor a version field."

    Design: Corner/entities/inspection_report_immutable_no_version_field
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(deposit_cents=20000, fleet_size=2)
    add_bikes(model["id"], 1)
    account = create_account(rental_cap=1)
    mv = read_model_version(model["id"], account["id"])
    rental = reserve(account["id"], model["id"], mv, rental_mode="DAILY",
                     return_due_clock="2026-06-30T00:00:00Z")
    schedule_and_complete_initial_delivery(rental["id"])
    activate(rental["id"], account["id"])
    sub = make_subscriber_headers(account["id"])
    get_success_data(api_client.request_return(rental["id"], {"return_address": "1 A St"}, sub))
    report = get_success_data(api_client.inspect_rental(rental["id"], inspect_payload(), TECH))
    fetched = get_success_data(api_client.get_inspection_report(report["id"], TECH))
    assert_no_version_field(fetched)
    assert "updated_at" not in fetched, "InspectionReport must NOT expose updated_at"
    assert "id" in fetched and "created_at" in fetched


# ===========================================================================
# Corner/entities/bike_requires_existing_parent_model
# ===========================================================================
def test_bike_requires_existing_model(api):
    """PRD §2.5: "the first identifier that does not resolve to an existing resource
    produces ERR_NOT_FOUND (HTTP 404)".

    POST /bikes referencing a non-existent model_id -> ERR_NOT_FOUND 404.

    Design: Corner/entities/bike_requires_existing_parent_model
    """
    resp = api_client.create_bike({"model_id": NON_EXISTENT_UUID, "serial_number": "S-1"}, OPS)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


# ===========================================================================
# Corner/entities/list_bike_models_paginated_envelope
# ===========================================================================
def test_list_bike_models_paginated_envelope(api):
    """PRD §2.3: "Each list response includes limit, offset, total_count, and has_more
    inside the meta object of the envelope."

    With two models and limit 1, total_count is 2 and has_more is true.

    Design: Corner/entities/list_bike_models_paginated_envelope
    """
    create_model(name="M1", model_class="STANDARD")
    create_model(name="M2", model_class="EBIKE", monthly_fee_cents=12000,
                 daily_rate_cents=4000, purchase_price_cents=180000, deposit_cents=20000)
    resp = api_client.list_bike_models(OPS, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


# ===========================================================================
# Corner/endpoints/advance_cycle_increments_completed_cycles
# ===========================================================================
def test_advance_cycle_increments_completed_cycles(api):
    """PRD §3.8: "The completed_cycles counter that drives equity is advanced by an
    OpsAdmin cycle-close capability: each invocation adds one to completed_cycles, and it
    does so only when the rental's rental_mode is MONTHLY and its lifecycle_status is
    either ACTIVE or IN_SERVICE."

    One advance-cycle call on an ACTIVE MONTHLY rental sets completed_cycles to 1.

    Design: Corner/endpoints/advance_cycle_increments_completed_cycles
    """
    ctx = setup_active_rental(rental_mode="MONTHLY", return_due_clock="2027-06-01T00:00:00Z")
    resp = api_client.advance_cycle(ctx["rental"]["id"], OPS)
    data = validate_success(resp, 200)
    assert data["completed_cycles"] == 1


# ===========================================================================
# Corner/endpoints/pay_fleet_invoice_marks_paid
# ===========================================================================
def test_pay_fleet_invoice_marks_paid(api):
    """PRD §3.11: "A fleet invoice can be marked paid by a FleetManager or OpsAdmin, which
    sets its status to PAID and recomputes the account's outstanding_balance_cents."

    POST /fleet-invoices/{id}/pay flips an ISSUED invoice to PAID.

    Design: Corner/endpoints/pay_fleet_invoice_marks_paid
    """
    ctx = setup_active_rental(rental_mode="MONTHLY", return_due_clock="2027-06-01T00:00:00Z",
                              account_type="FLEET")
    fm = make_fleet_manager_headers(ctx["account"]["id"])
    invoice = get_success_data(api_client.create_fleet_invoice(
        ctx["account"]["id"], {"cycle_index": 0}, fm))
    resp = api_client.pay_fleet_invoice(invoice["id"], fm)
    data = validate_success(resp, 200)
    assert data["status"] == "PAID"


# ===========================================================================
# Corner/errors/malformed_delivery_window_returns_invalid_request
# ===========================================================================
def test_malformed_delivery_window_returns_invalid_request(api):
    """PRD §3.4: "The window must be well-formed: window_start_clock must be strictly
    earlier than window_end_clock, otherwise the delivery is rejected with
    ERR_DELIVERY_WINDOW_CONFLICT (HTTP 409)."
    PRD §3.3: "the request-body well-formedness check that required fields are present,
    enums are valid, and money values are non-negative (ERR_INVALID_REQUEST, HTTP 400)".

    The contract addresses a malformed window (start >= end) under §3.4 as
    ERR_DELIVERY_WINDOW_CONFLICT, while the general well-formedness rule (§3.3) would
    classify it as ERR_INVALID_REQUEST; two faithful PRD-only readers could ship either,
    so this accepts both rather than pinning one.

    Design: Corner/errors/malformed_delivery_window_returns_invalid_request
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(fleet_size=2)
    add_bikes(model["id"], 1)
    account = create_account(rental_cap=1)
    mv = read_model_version(model["id"], account["id"])
    rental = reserve(account["id"], model["id"], mv)
    resp = api_client.create_delivery(
        {"rental_id": rental["id"], "delivery_type": "INITIAL", "address": "1 A St",
         "window_start_clock": "2026-06-02T12:00:00Z",
         "window_end_clock": "2026-06-02T08:00:00Z"}, OPS)
    validate_error_is_one_of(
        resp,
        [ApiErrorId.ERR_DELIVERY_WINDOW_CONFLICT.value, ApiErrorId.ERR_INVALID_REQUEST.value],
    )
