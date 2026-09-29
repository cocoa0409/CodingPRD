"""
The guards that stand between treated salt and a saleable pile, and between an
awarded contract and a customer's call on it.

These cover the quality-adjudication preconditions of PRD §3.5, the covered-storage
and capacity rules of §3.6, and the take-band and pre-season gates of §3.8. Every
threshold is exercised on the exact inclusive edge the PRD names, so that a rule
which admits "at least" is not implemented as "greater than".
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f, fixtures as fx
from test_helpers.api_errors import (
    ERR_COVERED_CAPACITY_EXCEEDED,
    ERR_DEPOT_CLOSED,
    ERR_PRESEASON_WINDOW_CLOSED,
    ERR_PURITY_BELOW_SPEC,
    ERR_TAKE_BAND_EXCEEDED,
    ERR_UNCOVERED_STORAGE_NOT_ALLOWED,
)
from test_helpers.assertions import (
    assert_amount,
    assert_lot_tonnage,
    assert_page_meta,
    assert_posture_view_threshold,
    assert_purity,
    assert_tons,
    assert_version_unchanged,
)
from test_helpers.constants import (
    COARSE,
    CONTRACT_ACTIVE,
    CONTRACT_AWARDED,
    COVERED,
    DECISION_PASS,
    DECISION_REWORK,
    DEPOT_CLOSED,
    DEPOT_OPEN,
    DEPOT_SURGE,
    FINE,
    FOOD_GRADE,
    HIGHWAY_DEICING,
    JURISDICTION_MUNICIPAL,
    LOT_AVAILABLE,
    METHOD_SEVERITY_WEIGHTED,
    OPEN_PAD,
    ORDER_ALLOCATED,
    ORDER_REQUESTED,
    ORDER_SHORTED,
    QC_PASSED,
    QC_PENDING,
    RUN_CLOSED,
    RUN_HOISTED,
    WATER_CONDITIONING,
)
from test_helpers.test_users import (
    CONTRACT_ADMIN,
    LAB_LEAD,
    LAB_TECH,
    LOGISTICS,
)

MINE = {"name": "Retsof Salt Mine", "state_code": "NY", "rated_hoist_tons_per_day": 24000}

WINDOW = {
    "hoist_window_start": "2026-08-02T00:00:00Z",
    "hoist_window_end": "2026-08-03T00:00:00Z",
}

FORECAST = {
    "season_code": "2026-27",
    "region_code": "NY-CENTRAL",
    "normal_season_tons": 20000,
    "severity_index": 60,
    "prior_season_1_actual_tons": 21000,
    "prior_season_2_actual_tons": 19000,
    "prior_season_3_actual_tons": 18000,
    "method": METHOD_SEVERITY_WEIGHTED,
    "preseason_lock_date": "2026-10-15T00:00:00Z",
}


def _panel(grade_pct_nacl: float, panel_code: str = "P-1") -> dict:
    """A panel whose reserve is a round 50,000 tons, so only the grade varies."""
    return {
        "panel_code": panel_code,
        "gross_tons_in_place": 100000,
        "extraction_ratio_pct": 50,
        "grade_pct_nacl": grade_pct_nacl,
        "insolubles_pct": 2.00,
    }


def _depot(name: str, covered: float = 5000, open_pad: float = 5000, freight: float = 12.500) -> dict:
    return {
        "name": name,
        "state_code": "NY",
        "covered_capacity_tons": covered,
        "open_pad_capacity_tons": open_pad,
        "loadout_rate_tons_per_hour": 500,
        "outbound_freight_rate_per_ton": freight,
    }


def test_water_conditioning_pass_below_minimum_purity_is_refused(api):
    """
    Water conditioning salt must assay at least 99.5 % NaCl. A COARSE cut off a
    95.00 % panel computes 95.500, so the batch may be opened but its quality-control
    pass must be refused and no tonnage may come into existence.
    "The batch's computed `purity_pct_nacl` must be at least the product line's
    minimum purity from §2.11, else `ERR_PURITY_BELOW_SPEC`."

    Design: Corner/validations/water_conditioning_pass_below_min_purity_returns_purity_below_spec
    """
    world = fx.hoisted_run(
        api,
        mine_kwargs=MINE,
        panel_kwargs=_panel(95.00),
        hoisted_tons=1500,
        planned_tons=1500,
        **WINDOW,
    )
    depot = fx.create_depot(api, **_depot("Syracuse Depot"))

    batch = validate_success(
        api.create_batch(
            f.batch_payload(
                world["run"]["id"],
                depot["id"],
                product_line=WATER_CONDITIONING,
                screen_spec=COARSE,
                anticaking_ppm=0.00,
                corrosion_inhibitor_pct=0.00,
                input_tons=1000,
                moisture_pct=0.00,
                storage_kind=COVERED,
            ),
            LAB_TECH,
        ),
        201,
    )
    # 95.00 panel grade plus the COARSE upgrade of 0.5 points.
    assert_purity(batch["purity_pct_nacl"], 95.500)
    assert_tons(batch["yield_tons"], 940.00, "yield_tons")

    validate_error(
        api.qc_decision(batch["id"], f.qc_decision_payload(DECISION_PASS), LAB_LEAD),
        ERR_PURITY_BELOW_SPEC,
        409,
    )

    after = fx.refresh_batch(api, batch["id"])
    assert after["qc_state"] == QC_PENDING, (
        f"a refused pass leaves the batch PENDING, got {after['qc_state']}"
    )
    assert after["qc_decided_by_user_id"] is None, (
        "a refused pass must not stamp qc_decided_by_user_id"
    )
    assert_version_unchanged(after, batch)

    # Nothing was minted: the pass is the only operation that creates tonnage.
    _, meta = validate_paginated(
        api.list_lots(LOGISTICS, {"treatment_batch_id": batch["id"]})
    )
    assert_page_meta(meta, total_count=0)
    posture = fx.storage_posture(api, depot["id"])
    assert_tons(posture["covered_stored_tons"], 0.00, "covered_stored_tons")

    run = fx.refresh_run(api, world["run"]["id"])
    assert run["open_batch_count"] == 1, (
        f"the batch is still pending, got open_batch_count {run['open_batch_count']}"
    )
    assert run["status"] == RUN_HOISTED, (
        f"the run cannot auto-close with a pending batch, got {run['status']}"
    )


def test_food_grade_batch_exactly_at_the_minimum_purity_passes(api):
    """
    Food grade salt must assay at least 99.6 % NaCl. A FINE cut off a 97.10 % panel
    computes exactly 99.600, which sits on the floor rather than above it, and the
    pass must therefore be admitted and mint the pile.
    "The batch's computed `purity_pct_nacl` must be at least the product line's
    minimum purity from §2.11, else `ERR_PURITY_BELOW_SPEC`."
    "The batch's `purity_pct_nacl` is the `grade_pct_nacl` of the panel behind the
    feeding run plus that upgrade, capped at a ceiling of 99.9, rounded half up to
    three decimal places."

    Design: Corner/validations/food_grade_batch_exactly_at_the_minimum_purity_passes
    """
    world = fx.hoisted_run(
        api,
        mine_kwargs=MINE,
        panel_kwargs=_panel(97.10),
        hoisted_tons=1500,
        planned_tons=1500,
        **WINDOW,
    )
    depot = fx.create_depot(api, **_depot("Syracuse Depot"))

    batch = validate_success(
        api.create_batch(
            f.batch_payload(
                world["run"]["id"],
                depot["id"],
                product_line=FOOD_GRADE,
                screen_spec=FINE,
                anticaking_ppm=8.00,
                corrosion_inhibitor_pct=0.00,
                input_tons=1000,
                moisture_pct=0.00,
                storage_kind=COVERED,
            ),
            LAB_TECH,
        ),
        201,
    )
    # 97.10 + 2.5 = 99.600, exactly the FOOD_GRADE floor.
    assert_purity(batch["purity_pct_nacl"], 99.600)

    passed = validate_success(
        api.qc_decision(batch["id"], f.qc_decision_payload(DECISION_PASS), LAB_LEAD), 200
    )
    assert passed["qc_state"] == QC_PASSED, (
        f"a batch on the purity floor passes, got {passed['qc_state']}"
    )

    lot = fx.lot_of_batch(api, batch["id"])
    assert_purity(lot["purity_pct_nacl"], 99.600)
    assert lot["product_line"] == FOOD_GRADE, (
        f"the lot copies the batch product line, got {lot['product_line']}"
    )
    assert lot["storage_kind"] == COVERED, (
        f"food grade salt is stored COVERED, got {lot['storage_kind']}"
    )
    assert lot["lot_state"] == LOT_AVAILABLE, (
        f"a freshly minted lot is AVAILABLE, got {lot['lot_state']}"
    )
    # 1000 * 0.82 landed in the shed.
    assert_lot_tonnage(lot, on_hand=820.00, reserved=0.00, available=820.00)

    posture = fx.storage_posture(api, depot["id"])
    assert_tons(posture["covered_stored_tons"], 820.00, "covered_stored_tons")
    assert_amount(posture["covered_utilization_pct"], 16.40, 2, "covered_utilization_pct")
    # 82000 is nowhere near 450000, so the depot stays open.
    assert posture["depot_state"] == DEPOT_OPEN, (
        f"utilization of 16.40 % leaves the depot OPEN, got {posture['depot_state']}"
    )
    assert_posture_view_threshold(posture)

    run = fx.refresh_run(api, world["run"]["id"])
    assert run["open_batch_count"] == 0, (
        f"the only batch left the pending state, got {run['open_batch_count']}"
    )
    assert run["status"] == RUN_CLOSED, (
        f"the run auto-closes with its last batch, got {run['status']}"
    )


def test_open_pad_is_refused_for_food_grade_but_allowed_for_highway_deicing(api):
    """
    The same depot's open pad is closed to food grade salt and open to highway
    deicing salt: the food grade batch is refused the moment it declares OPEN_PAD,
    while the highway batch off the very same run is stored outdoors and minted.
    "A batch declaring `OPEN_PAD` for `WATER_CONDITIONING` or `FOOD_GRADE` is refused
    with `ERR_UNCOVERED_STORAGE_NOT_ALLOWED`, and a batch aimed at a `CLOSED` depot
    is refused with `ERR_DEPOT_CLOSED`."

    Design: Corner/validations/open_pad_storage_is_refused_for_food_grade_but_allowed_for_highway_deicing
    """
    world = fx.hoisted_run(
        api,
        mine_kwargs=MINE,
        panel_kwargs=_panel(97.10),
        hoisted_tons=2500,
        planned_tons=2500,
        **WINDOW,
    )
    run_id = world["run"]["id"]
    depot = fx.create_depot(api, **_depot("Syracuse Depot"))

    # The food grade batch would assay 99.600 and would otherwise be perfectly good.
    validate_error(
        api.create_batch(
            f.batch_payload(
                run_id,
                depot["id"],
                product_line=FOOD_GRADE,
                screen_spec=FINE,
                anticaking_ppm=8.00,
                corrosion_inhibitor_pct=0.00,
                input_tons=1000,
                moisture_pct=0.00,
                storage_kind=OPEN_PAD,
            ),
            LAB_TECH,
        ),
        ERR_UNCOVERED_STORAGE_NOT_ALLOWED,
        409,
    )

    highway = validate_success(
        api.create_batch(
            f.batch_payload(
                run_id,
                depot["id"],
                product_line=HIGHWAY_DEICING,
                screen_spec=COARSE,
                anticaking_ppm=20.00,
                corrosion_inhibitor_pct=0.50,
                input_tons=1000,
                moisture_pct=0.00,
                storage_kind=OPEN_PAD,
            ),
            LAB_TECH,
        ),
        201,
    )
    assert highway["storage_kind"] == OPEN_PAD, (
        f"highway deicing salt may sit outdoors, got {highway['storage_kind']}"
    )
    assert_purity(highway["purity_pct_nacl"], 97.600)

    # Only the admitted batch exists on the run.
    rows, meta = validate_paginated(
        api.list_batches(LAB_TECH, {"production_run_id": run_id})
    )
    assert_page_meta(meta, total_count=1)
    assert rows[0]["id"] == highway["id"], (
        "the refused creation must not have written a batch"
    )

    validate_success(
        api.qc_decision(highway["id"], f.qc_decision_payload(DECISION_PASS), LAB_LEAD), 200
    )
    lot = fx.lot_of_batch(api, highway["id"])
    assert lot["storage_kind"] == OPEN_PAD, (
        f"the lot inherits the batch storage kind, got {lot['storage_kind']}"
    )
    assert_lot_tonnage(lot, on_hand=940.00, reserved=0.00, available=940.00)

    posture = fx.storage_posture(api, depot["id"])
    assert_tons(posture["open_pad_stored_tons"], 940.00, "open_pad_stored_tons")
    # Open-pad tonnage never touches the covered figures, so the surge test cannot fire.
    assert_tons(posture["covered_stored_tons"], 0.00, "covered_stored_tons")
    assert_amount(posture["covered_utilization_pct"], 0.00, 2, "covered_utilization_pct")
    assert posture["depot_state"] == DEPOT_OPEN, (
        f"an empty shed leaves the depot OPEN, got {posture['depot_state']}"
    )

    run = fx.refresh_run(api, run_id)
    assert run["status"] == RUN_CLOSED, (
        f"the run auto-closes with its last pending batch, got {run['status']}"
    )


def test_take_band_counts_every_live_order_and_admits_the_one_on_the_limit(api):
    """
    A 5,000-ton contract with a 110 percent ceiling may speak for 5,500 tons. With an
    allocated 2,000-ton order and a shorted 3,000-ton order already on the books, a
    501-ton order breaches the band by a single ton and is refused, while a 500-ton
    order lands exactly on the ceiling and is admitted.
    "The tonnage a contract has already spoken for is the sum of `requested_tons`
    across its delivery orders whose `status` is `REQUESTED`, `ALLOCATED`, `SHORTED`
    or `DELIVERED` — every order that has not been withdrawn, whether or not it was
    ever filled."
    "A new order is refused with `ERR_TAKE_BAND_EXCEEDED` when that consumed figure
    plus the new order's `requested_tons` would exceed `committed_tons` multiplied by
    `max_take_pct` divided by 100, the comparison again being made on the unrounded
    product."

    Design: Corner/validations/take_band_counts_every_live_order_and_admits_the_one_that_lands_on_the_limit
    """
    world = fx.lot_at_depot(
        api,
        mine_kwargs=MINE,
        panel_kwargs=_panel(96.00),
        depot_kwargs=_depot("Syracuse Depot"),
        run_kwargs={"planned_tons": 4500, **WINDOW},
        hoisted_tons=4500,
        product_line=HIGHWAY_DEICING,
        screen_spec=COARSE,
        anticaking_ppm=20.00,
        corrosion_inhibitor_pct=0.50,
        input_tons=4300,
        moisture_pct=0.00,
        storage_kind=COVERED,
    )
    depot_id = world["depot"]["id"]
    # 4300 * 0.94 = 4042.00, which clears the 4,000-ton activation floor.
    assert_tons(world["lot"]["tons_available"], 4042.00, "tons_available")

    contract = fx.active_contract(
        api,
        forecast_kwargs=FORECAST,
        contract_kwargs={
            "customer_name": "City of Syracuse DPW",
            "jurisdiction_level": JURISDICTION_MUNICIPAL,
            "state_code": "NY",
            "product_line": HIGHWAY_DEICING,
            "committed_tons": 5000,
            "guaranteed_price_per_ton": 80.00,
            "min_take_pct": 80,
            "max_take_pct": 110,
            "failure_to_supply_penalty_per_ton": 30.00,
            "price_guarantee_cap_pct": 10,
        },
    )["contract"]
    assert contract["status"] == CONTRACT_ACTIVE, (
        f"expected ACTIVE, got {contract['status']}"
    )

    filled = fx.create_order(
        api,
        contract["id"],
        depot_id,
        requested_tons=2000,
        required_by="2026-12-01T00:00:00Z",
        market_index_price_per_ton=82.00,
    )
    filled = fx.allocate(api, filled["id"])
    assert filled["status"] == ORDER_ALLOCATED, (
        f"2000 tons of 4042 available, expected ALLOCATED, got {filled['status']}"
    )
    starved = fx.create_order(
        api,
        contract["id"],
        depot_id,
        requested_tons=3000,
        required_by="2026-12-01T00:00:00Z",
        market_index_price_per_ton=82.00,
    )
    starved = fx.allocate(api, starved["id"])
    # Only 2042 tons were left, so this order is short but still very much alive.
    assert starved["status"] == ORDER_SHORTED, (
        f"expected SHORTED, got {starved['status']}"
    )
    assert_tons(starved["shorted_tons"], 958.00, "shorted_tons")

    ledger = validate_success(api.get_contract_ledger(contract["id"], CONTRACT_ADMIN), 200)
    # 2000 requested plus 3000 requested, regardless of what was actually filled.
    assert_tons(ledger["take_band_consumed_tons"], 5000.00, "take_band_consumed_tons")
    # 5000 * 110 / 100.
    assert_tons(ledger["take_band_limit_tons"], 5500.00, "take_band_limit_tons")

    before = fx.refresh_contract(api, contract["id"])
    validate_error(
        api.create_order(
            f.order_payload(
                contract["id"],
                depot_id,
                before["version"],
                requested_tons=501,
                required_by="2026-12-01T00:00:00Z",
                market_index_price_per_ton=82.00,
            ),
            LOGISTICS,
        ),
        ERR_TAKE_BAND_EXCEEDED,
        409,
    )
    # A refused creation neither writes an order nor bumps the parent contract.
    after_refusal = fx.refresh_contract(api, contract["id"])
    assert_version_unchanged(after_refusal, before)

    on_the_limit = validate_success(
        api.create_order(
            f.order_payload(
                contract["id"],
                depot_id,
                before["version"],
                requested_tons=500,
                required_by="2026-12-01T00:00:00Z",
                market_index_price_per_ton=82.00,
            ),
            LOGISTICS,
        ),
        201,
    )
    assert on_the_limit["status"] == ORDER_REQUESTED, (
        f"a new order opens at REQUESTED, got {on_the_limit['status']}"
    )
    assert_tons(on_the_limit["requested_tons"], 500.00, "requested_tons")

    final = validate_success(api.get_contract_ledger(contract["id"], CONTRACT_ADMIN), 200)
    # The band is now spent to the ton, and the ceiling was never crossed.
    assert_tons(final["take_band_consumed_tons"], 5500.00, "take_band_consumed_tons")
    assert_tons(final["take_band_limit_tons"], 5500.00, "take_band_limit_tons")

    _, meta = validate_paginated(
        api.list_orders(LOGISTICS, {"bid_contract_id": contract["id"], "limit": 100})
    )
    assert_page_meta(meta, total_count=3)


def test_delivery_order_on_a_closed_depot_is_refused(api):
    """
    A depot shut for the storm cannot be named on a new customer call, even by a
    contract that is perfectly healthy and even though the salt is physically still
    in the shed.
    "`CLOSED` removes every lot at the depot from every future candidate pool for
    every class of order, and blocks batch intake, lot minting, shipments, receipts,
    manual reservations and new delivery orders against it."
    "Creation is refused if the contract is not `ACTIVE` with
    `ERR_CONTRACT_INVALID_STATE`, if the named depot is `CLOSED` with
    `ERR_DEPOT_CLOSED`, and if the take band of §3.8 would be breached with
    `ERR_TAKE_BAND_EXCEEDED`."

    Design: Corner/validations/order_on_a_closed_depot_returns_depot_closed
    """
    world = fx.lot_at_depot(
        api,
        mine_kwargs=MINE,
        panel_kwargs=_panel(96.00),
        depot_kwargs=_depot("Syracuse Depot"),
        run_kwargs={"planned_tons": 1500, **WINDOW},
        hoisted_tons=1500,
        product_line=HIGHWAY_DEICING,
        screen_spec=COARSE,
        anticaking_ppm=20.00,
        corrosion_inhibitor_pct=0.50,
        input_tons=1000,
        moisture_pct=0.00,
        storage_kind=COVERED,
    )
    depot_id = world["depot"]["id"]

    contract = fx.active_contract(
        api,
        forecast_kwargs=FORECAST,
        contract_kwargs={
            "customer_name": "Town of Camillus",
            "jurisdiction_level": JURISDICTION_MUNICIPAL,
            "state_code": "NY",
            "product_line": HIGHWAY_DEICING,
            "committed_tons": 1000,
            "guaranteed_price_per_ton": 80.00,
            "min_take_pct": 80,
            "max_take_pct": 110,
            "failure_to_supply_penalty_per_ton": 30.00,
            "price_guarantee_cap_pct": 10,
        },
    )["contract"]

    closed = fx.set_posture(
        api, depot_id, DEPOT_CLOSED, reason="Roof repair, depot shut to traffic"
    )
    assert closed["depot_state"] == DEPOT_CLOSED, (
        f"expected CLOSED, got {closed['depot_state']}"
    )

    before = fx.refresh_contract(api, contract["id"])
    validate_error(
        api.create_order(
            f.order_payload(
                contract["id"],
                depot_id,
                before["version"],
                requested_tons=300,
                required_by="2026-12-01T00:00:00Z",
                market_index_price_per_ton=82.00,
            ),
            LOGISTICS,
        ),
        ERR_DEPOT_CLOSED,
        409,
    )

    # Order creation normally bumps the parent contract, so the refusal must not.
    after = fx.refresh_contract(api, contract["id"])
    assert_version_unchanged(after, before)
    assert after["status"] == CONTRACT_ACTIVE, (
        f"the contract itself is untouched, got {after['status']}"
    )
    _, meta = validate_paginated(
        api.list_orders(LOGISTICS, {"bid_contract_id": contract["id"]})
    )
    assert_page_meta(meta, total_count=0)

    # Closing the depot moved no tonnage: the salt is simply unreachable.
    assert_lot_tonnage(
        fx.refresh_lot(api, world["lot"]["id"]),
        on_hand=940.00,
        reserved=0.00,
        available=940.00,
    )


def test_activation_one_second_after_the_preseason_lock_is_refused(api):
    """
    Two awarded contracts against one forecast whose pre-season lock falls at
    2026-10-15T00:00:00Z. Activated exactly on the lock instant the first is admitted,
    because the clock is at the lock rather than past it; activated one second later
    the second is refused on the window even though it is also short of coverage.
    "First, the pre-season window must still be open: the logical clock must be at or
    before the forecast's `preseason_lock_date`, else `ERR_PRESEASON_WINDOW_CLOSED`."

    Design: Corner/validations/activation_one_second_after_the_preseason_lock_is_refused
    """
    world = fx.lot_at_depot(
        api,
        mine_kwargs=MINE,
        panel_kwargs=_panel(96.00),
        depot_kwargs=_depot("Syracuse Depot"),
        run_kwargs={"planned_tons": 1500, **WINDOW},
        hoisted_tons=1500,
        product_line=HIGHWAY_DEICING,
        screen_spec=COARSE,
        anticaking_ppm=20.00,
        corrosion_inhibitor_pct=0.50,
        input_tons=1000,
        moisture_pct=0.00,
        storage_kind=COVERED,
    )
    assert_tons(world["lot"]["tons_available"], 940.00, "tons_available")

    forecast = fx.create_forecast(api, **FORECAST)
    # 50 is the lowest minimum take the PRD admits, so coverage of 940 tons carries a
    # 1,000-ton commitment (500 required) but not a 3,000-ton one (1,500 required).
    common = {
        "jurisdiction_level": JURISDICTION_MUNICIPAL,
        "state_code": "NY",
        "product_line": HIGHWAY_DEICING,
        "guaranteed_price_per_ton": 80.00,
        "min_take_pct": 50,
        "max_take_pct": 110,
        "failure_to_supply_penalty_per_ton": 30.00,
        "price_guarantee_cap_pct": 10,
    }
    in_time = fx.create_contract(
        api,
        forecast["id"],
        customer_name="Village of Solvay",
        committed_tons=1000,
        **common,
    )
    too_late = fx.create_contract(
        api,
        forecast["id"],
        customer_name="Village of Marcellus",
        committed_tons=3000,
        **common,
    )
    for contract in (in_time, too_late):
        fx.submit_contract(api, contract["id"])
        awarded = fx.decide_contract(api, contract["id"])
        assert awarded["status"] == CONTRACT_AWARDED, (
            f"expected AWARDED, got {awarded['status']}"
        )

    fx.set_clock(api, "2026-10-15T00:00:00Z")
    activated = validate_success(
        api.activate_contract(in_time["id"], CONTRACT_ADMIN), 200
    )
    assert activated["status"] == CONTRACT_ACTIVE, (
        f"the lock instant itself is still inside the window, got {activated['status']}"
    )
    assert activated["supply_reliability_score"] == 100, (
        f"activation initialises the score to 100, got "
        f"{activated['supply_reliability_score']}"
    )
    assert activated["breach_watch"] is False, (
        f"activation initialises breach_watch to false, got {activated['breach_watch']}"
    )

    fx.set_clock(api, "2026-10-15T00:00:01Z")
    before = fx.refresh_contract(api, too_late["id"])
    validate_error(
        api.activate_contract(too_late["id"], CONTRACT_ADMIN),
        ERR_PRESEASON_WINDOW_CLOSED,
        409,
    )

    after = fx.refresh_contract(api, too_late["id"])
    assert after["status"] == CONTRACT_AWARDED, (
        f"a refused activation leaves the contract AWARDED, got {after['status']}"
    )
    assert_version_unchanged(after, before)


def test_rework_shrinks_the_batch_until_it_finally_fits_the_covered_pad(api):
    """
    A 940-ton yield will not fit a 900-ton shed, so the pass is refused; one rework
    shrinks it to 911.80 and it still will not fit; a second rework brings it to
    884.45, which fits and is minted — and the arrival takes the shed past 90 percent
    utilization, so the depot moves itself into storm posture.
    "And the tonnage must fit: for a `COVERED` batch, the depot's
    `covered_stored_tons` plus the batch's `yield_tons` must not exceed its
    `covered_capacity_tons`; for an `OPEN_PAD` batch, `open_pad_stored_tons` plus
    `yield_tons` must not exceed `open_pad_capacity_tons`."
    "Each accepted rework increases `rework_count` by 1 and recomputes `yield_tons`
    with the loss factor of 0.97 raised to the new `rework_count` — so a
    once-reworked batch keeps 97 percent of its original yield and a twice-reworked
    batch 94.09 percent of it, since the exponent grows with each loop."
    "Whenever tonnage lands at a depot — a quality-control pass minting a lot, or a
    shipment being received — the server tests the depot's `covered_stored_tons`
    multiplied by 100 against its `covered_capacity_tons` multiplied by 90, and a
    depot that is `OPEN` moves `OPEN → SURGE` when that product reaches or exceeds
    the threshold."

    Design: Corner/validations/rework_shrinks_the_batch_until_it_finally_fits_the_covered_pad
    """
    world = fx.hoisted_run(
        api,
        mine_kwargs=MINE,
        panel_kwargs=_panel(96.00),
        hoisted_tons=1500,
        planned_tons=1500,
        **WINDOW,
    )
    depot = fx.create_depot(api, **_depot("Syracuse Depot", covered=900))

    batch = validate_success(
        api.create_batch(
            f.batch_payload(
                world["run"]["id"],
                depot["id"],
                product_line=HIGHWAY_DEICING,
                screen_spec=COARSE,
                anticaking_ppm=20.00,
                corrosion_inhibitor_pct=0.50,
                input_tons=1000,
                moisture_pct=0.00,
                storage_kind=COVERED,
            ),
            LAB_TECH,
        ),
        201,
    )
    assert_tons(batch["yield_tons"], 940.00, "yield_tons")

    # 0 stored plus 940.00 exceeds the 900-ton shed.
    validate_error(
        api.qc_decision(batch["id"], f.qc_decision_payload(DECISION_PASS), LAB_LEAD),
        ERR_COVERED_CAPACITY_EXCEEDED,
        409,
    )

    once = validate_success(
        api.qc_decision(batch["id"], f.qc_decision_payload(DECISION_REWORK), LAB_LEAD), 200
    )
    assert once["rework_count"] == 1, f"expected rework_count 1, got {once['rework_count']}"
    # 1000 * 0.94 * 0.97.
    assert_tons(once["yield_tons"], 911.80, "yield_tons")
    assert once["qc_state"] == QC_PENDING, (
        f"rework is the PENDING self-loop, got {once['qc_state']}"
    )
    # Still 11.80 tons too much for the shed.
    validate_error(
        api.qc_decision(batch["id"], f.qc_decision_payload(DECISION_PASS), LAB_LEAD),
        ERR_COVERED_CAPACITY_EXCEEDED,
        409,
    )

    twice = validate_success(
        api.qc_decision(batch["id"], f.qc_decision_payload(DECISION_REWORK), LAB_LEAD), 200
    )
    assert twice["rework_count"] == 2, (
        f"expected rework_count 2, got {twice['rework_count']}"
    )
    # 1000 * 0.94 * 0.9409 = 884.446, which rounds half up to 884.45.
    assert_tons(twice["yield_tons"], 884.45, "yield_tons")
    # Purity is frozen at creation and survives both reworks untouched.
    assert_purity(twice["purity_pct_nacl"], 96.500)

    passed = validate_success(
        api.qc_decision(batch["id"], f.qc_decision_payload(DECISION_PASS), LAB_LEAD), 200
    )
    assert passed["qc_state"] == QC_PASSED, (
        f"884.45 tons fit the 900-ton shed, got {passed['qc_state']}"
    )

    lot = fx.lot_of_batch(api, batch["id"])
    assert_lot_tonnage(lot, on_hand=884.45, reserved=0.00, available=884.45)
    assert_purity(lot["purity_pct_nacl"], 96.500)

    posture = fx.storage_posture(api, depot["id"])
    assert_tons(posture["covered_stored_tons"], 884.45, "covered_stored_tons")
    # 884.45 * 100 / 900 = 98.2722..., published at two decimals.
    assert_amount(posture["covered_utilization_pct"], 98.27, 2, "covered_utilization_pct")
    # 88445.00 is past 81000.00, so the depot moved itself.
    assert posture["depot_state"] == DEPOT_SURGE, (
        f"the arrival should have tripped the surge threshold, got {posture['depot_state']}"
    )
    assert_posture_view_threshold(posture)
    surged = fx.refresh_depot(api, depot["id"])
    assert surged["storm_state_set_by_user_id"] is None, (
        "an automatic posture move must not stamp storm_state_set_by_user_id"
    )

    run = fx.refresh_run(api, world["run"]["id"])
    assert run["open_batch_count"] == 0, (
        f"the batch finally left the pending state, got {run['open_batch_count']}"
    )
    assert run["status"] == RUN_CLOSED, (
        f"the run auto-closes with its last batch, got {run['status']}"
    )
