"""Bootstrap, member creation/reads, and the member suspend/reinstate cycle.

Covers co-op bootstrap counters, member creation defaults, request-shape and
existence errors, the paginated member roster, activation semantics, and the
ACTIVE <-> SUSPENDED cycle with its enrollment cascade.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    is_valid_uuid,
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    bootstrap_coop,
    create_pending_member,
    create_active_member,
    create_member_payload,
    create_onboarded_supplier,
    create_open_program,
    enroll_member,
    assert_coop,
    assert_member,
)


class TestBootstrap:
    def test_bootstrap_creates_singleton_with_zero_counters(self, api, admin_headers):
        """PRD §3.1: "The singleton `Coop` comes into existence with
        `current_quarter_index` at 0, `pool_reserve_cents` at 0, and
        `retained_revenue_cents` at 0, and quarter 0 is immediately open for
        business."
        PRD §2.4: "`id` is a server-minted UUID with no type prefix."

        Design: Corner/entities/coop_bootstrap_creates_singleton_with_zero_counters
        """
        resp = api.bootstrap({"name": "Init"}, admin_headers)
        coop = validate_success(resp, 201)
        assert_coop(coop)
        assert coop["current_quarter_index"] == 0
        assert coop["pool_reserve_cents"] == 0
        assert coop["retained_revenue_cents"] == 0
        assert is_valid_uuid(coop["id"]), "Coop.id must be a UUID with no type prefix"


class TestMemberCreation:
    def test_member_create_returns_pending_with_defaults(self, api, admin_headers):
        """PRD §3.2: "The member begins life in `PENDING` status, unable to
        participate in anything, and the roster can be listed with filters on
        `status` and `commitment_level`."
        PRD §3.2 (of the three computed counters): "All three start at 0."

        Design: Corner/entities/member_create_returns_pending_with_defaults
        """
        bootstrap_coop()
        resp = api.create_member(
            {"legal_name": "NewMember", "commitment_level": "BUILDER"}, admin_headers
        )
        member = validate_success(resp, 201)
        assert_member(member)
        assert member["status"] == "PENDING"
        assert member["commitment_level"] == "BUILDER"
        assert member["legal_name"] == "NewMember"
        assert member["lifetime_pass_through_cents"] == 0
        assert member["lifetime_clawback_cents"] == 0
        assert member["prior_audit_findings_count"] == 0

    def test_member_create_missing_required_field_returns_invalid_request(
        self, api, admin_headers
    ):
        """PRD §3.2: "A `CoopAdmin` enrolls a new member retailer by supplying
        its `legal_name` and a `commitment_level` of `BUILDER`, `STANDARD`, or
        `PLATINUM`".
        PRD §2.9: "any request whose body fails schema validation — a missing
        required field, a value of the wrong type, or a negative amount where
        a positive one is required — is rejected with `ERR_INVALID_REQUEST`
        (HTTP 400)."

        Design: Corner/entities/member_create_missing_required_field_returns_invalid_request
        """
        bootstrap_coop()
        resp = api.create_member({"commitment_level": "STANDARD"}, admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_member_get_nonexistent_returns_not_found(self, api, admin_headers):
        """PRD §2.10: "Path-templated ids are validated left to right — the
        parent must exist before the child beneath it is examined — and the
        first id that fails to resolve yields `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/member_get_nonexistent_returns_not_found
        """
        bootstrap_coop()
        resp = api.get_member(NON_EXISTENT_UUID, admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_member_list_returns_paginated_array_with_envelope(
        self, api, admin_headers
    ):
        """PRD §2.3: "The `meta` object of every list response carries the
        pagination fields `limit`, `offset`, `total_count`, and `has_more`, so
        a client can always tell how many records exist in total and whether
        further pages remain."
        PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."

        Design: Corner/entities/member_list_returns_paginated_array_with_envelope
        """
        bootstrap_coop()
        create_pending_member("M1", "STANDARD")
        create_pending_member("M2", "PLATINUM")
        resp = api.list_members(admin_headers)
        data, meta = validate_paginated(resp)
        body = resp.json()
        assert isinstance(meta["api_request_id"], str)
        assert isinstance(meta["api_request_timestamp"], str)
        assert body["response_type"] == "array"
        for key in ("limit", "offset", "total_count", "has_more"):
            assert key in meta, f"pagination key {key} missing from meta"
        assert meta["total_count"] == 2
        assert len(data) == 2


class TestMemberActivation:
    def test_member_activate_from_pending_succeeds(self, api, admin_headers):
        """PRD §3.2: "Activation moves the member from `PENDING` to `ACTIVE`;
        attempting it on a member in any other state fails with
        `ERR_INVALID_STATE` (HTTP 409). Activation stamps
        `enrolled_quarter_index` with the co-op's current quarter and
        increments the member's `version`."

        Design: Corner/state_machines/member_activate_from_pending_succeeds
        """
        bootstrap_coop()
        member = create_pending_member()
        resp = api.activate_member(member["id"], admin_headers)
        activated = validate_success(resp, 200)
        assert activated["status"] == "ACTIVE"
        assert activated["enrolled_quarter_index"] == 0

    def test_member_activate_twice_returns_invalid_state(self, api, admin_headers):
        """PRD §3.2: "Activation moves the member from `PENDING` to `ACTIVE`;
        attempting it on a member in any other state fails with
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/member_activate_twice_returns_invalid_state
        """
        bootstrap_coop()
        member = create_active_member()
        resp = api.activate_member(member["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestMemberSuspendReinstateCycle:
    def test_suspend_reinstate_cycle_restores_member_and_enrollment(
        self, api, admin_headers
    ):
        """PRD §3.2: "Suspension moves an `ACTIVE` member to `SUSPENDED` —
        again, any other source state draws `ERR_INVALID_STATE` — and the
        suspension cascades: every one of the member's program enrollments
        currently in `ACTIVE` status moves to `SUSPENDED` alongside it, each
        enrollment's `version` incrementing as it flips. Reinstatement
        reverses the journey, moving a `SUSPENDED` member back to `ACTIVE`
        and flipping each of its `SUSPENDED` enrollments back to `ACTIVE`".

        Two full suspend+reinstate cycles must leave both the member and its
        enrollment ACTIVE.

        Design: Difficulty/non_linear_state_machine/member_suspend_reinstate_cycle
        """
        scenario_member = create_active_member  # readability alias
        bootstrap_coop()
        member = scenario_member(commitment_level="PLATINUM")
        supplier = create_onboarded_supplier()
        program = create_open_program(
            supplier,
            program_code="P-SUSP",
            tier_schedule=[{"min_qty": 0, "rate_bps": 100}],
        )
        enrollment = enroll_member(member, program)

        for _ in range(2):
            suspended = validate_success(
                api.suspend_member(member["id"], admin_headers), 200
            )
            assert suspended["status"] == "SUSPENDED"
            mid_cycle_enrollment = get_success_data(
                api.get_enrollment(enrollment["id"], admin_headers)
            )
            assert mid_cycle_enrollment["status"] == "SUSPENDED"
            reinstated = validate_success(
                api.reinstate_member(member["id"], admin_headers), 200
            )
            assert reinstated["status"] == "ACTIVE"

        final_member = get_success_data(api.get_member(member["id"], admin_headers))
        final_enrollment = get_success_data(
            api.get_enrollment(enrollment["id"], admin_headers)
        )
        assert final_member["status"] == "ACTIVE"
        assert final_enrollment["status"] == "ACTIVE"

    def test_suspend_reinstate_cycle_increments_versions_on_every_mutation(
        self, api, admin_headers
    ):
        """PRD §2.4: "`version` is an integer that increments by one on every
        mutation of the entity, including mutations driven by cascades from
        another entity's transition."
        PRD §3.2: "the suspension cascades: every one of the member's program
        enrollments currently in `ACTIVE` status moves to `SUSPENDED`
        alongside it, each enrollment's `version` incrementing as it flips."

        After create + activate + 2x(suspend+reinstate), the member's version
        has advanced by exactly 5 from its post-creation value, and the
        enrollment's by exactly 4 (one per cascade) from its own.

        Design: Difficulty/non_linear_state_machine/member_suspend_reinstate_cycle
        """
        bootstrap_coop()
        member = create_pending_member(commitment_level="PLATINUM")
        member_v0 = member["version"]
        supplier = create_onboarded_supplier()
        program = create_open_program(
            supplier,
            program_code="P-SUSV",
            tier_schedule=[{"min_qty": 0, "rate_bps": 100}],
        )
        enrollment = enroll_member(
            get_success_data(api.activate_member(member["id"], admin_headers)),
            program,
        )
        enrollment_v0 = enrollment["version"]

        for _ in range(2):
            api.suspend_member(member["id"], admin_headers)
            api.reinstate_member(member["id"], admin_headers)

        final_member = get_success_data(api.get_member(member["id"], admin_headers))
        final_enrollment = get_success_data(
            api.get_enrollment(enrollment["id"], admin_headers)
        )
        # create(v0) -> activate -> suspend -> reinstate -> suspend -> reinstate
        assert final_member["version"] == member_v0 + 5, (
            f"member version should advance by 5 (activate + 2 cycles), got "
            f"{final_member['version']} from {member_v0}"
        )
        # enrollment mutated once per cascade leg: 2 suspends + 2 reinstates
        assert final_enrollment["version"] == enrollment_v0 + 4, (
            f"enrollment version should advance by 4 (cascades), got "
            f"{final_enrollment['version']} from {enrollment_v0}"
        )
