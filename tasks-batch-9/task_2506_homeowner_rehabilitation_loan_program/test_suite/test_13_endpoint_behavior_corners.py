"""Endpoint corners: corrections, standing changes, determinations and reads."""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    assert_applicant,
    assert_contractor,
    assert_rehab_application,
    assert_unset,
    assert_work_write_up,
    create_complaint_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    INTAKE,
    PROGRAM_MANAGER,
    REHAB,
    add_work_item,
    build_applicant,
    build_application,
    build_contractor,
    build_verified_applicant,
    build_write_up,
    refresh_applicant,
    refresh_application,
    refresh_contractor,
    set_contractor_status,
)

GENERAL_LINE = {
    "description": "Interior repaint",
    "category": "ACCESSIBILITY",
    "priority_class": "GENERAL_PROPERTY_IMPROVEMENT",
    "estimated_cost_cents": 500_000,
}


class TestHouseholdCorrections:
    """Declarations may be corrected right up to certification, and not after it."""

    def test_a_partial_correction_moves_only_the_supplied_declarations(
        self, program_year
    ):
        """Three corrected figures move; the rest of the record holds where it was.

        PRD: "Correction accepts `income_calc_method`, `wage_income_cents`,
        `benefit_income_cents`, `actual_asset_income_cents`,
        `household_assets_cents`, `household_size`, `dependents_count` and
        `elderly_household`, each optional, and advances the household's `version`
        by one."

        Design: Corner/endpoints/patching_an_unverified_applicant_updates_inputs_and_defers_recertification
        """
        household = build_applicant(
            program_year["id"],
            wage_income_cents=4_500_000,
            household_assets_cents=0,
            dependents_count=0,
        )
        assert household["version"] == 1

        corrected = validate_success(
            api_client.update_applicant(
                household["id"],
                {
                    "wage_income_cents": 7_000_000,
                    "household_assets_cents": 5_000_000,
                    "dependents_count": 2,
                },
                INTAKE,
            ),
            200,
        )

        assert_applicant(corrected)
        assert corrected["wage_income_cents"] == 7_000_000
        assert corrected["household_assets_cents"] == 5_000_000
        assert corrected["dependents_count"] == 2
        assert corrected["household_size"] == 4, (
            "An omitted field is left alone rather than reset"
        )
        assert corrected["income_calc_method"] == "PART_5_ANNUAL"
        assert corrected["full_name"] == "Odell Marsh"
        assert corrected["version"] == 2
        assert corrected["eligibility_status"] == "APPLIED", (
            "Correcting declarations does not certify the household"
        )
        assert_unset(corrected, "annual_income_cents")
        assert_unset(corrected, "ami_percent")

        certified = validate_success(
            api_client.verify_income(household["id"], INTAKE), 200
        )

        assert certified["annual_income_cents"] == 7_020_000, (
            "Certification reads the corrected declarations, got "
            f"{certified['annual_income_cents']}"
        )
        assert certified["ami_percent"] == pytest.approx(78.0, abs=0.01)
        assert certified["income_category"] == "LOW"
        assert certified["eligibility_status"] == "INCOME_VERIFIED"

    def test_a_correction_after_certification_is_refused_and_changes_nothing(
        self, program_year
    ):
        """Once the figures are certified the household record is frozen.

        PRD: "Once income has been certified, the household record is frozen and a
        correction attempt is refused with `ERR_INVALID_STATE`."

        Design: Corner/endpoints/patching_an_unverified_applicant_updates_inputs_and_defers_recertification
        """
        household = build_verified_applicant(program_year["id"])
        certified_version = household["version"]

        response = api_client.update_applicant(
            household["id"], {"wage_income_cents": 1_000_000}, INTAKE
        )

        validate_error(response, "ERR_INVALID_STATE", 409)
        unchanged = refresh_applicant(household["id"])
        assert unchanged["wage_income_cents"] == 7_000_000, (
            "The refused correction writes nothing, got "
            f"{unchanged['wage_income_cents']}"
        )
        assert unchanged["annual_income_cents"] == 7_020_000
        assert unchanged["version"] == certified_version


