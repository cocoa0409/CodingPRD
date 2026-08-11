"""Scheduling a visit: foreign keys, the two property axes and the turnover geometry."""

from test_helpers import (
    ACCOUNT_MANAGER,
    AUDITOR,
    DISPATCHER,
    PLATFORM_ADMIN,
    ApiErrorId,
    assert_same_instant,
    assert_visit,
    create_away_period_payload,
    create_visit_payload,
    new_owner,
    new_property,
    new_rental_turnover,
    new_service_plan,
    new_subscription,
    new_template,
    new_visit,
    refresh_property,
    refresh_turnover,
    refresh_visit,
    run_occupancy,
    run_seasonal,
    set_clock,
    setup_subscribed_property,
    validate_error,
    validate_paginated,
    validate_success,
)

STANDARD = {"tier": "STANDARD", "monthly_fee_cents": 19986, "included_visit_units": 4,
            "covered_visit_types": ["ROUTINE_WATCH"]}


def test_new_visit_is_born_scheduled_with_every_system_field_null(api):
    """PRD 3.3: "A new visit is born `SCHEDULED`, with `entitlement_applied` false,
    `billable_amount_cents` zero, `after_hours_flag` false, `deferral_count` zero,
    `checklist_completion_pct` 0.0, empty `completed_item_codes` and
    `failed_item_codes`, and a null `billing_cycle_id`, `departed_at`, `arrived_at`,
    `completed_at`, `tech_user_id`, `interior_temp_f` and `defer_reason`."

    Design: Corner/entities/visit_system_fields_are_server_stamped_not_client_supplied
    """
    ctx = setup_subscribed_property(plan_overrides=STANDARD)
    template = new_template("ROUTINE_WATCH", item_codes=["EXT_WALK"], critical_item_codes=[])
    response = api.create_visit(
        create_visit_payload(ctx["property_id"], template["id"]), DISPATCHER
    )
    data = validate_success(response, 201)
    assert_visit(data)
    assert data["status"] == "SCHEDULED"
    assert data["departed_at"] is None
    assert data["arrived_at"] is None
    assert data["completed_at"] is None
    assert data["tech_user_id"] is None
    assert data["billing_cycle_id"] is None
    assert data["entitlement_applied"] is False
    assert data["billable_amount_cents"] == 0
    assert data["after_hours_flag"] is False
    assert data["deferral_count"] == 0
    assert data["checklist_completion_pct"] == 0.0
    assert data["completed_item_codes"] == []
    assert data["failed_item_codes"] == []
    assert data["interior_temp_f"] is None
    assert data["defer_reason"] is None
    assert data["version"] == 1


def test_one_visit_row_carries_several_independent_foreign_keys(api):
    """PRD 3.3: "Three optional links may be supplied: an `away_period_id` naming the
    cadence window that produced the visit, a `storm_response_id` set only on the storm
    pipeline, and a `rental_turnover_id` when the visit is bound to a turnover."
    PRD 3.3: "`scheduled_visit_count` itself counts the visits bound to this away period
    whose status is `SCHEDULED`, `EN_ROUTE`, `IN_PROGRESS` or `COMPLETED`."

    Design: Corner/entities/graph_topology_visit_carries_six_independent_foreign_keys
    """
    ctx = setup_subscribed_property(
        plan_overrides=STANDARD,
        property_overrides={"label": "Graph House", "address_line": "1 Edge St",
                            "travel_distance_miles": 18.0, "rental_program_enrolled": True},
    )
    template = new_template("ROUTINE_WATCH", item_codes=["EXT_WALK"], critical_item_codes=[])
    away = validate_success(api.create_away_period(
        create_away_period_payload(ctx["property_id"], ctx["owner_id"],
                                   start_at="2026-06-01T00:00:00Z",
                                   end_at="2026-08-30T00:00:00Z", cadence_days=14),
        ACCOUNT_MANAGER,
    ), 201)
    turnover = new_rental_turnover(ctx["property_id"], checkout_at="2026-07-10T11:00:00Z",
                                   checkin_at="2026-07-12T15:00:00Z", guest_reference="BK-9100")

    visit = new_visit(ctx["property_id"], template["id"],
                      scheduled_start_at="2026-06-05T13:00:00Z",
                      scheduled_end_at="2026-06-05T15:00:00Z",
                      away_period_id=away["id"], rental_turnover_id=turnover["id"])
    assert visit["away_period_id"] == away["id"]
    assert visit["rental_turnover_id"] == turnover["id"]
    assert visit["checklist_template_id"] == template["id"]
    assert visit["property_id"] == ctx["property_id"]

    by_away, meta_a = validate_paginated(
        api.list_visits(headers=AUDITOR, params={"away_period_id": away["id"]})
    )
    assert meta_a["total_count"] == 1 and by_away[0]["id"] == visit["id"]
    by_turnover, meta_t = validate_paginated(
        api.list_visits(headers=AUDITOR, params={"rental_turnover_id": turnover["id"]})
    )
    assert meta_t["total_count"] == 1 and by_turnover[0]["id"] == visit["id"]

    reread = validate_success(api.get_away_period(away["id"], ACCOUNT_MANAGER))
    assert reread["scheduled_visit_count"] == 1


