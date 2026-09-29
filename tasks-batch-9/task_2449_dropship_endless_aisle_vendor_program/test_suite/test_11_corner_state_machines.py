"""State-machine behaviour of the dropship program.

Initial states, legal transitions, transitions refused because the row is in the
wrong state, terminal-state lockdown, and the multi-hop cascades a vendor
suspension, a vendor reinstatement, a line cancellation and a feed message set
off across coverage rows, offers, lines and orders.
"""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    acknowledge_payload,
    create_active_item,
    create_certified_vendor,
    create_draft_item,
    create_draft_vendor,
    create_integration_test_payload,
    create_inventory_snapshot_payload,
    evaluate_integration_test_payload,
    get_success_data,
    make_merchandise_manager_headers,
    make_vendor_ops_analyst_headers,
    make_vendor_user_headers,
    open_return,
    order_line_input,
    order_lines_of,
    place_and_transmit_order,
    place_order,
    publish_seeded_scorecard,
    refresh_item,
    refresh_line,
    refresh_order,
    refresh_return,
    refresh_vendor,
    reject_return_payload,
    set_clock,
    setup_shipped_line,
    setup_vendor_with_active_offer,
    ship_confirm,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["vendor_ops_analyst_headers"]
MM = TEST_USERS["merchandise_manager_headers"]


# ─── Module-private setup helpers ─────────────────────


def _active_offer_with_untransmitted_line(api, suffix, order_ref):
    """An ACTIVE vendor and offer carrying one PENDING_TRANSMIT line of 2 units."""
    base = setup_vendor_with_active_offer(api, suffix=suffix)
    order = place_order(api, base["item_id"], quantity=2, order_ref=order_ref)
    line = order_lines_of(api, order["id"])[0]
    return {
        **base,
        "order_id": order["id"],
        "line_id": line["id"],
    }


def _vendor_with_cascade_and_manual_offers(api, suffix):
    """One ACTIVE offer plus a second offer an operator suppressed by hand."""
    base = setup_vendor_with_active_offer(api, suffix=suffix)
    manual = create_active_item(
        api,
        base["vendor_id"],
        sku="SKU-MANUAL-8",
        unit_retail_cents=3000,
    )
    get_success_data(api.suppress_item(manual["id"], MM))
    return {**base, "manual_item_id": manual["id"]}


# ─── Declared initial states ──────────────────────────


def test_new_offer_is_born_in_draft_with_zero_availability(api):
    """PRD §3.3: "A new offer is born in `status` `DRAFT` with `suppression_reason` null, `reserved_units` at 0, `effective_on_hand_units` at 0, `available_units` at 0, `inventory_is_stale` true (nothing has been fed yet), `last_inventory_refresh_at` null, and `lifetime_reserved_units`, `lifetime_released_units` and `lifetime_shipped_units` all at 0."

    A freshly created offer sits in its declared initial state before any feed
    message has arrived: no availability, a stale feed and every counter at 0.

    Design: Corner/state_machines/corner_new_item_and_integration_test_start_in_their_declared_initial_states
    """
    vendor = create_certified_vendor(api, suffix="OFFER-INIT")

    item = create_draft_item(api, vendor["id"], sku="SKU-INIT-1", unit_retail_cents=4000)

    assert item["status"] == "DRAFT"
    assert item["suppression_reason"] is None
    assert item["available_units"] == 0
    assert item["effective_on_hand_units"] == 0
    assert item["reserved_units"] == 0
    assert item["inventory_is_stale"] is True
    assert item["last_inventory_refresh_at"] is None
    assert item["lifetime_reserved_units"] == 0
    assert item["lifetime_released_units"] == 0
    assert item["lifetime_shipped_units"] == 0
    assert item["version"] == 1


