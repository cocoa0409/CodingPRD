"""The guards the mill puts in front of each write: the moisture plan the kiln was
designed for, the chamber's capacity and the charge's kiln-dry volume, the mass
balance and waste ceiling of a milling report, the bundle and ruleset rules on a
grade run, the substrate rules on an engineered lot, the shape of a prefinish
window, the redry allowance, the byproduct ledger, code uniqueness, and the
temporal and volume guards on a warranty claim."""

import pytest

from test_helpers import (
    adjudicate_claim_payload,
    allocate_receipt_payload,
    complete_milling_payload,
    create_byproduct_sale_payload,
    create_flooring_lot_payload,
    create_grade_bundle_payload,
    create_grade_run_payload,
    create_kiln_chamber_payload,
    create_prefinish_run_payload,
    create_species_profile_payload,
    create_warranty_claim_payload,
    deallocate_receipt_payload,
    finalize_lot_payload,
    record_stress_test_payload,
    request_info_payload,
    supersede_grade_run_payload,
    validate_error,
    validate_paginated,
    validate_success,
    void_lot_payload,
)
from test_helpers.fixtures import (
    ADMIN,
    BROKER,
    INSPECTOR,
    OPERATOR,
    SCHEDULER,
    SUPERVISOR,
    create_accepted_receipt,
    create_chamber,
    create_core_stock,
    create_product_line,
    create_species,
    fetch_lot_batches,
    refetch_batch,
    refetch_chamber,
    refetch_charge,
    refetch_claim,
    refetch_core_stock,
    refetch_grade_run,
    refetch_lot,
    refetch_product_line,
    refetch_receipt,
    set_logical_clock,
    setup_conditioning_charge,
    setup_draft_grade_run,
    setup_line_only_submitted_claim,
    setup_lot_with_byproduct_sale,
    setup_milled_lot,
    setup_planned_lot,
    setup_prefinish_ready,
    setup_released_charge,
    setup_scheduled_charge,
    setup_second_lot_on_charge,
    setup_second_species_receipt,
    setup_warranty_line,
)
from test_helpers.test_users import (
    CLAIM_ADJUDICATOR_USER_ID,
    CLAIM_SUBMITTER_USER_ID,
    make_warranty_adjudicator_headers,
)

# A receipt whose green moisture sits far below the schedule's design point.
DRY_RECEIPT = {
    "received_board_feet": 5000,
    "accepted_board_feet": 5000,
    "moisture_pct_at_receipt": 38.6,
    "receipt_grade": "SELECT",
    "supplier_name": "Valley Sawmill",
}

# A third receipt that lands a 9000 board-foot chamber exactly on its capacity.
EXACT_FIT_RECEIPT = {
    "received_board_feet": 3400,
    "accepted_board_feet": 3200,
    "moisture_pct_at_receipt": 44.0,
    "receipt_grade": "SELECT",
}

# The milling report for a 4000 board-foot lot: 272.50 waste against a 480.00
# ceiling.
HALF_LOT_MILLING = {
    "actual_milled_width_in": 3.190,
    "net_flooring_bf": 3200,
    "shorts_bf": 100,
    "sawdust_tons": 1.00,
    "shavings_tons": 0.50,
}

# An 8000 board-foot lot whose sawdust batch opens with exactly 10.00 tons.
TEN_TON_SAWDUST_MILLING = {
    "actual_milled_width_in": 3.190,
    "net_flooring_bf": 4500,
    "shorts_bf": 200,
    "sawdust_tons": 10.00,
    "shavings_tons": 0.00,
}


class TestMoisturePlanDeviationOnLoad:
    """A kiln schedule is designed for a green moisture band, and the load is
    checked against the wood actually in the chamber."""

    def test_a_dry_load_is_turned_away_and_a_wetter_one_goes_in(self, api):
        """PRD 3.4: "And the load's actual green moisture must be one the schedule
        was designed for: the absolute difference between the charge's
        `weighted_initial_moisture_pct` and the schedule's `initial_moisture_pct`,
        compared at one decimal place, may be at most 3.0 percentage points, or the
        load is refused with `ERR_MC_PLAN_DEVIATION`."

        PRD 2.8: "Allocation and deallocation are exact inverses: allocating a
        receipt and then deallocating it restores both `charged_green_bf` and
        `weighted_initial_moisture_pct` to the values they held before, and returns
        the receipt to `ACCEPTED` with a null `kiln_charge_id`."

        Design: Corner/validations/mc_plan_deviation_blocks_load_then_passes_within_tolerance
        """
        ctx = setup_scheduled_charge(api)
        charge_id = ctx["charge"]["id"]

        dry_receipt = create_accepted_receipt(api, ctx["species"], **DRY_RECEIPT)
        wet_receipt = create_accepted_receipt(api, ctx["species"])

        validate_success(
            api.allocate_receipt(
                charge_id, allocate_receipt_payload(dry_receipt["id"]), OPERATOR
            ),
            expected_status=200,
        )

        validate_error(
            api.load_charge(charge_id, OPERATOR),
            "ERR_MC_PLAN_DEVIATION",
            expected_status=422,
        )
        assert refetch_charge(api, charge_id)["status"] == "SCHEDULED"
        assert refetch_chamber(api, ctx["chamber"]["id"])["status"] == "AVAILABLE"

        validate_success(
            api.deallocate_receipt(
                charge_id, deallocate_receipt_payload(dry_receipt["id"]), OPERATOR
            ),
            expected_status=200,
        )
        charge = validate_success(
            api.allocate_receipt(
                charge_id, allocate_receipt_payload(wet_receipt["id"]), OPERATOR
            ),
            expected_status=200,
        )
        assert charge["charged_green_bf"] == pytest.approx(5800, abs=0.01)
        assert charge["weighted_initial_moisture_pct"] == pytest.approx(46.0, abs=0.01)

        loaded = validate_success(
            api.load_charge(charge_id, OPERATOR), expected_status=200
        )
        assert loaded["status"] == "LOADED"
        assert refetch_chamber(api, ctx["chamber"]["id"])["status"] == "OCCUPIED"
        assert refetch_receipt(api, wet_receipt["id"])["status"] == "CONSUMED"

        released = refetch_receipt(api, dry_receipt["id"])
        assert released["status"] == "ACCEPTED"
        assert released["kiln_charge_id"] is None


