"""Edges the declared lifecycles do not contain, and the guards on the ones they do."""

from test_helpers import (
    CLOCK_DATE_T0,
    CLOCK_T0,
    CREW_COORDINATOR,
    DIRECTOR,
    INTAKE_ADVISOR,
    PERMIT_OFFICER,
    SHOP_ESTIMATOR,
    assert_facility_state,
    assert_no_version_or_updated_at,
    assert_permit_decision,
    assert_supplement_state,
    assert_technician_pay,
    assert_ticket_pay,
    assert_warranty_minted,
    billing_action,
    bring_vehicle_to,
    close_event,
    commission_facility,
    create_deployment,
    create_facility,
    create_storm_event,
    create_technician,
    crew_deployment_payload,
    crew_deployment_status_payload,
    damage_line_payload,
    demobilize_event,
    facility_payload,
    file_supplement,
    make_insurer_adjuster_headers,
    permit_decision_payload,
    read_deployment,
    read_event,
    read_facility,
    read_insurer,
    read_rate_agreement,
    read_supplement,
    read_technician,
    read_vehicle,
    read_vehicle_version,
    read_work_ticket,
    release_vehicle,
    review_supplement,
    set_clock,
    set_deployment_status,
    setup_operational_facility,
    storm_event_decision_payload,
    supplement_payload,
    supplement_review_payload,
    supplement_revise_payload,
    target_storm_event,
    tech_headers,
    tech_id,
    validate_error,
    validate_paginated,
    validate_success,
    work_ticket_payload,
)


def test_an_approved_permit_refuses_both_a_replay_and_a_reversal(api):
    """PRD §3.2: "A `PermitOfficer` — and nobody else, since the party that
    applies for a permit can never be the party that decides it — records a
    `decision` of `APPROVE` or `DENY` on a permit that is still `PENDING`; a
    decision on any other status is rejected with `ERR_PERMIT_ALREADY_DECIDED`."

    PRD §3.2: "An `APPROVE` decision must supply both `valid_from` and
    `valid_to`, with `valid_from` no later than `valid_to`, and both dates are
    persisted on the permit as the officer supplied them; the permit moves
    `PENDING` → `APPROVED` and `decided_at` is stamped from the logical clock."

    PRD §2.11: "**Permit still pending** — `ERR_PERMIT_ALREADY_DECIDED` (409), on
    `POST /hail-ops/permits/{id}/decision`."

    Design: Corner/state_machines/permit_second_decision_rejected_after_approval
    """
    scenario = setup_operational_facility(
        api, commission=False, activate_event=False, technicians=()
    )
    licence_id = scenario["permits"]["TEMP_BUSINESS_LICENSE"]["id"]

    replay = api.decide_permit(
        licence_id,
        permit_decision_payload("APPROVE", "2026-08-10", "2026-10-31"),
        PERMIT_OFFICER,
    )
    validate_error(replay, "ERR_PERMIT_ALREADY_DECIDED", 409)

    flip = api.decide_permit(licence_id, permit_decision_payload("DENY"), PERMIT_OFFICER)
    validate_error(flip, "ERR_PERMIT_ALREADY_DECIDED", 409)

    permits, meta = validate_paginated(
        api.list_facility_permits(
            scenario["facility_id"], DIRECTOR, {"permit_type": "TEMP_BUSINESS_LICENSE"}
        )
    )
    assert meta["total_count"] == 1
    assert_permit_decision(
        permits[0],
        status="APPROVED",
        valid_from="2026-08-01",
        valid_to="2026-09-30",
        decided_at=CLOCK_T0,
    )
    assert_no_version_or_updated_at(permits[0])


