"""Per-endpoint contract behaviour of the home-cook marketplace API.

The concern here is what each endpoint promises on its own surface: the
create-read-list round trip of a pickup hub, the preconditions an action
endpoint enforces before it will move a row, the idempotency of hub
consolidation, the linkage a refund event stores to the incident that justified
it, and the computed compliance projection.

The harness restarts the API server before every test, so each test builds its
whole world from scratch and the logical clock starts at its mandatory default
of 2026-08-01T00:00:00Z.
"""

from test_helpers import (
    ADMIN_HEADERS,
    ANONYMOUS_HEADERS,
    DINER_ONE_HEADERS,
    DINER_THREE_HEADERS,
    DINER_TWO_HEADERS,
    FINANCE_ONE_HEADERS,
    NON_EXISTENT_UUID,
    OFFICER_ONE_HEADERS,
    OFFICER_TWO_HEADERS,
    ApiErrorId,
    assert_common_fields,
    assert_fields,
    assert_order,
    assert_pickup_hub,
    assert_refund_event,
    assert_refund_three_bucket_identity,
    consolidate_payload,
    get_success_data,
    make_cook_headers,
    refund_event_payload,
    standing_action_payload,
    validate_error,
    validate_paginated,
)
from test_helpers import fixtures as fx

HUB_WINDOW_START = "2026-08-08T15:00:00Z"
HUB_WINDOW_END = "2026-08-08T19:00:00Z"
CUTOFF_AT = "2026-08-05T00:00:00Z"
SECOND_MISSING_UUID = "00000000-0000-4000-8000-000000008888"


def _hub_world(api):
    """A hub-pickup zone, a door-delivery zone in the same state, and one hub."""
    policy = fx.create_state_policy(api, state_code="CA")
    hub_zone = fx.create_delivery_zone(
        api,
        policy["id"],
        zone_code="OAK-HUB",
        state_code="CA",
        service_mode="HUB_PICKUP",
        postal_codes=["94607"],
        max_cold_chain_minutes=240,
    )
    door_zone = fx.create_delivery_zone(
        api,
        policy["id"],
        zone_code="SF-01",
        state_code="CA",
        service_mode="DOOR_DELIVERY",
        postal_codes=["94110"],
        max_cold_chain_minutes=240,
    )
    hub = fx.create_pickup_hub(
        api,
        hub_zone["id"],
        name="Jack London Square Hub",
        address="55 Water St, Oakland CA",
        slot_capacity_orders=4,
        hub_window_start_at=HUB_WINDOW_START,
        hub_window_end_at=HUB_WINDOW_END,
    )
    return policy, hub_zone, door_zone, hub


def test_01_pickup_hub_create_and_read_materialise_the_server_owned_fields(api):
    """Creating a hub mints status OPEN and a zero slot count, and the single read echoes them.

    PRD: "A hub is created in `status` `OPEN` with `assigned_order_count` at 0."
    Design: Corner/endpoints/pickup_hub_create_read_and_list_round_trip
    """
    _policy, hub_zone, _door_zone, hub = _hub_world(api)

    assert_common_fields(hub, expected_version=1)
    assert_pickup_hub(
        hub,
        delivery_zone_id=hub_zone["id"],
        name="Jack London Square Hub",
        address="55 Water St, Oakland CA",
        slot_capacity_orders=4,
        hub_window_start_at=HUB_WINDOW_START,
        hub_window_end_at=HUB_WINDOW_END,
        status="OPEN",
        assigned_order_count=0,
    )

    read = get_success_data(api.get_pickup_hub(hub["id"], ANONYMOUS_HEADERS), 200)
    assert_fields(
        read,
        id=hub["id"],
        delivery_zone_id=hub_zone["id"],
        slot_capacity_orders=4,
        status="OPEN",
        assigned_order_count=0,
    )
    assert read["created_at"] == hub["created_at"]