def test_recorded_integration_test_starts_pending_at_the_current_round(api):
    """PRD §3.1: "The run is created with `status` `PENDING`, and its `round_number` is copied from the vendor's `integration_round` at creation time, freezing the run to that round forever."

    Recording a test run against a vendor whose integration_round is 1 lands the
    run in PENDING at round 1 with no evaluation stamped on it yet.

    Design: Corner/state_machines/corner_new_item_and_integration_test_start_in_their_declared_initial_states
    """
    vendor = create_draft_vendor(api, suffix="TEST-INIT")
    get_success_data(api.begin_integration(vendor["id"], OPS))

    run = validate_success(
        api.record_integration_test(
            vendor["id"],
            create_integration_test_payload("CATALOG"),
            make_vendor_ops_analyst_headers("ops-recorder-init"),
        ),
        201,
    )

    assert run["status"] == "PENDING"
    assert run["round_number"] == 1
    assert run["evaluated_at"] is None
    assert run["evaluated_by_user_id"] is None


# ─── Declared transitions ─────────────────────────────


def test_begin_integration_moves_draft_vendor_to_integration_testing(api):
    """PRD §3.1: "A `VendorOpsAnalyst` opening integration on a `DRAFT` vendor moves it `DRAFT → INTEGRATION_TESTING` and sets `integration_round` to 1, clearing `certified_by_user_id` back to null in the same write."

    The first lifecycle transition of a vendor also bumps its version from the
    1 it was created with to 2.

    Design: Corner/state_machines/corner_begin_integration_moves_vendor_from_draft_to_integration_testing
    """
    vendor = create_draft_vendor(api, suffix="BEGIN")
    assert vendor["onboarding_status"] == "DRAFT"
    assert vendor["version"] == 1

    moved = validate_success(api.begin_integration(vendor["id"], OPS))

    assert moved["onboarding_status"] == "INTEGRATION_TESTING"
    assert moved["integration_round"] == 1
    assert moved["certified_by_user_id"] is None
    assert moved["version"] == 2


# ─── Transitions refused by the row's state ───────────


def test_certify_from_draft_is_refused_as_invalid_vendor_state(api):
    """PRD §2.6: "The vendor's `onboarding_status` permits the requested transition: begin-integration from `DRAFT` or `INTEGRATION_TESTING`, certification from `INTEGRATION_TESTING`, activation from `CERTIFIED`, suspension from `ACTIVE`, reinstatement from `SUSPENDED`."

    Certification is declared only out of INTEGRATION_TESTING, and the state check
    outranks the integration-completeness check, so a DRAFT vendor with no test
    runs at all still answers ERR_VENDOR_INVALID_STATE.

    Design: Corner/state_machines/corner_vendor_certify_from_draft_is_rejected
    """
    vendor = create_draft_vendor(api, suffix="EARLY")

    response = api.certify_vendor(
        vendor["id"], make_vendor_ops_analyst_headers("ops-certifier-early")
    )

    validate_error(response, ApiErrorId.ERR_VENDOR_INVALID_STATE.value)
    after = refresh_vendor(api, vendor["id"])
    assert after["onboarding_status"] == "DRAFT"
    assert after["certified_by_user_id"] is None
    assert after["version"] == 1


def test_certify_with_three_of_four_message_families_is_refused(api):
    """PRD §3.1: "Moving a vendor `INTEGRATION_TESTING → CERTIFIED` requires that for every one of the four message families there exists a test run of this vendor at the current `integration_round` whose `status` is `PASSED`; if even one family is missing its pass, certification is refused with `ERR_INTEGRATION_INCOMPLETE`."

    CATALOG, INVENTORY and ORDER all pass while SHIP_CONFIRM was never recorded,
    so the precondition is per-message-family coverage and not a count of passes.

    Design: Corner/state_machines/corner_vendor_certify_with_incomplete_message_matrix_is_rejected
    """
    vendor = create_draft_vendor(api, suffix="PARTIAL")
    get_success_data(api.begin_integration(vendor["id"], OPS))
    recorder = make_vendor_ops_analyst_headers("ops-recorder-partial")
    evaluator = make_vendor_ops_analyst_headers("ops-evaluator-partial")
    for message_type in ("CATALOG", "INVENTORY", "ORDER"):
        run = get_success_data(
            api.record_integration_test(
                vendor["id"], create_integration_test_payload(message_type), recorder
            )
        )
        get_success_data(
            api.evaluate_integration_test(
                run["id"], evaluate_integration_test_payload("PASS"), evaluator
            )
        )

    response = api.certify_vendor(
        vendor["id"], make_vendor_ops_analyst_headers("ops-certifier-partial")
    )

    validate_error(response, ApiErrorId.ERR_INTEGRATION_INCOMPLETE.value)
    after = refresh_vendor(api, vendor["id"])
    assert after["onboarding_status"] == "INTEGRATION_TESTING"
    assert after["certified_by_user_id"] is None
    runs = get_success_data(
        api.list_integration_tests(vendor["id"], ADMIN, params={"limit": 100})
    )
    assert len(runs) == 3
    assert all(run["status"] == "PASSED" for run in runs)


