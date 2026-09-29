"""Referential and conditional rules on the service side of the plant.

The tier floor is selected by tier rather than compared to one global number, a
project carries at most one contract whatever its tier, the required measurement
follows the case type, and the two referential hops behind a claim are checked by
joining the contract's project rather than by resolving ids. The colour-bin gate
then compares an ordinal neither module ever declared.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.api_errors import (
    ERR_COLOR_BIN_MISMATCH,
    ERR_CONTRACT_ALREADY_EXISTS,
    ERR_MEASUREMENT_REQUIRED,
    ERR_MODULE_GRID_MISMATCH,
    ERR_SPARE_PCT_BELOW_MINIMUM,
)
from test_helpers.assertions import (
    assert_2dp,
    assert_case_fields,
    assert_cents,
    assert_contract_fields,
    assert_instant_equals,
    assert_module_fields,
    assert_page_meta,
    assert_project_fields,
    assert_version,
    ids_of,
)
from test_helpers.constants import (
    CASE_APPROVED,
    CASE_FULFILLED,
    CASE_OPEN,
    CONTRACT_ACTIVE,
    CONTRACT_PENDING,
    MODULE_CALIBRATED,
    MODULE_INSTALLED,
    MODULE_RETURNED,
    POSTURE_NORMAL,
    WARRANTY_CASE_INSTANT,
)
from test_helpers.factories import (
    FP16_STD,
    fulfil_payload,
    service_contract_payload,
)

#: GOLD holds a 300 basis point floor, SILVER a 200 point floor, so 299 points
#: sits between the two.
GOLD_SPARE_FLOOR_BP = 300
BETWEEN_TIERS_SPARE_BP = 299
GOLD_RESPONSE_HOURS = 8
SILVER_RESPONSE_HOURS = 24

#: A single-module wall obliges one spare at any holding above zero.
SINGLE_MODULE_SPARE_REQUIRED_COUNT = 1

#: The BRONZE contract already on the project under test.
BRONZE_SPARE_BP = 100
BRONZE_TERM_MONTHS = 12

#: FP16-STD needs 150.00 kg/sqm of certified capacity and holds two slots.
FP16_REQUIRED_LOAD_KG_PER_SQM = 150.00

#: The two panels fitted in the wall under test.
DIM_INSTALLED_NITS = 4900
BRIGHT_INSTALLED_NITS = 4950
DIM_INSTALLED_CHROMA = (0.3130, 0.3292)
BRIGHT_INSTALLED_CHROMA = (0.3128, 0.3291)

#: A MAJOR claim on a GOLD contract is due in the full eight contracted hours.
GOLD_MAJOR_RESPONSE_DEADLINE = "2027-02-05T17:00:00.000Z"

SYMPTOM = "Quadrant one is dark"


def _module_fault_without_the_module(service_contract_id, cabinet_id):
    """A module-fault claim that omits the module its type demands."""
    return {
        "service_contract_id": service_contract_id,
        "cabinet_id": cabinet_id,
        "case_type": "MODULE_FAULT",
        "severity": "MAJOR",
        "symptom": SYMPTOM,
    }


def _degradation_without_the_measurement(service_contract_id, cabinet_id):
    """A brightness claim that omits the measurement its type demands."""
    return {
        "service_contract_id": service_contract_id,
        "cabinet_id": cabinet_id,
        "case_type": "BRIGHTNESS_DEGRADATION",
        "severity": "MAJOR",
        "symptom": SYMPTOM,
    }


def _module_fault_naming(service_contract_id, cabinet_id, faulty_module_id):
    payload = _module_fault_without_the_module(service_contract_id, cabinet_id)
    payload["faulty_module_id"] = faulty_module_id
    return payload


class TestTierSpareFloor:
    """The floor is selected by tier, so one holding straddles two verdicts."""

    def test_the_same_holding_fails_gold_and_passes_silver(self, plant):
        """Two rules guard the sale, in this order: a project that already carries
        a contract is refused with `ERR_CONTRACT_ALREADY_EXISTS`, and only then is
        the tier's spare floor checked — `spare_pct_bp` must be at least 100 basis
        points for `BRONZE`, 200 for `SILVER` and 300 for `GOLD`, with anything
        below refused as `ERR_SPARE_PCT_BELOW_MINIMUM`.

        Design: Corner/validations/spare_percentage_below_the_tier_minimum_rejected
        """
        model = plant.register_model()
        refused_project = plant.create_project(model["id"], customer_name="Gold Short")
        gold_project = plant.create_project(model["id"], customer_name="Gold Exact")
        silver_project = plant.create_project(model["id"], customer_name="Silver Same")

        refused = plant.api.create_service_contract(
            service_contract_payload(
                refused_project["id"], tier="GOLD", spare_pct_bp=BETWEEN_TIERS_SPARE_BP
            ),
            plant.service,
        )
        at_floor = plant.api.create_service_contract(
            service_contract_payload(
                gold_project["id"], tier="GOLD", spare_pct_bp=GOLD_SPARE_FLOOR_BP
            ),
            plant.service,
        )
        below_gold_above_silver = plant.api.create_service_contract(
            service_contract_payload(
                silver_project["id"],
                tier="SILVER",
                spare_pct_bp=BETWEEN_TIERS_SPARE_BP,
            ),
            plant.service,
        )

        validate_error(refused, ERR_SPARE_PCT_BELOW_MINIMUM, 422)
        gold = validate_success(at_floor, 201)
        silver = validate_success(below_gold_above_silver, 201)
        assert gold["spare_pct_bp"] == GOLD_SPARE_FLOOR_BP
        assert silver["spare_pct_bp"] == BETWEEN_TIERS_SPARE_BP
        assert_contract_fields(
            gold,
            contract_state=CONTRACT_PENDING,
            response_hours=GOLD_RESPONSE_HOURS,
            spare_required_count=SINGLE_MODULE_SPARE_REQUIRED_COUNT,
        )
        assert_contract_fields(
            silver,
            contract_state=CONTRACT_PENDING,
            response_hours=SILVER_RESPONSE_HOURS,
            spare_required_count=SINGLE_MODULE_SPARE_REQUIRED_COUNT,
        )
        rows, meta = validate_paginated(
            plant.api.list_service_contracts(
                plant.service, {"project_id": refused_project["id"]}
            )
        )
        assert rows == []
        assert_page_meta(meta, total_count=0, has_more=False)


class TestOneContractPerProject:
    """The uniqueness is on the project, whatever tier or state the first holds."""

    def test_a_different_tier_does_not_make_it_a_different_contract(self, plant):
        """A `ServiceManager` sells at most one service contract per project.

        Design: Corner/validations/a_project_may_carry_only_one_service_contract
        """
        model = plant.register_model()
        project = plant.create_project(model["id"])
        first = plant.sell_contract(
            project["id"],
            tier="BRONZE",
            spare_pct_bp=BRONZE_SPARE_BP,
            term_months=BRONZE_TERM_MONTHS,
        )

        response = plant.api.create_service_contract(
            service_contract_payload(project["id"], tier="GOLD"), plant.service
        )

        validate_error(response, ERR_CONTRACT_ALREADY_EXISTS, 409)
        rows, meta = validate_paginated(
            plant.api.list_service_contracts(
                plant.service, {"project_id": project["id"]}
            )
        )
        assert ids_of(rows) == [first["id"]]
        assert_page_meta(meta, total_count=1, has_more=False)
        held = plant.contract(first["id"])
        assert_contract_fields(held, tier="BRONZE", contract_state=CONTRACT_PENDING)
        assert held["term_months"] == BRONZE_TERM_MONTHS
        assert_version(held, 1, "contract")
        assert_project_fields(
            plant.project(project["id"]), service_posture=POSTURE_NORMAL
        )


def _live_two_slot_wall(plant):
    """A commissioned FP16-STD wall on an ACTIVE GOLD contract, clock in warranty."""
    scene = plant.commissioned_scene(
        model_base=FP16_STD,
        revision_overrides={"structural_load_kg_per_sqm": FP16_REQUIRED_LOAD_KG_PER_SQM},
        brightnesses=[DIM_INSTALLED_NITS, BRIGHT_INSTALLED_NITS],
        chroma=[DIM_INSTALLED_CHROMA, BRIGHT_INSTALLED_CHROMA],
    )
    plant.set_clock(WARRANTY_CASE_INSTANT)
    return scene


class TestMeasurementRequiredFollowsTheCaseType:
    """Neither omission is a missing required field in general — only for its type."""

    def test_each_type_misses_the_field_the_other_type_must_omit(self, plant):
        """A `MODULE_FAULT` case **requires** `faulty_module_id`, the caller-nominated
        failed module, and must **omit** `measured_brightness_nits`. A payload that
        omits the measurement its type demands is refused with
        `ERR_MEASUREMENT_REQUIRED`.

        Design: Corner/validations/case_type_dictates_which_measurement_is_required
        """
        scene = _live_two_slot_wall(plant)
        contract_id = scene.contract["id"]
        cabinet_id = scene.cabinet["id"]

        fault_without_module = plant.api.create_service_case(
            _module_fault_without_the_module(contract_id, cabinet_id), plant.service
        )
        degradation_without_measurement = plant.api.create_service_case(
            _degradation_without_the_measurement(contract_id, cabinet_id), plant.service
        )

        validate_error(fault_without_module, ERR_MEASUREMENT_REQUIRED, 422)
        validate_error(degradation_without_measurement, ERR_MEASUREMENT_REQUIRED, 422)
        rows, meta = validate_paginated(
            plant.api.list_service_cases(
                plant.service, {"service_contract_id": contract_id}
            )
        )
        assert rows == []
        assert_page_meta(meta, total_count=0, has_more=False)

    def test_the_named_module_completes_a_fault_claim_without_any_measurement(self, plant):
        """A `BRIGHTNESS_DEGRADATION` case **requires** `measured_brightness_nits`,
        the field brightness measurement, which must be zero or greater, and must
        **omit** `faulty_module_id` — a degradation claim is about the whole panel,
        and which module gets swapped is the server's decision, not the caller's.

        Design: Corner/validations/case_type_dictates_which_measurement_is_required
        """
        scene = _live_two_slot_wall(plant)
        bright = scene.modules[1]

        response = plant.api.create_service_case(
            _module_fault_naming(
                scene.contract["id"], scene.cabinet["id"], bright["id"]
            ),
            plant.service,
        )

        case = validate_success(response, 201)
        assert_case_fields(
            case,
            case_state=CASE_OPEN,
            case_type="MODULE_FAULT",
            severity="MAJOR",
            faulty_module_id=bright["id"],
            resolved_faulty_module_id=None,
            replacement_module_id=None,
            response_breached=False,
        )
        assert case["measured_brightness_nits"] is None
        assert_instant_equals(
            case["reported_at"], WARRANTY_CASE_INSTANT, "reported_at"
        )
        assert_instant_equals(
            case["response_deadline_at"],
            GOLD_MAJOR_RESPONSE_DEADLINE,
            "response_deadline_at",
        )
        rows, meta = validate_paginated(
            plant.api.list_service_cases(
                plant.service, {"service_contract_id": scene.contract["id"]}
            )
        )
        assert ids_of(rows) == [case["id"]]
        assert_page_meta(meta, total_count=1, has_more=False)


class TestClaimReferentialScope:
    """Both hops are joins through the contract's project, not id resolutions."""

    def test_a_foreign_cabinet_and_a_foreign_module_share_one_code(self, plant):
        """Three rules guard case creation in this order: the contract must be
        `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`); then the named cabinet must belong to
        the contract's project **and**, when a faulty module is nominated, that
        module must be installed in that very cabinet, with either violation refused
        as `ERR_MODULE_GRID_MISMATCH`; then the payload must match the case type.

        Design: Corner/validations/case_cabinet_and_faulty_module_must_belong_to_the_contract
        """
        scene = _live_two_slot_wall(plant)
        fitted = scene.modules[0]
        other_project = plant.create_project(
            scene.model["id"], customer_name="Neighbouring Wall"
        )
        plant.approve_engineering(
            other_project["id"],
            structural_load_kg_per_sqm=FP16_REQUIRED_LOAD_KG_PER_SQM,
        )
        other_cabinet = plant.plan_cabinet(other_project["id"])
        never_fitted = plant.calibrated_module(
            scene.model["id"],
            serial_no="M-STOCK",
            measured_brightness_nits=DIM_INSTALLED_NITS,
            measured_color_x=DIM_INSTALLED_CHROMA[0],
            measured_color_y=DIM_INSTALLED_CHROMA[1],
        )

        wrong_cabinet = plant.api.create_service_case(
            _module_fault_naming(
                scene.contract["id"], other_cabinet["id"], fitted["id"]
            ),
            plant.service,
        )
        wrong_module = plant.api.create_service_case(
            _module_fault_naming(
                scene.contract["id"], scene.cabinet["id"], never_fitted["id"]
            ),
            plant.service,
        )
        both_belong = plant.api.create_service_case(
            _module_fault_naming(
                scene.contract["id"], scene.cabinet["id"], fitted["id"]
            ),
            plant.service,
        )

        validate_error(wrong_cabinet, ERR_MODULE_GRID_MISMATCH, 422)
        validate_error(wrong_module, ERR_MODULE_GRID_MISMATCH, 422)
        accepted = validate_success(both_belong, 201)
        assert_case_fields(
            accepted, case_state=CASE_OPEN, faulty_module_id=fitted["id"]
        )
        assert_module_fields(
            plant.module(never_fitted["id"]),
            module_state=MODULE_CALIBRATED,
            cabinet_id=None,
            slot_index=None,
        )
        elsewhere, elsewhere_meta = validate_paginated(
            plant.api.list_service_cases(
                plant.service, {"cabinet_id": other_cabinet["id"]}
            )
        )
        assert elsewhere == []
        assert_page_meta(elsewhere_meta, total_count=0, has_more=False)


