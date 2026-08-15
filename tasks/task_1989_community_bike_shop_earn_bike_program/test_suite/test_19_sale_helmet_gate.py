"""Sale helmet-compliance gate (queue B)."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    make_ready_bike, make_helmet_part, restock_part,
    TEST_USERS,
    ApiErrorId,
)

COORD = TEST_USERS["coordinator_headers"]
DIRECTOR = TEST_USERS["director_headers"]


def test_sale_complete_requires_helmet_distribution():
    """PRD §3.9: "Completion requires the sale still `PENDING` (else
    `ERR_SALE_NOT_PENDING`), the bike still `READY_FOR_DISPOSITION` (else
    `ERR_BIKE_NOT_AVAILABLE`), and a helmet already distributed to this sale's
    buyer — a `SALE_BUYER` distribution referencing this sale — else
    `ERR_HELMET_REQUIRED`."

    Design: Corner/validations/sale_complete_requires_helmet_distribution
    """
    bike, _, _, _ = make_ready_bike(bike_type="BMX", grade="A",
                                    part_unit_cost_cents=100,
                                    wheel_size_inches=20)
    sale = validate_success(
        api_client.create_sale(
            {"bike_id": bike["id"], "buyer_name": "B H", "buyer_email": "bh@x.org"},
            COORD,
        ),
        expected_status=201,
    )
    hp = make_helmet_part(name="Helmet Q", helmet_size="M", unit_cost_cents=1500)
    restock_part(hp["id"], 2)
    r = api_client.complete_sale(sale["id"], {"payment_method": "CASH"}, COORD)
    validate_error(r, ApiErrorId.ERR_HELMET_REQUIRED)

    validate_success(
        api_client.create_helmet_distribution(
            {"helmet_part_id": hp["id"], "recipient_kind": "SALE_BUYER",
             "sale_id": sale["id"]},
            COORD,
        ),
        expected_status=201,
    )
    ok = validate_success(
        api_client.complete_sale(sale["id"], {"payment_method": "CASH"}, COORD)
    )
    assert ok["status"] == "COMPLETED"
    bike_after = validate_success(api_client.get_bike(bike["id"], COORD))
    assert bike_after["status"] == "SOLD"


def test_sale_already_pending_on_bike():
    """PRD §3.9: "At most one pending sale may exist per bike; opening a second
    is rejected with `ERR_SALE_ALREADY_PENDING`."

    Design: Corner/validations/sale_already_pending_on_bike
    """
    bike, _, _, _ = make_ready_bike(bike_type="HYBRID", grade="A",
                                    part_unit_cost_cents=100)
    validate_success(
        api_client.create_sale(
            {"bike_id": bike["id"], "buyer_name": "B 1", "buyer_email": "b1@x.org"},
            COORD,
        ),
        expected_status=201,
    )
    r = api_client.create_sale(
        {"bike_id": bike["id"], "buyer_name": "B 2", "buyer_email": "b2@x.org"},
        COORD,
    )
    validate_error(r, ApiErrorId.ERR_SALE_ALREADY_PENDING)
    _, meta = validate_paginated(
        api_client.list_sales(COORD, params={"bike_id": bike["id"]})
    )
    assert meta["total_count"] == 1
