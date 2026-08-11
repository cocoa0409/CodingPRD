"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch against a fresh server using
only PRD-declared endpoints. Setup calls use get_success_data() so a failed
precondition surfaces as a clear "Setup step failed" error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_STARTUP_DEFAULT
from .factories import (
    create_booth_assignment_payload,
    create_build_task_payload,
    create_cast_contract_payload,
    create_conduct_case_payload,
    create_faire_day_payload,
    create_food_permit_payload,
    create_performer_payload,
    create_rehearsal_slot_payload,
    create_season_payload,
    create_ticket_order_payload,
    create_vendor_application_payload,
    create_vendor_payload,
    create_volunteer_shift_payload,
    decide_application_payload,
)
from .test_users import (
    TEST_USERS,
    make_guest_headers,
    make_performer_headers,
    make_vendor_headers,
    make_volunteer_headers,
)

OPERATOR = TEST_USERS["operator_headers"]
DIRECTOR = TEST_USERS["cast_director_headers"]
VENDOR_CO = TEST_USERS["vendor_coordinator_headers"]
GATE = TEST_USERS["gate_agent_headers"]
VOLUNTEER_CO = TEST_USERS["volunteer_coordinator_headers"]
ANY = TEST_USERS["any_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock + primitive creators
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = CLOCK_STARTUP_DEFAULT):
    """Set the server logical clock (FaireOperator-only test-driving endpoint)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, OPERATOR))


def make_season(**overrides):
    """Create a season (starts PLANNING, posture BLOCKED, version 1)."""
    return get_success_data(api_client.create_season(create_season_payload(**overrides), OPERATOR))


def make_faire_day(season_id: str, date: str = "2026-06-06T00:00:00Z"):
    """Schedule a faire day (starts SCHEDULED)."""
    return get_success_data(
        api_client.create_faire_day(create_faire_day_payload(season_id, date), OPERATOR)
    )


def make_vendor(business_name: str = "Test Vendor", category: str = "ARTISAN"):
    return get_success_data(
        api_client.create_vendor(
            create_vendor_payload(business_name=business_name, category=category), VENDOR_CO
        )
    )


def make_application(season_id: str, vendor_id: str, booth_size_sqft: int = 64,
                     requested_location_tier: str = "MEADOW"):
    """File a jury application as the owning vendor (starts JURY_REVIEW)."""
    return get_success_data(
        api_client.create_vendor_application(
            create_vendor_application_payload(
                season_id,
                booth_size_sqft=booth_size_sqft,
                requested_location_tier=requested_location_tier,
            ),
            make_vendor_headers(vendor_id),
        )
    )


def decide_application(application_id: str, outcome: str,
                       craft_score: float = 8, authenticity_score: float = 8,
                       safety_score: float = 8):
    return get_success_data(
        api_client.decide_application(
            application_id,
            decide_application_payload(
                outcome,
                craft_score=craft_score,
                authenticity_score=authenticity_score,
                safety_score=safety_score,
            ),
            VENDOR_CO,
        )
    )


def make_performer(stage_name: str = "Test Trouper", act_type: str = "MUSIC",
                   base_day_rate_cents: int = 10000):
    return get_success_data(
        api_client.create_performer(
            create_performer_payload(
                stage_name=stage_name,
                act_type=act_type,
                base_day_rate_cents=base_day_rate_cents,
            ),
            DIRECTOR,
        )
    )


def make_contract(season_id: str, performer_id: str, **overrides):
    """Create a cast contract (starts DRAFT)."""
    return get_success_data(
        api_client.create_cast_contract(
            create_cast_contract_payload(season_id, performer_id, **overrides), DIRECTOR
        )
    )


def make_slot(contract_id: str, stage_name: str = "MAIN",
              start_time: str = "2026-05-10T09:00:00Z",
              end_time: str = "2026-05-10T10:00:00Z"):
    return get_success_data(
        api_client.create_rehearsal_slot(
            create_rehearsal_slot_payload(contract_id, stage_name, start_time, end_time),
            DIRECTOR,
        )
    )


def make_booth(application_id: str, booth_site: str = "A-01",
               residency_start_date: str = "2026-06-06T00:00:00Z",
               residency_end_date: str = "2026-06-20T00:00:00Z"):
    """Reserve a booth for a JURIED_IN application (starts RESERVED)."""
    return get_success_data(
        api_client.create_booth_assignment(
            create_booth_assignment_payload(
                application_id, booth_site, residency_start_date, residency_end_date
            ),
            VENDOR_CO,
        )
    )


def make_food_permit(application_id: str, vendor_id: str):
    """Apply for a health permit as the owning vendor (starts APPLIED)."""
    return get_success_data(
        api_client.create_food_permit(
            create_food_permit_payload(application_id), make_vendor_headers(vendor_id)
        )
    )


def make_shift(season_id: str, faire_day_id: str, volunteer_handle: str,
               role: str = "GATE", start_time: str = "2026-06-06T08:00:00Z",
               end_time: str = "2026-06-06T12:00:00Z"):
    """Sign up a volunteer shift as the volunteer (starts SIGNED_UP)."""
    return get_success_data(
        api_client.create_volunteer_shift(
            create_volunteer_shift_payload(
                season_id, faire_day_id, role=role,
                start_time=start_time, end_time=end_time,
            ),
            make_volunteer_headers(volunteer_handle),
        )
    )


def make_build_task(season_id: str, name: str = "Test task", phase: str = "BUILD",
                    depends_on_task_ids=None):
    payload = create_build_task_payload(season_id, phase=phase, name=name)
    if depends_on_task_ids is not None:
        payload["depends_on_task_ids"] = depends_on_task_ids
    return get_success_data(api_client.create_build_task(payload, OPERATOR))


def make_conduct_case(season_id: str, category: str = "BEHAVIOR",
                      subject_description: str = "Test violation", **links):
    """File a conduct case as a gate agent (starts REPORTED)."""
    return get_success_data(
        api_client.create_conduct_case(
            create_conduct_case_payload(
                season_id, category=category,
                subject_description=subject_description, **links,
            ),
            GATE,
        )
    )


def make_order(season_id: str, buyer_email: str, order_type: str = "DAY",
               quantity: int = 1, unit_price_cents: int = 3000,
               faire_day_id: str = None):
    """Place a ticket order as the buyer guest (starts UNPAID/UNREDEEMED)."""
    payload = create_ticket_order_payload(
        season_id, order_type=order_type, quantity=quantity,
        unit_price_cents=unit_price_cents,
    )
    if faire_day_id is not None:
        payload["faire_day_id"] = faire_day_id
    return get_success_data(
        api_client.create_ticket_order(payload, make_guest_headers(buyer_email))
    )


# ---------------------------------------------------------------------------
# Tier 1: state progression
# ---------------------------------------------------------------------------

def make_build_season(**overrides):
    """Season walked PLANNING -> BUILD. (Requires no PENDING BUILD-phase tasks.)"""
    season = make_season(**overrides)
    return get_success_data(api_client.begin_build(season["id"], OPERATOR))


def make_open_season(**overrides):
    """Season walked PLANNING -> BUILD -> OPEN (posture READY: no BUILD tasks,
    no unpermitted food vendors, volunteer threshold met by default 0)."""
    season = make_build_season(**overrides)
    return get_success_data(api_client.open_season(season["id"], OPERATOR))


def make_open_sales_day(season_id: str, date: str = "2026-06-06T00:00:00Z"):
    """Faire day walked SCHEDULED -> OPEN_FOR_SALES."""
    day = make_faire_day(season_id, date)
    return get_success_data(api_client.open_sales(day["id"], OPERATOR))


def make_operating_day(season_id: str, date: str = "2026-06-06T00:00:00Z",
                       clock_morning: str = None):
    """Faire day walked to OPERATING: opens gates on the day's own calendar date.
    The season must already be OPEN. Sets the clock to the day's morning."""
    day = make_open_sales_day(season_id, date)
    set_clock(clock_morning or date.replace("T00:00:00Z", "T07:00:00Z"))
    return get_success_data(api_client.open_gates(day["id"], OPERATOR))


