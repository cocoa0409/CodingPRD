"""RBAC, segregation of duties, auth context, and optimistic concurrency."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    accept_assessment,
    create_assessment,
    create_business_owner,
    create_change,
    create_change_payload,
    create_control,
    create_mapping,
    create_obligation,
    create_policy_update_payload,
    create_triaged_change,
    get_change,
    get_control_now,
    get_register,
    make_business_owner_headers,
    make_manager_headers,
    make_officer_headers,
    make_secretary_headers,
    start_assessment,
    submit_assessment,
    validate_error,
    validate_paginated,
    validate_success,
    MANAGER_1,
    OFFICER_A,
    OFFICER_B,
    SECRETARY_1,
    api_client,
)


class TestAuthContext:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request whose headers are missing, or whose `X-User-Role`
        value is not one of these five declared roles, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/val_missing_auth_headers_rejected
        """
        resp = api.list_regulatory_changes(headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_role_beats_existence_on_triage(self, api):
        """PRD §2.10: "When a request would fail several checks at once, the
        checks are evaluated in a fixed priority order and the earliest failing
        check determines the response, so an earlier failure masks later ones".
        PRD §2.10: "Priority 2 — authorization: a caller whose role is not
        admitted by the endpoint yields `ERR_UNAUTHORIZED_ROLE` (403)".
        PRD §2.10: "Priority 3 — existence: path identifiers are validated
        left-to-right, then foreign keys carried in the body
        (`regulatory_change_id`, `business_owner_id`, `obligation_id`,
        `control_id`, `gap_analysis_id`, `implementation_plan_id`,
        `supersedes_change_id`); any miss yields `ERR_NOT_FOUND` (404)".

        Design: Corner/validations/val_role_beats_existence_on_triage
        """
        owner = create_business_owner()
        resp = api.triage_regulatory_change(
            NON_EXISTENT_UUID,
            {"verdict": "APPLICABLE", "rationale": "r"},
            make_business_owner_headers(owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_existence_beats_state_on_triage(self, api, officer_a_headers):
        """PRD §2.10: "Priority 3 — existence: path identifiers are validated
        left-to-right, then foreign keys carried in the body
        (`regulatory_change_id`, `business_owner_id`, `obligation_id`,
        `control_id`, `gap_analysis_id`, `implementation_plan_id`,
        `supersedes_change_id`); any miss yields `ERR_NOT_FOUND` (404)."
        PRD §2.10: "Priority 4 — state-machine preconditions of the attempted
        transition, yielding the 409 state family".

        Design: Corner/validations/val_existence_beats_state_on_triage
        """
        resp = api.triage_regulatory_change(
            NON_EXISTENT_UUID, {"verdict": "APPLICABLE", "rationale": "r"}, officer_a_headers
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestRoleDenial:
    def test_business_owner_cannot_triage(self, api, officer_a_headers):
        """PRD §2.1: "Each endpoint admits a declared set of roles; a caller whose
        role is not in that set is rejected with `ERR_UNAUTHORIZED_ROLE`
        (HTTP 403)."
        PRD §4: "| POST | `/compliance/regulatory-changes/{id}/triage` | Triage a
        pending change (APPLICABLE / NOT_APPLICABLE) | ComplianceOfficer |".

        Design: Corner/rbac/rbac_business_owner_cannot_triage
        """
        owner = create_business_owner()
        change = create_change(citation="RB-1")
        resp = api.triage_regulatory_change(
            change["id"], {"verdict": "APPLICABLE", "rationale": "r"},
            make_business_owner_headers(owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        assert get_change(change["id"])["status"] == "PENDING_TRIAGE"

    def test_officer_cannot_accept_assessment(self, api, officer_a_headers):
        """PRD §2.1: "Each endpoint admits a declared set of roles; a caller whose
        role is not in that set is rejected with `ERR_UNAUTHORIZED_ROLE`
        (HTTP 403)."
        PRD §4: "| POST | `/compliance/impact-assessments/{id}/accept` | Accept a
        submitted assessment | ComplianceManager |".

        Design: Corner/rbac/rbac_officer_cannot_accept_assessment
        """
        owner = create_business_owner()
        change = create_triaged_change(citation="RB-2")
        assessment = create_assessment(change, owner["id"])
        start_assessment(assessment["id"], owner["id"])
        submit_assessment(assessment["id"], owner["id"], likelihood_score=2, severity_score=2)
        resp = api.accept_impact_assessment(assessment["id"], officer_a_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        data = validate_success(api.get_impact_assessment(assessment["id"], officer_a_headers))
        assert data["status"] == "SUBMITTED"

    def test_secretary_cannot_publish_register(self, api, secretary_1_headers):
        """PRD §2.1: "Each endpoint admits a declared set of roles; a caller whose
        role is not in that set is rejected with `ERR_UNAUTHORIZED_ROLE`
        (HTTP 403)."
        PRD §4: "| POST | `/compliance/obligation-register/publish` | Publish a
        new register version snapshotting all ACTIVE obligations (OCC on the
        register) | ComplianceOfficer |".

        Design: Corner/rbac/rbac_secretary_cannot_publish_register
        """
        change = create_triaged_change(citation="RB-3")
        create_obligation(change["id"], obligation_code="OBL-RB-3", criticality="LOW")
        register = get_register()
        resp = api.publish_obligation_register(
            {"expected_register_version": register["version"]}, secretary_1_headers
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        _versions, meta = validate_paginated(
            api.list_obligation_register_versions(make_officer_headers(OFFICER_A))
        )
        assert meta["total_count"] == 0, "No register version created"

    def test_platform_admin_cannot_create_change(self, api, admin_1_headers):
        """PRD §2.1: "A `PlatformAdmin` operates the logical clock and verifies
        the audit chain."
        PRD §2.1: "Each endpoint admits a declared set of roles; a caller whose
        role is not in that set is rejected with `ERR_UNAUTHORIZED_ROLE`
        (HTTP 403)."

        Design: Corner/rbac/rbac_platform_admin_cannot_create_change
        """
        resp = api.create_regulatory_change(create_change_payload(citation="RB-4"), admin_1_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestSegregationOfDuties:
    def test_triage_own_change_rejected(self, api, officer_a_headers, officer_b_headers):
        """PRD §2.8: "The officer who triages or retriages a regulatory change
        must not be the officer who ingested it (the change's
        `created_by_user_id`)."
        PRD §2.8: "Any violation of these three separations is rejected with
        `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403)."

        Design: Corner/rbac/sod_triage_own_change_rejected
        """
        change = create_change(citation="SD-1")
        resp = api.triage_regulatory_change(
            change["id"], {"verdict": "APPLICABLE", "rationale": "self-triage"}, officer_a_headers
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)
        resp = api.triage_regulatory_change(
            change["id"], {"verdict": "APPLICABLE", "rationale": "peer triage"}, officer_b_headers
        )
        assert validate_success(resp, 200)["status"] == "TRIAGED_APPLICABLE"

    def test_mapping_approve_own_rejected(self, api, officer_a_headers, officer_b_headers):
        """PRD §2.8: "The officer who approves an obligation–control mapping must
        not be the officer who proposed it (`created_by_user_id` on the mapping
        versus the actor recorded as `approved_by_user_id`)."

        Design: Corner/rbac/sod_mapping_approve_own_rejected
        """
        change = create_triaged_change(citation="SD-2")
        obl = create_obligation(change["id"], obligation_code="OBL-SD-2", criticality="LOW")
        ctl = create_control(control_code="CTL-SD-2")
        mapping = create_mapping(obl["id"], ctl["id"], coverage_weight=3, creator=OFFICER_A)

        resp = api.approve_mapping(mapping["id"], officer_a_headers)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)
        resp = api.approve_mapping(mapping["id"], officer_b_headers)
        assert validate_success(resp, 200)["status"] == "APPROVED"

    def test_policy_approve_own_draft_rejected(self, api):
        """PRD §2.8: "The manager who approves a policy update must not be the
        officer who drafted it (`drafted_by_user_id` versus the actor recorded
        as `approved_by_user_id`)."

        Design: Corner/rbac/sod_policy_approve_own_draft_rejected
        """
        user_x_officer = make_officer_headers("user-x")
        ctl = create_control(control_code="CTL-SD-3")
        resp = api.create_policy_update(
            create_policy_update_payload(control_id=ctl["id"]), user_x_officer
        )
        update = validate_success(resp, 201)
        api.submit_policy_update(update["id"], user_x_officer)

        same_person_as_manager = make_manager_headers("user-x")
        resp = api.approve_policy_update(
            update["id"], {"expected_control_version": ctl["version"]}, same_person_as_manager
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)
        resp = api.approve_policy_update(
            update["id"], {"expected_control_version": ctl["version"]}, make_manager_headers(MANAGER_1)
        )
        approved = validate_success(resp, 200)
        assert approved["status"] == "APPROVED"
        assert approved["new_policy_version"] == 2, "policy_version 1 + 1"


class TestOptimisticConcurrency:
    def test_assessment_create_stale_change_version(self, api, officer_a_headers):
        """PRD §2.7: "Creating an impact assessment requires the request to carry
        `expected_regulatory_change_version`, the caller's last-observed `version`
        of the target regulatory change. If the change's current `version` has
        advanced beyond that value — for example because another officer triaged
        it again or assigned a different owner after the caller last read it —
        the create is rejected with `ERR_STALE_CHANGE_VERSION` (HTTP 412)."
        PRD §3.4: "Creation automatically supersedes any prior assessment of the
        same change that is still non-terminal — standing in `ASSIGNED`,
        `IN_PROGRESS`, `RETURNED`, or `SUBMITTED` — moving it to `SUPERSEDED` and
        pointing the new record's `supersedes_assessment_id` at it".

        Design: Corner/cross_cutting_layers/occ_assessment_create_stale_change_version
        """
        owner = create_business_owner()
        change = create_triaged_change(citation="OC-1", severity_hint="LOW")
        stale_version = change["version"]
        first = create_assessment(change, owner["id"], due_date="2026-08-10T00:00:00Z")

        resp = api.create_impact_assessment(
            {
                "regulatory_change_id": change["id"],
                "business_owner_id": owner["id"],
                "due_date": "2026-08-12T00:00:00Z",
                "expected_regulatory_change_version": stale_version,
            },
            officer_a_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_CHANGE_VERSION)

        fresh = validate_success(api.get_regulatory_change(change["id"], officer_a_headers))
        resp = api.create_impact_assessment(
            {
                "regulatory_change_id": change["id"],
                "business_owner_id": owner["id"],
                "due_date": "2026-08-12T00:00:00Z",
                "expected_regulatory_change_version": fresh["version"],
            },
            officer_a_headers,
        )
        second = validate_success(resp, 201)
        assert second["supersedes_assessment_id"] == first["id"]
        old = validate_success(api.get_impact_assessment(first["id"], officer_a_headers))
        assert old["status"] == "SUPERSEDED"

    def test_register_publish_stale_version(self, api, officer_a_headers):
        """PRD §2.7: "Publishing a new obligation register version requires
        `expected_register_version` equal to the register's current `version`; a
        stale value is rejected with `ERR_STALE_REGISTER_VERSION` (HTTP 412)."
        PRD §3.2: "Publishing then advances the register's
        `current_version_number` by one and increments the register's `version`
        by one."

        Design: Corner/cross_cutting_layers/occ_register_publish_stale_version
        """
        change = create_triaged_change(citation="OC-2")
        create_obligation(change["id"], obligation_code="OBL-OC-2", criticality="LOW")
        register = get_register()
        first = api.publish_obligation_register(
            {"expected_register_version": register["version"]}, officer_a_headers
        )
        assert validate_success(first, 201)["version_number"] == 1

        stale = api.publish_obligation_register(
            {"expected_register_version": register["version"]}, officer_a_headers
        )
        validate_error(stale, ApiErrorId.ERR_STALE_REGISTER_VERSION)
        after = get_register()
        assert after["current_version_number"] == 1
        assert after["version"] == register["version"] + 1, "Register advanced exactly once"

    def test_policy_approve_stale_control_version(self, api, manager_1_headers):
        """PRD §2.7: "Approving a policy update requires `expected_control_version`
        equal to the target control's current `version`; a stale value is
        rejected with `ERR_STALE_CONTROL_VERSION` (HTTP 412)."
        PRD §3.7: "A successful approval snapshots `new_policy_version` as the
        control's `policy_version` plus one, stamps `approved_by_user_id`, and
        increments the control's `version` by one."

        Design: Corner/cross_cutting_layers/occ_policy_approve_stale_control_version
        """
        ctl = create_control(control_code="CTL-OC-3")
        resp = api.create_policy_update(
            create_policy_update_payload(control_id=ctl["id"], title="A", change_summary="a"),
            make_officer_headers(OFFICER_A),
        )
        update_a = validate_success(resp, 201)
        api.submit_policy_update(update_a["id"], make_officer_headers(OFFICER_A))
        resp = api.create_policy_update(
            create_policy_update_payload(
                control_id=ctl["id"], title="B", change_summary="b",
                effective_date="2026-09-01T00:00:00Z",
            ),
            make_officer_headers(OFFICER_B),
        )
        update_b = validate_success(resp, 201)
        api.submit_policy_update(update_b["id"], make_officer_headers(OFFICER_B))

        approved_a = validate_success(
            api.approve_policy_update(
                update_a["id"], {"expected_control_version": ctl["version"]}, manager_1_headers
            ),
            200,
        )
        assert approved_a["new_policy_version"] == 2

        stale = api.approve_policy_update(
            update_b["id"], {"expected_control_version": ctl["version"]}, manager_1_headers
        )
        validate_error(stale, ApiErrorId.ERR_STALE_CONTROL_VERSION)

        fresh_version = get_control_now(ctl["id"])["version"]
        approved_b = validate_success(
            api.approve_policy_update(
                update_b["id"], {"expected_control_version": fresh_version}, manager_1_headers
            ),
            200,
        )
        assert approved_b["status"] == "APPROVED"
        assert approved_b["new_policy_version"] == 2, (
            "policy_version only moves on publish, so the snapshot stays 1 + 1"
        )


class TestStateBeatsSod:
    def _approved_mapping(self, code_suffix=""):
        change = create_triaged_change(citation=f"PP-1{code_suffix}")
        obl = create_obligation(change["id"], obligation_code=f"OBL-PP1{code_suffix}", criticality="LOW")
        ctl = create_control(control_code=f"CTL-PP1{code_suffix}")
        mapping = create_mapping(obl["id"], ctl["id"], coverage_weight=3, creator=OFFICER_A)
        approve = api_client.approve_mapping(mapping["id"], make_officer_headers(OFFICER_B))
        assert approve.status_code == 200, f"Setup failed: {approve.text}"
        return mapping

    def test_second_approve_by_creator_reports_state_error(self, api, officer_a_headers):
        """PRD §2.10: "When a request would fail several checks at once, the
        checks are evaluated in a fixed priority order and the earliest failing
        check determines the response, so an earlier failure masks later ones".
        PRD §2.10: "Priority 4 — state-machine preconditions of the attempted
        transition, yielding the 409 state family: `ERR_INVALID_STATE`,
        `ERR_PLAN_NOT_SUBMITTED`, `ERR_PLAN_NOT_COMPLETED`,
        `ERR_PACKAGE_SEALED`, `ERR_CHANGE_NOT_SUPERSEDABLE`."
        PRD §2.10: "Priority 5 — segregation of duties and owner suspension:
        `ERR_SEGREGATION_OF_DUTIES_VIOLATION` or `ERR_OWNER_SUSPENDED`
        (both 403)."

        Design: Difficulty/priority_pair_validation_conflict/pp_state_beats_sod_on_mapping_approve
        """
        mapping = self._approved_mapping()
        resp = api.approve_mapping(mapping["id"], officer_a_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        data = validate_success(api.get_mapping(mapping["id"], officer_a_headers))
        assert data["status"] == "APPROVED"

    def test_second_approve_by_peer_reports_state_error(self, api, officer_b_headers):
        """PRD §2.10: "Priority 4 — state-machine preconditions of the attempted
        transition, yielding the 409 state family: `ERR_INVALID_STATE`,
        `ERR_PLAN_NOT_SUBMITTED`, `ERR_PLAN_NOT_COMPLETED`, `ERR_PACKAGE_SEALED`,
        `ERR_CHANGE_NOT_SUPERSEDABLE`."
        PRD §3.3: "Approval (`PROPOSED` → `APPROVED`) is segregated".

        Design: Difficulty/priority_pair_validation_conflict/pp_state_beats_sod_on_mapping_approve
        """
        mapping = self._approved_mapping("-peer")
        # officer-b approved the first time; approving again violates only the state gate.
        resp = api.approve_mapping(mapping["id"], officer_b_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        data = validate_success(api.get_mapping(mapping["id"], officer_b_headers))
        assert data["status"] == "APPROVED"