def test_cadence_revision_reprojects_forward_without_retiming_booked_visits(api):
    """PRD 3.3: "On a mid-period revision the calculation is anchored differently: the
    anchor instant is the later of the logical clock and `start_at`; the remaining-day
    count is the whole days from that anchor to `end_at`, again by flooring seconds
    divided by 86400; and the new projection is `scheduled_visit_count` plus the floor of
    the remaining-day count divided by the new `cadence_days`."
    PRD 3.3: "A revision is **non-retroactive**: already-scheduled visits are never
    cancelled or re-timed, and instead are counted into the new projection."

    Design: Corner/calculations/cadence_revision_is_forward_looking_and_never_retro_voids
    """
    ctx = setup_subscribed_property(
        clock="2026-06-25T00:00:00Z",
        plan_overrides={"tier": "PREMIUM", "monthly_fee_cents": 34944,
                        "included_visit_units": 8, "covered_visit_types": ["ROUTINE_WATCH"]},
        property_overrides={"label": "Away House", "address_line": "90 Season Way",
                            "travel_distance_miles": 18.0},
        started_on="2026-06-25T00:00:00Z",
    )
    away = validate_success(api.create_away_period(
        create_away_period_payload(ctx["property_id"], ctx["owner_id"],
                                   start_at="2026-07-01T00:00:00Z",
                                   end_at="2026-09-29T00:00:00Z", cadence_days=14),
        ACCOUNT_MANAGER,
    ), 201)
    assert away["projected_visit_count"] == 6

    template = new_template("ROUTINE_WATCH", item_codes=["EXT_WALK"], critical_item_codes=[])
    first = new_visit(ctx["property_id"], template["id"],
                      scheduled_start_at="2026-08-05T13:00:00Z",
                      scheduled_end_at="2026-08-05T15:00:00Z", away_period_id=away["id"])
    second = new_visit(ctx["property_id"], template["id"],
                       scheduled_start_at="2026-08-19T13:00:00Z",
                       scheduled_end_at="2026-08-19T15:00:00Z", away_period_id=away["id"])

    set_clock("2026-07-31T00:00:00Z")
    revised = validate_success(
        api.update_away_period_cadence(away["id"], {"cadence_days": 7}, ACCOUNT_MANAGER)
    )
    assert revised["cadence_days"] == 7
    assert revised["cadence_revision_count"] == 1
    assert revised["projected_visit_count"] == 10, "2 already booked plus floor(60 / 7) == 8"
    assert revised["scheduled_visit_count"] == 2
    assert revised["derived_status"] == "IN_EFFECT"

    assert_same_instant(refresh_visit(first["id"])["scheduled_start_at"],
                        "2026-08-05T13:00:00Z", "first visit start")
    assert refresh_visit(first["id"])["status"] == "SCHEDULED"
    assert_same_instant(refresh_visit(second["id"])["scheduled_start_at"],
                        "2026-08-19T13:00:00Z", "second visit start")
    assert refresh_visit(second["id"])["status"] == "SCHEDULED"


