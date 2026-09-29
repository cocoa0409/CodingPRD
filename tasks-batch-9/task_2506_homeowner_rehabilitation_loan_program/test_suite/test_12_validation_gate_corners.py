"""Gate corners: the intake and ownership preconditions, submission gates and ceilings."""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    assert_change_order,
    assert_rehab_application,
    assert_unset,
    create_application_payload,
    create_change_order_payload,
    create_inspection_payload,
    create_write_up_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    INSPECTOR,
    INTAKE,
    PROGRAM_MANAGER,
    REHAB,
    add_work_item,
    build_applicant,
    build_verified_applicant,
    build_write_up,
    refresh_applicant,
    refresh_application,
    refresh_loan,
    refresh_program_year,
    refresh_write_up,
    setup_case,
    verify_application_ownership,
)

REVERSED_WINDOW = {
    "scheduled_start_at": "2026-08-03T15:00:00Z",
    "scheduled_end_at": "2026-08-03T13:00:00Z",
}
GENERAL_LINE = {
    "description": "Kitchen cabinet upgrade",
    "category": "ACCESSIBILITY",
    "priority_class": "GENERAL_PROPERTY_IMPROVEMENT",
    "estimated_cost_cents": 800_000,
}
CODE_LINE = {
    "description": "Service panel grounding",
    "category": "ELECTRICAL",
    "priority_class": "CODE",
    "estimated_cost_cents": 300_000,
}


def _submit_change_order(loan_id, amount_delta_cents, justification):
    """Submit one change order against the loan's current version."""
    loan = refresh_loan(loan_id)
    return validate_success(
        api_client.create_change_order(
            create_change_order_payload(
                loan_id,
                loan["version"],
                amount_delta_cents=amount_delta_cents,
                justification=justification,
            ),
            REHAB,
        ),
        201,
    )


class TestIncomeCertificationGateOnIntake:
    """Intake is gated on the certification having run, and then on its verdict."""

    def test_intaking_a_case_for_an_uncertified_household_is_refused(
        self, program_year
    ):
        """A household still in `APPLIED` cannot have a property intaken at all.

        PRD: "The referenced applicant has `eligibility_status` equal to
        `INCOME_VERIFIED` — otherwise `ERR_INCOME_NOT_VERIFIED` (409). Applies to
        intaking a rehabilitation application."

        Design: Corner/validations/intake_before_income_verification_is_rejected
        """
        household = build_applicant(program_year["id"], full_name="Odell Marsh")
        assert household["eligibility_status"] == "APPLIED"

        response = api_client.create_application(
            create_application_payload(household["id"]), INTAKE
        )

        validate_error(response, "ERR_INCOME_NOT_VERIFIED", 409)
        assert refresh_applicant(household["id"])["eligibility_status"] == "APPLIED", (
            "The refused intake does not certify the household as a side effect"
        )
        rows, meta = validate_paginated(
            api_client.list_applications(INTAKE, {"applicant_id": household["id"]})
        )
        assert rows == []
        assert meta["total_count"] == 0, (
            f"No case is opened for the household, got {meta['total_count']}"
        )

    def test_the_same_payload_is_accepted_once_the_certification_has_run(
        self, program_year
    ):
        """With the certification recorded, the case opens and derives both reviews.

        PRD: "A pre-1978 dwelling inside a designated historic district opens at
        `DUAL_HOLD`."

        Design: Corner/validations/intake_immediately_after_verification_succeeds
        """
        household = build_verified_applicant(program_year["id"])
        assert household["eligibility_status"] == "INCOME_VERIFIED"
        assert household["income_category"] == "LOW"

        created = validate_success(
            api_client.create_application(
                create_application_payload(
                    household["id"],
                    address_line1="9 Canal Row",
                    year_built=1962,
                    assessed_value_cents=14_000_000,
                    senior_lien_balance_cents=9_000_000,
                    historic_district=True,
                ),
                INTAKE,
            ),
            201,
        )

        assert_rehab_application(created)
        assert created["workflow_state"] == "INTAKE"
        assert created["ownership_verification_status"] == "PENDING"
        assert created["lead_review_required"] is True, (
            "A 1962 dwelling is pre-1978 target housing"
        )
        assert created["historic_review_required"] is True
        assert created["compliance_posture"] == "DUAL_HOLD", (
            "Both triggers fire on the same property, got "
            f"{created['compliance_posture']}"
        )
        assert_unset(created, "awarded_contractor_id")
        assert_unset(created, "warranty_expires_at")


