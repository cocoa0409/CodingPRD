"""Second-pass tests for each difficulty instance (distinct angle on the same rule).

Each difficulty instance is covered by at least two tests; the first pass lives in the
domain files (pricing, workflows, validations, invariants). These complementary tests
exercise a different observable facet of the same PRD rule (a boundary neighbour, a
side-effect, or the non-conflicting positive branch) while citing the same rule.
"""
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    validate_paginated, ApiErrorId,
    setup_private_case_cremated, setup_private_case_invoiced,
    setup_received_case_with_cooler, setup_case_ready_for_return,
    setup_communal_batch_fired, setup_communal_batch_loaded,
    create_clinic, create_owner, create_retort, create_case, create_batch,
    create_cooler, drive_case_to_received, store_case, stage_load_fire_private,
    set_clock, get_case_version, TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
OPERATOR = TEST_USERS["operator_headers"]


def _case(case_id):
    return get_success_data(api_client.get_case(case_id, ADMIN))


def _charge(case_id):
    return _case(case_id)["cremation_charge_cents"]


# =========================================================================== #
# dual_variant_calc — second pass
# =========================================================================== #
def test_private_expedited_uses_flat_tier_not_pooled_allocation(api):
    """PRD §3.9: "For a `PRIVATE` batch — which holds the single member — the charge is
    the flat tier rate for that pet's weight tier plus the expedite surcharge if the case
    is expedited ... A private firing leaves the batch's `communal_firing_total_cents` at
    0."

    Design: Difficulty/dual_variant_calc/dual_calc_case_private_vs_communal_charge
    """
    ctx = setup_private_case_cremated(clock="2026-06-01T00:00:00Z", weight_lbs=50,
                                      expedited=True, bill_to="OWNER")
    case = _case(ctx["case"]["id"])
    assert case["cremation_charge_cents"] == 23000, "18000 MEDIUM flat + 5000 expedite"
    batch = get_success_data(api_client.get_batch(ctx["batch_id"], ADMIN))
    assert batch["communal_firing_total_cents"] == 0, "PRIVATE leaves pooled total at 0"


def test_clinic_statement_completion_only_counts_cremated(api):
    """PRD §3.14: "Under the `COMPLETION` basis recognition waits for cremation, so the sum
    includes only clinic-account cases whose custody status is `CREMATED`,
    `READY_FOR_RETURN`, or `RETURNED`."

    Design: Difficulty/dual_variant_calc/dual_calc_clinic_statement_accrual_vs_completion
    """
    ctx = setup_private_case_cremated(clock="2026-06-02T00:00:00Z", weight_lbs=50,
                                      bill_to="CLINIC_ACCOUNT")
    clinic_id = ctx["clinic_id"]
    completion = validate_success(
        api_client.get_clinic_statement(clinic_id, ADMIN, params={"basis": "COMPLETION"}))
    assert completion["balance_cents"] == 18000, "single cremated clinic case recognized"
    assert completion["clinic_id"] == clinic_id
    assert completion["basis"] == "COMPLETION"


# =========================================================================== #
# combinatorial_formula — second pass
# =========================================================================== #
def test_private_small_tier_no_surcharge(api):
    """PRD §3.9: "12000 cents for `SMALL`, 18000 for `MEDIUM`, 26000 for `LARGE`, and
    38000 for `XLARGE`, with an additional 5000 cents added when the `expedited` flag is
    true."

    Design: Difficulty/combinatorial_formula/combinatorial_private_charge_tier_plus_surcharge
    """
    ctx = setup_private_case_cremated(clock="2026-06-03T00:00:00Z", weight_lbs=20,
                                      expedited=False, bill_to="OWNER")
    case = _case(ctx["case"]["id"])
    assert case["weight_tier"] == "SMALL"
    assert case["cremation_charge_cents"] == 12000, "SMALL flat, no expedite"


def test_communal_two_member_remainder_distribution(api):
    """PRD §3.9: "For each member, its raw share is the pooled total of 30000 cents
    multiplied by that member's weight and divided by the total weight; that raw share is
    rounded half up to a whole cent, and this per-case rounding happens before any
    summation."

    Design: Difficulty/combinatorial_formula/combinatorial_communal_rounding_order_remainder
    """
    # weights 1 and 2 -> total 3; raw 10000 and 20000; exact, no rounding remainder.
    ctx = setup_communal_batch_fired("2026-06-04T00:00:00Z", [1, 2],
                                     scheduled_start="2026-06-04T08:00:00Z",
                                     scheduled_end="2026-06-04T10:00:00Z")
    c1, c2 = ctx["case_ids"]
    assert _charge(c1) == 10000
    assert _charge(c2) == 20000
    assert _charge(c1) + _charge(c2) == 30000


