"""Actions gated on a different entity's state (PRD §3.5, §3.6).

Two gates in opposite directions.  A set job whose own row is perfectly legal
cannot be dispatched while the order's site sits in `READINESS_FAILED`, and the
identical dispatch succeeds once the site is re-inspected clean with no change
to the job at all.  A corridor leg whose own row is equally legal cannot roll
while a crew holding a reserved assignment on it has been pushed over its
reserved-minute ceiling, and the identical departure succeeds once the
reservation is released and the crew's ledger is recomputed to zero.
"""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    book_set_job,
    inspect_site,
    make_transport_manager_headers,
    pay_and_issue_permit,
    read_escort_assignment,
    read_escort_crew,
    read_permit,
    read_route_leg,
    read_section,
    read_set_job,
    read_site,
    register_set_crew,
    register_site,
    release_escort,
    reserve_escort,
    setup_delivered_order,
    setup_leg_awaiting_escorts,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["network_admin_headers"]

RESERVATION_OPEN = "2026-08-03T06:00:00.000Z"
RESERVATION_CLOSE = "2026-08-03T14:00:00.000Z"


def _order_with_failed_site_and_scheduled_job():
    """A delivered single-section order whose site failed on the pier plan.

    The pad and the utilities pass and the pier plan lays out the six piers the
    single section demands, but the inspector fails the plan drawing, so exactly
    one of the three readiness dimensions is unsatisfied.  A set job is then
    booked against the order and left in `SCHEDULED`.
    """
    scenario = setup_delivered_order(section_count=1)
    site = register_site(scenario["order"]["id"], pad_type="RUNNER", pier_count=6)
    scenario["site"] = inspect_site(site["id"], pier_plan_pass=False)
    scenario["set_crew"] = register_set_crew()
    scenario["set_job"] = book_set_job(
        scenario["order"]["id"], scenario["set_crew"]["id"]
    )
    return scenario


def _issued_leg_with_an_overbooked_escort_crew():
    """An issued AZ permit with one scheduled leg and one overbooked crew.

    The AZ evaluation of a 168-inch-wide, 150-inch-tall floor on a single leg
    demands no escorts at all, so the permit is funded at its provisional fee and
    issued with no reservation on file; the reservation added afterwards is
    therefore optional coverage.  Its eight-hour window books 480 minutes against
    a crew whose ceiling is 300, which flips the crew to `OVERBOOKED`.
    """
    scenario = setup_leg_awaiting_escorts(
        escort_crews=[
            {
                "vendor_name": "Thin Margin Escort",
                "endorsement_class": "STANDARD",
                "buffer_minutes": 0,
                "max_reserved_minutes": 300,
            }
        ],
    )
    pay_and_issue_permit(scenario["permit"]["id"], scenario["hauler"]["id"])
    scenario["escort_crew"] = scenario["escort_crews"][0]
    scenario["assignment"] = reserve_escort(
        scenario["leg"]["id"],
        scenario["escort_crew"]["id"],
        scenario["hauler"]["id"],
        role="ESCORT",
        window_start=RESERVATION_OPEN,
        window_end=RESERVATION_CLOSE,
    )
    scenario["permit"] = read_permit(scenario["permit"]["id"])
    return scenario


def test_dispatch_refused_while_the_order_site_sits_in_readiness_failed():
    """PRD §3.6: "A site row exists for the job's order — an order with no site at
    all yields `ERR_SITE_NOT_FOUND` — and that site's `readiness_status` is
    `READY`, failing which the refusal is `ERR_SITE_NOT_READY`."
    PRD §3.3: "The pier-plan dimension is satisfied only when the inspector
    passes the pier plan **and** the site's `pier_count` is at least six piers per
    declared section — so a two-section home needs at least twelve piers laid out,
    and a four-section home at least twenty-four, regardless of what the inspector
    says about the plan drawing."
    PRD §3.3: "`blocking_defect_count` is then the number of those three
    dimensions that are **not** satisfied, so it always lands between 0 and 3
    inclusive, and the site reads `READY` when the count is 0 and
    `READINESS_FAILED` otherwise."

    Design: Difficulty/cross_entity_state_dependency/set_job_dispatch_depends_on_site_readiness_state
    """
    scenario = _order_with_failed_site_and_scheduled_job()
    site = read_site(scenario["site"]["id"])

    assert site["readiness_status"] == "READINESS_FAILED", (
        "a failed pier-plan dimension leaves the site in READINESS_FAILED, got "
        f"{site['readiness_status']}"
    )
    assert site["blocking_defect_count"] == 1, (
        "exactly one of the three readiness dimensions is unsatisfied, got "
        f"{site['blocking_defect_count']}"
    )

    response = api_client.dispatch_set_job(scenario["set_job"]["id"], {}, ADMIN)
    validate_error(response, ApiErrorId.ERR_SITE_NOT_READY.value, 409)

    job = read_set_job(scenario["set_job"]["id"])
    assert job["progress_status"] == "SCHEDULED", (
        "the refused dispatch leaves the job's progress dimension at SCHEDULED, got "
        f"{job['progress_status']}"
    )


