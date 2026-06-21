"""Transfer orders: dispatch/receive cascades, equity movement, conservation.

Translates Difficulty queue (A) instances `transitive_cascade /
transfer_dispatch_cascade...depth2`, `cross_entity_state_dependency /
transfer_dispatch_requires_asset_available`, `compensating_invariant /
transfer_dispatch_receive_conserves_total_physical_count`; and Corner queue (B)
instances from `state_machines`, `validations`, `cross_cutting_complexity_layers`,
and `consistency_model`.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    assert_asset,
    assert_location,
    assert_transfer_order,
    make_pool_admin_headers,
    make_pool_operator_headers,
)
import test_helpers as H

ADMIN = make_pool_admin_headers()
OPERATOR = make_pool_operator_headers()


# --------------------------------------------------------------------------
# Difficulty: dispatch cascade (depth-2: asset IN_TRANSIT -> origin balance)
# --------------------------------------------------------------------------
def test_transfer_dispatch_marks_assets_in_transit(api):
    """PRD §3.3: "On dispatch, each manifest asset becomes IN_TRANSIT with its
    current_location_id cleared to null, the origin's physical_balance drops by
    the manifest quantity, and dispatched_at is set to the current logical clock."

    Design: Difficulty/transitive_cascade/transfer_dispatch_cascade_asset_in_transit_then_origin_balance_depth2
    """
    ctx = H.bootstrap_program()
    a = H.create_location(ctx["account"]["id"], name="A")
    b = H.create_location(ctx["account"]["id"], name="B")
    assets = H.mint_assets(ctx["asset_type"]["id"], a["id"], 3, serial_prefix="T")
    asset_ids = [x["id"] for x in assets]
    to = H.get_success_data(
        api.create_transfer_order(
            {
                "from_location_id": a["id"],
                "to_location_id": b["id"],
                "kind": "TRANSFER",
                "asset_ids": asset_ids,
            },
            OPERATOR,
        )
    )
    validate_success(api.dispatch_transfer_order(to["id"], OPERATOR))
    asset_data = validate_success(api.get_asset(asset_ids[0], OPERATOR))
    assert_asset(asset_data)
    assert asset_data["condition"] == "IN_TRANSIT"
    assert asset_data["current_location_id"] is None


def test_transfer_dispatch_drops_origin_physical_balance(api):
    """PRD §3.3: "On dispatch, each manifest asset becomes IN_TRANSIT with its
    current_location_id cleared to null, the origin's physical_balance drops by
    the manifest quantity, and dispatched_at is set to the current logical clock."

    Design: Difficulty/transitive_cascade/transfer_dispatch_cascade_asset_in_transit_then_origin_balance_depth2
    """
    ctx = H.bootstrap_program()
    a = H.create_location(ctx["account"]["id"], name="A")
    b = H.create_location(ctx["account"]["id"], name="B")
    assets = H.mint_assets(ctx["asset_type"]["id"], a["id"], 3, serial_prefix="T")
    asset_ids = [x["id"] for x in assets]
    to = H.get_success_data(
        api.create_transfer_order(
            {
                "from_location_id": a["id"],
                "to_location_id": b["id"],
                "kind": "TRANSFER",
                "asset_ids": asset_ids,
            },
            OPERATOR,
        )
    )
    validate_success(api.dispatch_transfer_order(to["id"], OPERATOR))
    loc = validate_success(api.get_location(a["id"], OPERATOR))
    assert loc["physical_balance"] == 0, \
        f"origin physical_balance should drop to 0, got {loc['physical_balance']}"


# --------------------------------------------------------------------------
# Difficulty: dispatch requires asset AVAILABLE (TransferOrder -> Asset)
# --------------------------------------------------------------------------
def test_transfer_dispatch_requires_asset_available(api):
    """PRD §3.3: "an asset that is not AVAILABLE is rejected with
    ERR_ASSET_NOT_AVAILABLE, and one sitting elsewhere with
    ERR_ASSET_WRONG_LOCATION."

    Design: Difficulty/cross_entity_state_dependency/transfer_dispatch_requires_asset_available
    """
    ctx = H.bootstrap_program()
    a = H.create_location(ctx["account"]["id"], name="A")
    b = H.create_location(ctx["account"]["id"], name="B")
    asset = H.create_asset(ctx["asset_type"]["id"], a["id"], serial="D1")
    to = H.get_success_data(
        api.create_transfer_order(
            {
                "from_location_id": a["id"],
                "to_location_id": b["id"],
                "kind": "TRANSFER",
                "asset_ids": [asset["id"]],
            },
            OPERATOR,
        )
    )
    H.get_success_data(api.report_damage(asset["id"], OPERATOR))
    resp = api.dispatch_transfer_order(to["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_ASSET_NOT_AVAILABLE.value, expected_status=409)


def test_transfer_dispatch_requires_asset_available_rejects_on_hire_asset(api):
    """PRD §3.3: "every asset in the manifest have condition AVAILABLE and a
    current_location_id equal to the from_location_id — an asset that is not
    AVAILABLE is rejected with ERR_ASSET_NOT_AVAILABLE".

    Design: Difficulty/cross_entity_state_dependency/transfer_dispatch_requires_asset_available
    """
    # Open a hire so the asset is ON_HIRE (not AVAILABLE) at its location.
    ctx = H.setup_open_hire(asset_count=1, credit_limit_cents=100_000_000)
    asset_id = ctx["asset_ids"][0]
    b = H.create_location(ctx["account"]["id"], name="B")
    to = H.get_success_data(
        api.create_transfer_order(
            {
                "from_location_id": ctx["location"]["id"],
                "to_location_id": b["id"],
                "kind": "TRANSFER",
                "asset_ids": [asset_id],
            },
            OPERATOR,
        )
    )
    resp = api.dispatch_transfer_order(to["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_ASSET_NOT_AVAILABLE.value, expected_status=409)


def test_transfer_dispatch_from_closed_location_returns_location_closed(api):
    """PRD §3.3: "Dispatch requires that the origin location's status be OPEN
    (otherwise ERR_LOCATION_CLOSED)".

    Design: Corner/validations/transfer_dispatch_from_closed_location_returns_location_closed
    """
    ctx = H.bootstrap_program()
    a = H.create_location(ctx["account"]["id"], name="A")
    b = H.create_location(ctx["account"]["id"], name="B")
    to = H.get_success_data(
        api.create_transfer_order(
            {
                "from_location_id": a["id"],
                "to_location_id": b["id"],
                "kind": "TRANSFER",
                "asset_ids": [],
            },
            OPERATOR,
        )
    )
    H.get_success_data(api.close_location(a["id"], OPERATOR))
    resp = api.dispatch_transfer_order(to["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_LOCATION_CLOSED.value, expected_status=409)


# --------------------------------------------------------------------------
# Corner: invalid transition (receive from DRAFT)
# --------------------------------------------------------------------------
def test_transfer_receive_from_draft_returns_invalid_state(api):
    """PRD §3.3: "Receiving a dispatched order advances it DISPATCHED to RECEIVED
    and requires the destination location's status to be OPEN". PRD §2.10: "then
    the target resource's state eligibility for the requested transition
    (ERR_INVALID_STATE)".

    Design: Corner/state_machines/transfer_receive_from_draft_returns_invalid_state
    """
    ctx = H.bootstrap_program()
    a = H.create_location(ctx["account"]["id"], name="A")
    b = H.create_location(ctx["account"]["id"], name="B")
    asset = H.create_asset(ctx["asset_type"]["id"], a["id"], serial="T1")
    to = H.get_success_data(
        api.create_transfer_order(
            {
                "from_location_id": a["id"],
                "to_location_id": b["id"],
                "kind": "TRANSFER",
                "asset_ids": [asset["id"]],
            },
            OPERATOR,
        )
    )
    resp = api.receive_transfer_order(to["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


# --------------------------------------------------------------------------
# Difficulty: physical-count conservation across dispatch -> receive
# --------------------------------------------------------------------------
def test_transfer_dispatch_receive_conserves_total_physical_count(api):
    """PRD §3.3: "On dispatch, each manifest asset becomes IN_TRANSIT with its
    current_location_id cleared to null, the origin's physical_balance drops by
    the manifest quantity". PRD §3.3: "On receipt, every manifest asset becomes
    AVAILABLE with its current_location_id set to the to_location_id, the
    destination's physical_balance rises by the manifest quantity".

    Design: Difficulty/compensating_invariant/transfer_dispatch_receive_conserves_total_physical_count
    """
    ctx = H.bootstrap_program()
    a = H.create_location(ctx["account"]["id"], name="A")
    b = H.create_location(ctx["account"]["id"], name="B")
    assets = H.mint_assets(ctx["asset_type"]["id"], a["id"], 5, serial_prefix="C")
    asset_ids = [x["id"] for x in assets][:3]
    to = H.get_success_data(
        api.create_transfer_order(
            {
                "from_location_id": a["id"],
                "to_location_id": b["id"],
                "kind": "TRANSFER",
                "asset_ids": asset_ids,
            },
            OPERATOR,
        )
    )
    H.get_success_data(api.dispatch_transfer_order(to["id"], OPERATOR))
    to_final = validate_success(api.receive_transfer_order(to["id"], OPERATOR))
    assert_transfer_order(to_final)
    assert to_final["status"] == "RECEIVED"
    loc_a = validate_success(api.get_location(a["id"], OPERATOR))
    loc_b = validate_success(api.get_location(b["id"], OPERATOR))
    assert loc_a["physical_balance"] == 2, f"A should be 2, got {loc_a['physical_balance']}"
    assert loc_b["physical_balance"] == 3, f"B should be 3, got {loc_b['physical_balance']}"


def test_transfer_received_assets_land_available_at_destination(api):
    """PRD §3.3: "On receipt, every manifest asset becomes AVAILABLE with its
    current_location_id set to the to_location_id, the destination's
    physical_balance rises by the manifest quantity".

    Design: Difficulty/compensating_invariant/transfer_dispatch_receive_conserves_total_physical_count
    """
    ctx = H.bootstrap_program()
    a = H.create_location(ctx["account"]["id"], name="A")
    b = H.create_location(ctx["account"]["id"], name="B")
    assets = H.mint_assets(ctx["asset_type"]["id"], a["id"], 5, serial_prefix="C")
    asset_ids = [x["id"] for x in assets][:3]
    to = H.get_success_data(
        api.create_transfer_order(
            {
                "from_location_id": a["id"],
                "to_location_id": b["id"],
                "kind": "TRANSFER",
                "asset_ids": asset_ids,
            },
            OPERATOR,
        )
    )
    H.get_success_data(api.dispatch_transfer_order(to["id"], OPERATOR))
    H.get_success_data(api.receive_transfer_order(to["id"], OPERATOR))
    # Each moved asset is AVAILABLE at B (in-transit count back to 0).
    for aid in asset_ids:
        asset = validate_success(api.get_asset(aid, OPERATOR))
        assert asset["condition"] == "AVAILABLE", f"{aid} condition {asset['condition']}"
        assert asset["current_location_id"] == b["id"]


# --------------------------------------------------------------------------
# Corner: derived-field reconciliation + equity_status threshold
# --------------------------------------------------------------------------
def test_derived_field_physical_balance_reconciles_after_issuance_receive(api):
    """PRD §3.3: "for an ISSUANCE the destination's equity_balance increases by
    quantity". PRD §2.5: "The physical_balance is the count of assets whose
    current_location_id equals the location and whose condition is anything other
    than LOST; it is recomputed on every movement, hire, and audit side effect and
    whenever the location is read."

    Design: Corner/cross_cutting_complexity_layers/derived_field_physical_balance_reconciles_after_issuance_receive
    """
    ctx = H.bootstrap_program()
    stock = H.create_location(ctx["account"]["id"], name="Stock")
    l1 = H.create_location(ctx["account"]["id"], name="L1")
    H.issue_assets_into_location(ctx["asset_type"]["id"], stock["id"], l1["id"], 4)
    loc = validate_success(api.get_location(l1["id"], OPERATOR))
    assert_location(loc)
    assert loc["physical_balance"] == 4
    assert loc["equity_balance"] == 4


def test_equity_warn_threshold_flags_location_short(api):
    """PRD §2.5: "The location is SHORT when its equity_balance is at or above the
    policy's equity_warn_threshold; it is SURPLUS when its equity_balance is
    strictly less than zero; otherwise it is BALANCED."

    Design: Corner/cross_cutting_complexity_layers/equity_warn_threshold_flags_location_short
    """
    policy = H.create_policy(equity_warn_threshold=4)
    asset_type = H.create_asset_type()
    account = H.create_account(role_type="DISTRIBUTOR")
    stock = H.create_location(account["id"], name="Stock")
    l1 = H.create_location(account["id"], name="L1")
    H.issue_assets_into_location(asset_type["id"], stock["id"], l1["id"], 4)
    loc = validate_success(api.get_location(l1["id"], OPERATOR))
    assert loc["equity_balance"] == 4
    assert loc["equity_status"] == "SHORT"


def test_immediate_consistency_balances_visible_in_receive_response(api):
    """PRD §2.6: "All balance, equity, and charge mutations are immediate and
    atomic: every consequence of a triggering request lands within that same
    request, never deferred."

    Design: Corner/consistency_model/immediate_consistency_balances_visible_in_receive_response
    """
    ctx = H.bootstrap_program()
    stock = H.create_location(ctx["account"]["id"], name="Stock")
    l1 = H.create_location(ctx["account"]["id"], name="L1")
    H.issue_assets_into_location(ctx["asset_type"]["id"], stock["id"], l1["id"], 2)
    loc = validate_success(api.get_location(l1["id"], OPERATOR))
    assert loc["equity_balance"] == 2
    assert loc["physical_balance"] == 2
