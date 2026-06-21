"""Catalog creation (gear units, rate cards, gear types, customers), system/computed
field handling, listing/pagination, and role-based access control.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS, make_renter_headers, build_user_headers,
    assert_gear_unit, assert_customer,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["shop_admin_headers"]
AGENT = TEST_USERS["rental_agent_headers"]


# ===========================================================================
# Queue B — entities (corner)
# ===========================================================================

def test_create_gear_unit_returns_201_with_defaults(api):
    """PRD §3.3: "A physical **gear unit** itself is created by a `ShopAdmin` from a
    `gear_type_id`, a `rate_card_id`, and a unique `asset_tag`, and is born `AVAILABLE`
    with `condition` `GOOD`."
    PRD §2.4: "The `version` starts at 1 when the resource is created"

    Design: Corner/entities/create_gear_unit_returns_201_with_defaults
    """
    gt = fx.create_gear_type(category="KAYAK", name="Rec K", size_label="M")
    rc = fx.create_rate_card(gt["id"])
    unit = validate_success(
        api.create_gear_unit({"gear_type_id": gt["id"], "rate_card_id": rc["id"],
                              "asset_tag": "K-NEW"}, ADMIN), expected_status=201)
    assert_gear_unit(unit)
    assert unit["availability"] == "AVAILABLE"
    assert unit["condition"] == "GOOD"
    assert unit["version"] == 1


def test_get_reservation_not_found_returns_404(api):
    """PRD §2.6: "the server validates their existence left to right and rejects the
    request at the first identifier that does not resolve, returning `ERR_NOT_FOUND`."

    Design: Corner/entities/get_reservation_not_found_returns_404
    """
    resp = api.get_reservation(NON_EXISTENT_UUID, AGENT)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_rate_card_missing_required_field_returns_validation(api):
    """PRD §2.9: "first, payload well-formedness — required fields present, enums and
    types valid, every cents value non-negative ... failing which the request is
    rejected with `ERR_VALIDATION` at HTTP 400."
    PRD §3.1: "the `hourly_cents` base rate, the `daily_cents` rate that caps a 24-hour
    block, the `seasonal_flat_cents` rate charged once for an entire seasonal rental"

    Design: Corner/entities/create_rate_card_missing_required_field_returns_validation
    """
    gt = fx.create_gear_type(category="SUP", name="X", size_label="10ft")
    # Omit hourly_cents (a required money field).
    resp = api.create_rate_card({
        "gear_type_id": gt["id"], "daily_cents": 3000, "seasonal_flat_cents": 20000,
        "deposit_cents": 5000, "damage_waiver_cents_per_day": 400,
        "late_fee_cents_per_hour": 800, "loss_fee_cents": 20000}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_create_gear_type_default_active_true_applied(api):
    """PRD §3.1: "A gear type may flag `requires_lesson_for_beginner`, which defaults to
    false; when true, a beginner renter must attach a lesson before they can confirm.
    The `active` flag defaults to true and governs whether new units may be created
    under the type"

    Design: Corner/entities/create_gear_type_default_active_true_applied
    """
    gt = validate_success(
        api.create_gear_type({"category": "SKI", "name": "Default Ski", "size_label": "170cm"},
                             ADMIN), expected_status=201)
    assert gt["active"] is True
    assert gt["requires_lesson_for_beginner"] is False


def test_reservation_system_fields_ignore_client_input(api):
    """PRD §3.3: "The reservation is born with `lifecycle_status` of `QUOTED` and
    `payment_status` of `UNPAID`"
    PRD §2.4: "The `version` starts at 1 when the resource is created"

    Design: Corner/entities/reservation_system_fields_ignore_client_input
    """
    fx.set_clock("2026-06-01T08:00:00Z")
    s = fx.setup_catalog(category="SUP", asset_tag="SYS-1",
                         customer_overrides={"email": "pat@x.com", "skill_level": "EXPERT"})
    res = fx.create_reservation(s["customer"]["id"], s["gear_unit"]["id"], s["gear_unit"]["version"],
                                "2026-06-01T08:00:00Z", "2026-06-01T10:00:00Z", actor=AGENT)
    assert res["lifecycle_status"] == "QUOTED"
    assert res["version"] == 1


def test_create_gear_type_invalid_category_enum_rejected(api):
    """PRD §3.1: "its `category` is one of `KAYAK`, `SKI`, `SUP`, or `SNOWBOARD`"
    PRD §2.9: "first, payload well-formedness — required fields present, enums and
    types valid ... failing which the request is rejected with `ERR_VALIDATION` at
    HTTP 400."

    Design: Corner/entities/create_gear_type_invalid_category_enum_rejected
    """
    resp = api.create_gear_type({"category": "JETSKI", "name": "Bad", "size_label": "M"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_reservation_create_wrong_gear_unit_not_found(api):
    """PRD §2.6: "Where an endpoint path or request body names several resources, the
    server validates their existence left to right and rejects the request at the first
    identifier that does not resolve, returning `ERR_NOT_FOUND`."

    Design: Corner/entities/reservation_create_wrong_gear_unit_not_found
    """
    s = fx.setup_catalog(category="KAYAK", asset_tag="NF-1",
                         customer_overrides={"email": "qi@x.com", "skill_level": "EXPERT"})
    resp = api.create_reservation(
        {"customer_id": s["customer"]["id"], "gear_unit_id": NON_EXISTENT_UUID,
         "pickup_at": "2026-06-02T08:00:00Z", "due_at": "2026-06-02T10:00:00Z",
         "expected_gear_unit_version": s["gear_unit"]["version"]}, AGENT)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_customer_computed_standing_good_on_create(api):
    """PRD §3.2: "At registration the customer's derived fields are seeded: `standing`
    is `GOOD`, `strike_points` is 0, and `open_loss_balance_cents` is 0."

    Design: Corner/entities/customer_computed_standing_good_on_create
    """
    cust = validate_success(
        api.create_customer({"full_name": "Ron Im", "email": "ron@x.com"},
                            TEST_USERS["renter_headers"]), expected_status=201)
    assert_customer(cust)
    assert cust["standing"] == "GOOD"
    assert cust["strike_points"] == 0
    assert cust["open_loss_balance_cents"] == 0


# ===========================================================================
# Queue B — endpoints (corner)
# ===========================================================================

def test_list_reservations_filtered_by_customer_paginates(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned ... Every
    list response carries the pagination bookkeeping in the envelope's `meta` object:
    `limit`, `offset`, `total_count`, and `has_more`."
    PRD Endpoints: "List reservations, optionally by customer/unit/lifecycle"

    Design: Corner/endpoints/list_reservations_filtered_by_customer_paginates
    """
    fx.set_clock("2026-06-15T08:00:00Z")
    gt = fx.create_gear_type(category="KAYAK", name="Pag", size_label="M")
    rc = fx.create_rate_card(gt["id"])
    unit1 = fx.create_gear_unit(gt["id"], rc["id"], asset_tag="PAG-1")
    unit2 = fx.create_gear_unit(gt["id"], rc["id"], asset_tag="PAG-2")
    cust = fx.create_customer(actor=AGENT, email="fin@x.com", skill_level="EXPERT")
    fx.create_reservation(cust["id"], unit1["id"], unit1["version"],
                          "2026-06-15T08:00:00Z", "2026-06-15T10:00:00Z", actor=AGENT)
    fx.create_reservation(cust["id"], unit2["id"], unit2["version"],
                          "2026-06-15T08:00:00Z", "2026-06-15T10:00:00Z", actor=AGENT)
    data, meta = validate_paginated(
        api.list_reservations(AGENT, params={"customer_id": cust["id"], "limit": 1, "offset": 0}))
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


