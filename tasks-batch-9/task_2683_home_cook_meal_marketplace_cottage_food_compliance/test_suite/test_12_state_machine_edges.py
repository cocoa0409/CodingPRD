"""State-machine edges: initial states, undeclared transitions, terminal lockout,
clock-gated edges and the reversal edges that restore conserved counters.

Every test builds its own world from scratch: the harness restarts the API server
before each test, so nothing here may rely on another test's rows.
"""

from test_helpers import (
    ADMIN_HEADERS,
    DINER_TWO_HEADERS,
    FINANCE_ONE_HEADERS,
    OFFICER_ONE_HEADERS,
    OFFICER_TWO_HEADERS,
    REVIEWER_ONE_HEADERS,
    assert_capacity_triple,
    assert_cook_dimensions,
    assert_fields,
    assert_money_is_integer,
    assert_net_payout_identity,
    assert_order_dimensions,
    assert_refund_three_bucket_identity,
    factories,
    make_cook_headers,
    make_compliance_reviewer_headers,
    make_diner_headers,
    validate_error,
    validate_paginated,
)
from test_helpers import fixtures as fx


# ==========================================================================
# Initial states of freshly created rows
# ==========================================================================
def test_01_new_cook_starts_draft_on_onboarding_and_clear_on_standing(api):
    """A newly registered cook seeds both of its status dimensions independently.

    PRD: "A new cook starts with `onboarding_status` `DRAFT`, `compliance_standing` `CLEAR`, `safety_score` 100, a null `standing_reason`, a null `verified_kitchen_type`, `cap_status` `UNDER_CAP`, and every money counter — `ytd_gross_sales_cents`, `ytd_cottage_revenue_cents`, `pending_payout_cents`, `lifetime_paid_cents` — at zero."
    Design: Corner/state_machines/newly_created_rows_start_in_declared_initial_state
    """
    fx.reset_clock(api)
    fx.create_state_policy(api, state_code="CA")

    cook = fx.register_cook(api, state_code="CA", claimed_kitchen_type="HOME_COTTAGE")
    assert_fields(
        cook,
        onboarding_status="DRAFT",
        compliance_standing="CLEAR",
        safety_score=100,
        standing_reason=None,
        verified_kitchen_type=None,
        cap_status="UNDER_CAP",
        ytd_gross_sales_cents=0,
        ytd_cottage_revenue_cents=0,
        pending_payout_cents=0,
        lifetime_paid_cents=0,
        version=1,
    )
    assert_money_is_integer(
        cook,
        "ytd_gross_sales_cents",
        "ytd_cottage_revenue_cents",
        "pending_payout_cents",
        "lifetime_paid_cents",
    )

    # The document write advances the onboarding dimension and leaves the
    # standing dimension exactly where it started.
    document = fx.submit_food_handler_cert(api, cook)
    assert_fields(
        document,
        review_status="SUBMITTED",
        doc_type="FOOD_HANDLER_CERT",
        reviewed_by_user_id=None,
        reviewed_at=None,
        superseded_by_document_id=None,
        version=1,
    )
    after = fx.read_cook(api, cook["id"])
    assert_cook_dimensions(after, "DOCS_SUBMITTED", "CLEAR")
    assert_fields(after, safety_score=100, standing_reason=None, version=2)


def test_02_new_menu_item_starts_draft_with_a_zero_revision_round(api):
    """A drafted dish begins in DRAFT with an untouched revision counter.

    PRD: "The item is created in `review_status` `DRAFT` with `revision_round` at 0, a null `approved_by_user_id`, a null `approved_at` and a null `delist_reason`."
    Design: Corner/state_machines/newly_created_rows_start_in_declared_initial_state
    """
    fx.reset_clock(api)
    fx.create_state_policy(api, state_code="CA")
    cook = fx.register_cook(api, state_code="CA", claimed_kitchen_type="HOME_COTTAGE")

    item = fx.draft_menu_item(
        api,
        cook,
        name="Plain Scone",
        food_category="BAKED_NON_TCS",
        allergens=["WHEAT"],
        shelf_life_days=5,
        unit_price_cents=400,
    )
    assert_fields(
        item,
        review_status="DRAFT",
        revision_round=0,
        approved_by_user_id=None,
        approved_at=None,
        delist_reason=None,
        version=1,
    )


def test_03_new_pickup_hub_starts_open_with_no_assigned_orders(api):
    """A pickup hub is seeded OPEN with an empty slot count.

    PRD: "A hub is created in `status` `OPEN` with `assigned_order_count` at 0."
    Design: Corner/state_machines/newly_created_rows_start_in_declared_initial_state
    """
    fx.reset_clock(api)
    policy = fx.create_state_policy(api, state_code="CA")
    zone = fx.create_delivery_zone(
        api,
        policy["id"],
        state_code="CA",
        service_mode="HUB_PICKUP",
        max_cold_chain_minutes=240,
    )

    hub = fx.create_pickup_hub(
        api,
        zone["id"],
        name="Mission Hub",
        address="1 Valencia St",
        slot_capacity_orders=4,
        hub_window_start_at="2026-08-08T15:00:00Z",
        hub_window_end_at="2026-08-08T19:00:00Z",
    )
    assert_fields(hub, status="OPEN", assigned_order_count=0, version=1)


