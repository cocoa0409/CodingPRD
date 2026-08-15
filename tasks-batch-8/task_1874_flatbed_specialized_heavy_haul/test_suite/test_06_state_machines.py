"""State-machine claims: invalid transitions, terminal lockdowns, cancel and
arrive cascades, securement terminal states, fine dispute guards, invoice
pay/void rules, suspension gating, and hold release (PRD §3.1-§3.9)."""
from test_helpers import (
    BILLING,
    DISPATCHER,
    DRIVER,
    SAFETY,
    ApiErrorId,
    book_escort,
    create_customer,
    create_fine_payload,
    create_load_for_customer,
    create_load_payload,
    create_permit_for_load,
    file_and_approve_securement,
    issue_invoice,
    make_shipper_headers,
    plan_load,
    record_scale_violation,
    report_and_resolve_fine,
    resolve_fine_payload,
    schedule_both_cranes,
    schedule_crane,
    set_clock,
    setup_ca_load_in_transit,
    setup_standard_load_cleared,
    setup_standard_load_delivered,
    setup_standard_load_in_transit,
    survey_load,
    validate_error,
    validate_success,
)


def test_cancel_in_transit_rejected(api):
    """PRD §3.7: "A load in `DRAFT`, `PLANNED`, `SURVEYED`, `CLEARED`, or
    `ON_HOLD` may be cancelled; one in `IN_TRANSIT`, `DELIVERED`, or
    `CANCELLED` may not, and the attempt is rejected with
    `ERR_LOAD_NOT_CANCELLABLE` (HTTP 409)."

    Design: Corner/state_machines/cancel_in_transit_rejected
    """
    customer, load = setup_standard_load_in_transit(
        company_name="Transit Cancel Co"
    )
    err = validate_error(
        api.cancel_load(load["id"], make_shipper_headers(customer["id"])),
        ApiErrorId.ERR_LOAD_NOT_CANCELLABLE,
    )
    assert err["error_id"] == "ERR_LOAD_NOT_CANCELLABLE"
    # The rejected cancel leaves the load untouched.
    current = validate_success(api.get_load(load["id"], DISPATCHER), 200)
    assert current["status"] == "IN_TRANSIT"


def test_delivered_terminal_lockdown(api):
    """PRD §3.2: "Planning is allowed while the load is `DRAFT`, `PLANNED`, or
    `SURVEYED` — the latter two being re-plans — and any other state is
    rejected with `ERR_LOAD_INVALID_STATE` (HTTP 409)."
    PRD §3.7: "A load in `DRAFT`, `PLANNED`, `SURVEYED`, `CLEARED`, or
    `ON_HOLD` may be cancelled; one in `IN_TRANSIT`, `DELIVERED`, or
    `CANCELLED` may not, and the attempt is rejected with
    `ERR_LOAD_NOT_CANCELLABLE` (HTTP 409)."

    Design: Corner/state_machines/delivered_terminal_lockdown
    """
    customer, load_x = setup_standard_load_delivered(company_name="Terminal Co")
    shipper = make_shipper_headers(customer["id"])
    plan_payload = {
        "trailer_type": "FLATBED", "trailer_axle_count": 2,
        "driver_name": "W. Eve", "driver_oversize_endorsed": False,
    }
    # DELIVERED is terminal.
    assert validate_error(
        api.plan_load(load_x["id"], plan_payload, DISPATCHER),
        ApiErrorId.ERR_LOAD_INVALID_STATE,
    )["error_id"] == "ERR_LOAD_INVALID_STATE"
    assert validate_error(
        api.depart_load(load_x["id"], DRIVER),
        ApiErrorId.ERR_LOAD_INVALID_STATE,
    )["error_id"] == "ERR_LOAD_INVALID_STATE"
    assert validate_error(
        api.cancel_load(load_x["id"], shipper),
        ApiErrorId.ERR_LOAD_NOT_CANCELLABLE,
    )["error_id"] == "ERR_LOAD_NOT_CANCELLABLE"
    # CANCELLED is terminal too.
    load_y = create_load_for_customer(customer["id"], cargo_description="Y")
    validate_success(api.cancel_load(load_y["id"], shipper), 200)
    assert validate_error(
        api.plan_load(load_y["id"], plan_payload, DISPATCHER),
        ApiErrorId.ERR_LOAD_INVALID_STATE,
    )["error_id"] == "ERR_LOAD_INVALID_STATE"


