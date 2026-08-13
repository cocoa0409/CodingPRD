"""Auth, RBAC, existence ordering, error envelope, OCC, and sweep idempotence."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_active_school,
    create_active_steward,
    create_box_payload,
    create_sorted_batch,
    create_steward_with_active_box,
    is_iso8601_timestamp,
    make_school_liaison_headers,
    make_steward_headers,
    pin_clock,
    propose_drive,
    register_steward,
    run_sweep,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
HUB = TEST_USERS["hub_headers"]
MOD1 = TEST_USERS["mod1_headers"]


class TestAuthentication:
    def test_auth_missing_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "Endpoints whose authorized-role list includes `Anonymous`
        may be called without either header and are then treated as anonymous
        public calls; every other endpoint rejects a missing or malformed
        header pair, or a role string that is not one of the declared roles,
        with `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/auth_missing_headers_returns_unauthenticated
        """
        # GET /library-network/stewards does not list Anonymous.
        res = api.list_stewards({})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value,
                       expected_status=401)


class TestRoleChecks:
    def test_steward_role_denied_for_module_management(self, api):
        """PRD §2.1: "Role membership alone does not authorize a call: the
        presented role must appear in the endpoint's authorized-role list, and
        a disallowed role is rejected with `ERR_UNAUTHORIZED_ROLE`."
        PRD §3.1: "A `NetworkAdmin` curates the training catalog."

        Design: Corner/validations/steward_role_denied_for_module_management
        """
        pin_clock()
        steward = register_steward(full_name="Role Tester",
                                   email="role@example.org")
        headers = make_steward_headers(steward["id"])

        res1 = api.create_training_module(
            {"code": "HACK", "title": "Hack", "level": 1}, headers
        )
        validate_error(res1, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value,
                       expected_status=403)

        res2 = api.run_map_sweep(headers)
        validate_error(res2, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value,
                       expected_status=403)

    def test_role_check_fires_before_existence(self, api):
        """PRD §2.8: "A request that fails several rules at once must fail
        predictably, so validation runs as an ordered pipeline and the first
        failing stage wins."
        PRD §2.8: "2. **Role and ownership.** The role must be listed for the
        endpoint, role-restricted transition targets are enforced, and
        entity-backed callers must own the target — failures are
        `ERR_UNAUTHORIZED_ROLE` or `ERR_FORBIDDEN_OWNERSHIP` (403).
        3. **Path existence.** Path identifiers resolve left to right with
        entity-specific 404s."

        Design: Corner/rbac/role_check_fires_before_existence
        """
        pin_clock()
        # network-decision is NetworkAdmin-only: a Moderator gets 403 even
        # though the drive id does not exist.
        res1 = api.drive_network_decision(
            "00000000-0000-4000-8000-0000000000ee", "APPROVE", MOD1
        )
        validate_error(res1, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value,
                       expected_status=403)

        # complaint triage is Moderator/NetworkAdmin-only: a HubCoordinator
        # gets 403 even though the complaint id does not exist.
        res2 = api.triage_complaint(
            "00000000-0000-4000-8000-0000000000ff", HUB
        )
        validate_error(res2, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value,
                       expected_status=403)


