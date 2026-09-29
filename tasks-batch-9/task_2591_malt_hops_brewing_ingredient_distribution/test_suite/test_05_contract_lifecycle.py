"""Hop contracts: the carry-forward loop, program settlement, windows and offers."""
import pytest

from test_helpers import (
    AM_HEADERS,
    contract_version,
    create_brewer,
    create_contract,
    create_program,
    create_variety,
    decide_carry_forward,
    get_brewer,
    pin_clock,
    report_harvest,
    request_carry_forward,
    validate_error,
    validate_paginated,
    validate_success,
)


@pytest.fixture
def rollover_world():
    """A harvest-reported 2026 contract with an OPEN 2027 program to roll into."""
    pin_clock()
    brewer = create_brewer(name="Rollover Brewing", credit_limit_cents=5000000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    prog26 = create_program(crop_year=2026)
    prog27 = create_program(crop_year=2027)
    variety = create_variety()
    contract = create_contract(brewer["id"], variety["id"], prog26["id"],
                               contracted_lbs=5000, price_per_lb_cents=250.00)
    report_harvest(prog26["id"], harvest_yield_pct=100.00)
    return {"brewer": brewer, "prog26": prog26, "prog27": prog27,
            "variety": variety, "contract": contract}


def test_a_carry_forward_request_parks_the_contract_and_prices_the_fee(
        api, rollover_world):
    """1,250 lbs is exactly the 25 percent cap and carries an 8 percent fee.

    PRD §3.5: "The accepted request writes `carry_forward_requested_lbs` equal to
    the requested poundage and `carry_forward_fee_cents` equal to the requested
    poundage multiplied by `price_per_lb_cents`, multiplied by 8 and divided by
    100, rounded half up to whole cents"

    Design: Difficulty/non_linear_state_machine/hop_contract_carry_forward_decline_reenters_active
    """
    world = rollover_world
    contract = request_carry_forward(world["contract"]["id"], world["brewer"]["id"],
                                     world["prog27"]["id"], 1250,
                                     justification="tank space")

    assert contract["status"] == "CARRY_FORWARD_PENDING", (
        f"the request parks the contract, got {contract['status']}")
    assert contract["carry_forward_requested_lbs"] == 1250, (
        f"the requested poundage is recorded, got "
        f"{contract['carry_forward_requested_lbs']}")
    assert contract["carry_forward_fee_cents"] == 25000, (
        f"1250 * 250.00 * 8 / 100 = 25000, got {contract['carry_forward_fee_cents']}")
    assert contract["carry_forward_target_program_id"] == world["prog27"]["id"], (
        "the target program is stamped, got "
        f"{contract['carry_forward_target_program_id']}")
    assert contract["carried_forward_out_lbs"] == 0, (
        "nothing has rolled yet, got "
        f"{contract['carried_forward_out_lbs']}")

    brewer = get_brewer(world["brewer"]["id"])
    assert brewer["ar_balance_cents"] == 0, (
        f"the fee posts only on approval, got {brewer['ar_balance_cents']}")


def test_declining_returns_the_contract_to_active_and_clears_the_request_fields(
        api, rollover_world):
    """A DECLINE nulls the three request fields so the retry recomputes them.

    PRD §3.5: "Declining moves the contract `CARRY_FORWARD_PENDING → ACTIVE` and
    clears `carry_forward_target_program_id`, `carry_forward_requested_lbs` and
    `carry_forward_fee_cents` back to null"

    Design: Difficulty/non_linear_state_machine/hop_contract_carry_forward_decline_reenters_active
    """
    world = rollover_world
    request_carry_forward(world["contract"]["id"], world["brewer"]["id"],
                          world["prog27"]["id"], 1250)
    declined = decide_carry_forward(world["contract"]["id"], "DECLINE",
                                    decision_note="crop already allocated")

    assert declined["status"] == "ACTIVE", (
        f"the decline re-enters ACTIVE, got {declined['status']}")
    assert declined["carry_forward_target_program_id"] is None, (
        "the target must be cleared, got "
        f"{declined['carry_forward_target_program_id']}")
    assert declined["carry_forward_requested_lbs"] is None, (
        "the requested poundage must be cleared, got "
        f"{declined['carry_forward_requested_lbs']}")
    assert declined["carry_forward_fee_cents"] is None, (
        f"the fee must be cleared, got {declined['carry_forward_fee_cents']}")
    assert declined["carried_forward_out_lbs"] == 0, (
        f"nothing rolled out, got {declined['carried_forward_out_lbs']}")
    assert declined["remaining_lbs"] == 5000, (
        f"the whole commitment is still undrawn, got {declined['remaining_lbs']}")

    resubmitted = request_carry_forward(world["contract"]["id"],
                                        world["brewer"]["id"],
                                        world["prog27"]["id"], 1250,
                                        justification="re-submitted after review")
    assert resubmitted["status"] == "CARRY_FORWARD_PENDING", (
        f"the second request parks the contract again, got {resubmitted['status']}")
    assert resubmitted["carry_forward_fee_cents"] == 25000, (
        "the fee is recomputed from scratch on the second pass, got "
        f"{resubmitted['carry_forward_fee_cents']}")


def test_only_the_second_pass_mints_the_successor_contract_and_posts_the_fee(
        api, rollover_world):
    """Approval after the retry rolls 1,250 lbs into 2027 and bills the fee once.

    PRD §3.5: "mints a successor contract in the target program carrying the same
    `brewer_id`, `variety_id`, `contract_type` and `price_per_lb_cents`, with
    `contracted_lbs` equal to the carried poundage, `carried_forward_from_contract_id`
    pointing back at the predecessor, a delivery window shifted forward by 365 days
    from the predecessor's `delivery_window_start` and `delivery_window_end`"

    Design: Difficulty/non_linear_state_machine/hop_contract_carry_forward_decline_reenters_active
    """
    world = rollover_world
    request_carry_forward(world["contract"]["id"], world["brewer"]["id"],
                          world["prog27"]["id"], 1250)
    decide_carry_forward(world["contract"]["id"], "DECLINE")
    request_carry_forward(world["contract"]["id"], world["brewer"]["id"],
                          world["prog27"]["id"], 1250)
    approved = decide_carry_forward(world["contract"]["id"], "APPROVE",
                                    decision_note="approved on appeal")

    assert approved["status"] == "CARRIED_FORWARD", (
        f"approval is terminal for the predecessor, got {approved['status']}")
    assert approved["carried_forward_out_lbs"] == 1250, (
        f"1250 lbs rolled out, got {approved['carried_forward_out_lbs']}")
    assert approved["remaining_lbs"] == 3750, (
        f"5000 - 1250 = 3750 undrawn, got {approved['remaining_lbs']}")
    assert approved["allocated_lbs"] == 5000, (
        f"the roll does not touch the crop allocation, got {approved['allocated_lbs']}")

    rows, meta = validate_paginated(api.list_hop_contracts(
        AM_HEADERS,
        params={"carried_forward_from_contract_id": world["contract"]["id"]}))
    assert meta["total_count"] == 1, (
        f"exactly one successor exists, got {meta['total_count']}")
    successor = rows[0]
    assert successor["contracted_lbs"] == 1250, (
        f"the successor carries the rolled poundage, got {successor['contracted_lbs']}")
    assert successor["status"] == "ACTIVE", (
        f"the successor opens ACTIVE, got {successor['status']}")
    assert successor["crop_year_program_id"] == world["prog27"]["id"], (
        f"it books against 2027, got {successor['crop_year_program_id']}")
    assert successor["price_per_lb_cents"] == pytest.approx(250.00, abs=0.005), (
        f"the price carries over, got {successor['price_per_lb_cents']}")
    assert successor["contract_type"] == "FIXED_CROP_YEAR", (
        f"the type carries over, got {successor['contract_type']}")
    assert successor["delivery_window_start"].startswith("2027-09-01"), (
        "2026-09-01 plus 365 days is 2027-09-01, got "
        f"{successor['delivery_window_start']}")
    assert successor["delivery_window_end"].startswith("2027-12-31"), (
        "2026-12-31 plus 365 days is 2027-12-31, got "
        f"{successor['delivery_window_end']}")

    brewer = get_brewer(world["brewer"]["id"])
    assert brewer["ar_balance_cents"] == 25000, (
        f"the fee is billed exactly once, got {brewer['ar_balance_cents']}")
    assert brewer["credit_utilization_pct"] == pytest.approx(0.50, abs=0.005), (
        f"25000 against a 5,000,000-cent limit, got {brewer['credit_utilization_pct']}")
    assert brewer["credit_status"] == "GOOD_STANDING", (
        f"the brewer is nowhere near its limit, got {brewer['credit_status']}")


@pytest.fixture
def program_with_pending_child():
    """A HARVEST_REPORTED 2026 program holding one CARRY_FORWARD_PENDING contract."""
    pin_clock()
    brewer = create_brewer(name="Openbook Brewing", credit_limit_cents=5000000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    prog26 = create_program(crop_year=2026)
    prog27 = create_program(crop_year=2027)
    variety = create_variety()
    contract = create_contract(brewer["id"], variety["id"], prog26["id"],
                               contracted_lbs=5000, price_per_lb_cents=250.00)
    report_harvest(prog26["id"], harvest_yield_pct=100.00)
    contract = request_carry_forward(contract["id"], brewer["id"], prog27["id"],
                                     1250,
                                     justification="no tank space this year")
    return {"brewer": brewer, "prog26": prog26, "prog27": prog27,
            "contract": contract}


def test_settlement_is_blocked_while_a_child_contract_is_carry_forward_pending(
        api, program_with_pending_child):
    """The program's own status is already correct, so the child is the whole reason.

    PRD §3.3: "Settlement is refused with `ERR_INVALID_PROGRAM_STATE` when the
    program is not in `HARVEST_REPORTED`, and equally when any contract belonging
    to the program is still sitting in `CARRY_FORWARD_PENDING`"

    Design: Difficulty/cross_entity_state_dependency/program_settlement_gated_on_pending_carry_forward_contract
    """
    world = program_with_pending_child
    assert world["contract"]["status"] == "CARRY_FORWARD_PENDING", (
        f"the child must be parked, got {world['contract']['status']}")

    program = validate_success(api.get_crop_year_program(world["prog26"]["id"],
                                                        AM_HEADERS))
    assert program["status"] == "HARVEST_REPORTED", (
        f"the parent's own status is already correct, got {program['status']}")

    blocked = api.settle_program(world["prog26"]["id"],
                                 {"settlement_note": "closing the crop year"},
                                 AM_HEADERS)
    validate_error(blocked, "ERR_INVALID_PROGRAM_STATE", expected_status=409)

    program = validate_success(api.get_crop_year_program(world["prog26"]["id"],
                                                         AM_HEADERS))
    assert program["status"] == "HARVEST_REPORTED", (
        f"the refused settlement changes nothing, got {program['status']}")


def test_deciding_the_child_request_unblocks_the_parent_settlement(
        api, program_with_pending_child):
    """Resolving the child needs an act on the child, not a retry on the parent.

    PRD §3.3: "Once every carry-forward request against the program has been
    decided, the hop desk closes it, transitioning `HARVEST_REPORTED → SETTLED`
    with an optional `settlement_note`."

    Design: Difficulty/cross_entity_state_dependency/program_settlement_gated_on_pending_carry_forward_contract
    """
    world = program_with_pending_child
    validate_error(api.settle_program(world["prog26"]["id"],
                                      {"settlement_note": "closing the crop year"},
                                      AM_HEADERS),
                   "ERR_INVALID_PROGRAM_STATE", expected_status=409)

    declined = decide_carry_forward(world["contract"]["id"], "DECLINE",
                                    decision_note="2027 crop already committed")
    assert declined["status"] == "ACTIVE", (
        f"the child returns to ACTIVE, got {declined['status']}")
    assert declined["carry_forward_requested_lbs"] is None, (
        "the decline clears the request, got "
        f"{declined['carry_forward_requested_lbs']}")

    settled = validate_success(api.settle_program(
        world["prog26"]["id"], {"settlement_note": "closing the crop year"},
        AM_HEADERS))
    assert settled["status"] == "SETTLED", (
        f"the parent now closes, got {settled['status']}")

    other = validate_success(api.get_crop_year_program(world["prog27"]["id"],
                                                       AM_HEADERS))
    assert other["status"] == "OPEN", (
        f"only the source program settles, got {other['status']}")

    brewer = get_brewer(world["brewer"]["id"])
    assert brewer["ar_balance_cents"] == 0, (
        f"a declined carry-forward posts no fee, got {brewer['ar_balance_cents']}")


@pytest.fixture
def window_world():
    """An OPEN 2026 program and one Citra brewer with no contracts yet."""
    pin_clock()
    brewer = create_brewer(name="Window Pane Brewing", credit_limit_cents=5000000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    program = create_program(crop_year=2026)
    variety = create_variety()
    return {"brewer": brewer, "program": program, "variety": variety}


def test_two_windows_sharing_one_endpoint_date_are_refused_as_an_intersection(
        api, window_world):
    """A window ending 2026-12-31 collides with one starting 2026-12-31.

    PRD §3.2: "sharing a single endpoint date **is** an intersection and is
    refused with `ERR_CONTRACT_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/contract_delivery_windows_are_closed_intervals_sharing_an_endpoint
    """
    world = window_world
    first = create_contract(world["brewer"]["id"], world["variety"]["id"],
                            world["program"]["id"], contracted_lbs=2000,
                            price_per_lb_cents=285.50,
                            delivery_window_start="2026-09-01T00:00:00Z",
                            delivery_window_end="2026-12-31T00:00:00Z")
    assert first["status"] == "ACTIVE", (
        f"the first window is written, got {first['status']}")
    version_before = contract_version(first["id"])

    clash = api.create_hop_contract(
        {"brewer_id": world["brewer"]["id"], "variety_id": world["variety"]["id"],
         "crop_year_program_id": world["program"]["id"],
         "contract_type": "SPOT_HOLD", "contracted_lbs": 1000,
         "price_per_lb_cents": 51.00,
         "delivery_window_start": "2026-12-31T00:00:00Z",
         "delivery_window_end": "2027-03-31T00:00:00Z"},
        AM_HEADERS)
    validate_error(clash, "ERR_CONTRACT_WINDOW_OVERLAP", expected_status=409)

    rows, meta = validate_paginated(api.list_hop_contracts(
        AM_HEADERS, params={"brewer_id": world["brewer"]["id"]}))
    assert meta["total_count"] == 1, (
        f"the refused write left no row, got {meta['total_count']}")
    assert contract_version(first["id"]) == version_before, (
        "the refused write must not disturb the existing contract, version moved "
        f"from {version_before} to {contract_version(first['id'])}")


def test_one_day_of_clearance_between_closed_windows_is_enough(api, window_world):
    """2027-01-01 shares no instant with a window closing on 2026-12-31.

    PRD §3.2: "Two contracts for the same brewery-and-variety pair may not have
    intersecting delivery windows: the check compares closed inclusive intervals
    against every existing contract for that pair whose `status` is anything other
    than `CARRIED_FORWARD` or `RESOLD`"

    Design: Difficulty/resource_temporal_overlap/contract_delivery_windows_are_closed_intervals_sharing_an_endpoint
    """
    world = window_world
    first = create_contract(world["brewer"]["id"], world["variety"]["id"],
                            world["program"]["id"], contracted_lbs=2000,
                            price_per_lb_cents=285.50,
                            delivery_window_start="2026-09-01T00:00:00Z",
                            delivery_window_end="2026-12-31T00:00:00Z")
    validate_error(api.create_hop_contract(
        {"brewer_id": world["brewer"]["id"], "variety_id": world["variety"]["id"],
         "crop_year_program_id": world["program"]["id"],
         "contract_type": "SPOT_HOLD", "contracted_lbs": 1000,
         "price_per_lb_cents": 51.00,
         "delivery_window_start": "2026-12-31T00:00:00Z",
         "delivery_window_end": "2027-03-31T00:00:00Z"}, AM_HEADERS),
        "ERR_CONTRACT_WINDOW_OVERLAP", expected_status=409)

    cleared = validate_success(api.create_hop_contract(
        {"brewer_id": world["brewer"]["id"], "variety_id": world["variety"]["id"],
         "crop_year_program_id": world["program"]["id"],
         "contract_type": "SPOT_HOLD", "contracted_lbs": 1000,
         "price_per_lb_cents": 51.00,
         "delivery_window_start": "2027-01-01T00:00:00Z",
         "delivery_window_end": "2027-03-31T00:00:00Z"}, AM_HEADERS),
        expected_status=201)
    assert cleared["status"] == "ACTIVE", (
        f"a single day of clearance is enough, got {cleared['status']}")

    rows, meta = validate_paginated(api.list_hop_contracts(
        AM_HEADERS, params={"brewer_id": world["brewer"]["id"]}))
    assert meta["total_count"] == 2, (
        f"both accepted contracts are on file, got {meta['total_count']}")
    assert first["remaining_lbs"] == 2000 and cleared["remaining_lbs"] == 1000, (
        "neither commitment is drawn, got "
        f"{first['remaining_lbs']} and {cleared['remaining_lbs']}")


@pytest.fixture
def substitution_world():
    """A shorted Citra contract whose only group peer holds 999 spot pounds."""
    pin_clock()
    brewer = create_brewer(name="Substitute Brewing", credit_limit_cents=5000000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    program = create_program(crop_year=2026)
    citra = create_variety()
    mosaic = create_variety(variety_code="MOSAIC", name="Mosaic",
                            alpha_acid_target_pct=12.00,
                            spot_price_cents_per_lb=450.00,
                            available_spot_lbs=999)
    contract = create_contract(brewer["id"], citra["id"], program["id"],
                               contracted_lbs=5000, price_per_lb_cents=285.50)
    report_harvest(program["id"], harvest_yield_pct=80.00,
                   reported_note="crop down a fifth")
    return {"brewer": brewer, "program": program, "citra": citra,
            "mosaic": mosaic, "contract": contract}


def test_a_peer_one_pound_short_of_the_offer_leaves_the_candidate_pool_empty(
        api, substitution_world):
    """999 available against 1,000 offered is not a candidate, so nothing is minted.

    PRD §3.4: "a variety is only a legitimate substitute when three things hold:
    its `substitution_group` equals the shorted variety's `substitution_group`, it
    is not the shorted variety itself, and its `available_spot_lbs` is at least the
    offered poundage."

    Design: Difficulty/boundary_precision_check/substitute_candidate_admitted_at_exactly_offered_pounds
    """
    world = substitution_world
    contract = validate_success(api.get_hop_contract(world["contract"]["id"],
                                                     AM_HEADERS))
    assert contract["status"] == "SHORTFALL_ADJUSTED", (
        f"an 80 percent crop cuts the contract back, got {contract['status']}")
    assert contract["allocated_lbs"] == 4000 and contract["shortfall_lbs"] == 1000, (
        "5000 at 80 percent allocates 4000 and shorts 1000, got allocated "
        f"{contract['allocated_lbs']} shortfall {contract['shortfall_lbs']}")
    version_before = contract["version"]

    refused = api.create_substitution_offer(
        world["contract"]["id"],
        {"expected_hop_contract_version": version_before,
         "selection_mode": "AUTO_RANKED", "offered_lbs": 1000},
        AM_HEADERS)
    validate_error(refused, "ERR_NO_SUBSTITUTE_AVAILABLE", expected_status=422)

    rows, meta = validate_paginated(api.list_substitution_offers(
        AM_HEADERS, params={"hop_contract_id": world["contract"]["id"]}))
    assert meta["total_count"] == 0, (
        f"no offer row may be created, got {meta['total_count']}")
    assert contract_version(world["contract"]["id"]) == version_before, (
        "the refused call must not bump the contract, version moved from "
        f"{version_before} to {contract_version(world['contract']['id'])}")


def test_exactly_the_offered_poundage_admits_the_peer_and_mints_the_offer(
        api, substitution_world):
    """Repricing Mosaic to exactly 1,000 available makes the same call succeed.

    PRD §3.4: "The first candidate in that order is selected, its
    `spot_price_cents_per_lb` is snapshotted onto the offer as
    `offered_price_cents_per_lb`, and `selection_mode` is recorded as
    `AUTO_RANKED`."

    Design: Difficulty/boundary_precision_check/substitute_candidate_admitted_at_exactly_offered_pounds
    """
    world = substitution_world
    validate_error(api.create_substitution_offer(
        world["contract"]["id"],
        {"expected_hop_contract_version": contract_version(world["contract"]["id"]),
         "selection_mode": "AUTO_RANKED", "offered_lbs": 1000}, AM_HEADERS),
        "ERR_NO_SUBSTITUTE_AVAILABLE", expected_status=422)

    validate_success(api.update_spot_price(
        world["mosaic"]["id"],
        {"spot_price_cents_per_lb": 450.00, "available_spot_lbs": 1000},
        AM_HEADERS))

    offer = validate_success(api.create_substitution_offer(
        world["contract"]["id"],
        {"expected_hop_contract_version": contract_version(world["contract"]["id"]),
         "selection_mode": "AUTO_RANKED", "offered_lbs": 1000}, AM_HEADERS),
        expected_status=201)

    assert offer["status"] == "OPEN", (
        f"the minted offer opens OPEN, got {offer['status']}")
    assert offer["substitute_variety_id"] == world["mosaic"]["id"], (
        f"Mosaic is the only peer, got {offer['substitute_variety_id']}")
    assert offer["offered_lbs"] == 1000, (
        f"the offered poundage is recorded, got {offer['offered_lbs']}")
    assert offer["offered_price_cents_per_lb"] == pytest.approx(450.00, abs=0.005), (
        f"Mosaic's spot price is snapshotted, got "
        f"{offer['offered_price_cents_per_lb']}")
    assert offer["alpha_acid_delta_pct"] == pytest.approx(0.50, abs=0.005), (
        f"the absolute difference of 12.00 and 12.50, got "
        f"{offer['alpha_acid_delta_pct']}")

    mosaic = validate_success(api.get_hop_variety(world["mosaic"]["id"], AM_HEADERS))
    assert mosaic["available_spot_lbs"] == 1000, (
        "nothing is drawn until the brewer accepts, got "
        f"{mosaic['available_spot_lbs']}")

    rows, meta = validate_paginated(api.list_substitution_offers(
        AM_HEADERS, params={"hop_contract_id": world["contract"]["id"]}))
    assert meta["total_count"] == 1, (
        f"exactly one offer exists, got {meta['total_count']}")
