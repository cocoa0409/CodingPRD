"""Yeast propagation: the pitch advisory, vessel turnover spacing, and gate order."""
import pytest

from test_helpers import (
    add_malt_line,
    add_spot_hop_line,
    confirm_order,
    create_brewer,
    create_malt_product,
    create_order,
    create_recipe,
    create_released_lot,
    create_strain,
    create_variety,
    get_brewer,
    make_brewer_headers,
    pin_clock,
    set_credit_limit,
    validate_error,
    validate_paginated,
    validate_success,
)


@pytest.fixture
def pilot_batch():
    """A 1.0 bbl, 5.00-Plato ale on a bench whose smallest run is 20 litres."""
    pin_clock()
    brewer = create_brewer(name="Pilot House Brewing", credit_limit_cents=5000000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    strain = create_strain()
    product = create_malt_product()
    recipe = create_recipe(brewer["id"], product["id"], strain["id"],
                           name="Pilot Ale", batch_volume_bbl=1.0,
                           original_gravity_plato=5.00,
                           target_color_lovibond=2.50, target_extract_pct=80.00,
                           target_protein_pct=11.00,
                           requested_pitch_rate_million_cells_per_ml_per_plato=0.75,
                           adjunct_pct=0.0)
    return {"brewer": brewer, "strain": strain, "product": product,
            "recipe": recipe}


def test_tiny_batch_slurry_is_lifted_to_the_bench_minimum_after_the_safety_factor(
        api, pilot_batch):
    """0.470 L of slurry scales to 0.541 L and is then raised to the 20.0 L floor.

    PRD §3.7: "`propagation_volume_l` applies a safety factor and then clamps to
    the bench: take `recommended_slurry_l` multiplied by 1.15, rounded half up to
    three decimal places; raise the result to `min_batch_l` if it falls below that
    floor; and then lower it to `vessel_max_l` if it exceeds that ceiling."

    Design: Difficulty/combinatorial_formula/pitch_advisory_nested_clamp_over_decayed_viability_mode_a
    """
    world = pilot_batch
    job = validate_success(api.create_propagation_job(
        {"brewer_id": world["brewer"]["id"], "recipe_id": world["recipe"]["id"],
         "yeast_strain_id": world["strain"]["id"],
         "pitch_date": "2026-08-08T00:00:00Z"},
        make_brewer_headers(world["brewer"]["id"])), expected_status=201)

    assert job["recommended_slurry_l"] == pytest.approx(0.470, abs=0.0005), (
        "440.06 cells over 1.2 * 0.78 viability over 1000, got "
        f"{job['recommended_slurry_l']}")
    assert job["propagation_volume_l"] == pytest.approx(20.0, abs=0.0005), (
        "the 0.541 L safety-scaled figure is below the 20.0 L bench minimum, got "
        f"{job['propagation_volume_l']}")
    assert job["propagation_volume_l"] != pytest.approx(0.541, abs=0.0005), (
        "0.541 would mean the min_batch_l floor was never applied")
    assert job["status"] == "REQUESTED", (
        f"an accepted request lands in REQUESTED, got {job['status']}")


def test_required_cells_and_advice_come_from_the_ale_rate_and_decayed_viability(
        api, pilot_batch):
    """A 7-day wait decays 0.92 to 0.78, and 0.75 matches the ale recommendation.

    PRD §3.7: "the viability fraction is the strain's `viability_pct_at_ship`
    divided by 100, less 0.02 for each whole waiting day, but never allowed below
    a hard floor of 0.50"

    Design: Difficulty/combinatorial_formula/pitch_advisory_nested_clamp_over_decayed_viability_mode_a
    """
    world = pilot_batch
    job = validate_success(api.create_propagation_job(
        {"brewer_id": world["brewer"]["id"], "recipe_id": world["recipe"]["id"],
         "yeast_strain_id": world["strain"]["id"],
         "pitch_date": "2026-08-08T00:00:00Z"},
        make_brewer_headers(world["brewer"]["id"])), expected_status=201)

    assert job["recommended_pitch_rate_million_cells_per_ml_per_plato"] == \
        pytest.approx(0.75, abs=0.0005), (
        "an ALE strain is pitched at 0.75, got "
        f"{job['recommended_pitch_rate_million_cells_per_ml_per_plato']}")
    assert job["required_cells_billion"] == pytest.approx(440.06, abs=0.005), (
        "0.75 * 5.00 * (1.0 * 117.348) = 440.055 rounds to 440.06, got "
        f"{job['required_cells_billion']}")
    assert job["pitch_rate_advice"] == "OPTIMAL", (
        "the recipe asked for exactly the recommended rate, got "
        f"{job['pitch_rate_advice']}")


@pytest.fixture
def vessel_queue():
    """A 30 bbl ale recipe on a strain whose vessel turns over in 7 whole days."""
    pin_clock()
    brewer = create_brewer(name="Vessel Queue Brewing",
                           credit_limit_cents=5000000, cold_chain_certified=True,
                           legacy_trailing_lbs=0)
    strain = create_strain()
    product = create_malt_product()
    recipe = create_recipe(brewer["id"], product["id"], strain["id"],
                           name="House Ale", batch_volume_bbl=30.0,
                           original_gravity_plato=12.50,
                           target_color_lovibond=2.50, target_extract_pct=80.00,
                           target_protein_pct=11.00,
                           requested_pitch_rate_million_cells_per_ml_per_plato=0.75,
                           adjunct_pct=0.0)
    return {"brewer": brewer, "strain": strain, "recipe": recipe}


def _job_payload(world, pitch_date):
    return {"brewer_id": world["brewer"]["id"],
            "recipe_id": world["recipe"]["id"],
            "yeast_strain_id": world["strain"]["id"],
            "pitch_date": pitch_date}


def test_a_pitch_date_strictly_closer_than_the_lead_time_is_refused(
        api, vessel_queue):
    """A five-day gap on one strain cannot share the propagation vessel.

    PRD §3.7: "No other job on the same `yeast_strain_id` whose `status` is
    `REQUESTED`, `PROPAGATING` or `READY` may have a `pitch_date` strictly closer
    than `propagation_lead_time_days` whole days to the requested date"

    Design: Difficulty/resource_temporal_overlap/propagation_slot_gap_measured_in_whole_days_inclusive_at_lead_time
    """
    world = vessel_queue
    headers = make_brewer_headers(world["brewer"]["id"])
    first = validate_success(api.create_propagation_job(
        _job_payload(world, "2026-08-20T00:00:00Z"), headers),
        expected_status=201)
    assert first["status"] == "REQUESTED"

    clash = api.create_propagation_job(
        _job_payload(world, "2026-08-25T00:00:00Z"), headers)
    validate_error(clash, "ERR_PROPAGATION_SLOT_CONFLICT", expected_status=409)

    data, meta = validate_paginated(api.list_propagation_jobs(
        headers, params={"yeast_strain_id": world["strain"]["id"]}))
    assert meta["total_count"] == 1, (
        f"the refused request must leave no job row, got {meta['total_count']}")


def test_a_gap_of_exactly_the_lead_time_is_accepted(api, vessel_queue):
    """Seven whole days apart is permitted because the vessel has turned over.

    PRD §3.7: "a gap exactly equal to the lead time is permitted, because by then
    the propagation vessel has been turned over, and anything tighter is refused
    with `ERR_PROPAGATION_SLOT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/propagation_slot_gap_measured_in_whole_days_inclusive_at_lead_time
    """
    world = vessel_queue
    headers = make_brewer_headers(world["brewer"]["id"])
    first = validate_success(api.create_propagation_job(
        _job_payload(world, "2026-08-20T00:00:00Z"), headers),
        expected_status=201)
    third = validate_success(api.create_propagation_job(
        _job_payload(world, "2026-08-27T00:00:00Z"), headers),
        expected_status=201)

    assert third["status"] == "REQUESTED", (
        f"the exactly-at-the-gap request is accepted, got {third['status']}")
    assert first["pitch_date"].startswith("2026-08-20"), (
        f"the earlier job keeps its date, got {first['pitch_date']}")
    assert third["pitch_date"].startswith("2026-08-27"), (
        f"the later job keeps its date, got {third['pitch_date']}")

    data, meta = validate_paginated(api.list_propagation_jobs(
        headers, params={"yeast_strain_id": world["strain"]["id"]}))
    assert meta["total_count"] == 2, (
        f"both accepted jobs are on the strain, got {meta['total_count']}")


def test_viability_decay_floors_at_one_half_across_the_two_accepted_slots(
        api, vessel_queue):
    """A 19-day wait decays to 0.54 while a 26-day wait is clamped at 0.50.

    PRD §3.7: "`recommended_slurry_l` is `required_cells_billion` divided by the
    product of the strain's `cells_per_ml_slurry_billion` and the viability
    fraction, then divided by 1000, rounded half up to three decimal places."

    Design: Difficulty/resource_temporal_overlap/propagation_slot_gap_measured_in_whole_days_inclusive_at_lead_time
    """
    world = vessel_queue
    headers = make_brewer_headers(world["brewer"]["id"])
    first = validate_success(api.create_propagation_job(
        _job_payload(world, "2026-08-20T00:00:00Z"), headers),
        expected_status=201)
    third = validate_success(api.create_propagation_job(
        _job_payload(world, "2026-08-27T00:00:00Z"), headers),
        expected_status=201)

    assert first["required_cells_billion"] == pytest.approx(33004.13, abs=0.005), (
        "0.75 * 12.50 * (30.0 * 117.348) = 33004.125 rounds to 33004.13, got "
        f"{first['required_cells_billion']}")
    assert first["recommended_slurry_l"] == pytest.approx(50.932, abs=0.0005), (
        "a 19-day wait decays viability to 0.54, got "
        f"{first['recommended_slurry_l']}")
    assert third["recommended_slurry_l"] == pytest.approx(55.007, abs=0.0005), (
        "a 26-day wait would decay to 0.40 but the 0.50 floor holds, got "
        f"{third['recommended_slurry_l']}")


@pytest.fixture
def held_brewer_with_mismatched_strain():
    """A brewer on credit HOLD at 168.38 percent, plus a recipe on the wrong strain.

    The 168,380-cent confirmed order supplies the exposure; the credit limit is
    squeezed to 100,000 afterwards so the posture flips without the confirmation
    itself being refused.
    """
    pin_clock()
    brewer = create_brewer(name="Crosswire Brewing", credit_limit_cents=200000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    ale = create_strain()
    lager = create_strain(strain_code="W-34-70", name="Frisian Lager",
                          fermentation_type="LAGER",
                          propagation_lead_time_days=10,
                          list_price_cents_per_l=1350.00)
    product = create_malt_product()
    lot = create_released_lot(product["id"], quantity_lbs=20000)
    variety = create_variety()
    recipe = create_recipe(brewer["id"], product["id"], ale["id"],
                           name="Cellar Ale", batch_volume_bbl=30.0,
                           original_gravity_plato=12.50,
                           target_color_lovibond=2.50, target_extract_pct=80.00,
                           target_protein_pct=11.00,
                           requested_pitch_rate_million_cells_per_ml_per_plato=0.75,
                           adjunct_pct=0.0)
    order = create_order(brewer["id"],
                         requested_ship_date="2026-09-20T00:00:00Z",
                         purchase_order_ref="PO-9001")
    add_malt_line(order["id"], brewer["id"], lot["id"], 1000)
    add_spot_hop_line(order["id"], brewer["id"], variety["id"], 880)
    order = confirm_order(order["id"], brewer["id"])
    brewer = set_credit_limit(brewer["id"], 100000)
    return {"brewer": brewer, "ale": ale, "lager": lager, "recipe": recipe,
            "order": order}


def test_strain_recipe_mismatch_is_reported_ahead_of_the_brewer_credit_hold(
        api, held_brewer_with_mismatched_strain):
    """A referential disagreement outranks the fiscal gate on the same request.

    PRD §2.8: "**Credit and money** (priorities 44–47): fiscal checks fire last,
    so a request that is both fiscally and structurally invalid always reports the
    structural problem."

    Design: Difficulty/priority_pair_validation_conflict/referential_mismatch_outranks_brewer_credit_hold_on_propagation_request
    """
    world = held_brewer_with_mismatched_strain
    assert world["brewer"]["credit_status"] == "HOLD", (
        "the setup must actually put the brewer on hold, got "
        f"{world['brewer']['credit_status']}")

    response = api.create_propagation_job(
        {"brewer_id": world["brewer"]["id"], "recipe_id": world["recipe"]["id"],
         "yeast_strain_id": world["lager"]["id"],
         "pitch_date": "2026-08-20T00:00:00Z"},
        make_brewer_headers(world["brewer"]["id"]))

    error = validate_error(response, "ERR_STRAIN_RECIPE_MISMATCH",
                           expected_status=422)
    assert error["error_id"] != "ERR_BREWER_CREDIT_HOLD", (
        "the fiscal gate must not pre-empt the referential one")
    assert response.status_code != 402, (
        "402 would mean the credit hold was reported instead of the mismatch")


def test_the_mismatched_propagation_request_creates_no_job_row(
        api, held_brewer_with_mismatched_strain):
    """The refused request leaves the strain's queue empty.

    PRD §3.7: "The job's `yeast_strain_id` must equal the named recipe's own
    `yeast_strain_id`, and the recipe's `brewer_id` must equal the job's
    `brewer_id`; either mismatch is refused with `ERR_STRAIN_RECIPE_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/referential_mismatch_outranks_brewer_credit_hold_on_propagation_request
    """
    world = held_brewer_with_mismatched_strain
    headers = make_brewer_headers(world["brewer"]["id"])
    response = api.create_propagation_job(
        {"brewer_id": world["brewer"]["id"], "recipe_id": world["recipe"]["id"],
         "yeast_strain_id": world["lager"]["id"],
         "pitch_date": "2026-08-20T00:00:00Z"}, headers)
    validate_error(response, "ERR_STRAIN_RECIPE_MISMATCH", expected_status=422)

    data, meta = validate_paginated(api.list_propagation_jobs(
        headers, params={"brewer_id": world["brewer"]["id"]}))
    assert meta["total_count"] == 0, (
        f"no propagation job may be created, got {meta['total_count']}")

    brewer = get_brewer(world["brewer"]["id"])
    assert brewer["credit_utilization_pct"] == pytest.approx(168.38, abs=0.005), (
        "168380 cents of exposure against a 100000-cent limit, got "
        f"{brewer['credit_utilization_pct']}")
