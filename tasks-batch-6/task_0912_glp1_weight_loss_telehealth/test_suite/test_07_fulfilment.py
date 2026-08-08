"""Fulfilment: routing, reservation, shipment, cancellation and stock conservation."""

from test_helpers import (
    assert_lot_split,
    assert_pharmacy_order,
    create_pharmacy_order_payload,
    file_check_in,
    make_pharmacy_operator_headers,
    make_provider_headers,
    place_pharmacy_order,
    platform_admin_headers,
    prescription_version,
    read_prescription,
    read_supply_lot,
    record_supply_lot,
    register_pharmacy,
    reserve_order,
    set_clock,
    setup_prescription_with_stock,
    setup_reserved_order,
    setup_routed_order,
    setup_shipped_order,
    triage_check_in,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_routing_refuses_when_the_only_matching_lot_has_no_units(api):
    """PRD §3.7: "If the candidate set is empty, the request is rejected with
    `ERR_NO_ELIGIBLE_SUPPLY_LOT` (409)."
    PRD §3.7: "- the lot's `available_units` is at least the requested
    `units_requested`;"

    Design: Difficulty/boundary_precision_check/zero_available_units_yields_empty_routing_pool
    """
    scenario = setup_prescription_with_stock(
        patient={"email": "vic@example.com", "full_name": "Vic Osei"},
        lot={"lot_code": "L-0005", "total_units": 0},
    )

    response = api.create_pharmacy_order(
        create_pharmacy_order_payload(
            scenario["prescription"]["id"],
            scenario["step"]["id"],
            prescription_version(scenario["prescription"]["id"], scenario["clinician"]["id"]),
            units_requested=1,
        ),
        make_provider_headers(scenario["clinician"]["id"]),
    )

    validate_error(response, "ERR_NO_ELIGIBLE_SUPPLY_LOT")
    assert_lot_split(
        read_supply_lot(scenario["lot"]["id"]), available=0, reserved=0, dispensed=0
    )


def test_refused_routing_leaves_the_fulfilment_axis_unrouted(api):
    """PRD §3.4: "The fulfilment axis, `fulfillment_status`, is one of `UNROUTED`,
    `ROUTED`, `DISPENSED` or `REFILL_DUE` and begins at `UNROUTED`."
    PRD §2.7: "Rules are evaluated in a strict ascending order, and the first rule
    that fails determines the response — no later rule runs, and no partial
    mutation is persisted."

    Design: Difficulty/boundary_precision_check/zero_available_units_yields_empty_routing_pool
    """
    scenario = setup_prescription_with_stock(
        patient={"email": "vic2@example.com", "full_name": "Vic Osei"},
        lot={"lot_code": "L-0005B", "total_units": 0},
    )

    validate_error(
        api.create_pharmacy_order(
            create_pharmacy_order_payload(
                scenario["prescription"]["id"],
                scenario["step"]["id"],
                prescription_version(
                    scenario["prescription"]["id"], scenario["clinician"]["id"]
                ),
                units_requested=1,
            ),
            make_provider_headers(scenario["clinician"]["id"]),
        ),
        "ERR_NO_ELIGIBLE_SUPPLY_LOT",
    )

    prescription = read_prescription(
        scenario["prescription"]["id"], scenario["clinician"]["id"]
    )
    assert prescription["fulfillment_status"] == "UNROUTED"

    rows, meta = validate_paginated(
        api.list_pharmacy_orders(
            platform_admin_headers(),
            params={"prescription_id": scenario["prescription"]["id"]},
        )
    )
    assert meta["total_count"] == 0


def test_units_above_the_cycle_allowance_are_refused(api):
    """PRD §3.7: "That ceiling requires `units_requested` to be at most 4 and also
    at most the prescription's `units_per_cycle`; a request exceeding either bound
    is rejected with `ERR_UNITS_EXCEED_LIMIT` (422)."

    Design: Corner/validations/units_requested_above_units_per_cycle_rejected
    """
    scenario = setup_prescription_with_stock(
        patient={"email": "val2@example.com", "full_name": "Val Two"},
        prescription={"units_per_cycle": 2},
        lot={"lot_code": "L-0011"},
    )

    response = api.create_pharmacy_order(
        create_pharmacy_order_payload(
            scenario["prescription"]["id"],
            scenario["step"]["id"],
            prescription_version(scenario["prescription"]["id"], scenario["clinician"]["id"]),
            units_requested=4,
        ),
        make_provider_headers(scenario["clinician"]["id"]),
    )

    validate_error(response, "ERR_UNITS_EXCEED_LIMIT")
    assert_lot_split(
        read_supply_lot(scenario["lot"]["id"]), available=24, reserved=0, dispensed=0
    )
    prescription = read_prescription(
        scenario["prescription"]["id"], scenario["clinician"]["id"]
    )
    assert prescription["fulfillment_status"] == "UNROUTED"


def test_overlapping_reservation_beyond_window_capacity_is_refused(api):
    """PRD §3.7: "The lot must still hold at least `units_requested` in
    `available_units`, and the windowed aggregate test must pass: the sum of
    `units_requested` on this order plus the `units_requested` of every *other*
    order on the same `supply_lot_id` that is currently `RESERVED` and whose
    half-open window from `window_start_at` up to but not including `window_end_at`
    overlaps this order's window must be at most the lot's `window_capacity_units`.
    Failing either is rejected with `ERR_LOT_CAPACITY_EXCEEDED` (409)."

    Design: Difficulty/resource_temporal_overlap/supply_lot_windowed_aggregate_capacity
    """
    scenario = setup_routed_order(
        patient={"email": "bex@example.com", "full_name": "Bex Ono"},
        prescription={"units_per_cycle": 4},
        lot={"lot_code": "L-0007", "total_units": 24, "window_capacity_units": 6},
        order={
            "units_requested": 4,
            "window_start_at": "2026-06-05T00:00:00Z",
            "window_end_at": "2026-06-10T00:00:00Z",
        },
    )
    overlapping = place_pharmacy_order(
        scenario["prescription"]["id"],
        scenario["step"]["id"],
        scenario["clinician"]["id"],
        units_requested=3,
        window_start_at="2026-06-08T00:00:00Z",
        window_end_at="2026-06-12T00:00:00Z",
    )
    reserve_order(scenario["order"])

    response = api.reserve_pharmacy_order(
        overlapping["id"], {}, make_pharmacy_operator_headers(overlapping["pharmacy_id"])
    )

    validate_error(response, "ERR_LOT_CAPACITY_EXCEEDED")
    still_created = validate_success(
        api.get_pharmacy_order(overlapping["id"], platform_admin_headers())
    )
    assert still_created["status"] == "CREATED"
    assert_lot_split(
        read_supply_lot(scenario["lot"]["id"]), available=20, reserved=4, dispensed=0
    )


def test_reservation_in_a_merely_abutting_window_is_accepted(api):
    """PRD §3.7: "A successful reservation sets `reserved_at` to the clock,
    decrements the lot's `available_units` by `units_requested` and increments its
    `reserved_units` by the same amount; `total_units` never moves."
    PRD §2.10: "For every supply lot, `total_units` always equals `available_units`
    plus `reserved_units` plus `dispensed_units`."

    Design: Difficulty/resource_temporal_overlap/supply_lot_windowed_aggregate_capacity
    """
    scenario = setup_routed_order(
        patient={"email": "bex2@example.com", "full_name": "Bex Ono"},
        prescription={"units_per_cycle": 4},
        lot={"lot_code": "L-0007B", "total_units": 24, "window_capacity_units": 6},
        order={
            "units_requested": 4,
            "window_start_at": "2026-06-05T00:00:00Z",
            "window_end_at": "2026-06-10T00:00:00Z",
        },
    )
    abutting = place_pharmacy_order(
        scenario["prescription"]["id"],
        scenario["step"]["id"],
        scenario["clinician"]["id"],
        units_requested=3,
        window_start_at="2026-06-10T00:00:00Z",
        window_end_at="2026-06-15T00:00:00Z",
    )
    reserve_order(scenario["order"])

    response = api.reserve_pharmacy_order(
        abutting["id"], {}, make_pharmacy_operator_headers(abutting["pharmacy_id"])
    )
    reserved = validate_success(response)

    assert_pharmacy_order(reserved)
    assert reserved["status"] == "RESERVED"
    assert_lot_split(
        read_supply_lot(scenario["lot"]["id"]), available=17, reserved=7, dispensed=0
    )


def test_reserve_then_cancel_restores_the_lot_split_component_for_component(api):
    """PRD §2.10: "Reserving a pharmacy order moves `units_requested` from
    `available_units` to `reserved_units`; cancelling that order while it is
    reserved moves exactly the same quantity back from `reserved_units` to
    `available_units`, restoring both components to their pre-reservation values
    rather than merely restoring the sum."
    PRD §3.7: "On either path, `cancel_reason` is set to `OPERATOR` when a human
    invoked the cancellation, to `PA_DENIED` when the cascade came from a payer
    denial, and to `CLINICAL_HOLD` when it came from a clinical hold or a
    discontinuation."

    Design: Difficulty/compensating_invariant/supply_lot_units_conserved_across_reserve_then_cancel
    """
    scenario = setup_routed_order(
        patient={"email": "cyd@example.com", "full_name": "Cyd Rao"},
        lot={"lot_code": "L-0008", "total_units": 24},
    )
    assert_lot_split(
        read_supply_lot(scenario["lot"]["id"]), available=24, reserved=0, dispensed=0
    )

    reserve_order(scenario["order"])
    assert_lot_split(
        read_supply_lot(scenario["lot"]["id"]), available=22, reserved=2, dispensed=0
    )

    cancelled = validate_success(
        api.cancel_pharmacy_order(
            scenario["order"]["id"],
            {},
            make_pharmacy_operator_headers(scenario["pharmacy"]["id"]),
        )
    )

    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "OPERATOR"
    assert_lot_split(
        read_supply_lot(scenario["lot"]["id"]), available=24, reserved=0, dispensed=0
    )


def test_cancelled_reservation_rewinds_the_fulfilment_axis(api):
    """PRD §3.7: "Cancelling from `RESERVED` moves the order `RESERVED →
    CANCELLED`, increments the lot's `available_units` by `units_requested` and
    decrements its `reserved_units` by the same amount — restoring the
    pre-reservation split exactly, component for component — and additionally
    rewinds the prescription's `fulfillment_status` to `UNROUTED` when no other
    order for that prescription remains in `CREATED` or `RESERVED`."

    Design: Difficulty/compensating_invariant/supply_lot_units_conserved_across_reserve_then_cancel
    """
    scenario = setup_reserved_order(
        patient={"email": "cyd2@example.com", "full_name": "Cyd Rao"},
        lot={"lot_code": "L-0008B", "total_units": 24},
    )
    routed = read_prescription(
        scenario["prescription"]["id"], scenario["clinician"]["id"]
    )
    assert routed["fulfillment_status"] == "ROUTED"

    validate_success(
        api.cancel_pharmacy_order(
            scenario["order"]["id"],
            {},
            make_pharmacy_operator_headers(scenario["pharmacy"]["id"]),
        )
    )

    rewound = read_prescription(
        scenario["prescription"]["id"], scenario["clinician"]["id"]
    )
    assert rewound["fulfillment_status"] == "UNROUTED"
    assert_lot_split(
        read_supply_lot(scenario["lot"]["id"]), available=24, reserved=0, dispensed=0
    )


def test_reserving_an_already_shipped_order_is_refused(api):
    """PRD §3.7: "**Reserving.** The operator of the routed pharmacy holds the
    units. This moves the order `CREATED → RESERVED` and may only be performed by
    the `PharmacyOperator` whose pharmacy identity matches the order's
    `pharmacy_id`."
    PRD §2.7: "**State admissibility.** The target row is in a state from which the
    requested transition is declared (`ERR_INVALID_STATE`, 409)"

    Design: Corner/state_machines/reserve_on_shipped_order_returns_invalid_state
    """
    scenario = setup_shipped_order(
        patient={"email": "sm7@example.com", "full_name": "Sm Seven"},
        lot={"lot_code": "L-0010", "total_units": 24},
    )

    response = api.reserve_pharmacy_order(
        scenario["order"]["id"],
        {},
        make_pharmacy_operator_headers(scenario["pharmacy"]["id"]),
    )

    validate_error(response, "ERR_INVALID_STATE")
    still = validate_success(
        api.get_pharmacy_order(scenario["order"]["id"], platform_admin_headers())
    )
    assert still["status"] == "SHIPPED"
    assert_lot_split(
        read_supply_lot(scenario["lot"]["id"]), available=22, reserved=0, dispensed=2
    )


def test_stale_prescription_version_rejects_the_order_create(api):
    """PRD §2.8: "A `POST /glp1/pharmacy-orders` request must carry
    `expected_prescription_version`, a non-optional integer field holding the
    client's last observed `version` of the Prescription named by
    `prescription_id`. If that value does not equal the Prescription's current
    `version`, the request is rejected with `ERR_STALE_PRESCRIPTION_VERSION`
    (412)."
    PRD §3.7: "Creating an order also requires the prescription's
    `clinical_status` to be `ACTIVE`, failing which the request is refused with
    `ERR_PRESCRIPTION_NOT_ACTIVE` (409), and it advances the fulfilment axis as
    described in §3.4 while incrementing the prescription's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_prescription_version_rejects_order_create
    """
    scenario = setup_prescription_with_stock(
        patient={"email": "occ2@example.com", "full_name": "Occ Two"},
        lot={"lot_code": "L-0012", "total_units": 24},
    )
    stale_version = prescription_version(
        scenario["prescription"]["id"], scenario["clinician"]["id"]
    )
    place_pharmacy_order(
        scenario["prescription"]["id"],
        scenario["step"]["id"],
        scenario["clinician"]["id"],
        expected_prescription_version=stale_version,
    )

    refused = api.create_pharmacy_order(
        create_pharmacy_order_payload(
            scenario["prescription"]["id"],
            scenario["step"]["id"],
            stale_version,
            window_start_at="2026-06-12T00:00:00Z",
            window_end_at="2026-06-19T00:00:00Z",
        ),
        make_provider_headers(scenario["clinician"]["id"]),
    )
    validate_error(refused, "ERR_STALE_PRESCRIPTION_VERSION")

    refreshed = prescription_version(
        scenario["prescription"]["id"], scenario["clinician"]["id"]
    )
    accepted = api.create_pharmacy_order(
        create_pharmacy_order_payload(
            scenario["prescription"]["id"],
            scenario["step"]["id"],
            refreshed,
            window_start_at="2026-06-12T00:00:00Z",
            window_end_at="2026-06-19T00:00:00Z",
        ),
        make_provider_headers(scenario["clinician"]["id"]),
    )
    validate_success(accepted, 201)

    rows, meta = validate_paginated(
        api.list_pharmacy_orders(
            platform_admin_headers(),
            params={"prescription_id": scenario["prescription"]["id"]},
        )
    )
    assert meta["total_count"] == 2
    prescription = read_prescription(
        scenario["prescription"]["id"], scenario["clinician"]["id"]
    )
    assert prescription["fulfillment_status"] == "ROUTED"
    assert_lot_split(
        read_supply_lot(scenario["lot"]["id"]), available=24, reserved=0, dispensed=0
    )


def test_operator_of_another_pharmacy_cannot_reserve_the_routed_order(api):
    """PRD §2.1: "Ownership is enforced on six operations in particular — closing a
    consult, discontinuing a prescription, reserving a pharmacy order, shipping a
    pharmacy order, completing a coaching session, and cancelling a subscription. On
    these six, a caller whose role is listed for the endpoint but who is not the
    owner of the target row is still rejected with `ERR_UNAUTHORIZED` (403)."
    PRD §3.7: "Among the survivors the selector ranks first-expiring-first-out:
    earliest `expires_at` wins."

    Design: Corner/rbac/pharmacy_operator_cannot_reserve_another_pharmacys_order
    """
    set_clock("2026-06-01T00:00:00Z")
    other_pharmacy = register_pharmacy(name="Coast Compounding")
    other_lot = record_supply_lot(
        other_pharmacy["id"],
        lot_code="B-1",
        strength_mg=0.25,
        total_units=24,
        expires_at="2027-06-30T00:00:00Z",
    )
    scenario = setup_routed_order(
        patient={"email": "rb3@example.com", "full_name": "Rb Three"},
        pharmacy={"name": "Bay Compounding"},
        lot={"lot_code": "A-1", "total_units": 24, "expires_at": "2026-12-31T00:00:00Z"},
    )

    assert scenario["order"]["pharmacy_id"] == scenario["pharmacy"]["id"]
    assert scenario["order"]["supply_lot_id"] == scenario["lot"]["id"]

    response = api.reserve_pharmacy_order(
        scenario["order"]["id"], {}, make_pharmacy_operator_headers(other_pharmacy["id"])
    )
    validate_error(response, "ERR_UNAUTHORIZED")

    still = validate_success(
        api.get_pharmacy_order(scenario["order"]["id"], platform_admin_headers())
    )
    assert still["status"] == "CREATED"
    assert read_supply_lot(scenario["lot"]["id"])["available_units"] == 24
    assert read_supply_lot(other_lot["id"])["available_units"] == 24


def test_held_prescription_pre_empts_the_unit_ceiling_on_order_creation(api):
    """PRD §2.7: "Rules are evaluated in a strict ascending order, and the first
    rule that fails determines the response — no later rule runs, and no partial
    mutation is persisted."
    PRD §2.7: "where an operation additionally demands that the governing
    prescription be clinically active, a `HELD` or `DISCONTINUED` prescription
    yields `ERR_PRESCRIPTION_NOT_ACTIVE` (409)"
    PRD §2.7: "**Supply and quota constraints.** Lot routing, per-order unit
    ceilings, windowed lot capacity, and the appeal ceiling."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_constraint_on_order_creation
    """
    scenario = setup_prescription_with_stock(
        patient={"email": "mia@example.com", "full_name": "Mia Cruz"},
        prescription={"units_per_cycle": 2},
        lot={"lot_code": "L-0004", "total_units": 24},
    )
    set_clock("2026-06-20T00:00:00Z")
    check_in = file_check_in(
        scenario["patient"]["id"],
        scenario["prescription"]["id"],
        nausea_score=3,
        vomiting_score=3,
    )
    triage_check_in(check_in["id"], scenario["clinician"]["id"])
    held = read_prescription(scenario["prescription"]["id"], scenario["clinician"]["id"])
    assert held["clinical_status"] == "HELD"

    response = api.create_pharmacy_order(
        create_pharmacy_order_payload(
            scenario["prescription"]["id"],
            scenario["step"]["id"],
            held["version"],
            units_requested=4,
            window_start_at="2026-06-21T00:00:00Z",
            window_end_at="2026-06-28T00:00:00Z",
        ),
        make_provider_headers(scenario["clinician"]["id"]),
    )

    validate_error(response, "ERR_PRESCRIPTION_NOT_ACTIVE")
    assert response.json()["data"]["error_id"] != "ERR_UNITS_EXCEED_LIMIT", (
        "the state rung of the ladder runs before the supply-and-quota rung"
    )


def test_rejected_order_creation_writes_no_order_row(api):
    """PRD §2.7: "Rules are evaluated in a strict ascending order, and the first
    rule that fails determines the response — no later rule runs, and no partial
    mutation is persisted."
    PRD §2.7: "`ERR_PRESCRIPTION_NOT_ACTIVE` guards exactly five operations:
    creating a pharmacy order, reserving a pharmacy order, shipping a pharmacy
    order, escalating a titration rung, and requesting a refill."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_constraint_on_order_creation
    """
    scenario = setup_prescription_with_stock(
        patient={"email": "mia2@example.com", "full_name": "Mia Cruz"},
        prescription={"units_per_cycle": 2},
        lot={"lot_code": "L-0004B", "total_units": 24},
    )
    set_clock("2026-06-20T00:00:00Z")
    check_in = file_check_in(
        scenario["patient"]["id"],
        scenario["prescription"]["id"],
        nausea_score=3,
        vomiting_score=3,
    )
    triage_check_in(check_in["id"], scenario["clinician"]["id"])
    held = read_prescription(scenario["prescription"]["id"], scenario["clinician"]["id"])

    validate_error(
        api.create_pharmacy_order(
            create_pharmacy_order_payload(
                scenario["prescription"]["id"],
                scenario["step"]["id"],
                held["version"],
                units_requested=4,
                window_start_at="2026-06-21T00:00:00Z",
                window_end_at="2026-06-28T00:00:00Z",
            ),
            make_provider_headers(scenario["clinician"]["id"]),
        ),
        "ERR_PRESCRIPTION_NOT_ACTIVE",
    )

    rows, meta = validate_paginated(
        api.list_pharmacy_orders(
            platform_admin_headers(),
            params={"prescription_id": scenario["prescription"]["id"]},
        )
    )
    assert meta["total_count"] == 0
    assert_lot_split(
        read_supply_lot(scenario["lot"]["id"]), available=24, reserved=0, dispensed=0
    )