def test_second_offer_activation_is_refused_and_leaves_the_offer_untouched(api):
    """PRD §2.6: "The offer's `status` permits the requested transition: activation from `DRAFT` or `SUPPRESSED`, suppression from `ACTIVE`, amendment only from `DRAFT` or `SUPPRESSED`; and a suppressed offer may only be restored through the path that owns its `suppression_reason`."

    Replaying activation against an already-ACTIVE offer is a state error rather
    than a no-op success, and the refused call writes nothing, so the offer's
    version stays at the value its single successful activation left behind.

    Design: Corner/state_machines/corner_item_activate_twice_second_call_is_rejected
    """
    base = setup_vendor_with_active_offer(api, suffix="TWICE", feed=False)
    item = refresh_item(api, base["item_id"])
    assert item["status"] == "ACTIVE"
    assert item["version"] == 2

    response = api.activate_item(base["item_id"], MM)

    validate_error(response, ApiErrorId.ERR_ITEM_INVALID_STATE.value)
    after = refresh_item(api, base["item_id"])
    assert after["status"] == "ACTIVE"
    assert after["version"] == 2


def test_receive_on_a_rejected_return_is_refused(api):
    """PRD §2.6: "The return's `status` permits the requested transition: authorization from `REQUESTED`, receipt from `AUTHORIZED`, rejection from either `REQUESTED` or `AUTHORIZED`."

    REJECTED is the end of the road for a return: receipt is declared only out of
    AUTHORIZED, so it cannot be used to walk a rejected return forward, and the
    order's financial axis is left where the shipment put it.

    Design: Corner/state_machines/corner_return_receive_from_rejected_terminal_state_is_rejected
    """
    state = setup_shipped_line(api, quantity=1, order_ref="ORD-TERM-1", suffix="TERM")
    ra = open_return(api, state["line_id"], quantity_returned=1, reason_code="BUYER_REMORSE")
    get_success_data(api.reject_return(ra["id"], reject_return_payload("POLICY"), MM))

    response = api.receive_return(ra["id"], ADMIN, {"restocked_units": 1})

    validate_error(response, ApiErrorId.ERR_RETURN_INVALID_STATE.value)
    after = refresh_return(api, ra["id"])
    assert after["status"] == "REJECTED"
    assert after["restocked_units"] == 0
    assert refresh_order(api, state["order_id"])["financial_status"] == "CAPTURED"


# ─── Suspension and reinstatement cascades ────────────


def test_manual_suspension_runs_all_four_cascade_hops(api):
    """PRD §3.9: "A manual suspension by a `MerchandiseManager` is legal only from `ACTIVE`, sets `suspension_reason` to `MANUAL_OPS` instead, and runs exactly the same four hops."

    One request must take down the coverage row, suppress the offer, push the
    untransmitted line to BACKORDERED and re-derive the owning order — an
    implementation that stops after the vendor row has not performed the
    operation.

    Design: Corner/state_machines/corner_vendor_suspend_runs_all_four_declared_cascade_hops
    """
    state = _active_offer_with_untransmitted_line(api, "SUSP", "ORD-SUSP-1")

    response = api.suspend_vendor(
        state["vendor_id"], make_merchandise_manager_headers("mm-suspender-1")
    )

    validate_success(response)
    vendor = refresh_vendor(api, state["vendor_id"])
    assert vendor["onboarding_status"] == "SUSPENDED"
    assert vendor["suspension_reason"] == "MANUAL_OPS"
    assert vendor["version"] == 5
    rules = get_success_data(
        api.list_serviceability_rules(state["vendor_id"], ADMIN, params={"limit": 100})
    )
    assert len(rules) == 1
    assert rules[0]["status"] == "INACTIVE"
    assert rules[0]["inactivated_by_suspension"] is True
    item = refresh_item(api, state["item_id"])
    assert item["status"] == "SUPPRESSED"
    assert item["suppression_reason"] == "VENDOR_SUSPENDED"
    assert item["available_units"] == 0
    assert refresh_line(api, state["line_id"])["status"] == "BACKORDERED"
    assert refresh_order(api, state["order_id"])["fulfillment_status"] == "OPEN"


