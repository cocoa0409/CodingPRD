"""The layers that cut across the whole mill: the two optimistic-concurrency
tokens, the reserve floor that decides a line's posture, the substrate aggregate
that survives a void, and the immediacy of a freeze cascade."""

import pytest

from test_helpers import (
    create_drying_schedule_payload,
    create_flooring_lot_payload,
    create_grade_run_payload,
    freeze_product_line_payload,
    fund_warranty_payload,
    validate_error,
    validate_paginated,
    validate_success,
    void_lot_payload,
)
from test_helpers.fixtures import (
    ADMIN,
    INSPECTOR,
    SCHEDULER,
    SUPERVISOR,
    create_core_stock,
    create_product_line,
    create_species,
    refetch_charge,
    refetch_core_stock,
    refetch_lot,
    set_logical_clock,
    setup_milled_lot,
    setup_released_charge,
    setup_scheduled_prefinish_run,
    setup_warranty_line,
)

# The engineered line and its substrate holding, sized so two lots fit inside it.
ENGINEERED_LINE = {
    "line_code": "ENG-RO-500",
    "construction_type": "ENGINEERED",
    "nominal_width_in": 5.000,
    "nominal_thickness_in": 0.500,
    "material_value_cents_per_sf": 720,
    "warranty_funded_total_cents": 400000,
}

CORE_STOCK = {
    "core_material": "BIRCH_PLY",
    "lot_reference": "BP-2026-04",
    "available_square_feet": 4000.00,
}

# The single full-volume bundle that grades the lot used by the freeze cascade.
FULL_LOT_BUNDLE = {
    "grade_class": "CLEAR",
    "bundle_board_feet": 4680.00,
    "average_length_in": 50,
}


