"""Validation claims: auth headers, request-body sanity, tarping conditional,
permit-type matching, duplicate permits, manual overweight fines, trailer
selection ordering, endorsement, securement WLL, travel windows, curfew,
credit at depart, and the one-invoice rule (PRD §2.1, §3.2-§3.9)."""
from test_helpers import (
    BILLING,
    DISPATCHER,
    DRIVER,
    PERMIT_CLERK,
    SAFETY,
    ApiErrorId,
    book_escort,
    create_customer,
    create_crane_appointment_payload,
    create_filed_and_granted_permit,
    create_fine_payload,
    create_load_for_customer,
    create_permit_for_load,
    file_and_approve_securement,
    get_load_version,
    issue_invoice,
    plan_load,
    schedule_both_cranes,
    set_clock,
    setup_ca_oversize_overweight_cleared,
    setup_standard_load_cleared,
    setup_standard_load_delivered,
    survey_load,
    validate_error,
    validate_success,
)


def test_request_missing_header_returns_unauthenticated(api):
    """PRD §2.1: "All interactions with the API are authenticated through two
    mandatory HTTP headers: `X-User-ID`, identifying the acting user, and
    `X-User-Role`, declaring the operational capacity in which they act. A
    request missing either header, or carrying an `X-User-Role` value that is
    not one of the declared roles, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/request_missing_header_returns_unauthenticated
    """
    customer = create_customer("Header Co", 500000)
    # The test client strips both auth headers from the wire call.
    err = validate_error(
        api.get_customer(customer["id"], headers={"Content-Type": "application/json"}),
        ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    )
    assert err["error_id"] == "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"


