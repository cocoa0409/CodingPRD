"""Action endpoints, catalogue reads and the collection filters that expose them."""
import pytest

from test_helpers import (
    ALLOC_1_HEADERS,
    ALLOC_2_HEADERS,
    AM_HEADERS,
    CM_HEADERS,
    NON_EXISTENT_UUID,
    WH_HEADERS,
    add_malt_line,
    add_spot_hop_line,
    analyse_lot,
    api_client,
    approve_credit,
    cancel_order,
    complete_propagation,
    confirm_order,
    contract_version,
    create_brewer,
    create_contract,
    create_job,
    create_lot,
    create_malt_product,
    create_order,
    create_program,
    create_recipe,
    create_released_lot,
    create_strain,
    create_variety,
    create_zone,
    declare_default,
    get_brewer,
    get_order,
    hold_credit,
    make_brewer_headers,
    pick_order,
    pin_clock,
    report_harvest,
    stage_shipment,
    validate_error,
    validate_paginated,
    validate_success,
)


@pytest.fixture
def defaulted_contract_priced_by_liquidation():
    """A 5,000 lb contract defaulted before any harvest, on a 400,000 cent limit."""
    pin_clock()
    defaulter = create_brewer(name="Walkaway Brewing", credit_limit_cents=400000,
                              cold_chain_certified=True, legacy_trailing_lbs=0)
    buyer = create_brewer(name="Opportunist Brewing",
                          credit_limit_cents=5000000,
                          cold_chain_certified=True, legacy_trailing_lbs=0)
    program = create_program(crop_year=2026)
    variety = create_variety()
    contract = create_contract(defaulter["id"], variety["id"], program["id"],
                               contracted_lbs=5000, price_per_lb_cents=250.00)
    defaulted = declare_default(contract["id"],
                               default_reason="brewery exited the style",
                               headers=ALLOC_1_HEADERS)
    return {"defaulter": defaulter, "buyer": buyer, "program": program,
            "variety": variety, "contract": defaulted}


def test_the_desk_that_declared_the_default_may_not_resell_it(
        api, defaulted_contract_priced_by_liquidation):
    """Liquidated damages land on the defaulter, and three gates guard the resale.

    PRD §3.5: "Under `LIQUIDATED`, `settlement_damages_cents` is the defaulted
    poundage multiplied by `price_per_lb_cents`, multiplied by 35 and divided by
    100, rounded half up to whole cents, with no reference to spot at all."

    PRD §3.5: "the acting `X-User-ID` must differ from the contract's
    `defaulted_by_user_id`, refused otherwise with `ERR_SEGREGATION_OF_DUTIES`"

    Design: Corner/endpoints/resale_credit_is_capped_at_the_settlement_it_offsets
    """
    world = defaulted_contract_priced_by_liquidation
    contract, defaulter, buyer = world["contract"], world["defaulter"], world["buyer"]
    assert contract["settlement_variant"] == "LIQUIDATED", (
        "the program never reported a harvest so no market reference exists, got "
        f"{contract['settlement_variant']}")
    assert contract["defaulted_lbs"] == 5000, (
        f"the whole undrawn commitment defaults, got {contract['defaulted_lbs']}")
    assert contract["settlement_damages_cents"] == 437500, (
        "5000 times 250.00 times 35 divided by 100 = 437500, got "
        f"{contract['settlement_damages_cents']}")
    assert contract["settlement_admin_fee_cents"] == 8750, (
        "437500 is under the tier threshold so the higher 2.0 percent rate applies, "
        f"got {contract['settlement_admin_fee_cents']}")
    assert contract["settlement_total_cents"] == 446250, (
        f"437500 plus 8750 = 446250, got {contract['settlement_total_cents']}")

    posture = get_brewer(defaulter["id"])
    assert posture["ar_balance_cents"] == 446250, (
        f"the settlement is invoiced to the defaulter, got "
        f"{posture['ar_balance_cents']}")
    assert posture["credit_exposure_cents"] == 446250, (
        f"with no open orders the exposure is the receivable, got "
        f"{posture['credit_exposure_cents']}")
    assert posture["credit_utilization_pct"] == pytest.approx(111.56, abs=0.005), (
        "446250 of 400000 is 111.56 percent, got "
        f"{posture['credit_utilization_pct']}")
    assert posture["credit_status"] == "HOLD", (
        f"exposure strictly over the limit is a hold, got {posture['credit_status']}")

    same_desk = api.resell_contract(contract["id"],
                                   {"buyer_brewer_id": buyer["id"],
                                    "resale_lbs": 2000,
                                    "resale_price_cents_per_lb": 60.00},
                                   ALLOC_1_HEADERS)
    validate_error(same_desk, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)

    too_much = api.resell_contract(contract["id"],
                                  {"buyer_brewer_id": buyer["id"],
                                   "resale_lbs": 5001,
                                   "resale_price_cents_per_lb": 60.00},
                                  ALLOC_2_HEADERS)
    validate_error(too_much, "ERR_RESALE_EXCEEDS_DEFAULTED_VOLUME",
                   expected_status=422)

    to_itself = api.resell_contract(contract["id"],
                                   {"buyer_brewer_id": defaulter["id"],
                                    "resale_lbs": 2000,
                                    "resale_price_cents_per_lb": 60.00},
                                   ALLOC_2_HEADERS)
    validate_error(to_itself, "ERR_RESALE_BUYER_INVALID", expected_status=422)