def test_only_the_declared_event_edges_exist_and_the_gate_guards_children(api):
    """PRD §2.11: "**Storm event state** — `ERR_INVALID_STORM_EVENT_STATE` (409),
    on the four storm-event lifecycle calls (`POST
    /hail-ops/storm-events/{id}/decision`, `/activate`, `/demobilize`, `/close`),
    on `POST /hail-ops/facilities`, and on `POST
    /hail-ops/rate-agreements/{id}/activate`."

    PRD §3.1: "Both branches require the event to still be `EVALUATING`; a second
    decision on an already-decided event is rejected with
    `ERR_INVALID_STORM_EVENT_STATE`."

    PRD §3.2: "Attempting to stand up a facility against an event that is neither
    `TARGETED` nor `ACTIVE` is rejected with `ERR_INVALID_STORM_EVENT_STATE`."

    Design: Corner/state_machines/storm_event_transitions_outside_the_declared_map_are_rejected
    """
    set_clock(api, CLOCK_T0)
    live = create_storm_event(api)
    declined = create_storm_event(
        api,
        name="Salina Marginal Cell",
        max_hail_size_mm=45,
        swath_area_km2=410,
        vehicle_population_estimate=30000,
        competitor_shop_count=2,
        first_hail_at="2026-08-04T23:00:00Z",
    )
    validate_success(
        api.decide_storm_event(
            declined["id"], storm_event_decision_payload("DECLINE"), DIRECTOR
        )
    )

    # An `EVALUATING` event has no activate edge and no close edge.
    validate_error(
        api.activate_storm_event(live["id"], DIRECTOR),
        "ERR_INVALID_STORM_EVENT_STATE",
        409,
    )
    validate_error(
        api.close_storm_event(live["id"], DIRECTOR),
        "ERR_INVALID_STORM_EVENT_STATE",
        409,
    )

    targeted = validate_success(
        api.decide_storm_event(
            live["id"], storm_event_decision_payload("TARGET"), DIRECTOR
        )
    )
    assert targeted["status"] == "TARGETED"

    validate_error(
        api.decide_storm_event(
            live["id"], storm_event_decision_payload("TARGET"), DIRECTOR
        ),
        "ERR_INVALID_STORM_EVENT_STATE",
        409,
    )
    validate_error(
        api.demobilize_storm_event(live["id"], DIRECTOR),
        "ERR_INVALID_STORM_EVENT_STATE",
        409,
    )
    # The same gate refuses a child of a terminal event.
    validate_error(
        api.create_facility(
            facility_payload(
                declined["id"],
                name="Declined Event Lot",
                address="9 Nowhere Rd",
                staging_slot_count=2,
            ),
            DIRECTOR,
        ),
        "ERR_INVALID_STORM_EVENT_STATE",
        409,
    )

    assert read_event(api, live["id"])["status"] == "TARGETED"
    assert read_event(api, live["id"])["demobilized_at"] is None
    assert read_event(api, declined["id"])["status"] == "DECLINED"
    _, lots = validate_paginated(
        api.list_facilities(DIRECTOR, {"storm_event_id": declined["id"]})
    )
    assert lots["total_count"] == 0


def test_activation_waits_on_a_commissioned_lot_not_on_the_events_own_state(api):
    """PRD §3.1: "Activation requires the event to be `TARGETED` and requires at
    least one facility of the event to have `status` equal to `COMMISSIONED`; with
    no commissioned site the request is rejected with
    `ERR_NO_COMMISSIONED_FACILITY`."

    PRD §2.6: "Otherwise, if the facility's `status` is `SETUP`, posture is
    `RESTRICTED`."

    PRD §3.2: "On success the facility becomes `COMMISSIONED`, `commissioned_at`
    is stamped from the logical clock, posture is recomputed, and `version`
    increments by one."

    Design: Corner/state_machines/event_activation_blocked_until_a_facility_is_commissioned
    """
    scenario = setup_operational_facility(api, commission=False, activate_event=False)
    assert read_facility(api, scenario["facility_id"])["posture"] == "RESTRICTED"

    too_early = api.activate_storm_event(scenario["event_id"], DIRECTOR)
    validate_error(too_early, "ERR_NO_COMMISSIONED_FACILITY", 409)
    assert read_event(api, scenario["event_id"])["status"] == "TARGETED"

    facility = commission_facility(api, scenario["facility_id"])
    assert_facility_state(facility, status="COMMISSIONED", posture="OPEN")
    assert facility["commissioned_at"] == CLOCK_T0

    activated = validate_success(
        api.activate_storm_event(scenario["event_id"], DIRECTOR)
    )
    assert activated["status"] == "ACTIVE"

    facility = read_facility(api, scenario["facility_id"])
    assert facility["staging_slots_free"] == 6
    assert facility["staging_occupancy_ratio"] == 0.0


