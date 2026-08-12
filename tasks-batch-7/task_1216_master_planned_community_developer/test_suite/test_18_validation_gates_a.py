"""Corner coverage: authentication, authorization matrix, uniqueness scopes,
exactly-one-of identity rules, and cross-entity referential checks."""
from test_helpers import (
    api_client,
    create_active_agreement,
    create_active_community,
    create_adopted_budget,
    create_and_close_lot,
    create_closing_payload,
    create_draft_agreement,
    create_district_with_advances,
    create_offered_lot,
    create_open_phase,
    create_phase,
    create_lot,
    create_builder,
    create_community,
    create_resident,
    set_clock,
    get_success_data,
    validate_error,
    build_user_headers,
    make_builder_rep_headers,
    ApiErrorId,
    TEST_USERS,
)
from test_helpers.factories import (
    create_agreement_payload,
    create_application_payload,
    create_budget_payload,
    create_district_payload,
    create_event_payload,
    create_tranche_payload,
    create_violation_payload,
)

EXEC = TEST_USERS["declarant_executive_headers"]
CTRL = TEST_USERS["declarant_controller_headers"]
DIRECTOR = TEST_USERS["association_director_headers"]
REVIEWER = TEST_USERS["design_reviewer_headers"]
LIFESTYLE = TEST_USERS["lifestyle_coordinator_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


class TestMissingAuthHeaders:
    def test_missing_role_header_is_unauthenticated(self):
        """PRD §2.1: "A request whose `X-User-Role` is missing or does not name one of these roles, or whose `X-User-ID` is missing, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401); the platform clock endpoint is authenticated under the same rule.".

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        # No X-User-Role / X-User-ID headers at all.
        resp = api_client.create_community(
            {"community_name": "Anon Acres", "total_planned_units": 5}, headers={}
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestForbiddenRoleMatrix:
    def test_exclusive_operations_reject_foreign_roles(self):
        """PRD §2.1: "A request whose named role is not in the target endpoint's authorized role list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: POST /mpc/budgets -> DeclarantController; POST /mpc/agreements
        -> DeclarantController; POST /mpc/events -> LifestyleCoordinator;
        POST /_clock/set_current_utc -> PlatformAdmin.

        Design: Corner/validations/forbidden_role_matrix
        """
        community = create_active_community("Role Ridge", 10)

        resp1 = api_client.create_budget(
            create_budget_payload(community_id=community["id"], fiscal_year=2027),
            make_builder_rep_headers("builder-x"),
        )
        validate_error(resp1, ApiErrorId.ERR_FORBIDDEN_ROLE)

        resp2 = api_client.create_agreement(
            create_agreement_payload(
                community_id=community["id"], builder_id="builder-x", phase_id="phase-x",
                base_price_per_lot_cents=100, annual_escalation_pct=1.0,
                penalty_per_lot_per_day_cents=1, earnest_money_cents=1, total_lots_committed=1,
            ),
            LIFESTYLE,
        )
        validate_error(resp2, ApiErrorId.ERR_FORBIDDEN_ROLE)

        resp3 = api_client.create_event(
            create_event_payload(
                community_id=community["id"], title="Nope",
                start_at="2026-06-01T10:00:00Z", end_at="2026-06-01T12:00:00Z", capacity=5,
            ),
            REVIEWER,
        )
        validate_error(resp3, ApiErrorId.ERR_FORBIDDEN_ROLE)

        resp4 = api_client.set_clock(
            {"to_iso8601": "2026-06-01T00:00:00Z"},
            build_user_headers("res-x", "HomeownerResident"),
        )
        validate_error(resp4, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestDuplicateConstraints:
    def test_four_uniqueness_scopes_reject_second_writer(self):
        """PRD §3.5: "Only one budget per community and fiscal year may exist outside `SUPERSEDED` status; a duplicate is rejected `ERR_DUPLICATE_FISCAL_YEAR`."
        PRD §3.6: "A `DeclarantController` creates at most one `ReimbursementDistrict` per community (`ERR_DUPLICATE_DISTRICT`), naming it (`district_name`, in the MUD/PID/CFD style) and fixing its `interest_rate_annual_pct` (zero or more).".
        PRD §3.3: "Against a `DRAFT` agreement, the controller adds `TakedownTranche` rows — each with a `tranche_no` unique within the agreement (duplicates are rejected `ERR_DUPLICATE_TRANCHE_NO`), a `due_date`, and a `lot_count_due` of at least 1, representing the lots due by that date for that tranche alone, not cumulatively.".
        PRD §3.5: "The rate's `fiscal_year` must equal its budget's (`ERR_FISCAL_YEAR_MISMATCH`), the referenced budget must be `ADOPTED` (`ERR_BUDGET_NOT_ADOPTED`), and only one non-`SUPERSEDED` rate may exist per community and fiscal year (`ERR_DUPLICATE_ASSESSMENT_YEAR`).".

        Design: Corner/validations/duplicate_constraints
        """
        community = create_active_community("Dup Dunes", 10)
        budget = get_success_data(
            api_client.create_budget(
                create_budget_payload(community_id=community["id"], fiscal_year=2027), CTRL
            )
        )
        district, _ = create_district_with_advances(community["id"], [], "MUD 1")
        phase = create_phase(community["id"], "P1", 1, 5)
        builder = create_builder(community["id"], "Dup Builders", "A")
        agreement, _ = create_draft_agreement(
            community["id"], builder["id"], phase["id"], 1,
            [("2026-06-30T00:00:00Z", 1)],
            base_price_per_lot_cents=1000000, annual_escalation_pct=1.0,
            penalty_per_lot_per_day_cents=100, earnest_money_cents=1000,
        )
        adopted = create_adopted_budget(community["id"], 2028, [("MANAGEMENT", 100000)])
        # FY2027 budget adopted via a second budget row path: use the first
        # budget through the full lifecycle for the rate. Clock is already at
        # 2026-05-17 from the FY2028 adoption above, so notice send_at must be
        # strictly later.
        from test_helpers import create_and_schedule_notice, create_proposed_budget
        from test_helpers.factories import create_line_item_payload
        get_success_data(
            api_client.create_line_item(
                create_line_item_payload(budget_id=budget["id"], category="MANAGEMENT",
                                         amount_cents=100000),
                CTRL,
            )
        )
        get_success_data(api_client.propose_budget(budget["id"], CTRL))
        create_and_schedule_notice(
            community["id"], "BUDGET_ADOPTION", "2026-05-18T00:00:00Z",
            budget_id=budget["id"], subject="b", body="adopt",
        )
        set_clock("2026-05-18T00:00:00Z")
        set_clock("2026-06-02T00:00:00Z")
        get_success_data(api_client.adopt_budget(budget["id"], DIRECTOR))
        get_success_data(
            api_client.create_assessment_rate(
                {"community_id": community["id"], "budget_id": budget["id"], "fiscal_year": 2027},
                CTRL,
            )
        )

        resp_budget = api_client.create_budget(
            create_budget_payload(community_id=community["id"], fiscal_year=2027), CTRL
        )
        validate_error(resp_budget, ApiErrorId.ERR_DUPLICATE_FISCAL_YEAR)

        resp_district = api_client.create_district(
            create_district_payload(
                community_id=community["id"], district_name="MUD 1 Again",
                interest_rate_annual_pct=4.0,
            ),
            CTRL,
        )
        validate_error(resp_district, ApiErrorId.ERR_DUPLICATE_DISTRICT)

        resp_tranche = api_client.create_tranche(
            create_tranche_payload(
                agreement_id=agreement["id"], tranche_no=1,
                due_date="2026-09-30T00:00:00Z", lot_count_due=1,
            ),
            CTRL,
        )
        validate_error(resp_tranche, ApiErrorId.ERR_DUPLICATE_TRANCHE_NO)

        resp_rate = api_client.create_assessment_rate(
            {"community_id": community["id"], "budget_id": budget["id"], "fiscal_year": 2027},
            CTRL,
        )
        validate_error(resp_rate, ApiErrorId.ERR_DUPLICATE_ASSESSMENT_YEAR)


class TestIdentityValidationApplicantAndRespondent:
    def test_exactly_one_of_applicant_and_respondent(self):
        """PRD §3.7: "Exactly one of the two applicant identifiers must be present (`ERR_APPLICANT_IDENTITY_INVALID`)."
        PRD §3.7: "A `DesignReviewer` or `AssociationDirector` reports a `DesignViolation` with a `community_id`, a `lot_id`, a `violation_type` of `UNAPPROVED_MODIFICATION`, `NONCONFORMING_MATERIALS`, `SETBACK`, or `LANDSCAPE_DEADLINE`, and exactly one respondent — `respondent_resident_id` or `respondent_builder_id` (`ERR_RESPONDENT_IDENTITY_INVALID`)."

        Design: Corner/validations/identity_validation_applicant_and_respondent
        """
        community = create_active_community("Identity Isle", 10)
        phase = create_phase(community["id"], "P1", 1, 5)
        lot = create_lot(phase["id"], "L1")
        builder = create_builder(community["id"], "ID Builders", "A")
        resident = create_resident(community["id"], "Ida Identity", "ida@x.com")

        resp_app = api_client.create_application(
            create_application_payload(
                community_id=community["id"], lot_id=lot["id"], project_type="LANDSCAPE",
                applicant_builder_id=builder["id"], applicant_resident_id=resident["id"],
            ),
            make_builder_rep_headers(builder["id"]),
        )
        validate_error(resp_app, ApiErrorId.ERR_APPLICANT_IDENTITY_INVALID)

        resp_vio = api_client.create_violation(
            create_violation_payload(
                community_id=community["id"], lot_id=lot["id"], violation_type="SETBACK",
            ),
            REVIEWER,
        )
        validate_error(resp_vio, ApiErrorId.ERR_RESPONDENT_IDENTITY_INVALID)


class TestLotPhaseMismatch:
    def test_closing_lot_must_belong_to_agreement_phase(self):
        """PRD §3.4: "Creation requires the agreement to be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`), the lot to be `OFFERED` (`ERR_LOT_NOT_OFFERED`), and the lot to belong to the agreement's phase (`ERR_LOT_PHASE_MISMATCH`); the closing starts `PENDING`, its `community_id` is denormalized from the agreement, and the lot moves automatically from `OFFERED` to `UNDER_CONTRACT`.".

        Design: Corner/validations/lot_phase_mismatch
        """
        community = create_active_community("Mismatch Mesa", 20)
        phase1 = create_open_phase(community["id"], "P1", 1, 5)
        phase2 = create_phase(community["id"], "P2", 2, 5)
        builder = create_builder(community["id"], "Mismatch Builders", "A")
        agreement, _ = create_active_agreement(
            community["id"], builder["id"], phase1["id"], 2,
            [("2026-06-30T00:00:00Z", 2)], earnest_money_cents=1000000,
        )
        lot_a = create_offered_lot(phase1["id"], "M1")
        set_clock("2026-06-01T00:00:00Z")
        create_and_close_lot(agreement["id"], lot_a["id"])  # phase1 -> DELIVERING
        get_success_data(api_client.open_sales(phase2["id"], EXEC))
        lot_b = create_offered_lot(phase2["id"], "M2")

        resp = api_client.create_closing(
            create_closing_payload(agreement_id=agreement["id"], lot_id=lot_b["id"]), CTRL
        )
        validate_error(resp, ApiErrorId.ERR_LOT_PHASE_MISMATCH)
        lot_read = get_success_data(api_client.get_lot(lot_b["id"], EXEC))
        assert lot_read["status"] == "OFFERED", "the rejected escrow leaves lot B OFFERED"


class TestResidentCommunityMismatch:
    def test_record_purchase_cross_community_lot_rejected(self):
        """PRD §3.8: "Recording a purchase links the prospect to their homesite `lot_id`: the lot must belong to the same community as the resident (`ERR_RESIDENT_COMMUNITY_MISMATCH`) and must be `UNDER_CONTRACT` or `CLOSED` (`ERR_LOT_NOT_UNDER_CONTRACT`); the resident becomes a `PURCHASER`."

        Design: Corner/validations/resident_community_mismatch
        """
        community_a = create_active_community("Community A", 10)
        phase_a = create_open_phase(community_a["id"], "P1", 1, 5)
        builder_a = create_builder(community_a["id"], "A Builders", "A")
        agreement_a, _ = create_active_agreement(
            community_a["id"], builder_a["id"], phase_a["id"], 1,
            [("2026-06-30T00:00:00Z", 1)], earnest_money_cents=1000000,
        )
        lot_a = create_offered_lot(phase_a["id"], "A1")
        get_success_data(
            api_client.create_closing(
                create_closing_payload(agreement_id=agreement_a["id"], lot_id=lot_a["id"]), CTRL
            )
        )

        community_b = create_community("Community B", 10)
        resident_b = create_resident(community_b["id"], "Bella Buyer", "bella@x.com")

        resp = api_client.record_purchase(resident_b["id"], {"lot_id": lot_a["id"]}, LIFESTYLE)
        validate_error(resp, ApiErrorId.ERR_RESIDENT_COMMUNITY_MISMATCH)
        resident_read = get_success_data(api_client.get_resident(resident_b["id"], LIFESTYLE))
        assert resident_read["status"] == "PROSPECT"
        assert resident_read["lot_id"] is None


class TestTrancheCoverageMismatchAtExecute:
    def test_execute_requires_exact_coverage(self):
        """PRD §3.3: "Execution moves the agreement from `DRAFT` to `EXECUTED` under a `DeclarantExecutive` and enforces four gates: the community must be `ACTIVE` (`ERR_COMMUNITY_NOT_ACTIVE`), the builder must be in `GOOD_STANDING` (`ERR_BUILDER_NOT_IN_GOOD_STANDING`), the phase must be `SALES_OPEN` or `DELIVERING` (`ERR_PHASE_NOT_OPEN_FOR_SALES`), and the tranche schedule must exactly cover the commitment — the sum of `lot_count_due` across the agreement's tranches must equal `total_lots_committed` (`ERR_TRANCHE_COVERAGE_MISMATCH`)."

        Design: Corner/validations/tranche_coverage_mismatch_at_execute
        """
        community = create_active_community("Coverage Creek", 20)
        phase = create_open_phase(community["id"], "P1", 1, 10)
        builder = create_builder(community["id"], "Coverage Builders", "A")
        agreement, _ = create_draft_agreement(
            community["id"], builder["id"], phase["id"], 3,
            [("2026-06-30T00:00:00Z", 2)],
        )
        resp = api_client.execute_agreement(agreement["id"], EXEC)
        validate_error(resp, ApiErrorId.ERR_TRANCHE_COVERAGE_MISMATCH)
        read = get_success_data(api_client.get_agreement(agreement["id"], CTRL))
        assert read["status"] == "DRAFT"
        assert read["execution_date"] is None
