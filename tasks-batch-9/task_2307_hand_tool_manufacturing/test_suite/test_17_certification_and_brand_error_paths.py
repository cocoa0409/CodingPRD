"""The channel hardness margin, the idempotency of release, a non-mandatory
failure that blocks certification without quarantining anything, and the
suspended posture that keeps a certified pack off the shelf."""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_specimen_ledger,
    assert_unit_ledger,
    certify_lot,
    confirm_report,
    create_report,
    dismiss_report,
    read_lot,
    read_pack,
    read_sku,
    read_test_run,
    release_payload,
    schedule_test_run,
    setup_certified_sku_pack,
    setup_lot_ready_for_certification,
    submit_results,
    validate_error,
    validate_paginated,
    validate_success,
    void_payload,
)

CM = TEST_USERS["channel_manager_headers"]
PP = TEST_USERS["production_planner_headers"]
QE = TEST_USERS["quality_engineer_headers"]
BP = TEST_USERS["brand_protection_analyst_headers"]

FLOOR_HARDNESS = (50.0, 50.4)
LATE_HARDNESS_SLOT = ("2026-08-09T08:00:00Z", "2026-08-09T12:00:00Z")
EIGHT_HIGH_READINGS = (53.0, 53.0, 53.0, 53.0, 53.0, 53.0, 53.0, 53.0)
DURABILITY_SLOT = ("2026-08-09T08:00:00Z", "2026-08-09T18:00:00Z")
FAILING_CYCLES = (4000.0, 4200.0)
STRONG_SIGHTING = {"evidence_grade": "STRONG", "unit_estimate": 600}


# ---------------------------------------------------------------------------
# Passing every individual test is not the same as clearing the channel margin
# ---------------------------------------------------------------------------


def _a_wrench_lot_resting_on_the_alloy_floor():
    """All four mandatory wrench runs resolve PASSED, but the only hardness run
    pools to 50.20: above the CR_MO minimum of 50.0 and below the branded
    certification floor of 51.0."""
    return setup_lot_ready_for_certification(hardness_readings=FLOOR_HARDNESS)


def test_four_runs_that_each_pass_can_still_miss_the_branded_channel_margin():
    """Each governing statistic clears its own requirement with a positive
    margin, yet the pooled index falls a fifth of a point short of the branded
    floor and certification is refused.

    PRD §3.5: "The comparison is inclusive, so a pooled index landing exactly on
    the adjusted minimum certifies; falling short is
    `ERR_HARDNESS_MARGIN_NOT_MET`."

    Design: Corner/errors/hardness_margin_gate_then_release_idempotency_refusal
    """
    ctx = _a_wrench_lot_resting_on_the_alloy_floor()
    lot_id = ctx["lot"]["id"]
    assert ctx["lot"]["proof_torque_required_nm"] == pytest.approx(115.8, abs=0.01)

    expected_margins = {
        "HARDNESS": 0.40,
        "PROOF_TORQUE": 10.97,
        "DIMENSIONAL": 33.33,
        "SALT_SPRAY": 25.00,
    }
    for test_type, margin in expected_margins.items():
        resolved = read_test_run(ctx["runs"][test_type]["id"])
        assert resolved["status"] == "PASSED", f"{test_type} must pass its own bar"
        assert resolved["result_margin_pct"] == pytest.approx(margin, abs=0.01)

    assert read_test_run(ctx["runs"]["HARDNESS"]["id"])["mean_reading"] == pytest.approx(
        50.2, abs=0.01
    )
    assert read_lot(lot_id)["hardness_index_pooled"] == pytest.approx(50.20, abs=0.01)

    validate_error(
        api_client.certify_production_lot(lot_id, QE),
        ApiErrorId.ERR_HARDNESS_MARGIN_NOT_MET,
        422,
    )

    refused = read_lot(lot_id)
    assert refused["cert_status"] == "IN_TEST"
    assert refused["certified_at"] is None


def test_a_weightier_second_hardness_run_lifts_the_pooled_index_over_the_floor():
    """Eight specimens at 53.0 dominate the two-specimen run in the pooled index
    but count only once in the sample index, and the pooled figure is the one
    that certifies.

    PRD §3.4: "`hardness_index_pooled` is the **certification reading**: every
    raw reading from every qualifying run is pooled in `created_at` order, one
    mean is taken over the whole pool with no intermediate rounding, and that mean
    is rounded half up to two decimal places, so each run's influence is
    proportional to its `specimen_count`."

    Design: Corner/errors/hardness_margin_gate_then_release_idempotency_refusal
    """
    ctx = _a_wrench_lot_resting_on_the_alloy_floor()
    lot_id = ctx["lot"]["id"]

    second = submit_results(
        schedule_test_run(lot_id, "HARDNESS", 8, LATE_HARDNESS_SLOT)["id"], EIGHT_HIGH_READINGS
    )
    assert second["status"] == "PASSED"
    assert second["mean_reading"] == pytest.approx(53.0, abs=0.01)

    certified = certify_lot(lot_id)

    assert certified["cert_status"] == "CERTIFIED"
    assert certified["hardness_index_pooled"] == pytest.approx(52.44, abs=0.01)
    assert certified["hardness_index_sample"] == pytest.approx(51.60, abs=0.01)
    assert certified["specimens_consumed"] == 17
    assert certified["specimens_available"] == 23
    assert_specimen_ledger(certified)


