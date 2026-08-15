"""Segregation of duties: the six second-pair-of-eyes checks (PRD §2.10)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    close_settlement,
    create_draft_agreement,
    create_draft_contract,
    create_odor_event,
    create_plant,
    create_supplier,
    create_walkin_batch,
    get_settlement,
    make_headers,
    setup_plant_with_agreement,
    setup_completed_cook_run,
    validate_error,
    validate_success,
)

PM2 = TEST_USERS["plant_manager_2_headers"]
ANY = TEST_USERS["any_headers"]


class TestAgreementApprovalSoD:
    def test_sod_agreement_creator_cannot_approve(self, api):
        """PRD §2.10: "A supplier agreement may only be approved by someone other than its
        `created_by` drafter."
        PRD §2.10: "Each violation is rejected with `ERR_SOD_VIOLATION` (HTTP 403)."

        Design: Corner/rbac/sod_agreement_creator_cannot_approve
        """
        plant = create_plant()
        supplier = create_supplier(plant["id"])
        # created_by = pm-1 (the ProcurementManager caller).
        agreement = create_draft_agreement(plant["id"], supplier["id"])
        assert agreement["created_by"] == "pm-1"
        validate_success(
            api.submit_agreement(agreement["id"], make_headers("pm-1", "ProcurementManager")),
            200,
        )

        # The creator cannot approve, even holding the correct PlantManager role.
        res = api.approve_agreement(
            agreement["id"], make_headers("pm-1", "PlantManager")
        )
        validate_error(res, ApiErrorId.ERR_SOD_VIOLATION, expected_status=403)
        mid = validate_success(api.get_supplier_agreement(agreement["id"], ANY), 200)
        assert mid["status"] == "SUBMITTED"

        # A different PlantManager approves.
        approved = validate_success(
            api.approve_agreement(agreement["id"], make_headers("pmgr-9", "PlantManager")),
            200,
        )
        assert approved["status"] == "ACTIVE"


class TestContractApprovalSoD:
    def test_sod_contract_creator_cannot_approve(self, api):
        """PRD §2.10: "A customer contract may only be approved by someone other than its
        `created_by` drafter."
        PRD §2.10: "Each violation is rejected with `ERR_SOD_VIOLATION` (HTTP 403)."

        Design: Corner/rbac/sod_contract_creator_cannot_approve
        """
        plant = create_plant()
        contract = create_draft_contract(plant["id"])  # created_by = sm-1
        assert contract["created_by"] == "sm-1"
        validate_success(
            api.submit_contract(contract["id"], make_headers("sm-1", "SalesManager")), 200
        )

        res = api.approve_contract(
            contract["id"], make_headers("sm-1", "PlantManager")
        )
        validate_error(res, ApiErrorId.ERR_SOD_VIOLATION, expected_status=403)

        approved = validate_success(
            api.approve_contract(contract["id"], make_headers("pmgr-1", "PlantManager")),
            200,
        )
        assert approved["status"] == "ACTIVE"


class TestOdorResolutionSoD:
    def test_sod_odor_reporter_cannot_confirm(self, api):
        """PRD §2.10: "An odor event may only be confirmed or dismissed by someone other
        than its `reported_by` logger."
        PRD §2.10: "Each violation is rejected with `ERR_SOD_VIOLATION` (HTTP 403)."
        PRD §3.2: "On confirmation the server records `confirmed_by`, links `permit_id` to
        the plant's `ACTIVE` permit when one exists, and applies the severity penalty to the
        plant's `odor_score`: 50 points for `LOW`, 100 for `MEDIUM`, 150 for `HIGH`, never
        driving the score below 0."

        Design: Corner/rbac/sod_odor_reporter_cannot_confirm
        """
        plant = create_plant()
        event = create_odor_event(plant["id"], severity="LOW")  # reported_by = co-1
        assert event["reported_by"] == "co-1"

        res = api.confirm_odor_event(event["id"], make_headers("co-1", "ComplianceOfficer"))
        validate_error(res, ApiErrorId.ERR_SOD_VIOLATION, expected_status=403)
        mid = validate_success(api.get_odor_event(event["id"], ANY), 200)
        assert mid["status"] == "REPORTED"
        plant_mid = validate_success(api.get_plant(plant["id"], ANY), 200)
        assert plant_mid["odor_score"] == 1000

        confirmed = validate_success(
            api.confirm_odor_event(event["id"], make_headers("co-2", "ComplianceOfficer")),
            200,
        )
        assert confirmed["status"] == "CONFIRMED"
        plant_after = validate_success(api.get_plant(plant["id"], ANY), 200)
        assert plant_after["odor_score"] == 950


class TestBatchAdjudicationSoD:
    def test_sod_batch_screener_cannot_adjudicate(self, api):
        """PRD §2.10: "A quarantined batch may only be adjudicated by someone other than the
        `screened_by` screener, when a screener is recorded."
        PRD §2.10: "Each violation is rejected with `ERR_SOD_VIOLATION` (HTTP 403)."

        Design: Corner/rbac/sod_batch_screener_cannot_adjudicate
        """
        plant, supplier, agreement = setup_plant_with_agreement()
        batch = create_walkin_batch(plant["id"], supplier["id"], agreement["id"],
                                    temperature_f=104.0)
        screened = validate_success(
            api.screen_batch(
                batch["id"], {"screening_result": "FAIL_TEMPERATURE"},
                make_headers("sh-1", "ScalehouseOperator"),
            ),
            200,
        )
        assert screened["status"] == "QUARANTINED"
        assert screened["screened_by"] == "sh-1"

        # sh-1 holds the ComplianceOfficer role here, yet still matches screened_by.
        res = api.adjudicate_batch(
            batch["id"], {"decision": "ACCEPT"},
            make_headers("sh-1", "ComplianceOfficer"),
        )
        validate_error(res, ApiErrorId.ERR_SOD_VIOLATION, expected_status=403)

        adjudicated = validate_success(
            api.adjudicate_batch(
                batch["id"], {"decision": "ACCEPT"},
                make_headers("co-1", "ComplianceOfficer"),
            ),
            200,
        )
        assert adjudicated["status"] == "ACCEPTED"


class TestLotReleaseSoD:
    def test_sod_lot_grader_cannot_release(self, api):
        """PRD §2.10: "A product lot may only be released by someone other than the
        `graded_by` lab technician."
        PRD §3.7: "A `GRADED` lot is released for sale by a `ProductionSupervisor` — never
        by the technician who graded it (`ERR_SOD_VIOLATION`); the lot must be `GRADED` and
        its grade must not be `OFF_SPEC` (both violations surface as
        `ERR_LOT_INVALID_STATE`)."

        Design: Corner/rbac/sod_lot_grader_cannot_release
        """
        from test_helpers import get_lot_for_run, grade_lot

        ctx = setup_completed_cook_run()
        lot = get_lot_for_run(ctx["run"]["id"], "TALLOW")
        graded = grade_lot(lot["id"], 0.2, 1.5, 0)  # graded_by = ql-1
        assert graded["grade"] == "PREMIUM"
        assert graded["graded_by"] == "ql-1"

        # The grading technician cannot release, even holding ProductionSupervisor.
        res = api.release_lot(lot["id"], make_headers("ql-1", "ProductionSupervisor"))
        validate_error(res, ApiErrorId.ERR_SOD_VIOLATION, expected_status=403)

        released = validate_success(
            api.release_lot(lot["id"], make_headers("ps-1", "ProductionSupervisor")), 200
        )
        assert released["status"] == "RELEASED"


class TestSettlementFinalizeSoD:
    def test_sod_settlement_closer_cannot_finalize(self, api):
        """PRD §2.10: "A period settlement may only be finalized by someone other than its
        `closed_by` closer."
        PRD §3.9: "Finalization is the terminal act: a `PlantManager` finalizes a `CLOSED`
        settlement, and the finalizer must differ from the recorded `closed_by`
        (`ERR_SOD_VIOLATION`). `FINALIZED` is terminal."

        Design: Corner/rbac/sod_settlement_closer_cannot_finalize
        """
        plant = create_plant()
        settlement = get_settlement(plant["id"], period_index=1)
        closed = close_settlement(plant["id"], period_index=1)  # closed_by = fa-1
        assert closed["closed_by"] == "fa-1"

        # fa-1 swapping to the PlantManager role still matches closed_by.
        res = api.finalize_settlement(
            settlement["id"], make_headers("fa-1", "PlantManager")
        )
        validate_error(res, ApiErrorId.ERR_SOD_VIOLATION, expected_status=403)

        finalized = validate_success(
            api.finalize_settlement(settlement["id"], make_headers("pmgr-1", "PlantManager")),
            200,
        )
        assert finalized["status"] == "FINALIZED"
