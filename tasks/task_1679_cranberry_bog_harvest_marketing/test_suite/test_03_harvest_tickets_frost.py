"""Harvest tickets, water scheduling, and frost protection (PRD §2.7, §3.4, §3.5)."""
from types import SimpleNamespace

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    approve_estimate,
    approve_ticket,
    assert_money,
    create_active_member,
    create_bog_for,
    create_estimate,
    create_frost_event,
    create_frost_event_payload,
    create_pool,
    create_season,
    create_station,
    create_ticket,
    create_ticket_payload,
    get_estimate,
    get_quota_for,
    get_ticket,
    make_grower_headers,
    open_season,
    setup_accepted_delivery,
    transition_bog,
    transition_frost_event,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["coop_admin_headers"]
OFFICER = TEST_USERS["field_officer_headers"]


def _member_bog_season():
    member = create_active_member()
    bog = create_bog_for(member["id"])
    season = create_season()
    return member, bog, season


def test_ticket_window_start_after_end_rejected(api):
    """PRD §3.4: "a `window_start` strictly before `window_end`
    (`ERR_INVALID_WINDOW` otherwise)".

    Design: Corner/validations/ticket_window_start_after_end_rejected
    """
    member, bog, season = _member_bog_season()
    resp = api.create_harvest_ticket(
        create_ticket_payload(bog["id"], season["id"],
                              window_start="2026-10-05T00:00:00Z",
                              window_end="2026-10-01T00:00:00Z"),
        make_grower_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)


