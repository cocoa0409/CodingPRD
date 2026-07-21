"""Customers, foot measurements (pediatric fitting length + growth delta), and inventory
read/listing."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    assert_customer, assert_measurement, ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as fx

SM = TEST_USERS["store_manager_headers"]
FITTER = TEST_USERS["fitter_headers"]
NON_EXISTENT = "00000000-0000-4000-8000-000000000000"


def test_create_customer_returns_201_with_system_fields(api):
    """PRD §2.4: "`version` is an integer that starts at 1 and increments by one on every
    mutation of the resource."
    PRD §3.2: "The customer is flagged `is_pediatric` when their age — the current clock
    date minus `date_of_birth` — is under 13 years."

    Design: Corner/entities/create_customer_returns_201_with_system_fields
    """
    fx.set_clock()
    customer = validate_success(api.create_customer(
        {"full_name": "Al Adult", "date_of_birth": "1980-01-01"}, SM), expected_status=201)
    assert_customer(customer)
    assert customer["version"] == 1
    assert customer["is_pediatric"] is False


def test_customer_not_found_returns_404(api):
    """PRD §2.8: "Every foreign-key reference — whether supplied as a path identifier or
    inside a request body — must resolve to an existing resource." — the customer
    not-found error is `ERR_CUSTOMER_NOT_FOUND`.

    Design: Corner/entities/customer_not_found_returns_404
    """
    resp = api.get_customer(NON_EXISTENT, SM)
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value)


def test_pediatric_recommended_mondo_computed(api):
    """PRD §3.2: "take the greater of the two foot lengths, add a toe allowance of 14
    millimetres if the customer is pediatric or 12 millimetres otherwise, divide that
    fitting length by the 5-millimetre Mondopoint step, round up to the next whole step,
    and multiply back by 5."

    Design: Corner/entities/pediatric_recommended_mondo_computed
    """
    fx.set_clock()
    cust = fx.create_customer(full_name="Kid K", date_of_birth="2016-01-01")  # age 10
    meas = validate_success(api.create_measurement(
        cust["id"],
        {"foot_length_mm_left": 176, "foot_length_mm_right": 178,
         "foot_width_mm_left": 70, "foot_width_mm_right": 71}, FITTER), expected_status=201)
    assert_measurement(meas)
    # max(176,178)=178 + 14 = 192; ceil(192/5)*5 = 195
    assert meas["recommended_mondo_mm"] == 195
    assert meas["length_change_mm_from_prior"] == 0


def test_measurement_growth_delta_from_prior(api):
    """PRD §3.2: "The `length_change_mm_from_prior` is the growth delta: the greater of
    this measurement's two foot lengths minus the greater of the two foot lengths of the
    immediately prior measurement for the same customer (ordered by `created_at`
    ascending), or 0 when this is the customer's first measurement."

    Design: Corner/entities/measurement_growth_delta_from_prior
    """
    fx.set_clock()
    cust = fx.create_customer(full_name="Grow G", date_of_birth="2015-01-01")
    get_success_data(api.create_measurement(
        cust["id"],
        {"foot_length_mm_left": 175, "foot_length_mm_right": 178,
         "foot_width_mm_left": 70, "foot_width_mm_right": 71}, FITTER))
    meas2 = validate_success(api.create_measurement(
        cust["id"],
        {"foot_length_mm_left": 188, "foot_length_mm_right": 190,
         "foot_width_mm_left": 72, "foot_width_mm_right": 73}, FITTER), expected_status=201)
    # max 190 - prior max 178 = 12
    assert meas2["length_change_mm_from_prior"] == 12


def test_list_inventory_by_product_returns_paginated_array(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope." — inventory may be filtered by
    `product_id`.

    Design: Corner/endpoints/list_inventory_by_product_paginated_envelope
    """
    prod = fx.create_product(name="List Prod", brand="X", category="REGULAR", base_price_cents=5000)
    fx.create_inventory(prod["id"], size=9.0, width="D", lot_number="LL1", quantity_on_hand=2)
    fx.create_inventory(prod["id"], size=9.5, width="E", lot_number="LL2", quantity_on_hand=1)
    resp = api.list_inventory_items(SM, params={"product_id": prod["id"], "limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(data) == 2


def test_inventory_item_not_found_on_line_add(api):
    """PRD §2.8: "Body foreign keys are resolved after the path resolves and raise the
    corresponding entity's not-found error." — the inventory not-found error is
    `ERR_INVENTORY_ITEM_NOT_FOUND`.

    Design: Corner/errors/inventory_item_not_found_on_line_add
    """
    fx.set_clock()
    cust = fx.create_customer(full_name="NF Cust", date_of_birth="1984-04-04")
    fitter = fx.create_fitter(full_name="NF Fit")
    fh = fx.make_fitter_headers(fitter["id"])
    sale = fx.open_sale(cust["id"], fitter["id"], fh)
    resp = api.add_sale_line(
        sale["id"], {"inventory_item_id": "00000000-0000-4000-8000-0000000000ff", "quantity": 1}, fh)
    validate_error(resp, ApiErrorId.ERR_INVENTORY_ITEM_NOT_FOUND.value)
