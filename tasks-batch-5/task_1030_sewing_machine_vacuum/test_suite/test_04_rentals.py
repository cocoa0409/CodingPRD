"""Loaner rentals: half-open overlap geometry, billable days, and late-fee settlement."""
from test_helpers import (
    TEST_USERS,
    new_rental,
    setup_customer_product_item,
    validate_success,
    validate_error,
)

SA = TEST_USERS["sales_associate_headers"]


# ─────────────────── half-open interval overlap on the unit ────────────────
def test_overlapping_rental_of_same_item_rejected(api):
    """PRD §3.5: "two intervals conflict when the new start is before the existing
    due **and** the existing start is before the new due."

    Design: Difficulty/resource_temporal_overlap/rental_half_open_item_overlap
    """
    cust, _prod, item = setup_customer_product_item(
        credit=100000, item_overrides={"serial_number": "SN-O", "condition": "REFURBISHED",
                                        "acquisition_cost_cents": 9000, "list_price_cents": 25000},
        product_overrides={"model_name": "Ov Vac", "category": "VACUUM", "brand": "Generic", "msrp_cents": 25000},
    )
    new_rental(cust["id"], item["id"], start_at="2026-07-02T00:00:00Z", due_at="2026-07-06T00:00:00Z",
               daily_rate_cents=2000, deposit_cents=5000)
    res = api.create_rental(
        {"customer_id": cust["id"], "inventory_item_id": item["id"],
         "start_at": "2026-07-05T00:00:00Z", "due_at": "2026-07-08T00:00:00Z",
         "daily_rate_cents": 2000, "deposit_cents": 5000},
        SA,
    )
    validate_error(res, "ERR_RENTAL_OVERLAP", expected_status=409)


def test_adjacent_rental_of_same_item_allowed(api):
    """PRD §3.5: "Intervals that merely touch at an endpoint — the new start equal to
    an existing due, or vice versa — do not conflict, because the due instant is
    exclusive."

    Design: Difficulty/resource_temporal_overlap/rental_half_open_item_overlap
    """
    cust, _prod, item = setup_customer_product_item(
        credit=100000, item_overrides={"serial_number": "SN-O2", "condition": "REFURBISHED",
                                        "acquisition_cost_cents": 9000, "list_price_cents": 25000},
        product_overrides={"model_name": "Ov Vac", "category": "VACUUM", "brand": "Generic", "msrp_cents": 25000},
    )
    new_rental(cust["id"], item["id"], start_at="2026-07-02T00:00:00Z", due_at="2026-07-06T00:00:00Z",
               daily_rate_cents=2000, deposit_cents=5000)
    res = api.create_rental(
        {"customer_id": cust["id"], "inventory_item_id": item["id"],
         "start_at": "2026-07-06T00:00:00Z", "due_at": "2026-07-08T00:00:00Z",
         "daily_rate_cents": 2000, "deposit_cents": 5000},
        SA,
    )
    rental = validate_success(res, 201)
    assert rental["status"] == "ACTIVE"


# ──────────────────────────── corner instances ────────────────────────────
def test_rental_days_computed_on_create(api):
    """PRD §3.5: "the billable `rental_days` is computed as the ceiling of the span
    from `start_at` to `due_at` measured in days"

    Design: Corner/state_machines/rental_days_computed_on_create
    """
    cust, _prod, item = setup_customer_product_item(
        credit=100000, item_overrides={"serial_number": "SN-RD", "condition": "REFURBISHED",
                                        "acquisition_cost_cents": 8000, "list_price_cents": 22000},
        product_overrides={"model_name": "RD Vac", "category": "VACUUM", "brand": "G", "msrp_cents": 22000},
    )
    rental = new_rental(cust["id"], item["id"], start_at="2026-07-02T00:00:00Z",
                        due_at="2026-07-06T00:00:00Z", daily_rate_cents=2000, deposit_cents=5000)
    assert rental["rental_days"] == 4
    assert rental["status"] == "ACTIVE"


def test_late_return_charges_multiplier_fee(api):
    """PRD §3.5: "The `late_fee_cents` is `days_late` multiplied by `daily_rate_cents`
    multiplied by the late multiplier of 1.5, rounded half up to whole cents. The
    `total_charge_cents` is `rental_days` multiplied by `daily_rate_cents` plus the
    `late_fee_cents`."

    Design: Corner/state_machines/rental_late_fee_on_late_return
    """
    cust, _prod, item = setup_customer_product_item(
        credit=100000, item_overrides={"serial_number": "SN-LF", "condition": "REFURBISHED",
                                        "acquisition_cost_cents": 8000, "list_price_cents": 22000},
        product_overrides={"model_name": "LF Vac", "category": "VACUUM", "brand": "G", "msrp_cents": 22000},
    )
    rental = new_rental(cust["id"], item["id"], start_at="2026-07-02T00:00:00Z",
                        due_at="2026-07-06T00:00:00Z", daily_rate_cents=2000, deposit_cents=5000)
    returned = validate_success(
        api.return_rental(rental["id"], {"returned_at": "2026-07-09T00:00:00Z"}, SA), 200
    )
    assert returned["late_fee_cents"] == 9000
    assert returned["total_charge_cents"] == 17000
    assert returned["status"] == "RETURNED"