def test_the_resale_credit_lifts_the_hold_without_overshooting_the_receivable(
        api, defaulted_contract_priced_by_liquidation):
    """120,000 cents of proceeds is credited to the defaulter, and only once.

    PRD §3.5: "It sets `resale_credit_cents` to the lesser of
    `settlement_total_cents` and the resale proceeds — the `resale_lbs` multiplied
    by `resale_price_cents_per_lb`, rounded half up to whole cents — and subtracts
    that credit from the defaulting brewery's `ar_balance_cents`."

    Design: Corner/endpoints/resale_credit_is_capped_at_the_settlement_it_offsets
    """
    world = defaulted_contract_priced_by_liquidation
    contract, defaulter, buyer = world["contract"], world["defaulter"], world["buyer"]

    resold = validate_success(api.resell_contract(
        contract["id"], {"buyer_brewer_id": buyer["id"], "resale_lbs": 2000,
                         "resale_price_cents_per_lb": 60.00}, ALLOC_2_HEADERS))
    assert resold["status"] == "RESOLD", (
        f"the contract lands in its terminal resale state, got {resold['status']}")
    assert resold["resold_lbs"] == 2000, (
        f"2000 lbs move into the resold bucket, got {resold['resold_lbs']}")
    assert resold["defaulted_lbs"] == 3000, (
        f"and out of the defaulted bucket, got {resold['defaulted_lbs']}")
    assert resold["resale_credit_cents"] == 120000, (
        "min(446250, 2000 times 60.00) = 120000, got "
        f"{resold['resale_credit_cents']}")
    assert resold["allocated_lbs"] == 5000, (
        f"the resale never touches allocated_lbs, got {resold['allocated_lbs']}")
    buckets = (resold["remaining_lbs"] + resold["committed_lbs"]
               + resold["carried_forward_out_lbs"] + resold["defaulted_lbs"]
               + resold["resold_lbs"])
    assert buckets == 5000, (
        "0 + 0 + 0 + 3000 + 2000 must still partition the 5000 allocated pounds, "
        f"got {buckets}")

    after = get_brewer(defaulter["id"])
    assert after["ar_balance_cents"] == 326250, (
        f"446250 less the 120000 credit = 326250, got {after['ar_balance_cents']}")
    assert after["credit_utilization_pct"] == pytest.approx(81.56, abs=0.005), (
        f"326250 of 400000 is 81.56 percent, got {after['credit_utilization_pct']}")
    assert after["credit_status"] == "GOOD_STANDING", (
        "the recovery lifted the hold rather than merely easing it, got "
        f"{after['credit_status']}")

    buyer_ledger = get_brewer(buyer["id"])
    assert buyer_ledger["ar_balance_cents"] == 0, (
        "the recovery offsets the defaulter's settlement and never bills the buyer, "
        f"got {buyer_ledger['ar_balance_cents']}")

    again = api.resell_contract(contract["id"],
                               {"buyer_brewer_id": buyer["id"],
                                "resale_lbs": 1000,
                                "resale_price_cents_per_lb": 60.00},
                               ALLOC_2_HEADERS)
    validate_error(again, "ERR_INVALID_CONTRACT_STATE", expected_status=409)


