"""Validation precedence: which rung answers when one request breaks two rules."""
from test_helpers import (
    ApiErrorId,
    FIXTURE_SPECS_THREE,
    POSITION_SPECS_REBALANCE,
    STORE_SPECS_FOUR,
    create_proposed_run,
    create_transfer_payload,
    current_position_version,
    line_for_store,
    lines_for_run,
    lock_program,
    propose_transfer,
    refresh_position,
    refresh_program,
    refresh_receipt,
    set_clock,
    setup_network,
    setup_network_with_staged_receipt,
    setup_rebalance_network,
    size_units,
    unlock_program,
    units_by_size,
    validate_error,
    validate_success,
)


def _proposed_transfer_under_an_unreachable_ratio_gate():
    """A six-unit rebalance 0102 -> 0101 worth 78.30 against a landed cost of 50.40,
    inside a program whose freight-worthiness floor is set to 20000 basis points."""
    scenario = setup_rebalance_network(
        program_overrides={"transfer_min_ratio_bp": 20000}
    )
    scenario["transfer"] = propose_transfer(scenario, units=6)
    return scenario


def test_a_locked_program_answers_the_approve_before_the_benefit_gate_is_reached(
    api, allocation_manager_headers
):
    """PRD §2.10: "Checks are evaluated in ascending priority and the **first**
    violated check determines the response; later checks are never reached, so a
    request that violates three rules always reports the lowest-numbered one." The
    ladder places "The program is `ACTIVE`, for the decision endpoints listed in §2.6
    — `ERR_PROGRAM_LOCKED`, 409." at rung 9 and "Freight worthiness of a rebalancing
    transfer — `ERR_BENEFIT_RATIO_BELOW_THRESHOLD`, 409." at rung 34.

    The approve breaks both rules at once, so only the lock is reported and the
    recommendation is left exactly where it was.

    Design: Difficulty/priority_pair_validation_conflict/program_locked_state_beats_benefit_ratio_fiscal_gate
    """
    scenario = _proposed_transfer_under_an_unreachable_ratio_gate()
    transfer = scenario["transfer"]
    assert transfer["benefit_ratio_bp"] == 15536
    assert scenario["program"]["transfer_min_ratio_bp"] == 20000

    lock_program(scenario["program"]["id"], "month-end freeze")

    validate_error(
        api.approve_transfer(transfer["id"], allocation_manager_headers),
        ApiErrorId.ERR_PROGRAM_LOCKED.value,
        409,
    )

    still_proposed = validate_success(
        api.get_transfer_recommendation(transfer["id"], allocation_manager_headers)
    )
    assert still_proposed["status"] == "PROPOSED"


def test_the_lock_stamps_the_logical_clock_and_the_supplied_reason(
    api, allocation_manager_headers
):
    """PRD §3.1: "An `AllocationManager` may take the program `ACTIVE → LOCKED`,
    supplying a `reason` that is stored as `lock_reason` while `locked_at` records the
    current logical clock; the reverse transition `LOCKED → ACTIVE` clears both fields
    back to null."

    The lock that outranked the fiscal gate is itself observable, and unlocking wipes
    both stamps — which is what makes the precedence claim falsifiable.

    Design: Difficulty/priority_pair_validation_conflict/program_locked_state_beats_benefit_ratio_fiscal_gate
    """
    scenario = _proposed_transfer_under_an_unreachable_ratio_gate()

    lock_program(scenario["program"]["id"], "month-end freeze")
    locked = refresh_program(scenario)
    assert locked["status"] == "LOCKED"
    assert locked["locked_at"][:19] == "2026-08-01T00:00:00"
    assert locked["lock_reason"] == "month-end freeze"

    unlock_program(scenario["program"]["id"])
    unlocked = refresh_program(scenario)
    assert unlocked["status"] == "ACTIVE"
    assert unlocked["locked_at"] is None
    assert unlocked["lock_reason"] is None


