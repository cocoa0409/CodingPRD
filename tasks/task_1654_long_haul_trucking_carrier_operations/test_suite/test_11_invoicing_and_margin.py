"""Invoicing: creation guards, the open-accessorial aggregate gate, issue /
mark-paid / void lifecycle, the compensating void-reissue invariant, and the
provisional-vs-final margin variants (PRD §3.2, §3.6)."""
from test_helpers import (
    ApiErrorId,
    adjudicate_to_approved,
    api_client,
    first_load_accessorial_id,
    get_accessorial,
    get_load,
    make_load_planner_headers,
    screen_load,
    setup_accepted_load,
    setup_delivered_trip,
    setup_delivered_trip_no_detention,
    setup_issued_invoice,
    tender_load,
    validate_error,
    validate_success,
)

LOAD_PLANNER = make_load_planner_headers()


def test_issue_bills_accessorials_and_mark_paid_closes_load(api):
    """PRD §3.6: "On issue, every `APPROVED` accessorial of the load flips to
    `BILLED`; `accessorial_total_cents` becomes the sum of those newly billed
    amounts; `total_cents` is the sum of `linehaul_cents`,
    `fuel_surcharge_cents`, and `accessorial_total_cents`; and the invoice
    moves from `DRAFT` to `ISSUED`."
    PRD §3.6: "Marking an `ISSUED` invoice paid — from any other state,
    `ERR_INVOICE_NOT_PAYABLE` — moves it to the terminal `PAID` state and
    closes the load, `INVOICED` to `CLOSED`."

    Design: Corner/state_machines/invoice_issue_pay_closes_load_and_locks
    """
    ctx = setup_delivered_trip(cdl_number="CDL-C20", unit_number="T-C20")
    acc_id = first_load_accessorial_id(ctx["load"]["id"])
    adjudicate_to_approved(acc_id)
    invoice = validate_success(
        api_client.create_load_invoice(ctx["load"]["id"], LOAD_PLANNER),
        expected_status=201)
    issued = validate_success(api_client.issue_invoice(invoice["id"], LOAD_PLANNER))
    assert issued["status"] == "ISSUED"
    assert issued["total_cents"] == 276769, "250000 + 20769 + 6000"
    assert get_accessorial(acc_id)["status"] == "BILLED"

    paid = validate_success(api_client.mark_invoice_paid(invoice["id"], LOAD_PLANNER))
    assert paid["status"] == "PAID"
    assert get_load(ctx["load"]["id"])["status"] == "CLOSED"
    validate_error(api_client.mark_invoice_paid(invoice["id"], LOAD_PLANNER),
                   ApiErrorId.ERR_INVOICE_NOT_PAYABLE)


def test_issue_blocked_by_open_accessorial(api):
    """PRD §3.6: "no accessorial of the load may remain open: any charge in
    `PENDING`, `SUBMITTED`, or `DISPUTED` blocks the issue with
    `ERR_INVOICE_OPEN_ACCESSORIALS`, leaving `APPROVED`, `BILLED`, and
    `REJECTED` charges admissible."

    Design: Corner/validations/invoice_issue_blocked_by_open_accessorial
    """
    ctx = setup_delivered_trip(cdl_number="CDL-V8", unit_number="T-V8")
    acc_id = first_load_accessorial_id(ctx["load"]["id"])  # PENDING
    invoice = validate_success(
        api_client.create_load_invoice(ctx["load"]["id"], LOAD_PLANNER),
        expected_status=201)
    validate_error(api_client.issue_invoice(invoice["id"], LOAD_PLANNER),
                   ApiErrorId.ERR_INVOICE_OPEN_ACCESSORIALS)
    adjudicate_to_approved(acc_id)
    issued = validate_success(api_client.issue_invoice(invoice["id"], LOAD_PLANNER))
    assert issued["status"] == "ISSUED"
    assert issued["total_cents"] == 276769
    assert get_accessorial(acc_id)["status"] == "BILLED"


def test_invoice_create_issue_void_state_guards(api):
    """PRD §3.6: "An invoice is created by a `LoadPlanner` against a load that
    has reached `DELIVERED` — creating one against a load in any other status
    is rejected with `ERR_INVOICE_NOT_ISSUABLE` — and a load may have at most
    one non-`VOID` invoice at a time, a second attempt drawing
    `ERR_INVOICE_ALREADY_EXISTS`."
    PRD §3.6: "The invoice must be `DRAFT` and the load still `DELIVERED` —
    either violation is `ERR_INVOICE_NOT_ISSUABLE`".
    PRD §3.6: "Voiding an `ISSUED` invoice — from any other state,
    `ERR_INVOICE_NOT_VOIDABLE` — is the compensating unwind".

    Design: Corner/errors/invoice_create_issue_void_state_errors
    """
    ctx = setup_delivered_trip_no_detention(cdl_number="CDL-R10",
                                            unit_number="T-R10")
    load2 = tender_load(ctx["customer"]["id"], ctx["lane"]["id"],
                        pickup_appt_at="2026-08-04T08:00:00Z",
                        delivery_appt_at="2026-08-05T18:00:00Z")
    screen_load(load2["id"])
    validate_success(api_client.accept_load(load2["id"], LOAD_PLANNER))

    validate_error(api_client.create_load_invoice(load2["id"], LOAD_PLANNER),
                   ApiErrorId.ERR_INVOICE_NOT_ISSUABLE)
    invoice = validate_success(
        api_client.create_load_invoice(ctx["load"]["id"], LOAD_PLANNER),
        expected_status=201)
    validate_error(api_client.create_load_invoice(ctx["load"]["id"], LOAD_PLANNER),
                   ApiErrorId.ERR_INVOICE_ALREADY_EXISTS)
    validate_error(api_client.void_invoice(invoice["id"], LOAD_PLANNER),
                   ApiErrorId.ERR_INVOICE_NOT_VOIDABLE)
    issued = validate_success(api_client.issue_invoice(invoice["id"], LOAD_PLANNER))
    assert issued["status"] == "ISSUED"
    assert issued["total_cents"] == 270769, "250000 + 20769 + 0"
    validate_error(api_client.issue_invoice(invoice["id"], LOAD_PLANNER),
                   ApiErrorId.ERR_INVOICE_NOT_ISSUABLE)


