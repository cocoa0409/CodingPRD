"""What each operation returns and what the next read shows: catalogue echo,
the countersign that feeds the rollup, the mutual pairing, the recomputed
supplement, three derived departure fields in one read, and an idle ratification.
"""

from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    api_client,
    assign_room,
    countersign_land_assignment,
    create_land_assignment,
    create_land_resource,
    create_service_booking,
    enrol_traveler,
    expected_invoice_total,
    expected_land_line,
    open_departure,
    pay,
    read_departure,
    read_land_assignment,
    read_traveler,
    validate_error,
    validate_paginated,
    validate_success,
    HOLY_LAND_T1_INVOICE_CENTS,
    TEST_USERS,
)

PLANNER = TEST_USERS["program_manager"]
PLANNER_SECOND = TEST_USERS["program_manager_second"]
LAND = TEST_USERS["land_contractor"]
FINANCE = TEST_USERS["finance_controller"]


def test_a_land_resource_reads_back_exactly_as_it_was_registered(api):
    """PRD §3.3: "A `LandContractor` registers a **LandResource** with the
    `operator_name` holding it under contract (1 to 120 characters), the
    `country` of performance as exactly two uppercase letters, a `resource_type`
    of `HOTEL_ROOM_BLOCK`, `MOTORCOACH` or `GUIDE`, a `units_total` between 1 and
    500 stating how many units the operator guarantees per calendar day, a
    `unit_rate_local_cents` of at least 1 in the local currency's minor units per
    unit per day, an `fx_rate_bp` between 1 and 1,000,000 pinning the
    local-to-USD conversion in basis points where 10,000 basis points is parity,
    and a `force_majeure_notice_days` between 0 and 180 giving the
    local-conditions notice window inside which termination is penalty-free."

    Design: Corner/endpoints/land_resource_create_and_read_back
    """
    payload = {
        "operator_name": "Galilee Coaches Ltd",
        "country": "IL",
        "resource_type": "MOTORCOACH",
        "units_total": 4,
        "unit_rate_local_cents": 90_000,
        "fx_rate_bp": 10_833,
        "force_majeure_notice_days": 30,
    }
    created = validate_success(api_client.create_land_resource(payload, LAND), 201)

    fetched = validate_success(api_client.get_land_resource(created["id"], PLANNER))

    assert fetched["id"] == created["id"]
    for field, value in payload.items():
        assert fetched[field] == value


def test_countersigning_pulls_the_draft_line_into_the_departure_rollup(api):
    """PRD §3.3: "A departure's `land_cost_total_cents` aggregates only those of
    its lines whose `status` is `COUNTERSIGNED`. Draft lines occupy units but
    contribute nothing to cost; terminated lines contribute nothing and release
    their units." And: "The rollup is recomputed when a line is countersigned,
    when a line is terminated, when an itinerary modification is ratified, and
    when sales close; creating a draft line computes that line's own figures but
    leaves the departure's total unchanged."

    Design: Corner/endpoints/countersign_moves_a_draft_land_line_into_the_rollup
    """
    stage = open_departure()
    departure_id = stage["departure"]["id"]
    resource = create_land_resource(
        operator_name="Galilee Coaches Ltd",
        country="IL",
        resource_type="MOTORCOACH",
        units_total=4,
        unit_rate_local_cents=90_000,
        fx_rate_bp=10_833,
        force_majeure_notice_days=30,
    )
    line = create_land_assignment(
        resource["id"],
        departure_id,
        date_from="2026-10-28",
        date_to="2026-11-01",
        units_requested=3,
    )
    days, local, usd = expected_land_line(3, "2026-10-28", "2026-11-01", 90_000, 10_833)
    assert (days, local, usd) == (5, 1_350_000, 1_462_455)
    # The draft line prices itself but contributes nothing yet.
    assert read_departure(departure_id)["land_cost_total_cents"] == 0

    countersigned = countersign_land_assignment(line["id"])

    assert countersigned["status"] == "COUNTERSIGNED"
    live = read_land_assignment(line["id"])
    assert live["days_inclusive"] == days
    assert live["line_local_cents"] == local
    assert live["line_usd_cents"] == usd
    assert read_departure(departure_id)["land_cost_total_cents"] == usd