# ===========================================================================
# Queue B — rbac (corner)
# ===========================================================================

def test_renter_cannot_checkout_returns_unauthorized(api):
    """PRD §2.1: "A `RentalAgent` runs the rental counter: checkout, check-in, and
    settlement"
    PRD §2.1: "When an authenticated principal attempts an operation their role is not
    permitted to perform, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/renter_cannot_checkout_returns_unauthorized
    """
    fx.set_clock("2026-06-19T08:00:00Z")
    gt = fx.create_gear_type(category="KAYAK", name="Rb", size_label="M")
    rc = fx.create_rate_card(gt["id"])
    unit = fx.create_gear_unit(gt["id"], rc["id"], asset_tag="RB-1")
    cust = fx.create_customer(actor="RENTER", email="ira@x.com", skill_level="EXPERT")
    cust_id = cust["id"]
    res = fx.create_reservation(cust_id, unit["id"], unit["version"],
                                "2026-06-19T08:00:00Z", "2026-06-19T10:00:00Z", actor="RENTER")
    fx.confirm_reservation(res["id"], actor="RENTER", customer_id=cust_id)
    resp = api.checkout_reservation(res["id"], {"condition_rating": "GOOD"},
                                    make_renter_headers(cust_id))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_renter_cannot_confirm_other_renters_reservation(api):
    """PRD §2.1: "a `Renter` may only confirm, cancel, attach add-ons to, or dispute
    against reservations whose `customer_id` equals their own `X-User-ID`; an attempt
    to act on another customer's reservation is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/renter_cannot_confirm_other_renters_reservation
    """
    fx.set_clock("2026-06-20T08:00:00Z")
    gt = fx.create_gear_type(category="KAYAK", name="Own", size_label="M")
    rc = fx.create_rate_card(gt["id"])
    unit = fx.create_gear_unit(gt["id"], rc["id"], asset_tag="OWN-1")
    cust_b = fx.create_customer(actor="RENTER", full_name="Cust B", email="custb@x.com",
                                skill_level="EXPERT")
    cust_a = fx.create_customer(actor="RENTER", full_name="Cust A", email="custa@x.com",
                                skill_level="EXPERT")
    res = fx.create_reservation(cust_b["id"], unit["id"], unit["version"],
                                "2026-06-20T08:00:00Z", "2026-06-20T10:00:00Z",
                                actor="RENTER")
    # Customer A tries to confirm customer B's reservation.
    resp = api.confirm_reservation(res["id"], make_renter_headers(cust_a["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_missing_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying values that cannot be
    validated, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    resp = api.create_gear_type({"category": "KAYAK", "name": "NoAuth", "size_label": "M"}, {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