def test_invoice_high_tier_fee_zero_above_50000(api):
    """PRD §3.10: "0 cents when the subtotal is above 50000 cents. The total is the
    subtotal plus the handling fee"

    Design: Difficulty/combinatorial_formula/combinatorial_invoice_subtotal_then_fee_tier
    """
    # PRIVATE XLARGE (200 lbs) -> 38000 charge + PENDANT 9500 + URN 8000 = 55500 (> 50000).
    set_clock("2026-06-05T00:00:00Z")
    retort = create_retort(max_load_lbs=300)
    owner = create_owner()
    case = create_case(owner["id"], service_type="PRIVATE", weight_lbs=200,
                       bill_to="OWNER", pickup_kind="HOME", species="OTHER")
    get_success_data(api_client.create_keepsake(case["id"], "PENDANT", OPERATOR))
    get_success_data(api_client.create_keepsake(case["id"], "URN", OPERATOR))
    drive_case_to_received(case["id"])
    batch = stage_load_fire_private(case["id"], retort["id"],
                                    "2026-06-05T08:00:00Z", "2026-06-05T10:00:00Z")
    get_success_data(api_client.complete_batch(batch, OPERATOR))
    version = get_case_version(case["id"])
    invoice = validate_success(api_client.create_invoice(case["id"], version, ADMIN), 201)
    assert invoice["subtotal_cents"] == 55500
    assert invoice["handling_fee_cents"] == 0, "subtotal above 50000 -> fee 0"
    assert invoice["total_cents"] == 55500


# =========================================================================== #
# non_linear_state_machine — second pass
# =========================================================================== #
def test_case_billing_settled_while_custody_returned(api):
    """PRD §3.2: "The two case axes — `custody_status` and `billing_status` — evolve
    independently."
    PRD §3.11: "Payment cascades the case's billing from `INVOICED` to `SETTLED`."

    Design: Difficulty/non_linear_state_machine/nonlinear_case_parallel_custody_x_billing
    """
    ctx = setup_private_case_invoiced(clock="2026-06-06T00:00:00Z", weight_lbs=50,
                                      bill_to="OWNER")
    case_id = ctx["case"]["id"]
    get_success_data(api_client.pay_invoice(ctx["invoice"]["id"], ADMIN))
    case = _case(case_id)
    # Custody remains CREMATED (no return performed) while billing reached SETTLED.
    assert case["custody_status"] == "CREMATED"
    assert case["billing_status"] == "SETTLED"


def test_cooler_available_after_store_below_capacity(api):
    """PRD §3.1: "A cooler's status is `FULL` when its occupied count is at least its total
    capacity, and `AVAILABLE` otherwise"

    Design: Difficulty/non_linear_state_machine/nonlinear_cooler_cyclic_full_to_available
    """
    # cap-2 cooler stays AVAILABLE after a single store (occupied 1 < 2).
    ctx = setup_received_case_with_cooler(clock="2026-06-07T00:00:00Z", capacity=2)
    store_case(ctx["case"]["id"], ctx["cooler"]["id"])
    cooler = get_success_data(api_client.get_cooler(ctx["cooler"]["id"], ADMIN))
    assert cooler["occupied_count"] == 1
    assert cooler["status"] == "AVAILABLE", "1 of 2 slots used remains AVAILABLE"


# =========================================================================== #
# transitive_cascade — second pass
# =========================================================================== #
def test_invoice_void_cascades_case_back_to_billable(api):
    """PRD §3.11: "Voiding cascades the case's billing from `INVOICED` back to `BILLABLE`,
    making the case eligible to be invoiced again. When the voided invoice is account-
    billed, the clinic's `outstanding_balance_cents` is decreased by the invoice's
    `total_cents`"

    Design: Difficulty/transitive_cascade/cascade_invoice_pay_to_case_to_clinic_depth3
    """
    ctx = setup_private_case_invoiced(clock="2026-06-08T00:00:00Z", weight_lbs=50,
                                      bill_to="CLINIC_ACCOUNT")
    get_success_data(api_client.void_invoice(ctx["invoice"]["id"], ADMIN))
    assert _case(ctx["case"]["id"])["billing_status"] == "BILLABLE"
    clinic = get_success_data(api_client.get_clinic(ctx["clinic_id"], ADMIN))
    assert clinic["outstanding_balance_cents"] == 0