def make_accepted_contract(season_id: str, performer_id: str = None,
                           performer_name: str = "Test Trouper", **contract_overrides):
    """Performer + contract walked DRAFT -> OFFERED -> ACCEPTED.
    Returns (performer, contract)."""
    if performer_id is not None:
        performer = get_success_data(api_client.get_performer(performer_id, ANY))
    else:
        performer = make_performer(stage_name=performer_name)
    contract = make_contract(season_id, performer["id"], **contract_overrides)
    get_success_data(api_client.offer_contract(contract["id"], {}, DIRECTOR))
    accepted = get_success_data(
        api_client.accept_contract(contract["id"], make_performer_headers(performer["id"]))
    )
    return performer, accepted


def make_juried_vendor(season_id: str, business_name: str = "Test Vendor",
                       category: str = "ARTISAN", booth_size_sqft: int = 64,
                       requested_location_tier: str = "MEADOW",
                       outcome: str = "JURIED_IN", scores=(8, 8, 8)):
    """Vendor + application decided to `outcome`. Returns (vendor, application)."""
    vendor = make_vendor(business_name, category)
    application = make_application(
        season_id, vendor["id"], booth_size_sqft, requested_location_tier
    )
    decided = decide_application(application["id"], outcome, *scores)
    return vendor, decided