class TestOwnershipGateBeforeFieldWork:
    """No site visit and no scope until the deed and the title report are in."""

    def test_reserving_a_window_before_ownership_verification_is_refused(
        self, application
    ):
        """The ownership gate answers with its own identifier, not the generic one.

        PRD: "The rehabilitation application has `ownership_verification_status`
        equal to `VERIFIED` — otherwise `ERR_OWNERSHIP_NOT_VERIFIED` (409).
        Applies to two operations: reserving an inspection window and opening a
        work write-up."

        Design: Corner/validations/scheduling_an_inspection_before_ownership_verification_is_rejected
        """
        application_id = application["id"]
        assert application["ownership_verification_status"] == "PENDING"
        window = create_inspection_payload(
            application_id,
            scheduled_start_at="2026-08-03T13:00:00Z",
            scheduled_end_at="2026-08-03T15:00:00Z",
        )

        response = api_client.create_inspection(window, INSPECTOR)

        validate_error(response, "ERR_OWNERSHIP_NOT_VERIFIED", 409)
        rows, meta = validate_paginated(
            api_client.list_inspections(INSPECTOR, {"application_id": application_id})
        )
        assert rows == []
        assert meta["total_count"] == 0, (
            f"No site visit is left behind to block a later window, got {rows}"
        )
        validate_error(
            api_client.create_write_up(
                create_write_up_payload(application_id, application["version"]), REHAB
            ),
            "ERR_OWNERSHIP_NOT_VERIFIED",
            409,
        )

        verify_application_ownership(application_id)

        scheduled = validate_success(
            api_client.create_inspection(window, INSPECTOR), 201
        )
        assert scheduled["status"] == "SCHEDULED", (
            "The identical window is accepted once ownership is verified"
        )
        assert (
            refresh_application(application_id)["ownership_verification_status"]
            == "VERIFIED"
        )


class TestWriteUpSubmissionGates:
    """Submission tests emptiness first and the priority subtotal second."""

    def test_an_empty_scope_is_refused_for_emptiness_not_for_its_priorities(
        self, inspected_case
    ):
        """A scope with no lines reports the emptiness identifier alone.

        PRD: "Submission requires at least one repair line — an empty scope is
        refused with `ERR_WRITE_UP_EMPTY` — and requires that the scope address at
        least one health-and-safety or code repair, so a
        `priority_repair_total_cents` of zero is refused with
        `ERR_PRIORITY_REPAIRS_NOT_ADDRESSED`."

        Design: Corner/validations/submitting_an_empty_write_up_is_rejected
        """
        write_up = build_write_up(inspected_case["application"]["id"])
        assert write_up["work_item_count"] == 0

        response = api_client.submit_write_up(write_up["id"], REHAB)

        validate_error(response, "ERR_WRITE_UP_EMPTY", 422)
        unchanged = refresh_write_up(write_up["id"])
        assert unchanged["state"] == "DRAFT"
        assert unchanged["work_item_count"] == 0
        assert unchanged["base_estimate_cents"] == 0
        assert unchanged["total_estimate_cents"] == 0
        assert (
            refresh_application(inspected_case["application"]["id"])["workflow_state"]
            == "INSPECTED"
        )

    def test_a_general_improvement_only_scope_is_refused_on_its_priority_subtotal(
        self, inspected_case
    ):
        """A non-empty scope still fails while no health-and-safety or code line is in it.

        PRD: "The write-up has `priority_repair_total_cents` greater than 0 —
        otherwise `ERR_PRIORITY_REPAIRS_NOT_ADDRESSED` (422). Applies to two
        operations: submitting a write-up and opening a bid solicitation."

        Design: Corner/validations/submitting_a_general_improvement_only_write_up_is_rejected
        """
        write_up = build_write_up(inspected_case["application"]["id"])
        add_work_item(write_up["id"], **GENERAL_LINE)

        response = api_client.submit_write_up(write_up["id"], REHAB)

        validate_error(response, "ERR_PRIORITY_REPAIRS_NOT_ADDRESSED", 422)
        refused = refresh_write_up(write_up["id"])
        assert refused["state"] == "DRAFT"
        assert refused["work_item_count"] == 1
        assert refused["base_estimate_cents"] == 800_000, (
            "The scope carries real money, it simply carries no priority repair"
        )
        assert refused["priority_repair_total_cents"] == 0

        add_work_item(write_up["id"], **CODE_LINE)
        submitted = validate_success(
            api_client.submit_write_up(write_up["id"], REHAB), 200
        )

        assert submitted["state"] == "SUBMITTED"
        assert submitted["priority_repair_total_cents"] == 300_000, (
            "The added code line is the whole priority subtotal, got "
            f"{submitted['priority_repair_total_cents']}"
        )
        assert submitted["base_estimate_cents"] == 1_100_000
        assert submitted["contingency_cents"] == 110_000
        assert submitted["total_estimate_cents"] == 1_210_000


