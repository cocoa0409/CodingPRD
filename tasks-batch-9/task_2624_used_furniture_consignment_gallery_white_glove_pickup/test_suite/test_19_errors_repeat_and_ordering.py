"""Doing a one-way thing twice, and asking for a window that runs backwards."""

from test_helpers import (
    GALLERY_MANAGER,
    LOGISTICS_COORDINATOR,
    ApiErrorId,
    api_client,
    buyer_payload,
    consignor_payload,
    create_buyer,
    create_consignor,
    create_price_schedule,
    create_truck,
    create_zone,
    fetch_buyer,
    fetch_price_schedule,
    fetch_zone,
    get_success_data,
    pickup_job_payload,
    price_schedule_step_payload,
    total_count,
    validate_error,
)

SHARED_ADDRESS = "alpha@example.com"
ONE_STEP = [(1, 0, 0.00, 0)]


def test_registering_a_second_consignor_on_the_same_email_is_refused():
    """The address is unique among consignors, and a buyer may still carry it.

    PRD 3.1: "The `email` must not already belong to another consignor, and a collision is
    refused with `ERR_DUPLICATE_EMAIL`."

    PRD 3.1: "A buyer's `email` is likewise unique across buyers, with
    `ERR_DUPLICATE_EMAIL` on collision, and a new buyer opens with `status` `ACTIVE`."

    Design: Corner/errors/registering_a_second_consignor_on_the_same_email_is_refused
    """
    create_consignor(display_name="Alpha", email=SHARED_ADDRESS, address_line="1 A St")

    twin = api_client.create_consignor(
        consignor_payload(
            display_name="Alpha Twin",
            email=SHARED_ADDRESS,
            address_line="2 A St",
            floor_number=2,
        ),
        GALLERY_MANAGER,
    )
    validate_error(twin, ApiErrorId.ERR_DUPLICATE_EMAIL, 409)

    listed = api_client.list_consignors(GALLERY_MANAGER, params={"limit": 100})
    assert total_count(listed) == 1, (
        f"Expected the refused registration to open no second account, "
        f"got {total_count(listed)}"
    )

    at_the_register = api_client.create_buyer(
        buyer_payload(display_name="Alpha Buyer", email=SHARED_ADDRESS), GALLERY_MANAGER
    )
    assert at_the_register.status_code == 201, (
        f"Expected the same address to be free among buyers, "
        f"got {at_the_register.status_code}: {at_the_register.text}"
    )
    buyer = get_success_data(at_the_register)
    assert buyer["email"] == SHARED_ADDRESS, (
        f"Expected the shared address stored, got {buyer['email']}"
    )
    assert buyer["status"] == "ACTIVE", (
        f"Expected ACTIVE, got {buyer['status']}"
    )


def test_blocking_an_already_blocked_buyer_is_refused():
    """The second block is a refusal, so the buyer's version stops at two.

    PRD 3.1: "A manager may later move a buyer to `BLOCKED`, which bumps the buyer's
    `version` by 1 and bars future purchases while leaving every existing `Sale` and
    `DeliveryOrder` completely untouched; attempting to block a buyer who is already
    `BLOCKED` is refused with `ERR_BUYER_BLOCKED`."

    PRD 2.4: "`version`, an integer that begins at 1 on creation and increments by exactly
    1 on each mutation that actually changes a stored field."

    Design: Corner/errors/blocking_an_already_blocked_buyer_is_refused
    """
    buyer = create_buyer(display_name="Nora Vance", floor_number=2)
    assert buyer["version"] == 1, (
        f"Expected a fresh buyer at version 1, got {buyer['version']}"
    )

    blocked = get_success_data(api_client.block_buyer(buyer["id"], GALLERY_MANAGER))
    assert blocked["status"] == "BLOCKED", (
        f"Expected BLOCKED, got {blocked['status']}"
    )
    assert blocked["version"] == 2, (
        f"Expected version 2 after the single block, got {blocked['version']}"
    )

    again = api_client.block_buyer(buyer["id"], GALLERY_MANAGER)
    validate_error(again, ApiErrorId.ERR_BUYER_BLOCKED, 409)

    after = fetch_buyer(buyer["id"])
    assert after["status"] == "BLOCKED", (
        f"Expected BLOCKED still, got {after['status']}"
    )
    assert after["version"] == 2, (
        f"Expected version 2 rather than 3, got {after['version']}"
    )


