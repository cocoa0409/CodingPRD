"""
Two temporal resources with different interval semantics: the hall, which is a
closed padded date interval and mutually exclusive, and the selection desk, which
counts half-open windows per round against a finite capacity.
"""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    AppointmentState,
    ShowStatus,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-15T00:00:00Z"

A100 = f.booth_payload("A100", 20, 20, location_class="CORNER",
                       premium_zone="MAIN_AISLE", max_height_ft=16)
C050 = f.inline_booth_payload("C050", 10, 20)

HALL_B_TERMS = {
    "hall_code": "HALL_B",
    "hall_gross_sqft": 120000,
    "committed_net_sqft_per_year": 400,
    "attrition_allowance_pct": 10,
    "advance_order_discount_pct": 15,
    "labor_rate_cents_per_hour": 9000,
    "electrical_rate_cents_per_amp": 4000,
    "material_handling_rate_cents_per_cwt": 8000,
}


# ── The hall: closed date intervals padded on both ends ─────────────────────
def _two_halls(client: ApiClient) -> dict:
    """
    One edition occupying MCC / HALL_A from 2027-03-01 to 2027-03-09, plus an
    executed agreement on the neighbouring HALL_B.
    """
    fx.set_clock(client, CLOCK)
    hall_a = fx.executed_venue_contract(client)
    hall_b = fx.executed_venue_contract(client, **HALL_B_TERMS)
    first = validate_success(
        client.create_show(
            f.show_payload(hall_a["id"], name="Spring Buyers Expo"),
            fx.DIRECTOR_HEADERS,
        ),
        201,
    )
    return {"hall_a": hall_a, "hall_b": hall_b, "first": first}


def _fair_payload(venue_contract_id: str, move_in_start: str, event_start: str,
                  event_end: str, move_out_end: str) -> dict:
    return f.show_payload(
        venue_contract_id, name="Late Spring Housewares Fair",
        move_in_start=move_in_start, event_start=event_start,
        event_end=event_end, move_out_end=move_out_end,
        gross_sqft=90000, base_rate_cents_per_sqft=3000,
        selection_desk_capacity=1,
    )


