"""Catalog and customer-book records: defaults, required fields, computed fields,
listing envelope, and the try-on kit item's deliberately reduced field set."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_customer,
    assert_try_on_kit_item,
    create_customer_payload,
    create_prescription_payload,
    make_customer_headers,
    new_customer,
    new_frame,
    new_kit,
    new_material,
    new_verified_prescription,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, STORE


def test_customer_registration_seeds_its_declared_defaults(api):
    """PRD §3.1: "A **customer** is registered with a `full_name`, a unique `email`,
    a `dob` date of birth in ISO 8601 UTC, an optional `insurance_policy_id`
    pointing at a registered plan (null by default — the customer is then
    self-pay), and an optional `fsa_balance_cents` flexible-spending balance of
    zero or more that defaults to zero. Two computed fields are seeded at
    registration: `lifetime_kit_count` at zero and `return_risk_score` at zero."

    Design: Corner/entities/customer_creation_applies_declared_defaults
    """
    payload = create_customer_payload(
        full_name="Dee Fault", email="dee.fault@example.com", dob="1990-01-01T00:00:00Z"
    )
    resp = api.create_customer(payload, ADMIN)
    data = validate_success(resp, 201)

    assert_customer(data)
    assert data["fsa_balance_cents"] == 0, "fsa_balance_cents defaults to zero"
    assert data["insurance_policy_id"] is None, "insurance_policy_id is null by default"
    assert data["lifetime_kit_count"] == 0, "lifetime_kit_count is seeded at zero"
    assert data["return_risk_score"] == 0, "return_risk_score is seeded at zero"


def test_reading_an_unknown_frame_returns_frame_not_found(api):
    """PRD §2.9: "**Path existence.** Every resource named in the URL path exists,
    validated left to right, so that the leftmost missing identifier is the one
    reported. The not-found codes are `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_FRAME_NOT_FOUND`, `ERR_PRESCRIPTION_NOT_FOUND`, `ERR_KIT_NOT_FOUND`,
    `ERR_ORDER_NOT_FOUND`, `ERR_LAB_ORDER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`,
    `ERR_WARRANTY_CLAIM_NOT_FOUND` and `ERR_APPOINTMENT_NOT_FOUND`, all HTTP 404."

    Design: Corner/entities/get_frame_with_unknown_id_returns_not_found
    """
    resp = api.get_frame(NON_EXISTENT_UUID, STORE)
    validate_error(resp, ApiErrorId.ERR_FRAME_NOT_FOUND.value)


def test_prescription_without_pd_mm_is_an_invalid_request(api):
    """PRD §2.9: "**Request schema.** Required fields present, types correct, enum
    members valid, money and count fields not negative, `expires_at` strictly after
    `issued_at`, `due_date` strictly after `ship_date`, `end_at` strictly after
    `start_at` — otherwise `ERR_INVALID_REQUEST` (400). Applies to every write."
    PRD §3.2: "The payload names the `customer_id` it belongs to, the four
    measurement powers — `od_sphere` and `od_cylinder` for the right eye,
    `os_sphere` and `os_cylinder` for the left — the `pd_mm` pupillary distance,
    the `issued_at` date the prescription was written and the `expires_at` date it
    lapses, which must be strictly after `issued_at`."

    Design: Corner/entities/prescription_missing_required_pd_returns_invalid_request
    """
    customer = new_customer(full_name="Nora Field", email="nora@example.com")
    payload = create_prescription_payload(customer["id"])
    payload.pop("pd_mm")

    resp = api.create_prescription(payload, make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_client_supplied_lens_upcharge_is_discarded_and_recomputed(api):
    """PRD §3.5: "Once the optics pass, the system computes `lens_upcharge_cents` in
    the following pinned order, in integer cents, and freezes it on the order. It
    is computed exactly once, at order creation, and no later operation ever
    recomputes it."
    PRD §3.6: "**Step one: the subtotal.** `subtotal_cents` is the frame's
    `price_cents` plus the order's frozen `lens_upcharge_cents`."

    Design: Corner/entities/order_computed_money_fields_input_ignored
    """
    frame = new_frame(price_cents=9500, min_pd_mm=54.0, max_pd_mm=70.0)
    material = new_material(code="M160", base_price_cents=6000, material_index=1.60)
    customer = new_customer(full_name="Cora Computed", email="cora@example.com")
    rx = new_verified_prescription(
        customer["id"],
        od_sphere=-2.00,
        od_cylinder=0.00,
        os_sphere=-2.00,
        os_cylinder=0.00,
        pd_mm=62.0,
    )

    resp = api.create_order(
        {
            "customer_id": customer["id"],
            "prescription_id": rx["id"],
            "frame_id": frame["id"],
            "material_option_id": material["id"],
            "delivery_method": "SHIP",
            # The client tries to dictate a computed money field.
            "lens_upcharge_cents": 1,
        },
        make_customer_headers(customer["id"]),
    )
    order = validate_success(resp, 201)

    # The material's own base price is the whole upcharge: power is 2.00, so no
    # high-power surcharge; no coatings and no prism.
    assert order["lens_upcharge_cents"] == 6000
    assert order["subtotal_cents"] == 15500
    assert order["discount_cents"] == 0, "a 15,500c subtotal sits below the 25,000c tier"
    assert order["customer_due_cents"] == 15500


def test_customer_list_reports_the_four_pagination_fields(api):
    """PRD §2.3: "List responses expose four pagination fields inside the envelope's
    `meta` object: `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/entities/customer_list_returns_pagination_envelope
    """
    new_customer(full_name="P One", email="p1@example.com")
    new_customer(full_name="P Two", email="p2@example.com")

    resp = api.list_customers(ADMIN, params={"limit": 1, "offset": 1})
    data, meta = validate_paginated(resp)

    assert resp.json()["response_type"] == "array"
    assert len(data) == 1, "a limit of 1 returns exactly one row"
    assert meta["total_count"] == 2
    assert meta["has_more"] is False, "offset 1 + limit 1 exhausts a 2-row collection"
    assert meta["limit"] == 1
    assert meta["offset"] == 1


def test_try_on_kit_item_carries_no_version_and_no_updated_at(api):
    """PRD §2.4: "A try-on kit item — the row that records "sample unit of frame X is
    currently in kit Y" — carries only `id` and `created_at`. It has **no**
    `updated_at` field and **no** `version` field, and clients must not expect
    either to be present in its representation."
    PRD §3.4: "Each item records its `kit_id`, its `frame_id`, and an `outcome` that
    starts at `PENDING`, and each item's creation decrements its frame's
    `tryon_available` by one."

    Design: Corner/entities/try_on_kit_item_is_immutable_and_carries_no_version
    """
    frame = new_frame(tryon_stock=1, min_pd_mm=50.0, max_pd_mm=75.0)
    customer = new_customer(full_name="Imm Utable", email="imm@example.com")
    kit = new_kit(customer["id"], [frame["id"]])

    resp = api.list_kit_items(kit["id"], STORE)
    items, _meta = validate_paginated(resp)

    assert len(items) == 1
    item = items[0]
    assert_try_on_kit_item(item)
    assert item["frame_id"] == frame["id"]
    assert item["kit_id"] == kit["id"]
    assert item["outcome"] == "PENDING"
    assert "version" not in item
    assert "updated_at" not in item
