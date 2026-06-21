"""State machine behavior: parallel visit dimensions, the cyclic agreement,
cross-entity transition preconditions, invalid/terminal transitions, initial
states, photo-gated transitions, and lazy quote expiry.
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    create_account, create_property, create_quote, create_sent_quote,
    setup_active_agreement, setup_dispatched_visit, setup_in_progress_visit,
    setup_completed_visit, setup_scheduled_visit, create_crew, create_route,
    commit_visit, upload_photo, activate_agreement,
    setup_pending_agreement, post_deposit,
    set_clock_payload,
    TEST_USERS, make_customer_headers,
)

BILLING = TEST_USERS["billing_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
FIELD_CREW = TEST_USERS["field_crew_headers"]


def _list(res):
    body = res.json()
    return body["data"], body["meta"]


# ===========================================================================
# Queue A — non_linear_state_machine
# ===========================================================================
def test_visit_schedule_status_stays_completed_while_billing_evolves(api):
    """PRD §3.7: "Once a visit's schedule status is `COMPLETED`, the billing office
    may invoice it, moving the visit's `billing_status` from `UNBILLED` to
    `INVOICED`".

    Design: Difficulty/non_linear_state_machine/visit_parallel_schedule_and_billing_dimensions_independent
    """
    account, prop, agreement, visit, crew, route = setup_completed_visit(
        region_code="NORTH", schedule_kind="ONE_TIME",
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]},
        after_photo_count=1)
    assert visit["schedule_status"] == "COMPLETED"
    assert visit["billing_status"] == "UNBILLED"

    invoice = validate_success(api.create_invoice({"visit_id": visit["id"]}, BILLING), 201)
    assert invoice["amount_cents"] == 23000
    after = validate_success(api.get_visit(visit["id"], BILLING), 200)
    assert after["schedule_status"] == "COMPLETED"
    assert after["billing_status"] == "INVOICED"


def test_visit_billing_advances_to_paid_independently_of_schedule(api):
    """PRD §3.7: "An `INVOICED` invoice is paid by the billing office, moving the
    invoice to `PAID` and the visit's `billing_status` to `PAID`."

    Design: Difficulty/non_linear_state_machine/visit_parallel_schedule_and_billing_dimensions_independent
    """
    account, prop, agreement, visit, crew, route = setup_completed_visit(
        region_code="NORTH", schedule_kind="ONE_TIME",
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]},
        after_photo_count=1)
    invoice = validate_success(api.create_invoice({"visit_id": visit["id"]}, BILLING), 201)
    validate_success(api.pay_invoice(invoice["id"], BILLING), 200)
    after = validate_success(api.get_visit(visit["id"], BILLING), 200)
    assert after["schedule_status"] == "COMPLETED"
    assert after["billing_status"] == "PAID"


def test_agreement_cycles_active_paused_active(api):
    """PRD §3.2: "A `PAUSED` agreement may be resumed back to `ACTIVE`, completing
    the cyclic `ACTIVE` ↔ `PAUSED` relationship."

    Design: Difficulty/non_linear_state_machine/agreement_active_paused_cycle_round_trip
    """
    account, prop, agreement, visit = setup_active_agreement(
        schedule_kind="RECURRING", region_code="NORTH",
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]})
    cust = make_customer_headers(account["id"])
    paused = validate_success(api.pause_agreement(agreement["id"], cust), 200)
    assert paused["status"] == "PAUSED"
    resumed = validate_success(api.resume_agreement(agreement["id"], cust), 200)
    assert resumed["status"] == "ACTIVE"


def test_agreement_pause_from_active_then_resume_returns_to_active(api):
    """PRD §3.2: "The customer may pause an `ACTIVE` agreement, moving it to
    `PAUSED`".

    Design: Difficulty/non_linear_state_machine/agreement_active_paused_cycle_round_trip
    """
    account, prop, agreement, visit = setup_active_agreement(
        schedule_kind="RECURRING", region_code="NORTH",
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]})
    cust = make_customer_headers(account["id"])
    assert agreement["status"] == "ACTIVE"
    paused = validate_success(api.pause_agreement(agreement["id"], cust), 200)
    assert paused["status"] == "PAUSED"
    resumed = validate_success(api.resume_agreement(agreement["id"], cust), 200)
    assert resumed["status"] == "ACTIVE"


# ===========================================================================
# Queue A — cross_entity_state_dependency
# ===========================================================================
def test_commit_visit_blocked_when_agreement_paused(api):
    """PRD §3.4: "The visit's agreement must be `ACTIVE`, or the commit is rejected
    with `ERR_AGREEMENT_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/visit_commit_requires_agreement_active
    """
    account, prop, agreement, visit = setup_active_agreement(
        schedule_kind="RECURRING", region_code="NORTH",
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]})
    cust = make_customer_headers(account["id"])
    validate_success(api.pause_agreement(agreement["id"], cust), 200)

    crew = create_crew(region_code="NORTH", skill_codes=[], daily_capacity_minutes=600)
    route = create_route(crew["id"], region_code="NORTH", service_date="2026-07-01")
    res = api.commit_visit(route["id"],
                           {"visit_id": visit["id"], "expected_route_version": route["version"]},
                           DISPATCHER)
    validate_error(res, "ERR_AGREEMENT_NOT_ACTIVE", expected_status=409)


def test_commit_visit_succeeds_after_agreement_resumed(api):
    """PRD §3.4: "The visit's agreement must be `ACTIVE`, or the commit is rejected
    with `ERR_AGREEMENT_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/visit_commit_requires_agreement_active
    """
    account, prop, agreement, visit = setup_active_agreement(
        schedule_kind="RECURRING", region_code="NORTH",
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]})
    cust = make_customer_headers(account["id"])
    validate_success(api.pause_agreement(agreement["id"], cust), 200)
    validate_success(api.resume_agreement(agreement["id"], cust), 200)

    crew = create_crew(region_code="NORTH", skill_codes=[], daily_capacity_minutes=600)
    route = create_route(crew["id"], region_code="NORTH", service_date="2026-07-01")
    committed = validate_success(api.commit_visit(
        route["id"], {"visit_id": visit["id"], "expected_route_version": route["version"]},
        DISPATCHER), 201)
    assert committed["schedule_status"] == "SCHEDULED"


def test_dispatch_blocked_when_crew_offline(api):
    """PRD §3.4: "A dispatcher dispatches a `PLANNING` route, moving it to
    `DISPATCHED`, provided its crew is `AVAILABLE` (otherwise `ERR_CREW_OFFLINE`)".

    Design: Difficulty/cross_entity_state_dependency/route_dispatch_requires_crew_available
    """
    account, prop, agreement, visit, crew, route = setup_scheduled_visit(
        region_code="NORTH", schedule_kind="ONE_TIME",
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]})
    validate_success(api.set_crew_status(crew["id"], {"status": "OFFLINE"}, DISPATCHER), 200)
    res = api.dispatch_route(route["id"], DISPATCHER)
    validate_error(res, "ERR_CREW_OFFLINE", expected_status=409)


def test_dispatch_succeeds_after_crew_back_available(api):
    """PRD §3.4: "A dispatcher dispatches a `PLANNING` route, moving it to
    `DISPATCHED`, provided its crew is `AVAILABLE` (otherwise `ERR_CREW_OFFLINE`)".

    Design: Difficulty/cross_entity_state_dependency/route_dispatch_requires_crew_available
    """
    account, prop, agreement, visit, crew, route = setup_scheduled_visit(
        region_code="NORTH", schedule_kind="ONE_TIME",
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]})
    validate_success(api.set_crew_status(crew["id"], {"status": "OFFLINE"}, DISPATCHER), 200)
    validate_success(api.set_crew_status(crew["id"], {"status": "AVAILABLE"}, DISPATCHER), 200)
    dispatched = validate_success(api.dispatch_route(route["id"], DISPATCHER), 200)
    assert dispatched["status"] == "DISPATCHED"


# ===========================================================================
# Queue B — state_machines
# ===========================================================================
def test_accept_quote_from_draft_rejected(api):
    """PRD §3.1: "From `SENT`, the customer may accept it, moving it to `ACCEPTED`".
    PRD §3.9: "The generic "transition not defined from the current state" guard
    yields `ERR_INVALID_STATE`".

    Design: Corner/state_machines/accept_quote_from_draft_returns_invalid_state
    """
    account = create_account(region_code="NORTH")
    prop = create_property(account["id"])
    quote = create_quote(account["id"], prop["id"],
                         pricing_basis="PANE_COUNT", addon_codes=["GUTTER"])
    assert quote["status"] == "DRAFT"
    cust = make_customer_headers(account["id"])
    res = api.accept_quote(quote["id"], cust)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_cancel_completed_agreement_rejected(api):
    """PRD §3.2: "Both `COMPLETED` and `CANCELLED` are terminal."
    PRD §3.9: "The generic "transition not defined from the current state" guard
    yields `ERR_INVALID_STATE`".

    Design: Corner/state_machines/cancel_agreement_from_completed_returns_invalid_state
    """
    account, prop, agreement, visit, crew, route = setup_completed_visit(
        region_code="NORTH", schedule_kind="ONE_TIME",
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]},
        after_photo_count=1)
    completed = validate_success(api.complete_agreement(agreement["id"], BILLING), 200)
    assert completed["status"] == "COMPLETED"
    cust = make_customer_headers(account["id"])
    res = api.cancel_agreement(agreement["id"], cust)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_first_visit_initial_states_unscheduled_unbilled(api):
    """PRD §3.4: "A visit carries two independent status dimensions: a
    `schedule_status` that begins `UNSCHEDULED` and a `billing_status` that begins
    `UNBILLED`; the two evolve independently of one another."

    Design: Corner/state_machines/newly_created_visit_initial_states_unscheduled_unbilled
    """
    account, prop, agreement, visit = setup_active_agreement(
        schedule_kind="ONE_TIME", region_code="NORTH",
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]})
    assert visit["schedule_status"] == "UNSCHEDULED"
    assert visit["billing_status"] == "UNBILLED"
    assert visit["reschedule_count"] == 0


def test_start_visit_without_before_photo_rejected(api):
    """PRD §3.5: "A `DISPATCHED` visit is started by the field crew, advancing its
    schedule status to `IN_PROGRESS`, but only when exactly one `BEFORE`-phase photo
    exists for the visit; starting without that before photo is rejected with
    `ERR_BEFORE_PHOTO_REQUIRED`."

    Design: Corner/state_machines/start_visit_without_before_photo_returns_before_photo_required
    """
    account, prop, agreement, visit, crew, route = setup_dispatched_visit(
        region_code="NORTH", schedule_kind="ONE_TIME",
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]})
    res = api.start_visit(visit["id"], FIELD_CREW)
    validate_error(res, "ERR_BEFORE_PHOTO_REQUIRED", expected_status=422)


def test_complete_visit_without_after_photo_rejected(api):
    """PRD §3.5: "An `IN_PROGRESS` visit is completed by the field crew, advancing
    its schedule status to `COMPLETED`, but only when at least one `AFTER`-phase
    photo exists; completing without an after photo is rejected with
    `ERR_AFTER_PHOTO_REQUIRED`."

    Design: Corner/state_machines/complete_visit_without_after_photo_returns_after_photo_required
    """
    account, prop, agreement, visit, crew, route = setup_in_progress_visit(
        region_code="NORTH", schedule_kind="ONE_TIME",
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]})
    res = api.complete_visit(visit["id"], FIELD_CREW)
    validate_error(res, "ERR_AFTER_PHOTO_REQUIRED", expected_status=422)


def test_quote_lazily_expires_when_clock_passes_valid_until(api):
    """PRD §2.10: "A quote that is still in `DRAFT` or `SENT` automatically
    transitions to `EXPIRED` the moment the current clock reaches or passes
    `valid_until`; this is evaluated lazily, on any read or transition that touches
    the quote."

    Design: Corner/state_machines/quote_lazy_expires_when_clock_past_valid_until
    """
    account = create_account(region_code="NORTH")
    prop = create_property(account["id"])
    quote = create_sent_quote(account["id"], prop["id"],
                              pricing_basis="PANE_COUNT", addon_codes=["GUTTER"],
                              valid_until="2026-07-01T00:00:00Z")
    validate_success(api.set_clock(set_clock_payload("2026-07-02T00:00:00Z"), BILLING), 200)
    read = validate_success(api.get_quote(quote["id"], BILLING), 200)
    assert read["status"] == "EXPIRED"
