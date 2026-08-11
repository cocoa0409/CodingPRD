"""Lameness, therapeutic prescriptions, the hold and the two chains they drive."""

from test_helpers import *  # noqa: F401,F403


def test_activating_a_second_prescription_supersedes_the_first(api, vet):
    """PRD §3.6: "On success: any sibling prescription of the **same case** whose
    `status` is `ACTIVE` moves to `SUPERSEDED`, its `version` incrementing by 1; the
    horse's `active_prescription_id` is set to this prescription; the horse's
    `next_due_on` is recomputed using the therapeutic cycle, but only when the
    horse's `last_completed_on` is already set, since there is no base date
    otherwise; the case moves from `OPEN` to `PRESCRIBED`, and a case already
    `PRESCRIBED` or `RESOLVED` keeps the status it has; and the prescription's
    `version` and the case's `version` each increment by 1."

    Design: Corner/state_machines/corner_activating_a_second_prescription_supersedes_the_first
    """
    set_clock("2026-05-04T08:00:00Z")
    barn = create_barn()
    client = create_client(barn["id"])
    horse = create_horse(client["id"], barn["id"])
    case = report_lameness(horse["id"], "2026-05-04", 2)
    first = draft_prescription(
        case["id"], "2026-05-04", "2026-06-30", ["LF", "RF"], 4
    )
    activate_prescription(first["id"], case["id"])
    second = draft_prescription(
        case["id"], "2026-05-04", "2026-06-30", ["LF", "RF", "LH", "RH"], 2
    )

    data = validate_success(
        api.activate_prescription(
            second["id"],
            {"expected_lameness_case_version": read_case(case["id"])["version"]},
            vet,
        )
    )

    assert_prescription(data)
    assert data["status"] == "ACTIVE"
    assert read_prescription(first["id"])["status"] == "SUPERSEDED"
    assert read_horse(horse["id"])["active_prescription_id"] == second["id"]
    assert read_case(case["id"])["status"] == "PRESCRIBED"
    rows, _meta = validate_paginated(
        api.list_prescriptions(vet, params={"lameness_case_id": case["id"]})
    )
    assert len(rows) == 2


def test_prescription_activate_with_a_stale_case_version_is_refused(api, vet):
    """PRD §2.8: "Activating a prescription requires
    `expected_lameness_case_version` matching the current `version` of the
    `LamenessCase` the prescription belongs to. A mismatch is
    `ERR_STALE_CASE_VERSION` (HTTP 412)."
    PRD §2.8: "Activation legitimately supersedes any sibling already `ACTIVE` on
    the same case, so a second activation is a valid product operation rather than
    an invalid-state error; the version check is what rejects an activation raised
    against a case whose prescription picture the veterinarian has not re-read."

    Design: Corner/cross_cutting_layers/corner_occ_prescription_activate_with_a_stale_case_version_returns_412
    """
    set_clock("2026-05-04T08:00:00Z")
    barn = create_barn()
    client = create_client(barn["id"])
    horse = create_horse(client["id"], barn["id"])
    case = report_lameness(horse["id"], "2026-05-04", 2)
    version_at_creation = case["version"]
    first = draft_prescription(case["id"], "2026-05-04", "2026-06-30", ["LF"], 4)
    second = draft_prescription(case["id"], "2026-05-04", "2026-06-30", ["RF"], 2)
    get_success_data(
        api.activate_prescription(
            first["id"], {"expected_lameness_case_version": version_at_creation}, vet
        )
    )

    response = api.activate_prescription(
        second["id"], {"expected_lameness_case_version": version_at_creation}, vet
    )

    validate_error(response, ApiErrorId.ERR_STALE_CASE_VERSION.value)
    assert response.status_code == 412
    assert read_prescription(first["id"])["status"] == "ACTIVE"
    assert read_prescription(second["id"])["status"] == "DRAFT"
    assert read_horse(horse["id"])["active_prescription_id"] == first["id"]


