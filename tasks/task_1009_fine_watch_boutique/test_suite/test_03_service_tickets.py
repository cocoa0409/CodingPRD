"""Service quote computation, the parallel workflow/payment dimensions of a
ticket, terminal lockdown, and the Watchmaker-exclusive diagnose gate."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    service_context, open_ticket, ticket_ready_unpaid, ticket_collected,
    make_watchmaker_headers, TEST_USERS,
)

ASSOC = TEST_USERS["associate_headers"]


def test_grand_complication_movement_overhaul_quote(api):
    """PRD §3.6: "Labor is a base amount for the service type — 8000 cents for
    BATTERY, 60000 cents for MOVEMENT_OVERHAUL, 25000 cents for WATER_RESISTANCE —
    multiplied by a complication factor of 1.0 for STANDARD, 1.5 for CHRONOGRAPH,
    or 2.5 for GRAND_COMPLICATION."
    PRD §3.6: "The raw total is labor plus parts_cost_cents plus the water
    surcharge, rounded half-up, and then clamped to lie between a floor of 12000
    cents and a ceiling of 500000 cents."

    Design: Difficulty/combinatorial_formula/service_quote_nonlinear_labor_complication_water
    """
    ctx = service_context()
    ticket = open_ticket(ctx, service_type="MOVEMENT_OVERHAUL",
                         movement_complexity="GRAND_COMPLICATION", parts_cost_cents=15000,
                         appt_start="2026-07-03T10:00:00Z", appt_end="2026-07-03T12:00:00Z")
    wm = make_watchmaker_headers(ctx["watchmaker"]["id"])
    data = validate_success(api.diagnose_ticket(ticket["id"], wm))
    # 60000 * 2.5 = 150000 labor, + 15000 parts = 165000, within [12000, 500000].
    assert data["quoted_cents"] == 165000, data["quoted_cents"]


def test_diagnose_transitions_received_to_diagnosed_with_quote(api):
    """PRD §3.6: "Diagnosis moves the ticket RECEIVED → DIAGNOSED and computes the
    quoted_cents. The quote is built in a fixed order: labor first, then parts, then
    a water surcharge, then a clamp."

    Design: Difficulty/combinatorial_formula/service_quote_nonlinear_labor_complication_water
    """
    ctx = service_context()
    ticket = open_ticket(ctx, service_type="MOVEMENT_OVERHAUL",
                         movement_complexity="GRAND_COMPLICATION", parts_cost_cents=15000,
                         appt_start="2026-07-03T10:00:00Z", appt_end="2026-07-03T12:00:00Z")
    assert ticket["status"] == "RECEIVED"
    wm = make_watchmaker_headers(ctx["watchmaker"]["id"])
    data = validate_success(api.diagnose_ticket(ticket["id"], wm))
    assert data["status"] == "DIAGNOSED"
    assert data["quoted_cents"] == 165000


def test_collect_blocked_while_ready_but_unpaid(api):
    """PRD §3.6: "Collection is the one action gated on both ticket dimensions: it
    moves the workflow READY → COLLECTED only when the ticket is READY and its
    payment_status is PAID, rejecting an unpaid collection with
    ERR_PAYMENT_NOT_COMPLETE (409)."

    Design: Difficulty/non_linear_state_machine/service_ticket_parallel_status_payment
    """
    ctx = ticket_ready_unpaid(service_type="BATTERY")
    ticket = ctx["ticket"]
    assert ticket["status"] == "READY" and ticket["payment_status"] == "UNPAID"
    validate_error(api.collect_ticket(ticket["id"], ASSOC), ApiErrorId.ERR_PAYMENT_NOT_COMPLETE)


def test_payment_completes_then_collection_succeeds(api):
    """PRD §3.6: "While the running total stays below the quote the payment_status
    sits at PARTIALLY_PAID; when it reaches exactly quoted_cents the payment_status
    becomes PAID."
    PRD §3.6: "On collection the watch returns IN_SERVICE → IN_STOCK and any loaner
    interval is released."

    Design: Difficulty/non_linear_state_machine/service_ticket_parallel_status_payment
    """
    ctx = ticket_ready_unpaid(service_type="BATTERY")
    tid = ctx["ticket"]["id"]
    assert ctx["ticket"]["quoted_cents"] == 12000  # BATTERY base 8000 clamped up to 12000 floor
    paid = validate_success(api.pay_ticket(tid, {"amount_cents": 12000}, ASSOC))
    assert paid["payment_status"] == "PAID"
    collected = validate_success(api.collect_ticket(tid, ASSOC))
    assert collected["status"] == "COLLECTED"


def test_diagnose_on_collected_ticket_rejected(api):
    """PRD §3.6: "Diagnosis moves the ticket RECEIVED → DIAGNOSED and computes the
    quoted_cents."
    PRD §2.10: "Among the business rules, state-validity checks (ERR_INVALID_STATE,
    409) and the specific business constraints described throughout Section 3
    apply".

    Design: Corner/state_machines/diagnose_collected_ticket_terminal_lockdown
    """
    ctx = ticket_collected()
    tid = ctx["ticket"]["id"]
    assert ctx["ticket"]["status"] == "COLLECTED"
    wm = make_watchmaker_headers(ctx["watchmaker"]["id"])
    validate_error(api.diagnose_ticket(tid, wm), ApiErrorId.ERR_INVALID_STATE)


def test_diagnose_by_associate_is_unauthorized(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with ERR_UNAUTHORIZED
    (HTTP 403)."
    PRD §2.1: "When X-User-Role is Watchmaker, X-User-ID is the id of the acting
    Watchmaker ... A watchmaker works their own bench tickets — diagnosing and
    finishing them."

    Design: Corner/rbac/diagnose_by_associate_unauthorized
    """
    ctx = service_context()
    ticket = open_ticket(ctx)
    validate_error(api.diagnose_ticket(ticket["id"], ASSOC), ApiErrorId.ERR_UNAUTHORIZED)
