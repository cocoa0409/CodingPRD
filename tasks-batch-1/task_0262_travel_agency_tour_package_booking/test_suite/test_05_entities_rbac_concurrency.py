"""Entity creation/validation, RBAC, optimistic concurrency, derived-field reconciliation,
scheduled milestone due dates, and the user-context header guard.

Covers corner sections: entities, rbac, validations (auth), and cross_cutting_complexity
_layers (OCC, derived field, scheduled actions).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_agency_payload, create_customer_payload, create_tour_package_payload,
    add_traveler_payload, reserve_payload,
)
from test_helpers.fixtures import (
    create_agency, create_customer, create_supplier, create_published_package,
    open_draft_booking, add_travelers, attach_insurance, request_component,
    setup_draft_booking_with_travelers, get_booking, _booking_version,
    get_milestone_id, AGENT, ADMIN,
)
from test_helpers.test_users import make_customer_headers
from test_helpers import api_client


# ─── Entities: creation, required, defaults, computed, not-found ─────────
def test_create_agency_returns_201_with_system_fields(api):
    """PRD §2.5: "The `version` is an integer that starts at its initial value when the
    resource is created and increments by one on every mutation."
    PRD §3.1: "The setup of the platform begins with an `AgencyAdmin`, who creates an
    `Agency` by supplying its `name` and, optionally, its `currency` (defaulting to
    `USD`)."

    Design: Corner/entities/create_agency_returns_201_with_system_fields
    """
    res = api.create_agency(create_agency_payload(name="Globe", currency="USD"), ADMIN)
    agency = validate_success(res, 201)
    assert agency["name"] == "Globe"
    assert agency["version"] == 1


def test_create_customer_missing_email_invalid_request(api):
    """PRD §3.1: "A `Customer` is created with its `agency_id`, an `email`, and a
    `full_name`."
    PRD §5 / §2.2: a malformed body missing a required field is rejected with
    `ERR_INVALID_REQUEST`.

    email has no default; omitting it => ERR_INVALID_REQUEST (400).

    Design: Corner/entities/create_customer_missing_email_returns_invalid_request
    """
    agency = create_agency(clock=None)
    res = api.create_customer({"agency_id": agency["id"], "full_name": "No Email"}, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_tour_package_default_deposit_pct(api):
    """PRD §3.2: "`deposit_pct`, the deposit as a percentage of the grand total, an
    integer between 1 and 100 inclusive that defaults to 20".

    Omitting deposit_pct applies default 20; package born DRAFT.

    Design: Corner/entities/tour_package_default_deposit_pct_applied
    """
    agency = create_agency(clock=None)
    package = validate_success(api.create_tour_package(
        {"agency_id": agency["id"], "title": "P", "base_price_per_person_cents": 100000}, AGENT), 201)
    assert package["deposit_pct"] == 20
    assert package["status"] == "DRAFT"


def test_customer_wallet_credit_starts_zero(api):
    """PRD §3.1: "A new customer starts with `wallet_credit_cents` of 0".

    Design: Corner/entities/customer_wallet_credit_computed_starts_zero
    """
    agency = create_agency(clock=None)
    customer = validate_success(api.create_customer(
        {"agency_id": agency["id"], "email": "c@x.com", "full_name": "C"}, ADMIN), 201)
    assert customer["wallet_credit_cents"] == 0


def test_get_nonexistent_customer_not_found(api):
    """PRD §2.4: "When a path names a resource that does not exist within the agency, the
    request is rejected with `ERR_NOT_FOUND`."

    Design: Corner/entities/get_customer_nonexistent_returns_not_found
    """
    create_agency(clock=None)
    res = api.get_customer("00000000-0000-0000-0000-000000000000", ADMIN)
    validate_error(res, "ERR_NOT_FOUND")


def test_duplicate_customer_email_rejected(api):
    """PRD §3.1: "The `email` must be unique within the agency: a create that reuses an
    email already present in that agency is rejected with `ERR_DUPLICATE_EMAIL`."

    Design: Corner/entities/duplicate_customer_email_rejected
    """
    agency = create_agency(clock=None)
    create_customer(agency["id"], email="c@x.com", full_name="C1")
    res = api.create_customer({"agency_id": agency["id"], "email": "c@x.com", "full_name": "C2"}, ADMIN)
    validate_error(res, "ERR_DUPLICATE_EMAIL")


def test_supplier_invalid_kind_enum_rejected(api):
    """PRD §3.1: "A `Supplier` is created with its owning `agency_id`, a `name`, a `kind`
    — one of `FLIGHT`, `HOTEL`, or `ACTIVITY`".
    PRD §5: a malformed body with an invalid enum is rejected with `ERR_INVALID_REQUEST`.

    kind=BUS is not a valid enum => ERR_INVALID_REQUEST (400).

    Design: Corner/entities/supplier_invalid_kind_enum_rejected
    """
    agency = create_agency(clock=None)
    res = api.create_supplier({"agency_id": agency["id"], "name": "X", "kind": "BUS"}, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_invalid_agency_id_reference_on_customer_create(api):
    """PRD §2.4: "Whenever a request body carries a foreign key, that reference must
    resolve to an existing resource within the same agency, or the request is rejected
    with `ERR_INVALID_REFERENCE`. This referential check applies to the creation of
    customers, suppliers, tour packages, bookings, travelers, components, insurance
    policies, and payments."

    Design: Corner/entities/invalid_agency_id_reference_on_customer_create
    """
    res = api.create_customer(
        {"agency_id": "00000000-0000-0000-0000-000000000000", "email": "c@x.com",
         "full_name": "C"}, ADMIN)
    validate_error(res, "ERR_INVALID_REFERENCE")


def test_list_bookings_pagination_envelope(api):
    """PRD §2.3: "Every list response carries the pagination bookkeeping in the `meta`
    object of the envelope: `limit`, `offset`, `total_count` (the total number of matching
    items across all pages), and `has_more` (true when items remain beyond the current
    page)."

    Design: Corner/entities/list_bookings_pagination_envelope
    """
    agency = create_agency(clock=None)
    customer = create_customer(agency["id"])
    package = create_published_package(agency["id"], base_price_per_person_cents=100000)
    open_draft_booking(agency["id"], customer["id"], package["id"])
    data, meta = validate_paginated(api.list_bookings(
        AGENT, params={"agency_id": agency["id"], "limit": 10, "offset": 0}))
    assert meta["total_count"] >= 1
    assert meta["has_more"] is False


# ─── RBAC ────────────────────────────────────────────────────────────────
def test_customer_cannot_create_tour_package(api):
    """PRD §3.2: "A `TourPackage` is the template a booking instantiates, and only a
    `TravelAgent` may create one."
    PRD §2.1: "When the role is recognized but is not permitted to perform the requested
    operation — or when an ownership check fails — the request is rejected with
    `ERR_FORBIDDEN_FOR_ROLE`."

    Design: Corner/rbac/customer_cannot_create_tour_package
    """
    agency = create_agency(clock=None)
    customer = create_customer(agency["id"])
    res = api.create_tour_package(
        {"agency_id": agency["id"], "title": "P", "base_price_per_person_cents": 100000},
        make_customer_headers(customer["id"]))
    validate_error(res, "ERR_FORBIDDEN_FOR_ROLE")


def test_supplier_cannot_confirm_other_suppliers_component(api):
    """PRD §2.1: "a supplier may confirm or reject only those components whose
    `supplier_id` equals `X-User-ID`. A confirm or reject against a component owned by a
    different supplier is rejected with `ERR_FORBIDDEN_FOR_ROLE`."

    sup2 confirms sup1's component => ERR_FORBIDDEN_FOR_ROLE; component stays REQUESTED.

    Design: Corner/rbac/supplier_cannot_confirm_other_suppliers_component
    """
    agency = create_agency(clock=None)
    customer = create_customer(agency["id"])
    sup1 = create_supplier(agency["id"], kind="FLIGHT", name="Air1", auto_confirm=False)
    sup2 = create_supplier(agency["id"], kind="FLIGHT", name="Air2", auto_confirm=False)
    package = create_published_package(agency["id"], base_price_per_person_cents=100000)
    booking = open_draft_booking(agency["id"], customer["id"], package["id"])
    component = request_component(booking["id"], sup1["id"], kind="FLIGHT",
                                  starts_at="2026-06-01T08:00:00.000Z",
                                  ends_at="2026-06-01T12:00:00.000Z")
    from test_helpers.test_users import make_supplier_headers
    res = api.confirm_component(component["id"], make_supplier_headers(sup2["id"]))
    validate_error(res, "ERR_FORBIDDEN_FOR_ROLE")
    component_after = validate_success(api.get_component(component["id"], AGENT), 200)
    assert component_after["status"] == "REQUESTED"


# ─── Validations: user-context header ────────────────────────────────────
def test_unknown_role_rejected(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` does not name a
    recognized role, the request is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/validations/missing_user_context_header_rejected
    """
    headers = {"X-User-ID": "someone", "X-User-Role": "NotARole"}
    res = api.create_agency(create_agency_payload(name="Globe", currency="USD"), headers)
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")