def test_corrective_on_a_limb_outside_the_prescription_scope_is_rejected(
    api, dispatcher
):
    """PRD §3.5: "That prescription's `limb_scope` must contain the exact limb of
    the referenced limb row, else `ERR_LIMB_NOT_IN_PRESCRIPTION_SCOPE`."
    PRD §3.6: "Coverage is set membership: a prescription covers a limb exactly when
    that limb is a member of its `limb_scope`."

    Design: Corner/validations/corner_corrective_on_a_limb_outside_the_prescription_scope_is_rejected
    """
    set_clock("2026-05-04T08:00:00Z")
    barn = create_barn()
    client = create_client(barn["id"])
    horse = create_horse(client["id"], barn["id"])
    limbs = limb_ids(horse["id"])
    sku = create_sku()
    case = report_lameness(horse["id"], "2026-05-04", 2)
    prescription = draft_prescription(
        case["id"], "2026-05-04", "2026-06-30", ["LF", "RF"], 3
    )
    activate_prescription(prescription["id"], case["id"])
    appointment = create_appointment(horse["id"], "2026-05-06")

    response = api.add_service_lines(
        appointment["id"],
        service_lines_payload(
            [
                service_line(
                    limbs["RH"],
                    "CORRECTIVE",
                    sku_id=sku["id"],
                    prescription_id=prescription["id"],
                )
            ],
            appointment["version"],
        ),
        dispatcher,
    )

    assert read_prescription(prescription["id"])["status"] == "ACTIVE"
    validate_error(response, ApiErrorId.ERR_LIMB_NOT_IN_PRESCRIPTION_SCOPE.value)
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# A CORRECTIVE line needs a live prescription, not merely an existing one
# ---------------------------------------------------------------------------


def _setup_draft_prescription_world():
    set_clock("2026-05-04T08:00:00Z")
    barn = create_barn()
    client = create_client(barn["id"])
    horse = create_horse(client["id"], barn["id"])
    limbs = limb_ids(horse["id"])
    sku = create_sku()
    case = report_lameness(horse["id"], "2026-05-04", 2)
    prescription = draft_prescription(
        case["id"], "2026-05-04", "2026-06-30", ["LF", "RF", "LH", "RH"], 3
    )
    appointment = create_appointment(horse["id"], "2026-05-06")
    return {
        "horse": horse,
        "limbs": limbs,
        "sku": sku,
        "prescription": prescription,
        "appointment": appointment,
    }


def _corrective_line_request(world, dispatcher):
    return api_client.add_service_lines(
        world["appointment"]["id"],
        service_lines_payload(
            [
                service_line(
                    world["limbs"]["LF"],
                    "CORRECTIVE",
                    sku_id=world["sku"]["id"],
                    prescription_id=world["prescription"]["id"],
                )
            ],
            world["appointment"]["version"],
        ),
        dispatcher,
    )


def test_corrective_line_under_a_draft_prescription_is_refused(api, dispatcher):
    """PRD §3.5: "A `CORRECTIVE` line's named prescription must be **live on the
    appointment's `scheduled_date`** — its `status` is `ACTIVE`, its `issued_on` is
    on or before that date and that date is on or before its `expires_on`, both
    bounds inclusive — else `ERR_NO_LIVE_PRESCRIPTION`."
    PRD §3.6: "The prescription copies `horse_id` from its case and is minted
    `DRAFT`, which authorises nothing."

    Design: Difficulty/cross_entity_state_dependency/corrective_service_line_refused_while_its_prescription_is_still_draft
    """
    world = _setup_draft_prescription_world()
    assert read_prescription(world["prescription"]["id"])["status"] == "DRAFT"
    assert read_horse(world["horse"]["id"])["hold_status"] == "CLEAR"

    response = _corrective_line_request(world, dispatcher)

    validate_error(response, ApiErrorId.ERR_NO_LIVE_PRESCRIPTION.value)
    assert response.status_code == 422