def test_commissioning_a_commissioned_lot_writes_nothing(api):
    """PRD §3.2: "The facility's own `status` must be `SETUP`, or the request is
    rejected with `ERR_INVALID_FACILITY_STATE`."

    PRD §2.11: "**Facility state for commissioning** — `ERR_INVALID_FACILITY_STATE`
    (409), on `POST /hail-ops/facilities/{id}/commission`."

    PRD §2.5: "Most resources additionally carry an `updated_at` timestamp,
    refreshed on every mutation, and a `version` integer that starts at 1 on
    creation and increments by exactly one on every mutation of that resource —
    including mutations that only rewrite derived money or counter fields."

    Design: Corner/state_machines/facility_commission_is_not_idempotent_and_second_attempt_rejected
    """
    scenario = setup_operational_facility(api, activate_event=False)
    before = read_facility(api, scenario["facility_id"])
    assert before["status"] == "COMMISSIONED"

    replay = api.commission_facility(scenario["facility_id"], DIRECTOR)
    validate_error(replay, "ERR_INVALID_FACILITY_STATE", 409)

    after = read_facility(api, scenario["facility_id"])
    assert after["status"] == "COMMISSIONED"
    assert after["commissioned_at"] == CLOCK_T0
    assert after["version"] == before["version"]
    assert after["posture"] == "OPEN"


def test_a_cancelled_stint_no_longer_counts_as_crew_on_the_site(api):
    """PRD §3.2: "And at least one crew deployment on the site must be
    `CONFIRMED` or `ON_SITE` with a technician whose `license_state_code` equals
    the facility's `state_code` and whose `license_expires_at` is no earlier than
    the current clock date; without such a deployment the rejection is
    `ERR_NO_LICENSED_TECHNICIAN`."

    PRD §3.3: "Moving `CONFIRMED` → `CANCELLED` requires only that the deployment
    be `CONFIRMED`; the deployment becomes terminal, its `version` increments, the
    housing unit's `occupied_beds` and `bed_nights_committed` are recomputed — the
    cancelled interval drops out of both sums — and the technician's
    `deployment_state` is refreshed."

    PRD §2.6: "Otherwise, if the count of on-site licensed technicians is zero,
    posture is `RESTRICTED`."

    Design: Corner/state_machines/commission_requires_a_live_licensed_deployment_not_a_cancelled_one
    """
    scenario = setup_operational_facility(
        api, commission=False, activate_event=False, on_site=()
    )
    traveller_id = tech_id(scenario, "TA")
    cancelled = set_deployment_status(
        api, scenario["deployments"]["TA"]["id"], "CANCELLED"
    )

    assert read_technician(api, traveller_id)["deployment_state"] == "AVAILABLE"
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["actual_end_date"] is None
    assert cancelled["effective_end_date"] == "2026-09-15"

    unstaffed = api.commission_facility(scenario["facility_id"], DIRECTOR)
    validate_error(unstaffed, "ERR_NO_LICENSED_TECHNICIAN", 409)

    # The cancelled interval no longer collides, so the same dates are free.
    replacement = validate_success(
        api.create_crew_deployment(
            crew_deployment_payload(
                traveller_id, scenario["facility_id"], "2026-08-05", "2026-09-15"
            ),
            CREW_COORDINATOR,
        ),
        201,
    )
    assert replacement["status"] == "CONFIRMED"
    assert replacement["pay_split_pct_snapshot"] == 0.45
    assert read_technician(api, traveller_id)["deployment_state"] == "DEPLOYED"

    facility = commission_facility(api, scenario["facility_id"])
    assert facility["status"] == "COMMISSIONED"
    # Confirmed is not the same as arrived, so the lot stays restricted.
    assert facility["posture"] == "RESTRICTED"