def test_one_rooming_call_writes_the_pairing_on_both_travelers(api):
    """PRD §3.5: "A successful assignment writes `room_type_assigned`,
    `room_label`, `ground_floor` and `dietary_codes`, writes
    `roommate_pilgrim_id` on **both** travelers so the pairing is mutual, sets
    `single_supplement_applied_cents` to the departure's
    `provisional_single_supplement_cents` when `room_type_assigned` is `SINGLE`
    and clears it to 0 otherwise, recomputes the invoice, and increments the
    traveler's `version`."

    Design: Corner/endpoints/rooming_writes_the_pairing_on_both_travelers
    """
    stage = open_departure()
    departure_id = stage["departure"]["id"]
    first = enrol_traveler(
        departure_id, full_name="Pair One", date_of_birth="1975-01-10"
    )
    second = enrol_traveler(
        departure_id, full_name="Pair Two", date_of_birth="1976-03-12"
    )
    assign_room(first["id"], room_type_assigned="DOUBLE", room_label="IL-208")

    paired = validate_success(
        api_client.assign_rooming(
            second["id"],
            {
                "room_type_assigned": "DOUBLE",
                "room_label": "IL-208",
                "ground_floor": False,
                "roommate_pilgrim_id": first["id"],
            },
            PLANNER,
        )
    )
    assert paired["roommate_pilgrim_id"] == first["id"]

    rows, meta = validate_paginated(
        api_client.list_pilgrims(
            PLANNER,
            {"departure_id": departure_id, "roommate_pilgrim_id": first["id"]},
        )
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["id"] == second["id"]
    # The partner was never the subject of a call, yet carries the back-reference.
    assert read_traveler(first["id"])["roommate_pilgrim_id"] == second["id"]


def test_re_rooming_out_of_a_single_clears_the_supplement(api):
    """PRD §3.5: "A successful assignment writes `room_type_assigned`,
    `room_label`, `ground_floor` and `dietary_codes`, writes
    `roommate_pilgrim_id` on **both** travelers so the pairing is mutual, sets
    `single_supplement_applied_cents` to the departure's
    `provisional_single_supplement_cents` when `room_type_assigned` is `SINGLE`
    and clears it to 0 otherwise, recomputes the invoice, and increments the
    traveler's `version`."

    Design: Corner/endpoints/single_supplement_applied_then_cleared_by_reassignment
    """
    stage = open_departure()
    traveler = enrol_traveler(
        stage["departure"]["id"],
        full_name="Solo Traveler",
        date_of_birth="1975-01-10",
        room_type_requested="SINGLE",
    )
    single = assign_room(
        traveler["id"], room_type_assigned="SINGLE", room_label="IL-301"
    )
    assert single["single_supplement_applied_cents"] == 98_000
    assert single["invoice_total_cents"] == expected_invoice_total(587_000, 98_000)
    assert single["invoice_total_cents"] == 673_526
    pay(traveler["id"], 50_000, method="PARISH_TRANSFER")

    moved = validate_success(
        api_client.assign_rooming(
            traveler["id"],
            {
                "room_type_assigned": "DOUBLE",
                "room_label": "IL-302",
                "ground_floor": False,
            },
            PLANNER,
        )
    )

    assert moved["single_supplement_applied_cents"] == 0
    assert moved["room_type_assigned"] == "DOUBLE"
    assert moved["room_label"] == "IL-302"
    # Recomputed from scratch rather than accumulated.
    assert moved["invoice_total_cents"] == HOLY_LAND_T1_INVOICE_CENTS


def test_one_departure_read_returns_three_independently_derived_fields(api):
    """PRD §3.1: "`paying_pax_count` is the number of travelers on the departure
    whose `is_paying` is true and whose `booking_status` is `DEPOSITED` or
    `CONFIRMED` — the same population the provisional variant prices from — and it
    opens at 0 and is refreshed on every roster movement. `service_coverage_ok`
    opens at true on a brand-new departure and is thereafter true only while the
    departure has at least one non-cancelled service booking, every non-cancelled
    booking has reached `CONFIRMED`, and none of them was force-cancelled by a
    risk suspension. `land_cost_total_cents` opens at 0 and holds the USD-cent
    land cost described in §3.3."

    Design: Corner/endpoints/departure_read_exposes_three_independently_derived_fields
    """
    stage = open_departure()
    departure_id = stage["departure"]["id"]
    for full_name, born in (("Traveler A", "1975-01-10"), ("Traveler B", "1976-03-12")):
        traveler = enrol_traveler(
            departure_id, full_name=full_name, date_of_birth=born
        )
        assign_room(traveler["id"])
        pay(traveler["id"], 50_000, method="PARISH_TRANSFER")
    resource = create_land_resource(
        operator_name="Jerusalem Guides Co",
        country="IL",
        resource_type="GUIDE",
        units_total=3,
        unit_rate_local_cents=51_000,
        fx_rate_bp=10_833,
        force_majeure_notice_days=30,
    )
    line = create_land_assignment(
        resource["id"],
        departure_id,
        date_from="2026-11-01",
        date_to="2026-11-05",
        units_requested=2,
    )
    countersign_land_assignment(line["id"])
    site = validate_success(
        api_client.create_sacred_site(
            {
                "name": "Mount of Olives Overlook",
                "country": "IL",
                "access_regime": "OPEN_ACCESS",
                "daily_capacity_pax": 200,
                "turnaround_buffer_minutes": 30,
                "requires_local_clergy": False,
            },
            PLANNER,
        ),
        201,
    )
    held = create_service_booking(
        departure_id,
        site["id"],
        service_type="MASS",
        scheduled_start_utc="2026-11-02T09:00:00Z",
        duration_minutes=90,
        pax_count=2,
    )
    assert held["status"] == "SITE_HELD"

    fetched = validate_success(api_client.get_departure(departure_id, FINANCE))

    _days, _local, usd = expected_land_line(2, "2026-11-01", "2026-11-05", 51_000, 10_833)
    assert usd == 552_483
    assert fetched["land_cost_total_cents"] == usd
    assert fetched["paying_pax_count"] == 2
    assert fetched["provisional_tier_code"] == "T1"
    assert fetched["provisional_per_pax_price_cents"] == 587_000
    assert fetched["service_coverage_ok"] is False
    assert fetched["status"] == "OPEN_FOR_SALE"


def test_ratifying_with_nothing_proposed_is_refused(api):
    """PRD §3.9: "Ratification requires `pending_modification_required` to be
    true, failing which — nothing was proposed, or the previous proposal was
    already ratified — the answer is `ERR_NO_PENDING_MODIFICATION` (HTTP 409);
    and it requires the acting `X-User-ID` to differ from
    `pending_modification_proposed_by_user_id`, failing which the answer is
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/endpoints/ratify_modification_without_a_pending_proposal_rejected
    """
    stage = open_departure()
    departure_id = stage["departure"]["id"]
    assert stage["departure"]["pending_modification_required"] is False

    response = api_client.ratify_itinerary_modification(departure_id, PLANNER_SECOND)
    validate_error(response, ApiErrorId.NO_PENDING_MODIFICATION.value)

    live = read_departure(departure_id)
    assert live["pending_modification_required"] is False
    assert live["ratified_modification_count"] == 0
    assert live["itinerary_cost_delta_cents"] == 0