def test_unlocking_reveals_the_fiscal_violation_that_was_hiding_underneath(
    api, allocation_manager_headers
):
    """PRD §3.8: "The **freight-worthiness gate** is conditional on `source_reason`: a
    `CONSOLIDATION` transfer skips it entirely, because a mandated sweep-up is exempt
    by design, while a `REBALANCE` transfer requires `benefit_ratio_bp` to be greater
    than or equal to the program's `transfer_min_ratio_bp`, with equality passing, and
    otherwise is refused with `ERR_BENEFIT_RATIO_BELOW_THRESHOLD`."

    The identical approve, with nothing about the transfer touched, now reports the
    ratio shortfall: both rules really were violated while the program was locked.

    Design: Difficulty/priority_pair_validation_conflict/program_locked_state_beats_benefit_ratio_fiscal_gate
    """
    scenario = _proposed_transfer_under_an_unreachable_ratio_gate()
    transfer = scenario["transfer"]

    lock_program(scenario["program"]["id"], "month-end freeze")
    validate_error(
        api.approve_transfer(transfer["id"], allocation_manager_headers),
        ApiErrorId.ERR_PROGRAM_LOCKED.value,
        409,
    )
    unlock_program(scenario["program"]["id"])

    validate_error(
        api.approve_transfer(transfer["id"], allocation_manager_headers),
        ApiErrorId.ERR_BENEFIT_RATIO_BELOW_THRESHOLD.value,
        409,
    )


def test_neither_refused_approve_reserved_a_single_donor_unit(
    api, allocation_manager_headers
):
    """PRD §3.8: "On success the recommendation moves `PROPOSED → APPROVED`,
    `approved_by_user_id` is set to the acting `X-User-ID`, the transfer's `units` are
    added to the donor position's `reserved_out_units` — which lowers that position's
    `available_units` and re-derives its `stock_status` — and the recommendation's
    `version` advances by one."

    Both refusals are non-events on the ledger: the reservation, the approver stamp
    and the donor's stock band are all untouched.

    Design: Difficulty/priority_pair_validation_conflict/program_locked_state_beats_benefit_ratio_fiscal_gate
    """
    scenario = _proposed_transfer_under_an_unreachable_ratio_gate()
    transfer = scenario["transfer"]

    lock_program(scenario["program"]["id"], "month-end freeze")
    validate_error(
        api.approve_transfer(transfer["id"], allocation_manager_headers),
        ApiErrorId.ERR_PROGRAM_LOCKED.value,
        409,
    )
    unlock_program(scenario["program"]["id"])
    validate_error(
        api.approve_transfer(transfer["id"], allocation_manager_headers),
        ApiErrorId.ERR_BENEFIT_RATIO_BELOW_THRESHOLD.value,
        409,
    )

    final = validate_success(
        api.get_transfer_recommendation(transfer["id"], allocation_manager_headers)
    )
    assert final["status"] == "PROPOSED"
    assert final["approved_by_user_id"] is None

    donor = refresh_position(scenario, "0102")
    assert donor["reserved_out_units"] == 0
    assert donor["available_units"] == 30
    assert donor["on_hand_units"] == 30