class TestReferenceResolutionOutranksPayloadShape:
    """A request that is wrong twice reports the unresolved row, not the bad body."""

    def test_an_unknown_case_reference_outranks_the_reversed_window(
        self, ownership_verified_application
    ):
        """Body references resolve before the window's ordering is judged.

        PRD: "Note also that the two 404 layers precede schema validation, so a
        request with both a bad identifier and a malformed body reports the
        missing row."

        Design: Corner/validations/unresolvable_body_fk_outranks_the_reversed_window_shape_error_not_found
        """
        unresolvable = api_client.create_inspection(
            create_inspection_payload(NON_EXISTENT_UUID, **REVERSED_WINDOW), INSPECTOR
        )

        validate_error(unresolvable, "ERR_APPLICATION_NOT_FOUND", 404)

        malformed = api_client.create_inspection(
            create_inspection_payload(
                ownership_verified_application["id"], **REVERSED_WINDOW
            ),
            INSPECTOR,
        )

        validate_error(malformed, "ERR_INVALID_REQUEST", 400)
        _, meta = validate_paginated(
            api_client.list_inspections(
                INSPECTOR,
                {"application_id": ownership_verified_application["id"]},
            )
        )
        assert meta["total_count"] == 0, (
            f"Neither refusal writes a site visit, got {meta['total_count']}"
        )


