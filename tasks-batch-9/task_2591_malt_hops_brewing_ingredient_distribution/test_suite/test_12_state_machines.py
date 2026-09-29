"""Declared transitions: malt lot quality, the propagation bench, offer supersession."""
import pytest

from test_helpers import (
    AM_HEADERS,
    ANALYST_HEADERS,
    ANALYST_USER_ID,
    RELEASER_USER_ID,
    WH_HEADERS,
    analyse_lot,
    api_client,
    contract_version,
    create_brewer,
    create_job,
    create_lot,
    create_malt_product,
    create_passed_lot,
    create_program,
    create_recipe,
    create_released_lot,
    create_strain,
    create_variety,
    create_contract,
    make_brewer_headers,
    make_warehouse_operator_headers,
    pin_clock,
    report_harvest,
    validate_error,
    validate_paginated,
    validate_success,
)

THIRD_OPERATOR_ID = "qa-analyst-3"
THIRD_OPERATOR_HEADERS = make_warehouse_operator_headers(THIRD_OPERATOR_ID)

CONFORMING_SHEET = {
    "color_lovibond": 2.60,
    "extract_pct": 79.90,
    "moisture_pct": 4.20,
    "protein_pct": 11.10,
    "diastatic_power": 95.00,
}
REVISED_SHEET = {
    "color_lovibond": 3.00,
    "extract_pct": 79.00,
    "moisture_pct": 4.50,
    "protein_pct": 11.50,
    "diastatic_power": 90.00,
}


@pytest.fixture
def base_malt_product():
    """A BASE pale ale malt with a 5.0 moisture ceiling and a 60.0 enzyme floor."""
    pin_clock()
    return create_malt_product()


def test_a_freshly_received_lot_carries_no_analysis_and_its_whole_quantity(
        api, base_malt_product):
    """RECEIVED with five null figures, and available_lbs equal to the 5000 received.

    PRD §3.6: "The lot lands in `status` `RECEIVED` with `analysis_count` 0, all
    five analysis figures — `color_lovibond`, `extract_pct`, `moisture_pct`,
    `protein_pct` and `diastatic_power` — null, `quarantine_reason`,
    `analyzed_by_user_id` and `released_by_user_id` all null, `committed_lbs` 0
    and `available_lbs` equal to `quantity_lbs`."

    PRD §3.6: "An optional `received_at` records the warehouse receipt timestamp;
    when omitted it defaults to the current logical clock."

    Design: Corner/state_machines/malt_lot_is_born_received_with_no_analysis_on_file
    """
    lot = create_lot(base_malt_product["id"], quantity_lbs=5000,
                     lot_code="LOT-IS-1")
    assert lot["status"] == "RECEIVED", (
        f"a received lot is not PASSED, got {lot['status']}")
    assert lot["analysis_count"] == 0, (
        f"no sheet has been filed, got {lot['analysis_count']}")
    assert lot["analyzed_by_user_id"] is None, (
        f"no analyst is recorded, got {lot['analyzed_by_user_id']}")
    assert lot["released_by_user_id"] is None, (
        f"no releaser is recorded, got {lot['released_by_user_id']}")
    assert lot["quarantine_reason"] is None, (
        f"nothing has been quarantined, got {lot['quarantine_reason']}")
    for figure in ("color_lovibond", "extract_pct", "moisture_pct",
                   "protein_pct", "diastatic_power"):
        assert lot[figure] is None, (
            f"{figure} must be null on receipt, got {lot[figure]}")
    assert lot["quantity_lbs"] == 5000, (
        f"the received poundage is 5000, got {lot['quantity_lbs']}")
    assert lot["committed_lbs"] == 0, (
        f"nothing is committed, got {lot['committed_lbs']}")
    assert lot["available_lbs"] == 5000, (
        "the whole quantity is available, not a partial figure, got "
        f"{lot['available_lbs']}")
    assert lot["received_at"].startswith("2026-08-01T00:00:00"), (
        f"received_at defaults to the logical clock, got {lot['received_at']}")
    assert lot["version"] == 1, (
        f"receipt is the first write, got {lot['version']}")


