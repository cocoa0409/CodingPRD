"""Optimistic-concurrency guards, version increments, RBAC isolation, and immediate
consistency.

Queue B (Corner) — cross_cutting_complexity_layers (OCC settlement, OCC meet-call,
                   version increment), rbac (peer-role isolation + shared read),
                   consistency_model (immediate cascade visibility).
"""
from test_helpers import validate_success, validate_error, ApiErrorId, TEST_USERS
import test_helpers.fixtures as fx

MERCH = TEST_USERS["merchandiser_headers"]
CLERK = TEST_USERS["grade_clerk_headers"]
OFFICER = TEST_USERS["settlement_officer_headers"]
SHIPPER = TEST_USERS["shipping_clerk_headers"]
RISK = TEST_USERS["risk_manager_headers"]


def test_settlement_post_stale_position_after_prior_post_returns_412(api):
    """PRD §2.10: "if they do not match — because a prior settlement post or a shipment
    load already drew down that position's `bushels_available` and advanced its `version`
    since the client read it — the post is rejected with `ERR_STALE_VERSION` (HTTP 412).
    This prevents a second post that still carries the old version from over-drawing a
    position whose available bushels it has not actually observed."

    Design: Corner/cross_cutting_complexity_layers/settlement_post_stale_position_version_returns_412
    """
    fx.reset_clock_default()
    commodity = fx.create_commodity()
    fx.create_price_board(commodity["id"])
    member = fx.create_member(name="PP Farm")
    _, _, _graded, position = fx.create_graded_position(
        commodity_id=commodity["id"], member_id=member["id"], member_name="PP Farm",
    )
    contract = fx.create_priced_cash_contract(member["id"], commodity["id"], contracted_bushels=1000)
    st1 = fx.create_draft_settlement(contract["id"], position["id"], priced_bushels=400)
    st2 = fx.create_draft_settlement(contract["id"], position["id"], priced_bushels=300)
    pos0 = validate_success(api.get_storage_position(position["id"], OFFICER))
    v0 = pos0["version"]
    # first post advances the position version
    validate_success(api.post_settlement(st1["id"], {"expected_storage_position_version": v0}, OFFICER))
    # second post still carries the pre-post version
    resp = api.post_settlement(st2["id"], {"expected_storage_position_version": v0}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
    st2_after = validate_success(api.get_settlement(st2["id"], OFFICER))
    pos_after = validate_success(api.get_storage_position(position["id"], OFFICER))
    assert st2_after["status"] == "DRAFT"
    assert pos_after["bushels_available"] == 600.0


def test_meet_call_stale_hedge_version_after_mark_returns_412(api):
    """PRD §2.10: "The server compares it against the position's current `version`; if they
    do not match — because a new mark moved the call amount (or cleared the call entirely)
    and advanced the position's `version` since the client read it — the meet-call is
    rejected with `ERR_STALE_VERSION` (HTTP 412), because it is acting on a stale call
    figure."

    Design: Corner/cross_cutting_complexity_layers/meet_call_stale_hedge_version_returns_412
    """
    commodity = fx.create_commodity()
    hedge = fx.open_hedge(commodity["id"], side="SHORT", contracts=3, entry_futures_price=4.50)
    # Mark 4.80 drives the SHORT into MARGIN_CALL: pnl = (4.50-4.80)*5000*3 = -4500,
    # equity = 6000-4500 = 1500 < maintenance 4500 -> call = 6000-1500 = 4500.
    validate_success(api.mark_hedge_position(hedge["id"], {"mark_futures_price": 4.80}, RISK))
    hp_pre = validate_success(api.get_hedge_position(hedge["id"], RISK))
    stale_version = hp_pre["version"]
    # Advance the position's version legally (PRD §3.8 forbids marking a non-OPEN
    # position): meet the call back to OPEN, then a fresh mark re-triggers a call.
    fx.meet_call(hedge["id"], deposit_dollars=4500)  # posted -> 10500, status OPEN
    # Mark 4.95 (OPEN): pnl = (4.50-4.95)*5000*3 = -6750, equity = 10500-6750 = 3750
    # < maintenance 4500 -> back into MARGIN_CALL with an advanced version.
    validate_success(api.mark_hedge_position(hedge["id"], {"mark_futures_price": 4.95}, RISK))
    # meet-call still carries the pre-advance (stale) version -> 412.
    resp = api.meet_call(
        hedge["id"],
        {"deposit_dollars": 9000, "expected_hedge_position_version": stale_version},
        RISK,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
    after = validate_success(api.get_hedge_position(hedge["id"], RISK))
    assert after["status"] == "MARGIN_CALL"


def test_version_increments_on_grade_mutation(api):
    """PRD §2.4: "an integer `version` that begins at 1 on creation and increments by
    exactly 1 on each mutation." PRD §3.2: "the ticket moves to `GRADED`, bumping the
    ticket's version."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_grade_mutation
    """
    commodity = fx.create_commodity()
    member = fx.create_member(name="QQ Farm")
    ticket = fx.create_weighed_ticket(member["id"], commodity["id"])
    assert ticket["version"] == 1
    graded = fx.grade_ticket(ticket["id"])
    assert graded["version"] == 2, f"version must be 2 after grade, got {graded['version']}"


def test_gradeclerk_cannot_post_settlement_returns_forbidden(api):
    """PRD §2.1: "If the role is recognized but is not permitted to perform the requested
    operation under the access-control matrix below, the request is rejected with
    `ERR_FORBIDDEN` (HTTP 403)." PRD §2.1: "A `SettlementOfficer` exclusively drafts
    settlements, posts them, and cancels them."

    Design: Corner/rbac/rbac_gradeclerk_cannot_post_settlement_returns_forbidden
    """
    fx.reset_clock_default()
    commodity = fx.create_commodity()
    fx.create_price_board(commodity["id"])
    member = fx.create_member(name="OO Farm")
    _, _, _graded, position = fx.create_graded_position(
        commodity_id=commodity["id"], member_id=member["id"], member_name="OO Farm",
    )
    contract = fx.create_priced_cash_contract(member["id"], commodity["id"], contracted_bushels=1000)
    # GradeClerk attempts a SettlementOfficer-exclusive op
    resp = api.create_settlement(
        {
            "contract_id": contract["id"], "storage_position_id": position["id"],
            "priced_bushels": 600, "storage_basis": "ACTUAL",
        },
        CLERK,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_shippingclerk_cannot_open_hedge_returns_forbidden(api):
    """PRD §2.1: "A `RiskManager` exclusively opens hedge positions, applies marks, meets
    margin calls, and closes positions." PRD §2.1: "the request is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/rbac_shippingclerk_cannot_open_hedge_returns_forbidden
    """
    commodity = fx.create_commodity()
    resp = api.create_hedge_position(
        {"commodity_id": commodity["id"], "side": "SHORT", "contracts": 1, "entry_futures_price": 4.50},
        SHIPPER,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_settlement_officer_shared_read_commodity_allowed(api):
    """PRD §2.1: "These are peer roles: each owns an exclusive set of write operations, and
    all five share broad read access to the resources relevant to their work."

    Design: Corner/rbac/rbac_shared_get_commodity_allowed_for_settlementofficer
    """
    commodity = fx.create_commodity(symbol="CORN")
    resp = api.get_commodity(commodity["id"], OFFICER)
    data = validate_success(resp)
    assert data["symbol"] == "CORN"


def test_settlement_post_cascades_visible_immediately(api):
    """PRD §2.8: "The governing principle is that these cascades are atomic with the
    triggering operation". PRD §3.5: "the member's `cash_paid_dollars` is increased by the
    net proceeds and the member's `net_priced_bushels` is increased by the priced
    bushels".

    Design: Corner/consistency_model/immediate_consistency_settlement_post_reflects_all_cascades_in_response
    """
    fx.reset_clock_default()
    commodity = fx.create_commodity()
    fx.create_price_board(commodity["id"])
    member = fx.create_member(name="RR Farm")
    _, _, _graded, position = fx.create_graded_position(
        commodity_id=commodity["id"], member_id=member["id"], member_name="RR Farm",
    )
    contract = fx.create_priced_cash_contract(member["id"], commodity["id"], contracted_bushels=1000)
    fx.set_clock("2026-02-15T00:00:00Z")  # 15 chargeable days
    settlement = fx.create_draft_settlement(
        contract["id"], position["id"], priced_bushels=1000, storage_basis="ACTUAL"
    )
    posted = fx.post_settlement(settlement["id"], position["id"])
    # gross 4700.00 minus storage 7.50 (1000 * 0.0005 * 15) = 4692.50
    assert posted["net_proceeds_dollars"] == 4692.50

    member_after = validate_success(api.get_member(member["id"], OFFICER))
    pos_after = validate_success(api.get_storage_position(position["id"], OFFICER))
    assert member_after["cash_paid_dollars"] == 4692.50
    assert member_after["net_priced_bushels"] == 1000
    assert pos_after["bushels_available"] == 0
    assert pos_after["status"] == "DEPLETED"