#: Both spares are calibrated below the 4800 nit digit floor, so the bin letter is
#: the only thing that separates them: an x offset of 0.0002 stays inside the
#: 0.003 letter band while 0.0050 falls outside it.
SPARE_NITS = 4700
A2_SPARE_CHROMA = (0.3130, 0.3290)
B2_SPARE_CHROMA = (0.3178, 0.3290)
A1_RANK = 0
A2_RANK = 1
B2_RANK = 3

#: The frozen baseline over (4900, 4950) and the live score after the dim panel is
#: swapped for a 4700 nit spare.
BASELINE_UNIFORMITY_SCORE = 97.88
AS_BUILT_UNIFORMITY_AFTER_SWAP = 91.63

#: A 300 basis point holding on the two-module wall obliges a single spare, so
#: consuming one of the two held modules leaves the pool exactly at its floor.
TWO_MODULE_SPARE_REQUIRED_COUNT = 1


def _approved_claim_with_two_bins_in_stock(plant):
    """A live wall whose dimmest A1 panel is approved for replacement, with an A2
    and a B2 spare both held against the same contract."""
    scene = _live_two_slot_wall(plant)
    scene.two_bins_away = plant.calibrated_module(
        scene.model["id"],
        serial_no="M-B2-SPARE",
        measured_brightness_nits=SPARE_NITS,
        measured_color_x=B2_SPARE_CHROMA[0],
        measured_color_y=B2_SPARE_CHROMA[1],
    )
    scene.one_bin_away = plant.calibrated_module(
        scene.model["id"],
        serial_no="M-A2-SPARE",
        measured_brightness_nits=SPARE_NITS,
        measured_color_x=A2_SPARE_CHROMA[0],
        measured_color_y=A2_SPARE_CHROMA[1],
    )
    plant.reserve_spare(scene.contract["id"], scene.two_bins_away["id"])
    plant.reserve_spare(scene.contract["id"], scene.one_bin_away["id"])
    case = plant.open_module_fault_case(
        scene.contract["id"], scene.cabinet["id"], scene.modules[0]["id"]
    )
    plant.respond(case["id"])
    scene.case = plant.assess(case["id"], decision="APPROVE")
    scene.contract = plant.contract(scene.contract["id"])
    return scene