def test_the_deployment_lifecycle_runs_one_way_only(api):
    """PRD §3.3: "Moving `ON_SITE` → `ENDED` requires the deployment to be
    `ON_SITE`; it writes `actual_end_date` from the current clock date, which
    immediately becomes the `effective_end_date`, increments `version`, recomputes
    the housing unit's `occupied_beds` and `bed_nights_committed` from the
    shortened interval, and refreshes the technician's `deployment_state`."

    PRD §3.3: "Any of these three requested from a status that does not allow it
    is rejected with `ERR_INVALID_LIFECYCLE_STATE`."

    PRD §2.11: "**Deployment and ticket lifecycle** — `ERR_INVALID_LIFECYCLE_STATE`
    (409), on `POST /hail-ops/crew-deployments/{id}/status` and `POST
    /hail-ops/work-tickets/{id}/submit`."

    Design: Corner/state_machines/crew_deployment_status_moves_outside_the_map_are_rejected
    """
    set_clock(api, CLOCK_T0)
    event = create_storm_event(api)
    target_storm_event(api, event["id"])
    facility = create_facility(api, event["id"])
    traveller = create_technician(api, "TA")
    deployment = create_deployment(api, traveller["id"], facility["id"])

    arrived = set_deployment_status(api, deployment["id"], "ON_SITE")
    assert arrived["status"] == "ON_SITE"

    validate_error(
        api.set_crew_deployment_status(
            deployment["id"],
            crew_deployment_status_payload("CANCELLED"),
            CREW_COORDINATOR,
        ),
        "ERR_INVALID_LIFECYCLE_STATE",
        409,
    )

    ended = set_deployment_status(api, deployment["id"], "ENDED")
    assert ended["status"] == "ENDED"
    assert ended["actual_end_date"] == CLOCK_DATE_T0
    assert ended["effective_end_date"] == CLOCK_DATE_T0

    validate_error(
        api.set_crew_deployment_status(
            deployment["id"],
            crew_deployment_status_payload("ON_SITE"),
            CREW_COORDINATOR,
        ),
        "ERR_INVALID_LIFECYCLE_STATE",
        409,
    )

    settled = read_deployment(api, deployment["id"])
    assert settled["end_date"] == "2026-09-15"
    assert read_technician(api, traveller["id"])["deployment_state"] == "AVAILABLE"
    _, ended_meta = validate_paginated(
        api.list_crew_deployments(
            CREW_COORDINATOR, {"technician_id": traveller["id"], "status": "ENDED"}
        )
    )
    assert ended_meta["total_count"] == 1


def _a_car_walked_all_the_way_to_ready(api):
    """One conventional repair inspected and passed, waiting only for release."""
    scenario = setup_operational_facility(api, technicians=("TA", "TI"))
    car = bring_vehicle_to(
        api,
        scenario,
        "READY",
        damage_profile="single_panel_conventional",
        rental_required=False,
    )
    return scenario, car


def test_release_mints_one_warranty_and_then_the_car_is_untouchable(api):
    """PRD §3.9: "A released repair mints a warranty: the facility's
    `warranty_counter` is incremented first, then the vehicle's `warranty_number`
    is minted as the literal prefix `PDR-` followed by that counter value
    zero-padded to four digits, and `warranty_expires_at` is set to `released_at`
    plus 90 days."

    PRD §2.11: "**Vehicle repair dimension** — `ERR_INVALID_VEHICLE_REPAIR_STATE`
    (409), on `POST /hail-ops/vehicles/{id}/estimate`, `/triage`, `/start-repair`,
    `/release` and `/billing`, and on `POST /hail-ops/damage-lines`, `POST
    /hail-ops/work-tickets`, `POST /hail-ops/quality-inspections` and `POST
    /hail-ops/supplements`."

    PRD §3.7: "Hop one: every work ticket of that vehicle whose `status` is
    `SUBMITTED` moves `SUBMITTED` → `APPROVED`, which is terminal, receiving
    `payable_flat_cents`, `payable_pooled_cents`, `payable_cents` and
    `pay_model_applied` in the process, each with a `version` increment."

    Design: Corner/state_machines/released_vehicle_is_terminal_and_rejects_every_further_repair_operation
    """
    scenario, car = _a_car_walked_all_the_way_to_ready(api)
    vehicle_id = car["vehicle_id"]

    released = release_vehicle(api, vehicle_id)
    assert released["repair_status"] == "RELEASED"
    assert released["released_at"] == CLOCK_T0
    assert_warranty_minted(
        released, warranty_number="PDR-0001", warranty_expires_at="2026-11-03T08:00:00Z"
    )
    assert released["rental_days_billed"] == 0
    assert released["shop_absorbed_rental_cents"] == 0
    assert released["billing_status"] == "AUTHORIZED"
    assert released["net_billable_cents"] == 80850

    for refused in (
        api.release_vehicle(vehicle_id, INTAKE_ADVISOR),
        api.estimate_vehicle(vehicle_id, SHOP_ESTIMATOR),
        api.triage_vehicle(vehicle_id, SHOP_ESTIMATOR),
        api.start_vehicle_repair(vehicle_id, SHOP_ESTIMATOR),
        api.create_damage_line(
            damage_line_payload(
                vehicle_id,
                panel_code="ROOF",
                dent_count=15,
                dent_size_class="DIME",
                conventional_labor_hours=12.0,
                conventional_paint_materials_cents=26000,
            ),
            INTAKE_ADVISOR,
        ),
        api.create_work_ticket(
            work_ticket_payload(
                vehicle_id,
                tech_id(scenario, "TA"),
                labor_units=1.0,
                dents_repaired=3,
            ),
            tech_headers(scenario, "TA"),
        ),
    ):
        validate_error(refused, "ERR_INVALID_VEHICLE_REPAIR_STATE", 409)

    facility = read_facility(api, scenario["facility_id"])
    assert facility["warranty_counter"] == 1
    assert facility["staging_slots_occupied"] == 0
    assert facility["staging_slots_free"] == 6
    assert facility["posture"] == "OPEN"

    ticket = read_work_ticket(api, car["work_tickets"][0]["id"])
    assert_ticket_pay(
        ticket,
        payable_flat_cents=19058,
        payable_pooled_cents=21175,
        payable_cents=19058,
        pay_model_applied="FLAT",
        status="APPROVED",
    )
    assert_technician_pay(
        read_technician(api, tech_id(scenario, "TA")),
        accrued_pay_cents=19058,
        approved_ticket_count=1,
    )
    assert car["inspection"]["result"] == "PASS"
    assert car["inspection"]["rework_index"] == 0
    _, lines = validate_paginated(
        api.list_vehicle_damage_lines(vehicle_id, SHOP_ESTIMATOR)
    )
    assert lines["total_count"] == 1


