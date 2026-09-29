"""Initial states, the valid edges, and the terminal states that refuse every
later verb across the lot, campaign, furnace, run, pack, claimant, claim and
counterfeit-report machines."""

import pytest

from test_helpers import (
    HARDNESS_WINDOW,
    TEST_USERS,
    ApiErrorId,
    advance_lot,
    advance_payload,
    api_client,
    assert_specimen_ledger,
    claimant_block_payload,
    create_chamber,
    create_claimant,
    create_furnace,
    create_lot,
    create_pack,
    create_report,
    create_sku,
    campaign_complete_payload,
    deny_payload,
    dismiss_report,
    furnace_status_payload,
    approve_claim_payload,
    fulfill_payload,
    hold_payload,
    add_pack_member,
    pack_member_payload,
    pack_withdraw_payload,
    read_claim,
    read_lot,
    read_pack,
    read_program,
    read_sku,
    read_test_run,
    release_payload,
    schedule_campaign,
    schedule_test_run,
    set_clock,
    setup_lot_with_completed_campaign,
    setup_rejected_lot,
    setup_warranty_scenario,
    submit_results,
    make_test_run_payload,
    validate_error,
    validate_paginated,
    validate_success,
    void_payload,
    make_warranty_administrator_headers,
)

CM = TEST_USERS["channel_manager_headers"]
PP = TEST_USERS["production_planner_headers"]
QE = TEST_USERS["quality_engineer_headers"]
WA_1 = make_warranty_administrator_headers("wa-1")
WA_2 = make_warranty_administrator_headers("wa-2")

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"
FIRST_WINDOW = ("2026-08-02T06:00:00Z", "2026-08-02T10:00:00Z")
CHAMBER_WINDOW = ("2026-08-04T00:00:00Z", "2026-08-06T00:00:00Z")
WEAK_SIGHTING = {
    "channel_name": "OpenBazaar",
    "seller_handle": "torque_deals_99",
    "evidence_grade": "WEAK",
    "unit_estimate": 10,
}
STRONG_SIGHTING = {
    "channel_name": "OpenBazaar",
    "seller_handle": "torque_deals_99",
    "evidence_grade": "STRONG",
    "unit_estimate": 600,
}
HANDLE_LINE = {"component_code": "HANDLE", "component_list_price_cents": 1099, "quantity": 1}


# ---------------------------------------------------------------------------
# Initial states
# ---------------------------------------------------------------------------


def test_every_new_row_lands_in_its_declared_initial_state():
    """A lot arrives in all three of its initial states at once, a furnace
    AVAILABLE, a campaign SCHEDULED with no soak recorded, and a sighting OPEN
    with its points already frozen but contributing nothing.

    PRD §3.2: "A furnace starts `AVAILABLE` and may be moved between `AVAILABLE`
    and `MAINTENANCE` by supplying the desired `status`."

    Design: Corner/state_machines/initial_states_of_every_lifecycle_entity
    """
    set_clock(DEFAULT_CLOCK)
    sku = create_sku()
    furnace = create_furnace()
    lot = create_lot(sku["id"], lot_code="LOT-BR-A", specimen_pool_total=20)
    campaign = schedule_campaign(
        lot["id"],
        furnace["id"],
        window_start=FIRST_WINDOW[0],
        window_end=FIRST_WINDOW[1],
        charge_kg=800,
    )
    report = create_report(sku["id"], **WEAK_SIGHTING)

    assert lot["process_status"] == "FORGED"
    assert lot["cert_status"] == "DRAFT"
    assert lot["disposition"] == "IN_PROCESS"
    assert furnace["status"] == "AVAILABLE"
    assert campaign["status"] == "SCHEDULED"
    assert campaign["soak_minutes"] is None
    assert campaign["buffered_end"].startswith("2026-08-02T10:45")
    assert report["status"] == "OPEN"
    assert report["risk_points"] == 5
    assert report["confirmation_note"] is None
    assert report["dismissal_note"] is None

    refreshed = read_sku(sku["id"])
    assert refreshed["brand_risk_score"] == 0
    assert refreshed["warranty_posture"] == "OPEN"


# ---------------------------------------------------------------------------
# The shop-floor machines
# ---------------------------------------------------------------------------