# ─── Cross-cutting: OCC, derived field, scheduled milestone due ──────────
def test_occ_stale_version_on_second_traveler_add(api):
    """PRD §2.7: "A second add that still carries the pre-add `expected_booking_version`
    is therefore acting on a booking whose price basis has already shifted underneath it,
    and it is rejected on the stale-version check rather than silently re-quoting against
    an outdated subtotal."
    PRD §2.7: "The server compares it against the booking's current `version`; if they do
    not match — because some other writer has advanced the booking since the client read
    it — the request is rejected with `ERR_STALE_VERSION` and an HTTP 412 status, and no
    mutation occurs."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_second_traveler_add
    """
    agency = create_agency(clock=None)
    customer = create_customer(agency["id"])
    package = create_published_package(agency["id"], base_price_per_person_cents=100000)
    booking = open_draft_booking(agency["id"], customer["id"], package["id"])
    v0 = booking["version"]
    validate_success(api.add_traveler(booking["id"], add_traveler_payload(v0, full_name="T1"), AGENT), 201)
    # Second add reuses the now-stale v0.
    res = api.add_traveler(booking["id"], add_traveler_payload(v0, full_name="T2"), AGENT)
    validate_error(res, "ERR_STALE_VERSION")


def test_grand_total_recomputed_on_insurance_attach(api):
    """PRD §3.4: "The booking's `insurance_premium_cents` is the sum of the `premium_cents`
    of all `ACTIVE` insurance policies attached to it, and its `grand_total_cents` is
    `subtotal_cents` plus `insurance_premium_cents`."
    PRD §3.4: "a `PREMIUM` policy costs 4000 cents per traveler".

    2 travelers base 100000 (subtotal 200000), PREMIUM 2*4000=8000 => grand 208000.

    Design: Corner/cross_cutting_complexity_layers/derived_grand_total_recomputed_on_insurance_attach
    """
    ctx = setup_draft_booking_with_travelers(
        num_travelers=2, clock=None,
        pkg_overrides={"base_price_per_person_cents": 100000, "min_group_size_for_discount": 5})
    attach_insurance(ctx["booking_id"], "PREMIUM")
    booking = get_booking(ctx["booking_id"])
    assert booking["insurance_premium_cents"] == 8000
    assert booking["grand_total_cents"] == 208000


