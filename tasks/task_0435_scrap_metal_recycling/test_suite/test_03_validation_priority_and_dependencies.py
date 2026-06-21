"""Validation-priority conflicts, cross-entity state dependencies, boundary precision.

Difficulty queue: priority_pair_validation_conflict + boundary_precision_check +
cross_entity_state_dependency instances.
"""
from test_helpers import fixtures, validate_success, validate_error
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    publish_price,
    register_seller,
    stage_container,
    open_ticket,
    add_line,
    create_weighed_ticket,
    create_released_ticket,
    open_hedge,
    dispatch_container,
    WM, PC, SA, CO, YM,
)
from test_helpers.test_users import make_payout_clerk_headers
from test_helpers.api_client import api_client


# ---------------------------------------------------------------------------
# Rule 5 — priority_pair_validation_conflict / segregation_beats_category_mismatch
# ---------------------------------------------------------------------------
def test_segregation_of_duties_blocks_self_approved_payout(api):
    """PRD §3.5: "the acting `PayoutClerk`'s `X-User-ID` must differ from the value
    recorded in the ticket's `theft_hold_released_by`; if they are equal — the same
    person who cleared the theft hold is trying to approve the money — the request
    is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    The same operator id cleared the hold and now creates the payout -> SoD fires.

    Design: Difficulty/priority_pair_validation_conflict/segregation_beats_category_mismatch
    """
    built = fixtures.create_released_ticket_with_cleared_hold(
        clearer_user_id="U_SAME", grade_code="SHRED_STEEL", category="FERROUS",
        spot=11, weight_lb=100, capacity_lb=5000,
    )
    same_clerk = make_payout_clerk_headers("U_SAME")
    resp = api.create_payout({"ticket_id": built["ticket"]["id"], "method": "CASH"}, same_clerk)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


def test_segregation_of_duties_allows_different_clerk(api):
    """PRD §3.5: "the acting `PayoutClerk`'s `X-User-ID` must differ from the value
    recorded in the ticket's `theft_hold_released_by`; if they are equal ... the
    request is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    A distinct PayoutClerk id (not the hold clearer) is allowed to create the payout.

    Design: Difficulty/priority_pair_validation_conflict/segregation_beats_category_mismatch
    """
    built = fixtures.create_released_ticket_with_cleared_hold(
        clearer_user_id="U_CLEARER", grade_code="SHRED_STEEL", category="FERROUS",
        spot=11, weight_lb=100, capacity_lb=5000,
    )
    other_clerk = make_payout_clerk_headers("U_DIFFERENT")
    data = validate_success(
        api.create_payout({"ticket_id": built["ticket"]["id"], "method": "CASH"}, other_clerk), 201
    )
    assert data["status"] == "PENDING", f"expected PENDING payout, got {data['status']}"


# ---------------------------------------------------------------------------
# Rule 5 — priority_pair_validation_conflict / seller_frozen_beats_tin_required_on_settle
# ---------------------------------------------------------------------------
def test_seller_frozen_beats_tin_required_on_settle(api):
    """PRD §2.8: "their relative ordering, where two could fire on one endpoint,
    follows the priority sequence: segregation of duties, then seller-frozen checks,
    then container-category match, then grade-active check, then weight validity,
    then container capacity, then hedge over-realization, then the 1099 TIN gate."
    PRD §3.5: "Settling requires the payout to be `PENDING` and the seller to be
    `ACTIVE` (a seller who became frozen between creation and settlement blocks the
    settle with `ERR_SELLER_FROZEN`)."

    A 70000c CASH payout for a TIN-less seller frozen post-release: the seller-frozen
    check ranks above the 1099 TIN gate, so ERR_SELLER_FROZEN is returned.

    Design: Difficulty/priority_pair_validation_conflict/seller_frozen_beats_tin_required_on_settle
    """
    publish_price("CU_BARE_BRIGHT", "NON_FERROUS", spot=700, mill=720)
    seller = register_seller(legal_name="Frozen Co", id_type="STATE_ID", id_number="SID-8")
    built = create_released_ticket(
        grade_code="CU_BARE_BRIGHT", category="NON_FERROUS", spot=700, mill=720,
        weight_lb=100, capacity_lb=5000, seller_id=seller["id"],
    )
    payout = validate_success(
        api.create_payout({"ticket_id": built["ticket"]["id"], "method": "CASH"}, PC), 201
    )
    # File a theft report after release -> seller becomes FLAGGED.
    validate_success(
        api.create_theft_report(
            {"seller_id": seller["id"], "reason": "post-release tip",
             "ticket_id": built["ticket"]["id"]}, CO), 201
    )
    resp = api.settle_payout(payout["id"], PC)
    validate_error(resp, ApiErrorId.ERR_SELLER_FROZEN.value)