def test_02_pickup_hub_list_narrows_by_delivery_zone_and_status(api):
    """The hub collection read is an exact-match filter on delivery_zone_id and on status.

    PRD: "Delivery zones filter by `state_policy_id`, by `state_code` and by `service_mode`; pickup hubs filter by `delivery_zone_id` and by `status`."
    Design: Corner/endpoints/pickup_hub_create_read_and_list_round_trip
    """
    _policy, hub_zone, door_zone, hub = _hub_world(api)

    rows, meta = validate_paginated(
        api.list_pickup_hubs(
            DINER_ONE_HEADERS,
            {"delivery_zone_id": hub_zone["id"], "status": "OPEN", "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 1, f"expected exactly the one hub of the zone, got {meta}"
    assert meta["has_more"] is False, f"a single row leaves nothing beyond the page: {meta}"
    assert meta["limit"] == 10 and meta["offset"] == 0
    assert [row["id"] for row in rows] == [hub["id"]]

    empty_rows, empty_meta = validate_paginated(
        api.list_pickup_hubs(
            ANONYMOUS_HEADERS, {"delivery_zone_id": door_zone["id"], "limit": 10, "offset": 0}
        )
    )
    assert empty_meta["total_count"] == 0, (
        f"the door-delivery zone holds no hub, so the filtered count must be 0: {empty_meta}"
    )
    assert empty_rows == []


def _suspended_cook_with_open_incident(api):
    """An ACTIVE cook with one APPROVED dish, one INTAKE report, then SUSPENDED."""
    setup = fx.onboard_active_cook(api)
    item = fx.approved_menu_item(api, setup.cook)
    incident = fx.report_incident(
        api,
        setup.cook_id,
        reporter_headers=OFFICER_ONE_HEADERS,
        subject_type="COOK",
        category="TEMP_ABUSE",
        severity="MODERATE",
        description="cold holding above 5C at a market stall",
        occurred_at="2026-07-30T12:00:00Z",
    )
    suspended = fx.suspend_cook(api, setup.cook_id, reason="pending temperature-abuse review")
    return setup, item, incident, suspended


def test_03_reinstate_waits_for_the_open_incident_and_undelists_nothing(api):
    """REINSTATE is refused while a report sits in INTAKE, accepted once it is dismissed, and never revives a delisted dish.

    PRD: "An `action` of `REINSTATE` is available only from `SUSPENDED` and only when the cook has zero incidents in `INTAKE` or `TRIAGED`; it returns the cook to `CLEAR` but un-delists nothing."
    Design: Corner/endpoints/standing_action_endpoint_enforces_the_reinstate_precondition
    """
    setup, item, incident, suspended = _suspended_cook_with_open_incident(api)
    assert incident["status"] == "INTAKE", f"the report starts in INTAKE: {incident['status']!r}"
    assert_fields(
        suspended,
        compliance_standing="SUSPENDED",
        standing_reason="pending temperature-abuse review",
        onboarding_status="ACTIVE",
    )

    validate_error(
        api.cook_standing_action(
            setup.cook_id,
            standing_action_payload("REINSTATE", "cook says it was a thermometer fault"),
            OFFICER_ONE_HEADERS,
        ),
        ApiErrorId.INVALID_COOK_TRANSITION,
        409,
    )

    triaged = fx.triage_incident(api, incident["id"], "DISMISS", officer_headers=OFFICER_TWO_HEADERS)
    assert triaged["status"] == "DISMISSED", (
        f"DISMISS at triage empties the open-incident set: {triaged['status']!r}"
    )

    reinstated = get_success_data(
        api.cook_standing_action(
            setup.cook_id,
            standing_action_payload("REINSTATE", "incident dismissed at triage"),
            OFFICER_ONE_HEADERS,
        ),
        200,
    )
    assert_fields(
        reinstated,
        compliance_standing="CLEAR",
        standing_reason="incident dismissed at triage",
        onboarding_status="ACTIVE",
    )

    after = fx.read_menu_item(api, item["id"])
    assert_fields(after, review_status="DELISTED", delist_reason="COOK_SUSPENDED")


def test_04_reinstating_a_clear_cook_is_an_invalid_cook_transition(api):
    """Each accepted standing action bumps the cook's version, and a second REINSTATE from CLEAR is refused.

    PRD: "All four increment the cook's `version`, and any action that is not declared from the cook's current standing — reinstating a `CLEAR` cook, revoking a `WARNED` one, or anything at all against `REVOKED` — is `ERR_INVALID_COOK_TRANSITION`."
    Design: Corner/endpoints/standing_action_endpoint_enforces_the_reinstate_precondition
    """
    setup, _item, incident, suspended = _suspended_cook_with_open_incident(api)
    fx.triage_incident(api, incident["id"], "DISMISS", officer_headers=OFFICER_TWO_HEADERS)

    reinstated = get_success_data(
        api.cook_standing_action(
            setup.cook_id,
            standing_action_payload("REINSTATE", "incident dismissed at triage"),
            OFFICER_ONE_HEADERS,
        ),
        200,
    )
    assert reinstated["version"] == suspended["version"] + 1, (
        f"reinstatement increments version: {suspended['version']} -> {reinstated['version']}"
    )
    assert reinstated["compliance_standing"] == "CLEAR"

    validate_error(
        api.cook_standing_action(
            setup.cook_id,
            standing_action_payload("REINSTATE", "double click"),
            OFFICER_ONE_HEADERS,
        ),
        ApiErrorId.INVALID_COOK_TRANSITION,
        409,
    )
    unchanged = fx.read_cook(api, setup.cook_id)
    assert_fields(unchanged, compliance_standing="CLEAR", onboarding_status="ACTIVE")
    assert unchanged["version"] == reinstated["version"], (
        "a rejected standing action must not touch the row"
    )


def _hub_routing_world(api):
    """A hub-pickup zone, one hub with three slots, and three single-meal orders."""
    setup = fx.selling_cook(
        api,
        item_overrides={"unit_price_cents": 400},
        window_overrides={"capacity_meals": 20},
        zone_overrides={
            "zone_code": "OAK-HUB",
            "service_mode": "HUB_PICKUP",
            "postal_codes": ["94607"],
            "max_cold_chain_minutes": 240,
        },
    )
    hub = fx.create_pickup_hub(
        api,
        setup.zone["id"],
        name="Jack London Square Hub",
        address="55 Water St, Oakland CA",
        slot_capacity_orders=3,
        hub_window_start_at=HUB_WINDOW_START,
        hub_window_end_at=HUB_WINDOW_END,
    )
    orders = [
        fx.order_in_scenario(api, setup, quantity=1, diner_headers=headers)
        for headers in (DINER_ONE_HEADERS, DINER_TWO_HEADERS, DINER_THREE_HEADERS)
    ]
    return setup, hub, orders


def test_05_consolidation_before_the_cutoff_is_rejected(api):
    """Consolidating a window that has not yet reached its order cutoff is refused.

    PRD: "The window must have reached its `order_cutoff_at` (`ERR_CUTOFF_NOT_REACHED`)."
    Design: Corner/endpoints/hub_consolidation_is_idempotent_and_waits_for_the_cutoff
    """
    setup, hub, orders = _hub_routing_world(api)
    fx.route_order(api, orders[0]["id"])
    fx.route_order(api, orders[1]["id"])

    validate_error(
        api.consolidate_pickup_hub(
            hub["id"], consolidate_payload(setup.window["id"]), ADMIN_HEADERS
        ),
        ApiErrorId.CUTOFF_NOT_REACHED,
        409,
    )

    untouched = fx.read_hub(api, hub["id"])
    assert_fields(untouched, assigned_order_count=2, status="OPEN")


def test_06_consolidating_already_attached_orders_moves_no_slot_counter(api):
    """Re-running consolidation over orders the router already parked on the hub changes nothing.

    PRD: "It sets `pickup_hub_id` on every eligible order of the window whose `pickup_hub_id` is not already this hub, and it increases the hub's `assigned_order_count` by the count of **newly attached** orders only — re-running the same consolidation therefore changes nothing."
    Design: Corner/endpoints/hub_consolidation_is_idempotent_and_waits_for_the_cutoff
    """
    setup, hub, orders = _hub_routing_world(api)
    first = fx.route_order(api, orders[0]["id"])
    second = fx.route_order(api, orders[1]["id"])
    assert first["pickup_hub_id"] == hub["id"], "the only eligible hub takes the first order"
    assert second["pickup_hub_id"] == hub["id"], "the only eligible hub takes the second order"
    assert first["total_charge_cents"] == 436, (
        f"400 subtotal + 36 diner fee + 0 cold-chain surcharge: {first['total_charge_cents']}"
    )

    fx.set_clock(api, CUTOFF_AT)
    fx.advance_window(api, setup.window, "CUTOFF_PASSED")

    payload = consolidate_payload(setup.window["id"])
    run_one = get_success_data(
        api.consolidate_pickup_hub(hub["id"], payload, FINANCE_ONE_HEADERS), 200
    )
    assert_fields(
        run_one,
        pickup_hub_id=hub["id"],
        production_window_id=setup.window["id"],
        consolidated_order_count=2,
        assigned_order_count=2,
        status="OPEN",
    )

    run_two = get_success_data(
        api.consolidate_pickup_hub(hub["id"], payload, FINANCE_ONE_HEADERS), 200
    )
    assert_fields(
        run_two,
        pickup_hub_id=hub["id"],
        production_window_id=setup.window["id"],
        consolidated_order_count=2,
        assigned_order_count=2,
        status="OPEN",
    )

    fresh = fx.read_hub(api, hub["id"])
    assert_fields(fresh, assigned_order_count=2, status="OPEN")


def test_07_consolidation_reports_the_eligible_set_and_closes_a_full_hub(api):
    """The reported count follows the window's eligible orders, and the hub closes once its slots are full.

    PRD: "The response reports `pickup_hub_id`, `production_window_id`, a `consolidated_order_count` giving the number of eligible orders of that window now attached to this hub whether newly attached or already attached, the resulting `assigned_order_count`, and the resulting `status`, which becomes `CLOSED` if the accumulated count reached `slot_capacity_orders`."
    Design: Corner/endpoints/hub_consolidation_is_idempotent_and_waits_for_the_cutoff
    """
    setup, hub, orders = _hub_routing_world(api)
    fx.route_order(api, orders[0]["id"])
    fx.route_order(api, orders[1]["id"])

    fx.set_clock(api, CUTOFF_AT)
    fx.advance_window(api, setup.window, "CUTOFF_PASSED")
    get_success_data(
        api.consolidate_pickup_hub(
            hub["id"], consolidate_payload(setup.window["id"]), FINANCE_ONE_HEADERS
        ),
        200,
    )

    third = fx.route_order(api, orders[2]["id"])
    assert third["pickup_hub_id"] == hub["id"], "the third route consumes the last free slot"

    run_three = get_success_data(
        api.consolidate_pickup_hub(
            hub["id"], consolidate_payload(setup.window["id"]), ADMIN_HEADERS
        ),
        200,
    )
    assert_fields(
        run_three,
        pickup_hub_id=hub["id"],
        production_window_id=setup.window["id"],
        consolidated_order_count=3,
        assigned_order_count=3,
        status="CLOSED",
    )

    fresh = fx.read_hub(api, hub["id"])
    assert_fields(fresh, assigned_order_count=3, status="CLOSED")


def _captured_order_with_substantiated_incident(api):
    """A DELIVERED and CAPTURED order on a CLOSED window, plus a SUBSTANTIATED report on it."""
    setup = fx.handed_off_order_scenario(api, quantity=2, item_overrides={"unit_price_cents": 400})
    order = fx.deliver_order(api, setup.order)
    fx.close_window(api, setup)
    incident = fx.substantiated_incident(
        api,
        setup.cook_id,
        subject_type="ORDER",
        order_id=order["id"],
        category="FOODBORNE_ILLNESS",
        severity="MODERATE",
        description="two diners reported stomach upset",
        occurred_at="2026-08-08T20:00:00Z",
    )
    order = fx.read_order(api, order["id"])
    assert_order(
        order,
        subtotal_cents=800,
        platform_commission_cents=180,
        cook_earnings_cents=620,
        total_charge_cents=872,
        payment_status="CAPTURED",
        refunded_cents=0,
    )
    assert incident["status"] == "SUBSTANTIATED", (
        f"the refund's justification must be substantiated: {incident['status']!r}"
    )
    return setup, order, incident


def test_08_a_safety_refund_without_its_incident_reference_is_invalid(api):
    """A refund whose reason is SAFETY must carry safety_incident_id in the body.

    PRD: "When `reason` is `SAFETY`, `safety_incident_id` is required and must name the substantiated incident that justifies the refund; for every other reason it is optional."
    Design: Corner/endpoints/refund_event_links_its_substantiated_incident_and_rejects_an_unknown_one
    """
    _setup, order, _incident = _captured_order_with_substantiated_incident(api)

    validate_error(
        api.create_refund_event(
            refund_event_payload(
                order["id"],
                reason="SAFETY",
                fault_party="COOK",
                refund_amount_cents=200,
                settle_immediately=True,
            ),
            FINANCE_ONE_HEADERS,
        ),
        ApiErrorId.INVALID_REQUEST,
        422,
    )

    # The same payload under a non-safety reason needs no incident at all.
    accepted = get_success_data(
        api.create_refund_event(
            refund_event_payload(
                order["id"],
                reason="QUALITY",
                fault_party="COOK",
                refund_amount_cents=200,
                settle_immediately=True,
            ),
            FINANCE_ONE_HEADERS,
        ),
        201,
    )
    assert_refund_event(accepted, reason="QUALITY", safety_incident_id=None)


def test_09_refund_body_foreign_keys_resolve_left_to_right(api):
    """An unresolvable incident reference is the incident 404, and a bad order_id masks it.

    PRD: "Second, every foreign-key identifier supplied in the request body is resolved **left to right in the order the endpoint declares its inputs**, so that when a payload carries two bad references the error reported is the one belonging to the earlier field."
    Design: Corner/endpoints/refund_event_links_its_substantiated_incident_and_rejects_an_unknown_one
    """
    _setup, order, _incident = _captured_order_with_substantiated_incident(api)

    validate_error(
        api.create_refund_event(
            refund_event_payload(
                order["id"],
                reason="SAFETY",
                fault_party="COOK",
                refund_amount_cents=200,
                settle_immediately=True,
                safety_incident_id=NON_EXISTENT_UUID,
            ),
            FINANCE_ONE_HEADERS,
        ),
        ApiErrorId.INCIDENT_NOT_FOUND,
        404,
    )

    validate_error(
        api.create_refund_event(
            refund_event_payload(
                SECOND_MISSING_UUID,
                reason="SAFETY",
                fault_party="COOK",
                refund_amount_cents=200,
                settle_immediately=True,
                safety_incident_id=NON_EXISTENT_UUID,
            ),
            FINANCE_ONE_HEADERS,
        ),
        ApiErrorId.ORDER_NOT_FOUND,
        404,
    )


def test_10_settled_refund_stores_its_incident_link_and_charges_the_cook_bucket(api):
    """settle_immediately lands the refund in SETTLED with its incident association persisted.

    PRD: "A refund event is created in `status` `PENDING` unless `settle_immediately` is true, in which case it is created and immediately moved `PENDING → SETTLED` with `settled_at` stamped from the logical clock."
    Design: Corner/endpoints/refund_event_links_its_substantiated_incident_and_rejects_an_unknown_one
    """
    setup, order, incident = _captured_order_with_substantiated_incident(api)

    refund = get_success_data(
        api.create_refund_event(
            refund_event_payload(
                order["id"],
                reason="SAFETY",
                fault_party="COOK",
                refund_amount_cents=200,
                settle_immediately=True,
                safety_incident_id=incident["id"],
            ),
            FINANCE_ONE_HEADERS,
        ),
        201,
    )
    assert_refund_event(
        refund,
        order_id=order["id"],
        safety_incident_id=incident["id"],
        reason="SAFETY",
        fault_party="COOK",
        refund_amount_cents=200,
        status="SETTLED",
        created_by_user_id="fin-1",
        # A COOK-fault waterfall drains the cook bucket first: capacity 620 covers 200.
        cook_chargeback_cents=200,
        commission_reversed_cents=0,
        platform_absorbed_cents=0,
    )
    assert refund["settled_at"] is not None, "settle_immediately stamps settled_at"
    assert_refund_three_bucket_identity(refund)

    stored = get_success_data(
        api.get_refund_event(refund["id"], make_cook_headers(setup.cook_id)), 200
    )
    assert_fields(stored, safety_incident_id=incident["id"], order_id=order["id"], status="SETTLED")


def test_11_a_partial_refund_moves_the_order_and_the_cooks_pending_payout(api):
    """Two hundred cents against an 872-cent charge leaves the order PARTIALLY_REFUNDED.

    PRD: "Recording a refund moves the order's `payment_status` forward: `CAPTURED → PARTIALLY_REFUNDED` when the order's accumulated `refunded_cents` plus this refund amount is strictly less than the order's `total_charge_cents`, and `CAPTURED → REFUNDED` when the two are exactly equal."
    Design: Corner/endpoints/refund_event_links_its_substantiated_incident_and_rejects_an_unknown_one
    """
    setup, order, incident = _captured_order_with_substantiated_incident(api)
    before = fx.read_cook(api, setup.cook_id)
    assert before["pending_payout_cents"] == 620, (
        f"one captured order's cook earnings sit pending: {before['pending_payout_cents']}"
    )

    get_success_data(
        api.create_refund_event(
            refund_event_payload(
                order["id"],
                reason="SAFETY",
                fault_party="COOK",
                refund_amount_cents=200,
                settle_immediately=True,
                safety_incident_id=incident["id"],
            ),
            FINANCE_ONE_HEADERS,
        ),
        201,
    )

    after = fx.read_order(api, order["id"])
    assert_order(
        after,
        payment_status="PARTIALLY_REFUNDED",
        refunded_cents=200,
        cook_chargeback_cents=200,
        commission_reversed_cents=0,
        platform_absorbed_cents=0,
        fulfillment_status="DELIVERED",
    )

    cook = fx.read_cook(api, setup.cook_id)
    assert cook["pending_payout_cents"] == 420, (
        f"pending payout is cook earnings less the chargeback: {cook['pending_payout_cents']}"
    )


def _cook_with_a_mixed_incident_record(api):
    """One captured 800-cent order plus four incidents, one in each terminal state.

    The MODERATE report is substantiated (12 points at full weight), a SEVERE one
    is left in INTAKE, a MINOR one is dismissed at triage and a CRITICAL one is
    adjudicated away as unsubstantiated. Every incident is created while the clock
    reads 2026-08-08, so all of them are zero weeks old and carry full weight.
    """
    setup = fx.handed_off_order_scenario(api, quantity=2, item_overrides={"unit_price_cents": 400})
    order = fx.deliver_order(api, setup.order)
    fx.close_window(api, setup)

    substantiated = fx.substantiated_incident(
        api,
        setup.cook_id,
        subject_type="ORDER",
        order_id=order["id"],
        category="FOODBORNE_ILLNESS",
        severity="MODERATE",
        description="two diners reported stomach cramps after the handoff",
        occurred_at="2026-08-08T13:00:00Z",
        reporter_headers=DINER_ONE_HEADERS,
    )

    intake = fx.report_incident(
        api,
        setup.cook_id,
        reporter_headers=OFFICER_ONE_HEADERS,
        subject_type="COOK",
        category="TEMP_ABUSE",
        severity="SEVERE",
        description="cooler logged at 12C during an unannounced spot check",
        occurred_at="2026-08-08T14:00:00Z",
    )

    dismissed_report = fx.report_incident(
        api,
        setup.cook_id,
        reporter_headers=DINER_TWO_HEADERS,
        subject_type="MENU_ITEM",
        menu_item_id=setup.menu_item["id"],
        category="LABEL_MISSING",
        severity="MINOR",
        description="the photo of the label looks like it is missing a net weight",
        occurred_at="2026-08-08T15:00:00Z",
    )
    dismissed = fx.triage_incident(api, dismissed_report["id"], "DISMISS")

    unsubstantiated_report = fx.report_incident(
        api,
        setup.cook_id,
        reporter_headers=DINER_THREE_HEADERS,
        subject_type="COOK",
        category="FOREIGN_OBJECT",
        severity="CRITICAL",
        description="a metal fragment was alleged to have been found in a portion",
        occurred_at="2026-08-08T15:30:00Z",
    )
    fx.triage_incident(api, unsubstantiated_report["id"], "ACCEPT")
    unsubstantiated = fx.adjudicate_incident(
        api,
        unsubstantiated_report["id"],
        "DISMISS",
        resolution_note="the fragment came from the diner's own pepper grinder",
    )

    assert_fields(substantiated, status="SUBSTANTIATED", severity_points=12)
    assert_fields(intake, status="INTAKE", severity_points=25)
    assert_fields(dismissed, status="DISMISSED", severity_points=0)
    assert_fields(unsubstantiated, status="UNSUBSTANTIATED", severity_points=0)
    return setup, order


def test_12_compliance_summary_projects_the_cooks_standing_cap_and_counts(api):
    """The computed read reports the authoritative score, the cap headroom and the three counts.

    PRD: "The response reports `cook_id`, the authoritative `safety_score` beside the advisory `provisional_safety_score`, the current `compliance_standing` and `cap_status`, the recognised `ytd_cottage_revenue_cents`, a `cap_remaining_cents` giving the headroom left under the state's annual cap, an `open_incident_count` covering incidents in `INTAKE` or `TRIAGED`, a `substantiated_incident_count`, and an `approved_menu_item_count`."
    Design: Corner/endpoints/compliance_summary_computed_read_matches_both_score_variants
    """
    setup, _order = _cook_with_a_mixed_incident_record(api)

    summary = get_success_data(
        api.get_compliance_summary(setup.cook_id, make_cook_headers(setup.cook_id)), 200
    )
    assert_fields(
        summary,
        cook_id=setup.cook_id,
        # 100 less the single substantiated MODERATE charge of 12 at full weight.
        safety_score=88,
        compliance_standing="CLEAR",
        cap_status="UNDER_CAP",
        # The one captured order recognises its 800-cent subtotal against the cap.
        ytd_cottage_revenue_cents=800,
        cap_remaining_cents=4_999_200,
        # Only the SEVERE report is still in INTAKE or TRIAGED.
        open_incident_count=1,
        substantiated_incident_count=1,
        approved_menu_item_count=1,
    )
    assert isinstance(summary["cap_remaining_cents"], int) and not isinstance(
        summary["cap_remaining_cents"], bool
    ), f"cap_remaining_cents must be integer cents: {summary['cap_remaining_cents']!r}"
    assert "provisional_safety_score" in summary, (
        f"the advisory score is reported beside the authoritative one: {sorted(summary)}"
    )

    cook = fx.read_cook(api, setup.cook_id)
    assert_fields(
        cook,
        safety_score=summary["safety_score"],
        compliance_standing=summary["compliance_standing"],
        cap_status=summary["cap_status"],
        ytd_cottage_revenue_cents=summary["ytd_cottage_revenue_cents"],
    )


def test_13_advisory_score_charges_the_open_intake_at_half_weight(api):
    """The provisional score adds half of the untriaged SEVERE report to the substantiated charge.

    PRD: "It takes the same substantiated charge at full decayed weight and adds, for every incident whose `status` is `INTAKE` or `TRIAGED`, that incident's decayed points multiplied by a half-weight of 0.5; the sum is again rounded half up exactly once, subtracted from 100 and floored at zero."
    Design: Corner/endpoints/compliance_summary_computed_read_matches_both_score_variants
    """
    setup, _order = _cook_with_a_mixed_incident_record(api)

    summary = get_success_data(
        api.get_compliance_summary(setup.cook_id, OFFICER_ONE_HEADERS), 200
    )
    # 12 substantiated + 0.5 * 25 open = 24.5, rounded half up once to 25, so 100 - 25.
    assert_fields(summary, provisional_safety_score=75, safety_score=88)
    assert summary["provisional_safety_score"] <= summary["safety_score"], (
        "the advisory score sits at or below the authoritative one while an "
        f"un-adjudicated report exists: {summary['provisional_safety_score']} vs "
        f"{summary['safety_score']}"
    )


def _door_delivery_world_with_two_orders(api):
    """An OPEN window carrying a two-meal order and a one-meal order, nothing routed.

    The dish is priced at 400 cents so the two-meal order charges 800 cents of
    subtotal, and the window is roomy enough that both orders are admitted.
    """
    setup = fx.selling_cook(
        api,
        item_overrides={"unit_price_cents": 400},
        window_overrides={"capacity_meals": 20},
    )
    order_a = fx.order_in_scenario(api, setup, quantity=2, diner_headers=DINER_ONE_HEADERS)
    order_b = fx.order_in_scenario(api, setup, quantity=1, diner_headers=DINER_TWO_HEADERS)
    assert_fields(order_a, fulfillment_status="PLACED", subtotal_cents=800)
    assert_fields(order_b, fulfillment_status="PLACED", subtotal_cents=400)
    return setup, order_a, order_b


def test_14_routing_moves_a_placed_order_once_and_refuses_a_second_attempt(api):
    """The route endpoint carries PLACED to ROUTED and rejects a repeat of itself.

    PRD: "Routing is the step that decides *how* a meal will physically reach its diner, and it moves the order `PLACED → ROUTED`."
    Design: Corner/endpoints/route_is_conditional_on_window_status_and_cannot_repeat
    """
    _setup, order_a, _order_b = _door_delivery_world_with_two_orders(api)

    routed = get_success_data(api.route_order(order_a["id"], ADMIN_HEADERS), 200)
    assert_order(
        routed,
        fulfillment_status="ROUTED",
        payment_status="AUTHORIZED",
        # A batch-cook-and-chill dish on a two-hour door-delivery window never
        # qualifies for the same-day hot path.
        routing_mode="BATCH_COOK_AND_CHILL",
        # The dish needs no refrigeration, so no surcharge lands and the charge
        # stays at the 800-cent subtotal plus the 72-cent service fee.
        cold_chain_surcharge_cents=0,
        subtotal_cents=800,
        diner_service_fee_cents=72,
        total_charge_cents=872,
    )

    validate_error(
        api.route_order(order_a["id"], ADMIN_HEADERS),
        ApiErrorId.INVALID_ORDER_TRANSITION,
        409,
    )

    unchanged = fx.read_order(api, order_a["id"])
    assert_fields(
        unchanged,
        fulfillment_status="ROUTED",
        routing_mode="BATCH_COOK_AND_CHILL",
        total_charge_cents=872,
    )


def test_15_entering_production_sweeps_the_order_that_was_never_routed(api):
    """The unrouted order is cancelled and voided while the routed one is left alone.

    PRD: "`CUTOFF_PASSED → IN_PRODUCTION` requires that the cook's `compliance_standing` be neither `SUSPENDED` nor `REVOKED`, and carries a conditional cascade: every order on the window still sitting in `PLACED` — that is, never routed — moves to `CANCELLED` with `cancelled_reason` `WINDOW_CANCELLED`, its `payment_status` moves `AUTHORIZED → VOIDED`, and `committed_meals` is decremented by that order's `quantity`."
    Design: Corner/endpoints/route_is_conditional_on_window_status_and_cannot_repeat
    """
    setup, order_a, order_b = _door_delivery_world_with_two_orders(api)
    fx.route_order(api, order_a["id"])
    before = fx.read_window(api, setup.window["id"])
    assert_fields(before, committed_meals=3)

    fx.set_clock(api, CUTOFF_AT)
    window = fx.advance_window(api, before, "CUTOFF_PASSED")
    window = fx.advance_window(api, window, "IN_PRODUCTION")
    assert_fields(window, status="IN_PRODUCTION", committed_meals=2)

    swept = fx.read_order(api, order_b["id"])
    assert_order(
        swept,
        fulfillment_status="CANCELLED",
        cancelled_reason="WINDOW_CANCELLED",
        payment_status="VOIDED",
    )

    survivor = fx.read_order(api, order_a["id"])
    assert_fields(survivor, fulfillment_status="ROUTED", payment_status="AUTHORIZED")

    validate_error(
        api.route_order(order_b["id"], ADMIN_HEADERS),
        ApiErrorId.INVALID_ORDER_TRANSITION,
        409,
    )