def test_a_denied_supplement_is_closed_but_may_still_be_cited(api):
    """PRD §3.8: "`DENY` moves `UNDER_REVIEW` → `DENIED`, terminal, forces
    `approved_amount_cents` to 0, stamps `decided_at` and increments `version`;
    nothing cascades, because a denied supplement never entered the ledger."

    PRD §3.8: "And when `supersedes_supplement_id` is supplied, its target must be
    a supplement whose `status` is `DENIED` or `WITHDRAWN`; pointing at a live or
    already-approved filing is rejected with `ERR_INVALID_SUPPLEMENT_STATE`."

    PRD §3.8: "A new supplement copies the vehicle's `pinned_rate_agreement_id`
    into its own `rate_agreement_id`, starts at `round_index` 1, and increments the
    vehicle's `version` by one."

    Design: Corner/state_machines/denied_supplement_rejects_further_review_revise_and_bad_supersede
    """
    scenario = setup_operational_facility(api)
    car = bring_vehicle_to(
        api,
        scenario,
        "TRIAGED",
        damage_profile="single_panel_conventional",
        rental_required=False,
    )
    first = file_supplement(api, car["vehicle_id"], 20000)
    denied = review_supplement(api, first["id"], scenario["insurer_id"], "DENY")
    assert denied["status"] == "DENIED"

    validate_error(
        api.review_supplement(
            first["id"],
            supplement_review_payload("APPROVE"),
            make_insurer_adjuster_headers(scenario["insurer_id"]),
        ),
        "ERR_INVALID_SUPPLEMENT_STATE",
        409,
    )
    validate_error(
        api.revise_supplement(
            first["id"], supplement_revise_payload("REVISE", 12000), SHOP_ESTIMATOR
        ),
        "ERR_INVALID_SUPPLEMENT_STATE",
        409,
    )

    second = validate_success(
        api.create_supplement(
            supplement_payload(
                car["vehicle_id"],
                18000,
                read_vehicle_version(api, car["vehicle_id"]),
                supersedes_supplement_id=first["id"],
            ),
            SHOP_ESTIMATOR,
        ),
        201,
    )
    assert second["status"] == "UNDER_REVIEW"
    assert second["supersedes_supplement_id"] == first["id"]
    assert second["round_index"] == 1

    # The replacement is still live, so it cannot itself be superseded.
    validate_error(
        api.create_supplement(
            supplement_payload(
                car["vehicle_id"],
                5000,
                read_vehicle_version(api, car["vehicle_id"]),
                supersedes_supplement_id=second["id"],
            ),
            SHOP_ESTIMATOR,
        ),
        "ERR_INVALID_SUPPLEMENT_STATE",
        409,
    )

    assert_supplement_state(
        read_supplement(api, first["id"]),
        status="DENIED",
        round_index=1,
        approved_amount_cents=0,
    )
    assert read_supplement(api, first["id"])["decided_at"] == CLOCK_T0
    vehicle = read_vehicle(api, car["vehicle_id"])
    assert vehicle["approved_supplement_cents"] == 0
    assert vehicle["net_billable_cents"] == 80850
    _, all_filings = validate_paginated(
        api.list_supplements(SHOP_ESTIMATOR, {"vehicle_id": car["vehicle_id"]})
    )
    assert all_filings["total_count"] == 2
    _, replacements = validate_paginated(
        api.list_supplements(SHOP_ESTIMATOR, {"supersedes_supplement_id": first["id"]})
    )
    assert replacements["total_count"] == 1