# ---------------------------------------------------------------------------
# Queue A: compensating_invariant / invoice_void_reissue_conserves_total
# ---------------------------------------------------------------------------

def test_invoice_void_restores_accessorial_and_load_state(api):
    """PRD §3.6: "Voiding an `ISSUED` invoice — from any other state,
    `ERR_INVOICE_NOT_VOIDABLE` — is the compensating unwind: the invoice lands
    in the terminal `VOID` state, every `BILLED` accessorial of the load flips
    back to `APPROVED`, the load returns from `INVOICED` to `DELIVERED` with
    its `final_margin_cents` cleared to null, and the load's
    `total_accessorial_cents` is recomputed with no billed charges remaining."

    Design: Difficulty/compensating_invariant/invoice_void_reissue_conserves_total
    """
    ctx = setup_issued_invoice(cdl_number="CDL-16", unit_number="T-20")
    assert ctx["invoice"]["total_cents"] == 276769
    voided = validate_success(api_client.void_invoice(ctx["invoice"]["id"],
                                                      LOAD_PLANNER))
    assert voided["status"] == "VOID"
    assert get_accessorial(ctx["accessorial"]["id"])["status"] == "APPROVED"
    load = get_load(ctx["load"]["id"])
    assert load["status"] == "DELIVERED"
    assert load["total_accessorial_cents"] == 0
    assert load.get("final_margin_cents") is None


def test_reissue_after_void_conserves_billed_total(api):
    """PRD §3.6: "At creation the invoice is `DRAFT` and snapshots the load's
    `rate_cents` into `linehaul_cents` and the load's `fuel_surcharge_cents`
    into its own `fuel_surcharge_cents`" — so issue -> void -> recreate ->
    issue reproduces the identical total (276769) from unchanged inputs.

    Design: Difficulty/compensating_invariant/invoice_void_reissue_conserves_total
    """
    ctx = setup_issued_invoice(cdl_number="CDL-16", unit_number="T-20")
    first_total = ctx["invoice"]["total_cents"]
    assert first_total == 276769
    validate_success(api_client.void_invoice(ctx["invoice"]["id"], LOAD_PLANNER))
    invoice2 = validate_success(
        api_client.create_load_invoice(ctx["load"]["id"], LOAD_PLANNER),
        expected_status=201)
    issued2 = validate_success(api_client.issue_invoice(invoice2["id"],
                                                        LOAD_PLANNER))
    assert issued2["total_cents"] == 276769 == first_total, (
        "re-issue conserves the billed total exactly")


# ---------------------------------------------------------------------------
# Queue A: dual_variant_calc / load_margin_provisional_vs_final
# ---------------------------------------------------------------------------

def test_provisional_margin_computed_at_screen(api):
    """PRD §3.2: "Estimated total miles are the lane's `loaded_miles` plus a
    flat deadhead allowance of 100 miles. Projected revenue is the `rate_cents`
    linehaul plus the freshly computed `fuel_surcharge_cents`. Projected cost
    charges every estimated mile at 145 cents of variable operating cost and —
    because no driver has been assigned yet — a further 62 cents per mile of
    fleet-average driver pay."
    (FSC round_half_up(900 * 150 / 6.5) = 20769; margin 270769 - 207000 =
    63769; rpm round_half_up(270769/1000) = 271.)

    Design: Difficulty/dual_variant_calc/load_margin_provisional_vs_final
    """
    ctx = setup_accepted_load()
    accepted = ctx["load"]
    assert accepted["fuel_surcharge_cents"] == 20769
    assert accepted["projected_margin_cents"] == 63769
    assert accepted["projected_rpm_cents"] == 271


def test_final_margin_differs_from_provisional_at_issue(api):
    """PRD §3.6: "The same event moves the load from `DELIVERED` to `INVOICED`
    and computes the final margin: revenue is now the `rate_cents` linehaul
    plus the snapshotted `fuel_surcharge_cents` plus the newly billed
    accessorial total; miles are the completing trip's `actual_miles`; cost is
    those miles at the same 145-cent variable rate plus the trip's
    `final_pay_cents`; and `final_margin_cents` is the difference."
    (276769 - (1050 * 145 + 65100) = 59419, vs provisional 63769.)

    Design: Difficulty/dual_variant_calc/load_margin_provisional_vs_final
    """
    ctx = setup_issued_invoice(cdl_number="CDL-1", unit_number="T-1")
    assert ctx["invoice"]["total_cents"] == 276769
    load = get_load(ctx["load"]["id"])
    assert load["status"] == "INVOICED"
    assert load["final_margin_cents"] == 59419
    assert load["projected_margin_cents"] == 63769
    assert load["final_margin_cents"] != load["projected_margin_cents"]