def test_load_cancel_cascades_children(api):
    """PRD §3.7: "Cancellation cascades: every non-terminal permit becomes
    `WITHDRAWN`, every `CONFIRMED` escort booking and every `SCHEDULED` crane
    appointment becomes `CANCELLED`, the load becomes `CANCELLED`, and the
    load's `version` increments."
    PRD §3.5: "cancelling the load withdraws every permit not yet in a terminal
    state — any of `DRAFT`, `FILED`, `GRANTED`, `DENIED`, or `REVOKED` becomes
    `WITHDRAWN`."

    Design: Corner/state_machines/load_cancel_cascades_children
    """
    customer = create_customer("Cascade Cancel Co", 50_000_000)
    load = create_load_for_customer(
        customer["id"],
        cargo_description="Wide tank", gross_weight_lbs=40000,
        width_in=150, height_in=100, length_in=400,
        origin="X", destination="Y",
    )
    plan_load(
        load["id"], trailer_type="FLATBED", trailer_axle_count=2,
        driver_name="X. Abe", driver_oversize_endorsed=True,
    )
    surveyed = survey_load(
        load["id"], route_miles=100, states_crossed=["CA"],
        min_bridge_clearance_in=200, max_bridge_weight_lbs=80000,
    )
    create_permit_for_load(
        load["id"], "CA", "OVERSIZE",
        expected_load_version=surveyed["version"],
    )
    book_escort(load["id"], provider_name="Cascade Pilots", position="REAR")
    schedule_crane(load["id"], site="ORIGIN", crane_id="CRANE-A")
    cancelled = validate_success(
        api.cancel_load(load["id"], make_shipper_headers(customer["id"])), 200
    )
    assert cancelled["status"] == "CANCELLED"
    permits = validate_success(api.list_permits(load["id"], DISPATCHER), 200)
    assert permits[0]["status"] == "WITHDRAWN"
    escorts = validate_success(
        api.list_escort_bookings(load["id"], DISPATCHER), 200
    )
    assert escorts[0]["status"] == "CANCELLED"
    cranes = validate_success(
        api.list_crane_appointments(load["id"], DISPATCHER), 200
    )
    assert cranes[0]["status"] == "CANCELLED"


def test_securement_reject_is_terminal(api):
    """PRD §3.4: "Approving a plan that is no longer `SUBMITTED` is
    `ERR_INVALID_STATE`. A successful approval moves the plan to `APPROVED` and
    re-evaluates the load's readiness gate (§3.7), which may advance a
    `SURVEYED` load to `CLEARED`. Rejection moves the plan to `REJECTED`; both
    outcomes are terminal for that plan, and a rejected plan is replaced by
    filing a new one, not by reopening the old."

    Design: Corner/state_machines/securement_reject_is_terminal
    """
    customer = create_customer("Reject Co", 50_000_000)
    load = create_load_for_customer(customer["id"], cargo_description="Skids")
    plan_load(
        load["id"], trailer_type="FLATBED", trailer_axle_count=2,
        driver_name="Y. Kay", driver_oversize_endorsed=False,
    )
    resp = api.create_securement_plan(
        load["id"],
        {
            "method": "CHAINS", "tiedown_count": 4,
            "wll_per_tiedown_lbs": 6000,
        },
        DISPATCHER,
    )
    plan = validate_success(resp, 201)
    rejected = validate_success(
        api.reject_securement_plan(plan["id"], SAFETY), 200
    )
    assert rejected["status"] == "REJECTED"
    err = validate_error(
        api.approve_securement_plan(plan["id"], SAFETY),
        ApiErrorId.ERR_INVALID_STATE,
    )
    assert err["error_id"] == "ERR_INVALID_STATE"


def test_fine_dispute_state_and_liability_rules(api):
    """PRD §3.9: "A `Shipper` may dispute a fine that is still `PENDING` and
    customer-liable — disputing a non-pending fine or a carrier-liable one
    (those are absorbed, not disputed) is rejected with
    `ERR_FINE_NOT_DISPUTABLE` (HTTP 409) — and only for loads they own, with
    `ERR_NOT_OWN_RESOURCE` guarding cross-customer disputes."
    PRD §3.9: "Manual fines are born `PENDING` with `liable_party` defaulted to
    `CARRIER`, on the principle that breakage and permit violations are the
    carrier's problem until adjudicated; the system-created `OVERWEIGHT` fine
    is the mirror image, born customer-liable."

    Design: Corner/state_machines/fine_dispute_state_and_liability_rules
    """
    customer, load = setup_standard_load_cleared(company_name="Dispute Co")
    shipper = make_shipper_headers(customer["id"])
    resp = api.create_fine(
        load["id"],
        create_fine_payload(
            kind="DAMAGE", amount_cents=30000, description="Tarp torn"
        ),
        DRIVER,
    )
    fine = validate_success(resp, 201)
    # Kind-based liability default.
    assert fine["liable_party"] == "CARRIER"
    assert fine["status"] == "PENDING"
    # Carrier-liable fines are absorbed, not disputed.
    err1 = validate_error(
        api.dispute_fine(fine["id"], shipper),
        ApiErrorId.ERR_FINE_NOT_DISPUTABLE,
    )
    assert err1["error_id"] == "ERR_FINE_NOT_DISPUTABLE"
    resolved = validate_success(
        api.resolve_fine(
            fine["id"], resolve_fine_payload("CARRIER_LIABLE"), SAFETY
        ),
        200,
    )
    assert resolved["status"] == "RESOLVED_CARRIER_LIABLE"
    # Non-PENDING this time.
    err2 = validate_error(
        api.dispute_fine(fine["id"], shipper),
        ApiErrorId.ERR_FINE_NOT_DISPUTABLE,
    )
    assert err2["error_id"] == "ERR_FINE_NOT_DISPUTABLE"


