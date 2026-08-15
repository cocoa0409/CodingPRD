"""RBAC, optimistic concurrency, versioning, and immediate-consistency claims
(PRD §2.1, §2.4, §2.6, §2.7, §3.7)."""
from test_helpers import (
    DISPATCHER,
    PERMIT_CLERK,
    SAFETY,
    ApiErrorId,
    book_escort,
    create_customer,
    create_escort_booking_payload,
    create_filed_and_granted_permit,
    create_load_for_customer,
    create_permit_for_load,
    file_and_approve_securement,
    get_load_version,
    make_shipper_headers,
    plan_load,
    record_scale_violation,
    schedule_both_cranes,
    survey_load,
    validate_error,
    validate_success,
)


def test_dispatcher_cannot_create_customer(api):
    """PRD §4: "| POST | `/heavy-haul/customers` | Register a shipper customer
    | PlatformAdmin |"
    PRD §2.1: "Beyond header presence, every endpoint restricts which roles may
    call it; an authenticated caller whose role is not on the endpoint's
    authorized list is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/dispatcher_cannot_create_customer
    """
    create_customer("Seed Co", 500000)
    err = validate_error(
        api.create_customer(
            {"company_name": "Intruder Co", "credit_limit_cents": 500000},
            DISPATCHER,
        ),
        ApiErrorId.ERR_FORBIDDEN,
    )
    assert err["error_id"] == "ERR_FORBIDDEN"


def test_shipper_cannot_plan(api):
    """PRD §4: "| POST | `/heavy-haul/loads/{id}/plan` | Select trailer
    configuration and driver; compute flags, axles, escort positions |
    Dispatcher |"
    PRD §2.1: "Beyond header presence, every endpoint restricts which roles may
    call it; an authenticated caller whose role is not on the endpoint's
    authorized list is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/shipper_cannot_plan
    """
    customer = create_customer("Self Serve Co", 500000)
    load = create_load_for_customer(customer["id"], cargo_description="Crates")
    # Ownership does not substitute for role: planning is Dispatcher-exclusive
    # even for the load's owner.
    err = validate_error(
        api.plan_load(
            load["id"],
            {
                "trailer_type": "FLATBED", "trailer_axle_count": 2,
                "driver_name": "U. Be", "driver_oversize_endorsed": False,
            },
            make_shipper_headers(customer["id"]),
        ),
        ApiErrorId.ERR_FORBIDDEN,
    )
    assert err["error_id"] == "ERR_FORBIDDEN"


def test_shipper_cannot_cancel_other_shippers_load(api):
    """PRD §2.1: "A `Shipper` who attempts to act on a load, fine, cost
    estimate, or invoice belonging to a different customer is rejected with
    `ERR_NOT_OWN_RESOURCE` (HTTP 403)."
    PRD §3.7: "A `Shipper` may cancel only their own loads — ownership is
    checked per §2.1 with `ERR_NOT_OWN_RESOURCE`."

    Design: Corner/rbac/shipper_cannot_cancel_other_shippers_load
    """
    cust_a = create_customer("Owner A", 500000)
    cust_b = create_customer("Owner B", 500000)
    load = create_load_for_customer(cust_a["id"], cargo_description="A's crates")
    # The role is allowed on cancel; ownership is not.
    err = validate_error(
        api.cancel_load(load["id"], make_shipper_headers(cust_b["id"])),
        ApiErrorId.ERR_NOT_OWN_RESOURCE,
    )
    assert err["error_id"] == "ERR_NOT_OWN_RESOURCE"
    current = validate_success(api.get_load(load["id"], DISPATCHER), 200)
    assert current["status"] == "DRAFT"