def test_a_campaign_completes_once_and_then_refuses_a_second_soak_record():
    """The soak is written and the campaign leaves SCHEDULED, so replaying the
    identical request is a state error rather than a silent overwrite.

    PRD §3.2: "The campaign must still be `SCHEDULED`, otherwise
    `ERR_CAMPAIGN_STATE_INVALID`, and the reported soak must be at least a full
    hour — 60 minutes — otherwise `ERR_SOAK_TIME_TOO_SHORT`."

    Design: Corner/state_machines/campaign_completion_stores_soak_then_second_completion_rejected
    """
    sku = create_sku()
    furnace = create_furnace()
    lot = create_lot(sku["id"], lot_code="LOT-BR-A", specimen_pool_total=20)
    campaign = schedule_campaign(
        lot["id"],
        furnace["id"],
        window_start=FIRST_WINDOW[0],
        window_end=FIRST_WINDOW[1],
        charge_kg=800,
    )

    completed = validate_success(
        api_client.complete_furnace_campaign(
            campaign["id"], campaign_complete_payload(soak_minutes=120), PP
        )
    )
    assert completed["status"] == "COMPLETED"
    assert completed["soak_minutes"] == 120
    assert completed["version"] == 2

    validate_error(
        api_client.complete_furnace_campaign(
            campaign["id"], campaign_complete_payload(soak_minutes=180), PP
        ),
        ApiErrorId.ERR_CAMPAIGN_STATE_INVALID,
        409,
    )

    unchanged = validate_success(api_client.get_furnace_campaign(campaign["id"], PP))
    assert unchanged["soak_minutes"] == 120
    assert unchanged["version"] == 2
    assert read_lot(lot["id"])["process_status"] == "FORGED"


@pytest.mark.parametrize("target", ["MACHINED", "FORGED"])
def test_the_routing_dimension_refuses_any_stage_but_its_immediate_successor(target):
    """A FORGED lot with heat treatment already recorded still cannot skip to
    MACHINED, and it cannot restate the stage it is already on.

    PRD §3.2: "The requested stage must be the immediate successor of the lot's
    current stage — `HEAT_TREATED` only from `FORGED`, `MACHINED` only from
    `HEAT_TREATED`, `PLATED` only from `MACHINED`, `ASSEMBLED` only from
    `PLATED` — and anything else is `ERR_LOT_PROCESS_STATE_INVALID`."

    Design: Corner/state_machines/advance_skipping_a_process_stage_rejected
    """
    ctx = setup_lot_with_completed_campaign(lot_overrides={"specimen_pool_total": 20})
    lot_id = ctx["lot"]["id"]
    before = read_lot(lot_id)

    validate_error(
        api_client.advance_production_lot(lot_id, advance_payload(target), PP),
        ApiErrorId.ERR_LOT_PROCESS_STATE_INVALID,
        409,
    )

    after = read_lot(lot_id)
    assert after["process_status"] == "FORGED"
    assert after["version"] == before["version"]


def test_certifying_a_draft_dossier_reports_the_dossier_and_not_the_routing_state():
    """A lot with no test runs at all is refused on its dossier, which sits ahead
    of the routing, quarantine, battery and margin gates.

    PRD §3.5: "The dossier must be `IN_TEST` — a lot still `DRAFT`, already
    `CERTIFIED` or currently `REJECTED` gives `ERR_LOT_CERT_STATE_INVALID`."

    Design: Corner/state_machines/certify_while_cert_status_draft_rejected
    """
    sku = create_sku()
    lot = create_lot(sku["id"], lot_code="LOT-BR-A", specimen_pool_total=20)

    body = validate_error(
        api_client.certify_production_lot(lot["id"], QE),
        ApiErrorId.ERR_LOT_CERT_STATE_INVALID,
        409,
    )
    assert body["error_id"] != ApiErrorId.ERR_LOT_PROCESS_STATE_INVALID

    unchanged = read_lot(lot["id"])
    assert unchanged["cert_status"] == "DRAFT"
    assert unchanged["certified_at"] is None
    assert unchanged["process_status"] == "FORGED"


# ---------------------------------------------------------------------------
# Test runs: terminal statuses and the compensating void
# ---------------------------------------------------------------------------