def _a_certified_wrench_lot_of_five_hundred_units():
    ctx = _a_wrench_lot_resting_on_the_alloy_floor()
    submit_results(
        schedule_test_run(ctx["lot"]["id"], "HARDNESS", 8, LATE_HARDNESS_SLOT)["id"],
        EIGHT_HIGH_READINGS,
    )
    ctx["lot"] = certify_lot(ctx["lot"]["id"])
    return ctx


def test_a_released_lot_refuses_a_second_release_ahead_of_the_stale_token():
    """Banking the lot leaves the token one version behind, so the repeat release
    violates both the disposition rule and the version rule and is answered on the
    disposition.

    PRD §3.5: "Its gates run in this order: the lot must not be `QUARANTINED`
    (`ERR_LOT_QUARANTINED`); its `disposition` must be `IN_PROCESS`, so a lot
    already `RELEASED` cannot be released twice (`ERR_LOT_ALREADY_DISPOSITIONED`);
    the supplied `expected_sku_version` must equal the parent SKU's current
    `version` (`ERR_STALE_SKU_VERSION`, HTTP 412); and only then, the dossier must
    be `CERTIFIED` (`ERR_LOT_NOT_CERTIFIED`)."

    Design: Corner/errors/hardness_margin_gate_then_release_idempotency_refusal
    """
    ctx = _a_certified_wrench_lot_of_five_hundred_units()
    lot_id = ctx["lot"]["id"]
    token = read_sku(ctx["sku"]["id"])["version"]

    released = validate_success(
        api_client.release_production_lot(lot_id, release_payload(token), PP)
    )
    assert released["disposition"] == "RELEASED"

    banked = read_sku(ctx["sku"]["id"])
    assert banked["units_received_total"] == 500
    assert banked["units_on_hand"] == 500
    assert banked["version"] == token + 1
    assert_unit_ledger(banked)

    body = validate_error(
        api_client.release_production_lot(lot_id, release_payload(token), PP),
        ApiErrorId.ERR_LOT_ALREADY_DISPOSITIONED,
        409,
    )
    assert body["error_id"] != ApiErrorId.ERR_STALE_SKU_VERSION
    assert read_sku(ctx["sku"]["id"])["units_received_total"] == 500


# ---------------------------------------------------------------------------
# A failure outside the battery blocks the dossier without quarantining the lot
# ---------------------------------------------------------------------------


def _a_wrench_lot_carrying_a_failed_durability_run():
    """Mechanism cycling is mandatory for a plier and optional for a wrench, so
    this failure resolves the run and nothing else."""
    ctx = setup_lot_ready_for_certification()
    ctx["durability"] = submit_results(
        schedule_test_run(ctx["lot"]["id"], "MECHANISM_CYCLE", 2, DURABILITY_SLOT)["id"],
        FAILING_CYCLES,
    )
    return ctx


def test_a_failure_outside_the_wrench_battery_fires_no_quarantine_cascade():
    """The weakest specimen turns four thousand cycles against a five-thousand
    requirement, and the twenty-percent shortfall costs the lot neither its dossier
    nor its disposition.

    PRD §3.4: "A failed run that is **not** mandatory, or a mandatory failure on a
    lot whose dossier is not `IN_TEST`, resolves the run alone and fires no
    cascade."

    Design: Corner/errors/non_mandatory_failure_blocks_certification_without_quarantine
    """
    ctx = _a_wrench_lot_carrying_a_failed_durability_run()
    run = ctx["durability"]

    assert run["mandatory"] is False
    assert run["requirement_value"] == pytest.approx(5000, abs=0.01)
    assert run["status"] == "FAILED"
    assert run["governing_statistic"] == pytest.approx(4000.0, abs=0.01)
    assert run["result_margin_pct"] == pytest.approx(-20.00, abs=0.01)

    lot = read_lot(ctx["lot"]["id"])
    assert lot["cert_status"] == "IN_TEST"
    assert lot["disposition"] == "IN_PROCESS"
    assert lot["rework_cycle_count"] == 0
    assert lot["specimens_consumed"] == 11
    assert_specimen_ledger(lot)


def test_certification_is_refused_while_any_failed_run_sits_on_the_lot():
    """The four mandatory types all hold a passing run and the pooled index is
    comfortably over the branded floor, yet the optional failure is enough to keep
    the dossier open.

    PRD §3.5: "Next, no run on the lot may be in `FAILED` status at all, and the
    presence of one is `ERR_FAILED_TEST_PRESENT`."

    Design: Corner/errors/non_mandatory_failure_blocks_certification_without_quarantine
    """
    ctx = _a_wrench_lot_carrying_a_failed_durability_run()
    lot_id = ctx["lot"]["id"]
    assert read_lot(lot_id)["hardness_index_pooled"] == pytest.approx(52.50, abs=0.01)

    validate_error(
        api_client.certify_production_lot(lot_id, QE),
        ApiErrorId.ERR_FAILED_TEST_PRESENT,
        409,
    )

    still_open = read_lot(lot_id)
    assert still_open["cert_status"] == "IN_TEST"
    assert still_open["certified_at"] is None


