"""Escort assignments: explicit-path validations, window overlap, selector."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    register_carrier,
    register_escort,
    read_escort,
    set_clock,
    create_tx_job,
    list_job_legs,
    quote_job,
    accept_quote,
    offer_assignment,
    accept_assignment,
    release_assignment,
    get_assignment,
    get_leg,
    setup_booked_job,
    setup_delivered_rear_job,
    advance_to_cleared,
    advance_to_scheduled,
    advance_to_en_route,
    advance_to_delivered,
    offer_and_accept,
    report_incident,
    assess_incident,
    settle_incident,
    make_escort_operator_headers,
    api_client,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
SAFETY = TEST_USERS["safety_manager_headers"]


def _setup_certification_conflict():
    """OK-only escort ACCEPTED on a booked OK job; a booked TX job whose
    buffered window overlaps the OK job's buffered window."""
    carrier = register_carrier(10_000_000, "Sooner Shipping")
    esc2 = register_escort(("OK",), "Okie Only")
    bundle_k = setup_booked_job(
        carrier,
        load_description="OK job",
        state_code="OK",
        distance_miles=100,
    )
    asg_k = offer_assignment(bundle_k["leg"]["id"], "REAR", esc2["id"])
    accept_assignment(asg_k, esc2["id"])
    bundle_b = setup_booked_job(
        carrier,
        load_description="TX job",
        width_inches=185,
        window_start_at="2026-08-10T10:00:00Z",
        window_end_at="2026-08-10T14:00:00Z",
        planned_entry_at="2026-08-10T10:00:00Z",
        planned_exit_at="2026-08-10T14:00:00Z",
    )
    return carrier, esc2, bundle_k, bundle_b


def test_certification_error_beats_window_conflict(api):
    """PRD §2.11: "8. Escort safety checks on explicit assignment offers: state
    certification (`ERR_ESCORT_NOT_CERTIFIED_FOR_STATE`, HTTP 422) and
    height-pole equipment (`ERR_HEIGHT_POLE_EQUIPMENT_MISSING`, HTTP 422)."
    PRD §3.5: "the leg's `state_code` must appear in the escort's
    `certified_state_codes`, else `ERR_ESCORT_NOT_CERTIFIED_FOR_STATE` (HTTP
    422); for a `FRONT` position on a leg that requires a height pole, the
    escort must carry a pole ... and the escort's buffered availability must be
    free, else `ERR_ESCORT_WINDOW_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_assignment
    """
    carrier, esc2, bundle_k, bundle_b = _setup_certification_conflict()
    resp = api.create_assignment(
        bundle_b["leg"]["id"], {"position": "REAR", "escort_id": esc2["id"]}, DISPATCHER
    )
    # Certification (pipeline item 8) fires before the window check (item 10),
    # even though the buffered windows also overlap.
    validate_error(resp, ApiErrorId.ERR_ESCORT_NOT_CERTIFIED_FOR_STATE)
    assert resp.status_code == 422


def test_rejected_offer_creates_no_assignment(api):
    """PRD §3.5: "the leg's `state_code` must appear in the escort's
    `certified_state_codes`, else `ERR_ESCORT_NOT_CERTIFIED_FOR_STATE` (HTTP
    422)"

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_assignment
    """
    carrier, esc2, bundle_k, bundle_b = _setup_certification_conflict()
    resp = api.create_assignment(
        bundle_b["leg"]["id"], {"position": "REAR", "escort_id": esc2["id"]}, DISPATCHER
    )
    validate_error(resp, ApiErrorId.ERR_ESCORT_NOT_CERTIFIED_FOR_STATE)
    rows, meta = validate_paginated(api.list_leg_assignments(bundle_b["leg"]["id"], DISPATCHER))
    assert rows == [] and meta["total_count"] == 0


def _setup_overlap_jobs():
    """Escort ACCEPTED on booked job A (09:00..13:00); booked jobs B (15:00..
    17:00, exactly 120 minutes later) and C (13:59..16:00, 119 minutes later)."""
    carrier = register_carrier(1_000_000, "Overlap Test Co")
    esc = register_escort(("TX",), "Busy Rider")
    bundle_a = setup_booked_job(carrier, load_description="A", width_inches=185)
    asg_a = offer_assignment(bundle_a["leg"]["id"], "REAR", esc["id"])
    accept_assignment(asg_a, esc["id"])
    bundle_b = setup_booked_job(
        carrier,
        load_description="B",
        width_inches=185,
        distance_miles=60,
        window_start_at="2026-08-10T15:00:00Z",
        window_end_at="2026-08-10T17:00:00Z",
    )
    bundle_c = setup_booked_job(
        carrier,
        load_description="C",
        width_inches=185,
        distance_miles=60,
        window_start_at="2026-08-10T13:59:00Z",
        window_end_at="2026-08-10T16:00:00Z",
    )
    return carrier, esc, bundle_a, bundle_b, bundle_c


