"""RMA cases: warranty state, the ordered routing list, the hold and the return window."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_is_null,
    assert_rma_case,
    assert_same_instant,
    claim,
    claim_and_activate,
    fetch_device,
    fetch_rma,
    fetch_subscription,
    list_rma_cases,
    new_catalog,
    open_rma,
    set_clock,
    setup_account,
    setup_account_with_catalog,
    setup_advance_replacement_case,
    setup_shipped_advance_case,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
AGENT = TEST_USERS["support_agent_headers"]


def test_rma_case_read_with_unknown_id_reports_rma_not_found(api):
    """PRD 2.9 rung 18: "Every `RmaCase` id named in the path exists — otherwise
    `ERR_RMA_NOT_FOUND`. Applies to the RMA action endpoints and the single-case
    read."

    Design: Corner/entities/rma_case_get_with_unknown_id_returns_not_found
    """
    set_clock("2026-05-01T00:00:00Z")
    response = api.get_rma_case("00000000-0000-4000-8000-000000000000", AGENT)
    validate_error(response, ApiErrorId.ERR_RMA_NOT_FOUND.value, 404)


def test_an_expired_warranty_routes_the_case_to_the_customer_paid_depot(api):
    """PRD 3.11: "the case's `warranty_state` is `IN_WARRANTY` when the clock is
    strictly before the device's `warranty_expires_at`, and `EXPIRED` otherwise — a
    case opened at exactly the expiry instant is `EXPIRED`."
    PRD 3.11: "1. If the warranty state is `EXPIRED`, the target is
    `CUSTOMER_PAID_DEPOT`."
    PRD 3.11: "On every other target `hold_amount_cents` is 0 and `hold_state` stays
    `NONE`."

    A 12-month SENSOR term with no tier extension from a 2020-01-01 purchase expired
    on 2021-01-01, long before the 2026-05-01 clock.

    Design: Corner/calculations/rma_routing_is_customer_paid_depot_when_warranty_has_expired
    """
    world = setup_account_with_catalog(
        "SENSOR",
        plan_kind="BASIC",
        plan_overrides={"included_device_count": 2},
        allow_overage=False,
        name="Exp House",
        email_prefix="expw",
    )
    device = claim(
        world["household"]["id"],
        world["catalog"]["id"],
        "SNB000001",
        world["owner_headers"],
        purchase_date="2020-01-01",
    )

    data = validate_success(
        api.open_rma_case(
            {"device_id": device["id"], "expected_device_version": device["version"]}, AGENT
        ),
        201,
    )

    assert_rma_case(data)
    assert_same_instant(
        device["warranty_expires_at"], "2021-01-01T00:00:00Z", "Device.warranty_expires_at"
    )
    assert data["warranty_state"] == "EXPIRED"
    assert data["routing_target"] == "CUSTOMER_PAID_DEPOT"
    assert data["hold_amount_cents"] == 0
    assert data["hold_state"] == "NONE"
    assert data["status"] == "ROUTED"


def test_routing_forks_on_manufacturer_service_only_when_advance_is_ineligible(api):
    """PRD 3.11: "4. Otherwise, if the model's `manufacturer_service_only` is true, the
    target is `MANUFACTURER`."
    PRD 3.11: "5. Otherwise the target is `IN_HOUSE_DEPOT`."
    PRD 3.3: "a boolean `manufacturer_service_only` that redirects in-warranty depot
    repairs to the manufacturer"

    Design: Corner/calculations/rma_routing_forks_between_manufacturer_and_in_house_depot
    """
    world = setup_account(
        plan_kind="PLUS", allow_overage=False, name="Fork House", email_prefix="fork"
    )
    camera = new_catalog("CAMERA")
    sensor = new_catalog("SENSOR")
    camera_device = claim(
        world["household"]["id"], camera["id"], "CMA000001", world["owner_headers"]
    )
    sensor_device = claim(
        world["household"]["id"], sensor["id"], "SNB000001", world["owner_headers"]
    )

    camera_case = validate_success(
        api.open_rma_case(
            {
                "device_id": camera_device["id"],
                "expected_device_version": camera_device["version"],
            },
            AGENT,
        ),
        201,
    )
    sensor_case = validate_success(
        api.open_rma_case(
            {
                "device_id": sensor_device["id"],
                "expected_device_version": sensor_device["version"],
            },
            AGENT,
        ),
        201,
    )

    assert camera_case["warranty_state"] == "IN_WARRANTY"
    assert camera_case["routing_target"] == "MANUFACTURER"
    assert sensor_case["warranty_state"] == "IN_WARRANTY"
    assert sensor_case["routing_target"] == "IN_HOUSE_DEPOT"
    assert camera_case["hold_amount_cents"] == 0
    assert sensor_case["hold_amount_cents"] == 0
    assert_same_instant(
        camera_device["warranty_expires_at"],
        "2027-10-01T00:00:00Z",
        "Device.warranty_expires_at",
    )


def test_the_thirty_day_advance_replacement_floor_is_inclusive(api):
    """PRD 3.11: "3. Otherwise, if the in-force plan's `advance_replacement_eligible` is
    true, the model's `device_class` is `CAMERA` or `LOCK`, **and** the remaining
    warranty days are at least 30, the target is `ADVANCE_REPLACEMENT`. Hubs carry no
    such floor; cameras and locks do."
    PRD 3.11: "The remaining warranty days are the whole days from the clock to
    `warranty_expires_at` by floor division on an 86 400-second day, clamped below at
    0."
    PRD 3.11: "**The hold** is computed only when the target is `ADVANCE_REPLACEMENT`:
    `hold_amount_cents` is the model's `msrp_cents` multiplied by 0.60, rounded half
    up to whole cents, and `hold_state` is set to `HELD`."

    Both cameras expire 2026-06-01. From 2026-05-02 exactly 30 whole days remain and
    the case routes to ADVANCE_REPLACEMENT with round_half_up(12900 * 0.60) == 7740;
    one day later only 29 remain and the identical unit falls through to MANUFACTURER.

    Design: Corner/calculations/advance_replacement_thirty_day_warranty_floor_is_inclusive
    """
    world = setup_account_with_catalog(
        "CAMERA", plan_kind="PRO", allow_overage=False, name="Floor House", email_prefix="flr"
    )
    first = claim(
        world["household"]["id"],
        world["catalog"]["id"],
        "CMA000001",
        world["owner_headers"],
        purchase_date="2024-06-01",
    )
    second = claim(
        world["household"]["id"],
        world["catalog"]["id"],
        "CMA000002",
        world["owner_headers"],
        purchase_date="2024-06-01",
    )
    assert_same_instant(
        first["warranty_expires_at"], "2026-06-01T00:00:00Z", "Device.warranty_expires_at"
    )

    set_clock("2026-05-02T00:00:00Z")
    at_the_floor = open_rma(first["id"], first["version"])
    set_clock("2026-05-03T00:00:00Z")
    below_the_floor = open_rma(second["id"], second["version"])

    assert at_the_floor["routing_target"] == "ADVANCE_REPLACEMENT"
    assert at_the_floor["hold_amount_cents"] == 7740
    assert at_the_floor["hold_state"] == "HELD"
    assert below_the_floor["routing_target"] == "MANUFACTURER"
    assert below_the_floor["hold_amount_cents"] == 0
    assert below_the_floor["hold_state"] == "NONE"


def test_a_second_rma_case_supersedes_the_first_and_records_the_link(api):
    """PRD 3.11: "Creation also supersedes: any prior case on the same device whose
    `status` is `OPEN` or `ROUTED` moves to `SUPERSEDED`, and the new case records
    that prior case's id in its own `supersedes_rma_id`."
    PRD 3.11: "Cases may be listed with optional `device_id`, `ticket_id` and
    `supersedes_rma_id` filters alongside `limit` and `offset` — the third filter is
    how an operator traces a supersession chain"

    Design: Corner/state_machines/opening_a_second_rma_supersedes_the_prior_open_case
    """
    world = setup_advance_replacement_case(name="Sup House", email_prefix="sup")
    first_case = world["rma"]
    device_now = fetch_device(world["device"]["id"])

    second_case = validate_success(
        api.open_rma_case(
            {
                "device_id": world["device"]["id"],
                "expected_device_version": device_now["version"],
            },
            AGENT,
        ),
        201,
    )

    assert fetch_rma(first_case["id"])["status"] == "SUPERSEDED"
    assert second_case["supersedes_rma_id"] == first_case["id"]
    assert second_case["status"] == "ROUTED"
    assert second_case["routing_target"] == "ADVANCE_REPLACEMENT"
    assert second_case["hold_amount_cents"] == 14940

    traced = list_rma_cases(supersedes_rma_id=first_case["id"])
    assert len(traced) == 1
    assert traced[0]["id"] == second_case["id"]


def test_shipping_an_advance_unit_on_a_manufacturer_case_is_not_eligible(api):
    """PRD 3.11: "Shipping the replacement is refused with
    `ERR_ADVANCE_REPLACEMENT_NOT_ELIGIBLE` unless `routing_target` is
    `ADVANCE_REPLACEMENT`, and requires the case to be `ROUTED`."

    Design: Corner/validations/shipping_an_advance_unit_on_a_depot_case_is_not_eligible
    """
    world = setup_account_with_catalog(
        "CAMERA", plan_kind="PLUS", allow_overage=False, name="Depot House", email_prefix="dep"
    )
    device = claim_and_activate(
        world["household"]["id"], world["catalog"]["id"], "CMA000001", world["owner_headers"]
    )
    case = open_rma(device["id"], device["version"])
    assert case["routing_target"] == "MANUFACTURER"

    response = api.ship_advance_replacement(case["id"], {}, AGENT)
    validate_error(response, ApiErrorId.ERR_ADVANCE_REPLACEMENT_NOT_ELIGIBLE.value, 409)

    current = fetch_rma(case["id"])
    assert current["status"] == "ROUTED"
    assert current["routing_target"] == "MANUFACTURER"
    assert_is_null(current, "shipped_at", "RmaCase")
    assert current["hold_state"] == "NONE"
    assert fetch_device(device["id"])["lifecycle_status"] == "ACTIVE"


def test_closing_the_return_window_before_the_deadline_is_refused(api):
    """PRD 3.11: "On success `shipped_at` is stamped with the logical-clock instant,
    `return_deadline_at` is computed as `shipped_at` plus 14 days, the case walks
    `ROUTED → ADVANCE_SHIPPED → AWAITING_RETURN` inside the one request, and the
    device moves `ACTIVE → SUSPENDED_RMA`."
    PRD 3.11: "On a case still in `AWAITING_RETURN` it requires the logical clock to be
    **strictly after** `return_deadline_at`; called at or before the deadline it is
    refused with `ERR_RETURN_WINDOW_OPEN`."

    Design: Corner/validations/closing_the_return_window_early_returns_return_window_open
    """
    world = setup_shipped_advance_case(name="Hold House", email_prefix="hol")
    set_clock("2026-05-10T00:00:00Z")

    response = api.close_return_window(world["rma"]["id"], {}, AGENT)
    validate_error(response, ApiErrorId.ERR_RETURN_WINDOW_OPEN.value, 409)

    case = fetch_rma(world["rma"]["id"])
    assert case["status"] == "AWAITING_RETURN"
    assert_same_instant(
        case["return_deadline_at"], "2026-05-15T00:00:00Z", "RmaCase.return_deadline_at"
    )
    assert case["hold_state"] == "HELD"
    assert case["hold_amount_cents"] == 14940
    assert fetch_device(world["device"]["id"])["lifecycle_status"] == "SUSPENDED_RMA"
    assert (
        fetch_subscription(world["subscription"]["id"])["next_invoice_adjustment_cents"] == 0
    )


def test_reopening_an_rma_with_a_stale_device_version_is_rejected(api):
    """PRD 2.7: "**Opening an RMA case** requires the non-optional field
    `expected_device_version`, carrying the client's last observed `version` of the
    `Device` named by `device_id`. If it does not equal that device's current
    `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and
    nothing is written."
    PRD 3.11: "Opening a case bumps `Device.version` by one, which is precisely why
    the guard exists: a second case genuinely supersedes the first, so without the
    version check a caller acting on a stale view of the device would silently
    succeed."

    Design: Corner/cross_cutting_layers/occ_rma_create_with_a_stale_device_version_is_rejected
    """
    world = setup_advance_replacement_case(name="Occ1 House", email_prefix="occ1")
    stale_version = world["device"]["version"]

    response = api.open_rma_case(
        {"device_id": world["device"]["id"], "expected_device_version": stale_version}, AGENT
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value, 412)

    assert fetch_rma(world["rma"]["id"])["status"] == "ROUTED"
    assert len(list_rma_cases(device_id=world["device"]["id"])) == 1
