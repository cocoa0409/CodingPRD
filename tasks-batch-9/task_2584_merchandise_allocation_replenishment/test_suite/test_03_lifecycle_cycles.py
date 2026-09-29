"""Cyclic and forking lifecycles: SKU health, the two position dimensions and the
four-way fork out of a PROPOSED transfer recommendation."""
from test_helpers import (
    ApiErrorId,
    actions_for,
    make_store_operator_headers,
    propose_transfer,
    receive_transfer,
    refresh_item,
    refresh_position,
    run_detection,
    setup_approved_transfer,
    setup_detected_action,
    setup_dispatched_transfer,
    setup_executed_consolidation,
    setup_rebalance_network,
    size_units,
    validate_error,
    validate_success,
)


def test_a_position_opening_with_two_empty_core_sizes_drives_the_sku_to_broken(
    api, allocator_headers
):
    """PRD §3.3: "Creation itself runs the full health derivation described later in
    this subsection, so a brand-new position is created with `broken_size_count`,
    `stock_status` and `assortment_status` already populated, and it immediately
    recomputes the SKU's `broken_store_count` and `size_out_store_count` and
    re-derives the SKU's `lifecycle_state` — a season can therefore open with a SKU
    already `BROKEN` if its opening size mixes are thin." PRD §3.3: "otherwise
    `broken_size_count` is 2 or more and the position is `BROKEN`."

    Position 0101 opens with no S and no XL against a four-CORE-size curve, so it is
    BROKEN and drags the freshly created SKU from ACTIVE to BROKEN.

    Design: Difficulty/non_linear_state_machine/item_lifecycle_cycles_active_broken_consolidation_pending_active
    """
    scenario = setup_rebalance_network()

    position = refresh_position(scenario, "0101")
    assert position["broken_size_count"] == 2
    assert position["assortment_status"] == "BROKEN"

    item = refresh_item(scenario)
    assert item["lifecycle_state"] == "BROKEN"
    assert item["broken_store_count"] == 1


def test_executing_the_consolidation_remedy_moves_the_sku_broken_to_consolidation_pending(
    api, allocation_manager_headers
):
    """PRD §3.9: "A `CONSOLIDATION` action creates a transfer recommendation with
    `source_reason` of `CONSOLIDATION`, `from_store_id` set to the action's own
    `store_id`, `to_store_id` set to the action's `consolidation_target_store_id`,
    `units` set to `units_at_detection`, `assortment_action_id` set to the action's
    identifier, and `proposed_by_user_id` set to the literal string `system`". "The
    SKU is then driven `BROKEN → CONSOLIDATION_PENDING` and its `version` advances
    by one."

    The sweep raises one BROKEN_ASSORTMENT action on position 0101 for its 4
    available units, and executing it opens a system-owned four-unit sweep-up.

    Design: Difficulty/non_linear_state_machine/item_lifecycle_cycles_active_broken_consolidation_pending_active
    """
    scenario = setup_executed_consolidation()
    action = scenario["action"]
    transfer = scenario["transfer"]

    assert action["trigger_reason"] == "BROKEN_ASSORTMENT"
    assert action["action_type"] == "CONSOLIDATION"
    assert action["units_at_detection"] == 4
    assert action["broken_size_count"] == 2
    assert action["markdown_pct_bp"] is None
    assert action["status"] == "EXECUTED"

    assert transfer["units"] == 4
    assert transfer["proposed_by_user_id"] == "system"
    assert transfer["assortment_action_id"] == action["id"]
    assert size_units(transfer, "size_split") == {"M": 3, "L": 1}

    assert refresh_item(scenario)["lifecycle_state"] == "CONSOLIDATION_PENDING"


def test_receiving_the_consolidation_transfer_returns_the_sku_to_active(
    api, allocation_manager_headers
):
    """PRD §3.3: "Second, if the SKU is `CONSOLIDATION_PENDING`, it returns to
    `ACTIVE` only when `broken_store_count` has reached 0, and otherwise stays where
    it is." PRD §3.8: "If the donor position's `on_hand_units` has reached 0 and the
    transfer's `source_reason` is `CONSOLIDATION`, the donor position's
    `consolidated_out` flag is set to true, which by the pinned evaluation order in
    §3.3 immediately makes that position `EXITED`."

    Dispatch empties donor 0101 without healing anything, so the SKU stays
    CONSOLIDATION_PENDING; the arrival at 0103 exits the donor, drops
    `broken_store_count` to 0 and re-enters ACTIVE by a second mechanism, and
    MARKDOWN is never touched.

    Design: Difficulty/non_linear_state_machine/item_lifecycle_cycles_active_broken_consolidation_pending_active
    """
    scenario = setup_executed_consolidation()
    transfer_id = scenario["transfer"]["id"]

    validate_success(api.approve_transfer(transfer_id, allocation_manager_headers))
    validate_success(api.dispatch_transfer(transfer_id, allocation_manager_headers))

    donor = refresh_position(scenario, "0101")
    assert donor["on_hand_units"] == 0
    assert donor["broken_size_count"] == 4
    assert donor["assortment_status"] == "BROKEN"
    assert refresh_item(scenario)["lifecycle_state"] == "CONSOLIDATION_PENDING"

    receive_transfer(scenario, to_code="0103")

    target = refresh_position(scenario, "0103")
    assert target["on_hand_units"] == 9
    assert size_units(target, "size_on_hand") == {"S": 1, "M": 5, "L": 2, "XL": 1}
    assert target["assortment_status"] == "COMPLETE"

    donor = refresh_position(scenario, "0101")
    assert donor["consolidated_out"] is True
    assert donor["assortment_status"] == "EXITED"

    item = refresh_item(scenario)
    assert item["broken_store_count"] == 0
    assert item["lifecycle_state"] == "ACTIVE"