class TestCumulativeChangeOrderCeiling:
    """Each change order is modest; the running total against the contract is not."""

    @pytest.fixture
    def secured_loan_case(self):
        """A 2,000,000 awarded contract on a deferred note whose lien is recorded."""
        return setup_case(
            stage="lien_recorded",
            loan_overrides={
                "structure_type": "DEFERRED",
                "forgiveness_term_months": 60,
            },
        )

    def test_the_first_change_order_moves_the_cost_the_note_and_the_commitment(
        self, secured_loan_case
    ):
        """A 300,000 increase is fifteen percent of the awarded contract.

        PRD: "`cumulative_delta_pct` is one hundred multiplied by the cumulative
        delta divided by the loan's `awarded_bid_amount_cents`, rounded half up to
        two decimal places."

        Design: Corner/validations/individually_modest_change_orders_collectively_hit_the_twenty_percent_ceiling
        """
        case = secured_loan_case
        loan_id = case["loan"]["id"]
        assert case["loan"]["awarded_bid_amount_cents"] == 2_000_000
        assert case["loan"]["principal_cents"] == 2_015_000
        submitted = _submit_change_order(
            loan_id, 300_000, "Concealed rafter rot found on demolition"
        )
        assert_change_order(submitted)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["cumulative_delta_pct"] == pytest.approx(0.0, abs=0.01)

        approved = validate_success(
            api_client.approve_change_order(submitted["id"], PROGRAM_MANAGER), 200
        )

        assert approved["status"] == "APPROVED"
        assert approved["cumulative_delta_pct"] == pytest.approx(15.00, abs=0.01), (
            "300,000 against a 2,000,000 contract is 15.00 percent, got "
            f"{approved['cumulative_delta_pct']}"
        )
        loan = refresh_loan(loan_id)
        assert loan["approved_project_cost_cents"] == 2_300_000
        assert loan["principal_cents"] == 2_315_000
        assert loan["lien_recording_fee_cents"] == 15_000, (
            "The fee tier is not re-derived from the grown cost, got "
            f"{loan['lien_recording_fee_cents']}"
        )
        program_year = refresh_program_year(case["program_year"]["id"])
        assert program_year["committed_amount_cents"] == 2_300_000
        assert program_year["uncommitted_amount_cents"] == 47_685_000

    def test_a_cumulative_twenty_percent_exactly_is_still_approved(
        self, secured_loan_case
    ):
        """The second change order brings the running total to the limit itself.

        PRD: "The program tolerates cumulative growth up to twenty percent of the
        awarded contract: a cumulative figure exactly at 20.00 percent is
        approved, and anything above it is refused with
        `ERR_CHANGE_ORDER_EXCEEDS_LIMIT`."

        Design: Corner/validations/individually_modest_change_orders_collectively_hit_the_twenty_percent_ceiling
        """
        case = secured_loan_case
        loan_id = case["loan"]["id"]
        first = _submit_change_order(
            loan_id, 300_000, "Concealed rafter rot found on demolition"
        )
        validate_success(
            api_client.approve_change_order(first["id"], PROGRAM_MANAGER), 200
        )
        second = _submit_change_order(
            loan_id, 100_000, "Additional flashing and gutter tie-in"
        )

        approved = validate_success(
            api_client.approve_change_order(second["id"], PROGRAM_MANAGER), 200
        )

        assert approved["cumulative_delta_pct"] == pytest.approx(20.00, abs=0.01), (
            "300,000 plus 100,000 against 2,000,000 is exactly 20.00 percent, got "
            f"{approved['cumulative_delta_pct']}"
        )
        assert approved["status"] == "APPROVED", (
            "A figure sitting exactly at the limit is inside it"
        )
        loan = refresh_loan(loan_id)
        assert loan["approved_project_cost_cents"] == 2_400_000
        assert loan["principal_cents"] == 2_415_000
        program_year = refresh_program_year(case["program_year"]["id"])
        assert program_year["committed_amount_cents"] == 2_400_000
        assert program_year["uncommitted_amount_cents"] == 47_585_000

    def test_the_next_modest_increase_tips_over_the_limit_and_writes_nothing(
        self, secured_loan_case
    ):
        """A 10,000 change order is refused because the running total reaches 20.50.

        PRD: "This is an aggregate test — each individual change order may be
        modest while the running total crosses the limit."

        Design: Corner/validations/individually_modest_change_orders_collectively_hit_the_twenty_percent_ceiling
        """
        case = secured_loan_case
        loan_id = case["loan"]["id"]
        first = _submit_change_order(
            loan_id, 300_000, "Concealed rafter rot found on demolition"
        )
        validate_success(
            api_client.approve_change_order(first["id"], PROGRAM_MANAGER), 200
        )
        second = _submit_change_order(
            loan_id, 100_000, "Additional flashing and gutter tie-in"
        )
        validate_success(
            api_client.approve_change_order(second["id"], PROGRAM_MANAGER), 200
        )
        third = _submit_change_order(loan_id, 10_000, "Ridge vent upgrade")

        response = api_client.approve_change_order(third["id"], PROGRAM_MANAGER)

        validate_error(response, "ERR_CHANGE_ORDER_EXCEEDS_LIMIT", 422)
        refused = validate_success(
            api_client.get_change_order(third["id"], REHAB), 200
        )
        assert refused["status"] == "SUBMITTED", (
            f"The refused change order stays open, got {refused['status']}"
        )
        loan = refresh_loan(loan_id)
        assert loan["approved_project_cost_cents"] == 2_400_000, (
            "The refusal moves no money, got "
            f"{loan['approved_project_cost_cents']}"
        )
        assert loan["principal_cents"] == 2_415_000
        program_year = refresh_program_year(case["program_year"]["id"])
        assert program_year["committed_amount_cents"] == 2_400_000
        assert program_year["uncommitted_amount_cents"] == 47_585_000