# ---------------------------------------------------------------------------
# Rule 6 — boundary_precision_check / tin_1099_threshold_exact_60000_triggers
# ---------------------------------------------------------------------------
def test_tin_1099_threshold_exact_60000_triggers(api):
    """PRD §3.5: "if the seller's `ytd_cash_paid_cents` is at or above the cumulative
    cash threshold of $600.00 (that is, 60000 cents), the seller's `requires_1099`
    flag is set true."
    PRD §3.5: "The boundary is inclusive: a cumulative post-increment total of
    exactly 60000 cents triggers the requirement, while 59999 cents does not."

    A CASH payout pushing ytd to exactly 60000 sets requires_1099 and form_1099_issued.

    Design: Difficulty/boundary_precision_check/tin_1099_threshold_exact_60000_triggers
    """
    publish_price("BRASS", "NON_FERROUS", spot=100, mill=110)
    seller = register_seller(legal_name="Edge Co", id_type="STATE_ID",
                             id_number="SID-9", tin="99-9999999")
    built = create_released_ticket(
        grade_code="BRASS", category="NON_FERROUS", spot=100, mill=110,
        weight_lb=600, capacity_lb=5000, seller_id=seller["id"],
    )
    payout = validate_success(
        api.create_payout({"ticket_id": built["ticket"]["id"], "method": "CASH"}, PC), 201
    )
    settled = validate_success(api.settle_payout(payout["id"], PC))
    seller_after = validate_success(api.get_seller(seller["id"], WM))
    assert seller_after["ytd_cash_paid_cents"] == 60000, \
        f"expected ytd 60000, got {seller_after['ytd_cash_paid_cents']}"
    assert seller_after["requires_1099"] is True, \
        f"expected requires_1099 True at exactly 60000, got {seller_after['requires_1099']}"
    assert settled["form_1099_issued"] is True, \
        f"expected form_1099_issued True, got {settled['form_1099_issued']}"


# ---------------------------------------------------------------------------
# Rule 6 — boundary_precision_check / weigh_out_blocked_on_empty_line_item_set
# ---------------------------------------------------------------------------
def test_weigh_out_blocked_on_empty_line_item_set(api):
    """PRD §3.3: "This weigh-out is only valid from `DRAFT` and only when the ticket
    has at least one line item; a weigh-out on a ticket with zero lines is rejected
    with `ERR_NO_LINE_ITEMS` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/weigh_out_blocked_on_empty_line_item_set
    """
    seller = register_seller(legal_name="Empty Co", id_type="STATE_ID", id_number="SID-10")
    ticket = open_ticket(seller["id"], gross_weight_lb=1500)
    resp = api.weigh_out(ticket["id"], {"tare_weight_lb": 200}, WM)
    validate_error(resp, ApiErrorId.ERR_NO_LINE_ITEMS.value)
    after = validate_success(api.get_ticket(ticket["id"], WM))
    assert after["status"] == "DRAFT", f"ticket must remain DRAFT, got {after['status']}"


# ---------------------------------------------------------------------------
# Rule 7 — cross_entity_state_dependency / ticket_release_requires_seller_active
# ---------------------------------------------------------------------------
def test_release_blocked_by_flagged_seller(api):
    """PRD §3.4: "The seller must be `ACTIVE` and free of any open theft reports; a
    `FLAGGED` or `BANNED` seller, or a seller with `open_theft_reports` greater than
    0, blocks the release with `ERR_SELLER_FROZEN`."

    A weighed ticket whose seller was flagged by a proactive report cannot be released.

    Design: Difficulty/cross_entity_state_dependency/ticket_release_requires_seller_active
    """
    built = create_weighed_ticket(grade_code="SHRED_STEEL", category="FERROUS",
                                  spot=11, mill=14, weight_lb=100)
    container = stage_container("FERROUS", capacity_lb=5000)
    validate_success(
        api.create_theft_report(
            {"seller_id": built["seller_id"], "reason": "open investigation"}, CO), 201
    )
    resp = api.release_ticket(built["ticket"]["id"], {"container_id": container["id"]}, WM)
    validate_error(resp, ApiErrorId.ERR_SELLER_FROZEN.value)
    after = validate_success(api.get_ticket(built["ticket"]["id"], WM))
    assert after["status"] == "WEIGHED", f"ticket must remain WEIGHED, got {after['status']}"