def test_ticket_expiry_sweep_via_logical_clock(api):
    """PRD §2.7: "Setting the clock triggers an expiry sweep: every harvest
    ticket still in `REQUESTED` status whose `window_start` lies before the new
    current time is moved to `EXPIRED`."
    PRD §3.4: "`COMPLETED`, `CANCELLED`, and `EXPIRED` are all terminal."

    Design: Corner/state_machines/ticket_expiry_sweep_via_logical_clock
    """
    member, bog, season = _member_bog_season()
    ticket = create_ticket(bog["id"], season["id"], member["id"],
                           window_start="2026-10-01T00:00:00Z",
                           window_end="2026-10-05T00:00:00Z")
    assert ticket["status"] == "REQUESTED"

    resp = api.set_clock("2026-10-02T00:00:00Z", ADMIN)
    validate_success(resp, 200)

    assert get_ticket(ticket["id"])["status"] == "EXPIRED", (
        "ticket whose window_start lies before the clock must be swept to EXPIRED")

    resp = api.transition_harvest_ticket(ticket["id"], {"to": "APPROVED"}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_transition_on_unknown_bog_not_found_beats_state(api, field_officer_headers):
    """PRD §2.8: "A request that would fail several checks is always rejected by
    the earliest applicable band, and the bands are evaluated in this fixed
    order:" — existence (band 4) precedes state legality (band 6).
    PRD §2.8: "**Existence** — path identifiers and body-referenced ids (such as
    `season_id`, `bog_id`, `receiving_station_id`, and `harvest_ticket_id`)
    resolve to live records, validated left to right so the first missing
    reference surfaces; otherwise `ERR_NOT_FOUND`."

    Design: Corner/validations/transition_on_unknown_bog_not_found_beats_state
    """
    resp = api.transition_bog(NON_EXISTENT_UUID, {"to": "RENOVATION_PLANNED"},
                              field_officer_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_ticket_approve_blocked_when_bog_not_active(api):
    """PRD §3.4: "A `FieldOfficer` approves a `REQUESTED` ticket — approval
    requires the bog still `ACTIVE` (`ERR_BOG_NOT_ACTIVE`) in addition to the
    fresh overlap check".

    Design: Difficulty/cross_entity_state_dependency/ticket_approve_blocked_when_bog_not_active
    """
    member, bog, season = _member_bog_season()
    ticket = create_ticket(bog["id"], season["id"], member["id"])
    transition_bog(bog["id"], "RENOVATION_PLANNED", make_grower_headers(member["id"]))

    resp = api.transition_harvest_ticket(ticket["id"], {"to": "APPROVED"}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_BOG_NOT_ACTIVE)
    assert get_ticket(ticket["id"])["status"] == "REQUESTED"


def test_ticket_create_blocked_when_bog_not_active(api):
    """PRD §3.4: "Creation requires the season in `SETUP` or `OPEN`, the bog
    `ACTIVE`, a `window_start` strictly before `window_end` (`ERR_INVALID_WINDOW`
    otherwise), and a window that lies entirely within the season's inclusive
    harvest window (`ERR_WINDOW_OUTSIDE_SEASON` otherwise)."
    PRD §2.8: "then bog `ACTIVE` where required, then station existence and
    harvest-ticket consistency, then the quota lock (`ERR_SEASON_NOT_OPEN`,
    `ERR_BOG_NOT_ACTIVE`, `ERR_TICKET_INVALID`, `ERR_QUOTA_LOCKED`)".

    Design: Difficulty/cross_entity_state_dependency/ticket_approve_blocked_when_bog_not_active
    """
    member, bog, season = _member_bog_season()
    transition_bog(bog["id"], "RENOVATION_PLANNED", make_grower_headers(member["id"]))

    resp = api.create_harvest_ticket(
        create_ticket_payload(bog["id"], season["id"]),
        make_grower_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_BOG_NOT_ACTIVE)


def test_harvest_ticket_overlap_rejected_adjacency_allowed(api):
    """PRD §3.4: "A new or approving ticket conflicts with any other ticket on
    the same bog in `REQUESTED` or `APPROVED` status whenever the existing
    ticket's `window_start` falls before the new window's end and the new
    window's start falls before the existing ticket's end — half-open interval
    semantics, under which two windows that merely touch (one's end equal to the
    other's start) do **not** conflict."
    PRD §3.4: "The check runs at creation and is re-checked at approval; a
    conflict is rejected with `ERR_HARVEST_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/harvest_ticket_half_open_overlap_on_bog
    """
    member, bog, season = _member_bog_season()
    grower = make_grower_headers(member["id"])
    ticket1 = create_ticket(bog["id"], season["id"], member["id"],
                            window_start="2026-10-01T00:00:00Z",
                            window_end="2026-10-05T00:00:00Z")
    approve_ticket(ticket1["id"])

    # Overlapping window [10-04, 10-08) intersects [10-01, 10-05).
    resp = api.create_harvest_ticket(
        create_ticket_payload(bog["id"], season["id"],
                              window_start="2026-10-04T00:00:00Z",
                              window_end="2026-10-08T00:00:00Z"),
        grower)
    validate_error(resp, ApiErrorId.ERR_HARVEST_WINDOW_OVERLAP)

    # Adjacent window [10-05, 10-09): start == first window's end is no conflict.
    resp = api.create_harvest_ticket(
        create_ticket_payload(bog["id"], season["id"], method="WET",
                              window_start="2026-10-05T00:00:00Z",
                              window_end="2026-10-09T00:00:00Z"),
        grower)
    adjacent = validate_success(resp, 201)
    assert adjacent["status"] == "REQUESTED"


def test_cancelled_ticket_does_not_block_overlap(api):
    """PRD §3.4: "A new or approving ticket conflicts with any other ticket on
    the same bog in `REQUESTED` or `APPROVED` status" — a CANCELLED ticket is
    outside that set.
    PRD §3.4: "Cancellation from either `REQUESTED` or `APPROVED` is available
    to the owning grower or a `FieldOfficer`, moving the ticket to `CANCELLED`."

    Design: Difficulty/resource_temporal_overlap/harvest_ticket_half_open_overlap_on_bog
    """
    member, bog, season = _member_bog_season()
    grower = make_grower_headers(member["id"])
    ticket1 = create_ticket(bog["id"], season["id"], member["id"],
                            window_start="2026-10-01T00:00:00Z",
                            window_end="2026-10-05T00:00:00Z")
    cancelled = validate_success(
        api.transition_harvest_ticket(ticket1["id"], {"to": "CANCELLED"}, grower),
        200)
    assert cancelled["status"] == "CANCELLED"

    resp = api.create_harvest_ticket(
        create_ticket_payload(bog["id"], season["id"],
                              window_start="2026-10-02T00:00:00Z",
                              window_end="2026-10-06T00:00:00Z"),
        grower)
    ticket2 = validate_success(resp, 201)
    assert ticket2["status"] == "REQUESTED", (
        "a CANCELLED ticket occupies no window and must not conflict")


def test_ticket_create_temporal_error_beats_overlap_constraint(api):
    """PRD §2.8: "A request that would fail several checks is always rejected by
    the earliest applicable band, and the bands are evaluated in this fixed
    order:" — window sanity and season alignment (band 7, yielding
    `ERR_WINDOW_OUTSIDE_SEASON`) precedes resource occupation conflicts
    (band 8, yielding `ERR_HARVEST_WINDOW_OVERLAP`).

    Design: Difficulty/priority_pair_validation_conflict/ticket_create_temporal_error_beats_overlap_constraint
    """
    member, bog, season = _member_bog_season()
    grower = make_grower_headers(member["id"])
    ticket1 = create_ticket(bog["id"], season["id"], member["id"],
                            window_start="2026-10-01T00:00:00Z",
                            window_end="2026-10-05T00:00:00Z")
    approve_ticket(ticket1["id"])

    # [10-04, 11-20) overlaps the APPROVED ticket AND extends past the season
    # harvest end 2026-11-15; the temporal error must win.
    resp = api.create_harvest_ticket(
        create_ticket_payload(bog["id"], season["id"],
                              window_start="2026-10-04T00:00:00Z",
                              window_end="2026-11-20T00:00:00Z"),
        grower)
    validate_error(resp, ApiErrorId.ERR_WINDOW_OUTSIDE_SEASON)


def test_ticket_invalid_window_beats_overlap_constraint(api):
    """PRD §2.8: "A request that would fail several checks is always rejected by
    the earliest applicable band, and the bands are evaluated in this fixed
    order:" — band 7 yields `ERR_INVALID_WINDOW` for "`window_start` strictly
    before `window_end`" before band 8 yields `ERR_HARVEST_WINDOW_OVERLAP`.

    Design: Difficulty/priority_pair_validation_conflict/ticket_create_temporal_error_beats_overlap_constraint
    """
    member, bog, season = _member_bog_season()
    grower = make_grower_headers(member["id"])
    ticket1 = create_ticket(bog["id"], season["id"], member["id"],
                            window_start="2026-10-01T00:00:00Z",
                            window_end="2026-10-05T00:00:00Z")
    approve_ticket(ticket1["id"])

    # Reversed window [10-04, 10-02) also overlaps the APPROVED ticket.
    resp = api.create_harvest_ticket(
        create_ticket_payload(bog["id"], season["id"],
                              window_start="2026-10-04T00:00:00Z",
                              window_end="2026-10-02T00:00:00Z"),
        grower)
    validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)


def test_frost_event_conflicts_with_wet_harvest_flood(api):
    """PRD §3.5: "A frost event conflicts — and its creation is rejected with
    `ERR_WATER_SCHEDULE_CONFLICT` — whenever its window intersects the flood
    interval of any `WET` harvest ticket on the same bog in `REQUESTED` or
    `APPROVED` status, where the ticket's flood interval runs from 24 hours
    before the ticket's `window_start` until the ticket's `window_end`".

    Design: Corner/calculations/frost_event_conflicts_with_wet_harvest_flood
    """
    member, bog, season = _member_bog_season()
    ticket = create_ticket(bog["id"], season["id"], member["id"], method="WET",
                           window_start="2026-10-10T00:00:00Z",
                           window_end="2026-10-12T00:00:00Z")
    approve_ticket(ticket["id"])

    # Flood interval: [10-09T00:00, 10-12T00:00); frost window intersects it.
    resp = api.create_frost_event(
        create_frost_event_payload(bog["id"], season["id"],
                                   window_start="2026-10-09T12:00:00Z",
                                   window_end="2026-10-09T18:00:00Z",
                                   forecast_min_temp_c=-3.0),
        OFFICER)
    validate_error(resp, ApiErrorId.ERR_WATER_SCHEDULE_CONFLICT)


def test_frost_event_no_conflict_with_dry_harvest(api):
    """PRD §3.5: "`DRY` tickets occupy no flood interval and never produce this
    conflict."
    PRD §3.5: "The event starts `DECLARED`".

    Design: Corner/calculations/frost_event_no_conflict_with_dry_harvest
    """
    member, bog, season = _member_bog_season()
    ticket = create_ticket(bog["id"], season["id"], member["id"], method="DRY",
                           window_start="2026-10-10T00:00:00Z",
                           window_end="2026-10-12T00:00:00Z")
    approve_ticket(ticket["id"])

    resp = api.create_frost_event(
        create_frost_event_payload(bog["id"], season["id"],
                                   window_start="2026-10-09T12:00:00Z",
                                   window_end="2026-10-09T18:00:00Z",
                                   forecast_min_temp_c=-3.0),
        OFFICER)
    event = validate_success(resp, 201)
    assert event["status"] == "DECLARED"


def _setup_delivered_2100_with_approved_estimate():
    """Member with APPROVED estimate 2300 (quota base 2300) and two ACCEPTED
    B-grade deliveries netting 1100 + 1000 = 2100 barrels delivered."""
    member = create_active_member()
    bog = create_bog_for(member["id"], acres=10)
    season = create_season()
    estimate = create_estimate(bog["id"], season["id"], member["id"], 2300)
    approve_estimate(estimate["id"])
    open_season(season["id"])
    station = create_station()
    main_pool = create_pool(season["id"], code="MAIN", rate=0.50, retain_pct=0.20)

    ctx = SimpleNamespace(member=member, bog=bog, season=season, station=station)
    setup_accepted_delivery(ctx, gross_barrels=1150, tare_barrels=50,
                            color_score=7.5, firmness_score=7.0,
                            foreign_matter_pct=3.0,
                            scheduled_date="2026-10-10", expected_barrels=1150)
    setup_accepted_delivery(ctx, gross_barrels=1050, tare_barrels=50,
                            color_score=7.5, firmness_score=7.0,
                            foreign_matter_pct=3.0,
                            scheduled_date="2026-10-12", expected_barrels=1050)
    return ctx, estimate, main_pool


def test_frost_damage_cascade_flags_estimate_and_flips_posture(api):
    """PRD §3.5: "At completion the system computes `damage_flag`: `true`
    exactly when `actual_min_temp_c` is at or below the bog's
    `frost_damage_threshold_c`. A damaging completion cascades: if an `APPROVED`
    yield estimate exists for that bog and the event's season, it transitions
    automatically from `APPROVED` to `FLAGGED`, which triggers a recomputation
    of the member's quota excluding that estimate — and if the member's
    deliveries already exceed the recomputed figure, the quota's `posture` flips
    to `OVER_QUOTA` as part of the same cascade."

    Design: Difficulty/transitive_cascade/frost_damage_flags_estimate_recomputes_quota_flips_posture
    """
    ctx, estimate, _pool = _setup_delivered_2100_with_approved_estimate()
    event = create_frost_event(ctx.bog["id"], ctx.season["id"],
                               window_start="2026-10-20T00:00:00Z",
                               window_end="2026-10-20T06:00:00Z",
                               forecast_min_temp_c=-4.0)
    transition_frost_event(event["id"], {"to": "ACTIVE"})

    completed = transition_frost_event(
        event["id"], {"to": "COMPLETED", "actual_min_temp_c": -5.0})
    assert completed["damage_flag"] is True, "-5.0 is at or below the -2.0 threshold"

    assert get_estimate(estimate["id"])["status"] == "FLAGGED", (
        "cascade link 1: the APPROVED estimate is flagged by the damage")

    quota = get_quota_for(ctx.member["id"], ctx.season["id"])
    assert_money(quota["base_quota_barrels"], 2000)  # baseline fallback: 10 * 200
    assert_money(quota["delivered_barrels"], 2100)
    assert quota["posture"] == "OVER_QUOTA", (
        "cascade link 3: delivered 2100 exceeds the recomputed base 2000")


def test_frost_completion_without_damage_leaves_estimate_and_quota(api):
    """PRD §3.5: "At completion the system computes `damage_flag`: `true`
    exactly when `actual_min_temp_c` is at or below the bog's
    `frost_damage_threshold_c`." — above the threshold there is no damage, so
    the cascade of §3.5 ("A damaging completion cascades ...") does not run.

    Design: Difficulty/transitive_cascade/frost_damage_flags_estimate_recomputes_quota_flips_posture
    """
    ctx, estimate, _pool = _setup_delivered_2100_with_approved_estimate()
    event = create_frost_event(ctx.bog["id"], ctx.season["id"],
                               window_start="2026-10-20T00:00:00Z",
                               window_end="2026-10-20T06:00:00Z",
                               forecast_min_temp_c=-1.0)
    transition_frost_event(event["id"], {"to": "ACTIVE"})

    completed = transition_frost_event(
        event["id"], {"to": "COMPLETED", "actual_min_temp_c": -1.0})
    assert completed["damage_flag"] is False, "-1.0 is above the -2.0 threshold"

    assert get_estimate(estimate["id"])["status"] == "APPROVED", (
        "no damage, so the estimate is not flagged")

    quota = get_quota_for(ctx.member["id"], ctx.season["id"])
    assert_money(quota["base_quota_barrels"], 2300)
    assert quota["posture"] == "WITHIN_QUOTA", (
        "delivered 2100 remains within the unchanged base 2300")