def test_the_happy_path_is_two_hops_analysed_then_released_by_another_operator(
        api, base_malt_product):
    """RECEIVED to PASSED by qa-analyst-1, then PASSED to RELEASED by qa-analyst-2.

    PRD §3.6: "The lot passes — `RECEIVED → PASSED` — when its `moisture_pct` is
    at or below the product's `max_moisture_pct` **and** either the product's
    `malt_class` is `SPECIALTY` or its `diastatic_power` is at or above the
    product's `min_diastatic_power`; passing also clears `quarantine_reason` to
    null."

    PRD §3.6: "A passed lot is released for picking by a `WarehouseOperator` with
    an optional `release_note`, moving `PASSED → RELEASED`, which is also
    terminal, and recording `released_by_user_id` as the releasing `X-User-ID`."

    Design: Corner/state_machines/malt_lot_analysis_passes_and_a_second_operator_releases_it
    """
    lot = create_lot(base_malt_product["id"], quantity_lbs=5000,
                     lot_code="LOT-VT-1")
    analysed = analyse_lot(lot["id"], **CONFORMING_SHEET)
    assert analysed["status"] == "PASSED", (
        f"a conforming sheet passes the lot, got {analysed['status']}")
    assert analysed["quarantine_reason"] is None, (
        f"passing clears the quarantine reason, got {analysed['quarantine_reason']}")

    released = validate_success(api.release_malt_lot(
        lot["id"], {"release_note": "COA on file"},
        make_warehouse_operator_headers(RELEASER_USER_ID)))
    assert released["status"] == "RELEASED", (
        f"a different operator may release it, got {released['status']}")
    assert released["color_lovibond"] == pytest.approx(2.60, abs=0.005), (
        f"the filed colour survives, got {released['color_lovibond']}")
    assert released["extract_pct"] == pytest.approx(79.90, abs=0.005), (
        f"the filed extract survives, got {released['extract_pct']}")
    assert released["moisture_pct"] == pytest.approx(4.20, abs=0.005), (
        f"the filed moisture survives, got {released['moisture_pct']}")
    assert released["protein_pct"] == pytest.approx(11.10, abs=0.005), (
        f"the filed protein survives, got {released['protein_pct']}")
    assert released["diastatic_power"] == pytest.approx(95.00, abs=0.005), (
        f"the filed enzyme figure survives, got {released['diastatic_power']}")
    assert released["analysis_count"] == 1, (
        f"exactly one sheet was filed, got {released['analysis_count']}")
    assert released["analyzed_by_user_id"] == ANALYST_USER_ID, (
        f"the analyst is qa-analyst-1, got {released['analyzed_by_user_id']}")
    assert released["released_by_user_id"] == RELEASER_USER_ID, (
        f"the releaser is qa-analyst-2, got {released['released_by_user_id']}")
    assert released["quarantine_reason"] is None, (
        f"a released lot has no quarantine reason, got {released['quarantine_reason']}")
    assert released["version"] == 3, (
        "creation plus two transitions is version 3, got "
        f"{released['version']}")
    assert released["available_lbs"] == 5000, (
        "release is a quality gate, not a commitment, got "
        f"{released['available_lbs']}")


def test_releasing_an_unanalysed_lot_reports_the_state_error_not_the_duties_error(
        api, base_malt_product):
    """Priority 14 fires before priority 20, so RECEIVED beats a null analyst id.

    PRD §2.9: "Either violation is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP
    403), evaluated at priority 20 — after the target's state precondition, so a
    release attempted on a lot that is not in a releasable status reports the
    lot-state error instead."

    Design: Corner/state_machines/releasing_an_unanalysed_lot_returns_invalid_lot_state
    """
    lot = create_lot(base_malt_product["id"], quantity_lbs=5000,
                     lot_code="LOT-PE-1")
    assert lot["analyzed_by_user_id"] is None, (
        "no analyst has been recorded, so the duties gate could never match")

    refused = api.release_malt_lot(lot["id"], {"release_note": "premature"},
                                  ANALYST_HEADERS)
    error = validate_error(refused, "ERR_INVALID_LOT_STATE", expected_status=409)
    assert error["error_id"] != "ERR_SEGREGATION_OF_DUTIES", (
        f"the state precondition is reported first, got {error['error_id']}")

    after = validate_success(api.get_malt_lot(lot["id"], WH_HEADERS))
    assert after["status"] == "RECEIVED", (
        f"the refused call did not move the lot, got {after['status']}")
    assert after["released_by_user_id"] is None, (
        f"no releaser was stamped, got {after['released_by_user_id']}")
    assert after["version"] == 1, (
        f"the refused call had no side effects, got {after['version']}")