def _passed_hardness_run():
    """A HEAT_TREATED lot of 20 specimens with one two-specimen HARDNESS run
    already resolved to PASSED."""
    ctx = setup_lot_with_completed_campaign(lot_overrides={"specimen_pool_total": 20})
    lot_id = ctx["lot"]["id"]
    advance_lot(lot_id, "HEAT_TREATED")
    run = schedule_test_run(lot_id, "HARDNESS", 2, HARDNESS_WINDOW)
    ctx["run"] = submit_results(run["id"], (52.0, 53.0))
    ctx["lot"] = read_lot(lot_id)
    return ctx


def test_a_resolved_run_will_not_accept_a_second_set_of_readings():
    """The stored result is final: fresh readings on a PASSED run are refused and
    the original mean stays on the row.

    PRD §3.4: "The run must be `SCHEDULED`, and results on a run that has already
    resolved are `ERR_TEST_RUN_STATE_INVALID`."

    Design: Corner/state_machines/test_run_results_and_void_blocked_after_terminal_status
    """
    ctx = _passed_hardness_run()
    assert ctx["run"]["status"] == "PASSED"
    assert ctx["run"]["mean_reading"] == pytest.approx(52.5, abs=0.01)
    assert ctx["run"]["requirement_value"] == pytest.approx(50.0, abs=0.01)
    assert ctx["run"]["result_margin_pct"] == pytest.approx(5.00, abs=0.01)

    validate_error(
        api_client.submit_test_run_results(
            ctx["run"]["id"], {"readings": [58.0, 59.0]}, QE
        ),
        ApiErrorId.ERR_TEST_RUN_STATE_INVALID,
        409,
    )

    unchanged = read_test_run(ctx["run"]["id"])
    assert unchanged["readings"] == [52.0, 53.0]
    assert unchanged["mean_reading"] == pytest.approx(52.5, abs=0.01)


def test_a_resolved_run_will_not_be_voided_to_reclaim_its_specimens():
    """Destroyed material never returns, so voiding a PASSED run is refused and
    the consumed bucket keeps its two specimens.

    PRD §3.3: "The run must still be `SCHEDULED`, otherwise
    `ERR_TEST_RUN_STATE_INVALID`."

    Design: Corner/state_machines/test_run_results_and_void_blocked_after_terminal_status
    """
    ctx = _passed_hardness_run()

    validate_error(
        api_client.void_test_run(
            ctx["run"]["id"],
            void_payload(void_reason="Operator wants to discard the result"),
            QE,
        ),
        ApiErrorId.ERR_TEST_RUN_STATE_INVALID,
        409,
    )

    lot = read_lot(ctx["lot"]["id"])
    assert lot["specimens_consumed"] == 2
    assert lot["specimens_committed"] == 0
    assert lot["specimens_available"] == 18
    assert lot["cert_status"] == "IN_TEST"
    assert lot["hardness_index_sample"] == pytest.approx(52.50, abs=0.01)
    assert lot["hardness_index_pooled"] == pytest.approx(52.50, abs=0.01)
    assert_specimen_ledger(lot)


def _plated_lot_with_a_scheduled_exposure():
    """A PLATED lot of 40 specimens holding a ten-coupon corrosion booking in a
    24 coupon cabinet."""
    ctx = setup_lot_with_completed_campaign(lot_overrides={"specimen_pool_total": 40})
    lot_id = ctx["lot"]["id"]
    for stage in ("HEAT_TREATED", "MACHINED", "PLATED"):
        advance_lot(lot_id, stage)
    ctx["chamber"] = create_chamber(coupon_capacity=24)
    ctx["run"] = schedule_test_run(
        lot_id, "SALT_SPRAY", 10, CHAMBER_WINDOW, chamber_id=ctx["chamber"]["id"]
    )
    ctx["lot"] = read_lot(lot_id)
    return ctx