def test_padded_hall_windows_that_share_a_single_date_collide(client: ApiClient):
    """
    A move-in four days after the previous move-out: the two buffered intervals
    share exactly 2027-03-11, and one further day is clear.

    "Each edition occupies its hall over the closed interval that runs from two days
    before its `move_in_start` to two days after its `move_out_end` — a symmetric
    dark-day buffer of two days on each side".  "Because the intervals are closed and
    the buffer is symmetric, a move-in exactly two days after another show's move-out
    still collides, and one further day is clear."

    Design: Difficulty/resource_temporal_overlap/hall_occupancy_is_a_closed_date_interval_padded_by_dark_days
    """
    env = _two_halls(client)

    validate_error(
        client.create_show(
            _fair_payload(env["hall_a"]["id"], "2027-03-13", "2027-03-16",
                          "2027-03-17", "2027-03-20"),
            fx.DIRECTOR_HEADERS,
        ),
        ApiErrorId.HALL_OCCUPANCY_CONFLICT,
        409,
    )

    second = validate_success(
        client.create_show(
            _fair_payload(env["hall_a"]["id"], "2027-03-14", "2027-03-17",
                          "2027-03-18", "2027-03-21"),
            fx.DIRECTOR_HEADERS,
        ),
        201,
    )
    assert second["status"] == ShowStatus.PLANNING
    assert second["move_in_start"] == "2027-03-14"

    rows, meta = validate_paginated(
        client.list_venue_contract_shows(env["hall_a"]["id"], fx.DIRECTOR_HEADERS)
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {env["first"]["id"], second["id"]}


def test_an_identical_window_in_another_hall_is_a_different_resource(
    client: ApiClient,
):
    """
    The same dates in HALL_B are accepted, because the occupancy key is the pairing
    of venue and hall.

    "If that buffered interval overlaps the equally buffered interval of any other
    show in the same `venue_code` and `hall_code` pairing whose status is `PLANNING`,
    `SPACE_SELECTION`, `SELLING`, `ON_SITE` or `CLOSED`, the request fails with
    `ERR_HALL_OCCUPANCY_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/hall_occupancy_is_a_closed_date_interval_padded_by_dark_days
    """
    env = _two_halls(client)

    other_hall = validate_success(
        client.create_show(
            f.show_payload(
                env["hall_b"]["id"], name="Spring Gift Market",
                gross_sqft=40000, aisle_ratio_pct=35,
                base_rate_cents_per_sqft=2100, selection_desk_capacity=1,
            ),
            fx.DIRECTOR_HEADERS,
        ),
        201,
    )
    assert other_hall["status"] == ShowStatus.PLANNING
    assert other_hall["move_in_start"] == env["first"]["move_in_start"]
    assert other_hall["move_out_end"] == env["first"]["move_out_end"]

    rows, meta = validate_paginated(
        client.list_venue_contract_shows(env["hall_b"]["id"], fx.DIRECTOR_HEADERS)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == other_hall["id"]


# ── The selection desk: half-open windows counted per round ─────────────────
DESK_EXHIBITORS = [
    ("Nordic Furnishings", "sales@nordic.example", 6),
    ("Harbor Ceramics", "sales@harbor.example", 2),
    ("Alder Textiles", "sales@alder.example", 1),
    ("Basalt Cookware", "sales@basalt.example", 4),
    ("Cedarworks Displays", "sales@cedarworks.example", 3),
]


def _desk_env(client: ApiClient) -> dict:
    """
    A two-desk edition whose first round already holds 09:00-11:00 and 11:00-13:00.
    """
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, [A100, C050])
    assert env["show"]["selection_desk_capacity"] == 2

    exhibitors = {}
    for legal_name, email, years in DESK_EXHIBITORS:
        exhibitors[legal_name] = fx.exhibitor(
            client, legal_name, fx.SALES_REP_HEADERS,
            contact_email=email, consecutive_years=years,
        )
    env["exhibitors"] = exhibitors

    show_id = env["show"]["id"]
    env["appt_a"] = fx.scheduled_appointment(
        client, show_id, exhibitors["Nordic Furnishings"]["id"], 1,
        "2027-01-10T09:00:00Z", "2027-01-10T11:00:00Z", fx.SALES_REP_HEADERS,
    )
    env["appt_b"] = fx.scheduled_appointment(
        client, show_id, exhibitors["Harbor Ceramics"]["id"], 1,
        "2027-01-10T11:00:00Z", "2027-01-10T13:00:00Z", fx.SALES_REP_HEADERS,
    )
    return env


def _book(client: ApiClient, show_id: str, exhibitor_id: str, round_index: int,
          window_start: str, window_end: str):
    return client.create_selection_appointment(
        show_id,
        f.appointment_payload(exhibitor_id, round_index, window_start, window_end),
        fx.SALES_REP_HEADERS,
    )


def test_a_third_straddling_window_exceeds_the_desk_while_adjacency_does_not(
    client: ApiClient,
):
    """
    10:00-12:00 overlaps both held windows and would make three concurrent holders
    against a capacity of two; 13:00-14:00 merely touches the second one's end.

    "counting the `SCHEDULED` appointments of the same show and the same
    `round_index` whose half-open windows overlap the requested one, plus the
    requested appointment itself, the total may not exceed the show's
    `selection_desk_capacity`, or the request is refused with
    `ERR_SELECTION_DESK_CAPACITY_EXCEEDED`."  "Half-open semantics mean an
    appointment starting at the exact instant another ends does not overlap it."

    Design: Difficulty/resource_temporal_overlap/selection_desk_capacity_counts_half_open_windows_per_round
    """
    env = _desk_env(client)
    show_id = env["show"]["id"]
    alder = env["exhibitors"]["Alder Textiles"]["id"]

    validate_error(
        _book(client, show_id, alder, 1,
              "2027-01-10T10:00:00Z", "2027-01-10T12:00:00Z"),
        ApiErrorId.SELECTION_DESK_CAPACITY_EXCEEDED,
        409,
    )

    adjacent = validate_success(
        _book(client, show_id, env["exhibitors"]["Basalt Cookware"]["id"], 1,
              "2027-01-10T13:00:00Z", "2027-01-10T14:00:00Z"),
        201,
    )
    assert adjacent["state"] == AppointmentState.SCHEDULED
    assert adjacent["round_index"] == 1

    rows, meta = validate_paginated(
        client.list_selection_appointments(
            fx.DIRECTOR_HEADERS, {"show_id": show_id, "exhibitor_id": alder}
        )
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_the_same_wall_clock_window_in_the_next_round_uses_its_own_desk(
    client: ApiClient,
):
    """
    Rounds partition the desk, so 09:30-10:30 is free in round 2 even though it
    straddles a round-1 holder.

    "And the desk itself is a finite resource: counting the `SCHEDULED` appointments
    of the same show and the same `round_index` whose half-open windows overlap the
    requested one, plus the requested appointment itself, the total may not exceed the
    show's `selection_desk_capacity`".  "Appointments are readable individually and as
    a filtered list, narrowable by `show_id`, `exhibitor_id`, `round_index` or
    `state`."

    Design: Difficulty/resource_temporal_overlap/selection_desk_capacity_counts_half_open_windows_per_round
    """
    env = _desk_env(client)
    show_id = env["show"]["id"]

    validate_error(
        _book(client, show_id, env["exhibitors"]["Alder Textiles"]["id"], 1,
              "2027-01-10T10:00:00Z", "2027-01-10T12:00:00Z"),
        ApiErrorId.SELECTION_DESK_CAPACITY_EXCEEDED,
        409,
    )
    adjacent = validate_success(
        _book(client, show_id, env["exhibitors"]["Basalt Cookware"]["id"], 1,
              "2027-01-10T13:00:00Z", "2027-01-10T14:00:00Z"),
        201,
    )

    next_round = validate_success(
        _book(client, show_id, env["exhibitors"]["Cedarworks Displays"]["id"], 2,
              "2027-01-10T09:30:00Z", "2027-01-10T10:30:00Z"),
        201,
    )
    assert next_round["state"] == AppointmentState.SCHEDULED
    assert next_round["round_index"] == 2

    round_one, meta_one = validate_paginated(
        client.list_selection_appointments(
            fx.DIRECTOR_HEADERS, {"show_id": show_id, "round_index": 1}
        )
    )
    assert meta_one["total_count"] == 3
    assert {row["id"] for row in round_one} == {
        env["appt_a"]["id"], env["appt_b"]["id"], adjacent["id"],
    }

    round_two, meta_two = validate_paginated(
        client.list_selection_appointments(
            fx.DIRECTOR_HEADERS, {"show_id": show_id, "round_index": 2}
        )
    )
    assert meta_two["total_count"] == 1
    assert round_two[0]["id"] == next_round["id"]
