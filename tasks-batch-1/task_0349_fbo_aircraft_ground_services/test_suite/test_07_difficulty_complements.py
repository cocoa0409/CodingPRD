"""Second tests for every difficulty-queue instance — complementary facets (boundary
neighbours, opposite branches, positive controls) of the same rule, each
independently PRD-derivable (PRD §3.2–§3.10).

These satisfy the ≥2-tests-per-difficulty-instance coverage target. Each carries the
same Design tag as its primary test in test_01..test_06.
"""
import pytest

from test_helpers import (
    api_client as api,
    get_success_data,
    validate_error,
    validate_success,
    setup_operator_aircraft_contract,
    setup_on_ground_visit,
    setup_servicing_visit,
    setup_departed_visit_with_invoice,
    setup_revoked_slot,
    get_invoice_for_visit,
    create_requested_fuel_order,
    create_fueled_fuel_order,
    create_dispatched_fuel_order,
    create_parking_assignment_payload,
    create_deice_service_payload,
    create_ramp_slot_payload,
    post_into_plane_ticket,
    occupy_payload,
    make_operator_headers,
    NON_EXISTENT_UUID,
    TEST_USERS,
)

OPS = TEST_USERS["ops_dispatcher_headers"]
FUEL = TEST_USERS["fuel_tech_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]
LINE = TEST_USERS["line_manager_headers"]


# ─── dual_variant_calc / fuel_cost_volume_vs_tankered ─────────────────
def test_volume_and_tankered_variants_diverge_on_same_entity():
    """PRD §3.2: "For a **tankering** order, the FBO is merely handling fuel uplifted
    off-field: the priced amount is simply the order's `ordered_gallons` multiplied by
    the contract's `tankering_fee_cents_per_gal`, with no product cost, no volume
    discount, and no movement of the operator's tier."
    PRD §3.2: "The order's `priced_amount_cents` is the sum of those per-gallon prices"

    The two variants priced on identical 6000-gal uplifts diverge: 3,115,000 (volume) vs
    180,000 (tankered).

    Design: Difficulty/dual_variant_calc/fuel_cost_volume_vs_tankered
    """
    operator, aircraft, contract = setup_operator_aircraft_contract()
    v1 = setup_on_ground_visit(operator["id"], aircraft["id"])
    o1 = create_requested_fuel_order(v1["id"], aircraft["id"], contract["id"],
                                     ordered_gallons=6000, tankering=False)
    vol = get_success_data(api.dispatch_fuel_order(o1["id"], FUEL))

    v2 = setup_on_ground_visit(operator["id"], aircraft["id"],
                               visit_overrides={"arrival_utc": "2026-06-16T08:00:00.000Z",
                                                "departure_utc": "2026-06-17T08:00:00.000Z"})
    o2 = create_requested_fuel_order(v2["id"], aircraft["id"], contract["id"],
                                     ordered_gallons=6000, tankering=True)
    tank = get_success_data(api.dispatch_fuel_order(o2["id"], FUEL))

    assert vol["priced_amount_cents"] == 3_115_000
    assert tank["priced_amount_cents"] == 180_000
    assert vol["priced_amount_cents"] != tank["priced_amount_cents"]


# ─── dual_variant_calc / ramp_fee_standard_vs_waived ──────────────────
def test_ramp_fee_not_waived_below_threshold_under_200_gallons():
    """PRD §3.5: "A `HANGAR` or `TIE_DOWN` spot never waives, and a `RAMP` spot below the
    200-gallon threshold pays the full weight-class rate times nights."

    A MID 3-night RAMP occupation on a visit with only 199 delivered Jet-A gallons (below
    the 200 threshold) pays the full standard fee 45,000 — the waiver does not apply.

    Design: Difficulty/dual_variant_calc/ramp_fee_standard_vs_waived
    """
    operator, aircraft, contract = setup_operator_aircraft_contract()
    visit = setup_on_ground_visit(operator["id"], aircraft["id"],
                                  visit_overrides={"arrival_utc": "2026-06-20T08:00:00.000Z",
                                                   "departure_utc": "2026-06-23T08:00:00.000Z"})
    order = create_fueled_fuel_order(visit["id"], aircraft["id"], contract["id"],
                                     ordered_gallons=199, tankering=False)
    post_into_plane_ticket(order["id"], 199)
    spot = get_success_data(api.create_parking_spot(
        {"label": "RAMP-C", "spot_type": "RAMP", "max_weight_class": "HEAVY"}, OPS))
    assignment = get_success_data(api.create_parking_assignment(
        create_parking_assignment_payload(visit["id"], spot["id"],
                                          occupy_start_utc="2026-06-20T08:00:00.000Z",
                                          occupy_end_utc="2026-06-23T08:00:00.000Z"), OPS))
    occupied = get_success_data(api.occupy_parking_assignment(
        assignment["id"], occupy_payload(assignment["version"]), OPS))
    assert occupied["fee_cents"] == 45000, (
        f"RAMP fee at 199 gallons (below 200) should be the full 45000, got {occupied['fee_cents']}"
    )


# ─── combinatorial_formula / fuel_marginal_cross_tier ─────────────────
def test_marginal_pricing_within_single_tier1():
    """PRD §3.2: "A gallon whose cumulative index is below 5,000 receives no discount"
    PRD §3.2: "The order's `priced_amount_cents` is the sum of those per-gallon prices"

    A 100-gal order at cumulative 0 stays entirely within tier 1: 100 * 520 = 52,000
    cents — the marginal sum with no tier crossing.

    Design: Difficulty/combinatorial_formula/fuel_marginal_cross_tier
    """
    operator, aircraft, contract = setup_operator_aircraft_contract()
    visit = setup_on_ground_visit(operator["id"], aircraft["id"])
    order = create_requested_fuel_order(visit["id"], aircraft["id"], contract["id"],
                                        ordered_gallons=100, tankering=False)
    dispatched = get_success_data(api.dispatch_fuel_order(order["id"], FUEL))
    assert dispatched["priced_amount_cents"] == 52_000, (
        f"100-gal tier-1 order should price 52000, got {dispatched['priced_amount_cents']}"
    )


# ─── combinatorial_formula / deice_pinned_rounding_order ──────────────
def test_deice_type_i_with_surcharge():
    """PRD §3.8: "The fluid base term is `deice_fluid_gallons` multiplied by 1,800 cents
    per gallon, multiplied by a dilution factor of 1.0 for `TYPE_I` fluid or 1.4 for
    `TYPE_IV` fluid. The holdover surcharge is the holdover minutes beyond a 15-minute
    free allowance — that is, the larger of zero and `deice_holdover_minutes` minus 15 —
    multiplied by 400 cents per minute."

    30 gal TYPE_I (dilution 1.0) with 20 min holdover: base 30*1800*1.0 = 54,000;
    surcharge (20-15)*400 = 2,000; total 56,000 cents.

    Design: Difficulty/combinatorial_formula/deice_pinned_rounding_order
    """
    operator, aircraft, _contract = setup_operator_aircraft_contract()
    visit, _spot, _assignment = setup_servicing_visit(
        operator["id"], aircraft["id"], spot_overrides={"label": "TD-9"})
    service = get_success_data(api.create_ramp_service(
        create_deice_service_payload(visit["id"], deice_fluid_gallons=30,
                                     deice_fluid_type="TYPE_I", deice_holdover_minutes=20), OPS))
    get_success_data(api.start_ramp_service(service["id"], LINE))
    completed = get_success_data(api.complete_ramp_service(service["id"], LINE))
    assert completed["charge_cents"] == 56000, (
        f"30 gal TYPE_I with 20 min holdover should charge 56000, got {completed['charge_cents']}"
    )


# ─── non_linear_state_machine / fuel_order_parallel_axes_independent ──
def test_flagged_reconciliation_leaves_logistics_axis_fueled():
    """PRD §3.6: "A **FuelOrder** carries two independent state stories on the same row,
    and they evolve separately."
    PRD §3.6: "Posting a ticket whose outcome is `FLAGGED` under the same preconditions
    instead advances the axis `NOT_STARTED → IN_REVIEW`, creating the ticket with
    `outcome` of `FLAGGED`."

    Posting a FLAGGED ticket moves the reconciliation axis to IN_REVIEW while the
    logistics axis remains FUELED — the two axes evolve independently.

    Design: Difficulty/non_linear_state_machine/fuel_order_parallel_axes_independent
    """
    operator, aircraft, contract = setup_operator_aircraft_contract()
    visit = setup_on_ground_visit(operator["id"], aircraft["id"])
    order = create_fueled_fuel_order(visit["id"], aircraft["id"], contract["id"],
                                     ordered_gallons=6000, tankering=False)
    post_into_plane_ticket(order["id"], 6300)  # +5.00% → FLAGGED
    after = get_success_data(api.get_fuel_order(order["id"], FUEL))
    assert after["logistics_status"] == "FUELED"
    assert after["reconciliation_status"] == "IN_REVIEW"


# ─── non_linear_state_machine / ramp_slot_revoke_re_request_cycle ─────
def test_re_requested_slot_can_be_approved_again():
    """PRD §3.9: "A revoked slot can be **re-requested** — moving it `REVOKED → REQUESTED`"
    PRD §3.9: "A dispatcher **approves** a slot, moving it `REQUESTED → APPROVED`, only
    while the slot is `REQUESTED`"

    After the cycle returns the slot to REQUESTED, it can be approved again — closing the
    REQUESTED→APPROVED→REVOKED→REQUESTED→APPROVED loop.

    Design: Difficulty/non_linear_state_machine/ramp_slot_revoke_re_request_cycle
    """
    operator, aircraft, _contract = setup_operator_aircraft_contract()
    visit, pad, slot = setup_revoked_slot(operator["id"], aircraft["id"])
    re_requested = validate_success(
        api.re_request_ramp_slot(slot["id"], make_operator_headers(operator["id"])), 200)
    assert re_requested["status"] == "REQUESTED"
    re_approved = validate_success(api.approve_ramp_slot(slot["id"], OPS), 200)
    assert re_approved["status"] == "APPROVED", "re-requested slot must be approvable again"


# ─── transitive_cascade / visit_cancel_cascade_depth3 ─────────────────
def test_visit_cancel_also_revokes_approved_ramp_slot():
    """PRD §3.3: "Cancelling an `ON_GROUND` visit is permitted only when no fuel order on
    the visit has reached `FUELED`; it moves the visit `ON_GROUND → CANCELLED` and runs a
    deeper cascade: every non-terminal parking assignment is released to `RELEASED` and
    each released assignment frees its spot's occupation window so it no longer blocks
    overlap checks; every non-terminal ramp service is cancelled to `CANCELLED`; and every
    ramp slot in `REQUESTED` or `APPROVED` status is revoked to `REVOKED`."

    Cancelling an ON_GROUND visit revokes its APPROVED ramp slot to REVOKED (a second
    hop of the cancel cascade, distinct from the parking release).

    Design: Difficulty/transitive_cascade/visit_cancel_cascade_depth3
    """
    operator, aircraft, _contract = setup_operator_aircraft_contract()
    visit = setup_on_ground_visit(operator["id"], aircraft["id"])
    pad = get_success_data(api.create_parking_spot(
        {"label": "PAD-CX", "spot_type": "RAMP", "max_weight_class": "HEAVY"}, OPS))
    slot = get_success_data(api.create_ramp_slot(
        create_ramp_slot_payload(visit["id"], pad["id"],
                                 "2026-06-14T10:00:00.000Z", "2026-06-14T11:00:00.000Z"), OPS))
    get_success_data(api.approve_ramp_slot(slot["id"], OPS))

    get_success_data(api.cancel_service_visit(visit["id"], OPS))
    slot_after = get_success_data(api.get_ramp_slot(slot["id"], OPS))
    assert slot_after["status"] == "REVOKED", "cancel cascade must revoke the APPROVED slot"


# ─── transitive_cascade / adjust_billing_cascade_depth3 ───────────────
def test_adjust_billing_reprices_downward_on_under_delivery():
    """PRD §3.6: "The system re-runs the fuel-pricing engine using the ticket's
    `delivered_gallons` in place of the ordered figure and overwrites the order's
    `priced_amount_cents`; then, if the order's parent visit already has an `ISSUED`
    invoice, that invoice's `total_cents` is recomputed; then the owning operator's
    `open_invoice_balance_cents` is recomputed."

    An under-delivery (5760 gal, -4.00% → IN_REVIEW) re-prices the order downward from
    3,115,000 to 2,991,400 (5000@520 + 760@515), cascading to the invoice and balance.

    Design: Difficulty/transitive_cascade/adjust_billing_cascade_depth3
    """
    operator, aircraft, contract, visit, order, invoice = setup_departed_visit_with_invoice(
        order_overrides={"ordered_gallons": 6000, "tankering": False},
        ticket_delivered=5760,
    )
    assert order["reconciliation_status"] == "IN_REVIEW"
    adjusted = get_success_data(api.adjust_billing_fuel_order(order["id"], BILLING))
    assert adjusted["priced_amount_cents"] == 2_991_400
    invoice_after = get_invoice_for_visit(visit["id"])
    assert invoice_after["total_cents"] == 2_991_400
    operator_after = get_success_data(api.get_operator(operator["id"], BILLING))
    assert operator_after["open_invoice_balance_cents"] == 2_991_400


# ─── priority_pair_validation_conflict / state_beats_business_referential_on_dispatch ──
def test_dispatch_on_dispatched_order_with_expired_contract_returns_invalid_state():
    """PRD §3.10: "State eligibility for the requested transition comes next with
    `ERR_INVALID_STATE`."
    PRD §3.6: "Dispatch is permitted only while `logistics_status` is `REQUESTED`, only
    while the parent visit is `ON_GROUND` or `SERVICING`, and only while the chosen
    contract is `ACTIVE` — a dispatch against an `EXPIRED` contract is rejected with
    `ERR_CONTRACT_EXPIRED` (HTTP 422)."

    Re-dispatching an already-DISPATCHED order whose contract was then expired still
    surfaces ERR_INVALID_STATE — state is checked before the contract business rule.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_referential_on_dispatch
    """
    operator, aircraft, contract = setup_operator_aircraft_contract()
    visit = setup_on_ground_visit(operator["id"], aircraft["id"])
    order = create_dispatched_fuel_order(visit["id"], aircraft["id"], contract["id"],
                                         ordered_gallons=6000, tankering=False)
    get_success_data(api.expire_fuel_contract(contract["id"], BILLING))
    res = api.dispatch_fuel_order(order["id"], FUEL)
    validate_error(res, "ERR_INVALID_STATE")


# ─── priority_pair_validation_conflict / existence_beats_state_on_occupy ──
def test_occupy_nonexistent_assignment_not_stale_version():
    """PRD §2.5: "the first reference that does not resolve to an existing resource causes
    the whole request to be rejected with `ERR_NOT_FOUND` (HTTP 404) before any business
    rule is evaluated."
    PRD §3.10: "Existence of every path identifier and body foreign key, resolved left to
    right, comes next with `ERR_NOT_FOUND`. State eligibility for the requested
    transition comes next with `ERR_INVALID_STATE`."

    Occupy on a non-existent assignment id resolves to ERR_NOT_FOUND rather than any
    later state or concurrency error, proving existence is checked before them.

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_occupy
    """
    setup_operator_aircraft_contract()
    res = api.occupy_parking_assignment(NON_EXISTENT_UUID, {"expected_assignment_version": 99}, OPS)
    validate_error(res, "ERR_NOT_FOUND")


# ─── boundary_precision_check / reconciliation_tolerance_exactly_two_pct ──
def test_reconciliation_tolerance_negative_two_pct_reconciles():
    """PRD §3.6: "The ticket's `outcome` is `RECONCILED` when the absolute value of
    `variance_pct` is at most 2.00 — exactly 2.00 still reconciles — and `FLAGGED`
    otherwise."

    5880 delivered vs 6000 ordered = -120 gal = -2.00% (absolute value exactly 2.00) →
    still RECONCILED, exercising the negative side of the tolerance band.

    Design: Difficulty/boundary_precision_check/reconciliation_tolerance_exactly_two_pct
    """
    operator, aircraft, contract = setup_operator_aircraft_contract()
    visit = setup_on_ground_visit(operator["id"], aircraft["id"])
    order = create_fueled_fuel_order(visit["id"], aircraft["id"], contract["id"],
                                     ordered_gallons=6000, tankering=False)
    ticket = post_into_plane_ticket(order["id"], 5880)
    assert ticket["variance_pct"] == pytest.approx(-2.0, abs=1e-9)
    assert ticket["outcome"] == "RECONCILED"
    after = get_success_data(api.get_fuel_order(order["id"], FUEL))
    assert after["reconciliation_status"] == "RECONCILED"


# ─── boundary_precision_check / fuel_tier_boundary_at_five_thousand_gallons ──
def test_tier_boundary_one_gallon_at_exactly_five_thousand_is_tier2():
    """PRD §3.2: "a gallon whose cumulative index is at least 5,000 but below 20,000 is
    discounted by 5 cents"

    With cumulative exactly 5000, a 1-gal order prices gallon index 5000 at base 520 - 5
    = 515 cents (tier 2 applies at index >= 5000).

    Design: Difficulty/boundary_precision_check/fuel_tier_boundary_at_five_thousand_gallons
    """
    operator, aircraft, contract = setup_operator_aircraft_contract()
    v1 = setup_on_ground_visit(operator["id"], aircraft["id"])
    create_fueled_fuel_order(v1["id"], aircraft["id"], contract["id"],
                             ordered_gallons=5000, tankering=False)
    operator_after = get_success_data(api.get_operator(operator["id"], BILLING))
    assert operator_after["jeta_month_cumulative_gallons"] == 5000

    v2 = setup_on_ground_visit(operator["id"], aircraft["id"],
                               visit_overrides={"arrival_utc": "2026-06-16T08:00:00.000Z",
                                                "departure_utc": "2026-06-17T08:00:00.000Z"})
    order2 = create_requested_fuel_order(v2["id"], aircraft["id"], contract["id"],
                                         ordered_gallons=1, tankering=False)
    dispatched2 = get_success_data(api.dispatch_fuel_order(order2["id"], FUEL))
    assert dispatched2["priced_amount_cents"] == 515, (
        f"1-gal order at cumulative index 5000 should price 515 (tier2), "
        f"got {dispatched2['priced_amount_cents']}"
    )


# ─── cross_entity_state_dependency / fuel_dispatch_requires_visit_on_ground ──
def test_dispatch_succeeds_when_parent_visit_servicing():
    """PRD §3.6: "Dispatch is permitted only while `logistics_status` is `REQUESTED`,
    only while the parent visit is `ON_GROUND` or `SERVICING`, and only while the chosen
    contract is `ACTIVE`"

    Positive control for the parent-state gate: with the parent visit advanced to
    SERVICING, dispatch is permitted and the order moves to DISPATCHED.

    Design: Difficulty/cross_entity_state_dependency/fuel_dispatch_requires_visit_on_ground
    """
    operator, aircraft, contract = setup_operator_aircraft_contract()
    visit, _spot, _assignment = setup_servicing_visit(
        operator["id"], aircraft["id"], spot_overrides={"label": "TD-SV"})
    order = create_requested_fuel_order(visit["id"], aircraft["id"], contract["id"],
                                        ordered_gallons=6000, tankering=False)
    dispatched = validate_success(api.dispatch_fuel_order(order["id"], FUEL), 200)
    assert dispatched["logistics_status"] == "DISPATCHED"


# ─── cross_entity_state_dependency / visit_mark_ready_requires_children_settled ──
def test_mark_ready_blocked_while_fuel_order_dispatched():
    """PRD §3.3: "Marking the stay ready moves it `SERVICING → READY_FOR_DEPARTURE` only
    when the visit is settled: `services_outstanding` must be 0 (every ramp service
    `COMPLETED` or `CANCELLED`) and no fuel order on the visit may still be in `REQUESTED`
    or `DISPATCHED` logistics status."

    A SERVICING visit whose fuel order is still DISPATCHED (not yet FUELED) cannot be
    marked ready; the request is rejected and the visit stays SERVICING.

    Design: Difficulty/cross_entity_state_dependency/visit_mark_ready_requires_children_settled
    """
    operator, aircraft, contract = setup_operator_aircraft_contract()
    visit, _spot, _assignment = setup_servicing_visit(
        operator["id"], aircraft["id"], spot_overrides={"label": "TD-MR"})
    create_dispatched_fuel_order(visit["id"], aircraft["id"], contract["id"],
                                 ordered_gallons=6000, tankering=False)
    res = api.mark_ready_service_visit(visit["id"], OPS)
    validate_error(res, "ERR_INVALID_STATE")
    after = get_success_data(api.get_service_visit(visit["id"], OPS))
    assert after["status"] == "SERVICING"


# ─── resource_temporal_overlap / hangar_tow_buffer_blocks_adjacency ───
def test_hangar_well_separated_window_allowed():
    """PRD §3.4: "For a `HANGAR` spot, the assignment's interval is widened by a
    30-minute tow buffer at each side, and if that buffered window collides with any
    already-`OCCUPIED` assignment's window on the same spot (a closed, buffer-inclusive
    overlap), the request is rejected with `ERR_SPOT_TOW_BUFFER_CONFLICT` (HTTP 409)."

    On a HANGAR spot, a second occupation hours away ([14:00,15:00) after [10:00,11:00))
    is well clear of the 30-minute buffer and is allowed to occupy.

    Design: Difficulty/resource_temporal_overlap/hangar_tow_buffer_blocks_adjacency
    """
    operator, aircraft, _contract = setup_operator_aircraft_contract()
    spot = get_success_data(api.create_parking_spot(
        {"label": "H-2", "spot_type": "HANGAR", "max_weight_class": "HEAVY"}, OPS))
    v1 = setup_on_ground_visit(operator["id"], aircraft["id"])
    pa1 = get_success_data(api.create_parking_assignment(
        create_parking_assignment_payload(v1["id"], spot["id"],
                                          occupy_start_utc="2026-06-14T10:00:00.000Z",
                                          occupy_end_utc="2026-06-14T11:00:00.000Z"), OPS))
    get_success_data(api.occupy_parking_assignment(pa1["id"], occupy_payload(pa1["version"]), OPS))

    v2 = setup_on_ground_visit(operator["id"], aircraft["id"],
                               visit_overrides={"arrival_utc": "2026-06-14T09:00:00.000Z",
                                                "departure_utc": "2026-06-15T09:00:00.000Z"})
    pa2 = get_success_data(api.create_parking_assignment(
        create_parking_assignment_payload(v2["id"], spot["id"],
                                          occupy_start_utc="2026-06-14T14:00:00.000Z",
                                          occupy_end_utc="2026-06-14T15:00:00.000Z"), OPS))
    occupied2 = validate_success(api.occupy_parking_assignment(pa2["id"], occupy_payload(pa2["version"]), OPS), 200)
    assert occupied2["status"] == "OCCUPIED", "well-separated hangar window must be allowed"


# ─── resource_temporal_overlap / ramp_slot_half_open_allows_adjacency ──
def test_ramp_slot_true_overlap_rejected():
    """PRD §3.9: "only when no other `APPROVED` slot on the same `pad_id`
    half-open-overlaps this window — adjacency, where one window ends exactly as another
    begins, is allowed, but a true overlap is rejected with `ERR_SLOT_OVERLAP`
    (HTTP 409)."

    On a RAMP pad with an APPROVED [10:00,11:00) slot, a truly overlapping [10:30,11:30)
    slot is rejected with ERR_SLOT_OVERLAP and stays REQUESTED.

    Design: Difficulty/resource_temporal_overlap/ramp_slot_half_open_allows_adjacency
    """
    operator, aircraft, _contract = setup_operator_aircraft_contract()
    pad = get_success_data(api.create_parking_spot(
        {"label": "PAD-OV", "spot_type": "RAMP", "max_weight_class": "HEAVY"}, OPS))
    visit = get_success_data(api.create_service_visit(
        {"operator_id": operator["id"], "aircraft_id": aircraft["id"],
         "arrival_utc": "2026-06-14T08:00:00.000Z", "departure_utc": "2026-06-15T08:00:00.000Z"}, OPS))
    s1 = get_success_data(api.create_ramp_slot(
        create_ramp_slot_payload(visit["id"], pad["id"],
                                 "2026-06-14T10:00:00.000Z", "2026-06-14T11:00:00.000Z"), OPS))
    get_success_data(api.approve_ramp_slot(s1["id"], OPS))
    s2 = get_success_data(api.create_ramp_slot(
        create_ramp_slot_payload(visit["id"], pad["id"],
                                 "2026-06-14T10:30:00.000Z", "2026-06-14T11:30:00.000Z"), OPS))
    res = api.approve_ramp_slot(s2["id"], OPS)
    validate_error(res, "ERR_SLOT_OVERLAP")
    s2_after = get_success_data(api.get_ramp_slot(s2["id"], OPS))
    assert s2_after["status"] == "REQUESTED"


# ─── compensating_invariant / adjust_billing_conserves_invoice_total_equals_lines ──
def test_invoice_equals_line_sum_after_under_delivery_adjust():
    """PRD §3.6: "This three-step cascade conserves the invariant that an invoice always
    equals the sum of its current billable lines."
    PRD §3.7: "every fuel order on the visit whose `logistics_status` is not `CANCELLED`
    contributes its `priced_amount_cents`"

    After an under-delivery adjust re-prices the sole fuel line to 2,991,400, the invoice
    total equals exactly that live line — the invariant holds on the downward path too.

    Design: Difficulty/compensating_invariant/adjust_billing_conserves_invoice_total_equals_lines
    """
    operator, aircraft, contract, visit, order, invoice = setup_departed_visit_with_invoice(
        order_overrides={"ordered_gallons": 6000, "tankering": False},
        ticket_delivered=5760,
    )
    get_success_data(api.adjust_billing_fuel_order(order["id"], BILLING))
    order_after = get_success_data(api.get_fuel_order(order["id"], FUEL))
    invoice_after = get_invoice_for_visit(visit["id"])
    assert invoice_after["total_cents"] == 2_991_400
    assert invoice_after["total_cents"] == order_after["priced_amount_cents"]


# ─── compensating_invariant / void_conserves_operator_open_balance ────
def test_void_returns_invoice_status_void_and_zeroes_balance():
    """PRD §3.7: "A `LineManager` may **void** an `ISSUED` invoice, moving it
    `ISSUED → VOID` and recomputing the operator's `open_invoice_balance_cents` so the
    voided invoice drops out of the balance."

    Voiding the sole ISSUED invoice both sets its status to VOID and recomputes the
    operator's open balance down to 0.

    Design: Difficulty/compensating_invariant/void_conserves_operator_open_balance
    """
    operator, aircraft, contract, visit, order, invoice = setup_departed_visit_with_invoice(
        order_overrides={"ordered_gallons": 6000, "tankering": True},
    )
    voided = get_success_data(api.void_invoice(invoice["id"], LINE))
    assert voided["status"] == "VOID"
    operator_after = get_success_data(api.get_operator(operator["id"], BILLING))
    assert operator_after["open_invoice_balance_cents"] == 0