def test_the_two_closeout_gates_ask_different_questions(api):
    """PRD §3.9: "A single car still on the lot blocks the whole demobilization
    with `ERR_EVENT_CLOSEOUT_BLOCKED`."

    PRD §3.9: "The director moves the event `DEMOBILIZING` → `CLOSED`, terminal,
    and it requires three things: the event must be `DEMOBILIZING`, every facility
    of the event must already be `DEMOBILIZED`, and no vehicle at any facility of
    the event may still have a `billing_status` of `AUTHORIZED` or `BILLED` — every
    claim must be either settled to `PAID` or never authorized at all."

    PRD §3.9: "On success the event's `version` increments and one last cascade
    runs: every rate agreement scoped to this event whose `status` is `ACTIVE`
    moves to `SUPERSEDED`, terminal, with a `version` increment, and each affected
    carrier recomputes its `active_rate_agreement_count`."

    Design: Corner/state_machines/demobilize_and_close_blocked_until_vehicles_are_terminal_and_settled
    """
    scenario, car = _a_car_walked_all_the_way_to_ready(api)

    still_parked = api.demobilize_storm_event(scenario["event_id"], DIRECTOR)
    validate_error(still_parked, "ERR_EVENT_CLOSEOUT_BLOCKED", 409)

    released = release_vehicle(api, car["vehicle_id"])
    assert released["repair_status"] == "RELEASED"
    assert released["warranty_number"] == "PDR-0001"

    winding_down = demobilize_event(api, scenario["event_id"])
    assert winding_down["status"] == "DEMOBILIZING"
    assert winding_down["demobilized_at"] == CLOCK_T0
    assert_facility_state(
        read_facility(api, scenario["facility_id"]),
        status="DEMOBILIZED",
        posture="FROZEN",
    )
    for handle in ("TA", "TI"):
        stint = read_deployment(api, scenario["deployments"][handle]["id"])
        assert stint["status"] == "ENDED"
        assert stint["actual_end_date"] == CLOCK_DATE_T0

    validate_error(
        api.close_storm_event(scenario["event_id"], DIRECTOR),
        "ERR_EVENT_CLOSEOUT_BLOCKED",
        409,
    )
    billed = billing_action(
        api, car["vehicle_id"], "SUBMIT_BILL", scenario["insurer_id"]
    )
    assert billed["billing_status"] == "BILLED"
    validate_error(
        api.close_storm_event(scenario["event_id"], DIRECTOR),
        "ERR_EVENT_CLOSEOUT_BLOCKED",
        409,
    )

    paid = billing_action(api, car["vehicle_id"], "SETTLE", scenario["insurer_id"])
    assert paid["billing_status"] == "PAID"
    carrier = read_insurer(api, scenario["insurer_id"])
    assert carrier["outstanding_direct_bill_cents"] == 0
    assert carrier["settled_cents"] == 80850
    # Settling the carrier does not unwind the site's accrual.
    assert read_facility(api, scenario["facility_id"])["billable_accrued_cents"] == 80850

    closed = close_event(api, scenario["event_id"])
    assert closed["status"] == "CLOSED"
    assert read_rate_agreement(api, scenario["rate_agreement_id"])["status"] == (
        "SUPERSEDED"
    )
    assert read_insurer(api, scenario["insurer_id"])["active_rate_agreement_count"] == 0