def test_buffered_windows_touching_at_120_minutes_allowed(api):
    """PRD §3.5: "Intervals that merely touch after expansion do not conflict:
    two jobs whose unbuffered windows are exactly 120 minutes apart do not
    conflict, while windows 119 minutes apart do."

    Design: Difficulty/resource_temporal_overlap/escort_buffered_window_touch_vs_conflict
    """
    carrier, esc, bundle_a, bundle_b, bundle_c = _setup_overlap_jobs()
    resp = api.create_assignment(
        bundle_b["leg"]["id"], {"position": "REAR", "escort_id": esc["id"]}, DISPATCHER
    )
    created = validate_success(resp, 201)
    assert created["assignment_status"] == "OFFERED"
    # A's expanded window [08:00, 14:00] merely touches B's [14:00, 18:00].
    esc_row = read_escort(esc["id"])
    assert esc_row["active_assignment_count"] == 1, (
        "an OFFERED assignment does not move the count"
    )


def test_buffered_windows_119_minutes_apart_conflict(api):
    """PRD §3.5: "The candidate escort's window for this job runs from 60
    minutes before `window_start_at` to 60 minutes after `window_end_at`, and
    it conflicts with any of the escort's other assignments in `ACCEPTED` or
    `ACTIVE` whose own job windows, expanded by the same 60 minutes on both
    ends, strictly intersect it."

    Design: Difficulty/resource_temporal_overlap/escort_buffered_window_touch_vs_conflict
    """
    carrier, esc, bundle_a, bundle_b, bundle_c = _setup_overlap_jobs()
    ok = api.create_assignment(
        bundle_b["leg"]["id"], {"position": "REAR", "escort_id": esc["id"]}, DISPATCHER
    )
    validate_success(ok, 201)
    resp = api.create_assignment(
        bundle_c["leg"]["id"], {"position": "REAR", "escort_id": esc["id"]}, DISPATCHER
    )
    validate_error(resp, ApiErrorId.ERR_ESCORT_WINDOW_CONFLICT)
    assert resp.status_code == 409
    esc_row = read_escort(esc["id"])
    assert esc_row["active_assignment_count"] == 1


def test_suspension_leaves_offered_assignment_offered(api):
    """PRD §3.1: "Suspension moves the escort to `SUSPENDED` and immediately
    releases every one of that escort's assignments currently in `ACCEPTED`:
    each becomes `RELEASED` with `release_cause` `ESCORT_SUSPENDED`, and the
    escort's `active_assignment_count` is decremented for each release."

    Design: Difficulty/cross_entity_state_dependency/assignment_accept_requires_escort_active
    """
    carrier = register_carrier(10_000_000, "Stable Freight")
    esc = register_escort(("TX",), "Shaky Rider")
    bundle = setup_booked_job(carrier)
    asg = offer_assignment(bundle["leg"]["id"], "REAR", esc["id"])

    resp = api.suspend_escort(esc["id"], SAFETY)
    validate_success(resp)

    assert get_assignment(asg["id"])["assignment_status"] == "OFFERED", (
        "suspension releases only ACCEPTED assignments; OFFERED is untouched"
    )
    assert read_escort(esc["id"])["escort_status"] == "SUSPENDED"


def test_accept_while_escort_suspended_rejected(api):
    """PRD §3.5: "Acceptance requires the assignment to be `OFFERED` (else
    `ERR_ASSIGNMENT_INVALID_STATE`), the escort to be `ACTIVE` (else
    `ERR_ESCORT_INVALID_STATE`), the leg's job to be in `BOOKED`, `CLEARED`, or
    `SCHEDULED` (else `ERR_JOB_INVALID_STATE`)"

    Design: Difficulty/cross_entity_state_dependency/assignment_accept_requires_escort_active
    """
    carrier = register_carrier(10_000_000, "Stable Freight")
    esc = register_escort(("TX",), "Shaky Rider")
    bundle = setup_booked_job(carrier)
    asg = offer_assignment(bundle["leg"]["id"], "REAR", esc["id"])
    validate_success(api.suspend_escort(esc["id"], SAFETY))

    resp = api.accept_assignment(asg["id"], make_escort_operator_headers(esc["id"]))
    validate_error(resp, ApiErrorId.ERR_ESCORT_INVALID_STATE)

    assert get_assignment(asg["id"])["assignment_status"] == "OFFERED", "no partial mutation"
    assert read_escort(esc["id"])["escort_status"] == "SUSPENDED"