def test_template_of_a_different_visit_type_is_a_payload_mismatch(api):
    """PRD 3.3: "The bound template's own `visit_type` must equal the submitted
    `visit_type` and the template must be `ACTIVE`; otherwise the request is rejected
    with `ERR_TEMPLATE_TYPE_MISMATCH`."

    Design: Corner/errors/err_template_type_mismatch_when_template_visit_type_differs_returns_400
    """
    ctx = setup_subscribed_property(plan_overrides=STANDARD)
    template = new_template("STORM_SECURE", item_codes=["SHUTTERS"], critical_item_codes=[])
    response = api.create_visit(
        create_visit_payload(ctx["property_id"], template["id"], visit_type="ROUTINE_WATCH"),
        DISPATCHER,
    )
    validate_error(response, ApiErrorId.ERR_TEMPLATE_TYPE_MISMATCH.value)
    _, meta = validate_paginated(
        api.list_visits(headers=AUDITOR, params={"property_id": ctx["property_id"]})
    )
    assert meta["total_count"] == 0


def test_unknown_checklist_template_is_reported_after_the_property_resolves(api):
    """PRD 2.8: "A body field `checklist_template_id` resolves to an existing checklist
    template. This applies to visit scheduling. Otherwise `ERR_TEMPLATE_NOT_FOUND`,
    HTTP 404."
    PRD 2.7: "Path ids are resolved left to right in path order; then body foreign keys
    are resolved in the order the fields are listed in the endpoint's request body."

    Design: Corner/errors/err_template_not_found_on_visit_create_returns_404
    """
    ctx = setup_subscribed_property(plan_overrides=STANDARD)
    response = api.create_visit(
        create_visit_payload(ctx["property_id"], "00000000-0000-4000-8000-0000000000b2"),
        DISPATCHER,
    )
    validate_error(response, ApiErrorId.ERR_TEMPLATE_NOT_FOUND.value)


def test_unknown_optional_away_period_link_is_a_linked_resource_404(api):
    """PRD 2.8: "Every optional foreign key supplied in the body resolves, checked **in
    the order the fields are listed in that endpoint's request body**. The optional keys
    covered by this rung are `away_period_id`, `rental_turnover_id`, `storm_response_id`,
    `key_asset_id`, `key_issuance_id`, `visit_id`, `security_incident_id`, `mail_hold_id`
    and `work_order_id`. This rung applies on every endpoint. Otherwise
    `ERR_LINKED_RESOURCE_NOT_FOUND`, HTTP 404."

    Design: Corner/errors/err_linked_resource_not_found_for_unknown_away_period_returns_404
    """
    ctx = setup_subscribed_property(plan_overrides=STANDARD)
    template = new_template("ROUTINE_WATCH", item_codes=["EXT_WALK"], critical_item_codes=[])
    response = api.create_visit(
        create_visit_payload(ctx["property_id"], template["id"],
                             away_period_id="00000000-0000-4000-8000-0000000000b4"),
        DISPATCHER,
    )
    validate_error(response, ApiErrorId.ERR_LINKED_RESOURCE_NOT_FOUND.value)


