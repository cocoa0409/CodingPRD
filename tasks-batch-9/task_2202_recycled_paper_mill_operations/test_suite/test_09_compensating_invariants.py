"""Four conserved ledgers observed either side of their compensating action: the mill
fiber balance, the batch pulp ledger, net solids across sign and void, and the solids
split identity across a reversal.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    declare_tl_140, setup_available_lot, sublot, queue_batch, furnish_line,
    drive_batch_to_cleaned, approve_batch, register_machine, register_permit,
    schedule_run, start_run, fiber_balance, solids_rows, solids_summary,
    prepare_manifest, sign_manifest, TEST_USERS,
)

PLANNER = TEST_USERS["planner_headers"]
OPERATOR = TEST_USERS["operator_headers"]
ENV = TEST_USERS["env_officer_headers"]
ENV_PREPARER = TEST_USERS["env_preparer_headers"]
ENV_SIGNER = TEST_USERS["env_signer_headers"]

PM1 = {"name": "PM1", "wire_width_mm": 4200, "max_tons_per_hour": 20.00,
       "changeover_buffer_minutes": 60, "steam_tph_per_ton": 1.400}
EVEN_SUBLOTS = [sublot(1, 20.000, 2.000, 12.00, 2.50),
                sublot(2, 20.000, 2.000, 12.00, 2.50)]


def _thirty_six_ton_lot():
    """One receipt of two identical sublots exactly on the moisture ceiling, so no
    deduction applies and the mill holds a single 36.00-ton lot at 2.50 contamination."""
    declare_tl_140()
    bundle = setup_available_lot(sublots_list=EVEN_SUBLOTS)
    assert bundle["receipt"]["net_tons"] == pytest.approx(36.00, abs=1e-6)
    assert bundle["receipt"]["moisture_deduction_tons"] == pytest.approx(0.000, abs=1e-6)
    assert bundle["receipt"]["weighted_contamination_pct"] == pytest.approx(2.50, abs=1e-6)
    return bundle["lot"]


def _assert_balance(received, consumed, available):
    ledger = fiber_balance()
    assert ledger["total_received_tons"] == pytest.approx(received, abs=1e-6)
    assert ledger["total_consumed_tons"] == pytest.approx(consumed, abs=1e-6)
    assert ledger["total_available_tons"] == pytest.approx(available, abs=1e-6)
    assert ledger["imbalance_tons"] == pytest.approx(0.000, abs=1e-6)


def test_charging_the_whole_lot_leaves_the_mill_fiber_balance_at_zero_imbalance():
    """PRD §2.9: "That imbalance must read exactly zero at every point at which it can
    be observed, including immediately after a pulp batch cancellation releases a
    reservation and immediately after an aborted run returns its drawn pulp."

    Design: Difficulty/compensating_invariant/lot_fiber_ledger_survives_pulper_charge_then_cancel
    """
    lot = _thirty_six_ton_lot()
    batch = queue_batch("TL_140", [furnish_line(lot["id"], 36.000)])

    charged = get_success_data(api_client.start_pulp_batch(batch["id"], OPERATOR))
    assert charged["charged_tons"] == pytest.approx(36.000, abs=1e-6)
    assert charged["blend_contamination_pct"] == pytest.approx(2.500, abs=1e-6)
    assert charged["provisional_accepted_tons"] == pytest.approx(30.060, abs=1e-6), \
        "an 83.50 percent effective yield on 36.000 tons"

    depleted = get_success_data(api_client.get_inventory_lot(lot["id"], OPERATOR))
    assert depleted["tons_consumed"] == pytest.approx(36.000, abs=1e-6)
    assert depleted["tons_available"] == pytest.approx(0.000, abs=1e-6)
    assert depleted["status"] == "DEPLETED"
    _assert_balance(36.000, 36.000, 0.000)


def test_cancelling_from_pulping_releases_the_reservation_without_erasing_the_yield():
    """PRD §3.3: "A batch cancelled while `PULPING` must undo its reservation: each
    furnish line's `tons_charged` is subtracted back out of its lot's `tons_consumed`,
    and any lot that consequently leaves `DEPLETED` returns to `AVAILABLE`."

    Design: Difficulty/compensating_invariant/lot_fiber_ledger_survives_pulper_charge_then_cancel
    """
    lot = _thirty_six_ton_lot()
    batch = queue_batch("TL_140", [furnish_line(lot["id"], 36.000)])
    get_success_data(api_client.start_pulp_batch(batch["id"], OPERATOR))

    cancelled = get_success_data(api_client.cancel_pulp_batch(batch["id"], PLANNER))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["provisional_accepted_tons"] == pytest.approx(30.060, abs=1e-6), \
        "the release does not rewrite the pinned book projection"

    restored = get_success_data(api_client.get_inventory_lot(lot["id"], OPERATOR))
    assert restored["tons_consumed"] == pytest.approx(0.000, abs=1e-6)
    assert restored["tons_available"] == pytest.approx(36.000, abs=1e-6)
    assert restored["status"] == "AVAILABLE"
    _assert_balance(36.000, 0.000, 36.000)

    again = api_client.start_pulp_batch(batch["id"], OPERATOR)
    validate_error(again, ApiErrorId.ERR_PULP_BATCH_INVALID_STATE.value, 409)


def _approved_batch_with_a_running_run():
    lot = _thirty_six_ton_lot()
    batch = queue_batch("TL_140", [furnish_line(lot["id"], 30.000)])
    drive_batch_to_cleaned(batch["id"], 4.500)
    batch = approve_batch(batch["id"])
    register_permit()
    machine = register_machine(**PM1)
    run = schedule_run(machine["id"], "TL_140", batch["id"],
                       window_start="2026-08-06T00:00:00Z",
                       window_end="2026-08-06T06:00:00Z", pulp_draw_tons=12.000)
    start_run(machine["id"], run["id"])
    return lot, batch, machine, run


def test_the_pulp_draw_moves_the_batch_ledger_and_leaves_the_lot_ledger_alone():
    """PRD §3.3: "`available_tons` is `final_accepted_tons` minus `consumed_tons`
    rounded to three decimal places while the batch is `APPROVED`, and reads 0.000 in
    every other status; at the instant of approval `consumed_tons` is still 0.000, so
    `available_tons` opens equal to `final_accepted_tons`."

    Design: Difficulty/compensating_invariant/batch_pulp_ledger_restored_by_run_abort_without_touching_lots
    """
    lot, batch, _machine, _run = _approved_batch_with_a_running_run()
    assert batch["final_accepted_tons"] == pytest.approx(25.500, abs=1e-6)
    assert batch["provisional_accepted_tons"] == pytest.approx(25.050, abs=1e-6)
    assert batch["yield_variance_tons"] == pytest.approx(0.450, abs=1e-6)

    drawn = get_success_data(api_client.get_pulp_batch(batch["id"], OPERATOR))
    assert drawn["consumed_tons"] == pytest.approx(12.000, abs=1e-6)
    assert drawn["available_tons"] == pytest.approx(13.500, abs=1e-6)
    assert drawn["consumed_tons"] + drawn["available_tons"] == \
        pytest.approx(drawn["final_accepted_tons"], abs=1e-6)

    untouched = get_success_data(api_client.get_inventory_lot(lot["id"], OPERATOR))
    assert untouched["tons_consumed"] == pytest.approx(30.000, abs=1e-6)
    assert untouched["tons_available"] == pytest.approx(6.000, abs=1e-6)
    assert untouched["status"] == "AVAILABLE"
    _assert_balance(36.000, 30.000, 6.000)


def test_aborting_the_run_returns_the_pulp_and_credits_nothing_to_the_lot():
    """PRD §3.5: "Aborting a run, `RUNNING → ABORTED`, is the planner's emergency stop
    and is the compensating action for the pulp draw. It subtracts `pulp_draw_tons` back
    out of the batch's `consumed_tons` and recomputes `available_tons`, so total fiber
    tonnage is conserved."

    Design: Difficulty/compensating_invariant/batch_pulp_ledger_restored_by_run_abort_without_touching_lots
    """
    lot, batch, machine, run = _approved_batch_with_a_running_run()

    aborted = get_success_data(api_client.abort_run(machine["id"], run["id"], PLANNER))
    assert aborted["run_status"] == "ABORTED"
    assert aborted["quality_status"] == "CONDEMNED"

    returned = get_success_data(api_client.get_pulp_batch(batch["id"], OPERATOR))
    assert returned["consumed_tons"] == pytest.approx(0.000, abs=1e-6)
    assert returned["available_tons"] == pytest.approx(25.500, abs=1e-6)
    assert returned["final_accepted_tons"] == pytest.approx(25.500, abs=1e-6)
    assert returned["status"] == "APPROVED", "the returned pulp is drawable again"

    unchanged = get_success_data(api_client.get_inventory_lot(lot["id"], OPERATOR))
    assert unchanged["tons_consumed"] == pytest.approx(30.000, abs=1e-6)
    assert unchanged["tons_available"] == pytest.approx(6.000, abs=1e-6)
    _assert_balance(36.000, 30.000, 6.000)


def _assert_solids(gross, reversed_tons, net, manifested, unmanifested, repulped):
    summary = solids_summary()
    assert summary["gross_solids_tons"] == pytest.approx(gross, abs=1e-6)
    assert summary["reversed_solids_tons"] == pytest.approx(reversed_tons, abs=1e-6)
    assert summary["net_solids_tons"] == pytest.approx(net, abs=1e-6)
    assert summary["manifested_dry_solids_tons"] == pytest.approx(manifested, abs=1e-6)
    assert summary["unmanifested_dry_solids_tons"] == pytest.approx(unmanifested, abs=1e-6)
    assert summary["repulped_dry_solids_tons"] == pytest.approx(repulped, abs=1e-6)
    assert summary["net_solids_tons"] == pytest.approx(manifested + unmanifested, abs=1e-6)


def _one_pending_row_on_a_draft_manifest():
    lot = _thirty_six_ton_lot()
    batch = queue_batch("TL_140", [furnish_line(lot["id"], 30.000)])
    drive_batch_to_cleaned(batch["id"], 4.500)
    rows = solids_rows(source_ref_id=batch["id"], source_kind="PULP_REJECT")
    assert len(rows) == 1
    manifest = prepare_manifest([rows[0]["id"]], manifest_number="MAN-0001",
                               destination="LANDFILL")
    assert manifest["total_dry_solids_tons"] == pytest.approx(4.500, abs=1e-6)
    assert manifest["status"] == "DRAFT"
    assert manifest["prepared_by_user_id"] == "eo_prep"
    return rows[0], manifest


def test_signing_moves_tonnage_between_buckets_without_moving_the_net():
    """PRD §3.7: "Signing records `signed_by_user_id`, sets `manifest_id` on each claimed
    solids row, and moves each of those rows' `disposition` from `PENDING` to
    `MANIFESTED`."

    Design: Difficulty/compensating_invariant/solids_net_tonnage_conserved_across_manifest_sign_then_void
    """
    row, manifest = _one_pending_row_on_a_draft_manifest()
    assert row["disposition"] == "PENDING"
    assert row["manifest_id"] is None
    _assert_solids(4.500, 0.000, 4.500, 0.000, 4.500, 0.000)

    signed = sign_manifest(manifest["id"])
    assert signed["status"] == "SIGNED"
    assert signed["signed_by_user_id"] == "eo_sign"

    claimed = get_success_data(api_client.get_reject_stream(row["id"], ENV))
    assert claimed["disposition"] == "MANIFESTED"
    assert claimed["manifest_id"] == manifest["id"]
    _assert_solids(4.500, 0.000, 4.500, 4.500, 0.000, 0.000)


def test_voiding_returns_the_row_to_pending_and_cannot_be_signed_again():
    """PRD §3.7: "Voiding a manifest is available from `DRAFT` or `SIGNED`, moves it to
    `VOIDED`, and is the exact compensating action for signing: each claimed row has its
    `manifest_id` cleared and its `disposition` returned to `PENDING`, leaving
    `net_solids_tons` unchanged before and after."

    Design: Difficulty/compensating_invariant/solids_net_tonnage_conserved_across_manifest_sign_then_void
    """
    row, manifest = _one_pending_row_on_a_draft_manifest()
    sign_manifest(manifest["id"])

    voided = get_success_data(
        api_client.void_sludge_manifest(manifest["id"], ENV_SIGNER))
    assert voided["status"] == "VOIDED"
    assert voided["total_dry_solids_tons"] == pytest.approx(4.500, abs=1e-6), \
        "the claim amount is history, not a live balance"

    released = get_success_data(api_client.get_reject_stream(row["id"], ENV))
    assert released["disposition"] == "PENDING"
    assert released["manifest_id"] is None
    _assert_solids(4.500, 0.000, 4.500, 0.000, 4.500, 0.000)

    again = api_client.sign_sludge_manifest(manifest["id"], ENV_SIGNER)
    validate_error(again, ApiErrorId.ERR_ENV_RECORD_INVALID_STATE.value, 409)


def _two_pending_rows_totalling_eight_and_a_half_tons():
    lot = _thirty_six_ton_lot()
    rows = []
    for tons_charged, rejects in ((20.000, 6.000), (16.000, 2.500)):
        batch = queue_batch("TL_140", [furnish_line(lot["id"], tons_charged)])
        drive_batch_to_cleaned(batch["id"], rejects)
        found = solids_rows(source_ref_id=batch["id"], source_kind="PULP_REJECT")
        assert len(found) == 1
        rows.append(found[0])
    depleted = get_success_data(api_client.get_inventory_lot(lot["id"], OPERATOR))
    assert depleted["tons_consumed"] == pytest.approx(36.000, abs=1e-6)
    assert depleted["status"] == "DEPLETED"
    _assert_balance(36.000, 36.000, 0.000)
    return rows[0], rows[1]


def test_a_reversal_lowers_the_net_while_the_split_identity_still_closes():
    """PRD §3.7: "Reversing requires the addressed row's `disposition` to be `PENDING`,
    failing with `ERR_ENV_RECORD_INVALID_STATE` otherwise, and produces a **new** solids
    row whose `reversal_of_id` is the addressed row and whose `dry_solids_tons` equals
    the addressed row's tonnage."

    Design: Difficulty/compensating_invariant/solids_split_identity_holds_across_reject_reversal
    """
    bigger, smaller = _two_pending_rows_totalling_eight_and_a_half_tons()
    _assert_solids(8.500, 0.000, 8.500, 0.000, 8.500, 0.000)

    response = api_client.reverse_reject_stream(bigger["id"], ENV)
    validate_success(response, expected_status=201)
    twin = get_success_data(response)
    assert twin["reversal_of_id"] == bigger["id"]
    assert twin["dry_solids_tons"] == pytest.approx(6.000, abs=1e-6)

    assert get_success_data(api_client.get_reject_stream(bigger["id"], ENV))["disposition"] \
        == "REPULPED"
    assert get_success_data(api_client.get_reject_stream(smaller["id"], ENV))["disposition"] \
        == "PENDING"
    _assert_solids(8.500, 6.000, 2.500, 0.000, 2.500, 6.000)
    assert len(solids_rows(reversal_of_id=bigger["id"])) == 1


def test_the_compensation_cannot_be_applied_twice_or_claimed_by_a_hauler():
    """PRD §3.7: "That reversal row counts negatively in every solids aggregation, and
    the addressed row's `disposition` moves `PENDING → REPULPED`." PRD §3.7: "Every entry
    must resolve to a real row that is **not** itself a reversal; an entry that fails
    either test is rejected with `ERR_REJECT_STREAM_REFERENCE_INVALID` (HTTP 404)."

    Design: Difficulty/compensating_invariant/solids_split_identity_holds_across_reject_reversal
    """
    bigger, _smaller = _two_pending_rows_totalling_eight_and_a_half_tons()
    twin = get_success_data(api_client.reverse_reject_stream(bigger["id"], ENV))

    doubled = api_client.reverse_reject_stream(bigger["id"], ENV)
    validate_error(doubled, ApiErrorId.ERR_ENV_RECORD_INVALID_STATE.value, 409)

    claimed = api_client.create_sludge_manifest(
        {"manifest_number": "MAN-0002", "destination": "LANDFILL",
         "reject_stream_ids": [twin["id"]]}, ENV_PREPARER)
    validate_error(claimed, ApiErrorId.ERR_REJECT_STREAM_REFERENCE_INVALID.value, 404)

    _assert_solids(8.500, 6.000, 2.500, 0.000, 2.500, 6.000)