def test_04_new_safety_report_starts_in_intake_with_no_triage_trace(api):
    """Intake seeds a report in INTAKE, stamps the reporter and leaves every later field null.

    PRD: "A new report is created in `status` `INTAKE`, records `reported_by_user_id` from the acting `X-User-ID`, derives its `severity_points` from the graded severity, and leaves `triaged_by_user_id`, `triaged_at`, `adjudicated_by_user_id`, `adjudicated_at` and `resolution_note` null."
    Design: Corner/state_machines/newly_created_rows_start_in_declared_initial_state
    """
    fx.reset_clock(api)
    fx.create_state_policy(api, state_code="CA")
    cook = fx.register_cook(api, state_code="CA", claimed_kitchen_type="HOME_COTTAGE")

    incident = fx.report_incident(
        api,
        cook["id"],
        reporter_headers=make_diner_headers("diner-x"),
        subject_type="COOK",
        category="LABEL_MISSING",
        severity="MINOR",
        description="packaging photo lacked the disclaimer",
    )
    assert_fields(
        incident,
        status="INTAKE",
        severity="MINOR",
        severity_points=5,
        reported_by_user_id="diner-x",
        triaged_by_user_id=None,
        triaged_at=None,
        adjudicated_by_user_id=None,
        adjudicated_at=None,
        resolution_note=None,
        version=1,
    )
    # Intake never charges the authoritative score.
    assert_fields(fx.read_cook(api, cook["id"]), safety_score=100, compliance_standing="CLEAR")