def make_paid_order(season_id: str, buyer_email: str, order_type: str = "DAY",
                    quantity: int = 1, unit_price_cents: int = 3000,
                    faire_day_id: str = None):
    """Order walked UNPAID -> PAID (mints `quantity` VALID tickets)."""
    order = make_order(
        season_id, buyer_email, order_type, quantity, unit_price_cents, faire_day_id
    )
    return get_success_data(api_client.pay_order(order["id"], make_guest_headers(buyer_email)))


def tickets_of_order(order_id: str):
    """All tickets minted under an order, creation-ascending."""
    data, _meta = _list(api_client.list_tickets(ANY, params={"order_id": order_id}))
    return data


def rain_checks_of_ticket(ticket_id: str):
    data, _meta = _list(api_client.list_rain_checks(ANY, params={"ticket_id": ticket_id}))
    return data


def rain_checks_of_day(day_id: str):
    data, _meta = _list(api_client.list_rain_checks(ANY, params={"issued_for_day_id": day_id}))
    return data


def _list(response):
    """Lenient list helper returning (data, meta)."""
    body = response.json()
    if not (200 <= response.status_code < 300):
        raise AssertionError(f"Setup list call failed: HTTP {response.status_code}: {response.text}")
    return body["data"], body["meta"]


def get_season(season_id: str):
    return get_success_data(api_client.get_season(season_id, ANY))


def get_day(day_id: str):
    return get_success_data(api_client.get_faire_day(day_id, ANY))


def get_order(order_id: str):
    return get_success_data(api_client.get_ticket_order(order_id, ANY))


def get_booth(booth_id: str):
    return get_success_data(api_client.get_booth_assignment(booth_id, ANY))


def get_contract(contract_id: str):
    return get_success_data(api_client.get_cast_contract(contract_id, ANY))


# ---------------------------------------------------------------------------
# Tier 2: composite scenarios shared by several tests
# ---------------------------------------------------------------------------

def setup_season_build_with_sales_day(volunteer_min_hours: float = 0,
                                      daily_capacity: int = 500,
                                      group_min_size: int = 10,
                                      date: str = "2026-06-06T00:00:00Z",
                                      **season_overrides):
    """Season in BUILD with one faire day OPEN_FOR_SALES.
    Returns (season, day)."""
    season = make_build_season(
        volunteer_min_hours=volunteer_min_hours,
        daily_capacity=daily_capacity,
        group_min_size=group_min_size,
        **season_overrides,
    )
    day = make_faire_day(season["id"], date)
    day = get_success_data(api_client.open_sales(day["id"], OPERATOR))
    return season, day


def setup_paid_day_order(quantity: int = 1, unit_price_cents: int = 3000,
                         buyer_email: str = "guest@example.com",
                         order_type: str = "DAY", **season_overrides):
    """BUILD season + OPEN_FOR_SALES day + one PAID order.
    Returns (season, day, order)."""
    season, day = setup_season_build_with_sales_day(**season_overrides)
    order = make_paid_order(
        season["id"], buyer_email, order_type, quantity, unit_price_cents, day["id"]
    )
    return season, day, order


def setup_issued_rain_check(quantity: int = 1, buyer_email: str = "rc-buyer@example.com",
                            target_date: str = "2026-06-13T00:00:00Z",
                            **season_overrides):
    """PAID DAY order whose day is then weather-cancelled: tickets RAINCHECKED,
    one ISSUED rain check per ticket. A second day stands OPEN_FOR_SALES as a
    redemption target. Returns (season, source_day, target_day, order, checks)."""
    season = make_build_season(**season_overrides)
    source_day = make_faire_day(season["id"], "2026-06-06T00:00:00Z")
    target_day = make_faire_day(season["id"], target_date)
    get_success_data(api_client.open_sales(source_day["id"], OPERATOR))
    get_success_data(api_client.open_sales(target_day["id"], OPERATOR))
    order = make_paid_order(
        season["id"], buyer_email, "DAY", quantity, 3000, source_day["id"]
    )
    get_success_data(api_client.cancel_weather(source_day["id"], OPERATOR))
    checks = rain_checks_of_day(source_day["id"])
    return season, get_day(source_day["id"]), get_day(target_day["id"]), order, checks