def test_closing_an_already_closed_zone_is_refused():
    """An empty zone can be shut once; the second attempt changes nothing.

    PRD 3.1: "A manager may close a zone, which sets `status` to `CLOSED` and increments
    the zone's `version` by 1 while leaving `occupied_sqft` untouched and every piece
    already inside it exactly where it stands — a closed zone refuses new placements and
    new counts, it does not evacuate."

    PRD 3.1: "Closing an already-closed zone is refused with `ERR_ZONE_CLOSED`."

    Design: Corner/errors/closing_an_already_closed_zone_is_refused
    """
    zone = create_zone(name="Front A", zone_type="SHOWROOM_FRONT", capacity_sqft=200)
    assert zone["occupied_sqft"] == 0, (
        f"Expected an empty zone, got {zone['occupied_sqft']}"
    )

    closed = get_success_data(api_client.close_zone(zone["id"], GALLERY_MANAGER))
    assert closed["status"] == "CLOSED", (
        f"Expected CLOSED, got {closed['status']}"
    )
    assert closed["version"] == 2, (
        f"Expected version 2 after the single close, got {closed['version']}"
    )

    again = api_client.close_zone(zone["id"], GALLERY_MANAGER)
    validate_error(again, ApiErrorId.ERR_ZONE_CLOSED, 409)

    after = fetch_zone(zone["id"])
    assert after["status"] == "CLOSED", (
        f"Expected CLOSED still, got {after['status']}"
    )
    assert after["version"] == 2, (
        f"Expected version 2 rather than 3, got {after['version']}"
    )
    assert after["occupied_sqft"] == 0, (
        f"Expected no square feet claimed by the refusal, got {after['occupied_sqft']}"
    )


def test_retiring_an_already_retired_schedule_is_refused():
    """Retirement is one-way, and the step already appended survives the refusal.

    PRD 3.1: "Retiring a schedule closes it to new business without disturbing old
    business: its `status` becomes `RETIRED`, its `version` increments by 1, no new
    agreement may reference it, and every `ACTIVE` agreement that already references it
    keeps marking its items down exactly as before."

    PRD 3.1: "Retiring a schedule that is already `RETIRED`, or referencing a `RETIRED`
    schedule when drafting or activating an agreement, is refused with
    `ERR_SCHEDULE_RETIRED`."

    Design: Corner/errors/retiring_an_already_retired_schedule_is_refused
    """
    schedule = create_price_schedule(steps=ONE_STEP, name="STD-2026")
    assert schedule["step_count"] == 1, (
        f"Expected one step attached, got {schedule['step_count']}"
    )

    retired = get_success_data(
        api_client.retire_price_schedule(schedule["id"], GALLERY_MANAGER)
    )
    assert retired["status"] == "RETIRED", (
        f"Expected RETIRED, got {retired['status']}"
    )
    assert retired["version"] == schedule["version"] + 1, (
        f"Expected the retirement to bump {schedule['version']} by one, "
        f"got {retired['version']}"
    )

    again = api_client.retire_price_schedule(schedule["id"], GALLERY_MANAGER)
    validate_error(again, ApiErrorId.ERR_SCHEDULE_RETIRED, 409)

    after = fetch_price_schedule(schedule["id"])
    assert after["status"] == "RETIRED", (
        f"Expected RETIRED still, got {after['status']}"
    )
    assert after["step_count"] == 1, (
        f"Expected the step untouched, got {after['step_count']}"
    )
    assert after["version"] == retired["version"], (
        f"Expected version {retired['version']} unchanged by the refusal, "
        f"got {after['version']}"
    )

    steps = api_client.list_price_schedule_steps(
        schedule["id"], GALLERY_MANAGER, params={"limit": 100}
    )
    assert total_count(steps) == 1, (
        f"Expected one step still readable, got {total_count(steps)}"
    )