class TestChamberCapacityOnAllocate:
    """Capacity is checked against the running total, so the last receipt that
    fits is accepted and the one that overflows is not."""

    def test_an_overflowing_allocation_is_refused_and_an_exact_fit_is_taken(self, api):
        """PRD 3.4: "Three preconditions guard the move: the charge must be in
        `SCHEDULED` status, or the request is refused with `ERR_CHARGE_STATE_INVALID`;
        the receipt's species must be the same species as the charge's governing
        schedule, or the request is refused with `ERR_SPECIES_MISMATCH`; and the
        charge's `charged_green_bf` after adding this receipt's `accepted_board_feet`
        must not exceed the chamber's `capacity_board_feet`, or the request is refused
        with `ERR_CHAMBER_CAPACITY_EXCEEDED`."

        PRD 3.4: "The second, `weighted_initial_moisture_pct`, is the volume-weighted
        green moisture of the load: each receipt's `accepted_board_feet` is multiplied
        by its `moisture_pct_at_receipt`, those products are totalled, the total is
        divided by `charged_green_bf`, and the resulting ratio is rounded half up to
        one decimal place — once, on the aggregate, never per receipt."

        Design: Corner/validations/chamber_capacity_exceeded_on_allocate_and_exact_fit_passes
        """
        ctx = setup_scheduled_charge(
            api, chamber_overrides={"chamber_code": "K3", "capacity_board_feet": 9000}
        )
        charge_id = ctx["charge"]["id"]

        first = create_accepted_receipt(api, ctx["species"])
        overflowing = create_accepted_receipt(
            api,
            ctx["species"],
            received_board_feet=4000,
            accepted_board_feet=3900,
            moisture_pct_at_receipt=44.0,
            receipt_grade="SELECT",
        )
        exact_fit = create_accepted_receipt(api, ctx["species"], **EXACT_FIT_RECEIPT)

        validate_success(
            api.allocate_receipt(
                charge_id, allocate_receipt_payload(first["id"]), OPERATOR
            ),
            expected_status=200,
        )

        validate_error(
            api.allocate_receipt(
                charge_id, allocate_receipt_payload(overflowing["id"]), OPERATOR
            ),
            "ERR_CHAMBER_CAPACITY_EXCEEDED",
            expected_status=422,
        )
        rejected = refetch_receipt(api, overflowing["id"])
        assert rejected["status"] == "ACCEPTED"
        assert rejected["kiln_charge_id"] is None
        assert refetch_charge(api, charge_id)["charged_green_bf"] == pytest.approx(
            5800, abs=0.01
        )

        charge = validate_success(
            api.allocate_receipt(
                charge_id, allocate_receipt_payload(exact_fit["id"]), OPERATOR
            ),
            expected_status=200,
        )
        assert charge["charged_green_bf"] == pytest.approx(9000, abs=0.01)
        assert charge["weighted_initial_moisture_pct"] == pytest.approx(45.3, abs=0.01)


class TestChargeDryVolumeCeilingOnLotPlanning:
    """A lot may draw no more kiln-dry volume than the charge has left, and the
    comparison is made at two decimal places."""

    def test_one_hundredth_of_a_board_foot_too_much_is_refused(self, api):
        """PRD 3.6: "The charge must be in `RELEASED` status, or the request is
        refused with `ERR_CHARGE_STATE_INVALID`, and the requested draw may not exceed
        the charge's `remaining_dry_bf`, or it is refused with
        `ERR_CHARGE_DRY_BF_EXCEEDED`."

        PRD 3.5: "A charge holding 9700 green board feet of a `DENSE` species yields
        8972.50 kiln-dry board feet."

        Design: Corner/validations/lot_input_above_charge_remaining_dry_bf_rejected
        """
        ctx = setup_released_charge(api)
        charge_id = ctx["charge"]["id"]
        product_line = create_product_line(api, ctx["species"])

        validate_error(
            api.create_flooring_lot(
                create_flooring_lot_payload(product_line["id"], charge_id, 8972.51),
                SUPERVISOR,
            ),
            "ERR_CHARGE_DRY_BF_EXCEEDED",
            expected_status=422,
        )
        charge = refetch_charge(api, charge_id)
        assert charge["remaining_dry_bf"] == pytest.approx(8972.50, abs=0.01)
        assert charge["status"] == "RELEASED"

        lot = validate_success(
            api.create_flooring_lot(
                create_flooring_lot_payload(product_line["id"], charge_id, 8972.50),
                SUPERVISOR,
            ),
            expected_status=201,
        )
        assert lot["input_dry_bf"] == pytest.approx(8972.50, abs=0.01)

        _rows, meta = validate_paginated(
            api.list_flooring_lots(SUPERVISOR, params={"kiln_charge_id": charge_id})
        )
        assert meta["total_count"] == 1


class TestMillMassBalanceAndWasteCeiling:
    """The milling report has to account for the wood it consumed, and the
    unaccounted remainder has a ceiling."""

    def test_negative_waste_and_excessive_waste_are_separate_refusals(self, api):
        """PRD 3.6: "A negative `waste_bf` means the lot reported more output than it
        consumed and is refused with `ERR_MILL_MASS_BALANCE_VIOLATION`."

        PRD 3.6: "A `waste_bf` above 12 percent of `input_dry_bf`, that ceiling itself
        rounded half up to two decimal places, is refused with
        `ERR_WASTE_LIMIT_EXCEEDED`."

        PRD 3.6: "Three batches are created against the lot, one per stream, each with
        its `byproduct_type` set to `SAWDUST`, `SHAVINGS` and `SHORTS` respectively,
        `sold_tons` at 0, and `available_tons` fixed once from the milling report: the
        sawdust batch takes `sawdust_tons`, the shavings batch takes `shavings_tons`,
        and the shorts batch takes `shorts_bf` divided by the same 285 board feet per
        ton, rounded half up to two decimal places."

        Design: Corner/validations/mill_mass_balance_negative_waste_and_waste_limit_pair
        """
        ctx = setup_planned_lot(api, input_dry_bf=6000)
        lot_id = ctx["lot"]["id"]

        validate_error(
            api.complete_milling(
                lot_id,
                complete_milling_payload(sawdust_tons=3.00, shavings_tons=2.00),
                SUPERVISOR,
            ),
            "ERR_MILL_MASS_BALANCE_VIOLATION",
            expected_status=422,
        )
        validate_error(
            api.complete_milling(
                lot_id,
                complete_milling_payload(
                    net_flooring_bf=3000,
                    shorts_bf=100,
                    sawdust_tons=1.00,
                    shavings_tons=0.50,
                ),
                SUPERVISOR,
            ),
            "ERR_WASTE_LIMIT_EXCEEDED",
            expected_status=422,
        )

        untouched = refetch_lot(api, lot_id)
        assert untouched["status"] == "PLANNED"
        assert untouched["net_flooring_bf"] is None
        assert untouched["residue_bf"] is None
        assert untouched["waste_bf"] is None
        _rows, meta = validate_paginated(
            api.list_byproduct_batches(BROKER, params={"flooring_lot_id": lot_id})
        )
        assert meta["total_count"] == 0

        milled = validate_success(
            api.complete_milling(lot_id, complete_milling_payload(), SUPERVISOR),
            expected_status=200,
        )
        assert milled["status"] == "MILLED"
        assert milled["residue_bf"] == pytest.approx(570.00, abs=0.01)
        assert milled["waste_bf"] == pytest.approx(570.00, abs=0.01)
        assert milled["provisional_yield_pct"] == pytest.approx(78.00, abs=0.01)

        batches = fetch_lot_batches(api, lot_id)
        assert batches["SAWDUST"]["available_tons"] == pytest.approx(1.20, abs=0.01)
        assert batches["SHAVINGS"]["available_tons"] == pytest.approx(0.80, abs=0.01)
        assert batches["SHORTS"]["available_tons"] == pytest.approx(0.63, abs=0.01)

    def test_waste_landing_exactly_on_the_twelve_percent_ceiling_is_accepted(self, api):
        """PRD 3.6: "A `waste_bf` above 12 percent of `input_dry_bf`, that ceiling
        itself rounded half up to two decimal places, is refused with
        `ERR_WASTE_LIMIT_EXCEEDED`."

        PRD 3.6: "The provisional yield is recorded at the same time:
        `provisional_yield_pct` is `net_flooring_bf` divided by `input_dry_bf`,
        expressed as a percentage and rounded half up to two decimal places — 78.00
        percent in that example."

        Design: Corner/validations/waste_exactly_at_twelve_percent_limit_passes
        """
        ctx = setup_planned_lot(api, input_dry_bf=6000)
        lot_id = ctx["lot"]["id"]

        milled = validate_success(
            api.complete_milling(
                lot_id,
                complete_milling_payload(
                    net_flooring_bf=4700,
                    shorts_bf=152.50,
                    sawdust_tons=1.00,
                    shavings_tons=0.50,
                ),
                SUPERVISOR,
            ),
            expected_status=200,
        )
        assert milled["status"] == "MILLED"
        assert milled["residue_bf"] == pytest.approx(427.50, abs=0.01)
        assert milled["waste_bf"] == pytest.approx(720.00, abs=0.01)
        assert milled["provisional_yield_pct"] == pytest.approx(78.33, abs=0.01)

        rows, meta = validate_paginated(
            api.list_byproduct_batches(BROKER, params={"flooring_lot_id": lot_id})
        )
        assert meta["total_count"] == 3
        shorts = next(row for row in rows if row["byproduct_type"] == "SHORTS")
        assert shorts["available_tons"] == pytest.approx(0.54, abs=0.01)