def test_invoice_pay_void_after_terminal_rejected(api):
    """PRD §3.9: "Paying an invoice requires the caller's `amount_cents` to
    equal the invoice's `total_cents` exactly — a mismatch is
    `ERR_INVALID_REQUEST` — and requires the invoice to be `ISSUED`, otherwise
    `ERR_INVOICE_NOT_ISSUED` (HTTP 409). Payment moves the invoice to the
    terminal `PAID` state and credits `outstanding_balance_cents` down by
    `total_cents`. Voiding, also restricted to `ISSUED` invoices, moves it to
    the terminal `VOID` state, credits the same amount off the outstanding
    balance, and un-sweeps the invoice's fines from `APPLIED` back to
    `PENDING` so that a replacement invoice can legitimately include them."

    Design: Corner/state_machines/invoice_pay_void_after_terminal_rejected
    """
    customer, load = setup_standard_load_delivered(company_name="Pay Twice Co")
    invoice = issue_invoice(load["id"])
    # linehaul 35000 + fuel 2800
    assert invoice["total_cents"] == 37800
    # Partial payment not accepted.
    err1 = validate_error(
        api.pay_invoice(invoice["id"], {"amount_cents": 1}, BILLING),
        ApiErrorId.ERR_INVALID_REQUEST,
    )
    assert err1["error_id"] == "ERR_INVALID_REQUEST"
    paid = validate_success(
        api.pay_invoice(invoice["id"], {"amount_cents": 37800}, BILLING), 200
    )
    assert paid["status"] == "PAID"
    # Repeat pay rejected — no double debit.
    err2 = validate_error(
        api.pay_invoice(invoice["id"], {"amount_cents": 37800}, BILLING),
        ApiErrorId.ERR_INVOICE_NOT_ISSUED,
    )
    assert err2["error_id"] == "ERR_INVOICE_NOT_ISSUED"
    # Void of a PAID invoice rejected.
    err3 = validate_error(
        api.void_invoice(invoice["id"], BILLING),
        ApiErrorId.ERR_INVOICE_NOT_ISSUED,
    )
    assert err3["error_id"] == "ERR_INVOICE_NOT_ISSUED"
    customer_now = validate_success(
        api.get_customer(customer["id"], BILLING), 200
    )
    # Exactly one debit happened across the whole sequence.
    assert customer_now["outstanding_balance_cents"] == 0


def test_arrive_completes_children(api):
    """PRD §3.7: "Arrival is the counterpart of departure: the `Driver` marks
    an `IN_TRANSIT` load delivered, moving it to the terminal `DELIVERED`
    state, completing every `CONFIRMED` escort booking and every `SCHEDULED`
    crane appointment on the load, and incrementing the load's `version`."

    Design: Corner/state_machines/arrive_completes_children
    """
    customer = create_customer("Arrive Co", 10_000_000)
    load = create_load_for_customer(customer["id"], cargo_description="Bales")
    plan_load(
        load["id"], trailer_type="FLATBED", trailer_axle_count=2,
        driver_name="B. Lu", driver_oversize_endorsed=False,
    )
    survey_load(
        load["id"], route_miles=100, states_crossed=["OR"],
        min_bridge_clearance_in=200, max_bridge_weight_lbs=80000,
    )
    # Extra (not required) escort booking: STANDARD loads require none.
    book_escort(
        load["id"], provider_name="Extra Eyes", position="REAR",
        rate_per_hour_cents=9000,
    )
    schedule_both_cranes(load["id"])
    file_and_approve_securement(
        load["id"], method="STRAPS", tiedown_count=2, wll_per_tiedown_lbs=10000
    )
    set_clock("2026-08-12T10:00:00Z")
    validate_success(api.depart_load(load["id"], DRIVER), 200)
    arrived = validate_success(api.arrive_load(load["id"], DRIVER), 200)
    assert arrived["status"] == "DELIVERED"
    escorts = validate_success(
        api.list_escort_bookings(load["id"], DISPATCHER), 200
    )
    assert escorts[0]["status"] == "COMPLETED"
    cranes = validate_success(
        api.list_crane_appointments(load["id"], DISPATCHER), 200
    )
    assert all(c["status"] == "COMPLETED" for c in cranes)
    assert len(cranes) == 2