def setup_confirmed_hours(season_id: str, faire_day_id: str, specs):
    """Create + confirm volunteer shifts. `specs` is a list of
    (handle, role, start_time, end_time) tuples. Returns the confirmed shifts."""
    confirmed = []
    for handle, role, start, end in specs:
        shift = make_shift(season_id, faire_day_id, handle, role, start, end)
        confirmed.append(get_success_data(api_client.confirm_shift(shift["id"], VOLUNTEER_CO)))
    return confirmed


def setup_food_booth_confirmed(booth_site: str = "F-12", category: str = "FOOD",
                               booth_size_sqft: int = 80,
                               requested_location_tier: str = "STANDARD",
                               residency_end_date: str = "2026-06-21T00:00:00Z",
                               **season_overrides):
    """Season + JURIED_IN food-category vendor + ISSUED permit + CONFIRMED booth.
    Returns dict(season, vendor, application, permit, booth)."""
    season = make_season(**season_overrides)
    vendor, application = make_juried_vendor(
        season["id"], category=category, booth_size_sqft=booth_size_sqft,
        requested_location_tier=requested_location_tier,
    )
    permit = make_food_permit(application["id"], vendor["id"])
    permit = get_success_data(
        api_client.inspect_permit(permit["id"], {"outcome": "PASSED"}, VENDOR_CO)
    )
    booth = make_booth(
        application["id"], booth_site,
        "2026-06-06T00:00:00Z", residency_end_date,
    )
    booth = get_success_data(
        api_client.confirm_booth(booth["id"], make_vendor_headers(vendor["id"]))
    )
    return {
        "season": season, "vendor": vendor, "application": application,
        "permit": permit, "booth": booth,
    }


# ---------------------------------------------------------------------------
# Tier 3/4: heavy lifecycle scenarios for the deep calculation/cascade tests
# ---------------------------------------------------------------------------

def setup_booth_fee_scenario():
    """Full season arc for the booth-fee dual-variant scenario.

    Season 2026-06-06..2026-06-20 (2 weeks), PRIME 100 sqft booth at A-01 with
    residency [06-06, 06-20) CONFIRMED; days 06-07/06-13/06-14 weather-cancelled
    inside the residency; days 06-06 and 06-20 completed; season in STRIKE.

    Expected arithmetic: provisional 24000 (100*120*2); daily credit
    round(24000*0.25/14) = 429, three days -> 1287.

    Returns dict(season_id, booth_id, day_ids).
    """
    set_clock()
    season = make_season(
        name="Summer Revel", volunteer_min_hours=8,
    )
    s_id = season["id"]
    days = {
        d: make_faire_day(s_id, f"2026-06-{d:02d}T00:00:00Z")
        for d in (6, 7, 13, 14, 20)
    }
    vendor, application = make_juried_vendor(
        s_id, business_name="Ironwood Carvings", category="ARTISAN",
        booth_size_sqft=100, requested_location_tier="PRIME",
    )
    booth = make_booth(application["id"], "A-01")
    get_success_data(api_client.confirm_booth(booth["id"], make_vendor_headers(vendor["id"])))
    # Two 4h confirmed shifts on opening day: 8.0 hours meets the threshold.
    shifts = setup_confirmed_hours(s_id, days[6]["id"], [
        ("vol-anna", "GATE", "2026-06-06T08:00:00Z", "2026-06-06T12:00:00Z"),
        ("vol-ben", "TAVERN", "2026-06-06T08:00:00Z", "2026-06-06T12:00:00Z"),
    ])
    get_success_data(api_client.begin_build(s_id, OPERATOR))
    get_success_data(api_client.open_season(s_id, OPERATOR))
    # Opening day runs to completion.
    set_clock("2026-06-06T07:00:00Z")
    get_success_data(api_client.open_sales(days[6]["id"], OPERATOR))
    get_success_data(api_client.open_gates(days[6]["id"], OPERATOR))
    for shift in shifts:
        get_success_data(
            api_client.close_out_shift(shift["id"], {"outcome": "WORKED"}, VOLUNTEER_CO)
        )
    get_success_data(api_client.complete_day(days[6]["id"], OPERATOR))
    # Three in-residency days are weather-cancelled.
    for d in (7, 13, 14):
        get_success_data(api_client.open_sales(days[d]["id"], OPERATOR))
        get_success_data(api_client.cancel_weather(days[d]["id"], OPERATOR))
    # Closing day runs to completion.
    get_success_data(api_client.open_sales(days[20]["id"], OPERATOR))
    set_clock("2026-06-20T07:00:00Z")
    get_success_data(api_client.open_gates(days[20]["id"], OPERATOR))
    get_success_data(api_client.complete_day(days[20]["id"], OPERATOR))
    get_success_data(api_client.begin_strike(s_id, OPERATOR))
    return {
        "season_id": s_id,
        "booth_id": booth["id"],
        "day_ids": {d: day["id"] for d, day in days.items()},
    }