def test_a_lot_failing_both_quality_gates_is_stamped_with_the_moisture_reason(
        api, base_malt_product):
    """5.40 moisture and 55.0 enzyme both fail, yet only moisture is reported.

    PRD §3.6: "quarantining sets `quarantine_reason` to `MOISTURE_ABOVE_MAX` or
    `DIASTATIC_POWER_BELOW_MIN`, with moisture evaluated first so that a lot
    failing both reports the moisture reason"

    Design: Corner/state_machines/quarantine_reason_reports_moisture_first_when_both_gates_fail
    """
    lot = create_lot(base_malt_product["id"], quantity_lbs=5000,
                     lot_code="LOT-SE-1")
    quarantined = analyse_lot(lot["id"], color_lovibond=2.60, extract_pct=79.90,
                              moisture_pct=5.40, protein_pct=11.10,
                              diastatic_power=55.00)
    assert quarantined["status"] == "QUARANTINED", (
        f"a doubly failing sheet quarantines the lot, got {quarantined['status']}")
    assert quarantined["quarantine_reason"] == "MOISTURE_ABOVE_MAX", (
        "moisture is evaluated first, so the enzyme reason must not win, got "
        f"{quarantined['quarantine_reason']}")
    assert quarantined["moisture_pct"] == pytest.approx(5.40, abs=0.005), (
        f"the failing moisture is persisted, got {quarantined['moisture_pct']}")
    assert quarantined["diastatic_power"] == pytest.approx(55.00, abs=0.005), (
        f"the failing enzyme figure is persisted too, got "
        f"{quarantined['diastatic_power']}")
    assert quarantined["analysis_count"] == 1, (
        "a failing sheet still counts, got "
        f"{quarantined['analysis_count']}")
    assert quarantined["analyzed_by_user_id"] == ANALYST_USER_ID, (
        f"the filing operator is recorded, got "
        f"{quarantined['analyzed_by_user_id']}")


def test_the_enzyme_floor_does_not_apply_to_a_specialty_malt(api, base_malt_product):
    """The same 55.0 diastatic power passes when the parent product is SPECIALTY.

    PRD §3.6: "`min_diastatic_power`, the diastatic power floor in degrees
    Lintner, zero or greater at two decimal places and defaulting to 60.0, which
    is enforced only for `BASE` malt because `SPECIALTY` malts are exempt from the
    enzyme requirement"

    Design: Corner/state_machines/quarantine_reason_reports_moisture_first_when_both_gates_fail
    """
    specialty = create_malt_product(sku="CARA-60", name="Caramel 60",
                                    malt_class="SPECIALTY", max_moisture_pct=5.0,
                                    min_diastatic_power=60.0)
    lot = create_lot(specialty["id"], quantity_lbs=5000, lot_code="LOT-SE-2")
    passed = analyse_lot(lot["id"], color_lovibond=2.60, extract_pct=79.90,
                         moisture_pct=4.20, protein_pct=11.10,
                         diastatic_power=55.00)
    assert passed["status"] == "PASSED", (
        f"a specialty malt is exempt from the enzyme floor, got {passed['status']}")
    assert passed["quarantine_reason"] is None, (
        f"nothing was quarantined, got {passed['quarantine_reason']}")
    assert passed["diastatic_power"] == pytest.approx(55.00, abs=0.005), (
        f"the low enzyme figure is still recorded, got {passed['diastatic_power']}")

    base_lot = create_lot(base_malt_product["id"], quantity_lbs=5000,
                          lot_code="LOT-SE-3")
    base_result = analyse_lot(base_lot["id"], color_lovibond=2.60,
                              extract_pct=79.90, moisture_pct=4.20,
                              protein_pct=11.10, diastatic_power=55.00)
    assert base_result["status"] == "QUARANTINED", (
        f"the identical sheet quarantines a BASE lot, got {base_result['status']}")
    assert base_result["quarantine_reason"] == "DIASTATIC_POWER_BELOW_MIN", (
        "with compliant moisture the enzyme reason is reported, got "
        f"{base_result['quarantine_reason']}")


def test_a_passed_lot_admits_neither_rejection_nor_retest_nor_a_second_sheet(
        api, base_malt_product):
    """Reject and retest are declared only from QUARANTINED; analysis only from RECEIVED.

    PRD §3.6: "A quarantined lot has two exits, both taken by the warehouse. A
    retest, carrying an optional `retest_reason`, moves it `QUARANTINED →
    RECEIVED` and clears `quarantine_reason` to null"

    PRD §3.6: "A rejection, which requires a `reject_reason`, moves it
    `QUARANTINED → REJECTED` and is terminal."

    PRD §3.6: "Filing against a lot in any other status is refused with
    `ERR_INVALID_LOT_STATE`."

    Design: Corner/state_machines/rejecting_a_passed_lot_is_not_a_declared_transition
    """
    passed = create_passed_lot(base_malt_product["id"], quantity_lbs=5000,
                               lot_code="LOT-IT-1", **CONFORMING_SHEET)
    assert passed["status"] == "PASSED", (
        f"the lot starts in PASSED, got {passed['status']}")

    rejected = api.reject_malt_lot(
        passed["id"], {"reject_reason": "customer changed the recipe"},
        ANALYST_HEADERS)
    validate_error(rejected, "ERR_INVALID_LOT_STATE", expected_status=409)

    retested = api.retest_malt_lot(passed["id"],
                                   {"retest_reason": "second opinion"},
                                   ANALYST_HEADERS)
    validate_error(retested, "ERR_INVALID_LOT_STATE", expected_status=409)

    resheeted = api.record_analysis(passed["id"], dict(REVISED_SHEET),
                                    ANALYST_HEADERS)
    validate_error(resheeted, "ERR_INVALID_LOT_STATE", expected_status=409)

    after = validate_success(api.get_malt_lot(passed["id"], WH_HEADERS))
    assert after["status"] == "PASSED", (
        f"none of the three refusals moved the lot, got {after['status']}")
    assert after["version"] == 2, (
        "receipt plus one analysis is version 2, got "
        f"{after['version']}")
    assert after["analysis_count"] == 1, (
        f"the refused sheet was not counted, got {after['analysis_count']}")