# ---------------------------------------------------------------------------
# Rule 7 — cross_entity_state_dependency / shipment_settle_requires_hedge_open
# ---------------------------------------------------------------------------
def test_settle_against_closed_hedge_rejected(api):
    """PRD §3.7: "The referenced hedge must be `OPEN`, its `category` must match the
    shipment's `category`, and its `version` must equal `expected_hedge_version`."
    PRD §3.8: "once closed, no further shipments may realize against it."

    A shipment linked to a hedge manually CLOSED before settle is rejected with
    ERR_INVALID_STATE.

    Design: Difficulty/cross_entity_state_dependency/shipment_settle_requires_hedge_open
    """
    built = fixtures.create_shipped_shipment_with_hedge(
        hedged_weight_lb=1300, locked_price=90, category="FERROUS",
        weight_lb=1000, gross_weight_lb=1500, tare_weight_lb=200,
        spot=11, mill=14, grade_code="SHRED_STEEL",
    )
    # Manually close the hedge before settling.
    validate_success(api.close_hedge(built["hedge"]["id"], SA))
    resp = api.settle_mill_shipment(
        built["shipment"]["id"],
        {"final_settlement_cents": 100000,
         "expected_hedge_version": built["hedge_version"]},
        SA,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_mill_shipment(built["shipment"]["id"], SA))
    assert after["status"] == "SHIPPED", f"shipment must remain SHIPPED, got {after['status']}"


# ---------------------------------------------------------------------------
# Second tests for ≥2-per-instance difficulty coverage
# ---------------------------------------------------------------------------
def test_seller_frozen_on_settle_leaves_payout_pending(api):
    """PRD §3.5: "Settling requires the payout to be `PENDING` and the seller to be
    `ACTIVE` (a seller who became frozen between creation and settlement blocks the
    settle with `ERR_SELLER_FROZEN`)."
    PRD §3.5: "if not, the settle is rejected with `ERR_TIN_REQUIRED_FOR_1099` (HTTP
    422) and no funds are disbursed."

    When both seller-frozen and the missing-TIN gate hold, the rejected settle leaves
    the payout PENDING (no disbursement) — verifying the blocked side effect.

    Design: Difficulty/priority_pair_validation_conflict/seller_frozen_beats_tin_required_on_settle
    """
    publish_price("CU_BARE_BRIGHT", "NON_FERROUS", spot=700, mill=720)
    seller = register_seller(legal_name="Frozen2 Co", id_type="STATE_ID", id_number="SID-8B")
    built = create_released_ticket(
        grade_code="CU_BARE_BRIGHT", category="NON_FERROUS", spot=700, mill=720,
        weight_lb=100, capacity_lb=5000, seller_id=seller["id"],
    )
    payout = validate_success(
        api.create_payout({"ticket_id": built["ticket"]["id"], "method": "CASH"}, PC), 201
    )
    validate_success(
        api.create_theft_report(
            {"seller_id": seller["id"], "reason": "post-release tip",
             "ticket_id": built["ticket"]["id"]}, CO), 201
    )
    resp = api.settle_payout(payout["id"], PC)
    validate_error(resp, ApiErrorId.ERR_SELLER_FROZEN.value)
    after = validate_success(api.get_payout(payout["id"], PC))
    assert after["status"] == "PENDING", \
        f"rejected settle must leave payout PENDING, got {after['status']}"


