"""Railcar registration, reads, pagination, and filtered lists."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS, api_client,
    create_railcar_payload, create_work_order_payload, set_clock,
    setup_shop_ctx, validate_error, validate_paginated, validate_success,
)

ADMIN = TEST_USERS["shop_admin"]
YARD = TEST_USERS["yard_clerk"]
FOREMAN = TEST_USERS["repair_foreman"]
INSPECTOR = TEST_USERS["car_inspector"]


def _instant(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)


def test_railcar_create_missing_required_car_number():
    """PRD §2.12: "A malformed body, a missing required field, an invalid enum
    literal, a negative or zero quantity, or a slot whose `ends_at` is not
    after its `starts_at` is rejected with `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/railcar_create_missing_required_car_number
    """
    ctx = setup_shop_ctx()
    payload = create_railcar_payload(ctx["shop"]["id"], ctx["owner"]["id"],
                                     ctx["line"]["id"])
    del payload["car_number"]
    resp = api_client.create_railcar(payload, YARD)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_railcar_create_system_status_input_ignored():
    """PRD §3.2: "Registration stamps `arrived_at` from the logical clock, sets
    `status` to `ARRIVED`, zeroes `shop_delay_hours`, and leaves both dwell
    fields — `projected_dwell_charge_cents` and `dwell_charge_cents` — null
    until routing and departure produce them."
    PRD §2.4: "At startup the logical clock reads exactly
    `2026-05-01T00:00:00Z`, and before any clock-setting call it continues to
    read exactly that instant."

    Design: Corner/entities/railcar_create_system_status_input_ignored
    """
    # No clock-setting call: the startup reading applies (server is fresh).
    ctx = setup_shop_ctx(clock=None)
    payload = create_railcar_payload(ctx["shop"]["id"], ctx["owner"]["id"],
                                     ctx["line"]["id"], car_number="2002")
    payload["status"] = "DEPARTED"  # system-managed field; must be ignored
    car = validate_success(api_client.create_railcar(payload, YARD), expected_status=201)
    assert car["status"] == "ARRIVED", "system initial state must win over client input"
    assert _instant(car["arrived_at"]) == _instant("2026-05-01T00:00:00Z"), (
        f"arrived_at must be the startup clock reading, got {car['arrived_at']}"
    )


def test_railcar_get_not_found_returns_404():
    """PRD §2.12: "fifth the existence of path resources (else `ERR_NOT_FOUND`,
    404)".

    Design: Corner/entities/railcar_get_not_found_returns_404
    """
    validate_success(api_client.create_shop(
        {"name": "Shop", "stalls": 2, "dwell_rate_cents_per_hour": 500}, ADMIN),
        expected_status=201)
    resp = api_client.get_railcar(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_railcar_list_pagination_defaults():
    """PRD §2.3: "`limit` sets the maximum number of items returned: it
    defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the
    number of items skipped and defaults to 0."
    PRD §2.3: "Paginated list responses carry `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/railcar_list_pagination_defaults
    """
    ctx = setup_shop_ctx()
    for number in ("3001", "3002"):
        validate_success(api_client.create_railcar(
            create_railcar_payload(ctx["shop"]["id"], ctx["owner"]["id"],
                                   ctx["line"]["id"], car_number=number), YARD),
            expected_status=201)
    data, meta = validate_paginated(api_client.list_railcars(ADMIN))
    assert len(data) == 2
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert meta["limit"] == 10, "default limit"
    assert meta["offset"] == 0, "default offset"


def test_immediate_consistency_read_after_write():
    """PRD §3.2: "Registration stamps `arrived_at` from the logical clock, sets
    `status` to `ARRIVED`, zeroes `shop_delay_hours`, and leaves both dwell
    fields — `projected_dwell_charge_cents` and `dwell_charge_cents` — null
    until routing and departure produce them."

    Design: Corner/consistency_model/immediate_consistency_read_after_write
    """
    set_clock("2026-05-01T08:00:00Z")
    ctx = setup_shop_ctx(clock=None)
    created = validate_success(api_client.create_railcar(
        create_railcar_payload(ctx["shop"]["id"], ctx["owner"]["id"],
                               ctx["line"]["id"], car_number="9001"), YARD),
        expected_status=201)
    car = validate_success(api_client.get_railcar(created["id"], ADMIN))
    assert car["car_number"] == "9001"
    assert car["status"] == "ARRIVED"
    assert car["version"] == 1, "freshly created resource version"
    assert _instant(car["arrived_at"]) == _instant("2026-05-01T08:00:00Z")
    assert car["departed_at"] is None


def test_fk_reverse_reachability_filtered_lists():
    """PRD §3.2: "The railcar list filters by `shop_id`, `owner_id`,
    `handling_line_id`, and `status`."
    PRD §3.3: "The work-order list filters by `railcar_id`, `inspection_id`,
    `assigned_slot_id`, `auth_status`, and `exec_status`."

    Design: Corner/endpoints/fk_reverse_reachability_filtered_lists
    """
    ctx = setup_shop_ctx()
    owner_b = validate_success(api_client.create_car_owner(
        {"shop_id": ctx["shop"]["id"], "name": "Owner B", "scac_code": "OWNB"}, ADMIN),
        expected_status=201)
    car_a = validate_success(api_client.create_railcar(
        create_railcar_payload(ctx["shop"]["id"], ctx["owner"]["id"],
                               ctx["line"]["id"], car_number="7001"), YARD),
        expected_status=201)
    validate_success(api_client.create_railcar(
        create_railcar_payload(ctx["shop"]["id"], owner_b["id"],
                               ctx["line"]["id"], car_number="7002",
                               reporting_mark="OWNB", built_date="2019-05-05"), YARD),
        expected_status=201)
    insp = validate_success(api_client.create_inspection(car_a["id"], INSPECTOR),
                            expected_status=201)
    validate_success(api_client.complete_inspection(insp["id"], INSPECTOR))
    car_now = validate_success(api_client.get_railcar(car_a["id"], ADMIN))
    wo = validate_success(api_client.create_work_order(
        create_work_order_payload(car_a["id"], insp["id"], car_now["version"]),
        FOREMAN), expected_status=201)

    cars, meta = validate_paginated(
        api_client.list_railcars(ADMIN, params={"owner_id": ctx["owner"]["id"]}))
    assert meta["total_count"] == 1 and len(cars) == 1
    assert cars[0]["id"] == car_a["id"]

    wos, meta = validate_paginated(
        api_client.list_work_orders(ADMIN, params={"railcar_id": car_a["id"]}))
    assert meta["total_count"] == 1 and len(wos) == 1
    assert wos[0]["id"] == wo["id"]
