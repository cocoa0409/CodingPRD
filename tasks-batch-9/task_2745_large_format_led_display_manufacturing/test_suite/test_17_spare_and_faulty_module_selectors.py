"""The two deterministic pickers: contracted spares and the module a claim blames.

The spare selector filters on state, family and existing reservation and then
ranks the survivors weakest bin first; the faulty-module selector looks only
inside the claim's own cabinet and takes the dimmest panel there.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers.api_errors import ERR_NO_ELIGIBLE_SPARE_MODULE
from test_helpers.assertions import (
    assert_2dp,
    assert_case_fields,
    assert_cents,
    assert_contract_fields,
    assert_instant_equals,
    assert_module_fields,
    assert_page_meta,
    assert_version,
    ids_of,
)
from test_helpers.constants import (
    CASE_APPROVED,
    CLOCK_EPOCH,
    CONTRACT_PENDING,
    WARRANTY_CASE_INSTANT,
)
from test_helpers.factories import FP16_STD, spare_reservation_payload

#: The FP10-IN and FP16-STD families both publish reference_color_x 0.3128 and
#: reference_color_y 0.3290, so an x offset alone sets the chroma error.
MATCHED_COLOR_X = 0.3130
MATCHED_COLOR_Y = 0.3292
LETTER_B_COLOR_X = 0.3178

#: Three eligible spares, one per observable bin, plus the brightnesses that put
#: them either side of the 4800 nit digit floor.
A1_SPARE_NITS = 4900
A2_SPARE_NITS = 4799
B1_SPARE_NITS = 4850

#: A dead-pixel count of 5 exceeds the FP10-IN allowance of 3, so the module lands
#: in REWORK instead of PIXEL_TESTED.
FAILING_DEAD_PIXELS = 5

#: One second past the clock's startup default, so the second candidate row is
#: written strictly after the first.
ONE_SECOND_LATER = "2026-08-01T00:00:01.000Z"

#: A GOLD holding of 300 basis points over a single-module wall obliges one spare.
GOLD_SPARE_REQUIRED_COUNT = 1

#: The FP16-STD family needs 150.00 kg/sqm of structural capacity.
FP16_REQUIRED_LOAD_KG_PER_SQM = 150.00

#: Two panels fitted in the claim's own cabinet, and one dimmer module that never
#: left stock.
DIM_INSTALLED_NITS = 4900
BRIGHT_INSTALLED_NITS = 4950
STOCK_NITS = 4700

#: The field measurement on a 5000 nit family: an 8.00 percent loss.
FIELD_BRIGHTNESS_NITS = 4600

#: 2026-08-05T09:00Z to 2027-02-05T09:00Z is 184 whole days, so floor(184 / 30).
ELAPSED_WARRANTY_MONTHS = 6
ALLOWED_DEGRADATION_PCT = 5.00
DEGRADATION_PCT = 8.00
SHORTFALL_PCT = 3.00

#: round(102400 x min(3.00 / 100 x 2.5, 0.6)) on a 0.1024 sqm FP16-STD cabinet.
SHORTFALL_SEVERITY_CREDIT_CENTS = 7680

#: A MAJOR claim on a GOLD contract is due in the full eight contracted hours.
GOLD_MAJOR_RESPONSE_DEADLINE = "2027-02-05T17:00:00.000Z"


def _seven_modules_of_which_three_are_eligible(plant):
    """A contracted wall surrounded by stock in every disqualifying condition."""
    model = plant.register_model()
    foreign_model = plant.register_model(FP16_STD)
    project = plant.create_project(model["id"])
    contract = plant.sell_contract(project["id"])

    a1_spare = plant.calibrated_module(
        model["id"],
        serial_no="M-A1",
        measured_brightness_nits=A1_SPARE_NITS,
        measured_color_x=MATCHED_COLOR_X,
        measured_color_y=MATCHED_COLOR_Y,
    )
    a2_spare = plant.calibrated_module(
        model["id"],
        serial_no="M-A2",
        measured_brightness_nits=A2_SPARE_NITS,
        measured_color_x=MATCHED_COLOR_X,
        measured_color_y=MATCHED_COLOR_Y,
    )
    b1_spare = plant.calibrated_module(
        model["id"],
        serial_no="M-B1",
        measured_brightness_nits=B1_SPARE_NITS,
        measured_color_x=LETTER_B_COLOR_X,
        measured_color_y=MATCHED_COLOR_Y,
    )

    untested = plant.register_module(model["id"], "M-MANUFACTURED")
    pixel_tested = plant.register_module(model["id"], "M-PIXEL-TESTED")
    plant.pixel_test(pixel_tested["id"])
    in_rework = plant.register_module(model["id"], "M-REWORK")
    plant.pixel_test(in_rework["id"], FAILING_DEAD_PIXELS, 1)
    foreign = plant.calibrated_module(
        foreign_model["id"],
        serial_no="M-FOREIGN-B1",
        measured_brightness_nits=B1_SPARE_NITS,
        measured_color_x=LETTER_B_COLOR_X,
        measured_color_y=MATCHED_COLOR_Y,
    )

    return {
        "contract": contract,
        "a1": a1_spare,
        "a2": a2_spare,
        "b1": b1_spare,
        "ineligible": [untested, pixel_tested, in_rework, foreign],
    }


class TestSpareSelectorEligibilityAndRanking:
    """Four eligibility clauses, then an inverted ranking over the survivors."""

    def test_the_weakest_bin_is_reserved_first_and_a1_stock_is_held_back(self, plant):
        """Candidates are ordered by `color_bin_rank` **descending**, so the weakest
        bins are reserved first and `A1` stock is held back for production installs;
        ties are broken by `measured_brightness_nits` **ascending**, and any
        remaining tie by `created_at` ascending.

        Design: Corner/calculations/spare_reservation_skips_uncalibrated_and_foreign_modules
        """
        stock = _seven_modules_of_which_three_are_eligible(plant)
        contract = stock["contract"]
        assert_version(contract, 1, "contract")
        assert_version(stock["b1"], 3, "module")

        first_pick = plant.reserve_spare(contract["id"])
        second_pick = plant.reserve_spare(contract["id"])

        assert first_pick["id"] == stock["b1"]["id"]
        assert second_pick["id"] == stock["a2"]["id"]
        assert_module_fields(first_pick, reserved_service_contract_id=contract["id"])
        assert_module_fields(second_pick, reserved_service_contract_id=contract["id"])
        assert_version(first_pick, 4, "module")
        assert_module_fields(
            plant.module(stock["a1"]["id"]), reserved_service_contract_id=None
        )
        held = plant.contract(contract["id"])
        assert_contract_fields(
            held,
            contract_state=CONTRACT_PENDING,
            spare_reserved_count=2,
            spare_required_count=GOLD_SPARE_REQUIRED_COUNT,
        )
        assert_version(held, 3, "contract")

    def test_uncalibrated_and_foreign_stock_is_never_a_candidate(self, plant):
        """Eligible candidates are modules whose `module_state` is `CALIBRATED`,
        whose `display_model_id` matches the display model pinned by the contract's
        project, and whose `reserved_service_contract_id` is unset — modules that are
        `MANUFACTURED`, `PIXEL_TESTED`, in `REWORK`, `INSTALLED`, `RETURNED` or
        `SCRAPPED` are never candidates. If the eligible pool is empty the
        reservation is refused with `ERR_NO_ELIGIBLE_SPARE_MODULE`.

        Design: Corner/calculations/spare_reservation_skips_uncalibrated_and_foreign_modules
        """
        stock = _seven_modules_of_which_three_are_eligible(plant)
        contract = stock["contract"]
        for _ in range(3):
            plant.reserve_spare(contract["id"])

        response = plant.api.reserve_spare(
            contract["id"],
            spare_reservation_payload(plant.contract_version(contract["id"])),
            plant.service,
        )

        validate_error(response, ERR_NO_ELIGIBLE_SPARE_MODULE, 409)
        for module in stock["ineligible"]:
            assert_module_fields(
                plant.module(module["id"]), reserved_service_contract_id=None
            )
        assert_contract_fields(plant.contract(contract["id"]), spare_reserved_count=3)


class TestSpareSelectorTieBreak:
    """When both declared ranking keys tie, the older row leaves stock first."""

    def test_two_indistinguishable_spares_are_separated_by_creation_order(self, plant):
        """Candidates are ordered by `color_bin_rank` **descending**, so the weakest
        bins are reserved first and `A1` stock is held back for production installs;
        ties are broken by `measured_brightness_nits` **ascending**, and any
        remaining tie by `created_at` ascending.

        Design: Corner/calculations/spare_reservation_tie_breaks_on_created_at_ascending
        """
        model = plant.register_model()
        project = plant.create_project(model["id"])
        contract = plant.sell_contract(project["id"])
        plant.set_clock(CLOCK_EPOCH)
        early = plant.calibrated_module(
            model["id"],
            serial_no="M-EARLY",
            measured_brightness_nits=A1_SPARE_NITS,
            measured_color_x=MATCHED_COLOR_X,
            measured_color_y=MATCHED_COLOR_Y,
        )
        plant.set_clock(ONE_SECOND_LATER)
        late = plant.calibrated_module(
            model["id"],
            serial_no="M-LATE",
            measured_brightness_nits=A1_SPARE_NITS,
            measured_color_x=MATCHED_COLOR_X,
            measured_color_y=MATCHED_COLOR_Y,
        )
        assert_module_fields(early, color_bin="A1", color_bin_rank=0)
        assert_module_fields(late, color_bin="A1", color_bin_rank=0)
        assert early["measured_brightness_nits"] == late["measured_brightness_nits"]

        picked = plant.reserve_spare(contract["id"])

        assert picked["id"] == early["id"]
        assert_module_fields(
            plant.module(late["id"]), reserved_service_contract_id=None
        )
        assert_contract_fields(plant.contract(contract["id"]), spare_reserved_count=1)


def _commissioned_wall_with_a_dimmer_module_in_stock(plant):
    """A live GOLD wall, a responded brightness claim, and dimmer free stock."""
    scene = plant.commissioned_scene(
        model_base=FP16_STD,
        revision_overrides={"structural_load_kg_per_sqm": FP16_REQUIRED_LOAD_KG_PER_SQM},
        brightnesses=[DIM_INSTALLED_NITS, BRIGHT_INSTALLED_NITS],
        chroma=[(MATCHED_COLOR_X, MATCHED_COLOR_Y), (0.3128, 0.3291)],
    )
    scene.stock = plant.calibrated_module(
        scene.model["id"],
        serial_no="M-STOCK",
        measured_brightness_nits=STOCK_NITS,
        measured_color_x=MATCHED_COLOR_X,
        measured_color_y=MATCHED_COLOR_Y,
    )
    plant.set_clock(WARRANTY_CASE_INSTANT)
    case = plant.open_degradation_case(
        scene.contract["id"],
        scene.cabinet["id"],
        measured_brightness_nits=FIELD_BRIGHTNESS_NITS,
    )
    plant.respond(case["id"])
    scene.case = plant.case(case["id"])
    return scene


class TestFaultyModuleSelectorScope:
    """A degradation claim is about the wall, so the warehouse never competes."""

    def test_the_dimmest_installed_panel_beats_a_dimmer_module_in_stock(self, plant):
        """For a `BRIGHTNESS_DEGRADATION` case the server selects it: among the
        modules whose `cabinet_id` is the case's cabinet and whose `module_state` is
        `INSTALLED` — returned modules from earlier swaps are excluded even though
        they retain a `cabinet_id` — it takes the one with the lowest
        `measured_brightness_nits`, because the dimmest panel is what the
        degradation claim is about, breaking ties by `created_at` ascending.

        Design: Corner/calculations/warranty_approval_resolves_the_dimmest_installed_module
        """
        scene = _commissioned_wall_with_a_dimmer_module_in_stock(plant)
        dim, bright = scene.modules[0], scene.modules[1]

        approved = plant.assess(
            scene.case["id"], decision="APPROVE", assessment_basis="SHORTFALL_SEVERITY"
        )

        assert_case_fields(
            approved,
            case_state=CASE_APPROVED,
            resolved_faulty_module_id=dim["id"],
            replacement_module_id=None,
            denial_reason=None,
        )
        assert approved["resolved_faulty_module_id"] != bright["id"]
        assert approved["resolved_faulty_module_id"] != scene.stock["id"]

    def test_the_approval_pins_the_curve_arithmetic_and_stays_reverse_findable(self, plant):
        """`allowed_degradation_pct` is the brightness loss the warranty concedes by
        then: 50 percent — the guaranteed total loss over the warranty's five-year,
        60-month term — multiplied by `elapsed_warranty_months`, divided by 60,
        rounded to 2 decimal places. Service cases can be listed by
        `service_contract_id`, `cabinet_id`, `faulty_module_id`,
        `resolved_faulty_module_id`, `replacement_module_id`, `case_type` and
        `case_state`.

        Design: Corner/calculations/warranty_approval_resolves_the_dimmest_installed_module
        """
        scene = _commissioned_wall_with_a_dimmer_module_in_stock(plant)
        dim, bright = scene.modules[0], scene.modules[1]

        approved = plant.assess(
            scene.case["id"], decision="APPROVE", assessment_basis="SHORTFALL_SEVERITY"
        )

        assert approved["elapsed_warranty_months"] == ELAPSED_WARRANTY_MONTHS
        assert_2dp(
            approved["allowed_degradation_pct"], ALLOWED_DEGRADATION_PCT, "allowed_degradation_pct"
        )
        assert_2dp(approved["degradation_pct"], DEGRADATION_PCT, "degradation_pct")
        assert_2dp(approved["shortfall_pct"], SHORTFALL_PCT, "shortfall_pct")
        assert_case_fields(approved, assessment_basis="SHORTFALL_SEVERITY", response_breached=False)
        assert_cents(approved["credit_cents"], SHORTFALL_SEVERITY_CREDIT_CENTS, "credit_cents")
        assert_instant_equals(
            approved["response_deadline_at"],
            GOLD_MAJOR_RESPONSE_DEADLINE,
            "response_deadline_at",
        )

        matched, matched_meta = validate_paginated(
            plant.api.list_service_cases(
                plant.service, {"resolved_faulty_module_id": dim["id"]}
            )
        )
        empty, empty_meta = validate_paginated(
            plant.api.list_service_cases(
                plant.service, {"resolved_faulty_module_id": bright["id"]}
            )
        )

        assert ids_of(matched) == [scene.case["id"]]
        assert_page_meta(matched_meta, total_count=1, has_more=False)
        assert empty == []
        assert_page_meta(empty_meta, total_count=0, has_more=False)
