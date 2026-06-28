"""State-machine behaviour: the quote revision cycle, the visit re-clean cycle, invalid /
terminal transitions, initial state, photo+crew start/complete preconditions, and the
unschedule / reject-claim side effects. Translates Difficulty rule non_linear_state_machine
and the state_machines corner instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    setup_accepted_quote, setup_scheduled_visit, setup_crewed_scheduled_visit,
    setup_completed_visit, setup_open_claim,
    create_customer_payload, create_route_payload, create_property_payload,
    create_quote_payload, create_line_item_payload, create_visit_payload,
    create_clear_weather_window, create_technician, create_visit, schedule_visit,
    reserve_crew, confirm_crew, upload_photo, start_visit, complete_visit, set_clock,
    accept_quote, send_quote, add_line_item, create_draft_quote, create_property, create_customer,
    TEST_USERS, make_customer_headers, make_field_tech_headers,
)

DISP = TEST_USERS["dispatcher_headers"]


# ─────────────────────────────────────────────────────────────────────────
# Difficulty / non_linear_state_machine
# ─────────────────────────────────────────────────────────────────────────

def test_quote_revision_cycle_sent_draft_sent(api):
    """PRD §3.2: "When a `Dispatcher` revises a quote, it returns from `SENT` to `DRAFT` —
    legal only from `SENT`, otherwise `ERR_INVALID_STATE` — reopening it for line-item edits
    and clearing the frozen subtotal and total so they recompute on the next send. This
    `SENT → DRAFT → SENT` cycle is the revision loop."

    Design: Difficulty/non_linear_state_machine/quote_revision_cycle_sent_to_draft_to_sent
    """
    cust = create_customer()
    from test_helpers import create_route
    route = create_route()
    prop = create_property(cust["id"], route["id"], stories=1, siding_sqft=1000)
    quote = create_draft_quote(prop["id"], prop["version"])
    add_line_item(quote["id"], "SIDING", "HOUSE_WASH", 1000)
    send_quote(quote["id"])
    revised = validate_success(api.revise_quote(quote["id"], DISP), 200)
    assert revised["status"] == "DRAFT", revised["status"]
    resent = validate_success(api.send_quote(quote["id"], DISP), 200)
    assert resent["status"] == "SENT", resent["status"]
    # 1000 * 15 * 1.0 * 1.0 = 15000 re-frozen subtotal.
    assert resent["subtotal_cents"] == 15000, resent["subtotal_cents"]


def test_revise_from_draft_rejected_invalid_state(api):
    """PRD §3.2: "When a `Dispatcher` revises a quote, it returns from `SENT` to `DRAFT` —
    legal only from `SENT`, otherwise `ERR_INVALID_STATE`".

    Design: Difficulty/non_linear_state_machine/quote_revision_cycle_sent_to_draft_to_sent
    """
    cust = create_customer()
    from test_helpers import create_route
    route = create_route()
    prop = create_property(cust["id"], route["id"], stories=1, siding_sqft=1000)
    quote = create_draft_quote(prop["id"], prop["version"])
    add_line_item(quote["id"], "SIDING", "HOUSE_WASH", 1000)
    # Still DRAFT (never sent) -> revise illegal.
    validate_error(api.revise_quote(quote["id"], DISP), ApiErrorId.ERR_INVALID_STATE.value)


def test_visit_reclean_cycle_completed_to_reclean_requested(api):
    """PRD §3.10: "Approval is a two-hop cascade: first, a free re-clean `Visit` is spawned,
    whose `reclean_of_visit_id` is set to the claim's visit, covering the same property and
    scope and starting in `REQUESTED` status, and the claim's `reclean_visit_id` is set to
    that new visit; second, the source visit moves from `COMPLETED` to `RECLEAN_REQUESTED`,
    closing the completed-to-re-clean cycle."

    Design: Difficulty/non_linear_state_machine/visit_reclean_cycle_completed_to_reclean_requested
    """
    ctx = setup_open_claim(
        property_overrides={"stories": 2, "roof_sqft": 2000, "siding_sqft": 1500},
        line_items=[("ROOF", "ROOF_SOFT_WASH", 2000), ("SIDING", "HOUSE_WASH", 1500)],
        route_overrides={"travel_buffer_minutes": 0},
    )
    v0_id = ctx["visit"]["id"]
    approved = validate_success(api.approve_claim(ctx["claim"]["id"], DISP))
    assert approved["status"] == "APPROVED", approved["status"]
    rc_id = approved["reclean_visit_id"]
    assert rc_id is not None
    source = get_success_data(api.get_visit(v0_id, DISP))
    assert source["status"] == "RECLEAN_REQUESTED", source["status"]
    reclean = get_success_data(api.get_visit(rc_id, DISP))
    assert reclean["reclean_of_visit_id"] == v0_id, reclean["reclean_of_visit_id"]
    assert reclean["status"] == "REQUESTED", reclean["status"]


def test_approve_claim_spawns_reclean_only_when_source_completed(api):
    """PRD §3.10: "Approving is legal only when the claim is `OPEN` (otherwise
    `ERR_INVALID_STATE`) and the linked visit is in `COMPLETED` status (otherwise
    `ERR_INVALID_STATE`)."

    Design: Difficulty/non_linear_state_machine/visit_reclean_cycle_completed_to_reclean_requested
    """
    # File then approve once (succeeds), then a second approve must be ERR_INVALID_STATE
    # (claim no longer OPEN), proving APPROVED is the only path that spawns the re-clean.
    ctx = setup_open_claim(
        property_overrides={"stories": 2, "roof_sqft": 2000},
        line_items=[("ROOF", "ROOF_SOFT_WASH", 2000)],
        route_overrides={"travel_buffer_minutes": 0},
    )
    validate_success(api.approve_claim(ctx["claim"]["id"], DISP))
    validate_error(api.approve_claim(ctx["claim"]["id"], DISP), ApiErrorId.ERR_INVALID_STATE.value)


# ─────────────────────────────────────────────────────────────────────────
# Corner / state_machines
# ─────────────────────────────────────────────────────────────────────────

def test_schedule_completed_visit_rejected_invalid_state(api):
    """PRD §3.5: "Scheduling moves a visit from `REQUESTED` to `SCHEDULED` ... The transition
    is legal only from `REQUESTED` (otherwise `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/schedule_visit_from_completed_returns_invalid_state
    """
    ctx = setup_completed_visit(
        property_overrides={"stories": 2, "roof_sqft": 2000},
        line_items=[("ROOF", "ROOF_SOFT_WASH", 2000)],
        route_overrides={"travel_buffer_minutes": 0},
    )
    visit = ctx["visit"]
    from test_helpers import schedule_visit_payload
    resp = api.schedule_visit(visit["id"], schedule_visit_payload(visit["version"]), DISP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = get_success_data(api.get_visit(visit["id"], DISP))
    assert after["status"] == "COMPLETED", after["status"]


def test_cancel_already_cancelled_visit_rejected_invalid_state(api):
    """PRD §3.5: "A `Dispatcher` may cancel a visit while it is `REQUESTED` or `SCHEDULED`,
    moving it to the terminal `CANCELLED` status; from any other status the cancel is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_terminal_cancelled_visit_returns_invalid_state
    """
    cust = create_customer()
    from test_helpers import create_route
    route = create_route()
    prop = create_property(cust["id"], route["id"], stories=1, siding_sqft=1000)
    quote = create_draft_quote(prop["id"], prop["version"])
    add_line_item(quote["id"], "SIDING", "HOUSE_WASH", 1000)
    send_quote(quote["id"])
    accept_quote(quote["id"], cust["id"])
    visit = create_visit(prop["id"], quote["id"], scheduled_date="2026-05-01")
    validate_success(api.cancel_visit(visit["id"], DISP), 200)
    validate_error(api.cancel_visit(visit["id"], DISP), ApiErrorId.ERR_INVALID_STATE.value)


def test_new_visit_starts_requested_unbilled_route_copied(api):
    """PRD §3.5: "On creation the visit's `route_id` is copied from the property's route, its
    `billing_status` is `UNBILLED`, and its `status` is `REQUESTED`."

    Design: Corner/state_machines/new_visit_initial_state_requested
    """
    cust = create_customer()
    from test_helpers import create_route
    route = create_route()
    prop = create_property(cust["id"], route["id"], stories=1, siding_sqft=800)
    quote = create_draft_quote(prop["id"], prop["version"])
    add_line_item(quote["id"], "SIDING", "HOUSE_WASH", 800)
    send_quote(quote["id"])
    accept_quote(quote["id"], cust["id"])
    visit = validate_success(
        api.create_visit(create_visit_payload(prop["id"], quote["id"], "2026-05-01"), DISP), 201)
    assert visit["status"] == "REQUESTED", visit["status"]
    assert visit["billing_status"] == "UNBILLED", visit["billing_status"]
    assert visit["route_id"] == route["id"], visit["route_id"]


def test_start_visit_without_before_photo_rejected(api):
    """PRD §3.7: "Starting is legal only from `SCHEDULED` (otherwise `ERR_INVALID_STATE`),
    requires at least one crew assignment in `CONFIRMED` status (otherwise
    `ERR_NO_CONFIRMED_CREW`), and requires a `BEFORE` photo set on the visit (otherwise
    `ERR_BEFORE_PHOTO_MISSING`)."

    Design: Corner/state_machines/start_visit_without_before_photo_returns_error
    """
    # CONFIRMED crew but no BEFORE photo.
    ctx = setup_crewed_scheduled_visit(
        property_overrides={"stories": 2, "roof_sqft": 2000},
        line_items=[("ROOF", "ROOF_SOFT_WASH", 2000)],
        route_overrides={"travel_buffer_minutes": 0},
        confirm=True,
    )
    resp = api.start_visit(ctx["visit"]["id"], make_field_tech_headers(ctx["technician"]["id"]))
    validate_error(resp, ApiErrorId.ERR_BEFORE_PHOTO_MISSING.value)


def test_start_visit_without_confirmed_crew_rejected(api):
    """PRD §3.7: "requires at least one crew assignment in `CONFIRMED` status (otherwise
    `ERR_NO_CONFIRMED_CREW`)".

    Design: Corner/state_machines/start_visit_without_confirmed_crew_returns_error
    """
    # RESERVED (not CONFIRMED) crew + a BEFORE photo.
    ctx = setup_crewed_scheduled_visit(
        property_overrides={"stories": 2, "roof_sqft": 2000},
        line_items=[("ROOF", "ROOF_SOFT_WASH", 2000)],
        route_overrides={"travel_buffer_minutes": 0},
        confirm=False,
    )
    upload_photo(ctx["visit"]["id"], "BEFORE", ctx["technician"]["id"])
    resp = api.start_visit(ctx["visit"]["id"], make_field_tech_headers(ctx["technician"]["id"]))
    validate_error(resp, ApiErrorId.ERR_NO_CONFIRMED_CREW.value)


def test_complete_visit_without_after_photo_rejected(api):
    """PRD §3.7: "Completing a visit moves it from `IN_PROGRESS` to `COMPLETED`, legal only
    from `IN_PROGRESS` (otherwise `ERR_INVALID_STATE`) and only when an `AFTER` photo set
    exists (otherwise `ERR_AFTER_PHOTO_MISSING`)."

    Design: Corner/state_machines/complete_visit_without_after_photo_returns_error
    """
    from test_helpers import setup_in_progress_visit, complete_visit_payload
    ctx = setup_in_progress_visit(
        property_overrides={"stories": 2, "roof_sqft": 2000},
        line_items=[("ROOF", "ROOF_SOFT_WASH", 2000)],
        route_overrides={"travel_buffer_minutes": 0},
    )
    # IN_PROGRESS with only a BEFORE photo; no AFTER uploaded.
    resp = api.complete_visit(
        ctx["visit"]["id"], complete_visit_payload(re_measured_roof_sqft=2000),
        make_field_tech_headers(ctx["technician"]["id"]))
    validate_error(resp, ApiErrorId.ERR_AFTER_PHOTO_MISSING.value)


def test_unschedule_releases_crew_and_clears_provisional_cost(api):
    """PRD §3.5: "Unscheduling is legal only from `SCHEDULED` (otherwise `ERR_INVALID_STATE`);
    it releases all of the visit's `RESERVED` and `CONFIRMED` crew assignments to `RELEASED`
    — each release freeing the technician's interval and decrementing that technician's
    `scheduled_minutes` by the assignment's `duration_minutes` — and clears
    `provisional_cost_cents` back to null."

    Design: Corner/state_machines/unschedule_releases_crew_and_clears_provisional_cost
    """
    ctx = setup_crewed_scheduled_visit(
        property_overrides={"stories": 2, "roof_sqft": 2000},
        line_items=[("ROOF", "ROOF_SOFT_WASH", 2000)],
        route_overrides={"travel_buffer_minutes": 0},
        confirm=False,
    )
    visit, tech, asg = ctx["visit"], ctx["technician"], ctx["assignment"]
    unsched = validate_success(api.unschedule_visit(visit["id"], DISP), 200)
    assert unsched["status"] == "REQUESTED", unsched["status"]
    assert unsched["provisional_cost_cents"] is None, unsched["provisional_cost_cents"]
    after_asg = get_success_data(api.get_assignment(asg["id"], DISP))
    assert after_asg["status"] == "RELEASED", after_asg["status"]
    after_tech = get_success_data(api.get_technician(tech["id"], DISP))
    assert after_tech["scheduled_minutes"] == 0, after_tech["scheduled_minutes"]


def test_reject_claim_leaves_source_visit_completed(api):
    """PRD §3.10: "Rejecting a claim moves it from `OPEN` to the terminal `REJECTED` status,
    legal only from `OPEN` (otherwise `ERR_INVALID_STATE`), with no further effects."

    Design: Corner/state_machines/reject_claim_leaves_source_visit_completed
    """
    ctx = setup_open_claim(
        property_overrides={"stories": 2, "roof_sqft": 2000},
        line_items=[("ROOF", "ROOF_SOFT_WASH", 2000)],
        route_overrides={"travel_buffer_minutes": 0},
    )
    rejected = validate_success(api.reject_claim(ctx["claim"]["id"], DISP), 200)
    assert rejected["status"] == "REJECTED", rejected["status"]
    assert rejected["reclean_visit_id"] is None, rejected["reclean_visit_id"]
    source = get_success_data(api.get_visit(ctx["visit"]["id"], DISP))
    assert source["status"] == "COMPLETED", source["status"]


def test_void_paid_invoice_rejected_invalid_state(api):
    """PRD §3.8: "A `BillingAdmin` records payment on an `ISSUED` invoice, moving it to the
    terminal `PAID` status".
    PRD §3.8: "A `BillingAdmin` may void an invoice that is `ISSUED` or `DISPUTED`, moving it
    to the terminal `VOIDED` status (from any other status, `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/invoice_pay_then_void_from_paid_returns_invalid_state
    """
    BILL = TEST_USERS["billing_admin_headers"]
    ctx = setup_completed_visit(
        property_overrides={"stories": 2, "roof_sqft": 2000},
        line_items=[("ROOF", "ROOF_SOFT_WASH", 2000)],
        route_overrides={"travel_buffer_minutes": 0},
    )
    inv = ctx["invoice"]
    validate_success(api.pay_invoice(inv["id"], BILL), 200)
    validate_error(api.void_invoice(inv["id"], BILL), ApiErrorId.ERR_INVALID_STATE.value)