def test_invalid_enum_and_range_rejected(api):
    """PRD §3.2: "Each of the weight and dimension fields must be greater than
    zero; violations of required-field presence, enum membership, integer
    floors, or datetime ordering on any endpoint are rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.6: "The `Dispatcher` schedules an appointment with a `site` of
    `ORIGIN` or `DESTINATION`, a `crane_id`, and a `window_start` /
    `window_end` pair with the end strictly after the start; the load must be
    `PLANNED`, `SURVEYED`, `CLEARED`, or `ON_HOLD`."

    Design: Corner/validations/invalid_enum_and_range_rejected
    """
    customer = create_customer("Sanity Co", 500000)
    load = create_load_for_customer(customer["id"], cargo_description="Crates")
    # trailer_type not in the declared catalog enum.
    err1 = validate_error(
        api.plan_load(
            load["id"],
            {
                "trailer_type": "MAGIC_CARPET", "trailer_axle_count": 2,
                "driver_name": "I. Jo", "driver_oversize_endorsed": False,
            },
            DISPATCHER,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
    )
    assert err1["error_id"] == "ERR_INVALID_REQUEST"
    # Plan legally so the load-state gate passes, isolating datetime ordering.
    plan_load(load["id"])
    err2 = validate_error(
        api.create_crane_appointment(
            load["id"],
            create_crane_appointment_payload(
                site="ORIGIN", crane_id="CRANE-A",
                window_start="2026-08-12T08:00:00Z",
                window_end="2026-08-12T06:00:00Z",
            ),
            DISPATCHER,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
    )
    assert err2["error_id"] == "ERR_INVALID_REQUEST"


def test_tarping_conditional_validation(api):
    """PRD §3.4: "Approval evaluates two conditions: the aggregate working load
    limit must be at least half the load's gross weight, where an odd pound
    rounds up — a shortfall is rejected with `ERR_SECUREMENT_WLL_INSUFFICIENT`
    (HTTP 422) — and when the load's `cargo_requires_tarp` flag is set, the
    method must be `CHAINS_AND_TARPS`, or approval is rejected with
    `ERR_TARPING_REQUIRED` (HTTP 422)."

    Design: Corner/validations/tarping_conditional_validation
    """
    customer = create_customer("Tarp Co", 50_000_000)
    load = create_load_for_customer(
        customer["id"], cargo_description="Lumber packs",
        cargo_requires_tarp=True,
    )
    plan_load(
        load["id"], trailer_type="FLATBED", trailer_axle_count=2,
        driver_name="J. Vu", driver_oversize_endorsed=False,
    )
    resp = api.create_securement_plan(
        load["id"],
        {"method": "CHAINS", "tiedown_count": 2, "wll_per_tiedown_lbs": 10000},
        DISPATCHER,
    )
    plan1 = validate_success(resp, 201)
    # Flag true + method CHAINS -> tarping rule fires.
    err = validate_error(
        api.approve_securement_plan(plan1["id"], SAFETY),
        ApiErrorId.ERR_TARPING_REQUIRED,
    )
    assert err["error_id"] == "ERR_TARPING_REQUIRED"
    # Same load, compliant method -> the conditional rule passes.
    resp2 = api.create_securement_plan(
        load["id"],
        {
            "method": "CHAINS_AND_TARPS", "tiedown_count": 2,
            "wll_per_tiedown_lbs": 10000,
        },
        DISPATCHER,
    )
    plan2 = validate_success(resp2, 201)
    approved = validate_success(
        api.approve_securement_plan(plan2["id"], SAFETY), 200
    )
    assert approved["status"] == "APPROVED"


def test_permit_type_not_required_rejected(api):
    """PRD §3.5: "Every state the route crosses requires its own permit, and
    the permit class must match the load's computed flags: a superload requires
    a `SUPERLOAD` permit; otherwise an oversize load requires an `OVERSIZE`
    permit if and only if `is_oversize` holds, and an overweight load requires
    an `OVERWEIGHT` permit if and only if `is_overweight` holds. A `STANDARD`
    load — neither oversize nor overweight — needs no permits at all."
    PRD §3.5: "Creating a permit whose type does not match the load's flags is
    rejected with `ERR_PERMIT_TYPE_NOT_REQUIRED` (HTTP 409)"

    Design: Corner/validations/permit_type_not_required_rejected
    """
    customer = create_customer("Permit Match Co", 50_000_000)
    load = create_load_for_customer(customer["id"], cargo_description="Crates")
    plan_load(
        load["id"], trailer_type="FLATBED", trailer_axle_count=2,
        driver_name="K. Han", driver_oversize_endorsed=False,
    )
    surveyed = survey_load(
        load["id"], route_miles=100, states_crossed=["OR"],
        min_bridge_clearance_in=200, max_bridge_weight_lbs=80000,
    )
    version = surveyed["version"]
    # is_overweight false on a 40000-lb STANDARD load.
    err1 = validate_error(
        api.create_permit(
            load["id"],
            {
                "state_code": "OR", "permit_type": "OVERWEIGHT",
                "expected_load_version": version,
            },
            PERMIT_CLERK,
        ),
        ApiErrorId.ERR_PERMIT_TYPE_NOT_REQUIRED,
    )
    assert err1["error_id"] == "ERR_PERMIT_TYPE_NOT_REQUIRED"
    # is_superload false as well.
    err2 = validate_error(
        api.create_permit(
            load["id"],
            {
                "state_code": "OR", "permit_type": "SUPERLOAD",
                "expected_load_version": version,
            },
            PERMIT_CLERK,
        ),
        ApiErrorId.ERR_PERMIT_TYPE_NOT_REQUIRED,
    )
    assert err2["error_id"] == "ERR_PERMIT_TYPE_NOT_REQUIRED"
    # Both rejected before any permit row is created; version unchanged.
    assert get_load_version(load["id"]) == version


def test_duplicate_permit_rejected(api):
    """PRD §3.5: "creating a second permit for the same `(state_code,
    permit_type)` pair while one already exists in `DRAFT`, `FILED`, or
    `GRANTED` status is rejected with `ERR_DUPLICATE_PERMIT` (HTTP 409)."

    Design: Corner/validations/duplicate_permit_rejected
    """
    customer = create_customer("Dupe Co", 50_000_000)
    load = create_load_for_customer(
        customer["id"],
        cargo_description="Wide pallet", gross_weight_lbs=40000,
        width_in=150, height_in=100, length_in=400,
        origin="X", destination="Y",
    )
    plan_load(
        load["id"], trailer_type="FLATBED", trailer_axle_count=2,
        driver_name="L. Qi", driver_oversize_endorsed=True,
    )
    surveyed = survey_load(
        load["id"], route_miles=100, states_crossed=["CA"],
        min_bridge_clearance_in=200, max_bridge_weight_lbs=80000,
    )
    create_permit_for_load(
        load["id"], "CA", "OVERSIZE",
        expected_load_version=surveyed["version"],
    )
    err = validate_error(
        api.create_permit(
            load["id"],
            {
                "state_code": "CA", "permit_type": "OVERSIZE",
                "expected_load_version": get_load_version(load["id"]),
            },
            PERMIT_CLERK,
        ),
        ApiErrorId.ERR_DUPLICATE_PERMIT,
    )
    assert err["error_id"] == "ERR_DUPLICATE_PERMIT"


def test_overweight_fine_manual_rejected(api):
    """PRD §3.9: "Manually reporting an `OVERWEIGHT` fine is rejected with
    `ERR_FINE_KIND_NOT_MANUAL` (HTTP 409) — that class exists only through the
    scale cascade."

    Design: Corner/validations/overweight_fine_manual_rejected
    """
    _, load = setup_standard_load_cleared(company_name="Fine Kind Co")
    err = validate_error(
        api.create_fine(
            load["id"],
            create_fine_payload(
                kind="OVERWEIGHT", amount_cents=5000,
                description="manual entry attempt",
            ),
            SAFETY,
        ),
        ApiErrorId.ERR_FINE_KIND_NOT_MANUAL,
    )
    assert err["error_id"] == "ERR_FINE_KIND_NOT_MANUAL"


def test_trailer_capacity_checked_before_axles(api):
    """PRD §3.2: "Three adequacy checks run at plan time, in a fixed order so
    the first failure is the one reported:"
    PRD §3.2: "1. **Capacity first.** The chosen trailer's catalog payload
    limit must be greater than or equal to `gross_weight_lbs` — a payload
    exactly equal to the limit passes — or the plan is rejected with
    `ERR_TRAILER_CAPACITY_EXCEEDED` (HTTP 422)."
    PRD §3.2: "2. **Axles second.** `trailer_axle_count` must be at least the
    required axle count, which is the greater of 2 and the declared gross
    weight divided by 20,000 lbs per axle rounded up to a whole axle; a
    shortfall is rejected with `ERR_AXLE_COUNT_INSUFFICIENT` (HTTP 422)."

    Design: Corner/validations/trailer_capacity_checked_before_axles
    """
    customer = create_customer("Order Check Co", 50_000_000)
    load = create_load_for_customer(
        customer["id"], cargo_description="Heavy skid", gross_weight_lbs=96000,
        width_in=100, height_in=50, length_in=400, origin="X", destination="Y",
    )
    # required_axles = max(2, ceil(96000/20000)) = 5.
    # FLATBED capacity 48000 < 96000 AND 4 axles < 5: capacity wins.
    err1 = validate_error(
        api.plan_load(
            load["id"],
            {
                "trailer_type": "FLATBED", "trailer_axle_count": 4,
                "driver_name": "N. Oz", "driver_oversize_endorsed": True,
            },
            DISPATCHER,
        ),
        ApiErrorId.ERR_TRAILER_CAPACITY_EXCEEDED,
    )
    assert err1["error_id"] == "ERR_TRAILER_CAPACITY_EXCEEDED"
    # EXTENDABLE capacity 150000 passes; 4 < 5 isolates the axle check.
    err2 = validate_error(
        api.plan_load(
            load["id"],
            {
                "trailer_type": "EXTENDABLE_DOUBLE_DROP",
                "trailer_axle_count": 4,
                "driver_name": "N. Oz", "driver_oversize_endorsed": True,
            },
            DISPATCHER,
        ),
        ApiErrorId.ERR_AXLE_COUNT_INSUFFICIENT,
    )
    assert err2["error_id"] == "ERR_AXLE_COUNT_INSUFFICIENT"
    # No partial mutation after either failed plan.
    current = validate_success(api.get_load(load["id"], DISPATCHER), 200)
    assert current["status"] == "DRAFT"


def test_driver_endorsement_required(api):
    """PRD §3.2: "3. **Endorsement last.** When the load is oversize or
    overweight, `driver_oversize_endorsed` must be true; planning such a load
    under an unendorsed driver is rejected with `ERR_DRIVER_NOT_ENDORSED`
    (HTTP 422)."

    Design: Corner/validations/driver_endorsement_required
    """
    customer = create_customer("Endorse Co", 50_000_000)
    load = create_load_for_customer(
        customer["id"], cargo_description="Heavy skid", gross_weight_lbs=96000,
        width_in=100, height_in=50, length_in=400, origin="X", destination="Y",
    )
    # Capacity and axles both pass, isolating the third check.
    err = validate_error(
        api.plan_load(
            load["id"],
            {
                "trailer_type": "EXTENDABLE_DOUBLE_DROP",
                "trailer_axle_count": 6,
                "driver_name": "O. Py", "driver_oversize_endorsed": False,
            },
            DISPATCHER,
        ),
        ApiErrorId.ERR_DRIVER_NOT_ENDORSED,
    )
    assert err["error_id"] == "ERR_DRIVER_NOT_ENDORSED"


def test_securement_wll_insufficient(api):
    """PRD §3.4: "Approval evaluates two conditions: the aggregate working load
    limit must be at least half the load's gross weight, where an odd pound
    rounds up — a shortfall is rejected with `ERR_SECUREMENT_WLL_INSUFFICIENT`
    (HTTP 422) — and when the load's `cargo_requires_tarp` flag is set, the
    method must be `CHAINS_AND_TARPS`, or approval is rejected with
    `ERR_TARPING_REQUIRED` (HTTP 422)."
    PRD §3.4: "The plan's `aggregate_wll_lbs` is computed as `tiedown_count`
    multiplied by `wll_per_tiedown_lbs`, and the plan is created directly in
    `SUBMITTED` status."

    Design: Corner/validations/securement_wll_insufficient
    """
    customer = create_customer("WLL Co", 50_000_000)
    load = create_load_for_customer(
        customer["id"], cargo_description="Heavy skid", gross_weight_lbs=96000,
        width_in=100, height_in=50, length_in=400, origin="X", destination="Y",
    )
    plan_load(
        load["id"], trailer_type="EXTENDABLE_DOUBLE_DROP",
        trailer_axle_count=6, driver_name="P. Al",
        driver_oversize_endorsed=True,
    )
    resp = api.create_securement_plan(
        load["id"],
        {"method": "CHAINS", "tiedown_count": 2, "wll_per_tiedown_lbs": 10000},
        DISPATCHER,
    )
    plan = validate_success(resp, 201)
    # Computed at creation: 2 x 10000.
    assert plan["aggregate_wll_lbs"] == 20000
    # 20000 < ceil(96000/2) = 48000.
    err = validate_error(
        api.approve_securement_plan(plan["id"], SAFETY),
        ApiErrorId.ERR_SECUREMENT_WLL_INSUFFICIENT,
    )
    assert err["error_id"] == "ERR_SECUREMENT_WLL_INSUFFICIENT"


def test_outside_travel_window_expires_permit(api):
    """PRD §3.7: "The logical clock must lie within every `GRANTED` permit's
    travel window — permits whose window has passed flip to `EXPIRED` during
    this evaluation, and any window violation is `ERR_OUTSIDE_TRAVEL_WINDOW`
    (HTTP 409)."
    PRD §3.5: "a granted permit whose travel window has passed flips lazily to
    `EXPIRED` the next time the readiness gate or the departure check evaluates
    it"

    Design: Corner/validations/outside_travel_window_expires_permit
    """
    # Build the CLEARED scenario with short permit windows (08-10..08-11).
    customer = create_customer("Window Co", 100_000_000)
    load = create_load_for_customer(
        customer["id"],
        cargo_description="Press", gross_weight_lbs=96000,
        width_in=150, height_in=100, length_in=400,
        origin="X", destination="Y",
    )
    plan_load(
        load["id"], trailer_type="EXTENDABLE_DOUBLE_DROP",
        trailer_axle_count=6, driver_name="Q. Un",
        driver_oversize_endorsed=True,
    )
    survey_load(
        load["id"], route_miles=500, states_crossed=["CA"],
        min_bridge_clearance_in=200, max_bridge_weight_lbs=120000,
    )
    short = ("2026-08-10T00:00:00Z", "2026-08-11T00:00:00Z")
    create_filed_and_granted_permit(
        load["id"], "CA", "OVERSIZE",
        window_start=short[0], window_end=short[1],
    )
    create_filed_and_granted_permit(
        load["id"], "CA", "OVERWEIGHT",
        window_start=short[0], window_end=short[1],
    )
    book_escort(load["id"], provider_name="Window Pilots", position="REAR")
    schedule_both_cranes(load["id"])
    file_and_approve_securement(load["id"])
    # Clock past both windows but inside curfew hours.
    set_clock("2026-08-12T10:00:00Z")
    err = validate_error(
        api.depart_load(load["id"], DRIVER),
        ApiErrorId.ERR_OUTSIDE_TRAVEL_WINDOW,
    )
    assert err["error_id"] == "ERR_OUTSIDE_TRAVEL_WINDOW"
    # Lazy expiry fired during the failed depart evaluation.
    permits = validate_success(api.list_permits(load["id"], DISPATCHER), 200)
    assert all(p["status"] == "EXPIRED" for p in permits)
    # The failed depart leaves the load in place.
    current = validate_success(api.get_load(load["id"], DISPATCHER), 200)
    assert current["status"] == "CLEARED"


def test_curfew_blocks_depart(api):
    """PRD §3.7: "The clock's UTC hour must be at least 5 and strictly before
    21, or departure is rejected with `ERR_CURFEW_VIOLATION` (HTTP 409)."
    PRD §2.8: "Independently, departure is only lawful when the logical clock's
    UTC hour is at least 5 and strictly before 21 — a night curfew that keeps
    oversize moves off the road between 21:00 and 05:00 UTC."

    Design: Corner/validations/curfew_blocks_depart
    """
    _, load = setup_standard_load_cleared(company_name="Curfew Co")
    # 02:00 UTC is outside the [5, 21) departure band; a fully CLEARED
    # STANDARD load with no permits at all still cannot depart.
    set_clock("2026-08-12T02:00:00Z")
    err = validate_error(
        api.depart_load(load["id"], DRIVER),
        ApiErrorId.ERR_CURFEW_VIOLATION,
    )
    assert err["error_id"] == "ERR_CURFEW_VIOLATION"
    current = validate_success(api.get_load(load["id"], DISPATCHER), 200)
    assert current["status"] == "CLEARED"


def test_credit_exceeded_at_depart(api):
    """PRD §3.7: "Finally, the provisional cost estimate's `total_cents` must
    not exceed the customer's remaining credit — `credit_limit_cents` minus
    `outstanding_balance_cents` — with equality passing and any excess rejected
    as `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

    Design: Corner/validations/credit_exceeded_at_depart
    """
    ctx = setup_ca_oversize_overweight_cleared(
        company_name="Broke Co", credit_limit_cents=100_000,
    )
    load_id = ctx["load"]["id"]
    est = validate_success(api.get_cost_estimate(load_id, BILLING), 200)
    # Escorts, windows, and curfew all satisfied; only the fiscal gate fails.
    assert est["total_cents"] == 475740
    set_clock("2026-08-12T10:00:00Z")
    err = validate_error(
        api.depart_load(load_id, DRIVER),
        ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED,
    )
    # 475740 > 100000 - 0.
    assert err["error_id"] == "ERR_CREDIT_LIMIT_EXCEEDED"
    current = validate_success(api.get_load(load_id, DISPATCHER), 200)
    assert current["status"] == "CLEARED"


def test_second_invoice_rejected(api):
    """PRD §3.9: "A `BillingClerk` creates the invoice for a `DELIVERED` load,
    and a load may carry at most one `ISSUED` invoice at a time — a second
    attempt is rejected with `ERR_INVOICE_EXISTS` (HTTP 409)."
    PRD §3.9: "Voiding, also restricted to `ISSUED` invoices, moves it to the
    terminal `VOID` state, credits the same amount off the outstanding balance,
    and un-sweeps the invoice's fines from `APPLIED` back to `PENDING` so that
    a replacement invoice can legitimately include them."

    Design: Corner/validations/second_invoice_rejected
    """
    _, load = setup_standard_load_delivered(company_name="Double Bill Co")
    first = issue_invoice(load["id"])
    assert first["status"] == "ISSUED"
    err = validate_error(
        api.create_invoice(load["id"], BILLING),
        ApiErrorId.ERR_INVOICE_EXISTS,
    )
    assert err["error_id"] == "ERR_INVOICE_EXISTS"
    # Voiding releases the slot and the replacement recomputes identically.
    validate_success(api.void_invoice(first["id"], BILLING), 200)
    second = issue_invoice(load["id"])
    assert second["status"] == "ISSUED"
    assert second["total_cents"] == 37800
