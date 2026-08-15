"""Composite setup helpers for multi-step test prerequisites.

The test runner restarts the API server before every test, so every fixture
builds its preconditions from scratch using only PRD-declared endpoints.
Setup calls use get_success_data() so a failed precondition surfaces as a
clear "setup failed" error rather than a confusing assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    approve_order_payload,
    as_run_entry,
    create_advertiser_payload,
    create_avail_unit_payload,
    create_avail_week_payload,
    create_copy_instruction_payload,
    create_log_day_payload,
    create_order_line_payload,
    create_order_payload,
    create_program_payload,
    place_spot_payload,
    preempt_payload,
    reconcile_payload,
)
from .test_users import TEST_USERS

SALESREP = TEST_USERS["salesrep_headers"]
TRAFFIC = TEST_USERS["trafficmanager_headers"]
COPYDESK = TEST_USERS["copycoordinator_headers"]
BILLING = TEST_USERS["billingclerk_headers"]
ADMIN = TEST_USERS["stationadmin_headers"]


# --- Tier 1: single-entity creation and single-action helpers -------------

def create_advertiser(**overrides):
    return get_success_data(
        api_client.create_advertiser(create_advertiser_payload(**overrides), SALESREP)
    )


def create_program(**overrides):
    return get_success_data(
        api_client.create_program(create_program_payload(**overrides), TRAFFIC)
    )


def create_avail_week(week_start_date: str = "2026-08-03"):
    return get_success_data(
        api_client.create_avail_week(create_avail_week_payload(week_start_date), TRAFFIC)
    )


def create_avail_unit(
    week_id,
    program_id,
    air_date,
    total_seconds=TEST_DEFAULTS["TOTAL_SECONDS"],
    break_position=1,
    reserved_political_seconds=None,
):
    payload = create_avail_unit_payload(
        program_id,
        air_date,
        total_seconds=total_seconds,
        break_position=break_position,
        reserved_political_seconds=reserved_political_seconds,
    )
    return get_success_data(api_client.create_avail_unit(week_id, payload, TRAFFIC))


def get_avail_unit(unit_id):
    return get_success_data(api_client.get_avail_unit(unit_id, TRAFFIC))


def get_avail_week(week_id):
    return get_success_data(api_client.get_avail_week(week_id, TRAFFIC))


def create_order(
    advertiser_id,
    flight_start_date=TEST_DEFAULTS["FLIGHT_START"],
    flight_end_date=TEST_DEFAULTS["FLIGHT_END"],
):
    return get_success_data(
        api_client.create_order(
            create_order_payload(advertiser_id, flight_start_date, flight_end_date), SALESREP
        )
    )


def get_order(order_id):
    return get_success_data(api_client.get_order(order_id, SALESREP))


def add_order_line(
    order_id,
    program_id,
    weeks_requested=1,
    spots_per_week=1,
    spot_length_seconds=30,
    gross_rate_cents=TEST_DEFAULTS["GROSS_RATE_CENTS"],
    guaranteed_rating=0,
):
    payload = create_order_line_payload(
        program_id,
        weeks_requested=weeks_requested,
        spots_per_week=spots_per_week,
        spot_length_seconds=spot_length_seconds,
        gross_rate_cents=gross_rate_cents,
        guaranteed_rating=guaranteed_rating,
    )
    return get_success_data(api_client.add_order_line(order_id, payload, SALESREP))


def list_order_lines(order_id):
    return get_success_data(api_client.list_order_lines(order_id, SALESREP))


def submit_order(order_id):
    return get_success_data(api_client.submit_order(order_id, SALESREP))


def approve_order(order_id):
    """Approve a submitted order with a fresh OCC read (PRD §2.8)."""
    fresh = get_order(order_id)
    return get_success_data(
        api_client.approve_order(
            order_id, approve_order_payload(fresh["version"]), TRAFFIC
        )
    )


def create_approved_order(advertiser_id, program_id, line_specs=None,
                          flight_start_date=TEST_DEFAULTS["FLIGHT_START"],
                          flight_end_date=TEST_DEFAULTS["FLIGHT_END"]):
    """Create an order, add lines, submit, approve. Returns (order, lines).

    line_specs: list of kwargs dicts accepted by add_order_line.
    """
    if line_specs is None:
        line_specs = [{}]
    order = create_order(advertiser_id, flight_start_date, flight_end_date)
    lines = [add_order_line(order["id"], program_id, **spec) for spec in line_specs]
    submit_order(order["id"])
    order = approve_order(order["id"])
    return order, lines


def create_copy(advertiser_id, length_seconds=30, rotation_weight=None):
    """Register copy (starts PENDING, PRD §3.3)."""
    return get_success_data(
        api_client.create_copy_instruction(
            create_copy_instruction_payload(
                advertiser_id, length_seconds, rotation_weight=rotation_weight
            ),
            COPYDESK,
        )
    )


def create_received_copy(advertiser_id, length_seconds=30, rotation_weight=None):
    copy_row = create_copy(advertiser_id, length_seconds, rotation_weight)
    return get_success_data(api_client.receive_copy(copy_row["id"], COPYDESK))


def list_line_spots(line_id):
    return get_success_data(api_client.list_line_spots(line_id, TRAFFIC))


def get_spot(spot_id):
    return get_success_data(api_client.get_spot(spot_id, TRAFFIC))


def place_spot_fresh(spot_id, unit_id):
    """Read the unit's current version, then place (PRD §2.8, §3.5)."""
    unit = get_avail_unit(unit_id)
    return get_success_data(
        api_client.place_spot(
            spot_id, place_spot_payload(unit_id, unit["version"]), TRAFFIC
        )
    )