def test_reinstatement_restores_cascade_suppressed_coverage_and_offer(api):
    """PRD §3.9: "On success `suspension_reason` is cleared to null, every serviceability rule of that vendor with `inactivated_by_suspension` true is returned to `status` `ACTIVE` with the flag cleared back to false — and only those rows, so a coverage row an operator retired deliberately before the suspension stays retired — and every offer of that vendor in `SUPPRESSED` with `suppression_reason` `VENDOR_SUSPENDED` returns `SUPPRESSED → ACTIVE` with `suppression_reason` cleared to null and `available_units` recomputed."

    Reinstatement undoes hops one and two: the flagged coverage row comes back,
    the offer returns to ACTIVE and its availability is recomputed against the
    60 on-hand units it was fed, less the 5-unit buffer and the 2 units the still
    open line reserves.

    Design: Corner/state_machines/corner_vendor_reinstate_restores_coverage_and_offers_but_not_backordered_lines
    """
    state = _active_offer_with_untransmitted_line(api, "REIN", "ORD-REIN-1")
    get_success_data(
        api.suspend_vendor(
            state["vendor_id"], make_merchandise_manager_headers("mm-suspender-2")
        )
    )

    response = api.reinstate_vendor(
        state["vendor_id"], make_merchandise_manager_headers("mm-reinstater-2")
    )

    validate_success(response)
    vendor = refresh_vendor(api, state["vendor_id"])
    assert vendor["onboarding_status"] == "ACTIVE"
    assert vendor["suspension_reason"] is None
    assert vendor["version"] == 6
    rules = get_success_data(
        api.list_serviceability_rules(state["vendor_id"], ADMIN, params={"limit": 100})
    )
    assert rules[0]["status"] == "ACTIVE"
    assert rules[0]["inactivated_by_suspension"] is False
    item = refresh_item(api, state["item_id"])
    assert item["status"] == "ACTIVE"
    assert item["suppression_reason"] is None
    assert item["reserved_units"] == 2
    assert item["available_units"] == 53


def test_reinstatement_leaves_backordered_lines_where_they_are(api):
    """PRD §3.9: "Lines that hop three pushed into `BACKORDERED` stay there, awaiting the explicit re-sourcing described in §3.7."

    Reinstatement is deliberately a partial compensation: the coverage row and
    the offer come back, but the line the suspension backordered is not walked
    back to PENDING_TRANSMIT.

    Design: Corner/state_machines/corner_vendor_reinstate_restores_coverage_and_offers_but_not_backordered_lines
    """
    state = _active_offer_with_untransmitted_line(api, "REIN2", "ORD-REIN-2")
    get_success_data(
        api.suspend_vendor(
            state["vendor_id"], make_merchandise_manager_headers("mm-suspender-2b")
        )
    )
    assert refresh_line(api, state["line_id"])["status"] == "BACKORDERED"

    response = api.reinstate_vendor(
        state["vendor_id"], make_merchandise_manager_headers("mm-reinstater-2b")
    )

    validate_success(response)
    assert refresh_line(api, state["line_id"])["status"] == "BACKORDERED"
    assert refresh_item(api, state["item_id"])["status"] == "ACTIVE"