def _proposed_run_that_breaks_both_shelf_rules(api, manager_headers):
    """A MIN_MAX_TOPUP spread of an 8-unit receipt over 0101 (empty, need 8, shelf
    minimum 12) and 0104 (2 on hand, need 4, capacity 10). After the spread is
    PROPOSED an 8-unit rebalance is dispatched into 0104, so its pipeline grows past
    its fixture capacity while line 0101 still sits below its presentation minimum."""
    fixture_specs = {
        "0101": dict(FIXTURE_SPECS_THREE["0101"]),
        "0102": dict(FIXTURE_SPECS_THREE["0102"]),
        "0104": {
            "fixture_count": 1,
            "facings_per_fixture": 2,
            "units_per_facing": 5,
            "presentation_min_units": 2,
        },
    }
    position_specs = {
        "0101": {
            "on_hand_units": 0,
            "size_on_hand": [],
            "min_units": 6,
            "max_units": 8,
            "weekly_forecast_units": 4,
            "trailing_4wk_sales_units": 12,
        },
        "0102": {
            "on_hand_units": 30,
            "size_on_hand": [
                {"size_code": "S", "units": 10},
                {"size_code": "M", "units": 8},
                {"size_code": "L", "units": 8},
                {"size_code": "XL", "units": 4},
            ],
            "min_units": 8,
            "max_units": 24,
            "weekly_forecast_units": 5,
            "trailing_4wk_sales_units": 16,
        },
        "0104": {
            "on_hand_units": 2,
            "size_on_hand": [
                {"size_code": "M", "units": 1},
                {"size_code": "L", "units": 1},
            ],
            "min_units": 2,
            "max_units": 6,
            "weekly_forecast_units": 1,
            "trailing_4wk_sales_units": 3,
        },
    }
    network = setup_network(
        store_specs=[STORE_SPECS_FOUR[0], STORE_SPECS_FOUR[1], STORE_SPECS_FOUR[3]],
        fixture_specs=fixture_specs,
        position_specs=position_specs,
        program_overrides={"transfer_min_ratio_bp": 0},
        item_overrides={
            "sku_code": "SKU-2001",
            "style_code": "ST-200",
            "item_type": "BASIC",
        },
    )
    scenario = setup_network_with_staged_receipt(
        units_received=8,
        size_received=[
            {"size_code": "S", "units": 2},
            {"size_code": "M", "units": 3},
            {"size_code": "L", "units": 2},
            {"size_code": "XL", "units": 1},
        ],
        network=network,
    )
    scenario["run"] = create_proposed_run(
        scenario["receipt"]["id"], method="MIN_MAX_TOPUP", need_basis="FORWARD_LOOKING"
    )
    transfer = propose_transfer(scenario, from_code="0102", to_code="0104", units=8)
    validate_success(api.approve_transfer(transfer["id"], manager_headers))
    scenario["transfer"] = validate_success(
        api.dispatch_transfer(transfer["id"], manager_headers)
    )
    return scenario


def test_the_commit_reports_the_presentation_minimum_and_not_the_capacity_breach(
    api, allocation_manager_headers
):
    """PRD §3.7: "Third, every line of the run must satisfy the brand presentation
    standard: for each line, the destination position's `available_units` plus its
    `in_transit_units` plus the line's `units_proposed` must be greater than or equal
    to the store's in-effect `presentation_min_units` for the SKU's class, and any line
    that falls short refuses the whole commit with `ERR_PRESENTATION_MIN_NOT_MET`."
    PRD §2.10 ranks "Brand presentation minimum on every line of a run being committed
    — `ERR_PRESENTATION_MIN_NOT_MET`, 409." at rung 13, ahead of "Fixture capacity on a
    run commit, a transfer approval or a consolidation execution —
    `ERR_FIXTURE_CAPACITY_EXCEEDED`, 409." at rung 14.

    Line 0101 is 6 units short of a presentable set and line 0104 is 2 units over its
    fixtures; the safety rung answers even though the capacity breach is the bigger
    operational problem.

    Design: Difficulty/priority_pair_validation_conflict/presentation_minimum_safety_beats_fixture_capacity_constraint
    """
    scenario = _proposed_run_that_breaks_both_shelf_rules(api, allocation_manager_headers)

    validate_error(
        api.commit_run(scenario["run"]["id"], allocation_manager_headers),
        ApiErrorId.ERR_PRESENTATION_MIN_NOT_MET.value,
        409,
    )


def test_the_refused_commit_books_nothing_on_the_run_or_the_receipt(
    api, allocation_manager_headers
):
    """PRD §3.6: "A line's `units_allocated` is 0 while the run is merely `PROPOSED`,
    becomes equal to its `units_proposed` once the run is `COMMITTED`, and returns to 0
    if the run is later recalled."

    The refusal leaves the run PROPOSED, so no line is allocated anything and the
    receipt's whole pool of 8 units is still unallocated.

    Design: Difficulty/priority_pair_validation_conflict/presentation_minimum_safety_beats_fixture_capacity_constraint
    """
    scenario = _proposed_run_that_breaks_both_shelf_rules(api, allocation_manager_headers)
    run_id = scenario["run"]["id"]

    validate_error(
        api.commit_run(run_id, allocation_manager_headers),
        ApiErrorId.ERR_PRESENTATION_MIN_NOT_MET.value,
        409,
    )

    run = validate_success(api.get_allocation_run(run_id, allocation_manager_headers))
    assert run["status"] == "PROPOSED"
    assert run["units_committed"] == 0

    lines = lines_for_run(run_id)
    assert len(lines) == 2
    assert all(line["units_allocated"] == 0 for line in lines)
    assert all(line["fulfillment_status"] == "PENDING" for line in lines)

    receipt = refresh_receipt(scenario)
    assert receipt["units_unallocated"] == 8
    assert receipt["units_committed"] == 0