def preempt_spot(spot_id, reason="OVERSOLD"):
    return get_success_data(api_client.preempt_spot(spot_id, preempt_payload(reason), TRAFFIC))


def offer_make_good(spot_id):
    return get_success_data(api_client.offer_make_good(spot_id, TRAFFIC))


def create_log_day(week_id, log_date):
    return get_success_data(
        api_client.create_log_day(week_id, create_log_day_payload(log_date), TRAFFIC)
    )


def get_log_day(log_id):
    return get_success_data(api_client.get_log_day(log_id, TRAFFIC))


def finalize_log_day(log_id):
    return get_success_data(api_client.finalize_log_day(log_id, TRAFFIC))


def reconcile_log_day(log_id, entries):
    return get_success_data(
        api_client.reconcile_log_day(log_id, reconcile_payload(entries), BILLING)
    )


def list_log_day_as_run_entries(log_id):
    return get_success_data(api_client.list_log_day_as_run_entries(log_id, BILLING))


def get_post_buy(order_id, method_variant=None):
    params = {"method_variant": method_variant} if method_variant else None
    return get_success_data(api_client.get_post_buy(order_id, BILLING, params=params))


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# --- Tier 2/3: composite scenario builders --------------------------------

def setup_scheduled_scenario(
    category="RETAIL",
    credit_limit_cents=TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
    daypart="DAYTIME",
    airs_weekday=1,
    rating_estimate=2.0,
    is_political_window=False,
    week_start_date="2026-08-03",
    air_date="2026-08-03",
    total_seconds=TEST_DEFAULTS["TOTAL_SECONDS"],
    reserved_political_seconds=None,
    num_units=1,
    spot_length_seconds=30,
    spots_per_week=1,
    weeks_requested=1,
    gross_rate_cents=TEST_DEFAULTS["GROSS_RATE_CENTS"],
    guaranteed_rating=0,
    flight_start_date=TEST_DEFAULTS["FLIGHT_START"],
    flight_end_date=TEST_DEFAULTS["FLIGHT_END"],
    num_copies=1,
    copy_received=True,
    place_count=1,
    log_date=None,
    finalize=False,
):
    """Full chain: advertiser -> program -> week -> units -> approved order with
    one line -> copy pipeline -> placements -> optional log day (+finalize).

    Placements go to units[0], units[1], ... in spot order. Returns a dict with
    every entity created plus the placed spots and (optionally) the log day.
    """
    advertiser = create_advertiser(
        product_category=category, credit_limit_cents=credit_limit_cents
    )
    program = create_program(
        daypart_code=daypart,
        airs_weekday=airs_weekday,
        rating_estimate=rating_estimate,
        is_political_window=is_political_window,
    )
    week = create_avail_week(week_start_date)
    units = [
        create_avail_unit(
            week["id"],
            program["id"],
            air_date,
            total_seconds=total_seconds,
            break_position=i + 1,
            reserved_political_seconds=reserved_political_seconds,
        )
        for i in range(num_units)
    ]
    order, lines = create_approved_order(
        advertiser["id"],
        program["id"],
        line_specs=[
            {
                "weeks_requested": weeks_requested,
                "spots_per_week": spots_per_week,
                "spot_length_seconds": spot_length_seconds,
                "gross_rate_cents": gross_rate_cents,
                "guaranteed_rating": guaranteed_rating,
            }
        ],
        flight_start_date=flight_start_date,
        flight_end_date=flight_end_date,
    )
    copies = []
    if copy_received:
        copies = [
            create_received_copy(advertiser["id"], spot_length_seconds)
            for _ in range(num_copies)
        ]
    spots = list_line_spots(lines[0]["id"])
    placed = []
    for i in range(min(place_count, len(spots))):
        placed.append(place_spot_fresh(spots[i]["id"], units[i % num_units]["id"]))
    log = None
    if log_date is not None:
        log = create_log_day(week["id"], log_date)
        if finalize:
            log = finalize_log_day(log["id"])
    return {
        "advertiser": advertiser,
        "program": program,
        "week": week,
        "units": units,
        "order": order,
        "line": lines[0],
        "spots": spots,
        "placed": placed,
        "copies": copies,
        "log": log,
    }