def test_suspended_customer_gates_and_reinstate(api):
    """PRD §3.1: "When an invoice is issued and the resulting
    `outstanding_balance_cents` is strictly greater than the customer's
    `credit_limit_cents`, the customer flips automatically to `SUSPENDED`;
    equality leaves the customer `ACTIVE`. A `SUSPENDED` customer cannot create
    loads — the attempt is rejected with `ERR_CUSTOMER_SUSPENDED` (HTTP 409).
    Reinstatement is performed by a `BillingClerk` and moves `SUSPENDED` back
    to `ACTIVE`, but only when the customer is in fact `SUSPENDED` (otherwise
    `ERR_INVALID_STATE`, HTTP 409) and only when the outstanding balance is at
    or below the credit limit — if it still exceeds the limit, the
    reinstatement is rejected with `ERR_REINSTATE_NOT_ALLOWED` (HTTP 409)."

    Design: Corner/state_machines/suspended_customer_gates_and_reinstate
    """
    customer = create_customer("Thin Credit Co", 50_000)
    load = create_load_for_customer(customer["id"], cargo_description="Sacks")
    plan_load(
        load["id"], trailer_type="FLATBED", trailer_axle_count=2,
        driver_name="C. Mo", driver_oversize_endorsed=False,
    )
    survey_load(
        load["id"], route_miles=100, states_crossed=["OR"],
        min_bridge_clearance_in=200, max_bridge_weight_lbs=80000,
    )
    schedule_both_cranes(load["id"])
    file_and_approve_securement(
        load["id"], method="STRAPS", tiedown_count=2, wll_per_tiedown_lbs=10000
    )
    set_clock("2026-08-12T10:00:00Z")
    # Provisional estimate 37800 <= 50000: depart passes.
    validate_success(api.depart_load(load["id"], DRIVER), 200)
    report_and_resolve_fine(
        load["id"], kind="DAMAGE", amount_cents=100000,
        resolution="CUSTOMER_LIABLE", description="Deck gouged",
    )
    validate_success(api.arrive_load(load["id"], DRIVER), 200)
    invoice = issue_invoice(load["id"])
    # subtotal 135000 = 35000 + 100000; fuel 8% = 10800.
    assert invoice["total_cents"] == 145800
    mid = validate_success(api.get_customer(customer["id"], BILLING), 200)
    # Auto-suspension: 145800 > 50000.
    assert mid["status"] == "SUSPENDED"
    assert mid["outstanding_balance_cents"] == 145800
    # Load creation blocked while suspended.
    err1 = validate_error(
        api.create_load(
            create_load_payload(cargo_description="New job"),
            make_shipper_headers(customer["id"]),
        ),
        ApiErrorId.ERR_CUSTOMER_SUSPENDED,
    )
    assert err1["error_id"] == "ERR_CUSTOMER_SUSPENDED"
    # Reinstate refused while outstanding still exceeds the limit.
    err2 = validate_error(
        api.reinstate_customer(customer["id"], BILLING),
        ApiErrorId.ERR_REINSTATE_NOT_ALLOWED,
    )
    assert err2["error_id"] == "ERR_REINSTATE_NOT_ALLOWED"
    # Void returns outstanding to 0, then reinstate succeeds.
    validate_success(api.void_invoice(invoice["id"], BILLING), 200)
    reinstated = validate_success(
        api.reinstate_customer(customer["id"], BILLING), 200
    )
    assert reinstated["status"] == "ACTIVE"


def test_release_hold_without_granted_permits_fails(api):
    """PRD §3.8: "Only then may a `SafetyManager` release the hold, and only
    when every required `(state_code, permit_type)` pair again has a `GRANTED`
    permit; a shortfall is rejected with `ERR_PERMIT_REQUIREMENT_UNMET` (HTTP
    409), and a release attempted on a load not `ON_HOLD` is
    `ERR_LOAD_INVALID_STATE`."

    Design: Corner/state_machines/release_hold_without_granted_permits_fails
    """
    ctx = setup_ca_load_in_transit(company_name="Hold Co")
    load_id = ctx["load"]["id"]
    # Scale violation holds the load and revokes the OVERWEIGHT permit.
    record_scale_violation(load_id, measured_gross_lbs=100000)
    err = validate_error(
        api.release_hold_load(load_id, SAFETY),
        ApiErrorId.ERR_PERMIT_REQUIREMENT_UNMET,
    )
    assert err["error_id"] == "ERR_PERMIT_REQUIREMENT_UNMET"
    # The failed release leaves the load in the hold.
    current = validate_success(api.get_load(load_id, DISPATCHER), 200)
    assert current["status"] == "ON_HOLD"