def test_both_shelf_rules_are_genuinely_broken_by_that_single_commit(
    api, allocation_manager_headers
):
    """PRD §3.6: "Each line records its owning `run_id` and destination `store_id`, the
    `need_units` computed for that store, the `units_proposed` the waterfall placed
    there, the `capacity_capped_units` from step three, and a `presentation_gap_units`
    figure computed as the greater of zero and the store's in-effect
    `presentation_min_units` less the sum of the position's `available_units`, its
    `in_transit_units` and the line's `units_proposed`." PRD §3.7: "Fourth, every line
    must satisfy fixture capacity: the same three quantities summed must be less than
    or equal to the in-effect shelf plan's `capacity_units`, and a breach refuses the
    commit with `ERR_FIXTURE_CAPACITY_EXCEEDED`."

    Line 0101 lands at 0 + 0 + 6 = 6 against a minimum of 12, and line 0104 lands at
    2 + 8 + 2 = 12 against a capacity of 10: the precedence claim is only meaningful
    because both sums are really out of bounds.

    Design: Difficulty/priority_pair_validation_conflict/presentation_minimum_safety_beats_fixture_capacity_constraint
    """
    scenario = _proposed_run_that_breaks_both_shelf_rules(api, allocation_manager_headers)
    run_id = scenario["run"]["id"]

    short_line = line_for_store(run_id, scenario["stores"]["0101"]["id"])
    assert short_line["need_units"] == 8
    assert short_line["units_proposed"] == 6
    assert short_line["presentation_gap_units"] == 6
    assert units_by_size(short_line["size_breakdown"]) == {"S": 1, "M": 3, "L": 2, "XL": 0}

    over_line = line_for_store(run_id, scenario["stores"]["0104"]["id"])
    assert over_line["need_units"] == 4
    assert over_line["units_proposed"] == 2
    assert over_line["presentation_gap_units"] == 0
    assert units_by_size(over_line["size_breakdown"]) == {"S": 0, "M": 1, "L": 1, "XL": 0}

    crowded = refresh_position(scenario, "0104")
    assert crowded["available_units"] == 2
    assert crowded["in_transit_units"] == 8
    assert scenario["fixture_plans"]["0104"]["capacity_units"] == 10
    assert 2 + 8 + over_line["units_proposed"] > 10


def test_the_rebalance_that_crowded_the_shelf_only_cleared_a_zero_ratio_floor(
    api, allocation_manager_headers
):
    """PRD §3.8: "Rounding happens **per size line**: for each entry of `size_split`,
    that entry's `units` multiplied by the realised per-unit margin is rounded half up
    to two decimals, and `benefit_usd` is the sum of those rounded per-size figures."
    And: "Fourth and last, `benefit_ratio_bp` is `benefit_usd` divided by
    `landed_cost_usd`, multiplied by 10000, rounded half up to a whole number of basis
    points."

    Eight units into 0104 fill its two empty CORE sizes S and XL, and at a
    sell-through of 3100 basis points the move only returns 9879 basis points of its
    landed cost — approvable solely because this program's floor is 0.

    Design: Difficulty/priority_pair_validation_conflict/presentation_minimum_safety_beats_fixture_capacity_constraint
    """
    scenario = _proposed_run_that_breaks_both_shelf_rules(api, allocation_manager_headers)
    transfer = scenario["transfer"]

    assert transfer["status"] == "DISPATCHED"
    assert units_by_size(transfer["size_split"]) == {"S": 5, "XL": 3}
    assert float(transfer["freight_cost_usd"]) == 45.00
    assert float(transfer["landed_cost_usd"]) == 50.40
    assert float(transfer["benefit_usd"]) == 49.79
    assert transfer["benefit_ratio_bp"] == 9879
    assert scenario["program"]["transfer_min_ratio_bp"] == 0