class TestApprovedListStandingEndpoint:
    """The standing action is the only way a firm walks back onto the list."""

    def test_the_standing_action_drives_every_manual_leg_of_the_list(self):
        """Probation, reinstatement, suspension and removal all run off one action.

        PRD: "The transitions available are `APPROVED → PROBATION`, `PROBATION →
        APPROVED` (which requires a `performance_score` of at least 50), `APPROVED
        → SUSPENDED`, `PROBATION → SUSPENDED`, `SUSPENDED → APPROVED` and
        `SUSPENDED → REMOVED`."

        Design: Corner/endpoints/contractor_status_endpoint_is_the_only_road_back_to_the_approved_list
        """
        firm = build_contractor(legal_name="Borough Builders Inc")
        assert firm["approved_list_status"] == "APPROVED"
        assert firm["version"] == 1

        demoted = set_contractor_status(
            firm["id"], "PROBATION", "Late close-out paperwork"
        )
        restored = set_contractor_status(firm["id"], "APPROVED", "Paperwork cured")
        suspended = set_contractor_status(firm["id"], "SUSPENDED", "Insurance lapse")
        removed = set_contractor_status(firm["id"], "REMOVED", "Debarment")

        assert_contractor(removed)
        assert demoted["approved_list_status"] == "PROBATION"
        assert restored["approved_list_status"] == "APPROVED", (
            "Reinstatement from probation is available to the program manager"
        )
        assert suspended["approved_list_status"] == "SUSPENDED"
        assert removed["approved_list_status"] == "REMOVED"
        assert [row["version"] for row in (demoted, restored, suspended, removed)] == [
            2,
            3,
            4,
            5,
        ], "Each accepted standing change advances the firm's version by one"
        assert removed["performance_score"] == 100, (
            "No complaint or sanction was involved, so the score is untouched"
        )
        assert removed["sanction_count"] == 0
        assert removed["open_complaint_count"] == 0

    def test_removal_is_terminal_and_a_non_member_standing_is_refused(self):
        """A removed firm cannot be revived, and only the four standings are accepted.

        PRD: "`REMOVED` is terminal."

        Design: Corner/endpoints/contractor_status_endpoint_is_the_only_road_back_to_the_approved_list
        """
        firm = build_contractor(legal_name="Borough Builders Inc")

        validate_error(
            api_client.set_contractor_status(
                firm["id"],
                {"approved_list_status": "DEBARRED", "reason": "Not an enum member"},
                PROGRAM_MANAGER,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )
        assert refresh_contractor(firm["id"])["approved_list_status"] == "APPROVED"

        set_contractor_status(firm["id"], "SUSPENDED", "Insurance lapse")
        set_contractor_status(firm["id"], "REMOVED", "Debarment")

        response = api_client.set_contractor_status(
            firm["id"],
            {"approved_list_status": "APPROVED", "reason": "Appeal granted"},
            PROGRAM_MANAGER,
        )

        validate_error(response, "ERR_INVALID_STATE", 409)
        assert refresh_contractor(firm["id"])["approved_list_status"] == "REMOVED"


class TestHistoricDeterminationBranches:
    """One determination endpoint, three different destinations for the posture."""

    @pytest.fixture
    def historic_only_case(self, program_year):
        """A 1995 dwelling inside a historic district, so only the historic axis holds."""
        household = build_verified_applicant(program_year["id"])
        application = build_application(
            household["id"],
            address_line1="7 Chapel Green",
            year_built=1995,
            assessed_value_cents=16_000_000,
            senior_lien_balance_cents=10_000_000,
            historic_district=True,
        )
        assert application["compliance_posture"] == "HISTORIC_HOLD"
        assert application["historic_review_required"] is True
        assert application["lead_review_required"] is False
        return application

    def test_an_adverse_determination_parks_the_case_in_a_terminal_posture(
        self, historic_only_case
    ):
        """An adverse effect is stored and no further determination is accepted.

        PRD: "A determination of `ADVERSE_EFFECT` is fatal to the case's
        financing. From either `HISTORIC_HOLD` or `DUAL_HOLD`, that outcome is
        stored and the posture moves to `ADVERSE_EFFECT_BLOCKED`, which is
        terminal on the compliance axis: lien recording can never proceed from
        there, no matter what else happens to the case."

        Design: Corner/endpoints/an_adverse_shpo_outcome_blocks_the_application_conditionally
        """
        application_id = historic_only_case["id"]

        blocked = validate_success(
            api_client.record_historic_clearance(
                application_id, {"shpo_review_outcome": "ADVERSE_EFFECT"}, PROGRAM_MANAGER
            ),
            200,
        )

        assert_rehab_application(blocked)
        assert blocked["compliance_posture"] == "ADVERSE_EFFECT_BLOCKED", (
            f"An adverse effect blocks the case, got {blocked['compliance_posture']}"
        )
        assert blocked["shpo_review_outcome"] == "ADVERSE_EFFECT"

        response = api_client.record_historic_clearance(
            application_id, {"shpo_review_outcome": "NO_ADVERSE_EFFECT"}, PROGRAM_MANAGER
        )

        validate_error(response, "ERR_INVALID_STATE", 409)
        assert (
            refresh_application(application_id)["compliance_posture"]
            == "ADVERSE_EFFECT_BLOCKED"
        ), "The blocked posture cannot be walked back"

    def test_a_clean_determination_clears_the_only_outstanding_axis(
        self, historic_only_case
    ):
        """With no lead protocol on the property, clearing historic review clears the case.

        PRD: "From `HISTORIC_HOLD` on a case whose `lead_review_required` is
        false, the posture moves `HISTORIC_HOLD → CLEAR`."

        Design: Corner/endpoints/an_adverse_shpo_outcome_blocks_the_application_conditionally
        """
        application_id = historic_only_case["id"]
        before_version = historic_only_case["version"]

        cleared = validate_success(
            api_client.record_historic_clearance(
                application_id,
                {"shpo_review_outcome": "NO_ADVERSE_EFFECT"},
                PROGRAM_MANAGER,
            ),
            200,
        )

        assert cleared["compliance_posture"] == "CLEAR", (
            "The historic axis was the only one outstanding, got "
            f"{cleared['compliance_posture']}"
        )
        assert cleared["shpo_review_outcome"] == "NO_ADVERSE_EFFECT"
        assert cleared["version"] == before_version + 1
        assert cleared["workflow_state"] == "INTAKE", (
            "A determination moves the compliance axis only"
        )


class TestWriteUpReadPaths:
    """The stored estimate reads back the same through both read paths."""

    def test_the_single_read_and_the_filtered_list_agree_on_the_estimate(
        self, inspected_case
    ):
        """Two readers of one scope see one set of derived figures.

        PRD: "`base_estimate_cents` is then the sum of the already-rounded
        `line_total_cents` of every line on the write-up."

        Design: Corner/endpoints/write_up_totals_read_back_identically_from_the_single_get_and_the_filtered_list
        """
        application_id = inspected_case["application"]["id"]
        write_up = build_write_up(application_id)
        add_work_item(write_up["id"])
        add_work_item(write_up["id"], **GENERAL_LINE)

        fetched = validate_success(api_client.get_write_up(write_up["id"], REHAB), 200)
        rows, meta = validate_paginated(
            api_client.list_write_ups(
                REHAB,
                {
                    "application_id": application_id,
                    "state": "DRAFT",
                    "limit": 10,
                    "offset": 0,
                },
            )
        )

        assert_work_write_up(fetched)
        assert fetched["work_item_count"] == 2
        assert fetched["base_estimate_cents"] == 2_500_000, (
            "2,000,000 plus 500,000 is the base estimate, got "
            f"{fetched['base_estimate_cents']}"
        )
        assert fetched["contingency_cents"] == 250_000
        assert fetched["total_estimate_cents"] == 2_750_000
        assert fetched["priority_repair_total_cents"] == 2_000_000
        assert len(rows) == 1
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        listed = rows[0]
        for field in (
            "work_item_count",
            "base_estimate_cents",
            "contingency_cents",
            "total_estimate_cents",
            "priority_repair_total_cents",
            "version",
        ):
            assert listed[field] == fetched[field], (
                f"{field} disagrees between the two read paths: "
                f"{listed[field]} against {fetched[field]}"
            )
        _, approved_meta = validate_paginated(
            api_client.list_write_ups(
                REHAB, {"application_id": application_id, "state": "APPROVED"}
            )
        )
        assert approved_meta["total_count"] == 0, (
            "The draft scope is not reported as approved"
        )


class TestComplaintReferences:
    """A complaint links two aggregates, and both are resolved before any rule runs."""

    def test_a_complaint_naming_an_unknown_firm_is_not_found(self, application):
        """The unresolved firm answers before the case's missing warranty does.

        PRD: "Foreign keys supplied in a request body are resolved after path
        identifiers, in the order the keys appear in the endpoint's input list,
        and yield the same 404 identifiers."

        Design: Corner/endpoints/filing_a_complaint_against_an_unknown_contractor_returns_not_found
        """
        application_id = application["id"]

        response = api_client.create_complaint(
            create_complaint_payload(
                NON_EXISTENT_UUID,
                application_id,
                description="Roof flashing leaks at the valley",
            ),
            REHAB,
        )

        validate_error(response, "ERR_CONTRACTOR_NOT_FOUND", 404)
        _, meta = validate_paginated(
            api_client.list_complaints(REHAB, {"application_id": application_id})
        )
        assert meta["total_count"] == 0, (
            f"The refusal files nothing, got {meta['total_count']} complaints"
        )

        mirrored = api_client.create_complaint(
            create_complaint_payload(
                build_contractor(legal_name="Borough Builders Inc")["id"],
                NON_EXISTENT_UUID,
                description="Roof flashing leaks at the valley",
            ),
            REHAB,
        )

        validate_error(mirrored, "ERR_APPLICATION_NOT_FOUND", 404)