def test_suspension_does_not_overwrite_a_manually_suppressed_offer(api):
    """PRD §3.9: "**Hop two**, caused by hop one stripping the vendor of live coverage, sets every offer of that vendor whose `status` is `ACTIVE` to `SUPPRESSED` with `suppression_reason` `VENDOR_SUSPENDED` and forces each such offer's `available_units` to 0."

    The offer hop is conditional on the child's own state: only ACTIVE offers are
    re-stamped, so an offer an operator had already suppressed by hand keeps its
    MANUAL reason.

    Design: Corner/state_machines/corner_suspension_cascade_skips_offers_already_manually_suppressed
    """
    state = _vendor_with_cascade_and_manual_offers(api, "MSKIP")

    response = api.suspend_vendor(
        state["vendor_id"], make_merchandise_manager_headers("mm-suspender-3")
    )

    validate_success(response)
    cascaded = refresh_item(api, state["item_id"])
    assert cascaded["status"] == "SUPPRESSED"
    assert cascaded["suppression_reason"] == "VENDOR_SUSPENDED"
    assert cascaded["available_units"] == 0
    manual = refresh_item(api, state["manual_item_id"])
    assert manual["status"] == "SUPPRESSED"
    assert manual["suppression_reason"] == "MANUAL"


def test_reinstatement_does_not_restore_a_manually_suppressed_offer(api):
    """PRD §3.9: "Offers suppressed for `MANUAL` or `ZERO_AVAILABILITY` reasons are untouched by reinstatement and follow their own restore paths from §3.3 and §3.4."

    Only the offers the suspension itself took down come back: the hand-suppressed
    offer stays SUPPRESSED with reason MANUAL and no availability, while the
    cascade-suppressed one returns to ACTIVE with its availability recomputed.

    Design: Corner/state_machines/corner_suspension_cascade_skips_offers_already_manually_suppressed
    """
    state = _vendor_with_cascade_and_manual_offers(api, "MSKIP2")
    get_success_data(
        api.suspend_vendor(
            state["vendor_id"], make_merchandise_manager_headers("mm-suspender-3b")
        )
    )

    response = api.reinstate_vendor(
        state["vendor_id"], make_merchandise_manager_headers("mm-reinstater-3b")
    )

    validate_success(response)
    cascaded = refresh_item(api, state["item_id"])
    assert cascaded["status"] == "ACTIVE"
    assert cascaded["suppression_reason"] is None
    assert cascaded["available_units"] == 55
    manual = refresh_item(api, state["manual_item_id"])
    assert manual["status"] == "SUPPRESSED"
    assert manual["suppression_reason"] == "MANUAL"
    assert manual["available_units"] == 0


# ─── Parent state derived from its children ───────────


def test_order_reads_shipped_when_its_last_open_line_is_cancelled(api):
    """PRD §3.6: "Because cancelled lines are excluded from the all-shipped test, an order holding one shipped line and one cancelled line reads `SHIPPED` rather than `PARTIALLY_SHIPPED`."

    The fulfillment axis is re-derived from the lines rather than written: once
    the only open line is cancelled the open set empties, so the order bubbles up
    to SHIPPED and its totals drop the cancelled line.

    Design: Corner/state_machines/corner_order_bubbles_up_to_shipped_when_the_only_open_line_is_cancelled
    """
    base = setup_vendor_with_active_offer(api, suffix="BUBBLE")
    vendor_headers = make_vendor_user_headers(base["vendor_id"])
    placed = place_and_transmit_order(
        api,
        base["item_id"],
        quantity=1,
        order_ref="ORD-BUBBLE-1",
        extra_lines=[order_line_input(base["item_id"], 1)],
    )
    first, second = placed["lines"][0], placed["lines"][1]
    get_success_data(
        api.acknowledge_line(first["id"], acknowledge_payload("ACCEPTED"), vendor_headers)
    )
    set_clock(api, "2026-08-04T10:00:00Z")
    ship_confirm(api, first["id"], base["vendor_id"], 1)
    assert refresh_order(api, placed["order_id"])["fulfillment_status"] == "PARTIALLY_SHIPPED"

    response = api.cancel_line(second["id"], vendor_headers)

    validate_success(response)
    assert refresh_line(api, second["id"])["status"] == "CANCELLED_BY_VENDOR"
    order = refresh_order(api, placed["order_id"])
    assert order["fulfillment_status"] == "SHIPPED"
    assert order["total_retail_cents"] == 24999
    item = refresh_item(api, base["item_id"])
    assert item["lifetime_shipped_units"] == 1
    assert item["lifetime_released_units"] == 1