class TestColourBinGapOnFulfilment:
    """The gate compares an ordinal neither module ever declared."""

    def test_a_two_bin_gap_is_refused_though_the_spare_is_properly_reserved(self, plant):
        """A nominated replacement must be reserved to this very contract — its
        `reserved_service_contract_id` equal to the case's `service_contract_id` — or
        the request is refused with `ERR_SPARE_NOT_RESERVED`; and its
        `color_bin_rank` must be within 1 of the outgoing module's `color_bin_rank`,
        so that an `A2` panel may be replaced by an `A1`, `A2` or `B1` module but
        never by a `B2`, with a wider gap refused as `ERR_COLOR_BIN_MISMATCH`.

        Design: Corner/validations/replacement_more_than_one_bin_away_rejected
        """
        scene = _approved_claim_with_two_bins_in_stock(plant)
        outgoing = plant.module(scene.modules[0]["id"])
        spare = plant.module(scene.two_bins_away["id"])
        assert_module_fields(outgoing, color_bin="A1", color_bin_rank=A1_RANK)
        assert_module_fields(
            spare,
            color_bin="B2",
            color_bin_rank=B2_RANK,
            reserved_service_contract_id=scene.contract["id"],
        )
        version_before = plant.cabinet_version(scene.cabinet["id"])

        response = plant.api.fulfil_case(
            scene.case["id"],
            fulfil_payload(version_before, spare["id"]),
            plant.service,
        )

        validate_error(response, ERR_COLOR_BIN_MISMATCH, 422)
        assert_case_fields(
            plant.case(scene.case["id"]),
            case_state=CASE_APPROVED,
            replacement_module_id=None,
            resolved_faulty_module_id=outgoing["id"],
        )
        assert_module_fields(
            plant.module(spare["id"]),
            module_state=MODULE_CALIBRATED,
            cabinet_id=None,
            slot_index=None,
            reserved_service_contract_id=scene.contract["id"],
        )
        assert_module_fields(
            plant.module(outgoing["id"]),
            module_state=MODULE_INSTALLED,
            slot_index=1,
        )
        assert plant.cabinet_version(scene.cabinet["id"]) == version_before
        assert_contract_fields(
            plant.contract(scene.contract["id"]),
            contract_state=CONTRACT_ACTIVE,
            spare_reserved_count=2,
        )

    def test_a_gap_of_exactly_one_bin_takes_the_vacated_slot(self, plant):
        """Second, the module pinned as `resolved_faulty_module_id` moves
        `INSTALLED → RETURNED` and gives up its `slot_index` while **retaining** its
        `cabinet_id` for traceability, and the replacement module moves
        `CALIBRATED → INSTALLED` into that vacated `slot_index`, with
        `replaces_module_id` set to the outgoing module's id — the self-referential
        chain that lets an auditor walk a slot's whole replacement history — and its
        `reserved_service_contract_id` cleared, since a module in service is no
        longer a spare.

        Design: Corner/validations/replacement_more_than_one_bin_away_rejected
        """
        scene = _approved_claim_with_two_bins_in_stock(plant)
        outgoing = scene.modules[0]
        spare = plant.module(scene.one_bin_away["id"])
        assert_module_fields(spare, color_bin="A2", color_bin_rank=A2_RANK)
        version_before = plant.cabinet_version(scene.cabinet["id"])
        refused = plant.api.fulfil_case(
            scene.case["id"],
            fulfil_payload(version_before, scene.two_bins_away["id"]),
            plant.service,
        )
        validate_error(refused, ERR_COLOR_BIN_MISMATCH, 422)

        response = plant.api.fulfil_case(
            scene.case["id"],
            fulfil_payload(version_before, spare["id"]),
            plant.service,
        )

        fulfilled = validate_success(response, 200)
        assert_case_fields(
            fulfilled,
            case_state=CASE_FULFILLED,
            replacement_module_id=spare["id"],
            resolved_faulty_module_id=outgoing["id"],
        )
        assert_cents(fulfilled["credit_cents"], 0, "credit_cents")
        assert_module_fields(
            plant.module(outgoing["id"]),
            module_state=MODULE_RETURNED,
            cabinet_id=scene.cabinet["id"],
            slot_index=None,
        )
        assert_module_fields(
            plant.module(spare["id"]),
            module_state=MODULE_INSTALLED,
            cabinet_id=scene.cabinet["id"],
            slot_index=1,
            replaces_module_id=outgoing["id"],
            reserved_service_contract_id=None,
        )
        assert_contract_fields(
            plant.contract(scene.contract["id"]),
            contract_state=CONTRACT_ACTIVE,
            spare_reserved_count=1,
            spare_required_count=TWO_MODULE_SPARE_REQUIRED_COUNT,
        )
        assert_project_fields(
            plant.project(scene.project["id"]), service_posture=POSTURE_NORMAL
        )
        cabinet = plant.cabinet(scene.cabinet["id"])
        assert_2dp(
            cabinet["baseline_uniformity_score"],
            BASELINE_UNIFORMITY_SCORE,
            "baseline_uniformity_score",
        )
        assert_2dp(
            cabinet["as_built_uniformity_score"],
            AS_BUILT_UNIFORMITY_AFTER_SWAP,
            "as_built_uniformity_score",
        )