def test_voiding_a_booking_returns_its_specimens_to_available_and_not_to_consumed():
    """Ten committed coupons come back to the available pool, which is the exact
    inverse of the scheduling move.

    PRD §3.3: "Voiding sets `status` to `VOID`, stores the supplied
    `void_reason`, returns the run's `specimen_count` from `specimens_committed`
    back to `specimens_available` — the exact compensating action of scheduling —
    releases whatever chamber coupons the run was holding so that later corrosion
    runs see the capacity again, and increments both the run's and the lot's
    `version`."

    Design: Corner/state_machines/void_returns_specimens_and_frees_chamber_capacity
    """
    ctx = _plated_lot_with_a_scheduled_exposure()
    assert ctx["lot"]["specimens_committed"] == 10
    assert ctx["lot"]["specimens_available"] == 30
    assert ctx["lot"]["specimens_consumed"] == 0

    voided = validate_success(
        api_client.void_test_run(
            ctx["run"]["id"],
            void_payload(void_reason="Chamber recalibration invalidated the booking"),
            QE,
        )
    )

    assert voided["status"] == "VOID"
    assert voided["void_reason"] == "Chamber recalibration invalidated the booking"

    lot = read_lot(ctx["lot"]["id"])
    assert lot["specimens_committed"] == 0
    assert lot["specimens_available"] == 40
    assert lot["specimens_consumed"] == 0
    assert_specimen_ledger(lot)


def test_a_voided_booking_stops_occupying_the_cabinet_it_had_reserved():
    """With the ten-coupon run void, a full 24 coupon exposure fits the identical
    window that would otherwise have peaked at 34.

    PRD §3.3: "a run beginning exactly when another ends never conflicts, and
    `VOID` runs never occupy anything."

    Design: Corner/state_machines/void_returns_specimens_and_frees_chamber_capacity
    """
    ctx = _plated_lot_with_a_scheduled_exposure()
    validate_success(
        api_client.void_test_run(
            ctx["run"]["id"],
            void_payload(void_reason="Chamber recalibration invalidated the booking"),
            QE,
        )
    )

    accepted = validate_success(
        api_client.create_test_run(
            make_test_run_payload(
                ctx["lot"]["id"],
                test_type="SALT_SPRAY",
                specimen_count=24,
                window_start=CHAMBER_WINDOW[0],
                window_end=CHAMBER_WINDOW[1],
                chamber_id=ctx["chamber"]["id"],
            ),
            QE,
        ),
        201,
    )
    assert accepted["status"] == "SCHEDULED"
    assert accepted["specimen_count"] == 24

    lot = read_lot(ctx["lot"]["id"])
    assert lot["specimens_committed"] == 24
    assert lot["specimens_available"] == 16
    assert_specimen_ledger(lot)

    _, meta = validate_paginated(
        api_client.list_test_runs(QE, params={"chamber_id": ctx["chamber"]["id"]})
    )
    assert meta["total_count"] == 2


# ---------------------------------------------------------------------------
# Two-state toggles and terminal branches
# ---------------------------------------------------------------------------


def test_a_furnace_toggles_between_two_states_and_refuses_its_current_one():
    """There is no self-edge on either side of the toggle, and each accepted move
    bumps the furnace version.

    PRD §3.2: "The requested status must differ from the current one, otherwise
    `ERR_FURNACE_STATUS_UNCHANGED`."

    Design: Corner/state_machines/furnace_status_toggles_and_rejects_unchanged_value
    """
    furnace = create_furnace()

    validate_error(
        api_client.set_furnace_status(furnace["id"], furnace_status_payload(status="AVAILABLE"), PP),
        ApiErrorId.ERR_FURNACE_STATUS_UNCHANGED,
        409,
    )

    down = validate_success(
        api_client.set_furnace_status(
            furnace["id"], furnace_status_payload(status="MAINTENANCE"), PP
        )
    )
    assert down["status"] == "MAINTENANCE"
    assert down["version"] == 2

    validate_error(
        api_client.set_furnace_status(
            furnace["id"], furnace_status_payload(status="MAINTENANCE"), PP
        ),
        ApiErrorId.ERR_FURNACE_STATUS_UNCHANGED,
        409,
    )
    assert validate_success(api_client.get_heat_treat_furnace(furnace["id"], PP))["version"] == 2

    up = validate_success(
        api_client.set_furnace_status(furnace["id"], furnace_status_payload(status="AVAILABLE"), PP)
    )
    assert up["status"] == "AVAILABLE"
    assert up["version"] == 3