def test_batch_complete_certificate_snapshots_pet_name(api):
    """PRD §3.6: "issues a certificate record in the `ISSUED` status bearing the next
    sequential `certificate_number`."
    PRD §3.6: "When issued it captures the next `certificate_number` in sequence, a
    snapshot of the case's `pet_name` and `service_type` as they stood at issuance"

    Design: Difficulty/transitive_cascade/cascade_batch_complete_to_case_to_certificate_depth2
    """
    set_clock("2026-06-09T00:00:00Z")
    retort = create_retort(max_load_lbs=300)
    owner = create_owner()
    case = create_case(owner["id"], service_type="PRIVATE", weight_lbs=40,
                       bill_to="OWNER", pickup_kind="HOME", pet_name="Rex")
    drive_case_to_received(case["id"])
    batch = stage_load_fire_private(case["id"], retort["id"],
                                    "2026-06-09T08:00:00Z", "2026-06-09T10:00:00Z")
    get_success_data(api_client.complete_batch(batch, OPERATOR))
    certs, _ = validate_paginated(api_client.list_certificates(case["id"], OPERATOR))
    assert certs[0]["status"] == "ISSUED"
    assert certs[0]["pet_name"] == "Rex"
    assert certs[0]["service_type"] == "PRIVATE"


# =========================================================================== #
# cross_entity_state_dependency — second pass
# =========================================================================== #
def test_completed_batch_drives_member_to_cremated(api):
    """PRD §3.6: "Completing the firing moves the batch from `FIRING` to `COMPLETED`.
    Completion cascades into every member case that is in the `STAGED` custody state,
    driving each from `STAGED` to `CREMATED`"

    Design: Difficulty/cross_entity_state_dependency/cross_case_staged_requires_batch_completed
    """
    set_clock("2026-06-10T00:00:00Z")
    retort = create_retort(max_load_lbs=300)
    owner = create_owner()
    case = create_case(owner["id"], service_type="PRIVATE", weight_lbs=30,
                       bill_to="OWNER", pickup_kind="HOME")
    drive_case_to_received(case["id"])
    batch_id = stage_load_fire_private(case["id"], retort["id"],
                                       "2026-06-10T08:00:00Z", "2026-06-10T10:00:00Z")
    assert _case(case["id"])["custody_status"] == "STAGED"
    get_success_data(api_client.complete_batch(batch_id, OPERATOR))
    assert _case(case["id"])["custody_status"] == "CREMATED", "completion crosses the dependency"


def test_finalize_return_requires_dispatched_route(api):
    """PRD §3.8: "Finalizing the return moves the case from `READY_FOR_RETURN` to
    `RETURNED`. This requires that the case be `READY_FOR_RETURN`, that its `service_type`
    be `PRIVATE` ... and that it have a return route currently in the `DISPATCHED` status."

    Design: Difficulty/cross_entity_state_dependency/cross_returnroute_dispatch_requires_case_ready
    """
    # Route still PLANNED (not dispatched) -> finalize-return must be rejected.
    ctx = setup_case_ready_for_return(clock="2026-06-11T00:00:00Z",
                                      return_method="COURIER_TO_HOME",
                                      destination_label="9 Rd")
    case_id = ctx["case"]["id"]
    validate_error(api_client.finalize_return(case_id, OPERATOR),
                   ApiErrorId.ERR_INVALID_STATE.value)
    assert _case(case_id)["custody_status"] == "READY_FOR_RETURN"


# =========================================================================== #
# priority_pair_validation_conflict — second pass
# =========================================================================== #
def test_cancel_intake_pending_case_succeeds_no_fiscal_block(api):
    """PRD §3.13: "Cancellation is permitted only while the case is in `INTAKE_PENDING`,
    `IN_TRANSIT`, `RECEIVED`, `IN_COOLER`, or `STAGED`"

    Design: Difficulty/priority_pair_validation_conflict/priority_state_beats_fiscal_on_cancel_after_complete
    """
    # The companion to the CREMATED lockdown: an INTAKE_PENDING case cancels cleanly,
    # confirming the state gate is what blocks the CREMATED case (not a generic refusal).
    set_clock("2026-06-12T00:00:00Z")
    owner = create_owner()
    case = create_case(owner["id"], service_type="PRIVATE", weight_lbs=30,
                       bill_to="OWNER", pickup_kind="HOME")
    cancelled = validate_success(api_client.cancel_case(case["id"], OPERATOR))
    assert cancelled["custody_status"] == "CANCELLED"