class TestOwnership:
    def test_patch_other_steward_rejected_forbidden(self, api):
        """PRD §3.1: "Profile upkeep runs through a patch operation that
        accepts an optional `full_name` and an optional `region_code` alongside
        the mandatory `expected_steward_version` described in §2.7; a steward
        may patch only their own record."
        PRD §2.1: "Ownership violations are rejected with
        `ERR_FORBIDDEN_OWNERSHIP`."

        Design: Corner/validations/patch_other_steward_rejected_forbidden
        """
        pin_clock()
        steward_a = register_steward(full_name="Owner A", email="oa@example.org")
        steward_b = register_steward(full_name="Owner B", email="ob@example.org")

        res = api.patch_steward(
            steward_b["id"],
            {"full_name": "Hijacked",
             "expected_steward_version": steward_b["version"]},
            make_steward_headers(steward_a["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP.value,
                       expected_status=403)

        after = validate_success(api.get_steward(steward_b["id"], ADMIN), 200)
        assert after["full_name"] == "Owner B"

    def test_school_liaison_forbidden_for_other_schools_drive(self, api):
        """PRD §2.1: "a `SchoolLiaison` may decide only drives belonging to
        their own school. Ownership violations are rejected with
        `ERR_FORBIDDEN_OWNERSHIP`."
        PRD §3.7: "The school's liaison decides the `school_approval_status` —
        the caller's `X-User-ID` must equal the drive's `school_id` or the
        attempt fails with `ERR_FORBIDDEN_OWNERSHIP`."

        Design: Corner/rbac/school_liaison_forbidden_for_other_schools_drive
        """
        pin_clock()
        steward = create_active_steward(full_name="Liaison Tester",
                                        email="lia@example.org")
        school_a = create_active_school(name="School A")
        school_b = create_active_school(name="School B")
        drive = propose_drive(school_b["id"], steward["id"], goal_books=5)

        # School A's liaison may not decide school B's drive.
        res = api.drive_school_decision(
            drive["id"], "APPROVE", make_school_liaison_headers(school_a["id"])
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP.value,
                       expected_status=403)

        after = validate_success(api.get_drive(drive["id"], ADMIN), 200)
        assert after["status"] == "PROPOSED"
        assert after["school_approval_status"] == "PENDING"


class TestExistenceOrdering:
    def test_existence_checked_before_state(self, api):
        """PRD §2.6: "When an endpoint path contains resource identifiers, the
        server validates their existence left to right and answers with the
        not-found error belonging to the first missing segment."
        PRD §2.6: "A missing path identifier yields HTTP 404."
        PRD §2.8: "3. **Path existence.** Path identifiers resolve left to
        right with entity-specific 404s."

        Design: Corner/validations/existence_checked_before_state
        """
        pin_clock()
        res1 = api.triage_complaint(
            "00000000-0000-4000-8000-0000000000aa", MOD1
        )
        validate_error(res1, ApiErrorId.ERR_COMPLAINT_NOT_FOUND.value,
                       expected_status=404)

        res2 = api.create_inspection(
            "00000000-0000-4000-8000-0000000000bb", {"result": "CONFIRMED"},
            MOD1,
        )
        validate_error(res2, ApiErrorId.ERR_BOX_NOT_FOUND.value,
                       expected_status=404)

    def test_not_found_sweep_returns_entity_specific_404s(self, api):
        """PRD §2.6: "Each entity has its own not-found error:
        `ERR_STEWARD_NOT_FOUND`, `ERR_BOX_NOT_FOUND`, `ERR_SCHOOL_NOT_FOUND`,
        `ERR_DRIVE_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_RUN_NOT_FOUND`,
        `ERR_ALLOCATION_NOT_FOUND`, `ERR_MAINTENANCE_NOT_FOUND`,
        `ERR_COMPLAINT_NOT_FOUND`, and `ERR_MODULE_NOT_FOUND`. A missing path
        identifier yields HTTP 404."

        Design: Corner/errors/not_found_sweep_returns_entity_specific_404s
        """
        pin_clock()
        cases = [
            (api.get_steward("00000000-0000-4000-8000-000000000001", ADMIN),
             ApiErrorId.ERR_STEWARD_NOT_FOUND.value),
            (api.get_box("00000000-0000-4000-8000-000000000002", {}),
             ApiErrorId.ERR_BOX_NOT_FOUND.value),
            (api.get_drive("00000000-0000-4000-8000-000000000003", ADMIN),
             ApiErrorId.ERR_DRIVE_NOT_FOUND.value),
            (api.get_batch("00000000-0000-4000-8000-000000000004", ADMIN),
             ApiErrorId.ERR_BATCH_NOT_FOUND.value),
            (api.get_distribution_run(
                "00000000-0000-4000-8000-000000000005", ADMIN),
             ApiErrorId.ERR_RUN_NOT_FOUND.value),
            (api.get_allocation("00000000-0000-4000-8000-000000000006", ADMIN),
             ApiErrorId.ERR_ALLOCATION_NOT_FOUND.value),
            (api.get_maintenance_request(
                "00000000-0000-4000-8000-000000000007", ADMIN),
             ApiErrorId.ERR_MAINTENANCE_NOT_FOUND.value),
            (api.get_complaint("00000000-0000-4000-8000-000000000008", ADMIN),
             ApiErrorId.ERR_COMPLAINT_NOT_FOUND.value),
            (api.get_training_module(
                "00000000-0000-4000-8000-000000000009", ADMIN),
             ApiErrorId.ERR_MODULE_NOT_FOUND.value),
            (api.get_school("00000000-0000-4000-8000-000000000010", ADMIN),
             ApiErrorId.ERR_SCHOOL_NOT_FOUND.value),
        ]
        for response, expected_error_id in cases:
            validate_error(response, expected_error_id, expected_status=404)


class TestResponseEnvelope:
    def test_response_envelope_shape_for_success_and_error(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error. The `message` provides a human-readable
        explanation of what went wrong."

        Design: Corner/endpoints/response_envelope_shape_for_success_and_error
        """
        pin_clock()
        # Public map listing as anonymous: success envelope with array data.
        ok = api.list_boxes({})
        assert ok.status_code == 200
        body = ok.json()
        assert body["response_type"] == "array"
        assert body["data"] == []
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])

        # Error envelope on a missing box.
        err = api.get_box("00000000-0000-4000-8000-0000000000dd", {})
        validate_error(err, ApiErrorId.ERR_BOX_NOT_FOUND.value,
                       expected_status=404)
        err_body = err.json()
        assert err_body["response_type"] == "error"
        assert isinstance(err_body["data"]["message"], str)
        assert len(err_body["data"]["message"].strip()) > 0


class TestOptimisticConcurrency:
    def test_occ_distribution_run_create_stale_version(self, api):
        """PRD §3.8: "Creating a distribution run for a `SORTED` batch requires
        the `expected_batch_version` of §2.7, and creating the run itself
        advances the batch's `version`, so a second writer holding a stale
        observation is turned away with `ERR_STALE_VERSION`."
        PRD §2.7: "Creating a distribution run for a batch requires
        `expected_batch_version`, carrying the client's last observed `version`
        of that DonationBatch; if the batch's current `version` has moved past
        what the client observed — for instance because another writer has
        already created a run for the same batch — the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_distribution_run_create_stale_version
        """
        pin_clock()
        _steward, _box = create_steward_with_active_box(
            steward_name="OCC Owner", box_name="OCC Box"
        )
        batch, _items = create_sorted_batch(item_count=1)
        observed_version = batch["version"]

        run1 = validate_success(
            api.create_distribution_run(batch["id"], observed_version, HUB),
            201,
        )
        assert run1["status"] == "DRAFT"

        # The first create advanced the batch version: replaying the stale
        # observation is rejected.
        res = api.create_distribution_run(batch["id"], observed_version, HUB)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION.value,
                       expected_status=412)

        run1_after = validate_success(
            api.get_distribution_run(run1["id"], HUB), 200
        )
        assert run1_after["status"] == "DRAFT"

    def test_occ_steward_patch_stale_version(self, api):
        """PRD §2.7: "Updating a steward profile requires
        `expected_steward_version`, carrying the client's last observed
        `version` of that Steward; a mismatch with the steward's current
        `version` — advanced by any profile patch, status transition, or
        cascaded recognition recompute — is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_steward_patch_stale_version
        """
        pin_clock()
        steward = register_steward(full_name="Patch Me",
                                   email="patch@example.org")
        observed_version = steward["version"]

        patched = validate_success(
            api.patch_steward(
                steward["id"],
                {"full_name": "Patched Once",
                 "expected_steward_version": observed_version},
                make_steward_headers(steward["id"]),
            ),
            200,
        )
        assert patched["version"] == observed_version + 1

        res = api.patch_steward(
            steward["id"],
            {"full_name": "Patched Twice",
             "expected_steward_version": observed_version},
            make_steward_headers(steward["id"]),
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION.value,
                       expected_status=412)

        after = validate_success(api.get_steward(steward["id"], ADMIN), 200)
        assert after["full_name"] == "Patched Once"
        assert after["version"] == observed_version + 1


class TestCrossEntityGates:
    def test_suspended_steward_cannot_create_box(self, api):
        """PRD §3.3: "The proposing steward must be `ACTIVE`
        (`ERR_STEWARD_NOT_ACTIVE` otherwise) and below the recognition-tier
        capacity of §3.2."

        Design: Corner/validations/suspended_steward_cannot_create_box
        """
        pin_clock()
        steward = create_active_steward(full_name="Suspended",
                                        email="sus@example.org")
        validate_success(api.suspend_steward(steward["id"], MOD1), 200)

        res = api.create_box(
            create_box_payload(steward["id"], name="Blocked Box"),
            make_steward_headers(steward["id"]),
        )
        validate_error(res, ApiErrorId.ERR_STEWARD_NOT_ACTIVE.value,
                       expected_status=409)


class TestSweepIdempotence:
    def test_sweep_idempotent_without_clock_change(self, api):
        """PRD §3.9: "The sweep is idempotent — a second pass without any
        clock movement changes nothing."
        PRD §3.9: "The sweep answers with a tally of its work:
        `expired_response_count`, `opened_drive_count`, `closed_drive_count`,
        `suspended_box_count`, `decommissioned_box_count`,
        `recycled_item_count`, and `posture_change_count`."

        Design: Corner/cross_cutting_layers/sweep_idempotent_without_clock_change
        """
        pin_clock()
        _steward, box = create_steward_with_active_box(
            steward_name="Idem Owner", box_name="Idem Box"
        )
        pin_clock("2027-01-28T00:00:00Z")
        first = run_sweep()
        assert first["suspended_box_count"] == 1

        # Second sweep with the same clock: every tally is zero.
        second = run_sweep()
        assert second["suspended_box_count"] == 0
        assert second["decommissioned_box_count"] == 0
        assert second["opened_drive_count"] == 0
        assert second["closed_drive_count"] == 0
        assert second["expired_response_count"] == 0
        assert second["recycled_item_count"] == 0
        assert second["posture_change_count"] == 0

        after = validate_success(api.get_box(box["id"], ADMIN), 200)
        assert after["charter_status"] == "SUSPENDED"