def test_a_dismissed_sighting_can_never_be_promoted_to_a_confirmation():
    """The quiet branch is terminal: the frozen 50 points stay on the row and
    never reach the roll-up.

    PRD §3.9: "Dismissal is the quiet branch. A `BrandProtectionAnalyst` supplies
    a `dismissal_note`, the report must be `OPEN` (otherwise
    `ERR_REPORT_STATE_INVALID`), and the report moves `OPEN → DISMISSED` with the
    note stored and its `version` incremented."

    Design: Corner/state_machines/dismissed_report_cannot_later_be_confirmed
    """
    sku = create_sku()
    report = create_report(sku["id"], **STRONG_SIGHTING)
    assert report["risk_points"] == 50

    dismissed = dismiss_report(
        report["id"], dismissal_note="Seller produced a valid distributor invoice"
    )
    assert dismissed["status"] == "DISMISSED"
    assert dismissed["dismissal_note"] == "Seller produced a valid distributor invoice"

    validate_error(
        api_client.confirm_counterfeit_report(
            report["id"], {"confirmation_note": "Reopening after new evidence"}, TEST_USERS[
                "brand_protection_analyst_headers"
            ]
        ),
        ApiErrorId.ERR_REPORT_STATE_INVALID,
        409,
    )

    still = validate_success(
        api_client.get_counterfeit_report(
            report["id"], TEST_USERS["brand_protection_analyst_headers"]
        )
    )
    assert still["status"] == "DISMISSED"
    assert still["confirmation_note"] is None

    refreshed = read_sku(sku["id"])
    assert refreshed["brand_risk_score"] == 0
    assert refreshed["confirmed_counterfeit_count"] == 0
    assert refreshed["warranty_posture"] == "OPEN"


def test_blocking_a_claimant_twice_is_refused_as_a_state_error():
    """BLOCKED is terminal, so the second block finds no ACTIVE claimant to move
    and applies nothing.

    PRD §3.7: "A `WarrantyAdministrator` may block a claimant after confirmed
    abuse by supplying a `block_reason`; the claimant must be `ACTIVE`, otherwise
    `ERR_CLAIMANT_STATE_INVALID`, and blocking moves the claimant `ACTIVE →
    BLOCKED`, leaves every existing claim in place, and increments the claimant's
    `version`."

    Design: Corner/state_machines/blocking_an_already_blocked_claimant_rejected
    """
    claimant = create_claimant()
    payload = claimant_block_payload(block_reason="Repeated fraudulent submissions")

    blocked = validate_success(api_client.block_claimant(claimant["id"], payload, WA_1))
    assert blocked["status"] == "BLOCKED"
    assert blocked["version"] == 2

    validate_error(
        api_client.block_claimant(claimant["id"], payload, WA_1),
        ApiErrorId.ERR_CLAIMANT_STATE_INVALID,
        409,
    )

    unchanged = validate_success(api_client.get_claimant(claimant["id"], WA_1))
    assert unchanged["version"] == 2
    assert unchanged["status"] == "BLOCKED"


def test_a_draft_pack_cannot_be_withdrawn_and_stays_open_for_edits():
    """Withdrawal is defined only from APPROVED, and the refusal leaves the pack
    accepting further member lines.

    PRD §3.6: "An approved pack is withdrawn from retail by a `ChannelManager` or
    a `BrandProtectionAnalyst` supplying a `withdrawal_reason`; the pack must be
    `APPROVED`, otherwise `ERR_PACK_STATE_INVALID`, and withdrawal moves it
    `APPROVED → WITHDRAWN` and increments its `version`."

    Design: Corner/state_machines/withdrawing_a_draft_pack_rejected
    """
    sku = create_sku()
    other = create_sku(sku_code="SO-20-BR", tool_family="SOCKET", nominal_size_mm=20,
                       alloy_grade="CR_V", list_price_cents=1500)
    pack = create_pack(sku["id"], pack_code="PK-RD-1", pack_type="RETAIL_DISPLAY")
    add_pack_member(pack["id"], sku["id"], 2)

    validate_error(
        api_client.withdraw_pack_configuration(
            pack["id"], pack_withdraw_payload(withdrawal_reason="Retail programme cancelled"), CM
        ),
        ApiErrorId.ERR_PACK_STATE_INVALID,
        409,
    )

    still_draft = read_pack(pack["id"])
    assert still_draft["status"] == "DRAFT"
    assert still_draft["distinct_member_count"] == 1

    appended = validate_success(
        api_client.add_pack_member(pack["id"], pack_member_payload(other["id"], 1), CM), 201
    )
    assert appended["sku_id"] == other["id"]
    assert read_pack(pack["id"])["distinct_member_count"] == 2


