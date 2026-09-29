"""Compensating arcs that must put a conserved quantity back exactly as it was.

Cancelling a confirmed order and reverting an applied edit each undo an earlier
movement without disturbing the identity the contract keeps over the whole record.
"""

from test_helpers import (
    CONTENT_EDIT_STATUS_REVERTED,
    ORDER_STATUS_CANCELLED,
    SAMPLING_STATUS_SHIPPED,
    TITLE_STATUS_ACTIVE,
    assert_page_budget_conserved,
    assert_print_unit_ledger_balances,
    fixtures,
    get_success_data,
    validate_success,
)


def test_cancelling_a_confirmed_order_releases_the_commitment(api):
    """The order gives back its allocation and forgets its contracted value.

    PRD 3.9: "From `CONFIRMED` the commitment is released: the edition's
    `committed_units` decreases by `allocated_units`, its `on_hand_units` increases
    by the same amount, `allocated_units` becomes 0, `contracted_tcv_cents` is reset
    to null and `freight_surcharge_cents` to 0."

    Design: Difficulty/compensating_invariant/order_cancel_restores_print_unit_ledger
    """
    world = fixtures.seed_open_cycle(
        api,
        "TN",
        state_overrides={"sampling_copies_required": 20},
        receipt_units=5000,
    )
    fixtures.seed_draft_submission(api, world)
    fixtures.ship_sampling_copies_to(api, world, 20)

    order_id = fixtures.quote_order(api, world, print_units=1200, digital_seats=0)
    quoted = validate_success(api.get_district_order(order_id, fixtures.QUOTING_REP))
    # 1,200 x 9,000 is 10,800,000 pre-freight, comfortably over the waiver.
    assert quoted["quoted_tcv_cents"] == 10800000
    assert quoted["freight_surcharge_cents"] == 0

    fixtures.confirm_order(api, world, order_id)

    cancelled = validate_success(
        api.cancel_district_order(
            order_id,
            {"reason": "The district deferred the purchase to the next fiscal year."},
            fixtures.QUOTING_REP,
        )
    )
    assert cancelled["status"] == ORDER_STATUS_CANCELLED
    assert cancelled["allocated_units"] == 0
    assert cancelled["contracted_tcv_cents"] is None
    assert cancelled["freight_surcharge_cents"] == 0


def test_the_cancellation_puts_every_print_unit_back_in_its_bucket(api):
    """The five buckets still add up to the units the warehouse ever received.

    PRD 2.10: "The **print-unit ledger** of a title states that
    `total_received_units` always equals the sum of `on_hand_units`,
    `committed_units`, `sample_reserved_units`, `fulfilled_units` and
    `written_off_units`."

    Design: Difficulty/compensating_invariant/order_cancel_restores_print_unit_ledger
    """
    world = fixtures.seed_open_cycle(
        api,
        "TN",
        state_overrides={"sampling_copies_required": 20},
        receipt_units=5000,
    )
    fixtures.seed_draft_submission(api, world)
    fixtures.ship_sampling_copies_to(api, world, 20)

    order_id = fixtures.quote_order(api, world, print_units=1200, digital_seats=0)
    fixtures.confirm_order(api, world, order_id)
    get_success_data(
        api.cancel_district_order(
            order_id,
            {"reason": "The district deferred the purchase to the next fiscal year."},
            fixtures.QUOTING_REP,
        )
    )

    edition = validate_success(api.get_title(world.title_id, fixtures.EDITOR))
    # The twenty sample copies stay reserved; the 1,200 confirmed copies come home.
    assert edition["total_received_units"] == 5000
    assert edition["on_hand_units"] == 4980
    assert edition["committed_units"] == 0
    assert edition["sample_reserved_units"] == 20
    assert edition["fulfilled_units"] == 0
    assert edition["written_off_units"] == 0
    assert_print_unit_ledger_balances(edition)

    submission = validate_success(
        api.get_submission(world.submission_id, fixtures.EDITOR)
    )
    assert submission["sampling_status"] == SAMPLING_STATUS_SHIPPED
    assert submission["sample_copies_shipped"] == 20


def test_reverting_an_applied_edit_gives_the_pages_back_to_the_budget(api):
    """Forty pages return to the signature budget and the identity still holds.

    PRD 3.3: "An accepted revert moves the edit from `APPLIED` to `REVERTED`, its
    terminal state, decreases `page_count` by `pages_delta` and increases
    `page_budget_remaining` by `pages_delta`, restoring the signature identity, and
    undoes the `content_tags` change the apply made."

    Design: Difficulty/compensating_invariant/content_edit_revert_restores_page_budget
    """
    world = fixtures.seed_state(api, "KY", required_topics=["DATA_LITERACY"])
    fixtures.seed_title(
        api,
        world,
        isbn_base="9780000001601",
        page_count=400,
        signature_page_capacity=480,
        content_tags=["RATIO_REASONING"],
    )
    edit_id = fixtures.seed_applied_content_edit(
        api, world, topic_code="DATA_LITERACY", pages_delta=40
    )

    applied = validate_success(api.get_title(world.title_id, fixtures.EDITOR))
    assert applied["page_count"] == 440
    assert applied["page_budget_remaining"] == 40

    reverted = validate_success(
        api.revert_content_edit(
            edit_id,
            {"reason": "The state withdrew the topic requirement before adoption."},
            fixtures.DIRECTOR,
        )
    )
    assert reverted["status"] == CONTENT_EDIT_STATUS_REVERTED

    edition = validate_success(api.get_title(world.title_id, fixtures.EDITOR))
    assert edition["page_count"] == 400
    assert edition["page_budget_remaining"] == 80
    assert_page_budget_conserved(edition)


def test_the_revert_still_counts_as_a_revision_of_its_own(api):
    """The tags go back but the revision number keeps climbing.

    PRD 3.3: "Crucially, the revert **also** increases `content_revision` by 1
    rather than restoring the previous number: revision numbers are strictly
    monotonic, so a revert never un-stales a submission that pinned a revision
    before the apply."

    Design: Difficulty/compensating_invariant/content_edit_revert_restores_page_budget
    """
    world = fixtures.seed_state(api, "KY", required_topics=["DATA_LITERACY"])
    fixtures.seed_title(
        api,
        world,
        isbn_base="9780000001601",
        page_count=400,
        signature_page_capacity=480,
        content_tags=["RATIO_REASONING"],
    )
    edit_id = fixtures.seed_applied_content_edit(
        api, world, topic_code="DATA_LITERACY", pages_delta=40
    )

    applied = validate_success(api.get_title(world.title_id, fixtures.EDITOR))
    assert applied["content_revision"] == 2
    assert "DATA_LITERACY" in applied["content_tags"]

    get_success_data(
        api.revert_content_edit(
            edit_id,
            {"reason": "The state withdrew the topic requirement before adoption."},
            fixtures.DIRECTOR,
        )
    )

    edition = validate_success(api.get_title(world.title_id, fixtures.EDITOR))
    assert edition["content_revision"] == 3
    assert edition["content_tags"] == ["RATIO_REASONING"]
    assert edition["status"] == TITLE_STATUS_ACTIVE
