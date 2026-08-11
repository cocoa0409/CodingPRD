"""Repair tickets: rush fee branches, the QC rework loop, validation-priority
ordering between the deposit and shaft-shortage gates, and payment rules."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, api_client,
    set_clock, create_customer, create_technician, create_component_item,
    create_repair_ticket, pay_ticket, get_ticket, get_component_item,
    customer_headers, staff_headers,
)


def test_rush_regrip_uses_min_fee_branch(api):
    """PRD §3.5: "The base price is 1,800 cents for a regrip" and "Rush work
    adds a rush fee of the greater of 1,500 cents and thirty-five percent of
    the base price rounded half-up; standard work adds nothing." and "The
    `promised_at` commitment is `created_at` plus 24 hours for rush work or
    plus 72 hours for standard work."

    Design: Difficulty/combinatorial_formula/repair_quote_rush_minfee_vs_rate_branch
    """
    set_clock("2026-05-10T09:00:00Z")
    customer = create_customer("Dan Dunes")
    ticket = create_repair_ticket(customer, "REGRIP", True,
                                  club_description="7-iron")
    # 1800 + max(1500, round(1800*0.35)=630) = 3300.
    assert ticket["quoted_total_cents"] == 3_300, (
        f"expected 3300 (min-fee branch), got {ticket['quoted_total_cents']}"
    )
    assert ticket["promised_at"].startswith("2026-05-11T09:00:00"), (
        f"rush promise must be created_at + 24h, got {ticket['promised_at']}"
    )
    assert ticket["work_status"] == "QUOTED"
    assert ticket["payment_status"] == "UNPAID"


def test_rush_reshaft_uses_rate_branch(api):
    """PRD §3.5: "The base price is 1,800 cents for a regrip, 6,500 cents for
    a reshaft, and 2,500 cents for a loft-and-lie adjustment." and "Rush
    work adds a rush fee of the greater of 1,500 cents and thirty-five percent
    of the base price rounded half-up" and "The `deposit_cents` is half of the
    quoted total, rounded half-up, and the eventual balance payment is exactly
    the remainder, keeping cents exact even on odd totals."

    Design: Difficulty/combinatorial_formula/repair_quote_rush_minfee_vs_rate_branch
    """
    set_clock("2026-05-10T09:00:00Z")
    customer = create_customer("Dan Dunes")
    create_technician()
    shaft = create_component_item("SHAFT", 9_000, 12_000, 3)
    ticket = create_repair_ticket(customer, "RESHAFT", True, shaft,
                                  club_description="driver")
    # 6500 + max(1500, round(6500*0.35)=2275) = 8775.
    assert ticket["quoted_total_cents"] == 8_775, (
        f"expected 8775 (rate branch), got {ticket['quoted_total_cents']}"
    )
    # round_half_up(8775 * 0.5) = 4388; balance remainder 4387 keeps cents exact.
    assert ticket["deposit_cents"] == 4_388, (
        f"expected deposit 4388, got {ticket['deposit_cents']}"
    )
    assert ticket["quoted_total_cents"] - ticket["deposit_cents"] == 4_387
    assert ticket["work_status"] == "QUOTED"
    assert ticket["payment_status"] == "UNPAID"


def _setup_rework_ticket():
    """REGRIP standard ticket (quoted 1800, deposit 900) IN_PROGRESS."""
    set_clock("2026-05-10T09:00:00Z")
    customer = create_customer("Fay Fern")
    technician = create_technician()
    ticket = create_repair_ticket(customer, "REGRIP", False, club_description="wedge")
    ticket = get_success_data(
        api_client.approve_repair_ticket(ticket["id"], customer_headers(customer))
    )
    ticket = pay_ticket(ticket, customer, "DEPOSIT")
    ticket = get_success_data(
        api_client.start_work(ticket["id"], staff_headers(technician))
    )
    return {"customer": customer, "technician": technician, "ticket": ticket}


def test_failed_qc_loops_in_progress_and_counts_rework(api):
    """PRD §3.5: "A failure keeps the ticket in `IN_PROGRESS` in a rework loop
    and increments `rework_count` by one; there is no cap on rework."

    Design: Difficulty/non_linear_state_machine/repair_ticket_qc_rework_cycle
    """
    ctx = _setup_rework_ticket()
    th = staff_headers(ctx["technician"])
    tid = ctx["ticket"]["id"]

    t = get_success_data(api_client.submit_qc(tid, {"passed": False}, th))
    assert t["work_status"] == "IN_PROGRESS" and t["rework_count"] == 1
    t = get_success_data(api_client.submit_qc(tid, {"passed": False}, th))
    assert t["work_status"] == "IN_PROGRESS" and t["rework_count"] == 2


def test_passing_qc_after_rework_preserves_count(api):
    """PRD §3.5: "A pass moves the ticket from `IN_PROGRESS` to `READY`" and
    "A failure keeps the ticket in `IN_PROGRESS` in a rework loop and
    increments `rework_count` by one; there is no cap on rework."

    Design: Difficulty/non_linear_state_machine/repair_ticket_qc_rework_cycle
    """
    ctx = _setup_rework_ticket()
    th = staff_headers(ctx["technician"])
    tid = ctx["ticket"]["id"]

    get_success_data(api_client.submit_qc(tid, {"passed": False}, th))
    get_success_data(api_client.submit_qc(tid, {"passed": False}, th))
    t = get_success_data(api_client.submit_qc(tid, {"passed": True}, th))
    assert t["work_status"] == "READY", f"passing QC must move to READY, got {t['work_status']}"
    assert t["rework_count"] == 2, "the rework counter never resets"


def _setup_approved_reshaft_unpaid_no_stock():
    """RESHAFT ticket APPROVED, payment UNPAID, shaft stock_on_hand 0."""
    set_clock("2026-05-10T09:00:00Z")
    customer = create_customer("Kai Knot")
    technician = create_technician()
    shaft = create_component_item("SHAFT", 12_000, 18_000, 0)
    ticket = create_repair_ticket(customer, "RESHAFT", False, shaft,
                                  club_description="driver")
    ticket = get_success_data(
        api_client.approve_repair_ticket(ticket["id"], customer_headers(customer))
    )
    return {"customer": customer, "technician": technician,
            "ticket": ticket, "shaft": shaft}


def test_start_work_deposit_error_beats_shortage_error(api):
    """PRD §2.10: "Tenth, fiscal rules before any parts are committed —
    customer standing, credit sufficiency, lesson-credit availability,
    deposit-before-work, payment sequencing, and paid-in-full before pickup.
    Eleventh and last, structural constraints — reshaft shaft requirements,
    component-slot type matching, shaft stock for bench work, the appeal cap,
    and duplicate-claim detection."

    Design: Difficulty/priority_pair_validation_conflict/start_work_deposit_error_beats_shortage_error
    """
    ctx = _setup_approved_reshaft_unpaid_no_stock()
    resp = api_client.start_work(ctx["ticket"]["id"], staff_headers(ctx["technician"]))
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_REQUIRED)


def test_start_work_dual_violation_leaves_no_side_effects(api):
    """PRD §3.5: "The deposit must be in: starting work while `payment_status`
    is still `UNPAID` is rejected with `ERR_DEPOSIT_REQUIRED` (HTTP 422)." and
    "A successful start-work on a reshaft reserves the shaft — one unit moves
    from `stock_on_hand` to `stock_reserved`."

    Design: Difficulty/priority_pair_validation_conflict/start_work_deposit_error_beats_shortage_error
    """
    ctx = _setup_approved_reshaft_unpaid_no_stock()
    resp = api_client.start_work(ctx["ticket"]["id"], staff_headers(ctx["technician"]))
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_REQUIRED)

    ticket = get_ticket(ctx["ticket"]["id"], staff_headers(ctx["technician"]))
    assert ticket["work_status"] == "APPROVED", (
        f"rejected start-work must leave the ticket APPROVED, got {ticket['work_status']}"
    )
    shaft = get_component_item(ctx["shaft"]["id"], staff_headers(ctx["technician"]))
    assert shaft["stock_reserved"] == 0, "no partial reservation may be left behind"


def test_rush_defaults_to_false_and_standard_terms(api):
    """PRD §3.5: "an optional `rush` flag defaulting to false" and "standard
    work adds nothing" and "The `promised_at` commitment is `created_at` plus
    24 hours for rush work or plus 72 hours for standard work."

    Design: Corner/entities/repair_ticket_rush_default_false
    """
    set_clock("2026-05-10T09:00:00Z")
    customer = create_customer("Tom Tao")
    # rush omitted entirely from the payload.
    ticket = create_repair_ticket(customer, "REGRIP", None,
                                  club_description="7-iron")
    assert ticket["rush"] is False
    assert ticket["quoted_total_cents"] == 1_800, (
        f"standard regrip must be the bare base 1800, got {ticket['quoted_total_cents']}"
    )
    assert ticket["promised_at"].startswith("2026-05-13T09:00:00"), (
        f"standard promise must be created_at + 72h, got {ticket['promised_at']}"
    )


def test_payment_dimension_independent_of_work_status(api):
    """PRD §3.5: "Work on a ticket and money on a ticket are parallel
    dimensions that evolve independently except where one gates the other."
    and "The payment dimension runs `UNPAID` to `DEPOSIT_PAID` to `PAID`".

    Design: Corner/state_machines/ticket_payment_dimension_independent_of_work
    """
    set_clock("2026-05-10T09:00:00Z")
    customer = create_customer("Ira Inlet")
    ticket = create_repair_ticket(customer, "REGRIP", False, club_description="wedge")
    ticket = pay_ticket(ticket, customer, "DEPOSIT")
    assert ticket["payment_status"] == "DEPOSIT_PAID"
    assert ticket["work_status"] == "QUOTED", (
        f"paying the deposit must not move the work dimension, got {ticket['work_status']}"
    )


def test_reshaft_without_shaft_item_rejected(api):
    """PRD §3.5: "A `RESHAFT` ticket without a `shaft_item_id`, or with one
    pointing at an item whose `component_type` is not `SHAFT`, is rejected
    with `ERR_RESHAFT_REQUIRES_SHAFT_ITEM` (HTTP 400)".

    Design: Corner/validations/reshaft_without_shaft_item_rejected
    """
    customer = create_customer("Rex Row")
    payload = {
        "customer_id": customer["id"],
        "club_description": "driver",
        "service_type": "RESHAFT",
        "rush": False,
    }
    resp = api_client.create_repair_ticket(payload, customer_headers(customer))
    validate_error(resp, ApiErrorId.ERR_RESHAFT_REQUIRES_SHAFT_ITEM)


def test_shaft_shortage_after_deposit_rejected(api):
    """PRD §3.5: "for a reshaft, the chosen shaft must physically exist on the
    wall: if `shaft_item_id` is present and its `stock_on_hand` is below one,
    start-work fails with `ERR_COMPONENT_SHORTAGE` (HTTP 409)."

    Design: Corner/validations/shaft_shortage_after_deposit_rejected
    """
    set_clock("2026-05-10T09:00:00Z")
    customer = create_customer("Tad Tor")
    technician = create_technician()
    shaft = create_component_item("SHAFT", 12_000, 18_000, 0)
    ticket = create_repair_ticket(customer, "RESHAFT", False, shaft,
                                  club_description="driver")
    ticket = get_success_data(
        api_client.approve_repair_ticket(ticket["id"], customer_headers(customer))
    )
    ticket = pay_ticket(ticket, customer, "DEPOSIT")
    resp = api_client.start_work(ticket["id"], staff_headers(technician))
    validate_error(resp, ApiErrorId.ERR_COMPONENT_SHORTAGE)
    shaft_after = get_component_item(shaft["id"], staff_headers(technician))
    assert shaft_after["stock_reserved"] == 0, "no partial reservation may be left behind"


def test_pickup_requires_paid_in_full(api):
    """PRD §3.5: "pickup while `payment_status` is anything but `PAID` is
    rejected with `ERR_TICKET_UNPAID` (HTTP 422)".

    Design: Corner/validations/ticket_pickup_unpaid_rejected
    """
    set_clock("2026-05-10T09:00:00Z")
    customer = create_customer("Yul Yew")
    technician = create_technician()
    ticket = create_repair_ticket(customer, "REGRIP", False, club_description="wedge")
    ticket = get_success_data(
        api_client.approve_repair_ticket(ticket["id"], customer_headers(customer))
    )
    ticket = pay_ticket(ticket, customer, "DEPOSIT")
    ticket = get_success_data(
        api_client.start_work(ticket["id"], staff_headers(technician))
    )
    ticket = get_success_data(
        api_client.submit_qc(ticket["id"], {"passed": True}, staff_headers(technician))
    )
    assert ticket["work_status"] == "READY"
    assert ticket["payment_status"] == "DEPOSIT_PAID"

    resp = api_client.pickup_ticket(ticket["id"], customer_headers(customer))
    validate_error(resp, ApiErrorId.ERR_TICKET_UNPAID)
    ticket = get_ticket(ticket["id"], customer_headers(customer))
    assert ticket["work_status"] == "READY"


def test_balance_before_deposit_rejected(api):
    """PRD §3.5: "Sequence is strict: a `DEPOSIT` payment is accepted only
    while `UNPAID`, a `BALANCE` payment only while `DEPOSIT_PAID`, and any
    payment at all while `PAID` or `REFUNDED` is rejected — each sequencing
    violation earns `ERR_PAYMENT_SEQUENCE` (HTTP 409)."

    Design: Corner/validations/balance_before_deposit_rejected
    """
    set_clock("2026-05-10T09:00:00Z")
    customer = create_customer("Zeb Zoll")
    ticket = create_repair_ticket(customer, "REGRIP", False,
                                  club_description="7-iron")
    resp = api_client.pay_ticket(
        ticket["id"], {"kind": "BALANCE", "method": "EXTERNAL"},
        customer_headers(customer),
    )
    validate_error(resp, ApiErrorId.ERR_PAYMENT_SEQUENCE)
    ticket = get_ticket(ticket["id"], customer_headers(customer))
    assert ticket["payment_status"] == "UNPAID"