def test_shipper_cannot_dispute_other_shippers_fine(api):
    """PRD §3.9: "A `Shipper` may dispute a fine that is still `PENDING` and
    customer-liable — disputing a non-pending fine or a carrier-liable one
    (those are absorbed, not disputed) is rejected with
    `ERR_FINE_NOT_DISPUTABLE` (HTTP 409) — and only for loads they own, with
    `ERR_NOT_OWN_RESOURCE` guarding cross-customer disputes."
    PRD §2.1: "A `Shipper` who attempts to act on a load, fine, cost estimate,
    or invoice belonging to a different customer is rejected with
    `ERR_NOT_OWN_RESOURCE` (HTTP 403)."

    Design: Corner/rbac/shipper_cannot_dispute_other_shippers_fine
    """
    cust_a = create_customer("Fine Owner A", 100_000_000)
    cust_b = create_customer("Fine Owner B", 100_000_000)
    # A's load: CLEARED CA scenario, then a scale violation at 100000 lbs
    # produces the PENDING CUSTOMER-liable OVERWEIGHT fine (PRD §3.8).
    load = create_load_for_customer(
        cust_a["id"],
        cargo_description="Press", gross_weight_lbs=96000,
        width_in=150, height_in=100, length_in=400,
        origin="X", destination="Y",
    )
    plan_load(
        load["id"], trailer_type="EXTENDABLE_DOUBLE_DROP",
        trailer_axle_count=6, driver_name="V. Ax",
        driver_oversize_endorsed=True,
    )
    survey_load(
        load["id"], route_miles=500, states_crossed=["CA"],
        min_bridge_clearance_in=200, max_bridge_weight_lbs=120000,
    )
    create_filed_and_granted_permit(load["id"], "CA", "OVERSIZE")
    create_filed_and_granted_permit(load["id"], "CA", "OVERWEIGHT")
    book_escort(load["id"], provider_name="Fine Pilots", position="REAR")
    schedule_both_cranes(load["id"])
    file_and_approve_securement(load["id"])
    record_scale_violation(
        load["id"], measured_gross_lbs=100000,
        weighed_at="2026-08-12T07:30:00Z",
    )
    fines = validate_success(api.list_fines(load["id"], SAFETY), 200)
    fine = fines[0]
    # Customer-liable OVERWEIGHT fine from the cascade.
    assert fine["status"] == "PENDING"
    assert fine["liable_party"] == "CUSTOMER"
    # B's X-User-ID != load.customer_id A.
    err = validate_error(
        api.dispute_fine(fine["id"], make_shipper_headers(cust_b["id"])),
        ApiErrorId.ERR_NOT_OWN_RESOURCE,
    )
    assert err["error_id"] == "ERR_NOT_OWN_RESOURCE"
    after = validate_success(api.list_fines(load["id"], SAFETY), 200)
    assert after[0]["status"] == "PENDING"


def test_occ_permit_create_stale_version(api):
    """PRD §2.6: "Creating a permit application for a load requires the request
    to carry `expected_load_version`, holding the load `version` the client
    last observed."
    PRD §2.6: "In both cases, if the supplied value does not equal the load's
    current `version`, the request is rejected with `ERR_STALE_LOAD_VERSION`
    (HTTP 412)."
    PRD §3.5: "A new permit starts in `DRAFT`, and its creation increments the
    owning load's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/occ_permit_create_stale_version
    """
    customer = create_customer("OCC Permit Co", 50_000_000)
    load = create_load_for_customer(
        customer["id"],
        cargo_description="Tank", gross_weight_lbs=96000,
        width_in=150, height_in=100, length_in=400,
        origin="X", destination="Y",
    )
    plan_load(
        load["id"], trailer_type="EXTENDABLE_DOUBLE_DROP",
        trailer_axle_count=6, driver_name="W. Cy",
        driver_oversize_endorsed=True,
    )
    surveyed = survey_load(
        load["id"], route_miles=500, states_crossed=["CA"],
        min_bridge_clearance_in=200, max_bridge_weight_lbs=120000,
    )
    current_version = surveyed["version"]
    # Stale expected version is refused with 412.
    err = validate_error(
        api.create_permit(
            load["id"],
            {
                "state_code": "CA", "permit_type": "OVERSIZE",
                "expected_load_version": current_version - 1,
            },
            PERMIT_CLERK,
        ),
        ApiErrorId.ERR_STALE_LOAD_VERSION,
    )
    assert err["error_id"] == "ERR_STALE_LOAD_VERSION"
    # The current version is accepted...
    permit = create_permit_for_load(
        load["id"], "CA", "OVERSIZE", expected_load_version=current_version
    )
    assert permit["status"] == "DRAFT"
    # ...and itself advances the load version by 1.
    assert get_load_version(load["id"]) == current_version + 1


