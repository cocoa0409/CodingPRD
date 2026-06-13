"""Field scheduling: slot capacity, technician travel-buffer overlap, OCC on booking."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_install_appointment_payload,
    setup_draft_tech_install_order, get_account_version,
)

AGENT = TEST_USERS["provisioning_agent_headers"]


# ===========================================================================
# Queue A — resource_temporal_overlap: aggregate slot capacity
# ===========================================================================
def test_slot_at_capacity_rejects_extra_booking_regardless_of_time(api):
    """PRD §3.4: "The slot must have room: if its `booked_count` has already
    reached `capacity` the booking is rejected with `ERR_SLOT_AT_CAPACITY`."

    Design: Difficulty/resource_temporal_overlap/install_slot_aggregate_capacity_overlap
    """
    ctx = setup_draft_tech_install_order(slot_capacity=1)
    addr, plan, slot = ctx["address"], ctx["plan"], ctx["slot"]
    # First booking fills the capacity-1 slot.
    from test_helpers import create_account, create_order
    acct1 = create_account(addr["id"], plan["id"], "cust-c1")
    order1 = create_order(acct1["id"], plan["id"], install_mode="TECH_INSTALL")
    get_success_data(api.create_install_appointment(
        create_install_appointment_payload(order1["id"], slot["id"], acct1["version"],
                                            start_iso="2026-06-02T09:00:00Z",
                                            end_iso="2026-06-02T10:00:00Z"), AGENT))
    # Second booking at a non-overlapping time is still rejected: count is full.
    acct2 = create_account(addr["id"], plan["id"], "cust-c2")
    order2 = create_order(acct2["id"], plan["id"], install_mode="TECH_INSTALL")
    resp = api.create_install_appointment(
        create_install_appointment_payload(order2["id"], slot["id"], acct2["version"],
                                            start_iso="2026-06-02T13:00:00Z",
                                            end_iso="2026-06-02T14:00:00Z"), AGENT)
    validate_error(resp, ApiErrorId.ERR_SLOT_AT_CAPACITY, expected_status=409)
    slot_after = validate_success(api.get_install_slot(slot["id"], AGENT))
    assert slot_after["booked_count"] == 1, \
        f"slot booked_count must stay 1, got {slot_after['booked_count']}"


def test_slot_status_flips_to_full_when_capacity_reached(api):
    """PRD §3.4: "its `status` becomes `FULL` precisely when `booked_count` equals `capacity".

    Design: Difficulty/resource_temporal_overlap/install_slot_aggregate_capacity_overlap
    """
    ctx = setup_draft_tech_install_order(slot_capacity=1)
    addr, plan, slot = ctx["address"], ctx["plan"], ctx["slot"]
    from test_helpers import create_account, create_order
    acct1 = create_account(addr["id"], plan["id"], "cust-full")
    order1 = create_order(acct1["id"], plan["id"], install_mode="TECH_INSTALL")
    get_success_data(api.create_install_appointment(
        create_install_appointment_payload(order1["id"], slot["id"], acct1["version"]), AGENT))
    slot_after = validate_success(api.get_install_slot(slot["id"], AGENT))
    assert slot_after["status"] == "FULL", \
        f"slot must be FULL when booked_count == capacity, got {slot_after['status']}"


# ===========================================================================
# Queue A — resource_temporal_overlap: technician travel-buffer interval
# ===========================================================================
def test_technician_double_booked_within_travel_buffer(api):
    """PRD §3.4: "the half-open interval from the appointment's `start_iso`
    through its `end_iso` extended by the technician's `travel_buffer_minutes`
    must not intersect any other `BOOKED` or `COMPLETED` appointment of the same
    technician, and an intersection is rejected with `ERR_TECHNICIAN_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/technician_travel_buffer_interval_overlap
    """
    # Slot capacity 5 so capacity is never the binding constraint.
    ctx = setup_draft_tech_install_order(slot_capacity=5)
    addr, plan, slot = ctx["address"], ctx["plan"], ctx["slot"]
    from test_helpers import create_account, create_order
    acct1 = create_account(addr["id"], plan["id"], "cust-b1")
    order1 = create_order(acct1["id"], plan["id"], install_mode="TECH_INSTALL")
    # First appointment 09:00-10:00; buffer 30 blocks the tech until 10:30.
    get_success_data(api.create_install_appointment(
        create_install_appointment_payload(order1["id"], slot["id"], acct1["version"],
                                            start_iso="2026-06-02T09:00:00Z",
                                            end_iso="2026-06-02T10:00:00Z"), AGENT))
    # Second appointment 10:15 falls inside the 09:00-10:30 buffered block.
    acct2 = create_account(addr["id"], plan["id"], "cust-b2")
    order2 = create_order(acct2["id"], plan["id"], install_mode="TECH_INSTALL")
    resp = api.create_install_appointment(
        create_install_appointment_payload(order2["id"], slot["id"], acct2["version"],
                                            start_iso="2026-06-02T10:15:00Z",
                                            end_iso="2026-06-02T11:00:00Z"), AGENT)
    validate_error(resp, ApiErrorId.ERR_TECHNICIAN_DOUBLE_BOOKED, expected_status=409)


def test_technician_booking_at_buffer_end_half_open_succeeds(api):
    """PRD §3.4: "the half-open interval from the appointment's `start_iso`
    through its `end_iso` extended by the technician's `travel_buffer_minutes`
    must not intersect any other `BOOKED` or `COMPLETED` appointment of the same
    technician".

    A start at exactly buffer-end (10:30) does not intersect the half-open block.

    Design: Difficulty/resource_temporal_overlap/technician_travel_buffer_interval_overlap
    """
    ctx = setup_draft_tech_install_order(slot_capacity=5)
    addr, plan, slot = ctx["address"], ctx["plan"], ctx["slot"]
    from test_helpers import create_account, create_order
    acct1 = create_account(addr["id"], plan["id"], "cust-h1")
    order1 = create_order(acct1["id"], plan["id"], install_mode="TECH_INSTALL")
    get_success_data(api.create_install_appointment(
        create_install_appointment_payload(order1["id"], slot["id"], acct1["version"],
                                            start_iso="2026-06-02T09:00:00Z",
                                            end_iso="2026-06-02T10:00:00Z"), AGENT))
    acct2 = create_account(addr["id"], plan["id"], "cust-h2")
    order2 = create_order(acct2["id"], plan["id"], install_mode="TECH_INSTALL")
    resp = api.create_install_appointment(
        create_install_appointment_payload(order2["id"], slot["id"], acct2["version"],
                                            start_iso="2026-06-02T10:30:00Z",
                                            end_iso="2026-06-02T11:30:00Z"), AGENT)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "BOOKED", \
        f"appointment at buffer-end must book, got status {data['status']}"


# ===========================================================================
# Queue B — validations: appointment outside slot window
# ===========================================================================
def test_appointment_outside_slot_window_rejected(api):
    """PRD §3.4: "the half-open interval from `start_iso` to `end_iso` must fall entirely within the slot's window from `window_start_iso` to `window_end_iso`, and an appointment that spills outside the slot window is rejected with `ERR_APPOINTMENT_OUTSIDE_SLOT` (HTTP 422)."

    Design: Corner/validations/appointment_outside_slot_window_rejected
    """
    ctx = setup_draft_tech_install_order(slot_capacity=2)
    # Slot window is 09:00-17:00; this appointment starts at 08:30 (before window).
    resp = api.create_install_appointment(
        create_install_appointment_payload(ctx["order"]["id"], ctx["slot"]["id"],
                                            ctx["account"]["version"],
                                            start_iso="2026-06-02T08:30:00Z",
                                            end_iso="2026-06-02T09:30:00Z"), AGENT)
    validate_error(resp, ApiErrorId.ERR_APPOINTMENT_OUTSIDE_SLOT, expected_status=422)


# ===========================================================================
# Queue B — cross_cutting: OCC on booking, correct then stale
# ===========================================================================
def test_booking_with_correct_then_stale_version(api):
    """PRD §2.11: "The server compares that value against the account's current `version`; if they match, the operation proceeds and increments the account's `version` by one, and if they differ the operation is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412)."
    PRD §3.4: "because booking is one of the four OCC-guarded account writes of §2.11 — increments the account's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_then_stale_fails_on_booking
    """
    ctx = setup_draft_tech_install_order(slot_capacity=2)
    plan, slot, acct = ctx["plan"], ctx["slot"], ctx["account"]
    from test_helpers import create_order
    order2 = create_order(acct["id"], plan["id"], order_type="UPGRADE",
                          install_mode="TECH_INSTALL")
    # First booking with version 1 succeeds, bumping account version to 2.
    first = validate_success(api.create_install_appointment(
        create_install_appointment_payload(ctx["order"]["id"], slot["id"], acct["version"],
                                            start_iso="2026-06-02T09:00:00Z",
                                            end_iso="2026-06-02T10:00:00Z"), AGENT),
        expected_status=201)
    assert first["status"] == "BOOKED"
    assert get_account_version(acct["id"]) == 2, "account version must advance to 2"
    # Second booking still carrying the now-stale version 1 fails.
    resp = api.create_install_appointment(
        create_install_appointment_payload(order2["id"], slot["id"], acct["version"],
                                            start_iso="2026-06-02T11:00:00Z",
                                            end_iso="2026-06-02T12:00:00Z"), AGENT)
    validate_error(resp, ApiErrorId.ERR_STALE_ACCOUNT_VERSION, expected_status=412)