def test_a_released_lot_refuses_every_remaining_quality_trigger(
        api, base_malt_product):
    """RELEASED is terminal: retest, reject and a fresh sheet are all 409s.

    PRD §3.6: "A passed lot is released for picking by a `WarehouseOperator` with
    an optional `release_note`, moving `PASSED → RELEASED`, which is also
    terminal"

    Design: Corner/state_machines/released_lot_is_locked_down_against_every_quality_trigger
    """
    lot = create_released_lot(base_malt_product["id"], quantity_lbs=5000,
                              lot_code="LOT-TL-1", **CONFORMING_SHEET)
    assert lot["status"] == "RELEASED", (
        f"the lot starts in RELEASED, got {lot['status']}")
    assert lot["version"] == 3, (
        f"receipt, analysis and release make version 3, got {lot['version']}")

    validate_error(api.retest_malt_lot(lot["id"],
                                       {"retest_reason": "post-release doubt"},
                                       ANALYST_HEADERS),
                   "ERR_INVALID_LOT_STATE", expected_status=409)
    validate_error(api.reject_malt_lot(lot["id"],
                                       {"reject_reason": "post-release doubt"},
                                       ANALYST_HEADERS),
                   "ERR_INVALID_LOT_STATE", expected_status=409)
    validate_error(api.record_analysis(lot["id"], dict(REVISED_SHEET),
                                       ANALYST_HEADERS),
                   "ERR_INVALID_LOT_STATE", expected_status=409)

    after = validate_success(api.get_malt_lot(lot["id"], WH_HEADERS))
    assert after["status"] == "RELEASED", (
        f"the terminal state is intact, got {after['status']}")
    assert after["version"] == 3, (
        f"three refusals wrote nothing, got {after['version']}")
    assert after["color_lovibond"] == pytest.approx(2.60, abs=0.005), (
        "the second sheet's 3.00 was discarded, got "
        f"{after['color_lovibond']}")
    assert after["analysis_count"] == 1, (
        f"the sheet count did not advance, got {after['analysis_count']}")
    assert after["released_by_user_id"] == RELEASER_USER_ID, (
        f"the recorded releaser is unchanged, got {after['released_by_user_id']}")


def test_replaying_a_successful_release_fails_and_keeps_the_first_releaser(
        api, base_malt_product):
    """The second release by a third operator is a 409, not a silent replay.

    PRD §2.8: "**State preconditions on the target resource** (priorities 12–18):
    whether the requested transition is declared from the target's current
    status."

    Design: Corner/state_machines/second_release_of_the_same_lot_is_refused
    """
    passed = create_passed_lot(base_malt_product["id"], quantity_lbs=5000,
                               lot_code="LOT-ID-1", **CONFORMING_SHEET)
    first = validate_success(api.release_malt_lot(
        passed["id"], {"release_note": "first release"},
        make_warehouse_operator_headers(RELEASER_USER_ID)))
    assert first["status"] == "RELEASED", (
        f"the first release succeeds, got {first['status']}")

    replay = api.release_malt_lot(passed["id"],
                                 {"release_note": "replayed release"},
                                 THIRD_OPERATOR_HEADERS)
    validate_error(replay, "ERR_INVALID_LOT_STATE", expected_status=409)

    after = validate_success(api.get_malt_lot(passed["id"], WH_HEADERS))
    assert after["released_by_user_id"] == RELEASER_USER_ID, (
        "the replay must not overwrite the releaser with qa-analyst-3, got "
        f"{after['released_by_user_id']}")
    assert after["version"] == 3, (
        f"the replay left the version alone, got {after['version']}")