def test_a_resolved_run_can_no_longer_be_retracted_by_voiding_it():
    """Voiding is the compensating action of scheduling and reaches only a run
    still awaiting readings, so the failure cannot be taken back off the lot.

    PRD §3.3: "The run must still be `SCHEDULED`, otherwise
    `ERR_TEST_RUN_STATE_INVALID`."

    Design: Corner/errors/non_mandatory_failure_blocks_certification_without_quarantine
    """
    ctx = _a_wrench_lot_carrying_a_failed_durability_run()
    run_id = ctx["durability"]["id"]

    validate_error(
        api_client.void_test_run(
            run_id, void_payload(void_reason="Attempt to retract the failed durability run"), QE
        ),
        ApiErrorId.ERR_TEST_RUN_STATE_INVALID,
        409,
    )

    assert read_test_run(run_id)["status"] == "FAILED"
    lot = read_lot(ctx["lot"]["id"])
    assert lot["specimens_consumed"] == 11
    assert lot["specimens_available"] == 29
    assert_specimen_ledger(lot)


# ---------------------------------------------------------------------------
# A suspended member keeps a properly certified pack off the shelf
# ---------------------------------------------------------------------------


def _a_certified_member_in_a_draft_display_pack():
    return setup_certified_sku_pack()


def test_two_confirmed_strong_sightings_suspend_a_sku_while_a_dismissal_adds_nothing():
    """Fifty frozen points apiece take the score to the cap in two confirmations,
    and the third sighting leaves no trace once it is dismissed.

    PRD §3.9: "Link two re-rolls the SKU's brand-protection figures over the
    reports on that SKU whose status is `CONFIRMED` — `OPEN` and `DISMISSED`
    reports contribute nothing: `confirmed_counterfeit_count` becomes the number of
    such reports and `brand_risk_score` becomes the sum of their frozen
    `risk_points`, capped at 100."

    Design: Corner/errors/suspended_posture_on_a_certified_member_blocks_pack_approval
    """
    ctx = _a_certified_member_in_a_draft_display_pack()
    sku_id = ctx["sku"]["id"]
    first = create_report(sku_id, seller_handle="seller-a", **STRONG_SIGHTING)
    second = create_report(sku_id, seller_handle="seller-b", **STRONG_SIGHTING)
    third = create_report(sku_id, seller_handle="seller-c", **STRONG_SIGHTING)
    assert first["risk_points"] == 50

    assert confirm_report(first["id"])["status"] == "CONFIRMED"
    assert read_sku(sku_id)["warranty_posture"] == "RESTRICTED"

    confirm_report(second["id"])
    assert dismiss_report(third["id"])["status"] == "DISMISSED"

    suspended = read_sku(sku_id)
    assert suspended["brand_risk_score"] == 100
    assert suspended["warranty_posture"] == "SUSPENDED"
    assert suspended["confirmed_counterfeit_count"] == 2

    _, confirmed = validate_paginated(
        api_client.list_sku_counterfeit_reports(sku_id, BP, params={"status": "CONFIRMED"})
    )
    assert confirmed["total_count"] == 2


def test_a_suspended_member_blocks_pack_approval_behind_a_satisfied_certificate():
    """The member has a genuinely certified lot, so the certification gate passes
    and the refusal is attributable to the brand posture alone.

    PRD §3.6: "No member SKU may have a `warranty_posture` of `SUSPENDED`,
    otherwise `ERR_MEMBER_SKU_RESTRICTED`; a merely `RESTRICTED` posture does not
    block packaging."

    Design: Corner/errors/suspended_posture_on_a_certified_member_blocks_pack_approval
    """
    ctx = _a_certified_member_in_a_draft_display_pack()
    sku_id = ctx["sku"]["id"]
    assert ctx["lot"]["cert_status"] == "CERTIFIED"

    for handle in ("seller-a", "seller-b"):
        confirm_report(create_report(sku_id, seller_handle=handle, **STRONG_SIGHTING)["id"])
    assert read_sku(sku_id)["warranty_posture"] == "SUSPENDED"

    body = validate_error(
        api_client.approve_pack_configuration(ctx["pack"]["id"], CM),
        ApiErrorId.ERR_MEMBER_SKU_RESTRICTED,
        409,
    )
    assert body["error_id"] != ApiErrorId.ERR_MEMBER_SKU_NOT_CERTIFIED

    unapproved = read_pack(ctx["pack"]["id"])
    assert unapproved["status"] == "DRAFT"
    assert unapproved["pack_total_cents"] == 0
    assert unapproved["distinct_member_count"] == 1
