"""Project creation defaults, phase advancement lockdown, tenant uniqueness,
auth-header enforcement, role authorization, error envelope, and 404 handling."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_project,
    build_user_headers,
    create_lod_requirement,
    create_lod_requirement_payload,
    create_model,
    create_partner,
    create_project,
    create_trade_partner_payload,
    get_model,
    get_project,
    is_iso8601_timestamp,
    make_trade_model_author_headers,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

VDC = TEST_USERS["vdc_manager_headers"]
COORD = TEST_USERS["bim_coordinator_headers"]
ENG = TEST_USERS["lead_engineer_headers"]
FM = TEST_USERS["facilities_manager_headers"]
AUTHOR = TEST_USERS["trade_model_author_headers"]
FAB = TEST_USERS["fabrication_lead_headers"]


class TestProjectCreation:
    def test_project_creation_applies_defaults(self, api):
        """PRD §3.1: "New projects begin in `SCHEMATIC_DESIGN` with
        `coordination_posture` at `NORMAL`, a `coordination_readiness_index`
        of 100, every derived counter at zero, and `ops_sweep_index` at zero."
        PRD §2.4: "The `version` is an integer that starts at 1 and increments
        by one on every mutation of that resource."

        Design: Corner/entities/project_creation_applies_defaults
        """
        resp = api.create_project({"name": "P0"}, VDC)
        project = validate_success(resp, 201)
        assert_project(project)
        assert project["current_phase"] == "SCHEMATIC_DESIGN"
        assert project["coordination_posture"] == "NORMAL"
        assert project["coordination_readiness_index"] == 100
        assert project["version"] == 1
        assert project["ops_sweep_index"] == 0
        assert project["open_critical_count"] == 0
        assert project["open_major_count"] == 0
        assert project["unassigned_minor_count"] == 0
        assert project["overdue_commitment_count"] == 0

    def test_project_create_missing_name_rejected(self, api):
        """PRD §3.1: "A `VDCManager` opens a coordination engagement by
        creating a **Project** with a `name`."
        PRD §2.8: "Fifth, request shape: required fields present, types
        correct, enum values within range, array constraints satisfied — a
        fabrication scope of one to three unique disciplines, a non-empty
        elements array whose each `gross_qty` is at least its `deduction_qty`
        with neither negative, element counters non-negative with at least one
        element across the three criticality classes — and `ends_at` strictly
        after `starts_at`; shape failures are `ERR_INVALID_REQUEST`, except
        malformed time ranges, which are `ERR_INVALID_TIME_RANGE`."

        Design: Corner/entities/project_create_missing_name_rejected
        """
        resp = api.create_project({}, VDC)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestPhaseAdvancement:
    def test_advance_phase_lockdown_at_closeout(self, api):
        """PRD §3.1: "A `VDCManager` advances the project's `current_phase`
        one step at a time along this order, and each advancement increments
        the project's `version` by one. `CLOSEOUT` is terminal — attempting to
        advance beyond it is rejected with `ERR_INVALID_PHASE_TRANSITION`."

        Design: Corner/state_machines/advance_phase_lockdown_at_closeout
        """
        project = create_project("SM17")
        expected = ["DESIGN_DEVELOPMENT", "CONSTRUCTION_DOCUMENTS",
                    "CONSTRUCTION_ADMINISTRATION", "CLOSEOUT"]
        for phase in expected:
            project = validate_success(api.advance_phase(project["id"], VDC))
            assert project["current_phase"] == phase
        resp = api.advance_phase(project["id"], VDC)
        validate_error(resp, ApiErrorId.ERR_INVALID_PHASE_TRANSITION)
        assert get_project(project["id"])["current_phase"] == "CLOSEOUT"


class TestTenantUniqueness:
    def test_duplicate_lod_requirement_and_partner_name_rejected(self, api):
        """PRD §3.1: "At most one requirement may exist per combination of
        `project_id`, `discipline`, and `phase`; a duplicate registration is
        rejected with `ERR_DUPLICATE_LOD_REQUIREMENT`."
        PRD §3.1: "Company names are unique within a project — a repeated
        `company_name` is rejected with `ERR_DUPLICATE_TRADE_PARTNER`."

        Design: Corner/validations/duplicate_lod_requirement_and_partner_name_rejected
        """
        project = create_project("V6")
        create_lod_requirement(project["id"], discipline="STRUCTURAL",
                               phase="SCHEMATIC_DESIGN", min_lod=300)
        create_partner(project["id"], company_name="StructCo")

        dup_req = api.create_lod_requirement(
            project["id"],
            create_lod_requirement_payload(discipline="STRUCTURAL",
                                           phase="SCHEMATIC_DESIGN",
                                           min_lod=200,
                                           clearance_requirement_mm=10.0),
            VDC)
        validate_error(dup_req, ApiErrorId.ERR_DUPLICATE_LOD_REQUIREMENT)

        dup_partner = api.create_trade_partner(
            project["id"],
            create_trade_partner_payload(company_name="StructCo",
                                         discipline="ELECTRICAL",
                                         hourly_rate_cents=9000,
                                         coordination_budget_hours=10.0,
                                         software_platform="TEKLA"),
            VDC)
        validate_error(dup_partner, ApiErrorId.ERR_DUPLICATE_TRADE_PARTNER)


class TestAuthHeaders:
    def test_auth_missing_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying an empty
        value in either, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."
        PRD §2.8: "every request passes through twelve validation layers in a
        fixed order and is rejected at the first layer it fails. First, the
        identity headers of §2.1."

        Design: Corner/validations/auth_missing_headers_rejected
        """
        # Even an unknown resource id must not be reached: identity headers
        # are layer one, existence only layer four.
        resp = api.get_project(NON_EXISTENT_UUID, headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestRoleAuthorization:
    def test_rbac_exclusive_operations_denied_to_other_roles(self, api):
        """PRD §2.1: "Each mutating operation admits exactly one role,
        enumerated per endpoint in §4; a caller whose role is not admitted is
        rejected with `ERR_UNAUTHORIZED_ROLE`."
        PRD §2.8: "Second, role authorization." (evaluated before "Fourth,
        existence of path and body references")

        Design: Corner/rbac/rbac_exclusive_operations_denied_to_other_roles
        """
        project = create_project("RB1")

        # Coordinator cannot onboard partners (VDCManager-only, PRD §4).
        r1 = api.create_trade_partner(
            project["id"],
            create_trade_partner_payload(company_name="X",
                                         hourly_rate_cents=1,
                                         coordination_budget_hours=1.0),
            COORD)
        validate_error(r1, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

        # Coordinator cannot drive the logical clock (VDCManager-only).
        r2 = api.set_clock("2026-08-02T00:00:00Z", COORD)
        validate_error(r2, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

        # A trade author cannot accept models (BIMCoordinator-only) — role
        # denial fires even for a non-existent model id.
        r3 = api.accept_trade_model(NON_EXISTENT_UUID,
                                    build_user_headers(NON_EXISTENT_UUID,
                                                       "TradeModelAuthor"))
        validate_error(r3, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

        # VDCManager cannot sign sign-offs (LeadEngineer-only).
        r4 = api.sign_signoff(NON_EXISTENT_UUID, VDC)
        validate_error(r4, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

        # Coordinator cannot respond to handovers (FacilitiesManager-only).
        r5 = api.respond_handover_package(NON_EXISTENT_UUID,
                                          {"decision": "ACCEPT"}, COORD)
        validate_error(r5, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_ownership_model_submit_by_other_partner_rejected(self, api):
        """PRD §2.1: "ownership checks on any resource that references a trade
        partner — a model's `trade_partner_id`, a clash's
        `assigned_trade_partner_id`, an as-built's partner, a package's
        `requesting_partner_id` — compare that foreign-key field to
        `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_OWNERSHIP`."
        PRD §3.2: "Ownership is enforced: the submitter's `X-User-ID` must
        equal the revision's `trade_partner_id`."

        Design: Corner/rbac/ownership_model_submit_by_other_partner_rejected
        """
        project = create_project("RB2")
        p1 = create_partner(project["id"], company_name="StructCo")
        p2 = create_partner(project["id"], company_name="OtherCo",
                            discipline="ELECTRICAL", hourly_rate_cents=9000,
                            coordination_budget_hours=40.0,
                            software_platform="IFC_ONLY")
        model = create_model(project["id"], p1["id"], life_safety_elements=1,
                             life_safety_compliant=1, envelope_elements=0,
                             envelope_compliant=0, finish_elements=0,
                             finish_compliant=0)

        resp = api.submit_trade_model(model["id"],
                                      make_trade_model_author_headers(p2["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
        assert get_model(model["id"])["status"] == "DRAFT"


class TestErrorEnvelope:
    def test_error_envelope_shape_on_business_rejection(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`." and "The `error_id` is
        a unique, machine-readable string that identifies the specific error."
        PRD §4: advance-phase admits only VDCManager.

        Design: Corner/endpoints/error_envelope_shape_on_business_rejection
        """
        project = create_project("EP2")
        resp = api.advance_phase(project["id"], COORD)
        body = resp.json()
        assert resp.status_code == 403
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_UNAUTHORIZED_ROLE"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]
        meta = body["meta"]
        assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"]
        assert is_iso8601_timestamp(meta.get("api_request_timestamp", ""))


class TestNotFound:
    def test_not_found_errors_on_unknown_ids(self, api):
        """PRD §2.8: "The request is rejected with the not-found error of the
        first identifier that fails to resolve — one of
        `ERR_PROJECT_NOT_FOUND`, `ERR_TRADE_PARTNER_NOT_FOUND`,
        `ERR_TRADE_MODEL_NOT_FOUND`, `ERR_FEDERATED_MODEL_NOT_FOUND`,
        `ERR_CLASH_RUN_NOT_FOUND`, `ERR_CLASH_ISSUE_NOT_FOUND`,
        `ERR_MEETING_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`,
        `ERR_PACKAGE_NOT_FOUND`, `ERR_SIGNOFF_NOT_FOUND`,
        `ERR_AS_BUILT_NOT_FOUND`, `ERR_TAKEOFF_NOT_FOUND`, or
        `ERR_HANDOVER_NOT_FOUND`."

        Design: Corner/entities/not_found_errors_on_unknown_ids
        """
        create_project("E8")

        r1 = api.get_project(NON_EXISTENT_UUID, VDC)
        validate_error(r1, ApiErrorId.ERR_PROJECT_NOT_FOUND)

        r2 = api.get_trade_model(NON_EXISTENT_UUID, VDC)
        validate_error(r2, ApiErrorId.ERR_TRADE_MODEL_NOT_FOUND)

        r3 = api.sign_signoff(NON_EXISTENT_UUID, ENG)
        validate_error(r3, ApiErrorId.ERR_SIGNOFF_NOT_FOUND)

        r4 = api.transmit_handover_package(NON_EXISTENT_UUID, COORD)
        validate_error(r4, ApiErrorId.ERR_HANDOVER_NOT_FOUND)

        # Nested create validates the project id first (left-to-right).
        r5 = api.create_trade_partner(
            NON_EXISTENT_UUID,
            create_trade_partner_payload(company_name="X",
                                         hourly_rate_cents=1,
                                         coordination_budget_hours=1.0),
            VDC)
        validate_error(r5, ApiErrorId.ERR_PROJECT_NOT_FOUND)

    def test_not_found_errors_on_action_paths(self, api):
        """PRD §2.8: "Requests that target nested resources resolve path
        identifiers strictly left to right: the project first, then each
        nested resource in turn. The request is rejected with the not-found
        error of the first identifier that fails to resolve"

        Design: Corner/entities/not_found_errors_on_action_paths
        """
        create_project("E9")

        r1 = api.start_clash_run(NON_EXISTENT_UUID, COORD)
        validate_error(r1, ApiErrorId.ERR_CLASH_RUN_NOT_FOUND)

        # Assign validates the clash path id before the body partner id —
        # the partner reference belongs to the clash's project, which cannot
        # even be scoped until the clash itself resolves.
        r2 = api.assign_clash(NON_EXISTENT_UUID,
                              {"trade_partner_id": NON_EXISTENT_UUID}, COORD)
        validate_error(r2, ApiErrorId.ERR_CLASH_ISSUE_NOT_FOUND)

        r3 = api.start_meeting(NON_EXISTENT_UUID, COORD)
        validate_error(r3, ApiErrorId.ERR_MEETING_NOT_FOUND)

        r4 = api.waive_commitment(NON_EXISTENT_UUID, COORD)
        validate_error(r4, ApiErrorId.ERR_COMMITMENT_NOT_FOUND)

        # Package release is ownership-gated (PRD §2.1, layer three); with a
        # non-existent package there is no requesting_partner_id to compare,
        # so a 404 is the natural reading — but an implementation that orders
        # the ownership layer strictly first may surface 403 instead.
        r5 = api.release_fabrication_package(
            NON_EXISTENT_UUID, build_user_headers(NON_EXISTENT_UUID,
                                                  "FabricationLead"))
        validate_error_is_one_of(
            r5, [ApiErrorId.ERR_PACKAGE_NOT_FOUND,
                 ApiErrorId.ERR_FORBIDDEN_OWNERSHIP])

        r6 = api.verify_as_built_model(NON_EXISTENT_UUID,
                                       {"verification_deviation_mm": 1.0}, VDC)
        validate_error(r6, ApiErrorId.ERR_AS_BUILT_NOT_FOUND)

        r7 = api.approve_quantity_takeoff(NON_EXISTENT_UUID, VDC)
        validate_error(r7, ApiErrorId.ERR_TAKEOFF_NOT_FOUND)

        r8 = api.freeze_federated_model(NON_EXISTENT_UUID, VDC)
        validate_error(r8, ApiErrorId.ERR_FEDERATED_MODEL_NOT_FOUND)

    def test_existence_precedes_state_on_action_paths(self, api):
        """PRD §2.8: "Beyond existence, every request passes through twelve
        validation layers in a fixed order and is rejected at the first layer
        it fails."
        PRD §2.8: "Fourth, existence of path and body references, as above."
        PRD §2.8: "Seventh, from-state legality — the target resource's
        current status must permit the requested transition, covering phase
        advancement, model submit, accept, and reject, assembly freeze,
        unfreeze, and release, run start and completion, clash assign,
        resolve, verify, and reopen, meeting start and adjourn, commitment
        waiver, package submit-for-signoff, release, and void, sign-off sign
        and decline, as-built submit and verify, takeoff approval, and
        handover mark-ready, transmit, and respond."

        Design: Corner/validations/existence_precedes_state_on_action_paths
        """
        create_project("V2")
        # Accept on a non-existent model: 404 existence, not the state error.
        resp = api.accept_trade_model(NON_EXISTENT_UUID, COORD)
        validate_error(resp, ApiErrorId.ERR_TRADE_MODEL_NOT_FOUND)
