"""Two shared write targets, five guarded operations, and one version each.

A cabinet is populated slot by slot and a contract's spare pool is drawn down and
refilled, so both carry a version a client must present. Each file section drives
one endpoint pair the way a real client does — read once, write twice — and pins
what a refused write must leave behind: nothing.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_INVALID_CASE_STATE,
    ERR_STALE_CABINET_VERSION,
    ERR_STALE_CONTRACT_VERSION,
)
from test_helpers.assertions import (
    assert_cabinet_fields,
    assert_case_fields,
    assert_contract_fields,
    assert_module_fields,
    assert_page_meta,
    assert_version,
    ids_of,
)
from test_helpers.constants import (
    CABINET_IN_ASSEMBLY,
    CABINET_POPULATED,
    CASE_APPROVED,
    CASE_FULFILLED,
    CONTRACT_ACTIVE,
    CONTRACT_PENDING,
    CONTRACT_SUSPENDED,
    MODULE_CALIBRATED,
    MODULE_INSTALLED,
    MODULE_RETURNED,
    POSTURE_AT_RISK,
    WARRANTY_CASE_INSTANT,
)
from test_helpers.factories import (
    FP10_IN,
    FP16_STD,
    fulfil_payload,
    install_module_payload,
    remove_module_payload,
    spare_reservation_payload,
    spare_release_payload,
)

#: The FP16-STD family certifies 150.00 kg/sqm and fits two modules per cabinet, so
#: one cabinet offers exactly the two slots this file competes for.
FP16_REQUIRED_LOAD_KG_PER_SQM = 150.00
FP16_SLOTS = 2

#: A freshly planned cabinet, and a freshly sold contract, are both at version 1.
FIRST_VERSION = 1

#: A 4x4 FP10-IN wall is 16 one-module cabinets, so a SILVER holding of 200 basis
#: points of 16 modules obliges ceil(0.32) = 1 spare.
FOUR_BY_FOUR = {"cabinet_grid_cols": 4, "cabinet_grid_rows": 4}
SILVER_SPARE_PCT_BP = 200
SILVER_TERM_MONTHS = 60
SILVER_SPARE_REQUIRED_COUNT = 1

#: Two interchangeable A1 spares, so nothing but the version can decide the answer.
SPARE_NITS = 4850
SPARE_CHROMA = (0.3130, 0.3290)

#: A GOLD holding of 300 basis points over a two-module wall obliges one spare, so
#: consuming it on a swap empties the pool.
GOLD_SPARE_REQUIRED_COUNT = 1
SYMPTOM = "Quadrant one is dark"


def _two_free_modules_and_an_empty_cabinet(plant):
    """An approved FP16-STD wall with one planned cabinet and two calibrated modules."""
    scene = plant.approved_project_scene(
        model_base=FP16_STD,
        revision_overrides={"structural_load_kg_per_sqm": FP16_REQUIRED_LOAD_KG_PER_SQM},
    )
    scene.cabinet = plant.plan_cabinet(scene.project["id"])
    scene.first = plant.calibrated_module(scene.model["id"], serial_no="M-1")
    scene.second = plant.calibrated_module(scene.model["id"], serial_no="M-2")
    return scene


class TestCabinetVersionGuardsBothSlotWrites:
    """One read cannot authorise two slot writes on the same cabinet."""

    def test_the_second_install_from_one_read_is_refused_and_changes_nothing(self, plant):
        """If the supplied value does not equal the cabinet's current `version`, the
        request is rejected with `ERR_STALE_CABINET_VERSION` (HTTP 412) and nothing is
        persisted. Slot assignment is the reason this matters: a writer holding a
        stale view of `occupied_slot_indexes` would otherwise hand out a slot that has
        already been filled.

        Design: Corner/cross_cutting_complexity_layers/stale_cabinet_version_rejects_the_install_and_the_removal
        """
        scene = _two_free_modules_and_an_empty_cabinet(plant)
        stale_version = plant.cabinet(scene.cabinet["id"])["version"]
        assert stale_version == FIRST_VERSION

        first_install = validate_success(
            plant.api.install_module(
                scene.cabinet["id"],
                install_module_payload(scene.first["id"], 1, stale_version),
                plant.operator,
            ),
            201,
        )
        second_install = plant.api.install_module(
            scene.cabinet["id"],
            install_module_payload(scene.second["id"], 2, stale_version),
            plant.operator,
        )

        assert_module_fields(first_install, module_state=MODULE_INSTALLED, slot_index=1)
        validate_error(second_install, ERR_STALE_CABINET_VERSION, 412)

        cabinet = plant.cabinet(scene.cabinet["id"])
        assert_version(cabinet, stale_version + 1, "cabinet")
        assert_cabinet_fields(
            cabinet,
            cabinet_state=CABINET_IN_ASSEMBLY,
            installed_module_count=1,
            occupied_slot_indexes=[1],
        )
        assert_module_fields(
            plant.module(scene.second["id"]),
            module_state=MODULE_CALIBRATED,
            cabinet_id=None,
            slot_index=None,
        )
        assert_version(plant.module(scene.second["id"]), scene.second["version"], "module")

    def test_the_re_read_version_succeeds_and_the_removal_repeats_the_pattern(self, plant):
        """Three operations require `expected_cabinet_version` as a mandatory input
        field carrying the client's last observed `version` of the target cabinet:
        installing a module into a cabinet slot, removing an installed module from a
        cabinet, and fulfilling an approved warranty case by swapping a module.

        Design: Corner/cross_cutting_complexity_layers/stale_cabinet_version_rejects_the_install_and_the_removal
        """
        scene = _two_free_modules_and_an_empty_cabinet(plant)
        stale_version = plant.cabinet(scene.cabinet["id"])["version"]
        plant.api.install_module(
            scene.cabinet["id"],
            install_module_payload(scene.first["id"], 1, stale_version),
            plant.operator,
        )
        after_first = plant.cabinet(scene.cabinet["id"])["version"]

        validate_success(
            plant.api.install_module(
                scene.cabinet["id"],
                install_module_payload(scene.second["id"], 2, after_first),
                plant.operator,
            ),
            201,
        )
        populated = plant.cabinet(scene.cabinet["id"])
        assert_version(populated, after_first + 1, "cabinet")
        assert_cabinet_fields(
            populated,
            cabinet_state=CABINET_POPULATED,
            installed_module_count=FP16_SLOTS,
            occupied_slot_indexes=[1, 2],
        )

        stale_removal = plant.api.remove_module(
            scene.cabinet["id"],
            remove_module_payload(scene.second["id"], after_first),
            plant.operator,
        )
        validate_error(stale_removal, ERR_STALE_CABINET_VERSION, 412)
        assert_version(plant.cabinet(scene.cabinet["id"]), after_first + 1, "cabinet")
        assert_module_fields(
            plant.module(scene.second["id"]), module_state=MODULE_INSTALLED, slot_index=2
        )

        removed = validate_success(
            plant.api.remove_module(
                scene.cabinet["id"],
                remove_module_payload(scene.second["id"], after_first + 1),
                plant.operator,
            ),
            201,
        )
        assert_module_fields(
            removed, module_state=MODULE_CALIBRATED, cabinet_id=None, slot_index=None
        )
        emptied = plant.cabinet(scene.cabinet["id"])
        assert_version(emptied, after_first + 2, "cabinet")
        assert_cabinet_fields(emptied, installed_module_count=1, occupied_slot_indexes=[1])
        assert_version(
            plant.module(scene.first["id"]), scene.first["version"] + 1, "installed module"
        )
        assert_version(
            plant.module(scene.second["id"]), scene.second["version"] + 2, "cycled module"
        )


def _a_pending_contract_and_two_interchangeable_spares(plant):
    """A SILVER contract over a 4x4 wall, with two A1 spares waiting in stock."""
    model = plant.register_model(FP10_IN)
    project = plant.create_project(model["id"], **FOUR_BY_FOUR)
    contract = plant.sell_contract(
        project["id"],
        tier="SILVER",
        spare_pct_bp=SILVER_SPARE_PCT_BP,
        term_months=SILVER_TERM_MONTHS,
    )
    first = plant.calibrated_module(
        model["id"],
        serial_no="S-1",
        measured_brightness_nits=SPARE_NITS,
        measured_color_x=SPARE_CHROMA[0],
        measured_color_y=SPARE_CHROMA[1],
    )
    second = plant.calibrated_module(
        model["id"],
        serial_no="S-2",
        measured_brightness_nits=SPARE_NITS,
        measured_color_x=SPARE_CHROMA[0],
        measured_color_y=SPARE_CHROMA[1],
    )
    return {"contract": contract, "first": first, "second": second}


class TestContractVersionGuardsTheSparePool:
    """The counter, not a slot map, is what a stale reservation would overwrite."""

    def test_the_second_reservation_from_one_read_carries_the_contracts_own_code(self, plant):
        """A mismatch with the contract's current `version` is rejected with
        `ERR_STALE_CONTRACT_VERSION` (HTTP 412). A reservation legitimately supersedes
        the prior composition of the spare pool, so a writer acting on a stale
        `spare_reserved_count` would over-reserve or under-reserve against the
        contracted `spare_required_count`.

        Design: Corner/cross_cutting_complexity_layers/stale_contract_version_rejects_the_second_reservation
        """
        stock = _a_pending_contract_and_two_interchangeable_spares(plant)
        contract = stock["contract"]
        stale_version = contract["version"]
        assert stale_version == FIRST_VERSION

        held = validate_success(
            plant.api.reserve_spare(
                contract["id"],
                spare_reservation_payload(stale_version, stock["first"]["id"]),
                plant.service,
            ),
            201,
        )
        refused = plant.api.reserve_spare(
            contract["id"],
            spare_reservation_payload(stale_version, stock["second"]["id"]),
            plant.service,
        )

        assert held["id"] == stock["first"]["id"]
        assert_module_fields(held, reserved_service_contract_id=contract["id"])
        validate_error(refused, ERR_STALE_CONTRACT_VERSION, 412)

        after = plant.contract(contract["id"])
        assert_version(after, stale_version + 1, "contract")
        assert_contract_fields(
            after,
            contract_state=CONTRACT_PENDING,
            spare_reserved_count=1,
            spare_required_count=SILVER_SPARE_REQUIRED_COUNT,
        )
        assert_module_fields(
            plant.module(stock["second"]["id"]), reserved_service_contract_id=None
        )

    def test_the_release_shares_the_field_and_the_retry_lands(self, plant):
        """Two operations require `expected_service_contract_version` as a mandatory
        input field carrying the client's last observed `version` of the target
        contract: reserving a spare module against the contract, and releasing a
        reserved spare back to free stock.

        Design: Corner/cross_cutting_complexity_layers/stale_contract_version_rejects_the_second_reservation
        """
        stock = _a_pending_contract_and_two_interchangeable_spares(plant)
        contract = stock["contract"]
        stale_version = contract["version"]
        plant.api.reserve_spare(
            contract["id"],
            spare_reservation_payload(stale_version, stock["first"]["id"]),
            plant.service,
        )
        current_version = plant.contract(contract["id"])["version"]

        stale_release = plant.api.release_spare(
            contract["id"],
            spare_release_payload(stock["first"]["id"], stale_version),
            plant.service,
        )

        validate_error(stale_release, ERR_STALE_CONTRACT_VERSION, 412)
        assert_module_fields(
            plant.module(stock["first"]["id"]),
            module_state=MODULE_CALIBRATED,
            reserved_service_contract_id=contract["id"],
        )
        assert_version(plant.contract(contract["id"]), current_version, "contract")

        validate_success(
            plant.api.reserve_spare(
                contract["id"],
                spare_reservation_payload(current_version, stock["second"]["id"]),
                plant.service,
            ),
            201,
        )
        refilled = plant.contract(contract["id"])
        assert_contract_fields(refilled, spare_reserved_count=2)
        assert_version(refilled, current_version + 1, "contract")

        reserved, meta = validate_paginated(
            plant.api.list_modules(
                plant.service, {"reserved_service_contract_id": contract["id"]}
            )
        )
        assert ids_of(reserved) == [stock["first"]["id"], stock["second"]["id"]]
        assert_page_meta(meta, total_count=2, has_more=False)


def _an_approved_fault_claim_on_a_commissioned_wall(plant):
    """A live FP16-STD wall with a reserved spare and an APPROVED module-fault claim.

    The claim names the module in slot 1, and the wall's cabinet has since absorbed
    two installs, a soak, a QA signature and a mounting, so its version has moved a
    long way from the value a client read while the cabinet was still empty.
    """
    scene = plant.reserved_spare_scene(
        model_base=FP16_STD,
        revision_overrides={"structural_load_kg_per_sqm": FP16_REQUIRED_LOAD_KG_PER_SQM},
        spare_brightness=SPARE_NITS,
        spare_chroma=SPARE_CHROMA,
    )
    plant.set_clock(WARRANTY_CASE_INSTANT)
    case = plant.open_module_fault_case(
        scene.contract["id"],
        scene.cabinet["id"],
        faulty_module_id=scene.modules[0]["id"],
        symptom=SYMPTOM,
    )
    plant.respond(case["id"])
    scene.case = plant.assess(case["id"], decision="APPROVE")
    return scene


class TestCabinetVersionGuardsAWarrantyFulfilment:
    """The guarded parent is the cabinet, whose id the request never mentions."""

    def test_a_version_cached_before_assembly_is_refused_and_the_claim_survives(self, plant):
        """The swap itself takes `expected_cabinet_version` and, optionally, the
        `replacement_module_id` to install. The case must be `APPROVED`
        (`ERR_INVALID_CASE_STATE`), the contract `ACTIVE`, and the cabinet version
        current (`ERR_STALE_CABINET_VERSION`).

        Design: Corner/cross_cutting_complexity_layers/stale_cabinet_version_rejects_a_warranty_fulfilment
        """
        scene = _an_approved_fault_claim_on_a_commissioned_wall(plant)
        faulty = scene.modules[0]
        current_version = plant.cabinet(scene.cabinet["id"])["version"]
        assert current_version > FIRST_VERSION

        refused = plant.api.fulfil_case(
            scene.case["id"],
            fulfil_payload(FIRST_VERSION, scene.spare["id"]),
            plant.service,
        )

        validate_error(refused, ERR_STALE_CABINET_VERSION, 412)
        assert_case_fields(
            plant.case(scene.case["id"]),
            case_state=CASE_APPROVED,
            replacement_module_id=None,
            resolved_faulty_module_id=faulty["id"],
        )
        assert_module_fields(
            plant.module(scene.spare["id"]),
            module_state=MODULE_CALIBRATED,
            reserved_service_contract_id=scene.contract["id"],
        )
        assert_module_fields(
            plant.module(faulty["id"]), module_state=MODULE_INSTALLED, slot_index=1
        )
        assert_version(plant.cabinet(scene.cabinet["id"]), current_version, "cabinet")
        assert_contract_fields(
            plant.contract(scene.contract["id"]),
            contract_state=CONTRACT_ACTIVE,
            spare_reserved_count=1,
            spare_required_count=GOLD_SPARE_REQUIRED_COUNT,
        )

    def test_the_retry_swaps_the_module_and_a_third_attempt_meets_the_case_gate(self, plant):
        """The case's `case_state` permits the operation: `OPEN` for response,
        `RESPONDED` for assessment, `APPROVED` for fulfilment — otherwise
        `ERR_INVALID_CASE_STATE`.

        Design: Corner/cross_cutting_complexity_layers/stale_cabinet_version_rejects_a_warranty_fulfilment
        """
        scene = _an_approved_fault_claim_on_a_commissioned_wall(plant)
        faulty = scene.modules[0]
        plant.api.fulfil_case(
            scene.case["id"],
            fulfil_payload(FIRST_VERSION, scene.spare["id"]),
            plant.service,
        )
        current_version = plant.cabinet(scene.cabinet["id"])["version"]

        fulfilled = validate_success(
            plant.api.fulfil_case(
                scene.case["id"],
                fulfil_payload(current_version, scene.spare["id"]),
                plant.service,
            ),
            200,
        )

        assert_case_fields(
            fulfilled,
            case_state=CASE_FULFILLED,
            replacement_module_id=scene.spare["id"],
            resolved_faulty_module_id=faulty["id"],
        )
        assert_module_fields(
            plant.module(faulty["id"]),
            module_state=MODULE_RETURNED,
            slot_index=None,
            cabinet_id=scene.cabinet["id"],
        )
        assert_module_fields(
            plant.module(scene.spare["id"]),
            module_state=MODULE_INSTALLED,
            slot_index=1,
            replaces_module_id=faulty["id"],
            reserved_service_contract_id=None,
        )
        after_swap = plant.cabinet(scene.cabinet["id"])["version"]
        assert after_swap == current_version + 1

        third_attempt = plant.api.fulfil_case(
            scene.case["id"],
            fulfil_payload(after_swap, scene.spare["id"]),
            plant.service,
        )
        validate_error(third_attempt, ERR_INVALID_CASE_STATE, 409)

        drained = plant.contract(scene.contract["id"])
        assert_contract_fields(
            drained,
            contract_state=CONTRACT_SUSPENDED,
            spare_reserved_count=0,
            spare_required_count=GOLD_SPARE_REQUIRED_COUNT,
        )
        assert plant.project(scene.project["id"])["service_posture"] == POSTURE_AT_RISK