def test_offer_then_decline_conserves_assignment_count(api):
    """PRD §3.5: "Declining requires only the `OFFERED` state and moves the
    assignment to the terminal `DECLINED`; an offer-then-decline pair leaves
    the escort's `active_assignment_count` unchanged — the count is conserved."

    Design: Difficulty/compensating_invariant/offer_accept_release_conserves_assignment_count
    """
    carrier = register_carrier(10_000_000, "Count Conservation Co")
    esc = register_escort(("TX",), "Counted Rider")
    bundle = setup_booked_job(carrier)

    asg1 = offer_assignment(bundle["leg"]["id"], "REAR", esc["id"])
    assert read_escort(esc["id"])["active_assignment_count"] == 0, "OFFERED never increments"

    resp = api.decline_assignment(asg1["id"], make_escort_operator_headers(esc["id"]))
    declined = validate_success(resp)
    assert declined["assignment_status"] == "DECLINED"
    assert read_escort(esc["id"])["active_assignment_count"] == 0

    # The terminal DECLINED offer frees the position quota for a fresh offer.
    asg2 = offer_assignment(bundle["leg"]["id"], "REAR", esc["id"])
    assert asg2["assignment_status"] == "OFFERED"


def test_accept_then_release_conserves_assignment_count(api):
    """PRD §3.5: "A successful acceptance moves the assignment to `ACCEPTED`,
    stamps `accepted_at`, and increments the escort's
    `active_assignment_count`."
    PRD §3.5: "Releasing an assignment that was `ACCEPTED` decrements the
    escort's `active_assignment_count`, so an accept-then-release pair
    conserves the count just as offer-then-decline does."

    Design: Difficulty/compensating_invariant/offer_accept_release_conserves_assignment_count
    """
    carrier = register_carrier(10_000_000, "Count Conservation Co")
    esc = register_escort(("TX",), "Counted Rider")
    bundle = setup_booked_job(carrier)

    asg = offer_assignment(bundle["leg"]["id"], "REAR", esc["id"])
    accepted = accept_assignment(asg, esc["id"])
    assert accepted["assignment_status"] == "ACCEPTED"
    assert read_escort(esc["id"])["active_assignment_count"] == 1

    released = release_assignment(asg["id"])
    assert released["assignment_status"] == "RELEASED"
    assert released["release_cause"] == "DISPATCHER"
    assert read_escort(esc["id"])["active_assignment_count"] == 0


def test_height_pole_equipment_missing_rejected(api):
    """PRD §3.5: "for a `FRONT` position on a leg that requires a height pole,
    the escort must carry a pole — `has_height_pole` true — whose
    `height_pole_max_inches` is at least the job's `height_inches`, else
    `ERR_HEIGHT_POLE_EQUIPMENT_MISSING` (HTTP 422)"

    Design: Corner/validations/height_pole_equipment_missing_rejected
    """
    carrier = register_carrier(10_000_000, "Pole Co")
    e_plain = register_escort(("TX",), "Plain")
    e_short = register_escort(("TX",), "Short Pole", True, 170)
    e_rear = register_escort(("TX",), "Rear Plain")
    bundle = setup_booked_job(
        carrier,
        load_description="Tall wide load",
        width_inches=195,
        height_inches=180,
        map_min_clearance_inches=200,
    )
    leg = get_leg(bundle["leg"]["id"])
    assert leg["requires_height_pole"] is True

    resp1 = api.create_assignment(
        leg["id"], {"position": "FRONT", "escort_id": e_plain["id"]}, DISPATCHER
    )
    validate_error(resp1, ApiErrorId.ERR_HEIGHT_POLE_EQUIPMENT_MISSING)

    resp2 = api.create_assignment(
        leg["id"], {"position": "FRONT", "escort_id": e_short["id"]}, DISPATCHER
    )
    validate_error(resp2, ApiErrorId.ERR_HEIGHT_POLE_EQUIPMENT_MISSING)

    # The equipment rule is position-conditional: REAR on the same leg succeeds.
    resp3 = api.create_assignment(
        leg["id"], {"position": "REAR", "escort_id": e_rear["id"]}, DISPATCHER
    )
    created = validate_success(resp3, 201)
    assert created["assignment_status"] == "OFFERED"
    assert created["position"] == "REAR"


