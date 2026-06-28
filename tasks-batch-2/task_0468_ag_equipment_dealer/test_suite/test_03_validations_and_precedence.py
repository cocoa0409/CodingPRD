"""Validation precedence, numeric boundaries, cross-entity preconditions, and
temporal/capacity rules.

Covers the fixed-priority ordering of structural gates ahead of deeper business
rules (PRD §3.9), the inclusive curtailment day boundary, the strict bid
minimum, deal/floor-plan dependence on unit availability, the strict auction
window, the one-active-note-per-unit rule, and the individually-isolated
business-rule validations (curtailment sufficiency, parts shortage, no-matching
unit, recall protection, request hygiene, trade attach).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_unit_payload, create_customer_payload, create_floor_plan_note_payload,
    create_deal_payload, create_trade_in_payload, create_work_order_payload,
    create_part_payload, create_part_line_payload, create_warranty_claim_payload,
    create_whole_goods_order_payload,
    create_customer, create_unit, create_part, create_offered_trade_in,
    create_quoted_deal, create_active_floor_plan_note,
    create_in_progress_work_order, add_part_line, setup_curtailment_due_note,
    setup_submitted_claim, create_live_lot, create_confirmed_order,
    ApiErrorId, TEST_USERS,
)

ADMIN = TEST_USERS["dealer_admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
FINANCE = TEST_USERS["finance_manager_headers"]
SERVICE = TEST_USERS["service_advisor_headers"]
PARTS = TEST_USERS["parts_clerk_headers"]
AUCTION = TEST_USERS["auction_clerk_headers"]


# ─── Priority-pair precedence: state before fiscal (Difficulty/priority_pair_validation_conflict) ──

def test_close_open_work_order_with_parts_shortage_fails_state_first(api):
    """PRD §3.9: "State legality is checked sixth: a transition requested from a
    state in which it is not defined yields `ERR_INVALID_STATE`. The
    optimistic-concurrency check is seventh on funding and settlement: a stale
    `expected_unit_version` yields `ERR_STALE_UNIT_VERSION`. Only after these
    structural gates pass does the system evaluate the deeper business-referential,
    safety, temporal, and fiscal rules described throughout Section 3 — unit
    reservability, trade-attach eligibility, recall protection, auction windows,
    bid minimums, curtailment sufficiency, parts availability, and whole-goods unit
    matching — each with its own dedicated error as named above."

    Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_on_work_order_close
    """
    # WorkOrder still OPEN (never started) with a part line that would overshoot stock.
    customer = create_customer(name="PV Cust", customer_type="RETAIL")
    unit = create_unit(condition="USED", model_code="5055E", engine_hours=2000)
    part = create_part(sku="BRG-9", description="bearing", category="MECHANICAL",
                       unit_price_cents=12000, on_hand_qty=1)
    wo = get_success_data(api.create_work_order(create_work_order_payload(
        unit["id"], customer["id"], complaint="noise", labor_rate_cents=13000,
        flat_rate_hours=1.5), SERVICE))
    add_part_line(wo["id"], part["id"], 5)
    # Close requires IN_PROGRESS; from OPEN the state gate (sixth) fires before the
    # fiscal parts-availability check (ERR_PARTS_SHORTAGE).
    validate_error(api.close_work_order(wo["id"], {"actual_hours": 2.0}, SERVICE),
                   ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_work_order(wo["id"], SERVICE), 200)
    assert after["status"] == "OPEN"


def test_close_open_work_order_state_gate_leaves_wo_open(api):
    """PRD §3.6: "The advisor closes a work order, moving it `IN_PROGRESS → CLOSED`
    (terminal); closing requires the order to be `IN_PROGRESS` and `actual_hours` to
    be greater than zero".

    Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_on_work_order_close
    """
    customer = create_customer(name="PV2 Cust", customer_type="RETAIL")
    unit = create_unit(condition="USED", model_code="5055E", engine_hours=2000)
    part = create_part(sku="BRG-10", description="bearing", category="MECHANICAL",
                       unit_price_cents=12000, on_hand_qty=1)
    wo = get_success_data(api.create_work_order(create_work_order_payload(
        unit["id"], customer["id"], complaint="noise", labor_rate_cents=13000,
        flat_rate_hours=1.5), SERVICE))
    add_part_line(wo["id"], part["id"], 5)
    validate_error(api.close_work_order(wo["id"], {"actual_hours": 2.0}, SERVICE),
                   ApiErrorId.ERR_INVALID_STATE.value)
    # No state change — the close was rejected on the state gate.
    after = validate_success(api.get_work_order(wo["id"], SERVICE), 200)
    assert after["status"] == "OPEN"


# ─── Priority-pair precedence: state before safety (Difficulty/priority_pair_validation_conflict) ──

def test_deny_draft_recall_claim_fails_state_before_safety(api):
    """PRD §3.9: "State legality is checked sixth: a transition requested from a
    state in which it is not defined yields `ERR_INVALID_STATE`. The
    optimistic-concurrency check is seventh on funding and settlement: a stale
    `expected_unit_version` yields `ERR_STALE_UNIT_VERSION`. Only after these
    structural gates pass does the system evaluate the deeper business-referential,
    safety, temporal, and fiscal rules described throughout Section 3 — unit
    reservability, trade-attach eligibility, recall protection, auction windows,
    bid minimums, curtailment sufficiency, parts availability, and whole-goods unit
    matching — each with its own dedicated error as named above."

    Design: Difficulty/priority_pair_validation_conflict/referential_before_safety_on_recall_adjudicate
    """
    unit = create_unit(condition="USED", model_code="6120M", engine_hours=1100)
    claim = validate_success(api.create_warranty_claim(create_warranty_claim_payload(
        unit["id"], claim_type="RECALL", campaign_code="SAFETY-22"), SERVICE), 201)
    # Claim is still DRAFT (never submitted). Adjudicate is defined only from
    # SUBMITTED, so the state gate (sixth) fires ahead of the recall safety rule.
    validate_error(api.adjudicate_warranty_claim(claim["id"], {"decision": "DENY"}, ADMIN),
                   ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_warranty_claim(claim["id"], SERVICE), 200)
    assert after["status"] == "DRAFT"


def test_adjudicate_draft_recall_claim_stays_draft(api):
    """PRD §3.7: "A `DealerAdmin` adjudicates a submitted claim by supplying a
    `decision`. A decision of `FULL` moves the claim `SUBMITTED → APPROVED`; a
    decision of `PARTIAL` moves it `SUBMITTED → PARTIAL`; a decision of `DENY` moves
    it `SUBMITTED → DENIED`."

    Design: Difficulty/priority_pair_validation_conflict/referential_before_safety_on_recall_adjudicate
    """
    unit = create_unit(condition="USED", model_code="6120M", engine_hours=1100)
    claim = validate_success(api.create_warranty_claim(create_warranty_claim_payload(
        unit["id"], claim_type="RECALL", campaign_code="SAFETY-23"), SERVICE), 201)
    validate_error(api.adjudicate_warranty_claim(claim["id"], {"decision": "DENY"}, ADMIN),
                   ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_warranty_claim(claim["id"], SERVICE), 200)
    assert after["status"] == "DRAFT"


# ─── Curtailment day boundary, inclusive >= (Difficulty/boundary_precision_check) ──

def test_curtailment_stage_one_at_exactly_90_days(api):
    """PRD §3.2: "The stage is 0 below 90 days; it is 1 once `days_outstanding`
    reaches at least 90, 2 once it reaches at least 180, and 3 once it reaches at
    least 270 — each boundary is inclusive, so exactly 90 days outstanding already
    triggers stage 1."

    Design: Difficulty/boundary_precision_check/curtailment_breakpoint_at_exactly_90_days
    """
    # 2026-01-01 -> 2026-04-01 is exactly 90 whole days.
    _, note = setup_curtailment_due_note(principal_cents=30000000, annual_rate_bps=875,
                                         to_iso8601="2026-04-01T00:00:00Z")
    assert note["days_outstanding"] == 90
    assert note["curtailment_stage"] == 1
    assert note["status"] == "CURTAILMENT_DUE"


def test_curtailment_stage_zero_one_day_before_breakpoint(api):
    """PRD §3.2: "The note carries curtailment breakpoints at 90, 180, and 270 whole
    days outstanding. The stage is 0 below 90 days".

    Design: Difficulty/boundary_precision_check/curtailment_breakpoint_at_exactly_90_days
    """
    # 2026-01-01 -> 2026-03-31 is 89 whole days, below the 90-day breakpoint.
    unit = create_unit(condition="NEW", dealer_cost_cents=30000000, list_price_cents=42000000)
    note = create_active_floor_plan_note(unit["id"], principal_cents=30000000, annual_rate_bps=875)
    get_success_data(api.set_clock({"to_iso8601": "2026-03-31T00:00:00Z"}, ADMIN))
    recomputed = validate_success(api.recompute_floor_plan_note(note["id"], FINANCE), 200)
    assert recomputed["days_outstanding"] == 89
    assert recomputed["curtailment_stage"] == 0
    assert recomputed["status"] == "ACTIVE"


# ─── Bid strictly greater than high (Difficulty/boundary_precision_check) ────

def test_bid_equal_to_high_bid_rejected(api):
    """PRD §3.5: "To be accepted, a bid must be strictly greater than the current
    `high_bid_cents`; meeting or exceeding the reserve is **not** required to bid."

    Design: Difficulty/boundary_precision_check/bid_must_strictly_exceed_high_bid_equal_rejected
    """
    bidder_a = create_customer(name="Bidder A", customer_type="COMMERCIAL_AG")
    bidder_b = create_customer(name="Bidder B", customer_type="COMMERCIAL_AG")
    _, lot = create_live_lot(
        unit_overrides={"model_code": "S780", "engine_hours": 2500},
        lot_overrides={"reserve_price_cents": 4500000, "closes_at": "2026-06-01T00:00:00Z"},
    )
    get_success_data(api.place_bid(lot["id"], {"bidder_customer_id": bidder_a["id"],
                                               "amount_cents": 5000000}, AUCTION))
    # A second bid equal to the current high (both 5000000) is not strictly greater.
    validate_error(api.place_bid(lot["id"], {"bidder_customer_id": bidder_b["id"],
                                             "amount_cents": 5000000}, AUCTION),
                   ApiErrorId.ERR_BID_TOO_LOW.value)
    after = validate_success(api.get_auction_lot(lot["id"], AUCTION), 200)
    assert after["high_bid_cents"] == 5000000
    assert after["high_bidder_customer_id"] == bidder_a["id"]


def test_bid_one_cent_above_high_accepted(api):
    """PRD §3.5: "When a bid is accepted and its amount strictly exceeds the current
    high, the lot's `high_bid_cents` and `high_bidder_customer_id` are updated to
    that bid."

    Design: Difficulty/boundary_precision_check/bid_must_strictly_exceed_high_bid_equal_rejected
    """
    bidder_a = create_customer(name="Bidder C", customer_type="COMMERCIAL_AG")
    bidder_b = create_customer(name="Bidder D", customer_type="COMMERCIAL_AG")
    _, lot = create_live_lot(
        unit_overrides={"model_code": "S780", "engine_hours": 2500},
        lot_overrides={"reserve_price_cents": 4500000, "closes_at": "2026-06-01T00:00:00Z"},
    )
    get_success_data(api.place_bid(lot["id"], {"bidder_customer_id": bidder_a["id"],
                                               "amount_cents": 5000000}, AUCTION))
    # 5000001 strictly exceeds 5000000 -> accepted and high updates.
    validate_success(api.place_bid(lot["id"], {"bidder_customer_id": bidder_b["id"],
                                               "amount_cents": 5000001}, AUCTION), 201)
    after = validate_success(api.get_auction_lot(lot["id"], AUCTION), 200)
    assert after["high_bid_cents"] == 5000001
    assert after["high_bidder_customer_id"] == bidder_b["id"]


# ─── Cross-entity: deal quote requires unit AVAILABLE (Difficulty/cross_entity_state_dependency) ──

def test_quote_second_deal_on_reserved_unit_rejected(api):
    """PRD §3.4: "Quoting requires the referenced unit to be `AVAILABLE`; a quote
    against a unit that is not available is rejected with `ERR_UNIT_NOT_RESERVABLE`
    (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/deal_quote_requires_unit_available
    """
    cust_a = create_customer(name="CE Cust A", customer_type="RETAIL")
    cust_b = create_customer(name="CE Cust B", customer_type="RETAIL")
    unit = create_unit(condition="NEW", model_code="6155R", dealer_cost_cents=7000000,
                       list_price_cents=9500000)
    # First quote reserves the unit (AVAILABLE -> RESERVED).
    create_quoted_deal(unit["id"], cust_a["id"], deal_type="SALE", sale_price_cents=9500000)
    # Second quote against the now-RESERVED unit is rejected.
    validate_error(api.create_deal(create_deal_payload(
        unit["id"], cust_b["id"], deal_type="SALE", sale_price_cents=9500000), SALES),
        ApiErrorId.ERR_UNIT_NOT_RESERVABLE.value)
    after = validate_success(api.get_unit(unit["id"], FINANCE), 200)
    assert after["status"] == "RESERVED"


def test_quote_sale_reserves_available_unit(api):
    """PRD §3.4: "Quoting a `SALE` or `LEASE` deal reserves the unit, moving it
    `AVAILABLE → RESERVED`; the new deal starts `QUOTED`."

    Design: Difficulty/cross_entity_state_dependency/deal_quote_requires_unit_available
    """
    cust = create_customer(name="CE Cust C", customer_type="RETAIL")
    unit = create_unit(condition="NEW", model_code="6155R", dealer_cost_cents=7000000,
                       list_price_cents=9500000)
    deal = create_quoted_deal(unit["id"], cust["id"], deal_type="SALE", sale_price_cents=9500000)
    assert deal["status"] == "QUOTED"
    after = validate_success(api.get_unit(unit["id"], FINANCE), 200)
    assert after["status"] == "RESERVED"


# ─── Cross-entity: floor-plan activate requires unit AVAILABLE (Difficulty/cross_entity_state_dependency) ──

def test_activate_note_on_reserved_unit_rejected(api):
    """PRD §3.2: "Activating a draft note moves it `DRAFT → ACTIVE`, sets
    `activated_on` to the current clock as the accrual anchor, and sets the financed
    unit's `floor_planned` to `true`. Activation is permitted only when the
    referenced unit is `AVAILABLE` and the unit has no other note already in
    `ACTIVE` or `CURTAILMENT_DUE` status; a violation of the defined transition
    surfaces as `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/floorplan_activate_requires_unit_available
    """
    cust = create_customer(name="FPA Cust", customer_type="RETAIL")
    unit = create_unit(condition="NEW", model_code="7R250", dealer_cost_cents=6500000,
                       list_price_cents=8800000)
    note = get_success_data(api.create_floor_plan_note(create_floor_plan_note_payload(
        unit["id"], principal_cents=6500000, annual_rate_bps=850), FINANCE))
    # Reserve the unit via a quote, then try to activate the draft note.
    create_quoted_deal(unit["id"], cust["id"], deal_type="SALE", sale_price_cents=8800000)
    validate_error(api.activate_floor_plan_note(note["id"], FINANCE),
                   ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_floor_plan_note(note["id"], FINANCE), 200)
    assert after["status"] == "DRAFT"


def test_activate_note_on_available_unit_succeeds(api):
    """PRD §3.2: "Activating a draft note moves it `DRAFT → ACTIVE`, sets
    `activated_on` to the current clock as the accrual anchor, and sets the financed
    unit's `floor_planned` to `true`."

    Design: Difficulty/cross_entity_state_dependency/floorplan_activate_requires_unit_available
    """
    unit = create_unit(condition="NEW", model_code="7R250", dealer_cost_cents=6500000,
                       list_price_cents=8800000)
    note = get_success_data(api.create_floor_plan_note(create_floor_plan_note_payload(
        unit["id"], principal_cents=6500000, annual_rate_bps=850), FINANCE))
    activated = validate_success(api.activate_floor_plan_note(note["id"], FINANCE), 200)
    assert activated["status"] == "ACTIVE"
    after = validate_success(api.get_unit(unit["id"], FINANCE), 200)
    assert after["floor_planned"] is True


# ─── Temporal: auction window opens strictly before closes (Difficulty/resource_temporal_overlap) ──

def test_create_lot_with_equal_open_and_close_rejected(api):
    """PRD §3.5: "The `closes_at` must be strictly after `opens_at`; a window where
    it is not is rejected with `ERR_AUCTION_WINDOW` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/auction_window_opens_before_closes_strict
    """
    unit = create_unit(condition="USED", model_code="S770", engine_hours=1900)
    # opens_at == closes_at is a degenerate zero-width window.
    validate_error(api.create_auction_lot({
        "unit_id": unit["id"], "reserve_price_cents": 4000000,
        "opens_at": "2026-03-01T00:00:00Z", "closes_at": "2026-03-01T00:00:00Z"}, AUCTION),
        ApiErrorId.ERR_AUCTION_WINDOW.value)
    after = validate_success(api.get_unit(unit["id"], AUCTION), 200)
    assert after["status"] == "AVAILABLE"


def test_create_lot_with_valid_window_consigns_unit(api):
    """PRD §3.5: "Consignment is permitted only when the unit is `AVAILABLE` and its
    `condition` is `USED`; it moves the unit `AVAILABLE → AUCTION_LISTED` and the
    new lot starts `DRAFT`."

    Design: Difficulty/resource_temporal_overlap/auction_window_opens_before_closes_strict
    """
    unit = create_unit(condition="USED", model_code="S770", engine_hours=1900)
    lot = validate_success(api.create_auction_lot({
        "unit_id": unit["id"], "reserve_price_cents": 4000000,
        "opens_at": "2026-03-01T00:00:00Z", "closes_at": "2026-04-01T00:00:00Z"}, AUCTION), 201)
    assert lot["status"] == "DRAFT"
    after = validate_success(api.get_unit(unit["id"], AUCTION), 200)
    assert after["status"] == "AUCTION_LISTED"


# ─── Capacity: one active note per unit (Difficulty/resource_temporal_overlap) ──

def test_activate_second_note_on_same_unit_rejected(api):
    """PRD §3.2: "Activation is permitted only when the referenced unit is
    `AVAILABLE` and the unit has no other note already in `ACTIVE` or
    `CURTAILMENT_DUE` status; a violation of the defined transition surfaces as
    `ERR_INVALID_STATE`."

    Design: Difficulty/resource_temporal_overlap/floorplan_one_active_note_per_unit_aggregate_capacity
    """
    unit = create_unit(condition="NEW", model_code="8R340", dealer_cost_cents=20000000,
                       list_price_cents=28000000)
    # First note activated -> unit floor_planned, note ACTIVE.
    create_active_floor_plan_note(unit["id"], principal_cents=20000000, annual_rate_bps=875)
    note2 = get_success_data(api.create_floor_plan_note(create_floor_plan_note_payload(
        unit["id"], principal_cents=20000000, annual_rate_bps=875), FINANCE))
    # Activating the second draft note on the same unit is rejected.
    validate_error(api.activate_floor_plan_note(note2["id"], FINANCE),
                   ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_floor_plan_note(note2["id"], FINANCE), 200)
    assert after["status"] == "DRAFT"


def test_first_note_activation_sets_floor_planned(api):
    """PRD §3.2: "Activating a draft note moves it `DRAFT → ACTIVE`, sets
    `activated_on` to the current clock as the accrual anchor, and sets the financed
    unit's `floor_planned` to `true`."

    Design: Difficulty/resource_temporal_overlap/floorplan_one_active_note_per_unit_aggregate_capacity
    """
    unit = create_unit(condition="NEW", model_code="8R340", dealer_cost_cents=20000000,
                       list_price_cents=28000000)
    note = create_active_floor_plan_note(unit["id"], principal_cents=20000000, annual_rate_bps=875)
    assert note["status"] == "ACTIVE"
    after = validate_success(api.get_unit(unit["id"], FINANCE), 200)
    assert after["floor_planned"] is True


# ─── Curtailment payment sufficiency (Corner/validations) ────────────────────

def test_curtail_payment_below_shortfall_rejected(api):
    """PRD §3.2: "The payment must be at least the shortfall required for the current
    stage, as computed above; a payment below that shortfall is rejected with
    `ERR_CURTAILMENT_SHORT` (HTTP 409)."

    Design: Corner/validations/curtail_payment_below_shortfall_rejected
    """
    _, note = setup_curtailment_due_note(principal_cents=30000000, annual_rate_bps=875,
                                         to_iso8601="2026-04-01T00:00:00Z")
    assert note["status"] == "CURTAILMENT_DUE"
    # Stage-1 required is 30000000 * 0.10 * 1 = 3000000; a 1000000 payment is short.
    validate_error(api.curtail_floor_plan_note(note["id"], {"payment_cents": 1000000}, FINANCE),
                   ApiErrorId.ERR_CURTAILMENT_SHORT.value)
    after = validate_success(api.get_floor_plan_note(note["id"], FINANCE), 200)
    assert after["status"] == "CURTAILMENT_DUE"


def test_curtail_payment_meets_shortfall_returns_active(api):
    """PRD §3.2: "A sufficient payment adds `payment_cents` to
    `curtailment_paid_cents`, and if all due stages are thereby satisfied the note
    returns `CURTAILMENT_DUE → ACTIVE`."

    Design: Corner/validations/curtail_payment_meets_shortfall_returns_active
    """
    _, note = setup_curtailment_due_note(principal_cents=30000000, annual_rate_bps=875,
                                         to_iso8601="2026-04-01T00:00:00Z")
    # A payment >= 3000000 clears the stage-1 shortfall.
    curtailed = validate_success(
        api.curtail_floor_plan_note(note["id"], {"payment_cents": 3000000}, FINANCE), 200)
    assert curtailed["status"] == "ACTIVE"
    assert curtailed["curtailment_paid_cents"] == 3000000


# ─── Parts shortage on close (Corner/validations) ────────────────────────────

def test_parts_shortage_on_close_rejected(api):
    """PRD §3.6: "Closing also enforces parts availability: if any part line's
    `quantity` exceeds the part's available quantity (`on_hand_qty` minus
    `reserved_qty`) at close, the close is rejected with `ERR_PARTS_SHORTAGE`
    (HTTP 409)."

    Design: Corner/validations/parts_shortage_on_close_rejected
    """
    # IN_PROGRESS work order with a line for 5 on a part stocked at 2.
    _, _, wo, _, _ = create_in_progress_work_order(
        wo_overrides={"labor_rate_cents": 14000, "flat_rate_hours": 3.0},
        part_qty=5, part_overrides={"sku": "INJ-7", "category": "MECHANICAL",
                                    "unit_price_cents": 18000, "on_hand_qty": 2},
    )
    validate_error(api.close_work_order(wo["id"], {"actual_hours": 3.0}, SERVICE),
                   ApiErrorId.ERR_PARTS_SHORTAGE.value)
    after = validate_success(api.get_work_order(wo["id"], SERVICE), 200)
    assert after["status"] == "IN_PROGRESS"


# ─── Whole-goods no matching unit (Corner/validations) ───────────────────────

def test_whole_goods_allocate_no_matching_unit_rejected(api):
    """PRD §3.8: "Allocating supplies a `unit_id` and requires an `AVAILABLE` unit
    whose `model_code` matches the order; if no such unit exists the allocation is
    rejected with `ERR_NO_MATCHING_UNIT` (HTTP 409)."

    Design: Corner/validations/whole_goods_allocate_no_matching_unit_rejected
    """
    wrong_unit = create_unit(condition="NEW", model_code="5045E", dealer_cost_cents=3000000,
                             list_price_cents=4000000)
    _, order = create_confirmed_order(
        customer_overrides={"name": "NM Cust", "customer_type": "COMMERCIAL_AG"},
        order_overrides={"model_code": "9RX830", "season_program": "IN_SEASON",
                         "quantity": 1, "unit_msrp_cents": 25000000},
    )
    # The passed unit's model_code does not match the order's 9RX830.
    validate_error(api.allocate_whole_goods_order(order["id"], {"unit_id": wrong_unit["id"]}, SALES),
                   ApiErrorId.ERR_NO_MATCHING_UNIT.value)
    after = validate_success(api.get_whole_goods_order(order["id"], SALES), 200)
    assert after["status"] == "CONFIRMED"


# ─── Recall safety rule (Corner/validations) ─────────────────────────────────

def test_recall_claim_full_approval_allowed(api):
    """PRD §3.7: "There is one absolute safety rule: a `RECALL` claim is a safety
    campaign that must be honored and can never be denied, so a `DENY` decision on a
    claim whose `claim_type` is `RECALL` is rejected with `ERR_RECALL_CANNOT_DENY`
    (HTTP 409)."

    Design: Corner/validations/recall_claim_full_approval_allowed
    """
    _, _, claim, _ = setup_submitted_claim(claim_type="RECALL", campaign_code="SAFE-9")
    assert claim["claimed_cents"] == 110000
    # FULL is allowed on a RECALL; only DENY is blocked. PIP/RECALL reimburse 100%.
    approved = validate_success(
        api.adjudicate_warranty_claim(claim["id"], {"decision": "FULL"}, ADMIN), 200)
    assert approved["status"] == "APPROVED"
    assert approved["approved_cents"] == 110000


def test_recall_claim_deny_blocked_by_safety_rule(api):
    """PRD §3.7: "a `RECALL` claim is a safety campaign that must be honored and can
    never be denied, so a `DENY` decision on a claim whose `claim_type` is `RECALL`
    is rejected with `ERR_RECALL_CANNOT_DENY` (HTTP 409)."

    Design: Corner/validations/recall_claim_deny_blocked_by_safety_rule
    """
    _, _, claim, _ = setup_submitted_claim(claim_type="RECALL", campaign_code="SAFE-11")
    assert claim["status"] == "SUBMITTED"
    validate_error(api.adjudicate_warranty_claim(claim["id"], {"decision": "DENY"}, ADMIN),
                   ApiErrorId.ERR_RECALL_CANNOT_DENY.value)
    after = validate_success(api.get_warranty_claim(claim["id"], SERVICE), 200)
    assert after["status"] == "SUBMITTED"


# ─── Request hygiene: numeric constraint (Corner/validations) ────────────────

def test_quote_deal_with_zero_sale_price_rejected(api):
    """PRD §3.9: "Request well-formedness is checked fourth: required input fields
    must be present and well-typed, every enum value must lie within its declared
    set, and numeric constraints (such as a `quantity` greater than zero or a
    `sale_price_cents` greater than zero) must hold — a violation yields
    `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/validations/invalid_request_negative_sale_price_rejected
    """
    cust = create_customer(name="Neg Cust", customer_type="RETAIL")
    unit = create_unit(condition="NEW", model_code="5045E", dealer_cost_cents=3000000,
                       list_price_cents=4000000)
    validate_error(api.create_deal(create_deal_payload(
        unit["id"], cust["id"], deal_type="SALE", sale_price_cents=0), SALES),
        ApiErrorId.ERR_INVALID_REQUEST.value)


# ─── Trade-attach eligibility (Corner/validations) ───────────────────────────

def test_quote_deal_with_appraised_trade_rejected(api):
    """PRD §3.4: "If the deal names a trade, that trade may be attached only while it
    is `OFFERED`; attaching a trade that is `DECLINED` or `ACCEPTED` (or otherwise
    not `OFFERED`) is rejected with `ERR_TRADEIN_NOT_OFFERED` (HTTP 409)."

    Design: Corner/validations/tradein_not_offered_cannot_attach_to_deal
    """
    cust = create_customer(name="TN Cust", customer_type="RETAIL")
    unit = create_unit(condition="NEW", model_code="6R165", dealer_cost_cents=6000000,
                       list_price_cents=8000000)
    # A freshly appraised trade is APPRAISED, not yet OFFERED.
    ti = validate_success(api.create_trade_in(create_trade_in_payload(
        cust["id"], model_code="6155M", engine_hours=500, condition_grade="GOOD",
        base_value_cents=3000000), SALES), 201)
    assert ti["status"] == "APPRAISED"
    validate_error(api.create_deal(create_deal_payload(
        unit["id"], cust["id"], deal_type="SALE", sale_price_cents=8000000,
        tradein_id=ti["id"]), SALES),
        ApiErrorId.ERR_TRADEIN_NOT_OFFERED.value)
    after = validate_success(api.get_trade_in(ti["id"], SALES), 200)
    assert after["status"] == "APPRAISED"