def test_refused_corrective_line_writes_nothing_at_all(api, dispatcher):
    """PRD §3.5: "The array is validated in index order, the first offending
    element's error is returned, and on any failure **nothing at all is written**:
    no partial line set, no roll-up change, no reservation."
    PRD §3.6: "Liveness is checked against a date, and both bounds are inclusive: a
    prescription is live on a given date when its `status` is `ACTIVE`, its
    `issued_on` is on or before that date, and that date is on or before its
    `expires_on`."

    Design: Difficulty/cross_entity_state_dependency/corrective_service_line_refused_while_its_prescription_is_still_draft
    """
    world = _setup_draft_prescription_world()

    response = _corrective_line_request(world, dispatcher)
    validate_error(response, ApiErrorId.ERR_NO_LIVE_PRESCRIPTION.value)

    assert service_lines_for(world["appointment"]["id"]) == []
    after = read_appointment(world["appointment"]["id"])
    assert after["service_units"] == 0
    assert reservations_for(world["appointment"]["id"]) == []


# ---------------------------------------------------------------------------
# The lameness chain: SCHEDULED -> BLOCKED -> UNROUTED
# ---------------------------------------------------------------------------


def _setup_blocked_appointment_world():
    """A TRIM visit attached to a PLANNED route, then a severity-4 lameness case."""
    world = setup_reference(with_sku=False)
    setup_route_with_stop(world, route_date="2026-05-06", planned_start_minute=480)
    setup_scheduled_visit(world, service_type="TRIM", scheduled_date="2026-05-06")
    plan_route(world["route"]["id"])
    world["case"] = report_lameness(world["horse"]["id"], "2026-05-04", 4)
    return world


def test_lameness_hold_blocks_the_scheduled_appointment_and_empties_the_route(api):
    """PRD §3.6: "Severity is what decides whether the yard's routine stops: a case
    whose `severity` is at least 3 (`LAMENESS_HOLD_SEVERITY_THRESHOLD`) has
    `hold_applied` set true and puts the horse's `hold_status` on `HOLD`,
    incrementing the horse's `version` by 1; a case of severity 1 or 2 is recorded
    with `hold_applied` false and changes nothing else at all."
    PRD §2.10: "Hop 3: because the horse went on hold, every appointment of that
    horse whose `status` is `SCHEDULED` or `CONFIRMED` becomes `BLOCKED` and its
    `route_stop_id` is cleared."
    PRD §3.4: "There is one system-driven leg back up the chain: a `PLANNED` route
    whose `committed_units` has fallen to zero reverts to `DRAFT`, incrementing its
    `version` by 1."

    Design: Difficulty/non_linear_state_machine/appointment_scheduled_blocked_unrouted_cycle_on_appointment
    """
    world = _setup_blocked_appointment_world()

    appointment = read_appointment(world["appointment"]["id"])
    assert appointment["status"] == "BLOCKED"
    assert appointment["route_stop_id"] is None
    route = read_route(world["route"]["id"])
    assert route["committed_units"] == 0
    assert route["status"] == "DRAFT"
    assert read_horse(world["horse"]["id"])["hold_status"] == "HOLD"


def test_resolving_the_case_returns_the_blocked_appointment_to_unrouted(api, vet):
    """PRD §3.6: "When the hold does clear, every appointment of that horse whose
    `status` is `BLOCKED` returns to `UNROUTED` — note that it returns unattached,
    since the block already stripped its `route_stop_id`, and each such
    appointment's `version` increments by 1 — and the horse's `version` increments
    by 1."
    PRD §3.6: "After a resolve, the horse's `hold_status` becomes `CLEAR` exactly
    when no remaining case for that horse has `hold_applied` true **and** a `status`
    of `OPEN` or `PRESCRIBED`; one qualifying case still open keeps the horse on
    hold however many others are closed."

    Design: Difficulty/non_linear_state_machine/appointment_scheduled_blocked_unrouted_cycle_on_appointment
    """
    world = _setup_blocked_appointment_world()
    assert read_appointment(world["appointment"]["id"])["status"] == "BLOCKED"

    data = validate_success(api.resolve_lameness_case(world["case"]["id"], vet))

    assert_lameness_case(data)
    assert data["status"] == "RESOLVED"
    after = read_appointment(world["appointment"]["id"])
    assert after["status"] == "UNROUTED", "the appointment occupies UNROUTED a second time"
    assert after["route_stop_id"] is None
    assert read_horse(world["horse"]["id"])["hold_status"] == "CLEAR"


