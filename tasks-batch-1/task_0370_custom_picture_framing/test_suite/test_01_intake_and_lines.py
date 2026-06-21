"""Intake: customer/order/line creation, defaults, validation, FK existence, OCC.

Translates queue B (Corner) entities + cross_cutting OCC instances, plus the
line_cost boundary/non-boundary corner instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_customer_payload, create_order_payload, add_frame_line_payload,
    TEST_USERS, MISSING_UUID,
    create_customer, create_order, add_line,
    assert_customer, assert_framing_order, assert_frame_line,
)

DESIGNER = TEST_USERS["frame_designer_headers"]
CLERK = TEST_USERS["front_desk_clerk_headers"]
TECH = TEST_USERS["frame_production_tech_headers"]


def test_create_customer_returns_201_with_derived_discount(api):
    """PRD §3.1: "The tier determines the customer's `loyalty_discount_pct`, a
    derived field: a `STANDARD` customer receives a discount fraction of 0.00, a
    `PREFERRED` customer 0.10, and a `TRADE` customer 0.15."
    PRD §3.1: "At creation the customer's reliability fields are seeded —
    `no_show_risk_score` starts at 0 and `settled_reputation_score` starts at 50 —
    and `open_order_count` starts at 0."

    Design: Corner/entities/create_customer_returns_201_with_derived_discount
    """
    payload = create_customer_payload(full_name="New Cust", email="nc@x.com",
                                       phone="555-0200", loyalty_tier="PREFERRED")
    data = validate_success(api.create_customer(payload, CLERK), expected_status=201)
    assert_customer(data)
    assert data["loyalty_discount_pct"] == 0.10
    assert data["no_show_risk_score"] == 0
    assert data["settled_reputation_score"] == 50
    assert data["version"] == 1


def test_get_framing_order_not_found_returns_404(api):
    """PRD §2.5: "A request for the lines of a non-existent order fails with
    `ERR_ORDER_NOT_FOUND` before any line is consulted."

    Design: Corner/entities/get_framing_order_not_found_returns_404
    """
    resp = api.get_order(MISSING_UUID, DESIGNER)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND)


def test_create_frame_line_missing_required_field_returns_invalid_request(api):
    """PRD §3.2: "Each piece becomes a **frame line** carrying an `artwork_label`
    describing the piece, the customer-stated intake dimensions `nominal_width_in`
    and `nominal_height_in` ... and a `molding_rate_per_ui`, the molding price per
    united inch in dollars (at least zero)."
    PRD §2.6: "fourth, request-body well-formedness — required fields present ...
    (`ERR_INVALID_REQUEST`, HTTP 400)".

    Design: Corner/entities/create_frame_line_missing_required_field_returns_invalid_request
    """
    cust = create_customer()
    order = create_order(cust["id"])
    payload = {"expected_order_version": order["version"], "artwork_label": "NoRate",
               "nominal_width_in": 8, "nominal_height_in": 10}
    resp = api.add_frame_line(order["id"], payload, DESIGNER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_frame_line_default_fields_applied_on_omission(api):
    """PRD §3.2: "`mat_border_in` is the mat reveal added to each side of the
    artwork in inches (at least zero, defaulting to 2); `mat_layers` is the count
    of stacked mat boards (an integer of at least 1, defaulting to 1); `glass_type`
    is one of `REGULAR`, `CONSERVATION`, or `MUSEUM` and defaults to `REGULAR`;
    `mounting_type` is one of `NONE`, `PLAIN`, `DRY_MOUNT`, or `CONSERVATION_HINGE`
    and defaults to `NONE`".

    Design: Corner/entities/frame_line_default_fields_applied_on_omission
    """
    cust = create_customer()
    order = create_order(cust["id"])
    payload = add_frame_line_payload(order["version"], artwork_label="D",
                                     nominal_width_in=8, nominal_height_in=10,
                                     molding_rate_per_ui=0.30)
    data = validate_success(api.add_frame_line(order["id"], payload, DESIGNER), expected_status=201)
    assert_frame_line(data)
    assert data["mat_border_in"] == 2
    assert data["mat_layers"] == 1
    assert data["glass_type"] == "REGULAR"
    assert data["mounting_type"] == "NONE"
    assert data["estimate_subtotal"] == 64.47


def test_system_fields_generated_and_input_ignored_on_create_order(api):
    """PRD §3.2: "A new order starts with `production_status` of `INTAKE` and
    `payment_status` of `UNBILLED`."
    PRD §2.4: "The `version` field is an integer that starts at 1 and increases by
    one on every mutation of the resource."

    Design: Corner/entities/system_fields_generated_and_input_ignored_on_create_order
    """
    cust = create_customer()
    data = validate_success(api.create_order(create_order_payload(cust["id"]), DESIGNER),
                            expected_status=201)
    assert_framing_order(data)
    assert data["production_status"] == "INTAKE"
    assert data["payment_status"] == "UNBILLED"
    assert data["version"] == 1


def test_invalid_enum_glass_type_returns_invalid_request(api):
    """PRD §2.6: "fourth, request-body well-formedness — required fields present,
    enums valid, numeric dimensions strictly positive ... (`ERR_INVALID_REQUEST`,
    HTTP 400)".

    Design: Corner/entities/invalid_enum_glass_type_returns_invalid_request
    """
    cust = create_customer()
    order = create_order(cust["id"])
    payload = add_frame_line_payload(order["version"], artwork_label="Bad",
                                     nominal_width_in=8, nominal_height_in=10,
                                     molding_rate_per_ui=0.30, glass_type="PLEXI")
    resp = api.add_frame_line(order["id"], payload, DESIGNER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_order_requires_existing_customer_else_not_found(api):
    """PRD §2.5: "`ERR_CUSTOMER_NOT_FOUND` for a customer (whether named in the
    path or referenced as a body `customer_id`)".

    Design: Corner/entities/order_requires_existing_customer_else_not_found
    """
    resp = api.create_order(create_order_payload("00000000-0000-4000-8000-000000000abc"), DESIGNER)
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_FOUND)


def test_flat_topology_workbench_fk_validated_on_task_create(api):
    """PRD §2.5: "`ERR_WORKBENCH_NOT_FOUND` for a workbench (whether named in the
    path or referenced as a body `workbench_id`)".

    Design: Corner/entities/flat_topology_workbench_fk_validated_on_task_create
    """
    from test_helpers import setup_in_production_order, create_task_payload
    cust, order, line = setup_in_production_order()
    payload = create_task_payload(order["id"], "00000000-0000-4000-8000-0000000bench0", 0, 30)
    resp = api.create_task(payload, TECH)
    validate_error(resp, ApiErrorId.ERR_WORKBENCH_NOT_FOUND)


# --- Per-line pricing corner instances ---

def test_oversize_tier_below_threshold_no_surcharge(api):
    """PRD §3.3: "The **oversize surcharge** is tiered on united inches and is
    non-additive — only the single highest tier the line crosses applies. If the
    united inches are at least 120, the surcharge is 95.00. Otherwise, if the
    united inches are at least 80, the surcharge is 40.00. Otherwise the surcharge
    is 0.00."

    Design: Corner/calculations/oversize_tier_below_threshold_no_surcharge
    """
    cust = create_customer()
    order = create_order(cust["id"])
    line = add_line(order["id"], order["version"], artwork_label="U79",
                    nominal_width_in=35.5, nominal_height_in=36, molding_rate_per_ui=0.10,
                    mat_border_in=2, mat_layers=1, glass_type="REGULAR")
    assert line["estimate_subtotal"] == 162.67


# --- OCC (cross_cutting_complexity_layers) ---

def test_occ_stale_order_version_on_second_line_add(api):
    """PRD §2.8: "If `expected_order_version` does not equal the order's current
    `version` — that is, if another writer has advanced the order's version since
    the client last read it — the addition is rejected with `ERR_STALE_ORDER_VERSION`
    and HTTP status 412".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_order_version_on_second_line_add
    """
    cust = create_customer()
    order = create_order(cust["id"])
    stale_version = order["version"]
    # First add bumps version (1 -> 2).
    add_line(order["id"], stale_version, artwork_label="First")
    # Second add still carries the pre-first-add version.
    payload = add_frame_line_payload(stale_version, artwork_label="Stale",
                                     nominal_width_in=9, nominal_height_in=12,
                                     molding_rate_per_ui=0.30)
    resp = api.add_frame_line(order["id"], payload, DESIGNER)
    validate_error(resp, ApiErrorId.ERR_STALE_ORDER_VERSION)


def test_occ_correct_order_version_succeeds_and_bumps_version(api):
    """PRD §2.8: "A request to add a frame line to an order must include the field
    `expected_order_version`, carrying the client's last observed `version` of the
    target `FramingOrder`."
    PRD §3.2: "On a successful add ... the order's `version` is incremented by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_order_version_succeeds_and_bumps_version
    """
    cust = create_customer()
    order = create_order(cust["id"])
    add_line(order["id"], order["version"], artwork_label="First")  # version 1 -> 2
    refreshed = get_success_data(api.get_order(order["id"], DESIGNER))
    assert refreshed["version"] == 2
    payload = add_frame_line_payload(refreshed["version"], artwork_label="Second",
                                     nominal_width_in=9, nominal_height_in=12,
                                     molding_rate_per_ui=0.30)
    validate_success(api.add_frame_line(order["id"], payload, DESIGNER), expected_status=201)
    final = get_success_data(api.get_order(order["id"], DESIGNER))
    assert final["version"] == 3