def test_appending_a_step_at_a_non_increasing_offset_is_refused():
    """The sequence number is right; the day offset is not, and that is enough.

    PRD 3.1: "Appends must be strictly ordered: the submitted `sequence` must equal the
    schedule's current `step_count` plus 1, the `start_day_offset` must be strictly greater
    than the previous step's `start_day_offset`, and the very first step must sit at offset
    0."

    PRD 3.1: "A successful append recomputes `step_count` and increments the schedule's
    `version` by 1."

    Design: Corner/errors/appending_a_step_at_a_non_increasing_offset_is_refused
    """
    schedule = create_price_schedule(steps=ONE_STEP, name="STD-2026")
    assert schedule["step_count"] == 1 and schedule["version"] == 2, (
        f"Expected one accepted append to leave step_count 1 and version 2, "
        f"got {schedule['step_count']} and {schedule['version']}"
    )

    flat = api_client.create_price_schedule_step(
        price_schedule_step_payload(schedule["id"], 2, 0, 0.15, 0), GALLERY_MANAGER
    )
    validate_error(flat, ApiErrorId.ERR_SCHEDULE_STEP_OVERLAP, 422)

    after = fetch_price_schedule(schedule["id"])
    assert after["step_count"] == 1, (
        f"Expected the refused append to attach nothing, got {after['step_count']}"
    )
    assert after["version"] == 2, (
        f"Expected version 2, bumped only by the accepted append, "
        f"got {after['version']}"
    )

    one_day_later = api_client.create_price_schedule_step(
        price_schedule_step_payload(schedule["id"], 2, 1, 0.15, 0), GALLERY_MANAGER
    )
    assert one_day_later.status_code == 201, (
        f"Expected the same step one day out to be accepted, "
        f"got {one_day_later.status_code}: {one_day_later.text}"
    )
    grown = fetch_price_schedule(schedule["id"])
    assert grown["step_count"] == 2, (
        f"Expected two steps, got {grown['step_count']}"
    )
    assert grown["version"] == 3, (
        f"Expected version 3, got {grown['version']}"
    )


def test_a_pickup_window_that_ends_when_it_starts_is_refused():
    """An empty truck calendar cannot excuse a window of zero length.

    PRD 3.4: "`window_start` must be strictly before `window_end`, or the request is
    refused with `ERR_WINDOW_ORDER_INVALID`."

    PRD 3.4: "Beyond that, a truck needs a **45-minute turnaround gap** between consecutive
    jobs to unload and reposition, so the requested window is compared against every other
    non-terminal job already reserved on the same truck."

    Design: Corner/errors/a_pickup_window_that_ends_when_it_starts_is_refused
    """
    consignor = create_consignor(display_name="Alpha", address_line="1 A St")
    truck = create_truck(name="BOX-1", capacity_volume_cuft=100)

    instantaneous = api_client.create_pickup_job(
        pickup_job_payload(
            consignor["id"],
            truck["id"],
            "2026-08-01T09:00:00Z",
            "2026-08-01T09:00:00Z",
        ),
        LOGISTICS_COORDINATOR,
    )
    validate_error(instantaneous, ApiErrorId.ERR_WINDOW_ORDER_INVALID, 422)

    listed = api_client.list_pickup_jobs(LOGISTICS_COORDINATOR, params={"limit": 100})
    assert total_count(listed) == 0, (
        f"Expected no job reserved, got {total_count(listed)}"
    )

    coherent = api_client.create_pickup_job(
        pickup_job_payload(
            consignor["id"],
            truck["id"],
            "2026-08-01T09:00:00Z",
            "2026-08-01T09:00:01Z",
        ),
        LOGISTICS_COORDINATOR,
    )
    assert coherent.status_code == 201, (
        f"Expected a one-second window to clear the strict comparison, "
        f"got {coherent.status_code}: {coherent.text}"
    )
    assert get_success_data(coherent)["status"] == "SCHEDULED", (
        "Expected the coherent window to reserve the truck"
    )
