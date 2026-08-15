"""Order confirmation gates and the request validation pipeline (PRD §2.10, §3.2)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_line,
    create_az_rule,
    create_dealer,
    create_draft_order,
    create_order_line_payload,
    get_success_data,
    setup_confirmed_order,
    setup_mn_catalog,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["plant_manager_headers"]


def test_confirm_order_without_lines_returns_error(api):
    """PRD §3.2: "An order with no non-`CANCELLED` lines cannot be confirmed at
    all (`ERR_ORDER_HAS_NO_LINES`)."

    Design: Corner/state_machines/confirm_order_without_lines_returns_error
    """
    dealer = create_dealer()
    order = create_draft_order(dealer["id"])
    res = api.confirm_order(order["id"], PM)
    validate_error(res, ApiErrorId.ERR_ORDER_HAS_NO_LINES, expected_status=409)
    fetched = validate_success(api.get_order(order["id"], PM), 200)
    assert fetched["production_status"] == "DRAFT"


def test_double_confirm_returns_invalid_state(api):
    """PRD §2.10: "Any transition attempted from a state in which it is not
    defined is rejected with `ERR_INVALID_STATE` unless a more specific state
    error applies."

    Design: Corner/state_machines/double_confirm_returns_invalid_state
    """
    env = setup_confirmed_order()
    res = api.confirm_order(env["order"]["id"], PM)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_cancelled_order_terminal_lockdown(api):
    """PRD §3.8: "Delivered and already-cancelled orders are terminal and accept
    no further transitions."
    PRD §2.10: "Any transition attempted from a state in which it is not defined
    is rejected with `ERR_INVALID_STATE` unless a more specific state error
    applies."

    Design: Corner/state_machines/cancelled_order_terminal_lockdown
    """
    cat = setup_mn_catalog()
    order = create_draft_order(cat["dealer"]["id"])
    add_line(order["id"], cat["series"]["id"], cat["glass"]["id"])
    validate_success(api.cancel_order(order["id"], PM), 200)
    res = api.confirm_order(order["id"], PM)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_line_add_to_confirmed_order_returns_not_draft(api):
    """PRD §3.2: "Lines are added only while the order is `DRAFT` — adding or
    editing a line on a confirmed-or-later order is rejected with
    `ERR_ORDER_NOT_DRAFT`."

    Design: Corner/validations/line_add_to_confirmed_order_returns_not_draft
    """
    env = setup_confirmed_order()
    res = api.add_order_line(
        env["order"]["id"],
        create_order_line_payload(env["series"]["id"], env["glass"]["id"],
                                  width_in=30, height_in=30),
        PM,
    )
    validate_error(res, ApiErrorId.ERR_ORDER_NOT_DRAFT, expected_status=409)


def test_credit_hold_blocks_confirm_direct(api):
    """PRD §3.1: "While a dealer sits on `CREDIT_HOLD`, confirming any of its
    orders is rejected with `ERR_DEALER_CREDIT_HOLD`; nothing else about the
    dealer's records changes."
    PRD §3.1: "Credit control is a cyclic mini-lifecycle: the `PlantManager` may
    place a dealer on `CREDIT_HOLD` and later release it back to `ACTIVE`."

    Design: Corner/validations/credit_hold_blocks_confirm_direct
    """
    cat = setup_mn_catalog()
    get_success_data(api.credit_hold_dealer(cat["dealer"]["id"], PM))
    order = create_draft_order(cat["dealer"]["id"])
    add_line(order["id"], cat["series"]["id"], cat["glass"]["id"])

    blocked = api.confirm_order(order["id"], PM)
    validate_error(blocked, ApiErrorId.ERR_DEALER_CREDIT_HOLD, expected_status=409)
    fetched = validate_success(api.get_order(order["id"], PM), 200)
    assert fetched["production_status"] == "DRAFT"

    get_success_data(api.credit_release_dealer(cat["dealer"]["id"], PM))
    confirmed = validate_success(api.confirm_order(order["id"], PM), 200)
    assert confirmed["production_status"] == "CONFIRMED"


def test_safety_before_fiscal_on_confirm(api):
    """PRD §2.10: "Because of this ordering, an order that would fail both the
    energy-compliance gate and the dealer credit gate at confirm is rejected with
    `ERR_ENERGY_CODE_VIOLATION`, not `ERR_DEALER_CREDIT_HOLD`; and a stale wave
    version surfaces as `ERR_STALE_VERSION` before any state or capacity check
    on the wave itself is reported."

    Design: Difficulty/priority_pair_validation_conflict/safety_before_fiscal_on_confirm
    """
    create_az_rule()  # max_shgc 0.25; the GP1 package's 0.40 fails it
    cat = setup_mn_catalog(dealer_name="Southwest", dealer_state="AZ", with_rule=False)
    get_success_data(api.credit_hold_dealer(cat["dealer"]["id"], PM))
    order = create_draft_order(cat["dealer"]["id"])
    add_line(order["id"], cat["series"]["id"], cat["glass"]["id"])

    res = api.confirm_order(order["id"], PM)
    validate_error(res, ApiErrorId.ERR_ENERGY_CODE_VIOLATION, expected_status=409)


def test_rejected_confirm_leaves_order_draft(api):
    """PRD §3.2: "Confirmation is the order's point of no return. A `DealerRep`
    confirming their own order — or a `PlantManager` — triggers three gates,
    evaluated in pipeline order: every line's energy label must show compliance
    `PASS` or `UNEVALUATED` (a single `FAIL` rejects the confirm with
    `ERR_ENERGY_CODE_VIOLATION`), and the dealer's `credit_status` must be
    `ACTIVE` (`ERR_DEALER_CREDIT_HOLD`)."

    Design: Difficulty/priority_pair_validation_conflict/safety_before_fiscal_on_confirm
    """
    create_az_rule()
    cat = setup_mn_catalog(dealer_name="Southwest", dealer_state="AZ", with_rule=False)
    get_success_data(api.credit_hold_dealer(cat["dealer"]["id"], PM))
    order = create_draft_order(cat["dealer"]["id"])
    add_line(order["id"], cat["series"]["id"], cat["glass"]["id"])

    validate_error(api.confirm_order(order["id"], PM), ApiErrorId.ERR_ENERGY_CODE_VIOLATION)
    fetched = validate_success(api.get_order(order["id"], PM), 200)
    assert fetched["production_status"] == "DRAFT"
    assert fetched["compliance_status"] == "PENDING"


def test_existence_before_state_on_line_patch(api):
    """PRD §2.10: "When several violations are present at once, the error
    returned is the one from the earliest stage in this order — later checks
    never mask earlier ones"
    PRD §2.6: "the server validates the existence of each identifier in path
    order and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first
    identifier that does not correspond to an existing resource"

    Design: Difficulty/priority_pair_validation_conflict/existence_before_state_on_line_patch
    """
    env = setup_confirmed_order()
    validate_success(api.cancel_order(env["order"]["id"], PM), 200)
    order = validate_success(api.get_order(env["order"]["id"], PM), 200)

    res = api.patch_order_line(
        order["id"], NON_EXISTENT_UUID,
        {"expected_order_version": order["version"], "quantity": 2},
        PM,
    )
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_patch_missing_line_not_found_for_owner_dealer(api):
    """PRD §2.6: "When a path contains multiple identifiers (for example,
    `/fenestration/orders/{orderId}/lines/{lineId}`), the server validates the
    existence of each identifier in path order and rejects the request with
    `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond
    to an existing resource."

    Design: Difficulty/priority_pair_validation_conflict/existence_before_state_on_line_patch
    """
    from test_helpers import make_dealer_rep_headers

    cat = setup_mn_catalog()
    order = create_draft_order(cat["dealer"]["id"])
    add_line(order["id"], cat["series"]["id"], cat["glass"]["id"])
    validate_success(api.confirm_order(order["id"], PM), 200)
    validate_success(api.cancel_order(order["id"], PM), 200)
    order = validate_success(api.get_order(order["id"], PM), 200)

    res = api.patch_order_line(
        order["id"], NON_EXISTENT_UUID,
        {"expected_order_version": order["version"], "quantity": 2},
        make_dealer_rep_headers(cat["dealer"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_stale_version_beats_state_on_line_patch(api):
    """PRD §2.10: "When several violations are present at once, the error
    returned is the one from the earliest stage in this order — later checks
    never mask earlier ones" (stage 6 optimistic concurrency precedes stage 7
    state preconditions).
    PRD §2.8: "A mismatch with the order's current `version` is rejected with
    `ERR_STALE_VERSION` (HTTP 412), even though the edit itself would be a
    legitimate `DRAFT`-state mutation, because line edits reprice the order and
    advance its version."

    Design: Corner/validations/stale_version_beats_state_on_line_patch
    """
    cat = setup_mn_catalog()
    order = create_draft_order(cat["dealer"]["id"])
    line = add_line(order["id"], cat["series"]["id"], cat["glass"]["id"])
    stale_version = validate_success(api.get_order(order["id"], PM), 200)["version"]
    validate_success(api.confirm_order(order["id"], PM), 200)  # bumps version and leaves DRAFT

    res = api.patch_order_line(
        order["id"], line["id"],
        {"expected_order_version": stale_version, "quantity": 5},
        PM,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


def test_stale_order_version_on_patch_returns_412(api):
    """PRD §2.8: "Reconfiguring an order line while the order is in `DRAFT`
    requires the request to carry `expected_order_version`, the `version` of the
    parent `WindowOrder` the client last observed. A mismatch with the order's
    current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), even
    though the edit itself would be a legitimate `DRAFT`-state mutation, because
    line edits reprice the order and advance its version."

    Design: Corner/cross_cutting_complexity_layers/stale_order_version_on_patch_returns_412
    """
    cat = setup_mn_catalog()
    order = create_draft_order(cat["dealer"]["id"])
    line = add_line(order["id"], cat["series"]["id"], cat["glass"]["id"])
    observed = validate_success(api.get_order(order["id"], PM), 200)["version"]

    first = validate_success(api.patch_order_line(
        order["id"], line["id"],
        {"expected_order_version": observed, "quantity": 2},
        PM,
    ), 200)
    assert first["line_total_cents"] == 330006  # repriced 165003 x 2

    replay = api.patch_order_line(
        order["id"], line["id"],
        {"expected_order_version": observed, "quantity": 3},
        PM,
    )
    validate_error(replay, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    after = validate_success(api.get_order(order["id"], PM), 200)
    assert after["version"] == observed + 1, (
        f"only the accepted edit may advance the order version: {observed} -> {after['version']}"
    )
