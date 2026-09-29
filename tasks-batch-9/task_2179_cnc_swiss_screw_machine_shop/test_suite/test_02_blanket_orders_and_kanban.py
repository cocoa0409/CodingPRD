"""The committed-quantity ledger: releases, short-closes, suspension and expiry."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_po_quantity_ledger,
    blanket_po_version,
    cut_release,
    machine_version,
    make_shop_planner_headers,
    read_blanket_po,
    read_release,
    read_work_order,
    schedule_work_order,
    set_clock,
    setup_shop_floor,
    start_work_order,
    validate_error,
    validate_success,
)

PLANNER = make_shop_planner_headers()


def _release_body(po_id, qty, version, due_at="2026-09-10T00:00:00Z"):
    return {
        "blanket_po_id": po_id,
        "qty": qty,
        "due_at": due_at,
        "expected_blanket_po_version": version,
    }


class TestReleaseGateOrder:
    """A release that trips several gates reports exactly one of them."""

    def test_suspended_order_reports_not_active_rather_than_qty_exceeded(self):
        """PRD 3.4: "Several gates guard the draw and they fire in this order:
        the named order must be in `ACTIVE` status, and a `SUSPENDED`,
        `EXHAUSTED` or `EXPIRED` order is rejected with `ERR_PO_NOT_ACTIVE` (HTTP
        409); then the logical clock must be strictly before the order's
        `expires_on`, and when it stands at or after that instant the order is
        moved `ACTIVE → EXPIRED`, its `version` is incremented by one, and the
        release request that triggered the re-evaluation is rejected with
        `ERR_PO_EXPIRED` (HTTP 409); then the requested `qty` must not exceed the
        order's `remaining_qty`, and a larger request is rejected with
        `ERR_PO_QTY_EXCEEDED` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/suspended_po_beats_qty_exceeded
        """
        shop = setup_shop_floor(with_release=False)
        validate_success(
            api_client.suspend_blanket_po(shop.po_id, {"reason": "CREDIT_HOLD"}, PLANNER), 200
        )
        version = blanket_po_version(shop.po_id)

        response = api_client.create_kanban_release(
            _release_body(shop.po_id, 500, version), PLANNER
        )
        error = validate_error(response, ApiErrorId.ERR_PO_NOT_ACTIVE.value)
        assert error["error_id"] != ApiErrorId.ERR_PO_QTY_EXCEEDED.value

    def test_release_refused_on_a_suspended_order_moves_no_pieces(self):
        """PRD 3.4: "Suspension does not touch existing kanban releases in any
        way — work already on the floor runs to completion — it only blocks new
        ones."
        PRD 2.7: "At every instant, `remaining_qty` plus `open_released_qty` plus
        `fulfilled_qty` equals `total_committed_qty` exactly."

        Design: Difficulty/priority_pair_validation_conflict/suspended_po_beats_qty_exceeded
        """
        shop = setup_shop_floor(with_release=False)
        validate_success(
            api_client.suspend_blanket_po(shop.po_id, {"reason": "CREDIT_HOLD"}, PLANNER), 200
        )
        version = blanket_po_version(shop.po_id)
        api_client.create_kanban_release(_release_body(shop.po_id, 500, version), PLANNER)

        po = read_blanket_po(shop.po_id)
        assert po["remaining_qty"] == 200
        assert po["open_released_qty"] == 0
        assert po["status"] == "SUSPENDED"
        assert_po_quantity_ledger(po)


class TestCommittedQuantityConservation:
    """Pieces move between the three buckets and are never created or lost."""

    def test_release_draws_pieces_from_remaining_into_open_released(self):
        """PRD 3.4: "The draw moves pieces on the ledger immediately: the
        released quantity is subtracted from the order's `remaining_qty` and added
        to its `open_released_qty`, and the order's `version` is incremented by
        one."
        PRD 2.7: "At every instant, `remaining_qty` plus `open_released_qty` plus
        `fulfilled_qty` equals `total_committed_qty` exactly."

        Design: Difficulty/compensating_invariant/po_quantity_conserved_across_release_and_short_close
        """
        shop = setup_shop_floor(committed_qty=700, release_qty=200)

        po = read_blanket_po(shop.po_id)
        assert po["remaining_qty"] == 500
        assert po["open_released_qty"] == 200
        assert po["fulfilled_qty"] == 0
        assert po["total_committed_qty"] == 700
        assert_po_quantity_ledger(po)

    def test_short_close_returns_the_entire_quantity_to_the_remaining_pool(self):
        """PRD 3.4: "Short-closing is the compensating action, performed by a
        `ShopPlanner` with a `reason` that is recorded as the release's
        `close_reason`."
        PRD 3.4: "In both cases the release moves to `SHORT_CLOSED`, its entire
        released quantity is subtracted from the order's `open_released_qty` and
        added back to its `remaining_qty` leaving `total_committed_qty` conserved,
        and the order's `version` is incremented by one."

        Design: Difficulty/compensating_invariant/po_quantity_conserved_across_release_and_short_close
        """
        shop = setup_shop_floor(committed_qty=700, release_qty=200)

        closed = validate_success(
            api_client.short_close_release(
                shop.release_id, {"reason": "CUSTOMER_DEFERRAL"}, PLANNER
            ),
            200,
        )
        assert closed["status"] == "SHORT_CLOSED"
        assert closed["close_reason"] == "CUSTOMER_DEFERRAL"
        assert closed["fulfilled_qty"] == 0

        po = read_blanket_po(shop.po_id)
        assert po["remaining_qty"] == 700
        assert po["open_released_qty"] == 0
        assert po["fulfilled_qty"] == 0
        assert po["total_committed_qty"] == 700
        assert po["status"] == "ACTIVE"
        assert_po_quantity_ledger(po)


def test_release_larger_than_remaining_quantity_is_rejected():
    """PRD 3.4: "then the requested `qty` must not exceed the order's
    `remaining_qty`, and a larger request is rejected with `ERR_PO_QTY_EXCEEDED`
    (HTTP 409)."

    Design: Corner/validations/release_qty_above_remaining_returns_po_qty_exceeded
    """
    shop = setup_shop_floor(with_release=False)
    version = blanket_po_version(shop.po_id)

    response = api_client.create_kanban_release(
        _release_body(shop.po_id, 201, version), PLANNER
    )
    validate_error(response, ApiErrorId.ERR_PO_QTY_EXCEEDED.value)

    po = read_blanket_po(shop.po_id)
    assert po["remaining_qty"] == 200
    assert po["open_released_qty"] == 0


def test_release_for_exactly_the_remaining_quantity_is_admitted():
    """PRD 3.4: "then the requested `qty` must not exceed the order's
    `remaining_qty`, and a larger request is rejected with `ERR_PO_QTY_EXCEEDED`
    (HTTP 409)."
    PRD 3.4: "A release that clears those gates opens in `status` `RELEASED` —
    one of `RELEASED`, `IN_PRODUCTION`, `FULFILLED` and `SHORT_CLOSED` — with
    `fulfilled_qty` at 0 and `close_reason` null."

    Design: Corner/validations/release_exactly_at_remaining_qty_succeeds
    """
    shop = setup_shop_floor(with_release=False)
    version = blanket_po_version(shop.po_id)

    release = validate_success(
        api_client.create_kanban_release(_release_body(shop.po_id, 200, version), PLANNER), 201
    )
    assert release["status"] == "RELEASED"
    assert release["qty"] == 200

    po = read_blanket_po(shop.po_id)
    assert po["remaining_qty"] == 0
    assert po["open_released_qty"] == 200
    assert po["status"] == "ACTIVE"


def test_second_short_close_on_a_closed_release_is_rejected():
    """PRD 3.4: "It is declared from two states. From `RELEASED`, short-close is
    permitted only when no work order on the release has a `machining_status` of
    `RUNNING`, `INTERRUPTED` or `MACHINING_COMPLETE`."
    PRD 2.9: "After those comes the generic state check: the target resource must
    be in a state from which the requested transition is declared, otherwise
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/short_close_on_already_short_closed_release_returns_invalid_state
    """
    shop = setup_shop_floor(committed_qty=700, release_qty=200)
    validate_success(
        api_client.short_close_release(shop.release_id, {"reason": "CUSTOMER_DEFERRAL"}, PLANNER),
        200,
    )

    response = api_client.short_close_release(shop.release_id, {"reason": "DUPLICATE"}, PLANNER)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    po = read_blanket_po(shop.po_id)
    assert po["remaining_qty"] == 700
    assert po["open_released_qty"] == 0
    assert read_release(shop.release_id)["status"] == "SHORT_CLOSED"


def test_suspend_then_reinstate_returns_the_order_to_active():
    """PRD 3.4: "A `ShopPlanner` may suspend an `ACTIVE` order, supplying a
    `reason` that is stored as the order's `suspension_reason`; the order moves
    `ACTIVE → SUSPENDED` and its `version` is incremented by one."
    PRD 3.4: "Reinstating moves the order `SUSPENDED → ACTIVE`, clears
    `suspension_reason` and increments `version` by one; reinstatement
    additionally requires that the logical clock is strictly before the order's
    `expires_on`."

    Design: Corner/endpoints/suspend_and_reinstate_toggle_the_blanket_order
    """
    shop = setup_shop_floor(with_release=False)

    suspended = validate_success(
        api_client.suspend_blanket_po(shop.po_id, {"reason": "CREDIT_HOLD"}, PLANNER), 200
    )
    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspension_reason"] == "CREDIT_HOLD"

    reinstated = validate_success(api_client.reinstate_blanket_po(shop.po_id, PLANNER), 200)
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["suspension_reason"] is None
    assert reinstated["version"] > suspended["version"]

    release = validate_success(
        api_client.create_kanban_release(
            _release_body(shop.po_id, 200, reinstated["version"]), PLANNER
        ),
        201,
    )
    assert release["status"] == "RELEASED"

    po = read_blanket_po(shop.po_id)
    assert po["remaining_qty"] == 0
    assert po["open_released_qty"] == 200


def test_release_cut_after_the_order_expiry_instant_is_rejected():
    """PRD 3.4: "then the logical clock must be strictly before the order's
    `expires_on`, and when it stands at or after that instant the order is moved
    `ACTIVE → EXPIRED`, its `version` is incremented by one, and the release
    request that triggered the re-evaluation is rejected with `ERR_PO_EXPIRED`
    (HTTP 409);"

    Design: Corner/errors/release_after_the_blanket_order_expiry_is_rejected
    """
    shop = setup_shop_floor(with_release=False, po_expires_on="2026-09-05T00:00:00Z")
    version = blanket_po_version(shop.po_id)
    set_clock("2026-09-06T00:00:00Z")

    response = api_client.create_kanban_release(
        _release_body(shop.po_id, 10, version), PLANNER
    )
    validate_error(response, ApiErrorId.ERR_PO_EXPIRED.value)

    po = read_blanket_po(shop.po_id)
    assert po["remaining_qty"] == 200
    assert po["open_released_qty"] == 0


def test_release_authored_against_a_stale_order_version_is_refused():
    """PRD 2.5: "If that value does not equal the blanket order's current
    `version`, the create is rejected with `ERR_STALE_PO_VERSION` (HTTP 412)."
    PRD 2.5: "Cutting a kanban release — a `POST /swiss-shop/kanban-releases`
    request — must carry `expected_blanket_po_version` as a non-optional field of
    the request body, holding the `version` the client last read from the
    `BlanketPO` named by `blanket_po_id`."

    Design: Corner/cross_cutting_complexity_layers/stale_blanket_po_version_on_release_returns_412
    """
    shop = setup_shop_floor(committed_qty=400, release_qty=100)
    current = blanket_po_version(shop.po_id)

    stale = api_client.create_kanban_release(
        _release_body(shop.po_id, 100, current - 1, due_at="2026-09-12T00:00:00Z"), PLANNER
    )
    validate_error(stale, ApiErrorId.ERR_STALE_PO_VERSION.value)

    fresh = validate_success(
        api_client.create_kanban_release(_release_body(shop.po_id, 100, current), PLANNER), 201
    )
    assert fresh["status"] == "RELEASED"

    po = read_blanket_po(shop.po_id)
    assert po["open_released_qty"] == 200
    assert po["remaining_qty"] == 200


def test_version_advances_by_exactly_one_on_each_mutation():
    """PRD 2.4: "Most resources additionally carry `updated_at`, in the same ISO
    8601 UTC format with three fractional digits, and `version`, an integer that
    begins at 1 on creation and increases by exactly one on every mutation of
    that row."
    PRD 3.5: "The machine's `version` is incremented by one as part of the same
    operation — which is precisely why a second schedule authored against the
    version the client read before the first will be refused as stale."
    PRD 3.6: "It sets the machine `AVAILABLE → RUNNING`, points the machine's
    `current_work_order_id` at this work order, and increments the machine's
    `version` by one."

    Design: Corner/cross_cutting_complexity_layers/version_increments_by_one_on_every_mutation
    """
    shop = setup_shop_floor(with_release=False)

    po_version_first_read = blanket_po_version(shop.po_id)
    po_version_second_read = blanket_po_version(shop.po_id)
    assert po_version_first_read == 1
    assert po_version_second_read == 1, "a read must not advance the order's version"

    release = cut_release(
        shop.po_id, qty=200, expected_blanket_po_version=po_version_first_read
    )
    assert blanket_po_version(shop.po_id) == 2

    machine_before_schedule = machine_version(shop.machine_id)
    assert machine_before_schedule == 1
    work_order = schedule_work_order(
        release["id"],
        shop.machine_id,
        shop.lot_id,
        expected_machine_version=machine_before_schedule,
        lights_out_hours=4,
    )
    assert machine_version(shop.machine_id) == 2

    start_work_order(work_order["id"], shop.machinist_id)
    assert machine_version(shop.machine_id) == 3
    # The start mutates the work order's own row too - it writes
    # machinist_operator_id and drives machining_status SCHEDULED -> RUNNING -
    # so the row opened at 1 on creation and advances by exactly one here.
    assert read_work_order(work_order["id"])["version"] == 2
    assert read_release(release["id"])["status"] == "IN_PRODUCTION"