def _an_expired_recommendation_over_a_drained_donor(api, manager_headers):
    """A 12-unit rebalance 0102 -> 0101 is created at the default clock, then a
    competing 20-unit rebalance 0102 -> 0103 is approved and reserves twenty of the
    donor's thirty units. The clock is then moved one day past the first
    recommendation's expiry instant."""
    fixture_specs = {code: dict(spec) for code, spec in FIXTURE_SPECS_THREE.items()}
    fixture_specs["0103"] = {
        "fixture_count": 2,
        "facings_per_fixture": 5,
        "units_per_facing": 6,
        "presentation_min_units": 4,
    }
    position_specs = {
        code: dict(spec) for code, spec in POSITION_SPECS_REBALANCE.items()
    }
    position_specs["0102"] = dict(
        position_specs["0102"],
        size_on_hand=[
            {"size_code": "S", "units": 12},
            {"size_code": "M", "units": 6},
            {"size_code": "L", "units": 4},
            {"size_code": "XL", "units": 8},
        ],
    )
    position_specs["0103"] = dict(
        position_specs["0103"],
        size_on_hand=[
            {"size_code": "S", "units": 0},
            {"size_code": "M", "units": 3},
            {"size_code": "L", "units": 2},
            {"size_code": "XL", "units": 0},
        ],
    )
    scenario = setup_network(
        store_specs=STORE_SPECS_FOUR[:3],
        fixture_specs=fixture_specs,
        position_specs=position_specs,
        program_overrides={"transfer_min_ratio_bp": 0},
    )
    scenario["transfer"] = propose_transfer(
        scenario, from_code="0102", to_code="0101", units=12
    )
    competing = propose_transfer(
        scenario, from_code="0102", to_code="0103", units=20
    )
    scenario["competing"] = validate_success(
        api.approve_transfer(competing["id"], manager_headers)
    )
    set_clock("2026-08-09T00:00:00Z")
    return scenario


def test_an_aged_recommendation_reports_its_expiry_and_not_the_donor_shortfall(
    api, allocation_manager_headers, allocator_headers
):
    """PRD §3.8: "A `PROPOSED` recommendation may be approved only while the logical
    clock is **strictly before** `expires_at`; at or past that instant it is no longer
    approvable and an approval attempt is refused with `ERR_TRANSFER_EXPIRED`." PRD
    §2.10 ranks "A recommendation being approved has not expired —
    `ERR_TRANSFER_EXPIRED`, 409." at rung 24, ahead of "The donor position holds enough
    uncommitted stock — `ERR_INSUFFICIENT_DONOR_UNITS`, 409." at rung 33.

    The clock stands at 2026-08-09 against an expiry of 2026-08-08 while the donor can
    only free 10 of the 12 units asked for: the temporal rung answers first.

    Design: Difficulty/priority_pair_validation_conflict/transfer_expiry_temporal_beats_insufficient_donor_units_fiscal
    """
    scenario = _an_expired_recommendation_over_a_drained_donor(
        api, allocation_manager_headers
    )
    aged = scenario["transfer"]
    assert aged["expires_at"][:19] == "2026-08-08T00:00:00"

    donor = refresh_position(scenario, "0102")
    assert donor["available_units"] == 10

    validate_error(
        api.approve_transfer(aged["id"], allocation_manager_headers),
        ApiErrorId.ERR_TRANSFER_EXPIRED.value,
        409,
    )

    unchanged = validate_success(
        api.get_transfer_recommendation(aged["id"], allocator_headers)
    )
    assert unchanged["status"] == "PROPOSED"
    assert unchanged["approved_by_user_id"] is None