def test_scheduling_a_visit_on_an_unsubscribed_property_is_refused(api):
    """PRD 2.8: "The property has a subscription whose status is anything other than
    `CANCELLED`. This applies to visit scheduling and to opening a draft invoice on a
    billing cycle. Otherwise `ERR_NO_ACTIVE_SUBSCRIPTION`, HTTP 409."

    Design: Corner/errors/err_no_active_subscription_on_visit_create_returns_409
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = new_owner(full_name="No Sub", primary_residence_state="MN")
    prop = new_property(owner["id"], label="NoSub House", address_line="53 Bare Bnd",
                        travel_distance_miles=18.0)
    template = new_template("ROUTINE_WATCH", item_codes=["EXT_WALK"], critical_item_codes=[])
    response = api.create_visit(create_visit_payload(prop["id"], template["id"]), DISPATCHER)
    validate_error(response, ApiErrorId.ERR_NO_ACTIVE_SUBSCRIPTION.value)
    _, meta = validate_paginated(
        api.list_visits(headers=AUDITOR, params={"property_id": prop["id"]})
    )
    assert meta["total_count"] == 0


def test_routine_watch_requires_a_vacant_home(api):
    """PRD 2.8: "A visit whose `visit_type` is `ROUTINE_WATCH` requires the property's
    `occupancy_state` to be `VACANT`, checked at scheduling and again at departure.
    Otherwise `ERR_OCCUPANCY_FORBIDS_VISIT`, HTTP 409."

    Design: Corner/errors/err_occupancy_forbids_visit_for_routine_watch_while_owner_in_residence_returns_409
    """
    ctx = setup_subscribed_property(
        plan_overrides=STANDARD,
        property_overrides={"label": "Occupied House", "address_line": "38 Home Hwy",
                            "travel_distance_miles": 18.0},
    )
    template = new_template("ROUTINE_WATCH", item_codes=["EXT_WALK"], critical_item_codes=[])
    run_occupancy(ctx["property_id"], "OWNER_IN_RESIDENCE", ctx["owner_headers"])

    response = api.create_visit(create_visit_payload(ctx["property_id"], template["id"]),
                                DISPATCHER)
    validate_error(response, ApiErrorId.ERR_OCCUPANCY_FORBIDS_VISIT.value)
    prop = refresh_property(ctx)
    assert prop["seasonal_state"] == "OPEN"
    assert prop["occupancy_state"] == "OWNER_IN_RESIDENCE"


def test_seasonal_band_is_evaluated_before_the_occupancy_band(api):
    """PRD 2.7: "6. **G6 — PROPERTY SEASONAL.** The property's `seasonal_state` permits
    the operation. This band is evaluated **before** occupancy because the seasonal axis
    is the slower-moving one and its violations cannot be recovered inside the request."
    PRD 2.8: "A visit whose `visit_type` is `TURNOVER_INSPECT` requires `seasonal_state`
    to be `OPEN`, checked at scheduling and again at departure. Otherwise
    `ERR_SEASONAL_STATE_FORBIDS_VISIT`, HTTP 409."

    Design: Corner/validations/seasonal_gate_precedes_occupancy_gate_on_visit_create
    """
    ctx = setup_subscribed_property(
        plan_overrides=STANDARD,
        property_overrides={"label": "Gate House", "address_line": "6 Order Rd",
                            "travel_distance_miles": 18.0, "rental_program_enrolled": True},
    )
    template = new_template("TURNOVER_INSPECT", item_codes=["LINENS"], critical_item_codes=[])
    turnover = new_rental_turnover(ctx["property_id"], checkout_at="2026-06-10T11:00:00Z",
                                   checkin_at="2026-06-12T15:00:00Z", guest_reference="BK-9600")
    # Interleaved: the close must begin while the home is still VACANT, and the home is
    # only driven to RENTAL_OCCUPIED afterwards by the turnover's own CHECKIN edge.
    run_seasonal(ctx["property_id"], "BEGIN_CLOSE", PLATFORM_ADMIN)
    set_clock("2026-06-10T12:00:00Z")
    for stage in ("CHECKOUT", "CLEANING", "INSPECTION", "READY"):
        validate_success(
            api.advance_rental_turnover(turnover["id"], {"to_status": stage}, DISPATCHER)
        )
    set_clock("2026-06-12T16:00:00Z")
    validate_success(
        api.advance_rental_turnover(turnover["id"], {"to_status": "CHECKIN"}, DISPATCHER)
    )
    prop = refresh_property(ctx)
    assert prop["seasonal_state"] == "CLOSING"
    assert prop["occupancy_state"] == "RENTAL_OCCUPIED"

    response = api.create_visit(
        create_visit_payload(ctx["property_id"], template["id"], visit_type="TURNOVER_INSPECT",
                             scheduled_start_at="2026-06-20T13:00:00Z",
                             scheduled_end_at="2026-06-20T15:00:00Z"),
        DISPATCHER,
    )
    assert response.status_code == 409, f"expected 409, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_SEASONAL_STATE_FORBIDS_VISIT.value)


def test_visit_list_filter_scopes_rows_to_one_property(api):
    """PRD 2.3: "Visits expose every foreign key as a filter — `property_id`,
    `checklist_template_id`, `away_period_id`, `storm_response_id`, `rental_turnover_id`,
    `billing_cycle_id` — plus `status` and `visit_type`."
    PRD 2.3: "Collections also accept domain filters, and each filter is an exact-match
    predicate on the named field."

    Design: Corner/endpoints/filtered_list_endpoints_scope_children_to_their_parent
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = new_owner(full_name="Vin Scope", primary_residence_state="OH")
    plan = new_service_plan(**STANDARD)
    template = new_template("ROUTINE_WATCH", item_codes=["EXT_WALK"], critical_item_codes=[])
    visits = {}
    for label, address, day in (("Scope A", "1 A Rd", "02"), ("Scope B", "2 B Rd", "03")):
        prop = new_property(owner["id"], label=label, address_line=address,
                            travel_distance_miles=18.0)
        subscription = new_subscription(prop["id"], plan["id"], "2026-06-01T00:00:00Z")
        validate_success(api.activate_subscription(subscription["id"], {}, ACCOUNT_MANAGER))
        visits[prop["id"]] = new_visit(prop["id"], template["id"],
                                       scheduled_start_at=f"2026-06-{day}T13:00:00Z",
                                       scheduled_end_at=f"2026-06-{day}T15:00:00Z")["id"]

    first_property = list(visits)[0]
    rows, meta = validate_paginated(
        api.list_visits(headers=AUDITOR, params={"property_id": first_property})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == visits[first_property]
    _, all_meta = validate_paginated(api.list_visits(headers=AUDITOR))
    assert all_meta["total_count"] == 2


def test_conversion_needs_a_real_overlap_with_the_padded_turnover_window(api):
    """PRD 3.4: "the target turnover must be in `CLEANING` or `INSPECTION` and the visit's
    window must overlap that turnover's padded window, an absent overlap being rejected
    with `ERR_NO_TURNOVER_OVERLAP`."
    PRD 3.4: "Conversion sets the visit's `rental_turnover_id`, points the turnover's
    `absorbed_visit_id` at this visit, leaves `entitlement_applied` false, and books an
    absorption charge of half the scheduled base fee — 6500 multiplied by 0.50, rounded,
    which is 3250 — into `billable_amount_cents`."

    Design: Corner/errors/err_no_turnover_overlap_on_convert_of_a_distant_visit_returns_409
    """
    ctx = setup_subscribed_property(
        plan_overrides=STANDARD,
        property_overrides={"label": "FarConv House", "address_line": "1 Distant Dr",
                            "travel_distance_miles": 18.0, "rental_program_enrolled": True},
    )
    template = new_template("ROUTINE_WATCH", item_codes=["EXT_WALK"], critical_item_codes=[])
    turnover = new_rental_turnover(ctx["property_id"], checkout_at="2026-06-10T11:00:00Z",
                                   checkin_at="2026-06-12T15:00:00Z", guest_reference="BK-9500")
    visit = new_visit(ctx["property_id"], template["id"],
                      scheduled_start_at="2026-06-05T13:00:00Z",
                      scheduled_end_at="2026-06-05T15:00:00Z")
    set_clock("2026-06-10T12:00:00Z")
    validate_success(
        api.advance_rental_turnover(turnover["id"], {"to_status": "CHECKOUT"}, DISPATCHER)
    )
    validate_success(
        api.advance_rental_turnover(turnover["id"], {"to_status": "CLEANING"}, DISPATCHER)
    )

    response = api.convert_to_turnover_visit(
        visit["id"], {"rental_turnover_id": turnover["id"]}, DISPATCHER
    )
    validate_error(response, ApiErrorId.ERR_NO_TURNOVER_OVERLAP.value)
    reread = refresh_visit(visit["id"])
    assert reread["status"] == "SCHEDULED"
    assert reread["billable_amount_cents"] == 0
    assert reread["rental_turnover_id"] is None
    assert refresh_turnover(turnover["id"])["absorbed_visit_id"] is None


# --------------------------------------------------------------------------
# The existence gate versus the payload gate
# --------------------------------------------------------------------------

def test_unknown_property_beats_a_missing_required_field(api):
    """PRD 2.7: "This is why a request that is simultaneously malformed and aimed at a
    parent that does not exist returns the 404 from the existence gate and never the 400
    from the payload gate — payload validation is deliberately last."
    PRD 2.8: "A body field `property_id` resolves to an existing property. This applies to
    subscription creation, away-period declaration, visit scheduling and storm-response
    enrolment. Otherwise `ERR_PROPERTY_NOT_FOUND`, HTTP 404."

    Design: Difficulty/priority_pair_validation_conflict/visit_create_missing_field_and_unknown_property_returns_404
    """
    set_clock("2026-06-01T00:00:00Z")
    template = new_template("ROUTINE_WATCH", item_codes=["EXT_WALK"], critical_item_codes=[])
    response = api.create_visit(
        {
            "property_id": "00000000-0000-4000-8000-000000000000",
            "checklist_template_id": template["id"],
            "visit_type": "ROUTINE_WATCH",
            "trigger_source": "SCHEDULED",
            "scheduled_start_at": "2026-06-02T13:00:00Z",
        },
        DISPATCHER,
    )
    assert response.status_code == 404, f"expected 404, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_PROPERTY_NOT_FOUND.value)
    _, meta = validate_paginated(api.list_visits(headers=AUDITOR))
    assert meta["total_count"] == 0, "no visit row may be created"


def test_unknown_property_beats_an_undeclared_enum_member(api):
    """PRD 2.7: "10. **G10 — PAYLOAD.** Field-level validation: required fields present,
    JSON types, enum membership, numeric ranges, interval well-formedness, and array
    membership against a declared code set."
    PRD 2.7: "3. **G3 — EXISTENCE.** Path ids are resolved left to right in path order;
    then body foreign keys are resolved in the order the fields are listed in the
    endpoint's request body. The first id that fails to resolve decides the 404."

    Design: Difficulty/priority_pair_validation_conflict/visit_create_missing_field_and_unknown_property_returns_404
    """
    set_clock("2026-06-01T00:00:00Z")
    template = new_template("ROUTINE_WATCH", item_codes=["EXT_WALK"], critical_item_codes=[])
    response = api.create_visit(
        {
            "property_id": "00000000-0000-4000-8000-000000000001",
            "checklist_template_id": template["id"],
            "visit_type": "NOT_A_VISIT_TYPE",
            "trigger_source": "SCHEDULED",
            "scheduled_start_at": "2026-06-02T13:00:00Z",
            "scheduled_end_at": "2026-06-02T15:00:00Z",
        },
        DISPATCHER,
    )
    assert response.status_code == 404, f"expected 404, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_PROPERTY_NOT_FOUND.value)


# --------------------------------------------------------------------------
# The half-open padded turnover window
# --------------------------------------------------------------------------

def _turnover_property(**overrides):
    ctx = setup_subscribed_property(
        plan_overrides=STANDARD,
        property_overrides={"label": "Turnover Terrace", "address_line": "90 Buffer Blvd",
                            "travel_distance_miles": 18.0, "rental_program_enrolled": True},
        **overrides,
    )
    template = new_template("ROUTINE_WATCH", item_codes=["EXT_WALK"], critical_item_codes=[])
    turnover = new_rental_turnover(ctx["property_id"], checkout_at="2026-06-10T11:00:00Z",
                                   checkin_at="2026-06-12T15:00:00Z", guest_reference="BK-9001")
    ctx = dict(ctx)
    ctx["template"] = template
    ctx["turnover"] = turnover
    return ctx


def test_visit_ending_exactly_on_the_padded_low_edge_does_not_collide(api):
    """PRD 3.3: "The overlap test is **half-open and strict**: the visit collides when its
    `scheduled_start_at` is strictly before the padded high edge **and** its
    `scheduled_end_at` is strictly after the padded low edge."
    PRD 3.3: "Touching endpoints therefore do not collide — a visit ending exactly at the
    padded low edge does not overlap, and one starting exactly at the padded high edge
    does not overlap either."

    Design: Difficulty/boundary_precision_check/visit_window_touching_padded_turnover_edge_is_not_an_overlap
    """
    ctx = _turnover_property()
    touching = api.create_visit(
        create_visit_payload(ctx["property_id"], ctx["template"]["id"],
                             scheduled_start_at="2026-06-10T07:30:00Z",
                             scheduled_end_at="2026-06-10T09:30:00Z"),
        DISPATCHER,
    )
    created = validate_success(touching, 201)
    assert created["status"] == "SCHEDULED"

    colliding = api.create_visit(
        create_visit_payload(ctx["property_id"], ctx["template"]["id"],
                             scheduled_start_at="2026-06-10T07:31:00Z",
                             scheduled_end_at="2026-06-10T09:31:00Z"),
        DISPATCHER,
    )
    assert colliding.status_code == 409, f"expected 409, got {colliding.status_code}"
    validate_error(colliding, ApiErrorId.ERR_TURNOVER_WINDOW_OVERLAP.value)
    _, meta = validate_paginated(
        api.list_visits(headers=AUDITOR, params={"property_id": ctx["property_id"]})
    )
    assert meta["total_count"] == 1


def test_visit_starting_exactly_on_the_padded_high_edge_does_not_collide(api):
    """PRD 3.3: "Each such turnover is padded by ninety minutes on both sides: the padded
    low edge is its `checkout_at` less ninety minutes and the padded high edge is its
    `checkin_at` plus ninety minutes."
    PRD 3.3: "A collision at scheduling or rescheduling is rejected with
    `ERR_TURNOVER_WINDOW_OVERLAP`, HTTP 409."

    Design: Difficulty/boundary_precision_check/visit_window_touching_padded_turnover_edge_is_not_an_overlap
    """
    ctx = _turnover_property()
    touching = api.create_visit(
        create_visit_payload(ctx["property_id"], ctx["template"]["id"],
                             scheduled_start_at="2026-06-12T16:30:00Z",
                             scheduled_end_at="2026-06-12T18:30:00Z"),
        DISPATCHER,
    )
    created = validate_success(touching, 201)
    assert created["status"] == "SCHEDULED"

    inside = api.create_visit(
        create_visit_payload(ctx["property_id"], ctx["template"]["id"],
                             scheduled_start_at="2026-06-12T16:29:00Z",
                             scheduled_end_at="2026-06-12T18:29:00Z"),
        DISPATCHER,
    )
    validate_error(inside, ApiErrorId.ERR_TURNOVER_WINDOW_OVERLAP.value)


def test_reschedule_into_the_padded_window_is_rejected_and_leaves_the_visit_deferred(api):
    """PRD 3.4: "A visit in `DEFERRED` is returned to `SCHEDULED` by rescheduling, which
    supplies a fresh `scheduled_start_at` and `scheduled_end_at`, re-runs the
    turnover-overlap test against the new window, and clears `defer_reason` back to null."
    PRD 2.8: "A visit's scheduled window does not overlap any padded rental-turnover
    window of the same property. This applies to visit scheduling and to rescheduling.
    Otherwise `ERR_TURNOVER_WINDOW_OVERLAP`, HTTP 409."

    Design: Difficulty/resource_temporal_overlap/reschedule_into_padded_turnover_window_rejected_half_open_geometry
    """
    ctx = _turnover_property()
    visit = new_visit(ctx["property_id"], ctx["template"]["id"],
                      scheduled_start_at="2026-06-05T13:00:00Z",
                      scheduled_end_at="2026-06-05T15:00:00Z")
    validate_success(api.defer_visit(visit["id"], {"defer_reason": "WEATHER"}, DISPATCHER))

    response = api.reschedule_visit(
        visit["id"],
        {"scheduled_start_at": "2026-06-11T09:00:00Z", "scheduled_end_at": "2026-06-11T11:00:00Z"},
        DISPATCHER,
    )
    assert response.status_code == 409, f"expected 409, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_TURNOVER_WINDOW_OVERLAP.value)
    reread = refresh_visit(visit["id"])
    assert reread["status"] == "DEFERRED"
    assert_same_instant(reread["scheduled_start_at"], "2026-06-05T13:00:00Z", "scheduled_start_at")
    assert reread["deferral_count"] == 1


def test_reschedule_clear_of_the_padded_window_restores_the_visit(api):
    """PRD 3.4: "A dispatcher may **defer** a scheduled visit, moving it from `SCHEDULED`
    to `DEFERRED` and supplying a `defer_reason` from `TURNOVER_OVERLAP`,
    `OWNER_IN_RESIDENCE`, `WEATHER`, `ACCESS_BLOCKED` or `SUBSCRIPTION_PAUSED`"
    PRD 3.3: "Touching endpoints therefore do not collide — a visit ending exactly at the
    padded low edge does not overlap, and one starting exactly at the padded high edge
    does not overlap either."

    Design: Difficulty/resource_temporal_overlap/reschedule_into_padded_turnover_window_rejected_half_open_geometry
    """
    ctx = _turnover_property()
    visit = new_visit(ctx["property_id"], ctx["template"]["id"],
                      scheduled_start_at="2026-06-05T13:00:00Z",
                      scheduled_end_at="2026-06-05T15:00:00Z")
    validate_success(api.defer_visit(visit["id"], {"defer_reason": "WEATHER"}, DISPATCHER))

    rescheduled = validate_success(api.reschedule_visit(
        visit["id"],
        {"scheduled_start_at": "2026-06-10T07:30:00Z", "scheduled_end_at": "2026-06-10T09:30:00Z"},
        DISPATCHER,
    ))
    assert rescheduled["status"] == "SCHEDULED"
    assert rescheduled["defer_reason"] is None
    assert_same_instant(rescheduled["scheduled_end_at"], "2026-06-10T09:30:00Z",
                        "scheduled_end_at")
    assert rescheduled["deferral_count"] == 1
