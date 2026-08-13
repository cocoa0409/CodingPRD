"""Role authorization boundaries: exclusive operations reject other roles with
ERR_UNAUTHORIZED even when the request is otherwise well-formed."""
from test_helpers import (
    ApiErrorId,
    create_grading_event_payload,
    create_intake,
    create_make_sheet,
    create_plant,
    create_released_additive_pair,
    create_vat,
    create_allocation_order,
    create_cut_wrap_run,
    create_export_certificate,
    make_completed_batch,
    make_released_batch,
    reconcile_run,
    set_clock,
    validate_error,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["plant_admin_headers"]
RECEIVER = TEST_USERS["milk_receiver_headers"]
PLANNER = TEST_USERS["make_planner_headers"]
CHEESEMAKER = TEST_USERS["cheesemaker_headers"]
SALES = TEST_USERS["sales_planner_headers"]


class TestExclusiveOperations:
    def test_cheesemaker_cannot_grade(self, api):
        """PRD §2.1: "A recognized role attempting an operation it is not
        permitted to perform is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §2.1: "`QAGrader` — quality grader; releases and recalls additive
        lots, grades batches, and releases graded batches; a grader must never
        grade a batch whose make steps that same user signed."

        Design: Corner/rbac/cheesemaker_cannot_grade
        """
        set_clock("2026-08-01T00:00:00Z")
        plant = create_plant(license_number="WI-260")
        vat = create_vat(plant["id"])
        intake = create_intake(plant["id"])
        culture, coagulant = create_released_additive_pair(plant["id"])
        make = create_make_sheet(
            vat["id"], vat["version"], intake["id"], culture["id"], coagulant["id"]
        )
        resp = api.create_grading_event(
            create_grading_event_payload(cheese_batch_id=make["id"]),
            CHEESEMAKER,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)

    def test_sales_planner_cannot_reconcile_cutwrap(self, api):
        """PRD §2.1: "A recognized role attempting an operation it is not
        permitted to perform is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §2.1: "`CutWrapOperator` — cut-and-wrap room operator; creates,
        reconciles, and voids conversion runs."

        Design: Corner/rbac/sales_planner_cannot_reconcile_cutwrap
        """
        ctx = make_released_batch(
            variety="MUENSTER", wheels_produced=4, green_weight_kg=500.0,
            age_to="2026-08-25T00:00:00Z",
        )
        order = create_allocation_order(
            ctx["batch_id"], channel="BRANDED", customer_name="House",
            wheels_requested=2, priority=1,
        )
        run = create_cut_wrap_run(
            order["id"], wheels_in=2, finished_case_weight_kg=5.4, trim_waste_kg=0.5
        )
        resp = api.reconcile_cut_wrap_run(run["id"], SALES)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)

    def test_make_planner_cannot_start_make(self, api):
        """PRD §2.1: "A recognized role attempting an operation it is not
        permitted to perform is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §2.1: "`Cheesemaker` — licensed cheesemaker; starts makes, signs
        off make-procedure steps, completes makes, performs CIP cleaning, and
        records whey valorization; the cheesemaker's identity is tracked on
        step sign-offs for segregation of duties."

        Design: Corner/rbac/make_planner_cannot_start_make
        """
        set_clock("2026-08-01T00:00:00Z")
        plant = create_plant(license_number="WI-262")
        vat = create_vat(plant["id"])
        intake = create_intake(plant["id"])
        culture, coagulant = create_released_additive_pair(plant["id"])
        make = create_make_sheet(
            vat["id"], vat["version"], intake["id"], culture["id"], coagulant["id"]
        )
        resp = api.start_make_sheet(make["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)

    def test_compliance_officer_exclusive_certificate_issue(self, api):
        """PRD §2.1: "A recognized role attempting an operation it is not
        permitted to perform is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §2.1: "`ComplianceOfficer` — export compliance officer; requests,
        issues, denies, and revokes export certificates."

        Design: Corner/rbac/compliance_officer_exclusive_certificate_issue
        """
        ctx = make_released_batch(
            variety="MUENSTER", wheels_produced=4, green_weight_kg=500.0,
            age_to="2026-08-25T00:00:00Z", export_listed=True,
        )
        order = create_allocation_order(
            ctx["batch_id"], channel="PRIVATE_LABEL", customer_name="Acme",
            wheels_requested=2, priority=1,
        )
        run = create_cut_wrap_run(
            order["id"], wheels_in=2, finished_case_weight_kg=5.4, trim_waste_kg=0.5
        )
        reconcile_run(run["id"])
        cert = create_export_certificate(
            run["id"], destination_country="DE", consignee="Berlin Imports"
        )
        resp = api.issue_export_certificate(cert["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