def test_the_create_path_has_no_expiry_rung_so_the_donor_shortfall_surfaces_there(
    api, allocation_manager_headers, allocator_headers
):
    """PRD §3.8: "The donor position must hold enough uncommitted stock, meaning its
    `available_units` must be at least the requested `units`, or the request is refused
    with `ERR_INSUFFICIENT_DONOR_UNITS`."

    Re-asking for the identical 12-unit move at the new clock proves the fiscal
    violation was real all along — creation never consults `expires_at`, so the rung
    that rung 24 had masked is the one that answers.

    Design: Difficulty/priority_pair_validation_conflict/transfer_expiry_temporal_beats_insufficient_donor_units_fiscal
    """
    scenario = _an_expired_recommendation_over_a_drained_donor(
        api, allocation_manager_headers
    )
    validate_error(
        api.approve_transfer(scenario["transfer"]["id"], allocation_manager_headers),
        ApiErrorId.ERR_TRANSFER_EXPIRED.value,
        409,
    )

    payload = create_transfer_payload(
        scenario["program"]["id"],
        scenario["stores"]["0102"]["id"],
        scenario["stores"]["0101"]["id"],
        scenario["item"]["id"],
        12,
        current_position_version(scenario["positions"]["0102"]["id"]),
    )
    validate_error(
        api.create_transfer_recommendation(payload, allocator_headers),
        ApiErrorId.ERR_INSUFFICIENT_DONOR_UNITS.value,
        409,
    )


def test_a_refused_create_supersedes_nothing_on_the_same_triple(
    api, allocation_manager_headers, allocator_headers
):
    """PRD §3.8: "If any recommendation on the identical donor-store, receiving-store
    and SKU triple is already sitting in `PROPOSED`, that peer is driven to `CANCELLED`
    with its `reject_reason` set to the string `superseded`, its `version` advances by
    one, and the new recommendation's `supersedes_recommendation_id` points at it."

    The refused create shares the donor, receiver and SKU of the aged recommendation,
    yet cancels nothing: a rejected write leaves the supersede chain alone.

    Design: Difficulty/priority_pair_validation_conflict/transfer_expiry_temporal_beats_insufficient_donor_units_fiscal
    """
    scenario = _an_expired_recommendation_over_a_drained_donor(
        api, allocation_manager_headers
    )
    aged = scenario["transfer"]

    payload = create_transfer_payload(
        scenario["program"]["id"],
        scenario["stores"]["0102"]["id"],
        scenario["stores"]["0101"]["id"],
        scenario["item"]["id"],
        12,
        current_position_version(scenario["positions"]["0102"]["id"]),
    )
    validate_error(
        api.create_transfer_recommendation(payload, allocator_headers),
        ApiErrorId.ERR_INSUFFICIENT_DONOR_UNITS.value,
        409,
    )

    survivor = validate_success(
        api.get_transfer_recommendation(aged["id"], allocator_headers)
    )
    assert survivor["status"] == "PROPOSED"
    assert survivor["supersedes_recommendation_id"] is None
    assert survivor["reject_reason"] is None


def test_the_competing_approval_is_what_drained_the_donor(
    api, allocation_manager_headers
):
    """PRD §3.8: "For a `REBALANCE` transfer the goal is to fill holes: the candidate
    sizes are the SKU's **CORE** sizes for which the receiving position shows zero units
    on hand and the donor position shows more than zero, and each candidate's weight is
    its `share_bp` from the size curve."

    0103 is empty in S and XL, so the twenty approved units are drawn entirely from the
    donor's twelve S and eight XL and reserved against it — which is precisely why the
    older 12-unit request can no longer be funded.

    Design: Difficulty/priority_pair_validation_conflict/transfer_expiry_temporal_beats_insufficient_donor_units_fiscal
    """
    scenario = _an_expired_recommendation_over_a_drained_donor(
        api, allocation_manager_headers
    )
    competing = scenario["competing"]

    assert competing["status"] == "APPROVED"
    assert units_by_size(competing["size_split"]) == {"S": 12, "XL": 8}

    donor = refresh_position(scenario, "0102")
    assert donor["on_hand_units"] == 30
    assert donor["reserved_out_units"] == 20
    assert donor["available_units"] == 10
    assert size_units(donor, "size_on_hand") == {"S": 12, "M": 6, "L": 4, "XL": 8}
