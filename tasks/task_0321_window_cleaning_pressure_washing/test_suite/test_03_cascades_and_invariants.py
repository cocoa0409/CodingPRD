"""Cascading side effects and conserved-quantity invariants.

Covers the cancel -> deposit-refund -> ledger -> balance chain, the recurring
visit-generation cascade, the deposit post/refund balance conservation, the
commit/weather-reschedule route-minute conservation, the pause cascade, and the
deposit-posting derived-field reconciliation.
"""
from test_helpers import (
    api_client, validate_success,
    create_account, create_property, create_sent_quote,
    setup_pending_agreement, setup_active_agreement, setup_in_progress_visit,
    setup_scheduled_visit, activate_agreement, post_deposit, create_crew,
    create_route, commit_visit, create_weather_suspend, upload_photo,
    weather_reschedule_once,
    create_service_agreement_payload, create_deposit_payload,
    TEST_USERS, make_customer_headers,
)

BILLING = TEST_USERS["billing_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
FIELD_CREW = TEST_USERS["field_crew_headers"]


def _list(res):
    body = res.json()
    return body["data"], body["meta"]


# ===========================================================================
# Queue A — transitive_cascade
# ===========================================================================
def test_cancel_agreement_refunds_deposit_and_zeroes_balances(api):
    """PRD §3.2: "it refunds every `HELD` deposit for the agreement exactly as
    completion does — each deposit moves to `REFUNDED`, a `DEPOSIT` `LedgerEntry`
    carrying the negative of the deposit amount is posted, and the account's
    `balance_cents` and `deposit_held_cents` are recomputed."

    Design: Difficulty/transitive_cascade/agreement_cancel_cascades_to_deposit_refund_to_ledger_to_balance
    """
    account, prop, quote, agreement = setup_pending_agreement(
        schedule_kind="ONE_TIME", region_code="EAST",
        property_overrides={"pane_count": 80, "glass_sqft": 100.0, "stories": 4, "soft_wash_sqft": 400.0},
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["SOFT_WASH"]})
    deposit = post_deposit(account["id"], agreement["id"], 9000)
    activate_agreement(agreement["id"])

    cust = make_customer_headers(account["id"])
    cancelled = validate_success(api.cancel_agreement(agreement["id"], cust), 200)
    assert cancelled["status"] == "CANCELLED"

    dep_after = validate_success(api.get_deposit(deposit["id"], BILLING), 200)
    assert dep_after["status"] == "REFUNDED"
    acct_after = validate_success(api.get_account(account["id"], BILLING), 200)
    assert acct_after["deposit_held_cents"] == 0
    assert acct_after["balance_cents"] == 0


def test_cancel_agreement_moves_held_deposit_to_refunded(api):
    """PRD §3.2: "each deposit moves to `REFUNDED`, a `DEPOSIT` `LedgerEntry`
    carrying the negative of the deposit amount is posted".

    Design: Difficulty/transitive_cascade/agreement_cancel_cascades_to_deposit_refund_to_ledger_to_balance
    """
    account, prop, quote, agreement = setup_pending_agreement(
        schedule_kind="ONE_TIME", region_code="EAST",
        property_overrides={"pane_count": 80, "glass_sqft": 100.0, "stories": 4, "soft_wash_sqft": 400.0},
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["SOFT_WASH"]})
    deposit = post_deposit(account["id"], agreement["id"], 9000)
    activate_agreement(agreement["id"])
    before = validate_success(api.get_deposit(deposit["id"], BILLING), 200)
    assert before["status"] == "HELD"

    cust = make_customer_headers(account["id"])
    validate_success(api.cancel_agreement(agreement["id"], cust), 200)
    after = validate_success(api.get_deposit(deposit["id"], BILLING), 200)
    assert after["status"] == "REFUNDED"


def test_complete_recurring_visit_generates_next_visit(api):
    """PRD §3.5: "When a `RECURRING` agreement's visit completes, the system
    generates the next `Visit` in `UNSCHEDULED` status, dated at the just-completed
    visit's `planned_date` plus the agreement's `recurrence_interval_days`, and
    increments the agreement's `visits_generated_count`."

    Design: Difficulty/transitive_cascade/visit_complete_cascades_to_next_recurring_visit_generation
    """
    account, prop, agreement, visit, crew, route = setup_in_progress_visit(
        region_code="NORTH", schedule_kind="RECURRING",
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]})
    upload_photo(visit["id"], "AFTER")
    completed = validate_success(api.complete_visit(visit["id"], FIELD_CREW), 200)
    assert completed["schedule_status"] == "COMPLETED"

    agr_after = validate_success(api.get_service_agreement(agreement["id"], BILLING), 200)
    assert agr_after["visits_generated_count"] == 2


