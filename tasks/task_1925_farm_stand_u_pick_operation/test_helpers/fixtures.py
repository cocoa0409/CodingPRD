"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. All roles are opaque (PRD §2.1), so the shared
header constants from TEST_USERS are used directly.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    DEFAULT_CLOSE_TIME,
    DEFAULT_OPEN_TIME,
    POLICY_A,
    WEEKDAY_DATE,
)
from .factories import (
    create_addon_booking_payload,
    create_addon_product_payload,
    create_crop_payload,
    create_field_payload,
    create_harvest_line_payload,
    create_offline_batch_payload,
    create_payment_payload,
    create_pricing_policy_payload,
    create_sales_day_payload,
    create_season_payload,
    create_visit_session_payload,
    create_waiver_payload,
    create_window_payload,
)
from .test_users import TEST_USERS

MANAGER = TEST_USERS["farm_manager_headers"]
GATE = TEST_USERS["gate_staff_headers"]
FIELD_STAFF = TEST_USERS["field_staff_headers"]
KIOSK = TEST_USERS["kiosk_device_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation / actions
# ---------------------------------------------------------------------------

def create_season(**overrides):
    """Create a season (born DRAFT with current_waiver_version 1)."""
    return get_success_data(
        api_client.create_season(create_season_payload(**overrides), MANAGER), 201)


def activate_season(season_id):
    """Move a season DRAFT -> ACTIVE. Returns the updated season."""
    return get_success_data(api_client.activate_season(season_id, MANAGER))


def create_policy(season_id, expected_season_version, **overrides):
    """Create a pricing policy (first one of a season is policy_version 1)."""
    return get_success_data(
        api_client.create_pricing_policy(
            create_pricing_policy_payload(season_id, expected_season_version,
                                          **overrides),
            MANAGER),
        201)


def create_policy_a(season_id, expected_season_version):
    """Create the canonical baseline policy (650/200/12500bps/1000bps/1500)."""
    return create_policy(season_id, expected_season_version, **POLICY_A)


def create_crop(season_id, **overrides):
    return get_success_data(
        api_client.create_crop(create_crop_payload(season_id, **overrides), MANAGER),
        201)


def create_field(season_id, **overrides):
    return get_success_data(
        api_client.create_field(create_field_payload(season_id, **overrides), MANAGER),
        201)


def create_sales_day(season_id, **overrides):
    return get_success_data(
        api_client.create_sales_day(
            create_sales_day_payload(season_id, **overrides), MANAGER),
        201)


def set_clock(to_iso8601):
    """Advance the server's logical clock (PRD §2.4)."""
    return get_success_data(api_client.set_clock(to_iso8601, MANAGER))


def open_sales_day(day_id):
    return get_success_data(api_client.open_day(day_id, MANAGER))


def open_field(field_id):
    return get_success_data(api_client.open_field(field_id, MANAGER))


def create_window(field_id, **overrides):
    return get_success_data(
        api_client.create_window(create_window_payload(field_id, **overrides), MANAGER),
        201)


def open_window(window_id):
    return get_success_data(api_client.open_window(window_id, MANAGER))


def sign_waiver(season_id, names, **overrides):
    """Sign a waiver at the public kiosk; names cover the whole party."""
    return get_success_data(
        api_client.create_waiver(
            create_waiver_payload(season_id, party_member_names=list(names),
                                  **overrides),
            ANON),
        201)


# ---------------------------------------------------------------------------
# Tier 2: operating-day composite (season + policy + crop + field + day +
# window + waiver). Flags let individual tests leave one layer unbuilt.
# ---------------------------------------------------------------------------

def setup_operating_day(*, date=WEEKDAY_DATE, day_type="WEEKDAY",
                        clock_at="2026-08-04T09:30:00Z",
                        picking_capacity_slots=30, parking_capacity=50,
                        staff_on_duty=3, estimated_harvest_oz=1000,
                        crop_price_per_lb=480, waiver_names=("Ann",),
                        activate=True, with_policy=True, with_crop=True,
                        do_open_field=True, do_open_day=True,
                        window_times=(DEFAULT_OPEN_TIME, DEFAULT_CLOSE_TIME),
                        do_open_window=True, policy_values=None,
                        field_name="North", rotation_order=1):
    """Build the canonical operating base. Returns a dict of live entities."""
    world = {}
    season = create_season()
    world["season_id"] = season["id"]
    if activate:
        season = activate_season(season["id"])
    world["season"] = season
    if with_policy:
        values = dict(POLICY_A)
        if policy_values:
            values.update(policy_values)
        policy = create_policy(season["id"], season["version"], **values)
        world["policy"] = policy
        world["policy_id"] = policy["id"]
    if with_crop:
        crop = create_crop(season["id"], price_per_lb_cents=crop_price_per_lb)
        world["crop_id"] = crop["id"]
    field = create_field(season["id"], name=field_name, rotation_order=rotation_order,
                         estimated_harvest_oz=estimated_harvest_oz)
    world["field"] = field
    world["field_id"] = field["id"]
    day = create_sales_day(season["id"], date=date, day_type=day_type,
                           parking_capacity=parking_capacity,
                           staff_on_duty=staff_on_duty)
    world["day_id"] = day["id"]
    if clock_at:
        set_clock(clock_at)
    if do_open_day:
        world["day"] = open_sales_day(day["id"])
    if do_open_field:
        world["field"] = open_field(field["id"])
    if window_times:
        window = create_window(field["id"], date=date, open_time=window_times[0],
                               close_time=window_times[1],
                               picking_capacity_slots=picking_capacity_slots)
        world["window_id"] = window["id"]
        if do_open_window:
            world["window"] = open_window(window["id"])
    if waiver_names is not None:
        world["waiver_id"] = sign_waiver(season["id"], list(waiver_names))["id"]
    return world


# ---------------------------------------------------------------------------
# Tier 3: session lifecycle shortcuts
# ---------------------------------------------------------------------------

def admit_online_session(world, *, party_size=1, container_count=0,
                         parking_spaces=0, waiver_id=None, window_id=None):
    """Admit a party at the gate (ONLINE origin). Returns the new session."""
    return get_success_data(
        api_client.create_visit_session(
            create_visit_session_payload(
                window_id or world["window_id"],
                waiver_id or world["waiver_id"],
                party_size=party_size,
                container_count=container_count,
                parking_spaces=parking_spaces),
            GATE),
        201)


def pay_amount(session_id, amount_cents, *, method="CASH", key="k1", headers=GATE):
    """Collect a CHARGE payment; returns the payment row."""
    return get_success_data(
        api_client.create_payment(
            create_payment_payload(session_id, method=method,
                                   amount_cents=amount_cents, idempotency_key=key),
            headers),
        201)


def pay_admission(session, *, method="CASH", key="k-adm", headers=GATE):
    """Pay exactly the session's pinned admission_charge_cents."""
    return pay_amount(session["id"], session["admission_charge_cents"],
                      method=method, key=key, headers=headers)


def enter_session(session_id):
    """Move a session CHECKED_IN -> FIELD_ACTIVE."""
    return get_success_data(api_client.enter_field(session_id, FIELD_STAFF))


def setup_paid_session(world, *, enter=False, party_size=1, container_count=0,
                       parking_spaces=0, method="CASH", key="k-adm",
                       waiver_id=None):
    """Admit + pay admission; optionally enter the field. Returns the session."""
    session = admit_online_session(world, party_size=party_size,
                                   container_count=container_count,
                                   parking_spaces=parking_spaces,
                                   waiver_id=waiver_id)
    pay_admission(session, method=method, key=key)
    if enter:
        session = enter_session(session["id"])
    return session


def weigh_out(session_id, crop_id, gross_weight_oz, container_count):
    """Staff weigh-out: creates a line born FINALIZED (PRD §3.5)."""
    return get_success_data(
        api_client.create_harvest_line(
            create_harvest_line_payload(session_id, crop_id,
                                        gross_weight_oz=gross_weight_oz,
                                        container_count=container_count),
            FIELD_STAFF),
        201)


def create_addon_product(season_id, **overrides):
    return get_success_data(
        api_client.create_addon_product(
            create_addon_product_payload(season_id, **overrides), MANAGER),
        201)


def book_addon(session_id, addon_product_id, **overrides):
    return get_success_data(
        api_client.create_addon_booking(
            create_addon_booking_payload(session_id, addon_product_id, **overrides),
            GATE),
        201)


# ---------------------------------------------------------------------------
# Tier 4: offline batch helpers
# ---------------------------------------------------------------------------

def upload_batch(device_id, batch_id, records, headers=KIOSK):
    """Upload an offline batch; returns the stored batch row."""
    return get_success_data(
        api_client.create_offline_batch(
            create_offline_batch_payload(device_id, batch_id, records), headers),
        201)


def only_session_on_window(window_id):
    """Read back the single session admitted on a window."""
    data, meta = validate_paginated(
        api_client.list_visit_sessions(MANAGER, params={"window_id": window_id}))
    assert meta["total_count"] >= 1, "expected at least one session on the window"
    return data[0]


def only_line_of_session(session_id):
    """Read back the single harvest line of a session."""
    data, meta = validate_paginated(
        api_client.list_harvest_lines(MANAGER, params={"session_id": session_id}))
    assert meta["total_count"] == 1, f"expected exactly one line, got {meta}"
    return data[0]


# ---------------------------------------------------------------------------
# Tier 5: field-state readers
# ---------------------------------------------------------------------------

def get_field(field_id):
    return get_success_data(api_client.get_field(field_id, MANAGER))


def get_session(session_id):
    return get_success_data(api_client.get_visit_session(session_id, MANAGER))


def get_window(window_id):
    return get_success_data(api_client.get_window(window_id, MANAGER))


def get_crop(crop_id):
    return get_success_data(api_client.get_crop(crop_id, MANAGER))


def get_sales_day(day_id):
    return get_success_data(api_client.get_sales_day(day_id, MANAGER))


def get_payment(payment_id):
    return get_success_data(api_client.get_payment(payment_id, MANAGER))
