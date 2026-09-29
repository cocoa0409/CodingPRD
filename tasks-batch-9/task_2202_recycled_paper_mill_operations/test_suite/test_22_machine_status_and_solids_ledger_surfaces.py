"""Round trips across the read and write surfaces: the machine's guarded status patch,
the solids summary over two producers, the hauler manifest, and the reversal row.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    NON_EXISTENT_UUID, TEST_USERS, declare_tl_140, register_machine, register_permit,
    setup_available_lot, setup_approved_batch, schedule_run,
    start_run, complete_run, machine_version, sublot, reel_reading,
    prepare_manifest, solids_rows, solids_summary, set_clock,
    setup_wrapped_set_on_certified_run, allocate_roll_set,
)

PLANNER = TEST_USERS["planner_headers"]
OPERATOR = TEST_USERS["operator_headers"]
ENV = TEST_USERS["env_officer_headers"]
ENV_PREPARER = TEST_USERS["env_preparer_headers"]
ENV_SIGNER = TEST_USERS["env_signer_headers"]

PM1 = {"name": "PM1", "wire_width_mm": 5600, "max_tons_per_hour": 20.00,
       "changeover_buffer_minutes": 30, "steam_tph_per_ton": 2.500}
MILL_PERMIT = {"permit_number": "MILL-NPDES-1", "bod_limit_kg_per_day": 500.00,
               "tss_limit_kg_per_day": 400.00, "flow_limit_m3_per_day": 9000.00,
               "rolling_window_days": 30}
TWENTY_TWO_TON_SUBLOT = [sublot(1, 30.000, 8.000, 10.00, 2.00)]
TWO_FIVE_TON_REELS = [reel_reading(1, 5.000, 140.0, 7.50, 2.60),
                      reel_reading(2, 5.000, 140.0, 7.50, 2.60)]


def _approved_twenty_ton_batch():
    declare_tl_140(moisture_tolerance_pct=0.50, min_sct_kn_m=2.50, rank_order=10)
    return setup_approved_batch(
        tons_charged=20.000, measured_reject_tons=2.000, declare_spec=False,
        lot_bundle=setup_available_lot(sublots_list=TWENTY_TWO_TON_SUBLOT))


def _scheduled_run_on_pm1():
    register_permit(**MILL_PERMIT)
    machine = register_machine(**PM1)
    bundle = _approved_twenty_ton_batch()
    run = schedule_run(machine["id"], "TL_140", bundle["batch"]["id"],
                       pulp_draw_tons=15.000)
    return machine, bundle["batch"], run


def _run_completed_with_broke(broke_tons):
    machine, batch, run = _scheduled_run_on_pm1()
    start_run(machine["id"], run["id"])
    complete_run(machine["id"], run["id"], TWO_FIVE_TON_REELS, broke_tons)
    return machine, batch, run


def test_taking_the_machine_down_needs_the_version_just_read_and_keeps_the_nameplate():
    """PRD §3.4: "A newly registered machine opens with `status` of `RUNNABLE`, `version`
    of 1, and `current_product_code` null."
    PRD §3.4: "The planner may take a machine out of service or return it, setting `status`
    to `DOWN` or `RUNNABLE`; a `DOWN` machine blocks both new run scheduling and run
    starting."
    PRD §2.4: "Most resources additionally carry `updated_at` — same ISO 8601 UTC format
    with three fractional digits, refreshed on every mutation of that row — and `version`,
    an integer that starts at 1 on creation and increments by exactly one on every
    mutation."

    Design: Corner/endpoints/machine_create_read_and_status_patch_round_trip_with_version_bump
    """
    set_clock("2026-08-01T00:00:00Z")
    machine = register_machine(**PM1)
    read_back = get_success_data(api_client.get_paper_machine(machine["id"], PLANNER))
    assert read_back["status"] == "RUNNABLE"
    assert read_back["version"] == 1

    downed = validate_success(api_client.patch_paper_machine_status(
        machine["id"], {"status": "DOWN",
                        "expected_machine_version": read_back["version"]}, PLANNER))

    assert downed["status"] == "DOWN"
    assert downed["version"] == read_back["version"] + 1
    assert downed["name"] == "PM1"
    assert downed["wire_width_mm"] == 5600
    assert downed["max_tons_per_hour"] == pytest.approx(20.00, abs=1e-6)
    assert downed["changeover_buffer_minutes"] == 30
    assert downed["steam_tph_per_ton"] == pytest.approx(2.500, abs=1e-6)
    assert downed["current_product_code"] is None
    seen_by_the_operator = get_success_data(
        api_client.get_paper_machine(machine["id"], OPERATOR))
    assert seen_by_the_operator["status"] == "DOWN"
    assert seen_by_the_operator["id"] == machine["id"]


def test_the_solids_summary_totals_the_press_rejects_and_the_machine_broke():
    """PRD §2.9: "The solids ledger reports `gross_solids_tons` (the sum of
    `dry_solids_tons` over rows that are not reversals, to 3 decimal places),
    `reversed_solids_tons` (the same sum over rows that *are* reversals),
    `net_solids_tons` (gross minus reversed, to 3 decimal places), and three disposition
    splits over non-reversal rows: `manifested_dry_solids_tons` for rows whose disposition
    is `MANIFESTED`, `unmanifested_dry_solids_tons` for rows whose disposition is
    `PENDING`, and `repulped_dry_solids_tons` for rows whose disposition is `REPULPED`."
    PRD §3.3: "Cleaning stores the value and appends one row to the solids ledger with
    `source_kind` of `PULP_REJECT`, `source_ref_id` pointing at this batch,
    `dry_solids_tons` equal to `measured_reject_tons`, and `disposition` of `PENDING`."
    PRD §3.5: "It appends a solids-ledger row with `source_kind` of `MACHINE_BROKE`,
    `source_ref_id` pointing at this run, `dry_solids_tons` equal to `broke_tons` and
    `disposition` of `PENDING`, skipping that row entirely when `broke_tons` is 0.000."
    PRD §3.5: "It sets the machine's `current_product_code` to the run's `product_code`,
    executes any planned grade change leaving this run as described in §3.4, and bumps the
    machine's `version` by one."

    Design: Corner/endpoints/solids_summary_adds_the_pulp_reject_and_the_machine_broke_rows
    """
    machine, batch, run = _run_completed_with_broke(1.500)

    summary = solids_summary()

    assert summary["gross_solids_tons"] == pytest.approx(3.500, abs=1e-6)
    assert summary["reversed_solids_tons"] == pytest.approx(0.000, abs=1e-6)
    assert summary["net_solids_tons"] == pytest.approx(3.500, abs=1e-6)
    assert summary["manifested_dry_solids_tons"] == pytest.approx(0.000, abs=1e-6)
    assert summary["unmanifested_dry_solids_tons"] == pytest.approx(3.500, abs=1e-6)
    assert summary["repulped_dry_solids_tons"] == pytest.approx(0.000, abs=1e-6)

    from_the_pulper = solids_rows(source_ref_id=batch["id"])
    assert len(from_the_pulper) == 1
    assert from_the_pulper[0]["source_kind"] == "PULP_REJECT"
    assert from_the_pulper[0]["dry_solids_tons"] == pytest.approx(2.000, abs=1e-6)
    from_the_machine = solids_rows(source_ref_id=run["id"],
                                   source_kind="MACHINE_BROKE")
    assert len(from_the_machine) == 1
    assert from_the_machine[0]["dry_solids_tons"] == pytest.approx(1.500, abs=1e-6)
    assert from_the_machine[0]["disposition"] == "PENDING"
    assert get_success_data(api_client.get_paper_machine(
        machine["id"], PLANNER))["current_product_code"] == "TL_140"


def test_the_second_officer_s_signature_is_what_moves_both_rows_to_manifested():
    """PRD §3.7: "Preparation records the acting officer as `prepared_by_user_id`, computes
    `total_dry_solids_tons` as the sum of `dry_solids_tons` across the claimed rows rounded
    to three decimal places, opens the manifest in `DRAFT`, and leaves the claimed rows in
    `PENDING` — nothing moves until the manifest is signed."
    PRD §3.7: "Signing records `signed_by_user_id`, sets `manifest_id` on each claimed
    solids row, and moves each of those rows' `disposition` from `PENDING` to
    `MANIFESTED`."
    PRD §2.9: "Signing a manifest moves tonnage from pending to manifested and voiding it
    moves the tonnage back, leaving `net_solids_tons` identical before and after."

    Design: Corner/endpoints/signing_a_manifest_links_both_claimed_solids_rows_and_moves_them_to_manifested
    """
    machine, batch, run = _run_completed_with_broke(1.500)
    pulp_row = solids_rows(source_ref_id=batch["id"], source_kind="PULP_REJECT")[0]
    broke_row = solids_rows(source_ref_id=run["id"], source_kind="MACHINE_BROKE")[0]
    draft = prepare_manifest([pulp_row["id"], broke_row["id"]],
                             manifest_number="MAN-0001", destination="LANDFILL")
    assert draft["status"] == "DRAFT"
    assert draft["total_dry_solids_tons"] == pytest.approx(3.500, abs=1e-6)
    assert get_success_data(api_client.get_reject_stream(
        pulp_row["id"], ENV))["disposition"] == "PENDING"

    signed = validate_success(api_client.sign_sludge_manifest(
        draft["id"], ENV_SIGNER))

    assert signed["status"] == "SIGNED"
    assert signed["total_dry_solids_tons"] == pytest.approx(3.500, abs=1e-6)
    assert signed["prepared_by_user_id"] == "eo_prep"
    assert signed["signed_by_user_id"] == "eo_sign"
    for row_id in (pulp_row["id"], broke_row["id"]):
        row = get_success_data(api_client.get_reject_stream(row_id, ENV))
        assert row["disposition"] == "MANIFESTED"
        assert row["manifest_id"] == draft["id"]
    summary = solids_summary()
    assert summary["manifested_dry_solids_tons"] == pytest.approx(3.500, abs=1e-6)
    assert summary["unmanifested_dry_solids_tons"] == pytest.approx(0.000, abs=1e-6)
    assert summary["net_solids_tons"] == pytest.approx(3.500, abs=1e-6)


def test_one_unresolvable_row_id_voids_the_entire_manifest_claim():
    """PRD §3.7: "An `EnvironmentalOfficer` prepares one with a unique `manifest_number` of
    1 to 40 characters, a `destination` of `LANDFILL`, `LAND_APPLICATION` or `FUEL`, and a
    `reject_stream_ids` array of between 1 and 20 unique solids-row identifiers."
    PRD §3.7: "Every entry must resolve to a real row that is **not** itself a reversal; an
    entry that fails either test is rejected with `ERR_REJECT_STREAM_REFERENCE_INVALID`
    (HTTP 404)."
    PRD §3.7: "Preparation records the acting officer as `prepared_by_user_id`, computes
    `total_dry_solids_tons` as the sum of `dry_solids_tons` across the claimed rows rounded
    to three decimal places, opens the manifest in `DRAFT`, and leaves the claimed rows in
    `PENDING` — nothing moves until the manifest is signed."

    Design: Corner/endpoints/one_bad_reject_stream_id_rejects_the_whole_manifest_claim
    """
    bundle = _approved_twenty_ton_batch()
    pulp_row = solids_rows(source_ref_id=bundle["batch"]["id"],
                           source_kind="PULP_REJECT")[0]

    response = api_client.create_sludge_manifest(
        {"manifest_number": "MAN-0002", "destination": "LANDFILL",
         "reject_stream_ids": [pulp_row["id"], NON_EXISTENT_UUID]}, ENV_PREPARER)
    validate_error(response, ApiErrorId.ERR_REJECT_STREAM_REFERENCE_INVALID.value, 404)

    untouched = get_success_data(api_client.get_reject_stream(pulp_row["id"], ENV))
    assert untouched["disposition"] == "PENDING"
    assert untouched["manifest_id"] is None, \
        "no partial manifest may claim only the row that resolved"
    summary = solids_summary()
    assert summary["manifested_dry_solids_tons"] == pytest.approx(0.000, abs=1e-6)
    assert summary["unmanifested_dry_solids_tons"] == pytest.approx(2.000, abs=1e-6)


def test_a_machine_out_of_service_refuses_the_start_until_it_is_returned():
    """PRD §3.5: "Conversely, a request that targets the run axis from the wrong state —
    starting a run that is not `SCHEDULED`, completing or aborting a run that is not
    `RUNNING` — is rejected with `ERR_RUN_INVALID_STATE` (HTTP 409), which is also the code
    returned when the parent machine's `status` is `DOWN` at start time."
    PRD §3.4: "The planner may take a machine out of service or return it, setting `status`
    to `DOWN` or `RUNNABLE`; a `DOWN` machine blocks both new run scheduling and run
    starting."
    PRD §3.5: "The run's `pulp_draw_tons` is added into the batch's `consumed_tons` and the
    batch's `available_tons` is recomputed."

    Design: Corner/endpoints/a_machine_taken_down_refuses_to_start_its_scheduled_run
    """
    machine, batch, run = _scheduled_run_on_pm1()
    validate_success(api_client.patch_paper_machine_status(
        machine["id"], {"status": "DOWN",
                        "expected_machine_version": machine_version(machine["id"])},
        PLANNER))

    response = api_client.start_run(machine["id"], run["id"], OPERATOR)
    validate_error(response, ApiErrorId.ERR_RUN_INVALID_STATE.value, 409)

    unstarted = get_success_data(api_client.get_run(run["id"], PLANNER))
    assert unstarted["run_status"] == "SCHEDULED"
    assert unstarted["started_by_user_id"] is None
    reserved_nothing = get_success_data(
        api_client.get_pulp_batch(batch["id"], OPERATOR))
    assert reserved_nothing["consumed_tons"] == pytest.approx(0.000, abs=1e-6)
    assert reserved_nothing["available_tons"] == pytest.approx(18.000, abs=1e-6)
    assert get_success_data(api_client.get_paper_machine(
        machine["id"], PLANNER))["status"] == "DOWN"

    validate_success(api_client.patch_paper_machine_status(
        machine["id"], {"status": "RUNNABLE",
                        "expected_machine_version": machine_version(machine["id"])},
        PLANNER))
    started = validate_success(api_client.start_run(machine["id"], run["id"], OPERATOR))
    assert started["run_status"] == "RUNNING", \
        "only the machine status stood between this run and its start"
    drawn = get_success_data(api_client.get_pulp_batch(batch["id"], OPERATOR))
    assert drawn["consumed_tons"] == pytest.approx(15.000, abs=1e-6)


def test_reversing_the_broke_row_keeps_net_equal_to_manifested_plus_pending():
    """PRD §3.7: "A row weighed in error is reversed rather than edited."
    PRD §3.7: "Reversing requires the addressed row's `disposition` to be `PENDING`, failing
    with `ERR_ENV_RECORD_INVALID_STATE` otherwise, and produces a **new** solids row whose
    `reversal_of_id` is the addressed row and whose `dry_solids_tons` equals the addressed
    row's tonnage."
    PRD §3.7: "That reversal row counts negatively in every solids aggregation, and the
    addressed row's `disposition` moves `PENDING → REPULPED`."
    PRD §2.9: "The invariant is that `net_solids_tons` equals the sum of
    `manifested_dry_solids_tons` and `unmanifested_dry_solids_tons` rounded to 3 decimal
    places, which holds because every repulped row is matched by exactly one reversal row of
    equal tonnage."

    Design: Corner/endpoints/reversing_a_broke_row_leaves_the_ledger_invariant_intact
    """
    machine, batch, run = _run_completed_with_broke(1.500)
    broke_row = solids_rows(source_ref_id=run["id"], source_kind="MACHINE_BROKE")[0]

    mirror = validate_success(api_client.reverse_reject_stream(broke_row["id"], ENV), 201)

    assert mirror["reversal_of_id"] == broke_row["id"]
    assert mirror["dry_solids_tons"] == pytest.approx(1.500, abs=1e-6)
    assert mirror["source_kind"] == "MACHINE_BROKE"
    assert mirror["source_ref_id"] == run["id"]
    reversed_row = get_success_data(api_client.get_reject_stream(broke_row["id"], ENV))
    assert reversed_row["disposition"] == "REPULPED"
    assert reversed_row["reversal_of_id"] is None
    summary = solids_summary()
    assert summary["gross_solids_tons"] == pytest.approx(3.500, abs=1e-6), \
        "the mirror row is not gross tonnage"
    assert summary["reversed_solids_tons"] == pytest.approx(1.500, abs=1e-6)
    assert summary["net_solids_tons"] == pytest.approx(2.000, abs=1e-6)
    assert summary["manifested_dry_solids_tons"] == pytest.approx(0.000, abs=1e-6)
    assert summary["unmanifested_dry_solids_tons"] == pytest.approx(2.000, abs=1e-6)
    assert summary["repulped_dry_solids_tons"] == pytest.approx(1.500, abs=1e-6)
    assert len(solids_rows(reversal_of_id=broke_row["id"])) == 1


def test_closing_a_half_filled_order_short_freezes_the_gap_and_ships_the_roll():
    """PRD §3.6: "A planner may instead close a partially filled order short:
    `PARTIALLY_ALLOCATED → SHORT_CLOSED` requires the order to be in `PARTIALLY_ALLOCATED`
    and requires `shortfall_tons` to be strictly greater than 0.000 — short-closing an order
    with nothing outstanding is rejected with `ERR_NO_SHORTFALL` (HTTP 409)."
    PRD §3.6: "Short-closing freezes `shortfall_tons` at its current value, flips the order's
    allocated roll sets `ALLOCATED → SHIPPED`, and bumps `version`."
    PRD §3.6: "The order's ledger is recomputed from the roll sets rather than accumulated:
    `allocated_tons` is the sum of `net_tons` over roll sets whose `allocated_order_id` is
    this order and whose status is `ALLOCATED` or `SHIPPED`, rounded to three decimal places;
    `shipped_tons` is the same sum restricted to sets in `SHIPPED`; and `shortfall_tons` is
    `ordered_tons` minus `allocated_tons`, floored at zero and rounded to three decimal
    places."

    Design: Corner/endpoints/short_closing_a_partially_allocated_order_freezes_the_shortfall_and_ships_the_rolls
    """
    bundle = setup_wrapped_set_on_certified_run(ordered_tons=10.00, set_net_tons=6.000)
    order_id = bundle["order"]["id"]
    allocate_roll_set(bundle["roll_set"]["id"], order_id)
    half_filled = get_success_data(api_client.get_customer_order(order_id, PLANNER))
    assert half_filled["status"] == "PARTIALLY_ALLOCATED"
    assert half_filled["shortfall_tons"] == pytest.approx(4.000, abs=1e-6)

    closed = validate_success(api_client.short_close_customer_order(order_id, PLANNER))

    assert closed["status"] == "SHORT_CLOSED"
    assert closed["allocated_tons"] == pytest.approx(6.000, abs=1e-6)
    assert closed["shipped_tons"] == pytest.approx(6.000, abs=1e-6)
    assert closed["shortfall_tons"] == pytest.approx(4.000, abs=1e-6), \
        "the gap is frozen, not recomputed away"
    shipped = get_success_data(
        api_client.get_roll_set(bundle["roll_set"]["id"], PLANNER))
    assert shipped["status"] == "SHIPPED"
    assert shipped["allocated_order_id"] == order_id
    listing = api_client.list_roll_sets(
        PLANNER, {"allocated_order_id": order_id, "status": "SHIPPED"}).json()
    assert listing["meta"]["total_count"] == 1