def test_complete_recurring_visit_next_visit_starts_unscheduled(api):
    """PRD §3.5: "the system generates the next `Visit` in `UNSCHEDULED` status,
    dated at the just-completed visit's `planned_date` plus the agreement's
    `recurrence_interval_days`".

    Design: Difficulty/transitive_cascade/visit_complete_cascades_to_next_recurring_visit_generation
    """
    account, prop, agreement, visit, crew, route = setup_in_progress_visit(
        region_code="NORTH", schedule_kind="RECURRING",
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]})
    upload_photo(visit["id"], "AFTER")
    validate_success(api.complete_visit(visit["id"], FIELD_CREW), 200)

    visits, _ = _list(api.list_agreement_visits(agreement["id"], BILLING))
    assert len(visits) == 2
    next_visit = [v for v in visits if v["id"] != visit["id"]][0]
    assert next_visit["schedule_status"] == "UNSCHEDULED"
    # first visit planned 2026-07-01 + 14 days = 2026-07-15
    assert next_visit["planned_date"] == "2026-07-15"


# ===========================================================================
# Queue A — compensating_invariant
# ===========================================================================
def test_deposit_post_then_refund_conserves_account_balance(api):
    """PRD §2.7: "The `balance_cents` field is the running sum of the
    `signed_amount_cents` of every `LedgerEntry` posted against the account".

    Design: Difficulty/compensating_invariant/deposit_post_then_refund_conserves_account_balance_zero
    """
    account, prop, quote, agreement = setup_pending_agreement(
        schedule_kind="ONE_TIME", region_code="EAST",
        property_overrides={"pane_count": 80, "glass_sqft": 100.0, "stories": 4, "soft_wash_sqft": 400.0},
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["SOFT_WASH"]})
    deposit = post_deposit(account["id"], agreement["id"], 9000)
    activate_agreement(agreement["id"])
    pre = validate_success(api.get_account(account["id"], BILLING), 200)
    assert pre["balance_cents"] == 9000

    cust = make_customer_headers(account["id"])
    validate_success(api.cancel_agreement(agreement["id"], cust), 200)
    post = validate_success(api.get_account(account["id"], BILLING), 200)
    assert post["balance_cents"] == 0
    assert post["deposit_held_cents"] == 0
    dep_after = validate_success(api.get_deposit(deposit["id"], BILLING), 200)
    assert dep_after["status"] == "REFUNDED"


def test_deposit_held_then_refund_zeroes_deposit_held(api):
    """PRD §2.7: "The `deposit_held_cents` field is the sum of `amount_cents`
    across all of the account's deposits that remain in `HELD` status, and it
    likewise starts at zero."

    Design: Difficulty/compensating_invariant/deposit_post_then_refund_conserves_account_balance_zero
    """
    account, prop, quote, agreement = setup_pending_agreement(
        schedule_kind="ONE_TIME", region_code="EAST",
        property_overrides={"pane_count": 80, "glass_sqft": 100.0, "stories": 4, "soft_wash_sqft": 400.0},
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["SOFT_WASH"]})
    post_deposit(account["id"], agreement["id"], 9000)
    activate_agreement(agreement["id"])
    pre = validate_success(api.get_account(account["id"], BILLING), 200)
    assert pre["deposit_held_cents"] == 9000

    cust = make_customer_headers(account["id"])
    validate_success(api.cancel_agreement(agreement["id"], cust), 200)
    post = validate_success(api.get_account(account["id"], BILLING), 200)
    assert post["deposit_held_cents"] == 0