class TestBundleVolumeCeiling:
    """A grade run may never tally more flooring than the lot produced."""

    def test_the_bundle_that_overflows_the_lot_is_refused_and_the_one_that_fills_it_is_not(
        self, api
    ):
        """PRD 3.7: "And a run may never tally more flooring than the lot produced:
        if the total `bundle_board_feet` across the run's bundles including the new one
        would exceed the lot's `net_flooring_bf`, the bundle is refused with
        `ERR_BUNDLE_BF_EXCEEDS_LOT`."

        PRD 3.7: "`credited_board_feet` is the total of each bundle's board feet
        multiplied by that bundle's credit factor, rounded half up to four decimal
        places."

        Design: Corner/validations/bundle_board_feet_above_lot_net_rejected
        """
        ctx = setup_draft_grade_run(
            api,
            ruleset="NHLA",
            bundles=[
                {
                    "grade_class": "CLEAR",
                    "bundle_board_feet": 4000.00,
                    "average_length_in": 50,
                }
            ],
        )
        run_id = ctx["grade_run"]["id"]

        validate_error(
            api.create_grade_bundle(
                run_id,
                create_grade_bundle_payload(
                    grade_class="SELECT",
                    bundle_board_feet=700.00,
                    average_length_in=36,
                ),
                INSPECTOR,
            ),
            "ERR_BUNDLE_BF_EXCEEDS_LOT",
            expected_status=422,
        )
        _rows, meta = validate_paginated(api.list_grade_run_bundles(run_id, INSPECTOR))
        assert meta["total_count"] == 1

        validate_success(
            api.create_grade_bundle(
                run_id,
                create_grade_bundle_payload(
                    grade_class="SELECT",
                    bundle_board_feet=680.00,
                    average_length_in=36,
                ),
                INSPECTOR,
            ),
            expected_status=201,
        )

        finalized = validate_success(
            api.finalize_grade_run(run_id, INSPECTOR), expected_status=200
        )
        assert finalized["tally_board_feet"] == pytest.approx(4680.00, abs=0.01)
        assert finalized["credited_board_feet"] == pytest.approx(4646.0000, abs=0.0001)


class TestGradeRunFinalizationPreconditions:
    """An empty run has nothing to tally, and a lot cannot close against a run
    that never finalized."""

    def test_an_empty_run_cannot_be_finalized_and_cannot_close_its_lot(self, api):
        """PRD 3.7: "Three preconditions apply: the run must carry at least one
        bundle, or it is refused with `ERR_NO_GRADE_BUNDLES`; the total bundle board
        feet must not exceed the lot's `net_flooring_bf`, or it is refused with
        `ERR_BUNDLE_BF_EXCEEDS_LOT`; and no `CHARACTER` or `CABIN` bundle may be
        present when the run's ruleset is `NHLA`, or it is refused with
        `ERR_CHARACTER_GRADE_NOT_PERMITTED`."

        PRD 3.7: "The payload names the `grade_run_id` to close against; that run must
        be in `FINALIZED` status, or the request is refused with
        `ERR_GRADE_RUN_STATE_INVALID`, and it must belong to this lot, or it is refused
        with `ERR_GRADE_RUN_LOT_MISMATCH`."

        Design: Corner/validations/grade_run_finalize_without_bundles_rejected
        """
        ctx = setup_draft_grade_run(api, ruleset="MILL_CHARACTER", bundles=[])
        run_id = ctx["grade_run"]["id"]
        lot_id = ctx["lot"]["id"]

        validate_error(
            api.finalize_grade_run(run_id, INSPECTOR),
            "ERR_NO_GRADE_BUNDLES",
            expected_status=422,
        )
        run = refetch_grade_run(api, run_id)
        assert run["status"] == "DRAFT"
        assert run["tally_board_feet"] is None
        assert run["credited_board_feet"] is None
        assert run["tally_value_cents"] is None

        validate_error(
            api.finalize_flooring_lot(lot_id, finalize_lot_payload(run_id), SUPERVISOR),
            "ERR_GRADE_RUN_STATE_INVALID",
            expected_status=409,
        )
        assert refetch_lot(api, lot_id)["status"] == "MILLED"


