"""Entity-surface claims: creation defaults, envelope shape, pagination,
not-found handling, required fields, computed flags, and scale-ticket
immutability (PRD §2.2-§2.4, §3.1-§3.2, §3.8)."""
from test_helpers import (
    ADMIN,
    BILLING,
    DISPATCHER,
    DRIVER,
    NON_EXISTENT_UUID,
    PERMIT_CLERK,
    ApiErrorId,
    assert_customer,
    assert_load,
    assert_scale_ticket,
    create_customer,
    create_customer_payload,
    create_load_for_customer,
    create_load_payload,
    create_scale_ticket_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_shipper_headers,
    plan_load,
    setup_standard_load_cleared,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_customer_creation_defaults_and_envelope(api):
    """PRD §3.1: "A `PlatformAdmin` registers each shipper by providing a
    `company_name`, which must be unique across customers, and a
    `credit_limit_cents`, which must be greater than zero. The customer record
    comes into existence with `status` `ACTIVE` and an
    `outstanding_balance_cents` of zero."
    PRD §2.2: "All successful API responses (those with 2xx status codes)
    follow this standard envelope format in their JSON body"

    Design: Corner/entities/customer_creation_defaults_and_envelope
    """
    resp = api.create_customer(
        create_customer_payload(
            company_name="Envelope Co", credit_limit_cents=500000
        ),
        ADMIN,
    )
    body = resp.json()
    # Fixed envelope (PRD §2.2): meta identifiers and object response type.
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
    data = validate_success(resp, 201)
    assert_customer(data)
    assert data["status"] == "ACTIVE"
    assert data["outstanding_balance_cents"] == 0
    assert data["version"] == 1
    # Server-minted identity — no client control.
    assert is_valid_uuid(data["id"])


def test_shipper_load_creation_owner_defaults(api):
    """PRD §3.2: "A `Shipper` opens a shipment by creating a load with a
    free-text `cargo_description`, the declared `gross_weight_lbs`, cargo
    `width_in`, `height_in`, and `length_in` in whole inches, free-text
    `origin` and `destination`, an optional `cargo_requires_tarp` flag that
    defaults to false, and an optional `declared_value_cents` that defaults to
    zero and may not be negative."
    PRD §3.2: "The new load's `customer_id` is taken from the calling shipper's
    `X-User-ID`, its `status` starts at `DRAFT`, and `survey_result` starts
    null."

    Design: Corner/entities/shipper_load_creation_owner_defaults
    """
    customer = create_customer("Default Shippers", 500000)
    resp = api.create_load(
        create_load_payload(
            cargo_description="Crated pump", gross_weight_lbs=30000,
            width_in=96, height_in=60, length_in=300,
            origin="Bakersfield CA", destination="Fresno CA",
        ),
        make_shipper_headers(customer["id"]),
    )
    data = validate_success(resp, 201)
    assert_load(data)
    # Ownership bound from the header, not the payload.
    assert data["customer_id"] == customer["id"]
    assert data["status"] == "DRAFT"
    assert data["version"] == 1
    # Documented defaults applied.
    assert data["cargo_requires_tarp"] is False
    assert data["declared_value_cents"] == 0
    assert data["survey_result"] is None


def test_load_list_pagination_and_shipper_scope(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items
    to return; when not provided it defaults to 10, with a minimum of 1 and a
    maximum of 100. The `offset` parameter specifies how many items to skip and
    defaults to 0."
    PRD §4: "List loads; Shipper callers auto-scoped to their own customer"

    Design: Corner/entities/load_list_pagination_and_shipper_scope
    """
    cust_a = create_customer("Pager A", 500000)
    cust_b = create_customer("Pager B", 500000)
    for desc in ("A1", "A2", "A3"):
        create_load_for_customer(cust_a["id"], cargo_description=desc)
    create_load_for_customer(cust_b["id"], cargo_description="B1")
    page1, meta1 = validate_paginated(
        api.list_loads(
            BILLING, params={"customer_id": cust_a["id"], "limit": 2, "offset": 0}
        )
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    page2, meta2 = validate_paginated(
        api.list_loads(
            BILLING, params={"customer_id": cust_a["id"], "limit": 2, "offset": 2}
        )
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    # Shipper-scoped list (no filter param) returns only own loads.
    scoped, _ = validate_paginated(
        api.list_loads(make_shipper_headers(cust_a["id"]))
    )
    assert len(scoped) == 3
    assert all(row["customer_id"] == cust_a["id"] for row in scoped)


def test_missing_resources_return_not_found(api):
    """PRD §2.10: "A request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the
    first path identifier that does not exist, and a child identifier that
    exists but belongs to a different parent is likewise `ERR_NOT_FOUND`.
    Existence checking happens before any business rule is evaluated, so a
    request against a nonexistent parent never surfaces a business-rule error."

    Design: Corner/entities/missing_resources_return_not_found
    """
    create_customer("Ghost Hunt", 500000)
    err1 = validate_error(
        api.get_load(NON_EXISTENT_UUID, DISPATCHER),
        ApiErrorId.ERR_NOT_FOUND,
    )
    assert err1["error_id"] == "ERR_NOT_FOUND"
    # Action on a missing child: existence validated before any state logic.
    err2 = validate_error(
        api.file_permit(NON_EXISTENT_UUID, PERMIT_CLERK),
        ApiErrorId.ERR_NOT_FOUND,
    )
    assert err2["error_id"] == "ERR_NOT_FOUND"


def test_load_create_missing_required_weight_rejected(api):
    """PRD §3.2: "Each of the weight and dimension fields must be greater than
    zero; violations of required-field presence, enum membership, integer
    floors, or datetime ordering on any endpoint are rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/load_create_missing_required_weight_rejected
    """
    customer = create_customer("Forgetful Freight", 500000)
    payload = {
        "cargo_description": "Mystery box",
        "width_in": 96,
        "height_in": 60,
        "length_in": 300,
        "origin": "X",
        "destination": "Y",
    }
    err = validate_error(
        api.create_load(payload, make_shipper_headers(customer["id"])),
        ApiErrorId.ERR_INVALID_REQUEST,
    )
    assert err["error_id"] == "ERR_INVALID_REQUEST"


def test_computed_flags_after_plan(api):
    """PRD §3.2: "On acceptance, the system stores the four plan inputs on the
    load and refreshes the computed dimensions. The overall height
    `overall_height_in` becomes `height_in` plus the chosen trailer's catalog
    deck height (it is null until the first successful plan). The flags
    `is_oversize`, `is_overweight`, and `is_superload` are computed from the
    §2.5 baselines. The required axle count `required_axles` is stored."
    PRD §2.5: "A load is **oversize** when its cargo is wider than 102 inches,
    taller than 162 inches of cargo height, or longer than 636 inches. A load
    is **overweight** when its gross weight exceeds 80,000 lbs. A load is a
    **superload** when gross weight exceeds 150,000 lbs or width exceeds 192
    inches."

    Design: Corner/entities/computed_flags_after_plan
    """
    customer = create_customer("Computed Co", 50_000_000)
    created = create_load_for_customer(
        customer["id"],
        cargo_description="Oven", gross_weight_lbs=85000,
        width_in=150, height_in=100, length_in=400,
        origin="X", destination="Y",
    )
    planned = plan_load(
        created["id"], trailer_type="EXTENDABLE_DOUBLE_DROP",
        trailer_axle_count=6, driver_name="T. Ray",
        driver_oversize_endorsed=True,
    )
    assert planned["is_oversize"] is True    # width 150 > 102
    assert planned["is_overweight"] is True  # 85000 > 80000
    assert planned["is_superload"] is False  # <= 150000 lbs and <= 192 in
    assert planned["required_axles"] == 5    # max(2, ceil(85000/20000))
    assert planned["overall_height_in"] == 122  # 100 + deck 22


def test_scale_ticket_immutability(api):
    """PRD §2.4: "Scale tickets are the deliberate exception. A `ScaleTicket`
    is an immutable, append-only weighing event: it carries `id` and
    `created_at` only, and both `updated_at` and `version` are absent from it
    entirely. No endpoint modifies or deletes a scale ticket."
    PRD §3.8: "`excess_lbs` is the amount by which the measured weight exceeds
    the load's declared `gross_weight_lbs`, floored at zero, and `is_violation`
    is true exactly when the measured weight, multiplied by 100, is strictly
    greater than the declared weight multiplied by 103 — a 3% tolerance
    evaluated in exact integer arithmetic with no floating-point rounding."

    Design: Corner/entities/scale_ticket_immutability
    """
    _, load = setup_standard_load_cleared(company_name="Weigh Co")
    resp = api.create_scale_ticket(
        load["id"],
        create_scale_ticket_payload(
            measured_gross_lbs=40500, weighed_at="2026-08-12T07:00:00Z"
        ),
        DRIVER,
    )
    data = validate_success(resp, 201)
    assert_scale_ticket(data)
    # 40500 vs declared 40000; 4050000 <= 4120000 -> no violation.
    assert data["is_violation"] is False
    assert data["excess_lbs"] == 500
    # Append-only surface: the API exposes no update/delete for scale tickets.
    put_resp = api.put(
        f"/heavy-haul/loads/{load['id']}/scale-tickets/{data['id']}",
        json={"measured_gross_lbs": 1},
        headers=DRIVER,
    )
    assert put_resp.status_code in (404, 405)
    del_resp = api.delete(
        f"/heavy-haul/loads/{load['id']}/scale-tickets/{data['id']}",
        headers=DRIVER,
    )
    assert del_resp.status_code in (404, 405)