def setup_second_advertiser_order(
    program_id,
    category="AUTOMOTIVE",
    credit_limit_cents=TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
    spot_length_seconds=30,
    spots_per_week=1,
    weeks_requested=1,
    gross_rate_cents=TEST_DEFAULTS["GROSS_RATE_CENTS"],
    guaranteed_rating=0,
    flight_start_date=TEST_DEFAULTS["FLIGHT_START"],
    flight_end_date=TEST_DEFAULTS["FLIGHT_END"],
):
    """A second advertiser with its own approved one-line order. Returns
    (advertiser, order, line, spots) — used by multi-party placement tests."""
    advertiser = create_advertiser(
        product_category=category, credit_limit_cents=credit_limit_cents
    )
    order, lines = create_approved_order(
        advertiser["id"],
        program_id,
        line_specs=[
            {
                "weeks_requested": weeks_requested,
                "spots_per_week": spots_per_week,
                "spot_length_seconds": spot_length_seconds,
                "gross_rate_cents": gross_rate_cents,
                "guaranteed_rating": guaranteed_rating,
            }
        ],
        flight_start_date=flight_start_date,
        flight_end_date=flight_end_date,
    )
    return advertiser, order, lines[0], list_line_spots(lines[0]["id"])


def setup_preempted_spot(**scenario_kwargs):
    """A scheduled spot preempted while its log day is still DRAFT.
    Returns the scenario dict plus the preempted spot and its make-good when
    offered (offer=True)."""
    offer = scenario_kwargs.pop("offer", False)
    scenario_kwargs.setdefault("log_date", scenario_kwargs.get("air_date", "2026-08-03"))
    ctx = setup_scheduled_scenario(**scenario_kwargs)
    preempted = preempt_spot(ctx["placed"][0]["id"], "OVERSOLD")
    ctx["preempted"] = preempted
    ctx["make_good"] = offer_make_good(preempted["id"]) if offer else None
    return ctx