def test_balance_milestone_due_date_from_departure_window(api):
    """PRD §3.8: "the balance's `due_date` is the booking's `departure_date` minus the
    package's `balance_due_days_before_departure` days."

    departure 2026-06-30, balance_due_days 30 => BALANCE due 2026-05-31T00:00:00.000Z.

    Design: Corner/cross_cutting_complexity_layers/scheduled_balance_milestone_due_date_from_clock
    """
    agency = create_agency(clock="2026-01-01T00:00:00.000Z")
    customer = create_customer(agency["id"])
    supplier = create_supplier(agency["id"], kind="FLIGHT", auto_confirm=True)
    package = create_published_package(agency["id"], base_price_per_person_cents=100000,
                                       deposit_pct=20, balance_due_days_before_departure=30)
    booking = open_draft_booking(agency["id"], customer["id"], package["id"],
                                 departure_date="2026-06-30T00:00:00.000Z")
    add_travelers(booking["id"], 1, booking["version"])
    request_component(booking["id"], supplier["id"], kind="FLIGHT",
                      starts_at="2026-06-30T08:00:00.000Z", ends_at="2026-06-30T12:00:00.000Z")
    version = _booking_version(booking["id"])
    validate_success(api.reserve_booking(booking["id"], reserve_payload(version), AGENT), 200)
    balance = validate_success(api.get_milestone(get_milestone_id(booking["id"], "BALANCE"), AGENT), 200)
    assert balance["due_date"] == "2026-05-31T00:00:00.000Z"
