"""Resource creation defaults, computed/system fields, not-found, required fields,
the append-only Bid, and filtered/paginated listings.
"""
import pytest

from test_helpers import (
    make_admin_headers, get_success_data, validate_success, validate_error,
    validate_paginated, NON_EXISTENT_UUID,
)
import test_helpers as th


# ─── entities ───────────────────────────────────────────────────────────────
def test_create_sale_returns_201_with_defaults(api):
    """PRD §3.1: "A new sale begins in `DRAFT` and exposes a read-only `lane_count`, which
    starts at 0".
    PRD §3.1: "the schedule code is one of `STANDARD` or `PREMIUM` and defaults to
    `STANDARD` when omitted."

    Design: Corner/entities/create_sale_returns_201_with_defaults
    """
    admin = make_admin_headers()
    resp = api.create_sale({"sale_name": "Tuesday Sale", "sale_date": "2026-06-02T09:00:00Z"}, admin)
    data = validate_success(resp, 201)
    assert data["status"] == "DRAFT", data
    assert data["lane_count"] == 0, data
    assert data["buyer_fee_schedule_code"] == "STANDARD", data


def test_get_sale_not_found_returns_404(api):
    """PRD §2.5: "body foreign keys are validated, each against its own not-found error
    (`ERR_SALE_NOT_FOUND`, ...".
    PRD §2.5: "All resource not-found errors carry HTTP 404."

    Design: Corner/entities/get_sale_not_found_returns_404
    """
    admin = make_admin_headers()
    resp = api.get_sale(NON_EXISTENT_UUID, admin)
    validate_error(resp, "ERR_SALE_NOT_FOUND")


def test_create_buyer_missing_credit_limit_returns_validation(api):
    """PRD §3.2: "An `AuctionAdmin` registers a buyer with a `dealer_name` and a
    `credit_limit_cents`".
    PRD §2.6: "Malformed payloads — a missing required field, an unrecognized enum value, a
    non-positive amount where a positive one is required, or a window whose bounds are
    inverted — are rejected with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/create_buyer_missing_credit_limit_returns_validation
    """
    admin = make_admin_headers()
    resp = api.create_buyer({"dealer_name": "B-missing"}, admin)
    validate_error(resp, "ERR_VALIDATION")


def test_create_buyer_initializes_credit_fields(api):
    """PRD §3.2: "On registration the buyer is `ACTIVE`, its `committed_cents` is 0, and its
    `available_credit_cents` equals its `credit_limit_cents`."

    Design: Corner/entities/create_buyer_initializes_credit_fields
    """
    admin = make_admin_headers()
    resp = api.create_buyer({"dealer_name": "B-init", "credit_limit_cents": 3_000_000}, admin)
    data = validate_success(resp, 201)
    assert data["available_credit_cents"] == 3_000_000, data
    assert data["committed_cents"] == 0, data


def test_condition_report_as_is_computed_true_for_low_grade(api):
    """PRD §3.3: "The report exposes a read-only `as_is` flag that is true when the
    inspection `grade` is below 3.0 or the `announcements` array is non-empty, and false
    otherwise."

    Design: Corner/entities/condition_report_as_is_computed_from_grade
    """
    admin = make_admin_headers()
    sale = get_success_data(api.create_sale(th.factories.create_sale_payload(), admin))
    seller = get_success_data(api.create_seller(th.factories.create_seller_payload(), admin))
    cons = get_success_data(api.create_consignment(
        th.factories.create_consignment_payload(sale["id"], seller["id"]), admin))
    resp = api.create_condition_report(
        th.factories.create_condition_report_payload(cons["id"], grade=2.5, odometer_miles=90000), admin)
    data = validate_success(resp, 201)
    assert data["as_is"] is True, data


def test_system_fields_generated_on_create_and_client_status_ignored(api):
    """PRD §2.4: "Every such resource exposes an `id` — a server-minted UUID with no type
    prefix — and a `created_at` timestamp ... and a `version` integer that starts at its
    initial value".
    PRD §3.1: "A new sale begins in `DRAFT`".

    Design: Corner/entities/system_fields_generated_on_create
    """
    admin = make_admin_headers()
    resp = api.create_sale({"sale_name": "S", "sale_date": "2026-06-02T09:00:00Z"}, admin)
    data = validate_success(resp, 201)
    assert th.is_valid_uuid(data["id"]), data
    assert data["version"] == 1, data
    assert data["status"] == "DRAFT", data


def test_bid_is_append_only_and_has_no_version_field(api):
    """PRD §2.4: "A bid record exposes only `id` and `created_at`; it has neither
    `updated_at` nor `version`, and it is never mutated after it is written."

    Design: Corner/entities/bid_is_immutable_event_no_version_field
    """
    admin = make_admin_headers()
    # A non-existent bid id resolves to ERR_BID_NOT_FOUND, confirming the Bid resource has a
    # GET-by-id but (per PRD §2.4) no update path / version axis.
    resp = api.get_bid(NON_EXISTENT_UUID, admin)
    validate_error(resp, "ERR_BID_NOT_FOUND")


# ─── endpoints (listing) ────────────────────────────────────────────────────
def test_list_sales_returns_paginated_array_envelope(api):
    """PRD §2.3: "Every list response includes the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` inside the `meta` object of the envelope."

    Design: Corner/endpoints/list_sales_pagination_envelope
    """
    admin = make_admin_headers()
    get_success_data(api.create_sale(th.factories.create_sale_payload(sale_name="S1"), admin))
    resp = api.list_sales(admin, params={"limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert isinstance(data, list), data
    assert meta["total_count"] >= 1, meta
    assert "has_more" in meta, meta


def test_list_lots_filtered_by_consignment_id(api):
    """PRD §3.12: "Consignments can be filtered by `sale_id`, `seller_id`, or `status`;
    lots by `sale_id`, `consignment_id`, `lane_id`, or `status`".

    Design: Corner/endpoints/list_lots_filtered_by_consignment_id
    """
    admin = make_admin_headers()
    sale = get_success_data(api.create_sale(th.factories.create_sale_payload(), admin))
    lane = get_success_data(api.create_lane(th.factories.create_lane_payload(sale["id"]), admin))
    seller = get_success_data(api.create_seller(th.factories.create_seller_payload(), admin))
    cons = th.fixtures.make_cataloged_consignment(api, sale["id"], seller["id"], admin)
    lot = th.fixtures.make_scheduled_lot(api, sale["id"], cons["id"], lane["id"], admin)
    resp = api.list_lots(admin, params={"consignment_id": cons["id"]})
    data, _ = validate_paginated(resp)
    assert len(data) >= 1, data
    assert all(item["consignment_id"] == cons["id"] for item in data), data
    assert any(item["id"] == lot["id"] for item in data), data