def test_assign_matching_service_type_succeeds(api):
    """PRD §3.5: "Staging is permitted only when the case is `RECEIVED` or `IN_COOLER`, the
    target batch is `OPEN`, and the case's `service_type` equals the batch's
    `service_type`."

    Design: Difficulty/priority_pair_validation_conflict/priority_safety_beats_referential_on_assign_mismatch
    """
    # Companion positive branch: when service types match, the safety check passes.
    set_clock("2026-06-13T00:00:00Z")
    retort = create_retort(max_load_lbs=300)
    owner = create_owner()
    case = create_case(owner["id"], service_type="COMMUNAL", weight_lbs=10,
                       bill_to="OWNER", pickup_kind="CLINIC", species="CAT")
    drive_case_to_received(case["id"], origin_kind="CLINIC", origin_label="V", driver_name="T")
    batch = create_batch(retort["id"], "COMMUNAL",
                         "2026-06-13T08:00:00Z", "2026-06-13T10:00:00Z")
    validate_success(api_client.assign_case(batch["id"], case["id"], OPERATOR))
    assert _case(case["id"])["custody_status"] == "STAGED"


# =========================================================================== #
# boundary_precision_check — second pass
# =========================================================================== #
def test_cooler_first_store_below_boundary_succeeds(api):
    """PRD §3.4: "Storing moves the case from `RECEIVED` to `IN_COOLER` and requires that
    the target cooler be `AVAILABLE` (equivalently, that its occupied count be below its
    total capacity)"

    Design: Difficulty/boundary_precision_check/boundary_cooler_capacity_at_full
    """
    # X-1 side of the boundary: the first store into a cap-1 cooler is accepted.
    ctx = setup_received_case_with_cooler(clock="2026-06-14T00:00:00Z", capacity=1)
    stored = validate_success(api_client.store_case(
        ctx["case"]["id"], ctx["cooler"]["id"], OPERATOR))
    assert stored["custody_status"] == "IN_COOLER"
    assert get_success_data(api_client.get_cooler(ctx["cooler"]["id"], ADMIN))["occupied_count"] == 1


def test_load_batch_with_one_member_succeeds(api):
    """PRD §3.6: "Loading requires that the batch be `OPEN`, that it have at least one
    member, and that its loaded weight not exceed the retort's maximum load."

    Design: Difficulty/boundary_precision_check/boundary_empty_batch_fire_zero_members
    """
    # member_count == 1 (just above the empty boundary) loads successfully.
    set_clock("2026-06-15T00:00:00Z")
    retort = create_retort(max_load_lbs=300)
    owner = create_owner()
    case = create_case(owner["id"], service_type="PRIVATE", weight_lbs=30,
                       bill_to="OWNER", pickup_kind="HOME")
    drive_case_to_received(case["id"])
    batch = create_batch(retort["id"], "PRIVATE",
                         "2026-06-15T08:00:00Z", "2026-06-15T10:00:00Z")
    get_success_data(api_client.assign_case(batch["id"], case["id"], OPERATOR))
    loaded = validate_success(api_client.load_batch(batch["id"], OPERATOR))
    assert loaded["status"] == "LOADED"


# =========================================================================== #
# resource_temporal_overlap — second pass
# =========================================================================== #
def test_retort_adjacent_window_does_not_conflict(api):
    """PRD §3.6: "windows that merely touch at an endpoint (one ending exactly when another
    begins) do not conflict."

    Design: Difficulty/resource_temporal_overlap/overlap_retort_firing_window_halfopen
    """
    set_clock("2026-06-16T00:00:00Z")
    retort = create_retort(max_load_lbs=400)
    owner = create_owner()

    x1 = create_case(owner["id"], service_type="PRIVATE", weight_lbs=30,
                     bill_to="OWNER", pickup_kind="HOME")
    drive_case_to_received(x1["id"])
    batchX = create_batch(retort["id"], "PRIVATE",
                          "2026-06-16T08:00:00Z", "2026-06-16T10:00:00Z")
    get_success_data(api_client.assign_case(batchX["id"], x1["id"], OPERATOR))
    get_success_data(api_client.load_batch(batchX["id"], OPERATOR))
    get_success_data(api_client.fire_batch(batchX["id"], OPERATOR))

    # Adjacent window starts exactly at the prior end (10:00) — half-open, no conflict.
    y1 = create_case(owner["id"], service_type="PRIVATE", weight_lbs=30,
                     bill_to="OWNER", pickup_kind="HOME")
    drive_case_to_received(y1["id"])
    batchY = create_batch(retort["id"], "PRIVATE",
                          "2026-06-16T10:00:00Z", "2026-06-16T12:00:00Z")
    get_success_data(api_client.assign_case(batchY["id"], y1["id"], OPERATOR))
    get_success_data(api_client.load_batch(batchY["id"], OPERATOR))
    fired = validate_success(api_client.fire_batch(batchY["id"], OPERATOR))
    assert fired["status"] == "FIRING", "touching endpoints do not conflict"


