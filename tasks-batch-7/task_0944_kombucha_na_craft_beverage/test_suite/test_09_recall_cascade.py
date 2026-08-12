"""The seven-hop ingredient recall cascade."""

from test_helpers import (
    TEST_USERS,
    assert_money,
    build_ingredient_exposure_chain,
    read_account,
    read_batch,
    read_lot,
    read_run,
    read_shipment,
    read_subscription,
    validate_paginated,
    validate_success,
)

OPERATOR = TEST_USERS["production_operator_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
SALES = TEST_USERS["sales_rep_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def test_the_quarantine_reaches_the_batch_the_run_and_the_finished_lot(api):
    """PRD 2.12: "*Hop 1.* The `IngredientLot` moves from `AVAILABLE`,
    `PARTIALLY_CONSUMED` or `CONSUMED` to `QUARANTINED`, and the status it held
    immediately before is recorded in `pre_quarantine_status`."
    PRD 2.12: "*Hop 2.* Every `Batch` reachable through a consumption record whose
    `voided` is false, and whose `ferment_stage` is `F1_ACTIVE`, `F2_ACTIVE` or
    `READY_TO_PACKAGE`, has its `qa_disposition` set to `NONCONFORMING`."
    PRD 2.12: "*Hop 3.* Every `PackagingRun` whose `status` is `COMPLETED` and which
    names one of the hop-2 batches in `source_draws` moves to `RECALL_FLAGGED`."
    PRD 2.12: "*Hop 4.* The `FinishedLot` of each newly `RECALL_FLAGGED` run, when its
    `status` is `HELD` or `RELEASED`, moves to `QUARANTINED` with
    `pre_quarantine_status` recorded."

    Design: Difficulty/transitive_cascade/ingredient_quarantine_propagates_seven_hops_to_the_account_notice
    """
    built = build_ingredient_exposure_chain(api)

    quarantined = validate_success(
        api.quarantine_ingredient_lot(
            built["ingredient_lot"]["id"], {"reason": "Supplier pesticide notice"}, COMPLIANCE
        )
    )
    assert quarantined["status"] == "QUARANTINED"
    assert quarantined["pre_quarantine_status"] == "PARTIALLY_CONSUMED"

    batch = read_batch(api, built["batch"]["id"])
    assert batch["qa_disposition"] == "NONCONFORMING"
    assert batch["ferment_stage"] == "READY_TO_PACKAGE", (
        "the cascade moves the quality axis only, never the process axis"
    )

    assert read_run(api, built["run"]["id"])["status"] == "RECALL_FLAGGED"

    lot = read_lot(api, built["lot"]["id"])
    assert lot["status"] == "QUARANTINED"
    assert lot["pre_quarantine_status"] == "RELEASED"


def test_the_quarantine_unwinds_the_shipment_line_and_the_allocated_box(api):
    """PRD 2.12: "(a) Every `ShipmentLine` with `line_status` `ACTIVE` sitting on a
    shipment whose `status` is `DRAFT` or `CONFIRMED` moves to `line_status`
    `RECALLED`, and the lot's `reserved_units` is decreased by that line's `units`; a
    `CONFIRMED` shipment additionally moves to `RECALL_HOLD`, while a `DRAFT` shipment
    keeps `status` `DRAFT` even though its exposed lines move."
    PRD 2.12: "(b) Every `SubscriptionAllocation` whose `status` is `ALLOCATED` moves
    to `REVERSED` with `reversal_reason` `LOT_QUARANTINED`, the lot's `reserved_units`
    is decreased by that allocation's `units`, and the subscription's `credit_balance`
    is increased by the allocation's `charge_amount`."
    PRD 3.9: "The three shipment totals are always taken over `ACTIVE` lines only;
    `RECALLED` and `CANCELLED` lines contribute nothing to any of them."

    Design: Difficulty/transitive_cascade/ingredient_quarantine_propagates_seven_hops_to_the_account_notice
    """
    built = build_ingredient_exposure_chain(api)

    validate_success(
        api.quarantine_ingredient_lot(
            built["ingredient_lot"]["id"], {"reason": "Supplier pesticide notice"}, COMPLIANCE
        )
    )

    lines, _ = validate_paginated(
        api.list_shipment_lines(built["shipment"]["id"], SALES)
    )
    line = [row for row in lines if row["id"] == built["line"]["id"]][0]
    assert line["line_status"] == "RECALLED"

    shipment = read_shipment(api, built["shipment"]["id"])
    assert shipment["status"] == "RECALL_HOLD"
    assert_money(shipment["subtotal"], 0.00, "subtotal over the remaining ACTIVE lines")

    allocations, _ = validate_paginated(
        api.list_subscription_allocations(built["subscription"]["id"], ADMIN)
    )
    allocation = [row for row in allocations if row["id"] == built["allocation"]["id"]][0]
    assert allocation["status"] == "REVERSED"
    assert allocation["reversal_reason"] == "LOT_QUARANTINED"

    subscription = read_subscription(api, built["subscription"]["id"])
    assert_money(subscription["credit_balance"], 42.00, "credit returned for the reversed box")

    lot = read_lot(api, built["lot"]["id"])
    assert lot["reserved_units"] == 0, "both reservations are released"
    assert lot["on_hand_units"] == 258, "releasing a reservation moves no physical units"


def test_the_quarantine_raises_one_notice_and_recomputes_the_account_counter(api):
    """PRD 2.12: "*Hop 6.* One `RecallNotice` in `status` `PENDING` is created for
    each account-and-lot pair that has any exposure, where exposure means either a
    line with `line_status` `ACTIVE` or `RECALLED` on any shipment of that account
    referencing the lot, or a keg from that lot held by the account with
    `deposit_state` `CHARGED`."
    PRD 2.12: "*Hop 7.* Each affected account's `open_recall_notice_count` is
    recomputed as the number of that account's recall notices whose `status` is
    `PENDING` or `OVERDUE`."
    PRD 3.11: "it records `trigger_source` describing where the chain began —
    `INGREDIENT_LOT_QUARANTINE` when it started at a raw ingredient lot quarantine,
    `LOT_QUARANTINE` when it started at a finished-lot quarantine, and `LOT_RECALL`
    when it started at a recall."

    Design: Difficulty/transitive_cascade/ingredient_quarantine_propagates_seven_hops_to_the_account_notice
    """
    built = build_ingredient_exposure_chain(api)

    validate_success(
        api.quarantine_ingredient_lot(
            built["ingredient_lot"]["id"], {"reason": "Supplier pesticide notice"}, COMPLIANCE
        )
    )

    notices, meta = validate_paginated(
        api.list_account_recall_notices(built["account"]["id"], SALES)
    )
    assert meta["total_count"] == 1, "exactly one notice per account-and-lot pair"
    notice = notices[0]
    assert notice["status"] == "PENDING"
    assert notice["trigger_source"] == "INGREDIENT_LOT_QUARANTINE"
    assert notice["finished_lot_id"] == built["lot"]["id"]

    assert read_account(api, built["account"]["id"])["open_recall_notice_count"] == 1