def test_selector_ranking_reliability_then_created_at(api):
    """PRD §3.5: "Eligible escorts are ranked by `reliability_score`
    descending, with ties broken by earlier `created_at`; the escort `id` is
    never consulted as a tiebreaker."
    PRD §3.7: "a fault share between 1 and 49 percent inclusive subtracts 10
    points"

    Design: Corner/calculations/selector_ranking_reliability_then_created_at
    """
    carrier = register_carrier(10_000_000, "Selector Co")
    # Distinct created_at instants so the created_at tie-break is observable.
    e_low = register_escort(("TX",), "Low")
    set_clock("2026-08-01T00:01:00Z")
    e_high = register_escort(("TX",), "High")
    set_clock("2026-08-01T00:02:00Z")
    e_late = register_escort(("TX",), "Late")

    # Deliver job J0 staffed by e_low, then dock e_low to 90 via a settled
    # 30%-fault incident tied to that completed assignment.
    bundle0 = setup_booked_job(carrier, load_description="J0")
    advance_to_cleared(bundle0)
    offer_and_accept(bundle0, e_low, "REAR")
    advance_to_scheduled(bundle0)
    advance_to_en_route(bundle0, "2026-08-10T09:00:00Z")
    advance_to_delivered(bundle0, "2026-08-10T10:00:00Z")
    asg0 = bundle0["assignments"][0]
    inc = report_incident(
        bundle0["job"]["id"],
        incident_type="EQUIPMENT_DAMAGE",
        description="Signage torn",
        claimed_amount_cents=100000,
        assignment_id=asg0["id"],
        reporter_user_id="disp-1",
        reporter_role="Dispatcher",
    )
    assess_incident(inc["id"], 30)
    settle_incident(inc["id"])
    assert read_escort(e_low["id"])["reliability_score"] == 90

    # Booked job B on a later window; auto-select twice (release between).
    bundle_b = setup_booked_job(
        carrier,
        load_description="B",
        window_start_at="2026-08-12T09:00:00Z",
        window_end_at="2026-08-12T13:00:00Z",
        planned_entry_at="2026-08-12T09:00:00Z",
        planned_exit_at="2026-08-12T13:00:00Z",
        clock_base="2026-08-10T10:00:00Z",
    )
    leg_b = bundle_b["leg"]["id"]

    pick1 = validate_success(
        api.create_assignment(leg_b, {"position": "REAR"}, DISPATCHER), 201
    )
    assert pick1["escort_id"] == e_high["id"], "reliability 100 beats 90"

    release_assignment(pick1["id"])

    pick2 = validate_success(
        api.create_assignment(leg_b, {"position": "REAR"}, DISPATCHER), 201
    )
    assert pick2["escort_id"] == e_high["id"], (
        "reliability tie 100 == 100 with the later-created escort; earlier created_at wins"
    )


def test_selector_empty_pool_returns_422(api):
    """PRD §3.5: "The top-ranked escort receives the offer; an empty pool is
    rejected with `ERR_NO_ELIGIBLE_ESCORT` (HTTP 422)."

    Design: Corner/calculations/selector_empty_pool_returns_422
    """
    carrier = register_carrier(10_000_000, "Empty Pool Co")
    register_escort(("OK",), "Okie")
    bundle = setup_booked_job(carrier, load_description="EP")

    resp = api.create_assignment(bundle["leg"]["id"], {"position": "REAR"}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_ESCORT)
    assert resp.status_code == 422
    rows, meta = validate_paginated(api.list_leg_assignments(bundle["leg"]["id"], DISPATCHER))
    assert rows == [] and meta["total_count"] == 0


def test_assignment_state_gates_rejected(api):
    """PRD §3.6: "a check-in is allowed while the assignment is `ACCEPTED` or
    `ACTIVE`; at any other status it is rejected with
    `ERR_ASSIGNMENT_INVALID_STATE`."
    PRD §3.5: "Acceptance requires the assignment to be `OFFERED` (else
    `ERR_ASSIGNMENT_INVALID_STATE`)"

    Design: Corner/state_machines/assignment_state_gates_rejected
    """
    carrier = register_carrier(10_000_000, "Assignment Gates Co")
    esc = register_escort(("TX",), "Rider G")
    bundle = setup_booked_job(carrier, load_description="G")
    asg = offer_assignment(bundle["leg"]["id"], "REAR", esc["id"])

    resp = api.create_checkin(asg["id"], make_escort_operator_headers(esc["id"]))
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_INVALID_STATE)

    accepted = accept_assignment(asg, esc["id"])
    resp2 = api.accept_assignment(asg["id"], make_escort_operator_headers(esc["id"]))
    validate_error(resp2, ApiErrorId.ERR_ASSIGNMENT_INVALID_STATE)
    assert get_assignment(asg["id"])["accepted_at"] == accepted["accepted_at"]