class TestCharacterGradesUnderNhla:
    """The two character classes are a `MILL_CHARACTER` privilege; the plain
    industry rules take everything else."""

    def test_character_and_cabin_are_barred_while_a_low_common_grade_is_not(self, api):
        """PRD 3.7: "`CHARACTER` and `CABIN` bundles are permitted only under the
        `MILL_CHARACTER` ruleset and are refused on an `NHLA` run with
        `ERR_CHARACTER_GRADE_NOT_PERMITTED`."

        PRD 3.7: "Its `credit_factor` is selected by grade class: 1.00 for `CLEAR`,
        0.95 for `SELECT`, 0.85 for `NO1_COMMON`, 0.70 for `NO2_COMMON`, 0.60 for
        `CHARACTER` and 0.40 for `CABIN`."

        Design: Corner/validations/character_and_cabin_bundles_rejected_under_nhla
        """
        ctx = setup_draft_grade_run(api, ruleset="NHLA", bundles=[])
        run_id = ctx["grade_run"]["id"]

        for barred in ("CHARACTER", "CABIN"):
            validate_error(
                api.create_grade_bundle(
                    run_id,
                    create_grade_bundle_payload(
                        grade_class=barred,
                        bundle_board_feet=100.00,
                        average_length_in=20,
                    ),
                    INSPECTOR,
                ),
                "ERR_CHARACTER_GRADE_NOT_PERMITTED",
                expected_status=422,
            )

        bundle = validate_success(
            api.create_grade_bundle(
                run_id,
                create_grade_bundle_payload(
                    grade_class="NO2_COMMON",
                    bundle_board_feet=100.00,
                    average_length_in=30,
                ),
                INSPECTOR,
            ),
            expected_status=201,
        )
        assert bundle["credit_factor"] == pytest.approx(0.70, abs=0.01)
        assert bundle["length_factor"] == pytest.approx(1.00, abs=0.01)
        assert bundle["tally_value_cents"] == 28000

        _rows, meta = validate_paginated(api.list_grade_run_bundles(run_id, INSPECTOR))
        assert meta["total_count"] == 1


class TestGradeRunBelongsToItsLot:
    """A finalized run is bound to the lot it graded, both as a closing run and as
    a replacement."""

    def test_another_lots_run_is_refused_in_both_roles(self, api):
        """PRD 3.7: "The payload names the `grade_run_id` to close against; that run
        must be in `FINALIZED` status, or the request is refused with
        `ERR_GRADE_RUN_STATE_INVALID`, and it must belong to this lot, or it is refused
        with `ERR_GRADE_RUN_LOT_MISMATCH`."

        PRD 3.7: "Superseding names a `replacement_grade_run_id`, which must exist,
        must belong to the same lot as the run being superseded — otherwise
        `ERR_GRADE_RUN_LOT_MISMATCH` — and must itself be in `FINALIZED` status."

        Design: Corner/validations/grade_run_from_another_lot_rejected_on_finalize_and_supersede
        """
        ctx = setup_planned_lot(api, input_dry_bf=4000)
        ctx = setup_second_lot_on_charge(api, input_dry_bf=4000, ctx=ctx)

        runs = []
        for lot in (ctx["lot"], ctx["lot_b"]):
            milled = validate_success(
                api.complete_milling(
                    lot["id"], complete_milling_payload(**HALF_LOT_MILLING), SUPERVISOR
                ),
                expected_status=200,
            )
            run = validate_success(
                api.create_grade_run(
                    create_grade_run_payload(
                        lot["id"], milled["version"], inspector_ruleset="NHLA"
                    ),
                    INSPECTOR,
                ),
                expected_status=201,
            )
            validate_success(
                api.create_grade_bundle(
                    run["id"],
                    create_grade_bundle_payload(
                        grade_class="CLEAR",
                        bundle_board_feet=3000.00,
                        average_length_in=50,
                    ),
                    INSPECTOR,
                ),
                expected_status=201,
            )
            runs.append(
                validate_success(
                    api.finalize_grade_run(run["id"], INSPECTOR), expected_status=200
                )
            )

        own_run, foreign_run = runs
        lot_id = ctx["lot"]["id"]

        validate_error(
            api.finalize_flooring_lot(
                lot_id, finalize_lot_payload(foreign_run["id"]), SUPERVISOR
            ),
            "ERR_GRADE_RUN_LOT_MISMATCH",
            expected_status=422,
        )
        blocked_lot = refetch_lot(api, lot_id)
        assert blocked_lot["status"] == "MILLED"
        assert blocked_lot["final_grade_run_id"] is None

        validate_error(
            api.supersede_grade_run(
                own_run["id"],
                supersede_grade_run_payload(foreign_run["id"]),
                INSPECTOR,
            ),
            "ERR_GRADE_RUN_LOT_MISMATCH",
            expected_status=422,
        )
        blocked_run = refetch_grade_run(api, own_run["id"])
        assert blocked_run["status"] == "FINALIZED"
        assert blocked_run["superseded_by_run_id"] is None

        graded = validate_success(
            api.finalize_flooring_lot(
                lot_id, finalize_lot_payload(own_run["id"]), SUPERVISOR
            ),
            expected_status=200,
        )
        assert graded["status"] == "GRADED"
        assert graded["final_yield_pct"] == pytest.approx(75.00, abs=0.01)
        assert graded["final_grade_run_id"] == own_run["id"]

        _rows, meta = validate_paginated(
            api.list_flooring_lots(
                SUPERVISOR, params={"final_grade_run_id": own_run["id"]}
            )
        )
        assert meta["total_count"] == 1


class TestAdjudicatedAreaWithinTheClaim:
    """The inspector may verify less than was claimed, never more, and the check
    happens before any money moves."""

    def test_verifying_more_area_than_was_claimed_moves_nothing(self, api):
        """PRD 3.9: "The verified area may not exceed the area claimed, or the request
        is refused with `ERR_ADJUDICATED_SF_EXCEEDS_CLAIM`."

        PRD 3.9: "Step five ages the claim: `service_months` is the number of whole
        months from `installation_date` to the current logical date, `depreciation_pct`
        is 0.5 percentage points per whole month of service capped at 40 percent, and
        the depreciated amount is the gross multiplied by one less that depreciation
        expressed as a fraction."

        PRD 3.9: "The `posture` is then `FROZEN` whenever `freeze_override` is true,
        regardless of money; otherwise it is `RESTRICTED` when `warranty_balance_cents`
        is below the restriction floor of 500000 cents; and otherwise it is `OPEN`."

        Design: Corner/validations/adjudicated_sf_above_claimed_sf_rejected
        """
        ctx = setup_line_only_submitted_claim(api)
        claim_id = ctx["claim"]["id"]
        line_id = ctx["product_line"]["id"]
        adjudicator = make_warranty_adjudicator_headers(CLAIM_ADJUDICATOR_USER_ID)

        validate_error(
            api.adjudicate_claim(
                claim_id,
                adjudicate_claim_payload(adjudicated_affected_sf=250),
                adjudicator,
            ),
            "ERR_ADJUDICATED_SF_EXCEEDS_CLAIM",
            expected_status=422,
        )
        untouched = refetch_claim(api, claim_id)
        assert untouched["adjudication_status"] == "SUBMITTED"
        assert untouched["adjudicated_liability_cents"] is None
        assert untouched["adjudicated_by_user_id"] is None

        line = refetch_product_line(api, line_id)
        assert line["warranty_committed_cents"] == 0
        assert line["posture"] == "OPEN"

        approved = validate_success(
            api.adjudicate_claim(
                claim_id,
                adjudicate_claim_payload(adjudicated_affected_sf=240),
                adjudicator,
            ),
            expected_status=200,
        )
        assert approved["adjudication_status"] == "APPROVED"
        assert approved["installer_share_pct"] == 50
        assert approved["service_months"] == 5
        assert approved["depreciation_pct"] == pytest.approx(2.5, abs=0.01)
        assert approved["adjudicated_liability_cents"] == 173113

        line = refetch_product_line(api, line_id)
        assert line["warranty_committed_cents"] == 173113
        assert line["warranty_balance_cents"] == 426887
        assert line["posture"] == "RESTRICTED"


