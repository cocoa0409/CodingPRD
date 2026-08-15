"""Crew assignment legality: duty/rest computation, the re-vet loop on
itinerary change, crew status gating, and type qualification."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId,
    create_crew, add_leg, quote_trip, setup_quoted_trip,
    create_crew_assignment, vet_crew_assignment, create_vetted_crew,
    make_ops_admin_headers, make_dispatch_manager_headers,
    make_sales_agent_headers,
)

OPS_ADMIN = make_ops_admin_headers()
DISPATCH_MANAGER = make_dispatch_manager_headers()
SALES_AGENT = make_sales_agent_headers()


def _quoted_trip_with_leg(block_minutes, departure_at="2026-08-10T10:00:00Z",
                          customer_name="Cust C"):
    return setup_quoted_trip(legs=((block_minutes, "REVENUE", False),),
                             departure_at=departure_at, customer_name=customer_name)


# ---------------------------------------------------------------------------
# Queue A: cross_entity_state_dependency / vet_requires_crew_active
# ---------------------------------------------------------------------------

def test_vet_rejected_when_crew_member_suspended(api):
    """PRD §3.6: "Vetting is the legality check, executed by a
    `DispatchManager` on a `PROPOSED` assignment
    (`ERR_CREW_ASSIGNMENT_NOT_PROPOSED` otherwise) whose crew member is still
    `ACTIVE` (a suspended member yields `ERR_INVALID_STATE`)."

    Design: Difficulty/cross_entity_state_dependency/vet_requires_crew_active
    """
    crew = create_crew(name="Pic S")
    trip, _legs = _quoted_trip_with_leg(60, customer_name="Cust S")
    ca = create_crew_assignment(trip["id"], crew["id"])
    suspended = validate_success(api_client.patch_crew_member(
        crew["id"], {"status": "SUSPENDED"}, OPS_ADMIN), 200)
    assert suspended["status"] == "SUSPENDED"
    resp = api_client.vet_crew_assignment(ca["id"], DISPATCH_MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_vet_succeeds_after_crew_member_reactivated(api):
    """PRD §3.1: "A new crew member starts `ACTIVE`; an `OpsAdmin` may later
    patch its `status` to `SUSPENDED` and back to `ACTIVE`."
    PRD §3.6: "When both `duty_legal` and `rest_legal` come out true, the
    assignment advances to `VETTED`; when either fails, it advances to
    `FLAGGED_ILLEGAL` instead."

    Design: Difficulty/cross_entity_state_dependency/vet_requires_crew_active
    """
    crew = create_crew(name="Pic S")
    trip, _legs = _quoted_trip_with_leg(60, customer_name="Cust S")
    ca = create_crew_assignment(trip["id"], crew["id"])
    api_client.patch_crew_member(crew["id"], {"status": "SUSPENDED"}, OPS_ADMIN)
    validate_error(api_client.vet_crew_assignment(ca["id"], DISPATCH_MANAGER),
                   ApiErrorId.ERR_INVALID_STATE)
    reactivated = validate_success(api_client.patch_crew_member(
        crew["id"], {"status": "ACTIVE"}, OPS_ADMIN), 200)
    assert reactivated["status"] == "ACTIVE"
    vetted = vet_crew_assignment(ca["id"])
    assert vetted["status"] == "VETTED"
    assert vetted["duty_legal"] is True and vetted["rest_legal"] is True


# ---------------------------------------------------------------------------
# Queue A: non_linear_state_machine / crew_assignment_revet_loop
# ---------------------------------------------------------------------------

def test_itinerary_change_returns_vetted_assignment_to_proposed(api):
    """PRD §3.6: "Neither result is sticky: adding or deleting a quote leg on
    the trip, or requoting it, returns every `VETTED` or `FLAGGED_ILLEGAL`
    assignment on the trip to `PROPOSED` with `duty_legal`, `rest_legal`, and
    `vetted_at` cleared, forcing a fresh vet against the new itinerary."

    Design: Difficulty/non_linear_state_machine/crew_assignment_revet_loop
    """
    crew = create_crew(name="Pic Loop")
    trip, _legs = _quoted_trip_with_leg(120, customer_name="Cust L")
    ca = create_vetted_crew(trip["id"], crew["id"])
    assert ca["status"] == "VETTED"
    assert ca["planned_duty_minutes"] == 180, "120 block + 60 report/debrief"

    # Requote (itinerary reset) then add a 60-minute positioning leg.
    validate_success(api_client.requote_trip(
        trip["id"], {"expected_trip_request_version": trip["version"]}, SALES_AGENT), 200)
    add_leg(trip["id"], seq_no=2, block_minutes=60, leg_type="POSITIONING",
            origin_icao="KTEB", destination_icao="KLAX")
    ca_after = validate_success(api_client.get_crew_assignment(ca["id"], DISPATCH_MANAGER), 200)
    assert ca_after["status"] == "PROPOSED", "auto-reverted by the itinerary change"
    assert ca_after["duty_legal"] is None
    assert ca_after["rest_legal"] is None
    assert ca_after["vetted_at"] is None


def test_second_vet_recomputes_planned_duty_on_new_itinerary(api):
    """PRD §3.6: "The run computes the `planned_duty_minutes`: the sum of the
    planned `block_minutes` across the trip's legs plus 60 minutes of report
    and debrief allowance."

    Design: Difficulty/non_linear_state_machine/crew_assignment_revet_loop
    """
    crew = create_crew(name="Pic Loop")
    trip, _legs = _quoted_trip_with_leg(120, customer_name="Cust L")
    ca = create_vetted_crew(trip["id"], crew["id"])
    validate_success(api_client.requote_trip(
        trip["id"], {"expected_trip_request_version": trip["version"]}, SALES_AGENT), 200)
    add_leg(trip["id"], seq_no=2, block_minutes=60, leg_type="POSITIONING",
            origin_icao="KTEB", destination_icao="KLAX")
    quote_trip(trip["id"])
    revetted = vet_crew_assignment(ca["id"])
    assert revetted["status"] == "VETTED"
    assert revetted["planned_duty_minutes"] == 240, "180 block + 60 report/debrief"


# ---------------------------------------------------------------------------
# Queue A: boundary_precision_check / rest_gap_exactly_600_legal
# ---------------------------------------------------------------------------

def _two_trips_same_crew(trip_b_departure):
    """Crew member with trip A (dep 2026-08-10T10:00:00Z, 240min leg -> duty
    interval [09:30, 14:30]) already VETTED, plus trip B (60min leg) with a
    PROPOSED PIC assignment. Returns the PROPOSED assignment of trip B."""
    crew = create_crew(name="Pic R")
    trip_a, _la = setup_quoted_trip(legs=((240, "REVENUE", False),),
                                    departure_at="2026-08-10T10:00:00Z",
                                    customer_name="Cust RA")
    ca_a = create_vetted_crew(trip_a["id"], crew["id"])
    assert ca_a["status"] == "VETTED"
    trip_b, _lb = setup_quoted_trip(legs=((60, "REVENUE", False),),
                                    departure_at=trip_b_departure,
                                    customer_name="Cust RB")
    return create_crew_assignment(trip_b["id"], crew["id"])


def test_rest_gap_exactly_600_minutes_is_legal(api):
    """PRD §3.6: "Rest is legal when, against every other `VETTED` assignment
    of the same crew member, the gap between the two duty intervals is at
    least 600 minutes — ten hours — on both sides, where the gap is the later
    interval's start minus the earlier interval's end, floored at zero.
    Overlapping intervals therefore have a gap of zero and always violate
    rest, while a gap of exactly 600 minutes is legal."

    Design: Difficulty/boundary_precision_check/rest_gap_exactly_600_legal
    """
    # Trip B dep 2026-08-11T01:00 -> duty [00:30, 02:30]; gap from trip A's
    # 14:30 close is exactly 600 minutes.
    ca_b = _two_trips_same_crew("2026-08-11T01:00:00Z")
    vetted = vet_crew_assignment(ca_b["id"])
    assert vetted["rest_legal"] is True, "exactly 600 minutes satisfies >= 600"
    assert vetted["status"] == "VETTED"


def test_rest_gap_600_with_duty_legal_flags_recorded(api):
    """PRD §3.6: "Duty is legal when the planned duty is at most 840 minutes
    — fourteen hours — and exactly 840 minutes is legal."
    PRD §3.6: "The vetting run stamps `vetted_at` at the current clock and
    records both flags."

    Design: Difficulty/boundary_precision_check/rest_gap_exactly_600_legal
    """
    ca_b = _two_trips_same_crew("2026-08-11T01:00:00Z")
    vetted = vet_crew_assignment(ca_b["id"])
    assert vetted["duty_legal"] is True, "120 planned <= 840"
    assert vetted["planned_duty_minutes"] == 120
    assert vetted["vetted_at"], "vetting stamps vetted_at"


# ---------------------------------------------------------------------------
# Queue A: resource_temporal_overlap / crew_rest_minimum_gap_violation
# ---------------------------------------------------------------------------

def test_rest_gap_570_flags_assignment_illegal(api):
    """PRD §3.6: "Rest is legal when, against every other `VETTED` assignment
    of the same crew member, the gap between the two duty intervals is at
    least 600 minutes — ten hours — on both sides..."
    PRD §3.6: "When both `duty_legal` and `rest_legal` come out true, the
    assignment advances to `VETTED`; when either fails, it advances to
    `FLAGGED_ILLEGAL` instead."

    Design: Difficulty/resource_temporal_overlap/crew_rest_minimum_gap_violation
    """
    # Trip B dep 2026-08-11T00:30 -> duty [00:00, 02:00]; gap from trip A's
    # 14:30 close is 570 minutes: below the 600-minute rest floor.
    ca_b = _two_trips_same_crew("2026-08-11T00:30:00Z")
    resp = api_client.vet_crew_assignment(ca_b["id"], DISPATCH_MANAGER)
    vetted = validate_success(resp, expected_status=200)  # vet never errors on illegality
    assert vetted["status"] == "FLAGGED_ILLEGAL"
    assert vetted["rest_legal"] is False, "570 < 600"
    assert vetted["duty_legal"] is True, "120 <= 840"


def test_rest_violation_still_records_vetting_run_fields(api):
    """PRD §3.6: "The vetting run stamps `vetted_at` at the current clock and
    records both flags. When both `duty_legal` and `rest_legal` come out
    true, the assignment advances to `VETTED`; when either fails, it advances
    to `FLAGGED_ILLEGAL` instead."
    PRD §3.6: "a trip's duty interval opens 30 minutes before its
    `departure_at` (the report allowance) and closes 30 minutes after the
    planned arrival implied by the total block time (the debrief allowance)."

    Design: Difficulty/resource_temporal_overlap/crew_rest_minimum_gap_violation
    """
    ca_b = _two_trips_same_crew("2026-08-11T00:30:00Z")
    flagged = vet_crew_assignment(ca_b["id"])
    assert flagged["status"] == "FLAGGED_ILLEGAL"
    assert flagged["planned_duty_minutes"] == 120, "60 block + 60 report/debrief"
    assert flagged["vetted_at"], "the run stamps vetted_at even on failure"


# ---------------------------------------------------------------------------
# Queue B: state_machines / vet_from_vetted_rejected
# ---------------------------------------------------------------------------

def test_vet_from_vetted_rejected(api):
    """PRD §3.6: "Vetting is the legality check, executed by a
    `DispatchManager` on a `PROPOSED` assignment
    (`ERR_CREW_ASSIGNMENT_NOT_PROPOSED` otherwise) whose crew member is still
    `ACTIVE` (a suspended member yields `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/vet_from_vetted_rejected
    """
    crew = create_crew(name="Pic VV")
    trip, _legs = _quoted_trip_with_leg(60, customer_name="Cust VV")
    ca = create_vetted_crew(trip["id"], crew["id"])
    assert ca["status"] == "VETTED"
    resp = api_client.vet_crew_assignment(ca["id"], DISPATCH_MANAGER)
    validate_error(resp, ApiErrorId.ERR_CREW_ASSIGNMENT_NOT_PROPOSED)


# ---------------------------------------------------------------------------
# Queue B: errors / crew_not_type_qualified_rejected
# ---------------------------------------------------------------------------

def test_crew_not_type_qualified_rejected(api):
    """PRD §3.6: "The trip must be `QUOTED` or `BOOKED` — any other status
    yields `ERR_INVALID_STATE` — and the crew member must be `ACTIVE` and
    type-qualified, meaning the trip's `requested_category` appears in the
    member's `qualified_categories`; an unqualified member is rejected with
    `ERR_CREW_NOT_TYPE_QUALIFIED`."

    Design: Corner/errors/crew_not_type_qualified_rejected
    """
    crew = create_crew(name="Pic TQ", qualified_categories=["LIGHT_JET"])
    trip, _legs = setup_quoted_trip(legs=((60, "REVENUE", False),), category="HEAVY_JET",
                                    customer_name="Cust TQ")
    resp = api_client.create_crew_assignment(
        {"trip_request_id": trip["id"], "crew_member_id": crew["id"], "duty_role": "PIC"},
        DISPATCH_MANAGER)
    validate_error(resp, ApiErrorId.ERR_CREW_NOT_TYPE_QUALIFIED)