def test_approving_a_transfer_moves_the_donor_stock_band_and_leaves_its_assortment_alone(
    api, allocator_headers
):
    """PRD §3.3: "A position carries **two health dimensions that move completely
    independently of one another**, and it is essential not to collapse them." PRD
    §3.8: "the transfer's `units` are added to the donor position's
    `reserved_out_units` — which lowers that position's `available_units` and
    re-derives its `stock_status`".

    Reserving six of donor 0102's thirty units drops its available count to exactly
    its 24-unit maximum, so it leaves OVERSTOCK for IN_STOCK while its assortment
    stays COMPLETE.

    Design: Difficulty/non_linear_state_machine/store_position_stock_and_assortment_dimensions_move_independently
    """
    scenario = setup_approved_transfer(units=6)

    donor = refresh_position(scenario, "0102")
    assert donor["reserved_out_units"] == 6
    assert donor["available_units"] == 24
    assert donor["stock_status"] == "IN_STOCK"
    assert donor["assortment_status"] == "COMPLETE"
    assert donor["on_hand_units"] == 30


def test_in_transit_units_repair_neither_dimension_on_the_receiving_position(
    api, allocation_manager_headers
):
    """PRD §3.3: "The second dimension is `assortment_status`, and it rests on
    `broken_size_count`: the number of the SKU's **CORE** sizes for which the
    position's `size_on_hand` shows zero units, where a size code entirely absent
    from `size_on_hand` counts as zero." PRD §3.3: "`available_units` is
    `on_hand_units` minus `reserved_out_units`, and it, not the raw on-hand count,
    is what every downstream decision reads."

    Six units in transit to 0101 touch neither its `size_on_hand` nor its
    `available_units`, so it is still LOW and still BROKEN, while the donor's
    departure leaves every size represented and its assortment COMPLETE.

    Design: Difficulty/non_linear_state_machine/store_position_stock_and_assortment_dimensions_move_independently
    """
    scenario = setup_dispatched_transfer(units=6)

    receiver = refresh_position(scenario, "0101")
    assert receiver["in_transit_units"] == 6
    assert receiver["on_hand_units"] == 4
    assert receiver["broken_size_count"] == 2
    assert receiver["assortment_status"] == "BROKEN"
    assert receiver["stock_status"] == "LOW"

    donor = refresh_position(scenario, "0102")
    assert donor["on_hand_units"] == 24
    assert size_units(donor, "size_on_hand") == {"S": 4, "M": 10, "L": 8, "XL": 2}
    assert donor["assortment_status"] == "COMPLETE"


def test_arrival_repairs_the_assortment_dimension_while_the_stock_band_stays_low(
    api, allocation_manager_headers
):
    """PRD §3.3: "Because the dimensions are orthogonal, a position may perfectly
    legitimately be `OVERSTOCK` and `BROKEN` at the same time — drowning in the
    wrong sizes." PRD §3.3: "otherwise, when `available_units` is greater than 0 and
    strictly less than `min_units` it is `LOW`".

    The four S units and two XL units close 0101's size holes, so its assortment
    reaches COMPLETE and the SKU returns to ACTIVE, yet ten units still sit under a
    twelve-unit minimum and the stock band does not move off LOW.

    Design: Difficulty/non_linear_state_machine/store_position_stock_and_assortment_dimensions_move_independently
    """
    scenario = setup_dispatched_transfer(units=6)

    receive_transfer(scenario, to_code="0101")

    receiver = refresh_position(scenario, "0101")
    assert receiver["on_hand_units"] == 10
    assert size_units(receiver, "size_on_hand") == {"S": 4, "M": 3, "L": 1, "XL": 2}
    assert receiver["broken_size_count"] == 0
    assert receiver["assortment_status"] == "COMPLETE"
    assert receiver["stock_status"] == "LOW"

    item = refresh_item(scenario)
    assert item["broken_store_count"] == 0
    assert item["lifecycle_state"] == "ACTIVE"