class TestSpeciesProfileConcurrencyToken:
    """Each schedule create consumes the profile's revision, so a replayed token
    is refused until the caller re-reads."""

    def test_a_replayed_profile_version_is_refused_and_the_re_read_one_is_taken(
        self, api
    ):
        """PRD 2.5: "If that value does not equal the profile's current `version`, the
        write is refused with `ERR_STALE_SPECIES_PROFILE_VERSION` (HTTP 412)."

        PRD 2.5: "A successful create increments `SpeciesProfile.version`, so a caller
        that holds a pre-write version is refused on its next attempt until it re-reads
        the profile."

        PRD 3.1: "A dense one-inch schedule taking stock from 45.0 percent down to 7.0
        percent with 24 conditioning hours and 12 stress relief hours therefore plans
        265.0 hours."

        PRD 3.1: "The result is rounded half up to one decimal place, and only then
        clamped into the range 48 to 360 hours: a computed 41.3 becomes 48.0 and a
        computed 402.7 becomes 360.0."

        Design: Corner/cross-cutting complexity layers/stale_species_profile_version_rejected_then_correct_version_succeeds
        """
        set_logical_clock(api)
        species = create_species(api)
        stale_version = species["version"]

        first = validate_success(
            api.create_drying_schedule(
                create_drying_schedule_payload(
                    species["id"], expected_species_profile_version=stale_version
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        assert first["planned_dry_hours"] == pytest.approx(265.0, abs=0.01)
        assert (
            validate_success(api.get_species_profile(species["id"], ADMIN))["version"]
            == stale_version + 1
        )

        validate_error(
            api.create_drying_schedule(
                create_drying_schedule_payload(
                    species["id"],
                    expected_species_profile_version=stale_version,
                    schedule_code="RO-125",
                    thickness_in=1.25,
                ),
                ADMIN,
            ),
            "ERR_STALE_SPECIES_PROFILE_VERSION",
            expected_status=412,
        )
        _rows, meta = validate_paginated(
            api.list_drying_schedules(
                ADMIN, params={"species_profile_id": species["id"]}
            )
        )
        assert meta["total_count"] == 1
        current = validate_success(api.get_species_profile(species["id"], ADMIN))
        assert current["version"] == stale_version + 1

        second = validate_success(
            api.create_drying_schedule(
                create_drying_schedule_payload(
                    species["id"],
                    expected_species_profile_version=current["version"],
                    schedule_code="RO-125",
                    thickness_in=1.25,
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        assert second["schedule_code"] == "RO-125"
        assert second["planned_dry_hours"] == pytest.approx(360.0, abs=0.01)
        assert (
            validate_success(api.get_species_profile(species["id"], ADMIN))["version"]
            == stale_version + 2
        )


class TestFlooringLotConcurrencyToken:
    """The milling-time lot revision is spent by the first grade run, and the
    refused replay spends nothing."""

    def test_the_milling_version_is_refused_after_the_first_run_and_two_drafts_coexist(
        self, api
    ):
        """PRD 2.5: "Creating a grade run requires a non-optional `expected_lot_version`
        field carrying the client's last observed `version` of the referenced
        `FlooringLot`; a value that does not equal the lot's current `version` is
        refused with `ERR_STALE_LOT_VERSION` (HTTP 412)."

        PRD 2.5: "A successful create increments `FlooringLot.version`, so a caller that
        read the lot before an intervening write is refused until it re-reads it."

        Design: Corner/cross-cutting complexity layers/stale_lot_version_rejected_on_grade_run_create
        """
        ctx = setup_milled_lot(api)
        lot_id = ctx["lot"]["id"]
        milling_version = ctx["lot"]["version"]

        first = validate_success(
            api.create_grade_run(
                create_grade_run_payload(
                    lot_id, milling_version, inspector_ruleset="NHLA"
                ),
                INSPECTOR,
            ),
            expected_status=201,
        )
        assert first["status"] == "DRAFT"
        assert refetch_lot(api, lot_id)["version"] > milling_version

        validate_error(
            api.create_grade_run(
                create_grade_run_payload(
                    lot_id, milling_version, inspector_ruleset="MILL_CHARACTER"
                ),
                INSPECTOR,
            ),
            "ERR_STALE_LOT_VERSION",
            expected_status=412,
        )
        _rows, meta = validate_paginated(
            api.list_grade_runs(INSPECTOR, params={"flooring_lot_id": lot_id})
        )
        assert meta["total_count"] == 1

        current_version = refetch_lot(api, lot_id)["version"]
        second = validate_success(
            api.create_grade_run(
                create_grade_run_payload(
                    lot_id, current_version, inspector_ruleset="MILL_CHARACTER"
                ),
                INSPECTOR,
            ),
            expected_status=201,
        )
        assert second["inspector_ruleset"] == "MILL_CHARACTER"
        assert refetch_lot(api, lot_id)["version"] == milling_version + 2

        _rows, meta = validate_paginated(
            api.list_grade_runs(INSPECTOR, params={"flooring_lot_id": lot_id})
        )
        assert meta["total_count"] == 2


class TestWarrantyPostureFloor:
    """The restriction floor is inclusive on the open side: one cent decides the
    posture."""

    def test_the_last_cent_up_to_the_floor_flips_the_line_open(self, api):
        """PRD 3.9: "The `posture` is then `FROZEN` whenever `freeze_override` is true,
        regardless of money; otherwise it is `RESTRICTED` when `warranty_balance_cents`
        is below the restriction floor of 500000 cents; and otherwise it is `OPEN`."

        PRD 3.9: "A `MillAdmin` funds a reserve by supplying an `amount_cents` to add,
        which increases both `warranty_funded_total_cents` and `warranty_balance_cents`
        before the posture is recomputed — the path by which a `RESTRICTED` line returns
        to `OPEN`."

        PRD 3.1: "On creation `warranty_balance_cents` equals
        `warranty_funded_total_cents`, `warranty_committed_cents` is 0,
        `freeze_override` is false, and `posture` is derived as described in §3.9."

        Design: Corner/cross-cutting complexity layers/warranty_posture_flips_exactly_at_the_five_hundred_thousand_floor
        """
        ctx = setup_warranty_line(
            api, line_overrides={"warranty_funded_total_cents": 300000}
        )
        line_id = ctx["product_line"]["id"]

        opening = validate_success(
            api.get_product_line(line_id, ADMIN), expected_status=200
        )
        assert opening["warranty_balance_cents"] == 300000
        assert opening["warranty_committed_cents"] == 0
        assert opening["posture"] == "RESTRICTED"
        assert opening["freeze_override"] is False

        just_under = validate_success(
            api.fund_warranty(line_id, fund_warranty_payload(199999), ADMIN),
            expected_status=200,
        )
        assert just_under["warranty_funded_total_cents"] == 499999
        assert just_under["warranty_balance_cents"] == 499999
        assert just_under["posture"] == "RESTRICTED"
        assert just_under["freeze_override"] is False

        exactly_at = validate_success(
            api.fund_warranty(line_id, fund_warranty_payload(1), ADMIN),
            expected_status=200,
        )
        assert exactly_at["warranty_funded_total_cents"] == 500000
        assert exactly_at["warranty_balance_cents"] == 500000
        assert exactly_at["posture"] == "OPEN"
        assert exactly_at["freeze_override"] is False


class TestCoreStockAggregateSurvivesAVoid:
    """The reserved footage is recomputed from the surviving lots rather than
    decremented, so a void lands it on the remaining reservation."""

    def test_voiding_one_of_two_lots_leaves_the_other_lots_reservation(self, api):
        """PRD 3.6: "For an engineered lot the server computes `reserved_core_sf` as the
        drawn `input_dry_bf` multiplied by 1.10 square feet of core per board foot,
        rounded half up to two decimal places — a draw of 2900 board feet reserves
        3190.00 square feet — and adds it to the core stock's `reserved_square_feet`,
        which is at all times the total `reserved_core_sf` of the non-voided lots on
        that stock."

        PRD 3.6: "A void unwinds every reservation the lot made: for an `ENGINEERED` lot
        the `reserved_core_sf` is released back so that the core stock's
        `reserved_square_feet` no longer counts it; the lot's `input_dry_bf` is restored
        to the supplying charge's `remaining_dry_bf`, and a charge that had been
        auto-closed returns from `CLOSED` to `RELEASED`; and for a lot already `MILLED`,
        every byproduct batch of the lot has its `available_tons` set to 0."

        PRD 3.1: "Engineered lines also consume substrate."

        Design: Corner/cross-cutting complexity layers/core_stock_reserved_square_feet_reconciles_after_create_and_void
        """
        ctx = setup_released_charge(api)
        charge_id = ctx["charge"]["id"]
        line = create_product_line(api, ctx["species"], **ENGINEERED_LINE)
        core = create_core_stock(api, line, **CORE_STOCK)

        big = validate_success(
            api.create_flooring_lot(
                create_flooring_lot_payload(
                    line["id"], charge_id, 2900, core_stock_id=core["id"]
                ),
                SUPERVISOR,
            ),
            expected_status=201,
        )
        assert big["reserved_core_sf"] == pytest.approx(3190.00, abs=0.01)

        small = validate_success(
            api.create_flooring_lot(
                create_flooring_lot_payload(
                    line["id"], charge_id, 100, core_stock_id=core["id"]
                ),
                SUPERVISOR,
            ),
            expected_status=201,
        )
        assert small["reserved_core_sf"] == pytest.approx(110.00, abs=0.01)
        assert refetch_core_stock(api, core["id"])[
            "reserved_square_feet"
        ] == pytest.approx(3300.00, abs=0.01)

        voided = validate_success(
            api.void_flooring_lot(
                big["id"],
                void_lot_payload(void_reason="Core lot recalled by the panel supplier."),
                SUPERVISOR,
            ),
            expected_status=200,
        )
        assert voided["status"] == "VOIDED"
        assert voided["void_reason"] == "Core lot recalled by the panel supplier."
        assert voided["reserved_core_sf"] == pytest.approx(3190.00, abs=0.01)
        assert refetch_charge(api, charge_id)["remaining_dry_bf"] == pytest.approx(
            8872.50, abs=0.01
        )

        final = refetch_core_stock(api, core["id"])
        assert final["reserved_square_feet"] == pytest.approx(110.00, abs=0.01)
        assert final["available_square_feet"] == pytest.approx(4000.00, abs=0.01)


class TestFreezeCascadeIsVisibleAtOnce:
    """The freeze response already carries the new posture and the very next
    reads already show the hold."""

    def test_the_hold_is_readable_and_enforced_on_the_first_attempt_after_the_freeze(
        self, api
    ):
        """PRD 3.9: "The same role may administratively freeze a line with a supplied
        `freeze_reason`, which sets `freeze_override` to true and forces the posture to
        `FROZEN` from either `OPEN` or `RESTRICTED`; when the line was `OPEN`, the freeze
        also holds every `SCHEDULED` prefinish run on it, whereas a line that was
        already `RESTRICTED` has held those runs already."

        PRD 3.8: "When a product line's posture becomes `RESTRICTED` or `FROZEN`, every
        `SCHEDULED` run whose snapshotted `product_line_id` matches that line moves to
        `HELD` with a `hold_reason` recorded."

        PRD 3.8: "Starting a `HELD` run is refused with
        `ERR_PREFINISH_RUN_STATE_INVALID`."

        PRD 3.8: "Pushing 5000 linear feet of 3.190-inch boards through a three-pass
        line therefore consumes 47.85 litres."

        Design: Corner/consistency model/freeze_effects_are_visible_immediately_without_polling
        """
        ctx = setup_scheduled_prefinish_run(
            api, ruleset="NHLA", bundles=[dict(FULL_LOT_BUNDLE)]
        )
        line_id = ctx["product_line"]["id"]
        run_id = ctx["prefinish_run"]["id"]

        frozen_line = validate_success(
            api.freeze_product_line(
                line_id,
                freeze_product_line_payload(
                    freeze_reason="Coating supplier recall under investigation."
                ),
                ADMIN,
            ),
            expected_status=200,
        )
        assert frozen_line["posture"] == "FROZEN"
        assert frozen_line["freeze_override"] is True

        held = validate_success(
            api.get_prefinish_run(run_id, SCHEDULER), expected_status=200
        )
        assert held["status"] == "HELD"
        assert held["hold_reason"] is not None
        assert held["coating_liters"] == pytest.approx(47.85, abs=0.01)

        rows, meta = validate_paginated(
            api.list_prefinish_runs(
                SCHEDULER, params={"product_line_id": line_id, "status": "HELD"}
            )
        )
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert rows[0]["id"] == run_id

        validate_error(
            api.start_prefinish_run(run_id, SCHEDULER),
            "ERR_PREFINISH_RUN_STATE_INVALID",
            expected_status=409,
        )
        assert validate_success(api.get_prefinish_run(run_id, SCHEDULER))[
            "coating_liters"
        ] == pytest.approx(47.85, abs=0.01)