def test_tin_1099_threshold_pays_ticket_on_trigger(api):
    """PRD §3.5: "A successful cash settlement thus performs a coordinated ledger
    sync — incrementing `ytd_cash_paid_cents`, recomputing `requires_1099`, and
    setting `form_1099_issued` — and as its final cross-entity effect transitions the
    underlying ticket `RELEASED → PAID`."

    The exact-60000 CASH settle (which triggers the 1099 flags) also drives the
    ticket to its terminal PAID state.

    Design: Difficulty/boundary_precision_check/tin_1099_threshold_exact_60000_triggers
    """
    publish_price("BRASS", "NON_FERROUS", spot=100, mill=110)
    seller = register_seller(legal_name="Edge2 Co", id_type="STATE_ID",
                             id_number="SID-9B", tin="99-9999999")
    built = create_released_ticket(
        grade_code="BRASS", category="NON_FERROUS", spot=100, mill=110,
        weight_lb=600, capacity_lb=5000, seller_id=seller["id"],
    )
    payout = validate_success(
        api.create_payout({"ticket_id": built["ticket"]["id"], "method": "CASH"}, PC), 201
    )
    validate_success(api.settle_payout(payout["id"], PC))
    ticket = validate_success(api.get_ticket(built["ticket"]["id"], WM))
    assert ticket["status"] == "PAID", \
        f"settled ticket must reach PAID, got {ticket['status']}"


def test_weigh_out_blocked_on_empty_lines_does_not_freeze_valuation(api):
    """PRD §3.3: "a weigh-out on a ticket with zero lines is rejected with
    `ERR_NO_LINE_ITEMS` (HTTP 409)."
    PRD §3.3: "The ticket is created in `DRAFT` with `gross_valuation_cents` at 0."

    The rejected weigh-out leaves the ticket DRAFT with gross_valuation_cents still 0.

    Design: Difficulty/boundary_precision_check/weigh_out_blocked_on_empty_line_item_set
    """
    seller = register_seller(legal_name="Empty2 Co", id_type="STATE_ID", id_number="SID-10B")
    ticket = open_ticket(seller["id"], gross_weight_lb=1500)
    resp = api.weigh_out(ticket["id"], {"tare_weight_lb": 200}, WM)
    validate_error(resp, ApiErrorId.ERR_NO_LINE_ITEMS.value)
    after = validate_success(api.get_ticket(ticket["id"], WM))
    assert after["status"] == "DRAFT"
    assert after["gross_valuation_cents"] == 0, \
        f"blocked weigh-out must not freeze valuation, got {after['gross_valuation_cents']}"


def test_release_blocked_by_banned_seller(api):
    """PRD §3.4: "a `FLAGGED` or `BANNED` seller, or a seller with
    `open_theft_reports` greater than 0, blocks the release with
    `ERR_SELLER_FROZEN`."

    A BANNED seller (a different Seller state than FLAGGED) likewise blocks release.

    Design: Difficulty/cross_entity_state_dependency/ticket_release_requires_seller_active
    """
    built = create_weighed_ticket(grade_code="SHRED_STEEL", category="FERROUS",
                                  spot=11, mill=14, weight_lb=100)
    container = stage_container("FERROUS", capacity_lb=5000)
    validate_success(api.ban_seller(built["seller_id"], CO))
    resp = api.release_ticket(built["ticket"]["id"], {"container_id": container["id"]}, WM)
    validate_error(resp, ApiErrorId.ERR_SELLER_FROZEN.value)
    after = validate_success(api.get_ticket(built["ticket"]["id"], WM))
    assert after["status"] == "WEIGHED", f"ticket must remain WEIGHED, got {after['status']}"


def test_settle_against_open_hedge_succeeds(api):
    """PRD §3.7: "The referenced hedge must be `OPEN`, its `category` must match the
    shipment's `category`, and its `version` must equal `expected_hedge_version`."
    PRD §3.7: "The shipment moves `SHIPPED → SETTLED`."

    The positive arm of the MillShipment<-HedgePosition dependency: settling against
    an OPEN hedge of matching category succeeds.

    Design: Difficulty/cross_entity_state_dependency/shipment_settle_requires_hedge_open
    """
    built = fixtures.create_shipped_shipment_with_hedge(
        hedged_weight_lb=1300, locked_price=90, category="FERROUS",
        weight_lb=1000, gross_weight_lb=1500, tare_weight_lb=200,
        spot=11, mill=14, grade_code="SHRED_STEEL",
    )
    data = validate_success(
        api.settle_mill_shipment(
            built["shipment"]["id"],
            {"final_settlement_cents": 100000,
             "expected_hedge_version": built["hedge_version"]},
            SA,
        )
    )
    assert data["status"] == "SETTLED", \
        f"settle against OPEN hedge must succeed, got {data['status']}"