def test_occ_escort_booking_stale_version(api):
    """PRD §2.6: "- Booking an escort for a load likewise requires
    `expected_load_version`."
    PRD §2.6: "In both cases, if the supplied value does not equal the load's
    current `version`, the request is rejected with `ERR_STALE_LOAD_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_escort_booking_stale_version
    """
    customer = create_customer("OCC Escort Co", 50_000_000)
    load = create_load_for_customer(
        customer["id"],
        cargo_description="Wide skid", gross_weight_lbs=40000,
        width_in=150, height_in=100, length_in=400,
        origin="X", destination="Y",
    )
    planned = plan_load(
        load["id"], trailer_type="FLATBED", trailer_axle_count=2,
        driver_name="X. Dy", driver_oversize_endorsed=True,
    )
    current_version = planned["version"]
    # Stale expected version refused even though the payload is well formed.
    err = validate_error(
        api.create_escort_booking(
            load["id"],
            create_escort_booking_payload(
                provider_name="Stale Pilots", position="REAR",
                expected_load_version=current_version - 1,
            ),
            DISPATCHER,
        ),
        ApiErrorId.ERR_STALE_LOAD_VERSION,
    )
    assert err["error_id"] == "ERR_STALE_LOAD_VERSION"
    # Retry with the observed version succeeds.
    booking = book_escort(
        load["id"], provider_name="Stale Pilots", position="REAR",
        expected_load_version=current_version,
    )
    assert booking["status"] == "CONFIRMED"


def test_version_increments_each_mutation(api):
    """PRD §2.4: "`version` (integer): a system-managed counter starting from
    its initial value at creation and incremented by exactly 1 on every
    mutation of the resource."
    PRD §3.2: "Every successful plan or re-plan increments the load's `version`
    by 1."
    PRD §3.3: "Each survey attempt increments the load's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/version_increments_each_mutation
    """
    customer = create_customer("Version Co", 500000)
    created = create_load_for_customer(customer["id"],
                                       cargo_description="Crates")
    assert created["version"] == 1
    planned = plan_load(created["id"])
    assert planned["version"] == 2
    surveyed = survey_load(planned["id"])
    assert surveyed["version"] == 3


def test_immediate_consistency_after_gate(api):
    """PRD §2.7: "The system maintains immediate consistency across the load
    and its dependents. When a parent load undergoes a state transition, every
    dependent child resource whose continued state would contradict the new
    reality is transitioned in the same request — permits are withdrawn on
    cancellation, escorts and crane appointments are completed on delivery, and
    the overweight cascade (§3.8) walks permits, the load, and escort bookings
    in one atomic step. Conversely, changes on child resources — a permit
    grant, an escort booking created or cancelled, a crane appointment
    scheduled, a securement plan approved — re-trigger evaluation of the parent
    load's readiness, and the load advances automatically when all criteria are
    satisfied."
    PRD §3.7: "When all five pass, the load advances to `CLEARED` and its
    `version` increments."

    Design: Corner/consistency_model/immediate_consistency_after_gate
    """
    customer = create_customer("Immediate Co", 50_000_000)
    load = create_load_for_customer(
        customer["id"],
        cargo_description="Wide crate", gross_weight_lbs=40000,
        width_in=150, height_in=100, length_in=400,
        origin="X", destination="Y",
    )
    plan_load(
        load["id"], trailer_type="FLATBED", trailer_axle_count=2,
        driver_name="Z. Fe", driver_oversize_endorsed=True,
    )
    survey_load(
        load["id"], route_miles=100, states_crossed=["CA"],
        min_bridge_clearance_in=200, max_bridge_weight_lbs=80000,
    )
    create_filed_and_granted_permit(load["id"], "CA", "OVERSIZE")
    book_escort(load["id"], provider_name="Gate Pilots", position="REAR")
    schedule_both_cranes(load["id"])
    resp = api.create_securement_plan(
        load["id"],
        {"method": "CHAINS", "tiedown_count": 2, "wll_per_tiedown_lbs": 10000},
        DISPATCHER,
    )
    plan = validate_success(resp, 201)
    # Gate incomplete one call earlier.
    pre = validate_success(api.get_load(load["id"], DISPATCHER), 200)
    assert pre["status"] == "SURVEYED"
    approved = validate_success(
        api.approve_securement_plan(plan["id"], SAFETY), 200
    )
    assert approved["status"] == "APPROVED"
    # The very next read (no delay, no rebuild) sees the gate's mutation.
    post = validate_success(api.get_load(load["id"], DISPATCHER), 200)
    assert post["status"] == "CLEARED"