@pytest.fixture
def requested_propagation_job():
    """A REQUESTED job for a 30 bbl ale at 12.50 Plato, pitching 19 days out.

    The strain's lead time is 7 days, so the 2026-08-20 pitch date clears the gate
    comfortably and the wait is long enough for viability to decay measurably.
    """
    pin_clock()
    brewer = create_brewer(name="Propagation Timing Brewing",
                           credit_limit_cents=5000000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    product = create_malt_product()
    strain = create_strain()
    recipe = create_recipe(
        brewer["id"], product["id"], strain["id"], name="House Ale",
        batch_volume_bbl=30.00, original_gravity_plato=12.50,
        target_color_lovibond=2.50, target_extract_pct=80.00,
        target_protein_pct=11.00,
        requested_pitch_rate_million_cells_per_ml_per_plato=0.75,
        adjunct_pct=0.0)
    job = create_job(brewer["id"], recipe["id"], strain["id"],
                     pitch_date="2026-08-20T00:00:00Z")
    return {"brewer": brewer, "product": product, "strain": strain,
            "recipe": recipe, "job": job}


def test_the_advisory_is_computed_at_request_time_while_readiness_stays_null(
        api, requested_propagation_job):
    """33004.13 cells, 50.932 L of slurry and a 58.572 L bench run, with ready_at null.

    PRD §3.7: "An accepted request lands in `status` `REQUESTED` with `ready_at`,
    `failure_reason` and `replaces_job_id` all null, and with the advisory figures
    below computed immediately."

    PRD §3.7: "the viability fraction is the strain's `viability_pct_at_ship`
    divided by 100, less 0.02 for each whole waiting day, but never allowed below
    a hard floor of 0.50"

    Design: Corner/state_machines/propagation_start_dates_readiness_from_the_strain_lead_time
    """
    job = requested_propagation_job["job"]
    assert job["status"] == "REQUESTED", (
        f"the job starts in REQUESTED, got {job['status']}")
    assert job["ready_at"] is None, (
        "readiness is written by the start transition alone, got "
        f"{job['ready_at']}")
    assert job["failure_reason"] is None, (
        f"nothing has failed, got {job['failure_reason']}")
    assert job["replaces_job_id"] is None, (
        f"this job replaces nothing, got {job['replaces_job_id']}")
    assert job["recommended_pitch_rate_million_cells_per_ml_per_plato"] == \
        pytest.approx(0.75, abs=0.0005), (
        "an ale is pitched at 0.75, got "
        f"{job['recommended_pitch_rate_million_cells_per_ml_per_plato']}")
    assert job["required_cells_billion"] == pytest.approx(33004.13, abs=0.005), (
        "0.75 times 12.50 times 3520.44 litres is 33004.13, got "
        f"{job['required_cells_billion']}")
    assert job["recommended_slurry_l"] == pytest.approx(50.932, abs=0.0005), (
        "33004.13 over 1.2 times a 0.54 viability fraction is 50.932 L, got "
        f"{job['recommended_slurry_l']}")
    assert job["propagation_volume_l"] == pytest.approx(58.572, abs=0.0005), (
        "50.932 with the 1.15 safety factor is 58.572 L, inside the bench limits, "
        f"got {job['propagation_volume_l']}")
    assert job["pitch_rate_advice"] == "OPTIMAL", (
        "the requested 0.75 equals the recommendation, got "
        f"{job['pitch_rate_advice']}")
    assert job["version"] == 1, (
        f"the request is the first write, got {job['version']}")


def test_starting_the_bench_dates_readiness_from_the_clock_not_the_pitch_date(
        api, requested_propagation_job):
    """ready_at is 2026-08-08, the clock plus 7 days, and a READY close preserves it.

    PRD §3.7: "The warehouse starts a propagation, moving the job `REQUESTED →
    PROPAGATING` and stamping `ready_at` as the current logical clock plus the
    strain's `propagation_lead_time_days` days; `ready_at` is written by this step
    alone and by nothing in the advisory."

    PRD §3.7: "the `PROPAGATING → READY` branch clears `failure_reason` to null,
    while the `PROPAGATING → FAILED` branch records the supplied
    `failure_reason`"

    Design: Corner/state_machines/propagation_start_dates_readiness_from_the_strain_lead_time
    """
    world = requested_propagation_job
    started = validate_success(api.start_propagation(world["job"]["id"],
                                                    WH_HEADERS))
    assert started["status"] == "PROPAGATING", (
        f"the bench is running, got {started['status']}")
    assert started["ready_at"].startswith("2026-08-08T00:00:00"), (
        "readiness is the clock plus seven days, not the 2026-08-20 pitch date, "
        f"got {started['ready_at']}")

    closed = validate_success(api.complete_propagation(
        world["job"]["id"], {"outcome": "READY"}, WH_HEADERS))
    assert closed["status"] == "READY", (
        f"the propagation closes ready, got {closed['status']}")
    assert closed["failure_reason"] is None, (
        f"the READY branch clears the failure reason, got {closed['failure_reason']}")
    assert closed["ready_at"].startswith("2026-08-08T00:00:00"), (
        f"the close does not restamp readiness, got {closed['ready_at']}")
    assert closed["pitch_date"].startswith("2026-08-20T00:00:00"), (
        f"the pitch date is untouched throughout, got {closed['pitch_date']}")
    assert closed["version"] == 3, (
        f"request, start and close make version 3, got {closed['version']}")


@pytest.fixture
def shorted_contract_with_one_peer_variety():
    """A SHORTFALL_ADJUSTED Citra contract; Mosaic is the only legitimate substitute.

    An 80.00 percent harvest cuts the 5,000 lb contract to 4,000 allocated with a
    1,000 lb shortfall, which is what makes it eligible for an offer at all.
    """
    pin_clock()
    brewer = create_brewer(name="Supersede Offer Brewing",
                           credit_limit_cents=5000000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    program = create_program(crop_year=2026)
    citra = create_variety()
    mosaic = create_variety(variety_code="MOSAIC", name="Mosaic",
                            alpha_acid_target_pct=12.00,
                            spot_price_cents_per_lb=450.00)
    contract = create_contract(brewer["id"], citra["id"], program["id"],
                               contracted_lbs=5000, price_per_lb_cents=285.50,
                               delivery_window_start="2026-09-01T00:00:00Z",
                               delivery_window_end="2026-12-31T00:00:00Z")
    report_harvest(program["id"], harvest_yield_pct=80.00,
                   reported_note="crop down a fifth")
    contract = validate_success(
        api_client.get_hop_contract(contract["id"], AM_HEADERS))
    return {"brewer": brewer, "program": program, "citra": citra,
            "mosaic": mosaic, "contract": contract}


def open_offer(api, contract_id, **payload):
    """Open an offer carrying a freshly read contract version."""
    body = {"expected_hop_contract_version": contract_version(contract_id)}
    body.update(payload)
    return api.create_substitution_offer(contract_id, body, AM_HEADERS)


def test_an_auto_ranked_offer_snapshots_the_only_peers_price_and_alpha_delta(
        api, shorted_contract_with_one_peer_variety):
    """Mosaic is picked at its own 450.00 spot price with a 0.50 alpha delta.

    PRD §3.4: "The first candidate in that order is selected, its
    `spot_price_cents_per_lb` is snapshotted onto the offer as
    `offered_price_cents_per_lb`, and `selection_mode` is recorded as
    `AUTO_RANKED`."

    PRD §3.4: "In either mode the offer records `alpha_acid_delta_pct` against the
    shorted variety and lands in `status` `OPEN` with `responded_at` and
    `created_contract_id` null."

    Design: Corner/state_machines/a_newer_substitution_offer_supersedes_the_open_one
    """
    world = shorted_contract_with_one_peer_variety
    assert world["contract"]["status"] == "SHORTFALL_ADJUSTED", (
        f"only a shorted contract is eligible, got {world['contract']['status']}")
    assert world["contract"]["shortfall_lbs"] == 1000, (
        f"5000 less 4000 allocated is 1000 short, got "
        f"{world['contract']['shortfall_lbs']}")

    offer = validate_success(open_offer(api, world["contract"]["id"],
                                        selection_mode="AUTO_RANKED",
                                        offered_lbs=600),
                             expected_status=201)
    assert offer["status"] == "OPEN", (
        f"a new offer lands OPEN, got {offer['status']}")
    assert offer["selection_mode"] == "AUTO_RANKED", (
        f"the ranking mode is recorded, got {offer['selection_mode']}")
    assert offer["substitute_variety_id"] == world["mosaic"]["id"], (
        "Mosaic is the only peer in the group, got "
        f"{offer['substitute_variety_id']}")
    assert offer["offered_lbs"] == 600, (
        f"the caller's poundage is honoured, got {offer['offered_lbs']}")
    assert offer["offered_price_cents_per_lb"] == pytest.approx(450.00, abs=0.005), (
        "the winner's spot price is snapshotted, got "
        f"{offer['offered_price_cents_per_lb']}")
    assert offer["alpha_acid_delta_pct"] == pytest.approx(0.50, abs=0.005), (
        f"12.50 against 12.00 is a 0.50 delta, got {offer['alpha_acid_delta_pct']}")
    assert offer["responded_at"] is None, (
        f"nobody has answered yet, got {offer['responded_at']}")
    assert offer["created_contract_id"] is None, (
        f"no contract has been minted, got {offer['created_contract_id']}")


def test_a_second_offer_supersedes_the_first_without_drawing_any_poundage(
        api, shorted_contract_with_one_peer_variety):
    """The EXPLICIT follow-up retires the AUTO_RANKED offer and moves no inventory.

    PRD §3.4: "Creating it also transitions any prior `OPEN` offer on the same
    contract `OPEN → SUPERSEDED`, incrementing that offer's `version`, and
    increments the shorted contract's own `version`."

    PRD §3.4: "Under `EXPLICIT`, the caller supplies `substitute_variety_id` and
    `offered_price_cents_per_lb` directly and no ranking runs, but the
    candidate-pool membership test still applies in full"

    Design: Corner/state_machines/a_newer_substitution_offer_supersedes_the_open_one
    """
    world = shorted_contract_with_one_peer_variety
    contract_id = world["contract"]["id"]
    first = validate_success(open_offer(api, contract_id,
                                        selection_mode="AUTO_RANKED",
                                        offered_lbs=600),
                             expected_status=201)

    second = validate_success(
        open_offer(api, contract_id, selection_mode="EXPLICIT", offered_lbs=1000,
                   substitute_variety_id=world["mosaic"]["id"],
                   offered_price_cents_per_lb=430.00),
        expected_status=201)
    assert second["status"] == "OPEN", (
        f"the newer offer is open, got {second['status']}")
    assert second["selection_mode"] == "EXPLICIT", (
        f"no ranking ran, got {second['selection_mode']}")
    assert second["offered_price_cents_per_lb"] == pytest.approx(430.00, abs=0.005), (
        "the caller's own price is kept, got "
        f"{second['offered_price_cents_per_lb']}")
    assert second["alpha_acid_delta_pct"] == pytest.approx(0.50, abs=0.005), (
        "the delta is still computed under EXPLICIT, got "
        f"{second['alpha_acid_delta_pct']}")

    retired = validate_success(api.get_substitution_offer(first["id"], AM_HEADERS))
    assert retired["status"] == "SUPERSEDED", (
        f"the prior open offer is retired, got {retired['status']}")
    assert retired["responded_at"] is None, (
        f"superseding is not a response, got {retired['responded_at']}")
    assert retired["created_contract_id"] is None, (
        f"nor does it mint a contract, got {retired['created_contract_id']}")

    mosaic = validate_success(api.get_hop_variety(world["mosaic"]["id"],
                                                  AM_HEADERS))
    assert mosaic["available_spot_lbs"] == 20000, (
        "no poundage moves until a brewer accepts, got "
        f"{mosaic['available_spot_lbs']}")

    contract = validate_success(api.get_hop_contract(contract_id, AM_HEADERS))
    assert contract["status"] == "SHORTFALL_ADJUSTED", (
        f"two offers are not a state change, got {contract['status']}")
    assert contract["allocated_lbs"] == 4000, (
        f"the allocation is untouched, got {contract['allocated_lbs']}")
    assert contract["shortfall_lbs"] == 1000, (
        f"the shortfall is untouched, got {contract['shortfall_lbs']}")
    assert contract["substitution_covered_lbs"] == 0, (
        "nothing is covered by an unanswered offer, got "
        f"{contract['substitution_covered_lbs']}")

    _, meta = validate_paginated(api.list_substitution_offers(
        AM_HEADERS, params={"hop_contract_id": contract_id}))
    assert meta["total_count"] == 2, (
        f"both offer rows are retained, got {meta['total_count']}")
    open_rows, open_meta = validate_paginated(api.list_substitution_offers(
        AM_HEADERS, params={"hop_contract_id": contract_id, "status": "OPEN"}))
    assert open_meta["total_count"] == 1, (
        f"exactly one offer is still open, got {open_meta['total_count']}")
    assert open_rows[0]["id"] == second["id"], (
        f"the survivor is the newer offer, got {open_rows[0]['id']}")


@pytest.fixture
def open_offer_covering_the_whole_shortfall(api, shorted_contract_with_one_peer_variety):
    """One OPEN AUTO_RANKED offer of 1,000 lbs of Mosaic at 450.00 against the shortfall."""
    world = shorted_contract_with_one_peer_variety
    world["offer"] = validate_success(
        open_offer(api, world["contract"]["id"], selection_mode="AUTO_RANKED",
                   offered_lbs=1000),
        expected_status=201)
    return world


def test_accepting_mints_a_spot_hold_contract_and_draws_the_substitute_pool(
        api, open_offer_covering_the_whole_shortfall):
    """One acceptance reconciles the new contract, the floor stock and the coverage figure.

    PRD §3.4: "Otherwise the system mints a fresh `SPOT_HOLD` contract on the
    substitute variety inside the shorted contract's own `crop_year_program_id`,
    with `contracted_lbs` equal to `offered_lbs`, `price_per_lb_cents` equal to
    `offered_price_cents_per_lb`, and `status` `ACTIVE`, and records the new
    contract in the offer's `created_contract_id`; it reduces the substitute
    variety's `available_spot_lbs` by `offered_lbs`; and it adds `offered_lbs` to
    the shorted contract's `substitution_covered_lbs`"

    PRD §3.4: "Either decision stamps `responded_at` with the current logical
    clock and increments the offer's `version`."

    Design: Corner/state_machines/accepting_an_offer_mints_a_contract_and_draws_the_substitute_pool
    """
    world = open_offer_covering_the_whole_shortfall
    brewer_headers = make_brewer_headers(world["brewer"]["id"])
    answered = validate_success(api.respond_to_offer(
        world["offer"]["id"],
        {"decision": "ACCEPT", "response_note": "Mosaic will do"},
        brewer_headers))
    assert answered["status"] == "ACCEPTED", (
        f"the offer is accepted, got {answered['status']}")
    assert answered["responded_at"].startswith("2026-08-01T00:00:00"), (
        f"the response is stamped with the clock, got {answered['responded_at']}")
    assert answered["created_contract_id"] is not None, (
        "acceptance mints a contract, got "
        f"{answered['created_contract_id']}")

    minted = validate_success(api.get_hop_contract(
        answered["created_contract_id"], AM_HEADERS))
    assert minted["variety_id"] == world["mosaic"]["id"], (
        f"the new contract is on the substitute, got {minted['variety_id']}")
    assert minted["contract_type"] == "SPOT_HOLD", (
        f"a substitute is held on the spot market, got {minted['contract_type']}")
    assert minted["contracted_lbs"] == 1000, (
        f"the offered poundage becomes the contract, got {minted['contracted_lbs']}")
    assert minted["price_per_lb_cents"] == pytest.approx(450.00, abs=0.005), (
        f"the offered price carries over, got {minted['price_per_lb_cents']}")
    assert minted["crop_year_program_id"] == world["program"]["id"], (
        "the new contract sits in the same crop year, got "
        f"{minted['crop_year_program_id']}")
    assert minted["status"] == "ACTIVE", (
        f"the minted contract is live, got {minted['status']}")
    assert minted["allocated_lbs"] == 1000, (
        f"all 1000 lbs are allocated, got {minted['allocated_lbs']}")
    assert minted["committed_lbs"] == 0, (
        f"nothing is committed yet, got {minted['committed_lbs']}")
    assert minted["remaining_lbs"] == 1000, (
        f"the whole poundage remains, got {minted['remaining_lbs']}")

    mosaic = validate_success(api.get_hop_variety(world["mosaic"]["id"],
                                                  AM_HEADERS))
    assert mosaic["available_spot_lbs"] == 19000, (
        "exactly the offered 1000 lbs was drawn, got "
        f"{mosaic['available_spot_lbs']}")

    shorted = validate_success(api.get_hop_contract(world["contract"]["id"],
                                                    AM_HEADERS))
    assert shorted["substitution_covered_lbs"] == 1000, (
        f"the coverage is booked, got {shorted['substitution_covered_lbs']}")
    assert shorted["shortfall_lbs"] == 1000, (
        "the shortfall was covered, not erased, got "
        f"{shorted['shortfall_lbs']}")
    assert shorted["allocated_lbs"] == 4000, (
        f"the allocation is unmoved, got {shorted['allocated_lbs']}")
    assert shorted["status"] == "SHORTFALL_ADJUSTED", (
        "acceptance is not a state change on the shorted contract, got "
        f"{shorted['status']}")

    _, meta = validate_paginated(api.list_hop_contracts(
        AM_HEADERS, params={"brewer_id": world["brewer"]["id"]}))
    assert meta["total_count"] == 2, (
        f"the brewery now holds two contracts, got {meta['total_count']}")


def test_answering_an_accepted_offer_again_is_refused_and_repeats_no_draw(
        api, open_offer_covering_the_whole_shortfall):
    """The replayed response is a 409 and Mosaic's floor stock stays at 19,000.

    PRD §3.4: "An offer that is already `ACCEPTED`, `DECLINED` or `SUPERSEDED`
    cannot be answered again and the attempt is refused with
    `ERR_INVALID_OFFER_STATE`."

    Design: Corner/state_machines/accepting_an_offer_mints_a_contract_and_draws_the_substitute_pool
    """
    world = open_offer_covering_the_whole_shortfall
    brewer_headers = make_brewer_headers(world["brewer"]["id"])
    validate_success(api.respond_to_offer(
        world["offer"]["id"], {"decision": "ACCEPT"}, brewer_headers))

    replay = api.respond_to_offer(world["offer"]["id"],
                                 {"decision": "DECLINE"}, brewer_headers)
    validate_error(replay, "ERR_INVALID_OFFER_STATE", expected_status=409)

    offer = validate_success(api.get_substitution_offer(world["offer"]["id"],
                                                        AM_HEADERS))
    assert offer["status"] == "ACCEPTED", (
        f"the refused replay did not flip the decision, got {offer['status']}")

    mosaic = validate_success(api.get_hop_variety(world["mosaic"]["id"],
                                                  AM_HEADERS))
    assert mosaic["available_spot_lbs"] == 19000, (
        f"the draw does not repeat, got {mosaic['available_spot_lbs']}")

    _, meta = validate_paginated(api.list_hop_contracts(
        AM_HEADERS, params={"brewer_id": world["brewer"]["id"]}))
    assert meta["total_count"] == 2, (
        f"no second contract was minted, got {meta['total_count']}")