def test_a_proposed_recommendation_forks_to_rejected_and_then_accepts_nothing(
    api, allocator_headers, allocation_manager_headers
):
    """PRD §3.8: "It may be **rejected** by an `AllocationManager`, which takes it
    `PROPOSED → REJECTED`, stores the supplied `reason` as `reject_reason` and
    advances `version` by one." PRD §2.10: "The target resource is in a state that
    permits the requested transition — `ERR_INVALID_STATE_TRANSITION`, 409."

    Rejection never records an approver, and a dispatch aimed at the rejected row is
    refused on the state rung.

    Design: Difficulty/non_linear_state_machine/transfer_recommendation_forks_to_rejected_cancelled_and_expired
    """
    scenario = setup_rebalance_network()
    transfer = propose_transfer(scenario, units=6, headers=allocator_headers)

    rejected = validate_success(
        api.reject_transfer(
            transfer["id"],
            {"reason": "not economic this week"},
            allocation_manager_headers,
        )
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["reject_reason"] == "not economic this week"
    assert rejected["approved_by_user_id"] is None

    validate_error(
        api.dispatch_transfer(transfer["id"], allocation_manager_headers),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        409,
    )


def test_cancelling_an_approved_recommendation_exactly_reverses_the_reservation(
    api, allocation_manager_headers
):
    """PRD §3.8: "An `AllocationManager` may **cancel** an approved recommendation,
    taking it `APPROVED → CANCELLED`, which exactly reverses the approval: the
    transfer's `units` are released from the donor position's `reserved_out_units`,
    restoring its `available_units` and re-deriving its `stock_status`, the supplied
    `reason` is stored as `reject_reason`, and `version` advances by one."

    The donor returns to thirty available units and to OVERSTOCK, exactly where the
    approval found it.

    Design: Difficulty/non_linear_state_machine/transfer_recommendation_forks_to_rejected_cancelled_and_expired
    """
    scenario = setup_approved_transfer(units=6)

    cancelled = validate_success(
        api.cancel_transfer(
            scenario["transfer"]["id"],
            allocation_manager_headers,
            {"reason": "consolidated into a later shipment"},
        )
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["reject_reason"] == "consolidated into a later shipment"

    donor = refresh_position(scenario, "0102")
    assert donor["reserved_out_units"] == 0
    assert donor["available_units"] == 30
    assert donor["stock_status"] == "OVERSTOCK"


def test_the_expiry_sweep_takes_only_the_surviving_proposed_arm(
    api, allocator_headers, allocation_manager_headers, planning_admin_headers
):
    """PRD §3.8: "An `AllocationManager` may also sweep the program, which drives
    every `PROPOSED` recommendation whose `expires_at` is at or before the logical
    clock to `EXPIRED` and advances each one's `version` by one; `APPROVED` and
    `DISPATCHED` recommendations are never expired by that sweep." PRD §2.10: "and a
    resource in a terminal state accepts nothing at all."

    One arm is rejected, one is approved and then cancelled, and only the third is
    still PROPOSED when the clock passes its 2026-08-08 expiry, so the sweep returns
    that one row alone; approving it afterwards reports the state refusal from rung 8
    rather than the expiry refusal from rung 24.

    Design: Difficulty/non_linear_state_machine/transfer_recommendation_forks_to_rejected_cancelled_and_expired
    """
    scenario = setup_rebalance_network()
    program_id = scenario["program"]["id"]

    rejected_arm = propose_transfer(scenario, units=6, headers=allocator_headers)
    validate_success(
        api.reject_transfer(
            rejected_arm["id"], {"reason": "not economic"}, allocation_manager_headers
        )
    )

    cancelled_arm = propose_transfer(scenario, units=6, headers=allocator_headers)
    assert cancelled_arm["supersedes_recommendation_id"] is None
    validate_success(api.approve_transfer(cancelled_arm["id"], allocation_manager_headers))
    validate_success(
        api.cancel_transfer(
            cancelled_arm["id"], allocation_manager_headers, {"reason": "later shipment"}
        )
    )

    surviving = propose_transfer(
        scenario, from_code="0103", to_code="0101", units=2, headers=allocator_headers
    )
    assert surviving["expires_at"][:19] == "2026-08-08T00:00:00"

    validate_success(
        api.set_current_utc(
            {"current_utc": "2026-08-09T00:00:00Z"}, planning_admin_headers
        )
    )
    swept = validate_success(
        api.run_transfer_expiry({"program_id": program_id}, allocation_manager_headers)
    )
    assert [row["id"] for row in swept] == [surviving["id"]]

    assert validate_success(
        api.get_transfer_recommendation(surviving["id"], allocation_manager_headers)
    )["status"] == "EXPIRED"
    assert validate_success(
        api.get_transfer_recommendation(rejected_arm["id"], allocation_manager_headers)
    )["status"] == "REJECTED"
    assert validate_success(
        api.get_transfer_recommendation(cancelled_arm["id"], allocation_manager_headers)
    )["status"] == "CANCELLED"

    validate_error(
        api.approve_transfer(surviving["id"], allocation_manager_headers),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        409,
    )
