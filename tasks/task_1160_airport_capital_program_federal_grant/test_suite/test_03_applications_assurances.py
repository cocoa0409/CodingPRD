"""Grant applications and the sponsor-assurance checklist (PRD §2.5, §2.10, §3.1–§3.4)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error,
    assert_grant_application, assert_sponsor_assurance, assert_money,
    create_application_payload,
    create_sponsor, create_draft_program, add_project, submit_program, accept_program,
    apply_selection, create_application, list_assurances, certify_all_assurances,
    submit_application, offer_application,
    setup_accepted_program_with_selection, setup_certified_application,
    set_clock, make_compliance_officer_headers,
    TEST_USERS, ApiErrorId,
    SPONSOR_USER_ID, COMPLIANCE_USER_ID, ASSURANCE_CODES,
)

FAA = TEST_USERS["faa_manager_headers"]
SPONSOR = TEST_USERS["sponsor_staff_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


class TestApplicationCreation:
    def test_application_creation_auto_creates_six_assurances(self):
        """PRD §3.3: "Creation also auto-generates the federal assurance checklist: exactly
        six SponsorAssurance children, one per `assurance_code` — `TITLE_VI`, `BUY_AMERICAN`,
        `DBE_PROGRAM`, `ENVIRONMENTAL_REVIEW`, `PREVAILING_WAGE`, and `AIRPORT_FEES` — each
        linked back through its `application_id` and each starting in `PENDING`."
        PRD §3.3: "The application exposes `assurances_total`, always 6, and
        `assurances_cleared`, the count of its child assurances currently in `CERTIFIED` or
        `WAIVED`."

        Design: Corner/entities/application_creation_auto_creates_six_assurances
        """
        sponsor = create_sponsor()
        program = create_draft_program(sponsor["id"])
        project = add_project(program["id"], title="Apron", project_type="CAPACITY",
                              estimated_cost=250_000, safety_score=5, capacity_score=5,
                              preservation_score=5, security_score=5, environmental_score=5)
        app = validate_success(api_client.create_application(
            create_application_payload(sponsor["id"], program["id"], [project["id"]]),
            SPONSOR), 201)
        assert_grant_application(app)
        assert app["assurances_total"] == 6
        assert app["assurances_cleared"] == 0
        # PRD §3.3: "Creation computes `total_eligible_cost` as the sum of `estimated_cost`
        # over the listed projects" and "derives `submission_deadline` as May 15 at 23:59:59
        # UTC of the year preceding the referenced program's `fiscal_year`."
        assert_money(app["total_eligible_cost"], 250_000.00, "total_eligible_cost")
        assert app["submission_deadline"].startswith("2026-05-15T23:59:59")

        rows = validate_success(api_client.list_assurances(app["id"], SPONSOR), 200)
        assert len(rows) == 6
        assert sorted(r["assurance_code"] for r in rows) == sorted(ASSURANCE_CODES)
        for row in rows:
            assert_sponsor_assurance(row)
            assert row["application_id"] == app["id"]
            assert row["status"] == "PENDING"

    def test_assurance_immutable_entity_shape(self):
        """PRD §2.5: "A SponsorAssurance, a DBEReport, and an AuditFinding each carry only
        `id` and `created_at`; both `updated_at` and `version` are absent from these
        resources, since each is written once and then transitioned to a terminal outcome."

        Design: Corner/entities/assurance_immutable_entity_shape
        """
        sponsor = create_sponsor()
        program = create_draft_program(sponsor["id"])
        project = add_project(program["id"], title="Apron", project_type="CAPACITY",
                              estimated_cost=250_000, safety_score=5, capacity_score=5,
                              preservation_score=5, security_score=5, environmental_score=5)
        app = create_application(sponsor["id"], program["id"], [project["id"]])
        rows = validate_success(api_client.list_assurances(app["id"], SPONSOR), 200)
        assert len(rows) == 6
        for row in rows:
            assert "id" in row and "created_at" in row
            assert "version" not in row, "version must be absent from SponsorAssurance"
            assert "updated_at" not in row, "updated_at must be absent from SponsorAssurance"

    def test_application_create_empty_project_ids_rejected(self):
        """PRD §3.3: "The array must contain at least one element and no duplicates — an empty
        or duplicate-bearing list is rejected with `ERR_EMPTY_SELECTION` (HTTP 422)".

        Design: Corner/validations/application_create_empty_project_ids_rejected
        """
        sponsor = create_sponsor()
        program = create_draft_program(sponsor["id"])
        res = api_client.create_application(
            create_application_payload(sponsor["id"], program["id"], []), SPONSOR)
        validate_error(res, ApiErrorId.ERR_EMPTY_SELECTION, expected_status=422)


class TestAssuranceCertification:
    def test_assurance_certify_twice_rejected(self):
        """PRD §3.3: "A `ComplianceOfficer` certifies an assurance, moving it from `PENDING`
        to `CERTIFIED` with `certified_by_user_id` set".
        PRD §2.9: "state preconditions for the requested transition (generic failures carry
        `ERR_INVALID_STATE`, HTTP 409, while specific ones carry their dedicated codes)".

        Design: Corner/state_machines/assurance_certify_twice_rejected
        """
        sponsor = create_sponsor()
        program = create_draft_program(sponsor["id"])
        project = add_project(program["id"], title="Apron", project_type="CAPACITY",
                              estimated_cost=250_000, safety_score=5, capacity_score=5,
                              preservation_score=5, security_score=5, environmental_score=5)
        app = create_application(sponsor["id"], program["id"], [project["id"]])
        row = list_assurances(app["id"])[0]
        first = validate_success(api_client.certify_assurance(row["id"], COMPLIANCE), 200)
        assert first["status"] == "CERTIFIED"

        res = api_client.certify_assurance(
            row["id"], make_compliance_officer_headers("user-compl-2"))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        app_after = validate_success(api_client.get_application(app["id"], SPONSOR), 200)
        assert app_after["assurances_cleared"] == 1, "no double count on a repeated certify"

    def test_assurance_self_certify_rejected(self):
        """PRD §2.10: "the certifier's `X-User-ID` is compared against the application's
        `created_by_user_id`, and a match is rejected with `ERR_SOD_VIOLATION` (HTTP 403)."

        Design: Corner/validations/assurance_self_certify_rejected
        """
        sponsor = create_sponsor()
        program = create_draft_program(sponsor["id"])
        project = add_project(program["id"], title="Apron", project_type="CAPACITY",
                              estimated_cost=250_000, safety_score=5, capacity_score=5,
                              preservation_score=5, security_score=5, environmental_score=5)
        # Application created by operator user-sponsor-1.
        app = create_application(sponsor["id"], program["id"], [project["id"]],
                                 creator_user_id=SPONSOR_USER_ID)
        row = list_assurances(app["id"])[0]
        res = api_client.certify_assurance(
            row["id"], make_compliance_officer_headers(SPONSOR_USER_ID))
        validate_error(res, ApiErrorId.ERR_SOD_VIOLATION, expected_status=403)
        row_after = [r for r in list_assurances(app["id"]) if r["id"] == row["id"]][0]
        assert row_after["status"] == "PENDING"


class TestApplicationLifecycle:
    def test_application_return_resubmit_cycle_status(self):
        """PRD §3.3: "A `FAAManager` who finds an application deficient returns it, moving
        `UNDER_REVIEW` to `RETURNED` and incrementing `version`, which reopens the sponsor's
        correction loop."
        PRD §3.3: "Submitting the application — from `DRAFT`, or resubmitting from `RETURNED`
        — moves it to `UNDER_REVIEW`".

        Design: Difficulty/non_linear_state_machine/application_return_resubmit_cycle
        """
        ctx = setup_certified_application()
        app_id = ctx["application"]["id"]
        submitted = submit_application(app_id)
        assert submitted["status"] == "UNDER_REVIEW"
        returned = validate_success(api_client.return_application(app_id, FAA), 200)
        assert returned["status"] == "RETURNED"
        resubmitted = submit_application(app_id)
        assert resubmitted["status"] == "UNDER_REVIEW"

    def test_application_return_resubmit_cycle_version_drift(self):
        """PRD §3.3: "each successful submission increments the application's `version` by
        one".
        PRD §3.3: "A `FAAManager` who finds an application deficient returns it, moving
        `UNDER_REVIEW` to `RETURNED` and incrementing `version`".

        Design: Difficulty/non_linear_state_machine/application_return_resubmit_cycle
        """
        ctx = setup_certified_application()
        app_id = ctx["application"]["id"]
        v_create = ctx["application"]["version"]
        v_submit = submit_application(app_id)["version"]
        assert v_submit == v_create + 1
        v_return = validate_success(
            api_client.return_application(app_id, FAA), 200)["version"]
        assert v_return == v_submit + 1
        v_resubmit = submit_application(app_id)["version"]
        assert v_resubmit == v_return + 1

    def test_declined_application_is_terminal(self):
        """PRD §3.3: "Declining the offer instead moves the application to the terminal
        `DECLINED` state with no further effect."
        PRD §2.9: "state preconditions for the requested transition (generic failures carry
        `ERR_INVALID_STATE`, HTTP 409, while specific ones carry their dedicated codes)".

        Design: Corner/state_machines/declined_application_is_terminal
        """
        ctx = setup_certified_application()
        app_id = ctx["application"]["id"]
        submit_application(app_id)
        offer_application(app_id)
        declined = validate_success(api_client.decline_offer(app_id, SPONSOR), 200)
        assert declined["status"] == "DECLINED"
        res = api_client.submit_application(app_id, SPONSOR)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        after = validate_success(api_client.get_application(app_id, SPONSOR), 200)
        assert after["status"] == "DECLINED"


class TestApplicationSubmitGates:
    def test_submit_requires_program_accepted_rejected(self):
        """PRD §3.3: "the referenced program must be `ACCEPTED` (otherwise
        `ERR_PROGRAM_NOT_ACCEPTED`, HTTP 409)".

        Design: Difficulty/cross_entity_state_dependency/application_submit_requires_program_accepted
        """
        set_clock("2026-05-01T00:00:00Z")
        sponsor = create_sponsor()
        program = create_draft_program(sponsor["id"])
        project = add_project(program["id"])
        submit_program(program["id"])  # program SUBMITTED, never accepted
        app = create_application(sponsor["id"], program["id"], [project["id"]])
        certify_all_assurances(app["id"])
        res = api_client.submit_application(app["id"], SPONSOR)
        validate_error(res, ApiErrorId.ERR_PROGRAM_NOT_ACCEPTED, expected_status=409)
        after = validate_success(api_client.get_application(app["id"], SPONSOR), 200)
        assert after["status"] == "DRAFT"

    def test_submit_succeeds_after_program_accepted(self):
        """PRD §3.1: "A `FAAManager` then accepts a submitted program, moving `SUBMITTED` to
        `ACCEPTED`."
        PRD §3.3: "Submitting the application — from `DRAFT`, or resubmitting from `RETURNED`
        — moves it to `UNDER_REVIEW`" once every submit gate passes.

        Design: Difficulty/cross_entity_state_dependency/application_submit_requires_program_accepted
        """
        set_clock("2026-05-01T00:00:00Z")
        sponsor = create_sponsor()
        program = create_draft_program(sponsor["id"])
        project = add_project(program["id"])
        submit_program(program["id"])
        app = create_application(sponsor["id"], program["id"], [project["id"]])
        certify_all_assurances(app["id"])
        # The program's own ACCEPT transition unlocks the application's submit.
        accepted = accept_program(program["id"])
        apply_selection(program["id"], 2_000_000, accepted["version"])
        submitted = submit_application(app["id"])
        assert submitted["status"] == "UNDER_REVIEW"

    def test_submit_after_deadline_rejected(self):
        """PRD §3.3: "the logical clock must not be past `submission_deadline` (otherwise
        `ERR_APPLICATION_DEADLINE_PASSED`, HTTP 422)".

        Design: Corner/validations/application_submit_after_deadline_rejected
        """
        ctx = setup_certified_application()
        app_id = ctx["application"]["id"]
        # FY2027 applications carry submission_deadline 2026-05-15T23:59:59Z.
        set_clock("2026-05-16T00:00:00Z")
        res = api_client.submit_application(app_id, SPONSOR)
        validate_error(res, ApiErrorId.ERR_APPLICATION_DEADLINE_PASSED, expected_status=422)
        after = validate_success(api_client.get_application(app_id, SPONSOR), 200)
        assert after["status"] == "DRAFT"

    def test_submit_unselected_project_rejected(self):
        """PRD §3.3: "every project in `project_ids` must currently be `SELECTED` (otherwise
        `ERR_PROJECT_NOT_SELECTED`, HTTP 422)".

        Design: Corner/validations/application_submit_unselected_project_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        sponsor = create_sponsor()
        program = create_draft_program(sponsor["id"])
        project = add_project(program["id"])
        submit_program(program["id"])
        accept_program(program["id"])  # ACCEPTED, but the selection sweep never ran
        app = create_application(sponsor["id"], program["id"], [project["id"]])
        certify_all_assurances(app["id"])
        res = api_client.submit_application(app["id"], SPONSOR)
        validate_error(res, ApiErrorId.ERR_PROJECT_NOT_SELECTED, expected_status=422)

    def test_submit_incomplete_assurances_rejected(self):
        """PRD §3.3: "and `assurances_cleared` must equal `assurances_total` (otherwise
        `ERR_ASSURANCES_INCOMPLETE`, HTTP 422)".
        PRD §3.3: "a `FAAManager` may instead waive one, moving it to `WAIVED`" — and waived
        assurances count toward `assurances_cleared`.

        Design: Corner/validations/application_submit_incomplete_assurances_rejected
        """
        ctx = setup_accepted_program_with_selection()
        app = create_application(ctx["sponsor"]["id"], ctx["program"]["id"],
                                 [ctx["project"]["id"]])
        rows = list_assurances(app["id"])
        for row in rows[:5]:  # certify only 5 of 6
            validate_success(api_client.certify_assurance(row["id"], COMPLIANCE), 200)
        res = api_client.submit_application(app["id"], SPONSOR)
        validate_error(res, ApiErrorId.ERR_ASSURANCES_INCOMPLETE, expected_status=422)

        # An FAA waiver of the last assurance clears the gate.
        validate_success(api_client.waive_assurance(rows[5]["id"], FAA), 200)
        submitted = submit_application(app["id"])
        assert submitted["status"] == "UNDER_REVIEW"