def test_viewing_room_far_apart_windows_allowed(api):
    """PRD §3.12: "the requested viewing window, extended by a viewing buffer of fifteen
    minutes, must not collide with any other non-cancelled viewing session already booked
    in the same `viewing_room_code`."

    Design: Difficulty/resource_temporal_overlap/overlap_viewing_room_buffered_window
    """
    set_clock("2026-06-17T00:00:00Z")
    owner = create_owner()
    a1 = create_case(owner["id"], service_type="PRIVATE", weight_lbs=20,
                     bill_to="OWNER", pickup_kind="HOME")
    get_success_data(api_client.create_memorial_addon(a1["id"], {
        "addon_type": "VIEWING_SESSION", "viewing_room_code": "ROOM-2",
        "viewing_start": "2026-06-17T10:00:00Z", "viewing_end": "2026-06-17T11:00:00Z",
    }, OPERATOR))

    a2 = create_case(owner["id"], service_type="PRIVATE", weight_lbs=20,
                     bill_to="OWNER", pickup_kind="HOME")
    # Starts 13:00, well beyond the 15-min buffer after the prior 11:00 end.
    addon = validate_success(api_client.create_memorial_addon(a2["id"], {
        "addon_type": "VIEWING_SESSION", "viewing_room_code": "ROOM-2",
        "viewing_start": "2026-06-17T13:00:00Z", "viewing_end": "2026-06-17T14:00:00Z",
    }, OPERATOR), 201)
    assert addon["status"] == "BOOKED"


# =========================================================================== #
# compensating_invariant — second pass
# =========================================================================== #
def test_cooler_capacity_invariant_holds_after_store(api):
    """PRD §3.1: "Available capacity is the total capacity minus the occupied count,
    floored at zero."

    Design: Difficulty/compensating_invariant/invariant_cooler_slots_conserved
    """
    # occupied_count + available_capacity == total_capacity must hold after a store too.
    ctx = setup_received_case_with_cooler(clock="2026-06-18T00:00:00Z", capacity=2)
    store_case(ctx["case"]["id"], ctx["cooler"]["id"])
    cooler = get_success_data(api_client.get_cooler(ctx["cooler"]["id"], ADMIN))
    assert cooler["occupied_count"] == 1
    assert cooler["available_capacity"] == 1
    assert cooler["occupied_count"] + cooler["available_capacity"] == cooler["total_capacity"]


def test_clinic_balance_returns_to_zero_after_pay(api):
    """PRD §3.11: "When the paid invoice is account-billed, the clinic's
    `outstanding_balance_cents` is decreased by the invoice's `total_cents` and its
    `account_status` is recomputed (returning from `DELINQUENT` to `CURRENT` if the
    balance falls to or below the credit limit)."

    Design: Difficulty/compensating_invariant/invariant_clinic_outstanding_conserved_on_void
    """
    # The pay path (rather than void) also restores outstanding to its pre-issue value.
    ctx = setup_private_case_invoiced(clock="2026-06-19T00:00:00Z", weight_lbs=50,
                                      bill_to="CLINIC_ACCOUNT")
    assert get_success_data(api_client.get_clinic(ctx["clinic_id"], ADMIN))["outstanding_balance_cents"] == 18000
    get_success_data(api_client.pay_invoice(ctx["invoice"]["id"], ADMIN))
    clinic = get_success_data(api_client.get_clinic(ctx["clinic_id"], ADMIN))
    assert clinic["outstanding_balance_cents"] == 0
    assert clinic["account_status"] == "CURRENT"
