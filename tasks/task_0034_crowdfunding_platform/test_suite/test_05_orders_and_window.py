"""Order placement, modification window, inventory, shipping checks.

PRD references:
  - §3.4 Going Live, Backing, and the Order Modification Window
  - §2.6 Nested Resource Path Resolution (cross-project)
  - §2.11 Concurrency and Serialization Guarantees
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_hours,
    add_on_line,
    advance_clock,
    assert_order,
    create_add_on_item,
    create_backer,
    create_order_payload,
    create_reward,
    default_shipping_address,
    make_backer_headers,
    make_initiator_headers,
    patch_order_payload,
    place_order,
    setup_inventory_limited_reward,
    setup_live_project,
    setup_live_with_order,
    setup_order_at_window_boundary,
    setup_project_in_content_review,
    validate_error,
    validate_success,
)


class TestOrderCreation:
    def test_order_create_pins_authorized_status(self, api):
        """PRD §3.4: 'On successful creation ... the order is persisted
        with payment_status AUTHORIZED and fulfillment_status NOT_STARTED.'

        Claim: POST /orders → order with AUTHORIZED + NOT_STARTED.
        """
        _, project, reward = setup_live_project(
            category="TECH", reward_pledge_cents=5_000,
            reward_type="DIGITAL", funding_target_cents=100_000,
        )
        backer = create_backer()
        res = api.create_order(
            create_order_payload(
                project_id=project["id"], reward_id=reward["id"],
            ),
            make_backer_headers(backer["id"]),
        )
        data = validate_success(res, expected_status=201)
        assert_order(data)
        assert data["payment_status"] == "AUTHORIZED"
        assert data["fulfillment_status"] == "NOT_STARTED"
        assert data["backer_id"] == backer["id"]
        assert data["project_id"] == project["id"]
        assert data["reward_id"] == reward["id"]

    def test_order_create_rejected_when_project_not_live(self, api):
        """PRD §3.4: 'Order creation is rejected with ERR_INVALID_STATE if
        the project is not in LIVE.'

        Claim: order on a CONTENT_REVIEW project → ERR_INVALID_STATE.
        """
        _, project_in_review, reward = setup_project_in_content_review()
        backer = create_backer()
        res = api.create_order(
            create_order_payload(
                project_id=project_in_review["id"], reward_id=reward["id"],
            ),
            make_backer_headers(backer["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_order_total_pins_pledge_plus_addons(self, api):
        """PRD §3.4: 'add_ons_total_cents is computed as the sum over the
        order's add-ons of price_cents multiplied by quantity; and
        order_total_cents is the sum of the snapshot pledge amount and
        the add-ons total.'

        Claim: with add-on of price 500 x 2 plus pledge 5000 →
        order_total_cents == 6000.
        """
        initiator, project, reward = setup_live_project(
            category="TECH", reward_pledge_cents=5_000,
            reward_type="DIGITAL", funding_target_cents=10_000_000,
        )
        # add_on_items can only be created in DRAFT — but project is now
        # LIVE. Re-build with an add-on at draft time.
        # Simpler: build a fresh project to LIVE that already has the
        # add-on created in DRAFT.
        from test_helpers import (
            create_add_on_item, create_draft_project,
            create_verified_initiator, take_project_live,
        )
        initiator2 = create_verified_initiator(with_tax_id=True)
        project2 = create_draft_project(
            initiator=initiator2,
            funding_target_cents=10_000_000,
            deadline_hours_from_now=240.0,
        )
        reward2 = create_reward(
            project=project2, initiator=initiator2,
            pledge_amount_cents=5_000, reward_type="DIGITAL",
        )
        addon = create_add_on_item(
            project=project2, initiator=initiator2,
            price_cents=500, requires_shipping=False,
        )
        project2 = take_project_live(project=project2, initiator=initiator2)
        backer = create_backer()
        res = api.create_order(
            create_order_payload(
                project_id=project2["id"], reward_id=reward2["id"],
                add_ons=[add_on_line(addon["id"], quantity=2)],
            ),
            make_backer_headers(backer["id"]),
        )
        data = validate_success(res, expected_status=201)
        assert data["pledge_amount_cents"] == 5_000
        assert data["add_ons_total_cents"] == 1_000  # 500 * 2
        assert data["order_total_cents"] == 6_000

    def test_physical_reward_requires_shipping_address(self, api):
        """PRD §3.4: 'A shipping_address is mandatory whenever the selected
        reward's reward_type is PHYSICAL or any referenced add-on has
        requires_shipping true; absence is rejected with
        ERR_SHIPPING_ADDRESS_REQUIRED.'

        Claim: PHYSICAL reward without shipping_address →
        ERR_SHIPPING_ADDRESS_REQUIRED.
        """
        _, project, reward = setup_live_project(
            category="TECH", reward_pledge_cents=5_000,
            reward_type="PHYSICAL", funding_target_cents=10_000_000,
        )
        backer = create_backer()
        res = api.create_order(
            create_order_payload(
                project_id=project["id"], reward_id=reward["id"],
                # explicitly no shipping_address
            ),
            make_backer_headers(backer["id"]),
        )
        validate_error(res, "ERR_SHIPPING_ADDRESS_REQUIRED")

    def test_reward_inventory_exhausted(self, api):
        """PRD §3.4: 'if the reward has a non-null inventory_limit and
        accepting this order would push inventory_claimed past it, the
        order is rejected with ERR_REWARD_INVENTORY_EXHAUSTED'.

        Claim: 2nd order on an inventory_limit=1 reward →
        ERR_REWARD_INVENTORY_EXHAUSTED.
        """
        ctx = setup_inventory_limited_reward(inventory_limit=1)
        # First order claims the only unit.
        place_order(
            project=ctx["project"], reward=ctx["reward"], backer=ctx["backer"]
        )
        # Second backer attempts to claim — should fail.
        backer2 = create_backer()
        res = api.create_order(
            create_order_payload(
                project_id=ctx["project"]["id"],
                reward_id=ctx["reward"]["id"],
            ),
            make_backer_headers(backer2["id"]),
        )
        validate_error(res, "ERR_REWARD_INVENTORY_EXHAUSTED")


class TestOrderModificationWindow:
    def test_modify_at_locked_at_rejected(self, api):
        """PRD §3.4: 'An attempt to modify or cancel an order at or after
        the locked-at moment is rejected with
        ERR_MODIFICATION_WINDOW_CLOSED.'

        Claim: PATCH at exactly locked_at → ERR_MODIFICATION_WINDOW_CLOSED.
        """
        ctx = setup_order_at_window_boundary(deadline_hours_from_now=240.0)
        order = ctx["order"]
        # locked_at is the earlier of (project.deadline, created_at + 72h).
        # With deadline 240h ahead, locked_at = created_at + 72h.
        locked_at = order["order_modification_locked_at"]
        # Advance to exactly the locked_at instant. PRD §3.4: 'at or
        # after the locked-at moment is rejected'.
        advance_clock(locked_at)
        res = api.patch_order(
            order["id"],
            patch_order_payload(
                version=order["version"],
                payment_method_token="tok-modify-late",
            ),
            make_backer_headers(ctx["backer"]["id"]),
        )
        validate_error(res, "ERR_MODIFICATION_WINDOW_CLOSED")

    def test_cancel_own_order_voids_authorization(self, api):
        """PRD §3.4: 'while still inside the window and with the project
        in LIVE, the backer may cancel, which moves the order's
        payment_status from AUTHORIZED to VOIDED'.

        Claim: backer-initiated cancel within window → VOIDED.
        """
        _, _, _, backer, order = setup_live_with_order(
            category="TECH", reward_pledge_cents=2_000,
            reward_type="DIGITAL", funding_target_cents=10_000_000,
        )
        res = api.cancel_order(
            order["id"], make_backer_headers(backer["id"])
        )
        data = validate_success(res, expected_status=200)
        assert data["payment_status"] == "VOIDED"


class TestProvisionalCounter:
    def test_provisional_raised_excludes_voided(self, api):
        """PRD §3.4: 'Voided, charged, refunded, partially refunded,
        charge-pending, charge-failed, and refund-pending orders are all
        excluded from this provisional sum.'

        Claim: after order cancel (VOIDED), provisional_raised_cents
        decreases back to zero on a project with one order.
        """
        from test_helpers import get_project
        _, project, _, backer, order = setup_live_with_order(
            category="TECH", reward_pledge_cents=7_000,
            reward_type="DIGITAL", funding_target_cents=10_000_000,
        )
        before = get_project(project["id"])["provisional_raised_cents"]
        # before should equal order.order_total_cents (only AUTHORIZED order)
        assert before == order["order_total_cents"]
        api.cancel_order(order["id"], make_backer_headers(backer["id"]))
        after = get_project(project["id"])["provisional_raised_cents"]
        assert after == 0, (
            "PRD §3.4: VOIDED orders are excluded from provisional sum; "
            "after cancel the only order on this project is VOIDED so the "
            "sum drops to zero."
        )