class TestEntitlementReconciliation:
    def test_npe_available_reconciles_on_accept_and_decline(self):
        """PRD §3.4: "Creation immediately debits the sponsor: `npe_entitlement_available` is
        reduced by `entitlement_portion`."
        PRD §3.3: "Declining the offer instead moves the application to the terminal
        `DECLINED` state with no further effect."

        Design: Corner/cross_cutting_layers/npe_available_reconciles_on_accept_and_decline
        """
        set_clock("2026-05-01T00:00:00Z")
        sponsor = create_sponsor(npe_total=5_000_000)
        program = create_draft_program(sponsor["id"])
        p1 = add_project(program["id"], title="P1", project_type="PRESERVATION",
                         estimated_cost=1_000_000)
        p2 = add_project(program["id"], title="P2", project_type="CAPACITY",
                         estimated_cost=400_000, safety_score=10)
        submit_program(program["id"])
        accepted = accept_program(program["id"])
        apply_selection(program["id"], 2_000_000, accepted["version"])

        app_a = create_application(sponsor["id"], program["id"], [p1["id"]])
        certify_all_assurances(app_a["id"])
        submit_application(app_a["id"])
        offer_application(app_a["id"])

        app_b = create_application(sponsor["id"], program["id"], [p2["id"]])
        certify_all_assurances(app_b["id"])
        submit_application(app_b["id"])
        offer_application(app_b["id"])

        # Accept A: entitlement portion (900,000 of the 900,000 obligation) is debited.
        accepted_a = validate_success(api_client.accept_offer(app_a["id"], SPONSOR), 200)
        assert accepted_a["created_grant_id"] is not None
        sponsor_after = validate_success(api_client.get_sponsor(sponsor["id"], SPONSOR), 200)
        assert_money(sponsor_after["npe_entitlement_available"], 4_100_000.00,
                     "npe_entitlement_available after accept")

        # Declining B changes nothing.
        declined_b = validate_success(api_client.decline_offer(app_b["id"], SPONSOR), 200)
        assert declined_b["status"] == "DECLINED"
        sponsor_final = validate_success(api_client.get_sponsor(sponsor["id"], SPONSOR), 200)
        assert_money(sponsor_final["npe_entitlement_available"], 4_100_000.00,
                     "npe_entitlement_available after decline")