@pytest.fixture
def failed_job_booked_nineteen_days_out(api):
    """A propagation for 2026-08-20 that was started and then failed on the bench."""
    pin_clock()
    brewer = create_brewer(name="Bench Retry Brewing", credit_limit_cents=5000000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    product = create_malt_product()
    strain = create_strain()
    recipe = create_recipe(brewer["id"], product["id"], strain["id"],
                          name="Retry Ale", batch_volume_bbl=30.00,
                          original_gravity_plato=12.50,
                          requested_pitch_rate_million_cells_per_ml_per_plato=0.75)
    job = create_job(brewer["id"], recipe["id"], strain["id"],
                    pitch_date="2026-08-20T00:00:00Z")
    validate_success(api.start_propagation(job["id"], WH_HEADERS))
    failed = complete_propagation(job["id"], outcome="FAILED",
                                 failure_reason="contamination in the propagator")
    return {"brewer": brewer, "strain": strain, "recipe": recipe,
            "requested": job, "failed": failed}


def test_the_original_booking_is_costed_against_nineteen_days_of_decay(
        api, failed_job_booked_nineteen_days_out):
    """0.92 less 19 times 0.02 is 0.54, which sets the slurry the bench then loses.

    PRD §3.7: "the viability fraction is the strain's `viability_pct_at_ship`
    divided by 100, less 0.02 for each whole waiting day, but never allowed below a
    hard floor of 0.50"

    PRD §3.7: "The warehouse starts a propagation, moving the job `REQUESTED →
    PROPAGATING` and stamping `ready_at` as the current logical clock plus the
    strain's `propagation_lead_time_days` days"

    Design: Corner/endpoints/requeue_rebooks_a_failed_job_and_rescores_the_advisory
    """
    world = failed_job_booked_nineteen_days_out
    booked, failed = world["requested"], world["failed"]
    assert booked["required_cells_billion"] == pytest.approx(33004.13, abs=0.005), (
        "0.75 times 12.50 times 30.0 times 117.348 = 33004.13, got "
        f"{booked['required_cells_billion']}")
    assert booked["recommended_slurry_l"] == pytest.approx(50.932, abs=0.0005), (
        "33004.13 divided by 1.2 times 0.54, then by 1000, is 50.932, got "
        f"{booked['recommended_slurry_l']}")
    assert booked["propagation_volume_l"] == pytest.approx(58.572, abs=0.0005), (
        "50.932 times the 1.15 safety factor is 58.572, inside the 20.0 to 2000.0 "
        f"bench band, got {booked['propagation_volume_l']}")
    assert failed["ready_at"].startswith("2026-08-08T00:00:00"), (
        "the clock plus 7 days of bench time, not the pitch date less the lead "
        f"time, got {failed['ready_at']}")
    assert failed["status"] == "FAILED", (
        f"the bench run failed, got {failed['status']}")
    assert failed["failure_reason"] == "contamination in the propagator", (
        f"and the stated cause is kept, got {failed['failure_reason']}")


def test_a_requeue_too_close_to_the_clock_leaves_the_failure_intact(
        api, failed_job_booked_nineteen_days_out):
    """Six days out misses a seven-day bench, and the refusal writes nothing.

    PRD §3.7: "The same two temporal gates that guarded the original request are
    re-applied to `new_pitch_date`: it must be at least
    `propagation_lead_time_days` whole days after the current logical clock, and it
    must not sit strictly closer than that lead time to another live job on the
    same strain."

    Design: Corner/endpoints/requeue_rebooks_a_failed_job_and_rescores_the_advisory
    """
    world = failed_job_booked_nineteen_days_out
    job_id = world["failed"]["id"]
    refused = api.requeue_propagation(
        job_id, {"new_pitch_date": "2026-08-07T00:00:00Z"}, WH_HEADERS)
    validate_error(refused, "ERR_INSUFFICIENT_PROPAGATION_LEAD_TIME",
                   expected_status=422)

    still = validate_success(api.get_propagation_job(job_id, WH_HEADERS))
    assert still["status"] == "FAILED", (
        f"the refused re-book does not move the job, got {still['status']}")
    assert still["failure_reason"] == "contamination in the propagator", (
        f"nor clear the recorded cause, got {still['failure_reason']}")
    assert still["version"] == 3, (
        "create, start and complete are the only three writes so far, got version "
        f"{still['version']}")


def test_a_far_future_rebook_clamps_on_the_viability_floor_and_asks_for_more(
        api, failed_job_booked_nineteen_days_out):
    """Twenty-four days would decay to 0.44, so the 0.50 floor lifts the slurry.

    PRD §3.7: "A requeue supplies a `new_pitch_date` and moves the job `FAILED →
    REQUESTED`, setting `pitch_date` to the new date and clearing both
    `failure_reason` and `ready_at` back to null."

    PRD §3.7: "a slurry sitting long enough to decay past that floor is still
    costed at the floor and never lower"

    Design: Corner/endpoints/requeue_rebooks_a_failed_job_and_rescores_the_advisory
    """
    world = failed_job_booked_nineteen_days_out
    job_id = world["failed"]["id"]
    rebooked = validate_success(api.requeue_propagation(
        job_id, {"new_pitch_date": "2026-08-25T00:00:00Z"}, WH_HEADERS))
    assert rebooked["status"] == "REQUESTED", (
        f"the job returns to the queue, got {rebooked['status']}")
    assert rebooked["pitch_date"].startswith("2026-08-25T00:00:00"), (
        f"on the new date, got {rebooked['pitch_date']}")
    assert rebooked["ready_at"] is None, (
        f"the old bench stamp is cleared, got {rebooked['ready_at']}")
    assert rebooked["failure_reason"] is None, (
        f"as is the old failure, got {rebooked['failure_reason']}")
    assert rebooked["recommended_slurry_l"] == pytest.approx(55.007, abs=0.0005), (
        "33004.13 divided by 1.2 times the clamped 0.50, then by 1000, is 55.007 "
        f"and so above the original 50.932, got {rebooked['recommended_slurry_l']}")
    assert rebooked["propagation_volume_l"] == pytest.approx(63.258, abs=0.0005), (
        f"55.007 times 1.15 is 63.258, got {rebooked['propagation_volume_l']}")
    assert rebooked["version"] == 4, (
        "the requeue is the fourth write and revises the job in place, got version "
        f"{rebooked['version']}")
    assert rebooked["replaces_job_id"] is None, (
        "a re-book is not a replacement job, got "
        f"{rebooked['replaces_job_id']}")

    read_back = validate_success(api.get_propagation_job(job_id, WH_HEADERS))
    assert read_back["status"] == "REQUESTED", (
        f"the read agrees with the write, got {read_back['status']}")
    assert read_back["recommended_pitch_rate_million_cells_per_ml_per_plato"] == \
        pytest.approx(0.75, abs=0.0005), (
        "an ALE strain is pitched at the 0.75 reference rate, got "
        f"{read_back['recommended_pitch_rate_million_cells_per_ml_per_plato']}")
    assert read_back["pitch_rate_advice"] == "OPTIMAL", (
        "the brewery asked for exactly the recommendation, got "
        f"{read_back['pitch_rate_advice']}")


@pytest.fixture
def two_picked_reefer_orders_and_one_slot():
    """A single-pallet zone, two PICKED reefer orders, and load A already staged."""
    pin_clock()
    brewer = create_brewer(name="One Slot Brewing", credit_limit_cents=5000000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    variety = create_variety()
    zone = create_zone(zone_code="Z2", temp_setpoint_c=2.0, capacity_pallets=1,
                      tolerance_c=2.0)
    orders = []
    for ref in ("PO-RH-A", "PO-RH-B"):
        order = create_order(brewer["id"],
                            requested_ship_date="2026-09-18T00:00:00Z",
                            purchase_order_ref=ref)
        add_spot_hop_line(order["id"], brewer["id"], variety["id"], 880)
        confirm_order(order["id"], brewer["id"])
        approve_credit(order["id"], note="within limit")
        pick_order(order["id"])
        orders.append(order)
    load_a = stage_shipment(orders[0]["id"], zone["id"], pallet_count=1,
                           stage_from="2026-08-01T08:00:00Z",
                           stage_until="2026-08-01T16:00:00Z")
    return {"brewer": brewer, "variety": variety, "zone": zone,
            "order_a": orders[0], "order_b": orders[1], "load_a": load_a}


def test_a_credit_hold_frees_the_slot_for_the_next_load(
        api, two_picked_reefer_orders_and_one_slot):
    """Holding load A drops it out of the occupancy set, so load B is admitted.

    PRD §3.8: "`HOLD` moves `credit_status` `PENDING_REVIEW → ON_HOLD` or `APPROVED
    → ON_HOLD`, and additionally freezes the dock: every reefer load of this order
    in `STAGED` moves to `HELD`, releasing its `pallet_count` from its zone's
    `occupied_pallets`."

    Design: Corner/endpoints/release_hold_re_tests_zone_capacity_before_restaging
    """
    world = two_picked_reefer_orders_and_one_slot
    held_order = hold_credit(world["order_a"]["id"], note="ledger review")
    assert held_order["credit_status"] == "ON_HOLD", (
        f"the desk freezes order A, got {held_order['credit_status']}")
    assert held_order["fulfillment_status"] == "PICKED", (
        "the credit dimension moves independently of fulfilment, got "
        f"{held_order['fulfillment_status']}")

    load_a = validate_success(api.get_shipment(world["load_a"]["id"], WH_HEADERS))
    assert load_a["status"] == "HELD", (
        f"and the load with it, got {load_a['status']}")

    load_b = stage_shipment(world["order_b"]["id"], world["zone"]["id"],
                           pallet_count=1, stage_from="2026-08-01T08:00:00Z",
                           stage_until="2026-08-01T16:00:00Z")
    assert load_b["status"] == "STAGED", (
        "the identical window is admissible now that the slot is free, got "
        f"{load_b['status']}")
    assert load_b["cold_storage_zone_id"] == world["zone"]["id"], (
        f"in the same single-pallet zone, got {load_b['cold_storage_zone_id']}")


def test_releasing_a_hold_re_runs_the_admission_sweep_and_can_be_refused(
        api, two_picked_reefer_orders_and_one_slot):
    """Approving the credit does not restage the load, and the slot is not held back.

    PRD §3.9: "A load moved `STAGED → HELD` by a credit hold is returned by the
    credit desk, moving `HELD → STAGED`; this requires the owning order's
    `credit_status` to be `APPROVED` again and re-runs the zone admission test over
    the load's original window, so a release can be refused with
    `ERR_ZONE_CAPACITY_EXCEEDED` if the zone filled up while the load was held."

    Design: Corner/endpoints/release_hold_re_tests_zone_capacity_before_restaging
    """
    world = two_picked_reefer_orders_and_one_slot
    load_a_id = world["load_a"]["id"]
    hold_credit(world["order_a"]["id"], note="ledger review")
    load_b = stage_shipment(world["order_b"]["id"], world["zone"]["id"],
                           pallet_count=1, stage_from="2026-08-01T08:00:00Z",
                           stage_until="2026-08-01T16:00:00Z")

    reapproved = approve_credit(world["order_a"]["id"], note="ledger cleared")
    assert reapproved["credit_status"] == "APPROVED", (
        f"order A is good again, got {reapproved['credit_status']}")
    assert validate_success(api.get_shipment(load_a_id,
                                            WH_HEADERS))["status"] == "HELD", (
        "but the load does not restage itself on the approval alone")

    refused = api.release_hold(load_a_id, CM_HEADERS)
    validate_error(refused, "ERR_ZONE_CAPACITY_EXCEEDED", expected_status=409)
    assert validate_success(api.get_shipment(load_a_id,
                                            WH_HEADERS))["status"] == "HELD", (
        "the refused release leaves the load held")

    _, held_meta = validate_paginated(api.list_shipments(
        WH_HEADERS, params={"status": "HELD"}))
    assert held_meta["total_count"] == 1, (
        f"only load A is held, got {held_meta['total_count']}")
    _, zone_meta = validate_paginated(api.list_shipments(
        WH_HEADERS, params={"cold_storage_zone_id": world["zone"]["id"]}))
    assert zone_meta["total_count"] == 2, (
        "both loads live in the zone's history regardless of status, got "
        f"{zone_meta['total_count']}")

    cancel_order(world["order_b"]["id"], cancel_reason="brewery took delivery late")
    superseded = validate_success(api.get_shipment(load_b["id"], WH_HEADERS))
    assert superseded["status"] == "SUPERSEDED", (
        f"cancelling order B releases its pallet, got {superseded['status']}")

    restaged = validate_success(api.release_hold(load_a_id, CM_HEADERS))
    assert restaged["status"] == "STAGED", (
        f"the retried release now passes the sweep, got {restaged['status']}")

    twice = api.release_hold(load_a_id, CM_HEADERS)
    validate_error(twice, "ERR_INVALID_SHIPMENT_STATE", expected_status=409)


def test_the_program_listing_composes_its_filter_with_limit_and_offset(api):
    """status=OPEN with limit 1 and offset 1 lands on the second open program.

    PRD §2.3: "Unless a specific listing states otherwise, list results are ordered
    by `created_at` ascending. Two listings are called out explicitly elsewhere
    because they read differently: the crop-year program listing is presented newest
    `crop_year` first"

    PRD §2.3: "Both are echoed in the envelope's `meta` object alongside
    `total_count` (the number of rows matching the filter before pagination is
    applied) and `has_more` (true when rows remain beyond the current page)."

    Design: Corner/endpoints/crop_year_program_listing_filters_by_status_and_paginates
    """
    pin_clock()
    program_26 = create_program(crop_year=2026)
    create_program(crop_year=2027)
    program_28 = create_program(crop_year=2028)
    report_harvest(program_26["id"], harvest_yield_pct=90.00,
                  reported_note="crop came in short")

    rows, meta = validate_paginated(api.list_crop_year_programs(AM_HEADERS))
    assert meta["total_count"] == 3, (
        f"three programs exist, got {meta['total_count']}")
    assert meta["limit"] == 10, (
        f"the omitted limit defaults to 10, got {meta['limit']}")
    assert meta["has_more"] is False, (
        f"three rows fit inside one default page, got {meta['has_more']}")
    assert rows[0]["crop_year"] == 2028, (
        f"the program listing leads with the newest crop year, got "
        f"{rows[0]['crop_year']}")

    _, open_meta = validate_paginated(api.list_crop_year_programs(
        AM_HEADERS, params={"status": "OPEN"}))
    assert open_meta["total_count"] == 2, (
        f"the harvested 2026 program is filtered out, got "
        f"{open_meta['total_count']}")

    page, page_meta = validate_paginated(api.list_crop_year_programs(
        AM_HEADERS, params={"status": "OPEN", "limit": 1, "offset": 1}))
    assert page_meta["total_count"] == 2, (
        "total_count still reports the filtered population rather than the page, "
        f"got {page_meta['total_count']}")
    assert page_meta["has_more"] is False, (
        f"the skipped row plus this one exhaust the filter, got "
        f"{page_meta['has_more']}")
    assert len(page) == 1 and page[0]["crop_year"] == 2027, (
        "the second open program under newest-first is 2027, never 2028, got "
        f"{[row['crop_year'] for row in page]}")

    year, year_meta = validate_paginated(api.list_crop_year_programs(
        AM_HEADERS, params={"crop_year": 2026}))
    assert year_meta["total_count"] == 1, (
        f"crop years are unique across programs, got {year_meta['total_count']}")
    assert year[0]["status"] == "HARVEST_REPORTED", (
        f"and that one has reported its crop, got {year[0]['status']}")

    one = validate_success(api.get_crop_year_program(program_28["id"], AM_HEADERS))
    assert one["crop_year"] == 2028 and one["status"] == "OPEN", (
        f"the single fetch agrees with the listing, got {one['crop_year']} in "
        f"{one['status']}")
    assert one["allocatable_pool_lbs"] == 0, (
        "a freshly opened program has an empty pool rather than a null one, got "
        f"{one['allocatable_pool_lbs']}")
    assert one["harvest_yield_pct"] is None, (
        f"and no reported yield at all, got {one['harvest_yield_pct']}")

    brewer = create_brewer(name="Catalogue Reader Brewing",
                          credit_limit_cents=5000000,
                          cold_chain_certified=True, legacy_trailing_lbs=0)
    _, brewer_meta = validate_paginated(api.list_crop_year_programs(
        make_brewer_headers(brewer["id"])))
    assert brewer_meta["total_count"] == 3, (
        "crop-year programs are not brewer-scoped, so a brewery sees the whole "
        f"catalogue, got {brewer_meta['total_count']}")


def test_a_superseded_offer_stays_queryable_with_its_original_poundage(api):
    """Both generations of the offer survive; only the live one answers status=OPEN.

    PRD §3.4: "Creating it also transitions any prior `OPEN` offer on the same
    contract `OPEN → SUPERSEDED`, incrementing that offer's `version`, and increments
    the shorted contract's own `version`."

    PRD §2.4: "Substitution offers may be filtered by `hop_contract_id`,
    `substitute_variety_id`, `created_contract_id` and `status`."

    Design: Corner/endpoints/substitution_offers_are_listable_per_contract_with_history
    """
    pin_clock()
    brewer = create_brewer(name="Offer History Brewing",
                          credit_limit_cents=5000000,
                          cold_chain_certified=True, legacy_trailing_lbs=0)
    program = create_program(crop_year=2026)
    citra = create_variety()
    mosaic = create_variety(variety_code="MOSAIC", name="Mosaic",
                           substitution_group="AROMA_HIGH_ALPHA",
                           alpha_acid_target_pct=11.50,
                           spot_price_cents_per_lb=48.00)
    contract = create_contract(brewer["id"], citra["id"], program["id"],
                              contracted_lbs=10000, price_per_lb_cents=250.00)
    report_harvest(program["id"], harvest_yield_pct=60.00,
                  reported_note="sixty percent crop")
    shorted = validate_success(api.get_hop_contract(contract["id"], AM_HEADERS))
    assert shorted["status"] == "SHORTFALL_ADJUSTED", (
        f"a 60 percent crop cuts the contract back, got {shorted['status']}")
    assert shorted["shortfall_lbs"] == 4000, (
        f"10000 less the 6000 allocated leaves 4000 short, got "
        f"{shorted['shortfall_lbs']}")
    assert shorted["allocated_lbs"] == 6000, (
        f"and 6000 allocated, got {shorted['allocated_lbs']}")

    offer_1 = validate_success(api.create_substitution_offer(
        contract["id"], {"expected_hop_contract_version": shorted["version"],
                         "selection_mode": "EXPLICIT",
                         "substitute_variety_id": mosaic["id"],
                         "offered_lbs": 2000,
                         "offered_price_cents_per_lb": 48.00}, AM_HEADERS),
        expected_status=201)
    offer_2 = validate_success(api.create_substitution_offer(
        contract["id"],
        {"expected_hop_contract_version": contract_version(contract["id"]),
         "selection_mode": "EXPLICIT", "substitute_variety_id": mosaic["id"],
         "offered_lbs": 1500, "offered_price_cents_per_lb": 48.00}, AM_HEADERS),
        expected_status=201)

    by_contract, contract_meta = validate_paginated(api.list_substitution_offers(
        AM_HEADERS, params={"hop_contract_id": contract["id"]}))
    assert contract_meta["total_count"] == 2, (
        f"the contract's offer history holds both generations, got "
        f"{contract_meta['total_count']}")
    assert by_contract[0]["id"] == offer_1["id"], (
        f"ordered created_at ascending, the first offer leads, got "
        f"{by_contract[0]['id']}")

    live, live_meta = validate_paginated(api.list_substitution_offers(
        AM_HEADERS, params={"hop_contract_id": contract["id"], "status": "OPEN"}))
    assert live_meta["total_count"] == 1, (
        f"only one offer is live, got {live_meta['total_count']}")
    assert live[0]["id"] == offer_2["id"], (
        f"and it is the newer one, got {live[0]['id']}")
    assert live[0]["offered_lbs"] == 1500, (
        f"carrying its own poundage, got {live[0]['offered_lbs']}")

    old = validate_success(api.get_substitution_offer(offer_1["id"], AM_HEADERS))
    assert old["status"] == "SUPERSEDED", (
        f"the first offer is superseded rather than deleted, got {old['status']}")
    assert old["offered_lbs"] == 2000, (
        f"and its poundage is never rewritten, got {old['offered_lbs']}")
    assert old["selection_mode"] == "EXPLICIT", (
        f"nor its selection mode, got {old['selection_mode']}")

    _, variety_meta = validate_paginated(api.list_substitution_offers(
        AM_HEADERS, params={"substitute_variety_id": mosaic["id"]}))
    assert variety_meta["total_count"] == 2, (
        f"both offers name the same substitute, got {variety_meta['total_count']}")

    unchanged = validate_success(api.get_hop_contract(contract["id"], AM_HEADERS))
    assert unchanged["substitution_covered_lbs"] == 0, (
        f"an unaccepted offer covers nothing, got "
        f"{unchanged['substitution_covered_lbs']}")
    assert unchanged["shortfall_lbs"] == 4000, (
        f"so the shortfall stands, got {unchanged['shortfall_lbs']}")


@pytest.fixture
def two_orders_sharing_a_lot_with_one_line_removed():
    """Order A keeps a malt line after its hop line is removed; order B holds another."""
    pin_clock()
    brewer = create_brewer(name="Line Query Brewing", credit_limit_cents=5000000,
                          cold_chain_certified=True, legacy_trailing_lbs=0)
    variety = create_variety()
    product = create_malt_product()
    lot = create_released_lot(product["id"], quantity_lbs=5000,
                            lot_code="LOT-LQ-1", diastatic_power=95.00)
    brewer_headers = make_brewer_headers(brewer["id"])
    order_a = create_order(brewer["id"],
                          requested_ship_date="2026-09-16T00:00:00Z",
                          purchase_order_ref="PO-LQ-A")
    hop_line = add_spot_hop_line(order_a["id"], brewer["id"], variety["id"], 880)
    malt_line_a = add_malt_line(order_a["id"], brewer["id"], lot["id"], 1000)
    trimmed_order = validate_success(api_client.remove_order_line(
        order_a["id"], hop_line["id"], brewer_headers))
    order_b = create_order(brewer["id"],
                          requested_ship_date="2026-09-16T00:00:00Z",
                          purchase_order_ref="PO-LQ-B")
    malt_line_b = add_malt_line(order_b["id"], brewer["id"], lot["id"], 1000)
    return {"brewer": brewer, "lot": lot, "order_a": trimmed_order,
            "order_b": order_b, "hop_line": hop_line,
            "malt_line_a": malt_line_a, "malt_line_b": malt_line_b}


def test_the_line_listing_reaches_removed_rows_and_crosses_orders(
        api, two_orders_sharing_a_lot_with_one_line_removed):
    """A removed line is filtered out by status but still counted unfiltered.

    PRD §2.4: "Order lines may be filtered by `sales_order_id`,
    `hop_contract_id`, `malt_lot_id`, `yeast_propagation_job_id`, `hop_variety_id`,
    `item_type`, `allocation_source` and `status`, and this listing is the only
    discovery channel for lines that a cascade trimmed or quarantined."

    Design: Corner/endpoints/order_lines_are_queryable_across_orders_and_after_removal
    """
    world = two_orders_sharing_a_lot_with_one_line_removed
    order_a, lot = world["order_a"], world["lot"]

    _, all_meta = validate_paginated(api.list_order_lines(
        WH_HEADERS, params={"sales_order_id": order_a["id"]}))
    assert all_meta["total_count"] == 2, (
        "the removed hop line is retained rather than erased, got "
        f"{all_meta['total_count']}")

    live, live_meta = validate_paginated(api.list_order_lines(
        WH_HEADERS, params={"sales_order_id": order_a["id"], "status": "OPEN"}))
    assert live_meta["total_count"] == 1, (
        f"only the malt line is still open, got {live_meta['total_count']}")
    assert live[0]["id"] == world["malt_line_a"]["id"], (
        f"and it is the one that survived, got {live[0]['id']}")

    _, lot_meta = validate_paginated(api.list_order_lines(
        WH_HEADERS, params={"malt_lot_id": lot["id"]}))
    assert lot_meta["total_count"] == 2, (
        "the lot filter reaches lines sitting on two different orders, got "
        f"{lot_meta['total_count']}")

    _, gone_meta = validate_paginated(api.list_order_lines(
        WH_HEADERS, params={"item_type": "HOP", "status": "REMOVED"}))
    assert gone_meta["total_count"] == 1, (
        f"the two filters compose on the same request, got "
        f"{gone_meta['total_count']}")


def test_the_rollup_excludes_the_removed_line_that_the_listing_still_returns(
        api, two_orders_sharing_a_lot_with_one_line_removed):
    """The order forgets the hop line's cold chain while the line itself remembers it.

    PRD §3.8: "The input set for all four is the order's lines whose `status` is
    `OPEN` or `TRIMMED` — lines in `CANCELLED_SHORTFALL`, `REMOVED` or `QUARANTINED`
    are excluded, so a quarantined line silently stops contributing to the order's
    totals."

    Design: Corner/endpoints/order_lines_are_queryable_across_orders_and_after_removal
    """
    world = two_orders_sharing_a_lot_with_one_line_removed
    brewer_headers = make_brewer_headers(world["brewer"]["id"])

    removed = validate_success(api.get_order_line(world["hop_line"]["id"],
                                                brewer_headers))
    assert removed["status"] == "REMOVED", (
        f"the line is fetchable in its terminal state, got {removed['status']}")
    assert removed["quantity"] == pytest.approx(880, abs=0.0005), (
        f"with its original poundage, got {removed['quantity']}")
    assert removed["cold_chain_required"] is True, (
        f"and its own refrigeration flag, got {removed['cold_chain_required']}")

    order_a = get_order(world["order_a"]["id"], brewer_headers)
    assert order_a["requires_cold_chain"] is False, (
        "the roll-up no longer sees a reefer line, got "
        f"{order_a['requires_cold_chain']}")
    assert order_a["line_count"] == 1, (
        f"nor counts the removed one, got {order_a['line_count']}")

    malt_line = validate_success(api.get_order_line(world["malt_line_a"]["id"],
                                                   brewer_headers))
    assert malt_line["pallet_break"] is True, (
        "1000 lbs is not an exact multiple of the 2200 lb pallet, got "
        f"{malt_line['pallet_break']}")


@pytest.fixture
def one_recipe_each_for_two_breweries():
    """Two breweries with a recipe apiece, sharing one malt product and one strain."""
    pin_clock()
    brewer_a = create_brewer(name="Recipe Owner Brewing",
                            credit_limit_cents=5000000,
                            cold_chain_certified=True, legacy_trailing_lbs=0)
    brewer_b = create_brewer(name="Recipe Rival Brewing",
                            credit_limit_cents=5000000,
                            cold_chain_certified=True, legacy_trailing_lbs=0)
    product = create_malt_product()
    strain = create_strain()
    recipe_a = create_recipe(brewer_a["id"], product["id"], strain["id"],
                           name="A House Ale", batch_volume_bbl=30.00)
    recipe_b = create_recipe(brewer_b["id"], product["id"], strain["id"],
                           name="B Adjunct Lager", batch_volume_bbl=60.00,
                           adjunct_pct=20.0)
    return {"brewer_a": brewer_a, "brewer_b": brewer_b, "product": product,
            "strain": strain, "recipe_a": recipe_a, "recipe_b": recipe_b}


def test_a_brewery_reading_a_rivals_recipe_is_refused_but_reads_its_own(
        api, one_recipe_each_for_two_breweries):
    """Recipes are brewer-private, and the refusal is a scope violation not a 404.

    PRD §2.1: "a `Brewer` actor may only address contracts, orders, order lines,
    recipes, propagation jobs, substitution offers and payments belonging to the
    brewery whose `id` equals `X-User-ID`; reaching for another brewery's resource
    is refused with `ERR_BREWER_SCOPE_VIOLATION` (HTTP 403)"

    Design: Corner/endpoints/recipe_reads_are_scoped_to_the_owning_brewer
    """
    world = one_recipe_each_for_two_breweries
    owner_headers = make_brewer_headers(world["brewer_a"]["id"])

    rival = api.get_brewer_recipe(world["recipe_b"]["id"], owner_headers)
    validate_error(rival, "ERR_BREWER_SCOPE_VIOLATION", expected_status=403)

    own = validate_success(api.get_brewer_recipe(world["recipe_a"]["id"],
                                                owner_headers))
    assert own["name"] == "A House Ale", (
        f"its own recipe reads back intact, got {own['name']}")
    assert own["batch_volume_bbl"] == pytest.approx(30.00, abs=0.005), (
        f"with its brew length, got {own['batch_volume_bbl']}")
    assert own["brewer_id"] == world["brewer_a"]["id"], (
        f"and its ownership, got {own['brewer_id']}")


def test_the_desk_sees_both_recipes_and_can_filter_them_two_ways(
        api, one_recipe_each_for_two_breweries):
    """The hop desk is unscoped, so brewer_id and yeast_strain_id do the narrowing.

    PRD §2.4: "Brewer recipes may be filtered by `brewer_id`, `malt_product_id` and
    `yeast_strain_id`."

    Design: Corner/endpoints/recipe_reads_are_scoped_to_the_owning_brewer
    """
    world = one_recipe_each_for_two_breweries

    _, all_meta = validate_paginated(api.list_brewer_recipes(AM_HEADERS))
    assert all_meta["total_count"] == 2, (
        f"the desk sees both breweries' recipes, got {all_meta['total_count']}")

    rows, filtered = validate_paginated(api.list_brewer_recipes(
        AM_HEADERS, params={"brewer_id": world["brewer_b"]["id"]}))
    assert filtered["total_count"] == 1, (
        f"the brewer filter narrows to one, got {filtered['total_count']}")
    assert rows[0]["adjunct_pct"] == pytest.approx(20.0, abs=0.005), (
        f"and that one carries its adjunct share, got {rows[0]['adjunct_pct']}")

    _, strain_meta = validate_paginated(api.list_brewer_recipes(
        AM_HEADERS, params={"yeast_strain_id": world["strain"]["id"]}))
    assert strain_meta["total_count"] == 2, (
        f"both recipes pitch the same strain, got {strain_meta['total_count']}")

    _, product_meta = validate_paginated(api.list_brewer_recipes(
        AM_HEADERS, params={"malt_product_id": world["product"]["id"]}))
    assert product_meta["total_count"] == 2, (
        f"and specify the same base malt, got {product_meta['total_count']}")


def test_one_product_holds_lots_in_three_quality_states_at_once(api):
    """status=RELEASED returns only the saleable lot while the product filter keeps all three.

    PRD §3.6: "The lot is quarantined — `RECEIVED → QUARANTINED` — when its
    `moisture_pct` is strictly above `max_moisture_pct`"

    PRD §2.4: "Malt lots may be filtered by `malt_product_id` and `status`."

    Design: Corner/endpoints/malt_lot_listing_filters_by_quality_status
    """
    pin_clock()
    product = create_malt_product(max_moisture_pct=5.0)
    create_released_lot(product["id"], quantity_lbs=5000, lot_code="LOT-ML-1",
                       diastatic_power=95.00)
    lot_2 = create_lot(product["id"], quantity_lbs=4000, lot_code="LOT-ML-2")
    quarantined = analyse_lot(lot_2["id"], color_lovibond=2.60, extract_pct=79.90,
                             moisture_pct=5.60, protein_pct=11.10,
                             diastatic_power=95.00)
    assert quarantined["status"] == "QUARANTINED", (
        f"5.60 breaches the 5.0 moisture ceiling, got {quarantined['status']}")
    assert quarantined["quarantine_reason"] == "MOISTURE_ABOVE_MAX", (
        f"and names the moisture as the cause, got "
        f"{quarantined['quarantine_reason']}")
    lot_3 = create_lot(product["id"], quantity_lbs=3000, lot_code="LOT-ML-3")

    rows, product_meta = validate_paginated(api.list_malt_lots(
        WH_HEADERS, params={"malt_product_id": product["id"]}))
    assert product_meta["total_count"] == 3, (
        "all three quality states hang off one product, got "
        f"{product_meta['total_count']}")
    assert rows[0]["lot_code"] == "LOT-ML-1", (
        f"ordered created_at ascending the first receipt leads, got "
        f"{rows[0]['lot_code']}")

    released, released_meta = validate_paginated(api.list_malt_lots(
        WH_HEADERS, params={"status": "RELEASED"}))
    assert released_meta["total_count"] == 1, (
        f"only one lot is saleable, got {released_meta['total_count']}")
    assert released[0]["lot_code"] == "LOT-ML-1", (
        f"and it is the one that passed, got {released[0]['lot_code']}")

    held, held_meta = validate_paginated(api.list_malt_lots(
        WH_HEADERS, params={"status": "QUARANTINED"}))
    assert held_meta["total_count"] == 1, (
        f"one lot is held back, got {held_meta['total_count']}")
    assert held[0]["quarantine_reason"] == "MOISTURE_ABOVE_MAX", (
        f"carrying its reason into the listing, got "
        f"{held[0]['quarantine_reason']}")

    _, page_meta = validate_paginated(api.list_malt_lots(
        WH_HEADERS, params={"malt_product_id": product["id"], "limit": 2,
                            "offset": 0}))
    assert page_meta["total_count"] == 3, (
        f"the count survives the page, got {page_meta['total_count']}")
    assert page_meta["has_more"] is True, (
        f"a third row remains beyond it, got {page_meta['has_more']}")

    fresh = validate_success(api.get_malt_lot(lot_3["id"], WH_HEADERS))
    assert fresh["status"] == "RECEIVED", (
        f"the third lot is only received, got {fresh['status']}")
    assert fresh["analysis_count"] == 0, (
        f"with no sheet filed, got {fresh['analysis_count']}")
    assert fresh["available_lbs"] == 3000, (
        f"and its whole receipt uncommitted, got {fresh['available_lbs']}")

    clash = api.create_malt_lot({"malt_product_id": product["id"],
                                "lot_code": "LOT-ML-1", "quantity_lbs": 1000},
                               WH_HEADERS)
    validate_error(clash, "ERR_DUPLICATE_LOT_CODE", expected_status=409)


@pytest.fixture
def a_specialty_malt_and_a_lager_strain():
    """One SPECIALTY malt SKU and one LAGER strain, both off the default settings."""
    pin_clock()
    product = create_malt_product(sku="MUNICH-10L", name="Munich 10L",
                                 malt_class="SPECIALTY",
                                 list_price_cents_per_lb=92.75,
                                 max_moisture_pct=4.5,
                                 min_diastatic_power=35.0,
                                 pallet_quantity_lbs=2000)
    strain = create_strain(strain_code="W3470", name="Bohemian Lager",
                          fermentation_type="LAGER",
                          propagation_lead_time_days=12,
                          list_price_cents_per_l=1200.00,
                          viability_pct_at_ship=88.0,
                          cells_per_ml_slurry_billion=1.0,
                          min_batch_l=25.0, vessel_max_l=1500.0)
    return {"product": product, "strain": strain}


def test_every_catalogue_specification_field_survives_the_round_trip(
        api, a_specialty_malt_and_a_lager_strain):
    """Reference rows carry no state and no derived money, so nothing may drift.

    PRD §2.5: "`version` as an integer that starts at 1 on creation and increments
    by exactly one on every mutation of that resource"

    PRD §2.8: "each reports the not-found code for the entity it names"

    Design: Corner/endpoints/reference_catalogue_rows_read_back_exactly_as_written
    """
    world = a_specialty_malt_and_a_lager_strain
    product = validate_success(api.get_malt_product(world["product"]["id"],
                                                   WH_HEADERS))
    assert product["sku"] == "MUNICH-10L", (
        f"the stock-keeping unit reads back, got {product['sku']}")
    assert product["malt_class"] == "SPECIALTY", (
        f"as does the class, got {product['malt_class']}")
    assert product["list_price_cents_per_lb"] == pytest.approx(92.75, abs=0.005), (
        f"and the spot price, got {product['list_price_cents_per_lb']}")
    assert product["max_moisture_pct"] == pytest.approx(4.5, abs=0.005), (
        f"the moisture ceiling is not defaulted away, got "
        f"{product['max_moisture_pct']}")
    assert product["min_diastatic_power"] == pytest.approx(35.0, abs=0.005), (
        f"nor the enzyme floor, got {product['min_diastatic_power']}")
    assert product["pallet_quantity_lbs"] == 2000, (
        f"nor the pallet size the break fee reads, got "
        f"{product['pallet_quantity_lbs']}")

    strain = validate_success(api.get_yeast_strain(world["strain"]["id"],
                                                  WH_HEADERS))
    assert strain["strain_code"] == "W3470", (
        f"the laboratory code reads back, got {strain['strain_code']}")
    assert strain["fermentation_type"] == "LAGER", (
        f"as does the fermentation type, got {strain['fermentation_type']}")
    assert strain["propagation_lead_time_days"] == 12, (
        f"and the bench time, got {strain['propagation_lead_time_days']}")
    assert strain["viability_pct_at_ship"] == pytest.approx(88.0, abs=0.005), (
        f"the viability the advisory decays, got {strain['viability_pct_at_ship']}")
    assert strain["cells_per_ml_slurry_billion"] == pytest.approx(1.0, abs=0.005), (
        f"the slurry density it divides by, got "
        f"{strain['cells_per_ml_slurry_billion']}")
    assert strain["min_batch_l"] == pytest.approx(25.0, abs=0.0005), (
        f"and both bench bounds, got {strain['min_batch_l']}")
    assert strain["vessel_max_l"] == pytest.approx(1500.0, abs=0.0005), (
        f"floor before ceiling, got {strain['vessel_max_l']}")

    for row, label in ((product, "malt product"), (strain, "yeast strain")):
        assert row["version"] == 1, (
            f"the {label} has never been mutated, got version {row['version']}")
        assert row["created_at"] == row["updated_at"], (
            f"so the {label}'s audit stamps agree, got {row['created_at']} against "
            f"{row['updated_at']}")
        assert row["created_at"].startswith("2026-08-01T00:00:00"), (
            f"both reading the logical clock, got {row['created_at']}")

    missing_product = api.get_malt_product(NON_EXISTENT_UUID, WH_HEADERS)
    validate_error(missing_product, "ERR_MALT_PRODUCT_NOT_FOUND",
                   expected_status=404)
    missing_strain = api.get_yeast_strain(NON_EXISTENT_UUID, WH_HEADERS)
    validate_error(missing_strain, "ERR_YEAST_STRAIN_NOT_FOUND",
                   expected_status=404)


def test_the_lager_parameters_drive_both_the_advisory_and_the_lead_time_gate(
        api, a_specialty_malt_and_a_lager_strain):
    """A twelve-day bench refuses an eleven-day booking and pitches at double the ale rate.

    PRD §3.7: "`recommended_pitch_rate_million_cells_per_ml_per_plato` is 0.75 when
    the strain's `fermentation_type` is `ALE` and 1.50 when it is `LAGER` — lagers
    are pitched at double the ale rate."

    PRD §3.7: "The `pitch_date` must fall at least `propagation_lead_time_days`
    whole days after the current logical clock, with exactly the lead time accepted
    and anything shorter refused with `ERR_INSUFFICIENT_PROPAGATION_LEAD_TIME`."

    Design: Corner/endpoints/reference_catalogue_rows_read_back_exactly_as_written
    """
    world = a_specialty_malt_and_a_lager_strain
    brewer = create_brewer(name="Pilsner Bench Brewing",
                          credit_limit_cents=5000000,
                          cold_chain_certified=True, legacy_trailing_lbs=0)
    recipe = create_recipe(brewer["id"], world["product"]["id"],
                         world["strain"]["id"], name="Bohemian Pils",
                         batch_volume_bbl=30.00, original_gravity_plato=12.50,
                         requested_pitch_rate_million_cells_per_ml_per_plato=1.50)
    brewer_headers = make_brewer_headers(brewer["id"])

    eleven_days = api.create_propagation_job(
        {"brewer_id": brewer["id"], "recipe_id": recipe["id"],
         "yeast_strain_id": world["strain"]["id"],
         "pitch_date": "2026-08-12T00:00:00Z"}, brewer_headers)
    validate_error(eleven_days, "ERR_INSUFFICIENT_PROPAGATION_LEAD_TIME",
                   expected_status=422)

    twelve_days = validate_success(api.create_propagation_job(
        {"brewer_id": brewer["id"], "recipe_id": recipe["id"],
         "yeast_strain_id": world["strain"]["id"],
         "pitch_date": "2026-08-13T00:00:00Z"}, brewer_headers),
        expected_status=201)
    assert twelve_days["status"] == "REQUESTED", (
        f"exactly the lead time is accepted, got {twelve_days['status']}")
    assert twelve_days["recommended_pitch_rate_million_cells_per_ml_per_plato"] == \
        pytest.approx(1.50, abs=0.0005), (
        "a LAGER strain is pitched at 1.50 rather than the 0.75 ale rate, got "
        f"{twelve_days['recommended_pitch_rate_million_cells_per_ml_per_plato']}")
    assert twelve_days["pitch_rate_advice"] == "OPTIMAL", (
        "and the brewery asked for exactly that, got "
        f"{twelve_days['pitch_rate_advice']}")
