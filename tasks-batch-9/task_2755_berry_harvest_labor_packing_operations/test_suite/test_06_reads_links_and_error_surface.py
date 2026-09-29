"""
The endpoint surface itself: the computed traceability read over an empty child
set, the two-sided join that creates an allocation line, the logical clock as a
first-class action endpoint, the reverse-navigation filters of the fruit-lot
list, the eleven distinct path-existence errors, the single authentication
identifier behind three different header failures, and the immediate visibility
of every derived figure.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers import test_users as u


def _sampled_block_with_window(api, name: str):
    """A CLEARED block, a recruiting crew and a PLANNED window over 2026-08-03."""
    block = x.register_block(
        api,
        name=name,
        variety="STRAWBERRY",
        acres=8.00,
        planting_year=2021,
        irrigation_source_code="WELL-" + name,
    )
    x.record_water_sample(
        api, block["id"], sample_date="2026-07-20", generic_ecoli_mpn=40
    )
    crew = x.recruit_crew(api, name="CREW-" + name)
    window = x.plan_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T14:00:00Z",
        forecast_brix=8.5,
        planned_volume_lbs=150.00,
        piece_rate_cents_per_clamshell=45,
        clamshell_net_weight_lbs=1.00,
    )
    return block, crew, window


def test_the_traceability_roll_up_of_a_never_picked_block_is_zeros_not_a_404(api):
    """
    The roll-up is a computed read over a possibly empty child set, so a block
    that has never been picked answers 200 with every count at zero and no pick
    dates at all.

    PRD 3.1: "A block with no lots at all returns zeros for every count and no value for either date — it is never a 404."

    PRD 3.1: "It reports the block's identifier as `block_id`, its `name` as `block_name`, its `variety`, its current `water_status` and `food_safety_posture`, the number of lots as `lot_count`, the number of distinct pick dates as `pick_date_count`, the sum of `net_packed_lbs` across all those lots as `total_packed_lbs` rounded half up to two decimals, the sum of `net_packed_lbs` across only the lots whose `disposition_status` is `DELIVERED` as `shipped_lbs` on the same rounding, the count of lots carrying `food_safety_hold` as `held_lot_count`, the count of lots whose `disposition_status` is `REJECTED` as `rejected_lot_count`, and the first and last pick dates in the ordering as `earliest_pick_date` and `latest_pick_date`."

    Design: Corner/endpoints/block_traceability_summary_on_an_empty_block_returns_zeros_not_404
    """
    block = x.register_block(
        api,
        name="BLK-V20",
        variety="STRAWBERRY",
        acres=4.00,
        planting_year=2022,
        irrigation_source_code="WELL-V20",
    )

    response = api.get_traceability_summary(block["id"], u.FOOD_SAFETY_OFFICER)
    summary = validate_success(response, 200)
    a.assert_object_response(response)

    assert summary["block_id"] == block["id"]
    assert summary["block_name"] == "BLK-V20"
    a.assert_status(summary, "variety", "STRAWBERRY")
    assert summary["lot_count"] == 0
    assert summary["pick_date_count"] == 0
    a.assert_pounds(summary["total_packed_lbs"], 0.00, "summary.total_packed_lbs")
    a.assert_pounds(summary["shipped_lbs"], 0.00, "summary.shipped_lbs")
    assert summary["held_lot_count"] == 0
    assert summary["rejected_lot_count"] == 0
    a.assert_unset(summary, "earliest_pick_date", "summary")
    a.assert_unset(summary, "latest_pick_date", "summary")
    a.assert_status(summary, "water_status", "NO_SAMPLES")
    a.assert_status(summary, "food_safety_posture", "RESTRICTED")


def test_an_allocation_needs_both_of_its_parents_and_each_reports_its_own_404(api):
    """
    The allocation endpoint joins a lot to a buyer program, and each side owns a
    distinct 404; neither refusal spends the commitment's version token, so the
    same guard value still carries the well-formed third attempt.

    PRD 2.7 rule 19: "On allocation creation, a body `fruit_lot_id` resolves to a `FruitLot` (`ERR_LOT_NOT_FOUND`) and a body `buyer_commitment_id` resolves to a `BuyerCommitment` (`ERR_COMMITMENT_NOT_FOUND`)."

    PRD 2.7: "**Rules are evaluated in ascending priority, the first violated rule determines the response, and no side effect of the request is applied once a rule has fired.**"

    PRD 3.7: "An accepted allocation is created in status `RESERVED`, moves the lot's `disposition_status` to `RESERVED` if it was `UNCOMMITTED`, recomputes the lot's `allocated_lbs` and `available_lbs`, recomputes the commitment's `committed_lbs`, `open_lbs`, `fill_pct`, coverage and `risk_flag`, and increments the `version` of the lot and the commitment by 1."

    Design: Corner/endpoints/lot_allocation_link_requires_both_lot_and_commitment_to_exist
    """
    block, _, window = _sampled_block_with_window(api, "BLK-V21")
    lot = x.pack_lot(
        api,
        window["id"],
        block["id"],
        variety="STRAWBERRY",
        grade="A",
        clamshell_count=50,
        clamshell_net_weight_lbs=1.00,
        pick_date="2026-08-03",
        pack_completed_at="2026-08-03T12:00:00Z",
        field_pulp_temp_f=62.0,
    )
    commitment = x.open_commitment(
        api,
        buyer_name="PROGRAM-V21",
        variety="STRAWBERRY",
        volume_commitment_lbs=200.00,
        price_cents_per_lb=400,
        window_start_date="2026-08-01",
        window_end_date="2026-08-10",
    )
    guard = commitment["version"]

    validate_error(
        api.create_lot_allocation(
            f.lot_allocation_payload(
                NON_EXISTENT_UUID, commitment["id"], 20.00, guard
            ),
            u.SALES_MANAGER,
        ),
        e.ERR_LOT_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_lot_allocation(
            f.lot_allocation_payload(lot["id"], NON_EXISTENT_UUID, 20.00, guard),
            u.SALES_MANAGER,
        ),
        e.ERR_COMMITMENT_NOT_FOUND,
        404,
    )

    line = validate_success(
        api.create_lot_allocation(
            f.lot_allocation_payload(lot["id"], commitment["id"], 20.00, guard),
            u.SALES_MANAGER,
        ),
        201,
    )
    a.assert_status(line, "status", "RESERVED")
    a.assert_pounds(line["allocated_lbs"], 20.00, "allocation.allocated_lbs")

    by_lot, lot_meta = x.list_allocations(api, fruit_lot_id=lot["id"])
    a.assert_page_meta(lot_meta, expected_total=1)
    assert a.ids_of(by_lot) == [line["id"]]

    by_commitment, commitment_meta = x.list_allocations(
        api, buyer_commitment_id=commitment["id"]
    )
    a.assert_page_meta(commitment_meta, expected_total=1)
    assert a.ids_of(by_commitment) == [line["id"]]

    stored_lot = x.read_lot(api, lot["id"])
    a.assert_pounds(stored_lot["allocated_lbs"], 20.00, "lot.allocated_lbs")
    a.assert_pounds(stored_lot["available_lbs"], 30.00, "lot.available_lbs")
    a.assert_status(stored_lot, "disposition_status", "RESERVED")

    stored_commitment = x.read_commitment(api, commitment["id"])
    a.assert_pounds(
        stored_commitment["committed_lbs"], 20.00, "commitment.committed_lbs"
    )
    a.assert_pounds(stored_commitment["open_lbs"], 180.00, "commitment.open_lbs")
    assert stored_commitment["version"] == 2


def test_the_clock_shuts_the_opening_gate_at_the_windows_end_instant(api):
    """
    The logical clock is an action endpoint every temporal rule reads: pushed one
    hour past a window's `end_at`, it turns a fully staffed and cleared
    `CONFIRMED` window into a refusal, and the crew is never promoted.

    PRD 2.7 rule 58: "The logical clock instant is strictly before the window's `end_at` when the window is opened or resumed; `cool_start_at` is not earlier than `pack_completed_at`; `cool_complete_at` is strictly after `cool_start_at`; and a buyer commitment settles only after its `window_end_date` has passed. All four failures report `ERR_TEMPORAL_ORDER_VIOLATION`."

    PRD 3.3: "And the current logical clock instant must be strictly before the window's `end_at`, otherwise `ERR_TEMPORAL_ORDER_VIOLATION` — a window whose end has already passed cannot be opened retroactively."

    PRD 3.3: "Opening increments the window's `version` by 1 and, when the crew was still `CERTIFIED`, advances it to `ACTIVE` and increments the crew's `version` by 1 as well."

    Design: Corner/endpoints/clock_endpoint_closes_the_window_open_gate_at_its_end_instant
    """
    block = x.register_block(
        api,
        name="BLK-V22",
        variety="STRAWBERRY",
        acres=8.00,
        planting_year=2021,
        irrigation_source_code="WELL-V22",
    )
    x.record_water_sample(
        api, block["id"], sample_date="2026-07-20", generic_ecoli_mpn=40
    )
    crew, _ = x.certified_crew(api, picker_count=1, name="CREW-V22")
    window = x.confirmed_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T14:00:00Z",
        forecast_brix=8.5,
        planned_volume_lbs=150.00,
        piece_rate_cents_per_clamshell=45,
        clamshell_net_weight_lbs=1.00,
    )
    x.set_clock(api, "2026-08-03T15:00:00Z")

    validate_error(
        api.open_harvest_window(window["id"], u.HARVEST_MANAGER),
        e.ERR_TEMPORAL_ORDER_VIOLATION,
        422,
    )

    stored_window = x.read_window(api, window["id"])
    a.assert_status(stored_window, "status", "CONFIRMED")
    assert stored_window["required_picker_count"] == 1

    stored_crew = x.read_crew(api, crew["id"])
    a.assert_status(stored_crew, "status", "CERTIFIED")
    assert stored_crew["picker_count"] == 1

    a.assert_status(
        x.read_block(api, block["id"]), "food_safety_posture", "CLEARED"
    )


def test_the_lot_list_walks_back_from_window_block_tunnel_and_repack_parent(api):
    """
    A repack child is reachable only through the list read, and each declared
    filter narrows the same three lots to a different subset: lineage by parent,
    occupancy by tunnel, and each state dimension on its own axis.

    PRD 2.11: "Fruit lots may be filtered by `harvest_window_id`, by `block_id`, by `source_lot_id` (which is how repack lineage is walked), by `cooling_tunnel_id`, by `cold_chain_status` or by `disposition_status`."

    PRD 3.6: "A repack **returns the newly created child lot**, not the source, with status 201."

    Design: Corner/endpoints/fruit_lot_list_filters_reverse_navigate_window_block_tunnel_and_repack_lineage
    """
    block, _, window = _sampled_block_with_window(api, "BLK-V23")
    tunnel = x.register_tunnel(api, name="TUN-V23", slot_capacity=2)

    parent = x.cooled_lot(
        api,
        window["id"],
        block["id"],
        tunnel["id"],
        cool_start_at="2026-08-03T13:00:00Z",
        planned_cool_end_at="2026-08-03T17:00:00Z",
        cool_complete_at="2026-08-03T17:00:00Z",
        entry_pulp_temp_f=60.0,
        exit_pulp_temp_f=34.0,
        variety="STRAWBERRY",
        grade="A",
        clamshell_count=50,
        clamshell_net_weight_lbs=1.00,
        pick_date="2026-08-03",
        pack_completed_at="2026-08-03T12:00:00Z",
        field_pulp_temp_f=62.0,
    )
    child = x.repack_lot(api, parent["id"], 30, 10, 10, output_grade="B")
    never_cooled = x.pack_lot(
        api,
        window["id"],
        block["id"],
        variety="STRAWBERRY",
        grade="A",
        clamshell_count=20,
        clamshell_net_weight_lbs=1.00,
        pick_date="2026-08-03",
        pack_completed_at="2026-08-03T12:30:00Z",
        field_pulp_temp_f=63.0,
    )

    everything, meta = x.list_lots(api)
    a.assert_page_meta(
        meta,
        expected_total=3,
        expected_limit=10,
        expected_offset=0,
        expected_has_more=False,
    )
    assert set(a.ids_of(everything)) == {parent["id"], child["id"], never_cooled["id"]}

    _, by_window = x.list_lots(api, harvest_window_id=window["id"])
    a.assert_page_meta(by_window, expected_total=3)
    _, by_block = x.list_lots(api, block_id=block["id"])
    a.assert_page_meta(by_block, expected_total=3)

    lineage, lineage_meta = x.list_lots(api, source_lot_id=parent["id"])
    a.assert_page_meta(lineage_meta, expected_total=1)
    assert a.ids_of(lineage) == [child["id"]]

    in_tunnel, tunnel_meta = x.list_lots(api, cooling_tunnel_id=tunnel["id"])
    a.assert_page_meta(tunnel_meta, expected_total=2)
    assert set(a.ids_of(in_tunnel)) == {parent["id"], child["id"]}

    cooled, cooled_meta = x.list_lots(api, cold_chain_status="COOLED")
    a.assert_page_meta(cooled_meta, expected_total=2)
    assert set(a.ids_of(cooled)) == {parent["id"], child["id"]}

    uncommitted, uncommitted_meta = x.list_lots(api, disposition_status="UNCOMMITTED")
    a.assert_page_meta(uncommitted_meta, expected_total=2)
    assert set(a.ids_of(uncommitted)) == {child["id"], never_cooled["id"]}

    stored_child = x.read_lot(api, child["id"])
    assert stored_child["source_lot_id"] == parent["id"]
    assert stored_child["harvest_window_id"] == window["id"]
    assert stored_child["cooling_tunnel_id"] == tunnel["id"]
    a.assert_pounds(stored_child["net_packed_lbs"], 30.00, "child.net_packed_lbs")

    stored_parent = x.read_lot(api, parent["id"])
    a.assert_status(stored_parent, "disposition_status", "REPACKED")
    a.assert_status(stored_parent, "cold_chain_status", "COOLED")
    a.assert_pounds(stored_parent["available_lbs"], 0.00, "parent.available_lbs")


def test_every_collection_can_be_made_to_report_its_own_path_404(api):
    """
    All eleven single-resource reads are reachable with an unknown identifier,
    and each answers with the not-found identifier that belongs to its own
    family rather than a shared generic one.

    PRD 2.7 rules 5-9: "**Path existence (5–9), left to right.** (5) `block_id` in the path resolves to a `Block`, otherwise `ERR_BLOCK_NOT_FOUND`. (6) `crew_id` resolves to a `Crew` (`ERR_CREW_NOT_FOUND`) and `picker_id` resolves to a `Picker` (`ERR_PICKER_NOT_FOUND`). (7) `harvest_window_id` resolves to a `HarvestWindow` (`ERR_WINDOW_NOT_FOUND`), `pick_session_id` to a `PickSession` (`ERR_SESSION_NOT_FOUND`), and `payroll_run_id` to a `PayrollRun` (`ERR_PAYROLL_RUN_NOT_FOUND`). (8) `fruit_lot_id` resolves to a `FruitLot` (`ERR_LOT_NOT_FOUND`) and `cooling_tunnel_id` to a `CoolingTunnel` (`ERR_TUNNEL_NOT_FOUND`). (9) `buyer_commitment_id` resolves to a `BuyerCommitment` (`ERR_COMMITMENT_NOT_FOUND`) and `lot_allocation_id` to a `LotAllocation` (`ERR_ALLOCATION_NOT_FOUND`)."

    PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."

    Design: Corner/errors/path_existence_errors_are_triggerable_for_every_collection
    """
    reads = [
        (api.get_block(NON_EXISTENT_UUID, u.HARVEST_MANAGER), e.ERR_BLOCK_NOT_FOUND),
        (api.get_crew(NON_EXISTENT_UUID, u.HARVEST_MANAGER), e.ERR_CREW_NOT_FOUND),
        (api.get_picker(NON_EXISTENT_UUID, u.CREW_SUPERVISOR), e.ERR_PICKER_NOT_FOUND),
        (
            api.get_harvest_window(NON_EXISTENT_UUID, u.HARVEST_MANAGER),
            e.ERR_WINDOW_NOT_FOUND,
        ),
        (
            api.get_pick_session(NON_EXISTENT_UUID, u.CREW_SUPERVISOR),
            e.ERR_SESSION_NOT_FOUND,
        ),
        (
            api.get_payroll_run(NON_EXISTENT_UUID, u.PAYROLL_CLERK),
            e.ERR_PAYROLL_RUN_NOT_FOUND,
        ),
        (
            api.get_fruit_lot(NON_EXISTENT_UUID, u.PACKHOUSE_OPERATOR),
            e.ERR_LOT_NOT_FOUND,
        ),
        (
            api.get_cooling_tunnel(NON_EXISTENT_UUID, u.PACKHOUSE_OPERATOR),
            e.ERR_TUNNEL_NOT_FOUND,
        ),
        (
            api.get_buyer_commitment(NON_EXISTENT_UUID, u.SALES_MANAGER),
            e.ERR_COMMITMENT_NOT_FOUND,
        ),
        (
            api.get_lot_allocation(NON_EXISTENT_UUID, u.SALES_MANAGER),
            e.ERR_ALLOCATION_NOT_FOUND,
        ),
        (
            api.get_water_test(NON_EXISTENT_UUID, u.FOOD_SAFETY_OFFICER),
            e.ERR_WATER_TEST_NOT_FOUND,
        ),
    ]

    seen = []
    for response, expected in reads:
        error = validate_error(response, expected, 404)
        assert error["message"].strip() != ""
        assert response.json()["response_type"] == "error"
        seen.append(error["error_id"])

    assert len(seen) == 11
    a.assert_all_distinct(seen, "path not-found identifiers")


def test_three_different_header_faults_all_land_on_one_authentication_error(api):
    """
    An absent role header, an undeclared role name and an empty operator
    identifier are one refusal, not three: the check runs ahead of the role
    matrix, so no attempt is ever reported as a role failure and no write lands.

    PRD 2.1: "Every request to the API must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which they act. If either header is absent or empty, or if `X-User-Role` carries a string that is not one of the seven declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). This check runs before anything else — before the role is matched against the endpoint, before any path identifier is resolved, and before any body field is inspected."

    PRD 2.7 rules 1-2: "**Authentication (1–2).** (1) `X-User-ID` and `X-User-Role` are both present and non-empty. (2) `X-User-Role` is one of the seven declared role names. Both failures report `ERR_UNAUTHENTICATED`, on every endpoint."

    Design: Corner/errors/missing_or_undeclared_auth_headers_returns_unauthenticated
    """
    role_omitted = api.list_blocks({"X-User-ID": u.HM_1})
    validate_error(role_omitted, e.ERR_UNAUTHENTICATED, 401)

    undeclared_role = api.list_blocks(
        {"X-User-ID": u.HM_1, "X-User-Role": "FieldBoss"}
    )
    validate_error(undeclared_role, e.ERR_UNAUTHENTICATED, 401)

    empty_identity = api.create_block(
        f.block_payload(
            name="BLK-V24",
            variety="STRAWBERRY",
            acres=6.00,
            planting_year=2022,
            irrigation_source_code="WELL-V24",
        ),
        {"X-User-ID": "", "X-User-Role": "HarvestManager"},
    )
    validate_error(empty_identity, e.ERR_UNAUTHENTICATED, 401)

    for response in (role_omitted, undeclared_role, empty_identity):
        assert response.status_code == 401
        assert response.json()["data"]["error_id"] != e.ERR_FORBIDDEN_ROLE

    _, meta = validate_paginated(api.list_blocks(u.HARVEST_MANAGER))
    a.assert_page_meta(meta, expected_total=0)


def test_a_write_returns_the_figures_it_derived_without_waiting_for_a_reread(api):
    """
    Every derived figure is settled inside the accepted write: the water sample
    reports the status it produced, and the allocation's own response already
    carries the pounds that the lot and the commitment will read back.

    PRD 3.1: "It also stores two derived facts about itself: `single_sample_exceedance`, true exactly when this sample's `generic_ecoli_mpn` is strictly greater than the single-sample maximum of 410 MPN per 100 mL, and `resulting_water_status`, a snapshot of the parent block's `water_status` as it stood immediately after this sample was folded in."

    PRD 3.1: "A block's `food_safety_posture` is recomputed at the end of every call that stores a water sample for it or toggles its manual hold, and it is never accepted as an input."

    PRD 3.7: "The exposure figures are always recomputed from the surviving allocation rows rather than nudged: `committed_lbs` is the sum of `allocated_lbs` over the commitment's `RESERVED` and `SHIPPED` lines, `shipped_lbs` the sum over the `SHIPPED` lines alone, and `open_lbs` is `volume_commitment_lbs` less `committed_lbs`, floored at 0.00 and carried to two decimals."

    Design: Corner/consistency_model/derived_pounds_and_postures_are_visible_in_the_same_response
    """
    block = x.register_block(
        api,
        name="BLK-V36",
        variety="STRAWBERRY",
        acres=8.00,
        planting_year=2021,
        irrigation_source_code="WELL-V36",
    )
    crew = x.recruit_crew(api, name="CREW-V36")
    window = x.plan_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T14:00:00Z",
        forecast_brix=8.5,
        planned_volume_lbs=150.00,
        piece_rate_cents_per_clamshell=45,
        clamshell_net_weight_lbs=1.00,
    )
    lot = x.pack_lot(
        api,
        window["id"],
        block["id"],
        variety="STRAWBERRY",
        grade="A",
        clamshell_count=100,
        clamshell_net_weight_lbs=1.00,
        pick_date="2026-08-03",
        pack_completed_at="2026-08-03T12:00:00Z",
        field_pulp_temp_f=62.0,
    )
    commitment = x.open_commitment(
        api,
        buyer_name="PROGRAM-V36",
        variety="STRAWBERRY",
        volume_commitment_lbs=200.00,
        price_cents_per_lb=400,
        window_start_date="2026-08-01",
        window_end_date="2026-08-10",
    )
    guard = commitment["version"]

    sample = validate_success(
        api.create_water_test(
            f.water_test_payload(
                block["id"], sample_date="2026-07-20", generic_ecoli_mpn=40
            ),
            u.FOOD_SAFETY_OFFICER,
        ),
        201,
    )
    a.assert_status(sample, "resulting_water_status", "PROVISIONAL")
    assert sample["single_sample_exceedance"] is False

    sampled_block = x.read_block(api, block["id"])
    assert sampled_block["water_sample_count"] == 1
    a.assert_geomean(sampled_block["water_geomean_mpn"], 40.0)
    a.assert_status(sampled_block, "water_status", "PROVISIONAL")
    a.assert_status(sampled_block, "food_safety_posture", "CLEARED")
    assert sampled_block["last_sample_date"] == "2026-07-20"

    line = validate_success(
        api.create_lot_allocation(
            f.lot_allocation_payload(lot["id"], commitment["id"], 40.00, guard),
            u.SALES_MANAGER,
        ),
        201,
    )
    a.assert_status(line, "status", "RESERVED")
    a.assert_pounds(line["allocated_lbs"], 40.00, "allocation.allocated_lbs")

    stored_lot = x.read_lot(api, lot["id"])
    a.assert_pounds(stored_lot["allocated_lbs"], 40.00, "lot.allocated_lbs")
    a.assert_pounds(stored_lot["available_lbs"], 60.00, "lot.available_lbs")
    a.assert_status(stored_lot, "disposition_status", "RESERVED")

    stored_commitment = x.read_commitment(api, commitment["id"])
    a.assert_pounds(
        stored_commitment["committed_lbs"], 40.00, "commitment.committed_lbs"
    )
    a.assert_pounds(stored_commitment["open_lbs"], 160.00, "commitment.open_lbs")
    assert stored_commitment["version"] == 2