def test_dispatch_accepted_after_the_site_is_re_inspected_clean():
    """PRD §3.3: "From `READINESS_FAILED` a clean evaluation moves the site
    `READINESS_FAILED → READY`, writing `blocking_defect_count` as 0, incrementing
    `inspection_round` by 1, stamping `last_inspector_user_id`, and re-deriving the
    order's posture."
    PRD §3.6: "Sending the crew to site is likewise a `NetworkAdmin` action, and
    it moves the job's progress dimension `SCHEDULED → DISPATCHED`."
    PRD §3.5: "Whether the floor is now home depends on the leg's position: when
    the arriving leg carries the highest `sequence_no` among that permit's legs
    whose `status` is `SCHEDULED`, `IN_TRANSIT` or `ARRIVED`, the floor moves
    `IN_TRANSIT → DELIVERED`; arriving on any earlier leg leaves the floor in
    `IN_TRANSIT`."

    Design: Difficulty/cross_entity_state_dependency/set_job_dispatch_depends_on_site_readiness_state
    """
    scenario = _order_with_failed_site_and_scheduled_job()

    refused = api_client.dispatch_set_job(scenario["set_job"]["id"], {}, ADMIN)
    validate_error(refused, ApiErrorId.ERR_SITE_NOT_READY.value, 409)

    inspect_site(scenario["site"]["id"])
    site = read_site(scenario["site"]["id"])
    assert site["readiness_status"] == "READY", (
        "a clean re-inspection moves the site to READY, got "
        f"{site['readiness_status']}"
    )
    assert site["blocking_defect_count"] == 0, (
        f"a clean re-inspection writes a defect count of 0, got {site['blocking_defect_count']}"
    )

    job = validate_success(
        api_client.dispatch_set_job(scenario["set_job"]["id"], {}, ADMIN), 200
    )
    assert job["progress_status"] == "DISPATCHED", (
        "the identical dispatch now moves the job to DISPATCHED, got "
        f"{job['progress_status']}"
    )

    section = read_section(scenario["sections"][0]["id"])
    assert section["transit_status"] == "DELIVERED", (
        f"the floor was already on the pad, got {section['transit_status']}"
    )