# ---------------------------------------------------------------------------
# The six-hop cascade out of a lameness report
# ---------------------------------------------------------------------------


def _setup_cascade_world():
    """Van bucket at 4 pairs, a NEW_SHOES visit attached to a PLANNED route and a
    still-REQUESTED replenishment transfer into that van bucket."""
    world = setup_reference(van_pairs=4)
    setup_route_with_stop(world, route_date="2026-05-06", planned_start_minute=480)
    setup_scheduled_visit(
        world, service_type="NEW_SHOES", use_sku=True, scheduled_date="2026-05-06"
    )
    plan_route(world["route"]["id"])
    world["transfer"] = create_transfer(
        world["sku"]["id"], world["shop"]["id"], world["van"]["id"], quantity_pairs=5
    )
    reserved = read_bucket(world["van"]["id"])
    assert reserved["available_pairs"] == 2 and reserved["replenishment_flag"] is True
    world["case"] = report_lameness(world["horse"]["id"], "2026-05-04", 4)
    return world


def test_lameness_report_blocks_the_visit_and_releases_its_reservation(api):
    """PRD §2.10: "Hop 1: the case is created with `status` `OPEN` and
    `hold_applied` true. Hop 2: because the hold applied, the horse's `hold_status`
    becomes `HOLD`. Hop 3: because the horse went on hold, every appointment of that
    horse whose `status` is `SCHEDULED` or `CONFIRMED` becomes `BLOCKED` and its
    `route_stop_id` is cleared. Hop 4: because those appointments were detached,
    each of their `RESERVED` reservations becomes `RELEASED`."
    PRD §3.6: "Only reservations that are `RESERVED` are released; ones already
    `COMMITTED` or `RELEASED` are untouched."

    Design: Difficulty/transitive_cascade/lameness_report_cascades_six_hops_to_stock_transfer_cancellation
    """
    world = _setup_cascade_world()

    case = read_case(world["case"]["id"])
    assert case["status"] == "OPEN"
    assert case["hold_applied"] is True
    assert read_horse(world["horse"]["id"])["hold_status"] == "HOLD"
    appointment = read_appointment(world["appointment"]["id"])
    assert appointment["status"] == "BLOCKED"
    assert appointment["route_stop_id"] is None
    reservations = reservations_for(world["appointment"]["id"])
    assert len(reservations) == 1
    assert reservations[0]["status"] == "RELEASED"
    assert reservations[0]["pairs"] == 2