class TestOpenClaimCeiling:
    """A line carries at most three undecided claims, and a claim awaiting
    information is still undecided."""

    CLAIM_TEMPLATES = (
        {
            "claim_type": "CUPPING",
            "affected_square_feet": 100,
            "installation_date": "2026-06-15",
            "subfloor_moisture_pct_at_install": 10.5,
            "ambient_rh_pct_at_install": 62,
        },
        {
            "claim_type": "GAPPING",
            "affected_square_feet": 100,
            "installation_date": "2026-06-16",
            "subfloor_moisture_pct_at_install": 9.5,
            "ambient_rh_pct_at_install": 40,
        },
        {
            "claim_type": "CUPPING",
            "affected_square_feet": 100,
            "installation_date": "2026-06-17",
            "subfloor_moisture_pct_at_install": 11.0,
            "ambient_rh_pct_at_install": 65,
        },
    )

    FOURTH_CLAIM = {
        "claim_type": "GAPPING",
        "affected_square_feet": 50,
        "installation_date": "2026-06-18",
        "subfloor_moisture_pct_at_install": 8.0,
        "ambient_rh_pct_at_install": 35,
    }

    def test_a_claim_awaiting_information_still_blocks_a_fourth_until_one_is_denied(
        self, api
    ):
        """PRD 3.9: "And a single product line may not carry more than three claims at
        once in `SUBMITTED` or `INFO_REQUESTED` status; a fourth is refused with
        `ERR_TOO_MANY_OPEN_CLAIMS`."

        PRD 3.9: "On the `DENIED` branch the claim moves from `SUBMITTED` to the
        terminal `DENIED` status, the supplied `denial_reason` is recorded, and the
        warranty reserve is left entirely untouched — `installer_share_pct`,
        `mill_share_pct`, `service_months`, `depreciation_pct` and
        `adjudicated_liability_cents` all stay null, and the line's posture does not
        move."

        Design: Corner/validations/fourth_open_claim_rejected_and_allowed_after_denial
        """
        ctx = setup_warranty_line(api)
        line_id = ctx["product_line"]["id"]
        submitter = make_warranty_adjudicator_headers(CLAIM_SUBMITTER_USER_ID)
        adjudicator = make_warranty_adjudicator_headers(CLAIM_ADJUDICATOR_USER_ID)

        open_claims = [
            validate_success(
                api.create_warranty_claim(
                    create_warranty_claim_payload(line_id, **template), submitter
                ),
                expected_status=201,
            )
            for template in self.CLAIM_TEMPLATES
        ]
        validate_success(
            api.request_claim_info(
                open_claims[2]["id"],
                request_info_payload(
                    info_request_note="Send the installer moisture log."
                ),
                adjudicator,
            ),
            expected_status=200,
        )

        validate_error(
            api.create_warranty_claim(
                create_warranty_claim_payload(line_id, **self.FOURTH_CLAIM), submitter
            ),
            "ERR_TOO_MANY_OPEN_CLAIMS",
            expected_status=409,
        )
        _rows, meta = validate_paginated(
            api.list_warranty_claims(adjudicator, params={"product_line_id": line_id})
        )
        assert meta["total_count"] == 3

        denied = validate_success(
            api.adjudicate_claim(
                open_claims[1]["id"],
                adjudicate_claim_payload(
                    decision="DENIED",
                    adjudicated_affected_sf=100,
                    adjudicated_subfloor_moisture_pct=9.5,
                    adjudicated_ambient_rh_pct=40,
                    denial_reason="Installed over an unacclimated slab.",
                ),
                adjudicator,
            ),
            expected_status=200,
        )
        assert denied["adjudication_status"] == "DENIED"
        assert denied["adjudicated_liability_cents"] is None
        assert refetch_product_line(api, line_id)["warranty_committed_cents"] == 0

        fourth = validate_success(
            api.create_warranty_claim(
                create_warranty_claim_payload(line_id, **self.FOURTH_CLAIM), submitter
            ),
            expected_status=201,
        )
        assert fourth["adjudication_status"] == "SUBMITTED"

        _rows, meta = validate_paginated(
            api.list_warranty_claims(adjudicator, params={"product_line_id": line_id})
        )
        assert meta["total_count"] == 4