def test_departure_refused_while_a_reserved_crew_is_overbooked():
    """PRD §3.5: "Five conditions guard it: the leg is `SCHEDULED`, the acting
    `X-User-ID` equals the leg's `hauler_id`, the leg's permit is in `ISSUED`
    status, the carrier's `status` is `ACTIVE`, and every reserved escort
    assignment on the leg belongs to a crew whose `status` is `AVAILABLE`."
    PRD §2.10: "Violation: `ERR_ESCORT_CREW_OVERBOOKED` (422). The second scope is
    a cross-entity dependency: a leg may not roll while any reserved assignment on
    it belongs to an overbooked crew."
    PRD §3.1: "A new crew starts with `reserved_minutes` at 0 and `status`
    `AVAILABLE`, and its `status` becomes `OVERBOOKED` the moment its booked
    `reserved_minutes` exceeds `max_reserved_minutes` — a crew sitting exactly at
    the ceiling is still `AVAILABLE`."
    PRD §3.5: "A reservation's own `reserved_minutes` is computed once, at
    creation, as the number of minutes between `window_start` and `window_end` —
    the elapsed seconds divided by sixty, rounded half up to a whole minute — and
    is frozen from then on."

    Design: Difficulty/cross_entity_state_dependency/route_leg_depart_depends_on_escort_crew_status
    """
    scenario = _issued_leg_with_an_overbooked_escort_crew()

    assert scenario["permit"]["escort_count_required"] == 0, (
        "an AZ permit for a 168-inch-wide floor demands no escorts, got "
        f"{scenario['permit']['escort_count_required']}"
    )
    assignment = read_escort_assignment(scenario["assignment"]["id"])
    assert assignment["reserved_minutes"] == 480, (
        "an eight-hour window freezes at 480 minutes, got "
        f"{assignment['reserved_minutes']}"
    )
    crew = read_escort_crew(scenario["escort_crew"]["id"])
    assert crew["reserved_minutes"] == 480, (
        f"the crew's ledger is the single 480-minute row, got {crew['reserved_minutes']}"
    )
    assert crew["status"] == "OVERBOOKED", (
        "480 booked minutes exceed the 300-minute ceiling, got " f"{crew['status']}"
    )

    response = api_client.depart_route_leg(
        scenario["leg"]["id"],
        {},
        make_transport_manager_headers(scenario["hauler"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_ESCORT_CREW_OVERBOOKED.value, 422)

    leg = read_route_leg(scenario["leg"]["id"])
    assert leg["status"] == "SCHEDULED", (
        f"the refused departure leaves the leg SCHEDULED, got {leg['status']}"
    )


def test_departure_accepted_once_the_overbooking_reservation_is_released():
    """PRD §3.5: "A carrier may release a reservation it owns while the
    reservation is `RESERVED` and the underlying leg is in `SCHEDULED`,
    `CANCELLED` or `HAULER_HOLD`, moving it `RESERVED → RELEASED`; the acting
    `X-User-ID` must equal the leg's `hauler_id`."
    PRD §3.5: "A crew's `reserved_minutes` is never incremented; it is recomputed
    in full as the sum of the frozen `reserved_minutes` of every one of that crew's
    reservations currently in `RESERVED` status."
    PRD §3.5: "After every recomputation the crew's `status` is refreshed:
    `OVERBOOKED` when the total exceeds `max_reserved_minutes`, `AVAILABLE`
    otherwise."
    PRD §3.5: "Departure moves the permit's floor `DISPATCH_READY → IN_TRANSIT`,
    raises both rows' `version`, and re-derives the order's posture."

    Design: Difficulty/cross_entity_state_dependency/route_leg_depart_depends_on_escort_crew_status
    """
    scenario = _issued_leg_with_an_overbooked_escort_crew()
    carrier = make_transport_manager_headers(scenario["hauler"]["id"])

    refused = api_client.depart_route_leg(scenario["leg"]["id"], {}, carrier)
    validate_error(refused, ApiErrorId.ERR_ESCORT_CREW_OVERBOOKED.value, 422)

    release_escort(scenario["assignment"]["id"], scenario["hauler"]["id"])

    assignment = read_escort_assignment(scenario["assignment"]["id"])
    assert assignment["status"] == "RELEASED", (
        f"the released reservation reads RELEASED, got {assignment['status']}"
    )
    crew = read_escort_crew(scenario["escort_crew"]["id"])
    assert crew["reserved_minutes"] == 0, (
        "no reservation of the crew survives in RESERVED status, so its ledger is "
        f"0, got {crew['reserved_minutes']}"
    )
    assert crew["status"] == "AVAILABLE", (
        f"0 booked minutes are within the ceiling, got {crew['status']}"
    )

    leg = validate_success(
        api_client.depart_route_leg(scenario["leg"]["id"], {}, carrier), 200
    )
    assert leg["status"] == "IN_TRANSIT", (
        f"the identical departure now moves the leg to IN_TRANSIT, got {leg['status']}"
    )

    section = read_section(scenario["section"]["id"])
    assert section["transit_status"] == "IN_TRANSIT", (
        "departure carries the floor DISPATCH_READY -> IN_TRANSIT, got "
        f"{section['transit_status']}"
    )
