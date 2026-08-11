"""Pipeline O: billable visits inside the service window."""

from test_helpers import (
    CLERK,
    COORD,
    ApiErrorId,
    assert_money,
    assert_visit,
    occupied_authorize_and_collect,
    set_clock,
    setup_occupied_agent_draft,
    setup_occupied_invoice_issued,
    validate_error,
    validate_success,
)


def test_a_short_visit_still_bills_the_two_hour_minimum(api):
    """PRD §3.7: "On completion the visit's `billable_hours` becomes the larger of the
    reported `hours_logged` and the minimum billable quantum of 2.0 hours, rounded half-up
    to two decimal places; a visit that is not `COMPLETED` has `billable_hours` of 0."
    PRD §3.7: "Each visit carries a `scheduled_at` that must fall on or before the project's
    `service_window_end_date`, and the service assigns a `visit_index`, the 1-based creation
    order of that visit within its project."
    PRD §3.3: "Under `AGENT` the listing agent is billed and the deposit is 20 percent of the
    contract value."

    Design: Corner/calculations/visit_billable_hours_applies_the_two_hour_minimum
    """
    ctx = setup_occupied_agent_draft()
    deposit_id = occupied_authorize_and_collect(ctx, actor="agent")
    visit = validate_success(api.schedule_visit(
        ctx["proj_id"], "2026-06-02T09:00:00Z", COORD), 201)
    set_clock("2026-06-02T09:00:00Z")

    validate_success(api.complete_visit(visit["id"], 1.5, COORD))

    stored = validate_success(api.get_visit(visit["id"], COORD))
    assert_visit(stored)
    assert float(stored["hours_logged"]) == 1.5
    assert float(stored["billable_hours"]) == 2.0
    assert stored["visit_index"] == 1
    deposit = validate_success(api.get_deposit(deposit_id, CLERK))
    assert_money(deposit["amount"], 829.00, "deposit.amount")
    project = validate_success(api.get_project(ctx["proj_id"], COORD))
    assert project["workflow_state"] == "STAGED"


def test_a_cancelled_visit_contributes_nothing_to_the_labour_component(api):
    """PRD §3.7: "The labour that reaches the invoice is aggregated from completed visits
    only; `NO_ACCESS` and `CANCELLED` visits contribute nothing."
    PRD §3.7: "That total is multiplied by the hourly rate of 165.00 and rounded half-up to
    two decimal places, and then — **after that rounding, not inside it** — a first-visit
    surcharge of 95.00 is added when any completed visit carries `visit_index` 1."
    PRD §3.9: "In every other case — `AGENT`, `SPLIT`, a non-exempt `BROKERAGE`, and
    `PAY_AT_CLOSING` — the whole `subtotal` is multiplied by the standard rate of 8.25
    percent."

    Design: Corner/calculations/occupied_labour_charge_excludes_no_access_visits
    """
    ctx = setup_occupied_agent_draft()
    occupied_authorize_and_collect(ctx, actor="agent")
    visit_1 = validate_success(api.schedule_visit(
        ctx["proj_id"], "2026-06-02T09:00:00Z", COORD), 201)
    visit_2 = validate_success(api.schedule_visit(
        ctx["proj_id"], "2026-06-03T09:00:00Z", COORD), 201)
    set_clock("2026-06-02T09:00:00Z")
    validate_success(api.complete_visit(visit_1["id"], 3.0, COORD))
    validate_success(api.cancel_visit(visit_2["id"], COORD))

    invoice = validate_success(api.open_closeout(ctx["proj_id"], CLERK), 201)

    assert float(validate_success(
        api.get_visit(visit_1["id"], COORD))["billable_hours"]) == 3.0
    assert validate_success(api.get_visit(visit_2["id"], COORD))["state"] == "CANCELLED"
    assert_money(invoice["subtotal"], 2990.00, "invoice.subtotal")
    assert_money(invoice["tax_amount"], 246.68, "invoice.tax_amount")
    assert_money(invoice["total_due"], 3236.68, "invoice.total_due")


def test_completing_a_visit_twice_is_an_invalid_visit_state(api):
    """PRD §2.7: "Rung 25: the visit's `state` is a legal origin for the requested
    transition; otherwise `ERR_VISIT_INVALID_STATE`, HTTP 409."
    PRD §3.7: "Completing a visit reports its `hours_logged`."

    Design: Corner/errors/completing_a_visit_twice_returns_visit_invalid_state
    """
    ctx = setup_occupied_invoice_issued()

    resp = api.complete_visit(ctx["visit_id"], 2.0, COORD)

    validate_error(resp, ApiErrorId.ERR_VISIT_INVALID_STATE.value, 409)
    visit = validate_success(api.get_visit(ctx["visit_id"], COORD))
    assert float(visit["hours_logged"]) == 2.0
    assert float(visit["billable_hours"]) == 2.0


def test_the_third_visit_reschedule_hits_the_attempt_limit(api):
    """PRD §2.7: "Rung 57: the visit's `attempt_count` is strictly less than 2 before a
    `NO_ACCESS` visit may be rescheduled; otherwise `ERR_VISIT_ATTEMPT_LIMIT`, HTTP 409."
    PRD §3.7: "It may then be re-booked to a new `scheduled_at`, moving `NO_ACCESS →
    SCHEDULED` and incrementing `attempt_count`, provided `attempt_count` is strictly below
    2 and the new instant is still on or before the service window's end; the third attempt
    is refused with `ERR_VISIT_ATTEMPT_LIMIT`."

    Design: Corner/errors/third_visit_reschedule_hits_the_attempt_limit
    """
    ctx = setup_occupied_agent_draft()
    occupied_authorize_and_collect(ctx, actor="agent")
    visit = validate_success(api.schedule_visit(
        ctx["proj_id"], "2026-06-02T09:00:00Z", COORD), 201)
    for now, nxt in (("2026-06-02T09:00:00Z", "2026-06-03T09:00:00Z"),
                     ("2026-06-03T09:00:00Z", "2026-06-04T09:00:00Z")):
        set_clock(now)
        validate_success(api.visit_no_access(visit["id"], COORD))
        validate_success(api.reschedule_visit(visit["id"], nxt, COORD))
    set_clock("2026-06-04T09:00:00Z")
    validate_success(api.visit_no_access(visit["id"], COORD))

    resp = api.reschedule_visit(visit["id"], "2026-06-05T09:00:00Z", COORD)

    validate_error(resp, ApiErrorId.ERR_VISIT_ATTEMPT_LIMIT.value, 409)
    stored = validate_success(api.get_visit(visit["id"], COORD))
    assert stored["attempt_count"] == 2
    assert stored["state"] == "NO_ACCESS"