# ==========================================================================
# Supersession, re-review and undeclared transitions
# ==========================================================================
def test_05_resubmitting_a_doc_type_supersedes_the_prior_row_and_points_at_the_new_one(api):
    """Re-submitting the same doc_type retires the old row and back-points it at the new row.

    PRD: "Submission is also a **superseding** write: if the cook already holds a document of that same `doc_type` in any of `SUBMITTED`, `VERIFIED`, `REJECTED`, `PASSED`, `FAILED` or `WAIVED`, that older row moves to `SUPERSEDED` and its `superseded_by_document_id` is set to the new row's `id`, forming a self-referential supersession chain that remains fully queryable."
    Design: Corner/state_machines/document_supersede_writes_back_pointer_and_reverts_cook_dimension
    """
    fx.reset_clock(api)
    fx.create_state_policy(api, state_code="CA")
    cook = fx.register_cook(api, state_code="CA", claimed_kitchen_type="HOME_COTTAGE")

    first = fx.submit_food_handler_cert(
        api, cook, certificate_number="FH-0001", issued_on="2026-01-15", expires_on="2028-01-15"
    )
    observed_version = fx.cook_version(api, cook["id"])
    second = fx.submit_food_handler_cert(
        api,
        cook,
        expected_version=observed_version,
        certificate_number="FH-0002",
        issued_on="2026-02-01",
        expires_on="2028-02-01",
    )

    retired = fx.read_document(api, first["id"])
    assert_fields(
        retired, review_status="SUPERSEDED", superseded_by_document_id=second["id"]
    )
    live = fx.read_document(api, second["id"])
    assert_fields(live, review_status="SUBMITTED", superseded_by_document_id=None)

    # The cook rides the declared self-loop rather than reverting to DRAFT, and
    # takes one version bump per document write.
    cook_now = fx.read_cook(api, cook["id"])
    assert_cook_dimensions(cook_now, "DOCS_SUBMITTED", "CLEAR")
    assert_fields(cook_now, version=3)

    # The chain is walkable backwards through the filter on the list endpoint.
    rows, meta = validate_paginated(
        api.list_onboarding_documents(
            REVIEWER_ONE_HEADERS,
            {"superseded_by_document_id": second["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 1, f"expected exactly one superseded row, got {meta}"
    assert rows[0]["id"] == first["id"], f"chain head is {rows[0]['id']}, expected {first['id']}"


def test_06_a_second_review_of_a_verified_document_is_refused(api):
    """A document already graded cannot be graded again, and the first signature survives.

    PRD: "The document under review has `review_status` equal to `SUBMITTED` — `ERR_DOC_ALREADY_REVIEWED`, 409, on document review."
    Design: Corner/state_machines/document_second_review_rejected_as_already_reviewed
    """
    fx.reset_clock(api)
    fx.create_state_policy(api, state_code="CA")
    cook = fx.register_cook(api, state_code="CA", claimed_kitchen_type="HOME_COTTAGE")
    cert = fx.submit_food_handler_cert(
        api, cook, certificate_number="FH-0001", issued_on="2026-01-15", expires_on="2028-01-15"
    )

    first = fx.review_document(api, cert["id"], "VERIFY", REVIEWER_ONE_HEADERS, note="first pass")
    assert_fields(first, review_status="VERIFIED", reviewed_by_user_id="rev-1")
    assert first["reviewed_at"] is not None, "a graded document must carry reviewed_at"

    resp = api.review_onboarding_document(
        cert["id"],
        factories.document_review_payload("VERIFY", note="second pass"),
        make_compliance_reviewer_headers("rev-3"),
    )
    validate_error(resp, "ERR_DOC_ALREADY_REVIEWED", 409)

    unchanged = fx.read_document(api, cert["id"])
    assert_fields(
        unchanged,
        review_status="VERIFIED",
        reviewed_by_user_id="rev-1",
        reviewed_at=first["reviewed_at"],
    )
    # A verified certificate alone cannot carry the cook to VERIFIED: no
    # kitchen-inspection document exists.
    assert_cook_dimensions(fx.read_cook(api, cook["id"]), "DOCS_SUBMITTED", "CLEAR")


def test_07_undeclared_transitions_are_refused_with_the_entity_specific_conflict_code(api):
    """Four "the verb exists but not from here" requests each return their own 409 code.

    PRD: "Requesting a transition that the relevant dimension does not declare from its current state — including any request against a terminal state — is rejected with the entity-specific conflict code: `ERR_INVALID_COOK_TRANSITION`, `ERR_INVALID_DOCUMENT_TRANSITION`, `ERR_INVALID_MENU_ITEM_TRANSITION`, `ERR_INVALID_WINDOW_TRANSITION`, `ERR_INVALID_ORDER_TRANSITION`, `ERR_INVALID_INCIDENT_TRANSITION` or `ERR_INVALID_STATEMENT_TRANSITION`, all HTTP 409."
    Design: Corner/state_machines/undeclared_transitions_rejected_across_document_cook_incident_and_menu_item
    """
    fx.reset_clock(api)
    fx.create_state_policy(api, state_code="CA")
    cook = fx.register_cook(api, state_code="CA", claimed_kitchen_type="HOME_COTTAGE")
    inspection = fx.submit_kitchen_inspection(
        api, cook, kitchen_type_claimed="HOME_COTTAGE", inspection_date="2026-06-01"
    )
    item = fx.draft_menu_item(api, cook, name="Plain Scone", allergens=["WHEAT"])
    incident = fx.report_incident(api, cook["id"], severity="MINOR", category="LABEL_MISSING")

    # VERIFY belongs to a certificate, never to a kitchen inspection.
    resp = api.review_onboarding_document(
        inspection["id"], factories.document_review_payload("VERIFY"), REVIEWER_ONE_HEADERS
    )
    validate_error(resp, "ERR_INVALID_DOCUMENT_TRANSITION", 409)
    assert_fields(fx.read_document(api, inspection["id"]), review_status="SUBMITTED")

    # REINSTATE is declared only from SUSPENDED.
    resp = api.cook_standing_action(
        cook["id"],
        factories.standing_action_payload("REINSTATE", "no suspension to lift"),
        OFFICER_ONE_HEADERS,
    )
    validate_error(resp, "ERR_INVALID_COOK_TRANSITION", 409)
    assert_cook_dimensions(fx.read_cook(api, cook["id"]), "DOCS_SUBMITTED", "CLEAR")

    # Triage is declared only from INTAKE.
    triaged = fx.triage_incident(api, incident["id"], "ACCEPT")
    assert_fields(triaged, status="TRIAGED", triaged_by_user_id="so-1")
    resp = api.triage_safety_incident(
        incident["id"], factories.triage_payload("DISMISS"), OFFICER_ONE_HEADERS
    )
    validate_error(resp, "ERR_INVALID_INCIDENT_TRANSITION", 409)
    assert_fields(
        fx.read_incident(api, incident["id"]), status="TRIAGED", triaged_by_user_id="so-1"
    )

    # APPROVE is declared only from UNDER_REVIEW, so a never-submitted draft
    # cannot be approved.
    resp = api.review_menu_item(
        item["id"], factories.approve_menu_item_payload(), REVIEWER_ONE_HEADERS
    )
    validate_error(resp, "ERR_INVALID_MENU_ITEM_TRANSITION", 409)
    assert_fields(
        fx.read_menu_item(api, item["id"]), review_status="DRAFT", approved_by_user_id=None
    )


# ==========================================================================
# Terminal-state lockout and the "not active yet" gate
# ==========================================================================
def test_08_a_rejected_cook_accepts_no_further_onboarding_decision(api):
    """REJECTED is terminal on the onboarding dimension: neither verb works again.

    PRD: "Nothing acts on a `REJECTED` cook thereafter."
    Design: Corner/state_machines/rejected_cook_is_locked_out_of_the_onboarding_dimension
    """
    fx.reset_clock(api)
    fx.create_state_policy(api, state_code="CA")
    cook = fx.register_cook(api, state_code="CA", claimed_kitchen_type="HOME_INSPECTED")
    fx.submit_food_handler_cert(api, cook)

    rejected = fx.decide_onboarding(
        api, cook["id"], "REJECT", REVIEWER_ONE_HEADERS, note="paperwork abandoned"
    )
    assert_cook_dimensions(rejected, "REJECTED", "CLEAR")
    assert_fields(rejected, standing_reason="paperwork abandoned", version=3)

    resp = api.cook_onboarding_decision(
        cook["id"], factories.onboarding_decision_payload("ACTIVATE"), REVIEWER_ONE_HEADERS
    )
    validate_error(resp, "ERR_INVALID_COOK_TRANSITION", 409)

    resp = api.cook_onboarding_decision(
        cook["id"],
        factories.onboarding_decision_payload("REJECT", note="rejecting twice"),
        REVIEWER_ONE_HEADERS,
    )
    validate_error(resp, "ERR_INVALID_COOK_TRANSITION", 409)

    # Two refusals leave the row byte-for-byte where the rejection left it.
    after = fx.read_cook(api, cook["id"])
    assert_cook_dimensions(after, "REJECTED", "CLEAR")
    assert_fields(after, standing_reason="paperwork abandoned", version=3)

    rows, meta = validate_paginated(
        api.list_onboarding_documents(
            REVIEWER_ONE_HEADERS, {"cook_id": cook["id"], "limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 1, f"expected the one submitted document, got {meta}"
    assert_fields(rows[0], review_status="SUBMITTED")


def test_09_a_rejected_cook_can_still_be_suspended_on_the_standing_dimension(api):
    """The terminal onboarding state does not freeze the independent standing dimension.

    PRD: "Neither dimension's transition table writes the other's field; they read each other only as preconditions."
    Design: Corner/state_machines/rejected_cook_is_locked_out_of_the_onboarding_dimension
    """
    fx.reset_clock(api)
    fx.create_state_policy(api, state_code="CA")
    cook = fx.register_cook(api, state_code="CA", claimed_kitchen_type="HOME_INSPECTED")
    fx.submit_food_handler_cert(api, cook)
    fx.decide_onboarding(api, cook["id"], "REJECT", REVIEWER_ONE_HEADERS, note="paperwork abandoned")

    suspended = fx.suspend_cook(api, cook["id"], reason="ONGOING_INVESTIGATION")
    assert_cook_dimensions(suspended, "REJECTED", "SUSPENDED")
    assert_fields(
        suspended, standing_reason="ONGOING_INVESTIGATION", safety_score=100, version=4
    )
    assert_money_is_integer(suspended, "ytd_cottage_revenue_cents", "pending_payout_cents")


def test_10_a_cook_who_never_activated_can_neither_list_a_dish_nor_open_a_window(api):
    """Menu-item submission and window creation both refuse a non-ACTIVE cook.

    PRD: "The referenced cook has `onboarding_status` equal to `ACTIVE` — `ERR_COOK_NOT_ACTIVE`, 409, on menu-item submission, production-window creation and order placement."
    Design: Corner/state_machines/inactive_cook_blocked_from_submitting_items_and_opening_windows
    """
    fx.reset_clock(api)
    fx.create_state_policy(api, state_code="CA")
    cook = fx.register_cook(api, state_code="CA", claimed_kitchen_type="HOME_INSPECTED")
    cook_headers = make_cook_headers(cook["id"])

    # Drafting a dish is allowed while still in DRAFT; submitting it is not.
    item = fx.draft_menu_item(api, cook, name="Sourdough Loaf", allergens=["WHEAT"])
    assert_fields(item, review_status="DRAFT")

    resp = api.submit_menu_item(item["id"], cook_headers)
    validate_error(resp, "ERR_COOK_NOT_ACTIVE", 409)
    assert_fields(fx.read_menu_item(api, item["id"]), review_status="DRAFT", revision_round=0)

    resp = api.create_production_window(
        factories.production_window_payload(cook["id"]), cook_headers
    )
    validate_error(resp, "ERR_COOK_NOT_ACTIVE", 409)

    rows, meta = validate_paginated(
        api.list_production_windows(ADMIN_HEADERS, {"cook_id": cook["id"], "limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 0, f"a blocked creation must persist nothing: {meta}"
    assert rows == [], f"expected no windows for this cook, got {rows}"
    assert_cook_dimensions(fx.read_cook(api, cook["id"]), "DRAFT", "CLEAR")


def test_11_adjudication_refuses_an_untriaged_and_a_dismissed_report(api):
    """Only a TRIAGED report may be adjudicated, and the refusal has its own code.

    PRD: "The report must be in `status` `TRIAGED`; adjudicating one still in `INTAKE`, already `DISMISSED`, or already adjudicated is `ERR_INCIDENT_NOT_TRIAGED`."
    Design: Corner/state_machines/incident_adjudication_before_triage_rejected
    """
    fx.reset_clock(api)
    setup = fx.onboard_active_cook(api)

    untriaged = fx.report_incident(
        api, setup.cook_id, severity="SEVERE", category="TEMP_ABUSE"
    )
    assert_fields(untriaged, status="INTAKE", adjudicated_by_user_id=None)
    resp = api.adjudicate_safety_incident(
        untriaged["id"], factories.adjudicate_payload("SUBSTANTIATE"), OFFICER_TWO_HEADERS
    )
    validate_error(resp, "ERR_INCIDENT_NOT_TRIAGED", 409)

    dismissed = fx.report_incident(
        api, setup.cook_id, severity="MINOR", category="LABEL_MISSING"
    )
    dismissed = fx.triage_incident(api, dismissed["id"], "DISMISS")
    assert_fields(dismissed, status="DISMISSED")
    resp = api.adjudicate_safety_incident(
        dismissed["id"], factories.adjudicate_payload("SUBSTANTIATE"), OFFICER_TWO_HEADERS
    )
    validate_error(resp, "ERR_INCIDENT_NOT_TRIAGED", 409)

    # Neither refusal stamped an adjudication or charged the cook's record.
    assert_fields(
        fx.read_incident(api, untriaged["id"]),
        status="INTAKE",
        adjudicated_by_user_id=None,
        adjudicated_at=None,
    )
    assert_fields(
        fx.read_incident(api, dismissed["id"]),
        status="DISMISSED",
        adjudicated_by_user_id=None,
        adjudicated_at=None,
    )
    cook = fx.read_cook(api, setup.cook_id)
    assert_fields(cook, safety_score=100)
    assert_cook_dimensions(cook, "ACTIVE", "CLEAR")


# ==========================================================================
# Clock-gated edges on the window and the order
# ==========================================================================
def test_12_the_cutoff_edge_waits_for_the_clock_and_leaves_routed_orders_alone(api):
    """A window cannot pass its cutoff early, and passing it touches no order.

    PRD: "`OPEN → CUTOFF_PASSED` simply stops the window accepting new orders and touches no order; it requires that the logical clock have reached `order_cutoff_at`, and an attempt before that instant is `ERR_CUTOFF_NOT_REACHED`."
    Design: Corner/state_machines/window_and_order_advance_walk_the_happy_path_with_clock_gated_rejections
    """
    fx.reset_clock(api)
    setup = fx.selling_cook(api)
    cook_headers = make_cook_headers(setup.cook_id)

    order = fx.order_in_scenario(api, setup, quantity=2)
    assert_order_dimensions(order, "PLACED", "AUTHORIZED")
    assert_fields(
        order,
        subtotal_cents=2400,
        diner_service_fee_cents=216,
        cold_chain_surcharge_cents=0,
        total_charge_cents=2616,
        platform_commission_cents=540,
        cook_earnings_cents=1860,
        routing_mode=None,
        pickup_hub_id=None,
    )
    window = fx.read_window(api, setup.window["id"])
    assert_capacity_triple(window, 2, 10)

    # The clock still sits at the startup instant, well before the cutoff.
    resp = api.advance_production_window(
        window["id"], factories.window_advance_payload("CUTOFF_PASSED"), cook_headers
    )
    validate_error(resp, "ERR_CUTOFF_NOT_REACHED", 409)
    assert_fields(fx.read_window(api, window["id"]), status="OPEN")

    # Routing is legal while the window is still OPEN.
    routed = fx.route_order(api, order["id"])
    assert_order_dimensions(routed, "ROUTED", "AUTHORIZED")
    assert_fields(
        routed,
        routing_mode="BATCH_COOK_AND_CHILL",
        pickup_hub_id=None,
        cold_chain_surcharge_cents=0,
        total_charge_cents=2616,
    )

    fx.set_clock(api, window["order_cutoff_at"])
    passed = fx.advance_window(api, window, "CUTOFF_PASSED")
    assert_fields(passed, status="CUTOFF_PASSED")

    # The routed order and the meal counter are untouched by the cutoff edge.
    assert_order_dimensions(fx.read_order(api, order["id"]), "ROUTED", "AUTHORIZED")
    assert_capacity_triple(fx.read_window(api, window["id"]), 2, 10)


def test_13_handoff_cannot_start_early_and_delivery_captures_the_payment(api):
    """HANDED_OFF waits for handoff_start_at and moves no money; DELIVERED captures.

    PRD: "`IN_PRODUCTION → HANDED_OFF` is a cook action requiring that the logical clock have reached the window's `handoff_start_at`, an earlier attempt being `ERR_HANDOFF_NOT_STARTED`; again no money field moves, because capture happens either at delivery confirmation or at window close."
    Design: Corner/state_machines/window_and_order_advance_walk_the_happy_path_with_clock_gated_rejections
    """
    fx.reset_clock(api)
    setup = fx.selling_cook(api)
    order = fx.routed_order(api, setup, quantity=2)
    window = fx.open_window_into_production(api, setup)
    assert_fields(window, status="IN_PRODUCTION")

    order = fx.advance_order(api, order, "IN_PRODUCTION")
    assert_order_dimensions(order, "IN_PRODUCTION", "AUTHORIZED")

    # The clock stands at the cutoff instant, which is before the handoff opens.
    resp = api.advance_order(
        order["id"],
        factories.order_advance_payload("HANDED_OFF"),
        make_cook_headers(setup.cook_id),
    )
    validate_error(resp, "ERR_HANDOFF_NOT_STARTED", 409)
    assert_order_dimensions(fx.read_order(api, order["id"]), "IN_PRODUCTION", "AUTHORIZED")

    fx.set_clock(api, window["handoff_start_at"])
    handed = fx.advance_order(api, order, "HANDED_OFF")
    assert_order_dimensions(handed, "HANDED_OFF", "AUTHORIZED")
    assert_fields(handed, captured_at=None, effective_year=None)
    waiting = fx.read_cook(api, setup.cook_id)
    assert_fields(
        waiting,
        ytd_gross_sales_cents=0,
        ytd_cottage_revenue_cents=0,
        pending_payout_cents=0,
    )

    delivered = fx.deliver_order(api, handed)
    assert_order_dimensions(delivered, "DELIVERED", "CAPTURED")
    assert_fields(delivered, effective_year=2026)
    assert delivered["captured_at"] is not None, "capture must stamp captured_at"
    paid = fx.read_cook(api, setup.cook_id)
    assert_fields(
        paid,
        ytd_gross_sales_cents=2400,
        ytd_cottage_revenue_cents=2400,
        pending_payout_cents=1860,
    )
    assert_money_is_integer(paid, "ytd_gross_sales_cents", "pending_payout_cents")


def test_14_a_window_cannot_close_before_the_handoff_interval_ends(api):
    """Closing early is refused; closing on time captures the handed-off order.

    PRD: "The logical clock is at or after the window's `handoff_end_at` before the window may reach `CLOSED` — `ERR_HANDOFF_NOT_FINISHED`, 409, on production-window advancement."
    Design: Corner/state_machines/window_and_order_advance_walk_the_happy_path_with_clock_gated_rejections
    """
    fx.reset_clock(api)
    setup = fx.handed_off_order_scenario(api, quantity=2)
    window = fx.read_window(api, setup.window["id"])
    assert_fields(window, status="IN_PRODUCTION", closed_at=None)
    version_before = window["version"]

    # The clock sits at handoff_start_at, two hours before the interval ends.
    resp = api.advance_production_window(
        window["id"], factories.window_advance_payload("CLOSED"), FINANCE_ONE_HEADERS
    )
    validate_error(resp, "ERR_HANDOFF_NOT_FINISHED", 409)
    still_open = fx.read_window(api, window["id"])
    assert_fields(
        still_open, status="IN_PRODUCTION", closed_at=None, version=version_before
    )
    assert_order_dimensions(fx.read_order(api, setup.order["id"]), "HANDED_OFF", "AUTHORIZED")

    fx.set_clock(api, window["handoff_end_at"])
    closed = fx.advance_window(api, window, "CLOSED")
    assert_fields(closed, status="CLOSED")
    assert closed["closed_at"] is not None, "the close cascade must stamp closed_at"
    assert closed["version"] > version_before, (
        f"closing must bump the window version: {version_before} -> {closed['version']}"
    )

    captured = fx.read_order(api, setup.order["id"])
    assert_order_dimensions(captured, "HANDED_OFF", "CAPTURED")
    assert_fields(captured, effective_year=2026)
    assert captured["captured_at"] is not None, "the close cascade must stamp captured_at"
    cook = fx.read_cook(api, setup.cook_id)
    assert_fields(
        cook,
        ytd_gross_sales_cents=2400,
        ytd_cottage_revenue_cents=2400,
        pending_payout_cents=1860,
    )


# ==========================================================================
# Clock-driven decay and the reversal edges that restore the counters
# ==========================================================================
def test_15_moving_the_clock_decays_the_charge_and_returns_a_warned_cook_to_clear(api):
    """A warned cook recovers by decay alone once the incidents cross eight weeks.

    PRD: "When the logical clock is moved forward, every cook's score is re-evaluated at the new instant, and a cook in `WARNED` whose recomputed score has climbed back to 80 or more moves `WARNED → CLEAR`, writing the new `safety_score`, setting `standing_reason` to null, and incrementing `version`."
    Design: Corner/state_machines/clock_advance_decays_severity_and_returns_a_warned_cook_to_clear
    """
    fx.reset_clock(api)
    setup = fx.onboard_active_cook(api)

    moderate = fx.substantiated_incident(
        api, setup.cook_id, severity="MODERATE", category="LABEL_MISSING"
    )
    assert_fields(moderate, status="SUBSTANTIATED", severity_points=12)
    after_first = fx.read_cook(api, setup.cook_id)
    assert_fields(after_first, safety_score=88, standing_reason=None)
    assert_cook_dimensions(after_first, "ACTIVE", "CLEAR")

    severe = fx.substantiated_incident(
        api, setup.cook_id, severity="SEVERE", category="FOODBORNE_ILLNESS"
    )
    assert_fields(severe, status="SUBSTANTIATED", severity_points=25)
    warned = fx.read_cook(api, setup.cook_id)
    assert_fields(warned, safety_score=63, standing_reason="SAFETY_SCORE_WARN")
    assert_cook_dimensions(warned, "ACTIVE", "WARNED")

    # 55 days after the reports: both are still 7 whole weeks old, so both keep
    # their full weight and the charge of 37 points is unchanged.
    fx.set_clock(api, "2026-09-25T00:00:00Z")
    held = fx.read_cook(api, setup.cook_id)
    assert_fields(held, safety_score=63, standing_reason="SAFETY_SCORE_WARN")
    assert_cook_dimensions(held, "ACTIVE", "WARNED")

    # 56 days: both are 8 whole weeks old, so both drop to half weight. The
    # charge is 6 + 12.5 = 18.5, rounded half up once to 19, leaving 81.
    fx.set_clock(api, "2026-09-26T00:00:00Z")
    recovered = fx.read_cook(api, setup.cook_id)
    assert_fields(recovered, safety_score=81, standing_reason=None)
    assert_cook_dimensions(recovered, "ACTIVE", "CLEAR")
    assert recovered["version"] > warned["version"], (
        f"the recovery edge must bump version: {warned['version']} -> {recovered['version']}"
    )

    summary = fx.read_compliance_summary(api, setup.cook_id)
    assert_fields(
        summary,
        safety_score=81,
        provisional_safety_score=81,
        compliance_standing="CLEAR",
        open_incident_count=0,
        substantiated_incident_count=2,
    )


def test_16_entering_production_sweeps_unrouted_orders_and_gives_back_their_meals(api):
    """The conditional cascade cancels PLACED orders only and restores committed_meals.

    PRD: "`CUTOFF_PASSED → IN_PRODUCTION` requires that the cook's `compliance_standing` be neither `SUSPENDED` nor `REVOKED`, and carries a conditional cascade: every order on the window still sitting in `PLACED` — that is, never routed — moves to `CANCELLED` with `cancelled_reason` `WINDOW_CANCELLED`, its `payment_status` moves `AUTHORIZED → VOIDED`, and `committed_meals` is decremented by that order's `quantity`."
    Design: Corner/state_machines/order_cancellations_release_hub_slots_and_restore_the_capacity_counter
    """
    fx.reset_clock(api)
    setup = fx.selling_cook(api, window_overrides={"capacity_meals": 20})

    kept = fx.routed_order(api, setup, quantity=3)
    swept = fx.order_in_scenario(api, setup, quantity=2, diner_headers=DINER_TWO_HEADERS)
    assert_order_dimensions(kept, "ROUTED", "AUTHORIZED")
    assert_order_dimensions(swept, "PLACED", "AUTHORIZED")

    window = fx.read_window(api, setup.window["id"])
    assert_capacity_triple(window, 5, 20)

    fx.set_clock(api, window["order_cutoff_at"])
    window = fx.advance_window(api, window, "CUTOFF_PASSED")
    window = fx.advance_window(api, window, "IN_PRODUCTION")
    assert_fields(window, status="IN_PRODUCTION")

    # Only the never-routed order's meals come back.
    assert_capacity_triple(fx.read_window(api, window["id"]), 3, 20)

    cancelled = fx.read_order(api, swept["id"])
    assert_order_dimensions(cancelled, "CANCELLED", "VOIDED")
    assert_fields(cancelled, cancelled_reason="WINDOW_CANCELLED")

    untouched = fx.read_order(api, kept["id"])
    assert_order_dimensions(untouched, "ROUTED", "AUTHORIZED")
    assert_fields(untouched, cancelled_reason=None)

    # Nothing captured, so no money counter moved.
    assert_fields(
        fx.read_cook(api, setup.cook_id),
        ytd_gross_sales_cents=0,
        ytd_cottage_revenue_cents=0,
        pending_payout_cents=0,
    )


def test_17_cancelling_a_routed_order_frees_its_hub_slot_and_reopens_the_hub(api):
    """A diner cancellation releases the slot, reopens the hub and restores the meals.

    PRD: "When the order was `ROUTED` and holds a non-null `pickup_hub_id`, the hub's `assigned_order_count` is decremented by one and the hub's `CLOSED → OPEN` edge is re-evaluated."
    Design: Corner/state_machines/order_cancellations_release_hub_slots_and_restore_the_capacity_counter
    """
    fx.reset_clock(api)
    setup = fx.selling_cook(api, zone_overrides={"service_mode": "HUB_PICKUP"})
    hub = fx.create_pickup_hub(api, setup.zone["id"], slot_capacity_orders=1)
    assert_fields(hub, status="OPEN", assigned_order_count=0)

    order = fx.routed_order(api, setup, quantity=3)
    assert_order_dimensions(order, "ROUTED", "AUTHORIZED")
    assert_fields(order, pickup_hub_id=hub["id"])

    # The single slot is now taken, so the hub closes itself.
    filled = fx.read_hub(api, hub["id"])
    assert_fields(filled, assigned_order_count=1, status="CLOSED")
    assert_capacity_triple(fx.read_window(api, setup.window["id"]), 3, 10)

    cancelled = fx.cancel_order(api, order, reason="changed my mind")
    assert_order_dimensions(cancelled, "CANCELLED", "VOIDED")
    assert_fields(cancelled, cancelled_reason="DINER_REQUEST")

    freed = fx.read_hub(api, hub["id"])
    assert_fields(freed, assigned_order_count=0, status="OPEN")

    # The conserved meal counter is back at its exact pre-placement value.
    assert_capacity_triple(fx.read_window(api, setup.window["id"]), 0, 10)
    assert_fields(
        fx.read_cook(api, setup.cook_id),
        ytd_cottage_revenue_cents=0,
        pending_payout_cents=0,
    )


def test_18_finalising_a_statement_settles_every_pending_refund_of_its_window(api):
    """Finalisation stamps the statement, settles the window's pending refunds and clears the balance.

    PRD: "Finalisation stamps `finalized_at` from the logical clock, moves every refund event still in `PENDING` whose order belongs to that window `PENDING → SETTLED` with `settled_at` stamped, and recomputes the cook's `pending_payout_cents`."
    Design: Corner/state_machines/statement_finalization_settles_every_pending_refund_of_its_window
    """
    fx.reset_clock(api)
    setup = fx.closed_window_scenario(api, quantity=2)
    order = fx.read_order(api, setup.order["id"])
    assert_order_dimensions(order, "HANDED_OFF", "CAPTURED")
    assert_fields(
        order, subtotal_cents=2400, platform_commission_cents=540, cook_earnings_cents=1860
    )

    refund = fx.record_refund(
        api, order["id"], reason="QUALITY", fault_party="COOK", refund_amount_cents=100
    )
    assert_fields(
        refund,
        status="PENDING",
        cook_chargeback_cents=100,
        commission_reversed_cents=0,
        platform_absorbed_cents=0,
        settled_at=None,
    )
    assert_refund_three_bucket_identity(refund)

    refunded = fx.read_order(api, order["id"])
    assert_order_dimensions(refunded, "HANDED_OFF", "PARTIALLY_REFUNDED")
    assert_fields(refunded, refunded_cents=100, cook_chargeback_cents=100)
    assert_fields(
        fx.read_cook(api, setup.cook_id),
        ytd_gross_sales_cents=2400,
        ytd_cottage_revenue_cents=2300,
        pending_payout_cents=1760,
    )

    statement = fx.draft_payout_statement(
        api, setup.cook_id, setup.window["id"], basis="ACCRUAL_WINDOW"
    )
    assert_fields(
        statement,
        status="DRAFT",
        basis="ACCRUAL_WINDOW",
        included_order_count=1,
        gross_sales_cents=2400,
        commission_cents=540,
        refund_chargeback_cents=100,
        safety_hold_cents=0,
        net_payout_cents=1760,
        finalized_at=None,
        paid_at=None,
    )
    assert_net_payout_identity(statement)

    finalized = fx.advance_statement(api, statement["id"], "FINALIZED", note="week closed out")
    assert_fields(finalized, status="FINALIZED", net_payout_cents=1760)
    assert finalized["finalized_at"] is not None, "finalisation must stamp finalized_at"

    settled = fx.read_refund(api, refund["id"])
    assert_fields(settled, status="SETTLED")
    assert settled["settled_at"] is not None, "settlement must stamp settled_at"

    # The covered order now sits behind a FINALIZED statement, so nothing is pending,
    # and nothing has been paid out yet.
    assert_fields(
        fx.read_cook(api, setup.cook_id), pending_payout_cents=0, lifetime_paid_cents=0
    )