def test_lameness_report_clears_the_flag_and_cancels_the_inbound_transfer(api):
    """PRD §2.10: "Hop 5: because a reservation was released, its bucket gains
    `available_pairs`, loses `reserved_pairs`, and has `replenishment_flag`
    recomputed. Hop 6: because that flag flipped from true to false, every transfer
    still `REQUESTED` into that bucket becomes `CANCELLED`."
    PRD §2.10: "A parallel branch runs alongside hops 3 and 4: hop 3b, a stop left
    with no attached appointment becomes `VOIDED`; hop 4b, because the stop was
    voided, the route's `committed_minutes` and `stop_count` fall, and a `PLANNED`
    route whose `committed_units` has reached zero reverts to `DRAFT`."

    Design: Difficulty/transitive_cascade/lameness_report_cascades_six_hops_to_stock_transfer_cancellation
    """
    world = _setup_cascade_world()

    bucket = read_bucket(world["van"]["id"])
    assert bucket["available_pairs"] == 4
    assert bucket["reserved_pairs"] == 0
    assert bucket["on_hand_pairs"] == 4
    assert bucket["replenishment_flag"] is False
    assert_bucket_balance(bucket)
    assert read_transfer(world["transfer"]["id"])["status"] == "CANCELLED"
    assert read_stop(world["stop"]["id"])["status"] == "VOIDED"
    route = read_route(world["route"]["id"])
    assert route["committed_units"] == 0
    assert route["committed_minutes"] == 0
    assert route["stop_count"] == 0
    assert route["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Gate 4 pre-empts the van-stock rung
# ---------------------------------------------------------------------------


def _setup_held_horse_with_empty_van():
    """Lines added before the hold, so the appointment is UNROUTED and untouched by
    the lameness chain, and the van holds none of the two pairs the visit needs."""
    world = setup_reference(van_pairs=0)
    setup_route_with_stop(world, route_date="2026-05-06", planned_start_minute=480)
    setup_unrouted_visit(
        world, service_type="NEW_SHOES", use_sku=True, scheduled_date="2026-05-06"
    )
    world["case"] = report_lameness(world["horse"]["id"], "2026-05-04", 4)
    return world


def test_horse_on_hold_pre_empts_the_van_stock_shortfall(api, dispatcher):
    """PRD §2.6: "**Gate 4 — the horse is not on hold.** `Horse.hold_status` must be
    `CLEAR`; alternatively the horse may pass while on `HOLD` if every `ServiceLine`
    already on the appointment in scope has `service_type` `CORRECTIVE` under a
    prescription that is live and whose `limb_scope` covers that line's `limb`. The
    refusal is `ERR_HORSE_ON_HOLD` (HTTP 409)."
    PRD §2.7: "When more than one rung would fire for a single request, the
    **lowest-numbered rung wins** and its code is returned; later rungs are not
    evaluated and their side conditions are irrelevant."

    Design: Difficulty/priority_pair_validation_conflict/horse_hold_safety_preempts_van_stock_constraint
    """
    world = _setup_held_horse_with_empty_van()
    assert read_bucket(world["van"]["id"])["available_pairs"] == 0
    assert read_horse(world["horse"]["id"])["hold_status"] == "HOLD"

    response = attach_response(
        world["stop"]["id"], world["appointment"]["id"], world["route"]["id"]
    )

    validate_error(response, ApiErrorId.ERR_HORSE_ON_HOLD.value)
    assert response.status_code == 409


def test_the_pre_empted_attach_reserves_nothing_and_moves_no_capacity(api, dispatcher):
    """PRD §2.7: "(51) The van bucket holds enough pairs, else
    `ERR_VAN_STOCK_INSUFFICIENT` (HTTP 409); on attachment."
    PRD §2.7: "**Rungs 28–33, the five gates.** (28) Gate 1a —
    `ERR_FARRIER_INACTIVE`. (29) Gate 1b — `ERR_FARRIER_CERT_EXPIRED`. (30) Gate 2 —
    `ERR_ROUTE_NOT_OPEN`. (31) Gate 3 — `ERR_CLIENT_PREPAY_REQUIRED`. (32) Gate 4 —
    `ERR_HORSE_ON_HOLD`. (33) Gate 5 — `ERR_APPOINTMENT_NOT_ELIGIBLE`."

    Design: Difficulty/priority_pair_validation_conflict/horse_hold_safety_preempts_van_stock_constraint
    """
    world = _setup_held_horse_with_empty_van()

    response = attach_response(
        world["stop"]["id"], world["appointment"]["id"], world["route"]["id"]
    )
    validate_error(response, ApiErrorId.ERR_HORSE_ON_HOLD.value)

    assert reservations_for(world["appointment"]["id"]) == []
    assert read_route(world["route"]["id"])["committed_units"] == 0
    assert read_appointment(world["appointment"]["id"])["status"] == "UNROUTED"


# ---------------------------------------------------------------------------
# The expiry chain out of a clock advance
# ---------------------------------------------------------------------------


def _setup_expiring_prescription_world():
    """Four CORRECTIVE limbs under a prescription that expires on 2026-05-20, on a
    DRAFT route dated 2026-05-13."""
    world = setup_reference(
        farrier={"certification_level": "CERTIFIED_THERAPEUTIC"},
    )
    world["case"] = report_lameness(world["horse"]["id"], "2026-05-04", 2)
    world["prescription"] = draft_prescription(
        world["case"]["id"], "2026-05-04", "2026-05-20", ["LF", "RF", "LH", "RH"], 3
    )
    activate_prescription(world["prescription"]["id"], world["case"]["id"])
    setup_route_with_stop(world, route_date="2026-05-13", planned_start_minute=480)
    setup_scheduled_visit(
        world,
        service_type="CORRECTIVE",
        use_sku=True,
        scheduled_date="2026-05-13",
        line_overrides={"prescription_id": world["prescription"]["id"]},
    )
    return world


def test_clock_advance_expires_the_live_prescription(api, admin):
    """PRD §3.6: "Expiry is the same ending reached without anyone acting: when the
    logical clock advances past a live prescription's `expires_on`, that
    prescription becomes `EXPIRED` and the expiry chain of §2.10 runs — the horse's
    `active_prescription_id` is nulled and `next_due_on` reverts to the routine
    derivation, every `PLANNED` `CORRECTIVE` service line on a non-terminal
    appointment of that horse moves to `REMOVED`, and the affected appointments'
    `service_units` and `service_minutes` and their routes' committed totals are
    recomputed."
    PRD §3.9: "Advancing the logical clock is thus a business event and not merely a
    test fixture. It expires every `ACTIVE` prescription whose `expires_on` falls
    strictly before the new date and runs the expiry chain for each"

    Design: Difficulty/transitive_cascade/clock_advance_expires_prescription_and_strips_corrective_lines
    """
    world = _setup_expiring_prescription_world()
    assert read_prescription(world["prescription"]["id"])["status"] == "ACTIVE"

    data = validate_success(
        api.set_clock({"to_iso8601": "2026-05-21T08:00:00Z"}, admin)
    )

    assert_same_instant(data["current_utc"], "2026-05-21T08:00:00Z")
    assert world["prescription"]["id"] in data["expired_prescription_ids"]
    assert read_prescription(world["prescription"]["id"])["status"] == "EXPIRED"
    assert read_horse(world["horse"]["id"])["active_prescription_id"] is None
    assert read_case(world["case"]["id"])["status"] == "PRESCRIBED"


def test_expiry_strips_the_corrective_lines_and_frees_the_route_units(api, admin):
    """PRD §2.10: "Hop 4: because no live prescription remains, every `PLANNED`
    `CORRECTIVE` service line on a non-terminal appointment of that horse becomes
    `REMOVED`. Hop 5: because lines were removed, the affected appointment's
    `service_units` and `service_minutes` and its route's committed totals are
    recomputed."
    PRD §3.4: "`committed_units` is the sum of `service_units` over the appointments
    attached to any non-`VOIDED` stop of the route whose `status` is `SCHEDULED`,
    `CONFIRMED`, `IN_PROGRESS` or `COMPLETED`"

    Design: Difficulty/transitive_cascade/clock_advance_expires_prescription_and_strips_corrective_lines
    """
    world = _setup_expiring_prescription_world()
    before_appointment = read_appointment(world["appointment"]["id"])
    # Four CORRECTIVE limbs: 4 x 5 units, 4 x 32 chair minutes + 6 handling.
    assert before_appointment["service_units"] == 20
    assert before_appointment["service_minutes"] == 134
    before_route = read_route(world["route"]["id"])
    assert before_route["committed_units"] == 20
    assert before_route["committed_minutes"] == 149

    get_success_data(api.set_clock({"to_iso8601": "2026-05-21T08:00:00Z"}, admin))

    lines = service_lines_for(world["appointment"]["id"])
    assert len(lines) == 4
    assert {line["status"] for line in lines} == {"REMOVED"}
    assert read_appointment(world["appointment"]["id"])["service_units"] == 0
    assert read_route(world["route"]["id"])["committed_units"] == 0
