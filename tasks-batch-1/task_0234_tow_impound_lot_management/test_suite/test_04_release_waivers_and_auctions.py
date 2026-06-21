"""Release authorization gating, validation precedence, fee-waiver segregation,
auction window overlap, sweep/sale linkage, and void-sale conservation.

Covers difficulty rules: priority_pair_validation_conflict, cross_entity_state_dependency
(pending waiver), resource_temporal_overlap (window overlap), compensating_invariant
(void-sale money conservation); and corner validations / errors / endpoints / rbac.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    assert_auction_conservation,
    TEST_USERS,
    make_claimant_headers,
    set_clock,
    create_lot,
    create_order,
    add_inventory,
    create_stored_order,
    create_stored_lien_order,
    create_delivered_notice,
    file_waiver,
    file_and_review_waiver,
    pay,
    setup_open_auction_with_swept_order,
    setup_auction_eligible_order,
)

OP = TEST_USERS["lot_operator_headers"]
POLICE = TEST_USERS["police_officer_headers"]
CLAIMANT = TEST_USERS["claimant_headers"]
AUCTION = TEST_USERS["auction_official_headers"]


# ─── priority_pair / hold_active_beats_balance_unpaid_on_authorize_release ────
def test_hold_active_reported_over_balance_unpaid(api):
    """PRD §3.10: "an active POLICE_HOLD or EVIDENCE_HOLD blocking release authorization,
    release recording, marking auction-eligible, and recording a sale (ERR_HOLD_ACTIVE);
    ... a pending REQUESTED or UNDER_REVIEW waiver blocking release authorization
    (ERR_WAIVER_PENDING); the requirement that amount_paid_cents cover net_due_cents
    before release authorization (ERR_BALANCE_UNPAID)"

    Design: Difficulty/priority_pair_validation_conflict/hold_active_beats_balance_unpaid_on_authorize_release
    """
    set_clock("2026-08-01T00:00:00Z")
    lot, order = create_stored_order(order_overrides={"tow_type": "POLICE"})
    # Place a hold; balance is unpaid (no payment made). Both rules violated.
    get_success_data(api.place_hold(order["id"], {"hold_status": "POLICE_HOLD"}, POLICE))
    res = api.authorize_release(order["id"], OP)
    validate_error(res, "ERR_HOLD_ACTIVE", expected_status=409)


def test_balance_unpaid_reported_when_only_balance_violated(api):
    """PRD §3.5: "the order's amount_paid_cents must be at least its net_due_cents, since
    an unsatisfied balance blocks authorization with ERR_BALANCE_UNPAID."

    Design: Difficulty/priority_pair_validation_conflict/hold_active_beats_balance_unpaid_on_authorize_release
    """
    set_clock("2026-08-01T00:00:00Z")
    lot, order = create_stored_order(order_overrides={"tow_type": "POLICE"})
    set_clock("2026-08-06T00:00:00Z")  # accrues balance, no hold, no waiver, unpaid
    res = api.authorize_release(order["id"], OP)
    validate_error(res, "ERR_BALANCE_UNPAID", expected_status=409)


# ─── priority_pair / invalid_state_beats_waiver_pending_on_authorize_release ──
def test_invalid_state_reported_over_waiver_pending(api):
    """PRD §3.10: "a malformed body before a state problem, and a state problem before any
    of the domain-specific business rules."
    PRD §3.5: "the order must be in STORED (otherwise ERR_INVALID_STATE)"

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_waiver_pending_on_authorize_release
    """
    set_clock("2026-08-10T00:00:00Z")
    lot = create_lot()
    order = create_order(lot["id"], tow_type="POLICE")  # still TOWED, never STORED
    file_waiver(order["id"], filer_user_id="claimant-2",
                reason="WRONGFUL_TOW", requested_amount_cents=1000)
    res = api.authorize_release(order["id"], OP)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_authorize_release_on_towed_order_is_invalid_state(api):
    """PRD §3.5: "the order must be in STORED (otherwise ERR_INVALID_STATE)"

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_waiver_pending_on_authorize_release
    """
    lot = create_lot()
    order = create_order(lot["id"], tow_type="POLICE")  # TOWED
    res = api.authorize_release(order["id"], OP)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── cross_entity_state_dependency / authorize_release_blocked_by_pending_feewaiver ─
def test_pending_waiver_blocks_release_even_when_paid(api):
    """PRD §3.5: "there must be no fee waiver on the order still in REQUESTED or
    UNDER_REVIEW status, since a pending waiver blocks authorization with
    ERR_WAIVER_PENDING; and the order's amount_paid_cents must be at least its net_due_cents"

    Design: Difficulty/cross_entity_state_dependency/authorize_release_blocked_by_pending_feewaiver
    """
    set_clock("2026-10-01T00:00:00Z")
    lot, lh, order = create_stored_lien_order(
        lot_overrides={"daily_storage_rate_cents": 5000, "admin_fee_cents": 7500,
                       "lien_processing_fee_cents": 3000})
    set_clock("2026-10-06T00:00:00Z")  # net_due 35500
    pay(order["id"], 35500, user_id="claimant-3")
    file_waiver(order["id"], filer_user_id="claimant-3",
                reason="BILLING_DISPUTE", requested_amount_cents=1000)
    res = api.authorize_release(order["id"], OP)
    validate_error(res, "ERR_WAIVER_PENDING", expected_status=409)


def test_release_authorizes_when_paid_and_no_pending_waiver(api):
    """PRD §3.5: "On success the server freezes accrual: it closes the current open
    StorageLedgerEntry by setting its segment_end to the current clock with kind FREEZE,
    sets the order's accrual_frozen_at to that instant"

    Design: Difficulty/cross_entity_state_dependency/authorize_release_blocked_by_pending_feewaiver
    """
    set_clock("2026-10-01T00:00:00Z")
    lot, lh, order = create_stored_lien_order(
        lot_overrides={"daily_storage_rate_cents": 5000, "admin_fee_cents": 7500,
                       "lien_processing_fee_cents": 3000})
    set_clock("2026-10-06T00:00:00Z")  # net_due 35500
    pay(order["id"], 35500, user_id="claimant-3")
    res = api.authorize_release(order["id"], OP)
    authorized = validate_success(res, 200)
    assert authorized["status"] == "RELEASE_AUTHORIZED"
    assert authorized["accrual_frozen_at"] is not None


# ─── resource_temporal_overlap / auction_window_overlap_on_same_lot_rejected ──
def test_overlapping_auction_window_rejected(api):
    """PRD §3.9: "Two auctions on the same lot may not have overlapping windows: a
    scheduled window that overlaps an existing window on the same lot is rejected with
    ERR_AUCTION_WINDOW_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/auction_window_overlap_on_same_lot_rejected
    """
    lot = create_lot()
    get_success_data(api.create_auction(
        {"lot_id": lot["id"], "window_start": "2026-12-01T00:00:00Z",
         "window_end": "2026-12-01T06:00:00Z"}, AUCTION))
    res = api.create_auction(
        {"lot_id": lot["id"], "window_start": "2026-12-01T03:00:00Z",
         "window_end": "2026-12-01T09:00:00Z"}, AUCTION)
    validate_error(res, "ERR_AUCTION_WINDOW_OVERLAP", expected_status=409)


def test_non_overlapping_auction_window_allowed(api):
    """PRD §3.9: "An auction is scheduled against a lot by an AuctionOfficial or a
    LotOperator, supplying the lot_id, a window_start, and a window_end that must be
    strictly after window_start. A new auction begins SCHEDULED."

    Design: Difficulty/resource_temporal_overlap/auction_window_overlap_on_same_lot_rejected
    """
    lot = create_lot()
    get_success_data(api.create_auction(
        {"lot_id": lot["id"], "window_start": "2026-12-01T00:00:00Z",
         "window_end": "2026-12-01T06:00:00Z"}, AUCTION))
    res = api.create_auction(
        {"lot_id": lot["id"], "window_start": "2026-12-01T06:00:00Z",
         "window_end": "2026-12-01T12:00:00Z"}, AUCTION)
    second = validate_success(res, 201)
    assert second["status"] == "SCHEDULED"


# ─── compensating_invariant / void_sale_restores_auction_proceeds ────────────
def test_void_sale_restores_gross_proceeds_and_order_state(api):
    """PRD §3.9: "An AuctionOfficial voids a sale against the auction by naming the
    tow_order_id; this is a compensating action that returns the order to AUCTION_ELIGIBLE,
    removes the order's SETTLEMENT ledger entry, subtracts that order's sale price from the
    auction's gross_proceeds_cents, and recomputes the distribution waterfall so that
    conservation is restored."

    Design: Difficulty/compensating_invariant/void_sale_restores_auction_proceeds_money_conservation
    """
    lot, order, auction = setup_open_auction_with_swept_order(
        intake_iso="2027-01-01T00:00:00Z", eligible_iso="2027-02-15T00:00:00Z",
        window_start="2027-02-15T00:00:00Z", window_end="2027-02-15T06:00:00Z")
    get_success_data(api.record_sale(
        auction["id"], {"tow_order_id": order["id"], "sale_price_cents": 40000}, AUCTION))
    res = api.void_sale(auction["id"], {"tow_order_id": order["id"]}, AUCTION)
    voided_order = validate_success(res, 200)
    assert voided_order["status"] == "AUCTION_ELIGIBLE"
    auc = validate_success(api.get_auction(auction["id"], AUCTION), 200)
    assert auc["gross_proceeds_cents"] == 0
    assert auc["distributed_cents"] == 0
    assert auc["surplus_to_owner_cents"] == 0
    assert_auction_conservation(auc)


def test_record_sale_accumulates_gross_proceeds(api):
    """PRD §3.9: "Recording a sale moves the order to the terminal AUCTIONED state, writes
    a SETTLEMENT StorageLedgerEntry finalizing the order's accrued_storage_cents, adds the
    sale_price_cents to the auction's gross_proceeds_cents, and re-runs the distribution
    waterfall on the auction."

    Design: Difficulty/compensating_invariant/void_sale_restores_auction_proceeds_money_conservation
    """
    lot, order, auction = setup_open_auction_with_swept_order(
        intake_iso="2027-01-01T00:00:00Z", eligible_iso="2027-02-15T00:00:00Z",
        window_start="2027-02-15T00:00:00Z", window_end="2027-02-15T06:00:00Z")
    res = api.record_sale(
        auction["id"], {"tow_order_id": order["id"], "sale_price_cents": 40000}, AUCTION)
    sold = validate_success(res, 200)
    assert sold["status"] == "AUCTIONED"
    auc = validate_success(api.get_auction(auction["id"], AUCTION), 200)
    assert auc["gross_proceeds_cents"] == 40000


# ─── Corner: validations / intake_on_suspended_lot_rejected ───────────────────
def test_intake_on_suspended_lot_rejected(api):
    """PRD §3.3: "the lot must be OPEN: intake against a SUSPENDED lot is rejected with
    ERR_LOT_SUSPENDED."

    Design: Corner/validations/intake_on_suspended_lot_rejected
    """
    lot = create_lot()
    get_success_data(api.suspend_lot(lot["id"], {"expected_lot_version": lot["version"]}, OP))
    from test_helpers import create_tow_order_payload
    res = api.create_tow_order(create_tow_order_payload(lot["id"], tow_type="POLICE"), OP)
    validate_error(res, "ERR_LOT_SUSPENDED", expected_status=409)


# ─── Corner: validations / authorize_release_balance_unpaid_rejected ──────────
def test_authorize_release_unpaid_balance_rejected(api):
    """PRD §3.5: "the order's amount_paid_cents must be at least its net_due_cents, since
    an unsatisfied balance blocks authorization with ERR_BALANCE_UNPAID."

    Design: Corner/validations/authorize_release_balance_unpaid_rejected
    """
    set_clock("2027-09-01T00:00:00Z")
    lot, order = create_stored_order(
        lot_overrides={"daily_storage_rate_cents": 5000, "admin_fee_cents": 7500},
        order_overrides={"tow_type": "POLICE"})
    set_clock("2027-09-06T00:00:00Z")  # net_due 32500, unpaid
    res = api.authorize_release(order["id"], OP)
    validate_error(res, "ERR_BALANCE_UNPAID", expected_status=409)


# ─── Corner: validations / invalid_request_window_end_before_start ────────────
def test_auction_window_end_before_start_rejected(api):
    """PRD §3.10: "the request body is well-formed — required fields present, enum values
    valid, amounts non-negative where required, and an auction's window_end strictly after
    its window_start (ERR_INVALID_REQUEST)"

    Design: Corner/validations/invalid_request_window_end_before_start
    """
    lot = create_lot()
    res = api.create_auction(
        {"lot_id": lot["id"], "window_start": "2027-10-01T06:00:00Z",
         "window_end": "2027-10-01T00:00:00Z"}, AUCTION)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


# ─── Corner: validations / reference_mismatch_rotation_provider ───────────────
def test_intake_provider_id_mismatch_rejected(api):
    """PRD §2.5: "When a tow order is created with a rotation_assignment_id, that
    assignment's provider_id must match the provider_id supplied on the order ... When
    these references resolve individually but contradict one another, the request is
    rejected with ERR_REFERENCE_MISMATCH."

    Design: Corner/validations/reference_mismatch_rotation_provider
    """
    from test_helpers import setup_offered_assignment, make_tow_provider_headers, create_tow_order_payload
    lot, providers, ra1, v = setup_offered_assignment(
        num_providers=2, lot_overrides={"max_provider_concurrent_offers": 5})
    p1, p2 = providers
    get_success_data(api.accept_rotation(ra1["id"], make_tow_provider_headers(p1["id"])))
    # Cite the ACCEPTED assignment (p1) but provide p2's id as provider_id.
    payload = create_tow_order_payload(
        lot["id"], tow_type="POLICE", provider_id=p2["id"], rotation_assignment_id=ra1["id"])
    res = api.create_tow_order(payload, OP)
    validate_error(res, "ERR_REFERENCE_MISMATCH", expected_status=409)


# ─── Corner: rbac / segregation_of_duties_same_user_rejected ──────────────────
def test_waiver_approve_by_filer_rejected(api):
    """PRD §3.6: "both decisions are subject to segregation of duties: the deciding
    operator's X-User-ID must differ from the waiver's recorded filed_by_user_id, or the
    decision is rejected with ERR_SEGREGATION_OF_DUTIES."

    Design: Corner/rbac/segregation_of_duties_same_user_rejected
    """
    set_clock("2028-02-01T00:00:00Z")
    lot, order = create_stored_order(order_overrides={"tow_type": "POLICE"})
    set_clock("2028-02-06T00:00:00Z")
    file_and_review_waiver(order["id"], filer_user_id="shared-user-1",
                           reason="HARDSHIP", requested_amount_cents=1000)
    waivers = get_success_data(api.list_fee_waivers(order["id"], OP))
    wid = waivers[0]["id"]
    from test_helpers import make_lot_operator_headers
    res = api.approve_waiver(order["id"], wid, make_lot_operator_headers("shared-user-1"))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=409)


# ─── Corner: errors / error_not_in_auction_on_record_sale ─────────────────────
def test_record_sale_for_unswept_order_rejected(api):
    """PRD §3.9: "it must already be swept into this auction so that its auction_id equals
    this auction's id (otherwise ERR_NOT_IN_AUCTION)"

    Design: Corner/errors/error_not_in_auction_on_record_sale
    """
    # Eligible order NOT swept; open auction exists.
    lot, order = setup_auction_eligible_order(
        intake_iso="2028-01-01T00:00:00Z", eligible_iso="2028-01-06T00:00:00Z",
        lot_overrides={"statutory_hold_days": 3, "notice_grace_days": 0})
    auction = get_success_data(api.create_auction(
        {"lot_id": lot["id"], "window_start": "2028-01-06T00:00:00Z",
         "window_end": "2028-01-06T06:00:00Z"}, AUCTION))
    get_success_data(api.open_auction(auction["id"], AUCTION))
    res = api.record_sale(
        auction["id"], {"tow_order_id": order["id"], "sale_price_cents": 40000}, AUCTION)
    validate_error(res, "ERR_NOT_IN_AUCTION", expected_status=409)


# ─── Corner: endpoints / sweep_links_auction_id_reverse_reachable ─────────────
def test_sweep_links_order_to_auction(api):
    """PRD §3.9: "Eligible orders are brought into the auction by a sweep, performed by an
    AuctionOfficial or a LotOperator against the auction with the tow_order_id to bring in;
    a swept order must be in AUCTION_ELIGIBLE with hold_status NONE ... and on success the
    order's auction_id is linked to the auction."

    Design: Corner/endpoints/sweep_links_auction_id_reverse_reachable
    """
    lot, order, auction = setup_open_auction_with_swept_order(
        intake_iso="2027-11-01T00:00:00Z", eligible_iso="2027-11-06T00:00:00Z",
        window_start="2027-11-06T00:00:00Z", window_end="2027-11-06T06:00:00Z",
        lot_overrides={"statutory_hold_days": 3, "notice_grace_days": 0})
    assert order["auction_id"] == auction["id"], "sweep linked auction_id"
    res = api.list_auction_tow_orders(auction["id"], AUCTION)
    body = res.json()
    assert body["response_type"] == "array"
    assert body["meta"]["total_count"] == 1