def test_commit_then_weather_reschedule_conserves_route_minutes(api):
    """PRD §2.8: "A route's booked time, `booked_minutes`, is a derived field: it
    is the sum of the `duration_minutes` of every visit committed to that route
    whose schedule status is `SCHEDULED`, `DISPATCHED`, `IN_PROGRESS`, or
    `COMPLETED`, and it starts at zero."

    Design: Difficulty/compensating_invariant/visit_commit_then_weather_reschedule_conserves_route_minutes
    """
    account, prop, agreement, visit, crew, route = setup_scheduled_visit(
        region_code="NORTH", schedule_kind="ONE_TIME", service_date="2026-07-01",
        window_start_min=540, window_end_min=660,
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]})
    pre = validate_success(api.get_route(route["id"], DISPATCHER), 200)
    assert pre["booked_minutes"] == 120

    create_weather_suspend("NORTH", "2026-07-01")
    rescheduled = validate_success(api.weather_reschedule_visit(
        visit["id"], {"new_planned_date": "2026-07-08"}, DISPATCHER), 200)
    assert rescheduled["schedule_status"] == "UNSCHEDULED"
    assert rescheduled["reschedule_count"] == 1

    post = validate_success(api.get_route(route["id"], DISPATCHER), 200)
    assert post["booked_minutes"] == 0


def test_weather_reschedule_clears_route_id_and_returns_unscheduled(api):
    """PRD §3.6: "the visit's `route_id` is cleared to null, its schedule status
    returns to `UNSCHEDULED`, its `planned_date` is set to the supplied
    `new_planned_date`, and its `reschedule_count` increments by one."

    Design: Difficulty/compensating_invariant/visit_commit_then_weather_reschedule_conserves_route_minutes
    """
    account, prop, agreement, visit, crew, route = setup_scheduled_visit(
        region_code="NORTH", schedule_kind="ONE_TIME", service_date="2026-07-01",
        window_start_min=540, window_end_min=660,
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]})
    create_weather_suspend("NORTH", "2026-07-01")
    rescheduled = validate_success(api.weather_reschedule_visit(
        visit["id"], {"new_planned_date": "2026-07-08"}, DISPATCHER), 200)
    assert rescheduled["route_id"] is None
    assert rescheduled["schedule_status"] == "UNSCHEDULED"
    assert rescheduled["planned_date"] == "2026-07-08"
    assert rescheduled["reschedule_count"] == 1


# ===========================================================================
# Queue B — cross_cutting_complexity_layers
# ===========================================================================
def test_pause_agreement_cancels_scheduled_visit_and_frees_minutes(api):
    """PRD §3.2: "pausing cancels every one of this agreement's visits that is
    currently in schedule status `SCHEDULED`, transitioning each to `CANCELLED` and
    decrementing the `booked_minutes` of whatever route each was committed to."

    Design: Corner/cross_cutting_complexity_layers/pause_agreement_cancels_scheduled_visit_and_frees_route_minutes
    """
    account, prop, agreement, visit, crew, route = setup_scheduled_visit(
        region_code="NORTH", schedule_kind="RECURRING", service_date="2026-07-01",
        window_start_min=540, window_end_min=660,
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["GUTTER"]})
    cust = make_customer_headers(account["id"])
    validate_success(api.pause_agreement(agreement["id"], cust), 200)

    visit_after = validate_success(api.get_visit(visit["id"], DISPATCHER), 200)
    assert visit_after["schedule_status"] == "CANCELLED"
    route_after = validate_success(api.get_route(route["id"], DISPATCHER), 200)
    assert route_after["booked_minutes"] == 0


def test_posting_deposit_recomputes_account_balance_and_held(api):
    """PRD §3.3: "Posting a deposit immediately writes a `DEPOSIT` `LedgerEntry`
    debit equal to the positive deposit amount and recomputes the account's
    `deposit_held_cents` and `balance_cents`."

    Design: Corner/cross_cutting_complexity_layers/deposit_post_recomputes_account_balance_and_held
    """
    account, prop, quote, agreement = setup_pending_agreement(
        schedule_kind="ONE_TIME", region_code="EAST",
        property_overrides={"pane_count": 80, "glass_sqft": 100.0, "stories": 4, "soft_wash_sqft": 400.0},
        quote_overrides={"pricing_basis": "PANE_COUNT", "addon_codes": ["SOFT_WASH"]})
    deposit = validate_success(api.create_deposit(
        create_deposit_payload(account["id"], agreement["id"], 9000), BILLING), 201)
    assert deposit["status"] == "HELD"
    acct = validate_success(api.get_account(account["id"], BILLING), 200)
    assert acct["balance_cents"] == 9000
    assert acct["deposit_held_cents"] == 9000