class TestConfigurationCodeUniqueness:
    """Each configuration code is unique inside its own collection."""

    def test_a_reused_species_code_and_chamber_code_are_refused(self, api):
        """PRD 2.10: "Configuration codes are unique within their own collection:
        `species_code` among species profiles, `schedule_code` among drying schedules,
        `chamber_code` among kiln chambers, and `line_code` among product lines and,
        separately, among prefinish lines."

        PRD 2.10: "Re-using a code within its collection is rejected with
        `ERR_DUPLICATE_CODE`."

        PRD 3.1: "Kiln chambers are registered by a `MillAdmin` with a unique
        `chamber_code` and a `capacity_board_feet` ceiling on green volume, and open in
        `AVAILABLE` status with a null `maintenance_note`."

        Design: Corner/validations/duplicate_species_code_and_chamber_code_rejected
        """
        set_logical_clock(api)
        create_species(api)
        chamber = create_chamber(api)

        validate_error(
            api.create_species_profile(
                create_species_profile_payload(
                    common_name="Northern Red Oak",
                    density_class="MEDIUM",
                    tangential_shrinkage_coefficient=0.120,
                    target_moisture_pct=8.0,
                    max_moisture_gradient_pp=1.5,
                ),
                ADMIN,
            ),
            "ERR_DUPLICATE_CODE",
            expected_status=409,
        )
        rows, meta = validate_paginated(api.list_species_profiles(ADMIN))
        assert meta["total_count"] == 1
        assert rows[0]["density_class"] == "DENSE"

        validate_error(
            api.create_kiln_chamber(
                create_kiln_chamber_payload(capacity_board_feet=8000), ADMIN
            ),
            "ERR_DUPLICATE_CODE",
            expected_status=409,
        )
        assert refetch_chamber(api, chamber["id"])["capacity_board_feet"] == 12000

        second = validate_success(
            api.create_kiln_chamber(
                create_kiln_chamber_payload(
                    chamber_code="K2", capacity_board_feet=8000
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        assert second["chamber_code"] == "K2"
        assert second["status"] == "AVAILABLE"

        _rows, meta = validate_paginated(api.list_kiln_chambers(ADMIN))
        assert meta["total_count"] == 2


class TestSpeciesAgreementOnAllocate:
    """A charge takes only the species its governing schedule was written for."""

    def test_a_foreign_species_receipt_is_refused_while_the_matching_one_is_taken(
        self, api
    ):
        """PRD 3.4: "Three preconditions guard the move: the charge must be in
        `SCHEDULED` status, or the request is refused with `ERR_CHARGE_STATE_INVALID`;
        the receipt's species must be the same species as the charge's governing
        schedule, or the request is refused with `ERR_SPECIES_MISMATCH`; and the
        charge's `charged_green_bf` after adding this receipt's `accepted_board_feet`
        must not exceed the chamber's `capacity_board_feet`, or the request is refused
        with `ERR_CHAMBER_CAPACITY_EXCEEDED`."

        PRD 3.4: "When the allocated set is empty, `charged_green_bf` is 0 and
        `weighted_initial_moisture_pct` is null."

        Design: Corner/validations/allocate_receipt_of_wrong_species_rejected
        """
        ctx = setup_second_species_receipt(
            api,
            species_overrides={"max_moisture_gradient_pp": 1.5},
            receipt_overrides={"supplier_name": "Northwoods Timber"},
        )
        charge_id = ctx["charge"]["id"]
        foreign_receipt = ctx["other_species_receipt"]

        validate_error(
            api.allocate_receipt(
                charge_id, allocate_receipt_payload(foreign_receipt["id"]), OPERATOR
            ),
            "ERR_SPECIES_MISMATCH",
            expected_status=422,
        )
        refused = refetch_receipt(api, foreign_receipt["id"])
        assert refused["status"] == "ACCEPTED"
        assert refused["kiln_charge_id"] is None

        charge = refetch_charge(api, charge_id)
        assert charge["charged_green_bf"] == pytest.approx(0, abs=0.01)
        assert charge["weighted_initial_moisture_pct"] is None

        own_receipt = create_accepted_receipt(api, ctx["species"])
        charge = validate_success(
            api.allocate_receipt(
                charge_id, allocate_receipt_payload(own_receipt["id"]), OPERATOR
            ),
            expected_status=200,
        )
        assert charge["charged_green_bf"] == pytest.approx(5800, abs=0.01)
        assert charge["weighted_initial_moisture_pct"] == pytest.approx(46.0, abs=0.01)


class TestCoreStockBranchRules:
    """The substrate rules are strictly symmetric, and the forbidden-core check is
    reached before the ownership check."""

    def test_missing_forbidden_and_foreign_core_each_get_their_own_refusal(self, api):
        """PRD 3.6: "An `ENGINEERED` lot must name a `core_stock_id`; omitting it is
        refused with `ERR_CORE_STOCK_REQUIRED`."

        PRD 3.6: "A `SOLID` lot must not name one; supplying it is refused with
        `ERR_CORE_STOCK_NOT_ALLOWED`."

        PRD 3.6: "Where core stock is named it must belong to the same product line as
        the lot, or the request is refused with `ERR_CORE_STOCK_LINE_MISMATCH`."

        PRD 2.7: "30. Core stock forbidden — `ERR_CORE_STOCK_NOT_ALLOWED` (422), on
        `POST /mill/flooring-lots`."

        PRD 3.6: "For an engineered lot the server computes `reserved_core_sf` as the
        drawn `input_dry_bf` multiplied by 1.10 square feet of core per board foot,
        rounded half up to two decimal places — a draw of 2900 board feet reserves
        3190.00 square feet — and adds it to the core stock's `reserved_square_feet`,
        which is at all times the total `reserved_core_sf` of the non-voided lots on
        that stock."

        Design: Corner/validations/core_stock_trio_rejects_missing_disallowed_and_foreign_core
        """
        ctx = setup_released_charge(api)
        charge_id = ctx["charge"]["id"]

        engineered_line = create_product_line(
            api,
            ctx["species"],
            line_code="ENG-RO-500",
            construction_type="ENGINEERED",
            nominal_width_in=5.000,
            nominal_thickness_in=0.500,
            material_value_cents_per_sf=720,
            warranty_funded_total_cents=400000,
        )
        solid_line = create_product_line(api, ctx["species"])
        other_engineered_line = create_product_line(
            api,
            ctx["species"],
            line_code="ENG-RO-425",
            construction_type="ENGINEERED",
            nominal_width_in=4.250,
            nominal_thickness_in=0.500,
            material_value_cents_per_sf=690,
            warranty_funded_total_cents=350000,
        )
        foreign_core = create_core_stock(
            api,
            other_engineered_line,
            core_material="BIRCH_PLY",
            lot_reference="BP-2026-07",
            available_square_feet=20000.00,
        )
        own_core = create_core_stock(
            api,
            engineered_line,
            core_material="HDF",
            lot_reference="HDF-2026-07",
            available_square_feet=20000.00,
        )

        validate_error(
            api.create_flooring_lot(
                create_flooring_lot_payload(engineered_line["id"], charge_id, 1000),
                SUPERVISOR,
            ),
            "ERR_CORE_STOCK_REQUIRED",
            expected_status=422,
        )
        validate_error(
            api.create_flooring_lot(
                create_flooring_lot_payload(
                    solid_line["id"], charge_id, 1000, core_stock_id=foreign_core["id"]
                ),
                SUPERVISOR,
            ),
            "ERR_CORE_STOCK_NOT_ALLOWED",
            expected_status=422,
        )
        validate_error(
            api.create_flooring_lot(
                create_flooring_lot_payload(
                    engineered_line["id"],
                    charge_id,
                    1000,
                    core_stock_id=foreign_core["id"],
                ),
                SUPERVISOR,
            ),
            "ERR_CORE_STOCK_LINE_MISMATCH",
            expected_status=422,
        )

        lot = validate_success(
            api.create_flooring_lot(
                create_flooring_lot_payload(
                    engineered_line["id"],
                    charge_id,
                    1000,
                    core_stock_id=own_core["id"],
                ),
                SUPERVISOR,
            ),
            expected_status=201,
        )
        assert lot["reserved_core_sf"] == pytest.approx(1100.00, abs=0.01)

        assert refetch_core_stock(api, own_core["id"])[
            "reserved_square_feet"
        ] == pytest.approx(1100.00, abs=0.01)
        assert refetch_core_stock(api, foreign_core["id"])[
            "reserved_square_feet"
        ] == pytest.approx(0.00, abs=0.01)


class TestPrefinishWindowShape:
    """A prefinish window must be non-empty and no longer than a day."""

    def test_an_over_long_and_an_empty_window_are_refused_while_a_full_day_is_not(
        self, api
    ):
        """PRD 2.9: "A window must also be non-empty — its end strictly after its
        start — and no longer than 24 hours, or it is rejected with
        `ERR_PREFINISH_WINDOW_INVALID`."

        PRD 3.8: "The square footage passing through the line is
        `scheduled_linear_feet` multiplied by the lot's `actual_milled_width_in` and
        divided by 12, and `coating_liters` is that square footage multiplied by 0.012
        litres per square foot and by the line's number of `coating_passes`, rounded
        half up to two decimal places once at the very end — the square footage is not
        pre-rounded."

        Design: Corner/validations/prefinish_window_over_twenty_four_hours_and_empty_window_rejected
        """
        ctx = setup_prefinish_ready(
            api,
            ruleset="NHLA",
            bundles=[
                {
                    "grade_class": "CLEAR",
                    "bundle_board_feet": 4680.00,
                    "average_length_in": 50,
                }
            ],
        )
        prefinish_line_id = ctx["prefinish_line"]["id"]
        lot_id = ctx["lot"]["id"]

        validate_error(
            api.create_prefinish_run(
                create_prefinish_run_payload(
                    prefinish_line_id,
                    lot_id,
                    window_start_utc="2026-08-20T06:00:00.000Z",
                    window_end_utc="2026-08-21T07:00:00.000Z",
                ),
                SCHEDULER,
            ),
            "ERR_PREFINISH_WINDOW_INVALID",
            expected_status=422,
        )
        validate_error(
            api.create_prefinish_run(
                create_prefinish_run_payload(
                    prefinish_line_id,
                    lot_id,
                    window_start_utc="2026-08-20T06:00:00.000Z",
                    window_end_utc="2026-08-20T06:00:00.000Z",
                ),
                SCHEDULER,
            ),
            "ERR_PREFINISH_WINDOW_INVALID",
            expected_status=422,
        )

        run = validate_success(
            api.create_prefinish_run(
                create_prefinish_run_payload(
                    prefinish_line_id,
                    lot_id,
                    window_start_utc="2026-08-20T06:00:00.000Z",
                    window_end_utc="2026-08-21T06:00:00.000Z",
                ),
                SCHEDULER,
            ),
            expected_status=201,
        )
        assert run["status"] == "SCHEDULED"
        assert run["coating_liters"] == pytest.approx(47.85, abs=0.01)

        _rows, meta = validate_paginated(
            api.list_prefinish_runs(
                SCHEDULER, params={"prefinish_line_id": prefinish_line_id}
            )
        )
        assert meta["total_count"] == 1


class TestVoidBlockedByByproductSales:
    """One settled sale is enough to freeze the lot against void, because voiding
    would zero a batch that has already shipped."""

    def test_a_single_partial_sale_bars_the_void(self, api):
        """PRD 3.6: "That last cascade is only safe while nothing has been sold, so a
        `MILLED` lot with any byproduct sale recorded against any of its batches may
        not be voided and is refused with `ERR_BYPRODUCT_SALE_EXISTS`."

        PRD 3.6: "The batch's `sold_tons` is at all times the total `quantity_tons` of
        the sales recorded against it, and a sale whose quantity would push `sold_tons`
        above the batch's `available_tons` is refused with
        `ERR_BYPRODUCT_QUANTITY_EXCEEDS_BATCH`."

        Design: Corner/validations/lot_void_blocked_after_byproduct_sale_exists
        """
        ctx = setup_lot_with_byproduct_sale(
            api,
            sale_overrides={
                "buyer_name": "Pellet Coop",
                "quantity_tons": 1.00,
                "unit_price_cents_per_ton": 2200,
                "haul_distance_miles": 30,
            },
        )
        lot_id = ctx["lot"]["id"]

        validate_error(
            api.void_flooring_lot(
                lot_id,
                void_lot_payload(
                    void_reason="Milling data entered against the wrong charge."
                ),
                SUPERVISOR,
            ),
            "ERR_BYPRODUCT_SALE_EXISTS",
            expected_status=409,
        )

        lot = refetch_lot(api, lot_id)
        assert lot["status"] == "MILLED"
        assert lot["void_reason"] is None
        assert refetch_charge(api, ctx["charge"]["id"])[
            "remaining_dry_bf"
        ] == pytest.approx(2972.50, abs=0.01)

        batch = refetch_batch(api, ctx["batches"]["SAWDUST"]["id"])
        assert batch["sold_tons"] == pytest.approx(1.00, abs=0.01)
        assert batch["available_tons"] == pytest.approx(1.20, abs=0.01)


class TestRedryAllowance:
    """Two redry cycles are allowed; the third failing test is refused instead of
    extending the charge again."""

    def test_the_third_failing_stress_test_is_refused_and_a_passing_one_still_releases(
        self, api
    ):
        """PRD 3.5: "On the redry branch the charge moves from `CONDITIONING` to
        `REDRY`. The readings and derived figures are stored exactly as on the release
        branch, `redry_count` is incremented, `planned_end_utc` is advanced by a
        further 48 hours, and `blocked_until_utc` is recomputed from the new end plus
        the same 6-hour cooldown buffer."

        PRD 3.5: "A charge may be sent back for redry at most twice; a failing stress
        test on a charge whose `redry_count` already stands at 2 is refused with
        `ERR_REDRY_LIMIT_EXCEEDED`, leaving the charge in `CONDITIONING`."

        PRD 3.5: "The chamber the charge occupied moves from `OCCUPIED` back to
        `AVAILABLE`, free for the next load."

        Design: Corner/validations/third_redry_cycle_rejected_at_limit
        """
        ctx = setup_conditioning_charge(api)
        charge_id = ctx["charge"]["id"]

        first = validate_success(
            api.record_stress_test(
                charge_id, record_stress_test_payload(5.9, 8.0), OPERATOR
            ),
            expected_status=200,
        )
        assert first["status"] == "REDRY"
        assert first["moisture_gradient_pp"] == pytest.approx(2.1, abs=0.01)
        assert first["redry_count"] == 1
        assert first["planned_end_utc"] == "2026-08-18T01:00:00.000Z"

        validate_success(
            api.resume_conditioning(charge_id, OPERATOR), expected_status=200
        )
        second = validate_success(
            api.record_stress_test(
                charge_id, record_stress_test_payload(5.9, 8.0), OPERATOR
            ),
            expected_status=200,
        )
        assert second["redry_count"] == 2
        assert second["planned_end_utc"] == "2026-08-20T01:00:00.000Z"

        validate_success(
            api.resume_conditioning(charge_id, OPERATOR), expected_status=200
        )
        validate_error(
            api.record_stress_test(
                charge_id, record_stress_test_payload(5.9, 8.0), OPERATOR
            ),
            "ERR_REDRY_LIMIT_EXCEEDED",
            expected_status=409,
        )
        held = refetch_charge(api, charge_id)
        assert held["status"] == "CONDITIONING"
        assert held["redry_count"] == 2
        assert held["planned_end_utc"] == "2026-08-20T01:00:00.000Z"

        released = validate_success(
            api.record_stress_test(
                charge_id, record_stress_test_payload(6.4, 8.2), OPERATOR
            ),
            expected_status=200,
        )
        assert released["status"] == "RELEASED"
        assert released["moisture_gradient_pp"] == pytest.approx(1.8, abs=0.01)
        assert released["average_moisture_pct"] == pytest.approx(7.3, abs=0.01)
        assert released["dry_bf_out"] == pytest.approx(8972.50, abs=0.01)
        assert released["blocked_until_utc"] == "2026-08-20T07:00:00.000Z"

        assert refetch_chamber(api, ctx["chamber"]["id"])["status"] == "AVAILABLE"


class TestByproductAvailability:
    """Availability is tracked per batch, so an exhausted stream cannot borrow
    from a sibling."""

    def test_the_last_hundredth_of_a_ton_sells_and_nothing_beyond_it_does(self, api):
        """PRD 3.6: "The batch's `sold_tons` is at all times the total `quantity_tons`
        of the sales recorded against it, and a sale whose quantity would push
        `sold_tons` above the batch's `available_tons` is refused with
        `ERR_BYPRODUCT_QUANTITY_EXCEEDS_BATCH`."

        PRD 3.6: "The invoice is built in a fixed order, each amount rounded half up
        to whole cents: `gross_cents` is `quantity_tons` multiplied by
        `unit_price_cents_per_ton`; `discount_cents` applies a volume discount of
        nothing below 5 tons, 3 percent from 5 tons up to but not including 20 tons,
        and 6 percent at 20 tons and above, taken against the gross; `haul_cents` is a
        flat 2500 cents plus 180 cents per mile of `haul_distance_miles`; and
        `net_cents` is the gross less the discount plus the haulage."

        Design: Corner/validations/byproduct_sale_above_available_tons_rejected
        """
        ctx = setup_milled_lot(
            api, input_dry_bf=8000, milling=dict(TEN_TON_SAWDUST_MILLING)
        )
        sawdust_id = ctx["batches"]["SAWDUST"]["id"]
        shavings_id = ctx["batches"]["SHAVINGS"]["id"]

        for buyer, tons in (("Pellet Coop", 5.00), ("Bedding Supply", 4.99)):
            validate_success(
                api.create_byproduct_sale(
                    create_byproduct_sale_payload(
                        sawdust_id, quantity_tons=tons, buyer_name=buyer
                    ),
                    BROKER,
                ),
                expected_status=201,
            )

        validate_error(
            api.create_byproduct_sale(
                create_byproduct_sale_payload(
                    sawdust_id, quantity_tons=0.02, buyer_name="Mulch Yard"
                ),
                BROKER,
            ),
            "ERR_BYPRODUCT_QUANTITY_EXCEEDS_BATCH",
            expected_status=422,
        )
        validate_error(
            api.create_byproduct_sale(
                create_byproduct_sale_payload(
                    shavings_id,
                    quantity_tons=0.01,
                    unit_price_cents_per_ton=3000,
                    haul_distance_miles=5,
                    buyer_name="Mulch Yard",
                ),
                BROKER,
            ),
            "ERR_BYPRODUCT_QUANTITY_EXCEEDS_BATCH",
            expected_status=422,
        )
        assert refetch_batch(api, sawdust_id)["sold_tons"] == pytest.approx(
            9.99, abs=0.01
        )

        sale = validate_success(
            api.create_byproduct_sale(
                create_byproduct_sale_payload(
                    sawdust_id, quantity_tons=0.01, buyer_name="Mulch Yard"
                ),
                BROKER,
            ),
            expected_status=201,
        )
        assert sale["gross_cents"] == 22
        assert sale["discount_cents"] == 0
        assert sale["haul_cents"] == 6100
        assert sale["net_cents"] == 6122

        assert refetch_batch(api, sawdust_id)["sold_tons"] == pytest.approx(
            10.00, abs=0.01
        )


class TestWarrantyIntakeDateGuards:
    """The installation date has to be in the past and inside the filing
    window."""

    def test_a_future_install_is_refused_an_old_one_expires_and_the_boundary_holds(
        self, api
    ):
        """PRD 3.9: "The installation date may not be after the current logical date,
        or the claim is refused with `ERR_INSTALL_DATE_IN_FUTURE`."

        PRD 3.9: "A claim may not be filed more than 60 whole months after
        installation, or it is refused with `ERR_WARRANTY_PERIOD_EXPIRED`."

        PRD 3.9: "First, a base is the `affected_square_feet` multiplied by the sum of
        the line's `material_value_cents_per_sf` and a remediation labour allowance of
        475 cents per square foot."

        Design: Corner/validations/install_date_in_future_and_expired_warranty_rejected
        """
        ctx = setup_warranty_line(api)
        line_id = ctx["product_line"]["id"]
        submitter = make_warranty_adjudicator_headers(CLAIM_SUBMITTER_USER_ID)

        validate_error(
            api.create_warranty_claim(
                create_warranty_claim_payload(
                    line_id,
                    affected_square_feet=100,
                    installation_date="2026-09-01",
                ),
                submitter,
            ),
            "ERR_INSTALL_DATE_IN_FUTURE",
            expected_status=422,
        )
        validate_error(
            api.create_warranty_claim(
                create_warranty_claim_payload(
                    line_id,
                    affected_square_feet=100,
                    installation_date="2021-03-15",
                ),
                submitter,
            ),
            "ERR_WARRANTY_PERIOD_EXPIRED",
            expected_status=422,
        )

        claim = validate_success(
            api.create_warranty_claim(
                create_warranty_claim_payload(
                    line_id,
                    affected_square_feet=100,
                    installation_date="2021-08-20",
                ),
                submitter,
            ),
            expected_status=201,
        )
        assert claim["adjudication_status"] == "SUBMITTED"
        assert claim["estimated_liability_cents"] == 147960

        _rows, meta = validate_paginated(
            api.list_warranty_claims(
                make_warranty_adjudicator_headers(CLAIM_ADJUDICATOR_USER_ID),
                params={"product_line_id": line_id},
            )
        )
        assert meta["total_count"] == 1