def setup_all_rain_cast_scenario():
    """Season with a PERFORMING contract whose five faire days are all
    weather-cancelled: accrual 5 * round(20000 * 0.5) = 50000.

    Returns dict(season_id, performer_id, contract_id).
    """
    set_clock()
    season = make_season(name="All-Rain Revel", volunteer_min_hours=0)
    s_id = season["id"]
    days = [
        make_faire_day(s_id, f"2026-06-{d:02d}T00:00:00Z")
        for d in (6, 7, 13, 14, 20)
    ]
    performer, contract = make_accepted_contract(
        s_id,
        performer_name="Sir Cedric",
        offered_day_rate_cents=20000,
        guaranteed_days=3,
        weather_pay_pct=0.5,
        required_rehearsal_hours=4,
    )
    # Two 2h attended slots: 4.0 of 4 required hours, buffered 15 minutes apart.
    r1 = make_slot(contract["id"], "MAIN", "2026-05-10T09:00:00Z", "2026-05-10T11:00:00Z")
    r2 = make_slot(contract["id"], "MAIN", "2026-05-10T11:15:00Z", "2026-05-10T13:15:00Z")
    for r in (r1, r2):
        get_success_data(api_client.record_attendance(r["id"], {"outcome": "ATTENDED"}, DIRECTOR))
    get_success_data(api_client.begin_build(s_id, OPERATOR))
    get_success_data(api_client.open_season(s_id, OPERATOR))
    for day in days:
        get_success_data(api_client.open_sales(day["id"], OPERATOR))
        get_success_data(api_client.cancel_weather(day["id"], OPERATOR))
    return {"season_id": s_id, "performer_id": performer["id"], "contract_id": contract["id"]}


def setup_weather_cascade_scenario():
    """Season BUILD, volunteer_min_hours 8, day 06-07 OPEN_FOR_SALES with two
    confirmed 4h shifts (8.0 hours -> posture READY). Returns dict."""
    set_clock()
    season = make_season(name="Cascade Revel", volunteer_min_hours=8)
    s_id = season["id"]
    day = make_faire_day(s_id, "2026-06-07T00:00:00Z")
    shifts = setup_confirmed_hours(s_id, day["id"], [
        ("vol-cara", "GATE", "2026-06-07T08:00:00Z", "2026-06-07T12:00:00Z"),
        ("vol-dan", "PARKING", "2026-06-07T08:00:00Z", "2026-06-07T12:00:00Z"),
    ])
    get_success_data(api_client.begin_build(s_id, OPERATOR))
    get_success_data(api_client.open_sales(day["id"], OPERATOR))
    return {
        "season_id": s_id,
        "day_id": day["id"],
        "shift_ids": [s["id"] for s in shifts],
    }


def setup_conduct_revoke_scenario():
    """FOOD vendor JURIED_IN + permit ISSUED + booth CONFIRMED, season BUILD,
    posture READY, and a REPORTED VENDOR_CONDUCT case linked to the permit."""
    ctx = setup_food_booth_confirmed()
    get_success_data(api_client.begin_build(ctx["season"]["id"], OPERATOR))
    case = make_conduct_case(
        ctx["season"]["id"],
        category="VENDOR_CONDUCT",
        subject_description="Unlicensed open-flame cooking observed",
        linked_permit_id=ctx["permit"]["id"],
    )
    ctx["case"] = case
    return ctx


