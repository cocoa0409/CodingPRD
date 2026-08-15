"""Routing windows, stop creation gates, budget gate, OCC, amendments (PRD §2.6, §2.7, §3.2)."""
from test_helpers import (
    PRODUCER,
    TOUR_MANAGER,
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_stop,
    advance_stop,
    assert_budget_identity,
    assert_stop,
    cancel_stop,
    contract_stop,
    create_stop_payload,
    create_tour,
    create_venue,
    get_stop,
    get_tour,
    validate_error,
    validate_success,
)


def test_stop_create_body_fk_not_found_returns_404(api):
    """PRD §2.7: "Foreign keys supplied in request bodies — a `venue_id` on stop
    creation, a `cast_member_id` on a coverage or per-diem, a
    `principal_member_id` on a track — must likewise resolve to existing
    resources or the request fails with `ERR_NOT_FOUND`."

    Design: Corner/entities/stop_create_body_fk_not_found_returns_404
    """
    tour = create_tour()
    payload = create_stop_payload(NON_EXISTENT_UUID, tour["version"])
    resp = api.create_stop(tour["id"], payload, TOUR_MANAGER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_stop_create_initial_state(api):
    """PRD §3.2: "A new stop is created with `booking_status` `TENTATIVE` and `compliance_status` `PENDING`, and its creation increments the tour’s `version`."

    Design: Corner/entities/stop_create_initial_state
    """
    tour = create_tour()
    venue = create_venue()
    stop = add_stop(tour["id"], venue["id"])
    assert_stop(stop)
    assert stop["booking_status"] == "TENTATIVE"
    assert stop["compliance_status"] == "PENDING"
    assert stop["tour_id"] == tour["id"]
    assert stop["venue_id"] == venue["id"]
    assert isinstance(stop["version"], int)

    after = get_tour(tour["id"])
    assert after["version"] == tour["version"] + 1, (
        "Stop creation increments the tour's version by one"
    )


def test_stop_window_shape_returns_invalid_request(api):
    """PRD §2.8: "Third comes request shape (priority 4): required fields
    present, unknown fields rejected, enums valid, and numeric ranges respected —
    cents non-negative, `split_pct` between 0 and 100 inclusive, `play_week_end`
    on or after `play_week_start`, `load_in_date` on or before `play_week_start`"

    Design: Corner/validations/stop_window_shape_returns_invalid_request
    """
    tour = create_tour()
    venue = create_venue()

    bad_end = create_stop_payload(
        venue["id"], tour["version"],
        play_week_start="2026-09-13", play_week_end="2026-09-07",
        load_in_date="2026-09-05",
    )
    validate_error(api.create_stop(tour["id"], bad_end, TOUR_MANAGER),
                   ApiErrorId.ERR_INVALID_REQUEST)

    bad_load_in = create_stop_payload(
        venue["id"], tour["version"],
        play_week_start="2026-09-07", play_week_end="2026-09-13",
        load_in_date="2026-09-08",
    )
    validate_error(api.create_stop(tour["id"], bad_load_in, TOUR_MANAGER),
                   ApiErrorId.ERR_INVALID_REQUEST)


def test_stop_routing_buffer_rejects_adjacent_start(api):
    """PRD §3.2: "The new stop’s play window, treated as a closed interval, must clear every other non-`CANCELLED` stop of the tour with a mandatory travel buffer: either the new stop’s `play_week_start` falls strictly after the sibling’s `play_week_end` plus the new stop’s own `travel_in_days`, or the sibling’s `play_week_start` falls strictly after the new stop’s `play_week_end` plus the sibling’s `travel_in_days`."
    PRD §3.2: "Equality on the passing side — a start exactly one day after the sibling’s end plus the travel days — passes; anything tighter is rejected with `ERR_STOP_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/stop_routing_travel_buffer
    """
    tour = create_tour()
    venue = create_venue()
    add_stop(tour["id"], venue["id"], play_week_start="2026-09-07",
             play_week_end="2026-09-13", load_in_date="2026-09-05", travel_in_days=0)
    tour_v = get_tour(tour["id"])["version"]

    # Sibling end 2026-09-13 + travel 3 = 2026-09-16; a start ON that day is
    # "tighter" than strictly-after and must be rejected.
    resp = api.create_stop(
        tour["id"],
        create_stop_payload(venue["id"], tour_v, play_week_start="2026-09-16",
                            play_week_end="2026-09-20", load_in_date="2026-09-15",
                            travel_in_days=3),
        TOUR_MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_STOP_WINDOW_CONFLICT)


def test_stop_routing_buffer_passes_one_day_beyond(api):
    """PRD §3.2: "Equality on the passing side — a start exactly one day after
    the sibling’s end plus the travel days — passes; anything tighter is rejected
    with `ERR_STOP_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/stop_routing_travel_buffer
    """
    tour = create_tour()
    venue = create_venue()
    add_stop(tour["id"], venue["id"], play_week_start="2026-09-07",
             play_week_end="2026-09-13", load_in_date="2026-09-05", travel_in_days=0)
    tour_v = get_tour(tour["id"])["version"]

    # 2026-09-17 == end 2026-09-13 + travel 3 + 1 -> passes the buffer.
    stop_b = validate_success(api.create_stop(
        tour["id"],
        create_stop_payload(venue["id"], tour_v, play_week_start="2026-09-17",
                            play_week_end="2026-09-20", load_in_date="2026-09-16",
                            travel_in_days=3),
        TOUR_MANAGER,
    ), 201)
    assert stop_b["booking_status"] == "TENTATIVE"


def test_budget_exceeded_on_contract(api):
    """PRD §3.2: "Contracting requires the tour to be in `PLANNING` or `ON_TOUR` and subjects the deal to the budget gate: the tour’s `budget_available_cents` must be at least the stop’s `guarantee_cents`, or the request fails with `ERR_TOUR_BUDGET_EXCEEDED`."

    Design: Corner/validations/budget_exceeded_on_contract
    """
    tour = create_tour(budget_total_cents=5_000_000)
    venue = create_venue()
    stop = add_stop(tour["id"], venue["id"], guarantee_cents=6_000_000)

    resp = api.put_stop(stop["id"], {"status": "CONTRACTED"}, PRODUCER)
    validate_error(resp, ApiErrorId.ERR_TOUR_BUDGET_EXCEEDED)

    after = get_stop(stop["id"])
    assert after["booking_status"] == "TENTATIVE", "Rejected contract must not move the stop"
    assert_budget_identity(get_tour(tour["id"]))


def test_stop_create_on_completed_tour_returns_not_bookable(api):
    """PRD §3.2: "Creation requires the OCC token `expected_tour_version` as
    described in §2.6, and the tour must be bookable — in `PLANNING` or
    `ON_TOUR`; booking against a `COMPLETED` or `CLOSED` tour is rejected with
    `ERR_TOUR_NOT_BOOKABLE`."

    Design: Corner/state_machines/stop_create_on_completed_tour_returns_not_bookable
    """
    tour = create_tour()
    venue = create_venue()
    stop = add_stop(tour["id"], venue["id"])
    cancel_stop(stop["id"])  # TENTATIVE cancel: no penalty, stop now terminal
    validate_success(api.patch_tour(tour["id"], {"status": "ON_TOUR"}, PRODUCER))
    validate_success(api.patch_tour(tour["id"], {"status": "COMPLETED"}, PRODUCER))

    tour_v = get_tour(tour["id"])["version"]
    payload = create_stop_payload(
        venue["id"], tour_v, play_week_start="2026-10-05",
        play_week_end="2026-10-11", load_in_date="2026-10-03", travel_in_days=1,
    )
    resp = api.create_stop(tour["id"], payload, TOUR_MANAGER)
    validate_error(resp, ApiErrorId.ERR_TOUR_NOT_BOOKABLE)


def test_occ_stop_create_stale_tour_version(api):
    """PRD §2.6: "If the tour’s current `version` does not match — because another stop creation has advanced it since the client last read the tour — the creation is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stop_create_stale_tour_version
    """
    tour = create_tour()
    venue = create_venue()
    tour_v1 = tour["version"]
    add_stop(tour["id"], venue["id"], expected_tour_version=tour_v1,
             play_week_start="2026-09-07", play_week_end="2026-09-13",
             load_in_date="2026-09-05", travel_in_days=1)

    # Second create still carrying the pre-first-create tour version.
    stale = api.create_stop(
        tour["id"],
        create_stop_payload(venue["id"], tour_v1, play_week_start="2026-09-15",
                            play_week_end="2026-09-20", load_in_date="2026-09-14",
                            travel_in_days=1),
        TOUR_MANAGER,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    # The rejected create advanced nothing; version moved by exactly one.
    tour_v2 = get_tour(tour["id"])["version"]
    assert tour_v2 == tour_v1 + 1

    retry = api.create_stop(
        tour["id"],
        create_stop_payload(venue["id"], tour_v2, play_week_start="2026-09-15",
                            play_week_end="2026-09-20", load_in_date="2026-09-14",
                            travel_in_days=1),
        TOUR_MANAGER,
    )
    validate_success(retry, 201)


def test_occ_stop_amend_stale_stop_version(api):
    """PRD §2.6: "Amending a stop’s contract terms requires the non-optional field `expected_stop_version`, carrying the client’s last observed `version` of the stop. If the stop’s current `version` does not match, the amendment is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stop_amend_stale_stop_version
    """
    tour = create_tour()
    venue = create_venue()
    stop = add_stop(tour["id"], venue["id"])
    contracted = contract_stop(stop["id"])
    stop_v = contracted["version"]

    first = api.amend_stop(stop["id"], {"expected_stop_version": stop_v,
                                        "guarantee_cents": 4_500_000}, PRODUCER)
    amended = validate_success(first, 200)
    assert amended["guarantee_cents"] == 4_500_000

    stale = api.amend_stop(stop["id"], {"expected_stop_version": stop_v,
                                        "guarantee_cents": 5_000_000}, PRODUCER)
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    final = get_stop(stop["id"])
    assert final["guarantee_cents"] == 4_500_000, "Loser's write must never land"


def test_state_beats_fiscal_on_amend_rejected(api):
    """PRD §3.2: "Amending outside `CONTRACTED` is rejected with
    `ERR_STOP_INVALID_STATE`."
    PRD §2.8: "Fourth come state guards (priority 5, all HTTP 409)"
    PRD §2.8: "Last come fiscal rules (priority 10, HTTP 422): the tour budget
    check (`ERR_TOUR_BUDGET_EXCEEDED`) and the settlement completeness check
    (`ERR_SETTLEMENT_INCOMPLETE`)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_amend
    """
    tour = create_tour()
    venue = create_venue()
    stop = add_stop(tour["id"], venue["id"])
    contract_stop(stop["id"])
    advanced = advance_stop(stop["id"])

    # Both rules fail here: amend is CONTRACTED-only (state) and the new
    # guarantee 60,000,000 exceeds the 46,000,000 available (fiscal). The
    # pipeline evaluates state guards before fiscal rules.
    resp = api.amend_stop(stop["id"], {"expected_stop_version": advanced["version"],
                                       "guarantee_cents": 60_000_000}, PRODUCER)
    validate_error(resp, ApiErrorId.ERR_STOP_INVALID_STATE)


def test_state_beats_fiscal_on_amend_in_budget_still_state_error(api):
    """PRD §3.2: "Amending outside `CONTRACTED` is rejected with
    `ERR_STOP_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_amend
    """
    tour = create_tour()
    venue = create_venue()
    stop = add_stop(tour["id"], venue["id"])
    contract_stop(stop["id"])
    advanced = advance_stop(stop["id"])

    # Only the state rule fails (the guarantee delta is affordable): the same
    # rejection isolates the state guard from the fiscal gate.
    resp = api.amend_stop(stop["id"], {"expected_stop_version": advanced["version"],
                                       "guarantee_cents": 4_500_000}, PRODUCER)
    validate_error(resp, ApiErrorId.ERR_STOP_INVALID_STATE)

    after = get_stop(stop["id"])
    assert after["guarantee_cents"] == 4_000_000, "Rejected amend must not change terms"
