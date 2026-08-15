"""Invoices: composition order, dual-variant divergence, disputes, payment."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    register_carrier,
    register_escort,
    set_clock,
    create_tx_job,
    list_job_legs,
    quote_job,
    accept_quote,
    get_job,
    get_invoice,
    get_carrier,
    setup_booked_job,
    setup_delivered_rear_job,
    setup_delivered_superload_tx,
    advance_to_cleared,
    advance_to_scheduled,
    advance_to_en_route,
    advance_to_delivered,
    offer_and_accept,
    open_delay,
    close_delay,
    generate_invoice,
    finalize_invoice,
    dispute_invoice,
    adjust_invoice,
    record_payment,
    add_permit,
    issue_permit,
    request_survey,
    submit_survey,
    decide_survey,
    confirm_police,
    offer_assignment,
    accept_assignment,
    check_in,
    depart_job,
    deliver_job,
    assert_invoice_invariants,
    make_carrier_rep_headers,
    make_billing_clerk_headers,
    leg_spec,
    api_client,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


def _setup_divergence_job():
    """TX job width 170 / height 170 (rear 1, survey required), delivered after
    a 270-minute movement with one 45-minute CARRIER_DELAY."""
    carrier = register_carrier(10_000_000, "Acme Heavy Haul")
    esc = register_escort(("TX",), "Escort One")
    bundle = setup_booked_job(carrier, load_description="Press brake", height_inches=170)
    bundle["escort"] = esc
    quoted_cents = get_job(bundle["job"]["id"])["quoted_cents"]
    advance_to_cleared(bundle, survey_clearance=180, permit_kwargs={"permit_number": "TX-P-1"})
    offer_and_accept(bundle, esc, "REAR")
    advance_to_scheduled(bundle)
    advance_to_en_route(bundle, "2026-08-10T09:00:00Z")
    set_clock("2026-08-10T10:00:00Z")
    delay = open_delay(bundle["job"]["id"], "CARRIER_DELAY", "2026-08-10T10:00:00Z")
    set_clock("2026-08-10T10:45:00Z")
    close_delay(delay["id"])
    advance_to_delivered(bundle, "2026-08-10T13:30:00Z", checkin_at="2026-08-10T12:00:00Z")
    bundle["quoted_cents"] = quoted_cents
    return bundle


def test_quote_vs_final_invoice_divergence(api):
    """PRD §3.3: "the estimated escort hours are the leg's `distance_miles`
    divided by an assumed average speed of 50 miles per hour, with the quotient
    rounded up to a multiple of half an hour"
    PRD §3.6: "subject to a floor of four billable hours per assignment"

    Design: Difficulty/dual_variant_calc/job_quote_vs_final_invoice_divergence
    """
    bundle = _setup_divergence_job()
    inv = generate_invoice(bundle["job"]["id"], "bc-1")

    # Provisional variant: 2.5 estimated hours x 1 position x 9000 = 22500 + 25000 survey fee.
    assert bundle["quoted_cents"] == 47500
    # Final variant: 270 actual minutes -> 4.5h (floor not binding) + standby.
    assert inv["total_cents"] == 71960
    assert bundle["quoted_cents"] != inv["total_cents"], (
        "identical job dimensions, divergent variants"
    )


def test_invoice_line_breakdown_vs_quote(api):
    """PRD §3.8: "First, `base_charges_cents` is the sum of
    `assignment_fee_cents` over the job's `COMPLETED` assignments. Second,
    `equipment_charges_cents` sums, over all legs of the job, 15,000 cents per
    leg requiring a height pole, 40,000 cents per leg requiring a police
    escort, and 25,000 cents per leg requiring a route survey. Third,
    `standby_total_cents` is the sum of `standby_amount_cents` over the job's
    `CLOSED` delay events."

    Design: Difficulty/dual_variant_calc/job_quote_vs_final_invoice_divergence
    """
    bundle = _setup_divergence_job()
    inv = generate_invoice(bundle["job"]["id"], "bc-1")

    assert inv["base_charges_cents"] == 40500, "4.5 actual hours x 9000"
    assert inv["equipment_charges_cents"] == 25000, "survey fee only"
    assert inv["standby_total_cents"] == 1875, "0.25h x 7500 x 1 position"
    assert inv["subtotal_cents"] == 67375
    assert inv["volume_discount_cents"] == 0, "tier basis 67375 < 100000"
    assert inv["fuel_surcharge_cents"] == 4585, "round_half_up(65500 x 0.07)"
    assert inv["total_cents"] == 71960
    assert_invoice_invariants(inv)


def test_invoice_discount_tier_reads_this_subtotal(api):
    """PRD §3.8: "Fifth, the volume discount: the tier basis is the carrier's
    `ytd_billed_cents` plus this invoice's subtotal; when the basis is at least
    500,000 cents the discount rate is 5 percent, otherwise when it is at least
    100,000 cents the rate is 2 percent, otherwise 0 percent, and
    `volume_discount_cents` is the subtotal multiplied by that rate, rounded
    half up to a whole cent."

    Design: Difficulty/combinatorial_formula/invoice_evaluation_order
    """
    bundle = setup_delivered_superload_tx(with_delay=True)
    inv = generate_invoice(bundle["job"]["id"], "bc-1")

    assert inv["subtotal_cents"] == 207125, "121500 base + 80000 equipment + 5625 standby"
    # Tier basis 0 + 207125 >= 100000 -> 2%: round_half_up(4142.5) = 4143.
    assert inv["volume_discount_cents"] == 4143


def test_fuel_surcharge_on_undiscounted_excluding_standby(api):
    """PRD §3.8: "Sixth, `fuel_surcharge_cents` is 7 percent of the sum of base
    and equipment charges — the pre-discount basis, and never including standby
    — rounded half up to a whole cent, even though the surcharge is added to
    the total after the discount is subtracted."

    Design: Difficulty/combinatorial_formula/invoice_evaluation_order
    """
    bundle = setup_delivered_superload_tx(with_delay=True)
    inv = generate_invoice(bundle["job"]["id"], "bc-1")

    assert inv["base_charges_cents"] == 121500, "3 assignments x 4.5h x 9000"
    assert inv["equipment_charges_cents"] == 80000, "15000 pole + 40000 police + 25000 survey"
    assert inv["standby_total_cents"] == 5625, "0.25h x 7500 x 3 positions"
    # 7% on the undiscounted base+equipment 201500, standby excluded.
    assert inv["fuel_surcharge_cents"] == 14105
    assert inv["total_cents"] == 217087, "207125 - 4143 + 14105"
    assert_invoice_invariants(inv)


def test_volume_discount_top_tier_full_composition(api):
    """PRD §3.8: "when the basis is at least 500,000 cents the discount rate is
    5 percent"
    PRD §3.3: "The job's `quoted_cents` is the sum of the base and equipment
    estimates across all legs, an integer number of cents with no further
    rounding."

    Design: Corner/calculations/volume_discount_top_tier_full_composition
    """
    carrier = register_carrier(10_000_000, "Top Tier Co")
    ef1 = register_escort(("TX",), "EF1", True, 192)
    ef2 = register_escort(("TX",), "EF2", True, 192)
    er1 = register_escort(("TX",), "ER1")
    ef3 = register_escort(("OK",), "EF3", True, 192)
    ef4 = register_escort(("OK",), "EF4", True, 192)
    er2 = register_escort(("OK",), "ER2")

    set_clock("2026-08-05T00:00:00Z")
    legs = [
        leg_spec("TX", 0, 120, "2026-08-10T09:00:00Z", "2026-08-10T13:00:00Z", 200),
        leg_spec("OK", 1, 100, "2026-08-10T13:30:00Z", "2026-08-10T15:30:00Z", 200),
    ]
    job = create_tx_job(
        carrier,
        load_description="Superload two-state",
        width_inches=195,
        height_inches=180,
        gross_weight_lbs=250000,
        window_start_at="2026-08-10T09:00:00Z",
        window_end_at="2026-08-10T15:30:00Z",
        legs=legs,
    )
    leg_tx, leg_ok = list_job_legs(job["id"])
    quoted = quote_job(job["id"])
    # TX: 2.5h x 3 x 9000 = 67500 + 80000; OK: 2.0h x 3 x 9000 = 54000 + 80000.
    assert quoted["quoted_cents"] == 281500
    accept_quote(job["id"], carrier)

    for leg, number in ((leg_tx, "TX-P-31"), (leg_ok, "OK-P-31")):
        permit = add_permit(leg["id"], permit_number=number)
        issue_permit(permit["id"])
    for leg in (leg_tx, leg_ok):
        survey = request_survey(leg["id"])
        submit_survey(survey["id"], 190)
        decide_survey(survey["id"], leg["id"], "ACCEPTED")
    confirm_police(leg_tx["id"])
    confirm_police(leg_ok["id"])

    assignments = []
    for leg, esc, pos in (
        (leg_tx, ef1, "FRONT"), (leg_tx, ef2, "FRONT"), (leg_tx, er1, "REAR"),
        (leg_ok, ef3, "FRONT"), (leg_ok, ef4, "FRONT"), (leg_ok, er2, "REAR"),
    ):
        asg = offer_assignment(leg["id"], pos, esc["id"])
        assignments.append(accept_assignment(asg, esc["id"]))

    validate_success(api.schedule_job(job["id"], DISPATCHER))
    set_clock("2026-08-10T09:00:00Z")
    depart_job(job["id"])
    set_clock("2026-08-10T14:30:00Z")
    for asg in assignments:
        check_in(asg["id"], asg["escort_id"])
    set_clock("2026-08-10T16:00:00Z")
    deliver_job(job["id"])

    inv = generate_invoice(job["id"], "bc-1")
    assert inv["base_charges_cents"] == 378000, "6 assignments x 7.0h x 9000"
    assert inv["equipment_charges_cents"] == 160000, "80000 x 2 legs"
    assert inv["standby_total_cents"] == 0
    assert inv["subtotal_cents"] == 538000
    assert inv["volume_discount_cents"] == 26900, "tier basis 538000 >= 500000 -> 5%"
    assert inv["fuel_surcharge_cents"] == 37660, "round_half_up(538000 x 0.07)"
    assert inv["total_cents"] == 548760
    assert_invoice_invariants(inv)


def test_invoice_state_gates_rejected(api):
    """PRD §3.8: "The owning `CarrierRep` disputes a `FINALIZED` invoice — any
    other status is rejected with `ERR_INVOICE_INVALID_STATE`"
    PRD §3.8: "a `BillingClerk` finalizes an invoice in `DRAFT` — any other
    status is rejected with `ERR_INVOICE_INVALID_STATE`"

    Design: Corner/state_machines/invoice_state_gates_rejected
    """
    bundle = setup_delivered_rear_job(deliver_at="2026-08-10T10:00:00Z", escort_name="Rider IV")
    inv = generate_invoice(bundle["job"]["id"], "bc-1")

    resp = api.dispute_invoice(
        inv["id"],
        {"dispute_reason": "too early"},
        make_carrier_rep_headers(bundle["carrier"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVOICE_INVALID_STATE)

    finalized = finalize_invoice(inv["id"], "bc-2")
    assert finalized["invoice_status"] == "FINALIZED"

    resp2 = api.finalize_invoice(inv["id"], make_billing_clerk_headers("bc-2"))
    validate_error(resp2, ApiErrorId.ERR_INVOICE_INVALID_STATE)
    assert get_invoice(inv["id"])["finalized_at"] == finalized["finalized_at"]


def test_sod_invoice_finalize_by_generator_forbidden(api):
    """PRD §3.8: "Finalization is the checker to the generator's maker: a
    `BillingClerk` finalizes an invoice in `DRAFT` — any other status is
    rejected with `ERR_INVOICE_INVALID_STATE` — but the finalizer's `X-User-ID`
    must differ from the invoice's `generated_by_user_id`, else the request is
    rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/sod_invoice_finalize_by_generator_forbidden
    """
    bundle = setup_delivered_rear_job(deliver_at="2026-08-10T10:00:00Z", escort_name="Rider SI")
    inv = generate_invoice(bundle["job"]["id"], "bc-1")

    resp = api.finalize_invoice(inv["id"], make_billing_clerk_headers("bc-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    finalized = finalize_invoice(inv["id"], "bc-2")
    assert finalized["invoice_status"] == "FINALIZED"
    assert finalized["total_cents"] == 38520, "base 36000 + fuel 2520"


def test_payment_amount_mismatch_then_exact(api):
    """PRD §3.8: "A `FinanceManager` records payment of a `FINALIZED` invoice —
    any other status is rejected with `ERR_INVOICE_INVALID_STATE` — and the
    paid `amount_cents` must equal the invoice's `total_cents` exactly; any
    other amount is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`."

    Design: Corner/validations/payment_amount_mismatch_then_exact
    """
    bundle = setup_delivered_rear_job(deliver_at="2026-08-10T10:00:00Z", escort_name="Rider Pay")
    inv = generate_invoice(bundle["job"]["id"], "bc-1")
    finalize_invoice(inv["id"], "bc-2")

    resp = api.record_payment(inv["id"], {"amount_cents": 38519}, TEST_USERS["finance_manager_headers"])
    validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)
    assert get_invoice(inv["id"])["invoice_status"] == "FINALIZED"

    paid = record_payment(inv["id"], 38520)
    assert paid["invoice_status"] == "PAID"
    assert paid["paid_at"] is not None
    assert get_carrier(bundle["carrier"]["id"])["ytd_billed_cents"] == 38520


def test_adjustment_bounds_and_revision_loop(api):
    """PRD §3.8: "The delta accumulates onto the running
    `adjustment_delta_cents` — the only way that field ever changes — the
    composition recomputes `total_cents`, and the resulting total must remain
    at least zero; an adjustment that would drive it below zero is rejected
    with `ERR_ADJUSTMENT_EXCEEDS_TOTAL`. A successful adjustment returns the
    invoice to `FINALIZED` and refreshes `finalized_at`, and the
    finalize–dispute–adjust loop may repeat"

    Design: Corner/validations/adjustment_bounds_and_revision_loop
    """
    bundle = setup_delivered_rear_job(deliver_at="2026-08-10T10:00:00Z", escort_name="Rider A")
    inv = generate_invoice(bundle["job"]["id"], "bc-1")
    finalize_invoice(inv["id"], "bc-2")
    dispute_invoice(inv["id"], bundle["carrier"], "standby overbilled")

    resp = api.adjust_invoice(
        inv["id"],
        {"adjustment_delta_cents": -99999999, "adjustment_note": "too much"},
        make_billing_clerk_headers("bc-2"),
    )
    validate_error(resp, ApiErrorId.ERR_ADJUSTMENT_EXCEEDS_TOTAL)
    assert get_invoice(inv["id"])["invoice_status"] == "DISPUTED"

    adjusted = adjust_invoice(inv["id"], -1000, "goodwill", "bc-2")
    assert adjusted["invoice_status"] == "FINALIZED"
    assert adjusted["adjustment_delta_cents"] == -1000
    assert adjusted["total_cents"] == 37520, "38520 - 1000"
    assert_invoice_invariants(adjusted)


def test_invoice_generate_state_and_empty_gates(api):
    """PRD §3.8: "A `BillingClerk` generates an invoice for a job in
    `DELIVERED` or `CANCELLED` status — any other status is rejected with
    `ERR_JOB_INVALID_STATE`"
    PRD §3.8: "a `CANCELLED` job whose `cancel_fee_cents` is 0 and which has no
    `COMPLETED` assignments has nothing to bill, so generation is rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/state_machines/invoice_generate_state_and_empty_gates
    """
    carrier = register_carrier(10_000_000, "Gen Gate Co")
    set_clock("2026-08-05T00:00:00Z")
    job_a = create_tx_job(carrier, load_description="A")
    quote_job(job_a["id"])
    accept_quote(job_a["id"], carrier)

    resp = api.create_invoice(job_a["id"], make_billing_clerk_headers("bc-1"))
    validate_error(resp, ApiErrorId.ERR_JOB_INVALID_STATE)

    job_b = create_tx_job(
        carrier,
        load_description="B",
        window_start_at="2026-08-11T09:00:00Z",
        window_end_at="2026-08-11T13:00:00Z",
        planned_entry_at="2026-08-11T09:00:00Z",
        planned_exit_at="2026-08-11T13:00:00Z",
    )
    quote_job(job_b["id"])
    validate_success(api.cancel_job(job_b["id"], make_carrier_rep_headers(carrier["id"])))
    assert get_job(job_b["id"])["cancel_fee_cents"] == 0

    resp2 = api.create_invoice(job_b["id"], make_billing_clerk_headers("bc-1"))
    validate_error(resp2, ApiErrorId.ERR_INVALID_REQUEST)
