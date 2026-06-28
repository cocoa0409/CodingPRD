"""Cross-entity gates (weather, insurance), interval / window overlap arithmetic, and the
PRD-ordered precedence pairs on schedule and confirm. Translates Difficulty rules
cross_entity_state_dependency, resource_temporal_overlap, and
priority_pair_validation_conflict, plus the validations corner instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    setup_accepted_quote, setup_scheduled_visit,
    create_clear_weather_window, create_technician, create_visit, schedule_visit,
    reserve_crew, confirm_crew, set_clock, create_customer, create_route, create_property,
    create_draft_quote, add_line_item, send_quote, accept_quote,
    create_weather_window_payload, schedule_visit_payload, create_assignment_payload,
    create_route_payload, create_property_payload, create_customer_payload, create_quote_payload,
    create_line_item_payload, create_visit_payload,
    TEST_USERS,
)

DISP = TEST_USERS["dispatcher_headers"]


# ─────────────────────────────────────────────────────────────────────────
# Difficulty / cross_entity_state_dependency
# ─────────────────────────────────────────────────────────────────────────

def test_schedule_requires_clear_weather_window(api):
    """PRD §3.5: "There must be a weather window on the visit's route whose `condition` is
    `CLEAR` and whose closed interval covers the visit's `scheduled_date`; absent such a
    window, scheduling fails with `ERR_NO_CLEAR_WEATHER`."

    Design: Difficulty/cross_entity_state_dependency/visit_schedule_requires_clear_weatherwindow
    """
    set_clock()
    ctx = setup_accepted_quote(
        property_overrides={"stories": 1, "siding_sqft": 1000},
        line_items=[("SIDING", "HOUSE_WASH", 1000)],
        customer_overrides={"credit_limit_cents": 100000000},
    )
    # Only a BLOCKED window (wind 40 >= MAX_WIND 35) covers the date.
    ww = validate_success(api.create_weather_window(
        create_weather_window_payload(ctx["route"]["id"], "2026-05-01T00:00:00Z",
                                      "2026-05-01T23:59:59Z", 40), DISP), 201)
    assert ww["condition"] == "BLOCKED", ww["condition"]
    visit = create_visit(ctx["property"]["id"], ctx["quote"]["id"], scheduled_date="2026-05-01")
    resp = api.schedule_visit(visit["id"], schedule_visit_payload(visit["version"]), DISP)
    validate_error(resp, ApiErrorId.ERR_NO_CLEAR_WEATHER.value)
    assert get_success_data(api.get_visit(visit["id"], DISP))["status"] == "REQUESTED"


def test_confirm_requires_active_insurance(api):
    """PRD §3.6: "Because insurance can lapse between reservation and confirmation, the
    technician's assignability is re-checked at confirm time: the technician's
    `insurance_status` must be `ACTIVE` and the technician's `ladder_cert_max_stories` must
    still be at least the property's `stories`. If either fails, confirmation is rejected with
    `ERR_TECH_NOT_ASSIGNABLE`."

    Design: Difficulty/cross_entity_state_dependency/crew_confirm_requires_assignable_technician
    """
    set_clock()
    ctx = setup_accepted_quote(
        property_overrides={"stories": 2, "roof_sqft": 2000},
        line_items=[("ROOF", "ROOF_SOFT_WASH", 2000)],
        route_overrides={"travel_buffer_minutes": 0},
    )
    create_clear_weather_window(ctx["route"]["id"])
    # Tech ladder cert 3 (covers 2 stories) but insurance EXPIRED: reserve OK, confirm fails.
    tech = create_technician(ladder_cert_max_stories=3, insurance_status="EXPIRED")
    visit = create_visit(ctx["property"]["id"], ctx["quote"]["id"], scheduled_date="2026-05-01")
    visit = schedule_visit(visit["id"], visit["version"])
    asg = reserve_crew(visit["id"], tech["id"], "2026-05-01T14:00:00Z")
    validate_error(api.confirm_assignment(asg["id"], DISP), ApiErrorId.ERR_TECH_NOT_ASSIGNABLE.value)
    assert get_success_data(api.get_assignment(asg["id"], DISP))["status"] == "RESERVED"


# ─────────────────────────────────────────────────────────────────────────
# Difficulty / resource_temporal_overlap
# ─────────────────────────────────────────────────────────────────────────

def test_technician_interval_overlap_half_open_with_travel_buffer(api):
    """PRD §3.6: "the new assignment's interval must not overlap any of that technician's
    existing `RESERVED` or `CONFIRMED` intervals. For this overlap test the half-open interval
    is padded on both sides by the route's `travel_buffer_minutes`, so that setup and travel
    time is respected; an overlap is rejected with `ERR_TECH_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/technician_interval_overlap_half_open_with_travel_buffer
    """
    set_clock()
    cust = create_customer(credit_limit_cents=100000000)
    route = create_route(travel_buffer_minutes=30)
    create_clear_weather_window(route["id"])
    tech = create_technician(ladder_cert_max_stories=3, insurance_status="ACTIVE")

    def accepted_quote_for(prop):
        q = create_draft_quote(prop["id"], prop["version"])
        add_line_item(q["id"], "ROOF", "ROOF_SOFT_WASH", 2000)
        send_quote(q["id"])
        accept_quote(q["id"], cust["id"])
        return q

    propA = create_property(cust["id"], route["id"], stories=2, roof_sqft=2000)
    qA = accepted_quote_for(propA)
    propB = create_property(cust["id"], route["id"], stories=2, roof_sqft=2000)
    qB = accepted_quote_for(propB)

    vA = create_visit(propA["id"], qA["id"], scheduled_date="2026-05-01", duration_minutes=120)
    vA = schedule_visit(vA["id"], vA["version"])
    confirm_crew(reserve_crew(vA["id"], tech["id"], "2026-05-01T14:00:00Z")["id"])  # 14:00-16:00

    vB = create_visit(propB["id"], qB["id"], scheduled_date="2026-05-01", duration_minutes=120)
    vB = schedule_visit(vB["id"], vB["version"])
    # Start 16:15 is within 16:00 + 30min buffer -> collision.
    resp = api.create_assignment(
        create_assignment_payload(vB["id"], tech["id"], "2026-05-01T16:15:00Z"), DISP)
    validate_error(resp, ApiErrorId.ERR_TECH_DOUBLE_BOOKED.value)


def test_technician_interval_no_collision_past_buffer(api):
    """PRD §3.6: "the new assignment's interval must not overlap any of that technician's
    existing `RESERVED` or `CONFIRMED` intervals. For this overlap test the half-open interval
    is padded on both sides by the route's `travel_buffer_minutes`".

    Design: Difficulty/resource_temporal_overlap/technician_interval_overlap_half_open_with_travel_buffer
    """
    set_clock()
    cust = create_customer(credit_limit_cents=100000000)
    route = create_route(travel_buffer_minutes=30)
    create_clear_weather_window(route["id"])
    tech = create_technician(ladder_cert_max_stories=3, insurance_status="ACTIVE")

    def accepted_quote_for(prop):
        q = create_draft_quote(prop["id"], prop["version"])
        add_line_item(q["id"], "ROOF", "ROOF_SOFT_WASH", 2000)
        send_quote(q["id"])
        accept_quote(q["id"], cust["id"])
        return q

    propA = create_property(cust["id"], route["id"], stories=2, roof_sqft=2000)
    qA = accepted_quote_for(propA)
    propB = create_property(cust["id"], route["id"], stories=2, roof_sqft=2000)
    qB = accepted_quote_for(propB)

    vA = create_visit(propA["id"], qA["id"], scheduled_date="2026-05-01", duration_minutes=120)
    vA = schedule_visit(vA["id"], vA["version"])
    confirm_crew(reserve_crew(vA["id"], tech["id"], "2026-05-01T14:00:00Z")["id"])  # 14:00-16:00

    vB = create_visit(propB["id"], qB["id"], scheduled_date="2026-05-01", duration_minutes=120)
    vB = schedule_visit(vB["id"], vB["version"])
    # Start exactly 16:30 == 16:00 + 30min buffer (half-open) -> no collision.
    asg = validate_success(api.create_assignment(
        create_assignment_payload(vB["id"], tech["id"], "2026-05-01T16:30:00Z"), DISP), 201)
    assert asg["status"] == "RESERVED", asg["status"]


def test_weather_window_overlap_closed_interval_touching_endpoints(api):
    """PRD §3.4: "On creation, the new window must not overlap any existing window on the same
    route; because the interval is closed, two windows that merely touch at an endpoint are
    considered to overlap and collide. An overlapping create is rejected with
    `ERR_WEATHER_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/weather_window_overlap_closed_interval_touching_endpoints_collide
    """
    route = create_route()
    validate_success(api.create_weather_window(
        create_weather_window_payload(route["id"], "2026-05-01T10:00:00Z",
                                      "2026-05-01T12:00:00Z", 5), DISP), 201)
    # New window starting exactly at the closed end 12:00 touches -> overlap.
    resp = api.create_weather_window(
        create_weather_window_payload(route["id"], "2026-05-01T12:00:00Z",
                                      "2026-05-01T14:00:00Z", 5), DISP)
    validate_error(resp, ApiErrorId.ERR_WEATHER_WINDOW_OVERLAP.value)


def test_weather_window_after_closed_end_accepted(api):
    """PRD §3.4: "A weather window covers a closed forecast interval that includes both its
    start and end instants."

    Design: Difficulty/resource_temporal_overlap/weather_window_overlap_closed_interval_touching_endpoints_collide
    """
    route = create_route()
    validate_success(api.create_weather_window(
        create_weather_window_payload(route["id"], "2026-05-01T10:00:00Z",
                                      "2026-05-01T12:00:00Z", 5), DISP), 201)
    # One second past the closed end -> no overlap.
    ok = validate_success(api.create_weather_window(
        create_weather_window_payload(route["id"], "2026-05-01T12:00:01Z",
                                      "2026-05-01T14:00:00Z", 5), DISP), 201)
    assert ok["condition"] == "CLEAR", ok["condition"]


# ─────────────────────────────────────────────────────────────────────────
# Difficulty / priority_pair_validation_conflict
# ─────────────────────────────────────────────────────────────────────────

def test_confirm_state_check_precedes_insurance_safety_check(api):
    """PRD §2.7: "then the legality of the requested state transition (`ERR_INVALID_STATE`);
    and finally the domain-specific business rules described throughout §3. A check earlier in
    this order always takes precedence over a later one."
    PRD §3.6: "Confirming an assignment moves it from `RESERVED` to `CONFIRMED`, legal only
    from `RESERVED` (otherwise `ERR_INVALID_STATE`)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_confirm_invalid_state_vs_tech_not_assignable
    """
    set_clock()
    ctx = setup_accepted_quote(
        property_overrides={"stories": 2, "roof_sqft": 2000},
        line_items=[("ROOF", "ROOF_SOFT_WASH", 2000)],
        route_overrides={"travel_buffer_minutes": 0},
    )
    create_clear_weather_window(ctx["route"]["id"])
    tech = create_technician(ladder_cert_max_stories=3, insurance_status="EXPIRED")
    visit = create_visit(ctx["property"]["id"], ctx["quote"]["id"], scheduled_date="2026-05-01")
    visit = schedule_visit(visit["id"], visit["version"])
    asg = reserve_crew(visit["id"], tech["id"], "2026-05-01T14:00:00Z")
    # Release first so the assignment is no longer RESERVED; tech is also EXPIRED.
    validate_success(api.release_assignment(asg["id"], DISP), 200)
    # Both a state violation (not RESERVED) and a safety violation (EXPIRED) are live;
    # state precedes business rules -> ERR_INVALID_STATE.
    validate_error(api.confirm_assignment(asg["id"], DISP), ApiErrorId.ERR_INVALID_STATE.value)


def test_schedule_weather_check_precedes_credit_check(api):
    """PRD §3.5: "There must be a weather window on the visit's route whose `condition` is
    `CLEAR` and whose closed interval covers the visit's `scheduled_date`; absent such a
    window, scheduling fails with `ERR_NO_CLEAR_WEATHER`. Finally, the credit gate applies: if
    the owning customer's `outstanding_balance_cents` plus this job's provisional amount would
    exceed the customer's `credit_limit_cents`, the schedule is rejected with
    `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/weather_beats_fiscal_on_schedule_no_clear_weather_vs_credit
    """
    set_clock()
    # credit_limit 0 (any positive provisional trips credit) AND only a BLOCKED window covers
    # the date. Weather is checked before credit ("Finally, the credit gate applies").
    ctx = setup_accepted_quote(
        property_overrides={"stories": 2, "roof_sqft": 2000},
        line_items=[("ROOF", "ROOF_SOFT_WASH", 2000)],
        customer_overrides={"credit_limit_cents": 0},
        route_overrides={"travel_buffer_minutes": 0},
    )
    validate_success(api.create_weather_window(
        create_weather_window_payload(ctx["route"]["id"], "2026-05-01T00:00:00Z",
                                      "2026-05-01T23:59:59Z", 40), DISP), 201)
    visit = create_visit(ctx["property"]["id"], ctx["quote"]["id"], scheduled_date="2026-05-01")
    resp = api.schedule_visit(visit["id"], schedule_visit_payload(visit["version"]), DISP)
    validate_error(resp, ApiErrorId.ERR_NO_CLEAR_WEATHER.value)
    assert get_success_data(api.get_visit(visit["id"], DISP))["status"] == "REQUESTED"


# ─────────────────────────────────────────────────────────────────────────
# Corner / validations
# ─────────────────────────────────────────────────────────────────────────

def test_weather_window_end_before_start_rejected(api):
    """PRD §2.8: "a weather window's `window_end_utc` must be strictly later than its
    `window_start_utc`. Any violation — a bad enum value, an out-of-range integer, a missing
    required field, or an end timestamp at or before the start timestamp — is rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/validations/window_end_before_start_returns_invalid_request
    """
    route = create_route()
    resp = api.create_weather_window(
        create_weather_window_payload(route["id"], "2026-05-01T12:00:00Z",
                                      "2026-05-01T10:00:00Z", 5), DISP)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_weather_window_blocked_at_wind_threshold(api):
    """PRD §3.4: "The window's `condition` is derived, not supplied: it is `BLOCKED` if the
    `wind_mph` is at least the maximum safe wind of 35 mph, or if `precip_flag` is true;
    otherwise it is `CLEAR`."

    Design: Corner/validations/weather_window_condition_blocked_when_wind_at_threshold
    """
    route = create_route()
    ww = validate_success(api.create_weather_window(
        create_weather_window_payload(route["id"], "2026-05-01T10:00:00Z",
                                      "2026-05-01T12:00:00Z", 35), DISP), 201)
    assert ww["condition"] == "BLOCKED", ww["condition"]


def test_visit_create_requires_accepted_quote(api):
    """PRD §3.5: "The backing quote referenced at creation must be in `ACCEPTED` status; a
    visit that references a non-accepted quote is rejected with `ERR_QUOTE_NOT_ACCEPTED`."

    Design: Corner/validations/quote_not_accepted_blocks_visit_create
    """
    cust = create_customer(credit_limit_cents=100000000)
    route = create_route()
    prop = create_property(cust["id"], route["id"], stories=1, siding_sqft=900)
    quote = create_draft_quote(prop["id"], prop["version"])
    add_line_item(quote["id"], "SIDING", "HOUSE_WASH", 900)
    send_quote(quote["id"])  # SENT, not ACCEPTED
    resp = api.create_visit(create_visit_payload(prop["id"], quote["id"], "2026-05-01"), DISP)
    validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_ACCEPTED.value)


def test_schedule_rejected_when_provisional_exceeds_credit_limit(api):
    """PRD §3.5: "the credit gate applies: if the owning customer's `outstanding_balance_cents`
    plus this job's provisional amount would exceed the customer's `credit_limit_cents`, the
    schedule is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

    Design: Corner/validations/credit_limit_exceeded_on_schedule_returns_402
    """
    set_clock()
    # credit_limit 1000; single ROOF 2000 line 2-story -> provisional 68000 > 1000; weather CLEAR.
    ctx = setup_accepted_quote(
        property_overrides={"stories": 2, "roof_sqft": 2000},
        line_items=[("ROOF", "ROOF_SOFT_WASH", 2000)],
        customer_overrides={"credit_limit_cents": 1000},
        route_overrides={"travel_buffer_minutes": 0},
    )
    create_clear_weather_window(ctx["route"]["id"])
    visit = create_visit(ctx["property"]["id"], ctx["quote"]["id"], scheduled_date="2026-05-01")
    resp = api.schedule_visit(visit["id"], schedule_visit_payload(visit["version"]), DISP)
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value)
    assert get_success_data(api.get_visit(visit["id"], DISP))["status"] == "REQUESTED"
