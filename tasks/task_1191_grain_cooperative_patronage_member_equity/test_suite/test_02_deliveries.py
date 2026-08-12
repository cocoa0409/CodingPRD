"""Grain delivery booking, settlement, and ledger reads (PRD §3.2)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    assert_delivery, delivery_payload, TEST_USERS,
    create_district, create_member, create_fiscal_year, set_clock,
    book_delivery, book_and_settle_delivery,
)

OPERATOR = TEST_USERS["operator_headers"]


def _member_and_year():
    set_clock("2025-09-01T00:00:00Z")
    district = create_district()
    member = create_member(district["id"])
    fy = create_fiscal_year()
    return district, member, fy


def test_net_bushels_floor_rounding(api, operator_headers):
    """PRD §3.2: "At settle time the system computes the delivery's
    `net_bushels` — the `gross_bushels` multiplied by one minus the
    `dockage_pct`, rounded down to a whole bushel — and then the delivery's
    `per_unit_retain_cents`, the per-unit retain withheld into member
    capital."

    Design: Corner/entities/grain_delivery_net_bushels_computed_floor_rounding
    """
    _, member, fy = _member_and_year()
    res = api.book_delivery(
        delivery_payload(member["id"], fy["id"], commodity="CORN",
                         gross_bushels=100, dockage_pct=0.075),
        operator_headers,
    )
    delivery = validate_success(res, 201)
    assert_delivery(delivery)
    # floor(100 * (1 - 0.075)) = floor(92.5) = 92
    assert delivery["net_bushels"] == 92, (
        f"Expected net_bushels 92, got {delivery['net_bushels']}"
    )


def test_delivery_initial_status_booked(api, operator_headers):
    """PRD §3.2: "A booked delivery records its `booked_at` from the logical
    clock and starts in `BOOKED` status."

    Design: Corner/entities/grain_delivery_status_initial_booked
    """
    _, member, fy = _member_and_year()
    res = api.book_delivery(
        delivery_payload(member["id"], fy["id"], commodity="WHEAT",
                         gross_bushels=50),
        operator_headers,
    )
    delivery = validate_success(res, 201)
    assert_delivery(delivery)
    assert delivery["status"] == "BOOKED"


def test_double_settle_rejected(api, operator_headers):
    """PRD §3.2: "A delivery that is already `SETTLED` cannot be settled
    again — the second attempt is rejected with
    `ERR_DELIVERY_ALREADY_SETTLED` (HTTP 409)."

    Design: Corner/state_machines/settle_delivery_from_settled_returns_invalid_state
    """
    _, member, fy = _member_and_year()
    delivery = book_and_settle_delivery(member["id"], fy["id"],
                                        commodity="CORN", gross_bushels=100)
    assert delivery["status"] == "SETTLED"
    res = api.settle_delivery(delivery["id"], operator_headers)
    validate_error(res, "ERR_DELIVERY_ALREADY_SETTLED", expected_status=409)
    after = validate_success(api.get_delivery(delivery["id"], operator_headers))
    assert after["status"] == "SETTLED"


def test_cancel_settled_delivery_rejected(api, operator_headers):
    """PRD §3.2: "A still-`BOOKED` delivery may instead be cancelled, moving
    it to `CANCELLED`."
    PRD §2.10: "The resource is in a valid source state for the requested
    transition — otherwise `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/cancel_delivery_from_settled_returns_invalid_state
    """
    _, member, fy = _member_and_year()
    delivery = book_and_settle_delivery(member["id"], fy["id"],
                                        commodity="CORN", gross_bushels=50)
    assert delivery["status"] == "SETTLED"
    res = api.cancel_delivery(delivery["id"], operator_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(api.get_delivery(delivery["id"], operator_headers))
    assert after["status"] == "SETTLED"


def test_dockage_pct_upper_boundary(api, operator_headers):
    """PRD §2.7: "Percentage-style inputs are decimal fractions: `dockage_pct`
    on a delivery must lie between 0.00 and 0.30 inclusive,
    `retained_reserve_pct` on a fiscal year between 0.0 and 0.5 inclusive, and
    `qualified_payout_pct` between 0 and 1 inclusive. Inputs outside these
    ranges are rejected with `ERR_FISCAL_BOUNDARY` (HTTP 422), as is any
    delivery whose `gross_bushels` is not greater than zero."

    Design: Corner/calculations/dockage_pct_upper_boundary_030
    """
    _, member, fy = _member_and_year()
    ok_res = api.book_delivery(
        delivery_payload(member["id"], fy["id"], commodity="CORN",
                         gross_bushels=100, dockage_pct=0.30),
        operator_headers,
    )
    ok = validate_success(ok_res, 201)
    assert_delivery(ok)
    bad_res = api.book_delivery(
        delivery_payload(member["id"], fy["id"], commodity="CORN",
                         gross_bushels=100, dockage_pct=0.31),
        operator_headers,
    )
    validate_error(bad_res, "ERR_FISCAL_BOUNDARY", expected_status=422)


def test_gross_bushels_zero_rejected(api, operator_headers):
    """PRD §2.7: "Inputs outside these ranges are rejected with
    `ERR_FISCAL_BOUNDARY` (HTTP 422), as is any delivery whose
    `gross_bushels` is not greater than zero."

    Design: Corner/validations/gross_bushels_zero_returns_fiscal_boundary
    """
    _, member, fy = _member_and_year()
    res = api.book_delivery(
        delivery_payload(member["id"], fy["id"], commodity="CORN",
                         gross_bushels=0),
        operator_headers,
    )
    validate_error(res, "ERR_FISCAL_BOUNDARY", expected_status=422)


def test_retain_rates_applied_per_commodity(api, operator_headers):
    """PRD §3.2: "The retain rate is fixed per commodity: 8 cents per bushel
    for `CORN`, 10 for `SOYBEAN`, 6 for `WHEAT`, 7 for `SORGHUM`, and 9 for
    `SUNFLOWER`. The delivery's retain is its `net_bushels` multiplied by the
    commodity's rate, rounded half-up to whole cents — and the rounding order
    is pinned: each delivery's retain is rounded individually at settle time,
    and only then accumulated into the member's `per_unit_retains_cents`."

    Design: Corner/calculations/per_unit_retain_rate_constants_applied_per_commodity
    """
    _, member, fy = _member_and_year()
    soy = book_and_settle_delivery(member["id"], fy["id"], commodity="SOYBEAN",
                                   gross_bushels=100)
    sun = book_and_settle_delivery(member["id"], fy["id"],
                                   commodity="SUNFLOWER", gross_bushels=100)
    # 100 net bu * 10c = 1000c; 100 net bu * 9c = 900c
    assert soy["per_unit_retain_cents"] == 1000
    assert sun["per_unit_retain_cents"] == 900


def test_list_member_deliveries_filtered_by_status(api, registrar_headers):
    """PRD §3.2: "Delivery ledgers can be read per member (optionally filtered
    by `fiscal_year_id` or `status`) or across the cooperative with
    `member_id`, `fiscal_year_id`, `status`, and `commodity` filters."

    Design: Corner/endpoints/list_member_deliveries_filtered_by_status
    """
    _, member, fy = _member_and_year()
    settled = book_and_settle_delivery(member["id"], fy["id"],
                                       commodity="CORN", gross_bushels=50)
    cancelled = book_delivery(member["id"], fy["id"], commodity="CORN",
                              gross_bushels=30)
    validate_success(api.cancel_delivery(cancelled["id"], OPERATOR))
    data, meta = validate_paginated(
        api.list_member_deliveries(member["id"], registrar_headers,
                                   params={"status": "SETTLED"}),
    )
    assert len(data) == 1, f"Expected exactly 1 SETTLED delivery, got {data}"
    assert data[0]["id"] == settled["id"]
    assert data[0]["status"] == "SETTLED"