def test_feed_message_refreshes_the_offers_availability_view(api):
    """PRD §3.4: "In the same request the offer's `last_inventory_refresh_at` is stamped with the logical clock and the offer's `version` is incremented."

    Posting a child feed message moves the parent offer in the same request: the
    trusted on-hand figure, the availability after the 5-unit safety buffer, the
    staleness flag, the refresh stamp and the offer's version all change.

    Design: Corner/state_machines/corner_snapshot_create_refreshes_item_effective_on_hand_and_availability
    """
    base = setup_vendor_with_active_offer(
        api, suffix="SNAP", feed=False, now_at="2026-08-03T09:00:00Z"
    )
    before = refresh_item(api, base["item_id"])
    assert before["version"] == 2
    assert before["inventory_is_stale"] is True
    assert before["last_inventory_refresh_at"] is None

    response = api.create_inventory_snapshot(
        base["item_id"],
        create_inventory_snapshot_payload(
            expected_item_version=before["version"],
            on_hand_units=60,
            effective_from="2026-08-03T09:00:00Z",
            feed_sequence=1,
        ),
        make_vendor_user_headers(base["vendor_id"]),
    )

    snapshot = validate_success(response, 201)
    assert snapshot["status"] == "ACTIVE"
    after = refresh_item(api, base["item_id"])
    assert after["effective_on_hand_units"] == 60
    assert after["available_units"] == 55
    assert after["inventory_is_stale"] is False
    assert after["last_inventory_refresh_at"] == "2026-08-03T09:00:00.000Z"
    assert after["version"] == 3


def test_return_routes_to_retailer_dc_when_the_vendor_defect_rate_exceeds_the_ceiling(api):
    """PRD §3.8: "If no candidate is eligible, the goods come home instead: `routing_destination` becomes `RETAILER_DC`, `routed_vendor_id` stays null, and `restock_disposition` is forced to `RETAILER_RESTOCK`."

    The sourcing offer declares no fallback and its vendor's latest published
    scorecard carries a defect rate of 2000 basis points, above the fifteen
    percent ceiling, so the only candidate is ineligible and no vendor balance
    moves on authorization.

    Design: Corner/state_machines/corner_return_authorize_routes_to_retailer_dc_when_vendor_defect_rate_exceeds_the_ceiling
    """
    state = setup_shipped_line(api, quantity=1, order_ref="ORD-ROUTE-1", suffix="ROUTE")
    scorecard = publish_seeded_scorecard(
        api,
        state["vendor_id"],
        avg_ship_hours=30.0,
        on_time_bps=9800,
        cancellation_bps=200,
        defect_bps=2000,
    )
    assert scorecard["composite_score"] == 94.40
    assert scorecard["tier"] == "GOLD"
    assert refresh_vendor(api, state["vendor_id"])["onboarding_status"] == "ACTIVE"
    ra = open_return(api, state["line_id"], quantity_returned=1, reason_code="DEFECTIVE")

    response = api.authorize_return(ra["id"], TEST_USERS["care_agent_headers"])

    authorized = validate_success(response)
    assert authorized["status"] == "AUTHORIZED"
    assert authorized["routing_destination"] == "RETAILER_DC"
    assert authorized["routed_vendor_id"] is None
    assert authorized["restock_disposition"] == "RETAILER_RESTOCK"
    assert authorized["vendor_chargeback_cents"] == 0
    assert authorized["refund_cents"] == 24999
    vendor = refresh_vendor(api, state["vendor_id"])
    assert vendor["chargeback_balance_cents"] == 0
    assert vendor["settlement_balance_cents"] == 21249
