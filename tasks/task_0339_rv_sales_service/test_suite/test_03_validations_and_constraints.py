"""Validation precedence pairs, numeric/interval boundary precision, cross-entity
state dependencies, bay/storage temporal overlap, and compensating invariants.

Covers the priority_pair_validation_conflict, boundary_precision_check,
cross_entity_state_dependency, resource_temporal_overlap, and
compensating_invariant difficulty rules plus the validation corner instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    api_client,
    ApiErrorId,
    TEST_USERS,
    setup_held_deal,
    setup_quoted_deal,
    setup_deal_in_walkthrough,
    setup_dealership_customer_unit,
    setup_started_service_order,
    setup_finance_requested_deal,
    setup_warranty_so_in_progress,
    create_deal_on_unit,
    create_part_item,
    create_service_bay,
    create_recall_campaign,
    create_customer,
    create_unit,
    create_warranty_plan,
    reserve_part,
    book_storage_slot,
    create_appointment_payload,
    create_pdi_inspection_payload,
)

SALES = TEST_USERS["sales_agent_headers"]
MGR = TEST_USERS["dealer_manager_headers"]
SVC = TEST_USERS["service_advisor_headers"]


# ===========================================================================
# Difficulty: priority_pair_validation_conflict / stop_sale_recall_beats_state_on_deliver
# ===========================================================================
def test_stop_sale_recall_blocks_deliver_in_walkthrough(api):
    """PRD §3.5: "Delivery is further gated by recall safety: if the unit falls
    under an open `STOP_SALE` recall campaign with a remedy that is not yet
    `CLEARED`, delivery is blocked with `ERR_STOP_SALE_RECALL_OPEN`."

    Deal in WALKTHROUGH (state legal) but unit under a STOP_SALE recall -> the
    safety error surfaces, not the state error.

    Design: Difficulty/priority_pair_validation_conflict/stop_sale_recall_beats_state_on_deliver
    """
    dealer, customer, unit, walk = setup_deal_in_walkthrough(
        unit_overrides={"list_price_cents": 7000000}, sale_price_cents=7000000
    )
    create_recall_campaign(
        dealer["id"], target_class_type="CLASS_C", target_model_year=2024, severity="STOP_SALE"
    )
    resp = api.deliver_deal(walk["id"], SALES)
    validate_error(resp, ApiErrorId.ERR_STOP_SALE_RECALL_OPEN.value)


def test_stop_sale_recall_leaves_deal_in_walkthrough(api):
    """PRD §3.5: "Delivery requires `sale_status` to be `WALKTHROUGH` ... Delivery
    is further gated by recall safety: if the unit falls under an open `STOP_SALE`
    recall campaign with a remedy that is not yet `CLEARED`, delivery is blocked
    with `ERR_STOP_SALE_RECALL_OPEN`."

    The rejected deliver leaves the deal in WALKTHROUGH (unchanged).

    Design: Difficulty/priority_pair_validation_conflict/stop_sale_recall_beats_state_on_deliver
    """
    dealer, customer, unit, walk = setup_deal_in_walkthrough(
        unit_overrides={"list_price_cents": 7000000}, sale_price_cents=7000000
    )
    create_recall_campaign(
        dealer["id"], target_class_type="CLASS_C", target_model_year=2024, severity="STOP_SALE"
    )
    api.deliver_deal(walk["id"], SALES)
    deal_after = validate_success(api.get_deal(walk["id"], SALES))
    assert deal_after["sale_status"] == "WALKTHROUGH", deal_after["sale_status"]


# ===========================================================================
# Difficulty: priority_pair_validation_conflict / insufficient_parts_beats_invalid_request_on_reserve
# ===========================================================================
def test_insufficient_parts_surfaces_capacity_error(api):
    """PRD §3.7: "The reservation quantity must not exceed the part's current
    `qty_available`; a shortfall is rejected with `ERR_INSUFFICIENT_PARTS`."

    qty_on_hand 2, reserve 5 (well-formed otherwise) -> the capacity error surfaces.

    Design: Difficulty/priority_pair_validation_conflict/insufficient_parts_beats_invalid_request_on_reserve
    """
    dealer, customer, unit, so = setup_started_service_order()
    part = create_part_item(dealer["id"], unit_price_cents=30000, qty_on_hand=2)
    resp = api.create_part_reservation(
        {"service_order_id": so["id"], "part_item_id": part["id"], "quantity": 5}, SVC
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PARTS.value)


def test_insufficient_parts_leaves_no_reservation_side_effect(api):
    """PRD §3.7: "A successful reservation opens in `RESERVED` status, snapshots
    the part's price into the reservation's `unit_price_cents`, and as a cascade
    raises the part's `qty_reserved` by the reserved quantity and recomputes its
    `qty_available`."

    A rejected over-reservation must not move qty_reserved (stays 0).

    Design: Difficulty/priority_pair_validation_conflict/insufficient_parts_beats_invalid_request_on_reserve
    """
    dealer, customer, unit, so = setup_started_service_order()
    part = create_part_item(dealer["id"], unit_price_cents=30000, qty_on_hand=2)
    api.create_part_reservation(
        {"service_order_id": so["id"], "part_item_id": part["id"], "quantity": 5}, SVC
    )
    part_after = validate_success(api.get_part_item(part["id"], SVC))
    assert part_after["qty_reserved"] == 0, part_after["qty_reserved"]


# ===========================================================================
# Difficulty: boundary_precision_check / ltv_band_boundary_exact_max_passes
# ===========================================================================
def test_ltv_at_exact_band_ceiling_is_approved(api):
    """PRD §3.4: "it must be less than or equal to the maximum permitted for the
    customer's credit tier, where the ceilings are 13000 basis points (130%) for
    `PRIME`, 12000 basis points (120%) for `STANDARD`, and 11000 basis points
    (110%) for `SUBPRIME`, and the comparison is inclusive at the ceiling."

    STANDARD ceiling 12000; financed 7200000 / list 6000000 = exactly 12000bps -> approved.

    Design: Difficulty/boundary_precision_check/ltv_band_boundary_exact_max_passes
    """
    dealer, customer, unit, deal_id = setup_finance_requested_deal(
        credit_tier="STANDARD", list_price_cents=6000000, sale_price_cents=7200000,
        term_months=60, down_payment_cents=0,
    )
    approved = validate_success(api.finance_decision(deal_id, {"decision": "APPROVE"}, MGR))
    assert approved["finance_status"] == "APPROVED", approved["finance_status"]


def test_ltv_boundary_amount_financed_is_exact(api):
    """PRD §3.4: "The loan-to-value, expressed in basis points, is the
    `amount_financed_cents` multiplied by ten thousand and divided by the unit's
    `list_price_cents`".

    No tax/doc/down: amount_financed == sale 7200000, giving ltv 12000bps exactly.

    Design: Difficulty/boundary_precision_check/ltv_band_boundary_exact_max_passes
    """
    dealer, customer, unit, deal_id = setup_finance_requested_deal(
        credit_tier="STANDARD", list_price_cents=6000000, sale_price_cents=7200000,
        term_months=60, down_payment_cents=0,
    )
    deal = validate_success(api.get_deal(deal_id, SALES))
    assert deal["amount_financed_cents"] == 7200000, deal["amount_financed_cents"]


# ===========================================================================
# Difficulty: boundary_precision_check / storage_zero_overlap_adjacent_intervals_allowed
# ===========================================================================
def test_adjacent_storage_slots_share_boundary_allowed(api):
    """PRD §2.10: "a new StorageSlot is rejected with `ERR_STORAGE_OVERLAP` if its
    `start_utc`-to-`end_utc` interval overlaps any other non-cancelled storage slot
    for the same unit, where a slot ending exactly when another begins does not
    count as an overlap."

    Slot A [06-01,06-05); slot B [06-05,06-10) for the same unit is accepted.

    Design: Difficulty/boundary_precision_check/storage_zero_overlap_adjacent_intervals_allowed
    """
    dealer, customer, unit = setup_dealership_customer_unit(
        unit_overrides={"class_type": "FIFTH_WHEEL", "list_price_cents": 5000000}
    )
    book_storage_slot(
        dealer, unit, customer, "2026-06-01T00:00:00.000Z", "2026-06-05T00:00:00.000Z",
        unit["version"], daily_rate_cents=5000,
    )
    unit_v1 = validate_success(api.get_unit(unit["id"], SVC))["version"]
    slot_b = validate_success(
        api.create_storage_slot(
            {
                "dealership_id": dealer["id"], "unit_id": unit["id"], "customer_id": customer["id"],
                "daily_rate_cents": 5000, "start_utc": "2026-06-05T00:00:00.000Z",
                "end_utc": "2026-06-10T00:00:00.000Z", "expected_unit_version": unit_v1,
            },
            SVC,
        ),
        expected_status=201,
    )
    assert slot_b["status"] == "BOOKED", slot_b["status"]


def test_two_storage_slots_coexist_for_unit(api):
    """PRD §2.10: "a slot ending exactly when another begins does not count as an
    overlap."

    After booking adjacent slots A and B, both non-cancelled slots exist for the unit.

    Design: Difficulty/boundary_precision_check/storage_zero_overlap_adjacent_intervals_allowed
    """
    dealer, customer, unit = setup_dealership_customer_unit(
        unit_overrides={"class_type": "FIFTH_WHEEL", "list_price_cents": 5000000}
    )
    book_storage_slot(
        dealer, unit, customer, "2026-06-01T00:00:00.000Z", "2026-06-05T00:00:00.000Z",
        unit["version"], daily_rate_cents=5000,
    )
    unit_v1 = validate_success(api.get_unit(unit["id"], SVC))["version"]
    get_success_data(
        api_client.create_storage_slot(
            {
                "dealership_id": dealer["id"], "unit_id": unit["id"], "customer_id": customer["id"],
                "daily_rate_cents": 5000, "start_utc": "2026-06-05T00:00:00.000Z",
                "end_utc": "2026-06-10T00:00:00.000Z", "expected_unit_version": unit_v1,
            },
            SVC,
        )
    )
    listing = validate_success(api.list_storage_slots(SVC, params={"unit_id": unit["id"]}))
    assert len(listing) == 2, listing


# ===========================================================================
# Difficulty: cross_entity_state_dependency / deliver_requires_unit_not_stop_sale_recalled
# ===========================================================================
def test_deliver_gated_by_sibling_unit_recall_posture(api):
    """PRD §3.5: "Delivery is further gated by recall safety: if the unit falls
    under an open `STOP_SALE` recall campaign with a remedy that is not yet
    `CLEARED`, delivery is blocked with `ERR_STOP_SALE_RECALL_OPEN`."

    The deal's WALKTHROUGH->DELIVERED move depends on the referenced Unit's recall posture.

    Design: Difficulty/cross_entity_state_dependency/deliver_requires_unit_not_stop_sale_recalled
    """
    dealer, customer, unit, walk = setup_deal_in_walkthrough(
        unit_overrides={"list_price_cents": 7000000}, sale_price_cents=7000000
    )
    create_recall_campaign(
        dealer["id"], target_class_type="CLASS_C", target_model_year=2024, severity="STOP_SALE"
    )
    resp = api.deliver_deal(walk["id"], MGR)
    validate_error(resp, ApiErrorId.ERR_STOP_SALE_RECALL_OPEN.value)


def test_recalled_unit_stays_held_after_blocked_deliver(api):
    """PRD §3.2: "A unit's recall exposure is tracked by `open_recall_count`, the
    number of remedies on the unit that are not yet `CLEARED` for a campaign that
    is still `OPEN`."
    PRD §3.5: "When all gates pass, delivery advances `sale_status` from
    `WALKTHROUGH` to the terminal `DELIVERED`, cascades the unit from `HELD` to
    `SOLD`".

    Blocked deliver: unit keeps open_recall_count 1 and stays HELD (not SOLD).

    Design: Difficulty/cross_entity_state_dependency/deliver_requires_unit_not_stop_sale_recalled
    """
    dealer, customer, unit, walk = setup_deal_in_walkthrough(
        unit_overrides={"list_price_cents": 7000000}, sale_price_cents=7000000
    )
    create_recall_campaign(
        dealer["id"], target_class_type="CLASS_C", target_model_year=2024, severity="STOP_SALE"
    )
    api.deliver_deal(walk["id"], MGR)
    unit_after = validate_success(api.get_unit(unit["id"], MGR))
    assert unit_after["open_recall_count"] == 1, unit_after["open_recall_count"]
    assert unit_after["status"] == "HELD", unit_after["status"]


# ===========================================================================
# Difficulty: cross_entity_state_dependency / start_pdi_requires_finance_settled
# ===========================================================================
def test_start_pdi_rejected_when_finance_not_settled(api):
    """PRD §3.5: "Moving a deal into pre-delivery inspection requires `sale_status`
    to be `QUOTED` (otherwise `ERR_DEAL_BAD_SALE_STATE`) and requires the financing
    to be settled — that is, `finance_status` must be either `CASH` or `APPROVED`;
    a deal whose financing is not settled is rejected with
    `ERR_FINANCE_NOT_SETTLED`."

    Finance REQUESTED (not settled) -> start-pdi rejected.

    Design: Difficulty/cross_entity_state_dependency/start_pdi_requires_finance_settled
    """
    dealer, customer, unit, deal = setup_held_deal(
        customer_overrides={"credit_tier": "STANDARD"},
        unit_overrides={"list_price_cents": 7000000},
        sale_price_cents=6000000,
        down_payment_cents=0,
        term_months=72,
    )
    get_success_data(api_client.quote_deal(deal["id"], SALES))
    get_success_data(api_client.request_finance(deal["id"], SALES))
    resp = api.start_pdi(deal["id"], SALES)
    validate_error(resp, ApiErrorId.ERR_FINANCE_NOT_SETTLED.value)


def test_start_pdi_rejected_leaves_deal_quoted(api):
    """PRD §3.5: "Starting pre-delivery inspection advances `sale_status` from
    `QUOTED` to `PDI_PENDING`."

    The rejected start-pdi leaves the deal in QUOTED on the sale axis.

    Design: Difficulty/cross_entity_state_dependency/start_pdi_requires_finance_settled
    """
    dealer, customer, unit, deal = setup_held_deal(
        customer_overrides={"credit_tier": "STANDARD"},
        unit_overrides={"list_price_cents": 7000000},
        sale_price_cents=6000000,
        down_payment_cents=0,
        term_months=72,
    )
    get_success_data(api_client.quote_deal(deal["id"], SALES))
    get_success_data(api_client.request_finance(deal["id"], SALES))
    api.start_pdi(deal["id"], SALES)
    deal_after = validate_success(api.get_deal(deal["id"], SALES))
    assert deal_after["sale_status"] == "QUOTED", deal_after["sale_status"]


# ===========================================================================
# Difficulty: resource_temporal_overlap / bay_overlap_with_cleanup_buffer
# ===========================================================================
def _bay_setup():
    dealer, customer, unit = setup_dealership_customer_unit()
    bay = create_service_bay(dealer["id"], name="Repair-1", bay_kind="REPAIR", cleanup_buffer_minutes=30)
    so1 = get_success_data(
        api_client.create_service_order(
            {"dealership_id": dealer["id"], "unit_id": unit["id"], "customer_id": customer["id"],
             "labor_hours": 1.0, "labor_rate_cents": 10000}, SVC
        )
    )
    so2 = get_success_data(
        api_client.create_service_order(
            {"dealership_id": dealer["id"], "unit_id": unit["id"], "customer_id": customer["id"],
             "labor_hours": 1.0, "labor_rate_cents": 10000}, SVC
        )
    )
    get_success_data(
        api_client.create_appointment(
            create_appointment_payload(
                dealer["id"], bay["id"], "REPAIR",
                "2026-06-01T10:00:00.000Z", "2026-06-01T11:00:00.000Z",
                service_order_id=so1["id"],
            ),
            SVC,
        )
    )
    return dealer, bay, so2


def test_bay_overlap_includes_trailing_cleanup_buffer(api):
    """PRD §2.10: "A new appointment is rejected with `ERR_BAY_DOUBLE_BOOKED` if
    its interval — taken together with the trailing cleanup buffer of any
    neighboring appointment — would overlap any other non-cancelled appointment on
    the same bay."

    Appt A [10:00,11:00) on a 30-min-buffer bay blocks until 11:30, so B at 11:15 is rejected.

    Design: Difficulty/resource_temporal_overlap/bay_overlap_with_cleanup_buffer
    """
    dealer, bay, so2 = _bay_setup()
    resp = api.create_appointment(
        create_appointment_payload(
            dealer["id"], bay["id"], "REPAIR",
            "2026-06-01T11:15:00.000Z", "2026-06-01T12:00:00.000Z",
            service_order_id=so2["id"],
        ),
        SVC,
    )
    validate_error(resp, ApiErrorId.ERR_BAY_DOUBLE_BOOKED.value)


def test_bay_overlap_rejection_creates_no_second_appointment(api):
    """PRD §3.9: "the slot is subject to the bay-overlap rule of §2.10, which folds
    in the bay's cleanup buffer and rejects collisions with
    `ERR_BAY_DOUBLE_BOOKED`. A new appointment opens in `SCHEDULED` status."

    The rejected appointment leaves only the original appointment on the bay.

    Design: Difficulty/resource_temporal_overlap/bay_overlap_with_cleanup_buffer
    """
    dealer, bay, so2 = _bay_setup()
    api.create_appointment(
        create_appointment_payload(
            dealer["id"], bay["id"], "REPAIR",
            "2026-06-01T11:15:00.000Z", "2026-06-01T12:00:00.000Z",
            service_order_id=so2["id"],
        ),
        SVC,
    )
    listing = validate_success(api.list_appointments(SVC, params={"service_bay_id": bay["id"]}))
    assert len(listing) == 1, listing


# ===========================================================================
# Difficulty: resource_temporal_overlap / storage_overlap_no_buffer_strict_intersection
# ===========================================================================
def test_storage_strict_intersection_rejected_no_buffer(api):
    """PRD §2.10: "Storage occupancy works on the same half-open principle but per
    unit and without any buffer: a new StorageSlot is rejected with
    `ERR_STORAGE_OVERLAP` if its `start_utc`-to-`end_utc` interval overlaps any
    other non-cancelled storage slot for the same unit".

    Slot A [06-01,06-10); slot B [06-05,06-08) strictly intersects -> rejected.

    Design: Difficulty/resource_temporal_overlap/storage_overlap_no_buffer_strict_intersection
    """
    dealer, customer, unit = setup_dealership_customer_unit(
        unit_overrides={"class_type": "TRAVEL_TRAILER", "list_price_cents": 4000000}
    )
    book_storage_slot(
        dealer, unit, customer, "2026-06-01T00:00:00.000Z", "2026-06-10T00:00:00.000Z",
        unit["version"], daily_rate_cents=5000,
    )
    unit_v1 = validate_success(api.get_unit(unit["id"], SVC))["version"]
    resp = api.create_storage_slot(
        {
            "dealership_id": dealer["id"], "unit_id": unit["id"], "customer_id": customer["id"],
            "daily_rate_cents": 5000, "start_utc": "2026-06-05T00:00:00.000Z",
            "end_utc": "2026-06-08T00:00:00.000Z", "expected_unit_version": unit_v1,
        },
        SVC,
    )
    validate_error(resp, ApiErrorId.ERR_STORAGE_OVERLAP.value)


def test_storage_overlap_rejection_keeps_single_slot(api):
    """PRD §2.10: "Storage occupancy works on the same half-open principle but per
    unit and without any buffer: a new StorageSlot is rejected with
    `ERR_STORAGE_OVERLAP` if its `start_utc`-to-`end_utc` interval overlaps any
    other non-cancelled storage slot for the same unit".

    The rejected overlapping slot leaves only slot A for the unit.

    Design: Difficulty/resource_temporal_overlap/storage_overlap_no_buffer_strict_intersection
    """
    dealer, customer, unit = setup_dealership_customer_unit(
        unit_overrides={"class_type": "TRAVEL_TRAILER", "list_price_cents": 4000000}
    )
    book_storage_slot(
        dealer, unit, customer, "2026-06-01T00:00:00.000Z", "2026-06-10T00:00:00.000Z",
        unit["version"], daily_rate_cents=5000,
    )
    unit_v1 = validate_success(api.get_unit(unit["id"], SVC))["version"]
    api.create_storage_slot(
        {
            "dealership_id": dealer["id"], "unit_id": unit["id"], "customer_id": customer["id"],
            "daily_rate_cents": 5000, "start_utc": "2026-06-05T00:00:00.000Z",
            "end_utc": "2026-06-08T00:00:00.000Z", "expected_unit_version": unit_v1,
        },
        SVC,
    )
    listing = validate_success(api.list_storage_slots(SVC, params={"unit_id": unit["id"]}))
    assert len(listing) == 1, listing


# ===========================================================================
# Difficulty: compensating_invariant / parts_conservation_reserve_then_cancel
# ===========================================================================
def test_parts_qty_on_hand_unchanged_after_reserve_then_cancel(api):
    """PRD §3.7: "Cancellation moves the order to the terminal `CANCELLED` and
    triggers two cascades: every `RESERVED` reservation for the order is moved to
    `RELEASED`, returning its quantity to stock by lowering each backing part's
    `qty_reserved` and recomputing `qty_available`".

    Reserve 4 of 10 then cancel: qty_on_hand stays 10 (no parts consumed).

    Design: Difficulty/compensating_invariant/parts_conservation_reserve_then_cancel
    """
    dealer, customer, unit, so = setup_started_service_order()
    part = create_part_item(dealer["id"], unit_price_cents=8000, qty_on_hand=10)
    reserve_part(so["id"], part["id"], 4)
    get_success_data(api_client.cancel_service_order(so["id"], SVC))
    part_after = validate_success(api.get_part_item(part["id"], SVC))
    assert part_after["qty_on_hand"] == 10, part_after["qty_on_hand"]


def test_parts_reserved_returns_to_zero_after_cancel(api):
    """PRD §2.8: "a PartItem's `qty_reserved` is the sum of quantities across that
    part's reservations still in `RESERVED` state, and its `qty_available` is its
    on-hand count minus that reserved figure and is never negative".

    After reserve-then-cancel, qty_reserved is back to 0 and qty_available == qty_on_hand.

    Design: Difficulty/compensating_invariant/parts_conservation_reserve_then_cancel
    """
    dealer, customer, unit, so = setup_started_service_order()
    part = create_part_item(dealer["id"], unit_price_cents=8000, qty_on_hand=10)
    reserve_part(so["id"], part["id"], 4)
    get_success_data(api_client.cancel_service_order(so["id"], SVC))
    part_after = validate_success(api.get_part_item(part["id"], SVC))
    assert part_after["qty_reserved"] == 0, part_after["qty_reserved"]
    assert part_after["qty_available"] == 10, part_after["qty_available"]


# ===========================================================================
# Difficulty: compensating_invariant / unit_availability_conservation_deal_create_then_cancel
# ===========================================================================
def test_unit_returns_available_after_deal_create_then_cancel(api):
    """PRD §3.2: "Releasing that hold by cancelling the deal carries the unit from
    `HELD` back to `AVAILABLE`, clears `active_hold_deal_id`, and again increments
    `version`; this release happens only for the deal that actually holds the
    unit."

    Create deal (AVAILABLE->HELD) then cancel (HELD->AVAILABLE): posture conserved.

    Design: Difficulty/compensating_invariant/unit_availability_conservation_deal_create_then_cancel
    """
    dealer, customer, unit, deal = setup_held_deal(
        unit_overrides={"list_price_cents": 7000000}, sale_price_cents=7000000
    )
    get_success_data(api_client.cancel_deal(deal["id"], SALES))
    unit_after = validate_success(api.get_unit(unit["id"], SALES))
    assert unit_after["status"] == "AVAILABLE", unit_after["status"]


def test_unit_active_hold_cleared_after_deal_cancel(api):
    """PRD §3.2: "Releasing that hold by cancelling the deal carries the unit from
    `HELD` back to `AVAILABLE`, clears `active_hold_deal_id`, and again increments
    `version`".

    active_hold_deal_id is null again after the paired create+cancel.

    Design: Difficulty/compensating_invariant/unit_availability_conservation_deal_create_then_cancel
    """
    dealer, customer, unit, deal = setup_held_deal(
        unit_overrides={"list_price_cents": 7000000}, sale_price_cents=7000000
    )
    get_success_data(api_client.cancel_deal(deal["id"], SALES))
    unit_after = validate_success(api.get_unit(unit["id"], SALES))
    assert unit_after["active_hold_deal_id"] in (None, ""), unit_after["active_hold_deal_id"]


# ===========================================================================
# Corner: validations / invalid_interval_end_before_start_storage
# ===========================================================================
def test_storage_inverted_interval_rejected(api):
    """PRD §2.10: "For both resources the supplied interval must be well-formed,
    with `end_utc` strictly later than `start_utc`; an inverted or empty interval
    is rejected with `ERR_INVALID_INTERVAL`."

    Design: Corner/validations/invalid_interval_end_before_start_storage
    """
    dealer, customer, unit = setup_dealership_customer_unit(
        unit_overrides={"list_price_cents": 5000000}
    )
    resp = api.create_storage_slot(
        {
            "dealership_id": dealer["id"], "unit_id": unit["id"], "customer_id": customer["id"],
            "daily_rate_cents": 5000, "start_utc": "2026-06-10T00:00:00.000Z",
            "end_utc": "2026-06-05T00:00:00.000Z", "expected_unit_version": unit["version"],
        },
        SVC,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_INTERVAL.value)


# ===========================================================================
# Corner: validations / invalid_term_out_of_range_on_request_finance
# ===========================================================================
def test_request_finance_below_minimum_term_rejected(api):
    """PRD §3.4: "Requesting finance requires a term within the inclusive range of
    12 to 240 months — a term outside that range is rejected with
    `ERR_INVALID_TERM`".

    term_months 6 (below 12) -> ERR_INVALID_TERM.

    The deal is left in DRAFT (finance_status NONE) so that the request-finance
    call is legal on the finance axis and the term-range check (PRD §2.6 priority
    13) is actually reached. A quoted cash deal (finance_status CASH) would be
    rejected earlier at the finance-state-legality check (priority 5,
    ERR_FINANCE_BAD_STATE), never reaching the term validation this test targets.

    Design: Corner/validations/invalid_term_out_of_range_on_request_finance
    """
    dealer, customer, unit, deal = setup_held_deal(
        unit_overrides={"list_price_cents": 7000000}, sale_price_cents=7000000
    )
    resp = api.request_finance(deal["id"], SALES, {"term_months": 6})
    validate_error(resp, ApiErrorId.ERR_INVALID_TERM.value)


# ===========================================================================
# Corner: validations / warranty_cap_exceeded_on_complete
# ===========================================================================
def test_warranty_completion_over_cap_rejected(api):
    """PRD §3.7: "A warranty completion is rejected with
    `ERR_WARRANTY_CAP_EXCEEDED` when the coverable portion would exceed the
    remaining headroom."

    Gross = round(2.5*12000)=30000 labor + 270000 part = 300000; cap 200000, ded 0 ->
    coverable 300000 > 200000 -> rejected.

    Design: Corner/validations/warranty_cap_exceeded_on_complete
    """
    dealer, customer, unit, plan, part, so = setup_warranty_so_in_progress(
        plan_cap_cents=200000, deductible_cents=0,
        labor_hours=2.5, labor_rate_cents=12000,
        part_price_cents=270000, part_qty_on_hand=3, reserve_qty=1,
    )
    resp = api.complete_service_order(so["id"], SVC)
    validate_error(resp, ApiErrorId.ERR_WARRANTY_CAP_EXCEEDED.value)
    so_after = validate_success(api.get_service_order(so["id"], SVC))
    assert so_after["status"] == "IN_PROGRESS", so_after["status"]


# ===========================================================================
# Corner: validations / warranty_unit_mismatch_on_service_order_create
# ===========================================================================
def test_warranty_order_for_uncovered_unit_rejected(api):
    """PRD §3.7: "when `is_warranty` is true the request must name the
    `warranty_plan_id`, and that plan must cover the order's unit — a plan that
    does not cover the unit is rejected with `ERR_WARRANTY_UNIT_MISMATCH`."

    Plan covers unit A; opening a warranty SO for unit B -> ERR_WARRANTY_UNIT_MISMATCH.

    Design: Corner/validations/warranty_unit_mismatch_on_service_order_create
    """
    dealer, customer, unit_a = setup_dealership_customer_unit(
        unit_overrides={"class_type": "CLASS_A", "list_price_cents": 9000000}
    )
    unit_b = create_unit(dealer["id"], class_type="CLASS_C", list_price_cents=7000000)
    plan = create_warranty_plan(
        dealer["id"], unit_a["id"], customer["id"],
        plan_kind="EXTENDED", coverage_cap_cents=500000, deductible_cents=0,
    )
    resp = api.create_service_order(
        {
            "dealership_id": dealer["id"], "unit_id": unit_b["id"], "customer_id": customer["id"],
            "labor_hours": 1.0, "labor_rate_cents": 10000,
            "is_warranty": True, "warranty_plan_id": plan["id"],
        },
        SVC,
    )
    validate_error(resp, ApiErrorId.ERR_WARRANTY_UNIT_MISMATCH.value)


# ===========================================================================
# Corner: validations / ltv_exceeded_subprime_band
# ===========================================================================
def test_ltv_exceeded_subprime_rejected(api):
    """PRD §3.4: "A loan-to-value above the tier ceiling is rejected with
    `ERR_LTV_EXCEEDED`."

    SUBPRIME ceiling 11000; financed 6000000 / list 4000000 = 15000bps > 11000 -> rejected.

    Design: Corner/validations/ltv_exceeded_subprime_band
    """
    dealer, customer, unit, deal_id = setup_finance_requested_deal(
        credit_tier="SUBPRIME", list_price_cents=4000000, sale_price_cents=6000000,
        term_months=72, down_payment_cents=0,
    )
    resp = api.finance_decision(deal_id, {"decision": "APPROVE"}, MGR)
    validate_error(resp, ApiErrorId.ERR_LTV_EXCEEDED.value)
    deal_after = validate_success(api.get_deal(deal_id, SALES))
    assert deal_after["finance_status"] == "REQUESTED", deal_after["finance_status"]