def test_a_denied_claim_refuses_every_later_verb_and_spends_nothing():
    """Hold, approve and fulfil all bounce off the terminal state, so no version
    check, no posture check and no ledger move is ever reached.

    PRD §3.8: "Adjudication is where the reserve is spent, and its state graph
    branches. A claim enters at `SUBMITTED`, may cycle through `FRAUD_HOLD` and
    back any number of times, and ends in one of four terminal states:
    `FULFILLED`, `DENIED`, `DENIED_FRAUD` or `REVOKED`."

    Design: Corner/state_machines/denied_claim_is_terminal_for_every_subsequent_action
    """
    ctx = setup_warranty_scenario(lines=(HANDLE_LINE,), claim_overrides={"serial_code": "SN-0001"})
    claim_id = ctx["claim"]["id"]

    denied = validate_success(
        api_client.deny_warranty_claim(claim_id, deny_payload(denial_code="NO_DEFECT_FOUND"), WA_1)
    )
    assert denied["status"] == "DENIED"
    assert denied["denial_code"] == "NO_DEFECT_FOUND"

    program_version = read_program(ctx["program"]["id"])["version"]
    for response in (
        api_client.hold_warranty_claim(
            claim_id, hold_payload(hold_reason="Late fraud signal"), WA_2
        ),
        api_client.approve_warranty_claim(
            claim_id, approve_claim_payload(program_version), WA_2
        ),
        api_client.fulfill_warranty_claim(claim_id, fulfill_payload(), WA_2),
    ):
        validate_error(response, ApiErrorId.ERR_CLAIM_STATE_INVALID, 409)

    claim = read_claim(claim_id)
    assert claim["status"] == "DENIED"
    assert claim["shipment_ref"] is None
    assert claim["hold_reason"] is None

    program = read_program(ctx["program"]["id"])
    assert program["reserve_balance_cents"] == 5_000_000
    assert program["open_hold_count"] == 0
    assert read_sku(ctx["sku"]["id"])["units_reserved"] == 0


def test_a_quarantined_lot_reports_its_quarantine_rather_than_its_missing_certificate():
    """The rejected lot is both quarantined and uncertified, and quarantine sits
    highest on the release ladder.

    PRD §3.5: "Its gates run in this order: the lot must not be `QUARANTINED`
    (`ERR_LOT_QUARANTINED`); its `disposition` must be `IN_PROCESS`, so a lot
    already `RELEASED` cannot be released twice
    (`ERR_LOT_ALREADY_DISPOSITIONED`); the supplied `expected_sku_version` must
    equal the parent SKU's current `version` (`ERR_STALE_SKU_VERSION`, HTTP 412);
    and only then, the dossier must be `CERTIFIED` (`ERR_LOT_NOT_CERTIFIED`)."

    Design: Corner/state_machines/quarantined_lot_cannot_be_released
    """
    ctx = setup_rejected_lot(lot_overrides={"specimen_pool_total": 20})
    assert ctx["failing_run"]["status"] == "FAILED"
    assert ctx["failing_run"]["mandatory"] is True
    assert ctx["failing_run"]["mean_reading"] == pytest.approx(40.5, abs=0.01)
    assert ctx["failing_run"]["requirement_value"] == pytest.approx(50.0, abs=0.01)
    assert ctx["failing_run"]["result_margin_pct"] == pytest.approx(-19.00, abs=0.01)
    assert ctx["lot"]["cert_status"] == "REJECTED"
    assert ctx["lot"]["disposition"] == "QUARANTINED"

    sku = read_sku(ctx["sku"]["id"])
    body = validate_error(
        api_client.release_production_lot(
            ctx["lot"]["id"], release_payload(sku["version"]), PP
        ),
        ApiErrorId.ERR_LOT_QUARANTINED,
        409,
    )
    assert body["error_id"] != ApiErrorId.ERR_LOT_NOT_CERTIFIED

    after = read_sku(ctx["sku"]["id"])
    assert after["units_received_total"] == 0
    assert after["units_on_hand"] == 0
    assert read_lot(ctx["lot"]["id"])["disposition"] == "QUARANTINED"