def setup_shortfall_scenario():
    """Contract (rate 20000, guaranteed 2 days, weather 0.5, required 4h) with
    only 2h attended: stays REHEARSING through opening. Day 06-06 completes with
    no accrual; day 06-07 weather-cancels, accruing 10000 at the weather rate.
    Season ends in STRIKE. Returns dict(season_id, contract_id)."""
    set_clock()
    season = make_season(name="Shortfall Revel", volunteer_min_hours=0)
    s_id = season["id"]
    d1 = make_faire_day(s_id, "2026-06-06T00:00:00Z")
    d2 = make_faire_day(s_id, "2026-06-07T00:00:00Z")
    performer, contract = make_accepted_contract(
        s_id,
        performer_name="Penny Dreadful",
        offered_day_rate_cents=20000,
        guaranteed_days=2,
        weather_pay_pct=0.5,
        required_rehearsal_hours=4,
    )
    slot = make_slot(contract["id"], "MAIN", "2026-05-10T09:00:00Z", "2026-05-10T11:00:00Z")
    get_success_data(api_client.record_attendance(slot["id"], {"outcome": "ATTENDED"}, DIRECTOR))
    get_success_data(api_client.begin_build(s_id, OPERATOR))
    get_success_data(api_client.open_season(s_id, OPERATOR))
    get_success_data(api_client.open_sales(d1["id"], OPERATOR))
    set_clock("2026-06-06T07:00:00Z")
    get_success_data(api_client.open_gates(d1["id"], OPERATOR))
    get_success_data(api_client.complete_day(d1["id"], OPERATOR))
    get_success_data(api_client.open_sales(d2["id"], OPERATOR))
    get_success_data(api_client.cancel_weather(d2["id"], OPERATOR))
    get_success_data(api_client.begin_strike(s_id, OPERATOR))
    return {"season_id": s_id, "contract_id": contract["id"]}


def setup_group_order_paid(quantity: int = 10, unit_price_cents: int = 3000,
                           buyer_email: str = "g-ref@example.com",
                           group_min_size: int = 10):
    """BUILD season, OPEN_FOR_SALES day, one PAID GROUP order.
    Returns (season, day, order)."""
    return setup_paid_day_order(
        quantity=quantity, unit_price_cents=unit_price_cents,
        buyer_email=buyer_email, order_type="GROUP",
        group_min_size=group_min_size,
    )


def setup_conservation_scenario():
    """Two PAID DAY orders on 06-06 (qty 3 + qty 2): outstanding_admissions 5.
    Day 06-13 stands OPEN_FOR_SALES as a rain-check redemption target.
    Returns dict(season_id, day1_id, day2_id, order_a, order_b)."""
    set_clock()
    season, day1 = setup_season_build_with_sales_day()
    day2 = make_faire_day(season["id"], "2026-06-13T00:00:00Z")
    get_success_data(api_client.open_sales(day2["id"], OPERATOR))
    order_a = make_paid_order(season["id"], "ga@example.com", "DAY", 3, 3000, day1["id"])
    order_b = make_paid_order(season["id"], "gb@example.com", "DAY", 2, 3000, day1["id"])
    return {
        "season_id": season["id"],
        "day1_id": day1["id"],
        "day2_id": day2["id"],
        "order_a": order_a,
        "order_b": order_b,
    }


def setup_priority_raincheck_scenario():
    """Capacity-1 season. Day 06-06 sold one DAY ticket, then weather-cancelled
    (one ISSUED rain check, redeem_by 2026-07-04). Day 06-20 sold out (1 PAID).
    Clock parked at 2026-05-01. Returns dict with the moving parts."""
    set_clock()
    season = make_build_season(name="Priority Revel B", daily_capacity=1)
    s_id = season["id"]
    d1 = make_faire_day(s_id, "2026-06-06T00:00:00Z")
    d2 = make_faire_day(s_id, "2026-06-20T00:00:00Z")
    get_success_data(api_client.open_sales(d1["id"], OPERATOR))
    get_success_data(api_client.open_sales(d2["id"], OPERATOR))
    order1 = make_paid_order(s_id, "g-one@example.com", "DAY", 1, 3000, d1["id"])
    get_success_data(api_client.cancel_weather(d1["id"], OPERATOR))
    ticket1 = tickets_of_order(order1["id"])[0]
    check = rain_checks_of_ticket(ticket1["id"])[0]
    order2 = make_paid_order(s_id, "g-two@example.com", "DAY", 1, 3000, d2["id"])
    return {
        "season_id": s_id,
        "day1_id": d1["id"],
        "day2_id": d2["id"],
        "order1": order1,
        "order2": order2,
        "ticket1": ticket1,
        "check": check,
    }
